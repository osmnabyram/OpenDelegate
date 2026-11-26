"""Web sohbeti: TOTP, giriş + oturum + deneme sınırı, CSRF kapısı, HTML süzgeci, WebBot, uçtan uca mesaj akışı."""

import asyncio
import base64
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
import main
import web_sohbet
from web_sohbet import DenemeSiniri, Oturumlar, WebBot, guvenli_html, totp_dogru, totp_uret

PAROLA = "test-web-parolasi-123"
SIR = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 test anahtarı
H = {"X-OD": "1"}


class TotpTesti(unittest.TestCase):
    def test_rfc6238_vektoru(self):
        self.assertEqual(totp_uret(SIR, 59), "287082")  # RFC 6238: T=59 -> 94287082, son 6 hane
        self.assertEqual(totp_uret(SIR, 1111111109), "081804")

    def test_dogru_yanlis_ve_tolerans(self):
        self.assertTrue(totp_dogru(SIR, "287082", 59))
        self.assertTrue(totp_dogru(SIR, "287082", 59 + 30))  # bir adım kayma tamam
        self.assertFalse(totp_dogru(SIR, "287082", 59 + 120))
        self.assertFalse(totp_dogru(SIR, "000000", 59))
        self.assertFalse(totp_dogru(SIR, "", 59))

    def test_bozuk_sir_hic_kabul_etmez(self):
        self.assertFalse(totp_dogru("!!!bozuk!!!", "123456"))


class SinirTesti(unittest.TestCase):
    def test_ip_basina_bes_sonra_kilit_ve_sure_dolunca_acilir(self):
        s = DenemeSiniri(ip_limit=5, genel_limit=30, bekleme=900)
        for _ in range(5):
            self.assertTrue(s.izin_var("1.1.1.1", 0))
            s.basarisiz("1.1.1.1", 0)
        self.assertFalse(s.izin_var("1.1.1.1", 10))
        self.assertTrue(s.izin_var("2.2.2.2", 10))  # başka IP etkilenmez
        self.assertTrue(s.izin_var("1.1.1.1", 901))

    def test_genel_sinir_ip_degistirerek_asilamaz(self):
        s = DenemeSiniri(ip_limit=5, genel_limit=6, bekleme=900)
        for i in range(6):
            s.basarisiz(f"10.0.0.{i}", 0)
        self.assertFalse(s.izin_var("9.9.9.9", 1))

    def test_oturum_suresi(self):
        o = Oturumlar()
        sid = o.ac()
        self.assertTrue(o.gecerli(sid))
        self.assertFalse(o.gecerli("uydurma"))
        self.assertFalse(o.gecerli(None))
        o.kapat(sid)
        self.assertFalse(o.gecerli(sid))
        sid2 = o.ac()
        o._sureler[sid2] = 0
        self.assertFalse(o.gecerli(sid2))


class SuzgecTesti(unittest.TestCase):
    def test_script_ve_olay_ozellikleri_atilir(self):
        c = guvenli_html('<b>merhaba</b><script>alert(1)</script><img src=x onerror=alert(1)>', True)
        self.assertEqual(c, "<b>merhaba</b>alert(1)")
        self.assertNotIn("<script", c)
        self.assertNotIn("onerror", c)

    def test_baglanti_sadece_http_https(self):
        self.assertIn('href="https://ornek.com/a?b=1&amp;c=2"', guvenli_html('<a href="https://ornek.com/a?b=1&c=2">x</a>', True))
        self.assertNotIn("<a", guvenli_html('<a href="javascript:alert(1)">x</a>', True))
        self.assertNotIn("<a", guvenli_html('<a href="data:text/html,x">x</a>', True))

    def test_ozellikli_izinli_etiket_ozelligini_kaybeder(self):
        self.assertEqual(guvenli_html('<b onclick="x()">k</b>', True), "<b>k</b>")

    def test_acik_kalan_etiket_kapanir_ve_sahte_kapanis_yok_sayilir(self):
        self.assertEqual(guvenli_html("<b>kalın", True), "<b>kalın</b>")
        self.assertEqual(guvenli_html("kalın</b></i>", True), "kalın")

    def test_html_degilse_tamami_kacar(self):
        self.assertEqual(guvenli_html("<b>x</b> & y", False), "&lt;b&gt;x&lt;/b&gt; &amp; y")


