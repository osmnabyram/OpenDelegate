"""Android uygulamasının sesli cevabı telefon beynini kullanıyor mu.

Kullanıcı 21.11: uygulama "saat kaç" sorusuna "telefonuna bak" diyordu — çünkü
/dinle hafızasız, araçsız, kimliksiz boş bir model çağrısıydı. Artık
arama.Arama.uygulama_cevabi üzerinden telefonla aynı beyin çalışıyor.
"""

import unittest
from datetime import datetime
from types import SimpleNamespace

import arama


class SahteMesaj(SimpleNamespace):
    pass


class UygulamaCevabi(unittest.IsolatedAsyncioTestCase):

    def _arama(self, cevap="Saat 15:30 efendim.", arac_cagir=False):
        self.gorulen = {}

        async def dusun(mesajlar, semalar):
            self.gorulen["mesajlar"] = mesajlar
            self.gorulen["arac_adlari"] = [s["function"]["name"] for s in semalar]
            return SahteMesaj(content=cevap, tool_calls=None)

        async def sistem():
            return "HAFIZA: Kullanıcı tenise Salı ve Perşembe gidiyor."

        return arama.Arama(
            hat=SimpleNamespace(), taban_url="https://vekil.test", token="tok", auth_token="gizli",
            kullanici="+905550000000", dusun=dusun, sistem=sistem, araclar={},
            semalar=[{"type": "function", "function": {"name": "hava_durumu"}}],
            sentez=None, gonder_metin=None,
            simdi=lambda: datetime(2026, 11, 21, 15, 30),
        )

    async def test_sistem_prompt_hafiza_ve_saat_iceriyor(self):
        a = self._arama()
        cevap = await a.uygulama_cevabi("saat kaç")

        self.assertEqual(cevap, "Saat 15:30 efendim.")
        sistem = self.gorulen["mesajlar"][0]["content"]
        self.assertIn("Sen Vekil'sin", sistem)
        self.assertIn("2026-11-21 15:30", sistem)
        self.assertIn("tenise Salı", sistem)
        self.assertIn("telefon görüşmesi değil", sistem)
        self.assertIn("hava_durumu", self.gorulen["arac_adlari"])

    async def test_gecmis_modele_gidiyor(self):
        a = self._arama()
        gecmis = [{"role": "user", "content": "hava nasıl"},
                  {"role": "assistant", "content": "Yağmurlu efendim."}]
        await a.uygulama_cevabi("peki yarın", gecmis)

        # _dusun kendi cevabını da aynı listeye ekliyor; modele giden ilk dördü önemli.
        roller = [m["role"] for m in self.gorulen["mesajlar"]][:4]
        self.assertEqual(roller, ["system", "user", "assistant", "user"])
        self.assertEqual(self.gorulen["mesajlar"][3]["content"], "peki yarın")

    async def test_hafiza_patlarsa_yine_cevap_verir(self):
        a = self._arama()

        async def patla():
            raise RuntimeError("DB kapalı")

        a.sistem = patla
        self.assertEqual(await a.uygulama_cevabi("saat kaç"), "Saat 15:30 efendim.")


