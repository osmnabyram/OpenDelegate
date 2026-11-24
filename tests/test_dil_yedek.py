"""Asistan dili ayarı (DIL=tr|en) ve /yedek hafıza dışa aktarımı."""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import arama
import config
import hafiza
import main
import seslendirme


def _config_yeniden(**ortam):
    """DIL gibi ortam değişkenleriyle config'i taze yükler; çağıran sonda eski haline döndürür."""
    with mock.patch.dict(os.environ, ortam):
        return importlib.reload(config)


class DilTesti(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config)

    def test_varsayilan_turkce_talimat_bos(self):
        c = _config_yeniden(DIL="tr")
        self.assertEqual((c.DIL, c.DIL_TALIMATI, c.STT_DIL), ("tr", "", "tr"))

    def test_ingilizce_talimat_ve_tanima_dili(self):
        c = _config_yeniden(DIL="en")
        self.assertEqual((c.DIL, c.STT_DIL), ("en", "en"))
        self.assertIn("English", c.DIL_TALIMATI)
        self.assertIn("efendim", c.DIL_TALIMATI)  # Türkçe kuralı geçersiz kılar

    def test_gecersiz_dil_turkceye_duser(self):
        self.assertEqual(_config_yeniden(DIL="fr").DIL, "tr")
        self.assertEqual(_config_yeniden(DIL=" EN ").DIL, "en")

    def test_stt_dil_acikca_verilirse_ezilmez(self):
        self.assertEqual(_config_yeniden(DIL="en", STT_DIL="").STT_DIL, "")

    def test_ses_ve_twilio_dili_dile_gore(self):
        _config_yeniden(DIL="en")
        self.assertIn("en-US", importlib.reload(seslendirme).SES)
        self.assertIn('language="en-US"', arama.twiml_dinle(None, "/x"))
        _config_yeniden(DIL="tr")
        self.assertEqual(importlib.reload(seslendirme).SES, "tr-TR-AhmetNeural")
        self.assertIn('language="tr-TR"', arama.twiml_dinle(None, "/x"))


class YedekTesti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.yama = mock.patch.object(config, "DB_YOLU", Path(self.tmp.name) / "t.db")
        self.yama.start()
        hafiza.onbellegi_bosalt()

    def tearDown(self):
        self.yama.stop()
        self.tmp.cleanup()

    def test_yedek_bilgi_ozet_ve_ayar_icerir_kilit_icermez(self):
        hafiza.bilgi_yaz.__wrapped__("tercih", "hitap", "kısa konuş")
        hafiza.ozet_kaydet.__wrapped__(1, "Bugün rapor yazıldı.")
        hafiza._ayar_yaz("tema", "koyu")
        hafiza._ayar_yaz("kilit", '{"ozet": "gizli"}')
        hafiza._ayar_yaz("api_token_x", "abc")
        veri = asyncio.run(hafiza.yedek_olustur())
        self.assertEqual(veri["surum"], 1)
        self.assertEqual([(b["tur"], b["anahtar"], b["deger"]) for b in veri["bilgiler"]],
                         [("tercih", "hitap", "kısa konuş")])
        self.assertEqual(veri["ozetler"][0]["ozet"], "Bugün rapor yazıldı.")
        anahtarlar = {a["anahtar"] for a in veri["ayarlar"]}
        self.assertIn("tema", anahtarlar)
        self.assertNotIn("kilit", anahtarlar)
        self.assertNotIn("api_token_x", anahtarlar)

    def test_sir_bicimli_kayit_yedege_girmez(self):
        hafiza.ozet_kaydet.__wrapped__(1, "anahtar sk-abcdefghijklmnopqrstuv1234")
        hafiza.ozet_kaydet.__wrapped__(1, "normal özet")
        veri = asyncio.run(hafiza.yedek_olustur())
        self.assertEqual([o["ozet"] for o in veri["ozetler"]], ["normal özet"])

    def test_komut_dosya_gonderir(self):
        hafiza.bilgi_yaz.__wrapped__("not", "ornek", "deger")
        bot = mock.AsyncMock()
        guncelleme = SimpleNamespace(effective_chat=SimpleNamespace(id=5), message=mock.AsyncMock())
        with mock.patch.object(main, "_yetkili", return_value=True):
            asyncio.run(main.komut_yedek(guncelleme, SimpleNamespace(bot=bot)))
        kw = bot.send_document.call_args.kwargs
        self.assertTrue(kw["filename"].startswith("vekil-hafiza-") and kw["filename"].endswith(".json"))
        icerik = json.loads(kw["document"].getvalue().decode("utf-8"))
        self.assertEqual(icerik["bilgiler"][0]["anahtar"], "ornek")

    def test_yetkisiz_kisiye_gondermez(self):
        bot = mock.AsyncMock()
        guncelleme = SimpleNamespace(effective_chat=SimpleNamespace(id=5), message=mock.AsyncMock())
        with mock.patch.object(main, "_yetkili", return_value=False):
            asyncio.run(main.komut_yedek(guncelleme, SimpleNamespace(bot=bot)))
        bot.send_document.assert_not_called()

    def test_hafiza_okunamazsa_dosya_yerine_mesaj(self):
        bot = mock.AsyncMock()
        guncelleme = SimpleNamespace(effective_chat=SimpleNamespace(id=5), message=mock.AsyncMock())
        with mock.patch.object(main, "_yetkili", return_value=True), \
                mock.patch.object(hafiza, "yedek_olustur", mock.AsyncMock(return_value=None)):
            asyncio.run(main.komut_yedek(guncelleme, SimpleNamespace(bot=bot)))
        bot.send_document.assert_not_called()
        guncelleme.message.reply_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
