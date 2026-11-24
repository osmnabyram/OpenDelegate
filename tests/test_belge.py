"""belge.py + main._dosyayi_metne_cevir testleri (ağ ve model yok; görsel model sahte).

Çalıştır: python -m unittest tests.test_belge
"""

import json
import types
import unittest
from datetime import date
from unittest import mock

import belge

GUN = date(2026, 11, 12)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def model(**alanlar):
    return "```json\n" + json.dumps(alanlar, ensure_ascii=False) + "\n```"


class Siniflandirma(unittest.TestCase):
    def test_turler(self):
        self.assertEqual(belge.siniflandir("fotograf.jpg", "image/jpeg", 300_000).tur, "resim")
        self.assertEqual(belge.siniflandir("ekran.PNG", None, 1000).tur, "resim")
        self.assertEqual(belge.siniflandir("hata.log", "application/octet-stream", 2000).tur, "metin")
        self.assertEqual(belge.siniflandir("notlar.md", "text/markdown", 2000).tur, "metin")

    def test_buyuk_dosya_kibar_ret(self):
        k = belge.siniflandir("fotograf.jpg", "image/jpeg", 12 * 1024 * 1024)
        self.assertEqual(k.tur, "ret")
        self.assertIn("12.0 MB", k.mesaj)
        self.assertIn("limit 8.0 MB", k.mesaj)
        self.assertEqual(belge.siniflandir("buyuk.txt", "text/plain", 600 * 1024).tur, "ret")

    def test_desteklenmeyenler(self):
        self.assertEqual(belge.siniflandir("fatura.pdf", "application/pdf", 1000).tur, "ofis")  # artık okunuyor
        self.assertIn("image/heic", belge.siniflandir("IMG_1.HEIC", "image/heic", 1000).mesaj)
        k = belge.siniflandir("kurulum.exe", "application/x-msdownload", 1000)
        self.assertEqual(k.tur, "ret")
        self.assertIn("Okuyabildiklerim", k.mesaj)


class DortMod(unittest.TestCase):
    def test_not_tenis_tahtasi(self):
        a = belge.analizi_ayristir(model(
            tur="not", baslik="Tenis antrenmanı", konu="Tenis", ozet="Antrenman tahtası.",
            metin="1. O-goshi giriş x10\n2. Seoi-nage x10\n3. Uki-goshi x[okunmuyor]",
            belirsiz=["3. satırdaki tekrar sayısı"], hassas=False, fis=None))
        self.assertEqual(a.tur, "not")
        yol, icerik = belge.kayit_onerisi(a, GUN)
        self.assertEqual(yol, "klasorler/notlar/tenis-2026-11-12.txt")
        self.assertIn("Seoi-nage x10", icerik)
        self.assertIn("Okunamayan / emin olunamayan yerler: 3. satırdaki tekrar sayısı", icerik)
        m = belge.ajan_mesaji(a, "", GUN)
        self.assertIn("onedrive_yukle", m)
        self.assertIn("yol='klasorler/notlar/tenis-2026-11-12.txt'", m)
        self.assertIn("Hazır dosya içeriği", m)

    def test_fis(self):
        a = belge.analizi_ayristir(model(
            tur="fis", ozet="Market fişi.", metin="...", belirsiz=[], hassas=False,
            fis={"magaza": "Migros Şişli", "tarih": "12.11.2026", "toplam": "245,90 TL", "odeme": "Kart",
                 "kalemler": [{"ad": "Yulaf", "tutar": "89,90"}, {"ad": "Yumurta 30'lu", "tutar": "156,00"}]}))
        yol, icerik = belge.kayit_onerisi(a, GUN)
        self.assertEqual(yol, "klasorler/fisler/2026-11-12-migros-sisli.txt")
        self.assertIn("Toplam: 245,90 TL", icerik)
        self.assertIn("  - Yulaf: 89,90", icerik)
        self.assertIn("fiş/fatura", belge.ajan_mesaji(a, "", GUN))

    def test_hata(self):
        a = belge.analizi_ayristir(model(
            tur="hata", ozet="Python ModuleNotFoundError.", metin="ModuleNotFoundError: No module named 'mss'",
            belirsiz=[], hassas=False, fis=None))
        self.assertIsNone(belge.kayit_onerisi(a, GUN))  # hata kaydedilmez, çözülür
        m = belge.ajan_mesaji(a, "bu ne kanka", GUN)
        self.assertIn("çözüm adımları öner", m)
        self.assertIn("Kullanıcının notu: bu ne kanka", m)
        self.assertNotIn("onedrive_yukle", m)

    def test_genel(self):
        a = belge.analizi_ayristir(model(tur="genel", ozet="Bir kedi fotoğrafı.", metin="", belirsiz=[],
                                         hassas=False, fis=None))
        self.assertIsNone(belge.kayit_onerisi(a, GUN))
        self.assertIn("ne olduğunu kısaca anlat", belge.ajan_mesaji(a, "", GUN))

    def test_bilinmeyen_tur_ve_json_olmayan_cevap_genele_duser(self):
        self.assertEqual(belge.analizi_ayristir(model(tur="tarif", ozet="x")).tur, "genel")
        a = belge.analizi_ayristir("Bu fotoğrafta bir masa var.")
        self.assertEqual((a.tur, a.ozet), ("genel", "Bu fotoğrafta bir masa var."))


