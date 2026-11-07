"""Girdi günlüğü (her girdi ve her DUR, STATE_DIR/gunluk-YYYYAAGG.log) ve eski dosya temizliği."""
from __future__ import annotations

import os
import time

from . import yollar

SAKLA_GUN = {"cikti": 5, "gunluk": 7}  # görüntüler/OCR önbelleği 5 gün, günlükler 7 gün


def _sakla_sn():
    return {yollar.cikti(): SAKLA_GUN["cikti"] * 86400, yollar.gunluk_dizin(): SAKLA_GUN["gunluk"] * 86400}


def temizle():
    """Eski ekran görüntüleri/OCR önbelleği (5 gün) ve günlükler (7 gün). tmpfiles günde bir çalışır;
    bu, süreyi kesinleştirir. Ölçüm: ~1 ms."""
    simdi = time.time()
    for kok, sure in _sakla_sn().items():
        for d, _, dosyalar in os.walk(kok):
            for f in dosyalar:
                yol = os.path.join(d, f)
                try:
                    if simdi - os.lstat(yol).st_mtime > sure:
                        os.remove(yol)
                except OSError:
                    pass
    _kirp(os.path.join(yollar.state_dir(), "bildirimler.jsonl"))


def _kirp(yol, azami=2 * 1024 * 1024, kalan=1024 * 1024):
    """Tek dosyada büyüyen kayıtlar (sanal masaüstü bildirimleri): azami boyutu aşınca son `kalan` baytı tut
    (satır başından)."""
    try:
        if os.path.getsize(yol) <= azami:
            return
        with open(yol, "rb") as f:
            f.seek(-kalan, os.SEEK_END)
            veri = f.read()
        veri = veri[veri.find(b"\n") + 1:]
        gecici = yol + ".kirp"
        with open(gecici, "wb") as f:
            f.write(veri)
        os.replace(gecici, yol)
    except OSError:
        pass


def gunluk(satir):
    try:
        d = yollar.gunluk_dizin()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, time.strftime("gunluk-%Y%m%d.log")), "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {satir}\n")
    except OSError:
        pass
