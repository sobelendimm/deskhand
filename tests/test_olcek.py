"""Ölçek 2 (HiDPI) görünmez masaüstü testleri: `deskhand desktop start --scale 2` / manage_desktop(scale=2).

Aynı mantıksal düzen (pencere geometrisi, tıklama koordinatı, EIS bölgesi mantıksal piksel), iki kat piksel: ekran
görüntüsü tam çözünürlükte 2×, tıklama doğru ögeye gider (Qt penceresi olay günlüğü + Firefox AT-SPI ögesi), OCR
çalışır, CLI screenshot --out tam çözünürlük kaydeder, --width küçültür. Firefox (XWayland) gerçekten 2× çizer
(devicePixelRatio 2, metin mürekkep yüksekliği ölçek 1'in ~2 katı). Xvfb türünde ölçek 2 açık iletiyle reddedilir.
Kullanıcının GERÇEK ekranına hiçbir girdi gitmez (tests/_yalitim.py; yalıtık KWin oturumu).

Çalıştır:  python3 tests/test_olcek.py"""
import argparse
import json
import os
import shutil
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
os.environ["DESKHAND_ARKA_TUR"] = "kwin"
import numpy as np  # noqa: E402

from deskhand import api, arka_uc, gorsel, kwin_oturum as ko, masalar, masaustu, mcp_sunucu, yollar  # noqa: E402
from deskhand.arka_uc import sec  # noqa: E402
from deskhand.hata import ARAC_EKSIK, Dur  # noqa: E402

# ---------------------------------------------------------------- 0) saf birim: AT-SPI kutu bölme YALNIZ ölçek > 1
from types import SimpleNamespace  # noqa: E402

from deskhand import erisim  # noqa: E402

_g0 = _t0 = 0


def _kontrol0(ad, kosul, ek=""):
    global _g0, _t0
    _t0 += 1
    _g0 += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


class _Durum:
    def contains(self, _s):
        return True


class _Oge:
    def __init__(self, kutu, cocuklar=(), ad=""):
        self.kutu, self.cocuklar, self.ad = kutu, list(cocuklar), ad

    def get_extents(self, _tur):
        return SimpleNamespace(x=self.kutu[0], y=self.kutu[1], width=self.kutu[2], height=self.kutu[3])

    def get_state_set(self):
        return _Durum()

    def get_role_name(self):
        return "push button" if self.ad else "frame"

    def get_name(self):
        return self.ad

    def get_child_count(self):
        return len(self.cocuklar)

    def get_child_at_index(self, i):
        return self.cocuklar[i]


_Atspi = SimpleNamespace(CoordType=SimpleNamespace(WINDOW=1), StateType=SimpleNamespace(SHOWING=1, SENSITIVE=2))
# pencere 700x460; uygulama çerçevesini İKİ KAT (1400x920) bildiriyor, düğme çerçevede (200,100) 160x40
_cerceve = _Oge((0, 0, 1400, 920), [_Oge((200, 100, 160, 40), ad="Kaydet")])


def _kutu(olcek):
    o = erisim._tara(_Atspi, _cerceve, (0, 0, 700, 460), 100, 5.0, 100, olcek=olcek)["ogeler"]
    return [(x["x"], x["y"], x["w"], x["h"]) for x in o]


print("0) AT-SPI kutu bölme (saf birim)")
_kontrol0("ölçek 1 + çerçeve pencerenin 2 katı → kutular BÖLÜNMEZ (eski davranış)", _kutu(1) == [(200, 100, 160, 40)],
          str(_kutu(1)))
_kontrol0("ölçek 2 + aynı çerçeve → kutular mantıksal piksele bölünür", _kutu(2) == [(100, 50, 80, 20)], str(_kutu(2)))
_kontrol0("xwayland_orani: ölçek 1 hep 1; ölçek 2'de yalnız oran ≈ 2 (1.5x, 3x çerçeve → 1)",
          erisim.xwayland_orani(1400, 920, 700, 460, 1) == 1 and erisim.xwayland_orani(1400, 920, 700, 460, 2) == 2
          and erisim.xwayland_orani(1050, 690, 700, 460, 2) == 1 and erisim.xwayland_orani(2100, 1380, 700, 460, 2) == 1
          and erisim.xwayland_orani(700, 460, 700, 460, 2) == 1 and erisim.xwayland_orani(1400, 920, 0, 460, 2) == 1)