class Durustluk(unittest.TestCase):
    def test_okunamayan_uydurulmaz(self):
        a = belge.analizi_ayristir(model(
            tur="fis", ozet="Silik fiş.", metin="Toplam: [okunmuyor]", belirsiz=["toplam tutar", "tarih"],
            hassas=False, fis={"magaza": "A101", "tarih": "", "toplam": "", "odeme": "", "kalemler": []}))
        _, icerik = belge.kayit_onerisi(a, GUN)
        self.assertIn("Toplam: [okunmuyor]", icerik)  # boş tutar yerine uydurma yok
        self.assertIn("Fiş tarihi: [okunmuyor]", icerik)
        m = belge.ajan_mesaji(a, "", GUN)
        self.assertIn("Okunamayan / emin olunamayan yerler: toplam tutar, tarih", m)
        self.assertIn("uydurma", m)


class Hassas(unittest.TestCase):
    def test_model_kacirsa_bile_maskelenir_ve_kaydedilmez(self):
        a = belge.analizi_ayristir(model(
            tur="not", konu="kimlik", ozet="Kimlik kartı", hassas=False, belirsiz=[], fis=None,
            metin="TC: 12345678901\nKart: 4543 1234 5678 9012\nIBAN TR33 0006 1005 1978 6457 8413 26"))
        self.assertTrue(a.hassas)
        for deger in ("12345678901", "4543 1234 5678 9012", "TR33"):
            self.assertNotIn(deger, a.metin)
        self.assertIsNone(belge.kayit_onerisi(a, GUN))
        m = belge.ajan_mesaji(a, "", GUN)
        self.assertIn("HASSAS BİLGİ GÖRÜNÜYOR", m)
        self.assertNotIn("onedrive_yukle", m)

    def test_normal_sayilar_maskelenmez(self):
        metin, h = belge.hassas_maskele("Toplam 1.245,90 TL, saat 20:00, tel 0532 123 45 67, tarih 12.11.2026")
        self.assertFalse(h)
        self.assertIn("1.245,90", metin)

    def test_metin_dosyasi(self):
        veri = ("Traceback...\nKeyError: 'x'\nkart 4543123456789012\n" + "a" * 30_000).encode()
        m = belge.metin_dosyasi_mesaji("hata.log", veri, "")
        self.assertIn("hata.log", m)
        self.assertIn("KeyError", m)
        self.assertNotIn("4543123456789012", m)
        self.assertIn("ilk 20000 karakter", m)


# --------------------------------------------------------------------------
# Telegram işleyicisi (main._dosyayi_metne_cevir)
# --------------------------------------------------------------------------

