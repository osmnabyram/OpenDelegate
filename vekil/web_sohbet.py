"""Web sohbeti: Telegram'a gerek kalmadan tarayıcıdan Vekil ile konuşma.

Üç parça:
  - Giriş: parola (+ isteğe bağlı TOTP), süreli HttpOnly çerez, yanlış denemede bekleme.
  - WebBot: Telegram `Bot` arayüzünün taklidi. Mevcut ajan kodu ona yazar, mesajlar sayfaya olay olarak gider.
  - Rotalar: /sohbet sayfası, olay akışı (uzun yoklama), mesaj ve düğme uçları.

Güvenlik: yanlış giriş hep aynı cevabı verir; durum değiştiren her istek oturum çerezi + `X-OD` başlığı ister
(başka sitenin formu bu başlığı koyamaz); sayfa betikleri ayrı dosyadır ve CSP `script-src 'self'` ile sınırlıdır;
Vekil'in HTML'i beyaz listeden süzülür (script, img, olay özellikleri atılır).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import mimetypes
import re
import secrets
import struct
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import config

STATIK = Path(__file__).with_name("static")
SAYFA_DOSYALARI = {"sohbet.js": "text/javascript; charset=utf-8", "sohbet.css": "text/css; charset=utf-8"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
MAKS_GOVDE = 64 * 1024
MAKS_METIN = 8000
MAKS_MEDYA = 20  # bellekte tutulan son medya sayısı
MAKS_MEDYA_BAYT = 25 * 1024 * 1024


# --------------------------------------------------------------------------
# TOTP (RFC 6238, SHA-1, 6 hane, 30 sn): Google Authenticator ile uyumlu, yeni paket yok
# --------------------------------------------------------------------------

def totp_uret(sir: str, an: float | None = None) -> str:
    anahtar = base64.b32decode(sir + "=" * (-len(sir) % 8))
    sayac = struct.pack(">Q", int((time.time() if an is None else an) // 30))
    ozet = hmac.new(anahtar, sayac, "sha1").digest()
    o = ozet[-1] & 15
    return f"{(struct.unpack('>I', ozet[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


def totp_dogru(sir: str, kod: str, an: float | None = None) -> bool:
    simdi = time.time() if an is None else an
    kod = (kod or "").strip().replace(" ", "")
    try:
        adaylar = [totp_uret(sir, simdi + k * 30) for k in (-1, 0, 1)]  # saat kayması için bir adım tolerans
    except Exception:  # noqa: BLE001 - bozuk base32 sır: giriş hiç açılmaz
        return False
    ok = False
    for a in adaylar:
        ok |= hmac.compare_digest(a.encode(), kod.encode())
    return ok


# --------------------------------------------------------------------------
# Giriş, oturum, deneme sınırı
# --------------------------------------------------------------------------

class Oturumlar:
    """Bellekte tutulur: sunucu yeniden başlarsa herkes tekrar giriş yapar (güvenli yön)."""

    def __init__(self) -> None:
        self._sureler: dict[str, float] = {}

    def ac(self) -> str:
        sid = secrets.token_urlsafe(32)
        self._sureler[sid] = time.time() + config.WEB_OTURUM_SAAT * 3600
        return sid

    def gecerli(self, sid: str | None) -> bool:
        if not sid:
            return False
        bitis = self._sureler.get(sid)
        if bitis is None:
            return False
        if bitis < time.time():
            self._sureler.pop(sid, None)
            return False
        return True

    def kapat(self, sid: str | None) -> None:
        self._sureler.pop(sid or "", None)


class DenemeSiniri:
    """Başarısız girişleri sayar. IP başına 5, genelde 30; dolunca 15 dakika kapalı."""

    def __init__(self, ip_limit: int = 5, genel_limit: int = 30, bekleme: float = 900.0) -> None:
        self.ip_limit, self.genel_limit, self.bekleme = ip_limit, genel_limit, bekleme
        self._ip: dict[str, list[float]] = {}
        self._genel: list[float] = []

    def _temizle(self, simdi: float) -> None:
        self._genel = [t for t in self._genel if simdi - t < self.bekleme]
        for ip in list(self._ip):
            self._ip[ip] = [t for t in self._ip[ip] if simdi - t < self.bekleme]
            if not self._ip[ip]:
                del self._ip[ip]

    def izin_var(self, ip: str, simdi: float | None = None) -> bool:
        simdi = time.time() if simdi is None else simdi
        self._temizle(simdi)
        return len(self._ip.get(ip, ())) < self.ip_limit and len(self._genel) < self.genel_limit

    def basarisiz(self, ip: str, simdi: float | None = None) -> None:
        simdi = time.time() if simdi is None else simdi
        self._ip.setdefault(ip, []).append(simdi)
        self._genel.append(simdi)

    def basarili(self, ip: str) -> None:
        self._ip.pop(ip, None)


def istemci_ip(request: Request) -> str:
    """Render'ın proxy'si gerçek IP'yi X-Forwarded-For'un SONUNA ekler; baştaki değerler sahte olabilir."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()[:64]
    return request.client.host if request.client else "?"