if _g0 != _t0:
    print(f"\n{_g0}/{_t0} geçti")
    sys.exit(1)

ok_, neden_ = ko.kullanilabilir()
if not ok_ or not shutil.which("kscreen-doctor") or not yollar.eis_bin() or not yollar.goruntu_bin():
    print(f"atlandı: KWin oturumu/kscreen-doctor/yardımcılar yok ({neden_})")
    sys.exit(0)

import atexit  # noqa: E402

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
gecen, toplam = _g0, _t0
olcum = {}
PENCERE = os.path.join(_yalitim.KOK, "tests", "yardimci", "kwin_test_pencere.py")
LOG = os.path.join(_yalitim.PAYLASIM, "olcek.log")


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


def bekle(kosul, sure=8.0, aralik=0.05):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return None


def loglar():
    try:
        with open(LOG, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def kutu_bul(im, renk, tol=6):
    a = np.asarray(im.convert("RGB")).astype(int)
    mk = (abs(a[:, :, 0] - renk[0]) <= tol) & (abs(a[:, :, 1] - renk[1]) <= tol) & (abs(a[:, :, 2] - renk[2]) <= tol)
    ys, xs = np.nonzero(mk)
    if len(xs) < 100:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def murekkep(im, kutu, f):
    """Test sayfasında eflatun kutunun (CSS 20,20 100x20) 40 CSS px altındaki metin satırının mürekkep yüksekliği."""
    x0, y0 = kutu[0], kutu[1] + round(30 * f)
    a = np.asarray(im.convert("L").crop((x0, y0, x0 + round(320 * f), y0 + round(30 * f)))).astype(int)
    ys = np.nonzero((a < 110).any(axis=1))[0]
    return int(ys.max() - ys.min() + 1) if len(ys) else 0


def firefox_olc(au, srv, f):
    """Firefox'u test sayfasıyla aç → (Firefox, pencere, dpr başlığı, tam görüntü, eflatun kutu, mürekkep yüksekliği)."""
    import web_tarayici as wt
    t = time.monotonic()
    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("olcek.html"))
    baslik = bekle(lambda: (lambda b: b if "dpr=" in b else None)(au.baslik(ff.k)), 30, 0.2) or au.baslik(ff.k)
    olcum[f"Firefox açılışı (ölçek {f:g})"] = f"{time.monotonic() - t:.1f} sn"
    with api.hedef("sanal"):
        im = bekle(lambda: (lambda im_: im_ if kutu_bul(im_, (255, 0, 255), 2) else None)(
            api.goruntu_al(ff.k, tam=True)[0]), 15, 0.2) or api.goruntu_al(ff.k, tam=True)[0]
    kutu = kutu_bul(im, (255, 0, 255), 2)
    return ff, baslik, im, kutu, murekkep(im, kutu, f) if kutu else 0


# ---------------------------------------------------------------- 1) doğrulama + Xvfb'de açık ret
print("1) ölçek doğrulama + Xvfb reddi")
kontrol("olcek_dogrula: 1/2 kabul, 3/0/'x'/1.5 → Dur 1",
        ko.olcek_dogrula(1) == 1 and ko.olcek_dogrula("2") == 2 and
        all(dur_kodu(ko.olcek_dogrula, v) == 1 for v in (3, 0, "x", 1.5, True)))
kontrol("olcek_al: eski kayıt (alan yok) → 1", ko.olcek_al({}) == 1 and ko.olcek_al({"olcek": 2}) == 2 and
        masaustu.olcek(None) == 1)
