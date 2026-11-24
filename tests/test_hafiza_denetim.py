"""Hafıza denetimi: 3 bulgu türü, otomatik değişiklik yok, tekrar raporlamama (öğrenme), bulgusuz sessizlik."""

import copy
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hafiza_denetim as hd
from zamanlayici import TR

SIMDI = datetime(2026, 11, 15, 20, 0, tzinfo=TR)
KAYITLAR = [
    {"tur": "not", "anahtar": "tenis_saati", "deger": "Tenis antrenmanı Salı ve Perşembe akşamı 20:00",
     "guncellendi": "2026-11-10"},
    {"tur": "not", "anahtar": "spor_tenis", "deger": "Tenis antrenmanı Salı ve Perşembe 20:00 akşamı",
     "guncellendi": "2026-11-12"},
    {"tur": "not", "anahtar": "ekonomi_6", "deger": "Güncel bakiye 1.000 TL", "guncellendi": "2026-09-01"},
    {"tur": "tercih", "anahtar": "tarayici", "deger": "Brave kullanır", "guncellendi": "2026-11-01"},
    {"tur": "tercih", "anahtar": "tarayici_2", "deger": "Chrome kullanır", "guncellendi": "2026-11-02"},
]


async def sahte_llm(sistem, metin):
    return '[{"a": "tarayici", "b": "tarayici_2", "neden": "biri Brave biri Chrome diyor"}, {"a": "yok", "b": "x"}]'


class Denetim(unittest.IsolatedAsyncioTestCase):
    async def test_uc_bulgu_turu_ve_kayitlara_dokunmaz(self):
        kayitlar = copy.deepcopy(KAYITLAR)
        durum = {}
        metin = await hd.denetle(kayitlar, SIMDI, sahte_llm, durum)
        self.assertIn("5 kayıt · 1 çakışma · 1 eski · 1 çelişki", metin)
        self.assertIn("tenis_saati / spor_tenis", metin)
        self.assertIn("ekonomi_6", metin)
        self.assertIn("tarayici / tarayici_2", metin)
        self.assertNotIn("yok", metin.split("\n", 1)[1].split("(")[0])  # uydurma anahtar elendi
        self.assertIn("Kendim bir şey silmedim", metin)
        self.assertEqual(kayitlar, KAYITLAR)  # otomatik değişiklik YOK

    async def test_ayni_bulgu_tekrar_raporlanmaz_sonra_hatirlatilir(self):
        durum = {}
        await hd.denetle(KAYITLAR, SIMDI, sahte_llm, durum)
        self.assertIsNone(await hd.denetle(KAYITLAR, SIMDI + timedelta(weeks=1), sahte_llm, durum))
        self.assertIsNotNone(await hd.denetle(KAYITLAR, SIMDI + timedelta(weeks=5), sahte_llm, durum))

    async def test_temiz_hafiza_sessiz_ve_llm_hatasi_tolere(self):
        async def bozuk(sistem, metin):
            raise OSError("ağ yok")
        temiz = [KAYITLAR[0], KAYITLAR[3]]
        self.assertIsNone(await hd.denetle(temiz, SIMDI, bozuk, {}))

    async def test_silinen_bulgu_unutulur(self):
        durum = {}
        await hd.denetle(KAYITLAR, SIMDI, None, durum)
        await hd.denetle(KAYITLAR[2:], SIMDI + timedelta(weeks=1), None, durum)  # Kullanıcı tenis kopyasını sildi
        self.assertFalse(any(i.startswith("çakışma") for i in durum["bildirilen"]))


if __name__ == "__main__":
    unittest.main()
