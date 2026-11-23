"""/ss: 3 butonlu ekran sorusu (tüm ekran / sol-ana / sağ), seçilen ekranın görüntüsü sohbete düşer."""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


def _sorgu(veri):
    return mock.Mock(data=veri, answer=mock.AsyncMock(), edit_message_text=mock.AsyncMock())


def _guncelleme(sorgu=None, mesaj=None):
    return types.SimpleNamespace(callback_query=sorgu, message=mesaj,
                                 effective_chat=types.SimpleNamespace(id=main.config.TELEGRAM_CHAT_ID))


class SsKomutu(unittest.IsolatedAsyncioTestCase):
    def test_uc_secenek(self):
        satirlar = [[(b.text, b.callback_data) for b in r] for r in main.SS_BUTONLARI.inline_keyboard]
        self.assertEqual(satirlar, [[("Tüm ekran", "ss:hepsi")], [("Ana monitör (sol)", "ss:1")],
                                    [("Sağ monitör", "ss:2")]])
        self.assertIn("ss", main._komut_haritasi())
        self.assertIn("ss", [k.command for k in main.KOMUT_MENUSU])

    async def test_duz_ss_butonlari_sorar_model_yok(self):
        mesaj = mock.Mock(text=" SS ", reply_text=mock.AsyncMock())
        with mock.patch.object(main, "ajan_turu", mock.AsyncMock()) as ajan:
            await main.mesaj_geldi(_guncelleme(mesaj=mesaj), types.SimpleNamespace(bot=None))
        self.assertIs(mesaj.reply_text.await_args.kwargs["reply_markup"], main.SS_BUTONLARI)
        ajan.assert_not_called()

    async def test_sag_monitor_secilince_goruntu_gider(self):
        sorgu = _sorgu("ss:2")
        bot = mock.Mock(send_message=mock.AsyncMock())
        with mock.patch.object(main.gorevler, "calistir_ekli",
                               mock.AsyncMock(return_value=(True, "alındı", b"png"))) as al, \
                mock.patch.object(main, "_ekrani_sohbete_gonder",
                                  mock.AsyncMock(return_value="fotoğraf sohbete gönderildi")) as gonder:
            await main.ss_butonu(_guncelleme(sorgu=sorgu), types.SimpleNamespace(bot=bot))
        al.assert_awaited_once_with("ekran_goruntusu", {"ekran": "2"}, onayli=True)
        self.assertEqual(gonder.await_args.args[2], b"png")
        bot.send_message.assert_not_awaited()

    async def test_pc_kapaliysa_sade_mesaj(self):
        bot = mock.Mock(send_message=mock.AsyncMock())
        with mock.patch.object(main.gorevler, "calistir_ekli",
                               mock.AsyncMock(return_value=(False, main.gorevler.AJAN_CEVRIMDISI, None))):
            await main.ss_butonu(_guncelleme(sorgu=_sorgu("ss:hepsi")), types.SimpleNamespace(bot=bot))
        self.assertIn("PC kapalı", bot.send_message.await_args.args[1])

    async def test_gecersiz_secim_ajan_cagrilmaz(self):
        with mock.patch.object(main.gorevler, "calistir_ekli", mock.AsyncMock()) as al:
            await main.ss_butonu(_guncelleme(sorgu=_sorgu("ss:9")), types.SimpleNamespace(bot=None))
        al.assert_not_called()


if __name__ == "__main__":
    unittest.main()