os.environ["DESKHAND_ARKA_TUR"] = "xvfb"
try:
    masaustu.masaustu_baslat("1280x800", olcek=2)
    kod, mesaj = None, ""
except Dur as e:
    kod, mesaj = e.kod, e.mesaj
os.environ["DESKHAND_ARKA_TUR"] = "kwin"
kontrol("Xvfb türünde ölçek 2 → Dur (yalnız KWin), masaüstü AÇILMADI",
        kod == ARAC_EKSIK and "yalnız KWin" in mesaj and masaustu.durum() is None, f"{kod} {mesaj}")

# ---------------------------------------------------------------- 2) ölçek 2 KWin masaüstü
print("\n2) ölçek 2 masaüstü")
t = time.monotonic()
d = masaustu.masaustu_baslat("1280x800", olcek=2)
olcum["ölçek 2 masaüstü açılışı"] = f"{time.monotonic() - t:.1f} sn"
au = sec(arka_bayragi=True)
arka_uc._ORNEKLER["sanal"] = au
kontrol("kayıt: tür kwin, boyut 1280x800 (mantıksal), ölçek 2",
        masaustu.tur(d) == "kwin" and d["boyut"][:2] == [1280, 800] and masaustu.olcek(masaustu.durum()) == 2, str(d))
kontrol("liste: ölçek görünür", any(m["acik"] and m.get("olcek") == 2 for m in masaustu.liste(temizle=False)),
        str(masaustu.liste(temizle=False)))
import contextlib  # noqa: E402
import io  # noqa: E402

cikti = io.StringIO()
with contextlib.redirect_stdout(cikti):
    masaustu.main(["status"])
kontrol("desktop status: 'ölçek 2: ekran görüntüsü 2560x1600 piksel (koordinatlar 1280x800)'",
        "ölçek 2" in cikti.getvalue() and "2560x1600" in cikti.getvalue(), cikti.getvalue())
kontrol("ekran alanı mantıksal (0,0,1280,800); tam kare fiziksel 2560x1600",
        au.ekran_alani() == (0, 0, 1280, 800) and au.goruntu().size == (2560, 1600),
        f"{au.ekran_alani()} {au.goruntu().size}")
with ko.Eis(d) as e_:
    kontrol("EIS bölgesi mantıksal 1280x800 (tıklama kesirleri mantıksal ekrana)", e_.boyut == (1280, 800), str(e_.boyut))
zaten = masaustu.masaustu_baslat("1280x800", olcek=1)
kontrol("açıkken farklı ölçekle start → 'zaten' + uyarı (yeniden açılmaz)",
        zaten.get("zaten") and any("ölçek 2" in u for u in zaten.get("uyarilar") or []), str(zaten.get("uyarilar")))

# ---------------------------------------------------------------- 3) Qt penceresi: görüntü 2×, tık doğru ögeye
print("\n3) Qt penceresi (Wayland)")
p1 = au.baslat([sys.executable, PENCERE], {"LOG": LOG, "BASLIK": "olcek ANA"})
k = bekle(lambda: next((w for w, b, _ in au.pencereler("olcek ANA")), None), 15)
kontrol("pencere açıldı", k is not None)
if k is None:
    sys.exit(1)
geo = au.geometri(k)
kontrol("geometri mantıksal: 700x460 (ölçek 1 ile aynı düzen)", geo[2:] == (700, 460), str(geo))
with api.hedef("sanal"):
    bekle(lambda: kutu_bul(gorsel.pencere_goruntusu(k, tam=True)[0], (255, 0, 255)), 10, 0.2)  # ilk kare çizilsin
    tam_im, geo2, kok_ = gorsel.pencere_goruntusu(k, tam=True)
    man_im, _g, _k = gorsel.pencere_goruntusu(k)
tam_im.save(os.path.join(_yalitim.PAYLASIM, "qt-tam.png"))
kontrol("pencere_goruntusu(tam=True): 1400x920 (2×), piksel_olcegi 2; varsayılan: 700x460 (mantıksal)",
        tam_im.size == (1400, 920) and gorsel.piksel_olcegi(tam_im) == 2.0 and man_im.size == (700, 460),
        f"{tam_im.size} {gorsel.piksel_olcegi(tam_im)} {man_im.size}")
