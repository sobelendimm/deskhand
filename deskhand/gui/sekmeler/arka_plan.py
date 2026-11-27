"""Arka plan ekranı sekmesi."""
from __future__ import annotations

import atexit
import os
import time
import zlib

from PyQt6.QtCore import (Qt, QTimer,
                          pyqtSignal)
from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QPushButton, QSizePolicy, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

from ...i18n import N_, _
from .. import metinler as T
from ..dil import Metinler
from ..onizleme import MaskeHatasi, Onizleme, OnizlemePenceresi, maskeli_goruntu, pil_qimage
from ..ortak import (IZLEME_MS, MASA_LISTE_MS, Isci, _devral_temizle, _DEVRAL_ATEXIT, soluk_etiket)

# Kontrol kullanıcıdayken kare aralığı (ölçülen kare maliyeti ≈16 ms; 100–150 ms hedef, UX-D O3) ve girdiden sonraki
# tek kare gecikmesi. İzlemede aralık IZLEME_MS kalır; değişmeyen kare yeniden çizilmez (ekran-fark imzası).
KONTROL_MS = 120
GIRDI_KARE_MS = 30

# Arka plan sekmesinin kendi metinleri (UX-D; gui/metinler.py başka görevin)
K_AL = N_("Kontrolü al")
K_GERI = N_("Geri ver")
K_AL_IPUCU = N_("Fare ve klavyeniz önizleme üzerinden arka plan masaüstüne gider; bu sırada Claude bekler. "
                "DUR açıkken hiçbir girdi gönderilmez.")
K_NOT = N_("Önizlemeye tıklayıp yazabilirsiniz. Bitince Geri ver'e basın.")
K_AL_HATA = N_("Kontrol alınamadı: geçici dosya yazılamadı (disk dolu olabilir). Biraz sonra yeniden deneyin.")
K_BANT = N_("Kontrol sizde — Claude bekliyor")
K_BANT_DUR = N_("Kontrol sizde — DUR açık: girdileriniz gönderilmiyor")
K_BUYUT = N_("Büyüt")
K_BUYUT_IPUCU = N_("Önizlemeyi ayrı, büyük bir pencerede açar. Gizli tutulan pencereler orada da karartılır.")
K_BUYUK_BASLIK = N_("Arka plan masaüstü — büyük görünüm")
K_GOREV_DURDUR = N_("Görevi durdur")
K_GOREV_DURDUR_IPUCU = N_("Yakında: Claude'un bu masaüstündeki işini durdurur.")
K_DURAKLAT = N_("Duraklat / Salt okunur")
K_DURAKLAT_IPUCU = N_("Yakında: Claude'u duraklatır ya da masaüstünü yalnız izlenir yapar.")
K_HATA_ULASILAMADI = N_("Önizleme alınamadı: arka plan masaüstüne ulaşılamıyor. Masaüstü kapanmış olabilir; "
                        "Durdur'a, sonra Başlat'a basın.")
K_HATA_TEKRAR = N_("bir sonraki karede yeniden denenir")
K_AYRINTI = N_("Ayrıntı")
K_AYRINTI_METIN = N_("Teknik ayrıntı (destek için): {tur}")


# =========================================================================== Arka plan ekranı

def _masaustu_modulu():
    try:
        from ... import masaustu
        return masaustu, None
    except Exception as e:  # noqa: BLE001 - başka ajan yazıyor / bağımlılık eksik
        return None, e


def _varsayilan_arka():
    from ...arka_uc import sec
    return sec(arka_bayragi=True)


