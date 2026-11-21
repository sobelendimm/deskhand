"""Erişilebilirlik (AT-SPI) eylem testleri için Qt penceresi: her denetim bir olayı LOG dosyasına yazar.
Çalıştırma (yalnız sanal masaüstünde): LOG=/yol/log PENCERE_BASLIK=ad python3 a11y_pencere.py"""
import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QListWidget, QMainWindow,
                             QPushButton, QRadioButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

LOG = os.environ.get("LOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "a11y.log")
open(LOG, "w").close()


def log(s):
    with open(LOG, "a") as f:
        f.write(s + "\n")


app = QApplication(sys.argv)
pencere = QMainWindow()
pencere.setWindowTitle(os.environ.get("PENCERE_BASLIK", "a11y-test"))
pencere.resize(520, 560)

merkez = QWidget()
dikey = QVBoxLayout(merkez)
dikey.addWidget(QLabel("Erişilebilirlik deneme penceresi"))

for ad in ("Kaydet", "Tamam", "Satın al"):
    d = QPushButton(ad)
    d.clicked.connect(lambda _=False, ad=ad: log(f"tikla:{ad}"))
    dikey.addWidget(d)

pasif = QPushButton("Pasif düğme")
pasif.setEnabled(False)
pasif.clicked.connect(lambda: log("tikla:Pasif düğme"))
dikey.addWidget(pasif)

onay = QCheckBox("Onayla")
onay.toggled.connect(lambda v: log(f"isaret:Onayla:{int(v)}"))
dikey.addWidget(onay)

radyo = QRadioButton("Seçenek A")
radyo.toggled.connect(lambda v: log(f"radyo:Seçenek A:{int(v)}"))
dikey.addWidget(radyo)

giris = QLineEdit()
giris.setAccessibleName("Ad")
giris.textChanged.connect(lambda t: log(f"metin:Ad:{t}"))
dikey.addWidget(giris)

gizli = QLineEdit()
gizli.setAccessibleName("Parola")
gizli.setEchoMode(QLineEdit.EchoMode.Password)
gizli.textChanged.connect(lambda t: log(f"metin:Parola:{t}"))
dikey.addWidget(gizli)

kutu = QComboBox()
kutu.setAccessibleName("Renk")
kutu.addItems(["Kırmızı", "Yeşil", "Mavi"])
kutu.currentIndexChanged.connect(lambda i: log(f"secim:Renk:{kutu.itemText(i)}"))
dikey.addWidget(kutu)

adet = QSpinBox()
adet.setAccessibleName("Adet")
adet.setRange(0, 100)
adet.valueChanged.connect(lambda v: log(f"deger:Adet:{v}"))
dikey.addWidget(adet)

kaydirgac = QSlider(Qt.Orientation.Horizontal)
kaydirgac.setAccessibleName("Ses")
kaydirgac.setRange(0, 10)
kaydirgac.valueChanged.connect(lambda v: log(f"deger:Ses:{v}"))
dikey.addWidget(kaydirgac)

liste = QListWidget()
liste.setAccessibleName("Liste")
liste.addItems(["Birinci", "İkinci", "Üçüncü"])
liste.currentTextChanged.connect(lambda t: log(f"liste:{t}"))
liste.itemSelectionChanged.connect(lambda: log("liste-secim:" + ",".join(i.text() for i in liste.selectedItems())))
liste.setMaximumHeight(70)
dikey.addWidget(liste)

sekmeler = QTabWidget()
sekmeler.addTab(QLabel("genel sayfa"), "Genel")
sekmeler.addTab(QLabel("gelişmiş sayfa"), "Gelişmiş")
sekmeler.currentChanged.connect(lambda i: log(f"sekme:{sekmeler.tabText(i)}"))
dikey.addWidget(sekmeler)

pencere.setCentralWidget(merkez)
menu = pencere.menuBar().addMenu("Dosya")
for ad in ("Aç", "Kaydet menü"):
    e = QAction(ad, pencere)
    e.triggered.connect(lambda _=False, ad=ad: log(f"menu:{ad}"))
    menu.addAction(e)

pencere.show()
log("hazir")
sys.exit(app.exec())
