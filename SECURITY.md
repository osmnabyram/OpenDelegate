# Güvenlik

## Tehdit modeli
Vekil tek kullanıcılı. Saldırgan hedefleri: (1) Telegram/Render uçlarına yetkisiz komut, (2) çalınmış token ile
telefon/PC kontrolü, (3) para/ödeme işlemi, (4) sızan sırlar, (5) ekran/mesaj içeriğiyle modeli yönlendirme.

## Katmanlar
- **Kimlik:** Telegram sadece `TELEGRAM_CHAT_ID`; webhook `WEBHOOK_SECRET`; PC ajanı `X-Ajan-Secret`;
  telefon `SESLI_TOKEN`; hepsi sabit zamanlı karşılaştırma (`secrets.compare_digest`).
- **Kill switch:** `kys` (kalıcı kilit, sadece şifreyle açılır, fail-closed).
- **Ödeme/para sınırı (kodda, `guvenlik.py`):** telefondan ödeme, havale, satın alma, banka/cüzdan uygulaması,
  kart/IBAN yazma reddedilir. Model prompt'una güvenilmez.
- **Hız ve boyut sınırı:** telefon uçları dakikada 90 istek; gövde boyut sınırları.
- **HTTP başlıkları:** nosniff, no-referrer, X-Frame-Options, HSTS; token'lı sayfalar `no-store`.
- **Log:** `access_log` kapalı; token ve bilinen sır biçimleri (bot token, API anahtarı, Bearer) maskelenir.
- **Ağ (SSRF):** dış istekler `ag.py` kapısından; özel IP aralıkları reddedilir.
- **Android:** sadece https, açık metin kapalı, sadece sistem CA; token ve PIN Android Keystore'da şifreli (PIN sunucuya gitmez); ekran ajanı şifre alanına yazmaz; bildirimler diske yazılmaz.
- **Depo:** `.env` git dışı; testler izlenen dosyalarda sır biçimi arar (`tests/test_guvenlik.py`).
- **Bağımlılık:** Dependabot (aylık).

## Sır yönetimi
Sırlar sadece ortam değişkeninde (Render env / yerel `.env`). Koda, teste, loga yazılmaz. Sızıntıdan şüphede:
Render'da ilgili env'i değiştir (`SESLI_TOKEN`, `WEBHOOK_SECRET`, `AJAN_SECRET`), uygulamada token'ı yeniden gir,
Telegram bot token'ını BotFather'dan yenile.

## Bilinen sınırlar
- Ödeme kapısı anahtar kelime tabanlıdır; eşanlamlılar kaçabilir. Ek katman: model talimatı + ekran ajanı durdurma.
- Uyandırma cümlesini herkes söyleyebilir (kilitliyken `uygulama_ac` PIN girer): bilinçli tercih.
- `SESLI_TOKEN` env'de yoksa bot token'ından türetilir; ayrı rastgele değer önerilir.

## Bildirim
Açık bulduysan depo sahibine özel olarak yaz; herkese açık issue açma.
