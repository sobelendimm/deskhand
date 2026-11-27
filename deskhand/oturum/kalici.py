"""Persistent background sessions (docs/SESSIONS.md §3.8): a site the user lists in `[oturum] kalici` keeps the
session it gets in the background Firefox copy from one copy to the next.

Why: every background Firefox is a fresh, throw-away copy of the real profile (firefox.hazirla). A site where the user
logs in ONLY in the background (a seller panel) lost that login when the copy was deleted, so every new copy asked for
a login again (and the real profile never had it).

What:
  kaydet(kopya, siteler)  when a copy is deleted (kopya_bekcisi.bekle_ve_sil, kopya._sil / supur, oturum._kapanis_ic):
                          the copy's cookies of the listed sites are written, ENCRYPTED, to
                          DATA_DIR/oturum-kalici/<site>.kayit (directory 0700, file 0600, atomic). A site with no live
                          cookie left (logged out) loses its record.
  uygula(kopya, siteler)  when a new copy is prepared (firefox.hazirla, before the cookie database is rebuilt): the
                          stored cookies go into the copy's cookies.sqlite. A row already in the copy wins only when it is
                          still valid and was used later than the stored one.
  durum(site)             value-free summary for `sessions check` / doctor (presence, age, expiry; never a value).
  unut(site) / unut_hepsi()   `deskhand sessions forget <site> | --all`.

Encryption (user decision 27 Kas: "kept on my own computer, encrypted"): AES-256-GCM (cryptography). The 256-bit key
is ONE item in the user's Secret Service (KDE Wallet), label "Deskhand session store", attributes
application=deskhand, purpose=kalici-oturum; it is created on the first save and never written to disk, to the log or
to any output. Every record has a fresh 96-bit nonce; the associated data binds it to this store and this domain (a
file copied or renamed to another domain does not decrypt). File: MAGIC | nonce | ciphertext+tag.
Closed-fail: no Secret Service, a locked wallet (no unlock prompt is ever raised from the background), an unreadable
key or a record that does not decrypt → nothing is written and nothing is applied, never a plain-text fallback; the
reason is kept (son_neden) for doctor / `sessions check`. A record that does not decrypt with a readable key (tampered,
renamed, or written under an older key) is deleted. Plain JSON records of the first release (b72755f) are deleted
(overwritten, then unlinked) the first time they are seen; they are not migrated.

Lifetime (user decision 27 Kas, no one-day cap): a persistent cookie keeps its own expiry; a session-only cookie
(no expiry, or expiry <= 0 in cookies.sqlite) gets `[oturum] kalici_sure_gun` days (default 30, 1..365) from the
first save; when that cookie comes back in a later copy unchanged in expiry it keeps the first deadline (no endless
renewal). A record whose cookies have all expired, or one "saved" in the future, is deleted when read. The server's
own session lifetime is not extended: a site that ends the session on its side still asks for a login, and
`sessions check` says so.

Never stored, never applied (checked at save AND at apply time, so a record written by hand or by an older release is
filtered as well):
  - bank / payment / government / central identity domains: the reject list of oturum.toml through
    Politika.site_reddedildi / Politika.cerez_reddedildi (every spelling: case, trailing dot, IDNA dots, Unicode and
    ACE). The panel's account-session permission does NOT open them here (the strict policy is used);
  - task mode (gorev_kipi): nothing is applied and a task copy (its user.js carries the task marker) is never saved;
  - sites not in the list, cookies of hosts outside the listed site, cookies of an unknown origin context.

Extension point (Faz 4 P2, user decision 27 Kas): bank/payment sessions will live in a SECOND, locked store that is
applied only after the user's approval and only for that task. That store is another `Depo` instance with its own
directory name and its own `kabul` rule (and the same key ring); the default store below keeps rejecting them.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import tempfile
import time
from pathlib import Path

from .. import yollar
from ..i18n import _

SURUM = 2
SURE_GUN_VARSAYILAN = 30
_DOSYA_AZAMI = 1024 * 1024    # a record larger than this is not read
_GELECEK_PAYI = 300           # a record "saved" this far in the future (clock change / hand edit) is dropped
_ESIT_PAYI = 2.0              # seconds: a cookie whose expiry equals the stored one is the same session-only cookie
_ZAMAN_AZAMI = 1e13           # seconds; larger (or non-finite) times are malformed
_SITE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
_ALANLAR = ("host", "name", "value", "path", "originAttributes")
_UZANTI = ".kayit"
_ESKI_UZANTI = ".json"        # plain records of the first release (b72755f)
_SIHIR = b"DHK2"
_NONCE = 12


# ---------------------------------------------------------------- key ring

class AnahtarYok(Exception):
    """The store key is not available. `yok`: the key ring answered and there is no key (nothing was ever saved)."""

    def __init__(self, neden: str, yok: bool = False):
        super().__init__(neden)
        self.neden = neden
        self.yok = yok


class GizliServis:
    """The key in the user's Secret Service (org.freedesktop.secrets: KDE Wallet / GNOME Keyring) via secretstorage
    (jeepney; the secret travels DH-encrypted on the bus). Never unlocks (no prompt from the background)."""

    ETIKET = "Deskhand session store"
    OZNITELIK = {"application": "deskhand", "purpose": "kalici-oturum"}

    def anahtar(self, olustur: bool) -> bytes:
        if os.environ.get("DESKHAND_ANAHTARLIK") == "kapali":  # tests (tests/_yalitim.py): never the real wallet
            raise AnahtarYok(_("anahtarlık kapalı (DESKHAND_ANAHTARLIK=kapali)"))
        try:
            import secretstorage
            from secretstorage.exceptions import SecretStorageException
        except ImportError:
            raise AnahtarYok(_("python-secretstorage kurulu değil")) from None
        try:
            baglanti = secretstorage.dbus_init()
        except Exception:  # noqa: BLE001 - no session bus
            raise AnahtarYok(_("Secret Service'e bağlanılamadı (oturum veri yolu yok)")) from None
        try:
            try:
                koleksiyon = secretstorage.Collection(baglanti)  # the default collection; never created here
            except SecretStorageException:
                raise AnahtarYok(_("Secret Service yok ya da varsayılan cüzdan yok (KDE Cüzdanı)")) from None
            if koleksiyon.is_locked():
                raise AnahtarYok(_("cüzdan kilitli"))
            k = self._bul(koleksiyon)
            if k is not None:
                return k
            if not olustur:
                raise AnahtarYok(_("anahtar yok (henüz kayıt yapılmadı)"), yok=True)
            return self._olustur(koleksiyon)
        except AnahtarYok:
            raise
        except Exception:  # noqa: BLE001 - D-Bus / service errors: closed-fail (the message may carry no secret)
            raise AnahtarYok(_("anahtar okunamadı (Secret Service hatası)")) from None
        finally:
            baglanti.close()

    def _bul(self, koleksiyon) -> bytes | None:
        for oge in koleksiyon.search_items(self.OZNITELIK):
            if oge.is_locked():
                raise AnahtarYok(_("cüzdan kilitli"))
            s = bytes(oge.get_secret())
            if len(s) == 32:
                return s
        return None

    def _olustur(self, koleksiyon) -> bytes:
        """Create the key once: an exclusive lock (RUNTIME_DIR) so two closing copies do not create two keys; read back
        what the service holds."""
        import fcntl
        kilit = os.path.join(yollar.runtime_dir(), "kalici-anahtar.kilit")
        os.makedirs(os.path.dirname(kilit), mode=0o700, exist_ok=True)
        fd = os.open(kilit, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            k = self._bul(koleksiyon)
            if k is None:
                koleksiyon.create_item(self.ETIKET, self.OZNITELIK, os.urandom(32), replace=True,
                                       content_type="application/octet-stream")
                k = self._bul(koleksiyon)
            if k is None:
                raise AnahtarYok(_("anahtar okunamadı (Secret Service hatası)"))
            return k
        finally:
            os.close(fd)


_anahtarlik = GizliServis()
_son_neden: str | None = None


def anahtarlik_ayarla(nesne) -> None:
    """Replace the key ring (tests inject a fake; an object with anahtar(olustur: bool) -> bytes)."""
    global _anahtarlik
    _anahtarlik = nesne


def son_neden() -> str | None:
    """The last reason the store could not be used in this process (None = it worked)."""
    return _son_neden


def _anahtar(olustur: bool) -> bytes | None:
    """The key, or None (reason kept in son_neden; logged once per reason)."""
    global _son_neden
    try:
        k = _anahtarlik.anahtar(olustur)
    except AnahtarYok as e:
        if not e.yok and _son_neden != e.neden:
            from ..gunluk import gunluk
            gunluk(f"oturum: kalıcı depo kullanılamadı: {e.neden}")
        _son_neden = None if e.yok else e.neden
        return None
    if not isinstance(k, (bytes, bytearray)) or len(k) != 32:
        _son_neden = _("anahtar okunamadı (Secret Service hatası)")
        return None
    _son_neden = None
    return bytes(k)


def _aad(depo: str, site: str) -> bytes:
    return f"deskhand-kalici/{SURUM}/{depo}/{site}".encode()


# ---------------------------------------------------------------- helpers

def _ret_disi(pol, konak: str, bilinen=()) -> bool:
    """Default store rule: a host is accepted only when the reject list does not reject it (any spelling)."""
    return not pol.cerez_reddedildi(konak, bilinen)


def ayar_siteleri() -> set[str]:
    """The `[oturum] kalici` setting as a set of domain names (invalid entries, `*`, bare public suffixes dropped)."""
    from .. import ayarlar, gorev_kipi
    try:
        return set(gorev_kipi.site_ayristir(str(ayarlar.al("oturum", "kalici") or "")))
    except Exception:  # noqa: BLE001 - unreadable setting: nothing is persistent
        return set()


def sure_gun() -> int:
    """`[oturum] kalici_sure_gun`: lifetime of a session-only cookie in the store (days, 1..365)."""
    from .. import ayarlar
    try:
        return max(1, min(365, int(ayarlar.al("oturum", "kalici_sure_gun"))))
    except Exception:  # noqa: BLE001
        return SURE_GUN_VARSAYILAN


def _siteler(siteler) -> list[str]:
    from .. import gorev_kipi
    return sorted({s for s in gorev_kipi.site_ayristir(",".join(str(x) for x in (siteler or ()))) if _SITE.fullmatch(s)})


def _politika():
    from . import politika
    return politika.coz("firefox")


def _konak(host) -> str:
    return str(host or "").strip().lower().rstrip(".")


def _site_konagi(host: str, site: str) -> bool:
    """The cookie belongs to the site: its host is the site or a subdomain of it (a leading dot is ignored)."""
    d = _konak(host).lstrip(".")
    return bool(d) and (d == site or d.endswith("." + site))


def _gorev_kopyasi(kopya: Path) -> bool:
    """True for a copy prepared in task mode (or one whose user.js cannot be read: closed-safe)."""
    from . import firefox
    isaret = firefox._GOREV_USER_JS.splitlines()[0]
    try:
        with open(kopya / "user.js", encoding="utf-8", errors="replace") as f:
            return isaret in f.read()
    except OSError:
        return True


def _sayi(v) -> bool:
    """A finite, sane JSON number (json.loads accepts NaN / Infinity / 10**400; a bool is not a number here)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(float(v)) and abs(float(v)) < _ZAMAN_AZAMI
    except OverflowError:
        return False


