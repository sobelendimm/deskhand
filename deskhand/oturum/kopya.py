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
import subprocess
import sys
import time

from . import kopya_bekcisi as _bekci
from . import politika

KOPYA_AZAMI_SAYI = 3                    # yeni kopya açılırken (tüm masaüstleri) en çok bu kadar kopya…
KOPYA_AZAMI_BAYT = 1536 * 1024 * 1024   # …ya da bu kadar bayt; aşılırsa EN ESKİ SAHİPSİZLER silinir (canlılar asla)
EN_AZ_BOS_BAYT = 256 * 1024 * 1024      # süpürmeden sonra RUNTIME_DIR'da bundan az boş yer varsa kopya açılmaz (Dur 9)
SINIR_PAYI = 120.0                      # sınır aşımında: hazırlayanı canlı ama sahibi yazılmamış kopya bu kadar sn korunur


def kopya_kok() -> str:
    d = politika.kopya_dizini()
    os.makedirs(d, mode=0o700, exist_ok=True)
    _izin_sagla(d)
    return d


def yeni_kopya_dizini(uygulama: str) -> str:
    """RUNTIME_DIR/oturum/<uygulama>-<zaman>-<pid>-<rastgele>/ (0700). Aynı saniyede iki kopya çakışmasın diye
    rastgele ek. Önce TÜM masaüstlerinin ölü kopyaları süpürülür ve sınır uygulanır (sınır_uygula); geçici alan yine
    de yetmiyorsa Dur 9 (kopya yarıda ENOSPC ile kalmasın). Kopyaya hazırlayan sürecin kaydı yazılır (sahibi
    sahip_kaydet ile yazılana dek HAZIRLIK_AZAMI sn korunur). Döner: mutlak yol."""
    kok = kopya_kok()
    sinir_uygula()
    bos_alan_denetle(kok)
    ad = f"{uygulama}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{os.urandom(3).hex()}"
    yol = os.path.join(kok, ad)
    os.makedirs(yol, mode=0o700, exist_ok=False)
    _bekci.sahip_yaz(yol, {"hazirlayan": os.getpid(), "hazirlayan_bas": _bekci.baslangic(os.getpid()),
                           "zaman": time.time()})
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


def izinleri_daralt(kok: str) -> None:
    """Kopyadaki her dosyayı 0600, her dizini 0700 yap (shutil.copyfile umask'la 0644 bırakıyordu: çerez/anahtar
    deposu kopyaları başka kullanıcıya açık olmasın; üst dizin zaten 0700). Sembolik bağlara dokunulmaz."""
    for k, dizinler, dosyalar in os.walk(kok):
        for ad, kip in [(d, 0o700) for d in dizinler] + [(f, 0o600) for f in dosyalar]:
            y = os.path.join(k, ad)
            try:
                if not os.path.islink(y):
                    os.chmod(y, kip)
            except OSError:
                pass


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


# ------------------------------------------------------------------ sahiplik + süpürme (22 Kas 2026: tmpfs doldu)

def kokler() -> list[str]:
    """Tüm masaüstlerinin kopya kökleri (var olanlar): RUNTIME_DIR/oturum + RUNTIME_DIR/masa/<ad>/oturum."""
    from .. import masalar
    sonuc = []
    adaylar = [masalar.oturum_koku("")]
    try:
        for ad in sorted(os.listdir(masalar.masa_koku())):
            if masalar.AD_DESENI.fullmatch(ad) and not os.path.islink(os.path.join(masalar.masa_koku(), ad)):
                adaylar.append(masalar.oturum_koku(ad))
    except OSError:
        pass
    for k in adaylar:
        if _bekci.kok_gecerli(k):
            sonuc.append(k)
    return sonuc


def _flatpak_korunan(kok: str) -> set[str]:
    """O kökün Flatpak kaydında PID'i yaşayan örneklerin kopyaları (flatpak run kendi scope'unda yaşar)."""
    from . import flatpak_ornek
    korunan = set()
    for g in flatpak_ornek.oku(os.path.join(kok, "flatpak.json")):
        try:
            if g.get("kopya") and g.get("pid") and flatpak_ornek._canli(int(g["pid"])):
                korunan.add(os.path.realpath(g["kopya"]))
        except (TypeError, ValueError):
            continue
    return korunan


