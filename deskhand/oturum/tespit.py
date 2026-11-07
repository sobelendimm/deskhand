"""Uygulamanın KULLANICININ oturumunda açık olup olmadığını saptama (docs/SESSIONS.md §6)
ve uygulama adından profil/veri yolu çözümü.

Tek sinyal güvenilir değil: herhangi biri pozitifse "çalışıyor" say; sorgulanamayan sinyal "belirsiz" olarak
bildirilir (çağıran açık sayar). Deskhand'nin kendi başlattıkları (DESKHAND_SANAL ortamı / sanal masaüstü durum
dosyasındaki özel DBUS_SESSION_BUS_ADDRESS) hariç tutulur. Hiçbir işlem BAŞLATILMAZ, kilit ALINMAZ;
yalnız salt-okuma sorgular (fcntl F_GETLK, /proc, ListNames, flatpak ps, /proc/net/unix).

Sır/parola/çerez DEĞERİ okunmaz; yalnız dosya adları, PID'ler, alan adları.
"""
from __future__ import annotations

import configparser
import fcntl
import os
import re
import shutil
import struct

# ------------------------------------------------------------------ süreç/ortam

def _ozel_bus_adresleri() -> set[str]:
    """Deskhand'nin özel D-Bus adres(ler)i: sanal masaüstü durum dosyasındaki `dbus_adres`."""
    try:
        from ..masaustu import durum_oku
        d = durum_oku() or {}
    except Exception:  # noqa: BLE001
        d = {}
    a = d.get("dbus_adres") or ""
    return {a} if a else set()


def _ozel_bus_mu(adres: str) -> bool:
    """Adres Deskhand'nin özel veri yolu mu? Durum dosyasındaki adres ya da RUNTIME_DIR/sanal-N/ altındaki soket."""
    if not adres:
        return False
    if adres in _ozel_bus_adresleri():
        return True
    try:
        from .. import yollar
        kok = os.path.realpath(yollar.runtime_dir())
    except Exception:  # noqa: BLE001
        return False
    for parca in adres.split(";"):
        for alan in parca.split(","):
            if alan.split(":", 1)[-1].startswith("path="):
                yol = os.path.realpath(alan.split("path=", 1)[1])
                if yol.startswith(os.path.join(kok, "sanal-")):
                    return True
    return False


def _kendi_sureci(pid: int) -> bool:
    """PID Deskhand'nin sanal masaüstüne mi ait (DESKHAND_SANAL ortamı ya da özel veri yolu)?"""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            cevre = f.read().split(b"\0")
    except OSError:
        return False
    for e in cevre:
        if e.startswith(b"DESKHAND_SANAL="):
            return True
        if e.startswith(b"DBUS_SESSION_BUS_ADDRESS=") and \
                _ozel_bus_mu(e.split(b"=", 1)[1].decode(errors="replace")):
            return True
    return False


def _proc_alanlari(pid: int) -> tuple[str, str, str]:
    """(comm, cmdline, exe-basename) — hata olursa boş dizeler."""
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
    except OSError:
        comm = ""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmdline = ""
    try:
        exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        exe = ""
    return comm, cmdline, exe


def _surec_ara(desenler, proc_koku: str = "/proc") -> list[int]:
    """Kullanıcının kendi UID'indeki, desene uyan (Deskhand dışı) PID'ler. proc_koku testlerde sahte olabilir."""
    uid = os.getuid()
    bulunan = []
    rx = re.compile("|".join(desenler), re.I) if desenler else None
    try:
        girisler = os.listdir(proc_koku)
    except OSError:
        return []
    for giris in girisler:
        if not giris.isdigit():
            continue
        pid = int(giris)
        d = os.path.join(proc_koku, giris)
        if proc_koku == "/proc":
            if pid == os.getpid():  # kendi komut satırımız (ör. "deskhand ac telegram") eşleşmesin
                continue
            try:
                if os.stat(d).st_uid != uid:
                    continue
            except OSError:
                continue
            if _kendi_sureci(pid):
                continue
            comm, cmdline, exe = _proc_alanlari(pid)
        else:  # test: sahte /proc (comm + cmdline dosyaları)
            comm = _oku(os.path.join(d, "comm"))
            cmdline = _oku(os.path.join(d, "cmdline")).replace("\0", " ")
            exe = os.path.basename(_oku(os.path.join(d, "exe_link")))
        metin = f"{comm} {exe} {cmdline}"
        if rx and rx.search(metin):
            bulunan.append(pid)
    return bulunan


