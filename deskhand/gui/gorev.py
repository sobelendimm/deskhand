"""Panelin "Görev" sekmesi: görev kutusu + canlı adımlar + görünmez masaüstünün canlı görüntüsü + sonuç + geçmiş.

Yürütme `deskhand/gorev.py`'dedir (Qt'siz): bu sekme yalnız arayüzdür. Olaylar yürütücünün okuyucu iş parçacığından
gelir; `olay_geldi` sinyaliyle arayüz iş parçacığına sıraya konur. Canlı görüntü YALNIZ görünmez (arka plan)
masaüstünden alınır (arka_f = arka_uc.sec(arka_bayragi=True)); kullanıcının kendi ekranından görüntü alınmaz.
"Devral" düğmesi mevcut Devral akışını (Arka plan ekranı sekmesi) açar.
"""
from __future__ import annotations

import os
import re

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QToolButton,
                             QVBoxLayout, QWidget)

from .. import ayarlar, gorev, gorev_kipi
from ..i18n import N_, _
from . import metinler as T
from .dil import Metinler
from .durum import RENK, Durum
from .onizleme import MaskeHatasi, Onizleme, maskeli_goruntu, pil_qimage

CANLI_MS = 1000  # ~1 kare/sn (yalnız görev çalışırken ve sekme görünürken)
from .durum import _D as _DURUM_RENK  # noqa: E402  (tokens.json; UX-K)

KIRMIZI, YESIL, GRI = _DURUM_RENK["hata"], _DURUM_RENK["basari"], _DURUM_RENK["bos"]

# UX-E (Y5/O8): bu sekmeye özgü yeni metinler (gui/metinler.py başka görevin dosyası; aynı N_ → _ kalıbı)
G_DUR_SERIDI = N_("Deskhand durduruldu — görev başlatmak için önce üstteki «Devam et» düğmesine basın.")
G_BOS_METIN = N_("Önce görevi yazın: kutuya ne yapılmasını istediğinizi yazıp yeniden Başlat'a basın.")
G_GOREVI_DURDUR = N_("Görevi durdur")
G_GOREVI_DURDUR_IPUCU = N_("Yalnız çalışan görevi durdurur; görünmez masaüstü açık kalır. "
                           "Tüm girdileri durdurmak için üstteki DUR düğmesini kullanın.")
G_BIR_DAHA_SORMA = N_("Bir daha sorma")
G_MODEL_KAYIT_HATA = N_("Model seçimi kaydedilemedi. Görevler bu oturumda yine seçtiğiniz modelle çalışır; panel "
                        "yeniden açılınca önceki seçim döner. Ne yapmalı: ayarlar klasörünün yazılabilir olduğunu "
                        "denetleyip modeli yeniden seçin.")
G_TERCIH_KAYIT_HATA = N_("«Bir daha sorma» seçimi kaydedilemedi; onay bir sonraki görevde yine sorulur. Ne yapmalı: "
                         "ayarlar klasörünün yazılabilir olduğunu denetleyin.")
G_AYRINTI = N_("Ayrıntı")
G_KUTU_AD = N_("Görev metni")
G_SITELER_AD = N_("Oturumla girilebilecek siteler")
G_SONUC_AD = N_("Görev sonucu")

# ham istisna izi (kullanıcıya üst satırda gösterilmez; UX-F O5)
_HAM_ILETI = re.compile(r"Errno|Error\b|Exception|Traceback|NoneType|No such file|Permission denied|`")

ONAY_ANAHTARI = ("gorev", "baslat_onayi")  # true = her görevde sor (varsayılan); false = "Bir daha sorma"


def baslat_onayi_saklanabilir() -> bool:
    """Ayar çekirdeği "Bir daha sorma" tercihini tanıyor mu (anahtar yoksa kutucuk gösterilmez: boş vaat yok)."""
    bolum, anahtar = ONAY_ANAHTARI
    return anahtar in ayarlar.VARSAYILAN.get(bolum, {})


