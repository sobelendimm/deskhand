"""Hassas düğme bağlamı, K2 inceleme turu (INCELEME-HASSAS O1/O2/D1): düzenleme alanı içeriği YALNIZ kanıtla ayıklanır.

O1  ağaç kesilmesi (süre / öge sınırı / çocuk sınırı / okunamayan dal / düğüm sınırı) → kanıt yok → None (eski davranış).
O2  alanı kapsayan öge, tıklanmadığı KANITLANMADIKÇA kap sayılmaz (SONKAPI: sayfa düzeyi istisnası yok); satırdaki hassas sözcük
    alanın kendi DEĞERİNDE olmalı (alanın üstüne/altına boyanmış "Pay" yazısı içerik değildir).
D1  alanın erişilebilir adı hassassa ya da alanın kendi tıklama eylemi varsa alan sayılmaz.

Ekransız: sahte AT-SPI nesneleri ve sahte D-Bus yolu; gerçek ekrana/veri yoluna dokunulmaz.
Çalıştır:  python3 tests/test_hassas_kanit.py"""
import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

import sys
from types import SimpleNamespace

from deskhand import erisim, guvenlik, ocr, web
from deskhand.arka_uc import EKRAN

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


def satir(t, x, y, x2, y2):
    return ocr.NoktaYazisi(t, (x, y, x2, y2))


ay = guvenlik.duzenleme_icerigini_ayikla
TA = (100, 100, 300, 100)
DEGER = "Release notes: Buy/Pay buttons now ask first"
PAY = satir("Buy/Pay buttons now ask first", 110, 150, 380, 168)
TA_D = (*TA, DEGER)  # alan kutusu + alanın değeri

# ---------------------------------------------------------------- O2 / değer kanıtı (saf karar)
print("O2) kap ve değer kanıtı (saf karar)")
kalan, cikan = ay([PAY], [TA_D], [], [], [(0, 0, 1200, 900)])
kontrol("kanıtlı kap + değerde 'pay' → ayıklanır", cikan == [PAY], f"{kalan} {cikan}")
kalan, cikan = ay([PAY], [TA_D], [(90, 90, 320, 120)], [])
kontrol("1b: kapsayan ama tıklanmadığı kanıtlanmamış öge (digerleri) → kalır", kalan == [PAY] and not cikan)
kalan, cikan = ay([PAY], [TA_D], [TA], [])
kontrol("1c: alanla aynı boyda kanıtsız öge (digerleri) → kalır", kalan == [PAY] and not cikan)
kalan, cikan = ay([PAY], [TA], [], [], [(0, 0, 1200, 900)])
kontrol("alanın değeri bilinmiyor → kalır (kanıt yok)", kalan == [PAY] and not cikan)
kalan, cikan = ay([PAY], [(*TA, "Release notes: buttons now ask first")], [], [], [(0, 0, 1200, 900)])
kontrol("hassas sözcük alanın değerinde yok (alana boyanmış yazı) → kalır", kalan == [PAY] and not cikan)
# yeniden yazıldı (SONKAPI A3): bağlamsız tek "Pay now" satırı artık kanıt değil (P6); satır bağlamıyla verilir
kalan, cikan = ay([satir("you can pay now, or", 110, 150, 300, 168)], [(*TA, "Notes:\nyou can pay now, or later")], [],
                  [], [(0, 0, 1200, 900)])
kontrol("değerde aynı hassas sözcük bağlamıyla var → ayıklanır", len(cikan) == 1)
kalan, cikan = ay([satir("Pay now", 110, 150, 200, 168)], [(*TA, "Pay attention")], [], [], [(0, 0, 1200, 900)])
kontrol("satırdaki hassas ifade (pay now) değerde yok (yalnız pay) → kalır", len(kalan) == 1 and not cikan, f"{kalan} {cikan}")
kalan, cikan = ay([PAY], [TA_D], [], [], [(105, 105, 200, 90)])
kontrol("kap alanı kapsamıyor (alanın içinde, satıra değiyor) → kalır", kalan == [PAY] and not cikan)
kalan, cikan = ay([satir("Paste", 110, 150, 160, 168)], [(*TA, "notes")], [], [], [(0, 0, 1200, 900)])
kontrol("yapıştırma satırı değerde yok → kalır", len(kalan) == 1 and not cikan)

