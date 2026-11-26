"""OpenDelegate yapılandırması.

Gizli değerlerin hepsi .env dosyasından okunur, koda hiçbir key yazılmaz.
Model, base_url gibi ayarlar da .env'den değiştirilebildiği için kod
başka bir OpenAI-uyumlu sağlayıcıya kolayca taşınır.
"""

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

PROJE_DIZINI = Path(__file__).resolve().parent.parent  # depo kökü (.env burada)
load_dotenv(PROJE_DIZINI / ".env")


def _zorunlu(ad: str) -> str:
    """Zorunlu bir ortam değişkenini okur, yoksa anlaşılır bir hata verir."""
    deger = os.getenv(ad, "").strip()
    if not deger:
        raise RuntimeError(f".env içinde '{ad}' eksik. .env.example dosyasına bak.")
    return deger


# --- Beyin (DeepSeek, OpenAI-uyumlu endpoint) ---
DEEPSEEK_API_KEY = _zorunlu("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# deepseek-flash: tool çağırma + görsel anlama (eski "deepseek-chat" adı emekliye ayrıldı).
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
GORSEL_MODEL = os.getenv("GORSEL_MODEL", "deepseek-flash")  # ekran görüntüsü inceleme (görsel destekli olmalı)

# --- Telegram (isteğe bağlı: boşsa OpenDelegate yalnızca web sohbeti ve telefon uygulamasıyla çalışır) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
# Türetilen bağlantı ve anahtarların tohumu. Telegram kullanılıyorsa bot token'ı; kullanılmıyorsa OPENDELEGATE_SIR.
ANA_SIR = TELEGRAM_BOT_TOKEN or _zorunlu("OPENDELEGATE_SIR")
# Zihin haritası linkinin token'ı. Boşsa TELEGRAM_BOT_TOKEN'dan HMAC ile türetilir (harita.py).
# Link sızarsa bunu değiştir: eski link anında 404 olur.
HARITA_TOKEN = os.getenv("HARITA_TOKEN", "").strip()
# Sadece bu sohbete cevap verilir. Telegram kapalıysa tek kullanıcılı web sohbetinin iç numarası (1).
TELEGRAM_CHAT_ID = int(_zorunlu("TELEGRAM_CHAT_ID")) if TELEGRAM_BOT_TOKEN else 1

# --- Web sohbeti (/sohbet): parola + isteğe bağlı ama önerilen TOTP (Google Authenticator) ---
WEB_PAROLA = os.getenv("WEB_PAROLA", "").strip()  # boşsa web sohbeti kapalı
WEB_TOTP_SIR = os.getenv("WEB_TOTP_SIR", "").strip().replace(" ", "").upper()  # base32; boşsa sadece parola
WEB_OTURUM_SAAT = int(os.getenv("WEB_OTURUM_SAAT", "12"))

# --- Çalışma modu ---
# WEBHOOK_URL (ya da Render'ın otomatik verdiği RENDER_EXTERNAL_URL) varsa webhook,
# yoksa polling modu. Lokalde ikisi de boş kalır -> polling.
WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
WEBHOOK_YOLU = "/webhook"
# Telegram her webhook isteğinde bu değeri header'da gönderir; sahte istekleri eler.
# Verilmezse bot token'ından türetilir (Telegram: 1-256 karakter, A-Z a-z 0-9 _ -).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip() or hashlib.sha256(
    ANA_SIR.encode()
).hexdigest()[:48]
PORT = int(os.getenv("PORT", "10000"))  # Render $PORT'u kendisi verir

