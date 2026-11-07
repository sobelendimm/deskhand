"""Panel denetleyicisi: izleyici + tepsi + pencere + onay diyalogları + genel kısayol + tek örnek."""
from __future__ import annotations

import fcntl
import os
import time

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from .. import guvenlik, onay, yollar
from ..gunluk import gunluk
from ..i18n import _
from . import ayar as A
from . import metinler as T
from .durum import Durum
from .izleyici import Izleyici
from .kisayol import GenelKisayol
from .onay_diyalog import OnayDiyalog
from .pencere import AnaPencere
from .tepsi import Tepsi, durum_simgesi

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIMGE_SVG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "deskhand.svg")


def soket_adi() -> str:
    """Tek örnek soketi (çalışma dizininde: testlerde geçici dizine düşer)."""
    return os.path.join(yollar.runtime_dir(), "panel.sock")


def kilit_adi() -> str:
    return os.path.join(yollar.runtime_dir(), "panel.lock")


def _mesaj_gonder(ad: str, mesaj: bytes, sure_ms: int = 400) -> bool:
    s = QLocalSocket()
    s.connectToServer(ad)
    if not s.waitForConnected(sure_ms):
        return False
    s.write(mesaj)
    s.flush()
    s.waitForBytesWritten(sure_ms)
    s.disconnectFromServer()
    return True