class Isleyici(unittest.IsolatedAsyncioTestCase):
    def _kur(self, foto=None, doc=None, icerik=JPEG, caption=None):
        import main
        self.main = main
        self.cevaplar, self.indirilen = [], []

        async def reply_text(t, **k):
            self.cevaplar.append(t)

        async def get_file(fid):
            self.indirilen.append(fid)

            async def indir():
                return bytearray(icerik)
            return types.SimpleNamespace(download_as_bytearray=indir)

        async def send_chat_action(*a, **k):
            return None

        mesaj = types.SimpleNamespace(photo=foto or [], document=doc, caption=caption, reply_text=reply_text)
        upd = types.SimpleNamespace(message=mesaj, effective_chat=types.SimpleNamespace(id=1))
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(get_file=get_file, send_chat_action=send_chat_action))
        return upd, ctx

    async def test_buyuk_foto_indirilmeden_reddedilir(self):
        upd, ctx = self._kur(foto=[types.SimpleNamespace(file_id="f", file_size=20 * 1024 * 1024, width=1, height=1)])
        self.assertIsNone(await self.main._dosyayi_metne_cevir(upd, ctx))
        self.assertEqual(self.indirilen, [])
        self.assertIn("çok büyük", self.cevaplar[0])

    async def test_foto_anlasilir(self):
        fotolar = [types.SimpleNamespace(file_id="kucuk", file_size=1000, width=90, height=90),
                   types.SimpleNamespace(file_id="buyuk", file_size=90000, width=1280, height=960)]
        upd, ctx = self._kur(foto=fotolar, caption="antrenman tahtası")
        sahte = mock.AsyncMock(return_value=model(tur="not", konu="tenis", ozet="Tahta", metin="O-goshi",
                                                  belirsiz=[], hassas=False, fis=None))
        with mock.patch.object(self.main.gorsel, "fotografi_incele", sahte):
            metin = await self.main._dosyayi_metne_cevir(upd, ctx)
        self.assertEqual(self.indirilen, ["buyuk"])  # en büyük boyut
        self.assertEqual(sahte.await_args.args[1], "antrenman tahtası")
        self.assertIn("Tür: not", metin)
        self.assertIn("klasorler/notlar/tenis-", metin)

    async def test_buyuk_pdf_indirilmeden_reddedilir(self):
        upd, ctx = self._kur(doc=types.SimpleNamespace(file_id="d", file_size=11 * 1024 * 1024,
                                                       file_name="fatura.pdf", mime_type="application/pdf"))
        self.assertIsNone(await self.main._dosyayi_metne_cevir(upd, ctx))
        self.assertIn("çok büyük", self.cevaplar[0])
        self.assertEqual(self.indirilen, [])

    async def test_boyutu_bilinmeyen_dosya_indirince_kontrol(self):
        upd, ctx = self._kur(doc=types.SimpleNamespace(file_id="d", file_size=None, file_name="log.txt",
                                                       mime_type="text/plain"), icerik=b"x" * (600 * 1024))
        self.assertIsNone(await self.main._dosyayi_metne_cevir(upd, ctx))
        self.assertIn("çok büyük", self.cevaplar[0])

    async def test_metin_dosyasi(self):
        upd, ctx = self._kur(doc=types.SimpleNamespace(file_id="d", file_size=30, file_name="hata.log",
                                                       mime_type="text/plain"), icerik=b"KeyError: 'x'")
        self.assertIn("KeyError", await self.main._dosyayi_metne_cevir(upd, ctx))

    def test_ses_filtresi_duruyor(self):
        import inspect
        import main
        kaynak = inspect.getsource(main.uygulama_kur)
        self.assertIn("filters.VOICE | filters.AUDIO", kaynak)
        self.assertIn("filters.PHOTO | filters.Document.ALL", kaynak)
        self.assertIn("_sesi_metne_cevir(update, context)", inspect.getsource(main.mesaj_geldi))


if __name__ == "__main__":
    unittest.main()


class VideoVeButonlar(unittest.IsolatedAsyncioTestCase):
    def test_video_dosyasi_kibar_ret(self):
        for ad, mime in (("antrenman.mp4", "video/mp4"), ("klip.MOV", None), ("x.webm", "video/webm")):
            k = belge.siniflandir(ad, mime, 1000)
            self.assertEqual(k.tur, "ret")
            self.assertIn("Videoyu göremiyorum", k.mesaj)

    async def test_video_mesaji_modele_gitmez(self):
        import main
        cevaplar = []

        async def reply_text(t, **k):
            cevaplar.append(t)

        mesaj = types.SimpleNamespace(video=object(), video_note=None, animation=None, text=None,
                                      reply_text=reply_text)
        upd = types.SimpleNamespace(message=mesaj, effective_chat=types.SimpleNamespace(id=main.config.TELEGRAM_CHAT_ID))
        with mock.patch.object(main, "ajan_turu", mock.AsyncMock()) as ajan:
            await main.mesaj_geldi(upd, types.SimpleNamespace(bot=None))
        self.assertEqual(cevaplar, [main.VIDEO_CEVABI])
        ajan.assert_not_called()

    def test_butonlar(self):
        import main
        satirlar = [[(b.text, b.callback_data) for b in r] for r in main.KOMUT_BUTONLARI.inline_keyboard]
        self.assertEqual([t for r in satirlar for t, _ in r],
                         ["🧠 Zihin haritası", "💾 Hafıza", "🖥 Masaüstü", "📊 Durum",
                          "📰 Brifing", "📜 Grind", "📡 Pist", "📞 Ara", "📸 SS"])
        for _, veri in (x for r in satirlar for x in r):
            self.assertIn(veri.split(":")[1], main._komut_haritasi())  # her butonun işleyicisi var