def _oku(yol: str) -> str:
    try:
        with open(yol, errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _flatpak_calisan() -> set[str] | None:
    """`flatpak ps` ile KULLANICININ çalışan uygulama kimlikleri (Deskhand'nin başlattığı örnekler hariç).
    flatpak yok → boş küme; sorgu başarısız → None (bilinemiyor)."""
    from . import flatpak_ornek, politika
    if not shutil.which("flatpak"):
        return set()
    ornekler = flatpak_ornek.ornekler()
    if ornekler is None:
        return None
    bizim = flatpak_ornek.kayitli_ornekler(politika.flatpak_kayit())
    return {o["application"] for o in ornekler
            if o["instance"] not in bizim and not (o["pid"] and _kendi_sureci(o["pid"]))}


# ------------------------------------------------------------------ genel süreç tespiti (bilinmeyen uygulamalar)

def _yorumlayici(ad: str) -> bool:
    from .cozum import _yorumlayici_mi
    return _yorumlayici_mi(ad)


def ikili_ara(ikililer, proc_koku: str = "/proc") -> tuple[list[int], bool]:
    """Kullanıcının UID'inde, Deskhand dışı, adı ikililer'den birine TAM uyan süreçler: exe adı, comm (15 karakter),
    argv[0] adı ya da (yorumlayıcıyla çalışıyorsa) betik adı. → (pidler, okunabildi). /proc okunamazsa
    okunabildi=False (bilinemiyor)."""
    adlar = {os.path.basename(a) for a in ikililer if a}
    if not adlar:
        return [], True
    kisa = {a[:15] for a in adlar}
    uid = os.getuid()
    try:
        girisler = os.listdir(proc_koku)
    except OSError:
        return [], False
    gercek = proc_koku == "/proc"
    bulunan = []
    for giris in girisler:
        if not giris.isdigit():
            continue
        pid = int(giris)
        d = os.path.join(proc_koku, giris)
        if gercek:
            if pid == os.getpid():
                continue
            try:
                if os.stat(d).st_uid != uid:
                    continue
            except OSError:
                continue
            try:
                with open(os.path.join(d, "cmdline"), "rb") as f:
                    argv = [x.decode(errors="replace") for x in f.read().split(b"\0") if x]
            except OSError:
                argv = []
            comm = _oku(os.path.join(d, "comm"))
            try:
                exe = os.path.basename(os.readlink(os.path.join(d, "exe")))
            except OSError:
                exe = ""
        else:  # test: sahte /proc (comm, cmdline [\0 ayrılmış], exe_link)
            comm = _oku(os.path.join(d, "comm"))
            argv = [x for x in _oku(os.path.join(d, "cmdline")).split("\0") if x]
            exe = os.path.basename(_oku(os.path.join(d, "exe_link")))
        exe = exe.removesuffix(" (deleted)")
        arg0 = os.path.basename(argv[0]) if argv else ""
        eslesti = exe in adlar or comm in kisa or arg0 in adlar
        if not eslesti and argv and (_yorumlayici(arg0) or _yorumlayici(exe)):
            betikler = [os.path.basename(a) for a in argv[1:4] if not a.startswith("-")]
            eslesti = any(b in adlar for b in betikler)
        if eslesti and not (gercek and _kendi_sureci(pid)):
            bulunan.append(pid)
    return bulunan, True


# ------------------------------------------------------------------ Firefox profil kilidi

# fcntl flock yapısı (l_type, l_whence, l_start, l_len, l_pid) — Linux x86_64 düzeni
_FLOCK = struct.Struct("hhqqi")


def _parentlock_kilitli(profil: str) -> int:
    """.parentlock üzerinde fcntl F_GETLK ile kilit sahibinin PID'si (0 = kilitsiz). Kilit ALINMAZ."""
    yol = os.path.join(profil, ".parentlock")
    if not os.path.exists(yol):
        return 0
    try:
        fd = os.open(yol, os.O_RDWR)
    except OSError:
        return 0
    try:
        veri = _FLOCK.pack(fcntl.F_WRLCK, 0, 0, 0, 0)
        sonuc = fcntl.fcntl(fd, fcntl.F_GETLK, veri)
        l_type, _, _, _, l_pid = _FLOCK.unpack(sonuc)
        return l_pid if l_type != fcntl.F_UNLCK else 0
    except OSError:
        return 0
    finally:
        os.close(fd)


def _lock_symlink_pid(profil: str) -> int:
    """`lock` symlink'i `ip:+pid` → yaşayan PID (0 yoksa). nsProfileLock.cpp yedek yolu."""
    try:
        hedef = os.readlink(os.path.join(profil, "lock"))
    except OSError:
        return 0
    m = re.search(r"\+(\d+)$", hedef)
    if not m:
        return 0
    pid = int(m.group(1))
    return pid if _pid_yasiyor(pid) else 0


def _pid_yasiyor(pid: int) -> bool:
    return os.path.isdir(f"/proc/{pid}")


# ------------------------------------------------------------------ Chromium SingletonLock

def _singleton_lock_pid(veri_dizini: str) -> int:
    """SingletonLock symlink'i `hostname-pid` → yaşayan, bize ait olmayan PID (0 yoksa)."""
    try:
        hedef = os.readlink(os.path.join(veri_dizini, "SingletonLock"))
    except OSError:
        return 0
    m = re.search(r"-(\d+)$", hedef)
    if not m:
        return 0
    pid = int(m.group(1))
    if not _pid_yasiyor(pid) or _kendi_sureci(pid):
        return 0
    return pid


# ------------------------------------------------------------------ soyut Unix soketleri (Telegram)

def _soyut_soket_var(desen: str) -> bool:
    """/proc/net/unix içinde @ ile başlayan (soyut) soket adı desene uyuyor mu? (Telegram ...-TelegramDesktop)"""
    try:
        with open("/proc/net/unix") as f:
            satirlar = f.read().splitlines()
    except OSError:
        return False
    rx = re.compile(desen, re.I)
    for s in satirlar[1:]:
        parcalar = s.split()
        if parcalar and parcalar[-1].startswith("@") and rx.search(parcalar[-1]):
            return True
    return False


# ------------------------------------------------------------------ D-Bus adı (gerçek oturum veri yolu)

def _dbus_sahip_var(ad: str) -> bool:
    """GERÇEK kullanıcı oturum veri yolunda ad'ın sahibi var mı (NameHasOwner). jeepney ile salt-okuma.
    Deskhand'nin özel veri yolundan DEĞİL, kullanıcınınkinden sorar (XDG_RUNTIME_DIR/bus)."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except ImportError:
        return False
    adres = _gercek_bus_adresi()
    try:
        conn = open_dbus_connection(bus=adres)
    except Exception:
        return False
    try:
        hedef = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus",
                            interface="org.freedesktop.DBus")
        yanit = conn.send_and_get_reply(new_method_call(hedef, "NameHasOwner", "s", (ad,)), timeout=3)
        return bool(yanit.body and yanit.body[0])
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _gercek_bus_adresi() -> str:
    """Kullanıcının gerçek oturum veri yolu adresi (özel Deskhand veri yolu DEĞİL)."""
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    varsayilan = f"unix:path={rt}/bus"
    adres = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or varsayilan
    # Deskhand içinden çağrılıyorsak (özel veri yolu / sanal masaüstü ortamı) gerçek yola dön
    if os.environ.get("DESKHAND_SANAL") or _ozel_bus_mu(adres):
        return varsayilan
    return adres


# ------------------------------------------------------------------ Firefox profil yolu çözümü

def firefox_profil_dizini() -> str | None:
    """profiles.ini'deki [Install*] Default= esas (NOT [Profile*] Default=1). Dönüş: realpath'li gerçek profil
    (psd symlink'i çözülür; *-backup/*-back-ovfs bayat kopyalar ASLA). Bulunamazsa None."""
    for kok in _firefox_kokleri():
        ini = os.path.join(kok, "profiles.ini")
        if not os.path.isfile(ini):
            continue
        cp = configparser.ConfigParser()
        try:
            cp.read(ini)
        except configparser.Error:
            continue
        # 1) [Install*] bölümündeki Default= (gerçek varsayılan)
        yol = None
        for bolum in cp.sections():
            if bolum.startswith("Install") and cp.has_option(bolum, "Default"):
                yol = cp.get(bolum, "Default")
                break
        # 2) yedek: [Profile*] Default=1 olan
        if not yol:
            for bolum in cp.sections():
                if bolum.startswith("Profile") and cp.get(bolum, "Default", fallback="0") == "1":
                    p = cp.get(bolum, "Path", fallback="")
                    rel = cp.get(bolum, "IsRelative", fallback="1") == "1"
                    yol = os.path.join(kok, p) if rel else p
                    break
                    # (Install* önceliklidir; buraya yalnız Install yoksa düşülür)
        if not yol:
            continue
        tam = yol if os.path.isabs(yol) else os.path.join(kok, yol)
        if os.path.exists(tam):
            return os.path.realpath(tam)
    return None


def _firefox_kokleri() -> list[str]:
    """Firefox profil köklerinin aday konumları (XDG ve eski düzen)."""
    ev = os.path.expanduser("~")
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(ev, ".config")
    return [os.path.join(cfg, "mozilla", "firefox"), os.path.join(ev, ".mozilla", "firefox")]


def chromium_veri_dizini(uygulama: str) -> str | None:
    """Chromium ailesi için kullanıcı veri dizini (realpath). Bulunamazsa None."""
    ev = os.path.expanduser("~")
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(ev, ".config")
    adlar = {"chromium": "chromium", "vivaldi": "vivaldi", "chrome": "google-chrome",
             "brave": os.path.join("BraveSoftware", "Brave-Browser")}
    alt = adlar.get(uygulama)
    if not alt:
        return None
    yol = os.path.join(cfg, alt)
    return os.path.realpath(yol) if os.path.exists(yol) else None


# ------------------------------------------------------------------ genel giriş

# Uygulama → süreç/komut desenleri ve flatpak kimliği
_SUREC_DESEN = {
    "firefox": [r"\bfirefox\b"],
    "chromium": [r"/chromium\b", r"\bchromium\b"],
    "vivaldi": [r"\bvivaldi\b"],
    "chrome": [r"google-chrome", r"/chrome\b"],
    "brave": [r"\bbrave\b"],
    "telegram": [r"[Tt]elegram"],
    "signal": [r"signal-desktop", r"\bSignal\b"],
    "element": [r"[Ee]lement"],
    "steam": [r"\bsteam\b"],
    "discord": [r"[Dd]iscord"],
    "spotify": [r"[Ss]potify"],
    "obsidian": [r"[Oo]bsidian"],
    "vscode": [r"/code\b", r"visual-studio-code", r"\bcode-oss\b"],
}


def calisiyor_mu(uygulama: str, flatpak_kimlik: str | None = None, ikililer=(), flatpaklar=()) -> tuple[bool, dict]:
    """(bool, ayrinti). Herhangi bir sinyal pozitifse True. ayrinti: hangi sinyallerin eşleştiği (PID'ler,
    yöntem); bir sinyal SORGULANAMADIYSA ayrinti["belirsiz"] = [nedenler] (çağıran "açık" saymalı).
    Deskhand'nin kendi süreçleri hariç. uygulama = politika normu (küçük harf); ikililer/flatpaklar = çözülmüş
    uygulamanın Exec ikili adları / Flatpak kimlikleri (cozum.coz)."""
    ayrinti: dict = {}
    pozitif = False
    belirsiz: list[str] = []

    # 1) süreç (bilinen uygulama desenleri)
    desenler = _SUREC_DESEN.get(uygulama)
    if desenler:
        pidler = _surec_ara(desenler)
        if pidler:
            ayrinti["surec_pid"] = pidler
            pozitif = True

    # 1b) süreç (çözülmüş Exec ikilisi; bilinmeyen uygulamalar dahil)
    if ikililer:
        pidler, okundu = ikili_ara(ikililer)
        if not okundu:
            belirsiz.append("/proc okunamadı")
        if pidler:
            ayrinti["ikili_pid"] = pidler
            pozitif = True

    # 2) Flatpak örneği
    fkler = [f for f in dict.fromkeys([flatpak_kimlik, *flatpaklar]) if f]
    if fkler:
        calisan = _flatpak_calisan()
        if calisan is None:
            belirsiz.append("flatpak ps sorgulanamadı")
        else:
            bulunan = [f for f in fkler if f in calisan]
            if bulunan:
                ayrinti["flatpak"] = bulunan[0] if len(bulunan) == 1 else bulunan
                pozitif = True

    # 3) profil kilidi
    if uygulama == "firefox":
        prof = firefox_profil_dizini()
        if prof:
            pid = _parentlock_kilitli(prof) or _lock_symlink_pid(prof)
            if pid and not _kendi_sureci(pid):
                ayrinti["profil_kilit_pid"] = pid
                pozitif = True
    elif uygulama in ("chromium", "vivaldi", "chrome", "brave"):
        vd = chromium_veri_dizini(uygulama)
        if vd:
            pid = _singleton_lock_pid(vd)
            if pid:
                ayrinti["singleton_pid"] = pid
                pozitif = True

    # 4) soyut soket (Telegram)
    if uygulama == "telegram" and _soyut_soket_var(r"-TelegramDesktop$"):
        ayrinti["soyut_soket"] = "TelegramDesktop"
        pozitif = True

    # 5) D-Bus adı (gerçek veri yolu)
    dbus_ad = {
        "lutris": "net.lutris.Lutris",
        "spotify": "org.mpris.MediaPlayer2.spotify",
    }.get(uygulama)
    if dbus_ad and _dbus_sahip_var(dbus_ad):
        ayrinti["dbus"] = dbus_ad
        pozitif = True

    if belirsiz:
        ayrinti["belirsiz"] = belirsiz
    return pozitif, ayrinti
