"""`deskhand install-desktop` (`masaustu-kur`): the desktop integration install.sh writes, for a pip/pipx install.

Writes (XDG paths, atomically, 0644): the application menu entry (`panel`), the "Give a task" entry (`panel --gorev`),
the login entry that starts the panel in the tray (`panel --tepsi`; `--no-autostart`: not written, ours removed), the
icon, and for KWin before 6.8 (or an unknown version) the desktop entry that grants the screenshot helper ScreenShot2.

Exec lines are ABSOLUTE: the running interpreter + `-I -m deskhand …` (no PATH lookup of `deskhand`; ~/.local/bin is
writable by any user process), quoted like install.sh's desktop_exec. A package in the user site-packages (pip --user)
cannot be imported under -I: there `-E -P` (no PYTHON* variables, no current directory on sys.path).

Every file we write carries ISARET (install.sh's marker: uninstall.sh removes it too) and IMZA (only we write it):
`--remove` deletes only files with IMZA, and the icon only when it is byte-identical to the packaged one.
An install.sh install (git clone) is never touched: run from a source checkout, or with install.sh's command or one of
its desktop entries present, the command says what to do and writes nothing (exit 1)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from . import yollar
from .i18n import _

ISARET = "X-Deskhand-Installed=true"  # install.sh / uninstall.sh DESKTOP_MARK
IMZA = "X-Deskhand-Installer=install-desktop"
SARMALAYICI_ISARETI = "# deskhand wrapper (install.sh)"  # install.sh MARK
GUVENLI = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./+,:=@%")


class KurulumHatasi(Exception):
    pass


def _kaynak_kurulumu() -> bool:
    from . import doktor
    return doktor._kaynak_kurulumu()


def _kullanici_sitesi() -> bool:
    """Is the package in the user site-packages (pip install --user)? -I would hide it."""
    import site
    try:
        kullanici = os.path.realpath(site.getusersitepackages())
    except Exception:  # noqa: BLE001
        return False
    return os.path.realpath(yollar.PAKET_DIZIN).startswith(kullanici + os.sep)


def kwin_surumu() -> str:
    from . import doktor
    return doktor._komut_ciktisi("kwin_wayland", "--version")


def _eski_kwin() -> bool:
    """KWin before 6.8 serves ScreenShot2 only to a program whose desktop entry lists it; unknown version: write it
    (harmless on a newer KWin, which ignores the entry)."""
    from . import doktor
    surum = doktor._surum_demeti(kwin_surumu() or "")
    return not surum or surum < (6, 8)


def _sycoca() -> None:
    arac = shutil.which("kbuildsycoca6")
    if not arac:
        return
    try:
        subprocess.run([arac, "--noincremental"], stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


def hedefler() -> dict[str, str]:
    """Target paths (XDG_DATA_HOME / XDG_CONFIG_HOME, else ~/.local/share and ~/.config), read at call time."""
    ev = os.path.expanduser("~")
    veri = os.environ.get("XDG_DATA_HOME") or os.path.join(ev, ".local", "share")
    ayar = os.environ.get("XDG_CONFIG_HOME") or os.path.join(ev, ".config")
    uyg = os.path.join(veri, "applications")
    return {"menu": os.path.join(uyg, "deskhand.desktop"),
            "gorev": os.path.join(uyg, "deskhand-gorev.desktop"),
            "goruntu": os.path.join(uyg, "deskhand-goruntu.desktop"),
            "acilis": os.path.join(ayar, "autostart", "deskhand.desktop"),
            "simge": os.path.join(veri, "icons", "hicolor", "scalable", "apps", "deskhand.svg"),
            "sarmalayici": os.path.join(ev, ".local", "bin", "deskhand")}


GIRDILER = ("menu", "gorev", "goruntu", "acilis")


def exec_kacis(s: str) -> str:
    """One program/argument of a desktop entry Exec= key (install.sh desktop_exec): % doubled; with a reserved character
    the word is double-quoted with \\ " ` $ backslash-escaped, and that backslash escaped again (string value)."""
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise KurulumHatasi(_("yol denetim karakteri içeriyor, masaüstü girdisine yazılamaz: {yol}").format(yol=repr(s)))
    s = s.replace("%", "%%")
    if all(c in GUVENLI for c in s):
        return s
    s = s.replace("\\", "\\\\\\\\")  # first: the backslashes added below must not be doubled again
    for c in ('"', "`", "$"):
        s = s.replace(c, "\\\\" + c)
    return f'"{s}"'


