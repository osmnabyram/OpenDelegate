"""Vekil kurulum sihirbazı: solda resim, sağda sorular, altta İleri/Geri. Sonunda .env dosyasını yazar.

Çalıştır: python kurulum.py          (pencere açılır)
          python kurulum.py --cli    (pencere yoksa ya da istenirse terminalde sorar)
Sadece standart kütüphane kullanır. Anahtarlar yalnızca yerel .env dosyasına yazılır.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

KOK = Path(__file__).resolve().parent
RESIM = KOK / "docs" / "assets" / "vekil_kurulum.png"

# --------------------------------------------------------------------------
# Sayfa tanımları: GUI ve terminal aynı listeyi kullanır
# alan: (anahtar, etiket, tur, secenekler/varsayilan)   tur: yazi | gizli | secim | coklu
# --------------------------------------------------------------------------
KULLANIM = ["Dosya ve bilgisayar işleri", "Hatırlatma ve planlama", "Araştırma ve haber", "Yazılım ve kod",
            "Müşteri / iş takibi", "Telefon asistanı (sesli)"]

SAYFALAR: list[dict[str, Any]] = [
    {"baslik": "Vekil'e hoş geldiniz",
     "metin": "Vekil, bilgisayarınızı ve telefonunuzu yazarak ya da konuşarak yöneten kişisel yapay zeka asistanınızdır.\n\n"
              "Bu sihirbaz sizi birkaç soruyla tanır, anahtarlarınızı doğrular ve kurulumu bitirir. "
              "Yaklaşık 3 dakika sürer.",
     "alanlar": []},
    {"baslik": "Sizi tanıyalım",
     "metin": "Vekil'in sizinle çalışma biçimi bu cevaplara göre şekillenir. Sonradan sohbetten de değiştirebilirsiniz.",
     "alanlar": [("KULLANICI_ADI", "İsminiz", "yazi", ""),
                 ("meslek", "Ne iş yaparsınız? (ör. inşaat mühendisi, işletme sahibi, yazılımcı)", "yazi", ""),
                 ("takim", "Vekil'i kimler kullanacak?", "secim", ["Sadece ben", "Küçük ekip / şirket"]),
                 ("sehir", "Yaşadığınız şehir (hava durumu için)", "yazi", "İstanbul")]},
    {"baslik": "Neyle ilgilenecek?",
     "metin": "Vekil'den en çok hangi işlerde yardım bekliyorsunuz? Birden fazla seçebilirsiniz.",
     "alanlar": [("kullanim", "Kullanım alanları", "coklu", KULLANIM)]},
    {"baslik": "Cihazlarınız",
     "metin": "Hangi cihazlarla çalışacağınızı bilmek, Vekil'in doğru araçları önermesini sağlar.",
     "alanlar": [("pc_os", "Bilgisayarınız", "secim", ["Windows", "macOS", "Linux", "Bilgisayar kullanmıyorum"]),
                 ("pc_acik", "Bilgisayar ne kadar açık?", "secim",
                  ["Genelde açık", "Gerektiğinde açarım", "Akıllı priz ile uzaktan açarım"]),
                 ("telefon", "Telefonunuz", "secim", ["Android", "iPhone", "Telefon asistanı istemiyorum"])]},
    {"baslik": "Yapay zeka anahtarı",
     "metin": "Vekil'in beyni DeepSeek modelidir. platform.deepseek.com adresinden API anahtarı alın "
              "(kullanım başına ödenir, günlük kullanım çok düşük maliyetlidir).",
     "alanlar": [("DEEPSEEK_API_KEY", "DeepSeek API anahtarı", "gizli", "")],
     "dogrula": "deepseek"},
    {"baslik": "Web sohbeti parolası",
     "metin": "OpenDelegate ile tarayıcıdan konuşacaksınız (kurulumdan sonra adres: https://<sizin-adresiniz>/sohbet). "
              "Giriş için bir parola belirleyin, en az 12 karakter. Bir sonraki sayfada telefonunuzdaki doğrulama "
              "uygulaması için anahtar göstereceğiz.",
     "alanlar": [("WEB_PAROLA", "Parola (en az 12 karakter)", "gizli", ""),
                 ("WEB_PAROLA2", "Parola (tekrar)", "gizli", "")],
     "dogrula": "web"},
    {"baslik": "Doğrulama uygulaması",
     "metin": "Telefonunuza Google Authenticator, Microsoft Authenticator ya da benzeri bir uygulama kurun; "
              "\"anahtar girerek ekle\" deyip aşağıdaki anahtarı yazın (zaman tabanlı). Girişte parolanıza ek olarak "
              "uygulamadaki 6 haneli kod istenir; parolanız sızsa bile telefonunuz olmadan kimse giremez. "
              "Anahtar bir daha gösterilmeyecek, .env dosyasında WEB_TOTP_SIR olarak durur.",
     "ozel": "totp",
     "alanlar": [("TOTP_ONAY", "Anahtarı doğrulama uygulamama ekledim.", "onay", "")],
     "dogrula": "totp_onay"},
    {"baslik": "Acil durdurma şifresi",
     "metin": "Sohbete sadece \"kys\" yazarsanız OpenDelegate kendini tamamen kilitler; yalnızca bu şifreyle açılır. "
              "Şifrenin kendisi hiçbir yerde saklanmaz, sadece doğrulama özeti .env dosyasına yazılır. "
              "ŞİFRENİZİ UNUTMAYIN, bir yere not edin: geri getirilemez.\n\n"
              "Sonraki sayfada, bu şifreyi unutursanız kullanabileceğiniz AYRI bir kurtarma kodu göstereceğiz.",
     "alanlar": [("KILIT_SIFRE", "Şifre (en az 8 karakter)", "gizli", ""),
                 ("KILIT_SIFRE2", "Şifre (tekrar)", "gizli", "")],
     "dogrula": "kilit"},
    {"baslik": "Kurtarma kodunuz",
     "metin": lambda d: (
         "Şifrenizi unutursanız bu kodla da kilidi açabilirsiniz. Şifreden TAMAMEN BAĞIMSIZDIR, yalnızca bu "
         "kuruluma özeldir (başka hiçbir kurulumda işe yaramaz) ve bir daha gösterilmeyecektir. Güvenli bir "
         "yere (kağıt, şifre yöneticisi) yazın.\n\n"
         "Kurulumu sizin için yapan kişiye bir kopyasını vermek isterseniz destek için saklayabilir; "
         "istemezseniz kimseyle paylaşmayın."),
     "ozel": "kurtarma",
     "alanlar": [("KURTARMA_ONAY", "Kurtarma kodunu güvenli bir yere kaydettim.", "onay", "")],
     "dogrula": "kurtarma_onay"},
    {"baslik": "İsteğe bağlı servisler",
     "metin": "Hepsini boş bırakabilirsiniz; sonradan .env dosyasına eklenebilir.",
     "alanlar": [("GROQ_API_KEY", "Groq anahtarı (sesli mesajlar için, console.groq.com)", "gizli", ""),
                 ("TAVILY_API_KEY", "Tavily anahtarı (internette arama için, app.tavily.com)", "gizli", ""),
                 ("DATABASE_URL", "Neon Postgres adresi (kalıcı hafıza için; boşsa geçici SQLite)", "yazi", "")]},
    {"baslik": "Hazır", "metin": "", "alanlar": [], "son": True},
]


# Özel sayfalarda gösterilen üretilmiş değer: ad -> (etiket, d anahtarı)
OZEL = {"kurtarma": ("Kurtarma kodunuz", "_KURTARMA_KODU"), "totp": ("Doğrulama uygulaması anahtarı", "WEB_TOTP_SIR")}


# --------------------------------------------------------------------------
# Mantık (GUI'den bağımsız, test edilebilir)
# --------------------------------------------------------------------------

def _istek(url: str, veri: bytes | None = None, baslik: dict[str, str] | None = None) -> dict:
    try:
        r = urllib.request.Request(url, data=veri, headers=baslik or {})
        with urllib.request.urlopen(r, timeout=20) as y:
            return json.loads(y.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_hata": e.code}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return {"_hata": 0}


def deepseek_gecerli(anahtar: str) -> bool | None:
    """True/False: anahtar geçerli mi. None: doğrulanamadı (ağ yok)."""
    v = _istek("https://api.deepseek.com/models", baslik={"Authorization": f"Bearer {anahtar}"})
    if "_hata" not in v:
        return True
    return False if v["_hata"] in (401, 403) else None


def _temiz(metin: str) -> str:
    """.env tek satır: satır sonu, # ve tırnak çıkarılır."""
    return re.sub(r"\s+", " ", re.sub(r"[#\"']+", "", metin or "")).strip()


