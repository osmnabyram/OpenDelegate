"""Güncelleme bildirimi: Render yeni sürümü açınca kullanıcıya Telegram'dan "Vekil güncellendi" + yenilikler.

- Sürüm: Render'ın verdiği RENDER_GIT_COMMIT (kısa hali). Aynı sürümle yeniden başlama -> mesaj yok.
- Yenilikler: degisiklikler.json'daki en üstteki not (her kullanıcıya görünür değişiklikte Claude ekler).
  Not eklenmemişse yine kısa "güncellendim" gider.
- Son bildirilen (commit + not no) `ayarlar`'da (guncelleme:son): açılışta 1 okuma, bildirimde 1 yazma.
- Model çağrılmaz; sadece bulutta çalışır (main.calis).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

import zamanlayici

logger = logging.getLogger("guncelleme")
ANAHTAR = "guncelleme:son"
NOTLAR = Path(__file__).with_name("degisiklikler.json")


def notlari_oku(yol: Path = NOTLAR) -> list[dict[str, Any]]:
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [n for n in veri if isinstance(n, dict) and "no" in n and n.get("maddeler")] if isinstance(veri, list) else []


async def bildir(
    gonder: Callable[[str], Awaitable[None]],
    *,
    commit: str | None = None,
    notlar: list[dict[str, Any]] | None = None,
    oku: Callable[[str], Awaitable[dict[str, Any] | None]] = zamanlayici.ayar_oku,
    yaz: Callable[[str, dict[str, Any]], Awaitable[None]] = zamanlayici.ayar_yaz,
) -> bool:
    """Yeni sürümse haber verir. True = mesaj gönderildi."""
    commit = (os.getenv("RENDER_GIT_COMMIT", "") if commit is None else commit).strip()[:7]
    notlar = notlari_oku() if notlar is None else notlar
    son_not = notlar[0] if notlar else None
    kayit = await oku(ANAHTAR) or {}
    yeni_not = son_not is not None and son_not["no"] != kayit.get("not_no")
    yeni_commit = bool(commit) and commit != kayit.get("commit")
    if not (yeni_not or yeni_commit):
        return False
    satir = ["Vekil güncellendi" + (f" ({commit})" if commit else "") + "."]
    if yeni_not:
        # Arka arkaya birkaç push olup ara sürümler hiç açılmadıysa: görülmemiş notların HEPSİ (en fazla 5)
        onceki = kayit.get("not_no")
        gorulmemis = [n for n in notlar if onceki is None or n["no"] > onceki][:5] or [son_not]
        satir.append("Yenilikler:")
        for n in reversed(gorulmemis):  # eskiden yeniye
            satir += [f"• {m}" for m in n["maddeler"]]
    else:
        satir.append("Küçük düzeltmeler.")
    await gonder("\n".join(satir))
    try:
        await yaz(ANAHTAR, {"commit": commit or kayit.get("commit"),
                            "not_no": son_not["no"] if son_not else kayit.get("not_no")})
    except Exception as e:  # noqa: BLE001 — yazılamazsa bir sonraki açılışta tekrar haber verir, o kadar
        logger.warning("güncelleme durumu yazılamadı: %s", type(e).__name__)
    return True
