"""Sesli çıkış: Vekil cevaplarını Türkçe sesli not olarak gönderir + "acil" sesli hatırlatma zinciri.

Motor: edge-tts (Microsoft Edge'in sinir ağı sesleri; ücretsiz, key yok). TEK ses: tr-TR-AhmetNeural (15.11 gece Giuseppe yerine; sadece Türkçe)
(Kullanıcı telefonda duyup her yerde istedi). Ses seçimi yok, sadece mod/hız. Çıktı MP3; Telegram sendVoice MP3'ü sesli not olarak kabul eder
(ffmpeg gerekmez). Sadece Render'da çalışır, PC ayak izi 0.

Modlar (ayarlar 'ses_ayar'): 'kapali' (varsayılan; sadece "sesli oku" deyince), 'sesliye_sesli' (sesli mesaja
sesli cevap), 'hepsi' (her cevap metin + ses). Metin HER ZAMAN da gider: ses olmazsa hiçbir şey kaybolmaz.

Parçalama: cümle sınırından en fazla PARCA_SINIR karakter (~45-60 sn ses); en fazla MAKS_PARCA not, gerisi
"devamı yazılı" der. Markdown/kod/link/emoji sesli okunmaz.

Hata: seslendirme olmazsa metinle devam; "seslendiremedim" notu en fazla HATA_NOT_ARALIK'ta bir (spam yok).

Acil zinciri: 1. sesli not -> 10 dk -> 2. (telefon açıksa ARAMA, olmazsa not) -> 20 dk -> 3. (son) -> "sırada
bekliyor" (yapılacaklara eklenir).
Kullanıcı arada herhangi bir mesaj yazarsa zincir durur. Durum `ayarlar` 'acil_zincir'de; Render yeniden başlasa da
kaldığı yerden devam eder (6 saatten eski adım atlanır).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

import zamanlayici
from zamanlayici import TR

logger = logging.getLogger("ses")

AYAR_ANAHTAR = "ses_ayar"
ZINCIR_ANAHTAR = "acil_zincir"
# Vekil'in TEK, imza sesi (Kullanıcı 15.11 seçti, 6 aday dinledi): çok dilli, doğal, sıradan "asistan sesi" değil.
# Değiştirilemez; sadece mod ve hız ayarlanır.
# 15.11 gece: Giuseppe (çok dilli) telefonda dile kaydı (Azeri/İngilizce okudu); kullanıcı telefonda Ahmet'i duyup
# "her yerde aynı ses olsun" dedi. Artık TEK ses Ahmet: sadece Türkçe, kayma yok.
SES = "tr-TR-AhmetNeural"
TELEFON_SES = SES
VARSAYILAN = {"ses": SES, "mod": "kapali", "hiz": "+0%"}
MODLAR = ("kapali", "sesliye_sesli", "hepsi")
PARCA_SINIR = 700
MAKS_PARCA = 6
SENTEZ_ZAMAN_ASIMI = 40.0
HATA_NOT_ARALIK = timedelta(minutes=30)
ZINCIR_ARALIK = [timedelta(0), timedelta(minutes=10), timedelta(minutes=20)]  # her adımdan önceki bekleme
ZINCIR_ONEK = ["Efendim, acil bir şey var: {m}.", "Efendim, tekrar söylüyorum, acil: {m}.",
               "Efendim, son kez söylüyorum: {m}. Bundan sonra sırada bekleyecek."]
ZINCIR_GECIKME_SINIRI = timedelta(hours=6)
TIK_SN = 20.0

_KOD = re.compile(r"```.*?```", re.S)
_LINK = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def temizle(metin: str) -> str:
    """Sesli okunacak hâle getir: kod bloğu, link, emoji, markdown/HTML işaretleri çıkar."""
    s = _KOD.sub(" (kod kısmını yazılı gönderdim) ", metin or "")
    s = _LINK.sub(" bağlantı ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _EMOJI.sub("", s)
    s = re.sub(r"[`*_#>|~]+", " ", s)
    s = re.sub(r"^\s*[-•·]\s+", "", s, flags=re.M)  # madde işaretleri
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def parcala(metin: str, sinir: int = PARCA_SINIR) -> list[str]:
    """Cümle (yoksa kelime) sınırından en fazla `sinir` karakterlik parçalar."""
    cumleler = [c.strip() for c in re.split(r"(?<=[.!?…:])\s+|\n+", metin) if c.strip()]
    parcalar: list[str] = []
    simdiki = ""
    for c in cumleler:
        while len(c) > sinir:  # tek cümle çok uzunsa kelimeden böl
            kes = c.rfind(" ", 0, sinir)
            kes = kes if kes > sinir // 2 else sinir
            if simdiki:
                parcalar.append(simdiki)
                simdiki = ""
            parcalar.append(c[:kes].strip())
            c = c[kes:].strip()
        if simdiki and len(simdiki) + 1 + len(c) > sinir:
            parcalar.append(simdiki)
            simdiki = c
        else:
            simdiki = f"{simdiki} {c}".strip()
    if simdiki:
        parcalar.append(simdiki)
    return parcalar


# Çok dilli ses dili CÜMLE CÜMLE tahmin ediyor: "Claude'a" görünce cümleyi Fransızca okudu. Ücretsiz servis
# <lang xml:lang='tr-TR'> etiketini kabul etmiyor (ses gelmiyor; 15.11'de denendi). Çare: yabancı kelimeleri
# seslendirmeden önce Türkçe okunuşuyla yaz; cümle Türkçe görünür, terim İngilizce telaffuza yakın çıkar.
OKUNUS = {
    "claude": "Klod", "anthropic": "Entropik", "commit": "komit", "commits": "komitler", "deploy": "diploy",
    "push": "puş", "pushla": "puşla", "pushladım": "puşladım", "github": "Githab", "git": "git", "render": "Rendır",
    "brave": "Breyv", "onedrive": "Vandrayv", "google": "Gugıl", "chrome": "Krom", "python": "Paytın",
    "windows": "Vindovs", "twilio": "Tvilio", "fitness": "fitnes", "email": "imeyl", "mail": "meyl",
    "update": "apdeyt", "cloud": "klaud", "online": "onlayn", "wifi": "vayfay", "bug": "bag", "web": "veb",
    "whatsapp": "Votsap", "youtube": "Yutub", "iphone": "Ayfon", "laptop": "leptop", "mouse": "maus",
    "download": "davnlod", "upload": "aplod", "server": "sörvır", "backup": "bekap", "software": "softver",
    "hardware": "hardver", "code": "kod", "deepseek": "Dipsik", "telegram": "Telegram", "edge": "Ec",
    "neon": "Neon", "ok": "okey", "okay": "okey", "sorry": "sori", "ditto": "Ditto", "kali": "Kali", "linux": "Linuks", "token": "tokın", "prompt": "prompt",
}
_KELIME = re.compile(r"\b([A-Za-z]+)(?!\w)((?:['’][a-zçğıöşü]+)?)", re.I)  # (?!\w): "Bugün"deki "Bug" değil


def turkce_okunus(metin: str) -> str:
    """Bilinen yabancı terimleri Türkçe okunuşuyla değiştirir (ekleri korur: Claude'a -> Klod'a)."""
    def degistir(m: re.Match[str]) -> str:
        karsilik = OKUNUS.get(m.group(1).lower())
        return (karsilik + m.group(2)) if karsilik else m.group(0)

    return _KELIME.sub(degistir, metin)


async def edge_sentez(metin: str, ses: str, hiz: str) -> bytes:
    """edge-tts ile MP3 (gerçek motor; testlerde sahtesi verilir)."""
    import edge_tts  # Render'da requirements.txt'ten; lokal testler sahte motor kullanır

    metin = turkce_okunus(metin)

    parcalar: list[bytes] = []
    async for p in edge_tts.Communicate(metin, ses, rate=hiz).stream():
        if p.get("type") == "audio":
            parcalar.append(p["data"])
    veri = b"".join(parcalar)
    if not veri:
        raise RuntimeError("boş ses")
    return veri


@dataclass
class Ses:
    gonder_ses: Callable[[bytes, str], Awaitable[None]]  # (mp3, başlık)
    gonder_metin: Callable[[str], Awaitable[None]]
    sentez: Callable[[str, str, str], Awaitable[bytes]] = edge_sentez
    oku: Callable[[str], Awaitable[dict[str, Any] | None]] = zamanlayici.ayar_oku
    yaz: Callable[[str, dict[str, Any]], Awaitable[None]] = zamanlayici.ayar_yaz
    simdi: Callable[[], datetime] = field(default=lambda: datetime.now(TR))
    uyu: Callable[[float], Awaitable[None]] = asyncio.sleep
    sira_ekle: Callable[[str], Awaitable[None]] | None = None  # zincir bitince yapılacaklara
    ara: Callable[[str], Awaitable[bool]] | None = None  # 2. adımda sesli not yerine telefon (arandıysa True)
    ayar: dict[str, Any] = field(default_factory=lambda: dict(VARSAYILAN))
    zincirler: list[dict[str, Any]] = field(default_factory=list)
    _son_hata_notu: datetime | None = None
    _bu_cevap_sesli: bool = False  # model 'bu cevabı sesli de gönder' dedi (tek seferlik)

    async def yukle(self) -> None:
        self.ayar = {**VARSAYILAN, **(await self.oku(AYAR_ANAHTAR) or {}), "ses": SES}  # eski kayıtlı ses yok sayılır
        self.zincirler = list((await self.oku(ZINCIR_ANAHTAR) or {}).get("zincirler", []))

    async def _yaz(self, anahtar: str, deger: dict[str, Any]) -> None:
        try:
            await self.yaz(anahtar, deger)
        except Exception as e:  # noqa: BLE001
            logger.warning("ses ayarı yazılamadı: %s", type(e).__name__)

    # --- seslendirme ------------------------------------------------------------

    async def seslendir(self, metin: str, *, sessiz_hata: bool = False) -> bool:
        """Metni parça parça sesli not olarak gönderir. Hiç gönderemezse False (metin zaten gitmiş olmalı)."""
        parcalar = parcala(temizle(metin))
        if not parcalar:
            return False
        fazla = len(parcalar) > MAKS_PARCA
        if fazla:
            parcalar = parcalar[:MAKS_PARCA]
            parcalar[-1] += " Devamını yazılı olarak gönderdim."
        gonderilen = 0
        for i, p in enumerate(parcalar):
            try:
                veri = await asyncio.wait_for(self._sentez_tekrarli(p), SENTEZ_ZAMAN_ASIMI)
                baslik = f"{i + 1}/{len(parcalar)}" if len(parcalar) > 1 else ""
                await self.gonder_ses(veri, baslik)
                gonderilen += 1
            except Exception as e:  # noqa: BLE001 — ses olmazsa metinle devam
                logger.warning("seslendirme başarısız (%d/%d): %s", i + 1, len(parcalar), type(e).__name__)
                if not sessiz_hata:
                    await self._hata_notu(gonderilen > 0)
                return gonderilen > 0
        return True

    async def _sentez_tekrarli(self, p: str) -> bytes:
        try:
            return await self.sentez(p, self.ayar["ses"], self.ayar["hiz"])
        except Exception:  # noqa: BLE001 — ağ kıpırtısı: bir kez daha dene
            await self.uyu(1.5)
            return await self.sentez(p, self.ayar["ses"], self.ayar["hiz"])

    async def _hata_notu(self, yarim: bool) -> None:
        simdi = self.simdi()
        if self._son_hata_notu and simdi - self._son_hata_notu < HATA_NOT_ARALIK:
            return
        self._son_hata_notu = simdi
        await self.gonder_metin("Seslendiremedim" + (" (sesin devamı gelmedi)" if yarim else "")
                                + ", metin olarak devam ediyorum.")

    async def cevap_eslik(self, cevap: str, sesli_giris: bool) -> None:
        """Her son cevaptan sonra: moda göre sesli kopyası."""
        mod = self.ayar.get("mod", "kapali")
        istendi, self._bu_cevap_sesli = self._bu_cevap_sesli, False
        if istendi or mod == "hepsi" or (mod == "sesliye_sesli" and sesli_giris):
            await self.seslendir(cevap)

    # --- tool -------------------------------------------------------------------

    async def ayarla(self, arg: dict[str, Any]) -> tuple[bool, str]:
        eylem = str(arg.get("eylem") or "").strip()
        if eylem == "oku":
            metin = str(arg.get("metin") or "").strip()
            if not metin:
                return False, "Sesli okunacak metin boş."
            ok = await self.seslendir(metin)
            return (True, "Sesli not olarak gönderdim.") if ok else (
                False, "Seslendiremedim (ses servisine ulaşılamadı); metin olarak yaz.")
        if eylem == "ayarla":
            yeni = dict(self.ayar)
            mod = str(arg.get("mod") or "").strip()
            if mod:
                if mod not in MODLAR:
                    return False, f"mod şunlardan biri olmalı: {', '.join(MODLAR)}."
                yeni["mod"] = mod
            hiz = str(arg.get("hiz") or "").strip()
            if hiz:
                if not re.fullmatch(r"[+-]\d{1,2}%", hiz):
                    return False, "hiz '+10%' ya da '-10%' gibi olmalı."
                yeni["hiz"] = hiz
            self.ayar = yeni
            await self._yaz(AYAR_ANAHTAR, self.ayar)
            return True, f"Ses ayarı: {self.durum()}"
        if eylem == "cevabi_sesli":  # bu turun son cevabı yazıldıktan sonra sesli de gider (metni tekrar yazma)
            self._bu_cevap_sesli = True
            return True, "Tamam, cevabını yazınca sesli olarak da göndereceğim."
        if eylem == "durum":
            return True, self.durum()
        if eylem == "acil":
            metin = re.sub(r"\s+", " ", str(arg.get("metin") or "")).strip()[:300]
            if not metin:
                return False, "Acil hatırlatma metni boş."
            await self.acil_baslat(metin)
            return True, "Acil hatırlatma zinciri başladı: şimdi, 10 dk sonra ve 20 dk sonra sesli not; cevap verirsen durur."
        if eylem == "acil_dur":
            n = await self.acil_durdur()
            return True, f"{n} acil hatırlatmayı durdurdum." if n else "Aktif acil hatırlatma yok."
        return False, "eylem şunlardan biri olmalı: oku, cevabi_sesli, ayarla, durum, acil, acil_dur."

    def durum(self) -> str:
        ad = "Vekil'in kendi sesi"
        mod = {"kapali": "sadece istersen", "sesliye_sesli": "sesli mesaja sesli cevap",
               "hepsi": "her cevap sesli de"}[self.ayar["mod"]]
        return f"ses {ad} ({self.ayar['ses']}), {mod}, hız {self.ayar['hiz']}"

    # --- acil zinciri -------------------------------------------------------------

    async def acil_baslat(self, metin: str) -> None:
        z = {"id": max((x["id"] for x in self.zincirler), default=0) + 1, "metin": metin, "adim": 0,
             "sonraki": self.simdi().isoformat()}
        self.zincirler.append(z)
        await self._yaz(ZINCIR_ANAHTAR, {"zincirler": self.zincirler})
        await self.tik()  # ilk not hemen

    async def acil_durdur(self) -> int:
        n = len(self.zincirler)
        if n:
            self.zincirler = []
            await self._yaz(ZINCIR_ANAHTAR, {"zincirler": []})
        return n

    async def kullanici_yazdi(self) -> bool:
        """Kullanıcı herhangi bir mesaj yazdı: zincir (ilk not gittiyse) durur. Durduysa True."""
        aktif = [z for z in self.zincirler if z["adim"] > 0]
        if not aktif:
            return False
        self.zincirler = [z for z in self.zincirler if z["adim"] == 0]
        await self._yaz(ZINCIR_ANAHTAR, {"zincirler": self.zincirler})
        return True

    async def tik(self) -> None:
        simdi = self.simdi()
        degisti = False
        for z in list(self.zincirler):
            zaman = datetime.fromisoformat(z["sonraki"])
            if zaman > simdi:
                continue
            adim = z["adim"]
            degisti = True
            if simdi - zaman > ZINCIR_GECIKME_SINIRI:  # Render uzun uyuduysa: eski zinciri bitir
                self.zincirler.remove(z)
                continue
            if adim >= len(ZINCIR_ARALIK):  # 3 not gitti, cevap yok: sıraya al
                self.zincirler.remove(z)
                await self._yaz(ZINCIR_ANAHTAR, {"zincirler": self.zincirler})
                if self.sira_ekle:
                    try:
                        await self.sira_ekle(z["metin"])
                    except Exception as e:  # noqa: BLE001
                        logger.warning("acil iş sıraya eklenemedi: %s", type(e).__name__)
                await self.gonder_metin(f"'{z['metin']}' cevapsız kaldı; yapılacaklar sırasında bekliyor.")
                continue
            # önce ilerlet ve kaydet, sonra gönder: yeniden başlamada çift not olmasın
            z["adim"] = adim + 1
            z["sonraki"] = (simdi + (ZINCIR_ARALIK[adim + 1] if adim + 1 < len(ZINCIR_ARALIK)
                                     else timedelta(minutes=1))).isoformat()
            await self._yaz(ZINCIR_ANAHTAR, {"zincirler": self.zincirler})
            metin = ZINCIR_ONEK[adim].format(m=z["metin"])
            if adim == 1 and self.ara is not None:  # 10 dk cevapsız: telefonla ara (aranamazsa not)
                try:
                    if await self.ara(z["metin"]):
                        continue
                except Exception as e:  # noqa: BLE001
                    logger.warning("acil arama hatası: %s", type(e).__name__)
            if not await self.seslendir(metin, sessiz_hata=True):
                await self.gonder_metin(metin)  # ses olmadıysa zincir metinle sürer
        if degisti:
            await self._yaz(ZINCIR_ANAHTAR, {"zincirler": self.zincirler})

    async def dongu(self) -> None:
        while True:
            try:
                await self.tik()
            except Exception:  # noqa: BLE001
                logger.exception("acil zincir tik hatası")
            await self.uyu(TIK_SN)
