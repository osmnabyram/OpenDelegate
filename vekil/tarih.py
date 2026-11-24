"""Tarih biçimi: 'Salı (17 Kasım)' (gün adı + parantezde tarih; '17.11' saat sanılmasın)."""

from __future__ import annotations

from datetime import date

GUN_ADI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AY_ADI = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def gun_yaz(d: date) -> str:
    return f"{GUN_ADI[d.weekday()]} ({d.day} {AY_ADI[d.month - 1]})"
