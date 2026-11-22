"""Panelin "Görev" sekmesi: görev kutusu + canlı adımlar + görünmez masaüstünün canlı görüntüsü + sonuç + geçmiş.

Yürütme `deskhand/gorev.py`'dedir (Qt'siz): bu sekme yalnız arayüzdür. Olaylar yürütücünün okuyucu iş parçacığından
gelir; `olay_geldi` sinyaliyle arayüz iş parçacığına sıraya konur. Canlı görüntü YALNIZ görünmez (arka plan)
masaüstünden alınır (arka_f = arka_uc.sec(arka_bayragi=True)); kullanıcının kendi ekranından görüntü alınmaz.
"Devral" düğmesi mevcut Devral akışını (Arka plan ekranı sekmesi) açar.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget)

from .. import ayarlar, gorev, gorev_kipi
from ..i18n import _
from . import metinler as T
from .dil import Metinler
from .durum import Durum
from .onizleme import Onizleme, pil_qimage

CANLI_MS = 1000  # ~1 kare/sn (yalnız görev çalışırken ve sekme görünürken)
KIRMIZI, YESIL, GRI = "#e03131", "#2f9e44", "#8a8f98"


def adim_metni(o: dict) -> str:
    """`arac` olayı → kısa Türkçe açıklama ("Firefox açılıyor", "‘Sepete ekle’ tıklanıyor"). Ham ad ipucundadır."""
    ad, g = o.get("arac", ""), o.get("girdi") or {}
    if not isinstance(g, dict):
        g = {}
    if ad == "open_app" and g.get("app"):
        uygulama = str(g["app"])
        return _(T.G_ARAC["open_app"]).format(app=uygulama[:1].upper() + uygulama[1:])
    if ad == "click":
        hedef = g.get("text") or g.get("element")
        return _(T.G_ARAC["click"]).format(hedef=hedef) if hedef else _(T.G_ARAC["click_genel"])
    if ad == "press_key" and g.get("keys"):
        return _(T.G_ARAC["press_key"]).format(keys=g["keys"])
    if ad == "wait_for":
        return _(T.G_ARAC["wait_for"]).format(value=g["value"]) if g.get("value") else _(T.G_ARAC["wait_for_genel"])
    if ad == "manage_desktop":
        return _(T.G_ARAC.get(f"manage_desktop_{g.get('action')}", T.G_ARAC["manage_desktop_status"]))
    if ad in T.G_ARAC and ad not in ("open_app", "click", "press_key", "wait_for", "manage_desktop"):
        return _(T.G_ARAC[ad])
    return _(T.G_ARAC_BILINMEYEN).format(arac=ad or "?")


def gecmis_satiri(g: dict) -> str:
    durum = _(T.G_BITTI.get(g.get("durum"), T.G_BITTI["devam"]))
    return _(T.G_GECMIS_SATIRI).format(zaman=(g.get("zaman") or "")[5:16], durum=durum,
                                       metin=" ".join((g.get("metin") or "").split())[:70])


def _nokta(renk: str):
    from .pencere import nokta  # döngüsel içe aktarmayı önlemek için tembel
    return nokta(renk)


class GorevKutusu(QPlainTextEdit):
    """Çok satırlı görev kutusu; Ctrl+Enter = gönder."""
    gonder = pyqtSignal()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            e.accept()
            self.gonder.emit()
            return
        super().keyPressEvent(e)


class GorevSekmesi(QWidget):
    olay_geldi = pyqtSignal(dict)   # yürütücü iş parçacığından arayüze
    devral_istendi = pyqtSignal()   # Devral düğmesi: pencere Arka plan ekranı sekmesini açıp Devral'ı çevirir
    durum_degisti = pyqtSignal(bool)  # çalışıyor mu (pencere/paneller için)

    def __init__(self, parent=None, arka_f=None, gorev_f=gorev.Gorev, gecmis_f=gorev.gecmis, olaylar_f=gorev.olaylar):
        super().__init__(parent)
        if arka_f is None:
            from .pencere import _varsayilan_arka
            arka_f = _varsayilan_arka
        self.arka_f, self.gorev_f, self.gecmis_f, self.olaylar_f = arka_f, gorev_f, gecmis_f, olaylar_f
        self.mt = Metinler()
        self.g = None            # çalışan yürütücü
        self.calisiyor = False
        self.durduruluyor = False
        self.sanal: dict | None = None
        self.bekleyen = 0
        self.adim_sayisi = 0
        self._adimlar: dict[str, QListWidgetItem] = {}   # tool_use kimliği → öğe
        self._dusunuyor: QListWidgetItem | None = None
        self._bitis_durumu = ""  # son görevin durumu (durum etiketi)
        self._gecmis: list[dict] = []

        kok = QVBoxLayout(self)
        self.kutu = GorevKutusu()
        self.kutu.setMaximumHeight(96)
        self.mt(self.kutu.setPlaceholderText, T.G_KUTU_IPUCU)
        kok.addWidget(self.kutu)
        self.kutu.gonder.connect(self.baslat)
        self.l_parola = QLabel()  # görev metni geçmişe/Claude'a gider: sır yazılmasın
        self.mt(self.l_parola.setText, T.G_PAROLA_UYARI)
        kok.addWidget(self.l_parola)
        site_sira = QHBoxLayout()
        self.l_siteler = QLabel()
        self.mt(self.l_siteler.setText, T.G_SITELER)
        self.siteler = QLineEdit()
        self.mt(self.siteler.setPlaceholderText, T.G_SITELER_IPUCU)
        self.mt(self.siteler.setToolTip, T.G_SITELER_ACIKLAMA)
        site_sira.addWidget(self.l_siteler)
        site_sira.addWidget(self.siteler, 1)
        kok.addLayout(site_sira)
        # Başlat'tan önce kısa onay (görev metni + izinli siteler + "yalnız tarayıcı"); başsız (offscreen) testte kapalı
        self.onay_iste = QApplication.platformName() != "offscreen"

        sira = QHBoxLayout()
        self.b_baslat = QPushButton()
        self.mt(self.b_baslat.setText, T.G_BASLAT)
        self.mt(self.b_baslat.setToolTip, T.G_BASLAT_IPUCU)
        self.b_baslat.clicked.connect(self.baslat)
        self.b_durdur = QPushButton()
        self.mt(self.b_durdur.setText, T.G_DURDUR)
        self.mt(self.b_durdur.setToolTip, T.G_DURDUR_IPUCU)
        self.b_durdur.clicked.connect(self.durdur)
        self.b_devral = QPushButton()
        self.mt(self.b_devral.setToolTip, T.G_DEVRAL_IPUCU)
        self.b_devral.clicked.connect(self.devral_istendi.emit)
        self.devral_durumu(False)
        self.l_model = QLabel()
        self.mt(self.l_model.setText, T.G_MODEL)
        self.c_model = QComboBox()
        self.mt(self.c_model.setToolTip, T.G_MODEL_IPUCU)
        for kod in gorev.MODELLER:
            self.c_model.addItem("", kod)
        self.mt.fn(self._model_adlari)
        self._model_yukle()
        self.c_model.currentIndexChanged.connect(self._model_secildi)
        for w in (self.b_baslat, self.b_durdur, self.b_devral):
            sira.addWidget(w)
        sira.addStretch(1)
        sira.addWidget(self.l_model)
        sira.addWidget(self.c_model)
        kok.addLayout(sira)

        self.l_durum = QLabel()
        self.l_durum.setWordWrap(True)
        kok.addWidget(self.l_durum)

        bolme = QSplitter(Qt.Orientation.Horizontal)
        sol = QWidget()
        sl = QVBoxLayout(sol)
        sl.setContentsMargins(0, 0, 0, 0)
        self.l_adimlar = QLabel()
        self.mt(self.l_adimlar.setText, T.G_ADIMLAR)
        sl.addWidget(self.l_adimlar)
        self.liste = QListWidget()
        self.liste.setUniformItemSizes(False)
        self.liste.setWordWrap(True)
        self.liste.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        sl.addWidget(self.liste, 3)
        self.l_sonuc = QLabel()
        self.mt(self.l_sonuc.setText, T.G_SONUC)
        sl.addWidget(self.l_sonuc)
        self.sonuc = QPlainTextEdit()
        self.sonuc.setReadOnly(True)
        self.sonuc.setMaximumHeight(110)
        sl.addWidget(self.sonuc)
        self.l_gecmis = QLabel()
        self.mt(self.l_gecmis.setText, T.G_GECMIS)
        sl.addWidget(self.l_gecmis)
        self.gecmis_liste = QListWidget()
        self.gecmis_liste.setMaximumHeight(120)
        self.gecmis_liste.itemClicked.connect(self._gecmis_sec)
        self.gecmis_liste.itemDoubleClicked.connect(self._gecmis_kutuya)
        sl.addWidget(self.gecmis_liste)
        bolme.addWidget(sol)
        self.onizleme = Onizleme()  # Devral girdisi bu pencerede KAPALI: Devral, Arka plan ekranı sekmesindedir
        self.onizleme.setMinimumSize(280, 160)
        self.mt.fn(lambda: setattr(self.onizleme, "bos_metin", _(T.G_ONIZLEME_BOS)))
        bolme.addWidget(self.onizleme)
        bolme.setStretchFactor(0, 1)
        bolme.setStretchFactor(1, 1)
        kok.addWidget(bolme, 1)

        self.olay_geldi.connect(self._olay)
        self.zaman = QTimer(self)
        self.zaman.setInterval(CANLI_MS)
        self.zaman.timeout.connect(self.kare)
        self.gecmis_yenile()
        self._durum_yaz()
        self._dugmeler()

    # -------- model
    def _model_adlari(self) -> None:
        for i, kod in enumerate(gorev.MODELLER):
            self.c_model.setItemText(i, _(T.G_MODEL_AD[kod]))

    def _model_yukle(self) -> None:
        try:
            kod = ayarlar.al("gorev", "model")
        except Exception:  # noqa: BLE001
            kod = "sonnet"
        self.c_model.blockSignals(True)
        self.c_model.setCurrentIndex(max(0, self.c_model.findData(kod)))
        self.c_model.blockSignals(False)

    def _model_secildi(self, *_a) -> None:
        try:
            ayarlar.ayarla("gorev", "model", self.c_model.currentData())
        except (ValueError, OSError):
            pass

    # -------- düğmeler / durum
    def _dugmeler(self) -> None:
        c = self.calisiyor
        self.b_baslat.setEnabled(not c)
        self.b_durdur.setEnabled(c and not self.durduruluyor)
        self.kutu.setReadOnly(c)
        self.siteler.setReadOnly(c)
        self.c_model.setEnabled(not c)
        self.gecmis_liste.setEnabled(not c)
        self.b_devral.setEnabled(self.sanal is not None)

    def _durum_yaz(self) -> None:
        if self.calisiyor:
            if self.durduruluyor:
                m = _(T.G_DURDURULUYOR)
            elif self.bekleyen:
                m = _(T.G_ONAY).format(n=self.bekleyen)
            else:
                m = _(T.G_CALISIYOR).format(n=self.adim_sayisi)
            if not self.durduruluyor and self.sanal is None and not self.bekleyen:
                m += "  " + _(T.G_SANAL_YOK)
        elif self._bitis_durumu:
            m = _(T.G_BITTI.get(self._bitis_durumu, T.G_BITTI["hata"]))
        else:
            m = _(T.G_HAZIR)
        self.l_durum.setText(m)
        pal = self.l_durum.palette()
        renk = QColor("#e8a317") if self.calisiyor and self.bekleyen else self.palette().color(QPalette.ColorRole.WindowText)
        pal.setColor(QPalette.ColorRole.WindowText, renk)
        self.l_durum.setPalette(pal)

    def durum_guncelle(self, d: Durum) -> None:
        """Panel durumu: bekleyen onay sayısı (kart ödemesi vb.; diyalog panelde zaten açılır)."""
        if d.bekleyen != self.bekleyen:
            self.bekleyen = d.bekleyen
            self._durum_yaz()

    def sanal_guncelle(self, s: dict | None) -> None:
        onceki = self.sanal is not None
        self.sanal = s
        self._dugmeler()
        if (s is not None) != onceki:
            self._durum_yaz()
        self._zamanlayici()

    def devral_durumu(self, acik: bool) -> None:
        self.b_devral.setText(_(T.G_BIRAK if acik else T.G_DEVRAL))

    def tazele(self) -> None:
        self.mt.tazele()
        self.devral_durumu(self.b_devral.text() == _(T.G_BIRAK))
        self._durum_yaz()
        self.gecmis_yenile()
        self.onizleme.update()

    # -------- başlat / durdur
    def baslat(self) -> None:
        if self.calisiyor:
            return
        metin = self.kutu.toPlainText().strip()
        if not metin:
            return
        siteler = ", ".join(gorev_kipi.site_ayristir(self.siteler.text()))
        if self.onay_iste and not self._onayla(metin, siteler):
            return
        self.liste.clear()
        self._adimlar.clear()
        self._dusunuyor = None
        self.sonuc.clear()
        self.adim_sayisi = 0
        self._bitis_durumu = ""
        try:
            self.g = self.gorev_f(olay_cb=self.olay_geldi.emit)
            if siteler:
                self.g.baslat(metin, siteler=siteler)
            else:
                self.g.baslat(metin)
        except gorev.GorevHatasi as e:
            self.g = None
            self._bitis_durumu = "hata"
            self.sonuc.setPlainText(_(T.G_BASLATMA_HATA).format(hata=str(e)))
            self._durum_yaz()
            return
        self.calisiyor, self.durduruluyor = True, False
        self.durum_degisti.emit(True)
        self._durum_yaz()
        self._dugmeler()
        self._zamanlayici()

    def onay_metni(self, metin: str, siteler: str) -> str:
        kisa = " ".join(metin.split())
        kisa = kisa if len(kisa) <= 300 else kisa[:299] + "…"
        return _(T.G_ONAY_METIN).format(metin=kisa, siteler=siteler or _(T.G_ONAY_SITE_YOK))

    def _onayla(self, metin: str, siteler: str) -> bool:
        k = QMessageBox(QMessageBox.Icon.Question, _(T.G_ONAY_BASLIK), self.onay_metni(metin, siteler),
                        QMessageBox.StandardButton.Cancel, self)
        b = k.addButton(_(T.G_BASLAT), QMessageBox.ButtonRole.AcceptRole)
        k.setDefaultButton(b)
        k.exec()
        return k.clickedButton() is b

    def durdur(self) -> None:
        if not self.calisiyor or self.g is None:
            return
        self.durduruluyor = True
        self.g.durdur()
        self._durum_yaz()
        self._dugmeler()

    def kapat(self, sure_ms: int = 5000) -> None:
        """Panel kapanırken çalışan görevi durdur (arka plan kalıntısı kalmasın)."""
        g = self.g
        if self.calisiyor and g is not None:
            g.durdur()
            g.bekle(sure_ms / 1000)
        self.zaman.stop()

    # -------- olaylar
    def _ekle(self, metin: str, renk: str | None = None, ipucu: str = "", soluk: bool = False) -> QListWidgetItem:
        it = QListWidgetItem(metin)
        if renk:
            it.setIcon(_nokta(renk))
        if ipucu:
            it.setToolTip(ipucu)
        if soluk:
            it.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
        self.liste.addItem(it)
        self.liste.scrollToBottom()
        return it

    def _olay(self, o: dict) -> None:
        tur = o.get("tur")
        if tur != "dusunce":
            self._dusunuyor = None
        if tur == "dusunce":
            if self._dusunuyor is None:
                self._dusunuyor = self._ekle(_(T.G_DUSUNUYOR), soluk=True, ipucu=o.get("ozet", ""))
        elif tur == "arac":
            self.adim_sayisi += 1
            it = self._ekle(adim_metni(o), GRI, ipucu=o.get("ozet", ""))
            if o.get("kimlik"):
                self._adimlar[o["kimlik"]] = it
            if self.calisiyor:
                self._durum_yaz()
        elif tur == "arac_sonuc":
            it = self._adimlar.get(o.get("kimlik"))
            if it is not None:
                it.setIcon(_nokta(KIRMIZI if o.get("hata") else YESIL))
                if o.get("hata"):
                    it.setToolTip(f"{it.toolTip()}\n→ {o.get('ozet', '')}")
        elif tur == "metin":
            self._ekle(o.get("ozet", ""), soluk=True)
        elif tur == "sonuc":
            self.sonuc.setPlainText(o.get("ozet", ""))
        elif tur == "hata":
            m = _(T.G_HATA_SATIRI).format(ozet=o.get("ozet", ""))
            if o.get("ipucu"):
                m += "\n" + o["ipucu"]
            self._ekle(m, KIRMIZI)
            if not self.sonuc.toPlainText():
                self.sonuc.setPlainText(m)
        elif tur == "bitti":
            self._bitti(o)

    def _bitti(self, o: dict) -> None:
        if o.get("indirilenler"):
            self._ekle(_(T.G_INDIRILENLER).format(dosyalar=", ".join(map(str, o["indirilenler"][:20])),
                                                  klasor=o.get("indirme_dizini", "")), YESIL)
        self.calisiyor = self.durduruluyor = False
        self._bitis_durumu = o.get("durum", "hata")
        self.zaman.stop()
        self.g = None
        self.gecmis_yenile()
        self._durum_yaz()
        self._dugmeler()
        self.durum_degisti.emit(False)

    # -------- geçmiş
    def gecmis_yenile(self) -> None:
        try:
            self._gecmis = list(self.gecmis_f())
        except Exception:  # noqa: BLE001
            self._gecmis = []
        self.gecmis_liste.clear()
        for g in self._gecmis:
            it = QListWidgetItem(gecmis_satiri(g))
            it.setToolTip(g.get("ozet", ""))
            it.setData(Qt.ItemDataRole.UserRole, g)
            self.gecmis_liste.addItem(it)

    def _gecmis_sec(self, it: QListWidgetItem) -> None:
        g = it.data(Qt.ItemDataRole.UserRole)
        if self.calisiyor or not g:
            return
        self.liste.clear()
        self._adimlar.clear()
        self.sonuc.setPlainText(g.get("ozet", ""))
        try:
            olaylar = self.olaylar_f(g["dosya"])
        except Exception:  # noqa: BLE001
            olaylar = []
        self.adim_sayisi = 0
        for o in olaylar:
            if o.get("tur") in ("arac", "arac_sonuc", "hata", "metin"):
                self._olay(o)
        self._dusunuyor = None
        self._bitis_durumu = g.get("durum", "hata")
        self._durum_yaz()

    def _gecmis_kutuya(self, it: QListWidgetItem) -> None:
        g = it.data(Qt.ItemDataRole.UserRole)
        if not self.calisiyor and g:
            self.kutu.setPlainText(g.get("metin", ""))

    # -------- canlı görüntü (yalnız görev çalışırken ve görünürken; yalnız GÖRÜNMEZ masaüstü)
    def _gorunur(self) -> bool:
        w = self.window()
        return self.isVisible() and not (w is not None and w.isMinimized())

    def _zamanlayici(self) -> None:
        if self.calisiyor and self.sanal is not None and self._gorunur():
            if not self.zaman.isActive():
                self.zaman.start()
                self.kare()
        else:
            self.zaman.stop()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._zamanlayici()

    def hideEvent(self, e):  # noqa: N802
        super().hideEvent(e)
        self.zaman.stop()

    def kare(self) -> None:
        if not self.calisiyor or self.sanal is None or not self._gorunur():
            self.zaman.stop()
            return
        try:
            im = self.arka_f().goruntu()
        except Exception as e:  # noqa: BLE001 - masaüstü kapandı / X hatası
            self.onizleme.bos_metin = _(T.G_ONIZLEME_HATA).format(hata=getattr(e, "mesaj", None) or e)
            self.onizleme.goster(None)
            return
        q, kaynak = pil_qimage(im, self.onizleme.hedef_boyut() if self.onizleme.kaynak.width() else None)
        self.onizleme.goster(q, kaynak)
