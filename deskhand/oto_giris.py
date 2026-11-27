"""Automatic login detection and the decision for the panel's one-time KDE Wallet card (A1).

Why: with automatic login (no password typed) pam_kwallet cannot open the wallet and KDE asks for its password at every
login. The panel offers, once, either to seal the wallet key (cuzdan_ac.cuzdan_otomatik_kur) or to keep Deskhand's
secrets in its own kasa. This module only DECIDES whether that card is shown; the card itself is gui/cuzdan_karti.py.

Rules (review focus 1, 2, 5):
  - pure detection: it reads files only (the login manager's configuration, /proc/self/mountinfo, /sys) and starts no
    process; kart_durumu() also asks cuzdan_ac (busctl --auto-start=no, never starting a service) and anahtar_deposu.
  - closed-fail: anything unknown (unreadable configuration, no session bus, a back-end error) hides the card.
  - the login manager's files are read the way it does (KConfig cascade, the last file read wins, an empty `User=`
    clears): plasmalogin usr/lib/plasmalogin/plasmalogin.conf.d/*.conf → etc/plasmalogin.conf.d/*.conf →
    etc/plasmalogin.conf; sddm usr/lib/sddm/sddm.conf.d/*.conf → etc/sddm.conf.d/*.conf → etc/sddm.conf. The main file
    OVERRIDES conf.d. Only the active display manager (etc/systemd/system/display-manager.service) is read; when that
    link is missing both are, plasmalogin first.

API (A2): otomatik_giris_kullanicisi(kok) · otomatik_giris_acik(kok) · disk_sifreli(yol, kok) · kart_durumu() ·
kart_kapat() · kart_kapali().  `kok` is the file-system root (tests give a fake tree).
"""
from __future__ import annotations

import configparser
import os
import pwd
import re
import stat

KAPALI_ISARET = "cuzdan-karti-kapali"
_AZAMI = 64 * 1024
_BOLUM = "Autologin"
_DM_BAG = "etc/systemd/system/display-manager.service"
# (name, display-manager unit, files in the order the manager reads them; "*" = every *.conf of that directory, sorted)
_YONETICILER = (
    ("plasmalogin", "plasmalogin.service", ("usr/lib/plasmalogin/plasmalogin.conf.d/*", "etc/plasmalogin.conf.d/*",
                                            "etc/plasmalogin.conf")),
    ("sddm", "sddm.service", ("usr/lib/sddm/sddm.conf.d/*", "etc/sddm.conf.d/*", "etc/sddm.conf")),
)


def _kokte(kok: str, goreli: str) -> str:
    return os.path.join(kok, goreli.lstrip("/"))


# ---------------------------------------------------------------- automatic login

def _dosyalar(kok: str, desenler: tuple[str, ...]) -> list[str]:
    yollar = []
    for d in desenler:
        if d.endswith("/*"):
            dizin = _kokte(kok, d[:-2])
            try:
                adlar = sorted(os.listdir(dizin))
            except OSError:
                continue
            yollar += [os.path.join(dizin, a) for a in adlar if a.endswith(".conf")]
        else:
            yollar.append(_kokte(kok, d))
    return yollar


