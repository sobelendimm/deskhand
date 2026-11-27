"""Persistent background sessions (deskhand/oturum/kalici.py, docs/SESSIONS.md §3.8) — EKRANSIZ; the real Firefox
profile is never touched (fake HOME in a temporary folder, fake profiles.ini + cookies.sqlite; made-up *.test domains).

Plan H3 red list 1a–1h, plus: the `sessions check` report line (2a/2b), the other copy-deletion paths (masaüstü
kapanışı, süpürme: 3a/3b), the `[oturum] kalici` setting (4a/4b) and value-free durum() (5).

Çalıştır:  python3 tests/test_oturum_kalici.py
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import _yalitim  # noqa: F401  (DESKHAND_* geçici; Deskhand'den ÖNCE)

from deskhand import ayarlar, gorev_kipi, yollar
from deskhand.oturum import firefox, kopya, kopya_bekcisi, politika

try:
    from deskhand.oturum import kalici
except ImportError:  # old code: every check below fails (counted), none crashes
    kalici = None

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def dene(ad, fn, ek=""):
    """kontrol(ad, fn()); an exception counts as a failure (red on old code without crashing the suite)."""
    try:
        sonuc = fn()
    except Exception as e:  # noqa: BLE001
        kontrol(ad, False, f"{type(e).__name__}: {e}")
        return
    kontrol(ad, sonuc, ek() if callable(ek) else ek)


_SEMA = (
    "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
    "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, "
    "creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, "
    "sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER DEFAULT 0, "
    "updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))")

SIMDI = time.time()
GUN = 86400
ACE_BANKA = "örnekbank.test".encode("idna").decode()  # xn--…bank-… : the `*bank*` rule against the ACE spelling


def _ms(sn):
    return int((time.time() + sn) * 1000)


def cerez_yaz(db, satirlar, erisim=None):
    """satirlar: (host, name, value, expiry_ms)."""
    yeni = not os.path.exists(db)
    con = sqlite3.connect(db)
    if yeni:
        con.execute(_SEMA)
    mikro = int((erisim if erisim is not None else time.time()) * 1e6)
    for host, name, value, exp in satirlar:
        con.execute("INSERT OR REPLACE INTO moz_cookies (originAttributes,name,value,host,path,expiry,lastAccessed,"
                    "creationTime,isSecure,isHttpOnly,updateTime) VALUES ('',?,?,?,'/',?,?,?,1,1,?)",
                    (name, value, host, exp, mikro, mikro, mikro))
    con.commit()
    con.close()


def cerezler(kopya_yolu):
    con = sqlite3.connect(os.path.join(kopya_yolu, "cookies.sqlite"))
    try:
        return {(r[0], r[1]): (r[2], r[3]) for r in con.execute("SELECT host, name, value, expiry FROM moz_cookies")}
    finally:
        con.close()


def mozlz4_yaz(yol, obj):
    import struct

    import lz4.block
    ham = json.dumps(obj).encode()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "wb") as f:
        f.write(b"mozLz40\0" + struct.pack("<I", len(ham)) + lz4.block.compress(ham, store_size=False))


def sahte_profil(kok):
    prof = "zz99.default-release"
    pdir = os.path.join(kok, prof)
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(kok, "profiles.ini"), "w") as f:
        f.write(f"[Profile0]\nName=d\nIsRelative=1\nPath={prof}\nDefault=1\n\n[InstallX]\nDefault={prof}\nLocked=1\n")
    cerez_yaz(os.path.join(pdir, "cookies.sqlite"), [
        ("www.dukkan.test", "sec_session_id", "PROFIL-ESKI", _ms(7200)),
        ("liste-disi.test", "sid", "PROFIL-LISTE-DISI", _ms(7200)),
    ], erisim=SIMDI - 3600)
    for ad in ("key4.db", "cert9.db", "prefs.js"):
        with open(os.path.join(pdir, ad), "w") as f:
            f.write("x")
    return pdir


def sha1(yol):
    with open(yol, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def depo_dizini():
    return os.path.join(yollar.data_dir(), "oturum-kalici")


def depo_metni():
    """Every byte of every file in the store, as text (to prove which values are NOT stored)."""
    d = depo_dizini()
    parcalar = []
    if os.path.isdir(d):
        for ad in sorted(os.listdir(d)):
            with open(os.path.join(d, ad), "rb") as f:
                parcalar.append(f.read().decode("utf-8", "replace"))
    return "\n".join(parcalar)


def ayar_yaz(metin):
    os.makedirs(os.path.dirname(ayarlar.dosya()), exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write(f'[oturum]\nkalici = "{metin}"\n')


def yeni_kopya():
    b = firefox.hazirla(politika.coz("firefox"))
    if b.get("durum") or not b.get("kopya_yolu"):
        raise RuntimeError(f"kopya hazırlanamadı: {b.get('durum')}")
    return b["kopya_yolu"]


def kapat(yol, umask=None):
    """Simulates the browser exiting: the copy watchdog (bekle_ve_sil) with a dead owner pid."""
    eski = os.umask(umask) if umask is not None else None
    try:
        return kopya_bekcisi.bekle_ve_sil(os.path.dirname(yol), yol, 0, None, aralik=0.05, azami=20, son_pay=0)
    finally:
        if eski is not None:
            os.umask(eski)


def kayit_duzenle(site, fn):
    """Edit a stored record by hand; no record (old code) → False, the checks that depend on it fail."""
    yol = os.path.join(depo_dizini(), f"{site}.json")
    try:
        with open(yol) as f:
            d = json.load(f)
        fn(d)
        with open(yol, "w") as f:
            json.dump(d, f)
        os.chmod(yol, 0o600)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def main():
    tdir = tempfile.mkdtemp(prefix="deskhand-kalici-src-")
    eski_home, eski_xdg = os.environ.get("HOME"), os.environ.get("XDG_CONFIG_HOME")
    os.environ["HOME"] = tdir
    os.environ.pop("XDG_CONFIG_HOME", None)
    for ad in (gorev_kipi.ORTAM, gorev_kipi.SITE_ORTAM):
        os.environ.pop(ad, None)
    try:
        fx_kok = os.path.join(tdir, ".config", "mozilla", "firefox")
        pdir = sahte_profil(fx_kok)
        izler = {y: sha1(y) for y in (os.path.join(fx_kok, "profiles.ini"), os.path.join(pdir, "cookies.sqlite"))}
        ayar_yaz(f"dukkan.test, ornekbank.test, {ACE_BANKA}, isbank.com.tr, panel.test")

        # ---- a background session: the agent logs in inside the copy, then the browser exits
        k1 = yeni_kopya()
        cerez_yaz(os.path.join(k1, "cookies.sqlite"), [
            ("www.dukkan.test", "sec_session_id", "ARKA-GIRIS", _ms(7200)),
            (".dukkan.test", "remember_me", "ARKA-UZUN", _ms(30 * GUN)),
            ("eski.dukkan.test", "sid", "ARKA-GECMIS", _ms(-60)),
            ("liste-disi.test", "sid", "ARKA-LISTE-DISI", _ms(7200)),
            ("www.ornekbank.test", "sessionid", "ARKA-BANKA", _ms(7200)),
            (f"www.{ACE_BANKA}", "sessionid", "ARKA-BANKA-ACE", _ms(7200)),
            (".ISBANK.com.tr.", "sessionid", "ARKA-ISBANK", _ms(7200)),
        ])
        silindi = kapat(k1, umask=0)
        kontrol("kopya kapanınca bekçi kopyayı siler", silindi and not os.path.exists(k1))
        dukkan = os.path.join(depo_dizini(), "dukkan.test.json")
        dene("1a: listedeki alanın oturum çerezi kopya kapanınca depoya yazılır",
             lambda: os.path.isfile(dukkan) and "ARKA-GIRIS" in depo_metni(), lambda: depo_metni()[:200])
        dene("1a': süresi geçmiş çerez depoya yazılmaz", lambda: "ARKA-GECMIS" not in depo_metni())
        dene("1c: listede olmayan alan yazılmaz",
             lambda: os.path.isfile(dukkan) and "LISTE-DISI" not in depo_metni()
             and not os.path.exists(os.path.join(depo_dizini(), "liste-disi.test.json")))
        dene("1d: banka alanı listede olsa da reddedilir (`*bank*` düz + ACE, büyük harf/sondaki nokta)",
             lambda: os.path.isfile(dukkan) and not any(v in depo_metni() for v in
                                                        ("ARKA-BANKA", "ARKA-BANKA-ACE", "ARKA-ISBANK"))
             and sorted(os.listdir(depo_dizini())) == ["dukkan.test.json"],
             lambda: str(os.listdir(depo_dizini())) if os.path.isdir(depo_dizini()) else "depo yok")
        dene("1e: depo 0600, dizin 0700 (umask 0 iken de)",
             lambda: (os.stat(depo_dizini()).st_mode & 0o777) == 0o700
             and all((os.stat(os.path.join(depo_dizini(), a)).st_mode & 0o777) == 0o600
                     for a in os.listdir(depo_dizini())) and os.listdir(depo_dizini()))

        # ---- next background browser: the saved session comes back
        k2 = yeni_kopya()
        c2 = cerezler(k2)
        tavan = (time.time() + GUN) * 1000 + 5000
        dene("1b: yeni kopyada geri yüklenir, ömür ≤ 1 gün",
             lambda: c2[("www.dukkan.test", "sec_session_id")][0] == "ARKA-GIRIS"
             and c2[(".dukkan.test", "remember_me")][0] == "ARKA-UZUN"
             and c2[(".dukkan.test", "remember_me")][1] <= tavan
             and c2[("www.dukkan.test", "sec_session_id")][1] <= tavan, lambda: str(c2))
        dene("1b': listede olmayan alanın kopyası profilden gelir (depodan değil)",
             lambda: c2[("liste-disi.test", "sid")][0] == "PROFIL-LISTE-DISI")

        # a record for a bank domain written by hand (tampered / older release) is never applied
        def banka_kaydi():
            kaynak = os.path.join(depo_dizini(), "dukkan.test.json")
            with open(kaynak) as f:
                d = json.load(f)
            d["site"] = "ornekbank.test"
            for c in d.get("cerezler", ()):
                c["host"] = "www.ornekbank.test"
                c["value"] = "SAHTE-BANKA"
            yol = os.path.join(depo_dizini(), "ornekbank.test.json")
            with open(yol, "w") as f:
                json.dump(d, f)
            os.chmod(yol, 0o600)
            return kalici.uygula(Path(k2), {"ornekbank.test"}) == 0 and \
                all(v[0] != "SAHTE-BANKA" for v in cerezler(k2).values())
        dene("1d': elle yazılmış banka kaydı uygulanmaz", banka_kaydi)
        kopya.temizle(k2)

        # ---- task mode: the store is neither applied nor written
        os.environ[gorev_kipi.ORTAM] = "1"
        os.environ[gorev_kipi.SITE_ORTAM] = "dukkan.test"
        try:
            k3 = yeni_kopya()
            c3 = cerezler(k3)
            once = depo_metni()
            cerez_yaz(os.path.join(k3, "cookies.sqlite"), [("www.dukkan.test", "sec_session_id", "GOREV-GIRIS", _ms(60))])
            dene("1f: görev kipinde uygulanmaz",
                 lambda: c3.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI"
                 and kalici.uygula(Path(k3), {"dukkan.test"}) == 0, lambda: str(c3))
        finally:
            os.environ.pop(gorev_kipi.ORTAM, None)
            os.environ.pop(gorev_kipi.SITE_ORTAM, None)
        kapat(k3)
        dene("1f': görev kopyası kapanınca depoya yazılmaz", lambda: "GOREV-GIRIS" not in depo_metni()
             and depo_metni() == once)

        # ---- expiry: an expired record is not applied and is deleted
        def gecmis_cerez(d):
            for c in d["cerezler"]:
                c["expiry"] = time.time() - 10
        duzenlendi = kayit_duzenle("dukkan.test", gecmis_cerez)
        k4 = yeni_kopya()
        c4 = cerezler(k4)
        gecti_1 = duzenlendi and c4.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI" and not os.path.exists(dukkan)
        kopya.temizle(k4)
        # a record older than one day whose cookies claim a later expiry (written by hand): not applied, deleted
        k5 = yeni_kopya()
        cerez_yaz(os.path.join(k5, "cookies.sqlite"), [("www.dukkan.test", "sec_session_id", "ESKI-KAYIT", _ms(7200))])
        kapat(k5)

        def eski_kayit(d):
            d["kayit"] = time.time() - 2 * GUN
            for c in d["cerezler"]:
                c["expiry"] = time.time() + 3600
        duzenlendi = kayit_duzenle("dukkan.test", eski_kayit)
        k6 = yeni_kopya()
        c6 = cerezler(k6)
        dene("1g: süresi geçmiş kayıt uygulanmaz ve silinir",
             lambda: gecti_1 and duzenlendi and c6.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI"
             and not os.path.exists(dukkan), lambda: f"{gecti_1} {c6.get(('www.dukkan.test', 'sec_session_id'))}")
        kopya.temizle(k6)

        # ---- sessions check: the store is part of the answer (no copy, the real profile has no session)
        from deskhand.oturum import cli, denetle
        k7 = yeni_kopya()
        cerez_yaz(os.path.join(k7, "cookies.sqlite"), [("panel.test", "sec_session_id", "PANEL-GIRIS", _ms(7200))])
        # a session-only cookie the site set in the background (Firefox keeps it only in the copy's sessionstore)
        mozlz4_yaz(os.path.join(k7, "sessionstore-backups", "recovery.jsonlz4"), {"cookies": [
            {"host": "panel.test", "name": "PHPSESSID", "value": "PANEL-OTURUM", "path": "/",
             "originAttributes": {"userContextId": 0, "privateBrowsingId": 0}}]})
        kapat(k7)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kod = cli.main(["check", "panel.test"])
        cikti = out.getvalue()
        dene("2a: sessions check kalıcı depo satırını gösterir, değer yok",
             lambda: "kalıcı depo" in cikti and "PANEL-GIRIS" not in cikti and "PANEL-OTURUM" not in cikti, cikti)
        dene("2b: kopya yok, profilde oturum yok, depoda geçerli giriş → 0", lambda: kod == 0, cikti)
        d = denetle.denetle("panel.test", simdi=time.time() + 3 * 3600)
        dene("2b': kopyanın oturumluk çerezi (sessionstore) de depoya yazılır", lambda: "PANEL-OTURUM" in depo_metni())
        dene("2c: depodaki giriş çerezinin süresi geçmiş → giriş gerekli (1)",
             lambda: d["kod"] == 1 and d["kalici"]["durum"] == "suresi_gecmis", str(d.get("kalici")))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["check", "panel.test", "--json"])
        dene("2d: JSON çıktısında değer yok", lambda: "PANEL-" not in out.getvalue() and '"kalici"' in out.getvalue())

        # ---- a record others could have written (group/other bits) or with a non-finite time is not read
        def genis_izin():
            yol = os.path.join(depo_dizini(), "panel.test.json")
            os.chmod(yol, 0o644)
            try:
                return kalici.durum("panel.test")["kayit"] is None
            finally:
                os.chmod(yol, 0o600)

        def nan_kayit():
            yol = os.path.join(depo_dizini(), "panel.test.json")
            with open(yol) as f:
                ham = f.read()
            d = json.loads(ham)
            d["kayit"] = float("nan")
            with open(yol, "w") as f:
                json.dump(d, f)
            try:
                return kalici.durum("panel.test")["kayit"] is None
            finally:
                with open(yol, "w") as f:
                    f.write(ham)
        dene("1e': başkasının yazabileceği (0644) kayıt okunmaz", genis_izin)
        dene("1g': sonlu olmayan (NaN) kayıt zamanı okunmaz", nan_kayit)

        # ---- the other copy-deletion paths save too
        from deskhand import oturum
        k8 = yeni_kopya()
        cerez_yaz(os.path.join(k8, "cookies.sqlite"), [("panel.test", "sec_session_id", "KAPANIS-GIRIS", _ms(7200))])
        oturum._kapanis_ic()
        dene("3a: masaüstü kapanışı (kopya silinmeden önce) depoya yazar",
             lambda: not os.path.exists(k8) and "KAPANIS-GIRIS" in depo_metni())
        k9 = yeni_kopya()
        cerez_yaz(os.path.join(k9, "cookies.sqlite"), [("panel.test", "sec_session_id", "SUPUR-GIRIS", _ms(7200))])
        kopya_bekcisi.sahip_yaz(k9, {"pid": 2 ** 22 + 7, "bas": "1", "zaman": time.time() - 3600})
        silinen = kopya.supur()
        dene("3b: sahipsiz kopya süpürülürken depoya yazar",
             lambda: k9 in silinen and "SUPUR-GIRIS" in depo_metni(), str(silinen))

        # ---- the setting
        dene("4a: [oturum] kalici normalleşir (adres, büyük harf, tekrar)",
             lambda: ayarlar.dogrula("oturum", "kalici", "Shopier.com, https://www.x.test/a, shopier.com")
             == "shopier.com,www.x.test")

        def ret(deger):
            try:
                ayarlar.dogrula("oturum", "kalici", deger)
            except ValueError:
                return True
            return False
        dene("4b: joker ve tek başına genel son ek reddedilir", lambda: ret("*.test") and ret("com.tr"))

        dene("5: durum() değer içermez",
             lambda: kalici.durum("panel.test")["listede"] and "PANEL" not in json.dumps(kalici.durum("panel.test"))
             and "SUPUR-GIRIS" not in json.dumps(kalici.durum("panel.test")))

        dene("1h: gerçek profil dosyaları (profiles.ini, cookies.sqlite) sha1 aynı",
             lambda: all(sha1(y) == s for y, s in izler.items()))
    finally:
        if eski_home:
            os.environ["HOME"] = eski_home
        if eski_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = eski_xdg
        shutil.rmtree(tdir, ignore_errors=True)
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
