"""KWin arka ucu testleri (deskhand/arka_uc/kwin.py + masaustu.py KWin türü): arka plan masaüstü yalıtık KWin oturumuyla
açılır; kullanıcının GERÇEK oturumuna HİÇBİR girdi gitmez (kwin_wayland --virtual, özel D-Bus, özel Wayland soketi).

Bölümler: 1) tür seçimi + Xvfb'ye düşme koşulu (süreçsiz + gerçek düşme) 2) GPU seçimi (sahte aygıt listeleri)
3) bağlantı kapısı (oynanmış durum kayıtları → Dur 14) 4) yaşam döngüsü + yalıtım (ortam sızıntısı, D-Bus sertleştirme,
erişilebilirlik veri yolu, GSettings, ölçek, GPU) 5) ArkaUc sözleşmesi (pencere, görüntü, girdi, pencere yönetimi,
klavye) 6) Türkçe yazı + pano yedeği (yapıştırma yolu) 7) DUR / Devral 8) EIS kopması kurtarması 9) işaretçi: park
edilmiş imleç + iki pencere arası hızlı tık 10) kapanış + kalıntı (çökme sonrası) 11) gerçek oturum değişmedi.
KWin < 6.8 ya da yardımcılar derlenmemişse "atlandı" der ve 0 ile çıkar.

Çalıştır:  python3 tests/test_arka_kwin.py        (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import atexit
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ["DESKHAND_ARKA_TUR"] = "kwin"
from deskhand import api, arka_uc, hata, kwin_oturum as ko, masaustu  # noqa: E402
from deskhand.arka_uc import ARKA_ONEK, EKRAN, sec  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
PENCERE = os.path.join(KOK, "tests", "yardimci", "kwin_test_pencere.py")
PANO_PENCERE = os.path.join(KOK, "tests", "yardimci", "pano_pencere.py")
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


ok, neden = ko.kullanilabilir()
if not ok:
    print(f"ATLANDI: KWin arka ucu testleri çalışamaz ({neden})")
    sys.exit(0)


def ata_pidler(pid):
    """pid ve ataları (uygulama bwrap ad alanında: başlatılan PID bwrap'in kendisi, pencere sahibi onun çocuğu)."""
    s_ = []
    while pid and pid > 1 and len(s_) < 16:
        s_.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return s_


def sha1(yol):
    try:
        with open(os.path.expanduser(yol), "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def gercek_fare():
    r = subprocess.run(["kdotool", "getmouselocation"], capture_output=True, text=True)
    m = re.search(r"x:(-?\d+)\s+y:(-?\d+)", r.stdout)
    return (int(m.group(1)), int(m.group(2))) if m else None


def pidler(ad):
    return subprocess.run(["pgrep", "-x", ad], capture_output=True, text=True).stdout.split()


GERCEK_DOSYALAR = ["~/.config/kwinrc", "~/.config/kwinoutputconfig.json", "~/.config/kglobalshortcutsrc",
                   "~/.config/kxkbrc", "~/.config/mozilla/firefox/profiles.ini", "~/.config/mozilla/firefox/installs.ini",
                   "~/.config/dconf/user"]
sha0 = {y: sha1(y) for y in GERCEK_DOSYALAR}
fare0 = gercek_fare()
# K3: koşu BOYUNCA gerçek imleç örneklenir (salt okuma, 0,25 sn): bizim gönderdiğimiz bir noktaya hiç gitmemeli
FARE_ORNEK = []
_ornek_dur = threading.Event()


def _fare_ornekle():
    while not _ornek_dur.is_set():
        f_ = gercek_fare()
        if f_ is not None:
            FARE_ORNEK.append(f_)
        time.sleep(0.25)


threading.Thread(target=_fare_ornekle, daemon=True).start()
BIZIM_X = []  # bu testin oturumlarının X ekran numaraları (sonda hiçbiri kalmamalı)
KWIN0 = sorted(p for p in pidler("kwin_wayland") if os.environ.get("WAYLAND_DISPLAY", "-") in
               subprocess.run(["cat", f"/proc/{p}/cmdline"], capture_output=True, text=True).stdout.replace("\0", " "))
x0 = set(os.listdir("/tmp/.X11-unix"))
gercek_bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={os.environ.get('XDG_RUNTIME_DIR')}/bus"

# ---------------------------------------------------------------- 1) tür seçimi + Xvfb'ye düşme
print("1) tür seçimi")
os.environ["DESKHAND_ARKA_TUR"] = ""
kontrol("seçim: koşullar uygun → kendiliğinden kwin", masaustu.secilen_tur()[:2] == ("kwin", False))
asil_kullanilabilir = ko.kullanilabilir
ko.kullanilabilir = lambda: (False, "test: KWin yok")
kontrol("seçim: KWin kullanılamıyorsa → xvfb (seçenek sunulmaz)", masaustu.secilen_tur() == ("xvfb", False, "test: KWin yok"))
os.environ["DESKHAND_ARKA_TUR"] = "kwin"
kontrol("seçim: kwin zorlanmış ama kullanılamıyor → Dur 9 (sessizce Xvfb'ye düşmez)", dur_kodu(masaustu.secilen_tur) == 9)
ko.kullanilabilir = asil_kullanilabilir
os.environ["DESKHAND_ARKA_TUR"] = "bilmem"
kontrol("seçim: geçersiz DESKHAND_ARKA_TUR → Dur 1", dur_kodu(masaustu.secilen_tur) == 1)
os.environ["DESKHAND_ARKA_TUR"] = "xvfb"
kontrol("seçim: xvfb zorlanabilir (tanılama)", masaustu.secilen_tur()[:2] == ("xvfb", True))
# gerçek düşme: KWin kendiliğinden seçildi ama AÇILAMADI → Xvfb, uyarıyla
os.environ["DESKHAND_ARKA_TUR"] = ""
asil_kwin_baslat = masaustu._kwin_baslat
masaustu._kwin_baslat = lambda boyut: (_ for _ in ()).throw(Dur(9, "test: KWin açılamadı"))
try:
    if shutil.which("Xvfb"):
        dx = masaustu.masaustu_baslat("800x600")
        kontrol("düşme: KWin açılamayınca Xvfb açıldı, uyarı yazıldı", masaustu.tur(dx) == "xvfb" and
                any("KWin oturumu açılamadı" in u for u in dx.get("uyarilar", [])), str(dx.get("uyarilar")))
        kontrol("düşme: sec() → Xvfb arka ucu (ad 'sanal', tur 'xvfb')", sec(arka_bayragi=True).ad == "sanal" and
                getattr(sec(arka_bayragi=True), "tur", "") == "xvfb")
        masaustu.masaustu_durdur()
    else:
        kontrol("düşme: Xvfb yok (atlandı)", True)
finally:
    masaustu._kwin_baslat = asil_kwin_baslat
os.environ["DESKHAND_ARKA_TUR"] = "kwin"

# ---------------------------------------------------------------- 2) GPU seçimi (sahte aygıtlar)
print("\n2) GPU seçimi")


def aygit(dugum, boot, bagli, tumlesik, erisim=True):
    return {"dugum": dugum, "kart": "card", "boot_vga": boot, "bagli": bagli, "tumlesik": tumlesik, "surucu": "amdgpu",
            "pci": "0000:00:00.0", "erisim": erisim}


A_OYUN, A_TUM = aygit("/dev/dri/renderD128", "1", True, False), aygit("/dev/dri/renderD129", "0", False, True)
kontrol("GPU: oyun GPU'su + tümleşik → tümleşik", (ko.render_sec([A_OYUN, A_TUM]) or {}).get("dugum") == A_TUM["dugum"])
kontrol("GPU: tek aygıt → varsayılan (None)", ko.render_sec([A_OYUN]) is None)
kontrol("GPU: 'bağlı çıkış' bilgisine güvenilmez (boot_vga=0 + tümleşik yeter)",
        (ko.render_sec([A_OYUN, {**A_TUM, "bagli": True}]) or {}).get("dugum") == A_TUM["dugum"])
kontrol("GPU: tümleşik boot_vga=1 ise seçilmez", ko.render_sec([A_OYUN, {**A_TUM, "boot_vga": "1"}]) is None)
kontrol("GPU: iki ayrık kart (tümleşik yok) → varsayılan", ko.render_sec([A_OYUN, {**A_TUM, "tumlesik": False}]) is None)
kontrol("GPU: erişilemeyen aygıt seçilmez", ko.render_sec([A_OYUN, {**A_TUM, "erisim": False}]) is None)
os.environ["DESKHAND_KWIN_GPU"] = "varsayilan"
kontrol("GPU: DESKHAND_KWIN_GPU=varsayilan → seçim yok", ko.render_sec([A_OYUN, A_TUM]) is None)
os.environ.pop("DESKHAND_KWIN_GPU")
GERCEK_GPU = ko.render_sec()
print(f"   bu makinede seçilen: {GERCEK_GPU}")

# ---------------------------------------------------------------- 3) bağlantı kapısı (süreç yok)
print("\n3) bağlantı kapısı")
RT = os.environ["DESKHAND_RUNTIME_DIR"]
ornek = {"kimlik": "ab12cd34", "calisma": f"{RT}/kwin-ab12cd34", "wayland": "deskhand-ab12cd34",
         "wayland_yol": f"{RT}/kwin-ab12cd34/deskhand-ab12cd34", "dbus_adres": f"unix:path={RT}/kwin-ab12cd34/bus",
         "xwayland": ":150"}
grt = os.environ.get("XDG_RUNTIME_DIR", "")
gw = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
os.makedirs(ornek["calisma"], mode=0o700, exist_ok=True)
BEKLENEN = {"calisma": ornek["calisma"], "wayland_yol": ornek["wayland_yol"], "dbus_adres": ornek["dbus_adres"]}
kontrol("kapı: geçerli kayıt → güvenli kayıt aynı yollar", all(ko.guvenli_kayit(ornek)[a] == v for a, v in BEKLENEN.items()))
kontrol("kapı: canlı karşı taraf yokken (soket/süreç yok) bağlantı kapısı → Dur 14", dur_kodu(ko.baglanti_denetle, ornek) == 14)
for ad_, ek_ in (("gerçek oturum veri yolu", {"dbus_adres": gercek_bus}),
                 ("veri yolu soketi oturum dizini dışında", {"dbus_adres": f"unix:path={RT}/bus"}),
                 ("kullanıcının Wayland soketi (mutlak yol)", {"wayland_yol": os.path.join(grt, gw), "wayland": gw}),
                 ("Wayland soketi oturum dizini dışında", {"wayland_yol": f"{RT}/deskhand-ab12cd34"}),
                 ("çalışma dizini = gerçek XDG_RUNTIME_DIR", {"calisma": grt}),
                 ("çalışma dizini RUNTIME_DIR dışında", {"calisma": "/tmp/kwin-ab12cd34"}),
                 ("kullanıcının DISPLAY'i XWayland diye", {"xwayland": os.environ.get("DISPLAY") or ":0"}),
                 ("eksik alan", {"wayland_yol": None})):
    k_ = {**ornek, **ek_}
    if ek_.get("wayland_yol") is None and "wayland_yol" in ek_:
        k_.pop("wayland_yol")
    try:  # oynanmış alan YOK SAYILIR: yollar kimlikten kurulur (ya da kayıt reddedilir)
        g_ = ko.guvenli_kayit(k_)
        yoksay = all(g_[a] == v for a, v in BEKLENEN.items()) and g_.get("xwayland") is None
    except Dur as e:
        yoksay = e.kod == 14
    kontrol(f"kapı: {ad_} → yok sayıldı (yollar oturum dizininden) ve bağlantı kapısı Dur 14",
            yoksay and dur_kodu(ko.baglanti_denetle, k_) == 14)
r = subprocess.run([kwin_oturum_eis := os.path.join(KOK, "deskhand", "yardimci", "deskhand-eis")], capture_output=True,
                   text=True, timeout=10, env={"PATH": os.environ["PATH"], "DBUS_SESSION_BUS_ADDRESS": gercek_bus})
kontrol("deskhand-eis: --bus yoksa ortamdaki (gerçek) adresi DEVRALMAZ → çıkış 2", r.returncode == 2)
r = subprocess.run([kwin_oturum_eis, "--bus", gercek_bus], capture_output=True, text=True, timeout=10)
kontrol("deskhand-eis: --bus gerçek adres → çıkış 2 (bus-yasak)", r.returncode == 2 and "bus-yasak" in r.stdout)

# ---------------------------------------------------------------- 4) yaşam döngüsü + yalıtım
print("\n4) yaşam döngüsü + yalıtım")
t = time.monotonic()
d = masaustu.masaustu_baslat("1600x900")
olcum["açılış (masaustu_baslat, hazır denetimleri dahil)"] = f"{time.monotonic() - t:.2f} sn"
kontrol("açılış: tür kwin, durum() tek kaynak, saglik tamam", masaustu.tur(d) == "kwin" and
        masaustu.durum() is not None and all((masaustu.durum() or {}).get("saglik", {}).values()),
        str((masaustu.durum() or {}).get("saglik")))
kontrol("açılış: ikinci başlatma (tür zorlaması değişse de) aynı masaüstü — tek arka plan masaüstü",
        (os.environ.__setitem__("DESKHAND_ARKA_TUR", "xvfb") or masaustu.masaustu_baslat().get("zaten")) is True
        and masaustu.tur(masaustu.durum()) == "kwin")
os.environ["DESKHAND_ARKA_TUR"] = "kwin"
au = sec(arka_bayragi=True)
kontrol("sec(): KWin arka ucu, ad 'sanal', tür 'kwin'", type(au).__name__ == "KwinArkaUc" and au.ad == "sanal" and
        au.tur == "kwin")
kontrol("sec(arka:{…} kimliği) → aynı arka uç", sec("arka:{00000000-0000-0000-0000-000000000000}") is au)
BIZIM_X.append(d["x_ana"])
kontrol("kafes: KWin + dbus + bildirim + kayıt defteri + öncelik bekçisi aynı bellek kafesinde",
        all(masaustu._cgroup(d["pid"][a]) == d["cgroup"] for a in ("kwin", "dbus", "bildirim", "a11y", "oncelik_bekcisi")),
        str({a: masaustu._cgroup(d["pid"].get(a)) for a in d["pid"]}))
onc = ko.oncelik_durumu(d["pid"]["kwin"])
io_ = subprocess.run(["ionice", "-p", str(d["pid"]["kwin"])], capture_output=True, text=True).stdout.strip()
def oncelik_iyi():
    o_ = ko.oncelik_durumu(d["pid"]["kwin"])
    i_ = subprocess.run(["ionice", "-p", str(d["pid"]["kwin"])], capture_output=True, text=True).stdout
    return o_ and all(n >= 10 and p not in (1, 2, 6) for _t, n, p in o_) and "idle" in i_


# ad tabanlı sistem kuralları (ananicy) exec anında yükseltebilir: öncelik bekçisi en çok ~1 sn'de düşürür
kontrol("öncelik: KWin'in TÜM iş parçacıkları nice >= 10, gerçek zamanlı yok, ionice idle (bekçi ≤ 2 sn içinde)",
        bekle(oncelik_iyi, 2, 0.1), f"{[x for x in onc if x[1] < 10 or x[2] in (1, 2, 6)][:5]} {io_}")
with open(os.path.join(d["calisma"], "oncelik-bekcisi.log"), errors="replace") as f_:
    olcum["öncelik bekçisinin düzelttikleri (açılışta)"] = len(f_.read().splitlines())
kontrol("ses: boş çıkış/ses bekçisi YOK (arka plan uygulaması ses sunucusuna erişmez)",
        d.get("ses") is None and "ses_bekcisi" not in d["pid"] and
        masaustu._sink_modulu("deskhand-sessiz-kwin-" + d["kimlik"]) is None)
kontrol("hazırlık: oturumun erişilebilirlik veri yolu, kullanıcınınkinden FARKLI ve oturum dizininde",
        d.get("a11y_adres") and d["calisma"] in d["a11y_adres"] and d["a11y_adres"] not in subprocess.run(
            ["busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress"],
            capture_output=True, text=True).stdout, d.get("a11y_adres"))
r = subprocess.run(["busctl", f"--address={d['dbus_adres']}", "get-property", "org.a11y.Bus", "/org/a11y/bus",
                    "org.a11y.Status", "IsEnabled"], capture_output=True, text=True)
kontrol("hazırlık: oturumda IsEnabled=true (uygulamalardan önce)", r.stdout.strip() == "b true", r.stdout)
r = subprocess.run(["busctl", f"--address={d['dbus_adres']}", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                    "org.freedesktop.DBus", "NameHasOwner", "s", "org.freedesktop.Notifications"],
                   capture_output=True, text=True)
kontrol("bildirim: yakalayıcı özel veri yolunda", r.stdout.strip() == "b true", r.stdout)
for uye in ("UpdateActivationEnvironment", "ReloadConfig"):
    imza = ("a{ss}", "1", "DISPLAY", ":0") if uye == "UpdateActivationEnvironment" else ()
    r = subprocess.run(["busctl", f"--address={d['dbus_adres']}", "call", "org.freedesktop.DBus",
                        "/org/freedesktop/DBus", "org.freedesktop.DBus", uye, *imza], capture_output=True, text=True)
    kontrol(f"D-Bus sertleştirme: {uye} reddedilir (AccessDenied)", r.returncode != 0 and "denied" in r.stderr.lower(),
            r.stderr)
bilgi = ko._kwin_bilgisi(d).replace("\\n", "\n")
olcum["KWin OpenGL oluşturucu"] = d.get("gpu")
kontrol("GPU: donanım hızlandırmalı (llvmpipe değil)", d.get("gpu") and not re.search("llvmpipe|softpipe", d["gpu"], re.I),
        d.get("gpu"))
if GERCEK_GPU:
    kontrol("GPU: KWin'e tümleşik GPU verildi (KWIN_RENDER_NODES)", d.get("render_dugumu") == GERCEK_GPU["dugum"],
            str(d.get("render_dugumu")))

# ortam sızıntısı: oturumda başlatılan bir sürecin GERÇEK ortamı
ENV_LOG = os.path.join(_yalitim.PAYLASIM, "env.txt")
os.environ["SSH_AUTH_SOCK"] = os.environ.get("SSH_AUTH_SOCK") or "/tmp/sahte-ssh-ajan"
os.environ["AT_SPI_BUS_ADDRESS"] = "unix:path=/run/user/0/sahte-a11y"
os.environ["LIBEI_SOCKET"] = "eis-0"
os.environ["PULSE_SERVER"] = "unix:/run/user/0/sahte-pulse"
with open(ENV_LOG, "w") as f_:
    pe = masaustu.baslat(["env", "-0"], {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0",
                                         "DBUS_SESSION_BUS_ADDRESS": gercek_bus, "BENIM": "1"}, stdout=f_, stderr=f_)
    pe.wait(10)
for a_ in ("AT_SPI_BUS_ADDRESS", "LIBEI_SOCKET", "PULSE_SERVER"):
    os.environ.pop(a_, None)
with open(ENV_LOG, "rb") as f_:
    oe = dict(x.decode(errors="replace").split("=", 1) for x in f_.read().split(b"\0") if b"=" in x)
kontrol("ortam: WAYLAND_DISPLAY oturumun MUTLAK soketi, DISPLAY oturumun XWayland'i, veri yolu özel (env ile verilen "
        "kullanıcı değerleri yok sayıldı)", oe.get("WAYLAND_DISPLAY") == d["wayland_yol"] and
        oe.get("DISPLAY") == d["xwayland"] and oe.get("DBUS_SESSION_BUS_ADDRESS") == d["dbus_adres"],
        str({a: oe.get(a) for a in ("WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}))
kontrol("ortam: SSH ajanı, kullanıcının erişilebilirlik adresi, EIS soketi, ses sunucusu GEÇMEDİ",
        not any(a in oe for a in ("SSH_AUTH_SOCK", "AT_SPI_BUS_ADDRESS", "LIBEI_SOCKET", "KDE_FULL_SESSION",
                                   "SESSION_MANAGER", "PULSE_SINK")) and
        oe.get("PULSE_SERVER") == f"unix:{d['calisma']}/ses-yok",
        str([a for a in ("SSH_AUTH_SOCK", "AT_SPI_BUS_ADDRESS", "LIBEI_SOCKET") if a in oe]) + str(oe.get("PULSE_SERVER")))
kontrol("ortam: XDG_RUNTIME_DIR masaüstünün KENDİ klasörü (kullanıcınınki değil), HOME kullanıcının",
        oe.get("XDG_RUNTIME_DIR", "").startswith(d["calisma"]) and oe.get("HOME") == os.path.expanduser("~"),
        str(oe.get("XDG_RUNTIME_DIR")))
kontrol("ortam: GSETTINGS_BACKEND=memory, ATSPI_DBUS_IMPLEMENTATION=dbus-daemon, Wayland araç takımları, ek değişken",
        oe.get("GSETTINGS_BACKEND") == "memory" and oe.get("ATSPI_DBUS_IMPLEMENTATION") == "dbus-daemon" and
        oe.get("QT_QPA_PLATFORM") == "wayland" and oe.get("MOZ_ENABLE_WAYLAND") == "1" and oe.get("BENIM") == "1")
de_ = masaustu._ortam_oku(d["pid"]["dbus"])
kontrol("dbus-daemon ortamı asgari: kullanıcının DISPLAY/WAYLAND_DISPLAY/veri yolu yok, KDE_SESSION_VERSION yok",
        de_ and not any(a in de_ for a in ("DISPLAY", "WAYLAND_DISPLAY", "KDE_SESSION_VERSION", "KDE_FULL_SESSION"))
        and de_.get("DBUS_SESSION_BUS_ADDRESS") == d["dbus_adres"], str(sorted(de_)))
if shutil.which("gsettings"):
    pg = masaustu.baslat(["gsettings", "set", "org.gnome.desktop.interface", "clock-format", "12h"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pg.wait(10)
    kontrol("GSettings: arka plan uygulamasının ayar yazısı gerçek ~/.config/dconf/user'ı DEĞİŞTİRMEDİ",
            sha1("~/.config/dconf/user") == sha0["~/.config/dconf/user"])

# ---------------------------------------------------------------- 5) ArkaUc sözleşmesi
print("\n5) ArkaUc sözleşmesi")
import numpy as np  # noqa: E402


def kutu_bul(im, renk, tol=6):
    a = np.asarray(im).astype(int)
    mk = (abs(a[:, :, 0] - renk[0]) <= tol) & (abs(a[:, :, 1] - renk[1]) <= tol) & (abs(a[:, :, 2] - renk[2]) <= tol)
    ys, xs = np.nonzero(mk)
    if len(xs) < 300:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


LOG = os.path.join(_yalitim.PAYLASIM, "a.log")
LOG2 = os.path.join(_yalitim.PAYLASIM, "b.log")


def loglar(yol=LOG):
    try:
        with open(yol, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def son(onek, yol=LOG):
    v = [l for l in loglar(yol) if l.startswith(onek)]
    return v[-1][len(onek):] if v else None


t = time.monotonic()
p1 = au.baslat([sys.executable, PENCERE], {"LOG": LOG, "BASLIK": "kwin-arka ANA"})
k = bekle(lambda: next((w for w, b, _ in au.pencereler("kwin-arka ANA")), None), 15, 0.05)
olcum["Qt penceresi açılışı (Wayland)"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
kontrol("pencere: açıldı, kimlik arka:{uuid}", k is not None and re.fullmatch(ARKA_ONEK + r"\{[0-9a-f-]{36}\}", k), str(k))
if k is None:
    sys.exit(1)
kontrol("pencere: platform wayland (oturumun soketi)", bekle(lambda: any(
    l.startswith("platform: wayland") and d["wayland_yol"] in l for l in loglar()), 5), str(loglar()[:2]))
geo = au.geometri(k)
kontrol("geometri: İSTEMCİ alanı (Xvfb türüyle aynı ölçü) = sabit 700x460", geo[2:] == (700, 460), str(geo))
kontrol("pencere_coz: ad → kimlik, kimlik → kimlik, {uuid} → arka:{uuid}, ekran → EKRAN",
        au.pencere_coz("kwin-arka ANA") == k and au.pencere_coz(k) == k and au.pencere_coz(k[len(ARKA_ONEK):]) == k
        and au.pencere_coz("ekran") == EKRAN)
kontrol("pencere_coz: yok → 8, yanlış biçim → 8", dur_kodu(au.pencere_coz, "yok-boyle") == 8 and
        dur_kodu(au.geometri, "arka:0x1234") == 8)
kontrol("baslik / sinif / pid / kimlikler", au.baslik(k) == "kwin-arka ANA" and au.sinif(k) == au.sinif(k).lower()
        and au.sinif(k) != "" and p1.pid in ata_pidler(au.pid(k)) and k in au.kimlikler(),
        f"{au.sinif(k)} {au.pid(k)} {p1.pid}")
kontrol("aktif: yeni pencere odak aldı", bekle(lambda: au.aktif() == k, 3), au.aktif())
kontrol("ekran_alani = oturum boyutu", au.ekran_alani() == (0, 0, 1600, 900), str(au.ekran_alani()))
sure = []
for _ in range(7):
    t = time.perf_counter()
    im = au.goruntu()
    sure.append((time.perf_counter() - t) * 1000)
olcum["görüntü (1600x900)"] = f"{sorted(sure)[3]:.1f} ms (medyan)"
kontrol("görüntü: RGB, oturum boyutu (ölçek 1)", im.mode == "RGB" and im.size == (1600, 900), str(im.size))
def kutular():
    """Pencerenin renkli ögeleri ekranda (pencere taşınınca yeniden bulunur)."""
    return bekle(lambda: (lambda t_: t_ if all(t_[1:]) else None)((lambda im_: (
        im_, kutu_bul(im_, (0, 255, 255)), kutu_bul(im_, (255, 0, 255)), kutu_bul(im_, (255, 255, 0))))(au.goruntu())),
        8, 0.1) or (au.goruntu(), None, None, None)


im, KUTU, DUGME, TEKER = kutular()
kontrol("görüntü: pencere ögeleri (renkli kutular) pencere geometrisi içinde", KUTU and DUGME and TEKER and
        geo[0] <= DUGME[0] and DUGME[2] <= geo[0] + geo[2] and geo[1] <= DUGME[1] and DUGME[3] <= geo[1] + geo[3],
        f"{geo} {DUGME}")
W, H = 1600, 900


def kesir(kutu):
    x, y = (kutu[0] + kutu[2]) / 2, (kutu[1] + kutu[3]) / 2
    GONDERILEN.append((int(x), int(y)))
    return f"mouseto {(x + 0.5) / W:.6f} {(y + 0.5) / H:.6f}"


g = au.girdi("test", denetle=lambda k_, desen: None)
t = time.perf_counter()
g.gonder(k, None, kesir(DUGME), "click left")
kontrol("tık: düğme → 'tik: Kaydet'", bekle(lambda: "tik: Kaydet" in loglar(), 3), str(loglar()[-3:]))
olcum["tık (gonder: mouseto + click, kalıcı EIS)"] = f"{(time.perf_counter() - t) * 1000:.1f} ms"
fx, fy, alt = au.fare()
kontrol("fare: imleç düğmede, altındaki pencere = hedef", alt == k and abs(fx - (DUGME[0] + DUGME[2]) / 2) <= 1,
        f"{fx},{fy} {alt}")
g.gonder(k, None, kesir(KUTU), "click left")
TR = "Işık İğne çöp ÜÇŞĞÖ şğıİöçü"
t = time.perf_counter()
g.gonder(k, None, f"type {TR}")
kontrol("yazı: Türkçe birebir (oturumun klavye düzeni)", bekle(lambda: son("yazi=") == TR, 3), repr(son("yazi=")))
olcum["yazı (28 karakter, typedelay 2 + typehold 8)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms"
kontrol("klavye_duzeni = kullanıcının etkin düzeni (ya da tr)", au.klavye_duzeni()[0] in ("tr", masaustu._klavye_duzeni()[0]))
kontrol("yazilabilir_mi: ş/€ evet, emoji/ж hayır (girdi göndermez)", au.yazilabilir_mi("ş") and au.yazilabilir_mi("€")
        and not au.yazilabilir_mi("😀") and not au.yazilabilir_mi("ж"))
kontrol("gecerli_tuslar: enter, leftctrl, f5, ctrl", {"enter", "leftctrl", "f5", "ctrl"} <= au.gecerli_tuslar())
g.gonder(k, None, "key ctrl+a", "key backspace")
kontrol("tuş: ctrl+a + backspace → boş", bekle(lambda: son("yazi=") == "", 3))
n0 = len(loglar())
g.gonder(k, None, kesir(TEKER), "wheel 2", "wheel -1")
kontrol("tekerlek: wheel 2 → +240, wheel -1 → -120 (ayrık 120'lik birim)",
        bekle(lambda: [l for l in loglar()[n0:] if l.startswith("tekerlek")][:2] == ["tekerlek 240 0", "tekerlek -120 0"],
              3) or bekle(lambda: sum(int(l.split()[1]) for l in loglar()[n0:] if l.startswith("tekerlek")) == 120, 1),
        str([l for l in loglar()[n0:] if l.startswith("tekerlek")]))
# pencere yönetimi (istemci alanı ölçüsü)
au.tasi(k, 100, 80)
kontrol("taşı: istemci alanı (100,80)", bekle(lambda: au.geometri(k)[:2] == (100, 80), 3), str(au.geometri(k)))
kod_b = dur_kodu(au.buyut, k)
kontrol("büyüt: sabit boyutlu pencere → büyütülemez, Dur 9 (doğrulamalı; sessiz başarı yok)",
        kod_b == 9 and "maximized" not in au.pencere_durumu(k), f"{kod_b} {au.pencere_durumu(k)}")
au.geri_yukle(k)
au.kucult(k)
kontrol("küçült: hidden", "hidden" in au.pencere_durumu(k), str(au.pencere_durumu(k)))
au.geri_yukle(k)
kontrol("geri yükle: hidden kalktı", not ({"hidden"} & au.pencere_durumu(k)), str(au.pencere_durumu(k)))
au.one_getir(k)
kontrol("one_getir: aktif", au.aktif() == k)
im, KUTU, DUGME, TEKER = kutular()  # pencere taşındı
kontrol("oturum_veri_yolu / atspi_adresi: oturumun", au.oturum_veri_yolu() == d["dbus_adres"] and
        au.atspi_adresi() == d["a11y_adres"])

# ---------------------------------------------------------------- 6) Türkçe + emoji yazı: yapıştırma yolu + pano yedeği
print("\n6) yazı + pano")
arka_uc._ORNEKLER["sanal"] = au
au.pano_yaz("eski pano ğ")
g.gonder(k, None, kesir(KUTU), "click left", "key ctrl+a", "key backspace")
with api.hedef("sanal"):
    r = api.yaz(k, "Merhaba 😀 dünya ж", None, False, False)
kontrol("yaz: düzende olmayan karakter (emoji, ж) → panodan yapıştırıldı, metin birebir",
        bekle(lambda: son("yazi=") == "Merhaba 😀 dünya ж", 3) and "panodan" in r, f"{son('yazi=')!r} {r}")
kontrol("yaz: eski pano GERİ yüklendi", au.pano_oku() == "eski pano ğ", repr(au.pano_oku()))
g.gonder(k, None, "key ctrl+a", "key backspace")
with api.hedef("sanal"):
    r = api.yaz(k, "düz Türkçe çğış", None, False, False)
kontrol("yaz: düzende olan metin harf harf (pano dokunulmadı)", bekle(lambda: son("yazi=") == "düz Türkçe çğış", 3)
        and "panodan" not in r and au.pano_oku() == "eski pano ğ", f"{son('yazi=')!r} {r}")
r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, stdin=subprocess.DEVNULL, timeout=5)
kontrol("pano: kullanıcının GERÇEK panosu bizim yazdığımızı içermiyor", b"eski pano" not in r.stdout and
        b"Merhaba" not in r.stdout)

# ---------------------------------------------------------------- 7) DUR / Devral
print("\n7) DUR / Devral")
n0 = len(loglar())
g.gonder(k, None, "keydown a")
open(hata.dur_dosyasi(), "w").close()
try:
    kontrol("DUR: gonder → 13", dur_kodu(g.gonder, k, None, "key b") == 13)
    kontrol("DUR: basılı 'a' bırakıldı, 'b' gitmedi", bekle(lambda: any(l.startswith("tus_birak 0x41") for l in
                                                                        loglar()[n0:]), 3) and
            not any(l.startswith("tus_bas 0x42") for l in loglar()[n0:]) and not g._basili_tus)
    kontrol("DUR: ham → 13", dur_kodu(g.ham, "type x") == 13)
finally:
    os.remove(hata.dur_dosyasi())
masaustu.devral_yaz()
kontrol("Devral: insan_var_mi, gonder → 12", au.insan_var_mi() and dur_kodu(g.gonder, k, None, "key c") == 12)
n0 = len(loglar())
g.insan_ham(kesir(DUGME))
g.insan_ham("buttondown left")
g.insan_ham("buttonup left")
kontrol("Devral: insan_ham girdisi Devral açıkken gider (panelin Devral'ı)", bekle(lambda: "tik: Kaydet" in loglar()[n0:], 3))
masaustu.devral_sil()

# ---------------------------------------------------------------- 8) EIS kopması kurtarması
print("\n8) EIS kopması")
n0 = len(loglar())
g.gonder(k, None, kesir(TEKER), "buttondown left")
kontrol("kopma: düğme basıldı", bekle(lambda: any(l.startswith("fare_bas sol") for l in loglar()[n0:]), 3))
eis_pid = au._eis.pid
os.kill(eis_pid, signal.SIGKILL)
bekle(lambda: au._eis.p.poll() is not None, 3)
kod = dur_kodu(g.gonder, k, None, "mouseto 0.5 0.5")
kontrol("kopma: sonraki gönderim Dur 9 (sessizce sürmez)", kod == 9, str(kod))
kontrol("kopma: basılı düğme KENDİLİĞİNDEN kurtarıldı (fare_birak)",
        bekle(lambda: any(l.startswith("fare_birak sol") for l in loglar()[n0:]), 3), str(loglar()[n0:][-4:]))
g.gonder(k, None, kesir(DUGME), "click left")
kontrol("kopma: sonraki çağrı yeni bağlantıyla çalışır", au._eis.pid != eis_pid and
        bekle(lambda: loglar()[-1].startswith("tik: Kaydet") or "tik: Kaydet" in loglar()[-3:], 3))

# ---------------------------------------------------------------- 9) işaretçi: park edilmiş imleç + hızlı iki pencere
print("\n9) işaretçi")
p2 = au.baslat([sys.executable, PENCERE], {"LOG": LOG2, "BASLIK": "kwin-arka IKI"})
k2 = bekle(lambda: next((w for w, b, _ in au.pencereler("kwin-arka IKI")), None), 15, 0.05)
au.tasi(k, 20, 40)
au.tasi(k2, 860, 40)
bekle(lambda: au.geometri(k)[:2] == (20, 40) and au.geometri(k2)[:2] == (860, 40), 3)
def iki_dugme():
    im_ = au.goruntu()
    a_, b_ = kutu_bul(im_.crop((0, 0, 800, 900)), (255, 0, 255)), kutu_bul(im_.crop((800, 0, 1600, 900)), (255, 0, 255))
    return (a_, (b_[0] + 800, b_[1], b_[2] + 800, b_[3])) if a_ and b_ else None


d1, d2 = bekle(iki_dugme, 8, 0.1)
n1, n2 = loglar().count("tik: Kaydet"), loglar(LOG2).count("tik: Kaydet")
gh = au.girdi("hizli")  # denetimsiz (masaüstü kipi): iki pencere arasında aynı gönderimde
t = time.perf_counter()
for _ in range(10):
    gh.gonder(EKRAN, None, kesir(d1), "click left", kesir(d2), "click left")
olcum["iki pencere arası 20 tık (hareket→tık beklemesi dahil)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms"
kontrol("hızlı tık: iki pencere arasında 10+10 tık hep DOĞRU yüzeye gitti",
        bekle(lambda: loglar().count("tik: Kaydet") - n1 == 10 and loglar(LOG2).count("tik: Kaydet") - n2 == 10, 3),
        f"{loglar().count('tik: Kaydet') - n1} / {loglar(LOG2).count('tik: Kaydet') - n2}")
# park edilmiş imleç: imleç d1'in üstünde dururken altına ikinci pencere gelir, AYNI noktaya tık → yeni pencere
gh.gonder(EKRAN, None, kesir(d1))
cx, cy = (d1[0] + d1[2]) // 2, (d1[1] + d1[3]) // 2
g2geo = au.geometri(k2)
ofs = ((d2[0] + d2[2]) // 2 - g2geo[0], (d2[1] + d2[3]) // 2 - g2geo[1])
au.tasi(k2, cx - ofs[0], cy - ofs[1])
au.one_getir(k2)
bekle(lambda: au.geometri(k2)[:2] == (cx - ofs[0], cy - ofs[1]), 3)
time.sleep(0.2)
n1, n2 = loglar().count("tik: Kaydet"), loglar(LOG2).count("tik: Kaydet")
gh.gonder(EKRAN, None, kesir(d1), "click left")
kontrol("park edilmiş imleç: altına gelen yeni pencereye tık gider (eskiye değil)",
        bekle(lambda: loglar(LOG2).count("tik: Kaydet") == n2 + 1, 3) and loglar().count("tik: Kaydet") == n1,
        f"eski {loglar().count('tik: Kaydet') - n1} yeni {loglar(LOG2).count('tik: Kaydet') - n2}")
gh.kapat()
g.kapat()
au.kapat(k2)
kontrol("kapat: ikinci pencere kibarca kapandı", bekle(lambda: k2 not in au.kimlikler(), 5) and
        bekle(lambda: p2.poll() is not None, 5))

# ---------------------------------------------------------------- 10) kapanış + kalıntı
print("\n10) kapanış + kalıntı")
pids = dict(d["pid"])
cg, cdir, xa = d["cgroup"], d["calisma"], d["x_ana"]
r = subprocess.run(["systemctl", "--user", "show", d["kafes"], "-p", "MemoryCurrent"], capture_output=True, text=True)
olcum["kafes belleği (KWin + 2 Qt penceresi)"] = r.stdout.strip()
t = time.monotonic()
ok_, notlar = masaustu.masaustu_durdur()
olcum["kapanış"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
kontrol("durdur: kapatıldı, not yok", ok_ and not notlar, str(notlar))
kontrol("durdur: süreçler (KWin, dbus, bildirim, kayıt defteri, öncelik bekçisi, uygulama) yok",
        not any(masaustu._canli(p) for p in pids.values()) and bekle(lambda: p1.poll() is not None, 3))
kontrol("durdur: kafes boş, çalışma dizini + durum dosyası silindi", not masaustu._kafes_surecleri(cg) and
        not os.path.exists(cdir) and not os.path.exists(masaustu.durum_yolu()))
kontrol("durdur: XWayland soketleri/kilitleri kalmadı", not any(os.path.exists(y) for n in (xa, xa + 1) for y in (
    f"/tmp/.X11-unix/X{n}", f"/tmp/.X{n}-lock")))
kontrol("durdur: hiçbir deskhand-sessiz ses çıkışı kalmadı (hiç kurulmadı)",
        masaustu._sink_modulu("deskhand-sessiz-kwin-" + d["kimlik"]) is None)
kontrol("durdur: kapalıyken arka uç → Dur 14", dur_kodu(au.goruntu) == 14 and dur_kodu(au.girdi) == 14)

# çökme: KWin SIGKILL → durum yok; sonraki başlatma kalıntıyı temizler
d2_ = masaustu.masaustu_baslat("800x600")
BIZIM_X.append(d2_.get("x_ana"))
os.kill(d2_["pid"]["kwin"], signal.SIGKILL)
bekle(lambda: not masaustu._canli(d2_["pid"]["kwin"]), 3)
kontrol("çökme: KWin ölünce durum() None (bayat kayıt bağlanmaz)", masaustu.durum() is None and
        dur_kodu(sec(arka_bayragi=True).goruntu) == 14)
d3_ = masaustu.masaustu_baslat("800x600")
BIZIM_X.append(d3_.get("x_ana"))
kalinti = {"dizin": os.path.exists(d2_["calisma"]),
           # eski oturumun kilidi kalmadı (aynı numarayı yeni oturum yeniden almış olabilir: onunki sayılmaz)
           "kilit": [n for n in (d2_["x_ana"], d2_["x_ana"] + 1) if os.path.exists(f"/tmp/.X{n}-lock")
                     and n not in (d3_["x_ana"], d3_["x_ana"] + 1)],
           "surec": [a for a, p in d2_["pid"].items() if masaustu._canli(p)]}
kontrol("çökme: yeni başlatma eskisinin kalıntılarını temizledi (dizin, X kilitleri, süreçler)",
        not kalinti["dizin"] and not kalinti["kilit"] and not kalinti["surec"] and masaustu.tur(d3_) == "kwin",
        str(kalinti))
masaustu.masaustu_durdur()

# ---------------------------------------------------------------- 11) gerçek oturum değişmedi
print("\n11) gerçek oturum")
for y in GERCEK_DOSYALAR:
    kontrol(f"gerçek dosya değişmedi: {y}", sha1(y) == sha0[y])
_ornek_dur.set()
fare1 = gercek_fare()
konumlar = sorted(set(FARE_ORNEK + [fare1]) - {None})
sizdi = [f_ for f_ in konumlar if any(abs(f_[0] - a) <= 2 and abs(f_[1] - b) <= 2 for a, b in GONDERILEN)]
print(f"   gerçek imleç koşu boyunca: {len(FARE_ORNEK)} örnek, {len(konumlar)} farklı konum "
      f"({'DEĞİŞTİ (kullanıcı)' if len(konumlar) > 1 else 'değişmedi'})")
kontrol("gerçek imleç koşu BOYUNCA hiç bizim gönderdiğimiz bir noktaya gitmedi", not sizdi, f"{sizdi[:5]}")
def kullanici_kwin():  # yalnız KULLANICININ KWin'i (kendi Wayland soketiyle); başka test oturumları sayılmaz
    gw_ = os.environ.get("WAYLAND_DISPLAY", "")
    return sorted(p for p in pidler("kwin_wayland") if gw_ and gw_ in masaustu._komut_satiri(p))


kontrol("kullanıcının kwin_wayland süreci aynı (yeniden başlamadı)", kullanici_kwin() == KWIN0)
kalan_x = [n for x_ in BIZIM_X if x_ is not None for n in (x_, x_ + 1)
           if os.path.exists(f"/tmp/.X11-unix/X{n}") or os.path.exists(f"/tmp/.X{n}-lock")]
kontrol("/tmp/.X11-unix: bu testin oturumlarından soket/kilit kalmadı (hiçbir aralık dışlanmadan)", not kalan_x,
        str(kalan_x))

print("\nölçümler:")
for a_, v_ in olcum.items():
    print(f"  {a_}: {v_}")
print(f"\n{gecen}/{toplam} KWin arka ucu testi geçti")
sys.exit(0 if gecen == toplam else 1)