class WebBotTesti(unittest.IsolatedAsyncioTestCase):
    async def test_mesaj_ve_dugmeler(self):
        b = WebBot()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Onayla", callback_data="onay:abc"),
                                    InlineKeyboardButton("Link", url="https://x.com")]])
        m = await b.send_message(1, "<b>Sor</b>", parse_mode="HTML", reply_markup=kb)
        o = b.olaylar_sonrasi(0)[0]
        self.assertEqual(o["metin"], "<b>Sor</b>")
        self.assertEqual(o["dugmeler"], [[{"yazi": "Onayla", "veri": "onay:abc"}]])  # url'li düğme alınmaz
        self.assertIs(b.dugme_mesaji("onay:abc"), m)
        await m.edit_text(m.text_html + "\nTamam", "HTML")
        d = b.olaylar_sonrasi(o["id"])[0]
        self.assertEqual((d["tur"], d["hedef"], d["dugmeler"]), ("duzenle", m.message_id, []))

    async def test_kullanici_yazisi_kacar(self):
        b = WebBot()
        b.kullanici_yazdi("<img src=x onerror=1>")
        self.assertNotIn("<img", b.olaylar_sonrasi(0)[0]["metin"])

    async def test_medya_ve_mime(self):
        b = WebBot()
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        await b.send_photo(1, png, caption="ekran")
        o = b.olaylar_sonrasi(0)[0]
        self.assertEqual((o["tur"], o["mime"]), ("medya", "image/png"))
        self.assertEqual(b.medya(o["url"].rsplit("/", 1)[1])[0], png)

    async def test_gecmis_yukle_ekran_bossa_ve_kacarak(self):
        b = WebBot()
        b.gecmis_yukle([{"role": "user", "content": "<b>selam</b>"}, {"role": "assistant", "content": "merhaba & hoş geldin"}])
        o = b.olaylar_sonrasi(0)
        self.assertEqual([x["tur"] for x in o], ["kullanici", "mesaj"])
        self.assertEqual(o[0]["metin"], "&lt;b&gt;selam&lt;/b&gt;")
        b.gecmis_yukle([{"role": "user", "content": "tekrar"}])  # ekran doluyken eklenmez
        self.assertEqual(len(b.olaylar), 2)

    async def test_temizle_ve_bilinmeyen_cagrilar(self):
        b = WebBot()
        await b.send_message(1, "x")
        await b.delete_messages(1, [1, 2])
        self.assertEqual([o["tur"] for o in b.olaylar], ["temizle"])
        await b.send_chat_action(1, "typing")
        self.assertTrue(b.yaziyor_mu())
        await b.set_my_commands([])