def profil_metni(d: dict[str, str]) -> str:
    """Cevaplardan Vekil'in hafızasına girecek tek paragraf."""
    parcalar = []
    if d.get("KULLANICI_ADI"):
        parcalar.append(f"Kullanıcının adı {d['KULLANICI_ADI']}.")
    if d.get("meslek"):
        parcalar.append(f"İşi: {d['meslek']}.")
    if d.get("takim"):
        parcalar.append(f"Kullanım: {d['takim'].lower()}.")
    if d.get("kullanim"):
        parcalar.append(f"Beklentisi: {d['kullanim'].lower()}.")
    cihaz = [x for x in (d.get("pc_os"), d.get("pc_acik"), d.get("telefon")) if x]
    if cihaz:
        parcalar.append("Cihazlar: " + "; ".join(cihaz) + ".")
    if d.get("sehir"):
        parcalar.append(f"Şehir: {d['sehir']}.")
    return _temiz(" ".join(parcalar))


def kilit_ozetleri(sifre: str, tuz: bytes | None = None) -> dict[str, str]:
    """Kill switch özetleri (vekil/kilit.py ile aynı yöntem): tuz + PBKDF2-SHA256 600k tur.
    Telegram'ın biçim işaretlerini silebildiği için işaretsiz hâlin özeti de yazılır."""
    tuz = tuz or secrets.token_bytes(16)
    sade = re.sub(r"[\s`\\_*~|]", "", sifre)
    return {"KILIT_TUZ": tuz.hex(),
            "KILIT_OZET": hashlib.pbkdf2_hmac("sha256", sifre.strip().encode("utf-8"), tuz, 600_000).hex(),
            "KILIT_OZET_SADE": hashlib.pbkdf2_hmac("sha256", sade.encode("utf-8"), tuz, 600_000).hex()}


