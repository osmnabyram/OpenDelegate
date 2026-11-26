"""Yönetim sayfası: Vekil'in durumu, hafıza sayıları ve son işler tek sayfada (salt okuma).

Adres: /yonetim/<token>. Token, bot anahtarından ayrı bir etiketle türetilir (koda gömülü sır yok);
yanlış token 404 verir. Sayfaya konuşma metni, eylem argümanı ya da sonuç GİTMEZ: yalnızca sayılar ve araç adları.
Model maliyeti gösterilmez: Vekil token kullanımını saklamıyor (DeepSeek panelinden bakın).
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any

import config

SAYFA_DOSYASI = Path(__file__).with_name("static") / "yonetim.html"


def token() -> str:
    tohum = (config.ANA_SIR or "").encode("utf-8")
    return hmac.new(tohum, b"vekil-yonetim-sayfasi-v1", hashlib.sha256).hexdigest()[:32]


def token_dogru(aday: str | None) -> bool:
    beklenen = token()
    return bool(aday) and bool(beklenen) and hmac.compare_digest(str(aday).encode(), beklenen.encode())


def link() -> str:
    taban = (config.WEBHOOK_URL or "").rstrip("/")
    return f"{taban}/yonetim/{token()}" if taban else ""


def sayfa() -> str:
    return SAYFA_DOSYASI.read_text(encoding="utf-8")


def derle(istatistik: dict[str, Any] | None, *, hafiza_turu: str, ajan_cevrimici: bool,
          son_sureler: list[float]) -> dict[str, Any]:
    """Sayfanın JSON'u. istatistik None ise hafıza erişilemiyor demektir (sayfa bunu gösterir)."""
    return {
        "model": config.DEEPSEEK_MODEL,
        "dil": config.DIL,
        "hafiza": {"tur": hafiza_turu, "erisilebilir": istatistik is not None},
        "pc_ajani_cevrimici": ajan_cevrimici,
        "istatistik": istatistik,
        "son_sureler_sn": [round(s, 1) for s in son_sureler[-10:]],
    }
