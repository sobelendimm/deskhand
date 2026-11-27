"""Ayarlar sekmesi."""
from __future__ import annotations


from PyQt6.QtCore import (Qt, pyqtSignal)
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                             QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                             QSpinBox, QVBoxLayout, QWidget)

from ... import i18n
from ...i18n import N_, _
from .. import ayar as A
from .. import metinler as T
from ..dil import Metinler, dil_secenekleri
from ..kisayol import VARSAYILAN_TUS, cakismalar
from ..ortak import (soluk_etiket)


# =========================================================================== Ayarlar

Y_DOGRULANMADI = N_("DOĞRULANMADI — dosyadaki onaylanmamış girişler (salt okunur). Cüzdan okununca panel imzalı kaydı "
                    "geri yükler (imzalı kayıt yoksa girişleri yeniden sorar); o zamana kadar Deskhand durdu (Dur 10).")
Y_DOSYADA_FARKLI = N_("Ayar dosyasında doğrulanmamış değer var ({deger}); uygulanmıyor. Gösterilen, geçerli değerdir.")


class AyarlarSekmesi(QScrollArea):
    kisayol_degisti = pyqtSignal(bool, str)
    dil_degisti = pyqtSignal(str)  # yeni etkin dil kodu (i18n yeniden yüklendikten SONRA)

    def __init__(self, parent=None, karar: A.KararAyarlari | None = None, cakisma_f=cakismalar):
        super().__init__(parent)
        self.karar = karar if karar is not None else A.KararAyarlari()
        self.cakisma_f = cakisma_f
        self._liste_kilitli: dict[str, bool] = {}
        self.mt = Metinler()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        govde = QWidget()
        kok = QVBoxLayout(govde)
        kok.setSpacing(14)

        # ---- meşgulken
        g = self._grup(T.Y_MESGUL)
        gl = QFormLayout(g)
        if self.karar.var:
            mevcut = self.karar.oku()
            self.c_mesgul = QComboBox()
            self._doldur(self.c_mesgul, self.karar.mesgulken_secenek, T.Y_MESGUL_SECENEK)
            self._sec(self.c_mesgul, mevcut.get("mesgulken"))
            self.s_sure = QSpinBox()
            self.s_sure.setRange(*[int(v) for v in self.karar.sor_sure_aralik])
            self.mt.fn(lambda: self.s_sure.setSuffix(" " + _(T.Y_SN)))
            try:
                self.s_sure.setValue(int(mevcut.get("sor_sure") or 30))
            except (TypeError, ValueError):
                self.s_sure.setValue(30)
            self.c_cevapsiz = QComboBox()
            self._doldur(self.c_cevapsiz, self.karar.cevapsiz_secenek, T.Y_CEVAPSIZ_SECENEK)
            self._sec(self.c_cevapsiz, mevcut.get("cevapsiz"))
            gl.addRow(self._etiket(T.Y_MESGULKEN), self.c_mesgul)
            gl.addRow(self._etiket(T.Y_SOR_SURE), self.s_sure)
            gl.addRow(self._etiket(T.Y_CEVAPSIZ), self.c_cevapsiz)
            self.k_tam = None
            if "tam_ekranda_sor" in self.karar.anahtarlar:
                self.k_tam = QCheckBox()
                self.mt(self.k_tam.setText, T.Y_TAM_EKRAN)
                self.k_tam.setChecked(bool(mevcut.get("tam_ekranda_sor")))
                self.mt(self.k_tam.setToolTip, T.Y_TAM_EKRAN_NOT)
                gl.addRow("", self.k_tam)
            b = QPushButton()
            self.mt(b.setText, T.Y_KAYDET)
            b.clicked.connect(self.karar_kaydet)
            self.l_karar = soluk_etiket("")
            gl.addRow(b, self.l_karar)
        else:
            gl.addRow(self._soluk(T.Y_MESGUL_YOK))
        kok.addWidget(g)

        # ---- onay soruları (kapsam): hepsi | kart; seçilince hemen kaydedilir
        g = self._grup(T.Y_ONAY)
        gl = QFormLayout(g)
        self.c_onay = QComboBox()
        self._doldur(self.c_onay, A.ONAY_KAPSAMLARI, T.Y_ONAY_SECENEK)
        self._sec(self.c_onay, A.onay_kapsami_oku())
        self.c_onay.activated.connect(lambda i: self.onay_kapsami_sec(self.c_onay.itemData(i)))
        gl.addRow(self._etiket(T.Y_ONAY_SORULARI), self.c_onay)
        self.l_onay = soluk_etiket("")
        gl.addRow(self.l_onay)
        gl.addRow(self._soluk(T.Y_ONAY_NOT))
        kok.addWidget(g)

        # ---- hesap oturumları (panel yetkili; açarken onay diyaloğu): Microsoft / Google
        g = self._grup(T.Y_HESAP)
        gl = QVBoxLayout(g)
        uyari = QLabel()
        uyari.setWordWrap(True)
        self.mt(lambda m, e=uyari: e.setText("⚠ " + m), T.Y_HESAP_UYARI)
        gl.addWidget(uyari)
        acik = A.hesap_oturumlari_oku()
        self.k_hesap_hepsi = QCheckBox()  # ana anahtar: üçünü birlikte açar/kapatır
        self.mt(self.k_hesap_hepsi.setText, T.Y_HESAP_HEPSI)
        self.k_hesap_hepsi.setChecked(set(A.HESAP_SAGLAYICILARI) <= acik)
        self.k_hesap_hepsi.toggled.connect(self.hesap_hepsi_sec)
        gl.addWidget(self.k_hesap_hepsi)
        self.k_hesap: dict[str, QCheckBox] = {}
        for sag in A.HESAP_SAGLAYICILARI:
            k = QCheckBox()
            self.mt(k.setText, T.Y_HESAP_SECENEK[sag])
            k.setChecked(sag in acik)
            k.toggled.connect(lambda durum, sag=sag: self.hesap_oturumu_sec(sag, durum))
            self.k_hesap[sag] = k
            k.setStyleSheet("QCheckBox { margin-left: 22px; }")  # ana anahtarın altında girintili
            gl.addWidget(k)
        self.l_hesap = soluk_etiket("")
        gl.addWidget(self.l_hesap)
        gl.addWidget(self._soluk(T.Y_HESAP_NOT))
        kok.addWidget(g)

        # ---- yasak pencereler
        g = self._grup(T.Y_YASAK)
        gl = QVBoxLayout(g)
        gl.addWidget(self._soluk(T.Y_YASAK_ACIKLAMA))
        self.yasak = QPlainTextEdit()
        f = self.yasak.font()
        f.setFamily("monospace")
        f.setStyleHint(f.StyleHint.Monospace)
        self.yasak.setFont(f)
        self.yasak.setMinimumHeight(150)
        gl.addWidget(self.yasak)
        sat = QHBoxLayout()
        self.l_yasak = QLabel("")
        self.l_yasak.setWordWrap(True)
        sat.addWidget(self.l_yasak, 1)
        b_geri = QPushButton()
        self.mt(b_geri.setText, T.Y_GERI_AL)
        b_geri.clicked.connect(self.yasak_yukle)
        b_kaydet = QPushButton()
        self.mt(b_kaydet.setText, T.Y_KAYDET)
        b_kaydet.clicked.connect(self.yasak_kaydet)
        self.b_yasak_kaydet = b_kaydet
        sat.addWidget(b_geri)
        sat.addWidget(b_kaydet)
        gl.addLayout(sat)
        kok.addWidget(g)
        self.yasak_yukle()

        # ---- uygulama erişim seviyeleri (yasak pencerelerle aynı kalıp)
        g = self._grup(T.Y_SEVIYE)
        gl = QVBoxLayout(g)
        gl.addWidget(self._soluk(T.Y_SEVIYE_ACIKLAMA))
        self.seviye = QPlainTextEdit()
        f = self.seviye.font()
        f.setFamily("monospace")
        f.setStyleHint(f.StyleHint.Monospace)
        self.seviye.setFont(f)
        self.seviye.setMinimumHeight(110)
        gl.addWidget(self.seviye)
        sat = QHBoxLayout()
        self.l_seviye = QLabel("")
        self.l_seviye.setWordWrap(True)
        sat.addWidget(self.l_seviye, 1)
        b_geri = QPushButton()
        self.mt(b_geri.setText, T.Y_GERI_AL)
        b_geri.clicked.connect(self.seviye_yukle)
        b_kaydet = QPushButton()
        self.mt(b_kaydet.setText, T.Y_KAYDET)
        b_kaydet.clicked.connect(self.seviye_kaydet)
        self.b_seviye_kaydet = b_kaydet
        sat.addWidget(b_geri)
        sat.addWidget(b_kaydet)
        gl.addLayout(sat)
        kok.addWidget(g)
        self.seviye_yukle()

        # ---- kısayol
        panel = A.panel_oku()
        g = self._grup(T.Y_KISAYOL)
        gl = QFormLayout(g)
        self.k_acik = QCheckBox()
        self.mt(self.k_acik.setText, T.Y_KISAYOL_AC)
        self.k_acik.setChecked(panel["kisayol_acik"])
        self.k_tus = QKeySequenceEdit(QKeySequence(panel["kisayol"]))
        self.k_tus.setMaximumWidth(340)
        if hasattr(self.k_tus, "setMaximumSequenceLength"):
            self.k_tus.setMaximumSequenceLength(1)
        if hasattr(self.k_tus, "setClearButtonEnabled"):
            self.k_tus.setClearButtonEnabled(True)
        # Qt tuş adlarını NativeText ile, Qt'nin kendi (sistem dili) çevirisiyle gösterir: Türkçe Qt çevirisi
        # "Meta+Seçenek+Vazgeç" yazıyordu. Kutu, KDE'nin ve kglobalshortcutsrc'nin kullandığı PortableText'i
        # (Meta+Alt+Esc) gösterir; kaydedilen değer zaten PortableText.
        self.k_tus.keySequenceChanged.connect(self._tus_yaz)
        self.k_tus.editingFinished.connect(self._tus_yaz)
        self._tus_yaz()
        self.l_kisayol = QLabel("")
        self.l_kisayol.setWordWrap(True)
        gl.addRow(self.k_acik)
        gl.addRow(self._etiket(T.Y_KISAYOL_TUS), self.k_tus)
        gl.addRow(self.l_kisayol)
        gl.addRow(self._soluk(T.Y_KISAYOL_NOT))
        self.k_acik.toggled.connect(self._kisayol_kaydet)
        self.k_tus.editingFinished.connect(self._kisayol_kaydet)
        kok.addWidget(g)
        self.cakisma_goster()

        # ---- dil
        g = self._grup(T.Y_DIL)
        gl = QFormLayout(g)
        self.c_dil = QComboBox()
        for kod, ad in dil_secenekleri():
            self.c_dil.addItem(ad, kod)
        self.mt.fn(self._dil_adlari)
        self._dil_secili()
        self.c_dil.activated.connect(lambda i: self.dil_sec(self.c_dil.itemData(i)))
        gl.addRow(self._etiket(T.Y_DIL), self.c_dil)
        self.l_dil = QLabel("")
        self.l_dil.setWordWrap(True)
        self.l_dil.setVisible(False)
        gl.addRow(self.l_dil)
        gl.addRow(self._soluk(T.Y_DIL_NOT))
        kok.addWidget(g)
        kok.addStretch(1)
        self.setWidget(govde)

    # -------- metin yardımcıları (dil değişince tazele() hepsini yeniden yazar)
    def _grup(self, msgid: str) -> QGroupBox:
        g = QGroupBox()
        self.mt(g.setTitle, msgid)
        return g

    def _etiket(self, msgid: str) -> QLabel:
        e = QLabel()
        self.mt(e.setText, msgid)
        return e

    def _soluk(self, msgid: str) -> QLabel:
        e = soluk_etiket("")
        self.mt(e.setText, msgid)
        return e

    def _doldur(self, c: QComboBox, anahtarlar, adlar: dict) -> None:
        for i, k in enumerate(anahtarlar):
            c.addItem("", k)
            self.mt.fn(lambda c=c, i=i, k=k: c.setItemText(i, _(adlar[k]) if k in adlar else str(k)))

    def _tus_yaz(self, *_a) -> None:
        kutu = self.k_tus.findChild(QLineEdit)
        if kutu is not None:
            kutu.setText(self.k_tus.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def tazele(self) -> None:
        self.mt.tazele()
        self._tus_yaz()
        self.cakisma_goster()
        for e in (getattr(self, "l_karar", None), self.l_onay, self.l_yasak, self.l_seviye):  # eski dildeki "Kaydedildi." vb.
            if e is not None:
                e.setText("")

    # -------- dil
    def _dil_adlari(self) -> None:
        for kod, ad in dil_secenekleri():
            j = self.c_dil.findData(kod)
            if j >= 0:
                self.c_dil.setItemText(j, ad)

    def _dil_secili(self) -> None:
        self.c_dil.blockSignals(True)
        self.c_dil.setCurrentIndex(max(0, self.c_dil.findData(i18n.ayar_oku())))
        self.c_dil.blockSignals(False)

    def dil_sec(self, kod: str) -> bool:
        """Seçimi CONFIG_DIR/arayuz.json'a yaz, kataloğu yeniden yükle, dil_degisti yay (panel metinleri
        tazelenir). → True: seçim değişti."""
        if kod == i18n.ayar_oku():
            return False
        try:
            i18n.ayar_yaz(kod)
        except (OSError, ValueError) as e:
            self._dil_secili()
            self.l_dil.setText(_(T.Y_DIL_HATA).format(hata=e))
            self.l_dil.setVisible(True)
            return False
        yeni = i18n.yeniden_yukle()
        istenen = i18n.sistem_dili() if kod == i18n.OTOMATIK else kod
        self._dil_secili()
        self.dil_degisti.emit(yeni)  # → AnaPencere.tazele → bu sekmenin tazele()'si
        if yeni != istenen:  # DESKHAND_DIL bu süreçte dili zorluyor
            self.l_dil.setText(_(T.Y_DIL_ZORLA).format(dil=i18n.DILLER.get(yeni, yeni)))
            self.l_dil.setVisible(True)
        else:
            self.l_dil.setText("")
            self.l_dil.setVisible(False)
        return True

    @staticmethod
    def _sec(c: QComboBox, deger):
        i = c.findData(deger)
        if i >= 0:
            c.setCurrentIndex(i)

    def panel_degerleri_yukle(self) -> None:
        """Onay kapsamı + hesap oturumları: arka ucun UYGULADIĞI (panelin yetkili) değer, sinyal üretmeden. Sekme
        panel koruyucusundan (liste_koruma.panel_baslat) ÖNCE kurulur: panel açılışta ve sekme her gösterildiğinde
        bunu çağırır. Dosyada başka (doğrulanmamış) değer yazıyorsa boş kutuyla gizlenmez, etiketlenir."""
        from ... import liste_koruma
        kapsam = A.onay_kapsami_oku()
        self._sec(self.c_onay, kapsam)
        self._hesap_kutulari()
        dosya_kapsam = liste_koruma._kapsam_dosyadan()
        self._farkli_etiket(self.l_onay, dosya_kapsam != kapsam,
                            _(T.Y_ONAY_SECENEK.get(dosya_kapsam, dosya_kapsam)))
        dosya_kimlik = liste_koruma.kimlik_dosyada()
        self._farkli_etiket(self.l_hesap, dosya_kimlik != A.hesap_oturumlari_oku(),
                            ", ".join(_(T.Y_HESAP_AD[s]) for s in A.HESAP_SAGLAYICILARI if s in dosya_kimlik) or "—")

    def _farkli_etiket(self, etiket: QLabel, farkli: bool, dosyadaki: str) -> None:
        if farkli:
            etiket.setText(_(Y_DOSYADA_FARKLI).format(deger=dosyadaki))
        elif etiket.property("dosyada_farkli"):
            etiket.setText("")
        etiket.setProperty("dosyada_farkli", farkli)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        from ... import liste_koruma
        if liste_koruma.AKTIF is not None:  # panel sürecinde: bellek okuması (kanal çağrısı yok)
            self.panel_degerleri_yukle()

    def karar_kaydet(self):
        try:
            d = {"mesgulken": self.c_mesgul.currentData(), "sor_sure": self.s_sure.value(),
                 "cevapsiz": self.c_cevapsiz.currentData()}
            if self.k_tam is not None:
                d["tam_ekranda_sor"] = self.k_tam.isChecked()
            self.karar.yaz(d)
            self.l_karar.setText(_(T.Y_KAYDEDILDI))
        except Exception as e:  # noqa: BLE001
            self.l_karar.setText(str(e))

    def onay_kapsami_sec(self, kapsam: str) -> bool:
        try:
            A.onay_kapsami_yaz(kapsam)
        except Exception as e:  # noqa: BLE001
            self._sec(self.c_onay, A.onay_kapsami_oku())
            self.l_onay.setText(_(T.Y_ONAY_HATA).format(hata=e))
            return False
        self.l_onay.setText(_(T.Y_KAYDEDILDI))
        return True

    def hesap_onay_sor(self, saglayici: str) -> bool:
        """Açmadan önce Evet/Hayır (varsayılan Hayır). Testler bu yöntemi değiştirir."""
        hesap = _(T.Y_HESAP_AD[saglayici])
        k = QMessageBox(QMessageBox.Icon.Warning, _(T.Y_HESAP_SORU_BASLIK).format(hesap=hesap),
                        _(T.Y_HESAP_SORU).format(hesap=hesap), QMessageBox.StandardButton.NoButton, self)
        evet = k.addButton(_(T.EVET), QMessageBox.ButtonRole.YesRole)
        hayir = k.addButton(_(T.HAYIR), QMessageBox.ButtonRole.NoRole)
        k.setDefaultButton(hayir)
        k.setEscapeButton(hayir)
        k.exec()
        return k.clickedButton() is evet

    def _hesap_kutulari(self) -> None:
        """Kutuları panelin yetkili değerine çek (sinyal üretmeden)."""
        acik = A.hesap_oturumlari_oku()
        for sag, k in [*self.k_hesap.items(), ("*", self.k_hesap_hepsi)]:
            k.blockSignals(True)
            k.setChecked(set(A.HESAP_SAGLAYICILARI) <= acik if sag == "*" else sag in acik)
            k.blockSignals(False)

    def hesap_hepsi_sec(self, acik: bool) -> bool:
        """Ana anahtar: açarken TEK onay diyaloğu (Hayır → geri döner); kapatmak sormadan. → kaydedildi mi."""
        if acik and not self.hesap_onay_sor("hepsi"):
            self._hesap_kutulari()
            self.l_hesap.setText("")
            return False
        try:
            A.hesap_oturumlari_hepsi_yaz(acik)
        except Exception as e:  # noqa: BLE001
            self._hesap_kutulari()
            self.l_hesap.setText(_(T.Y_HESAP_HATA).format(hata=e))
            return False
        self._hesap_kutulari()
        self.l_hesap.setText(_(T.Y_KAYDEDILDI))
        return True

    def hesap_oturumu_sec(self, saglayici: str, acik: bool) -> bool:
        """Onay kutusu: açarken onay diyaloğu (Hayır → kutu geri döner); kapatmak sormadan. → kaydedildi mi."""
        if acik and not self.hesap_onay_sor(saglayici):
            self._hesap_kutulari()
            self.l_hesap.setText("")
            return False
        try:
            A.hesap_oturumu_yaz(saglayici, acik)
        except Exception as e:  # noqa: BLE001
            self._hesap_kutulari()
            self.l_hesap.setText(_(T.Y_HESAP_HATA).format(hata=e))
            return False
        self._hesap_kutulari()
        self.l_hesap.setText(_(T.Y_KAYDEDILDI))
        return True

    def _liste_kilidi(self, tur: str) -> bool:
        """An unverified list (wallet unreadable, the user said No; liste_koruma) is shown READ-ONLY with a label and
        cannot be saved: saving would sign the unapproved file content (review EK-2). → locked."""
        from ... import liste_koruma
        kilitli = liste_koruma.dogrulanmamis(tur)
        alan, etiket, dugme = ((self.yasak, self.l_yasak, getattr(self, "b_yasak_kaydet", None)) if tur == "yasak" else
                               (self.seviye, self.l_seviye, getattr(self, "b_seviye_kaydet", None)))
        alan.setReadOnly(kilitli)
        if dugme is not None:
            dugme.setEnabled(not kilitli)
        if kilitli:
            # the same display as the panel's question (review INC4 O3): every applied entry numbered, invisible /
            # look-alike characters visible; the fixed label (entry count) is outside the content field
            g = liste_koruma.dogrulanmamis_gosterim(tur, liste_koruma.AKTIF.metin(tur) if liste_koruma.AKTIF else None)
            b = g.bolumler[0]
            alan.setPlainText("\n".join(b.satirlar))
            etiket.setTextFormat(Qt.TextFormat.PlainText)
            etiket.setText(_(Y_DOGRULANMADI) + " " + b.etiket)
        self._liste_kilitli[tur] = kilitli
        return kilitli

    def liste_durumu_tazele(self):
        """Panel poll: the lock state of yasak/seviye changed (wallet read → verified): reload the page."""
        from ... import liste_koruma
        for tur, yukle in (("yasak", self.yasak_yukle), ("seviye", self.seviye_yukle)):
            if liste_koruma.dogrulanmamis(tur) != self._liste_kilitli.get(tur, False):
                yukle()

    def yasak_yukle(self):
        self.yasak.setPlainText(A.yasak_metni())
        self.l_yasak.setText("")
        self._liste_kilidi("yasak")

    def yasak_kaydet(self) -> bool:
        if self._liste_kilidi("yasak"):
            return False
        metin = self.yasak.toPlainText()
        h = A.yasak_dogrula(metin)
        if h:
            self.l_yasak.setText(_(T.Y_DESEN_HATA).format(no=h[0], hata=h[1]))
            return False
        try:
            A.yasak_kaydet(metin)
        except OSError as e:  # disk dolu / salt okunur: slottan fırlamasın (panel çökmesin)
            self.l_yasak.setText(_(T.Y_KAYIT_HATA).format(hata=e))
            return False
        self.l_yasak.setText(_(T.Y_KAYDEDILDI))
        return True

    def seviye_yukle(self):
        self.seviye.setPlainText(A.seviye_metni())
        self.l_seviye.setText("")
        self._liste_kilidi("seviye")

    def seviye_kaydet(self) -> bool:
        if self._liste_kilidi("seviye"):
            return False
        metin = self.seviye.toPlainText()
        h = A.seviye_dogrula(metin)
        if h:
            self.l_seviye.setText(_(T.Y_SEVIYE_HATA).format(no=h[0], hata=h[1]))
            return False
        try:
            A.seviye_kaydet(metin)
        except OSError as e:  # disk dolu / salt okunur: slottan fırlamasın (panel çökmesin)
            self.l_seviye.setText(_(T.Y_KAYIT_HATA).format(hata=e))
            return False
        self.l_seviye.setText(_(T.Y_KAYDEDILDI))
        return True

    def tus(self) -> str:
        s = self.k_tus.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        return s or VARSAYILAN_TUS

    def cakisma_goster(self) -> list:
        tus = self.tus()
        c = self.cakisma_f(tus)
        if c:
            b, e, aciklama = c[0]
            self.l_kisayol.setText(_(T.Y_KISAYOL_CAKISMA).format(tus=tus, eylem=aciklama, bilesen=b))
        else:
            self.l_kisayol.setText(_(T.Y_KISAYOL_BOS).format(tus=tus))
        return c

    def _kisayol_kaydet(self, *_a):
        d = A.panel_oku()
        d["kisayol_acik"], d["kisayol"] = self.k_acik.isChecked(), self.tus()
        try:
            A.panel_yaz(d)
        except OSError as e:  # disk dolu / salt okunur: slottan fırlamasın (panel çökmesin)
            self.l_kisayol.setText(_(T.Y_KAYIT_HATA).format(hata=e))
            return
        self.cakisma_goster()
        self.kisayol_degisti.emit(d["kisayol_acik"], d["kisayol"])

    def kisayol_durumu(self, metin: str):
        self.l_kisayol.setText(metin)
