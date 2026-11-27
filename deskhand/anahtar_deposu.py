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

Selection: `secili_tur()` reads `[anahtar] depo`; with no value: a store that already has kasa items → kasa; earlier
panel marks or persistent-session records (an install that used the wallet) → cuzdan (nothing changes until the user
switches in Settings); otherwise (a new install) → kasa. `depo_degistir(yeni)` (panel only, after the user's Yes) copies
every item from the old store to the new one FIRST and only then writes the setting, so the signed panel state stays
valid. A changed setting with no copy (a hand edit) finds no signed state while marks exist: closed-fail, never a first
start (liste_koruma.ilk_kurulum).

Threat model (honest, docs/ARCHITECTURE.md §4): a process that only writes files cannot read the sealed items or make a
valid seal by copying files. Code running as the same user that DELIBERATELY runs `systemd-creds --user decrypt|encrypt`
can read and forge kasa items, exactly like same-user code that talks to an unlocked wallet: out of scope (it needs the
agent shell isolated from the user's credentials). Deleting the kasa items AND every panel mark AND both list files makes
the next panel start a first start (the default lists); removing only some of them is closed-fail.

DESKHAND_ANAHTARLIK=kapali (tests/_yalitim.py): `secili_depo()` is a store that refuses everything (never the real
wallet, never the real TPM); tests build KasaDepo with a fake systemd-creds on PATH.
"""
from __future__ import annotations

import os
import re
import shutil
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
}
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


# ---------------------------------------------------------------- kasa (systemd-creds)

_TPM: bool | None = None


def tpm_var() -> bool:
    """`systemd-creds has-tpm2` (cached; no TPM operation)."""
    global _TPM
    if _TPM is None:
        arac = shutil.which("systemd-creds")
        if not arac:
            return False
        try:
            _TPM = subprocess.run([arac, "has-tpm2", "-q"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=_SURE).returncode == 0
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
        arac = shutil.which("systemd-creds")
        if not arac:
            raise DepoHatasi(_("systemd-creds bulunamadı (systemd 256+ gerekir); Ayarlar'dan KDE Cüzdanı seçilebilir"),
                             yok_kesin=True)
        return arac

    def _calistir(self, argv: list[str], girdi: bytes) -> bytes:
        try:
            r = subprocess.run([self._arac(), "--user", *argv], input=girdi, capture_output=True, timeout=_SURE)
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
        return shutil.which("systemd-creds") is None

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
    """No `[anahtar] depo`: kasa items → kasa; panel marks or persistent-session records (the wallet was in use) →
    cuzdan; a new install → kasa. Reads files only (no D-Bus)."""
    try:
        if KasaDepo().tum_adlar():
            return "kasa"
    except DepoHatasi:
        return "kasa"  # an unsafe kasa directory exists: kasa (it refuses; closed-fail)
    from . import liste_koruma
    if liste_koruma.isaret_gecmisi():
        return "cuzdan"
    try:
        kayit = os.listdir(os.path.join(yollar.data_dir(), "oturum-kalici"))
    except OSError:
        kayit = []
    if any(a.endswith(".kayit") for a in kayit):
        return "cuzdan"
    return VARSAYILAN_TUR


def secili_tur() -> str:
    return _ayardaki_tur() or _varsayilan_tur()


def secili_depo() -> Depo:
    """The store the user selected (`[anahtar] depo`). Under DESKHAND_ANAHTARLIK=kapali: a store that refuses."""
    if _kapali():
        return KapaliDepo()
    return ornek(secili_tur())


def _ayar_yaz(tur: str) -> None:
    from . import ayarlar
    ham = ayarlar.ham_oku()
    bolum = ham.get(AYAR_BOLUM)
    ham[AYAR_BOLUM] = {**(bolum if isinstance(bolum, dict) else {}), AYAR_ANAHTAR: tur}
    ayarlar.yaz(ham)


def depo_degistir(yeni_tur: str, tasima: bool = True) -> dict:
    """Panel only, after the user's Yes: switch the store. Every item of the old store (internal + the user's) is copied
    to the new one FIRST (so the panel's signed state and its marks stay valid), then `[anahtar] depo` is written.
    The old items are left where they are (the user may remove them; a switch back finds them).
    → {"tur": yeni_tur, "tasinan": [names], "atlanan": [names]}.
    The old store cannot be read (locked wallet, broken seal) → DepoHatasi and NOTHING changes; tasima=False switches
    without copying (the panel then has no signed state: closed-fail, the user approves the lists again)."""
    if yeni_tur not in TURLER:
        raise ValueError(_("bilinmeyen depo: {tur}").format(tur=yeni_tur))
    if _kapali():
        raise DepoHatasi(_(KapaliDepo.NEDEN))
    with _SECIM_KILIT:
        eski_tur = secili_tur()
        tasinan, atlanan = [], []
        if yeni_tur != eski_tur and tasima:
            eski, yeni = ornek(eski_tur), ornek(yeni_tur)
            degerler = {}
            for ad in eski.tum_adlar():
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
        _ayar_yaz(yeni_tur)
    from .gunluk import gunluk
    gunluk(f"anahtar deposu: {eski_tur} → {yeni_tur} ({len(tasinan)} öğe taşındı)")
    try:
        from . import liste_koruma
        liste_koruma._anahtar_unut()  # forget the cached signed state: read it from the new store
    except Exception:  # noqa: BLE001
        pass
    return {"tur": yeni_tur, "tasinan": tasinan, "atlanan": atlanan}