# 0/O, 1/I/L karışmasın diye çıkarıldı; elle okuyup yazmak kolay olsun diye büyük harf + rakam.
_KURTARMA_ALFABE = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def totp_sir_uret() -> str:
    """Doğrulama uygulaması için rastgele base32 anahtar (160 bit)."""
    import base64
    return base64.b32encode(secrets.token_bytes(20)).decode()


def kurtarma_kodu_uret() -> str:
    """Şifreden TAMAMEN bağımsız, o kuruluma özel kurtarma kodu (~100 bit entropi). Hiçbir kurulumda ortak değildir."""
    grup = lambda: "".join(secrets.choice(_KURTARMA_ALFABE) for _ in range(5))
    return "-".join(grup() for _ in range(4))


def kurtarma_ozetleri(kod: str, tuz: bytes | None = None) -> dict[str, str]:
    """Kurtarma kodu özeti: kilit_ozetleri ile aynı yöntem, ama şifreden bağımsız ayrı tuz/özet çiftinde."""
    tuz = tuz or secrets.token_bytes(16)
    return {"KILIT_KURTARMA_TUZ": tuz.hex(),
            "KILIT_KURTARMA_OZET": hashlib.pbkdf2_hmac("sha256", kod.strip().encode("utf-8"), tuz, 600_000).hex()}


