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
(no expiry, or expiry <= 0; the same reading for cookies.sqlite and sessionstore, firefox.bitis_coz; a malformed
expiry is skipped) gets `[oturum] kalici_sure_gun` days (default 30, 1..365, panel-authoritative) from its LAST USE:
the cookie's own lastAccessed, never later than the copy's last use (review C2: a site used every day does not lose
its login on day 30; an unused cookie is not renewed). A record whose cookies have all expired, or one "saved" in the
future, is deleted when read. The server's own session lifetime is not extended: a site that ends the session on its
side still asks for a login, and `sessions check` says so.

Concurrency (review C1): every write/delete of the store holds one cross-process flock (DATA_DIR/<ad>/.kilit).
Forget (review Y2-Y4): `unut` resolves www./subdomains to the stored site, deletes the record and its temporary
leftovers and leaves <site>.unutuldu (forget --all: .hepsi.unutuldu); a copy opened before that time
(DATA_DIR/<ad>/.acilis/<copy path digest>, written by uygula; never a file in the copy) does not write the site back when it closes.

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

import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import tempfile
import threading
import time
import time as _saat  # monotonic / sleep for the lock (tests replace the module-level `time` with a shifted clock)
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
_KILIT_AD = ".kilit"          # cross-process store lock (review C1), in the store directory, 0600
_KILIT_SURE = 30.0            # seconds to wait for it; then nothing is written (logged)
_UNUTULDU = ".unutuldu"       # .<site>.unutuldu: when `sessions forget <site>` ran (review Y2)
_HEPSI_UNUTULDU = ".hepsi.unutuldu"  # `sessions forget --all`
_ACILIS = ".acilis"               # store dir: when each copy was first offered the store (uygula; review Y2)
_ACILIS_OMUR = 90 * 86400


# ---------------------------------------------------------------- key ring

class KilitAlinamadi(Exception):
    """forget could not take the store lock (another process holds it, or the store directory is not usable):
    NOTHING was forgotten. Distinct from "no record" (review INC3 B7): the CLI exits with its own code."""


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
    """The persistent-session sites the user approved in the panel (liste_koruma.kalici_siteleri: panel-authoritative,
    the settings file alone does not count; panel closed → empty, nothing is saved or applied)."""
    from .. import liste_koruma
    try:
        return set(liste_koruma.kalici_siteleri())
    except Exception:  # noqa: BLE001 - not verifiable: nothing is persistent
        return set()


def sure_gun() -> int:
    """`[oturum] kalici_sure_gun`: lifetime of a session-only cookie in the store (days, 1..365)."""
    from .. import liste_koruma
    try:
        return liste_koruma.kalici_sure_gun()  # panel-authoritative (review Y5): a longer value needs the panel
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


def _sn(deger, ms: bool) -> float | None | bool:
    """cookies.sqlite expiry → seconds; None = session-only (no expiry / <= 0); False = malformed (the cookie is
    skipped). The same helper reads sessionstore (firefox.bitis_coz; review C3)."""
    from .firefox import bitis_coz
    return bitis_coz(deger, ms)


def _kopya_cerezleri(kopya: Path, kullanim: float | None = None) -> tuple[list[dict], set[str]] | None:
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
                (enbuyuk,) = con.execute("SELECT MAX(expiry) FROM moz_cookies WHERE typeof(expiry) IN "
                                         "('integer', 'real')").fetchone()
                ms = not enbuyuk or enbuyuk > 1e11
                ek = [s for s in ("sameSite", "schemeMap", "isPartitionedAttributeSet") if s in sutunlar]
                for r in con.execute("SELECT originAttributes, name, value, host, path, expiry, lastAccessed, "
                                     "creationTime, isSecure, isHttpOnly" + "".join(f", {s}" for s in ek) +
                                     " FROM moz_cookies"):
                    bitis = _sn(r[5], ms)
                    if bitis is False:
                        continue  # malformed expiry: skipped (not a 30-day session-only cookie)
                    c = {"originAttributes": r[0] or "", "name": r[1] or "", "value": r[2] or "", "host": r[3] or "",
                         "path": r[4] or "/", "expiry": bitis, "lastAccessed": int(r[6] or 0),
                         "creationTime": int(r[7] or 0), "isSecure": int(bool(r[8])), "isHttpOnly": int(bool(r[9]))}
                    for i, s in enumerate(ek):
                        c[s] = int(r[10 + i] or 0)
                    sonuc.append(c)
            finally:
                con.close()
    except (sqlite3.Error, OSError, ValueError, OverflowError):
        return None
    rec = firefox._recovery_oku(str(kopya / "sessionstore-backups" / "recovery.jsonlz4"))
    mikro = int((kullanim if kullanim is not None else time.time()) * 1e6)  # session cookies: last use of the copy
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


