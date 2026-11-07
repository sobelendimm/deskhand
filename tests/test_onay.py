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
        return sorted(os.listdir(onay.dizin()))
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
                    gorulen.append(onay.yanitla(b[0]["id"], karar))
                return
            time.sleep(0.02)

    t = threading.Thread(target=calis, daemon=True)
    t.start()
    return t, gorulen


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
    sonuclar["ikinci"] = onay.yanitla(b["id"], "izin")


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
kontrol("süresi geçmiş isteğe İZİN yazılmaz", onay.yanitla(eski, "izin") is False)
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

# 11) yanıt dosyasını panel tarafı yazar: biçim
k = "3" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "ekran",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()})
onay.yanitla(k, "izin")
y = json.load(open(onay.yanit_yolu(k)))
kontrol("yanıt biçimi {id, karar, kaynak: arayuz, zaman}", y["id"] == k and y["karar"] == "izin" and
        y["kaynak"] == "arayuz" and isinstance(y["zaman"], float), str(y))
kontrol("yanıt dosyası 0600", stat.S_IMODE(os.stat(onay.yanit_yolu(k)).st_mode) == 0o600)
onay._sil(onay.istek_yolu(k), onay.yanit_yolu(k))
kontrol("geçici dosya kalmadı", not [f for f in dosyalar() if f.startswith(".")], str(dosyalar()))

# 12) Qt'siz: onay modülü Qt içe aktarmaz (CLI/MCP hafif kalsın)
r = subprocess.run([sys.executable, "-c", "import sys, deskhand.onay; print('PyQt6' in sys.modules)"],
                   capture_output=True, text=True)
kontrol("deskhand.onay PyQt6 yüklemez", r.stdout.strip() == "False", r.stdout + r.stderr)

onay.panel_sil()
print(f"\n{gecen}/{toplam} onay testi geçti")
sys.exit(0 if gecen == toplam else 1)
