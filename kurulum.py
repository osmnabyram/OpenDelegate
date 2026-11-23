"""Vekil kurulum sihirbazı: solda resim, sağda sorular, altta İleri/Geri. Sonunda .env dosyasını yazar.

Çalıştır: python kurulum.py          (pencere açılır)
          python kurulum.py --cli    (pencere yoksa ya da istenirse terminalde sorar)
Sadece standart kütüphane kullanır. Anahtarlar yalnızca yerel .env dosyasına yazılır.
"""

from __future__ import annotations

import getpass
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
    {"baslik": "Telegram botu",
     "metin": "Telegram'da @BotFather'a /newbot yazıp bir bot oluşturun, size verdiği anahtarı aşağıya yapıştırın.",
     "alanlar": [("TELEGRAM_BOT_TOKEN", "Bot anahtarı", "gizli", "")],
     "dogrula": "bot"},
    {"baslik": "Sohbetinizi bağlayalım",
     "metin": "Telegram'da botunuza herhangi bir mesaj atın, sonra \"Sohbetimi bul\" düğmesine basın. "
              "Vekil yalnızca bu sohbete cevap verir.",
     "alanlar": [("TELEGRAM_CHAT_ID", "Sohbet kimliği", "yazi", "")],
     "eylem": "sohbet", "dogrula": "sohbet"},
    {"baslik": "İsteğe bağlı servisler",
     "metin": "Hepsini boş bırakabilirsiniz; sonradan .env dosyasına eklenebilir.",
     "alanlar": [("GROQ_API_KEY", "Groq anahtarı (sesli mesajlar için, console.groq.com)", "gizli", ""),
                 ("TAVILY_API_KEY", "Tavily anahtarı (internette arama için, app.tavily.com)", "gizli", ""),
                 ("DATABASE_URL", "Neon Postgres adresi (kalıcı hafıza için; boşsa geçici SQLite)", "yazi", "")]},
    {"baslik": "Hazır", "metin": "", "alanlar": [], "son": True},
]


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


def telegram(token: str, yontem: str) -> dict:
    """Telegram Bot API çağrısı; hata olursa {'ok': False}."""
    v = _istek(f"https://api.telegram.org/bot{token}/{yontem}")
    return v if "ok" in v else {"ok": False}


def deepseek_gecerli(anahtar: str) -> bool | None:
    """True/False: anahtar geçerli mi. None: doğrulanamadı (ağ yok)."""
    v = _istek("https://api.deepseek.com/models", baslik={"Authorization": f"Bearer {anahtar}"})
    if "_hata" not in v:
        return True
    return False if v["_hata"] in (401, 403) else None


def sohbet_kimligi(token: str) -> int | None:
    """Botun aldığı son özel mesajdan sohbet kimliğini okur."""
    for g in reversed(telegram(token, "getUpdates").get("result", [])):
        sohbet = (g.get("message") or {}).get("chat", {})
        if sohbet.get("type") == "private":
            return int(sohbet["id"])
    return None


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


