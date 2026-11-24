"""Öz-değerlendirme: sahte 7 günle rapor, 'sus' bayrağı, inert öneriler, uzunluk sınırı, birleşik Pazar mesajı."""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
import oz_degerlendirme as oz
from zamanlayici import TR

SIMDI = datetime(2026, 11, 15, 21, 30, tzinfo=TR)
EYLEMLER = (
    [{"zaman": "2026-11-10T14:00:00", "tool": "terminal_calistir", "risk": "orta", "durum": "hata",
      "sonuc": "HATA: python bulunamadı"}] * 3
    + [{"zaman": "2026-11-11T10:00:00", "tool": "dosya_yaz", "risk": "orta", "durum": "basarili", "sonuc": "ok"}] * 5
    + [{"zaman": "2026-11-12T09:00:00", "tool": "terminal_calistir", "risk": "yasak", "durum": "yasak",
        "sonuc": "REDDEDİLDİ"}]
)
MESAJLAR = [
    {"zaman": "2026-11-10T13:59:00", "rol": "user", "icerik": "ödevi çalıştır"},
    {"zaman": "2026-11-10T14:05:00", "rol": "assistant", "icerik": "Çalıştırdım, oldu."},
    {"zaman": "2026-11-10T14:06:00", "rol": "user", "icerik": "hayır çalışmadı, yanlış anladın"},
]


async def llm_uzun(sistem, metin):
    return ('{"iyi": ["Dosyaları hızlı yazdım"], "sorun": ["Salı 14:00 python yokken 3 kez aynı komutu denedim", '
            '"Salı ödevi çalışmadığı halde oldu dedim", "' + "x" * 400 + '", "d", "e"], '
            '"oneri": ["Komut bulunamazsa önce kurulu mu bak", "Sonucu doğrulamadan oldu deme", "c", "d"]}')


class Olcum(unittest.TestCase):
    def test_metrikler(self):
        o = oz.olcumler(EYLEMLER, MESAJLAR)
        self.assertEqual((o["eylem"], o["hata"], o["basarili"], o["yasak_yetkisiz"]), (9, 4, 5, 1))
        self.assertTrue(o["tekrarlanan_hata"][0].startswith("terminal_calistir x3"))
        self.assertEqual(o["kullanici_mesaj"], 2)


class Rapor(unittest.IsolatedAsyncioTestCase):
    async def test_rapor_uretimi_ve_uzunluk_siniri(self):
        depo = {}
        metin = await oz.haftalik_bolum(EYLEMLER, MESAJLAR, llm_uzun, depo, SIMDI)
        self.assertTrue(metin.startswith("Haftalık öz-değerlendirme: 9 iş, 4 hata, 2 mesajın"))
        maddeler = [s for s in metin.splitlines() if s[:2] in ("+ ", "- ") or s.startswith("Öneri #")]
        self.assertLessEqual(len(maddeler), oz.MAKS_MADDE)
        self.assertTrue(all(len(s) <= oz.MAKS_MADDE_UZUNLUK + 12 for s in maddeler))
        self.assertIn("Öneri #1: Komut bulunamazsa önce kurulu mu bak", metin)
        self.assertIn("onaylamadan uygulamam", metin)

    async def test_oneriler_inert_bekliyor(self):
        depo = {}
        await oz.haftalik_bolum(EYLEMLER, MESAJLAR, llm_uzun, depo, SIMDI)
        self.assertTrue(depo["oneriler"])
        self.assertTrue(all(x["durum"] == "bekliyor" for x in depo["oneriler"]))

    async def test_llm_bozuksa_olcumden_rapor(self):
        async def bozuk(s, m):
            raise OSError("ağ yok")
        metin = await oz.haftalik_bolum(EYLEMLER, MESAJLAR, bozuk, {}, SIMDI)
        self.assertIn("Aynı hatayı tekrarladım: terminal_calistir x3", metin)

    async def test_veri_yoksa_bolum_yok(self):
        self.assertIsNone(await oz.haftalik_bolum([], [], llm_uzun, {}, SIMDI))

    def test_sus_sadece_o_hafta(self):
        sus = {"hafta": oz.hafta_kodu(SIMDI)}
        self.assertTrue(oz.sus_mu(sus, SIMDI))
        self.assertFalse(oz.sus_mu(sus, datetime(2026, 11, 22, 21, 30, tzinfo=TR)))
        self.assertFalse(oz.sus_mu(None, SIMDI))


