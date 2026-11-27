"""Etkinlik sekmesi."""
from __future__ import annotations

from collections import deque

from PyQt6.QtCore import (QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout,
                             QHeaderView, QLineEdit, QTableView, QVBoxLayout, QWidget)

from ...i18n import N_, _
from .. import metinler as T
from ..dil import Metinler, gunluk_eylemi
from ..durum import RENK
from ..gunluk_okur import KUYRUK
from ..insan_metni import ayrinti, pencere_metni
from ..ortak import (soluk_etiket)

# Sütunlar (UX-B, Y3/D3): Saat · Ne oldu (insan metni) · Pencere (kimlik/yasak başlık yok) · Ayrıntı (ham satır)
SUTUNLAR = (N_("Saat"), N_("Ne oldu"), N_("Pencere"), N_("Ayrıntı"))
ARKA_PENCERE = N_("{pencere} (arka plan)")
FILTRE_AD = N_("Etkinlikte ara")


def pencere_sutunu(d: dict) -> str:
    """Pencere sütunu: başlık (pencere_metni); arka plan masaüstündeki satırda "(arka plan)" eki."""
    p = pencere_metni(d)
    if d.get("arka") == "arka":
        return _(ARKA_PENCERE).format(pencere=p) if p else _(T.E_ARKA_AD["arka"])
    return p


# =========================================================================== Etkinlik

class EtkinlikModel(QAbstractTableModel):
    def __init__(self, parent=None, sinir: int = KUYRUK):
        super().__init__(parent)
        self.satirlar: deque[dict] = deque()
        self.sinir = sinir

    def rowCount(self, parent=QModelIndex()):  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.satirlar)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802, B008
        return 0 if parent.isValid() else len(SUTUNLAR)

    def headerData(self, bolum, yon, rol=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if yon == Qt.Orientation.Horizontal and rol == Qt.ItemDataRole.DisplayRole:
            return _(SUTUNLAR[bolum])
        return None

    def data(self, i: QModelIndex, rol=Qt.ItemDataRole.DisplayRole):
        if not i.isValid():
            return None
        d = self.satirlar[i.row()]
        if rol == Qt.ItemDataRole.DisplayRole:
            if i.column() == 1:
                return gunluk_eylemi(d)
            if i.column() == 2:
                return pencere_sutunu(d)
            if i.column() == 3:
                return ayrinti(d)
            return d["zaman"]
        if rol == Qt.ItemDataRole.ToolTipRole:
            return ayrinti(d)  # ham satır (yasak başlık / URL sorgusu maskeli)
        if rol == Qt.ItemDataRole.UserRole:
            return d
        if rol == Qt.ItemDataRole.BackgroundRole and d["tur"] == "dur":
            c = QColor(RENK["dur"])
            c.setAlphaF(0.22)
            return c
        if rol == Qt.ItemDataRole.BackgroundRole and d["tur"] == "onay":
            c = QColor(RENK["rozet"])
            c.setAlphaF(0.18)
            return c
        if rol == Qt.ItemDataRole.FontRole and d["tur"] == "dur":
            from PyQt6.QtGui import QFont
            f = QFont()
            f.setBold(True)
            return f
        return None

    def ekle(self, yeni: list[dict]) -> None:
        if not yeni:
            return
        yeni = yeni[-self.sinir:]
        fazla = len(self.satirlar) + len(yeni) - self.sinir
        if fazla > 0:
            self.beginRemoveRows(QModelIndex(), 0, fazla - 1)
            for _i in range(fazla):
                self.satirlar.popleft()
            self.endRemoveRows()
        n = len(self.satirlar)
        self.beginInsertRows(QModelIndex(), n, n + len(yeni) - 1)
        self.satirlar.extend(yeni)
        self.endInsertRows()

    def tazele(self) -> None:
        """Dil değişti: başlıklar ve çevrilen hücreler (Masaüstü, sabit günlük satırları) yeniden okunsun."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
        if self.satirlar:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.satirlar) - 1, self.columnCount() - 1))


class EtkinlikSuzgec(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.metin = ""
        self.tur = "hepsi"

    def ayarla(self, metin: str | None = None, tur: str | None = None) -> None:
        if metin is not None:
            self.metin = metin.casefold()
        if tur is not None:
            self.tur = tur
        self.invalidateFilter()

    def filterAcceptsRow(self, satir, ust):  # noqa: N802
        d = self.sourceModel().satirlar[satir]
        if self.tur == "dur" and d["tur"] != "dur" and "DUR anahtarı" not in d["eylem"]:
            return False
        if self.tur in ("ekran", "arka") and d["arka"] != self.tur:
            return False
        if self.tur == "onay" and d["tur"] != "onay":
            return False
        return not self.metin or self.metin in d["ham"].casefold() or self.metin in gunluk_eylemi(d).casefold()


class EtkinlikSekmesi(QWidget):
    def __init__(self, ilk: list[dict], parent=None):
        super().__init__(parent)
        self.mt = Metinler()
        self.model = EtkinlikModel(self)
        self.suzgec = EtkinlikSuzgec(self)
        self.suzgec.setSourceModel(self.model)
        kok = QVBoxLayout(self)
        ust = QHBoxLayout()
        self.filtre = QLineEdit()
        self.mt(self.filtre.setPlaceholderText, T.E_FILTRE_IPUCU)
        self.mt(self.filtre.setAccessibleName, FILTRE_AD)  # AT-SPI: adsız giriş olmasın
        self.filtre.setClearButtonEnabled(True)
        self.filtre.textChanged.connect(lambda m: self.suzgec.ayarla(metin=m))
        ust.addWidget(self.filtre, 1)
        self.tur = QComboBox()
        for i, (anahtar, ad) in enumerate(T.E_TUR):
            self.tur.addItem("", anahtar)
            self.mt(lambda m, i=i: self.tur.setItemText(i, m), ad)
        self.tur.currentIndexChanged.connect(lambda _i: self.suzgec.ayarla(tur=self.tur.currentData()))
        ust.addWidget(self.tur)
        self.kaydir = QCheckBox()
        self.mt(self.kaydir.setText, T.E_KAYDIR)
        self.kaydir.setChecked(True)
        ust.addWidget(self.kaydir)
        kok.addLayout(ust)
        self.tablo = QTableView()
        self.tablo.setModel(self.suzgec)
        self.tablo.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 8)
        self.tablo.setWordWrap(False)
        self.tablo.setShowGrid(False)
        self.tablo.setAlternatingRowColors(True)
        bas = self.tablo.horizontalHeader()
        bas.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        bas.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        bas.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        bas.resizeSection(2, 260)
        bas.setStretchLastSection(True)
        bas.setHighlightSections(False)
        kok.addWidget(self.tablo, 1)
        self.alt = soluk_etiket("", kaydir=False)
        kok.addWidget(self.alt)
        self.ekle(ilk)

    def ekle(self, satirlar: list[dict]) -> None:
        cubuk = self.tablo.verticalScrollBar()
        sonda = cubuk.value() >= cubuk.maximum() - 2
        self.model.ekle(satirlar)
        if self.kaydir.isChecked() and sonda:
            self.tablo.scrollToBottom()
        self._alt_yaz()

    def _alt_yaz(self) -> None:
        n = self.model.rowCount()
        self.alt.setText(_(T.E_SATIR).format(n=n) if n else _(T.E_BOS))

    def tazele(self) -> None:
        self.mt.tazele()
        self.model.tazele()
        self._alt_yaz()
