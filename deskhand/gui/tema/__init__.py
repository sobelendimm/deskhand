"""Panel teması: tokens.json → QPalette + QSS (uret.py). Giriş noktası: tema_uygula(app, kip)."""
from __future__ import annotations

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from .uret import KIPLER, palet_uret, qss_uret, yukle

__all__ = ["KIPLER", "qss_uret", "tema_uygula"]

_ISARET = "deskhand_tema_palet"


def tema_uygula(app: QApplication, kip: str = "sistem") -> None:
    """kip: "acik" | "koyu" | "sistem". sistem → platform paleti (daha önce bizim koyduğumuz palet geri alınır)."""
    tokens = yukle()
    st = app.style()
    pal = palet_uret(tokens, kip, st.standardPalette() if st is not None else None)
    if pal is not None:
        app.setPalette(pal)
        app.setProperty(_ISARET, True)
    elif app.property(_ISARET):
        app.setPalette(QPalette())  # boş çözüm maskesi → platform/stil varsayılanı
        app.setProperty(_ISARET, False)
    app.setStyleSheet(qss_uret(tokens, kip))
