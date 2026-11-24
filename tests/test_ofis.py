"""ofis.py + belge Office akışı testleri. Belgeler bellekte, gerçek OOXML yapısıyla üretilir.

Çalıştır: python -m unittest tests.test_ofis
"""

import io
import types
import unittest
import zipfile

import belge
import ofis

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A_NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def zipla(parcalar: dict[str, str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for ad, icerik in parcalar.items():
            z.writestr(ad, icerik)
    return b.getvalue()


def docx(govde: str) -> bytes:
    return zipla({"word/document.xml": f'<?xml version="1.0"?><w:document {W_NS}><w:body>{govde}</w:body></w:document>'})


def p(metin: str) -> str:
    return f"<w:p><w:r><w:t>{metin}</w:t></w:r></w:p>"


def xlsx() -> bytes:
    return zipla({
        "xl/workbook.xml": f'<workbook {S_NS} {R_NS}><sheets><sheet name="Bütçe" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst {S_NS}><si><t>Kalem</t></si><si><t>Tutar</t></si><si><t>Protein tozu</t></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {S_NS}><sheetData>'
                                    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                    '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>1450.5</v></c></row>'
                                    '<row r="3"><c r="A3" t="inlineStr"><is><t>Aktif mi</t></is></c><c r="B3" t="b"><v>1</v></c></row>'
                                    '</sheetData></worksheet>',
    })


def pptx() -> bytes:
    def slayt(*satirlar):
        govde = "".join(f"<a:p><a:r><a:t>{s}</a:t></a:r></a:p>" for s in satirlar)
        return f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" {A_NS}>{govde}</p:sld>'
    return zipla({"ppt/slides/slide10.xml": slayt("Sonuç"), "ppt/slides/slide2.xml": slayt("Yöntem", "Pentest"),
                  "ppt/slides/slide1.xml": slayt("Acme Güvenlik")})


class Okuma(unittest.TestCase):
    def test_word_paragraf_ve_tablo(self):
        tablo = ("<w:tbl><w:tr><w:tc>" + p("Gün") + "</w:tc><w:tc>" + p("Ders") + "</w:tc></w:tr>"
                 "<w:tr><w:tc>" + p("Pazartesi") + "</w:tc><w:tc>" + p("Bilgisayar Ağları") + "</w:tc></w:tr></w:tbl>")
        tur, metin = ofis.oku("rapor.docx", docx(p("Staj Raporu") + p("Giriş paragrafı.") + tablo))
        self.assertEqual(tur, "Word belgesi")
        self.assertIn("Staj Raporu\nGiriş paragrafı.", metin)
        self.assertIn("Pazartesi | Bilgisayar Ağları", metin)

    def test_excel_hucreler_yerinde(self):
        tur, metin = ofis.oku("butce.xlsx", xlsx())
        self.assertEqual(tur, "Excel tablosu")
        self.assertIn("## Sayfa: Bütçe", metin)
        self.assertIn("Kalem | Tutar", metin)
        self.assertIn("Protein tozu |  | 1450.5", metin)  # B2 boş, C2 doğru sütunda
        self.assertIn("Aktif mi | DOĞRU", metin)

    def test_powerpoint_slayt_sirasi(self):
        tur, metin = ofis.oku("sunum.pptx", pptx())
        self.assertEqual(tur, "PowerPoint sunumu")
        self.assertLess(metin.index("Acme"), metin.index("Yöntem"))
        self.assertLess(metin.index("Yöntem"), metin.index("Sonuç"))  # slide10, slide2'den sonra
        self.assertIn("## Slayt 3\nSonuç", metin)


class Guvenlik(unittest.TestCase):
    def test_bozuk_dosya(self):
        with self.assertRaises(ofis.OfisHatasi):
            ofis.oku("x.docx", b"bu bir zip degil")

    def test_zip_bombasi(self):
        bomba = zipla({"word/document.xml": "<a/>" + " " * (ofis.MAKS_ACIK_TOPLAM + 10)})
        self.assertLess(len(bomba), 200_000)  # sıkıştırılmış hali küçük
        with self.assertRaises(ofis.OfisHatasi) as h:
            ofis.oku("x.docx", bomba)
        self.assertIn("bomba", str(h.exception))

    def test_xxe_dosya_okumaz(self):
        kotu = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///C:/Windows/win.ini">]>'
                f'<w:document {W_NS}><w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>')
        try:
            _, metin = ofis.oku("x.docx", zipla({"word/document.xml": kotu}))
        except ofis.OfisHatasi:
            return  # reddetmek de güvenli
        self.assertNotIn("[fonts]", metin.lower())
        self.assertNotIn("for 16-bit", metin.lower())


class BelgeAkisi(unittest.TestCase):
    def test_siniflandir(self):
        self.assertEqual(belge.siniflandir("a.docx", None, 1000).tur, "ofis")
        self.assertEqual(belge.siniflandir("dosya", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                           1000).tur, "ofis")
        eski = belge.siniflandir("eski.doc", "application/msword", 1000)
        self.assertEqual(eski.tur, "ret")
        self.assertIn(".docx olarak", eski.mesaj)
        self.assertIn(".xlsx", belge.siniflandir("t.xls", None, 1000).mesaj)
        self.assertEqual(belge.siniflandir("buyuk.pptx", None, 11 * 1024 * 1024).tur, "ret")

    def test_uzantisiz_excel_mime_ile(self):
        m = belge.ofis_mesaji("dosya", xlsx(), "", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("Excel tablosu", m)
        self.assertIn("Protein tozu", m)

    def test_mesaj_ve_hassas_maskeleme(self):
        m = belge.ofis_mesaji("form.docx", docx(p("Ad: Kullanıcı") + p("TC: 12345678901")), "bunu özetle")
        self.assertIn("Word belgesi", m)
        self.assertIn("Kullanıcının notu: bunu özetle", m)
        self.assertNotIn("12345678901", m)
        self.assertIn("[hassas]", m)


class Isleyici(unittest.IsolatedAsyncioTestCase):
    async def test_telegramdan_excel(self):
        import main
        cevaplar = []

        async def reply_text(t, **k):
            cevaplar.append(t)

        async def get_file(fid):
            async def indir():
                return bytearray(xlsx())
            return types.SimpleNamespace(download_as_bytearray=indir)

        async def aksiyon(*a, **k):
            return None

        doc = types.SimpleNamespace(file_id="d", file_size=2000, file_name="butce.xlsx",
                                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        upd = types.SimpleNamespace(message=types.SimpleNamespace(photo=[], document=doc, caption="toplam ne",
                                                                  reply_text=reply_text),
                                    effective_chat=types.SimpleNamespace(id=1))
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(get_file=get_file, send_chat_action=aksiyon))
        metin = await main._dosyayi_metne_cevir(upd, ctx)
        self.assertIn("Excel tablosu", metin)
        self.assertIn("Kullanıcının notu: toplam ne", metin)

    async def test_bozuk_belge_kibar(self):
        import main
        cevaplar = []

        async def reply_text(t, **k):
            cevaplar.append(t)

        async def get_file(fid):
            async def indir():
                return bytearray(b"bozuk")
            return types.SimpleNamespace(download_as_bytearray=indir)

        async def aksiyon(*a, **k):
            return None

        doc = types.SimpleNamespace(file_id="d", file_size=5, file_name="x.docx", mime_type=None)
        upd = types.SimpleNamespace(message=types.SimpleNamespace(photo=[], document=doc, caption=None,
                                                                  reply_text=reply_text),
                                    effective_chat=types.SimpleNamespace(id=1))
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(get_file=get_file, send_chat_action=aksiyon))
        self.assertIsNone(await main._dosyayi_metne_cevir(upd, ctx))
        self.assertIn("Belgeyi açamadım kullanıcı", cevaplar[0])


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------
# PDF (pypdf)
# --------------------------------------------------------------------------

def pdf(*sayfalar: str) -> bytes:
    """Elle kurulmuş geçerli PDF: her argüman bir sayfanın metni ('' = metinsiz, taranmış gibi)."""
    n = len(sayfalar)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    nesne = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
             2: f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
             3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    for i, t in enumerate(sayfalar):
        sayfa, akis_no = 4 + 2 * i, 5 + 2 * i
        akis = f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET".encode() if t else b""
        nesne[sayfa] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                        f"/Resources << /Font << /F1 3 0 R >> >> /Contents {akis_no} 0 R >>").encode()
        nesne[akis_no] = b"<< /Length %d >>\nstream\n" % len(akis) + akis + b"\nendstream"
    cikti, konum = b"%PDF-1.4\n", {}
    for k in sorted(nesne):
        konum[k] = len(cikti)
        cikti += b"%d 0 obj\n" % k + nesne[k] + b"\nendobj\n"
    xref = len(cikti)
    cikti += b"xref\n0 %d\n0000000000 65535 f \n" % (len(nesne) + 1)
    cikti += b"".join(b"%010d 00000 n \n" % konum[k] for k in sorted(nesne))
    cikti += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(nesne) + 1, xref)
    return cikti


