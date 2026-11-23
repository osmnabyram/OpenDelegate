"""/dinle uç noktası: sürüm kapısı, telefon eylemi başlığı, Whisper uydurması.

Kullanıcı 21.11: "şu saate alarm kur" telefonda kurulsun. Eski uygulama X-Eylem'i tanımadığı için
ona telefonda_yap sunulmamalı (yoksa "kurdum" der ama kurulmaz).
"""

import json
import unittest
from unittest import mock
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import sesli


class SahteBeyin:
    def __init__(self):
        self.gelen_eylemler = "yok"

    async def uygulama_cevabi(self, soru, gecmis, eylemler=None, ekran_ajani=False):
        self.gelen_eylemler = eylemler
        if eylemler is not None:
            eylemler.append({"eylem": "alarm", "saat": 7, "dakika": 30, "etiket": ""})
        return "Alarmı 07:30'a kurdum efendim."


class DinleUcu(unittest.TestCase):
    def setUp(self):
        self.beyin = SahteBeyin()
        self.metin = "Yarın 7 buçuğa alarm kur."

        async def stt(veri, dosya_adi="", tur="", model=None, ipucu=""):
            self.stt_model = model
            return self.metin

        async def tts(metin, ses, hiz):
            return b"MP3"

        yamalar = [
            mock.patch.object(sesli.config, "SESLI_TOKEN", "tok"),
            mock.patch.object(sesli.config, "GROQ_API_KEY", "anahtar"),
            mock.patch.object(sesli.stt_mod, "metne_cevir", stt),
            mock.patch.object(sesli.seslendirme, "edge_sentez", tts),
            mock.patch.object(sesli, "beyin", lambda: self.beyin),
            mock.patch.object(sesli, "_GECMIS", []),
            mock.patch.object(sesli, "_son_soru", 0.0),
            mock.patch.object(sesli, "_saat", lambda: self.saat),
        ]
        self.saat = 10_000.0
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)
        self.istemci = TestClient(Starlette(routes=[
            Route("/dinle/{token}", sesli.sesli_dinle, methods=["POST"]),
            Route("/sor/{token}", sesli.sesli_sor, methods=["POST"])]))

    def _gonder(self, **basliklar):
        return self.istemci.post("/dinle/tok", content=b"RIFF....", headers={"content-type": "audio/wav", **basliklar})

    def test_yeni_surum_eylemi_baslikta_alir(self):
        y = self._gonder(**{"X-Vekil-Surum": "2"})
        self.assertEqual(y.status_code, 200)
        self.assertEqual(json.loads(unquote(y.headers["X-Eylem"])),
                         [{"eylem": "alarm", "saat": 7, "dakika": 30, "etiket": ""}])
        self.assertEqual(unquote(y.headers["X-Cevap"]), "Alarmı 07:30'a kurdum efendim.")
        self.assertEqual(self.stt_model, sesli.config.STT_TELEFON_MODEL)

    def test_eski_surume_telefon_eylemi_sunulmaz(self):
        y = self._gonder()
        self.assertEqual(y.status_code, 200)
        self.assertIsNone(self.beyin.gelen_eylemler)
        self.assertNotIn("X-Eylem", y.headers)

    def test_whisper_uydurmasi_soru_sayilmaz(self):
        self.metin = "Altyazı M.K."
        self.assertEqual(self._gonder(**{"X-Vekil-Surum": "2"}).status_code, 422)
        self.assertEqual(self.beyin.gelen_eylemler, "yok")  # beyne hiç gitmedi

    def test_eski_konusma_10_dk_sonra_unutulur(self):
        gelen = []

        async def cevap(soru, gecmis, eylemler=None):
            gelen.append(list(gecmis))
            return "Tamam efendim."
        self.beyin.uygulama_cevabi = cevap
        self._gonder()
        self.saat += 60
        self._gonder()
        self.assertEqual(len(gelen[1]), 2)  # 1 dk sonra: önceki soru-cevap bağlamda
        self.saat += 601
        self._gonder()
        self.assertEqual(gelen[2], [])  # 10 dk sessizlik: temiz sayfa

    def test_yazili_soru_sessiz(self):
        # Paneldeki klavye (21.11): ses tanıma yok, sessizse cevap sesi üretilmez; eylem yine gelir.
        y = self.istemci.post("/sor/tok", json={"metin": "Yarın 7 buçuğa alarm kur", "sessiz": True},
                              headers={"X-Vekil-Surum": "3"})
        self.assertEqual(y.status_code, 200)
        self.assertEqual(y.content, b"")
        self.assertEqual(unquote(y.headers["X-Metin"]), "Yarın 7 buçuğa alarm kur")
        self.assertIn("X-Eylem", y.headers)
        self.assertEqual(self.istemci.post("/sor/tok", json={"metin": "  "}).status_code, 400)
        self.assertEqual(self.istemci.post("/sor/baska", json={"metin": "x"}).status_code, 401)

    def test_yanlis_token(self):
        self.assertEqual(self.istemci.post("/dinle/baska", content=b"x").status_code, 401)


if __name__ == "__main__":
    unittest.main()
