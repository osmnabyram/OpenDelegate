"""Uzaktan PC açma (priz kullanıcı tarafından Tapo app'ten manuel açılır) ve ajanın
uyanık tutma / uykudan dönüş mantığı. OpenDelegate prize hiç dokunmaz, sadece ajanı bekler.

Çalıştır: python -m unittest tests.test_uyandirma
"""

import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gorevler  # noqa: E402
import uyandirma  # noqa: E402


class _Taban(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        gorevler._son_nabiz = None
        uyandirma._kilit = asyncio.Lock()  # her test kendi olay döngüsünde
        self.bildirimler: list[str] = []
        yamalar = [
            mock.patch.object(uyandirma, "BAGLANMA_SN", 0.05),
            mock.patch.object(uyandirma, "_KONTROL_SN", 0.01),
        ]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)

    def tearDown(self):
        gorevler._son_nabiz = None

    async def bildir(self, metin: str) -> None:
        self.bildirimler.append(metin)


class Uyandirma(_Taban):
    async def test_pc_zaten_acikken_hicbir_sey_yapilmaz(self):
        gorevler.nabiz()
        acildi, metin = await uyandirma.pc_uyandir(self.bildir)
        self.assertTrue(acildi)
        self.assertEqual(self.bildirimler, [])

    async def test_ajan_zamaninda_baglanirsa_acilir(self):
        async def gec_baglan():
            await asyncio.sleep(0.02)
            gorevler.nabiz()

        asyncio.ensure_future(gec_baglan())
        acildi, metin = await uyandirma.pc_uyandir(self.bildir)
        self.assertTrue(acildi)
        self.assertIn("AÇILDI", metin)
        self.assertEqual(len(self.bildirimler), 1)
        self.assertIn("Tapo", self.bildirimler[0])

    async def test_ajan_hic_baglanmazsa_durust_hata(self):
        acildi, metin = await uyandirma.pc_uyandir(self.bildir)
        self.assertFalse(acildi)
        self.assertIn("AÇILMADI", metin)
        self.assertIn("elle açması", metin)
        self.assertEqual(len(self.bildirimler), uyandirma.DENEME)  # ilk bilgi + her deneme uyarısı

    async def test_ayni_anda_iki_istek_tek_bekleme_yapar(self):
        async def gec_baglan():
            await asyncio.sleep(0.02)
            gorevler.nabiz()

        asyncio.ensure_future(gec_baglan())
        sonuclar = await asyncio.gather(uyandirma.pc_uyandir(self.bildir), uyandirma.pc_uyandir(self.bildir))
        self.assertTrue(all(a for a, _ in sonuclar))

    async def test_gerekirse_uyandir_acilinca_true(self):
        async def gec_baglan():
            await asyncio.sleep(0.02)
            gorevler.nabiz()

        asyncio.ensure_future(gec_baglan())
        self.assertTrue(await uyandirma.gerekirse_uyandir(self.bildir))

    async def test_dur_denirse_bekleme_iptal_olur(self):
        with mock.patch.object(uyandirma, "BAGLANMA_SN", 5.0):
            gorev = asyncio.ensure_future(uyandirma.pc_uyandir(self.bildir))
            await asyncio.sleep(0.02)
            gorev.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await gorev


