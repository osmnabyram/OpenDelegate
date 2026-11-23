"""Office belgelerinden düz metin: .docx (Word), .xlsx (Excel), .pptx (PowerPoint).

Yeni paket yok: bu biçimler ZIP içinde XML; zipfile (stdlib) + lxml (zaten kurulu) yeter.
Güvenlik: ZIP bombasına karşı açılmış boyut / dosya sayısı sınırı; XML'de varlık çözme, ağ ve
DTD yükleme kapalı (XXE yok). Dosya sadece bellekte işlenir.
"""

from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

MAKS_ACIK_TOPLAM = 40 * 1024 * 1024  # zip içindeki XML'lerin açılmış toplam boyutu
MAKS_ACIK_TEK = 20 * 1024 * 1024
MAKS_UYE = 3000
MAKS_KARAKTER = 60_000  # üretilen metin (ajana giden kısım ayrıca belge.py'de kesilir)
MAKS_SATIR = 400  # Excel: sayfa başına satır

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                          remove_comments=True)
TURLER = {".docx": "Word belgesi", ".xlsx": "Excel tablosu", ".pptx": "PowerPoint sunumu", ".pdf": "PDF belgesi"}
MAKS_SAYFA = 50  # PDF: okunacak en fazla sayfa
TARANMIS_ESIK = 5  # PDF: sayfa başına ortalama bu kadar harf/rakamdan azsa "taranmış" say (taranmışta ~0)
AZ_METIN_ESIK = 80  # bunun altındaysa okunur ama "çoğu resim olabilir" uyarısı eklenir


class OfisHatasi(Exception):
    pass


class _Arsiv:
    def __init__(self, veri: bytes) -> None:
        try:
            self.z = zipfile.ZipFile(io.BytesIO(veri))
        except zipfile.BadZipFile:
            raise OfisHatasi("dosya bozuk ya da gerçek bir Office belgesi değil") from None
        bilgiler = self.z.infolist()
        if len(bilgiler) > MAKS_UYE:
            raise OfisHatasi("belgenin içinde çok fazla parça var")
        if sum(i.file_size for i in bilgiler) > MAKS_ACIK_TOPLAM:
            raise OfisHatasi("belge açılınca çok büyük (sıkıştırma bombası olabilir)")
        self.adlar = {i.filename for i in bilgiler}

    def xml(self, ad: str) -> etree._Element | None:
        if ad not in self.adlar:
            return None
        if self.z.getinfo(ad).file_size > MAKS_ACIK_TEK:
            raise OfisHatasi("belgenin bir parçası çok büyük")
        try:
            return etree.fromstring(self.z.read(ad), _PARSER)
        except etree.XMLSyntaxError:
            raise OfisHatasi("belgenin içi okunamadı (bozuk XML)") from None


def _metin(el: etree._Element, etiket: str) -> str:
    return "".join(t.text or "" for t in el.iter(etiket))


# --------------------------------------------------------------------------

def _docx(z: _Arsiv) -> str:
    kok = z.xml("word/document.xml")
    if kok is None:
        raise OfisHatasi("Word belgesinin ana metni yok")
    govde = kok.find(f"{W}body")
    satirlar: list[str] = []
    for el in (govde if govde is not None else []):
        if el.tag == f"{W}p":
            satirlar.append(_metin(el, f"{W}t"))
        elif el.tag == f"{W}tbl":
            for tr in el.iter(f"{W}tr"):
                hucreler = [" ".join(_metin(p, f"{W}t") for p in tc.iter(f"{W}p")).strip() for tc in tr.iter(f"{W}tc")]
                satirlar.append(" | ".join(hucreler))
            satirlar.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(satirlar)).strip()


def _sutun_no(ref: str) -> int:
    no = 0
    for ch in re.match(r"[A-Z]*", ref or "").group(0):
        no = no * 26 + ord(ch) - 64
    return max(no - 1, 0)


