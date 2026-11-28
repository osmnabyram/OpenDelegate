"""Hafıza kayıtları: Türkiye saatiyle yazılır, eylem kaydı kırpılır, eskiler silinir (28.11 denetimi).

Neon ücretsiz 0,5 GB: dosya_yaz'ın tüm içeriği her eylemde saklanıyordu ve hiçbir kayıt silinmiyordu.
Geçici SQLite ile çalışır (DATABASE_URL boş).
"""

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import config
import hafiza
import zamanlayici


class EylemKaydi(unittest.TestCase):
    def setUp(self):
        klasor = tempfile.TemporaryDirectory()
        self.addCleanup(klasor.cleanup)
        for y in (mock.patch.object(config, "DATABASE_URL", ""),
                  mock.patch.object(config, "DB_YOLU", Path(klasor.name) / "test.db")):
            y.start()
            self.addCleanup(y.stop)

    def test_turkiye_saati(self):
        yazilan = datetime.fromisoformat(hafiza._simdi())
        tr = datetime.now(zamanlayici.TR).replace(tzinfo=None)
        self.assertLess(abs((tr - yazilan).total_seconds()), 5)

    def test_buyuk_arguman_kirpilir(self):
        eid = asyncio.run(hafiza.eylem_olustur(1, "dosya_yaz", {"yol": "C:/a.py", "icerik": "x" * 300_000}, "orta"))
        satir = hafiza._calistir("SELECT argumanlar FROM eylemler WHERE id = %s", (eid,), sonuc="tek")
        self.assertLessEqual(len(satir["argumanlar"]), hafiza.EYLEM_ARG_SINIRI)

    def test_eski_eylemler_silinir_yeniler_kalir(self):
        eski = (datetime.now(zamanlayici.TR) - timedelta(days=hafiza.EYLEM_OMRU_GUN + 5)).replace(tzinfo=None)
        asyncio.run(hafiza.eylem_olustur(1, "dosya_oku", {"yol": "C:/yeni.txt"}, "düşük"))
        with mock.patch.object(hafiza, "_simdi", return_value=eski.isoformat(timespec="seconds")):
            asyncio.run(hafiza.eylem_olustur(1, "dosya_oku", {"yol": "C:/eski.txt"}, "düşük"))
        self.assertEqual(asyncio.run(hafiza.eski_eylemleri_sil()), 1)
        kalan = hafiza._calistir("SELECT argumanlar FROM eylemler", sonuc="hepsi")
        self.assertEqual(len(kalan), 1)
        self.assertIn("yeni.txt", kalan[0]["argumanlar"])


if __name__ == "__main__":
    unittest.main()
