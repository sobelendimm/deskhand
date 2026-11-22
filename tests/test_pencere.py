"""Pencere yönetimi (taşı / boyutlandır / küçült / büyüt / geri yükle) testleri. Kullanıcının GERÇEK ekranına ve
pencerelerine HİÇBİR şey gitmez:

A) kde arka ucu: `kde.kd` TAKLİT edilir (gerçek kdotool/KWin çağrılmaz) → doğru kdotool argümanları, oyun/film
   koruması (15), karar bildirimi (12), masaüstü kipi reddi.
B) Çekirdek (eylem.pencere_yonet) + CLI + MCP manage_window: sahte arka uçla → ekran dışı (2), yasak (10), DUR (13),
   başlık kilidi (4), desteklenmeyen arka uç (9), uyarı, ayrıştırıcı (İngilizce/Türkçe adlar, eksi sayılar).
C) Sanal masaüstü (Xvfb + openbox): gerçek EWMH ile taşı/boyutlandır/büyüt/küçült/geri; CLI ve MCP ucu uca.

Çalıştır:  python3 tests/test_pencere.py      (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import asyncio
import atexit
import os
import re
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import arka_uc, cli, guvenlik, hata, komutlar, masaustu, mesgul, yollar
from deskhand.arka_uc import ArkaUc, kde
from deskhand.hata import Dur

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
gecen = toplam = 0


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
    except SystemExit as e:
        return e.code
    return None


def bekle(kosul, sure=5.0, aralik=0.02):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


# ================================================================ A) kde arka ucu: kd() taklidi

cagrilar = []
asil_kd = kde.kd
kde.kd = lambda *a: cagrilar.append(a) or ""
asil_koruma, asil_karar = mesgul.ekran_korumasi, mesgul.karar_bekliyor
koruma = {"neden": None, "karar": False}
mesgul.ekran_korumasi = lambda p=None, oynaticilar=None: koruma["neden"]
mesgul.karar_bekliyor = lambda: koruma["karar"]

kau = kde.KdeArkaUc()
W = "{11111111-2222-3333-4444-555555555555}"
kau.tasi(W, 120, 340)
kau.boyutlandir(W, 800, 600)
kau.kucult(W)
kau.buyut(W)
kau.geri_yukle(W)
kontrol("kde: tasi → kdotool windowmove X Y", cagrilar[0] == ("windowmove", W, "120", "340"), str(cagrilar[:1]))
kontrol("kde: boyutlandir → kdotool windowsize G Y", cagrilar[1] == ("windowsize", W, "800", "600"), str(cagrilar[1:2]))
kontrol("kde: kucult → kdotool windowminimize", cagrilar[2] == ("windowminimize", W), str(cagrilar[2:3]))
kontrol("kde: buyut → windowstate --add MAXIMIZED", cagrilar[3] == ("windowstate", "--add", "MAXIMIZED", W),
        str(cagrilar[3:4]))
kontrol("kde: geri_yukle → windowstate --remove MINIMIZED --remove MAXIMIZED",
        cagrilar[4] == ("windowstate", "--remove", "MINIMIZED", "--remove", "MAXIMIZED", W), str(cagrilar[4:5]))
kontrol("kde: 5 işlem = 5 kdotool çağrısı, eylemler yeniden DENENMEZ", len(cagrilar) == 5)
cagrilar.clear()

koruma["neden"] = "tam ekranda (oyun/film)"
kodlar = [dur_kodu(f, *a) for f, a in ((kau.tasi, (W, 1, 1)), (kau.boyutlandir, (W, 9, 9)), (kau.kucult, (W,)),
                                       (kau.buyut, (W,)), (kau.geri_yukle, (W,)))]
kontrol("kde: kullanıcı oyunda/film izlerken 5 işlem de Dur 15", kodlar == [15] * 5, str(kodlar))
kontrol("kde: Dur 15'te kdotool HİÇ çağrılmadı", cagrilar == [], str(cagrilar))
koruma["neden"], koruma["karar"] = None, True
kontrol("kde: karar bildirimi açıkken Dur 12 (one_getir ile aynı koruma)", dur_kodu(kau.tasi, W, 1, 1) == 12 and cagrilar == [])
koruma["karar"] = False
kontrol("kde: masaüstü kipi (EKRAN) taşınamaz → Dur 1", dur_kodu(kau.tasi, arka_uc.EKRAN, 1, 1) == 1 and cagrilar == [])
kde.kd = asil_kd
mesgul.ekran_korumasi, mesgul.karar_bekliyor = asil_koruma, asil_karar


# ================================================================ B) çekirdek + CLI + MCP: sahte arka uç

class SahteArka(ArkaUc):
    """Ön plan (kde) yerine: 1920x1080, iki pencere. Pencere işlemleri geometriyi gerçekten değiştirir."""
    ad = "kde"

    def __init__(self):
        self.pen = {"{sahte-1}": ["Pencere Bir", "bir", [100, 100, 800, 600]],
                    "{sahte-2}": ["Gizli Defter", "defter", [900, 100, 500, 400]]}
        self.kayit, self.onceki = [], {}
        self.kaydirma = (0, 0)  # pencere yöneticisi "bozuntusu": istenen konuma eklenir

    def _w(self, k):
        if k not in self.pen:
            raise Dur(8, "pencere yok")
        return self.pen[k]

    def pencere_coz(self, arg):
        if arg in self.pen:
            return arg
        if arg.lower() in ("ekran", "masaustu"):
            return arka_uc.EKRAN
        uy = [k for k, (b, _, _) in self.pen.items() if re.search(arg, b, re.I)]
        if not uy:
            raise Dur(8, f"'{arg}' yok")
        return uy[0]

    def pencereler(self, desen=None):
        return [(k, b, tuple(g)) for k, (b, _, g) in self.pen.items() if not desen or re.search(desen, b, re.I)]

    def geometri(self, k):
        return tuple(self._w(k)[2])

    def baslik(self, k):
        return self._w(k)[0]

    def sinif(self, k):
        return self._w(k)[1]

    def aktif(self):
        return "{sahte-1}"

    def one_getir(self, k):
        pass

    def kapat(self, k):
        self.kayit.append(("kapat", k))
        self.pen.pop(k, None)

    def fare(self):
        return (0, 0, "")

    def ekran_alani(self):
        return (0, 0, 1920, 1080)

    def goruntu(self):
        raise NotImplementedError

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        raise NotImplementedError

    def insan_var_mi(self):
        return False

    def baslat(self, argv, env=None, cikti=None):
        raise NotImplementedError

    def tasi(self, k, x, y):
        self.kayit.append(("tasi", k, x, y))
        g = self._w(k)[2]
        g[0], g[1] = x + self.kaydirma[0], y + self.kaydirma[1]

    def boyutlandir(self, k, g_, y):
        self.kayit.append(("boyutlandir", k, g_, y))
        g = self._w(k)[2]
        g[2], g[3] = g_, y

    def kucult(self, k):
        self.kayit.append(("kucult", k))

    def buyut(self, k):
        self.kayit.append(("buyut", k))
        self.onceki[k] = list(self._w(k)[2])
        self._w(k)[2][:] = [0, 0, 1920, 1080]

    def geri_yukle(self, k):
        self.kayit.append(("geri_yukle", k))
        self._w(k)[2][:] = self.onceki.get(k, self._w(k)[2])


from deskhand import api, eylem  # noqa: E402

sahte = SahteArka()
arka_uc._ORNEKLER["kde"] = sahte
os.environ.pop("DESKHAND_HEDEF", None)
os.environ.pop("DESKHAND_MCP_SADECE_ARKA", None)
os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True)
with open(yollar.yasak_dosya(), "w") as f:
    f.write("^Gizli\n")
W1, W2 = "{sahte-1}", "{sahte-2}"


# --- çekirdek: başarılı yollar
r = eylem.pencere_yonet(W1, "tasi", 200, 150)
kontrol("çekirdek: tasi → arka uç tasi(200,150), geometri yeni konumda",
        sahte.kayit[-1] == ("tasi", W1, 200, 150) and r["geometri"] == (200, 150, 800, 600) and
        r["onceki"] == (100, 100, 800, 600) and r["uyari"] == "", str(r))
r = eylem.pencere_yonet(W1, "boyut", g=640, h=480)
kontrol("çekirdek: boyut → arka uç boyutlandir(640,480)", sahte.kayit[-1] == ("boyutlandir", W1, 640, 480) and
        r["geometri"] == (200, 150, 640, 480), str(r))
r = eylem.pencere_yonet(W1, "buyut")
kontrol("çekirdek: buyut → ekranı kaplar", sahte.kayit[-1] == ("buyut", W1) and r["geometri"] == (0, 0, 1920, 1080), str(r))
r = eylem.pencere_yonet(W1, "geri")
kontrol("çekirdek: geri → büyütmeden önceki geometri", sahte.kayit[-1] == ("geri_yukle", W1) and
        r["geometri"] == (200, 150, 640, 480), str(r))
r = eylem.pencere_yonet(W1, "kucult")
kontrol("çekirdek: kucult → arka uç kucult", sahte.kayit[-1] == ("kucult", W1) and r["geometri"] == (200, 150, 640, 480), str(r))
gl = ""
for ad_ in os.listdir(yollar.gunluk_dizin()):
    gl += open(os.path.join(yollar.gunluk_dizin(), ad_), errors="replace").read()
kontrol("çekirdek: işlemler günlüğe yazıldı (başlık + işlem + geometri)",
        "pencere | [Pencere Bir] | tasi 200 150" in gl and "pencere | [Pencere Bir] | boyut 640 480" in gl and
        "pencere | [Pencere Bir] | buyut |" in gl, gl[-400:])

# --- çekirdek: ekran dışı (2): arka uç hiç çağrılmaz
sahte.kayit.clear()
kodlar = [dur_kodu(eylem.pencere_yonet, W1, "tasi", 1500, 100),    # sağ kenar 1500+640 > 1920
          dur_kodu(eylem.pencere_yonet, W1, "tasi", -5, 100),
          dur_kodu(eylem.pencere_yonet, W1, "tasi", 100, 1000),    # alt kenar 1000+480 > 1080
          dur_kodu(eylem.pencere_yonet, W1, "boyut", g=2000, h=100),
          dur_kodu(eylem.pencere_yonet, W1, "boyut", g=1800, h=300)]   # x=200 + 1800 > 1920
kontrol("çekirdek: ekran alanı dışına taşan taşıma/boyut → Dur 2", kodlar == [2] * 5, str(kodlar))
kontrol("çekirdek: Dur 2'de arka uç çağrılmadı, geometri aynı", sahte.kayit == [] and sahte.geometri(W1) == (200, 150, 640, 480))
kontrol("çekirdek: tam sınırda (sağ-alt köşe tam oturan) taşıma serbest",
        dur_kodu(eylem.pencere_yonet, W1, "tasi", 1920 - 640, 1080 - 480) is None)
eylem.pencere_yonet(W1, "tasi", 200, 150)
kontrol("çekirdek: boyut 0 / eksik değer → Dur 1", dur_kodu(eylem.pencere_yonet, W1, "boyut", g=0, h=10) == 1 and
        dur_kodu(eylem.pencere_yonet, W1, "tasi", 5, None) == 1 and
        dur_kodu(eylem.pencere_yonet, W1, "uc-boyut") == 1)
kontrol("çekirdek: masaüstü kipi (EKRAN) → Dur 1", dur_kodu(eylem.pencere_yonet, arka_uc.EKRAN, "tasi", 1, 1) == 1)

# --- çekirdek: yasak (10), DUR (13), başlık kilidi (4)
sahte.kayit.clear()
g2 = sahte.geometri(W2)
kodlar = [dur_kodu(eylem.pencere_yonet, W2, i, 10, 10) if i == "tasi" else dur_kodu(eylem.pencere_yonet, W2, i)
          for i in ("tasi", "kucult", "buyut", "geri")]
kontrol("çekirdek: yasak pencerede 4 işlem de Dur 10", kodlar == [10] * 4, str(kodlar))
kontrol("çekirdek: yasak pencerede arka uç çağrılmadı", sahte.kayit == [] and sahte.geometri(W2) == g2)
guvenlik.dur_ac("cli")
kontrol("çekirdek: DUR açıkken Dur 13, arka uç çağrılmadı",
        dur_kodu(eylem.pencere_yonet, W1, "tasi", 10, 10) == 13 and sahte.kayit == [])
guvenlik.dur_kapat("cli")
kontrol("çekirdek: başlık kilidi uymazsa Dur 4, uyarsa serbest",
        dur_kodu(eylem.pencere_yonet, W1, "tasi", 10, 10, desen="^Baska$") == 4 and sahte.kayit == [] and
        dur_kodu(eylem.pencere_yonet, W1, "tasi", 10, 10, desen="^Pencere B") is None)
guvenlik.SINIF_DESEN = "^baska$"
kontrol("çekirdek: sınıf kilidi (-s) uymazsa Dur 4", dur_kodu(eylem.pencere_yonet, W1, "tasi", 20, 20) == 4)
guvenlik.SINIF_DESEN = None

# --- çekirdek: pencere yöneticisi farklı geometri verirse uyarı
sahte.kaydirma = (7, 0)
r = eylem.pencere_yonet(W1, "tasi", 300, 300)
kontrol("çekirdek: pencere yöneticisi konumu değiştirdiyse uyarı döner", r["uyari"] != "" and r["geometri"][0] == 307, str(r))
sahte.kaydirma = (0, 0)

# --- desteklenmeyen arka uç: varsayılan Dur 9
Bos = type("Bos", (ArkaUc,), {m: (lambda self, *a, **k: None) for m in ArkaUc.__abstractmethods__} | {"ad": "bos"})
bos = Bos()
kodlar = [dur_kodu(f, *a) for f, a in ((bos.tasi, ("k", 1, 1)), (bos.boyutlandir, ("k", 1, 1)), (bos.kucult, ("k",)),
                                       (bos.buyut, ("k",)), (bos.geri_yukle, ("k",)))]
kontrol("arka uç varsayılanı: desteklenmiyor → Dur 9 (5 işlem)", kodlar == [9] * 5, str(kodlar))

# --- CLI ayrıştırıcı + komut tablosu
ay = cli.ayristirici(sessiz=True)
a = ay.parse_args(["window", "Pencere", "move", "10", "20"])
kontrol("CLI: window <k> move X Y ayrışır (komut=pencere, islem=tasi)", (a.komut, a.islem, a.deger) == ("pencere", "tasi", ["10", "20"]))
a = ay.parse_args(["pencere", "Pencere", "tasi", "-100", "20"])
kontrol("CLI: Türkçe 'pencere … tasi' ve eksi sayı (çok ekranlı) ayrışır", (a.islem, a.deger) == ("tasi", ["-100", "20"]))
eslesme = [("resize", "boyut", ["640", "480"]), ("minimize", "kucult", []), ("maximize", "buyut", []),
           ("restore", "geri", []), ("boyut", "boyut", ["1", "2"]), ("kucult", "kucult", []), ("buyut", "buyut", []),
           ("geri", "geri", [])]
sonuc = []
for ad_, ic, deg in eslesme:
    b = ay.parse_args(["window", "P", ad_, *deg])
    sonuc.append((b.islem, b.deger) == (ic, deg))
kontrol("CLI: 5 işlemin İngilizce + Türkçe adları iç adlara çevrilir", all(sonuc), str(sonuc))
try:
    ay.parse_args(["window", "P", "ucur"])
    gecersiz = False
except Exception:  # noqa: BLE001
    gecersiz = True
kontrol("CLI: bilinmeyen işlem reddedilir", gecersiz)
kontrol("CLI: doctor/doktor ayrışır", ay.parse_args(["doctor", "--json"]).komut == "doktor" and
        ay.parse_args(["doktor"]).komut == "doktor")
tr = [t for t, _ in komutlar.KOMUTLAR]
kontrol("KOMUTLAR: pencere, doktor satırları 'yardım'dan önce, pencere→doktor sıralı",
        tr.index("pencere") + 1 == tr.index("doktor") and tr.index("doktor") + 1 == tr.index("yardım"), str(tr[-5:]))
kontrol("KOMUTLAR: window/doctor İngilizce adları", komutlar.TR_EN["pencere"] == "window" and komutlar.EN_TR["doctor"] == "doktor")
kontrol("CLI: pencere GIRDI_KOMUTLARI'nda (DUR + yasak denetimi main'de)", "pencere" in eylem.GIRDI_KOMUTLARI)

import argparse  # noqa: E402
ns_ = lambda islem, *deg, baslik=None: argparse.Namespace(kimlik=W1, islem=islem, deger=list(deg), baslik=baslik)  # noqa: E731
kontrol("CLI: değer sayısı yanlış → Dur 1", dur_kodu(eylem.k_pencere, ns_("tasi", "5")) == 1 and
        dur_kodu(eylem.k_pencere, ns_("kucult", "5")) == 1 and dur_kodu(eylem.k_pencere, ns_("boyut")) == 1)
kontrol("CLI: değerler sayı değilse Dur 1", dur_kodu(eylem.k_pencere, ns_("tasi", "a", "b")) == 1)

# --- CLI uçtan uca (süreç içi main + sahte arka uç)
import contextlib  # noqa: E402
import io  # noqa: E402
sahte.kayit.clear()
cikti = io.StringIO()
with contextlib.redirect_stdout(cikti):
    kod = dur_kodu(cli.main, ["window", "Pencere", "move", "50", "60"])
kontrol("CLI main: window … move → çıkış 0, çıktıda yeni geometri", kod is None and "50,60" in cikti.getvalue() and
        sahte.kayit[-1] == ("tasi", W1, 50, 60), cikti.getvalue())
with contextlib.redirect_stderr(io.StringIO()):
    kod = dur_kodu(cli.main, ["window", "Pencere", "move", "5000", "60"])
kontrol("CLI main: ekran dışı → çıkış 2", kod == 2, str(kod))
with contextlib.redirect_stderr(io.StringIO()):
    kod = dur_kodu(cli.main, ["pencere", "Gizli", "kucult"])
kontrol("CLI main: yasak pencere → çıkış 10 (cli.main yasak denetimi)", kod == 10, str(kod))
guvenlik.dur_ac("cli")
with contextlib.redirect_stderr(io.StringIO()):
    kod = dur_kodu(cli.main, ["window", "Pencere", "minimize"])
guvenlik.dur_kapat("cli")
kontrol("CLI main: DUR açıkken çıkış 13", kod == 13, str(kod))
guvenlik.SINIF_DESEN = None

# --- MCP manage_window (sahte ön plan)
from deskhand import mcp_sunucu as ms  # noqa: E402
from mcp import Client  # noqa: E402


def yapi(r):
    return r.structured_content or {}


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


async def mcp_testleri():
    sahte.pen["{sahte-1}"][2][:] = [100, 100, 800, 600]
    sahte.kayit.clear()
    async with Client(ms.mcp) as c:
        adlar = [t.name for t in (await c.list_tools()).tools]
        kontrol("MCP: manage_window open_app'ten hemen sonra listelenir", "manage_window" in adlar and
                adlar.index("manage_window") == adlar.index("open_app") + 1, str(adlar))
        t = next(t for t in (await c.list_tools()).tools if t.name == "manage_window")
        kontrol("MCP: manage_window annotations = YUMUSAK (yıkıcı değil, açık dünya)",
                t.annotations is not None and t.annotations.destructive_hint is False and t.annotations.read_only_hint is False,
                str(t.annotations))
        r = await c.call_tool("manage_window", {"window": "Pencere", "action": "move", "x": 300, "y": 200,
                                                "desktop": "foreground"})
        s = yapi(r)
        kontrol("MCP: move → status moved + yeni geometri", not r.is_error and s.get("status") == "moved" and
                s["window"]["geometry"] == [300, 200, 800, 600] and s["previous_geometry"] == [100, 100, 800, 600], metin(r))
        r = await c.call_tool("manage_window", {"window": "Pencere", "action": "resize", "width": 400, "height": 300,
                                                "desktop": "foreground"})
        kontrol("MCP: resize", yapi(r).get("window", {}).get("geometry") == [300, 200, 400, 300], metin(r))
        for eylem_, durum in (("maximize", "maximized"), ("restore", "restored"), ("minimize", "minimized")):
            r = await c.call_tool("manage_window", {"window": "Pencere", "action": eylem_, "desktop": "foreground"})
            kontrol(f"MCP: {eylem_} → {durum}", not r.is_error and yapi(r).get("status") == durum, metin(r))
        r = await c.call_tool("manage_window", {"window": "Pencere", "action": "move", "x": 5, "desktop": "foreground"})
        kontrol("MCP: move y'siz → [1]", r.is_error and "[1]" in metin(r), metin(r))
        r = await c.call_tool("manage_window", {"window": "Pencere", "action": "resize", "width": 5,
                                                "desktop": "foreground"})
        kontrol("MCP: resize height'sız → [1]", r.is_error and "[1]" in metin(r), metin(r))
        r = await c.call_tool("manage_window", {"window": "Pencere", "action": "move", "x": 1900, "y": 0,
                                                "desktop": "foreground"})
        kontrol("MCP: ekran dışı move → [2], pencere yerinde", r.is_error and "[2]" in metin(r) and
                sahte.geometri(W1)[0] == 300, metin(r))
        r = await c.call_tool("manage_window", {"window": "Gizli", "action": "maximize", "desktop": "foreground"})
        kontrol("MCP: yasak pencere → [10]", r.is_error and "[10]" in metin(r), metin(r))
        r = await c.call_tool("manage_window", {"window": "Gizli", "action": "close", "desktop": "foreground"})
        kontrol("MCP: yasak pencere close → [10], kapanmadı", r.is_error and "[10]" in metin(r) and W2 in sahte.pen, metin(r))
        guvenlik.dur_ac("cli")
        r = await c.call_tool("manage_window", {"window": "Pencere", "action": "minimize", "desktop": "foreground"})
        r2 = await c.call_tool("manage_window", {"window": "Pencere", "action": "close", "desktop": "foreground"})
        guvenlik.dur_kapat("cli")
        kontrol("MCP: DUR açıkken [13] (taşıma ve close)", r.is_error and "[13]" in metin(r) and r2.is_error and
                "[13]" in metin(r2) and W1 in sahte.pen, metin(r) + metin(r2))
        # oyun/film koruması: sahte arka ucun kendisi 15 vermez; gerçek kde sınıfının koruması A) bölümünde sınandı
        sahte.kayit.clear()
        r = await c.call_tool("manage_window", {"window": W1, "action": "close", "desktop": "foreground"})
        kontrol("MCP: close (kimlikle) mevcut kapatma yolunu çağırır → kapandı", not r.is_error and
                yapi(r).get("status") == "closed" and W1 not in sahte.pen and sahte.kayit == [("kapat", W1)], metin(r))


asyncio.run(mcp_testleri())

# ================================================================ C) sanal masaüstü (gerçek EWMH)

arka_uc._ORNEKLER.pop("kde", None)
os.environ["DESKHAND_HEDEF"] = "arka"  # bu süreçte sec() hep sanal arka uç: gerçek kde'ye hiçbir şey gitmez
t = time.monotonic()
d = masaustu.masaustu_baslat()
au = arka_uc.sec("arka:0x1")
sw, sh = au.ekran_alani()[2:]
print(f"sanal masaüstü ({masaustu.tur(d)}) {d['ekran']} {sw}x{sh} ({(time.monotonic() - t) * 1000:.0f} ms)")
BAGLANTILAR = []
KW = masaustu.tur(d) == "kwin"
# KWin türünde test penceresi: en küçük Qt penceresi (Wayland; konumu KWin seçer, sonra taşınır)
QT_PENCERE = ("import sys\nfrom PyQt6.QtWidgets import QApplication, QWidget\napp = QApplication(sys.argv)\n"
              "w = QWidget(); w.setWindowTitle(sys.argv[1]); w.setMinimumSize(100, 80); w.resize(int(sys.argv[2]), "
              "int(sys.argv[3])); w.show(); app.exec()")


def x_pencere(baslik, x, y, g, h):
    """Kendi bağlantısıyla sanal ekranda bir pencere (kapatma XKillClient'ı yalnız bu bağlantıyı öldürür). KWin türünde
    Wayland Qt penceresi (aynı başlık/boyut), sonra arka ucun taşı yöntemiyle (x, y)'ye."""
    if KW:
        au.baslat([sys.executable, "-c", QT_PENCERE, baslik, str(g), str(h)])
        k = bekle(lambda: next((k for k, b, _ in au.pencereler(re.escape(baslik))), None), 15, 0.05)
        if k:
            au.tasi(k, x, y)
            bekle(lambda: au.geometri(k)[:2] == (x, y), 3, 0.05)
        return None, None, k
    from Xlib import X
    dpy = masaustu.x_ac(d["ekran"])
    ek = dpy.screen()
    w = ek.root.create_window(x, y, g, h, 0, ek.root_depth, X.InputOutput, X.CopyFromParent,
                              background_pixel=ek.white_pixel, event_mask=X.StructureNotifyMask)
    w.set_wm_name(baslik)
    w.set_wm_normal_hints(flags=(1 << 2) | (1 << 0), x=x, y=y, width=g, height=h)  # PPosition|USPosition benzeri
    w.map()
    dpy.sync()
    BAGLANTILAR.append(dpy)
    k = bekle(lambda: next((k for k, b, _ in au.pencereler(re.escape(baslik))), None), 10, 0.05)
    return dpy, w, k


_, _, KA = x_pencere("pencere-test A", 60, 70, 300, 200)
_, _, KB = x_pencere("pencere-test GIZLI", 400, 70, 300, 200)
kontrol("sanal: iki test penceresi açıldı", bool(KA) and bool(KB), f"{KA} {KB}")
G0 = au.geometri(KA)
st = (au.pencere_durumu if KW else  # noqa: E731
      lambda k: au._cagir(lambda x: x.wm_durumu(int(k.split("0x")[1], 16))))


def geo_bekle(k, tut, sure=3.0):
    return bekle(lambda: tut(au.geometri(k)), sure, 0.05)


r = eylem.pencere_yonet(KA, "tasi", 200, 150)
kontrol("sanal: taşı → istemci alanı (200,150)'de, boyut aynı", r["geometri"][:2] == (200, 150) and r["geometri"][2:] == G0[2:] and
        au.geometri(KA)[:2] == (200, 150), f"{G0} → {r}")
r = eylem.pencere_yonet(KA, "boyut", g=420, h=310)
kontrol("sanal: boyutlandır → 420x310, konum aynı", r["geometri"] == (200, 150, 420, 310), str(r))
oncesi = au.geometri(KA)
r = eylem.pencere_yonet(KA, "buyut")
kontrol("sanal: büyüt → _NET_WM_STATE maximized, ekranı (çerçeve payıyla) kaplar",
        "maximized" in st(KA) and r["geometri"][2] >= sw * 0.9 and r["geometri"][3] >= sh * 0.85, f"{r} {st(KA)}")
r = eylem.pencere_yonet(KA, "geri")
# openbox, büyütmeden dönerken kayıtlı alanı çerçeve köşesi sayar: istemci alanı çerçeve payı (~1, ~18 px) kayar
kontrol("sanal: geri → büyütme kalktı, boyut aynı, konum çerçeve payı içinde",
        "maximized" not in st(KA) and r["geometri"][2:] == oncesi[2:] and abs(r["geometri"][0] - oncesi[0]) <= 25 and
        abs(r["geometri"][1] - oncesi[1]) <= 25, f"{oncesi} → {r} {st(KA)}")
oncesi = au.geometri(KA)
r = eylem.pencere_yonet(KA, "kucult")
kontrol("sanal: küçült → simge durumunda (hidden)", "hidden" in st(KA), str(st(KA)))
r = eylem.pencere_yonet(KA, "geri")
kontrol("sanal: küçültülmüşü geri yükle → hidden kalktı, geometri aynı", "hidden" not in st(KA) and r["geometri"] == oncesi, f"{r} {st(KA)}")
eylem.pencere_yonet(KA, "kucult")
r = eylem.pencere_yonet(KA, "buyut")
kontrol("sanal: küçültülmüşken büyüt → maximized", "maximized" in st(KA), str(st(KA)))
eylem.pencere_yonet(KA, "geri")
eylem.pencere_yonet(KA, "geri")
kontrol("sanal: tekrar geri → normal (hidden/maximized yok)", not ({"hidden", "maximized"} & st(KA)), str(st(KA)))

g1 = au.geometri(KA)
kodlar = [dur_kodu(eylem.pencere_yonet, KA, "tasi", sw, 0), dur_kodu(eylem.pencere_yonet, KA, "tasi", 0, sh),
          dur_kodu(eylem.pencere_yonet, KA, "boyut", g=sw + 1, h=100), dur_kodu(eylem.pencere_yonet, KA, "tasi", -1, 0)]
kontrol("sanal: ekran dışı → Dur 2, pencere yerinde", kodlar == [2] * 4 and au.geometri(KA) == g1, f"{kodlar} {au.geometri(KA)} {g1}")

# yasak + DUR + başlık kilidi (gerçek pencerelerde)
with open(yollar.yasak_dosya(), "w") as f:
    f.write("GIZLI\n")
gB = au.geometri(KB)
kodlar = [dur_kodu(eylem.pencere_yonet, KB, "tasi", 10, 10), dur_kodu(eylem.pencere_yonet, KB, "kucult"),
          dur_kodu(eylem.pencere_yonet, KB, "buyut")]
kontrol("sanal: yasak pencere → Dur 10, pencere yerinde ve görünür", kodlar == [10] * 3 and au.geometri(KB) == gB and
        "hidden" not in st(KB), f"{kodlar} {st(KB)}")
guvenlik.dur_ac("cli")
kontrol("sanal: DUR → Dur 13, pencere yerinde", dur_kodu(eylem.pencere_yonet, KA, "tasi", 10, 10) == 13 and au.geometri(KA) == g1)
guvenlik.dur_kapat("cli")
kontrol("sanal: başlık kilidi uymazsa Dur 4, pencere yerinde", dur_kodu(eylem.pencere_yonet, KA, "tasi", 10, 10, desen="^yok$") == 4
        and au.geometri(KA) == g1)

# CLI uçtan uca (alt süreç): --arka window … move
def cli_kos(*arg):
    return subprocess.run([sys.executable, "-m", "deskhand", *arg], capture_output=True, text=True, cwd=KOK, timeout=60)


r = cli_kos("--arka", "window", KA, "move", "120", "130")
kontrol("sanal CLI: window … move → çıkış 0 ve gerçekten taşındı", r.returncode == 0 and au.geometri(KA)[:2] == (120, 130),
        f"{r.returncode} {r.stdout} {r.stderr}")
r = cli_kos("--arka", "pencere", KA, "boyut", "350", "250")
kontrol("sanal CLI: Türkçe pencere … boyut → çıkış 0, 350x250", r.returncode == 0 and au.geometri(KA)[2:] == (350, 250), f"{r.stdout} {r.stderr}")
r = cli_kos("--arka", "window", KA, "maximize")
kontrol("sanal CLI: maximize → maximized", r.returncode == 0 and "maximized" in st(KA), f"{r.stdout} {r.stderr}")
r = cli_kos("--arka", "window", KA, "restore")
kontrol("sanal CLI: restore → normal", r.returncode == 0 and "maximized" not in st(KA), f"{r.stdout} {r.stderr}")
r = cli_kos("--arka", "window", KA, "move", "99999", "0")
kontrol("sanal CLI: ekran dışı → çıkış 2", r.returncode == 2, f"{r.returncode} {r.stderr}")
r = cli_kos("--arka", "window", KB, "minimize")
kontrol("sanal CLI: yasak pencere → çıkış 10", r.returncode == 10, f"{r.returncode} {r.stderr}")
guvenlik.dur_ac("cli")
r = cli_kos("--arka", "window", KA, "move", "10", "10")
guvenlik.dur_kapat("cli")
kontrol("sanal CLI: DUR → çıkış 13", r.returncode == 13, f"{r.returncode} {r.stderr}")
with open(yollar.yasak_dosya(), "w") as f:
    f.write("\n")

# MCP (sanal) + close
async def mcp_sanal():
    async with Client(ms.mcp) as c:
        r = await c.call_tool("manage_window", {"window": KA, "action": "move", "x": 33, "y": 44, "desktop": "background"})
        s = yapi(r)
        kontrol("MCP sanal: move → status moved, geometri gerçek", not r.is_error and s.get("status") == "moved" and
                s["window"]["geometry"][:2] == [33, 44] and au.geometri(KA)[:2] == (33, 44), metin(r))
        r = await c.call_tool("manage_window", {"window": KA, "action": "minimize", "desktop": "background"})
        kontrol("MCP sanal: minimize", not r.is_error and "hidden" in st(KA), metin(r))
        r = await c.call_tool("manage_window", {"window": KA, "action": "restore", "desktop": "background"})
        kontrol("MCP sanal: restore", not r.is_error and "hidden" not in st(KA), metin(r))
        r = await c.call_tool("manage_window", {"window": KA, "action": "move", "x": 9999, "y": 0, "desktop": "background"})
        kontrol("MCP sanal: ekran dışı → [2]", r.is_error and "[2]" in metin(r), metin(r))
        r = await c.call_tool("manage_window", {"window": "pencere-test A", "action": "close", "desktop": "background"})
        kapandi = bekle(lambda: not any(k == KA for k, _, _ in au.pencereler()), 5)
        kontrol("MCP sanal: close (başlık deseniyle) → pencere kapandı", not r.is_error and yapi(r).get("status") == "closed"
                and kapandi, metin(r))
        r = await c.call_tool("manage_window", {"window": "pencere-test A", "action": "move", "x": 1, "y": 1,
                                                "desktop": "background"})
        kontrol("MCP sanal: kapanan pencere → hata (yok)", r.is_error, metin(r))


asyncio.run(mcp_sanal())

for dpy in BAGLANTILAR:
    try:
        dpy.close()
    except Exception:  # noqa: BLE001
        pass
masaustu.masaustu_durdur()
print(f"\n{gecen}/{toplam} pencere yönetimi testi geçti")
sys.exit(0 if gecen == toplam else 1)
