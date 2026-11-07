"""Tepsi testi yardımcısı: Deskhand panelini (tepsi simgesiyle) BU süreçte kurar ve stdin'den gelen komutlarla
tepsi menüsünün eylemlerini DOĞRUDAN tetikler (D-Bus menüsü üzerinden değil; kullanıcının menüden "DUR"a
basmasıyla aynı yol: QAction → Tepsi sinyali → Panel.dur()).

Ortam: testin DESKHAND_* geçici klasörleri (ortak/_yalitim alt süreçlere geçirir).
Protokol (satır satır): hazır olunca "hazir <pid>" yazar.
  dur | devam        tepsi menüsündeki DUR / Devam eylemini tetikle → "tamam <komut>"
  menu               → "menu dur=<0|1> devam=<0|1>" (görünürlük)
  cik                → paneli kapat, çık
"""
import os
import sys

os.environ.setdefault("QT_NO_GLIB", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PyQt6.QtCore import QSocketNotifier  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand import onay  # noqa: E402


def yaz(s):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def main():
    app = QApplication(sys.argv[:1])
    app.setApplicationName(onay.PANEL_SINIF)
    app.setDesktopFileName(onay.PANEL_SINIF)
    app.setQuitOnLastWindowClosed(False)
    from deskhand.gui.panel import Panel, tek_ornek
    sunucu = tek_ornek()
    if sunucu is None:
        yaz("hata panel-zaten-calisiyor")
        return 1
    p = Panel(app, sunucu)
    if p.tepsi is None:
        yaz("hata tepsi-yok")
        return 1
    tampon = [b""]

    def oku():
        veri = os.read(0, 4096)
        if not veri:
            p.cik()
            return
        tampon[0] += veri
        while b"\n" in tampon[0]:
            satir, tampon[0] = tampon[0].split(b"\n", 1)
            k = satir.decode().strip()
            if k == "dur":
                p.tepsi.a_dur.trigger()
                yaz("tamam dur")
            elif k == "devam":
                p.tepsi.a_devam.trigger()
                yaz("tamam devam")
            elif k == "devam-kutusu":  # tepsi Devam'ı panelde onay sorar: kutu açık mı?
                kutu = p.pencere.devam_kutusu
                yaz(f"kutu {int(bool(kutu is not None and kutu.isVisible()))}")
            elif k in ("devam-onayla", "devam-vazgec"):  # kutudaki düğmeye (insan yerine) bas
                kutu = p.pencere.devam_kutusu
                if kutu is None:
                    yaz("hata kutu yok")
                else:
                    (kutu.b_evet if k == "devam-onayla" else kutu.b_hayir).click()
                    yaz(f"tamam {k}")
            elif k == "menu":
                p.izleyici.yenile()
                yaz(f"menu dur={int(p.tepsi.a_dur.isVisible())} devam={int(p.tepsi.a_devam.isVisible())}")
            elif k == "cik":
                yaz("tamam cik")
                p.cik()
            else:
                yaz(f"hata bilinmeyen {k}")

    bildirici = QSocketNotifier(0, QSocketNotifier.Type.Read, app)
    bildirici.activated.connect(oku)
    app._bildirici = bildirici  # çöpe gitmesin
    yaz(f"hazir {os.getpid()}")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