def _oku(yol: str) -> str | None:
    """A configuration file's text; None (skipped) when it is missing, not a regular file, unreadable, larger than
    64 KiB or not UTF-8."""
    try:
        with open(yol, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            ham = f.read(_AZAMI + 1)
    except OSError:
        return None
    if len(ham) > _AZAMI:
        return None
    try:
        return ham.decode("utf-8")
    except UnicodeDecodeError:
        return None


class _KConfig(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr  # KConfig keys are case-sensitive


def _user_degeri(metin: str) -> tuple[bool, str | None]:
    """[Autologin] User of one file → (the key is present, its value stripped; "" = present and empty). A file that
    configparser cannot parse counts as not read (False, None)."""
    c = _KConfig(strict=False, interpolation=None, delimiters=("=",), comment_prefixes=("#",),
                 default_section="\x00deskhand-varsayilan")
    try:
        # KConfig allows keys before the first group ([DEFAULT] is an ordinary group there, hence default_section)
        c.read_string("[\x00deskhand-ust]\n" + metin.removeprefix("﻿"))
    except configparser.Error:
        return False, None
    if not c.has_section(_BOLUM) or not c.has_option(_BOLUM, "User"):
        return False, None
    return True, (c.get(_BOLUM, "User", raw=True) or "").strip()


def _yonetici_kullanicisi(kok: str, desenler: tuple[str, ...]) -> str | None:
    kullanici = None
    for yol in _dosyalar(kok, desenler):
        metin = _oku(yol)
        if metin is None:
            continue
        var, deger = _user_degeri(metin)
        if var:
            kullanici = deger or None  # the last file read wins; an empty User= clears
    return kullanici


def _etkin_yonetici(kok: str) -> str | None:
    """The display-manager unit's name ("plasmalogin.service", "sddm.service", "gdm.service", …); None: no link."""
    try:
        return os.path.basename(os.readlink(_kokte(kok, _DM_BAG)))
    except OSError:
        return None


def otomatik_giris_kullanicisi(kok: str = "/") -> tuple[str | None, str | None]:
    """→ (user, "plasmalogin" | "sddm") of the active login manager's automatic login, or (None, None) (no automatic
    login, another login manager, nothing readable)."""
    etkin = _etkin_yonetici(kok)
    for ad, birim, desenler in _YONETICILER:
        if etkin is not None and etkin != birim:
            continue
        kullanici = _yonetici_kullanicisi(kok, desenler)
        if kullanici:
            return kullanici, ad
    return None, None


def _ben() -> str | None:
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return None


def otomatik_giris_acik(kok: str = "/") -> bool:
    """The login manager logs THIS user in automatically (no password typed at login)."""
    kullanici, _kaynak = otomatik_giris_kullanicisi(kok)
    ben = _ben()
    return kullanici is not None and ben is not None and kullanici == ben


# ---------------------------------------------------------------- disk encryption

_KACIS = re.compile(r"\\([0-7]{3})")


def _kacis_coz(s: str) -> str:
    return _KACIS.sub(lambda m: chr(int(m.group(1), 8)), s)


def _baglama(kok: str, yol: str) -> tuple[str, str] | None:
    """mountinfo → ("major:minor", source) of the mount that holds `yol` (the longest mount point that is `yol` or a
    parent of it; the last such line wins: stacked mounts). None: mountinfo unreadable / nothing matches."""
    metin = _oku(_kokte(kok, "proc/self/mountinfo"))
    if metin is None:
        return None
    en_iyi, uzunluk = None, -1
    for satir in metin.splitlines():
        alan = satir.split()
        if len(alan) < 7 or "-" not in alan[6:]:
            continue
        ayrac = alan.index("-", 6)
        if len(alan) < ayrac + 3:
            continue
        nokta = _kacis_coz(alan[4])
        if not (nokta == "/" or yol == nokta or yol.startswith(nokta.rstrip("/") + "/")):
            continue
        if len(nokta) >= uzunluk:
            en_iyi, uzunluk = (alan[2], _kacis_coz(alan[ayrac + 2])), len(nokta)
    return en_iyi


def _blok_dizini(kok: str, majmin: str, kaynak: str) -> str | None:
    """The device's sysfs directory: sys/dev/block/M:m, or for a 0:N device (btrfs subvolume, overlay) the /dev path
    in the source field resolved to its kernel name (sys/class/block/<name>). None: not resolvable."""
    if not majmin.startswith("0:"):
        d = _kokte(kok, f"sys/dev/block/{majmin}")
        return d if os.path.isdir(d) else None
    if not kaynak.startswith("/dev/"):
        return None
    gercek = os.path.realpath(_kokte(kok, kaynak))
    if not os.path.exists(gercek):
        return None
    ad = os.path.basename(gercek)
    if not ad or ad in (".", ".."):
        return None
    d = _kokte(kok, f"sys/class/block/{ad}")
    return d if os.path.isdir(d) else None


def _crypt_mi(dizin: str, gorulen: set[str], derinlik: int = 0) -> bool:
    """dm/uuid "CRYPT-…" on this device, any device under it (slaves/, recursively) or the disk a partition is on."""
    gercek = os.path.realpath(dizin)
    if gercek in gorulen or derinlik > 16:
        return False
    gorulen.add(gercek)
    uuid = _oku(os.path.join(gercek, "dm", "uuid"))
    if uuid is not None and uuid.strip().startswith("CRYPT-"):
        return True
    alt = os.path.join(gercek, "slaves")
    try:
        adlar = sorted(os.listdir(alt))
    except OSError:
        adlar = []
    if any(_crypt_mi(os.path.join(alt, a), gorulen, derinlik + 1) for a in adlar):
        return True
    if os.path.exists(os.path.join(gercek, "partition")):
        return _crypt_mi(os.path.dirname(gercek), gorulen, derinlik + 1)
    return False


def disk_sifreli(yol: str | None = None, kok: str = "/") -> bool | None:
    """The file system holding `yol` (default: HOME) is on dm-crypt (LUKS, directly or under LVM/RAID) → True; a
    resolved device chain without dm-crypt → False; not resolvable → None. Reads /proc and /sys only."""
    if yol is None:
        yol = os.path.expanduser("~")
    yol = os.path.normpath(os.path.realpath(yol) if kok == "/" else yol)
    b = _baglama(kok, yol)
    if b is None:
        return None
    dizin = _blok_dizini(kok, *b)
    if dizin is None:
        return None
    return _crypt_mi(dizin, set())


# ---------------------------------------------------------------- the card's "do not show again" mark

def _isaret_yolu() -> str:
    from . import yollar
    return os.path.join(yollar.state_dir(), KAPALI_ISARET)


def kart_kapat() -> None:
    """"Do not show again": STATE_DIR/cuzdan-karti-kapali (atomic, 0600, never through a symbolic link). OSError when
    it cannot be written."""
    import datetime

    from .cuzdan_ac import atomik_yaz
    zaman = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    atomik_yaz(_isaret_yolu(), (zaman + "\n").encode("ascii"))


def kart_kapali() -> bool:
    """The mark exists as a regular file (a symbolic link is not a mark)."""
    try:
        return stat.S_ISREG(os.lstat(_isaret_yolu()).st_mode)
    except OSError:
        return False


# ---------------------------------------------------------------- the card's decision

def _depo_bilgisi() -> tuple[bool, str | None]:
    """(TPM2 present, selected store "kasa" | "cuzdan" | None). None when the selection is not verified or the store is
    off (DESKHAND_ANAHTARLIK=kapali in tests: no real TPM call)."""
    try:
        from . import anahtar_deposu as AD
        d = AD.secili_depo().durum()
    except Exception:  # noqa: BLE001 - display only; closed-fail
        return False, None
    tur = d.get("tur")
    return bool(d.get("tpm")), tur if tur in ("kasa", "cuzdan") else None


def kart_durumu(kok: str = "/") -> dict:
    """The panel card's state (run it off the GUI thread: up to a few busctl calls of ≤5 s each).

    → {"goster": bool, "varyant": "ilk" | "yeniden" | None, "neden": str, "oto_giris": bool, "cuzdan_var": bool | None,
       "kurulu": bool | None, "son_sonuc": str | None, "disk_sifreli": bool | None, "tpm": bool,
       "depo": "kasa" | "cuzdan" | None}

    Decision (first match wins; `neden`):
      no automatic login for this user → hide "giris_parolali" · no Secret Service answer (busctl / session bus
      unknown) → hide "veri_yolu_yok" · no KDE Wallet (or unknown) → hide "cuzdan_yok" · "do not show again" → hide
      "kapatildi" · login unit state unknown (a back-end error) → hide "durum_bilinmiyor" · installed and the last
      result is not "anahtar_acmadi" → hide "kurulu" · installed and "anahtar_acmadi" → show "yeniden"
      ("anahtar_acmadi") · otherwise show "ilk" ("kurulu_degil").
    Fields after the deciding one are not evaluated (None); disk_sifreli, tpm and depo are read only when the card is
    shown (tpm False and depo None otherwise)."""
    from . import cuzdan_ac as CA
    d = {"goster": False, "varyant": None, "neden": "", "oto_giris": False, "cuzdan_var": None, "kurulu": None,
         "son_sonuc": None, "disk_sifreli": None, "tpm": False, "depo": None}

    def gizle(neden: str) -> dict:
        d["neden"] = neden
        return d

    try:
        d["oto_giris"] = otomatik_giris_acik(kok)
    except Exception:  # noqa: BLE001 - closed-fail
        d["oto_giris"] = False
    if not d["oto_giris"]:
        return gizle("giris_parolali")
    try:
        servis = CA.servis_var()
    except Exception:  # noqa: BLE001
        servis = None
    if servis is None:
        return gizle("veri_yolu_yok")
    try:
        var = CA.cuzdan_durumu().get("var")
        d["cuzdan_var"] = var if isinstance(var, bool) else None
    except Exception:  # noqa: BLE001
        d["cuzdan_var"] = None
    if d["cuzdan_var"] is not True:
        return gizle("cuzdan_yok")
    if kart_kapali():
        return gizle("kapatildi")
    try:
        cd = CA.durum()
        # durum(): a kasa error is reported as kurulu False + a reason → unknown, not "not installed"
        d["kurulu"] = None if (not cd.get("kurulu") and cd.get("neden")) else bool(cd.get("kurulu"))
    except Exception:  # noqa: BLE001
        d["kurulu"] = None
    if d["kurulu"] is None:
        return gizle("durum_bilinmiyor")
    try:
        d["son_sonuc"] = (CA.son_sonuc() or {}).get("sonuc")
    except Exception:  # noqa: BLE001
        d["son_sonuc"] = None
    if d["kurulu"] and d["son_sonuc"] != "anahtar_acmadi":
        return gizle("kurulu")
    d["goster"] = True
    d["varyant"], d["neden"] = ("yeniden", "anahtar_acmadi") if d["kurulu"] else ("ilk", "kurulu_degil")
    try:
        d["disk_sifreli"] = disk_sifreli(kok=kok)
    except Exception:  # noqa: BLE001
        d["disk_sifreli"] = None
    d["tpm"], d["depo"] = _depo_bilgisi()
    return d
