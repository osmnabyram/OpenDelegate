"""Salt okunur takvim: Google Takvim (ya da başka) gizli iCal adresinden etkinlikleri okur.

Kurulum: TAKVIM_ICS_URL ortam değişkenine takvimin "gizli iCal adresi"ni (https) yazın; birden fazlaysa virgülle ayırın.
Google Takvim: Ayarlar -> takvimi seç -> "Takvimi entegre et" -> "iCal biçiminde gizli adres".
Okuma-yazma yok, Google hesabına giriş ya da izin tutulmaz; adresi bilen herkes takvimi okuyabilir, bu yüzden adres
yalnızca ortam değişkeninde durur, loga yazılmaz. Adres sızarsa Google'da "gizli adresi sıfırla".

shortcut: tekrarlayan kurallardan DAILY/WEEKLY/MONTHLY/YEARLY (INTERVAL, COUNT, UNTIL, BYDAY, BYMONTHDAY, EXDATE) desteklenir;
BYSETPOS/BYWEEKNO/BYYEARDAY ya da saatlik kurallar için yalnızca ilk etkinlik gösterilir. TZID'li saatler için sistemde saat dilimi
verisi yoksa Türkiye saati varsayılır. Yükseltmek için: `recurring-ical-events` paketi.
"""

from __future__ import annotations

import calendar
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import ag
import config
import tools
from zamanlayici import TR

logger = logging.getLogger("vekil.takvim")

GUNLER = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")
ONBELLEK_SN = 300  # aynı adres 5 dakikada bir indirilir
MAKS_BOYUT = 5 * 1024 * 1024
MAKS_GUN = 31
MAKS_DONGU = 6000  # tek kural için üretilen en çok örnek (sonsuz döngü koruması)
_HAFTA = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_DESTEKSIZ = ("BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND")


@dataclass(frozen=True)
class Etkinlik:
    baslangic: datetime  # TR saatiyle (tüm gün etkinlikte günün 00:00'ı)
    bitis: datetime
    tum_gun: bool
    baslik: str
    yer: str = ""


# --------------------------------------------------------------------------
# iCal ayrıştırma
# --------------------------------------------------------------------------

def _satirlar(metin: str) -> list[tuple[str, dict[str, str], str]]:
    """Katlanmış satırları açar; (ad, parametreler, değer) döner."""
    acik: list[str] = []
    for s in metin.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if s[:1] in (" ", "\t") and acik:
            acik[-1] += s[1:]
        elif s:
            acik.append(s)
    sonuc = []
    for s in acik:
        if ":" not in s:
            continue
        sol, deger = s.split(":", 1)
        parcalar = sol.split(";")
        param = {}
        for p in parcalar[1:]:
            if "=" in p:
                a, b = p.split("=", 1)
                param[a.upper()] = b.strip('"')
        sonuc.append((parcalar[0].upper(), param, deger))
    return sonuc


def _metin(deger: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), deger).strip()


def _zone(tzid: str | None):
    if not tzid or tzid in ("Europe/Istanbul", "Turkey", "Asia/Istanbul"):
        return TR
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tzid)
    except Exception:  # noqa: BLE001 - saat dilimi verisi yok: Türkiye saati
        return TR


def _tarih(deger: str, param: dict[str, str]) -> tuple[datetime, bool]:
    """iCal tarih/saatini (aware datetime, tüm_gün_mü) olarak okur. Tüm gün: TR 00:00."""
    d = deger.strip()
    if param.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", d):
        return datetime.strptime(d[:8], "%Y%m%d").replace(tzinfo=TR), True
    utc = d.endswith("Z")
    g = datetime.strptime(d.rstrip("Z"), "%Y%m%dT%H%M%S")
    return g.replace(tzinfo=timezone.utc if utc else _zone(param.get("TZID"))), False


def _kural(deger: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in deger.split(";") if "=" in p)


