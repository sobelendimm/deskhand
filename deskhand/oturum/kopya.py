"""Ortak kopyalama altyapısı: tutarlı SQLite yedeği (kilitli DB dahil), dizin kopyalama + dışlama,
0700 kopya dizini oluşturma, oturum sonu temizlik.

Tek yönlü: kaynak dosyalar YALNIZ okunur, hiç yazılmaz. Kopya RUNTIME_DIR/oturum/<uygulama>-<zaman>/ altında,
0700. Kopyada SQLite tutarlılığı (docs/SESSIONS.md §3.2): kaynak SQLite ile HİÇ bağlantı açılmaz
(`mode=ro` bile WAL kipindeki DB'nin yanında -wal/-shm OLUŞTURABİLİR); db + varsa -wal/-journal geçici 0700
klasöre ham kopyalanır (stat ile tutarlılık denemesi), oradan backup API ile tek dosyaya birleştirilir.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time

from . import politika


def kopya_kok() -> str:
    d = politika.kopya_dizini()
    os.makedirs(d, mode=0o700, exist_ok=True)
    _izin_sagla(d)
    return d


def yeni_kopya_dizini(uygulama: str) -> str:
    """RUNTIME_DIR/oturum/<uygulama>-<zaman>-<pid>-<rastgele>/ (0700). Aynı saniyede iki kopya çakışmasın diye
    rastgele ek. Döner: mutlak yol."""
    kok = kopya_kok()
    ad = f"{uygulama}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{os.urandom(3).hex()}"
    yol = os.path.join(kok, ad)
    os.makedirs(yol, mode=0o700, exist_ok=False)
    return yol


def _izin_sagla(yol: str) -> None:
    try:
        os.chmod(yol, 0o700)
    except OSError:
        pass


# ------------------------------------------------------------------ SQLite tutarlı yedek

def sqlite_yedek(kaynak: str, hedef: str) -> str:
    """kaynak SQLite'ını hedefe tutarlı tek dosya olarak yedekle (WAL birleştirilmiş, -shm/-wal'sız).
    Kaynakla bağlantı AÇILMAZ (kaynak klasörde -wal/-shm oluşmasın): db + -wal + -journal ham kopyadan backup.
    Döner: 'ham-kopya'. kaynak hiç yazılmaz."""
    os.makedirs(os.path.dirname(hedef), exist_ok=True)
    return _ham_kopya_yedek(kaynak, hedef)


def _ham_kopya_yedek(kaynak: str, hedef: str) -> str:
    """kaynak + -wal (+ -journal)'ı geçici yere ham kopyala (stat ile tutarlılık denemesi), oradan backup.
    -shm KOPYALANMAZ (geçici kopyada yeniden üretilir). Firefox DB'leri dışlayıcı kilitle açık olsa da dosya
    okuması engellenmez; yarım yazım riski stat karşılaştırmasıyla (3 deneme) azaltılır."""
    with tempfile.TemporaryDirectory(prefix="deskhand-sql-") as td:
        os.chmod(td, 0o700)
        gecici = os.path.join(td, "db.sqlite")
        for _ in range(3):
            d0 = tuple(_stat(kaynak + ek) for ek in ("", "-wal", "-journal"))
            shutil.copyfile(kaynak, gecici)
            for ek in ("-wal", "-journal"):
                if os.path.exists(gecici + ek):
                    os.remove(gecici + ek)
                if os.path.exists(kaynak + ek):
                    try:
                        shutil.copyfile(kaynak + ek, gecici + ek)
                    except FileNotFoundError:  # arada kapandı/birleştirildi
                        pass
            d1 = tuple(_stat(kaynak + ek) for ek in ("", "-wal", "-journal"))
            if d0 == d1:
                break
        src = sqlite3.connect(gecici, timeout=2)
        try:
            try:
                src.execute("PRAGMA integrity_check")
            except sqlite3.DatabaseError:
                pass
            dst = sqlite3.connect(hedef)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    return "ham-kopya"


def _stat(yol: str):
    try:
        s = os.stat(yol)
        return (s.st_size, s.st_mtime_ns)
    except OSError:
        return None


# ------------------------------------------------------------------ dosya/dizin kopyalama

def dosya_kopyala(kaynak: str, hedef: str) -> bool:
    """Tek dosyayı kopyala (varsa). Döner: kopyalandı mı. Kaynak yazılmaz."""
    if not os.path.isfile(kaynak):
        return False
    os.makedirs(os.path.dirname(hedef), exist_ok=True)
    shutil.copyfile(kaynak, hedef)
    return True


def dizin_kopyala(kaynak: str, hedef: str, disla=None, yalnizca=None, boyut_siniri=None) -> int:
    """kaynak dizinini hedefe kopyala. disla: atlanacak göreli yollar/adlar (küme). yalnizca: yalnız bu üst
    adları al (None=hepsi). boyut_siniri: üst dizin başına bayt üst sınırı (aşılırsa o üst dizin atlanır).
    Döner: kopyalanan dosya sayısı. Kaynak yazılmaz."""
    disla = set(disla or ())
    sayac = 0
    if not os.path.isdir(kaynak):
        return 0
    for ust in sorted(os.listdir(kaynak)):
        if ust in disla:
            continue
        if yalnizca is not None and ust not in yalnizca:
            continue
        k = os.path.join(kaynak, ust)
        h = os.path.join(hedef, ust)
        if boyut_siniri is not None and os.path.isdir(k) and _dizin_boyutu(k) > boyut_siniri:
            continue
        if os.path.islink(k):
            continue  # symlink izleme (psd/bayat kopya riski)
        if os.path.isdir(k):
            sayac += _agac_kopyala(k, h, disla)
        elif os.path.isfile(k):
            os.makedirs(hedef, mode=0o700, exist_ok=True)
            shutil.copyfile(k, h)
            sayac += 1
    return sayac


def _agac_kopyala(kaynak: str, hedef: str, disla: set) -> int:
    sayac = 0
    for kok, dizinler, dosyalar in os.walk(kaynak):
        dizinler[:] = [d for d in dizinler if d not in disla
                       and not os.path.islink(os.path.join(kok, d))]
        rel = os.path.relpath(kok, kaynak)
        hedef_kok = hedef if rel == "." else os.path.join(hedef, rel)
        os.makedirs(hedef_kok, mode=0o700, exist_ok=True)
        for f in dosyalar:
            if f in disla:
                continue
            kf = os.path.join(kok, f)
            if os.path.islink(kf):
                continue
            try:
                shutil.copyfile(kf, os.path.join(hedef_kok, f))
                sayac += 1
            except OSError:
                pass
    return sayac


def _dizin_boyutu(yol: str) -> int:
    toplam = 0
    for kok, _, dosyalar in os.walk(yol):
        for f in dosyalar:
            try:
                toplam += os.lstat(os.path.join(kok, f)).st_size
            except OSError:
                pass
    return toplam


# ------------------------------------------------------------------ temizlik

def temizle(kopya_yolu: str) -> None:
    """Tek bir kopya dizinini sil. Yalnız kopya kökünün altındaki yolları siler (güvenlik)."""
    if not kopya_yolu:
        return
    kok = os.path.realpath(politika.kopya_dizini())
    hedef = os.path.realpath(kopya_yolu)
    if hedef == kok or not hedef.startswith(kok + os.sep):
        return
    shutil.rmtree(hedef, ignore_errors=True)


def sil_hepsi(haric=()) -> int:
    """Tüm oturum kopyalarını sil (haric: realpath'leri verilen dizinler kalır; flatpak.json gibi düz dosyalar
    kopya değildir, kalır). Döner: silinen dizin sayısı."""
    kok = politika.kopya_dizini()
    if not os.path.isdir(kok):
        return 0
    haric = {os.path.realpath(h) for h in haric}
    n = 0
    for ad in os.listdir(kok):
        yol = os.path.join(kok, ad)
        if os.path.islink(yol) or not os.path.isdir(yol) or os.path.realpath(yol) in haric:
            continue
        shutil.rmtree(yol, ignore_errors=True)
        n += 1
    return n
