"""/grind: gün gün gruplu okunur biçim (Türkiye saati), ritüel commit elemesi ve geçmiş yoksa açık hata."""

import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import grind


class Grind(unittest.TestCase):
    def test_bicim_gun_gun_gruplu(self):
        m = grind.bicimle([
            ("2026-11-15T00:45:00Z", "Yeni  özellik\n\nayrıntı"),  # TR'de 03:45, 15 Kasım
            ("2026-11-15T18:00:00+03:00", "İkinci iş"),            # aynı gün
            ("2026-11-14T21:00:00+03:00", "Düzeltme"),             # 14 Kasım
        ])
        satirlar = m.splitlines()
        self.assertEqual(satirlar[0], "Son 3 geliştirme (en yeni üstte):")
        self.assertIn("15 Kasım", m)                 # gün başlığı (tam ay adı)
        self.assertIn("14 Kasım", m)
        self.assertIn("• 03:45  Yeni özellik", m)    # madde işareti + saat + mesaj
        self.assertIn("• 21:00  Düzeltme", m)
        # Aynı güne ait iki iş tek başlık altında (15 Kasım başlığı bir kez)
        self.assertEqual(sum(1 for s in satirlar if s.startswith("15 Kasım")), 1)

    def test_uzun_mesaj_kirpilir(self):
        m = grind.bicimle([("2026-11-15T12:00:00+03:00", "x" * 300)])
        self.assertIn("…", m)
        self.assertTrue(all(len(s) <= 160 for s in m.splitlines()))

    def test_ritul_commit_elenir(self):
        kayitlar = [
            ("2026-11-16T10:00:00+03:00", "Gelişim listesi güncellendi"),
            ("2026-11-16T09:00:00+03:00", "Gerçek bir özellik"),
            ("2026-11-15T10:00:00+03:00", "Gelişim listesi güncellendi"),
            ("2026-11-15T09:00:00+03:00", "Başka gerçek iş"),
        ]
        with mock.patch.object(grind, "_git_log", mock.AsyncMock(return_value=[])), \
                mock.patch.object(grind, "_dosyadan", lambda n: kayitlar):
            m = asyncio.run(grind.metin(5))
        self.assertNotIn("Gelişim listesi güncellendi", m)
        self.assertIn("Gerçek bir özellik", m)
        self.assertIn("Başka gerçek iş", m)
        self.assertTrue(m.startswith("Son 2 geliştirme"))  # 4 kayıttan 2'si gürültü elendi

    def test_kaynak_yoksa_acik_hata(self):
        with mock.patch.object(grind, "_git_log", mock.AsyncMock(return_value=[])), \
                mock.patch.object(grind, "_dosyadan", lambda n: []), mock.patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
            with self.assertRaises(grind.GrindHatasi):
                asyncio.run(grind.metin())

    def test_varsayilan_adet_on(self):
        self.assertEqual(grind.ADET, 10)


if __name__ == "__main__":
    unittest.main()
