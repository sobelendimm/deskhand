"""Persistent background sessions (docs/SESSIONS.md §3.8): a site the user lists in `[oturum] kalici` keeps the
session it gets in the background Firefox copy from one copy to the next.

Why: every background Firefox is a fresh, throw-away copy of the real profile (firefox.hazirla). A site where the user
logs in ONLY in the background (a seller panel) lost that login when the copy was deleted, so every new copy asked for
a login again (and the real profile never had it).

What:
  kaydet(kopya, siteler)  when a copy is deleted (kopya_bekcisi.bekle_ve_sil, kopya._sil / supur, oturum._kapanis_ic):
                          the copy's cookies of the listed sites are written to DATA_DIR/oturum-kalici/<site>.json
                          (directory 0700, file 0600, atomic). A site with no live cookie left (logged out) loses its
                          record.
  uygula(kopya, siteler)  when a new copy is prepared (firefox.hazirla, before the cookie database is rebuilt): the
                          stored cookies go into the copy's cookies.sqlite. A row already in the copy wins only when it is
                          still valid and was used later than the stored one.
  durum(site)             value-free summary for `sessions check` (denetle).

Lifetime: the source cookie's lifetime, at most ONE day from the save (the rule firefox._oturum_cerezleri_ekle applies to
session cookies). A session-only cookie (no expiry) is stored with save + 1 day. A record older than one day, or whose
cookies have all expired, is not applied and is deleted. Every save refreshes the day: a session used at least daily
stays; one left alone for a day is gone. The server's own session lifetime is not extended: a site that ends the
session on its side (a 2-hour sliding seller session) still asks for a login, and `sessions check` says so.

Never stored, never applied (checked at save AND at apply time, so a record written by hand or by an older release is
filtered as well):
  - bank / payment / government / central identity domains: the reject list of oturum.toml through
    Politika.site_reddedildi / Politika.cerez_reddedildi (every spelling: case, trailing dot, IDNA dots, Unicode and
    ACE). The panel's account-session permission does NOT open them here (the strict policy is used);
  - task mode (gorev_kipi): nothing is applied and a task copy (its user.js carries the task marker) is never saved;
  - sites not in the list, cookies of hosts outside the listed site, cookies of an unknown origin context.
Values are never printed or logged; durum() returns names, hosts and times only.

Extension point (Faz 4 P2, user decision 27 Kas): bank/payment sessions will live in a SECOND, locked store that is
applied only after the user's approval and only for that task. That store is another `Depo` instance with its own
directory name and its own `kabul` rule; the default store below keeps rejecting them.
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

OMUR_AZAMI = 86400            # a stored cookie never outlives save + 1 day
SURUM = 1
_DOSYA_AZAMI = 1024 * 1024    # a record larger than this is not read
_GELECEK_PAYI = 300           # a record "saved" this far in the future (clock change / hand edit) is dropped
_SITE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
_ALANLAR = ("host", "name", "value", "path", "originAttributes")


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


def _sn(deger, ms: bool) -> float | None:
    try:
        v = float(deger)
    except (TypeError, ValueError):
        return None
    return v / 1000 if ms else v


def _kopya_cerezleri(kopya: Path) -> tuple[list[dict], set[str]] | None:
    """Cookies of the copy (cookies.sqlite read from a consistent temporary 0700 copy, plus the copy's own
    sessionstore recovery file when Firefox wrote one) and the hosts known in the copy. None = unreadable."""
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
                         "creationTime": int(r[7] or 0), "isSecure": int(bool(r[8])), "isHttpOnly": int(bool(r[9])),
                         "oturumluk": False}
                    for i, s in enumerate(ek):
                        c[s] = int(r[10 + i] or 0)
                    sonuc.append(c)
            finally:
                con.close()
    except (sqlite3.Error, OSError):
        return None
    rec = firefox._recovery_oku(str(kopya / "sessionstore-backups" / "recovery.jsonlz4"))
    mikro = int(time.time() * 1e6)
    for c in rec.get("cookies") or ():
        if not isinstance(c, dict):
            continue
        oa = firefox.oa_soneki(c.get("originAttributes", ""))
        if oa is None:
            continue
        bitis = firefox._kaynak_bitis(c)
        sonuc.append({"originAttributes": oa, "name": str(c.get("name", "")), "value": str(c.get("value", "")),
                      "host": str(c.get("host", "")), "path": str(c.get("path", "/")), "expiry": bitis,
                      "lastAccessed": mikro, "creationTime": mikro, "isSecure": int(bool(c.get("secure"))),
                      "isHttpOnly": int(bool(c.get("httponly"))), "sameSite": int(c.get("sameSite", 0) or 0),
                      "schemeMap": int(c.get("schemeMap", 0) or 0),
                      "isPartitionedAttributeSet": int(bool(c.get("isPartitioned"))), "oturumluk": bitis is None})
    bilinen = {_konak(c["host"]).lstrip(".") for c in sonuc}
    try:
        bilinen |= firefox._bilinen_konaklar(str(kopya), str(db), rec)
    except (sqlite3.Error, OSError):
        pass
    return sonuc, bilinen


def _sayi(v) -> bool:
    """A finite JSON number (json.loads accepts NaN / Infinity; a bool is not a number here)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _gecerli_cerez(c) -> bool:
    """Structure check of a stored cookie (a record may have been edited by hand)."""
    if not isinstance(c, dict) or not all(isinstance(c.get(k), str) for k in _ALANLAR):
        return False
    if not _sayi(c.get("expiry")):
        return False
    oa = c["originAttributes"]
    return bool(c["host"]) and (oa == "" or oa.startswith("^"))


