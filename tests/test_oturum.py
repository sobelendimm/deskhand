"""Oturum köprüsü testleri (EKRANSIZ, kullanıcının gerçek profillerine DOKUNMAZ).

Sahte profiller geçici klasörde üretilir:
  - Firefox benzeri: cookies.sqlite (moz_cookies şeması), recovery.jsonlz4 (mozlz4), key4.db, storage/default/...,
    kilitli DB benzetimi (ikinci sqlite3 bağlantısı EXCLUSIVE kilit tutar)
  - Chromium benzeri dizin
Doğrulananlar: politika + birleştirme, ret listesi süzme, dışlamalar, 0700, KAYNAĞA YAZILMADIĞI (mtime/sha1),
tespit fonksiyonları (sahte /proc, symlink kilitleri, soyut soket yok), flatpak argv üretimi (başlatmadan),
değişim tespiti, cli.main.

GERÇEK profille uçtan uca deneme AYRI dosyada (tests/ekranli/, elle): bu dosya hiçbir uygulama başlatmaz.

Çalıştır:  python3 tests/test_oturum.py
"""
import hashlib
import json
import os
import sqlite3
import time
import struct
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici; Deskhand'den ÖNCE)

from deskhand import oturum
from deskhand.oturum import chromium, firefox, kopya, politika, tespit

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


# ------------------------------------------------------------------ sahte profil üreticileri

_COOKIES_SEMA = (
    "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
    "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, "
    "creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, "
    "sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER DEFAULT 0, "
    "updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))")


def sahte_cookies(yol, cerezler):
    con = sqlite3.connect(yol)
    con.execute(_COOKIES_SEMA)
    for c in cerezler:
        host, name, value = c[:3]
        expiry = c[3] if len(c) > 3 else 0
        con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('',?,?,?,'/',?)",
                    (name, value, host, expiry))
    con.commit()
    con.close()


def mozlz4_yaz(yol, obj):
    import lz4.block
    ham = json.dumps(obj).encode()
    sikis = lz4.block.compress(ham, store_size=False)
    with open(yol, "wb") as f:
        f.write(b"mozLz40\0")
        f.write(struct.pack("<I", len(ham)))
        f.write(sikis)


def sahte_firefox_profil(kok, kurulum="Install1", prof="ab12.default-release"):
    """profiles.ini + profil dizini (realpath için symlink DEĞİL; doğrudan). Döner: profil dizini."""
    os.makedirs(kok, exist_ok=True)
    pdir = os.path.join(kok, prof)
    os.makedirs(os.path.join(pdir, "sessionstore-backups"), exist_ok=True)
    os.makedirs(os.path.join(pdir, "storage", "default"), exist_ok=True)
    with open(os.path.join(kok, "profiles.ini"), "w") as f:
        f.write(f"[Profile0]\nName=dr\nIsRelative=1\nPath={prof}\nDefault=0\n\n"
                f"[Profile1]\nName=d\nIsRelative=1\nPath=other\nDefault=1\n\n"
                f"[{kurulum}]\nDefault={prof}\nLocked=1\n")
    # çerezler: izinli (github.com), ret (mybank.com), nötr (example.com)
    sahte_cookies(os.path.join(pdir, "cookies.sqlite"),
                  [("github.com", "user_session", "GIZLI1"),
                   (".github.com", "logged_in", "yes"),
                   ("mybank.com", "sess", "GIZLI2"),
                   ("example.com", "a", "1"),
                   (".google.com", "SID", "GIZLI3"),          # üst alan çerezi: accounts.google.com'a da gider
                   ("www.google.com", "NID", "n"),            # yalnız www'ye giden konak çerezi: kalır
                   (".yapikredi.com.tr", "s", "GIZLI4")])
    c = sqlite3.connect(os.path.join(pdir, "cookies.sqlite")); c.execute("PRAGMA journal_mode=WAL"); c.close()
    # permissions: kamera/mikrofon/konum/bildirim (silinmeli) + çerez izni (kalmalı)
    c = sqlite3.connect(os.path.join(pdir, "permissions.sqlite"))
    c.execute("CREATE TABLE moz_perms ( id INTEGER PRIMARY KEY,origin TEXT,type TEXT,permission INTEGER,"
              "expireType INTEGER,expireTime INTEGER,modificationTime INTEGER)")
    for origin, tur in (("https://meet.google.com", "camera"), ("https://meet.google.com", "microphone"),
                        ("https://maps.example", "geo"), ("https://haber.example", "desktop-notification"),
                        ("https://ekran.example", "screen"), ("https://github.com", "cookie")):
        c.execute("INSERT INTO moz_perms (origin,type,permission,expireType,expireTime,modificationTime) "
                  "VALUES (?,?,1,0,0,0)", (origin, tur))
    c.commit(); c.close()
    c = sqlite3.connect(os.path.join(pdir, "storage.sqlite")); c.execute("CREATE TABLE t(x)"); c.commit(); c.close()
    # kayıtlı parolalar: logins.json (+ yedek) ve Rust aynası logins.db (aynı kayıtlar)
    girisler = [("https://www.isbank.com.tr", "https://www.isbank.com.tr", "{g-isbank}"),
                ("https://github.com", "https://github.com", "{g-github}"),
                ("https://accounts.google.com", "", "{g-google}"),
                ("https://forum.example", "https://odeme.example/form", "{g-form}")]
    lj = {"nextId": 5, "version": 3, "potentiallyVulnerablePasswords": [],
          "dismissedBreachAlertsByLoginGUID": {"{g-isbank}": {"timeBreachAlertDismissed": 1}},
          "logins": [{"id": i + 1, "hostname": h, "formSubmitURL": f, "httpRealm": None, "guid": g,
                      "encryptedUsername": "SIFRELI-K", "encryptedPassword": "SIFRELI-P", "encType": 1}
                     for i, (h, f, g) in enumerate(girisler)]}
    for ad in ("logins.json", "logins-backup.json"):
        with open(os.path.join(pdir, ad), "w") as f:
            json.dump(lj, f)
    c = sqlite3.connect(os.path.join(pdir, "logins.db"))
    for t in ("loginsL", "loginsM"):
        c.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT NOT NULL, httpRealm TEXT, "
                  "formActionOrigin TEXT, timeCreated INTEGER NOT NULL DEFAULT 0, "
                  "timePasswordChanged INTEGER NOT NULL DEFAULT 0, secFields TEXT, guid TEXT NOT NULL UNIQUE)")
        for h, fo, g in girisler:
            c.execute(f"INSERT INTO {t} (origin, formActionOrigin, secFields, guid) VALUES (?,?,?,?)",
                      (h, fo, "SIFRELI", g))
    c.commit(); c.close()
    # oturum çerezi (recovery.jsonlz4): github.com (izinli) + tracker.gov.tr (ret)
    mozlz4_yaz(os.path.join(pdir, "sessionstore-backups", "recovery.jsonlz4"),
               {"cookies": [{"host": "github.com", "name": "_session", "value": "OTURUMX", "path": "/"},
                            {"host": "secure.gov.tr", "name": "t", "value": "X", "path": "/"}]})
    # oturum/depo: github.com (izinli), mybank.com (ret), example.com
    for origin, boyut in (("https+++github.com", 10), ("https+++mybank.com", 10), ("https+++example.com", 10)):
        d = os.path.join(pdir, "storage", "default", origin, "ls")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "data.sqlite"), "wb") as f:
            f.write(b"\0" * boyut)
    # oturum için dosyalar + hariç tutulacaklar
    for ad in ("key4.db", "cert9.db", "containers.json", "pkcs11.txt", "prefs.js", "signedInUser.json"):
        with open(os.path.join(pdir, ad), "w") as f:
            f.write("{}" if ad.endswith(".json") else "x")
    os.makedirs(os.path.join(pdir, "weave"), exist_ok=True)
    with open(os.path.join(pdir, "weave", "w.json"), "w") as f:
        f.write("x")
    with open(os.path.join(pdir, "places.sqlite"), "w") as f:
        f.write("x" * 100)
    with open(os.path.join(pdir, ".parentlock"), "w") as f:
        f.write("")
    return pdir


