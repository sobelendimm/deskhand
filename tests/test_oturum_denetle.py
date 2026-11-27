"""Süresiz oturum çerezleri + `sessions check` (denetle) testleri (EKRANSIZ; gerçek profile DOKUNMAZ).

Sahte Firefox profili geçici klasörde: cookies.sqlite (gerçek moz_cookies şeması, ms birimli expiry) +
sessionstore-backups/recovery.jsonlz4 (mozLz40 biçimi). Uydurma alan adları (*.test).
Doğrulananlar:
  - süresiz oturum çerezi (yalnız recovery.jsonlz4'te) izinli sitede kopyaya geçer, ret listesindekinde geçmez
  - aynı anahtarda SÜRESİ GEÇMİŞ kalıcı satır canlı oturum çerezini artık engellemez; geçerli kalıcı satır kalır
  - bölümlenmiş (CHIPS) çerezde isPartitionedAttributeSet, updateTime yazılır; kopya dizini 0700; kaynak değişmez
  - denetle: profil var/süresi geçmiş/yok/politika dışı, kopya güncel/eski/oturumsuz/yok, çıkış kodları 0/1/2,
    --cerez deseni, Türkçe takma ad; çıktıda (metin + JSON) çerez DEĞERİ yok

Çalıştır:  python3 tests/test_oturum_denetle.py
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici; Deskhand'den ÖNCE)

from deskhand import oturum
from deskhand.oturum import cli, denetle, firefox, politika

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


_SEMA = (
    "CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
    "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, lastAccessed INTEGER, "
    "creationTime INTEGER, isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0, "
    "sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0, isPartitionedAttributeSet INTEGER DEFAULT 0, "
    "updateTime INTEGER, CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))")

SIMDI = time.time()
GIZLI = ("DEGER-GIZLI-1", "DEGER-GIZLI-2", "DEGER-GIZLI-3", "DEGER-GIZLI-4", "DEGER-YENI-5", "DEGER-BANKA-6")


def _ms(sn):
    return int((SIMDI + sn) * 1000)


def kalici_yaz(db, satirlar, olusma=None):
    """satirlar: (host, name, value, expiry_ms)."""
    yeni = not os.path.exists(db)
    con = sqlite3.connect(db)
    if yeni:
        con.execute(_SEMA)
    mikro = int((olusma or SIMDI - 3600) * 1e6)
    for host, name, value, exp in satirlar:
        con.execute("INSERT OR REPLACE INTO moz_cookies (originAttributes,name,value,host,path,expiry,lastAccessed,"
                    "creationTime,isSecure,isHttpOnly,updateTime) VALUES ('',?,?,?,'/',?,?,?,1,1,?)",
                    (name, value, host, exp, mikro, mikro, mikro))
    con.commit()
    con.close()


def mozlz4_yaz(yol, obj):
    import lz4.block
    ham = json.dumps(obj).encode()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "wb") as f:
        f.write(b"mozLz40\0" + struct.pack("<I", len(ham)) + lz4.block.compress(ham, store_size=False))


def _oa(pk=""):
    return {"firstPartyDomain": "", "geckoViewSessionContextId": "", "partitionKey": pk, "privateBrowsingId": 0,
            "userContextId": 0}


def sahte_profil(kok):
    os.makedirs(kok, exist_ok=True)
    prof = "zz99.default-release"
    pdir = os.path.join(kok, prof)
    os.makedirs(os.path.join(pdir, "sessionstore-backups"), exist_ok=True)
    with open(os.path.join(kok, "profiles.ini"), "w") as f:
        f.write(f"[Profile0]\nName=d\nIsRelative=1\nPath={prof}\nDefault=1\n\n[InstallX]\nDefault={prof}\nLocked=1\n")
    # kalıcı: dukkan.test'in kalıcı giriş çerezi GEÇERLİ; eski.test'te aynı adlı süresi GEÇMİŞ satır (bayat) +
    # geçerli kalıcı çakışan satır (kalmalı); izleme çerezi (giriş değil)
    kalici_yaz(os.path.join(pdir, "cookies.sqlite"), [
        ("www.dukkan.test", "sec_session_id", GIZLI[0], _ms(7200)),
        (".dukkan.test", "viewedModal", "1", _ms(86400 * 10)),
        ("eski.test", "PHPSESSID", "BAYAT", _ms(-3600)),
        ("eski.test", "auth_token", "KALICI-GECERLI", _ms(3600)),
        ("www.ornekbank.test", "sessionid", GIZLI[5], _ms(3600)),
        # domain cookie of a site whose subdomain matches the `*bank*` reject rule; that subdomain is known only from
        # site storage (no cookie row), as in firefox._bilinen_konaklar
        (".ortak.test", "sessionid", "ORTAK-ALAN-GIZLI", _ms(3600)),
    ])
    os.makedirs(os.path.join(pdir, "storage", "default", "https+++bank.ortak.test"), exist_ok=True)
    mozlz4_yaz(os.path.join(pdir, "sessionstore-backups", "recovery.jsonlz4"), {"cookies": [
        {"host": "www.dukkan.test", "name": "PHPSESSID", "value": GIZLI[1], "path": "/", "sameSite": 256,
         "schemeMap": 2, "originAttributes": _oa()},
        {"host": "eski.test", "name": "PHPSESSID", "value": GIZLI[2], "path": "/", "originAttributes": _oa()},
        {"host": "eski.test", "name": "auth_token", "value": "SURESIZ-CAKISAN", "path": "/", "originAttributes": _oa()},
        {"host": "gomulu.test", "name": "sid", "value": GIZLI[3], "path": "/", "isPartitioned": True,
         "originAttributes": _oa("(https,dukkan.test)")},
        {"host": "www.ornekbank.test", "name": "bank_session", "value": "BANKA-SURESIZ", "path": "/",
         "originAttributes": _oa()},
    ]})
    for ad in ("key4.db", "cert9.db", "prefs.js"):
        with open(os.path.join(pdir, ad), "w") as f:
            f.write("x")
    return pdir


def agac_sha1(kok):
    h = hashlib.sha1()
    for k, _d, dosyalar in sorted(os.walk(kok)):
        for f in sorted(dosyalar):
            with open(os.path.join(k, f), "rb") as fh:
                h.update(f.encode() + fh.read())
    return h.hexdigest()


def cli_kos(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        kod = cli.main(argv)
    return kod, out.getvalue()


def degersiz(metin):
    return not any(v in metin for v in GIZLI + ("BAYAT", "KALICI-GECERLI", "SURESIZ-CAKISAN", "BANKA-SURESIZ",
                                       "ORTAK-ALAN-GIZLI"))


def main():
    tdir = tempfile.mkdtemp(prefix="deskhand-denetle-src-")
    eski_home, eski_xdg = os.environ.get("HOME"), os.environ.get("XDG_CONFIG_HOME")
    os.environ["HOME"] = tdir
    os.environ.pop("XDG_CONFIG_HOME", None)
    try:
        pdir = sahte_profil(os.path.join(tdir, ".config", "mozilla", "firefox"))
        once = agac_sha1(pdir)

        # ---- 1) kopya yokken denetle (profil kararı)
        kod, cikti = cli_kos(["check", "dukkan.test"])
        kontrol("kopya yok + profilde geçerli kalıcı giriş çerezi → 0", kod == 0, cikti)
        kontrol("çıktıda süresiz (tarayıcı oturumu) PHPSESSID görünür", "PHPSESSID" in cikti and "süresiz" in cikti, cikti)
        kontrol("giriş çerezi olmayan (viewedModal) listelenmez", "viewedModal" not in cikti, cikti)
        kontrol("çıktıda değer yok", degersiz(cikti), cikti)
        kod, cikti = cli_kos(["denetle", "https://www.dukkan.test/m/orders.php", "--json"])
        d = json.loads(cikti)
        kontrol("Türkçe takma ad + adres girdisi + JSON", kod == 0 and d["alan"] == "www.dukkan.test", cikti)
        kontrol("JSON'da değer/özet yok", degersiz(cikti) and "_oz" not in cikti, cikti)
        kod, cikti = cli_kos(["check", "x"])
        kontrol("geçersiz alan → 2", kod == 2, cikti)
        kod, cikti = cli_kos(["check", "yok.test"])
        kontrol("çerezsiz site → 1 (oturum çerezi yok)", kod == 1 and "yok" in cikti, cikti)
        kod, cikti = cli_kos(["check", "ornekbank.test"])
        kontrol("ret listesindeki site → 1 (politika dışı)", kod == 1 and "politika" in cikti, cikti)
        kontrol("ret sitesi çıktısında değer yok", degersiz(cikti), cikti)
        kod, cikti = cli_kos(["check", "www.ortak.test"])
        d = denetle.denetle("www.ortak.test")
        kontrol("alan çerezi reddedilen bilinen alt alana gider (`*bank*`) → politika dışı, 1 (hazirla ile aynı)",
                kod == 1 and d["profil_durum"] == "politika_disi" and d["cerezler"]
                and not any(c["tasinir"] for c in d["cerezler"]), str(d))
        kontrol("alan çerezi çıktısında değer yok", degersiz(cikti), cikti)
        d = denetle.denetle("dukkan.test", desenler=["sec_*"])
        kontrol("--cerez deseni yalnız o çerezi sayar", [c["ad"] for c in d["cerezler"]] == ["sec_session_id"],
                str(d["cerezler"]))

        # ---- 2) gerçek olay benzetimi: kalıcı giriş çerezinin süresi geçmiş, yalnız süresiz PHPSESSID kalmış
        d = denetle.denetle("dukkan.test", simdi=SIMDI + 3 * 3600)
        kontrol("süresi geçmiş kalıcı + yalnız süresiz → suresi_gecmis, kod 1",
                d["profil_durum"] == "suresi_gecmis" and d["kod"] == 1, str(d))

        # ---- 3) kopya: süresiz oturum çerezleri izinli sitede kopyaya geçer
        pol = politika.coz("firefox")
        b = firefox.hazirla(pol)
        hedef = b["kopya_yolu"]
        kontrol("kopya hazır", b["durum"] is None and hedef and os.path.isdir(hedef), str(b.get("durum")))
        con = sqlite3.connect(os.path.join(hedef, "cookies.sqlite"))
        satir = {(r[0], r[1]): r[2:] for r in con.execute(
            "SELECT host, name, value, expiry, isPartitionedAttributeSet, updateTime, originAttributes FROM moz_cookies")}
        con.close()
        kontrol("süresiz PHPSESSID (izinli) kopyada, değer aynı",
                satir.get(("www.dukkan.test", "PHPSESSID"), ("",))[0] == GIZLI[1], str(satir.keys()))
        kontrol("süresiz çerez kopyada geleceğe dönük bitişle (Firefox açılışta atmaz)",
                satir.get(("www.dukkan.test", "PHPSESSID"), (0, 0))[1] > SIMDI * 1000)
        kontrol("aynı anahtarda süresi GEÇMİŞ kalıcı satır canlı oturum çerezini engellemez",
                satir.get(("eski.test", "PHPSESSID"), ("",))[0] == GIZLI[2], str(satir.get(("eski.test", "PHPSESSID"))))
        kontrol("geçerli kalıcı çakışan satır kalır (süresiz olanla ezilmez)",
                satir.get(("eski.test", "auth_token"), ("",))[0] == "KALICI-GECERLI")
        g = satir.get(("gomulu.test", "sid"))
        kontrol("bölümlenmiş çerez: partitionKey + isPartitionedAttributeSet=1 + updateTime",
                g is not None and g[2] == 1 and g[3] and "partitionKey=" in g[4], str(g))
        kontrol("ret listesindeki süresiz çerez kopyaya geçmez", ("www.ornekbank.test", "bank_session") not in satir)
        kontrol("ret listesindeki kalıcı çerez kopyaya geçmez", ("www.ornekbank.test", "sessionid") not in satir)
        kontrol("reddedilen alt alana giden alan çerezi (.ortak.test) kopyaya geçmez",
                (".ortak.test", "sessionid") not in satir, str(satir.keys()))
        kontrol("kopya dizini 0700", (os.stat(hedef).st_mode & 0o777) == 0o700)
        kontrol("kopya dosyaları 0600", all((os.stat(os.path.join(k, f)).st_mode & 0o777) == 0o600
                                            for k, _d, fs in os.walk(hedef) for f in fs))
        kontrol("kaynak profil değişmedi", agac_sha1(pdir) == once)

        # ---- 4) kopya varken denetle
        kod, cikti = cli_kos(["check", "dukkan.test"])
        kontrol("kopya güncel → 0", kod == 0 and "güncel" in cikti, cikti)
        kontrol("kopya satırları değersiz", degersiz(cikti), cikti)
        # kullanıcı kopyadan SONRA yeniden giriş yaptı: profilde yeni değer + yeni oluşturma zamanı
        time.sleep(0.01)
        kalici_yaz(os.path.join(pdir, "cookies.sqlite"),
                   [("www.dukkan.test", "sec_session_id", GIZLI[4], _ms(7200))], olusma=time.time() + 5)
        kod, cikti = cli_kos(["check", "dukkan.test"])
        d = denetle.denetle("dukkan.test")
        kontrol("profilde kopyadan yeni giriş → kopya eski, 1", kod == 1 and d["kopya_durum"] == "eski", cikti)
        kontrol("eski kopya çıktısında değer yok", degersiz(cikti), cikti)
        # kopyanın kendi giriş çerezinin süresi geçti (zaman ilerletilerek): kopya oturumsuz
        d = denetle.denetle("dukkan.test", simdi=SIMDI + 3 * 3600)
        kontrol("kopyada kalıcı giriş çerezi geçmiş + yalnız süresiz → oturumsuz, 1",
                d["kopya_durum"] == "oturumsuz" and d["kod"] == 1, str(d))
        oturum.temizle(hedef)
        kontrol("temizle sonrası kopya yok", denetle.denetle("dukkan.test")["kopya"] is None)
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
