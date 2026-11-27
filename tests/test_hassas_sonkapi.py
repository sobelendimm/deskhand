"""Hassas düğme bağlamı, son kapı (INCELEME-SONKAPI-HASSAS A/B): saldırgan sayfa yazarının PoC'leri kilitli test.

A1  nokta_metni aynı yazılı iki satırı (alandaki "Pay now" + gerçek "Pay now" düğmesi) tek satıra indirmez.
A2  kendi tıklaması ya da "click ancestor"/"clickAncestor" eylemi olan öge hiçbir boyutta kap değil (P1 tam ekran
    onclick sarmalayıcı, P1b iframe dolduran sarmalayıcı, PoC-2c örtü), alan kanıtı da değil (React contenteditable).
A3  terimsiz satır ayıklanmaz; hassas sözcük değerde BAĞLAMIYLA (komşu sözcük) ya da tam satır olarak geçmeli (P6).
A4  ağaç okuma kapısı süzgeçle aynı koşul: yalnız yapıştırma satırı da ağacı okutur.

Ekransız: sahte OCR, sahte AT-SPI ögeleri; gerçek ekrana/veri yoluna dokunulmaz.
Çalıştır:  python3 tests/test_hassas_sonkapi.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import sys

from deskhand import eylem, guvenlik, ocr

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def satir(t, x, y, x2, y2):
    return ocr.NoktaYazisi(t, (x, y, x2, y2))


ay, kap, alan = guvenlik.duzenleme_icerigini_ayikla, guvenlik.duzenleme_kabi_mi, guvenlik.alan_kanitli_mi

# ---------------------------------------------------------------- A1 nokta_metni (yazı, kutu) tekilleştirme
print("A1) nokta_metni aynı yazılı satırları kutusuyla ayırır")
_eski = (ocr.korumali_goruntu, ocr.oku, ocr.satirla, ocr.kok_ekle)
try:
    ocr.korumali_goruntu = lambda k, r, kararli=True: (None, None, None)
    ocr.oku = lambda im, **s: ["x"]
    ocr.satirla = lambda ws: [{"t": "Pay now", "x": 110, "y": 140, "x2": 180, "y2": 156},   # textarea'nın son satırı
                              {"t": "Pay now", "x": 110, "y": 166, "x2": 180, "y2": 182}]   # gerçek <button>
    ocr.kok_ekle = lambda s, kok: s
    yakin = ocr.nokta_metni("pencere", 145, 170)  # tık gerçek düğmenin üstünde
finally:
    ocr.korumali_goruntu, ocr.oku, ocr.satirla, ocr.kok_ekle = _eski
kutular = sorted(t.kutu for t in yakin)
kontrol("A1 nokta_metni: aynı yazılı iki satır ikisi de döner (kutuları farklı)",
        kutular == [(110, 140, 180, 156), (110, 166, 180, 182)], str(kutular))
kontrol("A1 nokta_metni: aynı (yazı, kutu) birden çok okumada tek satır", len(yakin) == 2, str(len(yakin)))
TA = (100, 100, 300, 60)  # textarea y 100..160
DUGME = (105, 163, 90, 22)
kalan, cikan = ay(yakin, [(*TA, "Order note:\nPay now")], [], [DUGME], [])
kontrol("A1 alandaki 'Pay now' gerçek 'Pay now' düğmesini yutmaz → onay istenir",
        bool(guvenlik.hassas_mi(*kalan)) and [t.kutu for t in kalan] == [(110, 166, 180, 182)], f"{kalan} {cikan}")

# ---------------------------------------------------------------- A2 kap / alan kanıtı
print("A2) tıklanır öge (kendi ya da atasının tıklaması) kap değil, alan kanıtı değil")
TA2 = (100, 100, 300, 100)
GORUS = (0, 0, 1200, 900)
L = satir("Pay now", 110, 150, 200, 168)
kontrol("A2 P1 tam ekran onclick sarmalayıcı ['click'] → kap DEĞİL", kap(GORUS, ["click"], [TA2]) is False)
kontrol("A2 P1 sayfadan uzun tıklanır kök ['click'] → kap DEĞİL", kap((0, 0, 1200, 3000), ["click"], [TA2]) is False)
kontrol("A2 P1b iframe dolduran tıklanır sarmalayıcı → kap DEĞİL", kap((95, 95, 310, 110), ["click"], [TA2]) is False)
kontrol("A2 PoC-2c 'click ancestor' örtü → kap DEĞİL", kap((90, 90, 320, 120), ["click ancestor"], [TA2]) is False)
kontrol("A2 Firefox 'clickAncestor' örtü → kap DEĞİL", kap((90, 90, 320, 120), ["clickAncestor"], [TA2]) is False)
kontrol("A2 eylemsiz kap hâlâ kap", kap((90, 90, 320, 120), [], [TA2]) is True)
kontrol("A2 odak/menü eylemli kap hâlâ kap", kap((90, 90, 320, 120), ["focus", "showMenu"], [TA2]) is True)
kontrol("A2 React contenteditable ['click ancestor'] → alan kanıtı DEĞİL", alan("", ["click ancestor"]) is False)
kontrol("A2 textarea ['activate'] → alan", alan("", ["activate"]) is True)
kalan, cikan = ay([L], [(*TA2, "Notes: Pay now please")], [GORUS], [], [])
kontrol("A2 P1 sarmalayıcı digerleri'nde → satır kalır", kalan == [L] and not cikan, f"{kalan} {cikan}")

# ---------------------------------------------------------------- A3 değer kanıtı
print("A3) değer kanıtı: terimsiz satır kalır; hassas sözcük bağlamıyla ya da tam satır")
P6 = satir("Pay", 110, 150, 150, 168)
kalan, cikan = ay([P6], [(*TA2, "I will pay later")], [], [], [])
kontrol("A3 P6 alana boyanmış tek 'Pay', değerde başka yerde 'pay' → kalır", kalan == [P6] and not cikan,
        f"{kalan} {cikan}")
duz = satir("Order note:", 110, 120, 200, 138)
kalan, cikan = ay([duz], [(*TA2, "Order note:\nPay now")], [], [], [])
kontrol("A3 terimsiz satır asla ayıklanmaz (sayaç bozulmaz)", kalan == [duz] and not cikan, f"{kalan} {cikan}")
tam = satir("Pay now", 110, 140, 180, 156)
kalan, cikan = ay([tam], [(*TA2, "Order note:\nPay now")], [], [], [])
kontrol("A3 değerin tam satırı 'Pay now' → ayıklanır", cikan == [tam], f"{kalan} {cikan}")
bag = satir("you can pay now, or", 110, 150, 300, 168)
kalan, cikan = ay([bag], [(*TA2, "Notes:\nyou can pay now, or later")], [], [], [])
kontrol("A3 hassas sözcük komşu sözcüğüyle değerde → ayıklanır", cikan == [bag], f"{kalan} {cikan}")
yan = satir("Pay now immediately", 110, 150, 300, 168)
kalan, cikan = ay([yan], [(*TA2, "you can pay now, or later; act immediately")], [], [], [])
kontrol("A3 komşu sözcük değerde bitişik değil → kalır", kalan == [yan] and not cikan, f"{kalan} {cikan}")
gurultu = satir("uy/Pay buttons and payment pages wait for the user's appı", 110, 150, 390, 168)
kalan, cikan = ay([gurultu], [(*TA2, "Buy/Pay buttons and payment pages wait for the user's approval.")], [], [], [])
kontrol("A3 OCR gürültülü satır (Glama) bağlamıyla → ayıklanır", cikan == [gurultu], f"{kalan} {cikan}")

# ---------------------------------------------------------------- A4 ağaç kapısı = süzgeç koşulu
print("A4) ağaç okuma kapısı süzgeçle aynı koşul")
from deskhand import erisim  # noqa: E402
_orj = erisim.duzenleme_alanlari
CAGRI = [0]


def _sahte(k):
    CAGRI[0] += 1
    return [(*TA2, "Paste here")], [], [], []


try:
    erisim.duzenleme_alanlari = _sahte
    yap = satir("Paste here", 110, 150, 200, 168)
    kalan = eylem.duzenleme_icerigi_suz("{g}", [yap])
    kontrol("A4 yalnız yapıştırma satırı da ağacı okutur ve ayıklanır", CAGRI[0] == 1 and kalan == [],
            f"{CAGRI[0]} {kalan}")
    CAGRI[0] = 0
    eylem.duzenleme_icerigi_suz("{g}", [satir("Save", 110, 150, 200, 168)])
    kontrol("A4 terimsiz satırda ağaç okunmaz (tık gecikmesi yok)", CAGRI[0] == 0, str(CAGRI[0]))
finally:
    erisim.duzenleme_alanlari = _orj

# ---------------------------------------------------------------- B ağaç okuma: eksik liste kesik=False dönmez
print("B1) tarayıcı dışı: merkezi pencere dışında, kutusu alanı örten öge listede")
from types import SimpleNamespace  # noqa: E402

from deskhand import dogrulama_sinamasi, web  # noqa: E402

DEGER = "Release notes: Buy/Pay buttons now ask first"
PAY = satir("Buy/Pay buttons now ask first", 110, 150, 380, 168)


class _Durum:
    def contains(self, s):
        return True


class _O:
    def __init__(s, kutu, coc=(), rol="panel", ad=""):
        s.k, s.c, s.r, s.a = kutu, list(coc), rol, ad

    def get_extents(s, t):
        return SimpleNamespace(x=s.k[0], y=s.k[1], width=s.k[2], height=s.k[3])

    def get_state_set(s):
        return _Durum()

    def get_role_name(s):
        return s.r

    def get_name(s):
        return s.a

    def get_child_count(s):
        return len(s.c)

    def get_child_at_index(s, i):
        return s.c[i]


_A = SimpleNamespace(CoordType=SimpleNamespace(WINDOW=1), StateType=SimpleNamespace(SHOWING=1, SENSITIVE=2))
ortu = _O((-700, 90, 1110, 120), rol="push button")  # x -700..410: alanı (100..400) örter, cx=-145
r = erisim._tara(_A, _O((0, 0, 700, 460), [_O((100, 100, 300, 100), rol="text", ad="Notes"), ortu], rol="frame"),
                 (0, 0, 700, 460), 100, 5.0, 100, eylem_hepsi=True)
roller = [o["rol"] for o in r["ogeler"]]
kontrol("B1 güvenlik taraması: merkezi dışarıda, pencereyle kesişen düğme listede", "push button" in roller,
        f"{roller} kesik={r['kesik']}")
r2 = erisim._tara(_A, _O((0, 0, 700, 460), [_O((-900, 90, 100, 120), rol="push button")], rol="frame"),
                  (0, 0, 700, 460), 100, 5.0, 100, eylem_hepsi=True)
kontrol("B1 pencereyle hiç kesişmeyen öge yine atılır", r2["ogeler"] == [], str(r2["ogeler"]))
r3 = erisim._tara(_A, _O((0, 0, 700, 460), [ortu], rol="frame"), (0, 0, 700, 460), 100, 5.0, 100)
kontrol("B1 listeleme taraması (eylem_hepsi yok) eski süzgeç: merkez pencerede", r3["ogeler"] == [], str(r3["ogeler"]))
ALAN_O = {"rol": "text", "ad": "Notes", "x": 100, "y": 100, "w": 300, "h": 100, "durumlar": [], "eylemler": [],
          "deger": DEGER}
_t0, _e0 = dogrulama_sinamasi.tarayici_mi, erisim.erisim_ogeleri_kesik
try:
    dogrulama_sinamasi.tarayici_mi = lambda k: False
    erisim.erisim_ogeleri_kesik = lambda k, **kw: ([ALAN_O] + [o for o in r["ogeler"] if o["rol"] != "text"], 0.1,
                                                   r["kesik"])
    s = erisim.duzenleme_alanlari("{g}")
    kalan, cikan = ay([PAY], *s)
    kontrol("B1 PoC-1: örtü düğme dugmeler'de → 'Buy/Pay' satırı kalır (onay istenir)", kalan == [PAY] and not cikan,
            f"{s} {cikan}")
finally:
    dogrulama_sinamasi.tarayici_mi, erisim.erisim_ogeleri_kesik = _t0, _e0


class _AgacYol:
    """Sahte erişilebilirlik yolu (test_hassas_kanit ile aynı): düğüm yolu → rol, ad, durum, kutu, çocuk, eylem, metin."""

    def __init__(self, dugumler, gecikme=0.0):
        self.d, self.gecikme = dugumler, gecikme

    def _yanit(self, m):
        from jeepney.low_level import HeaderFields
        f = m.header.fields
        uye, yol = f.get(HeaderFields.member), f.get(HeaderFields.path)
        n = self.d.get(yol)
        if n is None:
            return None
        if uye == "GetRoleName":
            return (n["rol"],)
        if uye == "Get" and m.body[1] == "Name":
            return (("s", n.get("ad", "")),)
        if uye == "Get" and m.body[1] == "NActions":
            return (("i", len(n.get("eylemler", []))),)
        if uye == "GetState":
            bit = sum(1 << web._DURUM_BIT[x] for x in n.get("durum", ("showing", "visible")))
            return ([bit & 0xFFFFFFFF, bit >> 32],)
        if uye == "GetChildren":
            return ([(":1.5", c) for c in n.get("cocuk", [])],)
        if uye == "GetExtents":
            return (tuple(n["kutu"]),) if n.get("kutu") else None
        if uye == "GetAttributes":
            return ({"DocURL": "https://ornek.test/"},)
        if uye == "GetInterfaces":
            return (n.get("arayuz", ["org.a11y.atspi.Accessible", "org.a11y.atspi.Component"]),)
        if uye == "GetName":
            return (n["eylemler"][m.body[0]],)
        if uye == "GetText":
            return (n.get("metin", ""),)
        return None

    def toplu(self, mesajlar, sure=10.0, yeniden=True):
        if self.gecikme:  # gerçek _toplu gibi: her parçadan önce tarama_siniri bitişi denetlenir
            import time
            time.sleep(self.gecikme)
            son = getattr(web._SINIR, "bitis", None)
            if son is not None and time.monotonic() >= son:
                raise web.Dur(web.ARAC_EKSIK, "süre sınırı")
        return [self._yanit(m) for m in mesajlar]

    def kapat(self):
        pass


def _sahne(ekler, belge_cocuk, gecikme=0.0):
    d = {"/c": {"rol": "frame", "cocuk": ["/doc"], "kutu": (0, 0, 1200, 900)},
         "/doc": {"rol": "document web", "ad": "Glama", "cocuk": belge_cocuk, "kutu": (0, 0, 1200, 900)},
         "/alan": {"rol": "entry", "ad": "Description", "durum": ("editable", "showing", "visible"),
                   "kutu": (100, 100, 300, 100), "arayuz": ["org.a11y.atspi.Text", "org.a11y.atspi.Action"],
                   "eylemler": ["activate"], "metin": DEGER}, **ekler}
    return _AgacYol(d, gecikme)


def _web(yol):
    b0, p0 = web._baglam, web._belge_pencereye_ait
    try:
        web._baglam = lambda k, islem="tara": (SimpleNamespace(baslik=lambda k: "Glama — Mozilla Firefox"), yol,
                                              ":1.5", "/c", 1, (0, 0), "kuresel")
        web._belge_pencereye_ait = lambda *a: None
        return web.duzenleme_alanlari("{g}")
    finally:
        web._baglam, web._belge_pencereye_ait = b0, p0


print("B2) web: yaprak rolün (link, button…) ve kapalı combo box'ın taşan çocuğu okunur")
ORTU = {"rol": "section", "kutu": (90, 90, 320, 120), "arayuz": ["org.a11y.atspi.Action"], "eylemler": ["click"]}
for ebeveyn, ek in (("link", {"eylemler": ["jump"]}), ("push button", {"eylemler": ["press"]}),
                    ("combo box", {"durum": ("showing", "visible")})):
    yol = _sahne({"/ebe": {"rol": ebeveyn, "ad": "x", "cocuk": ["/ortu"], "kutu": (900, 800, 10, 10),
                           "arayuz": ["org.a11y.atspi.Action"], **ek}, "/ortu": ORTU}, ["/alan", "/ebe"])
    durum: dict = {}
    ham, _b, _s = web._yuru(yol, ":1.5", "/c", 1, (0, 0), web._TUM_ROLLER, False, durum=durum)
    kontrol(f"B2 _yuru(_TUM_ROLLER): {ebeveyn} çocuğu okunur", "/ortu" in [o["_yol"] for o in ham],
            f"{[o['_yol'] for o in ham]} kesik={durum.get('kesik')}")
    s = _web(yol)
    kalan, cikan = ay([PAY], *s) if s else ([PAY], [])
    kontrol(f"B2 PoC-2: {ebeveyn} altındaki taşan örtü → satır kalır", kalan == [PAY] and not cikan, f"{s} {cikan}")
yol = _sahne({"/ebe": {"rol": "link", "ad": "x", "cocuk": ["/ortu"], "kutu": (900, 800, 10, 10)}, "/ortu": ORTU},
             ["/alan", "/ebe"])
ham, _b, _s = web._yuru(yol, ":1.5", "/c", 1, (0, 0), set(web.ETKILESIMLI), True)
kontrol("B2 olağan tarama (rol süzgeçli) yaprak budaması sürer", "/ortu" not in [o["_yol"] for o in ham],
        str([o["_yol"] for o in ham]))
d2c = _sahne({"/ortu": {**ORTU, "eylemler": ["clickAncestor"]}}, ["/alan", "/ortu"])
s = _web(d2c)
kalan, cikan = ay([PAY], *s) if s else ([PAY], [])
kontrol("B4 PoC-2c: 'clickAncestor' örtü kap değil → satır kalır", kalan == [PAY] and not cikan, f"{s} {cikan}")

print("B3) web: hassas bağlam taraması süre sınırlı")
import time  # noqa: E402

_eski_sure = erisim.DUZENLEME_SURE
erisim.DUZENLEME_SURE = 0.2  # web yolu da erisim.DUZENLEME_SURE sınırını kullanır
try:
    t0 = time.monotonic()
    s = _web(_sahne({}, ["/alan"], gecikme=0.25))
finally:
    erisim.DUZENLEME_SURE = _eski_sure
gecen = time.monotonic() - t0
kontrol("B3 süre sınırı aşılınca → None (çağıran ayıklamaz)", s is None, f"sonuç={s} {gecen:.2f} sn")
kontrol("B3 sınır aşılınca tarama hemen biter", gecen < 1.5, f"{gecen:.2f} sn")

print(f"\n{GECEN}/{TOPLAM} hassas-sonkapı testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
