"""Panel penceresi: durum şeridi (DUR/Devam) + sekmeler (Etkinlik, Arka plan ekranı, Onaylar, Ayarlar, Simgeler,
Sağlık). Görünüm sistem paletinden (Breeze açık/koyu); sabit renk yalnız durum renklerinde."""
from __future__ import annotations

import atexit
import os
import time
from collections import deque

from PyQt6.QtCore import (QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel, Qt, QThread, QTimer,
                          pyqtSignal)
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QPalette, QPixmap
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                             QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QListView, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                             QSpinBox, QTableView, QTableWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from .. import i18n, onay, yollar
from ..i18n import _
from . import ayar as A
from . import metinler as T
from .dil import Metinler, dil_secenekleri, gunluk_eylemi
from . import saglik as S
from .durum import RENK, Durum
from .gunluk_okur import KUYRUK, onay_gecmisi
from .kisayol import VARSAYILAN_TUS, cakismalar
from .onizleme import Onizleme, pil_qimage
from .tepsi import durum_pixmap

ONIZLEME_MS = 500  # ~2 fps
YESIL, KIRMIZI = "#2f9e44", "#e03131"


class Isci(QThread):
    """Bir işlevi arka iş parçacığında çalıştırır → bitti(sonuç, hata). Bitince kendini siler; panel kapanırken
    çalışanlar `isciler_bekle` ile beklenir ("QThread destroyed while running" çökmesi olmasın)."""
    bitti = pyqtSignal(object, object)
    calisanlar: set = set()

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        Isci.calisanlar.add(self)
        self.finished.connect(self._bitince)

    def _bitince(self):
        Isci.calisanlar.discard(self)
        self.deleteLater()

    def run(self):
        try:
            self.bitti.emit(self.fn(), None)
        except BaseException as e:  # noqa: BLE001
            self.bitti.emit(None, e)


def isciler_bekle(ms: int = 10000) -> bool:
    """Çalışan arka işleri (masaüstü durdurma ~5 sn sürebilir) bekle. → hepsi bitti mi."""
    bitis = time.monotonic() + ms / 1000
    for i in list(Isci.calisanlar):
        try:
            kalan = max(0, int((bitis - time.monotonic()) * 1000))
            if i.isRunning() and not i.wait(kalan):
                return False
        except RuntimeError:  # C++ nesnesi zaten silinmiş
            Isci.calisanlar.discard(i)
    return True


def _devral_temizle(yol: str) -> None:
    """atexit: panel normal yoldan kapanmadan çıkarsa (istisna, sys.exit) kendi Devral dosyasını silsin."""
    try:
        from .. import masaustu
        masaustu.devral_sil(yalniz_kendi=True, yol=yol)
    except Exception:  # noqa: BLE001
        pass


_DEVRAL_ATEXIT: set[str] = set()


def nokta(renk: str, boyut: int = 12) -> QIcon:
    pm = QPixmap(boyut * 2, boyut * 2)
    pm.fill(Qt.GlobalColor.transparent)
    from PyQt6.QtGui import QPainter
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(renk))
    p.drawEllipse(4, 4, boyut * 2 - 8, boyut * 2 - 8)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def baslik_etiketi(metin: str) -> QLabel:
    e = QLabel(metin)
    f = e.font()
    f.setBold(True)
    f.setPointSizeF(f.pointSizeF() * 1.08)
    e.setFont(f)
    return e


def soluk_etiket(metin: str, kaydir: bool = True) -> QLabel:
    e = QLabel(metin)
    e.setWordWrap(kaydir)
    pal = e.palette()
    pal.setColor(QPalette.ColorRole.WindowText, pal.color(QPalette.ColorRole.PlaceholderText))
    e.setPalette(pal)
    return e


def _masaustu_adi(k) -> str:
    return _(T.MASAUSTU[k]) if k in T.MASAUSTU else str(k or "")


def _karar_adi(k) -> str:
    return _(T.O_KARAR[k]) if k in T.O_KARAR else str(k or "")


# =========================================================================== Etkinlik

