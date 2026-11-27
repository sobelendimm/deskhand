"""Onay protokolü testleri (EKRANSIZ; Qt yok): deskhand/onay.py'nin iki tarafı (iste ↔ bekleyenler/yanitla/temizle).
Panel, test sürecinin kendisi (panel_kaydet) ve bir iş parçacığı yanıtlayıcısıyla taklit edilir. RUNTIME_DIR geçici.

Çalıştır:  python3 tests/test_onay.py"""
import json, os, stat, subprocess, sys, threading, time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from deskhand import guvenlik, hata, onay, yollar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def dosyalar():
    try:
        return sorted(f for f in os.listdir(onay.dizin()) if f != "kanal.sock")  # kanal: panel yaşadıkça durur
    except OSError:
        return []


def yanitlayici(karar, gecikme=0.2, kontrol_f=None):
    """Bekleyen ilk isteği `gecikme` sonra `karar` ile yanıtlayan iş parçacığı. → (iş parçacığı, görülen istekler)"""
    gorulen = []

    def calis():
        son = time.monotonic() + 5
        while time.monotonic() < son:
            b = onay.bekleyenler()
            if b:
                gorulen.append(b[0])
                if kontrol_f:
                    kontrol_f(b[0])
                time.sleep(gecikme)
                if karar:
                    gorulen.append(gosterip_yanitla(b[0], karar))
                return
            time.sleep(0.02)

    t = threading.Thread(target=calis, daemon=True)
    t.start()
    return t, gorulen


def gosterip_yanitla(b, karar):
    """The panel dialog answers what it SHOWED: b = the request dict it was built from (or an id: read it now)."""
    if isinstance(b, str):
        b = onay.istek_oku(onay.istek_yolu(b)) or {"id": b}
    try:
        return onay.yanitla(b["id"], karar, gosterilen=b.get("_iz"))
    except TypeError:  # d78c8d6: the dialog passed only the id
        return onay.yanitla(b["id"], karar)


_ISTEYENLER = []


def isteyen_bagli(i):
    """An honest requester on the channel: `bekle <id> <sha256 of the bytes it wrote>` (review INC3 B3), the
    connection stays open (the decision comes on it)."""
    import hashlib
    import socket
    with open(onay.istek_yolu(i), "rb") as f:
        iz = hashlib.sha256(f.read()).hexdigest()
    c = socket.socket(socket.AF_UNIX)
    c.connect(onay.kanal_yolu())
    c.sendall(f"bekle {i} {iz}\n".encode())
    c.settimeout(3)
    _ISTEYENLER.append(c)
    son = time.monotonic() + 2
    while onay._KANAL is not None and onay._KANAL.istek_izi(i) is None and time.monotonic() < son:
        time.sleep(0.01)
    return c


def gunluk_satirlari():
    yol = os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))
    try:
        return open(yol).read().splitlines()
    except OSError:
        return []


# 1) panel kapalı → hemen red
t0 = time.monotonic()
s = onay.iste_sonuc("tıkla 'Satın al'", "Mağaza", sure=30)
kontrol("panel yok → hemen red", not s.izin and s.neden == "panel-yok" and time.monotonic() - t0 < 0.5, str(s))
kontrol("panel yok mesajı sözleşmedeki metin", s.mesaj == "Deskhand paneli kapalı, onay alınamadı")
kontrol("panel yok → istek dosyası bırakılmaz", not [f for f in dosyalar() if f.startswith("istek-")])
kontrol("sonuç günlüğe yazılır (onay panel-yok)", any("onay panel-yok | [Mağaza] | tıkla 'Satın al'" in l
                                                     for l in gunluk_satirlari()), str(gunluk_satirlari()[-2:]))
kontrol("iste() bool döner", onay.iste("x", "y", sure=5) is False)

