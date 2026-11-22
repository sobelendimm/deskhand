"""Erişilebilirlik (AT-SPI) testleri: otomatik açma, faresiz eylem/değer yazma, güvenlik denetimleri, Chromium bayrağı.

A) EKRANSIZ (sahte arka uç + sahte AT-SPI iş yürütücüsü; gerçek ekrana/panele/dotool'a/AT-SPI veri yoluna HİÇBİR şey gitmez):
   - eylem yolunda (ogeye-tikla --eylem, ogeye-yaz) güvenlik denetimleri fare yoluyla AYNI sonucu verir:
     DUR → 13, yasak pencere → 10, başlık kilidi → 4, sınıf kilidi → 4, hassas düğme adı → 10 / panel onayı /
     --onayli, ödeme sayfası → onay, kde'de oyun/film koruması → 15, onay beklerken araya giren DUR/başlık;
   - eylem hiç gitmez (işlem günlüğü), günlük satırı yazılır, gizli yazı günlüğe düşmez;
   - birincil eylem seçimi, oge_eylem / oge_deger_yaz (sahte erişilebilir nesnelerle), otomatik açma (kde),
     CLI ayrıştırma, komut tablosu, MCP via/element parametreleri, Chromium/Electron bayrağı (komut satırı üretimi).
B) SANAL masaüstünde GERÇEK Qt penceresiyle (Xvfb; kullanıcının ekranına girdi gitmez): masaüstü açılırken erişilebilirlik
   uygulamalardan ÖNCE açık, agac, eylem yolu senaryoları, güvenlik (DUR/yasak/başlık/hassas), yardımcı süreç yolu.
   Xvfb / PyQt6 / at-spi2-core yoksa atlanır.

Çalıştır:  python3 tests/test_erisim.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import argparse
import asyncio
import atexit
import glob
import os
import re
import shutil
import subprocess
import sys
import time

from PIL import Image

from deskhand import api, arka_uc, cli, erisim, eylem, guvenlik, hata, masaustu, onay, uygulama, yollar
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

KOK = _yalitim.KOK
GECEN = TOPLAM = 0
atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def kod_al(f, *a, **k):
    try:
        f(*a, **k)
        return 0
    except Dur as e:
        return e.kod


def gunluk_satirlari():
    sat = []
    for yol in sorted(glob.glob(os.path.join(yollar.gunluk_dizin(), "gunluk-*.log"))):
        with open(yol) as f:
            sat += f.read().splitlines()
    return sat


# ================================================================ A) sahte arka uç + sahte AT-SPI yürütücüsü

class SahteGirdi:
    """Fare yolu (karşılaştırma): guvenlik.denetle + kde koruması + satır kaydı; gerçek girdi yok."""

    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli, self.denetle = au, etiket, gizli, denetle
        self.etk, self.kesildi, self.hazir, self.son_fare = None, None, True, au.fare()[:2]
        self.son_etk = time.monotonic()

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        self.au.ekran_korumasi("girdi")
        for s in satirlar:
            if s.startswith("mouseto "):
                fx, fy = map(float, s.split()[1:3])
                self.au.imlec = (int(fx * 1920), int(fy * 1080))
            self.au.satirlar.append(s)

    def zorla(self, s): self.au.satirlar.append(s)
    def ham(self, s): self.au.satirlar.append(s)
    def izle(self, k, desen): pass
    def izle_bitir(self): pass
    def etk_denetle(self, ne=None): pass
    def insan_kontrol(self): pass
    def kapat(self): pass


class SahteAU(arka_uc.ArkaUc):
    ad = "kde"

    def __init__(self, baslik="Belge — KWrite", sinif="kwrite"):
        self.pen = {"{w}": [baslik, sinif, (100, 100, 800, 600)]}
        self.aktif_ = "{baska}"  # hedef pencere ETKİN DEĞİL: eylem yolu odağa ihtiyaç duymamalı
        self.imlec, self.satirlar, self.koruma = (5, 5), [], None

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return self.pen[k][2] if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return self.pen.get(k, [""])[0]
    def sinif(self, k): return self.pen.get(k, ["", ""])[1]
    def aktif(self): return self.aktif_
    def one_getir(self, k): self.aktif_ = k
    def kapat(self, k): pass
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")
    def pid(self, k): return "4242"

    def fare(self):
        x, y = self.imlec
        X, Y, W, H = self.pen["{w}"][2]
        return x, y, ("{w}" if X <= x < X + W and Y <= y < Y + H else "{masaustu}")

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        return SahteGirdi(self, etiket, gizli, etk, denetle)

    def ekran_korumasi(self, ne):
        if self.koruma:
            raise Dur(*self.koruma)


def oge(rol, ad, yol, etkin=True):
    return {"rol": rol, "ad": ad, "x": 10, "y": 10 + 40 * yol[0], "w": 100, "h": 30, "cx": 60, "cy": 25 + 40 * yol[0],
            "etkin": etkin, "derinlik": 1, "yol": yol}


OGELER = [oge("button", "Kaydet", [0]), oge("button", "Satın al", [1]), oge("button", "Tamam", [2]),
          oge("button", "Pasif", [3], etkin=False), oge("text", "Ad", [4]), oge("password text", "Parola", [5]),
          oge("slider", "Ses", [6]), oge("label", "Salt", [7])]
BILGI = {
    "Kaydet": {"eylemler": ["Press", "Set Focus"], "yazilabilir": False, "aciklama": "", "cocuklar": []},
    "Satın al": {"eylemler": ["Press"], "yazilabilir": False, "aciklama": "", "cocuklar": []},
    "Tamam": {"eylemler": ["Press"], "yazilabilir": False, "aciklama": "", "cocuklar": []},
    "Pasif": {"eylemler": ["Press"], "yazilabilir": False, "aciklama": "", "cocuklar": []},
    "Ad": {"eylemler": ["Set Focus"], "yazilabilir": True, "aciklama": "", "cocuklar": []},
    "Parola": {"eylemler": ["Set Focus"], "yazilabilir": True, "aciklama": "", "cocuklar": []},
    "Ses": {"eylemler": ["Increase", "Decrease"], "yazilabilir": True, "aciklama": "", "cocuklar": []},
    "Salt": {"eylemler": [], "yazilabilir": False, "aciklama": "", "cocuklar": []},
}
for ad_, b_ in BILGI.items():
    b_["ad"] = ad_
    b_["rol"] = next(o["rol"] for o in OGELER if o["ad"] == ad_)

ISLEMLER = []  # (islem, ad, ...) — sahte AT-SPI'nin gördüğü her istek


def sahte_calistir(istek):
    islem, ad = istek["islem"], istek.get("ad")
    if islem == "tara":
        ISLEMLER.append(("tara",))
        return {"ogeler": OGELER, "sure": 0.01}
    ISLEMLER.append((islem, ad, istek.get("eylem") or istek.get("metin")))
    if islem == "incele":
        return dict(BILGI[ad])
    if islem == "eylem":
        e = istek.get("eylem") or BILGI[ad]["eylemler"][0]
        return {"eylem": e, "eylemler": BILGI[ad]["eylemler"], "tamam": True}
    if islem == "yaz":
        return {"yontem": "EditableText", "dogrulandi": True}
    raise AssertionError(islem)


def eylemler():
    """Sahte AT-SPI'de gerçekten UYGULANAN (eylem/yaz) işlemler."""
    return [i for i in ISLEMLER if i[0] in ("eylem", "yaz")]


GERCEK = {a: getattr(erisim, a) for a in ("erisim_ac_garanti", "erisim_acik", "_erisim_yaz", "_a11y_adresi")}
erisim._atspi_calistir = sahte_calistir
erisim.erisim_ac_garanti = lambda: False
erisim._a11y_adresi = lambda: ""
erisim.nokta_metni = lambda k, x, y: []  # fare yolunda OCR yok: ögenin adı (ek_metinler) hassas denetimi için yeter

