"""Ölü adam anahtarı (kill switch): Kullanıcı sohbete sadece "kys" yazarsa OpenDelegate kendini TAMAMEN kapatır.

- Kilit `ayarlar` 'kilit'te kalıcı: Render yeniden başlasa, yeni sürüm gelse bile kilitli açılır.
- Kilitliyken: hiçbir mesaj/komut/buton işlenmez, model çağrılmaz; spor, brifing, zamanlı işler, konu takibi,
  sesli zincir başlatılmaz; PC ajanına iş gitmez. Her mesaja "kapalıyım, şifreyi yaz" denir.
- Açmak için şifre ya da kurtarma kodu. İkisi de KODDA YOK: sadece PBKDF2-SHA256 (600k tur, tuzlu) özetleri var
  (ortam değişkeninde). Kurtarma kodu kurulum sihirbazında ŞİFREDEN BAĞIMSIZ, o kuruluma özel üretilir; şifre
  unutulursa yedek olarak kullanılır. Hiçbir kurulumda ortak/sabit bir anahtar YOKTUR. Mesaj sohbetten silinir.
  5 yanlış denemeden sonra 15 dk bekleme.
- Veritabanı okunamazsa güvenli tarafta kalır: kilitli sayar (fail-closed).
- Kilitleme ve açma sonrası süreç kendini kapatır; Render temiz bir süreçle yeniden başlatır.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time

import config

logger = logging.getLogger("kilit")

ANAHTAR = "kilit"
TETIK = "kys"
# Şifre özeti kurulum sihirbazında üretilir ve ortam değişkenlerinde durur (KILIT_TUZ, KILIT_OZET, KILIT_OZET_SADE).
# Ayarlı değilse kill switch kapalıdır ("kys" bir şey yapmaz): açamayacağı kilidi kurmaz.
_TUZ = bytes.fromhex(config.KILIT_TUZ or "00" * 16)
_OZET = bytes.fromhex(config.KILIT_OZET or "")
_TUR = 600_000
# Telegram biçim işaretlerini (` \ _ * ~ |) silebiliyor/değiştirebiliyor: bunlar ve boşluklar atılmış hâlin özeti.
_OZET_SADE = bytes.fromhex(config.KILIT_OZET_SADE or "")
_BICIM = re.compile(r"[\s`\\_*~|]")

# Kurtarma kodu: şifreden TAMAMEN bağımsız, kurulum sihirbazının o kuruluma özel ürettiği yedek. Ortak/sabit bir
# anahtar DEĞİL; her kurulumda farklı, boşsa (ayarlanmamışsa) devre dışı.
_KURTARMA_TUZ = bytes.fromhex(config.KILIT_KURTARMA_TUZ or "00" * 16)
_KURTARMA_OZET = bytes.fromhex(config.KILIT_KURTARMA_OZET or "")
MAKS_DENEME = 5
BEKLEME_SN = 15 * 60
KAPALI_MESAJI = ("OpenDelegate kendini kapattı. Hiçbir şey yapmıyorum: mesaj işlemiyorum, bilgisayara ve hesaplara "
                 "dokunmuyorum. Açmak için şifreyi yaz.")

kilitli = False
_yanlis = 0
_bekle_bitis = 0.0


def etkin() -> bool:
    """Şifre özeti ayarlı mı? Değilse kill switch kapalı."""
    return bool(_OZET)


def tetik_mi(metin: str | None) -> bool:
    return etkin() and (metin or "").strip().lower() == TETIK


def kurtarma_kodu_dogru(metin: str | None) -> bool:
    """O kuruluma özel kurtarma kodu. Sadece BÜYÜK HARF+rakamdan oluştuğu için büyük/küçük harf duyarsız
    (şifreden farklı olarak). Ayarlı değilse (_KURTARMA_OZET boş) her zaman False."""
    if not _KURTARMA_OZET:
        return False
    aday = hashlib.pbkdf2_hmac("sha256", (metin or "").strip().upper().encode("utf-8"), _KURTARMA_TUZ, _TUR)
    if hmac.compare_digest(aday, _KURTARMA_OZET):
        return True
    sade = _BICIM.sub("", metin or "").upper()
    if not sade:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", sade.encode("utf-8"), _KURTARMA_TUZ, _TUR), _KURTARMA_OZET)


def sifre_dogru(metin: str | None) -> bool:
    if kurtarma_kodu_dogru(metin):
        return True
    if not _OZET:
        return False
    aday = hashlib.pbkdf2_hmac("sha256", (metin or "").strip().encode("utf-8"), _TUZ, _TUR)
    if hmac.compare_digest(aday, _OZET):
        return True
    sade = _BICIM.sub("", metin or "")
    if not sade or not _OZET_SADE:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", sade.encode("utf-8"), _TUZ, _TUR), _OZET_SADE)


def _oku_db() -> bool:
    import hafiza

    satir = hafiza._calistir("SELECT deger FROM ayarlar WHERE anahtar = %s", (ANAHTAR,), sonuc="tek")
    return bool(satir and json.loads(satir["deger"]).get("kilitli"))


def _yaz_db(deger: bool) -> None:
    import hafiza

    hafiza._ayar_yaz(ANAHTAR, json.dumps({"kilitli": deger, "zaman": time.time()}))


async def yukle() -> bool:
    """Açılışta. Okunamazsa 3 deneme; yine olmazsa kilitli say (güvenli taraf)."""
    global kilitli
    for i in range(3):
        try:
            kilitli = await asyncio.to_thread(_oku_db)
            return kilitli
        except Exception as e:  # noqa: BLE001
            logger.warning("kilit durumu okunamadı (%d/3): %s", i + 1, type(e).__name__)
            await asyncio.sleep(2)
    kilitli = True
    logger.error("kilit durumu okunamadı; güvenli tarafta kalıp kilitli açılıyorum")
    return kilitli


async def ayarla(deger: bool) -> None:
    """Kalıcı yazar (hata yükselir: yazılamazsa çağıran bilsin)."""
    global kilitli
    await asyncio.to_thread(_yaz_db, deger)
    kilitli = deger


def ham_adaylar(metin: str | None, varliklar: list[tuple[str, int, int]]) -> list[str]:
    """Telegram `ters tırnak` arasını "kod" biçimine çevirip tırnakları SİLER. Şifrede ` olduğu için:
    gelen metin + kod/pre biçimli parçaları tekrar ``'e sarılmış hâli aday. varliklar: (tür, ofset, uzunluk),
    ofset/uzunluk UTF-16 birimi (Telegram)."""
    metin = metin or ""
    adaylar = [metin]
    kodlar = sorted((o, u) for t, o, u in varliklar if t in ("code", "pre"))
    if kodlar:
        b = metin.encode("utf-16-le")
        parca, son = [], 0
        for o, u in kodlar:
            parca += [b[son * 2:o * 2], "`".encode("utf-16-le"), b[o * 2:(o + u) * 2], "`".encode("utf-16-le")]
            son = o + u
        parca.append(b[son * 2:])
        adaylar.append(b"".join(parca).decode("utf-16-le"))
    return adaylar


def deneme(metin: str | None | list[str], simdi: float | None = None) -> str:
    """Kilitliyken gelen mesaj (ya da aday listesi): 'dogru' | 'yanlis' | 'bekle'."""
    global _yanlis, _bekle_bitis
    simdi = time.monotonic() if simdi is None else simdi
    if simdi < _bekle_bitis:
        return "bekle"
    adaylar = metin if isinstance(metin, list) else [metin]
    if any(sifre_dogru(a) for a in adaylar):
        _yanlis = 0
        return "dogru"
    _yanlis += 1
    if _yanlis >= MAKS_DENEME:
        _yanlis = 0
        _bekle_bitis = simdi + BEKLEME_SN
    return "yanlis"