# 2) panel canlılığı
onay.panel_kaydet()
kontrol("panel_kaydet → panel_canli", onay.panel_canli() and onay.panel_pid() == os.getpid())
st = os.stat(yollar.runtime_dir())
kontrol("çalışma dizini 0700", stat.S_IMODE(st.st_mode) == 0o700, oct(st.st_mode))
kontrol("onay dizini 0700", stat.S_IMODE(os.stat(onay.dizin()).st_mode) == 0o700)
p = subprocess.Popen([sys.executable, "-c", "pass"])
p.wait()
onay.panel_kaydet(p.pid)
kontrol("ölü PID'li panel.pid → panel kapalı", not onay.panel_canli())
onay.panel_kaydet()
d = json.load(open(onay.panel_pid_yolu()))
d["baslangic"] = "1"
json.dump(d, open(onay.panel_pid_yolu(), "w"))
kontrol("PID yeniden kullanımı (başlangıç zamanı farklı) → panel kapalı", not onay.panel_canli())
open(onay.panel_pid_yolu(), "w").write("bozuk")
kontrol("bozuk panel.pid → panel kapalı", not onay.panel_canli())
onay.panel_kaydet()

# 3) izin
alanlar = {}


def alan_denetle(b):
    alanlar.update(b)
    yol = onay.istek_yolu(b["id"])
    alanlar["_mod"] = stat.S_IMODE(os.stat(yol).st_mode)
    alanlar["_ham"] = json.load(open(yol))


from PIL import Image  # noqa: E402

t, gorulen = yanitlayici("izin", kontrol_f=alan_denetle)
s = onay.iste_sonuc("tıkla 'Siparişi onayla'", "Firefox — Ödeme", "hassas düğme", masaustu="arka", sure=10,
                    goruntu=Image.new("RGB", (40, 20), (200, 30, 30)))
t.join(2)
kontrol("insan izin verdi → True", s.izin and s.neden == "izin", str(s))
ham = alanlar.get("_ham", {})
kontrol("istek alanları (id, eylem, hedef, ayrinti, masaustu, zaman, son_zaman, pid)",
        set(ham) >= {"id", "eylem", "hedef", "ayrinti", "masaustu", "zaman", "son_zaman", "pid"} and
        ham["masaustu"] == "arka" and ham["pid"] == os.getpid() and 9 < ham["son_zaman"] - ham["zaman"] <= 10.01, str(ham))
kontrol("istek dosyası 0600", alanlar.get("_mod") == 0o600, oct(alanlar.get("_mod", 0)))
kontrol("görüntü istekte (dosya var)", bool(alanlar.get("goruntu")) and alanlar["goruntu"].endswith(".png"))
kontrol("yanıtlayıcı yazabildi", gorulen[-1] is True)
kontrol("tek kullanımlık: istek, yanıt ve görüntü silindi", dosyalar() == [], str(dosyalar()))
kontrol("izin sonucu günlükte (arka)", any("onay izin | arka sanal [Firefox — Ödeme]" in l for l in gunluk_satirlari()))

# 4) red
t, _ = yanitlayici("red")
s = onay.iste_sonuc("ac", "steam", sure=10)
t.join(2)
kontrol("insan reddetti → False (red)", not s.izin and s.neden == "red", str(s))
kontrol("red sonrası dosya kalmadı", dosyalar() == [], str(dosyalar()))

# 5) süre
t0 = time.monotonic()
s = onay.iste_sonuc("x", "y", sure=1)
gecen_sure = time.monotonic() - t0
kontrol("yanıt yok → süre dolunca red", not s.izin and s.neden == "sure" and 0.9 < gecen_sure < 2.0,
        f"{s} {gecen_sure:.2f}")
kontrol("süre sonrası istek silindi", dosyalar() == [], str(dosyalar()))

# 6) tek kullanım: ikinci yanıt yazılamaz; süresi geçmiş isteğe izin yazılamaz
sonuclar = {}