ISTEKLER = []
YANIT = {"izin": False, "kanca": None}


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti, "goruntu": goruntu})
    if YANIT["kanca"]:
        YANIT["kanca"]()
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


gercek_iste_sonuc = onay.iste_sonuc
onay.iste_sonuc = sahte_iste_sonuc


def ns(**k):
    a = argparse.Namespace(baslik=None, sinif=None, onayli=False, gizli=False, kimlik="{w}", rol=None, sira=None,
                           dugme="sol", eylem="", ad="Kaydet")
    for x, v in k.items():
        setattr(a, x, v)
    return a


def eylem_yolu(**k):
    return erisim.k_ogeye_tikla(ns(**k))


def fare_yolu(**k):
    return erisim.k_ogeye_tikla(ns(eylem=None, **k))


def yaz_yolu(**k):
    k.setdefault("ad", "Ad")
    k.setdefault("metin", "Ali")
    return erisim.k_ogeye_yaz(ns(**k))


def sifirla(baslik="Belge — KWrite", sinif="kwrite"):
    ISLEMLER.clear()
    ISTEKLER.clear()
    YANIT.update(izin=False, kanca=None)
    au_ = SahteAU(baslik, sinif)
    arka_uc._ORNEKLER["kde"] = au_
    guvenlik.dur_kapat("kullanici")
    guvenlik.SINIF_DESEN = None
    if os.path.exists(yollar.yasak_dosya()):
        os.remove(yollar.yasak_dosya())
    return au_