b2, b1 = kutu_bul(tam_im, (255, 0, 255)), kutu_bul(man_im, (255, 0, 255), 30)
oran = (b2[3] - b2[1] + 1) / (b1[3] - b1[1] + 1) if b1 and b2 else 0
olcum["Qt düğmesi yüksekliği (tam / mantıksal)"] = f"{b2[3] - b2[1] + 1 if b2 else '?'} / {b1[3] - b1[1] + 1 if b1 else '?'} px"
if not kontrol("düğme tam görüntüde ~2× piksel (1.9–2.1)", 1.9 <= oran <= 2.1, f"{b2} {b1}"):
    sys.exit(1)
cx, cy = (b2[0] + b2[2]) / 2 / 2, (b2[1] + b2[3]) / 2 / 2  # tam görüntü pikseli → pencere (mantıksal) pikseli
with api.hedef("sanal"):
    r = api.tikla(k, round(cx), round(cy))
kontrol("tıklama: tam görüntüden bulunan konum / 2 → 'tik: Kaydet' (EIS + mantıksal koordinat)",
        bekle(lambda: "tik: Kaydet" in loglar(), 4), f"{r} {loglar()[-3:]}")

# MCP screenshot eşlemesi: tam çözünürlük → max_edge küçültme; shot pikseli → pencere pikseli = kök + x / (ölçek·f)
with api.hedef("sanal"):
    im_m, geo_m, kok_m, mask_m = api.goruntu_al(k, tam=True)
f = gorsel.piksel_olcegi(im_m)
o = api.olcek_hesapla(*im_m.size, 1280)
from PIL import Image  # noqa: E402

kucuk = im_m.resize((round(im_m.width * o), round(im_m.height * o)), Image.LANCZOS) if o < 1 else im_m
sid = mcp_sunucu.cekim_kaydet(k, "sanal", geo_m, kok_m, o * f, kucuk.size)
bk = kutu_bul(kucuk, (255, 0, 255), 12)
px, py = mcp_sunucu.cekim_noktasi(mcp_sunucu._CEKIMLER[sid], (bk[0] + bk[2]) / 2, (bk[1] + bk[3]) / 2)
kontrol("MCP shot eşlemesi: küçültülmüş tam görüntüdeki düğme → pencere pikseli düğmenin içinde",
        b1 and b1[0] <= px <= b1[2] and b1[1] <= py <= b1[3], f"{px:.0f},{py:.0f} {b1} f={f} o={o:.3f}")
n0 = loglar().count("tik: Kaydet")
with api.hedef("sanal"):
    api.tikla(k, round(px), round(py))
kontrol("MCP shot eşlemesiyle tık da düğmeye gider", bekle(lambda: loglar().count("tik: Kaydet") > n0, 4))

# OCR
t = time.monotonic()
with api.hedef("sanal"):
    oc = api.metin_oku(k, "Kaydet")
olcum["OCR (Kaydet)"] = f"{(time.monotonic() - t) * 1000:.0f} ms"
it = (oc.get("items") or [None])[0]
kontrol("OCR (read_text): 'Kaydet' bulundu, merkezi düğmenin içinde (pencere pikseli)",
        it and b1 and b1[0] <= it["center"][0] <= b1[2] and b1[1] <= it["center"][1] <= b1[3], str(oc)[:300])

# MCP araçları (doğrudan çağrı): get_status / manage_desktop ölçeği, screenshot + shot_id tıklaması
import base64  # noqa: E402

st = mcp_sunucu.get_status(desktop="background")
md = mcp_sunucu.manage_desktop("status")
kontrol("MCP get_status background.scale 2, manage_desktop status scale 2",
        st["background"].get("scale") == 2 and md.get("scale") == 2, f"{st['background']} {md.get('scale')}")
