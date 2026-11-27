#!/usr/bin/env python3
"""Tasarım kalite kapısı + hızlı önizleme panosu (UX-Q1).

Paneli (tüm sekmeler) ve onay diyaloğunu (3 tür) ekransız (offscreen, Fusion) kurar, widget ağacını gezer ve
tasarım kurallarını denetler:
  KESIK        metin sığmıyor (etiket/düğme/sekme/açılır kutu metni kesik ya da kırpılmış)
  HEDEF_KUCUK  tıklama hedefi < hedef_min × hedef_min
  YAZI_BOYUTU  yazı boyutu token ölçeği dışında
  QSS_RENK     QSS rengi token paleti dışında
  KONTRAST     metin/zemin kontrastı < kontrast_min (WCAG 2)
  ARALIK       düzen kenar/boşluk değeri aralık biriminin katı değil
  DOYGUNLUK    aynı ekranda >1 yüksek doygun vurgu rengi (HSL S ≥ s_min, l_min ≤ L ≤ l_max; tokens.json `doygunluk`)
  UYUM         koyu paletin vurgu/uyarı/başarı/tehlike + durum şeridi renkleri arası CIEDE2000 < renk_ayrim_min_de ya da
               biri koyu zemine (Window) kontrastı < 3:1 (WCAG 1.4.11 grafik öğe)
Eşikler token dosyasından okunur (esikler(): `min_tiklama_hedefi_px`, `kontrast_min`, aralık, yazı, palet); dosyada
eşik yoksa token şemasının varsayılanı (gui/tema/uret.VARSAYILAN: 24 px — WCAG 2.5.8, 4,5:1 — WCAG 1.4.3).

Kullanım:
  python3 tools/tasarim_kapi.py [--json] [--pano OUT.png] [--tokens PATH] [--kip acik|koyu]
                                [--bilinen PATH] [--bilinen-yaz]
Çıkış: 0 = ihlal yok ya da yalnız bilinen (tests/tasarim_bilinen.json), 1 = yeni ihlal, 2 = kullanım/çalışma hatası.
--pano: tüm ekranlar tek PNG (magick montage → ≤1600 px uzun kenar → pngquant + oxipng).
Gerçek ~/.config/deskhand'e dokunmaz: geçici HOME/XDG + tests/_yalitim (DESKHAND_* geçici klasörler)."""
from __future__ import annotations

import time

_T0 = time.perf_counter()

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTLER = os.path.join(KOK, "tests")
TOKENS = os.path.join(KOK, "deskhand", "gui", "tema", "tokens.json")
BILINEN = os.path.join(TESTLER, "tasarim_bilinen.json")
PANO_KENAR = 1600
KURALLAR = ("KESIK", "HEDEF_KUCUK", "YAZI_BOYUTU", "QSS_RENK", "KONTRAST", "ARALIK", "DOYGUNLUK", "UYUM")
DOYGUN_MIN_PX = 40  # bir vurgu "görünür" sayılması için en az piksel (kenar yumuşatma kırıntısı sayılmaz)
GRAFIK_KONTRAST_MIN = 3.0  # WCAG 1.4.11 (grafik öğe / durum rengi ↔ zemin)
# UYUM kuralının denetlediği roller: (ad, kaynak) — koyu palet Highlight + durum şeridi/uyarı renkleri
UYUM_ROLLER = (("vurgu", ("renk", "koyu", "palet", "Highlight")), ("uyari", ("durum", "uyari")),
               ("basari", ("durum", "basari")), ("tehlike", ("durum", "hata")), ("dur", ("durum", "dur")),
               ("bos", ("durum", "bos")), ("ekran", ("durum", "ekran")), ("arka", ("durum", "arka")))
_HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_QSS_RENK = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b[a-zA-Z]+\b")
_RENK_OZELLIK = ("color", "background", "border", "outline", "selection")
_RENK_DISI = {"transparent", "none", "solid", "dashed", "dotted", "inherit", "palette"}


