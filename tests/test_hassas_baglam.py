"""Hassas düğme bağlamı: tıklanan noktanın OCR komşu satırlarından bir DÜZENLENEBİLİR ALANIN (textarea/entry) İÇERİĞİ
hassas düğme sayılmaz; ödeme sayfası, hedefin kendi adı ve kanıtlanamayan her durum (ağaç yok, kutusuz yazı) eskisi gibi.

Gerçek olay (28 Kas 00:31): Glama profil sayfasında açıklama textarea'sına koordinatlı tık (yeniden yazmak için odak)
→ alanın içindeki "…Buy/Pay buttons and payment pages…" satırları OCR ile "noktadaki yazı" oldu → 'pay' → HASSAS düğme,
kullanıcıya ödeme onayı çıktı.

Ekransız: sahte arka uç, sahte onay paneli, sahte erişilebilirlik ağacı. Gerçek ekrana/panoya girdi yok; gerçek ~/.config
yazılmaz (_yalitim). Çalıştır:  python3 tests/test_hassas_baglam.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import sys

from PIL import Image

from deskhand import arka_uc, erisim, eylem, guvenlik, liste_koruma, ocr, onay, web
from deskhand.arka_uc import EKRAN
from deskhand.hata import Dur

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


liste_koruma.panel_baslat()  # bu süreç panel gibi (kapsam yazımı yetkili)


def kapsam(deger):
    liste_koruma.panel_kapsam_kaydet(deger)
    guvenlik.onay_kapsami_sifirla()
    return guvenlik.onay_kapsami() == deger


class SahteGirdi:
    def __init__(self, au):
        self.au, self.etiket = au, ""


class SahteAU(arka_uc.ArkaUc):
    def __init__(self):
        self.ad = "kde"
        self.pen = {"{g}": ["Profile | deskhand mcp | Glama — Mozilla Firefox", "firefox", (0, 0, 1200, 900)],
                    "{o}": ["Checkout — Shop — Mozilla Firefox", "firefox", (0, 0, 1200, 900)]}
        self.on = "{g}"

    def pencere_coz(self, arg): return arg
    def pencereler(self, desen=None): return []
    def geometri(self, k): return self.pen[k][2] if k != EKRAN else (0, 0, 1920, 1080)
    def baslik(self, k): return self.pen.get(k, [""])[0]
    def sinif(self, k): return self.pen.get(k, ["", ""])[1]
    def aktif(self): return self.on
    def one_getir(self, k): self.on = k
    def kapat(self, k): pass
    def ekran_alani(self): return (0, 0, 1920, 1080)
    def goruntu(self): return Image.new("RGB", (1920, 1080), (200, 200, 200))
    def insan_var_mi(self): return False
    def gecerli_tuslar(self): return None
    def fare(self): return (5, 5, "{masaustu}")
    def girdi(self, etiket="", gizli=False, etk=None, denetle=None): raise AssertionError("girdi açılmamalı")
    def baslat(self, argv, env=None, cikti=None): raise AssertionError("başlatılmamalı")


ISTEKLER = []


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti})
    return onay.OnaySonucu(False, "red")


onay.iste_sonuc = sahte_iste_sonuc
au = SahteAU()
arka_uc._ORNEKLER["kde"] = au
eylem.insan_dogrulama_nokta = lambda *a, **k: None  # CAPTCHA kapısı bu takımın konusu değil (ağaç okumasın)

# ---------------------------------------------------------------- sahne (pencere pikseli)
# açıklama textarea'sı: x 300..900, y 200..400; içinde 3 satır. Save düğmesi hemen altında: 300..380 × 405..435
TEXTAREA = (300, 200, 600, 200)
SAVE = (300, 405, 80, 30)
PAY_ICERDE = (800, 360, 90, 30)  # textarea'nın sağ alt köşesine bindirilmiş bir "Pay" düğmesi (sohbet kutusu deseni)


def satir(t, x, y, x2, y2):
    return ocr.NoktaYazisi(t, (x, y, x2, y2))


TA1 = satir("click visible text, type, press keys, scroll, drag, open apps,", 310, 300, 880, 318)
TA2 = satir("uy/Pay buttons aîııııi“rııaymen't pzı-ıges wait for the user's appı", 310, 322, 880, 340)
TA3 = satir("uy/Pay buttons and payment pages wait for the user's appı", 310, 344, 860, 362)
SAVE_Y = satir("Save", 320, 412, 360, 428)

AGAC: dict = {"deger": ([TEXTAREA], [], [SAVE])}
CAGRI = [0]


def sahte_alanlar(k):
    CAGRI[0] += 1
    d = AGAC["deger"]
    if isinstance(d, Exception):
        raise d
    return d


GERCEK_ALANLAR, GERCEK_WEB_ALANLAR = erisim.duzenleme_alanlari, web.duzenleme_alanlari
erisim.duzenleme_alanlari = sahte_alanlar


def sorar(k, x, y, yakin, ek_metinler=()):
    """→ (Dur kodu | 0, sorulan onay sayısı, onay isteğinin metni)"""
    ISTEKLER.clear()
    guvenlik.eylem_basladi()
    try:
        eylem.hassas_nokta(SahteGirdi(au), k, False, "tıklama", x, y, list(yakin), ek_metinler=ek_metinler)
        kod = 0
    except Dur as e:
        kod = e.kod
    metin = " ".join(i["eylem"] + i["ayrinti"] + i["hedef"] for i in ISTEKLER)
    return kod, len(ISTEKLER), metin


with arka_uc.hedef_sabit("kde"):
    for mod in ("hepsi", "kart"):
        assert kapsam(mod)
        # (olay) textarea'nın İÇİNE tık: noktadaki yazılar alanın içeriği → hassas düğme DEĞİL
        AGAC["deger"] = ([TEXTAREA], [(0, 0, 1200, 900)], [SAVE])
        kod, n, m = sorar("{g}", 580, 331, [TA1, TA2, TA3])
        kontrol(f"[{mod}] (olay) textarea içine tık, içerikte 'Buy/Pay' → onay sorulmaz", kod == 0 and n == 0,
                f"{kod} {n} {m}")
        # (a) Save düğmesi; hemen üstündeki textarea satırı OCR komşusu → hassas DEĞİL
        kod, n, m = sorar("{g}", 340, 420, [SAVE_Y, TA3])
        kontrol(f"[{mod}] (a) Save + üstte 'Buy/Pay…' yazan textarea satırı → onay sorulmaz", kod == 0 and n == 0,
                f"{kod} {n} {m}")
        # (b) hedef düğmenin kendisi Pay → hassas (ağaç düzenleme alanı bildirse de; satır alanın DIŞINDA)
        pay = satir("Pay now", 960, 412, 1030, 428)
        kod, n, m = sorar("{g}", 990, 420, [pay])
        kontrol(f"[{mod}] (b) 'Pay now' düğmesi → onay ister (red → 10)", kod == 10 and n == 1, f"{kod} {n}")
        kod, n, m = sorar("{g}", 990, 420, [pay], ek_metinler=["Pay now"])
        kontrol(f"[{mod}] (b) öge adı 'Pay now' (ek metin, kutusuz) → onay ister", kod == 10 and n == 1, f"{kod} {n}")
        # (b2) textarea kutusunun İÇİNE bindirilmiş Pay düğmesi: satır başka bir ögeyle kesişiyor → içerik sayılmaz
        AGAC["deger"] = ([TEXTAREA], [], [SAVE, PAY_ICERDE])
        pay_ic = satir("Pay", 820, 368, 860, 384)
        kod, n, m = sorar("{g}", 840, 375, [pay_ic])
        kontrol(f"[{mod}] (b2) textarea'ya bindirilmiş 'Pay' düğmesi → onay ister", kod == 10 and n == 1, f"{kod} {n}")
        # (b3) hedefin kendi adı/aranan metni (ek_metinler) ayıklanmaz: textarea satırında 'pay' olsa da
        AGAC["deger"] = ([TEXTAREA], [(0, 0, 1200, 900)], [SAVE])
        kod, n, m = sorar("{g}", 580, 353, [TA3], ek_metinler=[str(TA3)])
        kontrol(f"[{mod}] (b3) hedef metni (ek_metinler) 'Pay…' → onay ister", kod == 10 and n == 1, f"{kod} {n}")

    # (c) ödeme SAYFASINDA Save → hassas sayfa (başlık); textarea ayıklaması sayfa algısını değiştirmez
    assert kapsam("hepsi")
    AGAC["deger"] = ([TEXTAREA], [(0, 0, 1200, 900)], [SAVE])
    kod, n, m = sorar("{o}", 340, 420, [SAVE_Y, TA3])
    kontrol("(c) ödeme sayfasında (Checkout) Save → onay ister (red → 10)", kod == 10 and n == 1, f"{kod} {n}")
    kod, n, m = sorar("{o}", 580, 331, [TA1, TA2, TA3])
    kontrol("(c) ödeme sayfasında textarea içine tık → yine onay ister", kod == 10 and n == 1, f"{kod} {n}")

    # (d) yalnız OCR: ağaç okunamadı (Dur / istisna / None) → eski davranış: komşu satırda 'pay' → hassas
    for ad, deger in (("Dur 6", Dur(6, "ağaçta yok")), ("RuntimeError", RuntimeError("d-bus")), ("None", None)):
        AGAC["deger"] = deger
        kod, n, m = sorar("{g}", 580, 331, [TA1, TA2, TA3])
        kontrol(f"(d) ağaç yok ({ad}) + komşu satırda 'pay' → onay ister", kod == 10 and n == 1, f"{kod} {n}")
    # (d2) ağaç var ama düzenlenebilir alan yok → hassas
    AGAC["deger"] = ([], [], [SAVE])
    kod, n, m = sorar("{g}", 580, 331, [TA1, TA2, TA3])
    kontrol("(d2) ağaçta düzenlenebilir alan yok → onay ister", kod == 10 and n == 1, f"{kod} {n}")
    # (d3) kutusuz düz yazı (eski çağıran) → ayıklanmaz → hassas
    AGAC["deger"] = ([TEXTAREA], [(0, 0, 1200, 900)], [SAVE])
    kod, n, m = sorar("{g}", 580, 331, [str(TA2), str(TA3)])
    kontrol("(d3) kutusuz noktadaki yazı → onay ister (kanıt yok)", kod == 10 and n == 1, f"{kod} {n}")
    # (d4) satır alanın DIŞINA taşıyor (aynı satırda alan + yanında düğme) → ayıklanmaz
    tasan = satir("Buy/Pay buttons … Pay", 310, 344, 1030, 362)
    kod, n, m = sorar("{g}", 580, 353, [tasan])
    kontrol("(d4) textarea'dan dışarı taşan satır → onay ister", kod == 10 and n == 1, f"{kod} {n}")
    # (d5) masaüstü kipi (EKRAN): ağaç sorulmaz, eski davranış
    CAGRI[0] = 0
    kod, n, m = sorar(EKRAN, 580, 331, [TA2])
    kontrol("(d5) masaüstü kipi → ağaç sorulmaz, onay ister", kod == 10 and n == 1 and CAGRI[0] == 0,
            f"{kod} {n} {CAGRI[0]}")
    # maliyet: noktadaki yazıda hassas kalıp yoksa ağaç hiç okunmaz
    CAGRI[0] = 0
    kod, n, m = sorar("{g}", 340, 420, [SAVE_Y])
    kontrol("hassas kalıp yokken ağaç okunmaz (tık gecikmesi yok)", kod == 0 and n == 0 and CAGRI[0] == 0,
            f"{kod} {n} {CAGRI[0]}")

# ---------------------------------------------------------------- saf karar işlevi
ay = guvenlik.duzenleme_icerigini_ayikla
kalan, cikan = ay([SAVE_Y, TA3], [TEXTAREA], [], [SAVE])
kontrol("ayıkla: textarea satırı çıkar, Save kalır", kalan == [SAVE_Y] and cikan == [TA3], f"{kalan} {cikan}")
kalan, cikan = ay([TA3], [TEXTAREA], [(0, 0, 1200, 900), TEXTAREA], [])  # kapsayıcı belge + aynı boyda sarmalayıcı
kontrol("ayıkla: alanı kapsayan etkileşimsiz kap kesişim sayılmaz", cikan == [TA3], f"{kalan} {cikan}")
kalan, cikan = ay([TA3], [TEXTAREA], [(850, 340, 40, 30)], [])
kontrol("ayıkla: alanın içindeki etkileşimsiz öge satırla kesişiyor → kalır", kalan == [TA3] and not cikan)
kalan, cikan = ay([TA3], [TEXTAREA], [], [TEXTAREA])
kontrol("ayıkla: alanı birebir örten düğme (tık düğmeye gider) → kalır", kalan == [TA3] and not cikan)
kalan, cikan = ay([TA3], [TEXTAREA], [], [(0, 0, 1200, 900)])
kontrol("ayıkla: alanı kapsayan düğme/bağlantı → kalır", kalan == [TA3] and not cikan)
kalan, cikan = ay(["Pay"], [TEXTAREA], [], [])
kontrol("ayıkla: kutusuz yazı hep kalır", kalan == ["Pay"] and not cikan)
kalan, cikan = ay([satir("Pay", 310, 344, 310, 362)], [TEXTAREA], [], [])
kontrol("ayıkla: sıfır alanlı kutu ayıklanmaz", len(kalan) == 1 and not cikan)

# ---------------------------------------------------------------- nokta_metni kutu taşır
_eski = (ocr.korumali_goruntu, ocr.oku, ocr.satirla)
try:
    ocr.korumali_goruntu = lambda k, b, kararli=False: (Image.new("RGB", (440, 70)), None, (100, 200))
    ocr.oku = lambda im, **s: ["w"]
    ocr.satirla = lambda ws: [{"t": "Pay now", "x": 200, "y": 20, "x2": 260, "y2": 40, "cx": 230, "cy": 30}]
    y = ocr.nokta_metni("{g}", 330, 230)
    kontrol("nokta_metni: yazı + pencere pikseli kutusu (NoktaYazisi)",
            y == ["Pay now"] and getattr(y[0], "kutu", None) == (300, 220, 360, 240), f"{y} {getattr(y[0], 'kutu', 0)}")
finally:
    ocr.korumali_goruntu, ocr.oku, ocr.satirla = _eski

# ---------------------------------------------------------------- ağaç sağlayıcıları (erisim / web)
erisim.duzenleme_alanlari = GERCEK_ALANLAR
from deskhand import dogrulama_sinamasi  # noqa: E402

_t = dogrulama_sinamasi.tarayici_mi
try:
    dogrulama_sinamasi.tarayici_mi = lambda k: False
    erisim.erisim_ogeleri = lambda k, **kw: ([
        {"rol": "text", "ad": "", "x": 10, "y": 10, "w": 100, "h": 50, "durumlar": []},
        {"rol": "text", "ad": "", "x": 10, "y": 70, "w": 100, "h": 50, "durumlar": ["readonly"]},
        {"rol": "push button", "ad": "Save", "x": 10, "y": 130, "w": 40, "h": 20, "durumlar": []},
    ], 0.1)
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("erisim: düzenlenebilir text alan; salt okunur alan ve düğme 'dugmeler'",
            r is not None and r[0] == [(10, 10, 100, 50)] and r[2] == [(10, 70, 100, 50), (10, 130, 40, 20)], str(r))
    erisim.erisim_ogeleri = lambda k, **kw: ([{"rol": "text", "ad": "", "x": 10, "y": 10, "w": 100, "h": 50}], 0.1)
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("erisim: durum bilgisi yoksa alan sayılmaz (olumlu kanıt şart)", r is not None and r[0] == [], str(r))

    def _patlar(k, **kw):
        raise Dur(6, "ağaçta yok")
    erisim.erisim_ogeleri = _patlar
    kontrol("erisim: ağaç okunamadı → None", erisim.duzenleme_alanlari("{g}") is None)

    dogrulama_sinamasi.tarayici_mi = lambda k: True
    web.duzenleme_alanlari = lambda k: ([(1, 2, 3, 4)], [], [])
    kontrol("erisim: tarayıcı → web sağlayıcısı", erisim.duzenleme_alanlari("{g}") == ([(1, 2, 3, 4)], [], []))
    kontrol("erisim: masaüstü kipi → None", erisim.duzenleme_alanlari(EKRAN) is None)
finally:
    dogrulama_sinamasi.tarayici_mi = _t

web.duzenleme_alanlari = GERCEK_WEB_ALANLAR


class _Yol:
    def kapat(self): pass


def _ham(rol, d, kutu, alan=None):
    return {"rol": rol, "ad": "", "_d": set(d), "_kutu": kutu, "_alan": alan, "_derin": 1, "_yol": "/x",
            "_anahtar": (0,), "_adres": ""}


HAM = [_ham("entry", {"editable", "showing", "visible", "multi_line"}, (300, 200, 600, 200), (0, 0, 1200, 900)),
       _ham("entry", {"read_only", "showing", "visible"}, (300, 450, 600, 30), (0, 0, 1200, 900)),
       _ham("button", {"showing", "visible"}, (300, 405, 80, 30), (0, 0, 1200, 900)),
       _ham("entry", {"editable", "showing", "visible"}, (300, 850, 600, 100), (0, 0, 1200, 880)),
       _ham("entry", {"editable"}, (300, 600, 600, 100), (0, 0, 1200, 880)),  # görünmeyen alan: hiçbir listede
       _ham("static", {"showing", "visible"}, (820, 360, 50, 20), (0, 0, 1200, 900))]  # alana bindirilmiş yazı
KONUM = {"v": "kuresel_cerceve"}
web._baglam = lambda k, islem="tara": (au, _Yol(), "bus", "/c", 0, (0, 0), KONUM["v"])
web._yuru = lambda *a, **k: (HAM, [{"ad": "Profile | deskhand mcp | Glama", "adres": "", "durum": set(),
                                    "derinlik": 1, "kutu": (0, 0, 1200, 900)}], 10)
r = web.duzenleme_alanlari("{g}")
kontrol("web: düzenlenebilir entry alan (görüş alanına kırpılır); salt okunur entry ve düğme 'dugmeler'",
        r is not None and r[0] == [(300, 200, 600, 200), (300, 850, 600, 30)]
        and r[2] == [(300, 450, 600, 30), (300, 405, 80, 30)] and r[1] == [(820, 360, 50, 20)], str(r))
KONUM["v"] = None
kontrol("web: öge konumu doğrulanamadı → None", web.duzenleme_alanlari("{g}") is None)
KONUM["v"] = "kuresel_cerceve"
web._yuru = lambda *a, **k: (HAM, [{"ad": "Başka sayfa", "adres": "", "durum": set(), "derinlik": 1,
                                    "kutu": (0, 0, 1200, 900)}], 10)
kontrol("web: belge pencereye ait değil (sayfa belirsiz) → None", web.duzenleme_alanlari("{g}") is None)

print(f"\n{GECEN}/{TOPLAM} hassas-bağlam testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