def env_metni(d: dict[str, str]) -> str:
    """Boş olmayan değerleri .env satırlarına çevirir (gruplu)."""
    d = dict(d)
    d["PROFIL"] = profil_metni(d)
    d["SEHIR_AD"] = "" if d.get("sehir", "İstanbul") == "İstanbul" else _temiz(d.get("sehir", ""))
    d["KULLANICI_ADI"] = _temiz(d.get("KULLANICI_ADI", ""))
    gruplar = [
        ("Zorunlu", ["DEEPSEEK_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]),
        ("Güvenlik anahtarları (rastgele üretildi)", ["WEBHOOK_SECRET", "AJAN_SECRET", "SESLI_TOKEN"]),
        ("Kişiselleştirme", ["KULLANICI_ADI", "SEHIR_AD", "PROFIL"]),
        ("İsteğe bağlı servisler", ["GROQ_API_KEY", "TAVILY_API_KEY", "DATABASE_URL"]),
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
    elif tur == "bot":
        ben = telegram(d.get("TELEGRAM_BOT_TOKEN", ""), "getMe")
        if not ben.get("ok"):
            return "Bot anahtarı doğrulanamadı (yanlış anahtar ya da internet yok)."
        d["_bot"] = ben["result"].get("username", "bot")
    elif tur == "sohbet":
        if not d.get("TELEGRAM_CHAT_ID", "").lstrip("-").isdigit():
            return "Sohbet kimliği bir sayı olmalı. \"Sohbetimi bul\" düğmesini deneyin."
    return None


def yaz(d: dict[str, str], hedef: Path | None = None) -> Path:
    hedef = hedef or KOK / ".env"
    for k in ("WEBHOOK_SECRET", "AJAN_SECRET", "SESLI_TOKEN"):
        d.setdefault(k, secrets.token_hex(32))
    hedef.write_text(env_metni(d), encoding="utf-8")
    try:
        hedef.chmod(0o600)
    except OSError:
        pass
    return hedef


BITIS = ("Kurulum tamam. Başlatmak için terminalde:\n\n    python vekil/main.py\n\n"
         "Sonra Telegram'da botunuza yazın.\n\n"
         "PC ajanı için ajan/.env dosyasına AJAN_SECRET değerini aynen yazın.\n"
         "Android uygulamasında SESLI_TOKEN değerini girin.\n"
         "Bu anahtarlar .env dosyasındadır; kimseyle paylaşmayın.")


# --------------------------------------------------------------------------
# Pencere
# --------------------------------------------------------------------------

def pencere() -> int:
    import tkinter as tk
    from tkinter import ttk

    ARKA, PANEL, METIN, SOLUK, VURGU, HATA = "#0d1117", "#161b22", "#e6edf3", "#8b949e", "#2f81f7", "#f85149"
    kok = tk.Tk()
    kok.title("Vekil Kurulum")
    kok.geometry("860x540")
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
            else:
                d[anahtar] = v.get().strip()

    def sohbet_ara(girdi: tk.Entry, deneme: int = 0) -> None:
        token = d.get("TELEGRAM_BOT_TOKEN", "")
        bulunan = sohbet_kimligi(token)
        if bulunan is not None:
            girdi.delete(0, "end")
            girdi.insert(0, str(bulunan))
            hata.config(text="Sohbet bulundu.", fg="#3fb950")
        elif deneme < 30:
            hata.config(text=f"@{d.get('_bot', 'bot')} botuna bir mesaj atın, bekliyorum...", fg=SOLUK)
            kok.after(3000, lambda: sohbet_ara(girdi, deneme + 1))
        else:
            hata.config(text="Mesajı göremedim. Kimliği elle yazabilirsiniz (@userinfobot'a yazınca söyler).", fg=HATA)

    def goster() -> None:
        s = SAYFALAR[durum["i"]]
        for w in alan_cercevesi.winfo_children():
            w.destroy()
        degiskenler.clear()
        hata.config(text="", fg=HATA)
        baslik.config(text=s["baslik"])
        metin.config(text=BITIS if s.get("son") else s["metin"])
        adim_etiketi.config(text=f"Adım {durum['i'] + 1} / {len(SAYFALAR)}")
        geri.config(state="normal" if durum["i"] > 0 and not s.get("son") else "disabled")
        ileri.config(text="Kur ›" if durum["i"] == len(SAYFALAR) - 2 else "Kapat" if s.get("son") else "İleri ›")
        ilk_girdi = None
        for anahtar, etiket, tur, ek in s["alanlar"]:
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
                if s.get("eylem") == "sohbet":
                    tk.Button(alan_cercevesi, text="Sohbetimi bul", relief="flat", bg=PANEL, fg=METIN,
                              command=lambda g=g: (topla(), sohbet_ara(g))).pack(anchor="w", pady=8)
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
        print(f"\n== {s['baslik']} ==\n{s['metin']}\n")
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
                else:
                    gir = getpass.getpass if tur == "gizli" else input
                    d[anahtar] = gir(f"{etiket}" + (f" [{ek}]" if ek else "") + ": ").strip() or ek
            if s.get("eylem") == "sohbet" and not d.get("TELEGRAM_CHAT_ID"):
                print("Sohbet aranıyor (botunuza mesaj atın)...")
                for _ in range(30):
                    bulunan = sohbet_kimligi(d["TELEGRAM_BOT_TOKEN"])
                    if bulunan is not None:
                        d["TELEGRAM_CHAT_ID"] = str(bulunan)
                        break
                    time.sleep(3)
            sorun = dogrula(s["dogrula"], d) if s.get("dogrula") else None
            if not sorun:
                break
            print(sorun)
    print("\n" + str(yaz(d)) + " yazıldı.\n\n" + BITIS)
    return 0


def main() -> int:
    if "--cli" not in sys.argv:
        try:
            return pencere()
        except Exception as e:  # noqa: BLE001 — tkinter yok / ekran yok
            print(f"Pencere açılamadı ({type(e).__name__}), terminal moduna geçiliyor.")
    return terminal()


if __name__ == "__main__":
    sys.exit(main())