def kopyalar(kok_listesi=None, boyut: bool = True) -> list[dict]:
    """Kopyalar ve durumları: {yol, kok, boyut, zaman, canli, neden}. canli: sahip süreç (pid + başlangıç) yaşıyor,
    hazırlayanı yaşıyor (HAZIRLIK_AZAMI içinde), sahip kaydı yok ama çok yeni (ESKI_PAY), Flatpak kaydında canlı ya da
    bir süreç kopyayı kullanıyor (komut satırı / cwd / açık dosya). Ölçüt kuşkuluysa CANLI sayılır."""
    simdi = time.time()
    liste = []
    for kok in (kokler() if kok_listesi is None else kok_listesi):
        try:
            adlar = sorted(os.listdir(kok))
        except OSError:
            continue
        korunan = _flatpak_korunan(kok)
        for ad in adlar:
            yol = os.path.join(kok, ad)
            if not _bekci.KOPYA_DESENI.fullmatch(ad) or os.path.islink(yol) or not os.path.isdir(yol):
                continue
            s = _bekci.sahip_oku(yol)
            try:
                zaman = float(s.get("zaman") or os.lstat(yol).st_mtime)
            except (OSError, TypeError, ValueError):
                zaman = simdi
            g = {"yol": yol, "kok": kok, "boyut": _dizin_boyutu(yol) if boyut else None, "zaman": zaman, "canli": False,
                 "neden": "", "hazirlayan_canli": False}
            if os.path.realpath(yol) in korunan:
                g.update(canli=True, neden="flatpak")
            elif s.get("pid") is not None:
                if _bekci.canli(s.get("pid"), s.get("bas")):
                    g.update(canli=True, neden="sahip")
            elif s.get("hazirlayan") is not None:
                if _bekci.canli(s.get("hazirlayan"), s.get("hazirlayan_bas")) and simdi - zaman < _bekci.HAZIRLIK_AZAMI:
                    g.update(canli=True, neden="hazirlaniyor", hazirlayan_canli=True)
            else:
                try:
                    mtime = os.lstat(yol).st_mtime
                except OSError:
                    mtime = simdi
                if simdi - mtime < _bekci.ESKI_PAY:
                    g.update(canli=True, neden="yeni")
            liste.append(g)
    adaylar = [g["yol"] for g in liste if not g["canli"]]
    kullanilan = _bekci.kullanilanlar(adaylar) if adaylar else set()
    for g in liste:
        if g["yol"] in kullanilan:
            g.update(canli=True, neden="kullaniliyor")
    return liste


def _sil(g: dict) -> bool:
    from ..gunluk import gunluk
    mb = (g["boyut"] if g.get("boyut") is not None else _dizin_boyutu(g["yol"])) // (1024 * 1024)
    tamam = _bekci.guvenli_sil(g["yol"], g["kok"])
    if tamam:
        gunluk(f"oturum: sahipsiz kopya silindi: {g['yol']} ({mb} MB)")
    return tamam


def supur(kok_listesi=None) -> list[str]:
    """Sahibi ölmüş ve kimsenin kullanmadığı kopyaları sil (tüm masaüstleri). Canlı kopya ASLA silinmez. → silinenler."""
    return [g["yol"] for g in kopyalar(kok_listesi, boyut=False) if not g["canli"] and _sil(g)]


def supur_sessiz() -> None:
    """Masaüstü/uygulama başlatma yolunda: süpür, hata asıl işi düşürmesin."""
    try:
        supur()
    except Exception:  # noqa: BLE001
        pass