@dataclass
class _Ham:
    uid: str = ""
    baslik: str = ""
    yer: str = ""
    bas: datetime | None = None
    bit: datetime | None = None
    tum_gun: bool = False
    kural: dict[str, str] | None = None
    haric: tuple[datetime, ...] = ()
    yerine: datetime | None = None  # RECURRENCE-ID: bu örneğin yerine geçer
    iptal: bool = False


def _etkinlikler(metin: str) -> list[_Ham]:
    sonuc: list[_Ham] = []
    mevcut: _Ham | None = None
    haric: list[datetime] = []
    for ad, param, deger in _satirlar(metin):
        if ad == "BEGIN" and deger.upper() == "VEVENT":
            mevcut, haric = _Ham(), []
        elif ad == "END" and deger.upper() == "VEVENT" and mevcut is not None:
            mevcut.haric = tuple(haric)
            if mevcut.bas is not None:
                if mevcut.bit is None:
                    mevcut.bit = mevcut.bas + (timedelta(days=1) if mevcut.tum_gun else timedelta(0))
                sonuc.append(mevcut)
            mevcut = None
        elif mevcut is not None:
            try:
                if ad == "UID":
                    mevcut.uid = deger
                elif ad == "SUMMARY":
                    mevcut.baslik = _metin(deger)
                elif ad == "LOCATION":
                    mevcut.yer = _metin(deger)
                elif ad == "STATUS":
                    mevcut.iptal = deger.strip().upper() == "CANCELLED"
                elif ad == "DTSTART":
                    mevcut.bas, mevcut.tum_gun = _tarih(deger, param)
                elif ad == "DTEND":
                    mevcut.bit, _ = _tarih(deger, param)
                elif ad == "RRULE":
                    mevcut.kural = _kural(deger)
                elif ad == "EXDATE":
                    haric += [_tarih(x, param)[0] for x in deger.split(",") if x.strip()]
                elif ad == "RECURRENCE-ID":
                    mevcut.yerine = _tarih(deger, param)[0]
            except ValueError:
                logger.debug("bozuk iCal satırı atlandı: %s", ad)
    return sonuc


# --------------------------------------------------------------------------
# Tekrar kuralları
# --------------------------------------------------------------------------

def _nci_gun(yil: int, ay: int, haftagunu: int, n: int) -> date | None:
    """Ayın n'inci (n<0: sondan) haftagunu; yoksa None."""
    gunler = [d for d in range(1, calendar.monthrange(yil, ay)[1] + 1) if date(yil, ay, d).weekday() == haftagunu]
    try:
        return date(yil, ay, gunler[n - 1 if n > 0 else n])
    except IndexError:
        return None


def _byday(kural: dict[str, str]) -> list[tuple[int, int]]:
    """BYDAY -> [(sıra, haftagünü)]; sıra 0 = her hafta."""
    sonuc = []
    for p in kural.get("BYDAY", "").split(","):
        m = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", p.strip().upper())
        if m:
            sonuc.append((int(m.group(1) or 0), _HAFTA[m.group(2)]))
    return sonuc


