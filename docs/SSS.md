# Sık sorulan sorular / FAQ

[Türkçe](#türkçe) | [English](#english)

## Türkçe

**Vekil nedir, ne işe yarar?**
Telegram'dan yazarak ya da telefona seslenerek bilgisayarınızı ve telefonunuzu yöneten, sizi tanıyan kişisel yapay zeka asistanı. Ayrıntı: [README](../README.md).

**Verilerim nerede duruyor, kim görebilir?**
Kendi Render sunucunuzda ve kendi Neon veritabanınızda. Sizden başka kimse göremez. Hangi bilgi hangi hizmete gider: [GIZLILIK.md](GIZLILIK.md).

**Aylık maliyeti nedir?**
Vekil'in kendisi ücretsiz ve açık kaynak. Ödediğiniz yer:
- **Render:** ücretsiz plan yeterli (15 dk işlem olmazsa uyur; UptimeRobot ile uyanık tutulur).
- **Neon (hafıza):** ücretsiz katman başlangıç için yeterli.
- **DeepSeek (beyin):** kullandığınız kadar öder, bakiye yüklersiniz. Tutar kullanımınıza göre değişir; güncel fiyatlar için [platform.deepseek.com](https://platform.deepseek.com).
- **Groq, Tavily:** kartsız ücretsiz katmanları var (isteğe bağlı).
- **Twilio** (telefonla arama): ücretli, isteğe bağlı, çoğu kişiye gerekmez.

**DeepSeek yerine başka bir model kullanabilir miyim?**
Kod OpenAI uyumlu bir uçla konuşur. `DEEPSEEK_BASE_URL` ve `DEEPSEEK_MODEL` değişkenleriyle başka bir uyumlu sağlayıcıya geçebilirsiniz. Modelin araç çağırmayı (tool calling) desteklemesi gerekir; ekran görüntüsü için `GORSEL_MODEL` görsel destekli olmalıdır. Her sağlayıcıyla denenmiş değildir.

**iPhone'da çalışır mı?**
Telefon uygulaması şu an yalnızca Android. iPhone'da Telegram üzerinden kullanılır.

**Mac ya da Linux'ta çalışır mı?**
PC ajanı (bilgisayar yönetimi) şu an Windows içindir. Telegram, hafıza, internet ve telefon kısımları her yerde çalışır.

**Vekil benim yerime para öder mi?**
Hayır. Ödeme, banka ve para işlemleri kodda engellenir; modele bırakılmaz. Şifre alanlarına da yazmaz. Ayrıntı: [SECURITY.md](../SECURITY.md).

**Bir şeyler ters giderse nasıl durdururum?**
Telegram'a yalnızca `kys` yazın: Vekil kilitlenir. Yapmakta olduğu işi kesmek için "dur" yazın.

**Vekil İngilizce konuşabilir mi?**
`DIL=en` ortam değişkenini ekleyin (Render'da *Environment*). Cevaplar, sesli okuma ve konuşma tanıma İngilizce olur. `/durum` gibi yerleşik komut mesajları ve sabit bildirimler Türkçe kalır.

**Hafızamı nasıl yedeklerim?**
Telegram'da `/yedek` yazın: bilgiler, özetler ve ayarlar tek bir JSON dosyası olarak gelir. Kilit ve anahtar ayarları ile şifre/anahtar biçimli kayıtlar dosyaya girmez. Şu an yalnızca dışa aktarma var, geri yükleme yok.

**Hafızayı nasıl silerim?**
`/hafiza` ile görün, `/unut <anahtar>` ile tek tek silin, `/sifirla` ile konuşma geçmişini temizleyin. Tamamen silmek için Neon projenizi silmeniz yeterli.

**Sorun yaşıyorum, nereye yazayım?**
Kurulum ve genel sorular için GitHub Issues. Güvenlik açığı bulduysanız herkese açık issue açmayın; [SECURITY.md](../SECURITY.md) içindeki özel bildirim yolunu kullanın.

## English

**What is Vekil?**
A personal AI assistant that manages your computer and phone from Telegram or by voice, and learns who you are. See the [README](../README.en.md).

**Where is my data stored and who can see it?**
On your own Render server and your own Neon database. Nobody else can see it. Which data goes to which service: [GIZLILIK.md](GIZLILIK.md).

**What does it cost per month?**
Vekil itself is free and open source. What you pay for:
- **Render:** the free plan is enough (it sleeps after 15 minutes without requests; UptimeRobot keeps it awake).
- **Neon (memory):** the free tier is enough to start.
- **DeepSeek (the brain):** pay as you go with a prepaid balance. The amount depends on your usage; see [platform.deepseek.com](https://platform.deepseek.com) for current prices.
- **Groq, Tavily:** free tiers without a card (optional).
- **Twilio** (phone calls): paid, optional, most people do not need it.

**Can I use a model other than DeepSeek?**
The code talks to an OpenAI-compatible endpoint. Set `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL` to switch to another compatible provider. The model must support tool calling, and `GORSEL_MODEL` must support vision for screenshots. Not tested with every provider.

**Does it work on iPhone?**
The phone app is Android only for now. On iPhone use it through Telegram.

**Does it work on Mac or Linux?**
The PC agent (computer control) is Windows-only for now. Telegram, memory, internet and phone features work everywhere.

**Will Vekil pay for things for me?**
No. Payments, banking and money operations are blocked in code, not left to the model. It also does not type into password fields. See [SECURITY.md](../SECURITY.md).

**How do I stop it if something goes wrong?**
Write only `kys` on Telegram: Vekil locks. Write "dur" (stop) to cancel the work in progress.

**Can Vekil speak English?**
Add the `DIL=en` environment variable (on Render: *Environment*). Answers, spoken output and speech recognition become English. Built-in command messages such as `/durum` and fixed notifications stay Turkish.

**How do I back up my memory?**
Write `/yedek` on Telegram: knowledge, summaries and settings arrive as a single JSON file. Lock and key settings, and entries that look like passwords or keys, are left out. For now it is export only, there is no restore.

**How do I delete the memory?**
See it with `/hafiza`, delete single items with `/unut <key>`, clear the conversation history with `/sifirla`. To wipe everything, delete your Neon project.

**I have a problem, where do I write?**
For setup and general questions use GitHub Issues. If you found a security hole, do not open a public issue; use the private reporting route in [SECURITY.md](../SECURITY.md).
