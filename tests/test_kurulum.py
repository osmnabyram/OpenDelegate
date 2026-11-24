"""Kurulum sihirbazının saf mantığı (pencere açılmaz, ağ çağrısı yok)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vekil"))
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

    def test_kilit_ozetleri_kill_switch_ile_uyumlu(self):
        from unittest import mock

        import kilit
        o = kurulum.kilit_ozetleri("gizli-sifre-9", tuz=b"0123456789abcdef")
        with mock.patch.object(kilit, "_TUZ", b"0123456789abcdef"),                 mock.patch.object(kilit, "_OZET", bytes.fromhex(o["KILIT_OZET"])),                 mock.patch.object(kilit, "_OZET_SADE", bytes.fromhex(o["KILIT_OZET_SADE"])):
            self.assertTrue(kilit.sifre_dogru("gizli-sifre-9"))
            self.assertTrue(kilit.sifre_dogru("gizli`-sifre-9"))  # Telegram biçim işareti karışsa da
            self.assertFalse(kilit.sifre_dogru("yanlis"))

    def test_env_sifreyi_degil_ozeti_yazar(self):
        d = dict(self.CEVAP, KILIT_SIFRE="cok-gizli-sifre")
        metin = kurulum.env_metni(d)
        self.assertNotIn("cok-gizli-sifre", metin)
        self.assertRegex(metin, r"KILIT_OZET=[0-9a-f]{64}")

    def test_kilit_sifre_dogrulama(self):
        self.assertTrue(kurulum.dogrula("kilit", {"KILIT_SIFRE": "kisa", "KILIT_SIFRE2": "kisa"}))
        self.assertTrue(kurulum.dogrula("kilit", {"KILIT_SIFRE": "uzun-sifre-1", "KILIT_SIFRE2": "baska-sifre-1"}))
        self.assertIsNone(kurulum.dogrula("kilit", {"KILIT_SIFRE": "uzun-sifre-1", "KILIT_SIFRE2": "uzun-sifre-1"}))

    def test_dogrulama_bos_alan(self):
        self.assertTrue(kurulum.dogrula("deepseek", {}))
        self.assertTrue(kurulum.dogrula("sohbet", {"TELEGRAM_CHAT_ID": "abc"}))
        self.assertIsNone(kurulum.dogrula("sohbet", {"TELEGRAM_CHAT_ID": "-100123"}))


if __name__ == "__main__":
    unittest.main()
