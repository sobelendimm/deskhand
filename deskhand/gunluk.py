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
    izinleri_duzelt()
    simdi = time.time()
    for kok, sure in _sakla_sn().items():
        for d, alt, dosyalar in os.walk(kok):
            if kok == yollar.state_dir():
                alt[:] = [a for a in alt if a != "gorevler"]  # görev geçmişini gorev.py kırpar (son 50), süre değil
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


def ozel_dizin(d: str) -> None:
    """Dizini 0700 oluşturur; varsa ve grup/diğerlerine açıksa 0700'e çeker (yalnız bizimse)."""
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.stat(d)
    if st.st_mode & 0o077 and st.st_uid == os.getuid():
        os.chmod(d, 0o700)


def izinleri_duzelt() -> None:
    """Günlük ve önbellek gizli kalsın: STATE_DIR ve CACHE_DIR 0700, günlük dosyaları 0600 (eski sürümler 0755/0644
    oluşturuyordu: girdi günlüğü yazılan metinlerin parçalarını, önbellek ekran görüntülerini içerir). Yoksa 0700
    oluşturulur. Açılışta (temizle) ve sürecin ilk günlük satırında bir kez çalışır."""
    for d in (yollar.state_dir(), yollar.cache_dir()):
        try:  # yoksa burada 0700 oluşur: sonra başka yerdeki makedirs(exist_ok) izni değiştirmez
            ozel_dizin(d)
        except OSError:
            pass
    try:
        with os.scandir(yollar.gunluk_dizin()) as it:
            for g in it:
                if g.name.startswith("gunluk-") and g.is_file(follow_symlinks=False):
                    st = g.stat(follow_symlinks=False)
                    if st.st_mode & 0o077 and st.st_uid == os.getuid():
                        os.chmod(g.path, 0o600)
    except OSError:
        pass


_IZIN_TAMAM = False


def gunluk(satir):
    global _IZIN_TAMAM
    try:
        if not _IZIN_TAMAM:
            _IZIN_TAMAM = True
            izinleri_duzelt()
        d = yollar.gunluk_dizin()
        ozel_dizin(d)
        fd = os.open(os.path.join(d, time.strftime("gunluk-%Y%m%d.log")),
                     os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
        with open(fd, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {satir}\n")
    except OSError:
        pass
