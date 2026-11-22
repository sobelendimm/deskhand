"""read_text(source="tree") (api.agac_oku): yazılan metin ögenin ADINDA değil DEĞERİNDE (AT-SPI Text arayüzü).
KWrite'ın editör ögesi: rol "text", ad = dosya adı, değer = yazılan metin → ağaç çıktısı `value` alanını taşır, sorgu
değerde de aranır, parola alanının değeri okunmaz.

A) birim: erisim.erisim_ogeleri sahte (ekransız). B) GÖRÜNMEZ masaüstünde (DESKHAND_ARKA_TUR=kwin|xvfb) gerçek KWrite:
geçici .txt dosyası, klavye yazısı, read_text'in ağaç yolu metni DEĞER olarak döndürür. Her api çağrısı
`api.hedef("sanal")` içinde ve başta hedef denetlenir (kullanıcının ekranına HİÇBİR girdi gitmez).

Çalıştır:  python3 tests/test_agac_deger.py"""
import atexit
import os
import shutil
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import api, erisim, masaustu
from deskhand.arka_uc import sec

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


# ---------------------------------------------------------------- A) birim (sahte ağaç)
def oge(rol, ad, deger=None, no=0):
    o = {"rol": rol, "ad": ad, "etkin": True, "x": 1, "y": 2, "w": 30, "h": 10, "cx": 16, "cy": 7, "yol": [no],
         "durumlar": []}
    if deger is not None:
        o["deger"] = deger
    return o


SAHTE = [oge("text", "not.txt", "merhaba dunya", 1), oge("entry", "Ad", "Çağrı", 2), oge("label", "Ad", None, 3),
         oge("button", "Kaydet", None, 4), oge("password text", "Parola", None, 5)]
gercek = erisim.erisim_ogeleri
erisim.erisim_ogeleri = lambda k, *a, **kw: (SAHTE, 0.01)
gercek_yasak = api.yasak_mi
api.yasak_mi = lambda k: False
try:
    r = api.agac_oku("{w}", None, hepsi=True)
    deger = {i["text"] + "/" + i["role"]: i.get("value") for i in r["items"]}
    kontrol("birim: editör (text) ve giriş değeri `value` ile döner",
            deger["not.txt/text"] == "merhaba dunya" and deger["Ad/entry"] == "Çağrı", str(deger))
    kontrol("birim: değersiz öge (düğme, etiket) `value` taşımaz; parola alanı değer yok",
            "value" not in next(i for i in r["items"] if i["role"] == "button") and
            "value" not in next(i for i in r["items"] if i["role"] == "password text"))
    r = api.agac_oku("{w}", "merhaba")
    kontrol("birim: sorgu değerde de aranır (ad dosya adı olan editör)",
            [i["text"] for i in r["items"]] == ["not.txt"] and r["items"][0]["value"] == "merhaba dunya", str(r))
    r = api.agac_oku("{w}", "Kaydet")
    kontrol("birim: ad sorgusu eskisi gibi", [i["text"] for i in r["items"]] == ["Kaydet"])
finally:
    erisim.erisim_ogeleri = gercek
    api.yasak_mi = gercek_yasak

# ---------------------------------------------------------------- A2) değer maskesi (erisim._ayrinti: observe + read_text ortak)
import types  # noqa: E402


class SahteMetin:
    def __init__(self, metin):
        self.metin = metin


class SahteAtspi:
    class Text:
        @staticmethod
        def get_text(ti, bas, son):
            return ti.metin[:son]


class SahteOge:
    def __init__(self, deger, ad="", aciklama="", nitelik=None):
        self._d, self._ad, self._ac, self._n = deger, ad, aciklama, nitelik or {}

    def get_text_iface(self):
        return SahteMetin(self._d)

    def get_name(self):
        return self._ad

    def get_description(self):
        return self._ac

    def get_attributes(self):
        return self._n

    def get_value_iface(self):
        return None


def _deger(deger, rol="entry", **kw):
    ss = types.SimpleNamespace(contains=lambda _x: False)
    return erisim._ayrinti(SahteAtspi, SahteOge(deger, **kw), rol, ss, types.SimpleNamespace()).get("deger")


kontrol("maske: sıradan alan değeri aynen", _deger("merhaba", ad="Ad") == "merhaba")
kontrol("maske: ad 'Parola'/'Şifre'/'Sifre'/'PIN'/'OTP'/'CVV'/'CVC'/'Güvenlik kodu' → ***",
        all(_deger("abc123", ad=a) == "***" for a in ("Parola", "Şifre", "SİFRE", "Password", "PIN", "Pin kodu", "OTP",
                                                       "CVV", "CVC2", "Güvenlik Kodu", "Passcode")))
kontrol("maske: kart alanı (kart numarası, son kullanma, cc-number) → ***",
        all(_deger("4111", ad=a) == "***" for a in ("Kart Numarası", "Son kullanma tarihi", "Card number", "CVC")))
kontrol("maske: açıklama ya da nitelik (autocomplete/id/placeholder) gizli alanı gösteriyorsa → ***",
        _deger("x", ad="Alan", aciklama="Yeni parolanız") == "***" and
        _deger("x", ad="Alan", nitelik={"autocomplete": "one-time-code otp"}) == "***" and
        _deger("x", ad="Alan", nitelik={"autocomplete": "cc-number"}) == "***" and
        _deger("x", ad="Alan", nitelik={"id": "login-password"}) == "***" and
        _deger("x", ad="Alan", nitelik={"placeholder": "Şifrenizi girin"}) == "***" and
        _deger("x", ad="Alan", nitelik={"text-input-type": "password"}) == "***")
