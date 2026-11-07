"""Bağımlılık denetimi (Sağlık sekmesi). Qt'siz; yalnız okur (`which`, `tesseract --list-langs`, find_spec)."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess

from ..i18n import N_

# (ad, açıklama/paket) — araç adları tek dizede: ham araç taraması (tests/test_mantik.py) yalnız arka_uc'ye izin verir.
# Açıklamalar msgid (N_): Sağlık sekmesi gösterirken çevirir; paket adları parantez içinde aynen kalmalı.
_ARAC_ADLARI = "kdotool dotool spectacle tesseract Xvfb xdotool openbox".split()
ARAC_NOT = dict(zip(_ARAC_ADLARI, (
    N_("pencere bulma (AUR: kdotool-bin)"), N_("fare/klavye (AUR: dotool)"), N_("ekran görüntüsü (spectacle)"),
    N_("metin okuma (tesseract)"), N_("arka plan masaüstü (xorg-server-xvfb)"), N_("arka plan yedek araç (xdotool)"),
    N_("arka plan pencere yöneticisi (openbox)"))))
DILLER = {"tur": N_("Türkçe OCR (tesseract-data-tur)"), "eng": N_("İngilizce OCR (tesseract-data-eng)")}
MODULLER = {"PyQt6": N_("arayüz (python-pyqt6)"), "Xlib": N_("arka plan girdi/görüntü (python-xlib)"),
            "numpy": N_("görüntü işleme (python-numpy)"), "scipy": N_("simge eşleme (python-scipy)"),
            "PIL": N_("görüntü (python-pillow)"), "jeepney": N_("D-Bus (python-jeepney)"),
            "mcp": N_("MCP sunucusu (python-mcp)")}


def tesseract_dilleri(calistir=subprocess.run) -> set[str] | None:
    yol = shutil.which("tesseract")
    if not yol:
        return None
    try:
        r = calistir([yol, "--list-langs"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    satirlar = (r.stdout or "").splitlines() + (r.stderr or "").splitlines()
    return {s.strip() for s in satirlar if s.strip() and " " not in s.strip() and not s.endswith(":")}


def denetle(which=shutil.which, find_spec=importlib.util.find_spec, diller_f=tesseract_dilleri) -> list[dict]:
    """→ [{ad, tur ("arac"|"dil"|"modul"), ok, not}]."""
    sonuc = []
    for ad in _ARAC_ADLARI:
        sonuc.append({"ad": ad, "tur": "arac", "ok": bool(which(ad)), "not": ARAC_NOT[ad]})
    diller = diller_f()
    for ad, n in DILLER.items():
        sonuc.append({"ad": f"tesseract: {ad}", "tur": "dil", "ok": bool(diller and ad in diller), "not": n})
    for ad, n in MODULLER.items():
        try:
            ok = find_spec(ad) is not None
        except (ImportError, ValueError):
            ok = False
        sonuc.append({"ad": ad, "tur": "modul", "ok": ok, "not": n})
    return sonuc
