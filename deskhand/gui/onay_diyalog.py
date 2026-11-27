"""Onay diyaloğu (docs/ARCHITECTURE.md §8): modal değil ama öne çıkan; "Bir kez izin ver" / "Reddet".

Kazara izne karşı:
- Varsayılan düğme ve odak Reddet; Enter/Return/Esc ve pencereyi kapatmak = Reddet.
- "Bir kez izin ver" klavye odağı ALMAZ (yalnız fareyle tıklanır) ve açılıştan sonra en az KURMA_MS devre dışıdır;
  bu süre dolduktan SONRA fare diyaloğun üzerinde gerçekten (en az HAREKET_PX) hareket etmeden de etkinleşmez:
  diyalog hızlı tıklayan (oyun oynayan) kullanıcının durağan imlecinin altında açılsa bile kazara tık izne dönüşmez.
  Qt tıklamayı yalnız basma + bırakma ikisi de etkin düğmedeyse sayar (devre dışıyken başlayan basış izin olmaz).
- Diyalog etkinleştirilmeden gösterilir (WA_ShowWithoutActivating): kullanıcının klavyesini çalmaz.
- Süre dolunca otomatik red; istek geri çekilirse (isteyen vazgeçti) diyalog kendiliğinden kapanır.
Sunum (UX-C, R1): üstte türün sabit cümlesi + NEYE izin verildiği (düğme/komut/tuş; tek satır, temiz, tırnaklı)
+ tek satır risk (guvenlik.onay_iletisi; tür isteğin yapısal "konu" alanından); isteyen süreç (ad + PID), pencere ve
masaüstü görünür satırlarda; ham eylem ve ham ayrıntı katlanır "Ayrıntılar"da (varsayılan kapalı; tür bilinmiyorsa
açık); tüm etiketler düz metin; geri sayım Reddet düğmesinde; izin düğmesinin güvenlik beklemesi düğme metninde
görünür; not normal renkte.
Pencere başlığı sabit: onay.ONAY_BASLIK; uygulama sınıfı onay.PANEL_SINIF (yasak pencere listesine eklenir).
"""
from __future__ import annotations

import os
import time

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase, QKeyEvent, QPixmap, QTextOption
from PyQt6.QtWidgets import (QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
                             QPushButton,
                             QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget)

from .. import guvenlik, onay
from ..i18n import N_, _
from . import metinler as T
from .dil import Metinler

KURMA_MS = 1500   # izin düğmesi en erken bu kadar sonra etkinleşebilir…
HAREKET_PX = 12   # …ve ancak bu süreden SONRA fare diyalog üzerinde en az bu kadar (|dx|+|dy|) hareket edince
GORUNTU_EN = 420
GORUNTU_BOY = 220
DUGME_EN = 150
EN_AZ_EN = 460

D_PENCERE = N_("Pencere")
D_KAYDIR = N_("Komutun tamamını görmek için kaydırın.")
KUTU_SATIR = 6  # komut/tuş kutusu en çok bu kadar satır yüksekliğinde; taşarsa kaydırma çubuğu + D_KAYDIR
D_ISTEYEN = N_("İsteyen")
D_AYRINTILAR = N_("Ayrıntılar")
D_DUGME_SURE = N_("{dugme} ({sure})")                      # Reddet (1:58): geri sayım düğmede
D_IZIN_BEKLE = N_("{dugme} ({sn} sn…)")                     # güvenlik beklemesi görünür (kazara izne karşı)
D_IZIN_FARE = N_("{dugme} (fareyi oynatın)")               # bekleme bitti: fare bu pencerede hareket edince açılır
D_IZIN_KAYDIR = N_("{dugme} (önce sona kaydırın)")          # taşan komut kutusu sona kaydırılmadan izin yok (UX-C-R1c)
D_SON_KISIM = N_("Son kısım: {metin}")
SON_KISIM = 60  # taşan kutunun altında ayrıca görünen son karakter sayısı


def sure_metni(sn: float) -> str:
    sn = max(0, int(sn + 0.999))
    return f"{sn // 60}:{sn % 60:02d}"


