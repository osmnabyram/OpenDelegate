"""Ana döngünün model çağrısı (28.11 denetimi): düşünme kapalı (hız), sağlayıcı reddederse eski yol;
sistem mesajındaki saat tur başında sabit (DeepSeek önbelleği her dakika boşa gitmesin)."""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx
from openai import BadRequestError

import main


def _yanit(mesaj):
    return SimpleNamespace(choices=[SimpleNamespace(message=mesaj)])


async def _direkt(_bot, _chat, coro):
    return await coro


class ModelCagrisi(unittest.IsolatedAsyncioTestCase):
    async def test_dusunme_kapali_reddedilirse_varsayilan(self):
        red = BadRequestError("thinking desteklenmiyor", response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions")), body=None)
        create = mock.AsyncMock(side_effect=[red, _yanit(SimpleNamespace(content="Tamam efendim.", tool_calls=None))])
        with mock.patch.object(main.llm.chat.completions, "create", create), \
                mock.patch.object(main, "_yaziyor_iken", _direkt):
            mesaj = await main._model(mock.Mock(), 1, [{"role": "user", "content": "selam"}], [])
        self.assertEqual(mesaj.content, "Tamam efendim.")
        self.assertEqual(create.await_args_list[0].kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertNotIn("extra_body", create.await_args_list[1].kwargs)

    async def test_saat_tur_boyunca_sabit(self):
        cagri = SimpleNamespace(id="c1", function=SimpleNamespace(name="hava_durumu", arguments=json.dumps({})))
        yanitlar = [SimpleNamespace(content="", tool_calls=[cagri]),
                    SimpleNamespace(content="", tool_calls=[SimpleNamespace(id="c2", function=SimpleNamespace(
                        name="hava_durumu", arguments=json.dumps({"yer": "Kadıköy"})))]),
                    SimpleNamespace(content="Bitti efendim.", tool_calls=None)]
        sistemler: list[str] = []

        async def model(_bot, _chat, mesajlar, _semalar):
            sistemler.append(mesajlar[0]["content"])
            return yanitlar[len(sistemler) - 1]

        durum = mock.Mock(side_effect=lambda simdi=None: f"[Anlık durum] {simdi}")
        with mock.patch.object(main, "_model", model), \
                mock.patch.object(main, "_durum_satiri", durum), \
                mock.patch.object(main, "_hafiza_blogu", mock.AsyncMock(return_value="")), \
                mock.patch.object(main, "tool_cagrisini_isle", mock.AsyncMock(return_value="hava: açık")), \
                mock.patch.object(main, "_gonder", mock.AsyncMock()), \
                mock.patch.object(main.hafiza, "mesaj_kaydet", mock.AsyncMock()):
            await main.ajan_turu(mock.Mock(), 1, [{"role": "user", "content": "hava nasıl"}])
        saatler = {c.args[0] for c in durum.call_args_list}
        self.assertEqual(len(saatler), 1)  # üç adımda da aynı (tur başındaki) saat
        self.assertIsNotNone(next(iter(saatler)))
        self.assertEqual(len(set(sistemler)), 1)  # sistem mesajı adımlar arasında birebir aynı


if __name__ == "__main__":
    unittest.main()
