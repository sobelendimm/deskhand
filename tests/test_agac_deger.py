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
