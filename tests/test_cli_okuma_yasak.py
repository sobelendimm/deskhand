"""CLI okuma komutları yasak pencere listesine uyar (0.9.0): `foto`, `metin`, `bekle`, `simge-bul`, `simge-kaydet`,
`renk-bul` hedef yasaksa Dur 10 (hiçbir görüntü alınmaz/kaydedilmez); görüntüye düşen DİĞER yasak pencereler siyah
kutuyla örtülür (MCP yolu ile aynı: api.goruntu_al). Önceden bu komutlar gorsel.pencere_goruntusu'nu doğrudan
çağırıyor, yasak listeye hiç bakmıyordu.

EKRANSIZ: sahte arka uç (bellekte ekran görüntüsü); gerçek ekran/araç yok.
Çalıştır:  python3 tests/test_cli_okuma_yasak.py"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _yalitim  # noqa: F401,E402

from PIL import Image  # noqa: E402

from deskhand import api, gorsel, guvenlik, ocr  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ek=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


class SahteAU:
    """400x300 ekran, tamamı kırmızı. w1: sıradan pencere (0,0 200x150); w2: YASAK (100,50 100x100, w1'in üstünde);
    w3: YASAK hedef."""
    PEN = {"w1": ("Belge", "editor", (0, 0, 200, 150)),
           "w2": ("Gizli Kasa", "kasa", (100, 50, 100, 100)),
           "w3": ("Gizli Kasa 2", "kasa", (250, 200, 100, 80))}

    _api_sarili = True  # api.arka() girdi sarmalamasını atla (girdi yok)

    def __init__(self):
        self.on = "w1"
        self.goruntu_sayisi = 0

    def one_getir(self, k):
        self.on = k

    def aktif(self):
        return self.on

    def geometri(self, k):
        return self.PEN[k][2]

    def baslik(self, k):
        return self.PEN.get(k, ("",))[0]

    def sinif(self, k):
        return self.PEN.get(k, ("", ""))[1]

    def pencereler(self, desen=None):
        return [(k, v[0], v[2]) for k, v in self.PEN.items()]

    def ekran_alani(self):
        return (0, 0, 400, 300)

    def goruntu(self):
        self.goruntu_sayisi += 1
        return Image.new("RGB", (400, 300), (200, 0, 0))


au = SahteAU()
for m in (api, gorsel, guvenlik):
    m.sec = lambda *a, **k: au
guvenlik._kullanici_yasaklari = lambda: [r"^Gizli Kasa"]


def ns(**k):
    v = dict(kimlik="w3", bolge=None, cikti=None, genislik=None, izgara=None, ad="simge", esik=0.9, renk="kirmizi",
             en_az=50, derin=False, hassas=False, desen=None, hepsi=False, metin="Tamam", sure=0.2, yok=False)
    v.update(k)
    return argparse.Namespace(**v)


def dur_kodu(f, a):
    try:
        f(a)
    except Dur as e:
        return e.kod
    return None


# ---------------------------------------------------------------- 1) hedef yasak → 10, görüntü alınmaz
print("1) hedef yasak pencere → Dur 10, hiçbir görüntü alınmaz")
cikti_yolu = os.path.join(_yalitim.GECICI, "yasak.png")
for ad, f, a in [("foto", gorsel.k_foto, ns(cikti=cikti_yolu)),
                 ("metin", ocr.k_metin, ns()),
                 ("bekle", ocr.k_bekle, ns()),
                 ("simge-kaydet", gorsel.k_simge_kaydet, ns(bolge="0,0,10,10")),
                 ("renk-bul", gorsel.k_renk_bul, ns())]:
    au.goruntu_sayisi = 0
    kod = dur_kodu(f, a)
    kontrol(f"{ad}: yasak hedef → 10, görüntü alınmadı", kod == 10 and au.goruntu_sayisi == 0,
            f"kod={kod} görüntü={au.goruntu_sayisi}")
kontrol("foto: yasak hedefin dosyası yazılmadı", not os.path.exists(cikti_yolu))
# simge-bul: simge dosyası olmalı (yoksa 1 ile önce durur)
os.makedirs(os.path.dirname(gorsel.simge_yolu("simge")), exist_ok=True)
Image.new("RGB", (8, 8), (0, 0, 0)).save(gorsel.simge_yolu("simge"))
au.goruntu_sayisi = 0
kod = dur_kodu(gorsel.k_simge_bul, ns())
kontrol("simge-bul: yasak hedef → 10, görüntü alınmadı", kod == 10 and au.goruntu_sayisi == 0, f"kod={kod}")
kontrol("simge-kaydet: yasak hedeften simge kaydedilmedi",
        Image.open(gorsel.simge_yolu("simge")).getpixel((0, 0)) == (0, 0, 0))

# ---------------------------------------------------------------- 2) diğer yasak pencereler siyah
print("2) üstteki yasak pencere görüntüde siyah")
cikti_yolu = os.path.join(_yalitim.GECICI, "w1.png")
gorsel.k_foto(ns(kimlik="w1", cikti=cikti_yolu))
im = Image.open(cikti_yolu).convert("RGB")
kontrol("foto: yasak pencerenin kapladığı alan siyah", im.getpixel((150, 100)) == (0, 0, 0), str(im.getpixel((150, 100))))
kontrol("foto: kalan alan okunur (kırmızı)", im.getpixel((20, 20)) == (200, 0, 0), str(im.getpixel((20, 20))))
alanlar = gorsel.renk_alanlari(gorsel.korumali_goruntu("w1")[0], "kirmizi", 50)
toplam_alan = sum(a[0] for a in alanlar)
kontrol("renk-bul: yasak alan sayılmaz (200x150 − 100x100)", toplam_alan == 200 * 150 - 100 * 100, str(toplam_alan))
okunan = []
ocr.derin_oku = lambda im, *a, **k: okunan.append(im) or []
ocr.k_metin(ns(kimlik="w1"))
kontrol("metin: OCR'a giden görüntüde yasak alan siyah", okunan and okunan[0].getpixel((150, 100)) == (0, 0, 0))
ocr.oku = lambda im, *a, **k: okunan.append(im) or ""
ocr.satirla = lambda *a, **k: []
ocr.yedek_ara = lambda *a, **k: []
okunan.clear()
kod = dur_kodu(ocr.k_bekle, ns(kimlik="w1", sure=0.0))
kontrol("bekle: OCR'a giden görüntüde yasak alan siyah (bulunamadı → 7)",
        kod == 7 and okunan and okunan[0].getpixel((150, 100)) == (0, 0, 0), f"kod={kod}")

print(f"\n{GECEN}/{TOPLAM} geçti")
sys.exit(0 if GECEN == TOPLAM else 1)
