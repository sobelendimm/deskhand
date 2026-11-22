"""Yalıtık KWin oturumu testleri (deskhand/kwin_oturum.py + yardimci/deskhand-eis): kullanıcının GERÇEK oturumuna HİÇBİR
girdi gitmez (kwin_wayland --virtual, özel D-Bus, özel Wayland soketi; deskhand-eis yalnız özel veri yoluna bağlanır).

Bölümler: 1) güvenlik kapıları (süreç başlatmadan) 2) oturum açılışı + yalıtım denetimi + GPU 3) Wayland Qt penceresi:
tık, ASCII/Türkçe yazı, tuş, tekerlek 4) bırakma güvenceleri (EOF, SIGTERM, SIGKILL) 5) ekran görüntüsü + OCR + pencere
listesi 6) XWayland 7) pano + erişilebilirlik (araştırma) 8) kapanış, kalıntı yok 9) kullanıcının gerçek oturumu değişmedi.
KWin < 6.8 ya da yardımcılar derlenmemişse takım "atlandı" der ve 0 ile çıkar.

Çalıştır:  python3 tests/test_kwin_oturum.py        (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import atexit
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import hata, kwin_oturum as ko, masaustu
from deskhand.hata import Dur

KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
PENCERE = os.path.join(KOK, "tests", "yardimci", "kwin_test_pencere.py")
gecen = toplam = 0
olcum = {}
GONDERILEN = []


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod
    return None


def bekle(kosul, sure=8.0, aralik=0.03):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


# ---------------------------------------------------------------- 0) atlama koşulu + gerçek oturumun görüntüsü

ok, neden = ko.kullanilabilir()
if not ok:
    print(f"ATLANDI: KWin oturumu testleri çalışamaz ({neden})")
    sys.exit(0)

GERCEK_DOSYALAR = ["~/.config/kwinrc", "~/.config/kwinoutputconfig.json", "~/.config/kglobalshortcutsrc",
                   "~/.config/kxkbrc"]


def sha1(yol):
    yol = os.path.expanduser(yol)
    try:
        with open(yol, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None  # yok


def gercek_fare():
    """Kullanıcının gerçek faresi (kdotool SALT OKUMA; gerçek oturumda)."""
    if not shutil.which("kdotool"):
        return None
    f = subprocess.run(["kdotool", "getmouselocation"], capture_output=True, text=True).stdout
    m = re.search(r"x:(-?\d+)\s+y:(-?\d+)", f)
    return (int(m.group(1)), int(m.group(2))) if m else None


def x_soketleri():
    try:
        return set(os.listdir("/tmp/.X11-unix"))
    except OSError:
        return set()


def kwin_pidleri():
    """KULLANICININ kwin_wayland'i (komut satırında kendi Wayland soketi): eşzamanlı başka test oturumları sayılmaz."""
    r = subprocess.run(["pgrep", "-x", "kwin_wayland"], capture_output=True, text=True).stdout.split()
    gw = os.environ.get("WAYLAND_DISPLAY", "")
    return set(int(p) for p in r if gw and gw in masaustu._komut_satiri(p)[1:])


sha0 = {y: sha1(y) for y in GERCEK_DOSYALAR}
fare0 = gercek_fare()
x0 = x_soketleri()
kwin0 = kwin_pidleri()
gercek_pano0 = None
if shutil.which("wl-paste"):
    r = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=5)
    gercek_pano0 = hashlib.sha1(r.stdout).hexdigest()

# ---------------------------------------------------------------- 1) güvenlik kapıları (süreç YOK)
print("1) güvenlik kapıları")
g = ko._gercek_degerler()
gercek_bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={g['runtime']}/bus"
ozel_ok = dict(bus_adres=f"unix:path={GECICI}/runtime/kwin-x/bus", soket_adi="deskhand-test",
               config_dizini=f"{GECICI}/runtime/kwin-x/ev/config")
