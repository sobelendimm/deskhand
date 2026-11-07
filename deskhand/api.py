"""İnce iç API: CLI'nin metin çıktısı yerine yapılandırılmış sonuç (sözlük) döner. MCP sunucusu (mcp_sunucu.py)
bunu kullanır; mantık YAZMAZ, eylem/ocr/gorsel/akis/erisim/uygulama komutlarını argparse olmadan çağırır.

- Arka uç seçimi çağrı başına: `hedef("kde"|"sanal")` bağlamı (arka_uc.hedef_sabit, iş parçacığına özgü). Süreç
  içinde eşzamanlı çağrılar DESKHAND_HEDEF ortam değişkenini paylaşmaz.
- Komutların print() çıktısı iş parçacığına özgü yakalanır (`yakala`); Dur fırlarsa yakalanan metin `e.cikti`.
- Güvenlik katmanları komutların içindedir (yasak, hassas, başlık kilidi, DUR, insan önceliği): burada AYNEN
  çağrılır. Onay (--onayli) burada yalnız parametredir; kararı çağıran (MCP: insan onayı) verir.
- Ek gizlilik: yasak pencereler görüntüde siyah kutuyla maskelenir ve OCR sonucundan çıkarılır (goruntu_al).
- Açık girdi nesneleri kayıtlıdır (`acik_girdiler`): kapanışta basılı tuş/fare bırakılır (`hepsini_birak`).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import shlex
import shutil
import sys
import threading
import time
import weakref
from contextlib import contextmanager

from PIL import Image, ImageDraw

from . import yollar
from .arka_uc import ARKA_ONEK, EKRAN, hedef_sabit, sec
from .hata import Dur
from .i18n import _

ONAY_YASAK = ()  # onay diyaloğu/panel pencereleri (onay.YASAK_DESENLER): yoksa boş
try:
    from .onay import YASAK_DESENLER as ONAY_YASAK  # noqa: F811
except ImportError:  # panel modülü yoksa
    pass

# ---------------------------------------------------------------- çıktı yakalama (iş parçacığına özgü)

_YEREL = threading.local()


class _Bolucu:
    """sys.stdout/sys.stderr yerine: bu iş parçacığında yakalama açıksa tampona, değilse asıl akışa yazar."""

    def __init__(self, asil, ad):
        self._asil, self._ad = asil, ad

    def _hedef(self):
        t = getattr(_YEREL, self._ad, None)
        return t if t is not None else self._asil

    def write(self, s):
        return self._hedef().write(s)

    def flush(self):
        try:
            self._hedef().flush()
        except (AttributeError, ValueError):
            pass

    def __getattr__(self, ad):
        return getattr(self._asil, ad)


def yakalayici_kur():
    """sys.stdout/sys.stderr'i iş parçacığına özgü bölücüyle sar (bir kez; süreç başında)."""
    if not isinstance(sys.stdout, _Bolucu):
        sys.stdout = _Bolucu(sys.stdout, "out")
    if not isinstance(sys.stderr, _Bolucu):
        sys.stderr = _Bolucu(sys.stderr, "err")


@contextmanager
def yakala():
    """Bu iş parçacığının print() çıktısını topla → StringIO (stdout + stderr birlikte, sırayla)."""
    yakalayici_kur()
    tampon = io.StringIO()
    once = (getattr(_YEREL, "out", None), getattr(_YEREL, "err", None))
    _YEREL.out = _YEREL.err = tampon
    try:
        yield tampon
    finally:
        _YEREL.out, _YEREL.err = once


def calistir(f, a) -> str:
    """Komut fonksiyonunu (k_*) çalıştır, yazdığı metni döndür. Dur'da metin e.cikti'ye eklenir."""
    with yakala() as t:
        try:
            f(a)
        except Dur as e:
            e.cikti = t.getvalue().strip()
            raise
    return t.getvalue().strip()


def ns(**kw) -> argparse.Namespace:
    """Komutların beklediği argparse ad alanı (ortak varsayılanlar + verilenler)."""
    a = argparse.Namespace(baslik=None, sinif=None, onayli=False, bolge=None, sira=None, dugme="sol", kal=True)
    for k, v in kw.items():
        setattr(a, k, v)
    if hasattr(a, "kimlik") and not hasattr(a, "kimlik_ham"):
        a.kimlik_ham = a.kimlik
    return a


