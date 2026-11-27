"""Tasarım token'ları (tokens.json) → QPalette + QSS.

tokens.json tek kaynaktır; burada yalnız güvenlik ağı olarak VARSAYILAN durur (dosya yok/bozuk ya da anahtar eksikse
onaylı görünüm). Kip: "acik" | "koyu" | "sistem" (sistem = uygulamanın o anki paleti koyuysa "koyu", açıksa "acik"
token değerleri; KDE'de BreezeDark → koyu).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re

from PyQt6.QtGui import QColor, QPalette

KIPLER = ("acik", "koyu", "sistem")
TOKENS_YOLU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.json")
_RENK = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_ROLLER = {r.name: r for r in QPalette.ColorRole if r != QPalette.ColorRole.NColorRoles}
_PALET_BOLUMLERI = ("palet", "devre_disi")
_log = logging.getLogger(__name__)

# Onaylı tasarım A + Renk 1 (UX-D0, 27 Kas; tokens.json sürüm 2 ile aynı). Güvenlik ağı: dosya yok/bozuksa da bu görünüm.
_ACIK = {"zemin": "#eff0f1", "yuzey": "#fcfcfc", "yuzey2": "#e3e5e7", "cizgi": "#d0d3d6", "kenar": "#7d858c",
         "metin": "#232629", "soluk": "#566069", "vurgu": "#1b6ea8", "vurgu_metin": "#ffffff"}
_KOYU = {"zemin": "#31363b", "yuzey": "#232629", "yuzey2": "#3b4045", "cizgi": "#4d5359", "kenar": "#8f979e",
         "metin": "#eff0f1", "soluk": "#adb4ba", "vurgu": "#3daee9", "vurgu_metin": "#0b1823"}


def _renk_kipi(r: dict) -> dict:
    """Tasarım rengi (renk1) → QPalette rolleri (eşleme tokens.json $aciklama'da)."""
    return {"palet": {
        "Window": r["zemin"], "WindowText": r["metin"], "Base": r["yuzey"], "AlternateBase": r["zemin"],
        "Text": r["metin"], "PlaceholderText": r["soluk"], "Button": r["yuzey2"], "ButtonText": r["metin"],
        "Light": r["yuzey"] if r is _ACIK else r["yuzey2"], "Midlight": r["cizgi"], "Mid": r["cizgi"],
        "Dark": r["kenar"], "Shadow": r["kenar"], "Highlight": r["vurgu"], "HighlightedText": r["vurgu_metin"],
        "Accent": r["vurgu"], "Link": r["vurgu"], "LinkVisited": r["vurgu"], "ToolTipBase": r["yuzey"],
        "ToolTipText": r["metin"],
    }, "devre_disi": {"WindowText": r["soluk"], "Text": r["soluk"], "ButtonText": r["soluk"],
                      "Highlight": r["cizgi"], "Accent": r["cizgi"]}}


VARSAYILAN: dict = {
    "surum": 2,
    "min_tiklama_hedefi_px": 24,  # WCAG 2.5.8
    "kontrast_min": 4.5,          # WCAG 1.4.3
    "renk": {"acik": _renk_kipi(_ACIK), "koyu": _renk_kipi(_KOYU)},
    "durum": {
        "bos": "#8a8f98", "ekran": "#e8590c", "arka": "#1c7ed6", "dur": "#e03131", "dur_metin": "#ffffff",
        "dur_uzerinde": "#fb3737", "rozet": "#fab005", "basari": "#2f9e44", "hata": "#e03131", "uyari": "#e8a317",
        "soluk": "#8a8f98", "tepsi_on": "#ffffff", "tepsi_cizgi": "#2b2b2b",
    },
    "yazi": {"aile": None, "baslik_olcek": 1.08, "durum_olcek": 1.2, "diyalog_soru_olcek": 1.25,
             "kalin_agirlik": 700},
    "aralik": {
        "girinti": 22, "dugme_dikey": 6, "dugme_yatay": 18, "serit_yatay": 14, "serit_dikey": 10,
        "serit_bosluk": 12, "satir_bosluk": 2, "sekme_bosluk": 14, "liste_bosluk": 6, "kart_kenar": 10,
        "kart_bosluk": 8, "diyalog_yatay": 20, "diyalog_ust": 18, "diyalog_alt": 16, "diyalog_bosluk": 12,
        "dur_genislik": 120, "dur_yukseklik": 40,
    },
    "kose": {"dugme": 6},
    "odak": {"kalinlik": 1, "renk_rol": "Highlight"},
}


def renk_gecerli(v) -> bool:
    return isinstance(v, str) and bool(_RENK.match(v))


def _sayi(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _yaprak_gecerli(varsayilan, v, anahtar: str) -> bool:
    if anahtar == "renk_rol":
        return isinstance(v, str) and v in _ROLLER
    if anahtar == "aile":
        return v is None or (isinstance(v, str) and bool(v.strip()))
    if isinstance(varsayilan, str):
        return renk_gecerli(v)
    if _sayi(varsayilan):
        return _sayi(v)
    return isinstance(v, type(varsayilan))


def _denetle(varsayilan: dict, ham, yol: str, hatalar: list[str], palet: bool = False) -> dict:
    """ham'ı varsayılanla birleştirir; geçersiz/bilinmeyen değerleri atar ve hatalar'a yazar."""
    sonuc = copy.deepcopy(varsayilan)
    if not isinstance(ham, dict):
        hatalar.append(f"{yol}: sözlük değil")
        return sonuc
    for a, v in ham.items():
        y = f"{yol}.{a}" if yol else a
        if palet:
            if a not in _ROLLER:
                hatalar.append(f"{y}: bilinmeyen QPalette rolü")
            elif not renk_gecerli(v):
                hatalar.append(f"{y}: geçersiz renk {v!r}")
            else:
                sonuc[a] = v
            continue
        if a == "$aciklama" and not yol:
            continue
        if a not in varsayilan:
            hatalar.append(f"{y}: bilinmeyen anahtar")
        elif isinstance(varsayilan[a], dict):
            sonuc[a] = _denetle(varsayilan[a], v, y, hatalar, palet=a in _PALET_BOLUMLERI)
        elif _yaprak_gecerli(varsayilan[a], v, a):
            sonuc[a] = v
        else:
            hatalar.append(f"{y}: geçersiz değer {v!r}")
    return sonuc


def sema_denetle(ham) -> list[str]:
    hatalar: list[str] = []
    _denetle(VARSAYILAN, ham, "", hatalar)
    return hatalar


def birlestir(ham) -> dict:
    """Eksik/bozuk anahtar → varsayılan (anahtar düzeyinde)."""
    hatalar: list[str] = []
    sonuc = _denetle(VARSAYILAN, ham, "", hatalar)
    for h in hatalar:
        _log.warning("tema token yok sayıldı: %s", h)
    return sonuc


def yukle(yol: str | None = None) -> dict:
    try:
        with open(yol or TOKENS_YOLU, encoding="utf-8") as f:
            ham = json.load(f)
    except (OSError, ValueError) as e:
        _log.warning("tema token dosyası okunamadı (%s): varsayılan kullanılıyor", e)
        ham = {}
    return birlestir(ham)


def _kip_denetle(kip: str) -> None:
    if kip not in KIPLER:
        raise ValueError(f"bilinmeyen tema kipi: {kip!r} (beklenen: {', '.join(KIPLER)})")


def sistem_kipi(palet: QPalette | None = None) -> str:
    """Sistem paleti (verilmezse uygulamanın paleti) koyu mu? → "koyu" | "acik". Ölçüt: Window açıklığı < 128
    (renk düzeni ipucu yerine palet: KDE renk düzeni palete yansır, ekransız ortamda ipucu "bilinmiyor"dur)."""
    if palet is None:
        from PyQt6.QtGui import QGuiApplication
        palet = QGuiApplication.palette()
    return "koyu" if palet.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window).lightness() < 128 else "acik"


def palet_uret(tokens: dict, kip: str, temel: QPalette | None = None) -> QPalette:
    """kip için QPalette ("sistem" → sistem_kipi() ile acik/koyu). Verilmeyen roller temel paletten (varsayılan:
    Fusion standart paleti) gelir."""
    _kip_denetle(kip)
    if kip == "sistem":
        kip = sistem_kipi()
    t = birlestir(tokens)["renk"][kip]
    if temel is None:
        from PyQt6.QtWidgets import QStyleFactory
        st = QStyleFactory.create("Fusion")
        temel = st.standardPalette() if st is not None else QPalette()
    p = QPalette(temel)
    for ad, v in t["palet"].items():
        p.setColor(_ROLLER[ad], QColor(v))  # tüm gruplar
    for ad, v in t["devre_disi"].items():
        p.setColor(QPalette.ColorGroup.Disabled, _ROLLER[ad], QColor(v))
    return p


def qss_uret(tokens: dict, kip: str) -> str:
    """Uygulama düzeyi QSS: yalnız elle yazılmış kurallar (DUR düğmesi, girintili alt anahtar); genel widget
    kuralı yok (renkler QPalette'ten; QSS stil çizimini bozmasın). Bütün renkler token'dan (QSS_RENK kuralı)."""
    _kip_denetle(kip)
    t = birlestir(tokens)
    d, a, k, y = t["durum"], t["aralik"], t["kose"], t["yazi"]
    uzerinde = d["dur_uzerinde"]
    return (
        f"QPushButton#dur {{ background: {d['dur']}; color: {d['dur_metin']}; font-weight: {y['kalin_agirlik']};"
        f" border: none; border-radius: {k['dugme']}px; padding: {a['dugme_dikey']}px {a['dugme_yatay']}px; }}\n"
        f"QPushButton#dur:hover {{ background: {uzerinde}; }}\n"
        f"QCheckBox[girinti=\"true\"] {{ margin-left: {a['girinti']}px; }}\n"
    )


def _goreli_parlaklik(c: QColor) -> float:
    def kanal(x: float) -> float:
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * kanal(c.redF()) + 0.7152 * kanal(c.greenF()) + 0.0722 * kanal(c.blueF())


def kontrast(on: QColor, arka: QColor) -> float:
    """WCAG 2 kontrast oranı (on rengin alfası arka üzerine karıştırılır)."""
    if on.alphaF() < 1:
        al = on.alphaF()
        on = QColor.fromRgbF(on.redF() * al + arka.redF() * (1 - al), on.greenF() * al + arka.greenF() * (1 - al),
                             on.blueF() * al + arka.blueF() * (1 - al))
    a, b = _goreli_parlaklik(on), _goreli_parlaklik(arka)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)