class Pdf(unittest.TestCase):
    def test_metinli_pdf(self):
        tur, metin = ofis.oku("cv.pdf", pdf("Ali Veli - Cybersecurity", "Projects: Demo Toolkit"))
        self.assertEqual(tur, "PDF belgesi")
        self.assertIn("## Sayfa 1\nAli Veli - Cybersecurity", metin)
        self.assertIn("## Sayfa 2\nProjects: Demo Toolkit", metin)

    def test_taranmis_pdf_durustce_soylenir(self):
        with self.assertRaises(ofis.OfisHatasi) as h:
            ofis.oku("tarama.pdf", pdf("", ""))
        self.assertIn("taranmış", str(h.exception))

    def test_sifreli_pdf(self):
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf("Gizli rapor icerigi burada"))))
        w.encrypt(user_password="gizli", owner_password="sahip", algorithm="RC4-128")
        b = io.BytesIO()
        w.write(b)
        with self.assertRaises(ofis.OfisHatasi) as h:
            ofis.oku("sifreli.pdf", b.getvalue())
        self.assertIn("şifreli", str(h.exception))

    def test_bozuk_pdf(self):
        with self.assertRaises(ofis.OfisHatasi):
            ofis.oku("bozuk.pdf", b"%PDF-1.4\nbu gercek bir pdf degil")

    def test_sayfa_siniri(self):
        _, metin = ofis.oku("uzun.pdf", pdf(*[f"Sayfa metni numara {i}" for i in range(ofis.MAKS_SAYFA + 5)]))
        self.assertIn(f"toplam {ofis.MAKS_SAYFA + 5} sayfa; ilk {ofis.MAKS_SAYFA} sayfa okundu", metin)
        self.assertNotIn(f"numara {ofis.MAKS_SAYFA + 1}", metin)

    def test_belge_akisi_uzantisiz_pdf(self):
        self.assertEqual(belge.siniflandir("cv.pdf", "application/pdf", 5000).tur, "ofis")
        m = belge.ofis_mesaji("belge", pdf("Fatura toplam 245 TL"), "", "application/pdf")
        self.assertIn("PDF belgesi", m)
        self.assertIn("Fatura toplam 245 TL", m)


