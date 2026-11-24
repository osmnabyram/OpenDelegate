"""Salt okunur takvim (iCal): tekrar kuralları, saat dilimi, tüm gün, iptal/değişen örnek, getirme ve önbellek, araç, brifing."""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ag
import config
import takvim
import tools
from tests.test_brifing import kur
from zamanlayici import TR

GIZLI_URL = "https://calendar.google.com/calendar/ical/ornek%40gmail.com/private-GIZLIANAHTAR123/basic.ics"


def ics(*olaylar):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(
        f"BEGIN:VEVENT\r\n{o.strip()}\r\nEND:VEVENT\r\n" for o in olaylar) + "END:VCALENDAR\r\n"


def pencere(gun_baslangic, gun=1):
    bas = datetime.fromisoformat(gun_baslangic).replace(tzinfo=TR)
    return bas, bas + timedelta(days=gun)


def liste(metin, gun_baslangic, gun=1):
    bas, son = pencere(gun_baslangic, gun)
    return takvim.ayristir(metin, bas, son)


def ozet(etkinlikler):
    return [(f"{e.baslangic:%m-%d %H:%M}", e.baslik) for e in etkinlikler]


class Ayristirma(unittest.TestCase):
    def test_utc_saat_turkiyeye_cevrilir_ve_kacislar_acilir(self):
        m = ics("UID:1\nDTSTART:20261124T060000Z\nDTEND:20261124T070000Z\nSUMMARY:Toplantı\\, Ali\\nodası\nLOCATION:Ofis")
        (e,) = liste(m, "2026-11-24")
        self.assertEqual(f"{e.baslangic:%H:%M}-{e.bitis:%H:%M}", "09:00-10:00")
        self.assertEqual((e.baslik, e.yer), ("Toplantı, Ali\nodası", "Ofis"))

    def test_tzid_istanbul_ve_katlanmis_satir(self):
        m = ics("UID:1\nDTSTART;TZID=Europe/Istanbul:20261124T140000\nDTEND;TZID=Europe/Istanbul:20261124T150000\n"
                "SUMMARY:Uzun baş\r\n lık devam")
        (e,) = liste(m, "2026-11-24")
        self.assertEqual((f"{e.baslangic:%H:%M}", e.baslik), ("14:00", "Uzun başlık devam"))

    def test_tum_gun_tek_ve_cok_gunluk(self):
        m = ics("UID:1\nDTSTART;VALUE=DATE:20261124\nDTEND;VALUE=DATE:20261125\nSUMMARY:Tek",
                "UID:2\nDTSTART;VALUE=DATE:20261124\nDTEND;VALUE=DATE:20261127\nSUMMARY:Uç gün")
        self.assertTrue(all(e.tum_gun for e in liste(m, "2026-11-24")))
        self.assertEqual([e.baslik for e in liste(m, "2026-11-24")], ["Tek", "Uç gün"])
        self.assertEqual([e.baslik for e in liste(m, "2026-11-26")], ["Uç gün"])
        self.assertEqual(liste(m, "2026-11-27"), [])  # bitiş dışlayıcı

    def test_pencere_disi_ve_iptal_gelmez(self):
        m = ics("UID:1\nDTSTART:20261125T060000Z\nSUMMARY:Yarın",
                "UID:2\nDTSTART:20261124T060000Z\nSTATUS:CANCELLED\nSUMMARY:İptal")
        self.assertEqual(liste(m, "2026-11-24"), [])

    def test_bozuk_tarih_atlanir_digerleri_gelir(self):
        m = ics("UID:1\nDTSTART:bozuk\nSUMMARY:Bozuk", "UID:2\nDTSTART:20261124T060000Z\nSUMMARY:Sağlam")
        self.assertEqual([e.baslik for e in liste(m, "2026-11-24")], ["Sağlam"])


