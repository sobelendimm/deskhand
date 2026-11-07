"""OCR (tesseract, Türkçe; ekran kartı varsa EasyOCR ile desteklenir, bkz. ocr_gpu): ön işleme, okuma, önbellek,
satırlama, arama; ekrandan metin bulma döngüleri. Komutlar: metin, bekle.

Ekran kartı okuması tesseract'ın YERİNE geçmez (Türkçe harfte tesseract daha isabetli): arama zincirinde tesseract
bulamayınca ilk yedektir, liste/derin okumada ve güvenlik denetiminde tesseract satırlarına yalnız EKLENİR (aynı
yerdeki tesseract satırını değiştirmez). Kullanıcı oyundaysa ya da kurulum yoksa hat yalnız tesseract'tır."""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import time
import unicodedata

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from . import ocr_gpu, yollar
from .gorsel import bolge_coz, pencere_goruntusu
from .hata import Dur
from .i18n import _

DILLER = "tur"  # ölçüm: karışık TR+EN 18→23/24, terminal TR harfli kelime 19→37, %27 hızlı; salt EN 26→25/26
OCR_SURUM = "7"  # ön işlem değişince önbellek geçersizleşsin
# bulunamayınca sırayla denenen okumalar (ölçüm, 27 düğme/örnek: varsayılan 9, uyarlı+çizgisiz+psm6 23,
# azınlık+normal+çizgisiz+psm6 21). Varsayılan değişmedi: yoğun sayfalarda en iyisi o.
YEDEK_OKUMALAR = ({"hassas": True}, {"varyant": "uyarli", "cizgisiz": True, "psm": "6"},
                  {"varyant": "azinlik", "cizgisiz": True, "psm": "6"}, {"cizgisiz": True})
# güvenlik denetimi (tıklanan noktadaki yazı): bunlar PARALEL okunur, birleşimi alınır
DENETIM_OKUMALARI = ({}, {"varyant": "uyarli", "cizgisiz": True, "psm": "6"},
                     {"varyant": "azinlik", "cizgisiz": True, "psm": "6"})


def _kucuk_gri(im):
    return np.asarray(ImageOps.grayscale(im).reduce(2), dtype=np.uint8)


def _imlec_farki(eski, yeni):
    """İki yarı çözünürlüklü gri görüntü yalnız İNCE bir çizgi kadar mı farklı (yanıp sönen yazı imleci)?
    Fark yoksa ya da ≤30 belirgin piksel 1-2 piksel genişlik/yükseklikteki tek bir şeritteyse True.
    Rakam/harf değişikliği ('%16'→'%17') hem genişlik hem yükseklikte ≥3 piksel kutu yapar → False (yeniden okunur).
    Yalnız piksel SAYISINA bakmak (≤15 px) yetmez: tek rakamlık değişiklik eski metni döndürebilirdi."""
    m_ = np.abs(eski.astype(np.int16) - yeni) > 25
    n = int(m_.sum())
    if n == 0:
        return True
    if n > 30:
        return False
    ys, xs = np.nonzero(m_)
    return int(xs.max() - xs.min()) + 1 <= 2 or int(ys.max() - ys.min()) + 1 <= 2



