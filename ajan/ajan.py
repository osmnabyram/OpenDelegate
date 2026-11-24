"""Vekil PC ajanı — PC açıkken Vekil'in (Render) bu bilgisayardaki eli.

Ne yapar:
    Her YOKLAMA_ARALIGI saniyede bir Vekil'e GET /jobs/pending atar
    (X-Ajan-Secret ile kendini tanıtır), gelen görevleri çalıştırır ve
    sonucu POST /jobs/result ile geri yollar. Hata olursa hata metnini
    yollar; asla çökmez, bağlantı koparsa bekleyip tekrar dener.

Güvenlik:
    - Sadece şu görevleri bilir: dosya_oku, dosya_listele, dosya_yaz,
      dosya_sil, terminal_calistir, dosya_kaydet (Vekil'in internetten
      indirdiği dosyayı PC'ye kaydeder), ekran_goruntusu (bellekte alınır,
      diske yazılmaz), program_ac (brave/code/explorer), pencere_listele,
      pencere_kontrol (odakla/küçült/kapat; klavye-mouse yok), masaustu_durum / masaustu_olustur /
      masaustu_kaldir / pencere_tasi (Windows sanal masaüstleri). Başka bir şey gelirse reddeder.
    - Sanal masaüstü: VirtualDesktopAccessor.dll (bu klasörde, SHA256 sabit) belgelenmemiş Windows
      API'sini kullanır. Her çağrı AYRI bir alt süreçte yapılır (python ajan.py --masaustu ...):
      DLL çökerse ajan ayakta kalır. Sadece adı "Vekil - " ile başlayan masaüstleri oluşturulur/silinir;
      kullanıcının masaüstlerine (ilki dahil) asla dokunulmaz.
    - Arka planda: periyodik senkron (rclone sync) ve dosya izleme (kurallar Vekil'den;
      sadece yeni dosya adlarını bildirir). Telegram'a doğrudan yazmaz.
    - Onay Vekil tarafında (Telegram) alınır. Ajan ikinci bir kontrol yapar:
      yazma/silme/terminal/ekran görüntüsü ve hassas yollar (.env, .ssh, tarayıcı
      profilleri, Credentials...) için görevde "onayli": true yoksa çalıştırmaz.
    - Sırlar sadece bu klasördeki .env'de durur.

Sadece Python standart kütüphanesi kullanılır; kurulum gerekmez.
Çalıştırma: python ajan.py   (C:\\vekil-ajan içinde, .env ile)
"""

from __future__ import annotations

import base64
import fnmatch
import ctypes
import json
import logging
import logging.handlers
import operator
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable

DIZIN = Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# Yapılandırma (.env)
# --------------------------------------------------------------------------

def _env_yukle(yol: Path) -> None:
    """Basit .env okuyucu (KEY=VALUE). Ortamda zaten olan değerleri ezmez."""
    if not yol.exists():
        return
    for satir in yol.read_text(encoding="utf-8-sig").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, _, deger = satir.partition("=")
        os.environ.setdefault(anahtar.strip(), deger.strip().strip('"').strip("'"))


_env_yukle(DIZIN / ".env")

VEKIL_URL = os.getenv("VEKIL_URL", "").strip().rstrip("/")
AJAN_SECRET = os.getenv("AJAN_SECRET", "").strip()
YOKLAMA_ARALIGI = float(os.getenv("YOKLAMA_ARALIGI", "5"))
SICAK_ARALIK = 0.3  # sn; bir görev çalıştıktan sonra SICAK_SURE boyunca bu aralıkla yoklanır
SICAK_SURE = 25.0
# Uzun yoklama: sunucu görev gelene kadar (en çok bu kadar sn) cevabı bekletir -> görev anında alınır.
# AJAN_CEVRIMICI_SN'den (15) küçük kalmalı; sunucu da 10 sn ile sınırlar.
UZUN_YOKLAMA = max(1.0, min(float(os.getenv("UZUN_YOKLAMA", "8")), 10.0))
# 0 = süre sınırı YOK (Kullanıcı: uzun komutlar kesilmesin; "dur" ile kapatılır). İstenirse env ile üst sınır konur.
TERMINAL_ZAMAN_ASIMI = int(os.getenv("TERMINAL_ZAMAN_ASIMI", "0"))
CIKTI_LIMITI = 4000
MAKS_DOSYA_BOYUTU = 5 * 1024 * 1024
MAKS_YAZMA = 1 * 1024 * 1024
MAKS_LISTE = 200

# Uzaktan açılış (Vekil akıllı prizle elektriği verir, BIOS 'Wake on AC' laptopu hazırda bekletten uyandırır):
# Windows kimse dokunmadan uyandıysa ~2 dk sonra kendini geri uyutur. Ajan görev çalıştırırken, bittikten sonra
# ve uykudan dönüş algılanınca UYANIK_TUT_SN boyunca sistemi ve ekranı uyanık tutar, süre dolunca bırakır
# (Windows'un kendi ayarları geçerli olur). Kullanıcının elle uyutmasını (kapak, menü, güç düğmesi) ENGELLEMEZ:
# SetThreadExecutionState sadece boşta uykuyu erteler. Kurulum yok, sadece Windows API'si.
UYANIK_TUT_SN = 300.0
UYANIS_ESIK_SN = 120.0  # iki döngü başı arası duvar saati boşluğu (görev süresi hariç) bundan büyükse PC uyumuştu
UYANIS_HIZLI_SN = 120.0  # uykudan dönüşten sonra bu süre boyunca bağlantı hatasında en çok HIZLI_BEKLEME sn bekle
HIZLI_BEKLEME = 5.0  # (Wi-Fi uyanıştan birkaç sn sonra gelir; 60 sn'lik geri çekilme açılışı geciktirmesin)

# Periyodik senkron (PC -> OneDrive). SENKRON_KAYNAK boş bırakılırsa kapalı.
SENKRON_KAYNAK = os.getenv("SENKRON_KAYNAK", "").strip()
SENKRON_HEDEF = os.getenv("SENKRON_HEDEF", "").strip()
SENKRON_EXCLUDE = [e.strip() for e in os.getenv("SENKRON_EXCLUDE", "").split(",") if e.strip()]
SENKRON_ARALIK_DK = float(os.getenv("SENKRON_ARALIK_DK", "30"))
SENKRON_MAKS_SILME = int(os.getenv("SENKRON_MAKS_SILME", "25"))  # sigorta: daha fazla silme gerekiyorsa iptal
SENKRON_ZAMAN_ASIMI = int(os.getenv("SENKRON_ZAMAN_ASIMI", "1800"))
SENKRON_BILDIRIM_ESIGI = 3  # ard arda bu kadar hatada TEK Telegram bildirimi
RCLONE_BIN = os.getenv("RCLONE_BIN", "rclone").strip()

# Sanal masaüstü yardımcı süreci (python ajan.py --masaustu <json>): ajan.log'a yazmaz (döndürme çakışmasın).
_YARDIMCI_MOD = len(sys.argv) > 1 and sys.argv[1] == "--masaustu"

# Log rotasyonu: ajan.log 1 MB'ı geçince ajan.log.1'e döner; diskte en fazla ~2 MB log durur.
_log_hedefleri: list[logging.Handler] = [] if _YARDIMCI_MOD else [
    logging.handlers.RotatingFileHandler(DIZIN / "ajan.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
]
if sys.stdout is not None and not _YARDIMCI_MOD:  # pythonw ile (konsolsuz) çalışırken stdout yoktur
    _log_hedefleri.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO, handlers=_log_hedefleri)
log = logging.getLogger("ajan")


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------

def _kisalt(metin: str, limit: int = CIKTI_LIMITI) -> str:
    if len(metin) <= limit:
        return metin
    return metin[:limit] + f"\n... [{len(metin) - limit} karakter kesildi]"


def _boyut_yaz(bayt: float) -> str:
    for birim in ("B", "KB", "MB", "GB"):
        if bayt < 1024:
            return f"{bayt:.0f} {birim}" if birim == "B" else f"{bayt:.1f} {birim}"
        bayt /= 1024
    return f"{bayt:.1f} TB"


def _yol(ham: str) -> Path:
    """%USERPROFILE% ve ~ açılır; çalışma dizini ajan klasörü değil kullanıcı klasörüdür."""
    p = Path(os.path.expandvars(os.path.expanduser(str(ham).strip().strip('"'))))
    return p if p.is_absolute() else Path.home() / p


def _oem_kod_sayfasi() -> str:
    try:
        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except (AttributeError, OSError):
        return "utf-8"


def _coz(veri: bytes) -> str:
    try:
        return veri.decode("utf-8")
    except UnicodeDecodeError:
        return veri.decode(_oem_kod_sayfasi(), errors="replace")


# Hassas yollar — Vekil'deki tools.py ile aynı liste; değiştirirsen ikisini birlikte güncelle.
_HASSAS = [
    re.compile(p)
    for p in (
        r"(^|[\\\s\"'=])\.env(\.[\w.-]+)?($|[\\\s\"'])",
        r"\\\.(ssh|aws|azure|gnupg|kube|docker)(\\|$)",
        r"\.git-credentials|\.netrc|\.npmrc|\.pypirc",
        r"(^|\\)id_(rsa|ed25519|ecdsa|dsa)",
        r"\.(pem|key|pfx|p12|kdbx|ppk)($|[\s\"'])",
        r"credentials",
        r"\\microsoft\\(protect|vault)(\\|$)",
        r"\\windows\\system32\\config(\\|$)",
        r"\\appdata\\(local|roaming)\\(google\\chrome|microsoft\\edge|bravesoftware|vivaldi"
        r"|opera software|mozilla\\firefox|yandex)",
    )
]


def hassas_mi(metin: str) -> bool:
    m = metin.lower().replace("/", "\\")
    return any(p.search(m) for p in _HASSAS)


def _hassas_yol_mu(p: Path) -> bool:
    """Hem verilen hem de gerçek (symlink/junction çözülmüş) yolu kontrol eder."""
    try:
        gercek = str(p.resolve())
    except OSError:
        gercek = str(p)
    return hassas_mi(str(p)) or hassas_mi(gercek)


# --------------------------------------------------------------------------
# Görevler
# --------------------------------------------------------------------------

def dosya_oku(yol: str, maks_karakter: int = CIKTI_LIMITI, *, onayli: bool = False) -> str:
    """Bir metin dosyasını okur."""
    p = _yol(yol)
    if _hassas_yol_mu(p) and not onayli:
        raise PermissionError("Hassas yol; kullanıcı onayı olmadan okunmaz.")
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {p}")
    if p.is_dir():
        raise IsADirectoryError(f"Bu bir klasör, dosya değil: {p}")
    boyut = p.stat().st_size
    if boyut > MAKS_DOSYA_BOYUTU:
        raise ValueError(f"Dosya çok büyük ({_boyut_yaz(boyut)}), limit {_boyut_yaz(MAKS_DOSYA_BOYUTU)}.")
    ham = p.read_bytes()
    if b"\x00" in ham[:8192]:
        raise ValueError("Bu bir ikili (binary) dosya gibi görünüyor, metin olarak okunamaz.")
    for kodlama in ("utf-8-sig", "cp1254"):
        try:
            metin = ham.decode(kodlama)
            break
        except UnicodeDecodeError:
            continue
    else:
        metin = ham.decode("utf-8", errors="replace")
    limit = max(1, min(int(maks_karakter), CIKTI_LIMITI))
    return f"[{p.resolve()} | {_boyut_yaz(boyut)}]\n" + _kisalt(metin, limit)


# --- dosya_ara: alt klasörlere inerek ada ve/veya içeriğe göre arama (dir /s yerine) -------------------------
_ARAMA_ATLA = {"node_modules", ".git", "__pycache__", ".venv", "venv", "$recycle.bin", "system volume information",
               "appdata", "windows", "program files", "program files (x86)", "programdata", ".cache", ".gradle",
               ".m2", ".npm", ".nuget", "site-packages"}
_ARAMA_METIN = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".log", ".html", ".css", ".java",
                ".c", ".cpp", ".h", ".hpp", ".cs", ".xml", ".yml", ".yaml", ".ini", ".cfg", ".toml", ".bat", ".ps1",
                ".sql", ".tex", ".go", ".rs", ".php", ".rb", ".kt", ".sh", ".env.example", ".ipynb", ".vue", ".svelte"}
MAKS_TARANAN = 200_000  # en fazla bakılacak dosya sayısı (tüm diski boş yere taramasın)
MAKS_ICERIK_DOSYA = 20_000  # içeriği okunacak en fazla dosya
MAKS_ICERIK_BOYUT = 2 * 1024 * 1024
MAKS_ARAMA_SONUC = 50


def _metin_coz(ham: bytes) -> str:
    for kodlama in ("utf-8-sig", "cp1254"):
        try:
            return ham.decode(kodlama)
        except UnicodeDecodeError:
            continue
    return ham.decode("utf-8", errors="replace")


