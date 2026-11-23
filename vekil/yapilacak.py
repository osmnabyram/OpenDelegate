"""Yapılacaklar: Kullanıcının "bana hatırlat / bugün şunu yapacağım" dediği işler.

- Sabah brifinginde "Yapılacaklar" bölümünde görünür (bugünün, gecikenlerin ve tarihsizlerin; yarınki
  işler "yarın" diye ön bilgi olarak).
- Kullanıcı "yaptım / bitti / hallettim" deyince silinir (bitti).
- Saklama: `ayarlar` 'yapilacaklar' (JSON). Açılışta 1 okuma, her değişiklikte 1 yazma (Neon kotası).
- Saatli anlık dürtme (ör. "15:00'te hatırlat") henüz YOK: sadece brifingde ve sorulunca görünür.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

import zamanlayici
from zamanlayici import TR

ANAHTAR = "yapilacaklar"
MAKS_IS = 40
MAKS_METIN = 200
GUN_ADI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _gun(d: date) -> str:
    from tarih import gun_yaz  # tek biçim: 'Salı (17 Kasım)'

    return gun_yaz(d)


@dataclass
class Yapilacaklar:
    oku: Callable[[str], Awaitable[dict[str, Any] | None]] = zamanlayici.ayar_oku
    yaz: Callable[[str, dict[str, Any]], Awaitable[None]] = zamanlayici.ayar_yaz
    simdi: Callable[[], datetime] = field(default=lambda: datetime.now(TR))
    isler: list[dict[str, Any]] = field(default_factory=list)

    async def yukle(self) -> None:
        self.isler = list((await self.oku(ANAHTAR) or {}).get("isler", []))

    async def _kaydet(self) -> None:
        await self.yaz(ANAHTAR, {"isler": self.isler})

    def _tarih(self, ham: Any) -> date | None:
        s = str(ham or "").strip().lower()
        bugun = self.simdi().date()
        if s in ("", "yok"):
            return None
        if s == "bugün" or s == "bugun":
            return bugun
        if s == "yarın" or s == "yarin":
            return bugun + timedelta(days=1)
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    def _satir(self, i: dict[str, Any]) -> str:
        t = f" ({_gun(date.fromisoformat(i['tarih']))})" if i.get("tarih") else ""
        return f"#{i['id']} {i['metin']}{t}"

    def listele(self) -> str:
        if not self.isler:
            return "Yapılacaklar listesi boş."
        return "Yapılacaklar:\n" + "\n".join(self._satir(i) for i in self.isler)

    async def ayarla(self, arg: dict[str, Any]) -> tuple[bool, str]:
        """yapilacak tool'u: ekle | listele | bitti."""
        eylem = str(arg.get("eylem") or "").strip()
        if eylem == "listele":
            return True, self.listele()
        if eylem == "ekle":
            metin = re.sub(r"\s+", " ", str(arg.get("metin") or "")).strip()[:MAKS_METIN]
            if not metin:
                return False, "Ne hatırlatayım? metin boş."
            if len(self.isler) >= MAKS_IS:
                return False, f"Listede zaten {MAKS_IS} iş var; önce bitenleri sil."
            tarih = self._tarih(arg.get("tarih"))
            yeni = {"id": max((i["id"] for i in self.isler), default=0) + 1, "metin": metin,
                    "tarih": tarih.isoformat() if tarih else None, "eklendi": self.simdi().date().isoformat()}
            self.isler.append(yeni)
            await self._kaydet()
            ne_zaman = f"{_gun(tarih)} sabahki brifingde" if tarih else "her sabahki brifingde (bitene kadar)"
            return True, f"Not aldım: {self._satir(yeni)}. {ne_zaman} göreceksin."
        if eylem == "bitti":
            hedef = arg.get("id")
            metin = str(arg.get("metin") or "").strip().casefold()
            if hedef is not None:
                bulunan = [i for i in self.isler if str(i["id"]) == str(hedef).lstrip("#")]
            else:
                bulunan = [i for i in self.isler if metin and metin in i["metin"].casefold()]
            if len(bulunan) != 1:
                ne = "hiçbiri" if not bulunan else f"{len(bulunan)} tanesi"
                return False, f"Hangisi bitti emin olamadım ({ne} eşleşti). {self.listele()}"
            self.isler.remove(bulunan[0])
            await self._kaydet()
            return True, f"Sildim: {bulunan[0]['metin']}."
        return False, "eylem şunlardan biri olmalı: ekle, listele, bitti."

    def brifing_bolumu(self, gun: date) -> tuple[str, list[str]]:
        """(ilk satır özeti, maddeler). Bugün/geciken/tarihsiz + yarınkiler ön bilgi."""
        bugun, yarin, gecikmis = [], [], []
        for i in self.isler:
            t = date.fromisoformat(i["tarih"]) if i.get("tarih") else None
            if t is None or t == gun:
                bugun.append(i["metin"])
            elif t < gun:
                gecikmis.append(f"{i['metin']} (gecikti: {_gun(t)})")
            elif t == gun + timedelta(days=1):
                yarin.append(f"Yarın: {i['metin']}")
        maddeler = gecikmis + bugun + yarin
        sayi = len(gecikmis) + len(bugun)
        return (f"{sayi} iş" if sayi else ""), maddeler or ["Bugün için not ettiğin iş yok."]