# =========================================================================== eşikler
def _sayi(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _renkleri_topla(d, cik: set, anahtar: str = "") -> None:
    if anahtar in ("$aciklama", "aciklama", "kontrast"):
        return
    if isinstance(d, dict):
        for k, v in d.items():
            _renkleri_topla(v, cik, k)
    elif isinstance(d, list):
        for v in d:
            _renkleri_topla(v, cik)
    elif isinstance(d, str) and _HEX.fullmatch(d.strip()):
        cik.add(_renk_ad(d.strip()))


def _renk_ad(v: str) -> str:
    """#rgb/#rrggbb/#aarrggbb (Qt) → #rrggbb (alfa atılır; paletteki rengin yarı saydamı da palet içidir)."""
    from PyQt6.QtGui import QColor
    return QColor(v).name().lower()


def esikler(ham: dict, temel_pt: float) -> dict:
    """Token dosyası (tokens.json ya da tasarım token biçimi: yazi_pt/aralik_px/min_tiklama_hedefi_px) → eşikler.
      hedef_min     min_tiklama_hedefi_px | WCAG 24
      kontrast_min  kontrast_min | WCAG 4,5
      aralik_birim  aralik_px değerlerinin EBOB'u | aralik.* değerlerinin EBOB'u
      yazi_pt       yazi_pt.* (mutlak pt) | temel_pt × {1, yazi.*_olcek}
      palet         dosyadaki bütün renkler (#rrggbb)"""
    if isinstance(ham.get("aralik_px"), list):
        aralik = [int(v) for v in ham["aralik_px"] if _sayi(v)]
    else:
        aralik = [int(v) for v in (ham.get("aralik") or {}).values() if _sayi(v)]
    birim = math.gcd(*aralik) if aralik else 1
    if isinstance(ham.get("yazi_pt"), dict):
        yazi = sorted({float(v) for k, v in ham["yazi_pt"].items() if _sayi(v) and k != "satir_yuksekligi"})
    else:
        yazi = sorted({temel_pt} | {temel_pt * float(v) for k, v in (ham.get("yazi") or {}).items()
                                    if k.endswith("_olcek") and _sayi(v)})
    palet: set = set()
    _renkleri_topla(ham, palet)
    from deskhand.gui.tema.uret import VARSAYILAN  # eksik eşik → token şemasının varsayılanı (WCAG 24 px / 4,5)
    hedef, kontrast = ham.get("min_tiklama_hedefi_px"), ham.get("kontrast_min")
    de = ham.get("renk_ayrim_min_de")
    doy = dict(VARSAYILAN["doygunluk"])
    doy.update({k: float(v) for k, v in (ham.get("doygunluk") or {}).items() if k in doy and _sayi(v)})
    return {"hedef_min": int(hedef if _sayi(hedef) and hedef > 0 else VARSAYILAN["min_tiklama_hedefi_px"]),
            "kontrast_min": float(kontrast if _sayi(kontrast) and kontrast > 0 else VARSAYILAN["kontrast_min"]),
            "aralik_birim": max(1, birim), "yazi_pt": yazi, "palet": palet,
            "renk_ayrim_min_de": de if _sayi(de) and de > 0 else VARSAYILAN["renk_ayrim_min_de"], "doygunluk": doy}


# =========================================================================== denetim
def _yol(w, kok) -> str:
    parca = []
    while w is not None:
        ad = w.objectName()
        if ad:
            parca.append(f"{type(w).__name__}#{ad}")
        else:
            ebeveyn = w.parentWidget()
            kardes = [c for c in (ebeveyn.findChildren(type(w)) if ebeveyn else [])
                      if c.parentWidget() is ebeveyn and type(c) is type(w)]
            parca.append(f"{type(w).__name__}[{kardes.index(w) if w in kardes else 0}]")
        if w is kok:
            break
        w = w.parentWidget()
    return "/".join(reversed(parca))


def _duz_metin(m: str) -> str:
    if re.search(r"<[a-zA-Z/][^>]*>|&[a-z]+;", m):  # Qt::mightBeRichText PyQt6'da yok
        from PyQt6.QtGui import QTextDocument
        d = QTextDocument()
        d.setHtml(m)
        return d.toPlainText()
    return m


def _metin(w) -> str:
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit
    if isinstance(w, QLabel):
        return _duz_metin(w.text())
    if isinstance(w, QAbstractButton):
        return w.text().replace("&", "")
    if isinstance(w, QComboBox):
        return w.currentText()
    if isinstance(w, QLineEdit):
        return w.text() or w.placeholderText()
    if isinstance(w, QGroupBox):
        return w.title()
    return ""


def _kesik(w) -> str | None:
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLabel, QStyle, QStyleOptionComboBox, QTabBar
    if isinstance(w, QLabel):
        m = _metin(w)
        if not m.strip() or (w.pixmap() is not None and not w.pixmap().isNull()):
            return None
        if w.wordWrap():
            gerek = w.heightForWidth(w.width())
            return f"yükseklik {w.height()} < {gerek}" if gerek > w.height() + 1 else None
        fm = w.fontMetrics()
        gerek = max(fm.horizontalAdvance(s) for s in m.splitlines() or [""])
        var = w.contentsRect().width() - 2 * w.margin() - max(0, w.indent())
        return f"genişlik {var} < {gerek}" if gerek > var + 1 else None
    if isinstance(w, QAbstractButton):
        if not w.text().strip():
            return None
        gerek = w.sizeHint().width()
        return f"genişlik {w.width()} < {gerek}" if gerek > w.width() + 1 else None
    if isinstance(w, QTabBar):
        from PyQt6.QtWidgets import QStyleOptionTab  # tabSizeHint/initStyleOption korumalı (PyQt6) → elle seçenek
        for i in range(w.count()):
            opt = QStyleOptionTab()
            opt.initFrom(w)
            opt.rect, opt.text, opt.shape = w.tabRect(i), w.tabText(i), w.shape()
            opt.icon, opt.iconSize = w.tabIcon(i), w.iconSize()
            alan = w.style().subElementRect(QStyle.SubElement.SE_TabBarTabText, opt, w).width()
            gerek = w.fontMetrics().horizontalAdvance(w.tabText(i).replace("&", ""))
            if gerek > alan + 1:
                return f"sekme {i} genişlik {alan} < {gerek}"
        return None
    if isinstance(w, QComboBox) and w.currentText():
        opt = QStyleOptionComboBox()
        w.initStyleOption(opt)
        alan = w.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt,
                                        QStyle.SubControl.SC_ComboBoxEditField, w).width()
        gerek = w.fontMetrics().horizontalAdvance(w.currentText())
        return f"genişlik {alan} < {gerek}" if gerek > alan + 1 else None
    return None


