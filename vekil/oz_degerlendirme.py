"""Haftalık öz-değerlendirme: Vekil son 7 gününü (eylemler + sohbet) denetler, kısa ve dürüst bir rapor yazar.

- SADECE RAPOR: davranış, hafıza, ayar değiştirmez. Önerileri `ayarlar` 'oz_oneriler'de "bekliyor" olarak tutar
  (inert: hiçbir yerde okunmaz/uygulanmaz). Kullanıcı onaylarsa (oz_degerlendirme tool'u) öneri bir `tercih` hafıza
  kaydına dönüşür ve ancak o zaman davranışı etkiler; reddederse "reddedildi" olur.
- Ölçümler yerel (DB'deki kendi logları; ek servis yok): eylem sayısı, araç bazında hata, tekrar eden aynı hata,
  yasak/yetkisiz denemeler, "dur" ile kesilen işler. Yorum (iyi/sorun/öneri) haftada TEK LLM çağrısı.
- Rapor en fazla MAKS_MADDE madde, madde başı MAKS_MADDE_UZUNLUK karakter. Hafıza sağlık kontrolüyle aynı
  Pazar mesajında ayrı bölüm. Kullanıcı "sus" derse (tool: sus) o haftanın raporu atlanır.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

logger = logging.getLogger("oz_degerlendirme")

ONERI_ANAHTAR = "oz_oneriler"
SUS_ANAHTAR = "oz_sus"
MAKS_MADDE = 10
MAKS_MADDE_UZUNLUK = 180
MAKS_BEKLEYEN = 30
_HATA = ("hata", "yasak", "yetkisiz", "gecersiz", "reddedildi", "cevrimdisi")


def hafta_kodu(t: datetime) -> str:
    y, h, _ = t.isocalendar()
    return f"{y}-H{h:02d}"


def olcumler(eylemler: list[dict[str, Any]], mesajlar: list[dict[str, Any]]) -> dict[str, Any]:
    """LLM'siz sayılar: ne kadar iş, nerede hata, nerede kendini tekrar etti."""
    hatali = [e for e in eylemler if e["durum"] in _HATA]
    arac_hata = Counter(e["tool"] for e in hatali)
    tekrar = Counter((e["tool"], e.get("sonuc", "")[:80]) for e in hatali)
    return {
        "eylem": len(eylemler),
        "basarili": sum(e["durum"] == "basarili" for e in eylemler),
        "hata": len(hatali),
        "arac_hata": dict(arac_hata.most_common(5)),
        "tekrarlanan_hata": [f"{t} x{n}: {s}" for (t, s), n in tekrar.most_common(3) if n >= 3],
        "yasak_yetkisiz": sum(e["durum"] in ("yasak", "yetkisiz") for e in eylemler),
        "en_cok_arac": dict(Counter(e["tool"] for e in eylemler).most_common(5)),
        "kullanici_mesaj": sum(m["rol"] == "user" for m in mesajlar),
    }


ISTEK = (
    "Sen Vekil'sin (Kullanıcının kişisel asistanı). Son 7 gününü dürüstçe değerlendiriyorsun. Aşağıda ölçümler ve "
    "sohbetten örnekler var. Kullanıcının düzelttiği, tekrar sorduğu, 'hayır/yanlış/öyle değil/dur' dediği yerler yanlış "
    "anlamadır; aynı hatanın tekrarı ve gereksiz adımlar israftır. Kendini övme, kısa ve net ol, emoji yok. "
    "Sadece verilen veriye dayan, olay UYDURMA; gün/saat biliyorsan söyle. En fazla 3 iyi, 4 sorun, 3 öneri. "
    "Öneriler somut ve uygulanabilir davranış kuralı olsun ('X durumunda Y yap'). "
    'Sadece JSON döndür: {"iyi": ["..."], "sorun": ["..."], "oneri": ["..."]}'
)