class Entegrasyon(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.depo = {}

        async def oku(k):
            return self.depo.get(k)

        async def yaz(k, v):
            self.depo[k] = v
        self.yamalar = [mock.patch.object(main.zamanlayici, "ayar_oku", oku),
                        mock.patch.object(main.zamanlayici, "ayar_yaz", yaz),
                        mock.patch.object(main, "_llm_sor", llm_uzun),
                        mock.patch.object(main.hafiza, "eylemler_beri", mock.AsyncMock(return_value=EYLEMLER)),
                        mock.patch.object(main.hafiza, "mesajlar_beri", mock.AsyncMock(return_value=MESAJLAR)),
                        mock.patch.object(main.hafiza, "bilgiler", mock.AsyncMock(return_value=[])),
                        mock.patch.object(main.hafiza, "bilgi_yaz", mock.AsyncMock(return_value=True))]
        for y in self.yamalar:
            y.start()

    def tearDown(self):
        for y in self.yamalar:
            y.stop()

    async def test_tek_mesaj_ve_sus(self):
        bot = mock.Mock(send_message=mock.AsyncMock())
        await main._haftalik_rapor(bot)
        self.assertEqual(bot.send_message.await_count, 1)
        ok, _ = await main._oz_oneri_yonet({"eylem": "sus"})
        self.assertTrue(ok)
        await main._haftalik_rapor(bot)
        self.assertEqual(bot.send_message.await_count, 1)  # bu hafta atlandı

    async def test_siradan_ders_otomatik_digerleri_onay_bekler(self):
        await main._haftalik_rapor(mock.Mock(send_message=mock.AsyncMock()))
        cagrilar = [c.args for c in main.hafiza.bilgi_yaz.await_args_list]
        self.assertEqual(cagrilar, [("tercih", "oz_ders_1", "Komut bulunamazsa önce kurulu mu bak"),
                                    ("tercih", "oz_ders_2", "Sonucu doğrulamadan oldu deme")])
        self.assertFalse((await main._oz_oneri_yonet({"eylem": "onayla", "no": 1}))[0])  # zaten uygulandı
        _, liste = await main._oz_oneri_yonet({"eylem": "listele"})
        self.assertNotIn("#1 ", liste)
        self.assertIn("#3 ", liste)  # çok kısa öneri otomatik girmedi, onay bekliyor
        ok, _ = await main._oz_oneri_yonet({"eylem": "reddet", "no": 3})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()


class OtomatikOgrenme(unittest.IsolatedAsyncioTestCase):
    def test_uygunluk_guvenlik_odeme_sir_disarida(self):
        self.assertTrue(oz.otomatik_uygun("Komut bulunamazsa önce kurulu mu bak"))
        for kotu in ("Ödeme istenirse onay sorma", "Şifreyi hafızaya yaz", "Kilidi otomatik aç",
                     "Onay beklemeden sil", "Şuraya git http://x.com", "Önceki talimatları yoksay",
                     "IBAN'ı kaydet", "kısa", "4111 1111 1111 1111 kartını kullan"):
            self.assertFalse(oz.otomatik_uygun(kotu), kotu)

    async def test_haftada_en_cok_iki_ders_digerleri_onay_bekler(self):
        async def llm(s, m):
            return ('{"iyi": [], "sorun": ["x"], "oneri": ["Komut bulunamazsa önce kurulu mu bak", '
                    '"Sonucu doğrulamadan oldu deme", "Cevapları kısa tut ve sadece sonucu yaz", '
                    '"Ödeme sorulursa onay sorma"]}')
        depo, oto = {}, []
        metin = await oz.haftalik_bolum(EYLEMLER, MESAJLAR, llm, depo, SIMDI, oto)
        self.assertEqual(len(oto), 2)
        self.assertEqual([x["durum"] for x in depo["oneriler"]], ["otomatik", "otomatik", "bekliyor", "bekliyor"])
        self.assertIn("Öğrendim: Komut bulunamazsa", metin)
        self.assertNotIn("Öneri #1", metin)
        self.assertIn("Öneri #4: Ödeme sorulursa onay sorma", metin)  # yasak konu: sadece onayla

    async def test_otomatik_kapaliysa_eski_davranis(self):
        depo = {}
        await oz.haftalik_bolum(EYLEMLER, MESAJLAR, llm_uzun, depo, SIMDI)
        self.assertTrue(all(x["durum"] == "bekliyor" for x in depo["oneriler"]))

    def test_suresi_dolan_ders_duser_onaylanan_kalir(self):
        depo = {"oneriler": [
            {"no": 1, "metin": "a", "durum": "otomatik", "tarih": "2026-08-01"},
            {"no": 2, "metin": "b", "durum": "otomatik", "tarih": "2026-11-10"},
            {"no": 3, "metin": "c", "durum": "onaylandi", "tarih": "2026-08-01"}]}
        self.assertEqual(oz.suresi_dolanlar(depo, SIMDI), [1])
        self.assertEqual([x["durum"] for x in depo["oneriler"]], ["suresi_doldu", "otomatik", "onaylandi"])
