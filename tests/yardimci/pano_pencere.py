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
if os.environ.get("SINIF"):  # WM_CLASS sınıfı (xcb: uygulama adı): örn. SINIF=xterm → uçbirim sınıflı pencere
    app.setApplicationName(os.environ["SINIF"])
    app.setDesktopFileName(os.environ["SINIF"])  # Wayland (KWin oturumu): sınıf = xdg app_id
kutu = QPlainTextEdit()
kutu.setWindowTitle(os.environ.get("BASLIK", "pano-test"))
kutu.resize(700, 400)
kutu.textChanged.connect(lambda: log(json.dumps({"metin": kutu.toPlainText()}, ensure_ascii=False)))
if os.environ.get("SINIF") in ("xterm", "konsole", "kitty", "alacritty", "foot"):
    # uçbirim taklidi: gerçek uçbirimler gibi ctrl+shift+v yapıştırır (Deskhand uçbirim sınıfında bu tuşu kullanır)
    from PyQt6.QtGui import QKeySequence, QShortcut
    QShortcut(QKeySequence("Ctrl+Shift+V"), kutu, activated=kutu.paste)
kutu.show()
buyuk = int(os.environ.get("PANO_BUYUK", "0"))


def pano_doldur():
    app.clipboard().setText(("büyük ğüş İÇ 😀 " * (buyuk // 14 + 1))[:buyuk])
    log("pano hazir")


if buyuk:
    if app.platformName() == "wayland":
        # Wayland: istemci panoyu yalnız klavye odağı varken (geçerli bir olay seri numarasıyla) ayarlayabilir →
        # pencere etkinleşince doldur (KWin oturumunda yeni pencere odak alır)
        from PyQt6.QtCore import QTimer

        def etkin_olunca():
            if kutu.isActiveWindow():
                pano_doldur()
            else:
                QTimer.singleShot(50, etkin_olunca)
        QTimer.singleShot(50, etkin_olunca)
    else:
        pano_doldur()
sys.exit(app.exec())
