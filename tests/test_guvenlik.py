"""Genel güvenlik sertleştirmesi (23.11): başlıklar, hız sınırı, gövde sınırı, log/sır maskesi, depoda sır yok."""

import logging
import re
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import config
import guvenlik

KOK = Path(__file__).resolve().parent.parent


class Basliklar(unittest.TestCase):
    def test_her_cevaba_eklenir_rotanin_kendisi_ezilmez(self):
        async def a(request):
            return PlainTextResponse("x")

        async def b(request):
            return PlainTextResponse("y", headers={"Referrer-Policy": "same-origin"})

        app = Starlette(routes=[Route("/a", a), Route("/b", b)], middleware=[Middleware(guvenlik.BaslikEkleyici)])
        c = TestClient(app)
        r = c.get("/a")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertEqual(c.get("/b").headers["referrer-policy"], "same-origin")


class HizSiniri(unittest.TestCase):
    def test_pencere_dolunca_reddeder_sure_gecince_acar(self):
        t = [0.0]
        s = guvenlik.HizSiniri(limit=3, pencere_sn=60, saat=lambda: t[0])
        self.assertTrue(all(s.izin_var() for _ in range(3)))
        self.assertFalse(s.izin_var())
        t[0] = 61
        self.assertTrue(s.izin_var())


class GovdeSiniri(unittest.TestCase):
    def test_bozuk_ve_buyuk_baslik(self):
        k = lambda v: mock.Mock(headers={"content-length": v} if v is not None else {})  # noqa: E731
        self.assertFalse(guvenlik.govde_cok_buyuk(k("10"), 100))
        self.assertFalse(guvenlik.govde_cok_buyuk(k(None), 100))
        self.assertTrue(guvenlik.govde_cok_buyuk(k("101"), 100))
        self.assertTrue(guvenlik.govde_cok_buyuk(k("abc"), 100))


class SirMaskesi(unittest.TestCase):
    def test_bilinen_sir_bicimleri(self):
        bot = "123456789:AA" + "x" * 33
        self.assertNotIn(bot, guvenlik.sir_maskele(f"url https://api.telegram.org/bot{bot}/getMe"))
        self.assertNotIn("sk-" + "a" * 30, guvenlik.sir_maskele("key=sk-" + "a" * 30))
        self.assertNotIn("abcdefghijklmnop1234", guvenlik.sir_maskele("Authorization: Bearer abcdefghijklmnop1234"))
        self.assertEqual(guvenlik.sir_maskele("normal satir"), "normal satir")

    def test_log_filtresi(self):
        bot = "123456789:AA" + "y" * 33
        kayit = logging.LogRecord("x", logging.INFO, "", 0, "istek %s", (bot,), None)
        guvenlik.SirMaskeleyici().filter(kayit)
        self.assertNotIn(bot, kayit.getMessage())


class HassasMetin(unittest.TestCase):
    def test_kart_ve_iban_yazilmaz(self):
        self.assertTrue(guvenlik.hassas_metin_mi("4111 1111 1111 1111"))
        self.assertTrue(guvenlik.hassas_metin_mi("TR33 0006 1005 1978 6457 8413 26"))
        self.assertFalse(guvenlik.hassas_metin_mi("0532 123 45 67"))
        self.assertFalse(guvenlik.hassas_metin_mi("saat 19:30'da geliyorum"))


class AcilisDenetimi(unittest.TestCase):
    def test_kisa_secret_uyari_verir_deger_yazmaz(self):
        with mock.patch.object(config, "WEBHOOK_SECRET", "kisa"):
            u = guvenlik.acilis_denetimi()
        self.assertTrue(any("WEBHOOK_SECRET" in x for x in u))
        self.assertFalse(any("kisa" == x for x in u))


class DepodaSirYok(unittest.TestCase):
    def test_env_izlenmiyor_ve_izlenen_dosyada_sir_bicimi_yok(self):
        try:
            cikti = subprocess.run(["git", "ls-files"], cwd=KOK, capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git yok")
        dosyalar = cikti.splitlines()
        self.assertNotIn(".env", dosyalar)
        desen = re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}|\bsk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY")
        sizan = []
        for ad in dosyalar:
            p = KOK / ad
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".mp3", ".zip", ".jar", ".so", ".ttf", ".webp", ".gif"} or not p.is_file():
                continue
            try:
                if desen.search(p.read_text(encoding="utf-8", errors="ignore")):
                    sizan.append(ad)
            except OSError:
                pass
        self.assertEqual(sizan, [], f"sır biçimi bulundu: {sizan}")


if __name__ == "__main__":
    unittest.main()