class OnayDiyalog(QDialog):
    karar_verildi = pyqtSignal(str, str)  # (istek id, "izin" | "red" | "sure" | "geri")
    devral_istendi = pyqtSignal(str)      # (istek id): insan doğrulaması devri, arka plan masaüstü → panel Devral açar

    def __init__(self, istek: dict, parent=None, yanitla=None, saat=time.time, kurma_ms: int = KURMA_MS,
                 istek_var=None, hareket_px: int = HAREKET_PX):
        super().__init__(parent)
        if yanitla is None:  # security scan 4: the answer carries the fingerprint of THIS request as shown here
            gosterilen = istek.get("_iz")

            def yanitla(k, karar):
                return onay.yanitla(k, karar, gosterilen=gosterilen)
        self.istek, self._yanitla, self.saat = istek, yanitla, saat
        self.ret_nedeni: str | None = None  # set when a Yes was refused (closed as "red", B5)
        self._istek_var = istek_var or (lambda: os.path.exists(onay.istek_yolu(self.istek_id)))
        self.bitti = False
        self.setObjectName("deskhandOnay")
        self.setWindowTitle(onay.ONAY_BASLIK)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(False)
        self.mt = Metinler()  # dil değişince tazele()

        kok = QVBoxLayout(self)
        kok.setContentsMargins(20, 18, 20, 16)
        kok.setSpacing(12)
        kok.addStrut(EN_AZ_EN - 40)  # en az genişlik düzenden (pencereye sabit en az genişlik düzenin büyütmesini keserdi)

        self.devir = istek.get("tur") == onay.TUR_DEVIR  # insan doğrulaması devri: Devral / Bitti / Vazgeç

        def deger(metin: str = "", kalin: bool = False) -> QLabel:
            e = QLabel(metin)
            e.setWordWrap(True)
            e.setTextFormat(Qt.TextFormat.PlainText)  # ajanın yazdığı metin HTML olarak yorumlanmasın
            e.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if kalin:
                ff = e.font()
                ff.setBold(True)
                e.setFont(ff)
            return e

        # Üstte tek cümle "ne olacak" + tek satır risk (guvenlik.onay_iletisi; panelin dilinde, gizli/yasak temiz)
        ust = QHBoxLayout()
        ust.setSpacing(12)
        ikon = QLabel()
        # sistem uyarı simgesi sakinleştirilir (doygunluk tavanı): ekranda tek doygun vurgu = Highlight (UX-K)
        from .ortak import sakin_pixmap
        ikon.setPixmap(sakin_pixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(40, 40)))
        ikon.setAlignment(Qt.AlignmentFlag.AlignTop)
        ust.addWidget(ikon)
        metin_kutu = QVBoxLayout()
        metin_kutu.setSpacing(6)
        self.l_baslik = deger(kalin=True)
        f = self.l_baslik.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        self.l_baslik.setFont(f)
        self.l_icerik = deger(kalin=True)  # NEYE izin verildiği: düğme / komut / tuş (katlı değil; YÜKSEK 1)
        self.l_icerik.setObjectName("icerik")
        self.l_risk = deger()
        self.l_risk.setObjectName("risk")
        metin_kutu.addWidget(self.l_baslik)
        metin_kutu.addWidget(self.l_icerik)
        # komut / tuş: TAMAMI (asla kesilmez; UX-C-R1b), eş aralıklı, salt okunur, satır kaydıran kutu
        self.k_icerik = QPlainTextEdit()
        self.k_icerik.setObjectName("icerikKutu")
        self.k_icerik.setReadOnly(True)
        self.k_icerik.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # odak Reddet'te kalır
        self.k_icerik.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.k_icerik.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.k_icerik.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        ef = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        ef.setStyleHint(QFont.StyleHint.TypeWriter)
        ef.setFixedPitch(True)  # eş aralıklı istenir (sistemde yoksa Qt en yakınını seçer)
        self.k_icerik.setFont(ef)
        self.k_icerik.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.k_icerik.setVisible(False)
        metin_kutu.addWidget(self.k_icerik)
        self.l_kaydir = deger()
        self.l_kaydir.setObjectName("kaydir")
        self.mt(self.l_kaydir.setText, D_KAYDIR)
        self.l_kaydir.setVisible(False)
        metin_kutu.addWidget(self.l_kaydir)
        self.l_son = deger(kalin=True)  # taşan kutu: tehlikeli SON kısım kaydırmadan da görünür
        self.l_son.setObjectName("sonKisim")
        self.l_son.setVisible(False)
        metin_kutu.addWidget(self.l_son)
        self._tasiyor = False
        self._sona_kaydirildi = False
        self._bekleme_tamam = False
        self.k_icerik.verticalScrollBar().valueChanged.connect(lambda _v: self._kaydirma_denetle())
        self.k_icerik.verticalScrollBar().rangeChanged.connect(lambda *_a: self._kaydirma_denetle())
        metin_kutu.addWidget(self.l_risk)
        ust.addLayout(metin_kutu, 1)
        kok.addLayout(ust)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.l_hedef = deger()
        self.l_masaustu = deger()
        ms = istek.get("masaustu", "ekran")
        masa = str(istek.get("masa") or "") if ms == "arka" else ""  # adlı görünmez masaüstü (çoklu masaüstü)
        self.mt.fn(lambda: self.l_masaustu.setText(
            (_(T.MASAUSTU[ms]) if ms in T.MASAUSTU else str(ms or "")) + (f" — {masa}" if masa else "")))

        def satir(msgid: str, alan: QLabel):
            e = QLabel()
            e.setTextFormat(Qt.TextFormat.PlainText)
            self.mt(e.setText, msgid)
            form.addRow(e, alan)
            return e

        self.l_isteyen = deger()
        self._hedef_satiri = satir(D_PENCERE, self.l_hedef)
        satir(T.D_MASAUSTU, self.l_masaustu)
        self._isteyen_satiri = satir(D_ISTEYEN, self.l_isteyen)
        kok.addLayout(form)

        # Ayrıntılar (ham eylem dizgisi, pencere, ham ayrıntı, PID): katlanır, varsayılan KAPALI
        self.b_ayrinti = QToolButton()
        self.b_ayrinti.setCheckable(True)
        self.b_ayrinti.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_ayrinti.setAutoRaise(True)
        self.b_ayrinti.setArrowType(Qt.ArrowType.RightArrow)
        self.mt(self.b_ayrinti.setText, D_AYRINTILAR)
        self.b_ayrinti.toggled.connect(self.ayrinti_ac)
        kok.addWidget(self.b_ayrinti, 0, Qt.AlignmentFlag.AlignLeft)
        self.w_ayrinti = QFrame()
        self.w_ayrinti.setFrameShape(QFrame.Shape.StyledPanel)
        al = QVBoxLayout(self.w_ayrinti)
        al.setContentsMargins(8, 8, 8, 8)
        self.l_ayrinti = deger()
        al.addWidget(self.l_ayrinti)
        self.l_eylem = self.l_ayrinti  # eski ad (ham eylem artık yalnız Ayrıntılar'da)
        self.w_ayrinti.setVisible(False)
        kok.addWidget(self.w_ayrinti)
        self.mt.fn(self._iletiyi_yaz)
        if self.ileti["tur"] == "bilinmeyen":  # türü doğrulanamayan istek: ham eylem ve ayrıntı baştan görünür
            self.ayrinti_ac(True)

        self.l_goruntu = None
        g = istek.get("goruntu")
        if g and os.path.isfile(g):
            pm = QPixmap(g)
            if not pm.isNull():
                cer = QFrame()
                cer.setFrameShape(QFrame.Shape.StyledPanel)
                cl = QVBoxLayout(cer)
                cl.setContentsMargins(4, 4, 4, 4)
                self.l_goruntu = QLabel()
                self.l_goruntu.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if pm.width() > GORUNTU_EN or pm.height() > GORUNTU_BOY:  # yalnız küçült (büyütme bulanıklaştırır)
                    pm = pm.scaled(GORUNTU_EN, GORUNTU_BOY, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
                self.l_goruntu.setPixmap(pm)
                cl.addWidget(self.l_goruntu)
                kok.addWidget(cer)

        self.cubuk = QProgressBar()
        self.cubuk.setTextVisible(False)
        self.cubuk.setFixedHeight(6)
        toplam = max(1.0, float(istek.get("son_zaman", 0)) - float(istek.get("zaman", 0) or saat()))
        self.toplam = toplam
        self.cubuk.setRange(0, 1000)
        kok.addWidget(self.cubuk)
        self.l_kalan = QLabel()
        self.l_kalan.setTextFormat(Qt.TextFormat.PlainText)
        self.l_kalan.setWordWrap(True)
        kok.addWidget(self.l_kalan)
        self.l_not = QLabel()
        self.l_not.setTextFormat(Qt.TextFormat.PlainText)
        self.mt(self.l_not.setText, T.D_DEVIR_NOT if self.devir else T.D_NOT)
        self.l_not.setWordWrap(True)  # normal metin rengi (soluk değil): kontrast ≥ tokens kontrast_min
        kok.addWidget(self.l_not)

        dugmeler = QHBoxLayout()
        dugmeler.addStretch(1)
        self.b_red = QPushButton()  # metin + geri sayım: _dugme_metinleri
        self.b_red.setDefault(True)
        self.b_red.setAutoDefault(True)
        self.b_red.clicked.connect(lambda: self._karar("red"))
        self.b_izin = QPushButton()
        self.b_izin.setAutoDefault(False)
        self.b_izin.setDefault(False)
        self.b_izin.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # yalnız fareyle: Enter/boşluk izne dönüşmez
        self._bekleme_tamam = kurma_ms <= 0  # kurma_ms <= 0: bekleme koruması yok (yalnız testler)
        self._kurma_bitti = kurma_ms <= 0
        self.b_izin.setEnabled(self._izin_acilabilir())
        self._kurma_son = time.monotonic() + max(0, kurma_ms) / 1000.0
        self._hareket_px = max(0, int(hareket_px)) if kurma_ms > 0 else 0
        self._ilk_konum = None
        if kurma_ms > 0:
            self.mt(self.b_izin.setToolTip, T.D_IZIN_IPUCU)
        self.b_izin.clicked.connect(lambda: self._karar("izin"))
        for b in (self.b_red, self.b_izin):
            b.setMinimumWidth(DUGME_EN)
            b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.b_devral = None
        if self.devir and istek.get("masaustu") == "arka":
            self.b_devral = QPushButton()
            self.mt(self.b_devral.setText, T.D_DEVIR_DEVRAL)
            self.b_devral.setAutoDefault(False)
            self.b_devral.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.b_devral.setMinimumWidth(DUGME_EN)
            self.b_devral.clicked.connect(lambda: self.devral_istendi.emit(self.istek_id))
            dugmeler.addWidget(self.b_devral)
        dugmeler.addWidget(self.b_red)
        dugmeler.addWidget(self.b_izin)
        kok.addLayout(dugmeler)
        self.b_red.setFocus()
        for w in (self, *self.findChildren(QWidget)):  # gerçek fare hareketi: düğmesiz hareket olayları da gelsin
            w.setMouseTracking(True)
            w.installEventFilter(self)

        if kurma_ms > 0:
            QTimer.singleShot(kurma_ms, self._kur)
        self.sayac = QTimer(self)
        self.sayac.setInterval(250)
        self.sayac.timeout.connect(self._tik)
        self.sayac.start()
        self._tik()
        self.adjustSize()  # sarılan başlık/risk satırı ve geri sayımlı düğmeler kırpılmasın

    @property
    def istek_id(self) -> str:
        return self.istek.get("id", "")

    def _iletiyi_yaz(self):
        """Başlık cümlesi, risk satırı, pencere adı ve Ayrıntılar metni (panelin dilinde; dil değişince yeniden)."""
        ileti = guvenlik.onay_iletisi(self.istek)
        self.ileti = ileti
        self.l_baslik.setText(ileti["baslik"])
        kutu = bool(ileti.get("icerik_kutu"))
        self.l_icerik.setText(ileti["icerik_etiket"] + ":" if kutu else ileti["icerik"])
        self.l_icerik.setVisible(bool(ileti["icerik"]))
        self.k_icerik.setPlainText(ileti["icerik_deger"] if kutu else "")
        self.k_icerik.setVisible(kutu)
        self._kutu_boyu()
        self.l_risk.setText(ileti["risk"])
        self.l_isteyen.setText(ileti["isteyen"])
        self.l_isteyen.setVisible(bool(ileti["isteyen"]))
        self._isteyen_satiri.setVisible(bool(ileti["isteyen"]))
        self.l_hedef.setText(ileti["hedef"])
        self.l_hedef.setVisible(bool(ileti["hedef"].strip()))
        self._hedef_satiri.setVisible(bool(ileti["hedef"].strip()))
        self.l_ayrinti.setText(ileti["ayrinti"])

    def _kutu_boyu(self):
        """Komut kutusu: içeriğe göre 1..KUTU_SATIR satır yüksekliği; taşarsa kaydırma notu görünür."""
        if not self.k_icerik.isVisible() and not self.k_icerik.toPlainText():
            self.l_kaydir.setVisible(False)
            return
        fm = self.k_icerik.fontMetrics()
        en = max(1, self.k_icerik.viewport().width() or (EN_AZ_EN - 120))
        sutun = max(1, en // max(1, fm.horizontalAdvance("M")))
        satir = sum(max(1, -(-len(p) // sutun)) for p in self.k_icerik.toPlainText().split("\n"))
        ic = 2 * (self.k_icerik.frameWidth() + int(self.k_icerik.document().documentMargin()))
        self.k_icerik.setFixedHeight(min(satir, KUTU_SATIR) * fm.lineSpacing() + ic + 2)
        self._kaydirma_denetle(satir > KUTU_SATIR)

    def _kaydirma_denetle(self, tahmin_tasar: bool = False):
        """Kutu taşıyor mu (görünürken kaydırma çubuğundan, görünmeden önce satır tahmininden): taşıyorsa kaydırma notu +
        "Son kısım" satırı görünür ve izin düğmesi kutu bir kez sona kaydırılana dek pasif (Reddet hep etkin)."""
        k = self.k_icerik
        if not k.isVisibleTo(self) or not k.toPlainText():
            self._tasiyor = False
        else:
            sb = k.verticalScrollBar()
            self._tasiyor = sb.maximum() > 0 if k.isVisible() else (tahmin_tasar or sb.maximum() > 0)
            if self._tasiyor and k.isVisible() and sb.value() >= sb.maximum():
                self._sona_kaydirildi = True
        self.l_kaydir.setVisible(self._tasiyor)
        if self._tasiyor:
            metin = k.toPlainText()
            son = metin if len(metin) <= SON_KISIM else "…" + metin[-SON_KISIM:]
            self.l_son.setText(_(D_SON_KISIM).format(metin=son))
        self.l_son.setVisible(self._tasiyor)
        if hasattr(self, "_kurma_son"):  # düğmeler kurulduysa
            self.b_izin.setEnabled(self._izin_acilabilir())
            self._dugme_metinleri()

    def _izin_acilabilir(self) -> bool:
        """İzin düğmesi: güvenlik beklemesi (kurma + fare hareketi) bitti VE taşan komut kutusu sona kaydırıldı."""
        return (self._bekleme_tamam and not self.bitti and (not self._tasiyor or self._sona_kaydirildi)
                and (not hasattr(self, "toplam") or self.kalan() > 0))

    def resizeEvent(self, e):  # noqa: N802 - Qt API
        super().resizeEvent(e)
        self._kutu_boyu()

    def showEvent(self, e):  # noqa: N802 - Qt API
        super().showEvent(e)
        self._kutu_boyu()

    def ayrinti_ac(self, acik: bool = True):
        """Ayrıntılar alanını aç/kapat (varsayılan kapalı)."""
        acik = bool(acik)
        if self.b_ayrinti.isChecked() != acik:
            self.b_ayrinti.setChecked(acik)  # toggled → yeniden buraya
            return
        self.b_ayrinti.setArrowType(Qt.ArrowType.DownArrow if acik else Qt.ArrowType.RightArrow)
        self.w_ayrinti.setVisible(acik)
        self.adjustSize()

    def _dugme_metinleri(self, kalan: float | None = None):
        """Reddet düğmesinde geri sayım; izin düğmesinin güvenlik beklemesi metinle görünür (bozuk sanılmasın)."""
        k = self.kalan() if kalan is None else kalan
        red = _(T.D_DEVIR_VAZGEC if self.devir else T.D_RED)
        self.b_red.setText(_(D_DUGME_SURE).format(dugme=red, sure=sure_metni(k)))
        izin = _(T.D_DEVIR_BITTI if self.devir else T.D_IZIN)
        if self.b_izin.isEnabled() or self.bitti:
            self.b_izin.setText(izin)
        elif self._bekleme_tamam and self._tasiyor and not self._sona_kaydirildi:
            self.b_izin.setText(_(D_IZIN_KAYDIR).format(dugme=izin))
        elif not self._kurma_bitti:
            sn = max(1, int(self._kurma_son - time.monotonic() + 0.999))
            self.b_izin.setText(_(D_IZIN_BEKLE).format(dugme=izin, sn=sn))
        else:
            self.b_izin.setText(_(D_IZIN_FARE).format(dugme=izin))
        for b in (self.b_red, self.b_izin):  # sabit en az genişlik metni kırpmasın (geri sayım düğmeyi uzatır)
            b.setMinimumWidth(max(DUGME_EN, b.sizeHint().width()))

    def _kur(self):
        """Kurma süresi doldu: bundan SONRAKİ ilk gerçek fare hareketi düğmeyi etkinleştirir."""
        if self.bitti:
            return
        self._kurma_bitti = True
        self._ilk_konum = None  # süre içindeki hareket sayılmaz
        if self._hareket_px <= 0:
            self._bekleme_tamam = True
            self.b_izin.setEnabled(self._izin_acilabilir())
        self._dugme_metinleri()

    def eventFilter(self, nesne, olay):  # noqa: N802 - Qt API
        if (olay.type() == QEvent.Type.MouseMove and self._kurma_bitti and not self.bitti
                and not self._bekleme_tamam):
            p = olay.globalPosition()
            if self._ilk_konum is None:  # pencere imlecin altında açılınca gelen yapay hareket (aynı nokta) sayılmaz
                self._ilk_konum = p
            elif abs(p.x() - self._ilk_konum.x()) + abs(p.y() - self._ilk_konum.y()) >= self._hareket_px:
                self._bekleme_tamam = True
                self.b_izin.setEnabled(self._izin_acilabilir())
                self._dugme_metinleri()
        return False  # olay yutulmaz

    def kalan(self) -> float:
        return float(self.istek.get("son_zaman", 0)) - self.saat()

    def _tik(self):
        if self.bitti:
            return
        k = self.kalan()
        if k <= 0:
            self._karar("red", neden="sure")
            return
        if not self._istek_var():
            self._bitir("geri")  # isteyen vazgeçti / zaten yanıtlandı
            return
        self.cubuk.setValue(int(1000 * max(0.0, min(1.0, k / self.toplam))))
        self._dugme_metinleri(k)
        self.l_kalan.setText(_(T.D_KALAN_DEVIR if self.devir else T.D_KALAN).format(s=sure_metni(k)))

    def _karar(self, karar: str, neden: str | None = None, kapat: bool = True):
        if self.bitti:
            return
        if karar == "izin" and (not self.b_izin.isEnabled() or self.kalan() <= 0):
            return
        if karar == "izin" and kapat:
            self.hide()  # izin isteyene ulaşmadan önce: isteyen onaylanan bölgeyi yeniden görüntülerken diyalog örtmesin
        gitti = self._yanitla(self.istek_id, karar)  # izin YALNIZ onay kanalından gider (onay.yanitla)
        if karar == "izin" and gitti is False:
            # the Yes was refused (request changed / not as the requester wrote it / already answered): never
            # reported as "izin" (review INC3 B5); the reason is shown by the panel (onay.onay_reddedildi)
            self.ret_nedeni = "izin-reddedildi"
            self._bitir("red", kapat)
            return
        self._bitir(neden or karar, kapat)

    def _bitir(self, neden: str, kapat: bool = True):
        if self.bitti:
            return
        self.bitti = True
        self.sayac.stop()
        self.karar_verildi.emit(self.istek_id, neden)
        if kapat:
            self.close()

    def tazele(self):
        """Dil değişti: diyalog metinleri yeni dilde (ajanın yazdığı eylem/hedef/ayrıntı olduğu gibi kalır)."""
        self.mt.tazele()
        if not self.bitti:
            self._tik()

    def geri_cekildi(self):
        """Panel: istek artık bekleyenlerde değil (yanıtlandı/süresi doldu/isteyen vazgeçti)."""
        self._bitir("geri")

    # -------- klavye ve kapatma = red
    def keyPressEvent(self, e: QKeyEvent):  # noqa: N802 - Qt API
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self._karar("red")
            e.accept()
            return
        super().keyPressEvent(e)

    def reject(self):
        self._karar("red")

    def closeEvent(self, e):  # noqa: N802 - Qt API
        if not self.bitti:
            self._karar("red", kapat=False)  # iç içe close() yok: uygulama çıkışını engellemesin
        e.accept()
