"""Uzaktan PC açma: akıllı priz (Tapo P100, MANUEL) + BIOS 'Wake on AC'.

Neden manuel: Tapo P100'ü kontrol eden Python kütüphaneleri (python-tapo dahil) sadece
yerel ağdan (KLAP protokolü) çalışır; Render (bulut) ev ağındaki prize ulaşamaz.
TP-Link'in resmi uygulamasının kullandığı bulut yolu community kütüphanelerinde
çözülmüş değil (21.11.2026 araştırıldı). Çözüm: Kullanıcı resmi Tapo uygulamasından
(telefonundan, nerede olursa olsun çalışır) prizi kendisi kapatıp açıyor; Vekil sadece
ajanın bağlanmasını bekliyor, prize hiç dokunmuyor.

Akış (pc_uyandir):
    ajan zaten bağlıysa hiçbir şey yapılmaz.
    değilse: Kullanıcıya Tapo'dan prizi açması bilgisi verilir, en çok DENEME kez
    BAGLANMA_SN boyunca ajan beklenir. Hiçbiri tutmazsa dürüstçe "açılmadı".
Aynı anda tek bekleme (kilit); arkadan gelen istek ilkinin sonucunu görür.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import gorevler

logger = logging.getLogger(__name__)

DENEME = 3
BAGLANMA_SN = 45.0  # Kullanıcının Tapo app'ten prizi açması + hazırda bekletten dönüş + Wi-Fi + ilk yoklama
_KONTROL_SN = 1.0

Bildir = Callable[[str], Awaitable[None]]

_kilit = asyncio.Lock()


async def _ajani_bekle(sure: float) -> bool:
    bitis = time.monotonic() + sure
    while True:
        if gorevler.ajan_cevrimici():
            return True
        kalan = bitis - time.monotonic()
        if kalan <= 0:
            return False
        await asyncio.sleep(min(_KONTROL_SN, kalan))


async def _sessiz(bildir: Bildir | None, metin: str) -> None:
    if bildir is None:
        return
    try:
        await bildir(metin)
    except Exception as e:  # noqa: BLE001 - bilgi satırı gitmedi diye uyandırma yarıda kalmasın
        logger.warning("Uyandırma bilgisi gönderilemedi: %s", type(e).__name__)


def hazir() -> bool:
    """Uzaktan açma her zaman kurulu: priz Tapo app'ten kullanıcı tarafından manuel açılıyor."""
    return True


async def pc_uyandir(bildir: Bildir | None = None) -> tuple[bool, str]:
    """Ajan bağlanana kadar bekler (priz manuel; Vekil elektriğe dokunmaz).
    (açıldı_mı, modele dönecek metin). Exception fırlatmaz ('dur' hariç: CancelledError yayılır)."""
    if gorevler.ajan_cevrimici():
        return True, "PC zaten açık, ajan bağlı."
    async with _kilit:
        if gorevler.ajan_cevrimici():  # biz kilidi beklerken ajan bağlandı
            return True, "PC açıldı, ajan bağlı."
        baslangic = time.monotonic()
        await _sessiz(
            bildir,
            "Bilgisayar kapalı. Kullanıcıya söyle: Tapo uygulamasından prizi kapatıp açsın "
            "(Wake on AC tetiklensin); ben bağlanmasını bekliyorum.",
        )
        for deneme in range(1, DENEME + 1):
            if deneme > 1:
                await _sessiz(bildir, f"Henüz bağlanmadı, bekliyorum ({deneme}/{DENEME}).")
            if await _ajani_bekle(BAGLANMA_SN):
                sure = round(time.monotonic() - baslangic)
                logger.info("PC uzaktan açıldı (%d. deneme, %d sn)", deneme, sure)
                return True, f"PC AÇILDI (~{sure} sn). Ajan bağlı, işe devam edebilirsin."
        logger.warning("PC uzaktan açılamadı (%d deneme)", DENEME)
        return False, (
            f"PC AÇILMADI: ~{round(time.monotonic() - baslangic)} sn bekledim, ajan bağlanmadı. Kullanıcıya "
            "dürüstçe söyle: Tapo uygulamasından prizi gerçekten açtı mı kontrol etsin, ya da PC'yi elle "
            "açması gerekebilir."
        )


async def gerekirse_uyandir(bildir: Bildir | None = None) -> bool:
    """PC gerektiren bir işten önce: ajan bağlı değilse bağlanmasını bekler. Ajan bağlı mı döner."""
    if gorevler.ajan_cevrimici():
        return True
    acildi, _ = await pc_uyandir(bildir)
    return acildi


def durum_metni() -> str:
    pc = "açık (ajan bağlı)" if gorevler.ajan_cevrimici() else "kapalı ya da ajan bağlı değil"
    return f"PC: {pc}. Uzaktan açma: Tapo app'ten manuel (akıllı priz)."


def telegram_bildirici(bot, chat_id: int) -> Bildir:
    async def bildir(metin: str) -> None:
        await bot.send_message(chat_id, metin)
    return bildir