class TelefonEylemi(unittest.IsolatedAsyncioTestCase):
    """Kullanıcı 21.11: 'şu saate alarm kur' dediğinde telefonda kurulsun (uygulama X-Eylem ile yapar)."""

    def test_alarm_saat_cozulur(self):
        eylem, _ = arama.telefon_eylemi({"eylem": "alarm", "saat": "7.05", "etiket": " tenis "})
        self.assertEqual(eylem, {"eylem": "alarm", "saat": 7, "dakika": 5, "etiket": "tenis"})
        self.assertIsNone(arama.telefon_eylemi({"eylem": "alarm", "saat": "25:00"})[0])
        self.assertIsNone(arama.telefon_eylemi({"eylem": "alarm", "saat": "yedi"})[0])

    def test_zamanlayici_fener_uygulama(self):
        self.assertEqual(arama.telefon_eylemi({"eylem": "zamanlayici", "sure_sn": 300})[0]["sure_sn"], 300)
        self.assertIsNone(arama.telefon_eylemi({"eylem": "zamanlayici", "sure_sn": 0})[0])
        self.assertFalse(arama.telefon_eylemi({"eylem": "fener", "acik": False})[0]["acik"])
        self.assertIsNone(arama.telefon_eylemi({"eylem": "uygulama_ac", "uygulama": "  "})[0])
        self.assertIsNone(arama.telefon_eylemi({"eylem": "format_at"})[0])

    def test_arama_medya_ses(self):
        self.assertEqual(arama.telefon_eylemi({"eylem": "ara", "kisi": " Annem "})[0], {"eylem": "ara", "kisi": "Annem"})
        self.assertIsNone(arama.telefon_eylemi({"eylem": "ara", "kisi": ""})[0])
        self.assertEqual(arama.telefon_eylemi({"eylem": "medya", "komut": "duraklat"})[0]["komut"], "duraklat")
        self.assertIsNone(arama.telefon_eylemi({"eylem": "medya", "komut": "sil"})[0])
        self.assertEqual(arama.telefon_eylemi({"eylem": "ses", "yon": "kis"})[0]["yon"], "kis")
        self.assertIsNone(arama.telefon_eylemi({"eylem": "ses", "yon": "patlat"})[0])

    def _arama(self):
        self.semalar_gorulen = []
        cevaplar = [
            SahteMesaj(content="", tool_calls=[SimpleNamespace(id="c1", function=SimpleNamespace(
                name="telefonda_yap", arguments='{"eylem": "alarm", "saat": "07:30"}'))]),
            SahteMesaj(content="Alarmı 07:30'a kurdum efendim.", tool_calls=None),
        ]

        async def dusun(mesajlar, semalar):
            self.semalar_gorulen.append([s["function"]["name"] for s in semalar])
            return cevaplar.pop(0)

        async def sistem():
            return ""

        return arama.Arama(
            hat=SimpleNamespace(), taban_url="https://vekil.test", token="tok", auth_token="gizli",
            kullanici="+905550000000", dusun=dusun, sistem=sistem, araclar={}, semalar=[],
            sentez=None, gonder_metin=None, simdi=lambda: datetime(2026, 11, 21, 15, 30))

    async def test_uygulama_eylemi_listeye_ekler(self):
        a = self._arama()
        eylemler = []
        cevap = await a.uygulama_cevabi("yarın 7 buçuğa alarm kur", [], eylemler)
        self.assertEqual(cevap, "Alarmı 07:30'a kurdum efendim.")
        self.assertEqual(eylemler, [{"eylem": "alarm", "saat": 7, "dakika": 30, "etiket": ""}])
        self.assertIn("telefonda_yap", self.semalar_gorulen[0])

    async def test_eylem_listesi_yoksa_arac_sunulmaz(self):
        a = self._arama()
        a.dusun = lambda m, semalar: self._yakala(semalar)
        await a.uygulama_cevabi("saat kaç")
        self.assertNotIn("telefonda_yap", self.semalar_gorulen[-1])

    async def test_uygulama_semasi_ayni_adli_semanin_yerine_gecer(self):
        a = self._arama()
        a.semalar = [{"type": "function", "function": {"name": "isi_yap", "description": "HER iş"}}]
        a.uygulama_semalari = [{"type": "function", "function": {"name": "isi_yap", "description": "SADECE PC"}},
                               {"type": "function", "function": {"name": "webde_ara", "description": "ara"}}]
        gorulen = []

        async def dusun(m, semalar):
            gorulen.extend(semalar)
            return SahteMesaj(content="Tamam efendim.", tool_calls=None)
        a.dusun = dusun
        await a.uygulama_cevabi("bugün özel bir gün mü")
        aciklamalar = [s["function"].get("description") for s in gorulen if s["function"]["name"] == "isi_yap"]
        self.assertEqual(aciklamalar, ["SADECE PC"])
        self.assertIn("webde_ara", [s["function"]["name"] for s in gorulen])

    async def _yakala(self, semalar):
        self.semalar_gorulen.append([s["function"]["name"] for s in semalar])
        return SahteMesaj(content="Saat 15:30 efendim.", tool_calls=None)


class WhisperUydurmasi(unittest.TestCase):
    def test_sessizlik_uydurmasi_soru_sayilmaz(self):
        import sesli
        self.assertTrue(sesli._uydurma_mi("Altyazı M.K."))
        self.assertTrue(sesli._uydurma_mi(sesli._IPUCU))  # ipucunu aynen geri okudu
        self.assertFalse(sesli._uydurma_mi("Feneri aç."))  # gerçek istek
        self.assertNotIn("?", sesli._IPUCU)  # ipucu iş isteyen bir cümle olmasın
        self.assertFalse(sesli._uydurma_mi("Yarın hava nasıl olacak?"))
        self.assertFalse(sesli._uydurma_mi("Teşekkürler."))  # cevaptan sonra gerçekten denebilir


if __name__ == "__main__":
    unittest.main()
