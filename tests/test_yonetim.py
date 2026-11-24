"""Yönetim sayfası: token kapısı, sayılar, gizlilik (argüman/sonuç sızmaz), hafıza erişilemezse yine açılır, /yonetim komutu."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient

import config
import hafiza
import harita
import main
import yonetim

GIZLI = "cok-gizli-dosya-yolu-ve-sifre-ASDF"


class YonetimTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.yama = mock.patch.object(config, "DB_YOLU", Path(self.tmp.name) / "y.db")
        self.yama.start()
        app = mock.MagicMock()
        app.bot = mock.MagicMock()
        self.istemci = TestClient(main.web_uygulamasi(app), base_url="https://vekil.test")
        self.t = yonetim.token()

    def tearDown(self):
        self.yama.stop()
        self.tmp.cleanup()

    def test_token_sabit_uzunlukta_ve_haritadan_farkli(self):
        self.assertEqual(len(self.t), 32)
        self.assertNotEqual(self.t, harita.token())
        self.assertTrue(yonetim.token_dogru(self.t))
        self.assertFalse(yonetim.token_dogru(harita.token()))
        self.assertFalse(yonetim.token_dogru(None))
        self.assertFalse(yonetim.token_dogru(""))

    def test_yanlis_token_404(self):
        self.assertEqual(self.istemci.get("/yonetim/yanlis").status_code, 404)
        self.assertEqual(self.istemci.get("/yonetim/yanlis/veri").status_code, 404)
        self.assertEqual(self.istemci.get(f"/yonetim/{harita.token()}/veri").status_code, 404)

    def test_sayfa_acilir_ve_onbellege_girmez(self):
        r = self.istemci.get(f"/yonetim/{self.t}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Yönetim", r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertIn("noindex", r.headers["x-robots-tag"])

    def test_sayfa_innerhtml_kullanmaz(self):
        self.assertNotIn("innerHTML", yonetim.sayfa())  # sunucu verisi textContent ile yazılır (XSS yok)

    def test_veri_sayilari_dogru(self):
        hafiza.bilgi_yaz.__wrapped__("tercih", "a", "1")
        hafiza.bilgi_yaz.__wrapped__("tercih", "b", "2")
        hafiza.bilgi_yaz.__wrapped__("not", "c", "3")
        hafiza.ozet_kaydet.__wrapped__(1, "özet")
        hafiza.mesaj_kaydet.__wrapped__(1, "user", "merhaba")
        e = hafiza.eylem_olustur.__wrapped__(1, "hava_durumu", {"yol": GIZLI}, "düşük")
        hafiza.eylem_guncelle.__wrapped__(e, "basarili", GIZLI)
        v = self.istemci.get(f"/yonetim/{self.t}/veri").json()
        s = v["istatistik"]
        self.assertEqual(s["bilgi_turleri"], {"tercih": 2, "not": 1})
        self.assertEqual((s["ozet_adedi"], s["mesaj_adedi"]), (1, 1))
        self.assertEqual(s["eylem_durumlari"], {"basarili": 1})
        self.assertEqual(s["son_eylemler"][0]["tool"], "hava_durumu")
        self.assertEqual(v["model"], config.DEEPSEEK_MODEL)
        self.assertTrue(v["hafiza"]["erisilebilir"])
        self.assertEqual(v["hafiza"]["tur"], "sqlite")

    def test_eylem_argumani_ve_sonucu_sizmaz(self):
        e = hafiza.eylem_olustur.__wrapped__(1, "dosya_yaz", {"yol": GIZLI}, "orta")
        hafiza.eylem_guncelle.__wrapped__(e, "basarili", GIZLI)
        hafiza.mesaj_kaydet.__wrapped__(1, "user", GIZLI)
        govde = self.istemci.get(f"/yonetim/{self.t}/veri").text
        self.assertNotIn(GIZLI, govde)

    def test_hafiza_erisilemezse_yine_acilir(self):
        with mock.patch.object(hafiza, "istatistik", mock.AsyncMock(return_value=None)):
            v = self.istemci.get(f"/yonetim/{self.t}/veri").json()
        self.assertFalse(v["hafiza"]["erisilebilir"])
        self.assertIsNone(v["istatistik"])

    def test_son_sureler_en_fazla_10(self):
        v = yonetim.derle(None, hafiza_turu="sqlite", ajan_cevrimici=False, son_sureler=[1.23456] * 15)
        self.assertEqual(len(v["son_sureler_sn"]), 10)
        self.assertEqual(v["son_sureler_sn"][0], 1.2)

    def test_komut_baglanti_gonderir(self):
        guncelleme = SimpleNamespace(message=mock.AsyncMock())
        with mock.patch.object(main, "_yetkili", return_value=True), \
                mock.patch.object(config, "WEBHOOK_URL", "https://vekil.test"):
            asyncio.run(main.komut_yonetim(guncelleme, SimpleNamespace()))
        self.assertIn(f"https://vekil.test/yonetim/{self.t}", guncelleme.message.reply_text.call_args.args[0])

    def test_komut_yerelde_adres_yoksa_aciklar_ve_yetkisize_cevap_vermez(self):
        guncelleme = SimpleNamespace(message=mock.AsyncMock())
        with mock.patch.object(main, "_yetkili", return_value=True), mock.patch.object(config, "WEBHOOK_URL", ""):
            asyncio.run(main.komut_yonetim(guncelleme, SimpleNamespace()))
        self.assertNotIn("/yonetim/", guncelleme.message.reply_text.call_args.args[0])
        yetkisiz = SimpleNamespace(message=mock.AsyncMock())
        with mock.patch.object(main, "_yetkili", return_value=False):
            asyncio.run(main.komut_yonetim(yetkisiz, SimpleNamespace()))
        yetkisiz.message.reply_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
