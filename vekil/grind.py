"""/grind: Vekil'in son 10 anlamlı geliştirmesi (commit geçmişi), gün gün gruplu, en yeni üstte.

Kaynak sırası: (1) `git log` (lokal), (2) gelisim.json (Render .git tutmuyor; push öncesi
araclar/gelisim_yaz.py ile güncellenir), (3) GitHub API (GITHUB_TOKEN varsa), (4) yoksa ne eksik olduğunu söyler.
Ritüel "Gelişim listesi güncellendi" commit'leri elenir (bilgi taşımaz, ekranı doldururdu).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from zamanlayici import TR

REPO = os.getenv("GITHUB_REPO", "osmnabyram/VekilAi")
ADET = 10
_KOK = Path(__file__).resolve().parent
_AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
_GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _gurultu(mesaj: str) -> bool:
    """Bilgi taşımayan ritüel commit (listede yer kaplamasın)."""
    return re.sub(r"\s+", " ", mesaj).strip().lower().startswith("gelişim listesi güncellendi")


class GrindHatasi(Exception):
    pass


async def _git_log(n: int) -> list[tuple[str, str]]:
    if not (_KOK / ".git").exists():
        return []
    p = await asyncio.create_subprocess_exec(
        "git", "log", f"-{n}", "--format=%cI%x1f%s", cwd=str(_KOK),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    cikti, _ = await asyncio.wait_for(p.communicate(), 15)
    if p.returncode != 0:
        return []
    return [tuple(s.split("\x1f", 1)) for s in cikti.decode("utf-8", "replace").splitlines() if "\x1f" in s]


def _dosyadan(n: int) -> list[tuple[str, str]]:
    yol = _KOK / "gelisim.json"
    if not yol.exists():
        return []
    try:
        return [(k["zaman"], k["mesaj"]) for k in json.loads(yol.read_text(encoding="utf-8"))][:n]
    except (ValueError, KeyError):
        return []


async def _github(n: int) -> list[tuple[str, str]]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        return []
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"https://api.github.com/repos/{REPO}/commits", params={"per_page": n},
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if r.status_code != 200:
        raise GrindHatasi(f"GitHub geçmişi vermedi (HTTP {r.status_code}); GITHUB_TOKEN'ı kontrol et.")
    return [(x["commit"]["committer"]["date"], x["commit"]["message"].split("\n", 1)[0]) for x in r.json()]


def bicimle(kayitlar: list[tuple[str, str]]) -> str:
    """Gün gün gruplu, okunur liste: her gün başlık, altında '  SA:DK  mesaj' satırları."""
    satirlar = [f"Son {len(kayitlar)} geliştirme (en yeni üstte):"]
    son_gun = None
    for zaman, mesaj in kayitlar:
        t = datetime.fromisoformat(zaman.replace("Z", "+00:00")).astimezone(TR)
        gun = (t.year, t.month, t.day)
        if gun != son_gun:
            satirlar += ["", f"{t.day} {_AY[t.month - 1]} {_GUN[t.weekday()]}"]
            son_gun = gun
        m = re.sub(r"\s+", " ", mesaj).strip()
        if len(m) > 150:
            m = m[:149].rstrip() + "…"
        satirlar.append(f"• {t:%H:%M}  {m}")
    return "\n".join(satirlar)


async def metin(n: int = ADET) -> str:
    havuz = max(n * 4, 40)  # ritüel commit'ler elenince n tane anlamlı kayıt kalsın diye geniş çek
    kayitlar = await _git_log(havuz) or _dosyadan(havuz) or await _github(havuz)
    if not kayitlar:
        raise GrindHatasi("Geliştirme geçmişine ulaşamadım: sunucuda git geçmişi ve gelisim.json yok.")
    suzulmus = [k for k in kayitlar if not _gurultu(k[1])]
    return bicimle((suzulmus or kayitlar)[:n])