def _hedef(w):
    from PyQt6.QtWidgets import QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox, QLineEdit
    return isinstance(w, (QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit, QAbstractSlider))


def _metinli(w) -> bool:
    from PyQt6.QtWidgets import QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QTabBar
    if isinstance(w, QTabBar):
        return w.count() > 0
    return isinstance(w, (QLabel, QAbstractButton, QComboBox, QLineEdit, QGroupBox)) and bool(_metin(w).strip())


def _zemin(w):
    """Metnin gerçekten üstünde durduğu zemin: kendi zeminini boyayan (autoFill, QSS'li, düğme) ilk ata."""
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QAbstractButton
    o = w
    while o is not None:
        if o is w and isinstance(o, QAbstractButton):
            return o.palette().color(QPalette.ColorGroup.Active, o.backgroundRole())
        if o.autoFillBackground() or o.isWindow() or (o is w and o.styleSheet()):
            return o.palette().color(QPalette.ColorGroup.Active, o.backgroundRole())
        o = o.parentWidget()
    return w.palette().color(QPalette.ColorGroup.Active, w.backgroundRole())


def _qss_renkleri(qss: str) -> list[str]:
    from PyQt6.QtGui import QColor
    bloklar = re.findall(r"\{([^}]*)\}", qss) if "{" in qss else [qss]
    cik = []
    for b in bloklar:
        for bildirim in b.split(";"):
            if ":" not in bildirim:
                continue
            oz, deger = (s.strip().lower() for s in bildirim.split(":", 1))
            if not any(k in oz for k in _RENK_OZELLIK):
                continue
            for t in _QSS_RENK.findall(deger):
                if t in _RENK_DISI or t.isdigit():
                    continue
                if t.startswith("rgb"):
                    s = [float(x) for x in re.findall(r"[\d.]+", t)[:3]]
                    if len(s) == 3:
                        cik.append(QColor(int(s[0]), int(s[1]), int(s[2])).name())
                elif QColor.isValidColorName(t):
                    cik.append(QColor(t).name().lower())
    return cik