def sahte_chromium(kok):
    os.makedirs(os.path.join(kok, "Default", "Cache"), exist_ok=True)
    with open(os.path.join(kok, "Local State"), "w") as f:
        f.write("{}")
    with open(os.path.join(kok, "Default", "Cookies"), "w") as f:
        f.write("x")
    with open(os.path.join(kok, "Default", "Cache", "data_0"), "w") as f:
        f.write("x" * 1000)
    os.symlink("host-4242", os.path.join(kok, "SingletonLock"))
    return kok


def dosya_listesi(kok):
    """(göreli yol, boyut, mtime_ns) listesi — kaynakta yeni dosya/değişiklik olmadığını doğrulamak için."""
    sonuc = []
    for d, _, dosyalar in os.walk(kok):
        for f in dosyalar:
            st = os.lstat(os.path.join(d, f))
            sonuc.append((os.path.relpath(os.path.join(d, f), kok), st.st_size, st.st_mtime_ns))
    return sorted(sonuc)


def agac_sha1(kok):
    h = hashlib.sha1()
    for d, _, dosyalar in os.walk(kok):
        for f in sorted(dosyalar):
            yol = os.path.join(d, f)
            h.update(os.path.relpath(yol, kok).encode())
            try:
                with open(yol, "rb") as fp:
                    h.update(fp.read())
            except OSError:
                pass
    return h.hexdigest()


# ------------------------------------------------------------------ testler

def test_politika():
    yap = politika.yukle()
    kontrol("firefox politika kopya", politika.coz("firefox", yap).kapali_iken == "kopya")
    kontrol("chromium keyring+on", politika.coz("chromium", yap).acik_iken == "on"
            and politika.coz("chromium", yap).keyring)
    kontrol("telegram bekle", politika.coz("telegram", yap).acik_iken == "bekle")
    kontrol("bilinmeyen _varsayilan: kapalıyken paylas, açıkken bekle",
            politika.coz("asdfqwer", yap).kapali_iken == "paylas" and politika.coz("asdfqwer", yap).acik_iken == "bekle")
    # ad normu
    kontrol("ters alan adı normu", politika.coz("com.spotify.Client", yap).uygulama == "spotify")
    kontrol("code→vscode", politika.coz("code", yap).uygulama == "vscode")
    # site listeleri
    pol = politika.coz("firefox", yap)
    kontrol("ret: mybank", pol.site_reddedildi("mybank.com"))
    kontrol("ret: gov.tr alt", pol.site_reddedildi("secure.gov.tr"))
    kontrol("ret: accounts.google", pol.site_reddedildi("accounts.google.com"))
    kontrol("izinli: github (liste boş)", pol.site_izinli("github.com"))
    kontrol("izinli değil: ret ezer", not pol.site_izinli("mybank.com"))
    kontrol("görev izni: yalnız verilen", pol.site_izinli("x.com", ["x.com"])
            and not pol.site_izinli("y.com", ["x.com"]))


def test_politika_birlestir():
    # kullanıcı geçersiz kılması
    cdir = os.environ["DESKHAND_CONFIG_DIR"]
    os.makedirs(cdir, exist_ok=True)
    with open(os.path.join(cdir, "oturum.toml"), "w") as f:
        f.write('[uygulama.firefox]\nacik_iken = "bekle"\n')
    yap = politika.yukle()
    pol = politika.coz("firefox", yap)
    kontrol("kullanıcı üstüne yazar", pol.acik_iken == "bekle")
    kontrol("verilmeyen varsayılanda kalır", pol.kapali_iken == "kopya")
    os.remove(os.path.join(cdir, "oturum.toml"))


