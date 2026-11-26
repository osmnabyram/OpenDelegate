# Sık sorulan sorular / FAQ

[Türkçe](#türkçe) | [English](#english)

## Türkçe

**OpenDelegate nedir, ne işe yarar?**
Web sohbetinden yazarak ya da telefona seslenerek bilgisayarınızı ve telefonunuzu yöneten, sizi tanıyan kişisel yapay zeka asistanı. Ayrıntı: [README](../README.md).

**Verilerim nerede duruyor, kim görebilir?**
Kendi Render sunucunuzda ve kendi Neon veritabanınızda. Sizden başka kimse göremez. Hangi bilgi hangi hizmete gider: [GIZLILIK.md](GIZLILIK.md).

**Aylık maliyeti nedir?**
OpenDelegate'in kendisi ücretsiz ve açık kaynak. Ödediğiniz yer:
- **Render:** ücretsiz plan yeterli (15 dk işlem olmazsa uyur; UptimeRobot ile uyanık tutulur).
- **Neon (hafıza):** ücretsiz katman başlangıç için yeterli.
- **DeepSeek (beyin):** kullandığınız kadar öder, bakiye yüklersiniz. Tutar kullanımınıza göre değişir; güncel fiyatlar için [platform.deepseek.com](https://platform.deepseek.com).
- **Groq, Tavily:** kartsız ücretsiz katmanları var (isteğe bağlı).
- **Twilio** (telefonla arama): ücretli, isteğe bağlı, çoğu kişiye gerekmez.

**DeepSeek yerine başka bir model kullanabilir miyim?**
Kod OpenAI uyumlu bir uçla konuşur. `DEEPSEEK_BASE_URL` ve `DEEPSEEK_MODEL` değişkenleriyle başka bir uyumlu sağlayıcıya geçebilirsiniz. Modelin araç çağırmayı (tool calling) desteklemesi gerekir; ekran görüntüsü için `GORSEL_MODEL` görsel destekli olmalıdır. Her sağlayıcıyla denenmiş değildir.

**iPhone'da çalışır mı?**
Telefon uygulaması şu an yalnızca Android. iPhone'da tarayıcıdaki web sohbeti üzerinden kullanılır.

**Mac ya da Linux'ta çalışır mı?**
PC ajanı (bilgisayar yönetimi) şu an Windows içindir. Web sohbeti, hafıza, internet ve telefon kısımları her yerde çalışır.

**OpenDelegate benim yerime para öder mi?**
Hayır. Ödeme, banka ve para işlemleri kodda engellenir; modele bırakılmaz. Şifre alanlarına da yazmaz. Ayrıntı: [SECURITY.md](../SECURITY.md).

**Bir şeyler ters giderse nasıl durdururum?**
Sohbete yalnızca `kys` yazın: OpenDelegate kilitlenir. Yapmakta olduğu işi kesmek için "dur" yazın.

**Telegram kullanmak zorunda mıyım?**
Hayır. OpenDelegate kendi adresinizdeki **web sohbetinden** (`/sohbet`) kullanılır; Telegram isteğe bağlı bir ek kanaldır. `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` boşsa Telegram tamamen kapalıdır ve hiçbir veri Telegram'a gitmez.

**Web sohbeti güvenli mi?**
Giriş parola (en az 12 karakter) ve telefondaki doğrulama uygulamasının 6 haneli koduyla yapılır. Yanlış denemede 15 dakika beklenir, oturum çerezi tarayıcı betiklerinden gizlidir ve yalnızca https ile gider, süresi dolunca ya da çıkış yapınca biter. Telefonu kaybederseniz Render'da `WEB_TOTP_SIR` değerini değiştirerek eski kodları geçersiz kılarsınız.

**Web sohbetinden dosya ya da sesli mesaj gönderebilir miyim?**
Evet. Yazı kutusunun yanındaki *Dosya* düğmesiyle fotoğraf, PDF, Word, Excel ve metin dosyası; *Ses* düğmesiyle sesli mesaj gönderirsiniz (tarayıcı mikrofon izni ister; sesin yazıya çevrilmesi için `GROQ_API_KEY` gerekir). En fazla 25 MB. Dosyalar diske yazılmaz, bellekte işlenir.

**Sekme kapalıyken bildirim gelir mi?**
Evet, *Bildirim* düğmesine basıp izin verirseniz. Bildirim yalnızca "Yeni mesaj" der, mesajı açmak için sohbete girersiniz. iPhone'da bildirim için sayfayı önce *Ana Ekrana Ekle* ile kurmanız gerekir (iOS 16.4 ve üstü). Render'da ücretsiz plan uyuduysa bildirim ancak sunucu uyanıkken gider (UptimeRobot kurun).

**Takvimimi görebilir mi?**
Salt okunur olarak, evet. Google Takvim'de *Ayarlar → takvimi seç → Takvimi entegre et → iCal biçiminde gizli adres* kısmındaki adresi kopyalayıp `TAKVIM_ICS_URL` ortam değişkenine yapıştırın (Render'da *Environment*). Sonra "bugün ne var", "yarın toplantım var mı", "bu hafta programım" diye sorabilirsiniz; sabah brifingine de bugünün etkinlikleri girer. Etkinlik ekleyemez ya da silemez, e-postaya bakmaz. Adresi bilen herkes takvimi okuyabilir, o yüzden kimseyle paylaşmayın; sızarsa Google'da "gizli adresi sıfırla". Telefon uygulamasındaki sesli asistan takvime şu an bakmaz, yalnızca Telegram ve brifing.

**OpenDelegate'in durumunu nereden görürüm?**
Sohbette `/yonetim` yazın: gizli bir bağlantı gelir. Sayfada model, hafıza durumu, PC ajanı, hafıza sayıları ve son işler görünür. Konuşma metni ve eylem ayrıntıları gösterilmez. Model maliyeti şu an yok (DeepSeek panelinden bakın).

**OpenDelegate İngilizce konuşabilir mi?**
`DIL=en` ortam değişkenini ekleyin (Render'da *Environment*). Cevaplar, sesli okuma ve konuşma tanıma İngilizce olur. `/durum` gibi yerleşik komut mesajları ve sabit bildirimler Türkçe kalır.

**Hafızamı nasıl yedeklerim?**
Sohbette `/yedek` yazın: bilgiler, özetler ve ayarlar tek bir JSON dosyası olarak gelir. Kilit ve anahtar ayarları ile şifre/anahtar biçimli kayıtlar dosyaya girmez. Şu an yalnızca dışa aktarma var, geri yükleme yok.

**Hafızayı nasıl silerim?**
`/hafiza` ile görün, `/unut <anahtar>` ile tek tek silin, `/sifirla` ile konuşma geçmişini temizleyin. Tamamen silmek için Neon projenizi silmeniz yeterli.

**Sorun yaşıyorum, nereye yazayım?**
Kurulum ve genel sorular için GitHub Issues. Güvenlik açığı bulduysanız herkese açık issue açmayın; [SECURITY.md](../SECURITY.md) içindeki özel bildirim yolunu kullanın.

## English

**What is OpenDelegate?**
A personal AI assistant that manages your computer and phone from the web chat or by voice, and learns who you are. See the [README](../README.en.md).

**Where is my data stored and who can see it?**
On your own Render server and your own Neon database. Nobody else can see it. Which data goes to which service: [GIZLILIK.md](GIZLILIK.md).

**What does it cost per month?**
OpenDelegate itself is free and open source. What you pay for:
- **Render:** the free plan is enough (it sleeps after 15 minutes without requests; UptimeRobot keeps it awake).
- **Neon (memory):** the free tier is enough to start.
- **DeepSeek (the brain):** pay as you go with a prepaid balance. The amount depends on your usage; see [platform.deepseek.com](https://platform.deepseek.com) for current prices.
- **Groq, Tavily:** free tiers without a card (optional).
- **Twilio** (phone calls): paid, optional, most people do not need it.

**Can I use a model other than DeepSeek?**
The code talks to an OpenAI-compatible endpoint. Set `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL` to switch to another compatible provider. The model must support tool calling, and `GORSEL_MODEL` must support vision for screenshots. Not tested with every provider.

**Does it work on iPhone?**
The phone app is Android only for now. On iPhone use it through the web chat in the browser.

**Does it work on Mac or Linux?**
The PC agent (computer control) is Windows-only for now. Web chat, memory, internet and phone features work everywhere.

**Will OpenDelegate pay for things for me?**
No. Payments, banking and money operations are blocked in code, not left to the model. It also does not type into password fields. See [SECURITY.md](../SECURITY.md).

**How do I stop it if something goes wrong?**
Write only `kys` in the chat: OpenDelegate locks. Write "dur" (stop) to cancel the work in progress.

**Do I have to use Telegram?**
No. OpenDelegate is used through the **web chat** (`/sohbet`) on your own address; Telegram is an optional extra channel. If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are empty, Telegram is completely off and no data goes to Telegram.

**Is the web chat secure?**
Sign-in needs a password (12+ characters) and the 6-digit code from the authenticator app on your phone. After wrong tries it waits 15 minutes, the session cookie is hidden from page scripts and travels only over https, and it ends on expiry or sign-out. If you lose the phone, change `WEB_TOTP_SIR` on Render to invalidate the old codes.

**Can I send files or voice messages from the web chat?**
Yes. Use the *File* button next to the text box for photos, PDF, Word, Excel and text files, and the *Voice* button for a voice message (the browser asks for microphone permission; `GROQ_API_KEY` is needed to turn speech into text). Up to 25 MB. Files are not written to disk; they are processed in memory.

**Will I get a notification when the tab is closed?**
Yes, if you press the *Notifications* button and allow it. The notification only says "Yeni mesaj" (new message); you open the chat to read it. On iPhone you must first install the page with *Add to Home Screen* (iOS 16.4 and later). If the free Render plan has gone to sleep, the notification only goes out while the server is awake (set up UptimeRobot).

**Can it see my calendar?**
Read-only, yes. In Google Calendar open *Settings → pick the calendar → Integrate calendar → Secret address in iCal format*, copy the address and paste it into the `TAKVIM_ICS_URL` environment variable (on Render: *Environment*). Then you can ask "what is on today", "do I have a meeting tomorrow", "my schedule this week"; today's events also go into the morning briefing. It cannot add or delete events and does not read email. Anyone who knows the address can read the calendar, so share it with nobody; if it leaks, "reset secret address" in Google. The voice assistant in the phone app does not look at the calendar for now, only Telegram and the briefing.

**Where do I see OpenDelegate's status?**
Write `/yonetim` in the chat: a secret link arrives. The page shows the model, memory status, PC agent, memory counts and recent jobs. Conversation text and action details are not shown. There is no model cost yet (check the DeepSeek dashboard).

**Can OpenDelegate speak English?**
Add the `DIL=en` environment variable (on Render: *Environment*). Answers, spoken output and speech recognition become English. Built-in command messages such as `/durum` and fixed notifications stay Turkish.

**How do I back up my memory?**
Write `/yedek` in the chat: knowledge, summaries and settings arrive as a single JSON file. Lock and key settings, and entries that look like passwords or keys, are left out. For now it is export only, there is no restore.

**How do I delete the memory?**
See it with `/hafiza`, delete single items with `/unut <key>`, clear the conversation history with `/sifirla`. To wipe everything, delete your Neon project.

**I have a problem, where do I write?**
For setup and general questions use GitHub Issues. If you found a security hole, do not open a public issue; use the private reporting route in [SECURITY.md](../SECURITY.md).