def _xlsx(z: _Arsiv) -> str:
    ortak: list[str] = []
    ss = z.xml("xl/sharedStrings.xml")
    if ss is not None:
        ortak = [_metin(si, f"{S}t") for si in ss.iter(f"{S}si")]
    kitap = z.xml("xl/workbook.xml")
    iliski = z.xml("xl/_rels/workbook.xml.rels")
    if kitap is None or iliski is None:
        raise OfisHatasi("Excel çalışma kitabı yapısı eksik")
    hedef = {r.get("Id"): r.get("Target", "") for r in iliski.iter(f"{PR}Relationship")}
    parcalar: list[str] = []
    for sayfa in kitap.iter(f"{S}sheet"):
        yol = hedef.get(sayfa.get(f"{R}id"), "").lstrip("/")
        yol = yol if yol.startswith("xl/") else "xl/" + yol
        kok = z.xml(yol)
        if kok is None:
            continue
        parcalar.append(f"## Sayfa: {sayfa.get('name')}")
        for i, satir in enumerate(kok.iter(f"{S}row")):
            if i >= MAKS_SATIR:
                parcalar.append(f"... (ilk {MAKS_SATIR} satır gösterildi)")
                break
            degerler: dict[int, str] = {}
            for c in satir.iter(f"{S}c"):
                tip, v = c.get("t"), c.find(f"{S}v")
                if tip == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(ortak):
                    deger = ortak[int(v.text)]
                elif tip == "inlineStr":
                    deger = _metin(c, f"{S}t")
                elif tip == "b" and v is not None:
                    deger = "DOĞRU" if v.text == "1" else "YANLIŞ"
                else:
                    deger = (v.text or "") if v is not None else ""
                if deger != "":
                    degerler[_sutun_no(c.get("r", ""))] = deger.strip()
            if degerler:
                parcalar.append(" | ".join(degerler.get(k, "") for k in range(max(degerler) + 1)))
        parcalar.append("")
    return "\n".join(parcalar).strip()


def _pptx(z: _Arsiv) -> str:
    slaytlar = sorted(
        (a for a in z.adlar if re.fullmatch(r"ppt/slides/slide\d+\.xml", a)),
        key=lambda a: int(re.search(r"(\d+)\.xml$", a).group(1)),
    )
    parcalar: list[str] = []
    for no, ad in enumerate(slaytlar, 1):
        kok = z.xml(ad)
        if kok is None:
            continue
        satirlar = [s for s in (_metin(p, f"{A}t").strip() for p in kok.iter(f"{A}p")) if s]
        parcalar.append(f"## Slayt {no}")
        parcalar += satirlar or ["(metin yok)"]
        parcalar.append("")
    return "\n".join(parcalar).strip()


def _pdf(veri: bytes) -> str:
    """Metni seçilebilen PDF'ler (bilgisayarda üretilmiş). Taranmış PDF'te metin yok: açıkça söylenir."""
    import logging

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # bozuk PDF uyarıları loga taşmasın
    try:
        okuyucu = PdfReader(io.BytesIO(veri), strict=False)
        if okuyucu.is_encrypted and not okuyucu.decrypt(""):  # şifresiz-korumalı olanlar boş şifreyle açılır
            raise OfisHatasi("PDF şifreli; şifresiz bir kopyasını ya da sayfanın ekran görüntüsünü atarsan okurum")
        sayfalar = okuyucu.pages
        toplam = len(sayfalar)
        parcalar: list[str] = []
        harf = 0
        for no in range(min(toplam, MAKS_SAYFA)):
            metin = (sayfalar[no].extract_text() or "").strip()
            harf += sum(ch.isalnum() for ch in metin)
            parcalar += [f"## Sayfa {no + 1}", metin or "(bu sayfada metin yok)", ""]
    except OfisHatasi:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError) as e:
        raise OfisHatasi(f"PDF bozuk ya da okunamıyor ({type(e).__name__})") from None
    okunan = min(toplam, MAKS_SAYFA)
    if okunan and harf / okunan < TARANMIS_ESIK:
        raise OfisHatasi("bu PDF taranmış görünüyor (içinde yazı değil resim var); sayfanın fotoğrafını ya da "
                         "ekran görüntüsünü atarsan okurum")
    if toplam > MAKS_SAYFA:
        parcalar.append(f"... (toplam {toplam} sayfa; ilk {MAKS_SAYFA} sayfa okundu)")
    if okunan and harf / okunan < AZ_METIN_ESIK:
        parcalar.append("(UYARI: Bu PDF'ten çok az yazı çıktı; içeriğin çoğu resim ya da taranmış olabilir. Sadece "
                        "yukarıdakini okuyabildin: geri kalanını uydurma, kullanıcıya bunu söyle ve gerekirse "
                        "sayfaların fotoğrafını iste.)")
    return "\n".join(parcalar).strip()


def oku(ad: str, veri: bytes) -> tuple[str, str]:
    """(tür adı, düz metin). Okunamazsa OfisHatasi (Kullanıcıya gösterilebilir mesaj)."""
    uzanti = "." + ad.lower().rsplit(".", 1)[-1] if "." in ad else ""
    if uzanti not in TURLER:
        raise OfisHatasi("desteklenmeyen Office biçimi")
    if uzanti == ".pdf":
        return TURLER[uzanti], _pdf(veri)[:MAKS_KARAKTER]
    z = _Arsiv(veri)
    metin = {".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}[uzanti](z)
    return TURLER[uzanti], metin[:MAKS_KARAKTER]
