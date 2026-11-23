"""Sanal masaüstü çalışma alanları (Sprint 5 / A2) — Render tarafı.

Ordu çalışırken pencere açabilen her vekil (program_ac yetkisi olan: Kodcu) kendi Windows sanal
masaüstünde çalışır: "Vekil - <ad>". Kullanıcı Win+Tab ile gezip izler. Web-only vekiller (Araştırmacı,
Planlayıcı) masaüstü almaz.

Kurallar:
- Vekiller kendiliğinden ASLA kullanıcının masaüstlerine (ilki dahil) gitmez: işçinin program_ac'i her zaman
  kendi "Vekil - " masaüstüne yönlendirilir. Başvekil kullanıcının bir masaüstünü ("3") ancak kullanıcı o turda
  açıkça masaüstü dediyse hedefleyebilir.
- Destek ajan üzerinden yoklanır (masaustu_durum) ve önbelleğe alınır; ajan yeniden bağlanınca sıfırlanır.
  Desteklenmiyorsa iş masaüstüsüz sürer, kullanıcıya bir kez dürüstçe söylenir.
- Temizlik (iş bitince, "dur" dahil, arka planda): boş vekil masaüstleri hemen silinir. İçinde pencere
  kalanlar için "🧹 Kapat ve temizle / 📌 Kalsın" butonu gelir; cevap yoksa KALIR (Windows silinen masaüstünün
  pencerelerini kullanıcının masaüstüne taşırdı). Kapat = normal kapatma (WM_CLOSE), zorla değil.
"""

from __future__ import annotations

import asyncio
import contextvars
import html
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

import gorevler

logger = logging.getLogger("vekil.masaustu")

ONEK = "Vekil - "
DURUM_OMRU = 600  # sn; destek bilgisi bu kadar önbellekte kalır (ajan yeniden bağlanınca da sıfırlanır)
_durum: dict[str, Any] = {"destek": None, "neden": "", "zaman": 0.0}
_bekleyen_temizlik: dict[str, tuple[int, list[str]]] = {}  # buton jetonu -> (chat_id, masaüstü adları)
_arka: set[asyncio.Task[Any]] = set()


@dataclass
class Oturum:
    masaustleri: dict[str, str] = field(default_factory=dict)  # işçi adı -> "Vekil - <ad>"
    olusturulan: list[str] = field(default_factory=list)  # bu oturumda açılan (temizlenecek) masaüstleri


OTURUM: contextvars.ContextVar[Oturum | None] = contextvars.ContextVar("masaustu_oturumu", default=None)


def ad_yap(isci_adi: str) -> str:
    return (ONEK + re.sub(r"[\x00-\x1f]", "", isci_adi).strip())[:60]


def sifirla() -> None:
    """Ajan yeniden bağlandı (ajan.py / DLL değişmiş olabilir): desteği tekrar yokla."""
    _durum.update(destek=None, neden="", zaman=0.0)


async def _ajan(tur: str, arg: dict[str, Any], yetkili: bool = True) -> tuple[bool, str]:
    async with gorevler.PC_KILIDI:
        return await gorevler.calistir(tur, arg, onayli=yetkili)


def _json(metin: str) -> dict[str, Any] | None:
    try:
        v = json.loads(metin)
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


async def durum() -> dict[str, Any]:
    """Ajandan taze durum: {'destek': bool, 'neden'?, 'sayi'?, 'aktif'?, 'adlar'?}."""
    if not gorevler.ajan_cevrimici():
        return {"destek": False, "neden": "PC ajanı çevrimdışı"}
    basarili, sonuc = await _ajan("masaustu_durum", {}, yetkili=False)
    v = _json(sonuc) if basarili else None
    if v is None:  # eski ajan (görevi tanımıyor) ya da ajan hatası
        return {"destek": False, "neden": sonuc.removeprefix("HATA: ")[:200] if not basarili else "ajan cevabı okunamadı"}
    _durum.update(destek=bool(v.get("destek")), neden=str(v.get("neden") or ""), zaman=time.monotonic())
    return v


async def destek() -> tuple[bool, str]:
    if _durum["destek"] is None or time.monotonic() - _durum["zaman"] > DURUM_OMRU:
        v = await durum()
        if not v.get("destek"):
            _durum.update(destek=False, neden=str(v.get("neden") or "bilinmiyor"), zaman=time.monotonic())
    return bool(_durum["destek"]), str(_durum["neden"])