class AnaAkis(_Taban):
    """main.tool_cagrisini_isle: PC işi gelince önce uyandırma denenir (ajan bekler)."""

    def _cagri(self, ad: str, arg: dict) -> SimpleNamespace:
        return SimpleNamespace(id="c1", function=SimpleNamespace(name=ad, arguments=json.dumps(arg)))

    async def _isle(self, ad: str, arg: dict) -> str:
        import main
        bot = mock.Mock()
        bot.send_message = mock.AsyncMock()
        with mock.patch.object(main.hafiza, "eylem_olustur", mock.AsyncMock(return_value=1)), \
                mock.patch.object(main.hafiza, "eylem_guncelle", mock.AsyncMock()):
            return await main.tool_cagrisini_isle(bot, 1, self._cagri(ad, arg))

    async def test_pc_kapaliyken_once_uyandirma_denenir(self):
        import main
        uyan = mock.AsyncMock(return_value=False)
        with mock.patch.object(main.uyandirma, "gerekirse_uyandir", uyan):
            sonuc = await self._isle("dosya_oku", {"yol": "Masaüstü/not.txt"})
        uyan.assert_awaited_once()
        self.assertEqual(sonuc, gorevler.AJAN_CEVRIMDISI)  # açılamadı: eskisi gibi dürüst "PC kapalı"

    async def test_pc_acikken_uyandirma_cagrilmaz(self):
        import main
        gorevler.nabiz()
        uyan = mock.AsyncMock(return_value=True)
        with mock.patch.object(main.uyandirma, "gerekirse_uyandir", uyan), \
                mock.patch.object(main.gorevler, "calistir", mock.AsyncMock(return_value=(True, "içerik"))):
            sonuc = await self._isle("dosya_oku", {"yol": "Masaüstü/not.txt"})
        uyan.assert_not_awaited()
        self.assertIn("içerik", sonuc)

    async def test_pc_guc_tool_ac_ve_durum(self):
        async def gec_baglan():
            await asyncio.sleep(0.02)
            gorevler.nabiz()

        asyncio.ensure_future(gec_baglan())
        sonuc = await self._isle("pc_guc", {"eylem": "ac"})
        self.assertIn("AÇILDI", sonuc)
        durum = await self._isle("pc_guc", {"eylem": "durum"})
        self.assertIn("açık", durum)

    def test_pc_guc_dusuk_riskli_onaysiz(self):
        import tools
        self.assertEqual(tools.risk_degerlendir("pc_guc", {"eylem": "ac"}), "düşük")
        self.assertFalse(tools.onay_gerekir("düşük"))


@unittest.skipUnless(sys.platform == "win32", "ajan Windows'ta çalışır")
class AjanUyanikTut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ajan"))
        import ajan
        cls.ajan = ajan

    def test_uzat_ve_sure_dolunca_birak(self):
        a = self.ajan
        cagrilar: list[int] = []
        u = a.UyanikTut(uygula=cagrilar.append)
        u.uzat(100.0)
        u.uzat(150.0)  # zaten açık: Windows'a tekrar gitmez, sadece süre uzar
        self.assertEqual(len(cagrilar), 1)
        self.assertEqual(cagrilar[0], 0x80000003)  # CONTINUOUS | SYSTEM | DISPLAY
        u.kontrol(150.0 + a.UYANIK_TUT_SN - 1)
        self.assertTrue(u.acik)
        u.kontrol(150.0 + a.UYANIK_TUT_SN)
        self.assertFalse(u.acik)
        self.assertEqual(cagrilar[-1], 0x80000000)  # bırakıldı: Windows'un kendi ayarları
        u.kontrol(10_000.0)
        self.assertEqual(len(cagrilar), 2)  # bırakılmışken tekrar çağrılmaz

    def test_gercek_windows_cagrisi_patlamaz(self):
        a = self.ajan
        a.UyanikTut._windows(0x80000000)  # sadece 'normal'e döndürür: hiçbir şeyi uyanık tutmaz

    def test_uyanis_algilama(self):
        a = self.ajan
        self.assertFalse(a._uyanis_mi(0.0, 90.0, 0.0))  # normal en kötü tur: yoklama + 60 sn bekleme
        self.assertTrue(a._uyanis_mi(0.0, 3600.0, 0.0))  # gece hazırda beklet
        self.assertFalse(a._uyanis_mi(0.0, 900.0, 880.0))  # 15 dk'lık görev uyku sayılmaz

    def test_uyanistan_sonra_hizli_yeniden_baglanma(self):
        a = self.ajan
        self.assertEqual(a._geri_cekil(40.0, hizli=False), 60.0)
        self.assertEqual(a._geri_cekil(5.0, hizli=True), a.HIZLI_BEKLEME)
        self.assertEqual(a._geri_cekil(2.0, hizli=False), 4.0)


if __name__ == "__main__":
    unittest.main()