# ---------------------------------------------------------------- arka uç + girdi kaydı

acik_girdiler: "weakref.WeakSet" = weakref.WeakSet()
_kayit_kilit = threading.Lock()


@contextmanager
def hedef(ad: str):
    """Bu çağrı boyunca arka uç: "kde" (kullanıcının ekranı) | "sanal" (görünmez masaüstü)."""
    with hedef_sabit(ad):
        yield


def arka():
    """Geçerli hedefin arka ucu; girdi nesneleri kapanışta bırakılmak üzere kaydedilir."""
    au = sec()
    with _kayit_kilit:
        if not getattr(au, "_api_sarili", False):
            asil = au.girdi

            def girdi(*a, **k):
                g = asil(*a, **k)
                try:
                    acik_girdiler.add(g)
                except TypeError:  # zayıf başvuru desteklemeyen nesne: kaydedilemez
                    pass
                return g
            au.girdi = girdi
            au._api_sarili = True
    return au


def hepsini_birak(sure: float = 0.4) -> int:
    """Açık her girdi nesnesini kapat (basılı tuş/fare düğmeleri bırakılır). En çok `sure` sn bekler."""
    girdiler = list(acik_girdiler)
    ipler = []
    for g in girdiler:
        def birak(g=g):
            try:
                hb = getattr(g, "_hepsini_birak", None)  # sanal: bırakma anında, bağlantı kapanmadan
                if hb:
                    hb()
                g.kapat()
            except Exception:  # noqa: BLE001 - kapanışta her şey denenir
                pass
        t = threading.Thread(target=birak, daemon=True)
        t.start()
        ipler.append(t)
    bitis = time.monotonic() + sure
    for t in ipler:
        t.join(max(0.0, bitis - time.monotonic()))
    return len(girdiler)


# ---------------------------------------------------------------- pencere

def pencere(arg: str | None) -> str:
    """Pencere kimliği (başlık deseni / kimlik / None = tüm ekran)."""
    if arg is None or str(arg).strip().lower() in ("", "ekran", "screen", "desktop", "masaustu", "masaüstü"):
        return EKRAN
    au = arka()
    if au.ad == "kde" and str(arg).startswith(ARKA_ONEK):
        raise Dur(8, _("'{pencere}' görünmez masaüstünün penceresi; desktop='background' ile kullan").format(pencere=arg))
    return au.pencere_coz(arg)


def pencere_bilgi(k: str) -> dict:
    au = arka()
    if k == EKRAN:
        x0, y0, x1, y1 = au.ekran_alani()
        return {"id": "screen", "title": "", "class": "", "geometry": [x0, y0, x1 - x0, y1 - y0]}
    return {"id": k, "title": au.baslik(k), "class": au.sinif(k), "geometry": list(au.geometri(k))}


def yasak_mi(k: str) -> str | None:
    """Pencere yasak listede mi (guvenlik.yasak_denetle + onay/panel pencereleri) → eşleşen desen / None."""
    if not k or k == EKRAN:
        return None
    from .guvenlik import yasak_denetle
    au = arka()
    try:
        yasak_denetle(k)
    except Dur as e:
        if e.kod == 10:
            return e.mesaj
        raise
    b, s = au.baslik(k), au.sinif(k)
    for d in ONAY_YASAK:
        if re.search(d, b, re.I) or re.search(d, s, re.I):
            return _("Deskhand onay/panel penceresi /{desen}/").format(desen=d)
    return None


def pencereler(desen: str | None = None) -> list[dict]:
    au = arka()
    sonuc = []
    for k, b, geo in au.pencereler(desen):
        try:
            y = yasak_mi(k)
        except Dur:
            continue
        sonuc.append({"id": k, "title": "(yasak pencere)" if y else b, "class": "" if y else au.sinif(k),
                      "geometry": list(geo), "forbidden": bool(y)})
    return sonuc


# ---------------------------------------------------------------- görüntü (maskeli)

