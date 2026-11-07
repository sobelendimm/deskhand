#!/usr/bin/python3
"""deskhand OCR gerileme testi: ekran/pencere GEREKMEZ (kayıtlı örnek görüntüler). ~5 sn.
Ön işlem, dil, büyütme ya da tesseract ayarı değişince ÇALIŞTIR: Türkçe harfler birebir okunmalı.

Çalıştır:  python3 tests/test_ocr.py"""
import os
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from PIL import Image

from deskhand import ocr as m
ORNEK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ornek")

# görüntü → OCR metninde BİREBİR (Türkçe harfler dahil) geçmesi gereken ifadeler
BEKLENEN = {
    "ornek-degirmendere.png": ["Değirmendere", "dağ köyüdür", "Güneyindeki geçit"],
    "vikipedi-kapadokya.png": ["Kapadokya", "Türkiye'nin İç Anadolu Bölgesi'nde"],
    "vikipedi-goreme.png": ["Göreme", "Nevşehir"],
    "vikipedi-sanliurfa.png": ["Şanlıurfa"],
    "vikipedi-metin.png": ["Edessa"],
    "web-test-acik.png": ["Durum: Hazır", "Kaydet", "İptal", "Şifreyi sıfırla", "Çift tıkla beni", "Satın al",
                          "E-posta:", "Not alanı:"],
}
# arama (ara): Türkçe harfsiz/küçük harfli sorgu da bulunmalı
ARAMA = {"web-test-acik.png": ["iptal", "sifreyi sifirla", "satin al"], "ornek-degirmendere.png": ["degirmendere", "guneyindeki gecit"]}


def tam_ekran_testi(kontrol):
    """Gerçek ekran testinde bulunan hata: içerik büyük tek renkli zeminin köşesindeyken (tam ekran pencere)
    OCR hiçbir şey bulamıyordu. Örnek görüntü 2560x1440 koyu ve açık zeminlerin içine konur; yazılar bulunmalı ve
    koordinatlar görüntünün yerine göre kaymalı."""
    kaynak = Image.open(os.path.join(ORNEK, "web-test-acik.png")).convert("RGB")
    temel = {}
    for s in m.satirla(m.oku(kaynak)):
        for w in s["kelimeler"]:
            temel.setdefault(w["t"], (w["x"], w["y"]))
    for ad, renk, (ox, oy) in (("koyu", (32, 35, 38), (0, 0)), ("açık", (250, 250, 250), (900, 500))):
        tuval = Image.new("RGB", (2560, 1440), renk)
        tuval.paste(kaynak, (ox, oy))
        sat = m.satirla(m.oku(tuval))
        bulunan = {w["t"]: (w["x"], w["y"]) for s_ in sat for w in s_["kelimeler"]}
        ms = m.ara(sat, "Kaydet")
        kontrol(f"tam ekran ({ad} zemin): 'Kaydet' bulunur", bool(ms), f"{len(bulunan)} kelime")
        if ms and "Kaydet" in temel and "Kaydet" in bulunan:
            dx = bulunan["Kaydet"][0] - temel["Kaydet"][0] - ox
            dy = bulunan["Kaydet"][1] - temel["Kaydet"][1] - oy
            kontrol(f"tam ekran ({ad} zemin): koordinat doğru kaydırıldı", abs(dx) <= 3 and abs(dy) <= 3, f"{dx},{dy}")


def main():
    sonuc = []
    t0 = time.monotonic()
    for dosya, ifadeler in BEKLENEN.items():
        im = Image.open(os.path.join(ORNEK, dosya)).convert("RGB")
        satirlar = m.satirla(m.oku_tesseract(im))
        # araç arama/denetimde çizgisiz yedek okumayı da kullanır: ikisinin birleşimi
        satirlar_c = m.satirla(m.oku_tesseract(im, cizgisiz=True))
        metin = "\n".join(s["t"] for s in satirlar + satirlar_c)
        for ifade in ifadeler:
            ok = ifade in metin
            sonuc.append(ok)
            print(f"{'GEÇTİ ' if ok else 'KALDI!'} {dosya}: {ifade!r}")
        for sorgu in ARAMA.get(dosya, []):
            ok = bool(m.ara(satirlar, sorgu) or m.ara(satirlar_c, sorgu))
            sonuc.append(ok)
            print(f"{'GEÇTİ ' if ok else 'KALDI!'} {dosya}: ara({sorgu!r})")
    # Yakın önbellek eşleşmesi: imleç çizgisi = aynı; tek rakam/harf değişikliği = FARKLI (eski metin dönmemeli)
    from PIL import ImageDraw, ImageFont
    font = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 15) if os.path.exists("/usr/share/fonts/noto/NotoSans-Regular.ttf") else ImageFont.load_default()

    def resim(metin, imlec=False):
        r = Image.new("RGB", (240, 40), "white")
        d = ImageDraw.Draw(r)
        d.text((10, 10), metin, fill="black", font=font)
        if imlec:
            d.line([(150, 8), (150, 30)], fill="black", width=1)
        return m._kucuk_gri(r)
    durumlar = [("imleç yanıp söndü → aynı", resim("Makineleşme %16"), resim("Makineleşme %16", True), True),
                ("%16 → %17 → FARKLI", resim("Makineleşme %16"), resim("Makineleşme %17"), False),
                ("%16 → %18 → FARKLI", resim("Makineleşme %16"), resim("Makineleşme %18"), False),
                ("harf eklendi (abc → abcd) → FARKLI", resim("abc"), resim("abcd"), False),
                ("nokta eklendi (Hazır → Hazır.) → FARKLI değilse kabul", resim("Durum: Hazır"), resim("Durum: Hazır."), None)]
    for ad, a_, b_, beklenen in durumlar:
        sonuc_ = m._imlec_farki(a_, b_)
        if beklenen is None:
            print(f"BİLGİ  önbellek yakınlık: {ad}: {'aynı sayıldı' if sonuc_ else 'farklı sayıldı'}")
            continue
        ok = sonuc_ == beklenen
        sonuc.append(ok)
        print(f"{'GEÇTİ ' if ok else 'KALDI!'} önbellek yakınlık: {ad}")

    def kontrol(ad, ok, ayrinti=""):
        sonuc.append(bool(ok))
        print(f"{'GEÇTİ ' if ok else 'KALDI!'} {ad}" + (f"  [{ayrinti}]" if ayrinti else ""))
    tam_ekran_testi(kontrol)
    print(f"\n{sum(sonuc)}/{len(sonuc)} OCR testi geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if all(sonuc) else 1)


if __name__ == "__main__":
    main()
