"""Durum şeridi (DUR/Devam + durum yazısı)."""
from __future__ import annotations


from PyQt6.QtCore import (Qt, pyqtSignal)
from PyQt6.QtWidgets import (QFrame, QHBoxLayout,
                             QLabel, QPushButton, QVBoxLayout)

from ..i18n import _
from . import metinler as T
from .dil import Metinler
from .durum import RENK, Durum, etiket_kacis
from .tepsi import durum_pixmap
from .ortak import (_DUR_KAYNAK_PANEL, nokta, soluk_etiket)


class DurumSeridi(QFrame):
    dur_istendi = pyqtSignal()
    devam_istendi = pyqtSignal()
    onaylar_istendi = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("durumSeridi")
        self.mt = Metinler()
        self.durum = Durum()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        sat = QHBoxLayout(self)
        sat.setContentsMargins(14, 10, 14, 10)
        sat.setSpacing(12)
        self.simge = QLabel()
        sat.addWidget(self.simge)
        sut = QVBoxLayout()
        sut.setSpacing(2)
        self.l_durum = QLabel()
        self.l_durum.setTextFormat(Qt.TextFormat.PlainText)  # the DUR source label comes from a file: never HTML
        f = self.l_durum.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.2)
        self.l_durum.setFont(f)
        sut.addWidget(self.l_durum)
        self.l_alt = soluk_etiket("", kaydir=False)
        sut.addWidget(self.l_alt)
        sat.addLayout(sut, 1)
        self.b_onay = QPushButton()
        self.b_onay.setFlat(True)
        self.b_onay.clicked.connect(self.onaylar_istendi.emit)
        sat.addWidget(self.b_onay)
        self.b_dur = QPushButton()
        self.mt(self.b_dur.setText, T.DUR_DUGME)
        self.b_dur.setObjectName("dur")
        self.mt(self.b_dur.setToolTip, T.DUR_IPUCU)
        self.b_dur.setMinimumSize(120, 40)
        self.b_dur.setStyleSheet(f"QPushButton#dur {{ background: {RENK['dur']}; color: {RENK['dur_metin']}; font-weight: 700;"
                                 f" border: none; border-radius: 6px; padding: 6px 18px; }}"
                                 f" QPushButton#dur:hover {{ background: {RENK['dur_uzerinde']}; }}")
        self.b_dur.clicked.connect(self.dur_istendi.emit)
        self.b_devam = QPushButton()
        self.mt(self.b_devam.setText, T.DEVAM_DUGME)
        self.mt(self.b_devam.setToolTip, T.DEVAM_IPUCU)
        self.b_devam.setMinimumSize(120, 40)
        self.b_devam.clicked.connect(self.devam_istendi.emit)
        sat.addWidget(self.b_dur)
        sat.addWidget(self.b_devam)
        self.guncelle(Durum())

    def tazele(self):
        self.mt.tazele()
        self.guncelle(self.durum)

    def guncelle(self, d: Durum):
        self.durum = d
        pm = durum_pixmap(d, 64)
        pm.setDevicePixelRatio(2)
        self.simge.setPixmap(pm)
        metin = d.metin
        if d.ad == "dur" and d.dur_kaynak:
            k = d.dur_kaynak
            ad = T.DUR_KAYNAK.get(k) or _DUR_KAYNAK_PANEL.get(k)
            metin += f" — {_(ad) if ad else etiket_kacis(k)}"
        self.l_durum.setText(metin)
        alt = [_(T.SANAL_ACIK).format(ekran=d.sanal_ekran) if d.sanal_acik else _(T.SANAL_KAPALI)]
        if d.devral:
            alt.append(_(T.DEVRAL_ACIK))
        if d.son_eylem and d.ad in ("ekran", "arka"):
            from .dil import _komut_adlari
            alt.append(_komut_adlari(d.son_eylem)[:90])
        self.l_alt.setText(" · ".join(alt))
        self.b_onay.setVisible(bool(d.bekleyen))
        self.b_onay.setText(_(T.ONAY_BEKLIYOR).format(n=d.bekleyen))
        self.b_onay.setIcon(nokta(RENK["rozet"], 7))
        dur = d.ad == "dur"
        self.b_dur.setVisible(not dur)
        self.b_devam.setVisible(dur)