def _yasak_dikdortgenler(k: str, kok_ekran: tuple[int, int], boyut: tuple[int, int]) -> list[dict]:
    """Görüntüye düşen yasak pencerelerin kutuları (görüntü pikseli, ölçeksiz)."""
    au = arka()
    sonuc = []
    ox, oy = kok_ekran
    W, H = boyut
    for w, b, (X, Y, G, Yk) in au.pencereler():
        if w == k:
            continue
        try:
            y = yasak_mi(w)
        except Dur:
            continue
        if not y:
            continue
        x0, y0 = max(0, X - ox), max(0, Y - oy)
        x1, y1 = min(W, X - ox + G), min(H, Y - oy + Yk)
        if x1 > x0 and y1 > y0:
            sonuc.append({"id": w, "box": [x0, y0, x1 - x0, y1 - y0]})
    return sonuc


def goruntu_al(k: str, bolge=None):
    """→ (görüntü, geo, kök, maskeler). Görüntü pikseli + kök = pencere koordinatı. Hedef yasaksa Dur(10);
    görüntüye düşen diğer yasak pencereler siyah kutuyla örtülür (maskeler: görüntü pikseli)."""
    from .gorsel import pencere_goruntusu
    y = yasak_mi(k)
    if y:
        raise Dur(10, _("YASAK pencere: içeriği gösterilmez/okunmaz ({neden})").format(neden=y))
    bolge_s = ",".join(str(int(v)) for v in bolge) if bolge else None
    from .gorsel import bolge_coz
    im, geo, kok = pencere_goruntusu(k, bolge_coz(bolge_s))
    au = arka()
    sx0, sy0, *_x = au.ekran_alani()
    kok_ekran = (geo[0] + kok[0], geo[1] + kok[1]) if k != EKRAN else (sx0 + kok[0], sy0 + kok[1])
    maskeler = _yasak_dikdortgenler(k, kok_ekran, im.size)
    if maskeler:
        im = im.copy()
        d = ImageDraw.Draw(im)
        for m in maskeler:
            x, y_, g, h = m["box"]
            d.rectangle([x, y_, x + g - 1, y_ + h - 1], fill=(0, 0, 0))
    return im, geo, kok, maskeler


def olcek_hesapla(w: int, h: int, uzun_kenar: int = 1280) -> float:
    """Anthropic görüntü sınırı: ölçek = min(1, uzun_kenar/max(w,h), sqrt(1.15 MP / (w*h)))."""
    return min(1.0, uzun_kenar / max(w, h), (1_150_000 / (w * h)) ** 0.5)


def ozet(im) -> str:
    return hashlib.blake2b(im.tobytes(), digest_size=8).hexdigest()


@contextmanager
def okuma(k: str):
    """Okuma (öne getirir): bitince hedef hâlâ öndeyse önceki pencere geri gelir (CLI ile aynı)."""
    au = arka()
    onceki = au.aktif() if k != EKRAN else ""
    try:
        yield
    finally:
        try:
            if onceki and onceki != k and au.aktif() == k:
                getattr(au, "etkinlestir", au.one_getir)(onceki)
        except Dur:
            pass


# ---------------------------------------------------------------- okuma

def _satir(s: dict) -> dict:
    return {"text": s["t"], "box": [round(s["x"]), round(s["y"]), round(s["x2"] - s["x"]), round(s["y2"] - s["y"])],
            "center": [round(s["cx"]), round(s["cy"])], "conf": round(float(s["conf"]))}


