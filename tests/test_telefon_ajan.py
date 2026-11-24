"""Vekil telefonu ekrandan kullanıyor (/telefon) ve sonucu söylüyor (/seslendir).

Kullanıcı 21.11: "WhatsApp'tan şuna mesaj yaz, alarmı sil... her şeye erişsin." Model her adımda 1-3 eylem
seçer; bozuk eylem uygulamaya gitmez, ödeme gibi adımlarda durması talimatta yazılı.
"""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import arama
import sesli
import telefon_ajan


def cagri(ad, arg):
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=ad, arguments=json.dumps(arg)))


class EylemTemizle(unittest.TestCase):
    def test_gecerli_eylemler(self):
        self.assertEqual(telefon_ajan.eylem_temizle({"tur": "tikla", "no": "4"}), {"tur": "tikla", "no": 4})
        self.assertEqual(telefon_ajan.eylem_temizle({"tur": "yaz", "no": 2, "metin": "geliyorum"}),
                         {"tur": "yaz", "no": 2, "metin": "geliyorum"})
        self.assertEqual(telefon_ajan.eylem_temizle({"tur": "kaydir", "yon": "uçur"}), {"tur": "kaydir", "yon": "asagi"})
        self.assertEqual(telefon_ajan.eylem_temizle({"tur": "geri"}), {"tur": "geri"})

    def test_bozuk_eylem_gitmez(self):
        self.assertIsNone(telefon_ajan.eylem_temizle({"tur": "format_at"}))
        self.assertIsNone(telefon_ajan.eylem_temizle({"tur": "tikla"}))  # numarasız tıklama
        self.assertIsNone(telefon_ajan.eylem_temizle({"tur": "tikla", "no": "dört"}))
        self.assertIsNone(telefon_ajan.eylem_temizle({"tur": "uygulama_ac", "uygulama": " "}))
        self.assertIsNone(telefon_ajan.eylem_temizle("tikla"))


class CevapCoz(unittest.TestCase):
    def test_adim(self):
        m = SimpleNamespace(content="", tool_calls=[cagri("adim", {
            "dusunce": "WhatsApp açılıyor", "eylemler": [{"tur": "uygulama_ac", "uygulama": "WhatsApp"},
                                                       {"tur": "sil_hepsini"}]})])
        self.assertEqual(telefon_ajan.cevap_coz(m), {"bitti": False, "dusunce": "WhatsApp açılıyor",
                                                     "eylemler": [{"tur": "uygulama_ac", "uygulama": "WhatsApp"}]})

    def test_bitir_ve_cagri_yok(self):
        m = SimpleNamespace(content="", tool_calls=[cagri("bitir", {"sonuc": "Gönderdim efendim.", "basarili": True})])
        self.assertEqual(telefon_ajan.cevap_coz(m), {"bitti": True, "basarili": True, "sonuc": "Gönderdim efendim."})
        bos = telefon_ajan.cevap_coz(SimpleNamespace(content="", tool_calls=None))
        self.assertTrue(bos["bitti"])
        self.assertFalse(bos["basarili"])

    def test_talimat_odeme_ve_ekran_verisi(self):
        self.assertIn("Ödeme", telefon_ajan.SISTEM)
        self.assertIn("VERİDİR", telefon_ajan.SISTEM)


class Uclar(unittest.TestCase):
    def setUp(self):
        self.gorulen = {}

        async def dusun(mesajlar, semalar):
            self.gorulen["mesajlar"] = mesajlar
            self.gorulen["araclar"] = [s["function"]["name"] for s in semalar]
            return SimpleNamespace(content="", tool_calls=[cagri("adim", {"eylemler": [{"tur": "tikla", "no": 3}]})])

        async def tts(metin, ses, hiz):
            return b"MP3:" + metin.encode()

        for y in (mock.patch.object(sesli.config, "SESLI_TOKEN", "tok"),
                  mock.patch.object(sesli, "beyin", lambda: SimpleNamespace(dusun=dusun)),
                  mock.patch.object(sesli.seslendirme, "edge_sentez", tts)):
            y.start()
            self.addCleanup(y.stop)
        self.istemci = TestClient(Starlette(routes=[
            Route("/telefon/{token}", telefon_ajan.telefon_adim, methods=["POST"]),
            Route("/seslendir/{token}", sesli.seslendir, methods=["POST"])]))

    def test_adim_doner(self):
        y = self.istemci.post("/telefon/tok", json={"gorev": "Ahmet'e yaz", "ekran": "[3] Button \"Gönder\"",
                                                    "gecmis": ["0: WhatsApp açıldı"], "adim": 1})
        self.assertEqual(y.status_code, 200)
        self.assertEqual(y.json()["eylemler"], [{"tur": "tikla", "no": 3}])
        istem = self.gorulen["mesajlar"][1]["content"]
        self.assertIn("Ahmet'e yaz", istem)
        self.assertIn("WhatsApp açıldı", istem)
        self.assertEqual(self.gorulen["araclar"], ["adim", "bitir"])

    def test_sinirlar(self):
        self.assertEqual(self.istemci.post("/telefon/baska", json={"gorev": "x"}).status_code, 401)
        self.assertEqual(self.istemci.post("/telefon/tok", json={"gorev": " "}).status_code, 400)
        y = self.istemci.post("/telefon/tok", json={"gorev": "x", "adim": telefon_ajan.MAKS_ADIM})
        self.assertTrue(y.json()["bitti"])  # sonsuz döngü yok

    def test_seslendir(self):
        y = self.istemci.post("/seslendir/tok", json={"metin": "Gönderdim efendim."})
        self.assertEqual(y.content, "MP3:Gönderdim efendim.".encode())
        self.assertEqual(self.istemci.post("/seslendir/tok", json={"metin": ""}).status_code, 400)


