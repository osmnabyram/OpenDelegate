"""Hızlı hava durumu: tek istekte şu an + önümüzdeki saatler + 3 gün (Open-Meteo, key'siz).

Neden: "hava nasıl" sorusunda OpenDelegate internette arayıp sayfa okuyup birkaç model turu yapıyordu (15-20 sn).
Bu araç tek istekte, ~1 sn'de, sade Türkçe özet döner; model 1 tur daha düşünüp cevaplar. Telefonda da doğrudan
kullanılır. Konum verilmezse brifingin şehri (config.SEHIR_AD). Open-Meteo olmazsa YEDEK kaynak MET Norway denenir; ikisi de olmazsa hata metni döner ve model
internette ESKİ/tarihli sayfa okumaya YÖNLENDİRİLMEZ (19 Kasım 2026: Open-Meteo 429 verince model eski
tarihli sayfadan veri alıp yanlış hava söylemişti).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

import httpx

import ag
import config
from brifing import HAVA_URL, METNO_URL, _WMO, _metno_durum, _one_cikan
from zamanlayici import TR

GUN_ADI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
VARSAYILAN_SEHIR = {"ad": config.SEHIR_AD, "lat": config.SEHIR_LAT, "lon": config.SEHIR_LON}


def _d(x: Any) -> str:
    return f"{round(float(x))}" if x is not None else "?"


def ozetle(v: dict[str, Any], yer: str, simdi: datetime) -> str:
    """Open-Meteo cevabı -> kısa Türkçe metin (model okur, kullanıcıya kendi cümlesiyle söyler)."""
    s = v.get("current") or {}
    satirlar = [f"{yer} hava durumu (saat {simdi:%H:%M}):",
                f"Şu an: {_WMO.get(int(s.get('weather_code') or 0), '')}, {_d(s.get('temperature_2m'))}°C "
                f"(hissedilen {_d(s.get('apparent_temperature'))}°C), rüzgar {_d(s.get('wind_speed_10m'))} km/s."]
    h = v.get("hourly") or {}
    saatler = h.get("time") or []
    sonraki = []
    for i, t in enumerate(saatler):
        an = datetime.fromisoformat(t).replace(tzinfo=TR)
        if an <= simdi or len(sonraki) >= 8:
            continue
        if an.hour % 3 == 0:  # 3 saatte bir: kısa kalsın
            sonraki.append(f"{an:%H}:00 {_d(h['temperature_2m'][i])}°C {_WMO.get(int(h['weather_code'][i] or 0), '')}"
                           f", yağış ihtimali %{_d(h['precipitation_probability'][i])}")
    if sonraki:
        satirlar.append("Önümüzdeki saatler: " + "; ".join(sonraki[:6]) + ".")
    def hv(ad: str, i: int) -> Any:
        dizi = h.get(ad) or []
        return dizi[i] if i < len(dizi) else None

    g = v.get("daily") or {}
    # BUGÜN = sadece KALAN saatler. Günlük özet geçmiş sabahı da sayınca "bugün yağmurlu" yanılgısı çıkıyordu.
    kod, sic, yagis, ruzgar, tum_sic, kod_yagis = [], [], [], [], [], []
    for i, t in enumerate(saatler):
        an = datetime.fromisoformat(t).replace(tzinfo=TR)
        if an.date() != simdi.date():
            continue
        kodlar_i, sic_i, yagis_i, ruzgar_i = (hv("weather_code", i), hv("temperature_2m", i),
                                              hv("precipitation_probability", i), hv("wind_speed_10m", i))
        if sic_i is not None:
            tum_sic.append(float(sic_i))  # günün sıcaklık aralığı: geçmiş saatler de sayılır
        if an.hour < simdi.hour:
            continue  # hava ifadesi ve yağış: sadece KALAN saatler
        if kodlar_i is not None:
            kod.append(int(kodlar_i))
        if sic_i is not None:
            sic.append(float(sic_i))
        if yagis_i is not None:
            yagis.append(float(yagis_i))
        if kodlar_i is not None:
            kod_yagis.append((int(kodlar_i), float(yagis_i) if yagis_i is not None else None))
        if ruzgar_i is not None:
            ruzgar.append(float(ruzgar_i))
    if sic:
        satirlar.append(
            f"Bugün ({simdi.day}.{simdi.month}): {_WMO.get(_one_cikan(kod_yagis), '')}, "
            f"{_d(min(tum_sic or sic))}-{_d(max(tum_sic or sic))}°C"
            + (f", yağış ihtimali en çok %{_d(max(yagis))}" if yagis else "")
            + (f", rüzgar en çok {_d(max(ruzgar))} km/s" if ruzgar else "") + ".")
    for i, t in enumerate((g.get("time") or [])[:3]):
        gun = datetime.fromisoformat(t).date()
        if gun == simdi.date():  # bugün yukarıda kalan saatlerle verildi
            continue
        ad = GUN_ADI[gun.weekday()]
        satirlar.append(
            f"{ad} ({gun.day}.{gun.month}): {_WMO.get(int(g['weather_code'][i] or 0), '')}, "
            f"{_d(g['temperature_2m_min'][i])}-{_d(g['temperature_2m_max'][i])}°C, "
            f"yağış ihtimali %{_d(g['precipitation_probability_max'][i])}, rüzgar en çok {_d(g['wind_speed_10m_max'][i])} km/s.")
    return "\n".join(satirlar)


async def _metno_ozet(konum: dict[str, Any], istemci: Callable[[], httpx.AsyncClient],
                      simdi: datetime) -> str:
    """YEDEK kaynak: MET Norway locationforecast (key'siz; kimlik bildiren User-Agent ister).

    Open-Meteo çöktüğünde/429 verdiğinde kullanılır. Yağış OLASILIĞI yok (mm verir), hissedilen sıcaklık yok.
    """
    async with istemci() as c:
        r = await c.get(METNO_URL, params={"lat": round(konum["lat"], 4), "lon": round(konum["lon"], 4)},
                        headers={"User-Agent": ag.TARAYICI})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    seri = (r.json().get("properties") or {}).get("timeseries") or []
    kayitlar: list[dict[str, Any]] = []
    for z in seri:
        yerel = datetime.fromisoformat(z["time"].replace("Z", "+00:00")).astimezone(TR)
        a = (z.get("data") or {}).get("instant", {}).get("details") or {}
        yakin = z["data"].get("next_1_hours") or z["data"].get("next_6_hours") or {}
        ruzgar = a.get("wind_speed")
        kayitlar.append({"an": yerel, "sicaklik": a.get("air_temperature"),
                         "ruzgar": ruzgar * 3.6 if ruzgar is not None else None,
                         "sembol": (yakin.get("summary") or {}).get("symbol_code"),
                         "yagis_mm": (yakin.get("details") or {}).get("precipitation_amount")})
    if not kayitlar:
        raise RuntimeError("veri yok")
    # Geçmiş dilimi "şu an" diye sunmak yanıltıyordu (15:45'te sabahki yağmur "şu an yağmurlu" oluyordu).
    # Şu anı kapsayan dilim: en fazla 20 dk geriye izin ver, yoksa ilk ileri kaydı al.
    an = next((k for k in kayitlar if k["an"] >= simdi - timedelta(minutes=20)), kayitlar[0])
    satirlar = [f"{konum['ad']} hava durumu (saat {simdi:%H:%M}, kaynak MET Norway):",
                f"Şu an: {_metno_durum([an['sembol']] if an['sembol'] else []) or '?'}, "
                f"{_d(an['sicaklik'])}°C, rüzgar {_d(an['ruzgar'])} km/s."]
    sonraki = [k for k in kayitlar if k["an"] > simdi and k["an"].hour % 3 == 0][:6]
    if sonraki:
        satirlar.append("Önümüzdeki saatler: " + "; ".join(
            f"{k['an']:%H}:00 {_d(k['sicaklik'])}°C {_metno_durum([k['sembol']] if k['sembol'] else []) or '?'}"
            f", yağış {k['yagis_mm'] if k['yagis_mm'] is not None else 0} mm" for k in sonraki) + ".")
    for i in range(3):
        gun = simdi.date() + timedelta(days=i)
        gunluk = [k for k in kayitlar if k["an"].date() == gun and (i > 0 or k["an"] >= simdi)]
        if not gunluk:
            continue
        sicak = [k["sicaklik"] for k in gunluk if k["sicaklik"] is not None]
        ruzgarlar = [k["ruzgar"] for k in gunluk if k["ruzgar"] is not None]
        yagis = round(sum(k["yagis_mm"] or 0 for k in gunluk), 1)
        ad = "Bugün" if i == 0 else GUN_ADI[gun.weekday()]
        satirlar.append(
            f"{ad} ({gun.day}.{gun.month}): {_metno_durum([k['sembol'] for k in gunluk if k['sembol']])}, "
            f"{_d(min(sicak) if sicak else None)}-{_d(max(sicak) if sicak else None)}°C, toplam yağış {yagis} mm, "
            f"rüzgar en çok {_d(max(ruzgarlar) if ruzgarlar else None)} km/s.")
    return "\n".join(satirlar)


async def sorgula(arg: dict[str, Any], *, konum_bul: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
                  sehir: dict[str, Any] | None = None,
                  istemci: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=10),
                  simdi: Callable[[], datetime] = lambda: datetime.now(TR)) -> tuple[bool, str]:
    """hava_durumu tool'u. arg: {'yer': 'Kadıköy' (boşsa varsayılan şehir)}."""
    yer_adi = str(arg.get("yer") or "").strip()
    konum = sehir or VARSAYILAN_SEHIR
    if yer_adi and konum_bul is not None:
        try:
            konum = await konum_bul(yer_adi)
        except Exception as e:  # noqa: BLE001
            return False, f"'{yer_adi}' konumunu bulamadım ({e}). Başka bir yazımla dene; internette eski tarihli sayfalardan hava bilgisi alma."
    params = {"latitude": konum["lat"], "longitude": konum["lon"], "timezone": "Europe/Istanbul", "forecast_days": 3,
              "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
              "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
              "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,"
                       "wind_speed_10m_max"}
    sebep = ""
    try:
        async with istemci() as c:
            r = await c.get(HAVA_URL, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return True, ozetle(r.json(), konum["ad"], simdi())
    except Exception as e:  # noqa: BLE001
        sebep = f"{type(e).__name__}: {e}"
    try:  # YEDEK kaynak (Open-Meteo 429/kesinti -> MET Norway)
        return True, await _metno_ozet(konum, istemci, simdi())
    except Exception as e2:  # noqa: BLE001
        return False, (f"Hava servisine ulaşamadım (Open-Meteo: {sebep}; MET Norway: {type(e2).__name__}: {e2}). "
                       "Eski/tarihli sayfalardan hava bilgisi ALMA; kullanıcıya hava verisini şu an doğrulayamadığını söyle.")