def metin_oku(k: str, sorgu: str | None = None, bolge=None, derin: bool = False, hepsi: bool = False,
              bekle: float = 0.0, en_cok: int = 80) -> dict:
    """OCR (Türkçe). → {items: [{text, box (pencere pikseli), center, conf}], truncated, window, redacted}.
    sorgu: yalnız eşleşen parçalar; bekle: sorgu görünene dek en çok bu kadar sn."""
    from .ocr import (KUCUK_BOLGE, KUCUK_OKUMALAR, ara, derin_oku, gpu_ekle, gurultu_mu, kok_ekle, oku, satirla,
                      yedek_ara)
    from .ocr_gpu import SOGUK_SN
    t0 = time.monotonic()
    bitis = t0 + max(0.0, bekle)
    with okuma(k):
        while True:
            im, geo, kok, maskeler = goruntu_al(k, bolge)
            if derin:
                satirlar = derin_oku(im)
            elif im.size[0] <= KUCUK_BOLGE[0] and im.size[1] <= KUCUK_BOLGE[1]:
                satirlar = derin_oku(im, KUCUK_OKUMALAR, gpu_bekle=0.0)
            elif sorgu:
                satirlar = satirla(oku(im))  # arama: bulunamazsa yedek_ara (ekran kartı + tesseract yedekleri)
            else:
                # liste: tesseract + ekran kartı satırları (yalnız eklenir; tesseract satırı değişmez)
                satirlar = gpu_ekle(satirla(oku(im)), satirla(oku(im, motor="gpu", bekle=SOGUK_SN)))
            if sorgu:
                bulunan = ara(satirlar, sorgu) or yedek_ara(im, sorgu)
            else:
                bulunan = satirlar if hepsi else [s for s in satirlar if not gurultu_mu(s)]
            if bulunan or not sorgu or time.monotonic() >= bitis:
                break
            time.sleep(0.25)
    def maskede(s):
        return any(m["box"][0] <= s["cx"] < m["box"][0] + m["box"][2] and m["box"][1] <= s["cy"] < m["box"][1] + m["box"][3]
                   for m in maskeler)
    bulunan = [kok_ekle(s, kok) for s in bulunan if not maskede(s)]
    ogeler = [_satir(s) for s in bulunan]
    return {"items": ogeler[:en_cok], "truncated": len(ogeler) > en_cok, "geometry": list(geo),
            "redacted": len(maskeler), "seconds": round(time.monotonic() - t0, 2)}


def agac_oku(k: str, sorgu: str | None = None, hepsi: bool = False, en_cok: int = 80) -> dict:
    """Erişilebilirlik ağacı (AT-SPI): {items: [{text, role, box, center, enabled}]}."""
    from .erisim import ETKILESIMLI, erisim_ara, erisim_ogeleri
    if yasak_mi(k):
        raise Dur(10, _("YASAK pencere: ağacı okunmaz"))
    ogeler, sure = erisim_ogeleri(k)
    if sorgu:
        secili, _kademe = erisim_ara(ogeler, sorgu)
    else:
        secili = [o for o in ogeler if hepsi or o["rol"] in ETKILESIMLI or (o["ad"] and o["rol"] == "label")]
    sonuc = [{"text": o["ad"], "role": o["rol"], "box": [round(o["x"]), round(o["y"]), round(o["w"]), round(o["h"])],
              "center": [round(o["cx"]), round(o["cy"])], "enabled": bool(o["etkin"])} for o in secili]
    return {"items": sonuc[:en_cok], "truncated": len(sonuc) > en_cok, "seconds": round(sure, 2)}


def simge_bul(k: str, ad: str, esik: float = 0.9, bolge=None) -> dict:
    from .gorsel import simge_bul_ic
    if yasak_mi(k):
        raise Dur(10, _("YASAK pencere: içeriği okunmaz"))
    with okuma(k):
        kesin, yakin, geo = simge_bul_ic(ns(kimlik=k, ad=ad, esik=esik,
                                            bolge=",".join(map(str, bolge)) if bolge else None))
    return {"matches": [{"center": [round(cx), round(cy)], "score": round(sk, 3)} for sk, cx, cy in kesin],
            "near": [{"center": [round(cx), round(cy)], "score": round(sk, 3)} for sk, cx, cy in yakin],
            "geometry": list(geo)}


def renk_bul(k: str, renk: str, en_az: int = 250, bolge=None) -> dict:
    from .gorsel import renk_alanlari
    with okuma(k):
        im, geo, kok, _maske = goruntu_al(k, bolge)
    alanlar = renk_alanlari(im, renk, en_az)
    return {"matches": [{"center": [round(cx + kok[0]), round(cy + kok[1])], "area": alan,
                         "box": [x0 + kok[0], y0 + kok[1], x1 - x0 + 1, y1 - y0 + 1]}
                        for alan, cx, cy, (x0, y0, x1, y1) in alanlar[:20]], "geometry": list(geo)}


# ---------------------------------------------------------------- eylemler (CLI komutları, argparse'sız)