def oku(im, hassas=False, cizgisiz=False, varyant="gri", psm="11", motor="tesseract", bekle=0.0):
    """Önbellekli OCR. (1) Birebir aynı görüntü → tesseract yok. (2) YAKIN eşleşme: son 8 kaydın yarı çözünürlüklü
    gri kopyasından yalnız ince bir çizgi kadar farklıysa (_imlec_farki) aynı sayılır — yanıp sönen yazı imleci her
    okumada özeti değiştirip önbelleği boşa çıkarıyordu (ölçüm: 3 okumada 3 kayıt).
    motor="gpu": ekran kartı okuması (ön işlem seçenekleri yok sayılır); kullanılamıyorsa [] (önbelleğe yazılmaz).
    bekle: GPU sunucusu açılıyorsa en çok bu kadar sn beklenir."""
    if motor == "gpu":
        anahtar = f"{OCR_SURUM}|{im.size}|gpu{ocr_gpu.SURUM}"
    else:
        anahtar = f"{OCR_SURUM}|{im.size}|{hassas}|{cizgisiz}|{varyant}|{psm}|{motor}"
    on = hashlib.blake2b(anahtar.encode(), digest_size=6).hexdigest()
    h = hashlib.blake2b(digest_size=12)
    h.update(im.tobytes())
    OCR_ONBELLEK = yollar.ocr_onbellek()
    yol = os.path.join(OCR_ONBELLEK, f"{on}_{h.hexdigest()}.json")

    def yukle(y):
        with open(y) as f:
            kel = json.load(f)
        os.utime(y)
        for w in kel:
            w["anahtar"] = tuple(w["anahtar"])
        return kel
    try:
        return yukle(yol)
    except (OSError, ValueError):
        pass
    kucuk = _kucuk_gri(im)
    try:
        yakinlar = sorted((os.path.join(OCR_ONBELLEK, d) for d in os.listdir(OCR_ONBELLEK)
                           if d.startswith(on + "_") and d.endswith(".npy")), key=os.path.getmtime, reverse=True)[:8]
    except OSError:
        yakinlar = []
    for y in yakinlar:
        try:
            eski = np.load(y)
            if eski.shape == kucuk.shape and _imlec_farki(eski, kucuk):
                return yukle(y[:-4] + ".json")
        except (OSError, ValueError):
            continue
    if motor == "gpu":
        kelimeler = oku_gpu(im, bekle)
        if kelimeler is None:
            return []
    else:
        kelimeler = oku_tesseract(im, hassas, cizgisiz, varyant, psm)
    try:
        os.makedirs(OCR_ONBELLEK, exist_ok=True)
        gecici = f"{yol}.{os.getpid()}.{threading.get_ident()}"
        with open(gecici, "w") as f:  # atomik: eşzamanlı ekran süreçleri yarım dosya okumasın
            json.dump(kelimeler, f, ensure_ascii=False)
        os.replace(gecici, yol)
        np.save(yol[:-5] + ".npy", kucuk)
        dosyalar = sorted((os.path.join(OCR_ONBELLEK, d) for d in os.listdir(OCR_ONBELLEK) if d.endswith(".json")),
                          key=os.path.getmtime)
        for eski in dosyalar[:-40]:  # en çok 40 kayıt
            for uzanti in (".json", ".npy"):
                try:
                    os.remove(eski[:-5] + uzanti)
                except OSError:
                    pass
    except OSError:
        pass
    return kelimeler


def _uzun_kosu(b, L):
    """b (bool 2B) içinde satır boyunca ≥L ardışık True koşusuna ait pikseller (tamamen vektörel)."""
    if b.shape[1] < L:
        return np.zeros_like(b)
    c = np.concatenate([np.zeros((b.shape[0], 1), np.int32), np.cumsum(b, 1, dtype=np.int32)], 1)
    tam = (c[:, L:] - c[:, :-L]) == L  # [i, j]: j..j+L-1 hepsi True
    t = np.concatenate([np.zeros((b.shape[0], 1), np.int32), np.cumsum(tam, 1, dtype=np.int32)], 1)
    w, j = tam.shape[1], np.arange(b.shape[1])
    return (t[:, np.clip(j + 1, 0, w)] - t[:, np.clip(j - L + 1, 0, w)]) > 0


def _kaydir(b, dy):
    o = np.zeros_like(b)
    if dy > 0:
        o[dy:] = b[:-dy]
    else:
        o[:dy] = b[-dy:]
    return o


