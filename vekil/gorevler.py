"""PC ajanı için görev kuyruğu (bellekte, geçici).

Akış:
    Vekil (onaydan sonra) -> calistir() görevi kuyruğa ekler
    ajan.py -> GET /jobs/pending  -> bekleyenleri_al(): görev "alindi" olur
    ajan.py -> POST /jobs/result  -> sonuc_yaz(): görevi bekleyen coroutine uyanır

Kurallar:
- Her GET /jobs/pending bir "nabız"dır. Son nabız AJAN_CEVRIMICI_SN'den eskiyse
  ve elinde iş yoksa ajan çevrimdışı sayılır.
- Zaman aşımına uğrayan görev kuyruktan SİLİNİR; ajan sonradan bayat bir görevi
  (ör. onaylanmış bir silme) asla almaz.
- Render yeniden başlarsa kuyruk boşalır (bilerek geçici).
- Her görev onu açan sohbet turunu (SAHIP, contextvar) bilir; "dur" denince iptal_et() o turun
  henüz alınmamış görevlerini siler (ajan hiç görmez). Ajanın almış olduğu görev durdurulamaz
  (ajan değişmedi); sonucu gelirse yok sayılır.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import config

AJAN_CEVRIMDISI = (
    "HATA: PC ajanı çevrimdışı (PC kapalı ya da ajan.py çalışmıyor). Eylem ÇALIŞTIRILMADI. "
    "Önce bulutla çözmeyi dene: dosya ise onedrive_ara / onedrive_listele / onedrive_oku / onedrive_gonder "
    "('klasorler/...' = PC'deki desktop\\klasorler'in bulut aynası), bilgi ise webde_ara. PC'de yapılacak bir "
    "iş (dosya_yaz, program_ac, terminal_calistir) PC açılınca yapılmak üzere sıraya alınabilir. Bulutta "
    "karşılığı yoksa kullanıcıya dürüstçe PC'nin kapalı olduğunu söyle ve somut bir alternatif öner."
)

# Düğümler: "pc" = PC ajanı (ajan/ajan.py). Başka düğüm eklemek için DUGUMLER'e yeni ad ve secret ver.
# Her görev bir düğüme aittir; düğüm, ajanın yoklamada kullandığı secret'ten belli olur (main._ajan_dugumu).
DUGUMLER = ("pc",)


def _dugum(d: str | None) -> str:
    return d if d in DUGUMLER else "pc"


# Görevi açan sohbet turu (chat_id). main.py turu çalıştıran asyncio görevinde set eder; işçi vekiller
# (gather) bağlamı kopyaladığı için onlar da aynı sahibi taşır. Kuyruk işleyicisinde None.
SAHIP: contextvars.ContextVar[int | None] = contextvars.ContextVar("gorev_sahibi", default=None)


@dataclass
class Gorev:
    id: str
    tool: str
    argumanlar: dict[str, Any]
    onayli: bool  # kullanıcı Telegram'dan onayladı mı (ajan hassas işlerde buna bakar)
    dugum: str = "pc"  # "pc" (PC ajanı); sadece kendi düğümünün ajanı alır
    durum: str = "bekliyor"  # bekliyor | alindi | bitti
    olusturma: float = field(default_factory=time.monotonic)
    alinma: float | None = None
    sahip: int | None = field(default_factory=SAHIP.get)
    sonuc: asyncio.Future[tuple[bool, str, bytes | None]] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )


# Ajan tek: paralel vekillerin ve masaüstü yönetiminin işleri bu kilitle sırayla gider.
PC_KILIDI = asyncio.Lock()

_gorevler: dict[str, Gorev] = {}
_iptal_istenen: set[str] = set()  # ajanın şu an çalıştırdığı ama kullanıcının "dur" dediği görevler
BAGLANTI_KOPUK_SN = 120  # süre sınırı değil: görev sürerken ajandan bu kadar sn hiç nabız gelmezse bağlantı koptu
_dosyalar: dict[str, bytes] = {}  # indir -> PC: ajanın GET /jobs/file/{id} ile çekeceği içerik
_son_nabiz: dict[str, float] | None = {}  # düğüm -> son yoklama anı (monotonic). None'a atanırsa sıfırlanmış sayılır.
_yeni_is: dict[str, asyncio.Event] = {}  # düğüm -> uzun yoklamayı uyandıran olay (kuyruğa o düğümün görevi girdi)


def _nabizlar() -> dict[str, float]:
    """_son_nabiz'ı sözlük olarak döner. Testler/sıfırlama None'a atayabilir -> boş (çevrimdışı) say."""
    global _son_nabiz
    if not isinstance(_son_nabiz, dict):
        _son_nabiz = {}
    return _son_nabiz


def _olay(dugum: str) -> asyncio.Event:
    ev = _yeni_is.get(dugum)
    if ev is None:
        ev = _yeni_is[dugum] = asyncio.Event()
    return ev


UZUN_YOKLAMA_SINIR = 10.0  # sn; AJAN_CEVRIMICI_SN'den küçük kalmalı (bekleyen ajan çevrimdışı sayılmasın)


def nabiz(dugum: str = "pc") -> None:
    _nabizlar()[_dugum(dugum)] = time.monotonic()


def _mesgul(dugum: str) -> bool:
    """O düğümün ajanı şu an bir görevi çalıştırıyor mu? (uzun komutta yoklama gecikir)"""
    simdi = time.monotonic()
    return any(
        g.dugum == dugum and g.durum == "alindi" and g.alinma is not None
        and simdi - g.alinma < config.GOREV_SONUC_ZAMAN_ASIMI
        for g in _gorevler.values()
    )


def ajan_cevrimici(dugum: str = "pc") -> bool:
    dugum = _dugum(dugum)
    if _mesgul(dugum):
        return True
    son = _nabizlar().get(dugum)
    return son is not None and time.monotonic() - son < config.AJAN_CEVRIMICI_SN


def son_nabiz_sn(dugum: str = "pc") -> float | None:
    """O düğümün son yoklamasından bu yana geçen saniye (hiç gelmediyse None)."""
    son = _nabizlar().get(_dugum(dugum))
    return None if son is None else time.monotonic() - son


def bekleyenleri_al(limit: int = 5, dugum: str = "pc") -> list[dict[str, Any]]:
    """O düğümün ajanına verilecek görevleri döner ve 'alindi' olarak işaretler."""
    dugum = _dugum(dugum)
    nabiz(dugum)
    verilecek = [g for g in _gorevler.values() if g.durum == "bekliyor" and g.dugum == dugum][:limit]
    simdi = time.monotonic()
    for g in verilecek:
        g.durum = "alindi"
        g.alinma = simdi
    return [{"id": g.id, "tool": g.tool, "argumanlar": g.argumanlar, "onayli": g.onayli} for g in verilecek]


async def bekle_ve_al(sure: float, limit: int = 5, dugum: str = "pc") -> list[dict[str, Any]]:
    """Uzun yoklama: o düğümde bekleyen görev yoksa biri gelene kadar (en çok `sure` sn) bekler, sonra al.

    Ajan görevi 0.3-5 sn'lik yoklama aralığını beklemeden, kuyruğa girdiği an alır."""
    dugum = _dugum(dugum)
    nabiz(dugum)
    sure = max(0.0, min(float(sure), UZUN_YOKLAMA_SINIR, max(1.0, config.AJAN_CEVRIMICI_SN - 5)))
    ev = _olay(dugum)
    if sure and not any(g.durum == "bekliyor" and g.dugum == dugum for g in _gorevler.values()):
        ev.clear()  # kontrol ile clear arasında await yok: kaçan görev olmaz
        try:
            await asyncio.wait_for(ev.wait(), timeout=sure)
        except asyncio.TimeoutError:
            pass
    return bekleyenleri_al(limit, dugum)


