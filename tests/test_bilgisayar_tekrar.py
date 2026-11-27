import unittest

import bilgisayar as b


class TekrarFreni(unittest.TestCase):
    def test_yaz_enter_grubu_imza_verir(self):
        g = [{"tur": "tikla", "x": 500, "y": 900, "tus": "sol", "cift": False},
             {"tur": "yaz", "metin": "merhaba"}, {"tur": "tus", "tuslar": "enter"}]
        self.assertIsNotNone(b._grup_imzasi(g))
        self.assertEqual(b._grup_imzasi(g), b._grup_imzasi([dict(e) for e in g]))

    def test_sadece_tus_grubu_muaf(self):
        self.assertIsNone(b._grup_imzasi([{"tur": "tus", "tuslar": "tab"}]))

    def test_yazilan_metinler_kisa_ve_sifre_haric(self):
        toplu = [{"tur": "yaz", "metin": "merhaba dünya"}, {"tur": "yaz", "metin": "7"},
                 {"tur": "yaz", "metin": "gizli123", "sifre": True}]
        self.assertEqual(b._yazilan_metinler(toplu), {"merhaba dünya"})


if __name__ == "__main__":
    unittest.main()