def env_metni(d: dict[str, str]) -> str:
    """Boş olmayan değerleri .env satırlarına çevirir (gruplu)."""
    d = dict(d)
    d["PROFIL"] = profil_metni(d)
    if d.get("KILIT_SIFRE"):
        d.update(kilit_ozetleri(d["KILIT_SIFRE"]))
    if d.get("_KURTARMA_KODU"):
        d.update(kurtarma_ozetleri(d["_KURTARMA_KODU"]))
    d["SEHIR_AD"] = "" if d.get("sehir", "İstanbul") == "İstanbul" else _temiz(d.get("sehir", ""))
    d["KULLANICI_ADI"] = _temiz(d.get("KULLANICI_ADI", ""))
    gruplar = [
        ("Zorunlu", ["DEEPSEEK_API_KEY", "OPENDELEGATE_SIR", "WEB_PAROLA", "WEB_TOTP_SIR"]),
        ("Güvenlik anahtarları (rastgele üretildi)", ["WEBHOOK_SECRET", "AJAN_SECRET", "SESLI_TOKEN"]),
        ("Acil durdurma (kys) şifre özeti; şifrenin kendisi saklanmaz", ["KILIT_TUZ", "KILIT_OZET", "KILIT_OZET_SADE"]),
        ("Kurtarma kodu özeti; şifreden bağımsız, bu kuruluma özel, kodun kendisi saklanmaz",
         ["KILIT_KURTARMA_TUZ", "KILIT_KURTARMA_OZET"]),
        ("Kişiselleştirme", ["KULLANICI_ADI", "SEHIR_AD", "PROFIL"]),
        ("İsteğe bağlı servisler", ["GROQ_API_KEY", "TAVILY_API_KEY", "DATABASE_URL"]),
        ("İsteğe bağlı: Telegram kanalı (boşsa kapalı)", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]),
    ]
    satir: list[str] = []
    for baslik, anahtarlar in gruplar:
        secili = [(k, d[k]) for k in anahtarlar if d.get(k)]
        if secili:
            satir += [f"# {baslik}"] + [f"{k}={v}" for k, v in secili] + [""]
    return "\n".join(satir)


def dogrula(tur: str, d: dict[str, str]) -> str | None:
    """Sayfa doğrulaması: hata metni ya da None."""
    if tur == "deepseek":
        if not d.get("DEEPSEEK_API_KEY"):
            return "DeepSeek anahtarı gerekli."
        gecerli = deepseek_gecerli(d["DEEPSEEK_API_KEY"])
        if gecerli is False:
            return "Bu anahtar geçersiz görünüyor. Kontrol edip tekrar deneyin."
    elif tur == "web":
        if len(d.get("WEB_PAROLA", "")) < 12:
            return "Parola en az 12 karakter olmalı."
        if d.get("WEB_PAROLA") != d.get("WEB_PAROLA2"):
            return "İki parola aynı değil."
        d.setdefault("WEB_TOTP_SIR", totp_sir_uret())  # bir kez üretilir, geri/ileri gidince değişmez
    elif tur == "totp_onay":
        if not d.get("TOTP_ONAY"):
            return "Devam etmeden önce anahtarı doğrulama uygulamanıza eklediğinizi onaylayın."
    elif tur == "kilit":
        if len(d.get("KILIT_SIFRE", "")) < 8:
            return "Şifre en az 8 karakter olmalı."
        if d.get("KILIT_SIFRE") != d.get("KILIT_SIFRE2"):
            return "İki şifre aynı değil."
        d.setdefault("_KURTARMA_KODU", kurtarma_kodu_uret())  # bir kez üretilir, geri/ileri gidince değişmez
    elif tur == "kurtarma_onay":
        if not d.get("KURTARMA_ONAY"):
            return "Devam etmeden önce kurtarma kodunu kaydettiğinizi onaylayın."
    return None


def yaz(d: dict[str, str], hedef: Path | None = None) -> Path:
    hedef = hedef or KOK / ".env"
    for k in ("OPENDELEGATE_SIR", "WEBHOOK_SECRET", "AJAN_SECRET", "SESLI_TOKEN"):
        d.setdefault(k, secrets.token_hex(32))
    hedef.write_text(env_metni(d), encoding="utf-8")
    try:
        hedef.chmod(0o600)
    except OSError:
        pass
    return hedef


BITIS = ("Kurulum tamam. Anahtarlarınız ve ayarlarınız .env dosyasına yazıldı; ileride bir değeri değiştirmek "
         "ya da bir anahtarı bulmak isterseniz o dosyaya bakın. Kimseyle paylaşmayın.\n\n"
         "Başlatmak için terminalde:  python vekil/main.py\n\n"
         "Adım adım rehber: docs/KURULUM.md")