def test_firefox_kopya():
    tdir = tempfile.mkdtemp(prefix="deskhand-ff-src-")
    kok = os.path.join(tdir, ".config", "mozilla", "firefox")
    pdir = sahte_firefox_profil(kok)
    once_sha = agac_sha1(pdir)
    once_liste = dosya_listesi(pdir)
    # profil çözümü: HOME'u geçici yere al
    eski_home = os.environ.get("HOME"); eski_xdg = os.environ.get("XDG_CONFIG_HOME")
    os.environ["HOME"] = tdir
    os.environ.pop("XDG_CONFIG_HOME", None)
    try:
        coz = tespit.firefox_profil_dizini()
        kontrol("profil çözümü [Install*] esas", coz == os.path.realpath(pdir), f"{coz}")
        pol = politika.coz("firefox")
        b0 = firefox.hazirla(pol, gorev_siteleri=None)
        kontrol("görev sitesi yokken site deposu kopyalanmaz (yalnız çerez + girişler)",
                b0.get("origin_sayisi") == 0 and not os.path.isdir(os.path.join(b0["kopya_yolu"], "storage", "default")),
                str(b0.get("origin_sayisi")))
        b = firefox.hazirla(pol, gorev_siteleri=["github.com", "example.com", "mybank.com"])
        hedef = b["kopya_yolu"]
        kontrol("firefox kopya durum yok", b["durum"] is None, str(b.get("durum")))
        # ret listesi: mybank çerezi silindi, github/example kaldı
        con = sqlite3.connect(os.path.join(hedef, "cookies.sqlite"))
        hostlar = {r[0] for r in con.execute("SELECT DISTINCT host FROM moz_cookies")}
        con.close()
        kontrol("ret çerezi silindi (mybank)", "mybank.com" not in hostlar, str(hostlar))
        kontrol("izinli çerez kaldı (github)", "github.com" in hostlar)
        kontrol("ret silindi sayısı≥1", b["ret_silindi"] >= 1)
        # oturum çerezi eklendi (github _session), gov.tr eklenmedi
        con = sqlite3.connect(os.path.join(hedef, "cookies.sqlite"))
        adlar = {r[0] for r in con.execute("SELECT name FROM moz_cookies WHERE host='github.com'")}
        gov = con.execute("SELECT COUNT(*) FROM moz_cookies WHERE host LIKE '%gov.tr'").fetchone()[0]
        con.close()
        kontrol("oturum çerezi eklendi", "_session" in adlar, str(adlar))
        kontrol("ret oturum çerezi eklenmedi (gov.tr)", gov == 0)
        kontrol("oturum_cerez_eklendi=1", b["oturum_cerez_eklendi"] == 1)
        # dışlamalar
        kontrol("signedInUser kopyalanmadı", not os.path.exists(os.path.join(hedef, "signedInUser.json")))
        kontrol("weave kopyalanmadı", not os.path.exists(os.path.join(hedef, "weave")))
        kontrol("places kopyalanmadı", not os.path.exists(os.path.join(hedef, "places.sqlite")))
        kontrol(".parentlock kopyalanmadı", not os.path.exists(os.path.join(hedef, ".parentlock")))
        # dahil edilenler
        kontrol("key4.db kopyalandı", os.path.exists(os.path.join(hedef, "key4.db")))
        kontrol("logins.db kopyalandı", os.path.exists(os.path.join(hedef, "logins.db")))
        kontrol("user.js yazıldı", os.path.exists(os.path.join(hedef, "user.js")))
        with open(os.path.join(hedef, "user.js")) as f:
            uj = f.read()
        kontrol("user.js FxA kapalı", "identity.fxaccounts.enabled\", false" in uj)
        # O7: kamera/mikrofon/bildirim/konum varsayılanı engelle + izin istemi açık
        for pref in ('"media.navigator.permission.disabled", false', '"permissions.default.camera", 2',
                     '"permissions.default.microphone", 2', '"permissions.default.desktop-notification", 2',
                     '"permissions.default.geo", 2'):
            kontrol(f"user.js {pref}", pref in uj)
        con = sqlite3.connect(os.path.join(hedef, "permissions.sqlite"))
        turler = {r[0] for r in con.execute("SELECT type FROM moz_perms")}
        con.close()
        kontrol("O7: kamera/mikrofon/ekran/konum/bildirim izinleri silindi",
                not turler & {"camera", "microphone", "geo", "desktop-notification", "screen"}, str(turler))
        kontrol("O7: diğer izinler kaldı (cookie)", "cookie" in turler, str(turler))
        kontrol("O7: izin_silindi=5", b["izin_silindi"] == 5, str(b["izin_silindi"]))
        # O6a: ret alanlarının kayıtlı parolaları (logins.json + yedek + logins.db aynası) silindi
        for ad in ("logins.json", "logins-backup.json"):
            with open(os.path.join(hedef, ad)) as f:
                lj = json.load(f)
            hostlar_l = [g["hostname"] for g in lj["logins"]]
            kontrol(f"O6: {ad} ret girişleri silindi (isbank, accounts.google, ödeme formu)",
                    hostlar_l == ["https://github.com"], str(hostlar_l))
            kontrol(f"O6: {ad} şifreli değer dokunulmadan kaldı",
                    lj["logins"][0]["encryptedPassword"] == "SIFRELI-P")
            kontrol(f"O6: {ad} breach kaydı da silindi", "{g-isbank}" not in lj.get("dismissedBreachAlertsByLoginGUID", {}))
        con = sqlite3.connect(os.path.join(hedef, "logins.db"))
        for t in ("loginsL", "loginsM"):
            guidler = sorted(r[0] for r in con.execute(f"SELECT guid FROM {t}"))
            kontrol(f"O6: logins.db {t} aynası tutarlı (yalnız github)", guidler == ["{g-github}"], str(guidler))
        con.close()
        kontrol("O6: giris_silindi=3", b["giris_silindi"] == 3, str(b["giris_silindi"]))
        # O6b/c: üst alan çerezi ve TR banka
        con = sqlite3.connect(os.path.join(hedef, "cookies.sqlite"))
        hostlar2 = {r[0] for r in con.execute("SELECT DISTINCT host FROM moz_cookies")}
        con.close()
        kontrol("O6: .google.com alan çerezi silindi (accounts.google.com'a gider)", ".google.com" not in hostlar2,
                str(hostlar2))
        kontrol("O6: www.google.com konak çerezi kaldı", "www.google.com" in hostlar2, str(hostlar2))
        kontrol("O6: .yapikredi.com.tr silindi", ".yapikredi.com.tr" not in hostlar2, str(hostlar2))
        # storage: yalnız izinli origin (github), ret (mybank) ve izinsiz değil
        sd = os.path.join(hedef, "storage", "default")
        originler = set(os.listdir(sd)) if os.path.isdir(sd) else set()
        kontrol("storage github var", "https+++github.com" in originler, str(originler))
        kontrol("storage mybank yok (ret)", "https+++mybank.com" not in originler)
        # 0700
        kontrol("kopya dizini 0700", (os.stat(hedef).st_mode & 0o777) == 0o700)
        # argv
        kontrol("argv --no-remote", "--no-remote" in b["argv"] and "--new-instance" in b["argv"])
        # KAYNAK YAZILMADI
        kontrol("kaynak profil değişmedi (sha1)", agac_sha1(pdir) == once_sha)
        kontrol("D13: kaynakta yeni dosya yok, mtime'lar aynı (-wal/-shm oluşmadı)",
                dosya_listesi(pdir) == once_liste, str(set(dosya_listesi(pdir)) ^ set(once_liste)))
        oturum.temizle(hedef)
        kontrol("temizle sildi", not os.path.exists(hedef))
    finally:
        if eski_home:
            os.environ["HOME"] = eski_home
        if eski_xdg is not None:
            os.environ["XDG_CONFIG_HOME"] = eski_xdg
        import shutil
        shutil.rmtree(tdir, ignore_errors=True)


def test_sqlite_kilitli():
    """Kilitli DB benzetimi: EXCLUSIVE kilit tutan ikinci bağlantıyla da tutarlı yedek alınır."""
    tdir = tempfile.mkdtemp(prefix="deskhand-lock-")
    db = os.path.join(tdir, "cookies.sqlite")
    sahte_cookies(db, [("a.com", "n", "v")])
    # WAL kipinde aç, yazılmamış işlem bırakarak kilit tut
    tutucu = sqlite3.connect(db)
    tutucu.execute("PRAGMA journal_mode=WAL")
    tutucu.execute("BEGIN EXCLUSIVE")
    tutucu.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('','m','k','b.com','/',0)")
    hedef = os.path.join(tdir, "kopya.sqlite")
    try:
        yontem = kopya.sqlite_yedek(db, hedef)
        con = sqlite3.connect(hedef)
        n = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
        con.close()
        kontrol("kilitli DB yedeklendi", n >= 1, f"yöntem={yontem} n={n}")
    except Exception as e:
        kontrol("kilitli DB yedeklendi", False, str(e))
    finally:
        tutucu.rollback(); tutucu.close()
        import shutil
        shutil.rmtree(tdir, ignore_errors=True)


