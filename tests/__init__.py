"""Testler gerçek anahtar istemez: zorunlu ayarlar sahte değerlerle doldurulur (varsa gerçek .env'e dokunulmaz).
Uygulama modülleri vekil/ klasöründe; import edilebilsin diye yola eklenir."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vekil"))
os.environ.setdefault("DEEPSEEK_API_KEY", "test-anahtar")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:" + "AA" + "x" * 34)  # sahte; depo taraması gerçek token biçimi bulmasın
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")