def parola_dogru(parola: str) -> bool:
    if not config.WEB_PAROLA:
        return False
    return hmac.compare_digest(hashlib.sha256((parola or "").encode()).digest(),
                               hashlib.sha256(config.WEB_PAROLA.encode()).digest())


# --------------------------------------------------------------------------
# HTML süzgeci: Vekil'in (Telegram HTML'i) mesajı sayfaya güvenle girer
# --------------------------------------------------------------------------

class _Suzgec(HTMLParser):
    IZINLI = {"b", "strong", "i", "em", "u", "s", "code", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cikti: list[str] = []
        self._acik: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.IZINLI:
            self.cikti.append(f"<{tag}>")
            self._acik.append(tag)
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if re.match(r"https?://", href, re.I):
                self.cikti.append(f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">')
                self._acik.append("a")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._acik:
            while self._acik:
                son = self._acik.pop()
                self.cikti.append(f"</{son}>")
                if son == tag:
                    break

    def handle_data(self, data: str) -> None:
        self.cikti.append(html.escape(data))

    def sonuc(self) -> str:
        while self._acik:
            self.cikti.append(f"</{self._acik.pop()}>")
        return "".join(self.cikti)


def guvenli_html(metin: str, html_mi: bool) -> str:
    if not html_mi:
        return html.escape(metin or "")
    s = _Suzgec()
    s.feed(metin or "")
    s.close()
    return s.sonuc()


# --------------------------------------------------------------------------
# WebBot: Telegram Bot arayüzünün taklidi
# --------------------------------------------------------------------------

def _dugmeler(reply_markup: Any) -> list[list[dict[str, str]]]:
    satirlar = getattr(reply_markup, "inline_keyboard", None) or ()
    cikti = []
    for satir in satirlar:
        d = [{"yazi": str(b.text), "veri": str(b.callback_data)}
             for b in satir if getattr(b, "callback_data", None)]
        if d:
            cikti.append(d)
    return cikti


def _bayt(dosya: Any) -> tuple[bytes, str]:
    """bytes, InputFile ya da dosya benzeri nesne -> (bayt, ad)."""
    ad = getattr(dosya, "filename", None) or ""
    if isinstance(dosya, (bytes, bytearray)):
        return bytes(dosya), ad
    icerik = getattr(dosya, "input_file_content", None)
    if icerik is not None:
        return bytes(icerik), ad
    if hasattr(dosya, "read"):
        return bytes(dosya.read()), ad or getattr(dosya, "name", "") or ""
    raise TypeError("desteklenmeyen dosya türü")


def _mime(veri: bytes, ad: str) -> str:
    if veri[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if veri[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if veri[:4] == b"RIFF" and veri[8:12] == b"WEBP":
        return "image/webp"
    return mimetypes.guess_type(ad)[0] or "application/octet-stream"


class WebMesaj:
    """send_message'ın döndürdüğü: onay akışı `.text_html` okur ve `.edit_text` ile düzenler."""

    def __init__(self, bot: "WebBot", mesaj_id: int, metin: str, html_mi: bool = False) -> None:
        self._bot, self.message_id, self.text, self.text_html = bot, mesaj_id, metin, metin
        self._html_mi = html_mi

    async def edit_reply_markup(self, reply_markup: Any = None) -> "WebMesaj":
        return await self.edit_text(self.text_html, "HTML" if self._html_mi else None, reply_markup)

    async def edit_text(self, metin: str, parse_mode: Any = None, reply_markup: Any = None, **kw: Any) -> "WebMesaj":
        self.text = self.text_html = metin
        self._html_mi = bool(parse_mode)
        self._bot._ekle({"tur": "duzenle", "hedef": self.message_id,
                         "metin": guvenli_html(metin, bool(parse_mode)), "dugmeler": _dugmeler(reply_markup)})
        return self

    async def delete(self) -> None:
        self._bot._ekle({"tur": "sil", "hedef": self.message_id})


class WebBot:
    def __init__(self) -> None:
        self.olaylar: deque[dict[str, Any]] = deque(maxlen=500)
        self.no = 0
        self._medya: dict[str, tuple[bytes, str, str]] = {}
        self.mesajlar: dict[int, WebMesaj] = {}  # düğmeli mesaja düğme tıklanınca ulaşmak için
        self._yaziyor = 0.0

    def _ekle(self, olay: dict[str, Any]) -> int:
        self.no += 1
        olay["id"] = self.no
        olay["an"] = int(time.time())
        self.olaylar.append(olay)
        return self.no

    def yaziyor_mu(self) -> bool:
        return time.time() - self._yaziyor < 6

    def olaylar_sonrasi(self, son: int) -> list[dict[str, Any]]:
        return [o for o in self.olaylar if o["id"] > son]

    def dugme_mesaji(self, veri: str) -> WebMesaj | None:
        """Bu düğme verisini taşıyan en yeni mesaj."""
        for o in reversed(self.olaylar):
            if any(d["veri"] == veri for satir in o.get("dugmeler") or () for d in satir):
                return self.mesajlar.get(o.get("hedef", o["id"]))
        return None

    def kullanici_yazdi(self, metin: str) -> None:
        self._ekle({"tur": "kullanici", "metin": html.escape(metin)})

    async def send_message(self, chat_id: Any, text: str, parse_mode: Any = None, reply_markup: Any = None,
                           **kw: Any) -> WebMesaj:
        metin = str(text)
        no = self._ekle({"tur": "mesaj", "metin": guvenli_html(metin, bool(parse_mode)),
                         "dugmeler": _dugmeler(reply_markup)})
        m = WebMesaj(self, no, metin, bool(parse_mode))
        self.mesajlar[no] = m
        while len(self.mesajlar) > 200:
            self.mesajlar.pop(next(iter(self.mesajlar)))
        return m

    async def _medya_gonder(self, tur: str, dosya: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        veri, ad = _bayt(dosya)
        if len(veri) > MAKS_MEDYA_BAYT:
            return await self.send_message(0, "(Dosya çok büyük, web sohbetinde gösterilemedi.)")
        mid = secrets.token_urlsafe(12)
        ad = kw.get("filename") or ad or f"{tur}"
        self._medya[mid] = (veri, _mime(veri, ad), ad)
        while len(self._medya) > MAKS_MEDYA:
            self._medya.pop(next(iter(self._medya)))
        no = self._ekle({"tur": "medya", "cins": tur, "url": f"/sohbet/medya/{mid}", "ad": html.escape(ad),
                         "mime": self._medya[mid][1], "altyazi": html.escape(caption or "")})
        return WebMesaj(self, no, caption or "")

    async def send_photo(self, chat_id: Any, photo: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        return await self._medya_gonder("foto", photo, caption, **kw)

    async def send_document(self, chat_id: Any, document: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        return await self._medya_gonder("dosya", document, caption, **kw)

    async def send_voice(self, chat_id: Any, voice: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        return await self._medya_gonder("ses", voice, caption, **kw)

    async def send_audio(self, chat_id: Any, audio: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        return await self._medya_gonder("ses", audio, caption, **kw)

    async def send_video(self, chat_id: Any, video: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        return await self._medya_gonder("video", video, caption, **kw)

    async def send_animation(self, chat_id: Any, animation: Any, caption: str | None = None, **kw: Any) -> WebMesaj:
        return await self._medya_gonder("video", animation, caption, **kw)

    async def send_chat_action(self, chat_id: Any, action: Any = None, **kw: Any) -> None:
        self._yaziyor = time.time()

    async def delete_messages(self, chat_id: Any, message_ids: Any = None, **kw: Any) -> None:
        self.olaylar.clear()
        self._medya.clear()
        self.mesajlar.clear()
        self._ekle({"tur": "temizle"})

    async def set_my_commands(self, *a: Any, **kw: Any) -> None:
        return None

    async def get_file(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError("web sohbetinde dosya yükleme yok")

    def medya(self, mid: str) -> tuple[bytes, str, str] | None:
        return self._medya.get(mid)


web_bot = WebBot()
oturumlar = Oturumlar()
deneme_siniri = DenemeSiniri()


# --------------------------------------------------------------------------
# Rotalar
# --------------------------------------------------------------------------

def _json(veri: Any, durum: int = 200) -> JSONResponse:
    return JSONResponse(veri, status_code=durum, headers={"Cache-Control": "no-store", "Content-Security-Policy": CSP})


def _giris_var(request: Request) -> bool:
    return oturumlar.gecerli(request.cookies.get("od_oturum"))


def _yazma_izni(request: Request) -> bool:
    """Durum değiştiren istek: oturum + özel başlık + (varsa) aynı kaynaktan Origin."""
    if not _giris_var(request) or request.headers.get("x-od") != "1":
        return False
    origin = request.headers.get("origin")
    return origin is None or origin.split("://", 1)[-1] == request.headers.get("host", "")


async def _govde(request: Request) -> dict[str, Any] | None:
    ham = await request.body()
    if len(ham) > MAKS_GOVDE:
        return None
    try:
        veri = json.loads(ham or b"{}")
    except ValueError:
        return None
    return veri if isinstance(veri, dict) else None


def rotalar(mesaj_isle: Callable[[str], Awaitable[None]], dugme_isle: Callable[[str], Awaitable[None]]) -> list[Route]:
    """Web sohbeti kapalıysa (WEB_PAROLA boş) hiç rota eklenmez: /sohbet 404 verir."""
    if not config.WEB_PAROLA:
        return []
    arka: set[asyncio.Task[None]] = set()

    def baslat(coro: Awaitable[None]) -> None:
        t = asyncio.ensure_future(coro)
        arka.add(t)
        t.add_done_callback(arka.discard)

    async def sayfa(request: Request) -> Response:
        return Response((STATIK / "sohbet.html").read_text(encoding="utf-8"), media_type="text/html; charset=utf-8",
                        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store"})

    async def dosya(request: Request) -> Response:
        ad = request.path_params["ad"]
        if ad not in SAYFA_DOSYALARI:
            return Response(status_code=404)
        return Response((STATIK / ad).read_bytes(), media_type=SAYFA_DOSYALARI[ad],
                        headers={"Cache-Control": "no-cache"})

    async def ben(request: Request) -> Response:
        return _json({"giris": _giris_var(request), "totp": bool(config.WEB_TOTP_SIR)})

    async def giris(request: Request) -> Response:
        ip = istemci_ip(request)
        if not deneme_siniri.izin_var(ip):
            return _json({"hata": "Çok fazla yanlış deneme. 15 dakika sonra tekrar deneyin."}, 429)
        veri = await _govde(request)
        if veri is None or request.headers.get("x-od") != "1":
            return _json({"hata": "Geçersiz istek."}, 400)
        p_ok = parola_dogru(str(veri.get("parola", "")))
        k_ok = totp_dogru(config.WEB_TOTP_SIR, str(veri.get("kod", ""))) if config.WEB_TOTP_SIR else True
        if not (p_ok and k_ok):
            deneme_siniri.basarisiz(ip)
            return _json({"hata": "Bilgiler yanlış."}, 401)
        deneme_siniri.basarili(ip)
        yanit = _json({"tamam": True})
        guvenli = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        yanit.set_cookie("od_oturum", oturumlar.ac(), max_age=config.WEB_OTURUM_SAAT * 3600, httponly=True,
                         secure=guvenli, samesite="strict", path="/")
        return yanit

    async def cikis(request: Request) -> Response:
        if not _yazma_izni(request):
            return _json({"hata": "Yetkisiz."}, 403)
        oturumlar.kapat(request.cookies.get("od_oturum"))
        yanit = _json({"tamam": True})
        yanit.delete_cookie("od_oturum", path="/")
        return yanit

    async def olaylar(request: Request) -> Response:
        if not _giris_var(request):
            return _json({"hata": "Giriş gerekli."}, 401)
        try:
            son = int(request.query_params.get("son", "0"))
        except ValueError:
            son = 0
        bitis = time.time() + 20
        while web_bot.no <= son and time.time() < bitis:  # uzun yoklama: yeni olay gelince hemen döner
            await asyncio.sleep(0.4)
            if not _giris_var(request):
                break
        return _json({"olaylar": web_bot.olaylar_sonrasi(son), "son": web_bot.no, "yaziyor": web_bot.yaziyor_mu()})

    async def mesaj(request: Request) -> Response:
        if not _yazma_izni(request):
            return _json({"hata": "Yetkisiz."}, 403)
        veri = await _govde(request)
        metin = str((veri or {}).get("metin", "")).strip()
        if not metin or len(metin) > MAKS_METIN:
            return _json({"hata": "Mesaj boş ya da çok uzun."}, 400)
        baslat(mesaj_isle(metin))
        return _json({"tamam": True}, 202)

    async def dugme(request: Request) -> Response:
        if not _yazma_izni(request):
            return _json({"hata": "Yetkisiz."}, 403)
        veri = await _govde(request)
        d = str((veri or {}).get("veri", ""))
        if not d or len(d) > 200:
            return _json({"hata": "Geçersiz."}, 400)
        baslat(dugme_isle(d))
        return _json({"tamam": True}, 202)

    async def medya(request: Request) -> Response:
        if not _giris_var(request):
            return Response(status_code=404)
        kayit = web_bot.medya(request.path_params["mid"])
        if kayit is None:
            return Response(status_code=404)
        veri, mime, ad = kayit
        gomulu = mime.startswith(("image/", "audio/", "video/")) and mime != "image/svg+xml"
        if not gomulu:
            mime = "application/octet-stream"
        ad_guvenli = re.sub(r"[^\w.\- ]", "_", ad)[:80] or "dosya"
        return Response(veri, media_type=mime, headers={
            "Content-Disposition": f'{"inline" if gomulu else "attachment"}; filename="{ad_guvenli}"',
            "Content-Security-Policy": "default-src 'none'; sandbox", "Cache-Control": "private, no-store"})

    return [
        Route("/sohbet", sayfa, methods=["GET"]),
        Route("/sohbet/dosya/{ad}", dosya, methods=["GET"]),
        Route("/sohbet/ben", ben, methods=["GET"]),
        Route("/sohbet/giris", giris, methods=["POST"]),
        Route("/sohbet/cikis", cikis, methods=["POST"]),
        Route("/sohbet/olaylar", olaylar, methods=["GET"]),
        Route("/sohbet/mesaj", mesaj, methods=["POST"]),
        Route("/sohbet/dugme", dugme, methods=["POST"]),
        Route("/sohbet/medya/{mid}", medya, methods=["GET"]),
    ]
