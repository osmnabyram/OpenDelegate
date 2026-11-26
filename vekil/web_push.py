"""Web Push: sekme kapalıyken yeni mesaj (hatırlatma, brifing, bitmiş iş) için tarayıcı bildirimi.

- Anahtarlar (VAPID) `OPENDELEGATE_SIR`'dan türetilir: saklanacak ek sır yok, her açılışta aynı.
- Bildirim METİN TAŞIMAZ ("yeni mesaj"): içerik push servisinden (Google/Apple/Mozilla) geçmesin.
- Abonelikler `ayarlar` tablosunda (anahtar adında "token" var: `/yedek` dosyasına girmez).
- `pywebpush` yoksa özellik kapalıdır, sohbetin geri kalanı etkilenmez.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import config

logger = logging.getLogger("vekil.web_push")

ANAHTAR = "push_token_aboneler"
MAKS_ABONE = 5
ARALIK_SN = 30.0  # iki bildirim arası en az bu kadar (mesaj yağmurunda tek bildirim)
BASLIK = "OpenDelegate"
GOVDE = "Yeni mesaj"

# Bilinen tarayıcı push servisleri (Chrome/Brave/Edge/Samsung: FCM, Firefox: Mozilla, Safari: Apple, eski Edge: WNS).
# Abonelik adresi sunucudan çıkan bir istek olacağı için herhangi bir https adresine izin verilmez (SSRF).
IZINLI_UC_SONEKLERI = (".googleapis.com", ".mozilla.com", ".mozaws.net", ".apple.com", ".notify.windows.com")

_aboneler: list[dict[str, Any]] = []
_son_gonderim = 0.0
_arka: set[asyncio.Task[None]] = set()


def _kutuphane() -> bool:
    try:
        import pywebpush  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
    except Exception:  # noqa: BLE001 - paket yok: özellik kapalı
        return False
    return True


def acik() -> bool:
    return config.web_acik() and _kutuphane()


def _anahtar() -> Any:
    """ANA_SIR'dan sabit bir P-256 özel anahtarı türetir."""
    from cryptography.hazmat.primitives.asymmetric import ec

    n = int("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16)  # P-256 mertebesi
    ham = hmac.new(config.ANA_SIR.encode(), b"opendelegate-vapid-v1", hashlib.sha256).digest()
    return ec.derive_private_key(int.from_bytes(ham, "big") % (n - 1) + 1, ec.SECP256R1())


def genel_anahtar() -> str:
    """Tarayıcının `applicationServerKey` değeri (base64url, dolgusuz)."""
    from cryptography.hazmat.primitives import serialization

    nokta = _anahtar().public_key().public_bytes(serialization.Encoding.X962,
                                                    serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(nokta).rstrip(b"=").decode()


def _vapid() -> Any:
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    pem = _anahtar().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
    return Vapid.from_pem(pem)


def abone_gecerli(a: Any) -> bool:
    """Tarayıcının verdiği abonelik: https uç nokta + p256dh/auth anahtarları."""
    if not isinstance(a, dict):
        return False
    uc = a.get("endpoint")
    anahtarlar = a.get("keys")
    if not isinstance(uc, str) or len(uc) > 600:
        return False
    u = urlparse(uc)
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        return False
    host = (u.hostname or "").lower()
    if not host.endswith(IZINLI_UC_SONEKLERI):
        return False
    if not isinstance(anahtarlar, dict):
        return False
    return all(isinstance(anahtarlar.get(k), str) and 8 <= len(anahtarlar[k]) <= 200 for k in ("p256dh", "auth"))


async def yukle() -> None:
    import zamanlayici

    global _aboneler
    kayit = await zamanlayici.ayar_oku(ANAHTAR)
    _aboneler = [a for a in (kayit or {}).get("liste", []) if abone_gecerli(a)][:MAKS_ABONE]


async def _kaydet() -> None:
    import zamanlayici

    await zamanlayici.ayar_yaz(ANAHTAR, {"liste": _aboneler})


async def abone_ekle(a: dict[str, Any]) -> bool:
    if not abone_gecerli(a):
        return False
    temiz = {"endpoint": a["endpoint"], "keys": {"p256dh": a["keys"]["p256dh"], "auth": a["keys"]["auth"]}}
    _aboneler[:] = [x for x in _aboneler if x["endpoint"] != temiz["endpoint"]] + [temiz]
    del _aboneler[:-MAKS_ABONE]
    await _kaydet()
    return True


async def abone_sil(uc: str) -> None:
    _aboneler[:] = [x for x in _aboneler if x["endpoint"] != uc]
    await _kaydet()


def _gonder_tek(abone: dict[str, Any]) -> int:
    """Tek aboneye gönderir (iş parçacığında çalışır). Döner: HTTP durumu; 0 = ağ hatası."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(subscription_info=abone, data=json.dumps({"baslik": BASLIK, "govde": GOVDE}), vapid_private_key=_vapid(),
                vapid_claims={"sub": config.WEBHOOK_URL or "https://localhost"}, ttl=3600, timeout=10)
        return 201
    except WebPushException as e:
        return int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
    except Exception:  # noqa: BLE001 - ağ vb.: abonelik silinmez
        return 0


async def bildir() -> None:
    """Tüm abonelere 'yeni mesaj' bildirimi. Geçersiz (404/410) abonelikler silinir."""
    global _son_gonderim
    if not _aboneler or not acik():
        return
    simdi = time.monotonic()
    if simdi - _son_gonderim < ARALIK_SN:
        return
    _son_gonderim = simdi
    for a in list(_aboneler):
        durum = await asyncio.to_thread(_gonder_tek, a)
        if durum in (404, 410):
            await abone_sil(a["endpoint"])
        elif durum >= 400 or durum == 0:
            logger.info("web push gönderilemedi: durum %s", durum)


def tetikle() -> None:
    """WebBot'un sync `_ekle`'sinden çağrılır; olay döngüsünde arka plan görevi açar."""
    if not _aboneler:
        return
    try:
        t = asyncio.get_running_loop().create_task(bildir())
    except RuntimeError:  # döngü yok (test/sync bağlam)
        return
    _arka.add(t)
    t.add_done_callback(_arka.discard)