DUGME = {"left": "sol", "right": "sag", "middle": "orta", "double": "cift"}
YON = {"up": "yukari", "down": "asagi", "left": "sol", "right": "sag"}


def metne_tikla(k, metin, dugme="left", sira=None, bekle=0.0, kaydirarak=0, baslik=None, onayli=False, bolge=None,
                kay=None) -> str:
    from .eylem import k_metne_tikla
    return calistir(k_metne_tikla, ns(kimlik=k, metin=metin, dugme=DUGME[dugme], sira=sira, bekle=bekle,
                                      kaydirarak=kaydirarak, baslik=baslik, onayli=onayli,
                                      bolge=",".join(map(str, bolge)) if bolge else None,
                                      kay=f"{int(kay[0])},{int(kay[1])}" if kay else None))


def tikla(k, x, y, dugme="left", baslik=None, onayli=False, tekrar=1) -> str:
    from .eylem import k_tikla
    return calistir(k_tikla, ns(kimlik=k, x=float(x), y=float(y), dugme=DUGME[dugme], foto=False, onayli=onayli,
                                basili=0.0, tekrar=tekrar, baslik=baslik))


def simgeye_tikla(k, ad, dugme="left", sira=None, esik=0.9, baslik=None, onayli=False) -> str:
    from .eylem import k_simgeye_tikla
    return calistir(k_simgeye_tikla, ns(kimlik=k, ad=ad, dugme=DUGME[dugme], sira=sira, esik=esik, baslik=baslik,
                                        onayli=onayli))


def ogeye_tikla(k, ad, dugme="left", sira=None, baslik=None, onayli=False) -> str:
    from .erisim import k_ogeye_tikla
    return calistir(k_ogeye_tikla, ns(kimlik=k, ad=ad, dugme=DUGME[dugme], rol=None, sira=sira, baslik=baslik,
                                      onayli=onayli))


def yaz(k, metin, baslik=None, gizli=False, onayli=False) -> str:
    from .eylem import k_yaz
    return calistir(k_yaz, ns(kimlik=k, metin=metin, gizli=gizli, baslik=baslik, onayli=onayli))


def tus(k, kombinasyon, baslik=None, onayli=False) -> str:
    from .eylem import k_tus
    return calistir(k_tus, ns(kimlik=k, kombinasyon=kombinasyon, baslik=baslik, onayli=onayli))


def bas(k, tuslar, sure, baslik=None, onayli=False) -> str:
    from .eylem import k_bas
    return calistir(k_bas, ns(kimlik=k, tuslar=tuslar, sure=float(sure), baslik=baslik, onayli=onayli))


def kaydir(k, yon="down", adim=3, nokta=None, baslik=None) -> str:
    from .eylem import k_kaydir
    return calistir(k_kaydir, ns(kimlik=k, yon=YON[yon], adim=int(adim), baslik=baslik,
                                 nokta=f"{int(nokta[0])},{int(nokta[1])}" if nokta else None))


# ---------------------------------------------------------------- uygulama

def uygulama_komutu(uygulama: str, argumanlar: list[str] | None = None) -> tuple[list[str], str, list[str]]:
    """→ (argv, görünen ad, yasak denetimi için metinler). Önce .desktop girdisi, olmazsa çalıştırılabilir dosya."""
    from .uygulama import uygulama_bul
    argumanlar = list(argumanlar or [])
    if "/" not in uygulama and not argumanlar:
        try:
            g = uygulama_bul(uygulama)
            return ["gio", "launch", g["yol"]], f"{g['ad']} ({g['kimlik']})", [g["ad"], g["ad_en"], g["exec"], g["kimlik"]]
        except Dur as e:
            if e.kod != 6 or not shutil.which(uygulama):
                raise
    yol = uygulama if os.path.isfile(uygulama) else shutil.which(uygulama)
    if not yol:
        raise Dur(6, _("'{uygulama}' bulunamadı (.desktop girdisi ya da çalıştırılabilir dosya değil)").format(
            uygulama=uygulama))
    argv = [yol, *argumanlar]
    return argv, shlex.join(argv), [shlex.join(argv)]