def _blok(a, B, f):
    H, W = a.shape
    h2, w2 = -(-H // B) * B, -(-W // B) * B
    p = np.pad(a, ((0, h2 - H), (0, w2 - W)), mode="edge").reshape(h2 // B, B, w2 // B, B)
    return f(p, axis=(1, 3))


def _yay3(x, f):
    q = np.pad(x, 1, mode="edge")
    return f(np.stack([q[i:i + x.shape[0], j:j + x.shape[1]] for i in range(3) for j in range(3)]), 0)


def _uyarli_kaynak(im, G, B=16):
    """Gri YA DA en küçük renk kanalı: yerel zıtlığı (16 px blok, 3x3 komşuluk) belirgin yüksek olan.
    Turuncu/mavi/yeşil düğmede beyaz yazı griye çevrilince kayboluyor (turuncu≈140), en küçük kanalda
    zemin ≈17 → büyük zıtlık (bir mağaza sayfasında fiyat ve "Sepete Ekle" ancak böyle okundu)."""
    M = np.asarray(im, dtype=np.int16).min(2)
    zit = lambda a: _yay3(_blok(a, B, np.max), np.max) - _yay3(_blok(a, B, np.min), np.min)
    sec = np.repeat(np.repeat(zit(M) > zit(G) + 30, B, 0), B, 1)[:G.shape[0], :G.shape[1]]
    return np.where(sec, M, G)


def _azinlik_normal(G, r=12, delta=12, boy=17):
    """Yerel kutupluluk 'azınlıkta kalan ton yazıdır' + zemin normalleştirme (yerel zemin → beyaz).
    Orta tonlu düğmelerde (gri 90, turuncu) tesseract'ın genel eşiği düğmeyi yazıyla birlikte karartıyordu."""
    from scipy import ndimage as ndi
    g = G.astype(np.float32)
    ort = ndi.uniform_filter(g, 2 * r + 1)
    acik = ndi.uniform_filter((g > ort + delta).astype(np.float32), 2 * r + 1)
    koyu = ndi.uniform_filter((g < ort - delta).astype(np.float32), 2 * r + 1)
    ters = np.where((acik + koyu) > 0.02, acik < koyu, ort < 128)
    ters = ndi.uniform_filter(ters.astype(np.float32), 2 * r + 1) > 0.5  # karar harf içinde dönmesin
    a = np.where(ters, 255 - g, g)
    zemin = ndi.uniform_filter(ndi.maximum_filter(a, boy), 9)
    return np.clip(a * 255.0 / np.maximum(zemin, 1), 0, 255).astype(np.int16)


def icerik_kutusu(im, esik=24, pay=24, oran=0.6):
    """Büyük tek renkli zemin (tam ekran pencerede boş alan, sanal masaüstünün düz kökü) ön işlemeyi ve tesseract'ın
    sayfa bölümlemesini bozuyordu: 2560x1440 tam ekran test penceresinde 'Kaydet' 0 eşleşme (gerçek ekran testi).
    Zemin = kenar piksellerinin ortancası; ondan belirgin farklı piksellerin kutusu (+pay). Kutu görüntünün `oran`
    kadarından küçükse (x0, y0, x1, y1), değilse None (kırpmaya değmez)."""
    a = np.asarray(ImageOps.grayscale(im), dtype=np.int16)
    if a.size == 0:
        return None
    zemin = int(np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])))
    ys, xs = np.nonzero(np.abs(a - zemin) > esik)
    if not len(xs):
        return None
    h, w = a.shape
    x0, y0 = max(0, int(xs.min()) - pay), max(0, int(ys.min()) - pay)
    x1, y1 = min(w, int(xs.max()) + 1 + pay), min(h, int(ys.max()) + 1 + pay)
    if (x1 - x0) * (y1 - y0) >= oran * w * h:
        return None
    return x0, y0, x1, y1


def oku_tesseract(im, hassas=False, cizgisiz=False, varyant="gri", psm="11"):
    """Görüntü büyük boş zemin içeriyorsa yalnız içerik kutusu okunur (icerik_kutusu), koordinatlar geri kaydırılır."""
    kutu_ = icerik_kutusu(im)
    if kutu_ is None:
        return _oku_tesseract(im, hassas, cizgisiz, varyant, psm)
    x0, y0, x1, y1 = kutu_
    kelimeler = _oku_tesseract(im.crop(kutu_), hassas, cizgisiz, varyant, psm)
    for w in kelimeler:
        w["x"] += x0
        w["x2"] += x0
        w["y"] += y0
        w["y2"] += y0
    return kelimeler


def oku_gpu(im, bekle=0.0):
    """Ekran kartı okuması (ocr_gpu sunucusu); büyük boş zemin kırpılır (icerik_kutusu: VRAM ve süre düşer).
    → kelimeler ya da None (kullanılamıyor: kurulum yok, kullanıcı oyunda, sunucu açılmadı/hata)."""
    kutu_ = icerik_kutusu(im)
    kelimeler = ocr_gpu.oku(im if kutu_ is None else im.crop(kutu_), bekle)
    if kelimeler is None or kutu_ is None:
        return kelimeler
    x0, y0 = kutu_[:2]
    for w in kelimeler:
        w["x"] += x0
        w["x2"] += x0
        w["y"] += y0
        w["y2"] += y0
    return kelimeler