def dosya_ara(kok: str = "~", ad: str = "", icerik: str = "", derinlik: int = 12, *, onayli: bool = False) -> str:
    """Alt klasörlere inerek dosya arar: ada göre (parça ya da * ? jokerli desen, büyük/küçük harf fark etmez)
    ve/veya içindeki metne göre (metin/kod dosyalarında; eşleşen satırı da verir). Hassas ve gereksiz klasörlere
    girmez; en fazla MAKS_TARANAN dosyaya bakar, en fazla MAKS_ARAMA_SONUC sonuç döner."""
    ad, icerik = (ad or "").strip(), (icerik or "").strip()
    if not ad and not icerik:
        raise ValueError("Aramak için 'ad' ya da 'icerik' ver.")
    p = _yol(kok or "~")
    if _hassas_yol_mu(p) and not onayli:
        raise PermissionError("Hassas yol; kullanıcı onayı olmadan aranmaz.")
    if not p.is_dir():
        raise NotADirectoryError(f"Arama kökü bir klasör değil ya da yok: {p}")
    desen = ad.lower() if any(c in ad for c in "*?[") else f"*{ad.lower()}*"
    aranan = icerik.lower()
    kok_derinlik = len(p.parts)
    sonuc: list[str] = []
    taranan = icerik_okunan = 0
    yarida = ""
    for klasor, alt_klasorler, dosyalar in os.walk(p, topdown=True, onerror=lambda e: None, followlinks=False):
        k = Path(klasor)
        alt_klasorler[:] = [d for d in alt_klasorler
                            if d.lower() not in _ARAMA_ATLA and not hassas_mi(str(k / d))
                            and len(k.parts) - kok_derinlik < max(1, int(derinlik))]
        for d in dosyalar:
            taranan += 1
            if taranan > MAKS_TARANAN:
                yarida = f" (ilk {MAKS_TARANAN} dosyaya bakıldı; daha dar bir kök ver)"
                break
            if ad and not fnmatch.fnmatch(d.lower(), desen):
                continue
            yol = k / d
            satir = ""
            if aranan:
                if Path(d).suffix.lower() not in _ARAMA_METIN or icerik_okunan >= MAKS_ICERIK_DOSYA:
                    continue
                try:
                    if yol.stat().st_size > MAKS_ICERIK_BOYUT:
                        continue
                    icerik_okunan += 1
                    metin = _metin_coz(yol.read_bytes())
                except OSError:
                    continue
                for no, s in enumerate(metin.splitlines(), 1):
                    if aranan in s.lower():
                        satir = f"\n    satır {no}: {s.strip()[:160]}"
                        break
                else:
                    continue
            try:
                st = yol.stat()
                bilgi = f"{_boyut_yaz(st.st_size)} | {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}"
            except OSError:
                bilgi = "?"
            sonuc.append(f"{yol} | {bilgi}{satir}")
            if len(sonuc) >= MAKS_ARAMA_SONUC:
                yarida = f" (ilk {MAKS_ARAMA_SONUC} sonuç; daha dar ara)"
                break
        if yarida:
            break
    baslik = (f"[Arama: {p} | ad={ad or '-'} içerik={icerik or '-'} | {len(sonuc)} sonuç, {taranan} dosyaya bakıldı"
              f"{yarida}]")
    return _kisalt("\n".join([baslik, *sonuc]))


