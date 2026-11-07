"""ekran aracı için test penceresi: tıklama/yazma olaylarını test.log'a yazar.

Ortam: LOG (olay günlüğü), BASLIK, HAZIR_MS (Durum: Hazır gecikmesi),
UYGULAMA_KIMLIGI (Wayland app_id = KWin pencere sınıfı; MPRIS eşleme testi), TAM_EKRAN=1 (tam ekran açıl),
KOMUT (denetim dosyası: test girdi göndermeden pencereyi yönetir; ilk satır sıra no, sonra satır satır
"tam" | "normal" | "yazi:METİN" (insana talimat şeridi; boş = temizle))."""
import os, sys, time
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtWidgets import (QApplication, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget)

LOG = os.environ.get("LOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.log")
open(LOG, "w").close()


def log(s):
    with open(LOG, "a") as f:
        f.write(s + "\n")


DUGME_AD = {Qt.MouseButton.LeftButton: "sol", Qt.MouseButton.RightButton: "sag", Qt.MouseButton.MiddleButton: "orta"}


class OyunAlani(QWidget):
    """Oyun girdisi testleri: tuş bas/bırak (otomatik tekrar HARİÇ) ve fare bas/hareket/bırak, monotonik
    zaman damgasıyla (test sürecinin time.monotonic() ile karşılaştırılabilir)."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(170)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def paintEvent(self, e):
        q = QPainter(self)
        q.fillRect(self.rect(), QColor(40, 60, 45))
        q.setPen(QColor(230, 230, 230))
        q.setFont(QFont("Noto Sans", 14))
        q.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "OYUN ALANI")

    def keyPressEvent(self, e):
        if not e.isAutoRepeat():
            log(f"tus_bas {e.text() or e.key()} {time.monotonic():.3f}")

    def keyReleaseEvent(self, e):
        if not e.isAutoRepeat():
            log(f"tus_birak {e.text() or e.key()} {time.monotonic():.3f}")

    def mousePressEvent(self, e):
        p = e.position()
        log(f"fare_bas {DUGME_AD.get(e.button(), '?')} {p.x():.0f} {p.y():.0f} {time.monotonic():.3f}")

    def mouseReleaseEvent(self, e):
        p = e.position()
        log(f"fare_birak {DUGME_AD.get(e.button(), '?')} {p.x():.0f} {p.y():.0f} {time.monotonic():.3f}")

    def mouseMoveEvent(self, e):
        p = e.position()
        tur = "fare_surukle" if e.buttons() != Qt.MouseButton.NoButton else "fare_ustunde"
        log(f"{tur} {p.x():.0f} {p.y():.0f} {time.monotonic():.3f}")


class SagDugme(QPushButton):
    def contextMenuEvent(self, e):
        log(f"sağ: {self.text()}")


class CiftEtiket(QLabel):
    def mouseDoubleClickEvent(self, e):
        log(f"çift: {self.text()}")


app = QApplication(sys.argv)
if os.environ.get("UYGULAMA_KIMLIGI"):
    app.setDesktopFileName(os.environ["UYGULAMA_KIMLIGI"])  # Wayland app_id → KWin resourceClass
w = QWidget()
w.setWindowTitle(os.environ.get("BASLIK", "ekran-test ANA"))
w.resize(760, 640)
L = QGridLayout(w)
durum = QLabel("Durum: Yükleniyor")
L.addWidget(durum, 0, 0, 1, 3)
QTimer.singleShot(int(os.environ.get("HAZIR_MS", "4000")), lambda: durum.setText("Durum: Hazır"))
for i, ad in enumerate(["Kaydet", "İptal", "Şifreyi sıfırla"]):
    b = SagDugme(ad)
    b.clicked.connect(lambda _, a=ad: log(f"tık: {a}"))
    L.addWidget(b, 1, i)
for i in range(2):
    b = QPushButton("Tamam")
    b.clicked.connect(lambda _, n=i + 1: log(f"tık: Tamam{n}"))
    L.addWidget(b, 2, i)
L.addWidget(CiftEtiket("Çift tıkla beni"), 2, 2)
L.addWidget(QLabel("E-posta:"), 3, 0)
eposta = QLineEdit()
eposta.textChanged.connect(lambda t: log(f"eposta={t}"))
L.addWidget(eposta, 3, 1, 1, 2)
L.addWidget(QLabel("Not alanı:"), 4, 0)
notlar = QLineEdit()


def not_degisti(t):
    log(f"not={t}")
    if len(t) >= 10 and "SEKME" not in w.windowTitle() and "ANA" in w.windowTitle():
        w.setWindowTitle("ekran-test BAŞKA SEKME")  # kullanıcının sekme değiştirmesini taklit eder


notlar.textChanged.connect(not_degisti)
L.addWidget(notlar, 4, 1, 1, 2)
satin = QPushButton("Satın al")
satin.clicked.connect(lambda: log("tık: Satın al"))
L.addWidget(satin, 5, 0)
for i, (ad, renk) in enumerate([("Onayla", "#51995a"), ("Vazgeç", "#a04040")]):
    rb = QPushButton(ad)
    rb.setStyleSheet(f"background-color: {renk}; color: white; font-weight: bold; padding: 6px;")
    rb.clicked.connect(lambda _, a=ad: log(f"tık: {a}"))
    L.addWidget(rb, 5, 1 + i)
L.addWidget(OyunAlani(), 6, 0, 1, 3)
KOMUT = os.environ.get("KOMUT")
# insana talimat şeridi: yalnız KOMUT varken, SABİT yükseklikte ve her zaman yerleşimde (metin gelince düğmeler
# kaymasın: onay beklerken hesaplanmış tıklama koordinatı geçerli kalmalı)
talimat = QLabel("")
talimat.setWordWrap(True)
talimat.setFixedHeight(72)
TALIMAT_STIL = "color: black; font-size: 18px; font-weight: bold; padding: 6px; background-color: {zemin};"
talimat.setStyleSheet(TALIMAT_STIL.format(zemin="transparent"))
if KOMUT:
    L.addWidget(talimat, 7, 0, 1, 3)
_son_sira = [None]


def komut_oku():
    """Denetim dosyası (ilk satır sıra no): yalnız yeni sıra no'da uygulanır."""
    try:
        with open(KOMUT) as f:
            satirlar = f.read().splitlines()
    except OSError:
        return
    if not satirlar or satirlar[0] == _son_sira[0]:
        return
    _son_sira[0] = satirlar[0]
    for k in satirlar[1:]:
        if k == "tam":
            w.showFullScreen()
            log("pencere: tam")
        elif k == "normal":
            w.showNormal()
            log("pencere: normal")
        elif k.startswith("yazi:"):
            talimat.setText(k[5:])
            talimat.setStyleSheet(TALIMAT_STIL.format(zemin="#f0c040" if k[5:] else "transparent"))


if KOMUT:
    _zamanlayici = QTimer()
    _zamanlayici.timeout.connect(komut_oku)
    _zamanlayici.start(150)
if os.environ.get("TAM_EKRAN") == "1":
    w.showFullScreen()
else:
    w.show()
sys.exit(app.exec())
