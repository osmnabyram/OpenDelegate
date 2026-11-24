"""Android sesli asistan endpoint'leri.

POST /dinle/{token}      — ses baytları (WAV/OGG/MP3) gönderilir, MP3 döner.
  Akış: Groq Whisper → Vekil beyni (arama.uygulama_cevabi) → edge-tts → MP3
POST /sor/{token}        — {"metin": ..., "sessiz": bool} yazılı soru (paneldeki klavye); sessizse ses üretilmez
POST /seslendir/{token}  — {"metin": ...} → MP3 (telefonda ekrandan yapılan işin sonucunu söylemek için)
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import Response

import config
import guvenlik
import ses as stt_mod
import seslendirme

logger = logging.getLogger("vekil.sesli")

# Uygulama kayda uyanma anından başlıyor (cümlenin başı kaçmasın diye): sesin başında "vekil", "bakar mısın"
# ya da sadece "mısın" kalabiliyor. Sadece EN BAŞTAKİ uyanma parçası atılır; "Bir alarm kur" gibi cümleler kalır.
_UYANMA = re.compile(
    r"^[\s,.:;!?]*(?:vekil\b[\s,.:;!?]*)?(?:(?:bir\s+)?bakar\s+)?(?:m[ıi]s[ıi]n(?:[ıi]z)?\b)?[\s,.:;!?]*",
    re.IGNORECASE)

# Whisper'a sık geçen adlar (yazımı doğru çıksın). Bilerek cümle DEĞİL: Whisper sessizlikte ipucunu aynen geri
# okuyabiliyor; iş isteyen bir örnek cümle ("ekran görüntüsü al...") istenmemiş bir işi başlatabilirdi.
_IPUCU = "Vekil, efendim, Telegram, OneDrive, alarm, fener, ekran görüntüsü."

# Whisper sessizlikte ya da gürültüde bunları uyduruyor (Türkçe altyazı verisinden); Vekil'e söylenmez.
# "Teşekkürler" burada YOK: Kullanıcı cevaptan sonra gerçekten diyebilir.
_UYDURMA = {"altyazı m.k.", "altyazı m.k", "altyazı: m.k.", "izlediğiniz için teşekkür ederim.",
            "izlediğiniz için teşekkürler.", "abone olmayı unutmayın."}


# Telefon kaydı birkaç saniyelik; bunun üstü kötüye kullanım (Groq kotası).
MAKS_SES_BAYT = 5_000_000


def _uydurma_mi(metin: str) -> bool:
    m = metin.strip().lower()
    # İpucunun büyük kısmını aynen geri okuduysa uydurmadır; tek cümlesini kullanıcı gerçekten söylemiş olabilir.
    return m in _UYDURMA or (len(m) >= 0.6 * len(_IPUCU) and m in _IPUCU.lower())


def _surum(request: Request) -> int:
    try:
        return int(request.headers.get("x-vekil-surum") or 1)
    except ValueError:
        return 1


# main.py kurulumda doldurur: telefon beynini (arama.Arama) döndürür.
beyin: Callable[[], Any] | None = None

# Art arda sorularda bağlam kalsın (tek kullanıcı, süreç ömrü boyunca).
_GECMIS: list[dict[str, Any]] = []
_GECMIS_SINIRI = 6
# 10 dk sessizlikten sonra yeni konu: saatler önceki soru yeni soruyu yanlış yönlendirmesin.
_GECMIS_OMUR_SN = 600.0
_son_soru = 0.0
_saat: Callable[[], float] = time.monotonic


async def sesli_dinle(request: Request) -> Response:
    token = request.path_params["token"]
    if not guvenlik.token_esit(token, config.SESLI_TOKEN):
        return Response("yetkisiz", status_code=401)

    if not guvenlik.uygulama_siniri.izin_var():
        return Response("çok sık istek", status_code=429)
    if not config.GROQ_API_KEY:
        return Response("GROQ_API_KEY eksik", status_code=503)

    if guvenlik.govde_cok_buyuk(request, MAKS_SES_BAYT):
        return Response("ses çok büyük", status_code=413)
    veri = await request.body()
    if not veri:
        return Response("ses boş", status_code=400)
    if len(veri) > MAKS_SES_BAYT:
        return Response("ses çok büyük", status_code=413)

    tur = request.headers.get("content-type", "audio/wav")
    uzanti = "ogg" if "ogg" in tur else "wav"

    t0 = time.perf_counter()
    try:
        metin = await stt_mod.metne_cevir(veri, dosya_adi=f"ses.{uzanti}", tur=tur,
                                          model=config.STT_TELEFON_MODEL, ipucu=_IPUCU)
    except stt_mod.SesHatasi as e:
        logger.warning("STT hata: %s", e)
        return Response(str(e), status_code=422)

    metin = _UYANMA.sub("", metin).strip()
    if not metin or _uydurma_mi(metin):
        return Response("anlaşılamadı", status_code=422)
    stt_sn = time.perf_counter() - t0
    logger.info("sesli süre: stt=%.2fs", stt_sn)
    return await _cevapla(request, metin, sessiz=False)


async def sesli_sor(request: Request) -> Response:
    """Paneldeki klavyeden yazılı soru: ses tanıma yok; sessizse cevap sesi de üretilmez (sadece yazı)."""
    if not guvenlik.token_esit(request.path_params["token"], config.SESLI_TOKEN):
        return Response("yetkisiz", status_code=401)
    if not guvenlik.uygulama_siniri.izin_var():
        return Response("çok sık istek", status_code=429)
    if guvenlik.govde_cok_buyuk(request, 20_000):
        return Response("istek çok büyük", status_code=413)
    try:
        veri = await request.json()
        metin = str(veri.get("metin") or "").strip()[:1000]
        sessiz = bool(veri.get("sessiz"))
    except (ValueError, TypeError, AttributeError):
        return Response("bozuk istek", status_code=400)
    if not metin:
        return Response("soru boş", status_code=400)
    return await _cevapla(request, metin, sessiz=sessiz)


async def _cevapla(request: Request, metin: str, sessiz: bool) -> Response:
    """Sesli ve yazılı sorunun ortak yolu: beyin → (ses) → başlıklarla cevap."""
    logger.info("uygulama sorgusu: %s", metin[:80])

    ara = beyin() if beyin is not None else None
    if ara is None:
        logger.error("sesli: beyin kurulu değil")
        return Response("Vekil şu an sesli cevap veremiyor.", status_code=503)

    global _son_soru
    if _saat() - _son_soru > _GECMIS_OMUR_SN:
        _GECMIS.clear()
    _son_soru = _saat()

    # Alarm, fener gibi işleri uygulama kendisi yapar. Bunu bilen sürüm kendini X-Vekil-Surum ile tanıtır;
    # eski sürüme bu araç sunulmaz (yoksa "kurdum" der, uygulama başlığı tanımaz, alarm kurulmaz).
    # Sürüm 3: telefonu ekrandan kullanabiliyor (mesaj, "ekranda" işleri).
    surum = _surum(request)
    t_beyin = time.perf_counter()
    eylemler: list[dict[str, Any]] | None = [] if surum >= 2 else None
    if surum >= 3:
        cevap = (await ara.uygulama_cevabi(metin, list(_GECMIS), eylemler, ekran_ajani=True)).strip()
    else:
        cevap = (await ara.uygulama_cevabi(metin, list(_GECMIS), eylemler)).strip()
    beyin_sn = time.perf_counter() - t_beyin
    if not cevap:
        return Response("model cevap vermedi", status_code=502)

    _GECMIS.extend([{"role": "user", "content": metin}, {"role": "assistant", "content": cevap}])
    del _GECMIS[:-_GECMIS_SINIRI]

    mp3 = b""
    tts_sn = 0.0
    if not sessiz:
        t_tts = time.perf_counter()
        try:
            mp3 = await seslendirme.edge_sentez(cevap, seslendirme.SES, "+0%")
        except Exception as e:
            logger.warning("TTS hata: %s", e)
            return Response(f"TTS hatası: {e}", status_code=502)
        tts_sn = time.perf_counter() - t_tts
    logger.info("sesli süre: beyin=%.2fs tts=%.2fs", beyin_sn, tts_sn)

    # Uygulama konuşmayı yazı olarak da gösteriyor; başlıklar ASCII olmak zorunda.
    basliklar = {"X-Metin": quote(metin), "X-Cevap": quote(cevap)}
    if eylemler:
        basliklar["X-Eylem"] = quote(json.dumps(eylemler, ensure_ascii=False))
    return Response(mp3, media_type="audio/mpeg", headers=basliklar)


async def seslendir(request: Request) -> Response:
    """Telefonda ekrandan yapılan işin sonucunu Vekil'in sesiyle söyler."""
    if not guvenlik.token_esit(request.path_params["token"], config.SESLI_TOKEN):
        return Response("yetkisiz", status_code=401)
    if not guvenlik.uygulama_siniri.izin_var():
        return Response("çok sık istek", status_code=429)
    if guvenlik.govde_cok_buyuk(request, 20_000):
        return Response("istek çok büyük", status_code=413)
    try:
        metin = str((await request.json()).get("metin") or "").strip()[:500]
    except (ValueError, TypeError, AttributeError):
        return Response("bozuk istek", status_code=400)
    if not metin:
        return Response("metin boş", status_code=400)
    try:
        mp3 = await seslendirme.edge_sentez(metin, seslendirme.SES, "+0%")
    except Exception as e:  # noqa: BLE001
        logger.warning("TTS hata: %s", e)
        return Response("TTS hatası", status_code=502)
    return Response(mp3, media_type="audio/mpeg")