def test_chromium_dizin_kopya():
    tdir = tempfile.mkdtemp(prefix="deskhand-cr-")
    kok = sahte_chromium(os.path.join(tdir, "chromium"))
    once = agac_sha1(kok)
    hedef = os.path.join(tdir, "kopya")
    r = chromium.veri_dizini_kopyala(kok, hedef)
    kontrol("Local State kopyalandı", os.path.exists(os.path.join(hedef, "Local State")))
    kontrol("Cookies kopyalandı", os.path.exists(os.path.join(hedef, "Default", "Cookies")))
    kontrol("Cache HARİÇ", not os.path.exists(os.path.join(hedef, "Default", "Cache")))
    kontrol("SingletonLock kopyalanmadı", not os.path.exists(os.path.join(hedef, "SingletonLock")))
    kontrol("chromium kaynak değişmedi", agac_sha1(kok) == once)
    argv = chromium.chromium_argv("vivaldi", hedef)
    kontrol("chromium argv user-data-dir", f"--user-data-dir={hedef}" in argv)
    kontrol("chromium argv password-store", "--password-store=kwallet6" in argv)
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)


def test_flatpak_argv():
    pol = politika.coz("discord")
    argv = chromium.flatpak_argv(pol.flatpak, "com.discordapp.Discord", "/tmp/deskhand-x")
    kontrol("flatpak argv run", argv[:3] == ["flatpak", "run", "--die-with-parent"])
    kontrol("flatpak argv command=sh", "--command=sh" in argv)
    kontrol("flatpak argv filesystem kopya", "--filesystem=/tmp/deskhand-x" in argv)
    betik = argv[argv.index("-c") + 1]
    kontrol("flatpak argv exec içeride XDG", "XDG_CONFIG_HOME=\"$K/config\"" in betik)
    kontrol("flatpak argv exec komut", "exec com.discordapp.Discord" in betik)


def test_flatpak_electron_kopya():
    """Gerçek ~/.var/app yerine sahte userData ile kopya + argv (BAŞLATMADAN)."""
    tdir = tempfile.mkdtemp(prefix="deskhand-fe-")
    fk = "com.discordapp.Discord"
    src = os.path.join(tdir, ".var", "app", fk, "config", "discord")
    os.makedirs(os.path.join(src, "Local Storage"), exist_ok=True)
    os.makedirs(os.path.join(src, "Cache"), exist_ok=True)
    with open(os.path.join(src, "Local Storage", "leveldb"), "w") as f:
        f.write("sess")
    with open(os.path.join(src, "Cache", "big"), "w") as f:
        f.write("x" * 5000)
    once = agac_sha1(src)
    eski_home = os.environ.get("HOME")
    os.environ["HOME"] = tdir
    try:
        pol = politika.coz("discord")
        b = chromium.flatpak_electron_hazirla(pol, "discord")
        hedef = b["kopya_yolu"]
        kontrol("fe kopya Local Storage var",
                os.path.exists(os.path.join(hedef, "config", "discord", "Local Storage", "leveldb")))
        kontrol("fe kopya Cache HARİÇ",
                not os.path.exists(os.path.join(hedef, "config", "discord", "Cache")))
        kontrol("fe argv üretildi", b["argv"] and b["argv"][0] == "flatpak")
        kontrol("fe kaynak değişmedi", agac_sha1(src) == once)
        oturum.temizle(hedef)
    finally:
        if eski_home:
            os.environ["HOME"] = eski_home
        import shutil
        shutil.rmtree(tdir, ignore_errors=True)


def test_tespit_sahte_proc():
    tdir = tempfile.mkdtemp(prefix="deskhand-proc-")
    # sahte /proc: pid 111 firefox, pid 222 alakasız
    for pid, comm, cmd in ((111, "firefox", "/usr/lib/firefox/firefox"), (222, "bash", "bash")):
        d = os.path.join(tdir, str(pid)); os.makedirs(d)
        with open(os.path.join(d, "comm"), "w") as f:
            f.write(comm)
        with open(os.path.join(d, "cmdline"), "w") as f:
            f.write(cmd)
    bulunan = tespit._surec_ara([r"\bfirefox\b"], proc_koku=tdir)
    kontrol("sahte proc firefox bulundu", 111 in bulunan and 222 not in bulunan, str(bulunan))
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)


def test_tespit_lock_ve_singleton():
    tdir = tempfile.mkdtemp(prefix="deskhand-lk-")
    prof = os.path.join(tdir, "prof"); os.makedirs(prof)
    # lock symlink ölü PID (999999) → 0
    os.symlink("127.0.1.1:+999999", os.path.join(prof, "lock"))
    kontrol("lock ölü pid → 0", tespit._lock_symlink_pid(prof) == 0)
    # lock canlı PID (kendi pid) → pid
    os.remove(os.path.join(prof, "lock"))
    os.symlink(f"127.0.1.1:+{os.getpid()}", os.path.join(prof, "lock"))
    kontrol("lock canlı pid bulundu", tespit._lock_symlink_pid(prof) == os.getpid())
    # SingletonLock ölü
    cr = os.path.join(tdir, "cr"); os.makedirs(cr)
    os.symlink("host-888888", os.path.join(cr, "SingletonLock"))
    kontrol("SingletonLock ölü → 0", tespit._singleton_lock_pid(cr) == 0)
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)


def test_tespit_soyut_soket():
    # bu makinede Telegram soketi olmamalı → False (en azından çökmeden döner)
    r = tespit._soyut_soket_var(r"-TelegramDesktop$")
    kontrol("soyut soket sorgusu döndü", r in (True, False))


def test_hazirla_kararlar():
    # chromium → on (keyring, röle yok)
    h = oturum.hazirla("chromium")
    kontrol("chromium hazirla on", h.karar == "on" and not h.argv, h.karar)
    kontrol("chromium açıklama var", "arka planda açıl" in h.aciklama)
    # telegram → bekle
    kontrol("telegram hazirla bekle", oturum.hazirla("telegram").karar == "bekle")
    # bilinmeyen + ikilisi bulunamıyor → "açık mı" bilinemez → bekle (Y2)
    h = oturum.hazirla("qwertyxyz")
    kontrol("bilinmeyen (bulunamadı) hazirla bekle", h.karar == "bekle" and h.ayrinti.get("belirsiz"), h.karar)
    # obsidian → on (özel açıklama)
    h = oturum.hazirla("obsidian")
    kontrol("obsidian hazirla on", h.karar == "on")
    kontrol("obsidian açıklama kasa", "kasa" in h.aciklama)