# Sihirbazın kendisinin kurmadığı, sizin elle kuracağınız teknolojiler (README'deki liste ile aynı).
KURULACAKLAR = [
    ("Python 3.12 + pip paketleri", "pip install -r requirements.txt (zorunlu)"),
    ("Telegram hesabı ve bot", "@BotFather'dan /newbot (zorunlu)"),
    ("DeepSeek API hesabı", "platform.deepseek.com (zorunlu)"),
    ("Render hesabı", "Vekil'i buluta almak için; Docker imajını Render kendisi derler"),
    ("UptimeRobot (ya da benzeri)", "ücretsiz Render planında uyumasın diye /health'e 5 dk'da bir istek"),
    ("Neon Postgres", "kalıcı hafıza için (isteğe bağlı; yoksa geçici SQLite)"),
    ("Groq hesabı", "sesli mesajlar için (isteğe bağlı)"),
    ("Tavily hesabı", "internette arama için (isteğe bağlı)"),
    ("rclone + OneDrive", "bulut dosya işleri için (isteğe bağlı)"),
    ("PC ajanı", "ajan/ klasörü + Python + pip install mss (bilgisayarı yönetmek için)"),
    ("Android Studio + JDK", "telefon uygulamasını derlemek için; Vosk ses modeli ilk açılışta iner"),
    ("Twilio", "telefonla arama için (isteğe bağlı)"),
]


def kurulacaklar_metni() -> str:
    return "\n".join(f"  - {ad}: {aciklama}" for ad, aciklama in KURULACAKLAR)


# --------------------------------------------------------------------------
# Pencere
# --------------------------------------------------------------------------

