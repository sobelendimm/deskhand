"""Sakin örnek sayfa penceresi (UX-K): ornek_sayfa.html'i ağsız gösterir (QTextBrowser; dış bağlantı açılmaz).

Kullanıcıya gösterilen görüntülerde (önce/sonra panosu, demo) arka plan masaüstünde açılan pencere budur; piksel
algılayan testlerin renkli test sayfası (kwin_test_pencere.py) kullanıcı görüntülerine girmez.
Ortam: BASLIK (pencere başlığı), GENISLIK/YUKSEKLIK (varsayılan 900x620)."""
import os
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QTextBrowser

YOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ornek_sayfa.html")

app = QApplication(sys.argv)
w = QTextBrowser()
w.setOpenLinks(False)  # ağ yok: bağlantılar açılmaz
w.setStyleSheet("QTextBrowser { background: #232629; border: none; }")
w.setSource(QUrl.fromLocalFile(YOL))
w.setWindowTitle(os.environ.get("BASLIK", "Kent Günlüğü — Örnek sayfa"))
w.resize(int(os.environ.get("GENISLIK", "900")), int(os.environ.get("YUKSEKLIK", "620")))
w.show()
sys.exit(app.exec())
