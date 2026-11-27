"""Open the user's KDE Wallet at login without a password prompt (Settings: "Open KDE Wallet at login").

Why: with automatic login (no password typed) pam_kwallet5 logs "Empty or missing password, doing nothing", the wallet
stays locked and the first program that needs a secret raises the wallet's password prompt.

How (verified against the sources, kwallet-pam pam_kwallet.c and kwallet src/runtime/ksecretd/main.cpp; there is NO
`pamOpen` on D-Bus: kwalletd6 / ksecretd expose only open(wallet, wId, appid), which prompts):
  pam_kwallet5 derives key = PBKDF2-HMAC-SHA512(password, salt = ~/.local/share/kwalletd/kdewallet.salt (56 bytes),
  50000 rounds, 56 bytes) and starts `ksecretd --pam-login <pipe fd> <listening socket fd>`: ksecretd reads the 56-byte
  key from the pipe, accepts one connection on the socket and reads the session environment from it (KEY=VALUE lines),
  then calls its internal pamOpen(localWallet, key).
This module does the same at login, from a user unit (deskhand-cuzdan-ac.service) that runs before the desktop's
programs: only the KEY is kept (never the password), sealed in the Deskhand kasa (`kde-cuzdan`, systemd-creds with
TPM2 when present; anahtar_deposu.KasaDepo, whatever store is selected for the other secrets).

Rules (review focus 4): ONE attempt, no retry loop, one log line on failure.
  - org.freedesktop.secrets already has an owner: nothing is started; unlocked → "already open"; locked → one warning
    (it was started before this unit; the wallet's own prompt is the only way left). A running ksecretd is never
    stopped or replaced.
  - every D-Bus query uses --auto-start=no: checking never starts ksecretd (which would prompt).
  - a wrong stored key opens nothing: ksecretd stays locked (it prompts only when a program asks), and this reports it.

API (Settings, P2): cuzdan_otomatik_kur(parola) · cuzdan_ac() -> int (0 open/already open, 1 not opened) · kaldir() ·
durum() -> {"kurulu": bool, "acik": bool | None, "neden": str | None}.  CLI: `deskhand wallet open|status|remove`
(setup only from the panel: the password is never an argument).
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time

from .i18n import _

AD = "kde-cuzdan"
TUR_SAYISI = 50000
KARMA_BOYU = 56
TUZ_BOYU = 56
BIRIM = "deskhand-cuzdan-ac.service"
SERVIS = "org.freedesktop.secrets"
_BEKLE_SN = 10.0


class CuzdanHatasi(Exception):
    def __init__(self, neden: str):
        super().__init__(neden)
        self.neden = neden


def _gunluk(satir: str) -> None:
    try:
        from .gunluk import gunluk
        gunluk(satir)
    except Exception:  # noqa: BLE001 - logging must never break the login unit
        pass


def tuz_yolu() -> str:
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "kwalletd", "kdewallet.salt")


def _tuz() -> bytes:
    try:
        with open(tuz_yolu(), "rb") as f:
            t = f.read(TUZ_BOYU + 1)
    except OSError:
        raise CuzdanHatasi(_("KDE Cüzdanı tuz dosyası yok ({yol}); cüzdan bu kullanıcıda oluşturulmamış olabilir")
                           .format(yol=tuz_yolu())) from None
    if len(t) != TUZ_BOYU:
        raise CuzdanHatasi(_("KDE Cüzdanı tuz dosyası beklenen boyda değil"))
    return t


def karma(parola: str, tuz: bytes) -> bytes:
    """kwallet-pam's key: PBKDF2-HMAC-SHA512(password, salt, 50000, 56)."""
    return hashlib.pbkdf2_hmac("sha512", parola.encode("utf-8"), tuz, TUR_SAYISI, KARMA_BOYU)


