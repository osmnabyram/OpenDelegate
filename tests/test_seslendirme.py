"""Sesli cevap: kısa/uzun parçalama, mod, hata toleransı (spam yok), acil zinciri (sahte saat)."""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seslendirme as sl
from zamanlayici import TR


class Saat:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    async def uyu(self, sn):
        pass


class Temel(unittest.IsolatedAsyncioTestCase):
    async def kur(self, bozuk=False):
        self.sesler, self.metinler, self.sira, self.depo = [], [], [], {}
        self.saat = Saat(datetime(2026, 11, 15, 10, 0, tzinfo=TR))
        self.bozuk = bozuk

        async def sentez(metin, ses, hiz):
            if self.bozuk:
                raise OSError("ağ yok")
            return f"MP3[{ses}]{metin}".encode()

        async def gonder_ses(veri, baslik):
            self.sesler.append((veri.decode(), baslik))

        async def gonder_metin(m):
            self.metinler.append(m)

        async def oku(k):
            return self.depo.get(k)

        async def yaz(k, v):
            self.depo[k] = v

        async def sira_ekle(m):
            self.sira.append(m)

        self.s = sl.Ses(gonder_ses=gonder_ses, gonder_metin=gonder_metin, sentez=sentez, oku=oku, yaz=yaz,
                        simdi=self.saat, uyu=self.saat.uyu, sira_ekle=sira_ekle)
        await self.s.yukle()


class Parcalama(unittest.TestCase):
    def test_kisa_tek_parca(self):
        self.assertEqual(sl.parcala("Merhaba efendim. Nasılsın?"), ["Merhaba efendim. Nasılsın?"])

    def test_uzun_cumle_sinirindan(self):
        metin = " ".join(f"Bu {i}. cümle biraz uzunca bir cümledir." for i in range(60))
        p = sl.parcala(metin)
        self.assertGreater(len(p), 1)
        self.assertTrue(all(len(x) <= sl.PARCA_SINIR for x in p))
        self.assertTrue(all(x.endswith(".") for x in p))  # cümle ortasından kesilmedi
        self.assertEqual(" ".join(p), metin)

    def test_bosluksuz_dev_cumle(self):
        p = sl.parcala("a" * 2000)
        self.assertTrue(all(len(x) <= sl.PARCA_SINIR for x in p))

    def test_temizle(self):
        t = sl.temizle("**Kalın** bak: https://x.com/a 👍\n```py\nprint(1)\n```\n- madde")
        self.assertNotIn("https", t)
        self.assertNotIn("print", t)
        self.assertNotIn("*", t)
        self.assertNotIn("👍", t)
        self.assertIn("bağlantı", t)
        self.assertIn("madde", t)


class SesliCevap(Temel):
    async def test_kisa(self):
        await self.kur()
        self.assertTrue(await self.s.seslendir("Selam efendim."))
        self.assertEqual(self.sesler, [("MP3[tr-TR-AhmetNeural]Selam efendim.", "")])

    async def test_uzun_arka_arkaya_ve_sinir(self):
        await self.kur()
        metin = " ".join(f"Bu {i}. cümle biraz uzunca bir cümledir." for i in range(200))
        await self.s.seslendir(metin)
        self.assertEqual(len(self.sesler), sl.MAKS_PARCA)
        self.assertEqual(self.sesler[0][1], f"1/{sl.MAKS_PARCA}")
        self.assertIn("Devamını yazılı olarak gönderdim", self.sesler[-1][0])

    async def test_hata_metinle_devam_spam_yok(self):
        await self.kur(bozuk=True)
        self.assertFalse(await self.s.seslendir("Bir."))
        self.assertFalse(await self.s.seslendir("İki."))
        self.assertEqual(self.metinler, ["Seslendiremedim, metin olarak devam ediyorum."])  # tek not
        self.saat.t += timedelta(minutes=31)
        await self.s.seslendir("Üç.")
        self.assertEqual(len(self.metinler), 2)

    async def test_modlar_ve_tercih_kaydi(self):
        await self.kur()
        await self.s.cevap_eslik("Cevap.", sesli_giris=True)
        self.assertEqual(self.sesler, [])  # varsayılan: sadece istenince
        ok, _ = await self.s.ayarla({"eylem": "ayarla", "mod": "sesliye_sesli"})
        self.assertTrue(ok)
        self.assertEqual(self.depo["ses_ayar"]["mod"], "sesliye_sesli")  # kalıcı
        await self.s.cevap_eslik("Yazılı soruya cevap.", sesli_giris=False)
        await self.s.cevap_eslik("Sesli soruya cevap.", sesli_giris=True)
        self.assertEqual(self.sesler, [("MP3[tr-TR-AhmetNeural]Sesli soruya cevap.", "")])
        ok, _ = await self.s.ayarla({"eylem": "ayarla", "mod": "uydurma"})
        self.assertFalse(ok)

    async def test_bu_cevap_sesli_tek_seferlik(self):
        await self.kur()
        ok, _ = await self.s.ayarla({"eylem": "cevabi_sesli"})
        self.assertTrue(ok)
        await self.s.cevap_eslik("Hava güneşli.", sesli_giris=False)
        await self.s.cevap_eslik("Sonraki cevap.", sesli_giris=False)
        self.assertEqual(self.sesler, [("MP3[tr-TR-AhmetNeural]Hava güneşli.", "")])

    async def test_oku_tool(self):
        await self.kur()
        ok, msj = await self.s.ayarla({"eylem": "oku", "metin": "Hava güneşli."})
        self.assertTrue(ok)
        self.assertEqual(len(self.sesler), 1)