def sonuc_yaz(gorev_id: str, basarili: bool, sonuc: str, resim: bytes | None = None) -> bool:
    """Ajandan gelen sonucu işler (resim: ekran görüntüsü, sadece bellekte). Görev yoksa/bayatsa False."""
    g = _gorevler.get(gorev_id)
    nabiz(g.dugum if g else "pc")
    if g is None or g.durum != "alindi" or g.sonuc.done():
        return False
    g.durum = "bitti"
    g.sonuc.set_result((basarili, sonuc, resim))
    return True


def iptal_et(sahip: int) -> tuple[list[str], list[str]]:
    """'dur': sahibin görevlerini iptal eder. (PC'ye gitmeden silinenler, ajanın şu an çalıştırdıkları)."""
    silinen, calisan = [], []
    for g in list(_gorevler.values()):
        if g.sahip != sahip or g.sonuc.done():
            continue
        ozet = _ozet(g)
        if g.durum == "bekliyor":
            _gorevler.pop(g.id, None)  # ajan bir sonraki yoklamada görmez
            g.sonuc.set_result((False, "İPTAL: Kullanıcı 'dur' dedi, görev PC'ye gönderilmeden iptal edildi.", None))
            silinen.append(ozet)
        else:
            calisan.append(ozet)
            _iptal_istenen.add(g.id)  # ajan bir sonraki nabızda öğrenir ve komutu kapatır
    return silinen, calisan


