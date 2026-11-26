<p align="center"><a href="KURULUM.md">Türkçe</a> &nbsp;|&nbsp; <b>English</b></p>

# Step-by-step setup guide (from zero to done)

This guide is for the person who installs OpenDelegate for a user (a customer) **from scratch**. It assumes the user has no
technical background and has just bought their phone and computer. Go in order, without skipping back.

> Open the accounts with the **user's own email**, and hand the keys and passwords to them. Never pay for anything
> with the user's card on their behalf; let them do it themselves while you are next to them.

Note: the setup wizard and the Android app show Turkish text. Where this guide quotes a button or screen name, the
Turkish original is given in parentheses.

## Contents

0. [Preparation before the visit](#0-preparation-before-the-visit)
1. [Accounts](#1-accounts)
2. [Setup wizard](#2-setup-wizard-on-the-users-windows-computer)
3. [Deploy to Render](#3-deploy-to-render-keeping-vekil-running-247)
4. [PC agent](#4-pc-agent-windows)
5. [Building the phone app (APK)](#5-building-the-phone-app-apk)
6. [Installing on the phone](#6-installing-on-the-phone)
7. [Handover test](#7-handover-test)
8. [What to tell the user](#8-what-to-tell-the-user)
9. [Troubleshooting](#9-troubleshooting)

---

## 0. Preparation before the visit

- [ ] Get the latest repo: `git clone https://github.com/osmnabyram/OpenDelegate` (or `git pull`).
- [ ] If the user has special requests (form of address, rules, a new tool), copy the code for that user and customize it
      (`vekil/hafiza_tohum.py` for initial knowledge, `vekil/tools.py` for a new tool). Do not put user data in the main repo.
- [ ] **The Android signing key must be ready:** `android/imza/` and `android/keystore.properties`
      (if missing, run `python android/imza_olustur.py`). Keep a backup somewhere else (USB stick, password manager).
- [ ] Is the user's phone **Android**? On an iPhone there is no phone app; only the web chat and the computer are set up.
- [ ] Is the user's computer **Windows**? The PC agent is Windows-only for now (screen, mouse, program tasks). On Mac/Linux
      Web chat, phone, internet and memory still work; computer control does not.

## 1. Accounts

Open all of them with the user's email, together in the browser. Write the keys down; they go into the `.env` file at the end.

| Account | How | Required? |
|---|---|---|
| **Authenticator app** | Install Google Authenticator or Microsoft Authenticator on the phone (free, from the app store). Signing in to the web chat asks for the 6-digit code from it in addition to the password. The wizard shows a key; add it in the app with *enter a setup key*. | Recommended |
| **Telegram (optional)** | If you also want to chat from Telegram: in Telegram open **@BotFather** → `/newbot`, then add the bot token to `.env` as `TELEGRAM_BOT_TOKEN` and your chat id as `TELEGRAM_CHAT_ID`. Not needed for the web chat. | No |
| **DeepSeek** | [platform.deepseek.com](https://platform.deepseek.com) → account → *API Keys* → new key (`sk-...`). Pay as you go: the user tops up *Balance* with a small amount on their own card; it lasts months. | Yes |
| **Render** | [render.com](https://render.com) → account (GitHub or email). The free plan is enough, but it sleeps after 15 minutes without requests (UptimeRobot fixes this). | Yes (to run in the cloud) |
| **UptimeRobot** | [uptimerobot.com](https://uptimerobot.com) → free account. So that Render does not sleep. | Effectively yes |
| **Neon** | [neon.tech](https://neon.tech) → account → new project → *Connection string* (pooled) = `DATABASE_URL`. Without it OpenDelegate uses temporary memory, and memory is wiped every time Render restarts. | Recommended |
| **Groq** | [console.groq.com](https://console.groq.com) → *API Keys*. For voice messages and phone voice. | Recommended |
| **Calendar** | Google Calendar → *Settings → pick the calendar → Integrate calendar → Secret address in iCal format*; enter the address as `TAKVIM_ICS_URL` (read-only; share the address with nobody). | No |
| **Tavily** | [app.tavily.com](https://app.tavily.com). Web search. | No |
| **OneDrive / rclone** | If cloud file tasks are needed (advanced). | No |
| **Twilio** | OpenDelegate calling the user on the phone (paid, usually not needed). | No |

## 2. Setup wizard (on the user's Windows computer)

1. **Install Python:** [python.org/downloads](https://www.python.org/downloads) → Python 3.12 → during install tick
   **"Add python.exe to PATH"**.
2. **Download the OpenDelegate files:** on GitHub *Code → Download ZIP*, extract to the desktop (example: `C:\OpenDelegate`).
3. Open the command prompt (Windows key → `cmd`) and run in order:
   ```
   cd C:\OpenDelegate
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python kurulum.py
   ```
4. In the window that opens (OpenDelegate picture on the left, *İleri* (Next) bottom right) fill in the questions together with the user:
   name, job, uses, devices, city; then the DeepSeek key.
   - **Web chat password:** at least 12 characters. On the next page the wizard shows a key for the authenticator app; the user adds it in the app on the phone.
   - **Emergency stop password:** the user chooses the `kys` password (at least 8 characters). The wizard writes only a verification
     digest to `.env`, not the password itself. REMIND THE USER THAT THE PASSWORD MUST BE WRITTEN DOWN.
   - **Recovery code:** the next page shows a random code, independent of the password and specific to this installation (shown
     only once). The user must write it down somewhere safe. They may also leave a copy with you (the installer); this is not
     required, it is the user's choice. If you keep one, store it in your own private record (for example in a separate note file
     named after the customer); **there is no shared or fixed key**, every installation's code is different.
   - On the last page paste Groq, Tavily and Neon (`DATABASE_URL`) if you have them. The **"Kur" (Install)** button creates the `.env` file.
5. **Try it locally:** `python vekil\main.py` → open `http://localhost:10000/sohbet` in the browser, sign in with the password and the code from the app, write "merhaba"; an answer should come. Stop with `Ctrl+C`.
   This is only a test; the real run happens on Render and continues while the computer is off.
6. **The `.env` file:** all the keys from the setup are in it. Give the user a copy (USB stick or password manager).
   Do not send it to anyone, do not upload it to the internet, do not take screenshots of it.

## 3. Deploy to Render (keeping OpenDelegate running 24/7)

1. Render → **New + → Web Service → Public Git Repository** → repo address (`https://github.com/osmnabyram/OpenDelegate`) → *Connect*.
   If you made user-specific code changes, put them in a separate GitHub repo under the user's account and connect that one.
2. **Language: Docker**, **Instance Type: Free**, *Advanced → Health Check Path:* `/health`.
3. In the **Environment** section enter these values from `.env` one by one:
   `DEEPSEEK_API_KEY`, `WEB_PAROLA`, `WEB_TOTP_SIR`, `OPENDELEGATE_SIR`, `AJAN_SECRET`, `SESLI_TOKEN`,
   `KULLANICI_ADI`, `SEHIR_AD`, `PROFIL`, `KILIT_TUZ`, `KILIT_OZET`, `KILIT_OZET_SADE`,
   `KILIT_KURTARMA_TUZ`, `KILIT_KURTARMA_OZET`, and if present `DATABASE_URL`, `GROQ_API_KEY`, `TAVILY_API_KEY`.
   Do **not** enter `WEBHOOK_URL`; Render provides the address itself.
4. **Create Web Service.** The first build takes 5-10 minutes. The logs should show a line saying Telegram is off and the web chat is used (`Telegram kapalı`).
5. **Check:** in the browser open `https://<service-name>.onrender.com/health` → `ok`. Open `https://<service-name>.onrender.com/sohbet`, sign in and write; an answer should come.
6. **Save** the service address (`https://....onrender.com`): the phone app and the PC agent will use it.
7. **UptimeRobot:** *Add New Monitor → HTTP(s)* → URL `https://<service-name>.onrender.com/health` → interval **5 minutes**.
   Without this the free Render plan sleeps and the first message gets a slow answer.
8. **Your own domain (optional):** in Render open the service → *Settings → Custom Domains → Add* → enter an address like `chat.example.com`. Render shows a **CNAME** record; add it in your domain provider's DNS panel. Within minutes Render issues a free **https certificate** itself. Use a separate subdomain (e.g. `ahmet.example.com`) and a separate service for each customer.

## 4. PC agent (Windows)

1. Copy the `ajan` folder to `C:\vekil-ajan`.
2. In the command prompt: `pip install mss`
3. Create `C:\vekil-ajan\.env` (copy `ajan\.env.example`) and write:
   ```
   VEKIL_URL=https://<service-name>.onrender.com
   AJAN_SECRET=<EXACTLY THE SAME as AJAN_SECRET in the main .env>
   ```
4. Start it: `C:\vekil-ajan\baslat.bat` (or `python ajan.py`) → it should print `OpenDelegate'e bağlandı` (connected to OpenDelegate).
5. To start automatically with Windows: `Win+R` → `shell:startup` → put a shortcut to `baslat.bat` there.
6. Try it from the web chat: "masaüstümde ne var" (what is on my desktop) or "ekran görüntüsü al" (take a screenshot). If an answer comes, it works.

The agent works only while the computer is **on and connected to the internet**.

## 5. Building the phone app (APK)

> **Shortcut:** if you do not need the server address and key embedded in the app, download the ready-made signed APK
> from [Releases](https://github.com/osmnabyram/OpenDelegate/releases) and skip to step 6. The user then enters the address
> and `SESLI_TOKEN` in the app on first launch.

On the installer's computer, with the user's Render address and `SESLI_TOKEN` at hand:

```
cd android
python musteri_apk.py
```

Enter the customer name, the Render address (`https://...`) and the `SESLI_TOKEN` (from the user's `.env`).
Result: `android/cikti/<customer>.apk` (signed; address and key embedded).

- Give this APK **only to that user**; if it reaches anyone else, that user's key has leaked.
- A JDK is needed the first time (the `jbr` folder of Android Studio is enough); the first build takes a few minutes.
- Deliver the APK by copying it to the user's phone over USB into `Files > Downloads`, or by sending it to the user's own account.

## 6. Installing on the phone

Menu names vary a little by brand and Android version (Samsung, Xiaomi, Pixel).

1. In the Files app tap the APK → if "Allow install from unknown sources" appears, allow it → **Install**.
2. Open the OpenDelegate app. On first launch the speech model (Vosk) is downloaded: keep the phone **connected to the internet** and wait.
3. Grant the permissions in order:
   - **Microphone:** allow.
   - **Show notifications:** allow if asked.
   - **Display over other apps:** *Settings → Apps → OpenDelegate* → turn on the permission.
   - **Battery:** *Settings → Apps → OpenDelegate → Battery → Unrestricted* (otherwise it sleeps in the background and does not hear "vekil").
   - **Accessibility** (to read and tap the screen, **the most important one**): *Settings → Accessibility → Installed apps →
     OpenDelegate* → turn on. If Android 13+ says "Restricted setting": *Settings → Apps → OpenDelegate → top-right three dots →
     Allow restricted settings*, then turn accessibility on again.
   - **Notification access** (so it can read notifications): *Settings → Notifications → Notification access → OpenDelegate* → turn on.
   - **Contacts and Phone permission:** allow when asked, if calling is wanted.
4. If needed, the screen-lock PIN can be entered in the app (for waking while locked; stored encrypted only on the phone).
5. If the address is not embedded in the APK (you did not use `musteri_apk.py`): enter the Render address
   (`https://...`) and the `SESLI_TOKEN` in the app's settings.

## 7. Handover test

Do not leave until all of these pass:

- [ ] Web chat: sign in with password and code, "merhaba" → an answer comes.
- [ ] Web chat: "yarın sabah 9'da bana şunu hatırlat: ..." (remind me tomorrow at 9 am: ...) → it accepts.
- [ ] With the PC on: "ekran görüntüsü al" → it arrives.
- [ ] Phone: with the screen on, "delegate, bir bakar mısın" → it listens; ask a question → it answers aloud.
- [ ] Phone: a command like "alarm kur" (set an alarm) / "feneri aç" (turn on the flashlight) works.
- [ ] With the phone locked and the computer off, write in the web chat → an answer still comes through Render
      (except computer tasks).
- [ ] `/health` returns "ok", UptimeRobot is green.
- [ ] The `.env` backup is with the user, the keys are with the user.

## 8. What to tell the user

- They can write to OpenDelegate in the web chat or say "delegate, bir bakar mısın" to the phone.
- OpenDelegate does not touch payments, banking or money operations; the code blocks it. It does not type into password fields either.
- **Emergency stop:** writing only `kys` in the chat locks OpenDelegate. It is unlocked with the password chosen at setup or with the
  recovery code shown at setup.
- Writing "dur" (stop) cancels the work in progress.
- The keys (`.env`) are secret; share them with nobody. If they leak, new ones are generated.
- Updates are done on Render and (if needed) on the phone with a new APK. Because the APK is built with the same signing key,
  it installs over the old one and data and permissions are kept.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Cannot sign in to the web chat | Is the password exactly `WEB_PAROLA`; the 6-digit code depends on the phone's clock (keep automatic time on). After 5 wrong tries wait 15 minutes. If the page does not open at all, `WEB_PAROLA` is empty. |
| No answer comes | Check Render → *Logs*; the service may be asleep (UptimeRobot); is `DEEPSEEK_API_KEY` correct. |
| "Ajan çevrimdışı" (agent offline) | The computer is off or has no internet, or the agent is not running; is `AJAN_SECRET` the same in both places. |
| Phone does not wake on "vekil" | Battery restriction, microphone permission, accessibility on? Did the Vosk model finish downloading? |
| Memory disappears | `DATABASE_URL` (Neon) was not entered. |
| Render slow on the first request | The free plan fell asleep; UptimeRobot should ping every 5 minutes. |
| `kys` password forgotten | If the user kept the recovery code (or left it with you) it unlocks with that. If neither exists: the password is not stored, so it cannot be recovered; set a new password and recovery code with `python kurulum.py`, paste the `KILIT_*` values from `.env` into the same variables on Render and restart the service. |
| `kys` does not work | Are the `KILIT_*` values in `.env` and also entered on Render? If not, the kill switch is off. |
| New APK will not install ("package conflicts") | The signing key is different; uninstall the old app and install the new one. Never lose or change the signing key. |
