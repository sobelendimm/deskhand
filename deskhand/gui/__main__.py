"""python3 -m deskhand.gui [--tepsi] [--arka] [--gorev]: paneli başlat (ikinci kez başlatılırsa çalışanı öne getirir)."""
from __future__ import annotations

import argparse
import os
import sys

from ..i18n import _


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


AF_UNIX_SINIR = 107  # sockaddr_un.sun_path 108 bayt (sonlandırıcı NUL dahil): yol en çok 107 bayt


def soket_acilamadi_iletisi(ad: str, dizin: str) -> str:
    """"Panel soketi açılamadı" iletisi; soket yolu AF_UNIX sınırını aşıyorsa (çok uzun RUNTIME_DIR/XDG_RUNTIME_DIR)
    nedeni ve çaresi (daha kısa bir çalışma dizini) iletiye eklenir."""
    ileti = _("panel soketi açılamadı ({dizin})").format(dizin=dizin)
    uzunluk = len(os.fsencode(ad))
    if uzunluk > AF_UNIX_SINIR:
        ileti += _(": soket yolu {uzunluk} bayt, AF_UNIX sınırı {sinir}; DESKHAND_RUNTIME_DIR'i daha kısa bir "
                   "dizine ayarla").format(uzunluk=uzunluk, sinir=AF_UNIX_SINIR)
    return ileti


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deskhand panel", description="Deskhand izleme/yönetme paneli")
    ap.add_argument("--tepsi", action="store_true", help="pencereyi açma, yalnız tepsi simgesi (oturum açılışı)")
    ap.add_argument("--arka", action="store_true", help="Arka plan ekranı sekmesini aç")
    ap.add_argument("--gorev", action="store_true", help="Görev sekmesini aç (Claude'a görev ver)")
    a = ap.parse_args(argv)
    # Qt'nin GLib olay döngüsünü kapat: D-Bus jeepney ile (GLib'siz); GLib döngüsü başka D-Bus kitaplıklarıyla
    # (dbus-python) çakışabiliyor.
    os.environ.setdefault("QT_NO_GLIB", "1")
    from PyQt6.QtWidgets import QApplication

    from .. import onay, yollar
    app = QApplication(sys.argv[:1])
    from .. import gorev_kipi
    gorev_kipi.GOZLEMCI = True  # panel önizlemesi görev masaüstünü görebilir (kullanıcının kendi süreci)
    app.setApplicationName(onay.PANEL_SINIF)
    app.setDesktopFileName(onay.PANEL_SINIF)  # Wayland app_id / X11 WM_CLASS = yasak listesindeki sınıf
    app.setQuitOnLastWindowClosed(False)
    from .panel import Panel, tek_ornek
    sunucu = tek_ornek(b"gorev\n" if a.gorev else b"arka\n" if a.arka else b"goster\n")
    if sunucu is None:
        from .panel import baska_panel_var
        if onay.panel_canli() or baska_panel_var():
            return 0  # çalışan panel öne getirildi
        from .panel import soket_adi
        print(soket_acilamadi_iletisi(soket_adi(), yollar.runtime_dir()), file=sys.stderr)
        return 1
    from .panel import istisna_yakalayici_kur
    istisna_yakalayici_kur()  # Panel kurulurken de: yakalanmayan istisna SIGABRT olmasın
    p = Panel(app, sunucu, girdi_merkezi=True)
    istisna_yakalayici_kur(p)  # artık tepsi bildirimiyle
    _sinyal_kur(app, p.cik)
    if a.gorev:
        p.gorev_goster()
    elif a.arka:
        p.arka_goster()
    elif not a.tepsi or p.tepsi is None or not p.tepsi.ikon.isSystemTrayAvailable():
        p.goster()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