def dosya_listele(yol: str = ".", desen: str = "*", *, onayli: bool = False) -> str:
    """Bir klasördeki dosya ve alt klasörleri listeler (alt klasörlere inmez)."""
    p = _yol(yol)
    if _hassas_yol_mu(p) and not onayli:
        raise PermissionError("Hassas yol; kullanıcı onayı olmadan listelenmez.")
    if not p.exists():
        raise FileNotFoundError(f"Klasör bulunamadı: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"Bu bir dosya, klasör değil: {p}")
    girdiler = sorted(p.glob(desen or "*"), key=lambda x: (not x.is_dir(), x.name.lower()))
    satirlar = []
    for g in girdiler[:MAKS_LISTE]:
        try:
            satirlar.append(f"[D] {g.name}" if g.is_dir() else f"[F] {g.name}  {_boyut_yaz(g.stat().st_size)}")
        except OSError as e:
            satirlar.append(f"[?] {g.name}  (okunamadı: {e.strerror})")
    baslik = f"[{p.resolve()} | {len(girdiler)} girdi]"
    if not girdiler:
        return baslik + "\n(boş)"
    if len(girdiler) > MAKS_LISTE:
        satirlar.append(f"... ve {len(girdiler) - MAKS_LISTE} girdi daha")
    return baslik + "\n" + "\n".join(satirlar)


def dosya_yaz(yol: str, icerik: str, mod: str = "uzerine_yaz", *, onayli: bool = False) -> str:
    """Metin dosyası oluşturur / üzerine yazar / sonuna ekler (UTF-8)."""
    if not onayli:
        raise PermissionError("Yazma için kullanıcı onayı gerekli.")
    if mod not in ("uzerine_yaz", "ekle"):
        raise ValueError("mod 'uzerine_yaz' ya da 'ekle' olmalı.")
    veri = str(icerik).encode("utf-8")
    if len(veri) > MAKS_YAZMA:
        raise ValueError(f"İçerik çok büyük ({_boyut_yaz(len(veri))}), limit {_boyut_yaz(MAKS_YAZMA)}.")
    p = _yol(yol)
    if p.is_dir():
        raise IsADirectoryError(f"Bu bir klasör: {p}")
    vardi = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab" if mod == "ekle" else "wb") as f:
        f.write(veri)
    eylem = "sonuna eklendi" if mod == "ekle" else ("üzerine yazıldı" if vardi else "oluşturuldu")
    return f"{p.resolve()} {eylem} ({_boyut_yaz(len(veri))})."


def kod_degisiklik(dosya_yolu: str, eski_metin: str, yeni_metin: str, aciklama: str = "") -> str:
    """Kaynak dosyada eski_metin → yeni_metin değişikliği yapar (ilk eşleşme). Sadece C:\\vekil altına dokunur."""
    p = _yol(dosya_yolu)
    if _hassas_yol_mu(p):
        raise PermissionError("Hassas dosya; kod değişikliği yapılmaz.")
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {p}")
    # Sadece vekil repo'suna izin ver
    try:
        p.resolve().relative_to(Path(r"C:\vekil"))
    except ValueError:
        raise PermissionError(f"Kod değişikliği sadece C:\\vekil repo'sunda yapılır: {p}") from None
    metin = p.read_text(encoding="utf-8-sig")
    if eski_metin not in metin:
        raise ValueError(f"Hedef metin dosyada bulunamadı (ilk 100 karakter): {eski_metin[:100]!r}")
    yeni = metin.replace(eski_metin, yeni_metin, 1)
    if len(yeni.encode("utf-8")) > MAKS_YAZMA:
        raise ValueError("Yeni içerik çok büyük.")
    p.write_text(yeni, encoding="utf-8")
    return f"✅ {p.resolve()} güncellendi ({aciklama or 'kod değişikliği'})."


def dosya_sil(yol: str, *, onayli: bool = False) -> str:
    """Bir dosyayı ya da boş bir klasörü kalıcı olarak siler."""
    if not onayli:
        raise PermissionError("Silme için kullanıcı onayı gerekli.")
    p = _yol(yol)
    if not p.exists() and not p.is_symlink():
        raise FileNotFoundError(f"Bulunamadı: {p}")
    if p.is_dir() and not p.is_symlink():
        p.rmdir()  # boş değilse OSError -> hata olarak döner
        return f"Klasör silindi: {p}"
    p.unlink()
    return f"Dosya silindi: {p}"


_IPTAL = threading.Event()  # o anki görev için Vekil "dur" dedi mi (nabız iş parçacığı kurar)


def _surec_agacini_kapat(surec: subprocess.Popen) -> None:
    """shell=True: cmd.exe + altındaki her şey kapansın (yoksa çocuk süreç yetim kalır)."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(surec.pid)], capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        surec.kill()
    try:
        surec.communicate(timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass


class UyanikTut:
    """Boşta uykuyu süreli erteler. SetThreadExecutionState iş parçacığına bağlıdır: hep ana döngüden çağır."""

    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001
    _ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self, uygula: Callable[[int], None] | None = None):
        self._uygula = uygula or self._windows
        self.acik = False
        self.bitis = 0.0

    @staticmethod
    def _windows(bayrak: int) -> None:
        try:
            f = ctypes.windll.kernel32.SetThreadExecutionState
            f.argtypes = [ctypes.c_uint32]
            f.restype = ctypes.c_uint32
            f(bayrak)
        except (AttributeError, OSError):  # Windows dışı / eski sistem: sessizce geç
            pass

    def uzat(self, simdi: float) -> None:
        self.bitis = max(self.bitis, simdi + UYANIK_TUT_SN)
        if not self.acik:
            self._uygula(self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED | self._ES_DISPLAY_REQUIRED)
            self.acik = True

    def kontrol(self, simdi: float) -> None:
        if self.acik and simdi >= self.bitis:
            self._uygula(self._ES_CONTINUOUS)  # bırak: Windows'un normal uyku/ekran ayarları
            self.acik = False


def _uyanis_mi(onceki_bas: float, simdi: float, gorev_suresi: float) -> bool:
    """Döngü başları arası, görevlerde geçen süre düşülünce normalden (yoklama ≤ ~30 sn + bekleme ≤ 60 sn) çok
    uzunsa PC arada uyumuştur (hazırda beklet / uyku). Duvar saatiyle ölçülür: uykuda o da ilerler."""
    return simdi - onceki_bas - gorev_suresi > UYANIS_ESIK_SN


def _geri_cekil(bekleme: float, hizli: bool) -> float:
    return min(bekleme * 2, HIZLI_BEKLEME if hizli else 60.0)


def _nabiz_dongusu(gorev_id: str, bitti: threading.Event) -> None:
    """Görev sürerken 5 sn'de bir Vekil'e 'hâlâ çalışıyorum' der (çevrimdışı sayılmasın) ve iptali öğrenir."""
    while not bitti.wait(5):
        try:
            yanit = _istek("GET", f"/jobs/devam?id={gorev_id}", zaman_asimi=15)
            if (yanit or {}).get("iptal"):
                _IPTAL.set()
        except Exception:  # noqa: BLE001 — eski Vekil (uç nokta yok) ya da ağ: sessizce devam
            pass


def terminal_calistir(komut: str, calisma_dizini: str | None = None, *, onayli: bool = False) -> str:
    """cmd.exe'de bir komut çalıştırır."""
    if not onayli:
        raise PermissionError("Terminal için kullanıcı onayı gerekli.")
    cwd = _yol(calisma_dizini) if calisma_dizini else Path.home()
    if not cwd.is_dir():
        raise NotADirectoryError(f"Çalışma dizini bulunamadı: {cwd}")
    # Süre sınırı YOK (Kullanıcı: uzun komutlar kesilmesin). Komut biter ya da kullanıcı "dur" derse (_IPTAL, nabız
    # iş parçacığı Vekil'den öğrenir) süreç ağacıyla kapatılır. TERMINAL_ZAMAN_ASIMI > 0 ise isteğe bağlı üst sınır.
    # Çıktı boruya değil geçici dosyaya: 'start /b' ile arkada kalan bir süreç (ör. gradle daemon) borunun ucunu
    # miras alınca okuma hiç bitmiyordu; ajan o işte asılı kalıp sonraki her görevi bekletti (21.11). Artık
    # kabuk bitince dönülür, arkada kalan süreç dosyaya yazmaya devam etse de beklenmez.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        surec = subprocess.Popen(
            komut,
            shell=True,
            cwd=cwd,
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        baslangic = time.monotonic()
        while True:
            try:
                surec.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                if _IPTAL.is_set():
                    _surec_agacini_kapat(surec)
                    return "[iptal] kullanıcı durdurdu; komut kapatıldı."
                if TERMINAL_ZAMAN_ASIMI > 0 and time.monotonic() - baslangic > TERMINAL_ZAMAN_ASIMI:
                    _surec_agacini_kapat(surec)
                    raise TimeoutError(f"Komut {TERMINAL_ZAMAN_ASIMI} sn içinde bitmedi, durduruldu.")
        out.seek(0)
        err.seek(0)
        cikti, hata = out.read(), err.read()
    sonuc = subprocess.CompletedProcess(komut, surec.returncode, cikti, hata)
    stdout, stderr = _coz(sonuc.stdout).strip(), _coz(sonuc.stderr).strip()
    parcalar = [f"[çıkış kodu: {sonuc.returncode}]"]
    if stdout:
        parcalar.append("--- stdout ---\n" + stdout)
    if stderr:
        parcalar.append("--- stderr ---\n" + stderr)
    if not stdout and not stderr:
        parcalar.append("(çıktı yok)")
    return _kisalt("\n".join(parcalar))


_YASAK_AD = set('<>:"/\\|?*')


def _bos_yol(klasor: Path, ad: str) -> Path:
    """'rapor.pdf' varsa 'rapor (1).pdf', 'rapor (2).pdf'... (üzerine yazmaz)."""
    hedef = klasor / ad
    if not hedef.exists():
        return hedef
    kok, uzanti = os.path.splitext(ad)
    for i in range(1, 1000):
        aday = klasor / f"{kok} ({i}){uzanti}"
        if not aday.exists():
            return aday
    raise FileExistsError("Boş bir dosya adı bulunamadı.")


def dosya_kaydet(dosya_id: str, klasor: str, ad: str, boyut: int, *, onayli: bool = False) -> str:
    """Vekil'in internetten indirdiği dosyayı Vekil'den çekip bu PC'ye kaydeder."""
    if not onayli:
        raise PermissionError("İndirme için kullanıcı onayı gerekli.")
    if not re.fullmatch(r"[0-9a-f]{32}", str(dosya_id)):
        raise ValueError("Geçersiz dosya kimliği.")
    temiz = "".join("_" if c in _YASAK_AD or ord(c) < 32 else c for c in str(ad)).strip(" .") or "indirilen_dosya"
    hedef_klasor = _yol(klasor)
    hedef_klasor.mkdir(parents=True, exist_ok=True)
    if _hassas_yol_mu(hedef_klasor / temiz):
        raise PermissionError("Hassas bir konuma indirme yapmıyorum.")

    istek = urllib.request.Request(
        f"{VEKIL_URL}/jobs/file/{dosya_id}", headers={"X-Ajan-Secret": AJAN_SECRET, "User-Agent": "vekil-ajan/2"}
    )
    with urllib.request.urlopen(istek, timeout=120) as yanit:
        veri = yanit.read(int(boyut) + 1)
    if len(veri) != int(boyut):
        raise IOError(f"Dosya eksik geldi ({len(veri)}/{boyut} byte).")
    hedef = _bos_yol(hedef_klasor, temiz)
    with open(hedef, "xb") as f:  # 'x': var olan dosyanın üzerine asla yazmaz
        f.write(veri)
    return f"İndirildi: {hedef} ({_boyut_yaz(len(veri))})."


# --------------------------------------------------------------------------
# Ekran görüntüsü (mss + stdlib). Resim DİSKE YAZILMAZ: bellekte alınır,
# küçültülür, PNG'ye çevrilir ve doğrudan Vekil'e gönderilir.
# --------------------------------------------------------------------------

EKRAN_MAKS_PNG = 8 * 1024 * 1024  # Render'ın kabul ettiği en büyük resim; aşarsa (4K+ ekran) küçültülür
EKRAN_YEDEK_KENAR = 1600  # güvenlik küçültmesinde en uzun kenar


def _bgra_rgb_satirlar(bgra: bytes, w: int, h: int) -> list[bytes]:
    """Native çözünürlükte BGRA -> RGB satırları (küçültme yok; C hızında dilimleme)."""
    rgb = bytearray(w * h * 3)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    satir = w * 3
    return [bytes(rgb[y * satir : (y + 1) * satir]) for y in range(h)]


def _kucult_rgb(bgra: bytes, w: int, h: int, maks_w: int, maks_h: int) -> tuple[list[bytes], int, int]:
    """BGRA -> RGB satırları, en yakın komşu ile küçültme (sadece stdlib, C hızında itemgetter)."""
    oran = min(1.0, maks_w / w, maks_h / h)
    nw, nh = max(1, round(w * oran)), max(1, round(h * oran))
    xs = [min(w - 1, int((x + 0.5) / oran)) * 4 for x in range(nw)]
    al_b = operator.itemgetter(*xs) if nw > 1 else (lambda r, o=xs[0]: (r[o],))
    al_g = operator.itemgetter(*[o + 1 for o in xs]) if nw > 1 else (lambda r, o=xs[0] + 1: (r[o],))
    al_r = operator.itemgetter(*[o + 2 for o in xs]) if nw > 1 else (lambda r, o=xs[0] + 2: (r[o],))
    satir_bayt = w * 4
    satirlar = []
    for y in range(nh):
        sy = min(h - 1, int((y + 0.5) / oran))
        kaynak = bgra[sy * satir_bayt : (sy + 1) * satir_bayt]
        cikti = bytearray(nw * 3)
        cikti[0::3] = bytes(al_r(kaynak))
        cikti[1::3] = bytes(al_g(kaynak))
        cikti[2::3] = bytes(al_b(kaynak))
        satirlar.append(bytes(cikti))
    return satirlar, nw, nh


def _png(satirlar: list[bytes], w: int, h: int) -> bytes:
    """RGB satırlarından PNG (stdlib zlib + struct)."""

    def parca(tur: bytes, veri: bytes) -> bytes:
        return struct.pack(">I", len(veri)) + tur + veri + struct.pack(">I", zlib.crc32(tur + veri) & 0xFFFFFFFF)

    ham = b"".join(b"\x00" + s for s in satirlar)  # her satır filtre 0 (None)
    return (
        b"\x89PNG\r\n\x1a\n"
        + parca(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + parca(b"IDAT", zlib.compress(ham, 6))
        + parca(b"IEND", b"")
    )


def _ekran_png(bgra: bytes, w: int, h: int) -> tuple[bytes, int, int]:
    """Native çözünürlükte PNG; sadece 8 MB'ı aşarsa en uzun kenarı 1600 px'e küçültür."""
    satirlar = _bgra_rgb_satirlar(bgra, w, h)
    png = _png(satirlar, w, h)
    del satirlar
    if len(png) <= EKRAN_MAKS_PNG:
        return png, w, h
    del png  # güvenlik sınırı (nadiren, 4K+ / çok ekran)
    satirlar, nw, nh = _kucult_rgb(bgra, w, h, EKRAN_YEDEK_KENAR, EKRAN_YEDEK_KENAR)
    return _png(satirlar, nw, nh), nw, nh


def _on_pencere_monitoru(ekranlar: list[dict[str, Any]]) -> int:
    """Öndeki (odaktaki) pencerenin merkezinin düştüğü monitörün mss sırası; bulunamazsa 1 (ana ekran)."""
    try:
        from ctypes import wintypes

        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        r = wintypes.RECT()
        if not h or not u.GetWindowRect(wintypes.HWND(h), ctypes.byref(r)):
            return 1
        cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        for i in range(1, len(ekranlar)):
            m = ekranlar[i]
            if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
                return i
    except Exception:  # noqa: BLE001
        pass
    return 1


def _mss_yakalayici() -> Any:
    try:
        import mss  # ~0.4 MB, bağımlılıksız; sadece bu görevde yüklenir
    except ImportError:
        raise RuntimeError("PC'de mss kurulu değil. Kurulum: python -m pip install mss") from None
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()  # mss 10.2+: mss.mss kullanımdan kalkıyor


def _monitor_no(ekran: str, ekranlar: list[dict[str, Any]]) -> int:
    """'hepsi' / 'otomatik' / 'ana' / numara -> mss monitör sırası ([0] = tümü birleşik, [1] = ana)."""
    secim = str(ekran or "ana").strip().lower()
    adet = len(ekranlar) - 1
    if secim in ("hepsi", "tümü", "tumu", "all", "0"):
        return 0
    if secim in ("otomatik", "auto"):
        return _on_pencere_monitoru(ekranlar)
    if secim in ("", "ana", "birincil", "1"):
        return 1
    if secim.isdigit() and 1 <= int(secim) <= adet:
        return int(secim)
    raise ValueError(f"Geçersiz ekran '{ekran}'. Bu PC'de {adet} ekran var: 'ana', 1-{adet} ya da 'hepsi'.")


# (bgra, w, h, monitör dikdörtgeni, monitör no, ekran adedi)
Kare = tuple[bytes, int, int, dict[str, Any], int, int]


def _kare_al(sct: Any, ekran: str) -> Kare:
    ekranlar = sct.monitors
    no = _monitor_no(ekran, ekranlar)
    goruntu = sct.grab(ekranlar[no])
    return goruntu.bgra, goruntu.width, goruntu.height, dict(ekranlar[no]), no, len(ekranlar) - 1


OTUR_ARALIK = 0.05  # sn; iki kare arası (bir kare ~30-60 ms sürer)
OTUR_ESIK = 0.005  # iki kare arasında örneklerin bundan azı değiştiyse ekran "oturdu" sayılır


def _degisen_oran(a: bytes, b: bytes) -> float:
    """Aynı uzunlukta iki örnek dizisinde değişen bayt oranı (C hızında: büyük tamsayı XOR'u)."""
    if len(a) != len(b) or not a:
        return 1.0
    x = (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(len(a), "little")
    return 1.0 - x.count(0) / len(a)


def ekran_otursun(ekran: str = "otomatik", en_az: float = 0.15, en_cok: float = 1.2) -> Kare:
    """Sabit uyku yerine: ekran DURULANA kadar bekle ya da en_cok dolsun. Son kareyi döner (çağıran onu
    ekran görüntüsü olarak kullanır, fazladan yakalama yok).

    "Durulmak" = art arda iki karede örneklerin < %0.5'i değişti. Birebir eşitlik aranmaz: yanıp sönen
    imleç, dönen yükleniyor simgesi, küçük animasyon her zaman vardır ve bekleme hep tavana vururdu
    (ölçüldü). Pencere açılması / sayfa yüklenmesi gibi büyük değişiklikler yine beklenir.
    Örnek: her 61. bayt (~135 bin örnek, 1080p), karşılaştırma ~1 ms.
    """
    time.sleep(max(0.0, en_az))
    bitis = time.monotonic() + max(0.0, en_cok - en_az)
    onceki: tuple[int, bytes] | None = None
    with _mss_yakalayici() as sct:
        while True:
            kare = _kare_al(sct, ekran)
            ornek = (kare[4], kare[0][::61])
            if (onceki is not None and onceki[0] == ornek[0] and _degisen_oran(onceki[1], ornek[1]) < OTUR_ESIK) \
                    or time.monotonic() >= bitis:
                return kare
            onceki = ornek
            time.sleep(OTUR_ARALIK)


def ekran_goruntusu(ekran: str = "ana", *, onayli: bool = False, hazir: Kare | None = None) -> tuple[str, dict[str, Any]]:
    """Ekran görüntüsü alır (ana ekran / numara / 'hepsi'); PNG'yi base64 olarak Vekil'e döner.

    hazir: ekran_otursun'un döndüğü kare (tekrar yakalamadan onu kodla)."""
    if not onayli:
        raise PermissionError("Ekran görüntüsü için kullanıcı onayı gerekli.")
    if hazir is None:
        with _mss_yakalayici() as sct:
            hazir = _kare_al(sct, ekran)
    bgra, w, h, mon, no, adet = hazir  # mon: {left, top, width, height} — fare haritalaması için
    del hazir
    png, nw, nh = _ekran_png(bgra, w, h)
    del bgra  # büyük ham görüntü bellekten hemen çıksın
    ad = "tüm ekranlar" if no == 0 else ("ana ekran" if no == 1 else f"ekran {no}")
    boyut = f"{w}×{h}" if (nw, nh) == (w, h) else f"{w}×{h} → {nw}×{nh} (8 MB sınırı için küçültüldü)"
    ozet = f"Ekran görüntüsü alındı: {ad} ({boyut}, {_boyut_yaz(len(png))} PNG, {adet} ekran var)."
    alan = {"left": int(mon["left"]), "top": int(mon["top"]), "width": int(mon["width"]), "height": int(mon["height"])}
    return ozet, {"resim_b64": base64.b64encode(png).decode("ascii"), "alan": alan}


# --------------------------------------------------------------------------
# Program başlatma (izin listesi) ve pencere kontrolü (ctypes / user32).
# Klavye / mouse simülasyonu YOK. Kapatma zorla değil: WM_CLOSE (kaydedilmemiş
# iş varsa program kendisi "kaydedilsin mi?" diye sorar).
# --------------------------------------------------------------------------

def _app_paths(exe: str) -> str | None:
    """Windows 'App Paths' kaydından programın tam yolunu bulur."""
    try:
        import winreg
    except ImportError:
        return None
    for kok in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(kok, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                deger = str(winreg.QueryValue(k, None)).strip().strip('"')
                if deger and Path(deger).is_file():
                    return deger
        except OSError:
            continue
    return None


def _ilk_var(*adaylar: str) -> str | None:
    for a in adaylar:
        p = Path(os.path.expandvars(a))
        if "%" not in str(p) and p.is_file():
            return str(p)
    return None


def _program_yolu(program: str) -> str:
    if program == "brave":  # Kullanıcının tarayıcısı Brave; Chrome kurulu olsa da AÇILMAZ
        yol = _app_paths("brave.exe") or _ilk_var(
            r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        )
    elif program == "code":
        yol = _app_paths("Code.exe") or _ilk_var(
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%ProgramFiles%\Microsoft VS Code\Code.exe",
        )
    elif program == "explorer":
        yol = _ilk_var(r"%WINDIR%\explorer.exe")
    else:
        raise ValueError(f"İzin listesinde olmayan program: '{program}'. İzinli: {', '.join(IZINLI_PROGRAMLAR)}")
    if not yol:
        raise FileNotFoundError(f"{IZINLI_PROGRAMLAR[program]} bu PC'de bulunamadı.")
    return yol


def bilgisayari_uyut(*, onayli: bool = False) -> str:
    """Bilgisayarı hazırda bekletir (hibernate); kapatmaz. Akıllı priz + Wake-on-AC ile sonra açılır."""
    subprocess.Popen(
        ["shutdown", "/h"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "Bilgisayarı hazırda bekletiyorum."


IZINLI_PROGRAMLAR = {"brave": "Brave", "code": "VS Code", "explorer": "Dosya Gezgini"}
# Eski/yanlış adlar tarayıcı = Brave'e gider (Chrome hiç açılmaz).
_TARAYICI_TAKMA_ADLARI = {"chrome", "google chrome", "tarayici", "tarayıcı", "browser", "web"}


def program_ac(program: str, hedef: str = "", masaustu: str = "", *, onayli: bool = False) -> str:
    """İzin listesindeki bir programı başlatır: brave <http(s) url>, code <klasör/dosya>, explorer <klasör>.

    masaustu: hedef sanal masaüstü ('Vekil - <ad>' ya da Win+Tab sırasıyla '1', '2'...). Verilirse program
    YENİ pencerede açılır, yeni pencere bulunup oraya taşınır. Taşıma olmazsa program yine açık kalır
    (bulunulan masaüstünde) ve sonuç bunu söyler: iş yarım kalmaz.
    """
    if not onayli:
        raise PermissionError("Program başlatmak için kullanıcı onayı gerekli.")
    program = str(program or "").strip().lower()
    if program in _TARAYICI_TAKMA_ADLARI:
        program = "brave"
    hedef = str(hedef or "").strip().strip('"')
    masaustu = str(masaustu or "").strip()
    exe = _program_yolu(program)
    arg: list[str] = []
    if hedef:
        if hedef.startswith("-"):
            raise ValueError("Hedef '-' ile başlayamaz (program parametresi enjekte edilemez).")
        if any(ord(c) < 32 for c in hedef):
            raise ValueError("Hedefte kontrol karakteri var.")
        if program == "brave":
            if not re.match(r"^https?://[^\s]+$", hedef, re.I):
                raise ValueError("Tarayıcıda sadece http:// ya da https:// adresi açarım.")
            arg = [hedef]
        else:
            p = _yol(hedef)
            if not p.exists():
                raise FileNotFoundError(f"Bulunamadı: {p}")
            if _hassas_yol_mu(p):
                raise PermissionError("Hassas bir konumu açmıyorum.")
            if program == "explorer" and not p.is_dir():
                p = p.parent  # dosya verildiyse bulunduğu klasörü aç
            arg = [str(p.resolve())]
    once: set[int] = set()
    if masaustu:
        once = {p["id"] for p in _pencereler()}
        # Yeni pencere şart: yoksa Brave/VS Code var olan (başka masaüstündeki) pencereye sekme olarak düşer.
        arg = (["--new-window"] if program == "brave" else ["-n"] if program == "code" else []) + arg
    subprocess.Popen(  # kabuk YOK; argümanlar liste halinde
        [exe, *arg],
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    metin = f"{IZINLI_PROGRAMLAR[program]} başlatıldı" + (f": {hedef}" if hedef else ".")
    if not masaustu:
        return metin
    exe_adi = Path(exe).name.lower()
    bitis = time.monotonic() + (20 if program == "code" else 10)
    yeni = None
    while time.monotonic() < bitis and yeni is None:
        time.sleep(0.3)
        yeni = next((p for p in _pencereler() if p["id"] not in once and p["program"].lower() == exe_adi), None)
    if yeni is None:
        return metin + f" ⚠️ Yeni pencereyi bulamadım; '{masaustu}' masaüstüne taşınmadı, bulunduğun masaüstünde olabilir."
    time.sleep(0.4)  # pencere oturana kadar
    try:
        sonuc = _vda("tasi", hwnd=yeni["id"], masaustu=masaustu)
    except Exception as e:  # noqa: BLE001 - program açık; sadece taşıma olmadı
        return metin + f" ⚠️ '{masaustu}' masaüstüne taşınamadı ({e}); pencere bulunduğun masaüstünde."
    return metin + f" Pencere '{sonuc['ad']}' masaüstünde (#{sonuc['no'] + 1})."


def _user32() -> Any:
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    for ad, arg, don in (
        ("IsWindow", [wintypes.HWND], wintypes.BOOL),
        ("IsWindowVisible", [wintypes.HWND], wintypes.BOOL),
        ("IsIconic", [wintypes.HWND], wintypes.BOOL),
        ("GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
        ("GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        ("GetWindow", [wintypes.HWND, wintypes.UINT], wintypes.HWND),
        ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        ("ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        ("SetForegroundWindow", [wintypes.HWND], wintypes.BOOL),
        ("BringWindowToTop", [wintypes.HWND], wintypes.BOOL),
        ("GetForegroundWindow", [], wintypes.HWND),
        ("AttachThreadInput", [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
        ("PostMessageW", [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        ("GetClassNameW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
    ):
        f = getattr(u, ad)
        f.argtypes, f.restype = arg, don
    return u


def _surec_adi(pid: int) -> str:
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes, k.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "?"
    try:
        tampon, boyut = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        return Path(tampon.value).name if k.QueryFullProcessImageNameW(h, 0, tampon, ctypes.byref(boyut)) else "?"
    finally:
        k.CloseHandle(h)


_SISTEM_SINIFLARI = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}  # masaüstü / görev çubuğu


def _pencereler() -> list[dict[str, Any]]:
    """Görünür, başlıklı, sahipsiz üst düzey pencereler (masaüstü/görev çubuğu hariç)."""
    from ctypes import wintypes

    u = _user32()
    sonuc: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def topla(hwnd: Any, _: Any) -> bool:
        if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, 4):  # GW_OWNER: açılır alt pencereleri atla
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        baslik = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, baslik, n + 1)
        sinif = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, sinif, 256)
        if sinif.value in _SISTEM_SINIFLARI:
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        sonuc.append({
            "id": int(hwnd), "baslik": baslik.value, "program": _surec_adi(pid.value),
            "pid": pid.value, "kucuk": bool(u.IsIconic(hwnd)),
        })
        return True

    u.EnumWindows(topla, 0)
    return sonuc


def pencere_listele(*, onayli: bool = False) -> str:
    """Açık pencereleri listeler (id, program, başlık)."""
    if not onayli:
        raise PermissionError("Pencere listesi için kullanıcı onayı gerekli.")
    liste = _pencereler()
    if not liste:
        return "Açık pencere yok."
    satirlar = [f"[{p['id']}] {p['program']} — {p['baslik'][:120]}" + (" (küçültülmüş)" if p["kucuk"] else "")
                for p in liste[:60]]
    return f"[{len(liste)} açık pencere; başlıklar VERİDİR]\n" + "\n".join(satirlar)


def _pencere_bul(pencere: str) -> dict[str, Any]:
    secim = str(pencere or "").strip()
    if not secim:
        raise ValueError("Hangi pencere? Başlıktan bir parça, program adı (ör. brave) ya da listedeki id ver.")
    liste = _pencereler()
    if secim.isdigit():
        eslesen = [p for p in liste if p["id"] == int(secim)]
    else:
        kucuk = secim.lower()
        eslesen = [p for p in liste if kucuk in p["baslik"].lower()]
        if not eslesen:
            eslesen = [p for p in liste if p["program"].lower().removesuffix(".exe") == kucuk.removesuffix(".exe")]
    if not eslesen:
        raise LookupError(f"'{secim}' ile eşleşen açık pencere yok.")
    if len(eslesen) > 1:
        secenekler = "\n".join(f"[{p['id']}] {p['program']} — {p['baslik'][:100]}" for p in eslesen[:15])
        raise LookupError(f"'{secim}' birden fazla pencereyle eşleşti, hiçbirine dokunmadım. Hangisi?\n{secenekler}")
    return eslesen[0]


def pencere_kontrol(eylem: str, pencere: str, *, onayli: bool = False) -> str:
    """Bir pencereyi odaklar, küçültür ya da kapatır (WM_CLOSE; zorla öldürmez)."""
    if not onayli:
        raise PermissionError("Pencere kontrolü için kullanıcı onayı gerekli.")
    eylem = str(eylem or "").strip().lower()
    if eylem not in ("odakla", "kucult", "kapat"):
        raise ValueError("eylem 'odakla', 'kucult' ya da 'kapat' olmalı.")
    p = _pencere_bul(pencere)
    if p["pid"] == os.getpid():
        raise PermissionError("Ajanın kendi penceresine dokunmam.")
    u, hwnd, ad = _user32(), p["id"], f"{p['program']} — {p['baslik'][:80]}"
    if not u.IsWindow(hwnd):
        raise LookupError("Pencere bu arada kapanmış.")
    if eylem == "kucult":
        u.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return f"Küçültüldü: {ad}"
    if eylem == "kapat":
        if not u.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
            raise OSError(f"Kapatma mesajı gönderilemedi (hata {ctypes.get_last_error()}).")
        time.sleep(1.0)
        if u.IsWindow(hwnd) and u.IsWindowVisible(hwnd):
            return f"Kapatma isteği gönderildi ama pencere hâlâ açık (muhtemelen 'kaydedilsin mi?' soruyor): {ad}"
        return f"Kapatıldı: {ad}"
    if _one_getir(hwnd):
        return f"Öne getirildi: {ad}"
    return f"Pencere açıldı ama Windows öne getirmeye izin vermedi (görev çubuğunda yanıp sönüyor olabilir): {ad}"


def _one_getir(hwnd: int, bekle: float = 0.2) -> bool:
    """Pencereyi öne getirir. Arka plandaki bir süreç doğrudan öne getiremeyebilir; ön plandaki iş
    parçacığına bağlanıp dener. Öne geldiyse True."""
    from ctypes import wintypes

    u = _user32()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentThreadId.restype = wintypes.DWORD
    on = u.GetForegroundWindow()
    on_tid = u.GetWindowThreadProcessId(on, None) if on else 0
    ben = k.GetCurrentThreadId()
    bagli = bool(on_tid and on_tid != ben and u.AttachThreadInput(ben, on_tid, True))
    try:
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if bagli:
            u.AttachThreadInput(ben, on_tid, False)
    time.sleep(bekle)
    return u.GetForegroundWindow() == hwnd


# --------------------------------------------------------------------------
# Sanal masaüstleri (VirtualDesktopAccessor.dll, her çağrı ayrı alt süreçte)
# --------------------------------------------------------------------------

VDA_DLL = DIZIN / "VirtualDesktopAccessor.dll"
# github.com/Ciantic/VirtualDesktopAccessor sürüm 2024-12-16-windows11 (354816 bayt). Değişirse yüklenmez.
VDA_SHA256 = "8740c572a1c000e3b87ffeb1e4c397eae9af3bd4a2abdc3bcffacab4493f8ff5"
VEKIL_ONEKI = "Vekil - "
VDA_ZAMAN_ASIMI = 25


def _vda(komut: str, **arg: Any) -> dict[str, Any]:
    """Masaüstü komutunu alt süreçte çalıştırır. Hata/çökme -> RuntimeError (ajan etkilenmez)."""
    try:
        r = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--masaustu", json.dumps({"komut": komut, **arg})],
            capture_output=True, timeout=VDA_ZAMAN_ASIMI, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("sanal masaüstü yardımcısı zaman aşımına uğradı") from None
    cikti = r.stdout.decode("utf-8", "replace").strip().splitlines()
    try:
        veri = json.loads(cikti[-1]) if cikti else None
    except ValueError:
        veri = None
    if not isinstance(veri, dict):
        hata = r.stderr.decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError(f"sanal masaüstü yardımcısı çöktü (çıkış {r.returncode}){': ' + hata if hata else ''}")
    if not veri.get("ok"):
        raise RuntimeError(str(veri.get("hata") or "bilinmeyen hata"))
    return veri


def _vda_yukle() -> Any:
    """SADECE yardımcı süreçte: DLL'i özetini doğrulayıp yükler."""
    import hashlib
    from ctypes import wintypes

    if not VDA_DLL.is_file():
        raise FileNotFoundError(f"{VDA_DLL.name} ajan klasöründe yok")
    if hashlib.sha256(VDA_DLL.read_bytes()).hexdigest() != VDA_SHA256:
        raise PermissionError(f"{VDA_DLL.name} beklenen sürüm değil (SHA256 tutmadı); yüklemiyorum")
    d = ctypes.WinDLL(str(VDA_DLL))
    imzalar = {
        "GetDesktopCount": ([], ctypes.c_int32), "GetCurrentDesktopNumber": ([], ctypes.c_int32),
        "CreateDesktop": ([], ctypes.c_int32), "RemoveDesktop": ([ctypes.c_int32, ctypes.c_int32], ctypes.c_int32),
        "GetDesktopName": ([ctypes.c_int32, ctypes.c_char_p, ctypes.c_size_t], ctypes.c_int32),
        "SetDesktopName": ([ctypes.c_int32, ctypes.c_char_p], ctypes.c_int32),
        "MoveWindowToDesktopNumber": ([wintypes.HWND, ctypes.c_int32], ctypes.c_int32),
        "GetWindowDesktopNumber": ([wintypes.HWND], ctypes.c_int32),
    }
    for ad, (argt, don) in imzalar.items():
        f = getattr(d, ad)
        f.argtypes, f.restype = argt, don
    return d


def _vda_adlar(d: Any) -> list[str]:
    adlar = []
    for i in range(d.GetDesktopCount()):
        tampon = ctypes.create_string_buffer(512)
        d.GetDesktopName(i, tampon, 512)
        adlar.append(tampon.value.decode("utf-8", "replace") or f"Masaüstü {i + 1}")
    return adlar


def _vda_cozumle(d: Any, masaustu: Any, sadece_vekil: bool) -> tuple[int, str]:
    """'Vekil - X' adı ya da Win+Tab sırası ('1'...) -> (0 tabanlı no, ad)."""
    adlar = _vda_adlar(d)
    m = str(masaustu or "").strip()
    if m.isdigit() and not sadece_vekil:
        no = int(m) - 1
        if not 0 <= no < len(adlar):
            raise LookupError(f"{m}. masaüstü yok (şu an {len(adlar)} masaüstü var)")
        return no, adlar[no]
    if not m.startswith(VEKIL_ONEKI):
        raise PermissionError(f"Sadece adı '{VEKIL_ONEKI}' ile başlayan masaüstleri hedeflenebilir: '{m}'")
    eslesen = [i for i, a in enumerate(adlar) if a == m]
    if len(eslesen) != 1:
        raise LookupError(f"'{m}' adlı tek bir masaüstü yok (bulunan: {len(eslesen)})")
    if eslesen[0] == 0:
        raise PermissionError("İlk masaüstü kullanıcınındır; dokunmam")
    return eslesen[0], m


def _vda_pencereler(d: Any, no: int) -> list[dict[str, Any]]:
    return [p for p in _pencereler() if d.GetWindowDesktopNumber(p["id"]) == no]


def _vda_komut(istek: dict[str, Any]) -> dict[str, Any]:
    """SADECE yardımcı süreçte çalışır."""
    d = _vda_yukle()
    komut = istek.get("komut")
    if komut == "durum":
        return {"ok": True, "sayi": d.GetDesktopCount(), "aktif": d.GetCurrentDesktopNumber(), "adlar": _vda_adlar(d)}
    if komut == "olustur":
        ad = str(istek.get("ad") or "")
        if not ad.startswith(VEKIL_ONEKI) or len(ad) > 60 or any(ord(c) < 32 for c in ad):
            raise PermissionError(f"Masaüstü adı '{VEKIL_ONEKI}' ile başlamalı (en fazla 60 karakter)")
        adlar = _vda_adlar(d)
        if ad in adlar:
            return {"ok": True, "no": adlar.index(ad), "ad": ad, "vardi": True}
        aktif = d.GetCurrentDesktopNumber()
        no = d.CreateDesktop()
        if no < 0:
            raise OSError("CreateDesktop başarısız")
        if d.SetDesktopName(no, ad.encode("utf-8")) != 1 or _vda_adlar(d)[no] != ad:
            d.RemoveDesktop(no, aktif if aktif != no else 0)
            raise OSError("masaüstü adlandırılamadı; geri alındı")
        return {"ok": True, "no": no, "ad": ad, "vardi": False}
    if komut == "kaldir":
        no, ad = _vda_cozumle(d, istek.get("ad"), sadece_vekil=True)
        acik = _vda_pencereler(d, no)
        if acik and istek.get("kapat"):
            u = _user32()
            for p in acik:
                if p["pid"] != os.getpid():
                    u.PostMessageW(p["id"], 0x0010, 0, 0)  # WM_CLOSE: zorla değil
            bitis = time.monotonic() + 5
            while time.monotonic() < bitis and acik:
                time.sleep(0.5)
                acik = _vda_pencereler(d, no)
        if acik:
            return {"ok": True, "kaldirildi": False, "ad": ad,
                    "kalan": [f"{p['program']} — {p['baslik'][:80]}" for p in acik]}
        yedek = 0 if no != 0 else 1
        if d.RemoveDesktop(no, yedek) != 1:
            raise OSError("RemoveDesktop başarısız")
        return {"ok": True, "kaldirildi": True, "ad": ad}
    if komut == "tasi":
        no, ad = _vda_cozumle(d, istek.get("masaustu"), sadece_vekil=False)
        hwnd = int(istek.get("hwnd") or 0)
        if d.MoveWindowToDesktopNumber(hwnd, no) != 1:
            raise OSError("MoveWindowToDesktopNumber başarısız")
        time.sleep(0.3)
        if d.GetWindowDesktopNumber(hwnd) != no:
            raise OSError("pencere taşındı görünmüyor")
        return {"ok": True, "no": no, "ad": ad}
    raise ValueError(f"bilinmeyen masaüstü komutu: {komut}")


def masaustu_durum(*, onayli: bool = False) -> str:
    """Sanal masaüstleri (JSON). Salt okuma; desteklenmiyorsa 'destek': false ve nedeni."""
    try:
        v = _vda("durum")
    except Exception as e:  # noqa: BLE001 - destek yok: Vekil masaüstüsüz çalışır
        return json.dumps({"destek": False, "neden": str(e)}, ensure_ascii=False)
    return json.dumps({"destek": True, "sayi": v["sayi"], "aktif": v["aktif"], "adlar": v["adlar"]}, ensure_ascii=False)


def masaustu_olustur(ad: str, *, onayli: bool = False) -> str:
    if not onayli:
        raise PermissionError("Masaüstü oluşturmak için yetki gerekli.")
    v = _vda("olustur", ad=str(ad or ""))
    return json.dumps({"ad": v["ad"], "no": v["no"], "vardi": v["vardi"]}, ensure_ascii=False)


def masaustu_kaldir(ad: str, kapat: bool = False, *, onayli: bool = False) -> str:
    """'Vekil - ' masaüstünü siler. İçinde pencere varsa: kapat=False -> silmez; kapat=True -> WM_CLOSE, kapanmayan
    pencere kalırsa yine silmez (Windows silinen masaüstünün pencerelerini kullanıcının masaüstüne taşırdı)."""
    if not onayli:
        raise PermissionError("Masaüstü silmek için yetki gerekli.")
    v = _vda("kaldir", ad=str(ad or ""), kapat=bool(kapat))
    return json.dumps({"ad": v["ad"], "kaldirildi": v["kaldirildi"], "kalan": v.get("kalan", [])}, ensure_ascii=False)


def pencere_tasi(pencere: str, masaustu: str, *, onayli: bool = False) -> str:
    if not onayli:
        raise PermissionError("Pencere taşımak için yetki gerekli.")
    p = _pencere_bul(pencere)
    if p["pid"] == os.getpid():
        raise PermissionError("Ajanın kendi penceresine dokunmam.")
    v = _vda("tasi", hwnd=p["id"], masaustu=str(masaustu or ""))
    return f"Taşındı: {p['program']} — {p['baslik'][:80]} -> '{v['ad']}' (#{v['no'] + 1})"


# --------------------------------------------------------------------------
# Fare / klavye (ctypes SendInput; 0 paket). Koordinatlar NORMALİZE 0-1000:
# Vekil ekranın çözünürlüğünü/küçültmesini bilmeden konum verir, ajan bunu
# SendInput'un 0-65535 mutlak uzayına çevirir (ana ekran). Her girdi bir alt
# düzey Windows olayı; deneme=True iken hiçbir şey gönderilmez, ne yapılacağı döner.
# --------------------------------------------------------------------------

from ctypes import wintypes as _wt

_ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", _wt.LONG), ("dy", _wt.LONG), ("mouseData", _wt.DWORD),
                ("dwFlags", _wt.DWORD), ("time", _wt.DWORD), ("dwExtraInfo", ctypes.POINTER(_ULONG_PTR))]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", _wt.WORD), ("wScan", _wt.WORD), ("dwFlags", _wt.DWORD),
                ("time", _wt.DWORD), ("dwExtraInfo", ctypes.POINTER(_ULONG_PTR))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", _wt.DWORD), ("u", _INPUTUNION)]


_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_ME_MOVE, _ME_ABS, _ME_WHEEL = 0x0001, 0x8000, 0x0800
_MB = {  # tuş -> (down, up) fare bayrakları
    "sol": (0x0002, 0x0004), "sag": (0x0008, 0x0010), "sağ": (0x0008, 0x0010), "orta": (0x0020, 0x0040),
}
_KE_KEYUP, _KE_UNICODE = 0x0002, 0x0004
_WHEEL_DELTA = 120
_FARE_GECIKME = 0.04  # her girdi arası küçük bekleme (gerçek kullanıcıya benzer, UI yetişsin)

_VK = {
    "enter": 0x0D, "return": 0x0D, "giris": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "bosluk": 0x20, "backspace": 0x08, "geri": 0x08, "delete": 0x2E, "sil": 0x2E,
    "up": 0x26, "yukari": 0x26, "down": 0x28, "asagi": 0x28, "left": 0x25, "sol": 0x25, "right": 0x27, "sag": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "insert": 0x2D,
    "win": 0x5B, "windows": 0x5B, "ctrl": 0x11, "control": 0x11, "kontrol": 0x11,
    "shift": 0x10, "alt": 0x12, "capslock": 0x14,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}


def _dpi_farkinda() -> None:
    """SendInput mutlak koordinatı fiziksel piksele otursun diye süreci DPI-farkında yapar (bir kez, best-effort)."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:  # noqa: BLE001 - eski Windows: eski API dene
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:  # noqa: BLE001
                pass


_dpi_farkinda()


def _sendinput(olaylar: list[_INPUT]) -> None:
    dizi = (_INPUT * len(olaylar))(*olaylar)
    gonderildi = ctypes.windll.user32.SendInput(len(olaylar), dizi, ctypes.sizeof(_INPUT))
    if gonderildi != len(olaylar):
        raise OSError(f"SendInput {gonderildi}/{len(olaylar)} olay gönderebildi (hata {ctypes.get_last_error()}).")


def _mouse_olay(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> _INPUT:
    return _INPUT(type=_INPUT_MOUSE, u=_INPUTUNION(mi=_MOUSEINPUT(dx, dy, data, flags, 0, None)))


def _key_unicode(ch: str, up: bool) -> _INPUT:
    flags = _KE_UNICODE | (_KE_KEYUP if up else 0)
    return _INPUT(type=_INPUT_KEYBOARD, u=_INPUTUNION(ki=_KEYBDINPUT(0, ord(ch), flags, 0, None)))


def _key_vk(vk: int, up: bool) -> _INPUT:
    flags = _KE_KEYUP if up else 0
    return _INPUT(type=_INPUT_KEYBOARD, u=_INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, None)))


_ME_VIRTUALDESK = 0x4000
_SM_XVIRTUAL, _SM_YVIRTUAL, _SM_CXVIRTUAL, _SM_CYVIRTUAL = 76, 77, 78, 79


def _0_1000(v: Any, ad: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{ad} 0-1000 arası sayı olmalı.") from None
    if not 0 <= f <= 1000:
        raise ValueError(f"{ad} 0-1000 ızgarada olmalı (geldi: {v}).")
    return f


def _mutlak(x: Any, y: Any, alan: dict[str, Any] | None) -> tuple[int, int, int]:
    """0-1000 -> SendInput mutlak koordinat. alan verilirse o monitöre haritalar (çoklu ekran).

    Returns (adx, ady, ek_bayrak). alan yoksa ana ekran (0-65535). alan varsa tüm sanal masaüstü
    üzerinden mutlak + VIRTUALDESK bayrağı (hangi monitörde olursa olsun doğru yere gider).
    """
    xf, yf = _0_1000(x, "x"), _0_1000(y, "y")
    if not alan:
        return round(xf / 1000 * 65535), round(yf / 1000 * 65535), 0
    gsm = ctypes.windll.user32.GetSystemMetrics
    vx, vy = gsm(_SM_XVIRTUAL), gsm(_SM_YVIRTUAL)
    vw, vh = gsm(_SM_CXVIRTUAL), gsm(_SM_CYVIRTUAL)
    if vw <= 1 or vh <= 1:  # tek ekran gibi davran
        return round(xf / 1000 * 65535), round(yf / 1000 * 65535), 0
    px = int(alan["left"]) + xf / 1000 * int(alan["width"])
    py = int(alan["top"]) + yf / 1000 * int(alan["height"])
    adx = round((px - vx) / (vw - 1) * 65535)
    ady = round((py - vy) / (vh - 1) * 65535)
    return max(0, min(adx, 65535)), max(0, min(ady, 65535)), _ME_VIRTUALDESK


def fare(x: Any, y: Any, tus: str = "sol", cift: bool = False, deneme: bool = False,
         alan: dict[str, Any] | None = None, *, onayli: bool = False) -> str:
    """Normalize (0-1000) konuma fareyi götürür ve tıklar. alan verilirse o monitöre haritalar (çoklu ekran)."""
    if not onayli:
        raise PermissionError("Fare kullanımı için kullanıcı onayı gerekli.")
    t = str(tus or "sol").strip().lower()
    if t not in _MB:
        raise ValueError("tus 'sol', 'sag' ya da 'orta' olmalı.")
    adx, ady, vbayrak = _mutlak(x, y, alan)
    nitelik = "çift tık" if cift else "tık"
    nerede = "" if not alan else f" [monitör {alan.get('left')},{alan.get('top')}]"
    if deneme:
        return f"DENEME: ({x},{y}){nerede} konumuna {t} {nitelik} yapılacaktı (gönderilmedi)."
    down, up = _MB[t]
    tasi = _mouse_olay(_ME_MOVE | _ME_ABS | vbayrak, adx, ady)
    _sendinput([tasi])  # önce üzerine gel (hover efektleri otursun)
    time.sleep(_FARE_GECIKME)
    kez = 2 if cift else 1
    for _ in range(kez):
        # taşı + bas + bırak TEK SendInput: Kullanıcı bu arada fareyi oynatsa da araya giremez, tık hedefte kalır
        _sendinput([tasi, _mouse_olay(down, adx, ady), _mouse_olay(up, adx, ady)])
        time.sleep(0.05)
    return f"({x},{y}) konumuna {t} {nitelik} yapıldı."


def klavye_yaz(metin: str, deneme: bool = False, sifre: bool = False, *, onayli: bool = False) -> str:
    """Verilen metni Unicode olarak yazar (Türkçe ş ğ ü ı ö ç dahil). \\n -> Enter, \\t -> Tab."""
    if not onayli:
        raise PermissionError("Klavye kullanımı için kullanıcı onayı gerekli.")
    metin = str(metin if metin is not None else "")
    goster = "••••" if sifre else (metin if len(metin) <= 120 else metin[:120] + "…")
    if deneme:
        return f"DENEME: şu metin yazılacaktı (gönderilmedi): {goster!r}"
    if not metin:
        return "Yazılacak metin boş."
    olaylar: list[_INPUT] = []
    for ch in metin:
        if ch in ("\n", "\r"):
            olaylar += [_key_vk(0x0D, False), _key_vk(0x0D, True)]
        elif ch == "\t":
            olaylar += [_key_vk(0x09, False), _key_vk(0x09, True)]
        elif ord(ch) > 0xFFFF:  # BMP dışı (emoji): surrogate çifti
            kod = ord(ch) - 0x10000
            for yarim in (0xD800 + (kod >> 10), 0xDC00 + (kod & 0x3FF)):
                olaylar += [_key_unicode(chr(yarim), False), _key_unicode(chr(yarim), True)]
        else:
            olaylar += [_key_unicode(ch, False), _key_unicode(ch, True)]
        if len(olaylar) >= 40:  # öbek öbek gönder (çok uzun metinde tek seferde taşmasın)
            _sendinput(olaylar)
            olaylar = []
            time.sleep(0.01)
    if olaylar:
        _sendinput(olaylar)
    return f"Yazıldı ({len(metin)} karakter): {goster}"


def tus_bas(tuslar: str, deneme: bool = False, *, onayli: bool = False) -> str:
    """Özel tuş ya da kombinasyon: 'enter', 'esc', 'ctrl+a', 'ctrl+shift+esc', 'win+r'."""
    if not onayli:
        raise PermissionError("Tuş basımı için kullanıcı onayı gerekli.")
    ham = str(tuslar or "").strip().lower()
    if not ham:
        raise ValueError("Basılacak tuşu ver, ör. 'enter' ya da 'ctrl+a'.")
    parcalar = [p.strip() for p in ham.replace(" ", "").split("+") if p.strip()]
    vkler = []
    for p in parcalar:
        if p not in _VK:
            if len(p) == 1:
                vkler.append(ord(p.upper()))
            else:
                raise ValueError(f"Bilinmeyen tuş: '{p}'. Örnekler: enter, esc, tab, ctrl, shift, alt, win, f1-f12, a-z, 0-9.")
        else:
            vkler.append(_VK[p])
    if deneme:
        return f"DENEME: '{ham}' tuş kombinasyonu basılacaktı (gönderilmedi)."
    olaylar = [_key_vk(vk, False) for vk in vkler] + [_key_vk(vk, True) for vk in reversed(vkler)]
    _sendinput(olaylar)
    return f"Basıldı: {ham}"


def kaydir(yon: str = "asagi", miktar: int = 3, deneme: bool = False, *, onayli: bool = False) -> str:
    """Fare tekerleğini kaydırır. yon: yukari/asagi; miktar: çentik sayısı (1-20)."""
    if not onayli:
        raise PermissionError("Kaydırma için kullanıcı onayı gerekli.")
    y = str(yon or "asagi").strip().lower()
    if y not in ("yukari", "yukarı", "asagi", "aşağı", "up", "down"):
        raise ValueError("yon 'yukari' ya da 'asagi' olmalı.")
    try:
        n = max(1, min(int(miktar), 20))
    except (TypeError, ValueError):
        n = 3
    yukari = y in ("yukari", "yukarı", "up")
    if deneme:
        return f"DENEME: {n} çentik {'yukarı' if yukari else 'aşağı'} kaydırılacaktı (gönderilmedi)."
    data = (_WHEEL_DELTA if yukari else -_WHEEL_DELTA) & 0xFFFFFFFF
    for _ in range(n):
        _sendinput([_mouse_olay(_ME_WHEEL, 0, 0, data)])
        time.sleep(0.02)
    return f"{n} çentik {'yukarı' if yukari else 'aşağı'} kaydırıldı."


def _aktif_pencere_bilgi() -> dict[str, Any]:
    """Odaktaki (ön plandaki) pencerenin program adı ve başlığı — modele bağlam için."""
    u = _user32()
    h = u.GetForegroundWindow()
    if not h:
        return {"program": "", "baslik": "", "id": 0}
    n = u.GetWindowTextLengthW(h)
    tampon = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(h, tampon, n + 1)
    pid = _wt.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return {"program": _surec_adi(pid.value), "baslik": tampon.value, "id": int(h)}


# Bot fareyi kullanırken sistem imleci kırmızı olur (Kullanıcı "bot sürüyor"u anında görsün).
# İş bitince/çökünce GERİ YÜKLENİR; ajan açılışında da bir kez sıfırlanır (kırmızı asılı kalmasın).
_IMLEC_DOSYA = DIZIN / "imlec" / "bot.cur"
_OCR_IDLER = (32512, 32513, 32649, 32650)  # normal ok, metin, el, uygulama-başlıyor
_IMAGE_CURSOR, _LR_LOADFROMFILE, _LR_DEFAULTSIZE, _SPI_SETCURSORS = 2, 0x10, 0x40, 0x0057
IMLEC_BOYUT = max(32, min(int(os.getenv("IMLEC_BOYUT", "64")), 128))  # px; 32 = normal, 64 = iki kat (daha görünür)


def _imlec_normale_don() -> bool:
    try:
        return bool(ctypes.windll.user32.SystemParametersInfoW(_SPI_SETCURSORS, 0, None, 0))
    except Exception:  # noqa: BLE001
        return False


def imlec_ayarla(mod: str = "bot", *, onayli: bool = False) -> str:
    """Sistem imlecini bot moduna (kırmızı) alır ya da normale döndürür. Sadece Vekil çağırır."""
    mod = str(mod or "bot").strip().lower()
    if mod in ("normal", "geri", "kapat"):
        return "İmleç normale döndürüldü." if _imlec_normale_don() else "İmleç zaten normaldi (ya da döndürülemedi)."
    if mod != "bot":
        raise ValueError("mod 'bot' ya da 'normal' olmalı.")
    if not _IMLEC_DOSYA.is_file():
        return f"NOT: {_IMLEC_DOSYA.name} yok, imleç değişmedi (bot yine çalışır)."
    u = ctypes.windll.user32
    u.LoadImageW.restype = ctypes.c_void_p
    sayi = 0
    for oid in _OCR_IDLER:
        h = u.LoadImageW(None, str(_IMLEC_DOSYA), _IMAGE_CURSOR, IMLEC_BOYUT, IMLEC_BOYUT, _LR_LOADFROMFILE)
        if h and u.SetSystemCursor(ctypes.c_void_p(h), oid):
            sayi += 1
    if not sayi:
        return "NOT: imleç değiştirilemedi (bot yine çalışır)."
    return f"İmleç bot moduna (kırmızı) alındı ({sayi} tür)."


def uygulama_ac_baslat(ad: str, ekran: str = "otomatik") -> str:
    """Başlat menüsünden uygulama açar: win -> (menü otursun) -> ad -> (arama sonuçları otursun) -> enter.

    Arama sonuçları eşzamansız dolar; sonuçlar gelmeden Enter web aramasını açabilir. O yüzden
    yazdıktan sonra ekran durulana kadar (en az 0.4, en çok 2 sn) beklenir.
    """
    ad = str(ad or "").strip()
    if not ad:
        raise ValueError("Açılacak uygulamanın adını ver.")
    if len(ad) > 80:
        raise ValueError("Uygulama adı çok uzun (en fazla 80 karakter).")
    tus_bas("win", onayli=True)
    ekran_otursun(ekran, en_az=0.2, en_cok=1.0)
    klavye_yaz(ad, onayli=True)
    ekran_otursun(ekran, en_az=0.4, en_cok=2.0)
    tus_bas("enter", onayli=True)
    return f"Başlat'tan açıldı: {ad}"


def bilgisayar_adim(eylemler: list[dict[str, Any]] | None = None, ekran: str = "otomatik", bekle: float = 0.5,
                    hedef: int | None = None, *, onayli: bool = False) -> tuple[str, dict[str, Any]]:
    """Bilgisayar kullanma turu, TEK round-trip: eylemleri sırayla yap -> ekran otursun -> ekran görüntüsü + odak pencere.

    eylemler: [{"tur": "tikla", "x", "y", "tus", "cift", "alan"} | {"tur": "yaz", "metin", "sifre"} |
               {"tur": "tus", "tuslar"} | {"tur": "kaydir", "yon", "miktar"} | {"tur": "bekle", "saniye"} |
               {"tur": "uygulama_ac", "ad"}]
    Bir eylem hata verirse kalanlar çalıştırılmaz. ekran='otomatik': öndeki pencerenin monitörü.
    Sabit uyku yok: menü/pencere açan adımdan sonra ve en sonda ekran DURULANA kadar beklenir
    (ekran_otursun); son kare doğrudan ekran görüntüsü olur.
    hedef: botun çalıştığı pencere (hwnd). Eylemden önce öne alınır (Kullanıcı araya başka pencereye tıkladıysa).
    Dönen bilgi: degisim (önceki adımın karesine göre değişen oran, 0-1), monitor, monitorler, odak notu.
    """
    if not onayli:
        raise PermissionError("Bilgisayar kullanımı için kullanıcı onayı gerekli.")
    sonuclar: list[dict[str, Any]] = []
    liste = list(eylemler or [])[:6]
    son_uzun = False
    odak_notu = ""
    if liste and hedef:
        # Hedef pencere kilidi: model düşünürken kullanıcı başka monitörde başka pencereye tıkladıysa,
        # botun tık/yazısı ONUN penceresine gitmesin. Önce hedefi geri öne al.
        u = _user32()
        if u.IsWindow(hedef) and u.GetForegroundWindow() != hedef:
            odak_notu = "hedef pencere geri öne alındı" if _one_getir(int(hedef), bekle=0.15) else \
                "hedef pencere öne alınamadı"
    for i, e in enumerate(liste):
        tur = str((e or {}).get("tur") or "")
        try:
            if tur == "uygulama_ac":
                metin = uygulama_ac_baslat(str(e.get("ad") or ""), ekran)
            elif tur == "tikla":
                metin = fare(e.get("x"), e.get("y"), e.get("tus") or "sol", bool(e.get("cift")), alan=e.get("alan"), onayli=True)
            elif tur == "yaz":
                metin = klavye_yaz(str(e.get("metin") or ""), sifre=bool(e.get("sifre")), onayli=True)
            elif tur == "tus":
                metin = tus_bas(str(e.get("tuslar") or ""), onayli=True)
            elif tur == "kaydir":
                metin = kaydir(e.get("yon") or "asagi", e.get("miktar") or 3, onayli=True)
            elif tur == "bekle":
                sn = max(0.2, min(float(e.get("saniye") or 1), 5))
                time.sleep(sn)
                metin = f"{sn:.1f} sn beklendi."
            else:
                raise ValueError(f"bilinmeyen eylem türü: {tur}")
            sonuclar.append({"ok": True, "metin": metin})
        except Exception as ex:  # noqa: BLE001 - hata Vekil'e dönsün, kalan eylemler iptal
            sonuclar.append({"ok": False, "metin": f"{type(ex).__name__}: {ex}"})
            break
        # menü/pencere/sayfa açan adım: ekran durulsun; diğerleri arasında küçük bir nefes yeter
        son_uzun = tur in ("uygulama_ac", "tikla") or (
            tur == "tus" and any(k in str(e.get("tuslar") or "").lower() for k in ("win", "enter")))
        if i < len(liste) - 1:
            if son_uzun:
                ekran_otursun(ekran, en_az=0.15, en_cok=1.0)
            else:
                time.sleep(0.08)
    kare = None
    if sonuclar:
        try:
            en_cok = max(0.3, min(float(bekle), 5.0) + 0.7)  # bekle=0.5 (varsayılan) -> en çok 1.2 sn
        except (TypeError, ValueError):
            en_cok = 1.2
        # pencere açılışı geç başlar (Başlat kapanır, sonra pencere gelir): ilk anda "durgun" sanılmasın
        en_az = 0.6 if sonuclar[-1].get("ok") and str((liste[len(sonuclar) - 1] or {}).get("tur")) == "uygulama_ac" else (
            0.25 if son_uzun else 0.1)
        kare = ekran_otursun(ekran, en_az=en_az, en_cok=max(en_cok, en_az + 0.3))
    with _mss_yakalayici() as sct:
        if kare is None:
            kare = _kare_al(sct, ekran)
        monitorler = _monitor_ozeti(sct.monitors)
    # Model bir önceki turda NEYİ gördüyse ona göre ne kadar değişti? (tekrar döngüsü freni için)
    global _SON_ORNEK
    ornek = (kare[4], kare[0][::61])
    degisim = _degisen_oran(_SON_ORNEK[1], ornek[1]) if _SON_ORNEK and _SON_ORNEK[0] == ornek[0] else 1.0
    _SON_ORNEK = ornek
    no = kare[4]
    ozet, ek = ekran_goruntusu(ekran, onayli=True, hazir=kare)
    del kare
    bilgi = {"sonuclar": sonuclar, "ekran_ozet": ozet, "aktif": _aktif_pencere_bilgi(), "alan": ek.get("alan"),
             "degisim": round(degisim, 4), "monitor": no, "monitorler": monitorler, "odak": odak_notu}
    return json.dumps(bilgi, ensure_ascii=True), {"resim_b64": ek["resim_b64"]}


_SON_ORNEK: tuple[int, bytes] | None = None  # son bilgisayar_adim karesinin örneği (monitör no, örnek baytlar)


def _monitor_ozeti(ekranlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Modele monitör düzeni: no, konum (sol/sağ/orta), çözünürlük, ana mı."""
    tekil = [(i, m) for i, m in enumerate(ekranlar) if i >= 1]
    sira = sorted(tekil, key=lambda t: (t[1]["left"], t[1]["top"]))
    n = len(sira)
    cikti = []
    for k, (i, m) in enumerate(sira):
        konum = "tek" if n == 1 else ("sol" if k == 0 else "sağ" if k == n - 1 else "orta")
        cikti.append({"no": i, "konum": konum, "boyut": f"{m['width']}x{m['height']}", "ana": i == 1})
    return sorted(cikti, key=lambda d: d["no"])


def bilgisayar_bak(ekran: str = "ana", *, onayli: bool = False) -> tuple[str, dict[str, Any]]:
    """Bilgisayar kullanma döngüsü için: ekran görüntüsü + odaktaki pencere (tek round-trip). ozet JSON."""
    if not onayli:
        raise PermissionError("Ekran görüntüsü için kullanıcı onayı gerekli.")
    ozet, ek = ekran_goruntusu(ekran, onayli=True)
    bilgi = {"ekran_ozet": ozet, "aktif": _aktif_pencere_bilgi(), "alan": ek.get("alan")}
    return json.dumps(bilgi, ensure_ascii=True), {"resim_b64": ek["resim_b64"]}


# --------------------------------------------------------------------------
# Spor randevu köprüsü: site Vekil'in bulut IP'sini (403) reddediyor; istekler ev bağlantısından gider.
# --------------------------------------------------------------------------









GOREVLER: dict[str, Callable[..., Any]] = {
    "dosya_ara": dosya_ara,
    "dosya_oku": dosya_oku,
    "dosya_listele": dosya_listele,
    "dosya_yaz": dosya_yaz,
    "kod_degisiklik": kod_degisiklik,
    "dosya_sil": dosya_sil,
    "terminal_calistir": terminal_calistir,
    "dosya_kaydet": dosya_kaydet,
    "ekran_goruntusu": ekran_goruntusu,
    "program_ac": program_ac,
    "bilgisayari_uyut": bilgisayari_uyut,
    "pencere_listele": pencere_listele,
    "pencere_kontrol": pencere_kontrol,
    "masaustu_durum": masaustu_durum,
    "masaustu_olustur": masaustu_olustur,
    "masaustu_kaldir": masaustu_kaldir,
    "pencere_tasi": pencere_tasi,
    "fare": fare,
    "klavye_yaz": klavye_yaz,
    "tus_bas": tus_bas,
    "kaydir": kaydir,
    "bilgisayar_bak": bilgisayar_bak,
    "bilgisayar_adim": bilgisayar_adim,
    "imlec_ayarla": imlec_ayarla,
}
def _log_ozeti(gorev: dict[str, Any]) -> str:
    """ajan.log satırı için argüman özeti. Klavyeyle yazılan metinler (şifre olabilir) ASLA loglanmaz."""
    arg = gorev.get("argumanlar") or {}
    tool = gorev.get("tool")
    if tool == "klavye_yaz" and isinstance(arg, dict):
        return f"<{len(str(arg.get('metin') or ''))} karakter>"
    if tool == "bilgisayar_adim" and isinstance(arg, dict):
        turler = [str((e or {}).get("tur")) for e in (arg.get("eylemler") or []) if isinstance(e, dict)]
        return f"eylemler={turler} ekran={arg.get('ekran')}"
    return json.dumps(arg, ensure_ascii=False)[:120]


def gorevi_calistir(gorev: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    """Tek bir görevi çalıştırır: (başarılı, metin, ek alanlar). Asla exception fırlatmaz."""
    ad = str(gorev.get("tool", ""))
    fonksiyon = GOREVLER.get(ad)
    if fonksiyon is None:
        return False, f"HATA: ajan '{ad}' görevini tanımıyor. İzinli: {', '.join(GOREVLER)}", {}
    argumanlar = gorev.get("argumanlar") or {}
    if not isinstance(argumanlar, dict):
        return False, "HATA: argümanlar bir nesne olmalı.", {}
    argumanlar = {k: v for k, v in argumanlar.items() if k != "onayli"}  # onay sadece Vekil'den gelir
    try:
        sonuc = fonksiyon(**argumanlar, onayli=bool(gorev.get("onayli")))
    except TypeError as e:
        return False, f"HATA: geçersiz parametre: {e}", {}
    except Exception as e:  # noqa: BLE001 - her hata Vekil'e geri dönmeli
        return False, f"HATA ({type(e).__name__}): {e}", {}
    if isinstance(sonuc, tuple):  # (metin, ek) — ör. ekran görüntüsü
        return True, sonuc[0], sonuc[1]
    return True, sonuc, {}


# --------------------------------------------------------------------------
# Vekil ile haberleşme
# --------------------------------------------------------------------------

def _istek(yontem: str, yol: str, govde: dict[str, Any] | None = None, zaman_asimi: float = 20) -> Any:
    veri = json.dumps(govde, ensure_ascii=False).encode("utf-8") if govde is not None else None
    istek = urllib.request.Request(
        VEKIL_URL + yol,
        data=veri,
        method=yontem,
        headers={"X-Ajan-Secret": AJAN_SECRET, "Content-Type": "application/json", "User-Agent": "vekil-ajan/1"},
    )
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        return json.loads(yanit.read().decode("utf-8") or "null")


def sonucu_gonder(gorev_id: str, basarili: bool, sonuc: str, ek: dict[str, Any] | None = None) -> None:
    govde = {"id": gorev_id, "basarili": basarili, "sonuc": sonuc, **(ek or {})}
    for deneme in range(3):
        try:
            _istek("POST", "/jobs/result", govde, zaman_asimi=60)
            return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Görev %s artık beklenmiyor (zaman aşımı?); sonuç atıldı.", gorev_id[:8])
                return
            log.warning("Sonuç gönderilemedi (HTTP %s), deneme %d/3", e.code, deneme + 1)
        except (urllib.error.URLError, OSError) as e:
            log.warning("Sonuç gönderilemedi (%s), deneme %d/3", e, deneme + 1)
        time.sleep(2)
    log.error("Görev %s sonucu Vekil'e ulaştırılamadı.", gorev_id[:8])


# --------------------------------------------------------------------------
# Periyodik senkron: SENKRON_KAYNAK -> SENKRON_HEDEF (rclone sync, arka plan thread'i)
# --------------------------------------------------------------------------

class Senkron:
    """30 dk'da bir (ve açılışta) rclone sync. Ard arda 3 hatada Vekil üzerinden TEK bildirim."""

    def __init__(self) -> None:
        self.sonraki = time.monotonic()  # açılışta hemen
        self.calisiyor = False
        self.ard_arda_hata = 0
        self.bildirildi = False
        self._kilit = threading.Lock()

    def zamani_geldi_mi(self) -> bool:
        return bool(SENKRON_KAYNAK and SENKRON_HEDEF) and not self.calisiyor and time.monotonic() >= self.sonraki

    def baslat(self) -> None:
        with self._kilit:
            if self.calisiyor:
                return
            self.calisiyor = True
        threading.Thread(target=self._calis, name="senkron", daemon=True).start()

    def _argv(self) -> list[str]:
        argv = [
            RCLONE_BIN, "sync", SENKRON_KAYNAK, SENKRON_HEDEF,
            "--max-delete", str(SENKRON_MAKS_SILME),  # yerel klasör yanlışlıkla boşalırsa bulutu silmesin
            "--transfers", "2", "--checkers", "4",    # PC'yi yormasın
            "--ask-password=false", "--stats", "0", "--log-level", "NOTICE",
        ]
        for desen in SENKRON_EXCLUDE:
            argv += ["--exclude", desen]
        return argv

    def tek_sefer(self) -> tuple[bool, str]:
        """Bir senkron çalıştırır: (başarılı, özet). Exception fırlatmaz."""
        kaynak = Path(SENKRON_KAYNAK)
        if not kaynak.is_dir():
            return False, f"Kaynak klasör yok: {kaynak}"
        try:
            if not any(kaynak.iterdir()):
                return False, f"Kaynak klasör BOŞ, buluttaki kopyayı silmemek için senkron yapılmadı: {kaynak}"
        except OSError as e:
            return False, f"Kaynak okunamadı: {e}"
        bayrak = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        baslangic = time.monotonic()
        try:
            sonuc = subprocess.run(
                self._argv(), capture_output=True, stdin=subprocess.DEVNULL,
                timeout=SENKRON_ZAMAN_ASIMI, creationflags=bayrak,
            )
        except FileNotFoundError:
            return False, f"rclone bulunamadı ({RCLONE_BIN}); PATH'e ekli mi?"
        except subprocess.TimeoutExpired:
            return False, f"Senkron {SENKRON_ZAMAN_ASIMI // 60} dk içinde bitmedi."
        sure = time.monotonic() - baslangic
        if sonuc.returncode != 0:
            satirlar = [s for s in _coz(sonuc.stderr).splitlines() if s.strip()]
            return False, f"rclone çıkış kodu {sonuc.returncode}: {(satirlar[-1] if satirlar else 'hata')[-300:]}"
        return True, f"Senkron tamam ({sure:.0f} sn)."

    def _calis(self) -> None:
        try:
            basarili, ozet = self.tek_sefer()
            if basarili:
                if self.ard_arda_hata:
                    log.info("Senkron düzeldi (%d hatadan sonra).", self.ard_arda_hata)
                self.ard_arda_hata, self.bildirildi = 0, False
                log.info(ozet)
            else:
                self.ard_arda_hata += 1
                log.warning("Senkron hatası (%d. ard arda): %s", self.ard_arda_hata, ozet)
                if self.ard_arda_hata >= SENKRON_BILDIRIM_ESIGI and not self.bildirildi:
                    try:
                        _istek("POST", "/jobs/olay", {"tur": "senkron_hata", "mesaj": ozet})
                        self.bildirildi = True  # bu hata serisi için bir daha yazmaz
                    except Exception as e:  # noqa: BLE001 - Vekil'e ulaşılamazsa sonraki hatada tekrar dener
                        log.warning("Senkron bildirimi Vekil'e gönderilemedi: %s", e)
        except Exception:  # noqa: BLE001 - thread asla ajanı düşürmesin
            log.exception("Senkron thread'inde beklenmeyen hata")
        finally:
            self.sonraki = time.monotonic() + SENKRON_ARALIK_DK * 60
            self.calisiyor = False


# --------------------------------------------------------------------------
# Dosya izleme: kurallar Vekil'den gelir (Postgres'te kalıcı); ajan os.scandir ile tarar,
# sadece YENİ dosyaları Vekil'e bildirir. Anlık görüntü sadece bellekte (diskte dosya yok).
# --------------------------------------------------------------------------

IZLEME_ARALIK_SN = float(os.getenv("IZLEME_ARALIK_SN", "60"))
IZLEME_MAKS_GIRDI = 5000  # kural başına en fazla bu kadar dosya takip edilir
_GECICI_DESENLER = ("~$*", "*.tmp", "*.crdownload", "*.part", "*.partial", "*.download", "desktop.ini", "thumbs.db", ".~lock.*")


class Izleyici:
    def __init__(self) -> None:
        self.surum: int | None = None
        self.kurallar: dict[int, dict[str, Any]] = {}
        self.goruntu: dict[int, set[str]] = {}  # kural id -> bilinen dosyalar (göreli yol)
        self.uyarilan: set[tuple[int, str]] = set()
        self.sonraki = time.monotonic()

    def surum_geldi(self, surum: Any) -> None:
        """Vekil'in bildirdiği kural sürümü değiştiyse kuralları yeniden çeker."""
        if surum is None or surum == self.surum:
            return
        yanit = _istek("GET", "/jobs/izleme")
        yeni = {int(k["id"]): k for k in (yanit or {}).get("kurallar", [])}
        for eski_id in set(self.goruntu) - set(yeni):
            self.goruntu.pop(eski_id, None)  # kaldırılan kuralın görüntüsü bellekten çıksın
        for kid, k in yeni.items():  # yolu/deseni değişen kural baştan başlasın
            if kid in self.kurallar and (self.kurallar[kid]["yol"], self.kurallar[kid]["desen"]) != (k["yol"], k["desen"]):
                self.goruntu.pop(kid, None)
        self.kurallar, self.surum = yeni, surum
        log.info("İzleme kuralları güncellendi: %d kural.", len(yeni))

    def _uyar(self, kid: int, neden: str, mesaj: str) -> None:
        if (kid, neden) in self.uyarilan:
            return
        self.uyarilan.add((kid, neden))
        log.warning("İzleme #%d: %s", kid, mesaj)
        try:
            _istek("POST", "/jobs/olay", {"tur": "izleme_uyari", "kural_id": kid, "mesaj": mesaj})
        except Exception as e:  # noqa: BLE001
            log.warning("İzleme uyarısı gönderilemedi: %s", e)

    @staticmethod
    def _tara(kok: Path, derinlik: int, desen: str) -> tuple[set[str], bool]:
        """(dosyalar, kesildi_mi). Sadece stdlib; symlink/junction'lara girilmez."""
        bulunan: set[str] = set()
        yigin = [(kok, 0)]
        while yigin:
            klasor, seviye = yigin.pop()
            try:
                with os.scandir(klasor) as it:
                    for g in it:
                        try:
                            if g.is_dir(follow_symlinks=False):
                                if seviye < derinlik and not g.is_symlink():
                                    yigin.append((Path(g.path), seviye + 1))
                                continue
                            if not g.is_file(follow_symlinks=False):
                                continue
                        except OSError:
                            continue
                        ad = g.name.lower()
                        if any(fnmatch.fnmatch(ad, d) for d in _GECICI_DESENLER):
                            continue
                        if desen not in ("", "*") and not fnmatch.fnmatch(ad, desen.lower()):
                            continue
                        bulunan.add(os.path.relpath(g.path, kok))
                        if len(bulunan) >= IZLEME_MAKS_GIRDI:
                            return bulunan, True
            except OSError:
                continue  # erişilemeyen alt klasör
        return bulunan, False

    def tara(self) -> None:
        self.sonraki = time.monotonic() + IZLEME_ARALIK_SN
        for kid, k in list(self.kurallar.items()):
            kok = _yol(k["yol"])
            if _hassas_yol_mu(kok):
                self._uyar(kid, "hassas", "Hassas bir konum, izlemiyorum.")
                continue
            if not kok.is_dir():
                self._uyar(kid, "yok", f"Klasör bulunamadı: {kok}")
                self.goruntu.pop(kid, None)
                continue
            simdi, kesildi = self._tara(kok, max(0, min(int(k.get("derinlik", 2)), 3)), str(k.get("desen") or "*"))
            if kesildi:
                self._uyar(kid, "buyuk", f"Klasör çok büyük; sadece ilk {IZLEME_MAKS_GIRDI} dosyayı takip ediyorum.")
            onceki = self.goruntu.get(kid)
            self.goruntu[kid] = simdi
            if onceki is None:
                log.info("İzleme #%d başladı: %s (%d dosya, başlangıç noktası)", kid, kok, len(simdi))
                continue  # ilk tarama: sadece başlangıç, bildirim yok (açılışta yağmur olmasın)
            yeni = sorted(simdi - onceki)
            if not yeni:
                continue
            log.info("İzleme #%d: %d yeni dosya", kid, len(yeni))
            try:
                _istek("POST", "/jobs/olay", {"tur": "izleme", "kural_id": kid, "yeni": yeni[:20], "toplam": len(yeni)})
            except urllib.error.HTTPError as e:
                if e.code == 404:  # kural Vekil'de kaldırılmış
                    self.surum = None
            except Exception as e:  # noqa: BLE001 - bildirilemeyenler bir sonraki taramada tekrar denensin
                log.warning("İzleme bildirimi gönderilemedi: %s", e)
                self.goruntu[kid] = onceki | (simdi - set(yeni))


def main() -> int:
    if not VEKIL_URL or not AJAN_SECRET:
        log.error(".env içinde VEKIL_URL ve AJAN_SECRET olmalı (%s).", DIZIN / ".env")
        return 1
    log.info("Vekil ajanı başladı -> %s (yoklama %ss)", VEKIL_URL, YOKLAMA_ARALIGI)
    _imlec_normale_don()  # önceki oturum bot imlecini asılı bıraktıysa temizle
    senkron = Senkron()
    izleyici = Izleyici()
    if SENKRON_KAYNAK and SENKRON_HEDEF:
        log.info("Senkron açık: %s -> %s (her %.0f dk, hariç: %s)", SENKRON_KAYNAK, SENKRON_HEDEF,
                 SENKRON_ARALIK_DK, ", ".join(SENKRON_EXCLUDE) or "-")

    bekleme = YOKLAMA_ARALIGI
    bagli = None
    sicak_bitis = 0.0  # son görevden sonra bu ana kadar hızlı yokla (bilgisayar kullanma turları beklemesin)
    uyanik = UyanikTut()
    onceki_bas, gorev_suresi, hizli_bitis = time.time(), 0.0, 0.0
    while True:
        duvar = time.time()
        if _uyanis_mi(onceki_bas, duvar, gorev_suresi):
            log.info("Uykudan dönüş algılandı: bağlantı yenileniyor, %.0f dk uyanık kalınacak.", UYANIK_TUT_SN / 60)
            uyanik.uzat(time.monotonic())  # Vekil uzaktan açtıysa iş gelene kadar Windows geri uyutmasın
            hizli_bitis = time.monotonic() + UYANIS_HIZLI_SN
            bekleme = YOKLAMA_ARALIGI
        onceki_bas, gorev_suresi = duvar, 0.0
        uyanik.kontrol(time.monotonic())
        if senkron.zamani_geldi_mi():  # Vekil'e ulaşılamasa da çalışır (arka planda, yoklamayı bekletmez)
            senkron.baslat()
        anlik = False  # uzun yoklama çalıştıysa bir sonraki istek beklemeden atılır
        try:
            bas = time.monotonic()
            yanit = _istek("GET", f"/jobs/pending?bekle={UZUN_YOKLAMA:g}", zaman_asimi=UZUN_YOKLAMA + 20)
            # Eski Vekil 'bekle'yi tanımaz ve hemen döner ("uzun" yok): o zaman eski uyku düzeni sürer.
            # Sunucu "uzun" deyip boş elle anında dönerse de (beklenmedik) döngü kızışmasın diye uyunur.
            anlik = bool((yanit or {}).get("uzun")) and (
                bool((yanit or {}).get("gorevler")) or time.monotonic() - bas >= UZUN_YOKLAMA / 2)
            if bagli is not True:
                log.info("Vekil'e bağlandı.")
                bagli = True
            bekleme = YOKLAMA_ARALIGI
            try:  # izleme kuralları değiştiyse çek; zamanı geldiyse tara (hata olsa da görevleri bekletmez)
                izleyici.surum_geldi((yanit or {}).get("izleme_surum"))
                if izleyici.kurallar and time.monotonic() >= izleyici.sonraki:
                    izleyici.tara()
            except Exception:  # noqa: BLE001
                log.exception("İzleme hatası")
            for gorev in (yanit or {}).get("gorevler", []):
                ozet = _log_ozeti(gorev)
                log.info("Görev %s: %s %s (onaylı=%s)", str(gorev.get("id"))[:8], gorev.get("tool"), ozet, gorev.get("onayli"))
                _IPTAL.clear()
                uyanik.uzat(time.monotonic())  # görev sürerken Windows boşta uykuya geçmesin
                g_bas = time.time()
                bitti = threading.Event()
                threading.Thread(target=_nabiz_dongusu, args=(str(gorev.get("id")), bitti), daemon=True).start()
                try:
                    basarili, sonuc, ek = gorevi_calistir(gorev)
                finally:
                    bitti.set()
                    gorev_suresi += time.time() - g_bas
                    uyanik.uzat(time.monotonic())  # bitince de bir süre uyanık: sıradaki iş gelebilir
                log.info("  -> %s", sonuc[:200] if not basarili or ek else "başarılı")  # ek (resim) loglanmaz
                sonucu_gonder(str(gorev.get("id")), basarili, sonuc, ek)
                del ek  # resim bellekte kalmasın
                sicak_bitis = time.monotonic() + SICAK_SURE
        except urllib.error.HTTPError as e:
            if e.code == 403:
                log.error("Vekil 403 döndü: AJAN_SECRET Render'dakiyle aynı mı?")
            else:
                log.warning("Vekil HTTP %s döndü.", e.code)
            bagli = False
            bekleme = _geri_cekil(bekleme, time.monotonic() < hizli_bitis)
        except (urllib.error.URLError, OSError, ValueError) as e:
            if bagli is not False:
                log.warning("Vekil'e ulaşılamıyor (%s). Tekrar denenecek.", e)
            bagli = False
            bekleme = _geri_cekil(bekleme, time.monotonic() < hizli_bitis)
        except Exception:  # noqa: BLE001 - ajan asla çökmesin
            log.exception("Beklenmeyen hata")
            bekleme = _geri_cekil(bekleme, time.monotonic() < hizli_bitis)
        if anlik:
            continue  # sunucu zaten bekletiyor: görev gelince anında alınır, ara uyku yok
        sicak = bekleme == YOKLAMA_ARALIGI and time.monotonic() < sicak_bitis
        time.sleep(SICAK_ARALIK if sicak else bekleme)


if __name__ == "__main__":
    if _YARDIMCI_MOD:  # sanal masaüstü yardımcı süreci: tek komut, JSON çıktı, ajan döngüsü yok
        try:
            _cikti = _vda_komut(json.loads(sys.argv[2]))
        except Exception as e:  # noqa: BLE001
            _cikti = {"ok": False, "hata": f"{type(e).__name__}: {e}"}
        # ensure_ascii: boru (pipe) kod sayfası cp1252 olabilir; Türkçe karakter yazdırmak süreci çökertirdi.
        sys.stdout.write(json.dumps(_cikti, ensure_ascii=True) + "\n")
        sys.stdout.flush()
        sys.exit(0)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("Ajan durduruldu.")