def _gunler(h: _Ham, bitis_siniri: date) -> list[date]:
    """Kuralın ürettiği başlangıç günleri (dtstart dahil), `bitis_siniri` gününe kadar. Desteklenmezse yalnızca ilki."""
    k = h.kural or {}
    ilk = h.bas.astimezone(h.bas.tzinfo).date()
    if not k or any(x in k for x in _DESTEKSIZ):
        return [ilk]
    sik, aralik = k.get("FREQ", ""), max(1, int(k.get("INTERVAL", "1") or 1))
    sayi = int(k["COUNT"]) if k.get("COUNT", "").isdigit() else None
    son = None
    if k.get("UNTIL"):
        try:
            son = _tarih(k["UNTIL"], {})[0].astimezone(h.bas.tzinfo).date()
        except ValueError:
            pass
    sinir = min(bitis_siniri, son) if son else bitis_siniri
    bg = _byday(k)
    gun_no = [int(x) for x in k.get("BYMONTHDAY", "").split(",") if x.lstrip("-").isdigit()]
    adaylar: list[date] = []

    def uygun(d: date) -> bool:
        return d >= ilk

    if sik == "DAILY":
        d = ilk
        while d <= sinir and len(adaylar) < MAKS_DONGU:
            adaylar.append(d)
            d += timedelta(days=aralik)
    elif sik == "WEEKLY":
        pazartesi = ilk - timedelta(days=ilk.weekday())
        gunler = sorted({g for _, g in bg}) or [ilk.weekday()]
        hafta = pazartesi
        while hafta <= sinir and len(adaylar) < MAKS_DONGU:
            adaylar += [d for d in (hafta + timedelta(days=g) for g in gunler) if uygun(d)]
            hafta += timedelta(weeks=aralik)
    elif sik in ("MONTHLY", "YEARLY"):
        ay_indeksi = ilk.year * 12 + ilk.month - 1
        adim = aralik * (12 if sik == "YEARLY" else 1)
        while len(adaylar) < MAKS_DONGU:
            yil, ay = divmod(ay_indeksi, 12)
            ay += 1
            if date(yil, ay, 1) > sinir:
                break
            if sik == "YEARLY" and not bg and not gun_no:
                gunler = [date(yil, ilk.month, ilk.day)] if ay == ilk.month and (ilk.month != 2 or ilk.day <= calendar.monthrange(yil, 2)[1]) else []
            elif bg:
                gunler = [d for n, hg in bg if (d := (_nci_gun(yil, ay, hg, n) if n else None)) is not None]
                if any(n == 0 for n, _ in bg):  # "her X günü" (sıra yok): ayın tüm o günleri
                    gunler += [date(yil, ay, d) for d in range(1, calendar.monthrange(yil, ay)[1] + 1)
                               if date(yil, ay, d).weekday() in [hg for n, hg in bg if n == 0]]
            else:
                ay_gun = calendar.monthrange(yil, ay)[1]
                gunler = [date(yil, ay, g if g > 0 else ay_gun + 1 + g) for g in (gun_no or [ilk.day])
                          if 1 <= (g if g > 0 else ay_gun + 1 + g) <= ay_gun]
            adaylar += [d for d in sorted(set(gunler)) if uygun(d)]
            ay_indeksi += adim
    else:
        return [ilk]
    adaylar = sorted(set(adaylar))
    if sayi is not None:
        adaylar = adaylar[:sayi]
    return [d for d in adaylar if d <= sinir]


def _tr(dt: datetime) -> datetime:
    return dt.astimezone(TR)


def _genislet(hamlar: list[_Ham], bas: datetime, son: datetime) -> list[Etkinlik]:
    """[bas, son) ile kesişen etkinlikler (tekrarlar açılmış, TR saatiyle)."""
    degisen = {(h.uid, _tr(h.yerine)) for h in hamlar if h.yerine is not None}
    sonuc: list[Etkinlik] = []
    for h in hamlar:
        if h.iptal:
            continue
        sure = h.bit - h.bas
        if h.yerine is not None or not h.kural:
            baslar = [h.bas]
        else:
            baslar = []
            haric = {_tr(x) for x in h.haric}
            for g in _gunler(h, son.date() + timedelta(days=1)):
                b = datetime.combine(g, h.bas.timetz()) if h.bas.tzinfo else datetime.combine(g, h.bas.time())
                b = b.replace(tzinfo=h.bas.tzinfo)
                if _tr(b) in haric or (h.uid, _tr(b)) in degisen:
                    continue
                baslar.append(b)
        for b in baslar:
            bt, et = _tr(b), _tr(b + sure)
            if h.tum_gun:  # tüm gün: günün 00:00'ı (TR), saat kaymasından etkilenmesin
                bt = datetime.combine(b.date(), datetime.min.time(), tzinfo=TR)
                et = bt + sure
            if et > bas and bt < son or (bt == et and bas <= bt < son):
                sonuc.append(Etkinlik(bt, et, h.tum_gun, h.baslik or "(başlıksız)", h.yer))
    return sorted(sonuc, key=lambda e: (e.baslangic, e.baslik))


