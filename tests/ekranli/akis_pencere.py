"""ekran akis testi: sahte kurulum sihirbazı. MOD=takil → 'Kabul ediyorum' bir şey yapmaz (tekrar koruması);
MOD=hata → kurulum başarısız ekranı. Geçişler LOG dosyasına yazılır."""
import os, sys
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

LOG = os.environ.get("LOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "akis.log")
MOD = os.environ.get("MOD", "")
open(LOG, "w").close()


def log(s):
    with open(LOG, "a") as f:
        f.write(s + "\n")


app = QApplication(sys.argv)
yigin = QStackedWidget()
yigin.setWindowTitle(os.environ.get("BASLIK", "akis-test"))
yigin.resize(820, 520)


def sayfa(baslik, *ogeler):
    w = QWidget()
    L = QVBoxLayout(w)
    b = QLabel(baslik)
    b.setFont(QFont("Noto Sans", 20, QFont.Weight.Bold))
    L.addWidget(b)
    for o in ogeler:
        L.addWidget(o)
    L.addStretch(1)
    yigin.addWidget(w)
    return w


def git(i, ad):
    log(f"ekran: {ad}")
    yigin.setCurrentIndex(i)


ileri = QPushButton("İleri")
sayfa("Hoş geldiniz — kurulum sihirbazı", QLabel("Bu sihirbaz deneme uygulamasını kuracak."), ileri)
kabul = QPushButton("Kabul ediyorum")
kabul.setStyleSheet("background-color: #51995a; color: white; font-weight: bold; padding: 10px;")
red = QPushButton("Reddet")
red.setStyleSheet("background-color: #a04040; color: white; font-weight: bold; padding: 10px;")
sayfa("Lisans sözleşmesi", QLabel("Lütfen sözleşmeyi okuyun.\nDevam etmek için kabul edin."), kabul, red)
sayfa("Kuruluyor…", QLabel("Dosyalar kopyalanıyor, lütfen bekleyin."))
sayfa("Kurulum tamamlandı", QLabel("Uygulama kullanıma hazır."))
sayfa("Kurulum başarısız", QLabel("Disk dolu."))

ileri.clicked.connect(lambda: (log("tık: İleri"), git(1, "lisans")))


def kabul_et():
    log("tık: Kabul ediyorum")
    if MOD == "takil":
        return
    git(2, "kuruluyor")
    QTimer.singleShot(2500, lambda: git(4 if MOD == "hata" else 3, "basarisiz" if MOD == "hata" else "tamam"))


kabul.clicked.connect(kabul_et)
red.clicked.connect(lambda: log("tık: Reddet"))
log("ekran: hosgeldin")
yigin.show()
sys.exit(app.exec())
