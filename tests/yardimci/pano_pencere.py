"""deskhand pano testleri için Qt penceresi (Qt, XCB): çok satırlı metin kutusu. İçeriği her değişiklikte LOG dosyasına
JSON satırı olarak yazar ({"metin": ...}); yapıştırma (ctrl+v) Qt'nin kendi pano okumasıyla (Deskhand'in pano
yardımcısından bağımsız bir X11 seçim istemcisi) çalışır. PANO_BUYUK=N: açılışta panoyu N karakterlik metinle doldurur
(Qt seçim sahibi olur; büyük veride INCR kullanır) ve "pano hazir" yazar."""
import json
import os
import sys

from PyQt6.QtWidgets import QApplication, QPlainTextEdit

LOG = os.environ["LOG"]
open(LOG, "w").close()


def log(satir):
    with open(LOG, "a") as f:
        f.write(satir + "\n")


app = QApplication(sys.argv)
kutu = QPlainTextEdit()
kutu.setWindowTitle(os.environ.get("BASLIK", "pano-test"))
kutu.resize(700, 400)
kutu.textChanged.connect(lambda: log(json.dumps({"metin": kutu.toPlainText()}, ensure_ascii=False)))
kutu.show()
buyuk = int(os.environ.get("PANO_BUYUK", "0"))
if buyuk:
    app.clipboard().setText(("büyük ğüş İÇ 😀 " * (buyuk // 14 + 1))[:buyuk])
    log("pano hazir")
sys.exit(app.exec())
