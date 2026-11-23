"""Ölü adam anahtarı (kill switch): Kullanıcı sohbete sadece "kys" yazarsa Vekil kendini TAMAMEN kapatır.

- Kilit `ayarlar` 'kilit'te kalıcı: Render yeniden başlasa, yeni sürüm gelse bile kilitli açılır.
- Kilitliyken: hiçbir mesaj/komut/buton işlenmez, model çağrılmaz; spor, brifing, zamanlı işler, konu takibi,
  sesli zincir başlatılmaz; PC ajanına iş gitmez. Her mesaja "kapalıyım, şifreyi yaz" denir.
- Açmak için sadece şifre. Şifre KODDA YOK: sadece PBKDF2-SHA256 (600k tur, tuzlu) özeti var. Şifre mesajı
  sohbetten silinir. 5 yanlış denemeden sonra 15 dk bekleme.
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

logger = logging.getLogger("kilit")

ANAHTAR = "kilit"
TETIK = "kys"
_TUZ = bytes.fromhex("50bd9c11f3852bd351f8c1f71c4cff59")
_OZET = bytes.fromhex("702edda7ccdb74b6c90c35a681f0a1062031307de88ddf8c07f67b6b344b7c38")
_TUR = 600_000
# Telegram biçim işaretlerini (` \ _ * ~ |) silebiliyor/değiştirebiliyor: bunlar ve boşluklar atılmış hâlin özeti.
_OZET_SADE = bytes.fromhex("702edda7ccdb74b6c90c35a681f0a1062031307de88ddf8c07f67b6b344b7c38")
_BICIM = re.compile(r"[\s`\\_*~|]")
MAKS_DENEME = 5
BEKLEME_SN = 15 * 60
KAPALI_MESAJI = ("Vekil kendini kapattı. Hiçbir şey yapmıyorum: mesaj işlemiyorum, bilgisayara ve hesaplara "
                 "dokunmuyorum. Açmak için şifreyi yaz.")

kilitli = False
_yanlis = 0
_bekle_bitis = 0.0


def tetik_mi(metin: str | None) -> bool:
    return (metin or "").strip().lower() == TETIK


def sifre_dogru(metin: str | None) -> bool:
    aday = hashlib.pbkdf2_hmac("sha256", (metin or "").strip().encode("utf-8"), _TUZ, _TUR)
    if hmac.compare_digest(aday, _OZET):
        return True
    sade = _BICIM.sub("", metin or "")
    if not sade:
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
