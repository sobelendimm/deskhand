"""Persistent background sessions (deskhand/oturum/kalici.py, docs/SESSIONS.md §3.8) — EKRANSIZ; the real Firefox
profile is never touched (fake HOME in a temporary folder, fake profiles.ini + cookies.sqlite; made-up *.test domains)
and the real Secret Service / KDE Wallet is never touched (a fake key ring is injected: kalici.anahtarlik_ayarla;
_yalitim also sets DESKHAND_ANAHTARLIK=kapali so the real backend refuses inside tests).

Plan H3 red list 1a–1h, plus: the `sessions check` report line (2a–2d), the other copy-deletion paths (masaüstü
kapanışı, süpürme: 3a/3b), the settings (4a–4d), value-free durum() (5), and H3-2 (user decision 27 Kas: encrypted,
no one-day cap): 6a encrypted on disk, 6b wrong key / corrupt data, 6c no key ring, 6d AAD, 6e lifetime, 6f forget,
6g old plain records, 6h doctor row.

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

from deskhand import ayarlar, gorev_kipi, liste_koruma, yollar
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
    try:
        ek = ek() if callable(ek) else ek
    except Exception as e:  # noqa: BLE001
        ek = f"{type(e).__name__}: {e}"
    kontrol(ad, sonuc, ek)


def sessiz(fn, *a, **k):
    """Call for setup steps whose failure is reported by the checks that follow (old code)."""
    try:
        return fn(*a, **k)
    except Exception:  # noqa: BLE001
        return None


_SEMA = (
    "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
    "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, "
    "creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, "
    "sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER DEFAULT 0, "
    "updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))")

SIMDI = time.time()
GUN = 86400
ACE_BANKA = "örnekbank.test".encode("idna").decode()  # xn--…bank-… : the `*bank*` rule against the ACE spelling


class SahteAnahtarlik:
    """Fake key ring (no D-Bus): one 32-byte key in memory; `neden` set = unavailable (locked wallet…)."""

    def __init__(self):
        self.k = None
        self.neden = None
        self.okuma = 0

    def anahtar(self, olustur):
        self.okuma += 1
        if self.neden:
            raise kalici.AnahtarYok(self.neden)
        if self.k is None:
            if not olustur:
                raise kalici.AnahtarYok("anahtar yok", yok=True)
            self.k = os.urandom(32)
        return self.k


class SahteZaman:
    """kalici.time replacement: the clock moved by `kayma` seconds."""

    def __init__(self, kayma):
        self.kayma = kayma

    def time(self):
        return time.time() + self.kayma


@contextlib.contextmanager
def zaman_kaydir(sn):
    eski = kalici.time
    kalici.time = SahteZaman(sn)
    try:
        yield
    finally:
        kalici.time = eski


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


def depo_dosyalari():
    d = depo_dizini()
    # records only: the lock (.kilit) and forget markers (.<site>.unutuldu) are dot files
    return sorted(a for a in os.listdir(d) if not a.startswith(".")) if os.path.isdir(d) else []


def depo_ham():
    """Every byte of every file in the store (what an attacker reading the disk sees)."""
    parcalar = []
    for ad in depo_dosyalari():
        with open(os.path.join(depo_dizini(), ad), "rb") as f:
            parcalar.append(f.read())
    return b"\n".join(parcalar)


def kayit(site):
    """The decrypted record of a site (via the store itself) or None."""
    try:
        return kalici.DEPO._oku(site)
    except Exception:  # noqa: BLE001
        return None


def depo_metni():
    """The decrypted contents of every record (to prove which values are / are NOT stored)."""
    parcalar = []
    for ad in depo_dosyalari():
        site = ad.rsplit(".", 1)[0]
        parcalar.append(json.dumps(kayit(site), ensure_ascii=False))
    return "\n".join(parcalar)


def kayit_yolu(site):
    return os.path.join(depo_dizini(), f"{site}.kayit")


def ayar_yaz(metin, sure=None):
    os.makedirs(os.path.dirname(ayarlar.dosya()), exist_ok=True)
    with open(ayarlar.dosya(), "w") as f:
        f.write(f'[oturum]\nkalici = "{metin}"\n' + (f"kalici_sure_gun = {sure}\n" if sure else ""))


def panel_ac():
    """This process acts as the panel (liste_koruma) and the user approves the sites written in the file."""
    try:
        liste_koruma.panel_durdur()
        return liste_koruma.panel_baslat(onayla=lambda siteler: True)
    except TypeError:  # before the list was panel-authoritative (b72755f, 37d25b7): the file was read directly
        return None


def panel_tazele():
    if liste_koruma.AKTIF is not None:
        liste_koruma.AKTIF.denetle()


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
    """Edit a stored record through the store (decrypt → change → encrypt); no record → False."""
    try:
        d = kalici.DEPO._oku(site)
        if d is None:
            return False
        fn(d)
        return bool(kalici.DEPO._yaz(site, d))
    except Exception:  # noqa: BLE001
        return False


def cli_kos(argv):
    from deskhand.oturum import cli
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            kod = cli.main(argv)
    except SystemExit as e:  # argparse (old code: unknown command)
        kod = e.code
    return kod, out.getvalue()


def main():
    tdir = tempfile.mkdtemp(prefix="deskhand-kalici-src-")
    eski_home, eski_xdg = os.environ.get("HOME"), os.environ.get("XDG_CONFIG_HOME")
    os.environ["HOME"] = tdir
    os.environ.pop("XDG_CONFIG_HOME", None)
    for ad in (gorev_kipi.ORTAM, gorev_kipi.SITE_ORTAM):
        os.environ.pop(ad, None)
    anahtarlik = SahteAnahtarlik()
    sessiz(lambda: kalici.anahtarlik_ayarla(anahtarlik))
    try:
        fx_kok = os.path.join(tdir, ".config", "mozilla", "firefox")
        pdir = sahte_profil(fx_kok)
        izler = {y: sha1(y) for y in (os.path.join(fx_kok, "profiles.ini"), os.path.join(pdir, "cookies.sqlite"))}
        ayar_yaz(f"dukkan.test, ornekbank.test, {ACE_BANKA}, isbank.com.tr, panel.test")
        panel_ac()  # the list is panel-authoritative: this process is the panel, the user approves the file's sites

        # ---- a background session: the agent logs in inside the copy, then the browser exits
        k1 = yeni_kopya()
        cerez_yaz(os.path.join(k1, "cookies.sqlite"), [
            ("www.dukkan.test", "sec_session_id", "ARKA-GIRIS", _ms(7200)),
            (".dukkan.test", "remember_me", "ARKA-UZUN", _ms(10 * GUN)),
            ("www.dukkan.test", "sess0", "ARKA-SIFIR", 0),  # expiry 0: a session-only cookie
            ("eski.dukkan.test", "sid", "ARKA-GECMIS", _ms(-60)),
            ("liste-disi.test", "sid", "ARKA-LISTE-DISI", _ms(7200)),
            ("www.ornekbank.test", "sessionid", "ARKA-BANKA", _ms(7200)),
            (f"www.{ACE_BANKA}", "sessionid", "ARKA-BANKA-ACE", _ms(7200)),
            (".ISBANK.com.tr.", "sessionid", "ARKA-ISBANK", _ms(7200)),
        ])
        silindi = kapat(k1, umask=0)
        kontrol("kopya kapanınca bekçi kopyayı siler", silindi and not os.path.exists(k1))
        dukkan = kayit_yolu("dukkan.test")
        dene("1a: listedeki alanın oturum çerezi kopya kapanınca depoya yazılır",
             lambda: os.path.isfile(dukkan) and "ARKA-GIRIS" in depo_metni(), lambda: str(depo_dosyalari()))
        dene("1a': süresi geçmiş çerez depoya yazılmaz", lambda: "ARKA-GECMIS" not in depo_metni())
        dene("1c: listede olmayan alan yazılmaz",
             lambda: os.path.isfile(dukkan) and "LISTE-DISI" not in depo_metni()
             and not any(a.startswith("liste-disi") for a in depo_dosyalari()))
        dene("1d: banka alanı listede olsa da reddedilir (`*bank*` düz + ACE, büyük harf/sondaki nokta)",
             lambda: os.path.isfile(dukkan) and not any(v in depo_metni() for v in
                                                        ("ARKA-BANKA", "ARKA-BANKA-ACE", "ARKA-ISBANK"))
             and depo_dosyalari() == ["dukkan.test.kayit"], lambda: str(depo_dosyalari()))
        dene("1e: depo 0600, dizin 0700 (umask 0 iken de)",
             lambda: (os.stat(depo_dizini()).st_mode & 0o777) == 0o700
             and all((os.stat(os.path.join(depo_dizini(), a)).st_mode & 0o777) == 0o600
                     for a in depo_dosyalari()) and depo_dosyalari())
        # H3-2: encrypted at rest
        ham = depo_ham()
        dene("6a: diskteki dosyada çerez değeri/adı düz metin geçmez",
             lambda: ham and not any(s.encode() in ham for s in ("ARKA-GIRIS", "ARKA-UZUN", "sec_session_id",
                                                                 "remember_me", "dukkan")), lambda: ham[:80])

        def anahtar_disarda_yok():
            k = anahtarlik.k
            if not k:
                return False
            for kok, _d, fs in os.walk(_yalitim.GECICI):
                for f in fs:
                    try:
                        with open(os.path.join(kok, f), "rb") as fh:
                            b = fh.read()
                    except OSError:
                        continue
                    if k in b or k.hex().encode() in b:
                        return False
            return True
        dene("6a': anahtar diske (veri/ayar/durum/günlük) yazılmaz", anahtar_disarda_yok)
        r = kayit("dukkan.test") or {}
        oturumluk = [c for c in r.get("cerezler", ()) if c.get("name") == "sess0"]
        dene("6e1: expiry=0 (süresiz) çerez → 30 gün",
             lambda: oturumluk and abs(oturumluk[0]["expiry"] - (time.time() + 30 * GUN)) < 120, lambda: str(oturumluk))

        # ---- next background browser: the saved session comes back
        k2 = yeni_kopya()
        c2 = cerezler(k2)
        dene("1b: yeni kopyada geri yüklenir; kalıcı çerez kendi ömrüyle (1 gün tavanı yok)",
             lambda: c2[("www.dukkan.test", "sec_session_id")][0] == "ARKA-GIRIS"
             and c2[(".dukkan.test", "remember_me")][0] == "ARKA-UZUN"
             and abs(c2[(".dukkan.test", "remember_me")][1] - _ms(10 * GUN)) < 120_000, lambda: str(c2))
        dene("1b': listede olmayan alanın kopyası profilden gelir (depodan değil)",
             lambda: c2[("liste-disi.test", "sid")][0] == "PROFIL-LISTE-DISI")

        # a bank record written by someone holding the key (tampered / older release) is never applied
        def banka_kaydi():
            d = kayit("dukkan.test")
            d["site"] = "ornekbank.test"
            for c in d.get("cerezler", ()):
                c["host"] = "www.ornekbank.test"
                c["value"] = "SAHTE-BANKA"
            kalici.DEPO._yaz("ornekbank.test", d)
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

        # ---- H3-2 6b: wrong key / corrupt data → nothing applied, no exception, the browser still opens
        yedek = sessiz(Path(dukkan).read_bytes) or b""
        dogru = anahtarlik.k

        def yanlis_anahtar():
            anahtarlik.k = os.urandom(32)
            try:
                k = yeni_kopya()
                c = cerezler(k)
                kopya.temizle(k)
                return c.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI"
            finally:
                anahtarlik.k = dogru

        def bozuk_veri():
            with open(dukkan, "wb") as f:
                f.write(yedek[:-5] + bytes(b ^ 0xFF for b in yedek[-5:]))
            os.chmod(dukkan, 0o600)
            k = yeni_kopya()
            c = cerezler(k)
            kopya.temizle(k)
            return c.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI" and \
                kalici.durum("dukkan.test")["cerezler"] == []
        dene("6b: yanlış anahtar → uygulanmaz, istisna yok", yanlis_anahtar)
        dene("6b': bozuk şifreli veri → uygulanmaz, istisna yok", bozuk_veri)

        # ---- H3-2 6d: AAD binds the record to its domain (a file copied/renamed to another domain does not open)
        def aad():
            with open(kayit_yolu("panel.test"), "wb") as f:
                f.write(yedek)
            os.chmod(kayit_yolu("panel.test"), 0o600)
            k = yeni_kopya()
            c = cerezler(k)
            kopya.temizle(k)
            return kalici.DEPO._oku("panel.test") is None and not any(v[0].startswith("ARKA-") for v in c.values())
        dene("6d: AAD: başka alanın dosyası bu alana kopyalanınca çözülmez", aad)
        sessiz(os.remove, kayit_yolu("panel.test"))

        # ---- H3-2 6c: no key ring (locked wallet / no Secret Service): nothing written, nothing applied, a reason
        with open(dukkan, "wb") as f:
            f.write(yedek)
        os.chmod(dukkan, 0o600)
        anahtarlik.neden = "cüzdan kilitli"
        try:
            k = yeni_kopya()
            c = cerezler(k)
            cerez_yaz(os.path.join(k, "cookies.sqlite"), [("panel.test", "sec_session_id", "KILITLI-GIRIS", _ms(7200))])
            kapat(k)
            neden = sessiz(lambda: kalici.son_neden()) or ""
            from deskhand import doktor
            satir = sessiz(lambda: doktor.satir_kalici_oturum()) or {}
        finally:
            anahtarlik.neden = None
        dene("6c: cüzdan yokken kayıt yazılmaz, uygulanmaz, neden söylenir",
             lambda: c.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI"
             and not os.path.exists(kayit_yolu("panel.test")) and "cüzdan kilitli" in neden
             and os.path.isfile(dukkan), lambda: f"{neden!r} {depo_dosyalari()}")
        dene("6c': doctor satırı nedeni söyler (uyarı)",
             lambda: satir.get("durum") == "uyari" and "cüzdan kilitli" in satir.get("ayrinti", ""), lambda: str(satir))

        # ---- expiry: an expired record is not applied and is deleted
        def gecmis_cerez(d):
            for c in d["cerezler"]:
                c["expiry"] = time.time() - 10
        duzenlendi = kayit_duzenle("dukkan.test", gecmis_cerez)
        k4 = yeni_kopya()
        c4 = cerezler(k4)
        gecti_1 = duzenlendi and c4.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI" \
            and not os.path.exists(dukkan)
        kopya.temizle(k4)
        # a record "saved" in the future (clock change / hand edit): not applied, deleted
        k5 = yeni_kopya()
        cerez_yaz(os.path.join(k5, "cookies.sqlite"), [("www.dukkan.test", "sec_session_id", "GELECEK", _ms(7200))])
        kapat(k5)

        def gelecek_kayit(d):
            d["kayit"] = time.time() + 2 * GUN
        duzenlendi = kayit_duzenle("dukkan.test", gelecek_kayit)
        k6 = yeni_kopya()
        c6 = cerezler(k6)
        dene("1g: süresi geçmiş (ya da gelecekte kaydedilmiş) kayıt uygulanmaz ve silinir",
             lambda: gecti_1 and duzenlendi and c6.get(("www.dukkan.test", "sec_session_id"), ("",))[0] == "PROFIL-ESKI"
             and not os.path.exists(dukkan), lambda: f"{gecti_1} {c6.get(('www.dukkan.test', 'sec_session_id'))}")
        kopya.temizle(k6)

        # ---- H3-2 6e: lifetime without the one-day cap
        k = yeni_kopya()
        cerez_yaz(os.path.join(k, "cookies.sqlite"), [("www.dukkan.test", "sec_session_id", "IKI-SAAT", _ms(7200)),
                                                     (".dukkan.test", "remember_me", "ON-GUN", _ms(10 * GUN))])
        kapat(k)

        def ikinci_gun():
            k = yeni_kopya()
            try:
                con = sqlite3.connect(os.path.join(k, "cookies.sqlite"))  # hazirla already applied it: start empty
                con.execute("DELETE FROM moz_cookies WHERE host LIKE ?", ("%dukkan.test",))
                con.commit()
                con.close()
                with zaman_kaydir(2 * GUN):
                    n = kalici.uygula(Path(k), {"dukkan.test"})
                c = cerezler(k)
                return n == 1 and c[(".dukkan.test", "remember_me")][0] == "ON-GUN" and os.path.isfile(dukkan)
            finally:
                kopya.temizle(k)

        def on_birinci_gun():
            k = yeni_kopya()
            try:
                with zaman_kaydir(11 * GUN):
                    n = kalici.uygula(Path(k), {"dukkan.test"})
                return n == 0 and not os.path.exists(dukkan)
            finally:
                kopya.temizle(k)
        dene("6e2: 10 günlük çerez 2. gün uygulanır", ikinci_gun)
        dene("6e3: süresi geçen kayıt okunurken silinir (11. gün)", on_birinci_gun)

        # ---- sessions check: the store is part of the answer (no copy, the real profile has no session)
        from deskhand.oturum import denetle
        k7 = yeni_kopya()
        cerez_yaz(os.path.join(k7, "cookies.sqlite"), [("panel.test", "sec_session_id", "PANEL-GIRIS", _ms(7200))])
        # a session-only cookie the site set in the background (Firefox keeps it only in the copy's sessionstore)
        mozlz4_yaz(os.path.join(k7, "sessionstore-backups", "recovery.jsonlz4"), {"cookies": [
            {"host": "panel.test", "name": "PHPSESSID", "value": "PANEL-OTURUM", "path": "/",
             "originAttributes": {"userContextId": 0, "privateBrowsingId": 0}}]})
        kapat(k7)
        kod, cikti = cli_kos(["check", "panel.test"])
        dene("2a: sessions check kalıcı depo satırını gösterir, değer yok",
             lambda: "kalıcı depo" in cikti and "PANEL-GIRIS" not in cikti and "PANEL-OTURUM" not in cikti, cikti)
        dene("2a': kaydın yaşı ve son kullanma tarihi görünür",
             lambda: "kaydedildi" in cikti and "son kullanma" in cikti, cikti)
        dene("2b: kopya yok, profilde oturum yok, depoda geçerli giriş → 0", lambda: kod == 0, cikti)
        d = denetle.denetle("panel.test", simdi=time.time() + 3 * 3600)
        dene("2b': kopyanın oturumluk çerezi (sessionstore) de depoya yazılır", lambda: "PANEL-OTURUM" in depo_metni())
        dene("2c: depodaki giriş çerezinin süresi geçmiş → giriş gerekli (1)",
             lambda: d["kod"] == 1 and d["kalici"]["durum"] == "suresi_gecmis", str(d.get("kalici")))
        _k, cikti_json = cli_kos(["check", "panel.test", "--json"])
        dene("2d: JSON çıktısında değer yok", lambda: "PANEL-" not in cikti_json and '"kalici"' in cikti_json)

        # ---- a record others could have written (group/other bits) or with a non-finite time is not read
        def genis_izin():
            yol = kayit_yolu("panel.test")
            os.chmod(yol, 0o644)
            try:
                return kalici.durum("panel.test")["kayit"] is None
            finally:
                os.chmod(yol, 0o600)

        def nan_kayit():
            with open(kayit_yolu("panel.test"), "rb") as f:
                ham = f.read()
            try:
                kayit_duzenle("panel.test", lambda d: d.__setitem__("kayit", float("nan")))
                return kalici.durum("panel.test")["kayit"] is None
            finally:
                with open(kayit_yolu("panel.test"), "wb") as f:
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

        # ---- H3-2 6h: doctor row (value-free: presence, age, expiry)
        from deskhand import doktor
        dene("6h: doctor kalıcı oturum satırı (değersiz, yaş + son kullanma)",
             lambda: doktor.satir_kalici_oturum in doktor.SATIRLAR
             and "panel.test" in doktor.satir_kalici_oturum()["ayrinti"]
             and "SUPUR" not in json.dumps(doktor.satir_kalici_oturum(), ensure_ascii=False),
             lambda: str(doktor.satir_kalici_oturum()))

        # ---- H3-2 6g: a plain record of the first release (b72755f) is deleted on first read, never applied
        os.makedirs(depo_dizini(), mode=0o700, exist_ok=True)
        with open(os.path.join(depo_dizini(), "dukkan.test.json"), "w") as f:
            json.dump({"surum": 1, "site": "dukkan.test", "kayit": time.time(), "cerezler": [
                {"host": "www.dukkan.test", "name": "sec_session_id", "value": "DUZ-ESKI", "path": "/",
                 "originAttributes": "", "expiry": time.time() + 3600}]}, f)
        os.chmod(os.path.join(depo_dizini(), "dukkan.test.json"), 0o600)
        k = yeni_kopya()
        c = cerezler(k)
        kopya.temizle(k)
        dene("6g: eski düz JSON kayıt uygulanmaz ve silinir",
             lambda: c.get(("www.dukkan.test", "sec_session_id"), ("",))[0] != "DUZ-ESKI"
             and not os.path.exists(os.path.join(depo_dizini(), "dukkan.test.json")))

        # ---- H3-2 6f: forget
        kod_f, cikti_f = cli_kos(["forget", "panel.test"])
        dene("6f: `sessions forget <site>` kaydı siler",
             lambda: kod_f == 0 and not os.path.exists(kayit_yolu("panel.test")), cikti_f)
        k = yeni_kopya()
        cerez_yaz(os.path.join(k, "cookies.sqlite"), [("www.dukkan.test", "sec_session_id", "HEPSI", _ms(7200))])
        kapat(k)
        kod_h, cikti_h = cli_kos(["unut", "--all"])
        dene("6f': `sessions forget --all` (Türkçe takma ad) depoyu boşaltır",
             lambda: kod_h == 0 and depo_dosyalari() == [] and os.path.isfile(dukkan) is False, cikti_h)
        kod_g, cikti_g = cli_kos(["forget", "x"])
        dene("6f'': geçersiz alan → 2", lambda: kod_g == 2 and "geçersiz alan" in cikti_g, cikti_g)

        # ---- the settings
        dene("4a: [oturum] kalici normalleşir (adres, büyük harf, tekrar)",
             lambda: ayarlar.dogrula("oturum", "kalici", "Shopier.com, https://www.x.test/a, shopier.com")
             == "shopier.com,www.x.test")

        def ret(anahtar, deger):
            try:
                ayarlar.dogrula("oturum", anahtar, deger)
            except ValueError:
                return True
            return False
        dene("4b: joker ve tek başına genel son ek reddedilir", lambda: ret("kalici", "*.test") and ret("kalici", "com.tr"))
        dene("4c: kalici_sure_gun 1..365, varsayılan 30",
             lambda: ayarlar.VARSAYILAN["oturum"]["kalici_sure_gun"] == 30 and ret("kalici_sure_gun", 366)
             and ret("kalici_sure_gun", 0) and ayarlar.dogrula("oturum", "kalici_sure_gun", 365) == 365)

        def sure_ayari():
            ayar_yaz("panel.test", sure=7)
            panel_tazele()
            k = yeni_kopya()
            mozlz4_yaz(os.path.join(k, "sessionstore-backups", "recovery.jsonlz4"), {"cookies": [
                {"host": "panel.test", "name": "PHPSESSID", "value": "YEDI", "path": "/", "originAttributes": {}}]})
            kapat(k)
            r = kayit("panel.test") or {}
            return any(c["name"] == "PHPSESSID" and abs(c["expiry"] - (time.time() + 7 * GUN)) < 120
                       for c in r.get("cerezler", ()))
        dene("4d: kalici_sure_gun = 7 → süresiz çerez 7 gün", sure_ayari)

        dene("5: durum() değer içermez",
             lambda: kalici.durum("panel.test")["listede"] and "YEDI" not in json.dumps(kalici.durum("panel.test")))

        dene("1h: gerçek profil dosyaları (profiles.ini, cookies.sqlite) sha1 aynı",
             lambda: all(sha1(y) == s for y, s in izler.items()))
    finally:
        sessiz(liste_koruma.panel_durdur)
        if eski_home:
            os.environ["HOME"] = eski_home
        if eski_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = eski_xdg
        shutil.rmtree(tdir, ignore_errors=True)
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
