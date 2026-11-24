"""guncelleme.py testleri: yeni sürümde bir kez haber, aynı sürümde sessiz."""

import json
import unittest
from pathlib import Path

import guncelleme


class Depo:
    def __init__(self):
        self.veri = {}

    async def oku(self, k):
        return self.veri.get(k)

    async def yaz(self, k, v):
        self.veri[k] = json.loads(json.dumps(v))


NOTLAR = [{"no": 2, "tarih": "2026-11-15", "maddeler": ["Brifinge emoji geldi.", "Pist butonu."]},
          {"no": 1, "tarih": "2026-11-14", "maddeler": ["eski"]}]


class Bildirim(unittest.IsolatedAsyncioTestCase):
    async def _calis(self, depo, commit, notlar=NOTLAR):
        giden = []

        async def gonder(m):
            giden.append(m)

        await guncelleme.bildir(gonder, commit=commit, notlar=notlar, oku=depo.oku, yaz=depo.yaz)
        return giden

    async def test_yeni_surum_bir_kez_yeniden_baslamada_sessiz(self):
        depo = Depo()
        giden = await self._calis(depo, "abc1234def")
        self.assertEqual(len(giden), 1)
        self.assertTrue(giden[0].startswith("Vekil güncellendi (abc1234)."))
        self.assertIn("• Brifinge emoji geldi.", giden[0])
        self.assertIn("Yenilikler:\n• eski\n• Brifinge emoji geldi.\n• Pist butonu.", giden[0])  # ilk bildirim: görülmemiş notların hepsi, eskiden yeniye
        self.assertEqual(await self._calis(depo, "abc1234def"), [])  # aynı sürüm: Render yeniden başladı

    async def test_arada_kacan_notlar_da_gelir(self):
        depo = Depo()
        await self._calis(depo, "aaa1111", notlar=[{"no": 1, "maddeler": ["bir"]}])
        uc_not = [{"no": 4, "maddeler": ["dört"]}, {"no": 3, "maddeler": ["üç"]}, {"no": 2, "maddeler": ["iki"]},
                  {"no": 1, "maddeler": ["bir"]}]
        giden = await self._calis(depo, "ddd4444", notlar=uc_not)  # 2 ve 3 hiç açılmadan 4 geldi
        self.assertEqual(giden[0], "Vekil güncellendi (ddd4444).\nYenilikler:\n• iki\n• üç\n• dört")

    async def test_not_yoksa_kisa_mesaj(self):
        depo = Depo()
        await self._calis(depo, "aaa1111")
        giden = await self._calis(depo, "bbb2222")  # yeni commit ama yeni not yok
        self.assertEqual(giden, ["Vekil güncellendi (bbb2222).\nKüçük düzeltmeler."])

    async def test_commit_bilgisi_yoksa_nota_bakar(self):
        depo = Depo()
        self.assertEqual(len(await self._calis(depo, "")), 1)  # yeni not: haber ver
        self.assertEqual(await self._calis(depo, ""), [])

    def test_gercek_not_dosyasi_gecerli(self):
        notlar = guncelleme.notlari_oku()
        self.assertTrue(notlar, "degisiklikler.json okunamadı")
        self.assertEqual(notlar[0]["no"], max(n["no"] for n in notlar))  # en yeni en üstte
        for n in notlar:
            self.assertNotIn("\U0001F44B", json.dumps(n, ensure_ascii=False))  # el sallama emojisi asla

    def test_bozuk_dosya_bos_liste(self):
        yol = Path(__file__).with_name("_gecici_bozuk.json")
        yol.write_text("{bozuk", encoding="utf-8")
        try:
            self.assertEqual(guncelleme.notlari_oku(yol), [])
        finally:
            yol.unlink()


if __name__ == "__main__":
    unittest.main()
