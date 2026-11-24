"""Sesli mesaj -> metin (Render'da çalışır; PC devreye girmez).

Groq'un Whisper API'si (OpenAI uyumlu /audio/transcriptions) kullanılır:
kartsız ücretsiz katman, Telegram'ın OGG/Opus sesini dönüştürmeden kabul eder.
Ses sadece bellekte tutulur; diske ya da veritabanına yazılmaz.
"""

from __future__ import annotations

import logging

import httpx

import ag
import config

logger = logging.getLogger("vekil.ses")

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class SesHatasi(Exception):
    """Kullanıcıya gösterilecek, sebebi belli hata."""


def _hata(yanit: httpx.Response) -> SesHatasi:
    kod = yanit.status_code
    if kod in (401, 403):
        return SesHatasi("Ses API key'i geçersiz (GROQ_API_KEY). Render env'deki key'i kontrol et.")
    if kod == 413:
        return SesHatasi(f"Ses dosyası çok büyük (limit {ag.boyut_yaz(config.MAKS_SES)}).")
    if kod == 429:
        return SesHatasi("Groq'un ücretsiz ses limiti doldu (dakikalık ya da günlük). Biraz sonra tekrar dene ya da yazarak sor.")
    if kod == 400:
        return SesHatasi("Groq bu sesi işleyemedi (bozuk ya da desteklenmeyen format).")
    return SesHatasi(f"Ses API hatası (HTTP {kod}).")


async def metne_cevir(veri: bytes, dosya_adi: str = "ses.ogg", tur: str = "audio/ogg", *,
                      model: str | None = None, ipucu: str = "") -> str:
    """Ses baytlarını metne çevirir. Hata durumunda SesHatasi.

    model/ipucu sadece telefon uygulaması için (daha isabetli model + Whisper'a sık kelimeler); Telegram
    sesli mesajı varsayılanla aynen çalışır."""
    if not config.GROQ_API_KEY:
        raise SesHatasi("Sesli mesaj kapalı: GROQ_API_KEY girilmemiş (Render → Environment). Şimdilik yazarak sor efendim.")
    if not veri:
        raise SesHatasi("Ses dosyası boş geldi.")
    if len(veri) > config.MAKS_SES:
        raise SesHatasi(f"Ses dosyası çok büyük ({ag.boyut_yaz(len(veri))}, limit {ag.boyut_yaz(config.MAKS_SES)}).")

    alanlar = {"model": model or config.STT_MODEL, "response_format": "json", "temperature": "0"}
    if config.STT_DIL:
        alanlar["language"] = config.STT_DIL
    if ipucu:
        alanlar["prompt"] = ipucu
    basliklar = {"Authorization": f"Bearer {config.GROQ_API_KEY}", "User-Agent": ag.TARAYICI}
    dosya = {"file": (dosya_adi, veri, tur)}

    async with ag._istemci(timeout=60) as istemci:
        try:
            yanit = await istemci.post(GROQ_STT_URL, data=alanlar, files=dosya, headers=basliklar)
        except httpx.TimeoutException:
            yanit = await istemci.post(GROQ_STT_URL, data=alanlar, files=dosya, headers=basliklar)  # bir kez daha
        except httpx.HTTPError as e:
            raise SesHatasi(f"Ses API'sine bağlanamadım ({type(e).__name__}).") from e
    if yanit.status_code >= 400:
        raise _hata(yanit)
    try:
        metin = str(yanit.json().get("text") or "").strip()
    except ValueError as e:
        raise SesHatasi("Ses API'si bozuk yanıt döndü.") from e
    if not metin:
        raise SesHatasi("Seste anlaşılır bir konuşma duyamadım efendim, tekrar dener misin?")
    return metin
