"""Çalışma disiplini: Vekil'in işi OTONOM bitirmesi + sadece gerçek kısırdöngüde durması (Başvekil ve işçiler).

Kurallar (bir tur = kullanıcının tek mesajına verilen cevap ya da bir işçinin görevi):
- Başarısız bir çağrı, arada durumu değiştiren BAŞARILI bir işlem olmadan aynen tekrar ÇALIŞTIRILMAZ
  (modele "önce sebebini düzelt" denir). Dosya düzeltildikten sonra aynı komutu yeniden çalıştırmak serbest.
- Derleme/test hatası (sıfır olmayan çıkış kodu) normal iterasyondur: durak sebebi değildir.
- DURAK sadece kısırdöngüde: aynı başarısız çağrıyı değişiklik yapmadan 3 kez daha denemek ya da üst üste 6 boş
  arama. Durakta model soru SORMAZ: ne yaptığını, ne kaldığını, sıradaki adımı yazar.

Kullanıcının mesajındaki kesin Windows yolları turun başında "[Bilinenler]" olarak modele verilir.
"""

from __future__ import annotations

import json
import re
from typing import Any

KURAL = """Çalışma disiplini (her vekil için geçerli) — OTONOM ÇALIŞ:
- Kullanıcının amacı aradan çıkmak: verilen işi baştan sona SEN bitir. Planla, yap, sonucu kontrol et (kodu çalıştır/test
  et), hata çıkarsa hata mesajını oku, sebebini düzelt, tekrar dene. Takıldığın yerde webde_ara/webde_oku ile
  kendin araştır. Başka yol dene. Pes etmeden önce en az birkaç farklı çözüm dene.
- "Devam edeyim mi?", "Nasıl ilerleyelim?", "Şunu yapayım mı?" diye ASLA sorma. Ara bilgi verirsen kısa olsun ve
  soru içermesin; işe devam et.
- SADECE kullanıcıdan gelmesi şart olan bir şey eksikse sor: şifre/erişim, ödeme, ya da hedef gerçekten belirsizse
  (hangi dosya/hangi kişi) ve makul tahmin yoksa. O zaman bile tek, net soru.
- Kullanıcı KESİN bir yol / ad verdiyse doğrudan onu kullan; o dosya ya da kök için ayrıca arama/listeleme yapma.
  "[Bilinenler]" bloğundakileri tekrar sorgulama. Recursive taramaya EN DAR kökten başla.
- Başarısız bir çağrıyı HİÇBİR ŞEY değiştirmeden aynen tekrar etme: önce sebebini düzelt (dosyayı düzelt, başka
  komut/yol/argüman dene), sonra tekrar çalıştır. Düzelttikten sonra aynı komutu yeniden çalıştırmak serbest.
- İş bitince kısa rapor: ne yaptın, sonuç ne, (varsa) yapamadığın ve somut sebebi."""

DURAK_TALIMATI = (
    "[DURAK] Bu turda tool kullanamazsın. {neden} {kime} TEK kısa mesaj yaz: ne yaptın / neyi bitirdin, neyin "
    "eksik kaldığı ve somut sebebi (gerçek hata mesajıyla), bir sonraki somut adımın ne olacağı. 'Nasıl "
    "ilerleyelim?', 'Devam edeyim mi?' gibi SORU SORMA; 'devam' yazılırsa kaldığın yerden sürdüreceğini söyle. "
    "Sadece kullanıcıdan gelmesi şart bir şey (şifre, erişim, karar) varsa onu net iste. Sonuç uydurma."
)

# Tırnaklı yol olduğu gibi; tırnaksız yolda ara klasörlerde boşluk olabilir (arkasından '\' gelir),
# son parçada olamaz (yoksa "C:\a\kedi.png bir de C:\b" tek yol sanılırdı).
_YOL_TIRNAKLI = re.compile(r"[\"“”']([A-Za-z]:\\[^\"“”'\r\n<>|?*]+)[\"“”']")
_YOL = re.compile(r"(?<![\w])[A-Za-z]:\\(?:[^\\\r\n\"'<>|?*,:;]+\\)*[^\\\s\"'<>|?*,:;]*")
_KUYRUK_NOKTALAMA = ".,;:!)]}'\" "

# Başarısız / boş sonuç işaretleri (tool'ların kendi çıktı biçimleri).
_BOS = (
    re.compile(r"^HATA"),
    re.compile(r"\| 0 girdi\]"),  # dosya_listele / onedrive_listele boş klasör ya da desen eşleşmedi
    re.compile(r"\] Bulunamadı"),  # onedrive_ara
    re.compile(r"Sonuç bulunamadı"),  # webde_ara
    re.compile(r"\| 0 sonuç, "),  # dosya_ara: hiçbir şey bulunamadı
    re.compile(r"^\[çıkış kodu: (?!0\])-?\d+\]"),  # terminal: sıfır olmayan çıkış kodu
)