t = guvenlik.tiklanir_mi
kontrol("tiklanir_mi: bilinmiyor (None) → tıklanır sayılır", t(None) is True)
kontrol("tiklanir_mi: eylemsiz → tıklanmaz", t([]) is False)
kontrol("tiklanir_mi: click → tıklanır", t(["click"]) is True)
kontrol("tiklanir_mi: adı boş eylem → tıklanır (bilinmiyor)", t([""]) is True)
# ters döndü (SONKAPI): eski beklenti P1/B4 açığını kilitliyordu (atanın tıklaması abs çocukla alanı örtebilir)
kontrol("tiklanir_mi: 'click ancestor' / 'clickAncestor' (üst ögenin) → tıklanır sayılır",
        t(["click ancestor"]) is True and t(["clickAncestor"]) is True)
kontrol("tiklanir_mi: SetFocus → tıklanmaz", t(["SetFocus"]) is False)
kontrol("tiklanir_mi: activate kap için tıklanır, alan için olağan", t(["activate"]) is True
        and t(["activate"], alan=True) is False)

kap = guvenlik.duzenleme_kabi_mi
kontrol("kap: eylemsiz ve alanı kapsıyor → kap", kap((90, 90, 320, 120), [], [TA]) is True)
kontrol("kap: tıklanır ve alanı sarıyor → kap DEĞİL",
        kap((90, 90, 320, 120), ["click"], [TA]) is False)
kontrol("kap: eylemleri okunamadı → kap DEĞİL", kap((90, 90, 320, 120), None, [TA]) is False)
# ters döndü (SONKAPI): eski beklenti P1/B4 açığını kilitliyordu (tam ekran onclick sarmalayıcı = React kökü)
kontrol("kap: tıklanır ve görüş alanının tamamını kapsıyor → kap DEĞİL",
        kap((0, 0, 1200, 3000), ["click"], [TA]) is False)
kontrol("kap: alanı kapsamıyor → kap DEĞİL", kap((105, 105, 200, 90), [], [TA]) is False)

a = guvenlik.alan_kanitli_mi
kontrol("D1: alan adı 'Pay now' → alan sayılmaz", a("Pay now", ["activate"]) is False)
kontrol("D1: alanın kendi 'click' eylemi → alan sayılmaz", a("Notes", ["activate", "click"]) is False)
kontrol("D1: eylemleri okunamadı → alan sayılmaz", a("Notes", None) is False)
kontrol("D1: olağan alan (activate) → alan", a("Description", ["activate"]) is True)

# ---------------------------------------------------------------- O1: erisim._tara kesilme bayrağı
print("O1) erisim._tara kesilme")


class _Durum:
    def contains(self, _s):
        return True


class _Oge:
    def __init__(self, kutu, cocuklar=(), rol="panel", ad="", eylemler=None, cocuk_patlar=False):
        self.kutu, self.cocuklar, self.rol, self.ad = kutu, list(cocuklar), rol, ad
        self.eylemler, self.cocuk_patlar = eylemler, cocuk_patlar

    def get_extents(self, _tur):
        return SimpleNamespace(x=self.kutu[0], y=self.kutu[1], width=self.kutu[2], height=self.kutu[3])

    def get_state_set(self):
        return _Durum()

    def get_role_name(self):
        return self.rol

    def get_name(self):
        return self.ad

    def get_child_count(self):
        return len(self.cocuklar)

    def get_child_at_index(self, i):
        if self.cocuk_patlar:
            raise RuntimeError("defunct")
        return self.cocuklar[i]

    def get_action_iface(self):
        if self.eylemler is None:
            return None
        e = self.eylemler
        return SimpleNamespace(get_n_actions=lambda: len(e), get_action_name=lambda i: e[i])


