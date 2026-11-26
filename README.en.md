<div align="center">

<img src="docs/assets/vekil_icon.jpeg" width="140" alt="OpenDelegate"/>

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:30363d&height=140&section=header&text=OpenDelegate&fontColor=ffffff&fontSize=56&animation=fadeIn" width="100%" alt=""/>

<a href="https://github.com/osmnabyram/OpenDelegate">
  <img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=500&size=19&pause=1600&color=8B949E&center=true&vCenter=true&width=640&lines=Type+or+speak%2C+OpenDelegate+gets+it+done;Your+computer+and+phone+from+one+chat;Open+source+%C2%B7+your+own+server+%C2%B7+your+data+stays+yours" alt="OpenDelegate"/>
</a>

<br/>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white&style=flat-square)
![Android](https://img.shields.io/badge/Android-Kotlin-3DDC84?logo=android&logoColor=white&style=flat-square)
![Web](https://img.shields.io/badge/Web-Chat-8A909A?style=flat-square)
![Model](https://img.shields.io/badge/Model-DeepSeek-4D6BFE?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-8B949E?style=flat-square)

</div>

<p align="center"><a href="README.md">Türkçe</a> &nbsp;|&nbsp; <b>English</b></p>

---

## What is OpenDelegate?

OpenDelegate ("proxy" in Turkish) is a **personal AI assistant that runs on your own server**. You write to it in the **web chat** in your browser or say
"delegate, bir bakar mısın" to your phone; it thinks, uses tools and finishes the job. Telegram is not needed (it stays as an optional channel).

It handles files and programs on your computer, sees the screen and uses the mouse and keyboard, opens apps on your phone,
reads messages and sets alarms. No technical knowledge needed: no commands, no menus, just sentences.

> Even for someone who is not comfortable with technology: say what you want, OpenDelegate does the rest.

The assistant talks to its user in Turkish. This page and the code comments are partly Turkish; the setup guide is
available in English ([docs/KURULUM.en.md](docs/KURULUM.en.md)) and Turkish ([docs/KURULUM.md](docs/KURULUM.md)).

## What can it do?

| | |
|---|---|
| **Web chat** | On your own address (`/sohbet`): sign in with a password and an authenticator code; answers and approval buttons appear in the browser; you can upload files, photos and voice messages; a "new message" notification (Web Push) when the tab is closed; it can be added to the phone home screen. No Telegram dependency |
| **Computer control** | Files, terminal, programs, screenshots; works on its own by looking at the screen and using mouse and keyboard |
| **Phone screen agent** | On Android: open apps, tap, type, read notifications, alarms, flashlight, calls; never touches payment or password fields |
| **Voice assistant** | Always on in the phone, wakes on "delegate bir bakar mısın"; speaks Turkish (recognition: Groq Whisper, voice: Edge TTS) |
| **Persistent memory** | Knows you and learns your preferences; browse memory as a 3D **mind map** |
| **Calendar (read-only)** | Answers "what is on today, do I have a meeting tomorrow" from the secret iCal address of Google Calendar; today's events go into the morning briefing. Never adds or deletes |
| **Reminders and briefing** | Timed reminders, to-do list, morning briefing (weather, plan, news), topic follow-up |
| **Self-improvement** | Reviews itself every week and turns ordinary lessons into rules; never touches money or security topics on its own |
| **Internet and files** | Web search, page summaries, OneDrive (rclone), reads Word/Excel/PDF/PowerPoint, understands photos |
| **Phone calls** | Can call you when something important happens (Twilio, optional) |
| **Remote PC wake-up** | A smart plug plus a BIOS setting turns on a powered-off computer; OpenDelegate waits for the agent to connect |
| **Admin page** | `/yonetim` in the chat: status, memory counts, PC agent, recent jobs (never shows conversation text) |
| **Security** | Payments and banking are blocked in code; constant-time tokens, secret masking, rate limits, kill switch ([SECURITY.md](SECURITY.md)) |

## Screenshot

<p align="center"><img src="docs/assets/uygulama.png" width="180" alt="OpenDelegate Android app"/></p>

<p align="center"><img src="docs/assets/zihin_haritasi.jpg" width="760" alt="OpenDelegate 3D mind map"/><br/><sub>3D mind map: every memory entry sits around a planet for its type.</sub></p>

## How does it work?

```mermaid
flowchart LR
    U([You]) -- text --> T[Web chat]
    U -- "delegate, bir bakar mısın" --> A[Android app]
    T --> B
    A --> B
    subgraph B[OpenDelegate server - Render]
      direction TB
      M[Model: DeepSeek] --- H[(Memory: Postgres)]
      M --- K[Tools]
    end
    K -- task queue --> P[PC agent]
    K --> W[Web / OneDrive]
    P --> PC[(Your computer)]
    A --> PH[(Your phone)]
```

- The **brain** is a small Python server (Starlette + python-telegram-bot). It runs on Render's free plan.
- The **PC agent** is a small script on your computer; it pulls tasks from the server and opens no inbound connection.
- The **Android app** listens for the wake phrase on the device (Vosk) and reads the screen through the accessibility service.

## Quick start

> **Setting it up for someone with no technical background?** Step-by-step guide: [docs/KURULUM.en.md](docs/KURULUM.en.md)

You need: Python 3.12, a [DeepSeek](https://platform.deepseek.com) API key and an authenticator app on your phone (Google/Microsoft Authenticator).

```bash
git clone https://github.com/osmnabyram/OpenDelegate.git
cd OpenDelegate
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python kurulum.py                                  # wizard: asks for keys, writes the .env file
python vekil/main.py                               # open http://localhost:10000/sohbet in your browser
```

The wizard writes `.env`, takes your web chat password and generates the authenticator key.
To set up by hand, copy [`.env.example`](.env.example) to `.env` and fill it in.

### Deploy to the cloud (Render)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/osmnabyram/OpenDelegate)

The button reads `render.yaml` and prepares the service; the form asks for `DEEPSEEK_API_KEY`, `WEB_PAROLA`, `WEB_TOTP_SIR` and (recommended) `DATABASE_URL` (`python kurulum.py` generates the `WEB_TOTP_SIR` value). Render generates the random keys itself. When it is up, sign in at `https://<your-service-address>/sohbet`. To set it up by hand:

1. *New → Web Service →* this repo → **Language: Docker** → *Health Check Path* `/health`.
2. Environment: `DEEPSEEK_API_KEY`, `WEB_PAROLA`, `WEB_TOTP_SIR`, `OPENDELEGATE_SIR`, `AJAN_SECRET`.
3. For persistent memory add a [Neon](https://neon.tech) Postgres URL as `DATABASE_URL` (if empty, temporary SQLite is used).
4. The free plan sleeps the service; set up a monitor (e.g. UptimeRobot) that requests `/health` every 5 minutes.

### PC agent

Copy the `ajan/` folder to your computer, rename `ajan/.env.example` to `.env`, fill in `VEKIL_URL` and
`AJAN_SECRET`, and start it with `python ajan.py`. For screenshots one package is needed: `pip install mss`.

### Android app

**Ready-made APK:** to try it without building, download the signed APK from the [Releases](https://github.com/osmnabyram/OpenDelegate/releases) page.
To build it yourself, open `android/` in Android Studio or build from the command line. The package name is `com.opendelegate.app`.

```bash
cd android
python imza_olustur.py          # ONCE: creates the signing key (android/imza/ + keystore.properties)
./gradlew assembleRelease       # signed APK: app/build/outputs/apk/release/app-release.apk
./gradlew assembleDebug         # test APK (release is recommended for sideloading)
```

The APK is distributed as a plain file outside the Play Store; the user allows "install from unknown sources" on the phone.
**Back up the signing key (`android/imza/` and `keystore.properties`) somewhere safe**: updates require the same key, and if
you lose it users must uninstall and reinstall. These files never enter git.

**Customer-specific APK:** `python musteri_apk.py` asks for the customer name, server address and (optionally) the phone key,
embeds them in the APK and produces a signed `cikti/<customer>.apk`; the customer enters nothing on first launch. Give an APK with an embedded key only to that one customer.

Without embedded values, the first launch asks for your server address (https) and phone key (`SESLI_TOKEN`); the key is stored
encrypted with the Keystore. Accessibility and notification access permissions are requested from inside the app.

## Manual setup: required technologies

The wizard checks your keys and writes `.env`, but **you** must create the accounts and tools below.
The last column says which are required.

| Technology | What for | Required? |
|---|---|---|
| Python 3.12 and `pip install -r requirements.txt` | OpenDelegate itself | Yes |
| Authenticator app (Google/Microsoft Authenticator) | The 6-digit code for web chat sign-in | Recommended |
| Telegram account and bot (@BotFather → `/newbot`) | An extra channel to chat from Telegram too | No |
| DeepSeek API account ([platform.deepseek.com](https://platform.deepseek.com)) | OpenDelegate's brain | Yes |
| Render account | Keeping OpenDelegate running while your computer is off (Render builds the Docker image) | If running in the cloud |
| UptimeRobot or similar | Stops the free Render plan from sleeping: a request to `/health` every 5 minutes | If on Render free plan |
| Neon Postgres | Persistent memory (otherwise temporary SQLite) | No |
| Groq account | Voice message transcription | No |
| Tavily account | Web search | No |
| rclone and OneDrive | Cloud file tasks | No |
| PC agent: `ajan/` folder, Python, `pip install mss` | Managing the computer remotely | No |
| Android Studio and JDK | Building the phone app (the Vosk speech model downloads on first launch) | No |
| Twilio | OpenDelegate calling you on the phone | No |

To know where to put keys and addresses, look at the `.env` file: the wizard writes your answers there, and you can add
missing ones by hand using the lines in [`.env.example`](.env.example). On Render, enter the same values in the service's *Environment* section.

## Settings

All settings are environment variables; secrets are never written in code. The main ones:

| Variable | Description |
|---|---|
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` | Model key and name (default `deepseek-flash`) |
| `WEB_PAROLA`, `WEB_TOTP_SIR`, `WEB_OTURUM_SAAT` | Web chat: sign-in password (12+ characters), authenticator key (base32) and session length (hours, default 12). If `WEB_PAROLA` is empty the web chat is off |
| `OPENDELEGATE_SIR` | Seed for derived links and keys; a long random value. Required when Telegram is not used |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional: the Telegram channel and its single authorized chat. If empty, Telegram is off |
| `KULLANICI_ADI`, `SEHIR_AD`, `SEHIR_LAT`, `SEHIR_LON` | Briefing greeting and weather city |
| `DIL` | Assistant language: `tr` (default) or `en`. With `en`, answers, spoken output and speech recognition are English; built-in command messages such as `/durum` stay Turkish |
| `DATABASE_URL` | Persistent memory (Neon Postgres) |
| `GROQ_API_KEY` | Voice message and phone speech recognition |
| `TAVILY_API_KEY` | Web search |
| `TAKVIM_ICS_URL` | Calendar: secret iCal address(es) (https, comma separated). If empty the calendar is off. The address is a secret, share it with nobody |
| `AJAN_SECRET`, `VEKIL_URL` | PC agent identity and server address |
| `KILIT_TUZ`, `KILIT_OZET`, `KILIT_OZET_SADE` | Kill switch (`kys`) password digest; the wizard generates it and the password itself is not stored. If empty, `kys` is off |
| `KILIT_KURTARMA_TUZ`, `KILIT_KURTARMA_OZET` | Password-independent, per-installation recovery code digest (see [SECURITY.md](SECURITY.md)) |
| `SESLI_TOKEN` | Android app key (derived from the main secret if empty; a separate random value is recommended) |
| `TWILIO_*`, `KULLANICI_TELEFON` | Phone calls (optional) |

## Make it yours

OpenDelegate is a **foundation**; add or remove what you need:

- **New tool (recommended):** drop a `.py` file into the [`eklentiler/`](eklentiler/README.md) folder; it loads without touching the core code. Template: [`eklentiler/_ornek.py`](eklentiler/_ornek.py).
- **New built-in tool:** define a `Tool` in [`tools.py`](vekil/tools.py) and wire it into the tool dispatch in [`main.py`](vekil/main.py).
- **Memory seed:** use [`hafiza_tohum.py`](vekil/hafiza_tohum.py) to write what must be known on first start (company info, rules).
- **Briefing plan:** connect your calendar or business system with `brifing.Brifing(plan_kaynagi=...)`.
- **Address and identity:** the system prompts are in `main.py`, `arama.py` and `telefon_ajan.py`.

## Security

OpenDelegate manages your computer and phone, so security is a core design goal: payments and banking are rejected in code,
all endpoints are protected by constant-time keys, secrets are masked in logs, and the kill switch (`kys`) locks everything.
Details and how to report a vulnerability: [SECURITY.md](SECURITY.md).

## Development

```bash
python -m unittest discover -s tests -t . -q       # tests (no real keys needed)
```

FAQ: [docs/SSS.md](docs/SSS.md) (bilingual) · Data and privacy: [docs/GIZLILIK.md](docs/GIZLILIK.md) (bilingual) · [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)

The code uses Turkish naming. Architecture map and developer notes: [CLAUDE.md](CLAUDE.md).

## License and author

[MIT](LICENSE) © 2026 **Osman Bayram** · [github.com/osmnabyram](https://github.com/osmnabyram)

<div align="center"><img src="https://capsule-render.vercel.app/api?type=waving&color=0:30363d,100:0d1117&height=90&section=footer" width="100%" alt=""/></div>