# --- PC ajanı (görev API'si) ---
# Ajan GET /jobs/pending ve POST /jobs/result isteklerinde bunu X-Ajan-Secret
# header'ında gönderir. Boşsa görev API'si tamamen kapalıdır (her istek 403).
AJAN_SECRET = os.getenv("AJAN_SECRET", "").strip()
AJAN_CEVRIMICI_SN = int(os.getenv("AJAN_CEVRIMICI_SN", "15"))  # son yoklamadan bu kadar sn geçtiyse çevrimdışı
GOREV_SONUC_ZAMAN_ASIMI = int(os.getenv("GOREV_SONUC_ZAMAN_ASIMI", "0"))  # 0 = süre sınırı YOK (bağlantı kopması ayrı kontrol)
# PC kapalıyken sıraya alınan iş en fazla bu kadar bekler; sonra çalıştırılmadan iptal edilir (bayat onay).
KUYRUK_OMRU_SAAT = int(os.getenv("KUYRUK_OMRU_SAAT", "72"))

# --- Kişiselleştirme (hepsi isteğe bağlı) ---
# Salt okunur takvim: gizli iCal adres(ler)i (https, virgülle ayrılır). Boşsa takvim özelliği kapalı. Adres bir sırdır.
TAKVIM_ICS_URL = os.getenv("TAKVIM_ICS_URL", "").strip()
KULLANICI_ADI = os.getenv("KULLANICI_ADI", "").strip() or "efendim"  # brifing: "Günaydın <ad>"
# Kill switch şifre özeti (kurulum sihirbazı üretir; şifrenin kendisi hiçbir yerde saklanmaz)
KILIT_TUZ = os.getenv("KILIT_TUZ", "").strip()
KILIT_OZET = os.getenv("KILIT_OZET", "").strip()
KILIT_OZET_SADE = os.getenv("KILIT_OZET_SADE", "").strip()
# Kurtarma kodu: şifreden bağımsız, o kuruluma özel yedek açma yolu (kurulum sihirbazı üretir, bir kez gösterir).
# Ortak/sabit bir anahtar DEĞİLDİR; her kurulumda farklı, boşsa devre dışı.
KILIT_KURTARMA_TUZ = os.getenv("KILIT_KURTARMA_TUZ", "").strip()
KILIT_KURTARMA_OZET = os.getenv("KILIT_KURTARMA_OZET", "").strip()
PROFIL = os.getenv("PROFIL", "").strip()  # kurulum sihirbazının yazdığı kullanıcı profili (hafızaya bir kez girer)
SEHIR_AD = os.getenv("SEHIR_AD", "İstanbul").strip()  # hava durumu / brifing varsayılan şehri
SEHIR_LAT = float(os.getenv("SEHIR_LAT", "41.0082"))
SEHIR_LON = float(os.getenv("SEHIR_LON", "28.9784"))

# --- OneDrive (rclone: okuma + yeni dosya/klasör; silme/yeniden adlandırma yok) ---
# Render'da Secret File: /etc/secrets/rclone.conf. Salt okunur olduğu için açılışta
# yazılabilir bir kopyaya alınır (rclone token yenileyince oraya yazar).
# Boşsa rclone'un varsayılan config'i kullanılır (lokal: %APPDATA%\rclone\rclone.conf).
RCLONE_CONFIG = os.getenv("RCLONE_CONFIG", "").strip()
RCLONE_BIN = os.getenv("RCLONE_BIN", "rclone").strip()
ONEDRIVE_REMOTE = os.getenv("ONEDRIVE_REMOTE", "vekilod").strip()  # rclone config'teki remote adı
# OpenDelegate'in bakabileceği OneDrive kök klasörleri (virgülle).
ONEDRIVE_KLASORLER = [
    k.strip() for k in os.getenv("ONEDRIVE_KLASORLER", "Masaüstü,Belgeler").split(",") if k.strip()
]