def ikili(b):
    sonuclar["ilk"] = onay.yanitla(b["id"], "red")
    sonuclar["ikinci"] = gosterip_yanitla(b, "izin")


t, _ = yanitlayici(None, kontrol_f=ikili)
s = onay.iste_sonuc("x", "y", sure=5)
t.join(2)
kontrol("ilk yanıt yazılır, ikincisi YAZILMAZ (izin red'i ezemez)",
        sonuclar.get("ilk") is True and sonuclar.get("ikinci") is False and not s.izin, f"{sonuclar} {s}")
kontrol("var olmayan isteğe yanıt yok", onay.yanitla("0" * 32, "izin") is False)
kontrol("geçersiz kimlik (yol kaçışı) reddedilir", onay.yanitla("../../dur", "izin") is False)
kontrol("geçersiz karar reddedilir", onay.yanitla("0" * 32, "evet") is False)

# süresi geçmiş istek (elle yazılmış): izin yazılamaz, bekleyenlerde görünmez, temizle siler
eski = "e" * 32
onay._yaz_atomik(onay.istek_yolu(eski), {"id": eski, "eylem": "a", "hedef": "b", "ayrinti": "", "masaustu": "ekran",
                                       "zaman": time.time() - 200, "son_zaman": time.time() - 100, "pid": os.getpid()})
kontrol("süresi geçmiş isteğe İZİN yazılmaz", gosterip_yanitla(eski, "izin") is False)
kontrol("süresi geçmiş istek bekleyenlerde yok", not onay.bekleyenler())
kontrol("temizle süresi geçmiş isteği siler", f"istek-{eski}.json" in onay.temizle() and dosyalar() == [], str(dosyalar()))

# isteyeni ölmüş istek
olu = "d" * 32
onay._yaz_atomik(onay.istek_yolu(olu), {"id": olu, "eylem": "a", "hedef": "b", "ayrinti": "", "masaustu": "ekran",
                                      "zaman": time.time(), "son_zaman": time.time() + 100, "pid": p.pid})
kontrol("isteyeni ölmüş istek bekleyenlerde yok", not onay.bekleyenler())
onay.temizle()
kontrol("temizle isteyeni ölmüş isteği siler", dosyalar() == [], str(dosyalar()))

# ad/kimlik uyuşmazlığı ve bozuk istek
open(os.path.join(onay.dizin(), f"istek-{'b' * 32}.json"), "w").write('{"id": "' + "c" * 32 + '", "son_zaman": 1e12}')
open(os.path.join(onay.dizin(), f"istek-{'f' * 32}.json"), "w").write("{bozuk")
kontrol("adı kimliğiyle uyuşmayan / bozuk istek yok sayılır", not onay.bekleyenler())
onay.temizle()
kontrol("temizle bozuk istekleri siler", dosyalar() == [], str(dosyalar()))

# 7) sahte yanıt: kaynak "arayuz" değil ya da panel PID'i uymuyor → red
def sahte(b, alan):
    y = {"id": b["id"], "karar": "izin", "kaynak": "arayuz", "zaman": time.time(), "panel_pid": os.getpid()}
    y.update(alan)
    onay._yaz_atomik(onay.yanit_yolu(b["id"]), y)


for ad, alan in (("kaynak 'cli'", {"kaynak": "cli"}), ("panel PID'i farklı", {"panel_pid": 1}),
                 ("kimlik farklı", {"id": "0" * 32})):
    t, _ = yanitlayici(None, kontrol_f=lambda b, a=alan: sahte(b, a))
    s = onay.iste_sonuc("x", "y", sure=5)
    t.join(2)
    kontrol(f"sahte izin yanıtı ({ad}) → red", not s.izin, str(s))
kontrol("sahte yanıtlardan sonra dosya kalmadı", dosyalar() == [], str(dosyalar()))

# 8) DUR
guvenlik.dur_ac("kullanici")
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("DUR açıkken → hemen red (dur)", not s.izin and s.neden == "dur", str(s))
guvenlik.dur_kapat("kullanici")


