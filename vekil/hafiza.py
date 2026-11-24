"""Vekil hafızası: Postgres (Neon, kalıcı) ya da SQLite (lokal / yedek).

DATABASE_URL varsa Postgres kullanılır (Render'da: Neon, deploy'larda silinmez).
Yoksa SQLite (config.DB_YOLU); Render'da bu geçicidir, her deploy'da sıfırlanır.

Tablolar:
- mesajlar: kullanıcı ve asistan mesajları (açılışta son konuşma buradan geri yüklenir)
- eylemler: önerilen her tool çağrısı, onay durumu ve sonucu (denetim logu)
- ozetler:  geçmişten düşen konuşma parçalarının özetleri
- bilgiler: kalıcı hafıza — tercih / terim / karar / not (tür + anahtar tekil)
- ayarlar:  iç işaretler (seed sürümü, /sifirla noktası)
- vekiller: ordu kadrosu (rol -> görünen ad); açılışta bir kez okunur, bellekte durur
- bilgisayar_izin: ESKİ bilgisayar kullanma izin listesi (artık kullanılmıyor: bilgisayar kullanma tam
  otonom; tablo ve veri silinmedi)

Dayanıklılık: hafıza "en iyi çaba" ile çalışır. Veritabanı hatası (Neon uykuda,
ağ koptu, disk...) asla yukarı fırlatılmaz; uyarı loglanır, bot hafızasız devam eder.
Postgres bağlantısı koparsa bir kez yeniden bağlanıp tekrar denenir.

Tüm genel fonksiyonlar async'tir; asıl iş thread'de yapılır (event loop bloklanmaz).
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, TypeVar

import config

logger = logging.getLogger("vekil.hafiza")

T = TypeVar("T")

TURLER = ("tercih", "terim", "karar", "not")
MAKS_ANAHTAR = 80
MAKS_DEGER = 600
MAKS_BILGI_PROMPT = 80  # prompt'a en fazla kaç bilgi girer
MAKS_BILGI_KARAKTER = 5000

# İlk kurulumda bir kez eklenir (kullanıcı /unut ile silerse geri gelmez).
SEED = [
    (
        "terim",
        "pist",
        "Kullanıcının slang'i: dürtme / \"az bak\" anlamında; selamlaşmak ya da seni dürtüp çağırmak için "
        "kullanır. \"pist\" yazınca anlamını sorma, samimi bir şekilde karşılık ver (ör. \"buradayım efendim, ne yapıyoruz?\").",
    ),
]
SEED_SURUMU = "1"

# Sır gibi görünen değerler hafızaya yazılmaz.
_SIR = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|tvly-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}"
    r"|\d{8,10}:[A-Za-z0-9_-]{30,}|postgres(ql)?://\S+:\S+@|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|\b(şifre|sifre|parola|password|passwd)\b\s*[:=]\s*\S+)",
    re.I,
)


class HafizaHatasi(Exception):
    """Kullanıcıya gösterilecek doğrulama hatası (DB hatası değil)."""


# --------------------------------------------------------------------------
# Arka uç
# --------------------------------------------------------------------------

def postgres_mu() -> bool:
    return bool(config.DATABASE_URL)


def _ddl() -> list[str]:
    kimlik = "BIGSERIAL PRIMARY KEY" if postgres_mu() else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        f"""CREATE TABLE IF NOT EXISTS mesajlar (
            id {kimlik}, zaman TEXT NOT NULL, chat_id BIGINT NOT NULL,
            rol TEXT NOT NULL, icerik TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS mesajlar_chat ON mesajlar (chat_id, id)",
        f"""CREATE TABLE IF NOT EXISTS eylemler (
            id {kimlik}, zaman TEXT NOT NULL, chat_id BIGINT NOT NULL, tool TEXT NOT NULL,
            argumanlar TEXT NOT NULL, risk TEXT NOT NULL, durum TEXT NOT NULL,
            sonuc TEXT, guncellendi TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS ozetler (
            id {kimlik}, zaman TEXT NOT NULL, chat_id BIGINT NOT NULL, ozet TEXT NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS bilgiler (
            id {kimlik}, tur TEXT NOT NULL, anahtar TEXT NOT NULL, deger TEXT NOT NULL,
            olusturuldu TEXT NOT NULL, guncellendi TEXT NOT NULL, UNIQUE (tur, anahtar))""",
        "CREATE TABLE IF NOT EXISTS ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS bekleyen_gorevler (
            id {kimlik}, olusturuldu TEXT NOT NULL, guncellendi TEXT NOT NULL, chat_id BIGINT NOT NULL,
            tur TEXT NOT NULL, payload TEXT NOT NULL, durum TEXT NOT NULL, sonuc TEXT)""",
        "CREATE INDEX IF NOT EXISTS bekleyen_gorevler_durum ON bekleyen_gorevler (durum, id)",
        f"""CREATE TABLE IF NOT EXISTS izleme_kurallari (
            id {kimlik}, olusturuldu TEXT NOT NULL, chat_id BIGINT NOT NULL, yol TEXT NOT NULL,
            desen TEXT NOT NULL, derinlik INTEGER NOT NULL, aktif INTEGER NOT NULL)""",
        "CREATE TABLE IF NOT EXISTS vekiller (rol TEXT PRIMARY KEY, ad TEXT NOT NULL, guncellendi TEXT NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS is_defteri (
            id TEXT PRIMARY KEY, baslik TEXT NOT NULL, dosya TEXT NOT NULL DEFAULT '',
            adim TEXT NOT NULL DEFAULT '', durum TEXT NOT NULL DEFAULT 'devam',
            olusturma TEXT NOT NULL, guncelleme TEXT NOT NULL)""",
        f"""CREATE TABLE IF NOT EXISTS bilgisayar_izin (
            id {kimlik}, tur TEXT NOT NULL, kalip TEXT NOT NULL, olusturuldu TEXT NOT NULL, UNIQUE (tur, kalip))""",
    ]


