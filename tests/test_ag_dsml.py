"""Güvenlik kapısı (ag.py: iç ağa gitmeme) ve DSML onarımı (dsml.py: düz metne sızan tool çağrısı).

İkisi de 28.11 denetiminde testsiz bulundu: biri bozulursa hiçbir test kırmızı yanmıyordu.
"""

import asyncio
import json
import socket
import unittest
from types import SimpleNamespace
from unittest import mock

import ag
import dsml


def _cozumle(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (ip, 443))]


class IcAgKapisi(unittest.TestCase):
    def test_ic_ve_metadata_adresleri_reddedilir(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.2", "169.254.169.254", "::1", "fd00::1"):
            with mock.patch.object(socket, "getaddrinfo", _cozumle(ip)):
                with self.assertRaises(ag.AgHatasi, msg=ip):
                    asyncio.run(ag.url_guvenli("https://ornek.com/x"))

    def test_genel_adres_ve_sema_kontrolu(self):
        with mock.patch.object(socket, "getaddrinfo", _cozumle("93.184.216.34")):
            asyncio.run(ag.url_guvenli("https://ornek.com/x"))  # hata yok
        for url in ("file:///etc/passwd", "ftp://ornek.com/x", "http:///yok"):
            with self.assertRaises(ag.AgHatasi, msg=url):
                asyncio.run(ag.url_guvenli(url))

    def test_dns_degisse_de_baglanilan_ic_adres_okunmaz(self):
        # DNS rebinding: ön kontrolde genel IP, bağlantıda 127.0.0.1.
        akis = SimpleNamespace(get_extra_info=lambda ad: ("127.0.0.1", 80) if ad == "server_addr" else None)
        with self.assertRaises(ag.AgHatasi):
            ag._baglanilan_genel_mi(SimpleNamespace(extensions={"network_stream": akis}))
        ag._baglanilan_genel_mi(SimpleNamespace(extensions={}))  # adres bilinmiyor: ön kontrol yeter


class DsmlOnarim(unittest.TestCase):
    SIZINTI = ('Bakıyorum efendim.\n<｜DSML｜function_calls>\n<｜DSML｜invoke name="ekran_goruntusu">\n'
               '<｜DSML｜parameter name="ekran" string="true">hepsi</｜DSML｜parameter>\n'
               '<｜DSML｜parameter name="adet" string="false">2</｜DSML｜parameter>\n'
               '</｜DSML｜invoke>\n</｜DSML｜function_calls>')

    def test_sizinti_gercek_cagriya_cevrilir(self):
        mesaj, sizdi = dsml.onar(SimpleNamespace(content=self.SIZINTI, tool_calls=None))
        self.assertTrue(sizdi)
        self.assertEqual(mesaj.content, "Bakıyorum efendim.")  # markup efendime gitmez
        self.assertEqual(len(mesaj.tool_calls), 1)
        self.assertEqual(mesaj.tool_calls[0].function.name, "ekran_goruntusu")
        self.assertEqual(json.loads(mesaj.tool_calls[0].function.arguments), {"ekran": "hepsi", "adet": 2})

    def test_temiz_mesaja_dokunulmaz(self):
        asil = SimpleNamespace(content="Merhaba efendim.", tool_calls=None)
        self.assertEqual(dsml.onar(asil), (asil, False))


if __name__ == "__main__":
    unittest.main()