kontrol("maske: kısa kısaltmalar kelime sınırlı (spin/shipping/hotpot maskelenmez)",
        all(_deger("v", ad=a) == "v" for a in ("Spinner", "Shipping address", "Hotpot", "Optional note", "Typing")))
kontrol("maske: yalnız •●* karakterlerinden oluşan değer atlanır (değer yok)",
        _deger("••••••", ad="Alan") is None and _deger("●●●", ad="Alan") is None and _deger("***", ad="Alan") is None
        and _deger("• • •", ad="Alan") is None)
kontrol("maske: maske karakteri + gerçek metin atlanmaz", _deger("a*b", ad="Alan") == "a*b")
kontrol("denetim karakterleri ayıklanır (NUL/ESC/RLO/sıfır genişlik); satır sonu/sekme boşluk",
        _deger("a\x00b\x1b[31mc\u202ed\u200be\n f\tg", ad="Alan") == "ab[31mcde  f g",
        repr(_deger("a\x00b\x1b[31mc\u202ed\u200be\n f\tg", ad="Alan")))
kontrol("yalnız denetim karakteri olan değer atlanır", _deger("\x00\x01\u200b", ad="Alan") is None)
kontrol("parola rolü değeri zaten okunmaz", _deger("gizli", rol="password text", ad="Alan") is None)
kontrol("maskelenen değer uzunluğu/ipucu sızdırmaz (sabit ***)",
        _deger("a" * 150, ad="Parola") == _deger("b", ad="Parola") == "***")

# ağaç yolu da aynı üretici: `deger` maskeli gelir (erisim_ogeleri çıktısına api.agac_oku dokunmaz)
SAHTE2 = [oge("entry", "Parola", "***", 1), oge("entry", "Ad", "x", 2)]
erisim.erisim_ogeleri = lambda k, *a, **kw: (SAHTE2, 0.01)
api.yasak_mi = lambda k: False
try:
    r = api.agac_oku("{w}", None, hepsi=True)
    kontrol("read_text(tree): maskeli değer *** olarak döner", [i.get("value") for i in r["items"]] == ["***", "x"])
    r = api.agac_oku("{w}", "gizli-metin")
    kontrol("read_text(tree): sorgu maskeli ham değeri aratmaz", r["items"] == [])
finally:
    erisim.erisim_ogeleri = gercek
    api.yasak_mi = gercek_yasak

# ---------------------------------------------------------------- B) gerçek KWrite (görünmez masaüstü)
if not (shutil.which("kwrite") and shutil.which("bwrap")):
    print("B) atlandı: kwrite ya da bwrap yok")
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(0 if gecen == toplam else 1)
tur = (os.environ.get("DESKHAND_ARKA_TUR") or "").strip().lower()
if tur == "xvfb" and not shutil.which("Xvfb"):
    print("B) atlandı: Xvfb yok")
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(0 if gecen == toplam else 1)
try:
    import gi  # noqa: F401
    gi.require_version("Atspi", "2.0")
except (ImportError, ValueError):
    print("B) atlandı: AT-SPI (gi) yok")
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(0 if gecen == toplam else 1)

print("\nB) görünmez masaüstünde KWrite")
d = masaustu.masaustu_baslat()
au = sec(arka_bayragi=True)
if au.ad != "sanal":  # GÜVENLİK: hedef görünmez masaüstü değilse hiçbir şey yapılmaz
    print(f"!!! hedef sanal değil ({au.ad}); durduruldu")
    masaustu.masaustu_durdur()
    sys.exit(2)
try:
    dosya = os.path.join(_yalitim.PAYLASIM, "deneme.txt")
    open(dosya, "w").close()
    log = open(os.path.join(_yalitim.PAYLASIM, "kwrite.log"), "w")
    once = {w for w, _b, _g in au.pencereler()}
    p = au.baslat(["kwrite", dosya], cikti=log)
    k = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30 and not k:
        for w, _b, _g in au.pencereler():
            if w not in once:
                k = w
        time.sleep(0.4)
    kontrol("KWrite penceresi arka:", bool(k) and k.startswith("arka:"), str(k))
    if k:
        yazi = "merhaba dunya Deskhand"
        with api.hedef("sanal"):
            assert api.arka().ad == "sanal"
            time.sleep(2)
            api.yaz(k, yazi)
            r = {}
            bitis = time.monotonic() + 8
            while time.monotonic() < bitis:
                r = api.agac_oku(k, None, hepsi=True, en_cok=300)
                if any(i.get("value") == yazi for i in r["items"]):
                    break
                time.sleep(0.5)
            kontrol("read_text(tree): editörün değeri yazılan metin", any(i.get("value") == yazi and i["role"] == "text"
                                                                          for i in r["items"]), str(r)[:300])
            r = api.agac_oku(k, "dunya Deskhand")
            kontrol("read_text(tree, query=metin): editör bulunur", any(i.get("value") == yazi for i in r["items"]),
                    str(r)[:300])
    p.terminate()
    try:
        p.wait(8)
    except Exception:  # noqa: BLE001
        p.kill()
finally:
    masaustu.masaustu_durdur()

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