def test_politika_esleme():
    """Y1: politika çözülmüş addan/kimlikten; takma adlar ve ekler; en kısıtlayıcı."""
    yap = politika.yukle()
    beklenen = {"telegram-desktop": "bekle", "org.telegram.desktop": "bekle", "org.kde.kmail2": "kapali",
                "kmail2": "kapali", "vivaldi-stable": "on", "chromium-browser": "on", "google-chrome-beta": "on",
                "brave-browser-nightly": "on", "signal-desktop-beta": "bekle", "whatsapp-for-linux": "bekle",
                "steam-native": "bekle", "keepassxc": "kapali", "/usr/bin/telegram-desktop": "bekle",
                "com.valvesoftware.Steam": "bekle", "org.kde.kontact": "kapali"}
    for ad, karar in beklenen.items():
        pol = politika.coz(ad, yap)
        kontrol(f"Y1 politika {ad} → {karar}", pol.bilinen and pol.kapali_iken == karar,
                f"{pol.uygulama} {pol.kapali_iken}")
    kontrol("en_kisitlayici sırası", politika.en_kisitlayici(["paylas", "kopya", "bekle"]) == "bekle"
            and politika.en_kisitlayici(["on", "kapali"]) == "kapali"
            and politika.en_kisitlayici(["kopya", "paylas"]) == "kopya")
    kontrol("bilinmeyen ad bilinen değil", not politika.coz("qwerty-xyz", yap).bilinen)
    pol = politika.coz("firefox", yap)
    for alan in ("www.isbank.com.tr", "garantibbva.com.tr", "yapikredi.com.tr", "akbank.com", "qnb.com.tr",
                 "enpara.com", "papara.com", "ininal.com", "param.com.tr", "iyzico.com", "paytr.com",
                 "giris.turkiye.gov.tr", "ivd.gib.gov.tr", "www.paypal.com", "dashboard.stripe.com", "wise.com",
                 "app.revolut.com", "shop.example/checkout".split("/")[0].replace("shop", "checkout")):
        kontrol(f"O6 ret: {alan}", pol.site_reddedildi(alan))
    kontrol("O6 üst alan çerezi .google.com reddedildi", pol.cerez_reddedildi(".google.com"))
    kontrol("O6 .bank.com.tr reddedildi", pol.cerez_reddedildi(".bank.com.tr"))
    kontrol("O6 konak çerezi google.com (noktasız) kalır", not pol.cerez_reddedildi("google.com"))
    kontrol("O6 .github.com kalır", not pol.cerez_reddedildi(".github.com"))


