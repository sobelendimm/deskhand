"""Dosya izleyici: günlük, DUR, sanal masaüstü, Devral ve onay istekleri → Qt sinyalleri.

QFileSystemWatcher değişikliği bildirir (150 ms birleştirilir); ek olarak düşük sıklıkta yoklama yapılır
(çalışırken/onay beklerken 1 Hz, boştayken 3 sn): "çalışıyor → boşta" geçişi dosya değişmeden olur.
Her tur yalnız birkaç stat + küçük onay dizininin listesi; sanal masaüstü doğrulaması (/proc) en çok 10 sn'de bir
ya da çalışma dizini değişince.
"""
from __future__ import annotations

import os
import time

from PyQt6.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal

from .. import guvenlik, onay, yollar
from . import durum as D
from .gunluk_okur import GunlukOkuyucu

ERTELE_MS = 150
YOKLA_CALISIRKEN_MS = 1000
YOKLA_BOSTA_MS = 3000
SANAL_YENILE_SN = 10.0
TEMIZLE_SN = 30.0


class Izleyici(QObject):
    satirlar_geldi = pyqtSignal(list)
    durum_degisti = pyqtSignal(object)
    onaylar_degisti = pyqtSignal(list)
    sanal_degisti = pyqtSignal(object)

    def __init__(self, parent=None, saat=time.time, sanal_f=D.sanal_durum, baslat: bool = True):
        super().__init__(parent)
        self.saat, self.sanal_f = saat, sanal_f
        self.okuyucu = GunlukOkuyucu(saat=saat)
        self.ilk_satirlar = self.okuyucu.ilk()
        self.son_satir = self.ilk_satirlar[-1] if self.ilk_satirlar else None
        self.durum = D.Durum()
        self.bekleyen: list[dict] = []
        self.sanal: dict | None = None
        self._sanal_an = -1e9
        self._sanal_imza = None
        self._temiz_an = 0.0
        for d in (yollar.runtime_dir(), onay.dizin()):
            try:
                os.makedirs(d, mode=0o700, exist_ok=True)
            except OSError:
                pass
        self.fsw = QFileSystemWatcher(self)
        self.fsw.fileChanged.connect(self._tetikle)
        self.fsw.directoryChanged.connect(self._dizin_degisti)
        self._erte = QTimer(self)
        self._erte.setSingleShot(True)
        self._erte.setInterval(ERTELE_MS)
        self._erte.timeout.connect(self.yenile)
        self._yokla = QTimer(self)
        self._yokla.setInterval(YOKLA_BOSTA_MS)
        self._yokla.timeout.connect(self.yenile)
        self._izle_yollari()
        if baslat:
            self._yokla.start()
            QTimer.singleShot(0, lambda: self.yenile(sanal_zorla=True))

    # -------- izleme
    def _izle_yollari(self) -> None:
        istenen = [yollar.gunluk_dizin(), self.okuyucu.bugunku(), yollar.runtime_dir(), onay.dizin()]
        eski = [y for y in self.fsw.files() if y not in istenen]  # dünün günlük dosyası: izlemeyi bırak
        if eski:
            self.fsw.removePaths(eski)
        var = set(self.fsw.files()) | set(self.fsw.directories())
        yeni = [y for y in istenen if y not in var and os.path.exists(y)]
        if yeni:
            self.fsw.addPaths(yeni)

    def _tetikle(self, *_):
        if not self._erte.isActive():
            self._erte.start()

    def _dizin_degisti(self, yol: str):
        if yol == yollar.runtime_dir():
            self._sanal_an = -1e9  # sanal.json / devral / dur değişmiş olabilir
        self._tetikle()

    # -------- tur
    def yenile(self, sanal_zorla: bool = False) -> None:
        self._izle_yollari()
        simdi = self.saat()
        satirlar = self.okuyucu.yeni()
        if satirlar:
            self.son_satir = satirlar[-1]
            self.satirlar_geldi.emit(satirlar)
        if simdi - self._temiz_an > TEMIZLE_SN:
            self._temiz_an = simdi
            onay.temizle(simdi)
        bekleyen = onay.bekleyenler(simdi)
        if [b["id"] for b in bekleyen] != [b["id"] for b in self.bekleyen]:
            self.bekleyen = bekleyen
            self.onaylar_degisti.emit(bekleyen)
        self._sanal_yenile(simdi, sanal_zorla)
        d = D.durum_turet(guvenlik.dur_kaynagi(), self.son_satir, self.okuyucu.son_degisim(), simdi,
                          len(bekleyen), self.sanal, D.devral_var())
        if d != self.durum:
            self.durum = d
            self.durum_degisti.emit(d)
        hizli = d.ad in ("ekran", "arka") or d.bekleyen or d.devral
        aralik = YOKLA_CALISIRKEN_MS if hizli else YOKLA_BOSTA_MS
        if self._yokla.interval() != aralik:
            self._yokla.setInterval(aralik)

    def _sanal_imzasi(self):
        try:
            st = os.stat(os.path.join(yollar.runtime_dir(), "sanal.json"))
            return (st.st_ino, st.st_mtime_ns)
        except OSError:
            return None

    def _sanal_yenile(self, simdi: float, zorla: bool) -> None:
        imza = self._sanal_imzasi()
        if not zorla and imza == self._sanal_imza and simdi - self._sanal_an < SANAL_YENILE_SN:
            return
        self._sanal_imza, self._sanal_an = imza, simdi
        s = self.sanal_f() if imza is not None else None
        if (s is None) != (self.sanal is None) or (s and self.sanal and s.get("ekran") != self.sanal.get("ekran")):
            self.sanal = s
            self.sanal_degisti.emit(s)
        else:
            self.sanal = s

    def durdur(self) -> None:
        self._yokla.stop()
        self._erte.stop()