def _duzenler(w):
    lay = w.layout()
    if lay is None:
        return
    yigin = [lay]
    while yigin:
        lay = yigin.pop()
        yield lay
        for i in range(lay.count()):
            alt = lay.itemAt(i).layout()
            if alt is not None:
                yigin.append(alt)


def _aralik(lay, birim: int) -> str | None:
    from PyQt6.QtWidgets import QGridLayout
    m = lay.contentsMargins()
    degerler = {"kenar": [m.left(), m.top(), m.right(), m.bottom()]}
    gorunur = sum(1 for i in range(lay.count())
                  if (lay.itemAt(i).widget() is None or not lay.itemAt(i).widget().isHidden())
                  and lay.itemAt(i).spacerItem() is None)
    if gorunur >= 2:
        if isinstance(lay, QGridLayout):
            degerler["boşluk"] = [lay.horizontalSpacing(), lay.verticalSpacing()]
        else:
            degerler["boşluk"] = [lay.spacing()]
    kotu = {k: [v for v in vs if v > 0 and v % birim] for k, vs in degerler.items()}
    kotu = {k: v for k, v in kotu.items() if v}
    return ", ".join(f"{k} {v}" for k, v in kotu.items()) + f" (birim {birim})" if kotu else None


def denetle(kokler: list, esik: dict, ekran: str = "") -> list[dict]:
    """Görünen widget'lar → ihlal listesi (kural, ekran, yol, sinif, metin, deger)."""
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication, QLabel, QTabBar, QWidget

    from deskhand.gui.tema.uret import kontrast
    cik: list[dict] = []

    def ekle(kural, w, kok, deger):
        cik.append({"kural": kural, "ekran": ekran, "yol": _yol(w, kok), "sinif": type(w).__name__,
                    "metin": _metin(w).strip()[:40] if w is not None else "", "deger": deger})

    app = QApplication.instance()
    if app is not None and app.styleSheet():
        for r in _qss_renkleri(app.styleSheet()):
            if r not in esik["palet"]:
                cik.append({"kural": "QSS_RENK", "ekran": ekran, "yol": "<uygulama>", "sinif": "QApplication",
                            "metin": "", "deger": r})
    for kok in kokler:
        for w in [kok] + kok.findChildren(QWidget):
            if not w.isVisible():
                continue
            if _metinli(w):
                k = _kesik(w)
                if k:
                    ekle("KESIK", w, kok, k)
                f = w.font()
                pt = f.pointSizeF()
                if pt <= 0:
                    ekle("YAZI_BOYUTU", w, kok, f"{f.pixelSize()} px (pt değil)")
                elif not any(abs(pt - a) <= 0.01 * a for a in esik["yazi_pt"]):
                    ekle("YAZI_BOYUTU", w, kok, f"{pt:g} pt ∉ {[round(a, 2) for a in esik['yazi_pt']]}")
                # devre dışı DENETİM ÖĞESİ WCAG dışıdır; devre dışı ETİKET ise okunacak (soluk) metindir → denetlenir
                if (w.isEnabled() or isinstance(w, QLabel)) and not isinstance(w, QTabBar):
                    grup = QPalette.ColorGroup.Active if w.isEnabled() else QPalette.ColorGroup.Disabled
                    on, zemin = w.palette().color(grup, w.foregroundRole()), _zemin(w)
                    oran = kontrast(on, zemin)
                    if oran < esik["kontrast_min"]:
                        ekle("KONTRAST", w, kok, f"{on.name(QColor.NameFormat.HexArgb)} / {zemin.name()} = {oran:.2f}")
            if _hedef(w) and (w.width() < esik["hedef_min"] or w.height() < esik["hedef_min"]):
                ekle("HEDEF_KUCUK", w, kok, f"{w.width()}x{w.height()} < {esik['hedef_min']}")
            if w.styleSheet():
                for r in _qss_renkleri(w.styleSheet()):
                    if r not in esik["palet"]:
                        ekle("QSS_RENK", w, kok, r)
            for lay in _duzenler(w):
                a = _aralik(lay, esik["aralik_birim"])
                if a:
                    ekle("ARALIK", w, kok, f"{type(lay).__name__}: {a}")
    return cik