with arka_uc.hedef_sabit("kde"):
    # ------------------------------------------------------------ 1. temel akış: faresiz, odaksız, günlüklü
    au = sifirla()
    g0 = len(gunluk_satirlari())
    kontrol("eylem: düğme birincil eylemle (Press), pencere etkin DEĞİL, gerçek girdi yok", eylem_yolu(ad="Kaydet") is None
            and eylemler() == [("eylem", "Kaydet", "Press")] and au.aktif_ == "{baska}" and au.satirlar == [],
            f"{eylemler()} {au.aktif_} {au.satirlar}")
    yeni = gunluk_satirlari()[g0:]
    kontrol("eylem: günlük satırı (girdi biçimi, eylem adı)", any(
        "ogeye-tikla 'Kaydet' --eylem Press | [Belge — KWrite] | atspi action Press" in l for l in yeni), str(yeni))
    kontrol("eylem: ağaç + inceleme + eylem sırası", [i[0] for i in ISLEMLER] == ["tara", "incele", "eylem"], str(ISLEMLER))
    ISLEMLER.clear()
    eylem_yolu(ad="Kaydet", eylem="set focus")
    kontrol("eylem: --eylem adı boşluk/büyük harf duyarsız ('set focus' = 'Set Focus')",
            eylemler() == [("eylem", "Kaydet", "Set Focus")], str(eylemler()))
    kontrol("eylem: olmayan eylem adı → 6, işlem yok", kod_al(eylem_yolu, ad="Kaydet", eylem="Yok") == 6 and
            len(eylemler()) == 1)
    kontrol("eylem: eylemsiz öge (Action yok) → 6", kod_al(eylem_yolu, ad="Salt") == 6 and len(eylemler()) == 1)
    kontrol("eylem: birincil eylemi olmayan öge (yalnız Set Focus) → 6 ve eylem listesi mesajda",
            kod_al(eylem_yolu, ad="Ad") == 6 and len(eylemler()) == 1)
    kontrol("eylem: devre dışı öge → 6", kod_al(eylem_yolu, ad="Pasif") == 6 and len(eylemler()) == 1)
    kontrol("eylem: olmayan öge → 6", kod_al(eylem_yolu, ad="Yokyok") == 6 and len(eylemler()) == 1)
    kontrol("eylem: --eylem ile sağ/çift tık birlikte → 1", kod_al(eylem_yolu, ad="Kaydet", dugme="sag") == 1)
    n_ = len(eylemler())
    yaz_yolu(ad="Ad", metin="Çağrı ğüş")
    kontrol("yaz: değer yazıldı (faresiz, odaksız)", eylemler()[n_:] == [("yaz", "Ad", "Çağrı ğüş")] and au.satirlar == [],
            str(eylemler()))
    kontrol("yaz: yazılamayan öge (düğme) → 6", kod_al(yaz_yolu, ad="Kaydet") == 6 and len(eylemler()) == n_ + 1)
    g0 = len(gunluk_satirlari())
    yaz_yolu(ad="Ad", metin="açık metin")
    yaz_yolu(ad="Parola", metin="cok-gizli-123", onayli=True)  # parola alanı onay ister (CLI: --onayli)
    yaz_yolu(ad="Ad", metin="öteki-gizli-456", gizli=True)
    yeni = "\n".join(gunluk_satirlari()[g0:])
    kontrol("yaz günlüğü: düz metin görünür; password text ve --gizli günlüğe DÜŞMEZ",
            "açık metin" in yeni and "cok-gizli-123" not in yeni and "öteki-gizli-456" not in yeni and
            "***(13)" in yeni and "***(15)" in yeni, yeni)

    # ------------------------------------------------------------ 2. güvenlik: eylem yolu ≡ fare yolu
    def esit(ad_, hazirla, beklenen, yollar_=("eylem", "fare", "yaz"), **k):
        """Aynı koşulda eylem yolu, fare yolu ve yazma yolu AYNI çıkış kodunu verir; işlem/girdi yok."""
        sonuc = {}
        for etiket, f in (("eylem", eylem_yolu), ("fare", fare_yolu), ("yaz", yaz_yolu)):
            if etiket not in yollar_:
                continue
            au_ = hazirla()
            au_.aktif_ = "{w}"  # fare yolu etkin pencere ister; eylem yolu için fark etmez
            kod = kod_al(f, **{**k, "ad": "Ad", "metin": "Ali"}) if etiket == "yaz" else \
                kod_al(f, **{**k, "ad": k.get("ad", "Kaydet")})
            sonuc[etiket] = (kod, len(eylemler()) + len(au_.satirlar))
        ok = all(v == (beklenen, 0) for v in sonuc.values())
        kontrol(f"güvenlik [{ad_}]: {' / '.join(sonuc)} yolu hepsi {beklenen}, hiçbir işlem yapılmadı", ok, str(sonuc))

    def dur_hazirla():
        au_ = sifirla()
        guvenlik.dur_ac("cli")
        return au_

    esit("DUR", dur_hazirla, 13)
    guvenlik.dur_kapat("cli")

    def yasak_hazirla():
        au_ = sifirla()
        os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True)
        with open(yollar.yasak_dosya(), "w") as f:
            f.write("KWrite\n")
        return au_

    esit("yasak pencere", yasak_hazirla, 10)
    ISLEMLER.clear()
    kontrol("güvenlik [yasak pencere]: yasaklı pencerenin ağacına bile bakılmadı", ISLEMLER == [], str(ISLEMLER))
    os.remove(yollar.yasak_dosya())

    esit("başlık kilidi", lambda: sifirla(), 4, baslik="^Başka belge$")

    def sinif_hazirla():
        au_ = sifirla()
        guvenlik.SINIF_DESEN = "^firefox$"
        return au_

    esit("sınıf kilidi", sinif_hazirla, 4)
    guvenlik.SINIF_DESEN = None

    esit("hassas düğme 'Satın al' (onay yok → red)", lambda: sifirla(), 10, yollar_=("eylem", "fare"), ad="Satın al")
    sifirla()
    eylem_yolu_kod = kod_al(eylem_yolu, ad="Satın al")
    kontrol("güvenlik [hassas düğme]: eylem yolunda onay istendi, görüntüsüz (pencereyi öne getirmez)",
            eylem_yolu_kod == 10 and len(ISTEKLER) == 1 and ISTEKLER[0]["goruntu"] is None, str(ISTEKLER[:1])[:200])
    esit("ödeme sayfası başlığı", lambda: sifirla("Checkout - Ödeme - Shop", "firefox"), 10, yollar_=("eylem", "fare"),
         ad="Kaydet")
    sifirla("Checkout - Ödeme - Shop", "firefox")
    kod = kod_al(eylem_yolu, ad="Kaydet")
    kontrol("güvenlik [ödeme sayfası]: eylem yolunda da panele onay istendi (görüntüsüz)",
            kod == 10 and len(ISTEKLER) == 1 and "Hassas sayfada" in ISTEKLER[0]["eylem"] and
            ISTEKLER[0]["goruntu"] is None, str([i["eylem"] for i in ISTEKLER]))

    # hassas düğme: onay isteği ögenin adını taşır; izin → yapılır; --onayli → sorulmaz
    au = sifirla()
    YANIT["izin"] = True
    kontrol("hassas düğme: panel izin verdi → eylem yapıldı (tek onay)", eylem_yolu(ad="Satın al") is None and
            len(ISTEKLER) == 1 and eylemler() == [("eylem", "Satın al", "Press")], f"{ISTEKLER} {eylemler()}")
    kontrol("hassas düğme: onay isteği düğme adını gösterir", "Satın al" in ISTEKLER[0]["eylem"], str(ISTEKLER[0]))
    kontrol("hassas düğme: günlükte --onayli etiketi", any("--eylem Press --onayli |" in l for l in gunluk_satirlari()[-2:]))
    au = sifirla()
    eylem_yolu(ad="Satın al", onayli=True)
    kontrol("hassas düğme: --onayli → sorulmaz, yapılır", not ISTEKLER and eylemler() == [("eylem", "Satın al", "Press")])

    # hassas metin yalnız açıklamada / çocuk adında olsa da yakalanır (adı 'Tamam' olan düğme)
    for alan, deger in (("aciklama", "Siparişi tamamla"), ("cocuklar", ["Hemen al"])):
        au = sifirla()
        eski = dict(BILGI["Tamam"])
        BILGI["Tamam"][alan] = deger
        try:
            kod = kod_al(eylem_yolu, ad="Tamam")
        finally:
            BILGI["Tamam"].update(eski)
        kontrol(f"hassas düğme: adı 'Tamam', {alan}={deger!r} → onay ister, red → 10, işlem yok",
                kod == 10 and len(ISTEKLER) == 1 and not eylemler(), f"{kod} {ISTEKLER}")

    # yazı: ödeme sayfasında Enter/Tab/boşluklu metin onay ister (yaz ile aynı kural); boşluksuz serbest
    au = sifirla("Checkout - Ödeme - Shop", "firefox")
    for metin in ("4111\n", "a\tb", "ad soyad", " "):
        ISTEKLER.clear()
        kontrol(f"yaz: ödeme sayfası, {metin!r} → onay, red → 10, yazılmadı",
                kod_al(yaz_yolu, ad="Ad", metin=metin) == 10 and len(ISTEKLER) == 1 and not eylemler(), str(ISTEKLER))
    ISTEKLER.clear()
    kontrol("yaz: ödeme sayfası, boşluksuz (kart no) serbest", kod_al(yaz_yolu, ad="Ad", metin="4111111111111111") == 0
            and not ISTEKLER and len(eylemler()) == 1)
    YANIT["izin"] = True
    ISTEKLER.clear()
    kontrol("yaz: izin → TEK onayla yazıldı, istek metni ve görüntüsüzlüğü doğru",
            kod_al(yaz_yolu, ad="Ad", metin="Ali Veli\n34 Cadde\n") == 0 and len(ISTEKLER) == 1 and
            "Ali Veli" in ISTEKLER[0]["ayrinti"] and ISTEKLER[0]["goruntu"] is None, str(ISTEKLER)[:300])
    YANIT["izin"] = False
    ISTEKLER.clear()
    ISLEMLER.clear()
    kontrol("yaz: --onayli → sorulmaz", kod_al(yaz_yolu, ad="Ad", metin="a b\n", onayli=True) == 0 and not ISTEKLER)
    ISTEKLER.clear()
    kontrol("yaz: --gizli onay isteğinde içeriği göstermez",
            kod_al(yaz_yolu, ad="Ad", metin="sir sir\n", gizli=True) == 10 and "sir sir" not in ISTEKLER[0]["ayrinti"]
            and "***(8)" in ISTEKLER[0]["ayrinti"], str(ISTEKLER)[:300])

    # onay beklerken araya giren DUR / başlık değişikliği: eylem YAPILMAZ (son denetim onaydan SONRA)
    au = sifirla()
    YANIT["izin"] = True
    YANIT["kanca"] = lambda: guvenlik.dur_ac("cli")
    kontrol("onay sırasında DUR geldi → 13, eylem yapılmadı", kod_al(eylem_yolu, ad="Satın al") == 13 and not eylemler(),
            str(eylemler()))
    guvenlik.dur_kapat("cli")
    au = sifirla()
    YANIT["izin"] = True
    YANIT["kanca"] = lambda: au.pen["{w}"].__setitem__(0, "Başka belge")
    kontrol("onay sırasında başlık değişti (başlık kilidi) → 4, eylem yapılmadı",
            kod_al(eylem_yolu, ad="Satın al", baslik="^Belge — KWrite$") == 4 and not eylemler(), str(eylemler()))
    au = sifirla()
    YANIT["izin"] = True
    YANIT["kanca"] = lambda: setattr(au, "koruma", (15, "kullanıcı tam ekranda"))
    kontrol("onay sırasında kullanıcı film açtı (kde koruması) → 15, eylem yapılmadı",
            kod_al(eylem_yolu, ad="Satın al") == 15 and not eylemler(), str(eylemler()))
    # yazma yolunda da aynı
    au = sifirla("Checkout - Ödeme - Shop", "firefox")
    YANIT["izin"] = True
    YANIT["kanca"] = lambda: guvenlik.dur_ac("cli")
    kontrol("yaz: onay sırasında DUR geldi → 13, yazılmadı", kod_al(yaz_yolu, ad="Ad", metin="a b") == 13 and not eylemler())
    guvenlik.dur_kapat("cli")

    # kde: oyun/film koruması (15) — ağaca bakmadan, her iki yolda
    au = sifirla()
    au.koruma = (15, "tam ekranda (test)")
    kontrol("kde: oyun/film izlerken eylem → 15, ağaca bile bakılmadı", kod_al(eylem_yolu, ad="Kaydet") == 15 and
            ISLEMLER == [], str(ISLEMLER))
    kontrol("kde: oyun/film izlerken yazma → 15", kod_al(yaz_yolu, ad="Ad") == 15 and ISLEMLER == [])
    kontrol("kde: fare yolu da 15 (karşılaştırma)", (setattr(au, "aktif_", "{w}") or kod_al(fare_yolu, ad="Kaydet")) == 15)
    au.koruma = (12, "karar bildirimi açık")
    kontrol("kde: karar bildirimi açıkken eylem → 12", kod_al(eylem_yolu, ad="Kaydet") == 12 and not eylemler())
    au = sifirla()
    kontrol("koruma yokken eylem serbest", kod_al(eylem_yolu, ad="Kaydet") == 0 and len(eylemler()) == 1)

    # ------------------------------------------------------------ 2b. insan önceliği (12): kullanıcı klavye/fare kullanıyor
    au = sifirla()
    sayac_insan = {"n": 0}
    au.insan_var_mi = lambda: (sayac_insan.__setitem__("n", sayac_insan["n"] + 1) or True)
    erisim.INSAN_BEKLE_AZAMI = 0.5
    kontrol("insan önceliği: kullanıcı sürekli kullanıyorsa eylem → 12 (bekleyip vazgeçer), işlem yok",
            kod_al(eylem_yolu, ad="Kaydet") == 12 and not eylemler() and sayac_insan["n"] >= 2, str(sayac_insan))
    kontrol("insan önceliği: değer yazma → 12, yazılmadı", kod_al(yaz_yolu, ad="Ad") == 12 and not eylemler())
    kalan = {"n": 2}
    au.insan_var_mi = lambda: (kalan.__setitem__("n", kalan["n"] - 1) or kalan["n"] >= 0)
    kontrol("insan önceliği: kullanıcı işini bitirince (durgunluk) beklenip eylem yapılır",
            kod_al(eylem_yolu, ad="Kaydet") == 0 and len(eylemler()) == 1, str(eylemler()))
    au = sifirla()
    au.ad = "sanal"
    au.insan_var_mi = lambda: True  # sanalda 'Devral' açık
    kontrol("insan önceliği (sanal): Devral açıkken eylem → 12", kod_al(eylem_yolu, ad="Kaydet") == 12 and not eylemler())
    erisim.INSAN_BEKLE_AZAMI = 8.0

    # ------------------------------------------------------------ 2c. uygulama erişim seviyeleri (fare yoluyla aynı çıkış kodu)
    def seviye_yaz(*satirlar):
        os.makedirs(os.path.dirname(yollar.seviye_dosya()), exist_ok=True)
        with open(yollar.seviye_dosya(), "w") as f_:
            f_.write("\n".join(satirlar) + "\n")

    def seviye_sil():
        try:
            os.remove(yollar.seviye_dosya())
        except OSError:
            pass
    try:
        for sev, (eylem_kod, yaz_kod) in {"goruntule": (10, 10), "tikla": (0, 10), "tam": (0, 0)}.items():
            seviye_yaz(f"kwrite = {sev}")
            au = sifirla()
            ke = kod_al(eylem_yolu, ad="Kaydet")
            kf = kod_al(fare_yolu, ad="Kaydet")  # karşılaştırma: gerçek fare yolu (sahte girdi) — fare sınıfı
            ky = kod_al(yaz_yolu, ad="Ad")
            kontrol(f"seviye {sev}: tıklama eylemi → {eylem_kod}, fare yoluyla aynı kod ({kf})",
                    ke == eylem_kod and kf == eylem_kod, f"{ke} {kf}")
            kontrol(f"seviye {sev}: değer yazma (klavye sayılır) → {yaz_kod}", ky == yaz_kod, str(ky))
            if eylem_kod:
                kontrol(f"seviye {sev}: reddedilince AT-SPI'ye hiçbir eylem/yazma gitmedi", not eylemler(), str(ISLEMLER))
    finally:
        seviye_sil()

    # ------------------------------------------------------------ 2d. uçbirimde yıkıcı komut değer yazma yoluyla da onay ister
    au = sifirla("Terminal", "org.kde.konsole")
    kontrol("uçbirim: ogeye-yaz ile 'sudo rm -rf /' onaysız → 10, yazılmadı, görüntü eklenmedi",
            kod_al(yaz_yolu, ad="Ad", metin="sudo rm -rf /") == 10 and not eylemler() and len(ISTEKLER) == 1 and
            "Uçbirime komut yaz" in ISTEKLER[0]["eylem"] and ISTEKLER[0]["goruntu"] is None, str(ISTEKLER)[:300])
    YANIT["izin"] = True
    ISTEKLER.clear()
    kontrol("uçbirim: panel izin verince yazılır (tek onay)", kod_al(yaz_yolu, ad="Ad", metin="sudo rm -rf /") == 0 and
            len(eylemler()) == 1 and len(ISTEKLER) == 1, str(ISTEKLER)[:200])
    au = sifirla("Belge", "kwrite")
    kontrol("uçbirim olmayan pencerede aynı metin sorulmadan yazılır", kod_al(yaz_yolu, ad="Ad", metin="sudo rm -rf /") == 0 and
            not ISTEKLER)

    # masaüstü kipi: pencere ister
    kontrol("masaüstü kipi (EKRAN) → 1", kod_al(eylem_yolu, kimlik=EKRAN) == 1 and kod_al(yaz_yolu, kimlik=EKRAN) == 1)

    # ------------------------------------------------------------ 3. otomatik açma (kde)
    sifirla()
    durum = {"acik": False, "yazilan": []}
    erisim.erisim_acik = lambda: durum["acik"]
    erisim._erisim_yaz = lambda v: (durum["yazilan"].append(v), durum.update(acik=v))
    erisim.erisim_ac_garanti = GERCEK["erisim_ac_garanti"]
    gercek_uyku = time.sleep
    time.sleep = lambda s: None
    try:
        g0 = len(gunluk_satirlari())
        kontrol("otomatik açma: kapalıyken IsEnabled=true yazıldı, True döndü, günlük",
                erisim.erisim_ac_garanti() is True and durum["yazilan"] == [True] and
                any("erisim | otomatik ac" in l for l in gunluk_satirlari()[g0:]), str(durum))
        kontrol("otomatik açma: açıkken dokunmaz", erisim.erisim_ac_garanti() is False and durum["yazilan"] == [True])
        # Deskhand'in açtığı işareti (kalıcı masaüstü ayarı değişebilir): durum dizini + günlüğe BİR kez
        kontrol("otomatik açma (kde): durum dizinine 'Deskhand açtı' işareti yazıldı", os.path.exists(yollar.erisim_isareti()))
        kontrol("... işaret gerçek ~/.local/state'e değil yalıtılmış dizine yazıldı", yollar.erisim_isareti().startswith(
            _yalitim.GECICI))
        durum.update(acik=False)
        erisim.erisim_ac_garanti()
        kontrol("... günlüğe yalnız BİR kez yazıldı (ikinci açışta tekrarlanmadı)",
                sum("Deskhand erişilebilirliği açtı" in l for l in gunluk_satirlari()) == 1)
        from deskhand import doktor
        gercek_ciktisi = doktor._komut_ciktisi
        doktor._komut_ciktisi = lambda *a, **k: "b true"
        try:
            sat = doktor.satir_erisim()
            kontrol("doctor: işaret varsa 'açık (Deskhand açtı)'", sat["durum"] == "tamam" and "Deskhand açtı" in sat["ayrinti"],
                    str(sat))
            erisim.k_erisim(ns(islem="kapat", ad=None))
            kontrol("a11y off: işareti de temizler, ayar kapatıldı (sahte yazıcı)", not os.path.exists(yollar.erisim_isareti())
                    and durum["yazilan"][-1] is False, str(durum))
            durum.update(acik=True)
            sat = doktor.satir_erisim()
            kontrol("doctor: işaret yoksa yalnız 'açık'", sat["durum"] == "tamam" and "Deskhand açtı" not in sat["ayrinti"],
                    str(sat))
            doktor._komut_ciktisi = lambda *a, **k: "b false" if "IsEnabled" in a else "b true"
            sat = doktor.satir_erisim()
            kontrol("doctor: kapalıyken 'kapalı' uyarısı", sat["durum"] == "uyari" and "kapalı" in sat["ayrinti"], str(sat))
        finally:
            doktor._komut_ciktisi = gercek_ciktisi
        durum.update(acik=False)
        erisim.erisim_ac_garanti()  # sonraki testler için durum
        # erisim_ogeleri: az önce açıldıysa 'ağaçta yok' kısa süre yeniden denenir
        sayac = {"n": 0}

        def gec_giren(istek):
            sayac["n"] += 1
            if sayac["n"] < 3:
                raise Dur(6, "ağaçta yok", tur="agacta_yok")
            return {"ogeler": OGELER, "sure": 0.01}
        erisim._atspi_calistir = gec_giren
        erisim.erisim_ac_garanti = lambda: True  # az önce açıldı
        o, _sure = erisim.erisim_ogeleri("{w}")
        kontrol("agac: az önce açıldıysa uygulama ağaca girene dek yeniden dener", len(o) == len(OGELER) and sayac["n"] == 3,
                str(sayac))
        sayac["n"] = 0
        erisim.erisim_ac_garanti = lambda: False  # zaten açıktı: bekleme yok
        kontrol("agac: erişilebilirlik zaten açıksa 'ağaçta yok' beklemeden 6", kod_al(erisim.erisim_ogeleri, "{w}") == 6
                and sayac["n"] == 1, str(sayac))
        erisim._atspi_calistir = lambda i: (_ for _ in ()).throw(Dur(8, "başka hata"))
        erisim.erisim_ac_garanti = lambda: True
        kontrol("agac: başka hata yeniden denenmez", kod_al(erisim.erisim_ogeleri, "{w}") == 8)
    finally:
        time.sleep = gercek_uyku
        erisim._atspi_calistir = sahte_calistir
        erisim.erisim_acik, erisim._erisim_yaz = GERCEK["erisim_acik"], GERCEK["_erisim_yaz"]
        erisim.erisim_ac_garanti = lambda: False
        erisim._a11y_adresi = lambda: ""

    # api.agac_oku (MCP read_text tree) ve ogeye_tikla/ogeye_yaz katmanı aynı yürütücüyü kullanır
    sifirla()
    r = api.agac_oku("{w}", "Kaydet")
    kontrol("api.agac_oku: ağaç sonucu (kendiliğinden açma yolundan)", r["items"] and r["items"][0]["text"] == "Kaydet",
            str(r)[:200])
    api.ogeye_tikla("{w}", "Kaydet", eylem="")
    api.ogeye_yaz("{w}", "Ad", "x")
    kontrol("api.ogeye_tikla(eylem='') / ogeye_yaz AT-SPI yolundan gider", eylemler() == [("eylem", "Kaydet", "Press"),
                                                                                         ("yaz", "Ad", "x")], str(eylemler()))

