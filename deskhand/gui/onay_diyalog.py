"""Onay diyaloğu (docs/ARCHITECTURE.md §8): modal değil ama öne çıkan; "Bir kez izin ver" / "Reddet".

Kazara izne karşı:
- Varsayılan düğme ve odak Reddet; Enter/Return/Esc ve pencereyi kapatmak = Reddet.
- "Bir kez izin ver" klavye odağı ALMAZ (yalnız fareyle tıklanır) ve açılıştan sonra en az KURMA_MS devre dışıdır;
  bu süre dolduktan SONRA fare diyaloğun üzerinde gerçekten (en az HAREKET_PX) hareket etmeden de etkinleşmez:
  diyalog hızlı tıklayan (oyun oynayan) kullanıcının durağan imlecinin altında açılsa bile kazara tık izne dönüşmez.
  Qt tıklamayı yalnız basma + bırakma ikisi de etkin düğmedeyse sayar (devre dışıyken başlayan basış izin olmaz).
- Diyalog etkinleştirilmeden gösterilir (WA_ShowWithoutActivating): kullanıcının klavyesini çalmaz.
- Süre dolunca otomatik red; istek geri çekilirse (isteyen vazgeçti) diyalog kendiliğinden kapanır.
Pencere başlığı sabit: onay.ONAY_BASLIK; uygulama sınıfı onay.PANEL_SINIF (yasak pencere listesine eklenir).
"""
from __future__ import annotations

import os
import time

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtWidgets import (QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QSizePolicy, QStyle, QVBoxLayout, QWidget)

from .. import onay
from ..i18n import _
from . import metinler as T
from .dil import Metinler

KURMA_MS = 1500   # izin düğmesi en erken bu kadar sonra etkinleşebilir…
HAREKET_PX = 12   # …ve ancak bu süreden SONRA fare diyalog üzerinde en az bu kadar (|dx|+|dy|) hareket edince
GORUNTU_EN = 420
GORUNTU_BOY = 220


def sure_metni(sn: float) -> str:
    sn = max(0, int(sn + 0.999))
    return f"{sn // 60}:{sn % 60:02d}"