def dur_ac_sonra(b):
    time.sleep(0.2)
    guvenlik.dur_ac("cli")


t, _ = yanitlayici(None, kontrol_f=dur_ac_sonra)
s = onay.iste_sonuc("x", "y", sure=5)
t.join(2)
kontrol("beklerken DUR açılırsa → red (dur)", not s.izin and s.neden == "dur", str(s))
guvenlik.dur_kapat("cli")

# 9) panel beklerken kapanır
t, _ = yanitlayici(None, kontrol_f=lambda b: onay.panel_sil())
t0 = time.monotonic()
s = onay.iste_sonuc("x", "y", sure=10)
t.join(2)
kontrol("panel beklerken kapanırsa → red (panel-kapandi), süre dolmadan",
        not s.izin and s.neden == "panel-kapandi" and time.monotonic() - t0 < 3, f"{s} {time.monotonic() - t0:.1f}")
kontrol("panel_sil yalnız kendi pid dosyasını siler", not os.path.exists(onay.panel_pid_yolu()))
onay.panel_kaydet(p.pid)
onay.panel_sil()
kontrol("başkasının panel.pid'ini silmez", os.path.exists(onay.panel_pid_yolu()))
onay.panel_kaydet()

# 10) bekleyenler sıralı; yanıtlanan çıkar
a, b = "1" * 32, "2" * 32
for i, k in enumerate((b, a)):
    onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": f"e{i}", "hedef": "h", "ayrinti": "<b>x</b>",
                                        "masaustu": "garip", "zaman": time.time() + i, "son_zaman": time.time() + 60,
                                        "pid": os.getpid()})
bek = onay.bekleyenler()
kontrol("bekleyenler eskiden yeniye", [x["id"] for x in bek] == [b, a], str([x["id"][:2] for x in bek]))
kontrol("bilinmeyen masaüstü → ekran", all(x["masaustu"] == "ekran" for x in bek))
onay.yanitla(a, "red")
kontrol("yanıtlanan istek bekleyenlerden çıkar", [x["id"] for x in onay.bekleyenler()] == [b])
for k in (a, b):
    onay._sil(onay.istek_yolu(k), onay.yanit_yolu(k))

# 11) yanıt: İZİN yalnız kanaldan (dosya yazılmaz), RED dosyaya da yazılır (biçim)
k = "3" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "ekran",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()})
isteyen_bagli(k)
kontrol("izin yanıtı DOSYAYA yazılmaz (yalnız kanal)", gosterip_yanitla(k, "izin") is True and
        not os.path.exists(onay.yanit_yolu(k)))
kontrol("kanaldan yanıtlanan istek bekleyenlerde görünmez (diyalog yeniden açılmaz)",
        k not in [x["id"] for x in onay.bekleyenler()])
kontrol("izinden sonra red yazılamaz (tek kullanım)", onay.yanitla(k, "red") is False)
onay._sil(onay.istek_yolu(k))
k = "4" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "ekran",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()})
onay.yanitla(k, "red")
y = json.load(open(onay.yanit_yolu(k)))
kontrol("red yanıt biçimi {id, karar: red, kaynak: arayuz, zaman}", y["id"] == k and y["karar"] == "red" and
        y["kaynak"] == "arayuz" and isinstance(y["zaman"], float), str(y))
kontrol("yanıt dosyası 0600", stat.S_IMODE(os.stat(onay.yanit_yolu(k)).st_mode) == 0o600)
onay._sil(onay.istek_yolu(k), onay.yanit_yolu(k))
kontrol("geçici dosya kalmadı", not [f for f in dosyalar() if f.startswith(".")], str(dosyalar()))
kontrol("kanal soketi 0600", stat.S_IMODE(os.lstat(onay.kanal_yolu()).st_mode) == 0o600 and
        stat.S_ISSOCK(os.lstat(onay.kanal_yolu()).st_mode))

