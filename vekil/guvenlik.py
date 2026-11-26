"""Ortak güvenlik kapıları (kodda; modelin prompt'una güvenilmez).

- token_esit: sabit zamanlı token karşılaştırma (sesli uçlar).
- SesliMaskeleyici: sesli token'ı log satırlarında gizler (URL yolunda gidiyor, uvicorn.access yazar).
- odeme_gorevi / odeme_ekrani / banka_uygulamasi: telefondan para/ödeme işine dokunmayı keser.
  Kullanıcı 23.11: "ödeme hakkında beni gerçek etkileyebilecek her şeyde sınır; 'yapamam' desin".
"""

from __future__ import annotations

import logging
import os
import re
import secrets

import config

ODEME_RED = "Ödeme ve para işlerine telefondan dokunamam efendim, onları siz yapın."


def token_esit(gelen: str, beklenen: str) -> bool:
    """Sabit zamanlı; boş beklenen değer her zaman reddedilir."""
    if not beklenen:
        return False
    return secrets.compare_digest(str(gelen).encode("utf-8", "replace"), beklenen.encode("utf-8"))


class SesliMaskeleyici(logging.Filter):
    def filter(self, kayit: logging.LogRecord) -> bool:
        t = config.SESLI_TOKEN
        if t:
            try:
                mesaj = kayit.getMessage()
            except Exception:  # noqa: BLE001
                return True
            if t in mesaj:
                kayit.msg, kayit.args = mesaj.replace(t, t[:4] + "…"), ()
        return True


def _kucuk(metin: str) -> str:
    return (metin or "").replace("İ", "i").replace("I", "ı").lower()


# Görev cümlesi: para çıkaran FİİLLER. "ödeme günüm ne zaman" gibi bilgi soruları buraya girmez (ekranda değil).
_GOREV = re.compile(
    r"\böde(?!v)\w*|\bhavale\b|\beft\b|\bpara\s+(gönder|yolla|at|çek|transfer)|\bpara\s+aktar"
    r"|satın\s*al|\bsipariş\s+ver|\bkredi\s+kartı|\bkart\s+(numara|bilgi)|\bcvv\b|\b[ıi]ban\b|\bbahşiş|\bbağış"
    r"|\bfatura\s+öde|\bsepeti\s+onayla|\babone\s+ol|\bcoin\b|\bkripto|\bhisse\s+(al|sat)")
# Ekran: ödeme formu/onay izleri. Sohbette tek başına "ödeme" geçmesi durdurmaz; form/onay ifadesi arar.
_EKRAN = re.compile(
    r"\bcvv\b|\bcvc\b|güvenlik\s+kodu|kart\s+numaras|son\s+kullanma|\b[ıi]ban\b|ödemeyi\s+(onayla|tamamla)"
    r"|ödeme\s+(yap|yöntem|bilgi|ekran|onay)|\bsatın\s+al\b|siparişi\s+(onayla|tamamla)|\bhavale\b|\beft\b"
    r"|para\s+gönder|\bgönderimi\s+onayla|sepeti\s+onayla|\bpay\b|\bcheckout\b|tutar.*onayla")
# Uygulama adları (ekranın "Uygulama:" satırı ve uygulama_ac adı).
_BANKA = re.compile(
    r"ziraat|garanti|işcep|iş\s*bankas|akbank|yapı\s*kredi|yapıkredi|halkbank|vakıf|denizbank|qnb|enpara|papara"
    r"|ininal|tosla|paycell|\bfups\b|param\b|binance|btcturk|paribu|paypal|cüzdan|wallet|google\s*pay"
    r"|google\s*play|play\s*store|banka|\bbank\b|finansbank|ing\b|teb\b|şekerbank|kuveyt|albaraka|ziraat|odeabank|burgan")


def odeme_gorevi(gorev: str) -> bool:
    return bool(_GOREV.search(_kucuk(gorev)))


def banka_uygulamasi(ad: str) -> bool:
    return bool(_BANKA.search(_kucuk(ad)))


def odeme_ekrani(ekran: str) -> bool:
    """Ekran metni: ilk satır 'Uygulama: X' banka/cüzdan ise ya da ödeme formu izi varsa."""
    ilk, _, geri = (ekran or "").partition("\n")
    if ilk.lower().startswith("uygulama:") and banka_uygulamasi(ilk[9:]):
        return True
    return bool(_EKRAN.search(_kucuk(geri)))


# --------------------------------------------------------------------------
# Genel sertleştirme (23.11): başlıklar, hız sınırı, gövde sınırı, log maskesi, açılış denetimi
# --------------------------------------------------------------------------

import time
from collections import deque
from typing import Callable

GUVENLI_BASLIKLAR = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000",
}


