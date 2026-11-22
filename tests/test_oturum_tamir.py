"""Oturum / görünmez masaüstü / CLI masaüstü seçimi düzeltmelerinin regresyon testleri (0.9.0 taraması).

1) Firefox kopyasının XDG_CONFIG_HOME'u: kullanıcının user-dirs.dirs / user-dirs.locale (0600) + GTK görünümü; ad
   alanında GLib İndirilenler/Masaüstü'nü GERÇEK XDG yollarına çözer (eskiden None / ~/Desktop → indirilenler
   geçici ~/Downloads'a gidip kayboluyordu); user.js browser.download.dir + folderList=2; görev kipinde görev klasörü.
2) recovery.jsonlz4 oturum çerezleri: expiry gelecekte (birim mevcut satırlardan), originAttributes Firefox soneki
   (partitionKey + userContextId), gizli pencere çerezi atlanır; kapanış uyarısı yalnız kimlik alanları.
3) Masaüstü sahipliği: CLI'nin ata zincirindeki claude sahip yazılır (iki sahte claude), sahipsiz ama dolu varsayılan →
   MCP oturum-1, sahibi ölen CLI masaüstü süpürülür; uygulama_pidleri yalnız en üst bwrap süreçleri.
4) CLI --desktop-name her konumda, desktop --desktop-name, çıkış kodu 1; scroll X Y biçimi, --at, varsayılan adım 3.
5) Önbellek sınırı (user.js, Chromium --disk-cache-size), canlı kopya sınırı uyarısı.
6) Kopya dosyaları 0600; ölçek uyuşmazlığı çıkış 1 + JSON alanı; yarım insan-dogrulama.json.*.tmp süpürülür.

SAHTE ev (arka_ortak._EV_ZORLA) ve _yalitim'in geçici DESKHAND_* dizinleri; gerçek profil/ekran/masaüstü kullanılmaz.
Çalıştır:  python3 tests/test_oturum_tamir.py"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import arka_ortak as ao
from deskhand import cli, gunluk, masalar, masaustu
from deskhand.hata import Dur
from deskhand.oturum import chromium, firefox, kopya, politika

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod
    return None


kok = tempfile.mkdtemp(prefix="deskhand-tamir-", dir=_yalitim.GECICI)
EV = os.path.join(kok, "ev")
GERCEK_EV = os.path.realpath(os.path.expanduser("~"))
os.makedirs(os.path.join(EV, ".config", "gtk-3.0"))
os.makedirs(os.path.join(EV, "Indirilenler"))
os.makedirs(os.path.join(EV, "Masaustu"))
USER_DIRS = 'XDG_DESKTOP_DIR="$HOME/Masaustu"\nXDG_DOWNLOAD_DIR="$HOME/Indirilenler"\n'
with open(os.path.join(EV, ".config", "user-dirs.dirs"), "w") as f:
    f.write(USER_DIRS)
with open(os.path.join(EV, ".config", "user-dirs.locale"), "w") as f:
    f.write("tr_TR\n")
with open(os.path.join(EV, ".config", "gtk-3.0", "settings.ini"), "w") as f:
    f.write("[Settings]\ngtk-theme-name=Breeze\n")
ao._EV_ZORLA = EV

# ---------------------------------------------------------------- 1) XDG yapılandırması
print("\n1) Firefox kopyasının XDG yapılandırması")
hedef = kopya.yeni_kopya_dizini("firefox")
xdg = os.path.join(hedef, ".xdg-config")
indir = firefox.xdg_yapilandirma_kur(xdg)
ud = os.path.join(xdg, "user-dirs.dirs")
kontrol("user-dirs.dirs gerçek dosyayla AYNI", os.path.isfile(ud) and open(ud).read() == USER_DIRS)
kontrol("user-dirs.locale + gtk-3.0/settings.ini kopyalandı",
        os.path.isfile(os.path.join(xdg, "user-dirs.locale")) and
        os.path.isfile(os.path.join(xdg, "gtk-3.0", "settings.ini")))
kontrol("XDG dosyaları 0600", all(os.stat(os.path.join(d, f)).st_mode & 0o077 == 0
                                  for d, _a, fs in os.walk(xdg) for f in fs))
kontrol("indirme dizini = XDG_DOWNLOAD_DIR (gerçek veri klasörü)", indir == os.path.join(EV, "Indirilenler"), str(indir))
with open(os.path.join(hedef, "user.js"), "w") as f:
    f.write(firefox._USER_JS)
firefox._indirme_prefleri_yaz(hedef, indir)
uj = open(os.path.join(hedef, "user.js")).read()
kontrol("user.js browser.download.dir + folderList=2",
        f'"browser.download.dir", {json.dumps(indir)}' in uj and '"browser.download.folderList", 2' in uj, uj[-200:])
kontrol("5) user.js önbellek sınırı (smart_size kapalı, 64 MB)",
        '"browser.cache.disk.smart_size.enabled", false' in uj and '"browser.cache.disk.capacity", 65536' in uj)
kontrol("görev user.js'te eski folderList=1 yok", '"browser.download.folderList", 1' not in firefox._GOREV_USER_JS)

xdg_g = os.path.join(kok, "gorev-xdg")
from deskhand import gorev_kipi  # noqa: E402
gindir = firefox.xdg_yapilandirma_kur(xdg_g, gorev=True)
icerik = open(os.path.join(xdg_g, "user-dirs.dirs")).read()
kontrol("görev kipi: XDG_DOWNLOAD_DIR görev indirme yolunu gösterir (tek satır)",
        gindir == gorev_kipi.indirme_hedefi(EV) and icerik.count("XDG_DOWNLOAD_DIR") == 1 and
        f'XDG_DOWNLOAD_DIR="{gindir}"' in icerik, icerik)
os.rename(os.path.join(EV, "Indirilenler"), os.path.join(EV, "Indirilenler-yok"))
kontrol("İndirilenler ad alanında görünmüyorsa indirme tercihi yazılmaz (None)", firefox.indirme_dizini(False, EV) is None)
os.rename(os.path.join(EV, "Indirilenler-yok"), os.path.join(EV, "Indirilenler"))

GLIB = ("from gi.repository import GLib as G; U = G.UserDirectory; "
        "print(G.get_user_special_dir(U.DIRECTORY_DOWNLOAD)); print(G.get_user_special_dir(U.DIRECTORY_DESKTOP))")
gi_var = subprocess.run(["/usr/bin/python3", "-c", "import gi"], capture_output=True).returncode == 0
if shutil.which("bwrap") and gi_var:
    bos = os.path.join(kok, "bos-xdg")
    os.makedirs(bos, mode=0o700)

    def ad_alani(xdg_kok):
        argv = ao.korumali_argv(["/usr/bin/python3", "-I", "-c", GLIB], os.path.join(kok, "rt"), [(xdg_kok, True)],
                                ev=EV)
        i = argv.index("--tmpfs") + 2  # gerçek ev de boş (sonda gerçek ~/.config okunamaz)
        argv = argv[:i] + ["--tmpfs", GERCEK_EV] + argv[i:]
        return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                              env={"HOME": EV, "PATH": "/usr/bin", "XDG_CONFIG_HOME": xdg_kok, "LANG": "C.UTF-8"})
    r = ad_alani(bos)
    kontrol("kök neden: boş XDG_CONFIG_HOME'da GLib İndirilenler'i çözemez / Masaüstü = ~/Desktop",
            r.stdout.split("\n")[:2] == ["None", os.path.join(EV, "Desktop")], r.stdout + r.stderr[-300:])
    r = ad_alani(xdg)
    kontrol("ad alanı (korumali_argv + Firefox env_ek): GLib DOWNLOAD/DESKTOP = gerçek XDG yolları",
            r.stdout.split("\n")[:2] == [os.path.join(EV, "Indirilenler"), os.path.join(EV, "Masaustu")],
            r.stdout + r.stderr[-300:])
else:
    print("atlandı: bwrap ya da python3-gobject yok (ad alanı GLib sınaması)")

# Flatpak Electron kopyasında da (sandbox XDG_CONFIG_HOME = <kopya>/config)
pol_fk = politika.coz("discord")
pol_fk.flatpak = "com.discordapp.Discord"
b = chromium.flatpak_electron_hazirla(pol_fk, "discord")
kontrol("Flatpak Electron kopyası: config/user-dirs.dirs var",
        bool(b.get("kopya_yolu")) and os.path.isfile(os.path.join(b["kopya_yolu"], "config", "user-dirs.dirs")),
        str(b.get("durum")))
kontrol("5) Chromium argv --disk-cache-size", any(a.startswith("--disk-cache-size=") for a in
                                                  chromium.chromium_argv("chromium", "/x")))
kopya.temizle(b.get("kopya_yolu") or "")

# ---------------------------------------------------------------- 2) oturum çerezleri
print("\n2) oturum çerezleri (recovery.jsonlz4)")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_oturum import _COOKIES_SEMA, mozlz4_yaz  # noqa: E402

db = os.path.join(hedef, "cookies.sqlite")
con = sqlite3.connect(db)
con.execute(_COOKIES_SEMA)
con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('','k','v','github.com','/',?)",
            (int((time.time() + 86400 * 30) * 1000),))
con.commit()
con.close()
oa = {"firstPartyDomain": "", "geckoViewSessionContextId": "", "partitionKey": "(https,example.com)",
      "privateBrowsingId": 0, "userContextId": 2}
rec = os.path.join(kok, "recovery.jsonlz4")
mozlz4_yaz(rec, {"cookies": [
    {"host": "github.com", "name": "oturum", "value": "X", "path": "/", "originAttributes": oa},
    {"host": "github.com", "name": "duz", "value": "Y", "path": "/", "originAttributes": {**oa, "partitionKey": "",
                                                                                          "userContextId": 0}},
    {"host": "github.com", "name": "gizli", "value": "Z", "path": "/",
     "originAttributes": {**oa, "privateBrowsingId": 1}}]})
pol = politika.coz("firefox")
eklendi, _al = firefox._oturum_cerezleri_ekle(rec, db, pol, None)
con = sqlite3.connect(db)
satir = {r[0]: r[1:] for r in con.execute("SELECT name, expiry, originAttributes FROM moz_cookies")}
con.close()
simdi_ms = time.time() * 1000
kontrol("oturum çerezi expiry > şimdi (ms, mevcut satırlardan)", satir.get("oturum", (0,))[0] > simdi_ms, str(satir))
kontrol("partitionKey + userContextId → Firefox soneki",
        satir.get("oturum", (0, ""))[1] == "^userContextId=2&partitionKey=%28https%2Cexample.com%29", str(satir))
kontrol("varsayılan bağlam → ''", satir.get("duz", (0, None))[1] == "", str(satir))
kontrol("gizli pencere çerezi atlandı", "gizli" not in satir and eklendi == 2, str(satir))
db2 = os.path.join(kok, "c2.sqlite")
con = sqlite3.connect(db2)
con.execute(_COOKIES_SEMA)
con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('','k','v','github.com','/',?)",
            (int(time.time() + 86400 * 30),))
con.commit()
con.close()
firefox._oturum_cerezleri_ekle(rec, db2, pol, None)
con = sqlite3.connect(db2)
e = con.execute("SELECT expiry FROM moz_cookies WHERE name='oturum'").fetchone()[0]
con.close()
kontrol("saniye birimli DB'de expiry saniye ve gelecekte", time.time() < e < time.time() + 2 * 86400, str(e))
kontrol("oa_soneki: firstPartyDomain ':' → '+', bilinmeyen dolu alan → None",
        firefox.oa_soneki({"firstPartyDomain": "a:b"}) == "^firstPartyDomain=a%2Bb" and
        firefox.oa_soneki({"yeniAlan": "x"}) is None and firefox.oa_soneki("^userContextId=1") == "^userContextId=1")

# kapanış uyarısı: yalnız kimlik alanları, "asıl profil değiştirilmedi"
from deskhand import oturum  # noqa: E402
k2 = kopya.yeni_kopya_dizini("firefox")
cdb = os.path.join(k2, "cookies.sqlite")
con = sqlite3.connect(cdb)
con.execute(_COOKIES_SEMA)
ileri = int((time.time() + 86400 * 30) * 1000)
for h, n in ((".google.com", "SID"), ("github.com", "user_session")):
    con.execute("INSERT INTO moz_cookies (originAttributes,name,value,host,path,expiry) VALUES ('',?,'eski',?,'/',?)",
                (n, h, ileri))
con.commit()
con.close()
oturum.parmak_kaydet(k2)
con = sqlite3.connect(cdb)
con.execute("UPDATE moz_cookies SET value='yeni'")
con.commit()
con.close()
uy = oturum._kapanis_ic()
metin = " ".join(uy)
kontrol("kapanış uyarısı yalnız kimlik alanı (google.com), github.com yok, 'asıl profil değiştirilmedi'",
        "google.com" in metin and "github.com" not in metin and "asıl profil değiştirilmedi" in metin, metin)
kontrol("kimlik_alani_mi", politika.kimlik_alani_mi(".live.com") and not politika.kimlik_alani_mi("github.com")
        and not politika.kimlik_alani_mi("com"))

# ---------------------------------------------------------------- 6) kopya izinleri
print("\n6) kopya izinleri")
k3 = kopya.yeni_kopya_dizini("firefox")
with open(os.path.join(k3, "a.txt"), "w") as f:
    f.write("x")
os.makedirs(os.path.join(k3, "alt"), mode=0o755)
with open(os.path.join(k3, "alt", "b"), "w") as f:
    f.write("x")
os.chmod(os.path.join(k3, "alt", "b"), 0o644)
kopya.izinleri_daralt(k3)
kontrol("kopyadaki tüm dosya/dizinler & 0o077 == 0",
        all(os.stat(os.path.join(d, x)).st_mode & 0o077 == 0 for d, ds, fs in os.walk(k3) for x in ds + fs))
kontrol("5) canlı kopyalar sınırı aşınca uyarı (silinmez)",
        kopya.sinir_uygula(azami_sayi=1) == [] and bool(kopya.son_uyari()) and os.path.isdir(k3), str(kopya.son_uyari()))
kopya.sinir_uygula()
for k_ in (hedef, k2, k3):
    kopya.temizle(k_)

from deskhand.hata import calisma_dizini  # noqa: E402
olu = subprocess.Popen(["true"])
olu.wait()
y_olu = os.path.join(calisma_dizini(), f"insan-dogrulama.json.{olu.pid}.tmp")
y_canli = os.path.join(calisma_dizini(), f"insan-dogrulama.json.{os.getpid()}.tmp")
for y in (y_olu, y_canli):
    open(y, "w").close()
gunluk.temizle()
kontrol("yarım insan-dogrulama.json.<ölü pid>.tmp süpürüldü, canlınınki kaldı",
        not os.path.exists(y_olu) and os.path.exists(y_canli))
os.remove(y_canli)

eski_baslat = masaustu.masaustu_baslat
masaustu.masaustu_baslat = lambda *a, **k: {"zaten": True, "olcek_uyari": "ölçek 1 ile açık", "boyut": [1, 1]}
try:
    import contextlib
    import io
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon):
        kod = masaustu.main(["start", "--scale", "2", "--json"])
    d = json.loads(tampon.getvalue())
    kontrol("açık masaüstü farklı ölçekle: çıkış 1 + JSON olcek_uyusmaz", kod == 1 and d.get("olcek_uyusmaz") is True,
            f"{kod} {d}")
finally:
    masaustu.masaustu_baslat = eski_baslat

# ---------------------------------------------------------------- 3) sahiplik
print("\n3) masaüstü sahipliği (sahte claude ata zincirleri)")
bin_ = os.path.join(kok, "bin")
os.makedirs(bin_)
claude = os.path.join(bin_, "claude")
with open(claude, "w") as f:  # comm = "claude" (shebang betik adı); çocuğu argv[1:]'i çalıştırır
    f.write("#!/usr/bin/python3\nimport subprocess, sys\nsys.exit(subprocess.run(sys.argv[1:]).returncode)\n")
os.chmod(claude, 0o755)
A_KOD = ("import sys; from deskhand import masalar; print(masalar.cli_sahiplen('t1'), flush=True); sys.stdin.read()")
B_KOD = ("from deskhand import masalar, masaustu\nfrom deskhand.hata import Dur\n"
         "def k(f):\n    try:\n        f(); return 0\n    except Dur as e:\n        return e.kod\n"
         "print(k(lambda: masalar.erisim_kapisi('t1')), k(lambda: masaustu.masaustu_durdur('t1')),"
         " masalar.cli_sahiplen('t1'))")
a_p = subprocess.Popen([claude, sys.executable, "-c", A_KOD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
try:
    ilk = a_p.stdout.readline().strip()
    s = masalar.sahip_oku("t1")
    kontrol("A (claude) altında CLI sahiplendi: sahip = A'nın claude süreci, tür cli",
            ilk == "True" and s is not None and s["pid"] == a_p.pid and s["cli"], f"{ilk} {s} A={a_p.pid}")
    r = subprocess.run([claude, sys.executable, "-c", B_KOD], capture_output=True, text=True, timeout=60)
    kontrol("B (başka claude): erişim + stop → Dur 14, sahiplenemez", r.stdout.split() == ["14", "14", "False"],
            r.stdout + r.stderr[-300:])
finally:
    a_p.stdin.close()
    a_p.wait(timeout=30)
kontrol("A ölünce sahip kaydı ölü, masaüstü cli işaretli", masalar.sahip_oku("t1") is None and masalar.cli_mu("t1"))
kontrol("sahibi ölen CLI masaüstü süpürülür (dizin silinir)",
        "t1" in masaustu.oto_temizle() and not os.path.exists(masalar.kok("t1")))

# uygulama_pidleri: kafesteki en üst bwrap (sahte: bu sürecin cgroup'u, 'bwrap' adlı uyuyan süreç)
cg = ao._cgroup(os.getpid())
sahte_bwrap = os.path.join(bin_, "bwrap")
shutil.copy("/usr/bin/sleep", sahte_bwrap)
uyu = subprocess.Popen([sahte_bwrap, "30"])
try:
    masalar.kok_hazirla("t3")
    with open(masaustu.durum_yolu("t3"), "w") as f:
        json.dump({"cgroup": cg, "kafes": os.path.basename(cg), "pid": {"kwin": os.getpid()}}, f)
    pidler = masaustu.uygulama_pidleri("t3")
    kontrol("uygulama_pidleri: kafesteki en üst bwrap süreci (altyapı değil)", uyu.pid in pidler and
            os.getpid() not in pidler, f"{pidler} cg={cg}")
finally:
    uyu.kill()
    uyu.wait()
    os.remove(masaustu.durum_yolu("t3"))
    masalar.kok_sil("t3")

# MCP otomatik bağlanma: sahipsiz ama dolu varsayılan → oturum-1
try:
    from deskhand import mcp_sunucu
except ImportError:
    mcp_sunucu = None
    print("atlandı: mcp paketi yok (MCP bağlanma sınaması)")
if mcp_sunucu is not None:
    eski_dolu = masaustu.dolu_mu
    eski_masa = dict(mcp_sunucu._MASA)
    try:
        for dolu, beklenen in ((True, "oturum-1"), (False, "")):
            masaustu.dolu_mu = lambda ad, _d=dolu: _d and ad == ""
            mcp_sunucu._MASA.update(bagli=False, ad="", oto=False, sahip=False, sabit=None, ilk_ppid=None)
            ad = mcp_sunucu.masa_bagla()
            kontrol(f"MCP: varsayılan sahipsiz ve {'DOLU' if dolu else 'boş'} → {beklenen or 'varsayılan'}",
                    ad == beklenen, repr(ad))
            masalar.birak(ad)
            masalar.kok_sil(ad)
            os.environ.pop(masalar.ORTAM, None)
    finally:
        masaustu.dolu_mu = eski_dolu
        mcp_sunucu._MASA.clear()
        mcp_sunucu._MASA.update(eski_masa)

# ---------------------------------------------------------------- 4) CLI masaüstü seçimi + scroll
print("\n4) CLI --desktop-name ve scroll")
os.environ.pop(masalar.ORTAM, None)
kontrol("--background --desktop-name X windows", cli._masa_secenegi(["--background", "--desktop-name", "xa", "windows"])
        == ["--background", "windows"] and os.environ.get(masalar.ORTAM) == "xa")
kontrol("-b DESEN --desktop-name=Y click (değerli seçenek atlanır)",
        cli._masa_secenegi(["-b", "--desktop-name", "--desktop-name=yb", "click", "w", "--desktop-name", "metin"])
        == ["-b", "--desktop-name", "click", "w", "--desktop-name", "metin"] and os.environ.get(masalar.ORTAM) == "yb")
os.environ.pop(masalar.ORTAM, None)
p = cli.ayristirici()
a = p.parse_args(["windows", "--desktop-name", "zc"])
kontrol("alt komutta windows --desktop-name x kabul", a.masa == "zc")
a = p.parse_args(["scroll", "w1", "300", "400", "up"])
kontrol("scroll ID X Y yön → --point X,Y", (a.nokta, a.yon, a.adim) == ("300,400", "yukari", cli.KAYDIR_ADIM))
a = p.parse_args(["scroll", "w1", "--at", "5,6"])
kontrol("scroll --at takma adı", a.nokta == "5,6")
r = subprocess.run([sys.executable, "-m", "deskhand", "scroll", "w1", "300"], capture_output=True, text=True, timeout=60)
kontrol("scroll ID 300 → çıkış 1 + --point ipucu", r.returncode == 1 and "--point" in r.stderr, r.stderr[-300:])
import inspect  # noqa: E402
if mcp_sunucu is not None:
    kontrol("CLI ve MCP varsayılan kaydırma adımı eşit",
            inspect.signature(mcp_sunucu.scroll).parameters["amount"].default == cli.KAYDIR_ADIM == 3)
r = subprocess.run([sys.executable, "-m", "deskhand", "desktop", "list", "--desktop-name", "qq", "--json"],
                   capture_output=True, text=True, timeout=60)
kontrol("desktop list --desktop-name kabul (çıkış 0)", r.returncode == 0, r.stderr[-300:])
r = subprocess.run([sys.executable, "-m", "deskhand", "desktop", "yanlis"], capture_output=True, text=True, timeout=60)
kontrol("desktop kullanım hatası → çıkış 1 (argparse 2 değil)", r.returncode == 1, f"{r.returncode} {r.stderr[-200:]}")

tuzak = os.path.join(kok, "tuzak")
_yalitim.tuzak_araclari_kur(tuzak)
r = subprocess.run([sys.executable, "-m", "deskhand", "--desktop-name", "yokad", "windows"], capture_output=True,
                   text=True, timeout=60)
kontrol("--desktop-name (--background'sız) arka plana gider: kapalı adlı masaüstü iletisi, gerçek pencere listesi YOK",
        r.returncode == 14 and "'yokad' adlı görünmez masaüstü açık değil" in r.stderr and not r.stdout.strip(),
        f"{r.returncode} {r.stdout[-200:]} {r.stderr[-300:]}")
r = subprocess.run([sys.executable, "-m", "deskhand", "windows"], capture_output=True, text=True, timeout=60,
                   env={**os.environ, "DESKHAND_GERCEK_EKRAN": "kapali"})
kontrol("GERCEK_EKRAN=kapali: gerçek oturumun pencere listesi reddedilir (17)", r.returncode == 17 and
        not r.stdout.strip(), f"{r.returncode} {r.stdout[-200:]} {r.stderr[-200:]}")
kontrol("tuzak araçlar çağrılmadı", _yalitim.tuzak_cagrilari() == [], str(_yalitim.tuzak_cagrilari()))

ao._EV_ZORLA = None
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