_Atspi = SimpleNamespace(CoordType=SimpleNamespace(WINDOW=1), StateType=SimpleNamespace(SHOWING=1, SENSITIVE=2))


def _agac(n=5, **kw):
    return _Oge((0, 0, 700, 460), [_Oge((10 + 20 * i, 10, 15, 15), rol="push button", ad=f"B{i}") for i in range(n)],
                rol="frame", **kw)


def _tara(kok, en_cok=100, sure=5.0, cocuk_siniri=100, **kw):
    return erisim._tara(_Atspi, kok, (0, 0, 700, 460), en_cok, sure, cocuk_siniri, **kw)


r = _tara(_agac())
kontrol("_tara: tam tarama → kesik False", r.get("kesik") is False and len(r["ogeler"]) == 5, str(r.get("kesik")))
kontrol("_tara: öge sınırı dolunca → kesik True", _tara(_agac(), en_cok=3).get("kesik") is True)
kontrol("_tara: süre dolunca → kesik True", _tara(_agac(), sure=0.0).get("kesik") is True)
kontrol("_tara: çocuk sınırı kesti → kesik True", _tara(_agac(), cocuk_siniri=2).get("kesik") is True)
kontrol("_tara: çocuk okunamadı → kesik True", _tara(_agac(cocuk_patlar=True)).get("kesik") is True)
kap_oge = _Oge((0, 0, 700, 460), [_Oge((10, 10, 100, 50), rol="panel", eylemler=["click"])], rol="frame")
r = _tara(kap_oge, ayrinti=True, eylem_hepsi=True)
kontrol("_tara: eylem_hepsi → etkileşimsiz ögenin de eylemleri okunur",
        r["ogeler"] and r["ogeler"][0].get("eylemler") == ["click"], str(r["ogeler"]))
r = _tara(kap_oge, ayrinti=True)
kontrol("_tara: eylem_hepsi yokken etkileşimsiz ögenin eylemleri okunmaz (observe çıktısı değişmez)",
        r["ogeler"] and "eylemler" not in r["ogeler"][0], str(r["ogeler"]))

_eski_ac = (erisim.erisim_ac_garanti, erisim._atspi_calistir, erisim._pencere_istegi, erisim.sec)
try:
    YANIT: dict = {}
    erisim.erisim_ac_garanti = lambda: False
    erisim._atspi_calistir = lambda istek: dict(YANIT)
    erisim._pencere_istegi = lambda k, islem, **ek: {"islem": islem, **ek}
    erisim.sec = lambda *a: SimpleNamespace(geometri=lambda k: (0, 0, 700, 460), masaustu_olcegi=lambda: 1)
    YANIT.update(ogeler=[], sure=0.1)
    kontrol("erisim_ogeleri_kesik: bayrağı bildirmeyen yanıt → kesik True (kapalı-başarısız)",
            erisim.erisim_ogeleri_kesik("{g}")[2] is True)
    YANIT.update(kesik=False)
    kontrol("erisim_ogeleri_kesik: kesik False iletilir", erisim.erisim_ogeleri_kesik("{g}")[2] is False)
    kontrol("erisim_ogeleri: listeleme çağıranları için hep 2 öge", len(erisim.erisim_ogeleri("{g}")) == 2)
finally:
    erisim.erisim_ac_garanti, erisim._atspi_calistir, erisim._pencere_istegi, erisim.sec = _eski_ac

# ---------------------------------------------------------------- erisim.duzenleme_alanlari (masaüstü uygulaması)
print("O1/O2/D1) erisim.duzenleme_alanlari")
from deskhand import dogrulama_sinamasi  # noqa: E402

