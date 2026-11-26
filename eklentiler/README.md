# Eklentiler / Plugins

Müşteriye özel araçları ana koda dokunmadan buraya koyun. / Put customer-specific tools here without touching the core code.

## Türkçe

1. `_ornek.py` dosyasını `_` olmadan kopyalayın (ör. `takvim.py`).
2. `ARAC` içinde araç adı, açıklama, parametreler ve riski; `calistir` içinde işi yazın.
3. OpenDelegate'i yeniden başlatın (Render'da *Manual Deploy*). Açılış logunda `Eklenti yüklendi: <ad>` görünür.

Kurallar:
- `_` ile başlayan dosyalar yüklenmez.
- Bozuk eklenti atlanır, OpenDelegate çalışmaya devam eder (log'a uyarı düşer).
- Araç adı OpenDelegate'in kendi araçlarıyla çakışamaz.
- `risk` yalnızca `düşük` ya da `orta` olabilir; ödeme ve kritik işlemler eklentiyle açılmaz.
- Her çağrı 60 saniye ile sınırlıdır.
- API anahtarlarını koda değil ortam değişkenine (`os.environ`) koyun.

**Eklenti kodu sunucuda tam yetkiyle çalışır**: yalnızca kendi yazdığınız ya da okuyup güvendiğiniz kodu ekleyin.

## English

1. Copy `_ornek.py` without the leading `_` (e.g. `calendar.py`).
2. Define the tool name, description, parameters and risk in `ARAC`, and the work in `calistir`.
3. Restart OpenDelegate (on Render: *Manual Deploy*). The startup log shows `Eklenti yüklendi: <name>`.

Rules:
- Files starting with `_` are skipped.
- A broken plugin is skipped and OpenDelegate keeps running (a warning is logged).
- The tool name must not collide with a built-in tool.
- `risk` can only be `düşük` (low) or `orta` (medium); payments and critical actions cannot be enabled by a plugin.
- Each call is limited to 60 seconds.
- Keep API keys in environment variables, not in code.

**Plugin code runs on the server with full privileges**: only add code you wrote or have read and trust.
