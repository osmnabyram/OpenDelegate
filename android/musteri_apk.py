"""Müşteriye özel imzalı APK üretir: python musteri_apk.py

Sunucu adresi (ve isterseniz telefon anahtarı) APK'ya gömülür; müşteri uygulamayı açınca hiçbir şey girmez.
Önce bir kez `python imza_olustur.py` çalıştırılmış olmalı. Çıktı: cikti/<musteri>.apk (git'e girmez).
Anahtar gömülü APK'yı yalnızca o müşteriye verin; başkasına gitmesi anahtarın sızması demektir.
"""

import getpass
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent
APK = KOK / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"


def main() -> int:
    for akim in (sys.stdout, sys.stderr):
        try:
            akim.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    if not (KOK / "keystore.properties").exists():
        print("Önce imza anahtarı gerekli: python imza_olustur.py")
        return 1
    musteri = re.sub(r"[^A-Za-z0-9_-]+", "-", input("Müşteri adı (dosya adı olur): ").strip()) or "musteri"
    url = input("Sunucu adresi (https://...): ").strip().rstrip("/")
    if not url.startswith("https://"):
        print("Adres https:// ile başlamalı.")
        return 1
    token = getpass.getpass("Telefon anahtarı SESLI_TOKEN (boş bırakılırsa müşteri uygulamada girer): ").strip()
    komut = ["gradlew.bat" if os.name == "nt" else "./gradlew", "assembleRelease", f"-PsunucuUrl={url}"]
    if token:
        komut.append(f"-PsesliToken={token}")
    env = dict(os.environ)
    jbr = Path(r"C:\Program Files\Android\Android Studio\jbr")
    if "JAVA_HOME" not in env and jbr.exists():
        env["JAVA_HOME"] = str(jbr)
    if subprocess.run(komut, cwd=KOK, env=env).returncode != 0 or not APK.exists():
        print("Derleme başarısız.")
        return 1
    hedef = KOK / "cikti" / f"{musteri}.apk"
    hedef.parent.mkdir(exist_ok=True)
    shutil.copy2(APK, hedef)
    print(f"Hazır: {hedef}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