# --- İnternet ---
MAKS_INDIRME = 25 * 1024 * 1024  # indir / onedrive_yukle limiti
MAKS_SAYFA = 5 * 1024 * 1024  # webde_oku limiti
PC_INDIRME_KLASORU = os.getenv("PC_INDIRME_KLASORU", r"%USERPROFILE%\Downloads")
# webde_ara için Tavily Search API key'i (app.tavily.com, kartsız ücretsiz plan). Boşsa arama kapalı.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# --- Sesli mesaj (Groq Whisper, kartsız ücretsiz katman) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()  # boşsa sesli mesaj kapalı
# Android sesli asistan endpoint'i (/dinle/{token}). Boşsa bot token'ından türetilir.
SESLI_TOKEN = os.getenv("SESLI_TOKEN", "").strip() or hashlib.sha256(
    (ANA_SIR + "sesli").encode()
).hexdigest()[:40]
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
# Telefon uygulaması: kısa komutlar, turbo'dan daha isabetli tam model (Groq'ta ikisi de ücretsiz katmanda).
STT_TELEFON_MODEL = os.getenv("STT_TELEFON_MODEL", "whisper-large-v3")
# Asistanın konuşma dili: "tr" (varsayılan) ya da "en". "en" iken cevaplar, sesli okuma ve tanıma İngilizce olur;
# yerleşik komut mesajları (/durum gibi) Türkçe kalır.
DIL = os.getenv("DIL", "tr").strip().lower()
if DIL not in ("tr", "en"):
    DIL = "tr"
DIL_TALIMATI = "" if DIL == "tr" else (
    "\n\nLANGUAGE RULE (overrides every rule above that says to speak Turkish or to address the user as 'efendim'): "
    "always reply to the user in clear, natural English, short and polite. Address the user as 'sir' or by name."
)
STT_DIL = os.getenv("STT_DIL", "en" if DIL == "en" else "tr").strip()  # boş bırakılırsa dil otomatik algılanır
MAKS_SES = 20 * 1024 * 1024  # Telegram bot API'si de en fazla 20 MB indirtir

# --- Telefon araması (Twilio deneme hesabı; dördü de doluysa açık) ---
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()  # asla loglanmaz
TWILIO_NUMARA = os.getenv("TWILIO_NUMARA", "").strip()  # arayan (Twilio) numara, +1...
KULLANICI_TELEFON = os.getenv("KULLANICI_TELEFON", "").strip()  # aranan numara, +90...

# --- Hafıza ---
# Neon Postgres bağlantı adresi (postgresql://...?sslmode=require). Varsa kalıcı hafıza;
# yoksa SQLite (Render'da geçici). Asla loglanmaz.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_YOLU = Path(os.getenv("VEKIL_DB", str(PROJE_DIZINI / "vekil.db")))

# --- Ajan davranışı ---
ONAY_ZAMAN_ASIMI = int(os.getenv("ONAY_ZAMAN_ASIMI", "300"))  # sn; cevap gelmezse red sayılır
MAKS_ADIM = int(os.getenv("MAKS_ADIM", "60"))  # bir mesajda en fazla kaç model turu (Kullanıcı: işi bitirsin, durmasın)
GECMIS_LIMITI = int(os.getenv("GECMIS_LIMITI", "30"))  # modele gönderilen son mesaj sayısı
CIKTI_LIMITI = 4000  # modele dönen tool çıktısının en fazla karakter sayısı

# --- Bilgisayar kullanma (imleç + klavye; PC ajanı ekran görüp tıklar/yazar) ---
MAKS_PC_TUR = int(os.getenv("MAKS_PC_TUR", "25"))  # bir bilgisayar_kullan görevinde en fazla tur
PC_DURGUN_ESIK = int(os.getenv("PC_DURGUN_ESIK", "3"))  # ekran bu kadar tur üst üste aynıysa: ilerleme yok, dur

# --- OpenDelegate ordusu (Başvekil işi işçi vekillere dağıtır; her işçi ayrı token harcar) ---
MAKS_VEKIL = int(os.getenv("MAKS_VEKIL", "4"))  # bir dağıtımda en fazla kaç işçi
MAKS_ISCI_ADIM = int(os.getenv("MAKS_ISCI_ADIM", "25"))  # bir işçinin en fazla model turu
ISCI_ZAMAN_ASIMI = int(os.getenv("ISCI_ZAMAN_ASIMI", "0"))  # 0 = süre sınırı YOK (Kullanıcı: uzun işler kesilmesin)
KADRO_SORU_SN = int(os.getenv("KADRO_SORU_SN", "60"))  # kadro sorusuna cevap gelmezse öneriyle başlanır