sr = mcp_sunucu.screenshot(window=k, desktop="background")
sm = sr.structured_content
im_s = Image.open(io.BytesIO(base64.b64decode(sr.content[0].data)))
kontrol("MCP screenshot: max_edge 1280 içinde, scale = küçültme × 2 (1400 px'ten 1280'e: 1280/700)",
        max(im_s.size) <= 1280 and abs(sm["scale"] - im_s.width / 700) < 0.01, f"{im_s.size} {sm['scale']}")
bs = kutu_bul(im_s, (255, 0, 255), 12)
n0 = loglar().count("tik: Kaydet")
rs, hs = None, None
try:
    rs = mcp_sunucu.click(window=k, x=(bs[0] + bs[2]) / 2, y=(bs[1] + bs[3]) / 2, shot_id=sm["shot_id"],
                          verify=False, desktop="background")
except Exception as e:  # noqa: BLE001
    hs = str(e)
kontrol("MCP click(shot_id): düğmeye gider", bs and hs is None and bekle(lambda: loglar().count("tik: Kaydet") > n0, 4),
        f"{bs} {hs} {str(rs)[:200]}")

# CLI screenshot --out (tam çözünürlük) ve --width (küçültme)
dosya = os.path.join(_yalitim.GECICI, "tam.png")
with api.hedef("sanal"):
    gorsel.k_foto(argparse.Namespace(kimlik=k, bolge=None, genislik=None, izgara=None, cikti=dosya))
    foto = json.load(open(yollar.son_foto()))
    kucuk_dosya = os.path.join(_yalitim.GECICI, "kucuk.png")
    gorsel.k_foto(argparse.Namespace(kimlik=k, bolge=None, genislik=700, izgara=None, cikti=kucuk_dosya))
    foto2 = json.load(open(yollar.son_foto()))
kontrol("CLI screenshot --out: dosya TAM çözünürlük 1400x920, son_foto ölçeği 2",
        Image.open(dosya).size == (1400, 920) and foto["olcek"] == 2.0, f"{Image.open(dosya).size} {foto['olcek']}")
kontrol("CLI screenshot --width 700: 700x460, ölçek 1 (mantıksal ile aynı)",
        Image.open(kucuk_dosya).size == (700, 460) and abs(foto2["olcek"] - 1.0) < 1e-6,
        f"{Image.open(kucuk_dosya).size} {foto2['olcek']}")
au.kapat(k)
bekle(lambda: p1.poll() is not None, 5)

# ---------------------------------------------------------------- 4) Firefox (XWayland) 2× çizer, AT-SPI tık doğru
print("\n4) Firefox (XWayland)")
import web_tarayici as wt  # noqa: E402

srv = wt.Sunucu()
ff2 = None
try:
    ff2, baslik2, im2, kutu2, mur2 = firefox_olc(au, srv, 2)
    kontrol("Firefox devicePixelRatio 2 (GDK_SCALE)", "dpr=2" in baslik2, baslik2)
    kg = (kutu2[2] - kutu2[0] + 1, kutu2[3] - kutu2[1] + 1) if kutu2 else None
    kontrol("CSS 100x20 kutu tam görüntüde ~200x40 piksel", kg and abs(kg[0] - 200) <= 3 and abs(kg[1] - 40) <= 3,
            str(kg))
    bellek = os.path.join("/sys/fs/cgroup" + (d.get("cgroup") or "/yok"), "memory.current")
    if os.path.exists(bellek):
        olcum["kafes belleği (ölçek 2 + Firefox)"] = f"{int(open(bellek).read()) / 2**20:.0f} MiB / {d.get('bellek')}"
    with api.hedef("sanal"):
        try:
            r = api.ogeye_tikla(ff2.k, "Kaydet", rol="push button")
        except Dur as e:
            r = f"Dur {e.kod}: {e.mesaj}"
    kontrol("Firefox: AT-SPI ögesine (düğme 'Kaydet') gerçek fare tıklaması → sayfa 'olcek tiklandi'",
            bekle(lambda: "olcek tiklandi" in au.baslik(ff2.k), 5), f"{r} {au.baslik(ff2.k)}")
