"""Örnek eklenti şablonu. Kullanmak için: bu dosyayı `_` olmadan kopyalayın (ör. `saat.py`), düzenleyin, Vekil'i yeniden başlatın.

`_` ile başlayan dosyalar yüklenmez. Ayrıntı: eklentiler/README.md
"""

from datetime import datetime

ARAC = {
    "ad": "saat_sor",  # küçük harf, rakam, _ ; Vekil'in kendi araçlarıyla çakışmamalı
    # Model bu metne bakarak aracı NE ZAMAN çağıracağına karar verir; açık yazın.
    "aciklama": "[Örnek] Kullanıcı saati ya da tarihi sorarsa çağır. Başka konuda çağırma.",
    "parametreler": {"type": "object", "properties": {}},  # argüman gerekmiyorsa boş
    "risk": "düşük",  # "düşük" (sessiz) | "orta" (kullanıcıya bilgi satırı gider)
}


def calistir(argumanlar):
    """Metin döner (başarılı sayılır) ya da (False, "hata metni"). async def de olabilir."""
    return datetime.now().strftime("%d.%m.%Y %H:%M")
