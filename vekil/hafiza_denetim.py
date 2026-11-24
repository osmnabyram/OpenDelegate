"""Hafıza sağlık kontrolü: Vekil haftada bir (Pazar 20:00) kalıcı hafızasını SALT OKUMA ile tarar, bulguları
Kullanıcıya tek mesajla bildirir. Hiçbir şeyi kendisi silmez/değiştirmez; temizliği kullanıcı ister (hafizadan_sil).

Bulgu türleri:
- çakışma: iki kayıt aynı şeyi söylüyor (anahtar+değer kelime kökleri Jaccard >= CAKISMA_ESIK). Ucuz, yerel.
- eski: değer "güncel bakiye / şu an / bu hafta" gibi zamana bağlı ve kayıt ESKI_GUN'den eski. Ucuz, yerel.
- çelişki: iki kayıt birbirine ters (anlam ister): haftada tek bir LLM çağrısı; olmazsa bu tür atlanır.

Öğrenme: Kullanıcı bir bulguyu bildirildiği hâlde silmediyse ("kalsın" kararı) aynı bulgu SUSKUN_HAFTA hafta
tekrar raporlanmaz. Bulgu yoksa mesaj atılmaz (spam yok). Neon: kayıtlar hafiza önbelleğinden; tek yazma
(`ayarlar` 'hafiza_denetim').
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from harita import _kokler

logger = logging.getLogger("hafiza_denetim")

ANAHTAR = "hafiza_denetim"
CAKISMA_ESIK = 0.6
ESKI_GUN = 30
SUSKUN_HAFTA = 4
_GECICI = re.compile(r"güncel|bakiye|şu an|şimdilik|bu hafta|bu ay|henüz|geçici|yakında", re.I)


def _benzerlik(a: dict[str, str], b: dict[str, str]) -> float:
    ka = _kokler(f"{a['anahtar'].replace('_', ' ')} {a['deger']}")
    kb = _kokler(f"{b['anahtar'].replace('_', ' ')} {b['deger']}")
    return len(ka & kb) / len(ka | kb) if ka and kb else 0.0


def yerel_bulgular(kayitlar: list[dict[str, str]], simdi: datetime) -> list[dict[str, Any]]:
    """Çakışma + eski (LLM'siz)."""
    bulgular: list[dict[str, Any]] = []
    for i, a in enumerate(kayitlar):
        for b in kayitlar[i + 1:]:
            if _benzerlik(a, b) >= CAKISMA_ESIK:
                bulgular.append({"tur": "çakışma", "anahtarlar": [a["anahtar"], b["anahtar"]],
                                 "neden": "aynı bilgiyi tekrar ediyor"})
    for k in kayitlar:
        tarih = str(k.get("guncellendi") or "")[:10]
        if _GECICI.search(k["deger"]) and tarih:
            gun = (simdi.date() - datetime.fromisoformat(tarih).date()).days
            if gun >= ESKI_GUN:
                bulgular.append({"tur": "eski", "anahtarlar": [k["anahtar"]],
                                 "neden": f"zamana bağlı bilgi, {gun} gündür güncellenmedi"})
    return bulgular


CELISKI_ISTEK = (
    "Aşağıda bir asistanın kullanıcı (Kullanıcı) hakkındaki kalıcı hafıza kayıtları var (anahtar: değer). Birbirine "
    "AÇIKÇA ters düşen kayıt çiftlerini bul (ör. biri 'toplantı Salı', öbürü 'toplantı Çarşamba' diyor). Sadece gerçek "
    "çelişki; tamamlayıcı ya da farklı konudaki kayıtlar çelişki DEĞİL. Sadece JSON dizi döndür: "
    '[{"a": "anahtar1", "b": "anahtar2", "neden": "kısa Türkçe açıklama"}]. Yoksa [].'
)


async def celiskiler(kayitlar: list[dict[str, str]], llm: Callable[[str, str], Awaitable[str]]) -> list[dict[str, Any]]:
    metin = "\n".join(f"{k['anahtar']}: {k['deger']}" for k in kayitlar)[:20_000]
    try:
        ham = await llm(CELISKI_ISTEK, metin)
        m = re.search(r"\[.*\]", ham, re.S)
        gecerli = {k["anahtar"] for k in kayitlar}
        return [{"tur": "çelişki", "anahtarlar": [c["a"], c["b"]], "neden": str(c.get("neden", ""))[:200]}
                for c in (json.loads(m.group(0)) if m else [])
                if isinstance(c, dict) and c.get("a") in gecerli and c.get("b") in gecerli]
    except Exception as e:  # noqa: BLE001 — çelişki taraması olmazsa diğer bulgular yine raporlanır
        logger.warning("çelişki taraması yapılamadı: %s", type(e).__name__)
        return []


def _imza(b: dict[str, Any]) -> str:
    return b["tur"] + ":" + "|".join(sorted(b["anahtarlar"]))


def rapor(toplam: int, bulgular: list[dict[str, Any]]) -> str:
    say = {t: sum(b["tur"] == t for b in bulgular) for t in ("çakışma", "eski", "çelişki")}
    satirlar = [f"Hafıza kontrolü: {toplam} kayıt · {say['çakışma']} çakışma · {say['eski']} eski · "
                f"{say['çelişki']} çelişki"]
    for b in bulgular:
        satirlar.append(f"- {b['tur'].capitalize()}: {' / '.join(b['anahtarlar'])} ({b['neden']})")
    satirlar.append("Kendim bir şey silmedim. Hangilerini temizleyeyim ya da birleştireyim, söylemen yeterli.")
    return "\n".join(satirlar)


async def denetle(
    kayitlar: list[dict[str, str]],
    simdi: datetime,
    llm: Callable[[str, str], Awaitable[str]] | None,
    durum: dict[str, Any],
) -> str | None:
    """Rapor metni (bulgu yoksa None). `durum` (bildirilen imzalar) yerinde güncellenir; kayıtlara dokunulmaz."""
    bulgular = yerel_bulgular(kayitlar, simdi) + (await celiskiler(kayitlar, llm) if llm else [])
    bildirilen: dict[str, str] = durum.setdefault("bildirilen", {})
    sinir = simdi - timedelta(weeks=SUSKUN_HAFTA)
    yeni = [b for b in bulgular
            if _imza(b) not in bildirilen or datetime.fromisoformat(bildirilen[_imza(b)]) < sinir]
    canli = {_imza(b) for b in bulgular}
    durum["bildirilen"] = {i: z for i, z in bildirilen.items() if i in canli}  # silinenleri unut
    for b in yeni:
        durum["bildirilen"][_imza(b)] = simdi.isoformat()
    return rapor(len(kayitlar), yeni) if yeni else None