# ---------------------------------------------------------------- 4. işlev düzeyi: sahte erişilebilir nesneler
kontrol("birincil_eylem: click > press > activate > toggle, 'Set Focus'/'Show Menu' birincil değil",
        erisim.birincil_eylem(["Set Focus", "Press"]) == 1 and erisim.birincil_eylem(["toggle", "Click"]) == 1 and
        erisim.birincil_eylem(["Activate"]) == 0 and erisim.birincil_eylem(["Set Focus"]) is None and
        erisim.birincil_eylem(["Show Menu"]) is None and erisim.birincil_eylem([]) is None)
kontrol("eylem_sirasi: boşluk/_/-/büyük harf yok sayılır",
        erisim.eylem_sirasi(["Set Focus", "Show Menu"], "show_menu") == 1 and
        erisim.eylem_sirasi(["Set Focus"], "set-focus") == 0 and erisim.eylem_sirasi(["Press"], "yok") is None)


class SahteAction:
    def __init__(self, adlar, sonuc=True):
        self.adlar, self.sonuc, self.yapilan = adlar, sonuc, []

    def get_n_actions(self): return len(self.adlar)
    def get_action_name(self, i): return self.adlar[i]
    def do_action(self, i): return self.yapilan.append(i) or self.sonuc


class SahteDuzenlenebilir:
    def __init__(self, sonuc=True): self.sonuc, self.metin = sonuc, None
    def set_text_contents(self, m): return (setattr(self, "metin", m) or self.sonuc)