# 11b) kanal: yanıtın panelden geldiği doğrulanır (sahte yanıt dosyası / sahte kanal / izinli soket → red)


def sahte_izin_dosyasi(b):
    onay._yaz_atomik(onay.yanit_yolu(b["id"]), {"id": b["id"], "karar": "izin", "kaynak": "arayuz",
                                               "zaman": time.time(), "panel_pid": os.getpid()})


t, _ = yanitlayici(None, kontrol_f=sahte_izin_dosyasi)
s = onay.iste_sonuc("x", "y", sure=5)
t.join(2)
kontrol("kusursuz biçimli sahte İZİN dosyası (panel_pid doğru) → red", not s.izin and s.neden == "red", str(s))

SAHTE_SUNUCU = r"""
import os, socket, sys, time
yol = sys.argv[1]
if os.path.exists(yol): os.unlink(yol)
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.bind(yol); os.chmod(yol, 0o600); s.listen(4)
print("hazir", flush=True)
while True:
    c, _ = s.accept()
    try:
        satir = c.recv(256).decode().split()
        c.sendall(f"karar izin {satir[1]}\n".encode())
    except Exception:
        pass
"""
sahte_p = subprocess.Popen([sys.executable, "-c", SAHTE_SUNUCU, onay.kanal_yolu()], stdout=subprocess.PIPE, text=True)
sahte_p.stdout.readline()
t0 = time.monotonic()
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("kanalı panel olmayan süreç dinliyor (PID uymuyor) → hemen red (kanal), istek yazılmadı",
        not s.izin and s.neden == "kanal" and time.monotonic() - t0 < 1.5 and dosyalar() == [], f"{s} {dosyalar()}")
kontrol("kanal reddi günlükte", any("onay kanalı reddedildi" in l for l in gunluk_satirlari()))
d = json.load(open(onay.panel_pid_yolu()))
d2 = dict(d, pid=sahte_p.pid, baslangic=onay._baslangic(sahte_p.pid), exe=os.readlink(f"/proc/{sahte_p.pid}/exe"))
json.dump(d2, open(onay.panel_pid_yolu(), "w"))  # cmdline bu sürecinki (python3 tests/test_onay.py) kalır
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("aynı exe (python) ama komut satırı kayıttakinden farklı → red (kanal): exe tek başına yetmez",
        not s.izin and s.neden == "kanal", str(s))