def ayristir(metin: str, bas: datetime, son: datetime) -> list[Etkinlik]:
    return _genislet(_etkinlikler(metin), bas, son)


# --------------------------------------------------------------------------
# Getirme (önbellekli) ve çıktı
# --------------------------------------------------------------------------

_onbellek: dict[str, tuple[float, str]] = {}


def adresler() -> list[str]:
    ham = getattr(config, "TAKVIM_ICS_URL", "") or ""
    return [a.strip().replace("webcal://", "https://", 1) for a in ham.split(",") if a.strip()]


def ayarli() -> bool:
    return bool(adresler())


class TakvimHatasi(Exception):
    """Kullanıcıya gösterilebilir (adres içermeyen) hata."""


async def _getir(url: str) -> str:
    if not url.lower().startswith("https://"):
        raise TakvimHatasi("Takvim adresi https ile başlamalı.")
    simdi = time.monotonic()
    kayit = _onbellek.get(url)
    if kayit and simdi - kayit[0] < ONBELLEK_SN:
        return kayit[1]
    try:
        metin = (await ag.indir(url, MAKS_BOYUT, zaman_asimi=20)).veri.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001 - adres (sır) hata metnine ve loga girmesin
        logger.warning("takvim indirilemedi: %s", type(e).__name__)
        if kayit:
            return kayit[1]  # eski kopya yine de işe yarar
        raise TakvimHatasi("Takvime ulaşamadım (adres yanlış ya da geçici bir sorun olabilir).") from None
    if "BEGIN:VCALENDAR" not in metin:
        raise TakvimHatasi("Adres bir takvim dosyası döndürmedi; gizli iCal adresini kontrol edin.")
    _onbellek[url] = (simdi, metin)
    return metin


async def yenile() -> None:
    """Brifing öncesi önbelleği tazeler; hata vermez (brifing takvimsiz de çıkar)."""
    for url in adresler():
        try:
            if url in _onbellek:
                _onbellek[url] = (-1e9, _onbellek[url][1])  # süresi dolmuş say: yeniden indir, olmazsa eskisi kalır
            await _getir(url)
        except TakvimHatasi:
            pass


async def etkinlikler(bas: datetime, gun: int) -> list[Etkinlik]:
    son = bas + timedelta(days=gun)
    hepsi: list[Etkinlik] = []
    for url in adresler():
        hepsi += ayristir(await _getir(url), bas, son)
    return sorted(hepsi, key=lambda e: (e.baslangic, e.baslik))


def _gun_basligi(d: date) -> str:
    return f"{GUNLER[d.weekday()]} ({d.day} {AYLAR[d.month - 1]})"


def _etkinlik_satiri(e: Etkinlik) -> str:
    yer = f" ({e.yer})" if e.yer else ""
    if e.tum_gun:
        return f"Tüm gün: {e.baslik}{yer}"
    bitis = f"-{e.bitis:%H:%M}" if e.bitis > e.baslangic and e.bitis.date() == e.baslangic.date() else ""
    return f"{e.baslangic:%H:%M}{bitis} {e.baslik}{yer}"


def _son_gun(e: Etkinlik) -> date:
    """Etkinliğin takvimde göründüğü son gün (bitiş dışlayıcıdır: gece yarısı biten etkinlik ertesi güne taşmaz)."""
    return (e.bitis - timedelta(seconds=1)).date() if e.bitis > e.baslangic else e.baslangic.date()