def _oku_tesseract(im, hassas=False, cizgisiz=False, varyant="gri", psm="11"):
    """Ön işlem (ölçümler): gri + YEREL zemin kutupluluğu (koyu zeminli bölgeler ters çevrilir;
    karışık temada 8/12 → 12/12 kelime) + büyütme (küçük pencere 2x: "Yakleniyor"→"Yükleniyor",
    süre ≈ aynı; büyük pencerede 1,5x yeterli, 2x +0,3 sn). hassas: bir kademe daha büyük.
    cizgisiz: ≥40 px ince yatay çizgiler (düğme/kutu çerçevesi) silinir. Web'deki tek başına "Satın al"
    düğmesini ancak böyle okur; AMA terminaldeki ─── ayırıcıları silinince tesseract'ın sayfa bölümlemesi
    çöküyor (328→106 kelime, ölçüldü) → varsayılan DEĞİL, yalnız yedek okuma."""
    g = ImageOps.grayscale(im)
    a = np.asarray(g, dtype=np.int16)
    if varyant == "azinlik":
        a = _azinlik_normal(a)
        ters = np.zeros(a.shape, bool)
        zemin = np.full(a.shape, 255, np.int16)
    else:
        if varyant == "uyarli":
            a = _uyarli_kaynak(im, a)
            g = Image.fromarray(a.astype(np.uint8))
        zemin = np.asarray(g.filter(ImageFilter.BoxBlur(12)), dtype=np.int16)
        ters = zemin < 128
        a = np.where(ters, 255 - a, a)
    if cizgisiz:
        z = np.where(ters, 255 - zemin, zemin)
        koyu = a < (z - 30)
        ince = koyu & ~(_kaydir(koyu, 3) & _kaydir(koyu, -3))  # üstü ya da altı açık: ince yapı
        a = np.where(_uzun_kosu(ince, 40), np.maximum(z, 200), a)
    g = Image.fromarray(a.astype(np.uint8))
    buyuk = g.width * g.height > 1_200_000
    k = (2.0 if hassas else 1.5) if buyuk else (3.0 if hassas else 2.0)
    g = g.resize((round(g.width * k), round(g.height * k)), Image.LANCZOS)
    b = io.BytesIO()
    g.save(b, "PPM")
    # tessedit_do_invert VARSAYILAN (açık) kalmalı: kapatınca (%2 hız) turuncu "Sepete Ekle" okunmuyordu
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", DILLER, "--psm", psm, "tsv"],
                       input=b.getvalue(), capture_output=True)
    if r.returncode != 0:
        raise Dur(9, _("tesseract hata verdi: {hata}").format(hata=r.stderr.decode(errors="replace").strip()[:300]))
    kelimeler = []
    for satir in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
        f = satir.split("\t")
        if len(f) < 12 or not f[11].strip() or float(f[10]) < 0:
            continue
        if len(f[11].strip()) == 1 and not norm(f[11]):  # tek başına çizgi/simge (düğme kenarı "|")
            continue
        x, y, w, h = (int(v) / k for v in f[6:10])
        kelimeler.append({"anahtar": (int(f[2]), int(f[3]), int(f[4])), "x": x, "y": y, "g": w, "y2": y + h,
                          "x2": x + w, "conf": float(f[10]), "t": f[11]})
    return kelimeler


def satirla(kelimeler):
    satirlar = {}
    for w in kelimeler:
        satirlar.setdefault(w["anahtar"], []).append(w)
    sonuc = []
    for ws in satirlar.values():
        ws.sort(key=lambda w: w["x"])
        sonuc.append({"kelimeler": ws, **kutu(ws)})
    sonuc.sort(key=lambda s: (round(s["cy"] / 8), s["x"]))
    return sonuc


def kutu(ws):
    x, y = min(w["x"] for w in ws), min(w["y"] for w in ws)
    x2, y2 = max(w["x2"] for w in ws), max(w["y2"] for w in ws)
    return {"x": x, "y": y, "x2": x2, "y2": y2, "cx": (x + x2) / 2, "cy": (y + y2) / 2,
            "conf": sum(w["conf"] for w in ws) / len(ws), "t": " ".join(w["t"] for w in ws)}


TR_KATLA = str.maketrans("İIıŞşĞğÜüÖöÇç", "iiissgguuoocc")


