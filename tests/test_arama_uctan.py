"""Telefon görüşmesi UÇTAN UCA: sahte Twilio, gerçek HTTP uçları (imza, yönlendirme, ses dosyası indirme).

Twilio'nun yaptığı her isteği sırayla yapar: /basla -> sesi indir -> /cevap -> (bekleme sesi + /bekle)* -> ...
Her <Play> dosyası 200 ve dolu olmalı (boş/404 ses = gerçekte "application error" ile kopma), her webhook hızlı
dönmeli (gerçekte 15 sn sınırı). Sahte model DeepSeek gibi davranır: geçmişte cevapsız tool çağrısı varsa 400 verir.
Gerçek arama yok, para yok.
"""

import asyncio
import json
import re
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import arama

TABAN = "https://vekil.test"
TOKEN = "tok"
GIZLI = "gizli"


class SahteHat:
    async def ara(self, kime, url):
        return "CA1"


class BadRequest(Exception):
    pass


def gecmis_dogrula(mesajlar):
    """DeepSeek/OpenAI kuralı: tool_calls'lı assistant'tan sonra her id için tool mesajı gelmeli."""
    bekleyen = set()
    for m in mesajlar:
        if bekleyen and m["role"] != "tool":
            raise BadRequest("tool_calls cevapsız")
        if m["role"] == "assistant" and m.get("tool_calls"):
            bekleyen = {c["id"] for c in m["tool_calls"]}
        elif m["role"] == "tool":
            bekleyen.discard(m["tool_call_id"])
    if bekleyen:
        raise BadRequest("tool_calls cevapsız (sonda)")


def cagri(ad, arg, i):
    return SimpleNamespace(id=i, function=SimpleNamespace(name=ad, arguments=json.dumps(arg)))


