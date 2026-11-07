"""python3 -m deskhand.gui [--tepsi] [--arka]: paneli başlat (ikinci kez başlatılırsa çalışanı öne getirir)."""
from __future__ import annotations

import argparse
import os
import sys


def _sinyal_kur(app, cik) -> None:
    """SIGTERM/SIGINT/SIGHUP → düzgün çıkış (bekleyen onaylar reddedilir, panel.pid silinir). Yoklama yok:
    signal.set_wakeup_fd + QSocketNotifier."""
    import signal
    import socket

    from PyQt6.QtCore import QSocketNotifier
    okur, yazar = socket.socketpair()
    okur.setblocking(False)
    yazar.setblocking(False)
    signal.set_wakeup_fd(yazar.fileno())
    bildirici = QSocketNotifier(okur.fileno(), QSocketNotifier.Type.Read, app)

    def uyan():
        try:
            okur.recv(64)
        except OSError:
            pass

    bildirici.activated.connect(uyan)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):  # SIGHUP: oturum kapanışı
        signal.signal(s, lambda *_: cik())  # app.quit() değil: gizlenen ana pencere çıkışı reddederdi
    app._sinyal = (okur, yazar, bildirici)  # çöpe gitmesin


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deskhand panel", description="Deskhand izleme/yönetme paneli")
    ap.add_argument("--tepsi", action="store_true", help="pencereyi açma, yalnız tepsi simgesi (oturum açılışı)")
    ap.add_argument("--arka", action="store_true", help="Arka plan ekranı sekmesini aç")
    a = ap.parse_args(argv)
    # Qt'nin GLib olay döngüsünü kapat: D-Bus jeepney ile (GLib'siz); GLib döngüsü başka D-Bus kitaplıklarıyla
    # (dbus-python) çakışabiliyor.
    os.environ.setdefault("QT_NO_GLIB", "1")
    from PyQt6.QtWidgets import QApplication

    from .. import onay, yollar
    app = QApplication(sys.argv[:1])
    app.setApplicationName(onay.PANEL_SINIF)
    app.setDesktopFileName(onay.PANEL_SINIF)  # Wayland app_id / X11 WM_CLASS = yasak listesindeki sınıf
    app.setQuitOnLastWindowClosed(False)
    from .panel import Panel, tek_ornek
    sunucu = tek_ornek(b"arka\n" if a.arka else b"goster\n")
    if sunucu is None:
        from .panel import baska_panel_var
        if onay.panel_canli() or baska_panel_var():
            return 0  # çalışan panel öne getirildi
        print(f"panel soketi açılamadı ({yollar.runtime_dir()})", file=sys.stderr)
        return 1
    p = Panel(app, sunucu, girdi_merkezi=True)
    _sinyal_kur(app, p.cik)
    if a.arka:
        p.arka_goster()
    elif not a.tepsi or p.tepsi is None or not p.tepsi.ikon.isSystemTrayAvailable():
        p.goster()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