finally:
    if ff2 is not None:
        ff2.kapat()

# Chromium (XWayland, --ozone-platform=x11): Deskhand --force-device-scale-factor=2 ekler
if shutil.which("chromium"):
    import tempfile  # noqa: E402

    profil = tempfile.mkdtemp(prefix="chromium-", dir=_yalitim.PAYLASIM)
    from deskhand.uygulama import ERISIM_BAYRAGI  # noqa: E402

    t = time.monotonic()
    pc = au.baslat(["chromium", ERISIM_BAYRAGI, f"--user-data-dir={profil}", "--no-first-run",
                    "--no-default-browser-check", "--password-store=basic", "--disable-gpu", srv.url("olcek.html")],
                   {"XDG_CONFIG_HOME": profil, "XDG_CACHE_HOME": profil})
    try:
        kc = bekle(lambda: next((w for w, b, _ in au.pencereler("dpr=") if pc.pid in wt.ata_pidler(au.pid(w))), None),
                   40, 0.2)
        olcum["Chromium açılışı (ölçek 2)"] = f"{time.monotonic() - t:.1f} sn"
        kontrol("Chromium devicePixelRatio 2 (--force-device-scale-factor)", kc and "dpr=2" in au.baslik(kc),
                au.baslik(kc) if kc else "pencere yok")
        if kc:
            with api.hedef("sanal"):
                imc = bekle(lambda: (lambda im_: im_ if kutu_bul(im_, (255, 0, 255), 2) else None)(
                    api.goruntu_al(kc, tam=True)[0]), 15, 0.2)
            kc_ = kutu_bul(imc, (255, 0, 255), 2) if imc else None
            kg = (kc_[2] - kc_[0] + 1, kc_[3] - kc_[1] + 1) if kc_ else None
            kontrol("Chromium: CSS 100x20 kutu tam görüntüde ~200x40 piksel",
                    kg and abs(kg[0] - 200) <= 3 and abs(kg[1] - 40) <= 3, str(kg))
            au.kapat(kc)
    finally:
        if pc.poll() is None:
            bekle(lambda: pc.poll() is not None, 5)
        if pc.poll() is None:
            pc.terminate()
masaustu.masaustu_durdur()

# ---------------------------------------------------------------- 5) ölçek 1 (varsayılan) değişmedi + metin oranı
print("\n5) ölçek 1 (varsayılan)")
d1 = masaustu.masaustu_baslat("1280x800")
au = sec(arka_bayragi=True)
arka_uc._ORNEKLER["sanal"] = au
kontrol("varsayılan ölçek 1: kare 1280x800, kayıtta olcek 1", au.goruntu().size == (1280, 800) and
        masaustu.olcek(d1) == 1, str(au.goruntu().size))
ff1 = None
try:
    ff1, baslik1, im1, kutu1, mur1 = firefox_olc(au, srv, 1)
    kontrol("ölçek 1 Firefox: dpr=1, CSS kutu 100x20", "dpr=1" in baslik1 and kutu1 and
            abs(kutu1[2] - kutu1[0] + 1 - 100) <= 2, f"{baslik1} {kutu1}")
    olcum["14px metin mürekkep yüksekliği (ölçek 2 / ölçek 1)"] = f"{mur2} / {mur1} px"
    kontrol("14px metin: ölçek 2'de mürekkep yüksekliği ölçek 1'in ~2 katı (1.7–2.3)",
            mur1 > 0 and 1.7 <= mur2 / mur1 <= 2.3, f"{mur2} / {mur1}")
finally:
    if ff1 is not None:
        ff1.kapat()
    srv.kapat()
masaustu.masaustu_durdur()
kontrol("masaüstü kapandı", masaustu.durum() is None and masalar.secili() == "")

print("\nölçümler:")
for a, v in olcum.items():
    print(f"  {a}: {v}")
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
