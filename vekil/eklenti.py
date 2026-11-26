"""Eklenti klasörü: müşteriye özel araçlar ana koda dokunmadan `eklentiler/` içine konur.

Her `eklentiler/<ad>.py` dosyası şunları tanımlar:
  ARAC = {"ad": "...", "aciklama": "...", "parametreler": {JSON şeması}, "risk": "düşük" | "orta"}
  def calistir(argumanlar) -> str | tuple[bool, str]      # async def de olur
Adı `_` ile başlayan dosyalar atlanır (örnek şablon). Bozuk bir eklenti diğerlerini ve OpenDelegate'i durdurmaz.
Eklenti kodu sunucuda TAM yetkiyle çalışır: yalnızca kendi yazdığınız ya da okuyup güvendiğiniz kodu koyun.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Callable

import config
import tools

logger = logging.getLogger("vekil.eklenti")

KLASOR = config.PROJE_DIZINI / "eklentiler"
ZAMAN_ASIMI = 60  # sn; takılan eklenti OpenDelegate'in turunu dondurmasın
_AD = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_RISKLER = ("düşük", "orta")  # kritik/onaylı araç eklentiyle açılmaz

_islevler: dict[str, Callable[..., Any]] = {}


def yukle(klasor: Path | None = None) -> list[str]:
    """Klasördeki eklentileri `tools.TOOLLAR`'a kaydeder. Yüklenen araç adlarını döner."""
    klasor = klasor or KLASOR
    yuklenen: list[str] = []
    if not klasor.is_dir():
        return yuklenen
    for dosya in sorted(klasor.glob("*.py")):
        if dosya.name.startswith("_"):
            continue
        try:
            ad = _kaydet(dosya)
        except Exception as e:  # noqa: BLE001 - bozuk eklenti OpenDelegate'i düşürmemeli
            logger.warning("Eklenti atlandı (%s): %s", dosya.name, e)
            continue
        yuklenen.append(ad)
        logger.info("Eklenti yüklendi: %s", ad)
    return yuklenen


def _kaydet(dosya: Path) -> str:
    spec = importlib.util.spec_from_file_location(f"eklenti_{dosya.stem}", dosya)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    arac = getattr(modul, "ARAC", None)
    islev = getattr(modul, "calistir", None)
    if not isinstance(arac, dict) or not callable(islev):
        raise ValueError("ARAC (sözlük) ve calistir (işlev) gerekli")
    ad = str(arac.get("ad", ""))
    if not _AD.match(ad):
        raise ValueError(f"geçersiz araç adı: {ad!r} (küçük harf, rakam, _; 3-41 karakter)")
    if ad in tools.TOOLLAR and ad not in _islevler:
        raise ValueError(f"'{ad}' adı OpenDelegate'in kendi aracıyla çakışıyor")
    aciklama = str(arac.get("aciklama", "")).strip()
    if not aciklama:
        raise ValueError("aciklama boş: model aracı ne zaman çağıracağını bilemez")
    parametreler = arac.get("parametreler") or {"type": "object", "properties": {}}
    if not isinstance(parametreler, dict) or parametreler.get("type") != "object":
        raise ValueError("parametreler bir JSON şeması (type: object) olmalı")
    risk = arac.get("risk", "düşük")
    if risk not in _RISKLER:
        raise ValueError(f"risk {_RISKLER} değerlerinden biri olmalı")
    tools.TOOLLAR[ad] = tools.Tool(ad=ad, hedef="eklenti", risk=risk, aciklama=aciklama, parametreler=parametreler)
    _islevler[ad] = islev
    return ad


async def calistir(ad: str, argumanlar: dict[str, Any]) -> tuple[bool, str]:
    """Eklenti aracını çalıştırır: (başarılı_mı, metin)."""
    islev = _islevler.get(ad)
    if islev is None:
        return False, f"HATA: '{ad}' eklentisi yüklü değil."
    try:
        if inspect.iscoroutinefunction(islev):
            sonuc = await asyncio.wait_for(islev(argumanlar), ZAMAN_ASIMI)
        else:
            sonuc = await asyncio.wait_for(asyncio.to_thread(islev, argumanlar), ZAMAN_ASIMI)
    except asyncio.TimeoutError:
        return False, f"HATA: '{ad}' eklentisi {ZAMAN_ASIMI} sn içinde bitmedi."
    except Exception as e:  # noqa: BLE001
        logger.exception("Eklenti hatası: %s", ad)
        return False, f"HATA: '{ad}' eklentisi hata verdi: {type(e).__name__}: {e}"
    if isinstance(sonuc, tuple) and len(sonuc) == 2:
        return bool(sonuc[0]), str(sonuc[1])
    return True, str(sonuc)