class ArkaPlanSekmesi(QWidget):
    devral_degisti = pyqtSignal(bool)

    def __init__(self, parent=None, arka_f=_varsayilan_arka, masaustu_m=None, devral_yolu_f=None, masalar_f=None,
                 saat=time.time):
        super().__init__(parent)
        from .. import durum as D
        self.arka_f = arka_f
        if masaustu_m is None:
            masaustu_m, self.m_hata = _masaustu_modulu()
        else:
            self.m_hata = None
        self.m = masaustu_m
        self.devral_yolu_f = devral_yolu_f or D.devral_yolu
        # çalışan masaüstlerinin listesi (SALT OKUMA: durum.masa_listesi; masaustu modülünün durum()'u)
        self.masalar_f = masalar_f or (lambda: D.masa_listesi(self.m) if self.m is not None else [])
        self.saat = saat
        self.masalar: list[dict] = []
        self.son_eylemler = D.SonEylemler()
        self.devir_masa: str | None = None  # bir onay devrinin (panel.devral_ac) masaüstü: orada Devral serbest
        self._sinif_onb: dict = {}
        self.sanal: dict | None = None
        self.girdi = None
        self._isci: Isci | None = None
        self._tekerlek_uyarildi = False
        self.mt = Metinler()

        kok = QVBoxLayout(self)
        kok.setContentsMargins(8, 8, 8, 8)  # aralık biriminin katı (tasarım kapısı ARALIK); dikey yer önizlemenin
        kok.setSpacing(8)
        # ---- masaüstü seçici: çalışan bütün arka plan masaüstleri (ad, ne zamandır açık, son etkinlik)
        self.agac = QTreeWidget()
        self.agac.setRootIsDecorated(False)
        self.agac.setUniformRowHeights(True)
        self.agac.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.agac.setColumnCount(3)
        self.mt.fn(lambda: self.agac.setHeaderLabels([_(s) for s in T.A_MASA_SUTUNLAR]))
        self.mt(self.agac.setToolTip, T.A_MASA_IPUCU)
        self.agac.header().setStretchLastSection(True)
        self.agac.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.agac.setMaximumHeight(118)
        self.agac.setVisible(False)  # yalnız ≥2 masaüstünde (masalar_guncelle)
        self.agac.itemSelectionChanged.connect(self._agac_secim)
        kok.addWidget(self.agac)
        self.l_masa_yok = soluk_etiket("")
        self.mt(self.l_masa_yok.setText, T.A_MASA_YOK)
        kok.addWidget(self.l_masa_yok)
        self.l_eylem = QLabel("")
        self.l_eylem.setTextFormat(Qt.TextFormat.PlainText)  # pencere başlığı/etiket HTML olarak yorumlanmasın
        # durum + "ajan şu an" + düğmeler tek satırda: dikey yer önizlemenin (O2); uzun eylem satırı kırpılır, tamamı ipucunda
        self.l_eylem.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        ust = QHBoxLayout()
        self.l_durum = QLabel(_(T.A_KAPALI))
        ust.addWidget(self.l_durum)
        ust.addWidget(self.l_eylem, 1)
        self.b_baslat = QPushButton()
        self.mt(self.b_baslat.setText, T.A_BASLAT)
        self.b_baslat.clicked.connect(self.baslat)
        self.b_durdur = QPushButton()
        self.mt(self.b_durdur.setText, T.A_DURDUR)
        self.b_durdur.clicked.connect(self.durdur)
        self.b_devral = QPushButton()
        self.b_devral.setCheckable(True)
        self.mt.fn(lambda: self.b_devral.setText(_(K_GERI if self.b_devral.isChecked() else K_AL)))
        self.mt(self.b_devral.setToolTip, K_AL_IPUCU)
        self.b_devral.toggled.connect(self.devral)
        self.b_buyut = QPushButton()
        self.mt(self.b_buyut.setText, K_BUYUT)
        self.mt(self.b_buyut.setToolTip, K_BUYUT_IPUCU)
        self.b_buyut.clicked.connect(self.buyut)
        # ana plan yer tutucuları (N1b, C1): yalnız düğme YERİ, işlev yok
        self.b_ajan_durdur = QPushButton()
        self.mt(self.b_ajan_durdur.setText, K_GOREV_DURDUR)
        self.mt(self.b_ajan_durdur.setToolTip, K_GOREV_DURDUR_IPUCU)
        self.b_duraklat = QPushButton()
        self.mt(self.b_duraklat.setText, K_DURAKLAT)
        self.mt(self.b_duraklat.setToolTip, K_DURAKLAT_IPUCU)
        for b in (self.b_ajan_durdur, self.b_duraklat):
            b.setEnabled(False)
        for b in (self.b_baslat, self.b_durdur, self.b_devral, self.b_buyut, self.b_ajan_durdur, self.b_duraklat):
            ust.addWidget(b)
        kok.addLayout(ust)
        # "kontrol sizde" bandı: önizlemenin hemen üstünde, yalnız kontrol kullanıcıdayken
        self.bant = QFrame()
        self.bant.setObjectName("kontrolBandi")
        self.bant.setStyleSheet("QFrame#kontrolBandi { background: palette(highlight); border-radius: 4px; }"
                                "QFrame#kontrolBandi QLabel { color: palette(highlighted-text); font-weight: bold; }")
        bs = QHBoxLayout(self.bant)
        bs.setContentsMargins(8, 4, 4, 4)
        bs.setSpacing(8)
        self.l_bant = QLabel("")
        self.l_bant.setTextFormat(Qt.TextFormat.PlainText)
        bs.addWidget(self.l_bant, 1)
        self.b_bant_geri = QPushButton()
        self.mt(self.b_bant_geri.setText, K_GERI)
        self.b_bant_geri.clicked.connect(lambda: self.b_devral.setChecked(False))
        bs.addWidget(self.b_bant_geri)
        self.bant.setVisible(False)
        kok.addWidget(self.bant)
        self.onizleme = Onizleme(oranli=True)  # tam genişlik, yükseklik en-boy oranından: gri bant yok
        self.onizleme.satirlar.connect(self.gonder)
        kok.addWidget(self.onizleme)
        self.buyuk: OnizlemePenceresi | None = None
        self.hata_satiri = QWidget()
        hs = QHBoxLayout(self.hata_satiri)
        hs.setContentsMargins(0, 0, 0, 0)
        self.hata_satiri.setVisible(False)
        self.l_hata_ayrinti = soluk_etiket("")
        self.l_hata_ayrinti.setVisible(False)
        self.b_ayrinti = QPushButton()
        self.b_ayrinti.setCheckable(True)
        self.b_ayrinti.setFlat(True)
        self.mt(self.b_ayrinti.setText, K_AYRINTI)
        self.b_ayrinti.setVisible(False)
        self.b_ayrinti.toggled.connect(lambda ac: self.l_hata_ayrinti.setVisible(ac and self.b_ayrinti.isVisible()))
        hs.addWidget(self.b_ayrinti)
        hs.addWidget(self.l_hata_ayrinti, 1)
        kok.addWidget(self.hata_satiri)
        self.l_not = soluk_etiket("")
        self.mt.fn(lambda: self._not(_(K_NOT if self.b_devral.isChecked() else T.A_DEVRAL_IPUCU)))
        kok.addWidget(self.l_not)
        kok.addStretch(1)
        self._son_imza = None
        self._girdi_karesi_bekliyor = False

        self.zaman = QTimer(self)
        self.zaman.setInterval(IZLEME_MS)
        self.zaman.timeout.connect(self.kare)
        self.liste_zaman = QTimer(self)  # masaüstü listesi + "ajan şu an" satırı (yalnız görünürken)
        self.liste_zaman.setInterval(MASA_LISTE_MS)
        self.liste_zaman.timeout.connect(self.masalar_yenile)
        self.sanal_guncelle(None)
        self.masalar_guncelle([])

    # -------- masaüstü seçici (çoklu görünmez masaüstü; yalnız izleme)
    @staticmethod
    def _secili_masa() -> str:
        from ... import masalar
        return masalar.secili()

    IZLEME_KULLANIM_SN = 60

    def masalar_yenile(self) -> None:
        """Çalışan masaüstlerini yeniden oku (salt okuma) ve listeyi güncelle."""
        try:
            liste = self.masalar_f()
        except Exception:  # noqa: BLE001 - okunamadı: eski liste kalır
            return
        self.masalar_guncelle(liste)
        self._izleme_kullanimi()

    def _izleme_kullanimi(self) -> None:
        """0.9.1: kullanıcı önizlemeyi izlerken masaüstü 'boşta' sayılıp kendiliğinden kapanmasın (dakikada bir işaret)."""
        import time
        simdi = time.monotonic()
        if simdi - getattr(self, "_son_isaret", 0.0) < self.IZLEME_KULLANIM_SN or not self.isVisible():
            return
        self._son_isaret = simdi
        try:
            from ... import masaustu
            masaustu.kullanim_isaretle(self._secili_masa() or None, zorla=True)
        except Exception:  # noqa: BLE001 - işaretlenemedi: en kötü masaüstü boşta sayılır
            pass

    def masalar_guncelle(self, liste: list[dict]) -> None:
        self.masalar = list(liste or [])
        secili = self._secili_masa()
        adlar = [m["ad"] for m in self.masalar]
        if secili not in adlar and secili != "" and secili != self.devir_masa:
            self.masa_sec("")  # seçili adlı masaüstü kapandı: varsayılana dön
            secili = ""
        self.agac.blockSignals(True)
        try:
            self.agac.clear()
            for m in self.masalar:
                it = QTreeWidgetItem(["", "", ""])
                it.setData(0, Qt.ItemDataRole.UserRole, m["ad"])
                self.agac.addTopLevelItem(it)
                if m["ad"] == secili:
                    it.setSelected(True)
                    self.agac.setCurrentItem(it)
        finally:
            self.agac.blockSignals(False)
        self.l_masa_yok.setVisible(not self.masalar)
        self.agac.setVisible(len(self.masalar) >= 2)  # tek masaüstünde seçilecek bir şey yok: yer önizlemenin
        self._masa_metinleri()
        # seçili masaüstünün durumu listeden (adlı masaüstünün sanal.json değişimini izleyici görmez)
        g = next((m for m in self.masalar if m["ad"] == secili), None)
        s = g["durum"] if g else None
        if (s is None) != (self.sanal is None) or (s and self.sanal and s.get("ekran") != self.sanal.get("ekran")):  # noqa: SIM102
            if self._isci is None:
                self.sanal_guncelle(s)

    def _masa_metinleri(self) -> None:
        """Liste satırları + "ajan şu an ne yapıyor" satırı (süreler şimdiye göre)."""
        from .. import durum as D
        simdi = self.saat()
        for i in range(self.agac.topLevelItemCount()):
            it = self.agac.topLevelItem(i)
            ad = it.data(0, Qt.ItemDataRole.UserRole)
            m = next((x for x in self.masalar if x["ad"] == ad), None)
            if m is None:
                continue
            it.setText(0, f"{ad or _(T.A_MASA_VARSAYILAN)}  ({m['ekran']})" if m["ekran"] else (ad or _(T.A_MASA_VARSAYILAN)))
            it.setText(1, D.sure_metni(simdi - m["baslangic"]) if m.get("baslangic") else _(T.A_SON_YOK))
            e = self.son_eylemler.son(m["ekran"], m.get("baslangic"))
            it.setText(2, _(T.A_ONCE).format(sure=D.sure_metni(simdi - e["zaman"])) if e else _(T.A_SON_YOK))
        secili = self._secili_masa()
        g = next((m for m in self.masalar if m["ad"] == secili), None)
        if g is None:
            self.l_eylem.setText("")
            self.l_eylem.setVisible(False)
        else:
            metin = D.eylem_satiri(self.son_eylemler.son(g["ekran"], g.get("baslangic")), simdi)
            self.l_eylem.setText(metin)
            self.l_eylem.setToolTip(metin)
            self.l_eylem.setVisible(True)

    def etkinlik_ekle(self, satirlar: list[dict]) -> None:
        """Günlükten gelen yeni satırlar: masaüstü başına son eylem."""
        self.son_eylemler.ekle(satirlar, self.saat())
        if self.isVisible():
            self._masa_metinleri()

    def _agac_secim(self) -> None:
        sec = self.agac.selectedItems()
        if sec:
            self.masa_sec(sec[0].data(0, Qt.ItemDataRole.UserRole) or "")

    def masa_sec(self, masa: str) -> None:
        """Sekmeyi (önizleme, Devral, başlat/durdur) `masa` görünmez masaüstüne çevir ("" = varsayılan). Panel sürecinin
        bağlamıdır (masalar.secili ← DESKHAND_MASAUSTU); açık Devral önce kapanır (bayrak eski masaüstünün dosyasından
        silinsin). Önizleme yalnız GÖSTERİR: adlı masaüstüne Devral yalnız onay devrinde (devir_masa) açılır."""
        from ... import masalar
        try:
            masa = masalar.dogrula(masa or "", ayrilmis_serbest=True)
        except Exception:  # noqa: BLE001 - geçersiz ad: varsayılan
            masa = ""
        if masalar.secili() == masa:
            self._agac_esle(masa)
            return
        if self.b_devral.isChecked():
            self.b_devral.setChecked(False)
        if masa:
            os.environ[masalar.ORTAM] = masa
        else:
            os.environ.pop(masalar.ORTAM, None)
        self._sinif_onb.clear()
        self._son_imza = None
        self.onizleme.goster(None)
        g = next((m for m in self.masalar if m["ad"] == masa), None)
        if g is not None:
            s = g["durum"]
        else:
            try:
                s = self.m.durum() if self.m is not None else None
            except Exception:  # noqa: BLE001
                s = None
        self.sanal_guncelle(s)
        self._agac_esle(masa)
        self._masa_metinleri()

    def _agac_esle(self, masa: str) -> None:
        self.agac.blockSignals(True)
        try:
            for i in range(self.agac.topLevelItemCount()):
                it = self.agac.topLevelItem(i)
                bu = (it.data(0, Qt.ItemDataRole.UserRole) or "") == masa
                it.setSelected(bu)
                if bu:
                    self.agac.setCurrentItem(it)
        finally:
            self.agac.blockSignals(False)

    def _devral_serbest(self) -> bool:
        """Devral (girdi aktarımı) yalnız varsayılan masaüstünde ya da bir onay devrinin masaüstünde: ajanın kendi
        adlı masaüstünü listeden seçmek yalnız İZLEMEdir (yeni girdi yolu yok)."""
        masa = self._secili_masa()
        return masa == "" or masa == self.devir_masa

    # -------- durum
    def sanal_guncelle(self, s: dict | None) -> None:
        self.sanal = s
        if self.m is None:
            self.l_durum.setText(_(T.A_YOK).format(hata=self.m_hata))
        elif s is None:
            self.l_durum.setText(_(T.A_KAPALI))
        else:
            g, y = (s.get("boyut") or [0, 0])[:2]
            self.l_durum.setText(_(T.A_ACIK).format(ekran=s.get("ekran", "?"), g=g, y=y))
        acik = s is not None
        baslatabilir = self.m is not None and hasattr(self.m, "masaustu_baslat")
        self.b_baslat.setVisible(not acik)
        self.b_baslat.setEnabled(baslatabilir and self._isci is None)
        if not baslatabilir:
            self.b_baslat.setToolTip(_(T.A_YOK).format(hata=self.m_hata or _(T.A_BASLAT_YOK)))
        self.b_durdur.setVisible(acik)
        self.b_durdur.setEnabled(self.m is not None and hasattr(self.m, "masaustu_durdur") and self._isci is None)
        serbest = self._devral_serbest()
        self.b_devral.setEnabled(acik and (serbest or self.b_devral.isChecked()))
        if not self.b_devral.isChecked():
            self._not(_(T.A_DEVRAL_IPUCU if serbest else T.A_DEVRAL_ADLI))
        if not acik:
            if self.b_devral.isChecked():
                self.b_devral.setChecked(False)
            self._son_imza = None
            self.onizleme.goster(None)
            self.onizleme.bos_metin = _(T.A_KAPALI)
            _hata_ayrinti(self, None)
        self._zamanlayici()

    def _calis(self, fn, metin: str):
        if self._isci is not None:
            return
        self.l_durum.setText(metin)
        self._isci = Isci(fn, self)
        self._isci.bitti.connect(self._bitti)
        self.b_baslat.setEnabled(False)
        self.b_durdur.setEnabled(False)
        self._isci.start()

    def _bitti(self, _sonuc, hata):
        self._isci = None
        s = None
        try:
            s = self.m.durum() if self.m is not None else None
        except Exception:  # noqa: BLE001
            s = None
        self.sanal_guncelle(s)
        self.masalar_yenile()
        if hata is not None:
            self.l_durum.setText(f"{self.l_durum.text()} — {getattr(hata, 'mesaj', None) or hata}")

    def baslat(self):
        if self.m is not None and hasattr(self.m, "masaustu_baslat"):
            self._calis(self.m.masaustu_baslat, _(T.A_BASLATILIYOR))

    def durdur(self):
        if self.m is not None and hasattr(self.m, "masaustu_durdur"):
            self.b_devral.setChecked(False)
            self._calis(self.m.masaustu_durdur, _(T.A_DURDURULUYOR))

    # -------- önizleme (yalnız görünürken)
    def _gorunur(self) -> bool:
        w = self.window()
        return self.isVisible() and not (w is not None and w.isMinimized())

    def _zamanlayici(self):
        aralik = KONTROL_MS if self.b_devral.isChecked() else IZLEME_MS
        if self.zaman.interval() != aralik:
            self.zaman.setInterval(aralik)
        if self.sanal is not None and self._gorunur():
            if not self.zaman.isActive():
                self.zaman.start()
                self.kare()
        else:
            self.zaman.stop()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self.masalar_yenile()
        if not self.liste_zaman.isActive():
            self.liste_zaman.start()
        self._zamanlayici()

    def hideEvent(self, e):  # noqa: N802
        super().hideEvent(e)
        self.zaman.stop()
        self.liste_zaman.stop()

    def kare(self):
        """Bir kare: HER karede yasak pencere maskesi (maskeli_goruntu: liste karenin önü + arkası; api.goruntu_al
        kuralı) uygulanır; ekran değişmediyse (maskeli karenin imzası aynı) yeniden çizim yapılmaz. Büyük görünüm
        açıksa aynı maskeli kare orada da gösterilir. Not: test_guv_maske bunu yalın bir nesneyle çağırır; yeni
        öznitelikler getattr ile okunur."""
        if self.sanal is None or not self._gorunur():
            self.zaman.stop()
            return
        try:
            au = self.arka_f()
            if au is None:
                raise LookupError("arka uç yok")
            im = maskeli_goruntu(au, self._sinif_onb)
        except MaskeHatasi as e:  # denetlenemedi: kare HİÇ gösterilmez (güvenli taraf)
            _onizleme_hatasi(self, _(T.A_MASKE_HATA).format(hata=_(K_HATA_TEKRAR)), e)
            return
        except Exception as e:  # noqa: BLE001 - masaüstü kapandı / X hatası: ham ileti kullanıcıya çıkmaz
            _onizleme_hatasi(self, _(K_HATA_ULASILAMADI), e)
            return
        _bant_guncelle(self)
        buyuk = getattr(self, "buyuk", None)
        buyuk_acik = buyuk is not None and buyuk.isVisible()
        hedef = self.onizleme.hedef_boyut() if self.onizleme.kaynak.width() else None
        if buyuk_acik and hedef is not None:
            hb = buyuk.onizleme.hedef_boyut()
            if hb.width() > hedef.width():
                hedef = hb
        imza = (zlib.crc32(im.tobytes()), im.size, (hedef.width(), hedef.height()) if hedef is not None else None, buyuk_acik)
        if imza == getattr(self, "_son_imza", None):
            return  # ekran değişmedi: çizim yok (maske bu karede de denetlendi)
        self._son_imza = imza
        q, kaynak = pil_qimage(im, hedef)
        self.onizleme.goster(q, kaynak)
        if buyuk_acik:
            buyuk.onizleme.goster(q, kaynak)
        _hata_ayrinti(self, None)
        if self.l_eylem.isVisible():
            self._masa_metinleri()

    def buyut(self) -> None:
        """Önizlemeyi ayrı büyük pencerede aç (kare sekmeden gelir: aynı maske, aynı DUR denetimli girdi yolu)."""
        if self.buyuk is None:
            self.buyuk = OnizlemePenceresi(_(K_BUYUK_BASLIK), self)
            self.buyuk.onizleme.satirlar.connect(self.gonder)
        self.buyuk.onizleme.devral = self.onizleme.devral
        self.buyuk.onizleme.bos_metin = self.onizleme.bos_metin
        self.buyuk.show()
        self.buyuk.raise_()
        self._son_imza = None  # büyük görünüm için ilk kare hemen çizilsin
        self.kare()

    def _girdi_karesi(self) -> None:
        self._girdi_karesi_bekliyor = False
        self.kare()

    # -------- Devral
    def devral(self, acik: bool):
        yol = self.devral_yolu_f()
        if acik:
            from ..durum import devral_icerik
            gecici = f"{yol}.{os.getpid()}"
            try:  # /run/user dolu (ENOSPC) / yazılamıyor: slottan fırlayan istisna paneli öldürmesin; Devral açılmaz
                os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
                with open(gecici, "w") as f:
                    f.write(devral_icerik())  # "panel <pid> <başlangıç>": panel çökerse ajan bayat dosyada beklemez
                os.replace(gecici, yol)
            except OSError as e:
                try:
                    os.remove(gecici)
                except OSError:
                    pass
                from ...gunluk import gunluk
                gunluk(f"Devral açılamadı: {e}")
                self.b_devral.blockSignals(True)
                self.b_devral.setChecked(False)
                self.b_devral.blockSignals(False)
                self.b_devral.setText(_(K_AL))
                self._not(_(K_AL_HATA))
                return
            if yol not in _DEVRAL_ATEXIT:
                _DEVRAL_ATEXIT.add(yol)
                atexit.register(_devral_temizle, yol)
            self.b_devral.setText(_(K_GERI))
            self._not(_(K_NOT))
            self.onizleme.devral = True
            self.onizleme.setFocus()
        else:
            self._girdi_kapat()
            try:
                os.remove(yol)
            except FileNotFoundError:
                pass
            self.b_devral.setText(_(K_AL))
            serbest = self._devral_serbest()
            self._not(_(T.A_DEVRAL_IPUCU if serbest else T.A_DEVRAL_ADLI))
            self.b_devral.setEnabled(self.sanal is not None and serbest)
            self.onizleme.devral = False
        if self.buyuk is not None:
            self.buyuk.onizleme.devral = self.onizleme.devral
            self.buyuk.onizleme.update()
        _bant_guncelle(self)
        self.onizleme.update()
        self._zamanlayici()
        self.devral_degisti.emit(acik)

    def _not(self, metin: str) -> None:
        """Alt not satırı: olağan ipucu (düğme ipucunda ve bantta da var) gizli kalır, yer önizlemenin; uyarı/hata ve
        "yalnız izleme" notu görünür."""
        self.l_not.setText(metin)
        self.l_not.setVisible(metin not in (_(T.A_DEVRAL_IPUCU), _(K_NOT)))

    def tazele(self) -> None:
        self.mt.tazele()
        if self._isci is None:  # başlatılıyor/durduruluyor metni iş bitince zaten yenilenir
            self.sanal_guncelle(self.sanal)
        self.onizleme.update()

    def _girdi_kapat(self):
        g, self.girdi = self.girdi, None
        if g is not None:
            try:
                g.kapat()
            except Exception:  # noqa: BLE001
                pass

    def gonder(self, satirlar: list[str]):
        """Devral girdisi → sanal arka ucun Girdi'si. denetle=None (insan), DUR her satırda geçerli."""
        if not self.onizleme.devral:
            return
        from ...hata import Dur, dur_denetle
        try:
            dur = None
            try:
                dur_denetle()
            except Dur as e:
                # DUR açıkken yalnız BIRAKMA satırları (buttonup/keyup) geçer: önceden basılan düğme basılı kalmasın
                birak = [s for s in satirlar if s.split(" ", 1)[0] in ("buttonup", "keyup")]
                if not birak or self.girdi is None or not hasattr(self.girdi, "insan_ham"):
                    raise
                satirlar, dur = birak, e
            if self.girdi is None:
                self.girdi = self.arka_f().girdi(etiket="panel devral", denetle=None)
            gonder = getattr(self.girdi, "insan_ham", None) or self.girdi.ham
            for s in satirlar:
                try:
                    gonder(s)
                except Dur as e:
                    if e.kod == 12 and s.split()[0] in ("wheel", "hwheel"):
                        if not self._tekerlek_uyarildi:
                            self._tekerlek_uyarildi = True
                            self._not(_(T.A_TEKERLEK_YOK))
                        continue
                    raise
            if dur is not None:
                raise dur
            if not self._girdi_karesi_bekliyor:  # girdinin etkisi hemen görünsün (zamanlayıcıyı beklemeden)
                self._girdi_karesi_bekliyor = True
                QTimer.singleShot(GIRDI_KARE_MS, self._girdi_karesi)
        except Dur as e:
            self._not(_(T.A_GIRDI_HATA).format(hata=e.mesaj))
            _bant_guncelle(self)
            if e.kod != 13:
                self._girdi_kapat()
        except Exception as e:  # noqa: BLE001
            self._not(_(T.A_GIRDI_HATA).format(hata=e))
            self._girdi_kapat()