def _desktop_yaz(dizin, kimlik, ad, exec_):
    with open(os.path.join(dizin, kimlik + ".desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={ad}\nExec={exec_}\n")


def _sahte_ortam():
    """Geçici: .desktop dizini + PATH'te sahte ikililer (ELF: /usr/bin/true kopyası; kabuk başlatıcı; python
    betiği) + sahte flatpak/systemctl. → (tdir, eski_path, eski_dizinler)."""
    import shutil
    from deskhand import uygulama
    tdir = tempfile.mkdtemp(prefix="deskhand-coz-")
    app = os.path.join(tdir, "applications"); os.makedirs(app)
    bin_ = os.path.join(tdir, "bin"); os.makedirs(bin_)
    for ad in ("telegram-desktop", "dhtestelf"):
        shutil.copy(shutil.which("true"), os.path.join(bin_, ad))
    shutil.copy(shutil.which("sleep"), os.path.join(bin_, "dhtestuyku"))
    with open(os.path.join(bin_, "dhtestbaslatici"), "w") as f:
        f.write("#!/bin/sh\nexec /opt/dhtest/gercek \"$@\"\n")
    with open(os.path.join(bin_, "dhtestpy"), "w") as f:
        f.write("#!/usr/bin/env python3\nprint(1)\n")
    for ad in ("dhtestbaslatici", "dhtestpy"):
        os.chmod(os.path.join(bin_, ad), 0o755)
    _sahte_flatpak(bin_, tdir)
    _desktop_yaz(app, "org.telegram.desktop", "Telegram", "telegram-desktop -- %u")
    _desktop_yaz(app, "org.kde.kmail2", "KMail", "kmail -qwindowtitle %c %u")
    _desktop_yaz(app, "com.example.DhTest", "DhTest Flatpak",
                 "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=dhtestic --file-forwarding "
                 "com.example.DhTest @@u %U @@")
    _desktop_yaz(app, "dhtest-elf", "DhTestElf", "dhtestelf %F")
    _desktop_yaz(app, "dhtest-uyku", "DhTestUyku", "dhtestuyku 1")
    _desktop_yaz(app, "dhtest-baslatici", "DhTestBaslatici", "dhtestbaslatici")
    eski_path = os.environ.get("PATH", "")
    os.environ["PATH"] = bin_ + os.pathsep + eski_path
    os.environ["FAKE_FLATPAK_DIR"] = tdir
    eski_dizinler = uygulama.UYGULAMA_DIZINLERI
    uygulama.UYGULAMA_DIZINLERI = (app,)
    return tdir, eski_path, eski_dizinler


def _sahte_ortam_kapat(tdir, eski_path, eski_dizinler):
    import shutil
    from deskhand import uygulama
    os.environ["PATH"] = eski_path
    os.environ.pop("FAKE_FLATPAK_DIR", None)
    uygulama.UYGULAMA_DIZINLERI = eski_dizinler
    shutil.rmtree(tdir, ignore_errors=True)


_SAHTE_FLATPAK = r"""#!/bin/sh
# SAHTE flatpak (test): durum $FAKE_FLATPAK_DIR/ps (örnek<TAB>pid<TAB>kimlik), günlük $FAKE_FLATPAK_DIR/log
D="$FAKE_FLATPAK_DIR"
touch "$D/ps"
case "$1" in
  ps) [ -e "$D/ps_hata" ] && exit 1; cat "$D/ps"; exit 0 ;;
  kill)
    if [ -n "$FAKE_KOPYA" ] && [ -d "$FAKE_KOPYA" ]; then k=var; else k=yok; fi
    echo "kill $2 kopya=$k" >> "$D/log"
    [ -e "$D/kill_etkisiz" ] && exit 0
    pid=$(awk -F'\t' -v i="$2" '$1==i {print $2}' "$D/ps")
    awk -F'\t' -v i="$2" '$1!=i' "$D/ps" > "$D/ps.t"; mv "$D/ps.t" "$D/ps"
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
    exit 0 ;;
  run)
    shift; app=""
    for a in "$@"; do case "$a" in -*) ;; *) app="$a"; break ;; esac; done
    echo "run $app" >> "$D/log"
    printf '%s\t%s\t%s\n' "$((100000 + $$))" "$$" "$app" >> "$D/ps"
    exec sleep 30 ;;
esac
exit 0
"""


def _sahte_flatpak(bin_, tdir):
    for ad, icerik in (("flatpak", _SAHTE_FLATPAK),
                       ("systemctl", '#!/bin/sh\necho "$@" >> "$FAKE_FLATPAK_DIR/systemctl.log"\nexit 0\n')):
        with open(os.path.join(bin_, ad), "w") as f:
            f.write(icerik)
        os.chmod(os.path.join(bin_, ad), 0o755)


def test_cozum_ve_hazirla():
    """Y1/Y2: hazirla(ad) uygulamayı kendisi çözer (kısmi ad, .desktop kimliği, Exec ikilisi, mutlak yol, Flatpak);
    bilinmeyen uygulama yalnız kesin kapalıysa paylas. Sahte .desktop + PATH; gerçek uygulama başlatılmaz."""
    import subprocess
    import time
    from deskhand import uygulama
    from deskhand.hata import Dur
    from deskhand.oturum import cozum
    tdir, eski_path, eski_dizinler = _sahte_ortam()
    try:
        bin_ = os.path.join(tdir, "bin")
        kontrol("uygulama_adaylari = uygulama_bul eşlemesi (kısmi)",
                [g["kimlik"] for g in uygulama.uygulama_adaylari("telegra")] == ["org.telegram.desktop"]
                and uygulama.uygulama_bul("telegra")["kimlik"] == "org.telegram.desktop")
        c = cozum.coz("telegra")
        kontrol("çözüm: kısmi ad → .desktop kimliği + Exec ikilisi",
                "org.telegram.desktop" in c.adlar and "telegram-desktop" in c.ikililer, str(c.ozet()))
        for ad, karar in (("telegra", "bekle"), ("Telegram", "bekle"), ("org.telegram.desktop", "bekle"),
                          (os.path.join(bin_, "telegram-desktop"), "bekle"), ("kmail", "kapali"),
                          ("KMail", "kapali")):
            h = oturum.hazirla(ad)
            kontrol(f"Y1 hazirla({os.path.basename(ad)}) → {karar}", h.karar == karar,
                    f"{h.karar} {h.ayrinti.get('politikalar')}")
        try:
            uygulama.oturum_hazirla("telegra")
            kontrol("uygulama.oturum_hazirla(telegra) → Dur 16", False)
        except Dur as e:
            kontrol("uygulama.oturum_hazirla(telegra) → Dur 16", e.kod == 16, str(e.kod))
        # Y2: bilinmeyen ELF, çalışmıyor → paylas; çalışıyorsa → bekle
        h = oturum.hazirla("DhTestElf")
        kontrol("Y2 bilinmeyen ELF kapalı → paylas", h.karar == "paylas" and not h.ayrinti.get("belirsiz"),
                f"{h.karar} {h.ayrinti}")
        p = subprocess.Popen([os.path.join(bin_, "dhtestuyku"), "20"])
        try:
            time.sleep(0.2)
            h = oturum.hazirla("DhTestUyku")
            kontrol("Y2 bilinmeyen uygulama /proc'ta çalışıyor → bekle",
                    h.karar == "bekle" and p.pid in h.ayrinti.get("ikili_pid", []), f"{h.karar} {h.ayrinti}")
        finally:
            p.kill(); p.wait()
        h = oturum.hazirla("DhTestUyku")
        kontrol("Y2 aynı uygulama kapanınca → paylas", h.karar == "paylas", h.karar)
        h = oturum.hazirla("DhTestBaslatici")
        kontrol("Y2 kabuk başlatıcı betik (gerçek süreç adı bilinemez) → bekle",
                h.karar == "bekle" and h.ayrinti.get("belirsiz"), f"{h.karar} {h.ayrinti}")
        kontrol("Y2 bilinemiyor açıklaması", "bilinemiyor" in h.aciklama, h.aciklama)
        h = oturum.hazirla("dhtestpy")
        kontrol("Y2 python betiği (betik adıyla aranır) kapalı → paylas",
                h.karar == "paylas" and "dhtestpy" in h.ayrinti["cozum"]["ikililer"], f"{h.karar} {h.ayrinti}")
        kontrol("Y2 bulunamayan → bekle", oturum.hazirla("dhtest-yok-boyle-bir-sey").karar == "bekle")
        # ham komut (ac --komut / mutlak yol): bilinen değilse paylas, bilinen ise politika
        kontrol("ham komut bilinmeyen → paylas (test penceresi)",
                oturum.hazirla(sys.executable, ham_komut=True).karar == "paylas")
        kontrol("ham komut telegram-desktop → bekle",
                oturum.hazirla(os.path.join(bin_, "telegram-desktop"), ham_komut=True).karar == "bekle")
        # Flatpak bilinmeyen uygulama: paylas + kayıt sarmalayıcısı (kafes dışı scope'u yakalamak için)
        h = oturum.hazirla("DhTest Flatpak")
        kontrol("O1 flatpak paylas → sarmalayıcı argv", h.karar == "paylas" and h.argv[:2] == [sys.executable, "-I"]
                and h.argv[2].endswith("flatpak_ornek.py") and "com.example.DhTest" in h.argv, str(h.argv))
        if "--" in h.argv:
            ic = h.argv[h.argv.index("--") + 1:]
            kontrol("O1 sarmalanan komut .desktop Exec'i (alan kodları atılmış)",
                    ic[:2] == ["/usr/bin/flatpak", "run"] and "%U" not in ic and "@@u" not in ic, str(ic))
        open(os.path.join(tdir, "ps"), "a").write(f"777\t{os.getpid() + 900000}\tcom.example.DhTest\n")
        h = oturum.hazirla("DhTest Flatpak")
        kontrol("Y2 flatpak örneği kullanıcıda açık → bekle", h.karar == "bekle", f"{h.karar} {h.ayrinti}")
        open(os.path.join(tdir, "ps_hata"), "w").close()
        h = oturum.hazirla("DhTest Flatpak")
        kontrol("Y2 flatpak ps sorgulanamadı → bekle", h.karar == "bekle" and h.ayrinti.get("belirsiz"), h.karar)
        os.remove(os.path.join(tdir, "ps_hata"))
        kontrol("gerçek flatpak çağrılmadı (yalnız sahte günlük)", not os.path.exists(os.path.join(tdir, "log")))
    finally:
        _sahte_ortam_kapat(tdir, eski_path, eski_dizinler)


def test_ikili_ara_sahte_proc():
    tdir = tempfile.mkdtemp(prefix="deskhand-proc2-")
    for pid, comm, argv, exe in ((11, "telegram-deskto", ["/usr/bin/telegram-desktop", "--"], "telegram-desktop"),
                                 (12, "python3", ["python3", "/usr/bin/dhtestpy", "-x"], "python3.14"),
                                 (13, "bash", ["bash", "-c", "telegram-desktop"], "bash")):
        d = os.path.join(tdir, str(pid)); os.makedirs(d)
        for ad, icerik in (("comm", comm), ("cmdline", "\0".join(argv)), ("exe_link", "/usr/bin/" + exe)):
            with open(os.path.join(d, ad), "w") as f:
                f.write(icerik)
    pidler, okundu = tespit.ikili_ara(["telegram-desktop"], proc_koku=tdir)
    kontrol("ikili_ara exe/argv0 eşleşmesi (bash -c metni eşleşmez)", okundu and pidler == [11], str(pidler))
    pidler, _ = tespit.ikili_ara(["dhtestpy"], proc_koku=tdir)
    kontrol("ikili_ara yorumlayıcı + betik adı", pidler == [12], str(pidler))
    pidler, okundu = tespit.ikili_ara(["x"], proc_koku=os.path.join(tdir, "yok"))
    kontrol("ikili_ara /proc okunamadı → bilinemiyor", not okundu)
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)


def test_ozel_bus_d7():
    """D7: özel veri yolu tespiti gerçek yolu kullanır (RUNTIME_DIR/sanal-N/… ya da durum dosyasındaki adres)."""
    from deskhand import yollar
    rt = yollar.runtime_dir()
    kontrol("D7 özel bus (sanal-N yolu)", tespit._ozel_bus_mu(f"unix:path={rt}/sanal-90/bus"))
    kontrol("D7 gerçek bus özel değil", not tespit._ozel_bus_mu("unix:path=/run/user/1000/bus"))
    os.makedirs(rt, exist_ok=True)
    yol = os.path.join(rt, "sanal.json")
    with open(yol, "w") as f:
        json.dump({"dbus_adres": "unix:abstract=/tmp/dbus-dhtest,guid=1"}, f)
    try:
        kontrol("D7 durum dosyasındaki adres özel", tespit._ozel_bus_mu("unix:abstract=/tmp/dbus-dhtest,guid=1"))
        eski = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/sanal-90/bus"
        try:
            kontrol("D7 _gercek_bus_adresi özel yoldan gerçek yola döner",
                    tespit._gercek_bus_adresi().endswith("/bus") and "/sanal-" not in tespit._gercek_bus_adresi())
        finally:
            if eski is None:
                os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
            else:
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = eski
    finally:
        os.remove(yol)