def pencere() -> int:
    import tkinter as tk
    from tkinter import ttk

    ARKA, PANEL, METIN, SOLUK, VURGU, HATA = "#0d1117", "#161b22", "#e6edf3", "#8b949e", "#2f81f7", "#f85149"
    kok = tk.Tk()
    kok.title("Vekil Kurulum")
    kok.geometry("860x600")
    kok.resizable(False, False)
    kok.configure(bg=ARKA)

    d: dict[str, str] = {}
    degiskenler: dict[str, Any] = {}
    durum = {"i": 0}

    sol = tk.Frame(kok, bg="#000000", width=300)
    sol.pack(side="left", fill="y")
    sol.pack_propagate(False)
    try:
        resim = tk.PhotoImage(file=str(RESIM))
        tk.Label(sol, image=resim, bg="#000000", bd=0).pack(pady=(40, 12))
        sol.resim = resim  # type: ignore[attr-defined]
    except tk.TclError:
        tk.Label(sol, text="VEKIL", fg=METIN, bg="#000000", font=("Segoe UI", 28, "bold")).pack(pady=80)
    tk.Label(sol, text="Vekil", fg=METIN, bg="#000000", font=("Segoe UI", 20, "bold")).pack()
    tk.Label(sol, text="Kurulum sihirbazı", fg=SOLUK, bg="#000000", font=("Segoe UI", 10)).pack()
    adim_etiketi = tk.Label(sol, text="", fg=SOLUK, bg="#000000", font=("Segoe UI", 9))
    adim_etiketi.pack(side="bottom", pady=18)

    sag = tk.Frame(kok, bg=ARKA)
    sag.pack(side="left", fill="both", expand=True)
    baslik = tk.Label(sag, text="", fg=METIN, bg=ARKA, font=("Segoe UI", 18, "bold"), anchor="w")
    baslik.pack(fill="x", padx=32, pady=(34, 6))
    metin = tk.Label(sag, text="", fg=SOLUK, bg=ARKA, font=("Segoe UI", 10), anchor="w", justify="left", wraplength=470)
    metin.pack(fill="x", padx=32)
    alan_cercevesi = tk.Frame(sag, bg=ARKA)
    alan_cercevesi.pack(fill="both", expand=True, padx=32, pady=14)
    hata = tk.Label(sag, text="", fg=HATA, bg=ARKA, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=470)
    hata.pack(fill="x", padx=32)
    alt = tk.Frame(sag, bg=ARKA)
    alt.pack(fill="x", padx=32, pady=20)
    geri = tk.Button(alt, text="‹ Geri", width=10, relief="flat", bg=PANEL, fg=METIN, activebackground="#21262d",
                     activeforeground=METIN)
    ileri = tk.Button(alt, text="İleri ›", width=12, relief="flat", bg=VURGU, fg="white", activebackground="#1f6feb",
                      activeforeground="white", font=("Segoe UI", 10, "bold"))
    ileri.pack(side="right")
    geri.pack(side="right", padx=8)

    stil = ttk.Style()
    stil.theme_use("clam")
    stil.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=METIN, arrowcolor=METIN)
    stil.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", METIN)],
             selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", METIN)])
    kok.option_add("*TCombobox*Listbox.background", PANEL)
    kok.option_add("*TCombobox*Listbox.foreground", METIN)

    def topla() -> None:
        for anahtar, v in degiskenler.items():
            if isinstance(v, list):
                d[anahtar] = ", ".join(ad for ad, var in v if var.get())
            elif isinstance(v, tk.BooleanVar):
                d[anahtar] = "1" if v.get() else ""
            else:
                d[anahtar] = v.get().strip()

    def goster() -> None:
        s = SAYFALAR[durum["i"]]
        for w in alan_cercevesi.winfo_children():
            w.destroy()
        degiskenler.clear()
        hata.config(text="", fg=HATA)
        baslik.config(text=s["baslik"])
        s_metin = s["metin"](d) if callable(s.get("metin")) else s.get("metin", "")
        metin.config(text=BITIS if s.get("son") else s_metin)
        adim_etiketi.config(text=f"Adım {durum['i'] + 1} / {len(SAYFALAR)}")
        geri.config(state="normal" if durum["i"] > 0 and not s.get("son") else "disabled")
        ileri.config(text="Kur ›" if durum["i"] == len(SAYFALAR) - 2 else "Kapat" if s.get("son") else "İleri ›")
        ilk_girdi = None
        if s.get("son"):
            tk.Label(alan_cercevesi, text="Elle kurmanız gereken teknolojiler:", fg=METIN, bg=ARKA,
                     font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
            kutu = tk.Text(alan_cercevesi, height=14, wrap="word", bg=PANEL, fg=METIN, relief="flat",
                           font=("Segoe UI", 9), padx=8, pady=6)
            kutu.insert("1.0", kurulacaklar_metni())
            kutu.config(state="disabled")
            kutu.pack(fill="both", expand=True, pady=6)
        if s.get("ozel") in OZEL:
            etiket_ozel, anahtar_ozel = OZEL[s["ozel"]]
            tk.Label(alan_cercevesi, text=f"{etiket_ozel} (seçip kopyalayabilirsiniz):", fg=METIN, bg=ARKA,
                     font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
            kod_var = tk.StringVar(value=d.get(anahtar_ozel, ""))
            tk.Entry(alan_cercevesi, textvariable=kod_var, state="readonly", readonlybackground=PANEL, fg=VURGU,
                     relief="flat", font=("Consolas", 14, "bold"), justify="center").pack(fill="x", ipady=10, pady=(0, 10))
        for anahtar, etiket, tur, ek in s["alanlar"]:
            if tur != "onay":
                tk.Label(alan_cercevesi, text=etiket, fg=METIN, bg=ARKA, font=("Segoe UI", 10), anchor="w",
                         wraplength=470, justify="left").pack(fill="x", pady=(8, 2))
            onceki = d.get(anahtar, "")
            if tur in ("yazi", "gizli"):
                var = tk.StringVar(value=onceki or (ek if tur == "yazi" else ""))
                g = tk.Entry(alan_cercevesi, textvariable=var, show="•" if tur == "gizli" else "", bg=PANEL, fg=METIN,
                             insertbackground=METIN, relief="flat", font=("Segoe UI", 11))
                g.pack(fill="x", ipady=6)
                degiskenler[anahtar] = var
                ilk_girdi = ilk_girdi or g
            elif tur == "secim":
                var = tk.StringVar(value=onceki or ek[0])
                ttk.Combobox(alan_cercevesi, textvariable=var, values=ek, state="readonly",
                             font=("Segoe UI", 11)).pack(fill="x", ipady=3)
                degiskenler[anahtar] = var
            elif tur == "coklu":
                secili = set(onceki.split(", ")) if onceki else set()
                liste = []
                for ad in ek:
                    var = tk.BooleanVar(value=ad in secili)
                    tk.Checkbutton(alan_cercevesi, text=ad, variable=var, bg=ARKA, fg=METIN, selectcolor=PANEL,
                                   activebackground=ARKA, activeforeground=METIN, anchor="w",
                                   font=("Segoe UI", 10)).pack(fill="x")
                    liste.append((ad, var))
                degiskenler[anahtar] = liste
            elif tur == "onay":
                var = tk.BooleanVar(value=bool(onceki))
                tk.Checkbutton(alan_cercevesi, text=etiket, variable=var, bg=ARKA, fg=METIN, selectcolor=PANEL,
                               activebackground=ARKA, activeforeground=METIN, anchor="w", wraplength=440,
                               justify="left", font=("Segoe UI", 10)).pack(fill="x", pady=(4, 0))
                degiskenler[anahtar] = var
        if ilk_girdi:
            ilk_girdi.focus_set()

    def ileri_tikla(_=None) -> None:
        s = SAYFALAR[durum["i"]]
        if s.get("son"):
            kok.destroy()
            return
        topla()
        if s.get("dogrula"):
            hata.config(text="Doğrulanıyor...", fg=SOLUK)
            kok.update_idletasks()
            sorun = dogrula(s["dogrula"], d)
            if sorun:
                hata.config(text=sorun, fg=HATA)
                return
        if durum["i"] == len(SAYFALAR) - 2:
            yaz(d)
        durum["i"] += 1
        goster()

    def geri_tikla() -> None:
        topla()
        durum["i"] = max(0, durum["i"] - 1)
        goster()

    ileri.config(command=ileri_tikla)
    geri.config(command=geri_tikla)
    kok.bind("<Return>", ileri_tikla)
    goster()
    kok.mainloop()
    return 0


# --------------------------------------------------------------------------
# Terminal (pencere açılamıyorsa)
# --------------------------------------------------------------------------

def terminal() -> int:
    d: dict[str, str] = {}
    print("Vekil kurulumu\n")
    for s in SAYFALAR:
        if s.get("son"):
            break
        s_metin = s["metin"](d) if callable(s.get("metin")) else s.get("metin", "")
        print(f"\n== {s['baslik']} ==\n{s_metin}\n")
        if s.get("ozel") in OZEL:
            print(f"{OZEL[s['ozel']][0].upper()}: {d.get(OZEL[s['ozel']][1], '')}\n")
        while True:
            for anahtar, etiket, tur, ek in s["alanlar"]:
                if tur == "secim":
                    print(f"{etiket}: " + " / ".join(f"{i + 1}) {x}" for i, x in enumerate(ek)))
                    sec = input("Numara [1]: ").strip() or "1"
                    d[anahtar] = ek[int(sec) - 1] if sec.isdigit() and 0 < int(sec) <= len(ek) else ek[0]
                elif tur == "coklu":
                    print(etiket + ": " + " / ".join(f"{i + 1}) {x}" for i, x in enumerate(ek)))
                    sec = input("Numaralar (virgülle, boş = hiçbiri): ").replace(" ", "")
                    d[anahtar] = ", ".join(ek[int(n) - 1] for n in sec.split(",") if n.isdigit() and 0 < int(n) <= len(ek))
                elif tur == "onay":
                    sec = input(f"{etiket} (e/h): ").strip().lower()
                    d[anahtar] = "1" if sec == "e" else ""
                else:
                    gir = getpass.getpass if tur == "gizli" else input
                    d[anahtar] = gir(f"{etiket}" + (f" [{ek}]" if ek else "") + ": ").strip() or ek
            sorun = dogrula(s["dogrula"], d) if s.get("dogrula") else None
            if not sorun:
                break
            print(sorun)
    print("\n" + str(yaz(d)) + " yazıldı.\n\n" + BITIS)
    print("\nElle kurmanız gereken teknolojiler:\n" + kurulacaklar_metni())
    return 0


def main() -> int:
    for akim in (sys.stdout, sys.stderr):  # Windows konsolu/borusu Türkçe karakterde çökmesin
        try:
            akim.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    if "--cli" not in sys.argv:
        try:
            return pencere()
        except Exception as e:  # noqa: BLE001 — tkinter yok / ekran yok
            print(f"Pencere açılamadı ({type(e).__name__}), terminal moduna geçiliyor.")
    return terminal()


if __name__ == "__main__":
    sys.exit(main())