_kilit = threading.Lock()
_pg: Any = None  # açık psycopg bağlantısı
_sqlite_hazir = False


def _hata_turleri() -> tuple[type[BaseException], ...]:
    turler: list[type[BaseException]] = [sqlite3.Error, OSError]
    if postgres_mu():
        import psycopg

        turler.append(psycopg.Error)
    return tuple(turler)


def _pg_baglan() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(
        config.DATABASE_URL,
        autocommit=True,
        connect_timeout=10,
        row_factory=dict_row,
        prepare_threshold=None,  # Neon pooler (PgBouncer) prepared statement desteklemez
    )
    for komut in _ddl():
        conn.execute(komut)
    return conn


DEVRE_SURESI = 30  # sn; bağlanamazsak bu süre DB'yi hiç denemeyiz (her mesaj beklemesin)
_devre_acik_bitis = 0.0


def _pg_kapat() -> None:
    global _pg
    try:
        if _pg is not None:
            _pg.close()
    except Exception:  # noqa: BLE001
        pass
    _pg = None


def _yeni_pg() -> Any:
    """Yeni bağlantı. Başarısızsa devre kesiciyi açar (DEVRE_SURESI boyunca hızlı hata)."""
    global _devre_acik_bitis
    import psycopg

    if time.monotonic() < _devre_acik_bitis:
        raise psycopg.OperationalError("hafıza devre kesici açık (az önce bağlanılamadı)")
    try:
        return _pg_baglan()
    except psycopg.Error:
        _devre_acik_bitis = time.monotonic() + DEVRE_SURESI
        raise