class Depo:
    """One cookie store: DATA_DIR/<ad>/<site>.json. `kabul(politika, host, bilinen_konaklar) -> bool` decides which
    hosts may be stored and applied (the site itself is checked with the same rule and no known hosts)."""

    def __init__(self, ad: str, kabul=_ret_disi):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", ad):
            raise ValueError(ad)
        self.ad = ad
        self.kabul = kabul

    # ---- files
    def dizin(self) -> str:
        return os.path.join(yollar.data_dir(), self.ad)

    def _dosya(self, site: str) -> str | None:
        return os.path.join(self.dizin(), f"{site}.json") if _SITE.fullmatch(site or "") else None

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

    def _oku(self, site: str) -> dict | None:
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
            with os.fdopen(fd, "rb") as f:
                fd = -1
                d = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError):
            return None
        finally:
            if fd >= 0:
                os.close(fd)
        if not isinstance(d, dict) or d.get("site") != site or not isinstance(d.get("cerezler"), list):
            return None
        if not _sayi(d.get("kayit")):
            return None
        return d

    def _yaz(self, site: str, kayit: dict) -> bool:
        d = self._dizin_hazirla()
        yol = self._dosya(site)
        if d is None or yol is None:
            return False
        gecici = os.path.join(d, f".{site}.{os.getpid()}.tmp")
        try:
            try:
                os.unlink(gecici)
            except FileNotFoundError:
                pass
            fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                os.fchmod(f.fileno(), 0o600)
                json.dump(kayit, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(gecici, yol)
            return True
        except OSError:
            try:
                os.unlink(gecici)
            except OSError:
                pass
            return False

    def sil(self, site: str) -> None:
        yol = self._dosya(site)
        if yol is None or not self._dizin_gecerli():
            return
        try:
            if not os.path.islink(yol):
                os.unlink(yol)
        except OSError:
            pass

    # ---- lifetime
    @staticmethod
    def _canli_cerezler(kayit: dict, simdi: float) -> list[dict]:
        """Live cookies of a record: well-formed, not expired, not beyond save + 1 day. [] = the record is dead."""
        zaman = float(kayit["kayit"])
        if zaman > simdi + _GELECEK_PAYI or simdi - zaman >= OMUR_AZAMI:
            return []
        tavan = zaman + OMUR_AZAMI
        return [c for c in kayit["cerezler"] if _gecerli_cerez(c) and simdi < float(c["expiry"]) <= tavan]

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
        cerezler, bilinen = okunan
        pol = politika or _politika()
        simdi = time.time()
        tavan = simdi + OMUR_AZAMI
        toplam = 0
        for site in siteler:
            if not self.kabul(pol, site, ()):
                self.sil(site)
                continue
            secilen = {}
            for c in cerezler:
                if not _site_konagi(c["host"], site) or not self.kabul(pol, c["host"], bilinen):
                    continue
                if c["originAttributes"] and not c["originAttributes"].startswith("^"):
                    continue
                bitis = c["expiry"]
                if bitis is not None and bitis <= simdi:
                    continue
                anahtar = (c["name"], c["host"], c["path"], c["originAttributes"])
                secilen[anahtar] = {**c, "expiry": min(bitis if bitis is not None else tavan, tavan),
                                    "oturumluk": bool(c.get("oturumluk") or bitis is None)}
            if not secilen:
                self.sil(site)  # logged out / nothing left: the old record must not bring the session back
                continue
            if self._yaz(site, {"surum": SURUM, "site": site, "kayit": simdi, "cerezler": list(secilen.values())}):
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
                kayit = self._oku(site)
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
        anahtar = (c["name"], c["host"], c["path"], c["originAttributes"])
        ek = [s for s in ("sameSite", "schemeMap", "isPartitionedAttributeSet") if s in sutunlar]
        if "updateTime" in sutunlar:
            ek.append("updateTime")
        try:  # a hand-edited record may carry anything in these fields: such a cookie is skipped
            erisim = int(c.get("lastAccessed") or 0)
            olusma = int(c.get("creationTime") or erisim)
            degerler = [int(c.get(s, 0) or 0) if s != "updateTime" else erisim for s in ek]
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
                    (c["originAttributes"], c["name"], c["value"], c["host"], c["path"],
                     int(float(c["expiry"]) * carpan), erisim, olusma, int(bool(c.get("isSecure"))),
                     int(bool(c.get("isHttpOnly"))), *degerler))
        return 1

    def durum(self, site: str, siteler=None, simdi: float | None = None) -> dict:
        """Value-free summary for `sessions check` (READ ONLY: nothing is deleted). Cookies that would be sent to
        `site` (its own, its subdomains', parent-domain cookies of the listed site), expired ones flagged."""
        alan = _konak(site).lstrip(".")
        liste = ayar_siteleri() if siteler is None else set(_siteler(siteler))
        eslesen = sorted((s for s in liste if alan == s or alan.endswith("." + s)), key=len, reverse=True)
        d = {"site": alan, "listede": bool(eslesen), "depo_site": eslesen[0] if eslesen else None,
             "reddedildi": False, "kayit": None, "cerezler": []}
        if not eslesen:
            return d
        s = eslesen[0]
        pol = _politika()
        if not self.kabul(pol, s, ()):
            d["reddedildi"] = True
            return d
        kayit = self._oku(s)
        if kayit is None:
            return d
        simdi = time.time() if simdi is None else simdi
        zaman = float(kayit["kayit"])
        d["kayit"] = zaman
        tavan = zaman + OMUR_AZAMI
        bilinen = {_konak(c.get("host")).lstrip(".") for c in kayit["cerezler"] if isinstance(c, dict)}
        for c in kayit["cerezler"]:
            if not _gecerli_cerez(c) or not _site_konagi(c["host"], s) or not self.kabul(pol, c["host"], bilinen):
                continue
            h = _konak(c["host"])
            dh = h.lstrip(".")
            if not (dh == alan or dh.endswith("." + alan) or (h.startswith(".") and alan.endswith("." + dh))):
                continue
            bitis = min(float(c["expiry"]), tavan)
            d["cerezler"].append({"ad": c["name"], "konak": c["host"], "bitis": bitis,
                                  "oturumluk": bool(c.get("oturumluk")),
                                  "gecmis": bitis <= simdi or zaman > simdi + _GELECEK_PAYI})
        return d


DEPO = Depo("oturum-kalici")


def kaydet(kopya, siteler, politika=None) -> int:
    return DEPO.kaydet(kopya, siteler, politika)


def uygula(kopya, siteler, politika=None, gorev_siteleri=None, bilinen_konaklar=()) -> int:
    return DEPO.uygula(kopya, siteler, politika, gorev_siteleri, bilinen_konaklar)


def durum(site: str, siteler=None, simdi: float | None = None) -> dict:
    return DEPO.durum(site, siteler, simdi)


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
