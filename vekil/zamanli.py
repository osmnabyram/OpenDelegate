"""Saatli hatırlatma ve zamanlanmış görev: "15:00'te dürt", "her gün 22:00'de rapor klasörünü yedekle".

- tur 'hatirlat': saati gelince kullanıcıya Telegram mesajı.
- tur 'gorev'   : saati gelince Vekil işi KENDİSİ yapar (Kullanıcı o an istemiş gibi bir ajan turu; normal risk
                  kuralları geçerli).
- tekrar: 'yok' | 'gunluk' | 'haftalik'.
- Saklama: `ayarlar` 'zamanli' (açılışta 1 okuma, değişiklikte 1 yazma). Saat kontrolü bellekte, 20 sn'de bir:
  Neon'a her tikte sorgu gitmez.
- Render yeniden başlar / uyursa: 6 saate kadar geciken iş "gecikmeli" diye hemen yapılır; daha eskisi atlanır
  (tekrarlıysa bir sonraki zamana geçer).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Awaitable, Callable

import zamanlayici
from tarih import gun_yaz
from zamanlayici import TR

logger = logging.getLogger("zamanli")
ANAHTAR = "zamanli"
TIK_SN = 20.0
GECIKME_SINIRI = timedelta(hours=6)
MAKS_KAYIT = 50
TEKRAR = {"yok": None, "gunluk": timedelta(days=1), "haftalik": timedelta(days=7)}
TEKRAR_ADI = {"gunluk": "her gün", "haftalik": "her hafta"}


@dataclass
class Zamanli:
    calistir: Callable[[dict[str, Any], bool], Awaitable[None]]  # (kayıt, gecikmeli_mi)
    oku: Callable[[str], Awaitable[dict[str, Any] | None]] = zamanlayici.ayar_oku
    yaz: Callable[[str, dict[str, Any]], Awaitable[None]] = zamanlayici.ayar_yaz
    simdi: Callable[[], datetime] = field(default=lambda: datetime.now(TR))
    uyu: Callable[[float], Awaitable[None]] = asyncio.sleep
    kayitlar: list[dict[str, Any]] = field(default_factory=list)
    _gorevler: set[asyncio.Task[Any]] = field(default_factory=set)

    async def yukle(self) -> None:
        self.kayitlar = list((await self.oku(ANAHTAR) or {}).get("kayitlar", []))

    async def _kaydet(self) -> None:
        try:
            await self.yaz(ANAHTAR, {"kayitlar": self.kayitlar})
        except Exception as e:  # noqa: BLE001 — bellekte devam
            logger.warning("zamanlı kayıtlar yazılamadı: %s", type(e).__name__)

    # --- zaman çözme ------------------------------------------------------------

    def zaman_coz(self, ham: str) -> datetime:
        """'15:00' (bugün, geçtiyse yarın) | 'YYYY-MM-DD HH:MM' | 'yarın 09:30'. Geçmiş zaman kabul edilmez."""
        s = re.sub(r"\s+", " ", (ham or "").strip().lower())
        s = re.sub(r"^(\d{4}-\d{2}-\d{2})t", r"\1 ", s)  # ISO '2026-11-15T15:00' de olur
        simdi = self.simdi()
        m = re.fullmatch(r"(?:(bugün|bugun|yarın|yarin) )?(\d{1,2})[:.](\d{2})", s)
        if m:
            saat = time(int(m.group(2)), int(m.group(3)))
            gun = simdi.date() + (timedelta(days=1) if m.group(1) in ("yarın", "yarin") else timedelta())
            z = datetime.combine(gun, saat, TR)
            if m.group(1) is None and z <= simdi:  # sadece saat verildi ve geçti: yarın
                z += timedelta(days=1)
        else:
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{1,2})[:.](\d{2})", s)
            if not m:
                raise ValueError("Zamanı 'SS:DD' (ör. 15:00), 'yarın 09:30' ya da 'YYYY-AA-GG SS:DD' olarak ver.")
            z = datetime.combine(date.fromisoformat(m.group(1)), time(int(m.group(2)), int(m.group(3))), TR)
        if z <= simdi:
            raise ValueError(f"Bu zaman geçmiş ({gun_yaz(z.date())} {z:%H:%M}); ileri bir zaman ver.")
        return z

    def _yaz_kayit(self, k: dict[str, Any]) -> str:
        z = datetime.fromisoformat(k["zaman"])
        ne = "hatırlatma" if k["tur"] == "hatirlat" else "görev"
        tekrar = f", {TEKRAR_ADI[k['tekrar']]}" if k.get("tekrar") in TEKRAR_ADI else ""
        acil = (" (ACİL, sesli zincir)" if k.get("acil") else "") + (" (telefonla arayarak)" if k.get("ara") else "")
        return f"#{k['id']} {gun_yaz(z.date())} {z:%H:%M} · {ne}{tekrar}{acil}: {k['metin']}"

    # --- tool ---------------------------------------------------------------------

    async def ayarla(self, arg: dict[str, Any]) -> tuple[bool, str]:
        """zamanla tool'u: ekle | listele | sil."""
        eylem = str(arg.get("eylem") or "").strip()
        if eylem == "listele":
            if not self.kayitlar:
                return True, "Zamanlanmış hatırlatma ya da görev yok."
            return True, "Zamanlananlar:\n" + "\n".join(self._yaz_kayit(k) for k in sorted(
                self.kayitlar, key=lambda k: k["zaman"]))
        if eylem == "sil":
            hedef = str(arg.get("id") or "").lstrip("#")
            bulunan = [k for k in self.kayitlar if str(k["id"]) == hedef]
            if not bulunan:
                return False, f"#{hedef} diye bir kayıt yok. " + (await self.ayarla({"eylem": "listele"}))[1]
            self.kayitlar.remove(bulunan[0])
            await self._kaydet()
            return True, f"Sildim: {self._yaz_kayit(bulunan[0])}"
        if eylem == "ekle":
            metin = re.sub(r"\s+", " ", str(arg.get("metin") or "")).strip()[:500]
            if not metin:
                return False, "Ne hatırlatayım / ne yapayım? metin boş."
            tur = str(arg.get("tur") or "hatirlat").strip()
            tekrar = str(arg.get("tekrar") or "yok").strip()
            if tur not in ("hatirlat", "gorev"):
                return False, "tur 'hatirlat' ya da 'gorev' olmalı."
            if tekrar not in TEKRAR:
                return False, "tekrar 'yok', 'gunluk' ya da 'haftalik' olmalı."
            if len(self.kayitlar) >= MAKS_KAYIT:
                return False, f"Zaten {MAKS_KAYIT} zamanlanmış kayıt var; önce eskileri sil."
            try:
                z = self.zaman_coz(str(arg.get("zaman") or ""))
            except ValueError as e:
                return False, str(e)
            k = {"id": max((x["id"] for x in self.kayitlar), default=0) + 1, "zaman": z.isoformat(), "tur": tur,
                 "metin": metin, "tekrar": tekrar, "eklendi": self.simdi().isoformat(),
                 "acil": bool(arg.get("acil")), "ara": bool(arg.get("ara"))}
            self.kayitlar.append(k)
            await self._kaydet()
            return True, f"Tamam, zamanladım: {self._yaz_kayit(k)}"
        return False, "eylem şunlardan biri olmalı: ekle, listele, sil."

    # --- döngü ----------------------------------------------------------------------

    async def tik(self) -> None:
        simdi = self.simdi()
        degisti = False
        for k in list(self.kayitlar):
            z = datetime.fromisoformat(k["zaman"])
            if z > simdi:
                continue
            gecikme = simdi - z
            adim = TEKRAR.get(k.get("tekrar") or "yok")
            # Önce kaydı ilerlet/sil ve KAYDET, sonra çalıştır: Render tam o an yeniden başlarsa iki kez olmasın.
            if adim:
                while z <= simdi:
                    z += adim
                k["zaman"] = z.isoformat()
            else:
                self.kayitlar.remove(k)
            degisti = True
            if gecikme > GECIKME_SINIRI:
                logger.info("zamanlı #%s çok gecikti (%s), atlandı", k["id"], gecikme)
                continue
            gorev = asyncio.ensure_future(self._guvenli(dict(k), gecikme > timedelta(minutes=2)))
            self._gorevler.add(gorev)
            gorev.add_done_callback(self._gorevler.discard)
        if degisti:
            await self._kaydet()

    async def _guvenli(self, k: dict[str, Any], gecikmeli: bool) -> None:
        try:
            await self.calistir(k, gecikmeli)
        except Exception:  # noqa: BLE001 — bir kayıt diğerlerini durdurmasın
            logger.exception("zamanlı #%s çalıştırılamadı", k.get("id"))

    async def calis(self) -> None:
        await self.yukle()
        await self.dongu()

    async def dongu(self) -> None:
        """Kayıtlar zaten yüklüyse (main açılışta yükler) sadece döngü."""
        logger.info("Zamanlı hatırlatıcı açık (%d kayıt)", len(self.kayitlar))
        while True:
            try:
                await self.tik()
            except Exception:  # noqa: BLE001
                logger.exception("zamanlı tik hatası")
            await self.uyu(TIK_SN)

    def bugun(self, gun: date) -> list[str]:
        """Brifing için: bugün saati gelecek olanlar ('15:00 hatırlatma: X')."""
        satir = []
        for k in sorted(self.kayitlar, key=lambda k: k["zaman"]):
            z = datetime.fromisoformat(k["zaman"])
            if z.date() == gun:
                ne = "hatırlatma" if k["tur"] == "hatirlat" else "yapacağım"
                satir.append(f"{z:%H:%M} {ne}: {k['metin']}")
        return satir