_t, _eo = dogrulama_sinamasi.tarayici_mi, erisim.erisim_ogeleri_kesik
ALAN_O = {"rol": "text", "ad": "Notes", "x": 100, "y": 100, "w": 300, "h": 100, "durumlar": [], "eylemler": [],
          "deger": DEGER}


SON_KW: dict = {}


def _sahte_ogeler(ogeler, kesik=False):
    def f(k, **kw):
        SON_KW.clear()
        SON_KW.update(kw)
        return ogeler, 0.1, kesik
    return f


try:
    dogrulama_sinamasi.tarayici_mi = lambda k: False
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([ALAN_O], kesik=True)
    kontrol("O1 erisim: ağaç kesik → None", erisim.duzenleme_alanlari("{g}") is None)
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([ALAN_O])
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("erisim: kesik değil → alan + değer; eylemler hepsi için istenir",
            r is not None and r[0] == [(100, 100, 300, 100, DEGER)]
            and SON_KW.get("eylem_hepsi") is True, str(r))
    sar = {"rol": "panel", "ad": "", "x": 90, "y": 90, "w": 320, "h": 120, "durumlar": []}
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([ALAN_O, {**sar, "eylemler": ["click"]}])
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("O2 erisim: alanı saran tıklanır panel → kap değil (digerleri)",
            r is not None and (90, 90, 320, 120) in r[1] and (90, 90, 320, 120) not in r[3], str(r))
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([ALAN_O, sar])
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("O2 erisim: saran panelin eylemleri bilinmiyor → kap değil",
            r is not None and (90, 90, 320, 120) in r[1], str(r))
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([ALAN_O, {**sar, "eylemler": []}])
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("O2 erisim: saran panel eylemsiz → kap", r is not None and r[3] == [(90, 90, 320, 120)], str(r))
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([{**ALAN_O, "ad": "Pay now"}])
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("D1 erisim: alan adı 'Pay now' → alan değil, dugmeler",
            r is not None and r[0] == [] and (100, 100, 300, 100) in r[2], str(r))
    erisim.erisim_ogeleri_kesik = _sahte_ogeler([{**ALAN_O, "eylemler": ["click"]}])
    r = erisim.duzenleme_alanlari("{g}")
    kontrol("D1 erisim: alanın kendi tıklama eylemi → alan değil", r is not None and r[0] == [], str(r))
    kontrol("erisim: masaüstü kipi → None", erisim.duzenleme_alanlari(EKRAN) is None)
finally:
    dogrulama_sinamasi.tarayici_mi, erisim.erisim_ogeleri_kesik = _t, _eo

# ---------------------------------------------------------------- O1: web._yuru kesilme bayrağı (sahte D-Bus)
print("O1) web._yuru kesilme")


class _AgacYol:
    """Sahte erişilebilirlik yolu: düğüm yolu → (rol, ad, durumlar, kutu, çocuklar, arayüzler, eylemler, metin)."""

    def __init__(self, dugumler, bozuk=()):
        self.d, self.bozuk = dugumler, set(bozuk)

    def _yanit(self, m):
        from jeepney.low_level import HeaderFields
        f = m.header.fields
        uye, yol = f.get(HeaderFields.member), f.get(HeaderFields.path)
        n = self.d.get(yol)
        if n is None or (yol, uye) in self.bozuk:
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
        return [self._yanit(m) for m in mesajlar]

    def kapat(self):
        pass


def _sayfa(n_dugme=3, ic_ice=False):
    """ic_ice: her düğme kendi bölümünün (section) içinde — bir seviye daha derin."""
    kap = [f"/s{i}" for i in range(n_dugme)] if ic_ice else [f"/b{i}" for i in range(n_dugme)]
    d = {"/c": {"rol": "frame", "cocuk": ["/doc"], "kutu": (0, 0, 1200, 900)},
         "/doc": {"rol": "document web", "ad": "Glama", "cocuk": kap, "kutu": (0, 0, 1200, 900)}}
    for i in range(n_dugme):
        d[f"/b{i}"] = {"rol": "push button", "ad": f"B{i}", "kutu": (10 + 30 * i, 10, 20, 20)}
        if ic_ice:
            d[f"/s{i}"] = {"rol": "section", "cocuk": [f"/b{i}"], "kutu": (10 + 30 * i, 10, 20, 20)}
    return d


