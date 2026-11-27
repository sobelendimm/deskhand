"""Sağlık sekmesi."""
from __future__ import annotations


from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                             QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...i18n import _
from .. import metinler as T
from ..dil import Metinler
from .. import saglik as S
from ..ortak import (YESIL, KIRMIZI, SARI, Isci, nokta)


# =========================================================================== Sağlık

class SaglikSekmesi(QWidget):
    def __init__(self, parent=None, denetle=S.tam_denetim):
        super().__init__(parent)
        self.denetle_f = denetle
        self._isci: Isci | None = None
        self.sonuc: list[dict] = []
        self.mt = Metinler()
        kok = QVBoxLayout(self)
        self.tablo = QTableWidget(0, 3)
        self.mt.fn(lambda: self.tablo.setHorizontalHeaderLabels([_(x) for x in T.H_SUTUNLAR]))
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tablo.setShowGrid(False)
        b = self.tablo.horizontalHeader()
        b.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        b.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        b.setStretchLastSection(True)
        b.setHighlightSections(False)
        kok.addWidget(self.tablo, 1)
        alt = QHBoxLayout()
        self.l_ozet = QLabel("")
        alt.addWidget(self.l_ozet, 1)
        self.b_yenile = QPushButton()
        self.mt(self.b_yenile.setText, T.H_YENILE)
        self.b_yenile.clicked.connect(self.yenile)
        alt.addWidget(self.b_yenile)
        kok.addLayout(alt)
        self._ilk = True

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if self._ilk:
            self._ilk = False
            self.yenile()

    def yenile(self):
        if self._isci is not None:
            return
        self.b_yenile.setEnabled(False)
        self._isci = Isci(self.denetle_f, self)
        self._isci.bitti.connect(self._bitti)
        self._isci.start()

    def _bitti(self, sonuc, hata):
        self._isci = None
        self.b_yenile.setEnabled(True)
        self.goster(sonuc or [])
        if hata is not None:
            self.l_ozet.setText(str(hata))

    def goster(self, sonuc: list[dict]):
        self.sonuc = sonuc
        self.tablo.setRowCount(len(sonuc))
        for i, d in enumerate(sonuc):
            ad = QTableWidgetItem(d["ad"])
            ad.setToolTip(_(T.H_TUR[d["tur"]]) if d["tur"] in T.H_TUR else d["tur"])
            d_ = d.get("durum", "tamam" if d["ok"] else "eksik")
            durum = QTableWidgetItem(_(T.H_VAR if d["ok"] else T.H_UYARI if d_ == "uyari" else T.H_YOK))
            durum.setIcon(nokta(YESIL if d["ok"] else SARI if d_ == "uyari" else KIRMIZI, 6))
            self.tablo.setItem(i, 0, ad)
            self.tablo.setItem(i, 1, durum)
            self.tablo.setItem(i, 2, QTableWidgetItem(_(d["not"])))  # saglik.py notları msgid
        ok = sum(1 for d in sonuc if d["ok"])
        self.l_ozet.setText(_(T.H_OZET).format(ok=ok, n=len(sonuc)))

    def tazele(self) -> None:
        self.mt.tazele()
        if self.sonuc:
            self.goster(self.sonuc)
