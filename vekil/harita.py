"""Zihin haritası: OpenDelegate'in kalıcı hafızasını (bilgiler tablosu) tarayıcıda 3B bir evren olarak gösterir.

    GET /harita/{token}        -> tek sayfa (static/harita.html; Three.js + bloom, CDN)
    GET /harita/{token}/veri   -> JSON: çekirdek, gruplar (halka düğümleri), kayıtlar, bağlar

Kurallar:
- Token'lı URL: yanlış/eksik token -> 404 (sayfanın varlığı bile belli olmasın). Token .env'deki
  HARITA_TOKEN; yoksa TELEGRAM_BOT_TOKEN'dan HMAC ile türetilir (koda gömülü sır yok, Render'a ekstra
  ayar gerekmez). Karşılaştırma sabit zamanlı. Uygulama access log tutmaz; yine de token'ı log
  satırlarında maskeleyen filtre var (maskele()).
- Neon kotası: kayıtlar hafiza.bilgiler()'in bellekteki önbelleğinden gelir (sadece yazma/silmede
  yenilenir). Harita JSON'u da kayıt listesinin parmak izine göre önbelleklenir; bağ çıkarımı her
  istekte tekrar hesaplanmaz. "Yenile" (yenile=1) DB'yi zorla okur ama en fazla YENILE_ARALIK sn'de bir.
- Bağ çıkarımı: anahtar+değerdeki kelime kökleri (Türkçe küçük harf, 5 harf kök, durak kelimeleri ve
  kayıtların %35'inden fazlasında geçen kökler hariç) üzerinden kosinüs benzerliği; her kayıt için en
  güçlü 3 bağ (eşik BAG_ESIK). Kalabalıkta (30+ kayıt) kişi başı 2, toplam bağ ~ kayıt sayısı kadar.
- Gruplar: kayıt türü (tercih/terim/karar/not). profil_1..profil_11 gibi "ad_sayı" anahtarları en az 3
  taneyse kendi grubu olur (PROFİL).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import re
import time
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger("vekil.harita")

SAYFA_DOSYASI = Path(__file__).with_name("static") / "harita.html"
MUZIK_DOSYASI = Path(__file__).with_name("static") / "muzik.mp3"  # arka plan müziği (Kullanıcının seçimi)
YENILE_ARALIK = 15.0  # sn; zorla DB okuma sınırı
BAG_ESIK = 0.12  # gerçek 25 kayıtta 0.2 -> sadece 4 bağ (5/25 kayıt bağlı); 0.12 + genel kök ayıklama -> 17 anlamlı bağ
BAG_KISI_BASI = 3
BAG_UST_SINIR = 8  # bir kaydın toplam bağı (yumak/kıl yumağı görünümü olmasın)
# Kayıt arttıkça ip sayısı karesel büyümesin: toplam bağ ~ kayıt sayısıyla doğrusal (bütçe), kişi başı sınırlar
# kalabalıkta daralır. En güçlü bağlar kalır; zayıflar zaten göze "kıl" olarak batıyordu.
BAG_KALABALIK = 30        # bu kadar kayıttan sonra sınırlar daralır
BAG_BUTCE_ORAN = 1.1      # toplam bağ <= kayıt * oran
BAG_BUTCE_TABAN = 12

GRUP_BILGI = {  # tür -> (başlık, açıklama)
    "tercih": ("TERCİH", "Nasıl çalışmamı istediği"),
    "terim": ("TERİM", "Öğrendiğim kelimeler"),
    "karar": ("KARAR", "Birlikte verdiğimiz kararlar"),
    "not": ("NOT", "Aklımda tuttuklarım"),
}
_ONEK_BILGI = {"profil": ("PROFİL", "Kullanıcı hakkında"), "ekonomi": ("EKONOMİ", "Para durumu ve hedefler")}

_DURAK = frozenset("""
ve ile için icin bir gibi olan olarak daha çok cok ama fakat değil degil veya yada ise kadar sonra önce once
her hep şey sey şu bu o da de mi mu mı mü ki ne nasıl nasil neden zaman şekilde sekilde oldu olsun olur
vekil kanka bana beni benim sana seni senin onun onu kendi yapar yapma yap etme eder ediyor olmalı
""".split())
_ONEK_DESEN = re.compile(r"^(.+?)[_\-\s]?(\d+)$")


# --------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------

def token() -> str:
    acik = (getattr(config, "HARITA_TOKEN", "") or "").strip()
    if acik:
        return acik
    tohum = (config.ANA_SIR or "").encode("utf-8")
    return hmac.new(tohum, b"vekil-zihin-haritasi-v1", hashlib.sha256).hexdigest()[:32]


def token_dogru(aday: str | None) -> bool:
    beklenen = token()
    return bool(aday) and bool(beklenen) and hmac.compare_digest(str(aday).encode(), beklenen.encode())


def link() -> str:
    taban = (config.WEBHOOK_URL or "").rstrip("/")
    return f"{taban}/harita/{token()}" if taban else ""


def maskele(metin: str) -> str:
    """Log satırlarında token'ı gizler."""
    t = token()
    return metin.replace(t, t[:4] + "…") if t and t in metin else metin


