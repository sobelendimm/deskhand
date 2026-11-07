"""Görüntü: pencere görüntüsü (tüm ekran görüntüsünden pencere kırpımı), ızgara/cetvel, simge eşleme (NCC),
renk alanları. Komutlar: foto, simge-kaydet, simge-bul, renk-bul."""
from __future__ import annotations

import json
import math
import os
import re
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import yollar
from .arka_uc import EKRAN, sec
from .hata import Dur
from .i18n import _


def bolge_coz(s):
    if not s:
        return None
    v = [int(float(t)) for t in re.split(r"[,x+ ]+", s.strip()) if t]
    if len(v) != 4 or v[2] <= 0 or v[3] <= 0:
        raise Dur(1, _("--bolge x,y,genişlik,yükseklik olmalı: {deger}").format(deger=repr(s)))
    return v


def pencere_goruntusu(k, bolge=None, kararli=False):
    """→ (görüntü, pencere geometrisi, bölge kökü). Görüntü pikseli + kök = pencere koordinatı.
    kararli=True: içerik DURANA dek bekle (en çok 1,5 sn): tarayıcının yumuşak kaydırması sürerken okunan konuma
    tıklamak, sayfa kaymaya devam ettiği için bir üst satırdaki alanı tıklıyordu (gerçek ekran testi: yazı
    'Not alanı' yerine 'E-posta' kutusuna gitti). Tıklama/hassas denetim yolları bunu kullanır."""
    im, geo, kok = _pencere_goruntusu(k, bolge)
    if not kararli:
        return im, geo, kok
    from .ocr import ayni_konum
    bitis = time.monotonic() + 1.5
    while time.monotonic() < bitis:
        time.sleep(0.1)
        im2, geo2, kok2 = _pencere_goruntusu(k, bolge)
        durdu = geo2 == geo and ayni_konum(im, im2)
        im, geo, kok = im2, geo2, kok2
        if durdu:
            break
    return im, geo, kok


def _pencere_goruntusu(k, bolge=None):
    au = sec()
    au.one_getir(k)
    geo = au.geometri(k)
    X, Y, W, H = geo
    sx0, sy0, sx1, sy1 = au.ekran_alani()
    tam = au.goruntu()
    if tam.size != (sx1 - sx0, sy1 - sy0):  # ekran ölçeği ≠ 1: fiziksel piksel → mantıksal koordinat
        tam = tam.resize((sx1 - sx0, sy1 - sy0), Image.LANCZOS)
    if k != EKRAN and au.aktif() != k:
        raise Dur(3, _("görüntü alınırken pencere değişti → {baslik}").format(baslik=repr(au.baslik(au.aktif()))))
    im = tam.crop((X - sx0, Y - sy0, X - sx0 + W, Y - sy0 + H))
    bx = by = 0
    if bolge:
        bx, by, bw, bh = bolge
        bx, by = max(0, min(bx, W - 1)), max(0, min(by, H - 1))
        im = im.crop((bx, by, min(W, bx + bw), min(H, by + bh)))
    return im, geo, (bx, by)


# ---------------------------------------------------------------- ızgara

def font(boyut):
    for yol in ("/usr/share/fonts/noto/NotoSansMono-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf"):
        if os.path.exists(yol):
            return ImageFont.truetype(yol, boyut)
    return ImageFont.load_default()