class SahteDeger:
    def __init__(self, en_az=0.0, en_cok=10.0, sonuc=True): self.en_az, self.en_cok, self.sonuc, self.v = en_az, en_cok, sonuc, 0.0
    def get_minimum_value(self): return self.en_az
    def get_maximum_value(self): return self.en_cok
    def set_current_value(self, v): return (setattr(self, "v", v) or self.sonuc)
    def get_current_value(self): return self.v


class SahteMetin: pass


class SahteOge:
    def __init__(self, action=None, edit=None, deger=None, metin=None):
        self.a, self.e, self.d, self.m = action, edit, deger, metin
    def get_action_iface(self): return self.a
    def get_editable_text_iface(self): return self.e
    def get_value_iface(self): return self.d
    def get_text_iface(self): return self.m


class SahteAtspi:
    class Text:
        @staticmethod
        def get_text(ti, bas, son): return ti.icerik


erisim._modul = lambda: SahteAtspi
a = SahteAction(["Set Focus", "Press"])
r = erisim.oge_eylem(SahteOge(action=a))
kontrol("oge_eylem: ad verilmezse birincil (Press), eylem listesi dönüşte", a.yapilan == [1] and r["eylem"] == "Press" and
        r["eylemler"] == ["Set Focus", "Press"] and r["tamam"] is True, str(r))
a = SahteAction(["Set Focus", "Press"])
r = erisim.oge_eylem(SahteOge(action=a), "set focus")
kontrol("oge_eylem: ad verilirse o eylem", a.yapilan == [0] and r["eylem"] == "Set Focus", str(r))
kontrol("oge_eylem: Action yok → 6", kod_al(erisim.oge_eylem, SahteOge()) == 6)
kontrol("oge_eylem: olmayan eylem adı → 6", kod_al(erisim.oge_eylem, SahteOge(action=SahteAction(["Press"])), "x") == 6)
kontrol("oge_eylem: birincil yok (yalnız Set Focus) → 6", kod_al(erisim.oge_eylem, SahteOge(action=SahteAction(["Set Focus"]))) == 6)
a = SahteAction(["Press"], sonuc=False)
kontrol("oge_eylem: öge eylemi reddederse tamam=False döner", erisim.oge_eylem(SahteOge(action=a))["tamam"] is False)
et = SahteDuzenlenebilir()
ti = SahteMetin()
ti.icerik = "Merhaba"
r = erisim.oge_deger_yaz(SahteOge(edit=et, metin=ti), "Merhaba")
kontrol("oge_deger_yaz: EditableText + okuyarak doğrulama", et.metin == "Merhaba" and r == {"yontem": "EditableText",
                                                                                           "dogrulandi": True}, str(r))
ti.icerik = "••••"
kontrol("oge_deger_yaz: okunan farklıysa (parola) dogrulandi=False, hata değil",
        erisim.oge_deger_yaz(SahteOge(edit=SahteDuzenlenebilir(), metin=ti), "sir")["dogrulandi"] is False)
kontrol("oge_deger_yaz: EditableText reddederse → 6",
        kod_al(erisim.oge_deger_yaz, SahteOge(edit=SahteDuzenlenebilir(sonuc=False)), "x") == 6)
dg = SahteDeger()
r = erisim.oge_deger_yaz(SahteOge(deger=dg), "4,5")
kontrol("oge_deger_yaz: Value (virgüllü sayı), yazılanı okuyarak doğrular", dg.v == 4.5 and r["yontem"] == "Value" and
        r["dogrulandi"] is True, str(r))
kontrol("oge_deger_yaz: Value sayı değil → 1, aralık dışı → 1, reddedilirse → 6",
        kod_al(erisim.oge_deger_yaz, SahteOge(deger=SahteDeger()), "abc") == 1 and
        kod_al(erisim.oge_deger_yaz, SahteOge(deger=SahteDeger()), "11") == 1 and
        kod_al(erisim.oge_deger_yaz, SahteOge(deger=SahteDeger(sonuc=False)), "3") == 6)