# -------- kare yardımcıları (modül düzeyi: ArkaPlanSekmesi.kare yalın bir nesneyle de çağrılabilir; test_guv_maske)

def _bant_guncelle(o) -> None:
    """"Kontrol sizde" bandı: yalnız kontrol kullanıcıdayken; DUR açıkken DUR'u söyler (girdi gitmez)."""
    bant, etiket, dugme = getattr(o, "bant", None), getattr(o, "l_bant", None), getattr(o, "b_devral", None)
    if bant is None or etiket is None or dugme is None:
        return
    if not dugme.isChecked():
        bant.setVisible(False)
        return
    try:
        from ... import guvenlik
        dur = guvenlik.dur_acik()
    except Exception:  # noqa: BLE001 - okunamadı: DUR varsay (güvenli taraf: girdi zaten her satırda denetlenir)
        dur = True
    etiket.setText(_(K_BANT_DUR if dur else K_BANT))
    bant.setVisible(True)


def _hata_ayrinti(o, e) -> None:
    """Katlı teknik ayrıntı: yalnız hata TÜRÜ (ham ileti kullanıcıya çıkmaz). e=None → gizle."""
    et, b = getattr(o, "l_hata_ayrinti", None), getattr(o, "b_ayrinti", None)
    if et is None or b is None:
        return
    satir = getattr(o, "hata_satiri", None)
    if e is None:
        b.setVisible(False)
        et.setVisible(False)
        if satir is not None:
            satir.setVisible(False)
        return
    neden = getattr(e, "__cause__", None) or e
    et.setText(_(K_AYRINTI_METIN).format(tur=type(neden).__name__))
    b.setVisible(True)
    et.setVisible(b.isChecked())
    if satir is not None:
        satir.setVisible(True)


def _onizleme_hatasi(o, metin: str, e: Exception) -> None:
    """Kare gösterilmez; insan dilinde ne oldu + ne yapmalı; ham istisna metni gösterilmez."""
    o._son_imza = None
    o.onizleme.bos_metin = metin
    o.onizleme.goster(None)
    buyuk = getattr(o, "buyuk", None)
    if buyuk is not None:
        buyuk.onizleme.bos_metin = metin
        buyuk.onizleme.goster(None)
    # etkinlik günlüğüne YAZILMAZ: günlük ajan eylemlerinindir (üst şerit onu "çalışıyor" diye okur)
    _hata_ayrinti(o, e)
