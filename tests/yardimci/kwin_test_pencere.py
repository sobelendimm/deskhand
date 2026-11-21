"""KWin oturumu testleri için Qt penceresi (Wayland ya da xcb): aldığı olayları LOG dosyasına yazar.

Ögeler (renkleri ekran görüntüsünde konum bulmak için sabit): camgöbeği çerçeveli metin kutusu, eflatun düğme,
sarı tekerlek alanı, büyük başlık yazısı (OCR). Günlük satırları: platform, hazir, tik, yazi=, tus_bas/tus_birak,
fare_bas/fare_birak (düğme adıyla), tekerlek DY."""
import os
import sys
import time

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

LOG = os.environ["LOG"]
open(LOG, "w").close()


def log(s):
    with open(LOG, "a") as f:
        f.write(s + "\n")


ADLAR = {Qt.MouseButton.LeftButton: "sol", Qt.MouseButton.RightButton: "sag", Qt.MouseButton.MiddleButton: "orta"}


class Alan(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(120)
        self.setMouseTracking(True)

    def paintEvent(self, e):
        QPainter(self).fillRect(self.rect(), QColor(255, 255, 0))

    def wheelEvent(self, e):
        log(f"tekerlek {e.angleDelta().y()} {e.angleDelta().x()}")

    def mousePressEvent(self, e):
        log(f"fare_bas {ADLAR.get(e.button(), '?')} {time.monotonic():.3f}")

    def mouseReleaseEvent(self, e):
        log(f"fare_birak {ADLAR.get(e.button(), '?')} {time.monotonic():.3f}")


class Suzgec(QObject):
    def eventFilter(self, o, e):
        if o.isWindowType() and e.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and not e.isAutoRepeat():
            ad = "tus_bas" if e.type() == QEvent.Type.KeyPress else "tus_birak"
            log(f"{ad} {e.key():#x} {e.text()!r} {time.monotonic():.3f}")
        return False


app = QApplication(sys.argv)
s = Suzgec()
app.installEventFilter(s)
w = QWidget()
w.setWindowTitle(os.environ.get("BASLIK", "Deskhand KWin Test"))
w.setFixedSize(700, 460)
w.setStyleSheet("background-color: #ffffff;")
L = QVBoxLayout(w)
baslik = QLabel("DESKHAND KWINTEST")
baslik.setFont(QFont("Sans", 40, QFont.Weight.Bold))
baslik.setStyleSheet("color: #000000;")
L.addWidget(baslik)
kutu = QLineEdit()
kutu.setFont(QFont("Sans", 20))
kutu.setStyleSheet("border: 6px solid #00ffff; background-color: #ffffff; color: #000000;")
kutu.textChanged.connect(lambda t: log(f"yazi={t}"))
L.addWidget(kutu)
dugme = QPushButton("Kaydet")
dugme.setStyleSheet("background-color: #ff00ff; color: #000000; font-size: 24px; padding: 18px;")
dugme.clicked.connect(lambda: log("tik: Kaydet"))
L.addWidget(dugme)
L.addWidget(Alan())
w.show()
log(f"platform: {app.platformName()} wayland={os.environ.get('WAYLAND_DISPLAY', '')!r} display={os.environ.get('DISPLAY', '')!r}")
log("hazir")
sys.exit(app.exec())
