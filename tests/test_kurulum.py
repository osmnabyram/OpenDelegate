"""Kurulum sihirbazının saf mantığı (pencere açılmaz, ağ çağrısı yok)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kurulum  # noqa: E402


class Mantik(unittest.TestCase):
    CEVAP = {"KULLANICI_ADI": "Ali", "meslek": "inşaat mühendisi", "takim": "Sadece ben", "kullanim": "Hatırlatma ve planlama",
             "pc_os": "Windows", "pc_acik": "Genelde açık", "telefon": "Android", "sehir": "Ankara",
             "DEEPSEEK_API_KEY": "sk-x", "TELEGRAM_BOT_TOKEN": "1:AA", "TELEGRAM_CHAT_ID": "42"}

    def test_profil_metni(self):
        m = kurulum.profil_metni(self.CEVAP)
        for parca in ("Ali", "inşaat mühendisi", "Windows", "Android", "Ankara"):
            self.assertIn(parca, m)
        self.assertNotIn("\n", m)

    def test_env_tek_satirlik_ve_sirlar_uretilir(self):
        with tempfile.TemporaryDirectory() as t:
            yol = kurulum.yaz(dict(self.CEVAP), Path(t) / ".env")
            metin = yol.read_text(encoding="utf-8")
        self.assertIn("DEEPSEEK_API_KEY=sk-x", metin)
        self.assertIn("SEHIR_AD=Ankara", metin)
        self.assertRegex(metin, r"WEBHOOK_SECRET=[0-9a-f]{64}")
        self.assertRegex(metin, r"SESLI_TOKEN=[0-9a-f]{64}")
        self.assertEqual(sum(1 for s in metin.splitlines() if s.startswith("PROFIL=")), 1)

    def test_temiz_env_bozan_karakterleri_atar(self):
        self.assertEqual(kurulum._temiz('a\nb # "c"'), "a b c")

    def test_dogrulama_bos_alan(self):
        self.assertTrue(kurulum.dogrula("deepseek", {}))
        self.assertTrue(kurulum.dogrula("sohbet", {"TELEGRAM_CHAT_ID": "abc"}))
        self.assertIsNone(kurulum.dogrula("sohbet", {"TELEGRAM_CHAT_ID": "-100123"}))


if __name__ == "__main__":
    unittest.main()
