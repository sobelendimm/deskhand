"""Sanal arka uç testleri (GÖRÜNMEZ ikinci masaüstünde; kullanıcının ekranına HİÇBİR girdi gitmez).

Masaüstünü başlatır → Qt test penceresini (tests/yardimci/test_pencere.py) sanal masaüstünde açar → pencere
bulma, geometri, görüntü + OCR, tıklama, Türkçe yazı, tuş, kaydırma, sağ/çift tık, basılı tut/bırak, gözcü,
DUR (13), Devral (12), bildirim yakalama, sessiz ses çıkışı, CLI uçtan uca, kapatma ve temizlik.
EN ÖNEMLİSİ: kullanıcının GERÇEK fare konumu ve etkin penceresi baştan sona değişmemeli (kdotool yalnız SALT
OKUMA sorgusu: getmouselocation / getactivewindow).

Çalıştır:  python3 tests/test_sanal.py        (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import atexit
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import hata, masaustu, ocr
from deskhand.arka_uc import ARKA_ONEK, EKRAN, sec
from deskhand.hata import Dur

# ne olursa olsun (istisna dahil) masaüstü kapatılsın; _yalitim'in klasör silmesinden ÖNCE çalışır (atexit LIFO)
atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
TEST_PENCERE = os.path.join(KOK, "tests", "yardimci", "test_pencere.py")
gecen = toplam = 0
olcum = {}


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


def bekle(kosul, sure=5.0, aralik=0.02):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


# ---------------------------------------------------------------- gerçek oturumun SALT OKUMA görüntüsü

def gercek_durum():
    """Kullanıcının gerçek faresi + etkin penceresi (kdotool salt okuma; yoksa None)."""
    if not shutil.which("kdotool"):
        return None
    f = subprocess.run(["kdotool", "getmouselocation"], capture_output=True, text=True).stdout.strip()
    a = subprocess.run(["kdotool", "getactivewindow"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"x:(-?\d+)\s+y:(-?\d+)", f)
    return ((int(m.group(1)), int(m.group(2))) if m else None, a)


# Gerçek Deskhand test sırasında KULLANILIYOR olabilir (panel, başka Claude oturumu): onun günlük/işaret dosyaları
# değişir. Bu dosyalar özetten çıkarılır; testin oraya sızıp sızmadığı ayrıca İZİYLE denetlenir (test_izi_yok).
CANLI_DOSYA = re.compile(r"^(gunluk-\d{8}\.log|liste-[a-z]+\.isaret|ocr-gpu\.log)$")
TEST_IZLERI = ("ekran-test ANA", "ekran-test BAŞKA", "deskhand-test-")


def agac_ozeti(yol):
    h = hashlib.sha1()
    yol = os.path.expanduser(yol)
    for d, _, dosyalar in sorted(os.walk(yol)):
        for f in sorted(dosyalar):
            if CANLI_DOSYA.match(f):
                h.update(f.encode())  # var/yok değişimi sayılır, içerik (canlı kullanım) sayılmaz
                continue
            p = os.path.join(d, f)
            try:
                with open(p, "rb") as fp:
                    h.update(p.encode() + fp.read())
            except OSError:
                pass
    return h.hexdigest()


def pidler(ad):
    return subprocess.run(["pgrep", "-x", ad], capture_output=True, text=True).stdout.split()


ANAHTARLIK = ("ksecretd", "kwalletd6", "kwalletd5", "gnome-keyring-daemon")
anahtarlik0 = {a: pidler(a) for a in ANAHTARLIK}
GERCEK_YOLLAR = ("~/.config/deskhand", "~/.config/ekran", "~/.local/state/deskhand")
gercek0 = gercek_durum()
ozet0 = {y: agac_ozeti(y) for y in GERCEK_YOLLAR}
print(f"gerçek oturum (salt okuma): fare {gercek0[0] if gercek0 else '?'} etkin {gercek0[1] if gercek0 else '?'}")


def log_satirlari(yol):
    try:
        with open(yol) as f:
            return [l.rstrip("\n") for l in f]
    except OSError:
        return []


def log_bekle(yol, desen, sure=5.0, bas=0):
    rx = re.compile(desen)
    return bekle(lambda: next((l for l in log_satirlari(yol)[bas:] if rx.search(l)), None), sure)


# ---------------------------------------------------------------- 1) masaüstünü başlat

kanca_adres = []
masaustu.ozel_veri_yolu_kancasi(lambda adres, durum: kanca_adres.append((adres, durum["ekran"])))
t = time.monotonic()
d = masaustu.masaustu_baslat()
olcum["masaüstü açılış"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
KW = masaustu.tur(d) == "kwin"  # arka plan masaüstü türü: KWin oturumu ya da Xvfb (DESKHAND_ARKA_TUR ile zorlanır)
print(f"arka plan masaüstü türü: {masaustu.tur(d)}")
if os.environ.get("DESKHAND_ARKA_TUR") in ("kwin", "xvfb"):
    kontrol("masaüstü: zorlanan tür açıldı (DESKHAND_ARKA_TUR)", masaustu.tur(d) == os.environ["DESKHAND_ARKA_TUR"])
if KW:
    kontrol("masaüstü: KWin oturumu açıldı (özel Wayland soketi, XWayland :120+)",
            d["ekran"] == d["wayland"] and os.path.exists(d["wayland_yol"]) and int(d["xwayland"][1:]) >= 120)
else:
    kontrol("masaüstü: açıldı, :90+ ekranı", d and int(d["no"]) >= 90 and d["ekran"] == f":{d['no']}")
kontrol("masaüstü: durum dosyası doğrulanıyor", masaustu.durum() is not None)
kontrol("masaüstü: ikinci başlatma aynı masaüstünü döndürür", masaustu.masaustu_baslat().get("zaten") is True)
kontrol("kanca: özel veri yolu hazır kancası adresle çağrıldı", kanca_adres == [(d["dbus_adres"], d["ekran"])],
        str(kanca_adres))
masaustu.OZEL_VERI_YOLU_KANCALARI.clear()

# erişim anahtarı: anahtarsız yerel istemci (ör. X11 izni olan bir Flatpak uygulaması) bağlanamaz
xa = d.get("xauth") or ""
st = os.stat(xa) if xa and os.path.exists(xa) else None
XEKRAN = d["xwayland"] if KW else d["ekran"]  # X istemcilerinin ekranı (KWin: oturumun XWayland'i)
kontrol("anahtar: X sunucusu -auth ile açıldı, anahtar dosyası 0600 ve komut satırında",
        st is not None and (st.st_mode & 0o777) == 0o600 and
        xa in masaustu._komut_satiri(d["pid"]["kwin" if KW else "xvfb"]))
def _anahtarsiz(xauth_ortam):
    kod = ("import sys\nfrom Xlib import display\ntry:\n    display.Display(sys.argv[1]).close()\n"
           "    print('BAGLANDI')\nexcept Exception as e:\n    print('RED', type(e).__name__)")
    r = subprocess.run([sys.executable, "-I", "-c", kod, XEKRAN], capture_output=True, text=True, timeout=20,
                       env={k: v for k, v in os.environ.items() if k != "XAUTHORITY"} | xauth_ortam)
    satirlar = r.stdout.strip().splitlines()  # Xlib önce "no xauthority details" uyarısı basabilir
    return satirlar[-1] if satirlar else r.stderr.strip()[-200:]
kontrol("anahtar: anahtarsız bağlantı REDDEDİLİR", _anahtarsiz({"XAUTHORITY": "/dev/null"}).startswith("RED"))
kontrol("anahtar: kullanıcının kendi XAUTHORITY'siyle de REDDEDİLİR",
        _anahtarsiz({"XAUTHORITY": os.environ.get("XAUTHORITY", "/dev/null")}).startswith("RED"))
kontrol("anahtar: uygulamaya verilen XAUTHORITY ile bağlanır",
        _anahtarsiz({"XAUTHORITY": masaustu.uygulama_ortami(d).get("XAUTHORITY", "")}) == "BAGLANDI")
if KW:  # KWin türünde Deskhand X'e hiç bağlanmaz; x_ac oturumun Wayland soket adını ekran sanmaz (Dur 14)
    kontrol("anahtar: KWin türünde x_ac(ekran) reddedilir (X bağlantısı yok, soket adı ekran değil)",
            dur_kodu(masaustu.x_ac, d["ekran"]) == 14)
else:
    kontrol("anahtar: Deskhand'in kendi bağlantısı (x_ac) çalışır", masaustu.x_ac(d["ekran"]).screen() is not None)

ue = masaustu.uygulama_ortami(d, {"WAYLAND_DISPLAY": "wayland-0", "BENIM": "1"})
wd = ue.get("WAYLAND_DISPLAY", "")
if KW:
    kontrol("ortam: oturumun Wayland soketi (MUTLAK, var), DISPLAY=XWayland, özel D-Bus, Wayland araç takımları, ek "
            "değişken geçer", wd == d["wayland_yol"] and os.path.exists(wd) and ue["DISPLAY"] == d["xwayland"] and
            ue["XAUTHORITY"] == d["xauth"] and ue["DBUS_SESSION_BUS_ADDRESS"] == d["dbus_adres"] and
            ue["QT_QPA_PLATFORM"] == "wayland" and ue["GDK_BACKEND"] == "wayland" and ue["MOZ_ENABLE_WAYLAND"] == "1"
            and ue["ELECTRON_OZONE_PLATFORM_HINT"] == "wayland" and ue["PULSE_SERVER"].endswith("/ses-yok")
            and ue["BENIM"] == "1")
else:
    kontrol("ortam: DISPLAY/özel D-Bus/x11 zorunlu, WAYLAND_DISPLAY = var olmayan mutlak yol, ek değişken geçer",
            ue["DISPLAY"] == d["ekran"] and ue["DBUS_SESSION_BUS_ADDRESS"] == d["dbus_adres"] and
            os.path.isabs(wd) and not os.path.exists(wd) and wd.startswith(d["calisma"]) and
            ue["QT_QPA_PLATFORM"] == "xcb" and ue["GDK_BACKEND"] == "x11" and
            ue["MOZ_ENABLE_WAYLAND"] == "0" and ue["SDL_VIDEODRIVER"] == "x11" and
            ue["ELECTRON_OZONE_PLATFORM_HINT"] == "x11" and ue["PULSE_SERVER"].endswith("/ses-yok") and
            ue["BENIM"] == "1")
kontrol("ortam: XDG_CURRENT_DESKTOP=KDE, KDE_SESSION_VERSION=6, XDG_SESSION_TYPE",
        (ue["XDG_CURRENT_DESKTOP"], ue["KDE_SESSION_VERSION"], ue["XDG_SESSION_TYPE"]) ==
        ("KDE", "6", "wayland" if KW else "x11"))
kontrol("ortam: kullanıcının SSH ajanı/erişilebilirlik adresi/EIS soketi geçmez, GSETTINGS_BACKEND=memory",
        not any(a in ue for a in ("SSH_AUTH_SOCK", "AT_SPI_BUS_ADDRESS", "LIBEI_SOCKET", "KDE_FULL_SESSION"))
        and ue.get("GSETTINGS_BACKEND") == "memory", str([a for a in ("SSH_AUTH_SOCK", "AT_SPI_BUS_ADDRESS") if a in ue]))
kontrol("ortam: ses sunucusu YOK (PULSE_SERVER/PIPEWIRE_REMOTE var olmayan sokete; kullanıcının sunucusu yok)",
        ue["PULSE_SERVER"] == f"unix:{ue['PIPEWIRE_REMOTE']}" and not os.path.exists(ue["PIPEWIRE_REMOTE"]) and
        "PULSE_SINK" not in ue and "/run/user/" not in ue.get("PIPEWIRE_RUNTIME_DIR", ""), str(ue.get("PULSE_SERVER")))
kontrol("ortam: masaüstü kimliği işareti (kafessiz durdurma için)",
        len(d.get("kimlik") or "") == (8 if KW else 16) and ue.get("DESKHAND_SANAL_KIMLIK") == d["kimlik"])
if KW:
    kontrol("masaüstü: pencere yöneticisi = KWin (canlı, uyarı yok)", masaustu._canli(d["pid"]["kwin"]) and
            not d.get("uyarilar"), str(d.get("uyarilar")))
else:
    kontrol("masaüstü: openbox çalışıyor", d.get("openbox"), str(d.get("uyarilar")))
kontrol("masaüstü: bellek kafesi (scope) içinde", d.get("kafes") and d["cgroup"].endswith(d["kafes"]))
r = subprocess.run(["systemctl", "--user", "show", d["kafes"], "-p", "MemoryMax"], capture_output=True, text=True)
kontrol("masaüstü: kafes MemoryMax = 8G (ABM-KARAR a)", r.stdout.strip() == f"MemoryMax={8 * 1024 ** 3}", r.stdout)
r = subprocess.run(["systemctl", "--user", "show", d["kafes"], "-p", "MemorySwapMax"], capture_output=True, text=True)
kontrol("masaüstü: kafes MemorySwapMax = 0 (takasa taşmaz)", r.stdout.strip() == "MemorySwapMax=0", r.stdout)
kontrol("masaüstü: ses bekçisi YOK (ses sunucusuna erişim olmadığından gerekmez)", "ses_bekcisi" not in d["pid"])
xpid = d["pid"]["kwin" if KW else "xvfb"]
# ad tabanlı sistem kuralları (ör. ananicy: kwin_wayland → nice -12) exec anında yükseltebilir: kafesin öncelik
# bekçisi en çok ~0,5 sn'de geri düşürür
kontrol("masaüstü: ekran sunucusu nice 10 (öncelik bekçisi ≤ 2 sn)",
        bekle(lambda: os.getpriority(os.PRIO_PROCESS, xpid) >= 10, 2, 0.1), str(os.getpriority(os.PRIO_PROCESS, xpid)))
kontrol("masaüstü: ekran sunucusu ionice idle", bekle(lambda: "idle" in subprocess.run(
    ["ionice", "-p", str(xpid)], capture_output=True, text=True).stdout, 2, 0.1))
kontrol("masaüstü: öncelik bekçisi kafeste çalışıyor", masaustu._canli(d["pid"].get("oncelik_bekcisi")) and
        masaustu._cgroup(d["pid"]["oncelik_bekcisi"]) == d["cgroup"])
kontrol("masaüstü: boş ses çıkışı KURULMADI", d.get("ses") is None)
if shutil.which("pactl"):
    r = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True)
    kontrol("masaüstü: varsayılan ses çıkışı DEĞİŞMEDİ (deskhand-sessiz değil)",
            not r.stdout.strip().startswith("deskhand-sessiz"))
else:
    print("ATLANDI  masaüstü: varsayılan ses çıkışı denetimi (pactl yok: ses sunucusu istemcisi kurulu değil)")

# ---- Wayland sızıntısı: WAYLAND_DISPLAY yoksa libwayland $XDG_RUNTIME_DIR/wayland-0'a bağlanır (= çoğu KDE'de
# kullanıcının GERÇEK compositor'ı). Sahte bir runtime klasöründe dinleyen sahte wayland-0 kurulur; arka plan
# ortamındaki, Wayland'i ZORLAYAN istemciler ona bağlanmamalı. (Gerçek compositor'a hiçbir şey gitmez: istemcilerin
# XDG_RUNTIME_DIR'i sahte klasör.)
WL_ISTEMCI = ('import ctypes; l = ctypes.CDLL("libwayland-client.so.0"); l.wl_display_connect.restype = ctypes.c_void_p; '
              'print("BAGLANDI" if l.wl_display_connect(None) else "BAGLANAMADI")')
QT_ISTEMCI = ("from PyQt6.QtGui import QGuiApplication; "
              "a = QGuiApplication(['t', '-platform', 'wayland;offscreen']); print(a.platformName())")
GTK_ISTEMCI = ("import os; os.environ['GDK_BACKEND'] = 'wayland'; import gi; gi.require_version('Gtk', '4.0'); "
               "from gi.repository import Gtk; print('gtk', Gtk.init_check())")
sahte_rt = tempfile.mkdtemp(prefix="wl-", dir=GECICI)
os.chmod(sahte_rt, 0o700)
sw = socket.socket(socket.AF_UNIX)
sw.bind(os.path.join(sahte_rt, "wayland-0"))
sw.listen(16)
sw.setblocking(False)


def wl_baglanti_say():
    n = 0
    while True:
        try:
            c, _a = sw.accept()
        except BlockingIOError:
            return n
        c.close()
        n += 1


# denetim: eski davranış (WAYLAND_DISPLAY silinmiş) sahte sokete BAĞLANIYOR → test sızıntıyı görebilir
e0 = {k_: v_ for k_, v_ in ue.items() if k_ != "WAYLAND_DISPLAY"} | {"XDG_RUNTIME_DIR": sahte_rt}
r = subprocess.run([sys.executable, "-c", WL_ISTEMCI], env=e0, capture_output=True, text=True, timeout=20)
kontrol("wayland denetimi: WAYLAND_DISPLAY silinince istemci varsayılan wayland-0'a bağlanıyor (eski açık)",
        "BAGLANDI" in r.stdout and wl_baglanti_say() >= 1, r.stdout + r.stderr[-200:])
wl_cikti = []
for ad_, kod_ in (("libwayland", WL_ISTEMCI), ("qt6 -platform wayland", QT_ISTEMCI), ("gtk4 GDK_BACKEND=wayland", GTK_ISTEMCI)):
    pw = masaustu.baslat([sys.executable, "-c", kod_], {"XDG_RUNTIME_DIR": sahte_rt}, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    try:
        o_, e_ = pw.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        pw.kill()
        o_, e_ = pw.communicate()
    wl_cikti.append(f"{ad_}: {o_.decode().strip()} / {e_.decode().strip()[-120:]}")
time.sleep(0.2)
wl_n = wl_baglanti_say()
kontrol("WAYLAND: arka plan istemcileri (libwayland, Qt6 ve GTK4 Wayland'i zorlasa bile) wayland-0'a BAĞLANMADI",
        wl_n == 0 and ("BAGLANDI" if KW else "BAGLANAMADI") in wl_cikti[0], f"{wl_n} bağlantı; " + " | ".join(wl_cikti))
sw.close()

au = sec(arka_bayragi=True)
kontrol("arka uç: sec(--arka) → sanal", au.ad == "sanal")
kontrol("arka uç: ekran alanı = masaüstü boyutu", au.ekran_alani() == (0, 0, d["boyut"][0], d["boyut"][1]))
sureler = []
for _ in range(7):
    t = time.perf_counter()
    im = au.goruntu()
    sureler.append((time.perf_counter() - t) * 1000)
olcum["tüm ekran görüntüsü (1920x1080)"] = f"{statistics.median(sureler):.1f} ms (medyan, 7 ölçüm)"
kontrol("görüntü: RGB, ekran boyutunda", im.mode == "RGB" and im.size == tuple(d["boyut"][:2]))
if not KW:  # KWin türünde masaüstü zemini KWin'in (Plasma/duvar kâğıdı yok): yalnız Xvfb kökü boyanır
    kontrol("görüntü: kök zemin düz gri", im.getpixel((3, 3)) == (0x8C, 0x8C, 0x8C), str(im.getpixel((3, 3))))
kontrol("görüntü: < 50 ms", statistics.median(sureler) < 50, f"{statistics.median(sureler):.1f} ms")

# özel D-Bus: kullanıcının oturumundaki servisler etkinleşmez (kwalletd, kded…)
from jeepney import DBusAddress, new_method_call  # noqa: E402
from jeepney.io.blocking import open_dbus_connection  # noqa: E402

with open_dbus_connection(bus=d["dbus_adres"]) as c:
    dbus_ad = DBusAddress("/org/freedesktop/DBus", bus_name="org.freedesktop.DBus", interface="org.freedesktop.DBus")
    adlar = c.send_and_get_reply(new_method_call(dbus_ad, "ListActivatableNames")).body[0]
    kontrol("D-Bus: özel veri yolunda kwalletd/kded/plasma etkinleştirilemez",
            not any(a.startswith("org.kde.") for a in adlar), str(adlar))
    from jeepney import HeaderFields, MessageType  # noqa: E402

    def hata_adi(m):
        return (m.header.fields.get(HeaderFields.error_name, "?") if m.header.message_type == MessageType.error
                else "yanıt geldi")
    gizli = DBusAddress("/org/freedesktop/secrets", bus_name="org.freedesktop.secrets",
                        interface="org.freedesktop.DBus.Peer")
    yanit = hata_adi(c.send_and_get_reply(new_method_call(gizli, "Ping"), timeout=5))
    kontrol("D-Bus: org.freedesktop.secrets → ServiceUnknown (ikinci ksecretd/kwalletd yok)",
            yanit == "org.freedesktop.DBus.Error.ServiceUnknown", yanit)
    yanit = hata_adi(c.send_and_get_reply(new_method_call(DBusAddress("/", bus_name="org.kde.kwalletd6",
                                                                     interface="org.freedesktop.DBus.Peer"), "Ping"),
                                          timeout=5))
    kontrol("D-Bus: org.kde.kwalletd6 → ServiceUnknown", yanit == "org.freedesktop.DBus.Error.ServiceUnknown", yanit)
    sahip = c.send_and_get_reply(new_method_call(dbus_ad, "NameHasOwner", "s", ("org.freedesktop.Notifications",)))
    kontrol("D-Bus: bildirim adı yakalayıcıda", sahip.body[0] is True)
    bildirim = DBusAddress("/org/freedesktop/Notifications", bus_name="org.freedesktop.Notifications",
                           interface="org.freedesktop.Notifications")
    r = c.send_and_get_reply(new_method_call(bildirim, "Notify", "susssasa{sv}i",
                                             ("deneme", 0, "", "Başlık ğüş", "Gövde İÇ", [], {}, -1)))
    kontrol("bildirim: Notify kimlik döndürür", r.body[0] >= 1)
    srv = c.send_and_get_reply(new_method_call(bildirim, "GetServerInformation")).body
    kontrol("bildirim: GetServerInformation", srv[0] == "deskhand", str(srv))
kayit = bekle(lambda: log_satirlari(masaustu.bildirim_yolu()), 3)
son = json.loads(kayit[-1]) if kayit else {}
kontrol("bildirim: bildirimler.jsonl'a yazıldı (kullanıcıya düşmedi)",
        son.get("baslik") == "Başlık ğüş" and son.get("govde") == "Gövde İÇ" and son.get("uygulama") == "deneme",
        str(son))
kontrol("bildirim: günlük yalıtılmış STATE_DIR'de", masaustu.bildirim_yolu().startswith(GECICI))

# ---------------------------------------------------------------- 2) test penceresi

LOG = os.path.join(_yalitim.PAYLASIM, "test.log")
LOG2 = os.path.join(_yalitim.PAYLASIM, "test2.log")
t_ac = time.monotonic()
p1 = au.baslat([sys.executable, TEST_PENCERE], env={"LOG": LOG, "BASLIK": "deskhand-sanal ANA", "HAZIR_MS": "300"})
k = bekle(lambda: next((w for w, b, _ in au.pencereler("deskhand-sanal ANA")), None), 20, 0.05)
olcum["Qt test penceresi açılışı"] = f"{(time.monotonic() - t_ac) * 1000:.0f} ms"
kontrol("pencere: sanal masaüstünde açıldı", k is not None)
if k is None:
    masaustu.masaustu_durdur()
    sys.exit(1)
kontrol("pencere: kimlik arka:… biçiminde (xvfb: 0x…, kwin: {uuid})",
        re.fullmatch(ARKA_ONEK + (r"\{[0-9a-f-]{36}\}" if KW else r"0x[0-9a-f]+"), k), k)
kontrol("pencere: pencere_coz(ad) → aynı kimlik", au.pencere_coz("deskhand-sanal ANA") == k)
kontrol("pencere: pencere_coz(kimlik) → aynı", au.pencere_coz(k) == k)
kontrol("pencere: pencere_coz('ekran') → EKRAN", au.pencere_coz("ekran") == EKRAN)
kontrol("pencere: yok → Dur 8", dur_kodu(au.pencere_coz, "yok-boyle-bir-pencere") == 8)
kontrol("pencere: yanlış önek → Dur 8", dur_kodu(au.geometri, "{00000000-0000-0000-0000-000000000000}") == 8)
kontrol("pencere: başlık", au.baslik(k) == "deskhand-sanal ANA", au.baslik(k))
kontrol("pencere: sınıf (WM_CLASS, küçük harf)", au.sinif(k) != "" and au.sinif(k) == au.sinif(k).lower(), au.sinif(k))
def _atalar(pid):
    s_ = []
    while pid and pid > 1 and len(s_) < 16:
        s_.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f_:
                pid = int(f_.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return s_


kontrol("pencere: pid = başlatılan sürecin (bwrap ad alanı) çocuğu", p1.pid in _atalar(au.pid(k)), f"{au.pid(k)} / {p1.pid}")
kontrol("pencere: kimlikler() içeriyor", k in au.kimlikler())
geo = au.geometri(k)
W, H = au.ekran_alani()[2:]
kontrol("pencere: geometri ekranın içinde, 760x640", 0 <= geo[0] and 0 <= geo[1] and geo[0] + geo[2] <= W
        and geo[1] + geo[3] <= H and geo[2:] == (760, 640), str(geo))
kontrol("pencere: pencere yöneticisi yerleşimi (0,0 değil)", geo[0] > 0 and geo[1] > 0, str(geo))
kontrol("pencere: yeni pencere odak aldı (aktif)", bekle(lambda: au.aktif() == k, 3), au.aktif())
log_bekle(LOG, r"^$|.", 0.1)
bekle(lambda: True, 0.4)  # HAZIR_MS


def kirp(k_):
    x, y, g, h = au.geometri(k_)
    return au.goruntu().crop((x, y, x + g, y + h))


def bul(k_, metin):
    t = time.perf_counter()
    satirlar = ocr.satirla(ocr.oku(kirp(k_)))
    olcum.setdefault("pencere OCR (760x640)", f"{(time.perf_counter() - t) * 1000:.0f} ms")
    m = ocr.ara(satirlar, metin)
    return m[0] if m else None


m_kaydet = bul(k, "Kaydet")
kontrol("OCR: pencere kırpımında 'Kaydet' bulundu", m_kaydet is not None)
m_eposta = bul(k, "E-posta:")
m_cift = bul(k, "Çift tıkla beni")
m_iptal = bul(k, "İptal")
m_oyun = bul(k, "OYUN ALANI")
m_not = bul(k, "Not alanı:")
kontrol("OCR: E-posta, Çift tıkla, İptal, OYUN ALANI, Not alanı bulundu",
        all((m_eposta, m_cift, m_iptal, m_oyun, m_not)))


GONDERILEN = set()  # sanal ekrana gönderdiğimiz imleç noktaları (gerçek fare buralardan birine gitmiş mi?)


def nokta(k_, x, y):
    X, Y, _, _ = au.geometri(k_)
    GONDERILEN.add((int(X + x), int(Y + y)))
    return f"mouseto {(X + x + 0.5) / W:.6f} {(Y + y + 0.5) / H:.6f}"


def denetle(k_, desen):  # üst katmanın güvenlik denetiminin küçük taklidi (aktif + başlık)
    if k_ != EKRAN and au.aktif() != k_:
        raise Dur(3, f"aktif pencere değişti → {au.baslik(au.aktif())!r}")
    if desen and not re.search(desen, au.baslik(k_), re.I):
        raise Dur(4, "başlık uymadı")


g = au.girdi("test", denetle=denetle)
try:
    # tıklama + gecikme
    n0 = len(log_satirlari(LOG))
    g.gonder(k, "ANA", nokta(k, m_kaydet["cx"], m_kaydet["cy"]))
    fx, fy, alt = au.fare()
    X, Y = au.geometri(k)[:2]
    kontrol("fare: imleç hedefte, altındaki pencere = hedef",
            abs(fx - (X + m_kaydet["cx"])) <= 1 and abs(fy - (Y + m_kaydet["cy"])) <= 1 and alt == k, f"{fx},{fy} {alt}")
    t = time.perf_counter()
    g.gonder(k, "ANA", "click left")
    satir = log_bekle(LOG, r"^tık: Kaydet$", 5, n0)
    olcum["tık → uygulama olayı"] = f"{(time.perf_counter() - t) * 1000:.1f} ms"
    kontrol("tık: log'da 'tık: Kaydet'", satir is not None)

    # Türkçe yazı
    g.gonder(k, "ANA", nokta(k, m_iptal["cx"], m_eposta["cy"]), "click left")
    time.sleep(0.1)
    metin = "ğüşıöç İĞÜŞÖÇ"
    g.gonder(k, "ANA", f"type {metin}")
    kontrol("yazı: Türkçe karakterler birebir (eposta=ğüşıöç İĞÜŞÖÇ)",
            log_bekle(LOG, "^eposta=" + re.escape(metin) + "$", 3) is not None, (log_satirlari(LOG) or [""])[-1])
    g.gonder(k, "ANA", "key ctrl+a", "key backspace")
    kontrol("tuş: ctrl+a + backspace → alan boş", log_bekle(LOG, r"^eposta=$", 3) is not None)
    ozel = "a—b…c'd\"e“f”g‘h’i@#{}~|<>" if not KW else "a'b\"c@#{}~|<>$€"
    t = time.perf_counter()
    g.gonder(k, "ANA", f"type {ozel}")
    olcum["yazma hızı"] = f"{len(ozel) / (time.perf_counter() - t):.0f} harf/sn (typehold 8 + typedelay 2 ms)"
    kontrol("yazı: özel karakterler birebir (" + ozel + ")",
            log_bekle(LOG, "^eposta=" + re.escape(ozel) + "$", 3) is not None, (log_satirlari(LOG) or [""])[-1])
    g.gonder(k, "ANA", "key ctrl+a", "key backspace")
    if KW:  # KWin: klavye haritasında olmayan karakter (— ж) → `type` HEP YA DA HİÇ: Dur 1, hiçbir harf gitmez
        n0 = len(log_satirlari(LOG))
        kontrol("yazı: düzende olmayan karakter (— ж) → Dur 1, HİÇBİR harf yazılmadı (üst katman panoya düşer)",
                dur_kodu(g.gonder, k, "ANA", "type ab—cж") == 1 and
                log_bekle(LOG, "^eposta=.+$", 0.5, n0) is None, (log_satirlari(LOG) or [""])[-1])
        kontrol("yazı: yazilabilir_mi düzene göre (ş evet, — ve ж hayır)",
                au.yazilabilir_mi("ş") and not au.yazilabilir_mi("—") and not au.yazilabilir_mi("ж"))
    else:
        g.gonder(k, "ANA", "type ½ ŧ Ω ж")  # düzende ve kalıcı eşlemede yok → geçici eşleme
        kontrol("yazı: geçici eşleme (½ ŧ Ω ж)", log_bekle(LOG, "^eposta=½ ŧ Ω ж$", 3) is not None,
                (log_satirlari(LOG) or [""])[-1])
    g.gonder(k, "ANA", "key ctrl+a", "key x:BackSpace", "typedelay 1", "typehold 3", "type Hızlı", "key shift+home")
    kontrol("tuş: x:Keysym + typedelay/typehold", log_bekle(LOG, r"^eposta=Hızlı$", 3) is not None)

    # sağ tık, çift tık
    n0 = len(log_satirlari(LOG))
    g.gonder(k, "ANA", nokta(k, m_iptal["cx"], m_iptal["cy"]), "click right")
    kontrol("sağ tık: 'sağ: İptal'", log_bekle(LOG, r"^sağ: İptal$", 3, n0) is not None)
    g.gonder(k, "ANA", "key esc")
    g.gonder(k, "ANA", nokta(k, m_cift["cx"], m_cift["cy"]), "click left", "click left")
    kontrol("çift tık (tek gonder, iki click): 'çift: Çift tıkla beni'",
            log_bekle(LOG, r"^çift: Çift tıkla beni$", 3, n0) is not None)

    # oyun alanı: tuş bas/bırak, fare basılı tut/bırak
    ox, oy = m_oyun["cx"], m_oyun["cy"]
    n0 = len(log_satirlari(LOG))
    g.gonder(k, "ANA", nokta(k, ox, oy), "click left")
    g.gonder(k, "ANA", "key w")
    kontrol("tuş: oyun alanında 'w' bas+bırak", log_bekle(LOG, r"^tus_bas w ", 3, n0) and
            log_bekle(LOG, r"^tus_birak w ", 3, n0))
    n0 = len(log_satirlari(LOG))
    g.gonder(k, "ANA", "keydown d")
    time.sleep(0.3)
    g.zorla("keyup d")
    ls = [l for l in log_satirlari(LOG)[n0:] if " d " in l]
    kontrol("basılı tut: keydown d → keyup d (zorla), tekrar yok", bekle(lambda: any(
        l.startswith("tus_birak d") for l in log_satirlari(LOG)[n0:]), 3) and
            [l.split()[0] for l in log_satirlari(LOG)[n0:] if l.split()[1:2] == ["d"]] == ["tus_bas", "tus_birak"],
            str(ls))
    n0 = len(log_satirlari(LOG))
    g.gonder(k, "ANA", nokta(k, ox - 50, oy), "buttondown left")
    time.sleep(0.2)
    g.gonder(k, "ANA", nokta(k, ox + 50, oy))
    g.zorla("buttonup left")
    kontrol("basılı tut: buttondown → sürükle → buttonup",
            log_bekle(LOG, r"^fare_bas sol ", 3, n0) and log_bekle(LOG, r"^fare_surukle ", 3, n0) and
            log_bekle(LOG, r"^fare_birak sol ", 3, n0))
    kontrol("bırakma: basılı tuş/düğme kalmadı", not g._basili_tus and not g._basili_dugme)

    # DUR (13): her gonder/ham öncesi; basılı olan bırakılır
    n0 = len(log_satirlari(LOG))
    g.gonder(k, "ANA", "keydown a")
    os.makedirs(os.path.dirname(hata.dur_dosyasi()), exist_ok=True)
    open(hata.dur_dosyasi(), "w").close()
    kontrol("DUR: gonder → 13", dur_kodu(g.gonder, k, "ANA", "key b") == 13)
    kontrol("DUR: basılı 'a' bırakıldı", log_bekle(LOG, r"^tus_birak a ", 3, n0) is not None and not g._basili_tus)
    kontrol("DUR: ham → 13", dur_kodu(g.ham, "type x") == 13)
    kontrol("DUR: 'b' gönderilmedi", not any(l.startswith("tus_bas b") for l in log_satirlari(LOG)[n0:]))
    os.remove(hata.dur_dosyasi())

    # Devral (12): dosya + yazan süreç canlı olmalı (panel çökerse bayat dosya ajanı kalıcı 12'de tutmasın)
    with open(masaustu.devral_yolu(), "w") as f_:
        f_.write("panel 1234\n")  # eski biçim / sahipsiz
    kontrol("Devral: sahipsiz (eski biçim) dosya → insan yok", au.insan_var_mi() is False)
    ps_ = subprocess.Popen(["sleep", "30"])
    masaustu.devral_yaz(ps_.pid)
    kontrol("Devral: sahibi canlı → insan var", au.insan_var_mi() is True)
    ps_.kill()
    ps_.wait()
    kontrol("Devral: sahibi öldü (SIGKILL'lenmiş panel) → insan yok, bayat dosya beklenmez",
            au.insan_var_mi() is False and os.path.exists(masaustu.devral_yolu()))
    kontrol("Devral: sahipsiz dosya devral_sil ile silinir", masaustu.devral_sil() and
            not os.path.exists(masaustu.devral_yolu()))
    masaustu.devral_yaz()  # bu süreç = panel
    kontrol("Devral: insan_var_mi() True", au.insan_var_mi() is True)
    kontrol("Devral: etk_denetle → 12", dur_kodu(g.etk_denetle) == 12)
    kontrol("Devral: gonder → 12", dur_kodu(g.gonder, k, "ANA", "key c") == 12)
    g2 = au.girdi("devral")
    g2.devral_bekle = 0.3
    t = time.monotonic()
    kontrol("Devral: yeni girdi kısa bekler, sonra 12", dur_kodu(g2.gonder, k, "ANA", "key c") == 12 and
            time.monotonic() - t >= 0.3)
    kontrol("Devral: etkinlik() insan görür", au.etkinlik().insan(0) is True)
    g2.kapat()
    os.remove(masaustu.devral_yolu())
    kontrol("Devral: kalkınca insan_var_mi() False", au.insan_var_mi() is False)

    # kaydırma: kendi dinleyici penceremizde XTEST düğme 4/5/6/7
    from Xlib import X  # noqa: E402
    if KW:  # XWayland penceresi: Wayland tekerleği (ayrık 120'lik birim) XWayland'de düğme 4-7 olur
        from Xlib import display as _xdisp  # noqa: E402
        _eski_xa = os.environ.get("XAUTHORITY")
        os.environ["XAUTHORITY"] = d["xauth"]
        try:
            dp = _xdisp.Display(masaustu.guvenli_ekran(d["xwayland"]))
        finally:
            if _eski_xa is None:
                os.environ.pop("XAUTHORITY", None)
            else:
                os.environ["XAUTHORITY"] = _eski_xa
    else:
        dp = masaustu.x_ac(d["ekran"])
    kok = dp.screen().root
    dw = kok.create_window(0, 0, 300, 200, 0, dp.screen().root_depth, event_mask=X.ButtonPressMask,
                           background_pixel=0xFFFFFF)
    dw.set_wm_name("deskhand-sanal DINLEYICI")
    dw.map()
    dp.sync()
    if KW:
        kd_ = bekle(lambda: next((w for w, b, _ in au.pencereler("deskhand-sanal DINLEYICI")), None), 5)
    else:
        kd_ = ARKA_ONEK + f"0x{dw.id:x}"
    kontrol("kaydırma: dinleyici penceresi istemci listesinde", bekle(lambda: kd_ in au.kimlikler(), 3))
    au.one_getir(kd_)
    while dp.pending_events():
        dp.next_event()
    g.gonder(kd_, None, nokta(kd_, 150, 100), "wheel 2", "wheel -1", "hwheel 1", "hwheel -1")
    dugmeler = []
    bitis = time.monotonic() + 2
    while time.monotonic() < bitis and len(dugmeler) < 5:
        while dp.pending_events():
            ev = dp.next_event()
            if ev.type == X.ButtonPress:
                dugmeler.append(ev.detail)
        time.sleep(0.01)
    kontrol("kaydırma: wheel 2/-1, hwheel 1/-1 → düğme 4,4,5,7,6", dugmeler == [4, 4, 5, 7, 6], str(dugmeler))
    dw.destroy()
    dp.sync()
    dp.close()

    # öne getirme + gözcü (aktif pencere / başlık değişimi)
    p2 = au.baslat([sys.executable, TEST_PENCERE], env={"LOG": LOG2, "BASLIK": "deskhand-sanal İKİ", "HAZIR_MS": "100"})
    k2 = bekle(lambda: next((w for w, b, _ in au.pencereler("deskhand-sanal İKİ")), None), 20, 0.05)
    kontrol("ikinci pencere açıldı ve odak aldı", k2 and bekle(lambda: au.aktif() == k2, 3))
    kontrol("pencere_coz: iki pencereye uyan desen → Dur 5", dur_kodu(au.pencere_coz, "deskhand-sanal") == 5)
    kontrol("denetim: odak başka pencerede → gonder Dur 3 (girdi yok)", dur_kodu(g.gonder, k, "ANA", "key a") == 3)
    t = time.perf_counter()
    au.one_getir(k)
    olcum["one_getir"] = f"{(time.perf_counter() - t) * 1000:.0f} ms (50 ms yeniden çizim payı dahil)"
    kontrol("one_getir: ANA yeniden aktif", au.aktif() == k)
    g.izle(k, "ANA")
    au.etkinlestir(k2)
    kontrol("gözcü: aktif pencere değişti → ham Dur 3", bekle(lambda: g.kesildi is not None, 1) and
            dur_kodu(g.ham, "type x") == 3)
    g.izle_bitir()
    g.kesildi = None  # kde gibi: kesinti bayrağı bir sonraki izle()'ye dek kalır; aynı nesneyi sürdürüyoruz
    au.one_getir(k)
    g.gonder(k, "ANA", nokta(k, m_iptal["cx"], m_not["cy"]), "click left")
    time.sleep(0.1)
    g.izle(k, "ANA")
    yazilan, kod = 0, None
    try:
        for c in "0123456789abcdefghij":
            g.ham(f"type {c}")
            yazilan += 1
            time.sleep(0.03)
    except Dur as e:
        kod = e.kod
    g.izle_bitir()
    kontrol("gözcü: başlık değişti (10 harfte 'BAŞKA SEKME') → Dur 4, en çok 2 harf sızdı",
            kod == 4 and 10 <= yazilan <= 12, f"kod {kod}, {yazilan} harf")
    kontrol("kapat: ikinci pencere kibarca kapandı", (au.kapat(k2) or True) and
            bekle(lambda: k2 not in au.kimlikler(), 5) and bekle(lambda: p2.poll() is not None, 5))
finally:
    g.kapat()

# ---------------------------------------------------------------- 2b) SIGKILL sonrası basılı kalan tuş/düğme (D2)
from Xlib import X as _XX, display as _xd  # noqa: E402,F401
KW_2B = KW


def basililar():
    dp_ = masaustu.x_ac(d["ekran"])
    try:
        km = dp_.query_keymap()
        tus_ = [i * 8 + b for i, bayt in enumerate(km) for b in range(8) if bayt & (1 << b)]
        return tus_, dp_.screen().root.query_pointer().mask & _XX.Button1Mask
    finally:
        dp_.close()


COCUK = ("import sys, time; sys.path.insert(0, %r); from deskhand.arka_uc import sec, EKRAN; "
         "g = sec(arka_bayragi=True).girdi('takili-test'); "
         "g.gonder(EKRAN, None, 'mouseto 0.003 0.003', 'keydown leftshift', 'buttondown left'); "
         "print('basili', flush=True); time.sleep(60)") % KOK
if KW_2B:
    # KWin: Girdi'yi açan süreç SIGKILL'lenince deskhand-eis yardımcısı stdin EOF alır ve basılı HER ŞEYİ bırakır;
    # (yardımcının kendisi öldürülürse KWin tuşları bırakır, düğmeyi Eis.kurtar bırakır: test_arka_kwin.py).
    # Kanıt test penceresinin olay günlüğünden: OYUN ALANI'nda Shift + sol düğme basılıp süreç öldürülür.
    X_, Y_ = au.geometri(k)[:2]
    COCUK_K = ("import sys, time; sys.path.insert(0, %r); from deskhand.arka_uc import sec, EKRAN; "
               "g = sec(arka_bayragi=True).girdi('takili-test'); "
               "g.gonder(EKRAN, None, 'mouseto %.6f %.6f', 'click left'); time.sleep(0.2); "
               "g.gonder(EKRAN, None, 'keydown leftshift', 'buttondown left'); "
               "print('basili', flush=True); time.sleep(60)") % (KOK, (X_ + m_oyun["cx"] + 0.5) / W,
                                                                   (Y_ + m_oyun["cy"] + 0.5) / H)
    au.one_getir(k)
    n0 = len(log_satirlari(LOG))
    pc = subprocess.Popen([sys.executable, "-c", COCUK_K], stdout=subprocess.PIPE, text=True)
    hazir_ = pc.stdout.readline().strip()
    SHIFT = str(0x01000020)  # Qt::Key_Shift (olayın metni yok → kod yazılır)
    basildi = log_bekle(LOG, r"^tus_bas " + SHIFT + " ", 3, n0) and \
        bekle(lambda: [l.split()[0] for l in log_satirlari(LOG)[n0:] if l.startswith("fare_")][-1:] == ["fare_bas"], 3)
    n1 = len(log_satirlari(LOG))
    os.kill(pc.pid, signal.SIGKILL)
    pc.wait()
    kontrol("takılı (KWin): Girdi süreci SIGKILL → yardımcı (EOF) Shift + sol düğmeyi bıraktı",
            hazir_ == "basili" and basildi and log_bekle(LOG, r"^fare_birak sol ", 3, n1) is not None and
            log_bekle(LOG, r"^tus_birak " + SHIFT + " ", 3, n1) is not None, str(log_satirlari(LOG)[n0:][-6:]))
    g3 = au.girdi("takili-temizle")
    n0 = len(log_satirlari(LOG))
    g3.insan_ham("buttondown left")
    open(hata.dur_dosyasi(), "w").close()
    try:
        kontrol("insan_ham: DUR açıkken buttonup geçer, düğme bırakıldı",
                dur_kodu(g3.insan_ham, "buttonup left") is None and log_bekle(LOG, r"^fare_birak sol ", 3, n0))
        n1 = len(log_satirlari(LOG))
        kontrol("insan_ham: DUR açıkken buttondown → 13", dur_kodu(g3.insan_ham, "buttondown left") == 13 and
                log_bekle(LOG, r"^fare_bas sol ", 0.5, n1) is None)
    finally:
        os.remove(hata.dur_dosyasi())
        g3.kapat()
    pc = None
else:
    pc = subprocess.Popen([sys.executable, "-c", COCUK], stdout=subprocess.PIPE, text=True)
    hazir_ = pc.stdout.readline().strip()
    os.kill(pc.pid, signal.SIGKILL)
    pc.wait()
if not KW_2B:
    tus0, dugme0 = basililar()
    kontrol("takılı: SIGKILL sonrası Xvfb'de Shift (50) ve sol düğme basılı kaldı (sorun gerçek)",
            hazir_ == "basili" and 50 in tus0 and dugme0, f"{hazir_} {tus0} {dugme0}")
    g3 = au.girdi("takili-temizle")
    tus1, dugme1 = basililar()
    kontrol("takılı: yeni SanalGirdi basılı tuş/düğmeleri bıraktı", g3.takili[0] >= 1 and g3.takili[1] >= 1 and
            not tus1 and not dugme1, f"{g3.takili} {tus1} {dugme1}")
    g4 = au.girdi("takili-ikinci")
    kontrol("takılı: başka girdi nesnesi canlıyken temizlik YAPILMAZ (bilerek basılı tutulan bozulmasın)", g4.takili == (0, 0))
    g4.kapat()
    # Devral girdisi: DUR açıkken bırakma satırı yine gider (düğme basılı kalmasın), basma gitmez
    g3.insan_ham("mouseto 0.003 0.003")
    g3.insan_ham("buttondown left")
    open(hata.dur_dosyasi(), "w").close()
    try:
        kod_up = dur_kodu(g3.insan_ham, "buttonup left")
        kontrol("insan_ham: DUR açıkken buttonup geçer, düğme bırakıldı", kod_up is None and not basililar()[1])
        kontrol("insan_ham: DUR açıkken buttondown → 13", dur_kodu(g3.insan_ham, "buttondown left") == 13 and
                not basililar()[1])
    finally:
        os.remove(hata.dur_dosyasi())
        g3.kapat()

# ---------------------------------------------------------------- 3) ses: arka plan uygulaması ses sunucusuna ERİŞEMEZ
# (mikrofon gizliliği: çalma da kayıt da yok). Uygulama bwrap ad alanında gerçek runtime dizinini göremez; açık
# PULSE_SERVER/PIPEWIRE_REMOTE verse bile soket görünmez. Yalnız sıfır (sessiz) veri denenir.
if shutil.which("pactl"):
    SES_LOG = os.path.join(_yalitim.PAYLASIM, "ses.txt")
    kod_ = ("import os, subprocess\nr = subprocess.run(['pactl', 'info'], capture_output=True, text=True, timeout=10)\n"
            "r2 = subprocess.run(['pactl', 'info'], capture_output=True, text=True, timeout=10, env={**os.environ, "
            "'PULSE_SERVER': f'unix:/run/user/{os.getuid()}/pulse/native'})\n"
            f"open({SES_LOG!r}, 'w').write(f'{{r.returncode}} {{r2.returncode}} '"
            " + str(os.path.exists(f'/run/user/{os.getuid()}/pulse/native')) + ' '"
            " + str(os.path.exists(f'/run/user/{os.getuid()}/pipewire-0')))\n")
    ps_ = masaustu.baslat([sys.executable, "-c", kod_])
    ps_.wait(30)
    ses_s = open(SES_LOG).read().split() if os.path.exists(SES_LOG) else []
    kontrol("ses: arka plan uygulaması ses sunucusuna bağlanamaz (ortamla da, açık gerçek yolla da); soketler görünmez",
            len(ses_s) == 4 and ses_s[0] != "0" and ses_s[1] != "0" and ses_s[2:] == ["False", "False"], str(ses_s))

# ---------------------------------------------------------------- 4) CLI uçtan uca (gerçek güvenlik katmanıyla)


def deskhand(*a, sure=60):
    r = subprocess.run([sys.executable, "-m", "deskhand", "--arka", *a], capture_output=True, text=True, cwd=KOK,
                       timeout=sure)
    return r.returncode, r.stdout + r.stderr


kod, out = deskhand("bul", ".")
kontrol("cli: --arka bul → arka: kimliği", kod == 0 and k in out, f"{kod} {out}")
kod, out = deskhand("metin", k)
kontrol("cli: --arka metin → 'Kaydet' okundu", kod == 0 and "Kaydet" in out, f"{kod} {out[-300:]}")
n0 = len(log_satirlari(LOG))
t = time.monotonic()
kod, out = deskhand("-b", "SEKME", "metne-tikla", k, "Kaydet")  # başlık gözcü testinde 'BAŞKA SEKME' oldu
olcum["cli metne-tikla (süreç + OCR + tık)"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
kontrol("cli: --arka metne-tikla Kaydet → 'tık: Kaydet'", kod == 0 and log_bekle(LOG, r"^tık: Kaydet$", 3, n0),
        f"{kod} {out[-300:]}")
X, Y = au.geometri(k)[:2]
kod, out = deskhand("tikla", k, str(round(m_iptal["cx"])), str(round(m_eposta["cy"])))
kod2, out2 = deskhand("tus", k, "ctrl+a")
kod3, out3 = deskhand("yaz", k, "çığ ŞÖ")
kontrol("cli: --arka tikla + tus + yaz → eposta=çığ ŞÖ", (kod, kod2, kod3) == (0, 0, 0) and
        log_bekle(LOG, r"^eposta=çığ ŞÖ$", 3), f"{kod}/{kod2}/{kod3} {out3[-300:]}")
kod, out = deskhand("-b", "YANLIŞ-BAŞLIK", "tus", k, "a")
kontrol("cli: başlık kilidi tutmadı → 4", kod == 4, f"{kod} {out[-200:]}")
open(hata.dur_dosyasi(), "w").close()
kod, out = deskhand("tus", k, "a")
kontrol("cli: DUR açıkken → 13", kod == 13, f"{kod} {out[-200:]}")
os.remove(hata.dur_dosyasi())

# ---------------------------------------------------------------- 5) bellek + durdur + temizlik
try:
    r = subprocess.run(["systemctl", "--user", "show", d["kafes"], "-p", "MemoryCurrent", "-p", "MemoryPeak"],
                       capture_output=True, text=True).stdout
    v = dict(l.split("=", 1) for l in r.split())
    olcum["kafes belleği (masaüstü + Qt penceresi)"] = (f"{int(v['MemoryCurrent']) / 2 ** 20:.0f} MiB, tepe "
                                                         f"{int(v['MemoryPeak']) / 2 ** 20:.0f} MiB")
except (ValueError, KeyError):
    pass
cg = d["cgroup"]
from deskhand import bellek_bekcisi  # noqa: E402
bellek_bekcisi._durum_yaz(None, {"son_yeniden_olay": {"zaman": time.time(), "kimlik": d.get("kimlik")}})
bb_durum_vardi = os.path.exists(bellek_bekcisi._durum_yolu(None))
t = time.monotonic()
ok, notlar = masaustu.masaustu_durdur()
olcum["masaüstü kapanış"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
kontrol("durdur: kapatıldı, not yok", ok and not notlar, str(notlar))
kontrol("durdur: durum yok", masaustu.durum() is None and not os.path.exists(masaustu.durum_yolu()))
kontrol("durdur: bellek bekçisi durum dosyası (varsayılan masaüstü, RUNTIME_DIR) temizlendi (ABM-F1-R2 B5)",
        bb_durum_vardi and not os.path.exists(bellek_bekcisi._durum_yolu(None)))
kontrol("durdur: test penceresi süreci öldü", bekle(lambda: p1.poll() is not None, 3))
if KW:
    kontrol("durdur: XWayland soketleri + kilitleri ve Wayland soketi kalktı",
            not any(os.path.exists(y_) for n_ in (d["x_ana"], d["x_ana"] + 1)
                    for y_ in (f"/tmp/.X11-unix/X{n_}", f"/tmp/.X{n_}-lock")) and not os.path.exists(d["wayland_yol"]))
    kontrol("durdur: KWin süreci öldü", not masaustu._canli(d["pid"]["kwin"]))
else:
    kontrol("durdur: X soketi kalktı", not os.path.exists(f"/tmp/.X11-unix/X{d['no']}"))
kontrol("durdur: kafes boşaldı", not masaustu._kafes_surecleri(cg))
kontrol("durdur: hiçbir deskhand-sessiz ses çıkışı yok", masaustu._sink_modulu(f"deskhand-sessiz-{d.get('no')}") is None)
kontrol("durdur: özel D-Bus soketi/çalışma klasörü silindi", not os.path.exists(d["calisma"]))
kod, out = deskhand("bul", ".")
kontrol("cli: masaüstü kapalıyken --arka → 14", kod == 14, f"{kod} {out[-200:]}")
kontrol("durdur: ikinci durdur zararsız", masaustu.masaustu_durdur() == (False, []))

# ---------------------------------------------------------------- 5b) kafes KAPALIYKEN durdurma (D4)
os.environ["DESKHAND_SANAL_BELLEK"] = "0"
try:
    dk = masaustu.masaustu_baslat(openbox=False)
finally:
    os.environ.pop("DESKHAND_SANAL_BELLEK", None)
kontrol("kafessiz: masaüstü açıldı (kafes yok, uyarılı)", dk.get("kafes") is None and dk.get("cgroup") == "")
# çocuk + oturumdan kopan (setsid) torun: ortam işaretiyle bulunmalı
pk = masaustu.baslat(["sh", "-c", "sleep 61 & setsid sleep 62 & exec sleep 63"])
isaretli = bekle(lambda: len([p_ for p_ in masaustu._isaretli_surecler(dk)
                               if masaustu._komut_satiri(p_)[:1] == ["sleep"]]) >= 3 and
                 masaustu._isaretli_surecler(dk), 3)
uyku = [p_ for p_ in (isaretli or []) if masaustu._komut_satiri(p_)[:1] == ["sleep"]]
kontrol("kafessiz: başlatılan süreçler (setsid torun dahil) işaretle bulundu", len(uyku) == 3, str(isaretli))
kontrol("kafessiz: bu test süreci işaretli listede değil", os.getpid() not in (isaretli or []))
ok, notlar = masaustu.masaustu_durdur()
kontrol("kafessiz: durdur tüm uygulamaları kapattı (sonra boş çıkış kaldırıldı)",
        ok and bekle(lambda: not any(masaustu._canli(p_) for p_ in uyku), 3) and
        masaustu._sink_modulu((dk.get("ses") or {}).get("sink")) is None, f"{notlar} {uyku}")
pk.wait(3)

# ---------------------------------------------------------------- 5c) bayat durum dosyası + aynı numarada başka X (D6)
if KW:
    # KWin türü: OYNANMIŞ durum dosyası kullanıcının GERÇEK KWin'ini (canlı PID, gerçek Wayland soketi, gerçek veri
    # yolu) gösterse bile bağlantı kapısı (kwin_oturum.baglanti_denetle) Dur 14 verir; hiçbir araç bağlanmaz.
    gw_ = os.environ.get("WAYLAND_DISPLAY", "")
    grt = os.environ.get("XDG_RUNTIME_DIR", "")
    gpid = next((int(p_) for p_ in pidler("kwin_wayland") if gw_ and gw_ in masaustu._komut_satiri(p_)), None)
    if gpid and gw_:
        masaustu._durum_yaz({"surum": 1, "tur": "kwin", "kimlik": "sahte001", "ekran": gw_, "wayland": gw_,
                             "wayland_yol": os.path.join(grt, gw_), "calisma": grt, "boyut": [1920, 1080],
                             "dbus_adres": f"unix:path={grt}/bus", "pid": {"kwin": gpid}, "baslangic": 1,
                             "xwayland": os.environ.get("DISPLAY"), "kafes": None, "cgroup": "", "ses": None})
        try:
            au2 = sec(arka_bayragi=True)
            kontrol("oynanmış durum: gerçek KWin/soket/veri yolu → girdi, görüntü, pencere listesi, pano Dur 14",
                    type(au2).__name__ == "KwinArkaUc" and dur_kodu(au2.girdi, "bayat") == 14 and
                    dur_kodu(au2.goruntu) == 14 and dur_kodu(au2.pencereler) == 14 and dur_kodu(au2.pano_oku) == 14)
        finally:
            os.remove(masaustu.durum_yolu())
    else:
        kontrol("oynanmış durum testi: gerçek KWin bulunamadı (atlandı)", True)
no_ = masaustu.bos_ekran()
px = subprocess.Popen(["Xvfb", f":{no_}", "-nolisten", "tcp", "-screen", "0", "640x480x24"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL)
try:
    bekle(lambda: os.path.exists(f"/tmp/.X11-unix/X{no_}"), 5)
    masaustu._durum_yaz({"surum": 1, "no": no_, "ekran": f":{no_}", "boyut": [640, 480, 24], "pid": {"xvfb": 1},
                         "baslangic": 1, "kafes": None, "cgroup": "", "ses": None, "dbus_adres": ""})
    au2 = sec(arka_bayragi=True)
    kontrol("bayat durum: başka X sunucusu aynı numarada → girdi Dur 14 (bağlanmadı)",
            dur_kodu(au2.girdi, "bayat") == 14 and dur_kodu(au2.ekran_adi) == 14)
finally:
    try:
        os.remove(masaustu.durum_yolu())
    except OSError:
        pass
    px.terminate()
    px.wait(5)

# ---------------------------------------------------------------- 6) kullanıcının gerçek oturumu değişmedi
gercek1 = gercek_durum()
if gercek0 is not None:
    # kullanıcı film izlerken fareyi kendisi oynatabilir: değiştiyse, yeni konum bizim sanal ekrana gönderdiğimiz
    # hiçbir noktaya (±2 px) denk gelmemeli (denk gelseydi girdimiz gerçek ekrana sızmış olurdu)
    sizdi = gercek1[0] is not None and any(abs(gercek1[0][0] - a) <= 2 and abs(gercek1[0][1] - b) <= 2
                                           for a, b in GONDERILEN)
    if gercek0[0] != gercek1[0]:
        print(f"NOT: gerçek fare {gercek0[0]} → {gercek1[0]} (kullanıcı oynattı; gönderdiğimiz noktalarla eşleşme: "
              f"{'VAR' if sizdi else 'yok'})")
    kontrol("GERÇEK oturum: fare bizim gönderdiğimiz bir noktaya gitmedi", not sizdi, f"{gercek0[0]} → {gercek1[0]}")
    # Etkin pencere kullanıcının kendi işiyle değişebilir (test sürerken pencere değiştirdi): yalnız YENİ etkin pencere
    # bu testin başlattığı bir sürece aitse (test dizini / ad alanı izi) sızıntıdır.
    def _bizim_pencere(wid):
        pid = subprocess.run(["kdotool", "getwindowpid", wid], capture_output=True, text=True).stdout.strip()
        if not pid.isdigit():
            return False
        try:
            iz = open(f"/proc/{pid}/cmdline", "rb").read() + open(f"/proc/{pid}/environ", "rb").read()
        except OSError:
            return False
        return b"deskhand-test-" in iz or b"DESKHAND_AD_ALANI=1" in iz or b"tests/yardimci" in iz
    degisti = gercek0[1] != gercek1[1]
    if degisti:
        print(f"NOT: gerçek etkin pencere {gercek0[1]} → {gercek1[1]} (kullanıcı değiştirmiş olabilir)")
    kontrol("GERÇEK oturum: etkin pencere bu testin bir penceresine geçmedi",
            not (degisti and gercek1[1] and _bizim_pencere(gercek1[1])), f"{gercek0[1]} → {gercek1[1]}")
def test_izi_yok(yol):
    """Gerçek günlük/işaret dosyalarında bu testin izi (test pencere başlıkları, test geçici dizini) yok mu."""
    yol = os.path.expanduser(yol)
    for d, _, dosyalar in os.walk(yol):
        for f in dosyalar:
            if CANLI_DOSYA.match(f):
                try:
                    metin = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                if any(iz in metin for iz in TEST_IZLERI):
                    return False
    return True


for y in GERCEK_YOLLAR:
    kontrol(f"gerçek yol yazılmadı: {y}", agac_ozeti(y) == ozet0[y])
    kontrol(f"gerçek günlüklerde bu testin izi yok: {y}", test_izi_yok(y))
anahtarlik1 = {a: pidler(a) for a in ANAHTARLIK}
kontrol("anahtarlık: ksecretd/kwalletd/gnome-keyring süreçleri aynı (yeni örnek yok)", anahtarlik0 == anahtarlik1,
        f"{anahtarlik0} → {anahtarlik1}")

print("\nölçümler:")
for a_, v_ in olcum.items():
    print(f"  {a_}: {v_}")
print(f"\n{gecen}/{toplam} sanal arka uç testi geçti")
sys.exit(0 if gecen == toplam else 1)