def _ornek_sohbet(mesajlar: list[dict[str, Any]], sinir: int = 9000) -> str:
    satir = [f"[{m['zaman'][:16]}] {'Kullanıcı' if m['rol'] == 'user' else 'Vekil'}: {m['icerik']}" for m in mesajlar]
    metin = "\n".join(satir)
    return metin[-sinir:]


def _kisalt(x: Any) -> str:
    s = re.sub(r"\s+", " ", str(x)).strip()
    return s if len(s) <= MAKS_MADDE_UZUNLUK else s[:MAKS_MADDE_UZUNLUK - 1].rstrip() + "…"


async def degerlendir(
    eylemler: list[dict[str, Any]],
    mesajlar: list[dict[str, Any]],
    llm: Callable[[str, str], Awaitable[str]] | None,
) -> dict[str, list[str]]:
    """{'iyi','sorun','oneri'} (kısaltılmış, toplam en fazla MAKS_MADDE). LLM yoksa/bozuksa sadece ölçümden."""
    o = olcumler(eylemler, mesajlar)
    sonuc: dict[str, list[str]] = {"iyi": [], "sorun": [], "oneri": []}
    if llm is not None and (eylemler or mesajlar):
        try:
            ham = await llm(ISTEK, "ÖLÇÜMLER:\n" + json.dumps(o, ensure_ascii=False) + "\n\nSOHBET:\n"
                            + _ornek_sohbet(mesajlar))
            m = re.search(r"\{.*\}", ham, re.S)
            veri = json.loads(m.group(0)) if m else {}
            for k in sonuc:
                sonuc[k] = [_kisalt(x) for x in veri.get(k, []) if str(x).strip()]
        except Exception as e:  # noqa: BLE001 — yorum çıkmazsa ölçümle yetin
            logger.warning("öz-değerlendirme yorumu çıkmadı: %s", type(e).__name__)
    if not any(sonuc.values()):  # yedek: sadece sayılardan
        if o["hata"]:
            sonuc["sorun"].append(_kisalt(f"{o['eylem']} işin {o['hata']} tanesi hatayla bitti; en çok: "
                                          + ", ".join(f"{a} ({n})" for a, n in o["arac_hata"].items())))
        for t in o["tekrarlanan_hata"]:
            sonuc["sorun"].append(_kisalt(f"Aynı hatayı tekrarladım: {t}"))
    # toplam madde sınırı: önce sorunlar, sonra öneriler, sonra iyiler kısılır
    while sum(map(len, sonuc.values())) > MAKS_MADDE:
        for k in ("iyi", "oneri", "sorun"):
            if len(sonuc[k]) > 1:
                sonuc[k].pop()
                break
        else:
            break
    return sonuc


# Kendiliğinden öğrenme (23.11): Kullanıcı Vekil'i seyrek kullanıyor; haftalık değerlendirmeden çıkan SIRADAN davranış
# önerileri onay beklemeden tercih kaydı olur. Güvenlik/para/onay/silme konuları ve sır biçimleri ASLA otomatik
# girmez (onlar önceden olduğu gibi kullanıcının onayını bekler). Otomatik dersler OTOMATIK_OMUR_GUN sonra düşer.
OTOMATIK_HAFTALIK = 2
OTOMATIK_AZAMI = 12
OTOMATIK_OMUR_GUN = 60
_YASAK_KONU = re.compile(
    r"ödeme|para|havale|eft|[ıi]ban|şifre|pin|kilit|kilid|kys|token|onay|sil|izin|güvenlik|yetki"
    r"|http|www\.|talimat|yoksay|ignore|unut|kural(?:ı|ları)?\s+(?:değiştir|kaldır)|sistem\s+mesaj", re.I)


def otomatik_uygun(metin: str) -> bool:
    import guvenlik
    m = (metin or "").strip()
    return 10 <= len(m) <= MAKS_MADDE_UZUNLUK and not _YASAK_KONU.search(m) and not guvenlik.hassas_metin_mi(m)


