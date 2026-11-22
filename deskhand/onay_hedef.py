"""Onay verilen hedefin özeti: insan onayı beklenirken hedef değişirse onay GEÇERSİZDİR (docs/ARCHITECTURE.md §8).

Onay isteğinden HEMEN ÖNCE (girdi kilidi tutulurken) `yakala(k, bolge)`; izin geldikten sonra, eylemden önce yine
kilit altında `dogrula(h)` → None (aynı) | neden (değişti: eylem YAPILMAZ, Dur 10 "yeniden onay gerekir").
Karşılaştırılan: pencere kimliği hâlâ var mı, başlık, geometri ve — görüntü alındıysa — onay isteğine giden hedef
görüntüsünün kırpıldığı bölgenin gri küçük kopyası (fark.py: eşikli, yanıp sönen yazı imleci gürültü sayılmaz).

Arka uç = geçerli iş parçacığına sabitlenmiş hedef (arka_uc.sec). Görüntü almak kde'de pencereyi öne getirir; odak
çalmaması gereken yollar (`goruntu=False`) yalnız kimlik + başlık + geometri karşılaştırır."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import fark
from .arka_uc import EKRAN, sec
from .hata import Dur
from .i18n import _

ONAY_GORUNTU = (480, 200)  # guvenlik.ONAY_GORUNTU ile aynı: tıklama noktasının çevresi (pencere pikseli)
YENIDEN_DENE = (0.0, 0.15, 0.3)  # görüntü farkı görülürse bu aralıklarla yeniden bakılır (kalıcı değişiklik = ret)


@dataclass
class OnayHedefi:
    k: str                          # pencere kimliği (EKRAN = masaüstü kipi)
    masaustu: str                   # arka uç adı: "kde" | "sanal"
    baslik: str                     # onaydan önceki başlık
    geometri: tuple | None          # (x, y, g, y) ekran pikseli
    bolge: tuple | None = None      # karşılaştırılan bölge (pencere pikseli x, y, g, y); None = tüm pencere
    ozet: fark.Once | None = field(default=None, repr=False)  # bölgenin gri küçük kopyası (görüntü alınmadıysa None)
    zaman: float = field(default_factory=time.monotonic)


def nokta_bolgesi(nokta, boyut=ONAY_GORUNTU) -> tuple[int, int, int, int]:
    """Tıklama noktası (pencere pikseli) → onay görüntüsünün kırpıldığı bölge (guvenlik.hedef_goruntusu ile aynı)."""
    x, y = round(nokta[0]), round(nokta[1])
    gw, gh = boyut
    return (x - gw // 2, y - gh // 2, gw, gh)


def _durum(k: str):
    au = sec()
    if k == EKRAN:
        x0, y0, x1, y1 = au.ekran_alani()
        return au.ad, "", (x0, y0, x1 - x0, y1 - y0)
    return au.ad, au.baslik(k), tuple(au.geometri(k))


def _goruntu(k: str, bolge):
    from .gorsel import pencere_goruntusu
    im, _geo, kok = pencere_goruntusu(k, bolge)
    if bolge is not None:  # pencere kenarında kırpılmış olabilir: gerçek bölge = kök + görüntü boyutu
        bolge = (kok[0], kok[1], im.width, im.height)
    return fark.once_al(im), bolge


def yakala(k: str, bolge=None, goruntu: bool = True) -> OnayHedefi:
    """Onay isteğinden önce hedefin özeti. bolge: (x, y, g, y) pencere pikseli (None = tüm pencere).
    Görüntü alınamazsa (ör. pencere o an etkin değil) yalnız kimlik/başlık/geometri tutulur. Pencere yoksa Dur 8."""
    ad, baslik, geo = _durum(k)
    h = OnayHedefi(k=k, masaustu=ad, baslik=baslik, geometri=geo, bolge=tuple(bolge) if bolge else None)
    if goruntu:
        try:
            h.ozet, h.bolge = _goruntu(k, h.bolge)
        except Dur:
            h.ozet = None
    return h


def dogrula(h: OnayHedefi | None) -> str | None:
    """Onaydan sonra (kilit altında, eylemden önce): hedef onaylanan hâlinde mi? → None | neden (kullanıcıya/ajana)."""
    if h is None:
        return None
    try:
        ad, baslik, geo = _durum(h.k)
    except Dur:
        return _("pencere kapandı ya da taşındı")
    if ad != h.masaustu:
        return _("hedef masaüstü değişti")
    if baslik != h.baslik:
        return _("pencere başlığı değişti ({once} → {sonra})").format(once=repr(h.baslik)[:80], sonra=repr(baslik)[:80])
    if geo != h.geometri:
        return _("pencere taşındı ya da boyutu değişti")
    if h.ozet is not None:
        d = None
        for bekle in YENIDEN_DENE:  # geçici örtü (kapanmakta olan onay diyaloğunun solma animasyonu) gürültü sayılmaz
            if bekle:
                time.sleep(bekle)
            try:
                yeni, _bolge = _goruntu(h.k, h.bolge)
            except Dur as e:
                return _("hedef yeniden görüntülenemedi ({hata})").format(hata=e.mesaj)
            d = fark.fark(h.ozet, yeni)
            if d is None:
                return None
        return _("onaylanan bölgenin görüntüsü değişti (değişen alan {bolge})").format(bolge=d["region"])
    return None


def dogrula_dur(h: OnayHedefi | None) -> None:
    """dogrula + değiştiyse Dur(10, tur="hedef-degisti"): eylem yapılmaz, yeniden onay gerekir."""
    neden = dogrula(h)
    if neden:
        e = Dur(10, _("onay verilen hedef değişti; yeniden onay gerekir ({neden}). Eylem yapılmadı.").format(neden=neden))
        e.tur = "hedef-degisti"
        raise e