def katla(s):
    """Türkçe harf/aksan/büyük-küçük katlama; kelime aralıkları korunur."""
    s = unicodedata.normalize("NFKD", s.translate(TR_KATLA).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[\W_]+", " ", s).split())


def norm(s):
    return katla(s).replace(" ", "")


# tesseract'ın sık karışıklıkları (ölçüldü: "Müzik"→"Miizik", "önce"→"6nce"); YALNIZ benzerlik
# karşılaştırmasında, iki tarafa da aynı uygulanır. Tam eşleşme kuralı değişmez.
OCR_KARISIK = (("ii", "u"), ("rn", "m"), ("0", "o"), ("6", "o"))


def kaba(s):
    for x, y in OCR_KARISIK:
        s = s.replace(x, y)
    return s


def ara(satirlar, sorgu, esik=0.8):
    """Sorguyu satırlarda arar: Türkçe harf/büyük-küçük/noktalama duyarsız, OCR hatalarına
    karşı benzerlik ≥ esik. Tam eşleşme varsa yalnız onlar döner. Okuma sırasıyla."""
    q = [w for w in (norm(t) for t in sorgu.split()) if w]
    if not q:
        return []
    qs, n = "".join(q), len(q)
    qk = kaba(qs)
    if len(qs) <= 4:  # "OK", "Sil" gibi kısa sorgularda benzerlik yanıltır: yalnız tam eşleşme
        esik = 1.0
    adaylar = []
    for si, s in enumerate(satirlar):
        nw = [norm(w["t"]) for w in s["kelimeler"]]
        for L in sorted({max(1, n - 1), n, n + 1}):
            for i in range(len(nw) - L + 1):
                j = "".join(nw[i:i + L])
                if not j:
                    continue
                if j == qs:
                    skor = 1.0
                else:
                    jk = kaba(j)
                    skor = 0.99 if jk == qk else difflib.SequenceMatcher(None, jk, qk).ratio()
                if skor >= esik:
                    adaylar.append((skor, si, i, i + L))
    adaylar.sort(key=lambda a: (-a[0], a[3] - a[2]))
    secilen = []
    for a in adaylar:  # aynı satırda üst üste binenleri ele
        if all(not (b[1] == a[1] and a[2] < b[3] and b[2] < a[3]) for b in secilen):
            secilen.append(a)
    if secilen:  # tam eşleşme varsa yalnız onlar; yoksa en iyiye 0,05 yakın olanlar
        en_iyi = secilen[0][0]
        secilen = [a for a in secilen if a[0] == 1.0] if en_iyi == 1.0 else [a for a in secilen if a[0] >= en_iyi - 0.05]
    sonuc = [{**kutu(satirlar[si]["kelimeler"][i:j]), "skor": skor, "satir": satirlar[si]["t"]}
             for skor, si, i, j in secilen]
    sonuc.sort(key=lambda m: (round(m["cy"] / 8), m["x"]))
    return sonuc


def gurultu_mu(s):
    """Resim/simge üstünde OCR'ın uydurduğu parçalar ('aA', 'HEAECTE' [0]): düşük güven ya da 1-2 harf."""
    n = len(norm(s["t"]))
    return n == 0 or s["conf"] < 50 or (n <= 2 and s["conf"] < 85)


def kok_ekle(m, kok):
    bx, by = kok
    return {**m, **{a: m[a] + bx for a in ("x", "x2", "cx")}, **{a: m[a] + by for a in ("y", "y2", "cy")}}


def yazdir_eslesme(ms, numarali=True):
    for i, m in enumerate(ms, 1):
        no = f"#{i} " if numarali else ""
        benz = "" if m.get("skor", 1) == 1.0 else f" ~{m['skor']:.2f}"
        print(f"  {no}({m['cx']:.0f},{m['cy']:.0f}) [{m['conf']:.0f}{benz}] {m['t']}")


def tara(k, metin, bolge, hassas=False):
    """Bir kez görüntü al + oku + ara. → (pencere koordinatlı eşleşmeler, geo, kök, görüntü özeti).
    Görüntü içerik durunca alınır (kaydırma animasyonu sürerken okunan konum tıklamada kayar)."""
    im, geo, kok = pencere_goruntusu(k, bolge, kararli=True)
    ozet = hashlib.blake2b(im.tobytes(), digest_size=16).digest()
    ms = ara(satirla(oku(im, hassas)), metin)
    return [kok_ekle(m, kok) for m in ms], geo, kok, ozet, im


def yedek_ara(im, metin):
    """Varsayılan okuma bulamayınca: (1) ekran kartı okuması (sıcak sunucu ~0,2 sn; açık değilse arka planda açılır,
    beklenmez), (2) tesseract yedek okumaları sırayla, (3) sunucu o arada açılıyorsa onu bekle (ilk açılış ~2,5 sn).
    Ölçüm (38 düğme/soluk/küçük yazı): tesseract zinciri 32, ekran kartı 38. → eşleşmeler (görüntü koordinatı)."""
    ms = ara(satirla(oku(im, motor="gpu")), metin)
    if ms:
        return ms
    for secenek in YEDEK_OKUMALAR:
        ms = ara(satirla(oku(im, **secenek)), metin)
        if ms:
            return ms
    if ocr_gpu.calisiyor():
        return ara(satirla(oku(im, motor="gpu", bekle=ocr_gpu.SOGUK_SN)), metin)
    return []


def bul_dongu(k, metin, bolge, sure, yok=False, son_care=True):
    """Metin görünene (yok=True: kaybolana) kadar görüntü al + oku.
    → (eşleşmeler, geo, kök, süre, görüntü özeti, görüntü). Aynı görüntü yeniden okunmaz (önbellek)."""
    t0 = time.monotonic()
    bitis = t0 + sure
    hassas_denendi = False
    while True:
        ms, geo, kok, ozet, im = tara(k, metin, bolge)
        son = time.monotonic() >= bitis
        if not ms and not yok and son and son_care and not hassas_denendi:
            hassas_denendi = True  # son çare: ekran kartı, bir kademe büyütme, kutu çerçevesiz okumalar (yedek_ara)
            ms = [kok_ekle(m, kok) for m in yedek_ara(im, metin)]
        if bool(ms) != yok or son:
            return ms, geo, kok, time.monotonic() - t0, ozet, im
        time.sleep(0.2)


KAYDIR_BEKLE = 0.35  # tarayıcının yumuşak kaydırması bitsin


def ayni_konum(a, b):
    """İki kare aynı kaydırma konumunda mı? Satırların ≥%97'si aynıysa evet. Saat/imleç gibi küçük
    değişimlere dayanıklı (eski yöntem birebir özetti: saat değişince sayfa sonunu kaçırıyordu)."""
    if a.size != b.size:
        return False
    x = np.asarray(a.convert("L"), dtype=np.int16)
    y = np.asarray(b.convert("L"), dtype=np.int16)
    return (np.abs(x - y).max(1) > 2).mean() < 0.03


def kayma(onceki, simdi, en_az=60):
    """İçerik önceki→şimdi kaç piksel YUKARI kaydı? Satır imzası eşleştirmesi; tarayıcı çubukları gibi
    sabit şeritler uymasa da en çok uyan içerikli satır oranı seçilir (Vikipedi: 5/5 doğru, ~0,1 sn).
    Güvenilir değilse None."""
    if onceki.size != simdi.size:
        return None
    a_ = np.asarray(onceki.convert("L"), dtype=np.int16)
    b_ = np.asarray(simdi.convert("L"), dtype=np.int16)
    ra = np.concatenate([a_.mean(1, keepdims=True), a_[:, ::7]], 1)
    rb = np.concatenate([b_.mean(1, keepdims=True), b_[:, ::7]], 1)
    icerikli = ra[:, 1:].std(1) > 2
    H = len(ra)
    en_iyi, d_iyi = 0.0, None
    for d in range(1, H - en_az):
        ic = icerikli[d:]
        n = int(ic.sum())
        if n < 20:
            continue
        uyan = int(((np.abs(ra[d:] - rb[:H - d]).max(1) < 1) & ic).sum())
        if uyan >= 20 and uyan / n > en_iyi:
            en_iyi, d_iyi = uyan / n, d
    return d_iyi if en_iyi >= 0.15 else None


def dogrula(im, kok, metin, cx, cy):
    """Görüntüde (kök = görüntünün pencere koordinatındaki sol üstü) (cx,cy) çevresinde metin gerçekten
    var mı? Küçük bölge, normal + çizgisiz okuma. → pencere koordinatlı eşleşmeler ([] = yok)."""
    bx, by = kok
    x0, y0 = max(0, round(cx - bx) - 260), max(0, round(cy - by) - 40)
    parca = im.crop((x0, y0, min(im.width, x0 + 520), min(im.height, y0 + 80)))
    if parca.width < 20 or parca.height < 10:
        return []
    for secenek in ({},) + YEDEK_OKUMALAR[1:] + ({"motor": "gpu"},):
        ms = ara(satirla(oku(parca, **secenek)), metin)
        if ms:
            return [kok_ekle(m, (bx + x0, by + y0)) for m in ms]
    return []


def nokta_metni(k, x, y):
    """Tıklanacak noktanın üstündeki/yakınındaki yazı (hassas düğme denetimi için; ~0,4 sn, dotool
    kurulumuyla örtüşür)."""
    im, geo, kok = pencere_goruntusu(k, (round(x) - 220, round(y) - 35, 440, 70), kararli=True)
    sonuc = {}

    def is_(ad, **secenek):
        try:
            sonuc[ad] = oku(im, **secenek)
        except Dur:
            sonuc[ad] = []

    # güvenlik denetimi okuyamazsa kilit çalışmaz: birkaç yöntem BİRLİKTE (paralel), birleşim; ekran kartı sıcaksa
    # o da (açık değilse beklenmez, sonraki denetimler için açılır)
    ipler = [threading.Thread(target=is_, args=(i,), kwargs=sec)
             for i, sec in enumerate(DENETIM_OKUMALARI + ({"motor": "gpu"},))]
    for t in ipler:
        t.start()
    for t in ipler:
        t.join()
    yakin = []
    for ws in sonuc.values():
        for s in satirla(ws):
            s = kok_ekle(s, kok)
            if s["x"] - 15 <= x <= s["x2"] + 15 and s["y"] - 15 <= y <= s["y2"] + 15 and s["t"] not in yakin:
                yakin.append(s["t"])
    return yakin


# KÜÇÜK bölge (panel saati, tek düğme, durum çubuğu): psm 11 (dağınık metin) iri tek satırı hiç görmeyebiliyor —
# gerçek test: panel saati 140x54 → psm11 '16:16'yı atladı, psm6 okudu. Küçükte ikisi paralel, birleşik.
KUCUK_BOLGE = (420, 160)
KUCUK_OKUMALAR = ({}, {"psm": "6"})
LISTE_OKUMALARI = ({}, {"varyant": "uyarli", "cizgisiz": True, "psm": "6"})


def _ayni_satir(a, b):
    return (abs(a["cx"] - b["cx"]) < 25 and abs(a["cy"] - b["cy"]) < 12 and
            difflib.SequenceMatcher(None, norm(a["t"]), norm(b["t"])).ratio() > 0.6)


def gpu_ekle(satirlar, gpu_satirlari):
    """Ekran kartı satırlarını tesseract satırlarına EKLER; tesseract satırı hiç değişmez (Türkçe harfte tesseract
    daha isabetli). Bir ekran kartı satırı yalnız YENİ bilgi taşımıyorsa eklenmez: aynı yerde üst üste binen
    tesseract satırlarının (birleşik) katlanmış metni onu birebir içeriyorsa. Benzer ama farklı okuma eklenir: ölçümde
    tesseract 'Satın al' düğmesini 'sazmal', 'Ana menüye dön'ü '(önamenüyedn' okumuştu. Eklenenler s["gpu"]=True."""
    def var_mi(g):
        gn = norm(g["t"])
        if not gn:
            return True
        ortak = "".join(norm(s_["t"]) for s_ in sorted(satirlar, key=lambda s_: s_["x"])
                        if abs(g["cy"] - s_["cy"]) < 12 and s_["x"] < g["x2"] and g["x"] < s_["x2"])
        return gn in ortak
    eklenen = [{**g, "gpu": True} for g in gpu_satirlari if not var_mi(g)]
    if not eklenen:
        return satirlar
    return sorted(satirlar + eklenen, key=lambda s_: (round(s_["cy"] / 8), s_["x"]))


def derin_oku(im, okumalar=DENETIM_OKUMALARI, gpu_bekle=ocr_gpu.SOGUK_SN):
    """Birkaç ön işlem PARALEL okunur, satırlar birleştirilir (aynı yerdeki tekrarlar elenir): renkli düğmeler
    (yeşil 'Yeniden bağlan', kırmızı 'Oyundan çık') varsayılan okumada görünmüyordu (bir oyun menüsünde).
    Ekran kartı okuması da paralel çalışır ve gpu_ekle ile yalnız eklenir (gpu_bekle: sunucu açılıyorsa beklenecek
    en çok süre; None = ekran kartı yok)."""
    sonuc = {}

    def is_(i, sec):
        try:
            sonuc[i] = satirla(oku(im, **sec))
        except Dur:
            sonuc[i] = []
    isler = list(enumerate(okumalar))
    if gpu_bekle is not None:
        isler.append(("gpu", {"motor": "gpu", "bekle": gpu_bekle}))
    ipler = [threading.Thread(target=is_, args=(i, sec)) for i, sec in isler]
    for t in ipler:
        t.start()
    for t in ipler:
        t.join()
    birlesik = []
    for i in sorted(k for k in sonuc if k != "gpu"):
        for s_ in sonuc[i]:
            es = next((j for j, b in enumerate(birlesik) if _ayni_satir(s_, b)), None)
            if es is None:
                birlesik.append(s_)
            elif s_["conf"] > birlesik[es]["conf"]:  # aynı satırın daha güvenli okuması kalır (ör. tarih: 'N 31102026 Nez' [31] → '31.10.2026')
                birlesik[es] = s_
    birlesik.sort(key=lambda s_: (round(s_["cy"] / 8), s_["x"]))
    return gpu_ekle(birlesik, sonuc.get("gpu", []))


def k_metin(a):
    t0 = time.monotonic()
    im, geo, kok = pencere_goruntusu(a.kimlik, bolge_coz(a.bolge))
    if a.derin:
        satirlar = derin_oku(im)
    elif not a.hassas and im.size[0] <= KUCUK_BOLGE[0] and im.size[1] <= KUCUK_BOLGE[1]:
        satirlar = derin_oku(im, KUCUK_OKUMALAR, gpu_bekle=0.0)
    elif a.desen or a.hassas:
        satirlar = satirla(oku(im, a.hassas))  # arama: bulunamazsa aşağıda yedek okumalar
    else:
        # liste: varsayılan + düğme odaklı okuma PARALEL birleşir (ajan düğmeyi göremezse kullanamaz: Firefox'ta
        # tek başına duran 'Satın al' düğmesi varsayılan okumada görünmüyordu — gerçek ekran testi)
        satirlar = derin_oku(im, LISTE_OKUMALARI)
    sure = time.monotonic() - t0
    if a.desen:
        ms = [kok_ekle(m, kok) for m in ara(satirlar, a.desen)]
        if not ms and not a.hassas:  # bulunamazsa yedek okumalar (ekran kartı + tesseract yedekleri)
            ms = [kok_ekle(m, kok) for m in yedek_ara(im, a.desen)]
        sure = time.monotonic() - t0
        print(_("# '{desen}': {sayi} eşleşme ({sn} sn)").format(desen=a.desen, sayi=len(ms), sn=f"{sure:.2f}"))
        yazdir_eslesme(ms)
        if not ms:
            raise Dur(6, _("bulunamadı"))
    else:
        temiz = satirlar if a.hepsi else [s for s in satirlar if not gurultu_mu(s)]
        gizli = len(satirlar) - len(temiz)
        gpu_sayi = sum(1 for s in temiz if s.get("gpu"))
        print(_("# {sayi} satır, pencere {genislik}x{yukseklik} ({sn} sn); (merkez x,y) [güven] metin").format(
            sayi=len(temiz), genislik=geo[2], yukseklik=geo[3], sn=f"{sure:.2f}")
              + (_("; {sayi} gürültü satırı gizli (--hepsi)").format(sayi=gizli) if gizli else "")
              + (_("; {sayi} satırı yalnız ekran kartı okudu").format(sayi=gpu_sayi) if gpu_sayi else ""))
        yazdir_eslesme([kok_ekle(s, kok) for s in temiz], numarali=False)


def k_bekle(a):
    ms, geo, kok, sure, *_x = bul_dongu(a.kimlik, a.metin, bolge_coz(a.bolge), a.sure, a.yok)
    if a.yok:
        if ms:
            raise Dur(7, _("'{metin}' {sure} sn içinde kaybolmadı").format(metin=a.metin, sure=a.sure))
        print(_("kayboldu: '{metin}' ({sn} sn)").format(metin=a.metin, sn=f"{sure:.1f}"))
    else:
        if not ms:
            raise Dur(7, _("'{metin}' {sure} sn içinde görünmedi").format(metin=a.metin, sure=a.sure))
        print(_("göründü: '{metin}' ({sn} sn)").format(metin=a.metin, sn=f"{sure:.1f}"))
        yazdir_eslesme(ms)
