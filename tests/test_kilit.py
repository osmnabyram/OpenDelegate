"""Kill switch: 'kys' kilitler ve kapatır; kilitliyken her şey durur, sadece şifre açar; deneme sınırı.
(Gerçek şifre testte YOK: doğru-şifre yolu sahte özetle denenir.)"""

import hashlib
import os
import sys
import unittest
from types import SimpleNamespace as N
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kilit
import main
from telegram.ext import ApplicationHandlerStop


def sahte_ozet(sifre):
    return hashlib.pbkdf2_hmac("sha256", sifre.encode(), kilit._TUZ, kilit._TUR)


class Temel(unittest.TestCase):
    def setUp(self):
        kilit._yanlis, kilit._bekle_bitis = 0, 0.0

    def test_tetik(self):
        for m in ("kys", " KYS ", "Kys\n"):
            self.assertTrue(kilit.tetik_mi(m))
        for m in ("kys lütfen", "kysa", "", None):
            self.assertFalse(kilit.tetik_mi(m))

    def test_yanlis_sifreler(self):
        for m in ("", "kys", "sifre", None):
            self.assertFalse(kilit.sifre_dogru(m))

    def test_dogru_sifre_yolu(self):
        with mock.patch.object(kilit, "_OZET", sahte_ozet("deneme-123")):
            self.assertEqual(kilit.deneme("  deneme-123 "), "dogru")
            self.assertEqual(kilit.deneme("deneme-12"), "yanlis")

    def test_ters_tirnak_telegram_kod_bicimi(self):
        # Kullanıcı "ab`c£d`e" yazar; Telegram "abc£de" + code(2,3) gönderir
        self.assertIn("ab`c£d`e", kilit.ham_adaylar("abc£de", [("code", 2, 3)]))
        self.assertEqual(kilit.ham_adaylar("düz", []), ["düz"])
        with mock.patch.object(kilit, "_OZET", sahte_ozet("x`y\z`w")):
            self.assertEqual(kilit.deneme(kilit.ham_adaylar("xy\zw", [("code", 1, 3)])), "dogru")

    def test_bes_yanlistan_sonra_bekleme(self):
        for _ in range(kilit.MAKS_DENEME):
            self.assertEqual(kilit.deneme("x", simdi=100.0), "yanlis")
        self.assertEqual(kilit.deneme("x", simdi=101.0), "bekle")
        with mock.patch.object(kilit, "_OZET", sahte_ozet("dogru")):
            self.assertEqual(kilit.deneme("dogru", simdi=200.0), "bekle")  # beklerken doğru şifre bile işlenmez
            self.assertEqual(kilit.deneme("dogru", simdi=100.0 + kilit.BEKLEME_SN + 1), "dogru")


class Kapi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        kilit.kilitli = False
        kilit._yanlis, kilit._bekle_bitis = 0, 0.0
        self.gidenler = []

    def update(self, metin):
        async def reply_text(m):
            self.gidenler.append(m)

        async def send_message(m):
            self.gidenler.append(m)

        async def delete():
            self.gidenler.append("<silindi>")

        mesaj = N(text=metin, reply_text=reply_text, delete=delete, chat=N(send_message=send_message), message_id=500, entities=())
        return N(effective_chat=N(id=main.config.TELEGRAM_CHAT_ID), effective_message=mesaj, callback_query=None)

    async def test_kys_kilitler_ve_kapatir(self):
        async def ayarla(d):
            kilit.kilitli = d
        with mock.patch.object(kilit, "ayarla", ayarla), mock.patch.object(main, "_kendini_kapat") as kapat:
            bot = N(delete_messages=mock.AsyncMock())
            with self.assertRaises(ApplicationHandlerStop):
                await main.kilit_kapisi(self.update("kys"), N(bot=bot))
        self.assertTrue(kilit.kilitli)
        self.assertEqual(bot.delete_messages.await_args_list[0].args[1][0], 500)  # ekran temizlendi (kys dahil)
        kapat.assert_called_once()
        self.assertIn("kendini kapattı", self.gidenler[0])

    async def test_kilitsizken_normal_mesaj_gecer(self):
        await main.kilit_kapisi(self.update("merhaba"), None)  # istisna yok: diğer handler'lara gider
        self.assertEqual(self.gidenler, [])

    async def test_kilitliyken_her_sey_durur_yanlis_sifre(self):
        kilit.kilitli = True
        with self.assertRaises(ApplicationHandlerStop):
            await main.kilit_kapisi(self.update("bugün hava nasıl"), None)
        self.assertEqual(self.gidenler[0], "<silindi>")
        self.assertIn("Şifre yanlış", self.gidenler[1])
        self.assertIn("şifreyi yaz", self.gidenler[1])

    async def test_dogru_sifre_acar(self):
        kilit.kilitli = True

        async def ayarla(d):
            kilit.kilitli = d
        with mock.patch.object(kilit, "_OZET", sahte_ozet("acil-sifre")), mock.patch.object(kilit, "ayarla", ayarla), \
                mock.patch.object(main, "_kendini_kapat") as kapat:
            with self.assertRaises(ApplicationHandlerStop):
                await main.kilit_kapisi(self.update("acil-sifre"), None)
        self.assertFalse(kilit.kilitli)
        self.assertEqual(self.gidenler[0], "<silindi>")  # şifre sohbette kalmaz
        self.assertIn("yeniden açılıyor", self.gidenler[1])
        kapat.assert_called_once()

    async def test_db_okunamazsa_kilitli_acilir(self):
        with mock.patch.object(kilit, "_oku_db", side_effect=OSError("db yok")), \
                mock.patch.object(kilit.asyncio, "sleep", mock.AsyncMock()):
            self.assertTrue(await kilit.yukle())


if __name__ == "__main__":
    unittest.main()