kontrol("oge_deger_yaz: yazılabilir arayüz yok → 6", kod_al(erisim.oge_deger_yaz, SahteOge(), "x") == 6)

# ---------------------------------------------------------------- 5. CLI, komut tablosu, MCP şeması
p = cli.ayristirici("deskhand")
x = p.parse_args(["click-element", "K", "Kaydet", "--action"])
y = p.parse_args(["ogeye-tikla", "K", "Kaydet", "--eylem", "Show Menu"])
z = p.parse_args(["click-element", "K", "Kaydet"])
kontrol("CLI: --action (değersiz) = birincil '', --eylem ADI = o ad, yoksa None (fare yolu)",
        (x.eylem, y.eylem, z.eylem) == ("", "Show Menu", None), str((x.eylem, y.eylem, z.eylem)))
x = p.parse_args(["set-element", "K", "Ad", "Merhaba\\nDünya", "--secret", "--approved", "--role", "text", "--nth", "2"])
y = p.parse_args(["ogeye-yaz", "K", "Ad", "m"])
kontrol("CLI: set-element ≡ ogeye-yaz, kaçışlar çözülür, --secret/--approved/--role/--nth",
        x.komut == "ogeye-yaz" == y.komut and x.f is y.f is erisim.k_ogeye_yaz and x.metin == "Merhaba\nDünya" and
        x.gizli and x.onayli and x.rol == "text" and x.sira == 2, str(x))
from deskhand import komutlar  # noqa: E402

kaynak = open(komutlar.__file__, encoding="utf-8").read().splitlines()
i = next(n for n, l in enumerate(kaynak) if '("erisim", "a11y")' in l)
kontrol("komutlar.KOMUTLAR: ogeye-yaz kendi satırında, a11y satırından hemen sonra",
        kaynak[i + 1].strip() == '("ogeye-yaz", "set-element"),' and '("ogeye-yaz"' not in kaynak[i],
        kaynak[i + 1])
kontrol("komutlar.SECENEKLER: --eylem → --action", komutlar.SECENEKLER.get("--eylem") == "--action")
kontrol("ogeye-yaz girdi komutu (DUR/yasak ön denetimi, günlük)", "ogeye-yaz" in eylem.GIRDI_KOMUTLARI)

from deskhand import mcp_sunucu as s  # noqa: E402
import inspect  # noqa: E402

for ad_ in ("click", "type_text"):
    fn = getattr(s, ad_)
    fn = getattr(fn, "fn", fn)
    if ad_ == "click":
        adlar = list(inspect.signature(fn).parameters)
        kontrol("MCP click: via, element'in hemen ardında; varsayılan 'mouse'",
                adlar[adlar.index("element") + 1] == "via" and inspect.signature(fn).parameters["via"].default == "mouse",
                str(adlar))
    else:
        kontrol("MCP type_text: element parametresi (str | None, varsayılan None)",
                "element" in inspect.signature(fn).parameters and inspect.signature(fn).parameters["element"].default is None)


async def mcp_testleri():
    from mcp import Client
    with arka_uc.hedef_sabit("kde"):
        au_ = sifirla()
        au_.pen["{w}"][0] = "Sahte Pencere"
        au_.aktif_ = "{w}"
        os.environ.pop("DESKHAND_MCP_SADECE_ARKA", None)
        import deskhand.mesgul as mesgul
        mesgul.karar = lambda ozet: "on"
        mesgul.durum = lambda esik=None: {"mesgul": False, "nedenler": [], "ayrinti": {}}
        async with Client(s.mcp) as c:
            r = await c.call_tool("click", {"window": "{w}", "element": "Kaydet", "via": "action", "desktop": "foreground"})
            m = "\n".join(getattr(t, "text", "") for t in r.content)
            kontrol("MCP click(element, via='action'): eylem yapıldı, via=action, girdi yok",
                    not r.is_error and eylemler() == [("eylem", "Kaydet", "Press")] and au_.satirlar == [] and
                    (r.structured_content or {}).get("via") == "action", m[:300])
            r = await c.call_tool("click", {"window": "{w}", "text": "Kaydet", "via": "action", "desktop": "foreground"})
            kontrol("MCP click: via='action' yalnız element ile ([1])", r.is_error and "[1]" in "".join(
                getattr(t, "text", "") for t in r.content))
            r = await c.call_tool("click", {"window": "{w}", "element": "Kaydet", "via": "action", "button": "right",
                                            "desktop": "foreground"})
            kontrol("MCP click: via='action' + button='right' reddedilir ([1])", r.is_error)
            n_ = len(eylemler())
            r = await c.call_tool("type_text", {"window": "{w}", "text": "Ali", "element": "Ad", "desktop": "foreground"})
            kontrol("MCP type_text(element): AT-SPI ile yazıldı, klavye girdisi yok",
                    not r.is_error and eylemler()[n_:] == [("yaz", "Ad", "Ali")] and au_.satirlar == [],
                    "\n".join(getattr(t, "text", "") for t in r.content)[:300])
            r = await c.call_tool("type_text", {"window": "{w}", "text": "Ali", "element": "Ad", "submit": True,
                                                "desktop": "foreground"})
            kontrol("MCP type_text: element + submit reddedilir ([1])", r.is_error)
            guvenlik.dur_ac("cli")
            n_ = len(eylemler())
            r = await c.call_tool("click", {"window": "{w}", "element": "Kaydet", "via": "action", "desktop": "foreground"})
            kontrol("MCP click(via='action'): DUR → [13], eylem yok", r.is_error and "[13]" in "".join(
                getattr(t, "text", "") for t in r.content) and len(eylemler()) == n_)
            guvenlik.dur_kapat("cli")
            au_.koruma = (15, "tam ekranda (test)")
            r = await c.call_tool("type_text", {"window": "{w}", "text": "Ali", "element": "Ad", "desktop": "foreground"})
            kontrol("MCP type_text(element): kde oyun/film koruması → [15]", r.is_error and "[15]" in "".join(
                getattr(t, "text", "") for t in r.content) and len(eylemler()) == n_)
            au_.koruma = None


asyncio.run(mcp_testleri())

# ---------------------------------------------------------------- 6. Chromium/Electron bayrağı (komut satırı üretimi)
B = uygulama.ERISIM_BAYRAGI
kontrol("bayrak adı", B == "--force-renderer-accessibility")
for komut, beklenen in (
        (["/usr/bin/chromium"], True), (["vivaldi-stable", "--incognito"], True), (["google-chrome-stable"], True),
        (["/usr/bin/discord"], True), (["code", "."], True), (["/opt/Foo/node_modules/electron/dist/electron", "app"], True),
        (["/usr/lib/electron43/electron"], True), (["env", "A=1", "nice", "-n", "5", "/usr/bin/obsidian"], True),
        (["flatpak", "run", "--branch=stable", "--arch=x86_64", "com.discordapp.Discord"], True),
        (["flatpak", "run", "--command=sh", "md.obsidian.Obsidian", "-c", "x"], True),
        (["/usr/bin/firefox"], False), (["/usr/bin/kwrite"], False), (["python3", "chromium.py"], False),
        (["flatpak", "run", "org.kde.okular"], False), (["/usr/bin/foo", "--user-agent=chromium"], False), ([], False)):
    kontrol(f"chromium_ailesi_mi({' '.join(komut)!r}) = {beklenen}", uygulama.chromium_ailesi_mi(komut) is beklenen)
kontrol("bayrak komutun sonuna eklenir; zaten varsa yinelenmez; ilgisiz komut aynen",
        uygulama.erisim_bayragi_ekle(["/usr/bin/chromium", "--foo"]) == ["/usr/bin/chromium", "--foo", B] and
        uygulama.erisim_bayragi_ekle(["/usr/bin/chromium", B]) == ["/usr/bin/chromium", B] and
        uygulama.erisim_bayragi_ekle(["/usr/bin/firefox", "-P"]) == ["/usr/bin/firefox", "-P"])