class TokenMaskeleyici(logging.Filter):
    def filter(self, kayit: logging.LogRecord) -> bool:
        t = token()
        if t:
            try:
                mesaj = kayit.getMessage()
            except Exception:  # noqa: BLE001
                return True
            if t in mesaj:
                kayit.msg, kayit.args = maskele(mesaj), ()
        return True


# --------------------------------------------------------------------------
# Veri: gruplar, düğümler, bağlar
# --------------------------------------------------------------------------

def _kucuk(metin: str) -> str:
    return (metin or "").replace("İ", "i").replace("I", "ı").lower()


# Her kayıtta geçebilen genel fiil/zarf kökleri (kullan, iste, sadece, açık...): bunlardan bağ çıkarsa anlamsız olur.
_GENEL_KOK = frozenset("""
kull iste isti sade açık açma prof yapm yapı olsu olma gere değe şeki sorm soru verm alma işle zama dahi önce sonr
şimd hepsi
""".split())


def _kokler(metin: str) -> set[str]:
    """4 harflik kökler (Türkçe ekler atılsın: 'tarayıcı/tarayıcıyı', 'monitör/monitörde' eşleşsin)."""
    kelimeler = re.findall(r"[0-9a-zçğıöşüâîû]+", _kucuk(metin))
    return {k[:4] for k in kelimeler if len(k) >= 4 and k not in _DURAK and not k.isdigit()} - _GENEL_KOK


def _kimlik(tur: str, anahtar: str) -> str:
    return "k" + hashlib.sha1(f"{tur}\x00{anahtar}".encode()).hexdigest()[:10]


def _grupla(kayitlar: list[dict[str, str]]) -> dict[int, str]:
    """kayıt sırası -> grup anahtarı ('tur:not' ya da 'onek:profil')."""
    onekler: dict[str, list[int]] = {}
    for i, k in enumerate(kayitlar):
        m = _ONEK_DESEN.match(_kucuk(k["anahtar"]).strip())
        if m and len(m.group(1)) >= 3:
            onekler.setdefault(m.group(1).strip("_- "), []).append(i)
    grup: dict[int, str] = {i: f"tur:{k['tur']}" for i, k in enumerate(kayitlar)}
    for onek, uyeler in onekler.items():
        if len(uyeler) >= 3:
            for i in uyeler:
                grup[i] = f"onek:{onek}"
    return grup


def baglar_cikar(kokler: list[set[str]]) -> list[tuple[int, int, float]]:
    """Kosinüs benzerliği; çok yaygın kökler (kayıtların %35'inden fazlası) ayırt edici değil, sayılmaz."""
    n = len(kokler)
    if n < 2:
        return []
    sayac: dict[str, int] = {}
    for ks in kokler:
        for k in ks:
            sayac[k] = sayac.get(k, 0) + 1
    yaygin = {k for k, c in sayac.items() if n >= 6 and c / n > 0.35}
    temiz = [ks - yaygin for ks in kokler]
    adaylar: dict[int, list[tuple[float, int]]] = {i: [] for i in range(n)}
    for i in range(n):
        if not temiz[i]:
            continue
        for j in range(i + 1, n):
            if not temiz[j]:
                continue
            ortak = len(temiz[i] & temiz[j])
            if not ortak:
                continue
            w = ortak / math.sqrt(len(temiz[i]) * len(temiz[j]))
            if w >= BAG_ESIK:
                adaylar[i].append((w, j))
                adaylar[j].append((w, i))
    kalabalik = n > BAG_KALABALIK
    kisi_basi = 2 if kalabalik else BAG_KISI_BASI
    ust_sinir = 5 if kalabalik else BAG_UST_SINIR
    butce = max(BAG_BUTCE_TABAN, int(n * BAG_BUTCE_ORAN))
    secilen: dict[tuple[int, int], float] = {}
    for i, liste in adaylar.items():
        for w, j in sorted(liste, reverse=True)[:kisi_basi]:
            a, b = min(i, j), max(i, j)
            secilen[(a, b)] = max(w, secilen.get((a, b), 0.0))
    # Yumak önleme: başkalarının "en iyi 3"ünde çok geçen bir kayıt düzinelerce bağ toplayabilir;
    # en güçlüden başlayarak her kaydın toplam bağı BAG_UST_SINIR'ı geçmesin.
    derece: dict[int, int] = {}
    sonuc = []
    for (a, b), w in sorted(secilen.items(), key=lambda t: -t[1]):
        if len(sonuc) >= butce:
            break
        if derece.get(a, 0) >= ust_sinir or derece.get(b, 0) >= ust_sinir:
            continue
        derece[a] = derece.get(a, 0) + 1
        derece[b] = derece.get(b, 0) + 1
        sonuc.append((a, b, round(w, 3)))
    return sonuc