def _anahtar_metni(anahtar: tuple) -> str:
    return json.dumps(list(anahtar), ensure_ascii=False)


def _oz(deger) -> str:
    """Digest of a cookie value (kept only inside the encrypted record or the copy itself; never printed)."""
    import hashlib
    return hashlib.sha256(str(deger).encode("utf-8", "surrogatepass")).hexdigest()


def _tamsayi(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _ayni(a: dict, b: dict) -> bool:
    """Same cookies (key, value, expiry) in two {key: cookie} maps."""
    return a.keys() == b.keys() and all(a[k]["value"] == b[k]["value"] and a[k]["expiry"] == b[k]["expiry"] for k in a)


def _canli_silinenler(kayit: dict | None, simdi: float) -> dict:
    """Live tombstones of a record: {key text: {oz, bitis}} for cookies logged out in some copy; one lives as long as
    the dropped cookie would have (after that a stale copy's cookie is expired as well)."""
    sonuc = {}
    for km, t in ((kayit or {}).get("silinen") or {}).items():
        if isinstance(km, str) and isinstance(t, dict) and isinstance(t.get("oz"), str) and _sayi(t.get("bitis")) \
                and float(t["bitis"]) > simdi:
            sonuc[km] = {"oz": t["oz"], "bitis": float(t["bitis"])}
    return sonuc


def _bolum_sitesi(oa: str):
    """Top-level site of a partitioned cookie (originAttributes `^…partitionKey=%28https%2Cexample.com%29`): the
    site, None when not partitioned, "" when the key is malformed."""
    from urllib.parse import unquote
    if not oa or not oa.startswith("^"):
        return None
    for parca in oa[1:].split("&"):
        ad, _e, deger = parca.partition("=")
        if ad != "partitionKey":
            continue
        m = re.fullmatch(r"\((?:https?|[a-z][a-z0-9+.-]*),([^,()]+)(?:,\d+)?(?:,.*)?\)", unquote(deger.replace("+", " ")))
        return _konak(m.group(1)).lstrip(".") if m else ""
    return None


_KOPYA_ISARETI = ".deskhand-kalici.json"  # in the copy: the stored versions it received (key text → value digest)


def _kopya_isareti_oku(kopya: Path) -> dict:
    try:
        fd = os.open(kopya / _KOPYA_ISARETI, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            d = json.loads(f.read(_DOSYA_AZAMI).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    return {s: {k: v for k, v in m.items() if isinstance(k, str) and isinstance(v, str)}
            for s, m in d.items() if isinstance(s, str) and isinstance(m, dict)}


def _kopya_isareti_yaz(kopya: Path, d: dict) -> None:
    try:
        fd, gecici = tempfile.mkstemp(prefix=".kalici-", suffix=".tmp", dir=str(kopya))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(d, f)
        os.replace(gecici, kopya / _KOPYA_ISARETI)
    except OSError:
        try:
            os.unlink(gecici)
        except OSError:
            pass


def _acilis_yolu(depo_dizin: str, kopya: Path) -> str:
    oz = hashlib.sha256(os.path.abspath(str(kopya)).encode("utf-8", "surrogateescape")).hexdigest()[:40]
    return os.path.join(depo_dizin, _ACILIS, oz)


def _kopya_acilisi_yaz(depo_dizin: str, kopya: Path) -> None:
    """Record once when this copy was opened (prepared) for the store (review Y2: a forget after this time wins).
    Kept in the STORE directory (0700, keyed by the copy path), never in the copy: the browser in the copy can write
    its own directory (security scan 3). Entries older than _ACILIS_OMUR are pruned (unknown → 0.0, closed-safe)."""
    d = os.path.join(depo_dizin, _ACILIS)
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        pass
    except OSError:
        return
    simdi = time.time()
    try:
        for ad in os.listdir(d):
            yol = os.path.join(d, ad)
            try:
                if os.lstat(yol).st_mtime < simdi - _ACILIS_OMUR:
                    os.unlink(yol)
            except OSError:
                pass
        fd = os.open(_acilis_yolu(depo_dizin, kopya), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        return
    try:
        os.write(fd, repr(simdi).encode())
    except OSError:
        pass
    finally:
        os.close(fd)


def _kopya_acilisi(depo_dizin: str, kopya: Path) -> float:
    """When the copy was opened (0.0 = unknown: older than any forget, closed-safe); never later than now."""
    try:
        fd = os.open(_acilis_yolu(depo_dizin, kopya), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return 0.0
    try:
        v = float(os.read(fd, 64).decode("ascii", "replace").strip())
        return min(v, time.time()) if math.isfinite(v) else 0.0
    except (OSError, ValueError):
        return 0.0
    finally:
        os.close(fd)


def _son_kullanim(kopya: Path, simdi: float) -> float:
    """When the copy was last used: the newest mtime of its cookie / session files (never later than now)."""
    zamanlar = []
    for ad in ("cookies.sqlite", "cookies.sqlite-wal", "sessionstore-backups/recovery.jsonlz4",
               "sessionstore-backups/recovery.baklz4", "sessionstore.jsonlz4"):
        try:
            zamanlar.append(os.lstat(kopya / ad).st_mtime)
        except OSError:
            pass
    return min(simdi, max(zamanlar)) if zamanlar else simdi


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
        self._yerel = threading.local()  # lock depth of this thread (_kilitli is re-entrant)

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

    @contextlib.contextmanager
    def _kilitli(self):
        """Cross-process exclusive lock of the store (review C1): flock on DATA_DIR/<ad>/.kilit (0600). Every path
        that writes or deletes records holds it (kaydet's read-merge-write, sil, sil_hepsi, unut, uygula's deletions),
        so two copies closing at once cannot overwrite each other's logins or tombstones, and forget --all cannot
        cut a write in half (C4). Re-entrant within a thread. Yields False (the caller changes nothing) when the store
        directory is not usable or the lock is not obtained in _KILIT_SURE seconds (logged)."""
        import fcntl
        if getattr(self._yerel, "derinlik", 0):
            self._yerel.derinlik += 1
            try:
                yield True
            finally:
                self._yerel.derinlik -= 1
            return
        d = self._dizin_hazirla()
        fd = -1
        if d is not None:
            try:
                fd = os.open(os.path.join(d, _KILIT_AD), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                os.fchmod(fd, 0o600)
            except OSError:
                if fd >= 0:
                    os.close(fd)
                fd = -1
        if fd < 0:
            yield False
            return
        try:
            son = _saat.monotonic() + _KILIT_SURE
            alindi = False
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    alindi = True
                    break
                except BlockingIOError:
                    if _saat.monotonic() > son:
                        break
                    _saat.sleep(0.05)
            if not alindi:
                from ..gunluk import gunluk
                gunluk(f"oturum: kalıcı depo kilidi {_KILIT_SURE:.0f} sn içinde alınamadı; hiçbir şey yazılmadı")
                yield False
                return
            self._yerel.derinlik = 1
            try:
                yield True
            finally:
                self._yerel.derinlik = 0
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def sil(self, site: str) -> bool:
        """Delete the record of a site (a plain record of the first release, and a leftover temporary file of an
        interrupted write: review Y3). → something was deleted."""
        if self._dosya(site) is None or not self._dizin_gecerli():
            return False
        with self._kilitli() as tamam:
            if not tamam:
                return False
            silindi = False
            for uzanti in (_UZANTI, _ESKI_UZANTI):
                yol = self._dosya(site, uzanti)
                if yol is None or not os.path.lexists(yol):
                    continue
                if uzanti == _ESKI_UZANTI:
                    _guvenli_sil(yol)
                else:
                    try:
                        os.unlink(yol)
                    except OSError:
                        continue
                silindi = True
            try:
                adlar = os.listdir(self.dizin())
            except OSError:
                adlar = []
            for a in adlar:  # .<site>.XXXX.tmp: an encrypted full record (writes hold the lock: none is in flight)
                if a.startswith(f".{site}.") and a.endswith(".tmp"):
                    try:
                        os.unlink(os.path.join(self.dizin(), a))
                    except OSError:
                        pass
            return silindi

    def sil_hepsi(self) -> int:
        """Delete every record. → number of sites deleted."""
        if not self._dizin_gecerli():
            return 0
        with self._kilitli() as tamam:
            if not tamam:
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

    # ---- forget (sessions forget): a lasting "forgotten at" time (review Y2)
    def _unutma_yolu(self, site: str | None) -> str:
        return os.path.join(self.dizin(), _HEPSI_UNUTULDU if site is None else f".{site}{_UNUTULDU}")

    def _unutma_yaz(self, site: str | None) -> None:
        d = self._dizin_hazirla()
        if d is None:
            return
        try:
            fd, gecici = tempfile.mkstemp(prefix=".unut-", suffix=".tmp", dir=d)
        except OSError:
            return
        try:
            with os.fdopen(fd, "w") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(repr(time.time()))
            os.replace(gecici, self._unutma_yolu(site))
        except OSError:
            try:
                os.unlink(gecici)
            except OSError:
                pass

    def _unutma_zamani(self, site: str) -> float | None:
        """When the site (or every site) was last forgotten; None = never."""
        zamanlar = []
        for s in (site, None):
            try:
                fd = os.open(self._unutma_yolu(s), os.O_RDONLY | os.O_NOFOLLOW)
            except OSError:
                continue
            try:
                v = float(os.read(fd, 64).decode("ascii", "replace").strip())
                if math.isfinite(v):
                    zamanlar.append(v)
            except (OSError, ValueError):
                zamanlar.append(time.time())  # unreadable marker: forgotten (closed-safe)
            finally:
                os.close(fd)
        return max(zamanlar) if zamanlar else None

    def unut_site(self, site: str) -> str | None:
        """The stored site `site` refers to (review Y4: same parser as the settings; www.<site> or any subdomain →
        the listed / stored parent site, the longest match), or None when the name is not a site."""
        adaylar = _siteler([site])
        if not adaylar:
            return None
        s = adaylar[0]
        if os.path.lexists(self._dosya(s) or ""):
            return s
        bilinen = set(self.kayitli_siteler()) | ayar_siteleri()
        ust = sorted((b for b in bilinen if s.endswith("." + b)), key=len, reverse=True)
        return ust[0] if ust else s

    def unut(self, site: str) -> bool:
        """sessions forget <site>: delete the record and leave a forgotten-at time, so a copy that is open now does
        not write the site back when it closes (review Y2). → a record was deleted (False: there is no record).
        KilitAlinamadi: the store lock was not obtained, nothing changed (review INC3 B7)."""
        s = self.unut_site(site)
        if s is None:
            return False
        with self._kilitli() as tamam:
            if not tamam:
                raise KilitAlinamadi(s)
            self._unutma_yaz(s)
            return self.sil(s)

    def unut_hepsi(self) -> int:
        """sessions forget --all (forgotten-at time for every site). KilitAlinamadi: lock not obtained (B7)."""
        with self._kilitli() as tamam:
            if not tamam:
                raise KilitAlinamadi("*")
            self._unutma_yaz(None)
            return self.sil_hepsi()

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
        kullanim = _son_kullanim(kopya, time.time())  # before reading: reading must not count as a use
        okunan = _kopya_cerezleri(kopya, kullanim)
        if okunan is None:
            return 0
        k = _anahtar(True)
        if k is None:
            return 0  # closed-fail: no plain-text fallback, existing records are kept
        with self._kilitli() as tamam:  # C1: one writer at a time across processes (read → merge → write)
            if not tamam:
                return 0
            return self._kaydet_kilitli(kopya, siteler, okunan, k, politika, kullanim)

    def _kaydet_kilitli(self, kopya: Path, siteler, okunan, k: bytes, politika, kullanim: float) -> int:
        cerezler, bilinen = okunan
        pol = politika or _politika()
        simdi = time.time()
        # a session-only cookie's deadline slides with its use (review C2): its own last access (never later than
        # the copy's last use; a dead copy may be swept days later) + N days. Unused → no renewal.
        omur = sure_gun() * 86400
        alinan_hepsi = _kopya_isareti_oku(kopya)
        acilis = _kopya_acilisi(self.dizin(), kopya)
        toplam = 0
        for site in siteler:
            unutma = self._unutma_zamani(site)
            if unutma is not None and acilis <= unutma:
                continue  # review Y2: forgotten while this copy was open; only a copy opened later may save it
            if not self.kabul(pol, site, ()):
                self.sil(site)
                continue
            onceki = self._oku(site, k)
            P = {_anahtar_demeti(c): c for c in (onceki or {}).get("cerezler", ())
                 if _gecerli_cerez(c) and float(c["expiry"]) > simdi}
            T0 = _canli_silinenler(onceki, simdi)
            Tm = dict(T0)
            alinan = alinan_hepsi.get(site) or {}
            C = {}
            for c in cerezler:
                if not _site_konagi(c["host"], site) or not self.kabul(pol, c["host"], bilinen):
                    continue
                if c["originAttributes"] and not c["originAttributes"].startswith("^"):
                    continue
                if not self._bolum_kabul(pol, c["originAttributes"]):
                    continue
                anahtar = _anahtar_demeti(c)
                bitis = c["expiry"]
                p = P.get(anahtar)
                eski = float(p["expiry"]) if p is not None and p.get("oturumluk") else None
                erisim = _tamsayi(c.get("lastAccessed")) / 1e6
                kayan = (min(kullanim, erisim) if erisim > 0 else kullanim) + omur
                if bitis is None:  # session-only: last access + N days
                    bitis, oturumluk = kayan, True
                elif eski is not None and abs(bitis - eski) <= _ESIT_PAYI:
                    bitis, oturumluk = kayan, True  # a stored session-only cookie that came back through cookies.sqlite
                else:
                    oturumluk = False
                if not _sayi(bitis) or bitis <= simdi:
                    continue
                C[anahtar] = {**c, "expiry": bitis, "oturumluk": oturumluk}
            # merge per cookie (security review items 1, 2): the newer use wins; a cookie this copy received from
            # the store and then dropped is a logout → tombstone (its value digest), which a stale copy cannot undo;
            # a cookie this copy never received (apply failed, record changed meanwhile, site not visited) stays
            sonuc = {}
            for anahtar, c in C.items():
                km, oz = _anahtar_metni(anahtar), _oz(c["value"])
                t = Tm.get(km)
                if t is not None and t["oz"] == oz:
                    continue  # the session that was logged out in another copy
                p = P.get(anahtar)
                if p is not None and p["value"] != c["value"] and \
                        _tamsayi(p.get("lastAccessed")) > _tamsayi(c.get("lastAccessed")):
                    sonuc[anahtar] = p
                else:
                    sonuc[anahtar] = c
                    Tm.pop(km, None)
            for anahtar, p in P.items():
                if anahtar in sonuc:
                    continue
                km, oz = _anahtar_metni(anahtar), _oz(p["value"])
                if anahtar not in C and alinan.get(km) == oz:
                    Tm[km] = {"oz": oz, "bitis": float(p["expiry"])}  # received exactly this and dropped it
                else:
                    sonuc[anahtar] = p
            if not sonuc and not Tm:
                self.sil(site)
                continue
            if onceki is not None and Tm == T0 and _ayni(sonuc, P):
                continue  # nothing changed: the record (and its save time) stays as it is
            if self._yaz(site, {"surum": SURUM, "site": site, "kayit": simdi, "cerezler": list(sonuc.values()),
                                "silinen": Tm}, k):
                toplam += len(sonuc)
        return toplam

    def _bolum_kabul(self, pol, oa: str) -> bool:
        """A partitioned cookie (originAttributes partitionKey) is accepted only when its top-level site passes the
        same rule (a bank page embedding the site must not leave a session here); a malformed key is refused."""
        s = _bolum_sitesi(oa)
        if s is None:
            return True
        return bool(s) and self.kabul(pol, s, ())

    def uygula(self, kopya, siteler, politika=None, gorev_siteleri=None, bilinen_konaklar=()) -> int:
        """Put the stored cookies of the listed sites into the copy's cookies.sqlite (not in task mode). Expired
        records are deleted. → number of cookies written."""
        from .. import gorev_kipi
        kopya = Path(kopya)
        siteler = _siteler(siteler)
        db = kopya / "cookies.sqlite"
        if not gorev_kipi.etkin() and kopya.is_dir() and (siteler or self._dizin_gecerli()):
            d = self._dizin_hazirla()
            if d is not None:
                _kopya_acilisi_yaz(d, kopya)  # review Y2: a forget after this moment wins over this copy's close
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
        alinan: dict[str, dict[str, str]] = {}
        con = sqlite3.connect(str(db))
        try:
            sutunlar = {r[1] for r in con.execute("PRAGMA table_info(moz_cookies)")}
            (enbuyuk,) = con.execute("SELECT MAX(expiry) FROM moz_cookies WHERE typeof(expiry) IN "
                                     "('integer', 'real')").fetchone()
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
                    if not _canli_silinenler(kayit, simdi) or float(kayit["kayit"]) > simdi + _GELECEK_PAYI:
                        self.sil(site)  # dead (a record that only keeps live tombstones stays)
                    continue
                kayit_bilinen = bilinen | {_konak(c["host"]).lstrip(".") for c in canli}
                for c in canli:
                    host = c["host"]
                    alan = _konak(host).lstrip(".")
                    if not _site_konagi(host, site) or not self.kabul(pol, host, kayit_bilinen):
                        continue
                    if not self._bolum_kabul(pol, c["originAttributes"]) or not pol.site_izinli(alan, gorev_siteleri):
                        continue
                    if self._satir_yaz(con, c, sutunlar, carpan, simdi):
                        yazilan += 1
                        alinan.setdefault(site, {})[_anahtar_metni(_anahtar_demeti(c))] = _oz(c["value"])
            con.commit()
        except (sqlite3.Error, OverflowError):
            con.rollback()
            yazilan, alinan = 0, {}
        finally:
            con.close()
        if alinan:  # which versions this copy received: its close may then tell a logout from "never had it"
            onceki_isaret = _kopya_isareti_oku(kopya)
            for s, m in alinan.items():
                onceki_isaret.setdefault(s, {}).update(m)
            _kopya_isareti_yaz(kopya, onceki_isaret)
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
            if not _gecerli_cerez(c) or not _site_konagi(c["host"], s) or not self.kabul(pol, c["host"], bilinen) or not self._bolum_kabul(pol, c["originAttributes"]):
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
    return DEPO.unut(site)


def unut_hepsi() -> int:
    return DEPO.unut_hepsi()


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