def uygulama_ac(argv: list[str], ad: str, yasak_metinleri: list[str], env: dict | None = None,
                baslik: str | None = None, sure: float = 15.0) -> dict:
    """Uygulamayı GEÇERLİ hedefte başlat, YENİ penceresini bekle (uygulama.k_ac ile aynı döngü; ek: env).
    Yasak uygulama başlatılmaz (10)."""
    from .gunluk import gunluk
    from .guvenlik import baslatma_yasak_denetle
    from .uygulama import tum_pencereler
    baslatma_yasak_denetle(*yasak_metinleri, *argv)
    au = arka()
    once = tum_pencereler()
    os.makedirs(yollar.cikti(), exist_ok=True)
    log = os.path.join(yollar.cikti(), f"ac-{time.strftime('%H%M%S')}-{os.getpid()}.log")
    with open(log, "w") as fp:
        try:
            au.baslat(argv, env=env, cikti=fp)
        except TypeError:  # cikti desteklemeyen arka uç
            au.baslat(argv, env=env)
    gunluk(f"ac | {ad} | {shlex.join(argv)}" + (f" | env {sorted(env)}" if env else ""))
    t0 = time.monotonic()
    while time.monotonic() - t0 < sure:
        time.sleep(0.25)
        for w in tum_pencereler() - once:
            b, s = au.baslik(w), au.sinif(w)
            if (b or s) and (not baslik or re.search(baslik, b, re.I)):
                y = yasak_mi(w)
                return {"status": "opened", "window": {"id": w, "title": "(yasak pencere)" if y else b,
                                                       "class": s, "forbidden": bool(y)},
                        "seconds": round(time.monotonic() - t0, 1)}
    return {"status": "timeout", "window": None, "seconds": round(time.monotonic() - t0, 1),
            "message": _("{sn} sn içinde yeni pencere görünmedi (çıktı: {log})").format(sn=f"{sure:.0f}", log=log)}


# ---------------------------------------------------------------- akışlar

def akislar() -> list[dict]:
    d = yollar.akis_dizin()
    sonuc = []
    try:
        adlar = sorted(f for f in os.listdir(d) if f.endswith(".akis"))
    except OSError:
        return []
    for f in adlar:
        aciklama = ""
        try:
            with open(os.path.join(d, f)) as fp:
                icerik = fp.read()
            ilk = next((l for l in icerik.splitlines() if l.strip()), "")
            aciklama = ilk.lstrip("# ").strip() if ilk.lstrip().startswith("#") else ""
        except OSError:
            icerik = ""
        sonuc.append({"name": f[:-5], "description": aciklama[:200],
                      "needs_approval": bool(icerik) and bool(akis_onayli_adimlar(os.path.join(d, f)))})
    return sonuc


def akis_yolu(ad: str) -> str:
    if not re.fullmatch(r"[\w.-]+", ad or "") or ad.startswith("."):
        raise Dur(1, _("akış adı yalnız harf/rakam/._- içermeli: {ad} (list ile adlara bak)").format(ad=repr(ad)))
    yol = os.path.join(yollar.akis_dizin(), ad if ad.endswith(".akis") else ad + ".akis")
    if not os.path.isfile(yol):
        raise Dur(6, _("akış yok: {ad} ({dizin})").format(ad=ad, dizin=yollar.akis_dizin()))
    return yol


def akis_onayli_adimlar(yol: str) -> list[str]:
    """Akışın önceden onaylı (--onayli/--approved) adımları (ayrıştırılarak; alt dize değil). Okunamazsa []."""
    from .akis import onayli_adimlar
    try:
        return onayli_adimlar(yol)
    except Dur:
        return []


def akis_calistir(k: str, ad: str, sure: float | None = None, baslik: str | None = None,
                  onayli_izin: bool = False) -> str:
    """onayli_izin=False: akışta --onayli adım çalışırsa Dur 10 (kullanıcı o akışın onaylı adımlarını onaylamadı;
    ön taramadan sonra dosya değişmiş olsa bile)."""
    from .akis import k_akis
    return calistir(k_akis, ns(kimlik=k, kimlik_ham=k, dosya=akis_yolu(ad), sure=sure, baslik=baslik,
                               onayli_izin=onayli_izin))
