"""Uyanma kelimesi ayıklama.

Android uygulaması "vekil" kelimesini de gönderiyor (cümlenin devamı
kaybolmasın diye tek parça ses yollanıyor), modele gitmeden ayıklanmalı.
"""

import unittest

import sesli


class UyanmaAyikla(unittest.TestCase):

    def test_bastaki_vekil_atilir(self):
        for ham, beklenen in [
            ("vekil bir bakar mısın", ""),
            ("Vekil, hava nasıl?", "hava nasıl?"),
            ("  vekil.  saat kaç", "saat kaç"),
            ("Vekil." , ""),
        ]:
            self.assertEqual(sesli._UYANMA.sub("", ham).strip(), beklenen, ham)

    def test_kayda_giren_uyanma_parcasi_atilir(self):
        # Kayıt uyanma anında başlıyor (21.11): sesin başında cümlenin kuyruğu kalabiliyor.
        for ham, beklenen in [
            ("Mısın? Bugün hava nasıl?", "Bugün hava nasıl?"),
            ("bakar mısın, saat kaç", "saat kaç"),
            ("Vekil bir bakar mısın? Feneri aç.", "Feneri aç."),
            ("Bir alarm kur yediye", "Bir alarm kur yediye"),  # gerçek cümle başı korunur
            ("Misina al", "Misina al"),
            ("Mısır'ın başkenti ne?", "Mısır'ın başkenti ne?"),
        ]:
            self.assertEqual(sesli._UYANMA.sub("", ham).strip(), beklenen, ham)

    def test_ortadaki_vekil_korunur(self):
        ham = "bana vekil ne demek anlat"
        self.assertEqual(sesli._UYANMA.sub("", ham).strip(), ham)


if __name__ == "__main__":
    unittest.main()