def sinir_uygula(azami_sayi: int = KOPYA_AZAMI_SAYI, azami_bayt: int = KOPYA_AZAMI_BAYT, kok_listesi=None) -> list[str]:
    """Yeni kopya açılmadan önce: ölüleri süpür; toplam (yeni kopya dahil) sayı/boyut sınırı aşılıyorsa sahibi
    yazılmamış ve SINIR_PAYI'ndan eski (hazırlanırken takılmış) kopyalar da EN ESKİDEN başlayarak silinir. Sahip süreci
    yaşayan, kullanılan ya da Flatpak'ta canlı kopyaya DOKUNULMAZ. → silinenler."""
    try:
        liste = kopyalar(kok_listesi)
    except Exception:  # noqa: BLE001 - süpürme asıl işi (kopya açmayı) düşürmesin
        return []
    silinen = [g["yol"] for g in liste if not g["canli"] and _sil(g)]
    kalan = [g for g in liste if g["yol"] not in silinen]
    simdi = time.time()

    def asildi():
        return len(kalan) + 1 > azami_sayi or sum(g["boyut"] for g in kalan) > azami_bayt

    for g in sorted(kalan, key=lambda x: x["zaman"]):
        if not asildi():
            break
        if g["neden"] == "hazirlaniyor" and simdi - g["zaman"] >= SINIR_PAYI and \
                not _bekci.kullanilanlar([g["yol"]]) and _sil(g):
            silinen.append(g["yol"])
            kalan.remove(g)
    global _SON_UYARI
    _SON_UYARI = None
    if asildi():  # canlılar silinmez: yalnız uyar (tarayıcı önbelleği/indirmeler RUNTIME_DIR'ı doldurabilir)
        from ..gunluk import gunluk
        from ..i18n import _
        mb, sayi = sum(g["boyut"] for g in kalan) // (1024 * 1024), len(kalan)
        _SON_UYARI = _("açık oturum kopyaları sınırı aşıyor ({sayi} kopya, {mb} MB; sınır {azami_sayi} kopya / "
                       "{azami_mb} MB): kullanılmayan arka plan tarayıcılarını kapatın").format(
            sayi=sayi, mb=mb, azami_sayi=azami_sayi, azami_mb=azami_bayt // (1024 * 1024))
        gunluk(f"oturum: kopya sınırı aşıldı ({sayi} kopya, {mb} MB); canlı kopyalar silinmedi")
    return silinen


_SON_UYARI: str | None = None


def son_uyari() -> str | None:
    """Son sinir_uygula çağrısının uyarısı (canlı kopyalar sınırı aşıyorsa) ya da None."""
    return _SON_UYARI


def bos_alan_denetle(kok: str, en_az: int = EN_AZ_BOS_BAYT) -> None:
    """RUNTIME_DIR (tmpfs) boş alanı en_az'dan küçükse Dur 9: kopya yarıda ENOSPC ile kalmasın, diğer durum dosyaları
    yazılabilsin."""
    from ..hata import ARAC_EKSIK, Dur
    from ..i18n import _
    try:
        st = os.statvfs(kok)
    except OSError:
        return
    bos = st.f_bavail * st.f_frsize
    if bos < en_az:
        raise Dur(ARAC_EKSIK, _("geçici alan dolu ({yol}: {bos} MB boş): oturum kopyası açılmadı; ayrıntı: deskhand "
                                "doctor").format(yol=kok, bos=bos // (1024 * 1024)))


def sahip_kaydet(kopya_yolu: str, pid: int, bekci: bool = True, son_pay: float | None = None):
    """Kopyayı kullanan tarayıcı süreci başlatıldı: sahip kaydını yaz (pid + başlangıç zamanı) ve bekçiyi başlat
    (süreç bitince kopyayı HEMEN siler). Hata asıl işi düşürmez. → bekçi Popen | None."""
    if not kopya_yolu or not os.path.isdir(kopya_yolu):
        return None
    eski = _bekci.sahip_oku(kopya_yolu)
    bas = _bekci.baslangic(pid)
    _bekci.sahip_yaz(kopya_yolu, {**eski, "pid": int(pid), "bas": bas, "zaman": eski.get("zaman") or time.time()})
    if not bekci:
        return None
    kok = os.path.dirname(os.path.realpath(kopya_yolu))
    try:
        return subprocess.Popen([sys.executable, "-I", os.path.abspath(_bekci.__file__), "--kok", kok,
                                 "--kopya", os.path.realpath(kopya_yolu), "--pid", str(int(pid)),
                                 "--bas", str(bas or ""),
                                 *(["--son-pay", str(float(son_pay))] if son_pay is not None else [])],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                close_fds=True, start_new_session=True)
    except OSError:
        return None


def ozet() -> tuple[int, int, int]:
    """(kopya sayısı, toplam bayt, ölü kopya sayısı) — tüm masaüstleri."""
    liste = kopyalar()
    return len(liste), sum(g["boyut"] for g in liste), sum(1 for g in liste if not g["canli"])
