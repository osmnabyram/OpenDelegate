"""Dışarıya (internete) giden HTTP indirmeleri — tek ve ortak güvenlik kapısı.

onedrive_yukle, webde_oku ve indir hepsi buradan geçer; korumalar aynıdır:
- sadece http/https,
- sadece genel internet adresleri (localhost, 10.x, 172.16-31.x, 192.168.x,
  169.254.x / bulut metadata, ::1, fc00::/7 ... reddedilir),
- her yönlendirmede kontrol baştan yapılır,
- boyut limiti hem Content-Length'e hem de gerçekten gelen byte'a uygulanır.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx

MAKS_YONLENDIRME = 5
# Dürüst kimlik: kendini tarayıcı gibi göstermiyoruz (Wikimedia gibi siteler bunu ister).
TARAYICI = "Mozilla/5.0 (compatible; VekilBot/1.0; +https://github.com/osmnabyram/VekilAi) kisisel-asistan"


class AgHatasi(Exception):
    pass


@dataclass
class Indirilen:
    veri: bytes
    ad: str  # URL'den (ya da Content-Disposition'dan) çıkan dosya adı
    tur: str  # Content-Type (parametresiz, küçük harf)
    url: str  # yönlendirmelerden sonraki son adres


def _istemci(**kw: Any) -> httpx.AsyncClient:
    """HTTP istemcisi fabrikası (testlerde sahte transport enjekte edilir)."""
    return httpx.AsyncClient(**kw)


def boyut_yaz(bayt: float) -> str:
    for birim in ("B", "KB", "MB", "GB"):
        if bayt < 1024:
            return f"{bayt:.0f} {birim}" if birim == "B" else f"{bayt:.1f} {birim}"
        bayt /= 1024
    return f"{bayt:.1f} TB"


async def url_guvenli(url: str) -> None:
    """Sadece http(s) ve sadece genel internet adresleri (iç ağ / metadata yok)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise AgHatasi("Sadece http/https URL'leri kullanılabilir.")
    try:
        adresler = await asyncio.to_thread(
            socket.getaddrinfo, p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise AgHatasi(f"Alan adı çözülemedi: {p.hostname}")
    for *_, sockaddr in adresler:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise AgHatasi("Bu adres iç ağa/yerel ağa çıkıyor, oraya gitmem.")


def _dosya_adi(url: str, disposition: str | None) -> str:
    if disposition:
        m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.I) or re.search(
            r'filename="?([^";]+)"?', disposition, re.I
        )
        if m:
            return unquote(m.group(1).strip().strip('"')).rsplit("/", 1)[-1] or "indirilen_dosya"
    ad = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    return ad or "indirilen_dosya"


async def indir(url: str, limit: int, zaman_asimi: float = 60) -> Indirilen:
    """URL'yi `limit` byte sınırıyla belleğe indirir."""
    async with _istemci(timeout=zaman_asimi, follow_redirects=False) as istemci:
        for _ in range(MAKS_YONLENDIRME + 1):
            await url_guvenli(url)  # her yönlendirmede yeniden kontrol
            async with istemci.stream("GET", url, headers={"User-Agent": TARAYICI}) as yanit:
                if yanit.is_redirect and "location" in yanit.headers:
                    url = urljoin(url, yanit.headers["location"])
                    continue
                if yanit.status_code >= 400:
                    raise AgHatasi(f"İndirme başarısız (HTTP {yanit.status_code}).")
                if int(yanit.headers.get("content-length") or 0) > limit:
                    raise AgHatasi(f"Dosya çok büyük, limit {boyut_yaz(limit)}.")
                parcalar, toplam = [], 0
                async for parca in yanit.aiter_bytes():
                    toplam += len(parca)
                    if toplam > limit:
                        raise AgHatasi(f"Dosya çok büyük, limit {boyut_yaz(limit)}.")
                    parcalar.append(parca)
                return Indirilen(
                    veri=b"".join(parcalar),
                    ad=_dosya_adi(url, yanit.headers.get("content-disposition")),
                    tur=yanit.headers.get("content-type", "").split(";")[0].strip().lower(),
                    url=str(url),
                )
    raise AgHatasi("Çok fazla yönlendirme.")
