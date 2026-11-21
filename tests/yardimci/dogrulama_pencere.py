"""Faz 9b test penceresi (Qt): eylem sonrası doğrulama, döngü kesici, sürükleme, üçlü tık ve değiştirici tuş testleri.
Sabit yerleşim (kesin koordinatlar); olaylar LOG dosyasına yazılır (monotonik zaman damgalı).

  Sayaç etiketi + [Arttir] düğmesi : tıklanınca etiket DEĞİŞİR (küçük bölge değişimi, new_text)
  Metin kutusu                     : seçim değişince `secim=...` (üçlü tık = tüm satır)
  MOD ALANI                        : basınca `mod_tik <düğme> ctrl=0|1 shift=.. alt=.. meta=..`
  BOS ALAN                         : hiçbir şey yapmaz (sonuçsuz tıklama / döngü kesici)
  Sürükleme alanı                  : bas/hareket/bırak günlüğü; bırakınca çerçeve çizer (değişen bölge)"""
import os
import sys
import time

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QWidget

LOG = os.environ.get("LOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogrulama.log")
open(LOG, "w").close()


def log(s):
    with open(LOG, "a") as f:
        f.write(s + "\n")


DUGME_AD = {Qt.MouseButton.LeftButton: "sol", Qt.MouseButton.RightButton: "sag", Qt.MouseButton.MiddleButton: "orta"}


class Alan(QWidget):
    def __init__(self, ust, metin, renk, x, y, g, h):
        super().__init__(ust)
        self.metin, self.renk = metin, renk
        self.setGeometry(x, y, g, h)
        self.setMouseTracking(True)

    def paintEvent(self, e):
        q = QPainter(self)
        q.fillRect(self.rect(), QColor(*self.renk))
        q.setPen(QColor(10, 10, 10))
        q.setFont(QFont("Noto Sans", 16))
        q.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.metin)
        self.boya(q)

    def boya(self, q):
        pass


class ModAlani(Alan):
    def mousePressEvent(self, e):
        m = e.modifiers()
        log(f"mod_tik {DUGME_AD.get(e.button(), '?')} ctrl={int(bool(m & Qt.KeyboardModifier.ControlModifier))} "
            f"shift={int(bool(m & Qt.KeyboardModifier.ShiftModifier))} alt={int(bool(m & Qt.KeyboardModifier.AltModifier))} "
            f"meta={int(bool(m & Qt.KeyboardModifier.MetaModifier))} {time.monotonic():.3f}")


class OluAlan(Alan):
    def mousePressEvent(self, e):
        log(f"olu_tik {time.monotonic():.3f}")


class SurukleAlani(Alan):
    def __init__(self, *a):
        super().__init__(*a)
        self.bas = self.simdi = None
        self.kutu = None

    def mousePressEvent(self, e):
        p = e.position()
        self.bas = self.simdi = (p.x(), p.y())
        log(f"surukle_bas {DUGME_AD.get(e.button(), '?')} {p.x():.0f} {p.y():.0f} {time.monotonic():.3f}")

    def mouseMoveEvent(self, e):
        if e.buttons() != Qt.MouseButton.NoButton:
            p = e.position()
            self.simdi = (p.x(), p.y())
            log(f"surukle_hareket {p.x():.0f} {p.y():.0f}")

    def mouseReleaseEvent(self, e):
        p = e.position()
        log(f"surukle_birak {DUGME_AD.get(e.button(), '?')} {p.x():.0f} {p.y():.0f} {time.monotonic():.3f}")
        if self.bas:
            x0, y0, x1, y1 = self.bas[0], self.bas[1], p.x(), p.y()
            self.kutu = QRect(int(min(x0, x1)), int(min(y0, y1)), int(abs(x1 - x0)), int(abs(y1 - y0)))
            self.bas = None
            self.update()

    def boya(self, q):
        if self.kutu is not None:
            q.setPen(QPen(QColor(200, 0, 0), 4))
            q.setBrush(QColor(255, 255, 0))
            q.drawRect(self.kutu)


app = QApplication(sys.argv)
w = QWidget()
w.setWindowTitle(os.environ.get("BASLIK", "dogrulama-test"))
w.setFixedSize(760, 640)
w.setStyleSheet("QWidget { background-color: #f5f5f5; color: #101010; } QLineEdit { background-color: #ffffff; }")

sayac = QLabel("Sayac: 0", w)
sayac.setFont(QFont("Noto Sans", 20))
sayac.setGeometry(40, 30, 340, 50)
n = [0]


def arttir():
    n[0] += 1
    sayac.setText(f"Sayac degisti: {n[0]}")
    log(f"arttir {n[0]}")


b = QPushButton("Arttir", w)
b.setGeometry(40, 100, 160, 50)
b.clicked.connect(arttir)

kutu = QLineEdit("alfa beta gama delta", w)
kutu.setGeometry(40, 180, 340, 40)
kutu.setFont(QFont("Noto Sans", 14))
kutu.selectionChanged.connect(lambda: log(f"secim={kutu.selectedText()}") if kutu.selectedText() else None)

ModAlani(w, "MOD ALANI", (200, 220, 255), 40, 260, 300, 100)
OluAlan(w, "BOS ALAN", (230, 230, 230), 40, 400, 300, 100)
SurukleAlani(w, "SURUKLE", (180, 235, 180), 400, 40, 320, 300)
w.show()
sys.exit(app.exec())
