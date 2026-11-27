"""Onaylar sekmesi."""
from __future__ import annotations

import time

from PyQt6.QtCore import (QTimer,
                          pyqtSignal)
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                             QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...i18n import _
from .. import metinler as T
from ..dil import Metinler
from ..gunluk_okur import onay_gecmisi
from ..ortak import (YESIL, KIRMIZI, nokta, baslik_etiketi, soluk_etiket, _masaustu_adi, _karar_adi)


# =========================================================================== Onaylar

class OnaylarSekmesi(QWidget):
    ac_istendi = pyqtSignal(str)

    def __init__(self, parent=None, saat=time.time):
        super().__init__(parent)
        self.saat = saat
        self.bekleyen: list[dict] = []
        self.gecmis: list[dict] = []  # en yeni başta (t_gecmis satırlarıyla aynı sıra)
        self.mt = Metinler()
        kok = QVBoxLayout(self)
        e = baslik_etiketi("")
        self.mt(e.setText, T.O_BEKLEYEN)
        kok.addWidget(e)
        self.t_bekleyen = self._tablo(T.O_BEKLEYEN_SUTUNLAR)
        self.t_bekleyen.itemDoubleClicked.connect(lambda it: self._ac(it.row()))
        kok.addWidget(self.t_bekleyen, 2)
        alt = QHBoxLayout()
        self.l_bos = soluk_etiket("")
        self.mt(self.l_bos.setText, T.O_BOS)
        alt.addWidget(self.l_bos)
        alt.addStretch(1)
        self.b_ac = QPushButton()
        self.mt(self.b_ac.setText, T.O_AC)
        self.b_ac.clicked.connect(lambda: self._ac(self.t_bekleyen.currentRow()))
        alt.addWidget(self.b_ac)
        kok.addLayout(alt)
        e = baslik_etiketi("")
        self.mt(e.setText, T.O_GECMIS)
        kok.addWidget(e)
        self.t_gecmis = self._tablo(T.O_SUTUNLAR)
        kok.addWidget(self.t_gecmis, 3)
        for t, sutunlar in ((self.t_bekleyen, T.O_BEKLEYEN_SUTUNLAR), (self.t_gecmis, T.O_SUTUNLAR)):
            self.mt.fn(lambda t=t, sutunlar=sutunlar: t.setHorizontalHeaderLabels([_(x) for x in sutunlar]))
        self.zaman = QTimer(self)
        self.zaman.setInterval(1000)
        self.zaman.timeout.connect(self._kalanlari_yaz)
        self.guncelle([])

    @staticmethod
    def _tablo(sutunlar) -> QTableWidget:
        t = QTableWidget(0, len(sutunlar))
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        b = t.horizontalHeader()
        b.setStretchLastSection(True)
        b.setHighlightSections(False)
        for i in range(len(sutunlar) - 1):
            b.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        b.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        return t

    def _ac(self, satir: int):
        if 0 <= satir < len(self.bekleyen):
            self.ac_istendi.emit(self.bekleyen[satir]["id"])

    def guncelle(self, bekleyen: list[dict]) -> None:
        self.bekleyen = list(bekleyen)
        t = self.t_bekleyen
        t.setRowCount(len(self.bekleyen))
        for i, d in enumerate(self.bekleyen):
            vals = (time.strftime("%H:%M:%S", time.localtime(d["zaman"])), d["eylem"], d["hedef"],
                    _masaustu_adi(d["masaustu"]), "")
            for j, v in enumerate(vals):
                t.setItem(i, j, QTableWidgetItem(v))
        self._kalanlari_yaz()
        self.l_bos.setVisible(not self.bekleyen)
        self.b_ac.setEnabled(bool(self.bekleyen))
        if self.bekleyen and self.isVisible():
            self.zaman.start()
        elif not self.bekleyen:
            self.zaman.stop()

    def _kalanlari_yaz(self):
        from ..onay_diyalog import sure_metni
        simdi = self.saat()
        for i, d in enumerate(self.bekleyen):
            it = self.t_bekleyen.item(i, 4)
            if it is not None:
                it.setText(sure_metni(d["son_zaman"] - simdi))

    def gecmis_ekle(self, satirlar: list[dict]) -> None:
        for g in onay_gecmisi(satirlar):
            t = self.t_gecmis
            t.insertRow(0)
            self.gecmis.insert(0, g)
            self._gecmis_yaz(0, g)
            while t.rowCount() > 200:
                t.removeRow(t.rowCount() - 1)
            del self.gecmis[200:]

    def _gecmis_yaz(self, satir: int, g: dict) -> None:
        vals = (g["zaman"], g["eylem"], g["hedef"], _masaustu_adi(g["masaustu"]), _karar_adi(g["sonuc"]))
        for j, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if j == 4:
                it.setIcon(nokta(YESIL if g["sonuc"] in ("izin", "devir-tamam", "devir-kosul") else KIRMIZI, 6))
            self.t_gecmis.setItem(satir, j, it)

    def tazele(self) -> None:
        self.mt.tazele()
        self.guncelle(self.bekleyen)
        for i, g in enumerate(self.gecmis):
            self._gecmis_yaz(i, g)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self.bekleyen:
            self.zaman.start()

    def hideEvent(self, e):  # noqa: N802
        super().hideEvent(e)
        self.zaman.stop()
