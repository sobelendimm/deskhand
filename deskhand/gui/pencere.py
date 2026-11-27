"""Panel penceresi: durum şeridi (DUR/Devam) + sekmeler (Görev, Etkinlik, Arka plan ekranı, Onaylar, Ayarlar, Sağlık;
kayıtlı simgeler Ayarlar › Gelişmiş altında). Görünüm sistem paletinden (Breeze açık/koyu); sabit renk yalnız durum renklerinde."""
from __future__ import annotations


from PyQt6.QtCore import (Qt, pyqtSignal)
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QMainWindow, QMessageBox, QTabWidget, QVBoxLayout, QWidget)

from .. import onay
from ..i18n import _
from . import metinler as T
from .dil import Metinler
from . import saglik as S
from .durum import Durum
from .gorev import GorevSekmesi
from .kisayol import cakismalar
from .ortak import (_DUR_KAYNAK_PANEL, ONIZLEME_MS, IZLEME_MS, MASA_LISTE_MS, YESIL, KIRMIZI, SARI, Isci, isciler_bekle, _devral_temizle, _DEVRAL_ATEXIT, nokta, baslik_etiketi, soluk_etiket, _masaustu_adi, _karar_adi)  # noqa: F401 - yeniden dışa aktarım
from .sekmeler.etkinlik import (EtkinlikModel, EtkinlikSuzgec, EtkinlikSekmesi)  # noqa: F401
from .sekmeler.arka_plan import (_masaustu_modulu, _varsayilan_arka, ArkaPlanSekmesi)  # noqa: F401
from .sekmeler.onaylar import (OnaylarSekmesi)  # noqa: F401
from .sekmeler.ayarlar import (Y_DOGRULANMADI, Y_DOSYADA_FARKLI, AyarlarSekmesi)  # noqa: F401
from .sekmeler.simgeler import (SimgelerSekmesi)  # noqa: F401
from .sekmeler.saglik import (SaglikSekmesi)  # noqa: F401
from .durum_seridi import DurumSeridi  # noqa: F401


# =========================================================================== Ana pencere

