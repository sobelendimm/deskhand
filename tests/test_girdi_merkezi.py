"""Girdi merkezi testleri (EKRANSIZ: gerçek dotool/uinput KULLANILMAZ, ekrana girdi gitmez).

PATH'in başına SAHTE bir `dotool` konur: kurulumu (aygıtın görünmesi) taklit eder, stdin satırlarını kayıt dosyasına
"<pid> <satır>" olarak yazar. Gerçek dotool bulunursa test HİÇBİR ŞEY çalıştırmadan durur.

Çalıştır:  python3 tests/test_girdi_merkezi.py"""
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

SAHTE = os.path.join(_yalitim.GECICI, "sahte-bin")
AYGIT = os.path.join(_yalitim.GECICI, "sahte-aygitlar")
KAYIT = os.path.join(_yalitim.GECICI, "sahte-dotool.log")
os.makedirs(SAHTE, exist_ok=True)
with open(os.path.join(SAHTE, "dotool"), "w") as f:
    f.write(f"""#!{sys.executable}
import os, sys, time
if "--list-keys" in sys.argv:
    print("a 30"); sys.exit(0)
time.sleep(float(os.environ.get("SAHTE_KURULUM", "0.4")))  # gerçek dotool aygıt kurulumu ≈0,4 sn + 0,25 bekleme
with open(os.environ["SAHTE_AYGIT"], "a") as f:
    f.write('N: Name="dotool relative pointer"\\n')
for satir in sys.stdin:
    satir = satir.rstrip("\\n")
    with open(os.environ["SAHTE_KAYIT"], "a") as f:
        f.write(f"{{os.getpid()}} {{os.environ.get('DOTOOL_XKB_LAYOUT', '')}} {{satir}}\\n")
    if satir.startswith("type UYARI"):
        print("sahte uyarı: " + satir, file=sys.stderr, flush=True)
""")
os.chmod(os.path.join(SAHTE, "dotool"), 0o755)
open(AYGIT, "w").close()
os.environ.update(PATH=SAHTE + os.pathsep + os.environ.get("PATH", ""), SAHTE_AYGIT=AYGIT, SAHTE_KAYIT=KAYIT)
if shutil.which("dotool") != os.path.join(SAHTE, "dotool"):
    print("KALDI  sahte dotool PATH'te ilk değil: gerçek dotool çalışabilirdi, test durduruldu")
    sys.exit(2)

from deskhand import girdi_merkezi as GM, guvenlik, hata  # noqa: E402
from deskhand import mesgul as _mesgul  # noqa: E402
from deskhand.arka_uc import kde  # noqa: E402

_mesgul.ekran_korumasi = lambda *a, **k: None  # gerçek masaüstü (film/oyun) okunmasın
_mesgul.karar_bekliyor = lambda: False


def _sayac():
    try:
        with open(AYGIT) as f:
            return f.read().count('Name="dotool relative pointer"')
    except OSError:
        return 0


kde._goreli_imlec_sayisi = _sayac  # /proc/bus/input/devices yerine sahte aygıt listesi

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def kayit():
    try:
        with open(KAYIT) as f:
            return [l.rstrip("\n").split(" ", 2) for l in f if l.strip()]
    except OSError:
        return []


def kayit_bekle(kosul, sure=2.0):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if kosul(kayit()):
            return True
        time.sleep(0.01)
    return kosul(kayit())


def satirlar(pid=None):
    return [s for p, _d, s in kayit() if pid is None or p == str(pid)]


def kod_al(f, *a):
    try:
        f(*a)
        return 0
    except hata.Dur as x:
        return x.kod


class SahteAU:
    def fare(self):
        return (None, None, "")

    def baslik(self, k):
        return "test penceresi"


class SahteEtk:
    def __init__(self):
        self.kendi = []

    def kendi_girdi(self, bas, son):
        self.kendi.append((bas, son))

    def insan(self, beri):
        return False

    def calisiyor(self):
        return True

    def kapat(self):
        pass


def istemci():
    c = GM.Istemci.baglan(("tr", ""))
    assert c is not None, "merkeze bağlanılamadı"
    c.hazir_bekle(5)
    return c


def gonder_israrla(c, s):
    while True:
        try:
            return c.gonder(s)
        except GM.Mesgul as m:
            time.sleep(min(m.sn, 0.02))


def merkez_hazir(m, sure=5.0):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if m._hazir.is_set():
            return True
        time.sleep(0.01)
    return False


AU = SahteAU()
denetimler = []


def denetle(k, desen):
    denetimler.append((k, desen))


