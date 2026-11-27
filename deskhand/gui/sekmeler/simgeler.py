"""Simgeler sekmesi."""
from __future__ import annotations

import os

from PyQt6.QtCore import (QSize, Qt)
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                             QListView, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ... import yollar
from ...i18n import _
from .. import metinler as T
from ..dil import Metinler
from ..ortak import (soluk_etiket)


# =========================================================================== Simgeler

class SimgelerSekmesi(QWidget):
    def __init__(self, parent=None, sor=None):
        super().__init__(parent)
        self.sor = sor or self._sor
        self.mt = Metinler()
        kok = QVBoxLayout(self)
        self.liste = QListWidget()
        self.liste.setViewMode(QListView.ViewMode.IconMode)
        self.liste.setIconSize(QSize(72, 72))
        self.liste.setGridSize(QSize(132, 118))
        self.liste.setResizeMode(QListView.ResizeMode.Adjust)
        self.liste.setMovement(QListView.Movement.Static)
        self.liste.setWordWrap(True)
        self.liste.setSpacing(6)
        self.liste.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.liste.itemSelectionChanged.connect(self._secim)
        kok.addWidget(self.liste, 1)
        alt = QHBoxLayout()
        self.l_bilgi = soluk_etiket("")
        alt.addWidget(self.l_bilgi, 1)
        b = QPushButton()
        self.mt(b.setText, T.I_YENILE)
        b.clicked.connect(self.yenile)
        alt.addWidget(b)
        self.b_sil = QPushButton()
        self.mt(self.b_sil.setText, T.I_SIL)
        self.b_sil.setIcon(QIcon.fromTheme("edit-delete"))
        self.b_sil.clicked.connect(self.sil)
        alt.addWidget(self.b_sil)
        kok.addLayout(alt)
        self.yenile()

    def _sor(self, baslik: str, metin: str) -> bool:
        """Evet/Hayır sorusu; düğmeler panelin dilinde (Qt'nin standart düğmeleri sistem dilinde kalırdı)."""
        k = QMessageBox(QMessageBox.Icon.Question, baslik, metin, QMessageBox.StandardButton.NoButton, self)
        evet = k.addButton(_(T.EVET), QMessageBox.ButtonRole.YesRole)
        hayir = k.addButton(_(T.HAYIR), QMessageBox.ButtonRole.NoRole)
        k.setDefaultButton(hayir)
        k.setEscapeButton(hayir)
        k.exec()
        return k.clickedButton() is evet

    def tazele(self) -> None:
        self.mt.tazele()
        self.yenile()

    def simgeler(self) -> list[tuple[str, str]]:
        d = yollar.simge_dizin()
        try:
            return sorted((f[:-4], os.path.join(d, f)) for f in os.listdir(d) if f.endswith(".png"))
        except OSError:
            return []

    def yenile(self):
        self.liste.clear()
        for ad, yol in self.simgeler():
            pm = QPixmap(yol)
            it = QListWidgetItem(QIcon(pm), ad)
            it.setData(Qt.ItemDataRole.UserRole, yol)
            it.setToolTip(_(T.I_BILGI).format(ad=ad, g=pm.width(), y=pm.height()))
            self.liste.addItem(it)
        self._secim()

    def _secim(self):
        it = self.liste.currentItem() if self.liste.selectedItems() else None
        self.b_sil.setEnabled(it is not None)
        if it is not None:
            self.l_bilgi.setText(it.toolTip())
        else:
            self.l_bilgi.setText(_(T.I_BOS) if self.liste.count() == 0 else "")

    def sil(self) -> bool:
        it = self.liste.currentItem()
        if it is None:
            return False
        ad, yol = it.text(), it.data(Qt.ItemDataRole.UserRole)
        if not self.sor(_(T.I_SIL_BASLIK), _(T.I_SIL_SORU).format(ad=ad)):
            return False
        try:
            os.remove(yol)
        except OSError:
            pass
        self.yenile()
        return True