def _sn(deger, ms: bool) -> float | None:
    """cookies.sqlite expiry → seconds; None for a session-only cookie (no expiry / <= 0) or a malformed value."""
    try:
        v = float(deger)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v / 1000 if ms else v


def _kopya_cerezleri(kopya: Path) -> tuple[list[dict], set[str]] | None:
    """Cookies of the copy (cookies.sqlite read from a consistent temporary 0700 copy, plus the copy's own
    sessionstore recovery file when Firefox wrote one) and the hosts known in the copy. None = unreadable.
    `expiry` is None for a session-only cookie."""
    from . import firefox
    from . import kopya as kopya_mod
    db = kopya / "cookies.sqlite"
    if not db.is_file() or db.is_symlink():
        return None
    sonuc: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(prefix="deskhand-kalici-") as td:
            os.chmod(td, 0o700)
            gecici = os.path.join(td, "c.sqlite")
            kopya_mod.sqlite_yedek(str(db), gecici)
            con = sqlite3.connect(gecici)
            try:
                sutunlar = {r[1] for r in con.execute("PRAGMA table_info(moz_cookies)")}
                (enbuyuk,) = con.execute("SELECT MAX(expiry) FROM moz_cookies").fetchone()
                ms = not enbuyuk or enbuyuk > 1e11
                ek = [s for s in ("sameSite", "schemeMap", "isPartitionedAttributeSet") if s in sutunlar]
                for r in con.execute("SELECT originAttributes, name, value, host, path, expiry, lastAccessed, "
                                     "creationTime, isSecure, isHttpOnly" + "".join(f", {s}" for s in ek) +
                                     " FROM moz_cookies"):
                    c = {"originAttributes": r[0] or "", "name": r[1] or "", "value": r[2] or "", "host": r[3] or "",
                         "path": r[4] or "/", "expiry": _sn(r[5], ms), "lastAccessed": int(r[6] or 0),
                         "creationTime": int(r[7] or 0), "isSecure": int(bool(r[8])), "isHttpOnly": int(bool(r[9]))}
                    for i, s in enumerate(ek):
                        c[s] = int(r[10 + i] or 0)
                    sonuc.append(c)
            finally:
                con.close()
    except (sqlite3.Error, OSError, ValueError, OverflowError):
        return None
    rec = firefox._recovery_oku(str(kopya / "sessionstore-backups" / "recovery.jsonlz4"))
    mikro = int(time.time() * 1e6)
    for c in rec.get("cookies") or ():
        if not isinstance(c, dict):
            continue
        oa = firefox.oa_soneki(c.get("originAttributes", ""))
        if oa is None:
            continue
        try:
            sonuc.append({"originAttributes": oa, "name": str(c.get("name", "")), "value": str(c.get("value", "")),
                          "host": str(c.get("host", "")), "path": str(c.get("path", "/")),
                          "expiry": firefox._kaynak_bitis(c), "lastAccessed": mikro, "creationTime": mikro,
                          "isSecure": int(bool(c.get("secure"))), "isHttpOnly": int(bool(c.get("httponly"))),
                          "sameSite": int(c.get("sameSite", 0) or 0), "schemeMap": int(c.get("schemeMap", 0) or 0),
                          "isPartitionedAttributeSet": int(bool(c.get("isPartitioned")))})
        except (TypeError, ValueError, OverflowError):
            continue
    bilinen = {_konak(c["host"]).lstrip(".") for c in sonuc}
    try:
        bilinen |= firefox._bilinen_konaklar(str(kopya), str(db), rec)
    except (sqlite3.Error, OSError):
        pass
    return sonuc, bilinen