def baska_panel_var() -> bool:
    """Tek örnek kilidini başka bir (canlı) panel tutuyor mu."""
    try:
        with open(kilit_adi(), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def tek_ornek(mesaj: bytes = b"goster\n", deneme_ms: int = 3000) -> QLocalServer | None:
    """Başka panel çalışıyorsa ona `mesaj` gönder → None. Değilse dinleyen sunucu döner.

    Tek örnek ölçütü soket değil, panelin ÖMRÜ boyunca tuttuğu flock kilidi (RUNTIME_DIR/panel.lock; süreç ölünce
    çekirdek bırakır). Böylece meşgul (yanıt veremeyen) ya da henüz açılmakta olan bir panelin soketi silinip ikinci
    panel açılmaz (iki panel → panel.pid ezilir → onaylar "panel yok"/uyuşmaz sayılırdı)."""
    ad = soket_adi()
    os.makedirs(os.path.dirname(ad), mode=0o700, exist_ok=True)
    kilit = open(kilit_adi(), "a")
    try:
        fcntl.flock(kilit, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        kilit.close()
        # başka panel canlı (ya da açılıyor): ona ilet; soketine DOKUNMA
        bitis = time.monotonic() + deneme_ms / 1000
        while not _mesaj_gonder(ad, mesaj) and time.monotonic() < bitis:
            time.sleep(0.1)
        return None
    QLocalServer.removeServer(ad)  # kilit bizde: soket varsa ölü panelden kalmıştır
    sunucu = QLocalServer()
    sunucu.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not sunucu.listen(ad):
        kilit.close()
        return None
    sunucu._kilit = kilit  # sunucu yaşadıkça kilit tutulur
    return sunucu


def uygulama_simgesi() -> QIcon:
    yedek = QIcon(SIMGE_SVG) if os.path.isfile(SIMGE_SVG) else durum_simgesi(Durum())
    return QIcon.fromTheme(onay.PANEL_SINIF, yedek)


class Panel(QObject):
    def __init__(self, app: QApplication, sunucu: QLocalServer | None = None, tepsi: bool = True,
                 izleyici: Izleyici | None = None, kisayol: GenelKisayol | None = None, diyalog_kurma_ms=None,
                 **pencere_kw):
        super().__init__()
        self.app = app
        self.izleyici = izleyici or Izleyici(self)
        self.pencere = AnaPencere(self.izleyici.ilk_satirlar, **pencere_kw)
        self.pencere.setWindowIcon(uygulama_simgesi())
        self.tepsi = Tepsi(self) if tepsi else None
        self.kisayol = kisayol or GenelKisayol(self)
        self.diyaloglar: dict[str, OnayDiyalog] = {}
        self.diyalog_kurma_ms = diyalog_kurma_ms
        self.sunucu = sunucu
        if sunucu is not None:
            sunucu.newConnection.connect(self._baglanti)

        iz = self.izleyici
        iz.satirlar_geldi.connect(self.pencere.satirlar_geldi)
        iz.durum_degisti.connect(self._durum)
        iz.onaylar_degisti.connect(self._onaylar)
        iz.sanal_degisti.connect(self.pencere.arka.sanal_guncelle)
        self.pencere.dur_istendi.connect(self.dur)
        self.pencere.devam_istendi.connect(self.devam)
        self.pencere.onaylar.ac_istendi.connect(self.diyalog_one)
        self.pencere.ayarlar.kisayol_degisti.connect(self.kisayol_ayarla)
        self.kisayol.basildi.connect(self.dur)
        self.kisayol.hata.connect(lambda m: self.pencere.ayarlar.kisayol_durumu(_(T.Y_KISAYOL_HATA).format(hata=m)))
        self.pencere.ayarlar.dil_degisti.connect(self.dil_degisti)  # pencere kendini zaten tazeler
        if self.tepsi is not None:
            self.tepsi.dur_istendi.connect(self.dur)
            self.tepsi.devam_istendi.connect(self.devam_sor)  # menüyü plasmashell çizer: doğrudan kaldırma
            self.tepsi.panel_istendi.connect(self.ac_kapat)
            self.tepsi.arka_istendi.connect(self.arka_goster)
            self.tepsi.cikis_istendi.connect(self.cik)
        app.aboutToQuit.connect(self.kapanis)

        onay.panel_kaydet()
        try:  # önceki (çökmüş / SIGKILL) panelden kalan sahipsiz Devral bayrağı ajanı bekletmesin
            from .durum import devral_sahipsiz_sil
            devral_sahipsiz_sil()
        except Exception:  # noqa: BLE001
            pass
        self._durum(iz.durum)
        self.pencere.arka.sanal_guncelle(iz.sanal)
        ayarlar = A.panel_oku()
        if ayarlar["kisayol_acik"]:  # yalnız kullanıcı Ayarlar'da açtıysa
            QTimer.singleShot(0, lambda: self.kisayol_ayarla(True, ayarlar["kisayol"]))
        if self.tepsi is not None:
            self.tepsi.goster()

    # -------- DUR / devam (insanın kararı: kaynak "kullanici")
    def dur(self):
        guvenlik.dur_ac("kullanici")
        gunluk("DUR anahtarı açıldı (panel)")
        self.izleyici.yenile()

    def devam(self):
        """Panel penceresindeki Devam (yerleşik yasak pencere: ajan tıklayamaz) → DUR kalkar."""
        acikti = guvenlik.dur_kapat("kullanici")
        if acikti:
            gunluk("DUR anahtarı kaldırıldı (panel)")
        self.izleyici.yenile()

    def devam_sor(self):
        """Tepsi menüsündeki Devam: menüyü plasmashell çizer (yasak listesinde değil; bir ajan tıklayabilir).
        DUR doğrudan kalkmaz: panel penceresi açılır ve orada (ajan tıklayamaz) onay sorulur."""
        self.goster()
        self.pencere.devam_sor()

    # -------- durum
    def _durum(self, d: Durum):
        self.pencere.durum_guncelle(d)
        if self.tepsi is not None:
            self.tepsi.guncelle(d)

    # -------- onaylar
    def _onaylar(self, bekleyen: list[dict]):
        kimlikler = {b["id"] for b in bekleyen}
        for k, dlg in list(self.diyaloglar.items()):
            if k not in kimlikler:
                dlg.geri_cekildi()
        for b in bekleyen:
            if b["id"] not in self.diyaloglar:
                self._diyalog_ac(b)
        self.pencere.onaylar.guncelle(bekleyen)

    def _diyalog_ac(self, istek: dict) -> OnayDiyalog:
        kw = {} if self.diyalog_kurma_ms is None else {"kurma_ms": self.diyalog_kurma_ms}
        dlg = OnayDiyalog(istek, **kw)
        dlg.setWindowIcon(self.pencere.windowIcon())
        dlg.karar_verildi.connect(self._karar)
        self.diyaloglar[istek["id"]] = dlg
        dlg.show()
        dlg.raise_()
        return dlg

    def diyalog_one(self, istek_id: str):
        dlg = self.diyaloglar.get(istek_id)
        if dlg is not None and not dlg.bitti:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

    def _karar(self, istek_id: str, _neden: str):
        self.diyaloglar.pop(istek_id, None)
        QTimer.singleShot(50, self.izleyici.yenile)

    # -------- pencere
    def goster(self):
        self.pencere.show()
        self.pencere.showNormal() if self.pencere.isMinimized() else None
        self.pencere.raise_()
        self.pencere.activateWindow()

    def ac_kapat(self):
        if self.pencere.isVisible() and not self.pencere.isMinimized():
            self.pencere.hide()
        else:
            self.goster()

    def arka_goster(self):
        self.pencere.arka_goster()
        self.goster()

    def _baglanti(self):
        s = self.sunucu.nextPendingConnection()
        if s is None:
            return

        def oku():
            veri = bytes(s.readAll()).decode(errors="replace").strip()
            if veri == "arka":
                self.arka_goster()
            else:
                self.goster()
            s.disconnectFromServer()

        s.readyRead.connect(oku)
        s.disconnected.connect(s.deleteLater)

    # -------- kısayol
    def kisayol_ayarla(self, acik: bool, tus: str):
        try:
            if acik:
                self.kisayol.ac(tus)
                self.pencere.ayarlar.kisayol_durumu(_(T.Y_KISAYOL_TAMAM).format(tus=tus))
            elif self.kisayol.acik:
                self.kisayol.kapat(kaydi_sil=True)
                self.pencere.ayarlar.cakisma_goster()
        except Exception as e:  # noqa: BLE001 - KDE/D-Bus yok: tepsi yeterli
            self.pencere.ayarlar.kisayol_durumu(_(T.Y_KISAYOL_HATA).format(hata=e))

    # -------- dil
    def dil_degisti(self, _kod: str = ""):
        """Ayarlar'da dil değişti (i18n zaten yeniden yüklendi): tepsi + açık onay diyalogları yeni dilde.
        Açık genel kısayolun KDE'deki görünen adı bir sonraki kayıtta (aç/kapat ya da yeniden başlatma) güncellenir."""
        if self.tepsi is not None:
            self.tepsi.tazele()
        for dlg in list(self.diyaloglar.values()):
            if not dlg.bitti:
                dlg.tazele()

    # -------- çıkış
    def _diyaloglari_kapat(self):
        for k in list(self.diyaloglar):
            onay.yanitla(k, "red")  # panel kapanıyor: bekleyen istek açık kalmasın
        for dlg in list(self.diyaloglar.values()):
            dlg.geri_cekildi()
        self.diyaloglar.clear()

    def kapanis(self):
        self._diyaloglari_kapat()
        if self.pencere.arka.b_devral.isChecked():
            self.pencere.arka.b_devral.setChecked(False)  # devral dosyası silinir, girdi kapanır
        from .pencere import isciler_bekle
        isciler_bekle()  # masaüstü durdurma sürüyorsa bitsin (QThread çalışırken yok edilmesin)
        self.izleyici.durdur()
        self.kisayol.kapat(kaydi_sil=False)
        onay.panel_sil()
        if self.sunucu is not None:
            self.sunucu.close()
            k = getattr(self.sunucu, "_kilit", None)
            if k is not None:
                k.close()  # tek örnek kilidi bırakılır

    def cik(self):
        self._diyaloglari_kapat()
        self.pencere.kapaninca_gizle = False
        self.app.quit()