class OnayDiyalog(QDialog):
    karar_verildi = pyqtSignal(str, str)  # (istek id, "izin" | "red" | "sure" | "geri")

    def __init__(self, istek: dict, parent=None, yanitla=onay.yanitla, saat=time.time, kurma_ms: int = KURMA_MS,
                 istek_var=None, hareket_px: int = HAREKET_PX):
        super().__init__(parent)
        self.istek, self._yanitla, self.saat = istek, yanitla, saat
        self._istek_var = istek_var or (lambda: os.path.exists(onay.istek_yolu(self.istek_id)))
        self.bitti = False
        self.setObjectName("deskhandOnay")
        self.setWindowTitle(onay.ONAY_BASLIK)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(False)
        self.setMinimumWidth(460)
        self.mt = Metinler()  # dil değişince tazele()

        kok = QVBoxLayout(self)
        kok.setContentsMargins(20, 18, 20, 16)
        kok.setSpacing(12)

        ust = QHBoxLayout()
        ikon = QLabel()
        ikon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(40, 40))
        ikon.setAlignment(Qt.AlignmentFlag.AlignTop)
        ust.addWidget(ikon)
        soru = QLabel()
        self.mt(soru.setText, T.D_SORU)
        f = soru.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        f.setBold(True)
        soru.setFont(f)
        soru.setWordWrap(True)
        ust.addWidget(soru, 1)
        kok.addLayout(ust)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def deger(metin: str, kalin: bool = False) -> QLabel:
            e = QLabel(metin)
            e.setWordWrap(True)
            e.setTextFormat(Qt.TextFormat.PlainText)  # ajanın yazdığı metin HTML olarak yorumlanmasın
            e.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if kalin:
                ff = e.font()
                ff.setBold(True)
                e.setFont(ff)
            return e

        self.l_eylem = deger(istek.get("eylem", ""), kalin=True)
        self.l_hedef = deger(istek.get("hedef", ""))
        self.l_masaustu = deger("")
        ms = istek.get("masaustu", "ekran")
        self.mt.fn(lambda: self.l_masaustu.setText(_(T.MASAUSTU[ms]) if ms in T.MASAUSTU else str(ms or "")))

        def satir(msgid: str, alan: QLabel):
            e = QLabel()
            self.mt(e.setText, msgid)
            form.addRow(e, alan)

        satir(T.D_EYLEM, self.l_eylem)
        satir(T.D_HEDEF, self.l_hedef)
        satir(T.D_MASAUSTU, self.l_masaustu)
        if istek.get("ayrinti"):
            self.l_ayrinti = deger(istek["ayrinti"])
            satir(T.D_AYRINTI, self.l_ayrinti)
        if istek.get("pid"):
            satir(T.D_ISTEYEN, deger(f"PID {istek['pid']}"))
        kok.addLayout(form)

        self.l_goruntu = None
        g = istek.get("goruntu")
        if g and os.path.isfile(g):
            pm = QPixmap(g)
            if not pm.isNull():
                cer = QFrame()
                cer.setFrameShape(QFrame.Shape.StyledPanel)
                cl = QVBoxLayout(cer)
                cl.setContentsMargins(4, 4, 4, 4)
                self.l_goruntu = QLabel()
                self.l_goruntu.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if pm.width() > GORUNTU_EN or pm.height() > GORUNTU_BOY:  # yalnız küçült (büyütme bulanıklaştırır)
                    pm = pm.scaled(GORUNTU_EN, GORUNTU_BOY, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                self.l_goruntu.setPixmap(pm)
                cl.addWidget(self.l_goruntu)
                kok.addWidget(cer)

        self.cubuk = QProgressBar()
        self.cubuk.setTextVisible(False)
        self.cubuk.setFixedHeight(6)
        toplam = max(1.0, float(istek.get("son_zaman", 0)) - float(istek.get("zaman", 0) or saat()))
        self.toplam = toplam
        self.cubuk.setRange(0, 1000)
        kok.addWidget(self.cubuk)
        self.l_kalan = QLabel()
        self.l_kalan.setObjectName("muted")
        kok.addWidget(self.l_kalan)
        notu = QLabel()
        self.mt(notu.setText, T.D_NOT)
        notu.setWordWrap(True)
        notu.setEnabled(False)  # soluk (paletten)
        kok.addWidget(notu)

        dugmeler = QHBoxLayout()
        dugmeler.addStretch(1)
        self.b_red = QPushButton()
        self.mt(self.b_red.setText, T.D_RED)
        self.b_red.setDefault(True)
        self.b_red.setAutoDefault(True)
        self.b_red.clicked.connect(lambda: self._karar("red"))
        self.b_izin = QPushButton()
        self.mt(self.b_izin.setText, T.D_IZIN)
        self.b_izin.setAutoDefault(False)
        self.b_izin.setDefault(False)
        self.b_izin.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # yalnız fareyle: Enter/boşluk izne dönüşmez
        self.b_izin.setEnabled(kurma_ms <= 0)  # kurma_ms <= 0: koruma yok (yalnız testler)
        self._kurma_bitti = kurma_ms <= 0
        self._hareket_px = max(0, int(hareket_px)) if kurma_ms > 0 else 0
        self._ilk_konum = None
        if kurma_ms > 0:
            self.mt(self.b_izin.setToolTip, T.D_IZIN_IPUCU)
        self.b_izin.clicked.connect(lambda: self._karar("izin"))
        for b in (self.b_red, self.b_izin):
            b.setMinimumWidth(150)
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        dugmeler.addWidget(self.b_red)
        dugmeler.addWidget(self.b_izin)
        kok.addLayout(dugmeler)
        self.b_red.setFocus()
        for w in (self, *self.findChildren(QWidget)):  # gerçek fare hareketi: düğmesiz hareket olayları da gelsin
            w.setMouseTracking(True)
            w.installEventFilter(self)

        if kurma_ms > 0:
            QTimer.singleShot(kurma_ms, self._kur)
        self.sayac = QTimer(self)
        self.sayac.setInterval(250)
        self.sayac.timeout.connect(self._tik)
        self.sayac.start()
        self._tik()

    @property
    def istek_id(self) -> str:
        return self.istek.get("id", "")

    def _kur(self):
        """Kurma süresi doldu: bundan SONRAKİ ilk gerçek fare hareketi düğmeyi etkinleştirir."""
        if self.bitti:
            return
        self._kurma_bitti = True
        self._ilk_konum = None  # süre içindeki hareket sayılmaz
        if self._hareket_px <= 0:
            self.b_izin.setEnabled(True)

    def eventFilter(self, nesne, olay):  # noqa: N802 - Qt API
        if (olay.type() == QEvent.Type.MouseMove and self._kurma_bitti and not self.bitti
                and not self.b_izin.isEnabled()):
            p = olay.globalPosition()
            if self._ilk_konum is None:  # pencere imlecin altında açılınca gelen yapay hareket (aynı nokta) sayılmaz
                self._ilk_konum = p
            elif abs(p.x() - self._ilk_konum.x()) + abs(p.y() - self._ilk_konum.y()) >= self._hareket_px:
                self.b_izin.setEnabled(True)
        return False  # olay yutulmaz

    def kalan(self) -> float:
        return float(self.istek.get("son_zaman", 0)) - self.saat()

    def _tik(self):
        if self.bitti:
            return
        k = self.kalan()
        if k <= 0:
            self._karar("red", neden="sure")
            return
        if not self._istek_var():
            self._bitir("geri")  # isteyen vazgeçti / zaten yanıtlandı
            return
        self.cubuk.setValue(int(1000 * max(0.0, min(1.0, k / self.toplam))))
        self.l_kalan.setText(_(T.D_KALAN).format(s=sure_metni(k)))

    def _karar(self, karar: str, neden: str | None = None, kapat: bool = True):
        if self.bitti:
            return
        if karar == "izin" and (not self.b_izin.isEnabled() or self.kalan() <= 0):
            return
        self._yanitla(self.istek_id, karar)
        self._bitir(neden or karar, kapat)

    def _bitir(self, neden: str, kapat: bool = True):
        if self.bitti:
            return
        self.bitti = True
        self.sayac.stop()
        self.karar_verildi.emit(self.istek_id, neden)
        if kapat:
            self.close()

    def tazele(self):
        """Dil değişti: diyalog metinleri yeni dilde (ajanın yazdığı eylem/hedef/ayrıntı olduğu gibi kalır)."""
        self.mt.tazele()
        if not self.bitti:
            self._tik()

    def geri_cekildi(self):
        """Panel: istek artık bekleyenlerde değil (yanıtlandı/süresi doldu/isteyen vazgeçti)."""
        self._bitir("geri")

    # -------- klavye ve kapatma = red
    def keyPressEvent(self, e: QKeyEvent):  # noqa: N802 - Qt API
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self._karar("red")
            e.accept()
            return
        super().keyPressEvent(e)

    def reject(self):
        self._karar("red")

    def closeEvent(self, e):  # noqa: N802 - Qt API
        if not self.bitti:
            self._karar("red", kapat=False)  # iç içe close() yok: uygulama çıkışını engellemesin
        e.accept()
