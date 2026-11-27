"""Key store (anahtar deposu): ONE interface for every secret Deskhand keeps, with two back ends the user picks in
Settings (`[anahtar] depo` in ayarlar.toml).

  kasa    (default for a new install) a sealed file per item under DATA_DIR/kasa/ (directory 0700, `<ad>.cred` 0600,
          atomic replace), sealed by `systemd-creds --user encrypt --with-key=auto` (host key + TPM2 when the machine
          has one, else the host key; user-scoped: another user cannot open it, another machine cannot open it).
          The value goes through stdin/stdout only, never argv. NO D-Bus and NO Secret Service call at all: a locked
          KDE Wallet never shows a password prompt because of Deskhand.
  cuzdan  the user's Secret Service (org.freedesktop.secrets: KDE Wallet / GNOME Keyring) through secretstorage, as
          before this module (oturum/kalici.py GizliServis). Never unlocks (no prompt from the background).

Items: internal ones (IC_ADLAR: the panel's signed state, the persistent-session key, the sealed KDE Wallet password of
cuzdan_ac.py) and the user's named secrets (`deskhand secret set <ad>`, Settings "Saved passwords"; `type --secret-ref`).
`listele()` returns only the user's names; an internal name cannot be set or removed from the CLI.

Errors: `DepoHatasi(neden)` = the store cannot answer (locked wallet, no systemd-creds, a seal that does not open). It is
NEVER "no item": `oku` answers None only when the store definitely has no such item. Callers fail closed on DepoHatasi
(liste_koruma: no signed state, not a first start; kalici: nothing saved or applied).

Selection: `secili_tur()`: the selection sealed in the kasa by depo_degistir wins (a disagreeing `[anahtar] depo` is
closed-fail); else `[anahtar] depo`; else a store that already has kasa items → kasa; earlier panel marks (an install
that used the wallet) → cuzdan (nothing changes until the user switches in Settings); otherwise (a new install) → kasa. `depo_degistir(yeni)` (panel only, after the user's Yes) copies
every item from the old store to the new one FIRST and only then writes the setting, so the signed panel state stays
valid. A changed setting with no copy (a hand edit) finds no signed state while marks exist: closed-fail, never a first
start (liste_koruma.ilk_kurulum).

Threat model (honest, docs/ARCHITECTURE.md §4): a process that only writes files cannot read the sealed items or make a
valid seal by copying files. Code running as the same user that DELIBERATELY runs `systemd-creds --user decrypt|encrypt`
can read and forge kasa items, exactly like same-user code that talks to an unlocked wallet: out of scope (it needs the
agent shell isolated from the user's credentials). Deleting the kasa items AND every panel mark AND both list files AND
the anchor record (STATE_DIR/panel-nesil.kayit, liste_koruma.capa_kaydi_yolu; K2-2) makes the next panel start a first
start (the default lists, DUR off; Settings says so next to the kasa); removing only some of them is closed-fail.
ROLLBACK (security review 27 Kas, finding 2): a file-writing process can copy a sealed item and put the OLDER copy back
later (with the wallet this needed D-Bus). The panel's state carries a generation (liste_koruma `nesil`, +1 per write);
a process that has seen a newer generation treats an older one (or one without a generation) as rolled back
(closed-fail: the user's DUR stays on, no approved value); the newest generation is also kept in a SEPARATE sealed
item "panel-nesil" (written after the state; unreadable → closed-fail), so a new process catches a rollback of the
state item alone. Putting back the old state item AND the old anchor AND the old marks while NO Deskhand process
runs is NOT detected: user space has no
anchor a same-user process cannot rewind (TPM NV counters need the tss group + tpm2-tools; this user has neither).
Who needs that guarantee keeps the KDE Wallet store. Selection (finding 3): the selection is sealed in the kasa
(`depo-secimi`); `[anahtar] depo` that disagrees → closed-fail (SecimsizDepo); depo_degistir removes the panel state
from the old store, so switching the setting back by hand finds nothing to replay.

DESKHAND_ANAHTARLIK=kapali (tests/_yalitim.py): `secili_depo()` is a store that refuses everything (never the real
wallet, never the real TPM); tests build KasaDepo with a fake systemd-creds
given in SINAMA_ARACLARI (in-process; never PATH).
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import threading

from . import yollar
from .i18n import N_, _

TURLER = ("kasa", "cuzdan")
VARSAYILAN_TUR = "kasa"
AYAR_BOLUM, AYAR_ANAHTAR = "anahtar", "depo"
TUR_ADLARI = {"kasa": N_("Deskhand kasası"), "cuzdan": N_("KDE Cüzdanı")}

# internal items: name → (Secret Service label, content type); the purpose attribute is the name itself
IC_ADLAR = {
    "panel-isaret": ("Deskhand panel settings", "application/json"),
    "kalici-oturum": ("Deskhand session store", "application/octet-stream"),
    "kde-cuzdan": ("Deskhand KDE Wallet unlock", "application/octet-stream"),
    "depo-secimi": ("Deskhand key store selection", "text/plain"),
    "panel-nesil": ("Deskhand panel settings generation", "text/plain"),
}
KASA_SABIT = ("kde-cuzdan", "depo-secimi")  # always in the kasa, never moved by depo_degistir
SECIM_AD = "depo-secimi"
_AD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_UZANTI = ".cred"
_AZAMI = 64 * 1024          # a sealed item larger than this is not read; a value larger than this is not written
_SURE = 30                  # seconds for one systemd-creds call (TPM operations take well under a second)
_UYGULAMA = "deskhand"


class DepoHatasi(Exception):
    """The store cannot answer (it is NOT "no item"). `neden` is a short, translated, value-free reason.
    `yok_kesin`: the back end is definitely absent (no systemd-creds / no Secret Service), not merely unreadable."""

    def __init__(self, neden: str, yok_kesin: bool = False):
        super().__init__(neden)
        self.neden = neden
        self.yok_kesin = yok_kesin


def ad_gecerli(ad) -> bool:
    return isinstance(ad, str) and bool(_AD.fullmatch(ad)) and not ad.endswith(".")


def _ad_denetle(ad) -> str:
    if not ad_gecerli(ad):
        raise ValueError(_("geçersiz ad: harf, rakam, '.', '_' ya da '-' (en çok 64 karakter)"))
    return ad


def kullanici_adi_mi(ad) -> bool:
    """A name the user may set / remove / type (an internal item is not one)."""
    return ad_gecerli(ad) and ad not in IC_ADLAR


class Depo:
    """Interface. oku(ad) -> bytes | None (None = definitely no item) · yaz(ad, veri) · sil(ad) -> bool ·
    listele() -> list[str] (the user's names) · durum() -> {"tur", "hazir", "neden", "tpm"}. Errors: DepoHatasi."""

    tur = ""

    def oku(self, ad: str) -> bytes | None:
        raise NotImplementedError

    def yaz(self, ad: str, veri: bytes) -> None:
        raise NotImplementedError

    def sil(self, ad: str) -> bool:
        raise NotImplementedError

    def listele(self) -> list[str]:
        raise NotImplementedError

    def tum_adlar(self) -> list[str]:
        """Every item name, internal ones included (depo_degistir copies them all)."""
        return self.listele()

    def durum(self) -> dict:
        raise NotImplementedError

    def servis_yok_kesin(self) -> bool:
        """True ONLY when the back end is definitely absent (liste_koruma: the panel may then ask "run unsigned?")."""
        return False


# ---------------------------------------------------------------- helper programs (security review K2-1)

# Every helper this module and cuzdan_ac.py run (systemd-creds, busctl, ksecretd, systemctl, kcmshell6, kwalletmanager)
# is found ONLY through arka_ortak.arac: /usr/bin or /bin, the file and every parent root-owned and not writable by
# others. NEVER through PATH: its head is the user's writable ~/.local/bin, where a fake systemd-creds received every
# password on stdin and a fake ksecretd the wallet key (K2 review, finding 1). The children get a CLEAN environment.
# Tests only, in-process: name → absolute path of a fake helper (None: "not installed"). Never read from the environment
# or a file, so nothing outside this process can set it.
SINAMA_ARACLARI: dict[str, str | None] = {}
SINAMA_ORTAM_ADLARI: tuple[str, ...] = ()  # tests only, in-process: extra variables the fakes read
_ORTAM_ADLARI = ("HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


def yardimci_arac(ad: str, zorunlu: bool = True) -> str | None:
    """The SAFE absolute path of helper `ad` (arka_ortak.arac: /usr/bin, /bin, root-owned chain). Missing or unsafe:
    zorunlu → DepoHatasi(yok_kesin=True), else None. Never a PATH lookup."""
    if ad in SINAMA_ARACLARI:
        yol = SINAMA_ARACLARI[ad]
    else:
        from .arka_ortak import arac
        yol = arac(ad, zorunlu=False)
    if yol is None and zorunlu:
        raise DepoHatasi(_("güvenli araç bulunamadı: {ad} (yalnız /usr/bin ve /bin, root'a ait)").format(ad=ad),
                         yok_kesin=True)
    return yol


def temiz_ortam(ekler: tuple[str, ...] = ()) -> dict[str, str]:
    """A clean environment for a helper: PATH=/usr/bin:/bin plus only HOME, USER, LOGNAME, LANG(UAGE), LC_*,
    XDG_RUNTIME_DIR, DBUS_SESSION_BUS_ADDRESS and the names in `ekler` (no LD_*, PYTHON*, SYSTEMD_*, ... of the caller)."""
    from .arka_ortak import GUVENLI_PATH
    adlar = set(_ORTAM_ADLARI) | set(ekler) | set(SINAMA_ORTAM_ADLARI)
    ortam = {k: v for k, v in os.environ.items() if k in adlar or (k.startswith("LC_") and k.isupper())}
    ortam["PATH"] = GUVENLI_PATH
    return ortam


# ---------------------------------------------------------------- kasa (systemd-creds)

_TPM: bool | None = None


def tpm_var() -> bool:
    """`systemd-creds has-tpm2` (cached; no TPM operation)."""
    global _TPM
    if _TPM is None:
        arac = yardimci_arac("systemd-creds", zorunlu=False)
        if not arac:
            return False
        try:
            _TPM = subprocess.run([arac, "has-tpm2", "-q"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=_SURE, env=temiz_ortam()).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _TPM = False
    return _TPM


def _hata_satiri(stderr: bytes) -> str:
    """The first line of systemd-creds' error (it never contains the value: the value travels on stdin/stdout)."""
    s = (stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return s[0][:160] if s else ""


class KasaDepo(Depo):
    tur = "kasa"
    ANAHTAR = "auto"  # user scope: host+tpm2 when a TPM2 exists, else host (systemd-creds --user refuses plain tpm2)

    def __init__(self, dizin: str | None = None):
        self._dizin = dizin
        self._onbellek: dict[str, tuple[tuple, bytes]] = {}  # ad → ((dev, ino, size, mtime_ns), plaintext)
        self._kilit = threading.RLock()

    @property
    def dizin(self) -> str:
        return self._dizin or os.path.join(yollar.data_dir(), "kasa")

    def _arac(self) -> str:
        arac = yardimci_arac("systemd-creds", zorunlu=False)
        if not arac:
            raise DepoHatasi(_("systemd-creds bulunamadı (systemd 256+ gerekir); Ayarlar'dan KDE Cüzdanı seçilebilir"),
                             yok_kesin=True)
        return arac

    def _calistir(self, argv: list[str], girdi: bytes) -> bytes:
        try:
            r = subprocess.run([self._arac(), "--user", *argv], input=girdi, capture_output=True, timeout=_SURE,
                               env=temiz_ortam())
        except subprocess.TimeoutExpired:
            raise DepoHatasi(_("systemd-creds yanıt vermedi")) from None
        except OSError:
            raise DepoHatasi(_("systemd-creds çalıştırılamadı")) from None
        if r.returncode != 0:
            raise DepoHatasi(_("systemd-creds hatası: {hata}").format(hata=_hata_satiri(r.stderr) or r.returncode))
        return r.stdout

    def _dizin_hazir(self, olustur: bool) -> bool:
        """The store directory is ours, a real directory and 0700 (created when olustur). False: it does not exist."""
        d = self.dizin
        if olustur:
            os.makedirs(os.path.dirname(d), mode=0o700, exist_ok=True)
            try:
                os.mkdir(d, 0o700)
            except FileExistsError:
                pass
        try:
            st = os.lstat(d)
        except FileNotFoundError:
            return False
        except OSError:
            raise DepoHatasi(_("kasa dizini okunamadı")) from None
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise DepoHatasi(_("kasa dizini güvenli değil (dizin değil ya da başka kullanıcının)"))
        if stat.S_IMODE(st.st_mode) & 0o077:
            try:
                os.chmod(d, 0o700)
            except OSError:
                raise DepoHatasi(_("kasa dizini güvenli değil (izinler düzeltilemedi)")) from None
        return True

    def _yol(self, ad: str) -> str:
        return os.path.join(self.dizin, _ad_denetle(ad) + _UZANTI)

    def oku(self, ad: str) -> bytes | None:
        yol = self._yol(ad)
        with self._kilit:
            if not self._dizin_hazir(False):
                return None
            try:
                fd = os.open(yol, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            except FileNotFoundError:
                self._onbellek.pop(ad, None)
                return None
            except OSError:
                raise DepoHatasi(_("kasa öğesi okunamadı ({ad})").format(ad=ad)) from None
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_size > _AZAMI:
                    raise DepoHatasi(_("kasa öğesi güvenli değil ({ad})").format(ad=ad))
                imza = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
                eski = self._onbellek.get(ad)
                if eski is not None and eski[0] == imza:
                    return eski[1]  # the same sealed file: no TPM operation per poll
                with os.fdopen(os.dup(fd), "rb") as f:
                    muhur = f.read(_AZAMI + 1)
            finally:
                os.close(fd)
            try:
                veri = self._calistir([f"--name={ad}", "decrypt", "-", "-"], muhur)
            except DepoHatasi as e:
                if e.yok_kesin:
                    raise
                raise DepoHatasi(_("kasa öğesi açılamadı ({ad}): mühür bozuk ya da başka bir makinede/kullanıcıda "
                                   "oluşturulmuş; Ayarlar'dan parolayı yeniden girin ya da KDE Cüzdanı'nı seçin")
                                 .format(ad=ad)) from None
            self._onbellek[ad] = (imza, veri)
            return veri

    def yaz(self, ad: str, veri: bytes) -> None:
        yol = self._yol(ad)
        veri = bytes(veri)
        if len(veri) > _AZAMI:
            raise DepoHatasi(_("değer çok büyük"))
        with self._kilit:
            self._dizin_hazir(True)
            muhur = self._calistir([f"--name={ad}", f"--with-key={self.ANAHTAR}", "encrypt", "-", "-"], veri)
            if not muhur:
                raise DepoHatasi(_("systemd-creds boş çıktı verdi"))
            fd, gecici = tempfile.mkstemp(dir=self.dizin, prefix=f".{ad}.", suffix=".yeni")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(muhur)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(gecici, yol)
            except BaseException:
                try:
                    os.unlink(gecici)
                except OSError:
                    pass
                raise
            self._onbellek.pop(ad, None)

    def sil(self, ad: str) -> bool:
        yol = self._yol(ad)
        with self._kilit:
            self._onbellek.pop(ad, None)
            try:
                os.unlink(yol)
            except FileNotFoundError:
                return False
            except OSError:
                raise DepoHatasi(_("kasa öğesi silinemedi ({ad})").format(ad=ad)) from None
            return True

    def _adlar(self) -> list[str]:
        if not self._dizin_hazir(False):
            return []
        try:
            adlar = os.listdir(self.dizin)
        except OSError:
            raise DepoHatasi(_("kasa dizini okunamadı")) from None
        return sorted(a[:-len(_UZANTI)] for a in adlar if a.endswith(_UZANTI) and ad_gecerli(a[:-len(_UZANTI)]))

    def listele(self) -> list[str]:
        return [a for a in self._adlar() if a not in IC_ADLAR]

    def tum_adlar(self) -> list[str]:
        return self._adlar()

    def servis_yok_kesin(self) -> bool:
        return yardimci_arac("systemd-creds", zorunlu=False) is None

    def durum(self) -> dict:
        neden = None
        try:
            self._arac()
            self._dizin_hazir(False)
        except DepoHatasi as e:
            neden = e.neden
        return {"tur": self.tur, "hazir": neden is None, "neden": neden, "tpm": tpm_var()}


# ---------------------------------------------------------------- cuzdan (Secret Service)

class CuzdanDepo(Depo):
    """Items with attributes application=deskhand, purpose=<internal name> (the attributes the earlier releases used),
    or purpose=sir, ad=<name> for the user's secrets. Never unlocks, never creates a collection."""

    tur = "cuzdan"
    _baglanti = None  # the reused D-Bus connection of servis_yok_kesin (review INC6 D5)

    @staticmethod
    def _oznitelik(ad: str) -> dict:
        _ad_denetle(ad)
        if ad in IC_ADLAR:
            return {"application": _UYGULAMA, "purpose": ad}
        return {"application": _UYGULAMA, "purpose": "sir", "ad": ad}

    @staticmethod
    def _modul():
        try:
            import secretstorage
            from secretstorage.exceptions import SecretStorageException
        except ImportError:
            raise DepoHatasi(_("python-secretstorage kurulu değil"), yok_kesin=True) from None
        return secretstorage, SecretStorageException

    def _koleksiyon_ile(self, is_):
        ss, ss_hata = self._modul()
        try:
            baglanti = ss.dbus_init()
        except Exception:  # noqa: BLE001 - no session bus
            raise DepoHatasi(_("Secret Service'e bağlanılamadı (oturum veri yolu yok)")) from None
        try:
            try:
                koleksiyon = ss.Collection(baglanti)  # the default collection; never created here
            except ss_hata:
                raise DepoHatasi(_("Secret Service yok ya da varsayılan cüzdan yok (KDE Cüzdanı)")) from None
            if koleksiyon.is_locked():
                raise DepoHatasi(_("cüzdan kilitli"))
            return is_(koleksiyon)
        except DepoHatasi:
            raise
        except Exception:  # noqa: BLE001 - D-Bus / service errors: closed-fail (the message may carry no secret)
            raise DepoHatasi(_("anahtar okunamadı (Secret Service hatası)")) from None
        finally:
            try:
                baglanti.close()
            except Exception:  # noqa: BLE001
                pass

    def oku(self, ad: str) -> bytes | None:
        oz = self._oznitelik(ad)

        def is_(k):
            for oge in k.search_items(oz):
                if oge.is_locked():
                    raise DepoHatasi(_("cüzdan kilitli"))
                s = bytes(oge.get_secret())
                if s:
                    return s
            return None
        return self._koleksiyon_ile(is_)

    def yaz(self, ad: str, veri: bytes) -> None:
        oz = self._oznitelik(ad)
        etiket, tur = IC_ADLAR.get(ad, (f"Deskhand: {ad}", "application/octet-stream"))
        self._koleksiyon_ile(lambda k: k.create_item(etiket, oz, bytes(veri), replace=True, content_type=tur))

    def sil(self, ad: str) -> bool:
        oz = self._oznitelik(ad)

        def is_(k):
            n = 0
            for oge in k.search_items(oz):
                oge.delete()
                n += 1
            return n > 0
        return self._koleksiyon_ile(is_)

    def _adlar(self, kullanici: bool) -> list[str]:
        def is_(k):
            adlar = set()
            for oge in k.search_items({"application": _UYGULAMA}):
                oz = oge.get_attributes()
                ad = oz.get("ad") if oz.get("purpose") == "sir" else oz.get("purpose")
                if ad_gecerli(ad) and (ad in IC_ADLAR) != kullanici and (oz.get("purpose") == "sir") == kullanici:
                    adlar.add(ad)
            return sorted(adlar)
        return self._koleksiyon_ile(is_)

    def listele(self) -> list[str]:
        return self._adlar(True)

    def tum_adlar(self) -> list[str]:
        return self._adlar(False) + self._adlar(True)

    def servis_yok_kesin(self) -> bool:
        """True ONLY when there is definitely no Secret Service: python-secretstorage is not installed, or the session
        bus answers that org.freedesktop.secrets is neither running nor activatable. A locked wallet, no session bus and
        D-Bus errors are NOT "absent" (closed-fail)."""
        try:
            import secretstorage
        except ImportError:
            return True
        if self._baglanti is None:  # ONE session-bus connection for every poll (review INC6 D5)
            try:
                self._baglanti = secretstorage.dbus_init()
            except Exception:  # noqa: BLE001 - no session bus: unknown, not absent
                return False
        try:
            return not secretstorage.check_service_availability(self._baglanti)
        except Exception:  # noqa: BLE001 - unknown; a broken connection is opened again next time
            b, self._baglanti = self._baglanti, None
            try:
                b.close()
            except Exception:  # noqa: BLE001
                pass
            return False

    def durum(self) -> dict:
        neden = None
        try:
            self._koleksiyon_ile(lambda k: None)
        except DepoHatasi as e:
            neden = e.neden
        return {"tur": self.tur, "hazir": neden is None, "neden": neden, "tpm": tpm_var()}


class KapaliDepo(Depo):
    """DESKHAND_ANAHTARLIK=kapali (tests): refuses everything; never the real wallet or the real TPM."""

    tur = "kapali"
    NEDEN = N_("anahtarlık kapalı (DESKHAND_ANAHTARLIK=kapali)")

    def _ret(self):
        raise DepoHatasi(_(self.NEDEN))

    def oku(self, ad: str) -> bytes | None:
        self._ret()

    def yaz(self, ad: str, veri: bytes) -> None:
        self._ret()

    def sil(self, ad: str) -> bool:
        self._ret()
        return False

    def listele(self) -> list[str]:
        self._ret()
        return []

    def durum(self) -> dict:
        return {"tur": self.tur, "hazir": False, "neden": _(self.NEDEN), "tpm": False}


# ---------------------------------------------------------------- selection

_ORNEKLER: dict[str, Depo] = {}
_SECIM_KILIT = threading.RLock()


def _kapali() -> bool:
    return os.environ.get("DESKHAND_ANAHTARLIK") == "kapali"


def ornek(tur: str) -> Depo:
    """The (cached) store object of `tur` (the reused D-Bus connection and the kasa cache live in it)."""
    if tur not in TURLER:
        raise ValueError(tur)
    with _SECIM_KILIT:
        if tur not in _ORNEKLER:
            _ORNEKLER[tur] = KasaDepo() if tur == "kasa" else CuzdanDepo()
        return _ORNEKLER[tur]


def ornek_ayarla(tur: str, nesne: Depo | None) -> None:
    """Tests: replace the store object of `tur` (None: back to the real one)."""
    with _SECIM_KILIT:
        if nesne is None:
            _ORNEKLER.pop(tur, None)
        else:
            _ORNEKLER[tur] = nesne


def _ayardaki_tur() -> str | None:
    from . import ayarlar
    bolum = ayarlar.ham_oku().get(AYAR_BOLUM)
    deger = bolum.get(AYAR_ANAHTAR) if isinstance(bolum, dict) else None
    return deger if deger in TURLER else None


def _varsayilan_tur() -> str:
    """No selection at all: kasa items → kasa; panel marks (the wallet was in use before this release) → cuzdan; a new
    install → kasa. Reads files only (no D-Bus). Persistent-session records do NOT select a store (review: a file a
    process can create must not choose the store)."""
    try:
        if KasaDepo().tum_adlar():
            return "kasa"
    except DepoHatasi:
        return "kasa"  # an unsafe kasa directory exists: kasa (it refuses; closed-fail)
    from . import liste_koruma
    if liste_koruma.isaret_gecmisi():
        return "cuzdan"
    return VARSAYILAN_TUR


class SecimHatasi(DepoHatasi):
    """The sealed selection and `[anahtar] depo` disagree, or the sealed selection cannot be read: closed-fail."""


def _muhurlu_secim() -> str | None:
    """The selection sealed in the kasa by depo_degistir (None: never sealed). A seal that does not open → SecimHatasi.
    A process that only writes files cannot make one; it can delete it (then the setting decides and a store without
    the panel's item is closed-fail while marks exist) or put an older one back (then it disagrees with the setting
    written at the same time, or names a store whose panel item depo_degistir removed: closed-fail)."""
    k = ornek("kasa")
    try:
        if SECIM_AD not in k.tum_adlar():
            return None
        v = k.oku(SECIM_AD)
    except DepoHatasi as e:
        raise SecimHatasi(_("anahtar deposu seçimi doğrulanamadı: {neden}").format(neden=e.neden)) from None
    t = (v or b"").decode("ascii", "replace")
    if t not in TURLER:
        raise SecimHatasi(_("anahtar deposu seçimi bozuk"))
    return t


def secili_tur() -> str:
    """The selected store. The kasa-sealed selection wins; `[anahtar] depo` that disagrees with it → SecimHatasi
    (closed-fail: a hand edit of ayarlar.toml cannot switch the store). No sealed selection: the setting, else the
    default (_varsayilan_tur)."""
    muhurlu = _muhurlu_secim()
    ayar = _ayardaki_tur()
    if muhurlu is not None:
        if ayar is not None and ayar != muhurlu:
            raise SecimHatasi(_("anahtar deposu ayarı ({ayar}) mühürlü seçimle ({secim}) uyuşmuyor; ayar dosyası "
                                "panel dışında değişmiş. Ayarlar'dan depoyu yeniden seçin").format(ayar=ayar,
                                                                                                  secim=muhurlu))
        return muhurlu
    return ayar or _varsayilan_tur()


class SecimsizDepo(Depo):
    """The selection is not verified (SecimHatasi): every call refuses with that reason (closed-fail)."""

    tur = "dogrulanamadi"

    def __init__(self, neden: str):
        self.neden = neden

    def _ret(self):
        raise DepoHatasi(self.neden)

    def oku(self, ad: str) -> bytes | None:
        self._ret()

    def yaz(self, ad: str, veri: bytes) -> None:
        self._ret()

    def sil(self, ad: str) -> bool:
        self._ret()
        return False

    def listele(self) -> list[str]:
        self._ret()
        return []

    def durum(self) -> dict:
        return {"tur": self.tur, "hazir": False, "neden": self.neden, "tpm": tpm_var()}


def secili_depo() -> Depo:
    """The store the user selected. Under DESKHAND_ANAHTARLIK=kapali: a store that refuses. A selection that is not
    verified (SecimHatasi): a store that refuses with the reason."""
    if _kapali():
        return KapaliDepo()
    try:
        return ornek(secili_tur())
    except SecimHatasi as e:
        return SecimsizDepo(e.neden)


def _ayar_yaz(tur: str) -> None:
    from . import ayarlar
    ham = ayarlar.ham_oku()
    bolum = ham.get(AYAR_BOLUM)
    ham[AYAR_BOLUM] = {**(bolum if isinstance(bolum, dict) else {}), AYAR_ANAHTAR: tur}
    ayarlar.yaz(ham)


def depo_degistir(yeni_tur: str, tasima: bool = True) -> dict:
    """Panel only, after the user's Yes: switch the store. Every item of the old store (internal + the user's; not the
    kasa-only ones, KASA_SABIT) is copied to the new one FIRST and read back (so the panel's signed state and its marks
    stay valid); then the selection is SEALED in the kasa (`depo-secimi`) and `[anahtar] depo` is written; then the
    panel's signed state and the session key are deleted from the OLD store (a later hand switch back finds no stale
    state to replay: closed-fail). The user's named secrets stay in the old store as well.
    → {"tur": yeni_tur, "tasinan": [names], "atlanan": [names]}.
    The old store cannot be read (locked wallet, broken seal) → DepoHatasi and NOTHING changes; tasima=False switches
    without copying (the panel then has no signed state: closed-fail, the user approves the lists again). A selection
    that is not verified (SecimHatasi) is replaced by the user's choice here (the user's Yes in the panel)."""
    if yeni_tur not in TURLER:
        raise ValueError(_("bilinmeyen depo: {tur}").format(tur=yeni_tur))
    if _kapali():
        raise DepoHatasi(_(KapaliDepo.NEDEN))
    with _SECIM_KILIT:
        try:
            eski_tur = secili_tur()
        except SecimHatasi:
            eski_tur, tasima = None, False  # nothing verified to copy from
        tasinan, atlanan = [], []
        eski = ornek(eski_tur) if eski_tur else None
        if eski is not None and yeni_tur != eski_tur and tasima:
            yeni = ornek(yeni_tur)
            degerler = {}
            for ad in eski.tum_adlar():
                if ad in KASA_SABIT:
                    continue
                v = eski.oku(ad)
                if v is None:
                    atlanan.append(ad)
                else:
                    degerler[ad] = v
            for ad, v in degerler.items():
                yeni.yaz(ad, v)
                if yeni.oku(ad) != v:
                    raise DepoHatasi(_("taşınan öğe geri okunamadı ({ad}); depo değiştirilmedi").format(ad=ad))
                tasinan.append(ad)
        try:
            ornek("kasa").yaz(SECIM_AD, yeni_tur.encode("ascii"))
        except DepoHatasi:
            if yeni_tur == "kasa":
                raise
            try:  # no usable kasa (no systemd-creds): the setting alone selects the wallet; remove a stale seal
                ornek("kasa").sil(SECIM_AD)
            except DepoHatasi:
                pass
        _ayar_yaz(yeni_tur)
        if eski is not None and yeni_tur != eski_tur and tasima:
            for ad in ("panel-isaret", "panel-nesil", "kalici-oturum"):
                try:
                    eski.sil(ad)
                except DepoHatasi:
                    pass
    from .gunluk import gunluk
    gunluk(f"anahtar deposu: {eski_tur} → {yeni_tur} ({len(tasinan)} öğe taşındı)")
    try:
        from . import liste_koruma
        liste_koruma._anahtar_unut()  # forget the cached signed state: read it from the new store
    except Exception:  # noqa: BLE001
        pass
    return {"tur": yeni_tur, "tasinan": tasinan, "atlanan": atlanan}


# ---------------------------------------------------------------- where a named secret may be typed

# The binding lives INSIDE the secret's own sealed value (security review R2 finding 2: a separate binding item could
# be deleted to drop the binding): ZARF + JSON header line + "\n" + value. A value without the envelope (written
# directly through Depo.yaz, e.g. by an older panel) has no binding; it is still typed only with the user's panel
# approval (cli.k_yaz_sir). A malformed envelope is closed-fail.
_ZARF = b"DHSIR1\n"
_SITE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")


def _hedef_dogrula(uygulama: str | None, site: str | None) -> dict:
    uygulama = (uygulama or "").strip().lower() or None
    site = (site or "").strip().lower().rstrip(".") or None
    if uygulama is not None and not re.fullmatch(r"[a-z0-9._-]{1,128}", uygulama):
        raise ValueError(_("geçersiz uygulama sınıfı: {deger}").format(deger=uygulama))
    if site is not None and not _SITE.fullmatch(site):
        raise ValueError(_("geçersiz site: {deger}").format(deger=site))
    return {k: v for k, v in (("uygulama", uygulama), ("site", site)) if v}


def sir_paketle(deger: bytes, uygulama: str | None = None, site: str | None = None) -> bytes:
    import json
    hedef = _hedef_dogrula(uygulama, site)
    return _ZARF + json.dumps({"hedef": hedef}, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n" + \
        bytes(deger)


def sir_coz(ham: bytes) -> tuple[bytes, dict]:
    """(value, binding) of a stored secret. No envelope: (raw, {}). A malformed envelope → DepoHatasi."""
    import json
    if not ham.startswith(_ZARF):
        return ham, {}
    bas, ayrac, deger = ham[len(_ZARF):].partition(b"\n")
    try:
        h = json.loads(bas.decode("utf-8")).get("hedef") if ayrac else None
        if not isinstance(h, dict):
            raise ValueError
        hedef = _hedef_dogrula(h.get("uygulama"), h.get("site"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        raise DepoHatasi(_("gizli bilgi kaydı bozuk")) from None
    return deger, hedef


def sir_yaz(ad: str, deger: bytes, uygulama: str | None = None, site: str | None = None) -> None:
    """Store the user's secret `ad` with its binding (window class and/or site, subdomains included; None: unbound).
    Settings and `deskhand secret set` use this."""
    if not kullanici_adi_mi(ad):
        raise ValueError(_("geçersiz ya da ayrılmış ad: {ad}").format(ad=ad))
    if not deger:
        raise ValueError(_("boş değer kaydedilmez"))
    secili_depo().yaz(ad, sir_paketle(deger, uygulama, site))


def sir_oku(ad: str) -> tuple[bytes, dict] | None:
    """(value, binding) of the user's secret `ad`, or None (no such secret)."""
    if not kullanici_adi_mi(ad):
        raise ValueError(_("geçersiz ya da ayrılmış ad: {ad}").format(ad=ad))
    ham = secili_depo().oku(ad)
    return None if ham is None else sir_coz(ham)


def sir_hedefi_oku(ad: str) -> dict:
    """{"uygulama": ..., "site": ...} the secret `ad` is bound to ({}: unbound or no such secret)."""
    s = sir_oku(ad)
    return {} if s is None else s[1]


def sir_hedefi_yaz(ad: str, uygulama: str | None = None, site: str | None = None) -> None:
    """Change the binding of an existing secret (the value is re-sealed with it). No such secret → DepoHatasi."""
    s = sir_oku(ad)
    if s is None:
        raise DepoHatasi(_("kayıtlı gizli bilgi yok: {ad}").format(ad=ad))
    secili_depo().yaz(ad, sir_paketle(s[0], uygulama, site))