class PistButonu(unittest.IsolatedAsyncioTestCase):
    async def test_pist_aninda_cevap_model_yok(self):
        import main
        gonderilen = []

        async def send_message(chat_id, text, **kw):
            gonderilen.append(text)

        async def answer(*a, **k):
            return None

        sorgu = types.SimpleNamespace(data="komut:pist", answer=answer)
        upd = types.SimpleNamespace(callback_query=sorgu, effective_chat=types.SimpleNamespace(id=main.config.TELEGRAM_CHAT_ID),
                                    effective_user=None)
        with mock.patch.object(main, "ajan_turu", mock.AsyncMock()) as ajan:
            await main.komut_butonu(upd, types.SimpleNamespace(bot=types.SimpleNamespace(send_message=send_message), args=None))
        self.assertEqual(len(gonderilen), 1)
        self.assertIn(gonderilen[0], main.PIST_CEVAPLARI)
        ajan.assert_not_called()


class Cls(unittest.IsolatedAsyncioTestCase):
    async def test_temizler_sonra_temiz_start(self):
        import main
        silinen, gonderilen = [], []

        async def delete_messages(chat_id, ids):
            silinen.append(list(ids))
            if ids[0] < 400:
                raise RuntimeError("çok eski")  # bir grup patlasa da devam etmeli
            return True

        async def send_message(chat_id, text, **kw):
            gonderilen.append((text, kw.get("reply_markup")))

        bot = types.SimpleNamespace(delete_messages=delete_messages, send_message=send_message)
        mesaj = types.SimpleNamespace(message_id=1000, reply_text=None)  # silinen mesaja cevap verilmemeli
        upd = types.SimpleNamespace(message=mesaj, effective_chat=types.SimpleNamespace(id=main.config.TELEGRAM_CHAT_ID))
        await main.komut_cls(upd, types.SimpleNamespace(bot=bot))
        hepsi = [i for g in silinen for i in g]
        self.assertEqual(hepsi[0], 1000)  # /cls mesajının kendisi de silinir
        self.assertEqual(hepsi[-1], 1)  # geriye 1'e kadar (1000 < kapsam)
        self.assertTrue(all(len(g) <= 100 for g in silinen))  # Telegram sınırı: çağrı başına 100
        self.assertEqual(len(set(hepsi)), len(hepsi))
        self.assertEqual(gonderilen, [(main.START_GONDERI, main.KOMUT_BUTONLARI)])  # temiz /start + butonlar

    async def test_yetkisiz_dokunmaz(self):
        import main
        bot = types.SimpleNamespace(delete_messages=mock.AsyncMock(), send_message=mock.AsyncMock())
        upd = types.SimpleNamespace(message=types.SimpleNamespace(message_id=50),
                                    effective_chat=types.SimpleNamespace(id=12345))
        await main.komut_cls(upd, types.SimpleNamespace(bot=bot))
        bot.delete_messages.assert_not_called()


class DuzCls(unittest.IsolatedAsyncioTestCase):
    async def test_duz_cls_temizler_modele_gitmez(self):
        import main
        for metin in ("cls", "CLS", "  Cls  "):
            mesaj = types.SimpleNamespace(text=metin, message_id=10, video=None, video_note=None, animation=None)
            upd = types.SimpleNamespace(message=mesaj, effective_chat=types.SimpleNamespace(id=main.config.TELEGRAM_CHAT_ID))
            with mock.patch.object(main, "komut_cls", mock.AsyncMock()) as cls, \
                    mock.patch.object(main, "ajan_turu", mock.AsyncMock()) as ajan:
                await main.mesaj_geldi(upd, types.SimpleNamespace(bot=None))
            cls.assert_awaited_once()
            ajan.assert_not_called()

    async def test_icinde_cls_gecen_cumle_temizlemez(self):
        import main
        mesaj = types.SimpleNamespace(text="cls komutu ne işe yarıyor", message_id=10, video=None, video_note=None,
                                      animation=None, voice=None, audio=None, photo=None, document=None)
        upd = types.SimpleNamespace(message=mesaj, effective_chat=types.SimpleNamespace(id=main.config.TELEGRAM_CHAT_ID))
        with mock.patch.object(main, "komut_cls", mock.AsyncMock()) as cls, \
                mock.patch.object(main, "dur_mu", return_value=True), mock.patch.object(main, "durdur", mock.AsyncMock()):
            await main.mesaj_geldi(upd, types.SimpleNamespace(bot=None))  # 'dur' yolunda kesilir; cls çağrılmamalı
        cls.assert_not_called()