kontrol("kapı: geçerli özel değerler geçer", dur_kodu(ko.guvenlik_kapilari, **ozel_ok) is None)
kontrol("kapı: gerçek oturum veri yolu adresi (ortamdaki) → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "bus_adres": gercek_bus}) == 14)
kontrol("kapı: $XDG_RUNTIME_DIR/bus → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "bus_adres": f"unix:path={g['runtime']}/bus"}) == 14)
kontrol("kapı: gerçek adres ,guid= ekiyle de → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "bus_adres": f"unix:path={g['runtime']}/bus,guid=abc"}) == 14)
kontrol("kapı: gerçek yola sembolik bağ → Dur 14", (lambda: (
    os.symlink(f"{g['runtime']}/bus", f"{GECICI}/bus-bag"),
    dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "bus_adres": f"unix:path={GECICI}/bus-bag"}) == 14)[1])())
kontrol("kapı: unix:path= dışı adres → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "bus_adres": "unix:abstract=/tmp/dbus-x"}) == 14)
gw = os.environ.get("WAYLAND_DISPLAY") or "wayland-0"
kontrol("kapı: kullanıcının Wayland soket adı → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "soket_adi": gw}) == 14, gw)
kontrol("kapı: wayland-0 → Dur 14", dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "soket_adi": "wayland-0"}) == 14)
kontrol("kapı: gerçek runtime'da var olan soket adı → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "soket_adi": "bus"}) == 14)
kontrol("kapı: yol ayracı içeren soket adı → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "soket_adi": "../wayland-1"}) == 14)
kontrol("kapı: gerçek ~/.config → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "config_dizini": os.path.expanduser("~/.config")}) == 14)
kontrol("kapı: ~/.config altı → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "config_dizini": os.path.expanduser("~/.config/deskhand-x")}) == 14)
kontrol("kapı: ~/.config'i kapsayan üst dizin (~) → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **{**ozel_ok, "config_dizini": os.path.expanduser("~")}) == 14)
kontrol("kapı: gerçek HOME → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **ozel_ok, home=os.path.expanduser("~")) == 14)
kontrol("kapı: gerçek XDG_RUNTIME_DIR çalışma dizini → Dur 14",
        dur_kodu(ko.guvenlik_kapilari, **ozel_ok, calisma=g["runtime"]) == 14)
kontrol("kapı: kullanıcının DISPLAY'i → Dur 14",
        not g["display"] or dur_kodu(ko.guvenlik_kapilari, **ozel_ok, xekran=g["display"]) == 14)
kontrol("kapı: biçimsiz XWayland ekranı → Dur 14", dur_kodu(ko.guvenlik_kapilari, **ozel_ok, xekran="") == 14)

# deskhand-eis: gerçek veri yolunu reddeder, --bus'sız çıkar (süreç hiçbir veri yoluna bağlanmaz)
eis = ko.yollar.eis_bin()
r = subprocess.run([eis], capture_output=True, text=True, timeout=10,
                   env={"PATH": "/usr/bin", "DBUS_SESSION_BUS_ADDRESS": gercek_bus})
kontrol("deskhand-eis: --bus yok → çıkış 2 (ortamdaki adresi DEVRALMAZ)", r.returncode == 2, f"{r.returncode} {r.stdout!r}")
r = subprocess.run([eis, "--bus", f"unix:path=/run/user/{os.getuid()}/bus"], capture_output=True, text=True, timeout=10,
                   env={"PATH": "/usr/bin"})
kontrol("deskhand-eis: gerçek oturum veri yolu → çıkış 2, bağlanmadan", r.returncode == 2 and "bus-yasak" in r.stdout,
        f"{r.returncode} {r.stdout!r}")
r = subprocess.run([eis, "--bus", "unix:abstract=x"], capture_output=True, text=True, timeout=10, env={"PATH": "/usr/bin"})
kontrol("deskhand-eis: unix:path= dışı adres → çıkış 2", r.returncode == 2)

# uygulama ortamı: kullanıcının değerleri sızmaz (sahte oturum bilgisiyle; süreç yok)
sahte = {"kimlik": "ab12", "calisma": f"{GECICI}/runtime/kwin-ab12", "dbus_adres": f"unix:path={GECICI}/runtime/kwin-ab12/bus",
         "wayland_yol": f"{GECICI}/runtime/kwin-ab12/deskhand-ab12", "xwayland": None, "xauth": None,
         "ses": {"sink": "deskhand-sessiz-kwin-ab12"}}
os.environ["DISPLAY"] = os.environ.get("DISPLAY") or ":0"  # gerçek değer varmış gibi (testte garanti)
e = ko.uygulama_ortami(sahte)
kontrol("ortam: XWayland yokken DISPLAY/XAUTHORITY YOK (kullanıcınınki sızmaz)", "DISPLAY" not in e and "XAUTHORITY" not in e)
kontrol("ortam: WAYLAND_DISPLAY = oturumun MUTLAK soket yolu", e["WAYLAND_DISPLAY"] == sahte["wayland_yol"])
kontrol("ortam: özel D-Bus adresi", e["DBUS_SESSION_BUS_ADDRESS"] == sahte["dbus_adres"])
kontrol("ortam: Wayland araç takımı değişkenleri", e["QT_QPA_PLATFORM"] == "wayland" and e["GDK_BACKEND"] == "wayland"
        and e["MOZ_ENABLE_WAYLAND"] == "1")
kontrol("ortam: ses sunucusu YOK (PULSE_SINK yok, PULSE_SERVER var olmayan sokete)", "PULSE_SINK" not in e and
        e.get("PULSE_SERVER") == f"unix:{sahte['calisma']}/ses-yok")
e2 = ko.uygulama_ortami({**sahte, "xwayland": ":123", "xauth": "/x/Xauthority"},
                        {"QT_QPA_PLATFORM": "xcb", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0",
                         "DBUS_SESSION_BUS_ADDRESS": gercek_bus})
kontrol("ortam: env yalnız araç takımı ipucunu değiştirir (QT_QPA_PLATFORM)", e2["QT_QPA_PLATFORM"] == "xcb")
e3 = ko.uygulama_ortami({**sahte, "xwayland": ":123", "xauth": "/x/Xauthority"}, ko.gecko_ipuclari(["/usr/bin/firefox", "-P"]))
kontrol("ortam: Gecko (firefox) XWayland'den (GDK_BACKEND=x11, MOZ_ENABLE_WAYLAND=0), DISPLAY oturumun, Wayland soketi de var",
        e3["GDK_BACKEND"] == "x11" and e3["MOZ_ENABLE_WAYLAND"] == "0" and e3["DISPLAY"] == ":123"
        and e3["WAYLAND_DISPLAY"] == sahte["wayland_yol"] and e3["QT_QPA_PLATFORM"] == "wayland")
kontrol("ortam: Gecko ipuçları yalnız Gecko programlarına (başkası yerel Wayland kalır; env ezer)",
        ko.gecko_ipuclari(["konsole"]) == {} and ko.gecko_ipuclari([]) == {} and ko.gecko_ipuclari(["firefox"])
        and {**ko.gecko_ipuclari(["firefox"]), "MOZ_ENABLE_WAYLAND": "1"}["MOZ_ENABLE_WAYLAND"] == "1")
import tempfile as _tf  # noqa: E402
with _tf.TemporaryDirectory() as _td:
    _ff = os.path.join(_td, "ff.desktop")
    _kw = os.path.join(_td, "kw.desktop")
    with open(_ff, "w") as _f:
        _f.write("[Desktop Entry]\nType=Application\nName=Firefox\nExec=/usr/lib/firefox/firefox %u\n")
    with open(_kw, "w") as _f:
        _f.write("[Desktop Entry]\nType=Application\nName=KWrite\nExec=kwrite %U\n")
    kontrol("gecko ipucu MCP open_app yolunda da: `gio launch firefox.desktop` (Exec) ve `env V=1 firefox` tanınır; "
            "kwrite girdisi tanınmaz",
            ko.gecko_ipuclari(["gio", "launch", _ff, "http://x"]) == dict(ko.GECKO_IPUCLARI) and
            ko.gecko_ipuclari(["env", "A=1", "firefox"]) == dict(ko.GECKO_IPUCLARI) and
            ko.gecko_ipuclari(["gio", "launch", _kw]) == {})
_chr = ["chromium", "--force-renderer-accessibility", "file:///x.html"]
_cx, _ce = ko.chromium_x11(_chr)
kontrol("ortam: Chromium/Electron ailesi (erişilebilirlik bayraklı) XWayland'den: bayrak bayrağın arkasına, ipucu env",
        _cx == ["chromium", "--force-renderer-accessibility", "--ozone-platform=x11", "file:///x.html"]
        and _ce == {"ELECTRON_OZONE_PLATFORM_HINT": "x11"} and _chr[1:] == ["--force-renderer-accessibility", "file:///x.html"])
kontrol("ortam: Chromium X11 yönlendirmesi yalnız aileye (bayraksız komut ve açık --ozone-platform aynen)",
        ko.chromium_x11(["konsole"]) == (["konsole"], {}) and ko.chromium_x11([]) == ([], {})
        and ko.chromium_x11([*_chr, "--ozone-platform=wayland"])[1] == {}
        and ko.chromium_x11([*_chr, "--ozone-platform=wayland"])[0].count("--ozone-platform=x11") == 0)
kontrol("ortam: env ile verilen WAYLAND_DISPLAY/DISPLAY/DBUS yok sayılır",
        e2["WAYLAND_DISPLAY"] == sahte["wayland_yol"] and e2["DISPLAY"] == ":123"
        and e2["DBUS_SESSION_BUS_ADDRESS"] == sahte["dbus_adres"])
kw = ko._kwin_ortami({**sahte})
kontrol("KWin ortamı: asgari, os.environ'dan HİÇBİR ŞEY yok (DISPLAY/WAYLAND_DISPLAY/gerçek adres)",
        "DISPLAY" not in kw and "WAYLAND_DISPLAY" not in kw and kw["DBUS_SESSION_BUS_ADDRESS"] == sahte["dbus_adres"]
        and kw["HOME"].startswith(sahte["calisma"]) and kw["XDG_CONFIG_HOME"].startswith(sahte["calisma"])
        and kw["XDG_RUNTIME_DIR"] == sahte["calisma"] and set(kw) <= {
            "PATH", "HOME", "LANG", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
            "XDG_STATE_HOME", "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP",
            "ATSPI_DBUS_IMPLEMENTATION", "KWIN_RENDER_NODES"} and "KDE_SESSION_VERSION" not in kw
        and "KDE_FULL_SESSION" not in kw)

# ---------------------------------------------------------------- 2) oturum açılışı
print("\n2) oturum açılışı")
D = None
atexit.register(lambda: D is not None and ko.durdur(D))
t = time.monotonic()
D = ko.baslat((1280, 720), xwayland=True, duzen=("tr", ""))
olcum["açılış süresi (sn)"] = round(time.monotonic() - t, 2)
kontrol("oturum açıldı: KWin + dbus canlı, kafeste", ko._kwin_mi(D) and masaustu._canli(D["pid"]["dbus"])
        and D["cgroup"].endswith("/" + (D["kafes"] or "yok")), str(D["pid"]))
kontrol("oturum: durum() bu oturumu bulur", (ko.durum() or {}).get("kimlik") == D["kimlik"])
kontrol("oturum: özel veri yolu adresi gerçeğinden farklı", D["dbus_adres"] != gercek_bus and D["dbus_adres"].startswith(
    "unix:path=" + os.path.join(GECICI, "runtime")))
kontrol("oturum: çalışma dizini 0700", (os.stat(D["calisma"]).st_mode & 0o777) == 0o700)
kontrol("oturum: KWin kendi yapılandırmasını GEÇİCİ HOME'a yazdı (kwinrc/kxkbrc orada)",
        os.path.exists(os.path.join(D["calisma"], "ev", "config", "kxkbrc")))
kontrol("oturum: Wayland soketi oturum dizininde", os.path.exists(D["wayland_yol"]) and D["wayland"] != gw)
kontrol("oturum: XWayland ekranı bilindi ve soketi var", bool(D["xwayland"]) and os.path.exists(
    f"/tmp/.X11-unix/X{D['x_ana']}"), str(D["xwayland"]))
dp = D["pid"]["dbus"]
with open(f"/proc/{dp}/environ", "rb") as f:
    denv = dict(p.split(b"=", 1) for p in f.read().split(b"\0") if b"=" in p)
kontrol("dbus-daemon ortamı: kullanıcının DISPLAY/WAYLAND_DISPLAY değeri yok; veri yolu özel",
        b"DISPLAY" not in denv and b"WAYLAND_DISPLAY" not in denv
        and denv.get(b"DBUS_SESSION_BUS_ADDRESS") == D["dbus_adres"].encode()
        and denv.get(b"HOME", b"").startswith(D["calisma"].encode()))
with open(os.path.join(D["calisma"], "bus.conf")) as f:
    bc = f.read()
kontrol("dbus yapılandırması: standart servis dizini YOK, receive_sender var",
        "/usr/share/dbus-1" not in bc and 'receive_sender="*"' in bc and "<servicedir>" in bc
        and bc.count("<servicedir>") == 1 and D["calisma"] in bc)

destek = ko._busctl(D, "call", "org.kde.KWin", "/KWin", "org.kde.KWin", "supportInformation").stdout
m = re.search(r"OpenGL renderer string:\s*([^\\\n]+)", destek.replace("\\n", "\n"))
gpu = m.group(1).strip() if m else "?"
olcum["GPU oluşturucu"] = gpu
kontrol("GPU: KWin bileşikleştirmesi donanım hızlandırmalı (llvmpipe/softpipe değil)",
        bool(m) and not re.search(r"llvmpipe|softpipe|software", gpu, re.I), gpu)
with open(f"/proc/{D['pid']['kwin']}/status") as f:
    rss_k = int(re.search(r"VmRSS:\s+(\d+)", f.read()).group(1))
with open(f"/proc/{D['pid']['dbus']}/status") as f:
    rss_d = int(re.search(r"VmRSS:\s+(\d+)", f.read()).group(1))
try:
    with open(f"/sys/fs/cgroup{D['cgroup']}/memory.current") as f:
        kafes_bellek = int(f.read()) // 1024
except OSError:
    kafes_bellek = None
olcum["boş oturum RSS (KWin + dbus, MiB)"] = round((rss_k + rss_d) / 1024)
olcum["boş oturum kafes belleği (MiB, sayfa önbelleği dahil)"] = round(kafes_bellek / 1024) if kafes_bellek else "?"

# ---------------------------------------------------------------- 3) Wayland Qt penceresi + girdi
print("\n3) Wayland penceresi + girdi")
import numpy as np  # noqa: E402


def kutu_bul(im, renk, tol=6):
    a = np.asarray(im).astype(int)
    mk = (abs(a[:, :, 0] - renk[0]) <= tol) & (abs(a[:, :, 1] - renk[1]) <= tol) & (abs(a[:, :, 2] - renk[2]) <= tol)
    ys, xs = np.nonzero(mk)
    if len(xs) < 300:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def kesir(kutu, W, H):
    return ((kutu[0] + kutu[2]) / 2 + 0.5) / W, ((kutu[1] + kutu[3]) / 2 + 0.5) / H


LOG = os.path.join(_yalitim.PAYLASIM, "pencere.log")


def loglar():
    try:
        with open(LOG, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def son(onek):
    v = [l for l in loglar() if l.startswith(onek)]
    return v[-1][len(onek):] if v else None


p_wl = ko.uygulama_baslat(D, [sys.executable, PENCERE], {"LOG": LOG, "BASLIK": "Deskhand KWin Test"})
kontrol("pencere: günlükte hazir (Wayland Qt)", bekle(lambda: "hazir" in loglar(), 15), "\n".join(loglar()))
platform_satiri = next((l for l in loglar() if l.startswith("platform:")), "")
kontrol("pencere: Qt platformu wayland, WAYLAND_DISPLAY oturumun mutlak yolu",
        "platform: wayland" in platform_satiri and D["wayland_yol"] in platform_satiri, platform_satiri)
kontrol("pencere: kullanıcının DISPLAY'i değil oturumun XWayland ekranı", f"display='{D['xwayland']}'" in platform_satiri,
        platform_satiri)


def renk_kutulari():
    im = ko.goruntu(D)
    return im, kutu_bul(im, (0, 255, 255)), kutu_bul(im, (255, 0, 255)), kutu_bul(im, (255, 255, 0))


def hepsi_gorundu():
    im, a, b, c = renk_kutulari()
    return (im, a, b, c) if a and b and c else None


r_ = bekle(hepsi_gorundu, 10, 0.2)
kontrol("ekran görüntüsü: pencerenin renkli ögeleri görünüyor", bool(r_))
im, KUTU, DUGME, TEKER = r_ if r_ else (ko.goruntu(D), None, None, None)
W, H = im.size
kontrol("ekran görüntüsü: boyut oturum boyutuyla aynı", im.size == tuple(D["boyut"]), str(im.size))

t = time.monotonic()
eis = ko.Eis(D)
olcum["EIS bağlantı kurulumu (sn)"] = round(time.monotonic() - t, 3)
kontrol("deskhand-eis: hazir, ekran boyutu = oturum boyutu", eis.boyut == tuple(D["boyut"]), str(eis.boyut))
bilgi = eis.satir("bilgi")
kontrol("deskhand-eis: klavye düzeni Turkish (kxkbrc yalıtık yapılandırmadan)", "Turkish" in bilgi, bilgi)


def git(kutu):
    fx, fy = kesir(kutu, W, H)
    GONDERILEN.append((int(fx * W), int(fy * H)))
    eis.satir(f"mouseto {fx:.6f} {fy:.6f}")


# tık
git(DUGME)
eis.satir("click left")
kontrol("girdi: eflatun düğmeye sol tık → günlükte tık", bekle(lambda: "tik: Kaydet" in loglar(), 5), "\n".join(loglar()[-5:]))
# metin kutusu: tık + ASCII
git(KUTU)
eis.satir("click left")
ASCII = "Merhaba dunya 123 abc XYZ"
eis.yaz(ASCII)
kontrol("girdi: ASCII yazı", bekle(lambda: son("yazi=") == ASCII, 5), repr(son("yazi=")))
eis.gonder("key ctrl+a")
TR = "Işık İğne ıspanak iiII çöp ÜÇŞĞÖ şğıİöçü"
eis.yaz(TR)
kontrol("girdi: Türkçe harfler (ş ğ ı İ ö ç ü Ş Ğ Ö Ç Ü; I/ı/İ/i ayrımı dahil)", bekle(lambda: son("yazi=") == TR, 5),
        repr(son("yazi=")))
eis.gonder("key ctrl+a")
kontrol("girdi: ctrl+a → seçim (sonraki yazı değiştirir)", (eis.yaz("X"), bekle(lambda: son("yazi=") == "X", 5))[1],
        repr(son("yazi=")))
eis.gonder("key ctrl+a")
eis.yaz("a\tb")  # Tab karakteri tuşa gider (odak kayabilir): yalnız hata vermemeli
# kapsam: tüm yazdırılabilir ASCII
tum_ascii = "".join(chr(c) for c in range(0x20, 0x7f))
yok_ascii = eis.yazilamayanlar(tum_ascii)
olcum["tr düzeninde yazılamayan ASCII karakterler"] = repr(yok_ascii) if yok_ascii else "yok"
yazilir = "".join(c for c in tum_ascii if c not in yok_ascii)
eis.satir("mouseto %f %f" % kesir(KUTU, W, H))
eis.satir("click left")
eis.gonder("key ctrl+a")
eis.yaz(yazilir)
kontrol("girdi: yazılabilir her ASCII karakter birebir", bekle(lambda: son("yazi=") == yazilir, 8),
        f"{son('yazi=')!r} != {yazilir!r}")
# yazılamayan karakter: hiçbir şey yazılmaz
onceki = son("yazi=")
try:
    eis.satir("type ab日")
    yazilamaz = None
except ko.EisHatasi as e_:
    yazilamaz = e_
time.sleep(0.3)
kontrol("type: haritada olmayan karakter → 'hata yazilamaz 日', HİÇBİR şey yazılmaz",
        yazilamaz is not None and yazilamaz.yazilamayanlar == "日" and son("yazi=") == onceki, repr(yazilamaz))
kontrol("yazilabilir: yazılamayanları döndürür (girdi göndermez)",
        eis.yazilamayanlar("aş日€ç本") == "日本" and son("yazi=") == onceki)
kontrol("yazilabilir: Türkçe + AltGr (€ @) yazılabilir", eis.yazilamayanlar("şğıİöçüŞĞÖÇÜ€@") == "")
# tuş bas/bırak sırası


def sakin(sure=0.4, azami=5.0):
    """Pencere günlüğü `sure` boyunca değişmeyene dek bekle (önceki girdinin geç gelen olayları karışmasın)."""
    son_n, t0 = -1, time.monotonic()
    while time.monotonic() - t0 < azami:
        n = len(loglar())
        if n == son_n:
            return n
        son_n = n
        time.sleep(sure)
    return len(loglar())


n0 = sakin()
eis.gonder("keydown leftshift", "keydown a", "keyup a", "keyup leftshift")
yeni = bekle(lambda: len([l for l in loglar()[n0:] if l.startswith("tus_")]) >= 4, 5)
tuslar = [l.split()[0] for l in loglar()[n0:] if l.startswith("tus_")]
kontrol("girdi: keydown/keyup sırası (shift bas, a bas, a bırak, shift bırak)",
        tuslar == ["tus_bas", "tus_bas", "tus_birak", "tus_birak"], str([l for l in loglar()[n0:] if l.startswith("tus_")]))
# fare düğmesi bas/bırak + tekerlek (sarı alan)
git(TEKER)
n0 = sakin()
eis.gonder("buttondown left", "buttonup left")
kontrol("girdi: buttondown/buttonup → fare_bas + fare_birak",
        bekle(lambda: son("fare_birak sol") is not None, 5))
n0 = sakin()
eis.satir("wheel 3")
bekle(lambda: sum(int(l.split()[1]) for l in loglar()[n0:] if l.startswith("tekerlek")) >= 360, 5)
yukari = sum(int(l.split()[1]) for l in loglar()[n0:] if l.startswith("tekerlek"))
n0 = len(loglar())
eis.satir("wheel -2")
bekle(lambda: sum(int(l.split()[1]) for l in loglar()[n0:] if l.startswith("tekerlek")) <= -240, 5)
asagi = sum(int(l.split()[1]) for l in loglar()[n0:] if l.startswith("tekerlek"))
kontrol("girdi: wheel 3 = 3 çentik YUKARI (Qt angleDelta +360), wheel -2 = aşağı (-240)", yukari == 360 and asagi == -240,
        f"{yukari} {asagi}")
n0 = len(loglar())
eis.satir("hwheel 2")
bekle(lambda: any(l.startswith("tekerlek") for l in loglar()[n0:]), 5)
yatay = sum(int(l.split()[2]) for l in loglar()[n0:] if l.startswith("tekerlek"))
olcum["hwheel 2 → Qt angleDelta.x"] = yatay
kontrol("girdi: hwheel gelir (yönü ölçüme bak)", yatay != 0, str(yatay))
kontrol("girdi: bilinmeyen komut → hata, süreç yaşıyor", dur_kodu(eis.satir, "bilinmez 1") is not None
        and eis.satir("bilgi").startswith(f"{W} {H}"))
try:
    eis.satir("key olmayantus")
    h_ = None
except ko.EisHatasi as e_:
    h_ = e_.neden
kontrol("girdi: bilinmeyen tuş adı → hata (hiçbir şey basılmaz)", bool(h_) and h_.startswith("bilinmeyen-tus"), str(h_))
kontrol("girdi: mouseto aralık dışı değerler [0,1]'e kırpılır (hata değil)", eis.satir("mouseto 5 -3") == "")

# ---- ölçümler: kalıcı bağlantıyla tık ve 20 karakter
git(KUTU)
eis.satir("click left")
eis.gonder("key ctrl+a")
sureler = []
for _i in range(10):
    t = time.monotonic()
    eis.satir("mouseto 0.5 0.5")
    eis.satir("click left")
    sureler.append(time.monotonic() - t)
olcum["kalıcı EIS: mouseto + tık (ms, ort/10)"] = round(1000 * sum(sureler) / len(sureler), 1)
git(KUTU)
eis.satir("click left")
eis.gonder("key ctrl+a")
t = time.monotonic()
eis.yaz("abcdefghijklmnopqrst")
olcum["kalıcı EIS: 20 karakter yazı (ms, varsayılan typedelay 2/typehold 8)"] = round(1000 * (time.monotonic() - t))
eis.satir("typedelay 0")
eis.satir("typehold 1")
eis.gonder("key ctrl+a")
t = time.monotonic()
eis.yaz("abcdefghijklmnopqrst")
olcum["kalıcı EIS: 20 karakter yazı (ms, typedelay 0/typehold 1)"] = round(1000 * (time.monotonic() - t))
eis.satir("typedelay 2")
eis.satir("typehold 8")
kontrol("ölçüm yazısı pencereye ulaştı", bekle(lambda: son("yazi=") == "abcdefghijklmnopqrst", 5), repr(son("yazi=")))
sureler = []
for _i in range(10):
    t = time.monotonic()
    ko.goruntu(D)
    sureler.append(time.monotonic() - t)
olcum["ekran görüntüsü (ms, ort/10, deskhand-goruntu süreç açılışı dahil)"] = round(1000 * sum(sureler) / len(sureler), 1)

# ---------------------------------------------------------------- 4) bırakma güvenceleri
print("\n4) bırakma güvenceleri")


def tutulu_dene(kapatma, ad, bekleneni_cikar=True):
    """Yeni deskhand-eis: 'a' tuşu + sol düğme basılı → kapatma(e) → pencere günlüğünde bırakıldı mı?"""
    e_ = ko.Eis(D)
    git_ = lambda kb: e_.satir("mouseto %f %f" % kesir(kb, W, H))  # noqa: E731
    git_(TEKER)
    n = sakin()
    e_.gonder("keydown a", "buttondown left")
    bekle(lambda: any(l.startswith("tus_bas") for l in loglar()[n:]) and any(l.startswith("fare_bas") for l in loglar()[n:]), 5)
    kapatma(e_)
    bekle(lambda: any(l.startswith("tus_birak") for l in loglar()[n:]) and any(l.startswith("fare_birak") for l in loglar()[n:]), 3)
    sonra = loglar()[n:]
    tus_b = any(l.startswith("tus_birak") for l in sonra)
    fare_b = any(l.startswith("fare_birak") for l in sonra)
    if kapatma is not sigkill:
        e_.kapat()
        return tus_b, fare_b
    # SIGKILL: KWin 6.8.3 basılı fare düğmesini bırakmaz → Eis.kapat() (çökmüş yardımcı + izlenen basılı düğme) kurtarır
    e_.kapat()
    bekle(lambda: any(l.startswith("fare_birak") for l in loglar()[n:]), 3)
    fare_k = any(l.startswith("fare_birak") for l in loglar()[n:])
    return tus_b, fare_b, fare_k


def eof(e_):
    e_.p.stdin.close()
    e_.p.wait(5)


def sigterm(e_):
    os.kill(e_.pid, signal.SIGTERM)
    e_.p.wait(5)


def sigkill(e_):
    os.kill(e_.pid, signal.SIGKILL)
    e_.p.wait(5)


r = tutulu_dene(eof, "EOF")
kontrol("bırakma: stdin EOF → basılı tuş + fare düğmesi bırakıldı", r == (True, True), str(r))
r = tutulu_dene(sigterm, "SIGTERM")
kontrol("bırakma: SIGTERM → basılı tuş + fare düğmesi bırakıldı", r == (True, True), str(r))
r_kill = tutulu_dene(sigkill, "SIGKILL")
olcum["SIGKILL: KWin 6.8.3 EIS kopunca bıraktı mı (tuş, fare düğmesi) + Eis.kapat() kurtarmasıyla düğme"] = str(r_kill)
kontrol("bırakma: SIGKILL (yardımcı çöker) → basılı tuşu KWin bırakır; basılı fare düğmesini Eis.kapat() kurtarır",
        r_kill[0] and r_kill[2], str(r_kill))
# kapatma yolu: Eis.kapat() basılı tutarken
e_ = ko.Eis(D)
e_.satir("mouseto %f %f" % kesir(TEKER, W, H))
n = len(loglar())
e_.satir("keydown b")
bekle(lambda: any(l.startswith("tus_bas") for l in loglar()[n:]), 5)
e_.kapat()
kontrol("bırakma: Eis.kapat() (basılı tutarken) → bırakıldı", bekle(lambda: any(
    l.startswith("tus_birak") for l in loglar()[n:]), 3))
e_ = ko.Eis(D)
e_.satir("keydown c")
e_.satir("birak")
kontrol("bırakma: `birak` komutu hepsini hemen bırakır", bekle(lambda: loglar()[-1].startswith("tus_birak"), 3), loglar()[-1])
e_.kapat()

# ---------------------------------------------------------------- 5) görüntü, OCR, pencere listesi
print("\n5) görüntü / OCR / pencere listesi")
eis.kapat()
im = ko.goruntu(D)
kontrol("görüntü: tüm ekran, doğru boyut, boş değil", im.size == tuple(D["boyut"]) and len(set(im.resize((64, 36)).getdata())) > 3)
bolge = ko.goruntu(D, (0, 0, 200, 100))
kontrol("görüntü: bölge (CaptureArea) boyutu", bolge.size == (200, 100), str(bolge.size))
yol_png = os.path.join(GECICI, "ekran.png")
im.save(yol_png)
ocr = subprocess.run(["tesseract", yol_png, "stdout", "--psm", "11"], capture_output=True, text=True).stdout
kontrol("görüntü: OCR pencere başlık yazısını okur (DESKHAND KWINTEST)", "KWINTEST" in ocr.replace(" ", "").upper()
        or "DESKHAND" in ocr.upper(), ocr[:200])
pen = ko.pencereler(D)
wl = [p for p in pen if p[1] == "Deskhand KWin Test"]
kontrol("kdotool: pencere listesinde Wayland test penceresi (başlık + geometri)", len(wl) == 1 and wl[0][2][2] >= 700,
        str(pen))

# ---------------------------------------------------------------- 6) XWayland
print("\n6) XWayland")
LOG_X = os.path.join(_yalitim.PAYLASIM, "x.log")
p_x = ko.uygulama_baslat(D, [sys.executable, PENCERE], {"LOG": LOG_X, "BASLIK": "Deskhand XWayland Test",
                                                        "QT_QPA_PLATFORM": "xcb"})


def log_x():
    try:
        with open(LOG_X, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


kontrol("XWayland: xcb Qt penceresi açıldı", bekle(lambda: "hazir" in log_x(), 20), log_x()[-300:])
kontrol("XWayland: pencere xcb platformunda, DISPLAY oturumun XWayland ekranı", "platform: xcb" in log_x()
        and f"display='{D['xwayland']}'" in log_x(), log_x()[:200])
pen = bekle(lambda: [p for p in ko.pencereler(D) if p[1] == "Deskhand XWayland Test"], 10)
kontrol("XWayland: X11 penceresi kdotool pencere listesinde", bool(pen), str(ko.pencereler(D)))
ob = bekle(lambda: kutu_bul(ko.goruntu(D), (255, 0, 255)) is not None, 5)
kontrol("XWayland: X11 penceresi ekran görüntüsünde (eflatun düğme)", bool(ob))
try:
    from Xlib import display as xdisplay
    os.environ["XAUTHORITY"] = D["xauth"]
    xd = xdisplay.Display(D["xwayland"])
    adlar = []
    for w_ in xd.screen().root.query_tree().children:
        try:
            adlar.append(w_.get_wm_name() or "")
        except Exception:  # noqa: BLE001
            pass
    kontrol("XWayland: python-xlib oturumun Xauthority'siyle bağlanır, X11 penceresi ağaçta",
            "Deskhand XWayland Test" in adlar, str(adlar))
    xd.close()
except Exception as x_:  # noqa: BLE001
    kontrol("XWayland: python-xlib bağlantısı", False, str(x_))
finally:
    os.environ.pop("XAUTHORITY", None)

# ---------------------------------------------------------------- 7) pano + erişilebilirlik (araştırma)
print("\n7) pano + erişilebilirlik")
if shutil.which("wl-copy"):
    wenv = {"PATH": "/usr/bin", "WAYLAND_DISPLAY": D["wayland_yol"], "XDG_RUNTIME_DIR": D["calisma"]}
    # gerçek pano ölçümü işlemin HEMEN öncesinde: kullanıcı test sürerken kendi bir şey kopyalarsa yanlış alarm olmasın
    r0 = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=5)
    gercek_pano0 = hashlib.sha1(r0.stdout).hexdigest()
    kopya = subprocess.run(["wl-copy", "kwin-pano-denemesi-ş"], env=wenv, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)  # arka planda sahip kalır
    oku_ = subprocess.run(["wl-paste", "-n"], env=wenv, capture_output=True, text=True, timeout=10)
    olcum["wl-copy/wl-paste oturum soketiyle"] = f"copy rc={kopya.returncode} paste rc={oku_.returncode} {oku_.stdout!r} {oku_.stderr.strip()[:80]!r}"
    kontrol("pano: wl-copy/wl-paste oturumun soketiyle çalışır (yalıtık pano)", oku_.stdout == "kwin-pano-denemesi-ş",
            olcum["wl-copy/wl-paste oturum soketiyle"])
    r = subprocess.run(["wl-paste", "-n"], capture_output=True, timeout=5)
    kontrol("pano: kullanıcının GERÇEK panosu değişmedi", hashlib.sha1(r.stdout).hexdigest() == gercek_pano0)
adres = ko.atspi_baslat(D)
olcum["AT-SPI adresi (özel veri yolunda org.a11y.Bus)"] = adres or "yok"
kontrol("erişilebilirlik: org.a11y.Bus özel veri yolunda etkinleşti, adres oturum dizininde",
        bool(adres) and D["calisma"] in adres, str(adres))
if adres:
    LOG_A = os.path.join(_yalitim.PAYLASIM, "a.log")
    p_a = ko.uygulama_baslat(D, [sys.executable, PENCERE], {"LOG": LOG_A, "BASLIK": "Deskhand AT-SPI Test"})
    bekle(lambda: os.path.exists(LOG_A) and "hazir" in open(LOG_A).read(), 15)
    betik = ("import gi\ngi.require_version('Atspi','2.0')\nfrom gi.repository import Atspi\n"
             "m=Atspi.get_desktop(0)\n"
             "for i in range(m.get_child_count()):\n"
             "  a=m.get_child_at_index(i)\n"
             "  if a is None: continue\n"
             "  for j in range(a.get_child_count()):\n"
             "    f=a.get_child_at_index(j)\n"
             "    if f is not None: print('PENCERE', f.get_name())\n")
    aenv = {"PATH": "/usr/bin", "HOME": os.path.join(D["calisma"], "ev"), "XDG_RUNTIME_DIR": D["calisma"],
            "DBUS_SESSION_BUS_ADDRESS": D["dbus_adres"]}
    ag = bekle(lambda: "Deskhand AT-SPI Test" in subprocess.run(
        [sys.executable, "-c", betik], env=aenv, capture_output=True, text=True, timeout=20).stdout, 10, 0.5)
    r = subprocess.run([sys.executable, "-c", betik], env=aenv, capture_output=True, text=True, timeout=20)
    olcum["AT-SPI ağacında Qt test penceresi (özel veri yolu)"] = "VAR" if ag else f"YOK ({r.stdout.strip()!r} {r.stderr.strip()[-120:]!r})"
    kontrol("erişilebilirlik: Qt test penceresi oturumun KENDİ AT-SPI ağacında", bool(ag), r.stdout + r.stderr[-200:])

# ---------------------------------------------------------------- 8) kapanış + kalıntı
print("\n8) kapanış")
kimlik, calisma, xana = D["kimlik"], D["calisma"], D["x_ana"]
bizim_x = {f"X{n}" for n in (xana, xana + 1)} | ({"X" + D["xwayland"].lstrip(":").split(".")[0]} if D.get("xwayland") else set())
pidler = dict(D["pid"])
uyg = [p_wl.pid, p_x.pid]
ko.durdur(D)
D = None
kontrol("durdur: KWin / dbus / ses bekçisi süreçleri yok", not any(masaustu._canli(p) for p in pidler.values()), str(pidler))
kontrol("durdur: test uygulamaları da kapandı (kafes)", not any(masaustu._canli(p) for p in uyg))
kontrol("durdur: çalışma dizini silindi", not os.path.exists(calisma))
kontrol("durdur: durum() boş", ko.durum() is None)
kontrol("durdur: X soketleri ve kilitleri kalmadı", not any(os.path.exists(y) for y in (
    f"/tmp/.X11-unix/X{xana}", f"/tmp/.X11-unix/X{xana + 1}", f"/tmp/.X{xana}-lock", f"/tmp/.X{xana + 1}-lock")))
# Eşzamanlı BAŞKA KWin oturumlarının (X124…) soketleri sayılmaz: yalnız bu oturumun ekran numaraları sınanır.
kalan = bizim_x & x_soketleri()
kontrol("/tmp/.X11-unix: bu oturumun X soketleri silindi (başkalarının soketlerine bakılmaz)", not kalan, str(kalan))
kontrol("durdur: deskhand-sessiz ses çıkışı yok (hiç kurulmadı)",
        masaustu._sink_modulu("deskhand-sessiz-kwin-" + kimlik) is None)
if shutil.which("systemd-run"):
    kontrol("durdur: bellek kafesi (scope) kalmadı", subprocess.run(
        ["systemctl", "--user", "is-active", pidler and f"deskhand-kwin-{kimlik}-{os.getpid()}.scope"],
        capture_output=True, text=True).stdout.strip() != "active")

# yarım kalmış oturum kalıntısı temizlenir
sahte_cdir = ko._oturum_dizini("dead0001")
os.makedirs(sahte_cdir, mode=0o700)
ko._durum_yaz({"kimlik": "dead0001", "calisma": sahte_cdir, "pid": {"kwin": 2 ** 22 - 3, "dbus": 2 ** 22 - 4},
               "wayland": "deskhand-dead0001", "wayland_yol": sahte_cdir + "/x", "x_ana": None,
               "kafes": None, "cgroup": "", "ses": None, "baslangic": time.time() - 999, "baslatan_pid": 2 ** 22 - 5})
kontrol("kalıntı: ölü pid'li yarım oturum temizlenir", "dead0001" in ko.temizle_kalintilar() and not os.path.exists(sahte_cdir))

# ---------------------------------------------------------------- 9) gerçek oturum değişmedi
print("\n9) kullanıcının gerçek oturumu")
fare1 = gercek_fare()
if fare0 is not None:
    sizdi = fare1 is not None and any(abs(fare1[0] - a) <= 2 and abs(fare1[1] - b) <= 2 for a, b in GONDERILEN)
    if fare0 != fare1:
        print(f"NOT: gerçek fare {fare0} → {fare1} (kullanıcı oynattı olabilir)")
    kontrol("GERÇEK oturum: fare konumu aynı (ya da kullanıcı oynattı: bizim noktamız değil)",
            fare0 == fare1 or not sizdi, f"{fare0} → {fare1}")
for y in GERCEK_DOSYALAR:
    kontrol(f"gerçek yapılandırma değişmedi (sha1): {y}", sha1(y) == sha0[y])
kontrol("gerçek kwin_wayland süreçleri aynı (yalnız kullanıcının KWin'i)", kwin_pidleri() == kwin0,
        f"{kwin0} → {kwin_pidleri()}")

print("\nölçümler:")
for a_, v_ in olcum.items():
    print(f"  {a_}: {v_}")
print(f"\n{gecen}/{toplam} KWin oturumu testi geçti")
sys.exit(0 if gecen == toplam else 1)