class PdfIsleyici(unittest.IsolatedAsyncioTestCase):
    async def test_telegramdan_pdf(self):
        import main
        cevaplar = []

        async def reply_text(t, **k):
            cevaplar.append(t)

        async def get_file(fid):
            async def indir():
                return bytearray(pdf("CV icerigi: Doğus Universitesi"))
            return types.SimpleNamespace(download_as_bytearray=indir)

        async def aksiyon(*a, **k):
            return None

        doc = types.SimpleNamespace(file_id="d", file_size=3000, file_name="001-Ali-Veli.pdf",
                                    mime_type="application/pdf")
        upd = types.SimpleNamespace(message=types.SimpleNamespace(photo=[], document=doc, caption=None,
                                                                  reply_text=reply_text),
                                    effective_chat=types.SimpleNamespace(id=1))
        ctx = types.SimpleNamespace(bot=types.SimpleNamespace(get_file=get_file, send_chat_action=aksiyon))
        metin = await main._dosyayi_metne_cevir(upd, ctx)
        self.assertIn("PDF belgesi", metin)
        self.assertIn("CV icerigi", metin)
        self.assertEqual(cevaplar, [])


class PdfAzMetin(unittest.TestCase):
    def test_az_metinde_uyari_bol_metinde_yok(self):
        _, az = ofis.oku("az.pdf", pdf("Sadece baslik 2026"))
        self.assertIn("çok az yazı çıktı", az)
        _, bol = ofis.oku("bol.pdf", pdf("Bu sayfada yeterince uzun bir metin var: staj raporu giris, amac, "
                                         "yontem, bulgular ve sonuc bolumleri burada yaziyor."))
        self.assertNotIn("çok az yazı çıktı", bol)
