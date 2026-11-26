"""disiplin.py testleri: OpenDelegate işi bitirene kadar çalışsın, sadece gerçek kısırdöngüde dursun.

Çalıştır: python -m unittest tests.test_disiplin
"""

import json
import types
import unittest

import config
import disiplin


def cagri(ad, **arg):
    return types.SimpleNamespace(function=types.SimpleNamespace(name=ad, arguments=json.dumps(arg)))


DERLEME_HATASI = "[çıkış kodu: 1]\nTraceback ... NameError: name 'x' is not defined"
CALISTI = "[çıkış kodu: 0]\nÇıktı: 42"


def calistir(t, c, sonuc):
    """ajan_turu'nun yaptığı gibi: önce engel kontrolü, engel yoksa çalıştır + kaydet."""
    engel = t.engelle(c)
    if engel:
        return engel
    t.kaydet(c, sonuc)
    return sonuc


class OdevSenaryosu(unittest.TestCase):
    def test_hata_duzelt_tekrar_calistir_durmaz(self):
        """Kullanıcının ödevi: yaz, çalıştır, hata, düzelt, aynı komutu tekrar çalıştır... birçok tur."""
        t = disiplin.Takip()
        calistir_komut = cagri("terminal_calistir", komut="python odev.py")
        for i in range(6):  # 6 kez üst üste derleme/çalışma hatası: normal iterasyon
            self.assertEqual(calistir(t, calistir_komut, DERLEME_HATASI), DERLEME_HATASI)  # engellenmedi, çalıştı
            calistir(t, cagri("dosya_yaz", yol="C:/odev/odev.py", icerik=f"surum {i}"), "Yazıldı.")
            self.assertEqual(t.durmali(), "", f"{i}. düzeltmede durmamalıydı")
        self.assertEqual(calistir(t, calistir_komut, CALISTI), CALISTI)
        self.assertEqual(t.durmali(), "")

    def test_farkli_komutlarla_hata_durmaz(self):
        t = disiplin.Takip()
        for i in range(10):
            calistir(t, cagri("terminal_calistir", komut=f"pip install paket{i}"), DERLEME_HATASI)
        self.assertEqual(t.durmali(), "")


class Kisirdongu(unittest.TestCase):
    def test_degisiklik_yapmadan_ayni_hatayi_tekrarlamak_engellenir(self):
        t = disiplin.Takip()
        c = cagri("terminal_calistir", komut="python odev.py")
        calistir(t, c, DERLEME_HATASI)
        engel = calistir(t, c, DERLEME_HATASI)  # arada hiçbir şey değişmedi
        self.assertIn("aynen tekrar ÇALIŞTIRILMADI", engel)
        self.assertIn("webde_ara", engel)  # soru değil: düzelt / araştır
        self.assertEqual(t.durmali(), "")  # tek engel durak değil
        calistir(t, c, DERLEME_HATASI)
        calistir(t, c, DERLEME_HATASI)
        self.assertIn("tekrar tekrar", t.durmali())  # 3. engel: gerçek kısırdöngü

    def test_okuma_basarili_olsa_da_engel_kalkmaz(self):
        t = disiplin.Takip()
        c = cagri("terminal_calistir", komut="python odev.py")
        calistir(t, c, DERLEME_HATASI)
        calistir(t, cagri("dosya_oku", yol="C:/odev/odev.py"), "print(x)")  # okumak durumu değiştirmez
        self.assertIsNotNone(t.engelle(c))

    def test_alti_bos_arama_durur(self):
        t = disiplin.Takip()
        for i in range(5):
            calistir(t, cagri("webde_ara", sorgu=f"sorgu {i}"), "[Web araması: x]\nSonuç bulunamadı.")
        self.assertEqual(t.durmali(), "")
        calistir(t, cagri("webde_ara", sorgu="sorgu 6"), "[Web araması: x]\nSonuç bulunamadı.")
        self.assertIn("6 arama", t.durmali())

    def test_basarili_arama_sayaci_sifirlar(self):
        t = disiplin.Takip()
        for i in range(5):
            calistir(t, cagri("webde_ara", sorgu=f"a{i}"), "Sonuç bulunamadı.")
        calistir(t, cagri("webde_ara", sorgu="iyi"), "1. Başlık\n   https://x")
        for i in range(5):
            calistir(t, cagri("webde_ara", sorgu=f"b{i}"), "Sonuç bulunamadı.")
        self.assertEqual(t.durmali(), "")


class Talimatlar(unittest.TestCase):
    def test_soru_sormama_ve_otonomi(self):
        k = disiplin.KURAL
        self.assertIn("ASLA sorma", k)
        self.assertIn("webde_ara", k)
        self.assertNotIn("araştırma turizmine", k)
        self.assertIn("SORU SORMA", disiplin.DURAK_TALIMATI)

    def test_sistem_promptu(self):
        import main
        p = main.SYSTEM_PROMPT
        self.assertIn("EN ÖNEMLİ KURAL — otonom çalış", p)
        self.assertIn("SADECE kullanıcının EN SON mesajındaki işe odaklan", p)
        self.assertNotIn("Nasıl ilerleyelim?\"", p.replace("\"Nasıl ilerleyelim?\", \"Şunu", ""))

    def test_limitler(self):
        self.assertGreaterEqual(config.MAKS_ADIM, 40)
        self.assertGreaterEqual(config.MAKS_ISCI_ADIM, 20)


if __name__ == "__main__":
    unittest.main()