fk = ["flatpak", "run", "--branch=stable", "--arch=x86_64", "--command=discord", "com.discordapp.Discord"]
kontrol("Flatpak Electron: bayrak uygulama kimliğinden SONRA (uygulamaya iletilir)",
        uygulama.erisim_bayragi_ekle(fk) == [*fk, B])
from deskhand.oturum import flatpak_ornek  # noqa: E402

sarmal = flatpak_ornek.sarmala(fk, "com.discordapp.Discord", "/tmp/kayit.json", None)
yeni_ = uygulama.erisim_bayragi_ekle(sarmal)
kontrol("Flatpak Electron: Deskhand sarmalayıcısı içindeki komut da tanınır, bayrak sonda ('--' sonrası)",
        uygulama.chromium_ailesi_mi(sarmal) and yeni_ == [*sarmal, B] and yeni_.index("--") < yeni_.index(B))
with open(os.path.join(_yalitim.GECICI, "vivaldi.desktop"), "w") as f:
    f.write("[Desktop Entry]\nType=Application\nName=Tarayici\nExec=/usr/bin/vivaldi-stable %U\n"
            "[Desktop Action yeni]\nExec=/usr/bin/yanlis\n")
with open(os.path.join(_yalitim.GECICI, "okur.desktop"), "w") as f:
    f.write("[Desktop Entry]\nType=Application\nName=Okur\nExec=/usr/bin/okular %U\n")
kontrol(".desktop (gio launch) Chromium ailesiyse Exec doğrudan + bayrak ('%U' atılır, eylem bölümü yok sayılır)",
        uygulama.erisim_bayragi_ekle(["gio", "launch", os.path.join(_yalitim.GECICI, "vivaldi.desktop")]) ==
        ["/usr/bin/vivaldi-stable", B])
kontrol(".desktop (gio launch) Chromium ailesi değilse komut aynen",
        uygulama.erisim_bayragi_ekle(["gio", "launch", os.path.join(_yalitim.GECICI, "okur.desktop")]) ==
        ["gio", "launch", os.path.join(_yalitim.GECICI, "okur.desktop")])


class BaslatAU(SahteAU):
    ad = "sanal"

    def __init__(self):
        super().__init__()
        self.baslatilan = []

    def kimlikler(self): return []
    def baslat(self, argv, env=None, cikti=None):
        self.baslatilan.append(list(argv))
        raise Dur(7, "yeni pencere beklenmiyor (test)")


for ad_, beklenen_bayrak in (("sanal", True), ("kde", False)):
    bau = BaslatAU()
    bau.ad = ad_
    arka_uc._ORNEKLER[ad_] = bau
    with arka_uc.hedef_sabit(ad_):
        kod = kod_al(api.uygulama_ac, ["/usr/bin/chromium"], "Chromium", [])
    kontrol(f"api.uygulama_ac ({ad_}): Chromium komutuna bayrak {'EKLENİR' if beklenen_bayrak else 'eklenmez (kullanıcının ekranı)'}",
            bool(bau.baslatilan) and (B in bau.baslatilan[0]) is beklenen_bayrak, str(bau.baslatilan))
arka_uc._ORNEKLER.pop("sanal", None)

# ================================================================ B) sanal masaüstü + gerçek Qt penceresi
print("\nB) sanal masaüstü + gerçek Qt penceresi")


