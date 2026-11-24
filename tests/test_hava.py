"""Hızlı hava aracı (tek istek, sahte Open-Meteo) + hız ölçümü (/hiz) + ajan turunda hafıza bloğunun tekrar çekilmemesi."""

import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import httpx

import hava
from zamanlayici import TR

CEVAP = {
    "current": {"temperature_2m": 10.6, "apparent_temperature": 8.2, "weather_code": 3, "wind_speed_10m": 14.0},
    "hourly": {"time": [f"2026-11-15T{h:02d}:00" for h in range(24)],
               "temperature_2m": [10 + h % 5 for h in range(24)], "precipitation_probability": [20] * 24,
               "weather_code": [61] * 24},
    "daily": {"time": ["2026-11-15", "2026-11-16", "2026-11-17"], "temperature_2m_min": [11, 9, 8],
              "temperature_2m_max": [16, 16, 14], "precipitation_probability_max": [70, 10, 40],
              "weather_code": [61, 3, 80], "wind_speed_10m_max": [20, 15, 30]},
}


def istemci(durum=200, govde=CEVAP, istekler=None):
    def isle(req):
        if istekler is not None:
            istekler.append(req)
        return httpx.Response(durum, json=govde)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(isle))


SIMDI = datetime(2026, 11, 15, 14, 10, tzinfo=TR)


class Hava(unittest.IsolatedAsyncioTestCase):
    async def test_tek_istekte_ozet(self):
        istekler = []
        ok, m = await hava.sorgula({}, istemci=istemci(istekler=istekler), simdi=lambda: SIMDI)
        self.assertTrue(ok)
        self.assertEqual(len(istekler), 1)  # tek istek: hızlı
        self.assertIn("İstanbul", m)
        self.assertIn("Şu an: kapalı, 11°C (hissedilen 8°C)", m)
        self.assertIn("Bugün (15.11): hafif yağmurlu, 10-14°C, yağış ihtimali en çok %20", m)
        self.assertIn("Pazartesi (16.11)", m)
        self.assertIn("15:00", m)  # önümüzdeki saatler (geçmiş saat yok)
        self.assertNotIn("12:00", m)

    async def test_baska_yer(self):
        async def konum_bul(ad):
            return {"ad": "Kadıköy, İstanbul", "lat": 40.99, "lon": 29.03}

        ok, m = await hava.sorgula({"yer": "Kadıköy"}, konum_bul=konum_bul, istemci=istemci(), simdi=lambda: SIMDI)
        self.assertTrue(ok)
        self.assertIn("Kadıköy", m)

    async def test_gecmis_saatler_gunu_kirletmez(self):
        """Sabah yağan yağmur öğleden sonra "hâlâ yağmurlu" görünmesin (21 Kasım 2026 şikâyeti).

        Günün aralığı (9-16°C) günün tamamından gelir; hava ifadesi ve yağış ihtimali sadece KALAN saatlerden.
        """
        cevap = {
            "current": {"temperature_2m": 16.0, "apparent_temperature": 14.0, "weather_code": 1,
                        "wind_speed_10m": 10.0},
            "hourly": {"time": [f"2026-11-15T{h:02d}:00" for h in range(24)],
                       "temperature_2m": [9.0] * 8 + [16.0] * 16,
                       "precipitation_probability": [90] * 8 + [10] * 16,
                       "weather_code": [65] * 8 + [1] * 16,
                       "wind_speed_10m": [10.0] * 24},
            "daily": {"time": ["2026-11-15"], "temperature_2m_min": [9], "temperature_2m_max": [16],
                      "precipitation_probability_max": [90], "weather_code": [65], "wind_speed_10m_max": [10]},
        }
        ok, m = await hava.sorgula({}, istemci=istemci(govde=cevap), simdi=lambda: SIMDI)  # 14:10
        self.assertTrue(ok)
        self.assertIn("Bugün (15.11): çoğunlukla açık, 9-16°C, yağış ihtimali en çok %10", m)
        self.assertNotIn("kuvvetli yağmurlu", m)  # sabahki sağanak günün havası sayılmaz
        self.assertNotIn("%90", m)

    async def test_servis_yoksa_hata_metni(self):
        # İki kaynak da çökerse metin "internette ara" DEMEZ: eski/tarihli sayfa okunmasın (19 Kasım 2026 olayı)
        istekler = []
        ok, m = await hava.sorgula({}, istemci=istemci(durum=503, istekler=istekler), simdi=lambda: SIMDI)
        self.assertFalse(ok)
        self.assertEqual(len(istekler), 2)  # Open-Meteo + yedek MET Norway denendi
        self.assertIn("ALMA", m)
        self.assertNotIn("internette ara", m)
        self.assertIn("503", m)  # sebep görünür

    async def test_open_meteo_429_yedek_devreye(self):
        # Open-Meteo kota/429 -> MET Norway yedeği devreye girer, veri yine gelir
        METNO = {"properties": {"timeseries": [
            {"time": f"2026-11-15T{h:02d}:00:00Z",
             "data": {"instant": {"details": {"air_temperature": 9 + h % 6, "wind_speed": 3.0}},
                      "next_1_hours": {"summary": {"symbol_code": "clearsky_day"},
                                       "details": {"precipitation_amount": 0.1}}}}
            for h in range(24)]}}

        def isle(req):
            if req.url.host == "api.open-meteo.com":
                return httpx.Response(429, json={"error": True})
            return httpx.Response(200, json=METNO)

        istemci_karisik = lambda: httpx.AsyncClient(transport=httpx.MockTransport(isle))  # noqa: E731
        ok, m = await hava.sorgula({}, istemci=istemci_karisik, simdi=lambda: SIMDI)
        self.assertTrue(ok)
        self.assertIn("MET Norway", m)      # kaynak dürüstçe yazılı
        self.assertIn("açık", m)            # clearsky_day -> açık (sembol eşleşmesi)
        self.assertIn("Bugün (15.11)", m)


class HizVeHafiza(unittest.IsolatedAsyncioTestCase):
    async def test_hafiza_blogu_bir_kez_ve_hiz_kaydi(self):
        import main

        cagri = SimpleNamespace(id="c1", function=SimpleNamespace(name="hava_durumu", arguments="{}"))
        yanitlar = [SimpleNamespace(content="", tool_calls=[cagri]),
                    SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="c2", function=SimpleNamespace(
                        name="hava_durumu", arguments=json.dumps({"yer": "Kadıköy"})))]),
                    SimpleNamespace(content="Hava kapalı kanka.", tool_calls=None)]
        blok = mock.AsyncMock(return_value="[Hafıza]")
        with mock.patch.object(main, "_model", mock.AsyncMock(side_effect=yanitlar)), \
                mock.patch.object(main, "_hafiza_blogu", blok), \
                mock.patch.object(main, "tool_cagrisini_isle", mock.AsyncMock(return_value="hava: kapalı")), \
                mock.patch.object(main, "_gonder", mock.AsyncMock()), \
                mock.patch.object(main.hafiza, "mesaj_kaydet", mock.AsyncMock()):
            await main.ajan_turu(mock.Mock(), 1, [{"role": "user", "content": "hava nasıl"}])
        self.assertEqual(blok.await_count, 1)  # 3 adım, hafıza DB'den bir kez
        son = main.hiz_kayitlari[-1]
        self.assertEqual(len(son["model"]), 3)
        self.assertEqual([a for a, _ in son["araclar"]], ["hava_durumu", "hava_durumu"])
        self.assertIn("hava durumuna bakıyorum", main.hiz_metni())


if __name__ == "__main__":
    unittest.main()