# ---------------------------------------------------------------- 1) merkez YOKKEN: kde Girdi kendi dotool'una düşer
t = time.monotonic()
g = kde.Girdi(AU, "test-kendi", etk=SahteEtk(), denetle=denetle)
kontrol("merkez yok: Girdi kendi dotool'unu açtı (merkez bağlantısı yok)", g.merkez is None and g.p is not None)
g.gonder("{a}", None, "key a")
once_sn = time.monotonic() - t
g.kapat()
kontrol("merkez yok: satır Girdi'nin kendi dotool'una gitti", satirlar(g.p.pid) == ["key a"], str(kayit()))
kontrol(f"gecikme ÖNCE (kendi dotool, sahte kurulum 0,4+0,25 sn): {once_sn * 1000:.0f} ms ≈ 650 ms",
        0.55 <= once_sn <= 1.2, f"{once_sn:.3f}")

# eski panelden kalmış (dinleyicisi olmayan) soket dosyası → bağlanmaz, düşer
yol = GM.soket_yolu()
os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
olu = socket.socket(socket.AF_UNIX)
eski_umask = os.umask(0o177)
olu.bind(yol)
os.umask(eski_umask)
olu.close()
kontrol("ölü soket dosyası: Istemci.baglan → None (kendi yoluna düşer)", GM.Istemci.baglan(("tr", "")) is None)

# ---------------------------------------------------------------- 2) merkez: başlat, izinler, el sıkışma
m = GM.GirdiMerkezi(duzen=("tr", "")).baslat()
kontrol("merkez: ölü soket dosyası silinip yenisi açıldı", m.calisiyor())
st, std = os.stat(yol), os.stat(os.path.dirname(yol))
kontrol("merkez: soket 0600, dizin 0700", stat.S_IMODE(st.st_mode) == 0o600 and stat.S_IMODE(std.st_mode) == 0o700,
        f"{oct(st.st_mode)} {oct(std.st_mode)}")
kontrol("merkez: dotool hazır (sahte kurulum bekleniyor)", merkez_hazir(m))
try:
    GM.GirdiMerkezi(duzen=("tr", "")).baslat()
    kontrol("merkez: ikinci merkez aynı sokette açılmaz", False)
except OSError:
    kontrol("merkez: ikinci merkez aynı sokette açılmaz", True)

c = istemci()
kontrol("el sıkışma: tamam, dotool pid'i merkezinki", c.dotool_pid == m.dotool_pid(), f"{c.dotool_pid} {m.dotool_pid()}")
c.kapat()

# ---------------------------------------------------------------- 3) kde Girdi merkez yolu + gecikme
etk = SahteEtk()
denetimler.clear()
t = time.monotonic()
g = kde.Girdi(AU, "test-merkez", etk=etk, denetle=denetle)
g.gonder("{a}", "desen", "key b", "key c")
sonra_sn = time.monotonic() - t
kontrol("merkez var: Girdi dotool AÇMADI, merkeze bağlandı", g.p is None and g.merkez is not None)
kontrol("merkez var: satırlar merkezin dotool'una gitti", kayit_bekle(lambda k: [s for p, _d, s in k
        if p == str(m.dotool_pid())][-2:] == ["key b", "key c"]), str(kayit()[-4:]))
kontrol("merkez var: istemci denetimleri aynen (denetle çağrıldı)", denetimler == [("{a}", "desen")])
kontrol("merkez var: kendi girdi penceresi istemcide kaydedildi (insan.KENDI_PAY)", len(etk.kendi) == 1
        and etk.kendi[0][1] > etk.kendi[0][0])
kontrol(f"gecikme SONRA (merkez): {sonra_sn * 1000:.1f} ms (ilk satıra kadar)", sonra_sn < 0.1, f"{sonra_sn:.3f}")
g.kapat()
print(f"       ölçüm: kendi dotool {once_sn * 1000:.0f} ms → merkez {sonra_sn * 1000:.1f} ms")

# ---------------------------------------------------------------- 4) geçersiz satır, ayar satırları
c = istemci()
try:
    c.gonder(["rm -rf /"])
    kontrol("geçersiz fiil → hata 1", False)
except GM.MerkezHatasi as e:
    kontrol("geçersiz fiil → hata 1", e.kod == 1, str(e.kod))
c.kapat()

# ---------------------------------------------------------------- 5) atomik parti + iki istemci karışmaz
PARTI, TUR = 40, 6


def yaz_isci(no, c):
    for tur in range(TUR):
        gonder_israrla(c, [f"wheel {no * 100000 + tur * 1000 + i}" for i in range(PARTI)])