def test_sqlite_kaynak_yazilmaz():
    """D13: WAL kipindeki kaynak DB'de yedek alınırken kaynak klasörde HİÇBİR dosya oluşmaz/değişmez."""
    tdir = tempfile.mkdtemp(prefix="deskhand-d13-")
    src = os.path.join(tdir, "src"); os.makedirs(src)
    db = os.path.join(src, "cookies.sqlite")
    sahte_cookies(db, [("a.com", "n", "v")])
    c = sqlite3.connect(db); c.execute("PRAGMA journal_mode=WAL"); c.close()
    once = dosya_listesi(src)
    hedef = os.path.join(tdir, "kopya", "cookies.sqlite")
    yontem = kopya.sqlite_yedek(db, hedef)
    kontrol("D13 kaynak klasör aynı (yeni -wal/-shm yok, mtime aynı)", dosya_listesi(src) == once,
            str(dosya_listesi(src)))
    con = sqlite3.connect(hedef)
    n = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
    con.close()
    kontrol("D13 yedek okunur", n == 1 and yontem == "ham-kopya", f"{yontem} {n}")
    # canlı yazıcı: WAL'de birleştirilmemiş kayıt da yedeğe gelir
    tut = sqlite3.connect(db)
    tut.execute("PRAGMA wal_autocheckpoint=0")
    tut.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('','m','k','b.com','/',0)")
    tut.commit()
    once = dosya_listesi(src)
    kopya.sqlite_yedek(db, hedef + "2")
    sonra = dosya_listesi(src)
    con = sqlite3.connect(hedef + "2")
    n = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
    con.close()
    tut.close()
    kontrol("D13 -wal'daki kayıt yedekte", n == 2, str(n))
    kontrol("D13 canlı DB'de de kaynak klasör değişmedi", sonra == once, f"{once} → {sonra}")
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)


def test_flatpak_ornek():
    """O1: sarmalayıcı yeni örneği kaydeder; scope'a bellek sınırı; kapanis önce flatpak kill + bekle, SONRA
    kopyayı siler; kullanıcının kendi örneğine dokunulmaz. Sahte flatpak/systemctl (PATH) — gerçek yok."""
    import subprocess
    import time
    from deskhand.oturum import flatpak_ornek
    tdir, eski_path, eski_dizinler = _sahte_ortam()
    try:
        kayit = politika.flatpak_kayit()
        # kullanıcının kendi örneği (kayıtta yok): asla öldürülmemeli
        with open(os.path.join(tdir, "ps"), "w") as f:
            f.write(f"555\t{os.getpid()}\tcom.example.DhTest\n")
        kopya_yolu = kopya.yeni_kopya_dizini("dhtest")
        os.environ["FAKE_KOPYA"] = kopya_yolu
        argv = flatpak_ornek.sarmala(["flatpak", "run", "--die-with-parent", "com.example.DhTest"],
                                     "com.example.DhTest", kayit, "4G", kopya_yolu, sure=5)
        p = subprocess.Popen(argv, stderr=subprocess.PIPE, text=True)
        bitis = time.monotonic() + 8
        while time.monotonic() < bitis and not flatpak_ornek.oku(kayit):
            time.sleep(0.1)
        girdiler = flatpak_ornek.oku(kayit)
        kontrol("O1 sarmalayıcı yeni örneği kaydetti (kullanıcınınki değil)",
                len(girdiler) == 1 and girdiler[0]["instance"] != "555" and girdiler[0]["kopya"] == kopya_yolu,
                str(girdiler))
        g = girdiler[0] if girdiler else {}
        kontrol("O1 kayıt PID'i çocuğun PID'i (flatpak run → bwrap)", g.get("pid") and g.get("pid") != p.pid,
                str(g))
        kontrol("O1 Flatpak scope'u olmayan cgroup'a sınır uygulanmadı (yanlış birim yok)",
                g.get("scope") is None and not os.path.exists(os.path.join(tdir, "systemctl.log")), str(g))
        # scope_bul + bellek_uygula (sahte /proc + sahte systemctl)
        sp = os.path.join(tdir, "sproc", "4321"); os.makedirs(sp)
        with open(os.path.join(sp, "cgroup"), "w") as f:
            f.write("0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
                    "app-flatpak-com.example.DhTest-4321.scope\n")
        sc = flatpak_ornek.scope_bul(4321, "com.example.DhTest", proc_koku=os.path.join(tdir, "sproc"))
        kontrol("O1 scope_bul cgroup'tan", sc == "app-flatpak-com.example.DhTest-4321.scope", str(sc))
        kontrol("O1 scope_bul cgroup okunamazsa flatpak adlandırması",
                flatpak_ornek.scope_bul(99, "x.Y", proc_koku=os.path.join(tdir, "yok")) == "app-flatpak-x.Y-99.scope")
        kontrol("O1 bellek_uygula başarılı", flatpak_ornek.bellek_uygula(sc, "4G") is None)
        with open(os.path.join(tdir, "systemctl.log")) as f:
            sl = f.read()
        kontrol("O1 systemctl --user --runtime set-property MemoryMax + MemorySwapMax=0",
                f"--user --runtime set-property {sc} MemoryMax=4G MemorySwapMax=0" in sl, sl)
        # tespit: kendi kayıtlı örneğimiz "kullanıcıda açık" sayılmaz, kullanıcınınki sayılır
        calisan = tespit._flatpak_calisan()
        kontrol("O1 kayıtlı örnek kullanıcı örneği sayılmaz", calisan == {"com.example.DhTest"} and
                g.get("instance") not in str(calisan))
        # kapanis: önce kill (kopya o an VAR), bekle, sonra kopya silinir; kullanıcının 555'i dokunulmaz
        uyarilar = oturum.kapanis()
        with open(os.path.join(tdir, "log")) as f:
            log = f.read()
        kontrol("O1 kapanis flatpak kill <örnek> (kopya silinmeden ÖNCE)",
                f"kill {g.get('instance')} kopya=var" in log, log)
        kontrol("O1 kullanıcının örneği öldürülmedi", "kill 555" not in log, log)
        kontrol("O1 kopya örnek kapandıktan sonra silindi", not os.path.exists(kopya_yolu))
        kontrol("O1 kayıt boşaldı", flatpak_ornek.oku(kayit) == [], str(flatpak_ornek.oku(kayit)))
        kontrol("O1 uyarı yok", uyarilar == [], str(uyarilar))
        try:
            p.wait(timeout=5)
            kontrol("O1 sarmalayıcı uygulama kapanınca çıktı", True)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait()
            kontrol("O1 sarmalayıcı uygulama kapanınca çıktı", False)
        # kapanmayan örnek: kopyası SİLİNMEZ, kayıtta kalır
        open(os.path.join(tdir, "kill_etkisiz"), "w").close()
        kopya2 = kopya.yeni_kopya_dizini("dhtest")
        p2 = subprocess.Popen(flatpak_ornek.sarmala(["flatpak", "run", "com.example.DhTest"], "com.example.DhTest",
                                                    kayit, None, kopya2, sure=5), stderr=subprocess.DEVNULL)
        bitis = time.monotonic() + 8
        while time.monotonic() < bitis and not flatpak_ornek.oku(kayit):
            time.sleep(0.1)
        kapanan, kalan, notlar = flatpak_ornek.kapat_hepsi(kayit, sure=0.5)
        kontrol("O1 kapanmayan örnek kayıtta kalır + uyarı", len(kalan) == 1 and notlar, f"{kalan} {notlar}")
        kontrol("O1 sil_hepsi çalışan örneğin kopyasını silmez", oturum.sil_hepsi() == 0 and os.path.isdir(kopya2))
        kontrol("O1 sil_hepsi kayıt dosyasını silmez", os.path.isfile(kayit))
        # SIGTERM (masaustu durdur kafesi kapatırken): sarmalayıcı kendi örneğini flatpak kill ile kapatır
        os.remove(os.path.join(tdir, "kill_etkisiz"))
        p2.terminate()
        p2.wait(timeout=10)
        with open(os.path.join(tdir, "log")) as f:
            log = f.read()
        kontrol("O1 SIGTERM'de sarmalayıcı kendi örneğini kapattı", f"kill {kalan[0]['instance']}" in log, log)
        uyarilar = oturum.kapanis()
        kontrol("O1 sonra kapanis kopyayı siler", not os.path.exists(kopya2), str(uyarilar))
        kontrol("O1 kullanıcının örneği hâlâ listede", "555\t" in open(os.path.join(tdir, "ps")).read())
    finally:
        os.environ.pop("FAKE_KOPYA", None)
        _sahte_ortam_kapat(tdir, eski_path, eski_dizinler)


