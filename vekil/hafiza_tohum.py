"""Kalıcı hafızaya başlangıç bilgilerini BİR KEZ yazar.

Açılışta çalışır; `ayarlar`'daki "tohum:<surum>" işareti varsa hiçbir şey yapmaz. Böylece kullanıcı
sonradan /unut ile silerse kayıt geri gelmez. Yeni bilgi eklemek için yeni bir SURUM ve sadece
yeni/değişen kayıtlar eklenir.

Kendi profilini buraya koymak zorunda değilsin: Vekil'e Telegram'dan "bunu hatırla: ..." demen yeter.
İstersen KAYITLAR listesine ("not", "profil_1", "Adım X, ... yaşındayım") gibi satırlar ekleyip
yeni bir SURUM yazabilirsin (profil_* kayıtları haritada PROFİL gezegeni olur).
"""

from __future__ import annotations

import asyncio
import logging

import hashlib

import config
import hafiza

logger = logging.getLogger(__name__)

HITAP = ("Kullanıcıya 'kanka' DEME. Hitap: her zaman 'efendim'. "
         "Sıcak ve saygılı; iş ekseninde net ve kısa.")

KAYITLAR: list[tuple[str, str, str]] = [
    ("tercih", "konusma_tarzi", HITAP),
    ("tercih", "profil_kayit_kurali",
     "Kullanıcı hakkındaki sorularda profil_* kayıtlarına başvur; kayıtlarda olmayan detayı uydurma, "
     "'bilmiyorum' de."),
    ("terim", "pist", "Kullanıcının slang'i: dürtme / \"az bak\" anlamında; selamlaşmak ya da seni dürtüp çağırmak "
     "için kullanır. \"pist\" yazınca anlamını sorma, sıcak karşılık ver (ör. \"buradayım efendim, ne yapıyoruz?\")."),
]

SURUMLER: list[tuple[str, list[tuple[str, str, str]]]] = [("tohum:baslangic-1", KAYITLAR)]


async def uygula() -> None:
    """Açılışta çağrılır. Her sürüm bir kez yazılır (işaret varsa atlanır); DB yoksa sessizce geçer."""
    surumler = list(SURUMLER)
    if config.PROFIL:  # kurulum sihirbazı cevapları; metin değişince yeni sürüm olarak yeniden yazılır
        ozet = hashlib.sha1(config.PROFIL.encode("utf-8")).hexdigest()[:8]
        surumler.append((f"tohum:profil:{ozet}", [("not", "profil_1", config.PROFIL)]))
    for surum, kayitlar in surumler:
        await _uygula(surum, kayitlar)


async def _uygula(surum: str, kayitlar: list[tuple[str, str, str]]) -> None:
    try:
        isaret = await asyncio.to_thread(
            hafiza._calistir, "SELECT deger FROM ayarlar WHERE anahtar = %s", (surum,), sonuc="tek"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Hafıza tohumu atlandı (okunamadı): %s", type(e).__name__)
        return
    if isaret:
        return
    hepsi = True
    for tur, anahtar, deger in kayitlar:
        try:
            if not await hafiza.bilgi_yaz(tur, anahtar, deger):
                hepsi = False
        except hafiza.HafizaHatasi as e:
            logger.warning("Tohum kaydı reddedildi (%s): %s", anahtar, e)
    if hepsi:
        await asyncio.to_thread(hafiza._ayar_yaz, surum, "uygulandi")
        logger.info("Hafıza tohumu yazıldı: %d kayıt", len(kayitlar))
