# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# OpenDelegate — geliştirici notları

OpenDelegate: web sohbeti (Telegram isteğe bağlı) ve Android sesli uygulamasıyla konuşulan, PC'yi ve telefonu yönetebilen kişisel yapay zeka asistanı. Bu depo **temel sürümdür**; her müşteri/kullanıcı için üzerine eklenip çıkarılır.

## Komutlar

```bash
python -m unittest discover -s tests -t . -q      # tüm testler (gerçek anahtar gerekmez; tests/__init__.py sahte env koyar)
python -m unittest tests.test_guvenlik -v         # tek dosya
python kurulum.py                                  # kurulum sihirbazı (.env üretir)
python vekil/main.py                                     # yerel çalıştır (WEBHOOK_URL boşsa polling)
```

Testleri `-t .` ile çalıştır: `tests` paket olarak yüklenir ve sahte env ayarları devreye girer.

## Mimari (kısa harita)

Uygulama modülleri `vekil/` altındadır (kökte yalnızca `kurulum.py`, `ajan/`, `android/`, `tests/`, `docs/`). `python vekil/main.py` ile çalışır; modüller birbirini düz `import config` gibi içe aktarır (`vekil/` yola otomatik girer).

- `web_sohbet.py` + `static/sohbet.*`: web sohbeti (giriş: parola + TOTP, `WebBot` = Telegram `Bot` taklidi, rotalar). `main.web_mesaj_isle` / `web_dugme_isle` mesajı ve düğmeleri mevcut işleyicilere yönlendirir. `TELEGRAM_BOT_TOKEN` boşsa `calis(None)`: Telegram hiç kurulmaz, arka plan mesajları `web_bot`'a gider. Yeni özellik `bot.xxx` metodu kullanıyorsa `WebBot`'a da ekle.
- `main.py`: Telegram işleyicileri, ajan turu (`ajan_turu`), araç dağıtımı (`tool.hedef`), `SYSTEM_PROMPT`, açılış (`calis`), web uygulaması (`/jobs/*`, `/health`, `/harita/*`, `/webhook`).
- `tools.py`: Araç tanımları + risk/onay (`risk_degerlendir`, `onay_gerekir`).
- `config.py`: Tüm ortam değişkenleri burada okunur; gizli değer koda yazılmaz.
- `hafiza.py` + `hafiza_tohum.py`: Kalıcı bilgi (tercih/terim/karar/not). `DATABASE_URL` yoksa geçici SQLite.
- `harita.py` + `static/harita.html`: 3B zihin haritası.
- `gorevler.py` + `ajan/ajan.py`: PC görev kuyruğu ve PC tarafı ajan (dosya, terminal, ekran, fare/klavye).
- `bilgisayar.py`: `bilgisayar_kullan` görsel döngü. `ordu.py`/`masaustu.py`: işçi vekiller ve sanal masaüstleri.
- `brifing.py`, `zamanli.py`, `yapilacak.py`, `takip.py`, `zamanlayici.py`: sabah brifingi, hatırlatma, yapılacaklar, konu takibi.
- `oz_degerlendirme.py`: haftalık öz-değerlendirme; sıradan dersler kural olur (`/ogrendiklerim`).
- `seslendirme.py` (çıkış, edge-tts), `ses.py` (giriş, Groq Whisper), `sesli.py` (`/dinle`, `/sor`, `/seslendir`).
- `telefon_ajan.py` + `arama.py`: Android ekran ajanı ve sesli tur; `arama.py` ayrıca Twilio telefon araması.
- `guvenlik.py`: ödeme/banka kapıları, başlıklar, hız ve gövde sınırı, sır maskesi. Ayrıntı: `SECURITY.md`.
- `kilit.py`: kill switch (`kys`), şifre yalnızca PBKDF2 özeti olarak tutulur.
- `ag.py`: dış HTTP'nin tek kapısı (SSRF koruması). `web.py`, `onedrive.py`, `belge.py`, `gorsel.py`, `ofis.py`: internet, OneDrive, belge/resim anlama.
- `android/`: Kotlin uygulaması (`VekilService` uyanma kelimesi, `VekilErisim` erişilebilirlik, `Panel`, `Config`).

## Kurallar

- Ödeme/para/banka işlemleri **kodda** engellenir (`guvenlik.py`); modelin talimatına güvenme.
- Yeni telefon eylemini `arama.TELEFON_EYLEM_SEMASI`'na eklerken sürüm kapısına (`_EKRAN_EYLEMLERI`) bağla ve prompt'a "sadece kullanıcı isterse çağır" kuralını yaz.
- Sırlar sadece ortam değişkeninde. Koda, teste, loga yazma. `tests/test_guvenlik.py` izlenen dosyalarda sır biçimi arar.
- Kullanıcıya hitap: "efendim". Arayüzde emoji yok (Telegram komut butonları hariç).
- Yeni bağımlılık eklemeden önce gerekçe yaz; standart kütüphane ve mevcut paketler önceliklidir.

## Android derleme

Paket adı `com.opendelegate.app`. Satış için `python android/imza_olustur.py` (bir kez) + `./gradlew assembleRelease` imzalı APK üretir; `python android/musteri_apk.py` müşteriye özel (adres/anahtar gömülü) APK üretir (`BuildConfig.VARSAYILAN_*`, `Config.kt` yedek olarak okur); anahtar `android/imza/` ve `keystore.properties` git dışıdır, yedeklenmelidir.

```bash
cd android
./gradlew assembleDebug        # JAVA_HOME Android Studio jbr olmalı
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Kurulumdan sonra erişilebilirlik ve bildirim erişimi izinleri yeniden verilir.