def veri_olustur(kayitlar: list[dict[str, str]]) -> dict[str, Any]:
    """bilgiler kayıtlarından harita JSON'u."""
    grup_of = _grupla(kayitlar)
    gruplar: dict[str, dict[str, Any]] = {}
    sira = {f"tur:{t}": i for i, t in enumerate(GRUP_BILGI)}
    for i, k in enumerate(kayitlar):
        g = grup_of[i]
        if g not in gruplar:
            tur, ad = g.split(":", 1)
            baslik, aciklama = (GRUP_BILGI.get(ad) if tur == "tur" else _ONEK_BILGI.get(ad)) or (
                _kucuk(ad).replace("i", "İ").replace("ı", "I").upper(), "Kayıt grubu")
            gruplar[g] = {"id": g, "baslik": baslik, "aciklama": aciklama, "sayi": 0,
                          "tur": ad if tur == "tur" else "onek", "sira": sira.get(g, 10 + len(gruplar))}
        gruplar[g]["sayi"] += 1
    dugumler = [
        {"id": _kimlik(k["tur"], k["anahtar"]), "grup": grup_of[i], "tur": k["tur"], "anahtar": k["anahtar"],
         "deger": k["deger"], "tarih": k.get("guncellendi") or ""}
        for i, k in enumerate(kayitlar)
    ]
    kokler = [_kokler(f"{k['anahtar'].replace('_', ' ')} {k['deger']}") for k in kayitlar]
    baglar = [{"a": dugumler[a]["id"], "b": dugumler[b]["id"], "w": w} for a, b, w in baglar_cikar(kokler)]
    return {
        "cekirdek": {"ad": "OPENDELEGATE", "aciklama": "Kalıcı hafıza", "toplam": len(kayitlar)},
        "gruplar": sorted(gruplar.values(), key=lambda g: g["sira"]),
        "dugumler": dugumler,
        "baglar": baglar,
        "olusturuldu": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


class Onbellek:
    """Harita JSON'u: kayıt listesinin parmak izi değişmedikçe yeniden hesaplanmaz."""

    def __init__(self) -> None:
        self.iz: str | None = None
        self.veri: dict[str, Any] | None = None
        self.son_zorla = 0.0

    @staticmethod
    def _iz(kayitlar: list[dict[str, str]]) -> str:
        h = hashlib.sha1()
        for k in kayitlar:
            h.update(f"{k['tur']}\x00{k['anahtar']}\x00{k['deger']}\x00{k.get('guncellendi')}\x01".encode())
        return h.hexdigest()

    def al(self, kayitlar: list[dict[str, str]]) -> dict[str, Any]:
        iz = self._iz(kayitlar)
        if iz != self.iz or self.veri is None:
            self.veri, self.iz = veri_olustur(kayitlar), iz
        return self.veri

    def zorla_izinli(self) -> bool:
        simdi = time.monotonic()
        if simdi - self.son_zorla < YENILE_ARALIK:
            return False
        self.son_zorla = simdi
        return True


GUVENLI_BASLIKLAR = {
    "Cache-Control": "no-store",            # token'lı sayfa/veri ara önbelleklerde kalmasın
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",       # CDN'e giden isteklerde token'lı adres sızmasın
    "X-Content-Type-Options": "nosniff",
}
_sayfa_onbellek: dict[str, tuple[float, str]] = {}


def sayfa() -> str:
    """static/harita.html (bellekte; dosya değişirse yeniden okunur)."""
    mtime = SAYFA_DOSYASI.stat().st_mtime
    kayit = _sayfa_onbellek.get("s")
    if not kayit or kayit[0] != mtime:
        kayit = (mtime, SAYFA_DOSYASI.read_text(encoding="utf-8"))
        _sayfa_onbellek["s"] = kayit
    return kayit[1]
