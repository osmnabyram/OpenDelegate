"""İş defteri: uzun işlerde "neredeyim" takibi.

Model şu anki adımı, ilgili dosyayı ve sıradaki adımı buraya kaydeder;
bağlantı kopsa ya da yeni oturum açılsa kaldığı yerden devam edebilir.
Aynı hafıza veritabanını kullanır (Neon Postgres / SQLite).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import hafiza


async def calistir(argumanlar: dict[str, Any]) -> tuple[bool, str]:
    eylem = str(argumanlar.get("eylem", "listele")).strip().lower()
    try:
        if eylem == "ekle":
            return True, await asyncio.to_thread(_ekle, argumanlar)
        if eylem == "guncelle":
            return True, await asyncio.to_thread(_guncelle, argumanlar)
        if eylem == "bitti":
            return True, await asyncio.to_thread(_bitti, argumanlar)
        if eylem == "listele":
            return True, await asyncio.to_thread(_listele)
        if eylem == "sil":
            return True, await asyncio.to_thread(_sil, argumanlar)
        return False, f"Bilinmeyen eylem: '{eylem}' (ekle / guncelle / bitti / listele / sil)"
    except Exception as e:  # noqa: BLE001
        return False, f"İş defteri hatası: {e}"


def _simdi() -> str:
    return hafiza._simdi()  # Türkiye saati (sunucu saati UTC)


def _ekle(argumanlar: dict[str, Any]) -> str:
    baslik = str(argumanlar.get("baslik", "")).strip()
    if not baslik:
        raise ValueError("'baslik' zorunlu.")
    dosya = str(argumanlar.get("dosya", "")).strip()
    adim = str(argumanlar.get("adim", "")).strip()
    is_id = uuid.uuid4().hex[:12]
    simdi = _simdi()
    hafiza._calistir(
        "INSERT INTO is_defteri (id, baslik, dosya, adim, durum, olusturma, guncelleme) "
        "VALUES (%s, %s, %s, %s, 'devam', %s, %s)",
        (is_id, baslik, dosya, adim, simdi, simdi),
    )
    return f"İş eklendi [{is_id}]: {baslik}"


def _guncelle(argumanlar: dict[str, Any]) -> str:
    is_id = str(argumanlar.get("id", "")).strip()
    if not is_id:
        raise ValueError("'id' zorunlu (is_defteri listele ile bakabilirsin).")
    mevcut = hafiza._calistir("SELECT id FROM is_defteri WHERE id=%s", (is_id,), sonuc="tek")
    if not mevcut:
        raise LookupError(f"[{is_id}] bulunamadı.")
    alanlar, degerler = [], []
    for alan in ("adim", "dosya", "baslik"):
        if alan in argumanlar:
            alanlar.append(f"{alan}=%s")
            degerler.append(str(argumanlar[alan]))
    if not alanlar:
        raise ValueError("Güncellenecek alan yok (adim / dosya / baslik).")
    simdi = _simdi()
    alanlar.append("guncelleme=%s")
    degerler.append(simdi)
    degerler.append(is_id)
    hafiza._calistir(
        f"UPDATE is_defteri SET {', '.join(alanlar)} WHERE id=%s",
        tuple(degerler),
    )
    return f"[{is_id}] güncellendi."


def _bitti(argumanlar: dict[str, Any]) -> str:
    is_id = str(argumanlar.get("id", "")).strip()
    if not is_id:
        raise ValueError("'id' zorunlu.")
    simdi = _simdi()
    n = hafiza._calistir(
        "UPDATE is_defteri SET durum='bitti', guncelleme=%s WHERE id=%s",
        (simdi, is_id), sonuc="sayi",
    )
    if not n:
        raise LookupError(f"[{is_id}] bulunamadı.")
    return f"[{is_id}] tamamlandı olarak işaretlendi."


def _listele() -> str:
    satirlar = hafiza._calistir(
        "SELECT id, baslik, dosya, adim, durum, guncelleme FROM is_defteri ORDER BY guncelleme DESC",
        sonuc="hepsi",
    ) or []
    if not satirlar:
        return "İş defteri boş."
    parcalar = []
    for s in satirlar:
        simge = "✅" if s["durum"] == "bitti" else "🔄"
        dosya_ek = f" | dosya: {s['dosya']}" if s["dosya"] else ""
        adim_ek = f"\n   Adım: {s['adim']}" if s["adim"] else ""
        parcalar.append(f"{simge} [{s['id']}] {s['baslik']}{dosya_ek}{adim_ek}")
    return "\n".join(parcalar)


def _sil(argumanlar: dict[str, Any]) -> str:
    is_id = str(argumanlar.get("id", "")).strip()
    if not is_id:
        raise ValueError("'id' zorunlu.")
    n = hafiza._calistir("DELETE FROM is_defteri WHERE id=%s", (is_id,), sonuc="sayi")
    if not n:
        raise LookupError(f"[{is_id}] bulunamadı.")
    return f"[{is_id}] silindi."
