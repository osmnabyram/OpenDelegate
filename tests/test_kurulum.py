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
             "DEEPSEEK_API_KEY": "sk-x", "WEB_PAROLA": "uzun-web-parolasi-1", "WEB_TOTP_SIR": "JBSWY3DPEHPK3PXP"}

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

    def test_web_parolasi_dogrulama_ve_totp_anahtari(self):
        self.assertTrue(kurulum.dogrula("web", {"WEB_PAROLA": "kisa", "WEB_PAROLA2": "kisa"}))
        self.assertTrue(kurulum.dogrula("web", {"WEB_PAROLA": "uzun-web-parolasi-1", "WEB_PAROLA2": "baska-web-parola-2"}))
        d = {"WEB_PAROLA": "uzun-web-parolasi-1", "WEB_PAROLA2": "uzun-web-parolasi-1"}
        self.assertIsNone(kurulum.dogrula("web", d))
        sir = d["WEB_TOTP_SIR"]
        self.assertRegex(sir, r"^[A-Z2-7]{32}$")  # 160 bit, base32: web_sohbet bunu okuyabilir
        kurulum.dogrula("web", d)
        self.assertEqual(d["WEB_TOTP_SIR"], sir)  # geri/ileri gidince değişmez
        self.assertTrue(kurulum.dogrula("totp_onay", d))
        d["TOTP_ONAY"] = "1"
        self.assertIsNone(kurulum.dogrula("totp_onay", d))

    def test_env_web_ve_ana_sir_yazilir_telegram_gerekmez(self):
        with tempfile.TemporaryDirectory() as t:
            metin = kurulum.yaz(dict(self.CEVAP), Path(t) / ".env").read_text(encoding="utf-8")
        self.assertIn("WEB_PAROLA=uzun-web-parolasi-1", metin)
        self.assertRegex(metin, r"OPENDELEGATE_SIR=[0-9a-f]{64}")
        self.assertNotIn("TELEGRAM_BOT_TOKEN", metin)
        self.assertNotIn("WEB_PAROLA2", metin)

    def test_kurtarma_kodu_formati_ve_rastgeleligi(self):
        import re as re_mod

        kod1, kod2 = kurulum.kurtarma_kodu_uret(), kurulum.kurtarma_kodu_uret()
        self.assertRegex(kod1, r"^[23456789A-HJ-NP-Z]{5}(-[23456789A-HJ-NP-Z]{5}){3}$")
        self.assertNotEqual(kod1, kod2)  # her kurulumda farklı; ortak/sabit bir kod değil

    def test_kilit_dogrulamasi_kurtarma_kodu_uretir(self):
        d = {"KILIT_SIFRE": "sifre-1234", "KILIT_SIFRE2": "sifre-1234"}
        self.assertIsNone(kurulum.dogrula("kilit", d))
        self.assertIn("_KURTARMA_KODU", d)
        onceki = d["_KURTARMA_KODU"]
        self.assertIsNone(kurulum.dogrula("kilit", d))  # tekrar çağrılırsa (geri/ileri) kod DEĞİŞMEZ
        self.assertEqual(d["_KURTARMA_KODU"], onceki)

    def test_kurtarma_onay_dogrulamasi(self):
        self.assertIsNotNone(kurulum.dogrula("kurtarma_onay", {}))
        self.assertIsNotNone(kurulum.dogrula("kurtarma_onay", {"KURTARMA_ONAY": ""}))
        self.assertIsNone(kurulum.dogrula("kurtarma_onay", {"KURTARMA_ONAY": "1"}))

    def test_kurtarma_ozetleri_kill_switch_ile_uyumlu(self):
        from unittest import mock

        import kilit
        o = kurulum.kurtarma_ozetleri("ABCDE-FGHIJ-KLMNO-PQRST", tuz=b"0123456789abcdef")
        with mock.patch.object(kilit, "_KURTARMA_TUZ", b"0123456789abcdef"), \
                mock.patch.object(kilit, "_KURTARMA_OZET", bytes.fromhex(o["KILIT_KURTARMA_OZET"])):
            self.assertTrue(kilit.kurtarma_kodu_dogru("ABCDE-FGHIJ-KLMNO-PQRST"))
            self.assertTrue(kilit.kurtarma_kodu_dogru("abcde-fghij-klmno-pqrst"))  # büyük/küçük harf duyarsız
            self.assertFalse(kilit.kurtarma_kodu_dogru("YANLIS-KOD-XXXXX-YYYYY"))

    def test_env_kurtarma_kodunu_degil_ozetini_yazar(self):
        d = dict(self.CEVAP, _KURTARMA_KODU="ABCDE-FGHIJ-KLMNO-PQRST")
        metin = kurulum.env_metni(d)
        self.assertNotIn("ABCDE-FGHIJ-KLMNO-PQRST", metin)
        self.assertRegex(metin, r"KILIT_KURTARMA_OZET=[0-9a-f]{64}")
        self.assertNotIn("_KURTARMA_KODU", metin)


if __name__ == "__main__":
    unittest.main()
