"""OneDrive erişimi (rclone).

PC kapalıyken Vekil'in senkron klasörlere (Masaüstü, Belgeler) bulut üzerinden
erişmesini sağlar. PC açıkken buraya yüklenen dosyalar OneDrive senkronu ile
PC'deki klasöre de iner.

Yapabildikleri (hepsi bu kadar):
    listele / ara (rclone lsjson), oku / sohbete gönder (rclone cat, belleğe),
    klasör oluştur (rclone mkdir), yükle: URL'den ya da metinden YENİ dosya
    (rclone copyto --ignore-existing), SİLME: tek dosya (rclone deletefile) ya da
    BOŞ klasör (rclone rmdir) — ikisi de 🟡 onaysız (bilgi satırı + log).

TAŞIMA / YENİDEN ADLANDIRMA (rclone moveto, 2026-11-14): sadece izinli kökler içinde; hedefte aynı ad varsa
    üzerine YAZILMAZ (hata); izinli kök taşınamaz; klasör kendi içine taşınamaz.

BİLEREK YOK: üzerine yazma; ve RECURSIVE (içeriğiyle)
    SİLME — rclone'un bir klasörü içindekilerle birlikte silen komutları ne izin
    listesindedir ne de bu modülde çağrılır, dolayısıyla DOLU bir klasör tek hamlede
    ASLA silinemez (silme istenirse reddedilir).
    rclone yalnızca _IZINLI_KOMUTLAR içindeki komutlarla çağrılabilir; bunun
    dışında bir komut istenirse çalıştırılmadan reddedilir. Yükleme hedefinde
    aynı adda dosya varsa ya hata verilir ya da YENİ dosyaya boş bir ad bulunur.

Erişim ONEDRIVE_KLASORLER köklerine kısıtlıdır.

Kimlik: rclone.conf (rclone'un kendi kayıtlı uygulamasıyla alınmış OneDrive
token'ı). Render'da /etc/secrets/rclone.conf salt okunur olduğundan açılışta
yazılabilir bir kopyaya alınır; rclone token'ı yeniledikçe o kopyaya yazar.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import ag
import config
import tools

logger = logging.getLogger("vekil.onedrive")

MAKS_DOSYA_BOYUTU = 5 * 1024 * 1024  # okuma limiti
MAKS_YUKLEME = config.MAKS_INDIRME  # 25 MB
MAKS_LISTE = 200
MAKS_GONDERME = 20 * 1024 * 1024  # onedrive_gonder (Telegram'a belge) limiti
MAKS_ARAMA_SONUC = 50

# Kısayollar: ilk parça bunlardan biriyse gerçek yola açılır (izinli kökün ALTINDA kalır).
KISAYOLLAR = {"klasorler": "Masaüstü/klasorler"}

# rclone ile çalıştırılabilecek komutların TAMAMI. Başka komut yok.
# deletefile: SADECE tek dosya. rmdir: SADECE boş klasör. Recursive (içeriğiyle) silme komutları YOK.
_IZINLI_KOMUTLAR = frozenset({"lsjson", "cat", "mkdir", "copyto", "deletefile", "rmdir", "moveto"})
_YOK = 3  # rclone çıkış kodu: dizin/dosya bulunamadı


class OneDriveHatasi(Exception):
    pass


# --------------------------------------------------------------------------
# rclone kurulumu
# --------------------------------------------------------------------------

_aktif_config: str | None = None
_hazirlandi = False


def _varsayilan_config() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "rclone" / "rclone.conf"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "rclone" / "rclone.conf"


def _hazirla() -> None:
    """RCLONE_CONFIG verildiyse onu bir kez yazılabilir bir kopyaya alır."""
    global _aktif_config, _hazirlandi
    if _hazirlandi:
        return
    _hazirlandi = True
    if not config.RCLONE_CONFIG:
        return  # rclone varsayılan config'ini kullanır
    kaynak = Path(config.RCLONE_CONFIG)
    if not kaynak.is_file():
        logger.warning("RCLONE_CONFIG bulunamadı: %s (OneDrive bağlı değil)", kaynak)
        return
    dizin = Path(tempfile.gettempdir()) / "vekil-rclone"
    dizin.mkdir(mode=0o700, parents=True, exist_ok=True)
    hedef = dizin / "rclone.conf"
    try:
        shutil.copyfile(kaynak, hedef)
        os.chmod(hedef, 0o600)
        _aktif_config = str(hedef)
        logger.info("rclone config yazılabilir kopyaya alındı.")
    except OSError as e:  # kopyalanamazsa kaynağı doğrudan kullan (token yenilemesi kaydedilemez)
        logger.warning("rclone config kopyalanamadı (%s); salt okunur haliyle kullanılacak.", e)
        _aktif_config = str(kaynak)


def _config_yolu() -> Path:
    _hazirla()
    return Path(_aktif_config) if _aktif_config else _varsayilan_config()


def _rclone_var() -> bool:
    return bool(shutil.which(config.RCLONE_BIN) or Path(config.RCLONE_BIN).is_file())


def bagli_mi() -> bool:
    """rclone kurulu ve remote tanımlı mı? (ağ isteği atmaz)"""
    if not _rclone_var():
        return False
    if os.environ.get(f"RCLONE_CONFIG_{config.ONEDRIVE_REMOTE.upper()}_TYPE"):
        return True  # ortam değişkeniyle tanımlı remote
    if config.RCLONE_CONFIG and not Path(config.RCLONE_CONFIG).is_file():
        return False
    try:
        return f"[{config.ONEDRIVE_REMOTE}]" in _config_yolu().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _argv(komut: str, *args: str) -> list[str]:
    """Testlerde değiştirilebilir. Komut izin listesinde değilse çalıştırmaz."""
    if komut not in _IZINLI_KOMUTLAR:
        raise OneDriveHatasi(f"'{komut}' rclone komutu bu modülde yasak.")
    _hazirla()
    argv = [config.RCLONE_BIN, komut, *args, "--ask-password=false"]
    if _aktif_config:
        argv += ["--config", _aktif_config]
    return argv


async def _rclone(komut: str, *args: str, zaman_asimi: float | None = None) -> tuple[int, bytes, str]:
    """rclone'u kabuk OLMADAN çalıştırır. (çıkış kodu, stdout, stderr)

    Süre sınırı YOK (Kullanıcı: büyük yüklemeler kesilmesin). Kullanıcı "dur" derse tur iptal edilir ve süreç kapatılır.
    """
    argv = _argv(komut, *args)
    try:
        surec = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        raise OneDriveHatasi("rclone bulunamadı (kurulu değil ya da RCLONE_BIN yanlış).")
    try:
        cikti, hata = await asyncio.wait_for(surec.communicate(), timeout=zaman_asimi)
    except asyncio.TimeoutError:
        surec.kill()
        await surec.wait()
        raise OneDriveHatasi(f"OneDrive işlemi {zaman_asimi:.0f} sn içinde bitmedi.")
    except asyncio.CancelledError:  # "dur": arkada yarım rclone kalmasın
        surec.kill()
        await surec.wait()
        raise
    return surec.returncode or 0, cikti, hata.decode("utf-8", errors="replace")


def _hata(stderr: str) -> OneDriveHatasi:
    satirlar = [s for s in stderr.splitlines() if s.strip() and "NOTICE: Config file" not in s]
    son = satirlar[-1][-300:] if satirlar else "bilinmeyen hata"
    kucuk = stderr.lower()
    if "token" in kucuk and any(k in kucuk for k in ("expired", "invalid_grant", "unauthorized", "couldn't fetch")):
        return OneDriveHatasi(
            "OneDrive oturumu düşmüş (token geçersiz). Lokalde `rclone config reconnect "
            f"{config.ONEDRIVE_REMOTE}:` yapıp yeni rclone.conf'u Render'a yükle."
        )
    if "didn't find section in config file" in kucuk:
        return OneDriveHatasi(f"rclone config'te '{config.ONEDRIVE_REMOTE}' remote'u yok.")
    return OneDriveHatasi(f"rclone hatası: {son}")


# --------------------------------------------------------------------------
# Yol yardımcıları
# --------------------------------------------------------------------------

def _yolu_dogrula(yol: str | None) -> str:
    """Yolu normalize eder, izinli kök klasörlerin dışına çıkmasını engeller."""
    if yol and any(ord(c) < 32 for c in yol):
        raise OneDriveHatasi("Yolda kontrol karakteri olamaz.")
    parcalar = [p.strip() for p in (yol or "").replace("\\", "/").split("/") if p.strip() not in ("", ".")]
    if any(p == ".." for p in parcalar):
        raise OneDriveHatasi("Yolda '..' kullanılamaz.")
    if not parcalar:
        return ""
    kisayol = KISAYOLLAR.get(parcalar[0].casefold())
    if kisayol:
        parcalar = kisayol.split("/") + parcalar[1:]
    izinli = {k.casefold(): k for k in config.ONEDRIVE_KLASORLER}
    kok = izinli.get(parcalar[0].casefold())
    if kok is None:
        raise OneDriveHatasi(
            f"'{parcalar[0]}' izinli değil. Sadece şu klasörlere erişebilirim: {', '.join(config.ONEDRIVE_KLASORLER)}"
        )
    return "/".join([kok, *parcalar[1:]])


_YASAK_KARAKTER = set('"*:<>?|\\/')


def _ad_dogrula(ad: str) -> str:
    ad = ad.strip()
    if not ad or ad in (".", "..") or any(c in _YASAK_KARAKTER or ord(c) < 32 for c in ad) or ad.endswith("."):
        raise OneDriveHatasi(f"Geçersiz dosya/klasör adı: '{ad}'")
    return ad


def _uzak(yol: str) -> str:
    return f"{config.ONEDRIVE_REMOTE}:{yol}"


async def _stat(yol: str) -> dict[str, Any] | None:
    """Öğe varsa bilgisini ({Name, Size, IsDir}), yoksa None döner."""
    kod, cikti, hata = await _rclone("lsjson", "--stat", _uzak(yol))
    if kod == _YOK:
        return None
    if kod != 0:
        raise _hata(hata)
    return json.loads(cikti.decode("utf-8"))


# --------------------------------------------------------------------------
# Tool'lar
# --------------------------------------------------------------------------

async def listele(yol: str | None = None) -> str:
    yol = _yolu_dogrula(yol)
    if not yol:
        return "[OneDrive | izinli kökler]\n" + "\n".join(f"[D] {k}" for k in config.ONEDRIVE_KLASORLER)
    kod, cikti, hata = await _rclone("lsjson", "--no-mimetype", "--no-modtime", _uzak(yol))
    if kod == _YOK:
        raise OneDriveHatasi("OneDrive'da böyle bir klasör yok.")
    if kod != 0:
        raise _hata(hata)
    ogeler = sorted(json.loads(cikti.decode("utf-8")), key=lambda o: (not o.get("IsDir"), o["Name"].lower()))
    satirlar = [
        f"[D] {o['Name']}" if o.get("IsDir") else f"[F] {o['Name']}  {ag.boyut_yaz(max(o.get('Size', 0), 0))}"
        for o in ogeler[:MAKS_LISTE]
    ]
    if len(ogeler) > MAKS_LISTE:
        satirlar.append(f"... ve {len(ogeler) - MAKS_LISTE} girdi daha")
    return f"[OneDrive:/{yol} | {len(ogeler)} girdi]\n" + ("\n".join(satirlar) or "(boş)")


async def oku(yol: str) -> str:
    yol = _yolu_dogrula(yol)
    if not yol or "/" not in yol:
        raise OneDriveHatasi("Bir dosya yolu ver, ör. 'Belgeler/notlar.txt'.")
    meta = await _stat(yol)
    if meta is None:
        raise OneDriveHatasi("OneDrive'da böyle bir dosya yok.")
    if meta.get("IsDir"):
        raise OneDriveHatasi("Bu bir klasör; onedrive_listele kullan.")
    boyut = meta.get("Size", 0)
    if boyut > MAKS_DOSYA_BOYUTU:
        raise OneDriveHatasi(f"Dosya çok büyük ({ag.boyut_yaz(boyut)}), limit {ag.boyut_yaz(MAKS_DOSYA_BOYUTU)}.")
    kod, ham, hata = await _rclone("cat", "--count", str(MAKS_DOSYA_BOYUTU), _uzak(yol))
    if kod != 0:
        raise _hata(hata)
    if b"\x00" in ham[:8192]:
        raise OneDriveHatasi("Bu bir ikili (binary) dosya gibi görünüyor, metin olarak okunamaz.")
    for kodlama in ("utf-8-sig", "cp1254"):
        try:
            metin = ham.decode(kodlama)
            break
        except UnicodeDecodeError:
            continue
    else:
        metin = ham.decode("utf-8", errors="replace")
    return f"[OneDrive:/{yol} | {ag.boyut_yaz(boyut)}]\n" + tools.kisalt(metin)


async def bellege_al(yol: str, limit: int = MAKS_GONDERME) -> tuple[bytes, str, str]:
    """Dosyayı diske yazmadan belleğe çeker: (veri, dosya adı, normalize yol)."""
    yol = _yolu_dogrula(yol)
    if not yol or "/" not in yol:
        raise OneDriveHatasi("Bir dosya yolu ver, ör. 'klasorler/Projeler/rapor.pdf'.")
    meta = await _stat(yol)
    if meta is None:
        raise OneDriveHatasi("OneDrive'da böyle bir dosya yok (onedrive_ara ile aramayı dene).")
    if meta.get("IsDir"):
        raise OneDriveHatasi("Bu bir klasör; tek bir dosya ver.")
    boyut = int(meta.get("Size", 0))
    if boyut > limit:
        raise OneDriveHatasi(f"Dosya çok büyük ({ag.boyut_yaz(boyut)}), sohbete en fazla {ag.boyut_yaz(limit)} gönderebilirim.")
    kod, veri, hata = await _rclone("cat", "--count", str(limit + 1), _uzak(yol))
    if kod != 0:
        raise _hata(hata)
    if len(veri) > limit:
        raise OneDriveHatasi(f"Dosya çok büyük, sohbete en fazla {ag.boyut_yaz(limit)} gönderebilirim.")
    if boyut >= 0 and len(veri) != boyut:
        raise OneDriveHatasi(f"Dosya eksik geldi ({len(veri)}/{boyut} byte), tekrar dene.")
    return veri, yol.rsplit("/", 1)[-1], yol


_GLOB = set("*?[]{}\\/")  # rclone filtre/glob karakterleri sorgudan atılır


async def ara(sorgu: str, kok: str | None = None) -> str:
    """Ada göre alt klasörler dahil arama (büyük/küçük harf duyarsız). kok yoksa tüm izinli kökler."""
    temiz = "".join(c for c in str(sorgu or "") if c not in _GLOB and ord(c) >= 32).strip()
    if len(temiz) < 2:
        raise OneDriveHatasi("Aranacak en az 2 karakter ver (dosya/klasör adından bir parça).")
    kokler = [_yolu_dogrula(kok)] if kok and _yolu_dogrula(kok) else list(config.ONEDRIVE_KLASORLER)
    bulunan: list[tuple[str, dict[str, Any]]] = []
    for k in kokler:
        kod, cikti, hata = await _rclone(
            "lsjson", "-R", "--no-mimetype", "--max-depth", "12", "--ignore-case",
            "--include", f"*{temiz}*", "--include", f"*{temiz}*/**",
            _uzak(k),
        )
        if kod == _YOK:
            continue
        if kod != 0:
            raise _hata(hata)
        for o in json.loads(cikti.decode("utf-8")):
            if temiz.casefold() in o["Name"].casefold():  # klasörün içindekileri değil, adı eşleşenleri göster
                bulunan.append((f"{k}/{o['Path']}", o))
    if not bulunan:
        return f"[OneDrive araması: '{temiz}'] Bulunamadı ({', '.join(kokler)} altında)."
    bulunan.sort(key=lambda x: (not x[1].get("IsDir"), x[0].lower()))
    satirlar = [
        (f"[D] {yol}" if o.get("IsDir") else f"[F] {yol}  {ag.boyut_yaz(max(o.get('Size', 0), 0))}")
        for yol, o in bulunan[:MAKS_ARAMA_SONUC]
    ]
    if len(bulunan) > MAKS_ARAMA_SONUC:
        satirlar.append(f"... ve {len(bulunan) - MAKS_ARAMA_SONUC} sonuç daha (aramayı daralt)")
    return f"[OneDrive araması: '{temiz}' | {len(bulunan)} sonuç]\n" + "\n".join(satirlar)


async def klasor_olustur(yol: str) -> str:
    """Klasörü (gerekirse ara klasörlerle birlikte) oluşturur. Varsa dokunmaz."""
    yol = _yolu_dogrula(yol)
    parcalar = yol.split("/") if yol else []
    if len(parcalar) < 2:
        raise OneDriveHatasi("İzinli bir kökün altında bir klasör yolu ver, ör. 'Belgeler/Projeler'.")
    for p in parcalar[1:]:
        _ad_dogrula(p)
    ilk_eksik = None
    for i in range(2, len(parcalar) + 1):
        hedef = "/".join(parcalar[:i])
        meta = await _stat(hedef)
        if meta is None:
            ilk_eksik = i
            break
        if not meta.get("IsDir"):
            raise OneDriveHatasi(f"'{hedef}' bir dosya, altına klasör açılamaz.")
    if ilk_eksik is None:
        return f"OneDrive:/{yol} zaten var, bir şey yapmadım."
    kod, _, hata = await _rclone("mkdir", _uzak(yol))
    if kod != 0:
        raise _hata(hata)
    olusan = ["/".join(parcalar[:i]) for i in range(ilk_eksik, len(parcalar) + 1)]
    return "Oluşturuldu: " + ", ".join(f"OneDrive:/{o}" for o in olusan)


async def _bos_ad_bul(yol: str) -> str:
    """'Masaüstü/rapor.txt' doluysa 'Masaüstü/rapor 1.txt', 'rapor 2.txt'... dener."""
    ust, ad = yol.rsplit("/", 1)
    kok, nokta, uzanti = ad.rpartition(".")
    if not kok:  # uzantısız ad (ya da '.gitignore' gibi)
        kok, nokta, uzanti = ad, "", ""
    for i in range(1, 100):
        aday = f"{ust}/{kok} {i}{nokta}{uzanti}"
        if await _stat(aday) is None:
            return aday
    raise OneDriveHatasi("Boş bir dosya adı bulunamadı.")


async def veri_yukle(veri: bytes, yol: str, varsayilan_ad: str = "", cakisma: str = "hata") -> str:
    """Byte içeriği OneDrive'a YENİ dosya olarak koyar (indir tool'u da bunu kullanır).

    `yol` '/' ile biterse, izinli bir kökün kendisiyse ya da var olan bir
    klasörü gösteriyorsa dosya adı `varsayilan_ad` olur.
    """
    if cakisma not in ("hata", "yeni_ad"):
        raise OneDriveHatasi("cakisma 'hata' ya da 'yeni_ad' olmalı.")
    if len(veri) > MAKS_YUKLEME:
        raise OneDriveHatasi(f"İçerik çok büyük, limit {ag.boyut_yaz(MAKS_YUKLEME)}.")
    klasor_hedef = (yol or "").replace("\\", "/").rstrip().endswith("/")
    yol = _yolu_dogrula(yol)
    if not yol:
        raise OneDriveHatasi("Hedef yol ver, ör. 'Masaüstü/rapor.txt'.")

    meta = None if (klasor_hedef or "/" not in yol) else await _stat(yol)
    if klasor_hedef or "/" not in yol or (meta is not None and meta.get("IsDir")):
        if not varsayilan_ad:
            raise OneDriveHatasi("Hedef bir klasör; dosya adını da ver, ör. 'Masaüstü/not.txt'.")
        yol = f"{yol}/{_ad_dogrula(varsayilan_ad)}"
        meta = await _stat(yol)
    else:
        _ad_dogrula(yol.rsplit("/", 1)[-1])
    for p in yol.split("/")[1:-1]:
        _ad_dogrula(p)

    if meta is not None:
        if cakisma == "hata":
            raise OneDriveHatasi(
                f"OneDrive:/{yol} zaten var; üzerine yazmıyorum. Başka ad ver ya da cakisma='yeni_ad' kullan."
            )
        yol = await _bos_ad_bul(yol)

    with tempfile.TemporaryDirectory(prefix="vekil-yukle-") as gecici:
        kaynak = Path(gecici) / "icerik"
        kaynak.write_bytes(veri)
        # --ignore-existing: kontrolden sonra biri aynı adı oluşturduysa da üzerine yazılmaz.
        kod, _, hata = await _rclone("copyto", "--ignore-existing", "-vv", str(kaynak), _uzak(yol))
    if kod != 0:
        raise _hata(hata)
    if "destination exists, skipping" in hata.lower():
        raise OneDriveHatasi(f"Tam yüklerken OneDrive:/{yol} oluşmuş; üzerine yazmadım, tekrar dene.")
    return f"Yüklendi: OneDrive:/{yol} ({ag.boyut_yaz(len(veri))})."


async def yukle(yol: str, url: str | None = None, icerik: str | None = None, cakisma: str = "hata") -> str:
    """URL'den indirilen ya da verilen metni OneDrive'a YENİ dosya olarak koyar."""
    if bool(url) == bool(icerik):
        raise OneDriveHatasi("Ya 'url' ya da 'icerik' ver (ikisinden biri, sadece biri).")
    if url:
        try:
            dosya = await ag.indir(url, MAKS_YUKLEME)
        except ag.AgHatasi as e:
            raise OneDriveHatasi(str(e)) from e
        return await veri_yukle(dosya.veri, yol, dosya.ad, cakisma)
    return await veri_yukle(str(icerik).encode("utf-8"), yol, "", cakisma)


async def sil(yol: str) -> str:
    """Tek bir dosyayı (deletefile) ya da BOŞ bir klasörü (rmdir) siler. Recursive silme YOK.

    İzinli kökün kendisi silinemez; dolu klasör silinemez (içini tek tek sildir ya da boşalt).
    """
    ham = yol
    yol = _yolu_dogrula(yol)
    if not yol or "/" not in yol:
        raise OneDriveHatasi(
            f"Silinecek bir dosya ya da klasör yolu ver, ör. 'Belgeler/eski/not.txt'. İzinli kökü ('{ham}') silemem."
        )
    meta = await _stat(yol)
    if meta is None:
        raise OneDriveHatasi(f"OneDrive'da böyle bir şey yok: {yol}")
    if not meta.get("IsDir"):
        kod, _, hata = await _rclone("deletefile", _uzak(yol))
        if kod != 0:
            raise _hata(hata)
        return f"Silindi (dosya): OneDrive:/{yol}"
    # Klasör: önce boş mu diye bak. Recursive silme olmadığı için dolu klasör silinemez.
    kod, cikti, hata = await _rclone("lsjson", "--no-mimetype", "--no-modtime", _uzak(yol))
    if kod == _YOK:
        raise OneDriveHatasi(f"OneDrive'da böyle bir klasör yok: {yol}")
    if kod != 0:
        raise _hata(hata)
    icindekiler = json.loads(cikti.decode("utf-8"))
    if icindekiler:
        raise OneDriveHatasi(
            f"'{yol}' klasörünün içinde {len(icindekiler)} öğe var. OneDrive'da recursive (içeriğiyle) silme YOK; "
            "dolu klasörü silemem. İçindeki dosyaları tek tek sildir ya da sen boşalt, sonra boş klasörü silerim."
        )
    kod, _, hata = await _rclone("rmdir", _uzak(yol))
    if kod != 0:
        raise _hata(hata)
    return f"Silindi (boş klasör): OneDrive:/{yol}"


async def tasi(kaynak: str, hedef: str) -> str:
    """Dosya ya da klasörü taşır VEYA yeniden adlandırır (aynı klasörde yeni ad = yeniden adlandırma).

    Güvenlik: sadece izinli kökler; izinli kökün kendisi taşınamaz; klasör kendi içine taşınamaz; hedefte aynı
    adda bir şey varsa ÜZERİNE YAZILMAZ (hata). 'hedef' '/' ile biterse o klasörün İÇİNE aynı adla taşınır.
    """
    k = _yolu_dogrula(kaynak)
    if not k or "/" not in k:
        raise OneDriveHatasi(f"Taşınacak bir dosya ya da klasör yolu ver. İzinli kökü ('{kaynak}') taşıyamam.")
    meta = await _stat(k)
    if meta is None:
        raise OneDriveHatasi(f"OneDrive'da böyle bir şey yok: {k}")
    ham = (hedef or "").strip()
    klasorun_icine = ham.endswith(("/", "\\"))
    h = _yolu_dogrula(ham)
    if not h:
        raise OneDriveHatasi("Hedef yol boş.")
    if klasorun_icine:
        hmeta = await _stat(h)
        if hmeta is None or not hmeta.get("IsDir"):
            raise OneDriveHatasi(f"Hedef klasör yok: {h} (önce onedrive_klasor_olustur ile oluştur).")
        h = f"{h}/{k.rsplit('/', 1)[1]}"
    else:
        _ad_dogrula(h.rsplit("/", 1)[-1])
        if "/" not in h:
            raise OneDriveHatasi("Hedef, izinli bir kökün İÇİNDE olmalı (ör. 'Belgeler/yeni-ad.txt').")
    if h == k:
        raise OneDriveHatasi("Kaynak ile hedef aynı.")
    if h.casefold().startswith(k.casefold() + "/"):
        raise OneDriveHatasi("Bir klasörü kendi içine taşıyamam.")
    sadece_harf_buyuklugu = h.casefold() == k.casefold()  # OneDrive büyük/küçük harfe duyarsız: aynı öğe görünür
    if not sadece_harf_buyuklugu and await _stat(h) is not None:
        raise OneDriveHatasi(f"Hedefte aynı adda bir şey var ({h}); üzerine yazmam. Başka bir ad ver.")
    kod, _, hata = await _rclone("moveto", _uzak(k), _uzak(h))
    if kod != 0:
        raise _hata(hata)
    tur = "Klasör" if meta.get("IsDir") else "Dosya"
    return f"{tur} taşındı: OneDrive:/{k} -> OneDrive:/{h}"


async def calistir(tool: str, argumanlar: dict[str, Any]) -> tuple[bool, str]:
    """OneDrive tool'unu çalıştırır. Asla exception fırlatmaz."""
    if not bagli_mi():
        return False, "HATA: OneDrive bağlı değil (rclone ya da rclone.conf / remote eksik)."
    try:
        if tool == "onedrive_listele":
            return True, await listele(argumanlar.get("yol"))
        if tool == "onedrive_oku":
            return True, await oku(str(argumanlar.get("yol", "")))
        if tool == "onedrive_ara":
            return True, await ara(str(argumanlar.get("sorgu", "")), argumanlar.get("kok") or None)
        if tool == "onedrive_sil":
            return True, await sil(str(argumanlar.get("yol", "")))
        if tool == "onedrive_tasi":
            return True, await tasi(str(argumanlar.get("kaynak", "")), str(argumanlar.get("hedef", "")))
        if tool == "onedrive_klasor_olustur":
            return True, await klasor_olustur(str(argumanlar.get("yol", "")))
        if tool == "onedrive_yukle":
            return True, await yukle(
                str(argumanlar.get("yol", "")),
                url=argumanlar.get("url") or None,
                icerik=argumanlar.get("icerik") or None,
                cakisma=str(argumanlar.get("cakisma") or "hata"),
            )
        return False, f"HATA: bilinmeyen OneDrive tool'u: {tool}"
    except OneDriveHatasi as e:
        return False, f"HATA: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("OneDrive beklenmeyen hata")
        return False, f"HATA ({type(e).__name__}): {e}"