ca, cb = istemci(), istemci()
isler = [threading.Thread(target=yaz_isci, args=(n, c_)) for n, c_ in ((1, ca), (2, cb))]
for x in isler:
    x.start()
for x in isler:
    x.join()
kayit_bekle(lambda k: sum(1 for _p, _d, s in k if s.startswith("wheel ") and len(s) > 10) >= 2 * PARTI * TUR)
tekerler = [int(s.split()[1]) for s in satirlar(m.dotool_pid()) if s.startswith("wheel ") and len(s) > 10]
bloklar = [tekerler[i:i + PARTI] for i in range(0, len(tekerler), PARTI)]
atomik = len(tekerler) == 2 * PARTI * TUR and all(
    len({v // 1000 for v in b}) == 1 and b == sorted(b) for b in bloklar)
kontrol("iki istemci: her partinin satırları bitişik (atomik, karışmadı)", atomik, f"{len(tekerler)} satır")
ca.kapat()
cb.kapat()

# ---------------------------------------------------------------- 6) DUR: basma reddi, bırakma serbest
c = istemci()
guvenlik.dur_ac("cli")
try:
    try:
        c.gonder(["key a"])
        kontrol("DUR: merkez basma satırını reddetti (13)", False)
    except GM.MerkezHatasi as e:
        kontrol("DUR: merkez basma satırını reddetti (13)", e.kod == 13, str(e.kod))
    try:
        c.gonder(["keyup a", "buttonup left", "typedelay 4"])
        kontrol("DUR: bırakma + ayar satırları geçti", True)
    except GM.MerkezHatasi as e:
        kontrol("DUR: bırakma + ayar satırları geçti", False, str(e.kod))
    try:
        c.gonder(["keyup a", "click left"])
        kontrol("DUR: içinde basma olan parti BÜTÜNÜYLE reddedildi", False)
    except GM.MerkezHatasi as e:
        kontrol("DUR: içinde basma olan parti BÜTÜNÜYLE reddedildi", e.kod == 13 and "click left" not in satirlar())
    g = kde.Girdi(AU, "test-dur", etk=SahteEtk(), denetle=denetle)
    kontrol("DUR: kde Girdi.gonder → 13 (istemci tarafı)", kod_al(g.gonder, "{a}", None, "key z") == 13)
    g.zorla("keyup z")
    kontrol("DUR: kde Girdi.zorla merkezden geçti", kayit_bekle(lambda k: k and k[-1][2] == "keyup z"))
    g.kapat()
    # istemci denetimi atlanmış olsa bile (yarış) merkez durdurur → istemci 13 döner
    g = kde.Girdi(AU, "test-dur2", etk=SahteEtk(), denetle=denetle)
    g.hazir = True
    g.merkez.hazir_bekle(5)
    gercek_dd = kde.dur_denetle
    kde.dur_denetle = lambda: None
    try:
        kontrol("DUR yarışı: istemci denetimi kaçırsa da merkez reddeder → Dur 13",
                kod_al(g.gonder, "{a}", None, "key y") == 13 and "key y" not in satirlar())
    finally:
        kde.dur_denetle = gercek_dd
    g.kapat()
finally:
    guvenlik.dur_kapat("cli")
c.kapat()

# ---------------------------------------------------------------- 7) istemci SIGKILL → basılı kalanlar bırakılır
ISTEMCI_KOD = """
import sys, time
from deskhand import girdi_merkezi as GM
c = GM.Istemci.baglan(("tr", ""))
c.hazir_bekle(5)
c.gonder(sys.argv[1:])
print("hazir", flush=True)
time.sleep(60)
"""


def olen_istemci(*s):
    p = subprocess.Popen([sys.executable, "-c", ISTEMCI_KOD, *s], stdout=subprocess.PIPE, text=True,
                         cwd=_yalitim.KOK)
    kontrol_satir = p.stdout.readline().strip()
    return p, kontrol_satir


p, hz = olen_istemci("keydown leftshift+a", "buttondown left")
kontrol("SIGKILL: istemci tuş ve düğme bastı", hz == "hazir" and kayit_bekle(
    lambda k: [s for _p, _d, s in k][-2:] == ["keydown leftshift+a", "buttondown left"]))
os.kill(p.pid, signal.SIGKILL)
p.wait()
ok = kayit_bekle(lambda k: {"keyup leftshift", "keyup a", "buttonup left"} <= {s for _p, _d, s in k[-3:]})
kontrol("SIGKILL: merkez basılı her şeyi bıraktı (keyup leftshift, keyup a, buttonup left)", ok, str(kayit()[-4:]))

# iki bağlantı aynı tuşu basılı tutuyorsa: biri ölünce tuş bırakılmaz, ikincisi kapanınca bırakılır
c = istemci()
c.gonder(["keydown leftctrl"])
p, hz = olen_istemci("keydown leftctrl")
n0 = len(kayit())
os.kill(p.pid, signal.SIGKILL)
p.wait()
time.sleep(0.2)
kontrol("ortak tuş: bir bağlantı ölünce öbürünün tuttuğu tuş bırakılmadı",
        "keyup leftctrl" not in [s for _p, _d, s in kayit()[n0:]])
c.kapat()
kontrol("ortak tuş: son tutan da kapanınca bırakıldı",
        kayit_bekle(lambda k: "keyup leftctrl" in [s for _p, _d, s in k[n0:]]))

# ---------------------------------------------------------------- 8) DUR açılınca tüm bağlantıların basılıları bırakılır
c1, c2 = istemci(), istemci()
c1.gonder(["keydown q"])
c2.gonder(["buttondown right"])
n0 = len(kayit())
guvenlik.dur_ac("cli")
try:
    ok = kayit_bekle(lambda k: {"keyup q", "buttonup right"} <= {s for _p, _d, s in k[n0:]}, 1.0)
    kontrol("DUR açıldı: canlı bağlantıların basılıları bırakıldı (≤ 1 sn)", ok, str(kayit()[n0:]))
finally:
    guvenlik.dur_kapat("cli")
c1.kapat()
c2.kapat()

# DUR açıldığında kuyrukta girdi sürüyorsa dotool yeniden başlar (kuyruk düşer)
c = istemci()
eski_pid = m.dotool_pid()
c.gonder(["typehold 200", "type uzunmetin"])
guvenlik.dur_ac("cli")
try:
    bitis = time.monotonic() + 1.0
    while m.dotool_pid() == eski_pid and time.monotonic() < bitis:
        time.sleep(0.01)
    kontrol("DUR + kuyruk sürüyor: dotool yeniden başlatıldı (kuyruk düşer, aygıt yok olur)",
            m.dotool_pid() != eski_pid)
finally:
    guvenlik.dur_kapat("cli")
merkez_hazir(m)
try:
    c.gonder(["key a"])
    kontrol("DUR + yeniden başlama: eski bağlantı reddedilir (9)", False)
except GM.MerkezHatasi as e:
    kontrol("DUR + yeniden başlama: eski bağlantı reddedilir (9)", e.kod == 9, str(e.kod))
c.kapat()

# ---------------------------------------------------------------- 9) meşgul: başka bağlantının kuyruğu sürerken
merkez_hazir(m)
ca, cb = istemci(), istemci()
ca.gonder(["typehold 60", "type abcdefghij"])  # ≈0,7 sn kuyruk
try:
    cb.gonder(["key a"])
    kontrol("meşgul: başka bağlantının kuyruğu sürerken basma → Mesgul", False)
except GM.Mesgul as e:
    kontrol("meşgul: başka bağlantının kuyruğu sürerken basma → Mesgul", e.sn > 0.1, str(e.sn))
try:
    cb.gonder(["keyup a"])
    kontrol("meşgul: bırakma satırı bekletilmez", True)
except GM.Mesgul:
    kontrol("meşgul: bırakma satırı bekletilmez", False)
ca.gonder(["type b"])
kontrol("meşgul: kuyruğun sahibi beklemeden ekler (kendi sırası)", True)
cb.kapat()
denetimler.clear()
g = kde.Girdi(AU, "test-mesgul", etk=SahteEtk(), denetle=denetle)
t = time.monotonic()
g.gonder("{a}", None, "key m")
sure = time.monotonic() - t
kontrol("meşgul: kde Girdi bekledi, denetimleri YENİDEN yaptı, sonra gönderdi",
        len(denetimler) >= 2 and sure > 0.2 and kayit_bekle(lambda k: k[-1][2] == "key m"),
        f"{len(denetimler)} denetim, {sure:.2f} sn")
g.kapat()
t = time.monotonic()
uy = ca.bekle()
kontrol("bekle: bağlantının girdisi bitince döner", True)
ca.kapat()

# bekle uyarıları + ayarların bağlantı başına korunması
c = istemci()
c.gonder(["typedelay 7", "type UYARI deneme"])
uy = c.bekle()
kontrol("bekle: dotool uyarısı istemciye döndü", any("sahte uyarı" in u for u in uy), str(uy))
c2 = istemci()
n0 = len(kayit())
c2.gonder(["type x"])
kontrol("ayar: yeni bağlantıya dotool varsayılanı geri verildi (typedelay 2)",
        kayit_bekle(lambda k: [s for _p, _d, s in k[n0:]][:2] == ["typedelay 2", "type x"]), str(kayit()[n0:]))
c2.kapat()
c.kapat()

# kopan bağlantının kuyruğu sürüyorsa dotool yeniden başlar (denetimsiz girdi sürmesin)
merkez_hazir(m)
p = subprocess.Popen([sys.executable, "-c", ISTEMCI_KOD, "typehold 200", "type cokuzunbirmetin"],
                     stdout=subprocess.PIPE, text=True, cwd=_yalitim.KOK)
p.stdout.readline()
eski_pid = m.dotool_pid()
os.kill(p.pid, signal.SIGKILL)
p.wait()
bitis = time.monotonic() + 1.0
while m.dotool_pid() == eski_pid and time.monotonic() < bitis:
    time.sleep(0.01)
kontrol("SIGKILL + kuyruk sürüyor: dotool yeniden başlatıldı (kalan yazı düşer)", m.dotool_pid() != eski_pid)
merkez_hazir(m)

# ---------------------------------------------------------------- 10) başka kullanıcı / izin denetimi
m.izinli_uid = os.getuid() + 4242  # SO_PEERCRED uid'i "başka kullanıcı" sayılsın
try:
    c = GM.Istemci.baglan(("tr", ""))
    try:
        c.hazir_bekle(2)
        kontrol("SO_PEERCRED: başka kullanıcı reddedildi", False)
    except GM.MerkezHatasi:
        kontrol("SO_PEERCRED: başka kullanıcı reddedildi", True)
    c.kapat()
    g = kde.Girdi(AU, "test-yabanci", etk=SahteEtk(), denetle=denetle)
    g.gonder("{a}", None, "key k")
    kontrol("SO_PEERCRED reddi: kde Girdi kendi dotool'una düştü",
            g.merkez is None and g.p is not None and satirlar(g.p.pid) == ["key k"])
    g.kapat()
finally:
    m.izinli_uid = os.getuid()
gercek_es = GM.es_kimligi
GM.es_kimligi = lambda s: (1, os.getuid() + 4242, 1)  # sunucu başka kullanıcıymış gibi
try:
    kontrol("istemci: sunucu başka kullanıcıysa bağlanmaz", GM.Istemci.baglan(("tr", "")) is None)
finally:
    GM.es_kimligi = gercek_es
os.chmod(yol, 0o644)
try:
    kontrol("istemci: soket 0600 değilse bağlanmaz", GM.Istemci.baglan(("tr", "")) is None)
finally:
    os.chmod(yol, 0o600)

# ---------------------------------------------------------------- 11) klavye düzeni farkı
c = istemci()
c2 = GM.Istemci.baglan(("us", ""))
try:
    c2.hazir_bekle(3)
    kontrol("düzen farkı + merkez kullanımda: el sıkışma reddedildi", False)
except GM.MerkezHatasi as e:
    kontrol("düzen farkı + merkez kullanımda: el sıkışma reddedildi", e.kod == 9)
c2.kapat()
c.kapat()
time.sleep(0.05)
c2 = GM.Istemci.baglan(("us", ""))
c2.hazir_bekle(5)
c2.gonder(["type y"])
kontrol("düzen farkı + merkez boşta: dotool yeni düzenle yeniden açıldı",
        kayit_bekle(lambda k: k[-1][1:] == ["us", "type y"]), str(kayit()[-1:]))
c2.kapat()

# ---------------------------------------------------------------- 12) panel: başlat / durdur → dotool kapanır
eski_p = m._p
m.durdur()
kontrol("durdur: soket silindi, dotool kapandı", not os.path.exists(yol) and eski_p.poll() is not None)
g = kde.Girdi(AU, "test-sonra", etk=SahteEtk(), denetle=denetle)
kontrol("durdur sonrası: kde Girdi kendi yoluna döndü", g.merkez is None and g.p is not None)
g.kapat()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from deskhand.gui.panel import Panel  # noqa: E402
pm = Panel._merkez_baslat()
kontrol("panel: _merkez_baslat merkezi açtı", pm is not None and pm.calisiyor() and os.path.exists(yol))
merkez_hazir(pm)
ep = pm._p
pm.durdur()
kontrol("panel: durdurunca soket silindi, dotool kapandı", not os.path.exists(yol) and ep.poll() is not None)

print(f"\n{gecen}/{toplam} girdi merkezi testi geçti")
sys.exit(0 if gecen == toplam else 1)
