"""APK imza anahtarını (keystore) bir kez üretir: python imza_olustur.py

Satacağınız tüm APK'lar bu anahtarla imzalanır. Güncellemeler aynı anahtar ister: KAYBEDERSENİZ müşteriler
güncelleyemez, uygulamayı silip baştan kurmak zorunda kalır. imza/ klasörünü ve keystore.properties dosyasını
güvenli bir yere (şifre yöneticisi, şifreli yedek) kopyalayın; git'e girmez.
Gerekli: JDK içindeki keytool (Android Studio'nun jbr klasöründe de vardır).
"""

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent
ANAHTAR = KOK / "imza" / "vekil-imza.jks"
AYAR = KOK / "keystore.properties"


def keytool() -> str | None:
    yol = shutil.which("keytool")
    if yol:
        return yol
    for ev in (os.getenv("JAVA_HOME", ""), r"C:\Program Files\Android\Android Studio\jbr"):
        aday = Path(ev) / "bin" / ("keytool.exe" if os.name == "nt" else "keytool")
        if ev and aday.exists():
            return str(aday)
    return None


def main() -> int:
    for akim in (sys.stdout, sys.stderr):  # Windows konsolu/borusu Türkçe karakterde çökmesin
        try:
            akim.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    if ANAHTAR.exists() or AYAR.exists():
        print("İmza anahtarı zaten var; üzerine yazmıyorum (eskisi kaybolursa güncelleme yapılamaz).")
        print(f"  {ANAHTAR}\n  {AYAR}")
        return 1
    kt = keytool()
    if not kt:
        print("keytool bulunamadı. JDK kurun ya da JAVA_HOME'u Android Studio'nun jbr klasörüne ayarlayın.")
        return 1
    sahip = input("Anahtar sahibi (şirket ya da adınız) [OpenDelegate]: ").strip() or "OpenDelegate"
    sifre = secrets.token_urlsafe(18)
    ANAHTAR.parent.mkdir(exist_ok=True)
    komut = [kt, "-genkeypair", "-v", "-keystore", str(ANAHTAR), "-alias", "vekil", "-keyalg", "RSA", "-keysize", "4096",
             "-validity", "10000", "-storepass", sifre, "-keypass", sifre,
             "-dname", "CN=" + sahip.replace(",", " ") + ", O=OpenDelegate"]
    if subprocess.run(komut, capture_output=True, text=True).returncode != 0:
        print("Anahtar üretilemedi.")
        return 1
    AYAR.write_text(f"storeFile=imza/vekil-imza.jks\nstorePassword={sifre}\nkeyAlias=vekil\nkeyPassword={sifre}\n",
                    encoding="utf-8")
    try:
        AYAR.chmod(0o600)
    except OSError:
        pass
    print("Hazır. İmzalı APK için:  cd android && gradlew assembleRelease")
    print("Çıktı: app/build/outputs/apk/release/app-release.apk")
    print("ÖNEMLİ: android/imza/ klasörünü ve keystore.properties dosyasını güvenle YEDEKLEYİN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