class UcTanUcaTesti(unittest.TestCase):
    def setUp(self):
        self.yamalar = [mock.patch.object(config, "WEB_PAROLA", PAROLA), mock.patch.object(config, "WEB_TOTP_SIR", "")]
        for y in self.yamalar:
            y.start()
        web_sohbet.oturumlar = Oturumlar()
        web_sohbet.deneme_siniri = DenemeSiniri()
        self.istemci = TestClient(main.web_uygulamasi(None), base_url="https://od.test")

    def tearDown(self):
        for y in self.yamalar:
            y.stop()

    def giris(self, parola=PAROLA, kod=""):
        return self.istemci.post("/sohbet/giris", json={"parola": parola, "kod": kod}, headers=H)

    def test_sayfa_acik_ama_api_kapali(self):
        r = self.istemci.get("/sohbet")
        self.assertEqual(r.status_code, 200)
        self.assertIn("script-src 'self'", r.headers["content-security-policy"])
        self.assertNotIn("<script>", r.text.replace('<script src', ""))  # satır içi betik yok
        self.assertEqual(self.istemci.get("/sohbet/olaylar").status_code, 401)
        self.assertEqual(self.istemci.post("/sohbet/mesaj", json={"metin": "x"}, headers=H).status_code, 403)
        self.assertEqual(self.istemci.get("/sohbet/medya/x").status_code, 404)

    def test_yanlis_parola_ayni_hata_cerez_yok(self):
        r = self.giris("yanlis")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("set-cookie", r.headers)
        self.assertEqual(r.json()["hata"], "Bilgiler yanlış.")

    def test_basarili_giris_cerez_bayraklari(self):
        r = self.giris()
        self.assertEqual(r.status_code, 200)
        c = r.headers["set-cookie"].lower()
        for bayrak in ("httponly", "secure", "samesite=strict"):
            self.assertIn(bayrak, c)
        self.assertEqual(self.istemci.get("/sohbet/ben").json()["giris"], True)

    def test_giris_x_od_basligi_ister(self):
        r = self.istemci.post("/sohbet/giris", json={"parola": PAROLA})
        self.assertEqual(r.status_code, 400)

    def test_bes_yanlis_sonra_dogru_parola_bile_kilitli(self):
        for _ in range(5):
            self.assertEqual(self.giris("yanlis").status_code, 401)
        self.assertEqual(self.giris().status_code, 429)

    def test_totp_acikken_kod_sart(self):
        with mock.patch.object(config, "WEB_TOTP_SIR", SIR):
            self.assertEqual(self.giris(kod="").status_code, 401)
            self.assertEqual(self.giris(kod="000000").status_code, 401)
            with mock.patch("web_sohbet.time.time", return_value=59):
                self.assertEqual(self.giris(kod="287082").status_code, 200)

    def test_csrf_basligi_ve_origin(self):
        self.giris()
        self.assertEqual(self.istemci.post("/sohbet/mesaj", json={"metin": "x"}).status_code, 403)  # X-OD yok
        r = self.istemci.post("/sohbet/mesaj", json={"metin": "x"}, headers={**H, "Origin": "https://kotu.site"})
        self.assertEqual(r.status_code, 403)

    def test_mesaj_akisi_ve_sinirlar(self):
        self.giris()
        gidenler = []

        async def sahte(metin):
            gidenler.append(metin)

        # rotalar kurulurken verilen mesaj_isle gerçek; burada onun yerine modül düzeyinde yamalıyoruz
        with mock.patch.object(main, "web_mesaj_isle", sahte):
            istemci = TestClient(main.web_uygulamasi(None), base_url="https://od.test")
            istemci.cookies.update(self.istemci.cookies)
            self.assertEqual(istemci.post("/sohbet/mesaj", json={"metin": "merhaba"}, headers=H).status_code, 202)
            self.assertEqual(istemci.post("/sohbet/mesaj", json={"metin": "  "}, headers=H).status_code, 400)
            self.assertEqual(istemci.post("/sohbet/mesaj", json={"metin": "a" * 9000}, headers=H).status_code, 400)
            self.assertEqual(istemci.post("/sohbet/mesaj", content=b"{bozuk", headers=H).status_code, 400)
        self.assertEqual(gidenler, ["merhaba"])

    def test_yukleme_yetki_boyut_ve_baslik_temizligi(self):
        gelen = []

        async def sahte(veri, ad, mime, tur, not_):
            gelen.append((veri, ad, mime, tur, not_))

        self.assertEqual(self.istemci.post("/sohbet/yukle", content=b"x", headers=H).status_code, 403)  # girişsiz
        self.giris()
        with mock.patch.object(main, "web_yukle_isle", sahte):
            istemci = TestClient(main.web_uygulamasi(None), base_url="https://od.test")
            istemci.cookies.update(self.istemci.cookies)
            baslik = {**H, "Content-Type": "application/pdf", "X-Dosya-Adi": "..%2F..%2Fgizli%2Frapor.pdf", "X-Not": "%C3%B6zetle"}
            self.assertEqual(istemci.post("/sohbet/yukle", content=b"%PDF-1", headers=baslik).status_code, 202)
            self.assertEqual(istemci.post("/sohbet/yukle", content=b"", headers=H).status_code, 400)
            self.assertEqual(istemci.post("/sohbet/yukle", headers={**H, "Origin": "https://kotu.site"}, content=b"x").status_code, 403)
            buyuk = b"0" * (web_sohbet.MAKS_YUKLE + 1)
            self.assertEqual(istemci.post("/sohbet/yukle", content=buyuk, headers=H).status_code, 413)
            self.assertEqual(istemci.post("/sohbet/yukle", content=b"ses", headers={**H, "X-Tur": "ses", "Content-Type": "audio/webm;codecs=opus"}).status_code, 202)
        self.assertEqual(gelen[0], (b"%PDF-1", "rapor.pdf", "application/pdf", "dosya", "özetle"))
        self.assertEqual(gelen[1][2:4], ("audio/webm", "ses"))
        self.assertEqual(len(gelen), 2)

    def test_sayfa_mikrofon_iznini_sadece_kendine_verir(self):
        self.assertIn("microphone=(self)", self.istemci.get("/sohbet").headers["permissions-policy"])
        self.assertIn("microphone=()", self.istemci.get("/health").headers["permissions-policy"])

    def test_girissiz_hicbir_korumali_rota_calismaz(self):
        """Tüm /sohbet rotaları dolaşılır: herkese açık olması gerekenler dışında girişsiz hiçbiri 200 vermez."""
        acik = {("GET", "/sohbet"), ("GET", "/sohbet/ben"), ("GET", "/sohbet/sw.js"), ("GET", "/sohbet/manifest.webmanifest"),
                ("GET", "/sohbet/dosya/{ad}"), ("POST", "/sohbet/giris")}
        rotalar = [r for r in main.web_uygulamasi(None).routes if r.path.startswith("/sohbet")]
        self.assertGreaterEqual(len(rotalar), 14)
        for r in rotalar:
            for yontem in sorted(m for m in r.methods if m != "HEAD"):
                yol = r.path.replace("{ad}", "sohbet.js").replace("{mid}", "yok")
                yanit = self.istemci.request(yontem, yol, content=b"{}", headers={"Content-Type": "application/json"})
                if (yontem, r.path) in acik:
                    continue
                self.assertIn(yanit.status_code, (401, 403, 404), f"{yontem} {r.path} -> {yanit.status_code}")

    def test_cikis_oturumu_oldurur(self):
        self.giris()
        self.assertEqual(self.istemci.post("/sohbet/cikis", json={}, headers=H).status_code, 200)
        self.assertEqual(self.istemci.get("/sohbet/olaylar").status_code, 401)

    def test_parola_bos_ise_web_sohbeti_hic_yok(self):
        with mock.patch.object(config, "WEB_PAROLA", ""):
            istemci = TestClient(main.web_uygulamasi(None), base_url="https://od.test")
            self.assertEqual(istemci.get("/sohbet").status_code, 404)

    def test_statik_dosya_beyaz_liste(self):
        self.assertEqual(self.istemci.get("/sohbet/dosya/sohbet.js").status_code, 200)
        self.assertEqual(self.istemci.get("/sohbet/dosya/main.py").status_code, 404)
        self.assertEqual(self.istemci.get("/sohbet/dosya/..%2Fconfig.py").status_code, 404)