json.dump(dict(d2, cmdline=onay._komut_satiri(sahte_p.pid)), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("(sınır) panel.pid'i de ezebilen + soket açabilen süreç = kabuklu saldırgan: kapsam dışı, belgelendi",
        s.izin, str(s))  # tehdit modeli: aynı kullanıcıyla keyfi kod çalıştıran sürece karşı sandbox değil
sahte_p.kill()
sahte_p.wait()
onay.kanal_kapat()
onay.panel_kaydet()  # kendi kanalı yeniden açılır
d = json.load(open(onay.panel_pid_yolu()))
json.dump(dict(d, exe="/usr/bin/baska"), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("panel kaydındaki exe uymuyor → red (kanal)", not s.izin and s.neden == "kanal", str(s))
json.dump(dict(d, exe=None), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("panel kaydında exe yok (eski panel) → red (kanal)", not s.izin and s.neden == "kanal", str(s))
json.dump(dict(d, cmdline=None), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("panel kaydında cmdline yok (eski panel) → red (kanal)", not s.izin and s.neden == "kanal", str(s))
json.dump(dict(d, cmdline=[*d["cmdline"], "-m", "deskhand", "panel"]), open(onay.panel_pid_yolu(), "w"))
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("kayıttaki cmdline birebir değil (ek öğe) → red (kanal)", not s.izin and s.neden == "kanal", str(s))
onay.panel_kaydet()
os.chmod(onay.kanal_yolu(), 0o666)
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("kanal soketi başkalarına açık (0666) → red (kanal)", not s.izin and s.neden == "kanal", str(s))
os.chmod(onay.kanal_yolu(), 0o600)
onay.kanal_kapat()
open(onay.kanal_yolu(), "w").write("sahte")
s = onay.iste_sonuc("x", "y", sure=5)
kontrol("kanal yerinde düz dosya (yalnız dosya yazabilen ajan) → red (kanal)", not s.izin and s.neden == "kanal", str(s))
os.remove(onay.kanal_yolu())
onay.panel_kaydet()


def baskasi_bekle(b):
    # başka bir süreç aynı isteğin kararını almaya çalışır: panel isteğin pid'i ile bağlananı karşılaştırır
    kod = ("import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); "
           "s.sendall(f'bekle {sys.argv[2]}\\n'.encode()); s.settimeout(3); print(s.recv(100))")
    r = subprocess.run([sys.executable, "-c", kod, onay.kanal_yolu(), b["id"]], capture_output=True, text=True,
                       timeout=10)
    alanlar["baskasi"] = r.stdout.strip()
    gosterip_yanitla(b, "izin")


alanlar.clear()
t, _ = yanitlayici(None, kontrol_f=baskasi_bekle)
s = onay.iste_sonuc("x", "y", sure=8)
t.join(5)
kontrol("başka süreç başkasının isteğine bağlanınca karar almaz (bağlantı kapatılır)", alanlar.get("baskasi") == "b''",
        str(alanlar.get("baskasi")))
kontrol("asıl isteyen izni kanaldan alır", s.izin and s.neden == "izin", str(s))

# INC3 B3: a Yes needs the requester's hash; given before it arrives (no requester on the channel) → not approved
k = "5" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "ekran",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()})
_eski_bekle, onay.IZ_BEKLE_SN = onay.IZ_BEKLE_SN, 0.2
kontrol("isteyenin karması gelmeden verilen Evet → izin verilmez", gosterip_yanitla(k, "izin") is False)
onay.IZ_BEKLE_SN = _eski_bekle
c = isteyen_bagli(k)  # the requester (hash) arrives: the dialog shows it again, the Yes goes through
kontrol("karma geldikten sonra Evet → isteyene iletilir", gosterip_yanitla(k, "izin") is True and
        c.recv(100).decode() == f"karar izin {k}\n")
c.close()
onay._sil(onay.istek_yolu(k))

# 11c) bekleyen_var (MCP girdi kapısı): masaüstüne göre, kendi PID'i hariç, sahte uzun ömürlü istek sayılmaz
k = "6" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "arka",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getppid()})
kontrol("bekleyen_var: başka süreçten 'arka' isteği → arka True, ekran False",
        onay.bekleyen_var("arka") and not onay.bekleyen_var("ekran"))
kontrol("bekleyen_var: kendi PID'i hariç tutulabilir", not onay.bekleyen_var("arka", haric_pid=os.getppid()))
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "arka",
                                    "zaman": time.time(), "son_zaman": time.time() + 10 ** 6, "pid": os.getppid()})
kontrol("bekleyen_var: ömrü olağandışı uzun (sahte) istek girdiyi kilitlemez", not onay.bekleyen_var("arka"))
onay._sil(onay.istek_yolu(k))

# 13) security scan 4: a Yes is bound to the request the DIALOG showed (not to an earlier background read), and
# nothing-known-about-what-was-shown means No (fail-closed)
def istek_yaz(i, tur="", eylem="Kaydet"):
    simdi = time.time()
    veri = {"id": i, "eylem": eylem, "hedef": "Belge", "ayrinti": "", "masaustu": "ekran", "zaman": simdi,
            "son_zaman": simdi + 60, "pid": os.getpid()}
    if tur:
        veri["tur"] = tur
    onay._yaz_atomik(onay.istek_yolu(i), veri)
    with open(onay.istek_yolu(i), "rb") as f:
        return f.read()