def _kasa():
    from .anahtar_deposu import KasaDepo, ornek
    if os.environ.get("DESKHAND_ANAHTARLIK") == "kapali":
        from .anahtar_deposu import KapaliDepo
        return KapaliDepo()
    d = ornek("kasa")
    return d if isinstance(d, KasaDepo) or getattr(d, "tur", "") == "kasa" else KasaDepo()


# ---------------------------------------------------------------- D-Bus (busctl, never auto-starting a service)

def _arac(ad: str) -> str | None:
    """A helper's safe absolute path (anahtar_deposu.yardimci_arac: /usr/bin, /bin, root-owned; NEVER PATH, K2-1)."""
    from .anahtar_deposu import yardimci_arac
    return yardimci_arac(ad, zorunlu=False)


def _ortam() -> dict[str, str]:
    from .anahtar_deposu import temiz_ortam
    return temiz_ortam()


def _busctl(*arg: str) -> str | None:
    arac = _arac("busctl")
    if not arac:
        return None
    try:
        r = subprocess.run([arac, "--user", "--auto-start=no", *arg], capture_output=True, text=True, timeout=5,
                           stdin=subprocess.DEVNULL, env=_ortam())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def servis_var() -> bool | None:
    """org.freedesktop.secrets has an owner now (None: unknown)."""
    c = _busctl("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s",
                SERVIS)
    return None if c is None else c == "b true"


def kilitli() -> bool | None:
    """The default collection is locked (None: no owner / unknown). A property read: never a prompt."""
    if not servis_var():
        return None
    c = _busctl("get-property", SERVIS, "/org/freedesktop/secrets/aliases/default", "org.freedesktop.Secret.Collection",
                "Locked")
    return None if c is None else c == "b true"


# ---------------------------------------------------------------- unit

def birim_yolu() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "systemd", "user", BIRIM)


def _birim_tirnak(s: str) -> str:
    """One systemd unit-file word, double-quoted: \\ and " escaped, % (specifiers) and $ (variables) doubled. A
    control character cannot be written safely → CuzdanHatasi."""
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise CuzdanHatasi(_("birim dosyasına yazılamayan yol (denetim karakteri)"))
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def birim_metni() -> str:
    """The login unit. ExecStart is ABSOLUTE and quoted (K2-1/K2-5): the running interpreter + `-m deskhand` with the
    package's own directory on PYTHONPATH; no PATH lookup of `deskhand` (~/.local/bin is writable by any user process)."""
    paket_ust = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isabs(sys.executable or ""):
        raise CuzdanHatasi(_("Python yorumlayıcısının yolu bilinmiyor"))
    komut = f"{_birim_tirnak(sys.executable)} -m deskhand wallet open"
    return ("[Unit]\n"
            "Description=Deskhand: open KDE Wallet at login (sealed key, no prompt)\n"
            "PartOf=graphical-session.target\n"
            "After=plasma-kwin_wayland.service\n"
            "Before=plasma-plasmashell.service plasma-kded6.service plasma-kwallet-pam.service "
            "plasma-xdg-desktop-portal-kde.service xdg-desktop-portal.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"Environment={_birim_tirnak('PYTHONPATH=' + paket_ust)}\n"
            f"ExecStart={komut}\n"
            "TimeoutStartSec=30\n"
            "KillMode=process\n\n"
            "[Install]\n"
            "WantedBy=graphical-session.target\n")