class HataMetniTesti(unittest.TestCase):
    def test_402_bakiye_bitti_anlasilir_mesaj(self):
        e = Exception("Error code: 402 - Insufficient Balance")
        e.status_code = 402
        m = main._hata_metni(e)
        self.assertIn("bakiyesi bitmiş", m)
        self.assertNotIn("Exception", m)

    def test_diger_hatalar_eskisi_gibi(self):
        self.assertEqual(main._hata_metni(ValueError("x")), "⚠️ efendim, bi hata oldu: ValueError: x")
        e = Exception("y")
        e.status_code = 500
        self.assertIn("bi hata oldu", main._hata_metni(e))

    def test_sistem_istemi_ekran_durustlugu(self):
        self.assertIn("göremedim", main.SYSTEM_PROMPT)


class EntegrasyonTesti(unittest.IsolatedAsyncioTestCase):
    """web_mesaj_isle / web_dugme_isle: komut, düğme ve normal mesaj yolları."""

    def setUp(self):
        self.bot = WebBot()
        self.yama = mock.patch.object(web_sohbet, "web_bot", self.bot)
        self.yama.start()

    def tearDown(self):
        self.yama.stop()

    async def test_normal_mesaj_mesaj_geldi_ye_gider(self):
        cagri = mock.AsyncMock()
        with mock.patch.object(main, "mesaj_geldi", cagri), mock.patch.object(main.kilit, "kilitli", False):
            await main.web_mesaj_isle("selam")
        up = cagri.await_args.args[0]
        self.assertEqual(up.message.text, "selam")
        self.assertTrue(main._yetkili(up))  # web güncellemesi yetkili sohbetten sayılır
        self.assertEqual(cagri.await_args.args[1].bot, self.bot)
        self.assertEqual(self.bot.olaylar_sonrasi(0)[0]["tur"], "kullanici")

    async def test_komut_yonlenir_bilinmeyen_komut_reddedilir(self):
        durum = mock.AsyncMock()
        with mock.patch.dict(main._web_komutlari.__globals__, {"komut_durum": durum}), \
                mock.patch.object(main.kilit, "kilitli", False):
            await main.web_mesaj_isle("/durum")
            await main.web_mesaj_isle("/yokboyle")
        durum.assert_awaited_once()
        self.assertIn("tanımıyorum", self.bot.olaylar_sonrasi(0)[-1]["metin"])

    async def test_kilitliyken_sifre_sohbette_gosterilmez(self):
        with mock.patch.object(main.kilit, "kilitli", True), mock.patch.object(main.kilit, "deneme", return_value="yanlis"):
            await main.web_mesaj_isle("test-sifre")
        for o in self.bot.olaylar:
            self.assertNotIn("test-sifre", o.get("metin", ""))
        self.assertTrue(any("yanlış" in o["metin"] for o in self.bot.olaylar))

    async def test_onay_dugmesi_bekleyen_onayi_sonuclandirir(self):
        gelecek = asyncio.get_running_loop().create_future()
        main.bekleyen_onaylar["abc123"] = gelecek
        try:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Onayla", callback_data="onay:abc123"),
                                        InlineKeyboardButton("Reddet", callback_data="red:abc123")]])
            await self.bot.send_message(1, "<b>Onay?</b>", parse_mode="HTML", reply_markup=kb)
            with mock.patch.object(main.kilit, "kilitli", False):
                await main.web_dugme_isle("onay:abc123")
            self.assertTrue(gelecek.result())
            son = self.bot.olaylar_sonrasi(0)[-1]
            self.assertEqual(son["dugmeler"], [])  # tıklanınca düğmeler kalkar
            self.assertIn("Onaylandı", son["metin"])
        finally:
            main.bekleyen_onaylar.pop("abc123", None)

    async def test_yuklenen_ses_foto_belge_mesaj_geldi_ye_gider(self):
        cagri = mock.AsyncMock()
        with mock.patch.object(main, "mesaj_geldi", cagri), mock.patch.object(main.kilit, "kilitli", False):
            await main.web_yukle_isle(b"ogg", "ses.webm", "audio/webm", "ses", "")
            await main.web_yukle_isle(b"jpeg-baytlari", "foto.jpg", "image/jpeg", "dosya", "bu ne")
            await main.web_yukle_isle(b"abc", "not.txt", "text/plain", "dosya", "")
        ses, foto, belge_ = [c.args[0].message for c in cagri.await_args_list]
        self.assertEqual((ses.voice.mime_type, ses.photo, ses.document), ("audio/webm", None, None))
        self.assertEqual((foto.caption, len(foto.photo), foto.voice), ("bu ne", 1, None))
        self.assertEqual((belge_.document.file_name, belge_.document.mime_type), ("not.txt", "text/plain"))
        # İşleyicilerin yaptığı gibi dosya get_file ile bir kez alınabilir
        dosya = await self.bot.get_file(foto.photo[0].file_id)
        self.assertEqual(bytes(await dosya.download_as_bytearray()), b"jpeg-baytlari")
        with self.assertRaises(FileNotFoundError):
            await self.bot.get_file(foto.photo[0].file_id)

    async def test_kilitliyken_yukleme_reddedilir(self):
        cagri = mock.AsyncMock()
        with mock.patch.object(main, "mesaj_geldi", cagri), mock.patch.object(main.kilit, "kilitli", True):
            await main.web_yukle_isle(b"x", "a.txt", "text/plain", "dosya", "")
        cagri.assert_not_awaited()

    async def test_bilinmeyen_dugme_sessizce_yok_sayilir(self):
        await main.web_dugme_isle("hack:1")
        await main.web_dugme_isle("onay:yok")
        self.assertEqual(len(self.bot.olaylar), 0)


if __name__ == "__main__":
    unittest.main()