def doygunluk_denetle(resim, esik: dict, ekran: str = "") -> list[dict]:
    """Ekran görüntüsü (QImage) → yüksek doygun piksellerin ton grupları (10° kutu, ≥ DOYGUN_MIN_PX, bitişik kutular
    tek grup). >1 grup = DOYGUNLUK ihlali (tek ihlal; değer: grupların ortalama tonu ve piksel sayısı)."""
    import numpy as np
    from PyQt6.QtGui import QImage
    im = resim.convertToFormat(QImage.Format.Format_RGB32)
    g, y = im.width(), im.height()
    if g == 0 or y == 0:
        return []
    ham = np.frombuffer(im.constBits().asstring(im.sizeInBytes()), np.uint8).reshape(y, im.bytesPerLine())
    a = ham[:, : g * 4].reshape(y, g, 4)[:, :, 2::-1].astype(np.float32) / 255  # BGRA → RGB
    mx, mn = a.max(axis=2), a.min(axis=2)
    L = (mx + mn) / 2
    fark = mx - mn
    S = np.where(fark > 0, fark / np.maximum(1e-6, 1 - np.abs(2 * L - 1)), 0)
    d = esik["doygunluk"]
    m = (d["s_min"] <= S) & (d["l_min"] <= L) & (d["l_max"] >= L)
    if not m.any():
        return []
    p = a[m]
    r, gg, b = p[:, 0], p[:, 1], p[:, 2]
    f = np.maximum(1e-6, fark[m])
    mxp = mx[m]
    h = np.where(mxp == r, ((gg - b) / f) % 6, np.where(mxp == gg, (b - r) / f + 2, (r - gg) / f + 4)) * 60
    sayi = np.bincount((h // 10).astype(int) % 36, minlength=36)
    dolu = sayi >= DOYGUN_MIN_PX
    if dolu.all():
        gruplar = [(0, 36)]
    else:
        bas = int(np.argmin(dolu))  # boş bir kutudan başla: halka bitişikliği (350°–0°) tek grup
        gruplar, i = [], 0
        while i < 36:
            k = (bas + i) % 36
            if dolu[k]:
                j = i
                while j < 36 and dolu[(bas + j) % 36]:
                    j += 1
                gruplar.append((bas + i, j - i))
                i = j
            else:
                i += 1
    if len(gruplar) <= 1:
        return []
    ozet = ", ".join(f"{((s + n / 2) * 10) % 360:.0f}° ({sum(int(sayi[(s + t) % 36]) for t in range(n))} px)"
                     for s, n in gruplar)
    return [{"kural": "DOYGUNLUK", "ekran": ekran, "yol": "<ekran>", "sinif": "", "metin": "",
             "deger": f"{len(gruplar)} doygun vurgu: {ozet}"}]


def _token(ham: dict, yol: tuple):
    d = ham
    for k in yol:
        d = d[k]
    return d


def uyum_denetle(ham: dict, esik: dict) -> list[dict]:
    """Koyu palet: UYUM_ROLLER renkleri çift çift CIEDE2000 ≥ renk_ayrim_min_de (aynı renk = aynı rol, ör. dur ve
    tehlike, tek sayılır) ve her biri koyu zemine (Window) kontrast ≥ 3:1."""
    from PyQt6.QtGui import QColor

    from deskhand.gui.tema.uret import birlestir, de2000, kontrast
    t = birlestir(ham)
    zemin = t["renk"]["koyu"]["palet"]["Window"]
    renk = [(ad, _token(t, yol).lower()) for ad, yol in UYUM_ROLLER]
    cik = []

    def ekle(deger):
        cik.append({"kural": "UYUM", "ekran": "palet-koyu", "yol": "<tokens>", "sinif": "", "metin": "",
                    "deger": deger})
    for ad, r in renk:
        o = kontrast(QColor(r), QColor(zemin))
        if o < GRAFIK_KONTRAST_MIN:
            ekle(f"{ad} {r} / zemin {zemin} kontrast {o:.2f} < {GRAFIK_KONTRAST_MIN:g}")
    for i, (a1, r1) in enumerate(renk):
        for a2, r2 in renk[i + 1:]:
            if r1 == r2:
                continue
            de = de2000(r1, r2)
            if de < esik["renk_ayrim_min_de"]:
                ekle(f"{a1} {r1} ~ {a2} {r2} ΔE2000 {de:.1f} < {esik['renk_ayrim_min_de']:g}")
    return cik


def anahtar(i: dict) -> str:
    """Koordinatsız, ekrandan bağımsız kimlik (sekme dışı şerit her sekmede bir kez sayılır)."""
    return f"{i['kural']}|{i['yol']}|{i['metin']}"


# =========================================================================== panel + pano
def _ortam_yalit() -> str:
    """Geçici HOME/XDG (sabit ortam) + DESKHAND_* geçici klasörler; Qt/deskhand içe aktarılmadan ÖNCE çağrılır."""
    sys.path.insert(0, TESTLER)
    import _gorsel as G
    ev = tempfile.mkdtemp(prefix="tasarim-kapi-")
    yol = os.environ.get("PATH", "/usr/bin:/bin")
    os.environ.update(G.sabit_ortam(ev, DESKHAND_DIL=os.environ.get("DESKHAND_DIL", "tr")))
    os.environ["PATH"] = yol  # magick/pngquant/oxipng ~/.local/bin'de olabilir
    import _yalitim  # noqa: F401  (DESKHAND_* geçici; çıkışta silinir)
    import atexit
    atexit.register(shutil.rmtree, ev, True)
    return ev


def _bekle(app, sn: float) -> None:
    son = time.monotonic() + sn
    while time.monotonic() < son:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def calistir(ham: dict, kip: str, pano_dizin: str | None) -> tuple[list[dict], list[tuple[str, str]], int]:
    """Paneli ve diyalogları kurar, denetler; pano_dizin verilirse her ekranı PNG'ye çeker. → ihlaller, çekimler,
    ekran sayısı."""
    import _gorsel as G
    from PyQt6.QtWidgets import QApplication

    from deskhand.gui.tema import uret
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    birlesik = uret.birlestir(ham)
    # palet panel kurulmadan ÖNCE: soluk etiketler rengini kurulumda paletten alır; panelin tema_uygula("sistem")
    # çağrısı bu paletin koyu/açık oluşuna göre aynı kipi seçer, ardından denetlenen token'lar yeniden uygulanır
    app.setPalette(uret.palet_uret(birlesik, kip, app.style().standardPalette()))
    from deskhand.gui import ayar as A
    A.panel_yaz({**A.panel_oku(), "tema": kip})  # panel açılışta kayıtlı tercihi uygular (yoksa koyu; UX-K)
    panel = G._panel_kur(app)
    app.setPalette(uret.palet_uret(birlesik, kip, app.style().standardPalette()))
    app.setStyleSheet(uret.qss_uret(birlesik, kip))
    esik = esikler(ham, app.font().pointSizeF())
    w = panel.pencere
    w.show()
    app.processEvents()
    ihlal: list[dict] = []
    cekim: list[tuple[str, str]] = []
    n = w.sekmeler.count()
    ihlal += uyum_denetle(ham, esik)
    for i in range(n):
        w.sekmeler.setCurrentIndex(i)
        _bekle(app, 0.02)
        ad = f"sekme{i}-{w.sekmeler.tabText(i).replace('&', '')}"
        ihlal += denetle([w], esik, ad)
        resim = w.grab()
        ihlal += doygunluk_denetle(resim.toImage(), esik, ad)
        if pano_dizin:
            yol = os.path.join(pano_dizin, f"{i:02d}.png")
            resim.save(yol)
            cekim.append((yol, ad))
    w.hide()
    from deskhand.gui.onay_diyalog import OnayDiyalog
    istekler = G.diyalog_istekleri()
    for j, (ad, istek) in enumerate(istekler.items()):
        d = OnayDiyalog(istek, yanitla=lambda k, v: True, istek_var=lambda: True, kurma_ms=0,
                        saat=lambda z=istek["zaman"]: z)
        d.show()
        app.processEvents()
        ihlal += denetle([d], esik, f"diyalog-{ad}")
        resim = d.grab()
        ihlal += doygunluk_denetle(resim.toImage(), esik, f"diyalog-{ad}")
        if pano_dizin:
            yol = os.path.join(pano_dizin, f"{n + j:02d}.png")
            resim.save(yol)
            cekim.append((yol, f"diyalog-{ad}"))
        d.hide()
        d.deleteLater()
    return ihlal, cekim, n + len(istekler)


def pano_yap(cekim: list[tuple[str, str]], cikti: str) -> dict:
    """Ekranlar → tek iletişim sayfası (magick montage) → ≤1600 px → pngquant + oxipng."""
    t = time.perf_counter()
    sutun = math.ceil(math.sqrt(len(cekim)))
    gecici = cikti + ".tmp.png"
    arg = ["magick", "montage", "-background", "#808080", "-fill", "#ffffff", "-pointsize", "30"]
    for yol, ad in cekim:
        arg += ["-label", ad, yol]
    arg += ["-tile", f"{sutun}x", "-geometry", "+6+6", "miff:-"]
    montaj = subprocess.run(arg, check=True, capture_output=True, timeout=30).stdout
    subprocess.run(["magick", "miff:-", "-resize", f"{PANO_KENAR}x{PANO_KENAR}>", gecici], input=montaj, check=True,
                   capture_output=True, timeout=30)
    subprocess.run(["pngquant", "--force", "--speed", "3", "--quality", "60-90", "--skip-if-larger",
                    "--output", cikti, gecici], capture_output=True, timeout=30)
    if not os.path.exists(cikti):  # pngquant kalite sınırına ya da --skip-if-larger'a takıldı
        os.replace(gecici, cikti)
    elif os.path.exists(gecici):
        os.remove(gecici)
    subprocess.run(["oxipng", "-q", "-o", "2", "--strip", "safe", cikti], capture_output=True, timeout=30)
    from PIL import Image
    with Image.open(cikti) as im:
        boyut = im.size
    return {"yol": cikti, "bayt": os.path.getsize(cikti), "boyut": list(boyut), "ekran": len(cekim),
            "montaj_ms": round((time.perf_counter() - t) * 1000)}


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--json", action="store_true", help="sonucu JSON yaz")
    a.add_argument("--pano", metavar="OUT.png", help="tüm ekranlar tek sıkıştırılmış PNG")
    a.add_argument("--tokens", metavar="PATH", default=TOKENS, help="token dosyası (eşikler + tema)")
    a.add_argument("--kip", choices=("acik", "koyu"), default="acik")
    a.add_argument("--bilinen", metavar="PATH", default=BILINEN)
    a.add_argument("--bilinen-yaz", action="store_true", help="bugünkü ihlalleri bilinen listesine yaz")
    g = a.parse_args(argv)
    try:
        with open(g.tokens, encoding="utf-8") as f:
            ham = json.load(f)
    except (OSError, ValueError) as e:
        print(f"token dosyası okunamadı: {e}", file=sys.stderr)
        return 2
    _ortam_yalit()
    pano_dizin = tempfile.mkdtemp(prefix="pano-", dir=os.environ["XDG_CACHE_HOME"]) if g.pano else None
    ihlal, cekim, ekran = calistir(ham, g.kip, pano_dizin)
    tekil: dict[str, dict] = {}
    for i in ihlal:
        tekil.setdefault(anahtar(i), i)
    sure_ms = round((time.perf_counter() - _T0) * 1000)
    if g.bilinen_yaz:
        with open(g.bilinen, "w", encoding="utf-8") as f:
            json.dump(sorted(tekil), f, ensure_ascii=False, indent=1)
            f.write("\n")
    try:
        with open(g.bilinen, encoding="utf-8") as f:
            bilinen = set(json.load(f))
    except (OSError, ValueError):
        bilinen = set()
    yeni = [i for k, i in tekil.items() if k not in bilinen]
    tur = {k: sum(1 for i in tekil.values() if i["kural"] == k) for k in KURALLAR}
    sonuc: dict = {"ekran": ekran, "kip": g.kip, "tokens": g.tokens, "toplam": len(tekil),
             "bilinen": len(tekil) - len(yeni), "tur": tur, "yeni": yeni, "giden": sorted(bilinen - set(tekil)),
             "sure_ms": sure_ms}
    if g.pano:
        p = pano_yap(cekim, os.path.abspath(g.pano))
        p["sure_ms"] = round((time.perf_counter() - _T0) * 1000)
        sonuc["pano"] = p
    if g.json:
        print(json.dumps(sonuc, ensure_ascii=False, indent=1))
    else:
        for i in yeni:
            print(f"YENİ {i['kural']:<12} {i['ekran']:<22} {i['yol']}  «{i['metin']}»  {i['deger']}")
        print(f"{ekran} ekran · {len(tekil)} ihlal ({len(tekil) - len(yeni)} bilinen, {len(yeni)} yeni) · "
              + " ".join(f"{k}={v}" for k, v in tur.items() if v) + f" · {sure_ms} ms")
        if sonuc["giden"]:
            print(f"giderilen bilinen ihlal: {len(sonuc['giden'])} (--bilinen-yaz ile listeyi daralt)")
        if g.pano:
            p = sonuc["pano"]
            print(f"pano: {p['yol']} {p['boyut'][0]}x{p['boyut'][1]} {p['bayt']} bayt · {p['sure_ms']} ms")
    sys.stdout.flush()
    return 1 if yeni else 0


if __name__ == "__main__":
    import atexit
    rc = main()
    sys.stdout.flush()
    atexit._run_exitfuncs()  # geçici klasör temizliği (_yalitim + ev); ardından Qt sökümü atlanır (hız)
    os._exit(rc)