class Tekrar(unittest.TestCase):
    def test_haftalik_byday(self):
        m = ics("UID:1\nDTSTART;TZID=Europe/Istanbul:20261102T100000\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE\nSUMMARY:Ders")
        self.assertEqual(ozet(liste(m, "2026-11-23", 8)),
                         [("11-23 10:00", "Ders"), ("11-25 10:00", "Ders"), ("11-30 10:00", "Ders")])

    def test_haftalik_baslangictan_once_uretilmez(self):
        m = ics("UID:1\nDTSTART;TZID=Europe/Istanbul:20261125T100000\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE\nSUMMARY:Ders")
        self.assertEqual(ozet(liste(m, "2026-11-23", 3)), [("11-25 10:00", "Ders")])  # 23'ü başlangıçtan önce

    def test_gunluk_count_ve_aralik(self):
        m = ics("UID:1\nDTSTART:20261122T060000Z\nRRULE:FREQ=DAILY;COUNT=3\nSUMMARY:İlaç")
        self.assertEqual([d for d, _ in ozet(liste(m, "2026-11-20", 10))], ["11-22 09:00", "11-23 09:00", "11-24 09:00"])
        m2 = ics("UID:1\nDTSTART:20261122T060000Z\nRRULE:FREQ=DAILY;INTERVAL=2\nSUMMARY:İki günde bir")
        self.assertEqual([d for d, _ in ozet(liste(m2, "2026-11-22", 6))], ["11-22 09:00", "11-24 09:00", "11-26 09:00"])

    def test_until_durdurur(self):
        m = ics("UID:1\nDTSTART:20261122T060000Z\nRRULE:FREQ=DAILY;UNTIL=20261123T235959Z\nSUMMARY:X")
        self.assertEqual(len(liste(m, "2026-11-20", 10)), 2)

    def test_exdate_atlanir(self):
        m = ics("UID:1\nDTSTART:20261122T060000Z\nRRULE:FREQ=DAILY;COUNT=3\nEXDATE:20261123T060000Z\nSUMMARY:X")
        self.assertEqual([d for d, _ in ozet(liste(m, "2026-11-20", 10))], ["11-22 09:00", "11-24 09:00"])

    def test_aylik_ikinci_pazartesi(self):
        m = ics("UID:1\nDTSTART;TZID=Europe/Istanbul:20261012T180000\nRRULE:FREQ=MONTHLY;BYDAY=2MO\nSUMMARY:Aylık")
        self.assertEqual(ozet(liste(m, "2026-11-01", 30)), [("11-09 18:00", "Aylık")])

    def test_aylik_ayin_gunu_ve_olmayan_gun_atlanir(self):
        m = ics("UID:1\nDTSTART:20260131T060000Z\nRRULE:FREQ=MONTHLY;BYMONTHDAY=31\nSUMMARY:Ay sonu")
        self.assertEqual(liste(m, "2026-11-01", 30), [])  # kasımda 31 yok
        self.assertEqual(len(liste(m, "2026-12-01", 31)), 1)

    def test_yillik_dogum_gunu(self):
        m = ics("UID:1\nDTSTART;VALUE=DATE:20201125\nDTEND;VALUE=DATE:20201126\nRRULE:FREQ=YEARLY\nSUMMARY:Doğum günü")
        (e,) = liste(m, "2026-11-25")
        self.assertTrue(e.tum_gun)
        self.assertEqual(liste(m, "2026-11-26"), [])

    def test_degisen_ornek_eskisinin_yerine_gecer(self):
        m = ics("UID:A\nDTSTART;TZID=Europe/Istanbul:20261102T100000\nRRULE:FREQ=WEEKLY;BYDAY=MO\nSUMMARY:Ders",
                "UID:A\nRECURRENCE-ID;TZID=Europe/Istanbul:20261123T100000\nDTSTART;TZID=Europe/Istanbul:20261124T150000\n"
                "SUMMARY:Ders (taşındı)")
        self.assertEqual(ozet(liste(m, "2026-11-23", 2)), [("11-24 15:00", "Ders (taşındı)")])

    def test_iptal_edilen_ornek_gelmez(self):
        m = ics("UID:A\nDTSTART;TZID=Europe/Istanbul:20261102T100000\nRRULE:FREQ=WEEKLY;BYDAY=MO\nSUMMARY:Ders",
                "UID:A\nRECURRENCE-ID;TZID=Europe/Istanbul:20261123T100000\nDTSTART;TZID=Europe/Istanbul:20261123T100000\n"
                "STATUS:CANCELLED\nSUMMARY:Ders")
        self.assertEqual(liste(m, "2026-11-23", 1), [])
        self.assertEqual(len(liste(m, "2026-11-30", 1)), 1)

    def test_desteklenmeyen_kural_yalniz_ilk_etkinligi_gosterir(self):
        m = ics("UID:1\nDTSTART:20261122T060000Z\nRRULE:FREQ=MONTHLY;BYDAY=MO,TU;BYSETPOS=1\nSUMMARY:X")
        self.assertEqual(len(liste(m, "2026-11-22", 60)), 1)

    def test_cok_eski_gunluk_kural_donguyu_sinirlar(self):
        m = ics("UID:1\nDTSTART:19900101T060000Z\nRRULE:FREQ=DAILY\nSUMMARY:X")
        self.assertIsInstance(liste(m, "2026-11-24"), list)  # takılmaz, çökmez


