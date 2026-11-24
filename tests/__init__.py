"""Testler gerçek anahtar istemez: zorunlu ayarlar sahte değerlerle doldurulur (varsa gerçek .env'e dokunulmaz).
Uygulama modülleri vekil/ klasöründe; import edilebilsin diye yola eklenir."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vekil"))
os.environ.setdefault("DEEPSEEK_API_KEY", "test-anahtar")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:" + "AA" + "x" * 34)  # sahte; depo taraması gerçek token biçimi bulmasın
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")
# Kill switch testleri için sahte şifre özeti (çalışma anında üretilir, depoda gerçek özet olmaz)
import hashlib

_TUZ = b"test-tuz-test-tuz"
os.environ.setdefault("KILIT_TUZ", _TUZ.hex())
os.environ.setdefault("KILIT_OZET", hashlib.pbkdf2_hmac("sha256", b"test-sifre", _TUZ, 600_000).hex())
os.environ.setdefault("KILIT_OZET_SADE", hashlib.pbkdf2_hmac("sha256", b"test-sifre", _TUZ, 600_000).hex())