def _calistir(sql: str, params: tuple = (), *, sonuc: str = "yok") -> Any:
    """Tek SQL komutu. sonuc: 'yok' | 'hepsi' | 'tek' | 'sayi' (etkilenen satır)."""
    global _pg, _sqlite_hazir
    with _kilit:
        if postgres_mu():
            import psycopg

            try:
                if _pg is None or _pg.closed:
                    _pg = _yeni_pg()
                imlec = _pg.execute(sql, params)
            except psycopg.OperationalError:
                # Var olan bağlantı kopmuş olabilir (Neon uyudu / ağ): bir kez taze bağlantıyla dene.
                _pg_kapat()
                _pg = _yeni_pg()
                imlec = _pg.execute(sql, params)
        else:
            config.DB_YOLU.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(config.DB_YOLU, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                # Her bağlantıda: dosya silinmiş olsa da tablolar geri gelir (ucuz).
                for komut in _ddl():
                    conn.execute(komut)
                imlec = conn.execute(sql.replace("%s", "?"), params)
                if sonuc == "hepsi":
                    satirlar = [dict(s) for s in imlec.fetchall()]
                elif sonuc == "tek":
                    s = imlec.fetchone()
                    satirlar = dict(s) if s else None
                else:
                    satirlar = imlec.rowcount
                conn.commit()
                return satirlar if sonuc != "yok" else None
            finally:
                conn.close()
        if sonuc == "hepsi":
            return [dict(s) for s in imlec.fetchall()]
        if sonuc == "tek":
            s = imlec.fetchone()
            return dict(s) if s else None
        if sonuc == "sayi":
            return imlec.rowcount
        return None


def _sessiz(varsayilan: T) -> Callable[[Callable[..., T]], Callable[..., Any]]:
    """Sync işi thread'de çalıştırır; DB hatasını yutar, uyarı loglar, `varsayilan` döner."""

    def sarmala(fonksiyon: Callable[..., T]) -> Callable[..., Any]:
        @functools.wraps(fonksiyon)
        async def ic(*args: Any, **kwargs: Any) -> T:
            try:
                return await asyncio.to_thread(fonksiyon, *args, **kwargs)
            except HafizaHatasi:
                raise
            except _hata_turleri() as e:
                logger.warning("Hafıza işlemi atlandı (%s): %s", fonksiyon.__name__, type(e).__name__)
                return varsayilan

        return ic

    return sarmala


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Kurulum / sağlık
# --------------------------------------------------------------------------

@_sessiz(False)
def baslat() -> bool:
    """Tabloları kurar, seed'i (bir kez) ekler. Bağlanabildiyse True."""
    durum = _calistir("SELECT deger FROM ayarlar WHERE anahtar = %s", ("seed",), sonuc="tek")
    if not durum or durum["deger"] != SEED_SURUMU:
        for tur, anahtar, deger in SEED:
            _calistir(
                "INSERT INTO bilgiler (tur, anahtar, deger, olusturuldu, guncellendi) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (tur, anahtar) DO NOTHING",
                (tur, anahtar, deger, _simdi(), _simdi()),
            )
        _ayar_yaz("seed", SEED_SURUMU)
    _bilgi_onbellegi.clear()
    return True


@_sessiz(False)
def saglikli() -> bool:
    _calistir("SELECT 1 AS bir", sonuc="tek")
    return True


def tur_adi() -> str:
    return "Postgres (kalıcı)" if postgres_mu() else "SQLite (geçici, deploy'da silinir)"


def _ayar_yaz(anahtar: str, deger: str) -> None:
    _calistir(
        "INSERT INTO ayarlar (anahtar, deger) VALUES (%s, %s) ON CONFLICT (anahtar) DO UPDATE SET deger = excluded.deger",
        (anahtar, deger),
    )


# --------------------------------------------------------------------------
# Mesajlar
# --------------------------------------------------------------------------

@_sessiz(None)
def mesaj_kaydet(chat_id: int, rol: str, icerik: str) -> None:
    _calistir(
        "INSERT INTO mesajlar (zaman, chat_id, rol, icerik) VALUES (%s, %s, %s, %s)",
        (_simdi(), chat_id, rol, icerik),
    )


@_sessiz([])
def son_mesajlar(chat_id: int, limit: int) -> list[dict[str, str]]:
    """Son /sifirla'dan sonraki en fazla `limit` mesaj (eskiden yeniye), model formatında."""
    isaret = _calistir("SELECT deger FROM ayarlar WHERE anahtar = %s", (f"sifir:{chat_id}",), sonuc="tek")
    alt = int(isaret["deger"]) if isaret else 0
    satirlar = _calistir(
        "SELECT rol, icerik FROM mesajlar WHERE chat_id = %s AND id > %s AND rol IN ('user', 'assistant') "
        "ORDER BY id DESC LIMIT %s",
        (chat_id, alt, limit),
        sonuc="hepsi",
    )
    mesajlar = [{"role": s["rol"], "content": s["icerik"]} for s in reversed(satirlar)]
    while mesajlar and mesajlar[0]["role"] != "user":  # geçmiş her zaman kullanıcıyla başlar
        mesajlar.pop(0)
    return mesajlar


@_sessiz(None)
def sifirla(chat_id: int) -> None:
    """Açılışta geri yüklenecek konuşmayı bu noktadan sonrasıyla sınırlar (kayıtlar silinmez)."""
    s = _calistir("SELECT MAX(id) AS son FROM mesajlar WHERE chat_id = %s", (chat_id,), sonuc="tek")
    _ayar_yaz(f"sifir:{chat_id}", str((s or {}).get("son") or 0))


# --------------------------------------------------------------------------
# Eylemler (denetim logu)
# --------------------------------------------------------------------------

@_sessiz(-1)
def eylem_olustur(chat_id: int, tool: str, argumanlar: dict[str, Any], risk: str) -> int:
    """Yeni eylem önerisini 'bekliyor' olarak kaydeder, id'sini döner (hafıza yoksa -1)."""
    s = _calistir(
        "INSERT INTO eylemler (zaman, chat_id, tool, argumanlar, risk, durum) "
        "VALUES (%s, %s, %s, %s, %s, 'bekliyor') RETURNING id",
        (_simdi(), chat_id, tool, json.dumps(argumanlar, ensure_ascii=False), risk),
        sonuc="tek",
    )
    return int(s["id"]) if s else -1


@_sessiz(None)
def eylem_guncelle(eylem_id: int, durum: str, sonuc: str | None = None) -> None:
    if eylem_id < 0:  # kayıt hiç oluşturulamamıştı
        return
    _calistir(
        "UPDATE eylemler SET durum = %s, sonuc = COALESCE(%s, sonuc), guncellendi = %s WHERE id = %s",
        (durum, sonuc, _simdi(), eylem_id),
    )


@_sessiz([])
def son_eylemler(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    return _calistir(
        "SELECT id, zaman, tool, argumanlar, risk, durum FROM eylemler WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
        (chat_id, limit),
        sonuc="hepsi",
    )


@_sessiz([])
def eylemler_beri(chat_id: int, baslangic: str, limit: int = 2000) -> list[dict[str, Any]]:
    """Öz-değerlendirme için: `baslangic`tan (ISO) beri eylemler, eskiden yeniye (sonuç kısaltılmış)."""
    return _calistir(
        "SELECT zaman, tool, risk, durum, SUBSTR(COALESCE(sonuc, ''), 1, 160) AS sonuc FROM eylemler "
        "WHERE chat_id = %s AND zaman >= %s ORDER BY id LIMIT %s",
        (chat_id, baslangic, limit),
        sonuc="hepsi",
    )


@_sessiz([])
def mesajlar_beri(chat_id: int, baslangic: str, limit: int = 300) -> list[dict[str, Any]]:
    """Öz-değerlendirme için: `baslangic`tan beri sohbet (en yeni `limit` mesaj, eskiden yeniye)."""
    satirlar = _calistir(
        "SELECT zaman, rol, SUBSTR(icerik, 1, 400) AS icerik FROM mesajlar WHERE chat_id = %s AND zaman >= %s "
        "AND rol IN ('user', 'assistant') ORDER BY id DESC LIMIT %s",
        (chat_id, baslangic, limit),
        sonuc="hepsi",
    )
    return list(reversed(satirlar))


# --------------------------------------------------------------------------
# Özetler
# --------------------------------------------------------------------------

@_sessiz(None)
def ozet_kaydet(chat_id: int, ozet: str) -> None:
    _calistir("INSERT INTO ozetler (zaman, chat_id, ozet) VALUES (%s, %s, %s)", (_simdi(), chat_id, ozet))


@_sessiz([])
def son_ozetler(chat_id: int, limit: int = 3) -> list[dict[str, str]]:
    satirlar = _calistir(
        "SELECT zaman, ozet FROM ozetler WHERE chat_id = %s ORDER BY id DESC LIMIT %s",
        (chat_id, limit),
        sonuc="hepsi",
    )
    return list(reversed(satirlar))


# --------------------------------------------------------------------------
# Kalıcı bilgiler (tercih / terim / karar / not)
# --------------------------------------------------------------------------

_bilgi_onbellegi: dict[str, list[dict[str, str]]] = {}


def _dogrula(tur: str, anahtar: str, deger: str) -> tuple[str, str, str]:
    tur = (tur or "").strip().lower()
    anahtar = re.sub(r"\s+", " ", (anahtar or "")).strip()
    deger = (deger or "").strip()
    if tur not in TURLER:
        raise HafizaHatasi(f"tur şunlardan biri olmalı: {', '.join(TURLER)}")
    if not anahtar or not deger:
        raise HafizaHatasi("anahtar ve deger boş olamaz.")
    if len(anahtar) > MAKS_ANAHTAR or len(deger) > MAKS_DEGER:
        raise HafizaHatasi(f"Çok uzun (anahtar ≤ {MAKS_ANAHTAR}, deger ≤ {MAKS_DEGER} karakter). Kısalt.")
    if _SIR.search(anahtar) or _SIR.search(deger):
        raise HafizaHatasi("Bu bir şifre/key/token gibi görünüyor; sırları hafızaya yazmam.")
    return tur, anahtar, deger


@_sessiz(False)
def bilgi_yaz(tur: str, anahtar: str, deger: str) -> bool:
    """Ekler ya da aynı tür+anahtar varsa günceller. Doğrulama hatasında HafizaHatasi."""
    tur, anahtar, deger = _dogrula(tur, anahtar, deger)
    _calistir(
        "INSERT INTO bilgiler (tur, anahtar, deger, olusturuldu, guncellendi) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (tur, anahtar) DO UPDATE SET deger = excluded.deger, guncellendi = excluded.guncellendi",
        (tur, anahtar, deger, _simdi(), _simdi()),
    )
    _bilgi_onbellegi.clear()
    return True


@_sessiz(None)
def _bilgileri_oku() -> list[dict[str, str]]:
    return _calistir(
        "SELECT tur, anahtar, deger, guncellendi FROM bilgiler ORDER BY guncellendi DESC, id DESC",
        sonuc="hepsi",
    )


async def bilgiler() -> list[dict[str, str]]:
    """Tüm kalıcı bilgiler (en yeni önce). Yazmaya kadar bellekte tutulur."""
    if "hepsi" not in _bilgi_onbellegi:
        satirlar = await _bilgileri_oku()
        if satirlar is None:  # DB'ye ulaşılamadı: önbelleğe alma, sonra tekrar dene
            return []
        _bilgi_onbellegi["hepsi"] = satirlar
    return _bilgi_onbellegi["hepsi"]


def onbellegi_bosalt() -> None:
    """Bilgi önbelleğini boşaltır: bir sonraki bilgiler() DB'den okur (zihin haritasının 'yenile'si, sınırlı)."""
    _bilgi_onbellegi.clear()


@_sessiz(0)
def bilgi_sil(anahtar: str) -> int:
    """/unut komutu ve modelin hafizadan_sil tool'u (🟡, bilgi satırıyla) çağırır. Silinen satır sayısı."""
    sayi = _calistir("DELETE FROM bilgiler WHERE LOWER(anahtar) = LOWER(%s)", (anahtar.strip(),), sonuc="sayi")
    _bilgi_onbellegi.clear()
    return int(sayi or 0)


async def prompt_blogu() -> str:
    """Sistem prompt'una eklenecek 'Kullanıcı hakkında bildiklerin' bloğu."""
    kayitlar = (await bilgiler())[:MAKS_BILGI_PROMPT]
    if not kayitlar:
        return ""
    satirlar, toplam = [], 0
    for k in sorted(kayitlar, key=lambda k: (TURLER.index(k["tur"]) if k["tur"] in TURLER else 9, k["anahtar"])):
        satir = f"- [{k['tur']}] {k['anahtar']}: {k['deger']}"
        toplam += len(satir)
        if toplam > MAKS_BILGI_KARAKTER:
            break
        satirlar.append(satir)
    return "[Kalıcı hafıza — kullanıcı hakkında bildiklerin. Bunları tekrar sorma.]\n" + "\n".join(satirlar)


# --------------------------------------------------------------------------
# Görev kuyruğu (PC kapalıyken onaylanıp sıraya alınan işler)
# durum: bekliyor -> isleniyor -> bitti | hata ; ya da iptal | suresi_doldu
# --------------------------------------------------------------------------

@_sessiz(-1)
def kuyruga_ekle(chat_id: int, tur: str, payload: dict[str, Any]) -> int:
    s = _calistir(
        "INSERT INTO bekleyen_gorevler (olusturuldu, guncellendi, chat_id, tur, payload, durum) "
        "VALUES (%s, %s, %s, %s, %s, 'bekliyor') RETURNING id",
        (_simdi(), _simdi(), chat_id, tur, json.dumps(payload, ensure_ascii=False)),
        sonuc="tek",
    )
    return int(s["id"]) if s else -1


@_sessiz(None)
def kuyruktan_al() -> dict[str, Any] | None:
    """En eski bekleyen işi 'isleniyor' yapıp döner (yoksa None). Tek işleyici varsayılır."""
    for _ in range(3):
        g = _calistir(
            "SELECT id, olusturuldu, chat_id, tur, payload FROM bekleyen_gorevler WHERE durum = 'bekliyor' "
            "ORDER BY id LIMIT 1",
            sonuc="tek",
        )
        if g is None:
            return None
        alindi = _calistir(
            "UPDATE bekleyen_gorevler SET durum = 'isleniyor', guncellendi = %s WHERE id = %s AND durum = 'bekliyor'",
            (_simdi(), g["id"]),
            sonuc="sayi",
        )
        if alindi == 1:
            return g
    return None


@_sessiz(None)
def kuyruk_bitir(gorev_id: int, durum: str, sonuc: str) -> None:
    _calistir(
        "UPDATE bekleyen_gorevler SET durum = %s, sonuc = %s, guncellendi = %s WHERE id = %s",
        (durum, sonuc[:4000], _simdi(), gorev_id),
    )


@_sessiz(None)
def kuyruk_geri_al(gorev_id: int) -> None:
    """İş PC'ye hiç ulaşmadıysa (ajan tam o an kapandı) tekrar sıraya koyar."""
    _calistir(
        "UPDATE bekleyen_gorevler SET durum = 'bekliyor', guncellendi = %s WHERE id = %s AND durum = 'isleniyor'",
        (_simdi(), gorev_id),
    )


@_sessiz(False)
def kuyruk_iptal(gorev_id: int) -> bool:
    sayi = _calistir(
        "UPDATE bekleyen_gorevler SET durum = 'iptal', guncellendi = %s WHERE id = %s AND durum = 'bekliyor'",
        (_simdi(), gorev_id),
        sonuc="sayi",
    )
    return sayi == 1


@_sessiz([])
def kuyruk_bayatlari_isaretle(saat: int) -> list[dict[str, Any]]:
    """`saat`ten uzun bekleyen işleri çalıştırmadan 'suresi_doldu' yapar ve döner (bayat onay çalışmasın)."""
    sinir = (datetime.now() - timedelta(hours=saat)).isoformat(timespec="seconds")
    satirlar = _calistir(
        "SELECT id, olusturuldu, chat_id, tur, payload FROM bekleyen_gorevler WHERE durum = 'bekliyor' "
        "AND olusturuldu < %s ORDER BY id",
        (sinir,),
        sonuc="hepsi",
    )
    for g in satirlar:
        _calistir(
            "UPDATE bekleyen_gorevler SET durum = 'suresi_doldu', guncellendi = %s WHERE id = %s AND durum = 'bekliyor'",
            (_simdi(), g["id"]),
        )
    return satirlar


@_sessiz([])
def kuyruk_yarim_kalanlar() -> list[dict[str, Any]]:
    """Açılışta: 'isleniyor'da kalan işler (Vekil iş sürerken yeniden başladı). Tekrar ÇALIŞTIRILMAZ."""
    satirlar = _calistir(
        "SELECT id, olusturuldu, chat_id, tur, payload FROM bekleyen_gorevler WHERE durum = 'isleniyor' ORDER BY id",
        sonuc="hepsi",
    )
    for g in satirlar:
        kuyruk_bitir.__wrapped__(g["id"], "hata", "Vekil iş sürerken yeniden başladı; PC'de çalışmış olabilir.")
    return satirlar


@_sessiz([])
def kuyruk_listele(limit: int = 15, sadece_bekleyen: bool = False) -> list[dict[str, Any]]:
    filtre = "WHERE durum = 'bekliyor' " if sadece_bekleyen else ""
    return _calistir(
        f"SELECT id, olusturuldu, guncellendi, chat_id, tur, payload, durum, sonuc FROM bekleyen_gorevler {filtre}"
        "ORDER BY id DESC LIMIT %s",
        (limit,),
        sonuc="hepsi",
    )


# --------------------------------------------------------------------------
# Dosya izleme kuralları (ajan PC'de tarar; kurallar burada kalıcı durur)
# --------------------------------------------------------------------------

@_sessiz(-1)
def izleme_ekle(chat_id: int, yol: str, desen: str = "*", derinlik: int = 2) -> int:
    var = _calistir(
        "SELECT id FROM izleme_kurallari WHERE aktif = 1 AND LOWER(yol) = LOWER(%s) AND desen = %s",
        (yol, desen),
        sonuc="tek",
    )
    if var:
        return int(var["id"])  # aynı kural zaten var: tekrar ekleme
    s = _calistir(
        "INSERT INTO izleme_kurallari (olusturuldu, chat_id, yol, desen, derinlik, aktif) "
        "VALUES (%s, %s, %s, %s, %s, 1) RETURNING id",
        (_simdi(), chat_id, yol, desen, derinlik),
        sonuc="tek",
    )
    return int(s["id"]) if s else -1


@_sessiz(None)
def izleme_listele() -> list[dict[str, Any]] | None:
    """Aktif kurallar; DB'ye ulaşılamazsa None (önbellek eskisini korusun diye)."""
    return _calistir(
        "SELECT id, olusturuldu, chat_id, yol, desen, derinlik FROM izleme_kurallari WHERE aktif = 1 ORDER BY id",
        sonuc="hepsi",
    )


@_sessiz(False)
def izleme_kaldir(kural_id: int) -> bool:
    sayi = _calistir("UPDATE izleme_kurallari SET aktif = 0 WHERE id = %s AND aktif = 1", (kural_id,), sonuc="sayi")
    return sayi == 1


# --------------------------------------------------------------------------
# Vekil kadrosu (ordu.py bellekte tutar; DB'ye sadece açılışta ve ad değişince gidilir)
# --------------------------------------------------------------------------

@_sessiz(None)
def vekiller_yukle(varsayilanlar: dict[str, str]) -> dict[str, str] | None:
    """Eksik rolleri varsayılan adla ekler, rol -> ad döner. DB'ye ulaşılamazsa None."""
    for rol, ad in varsayilanlar.items():
        _calistir(
            "INSERT INTO vekiller (rol, ad, guncellendi) VALUES (%s, %s, %s) ON CONFLICT (rol) DO NOTHING",
            (rol, ad, _simdi()),
        )
    satirlar = _calistir("SELECT rol, ad FROM vekiller", sonuc="hepsi")
    return {s["rol"]: s["ad"] for s in satirlar if s["rol"] in varsayilanlar}


@_sessiz(False)
def vekil_adlandir(adlar: dict[str, str]) -> bool:
    for rol, ad in adlar.items():
        _calistir("UPDATE vekiller SET ad = %s, guncellendi = %s WHERE rol = %s", (ad, _simdi(), rol))
    return True

