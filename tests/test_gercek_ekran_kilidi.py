"""Gerçek ekran kilidi (DESKHAND_GERCEK_EKRAN) testleri: kullanıcının GERÇEK masaüstüne etki eden her yol, değişken
ayarlıyken EN ALT katmanda (gerçek aracı çalıştırmadan hemen önce) Dur 17 ile reddedilir.

Kullanıcının ekranına, panele, dotool'a, panoya, bildirim hizmetine HİÇBİR şey gitmez: `subprocess.run/Popen` bu dosyada
SAHTELENİR (gerçek araç hiç çalıştırılmaz; kilit delinirse sahte Popen patlar ve kayıt tutulur).

A) kapali: kde arka ucunun her yan etkili yöntemi Dur 17 + yan etkili alt süreç HİÇ başlamaz; okuma yolları açık
B) salt-okuma: yan etkiler yine reddedilir, ekran görüntüsü/pano OKUMA kilidi geçer
C) değişken yok: davranış aynı (sahte alt süreç çağrılır) + doctor satırı yalnız ayarlıyken
D) görünmez masaüstü (Xvfb) ve sahte kde arka ucu kilitten etkilenmez

Çalıştır:  python3 tests/test_gercek_ekran_kilidi.py      (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import atexit
import os
import subprocess
import sys
import time
import types

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler + DESKHAND_GERCEK_EKRAN=kapali; Deskhand'den ÖNCE)

from deskhand import api, arka_uc, doktor, erisim, girdi_merkezi as GM, hata, masaustu, mesgul
from deskhand.arka_uc import EKRAN, kde, kde_goruntu
from deskhand.hata import Dur
from deskhand import onay as _onay_mod  # noqa: E402
_ASIL_ISTE = _onay_mod.iste_sonuc  # sahte_masaustu.kur() sonra sahteler; E bölümü GERÇEĞİNİ sınar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    """→ (Dur kodu | None, ileti). Dur dışı istisna: ('hata', ad)."""
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod, e.mesaj
    except SystemExit as e:
        return ("cikis", e.code), ""
    except Exception as e:  # noqa: BLE001
        return "hata", f"{type(e).__name__}: {e}"
    return None, ""


# ---------------------------------------------------------------- sahte alt süreç katmanı (gerçek araç ÇALIŞMAZ)

KAYIT = []  # (tür, argv)
W = "{11111111-2222-3333-4444-555555555555}"
W2 = "{99999999-8888-7777-6666-555555555555}"  # etkin pencere (W) DEĞİL: one_getir gerçekten etkinleştirmeye kalkar


def _cevap(argv):
    a0 = os.path.basename(argv[0])
    if a0 == "kscreen-doctor":
        return "Geometry: 0,0 1920x1080"
    if a0 == "kdotool" and len(argv) > 1 and argv[1] == "getactivewindow":
        return W
    if a0 == "busctl":
        return "b false"
    if a0 == "dotool" and tuple(argv[1:]) == ("--list-keys",):
        return "Return 28\nreturn 28\nenter 28\na 30\nctrl 29"
    return ""


def sahte_run(argv, *a, **k):
    KAYIT.append(("run", tuple(argv)))
    return types.SimpleNamespace(stdout=_cevap(argv), stderr="", returncode=0)


class SahtePopen:
    def __init__(self, argv, *a, **k):
        KAYIT.append(("popen", tuple(argv)))
        raise RuntimeError(f"alt süreç başlatıldı (kilit delindi): {argv}")


YAN_ETKILI_ARACLAR = {"spectacle", "wl-copy", "gio", "xdg-open", "notify-send", "deskhand-goruntu"}  # dotool: _yan_etkili_mi


def yan_etkili_kayitlar():
    """Kaydedilen alt süreçlerden yan etkili olanlar: dotool/spectacle/wl-copy/gio/…, eylem sözlü kdotool, panoyu
    okuyan wl-paste (içerik)."""
    sonuc = []
    for tur, argv in KAYIT:
        ad = os.path.basename(argv[0])
        if ad in YAN_ETKILI_ARACLAR or ad == "wl-paste" or kde._yan_etkili_mi(argv):
            sonuc.append((tur, argv))
    return sonuc


asil_run, asil_popen = subprocess.run, subprocess.Popen
subprocess.run, subprocess.Popen = sahte_run, SahtePopen
atexit.register(lambda: (setattr(subprocess, "run", asil_run), setattr(subprocess, "Popen", asil_popen)))

class SahteEtkinlik:  # kde.insan_var_mi'nin yardımcı süreci (salt okuma, ama gerçek süreç açardı)
    def calisiyor(self): return False
    def insan(self, beri): return False
    def kapat(self): pass


kde.Etkinlik = SahteEtkinlik

# kilit dışındaki ön plan korumaları (oyun/film, kilit ekranı) test sürecini gerçek oturuma bakmasın
kde.KILIT_SORGU = lambda: False
mesgul._dbus_ac = lambda: None  # bu testte HİÇBİR yol kullanıcının oturum veri yoluna bağlanmaz (bildirim/okuma dahil)
mesgul.ekran_korumasi = lambda *a, **k: None
mesgul.karar_bekliyor = lambda: False

# ================================================================ kip çözümü

DEG = hata.GERCEK_EKRAN_DEGISKENI
kontrol("değişken adı DESKHAND_GERCEK_EKRAN", DEG == "DESKHAND_GERCEK_EKRAN")
kontrol("_yalitim değişkeni 'kapali' yapar", os.environ.get(DEG) == "kapali")
kiplar = {}
for deger in ("", "acik", "salt-okuma", "kapali", "KAPALI ", "yanlis", "0", "false"):
    os.environ[DEG] = deger
    kiplar[deger] = hata.gercek_ekran_kipi()
del os.environ[DEG]
kiplar["(ayarsız)"] = hata.gercek_ekran_kipi()
os.environ[DEG] = "kapali"
kontrol("kip: acik / ayarsız → acik; ayarlı ama BOŞ → kapali (VAR=$AYARSIZ kilidi açmasın)",
        kiplar["acik"] == kiplar["(ayarsız)"] == "acik" and kiplar[""] == "kapali", str(kiplar))
kontrol("kip: salt-okuma → salt-okuma; kapali (büyük harf/boşluk dahil) → kapali",
        kiplar["salt-okuma"] == "salt-okuma" and kiplar["kapali"] == kiplar["KAPALI "] == "kapali", str(kiplar))
kontrol("kip: tanınmayan değer (yazım hatası, 0, false) → kapali (kilidi açmaz)",
        kiplar["yanlis"] == kiplar["0"] == kiplar["false"] == "kapali", str(kiplar))
kod, ileti = dur_kodu(hata.gercek_ekran_denetle, "deneme")
kontrol("denetle: kapali → Dur 17, açık ileti (değişken + görünmez masaüstü yönlendirmesi)",
        kod == hata.GERCEK_EKRAN_KAPALI == 17 and "gerçek ekran bu süreçte kapalı (DESKHAND_GERCEK_EKRAN=kapali)" in ileti
        and "hedefi görünmez masaüstü yap" in ileti, f"{kod} {ileti}")
try:
    hata.gercek_ekran_denetle("x")
except Dur as e:
    kontrol("denetle: Dur.tur makinece okunur", e.tur == "gercek-ekran-kapali")

# ================================================================ A) kapali: yan etkili HER yöntem reddedilir

au = kde.KdeArkaUc()
YAN = [
    ("kd windowactivate", lambda: kde.kd("windowactivate", W)),
    ("kd windowclose", lambda: kde.kd("windowclose", W)),
    ("calis kdotool windowmove", lambda: kde.calis("kdotool", "windowmove", W, "1", "1")),
    ("calis zincirli (okuma + eylem sözü)", lambda: kde.calis("kdotool", "getwindowname", W, "windowactivate", W)),
    ("calis bilinmeyen kdotool sözü (kapalı-başarısız)", lambda: kde.calis("kdotool", "yenisoz", W)),
    ("calis kdotool sözsüz", lambda: kde.calis("kdotool")),
    ("calis dotool", lambda: kde.calis("dotool", "--bilinmeyen")),
    ("pencere: one_getir (etkin değil)", lambda: au.one_getir(W2)),
    ("pencere: etkinlestir", lambda: au.etkinlestir(W2)),
    ("pencere: kapat", lambda: au.kapat(W)),
    ("pencere: tasi", lambda: au.tasi(W, 10, 10)),
    ("pencere: boyutlandir", lambda: au.boyutlandir(W, 300, 200)),
    ("pencere: kucult", lambda: au.kucult(W)),
    ("pencere: buyut", lambda: au.buyut(W)),
    ("pencere: geri_yukle", lambda: au.geri_yukle(W)),
    ("girdi: au.girdi() (tık/yazı/tuş/sürükle tek giriş)", lambda: au.girdi("t")),
    ("girdi: Girdi(...)", lambda: kde.Girdi(au, "t", denetle=lambda k, d: None)),
    ("girdi: dotool_ac", lambda: kde.dotool_ac()),
    ("girdi merkezi: Istemci.baglan", lambda: GM.Istemci.baglan(("tr", ""))),
    ("uygulama başlat", lambda: au.baslat(["true"])),
    ("uygulama başlat (env)", lambda: au.baslat(["true"], {"A": "b"})),
    ("pano yaz", lambda: au.pano_yaz("merhaba")),
    ("pano temizle", lambda: au.pano_yaz("")),
    ("pano yaz (ham, geri yükleme yolu)", lambda: kde._pano_yaz_ham("x")),
    ("bildirim", lambda: mesgul.sor("deneme")),
    ("a11y ayarı (org.a11y.Status yaz)", lambda: erisim._erisim_yaz(True)),
    ("a11y eylem (AT-SPI)", lambda: erisim._atspi_is({"islem": "eylem", "a11y": "", "pid": "", "baslik": ""})),
    ("a11y değer yaz (AT-SPI)", lambda: erisim._atspi_is({"islem": "yaz", "a11y": "", "pid": "", "baslik": ""})),
]
for ad, f in YAN:
    kod, ileti = dur_kodu(f)
    kontrol(f"kapali: {ad} → Dur 17", kod == 17, f"{kod} {ileti}")
kod, uyari = None, None
try:
    uyari = au.pano_geri_yukle({"bos": True})
except Dur as e:
    kod = e.kod
kontrol("kapali: pano geri yükleme → çalıştırılmaz (uyarı döner), alt süreç yok",
        isinstance(uyari, str) and "geri yüklenemedi" in uyari and kod is None, f"{uyari} {kod}")

# içerik OKUYAN yollar (kapali'da kapanır)
OKU = [
    ("ekran görüntüsü (kde.ekran_goruntusu)", lambda: kde.ekran_goruntusu()),
    ("ekran görüntüsü (KdeArkaUc.goruntu)", lambda: au.goruntu()),
    ("ekran görüntüsü (spectacle yedeği)", lambda: kde.spectacle_goruntusu()),
    ("ekran görüntüsü (kde_goruntu.al)", lambda: kde_goruntu.al()),
    ("pano oku", lambda: au.pano_oku()),
    ("seçim oku", lambda: au.secim_oku()),
    ("pano yedekle", lambda: au.pano_yedekle()),
]
for ad, f in OKU:
    kod, ileti = dur_kodu(f)
    kontrol(f"kapali: {ad} → Dur 17 (kullanıcı içeriği)", kod == 17, f"{kod} {ileti}")

# yüksek düzey: hedef verilmemiş (varsayılan = kde) çağrılar ve hedef("kde") — kilit en altta olduğu için hepsi reddedilir
os.environ.pop("DESKHAND_HEDEF", None)
YUKSEK = [
    ("api.yaz(k, …) hedefsiz", lambda: api.yaz(EKRAN, "merhaba")),
    ("api.tikla hedefsiz", lambda: api.tikla(EKRAN, 0.5, 0.5)),
    ("api.tus hedefsiz", lambda: api.tus(EKRAN, "Return")),
    ("api.surukle hedefsiz", lambda: api.surukle(EKRAN, 0.1, 0.1, 0.2, 0.2)),
    ("api.pano_yaz hedefsiz", lambda: api.pano_yaz("x")),
    ("api.uygulama_ac hedefsiz", lambda: api.uygulama_ac(["true"], "deneme", [])),
]
for ad, f in YUKSEK:
    kod, ileti = dur_kodu(f)
    kontrol(f"kapali: {ad} → Dur 17", kod == 17, f"{kod} {ileti}")
with api.hedef("kde"):
    kod, ileti = dur_kodu(api.yaz, EKRAN, "merhaba")
kontrol("kapali: api.hedef('kde') + yaz → Dur 17", kod == 17, f"{kod} {ileti}")

kontrol("kapali: yan etkili HİÇBİR alt süreç başlamadı / çalıştırılmadı (dotool, spectacle, wl-*, gio, eylemli kdotool)",
        yan_etkili_kayitlar() == [] and not [k for k in KAYIT if k[0] == "popen"],
        str(yan_etkili_kayitlar()[:5] + [k for k in KAYIT if k[0] == "popen"][:5]))

# okuma yolları kapatılmaz: pencere listesi/başlık/geometri, etkin pencere, fare, ekran alanı, kilit durumu
n0 = len(KAYIT)
okumalar = {
    "aktif": au.aktif() == W,
    "ekran_alani": au.ekran_alani() == (0, 0, 1920, 1080),
    "baslik": au.baslik(W) == "",
    "kimlikler": isinstance(au.kimlikler(), set),
    "fare": au.fare()[0] is None,
    "kilit okuma": kde.oturum_kilidi_oku() is False,
}
kontrol("kapali: salt OKUMA yolları (etkin pencere, ekran alanı, başlık, pencere listesi, fare, kilit) açık",
        all(okumalar.values()) and len(KAYIT) > n0, str(okumalar))
KAYIT.clear()

# ================================================================ B) salt-okuma: yan etkiler reddedilir, okuma kilidi geçer

os.environ[DEG] = "salt-okuma"
for ad, f in YAN:
    kod, ileti = dur_kodu(f)
    kontrol(f"salt-okuma: {ad} → Dur 17", kod == 17 and "DESKHAND_GERCEK_EKRAN=salt-okuma" in ileti, f"{kod} {ileti}")
kontrol("salt-okuma: yan etkili alt süreç yok", yan_etkili_kayitlar() == [], str(yan_etkili_kayitlar()[:5]))

KAYIT.clear()
# ekran görüntüsü / pano OKUMA: kilidi geçer, sahte araca ulaşır (sahte Popen/yardımcı çıktısı bozuk → başka hata, 17 DEĞİL)
kod, ileti = dur_kodu(kde.spectacle_goruntusu)
kontrol("salt-okuma: spectacle ekran görüntüsü kilidi geçer (sahte araca ulaşır)",
        kod != 17 and any(os.path.basename(a[0]) == "spectacle" for _t, a in KAYIT), f"{kod} {ileti} {KAYIT}")
KAYIT.clear()
kod, ileti = dur_kodu(kde_goruntu.al)
kontrol("salt-okuma: ekran görüntüsü yardımcısı kilidi geçer", kod != 17 and any(
    "deskhand-goruntu" in a[0] for _t, a in KAYIT), f"{kod} {ileti} {KAYIT}")
KAYIT.clear()
kod, ileti = dur_kodu(au.pano_oku)
kontrol("salt-okuma: pano OKUMA (wl-paste) kilidi geçer", kod != 17 and any(
    os.path.basename(a[0]) == "wl-paste" for _t, a in KAYIT), f"{kod} {ileti} {KAYIT}")
kontrol("salt-okuma: pano YAZMA (wl-copy) yine reddedilir ve çalıştırılmaz",
        dur_kodu(au.pano_yaz, "x")[0] == 17 and not any(os.path.basename(a[0]) == "wl-copy" for _t, a in KAYIT))
KAYIT.clear()

# ================================================================ C) değişken yok: davranış birebir aynı

del os.environ[DEG]
kontrol("ayarsız: kip acik", hata.gercek_ekran_kipi() == "acik")
hata.gercek_ekran_denetle("x")
hata.gercek_ekran_denetle("x", okuma=True)
kontrol("ayarsız: denetle hiçbir şey yapmaz", True)

# her yan etkili yöntem sahte alt sürece KADAR gider (kilit yok): çağrı kaydı + (Popen için) sahte patlama
KAYIT.clear()
kod, _i = dur_kodu(kde.calis, "kdotool", "windowactivate", W)
kontrol("ayarsız: kdotool windowactivate sahte alt süreçte çalıştırılır",
        kod is None and ("run", ("kdotool", "windowactivate", W)) in KAYIT, str(KAYIT))
kod, ileti = dur_kodu(kde.dotool_ac)
kontrol("ayarsız: dotool_ac Popen'e ulaşır (sahte patladı, Dur değil)",
        kod == "hata" and "kilit delindi" in ileti and ("popen", ("dotool",)) in KAYIT, f"{kod} {ileti}")
kod, ileti = dur_kodu(au.baslat, ["true"])
kontrol("ayarsız: baslat Popen'e ulaşır (sahte patladı)", kod == "hata" and ("popen", ("true",)) in KAYIT, f"{kod} {ileti}")
kod, ileti = dur_kodu(au.pano_yaz, "merhaba")
kontrol("ayarsız: pano yazma wl-copy Popen'ine ulaşır (sahte patladı)",
        kod == "hata" and any(os.path.basename(a[0]) == "wl-copy" for t, a in KAYIT if t == "popen"), f"{kod} {ileti}")
kod, ileti = dur_kodu(kde.spectacle_goruntusu)
kontrol("ayarsız: spectacle çalıştırılır", any(os.path.basename(a[0]) == "spectacle" for _t, a in KAYIT), f"{kod} {ileti}")
# bildirim yolu: oturum veri yolu SAHTE (açılamıyor) → gerçek veri yoluna HİÇ bağlanılmaz, gerçek bildirim gitmez
cevap = mesgul.sor("deneme")
kontrol("ayarsız: bildirim yolu kilitlenmez (sahte veri yolu açılamadı → iletiyle döner, 17 değil)",
        cevap[0] is None and "veri yolu açılamadı" in cevap[1], str(cevap))
KAYIT.clear()
d = doktor.satir_gercek_ekran()
kontrol("doctor: ayarsızken 'Gerçek ekran' satırı yok", d is None and not any(
    s["ad"] == "Gerçek ekran" for s in doktor.topla()))
os.environ[DEG] = "kapali"
d = doktor.satir_gercek_ekran()
kontrol("doctor: ayarlıyken 'Gerçek ekran: bu süreçte kapalı' satırı",
        d and d["ad"] == "Gerçek ekran" and d["durum"] == "tamam" and "bu süreçte kapalı" in d["ayrinti"], str(d))
kontrol("doctor: topla() satırı içerir ve ayarsızken çıktı aynı sayıda satır",
        any(s["ad"] == "Gerçek ekran" for s in doktor.topla()))
os.environ[DEG] = "salt-okuma"
d = doktor.satir_gercek_ekran()
kontrol("doctor: salt-okuma satırı okumanın açık olduğunu söyler", d and "yalnız okuma serbest" in d["ayrinti"], str(d))
os.environ[DEG] = "kapali"

# ================================================================ D) görünmez masaüstü + sahte kde etkilenmez (kapali)

kontrol("D: değişken hâlâ kapali", os.environ[DEG] == "kapali")
subprocess.run, subprocess.Popen = asil_run, asil_popen  # görünmez masaüstü GERÇEK Xvfb başlatır (kullanıcının ekranı değil)
os.environ["DESKHAND_ARKA_TUR"] = "xvfb"
atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
sanal_ok = False
try:
    d = masaustu.masaustu_baslat()
    kontrol("D: görünmez masaüstü kapali kilidiyle açılır", d and d.get("ekran"))
    sau = arka_uc.sec(arka_bayragi=True)
    kontrol("D: sec(arka_bayragi) → sanal arka uç", sau.ad == "sanal")
    g = sau.girdi("kilit-testi")
    try:
        g.gonder(EKRAN, None, "mouseto 0.5 0.5")
        time.sleep(0.1)
        x, y, _w = sau.fare()
        x0, y0, x1, y1 = sau.ekran_alani()
        kontrol("D: sanal masaüstünde imleç hareketi çalışıyor (kilit etkilemez)",
                x is not None and abs(x - (x0 + x1) // 2) <= 2 and abs(y - (y0 + y1) // 2) <= 2, f"{x},{y}")
        g.gonder(EKRAN, None, "click left")
        kontrol("D: sanal masaüstünde tık çalışıyor (kilit etkilemez)", True)
    finally:
        g.kapat()
    im = sau.goruntu()
    kontrol("D: sanal masaüstünde ekran görüntüsü çalışıyor (kilit etkilemez)", im.size[0] > 100)
    with api.hedef("sanal"):
        kod, ileti = dur_kodu(api.tikla, EKRAN, 0.4, 0.4)
    kontrol("D: api.hedef('sanal') + tikla → 17 DEĞİL", kod != 17, f"{kod} {ileti}")
    sanal_ok = True
finally:
    masaustu.masaustu_durdur()
kontrol("D: görünmez masaüstü bölümü tamamlandı", sanal_ok)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
import sahte_masaustu as sm  # noqa: E402

sau = sm.kur()
g = sau.girdi("sahte")
g.gonder("{sahte-1}", None, "click left")
kontrol("D: sahte kde arka ucu kilitten etkilenmez (gerçek araç çağırmaz)", sau.satirlar[-1] == "click left", str(sau.satirlar))
kontrol("D: sahte kde ile api.tikla → 17 DEĞİL", dur_kodu(api.tikla, "{sahte-1}", 10, 10)[0] != 17)

# ---------------------------------------------------------------- E. inceleme ekleri (web eylemi, onay kanalı, kwinscript)
from deskhand import onay, web  # noqa: E402
from deskhand.mesgul import KWIN_BETIK  # noqa: E402

_asil_baglam = web._baglam
try:
    web._baglam = lambda k, ne: (types.SimpleNamespace(ad="kde"), object(), "bus", None)
    kontrol("E: web.eylem_yap gerçek oturumda (kde) → 17, DoAction yok",
            dur_kodu(web.eylem_yap, "{k}", {"_bus": ":1.9", "_yol": "/x"})[0] == 17)
finally:
    web._baglam = _asil_baglam
_rt = os.environ.pop("DESKHAND_RUNTIME_DIR")
try:
    _r = dur_kodu(_ASIL_ISTE, "tıkla", "deneme")
    kontrol("E: onay.iste_sonuc GERÇEK çalışma dizininde (kullanıcının paneli) → 17", _r[0] == 17, str(_r))
finally:
    os.environ["DESKHAND_RUNTIME_DIR"] = _rt
kontrol("E: kwinscript yalnız mesgul'ün sabit betiği okuma; başka inline/dosya betik yan etki",
        not kde._yan_etkili_mi(["kdotool", "kwinscript", "--inline", KWIN_BETIK]) and
        kde._yan_etkili_mi(["kdotool", "kwinscript", "--inline", "workspace.activeWindow.closeWindow()"]) and
        kde._yan_etkili_mi(["kdotool", "kwinscript", "betik.js"]))
kontrol("E: zincirli bilinmeyen eylem sözleri (set_desktop_for_window, windowlower) yan etki",
        all(kde._yan_etkili_mi(["kdotool", "getwindowname", "K", s_, "K", "1"])
            for s_ in ("set_desktop_for_window", "set_desktop", "windowlower", "set_num_desktops")))
_eski = os.environ.get(DEG)
try:
    os.environ[DEG] = ""
    kontrol("E: ayarlı ama BOŞ değer (VAR=$AYARSIZ) → kapali", hata.gercek_ekran_kipi() == "kapali")
finally:
    os.environ[DEG] = _eski
_kodlar = {k: v for k, v in vars(hata).items() if k.isupper() and isinstance(v, int) and not isinstance(v, bool)
           and 0 < v < 64}
kontrol("E: hata.py çıkış kodu sabitleri BENZERSİZ (iki özellik aynı koda düşmesin)",
        len(set(_kodlar.values())) == len(_kodlar), str(sorted(_kodlar.items(), key=lambda x: x[1])))

print(f"\n{gecen}/{toplam} gerçek ekran kilidi testi geçti")
sys.exit(0 if gecen == toplam else 1)