def gercek_a11y():
    return subprocess.run(["busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                           "IsEnabled"], capture_output=True, text=True).stdout.strip()


def sanal_mumkun():
    try:
        import PyQt6  # noqa: F401
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # noqa: F401
    except (ImportError, ValueError):
        return False
    return all(shutil.which(a) for a in ("Xvfb", "dbus-daemon", "busctl", "systemd-run")) and \
        os.path.exists("/usr/lib/at-spi-bus-launcher") and os.path.exists("/usr/lib/at-spi2-registryd")


if not sanal_mumkun():
    print("ATLANDI: Xvfb / PyQt6 / at-spi2-core yok")
else:
    gercek0 = gercek_a11y()  # kullanıcının GERÇEK oturumu: baştan sona dokunulmaz
    BASLIK = "a11y-deneme"
    LOG = os.path.join(_yalitim.GECICI, "a11y.log")

    def log():
        try:
            with open(LOG) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def cli_(*argv, zaman=60):
        r = subprocess.run([sys.executable, "-m", "deskhand", "--arka", *argv], capture_output=True, text=True,
                           timeout=zaman, cwd=KOK)
        return r.returncode, (r.stdout + r.stderr).strip()

    def olay(ad, argv, beklenen, kod_beklenen=0):
        n0 = len(log())
        kod, cikti = cli_(*argv)
        time.sleep(0.25)
        yeni = log()[n0:]
        ok = kod == kod_beklenen and (beklenen in yeni if beklenen is not None else not (kod_beklenen and yeni))
        kontrol(f"sanal: {ad}", ok, f"kod {kod} log {yeni} {cikti[-200:]}")
        return cikti

    import importlib  # A bölümünün sahte yamaları (erisim.*) temizlensin: B gerçek işlevlerle çalışır
    importlib.reload(erisim)

    d = masaustu.masaustu_baslat()
    try:
        kontrol("sanal: masaüstü açılırken erişilebilirlik hazırlandı (uyarı yok, adres var, kayıt defteri canlı)",
                d.get("a11y_adres") and (d.get("pid") or {}).get("a11y") and masaustu._canli(d["pid"]["a11y"]) and
                not [u for u in d["uyarilar"] if "erişilebilirlik" in u], str(d.get("uyarilar")))
        ac = subprocess.run(["busctl", f"--address={d['dbus_adres']}", "get-property", "org.a11y.Bus", "/org/a11y/bus",
                             "org.a11y.Status", "IsEnabled"], capture_output=True, text=True).stdout.strip()
        kontrol("sanal: IsEnabled uygulamalar BAŞLAMADAN ÖNCE açık (özel veri yolunda)", ac == "b true", ac)
        kontrol("sanal: gerçek oturumun erişilebilirlik durumu değişmedi", gercek_a11y() == gercek0, gercek_a11y())
        masaustu.baslat([sys.executable, os.path.join(KOK, "tests/yardimci/a11y_pencere.py")],
                        {"LOG": LOG, "PENCERE_BASLIK": BASLIK})
        t0 = time.monotonic()
        while time.monotonic() - t0 < 20 and "hazir" not in log():
            time.sleep(0.2)
        cikti = ""
        for _i in range(40):  # uygulamanın ağaca girmesi
            kod, cikti = cli_("agac", BASLIK, "--hepsi")
            if kod == 0 and "Kaydet" in cikti:
                break
            time.sleep(0.25)
        kontrol("sanal: agac — Qt penceresinin ögeleri ad + konumla (uygulamadan önce açık olduğu için ağaçta)",
                "button: Kaydet" in cikti and "check box: Onayla" in cikti and "spin button: Adet" in cikti, cikti[-300:])
        olay("düğme (Press)", ["click-element", BASLIK, "Kaydet", "--role", "button", "--action"], "tikla:Kaydet")
        olay("onay kutusu aç", ["click-element", BASLIK, "Onayla", "--action"], "isaret:Onayla:1")
        olay("onay kutusu kapat", ["click-element", BASLIK, "Onayla", "--action"], "isaret:Onayla:0")
        olay("radyo düğmesi", ["click-element", BASLIK, "Seçenek A", "--action"], "radyo:Seçenek A:1")
        olay("metin alanı (Türkçe harf)", ["set-element", BASLIK, "Ad", "Çağrı İşlem ğüş"], "metin:Ad:Çağrı İşlem ğüş")
        olay("parola alanı (--onayli: parola alanı onay ister)", ["set-element", BASLIK, "Parola", "sir-123-xyz", "--secret",
                                    "--approved"], "metin:Parola:sir-123-xyz")
        olay("sayı kutusu", ["set-element", BASLIK, "Adet", "7"], "deger:Adet:7")
        olay("kaydırgaç", ["set-element", BASLIK, "Ses", "4"], "deger:Ses:4")
        olay("sekme", ["click-element", BASLIK, "Gelişmiş", "--action"], "sekme:Gelişmiş")
        olay("liste ögesi (Toggle seçer)", ["click-element", BASLIK, "İkinci", "--action"], "liste-secim:İkinci")
        olay("menü aç (Show Menu, adı elle)", ["click-element", BASLIK, "Dosya", "--action", "Show Menu"], None)
        time.sleep(0.4)
        olay("menü ögesi", ["click-element", BASLIK, "Aç", "--action"], "menu:Aç")
        olay("açılır liste aç (Press)", ["click-element", BASLIK, "Kırmızı", "--role", "combo", "--action"], None)
        # BİLİNEN SINIR: açılır listenin ögesi Toggle ile seçilmez (combobox etkinleşmez); ölçüm raporunda
        kod, cikti = cli_("click-element", BASLIK, "Yeşil", "--action")
        kontrol("sanal: açılır liste ögesi eylemi çalıştırılır (ancak combobox seçimi değişmez: bilinen sınır)", kod == 0
                and "secim:Renk:Yeşil" not in log(), cikti[-200:])
        olay("pasif düğme → 6", ["click-element", BASLIK, "Pasif düğme", "--action"], None, 6)
        olay("olmayan öge → 6", ["click-element", BASLIK, "Yokyok", "--action"], None, 6)

        # güvenlik: gerçek pencerede, aynı denetimler
        n0 = len(log())
        guvenlik.dur_ac("cli")
        kod, cikti = cli_("click-element", BASLIK, "Tamam", "--action")
        kontrol("sanal güvenlik: DUR → 13, eylem yok", kod == 13 and log()[n0:] == [], f"{kod} {cikti[-150:]}")
        kod, cikti = cli_("set-element", BASLIK, "Ad", "yazilmamali")
        kontrol("sanal güvenlik: DUR → yazma da 13", kod == 13 and "metin:Ad:yazilmamali" not in log())
        guvenlik.dur_kapat("cli")
        os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True)
        with open(yollar.yasak_dosya(), "w") as f:
            f.write(BASLIK + "\n")
        kod, cikti = cli_("click-element", BASLIK, "Tamam", "--action")
        kontrol("sanal güvenlik: yasak pencere → 10, eylem yok", kod == 10 and log()[n0:] == [], f"{kod} {cikti[-150:]}")
        os.remove(yollar.yasak_dosya())
        kod, cikti = cli_("-b", "^baska$", "click-element", BASLIK, "Tamam", "--action")
        kontrol("sanal güvenlik: başlık kilidi uymadı → 4, eylem yok", kod == 4 and log()[n0:] == [], f"{kod} {cikti[-150:]}")
        kod, cikti = cli_("-s", "^baskasinif$", "set-element", BASLIK, "Ad", "yazilmamali")
        kontrol("sanal güvenlik: sınıf kilidi uymadı → 4, yazılmadı", kod == 4 and "metin:Ad:yazilmamali" not in log(),
                f"{kod} {cikti[-150:]}")
        kod, cikti = cli_("click-element", BASLIK, "Satın al", "--action")
        kontrol("sanal güvenlik: hassas düğme 'Satın al' (panel kapalı) → 10, eylem yok",
                kod == 10 and "tikla:Satın al" not in log(), f"{kod} {cikti[-150:]}")
        kod, cikti = cli_("click-element", BASLIK, "Satın al", "--action", "--approved")
        time.sleep(0.25)
        kontrol("sanal güvenlik: hassas düğme --approved ile yapılır", kod == 0 and "tikla:Satın al" in log(), f"{kod} {cikti[-150:]}")
        # günlük: eylem satırları, gizli yazı düşmedi
        gun = "\n".join(gunluk_satirlari())
        kontrol("sanal günlük: eylem satırı sanal biçimde (arka :N [başlık]) ve --onayli işareti",
                re.search(r"ogeye-tikla 'Kaydet' --eylem Press \| arka :\d+ \[a11y-deneme\] \| atspi action Press", gun)
                is not None and "--eylem Press --onayli | arka" in gun, gun[-500:])
        kontrol("sanal günlük: parola yazısı günlüğe DÜŞMEDİ (password text + --secret)", "sir-123-xyz" not in gun and
                "***(11)" in gun)
        kontrol("sanal günlük: normal metin görünür", "Çağrı İşlem ğüş" in gun)

        # yardımcı süreç yolu: bu süreç başka veri yoluna bağlıysa (MCP: iki masaüstü) iş yardımcı süreçte yürür
        with arka_uc.hedef_sabit("sanal"):
            onceki = erisim._BAGLI[0]
            erisim._BAGLI[0] = "unix:path=/yok/baska-veri-yolu"
            try:
                ogeler, sure = erisim.erisim_ogeleri(api.arka().pencere_coz(BASLIK))
                kontrol("sanal: başka veri yoluna bağlı süreçte ağaç YARDIMCI süreçle okunur (ögeler + yol)",
                        any(o["ad"] == "Kaydet" and o["yol"] for o in ogeler), f"{len(ogeler)} öge")
                n0 = len(log())
                api.ogeye_tikla(api.arka().pencere_coz(BASLIK), "Tamam", eylem="")
                time.sleep(0.25)
                kontrol("sanal: eylem de yardımcı süreçte yapılır", "tikla:Tamam" in log()[n0:], str(log()[n0:]))
                kontrol("sanal: yardımcı süreç bu sürecin veri yolu bağlantısını DEĞİŞTİRMEZ",
                        erisim._BAGLI[0] == "unix:path=/yok/baska-veri-yolu")
            finally:
                erisim._BAGLI[0] = onceki

        # kapalıyken kendiliğinden açma (sanal): özel veri yolunda IsEnabled=false → ilk çağrı açar
        subprocess.run(["busctl", f"--address={d['dbus_adres']}", "set-property", "org.a11y.Bus", "/org/a11y/bus",
                        "org.a11y.Status", "IsEnabled", "b", "false"], capture_output=True)
        with arka_uc.hedef_sabit("sanal"):
            acildi = erisim.erisim_ac_garanti()
            kontrol("sanal: kapalıyken erisim_ac_garanti kendiliğinden açar (True), özel veri yolunda",
                    acildi is True and erisim.erisim_acik() and gercek_a11y() == gercek0)
            # kayıt defteri ölmüşse erisim_hazirla yeniden başlatır
            eski = masaustu.durum_oku()["pid"]["a11y"]
            os.kill(eski, 15)
            time.sleep(0.5)
            a11y = masaustu.erisim_hazirla()
            yeni = masaustu.durum_oku()["pid"]["a11y"]
            kontrol("sanal: kayıt defteri ölürse erisim_hazirla yeniden başlatır (yeni pid, durum dosyasına yazıldı)",
                    a11y and yeni != eski and masaustu._canli(yeni), f"{eski}→{yeni}")
        kontrol("sanal: gerçek oturumun erişilebilirlik durumu baştan sona değişmedi", gercek_a11y() == gercek0,
                gercek_a11y())
    finally:
        masaustu.masaustu_durdur()

onay.iste_sonuc = gercek_iste_sonuc
print(f"\n{GECEN}/{TOPLAM} erişilebilirlik testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