def baslat_onayi_sorulsun() -> bool:
    """Tercih okunamazsa güvenli taraf: sorulur."""
    if not baslat_onayi_saklanabilir():
        return True
    try:
        return ayarlar.al(*ONAY_ANAHTARI) is not False
    except Exception:  # noqa: BLE001
        return True


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
        self.dur = False              # panel DUR'u açık mı (durum_guncelle ile; yoklama yok)
        self._bos_uyari = False       # boş metinle Başlat → görünür ileti + kutu vurgusu
        self._model_kayitsiz: str | None = None  # kaydedilemeyen model seçimi (bu oturumda yine kullanılır)
        self._hata: tuple[str, str] | None = None  # (metin kimliği, ayrıntı)
        self._care = ""  # üst satırdaki "ne yapılacak" (GorevHatasi ipucu)

        kok = QVBoxLayout(self)
        self.l_dur = QLabel()  # DUR açıkken görev başlatılamaz: görünür neden + ne yapmalı
        self.l_dur.setObjectName("gorevDurSeridi")
        self.l_dur.setWordWrap(True)
        self.l_dur.setStyleSheet(f"QLabel#gorevDurSeridi {{ border: 2px solid {RENK['dur']}; border-radius: 6px;"
                                 f" padding: 8px 14px; font-weight: 700; }}")
        self.mt(self.l_dur.setText, G_DUR_SERIDI)
        self.l_dur.setVisible(False)
        kok.addWidget(self.l_dur)
        self.kutu = GorevKutusu()
        self.kutu.setMaximumHeight(96)
        self.kutu.setProperty("hata", False)
        self.mt(self.kutu.setPlaceholderText, T.G_KUTU_IPUCU)
        self.mt(self.kutu.setAccessibleName, G_KUTU_AD)
        kok.addWidget(self.kutu)
        self.kutu.gonder.connect(self.baslat)
        self.kutu.textChanged.connect(self._bos_uyari_kaldir)
        self.l_parola = QLabel()  # görev metni geçmişe/Claude'a gider: sır yazılmasın
        self.mt(self.l_parola.setText, T.G_PAROLA_UYARI)
        kok.addWidget(self.l_parola)
        site_sira = QHBoxLayout()
        self.l_siteler = QLabel()
        self.mt(self.l_siteler.setText, T.G_SITELER)
        self.siteler = QLineEdit()
        self.mt(self.siteler.setPlaceholderText, T.G_SITELER_IPUCU)
        self.mt(self.siteler.setToolTip, T.G_SITELER_ACIKLAMA)
        self.mt(self.siteler.setAccessibleName, G_SITELER_AD)
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
        self.mt(self.b_durdur.setText, G_GOREVI_DURDUR)
        self.mt(self.b_durdur.setToolTip, G_GOREVI_DURDUR_IPUCU)
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
        # ayar kaydı hatası: ne oldu + ne yapmalı; teknik ayrıntı katlı (Ayrıntı düğmesi)
        hata_sira = QHBoxLayout()
        self.l_hata = QLabel()
        self.l_hata.setWordWrap(True)
        self.b_ayrinti = QToolButton()
        self.b_ayrinti.setCheckable(True)
        self.b_ayrinti.setMinimumSize(24, 24)
        self.mt(self.b_ayrinti.setText, G_AYRINTI)
        self.b_ayrinti.toggled.connect(lambda acik: self.l_ayrinti.setVisible(acik and self._hata is not None))
        hata_sira.addWidget(self.l_hata, 1)
        hata_sira.addWidget(self.b_ayrinti, 0, Qt.AlignmentFlag.AlignTop)
        kok.addLayout(hata_sira)
        self.l_ayrinti = QLabel()
        self.l_ayrinti.setWordWrap(True)
        self.l_ayrinti.setTextFormat(Qt.TextFormat.PlainText)
        self.l_ayrinti.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        kok.addWidget(self.l_ayrinti)
        self._hata_yaz()

        bolme = QSplitter(Qt.Orientation.Horizontal)
        sol = QWidget()
        sl = QVBoxLayout(sol)
        sl.setContentsMargins(0, 0, 0, 0)
        self.l_adimlar = QLabel()
        self.mt(self.l_adimlar.setText, T.G_ADIMLAR)
        self.l_adimlar_bos = self._bos_etiket(T.G_ADIMLAR_BOS)  # boş durum: başlığın yanında (yer kaplamaz)
        sl.addLayout(self._baslik_sirasi(self.l_adimlar, self.l_adimlar_bos))
        self.liste = QListWidget()
        self.liste.setUniformItemSizes(False)
        self.liste.setWordWrap(True)
        self.liste.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.liste.setMinimumHeight(72)  # UX-F O8d: boşken de anlamlı boy
        sl.addWidget(self.liste, 3)
        self.l_sonuc = QLabel()
        self.mt(self.l_sonuc.setText, T.G_SONUC)
        sl.addWidget(self.l_sonuc)
        self.sonuc = QPlainTextEdit()
        self.sonuc.setReadOnly(True)
        self.mt(self.sonuc.setAccessibleName, G_SONUC_AD)
        self.sonuc.setMinimumHeight(72)
        self.sonuc.setMaximumHeight(140)
        self.mt(self.sonuc.setPlaceholderText, T.G_SONUC_BOS)
        sl.addWidget(self.sonuc)
        self.l_gecmis = QLabel()
        self.mt(self.l_gecmis.setText, T.G_GECMIS)
        self.l_gecmis_bos = self._bos_etiket(T.G_GECMIS_BOS)
        sl.addLayout(self._baslik_sirasi(self.l_gecmis, self.l_gecmis_bos))
        self.gecmis_liste = QListWidget()
        self.gecmis_liste.setMinimumHeight(72)
        self.gecmis_liste.setMaximumHeight(160)
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

    def _bos_etiket(self, msgid: str) -> QLabel:
        e = QLabel()
        self.mt(lambda m: e.setText("— " + m), msgid)
        return e

    @staticmethod
    def _baslik_sirasi(baslik: QLabel, bos: QLabel) -> QHBoxLayout:
        sira = QHBoxLayout()
        sira.setSpacing(8)
        sira.addWidget(baslik)
        sira.addWidget(bos, 1)
        return sira

    def _bos_durumlar(self) -> None:
        """Boş kutunun altında ne göreceğini söyleyen tek satır (UX-F O8d); kutu dolunca kalkar."""
        if hasattr(self, "l_adimlar_bos"):
            self.l_adimlar_bos.setVisible(self.liste.count() == 0)
        if hasattr(self, "l_gecmis_bos"):
            self.l_gecmis_bos.setVisible(self.gecmis_liste.count() == 0)

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
        kod = self.c_model.currentData()
        try:
            ayarlar.ayarla("gorev", "model", kod)
        except Exception as e:  # noqa: BLE001 - sessiz yutma yok: görünür ileti, seçim bu oturumda kullanılır
            self._model_kayitsiz = kod
            self._hata_goster(G_MODEL_KAYIT_HATA, e)
            return
        self._model_kayitsiz = None
        if self._hata and self._hata[0] == G_MODEL_KAYIT_HATA:
            self._hata_goster(None)

    # -------- görünür ayar hatası (ne oldu + ne yapmalı; ayrıntı katlı)
    def _hata_goster(self, kimlik: str | None, hata: BaseException | None = None) -> None:
        """Üst satır: sade cümle + ne yapılacak (GorevHatasi'nin ipucu; yoksa ham olmayan kısa iletisi; o da yoksa
        genel çare). Ham ileti (istisna metni) yalnız katlı Ayrıntı'da."""
        ayrinti = T.hata_ayrinti(hata) if hata is not None else ""
        ipucu = str(getattr(hata, "ipucu", "") or "")
        mesaj = str(getattr(hata, "mesaj", "") or "")
        if not ipucu and mesaj and not _HAM_ILETI.search(mesaj):
            ipucu = mesaj
        self._care = ipucu
        self._hata = (kimlik, ayrinti) if kimlik else None
        self.b_ayrinti.setChecked(False)
        self._hata_yaz()

    def _hata_yaz(self) -> None:
        h = self._hata
        self.l_hata.setVisible(h is not None)
        self.b_ayrinti.setVisible(h is not None)
        self.l_ayrinti.setVisible(h is not None and self.b_ayrinti.isChecked())
        if h is not None:
            m = _(h[0])
            self.l_hata.setText(m.format(care=self._care or _(T.G_BASLATMA_CARE)) if "{care}" in m else m)
            self.l_ayrinti.setText(h[1])
            pal = self.l_hata.palette()
            pal.setColor(QPalette.ColorRole.WindowText, QColor(RENK["dur"]))
            self.l_hata.setPalette(pal)

    # -------- düğmeler / durum
    def _dugmeler(self) -> None:
        c = self.calisiyor
        self.b_baslat.setEnabled(not c and not self.dur)
        self.l_dur.setVisible(self.dur)
        self.b_durdur.setEnabled(c and not self.durduruluyor)
        self.kutu.setReadOnly(c)
        self.siteler.setReadOnly(c)
        self.c_model.setEnabled(not c)
        self.gecmis_liste.setEnabled(not c)
        self.b_devral.setEnabled(self.sanal is not None)

    def _durum_yaz(self) -> None:
        if self._bos_uyari and not self.calisiyor:
            m = _(G_BOS_METIN)
        elif self.calisiyor:
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
        # DUR açıkken boşta "Hazır… Başlat'a basın" şeritle çelişir: gizlenir (neden + ne yapmalı şeritte)
        self.l_durum.setVisible(not (self.dur and not self.calisiyor))
        pal = self.l_durum.palette()
        renk = QColor(_DURUM_RENK["uyari"]) if self.calisiyor and self.bekleyen else self.palette().color(QPalette.ColorRole.WindowText)
        pal.setColor(QPalette.ColorRole.WindowText, renk)
        self.l_durum.setPalette(pal)

    def durum_guncelle(self, d: Durum) -> None:
        """Panel durumu: bekleyen onay sayısı (kart ödemesi vb.; diyalog panelde zaten açılır) ve DUR (açıkken görev
        başlatma yollarının hepsi kapalı + şerit; kalkınca hemen açılır)."""
        if d.bekleyen != self.bekleyen:
            self.bekleyen = d.bekleyen
            self._durum_yaz()
        dur = d.ad == "dur"
        if dur != self.dur:
            self.dur = dur
            self._dugmeler()
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
        self._hata_yaz()
        self._durum_yaz()
        self.gecmis_yenile()
        self.onizleme.update()

    # -------- başlat / durdur
    def baslat(self) -> None:
        if self.calisiyor or self.dur:  # DUR açıkken hiçbir yol (düğme, Ctrl+Enter, doğrudan çağrı) başlatmaz
            return
        metin = self.kutu.toPlainText().strip()
        if not metin:  # sessiz kalma: kısa ileti + kutu vurgusu + odak
            self._bos_uyari = True
            self.kutu.setProperty("hata", True)
            self.kutu.setStyleSheet(f"GorevKutusu {{ border: 2px solid {RENK['dur']}; border-radius: 4px; }}")
            self.kutu.setFocus()
            self._durum_yaz()
            return
        gecerli, ret = gorev_kipi.site_ayristir_ayrintili(self.siteler.text())
        if ret:  # joker / tek başına genel son ek / geçersiz ad: açık ileti, görev başlamaz
            self._bitis_durumu = "hata"
            self.sonuc.setPlainText(_(T.G_SITE_RET).format(nedenler="\n".join(ret)))
            self._durum_yaz()
            return
        siteler = ", ".join(gecerli)
        if self.onay_iste and baslat_onayi_sorulsun() and not self._onayla(metin, siteler):
            return
        if self._dur_simdi():  # UX-FIX D-4: onay penceresi açıkken DUR açıldı → onaylansa da başlamaz
            return
        self.liste.clear()
        self._bos_durumlar()
        self._adimlar.clear()
        self._dusunuyor = None
        self.sonuc.clear()
        if self._hata and self._hata[0] == T.G_BASLATMA_HATA_SADE:
            self._hata_goster(None)
        self.adim_sayisi = 0
        self._bitis_durumu = ""
        try:
            ek_g = {"model": self._model_kayitsiz} if self._model_kayitsiz else {}
            self.g = self.gorev_f(olay_cb=self.olay_geldi.emit, **ek_g)
            ek = {"siteler": siteler} if siteler else {}
            try:
                self.g.baslat(metin, **ek)
            except gorev.GorevHatasi as e:
                # görünmez masaüstü başka bir iş için açık: kullanıcı onaylarsa kapatılıp görev başlar
                if getattr(e, "kod", "") != "masaustu_acik" or not self._masaustu_kapat_onayla():
                    raise
                if self._dur_simdi():  # UX-FIX D-4: onay beklenirken DUR açıldı → masaüstü kapatılmaz, görev başlamaz
                    self.g = None
                    self._durum_yaz()
                    return
                self.g.baslat(metin, masaustu_kapat=True, **ek)
        except gorev.GorevHatasi as e:
            # UX-F O5: üstte sade cümle + ne yapılacak; ham ileti katlı "Ayrıntı" altında
            self.g = None
            self._bitis_durumu = "hata"
            self.sonuc.clear()
            self._hata_goster(T.G_BASLATMA_HATA_SADE, e)
            self._durum_yaz()
            return
        self.calisiyor, self.durduruluyor = True, False
        self.durum_degisti.emit(True)
        self._durum_yaz()
        self._dugmeler()
        self._zamanlayici()

    def _dur_simdi(self) -> bool:
        """DUR şu an açık mı? Panel durumu (self.dur) ya da DUR dosyası; denetlenemezse açık (kapalı-başarısız). Modal
        pencere (exec) dönüşünden sonra yeniden denetim için: pencere açıkken DUR açılmış olabilir."""
        if self.dur:
            return True
        try:
            from ..hata import dur_dosyasi
            return os.path.exists(dur_dosyasi())
        except Exception:  # noqa: BLE001 - karar verilemedi: başlatma
            return True

    def onay_metni(self, metin: str, siteler: str) -> str:
        kisa = " ".join(metin.split())
        kisa = kisa if len(kisa) <= 300 else kisa[:299] + "…"
        return _(T.G_ONAY_METIN).format(metin=kisa, siteler=siteler or _(T.G_ONAY_SITE_YOK))

    def _onayla(self, metin: str, siteler: str) -> bool:
        k = QMessageBox(QMessageBox.Icon.Question, _(T.G_ONAY_BASLIK), self.onay_metni(metin, siteler),
                        QMessageBox.StandardButton.Cancel, self)
        b = k.addButton(_(T.G_BASLAT), QMessageBox.ButtonRole.AcceptRole)
        k.setDefaultButton(b)
        if baslat_onayi_saklanabilir():
            k.setCheckBox(QCheckBox(_(G_BIR_DAHA_SORMA), k))  # ebeveyn k: Python çöp toplayıcısı silmesin
        k.exec()
        kabul = k.clickedButton() is b
        cb = k.checkBox()
        if kabul and cb is not None and cb.isChecked():
            try:
                ayarlar.ayarla(*ONAY_ANAHTARI, False)
            except Exception as e:  # noqa: BLE001 - görünür ileti; onay sonraki görevde yine sorulur
                self._hata_goster(G_TERCIH_KAYIT_HATA, e)
        return kabul

    def _bos_uyari_kaldir(self) -> None:
        if self._bos_uyari and self.kutu.toPlainText().strip():
            self._bos_uyari = False
            self.kutu.setProperty("hata", False)
            self.kutu.setStyleSheet("")
            self._durum_yaz()

    def _masaustu_kapat_onayla(self) -> bool:
        k = QMessageBox(QMessageBox.Icon.Warning, _(T.G_MASAUSTU_ACIK_BASLIK), _(T.G_MASAUSTU_ACIK_METIN),
                        QMessageBox.StandardButton.Cancel, self)
        b = k.addButton(_(T.G_MASAUSTU_KAPAT_BASLAT), QMessageBox.ButtonRole.AcceptRole)
        k.setDefaultButton(k.button(QMessageBox.StandardButton.Cancel))
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
        self._bos_durumlar()
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
        self._bos_durumlar()

    def _gecmis_sec(self, it: QListWidgetItem) -> None:
        g = it.data(Qt.ItemDataRole.UserRole)
        if self.calisiyor or not g:
            return
        self.liste.clear()
        self._bos_durumlar()
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
        if not hasattr(self, "_sinif_onb"):
            self._sinif_onb = {}
        try:  # 0.9.1: Görev sekmesi önizlemesi de yasak pencereleri karartır (Arka plan sekmesiyle aynı kural)
            au = self.arka_f()
            im = maskeli_goruntu(au, self._sinif_onb)
        except MaskeHatasi as e:  # denetlenemedi: kare HİÇ gösterilmez (güvenli taraf)
            self.onizleme.bos_metin = _(T.A_MASKE_HATA).format(hata=e.mesaj)
            self.onizleme.goster(None)
            return
        except Exception as e:  # noqa: BLE001 - masaüstü kapandı / X hatası
            self.onizleme.bos_metin = _(T.G_ONIZLEME_HATA).format(hata=getattr(e, "mesaj", None) or e)
            self.onizleme.goster(None)
            return
        q, kaynak = pil_qimage(im, self.onizleme.hedef_boyut() if self.onizleme.kaynak.width() else None)
        self.onizleme.goster(q, kaynak)