async def oturum_ac(bot: Bot, chat_id: int, isci_adlari: list[str]) -> Oturum:
    """Ordu başında: PC vekilleri için masaüstleri. Hata olursa iş masaüstüsüz sürer (boş oturum)."""
    oturum = Oturum()
    var, neden = await destek()
    if not var:
        await _gonder(bot, chat_id, f"⚠️ Sanal masaüstü kullanılamıyor ({neden}); vekiller senin masaüstünde çalışacak.")
        return oturum
    olmayan = []
    for isci in isci_adlari:
        hedef = ad_yap(isci)
        basarili, sonuc = await _ajan("masaustu_olustur", {"ad": hedef})
        v = _json(sonuc) if basarili else None
        if v is None:
            olmayan.append(f"{isci} ({sonuc.removeprefix('HATA: ')[:120]})")
            continue
        oturum.masaustleri[isci] = hedef
        oturum.olusturulan.append(hedef)  # önceden kalmış olsa da (vardi) bu iş bitince temizlenmeye aday
    if oturum.masaustleri:
        adlar = ", ".join(oturum.masaustleri.values())
        n = len(oturum.masaustleri)
        kim = f"{n} vekil kendi masaüstünde çalışıyor" if n > 1 else f"{next(iter(oturum.masaustleri))} kendi masaüstünde çalışıyor"
        await _gonder(bot, chat_id, f"🖥 {kim}: {adlar}. Win+Tab ile izleyebilirsin.")
    if olmayan:
        await _gonder(bot, chat_id, "⚠️ Masaüstü açılamadı, bu vekiller senin masaüstünde çalışacak: " + "; ".join(olmayan))
    return oturum


def hedef_ayarla(ad: str, argumanlar: dict[str, Any], vekil: str | None, son_kullanici_mesaji: str) -> str | None:
    """program_ac / pencere_tasi için masaüstü hedefini düzenler. Reddedilecekse modele dönecek HATA metni."""
    if ad not in ("program_ac", "pencere_tasi"):
        return None
    if vekil is not None:
        # İşçi: pencere her zaman KENDİ masaüstüne; kullanıcının masaüstlerini hedefleyemez.
        oturum = OTURUM.get()
        hedef = oturum.masaustleri.get(vekil) if oturum else None
        if hedef:
            argumanlar["masaustu"] = hedef
        else:
            argumanlar.pop("masaustu", None)
        return None
    m = str(argumanlar.get("masaustu") or "").strip()
    if not m:
        if ad == "pencere_tasi":
            return "HATA: pencere_tasi için hedef masaüstü (masaustu) şart."
        argumanlar.pop("masaustu", None)
        return None
    sayi = re.fullmatch(r"#?\s*(\d{1,2})\s*\.?\s*(masa[uü]st[uü])?", m, re.I)
    if sayi:
        m = sayi.group(1)
    argumanlar["masaustu"] = m
    if m.startswith(ONEK):
        return None
    sade = (son_kullanici_mesaji or "").lower().replace("ü", "u")
    if not any(k in sade for k in ("masaust", "desktop")):
        return (
            "HATA: Kullanıcı bu mesajda masaüstü belirtmedi; onun masaüstlerine kendiliğinden pencere açamaz/taşıyamazsın. "
            "masaustu vermeden tekrar çağır (bulunduğu masaüstünde açılır) ya da hangi masaüstü olduğunu sor."
        )
    if not m.isdigit():
        return "HATA: Kullanıcının masaüstünü Win+Tab sırasıyla numara olarak ver (ilki '1')."
    return None


def listele_metni(v: dict[str, Any]) -> tuple[bool, str]:
    if not v.get("destek"):
        return False, f"HATA: Sanal masaüstü kullanılamıyor: {v.get('neden') or 'bilinmiyor'}"
    satirlar = []
    for i, ad in enumerate(v.get("adlar") or []):
        notlar = [n for n, kosul in (("şu an buradasın", i == v.get("aktif")), ("vekil", str(ad).startswith(ONEK))) if kosul]
        satirlar.append(f"{i + 1}. {ad}" + (f" ({', '.join(notlar)})" if notlar else ""))
    return True, f"[{v.get('sayi')} sanal masaüstü; numara = Win+Tab sırası]\n" + "\n".join(satirlar)


async def listele() -> tuple[bool, str]:
    return listele_metni(await durum())


# --------------------------------------------------------------------------
# Temizlik
# --------------------------------------------------------------------------

async def kaldir(adlar: list[str], kapat: bool) -> tuple[list[str], list[tuple[str, list[str]]], list[str]]:
    """(silinenler, [(pencere kalan masaüstü, pencereler)], hata verenler)."""
    silinen, dolu, hatali = [], [], []
    for ad in adlar:
        basarili, sonuc = await _ajan("masaustu_kaldir", {"ad": ad, "kapat": kapat})
        v = _json(sonuc) if basarili else None
        if v is None:
            if "tek bir masaüstü yok" in sonuc:
                silinen.append(ad)  # Kullanıcı elle kapatmış: zaten yok
            else:
                hatali.append(f"{ad} ({sonuc.removeprefix('HATA: ')[:120]})")
        elif v.get("kaldirildi"):
            silinen.append(ad)
        else:
            dolu.append((ad, list(v.get("kalan") or [])))
    return silinen, dolu, hatali


