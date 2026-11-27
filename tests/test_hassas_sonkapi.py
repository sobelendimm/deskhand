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

print(f"\n{GECEN}/{TOPLAM} hassas-sonkapı testi geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