def _ozet(g: Gorev) -> str:
    a = g.argumanlar
    hedef = str(a.get("yol") or a.get("komut") or a.get("hedef") or a.get("klasor") or a.get("pencere") or "")
    return f"{g.tool} {hedef[:100]}".strip()


def dosya_al(dosya_id: str) -> bytes | None:
    """Ajanın indirmesi için bekleyen dosya içeriği (yoksa None)."""
    nabiz()
    return _dosyalar.get(dosya_id)


async def dosya_gonder(veri: bytes, ad: str, klasor: str, onayli: bool) -> tuple[bool, str]:
    """Render'da indirilmiş bir dosyayı PC'ye kaydettirir (ajan 'dosya_kaydet' görevi)."""
    dosya_id = uuid.uuid4().hex
    _dosyalar[dosya_id] = veri
    try:
        return await calistir(
            "dosya_kaydet", {"dosya_id": dosya_id, "klasor": klasor, "ad": ad, "boyut": len(veri)}, onayli=onayli
        )
    finally:
        _dosyalar.pop(dosya_id, None)  # iş bitince bellekten sil


async def calistir(tool: str, argumanlar: dict[str, Any], onayli: bool, dugum: str = "pc") -> tuple[bool, str]:
    """Görevi kuyruğa atar ve ajanın sonucunu bekler. Asla exception fırlatmaz.

    dugum: "pc" (PC ajanı). Sadece o düğümün ajanı görevi alır.

    Returns:
        (başarılı_mı, modele dönecek metin)
    """
    basarili, sonuc, _ = await calistir_ekli(tool, argumanlar, onayli, dugum)
    return basarili, sonuc


def _cevrimdisi_mesaji(dugum: str) -> str:
    return AJAN_CEVRIMDISI


async def calistir_ekli(tool: str, argumanlar: dict[str, Any], onayli: bool,
                        dugum: str = "pc") -> tuple[bool, str, bytes | None]:
    """calistir() ile aynı, ama ajanın gönderdiği ikili eki (ekran görüntüsü) de döner."""
    dugum = _dugum(dugum)
    if not config.AJAN_SECRET:
        return False, "HATA: AJAN_SECRET tanımlı değil, PC ajanı devre dışı. Kullanıcıya Render env'i kontrol etmesini söyle.", None
    if not ajan_cevrimici(dugum):
        return False, _cevrimdisi_mesaji(dugum), None

    g = Gorev(id=uuid.uuid4().hex, tool=tool, argumanlar=argumanlar, onayli=onayli, dugum=dugum)
    _gorevler[g.id] = g
    _olay(dugum).set()  # uzun yoklamada bekleyen ajan anında alsın
    nerede = "PC"
    try:
        baslangic = time.monotonic()
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(g.sonuc), timeout=1)
            except asyncio.TimeoutError:
                pass
            # 1 sn'de bir kontrol. SÜRE SINIRI YOK (Kullanıcı: uzun işler kesilmesin): ajan görev sürerken 5 sn'de bir
            # /jobs/devam ile nabız verir. Sadece BAĞLANTI KOPARSA (ajan öldü / makine kapandı) beklemeyi bırak.
            if g.durum == "bekliyor" and not ajan_cevrimici(dugum):
                return False, _cevrimdisi_mesaji(dugum), None
            if g.durum == "alindi" and (son_nabiz_sn(dugum) or 0) > BAGLANTI_KOPUK_SN:
                return False, (
                    f"HATA: {nerede} ile bağlantı koptu ({BAGLANTI_KOPUK_SN} sn'dir ses yok; makine kapanmış ya da "
                    "ajan durmuş olabilir). İş yarım kalmış ya da bitmiş OLABİLİR; kullanıcıya sade dille söyle."
                ), None
            if config.GOREV_SONUC_ZAMAN_ASIMI > 0 and time.monotonic() - baslangic > config.GOREV_SONUC_ZAMAN_ASIMI:
                return False, f"HATA: {nerede}'den sonuç belirlenen süre sınırında gelmedi; iş sürüyor OLABİLİR.", None
    finally:
        _gorevler.pop(g.id, None)  # bayat görev kuyrukta kalmasın
        _iptal_istenen.discard(g.id)


def devam(gorev_id: str) -> bool:
    """Ajan uzun bir görev sürerken çağırır (/jobs/devam): nabız + 'Kullanıcı dur dedi mi?'."""
    g = _gorevler.get(gorev_id)
    nabiz(g.dugum if g else "pc")
    return gorev_id in _iptal_istenen