def _systemctl(*arg: str) -> bool:
    arac = _arac("systemctl")
    if not arac:
        return False
    try:
        return subprocess.run([arac, "--user", *arg], capture_output=True, timeout=30,
                              stdin=subprocess.DEVNULL, env=_ortam()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _birim_kur() -> None:
    yol = birim_yolu()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    fd, gecici = tempfile.mkstemp(dir=os.path.dirname(yol), prefix=".deskhand-cuzdan-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(birim_metni())
    os.replace(gecici, yol)
    _systemctl("daemon-reload")
    if not _systemctl("enable", BIRIM):
        raise CuzdanHatasi(_("kullanıcı birimi etkinleştirilemedi ({birim})").format(birim=BIRIM))


# ---------------------------------------------------------------- API

def cuzdan_otomatik_kur(parola: str) -> None:
    """Settings: seal the wallet KEY derived from `parola` (never the password itself) in the kasa and enable the login
    unit. The password cannot be checked here without opening the wallet (no API); a wrong one shows up at the next
    login as "not opened" (durum / doctor)."""
    from .anahtar_deposu import DepoHatasi
    if not isinstance(parola, str) or not parola:
        raise CuzdanHatasi(_("boş parola kaydedilmez"))
    try:
        _kasa().yaz(AD, karma(parola, _tuz()))
    except DepoHatasi as e:
        raise CuzdanHatasi(e.neden) from None
    _birim_kur()
    _gunluk("cüzdan: girişte otomatik açma kuruldu")


def kaldir() -> None:
    """Settings: disable the login unit and delete the sealed key. Missing pieces are not an error."""
    _systemctl("disable", BIRIM)
    try:
        os.unlink(birim_yolu())
    except FileNotFoundError:
        pass
    _systemctl("daemon-reload")
    from .anahtar_deposu import DepoHatasi
    try:
        _kasa().sil(AD)
    except DepoHatasi:
        pass
    _gunluk("cüzdan: girişte otomatik açma kaldırıldı")


def durum() -> dict:
    """{"kurulu": the sealed key and the unit exist, "acik": wallet unlocked (None: no Secret Service running /
    unknown), "neden": why it is not usable (None: fine)}. Starts nothing."""
    from .anahtar_deposu import DepoHatasi
    neden = None
    try:
        anahtar_var = AD in _kasa().tum_adlar()
    except DepoHatasi as e:
        anahtar_var, neden = False, e.neden
    kurulu = anahtar_var and os.path.exists(birim_yolu())
    k = kilitli()
    acik = None if k is None else not k
    if neden is None and kurulu and acik is False:
        neden = _("cüzdan kilitli: kayıtlı anahtar açmadı ya da cüzdan bu birimden önce başlatıldı")
    return {"kurulu": kurulu, "acik": acik, "neden": neden}


def _ksecretd() -> str:
    """ksecretd from /usr/bin or /bin only (root-owned chain): it receives the wallet KEY (K2-1)."""
    yol = _arac("ksecretd")
    if yol:
        return yol
    raise CuzdanHatasi(_("ksecretd bulunamadı (KDE Cüzdanı 6 gerekir)"))


# what ksecretd needs from the session (kwallet-pam sends its whole PAM environment; Deskhand only these, K2-4)
_SOKET_ORTAMI = ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "HOME", "USER", "LOGNAME",
                 "LANG", "LANGUAGE")


def soket_ortami() -> dict[str, str]:
    """The session environment ksecretd gets on the socket: XDG_*, LC_*, the names above and PATH=/usr/bin:/bin."""
    from .arka_ortak import GUVENLI_PATH
    ortam = {k: v for k, v in os.environ.items()
             if (k in _SOKET_ORTAMI or k.startswith(("XDG_", "LC_"))) and "\n" not in k + v and "=" not in k}
    ortam["PATH"] = GUVENLI_PATH
    return ortam


def _calisma_dizini() -> str:
    """XDG_RUNTIME_DIR: set, absolute, a real directory of this user, 0700. Otherwise REFUSED (K2-3: no /tmp fallback,
    where the socket name is predictable)."""
    import stat as _stat
    d = os.environ.get("XDG_RUNTIME_DIR") or ""
    try:
        st = os.lstat(d) if os.path.isabs(d) else None
    except OSError:
        st = None
    if st is None or not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or _stat.S_IMODE(st.st_mode) & 0o077:
        raise CuzdanHatasi(_("XDG_RUNTIME_DIR yok ya da güvenli değil; cüzdan açılmadı"))
    return d


def _baslat(anahtar: bytes) -> None:
    """kwallet-pam's protocol: `ksecretd --pam-login <pipe> <socket>`; key on the pipe, environment on the socket."""
    calisma = _calisma_dizini()
    ksecretd = _ksecretd()
    soket_yolu = os.path.join(calisma, f"deskhand-kwallet-{os.getpid()}.socket")
    try:
        os.unlink(soket_yolu)
    except FileNotFoundError:
        pass
    dinle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    oku_fd, yaz_fd = os.pipe()
    try:
        eski = os.umask(0o077)
        try:
            dinle.bind(soket_yolu)
        finally:
            os.umask(eski)
        dinle.listen(1)
        from .anahtar_deposu import SINAMA_ORTAM_ADLARI
        sok = soket_ortami()
        surec_ortami = {**sok, **{k: os.environ[k] for k in SINAMA_ORTAM_ADLARI if k in os.environ}}
        subprocess.Popen([ksecretd, "--pam-login", str(oku_fd), str(dinle.fileno())],
                         pass_fds=(oku_fd, dinle.fileno()), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, env=surec_ortami)
        os.close(oku_fd)
        oku_fd = -1
        yazilan = 0
        while yazilan < len(anahtar):
            yazilan += os.write(yaz_fd, anahtar[yazilan:])
        os.close(yaz_fd)
        yaz_fd = -1
        ortam = "".join(f"{k}={v}\n" for k, v in sok.items())
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(_BEKLE_SN)
            s.connect(soket_yolu)
            s.sendall(ortam.encode("utf-8", "surrogateescape"))
    finally:
        for fd in (oku_fd, yaz_fd):
            if fd >= 0:
                os.close(fd)
        dinle.close()
        try:
            os.unlink(soket_yolu)
        except OSError:
            pass


def cuzdan_ac() -> int:
    """Login unit / `deskhand wallet open`: ONE attempt. → 0 the wallet is open (now or already), 1 not opened (one
    log line with the reason; never a retry)."""
    from .anahtar_deposu import DepoHatasi
    var = servis_var()
    if var is None:
        _gunluk("cüzdan: açılmadı: oturum veri yolu sorgulanamadı")
        return 1
    if var:
        k = kilitli()
        if k is False:
            return 0
        _gunluk("cüzdan: açılmadı: Secret Service bu birimden önce başlatılmış ve kilitli (yeniden başlatılmaz)")
        return 1
    try:
        anahtar = _kasa().oku(AD)
    except DepoHatasi as e:
        _gunluk(f"cüzdan: açılmadı: {e.neden}")
        return 1
    if anahtar is None or len(anahtar) != KARMA_BOYU:
        _gunluk("cüzdan: açılmadı: kayıtlı anahtar yok (Ayarlar → Girişte KDE Cüzdanı'nı aç)")
        return 1
    try:
        _baslat(anahtar)
    except (OSError, CuzdanHatasi) as e:
        _gunluk(f"cüzdan: açılmadı: {getattr(e, 'neden', None) or type(e).__name__}")
        return 1
    son = time.monotonic() + _BEKLE_SN
    while time.monotonic() < son:  # bounded wait for ksecretd to take the bus name (one attempt, no restart)
        k = kilitli()
        if k is False:
            _gunluk("cüzdan: girişte açıldı")
            return 0
        if k is True:
            break
        time.sleep(0.2)
    _gunluk("cüzdan: açılmadı: kayıtlı anahtar cüzdanı açmadı (parola değişmiş olabilir; Ayarlar'dan yeniden girin)")
    return 1


def main(argv: list[str]) -> int:
    """`deskhand wallet open|status|remove` (setup only from Settings: the password is never an argument)."""
    import json
    islem = argv[0] if argv else "status"
    if islem == "open":
        return cuzdan_ac()
    if islem == "status":
        print(json.dumps(durum(), ensure_ascii=False))
        return 0
    if islem == "remove":
        kaldir()
        return 0
    print(_("kullanım: deskhand wallet open|status|remove (kurulum: panel Ayarlar)"), file=sys.stderr)
    return 1