def metne_cevir(liste: list[Etkinlik], bas: datetime, gun: int) -> str:
    if not liste:
        return "Bu aralıkta takvimde etkinlik yok."
    satirlar: list[str] = []
    for i in range(gun):
        d = (bas + timedelta(days=i)).date()
        o_gun = [e for e in liste if e.baslangic.date() <= d <= _son_gun(e)]
        if o_gun:
            satirlar.append(_gun_basligi(d) + ":")
            satirlar += [f"- {_etkinlik_satiri(e)}" for e in o_gun]
    return "\n".join(satirlar)


def _baslangic(deger: Any) -> datetime:
    simdi = datetime.now(TR)
    d = str(deger or "bugun").strip().lower().replace("ü", "u").replace("ı", "i")
    if d in ("", "bugun", "today"):
        gun = simdi.date()
    elif d in ("yarin", "tomorrow"):
        gun = simdi.date() + timedelta(days=1)
    else:
        try:
            gun = date.fromisoformat(d)
        except ValueError:
            raise TakvimHatasi("baslangic 'bugun', 'yarin' ya da YYYY-AA-GG olmalı.") from None
    return datetime.combine(gun, datetime.min.time(), tzinfo=TR)


async def calistir(argumanlar: dict[str, Any]) -> tuple[bool, str]:
    """`takvim_bak` aracı: (başarılı_mı, metin)."""
    if not ayarli():
        return False, "Takvim bağlı değil (TAKVIM_ICS_URL tanımlı değil)."
    try:
        bas = _baslangic(argumanlar.get("baslangic"))
        gun = int(argumanlar.get("gun") or 1)
        if not 1 <= gun <= MAKS_GUN:
            raise TakvimHatasi(f"gun 1 ile {MAKS_GUN} arasında olmalı.")
        return True, metne_cevir(await etkinlikler(bas, gun), bas, gun)
    except (TakvimHatasi, ValueError) as e:
        return False, f"HATA: {e}"


def plan_kaynagi(gun: date) -> tuple[str, list[str]]:
    """Brifing için senkron kaynak: `yenile()` ile doldurulan önbellekten okur (ağa çıkmaz)."""
    bas = datetime.combine(gun, datetime.min.time(), tzinfo=TR)
    hepsi: list[Etkinlik] = []
    for url in adresler():
        kayit = _onbellek.get(url)
        if kayit:
            hepsi += ayristir(kayit[1], bas, bas + timedelta(days=1))
    if not _onbellek:
        raise RuntimeError("takvim önbelleği boş")  # brifing bölümü sessizce atlanır
    hepsi.sort(key=lambda e: (e.baslangic, e.baslik))
    if not hepsi:
        return "", ["Takvimde bugün bir şey yok"]
    return f"{len(hepsi)} etkinlik", [_etkinlik_satiri(e) for e in hepsi]


ARAC = tools.Tool(
    ad="takvim_bak",
    hedef="takvim",
    risk="düşük",
    aciklama=(
        "[Takvim] Kullanıcının takvimindeki etkinlikleri okur (SALT OKUMA: ekleyemez, silemez). SADECE kullanıcı programını, "
        "toplantılarını, randevularını ya da bir günün/haftanın takvimini sorarsa çağır (nasıl söylediği fark etmez: 'bugün ne var', "
        "'yarın toplantım var mı', 'bu hafta programım'). Başka konuda ÇAĞIRMA. baslangic: 'bugun', 'yarin' ya da YYYY-AA-GG; "
        "gun: kaç gün (1-31, varsayılan 1; 'bu hafta' için 7)."
    ),
    parametreler={
        "type": "object",
        "properties": {
            "baslangic": {"type": "string", "description": "'bugun' (varsayılan), 'yarin' ya da YYYY-AA-GG"},
            "gun": {"type": "integer", "description": "Kaç günlük aralık (1-31, varsayılan 1)"},
        },
    },
)


def kaydet() -> bool:
    """TAKVIM_ICS_URL tanımlıysa `takvim_bak` aracını modele açar."""
    if ayarli():
        tools.TOOLLAR[ARAC.ad] = ARAC
        return True
    tools.TOOLLAR.pop(ARAC.ad, None)
    return False
