"""Yanıtlanan mesajı sesli okuma: bağlam modele gider (kalıp yok); uzun -> özet sorusu; metin değil -> ret."""

import os
import sys
import unittest
from types import SimpleNamespace as N

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


def mesaj(yanit=None):
    return N(reply_to_message=yanit)


def eski(text=None, caption=None, bot=True, **kw):
    alanlar = dict(voice=None, photo=None, video=None, video_note=None, document=None, sticker=None)
    alanlar.update(kw)
    return N(text=text, caption=caption, from_user=N(is_bot=bot), **alanlar)


class YanitBaglami(unittest.TestCase):
    def test_yanit_yoksa_bos(self):
        self.assertEqual(main._yanit_baglami(mesaj()), "")

    def test_vekil_raporu(self):
        b = main._yanit_baglami(mesaj(eski("Ödev dosyasını yazdım, testler geçti.")))
        self.assertIn("OpenDelegate'in mesajı", b)
        self.assertIn("Ödev dosyasını yazdım", b)
        self.assertIn("ses(eylem=oku", b)
        self.assertNotIn("özetleyip", b)

    def test_kendi_mesaji_ve_baslik(self):
        b = main._yanit_baglami(mesaj(eski(caption="Bu fotoğrafın altındaki not", bot=False, photo=[1])))
        self.assertIn("Kullanıcının kendi mesajı", b)
        self.assertIn("altındaki not", b)

    def test_uzun_mesaj_ozet_sorusu(self):
        b = main._yanit_baglami(mesaj(eski("Uzun rapor. " * 500)))
        self.assertIn("özetleyip okuyayım mı?", b)

    def test_metin_olmayan_kibar_ret(self):
        for kw, ad in (({"voice": 1}, "sesli mesaj"), ({"photo": [1]}, "fotoğraf"), ({"sticker": 1}, "çıkartma")):
            b = main._yanit_baglami(mesaj(eski(**kw)))
            self.assertIn(ad, b)
            self.assertIn("okunacak metin yok", b)

    def test_sistem_promptu_niyetten_anlar(self):
        self.assertIn("anahtar kelime bekleme", main.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
