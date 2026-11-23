"""DeepSeek DSML sızıntısı onarımı.

DeepSeek bazen tool çağrısını API'nin `tool_calls` alanı yerine kendi iç formatında DÜZ METİN olarak
`content` içine yazar:

    <｜DSML｜function_calls>
    <｜DSML｜invoke name="ekran_goruntusu">
    <｜DSML｜parameter name="ekran" string="true">hepsi</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜function_calls>

Onarılmazsa bu metin kullanıcıya "cevap" diye gider ve tur biter (iş yarıda kalır). onar() bu metni gerçek
tool çağrılarına çevirir; çıkaramazsa en azından markup'ı temizler. Ayraçlar (｜, |) ve etiket adları
sürümden sürüme değişebildiği için desenler toleranslı.
"""

from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace
from typing import Any

_ETIKET = r"<[^<>]*?DSML[^<>]*?"
_INVOKE = re.compile(_ETIKET + r'invoke\s+name="([^"]+)"[^>]*>(.*?)' + r"</[^<>]*?DSML[^<>]*?invoke\s*>", re.S)
_PARAM = re.compile(
    _ETIKET + r'parameter\s+name="([^"]+)"(?:\s+string="(true|false)")?[^>]*>(.*?)' + r"</[^<>]*?DSML[^<>]*?parameter\s*>",
    re.S,
)
_HERHANGI_ETIKET = re.compile(r"</?[^<>]*?DSML[^<>]*>")


def sizinti_mi(metin: str | None) -> bool:
    return bool(metin) and "DSML" in metin and _HERHANGI_ETIKET.search(metin) is not None


def _deger(ham: str, string: str | None) -> Any:
    ham = ham.strip()
    if string == "true":
        return ham
    try:
        return json.loads(ham)  # string="false": sayı, bool, nesne, liste
    except ValueError:
        return ham


def cagrilari_cikar(metin: str) -> list[tuple[str, dict[str, Any]]]:
    """DSML metninden [(tool_adı, argümanlar)]; yoksa boş liste."""
    cagrilar = []
    for ad, govde in _INVOKE.findall(metin or ""):
        arg = {p_ad: _deger(deger, string or None) for p_ad, string, deger in _PARAM.findall(govde)}
        cagrilar.append((ad.strip(), arg))
    return cagrilar


def temizle(metin: str) -> str:
    """DSML bloğunu (ilk DSML etiketinden son DSML etiketine kadar) metinden çıkarır."""
    eslesmeler = list(_HERHANGI_ETIKET.finditer(metin or ""))
    if not eslesmeler:
        return (metin or "").strip()
    return (metin[: eslesmeler[0].start()] + metin[eslesmeler[-1].end():]).strip()


def onar(mesaj: Any) -> tuple[Any, bool]:
    """Model mesajında DSML sızıntısı varsa onarılmış mesaj döner: (mesaj, sızıntı_vardı_mı).

    Gerçek tool_calls zaten varsa dokunmaz (sadece içerikteki markup'ı temizler). Onarılan mesaj
    SimpleNamespace'tir; .content, .tool_calls[i].id / .type / .function.name / .function.arguments
    alanları OpenAI mesajıyla aynıdır."""
    icerik = getattr(mesaj, "content", None) or ""
    if not sizinti_mi(icerik):
        return mesaj, False
    temiz = temizle(icerik)
    mevcut = list(getattr(mesaj, "tool_calls", None) or [])
    if mevcut:
        return SimpleNamespace(content=temiz, tool_calls=mevcut), True
    cagrilar = [
        SimpleNamespace(id=f"dsml_{uuid.uuid4().hex[:12]}", type="function",
                        function=SimpleNamespace(name=ad, arguments=json.dumps(arg, ensure_ascii=False)))
        for ad, arg in cagrilari_cikar(icerik)
    ]
    return SimpleNamespace(content=temiz, tool_calls=cagrilar or None), True