class AnaPencere(QMainWindow):
    dur_istendi = pyqtSignal()
    devam_istendi = pyqtSignal()

    def __init__(self, ilk_satirlar: list[dict] | None = None, parent=None, arka_f=_varsayilan_arka,
                 masaustu_m=None, karar=None, cakisma_f=cakismalar, simge_sor=None, saglik_f=S.tam_denetim,
                 gorev_f=None):
        super().__init__(parent)
        self.setWindowTitle(onay.PANEL_BASLIK)
        self.setObjectName("deskhandPanel")
        self.resize(1040, 680)
        self.kapaninca_gizle = True
        self.mt = Metinler()
        self._durum = Durum()
        self.devam_kutusu: QMessageBox | None = None
        merkez = QWidget()
        kok = QVBoxLayout(merkez)
        kok.setContentsMargins(10, 10, 10, 10)
        kok.setSpacing(8)
        self.serit = DurumSeridi()
        self.serit.dur_istendi.connect(self.dur_istendi.emit)
        self.serit.devam_istendi.connect(self.devam_istendi.emit)
        kok.addWidget(self.serit)
        self.sekmeler = QTabWidget()
        self.sekmeler.setDocumentMode(True)
        ilk = ilk_satirlar or []
        self.gorev = GorevSekmesi(arka_f=arka_f, **({"gorev_f": gorev_f} if gorev_f else {}))
        self.etkinlik = EtkinlikSekmesi(ilk)
        self.arka = ArkaPlanSekmesi(arka_f=arka_f, masaustu_m=masaustu_m)
        self.arka.etkinlik_ekle(ilk)
        self.onaylar = OnaylarSekmesi()
        self.onaylar.gecmis_ekle(ilk)
        self.ayarlar = AyarlarSekmesi(karar=karar, cakisma_f=cakisma_f, simge_sor=simge_sor)
        self.simgeler = self.ayarlar.simgeler  # UX-F O7: ayrı sekme değil, Ayarlar › Gelişmiş'te
        self.saglik = SaglikSekmesi(denetle=saglik_f)
        for w, ad, ikon in ((self.gorev, T.S_GOREV, "system-run"),
                            (self.etkinlik, T.S_ETKINLIK, "view-list-details"),
                            (self.arka, T.S_ARKA, "video-display"),
                            (self.onaylar, T.S_ONAY, "dialog-question"),
                            (self.ayarlar, T.S_AYAR, "configure"),
                            (self.saglik, T.S_SAGLIK, "checkmark")):
            i = self.sekmeler.addTab(w, QIcon.fromTheme(ikon), "")
            if w is not self.onaylar:  # Onaylar'ın adı bekleyen sayısını taşır: durum_guncelle yazar
                self.mt(lambda m, i=i: self.sekmeler.setTabText(i, m), ad)
        self._onay_sekmesi_yaz()
        self.serit.onaylar_istendi.connect(lambda: self.sekmeler.setCurrentWidget(self.onaylar))
        self.ayarlar.dil_degisti.connect(self.tazele)
        self.gorev.devral_istendi.connect(self._gorev_devral)
        self.arka.devral_degisti.connect(self.gorev.devral_durumu)
        kok.addWidget(self.sekmeler, 1)
        self.setCentralWidget(merkez)

    def durum_guncelle(self, d: Durum):
        self._durum = d
        self.serit.guncelle(d)
        self.gorev.durum_guncelle(d)
        self._onay_sekmesi_yaz()

    def _onay_sekmesi_yaz(self):
        n = self._durum.bekleyen
        self.sekmeler.setTabText(self.sekmeler.indexOf(self.onaylar),
                                 _(T.S_ONAY_SAYI).format(n=n) if n else _(T.S_ONAY))

    def tazele(self, _kod: str = ""):
        """Dil değişti (i18n yeniden yüklendi): tüm görünen metinler yeni dilde; içerik ve durum korunur."""
        self.mt.tazele()
        self.serit.tazele()
        for sekme in (self.gorev, self.etkinlik, self.arka, self.onaylar, self.ayarlar, self.saglik):
            sekme.tazele()
        self._onay_sekmesi_yaz()

    def satirlar_geldi(self, satirlar: list[dict]):
        self.etkinlik.ekle(satirlar)
        self.onaylar.gecmis_ekle(satirlar)
        self.arka.etkinlik_ekle(satirlar)

    def arka_goster(self):
        self.sekmeler.setCurrentWidget(self.arka)

    def gorev_goster(self):
        self.sekmeler.setCurrentWidget(self.gorev)
        self.gorev.kutu.setFocus()

    def _gorev_devral(self):
        """Görev sekmesindeki Devral: mevcut Devral akışı (Arka plan ekranı sekmesi) açılır/kapanır. Görev varsayılan
        masaüstünde çalışır: sekme listeden başka bir masaüstüne çevrilmişse önce varsayılana döner."""
        if not self.arka.b_devral.isChecked():
            self.arka.masa_sec("")
        self.arka.b_devral.setChecked(not self.arka.b_devral.isChecked())
        if self.arka.b_devral.isChecked():
            self.arka_goster()

    def devam_sor(self) -> QMessageBox:
        """Tepsiden gelen Devam: BU pencerede (sınıfı yerleşik yasak listede: ajan tıklayamaz) onay sorar; yalnız
        "Devam et" → devam_istendi. Modal değil (olay döngüsü bloklanmaz); varsayılan/Esc/Enter = DUR açık kalsın."""
        k = self.devam_kutusu
        if k is not None:
            try:
                if k.isVisible():
                    k.raise_()
                    k.activateWindow()
                    return k
            except RuntimeError:  # silinmiş
                pass
        k = QMessageBox(self)
        k.setIcon(QMessageBox.Icon.Question)
        k.setWindowTitle(onay.PANEL_BASLIK)
        k.setText(_(T.DEVAM_SORU))
        k.setTextFormat(Qt.TextFormat.PlainText)
        evet = k.addButton(_(T.DEVAM_DUGME), QMessageBox.ButtonRole.AcceptRole)
        hayir = k.addButton(_(T.DEVAM_VAZGEC), QMessageBox.ButtonRole.RejectRole)
        evet.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Enter/boşluk "Devam" olmasın
        evet.setAutoDefault(False)
        k.setDefaultButton(hayir)
        k.setEscapeButton(hayir)
        k.b_evet, k.b_hayir = evet, hayir
        k.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        k.buttonClicked.connect(lambda b: self.devam_istendi.emit() if b is evet else None)
        self.devam_kutusu = k
        k.open()
        return k

    def closeEvent(self, e):  # noqa: N802
        # kullanıcının kapat düğmesi (kendiliğinden olay) → tepsiye gizlen; uygulama çıkışı/oturum kapanışı → kapan
        if self.kapaninca_gizle and e.spontaneous():
            e.ignore()
            self.hide()
            return
        super().closeEvent(e)