def exec_satiri(arg: str) -> str:
    """`<interpreter> -I -m deskhand ARG` (ARG: our own fixed words)."""
    if not os.path.isabs(sys.executable or ""):
        raise KurulumHatasi(_("Python yorumlayıcısının yolu bilinmiyor"))
    bayrak = "-E -P" if _kullanici_sitesi() else "-I"
    return f"{exec_kacis(sys.executable)} {bayrak} -m deskhand {arg}"


def _ice_aktarilabilir() -> bool:
    """Does the Exec command find THIS package (same interpreter and flags, from / instead of the current directory)?
    No: a package run from an unpacked folder or via PYTHONPATH would give a menu entry that cannot start."""
    bayrak = ["-E", "-P"] if _kullanici_sitesi() else ["-I"]
    try:
        r = subprocess.run([sys.executable, *bayrak, "-c", "import deskhand, os; print(os.path.dirname(deskhand.__file__))"],
                           cwd="/", stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and os.path.realpath(r.stdout.strip()) == os.path.realpath(yollar.PAKET_DIZIN)


def _sablon(ad: str, arg: str) -> str:
    """deskhand/data/<ad> with an absolute Exec, without the template comments, plus our markers."""
    satirlar = []
    with open(os.path.join(yollar.PAKET_DIZIN, "data", ad), encoding="utf-8") as f:
        for satir in f.read().splitlines():
            if satir.startswith("#"):
                continue
            if satir.startswith("Exec="):
                satir = "Exec=" + exec_satiri(arg)
            satirlar.append(satir)
    return "\n".join(satirlar + [ISARET, IMZA]) + "\n"


def _goruntu_metni() -> str:
    yardimci = os.path.join(yollar.PAKET_DIZIN, "yardimci", yollar.GORUNTU_AD)
    return ("[Desktop Entry]\nType=Application\nName=Deskhand screenshot helper\n"
            "Comment=Takes screenshots for Deskhand through KWin\n"
            f"Exec={exec_kacis(yardimci)}\nNoDisplay=true\nTerminal=false\n"
            f"X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n{ISARET}\n{IMZA}\n")


def _icerik(yol: str) -> str | None:
    try:
        with open(yol, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def durum(yol: str) -> str:
    """"yok" | "bizim" (IMZA) | "installsh" (install.sh's marker without IMZA) | "yabanci"."""
    if not os.path.lexists(yol):
        return "yok"
    t = _icerik(yol) or ""
    satirlar = t.splitlines()
    if IMZA in satirlar:
        return "bizim"
    return "installsh" if ISARET in satirlar else "yabanci"


def _yaz(yol: str, veri: bytes) -> None:
    dizin = os.path.dirname(yol)
    os.makedirs(dizin, exist_ok=True)
    fd, gecici = tempfile.mkstemp(dir=dizin, prefix=".deskhand-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(veri)
            os.fchmod(f.fileno(), 0o644)
        os.replace(gecici, yol)
    except BaseException:
        try:
            os.unlink(gecici)
        except OSError:
            pass
        raise


def _say(metin: str) -> None:
    print(f"==> {metin}")


def _uyar(metin: str) -> None:
    print(_("UYARI: {metin}").format(metin=metin), file=sys.stderr)


def _installsh_engeli(h: dict[str, str]) -> str | None:
    """Why this must not run (an install.sh install), or None."""
    if _kaynak_kurulumu():
        kok = os.path.dirname(yollar.PAKET_DIZIN)
        return _("Deskhand bir kaynak klasöründen çalışıyor ({kok}): masaüstü girdilerini ./install.sh yazar "
                 "(menü, simge, oturum açılışı); orada ./install.sh çalıştırın.").format(kok=kok)
    if SARMALAYICI_ISARETI in (_icerik(h["sarmalayici"]) or "").splitlines():
        return _("{yol} install.sh kurulumunun komutu: masaüstü girdileri ondan geliyor. pipx kurulumunu kullanacaksanız "
                 "önce kaynak klasöründe ./uninstall.sh çalıştırın, sonra yeniden deneyin.").format(yol=h["sarmalayici"])
    for a in GIRDILER:
        if durum(h[a]) == "installsh":
            return _("{yol} install.sh tarafından yazılmış: masaüstü girdileri zaten var, dokunulmadı. pipx kurulumunu "
                     "kullanacaksanız önce kaynak klasöründe ./uninstall.sh çalıştırın, sonra yeniden "
                     "deneyin.").format(yol=h[a])
    return None


def kur(acilis: bool = True) -> int:
    h = hedefler()
    engel = _installsh_engeli(h)
    if engel:
        print(engel, file=sys.stderr)
        return 1
    if not _ice_aktarilabilir():
        print(_("{py} bu Deskhand paketini ({paket}) kendi başına bulamıyor (paket PYTHONPATH ya da çalışma klasörüyle mi "
                "yükleniyor?): menü girdisi çalışmaz. Deskhand'i pipx ya da pip ile kurup komutu yeniden "
                "çalıştırın.").format(py=sys.executable, paket=yollar.PAKET_DIZIN), file=sys.stderr)
        return 1
    # every text first: a path that cannot be written safely stops the command before any file changes
    metinler = {"menu": _sablon("deskhand.desktop", "panel"),
                "gorev": _sablon("deskhand-gorev.desktop", "panel --gorev")}
    if acilis:
        metinler["acilis"] = _sablon("deskhand.desktop", "panel --tepsi")
    if _eski_kwin():
        metinler["goruntu"] = _goruntu_metni()
    with open(os.path.join(yollar.PAKET_DIZIN, "data", "deskhand.svg"), "rb") as f:
        svg = f.read()
    adlar = {"menu": _("Uygulama menüsü"), "gorev": _("Görev ver kısayolu"),
             "acilis": _("Oturum açılışında panel (tepsi)"), "goruntu": _("Ekran görüntüsü izni (KWin < 6.8)")}
    for a in ("menu", "gorev", "acilis", "goruntu"):
        if a not in metinler:
            continue
        if durum(h[a]) == "yabanci":
            _uyar(_("{yol} bizim değil, dokunulmadı").format(yol=h[a]))
            continue
        _yaz(h[a], metinler[a].encode("utf-8"))
        _say(f"{adlar[a]}: {h[a]}")
    if not acilis:
        if durum(h["acilis"]) == "bizim":
            os.unlink(h["acilis"])
        _say(_("Oturum açılışında panel kapalı (--no-autostart). Onay istekleri için panel açık olmalı: "
               "deskhand panel --tepsi"))
    _yaz(h["simge"], svg)
    _say(_("Simge: {yol}").format(yol=h["simge"]))
    _sycoca()
    _say(_("Bitti. Kaldırmak için: deskhand install-desktop --remove"))
    return 0


def kaldir() -> int:
    h = hedefler()
    for a in GIRDILER:
        d = durum(h[a])
        if d == "bizim":
            os.unlink(h[a])
            _say(_("Kaldırıldı: {yol}").format(yol=h[a]))
        elif d != "yok":
            _uyar(_("{yol} bizim değil, dokunulmadı").format(yol=h[a]))
    try:
        with open(h["simge"], "rb") as a_, open(os.path.join(yollar.PAKET_DIZIN, "data", "deskhand.svg"), "rb") as b:
            ayni = a_.read() == b.read()
    except OSError:
        ayni = None
    if ayni:
        os.unlink(h["simge"])
        _say(_("Kaldırıldı: {yol}").format(yol=h["simge"]))
    elif ayni is False:
        _uyar(_("{yol} paketteki simgeden farklı, dokunulmadı").format(yol=h["simge"]))
    _sycoca()
    return 0


def main(argv: list[str]) -> int:
    """`deskhand install-desktop [--remove] [--no-autostart]` (Turkish: masaustu-kur [--kaldir] [--acilissiz])."""
    from .cli import _Ayristirici, prog_adi
    p = _Ayristirici(prog=f"{prog_adi()} install-desktop", allow_abbrev=False,
                     description=_("pip/pipx kurulumunda menü girdisi, simge ve oturum açılışında panel (install.sh "
                                   "kurulumunda gerekmez)."))
    p.add_argument("--remove", "--kaldir", dest="kaldir", action="store_true",
                   help=_("yalnız bu komutun yazdığı dosyaları sil"))
    p.add_argument("--no-autostart", "--acilissiz", dest="acilissiz", action="store_true",
                   help=_("panel oturum açılışında başlamasın"))
    a = p.parse_args(argv)
    if os.geteuid() == 0:
        print(_("root olarak çalıştırma: masaüstü girdileri kullanıcı başınadır"), file=sys.stderr)
        return 1
    try:
        return kaldir() if a.kaldir else kur(acilis=not a.acilissiz)
    except (KurulumHatasi, OSError) as e:
        print(_("HATA: {hata}").format(hata=e), file=sys.stderr)
        return 1
