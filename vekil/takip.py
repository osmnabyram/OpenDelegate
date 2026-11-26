"""OpenDelegate'in kendiliğinden yazması: konuştuğumuz ama sonucu belli olmayan bir konuyu ara ara sorar.

- Açık konular: konuşma özetlerinden ve son mesajlardan (LLM ile, günde en fazla 1 kez) çıkarılan "sonucu henüz
  belli olmayan" kişisel konular (sınav, başvuru, görüşme, plan, sorun...) + yapılacaklar listesi.
- Kullanıcının mesajında konunun kelimeleri geçerse "konuşuldu" sayılır (son temas).
- KONU_BOSTA gün konuşulmamış konu varsa, sadece gündüz (11-20), haftada EN FAZLA 1 kez sorar:
  "Geçen hafta X'ten bahsetmiştin, ne oldu?"
- Susturma kelimeye bağlı değil: model kullanıcının cevabını bağlamdan anlar ve konu_takip tool'unu çağırır
  (son sorulan konu sistem promptunda).
- Saklama: `ayarlar` 'konu_takip' (yeni tablo yok).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

import zamanlayici
from zamanlayici import TR

logger = logging.getLogger("takip")

# --------------------------------------------------------------------------
# Konu takibi
# --------------------------------------------------------------------------

KONU_ANAHTAR = "konu_takip"
KONU_BOSTA = timedelta(days=4)      # bu kadar konuşulmamış açık konu sorulur
NUDGE_ARALIK = timedelta(days=7)    # haftada en fazla 1
AYNI_KONU_TEKRAR = timedelta(days=21)
CEVAP_SURESI = timedelta(hours=72)  # Kullanıcının "sorma artık" cevabı bu süre içinde son soruya bağlanır
SAAT_ARALIGI = (11, 20)
_KOK_DISI = frozenset("için icin olan ile gibi daha sonra önce kadar şunu bunu vekil kanka".split())


def _kokler(metin: str) -> set[str]:
    k = re.findall(r"[0-9a-zçğıöşü]+", (metin or "").replace("İ", "i").replace("I", "ı").lower())
    return {w[:5] for w in k if len(w) >= 4 and w not in _KOK_DISI}


@dataclass
class KonuTakip:
    """kaynak() -> [{'anahtar','metin','nerede','baslangic'(iso)}] açık konular."""
    gonder: Callable[[str], Awaitable[None]]
    kaynak: Callable[[], Awaitable[list[dict[str, Any]]]]
    oku: Callable[[str], Awaitable[dict[str, Any] | None]] = zamanlayici.ayar_oku
    yaz: Callable[[str, dict[str, Any]], Awaitable[None]] = zamanlayici.ayar_yaz
    simdi: Callable[[], datetime] = field(default=lambda: datetime.now(TR))
    uyu: Callable[[float], Awaitable[None]] = asyncio.sleep
    d: dict[str, Any] = field(default_factory=dict)
    _son_konular: list[dict[str, Any]] = field(default_factory=list)

    async def yukle(self) -> None:
        self.d = await self.oku(KONU_ANAHTAR) or {}
        for k, v in (("temas", {}), ("sessiz", []), ("sorulan", {}), ("son_nudge", None), ("hepsi_sessiz", False)):
            self.d.setdefault(k, v)

    async def _kaydet(self) -> None:
        try:
            await self.yaz(KONU_ANAHTAR, self.d)
        except Exception as e:  # noqa: BLE001
            logger.warning("konu takip kaydedilemedi: %s", type(e).__name__)

    def son_soru_satiri(self) -> str:
        """Sistem promptuna: son sorulan konu (Kullanıcının 'artık sorma', 'o iş bitti' gibi cevabını model bağlasın)."""
        son = self.d.get("son_soru")
        if not son or self.simdi() - datetime.fromisoformat(son["zaman"]) > CEVAP_SURESI:
            return ""
        return (f"Son kendiliğinden sorduğun açık konu: '{son['metin']}' ({son['zaman'][:10]}). Kullanıcı bunu bir daha "
                "sormamanı isterse konu_takip(eylem=sustur); hiçbir şeyi sormamanı isterse hepsini_sustur.")

    async def ayarla(self, arg: dict[str, Any]) -> tuple[bool, str]:
        """konu_takip tool'u (model niyeti bağlamdan anlar; anahtar kelime yok): sustur | hepsini_sustur | ac."""
        eylem = str(arg.get("eylem") or "").strip()
        if eylem == "hepsini_sustur":
            self.d["hepsi_sessiz"] = True
            await self._kaydet()
            return True, "Açık konular için artık kendiliğimden sormayacağım."
        if eylem == "ac":
            self.d["hepsi_sessiz"] = False
            await self._kaydet()
            return True, "Açık kalan konuları yine ara ara soracağım (haftada en fazla bir kez)."
        if eylem == "sustur":
            son = self.d.get("son_soru")
            if not son:
                return False, "Yakın zamanda sorduğum bir konu yok."
            if son["anahtar"] not in self.d["sessiz"]:
                self.d["sessiz"].append(son["anahtar"])
            self.d["son_soru"] = None
            await self._kaydet()
            return True, f"'{son['metin']}' için bir daha sormayacağım."
        return False, "eylem şunlardan biri olmalı: sustur, hepsini_sustur, ac."

    async def mesaj(self, metin: str) -> str | None:
        """Kullanıcının her mesajı: geçen açık konuları 'konuşuldu' işaretler. (Susturma artık modelde: ayarla.)"""
        simdi = self.simdi()
        kokler = _kokler(metin)
        if kokler and self._son_konular:
            degisti = False
            for k in self._son_konular:
                kk = _kokler(k["metin"])
                if kk and len(kk & kokler) >= min(2, len(kk)):
                    onceki = self.d["temas"].get(k["anahtar"])
                    if not onceki or simdi - datetime.fromisoformat(onceki) > timedelta(hours=6):
                        self.d["temas"][k["anahtar"]] = simdi.isoformat()
                        degisti = True
            if degisti:
                await self._kaydet()
        return None

    def sorma_zamani(self) -> bool:
        """Şu an bir soru sorulabilir mi (susturulmadı, gündüz, haftalık hak dolmamış)."""
        simdi = self.simdi()
        if self.d.get("hepsi_sessiz") or not (SAAT_ARALIGI[0] <= simdi.hour < SAAT_ARALIGI[1]):
            return False
        son = self.d.get("son_nudge")
        return not son or simdi - datetime.fromisoformat(son) >= NUDGE_ARALIK

    def _bosta(self, k: dict[str, Any], simdi: datetime) -> timedelta:
        zamanlar = [k.get("baslangic"), self.d["temas"].get(k["anahtar"]), self.d["sorulan"].get(k["anahtar"])]
        son = max(datetime.fromisoformat(z) if "T" in z else datetime.fromisoformat(z + "T00:00:00+03:00")
                  for z in zamanlar if z)
        if son.tzinfo is None:
            son = son.replace(tzinfo=TR)
        return simdi - son

    async def tik(self) -> None:
        simdi = self.simdi()
        try:
            self._son_konular = await self.kaynak()
        except Exception as e:  # noqa: BLE001
            logger.warning("açık konular alınamadı: %s", type(e).__name__)
            return
        if self.d.get("hepsi_sessiz") or not (SAAT_ARALIGI[0] <= simdi.hour < SAAT_ARALIGI[1]):
            return
        if self.d.get("son_nudge") and simdi - datetime.fromisoformat(self.d["son_nudge"]) < NUDGE_ARALIK:
            return
        adaylar = []
        for k in self._son_konular:
            if k["anahtar"] in self.d["sessiz"]:
                continue
            sorulan = self.d["sorulan"].get(k["anahtar"])
            if sorulan and simdi - datetime.fromisoformat(sorulan) < AYNI_KONU_TEKRAR:
                continue
            bosta = self._bosta(k, simdi)
            if bosta >= KONU_BOSTA:
                adaylar.append((bosta, k))
        if not adaylar:
            return
        bosta, k = max(adaylar, key=lambda t: t[0])
        self.d["son_nudge"] = simdi.isoformat()
        self.d["sorulan"][k["anahtar"]] = simdi.isoformat()
        self.d["son_soru"] = {"anahtar": k["anahtar"], "metin": k["metin"], "zaman": simdi.isoformat()}
        await self._kaydet()
        soru = (k.get("soru") or "").strip() or (
            f"Efendim, aklıma geldi: {k.get('nerede', 'listende')} duran '{k['metin']}' ne oldu? "
            f"{bosta.days} gündür konuşmadık.")
        await self.gonder(f"{soru}\n(İstemezsen söylemen yeterli, bunu bir daha sormam.)")

    async def dongu(self) -> None:
        while True:
            try:
                await self.tik()
            except Exception:  # noqa: BLE001
                logger.exception("konu takip tik hatası")
            await self.uyu(3600)