def bilinenler(metin: str) -> str:
    """Mesajdaki kesin Windows yolları (en fazla 5)."""
    yollar: list[str] = []
    metin = metin or ""
    tirnakli = _YOL_TIRNAKLI.findall(metin)
    for y in tirnakli + _YOL.findall(_YOL_TIRNAKLI.sub(" ", metin)):
        y = y.rstrip(_KUYRUK_NOKTALAMA)
        if len(y) > 3 and y not in yollar:
            yollar.append(y)
    if not yollar:
        return ""
    return (
        "[Bilinenler — kullanıcı bu yolları kesin olarak verdi; doğrudan kullan, bunları ya da köklerini ARAMA]\n"
        + "\n".join(f"- {y}" for y in yollar[:5])
    )


def bos_mu(sonuc: str) -> bool:
    """Tool sonucu başarısız ya da boş mu? (Kullanıcının reddi / onay zaman aşımı sayılmaz: onlar onun kararı.)"""
    s = (sonuc or "").lstrip()
    if s.startswith("Kullanıcı"):
        return False
    return any(p.search(s) for p in _BOS)


def _anahtar(ad: str, argumanlar_json: str | None) -> str:
    try:
        arg = json.loads(argumanlar_json or "{}")
        norm = json.dumps(arg, sort_keys=True, ensure_ascii=False).lower()
    except ValueError:
        norm = (argumanlar_json or "").strip().lower()
    return f"{ad}|{norm}"


# Durumu değiştiren tool'lar: bunlardan biri BAŞARILI olunca önceki başarısız çağrılar tekrar denenebilir
# (ör. dosyayı düzelttikten sonra aynı 'python odev.py' komutunu yeniden çalıştırmak meşrudur).
DEGISTIREN = frozenset({
    "dosya_yaz", "dosya_sil", "dosya_kaydet", "terminal_calistir", "program_ac", "pencere_kontrol", "pencere_tasi",
    "onedrive_yukle", "onedrive_sil", "onedrive_tasi", "onedrive_klasor_olustur", "indir", "bilgisayar_kullan", "fare", "klavye_yaz",
    "tus_bas", "kaydir", "masaustu_olustur", "masaustu_kaldir", "gorev_dagit",
})
# Arama/listeleme: üst üste çok kez BOŞ dönerse gerçek bir arama spirali vardır.
ARAMA = frozenset({"dosya_ara", "dosya_listele", "onedrive_listele", "onedrive_ara", "webde_ara"})
ENGEL_DURAK = 3  # aynı başarısız çağrıyı hiçbir şey değiştirmeden 3 kez daha denemeye kalkarsa: kısırdöngü
ARAMA_DURAK = 6  # üst üste 6 boş arama


class Takip:
    """Bir turun tool geçmişi. ajan_turu ve işçi döngüsü her tool çağrısında kullanır.

    Sadece GERÇEK kısırdöngüde durdurur. Derleme/test hatası (sıfır olmayan çıkış kodu) normal iterasyondur:
    durak sebebi sayılmaz; düzeltip aynı komutu yeniden çalıştırmak engellenmez.
    """

    def __init__(self) -> None:
        self.basarisiz: dict[str, int] = {}  # değişiklik yapılmadan başarısız olmuş çağrılar
        self.engellenen: dict[str, int] = {}
        self.ardisik_bos_arama = 0
        self.durak_nedeni = ""

    def engelle(self, tool_call: Any) -> str | None:
        """Çalıştırmadan önce: aynı çağrı değişiklik yapılmadan zaten başarısız olduysa modele dönecek metin."""
        k = _anahtar(tool_call.function.name, tool_call.function.arguments)
        if self.basarisiz.get(k, 0) < 1:
            return None
        self.engellenen[k] = self.engellenen.get(k, 0) + 1
        if self.engellenen[k] >= ENGEL_DURAK and not self.durak_nedeni:
            self.durak_nedeni = "Aynı başarısız çağrıyı hiçbir şey değiştirmeden tekrar tekrar denedin."
        return (
            "HATA: Bu çağrı (aynı tool, aynı argümanlar) az önce başarısız oldu ve arada hiçbir şey değişmedi; aynen "
            "tekrar ÇALIŞTIRILMADI. Önce sebebini düzelt (hata mesajını oku; dosyayı düzelt, başka komut/yol/argüman "
            "dene, gerekirse webde_ara ile hatayı araştır), sonra tekrar çalıştır."
        )

    def kaydet(self, tool_call: Any, sonuc: str) -> None:
        ad = tool_call.function.name
        k = _anahtar(ad, tool_call.function.arguments)
        if bos_mu(sonuc):
            self.basarisiz[k] = self.basarisiz.get(k, 0) + 1
            if ad in ARAMA:
                self.ardisik_bos_arama += 1
                if self.ardisik_bos_arama >= ARAMA_DURAK and not self.durak_nedeni:
                    self.durak_nedeni = f"Üst üste {ARAMA_DURAK} arama boş döndü."
            return
        if ad in ARAMA:
            self.ardisik_bos_arama = 0
        if ad in DEGISTIREN:  # durum değişti: önceki başarısız çağrıları yeniden denemek artık anlamlı
            self.basarisiz.clear()
            self.engellenen.clear()

    def durmali(self) -> str:
        return self.durak_nedeni