def evet(i, gosterilen):
    """The dialog's Yes: it hands over the fingerprint of what it showed."""
    return gosterip_yanitla({"id": i, "_iz": gosterilen}, "izin")


try:
    guvenlik.dur_ac("kullanici")
    i = "a1" * 16
    dur_baytlari = istek_yaz(i, tur=onay.TUR_DUR)   # A: "remove DUR?"
    onay.bekleyenler()                               # the panel's background reads (watcher / channel / cleanup)…
    onay.temizle()
    istek_yaz(i, eylem="Kaydet")                     # …B replaces it before the dialog is built
    gosterilen = onay.istek_oku(onay.istek_yolu(i))  # the dialog shows B (an ordinary "Kaydet" question)
    with open(onay.istek_yolu(i), "wb") as f:
        f.write(dur_baytlari)                        # A is put back, byte for byte, before the user clicks Yes
    r = evet(i, gosterilen["_iz"])
    kontrol("tarama-4: istek başka yoldan okundu, diyalog farklı içerik gösterdi → Evet DUR'u kaldırmaz",
            r is False and guvenlik.dur_acik(), f"{r} dur_acik={guvenlik.dur_acik()}")
    onay._sil(onay.istek_yolu(i))

    j = "b2" * 16
    istek_yaz(j, tur=onay.TUR_DUR)
    isteyen_bagli(j)
    onay.istek_oku(onay.istek_yolu(j))               # shown…
    getattr(onay, "_GORULEN", {}).clear()           # …then the panel's memory of it is gone (d78c8d6: >4096 → clear())
    r = onay.yanitla(j, "izin")                      # nothing says what the user saw
    kontrol("tarama-4: gösterilen bilinmiyor (önbellek boşaldı) → izin reddedilir, DUR kalır, istek yeniden sorulur",
            r is False and guvenlik.dur_acik() and j in [x["id"] for x in onay.bekleyenler()],
            f"{r} dur_acik={guvenlik.dur_acik()}")
    gosterilen = onay.istek_oku(onay.istek_yolu(j))  # the dialog is shown again: this Yes is the user's
    kontrol("tarama-4: yeniden gösterilen DUR sorusuna Evet → DUR kalkar (tek kez)",
            evet(j, gosterilen["_iz"]) is True and not guvenlik.dur_acik() and evet(j, gosterilen["_iz"]) is False)
    onay._sil(onay.istek_yolu(j))

    guvenlik.dur_ac("kullanici")
    m = "c3" * 16
    istek_yaz(m, tur=onay.TUR_DUR)
    gosterilen = onay.istek_oku(onay.istek_yolu(m))
    istek_yaz(m, eylem="Kaydet")                     # shown as "remove DUR?", now an ordinary question
    kontrol("tarama-4: gösterilenden sonra değişen istek → Evet reddedilir (DUR da kalkmaz)",
            evet(m, gosterilen["_iz"]) is False and guvenlik.dur_acik())
    try:
        bicimsiz = onay.yanitla(m, "izin", gosterilen=("dur",))
    except TypeError:
        bicimsiz = None
    kontrol("tarama-4: biçimsiz gösterilen iz → red", bicimsiz is False, str(bicimsiz))
    onay._sil(onay.istek_yolu(m))
finally:
    guvenlik.dur_kapat("kullanici")

# 12) Qt'siz: onay modülü Qt içe aktarmaz (CLI/MCP hafif kalsın)
r = subprocess.run([sys.executable, "-c", "import sys, deskhand.onay; print('PyQt6' in sys.modules)"],
                   capture_output=True, text=True)
kontrol("deskhand.onay PyQt6 yüklemez", r.stdout.strip() == "False", r.stdout + r.stderr)

for _c in _ISTEYENLER:
    _c.close()
onay.panel_sil()
print(f"\n{gecen}/{toplam} onay testi geçti")
sys.exit(0 if gecen == toplam else 1)