class EtkinlikModel(QAbstractTableModel):
    def __init__(self, parent=None, sinir: int = KUYRUK):
        super().__init__(parent)
        self.satirlar: deque[dict] = deque()
        self.sinir = sinir

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.satirlar)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(T.E_SUTUNLAR)

    def headerData(self, bolum, yon, rol=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if yon == Qt.Orientation.Horizontal and rol == Qt.ItemDataRole.DisplayRole:
            return _(T.E_SUTUNLAR[bolum])
        return None

    def data(self, i: QModelIndex, rol=Qt.ItemDataRole.DisplayRole):
        if not i.isValid():
            return None
        d = self.satirlar[i.row()]
        if rol == Qt.ItemDataRole.DisplayRole:
            if i.column() == 1:
                return _(T.E_ARKA_AD[d["arka"]]) if d["arka"] in T.E_ARKA_AD else d["arka"]
            return (d["zaman"], "", d["pencere"], gunluk_eylemi(d))[i.column()]
        if rol == Qt.ItemDataRole.ToolTipRole:
            return d["ham"]
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
        return not self.metin or self.metin in d["ham"].casefold()


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


# =========================================================================== Arka plan ekranı

def _masaustu_modulu():
    try:
        from .. import masaustu
        return masaustu, None
    except Exception as e:  # noqa: BLE001 - başka ajan yazıyor / bağımlılık eksik
        return None, e


def _varsayilan_arka():
    from ..arka_uc import sec
    return sec(arka_bayragi=True)


class ArkaPlanSekmesi(QWidget):
    devral_degisti = pyqtSignal(bool)

    def __init__(self, parent=None, arka_f=_varsayilan_arka, masaustu_m=None, devral_yolu_f=None):
        super().__init__(parent)
        from .durum import devral_yolu
        self.arka_f = arka_f
        if masaustu_m is None:
            masaustu_m, self.m_hata = _masaustu_modulu()
        else:
            self.m_hata = None
        self.m = masaustu_m
        self.devral_yolu_f = devral_yolu_f or devral_yolu
        self.sanal: dict | None = None
        self.girdi = None
        self._isci: Isci | None = None
        self._tekerlek_uyarildi = False
        self.mt = Metinler()

        kok = QVBoxLayout(self)
        ust = QHBoxLayout()
        self.l_durum = QLabel(_(T.A_KAPALI))
        ust.addWidget(self.l_durum, 1)
        self.b_baslat = QPushButton()
        self.mt(self.b_baslat.setText, T.A_BASLAT)
        self.b_baslat.clicked.connect(self.baslat)
        self.b_durdur = QPushButton()
        self.mt(self.b_durdur.setText, T.A_DURDUR)
        self.b_durdur.clicked.connect(self.durdur)
        self.b_devral = QPushButton()
        self.b_devral.setCheckable(True)
        self.mt.fn(lambda: self.b_devral.setText(_(T.A_BIRAK if self.b_devral.isChecked() else T.A_DEVRAL)))
        self.mt(self.b_devral.setToolTip, T.A_DEVRAL_IPUCU)
        self.b_devral.toggled.connect(self.devral)
        for b in (self.b_baslat, self.b_durdur, self.b_devral):
            ust.addWidget(b)
        kok.addLayout(ust)
        self.onizleme = Onizleme()
        self.onizleme.satirlar.connect(self.gonder)
        kok.addWidget(self.onizleme, 1)
        self.l_not = soluk_etiket("")
        self.mt.fn(lambda: self.l_not.setText(_(T.A_DEVRAL_NOT if self.b_devral.isChecked() else T.A_DEVRAL_IPUCU)))
        kok.addWidget(self.l_not)

        self.zaman = QTimer(self)
        self.zaman.setInterval(ONIZLEME_MS)
        self.zaman.timeout.connect(self.kare)
        self.sanal_guncelle(None)

    # -------- durum
    def sanal_guncelle(self, s: dict | None) -> None:
        self.sanal = s
        if self.m is None:
            self.l_durum.setText(_(T.A_YOK).format(hata=self.m_hata))
        elif s is None:
            self.l_durum.setText(_(T.A_KAPALI))
        else:
            g, y = (s.get("boyut") or [0, 0])[:2]
            self.l_durum.setText(_(T.A_ACIK).format(ekran=s.get("ekran", "?"), g=g, y=y))
        acik = s is not None
        baslatabilir = self.m is not None and hasattr(self.m, "masaustu_baslat")
        self.b_baslat.setVisible(not acik)
        self.b_baslat.setEnabled(baslatabilir and self._isci is None)
        if not baslatabilir:
            self.b_baslat.setToolTip(_(T.A_YOK).format(hata=self.m_hata or _(T.A_BASLAT_YOK)))
        self.b_durdur.setVisible(acik)
        self.b_durdur.setEnabled(self.m is not None and hasattr(self.m, "masaustu_durdur") and self._isci is None)
        self.b_devral.setEnabled(acik)
        if not acik:
            if self.b_devral.isChecked():
                self.b_devral.setChecked(False)
            self.onizleme.goster(None)
            self.onizleme.bos_metin = _(T.A_KAPALI)
        self._zamanlayici()

    def _calis(self, fn, metin: str):
        if self._isci is not None:
            return
        self.l_durum.setText(metin)
        self._isci = Isci(fn, self)
        self._isci.bitti.connect(self._bitti)
        self.b_baslat.setEnabled(False)
        self.b_durdur.setEnabled(False)
        self._isci.start()

    def _bitti(self, _sonuc, hata):
        self._isci = None
        s = None
        try:
            s = self.m.durum() if self.m is not None else None
        except Exception:  # noqa: BLE001
            s = None
        self.sanal_guncelle(s)
        if hata is not None:
            self.l_durum.setText(f"{self.l_durum.text()} — {getattr(hata, 'mesaj', None) or hata}")

    def baslat(self):
        if self.m is not None and hasattr(self.m, "masaustu_baslat"):
            self._calis(self.m.masaustu_baslat, _(T.A_BASLATILIYOR))

    def durdur(self):
        if self.m is not None and hasattr(self.m, "masaustu_durdur"):
            self.b_devral.setChecked(False)
            self._calis(self.m.masaustu_durdur, _(T.A_DURDURULUYOR))

    # -------- önizleme (yalnız görünürken)
    def _gorunur(self) -> bool:
        w = self.window()
        return self.isVisible() and not (w is not None and w.isMinimized())

    def _zamanlayici(self):
        if self.sanal is not None and self._gorunur():
            if not self.zaman.isActive():
                self.zaman.start()
                self.kare()
        else:
            self.zaman.stop()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._zamanlayici()

    def hideEvent(self, e):  # noqa: N802
        super().hideEvent(e)
        self.zaman.stop()

    def kare(self):
        if self.sanal is None or not self._gorunur():
            self.zaman.stop()
            return
        try:
            im = self.arka_f().goruntu()
        except Exception as e:  # noqa: BLE001 - masaüstü kapandı / X hatası
            self.onizleme.bos_metin = _(T.A_ONIZLEME_HATA).format(hata=getattr(e, 'mesaj', None) or e)
            self.onizleme.goster(None)
            return
        q, kaynak = pil_qimage(im, self.onizleme.hedef_boyut() if self.onizleme.kaynak.width() else None)
        self.onizleme.goster(q, kaynak)

    # -------- Devral
    def devral(self, acik: bool):
        yol = self.devral_yolu_f()
        if acik:
            from .durum import devral_icerik
            os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
            gecici = f"{yol}.{os.getpid()}"
            with open(gecici, "w") as f:
                f.write(devral_icerik())  # "panel <pid> <başlangıç>": panel çökerse ajan bayat dosyada beklemez
            os.replace(gecici, yol)
            if yol not in _DEVRAL_ATEXIT:
                _DEVRAL_ATEXIT.add(yol)
                atexit.register(_devral_temizle, yol)
            self.b_devral.setText(_(T.A_BIRAK))
            self.l_not.setText(_(T.A_DEVRAL_NOT))
            self.onizleme.devral = True
            self.onizleme.setFocus()
        else:
            self._girdi_kapat()
            try:
                os.remove(yol)
            except FileNotFoundError:
                pass
            self.b_devral.setText(_(T.A_DEVRAL))
            self.l_not.setText(_(T.A_DEVRAL_IPUCU))
            self.onizleme.devral = False
        self.onizleme.update()
        self.devral_degisti.emit(acik)

    def tazele(self) -> None:
        self.mt.tazele()
        if self._isci is None:  # başlatılıyor/durduruluyor metni iş bitince zaten yenilenir
            self.sanal_guncelle(self.sanal)
        self.onizleme.update()

    def _girdi_kapat(self):
        g, self.girdi = self.girdi, None
        if g is not None:
            try:
                g.kapat()
            except Exception:  # noqa: BLE001
                pass

    def gonder(self, satirlar: list[str]):
        """Devral girdisi → sanal arka ucun Girdi'si. denetle=None (insan), DUR her satırda geçerli."""
        if not self.onizleme.devral:
            return
        from ..hata import Dur, dur_denetle
        try:
            dur = None
            try:
                dur_denetle()
            except Dur as e:
                # DUR açıkken yalnız BIRAKMA satırları (buttonup/keyup) geçer: önceden basılan düğme basılı kalmasın
                birak = [s for s in satirlar if s.split(" ", 1)[0] in ("buttonup", "keyup")]
                if not birak or self.girdi is None or not hasattr(self.girdi, "insan_ham"):
                    raise
                satirlar, dur = birak, e
            if self.girdi is None:
                self.girdi = self.arka_f().girdi(etiket="panel devral", denetle=None)
            gonder = getattr(self.girdi, "insan_ham", None) or self.girdi.ham
            for s in satirlar:
                try:
                    gonder(s)
                except Dur as e:
                    if e.kod == 12 and s.split()[0] in ("wheel", "hwheel"):
                        if not self._tekerlek_uyarildi:
                            self._tekerlek_uyarildi = True
                            self.l_not.setText(_(T.A_TEKERLEK_YOK))
                        continue
                    raise
            if dur is not None:
                raise dur
        except Dur as e:
            self.l_not.setText(_(T.A_GIRDI_HATA).format(hata=e.mesaj))
            if e.kod != 13:
                self._girdi_kapat()
        except Exception as e:  # noqa: BLE001
            self.l_not.setText(_(T.A_GIRDI_HATA).format(hata=e))
            self._girdi_kapat()


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
        from .onay_diyalog import sure_metni
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
                it.setIcon(nokta(YESIL if g["sonuc"] == "izin" else KIRMIZI, 6))
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


# =========================================================================== Ayarlar

class AyarlarSekmesi(QScrollArea):
    kisayol_degisti = pyqtSignal(bool, str)
    dil_degisti = pyqtSignal(str)  # yeni etkin dil kodu (i18n yeniden yüklendikten SONRA)

    def __init__(self, parent=None, karar: A.KararAyarlari | None = None, cakisma_f=cakismalar):
        super().__init__(parent)
        self.karar = karar if karar is not None else A.KararAyarlari()
        self.cakisma_f = cakisma_f
        self.mt = Metinler()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        govde = QWidget()
        kok = QVBoxLayout(govde)
        kok.setSpacing(14)

        # ---- meşgulken
        g = self._grup(T.Y_MESGUL)
        gl = QFormLayout(g)
        if self.karar.var:
            mevcut = self.karar.oku()
            self.c_mesgul = QComboBox()
            self._doldur(self.c_mesgul, self.karar.mesgulken_secenek, T.Y_MESGUL_SECENEK)
            self._sec(self.c_mesgul, mevcut.get("mesgulken"))
            self.s_sure = QSpinBox()
            self.s_sure.setRange(*[int(v) for v in self.karar.sor_sure_aralik])
            self.mt.fn(lambda: self.s_sure.setSuffix(" " + _(T.Y_SN)))
            try:
                self.s_sure.setValue(int(mevcut.get("sor_sure") or 30))
            except (TypeError, ValueError):
                self.s_sure.setValue(30)
            self.c_cevapsiz = QComboBox()
            self._doldur(self.c_cevapsiz, self.karar.cevapsiz_secenek, T.Y_CEVAPSIZ_SECENEK)
            self._sec(self.c_cevapsiz, mevcut.get("cevapsiz"))
            gl.addRow(self._etiket(T.Y_MESGULKEN), self.c_mesgul)
            gl.addRow(self._etiket(T.Y_SOR_SURE), self.s_sure)
            gl.addRow(self._etiket(T.Y_CEVAPSIZ), self.c_cevapsiz)
            self.k_tam = None
            if "tam_ekranda_sor" in self.karar.anahtarlar:
                self.k_tam = QCheckBox()
                self.mt(self.k_tam.setText, T.Y_TAM_EKRAN)
                self.k_tam.setChecked(bool(mevcut.get("tam_ekranda_sor")))
                self.mt(self.k_tam.setToolTip, T.Y_TAM_EKRAN_NOT)
                gl.addRow("", self.k_tam)
            b = QPushButton()
            self.mt(b.setText, T.Y_KAYDET)
            b.clicked.connect(self.karar_kaydet)
            self.l_karar = soluk_etiket("")
            gl.addRow(b, self.l_karar)
        else:
            gl.addRow(self._soluk(T.Y_MESGUL_YOK))
        kok.addWidget(g)

        # ---- yasak pencereler
        g = self._grup(T.Y_YASAK)
        gl = QVBoxLayout(g)
        gl.addWidget(self._soluk(T.Y_YASAK_ACIKLAMA))
        self.yasak = QPlainTextEdit()
        f = self.yasak.font()
        f.setFamily("monospace")
        f.setStyleHint(f.StyleHint.Monospace)
        self.yasak.setFont(f)
        self.yasak.setMinimumHeight(150)
        gl.addWidget(self.yasak)
        sat = QHBoxLayout()
        self.l_yasak = QLabel("")
        self.l_yasak.setWordWrap(True)
        sat.addWidget(self.l_yasak, 1)
        b_geri = QPushButton()
        self.mt(b_geri.setText, T.Y_GERI_AL)
        b_geri.clicked.connect(self.yasak_yukle)
        b_kaydet = QPushButton()
        self.mt(b_kaydet.setText, T.Y_KAYDET)
        b_kaydet.clicked.connect(self.yasak_kaydet)
        sat.addWidget(b_geri)
        sat.addWidget(b_kaydet)
        gl.addLayout(sat)
        kok.addWidget(g)
        self.yasak_yukle()

        # ---- kısayol
        panel = A.panel_oku()
        g = self._grup(T.Y_KISAYOL)
        gl = QFormLayout(g)
        self.k_acik = QCheckBox()
        self.mt(self.k_acik.setText, T.Y_KISAYOL_AC)
        self.k_acik.setChecked(panel["kisayol_acik"])
        self.k_tus = QKeySequenceEdit(QKeySequence(panel["kisayol"]))
        self.k_tus.setMaximumWidth(340)
        if hasattr(self.k_tus, "setMaximumSequenceLength"):
            self.k_tus.setMaximumSequenceLength(1)
        if hasattr(self.k_tus, "setClearButtonEnabled"):
            self.k_tus.setClearButtonEnabled(True)
        # Qt tuş adlarını NativeText ile, Qt'nin kendi (sistem dili) çevirisiyle gösterir: Türkçe Qt çevirisi
        # "Meta+Seçenek+Vazgeç" yazıyordu. Kutu, KDE'nin ve kglobalshortcutsrc'nin kullandığı PortableText'i
        # (Meta+Alt+Esc) gösterir; kaydedilen değer zaten PortableText.
        self.k_tus.keySequenceChanged.connect(self._tus_yaz)
        self.k_tus.editingFinished.connect(self._tus_yaz)
        self._tus_yaz()
        self.l_kisayol = QLabel("")
        self.l_kisayol.setWordWrap(True)
        gl.addRow(self.k_acik)
        gl.addRow(self._etiket(T.Y_KISAYOL_TUS), self.k_tus)
        gl.addRow(self.l_kisayol)
        gl.addRow(self._soluk(T.Y_KISAYOL_NOT))
        self.k_acik.toggled.connect(self._kisayol_kaydet)
        self.k_tus.editingFinished.connect(self._kisayol_kaydet)
        kok.addWidget(g)
        self.cakisma_goster()

        # ---- dil
        g = self._grup(T.Y_DIL)
        gl = QFormLayout(g)
        self.c_dil = QComboBox()
        for kod, ad in dil_secenekleri():
            self.c_dil.addItem(ad, kod)
        self.mt.fn(self._dil_adlari)
        self._dil_secili()
        self.c_dil.activated.connect(lambda i: self.dil_sec(self.c_dil.itemData(i)))
        gl.addRow(self._etiket(T.Y_DIL), self.c_dil)
        self.l_dil = QLabel("")
        self.l_dil.setWordWrap(True)
        self.l_dil.setVisible(False)
        gl.addRow(self.l_dil)
        gl.addRow(self._soluk(T.Y_DIL_NOT))
        kok.addWidget(g)
        kok.addStretch(1)
        self.setWidget(govde)

    # -------- metin yardımcıları (dil değişince tazele() hepsini yeniden yazar)
    def _grup(self, msgid: str) -> QGroupBox:
        g = QGroupBox()
        self.mt(g.setTitle, msgid)
        return g

    def _etiket(self, msgid: str) -> QLabel:
        e = QLabel()
        self.mt(e.setText, msgid)
        return e

    def _soluk(self, msgid: str) -> QLabel:
        e = soluk_etiket("")
        self.mt(e.setText, msgid)
        return e

    def _doldur(self, c: QComboBox, anahtarlar, adlar: dict) -> None:
        for i, k in enumerate(anahtarlar):
            c.addItem("", k)
            self.mt.fn(lambda c=c, i=i, k=k: c.setItemText(i, _(adlar[k]) if k in adlar else str(k)))

    def _tus_yaz(self, *_a) -> None:
        kutu = self.k_tus.findChild(QLineEdit)
        if kutu is not None:
            kutu.setText(self.k_tus.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def tazele(self) -> None:
        self.mt.tazele()
        self._tus_yaz()
        self.cakisma_goster()
        for e in (getattr(self, "l_karar", None), self.l_yasak):  # eski dildeki "Kaydedildi." vb.
            if e is not None:
                e.setText("")

    # -------- dil
    def _dil_adlari(self) -> None:
        for kod, ad in dil_secenekleri():
            j = self.c_dil.findData(kod)
            if j >= 0:
                self.c_dil.setItemText(j, ad)

    def _dil_secili(self) -> None:
        self.c_dil.blockSignals(True)
        self.c_dil.setCurrentIndex(max(0, self.c_dil.findData(i18n.ayar_oku())))
        self.c_dil.blockSignals(False)

    def dil_sec(self, kod: str) -> bool:
        """Seçimi CONFIG_DIR/arayuz.json'a yaz, kataloğu yeniden yükle, dil_degisti yay (panel metinleri
        tazelenir). → True: seçim değişti."""
        if kod == i18n.ayar_oku():
            return False
        try:
            i18n.ayar_yaz(kod)
        except (OSError, ValueError) as e:
            self._dil_secili()
            self.l_dil.setText(_(T.Y_DIL_HATA).format(hata=e))
            self.l_dil.setVisible(True)
            return False
        yeni = i18n.yeniden_yukle()
        istenen = i18n.sistem_dili() if kod == i18n.OTOMATIK else kod
        self._dil_secili()
        self.dil_degisti.emit(yeni)  # → AnaPencere.tazele → bu sekmenin tazele()'si
        if yeni != istenen:  # DESKHAND_DIL bu süreçte dili zorluyor
            self.l_dil.setText(_(T.Y_DIL_ZORLA).format(dil=i18n.DILLER.get(yeni, yeni)))
            self.l_dil.setVisible(True)
        else:
            self.l_dil.setText("")
            self.l_dil.setVisible(False)
        return True

    @staticmethod
    def _sec(c: QComboBox, deger):
        i = c.findData(deger)
        if i >= 0:
            c.setCurrentIndex(i)

    def karar_kaydet(self):
        try:
            d = {"mesgulken": self.c_mesgul.currentData(), "sor_sure": self.s_sure.value(),
                 "cevapsiz": self.c_cevapsiz.currentData()}
            if self.k_tam is not None:
                d["tam_ekranda_sor"] = self.k_tam.isChecked()
            self.karar.yaz(d)
            self.l_karar.setText(_(T.Y_KAYDEDILDI))
        except Exception as e:  # noqa: BLE001
            self.l_karar.setText(str(e))

    def yasak_yukle(self):
        self.yasak.setPlainText(A.yasak_metni())
        self.l_yasak.setText("")

    def yasak_kaydet(self) -> bool:
        metin = self.yasak.toPlainText()
        h = A.yasak_dogrula(metin)
        if h:
            self.l_yasak.setText(_(T.Y_DESEN_HATA).format(no=h[0], hata=h[1]))
            return False
        A.yasak_kaydet(metin)
        self.l_yasak.setText(_(T.Y_KAYDEDILDI))
        return True

    def tus(self) -> str:
        s = self.k_tus.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        return s or VARSAYILAN_TUS

    def cakisma_goster(self) -> list:
        tus = self.tus()
        c = self.cakisma_f(tus)
        if c:
            b, e, aciklama = c[0]
            self.l_kisayol.setText(_(T.Y_KISAYOL_CAKISMA).format(tus=tus, eylem=aciklama, bilesen=b))
        else:
            self.l_kisayol.setText(_(T.Y_KISAYOL_BOS).format(tus=tus))
        return c

    def _kisayol_kaydet(self, *_a):
        d = A.panel_oku()
        d["kisayol_acik"], d["kisayol"] = self.k_acik.isChecked(), self.tus()
        A.panel_yaz(d)
        self.cakisma_goster()
        self.kisayol_degisti.emit(d["kisayol_acik"], d["kisayol"])

    def kisayol_durumu(self, metin: str):
        self.l_kisayol.setText(metin)


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


# =========================================================================== Sağlık

class SaglikSekmesi(QWidget):
    def __init__(self, parent=None, denetle=S.denetle):
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
            durum = QTableWidgetItem(_(T.H_VAR if d["ok"] else T.H_YOK))
            durum.setIcon(nokta(YESIL if d["ok"] else KIRMIZI, 6))
            self.tablo.setItem(i, 0, ad)
            self.tablo.setItem(i, 1, durum)
            self.tablo.setItem(i, 2, QTableWidgetItem(_(d["not"])))  # saglik.py notları msgid
        ok = sum(1 for d in sonuc if d["ok"])
        self.l_ozet.setText(_(T.H_OZET).format(ok=ok, n=len(sonuc)))

    def tazele(self) -> None:
        self.mt.tazele()
        if self.sonuc:
            self.goster(self.sonuc)


# =========================================================================== Ana pencere

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
        self.b_dur.setStyleSheet(f"QPushButton#dur {{ background: {RENK['dur']}; color: white; font-weight: 700;"
                                 f" border: none; border-radius: 6px; padding: 6px 18px; }}"
                                 f" QPushButton#dur:hover {{ background: {QColor(RENK['dur']).lighter(112).name()}; }}")
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
            metin += f" — {_(T.DUR_KAYNAK[k]) if k in T.DUR_KAYNAK else k}"
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


class AnaPencere(QMainWindow):
    dur_istendi = pyqtSignal()
    devam_istendi = pyqtSignal()

    def __init__(self, ilk_satirlar: list[dict] | None = None, parent=None, arka_f=_varsayilan_arka,
                 masaustu_m=None, karar=None, cakisma_f=cakismalar, simge_sor=None, saglik_f=S.denetle):
        super().__init__(parent)
        self.setWindowTitle(onay.PANEL_BASLIK)
        self.setObjectName("deskhandPanel")
        self.resize(1040, 680)
        self.kapaninca_gizle = True
        self.mt = Metinler()
        self._durum = Durum()
        self.devam_kutusu: QMessageBox | None = None
        merkez = QWidget()
        kok = QVBoxLayout(merkez)
        kok.setContentsMargins(10, 10, 10, 10)
        kok.setSpacing(8)
        self.serit = DurumSeridi()
        self.serit.dur_istendi.connect(self.dur_istendi.emit)
        self.serit.devam_istendi.connect(self.devam_istendi.emit)
        kok.addWidget(self.serit)
        self.sekmeler = QTabWidget()
        self.sekmeler.setDocumentMode(True)
        ilk = ilk_satirlar or []
        self.etkinlik = EtkinlikSekmesi(ilk)
        self.arka = ArkaPlanSekmesi(arka_f=arka_f, masaustu_m=masaustu_m)
        self.onaylar = OnaylarSekmesi()
        self.onaylar.gecmis_ekle(ilk)
        self.ayarlar = AyarlarSekmesi(karar=karar, cakisma_f=cakisma_f)
        self.simgeler = SimgelerSekmesi(sor=simge_sor)
        self.saglik = SaglikSekmesi(denetle=saglik_f)
        for w, ad, ikon in ((self.etkinlik, T.S_ETKINLIK, "view-list-details"),
                            (self.arka, T.S_ARKA, "video-display"),
                            (self.onaylar, T.S_ONAY, "dialog-question"),
                            (self.ayarlar, T.S_AYAR, "configure"),
                            (self.simgeler, T.S_SIMGE, "folder-pictures"),
                            (self.saglik, T.S_SAGLIK, "checkmark")):
            i = self.sekmeler.addTab(w, QIcon.fromTheme(ikon), "")
            if w is not self.onaylar:  # Onaylar'ın adı bekleyen sayısını taşır: durum_guncelle yazar
                self.mt(lambda m, i=i: self.sekmeler.setTabText(i, m), ad)
        self._onay_sekmesi_yaz()
        self.serit.onaylar_istendi.connect(lambda: self.sekmeler.setCurrentWidget(self.onaylar))
        self.ayarlar.dil_degisti.connect(self.tazele)
        kok.addWidget(self.sekmeler, 1)
        self.setCentralWidget(merkez)

    def durum_guncelle(self, d: Durum):
        self._durum = d
        self.serit.guncelle(d)
        self._onay_sekmesi_yaz()

    def _onay_sekmesi_yaz(self):
        n = self._durum.bekleyen
        self.sekmeler.setTabText(self.sekmeler.indexOf(self.onaylar),
                                 _(T.S_ONAY_SAYI).format(n=n) if n else _(T.S_ONAY))

    def tazele(self, _kod: str = ""):
        """Dil değişti (i18n yeniden yüklendi): tüm görünen metinler yeni dilde; içerik ve durum korunur."""
        self.mt.tazele()
        self.serit.tazele()
        for sekme in (self.etkinlik, self.arka, self.onaylar, self.ayarlar, self.simgeler, self.saglik):
            sekme.tazele()
        self._onay_sekmesi_yaz()

    def satirlar_geldi(self, satirlar: list[dict]):
        self.etkinlik.ekle(satirlar)
        self.onaylar.gecmis_ekle(satirlar)

    def arka_goster(self):
        self.sekmeler.setCurrentWidget(self.arka)

    def devam_sor(self) -> QMessageBox:
        """Tepsiden gelen Devam: BU pencerede (sınıfı yerleşik yasak listede: ajan tıklayamaz) onay sorar; yalnız
        "Devam et" → devam_istendi. Modal değil (olay döngüsü bloklanmaz); varsayılan/Esc/Enter = DUR açık kalsın."""
        k = self.devam_kutusu
        if k is not None:
            try:
                if k.isVisible():
                    k.raise_()
                    k.activateWindow()
                    return k
            except RuntimeError:  # silinmiş
                pass
        k = QMessageBox(self)
        k.setIcon(QMessageBox.Icon.Question)
        k.setWindowTitle(onay.PANEL_BASLIK)
        k.setText(_(T.DEVAM_SORU))
        k.setTextFormat(Qt.TextFormat.PlainText)
        evet = k.addButton(_(T.DEVAM_DUGME), QMessageBox.ButtonRole.AcceptRole)
        hayir = k.addButton(_(T.DEVAM_VAZGEC), QMessageBox.ButtonRole.RejectRole)
        evet.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Enter/boşluk "Devam" olmasın
        evet.setAutoDefault(False)
        k.setDefaultButton(hayir)
        k.setEscapeButton(hayir)
        k.b_evet, k.b_hayir = evet, hayir
        k.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        k.buttonClicked.connect(lambda b: self.devam_istendi.emit() if b is evet else None)
        self.devam_kutusu = k
        k.open()
        return k

    def closeEvent(self, e):  # noqa: N802
        # kullanıcının kapat düğmesi (kendiliğinden olay) → tepsiye gizlen; uygulama çıkışı/oturum kapanışı → kapan
        if self.kapaninca_gizle and e.spontaneous():
            e.ignore()
            self.hide()
            return
        super().closeEvent(e)