def _yuru(yol, **kw):
    durum = {}
    ham, _b, _s = web._yuru(yol, ":1.5", "/c", 1, (0, 0), set(web.ETKILESIMLI), True, durum=durum, **kw)
    return ham, durum


ham, durum = _yuru(_AgacYol(_sayfa()))
kontrol("_yuru: tam tarama → kesik yok", not durum.get("kesik") and len(ham) == 3, f"{durum} {len(ham)}")
ham, durum = _yuru(_AgacYol(_sayfa(40, ic_ice=True)), en_cok_dugum=5)
kontrol("_yuru: düğüm sınırı doldu → kesik", durum.get("kesik") is True, str(durum))
ham, durum = _yuru(_AgacYol(_sayfa(), bozuk={("/doc", "GetChildren")}))
kontrol("_yuru: belgenin çocukları okunamadı → kesik", durum.get("kesik") is True, str(durum))
ham, durum = _yuru(_AgacYol(_sayfa(), bozuk={("/b1", "GetRoleName")}))
kontrol("_yuru: düğümün rolü okunamadı → kesik", durum.get("kesik") is True, str(durum))
ham, durum = _yuru(_AgacYol(_sayfa(), bozuk={("/b1", "GetExtents")}))
kontrol("_yuru: istenen ögenin kutusu okunamadı → kesik", durum.get("kesik") is True, str(durum))
d = _sayfa()
d["/b0"]["kutu"] = (-30, 120, 80, 30)  # sola taşan düğme: görünen kısmı alana değebilir
ham, durum = _yuru(_AgacYol(d))
b0 = next(o for o in ham if o["ad"] == "B0")
kontrol("_yuru: negatif konumlu ögenin ham kutusu saklanır (_hkutu)", b0.get("_hkutu") == (-30, 120, 80, 30),
        str(b0.get("_hkutu")))

# ---------------------------------------------------------------- web.duzenleme_alanlari
print("O1/O2/D1) web.duzenleme_alanlari")
AU = SimpleNamespace(baslik=lambda k: "Profile | Glama — Mozilla Firefox")
_eski_web = (web._baglam, web._yuru)


def _web_sahne(ekler, alan_ek=None, kesik=False):
    alan = {"rol": "entry", "ad": "Description", "durum": ("editable", "showing", "visible", "multi_line"),
            "kutu": (100, 100, 300, 100), "arayuz": ["org.a11y.atspi.Accessible", "org.a11y.atspi.Text",
                                                    "org.a11y.atspi.Action"],
            "eylemler": ["activate"], "metin": DEGER, **(alan_ek or {})}
    d = {"/alan": alan, **ekler}
    yol = _AgacYol(d)
    ham = []
    for y, n in d.items():
        k_: tuple = tuple(n.get("kutu") or ())
        ham.append({"_yol": y, "_anahtar": (len(ham),), "_alan": (0, 0, 1200, 900), "_d": set(n.get("durum", (
            "showing", "visible"))), "_kutu": k_ if k_ and min(k_[:2]) > -1 else None, "_hkutu": k_ or None,
            "_derin": 1, "_adres": "", "rol": n["rol"], "ad": n.get("ad", "")})
    web._baglam = lambda k, islem="tara": (AU, yol, ":1.5", "/c", 0, (0, 0), "kuresel_cerceve")

    def sahte_yuru(*a, durum=None, **kw):
        if durum is not None and kesik:
            durum["kesik"] = True
        return ham, [{"ad": "Profile | Glama", "adres": "", "durum": set(), "derinlik": 1,
                      "kutu": (0, 0, 1200, 900)}], 10
    web._yuru = sahte_yuru
    return web.duzenleme_alanlari("{g}")


