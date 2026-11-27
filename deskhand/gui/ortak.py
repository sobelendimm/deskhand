"""Panel ortak yardımcıları: arka iş parçacığı (Isci), durum renkleri, etiket/nokta yardımcıları."""
from __future__ import annotations

import time

from PyQt6.QtCore import (Qt, QThread, pyqtSignal)
from PyQt6.QtGui import QColor, QIcon, QPalette, QPixmap
from PyQt6.QtWidgets import (QLabel)

from ..i18n import N_, _
from . import metinler as T

# the panel's own closed-fail DUR source (guvenlik.DUR_KAPALI_BASARISIZ; review INC5 O4/O5)
_DUR_KAYNAK_PANEL = {"panel-kapali-basarisiz": N_("panel durdurdu: cüzdandaki DUR kaydı okunamıyor")}

ONIZLEME_MS = 500  # ~2 fps (Devral açıkken: girdi geri bildirimi)
IZLEME_MS = 1000  # yalnız izlerken 1 fps (her karede yasak pencere denetimi: pencere listesi okunur)
MASA_LISTE_MS = 2000  # masaüstü listesi yenileme (yalnız sekme görünürken)
YESIL, KIRMIZI, SARI = "#2f9e44", "#e03131", "#e8a317"


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
