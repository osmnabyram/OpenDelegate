"""komut_calistir: Vekil Telegram komutlarını niyetten kendisi çalıştırır; tehlikeliler (cls/sifirla/dur) yok."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class KomutCalistir(unittest.IsolatedAsyncioTestCase):
    async def test_komut_kullanici_yazmis_gibi_calisir(self):
        bot = mock.Mock(send_message=mock.AsyncMock())
        async def sahte_durum(update, context):
            await update.message.reply_text("Durum tamam")

        with mock.patch.object(main, "_komut_haritasi", return_value={"durum": sahte_durum}):
            ok, sonuc = await main._komut_calistir(bot, main.config.TELEGRAM_CHAT_ID, "durum")
        self.assertTrue(ok)
        self.assertEqual(bot.send_message.await_args.args[1], "Durum tamam")  # çıktı doğrudan sohbete
        self.assertIn("tekrar yazma", sonuc)
        self.assertIn("Durum tamam", sonuc)  # ve Vekil de okuyabiliyor

    async def test_tehlikeli_komutlar_yok(self):
        bot = mock.Mock(send_message=mock.AsyncMock())
        for k in ("cls", "sifirla", "dur", "unut", "pist"):
            ok, _ = await main._komut_calistir(bot, main.config.TELEGRAM_CHAT_ID, k)
            self.assertFalse(ok)
        bot.send_message.assert_not_awaited()

    def test_grind_butonu_var(self):
        veriler = [b.callback_data for satir in main.KOMUT_BUTONLARI.inline_keyboard for b in satir]
        self.assertIn("komut:grind", veriler)
        self.assertIn("grind", main._komut_haritasi())


if __name__ == "__main__":
    unittest.main()
