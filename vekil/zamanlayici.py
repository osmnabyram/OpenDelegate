"""Ortak zamanlayıcı çekirdeği: günlük işler (sabah brifingi; ileride bağlamsal hatırlatmalar, hafıza taraması).

Kurallar:
- Her iş günde EN FAZLA BİR KEZ başarıyla çalışır. Son başarılı gün `ayarlar`'da (zamanlayici:son) tutulur:
  Render yeniden başlasa da aynı gün ikinci kez gitmez.
- Render uyuyup geç uyanırsa: işin saati geçmiş ve bugün çalışmamışsa (son_saat'e kadar) hemen çalışır.
- Hata: 10 dk sonra tekrar, günde en fazla 3 deneme (spam ya da kota yakmasın).
- Neon kotası: açılışta 1 okuma, her başarılı çalışmada 1 yazma (günde 1-2 sorgu mertebesi).
- Saat Türkiye saati (UTC+3, yaz saati yok).

Kullanım: z = Zamanlayici(); z.ekle(GunlukIs("brifing", saat=..., calistir=...)); await z.calis()
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger("zamanlayici")
TR = timezone(timedelta(hours=3), "TR")
DURUM_ANAHTARI = "zamanlayici:son"
TEKRAR_ARALIK = timedelta(minutes=10)
GUNLUK_DENEME = 3


async def ayar_oku(anahtar: str) -> dict[str, Any] | None:
    """`ayarlar` tablosundan JSON değer (yoksa ya da DB yoksa None)."""
    import hafiza

    try:
        satir = await asyncio.to_thread(
            hafiza._calistir, "SELECT deger FROM ayarlar WHERE anahtar = %s", (anahtar,), sonuc="tek"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("ayar okunamadı (%s): %s", anahtar, type(e).__name__)
        return None
    try:
        return json.loads(satir["deger"]) if satir else None
    except (ValueError, TypeError):
        return None


async def ayar_yaz(anahtar: str, deger: dict[str, Any]) -> None:
    import hafiza

    await asyncio.to_thread(hafiza._ayar_yaz, anahtar, json.dumps(deger, ensure_ascii=False))


@dataclass
class GunlukIs:
    ad: str
    saat: Callable[[], time]  # her tikte sorulur: ayar değişince yeni saat hemen geçerli
    calistir: Callable[[], Awaitable[None]]  # başarısızsa exception fırlatmalı
    son_saat: time = time(23, 0)  # geç uyanmada bu saate kadar telafi edilir
    aktif: Callable[[], bool] = field(default=lambda: True)


class Zamanlayici:
    def __init__(
        self,
        *,
        simdi: Callable[[], datetime] = lambda: datetime.now(TR),
        uyu: Callable[[float], Awaitable[None]] = asyncio.sleep,
        oku: Callable[[str], Awaitable[dict[str, Any] | None]] = ayar_oku,
        yaz: Callable[[str, dict[str, Any]], Awaitable[None]] = ayar_yaz,
        tik: float = 30.0,
    ) -> None:
        self._simdi, self._uyu, self._oku, self._yaz, self._tik = simdi, uyu, oku, yaz, tik
        self._isler: list[GunlukIs] = []
        self._son: dict[str, str] = {}  # iş adı -> son başarılı gün (ISO)
        self._deneme: dict[str, tuple[str, int, datetime]] = {}  # ad -> (gün, deneme sayısı, sonraki deneme)
        self._yuklendi = False

    def ekle(self, is_: GunlukIs) -> None:
        self._isler.append(is_)

    def bugun_calisti_mi(self, ad: str) -> bool:
        return self._son.get(ad) == self._simdi().date().isoformat()

    async def yukle(self) -> None:
        self._son = dict(await self._oku(DURUM_ANAHTARI) or {})
        self._yuklendi = True

    async def tik(self) -> None:
        if not self._yuklendi:
            await self.yukle()
        simdi = self._simdi()
        bugun = simdi.date().isoformat()
        for is_ in self._isler:
            if self._son.get(is_.ad) == bugun or not is_.aktif():
                continue
            if not (is_.saat() <= simdi.time() < is_.son_saat):
                continue
            gun, sayi, sonraki = self._deneme.get(is_.ad, (bugun, 0, simdi))
            if gun != bugun:
                sayi, sonraki = 0, simdi
            if sayi >= GUNLUK_DENEME or simdi < sonraki:
                continue
            try:
                await is_.calistir()
            except Exception:  # noqa: BLE001 — bir iş diğerlerini durdurmasın
                logger.exception("Zamanlanmış iş başarısız: %s (deneme %d)", is_.ad, sayi + 1)
                self._deneme[is_.ad] = (bugun, sayi + 1, simdi + TEKRAR_ARALIK)
                continue
            self._son[is_.ad] = bugun
            self._deneme.pop(is_.ad, None)
            try:
                await self._yaz(DURUM_ANAHTARI, self._son)
            except Exception as e:  # noqa: BLE001 — bellekte işaretli; DB dönünce bir sonraki yazımda gider
                logger.warning("zamanlayıcı durumu yazılamadı: %s", type(e).__name__)

    async def calis(self) -> None:
        logger.info("Zamanlayıcı açık: %s", ", ".join(i.ad for i in self._isler) or "(iş yok)")
        while True:
            try:
                await self.tik()
            except Exception:  # noqa: BLE001
                logger.exception("zamanlayıcı tik hatası")
            await self._uyu(self._tik)
