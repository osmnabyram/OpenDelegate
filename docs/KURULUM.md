# Adım adım kurulum rehberi (sıfırdan 100'e)

Bu rehber, Vekil'i bir kullanıcıya (müşteriye) **sıfırdan** kuran kişi içindir. Kullanıcının teknolojiyle hiç
uğraşmadığı, telefonunu ve bilgisayarını yeni aldığı varsayılır. Başa dönmeden, sırayla ilerleyin.

> Hesapları **kullanıcının kendi e-postasıyla** açın, anahtarları ve şifreleri ona verin. Kullanıcının kartıyla
> yapılan hiçbir ödemeyi onun adına geçmeyin; yanınızdayken kendisi yapsın.

## İçindekiler

0. [Ziyaretten önce hazırlık](#0-ziyaretten-önce-hazırlık)
1. [Hesaplar](#1-hesaplar)
2. [Kurulum sihirbazı](#2-kurulum-sihirbazı-kullanıcının-windows-bilgisayarında)
3. [Render'a yükleme](#3-rendera-yükleme-vekili-724-çalıştırmak)
4. [PC ajanı](#4-pc-ajanı-windows)
5. [Telefon uygulaması (APK) üretimi](#5-telefon-uygulaması-apk-üretimi)
6. [Telefonda kurulum](#6-telefonda-kurulum)
7. [Teslim testi](#7-teslim-testi)
8. [Kullanıcıya anlatılacaklar](#8-kullanıcıya-anlatılacaklar)
9. [Sorun giderme](#9-sorun-giderme)

---

## 0. Ziyaretten önce hazırlık

- [ ] Depoyu güncel alın: `git clone https://github.com/osmnabyram/VekilAi` (varsa `git pull`).
- [ ] Kullanıcıya özel bir istek varsa (hitap, kurallar, yeni araç) kodu o kullanıcı için kopyalayıp özelleştirin
      (`vekil/hafiza_tohum.py` ilk bilgiler, `vekil/tools.py` yeni araç). Kullanıcı bilgisini ana depoya koymayın.
- [ ] **Android imza anahtarı hazır olmalı:** `android/imza/` ve `android/keystore.properties`
      (yoksa `python android/imza_olustur.py`). Yedeğini ayrı bir yerde (USB, şifre yöneticisi) saklayın.
- [ ] Kullanıcının telefonu **Android** mi? iPhone ise telefon uygulaması yoktur; yalnızca Telegram ve bilgisayar kurulur.
- [ ] Kullanıcının bilgisayarı **Windows** mu? PC ajanı şu an Windows içindir (ekran, fare, program işleri). Mac/Linux'ta
      Telegram, telefon, internet ve hafıza kısımları yine çalışır; bilgisayar yönetimi çalışmaz.

## 1. Hesaplar

Hepsini kullanıcının e-postasıyla, tarayıcıda birlikte açın. Anahtarları bir kenara yazın; en sonda `.env` dosyasına girecek.

| Hesap | Nasıl | Zorunlu mu |
|---|---|---|
| **Telegram** | Telefona Telegram'ı kurun, numarasıyla hesap açın. Telegram'da **@BotFather** → `/newbot` → bot adı ve kullanıcı adı (sonu `bot` ile biter). BotFather'ın verdiği **bot anahtarını** (`123456:ABC...`) kaydedin. Kimseyle paylaşmayın. | Evet |
| **DeepSeek** | [platform.deepseek.com](https://platform.deepseek.com) → hesap → *API Keys* → yeni anahtar (`sk-...`). Kullanım başına ödenir: *Balance*'a kullanıcı kendi kartıyla küçük bir tutar yükler, aylarca yeter. | Evet |
| **Render** | [render.com](https://render.com) → hesap (GitHub ya da e-posta). Ücretsiz plan yeterlidir ama 15 dk işlem olmazsa uyur (UptimeRobot bunu çözer). | Evet (bulutta çalıştırmak için) |
| **UptimeRobot** | [uptimerobot.com](https://uptimerobot.com) → ücretsiz hesap. Render uyumasın diye. | Fiilen evet |
| **Neon** | [neon.tech](https://neon.tech) → hesap → yeni proje → *Connection string* (pooled) = `DATABASE_URL`. Yapılmazsa Vekil geçici bellekle çalışır ve Render her yeniden başladığında hafıza silinir. | Önerilir |
| **Groq** | [console.groq.com](https://console.groq.com) → *API Keys*. Sesli mesaj ve telefon sesi için. | Önerilir |
| **Tavily** | [app.tavily.com](https://app.tavily.com). İnternette arama. | Hayır |
| **OneDrive / rclone** | Bulut dosya işleri gerekirse (ileri düzey). | Hayır |
| **Twilio** | Vekil'in kullanıcıyı telefonla araması (ücretli, genelde gerekmez). | Hayır |

## 2. Kurulum sihirbazı (kullanıcının Windows bilgisayarında)

1. **Python kurun:** [python.org/downloads](https://www.python.org/downloads) → Python 3.12 → kurarken
   **"Add python.exe to PATH"** kutusunu işaretleyin.
2. **Vekil dosyalarını indirin:** GitHub'da *Code → Download ZIP*, masaüstüne çıkarın (örnek: `C:\Vekil`).
3. Komut satırını açın (Windows tuşu → `cmd`) ve sırayla çalıştırın:
   ```
   cd C:\Vekil
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python kurulum.py
   ```
4. Açılan pencerede (solda Vekil resmi, sağ altta *İleri*) soruları kullanıcıyla birlikte doldurun:
   isim, işi, kullanım alanları, cihazlar, şehir; sonra DeepSeek anahtarı ve Telegram bot anahtarı.
   - **"Sohbetimi bul":** kullanıcı Telegram'dan botuna bir mesaj atar, sihirbaz sohbet kimliğini kendisi bulur.
   - **Acil durdurma şifresi:** kullanıcı `kys` şifresini belirler (en az 8 karakter). Sihirbaz şifrenin kendisini değil,
     yalnızca doğrulama özetini `.env`'e yazar. ŞİFRENİN NOT EDİLMESİ GEREKTİĞİNİ kullanıcıya hatırlatın.
   - **Kurtarma kodu:** sonraki sayfa, şifreden bağımsız, bu kuruluma özel rastgele bir kod gösterir (yalnızca bir
     kez). Kullanıcı bunu güvenli bir yere yazmalı. İsterse size (kurulumu yapana) de bir kopyasını bırakabilir —
     zorunlu değil, kullanıcının tercihi. Siz bıraktıysa kendi özel kaydınıza (ör. müşteri adıyla, ayrı bir not
     dosyasında) yazın; **hiçbir ortak/sabit anahtar yoktur**, her kurulumun kodu farklıdır.
   - Son sayfada Groq, Tavily, Neon (`DATABASE_URL`) varsa yapıştırın. **Kur** düğmesi `.env` dosyasını oluşturur.
5. **Yerelde deneyin:** `python vekil\main.py` → Telegram'da bota "merhaba" yazın, cevap gelmeli. `Ctrl+C` ile durdurun.
   Bu yalnızca deneme; gerçek çalışma Render'da, bilgisayar kapalıyken de sürer.
6. **`.env` dosyası:** kurulumdaki tüm anahtarlar orada. Kullanıcıya bir kopyasını verin (USB ya da şifre yöneticisi).
   Başkasına göndermeyin, internete yüklemeyin, ekran görüntüsü atmayın.

## 3. Render'a yükleme (Vekil'i 7/24 çalıştırmak)

1. Render → **New + → Web Service → Public Git Repository** → depo adresi (`https://github.com/osmnabyram/VekilAi`) → *Connect*.
   Kullanıcıya özel kod değişikliği yaptıysanız onun hesabında ayrı bir GitHub reposuna koyup onu bağlayın.
2. **Language: Docker**, **Instance Type: Free**, *Advanced → Health Check Path:* `/health`.
3. **Environment** bölümüne `.env` içindeki şu değerleri tek tek girin:
   `DEEPSEEK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WEBHOOK_SECRET`, `AJAN_SECRET`, `SESLI_TOKEN`,
   `KULLANICI_ADI`, `SEHIR_AD`, `PROFIL`, `KILIT_TUZ`, `KILIT_OZET`, `KILIT_OZET_SADE`,
   `KILIT_KURTARMA_TUZ`, `KILIT_KURTARMA_OZET`, ve varsa `DATABASE_URL`, `GROQ_API_KEY`, `TAVILY_API_KEY`.
   `WEBHOOK_URL`'yi **girmeyin**; Render adresi kendisi veriyor.
4. **Create Web Service.** İlk derleme 5-10 dakika sürer. Loglarda `Webhook kayıtlı` görünmeli.
5. **Kontrol:** tarayıcıda `https://<servis-adı>.onrender.com/health` → `ok`. Telegram'dan bota yazın, cevap gelmeli.
6. Servis adresini (`https://....onrender.com`) **kaydedin**: telefon uygulaması ve PC ajanı bunu kullanacak.
7. **UptimeRobot:** *Add New Monitor → HTTP(s)* → URL `https://<servis-adı>.onrender.com/health` → aralık **5 dakika**.
   Yapılmazsa ücretsiz Render uyur ve ilk mesaja geç cevap verir.

## 4. PC ajanı (Windows)

1. `ajan` klasörünü `C:\vekil-ajan` olarak kopyalayın.
2. Komut satırında: `pip install mss`
3. `C:\vekil-ajan\.env` oluşturun (`ajan\.env.example`'ı kopyalayın) ve yazın:
   ```
   VEKIL_URL=https://<servis-adı>.onrender.com
   AJAN_SECRET=<ana .env'deki AJAN_SECRET ile BİREBİR AYNI>
   ```
4. Başlatın: `C:\vekil-ajan\baslat.bat` (ya da `python ajan.py`) → `Vekil'e bağlandı` yazmalı.
5. Windows açılışında otomatik başlasın: `Win+R` → `shell:startup` → `baslat.bat`'ın kısayolunu oraya koyun.
6. Telegram'dan deneyin: "masaüstümde ne var" ya da "ekran görüntüsü al". Cevap geliyorsa tamam.

Ajan yalnızca bilgisayar **açık ve internete bağlıyken** çalışır.

## 5. Telefon uygulaması (APK) üretimi

Kurulumu yapan kişinin bilgisayarında, kullanıcının Render adresi ve `SESLI_TOKEN`'ı hazırken:

```
cd android
python musteri_apk.py
```

Sorulara müşteri adı, Render adresi (`https://...`) ve `SESLI_TOKEN`'ı (kullanıcının `.env`'inden) girin.
Sonuç: `android/cikti/<musteri>.apk` (imzalı; adres ve anahtar içine gömülü).

- Bu APK'yı **yalnızca o kullanıcıya** verin; başkasına gitmesi o kullanıcının anahtarının sızması demektir.
- İlk seferde JDK gerekir (Android Studio'nun `jbr` klasörü yeterli); ilk derleme birkaç dakika sürer.
- APK'yı kullanıcının telefonuna USB ile `Dosyalar > İndirilenler`'e kopyalayarak ya da kullanıcının kendi hesabına
  göndererek iletin.

## 6. Telefonda kurulum

Menü adları marka ve Android sürümüne göre biraz değişir (Samsung, Xiaomi, Pixel).

1. Dosyalar uygulamasında APK'ya dokunun → "Bilinmeyen kaynaktan kuruluma izin ver" çıkarsa izin verin → **Yükle**.
2. Vekil uygulamasını açın. İlk açılışta ses modeli (Vosk) indirilir: telefon **internete bağlı** olsun, bekleyin.
3. İzinleri sırayla verin:
   - **Mikrofon:** izin verin.
   - **Bildirim gösterme:** istenirse izin verin.
   - **Diğer uygulamaların üzerinde göster:** *Ayarlar → Uygulamalar → Vekil* → ilgili izni açın.
   - **Pil:** *Ayarlar → Uygulamalar → Vekil → Pil → Kısıtlamasız* (yoksa arka planda uyur, "vekil" demeyi duymaz).
   - **Erişilebilirlik** (ekranı okuma ve tıklama için, **en önemlisi**): *Ayarlar → Erişilebilirlik → Yüklü uygulamalar →
     Vekil* → açın. Android 13+ "Kısıtlanmış ayar" derse: *Ayarlar → Uygulamalar → Vekil → sağ üst üç nokta →
     Kısıtlanmış ayarlara izin ver*, sonra erişilebilirliği tekrar açın.
   - **Bildirim erişimi** (bildirimleri okusun diye): *Ayarlar → Bildirimler → Bildirim erişimi → Vekil* → açın.
   - **Kişiler ve Arama izni:** arama istenirse sorulduğunda verin.
4. Gerekirse uygulamada ekran kilidi PIN'i girilebilir (kilitliyken uyandırma için; yalnızca telefonda şifreli saklanır).
5. APK'ya adres gömülü değilse (`musteri_apk.py` kullanılmadıysa): uygulamanın ayarlarına Render adresini
   (`https://...`) ve `SESLI_TOKEN`'ı girin.

## 7. Teslim testi

Hepsi geçmeden ayrılmayın:

- [ ] Telegram: bota "merhaba" → cevap geliyor.
- [ ] Telegram: "yarın sabah 9'da bana şunu hatırlat: ..." → kabul ediyor.
- [ ] PC açıkken: "ekran görüntüsü al" → geliyor.
- [ ] Telefon: ekran açıkken "vekil, bir bakar mısın" → dinliyor; soru sorun → sesli cevap veriyor.
- [ ] Telefon: "alarm kur" / "feneri aç" gibi bir komut çalışıyor.
- [ ] Telefon kilitliyken ve bilgisayar kapalıyken Telegram'dan yazın → Render üzerinden yine cevap geliyor
      (bilgisayar işleri hariç).
- [ ] `/health` "ok" döndürüyor, UptimeRobot yeşil.
- [ ] `.env` yedeği kullanıcıda, anahtarlar kullanıcıda.

## 8. Kullanıcıya anlatılacaklar

- Vekil'e Telegram'dan yazabilir ya da telefona "vekil, bir bakar mısın" diyebilir.
- Ödeme, banka ve para işlemlerine Vekil dokunmaz; bunu kod engelliyor. Şifre alanlarına da yazmaz.
- **Acil durdurma:** Telegram'a yalnızca `kys` yazmak Vekil'i kilitler. Kurulumda belirlediği şifreyle ya da
  kurulumda gösterilen kurtarma koduyla açılır.
- "dur" yazarsa yaptığı iş kesilir.
- Anahtarlar (`.env`) gizlidir; kimseyle paylaşılmaz. Sızarsa yenileri üretilir.
- Güncelleme gerekirse Render'da ve (gerekirse) telefonda yeni APK ile yapılır. APK aynı imza anahtarıyla
  üretildiği için üzerine kurulur, veriler ve izinler korunur.

## 9. Sorun giderme

| Belirti | Çözüm |
|---|---|
| Bot cevap vermiyor | Render → *Logs* bakın; `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` doğru mu; servis uyuyor olabilir (UptimeRobot). |
| "Ajan çevrimdışı" | Bilgisayar kapalı/internet yok ya da ajan çalışmıyor; `AJAN_SECRET` iki yerde aynı mı. |
| Telefon "vekil" deyince uyanmıyor | Pil kısıtlaması, mikrofon izni, erişilebilirlik açık mı; Vosk modeli indi mi. |
| Hafıza kayboluyor | `DATABASE_URL` (Neon) girilmemiş. |
| Render ilk istekte yavaş | Ücretsiz plan uyumuş; UptimeRobot 5 dk'da bir bakmalı. |
| `kys` şifresi unutuldu | Kullanıcı kurtarma kodunu sakladıysa (ya da size bıraktıysa) onunla açılır. İkisi de yoksa: şifre saklanmadığı için geri getirilemez; `python kurulum.py` ile yeni şifre+kurtarma kodu belirleyin, `.env` içindeki `KILIT_*` değerlerini Render'daki aynı değişkenlere yapıştırıp servisi yeniden başlatın. |
| `kys` işe yaramıyor | `KILIT_*` değerleri `.env`'de var mı ve Render'da da girilmiş mi? Yoksa kill switch kapalıdır. |
| Yeni APK kurulmuyor ("paket çakışıyor") | İmza anahtarı farklı demektir; eski uygulamayı silip yenisini kurun. İmza anahtarını asla kaybetmeyin ya da değiştirmeyin. |