def suresi_dolanlar(depo: dict[str, Any], simdi: datetime) -> list[int]:
    """Süresi dolan otomatik derslerin numaraları (durumları 'suresi_doldu' olur); aktif sayı sınırını da korur."""
    liste = depo.get("oneriler", [])
    sinir = (simdi - timedelta(days=OTOMATIK_OMUR_GUN)).date().isoformat()
    dusen = [x for x in liste if x["durum"] == "otomatik" and x["tarih"] < sinir]
    aktif = [x for x in liste if x["durum"] == "otomatik" and x not in dusen]
    dusen += aktif[:max(0, len(aktif) - OTOMATIK_AZAMI)]
    for x in dusen:
        x["durum"] = "suresi_doldu"
    return [x["no"] for x in dusen]


def rapor_bolumu(o: dict[str, Any], d: dict[str, list[str]], oneri_nolari: list[int],
                 ogrenilen: list[str] | None = None) -> str:
    satir = [f"Haftalık öz-değerlendirme: {o['eylem']} iş, {o['hata']} hata, {o['kullanici_mesaj']} mesajın"]
    for x in d["iyi"]:
        satir.append(f"+ {x}")
    for x in d["sorun"]:
        satir.append(f"- {x}")
    for no, x in zip(oneri_nolari, d["oneri"]):
        if not any(x == y for y in (ogrenilen or [])):
            satir.append(f"Öneri #{no}: {x}")
    for x in ogrenilen or []:
        satir.append(f"Öğrendim: {x}")
    if any(not any(x == y for y in (ogrenilen or [])) for x in d["oneri"]):
        satir.append("Önerileri sen onaylamadan uygulamam; 'öneri 2'yi uygula' ya da 'gerek yok' demen yeterli.")
    return "\n".join(satir)


def oneri_ekle(depo: dict[str, Any], oneriler: list[str], simdi: datetime) -> list[int]:
    """Önerileri INERT olarak kaydet (bekliyor). Dönen: numaralar."""
    liste = depo.setdefault("oneriler", [])
    nolar = []
    for metin in oneriler:
        no = max((x["no"] for x in liste), default=0) + 1
        liste.append({"no": no, "metin": metin, "durum": "bekliyor", "tarih": simdi.date().isoformat()})
        nolar.append(no)
    bekleyen = [x for x in liste if x["durum"] == "bekliyor"]
    if len(bekleyen) > MAKS_BEKLEYEN:  # en eski bekleyenler düşer
        fazla = {x["no"] for x in bekleyen[:len(bekleyen) - MAKS_BEKLEYEN]}
        depo["oneriler"] = [x for x in liste if x["no"] not in fazla]
    return nolar


def sus_mu(sus: dict[str, Any] | None, simdi: datetime) -> bool:
    return bool(sus) and sus.get("hafta") == hafta_kodu(simdi)


async def haftalik_bolum(
    eylemler: list[dict[str, Any]],
    mesajlar: list[dict[str, Any]],
    llm: Callable[[str, str], Awaitable[str]] | None,
    depo: dict[str, Any],
    simdi: datetime,
    otomatik: list[dict[str, Any]] | None = None,
) -> str | None:
    """Raporun öz-değerlendirme bölümü (veri yoksa None). `depo` (öneriler) yerinde güncellenir."""
    if not eylemler and not mesajlar:
        return None
    d = await degerlendir(eylemler, mesajlar, llm)
    nolar = oneri_ekle(depo, d["oneri"], simdi)
    ogrenilen: list[str] = []
    if otomatik is not None:  # çağıran bunları hafızaya yazar (tercih)
        for no, metin in zip(nolar, d["oneri"]):
            if len(ogrenilen) < OTOMATIK_HAFTALIK and otomatik_uygun(metin):
                kayit = next(x for x in depo["oneriler"] if x["no"] == no)
                kayit["durum"] = "otomatik"
                otomatik.append({"no": no, "metin": metin})
                ogrenilen.append(metin)
    return rapor_bolumu(olcumler(eylemler, mesajlar), d, nolar, ogrenilen)


def yedi_gun_once(simdi: datetime) -> str:
    return (simdi - timedelta(days=7)).replace(tzinfo=None).isoformat(timespec="seconds")