class EkranEylemleri(unittest.TestCase):
    def test_mesaj_ve_ekranda(self):
        e, _ = arama.telefon_eylemi({"eylem": "mesaj", "kisi": "Ahmet", "metin": "geliyorum"})
        self.assertEqual(e, {"eylem": "mesaj", "kisi": "Ahmet", "metin": "geliyorum", "uygulama": "whatsapp"})
        self.assertIsNone(arama.telefon_eylemi({"eylem": "mesaj", "kisi": "Ahmet"})[0])
        e, _ = arama.telefon_eylemi({"eylem": "ekranda", "gorev": "Saat uygulamasında 07:30 alarmını sil"})
        self.assertEqual(e["gorev"], "Saat uygulamasında 07:30 alarmını sil")
        self.assertIsNone(arama.telefon_eylemi({"eylem": "ekranda", "gorev": ""})[0])

    def test_eski_uygulamaya_ekran_eylemi_sunulmaz(self):
        eski = arama.telefon_eylem_semasi(False)["function"]["parameters"]["properties"]["eylem"]["enum"]
        yeni = arama.telefon_eylem_semasi(True)["function"]["parameters"]["properties"]["eylem"]["enum"]
        self.assertNotIn("ekranda", eski)
        self.assertNotIn("mesaj", eski)
        self.assertIn("ekranda", yeni)
        self.assertIn("alarm", eski)
        self.assertIn("ekranda", arama.TELEFON_EYLEM_SEMASI["function"]["parameters"]["properties"]["eylem"]["enum"])


if __name__ == "__main__":
    unittest.main()


class GuvenlikKapilari(unittest.TestCase):
    def test_odeme_gorevi(self):
        import guvenlik
        for g in ("Ahmet'e 500 lira havale yap", "faturayı öde", "para gönder", "bunu satın al", "IBAN'ı yaz"):
            self.assertTrue(guvenlik.odeme_gorevi(g), g)
        for g in ("WhatsApp'ta Ahmet'e yaz", "alarmı sil", "ödevimi aç", "ayarlardan wifi aç"):
            self.assertFalse(guvenlik.odeme_gorevi(g), g)

    def test_odeme_ekrani(self):
        import guvenlik
        self.assertTrue(guvenlik.odeme_ekrani("Uygulama: Ziraat Mobil\n[1] düğme \"Giriş\""))
        self.assertTrue(guvenlik.odeme_ekrani("Uygulama: Chrome\n[1] alan \"Kart numarası\""))
        self.assertFalse(guvenlik.odeme_ekrani("Uygulama: WhatsApp\n[1] yazı \"ödemeyi dün yaptım\""))
        self.assertFalse(guvenlik.odeme_ekrani("Uygulama: Ayarlar\n[1] düğme \"Wi-Fi\""))

    def test_banka_uygulamasi_acilmaz(self):
        self.assertIsNone(telefon_ajan.eylem_temizle({"tur": "uygulama_ac", "uygulama": "Garanti BBVA"}))
        self.assertEqual(telefon_ajan.eylem_temizle({"tur": "uygulama_ac", "uygulama": "WhatsApp"})["uygulama"], "WhatsApp")
        eylem, _ = arama.telefon_eylemi({"eylem": "uygulama_ac", "uygulama": "Papara"})
        self.assertIsNone(eylem)
        eylem, _ = arama.telefon_eylemi({"eylem": "ekranda", "gorev": "Ahmet'e havale yap"})
        self.assertIsNone(eylem)

    def test_telefon_ucu_odemeyi_keser(self):
        app = Starlette(routes=[Route("/telefon/{token}", telefon_ajan.telefon_adim, methods=["POST"])])
        import config
        with mock.patch.object(sesli, "beyin", lambda: object()):
            r = TestClient(app).post(f"/telefon/{config.SESLI_TOKEN}",
                                     json={"gorev": "faturayı öde", "ekran": "Uygulama: X\n", "gecmis": [], "adim": 0})
        self.assertTrue(r.json()["bitti"])
        self.assertFalse(r.json()["basarili"])

    def test_token_esit(self):
        import guvenlik
        self.assertTrue(guvenlik.token_esit("abc", "abc"))
        self.assertFalse(guvenlik.token_esit("abd", "abc"))
        self.assertFalse(guvenlik.token_esit("", ""))