class AcilZincir(Temel):
    async def test_tam_zincir_cevapsiz(self):
        await self.kur()
        await self.s.ayarla({"eylem": "acil", "metin": "faturayı öde"})
        self.assertEqual(len(self.sesler), 1)
        self.assertIn("Efendim, acil bir şey var: faturayı öde", self.sesler[0][0])
        self.saat.t += timedelta(minutes=9)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 1)  # 10 dk dolmadı
        self.saat.t += timedelta(minutes=1)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 2)
        self.assertIn("tekrar söylüyorum", self.sesler[1][0])
        self.saat.t += timedelta(minutes=19)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 2)  # 20 dk dolmadı
        self.saat.t += timedelta(minutes=1)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 3)
        self.assertIn("son kez söylüyorum", self.sesler[2][0])
        self.saat.t += timedelta(minutes=1)
        await self.s.tik()
        self.assertEqual(self.sira, ["faturayı öde"])
        self.assertIn("sırasında bekliyor", self.metinler[-1])
        self.assertEqual(self.s.zincirler, [])
        self.saat.t += timedelta(hours=1)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 3)  # bitti, tekrar yok

    async def test_kullanici_yazinca_durur(self):
        await self.kur()
        await self.s.ayarla({"eylem": "acil", "metin": "ilacını al"})
        self.assertTrue(await self.s.kullanici_yazdi())
        self.saat.t += timedelta(hours=1)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 1)
        self.assertFalse(await self.s.kullanici_yazdi())  # aktif zincir yok

    async def test_ses_yoksa_zincir_metinle_surer(self):
        await self.kur(bozuk=True)
        await self.s.ayarla({"eylem": "acil", "metin": "kargo"})
        self.assertEqual(self.metinler, ["Efendim, acil bir şey var: kargo."])  # "seslendiremedim" spamı yok
        self.saat.t += timedelta(minutes=10)
        await self.s.tik()
        self.assertEqual(len(self.metinler), 2)

    async def test_ikinci_adimda_telefon(self):
        await self.kur()
        aranan = []

        async def ara(m):
            aranan.append(m)
            return True

        self.s.ara = ara
        await self.s.ayarla({"eylem": "acil", "metin": "faturayı öde"})
        self.assertEqual(aranan, [])  # ilk adım hep sesli not
        self.saat.t += timedelta(minutes=10)
        await self.s.tik()
        self.assertEqual(aranan, ["faturayı öde"])
        self.assertEqual(len(self.sesler), 1)  # aradı, 2. not gitmedi
        self.saat.t += timedelta(minutes=20)
        await self.s.tik()
        self.assertIn("son kez söylüyorum", self.sesler[-1][0])  # açmadıysa zincir sürer

    async def test_aranamazsa_sesli_not(self):
        await self.kur()

        async def ara(m):
            return False  # gece / sınır / Twilio yok

        self.s.ara = ara
        await self.s.ayarla({"eylem": "acil", "metin": "kargo"})
        self.saat.t += timedelta(minutes=10)
        await self.s.tik()
        self.assertIn("tekrar söylüyorum", self.sesler[1][0])

    async def test_yeniden_baslama_kaldigi_yerden(self):
        await self.kur()
        await self.s.ayarla({"eylem": "acil", "metin": "randevu"})
        depo = self.depo
        await self.kur()
        self.depo = depo
        await self.s.yukle()  # Render yeniden başladı
        self.assertEqual(self.s.zincirler[0]["adim"], 1)
        await self.s.tik()
        self.assertEqual(self.sesler, [])  # ilk not tekrar gitmez
        self.saat.t += timedelta(minutes=10)
        await self.s.tik()
        self.assertEqual(len(self.sesler), 1)


if __name__ == "__main__":
    unittest.main()


class TurkceOkunus(unittest.TestCase):
    def test_yabanci_terimler_turkce_yazilir_ekler_korunur(self):
        self.assertEqual(sl.turkce_okunus("Numarayı Claude'a söyle, deploy bitti, GitHub'a pushladım."),
                         "Numarayı Klod'a söyle, diploy bitti, Githab'a puşladım.")
        self.assertEqual(sl.turkce_okunus("Bugün hava güzel."), "Bugün hava güzel.")  # Türkçe metne dokunmaz
