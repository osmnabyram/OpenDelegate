# Veri ve gizlilik / Data and privacy

[Türkçe](#türkçe) | [English](#english)

## Türkçe

OpenDelegate sizin sunucunuzda çalışır; bizim (geliştiricinin) hiçbir sunucumuz yoktur ve verileriniz bize gelmez. Ama OpenDelegate çalışırken bazı dış hizmetleri kullanır. Hangi veri nereye gider:

| Veri | Nerede durur | Dışarı giden |
|---|---|---|
| Konuşmalar, hafıza, eylem kayıtları, hatırlatmalar | Sizin Neon veritabanınız (`DATABASE_URL` boşsa geçici dosya) | Mesajlar, cevap üretmek için model sağlayıcısına gider (varsayılan DeepSeek) |
| Sesli mesajlar | Saklanmaz | Yazıya çevirmek için Groq'a gider (kullanırsanız) |
| İnternet aramaları | Saklanmaz | Arama metni Tavily'ye gider (kullanırsanız) |
| Ekran görüntüleri | Diske ve veritabanına yazılmaz; sonuç yalnızca metin olarak kalır | Anlamak için görsel model sağlayıcısına gider |
| Kimlik, kart, IBAN gibi değerler | Hafızaya ve diske yazılmaz | Belge ve fotoğraflarda maskelenir |
| Takvim etkinlikleri | Saklanmaz (5 dakika bellekte tutulur) | Takvim adresine istek gider; sorduğunuzda etkinlik metni model sağlayıcısına gider |
| Web sohbeti oturumu | Sunucu belleğinde rastgele oturum kimliği (diske yazılmaz, yeniden başlatmada silinir); tarayıcıda yalnızca `HttpOnly` çerez | Hiçbir şey; sohbet metni yalnızca sizin adresinizle sizin tarayıcınız arasında gider |
| Telefon bildirimleri | Yalnızca telefonun belleğinde (son 30), diske yazılmaz | OpenDelegate'e sorduğunuzda içeriği model sağlayıcısına gider |
| Telefon kilit PIN'i | Yalnızca telefonda, Android Keystore ile şifreli | Sunucuya gitmez |
| Anahtarlar ve sırlar | Render ortam değişkenleri / yerel `.env` | Log'larda maskelenir; koda yazılmaz |

Yani verileriniz **sizin hesaplarınızda** durur; ama konuşma içeriği model sağlayıcısının (varsayılan DeepSeek) politikalarına tabidir. Bu sizin için sorunsa modeli `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` ile değiştirebilirsiniz ([SSS](SSS.md)).

Silmek için: `/unut`, `/sifirla` komutları ya da Neon projenizi silmek. Sunucuyu kapatırsanız OpenDelegate durur, veri Neon'da kalır.

Bu sayfa kodun mevcut davranışını anlatır; hukuki taahhüt değildir. Kullandığınız hizmetlerin (Render, Neon, DeepSeek, Groq, Tavily, Twilio ve kullanıyorsanız Telegram) kendi gizlilik politikaları geçerlidir.

## English

OpenDelegate runs on your server; the developer has no servers and your data does not come to us. But OpenDelegate uses some outside services while running. Which data goes where:

| Data | Where it stays | What leaves |
|---|---|---|
| Conversations, memory, action logs, reminders | Your Neon database (a temporary file if `DATABASE_URL` is empty) | Messages go to the model provider to produce answers (DeepSeek by default) |
| Voice messages | Not stored | Sent to Groq for transcription (if you use it) |
| Web searches | Not stored | The query goes to Tavily (if you use it) |
| Screenshots | Not written to disk or the database; only the text result stays | Sent to the vision model provider to be understood |
| ID, card, IBAN values | Not written to memory or disk | Masked in documents and photos |
| Calendar events | Not stored (kept in memory for 5 minutes) | A request goes to the calendar address; when you ask, the event text goes to the model provider |
| Web chat session | A random session id in server memory (never written to disk, cleared on restart); only an `HttpOnly` cookie in the browser | Nothing; chat text travels only between your own address and your own browser |
| Phone notifications | Only in the phone's memory (last 30), never written to disk | Their content goes to the model provider when you ask OpenDelegate |
| Phone lock PIN | Only on the phone, encrypted with Android Keystore | Never sent to the server |
| Keys and secrets | Render environment variables / local `.env` | Masked in logs; never written in code |

So your data stays **in your own accounts**, but conversation content is subject to the model provider's policies (DeepSeek by default). If that is a problem you can switch the model with `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` ([FAQ](SSS.md)).

To delete: the `/unut` and `/sifirla` commands, or delete your Neon project. If you shut down the server OpenDelegate stops and the data stays in Neon.

This page describes the current behaviour of the code; it is not a legal commitment. The privacy policies of the services you use (Render, Neon, DeepSeek, Groq, Tavily, Twilio and, if you use it, Telegram) apply.