class UctanUca(unittest.TestCase):
    def kur(self, senaryo, sentez_bozuk_metin=None, is_suresi=0.4, takilan_metin=None):
        """senaryo: Kullanıcının her cümlesine modelin vereceği cevap listesi (fonksiyon: mesajlar -> message)."""
        self.telegram = []
        self.isler = []

        async def dusun(mesajlar, semalar):
            gecmis_dogrula(mesajlar)
            await asyncio.sleep(0.05)  # model gecikmesi
            return senaryo.pop(0)(mesajlar)

        async def sentez(m):
            if takilan_metin and takilan_metin in m:
                await asyncio.Event().wait()  # Microsoft'un ucu isteği takılı bıraktı (15.11 canlı olay)
            await asyncio.sleep(0.03)
            if sentez_bozuk_metin and sentez_bozuk_metin in m:
                raise OSError("ses servisi yok")
            return b"MP3:" + m.encode()

        async def isi_yap(arg):
            self.isler.append(arg["is"])
            await asyncio.sleep(is_suresi)  # Telegram tarafında ajan turu
            return True, "İş bitti. Sonuç: Kadıköy akşama kadar 9 derece, rüzgarlı, yağış yok."

        async def gonder(m):
            self.telegram.append(m)

        async def sistem():
            await asyncio.sleep(0.05)  # Neon uyanıyor
            return "[Hafıza] kullanıcı Kadıköy'de oturur."

        depo = {}

        async def oku(k):
            return depo.get(k)

        async def yaz(k, v):
            depo[k] = v

        self.a = arama.Arama(hat=SahteHat(), taban_url=TABAN, token=TOKEN, auth_token=GIZLI, kullanici="+90555",
                             dusun=dusun, sistem=sistem, araclar={"isi_yap": isi_yap},
                             semalar=[{"type": "function", "function": {"name": "isi_yap"}}], sentez=sentez,
                             gonder_metin=gonder, oku=oku, yaz=yaz, izle=False)

        async def ara_ucu(request):
            ok, m = await self.a.ara("istek", "Kanka, OpenDelegate ben. Dinliyorum.", otomatik=False)
            return PlainTextResponse(next(iter(self.a.gorusmeler)) if ok else "HATA " + m)

        self.app = Starlette(routes=[*arama.rotalar(lambda: self.a), Route("/t/ara", ara_ucu, methods=["POST"])])

    # --- sahte Twilio ------------------------------------------------------------------

    def post(self, c, url, form):
        imza = arama.imza(url, form, GIZLI)
        bas = time.time()
        r = c.post(url.replace(TABAN, ""), data=form, headers={"X-Twilio-Signature": imza})
        self.assertLess(time.time() - bas, 2.0, f"webhook yavaş: {url}")  # gerçekte 15 sn sınırı (ölçekli)
        self.assertEqual(r.status_code, 200, f"{url} -> {r.status_code}")
        return r.text

    def cal(self, c, twiml):
        """TwiML'deki sesi Twilio gibi indir: 200 ve dolu olmalı."""
        for url in re.findall(r"<Play>(.*?)</Play>", twiml):
            r = c.get(url.replace(TABAN, ""))
            self.assertEqual(r.status_code, 200, f"ses indirilemedi (gerçekte kopma): {url}")
            self.assertTrue(r.content.startswith(b"MP3:"))
            self.calinan.append(r.content.decode()[4:])
        self.assertNotIn("<Say", twiml)  # Twilio'nun (kadın) sesi asla

    def konus(self, c, gid, soz):
        """Kullanıcı konuşur; Twilio /cevap'a gelir, bekleme seslerini ve /bekle yönlendirmelerini izler."""
        x = self.post(c, f"{TABAN}/arama/{TOKEN}/cevap?g={gid}", {"CallSid": "CA1", "SpeechResult": soz})
        for _ in range(60):
            self.cal(c, x)
            m = re.search(r"<Redirect method=\"POST\">(.*?)</Redirect>", x)
            if not m:
                return x
            x = self.post(c, m.group(1), {"CallSid": "CA1"})
        self.fail("bekleme hiç bitmedi")

    def calistir(self, senaryo, sozler, **kw):
        self.kur(senaryo, **kw)
        self.calinan = []
        sonuclar = []
        with mock.patch.object(arama, "ILK_BEKLEME", 0.1), mock.patch.object(arama, "BEKLEME_ADIMI", 0.15):
            with TestClient(self.app, base_url=TABAN) as c:
                gid = c.post("/t/ara").text
                self.assertNotIn("HATA", gid)
                x = self.post(c, f"{TABAN}/arama/{TOKEN}/basla?g={gid}", {"CallSid": "CA1"})
                self.assertIn('language="tr-TR"', x)
                self.cal(c, x)
                for soz in sozler:
                    sonuclar.append(self.konus(c, gid, soz))
                c.portal.call(self.a.bitti, gid, {"CallStatus": "completed", "CallDuration": "75"})
        return sonuclar

    # --- senaryolar ---------------------------------------------------------------------

    def test_hava_durumu_isi_bekleme_sesiyle_ve_kapanis(self):
        senaryo = [
            lambda m: SimpleNamespace(content="", tool_calls=[cagri("isi_yap", {"is": "Kadıköy hava durumu"}, "c1")]),
            lambda m: SimpleNamespace(content="Akşama kadar 9 derece ve rüzgarlı kanka, kalın giy.", tool_calls=None),
            lambda m: SimpleNamespace(content="Görüşürüz kanka.", tool_calls=[cagri("telefonu_kapat", {}, "c2")]),
        ]
        x = self.calistir(senaryo, ["dışarı çıkacağım kalın mı giyeyim", "tamam kapat"])
        self.assertIn("<Gather", x[0])
        self.assertIn("<Hangup/>", x[1])
        self.assertEqual(self.isler, ["Kadıköy hava durumu"])
        self.assertIn(arama.DOLGU_ILK, self.calinan)  # sessizlik yok: "bir saniye, bakıyorum"
        self.assertIn("Akşama kadar 9 derece ve rüzgarlı kanka, kalın giy.", self.calinan)
        ozet = self.telegram[-1]
        self.assertIn("Sen: dışarı çıkacağım kalın mı giyeyim", ozet)
        self.assertNotIn("Teknik iz", ozet)  # ben kapattım: iz yok

    def test_ben_kapatmadiysam_son_istekler_ozette(self):
        senaryo = [lambda m: SimpleNamespace(content="Bugün hava güzel.", tool_calls=None)]
        self.calistir(senaryo, ["hava nasıl"])  # sonra Twilio "completed" (OpenDelegate kapatmadı)
        ozet = self.telegram[-1]
        self.assertIn("Teknik iz (ben kapatmadım)", ozet)
        self.assertIn("cevap 200", ozet)
        self.assertIn("ses 200", ozet)

    def test_model_hatasi_gecmisi_bozmaz_konusma_surer(self):
        def patla(m):
            raise RuntimeError("model çöktü")

        senaryo = [
            lambda m: SimpleNamespace(content="", tool_calls=[cagri("isi_yap", {"is": "x"}, "c1")]),
            patla,  # tool sonucundan sonra model patlıyor: geçmişte cevapsız tur kalmamalı
            lambda m: SimpleNamespace(content="Buradayım kanka.", tool_calls=None),  # 400 vermemeli
        ]
        x = self.calistir(senaryo, ["bir şey yap", "duydun mu"])
        self.assertIn("ters gitti", " ".join(self.calinan))
        self.assertIn("Buradayım kanka.", self.calinan)
        self.assertIn("<Gather", x[1])

    def test_ses_uretilemezse_kopmaz_yaziya_duser(self):
        senaryo = [lambda m: SimpleNamespace(content="Bozuk cümle burada.", tool_calls=None),
                   lambda m: SimpleNamespace(content="Şimdi düzeldi.", tool_calls=None)]
        self.calistir(senaryo, ["selam", "naber"], sentez_bozuk_metin="Bozuk cümle")
        self.assertIn(arama.SES_TAKILDI, self.calinan)
        self.assertIn("Şimdi düzeldi.", self.calinan)
        self.assertTrue(any("Bozuk cümle burada." in t for t in self.telegram))

    def test_cok_uzun_is_konusmayi_kilitlemez(self):
        senaryo = [
            lambda m: SimpleNamespace(content="", tool_calls=[cagri("isi_yap", {"is": "uzun iş"}, "c1")]),
            lambda m: SimpleNamespace(content="Uzun iş bitti.", tool_calls=None),
            lambda m: SimpleNamespace(content="Tamam kanka.", tool_calls=None),
            lambda m: SimpleNamespace(content="Buradayım.", tool_calls=None),
        ]
        with mock.patch.object(arama, "UZUN_IS", 0.3):
            x = self.calistir(senaryo, ["uzun bir iş yap", "başka bir şey", "naber"], is_suresi=0.8)
        self.assertIn(arama.tek_cumle(arama.DOLGU_UZUN), self.calinan)  # konuşma kilitlenmedi
        self.assertTrue(all("<Gather" in t for t in x))
        self.assertNotIn("ters gitti", " ".join(self.calinan))  # geçmiş hiç bozulmadı (400 yok)
        self.assertIn("Buradayım.", self.calinan)

    def test_takilan_bekleme_sesi_aramayi_koparmaz(self):
        """15.11 canlı olay: 'Hâlâ bakıyorum' sesi üretilemeyip takıldı, Twilio dosyayı bekleyip koptu."""
        senaryo = [
            lambda m: SimpleNamespace(content="", tool_calls=[cagri("isi_yap", {"is": "hava durumu"}, "c1")]),
            lambda m: SimpleNamespace(content="Yarın 9-16 derece, yağış yok kanka.", tool_calls=None),
        ]
        with mock.patch.object(arama, "DOLGU_HAZIR", 0.05), mock.patch.object(arama, "SENTEZ_SURESI", 0.3):
            x = self.calistir(senaryo, ["hava durumunu söyler misin"], is_suresi=0.8, takilan_metin="Hâlâ")
        # cal(): verilen HER ses 200 döndü (takılan ses hiç verilmedi); cevap sonunda söylendi
        self.assertNotIn("Hâlâ bakıyorum efendim, az kaldı.", self.calinan)
        self.assertIn("Yarın 9-16 derece, yağış yok kanka.", self.calinan)
        self.assertIn("<Gather", x[0])

    def test_bos_ses_iki_kez_kibarca_kapanir(self):
        x = self.calistir([], ["", ""])
        self.assertIn("<Gather", x[0])
        self.assertIn("<Hangup/>", x[1])


if __name__ == "__main__":
    unittest.main()