class Getirme(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        takvim._onbellek.clear()
        self.yama = mock.patch.object(config, "TAKVIM_ICS_URL", GIZLI_URL, create=True)
        self.yama.start()

    def tearDown(self):
        self.yama.stop()
        takvim._onbellek.clear()
        takvim.kaydet()

    def indir(self, metin):
        return mock.AsyncMock(return_value=ag.Indirilen(veri=metin.encode(), ad="basic.ics", tur="text/calendar", url=GIZLI_URL))

    async def test_arac_etkinlikleri_gun_gun_listeler(self):
        m = ics("UID:1\nDTSTART:20261124T060000Z\nDTEND:20261124T070000Z\nSUMMARY:Toplantı\nLOCATION:Ofis",
                "UID:2\nDTSTART;VALUE=DATE:20261125\nSUMMARY:Tatil")
        with mock.patch.object(ag, "indir", self.indir(m)):
            ok, metin = await takvim.calistir({"baslangic": "2026-11-24", "gun": 2})
        self.assertTrue(ok)
        self.assertIn("Salı (24 Kasım):", metin)
        self.assertIn("- 09:00-10:00 Toplantı (Ofis)", metin)
        self.assertIn("Çarşamba (25 Kasım):", metin)
        self.assertIn("- Tüm gün: Tatil", metin)

    async def test_bos_aralik(self):
        with mock.patch.object(ag, "indir", self.indir(ics())):
            self.assertEqual(await takvim.calistir({"baslangic": "2026-11-24"}),
                             (True, "Bu aralıkta takvimde etkinlik yok."))

    async def test_bagli_degilse_acik_mesaj(self):
        with mock.patch.object(config, "TAKVIM_ICS_URL", "", create=True):
            ok, metin = await takvim.calistir({})
        self.assertFalse(ok)
        self.assertIn("bağlı değil", metin)

    async def test_gecersiz_argumanlar(self):
        with mock.patch.object(ag, "indir", self.indir(ics())):
            self.assertFalse((await takvim.calistir({"gun": 99}))[0])
            self.assertFalse((await takvim.calistir({"baslangic": "dün gece"}))[0])
            self.assertFalse((await takvim.calistir({"gun": "abc"}))[0])

    async def test_yalniz_https_kabul_edilir_ve_webcal_cevrilir(self):
        with mock.patch.object(config, "TAKVIM_ICS_URL", "webcal://a.test/x.ics,http://b.test/y.ics", create=True):
            self.assertEqual(takvim.adresler(), ["https://a.test/x.ics", "http://b.test/y.ics"])
            with self.assertRaises(takvim.TakvimHatasi):
                await takvim._getir("http://b.test/y.ics")

    async def test_onbellek_5_dakika_ag_bir_kez(self):
        indir = self.indir(ics())
        with mock.patch.object(ag, "indir", indir):
            await takvim.calistir({})
            await takvim.calistir({})
        self.assertEqual(indir.await_count, 1)

    async def test_hata_mesaji_gizli_adresi_icermez_ve_eski_kopya_kullanilir(self):
        m = ics("UID:1\nDTSTART:20261124T060000Z\nSUMMARY:Eski")
        with mock.patch.object(ag, "indir", self.indir(m)):
            await takvim.calistir({"baslangic": "2026-11-24"})
        takvim._onbellek[GIZLI_URL] = (-1e9, takvim._onbellek[GIZLI_URL][1])  # süresi dolmuş
        with mock.patch.object(ag, "indir", mock.AsyncMock(side_effect=ag.AgHatasi(f"HTTP 500 {GIZLI_URL}"))):
            ok, metin = await takvim.calistir({"baslangic": "2026-11-24"})
        self.assertTrue(ok)
        self.assertIn("Eski", metin)  # indirilemedi ama eski kopya yetti
        takvim._onbellek.clear()
        with mock.patch.object(ag, "indir", mock.AsyncMock(side_effect=ag.AgHatasi(f"HTTP 500 {GIZLI_URL}"))):
            ok, metin = await takvim.calistir({})
        self.assertFalse(ok)
        self.assertNotIn("GIZLIANAHTAR", metin)

    async def test_takvim_olmayan_icerik_reddedilir(self):
        with mock.patch.object(ag, "indir", self.indir("<html>giris yap</html>")):
            ok, metin = await takvim.calistir({})
        self.assertFalse(ok)
        self.assertIn("takvim dosyası", metin)

    async def test_birden_cok_adres_birlesir(self):
        a = ics("UID:1\nDTSTART:20261124T060000Z\nSUMMARY:A")
        b = ics("UID:2\nDTSTART:20261124T070000Z\nSUMMARY:B")

        async def indir(url, limit, zaman_asimi=60):
            return ag.Indirilen(veri=(a if "bir" in url else b).encode(), ad="x", tur="", url=url)

        with mock.patch.object(config, "TAKVIM_ICS_URL", "https://x.test/bir.ics, https://x.test/iki.ics", create=True), \
                mock.patch.object(ag, "indir", indir):
            ok, metin = await takvim.calistir({"baslangic": "2026-11-24"})
        self.assertLess(metin.index("A"), metin.index("B"))


class AracVeBrifing(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        takvim._onbellek.clear()

    def tearDown(self):
        takvim._onbellek.clear()
        with mock.patch.object(config, "TAKVIM_ICS_URL", "", create=True):
            takvim.kaydet()

    def test_arac_yalniz_takvim_bagliysa_acilir(self):
        with mock.patch.object(config, "TAKVIM_ICS_URL", "", create=True):
            self.assertFalse(takvim.kaydet())
            self.assertNotIn("takvim_bak", tools.TOOLLAR)
        with mock.patch.object(config, "TAKVIM_ICS_URL", GIZLI_URL, create=True):
            self.assertTrue(takvim.kaydet())
            self.assertEqual((tools.TOOLLAR["takvim_bak"].hedef, tools.risk_degerlendir("takvim_bak", {"baslangic": "bugun"})),
                             ("takvim", "düşük"))
            self.assertIn("takvim_bak", [s["function"]["name"] for s in tools.openai_semalari()])
            self.assertIn("ÇAĞIRMA", tools.TOOLLAR["takvim_bak"].aciklama)  # sahte çağrı tuzağına karşı

    def test_plan_kaynagi_onbellekten_okur(self):
        with mock.patch.object(config, "TAKVIM_ICS_URL", GIZLI_URL, create=True):
            with self.assertRaises(RuntimeError):  # önbellek boş: brifing bölümü atlanır
                takvim.plan_kaynagi(datetime(2026, 11, 24).date())
            takvim._onbellek[GIZLI_URL] = (0.0, ics("UID:1\nDTSTART:20261124T060000Z\nDTEND:20261124T070000Z\nSUMMARY:Toplantı"))
            self.assertEqual(takvim.plan_kaynagi(datetime(2026, 11, 24).date()), ("1 etkinlik", ["09:00-10:00 Toplantı"]))
            self.assertEqual(takvim.plan_kaynagi(datetime(2026, 11, 25).date()), ("", ["Takvimde bugün bir şey yok"]))

    async def test_brifing_once_hazirlar_sonra_plani_yazar(self):
        olaylar = []

        async def hazirla():
            olaylar.append("hazir")

        b, _, gonderilen, _ = kur(plan=lambda g: ("1 etkinlik", ["09:00 Toplantı"]), durum=lambda: "ok")
        b.plan_hazirla = hazirla
        await b.gonder_simdi()
        self.assertEqual(olaylar, ["hazir"])
        self.assertIn("09:00 Toplantı", gonderilen[0])

    async def test_hazirlik_patlarsa_brifing_yine_cikar(self):
        async def patlayan():
            raise RuntimeError("ag yok")

        b, _, gonderilen, _ = kur(plan=lambda g: ("", ["x"]), durum=lambda: "ok")
        b.plan_hazirla = patlayan
        await b.gonder_simdi()
        self.assertTrue(gonderilen)


if __name__ == "__main__":
    unittest.main()