try:
    r = _web_sahne({})
    kontrol("web: alan + değer okunur", r is not None and r[0] == [(100, 100, 300, 100, DEGER)], str(r))
    kontrol("O1 web: _yuru kesik bildirdi → None", _web_sahne({}, kesik=True) is None)
    sar = {"rol": "section", "kutu": (90, 90, 320, 120), "arayuz": ["org.a11y.atspi.Action"], "eylemler": ["click"]}
    r = _web_sahne({"/sar": sar})
    kontrol("O2 web: alanı saran tıklanır div → kap değil (digerleri)",
            r is not None and (90, 90, 320, 120) in r[1] and (90, 90, 320, 120) not in r[3], str(r))
    r = _web_sahne({"/sar": {**sar, "eylemler": ["click ancestor"]}})
    # ters döndü (SONKAPI): eski beklenti P1/B4 açığını kilitliyordu (atanın tıklaması: abs çocuk alanı örtebilir)
    kontrol("web: yalnız üst ögenin tıklaması ('click ancestor') → kap değil (digerleri)", r is not None
            and r[3] == [] and (90, 90, 320, 120) in r[1], str(r))
    r = _web_sahne({"/sar": {"rol": "section", "kutu": (90, 90, 320, 120)}})
    kontrol("web: Action arayüzü olmayan saran div → kap", r is not None and r[3] == [(90, 90, 320, 120)], str(r))
    r = _web_sahne({"/kok": {"rol": "section", "kutu": (0, 0, 1200, 2400), "arayuz": ["org.a11y.atspi.Action"],
                             "eylemler": ["click"]}})
    # ters döndü (SONKAPI): eski beklenti P1/B4 açığını kilitliyordu (tam ekran onclick sarmalayıcı = React kökü)
    kontrol("web: görüş alanını kapsayan tıklanır kök → kap değil (digerleri)", r is not None
            and r[3] == [] and (0, 0, 1200, 2400) in r[1], str(r))
    r = _web_sahne({"/es": {"rol": "canvas", "kutu": (100, 100, 300, 100), "arayuz": ["org.a11y.atspi.Action"],
                            "eylemler": ["click"]}})
    kontrol("O2 web: listede olmayan rol (canvas) üst örtü, tıklanır → digerleri", r is not None
            and (100, 100, 300, 100) in r[1], str(r))
    r = _web_sahne({"/b": {"rol": "push button", "ad": "Pay", "kutu": (-20, 150, 140, 30)}})
    kontrol("web: negatif konumlu düğme ham kutusuyla dugmeler'de", r is not None and (-20, 150, 140, 30) in r[2], str(r))
    r = _web_sahne({}, alan_ek={"ad": "Pay now"})
    kontrol("D1 web: alan adı 'Pay now' → alan değil, dugmeler", r is not None and r[0] == []
            and (100, 100, 300, 100) in r[2], str(r))
    r = _web_sahne({}, alan_ek={"eylemler": ["click"]})
    kontrol("D1 web: alanın kendi 'click' eylemi → alan değil", r is not None and r[0] == [], str(r))
    r = _web_sahne({}, alan_ek={"arayuz": ["org.a11y.atspi.Text"]})
    kontrol("web: Action arayüzü olmayan alan (eylemsiz) → alan", r is not None and len(r[0]) == 1, str(r))
    r = _web_sahne({}, alan_ek={"ad": "One-time code"})
    kontrol("web: gizli alan (OTP) değeri okunmaz → değer None", r is not None and r[0] == [(100, 100, 300, 100, None)],
            str(r))
finally:
    web._baglam, web._yuru = _eski_web

print(f"\n{GECEN}/{TOPLAM} hassas-kanıt testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
