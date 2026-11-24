# Değişiklikler / Changelog

Biçim: [Keep a Changelog](https://keepachangelog.com/). Sürümler [Releases](https://github.com/osmnabyram/VekilAi/releases) sayfasında.

## [Yayınlanmadı / Unreleased]

### Eklendi / Added
- Yönetim sayfası (`/yonetim`): durum, hafıza sayıları, PC ajanı, son işler; gizli bağlantı, salt okuma. / Admin page (`/yonetim`): status, memory counts, PC agent, recent jobs; secret link, read-only.

## [1.1.0] - 2026-11-24

Android uygulaması 1.0.1 ile aynı; yalnızca sunucu tarafı değişti. / The Android app is the same as 1.0.1; only the server side changed.

### Eklendi / Added
- `/yedek`: kalıcı hafızayı JSON dosyası olarak dışa aktarır. / `/yedek`: exports the persistent memory as a JSON file.
- `DIL=en` ayarı: asistan cevapları, sesli okuma ve konuşma tanıma İngilizce. / `DIL=en` setting: English answers, spoken output and speech recognition.

## [1.0.1] - 2026-11-24

### Değişti / Changed
- Yeni Vekil ikonu: README, kurulum sihirbazı ve Android uygulaması. / New Vekil icon: README, setup wizard and the Android app.

### Eklendi / Added
- `eklentiler/` klasörü: müşteriye özel araçlar ana koda dokunmadan eklenir. / `eklentiler/` folder: customer-specific tools without touching the core code.
- Zihin haritası ve uygulama ekran görüntüleri README'de. / Mind map and app screenshots in the README.
- `render.yaml` ve README'de "Deploy to Render" düğmesi. / `render.yaml` and a "Deploy to Render" button in the README.
- İngilizce README ve kurulum rehberi, dil seçenek bağlantıları. / English README and setup guide, language links.
- SSS, gizlilik sayfası, yol haritası, değişiklik günlüğü. / FAQ, privacy page, roadmap, changelog.
- GitHub özel güvenlik bildirimi, Dependabot güvenlik güncellemeleri. / GitHub private vulnerability reporting, Dependabot security updates.

### Düzeltildi / Fixed
- Türkçe README'deki yazı animasyonu adresi kodlanmadığı için görünmüyordu. / The Turkish README typing animation did not show because its URL was not encoded.

## [1.0.0] - 2026-11-24

İlk açık kaynak sürüm: Telegram ve sesli asistan, bilgisayar ve telefon kontrolü, kalıcı hafıza, zihin haritası, kill switch, imzalı Android APK.
/ First open source release: Telegram and voice assistant, computer and phone control, persistent memory, mind map, kill switch, signed Android APK.
