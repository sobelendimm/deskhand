"""Eylem öncesi/sonrası ekran farkı (MCP `changed`, `changed_region`, `changed_ratio`, `new_text`).

Ucuz: görüntüler yarı çözünürlüklü gri (NumPy) olarak tutulur, fark eşiklenir, değişen piksellerin sınır kutusu
alınır. Gürültüye dayanıklı: yanıp sönen yazı imleci (ince DİKEY çizgi, birkaç piksel) değişiklik sayılmaz
(ocr._imlec_farki ile aynı eşik); yatay ince çizgi (alt çizgi, ilerleme çubuğu) sayılır.
Saf işlevler: ekran/arka uç/MCP bilmez (testler sentetik görüntüyle çalışır)."""
from __future__ import annotations

import numpy as np
from PIL import ImageOps

ESIK = 25  # gri düzey farkı (ocr._imlec_farki ile aynı)
IMLEC_EN_COK = 40  # ince dikey çizginin en çok bu kadar belirgin pikseli olabilir (yarı çözünürlük)
IMLEC_GENISLIK = 2  # ... ve en çok bu kadar (yarı çözünürlüklü) piksel genişliğinde
KUCUK_ORAN = 0.25  # bundan küçük değişen alan için new_text okunur (mcp_sunucu) ...
YENI_METIN_ALAN = 70_000  # ... ve kutu en çok bu kadar piksel olabilir (ölçüm: yoğun yazıda 400×150 ≈ 250 ms,
#                            640×400 ≈ 700 ms; ek süre ~300 ms'yi aşmasın)


def yeni_metin_uygun(d: dict) -> bool:
    """fark() sonucu için değişen bölgenin OCR'ı yapılsın mı (küçük ve ucuz mu)?"""
    w, h = d["region"][2:]
    return d["ratio"] <= KUCUK_ORAN and 16 <= w and 10 <= h and w * h <= YENI_METIN_ALAN


class Once:
    """Bir ekran görüntüsünün küçük gri kopyası (yarı çözünürlük) + özgün boyut."""
    __slots__ = ("gri", "boyut")

    def __init__(self, gri: np.ndarray, boyut: tuple[int, int]):
        self.gri, self.boyut = gri, boyut


def once_al(im) -> Once:
    """PIL görüntüsü → Once (≈ birkaç ms; tam ekran 1080p ~5 ms)."""
    return Once(np.asarray(ImageOps.grayscale(im).reduce(2), dtype=np.uint8), tuple(im.size))


def fark(a: Once, b: Once) -> dict | None:
    """İki görüntü arasındaki anlamlı değişiklik. → None (yok / yalnız imleç gürültüsü) ya da
    {"region": [x, y, w, h] (piksel, özgün çözünürlük), "ratio": 0..1 (sınır kutusu alanı / görüntü alanı)}.
    Boyut değiştiyse tüm alan değişmiş sayılır."""
    W, H = b.boyut
    if a.boyut != b.boyut or a.gri.shape != b.gri.shape:
        return {"region": [0, 0, W, H], "ratio": 1.0}
    m = np.abs(a.gri.astype(np.int16) - b.gri) > ESIK
    n = int(m.sum())
    if n == 0:
        return None
    satir, sutun = m.any(1), m.any(0)
    y0, y1 = int(np.argmax(satir)), len(satir) - int(np.argmax(satir[::-1]))
    x0, x1 = int(np.argmax(sutun)), len(sutun) - int(np.argmax(sutun[::-1]))
    if n <= IMLEC_EN_COK and (x1 - x0) <= IMLEC_GENISLIK:
        return None  # yanıp sönen yazı imleci
    x, y = x0 * 2, y0 * 2
    w, h = min(W, x1 * 2) - x, min(H, y1 * 2) - y
    return {"region": [x, y, w, h], "ratio": round(min(1.0, (w * h) / max(1, W * H)), 4)}


def ayni_ekran(a: Once | None, b: Once | None) -> bool:
    """İki görüntü anlamlı biçimde aynı mı (döngü kesici: 'ekran değişti mi')? Biri yoksa False."""
    return a is not None and b is not None and fark(a, b) is None