def test_degisim():
    tdir = tempfile.mkdtemp(prefix="deskhand-deg-")
    hedef = os.path.join(tdir, "k"); os.makedirs(hedef)
    uzun = int(time.time()) + 30 * 86400
    sahte_cookies(os.path.join(hedef, "cookies.sqlite"), [
        ("a.com", "s", "1", uzun), ("b.com", "s", "2", uzun), (".github.com", "_gh_sess", "x", uzun),
        ("c.com", "oturumluk", "z", 0), ("d.com", "giris", "4", uzun * 1000)])  # d.com: milisaniyeli expiry
    once = oturum.cerez_parmak(hedef)
    con = sqlite3.connect(os.path.join(hedef, "cookies.sqlite"))
    con.execute("UPDATE moz_cookies SET value='YENI' WHERE host='b.com'")          # jeton döndü
    con.execute("UPDATE moz_cookies SET value='y' WHERE name='_gh_sess'")         # her istekte değişen
    con.execute("UPDATE moz_cookies SET value='w' WHERE host='c.com'")            # oturumluk
    con.execute("DELETE FROM moz_cookies WHERE host='d.com'")                     # sunucu oturumu kapattı
    con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('','yeni','n','a.com','/',?)",
                (uzun,))                                                            # yeni eklenen çerez
    con.commit(); con.close()
    degisen = oturum.degisim_bildir(once, oturum.cerez_parmak(hedef))
    kontrol("değişim: döndürülen (b.com) ve silinen (d.com) giriş çerezi; _gh_sess/oturumluk/yeni çerez YOK",
            degisen == ["b.com", "d.com"], str(degisen))
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)



def test_profil_grubu_yalitimi():
    """Gerçek olay: kopyaya taşınan toolkit.profiles.storeID, Firefox'un kullanıcının profiles.ini varsayılan yolunu
    ve Profile Groups listesini KOPYAYA çevirmesine yol açtı. Kopyada bu satırlar olmamalı ve kopya Firefox kendi
    yapılandırma köküyle (XDG_CONFIG_HOME) başlamalı."""
    from deskhand.oturum import firefox as ff
    tdir = tempfile.mkdtemp(prefix="deskhand-pg-")
    kaynak, hedef = os.path.join(tdir, "k"), os.path.join(tdir, "h")
    os.makedirs(kaynak); os.makedirs(hedef)
    with open(os.path.join(kaynak, "prefs.js"), "w") as f:
        f.write('user_pref("toolkit.profiles.storeID", "a1b2c3d4");\nuser_pref("browser.profiles.enabled", true);\n'
                'user_pref("browser.profiles.profile-name.updated", true);\nuser_pref("intl.locale.requested", "tr");\n'
                'user_pref("browser.backup.scheduled.enabled", true);\n'
                'user_pref("browser.backup.location", "/home/kisi/Belgeler/Restore Firefox");\n')
    ff._user_js_yaz(hedef, kaynak)
    prefs = open(os.path.join(hedef, "prefs.js")).read()
    kontrol("profil grubu: storeID ve browser.profiles.* kopyaya ALINMAZ, diğer ayarlar kalır",
            "storeID" not in prefs and "browser.profiles" not in prefs and "intl.locale.requested" in prefs, prefs)
    uj = open(os.path.join(hedef, "user.js")).read()
    kontrol("profil grubu: user.js profilleri kapatır", 'browser.profiles.enabled", false' in uj and
            'toolkit.profiles.storeID", ""' in uj)
    kontrol("yedekleme: kopya kullanıcının yedek klasörüne yazamaz (browser.backup.* alınmaz, user.js kapatır)",
            "browser.backup" not in prefs and 'browser.backup.scheduled.enabled", false' in uj and
            'browser.backup.enabled", false' in uj)
    import shutil
    shutil.rmtree(tdir, ignore_errors=True)

def test_cli():
    from deskhand.oturum import cli
    kontrol("cli politika 0", cli.main(["politika", "firefox", "--json"]) == 0)
    kontrol("cli durum 0", cli.main(["durum", "telegram"]) == 0)
    # hazirla bekle → çıkış 3
    kontrol("cli hazirla telegram=3", cli.main(["hazirla", "telegram"]) == 3)
    kontrol("cli sil 0", cli.main(["sil"]) == 0)


def main():
    test_politika()
    test_politika_esleme()
    test_politika_birlestir()
    test_firefox_kopya()
    test_sqlite_kilitli()
    test_chromium_dizin_kopya()
    test_flatpak_argv()
    test_flatpak_electron_kopya()
    test_tespit_sahte_proc()
    test_tespit_lock_ve_singleton()
    test_tespit_soyut_soket()
    test_hazirla_kararlar()
    test_cozum_ve_hazirla()
    test_ikili_ara_sahte_proc()
    test_ozel_bus_d7()
    test_sqlite_kaynak_yazilmaz()
    test_flatpak_ornek()
    test_degisim()
    test_profil_grubu_yalitimi()
    test_cli()
    print(f"\n{gecen}/{toplam} geçti")
    return 0 if gecen == toplam else 1


if __name__ == "__main__":
    sys.exit(main())