class BaslikEkleyici:
    """ASGI ara katmanı: her cevaba güvenli başlıklar ekler; rotanın kendi koyduğunu ezmez."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def gonder(mesaj):
            if mesaj["type"] == "http.response.start":
                mevcut = {k.lower() for k, _ in mesaj.get("headers", [])}
                ek = [(k.lower().encode(), v.encode()) for k, v in GUVENLI_BASLIKLAR.items()
                      if k.lower().encode() not in mevcut]
                mesaj = {**mesaj, "headers": list(mesaj.get("headers", [])) + ek}
            await send(mesaj)

        await self.app(scope, receive, gonder)


class HizSiniri:
    """Kayan pencere: `pencere_sn` içinde en çok `limit` çağrı. Token sızsa bile kota/maliyet kaçmasın."""

    def __init__(self, limit: int, pencere_sn: float = 60.0, saat: Callable[[], float] = time.monotonic):
        self.limit, self.pencere, self._saat = limit, pencere_sn, saat
        self._olaylar: deque[float] = deque()

    def izin_var(self) -> bool:
        simdi = self._saat()
        while self._olaylar and simdi - self._olaylar[0] > self.pencere:
            self._olaylar.popleft()
        if len(self._olaylar) >= self.limit:
            return False
        self._olaylar.append(simdi)
        return True


# Kullanıcının normal kullanımının (dakikada birkaç istek) çok üstünde; döngüye giren ya da çalınmış anahtarı keser.
uygulama_siniri = HizSiniri(limit=90)


def govde_cok_buyuk(request, azami: int) -> bool:
    """Content-Length sınırı aşıyor ya da bozuk mu? (gövde okunmadan bakılır)"""
    try:
        return int(request.headers.get("content-length") or 0) > azami
    except ValueError:
        return True


_SIR_DESENLERI = [
    (re.compile(r"(?<!\d)\d{8,10}:AA[A-Za-z0-9_-]{30,}"), "<telegram-token>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "<api-key>"),
    (re.compile(r"(?i)\b(bearer|authorization:?)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 <gizli>"),
    (re.compile(r"(?i)(x-(?:ajan|kopru|telegram-bot-api)-[a-z-]*(?:secret|token)['\"]?[:=]\s*['\"]?)[^\s'\",]{8,}"),
     r"\1<gizli>"),
]


def sir_maskele(metin: str) -> str:
    for desen, yerine in _SIR_DESENLERI:
        metin = desen.sub(yerine, metin)
    return metin


class SirMaskeleyici(logging.Filter):
    """Log satırlarındaki bilinen sır biçimlerini (bot token'ı, API anahtarı, Bearer) gizler."""

    def filter(self, kayit: logging.LogRecord) -> bool:
        try:
            mesaj = kayit.getMessage()
        except Exception:  # noqa: BLE001
            return True
        temiz = sir_maskele(mesaj)
        if temiz != mesaj:
            kayit.msg, kayit.args = temiz, ()
        return True


def acilis_denetimi() -> list[str]:
    """Zayıf/eksik sır ayarlarını döner (sadece uyarı: çalışmayı kesmez). Değerler ASLA yazılmaz."""
    uyari = []
    if not config.WEBHOOK_SECRET or len(config.WEBHOOK_SECRET) < 16:
        uyari.append("WEBHOOK_SECRET kısa ya da boş")
    if not os.getenv("SESLI_TOKEN"):
        uyari.append("SESLI_TOKEN env'de yok: ana sırdan türetiliyor (ayrı rastgele değer daha iyi)")
    elif len(config.SESLI_TOKEN) < 32:
        uyari.append("SESLI_TOKEN 32 karakterden kısa")
    if getattr(config, "AJAN_SECRET", "") and len(config.AJAN_SECRET) < 24:
        uyari.append("AJAN_SECRET 24 karakterden kısa")
    if config.web_acik():
        if not config.KILIT_OZET and len(config.WEB_PAROLA) < 12:
            uyari.append("WEB_PAROLA 12 karakterden kısa")
        if not config.WEB_TOTP_SIR:
            uyari.append("WEB_TOTP_SIR boş: web sohbeti yalnızca şifreyle korunuyor (doğrulama uygulaması önerilir)")
    elif not config.TELEGRAM_BOT_TOKEN:
        uyari.append("Ne kys şifresi (KILIT_OZET) ne WEB_PAROLA ne TELEGRAM_BOT_TOKEN var: OpenDelegate'e yazılı erişim yolu yok (yalnızca telefon uygulaması)")
    return uyari


# Yazılan metinde kart/IBAN: ekran ajanı bunları alanlara yazmaz (model ele geçirilse bile).
_KART = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IBAN = re.compile(r"(?i)\bTR\s?\d{2}(?:\s?\d{4}){5}\s?\d{2}\b")


def _luhn(sayi: str) -> bool:
    toplam, cift = 0, False
    for ch in reversed(sayi):
        d = int(ch)
        if cift:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        toplam += d
        cift = not cift
    return toplam % 10 == 0


def hassas_metin_mi(metin: str) -> bool:
    """Kart numarası (Luhn tutan 13-19 hane) ya da TR IBAN içeriyor mu?"""
    if _IBAN.search(metin or ""):
        return True
    for m in _KART.finditer(metin or ""):
        sayi = re.sub(r"\D", "", m.group())
        if 13 <= len(sayi) <= 19 and _luhn(sayi):
            return True
    return False