def _gecerli_cerez(c) -> bool:
    """Structure check of a stored cookie (a record may have been edited by someone holding the key)."""
    if not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in _ALANLAR):
        return False
    if not _sayi(c.get("expiry")):
        return False
    oa = c["originAttributes"]
    return bool(c["host"]) and (oa == "" or oa.startswith("^"))


def _anahtar_demeti(c: dict) -> tuple:
    return (c["name"], c["host"], c["path"], c["originAttributes"])


def _guvenli_sil(yol: str) -> None:
    """Best-effort wipe of a plain-text file (overwrite with zeros, fsync, unlink). On flash storage the old blocks
    may survive the overwrite; the file is gone from the file system either way."""
    try:
        fd = os.open(yol, os.O_WRONLY | os.O_NOFOLLOW)
    except OSError:
        fd = -1
    if fd >= 0:
        try:
            st = os.fstat(fd)
            if stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid():
                os.write(fd, b"\0" * min(st.st_size, _DOSYA_AZAMI))
                os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)
    try:
        os.unlink(yol)
    except OSError:
        pass


# ---------------------------------------------------------------- store

class Depo:
    """One cookie store: DATA_DIR/<ad>/<site>.kayit (encrypted). `kabul(politika, host, bilinen_konaklar) -> bool`
    decides which hosts may be stored and applied (the site itself is checked with the same rule and no known
    hosts)."""

    def __init__(self, ad: str, kabul=_ret_disi):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", ad):
            raise ValueError(ad)
        self.ad = ad
        self.kabul = kabul

    # ---- files
    def dizin(self) -> str:
        return os.path.join(yollar.data_dir(), self.ad)

    def _dosya(self, site: str, uzanti: str = _UZANTI) -> str | None:
        return os.path.join(self.dizin(), f"{site}{uzanti}") if _SITE.fullmatch(site or "") else None

    def _dizin_hazirla(self) -> str | None:
        """The store directory, created 0700; refused (None) when it is a symlink, not ours or not a directory."""
        d = self.dizin()
        try:
            os.makedirs(os.path.dirname(d), mode=0o700, exist_ok=True)
            try:
                os.mkdir(d, 0o700)
            except FileExistsError:
                pass
            st = os.lstat(d)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
                return None
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.chmod(d, 0o700)
        except OSError:
            return None
        return d

    def _dizin_gecerli(self) -> bool:
        """Read-side check (nothing created or changed): the store directory is ours, a real directory, 0700 or
        narrower."""
        try:
            st = os.lstat(self.dizin())
        except OSError:
            return False
        return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077

    def _eski_sil(self, site: str) -> None:
        """A plain record of the first release for this site is wiped (never read, never migrated)."""
        eski = self._dosya(site, _ESKI_UZANTI)
        if eski and self._dizin_gecerli() and os.path.lexists(eski):
            _guvenli_sil(eski)

    def kayitli_siteler(self) -> list[str]:
        """Sites with a record file (no decryption)."""
        if not self._dizin_gecerli():
            return []
        try:
            adlar = os.listdir(self.dizin())
        except OSError:
            return []
        return sorted(a[: -len(_UZANTI)] for a in adlar if a.endswith(_UZANTI) and _SITE.fullmatch(a[: -len(_UZANTI)]))

    def _ham_oku(self, site: str) -> bytes | None:
        yol = self._dosya(site)
        if yol is None or not self._dizin_gecerli():
            return None
        try:
            fd = os.open(yol, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or \
                    st.st_size > _DOSYA_AZAMI:
                return None
            parcalar = []
            while True:
                b = os.read(fd, 65536)
                if not b:
                    break
                parcalar.append(b)
            return b"".join(parcalar)
        except OSError:
            return None
        finally:
            os.close(fd)

    def _oku(self, site: str, anahtar: bytes | None = None) -> dict | None:
        """The decrypted record, or None. A record that does not decrypt with a readable key, or is malformed, is
        deleted; with no key nothing is deleted (a locked wallet must not cost the record)."""
        self._eski_sil(site)
        ham = self._ham_oku(site)
        if ham is None:
            return None
        k = anahtar if anahtar is not None else _anahtar(False)
        if k is None:
            return None
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        try:
            if not ham.startswith(_SIHIR) or len(ham) < len(_SIHIR) + _NONCE + 16:
                raise ValueError("biçim")
            nonce = ham[len(_SIHIR):len(_SIHIR) + _NONCE]
            acik = AESGCM(k).decrypt(nonce, ham[len(_SIHIR) + _NONCE:], _aad(self.ad, site))
            d = json.loads(acik.decode("utf-8"))
        except (InvalidTag, ValueError):
            self.sil(site)
            return None
        if not isinstance(d, dict) or d.get("site") != site or not isinstance(d.get("cerezler"), list) or \
                not _sayi(d.get("kayit")):
            self.sil(site)
            return None
        return d

    def _yaz(self, site: str, kayit: dict, anahtar: bytes | None = None) -> bool:
        k = anahtar if anahtar is not None else _anahtar(True)
        d = self._dizin_hazirla()
        yol = self._dosya(site)
        if k is None or d is None or yol is None:
            return False
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(_NONCE)
        try:
            veri = json.dumps(kayit, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except ValueError:
            return False
        sifreli = _SIHIR + nonce + AESGCM(k).encrypt(nonce, veri, _aad(self.ad, site))
        try:
            fd, gecici = tempfile.mkstemp(prefix=f".{site}.", suffix=".tmp", dir=d)
        except OSError:
            return False
        try:
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(sifreli)
                f.flush()
                os.fsync(f.fileno())
            os.replace(gecici, yol)
            self._eski_sil(site)
            return True
        except OSError:
            try:
                os.unlink(gecici)
            except OSError:
                pass
            return False

    def sil(self, site: str) -> bool:
        """Delete the record of a site (and a plain record of the first release). → something was deleted."""
        silindi = False
        for uzanti in (_UZANTI, _ESKI_UZANTI):
            yol = self._dosya(site, uzanti)
            if yol is None or not self._dizin_gecerli() or not os.path.lexists(yol):
                continue
            if uzanti == _ESKI_UZANTI:
                _guvenli_sil(yol)
            else:
                try:
                    os.unlink(yol)
                except OSError:
                    continue
            silindi = True
        return silindi

    def sil_hepsi(self) -> int:
        """Delete every record (forget --all). → number of sites deleted."""
        if not self._dizin_gecerli():
            return 0
        try:
            adlar = os.listdir(self.dizin())
        except OSError:
            return 0
        n = 0
        for a in adlar:
            for uzanti in (_UZANTI, _ESKI_UZANTI):
                if a.endswith(uzanti) and _SITE.fullmatch(a[: -len(uzanti)]):
                    n += self.sil(a[: -len(uzanti)])
            if a.startswith(".") and a.endswith(".tmp"):  # leftover of an interrupted write
                try:
                    os.unlink(os.path.join(self.dizin(), a))
                except OSError:
                    pass
        return n

    # ---- lifetime
    @staticmethod
    def _canli_cerezler(kayit: dict, simdi: float) -> list[dict]:
        """Live cookies of a record: well-formed and not expired. [] = the record is dead (also when it was "saved"
        in the future)."""
        if float(kayit["kayit"]) > simdi + _GELECEK_PAYI:
            return []
        return [c for c in kayit["cerezler"] if _gecerli_cerez(c) and float(c["expiry"]) > simdi]

    # ---- API
    def kaydet(self, kopya, siteler, politika=None) -> int:
        """Store the copy's cookies of the listed sites. → number of cookies stored."""
        from .. import gorev_kipi
        kopya = Path(kopya)
        siteler = _siteler(siteler)
        if not siteler or gorev_kipi.etkin() or _gorev_kopyasi(kopya):
            return 0
        okunan = _kopya_cerezleri(kopya)
        if okunan is None:
            return 0
        k = _anahtar(True)
        if k is None:
            return 0  # closed-fail: no plain-text fallback, existing records are kept
        cerezler, bilinen = okunan
        pol = politika or _politika()
        simdi = time.time()
        oturumluk_bitis = simdi + sure_gun() * 86400
        toplam = 0
        for site in siteler:
            if not self.kabul(pol, site, ()):
                self.sil(site)
                continue
            onceki = self._oku(site, k) or {}
            onceki_oturumluk = {_anahtar_demeti(c): float(c["expiry"]) for c in onceki.get("cerezler", ())
                                if _gecerli_cerez(c) and c.get("oturumluk")}
            secilen = {}
            for c in cerezler:
                if not _site_konagi(c["host"], site) or not self.kabul(pol, c["host"], bilinen):
                    continue
                if c["originAttributes"] and not c["originAttributes"].startswith("^"):
                    continue
                anahtar = _anahtar_demeti(c)
                bitis = c["expiry"]
                eski = onceki_oturumluk.get(anahtar)
                if bitis is None:  # session-only: the first deadline is kept, otherwise save + N days
                    bitis, oturumluk = (eski if eski is not None else oturumluk_bitis), True
                elif eski is not None and abs(bitis - eski) <= _ESIT_PAYI:
                    oturumluk = True  # a stored session-only cookie that came back through cookies.sqlite
                else:
                    oturumluk = False
                if bitis <= simdi or not _sayi(bitis):
                    continue
                secilen[anahtar] = {**c, "expiry": bitis, "oturumluk": oturumluk}
            if not secilen:
                self.sil(site)  # logged out / nothing left: the old record must not bring the session back
                continue
            if self._yaz(site, {"surum": SURUM, "site": site, "kayit": simdi, "cerezler": list(secilen.values())}, k):
                toplam += len(secilen)
        return toplam

    def uygula(self, kopya, siteler, politika=None, gorev_siteleri=None, bilinen_konaklar=()) -> int:
        """Put the stored cookies of the listed sites into the copy's cookies.sqlite (not in task mode). Expired
        records are deleted. → number of cookies written."""
        from .. import gorev_kipi
        kopya = Path(kopya)
        siteler = _siteler(siteler)
        db = kopya / "cookies.sqlite"
        # (no user.js check here: firefox.hazirla applies before writing user.js; it never calls this in task mode)
        if not siteler or gorev_kipi.etkin() or not db.is_file() or db.is_symlink():
            return 0
        if not any(os.path.lexists(self._dosya(s) or "") or os.path.lexists(self._dosya(s, _ESKI_UZANTI) or "")
                   for s in siteler):
            return 0  # nothing stored: the key ring is not even asked
        k = _anahtar(False)
        if k is None:
            for s in siteler:
                self._eski_sil(s)
            return 0
        pol = politika or _politika()
        simdi = time.time()
        yazilan = 0
        con = sqlite3.connect(str(db))
        try:
            sutunlar = {r[1] for r in con.execute("PRAGMA table_info(moz_cookies)")}
            (enbuyuk,) = con.execute("SELECT MAX(expiry) FROM moz_cookies").fetchone()
            carpan = 1000 if (not enbuyuk or enbuyuk > 1e11) else 1
            bilinen = set(bilinen_konaklar or ()) | {_konak(r[0]).lstrip(".") for r in
                                                     con.execute("SELECT DISTINCT host FROM moz_cookies")}
            for site in siteler:
                kayit = self._oku(site, k)
                if kayit is None:
                    continue
                if not self.kabul(pol, site, ()):
                    self.sil(site)
                    continue
                canli = self._canli_cerezler(kayit, simdi)
                if not canli:
                    self.sil(site)
                    continue
                kayit_bilinen = bilinen | {_konak(c["host"]).lstrip(".") for c in canli}
                for c in canli:
                    host = c["host"]
                    alan = _konak(host).lstrip(".")
                    if not _site_konagi(host, site) or not self.kabul(pol, host, kayit_bilinen):
                        continue
                    if not pol.site_izinli(alan, gorev_siteleri):
                        continue
                    yazilan += self._satir_yaz(con, c, sutunlar, carpan, simdi)
            con.commit()
        except (sqlite3.Error, OverflowError):
            con.rollback()
            yazilan = 0
        finally:
            con.close()
        return yazilan

    @staticmethod
    def _satir_yaz(con, c: dict, sutunlar: set, carpan: int, simdi: float) -> int:
        anahtar = _anahtar_demeti(c)
        ek = [s for s in ("sameSite", "schemeMap", "isPartitionedAttributeSet") if s in sutunlar]
        if "updateTime" in sutunlar:
            ek.append("updateTime")
        try:  # a hand-edited record may carry anything in these fields: such a cookie is skipped
            erisim = int(c.get("lastAccessed") or 0)
            olusma = int(c.get("creationTime") or erisim)
            degerler = [int(c.get(s, 0) or 0) if s != "updateTime" else erisim for s in ek]
            bitis = int(float(c["expiry"]) * carpan)
        except (TypeError, ValueError, OverflowError):
            return 0
        var = con.execute("SELECT expiry, lastAccessed FROM moz_cookies WHERE name=? AND host=? AND path=? AND "
                          "originAttributes=?", anahtar).fetchone()
        if var is not None and (var[0] or 0) > simdi * carpan and (var[1] or 0) >= erisim:
            return 0  # the copy already has a live row that was used later (fresh login in the real profile)
        con.execute("DELETE FROM moz_cookies WHERE name=? AND host=? AND path=? AND originAttributes=?", anahtar)
        con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry,lastAccessed,creationTime,"
                    "isSecure,isHttpOnly" + "".join(f",{s}" for s in ek) + ") VALUES (?,?,?,?,?,?,?,?,?,?" +
                    ",?" * len(ek) + ")",
                    (c["originAttributes"], c["name"], c["value"], c["host"], c["path"], bitis, erisim, olusma,
                     int(bool(c.get("isSecure"))), int(bool(c.get("isHttpOnly"))), *degerler))
        return 1

    def durum(self, site: str, siteler=None, simdi: float | None = None) -> dict:
        """Value-free summary for `sessions check` / doctor (nothing is changed, except that a record that does not
        decrypt with a readable key is deleted, as on every read). Cookies
        that would be sent to `site` (its own, its subdomains', parent-domain cookies of the listed site), expired
        ones flagged. `neden`: why the store could not be read (locked wallet…), else None."""
        alan = _konak(site).lstrip(".")
        liste = ayar_siteleri() if siteler is None else set(_siteler(siteler))
        eslesen = sorted((s for s in liste if alan == s or alan.endswith("." + s)), key=len, reverse=True)
        d = {"site": alan, "listede": bool(eslesen), "depo_site": eslesen[0] if eslesen else None,
             "reddedildi": False, "kayit": None, "bitis": None, "neden": None, "cerezler": []}
        if not eslesen:
            return d
        s = eslesen[0]
        pol = _politika()
        if not self.kabul(pol, s, ()):
            d["reddedildi"] = True
            return d
        if not os.path.lexists(self._dosya(s) or ""):
            self._eski_sil(s)
            return d
        k = _anahtar(False)
        if k is None:
            d["neden"] = son_neden() or _("anahtar yok (henüz kayıt yapılmadı)")
            return d
        kayit = self._oku(s, k)
        if kayit is None:
            return d
        simdi = time.time() if simdi is None else simdi
        zaman = float(kayit["kayit"])
        d["kayit"] = zaman
        bilinen = {_konak(c.get("host")).lstrip(".") for c in kayit["cerezler"] if isinstance(c, dict)}
        for c in kayit["cerezler"]:
            if not _gecerli_cerez(c) or not _site_konagi(c["host"], s) or not self.kabul(pol, c["host"], bilinen):
                continue
            h = _konak(c["host"])
            dh = h.lstrip(".")
            if not (dh == alan or dh.endswith("." + alan) or (h.startswith(".") and alan.endswith("." + dh))):
                continue
            bitis = float(c["expiry"])
            d["cerezler"].append({"ad": c["name"], "konak": c["host"], "bitis": bitis,
                                  "oturumluk": bool(c.get("oturumluk")),
                                  "gecmis": bitis <= simdi or zaman > simdi + _GELECEK_PAYI})
        gecerli = [c["bitis"] for c in d["cerezler"] if not c["gecmis"]]
        d["bitis"] = max(gecerli) if gecerli else None
        return d


DEPO = Depo("oturum-kalici")


def kaydet(kopya, siteler, politika=None) -> int:
    return DEPO.kaydet(kopya, siteler, politika)


def uygula(kopya, siteler, politika=None, gorev_siteleri=None, bilinen_konaklar=()) -> int:
    return DEPO.uygula(kopya, siteler, politika, gorev_siteleri, bilinen_konaklar)


def durum(site: str, siteler=None, simdi: float | None = None) -> dict:
    return DEPO.durum(site, siteler, simdi)


def unut(site: str) -> bool:
    return DEPO.sil(site)


def unut_hepsi() -> int:
    return DEPO.sil_hepsi()


def kapanirken(kopya_yolu: str) -> int:
    """Copy-deletion hook (watchdog, sweep, desktop shutdown): save the listed sites, never raise."""
    try:
        siteler = ayar_siteleri()
        if not siteler or not kopya_yolu or not os.path.isfile(os.path.join(kopya_yolu, "cookies.sqlite")):
            return 0
        n = kaydet(kopya_yolu, siteler)
        if n:
            from ..gunluk import gunluk
            gunluk(f"oturum: kalıcı depo: {os.path.basename(kopya_yolu)} kopyasından {n} çerez kaydedildi")
        return n
    except Exception:  # noqa: BLE001 - saving must not stop the copy from being deleted
        return 0