def ciz_izgara(im, adim, kok, olcek):
    """Izgara + üst/sol CETVEL (etiketler içeriğin dışında, yazıyı örtmez). Etiketler PENCERE
    koordinatıdır: görüntü küçültülmüş/kırpılmış olsa da okunan değer doğrudan `tikla`ya verilir.
    → (yeni görüntü, (sol_pay, üst_pay))"""
    f = font(11)
    bx, by = kok
    W, H = im.size
    adim_px = adim * olcek
    olc = ImageDraw.Draw(im)
    sol = olc.textbbox((0, 0), str(int(by + H / olcek)), font=f)[2] + 8
    ust = olc.textbbox((0, 0), "0123456789", font=f)[3] + 6
    xg = olc.textbbox((0, 0), str(int(bx + W / olcek)), font=f)[2]
    yeni = Image.new("RGB", (W + sol, H + ust), (250, 245, 190))
    yeni.paste(im, (sol, ust))
    d = ImageDraw.Draw(yeni, "RGBA")
    cizgi_kat = max(1, math.ceil(12 / adim_px))                        # çizgiler arası ≥ 12 piksel
    ex = math.ceil(max(cizgi_kat, (xg + 10) / adim_px) / cizgi_kat) * cizgi_kat
    ey = math.ceil(max(cizgi_kat, (ust + 4) / adim_px) / cizgi_kat) * cizgi_kat
    for wx in range(math.ceil(bx / adim) * adim, int(bx + W / olcek) + 1, adim):
        if (wx // adim) % cizgi_kat:
            continue
        ix = sol + (wx - bx) * olcek
        etiketli = (wx // adim) % ex == 0
        d.line([(ix, ust if not etiketli else 0), (ix, H + ust)], fill=(255, 0, 255, 150 if etiketli else 80), width=1)
        if etiketli:
            d.text((ix + 2, 1), str(wx), font=f, fill=(0, 0, 0, 255))
    for wy in range(math.ceil(by / adim) * adim, int(by + H / olcek) + 1, adim):
        if (wy // adim) % cizgi_kat:
            continue
        iy = ust + (wy - by) * olcek
        etiketli = (wy // adim) % ey == 0
        d.line([(sol if not etiketli else 0, iy), (W + sol, iy)], fill=(255, 0, 255, 150 if etiketli else 80), width=1)
        if etiketli:
            d.text((2, iy + 1), str(wy), font=f, fill=(0, 0, 0, 255))
    return yeni, (sol, ust)


# ---------------------------------------------------------------- simgeler (yazısız düğmeler)


def simge_yolu(ad):
    if not re.fullmatch(r"[\w.-]+", ad):
        raise Dur(1, _("simge adı yalnız harf/rakam/._- içermeli: {ad}").format(ad=repr(ad)))
    return os.path.join(yollar.simge_dizin(), ad + ".png")


SIMGE_YAKIN = 0.08  # eşiğin bu kadar altındaki adaylar da tıklamada BELİRSİZLİK sayılır (güvenlik)


def simge_ara(im, sablon, esik=0.9):
    """Normalize çapraz korelasyon (FFT, scipy). Aynı ölçek varsayılır. → [(skor, cx, cy)] (görüntü koord.),
    en iyiden kötüye, şablon boyu kadar çakışma bastırılmış. İkisi de σ=0,8 bulanıklaştırılır: alt piksel (RGB)
    yazı yumuşatması aynı düğmeyi farklı çiziyordu (ölçüm: eş 'Tamam' 0,874 → 0,960; en yüksek yanlış
    benzerlik 0,825; σ=1,2'de Kaydet↔Tamam 0,89 = tehlikeli)."""
    from scipy import ndimage as ndi
    from scipy.signal import fftconvolve
    I = np.asarray(im.convert("L").filter(ImageFilter.GaussianBlur(0.8)), dtype=np.float64)
    T = np.asarray(sablon.convert("L").filter(ImageFilter.GaussianBlur(0.8)), dtype=np.float64)
    h, w = T.shape
    if I.shape[0] < h or I.shape[1] < w:
        return []
    T0 = T - T.mean()
    tn = np.sqrt((T0 ** 2).sum())
    if tn < 1e-6:
        raise Dur(1, _("simge düz renk (ayırt edici değil); daha belirgin bir bölge kaydet"))
    pay = fftconvolve(I, T0[::-1, ::-1], mode="valid")
    bir = np.ones((h, w))
    s1 = fftconvolve(I, bir, mode="valid")
    s2 = fftconvolve(I * I, bir, mode="valid")
    var = np.maximum(s2 - s1 * s1 / (h * w), 1e-9)
    ncc = pay / (tn * np.sqrt(var))
    ncc[var < 1e-3 * h * w] = 0  # düz alanlar sahte eşleşme vermesin
    tepe = (ncc == ndi.maximum_filter(ncc, size=(h, w))) & (ncc >= esik)
    ys, xs = np.nonzero(tepe)
    # RENK UYUMU: NCC gri tonda çalışır; kırmızı 'Vazgeç' gri 'Kaydet'e 0,83 benziyordu → adayın
    # ortalama rengi şablondan bir kanalda >35 farklıysa ele
    Irgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    Tort = np.asarray(sablon.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(0)
    sonuc = []
    for y, x in zip(ys, xs):
        if np.abs(Irgb[y:y + h, x:x + w].reshape(-1, 3).mean(0) - Tort).max() <= 35:
            sonuc.append((float(ncc[y, x]), x + w / 2, y + h / 2))
    sonuc.sort(reverse=True)
    secilen = []
    for sk, cx, cy in sonuc:
        if all(abs(cx - a) >= w * 0.6 or abs(cy - b) >= h * 0.6 for _sk, a, b in secilen):
            secilen.append((sk, cx, cy))
    return secilen[:20]


def simge_bul_ic(a):
    yol = simge_yolu(a.ad)
    if not os.path.exists(yol):
        raise Dur(1, _("simge yok: {ad} (önce: ekran simge-kaydet <kimlik> {ad} --bolge x,y,g,y)").format(ad=a.ad))
    im, geo, kok = pencere_goruntusu(a.kimlik, bolge_coz(a.bolge))
    tum = simge_ara(im, Image.open(yol), a.esik - SIMGE_YAKIN)
    tum = [(sk, cx + kok[0], cy + kok[1]) for sk, cx, cy in tum]
    sira = lambda t: (round(t[2] / 8), t[1])  # okuma sırası (--sira için)
    kesin = sorted((t for t in tum if t[0] >= a.esik), key=sira)
    yakin = sorted((t for t in tum if t[0] < a.esik), key=sira)
    return kesin, yakin, geo



# ---------------------------------------------------------------- renk (yazısı okunamayan renkli düğmeler)

RENKLER = {  # kanal baskınlığı: (baskın kanal, diğerlerinden en az fark, en düşük değer). Ölçüm (oyun menüsü):
    "yesil": (1, 40, 90),    # Bağlan (81,153,85)
    "kirmizi": (0, 55, 110),  # Oyundan çık (159,64,64)
    "mavi": (2, 40, 110),
}


def renk_alanlari(im, renk, en_az=250):
    """Görüntüde renge uyan bağlantılı alanlar, büyükten küçüğe: [(alan, cx, cy, (x0,y0,x1,y1))]."""
    from scipy import ndimage as ndi
    a = np.asarray(im.convert("RGB"), dtype=np.int16)
    if renk in RENKLER:
        k, fark, taban = RENKLER[renk]
        digerleri = [i for i in range(3) if i != k]
        maske = (a[:, :, k] >= taban) & (a[:, :, k] - a[:, :, digerleri[0]] >= fark) & (a[:, :, k] - a[:, :, digerleri[1]] >= fark)
    else:
        hedef = np.array([int(v) for v in renk.split(",")], dtype=np.int16)
        maske = np.abs(a - hedef).max(axis=2) <= 35
    etiket, n = ndi.label(maske)
    if n == 0:
        return []
    alanlar = ndi.sum(maske, etiket, index=range(1, n + 1))
    sonuc = []
    for i, alan in enumerate(alanlar, 1):
        if alan >= en_az:
            ys, xs = np.nonzero(etiket == i)
            sonuc.append((int(alan), float(xs.mean()), float(ys.mean()), (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))))
    return sorted(sonuc, reverse=True)


# ---------------------------------------------------------------- komutlar

def k_foto(a):
    im, geo, kok = pencere_goruntusu(a.kimlik, bolge_coz(a.bolge))
    olcek = 1.0
    if a.genislik and im.width > a.genislik:
        olcek = a.genislik / im.width
        im = im.resize((a.genislik, max(1, round(im.height * olcek))), Image.LANCZOS)
    kenar = (0, 0)
    if a.izgara:
        im, kenar = ciz_izgara(im, a.izgara, kok, olcek)
    os.makedirs(yollar.cikti(), exist_ok=True)
    cikti = a.cikti or os.path.join(yollar.cikti(), "pencere.png")
    im.save(cikti)
    with open(yollar.son_foto(), "w") as fp:
        json.dump({"kimlik": a.kimlik, "geo": geo, "kok": kok, "olcek": olcek, "kenar": kenar, "dosya": cikti}, fp)
    ek = []
    if kok != (0, 0) or a.bolge:
        ek.append(_("bölge kökü +{x}+{y}").format(x=kok[0], y=kok[1]))
    if olcek != 1.0:
        ek.append(_("ölçek {olcek}").format(olcek=f"{olcek:.4f}"))
    if kenar != (0, 0):
        ek.append(_("cetvel payı sol {sol}, üst {ust}").format(sol=kenar[0], ust=kenar[1]))
    print(f"{cikti} ({im.width}x{im.height})"
          + ("  [" + _("{ayrinti}; tikla --foto eşler").format(ayrinti=", ".join(ek)) + "]" if ek else ""))


def k_simge_kaydet(a):
    bolge = bolge_coz(a.bolge)
    if not bolge:
        raise Dur(1, _("--bolge x,y,genişlik,yükseklik zorunlu (simgenin çevresi; foto --izgara ile bul)"))
    im, geo, kok = pencere_goruntusu(a.kimlik, bolge)
    os.makedirs(yollar.simge_dizin(), exist_ok=True)
    im.save(simge_yolu(a.ad))
    print(_("simge kaydedildi: {ad} ({genislik}x{yukseklik}) → {yol}").format(
        ad=a.ad, genislik=im.width, yukseklik=im.height, yol=simge_yolu(a.ad)))


def k_simge_bul(a):
    t0 = time.monotonic()
    kesin, yakin, _geo = simge_bul_ic(a)
    print(_("# simge '{ad}': {sayi} eşleşme ({sn} sn)").format(ad=a.ad, sayi=len(kesin), sn=f"{time.monotonic() - t0:.2f}")
          + (_(", {sayi} yakın aday (eşik altı)").format(sayi=len(yakin)) if yakin else ""))
    for i, (sk, cx, cy) in enumerate(kesin, 1):  # koordinat satırları: çevrilmez
        print(f"  #{i} ({cx:.0f},{cy:.0f}) benzerlik {sk:.3f}")
    for sk, cx, cy in yakin:
        print(f"  ~ ({cx:.0f},{cy:.0f}) benzerlik {sk:.3f} (eşik {a.esik} altı)")
    if not kesin:
        raise Dur(6, _("bulunamadı"))


def k_renk_bul(a):
    im, geo, kok = pencere_goruntusu(a.kimlik, bolge_coz(a.bolge))
    alanlar = renk_alanlari(im, a.renk, a.en_az)
    print(_("# '{renk}': {sayi} alan (en az {en_az} piksel)").format(renk=a.renk, sayi=len(alanlar), en_az=a.en_az))
    for i, (alan, cx, cy, (x0, y0, x1, y1)) in enumerate(alanlar[:10], 1):  # koordinat satırları: çevrilmez
        print(f"  #{i} ({cx + kok[0]:.0f},{cy + kok[1]:.0f}) {alan} piksel, kutu {x1 - x0 + 1}x{y1 - y0 + 1}")
    if not alanlar:
        raise Dur(6, _("bulunamadı"))
