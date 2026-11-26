# Güvenlik

## Tehdit modeli
OpenDelegate tek kullanıcılı. Saldırgan hedefleri: (1) web sohbeti, Telegram (açıksa) ve Render uçlarına yetkisiz komut, (2) çalınmış token ile
telefon/PC kontrolü, (3) para/ödeme işlemi, (4) sızan sırlar, (5) ekran/mesaj içeriğiyle modeli yönlendirme.

## Katmanlar
- **Web sohbeti (`/sohbet`):** şifre (kys şifresiyle aynı: yalnızca PBKDF2-SHA256 özeti saklanır, 600 bin tur, sabit zamanlı karşılaştırma; kurtarma kodu web girişinde geçmez) + TOTP kodu (`WEB_TOTP_SIR`, RFC 6238); yanlış girişte hep aynı cevap, IP başına 5 ve genelde 30 başarısız denemede 15 dk kilit; oturum çerezi `HttpOnly`, `Secure`, `SameSite=Strict`, bellekte tutulur (yeniden başlatmada herkes çıkar); durum değiştiren her istek çerez + özel `X-OD` başlığı + aynı kaynak (`Origin`) ister (CSRF); sayfa betikleri ayrı dosyadır ve CSP `script-src 'self'` ile sınırlıdır; Vekil'in HTML'i beyaz listeden süzülür (script, resim, olay özellikleri atılır). Ne kys şifresi (`KILIT_OZET`) ne yedek `WEB_PAROLA` varsa web sohbeti hiç açılmaz.
- **Kimlik:** Telegram (açıksa) sadece `TELEGRAM_CHAT_ID`; webhook `WEBHOOK_SECRET`; PC ajanı `X-Ajan-Secret`;
  telefon `SESLI_TOKEN`; hepsi sabit zamanlı karşılaştırma (`secrets.compare_digest`).
- **Kill switch:** `kys` (kalıcı kilit, fail-closed). Şifreyle ya da o kuruluma özel kurtarma koduyla açılır
  (bkz. aşağıdaki bölüm). Hiçbir kurulumda ortak/sabit bir "hepsini açan" anahtar YOKTUR.
- **Ödeme/para sınırı (kodda, `guvenlik.py`):** telefondan ödeme, havale, satın alma, banka/cüzdan uygulaması,
  kart/IBAN yazma reddedilir. Model prompt'una güvenilmez.
- **Hız ve boyut sınırı:** telefon uçları dakikada 90 istek; gövde boyut sınırları.
- **HTTP başlıkları:** nosniff, no-referrer, X-Frame-Options, HSTS; token'lı sayfalar `no-store`.
- **Log:** `access_log` kapalı; token ve bilinen sır biçimleri (bot token, API anahtarı, Bearer) maskelenir.
- **Ağ (SSRF):** dış istekler `ag.py` kapısından; özel IP aralıkları reddedilir.
- **Android:** sadece https, açık metin kapalı, sadece sistem CA; token ve PIN Android Keystore'da şifreli (PIN sunucuya gitmez); ekran ajanı şifre alanına yazmaz; bildirimler diske yazılmaz.
- **Depo:** `.env` git dışı; testler izlenen dosyalarda sır biçimi arar (`tests/test_guvenlik.py`).
- **Bağımlılık:** Dependabot (aylık).

## Kurtarma kodu (kill switch)
Kurulum sihirbazı, `kys` şifresinden **tamamen bağımsız**, **o kuruluma özel** rastgele bir kurtarma kodu üretir
(`KILIT_KURTARMA_TUZ`/`KILIT_KURTARMA_OZET`) ve kurulum sırasında bir kez ekranda gösterir; kodun kendisi hiçbir
yerde saklanmaz. Kullanıcı şifresini unutursa bu kodla da kilidi açabilir. Önemli: bu **sabit/ortak bir anahtar
değildir** — her kurulumda farklı, rastgele üretilir; biri sızsa bile yalnızca o tek kurulumu etkiler. Kurulumu
yapan kişiye bir kopyasını bırakmak kullanıcının tercihidir, zorunlu değildir. Hem şifre hem kurtarma kodu
unutulursa/kaybedilirse tek yol: yeni bir şifre+kod üretip ilgili `KILIT_*` ortam değişkenlerini güncellemektir
(servisi kuran kişinin erişimiyle; koda gömülü bir "yedek giriş" yoktur).

## Sır yönetimi
Sırlar sadece ortam değişkeninde (Render env / yerel `.env`). Koda, teste, loga yazılmaz. Sızıntıdan şüphede:
Render'da ilgili env'i değiştir (`KILIT_*` şifre özetleri, `WEB_TOTP_SIR`, `SESLI_TOKEN`, `WEBHOOK_SECRET`, `AJAN_SECRET`), uygulamada token'ı yeniden gir,
Telegram kullanıyorsan bot token'ını BotFather'dan yenile. Telefon kaybında `WEB_TOTP_SIR` değiştirmek eski kodları geçersiz kılar.

## Bilinen sınırlar
- Ödeme kapısı anahtar kelime tabanlıdır; eşanlamlılar kaçabilir. Ek katman: model talimatı + ekran ajanı durdurma.
- Uyandırma cümlesini herkes söyleyebilir (kilitliyken `uygulama_ac` PIN girer): bilinçli tercih.
- `SESLI_TOKEN` env'de yoksa ana sırdan (`OPENDELEGATE_SIR` ya da bot token'ı) türetilir; ayrı rastgele değer önerilir.
- Web sohbeti giriş sınırı genel (30 başarısız deneme / 15 dk): saldırgan sizi o süre dışarıda bırakabilir ama içeri giremez. IP başına sınır, proxy'nin `X-Forwarded-For` sonuna eklediği adrese dayanır; proxy arkasında birçok kişi aynı adresi görebilir.
- Web Push abonelik adresleri yalnızca bilinen push servislerine (Google FCM, Mozilla, Apple, Windows) izinlidir; bildirim "Yeni mesaj" der, metin taşımaz.
- Uyandırma cümlesi "delegate bir bakar mısın": Vosk Türkçe modelinde "delegate" kelimesi yok, "delege" tanınır; ses benzerliğine dayanır.

## Bildirim
Açık bulduysan herkese açık issue AÇMA. Depodaki **Security** sekmesinden *Report a vulnerability* ile özel olarak bildir
(GitHub özel güvenlik bildirimi); yalnızca depo sahibi görür.
