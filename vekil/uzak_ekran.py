"""Uzak ekran: tarayıcıdan PC'nin ekranını görüp tıklama/yazma (AnyDesk benzeri, canlı video DEĞİL).

Sayfa (static/uzak.html) ekranı ~3 sn'de bir tazeler; resme dokununca o noktaya tıklanır. Yazı, tuş,
kaydırma, monitör seçimi, tam ekran var.

GÜVENLİK (bu yol PC'nin tam kontrolünü verir, katmanlar bilerek çok):
1. Adres gizli: yol öneki ve token, ANA_SIR'dan (bot token'ı ya da OPENDELEGATE_SIR) HMAC-SHA256 ile türetilir (256 bit, tahmin
   edilemez; koda gömülü sır yok). Yanlış adres -> 404, çok yanlış deneme -> herkese 429.
2. Adresi bilmek yetmez, ÖNCE BAĞLANMAK gerekir. Bağlantı iki yoldan açılır:
   a) Sohbetteki /uzak bağlantısı 7 gün geçerli BİLET taşır (adresin # kısmında: sunucu
      logunda/referrer'da görünmez, sayfa onu hemen siler) -> bağlantı hemen açılır.
   b) Biletsiz (yer imi, sızmış adres) -> sohbete (ve Telegram açıksa oraya) "Sen miydin?" Onayla/Reddet gider; onay yoksa açılmaz.
3. Bağlantı = rastgele 256 bit OTURUM kimliği (sadece sayfa belleğinde, çerez DEĞİL: CSRF'ye kapalı).
   Her /ekran ve /eylem bunu ister. 6 saat boşta ya da 7 gün sonra düşer; en çok 3 eşzamanlı oturum.
4. Her bağlantıda sohbete haber (IP, saat) + "Tüm bağlantıları kes" düğmesi; /uzakkapat da var.
5. Kilitliyken (kys) hiçbir şey çalışmaz, oturumlar silinir. Başlıklar: CSP, frame-ancestors none, HSTS.

PC tarafı: her şey gorevler.calistir_ekli ile ajana gider; OpenDelegate ile aynı PC_KILIDI'ni paylaşır.
Aynı kare tekrar gönderilmez: istemci hash yollar, değişmediyse 204.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Route

import config
import gorevler
import kilit

logger = logging.getLogger(__name__)

SAYFA_DOSYASI = Path(__file__).with_name("static") / "uzak.html"
BASLIKLAR = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=63072000",
}
SAYFA_BASLIKLARI = {
    **BASLIKLAR,
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src blob: data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
}
EKRANLAR = ("ana", "1", "2", "hepsi")
TAZE_SN = 0.6            # bu kadar yeni kare varsa ajana tekrar sorma (sayfa en sık ~0,6 sn + yol süresi soruyor)
KILIT_BEKLE_SN = 20      # OpenDelegate adım atıyorsa en çok bu kadar sıra bekle
EYLEM_BEKLE = 0.1        # tıkladıktan sonra ekranın oturmasını en çok bu kadar (ek) bekle: hızlı dönüş
HATA_PENCERE = 60.0
HATA_LIMIT = 20
BILET_SN = 7 * 86400  # uzun dış işler için süre kısıtı yok denecek kadar; /uzakkapat siler
ONAY_SN = 120
OTURUM_BOSTA_SN = 6 * 3600  # sayfa arka plandayken tazeleme durur; telefon kilitlenince oturum hemen düşmesin
OTURUM_AZAMI_SN = 7 * 86400
MAKS_OTURUM = 3
MAKS_BEKLEYEN = 3
BAGLAN_PENCERE = 60.0
BAGLAN_LIMIT = 10

Bildirici = Callable[[str, list[tuple[str, str]]], Awaitable[None]]

_hatalar: deque[float] = deque()
_baglanlar: deque[float] = deque()
_cekim = asyncio.Lock()
_kare: dict[str, dict[str, Any]] = {}      # ekran -> {png, hash, alan, aktif, zaman}
_oturumlar: dict[str, dict[str, Any]] = {}  # oturum kimliği -> {olus, son, ip}
_biletler: dict[str, float] = {}           # bilet -> bitiş (monotonic)
_bekleyen: dict[str, dict[str, Any]] = {}  # onay kimliği -> {olus, durum, oturum, ip}
_bildirici: Bildirici | None = None


# --------------------------------------------------------------------------
# Adres: gizli yol + gizli token (ikisi de bot token'ından türer)
# --------------------------------------------------------------------------

def _tur(etiket: bytes) -> str:
    tohum = (config.ANA_SIR or "").encode("utf-8")
    if not tohum:
        return ""
    ozet = hmac.new(tohum, etiket, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(ozet).decode().rstrip("=")


def token() -> str:
    return _tur(b"vekil-uzak-ekran-v2")  # 43 karakter, 256 bit


def yol() -> str:
    return "/" + _tur(b"vekil-uzak-yol-v2")[:16]


def token_dogru(aday: str | None) -> bool:
    beklenen = token()
    return bool(aday) and bool(beklenen) and hmac.compare_digest(str(aday).encode(), beklenen.encode())


def link(bilet: str = "") -> str:
    taban = (config.WEBHOOK_URL or "").rstrip("/")
    if not taban or not token():
        return ""
    return f"{taban}{yol()}/{token()}" + (f"#b={bilet}" if bilet else "")


class TokenMaskeleyici(logging.Filter):
    """Token ve gizli yol hiçbir log satırına açık yazılmasın."""

    def filter(self, kayit: logging.LogRecord) -> bool:
        t = token()
        if t:
            try:
                mesaj = kayit.getMessage()
            except Exception:  # noqa: BLE001
                return True
            if t in mesaj:
                kayit.msg, kayit.args = mesaj.replace(t, t[:4] + "…"), ()
        return True


# --------------------------------------------------------------------------
# Bildirim (sohbet + varsa Telegram) + bilet + onay + oturum
# --------------------------------------------------------------------------

def bildirici_kur(fn: Bildirici | None) -> None:
    global _bildirici
    _bildirici = fn


async def _bildir(metin: str, butonlar: list[tuple[str, str]]) -> bool:
    if _bildirici is None:
        return False
    try:
        await _bildirici(metin, butonlar)
        return True
    except Exception as e:  # noqa: BLE001 - bildirim gitmediyse onay istenen yerde açılmaz
        logger.warning("Uzak ekran bildirimi gitmedi: %s", type(e).__name__)
        return False


def _ip(request: Request) -> str:
    ham = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not ham and request.client:
        ham = request.client.host
    return ham[:45] or "bilinmiyor"


_TARAYICILAR = (("SamsungBrowser", "Samsung Internet"), ("Edg", "Edge"), ("OPR", "Opera"), ("Firefox", "Firefox"),
                ("Brave", "Brave"), ("Chrome", "Chrome"), ("Safari", "Safari"))


def _cihaz(request: Request, model: Any = "") -> str:
    """'Samsung SM-S918B · Chrome' gibi okunur cihaz adı. model: sayfanın verdiği (Client Hints), yoksa User-Agent."""
    ua = request.headers.get("user-agent", "")
    m = re.sub(r"[^\w .,+\-]", "", str(model or ""))[:40].strip()
    if not m:
        if "iPhone" in ua:
            m = "iPhone"
        elif "iPad" in ua:
            m = "iPad"
        elif "Android" in ua:
            bulunan = re.search(r"Android[^;)]*;\s*([^;)]+)", ua)
            adi = re.sub(r"\sBuild.*", "", bulunan.group(1)).strip() if bulunan else ""
            m = adi if adi and adi != "K" else "Android telefon"
        elif "Windows" in ua:
            m = "Windows bilgisayar"
        elif "Macintosh" in ua:
            m = "Mac"
        elif "Linux" in ua:
            m = "Linux"
        else:
            m = "bilinmeyen cihaz"
    if re.match(r"(?i)sm-", m):
        m = "Samsung " + m.upper()
    tarayici = next((ad for iz, ad in _TARAYICILAR if iz in ua), "")
    return f"{m} · {tarayici}" if tarayici else m


def _temizle() -> None:
    simdi = time.monotonic()
    for b in [b for b, bitis in _biletler.items() if bitis < simdi]:
        _biletler.pop(b, None)
    for s in [s for s, o in _oturumlar.items()
              if simdi - o["son"] > OTURUM_BOSTA_SN or simdi - o["olus"] > OTURUM_AZAMI_SN]:
        _oturumlar.pop(s, None)
    for i in [i for i, b in _bekleyen.items() if simdi - b["olus"] > ONAY_SN + 30]:
        _bekleyen.pop(i, None)


def bilet_uret() -> str:
    """Sohbetteki /uzak için bilet (süresince tekrar kullanılabilir; sayfayı kapatıp açınca onay istemesin)."""
    _temizle()
    b = secrets.token_urlsafe(24)
    _biletler[b] = time.monotonic() + BILET_SN
    return b


def _bilet_gecerli(aday: str) -> bool:
    _temizle()
    if not aday:
        return False
    bulundu = False
    for b in list(_biletler):  # sabit zamanlı karşılaştırma, ilk eşleşmede durmadan
        if hmac.compare_digest(b.encode(), str(aday).encode()):
            bulundu = True
    return bulundu


def _oturum_ac(ip: str, cihaz: str = "") -> str:
    _temizle()
    while len(_oturumlar) >= MAKS_OTURUM:
        _oturumlar.pop(min(_oturumlar, key=lambda s: _oturumlar[s]["son"]))
    sid = secrets.token_urlsafe(32)
    simdi = time.monotonic()
    _oturumlar[sid] = {"olus": simdi, "son": simdi, "ip": ip, "cihaz": cihaz}
    return sid


def oturumlari_kes() -> int:
    n = len(_oturumlar)
    _oturumlar.clear()
    _bekleyen.clear()
    _biletler.clear()
    return n


def _oturum_gecerli(request: Request) -> bool:
    _temizle()
    aday = request.headers.get("x-oturum", "")
    if not aday:
        return False
    bulundu = None
    for sid in _oturumlar:
        if hmac.compare_digest(sid.encode(), aday.encode()):
            bulundu = sid
    if bulundu is None:
        return False
    _oturumlar[bulundu]["son"] = time.monotonic()
    return True


def onay_ver(onay_id: str, kabul: bool) -> str:
    """Sohbet düğmesi: bekleyen bağlantı isteğini onayla/reddet. Kullanıcıya dönecek kısa sonuç."""
    _temizle()
    b = _bekleyen.get(onay_id)
    if not b or b["durum"] != "bekliyor" or time.monotonic() - b["olus"] > ONAY_SN:
        return "İstek süresi dolmuş ya da zaten cevaplanmış."
    b["durum"] = "onay" if kabul else "red"
    if kabul:
        b["oturum"] = _oturum_ac(b["ip"], b.get("cihaz", ""))
    return "Bağlantı onaylandı." if kabul else "Bağlantı reddedildi."


# --------------------------------------------------------------------------
# İstek denetimi
# --------------------------------------------------------------------------

def _yetki(request: Request, oturum: bool = True) -> Response | None:
    """None = geçti. Yoksa dönecek hata cevabı. oturum=False: sadece adres (sayfa/baglan/durum)."""
    simdi = time.monotonic()
    while _hatalar and simdi - _hatalar[0] > HATA_PENCERE:
        _hatalar.popleft()
    if len(_hatalar) >= HATA_LIMIT:
        return Response(status_code=429)
    if not token_dogru(request.path_params.get("token")):
        _hatalar.append(simdi)
        return Response(status_code=404)
    if kilit.kilitli:
        oturumlari_kes()
        return Response(status_code=403)
    if oturum and not _oturum_gecerli(request):
        _hatalar.append(simdi)  # oturumsuz deneme de sayılır
        return _hata(401, "Oturum yok ya da süresi doldu.")
    return None


def _ekran_adi(ham: Any) -> str:
    e = str(ham or "ana").strip().lower()
    return e if e in EKRANLAR else "ana"


def _hata(kod: int, mesaj: str) -> Response:
    return JSONResponse({"hata": mesaj}, status_code=kod, headers=BASLIKLAR)


# --------------------------------------------------------------------------
# Bağlantı uçları
# --------------------------------------------------------------------------

async def baglan(request: Request) -> Response:
    """POST .../baglan {b: bilet}: bilet geçerliyse oturum; değilse sohbet onayı bekle."""
    if (red := _yetki(request, oturum=False)) is not None:
        return red
    simdi = time.monotonic()
    while _baglanlar and simdi - _baglanlar[0] > BAGLAN_PENCERE:
        _baglanlar.popleft()
    if len(_baglanlar) >= BAGLAN_LIMIT:
        return _hata(429, "Çok fazla deneme, biraz bekleyin.")
    _baglanlar.append(simdi)
    try:
        govde = await request.json()
        bilet = str(govde.get("b") or "")[:80]
        model = govde.get("m") or ""
    except (ValueError, TypeError, AttributeError):
        bilet, model = "", ""
    ip = _ip(request)
    cihaz = _cihaz(request, model)
    if _bilet_gecerli(bilet):
        sid = _oturum_ac(ip, cihaz)
        await _bildir(f"Uzak ekran bağlandı.\nCihaz: {cihaz}\nIP: {ip}", [("Tüm bağlantıları kes", "uzak:kes")])
        return JSONResponse({"oturum": sid}, headers=BASLIKLAR)
    _temizle()
    if sum(1 for b in _bekleyen.values() if b["durum"] == "bekliyor") >= MAKS_BEKLEYEN:
        return _hata(429, "Bekleyen istek çok, biraz bekleyin.")
    onay_id = secrets.token_urlsafe(9)
    _bekleyen[onay_id] = {"olus": simdi, "durum": "bekliyor", "oturum": None, "ip": ip, "cihaz": cihaz}
    gitti = await _bildir(
        f"Uzak ekran bağlantı isteği.\nCihaz: {cihaz}\nIP: {ip}\nSiz miydiniz? 2 dakika içinde cevaplayın.",
        [("Onayla", f"uzak:onay:{onay_id}"), ("Reddet", f"uzak:red:{onay_id}")])
    if not gitti:  # Bildirim gidemiyorsa kimse onaylayamaz: kapalı kal
        _bekleyen.pop(onay_id, None)
        return _hata(503, "Onay istenemedi, daha sonra deneyin.")
    return JSONResponse({"bekle": onay_id}, headers=BASLIKLAR)


async def durum(request: Request) -> Response:
    """GET .../durum?id=: onay beklenirken yoklanır. Oturum kimliği SADECE BİR KEZ verilir."""
    if (red := _yetki(request, oturum=False)) is not None:
        return red
    b = _bekleyen.get(str(request.query_params.get("id") or ""))
    if not b or time.monotonic() - b["olus"] > ONAY_SN:
        return JSONResponse({"durum": "yok"}, headers=BASLIKLAR)
    if b["durum"] == "onay" and b["oturum"]:
        sid, b["oturum"] = b["oturum"], None
        return JSONResponse({"durum": "onay", "oturum": sid}, headers=BASLIKLAR)
    return JSONResponse({"durum": b["durum"]}, headers=BASLIKLAR)


async def kes(request: Request) -> Response:
    """POST .../kes: bu oturumu kapat."""
    if (red := _yetki(request, oturum=False)) is not None:
        return red
    aday = request.headers.get("x-oturum", "")
    for sid in list(_oturumlar):
        if aday and hmac.compare_digest(sid.encode(), aday.encode()):
            o = _oturumlar.pop(sid)
            await _bildir(f"Uzak ekran bağlantısı kesildi.\nCihaz: {o.get('cihaz') or 'bilinmiyor'}\nIP: {o['ip']}", [])
    return JSONResponse({"tamam": True}, headers=BASLIKLAR)


# --------------------------------------------------------------------------
# Ekran + eylem
# --------------------------------------------------------------------------

def _kare_cevabi(kare: dict[str, Any], istemci_hash: str = "") -> Response:
    basliklar = {**BASLIKLAR, "X-Hash": kare["hash"],
                 "X-Aktif": json.dumps(kare["aktif"], ensure_ascii=True)[:300],
                 "Access-Control-Expose-Headers": "X-Hash, X-Aktif"}
    if istemci_hash and istemci_hash == kare["hash"]:
        return Response(status_code=204, headers=basliklar)
    return Response(content=kare["png"], media_type="image/png", headers=basliklar)


def _kareyi_kaydet(ekran: str, ozet: str, resim: bytes) -> dict[str, Any]:
    try:
        bilgi = json.loads(ozet)
    except (ValueError, TypeError):
        bilgi = {}
    aktif = bilgi.get("aktif") or {}
    kare = {"png": resim, "hash": hashlib.sha1(resim).hexdigest()[:16], "alan": bilgi.get("alan"),
            "aktif": {"baslik": str(aktif.get("baslik") or "")[:80], "surec": str(aktif.get("program") or "")[:40]},
            "zaman": time.monotonic()}
    _kare[ekran] = kare
    return kare


async def _ajana_sor(tool: str, arg: dict[str, Any], ekran: str) -> tuple[dict[str, Any] | None, str]:
    basarili, ozet, resim = await gorevler.calistir_ekli(tool, arg, onayli=True)
    if not basarili or resim is None:
        return None, ozet if not basarili else "Ekran görüntüsü gelmedi."
    return _kareyi_kaydet(ekran, ozet, resim), ""


async def ekran(request: Request) -> Response:
    """GET .../ekran?e=ana&h=<hash>: güncel kare (ya da 204 = değişmedi)."""
    if (red := _yetki(request)) is not None:
        return red
    e = _ekran_adi(request.query_params.get("e"))
    h = str(request.query_params.get("h") or "")
    eski = _kare.get(e)
    if eski and time.monotonic() - eski["zaman"] < TAZE_SN:
        return _kare_cevabi(eski, h)
    async with _cekim:  # aynı anda tek yakalama; bekleyenler yeni kareyi paylaşır
        eski = _kare.get(e)
        if eski and time.monotonic() - eski["zaman"] < TAZE_SN:
            return _kare_cevabi(eski, h)
        kare, hata = await _ajana_sor("bilgisayar_bak", {"ekran": e}, e)
    if kare is None:
        return _hata(503, hata)
    return _kare_cevabi(kare, h)


def _eylem(govde: dict[str, Any], alan: dict[str, Any] | None) -> dict[str, Any]:
    tur = str(govde.get("tur") or "")
    if tur == "tikla":
        try:
            x, y = float(govde.get("x")), float(govde.get("y"))
        except (TypeError, ValueError):
            raise ValueError("Tık konumu geçersiz.") from None
        if not (0 <= x <= 1000 and 0 <= y <= 1000):
            raise ValueError("Tık konumu ekran dışında.")
        e: dict[str, Any] = {"tur": "tikla", "x": x, "y": y,
                             "tus": "sag" if govde.get("tus") == "sag" else "sol", "cift": bool(govde.get("cift"))}
        if alan:
            e["alan"] = alan
        return e
    if tur == "yaz":
        metin = str(govde.get("metin") or "")[:2000]
        if not metin:
            raise ValueError("Yazılacak metin boş.")
        return {"tur": "yaz", "metin": metin}
    if tur == "tus":
        tuslar = str(govde.get("tuslar") or "").strip()[:60]
        if not tuslar:
            raise ValueError("Tuş boş.")
        return {"tur": "tus", "tuslar": tuslar}
    if tur == "kaydir":
        return {"tur": "kaydir", "yon": "yukari" if govde.get("yon") == "yukari" else "asagi", "miktar": 3}
    raise ValueError("Bilinmeyen eylem.")


async def eylem(request: Request) -> Response:
    """POST .../eylem: tek eylem (tikla/yaz/tus/kaydir), sonra yeni kareyi döner."""
    if (red := _yetki(request)) is not None:
        return red
    try:
        govde = await request.json()
        e = _ekran_adi(govde.get("e"))
        eylemi = _eylem(govde, (_kare.get(e) or {}).get("alan"))
    except (ValueError, TypeError, AttributeError) as ex:
        return _hata(400, str(ex) or "Geçersiz istek.")
    try:
        await asyncio.wait_for(gorevler.PC_KILIDI.acquire(), KILIT_BEKLE_SN)
    except asyncio.TimeoutError:
        return _hata(409, "OpenDelegate şu an PC'de çalışıyor, sonra tekrar dene.")
    try:
        kare, hata = await _ajana_sor("bilgisayar_adim", {"eylemler": [eylemi], "ekran": e, "bekle": EYLEM_BEKLE}, e)
    finally:
        gorevler.PC_KILIDI.release()
    if kare is None:
        return _hata(503, hata)
    logger.info("Uzak ekran eylemi: %s", eylemi["tur"])
    return _kare_cevabi(kare)


_sayfa_onbellek: dict[str, tuple[float, str]] = {}


def _sayfa_metni() -> str:
    mtime = SAYFA_DOSYASI.stat().st_mtime
    kayit = _sayfa_onbellek.get("s")
    if not kayit or kayit[0] != mtime:
        kayit = (mtime, SAYFA_DOSYASI.read_text(encoding="utf-8"))
        _sayfa_onbellek["s"] = kayit
    return kayit[1]


async def sayfa(request: Request) -> Response:
    if (red := _yetki(request, oturum=False)) is not None:
        return red
    return HTMLResponse(_sayfa_metni(), headers=SAYFA_BASLIKLARI)


def rotalar() -> list[BaseRoute]:
    """main.py'nin rota listesine eklenir. Bot token'ı yoksa (adres türetilemez) hiç rota yok."""
    if not token():
        return []
    k = yol() + "/{token}"
    return [
        Route(k, sayfa, methods=["GET"]),
        Route(k + "/baglan", baglan, methods=["POST"]),
        Route(k + "/durum", durum, methods=["GET"]),
        Route(k + "/kes", kes, methods=["POST"]),
        Route(k + "/ekran", ekran, methods=["GET"]),
        Route(k + "/eylem", eylem, methods=["POST"]),
    ]