def arka_planda_kapat(bot: Bot, chat_id: int, oturum: Oturum) -> None:
    """Ordu bitti ("dur" dahil): temizliği turdan bağımsız başlatır (tur iptal edilse de çalışır).

    Taze bağlam: "dur"un tur görevlerini silen iptal_et'i bu işe dokunmasın (SAHIP yok).
    """
    if not oturum.olusturulan:
        return
    gorev = asyncio.get_running_loop().create_task(_kapat(bot, chat_id, list(oturum.olusturulan)),
                                                   context=contextvars.Context())
    _arka.add(gorev)
    gorev.add_done_callback(_arka.discard)


async def _kapat(bot: Bot, chat_id: int, adlar: list[str]) -> None:
    try:
        if not gorevler.ajan_cevrimici():
            await _gonder(bot, chat_id, "🖥 PC'ye ulaşamadım, vekil masaüstleri duruyor olabilir. Sonra: /masaustu temizle")
            return
        _, dolu, hatali = await kaldir(adlar, kapat=False)
        if hatali:
            await _gonder(bot, chat_id, "⚠️ Bazı vekil masaüstlerini temizleyemedim: " + "; ".join(hatali))
        if dolu:
            await temizlik_sor(bot, chat_id, dolu)
    except Exception:  # noqa: BLE001 - temizlik hatası işi bozmasın
        logger.exception("Masaüstü temizliği patladı")


async def temizlik_sor(bot: Bot, chat_id: int, dolu: list[tuple[str, list[str]]]) -> None:
    jeton = uuid.uuid4().hex[:12]
    _bekleyen_temizlik[jeton] = (chat_id, [ad for ad, _ in dolu])
    while len(_bekleyen_temizlik) > 20:  # eski butonlar birikmesin
        _bekleyen_temizlik.pop(next(iter(_bekleyen_temizlik)))
    satirlar = []
    for ad, pencereler in dolu:
        ozet = ", ".join(html.escape(p) for p in pencereler[:4]) + (" ..." if len(pencereler) > 4 else "")
        satirlar.append(f"• <b>{html.escape(ad)}</b>: {len(pencereler)} pencere ({ozet})")
    klavye = InlineKeyboardMarkup([[
        InlineKeyboardButton("🧹 Kapat ve temizle", callback_data=f"masaustu:{jeton}:temizle"),
        InlineKeyboardButton("📌 Kalsın", callback_data=f"masaustu:{jeton}:kalsin"),
    ]])
    await bot.send_message(
        chat_id,
        "🖥 İş bitti. Bu vekil masaüstlerinde pencere açık kaldı:\n" + "\n".join(satirlar)
        + "\n\nKapatayım mı? Cevap vermezsen kalır (sonra: /masaustu temizle).",
        parse_mode=ParseMode.HTML, reply_markup=klavye,
    )


async def buton(jeton: str, secim: str) -> str | None:
    """Temizlik butonu. Mesaja eklenecek sonuç metni (geçersizse None)."""
    kayit = _bekleyen_temizlik.pop(jeton, None)
    if kayit is None:
        return None
    if secim != "temizle":
        return "📌 Kalıyor. Sonra kapatmak için: /masaustu temizle"
    return await temizle_metni(kayit[1])


async def temizle_metni(adlar: list[str]) -> str:
    if not adlar:
        return "Temizlenecek vekil masaüstü yok."
    if not gorevler.ajan_cevrimici():
        return "⚠️ PC ajanı çevrimdışı, şu an temizleyemiyorum."
    silinen, dolu, hatali = await kaldir(adlar, kapat=True)
    parcalar = []
    if silinen:
        parcalar.append("🧹 Temizlendi: " + ", ".join(silinen))
    for ad, pencereler in dolu:
        parcalar.append(
            f"⚠️ {ad} kapanmadı (kaydedilmemiş iş soruyor olabilir), masaüstü duruyor: " + ", ".join(pencereler[:4])
        )
    if hatali:
        parcalar.append("⚠️ Temizlenemedi: " + "; ".join(hatali))
    return "\n".join(parcalar)


async def tum_vekil_masaustleri() -> tuple[list[str] | None, str]:
    v = await durum()
    if not v.get("destek"):
        return None, str(v.get("neden") or "bilinmiyor")
    return [a for a in (v.get("adlar") or []) if str(a).startswith(ONEK)], ""


async def _gonder(bot: Bot, chat_id: int, metin: str) -> None:
    try:
        await bot.send_message(chat_id, metin)
    except Exception as e:  # noqa: BLE001
        logger.warning("Masaüstü bildirimi gönderilemedi: %s", type(e).__name__)
