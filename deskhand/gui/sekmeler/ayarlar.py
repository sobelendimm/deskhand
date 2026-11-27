"""Ayarlar sekmesi.

Tek kaydetme modeli (KDE Sistem Ayarları kalıbı, UX-A): alanlar yalnız ekrandaki değeri değiştirir; alt çubuktaki
Uygula hepsini kaydeder, Sıfırla kayıtlı değerlere döndürür, "Kaydedilmemiş değişiklikler var" göstergesi
bekleyen değişikliği gösterir. Güvenlik ayarları (yasaklar, seviyeler, onay soruları, hesap oturumları) Uygula'nın
İÇİNDE mevcut yoldan yazılır: liste_koruma'nın imzalı panel kaydı, hesap açarken onay diyaloğu. Sekmeden ya da
pencereden çıkarken bekleyen değişiklik varsa Uygula / Değişiklikleri at / İptal sorulur.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                             QGroupBox, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                             QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout,
                             QWidget)

from ... import ayarlar as AY
from ... import i18n
from ...i18n import N_, _
from .. import ayar as A
from .. import metinler as T
from ..dil import Metinler, dil_secenekleri
from ..kisayol import VARSAYILAN_TUS, cakismalar
from .gizli import G_BASLIK as Y_GIZLI
from .gizli import ArkaUc, GizliBilgiler
from .simgeler import SimgelerSekmesi

Y_DOGRULANMADI = N_("DOĞRULANMADI — dosyadaki onaylanmamış girişler (salt okunur). Cüzdan okununca panel imzalı kaydı "
                    "geri yükler (imzalı kayıt yoksa girişleri yeniden sorar); o zamana kadar Deskhand durdu (Dur 10).")
Y_DOSYADA_FARKLI = N_("Ayar dosyasında doğrulanmamış değer var ({deger}); uygulanmıyor. Gösterilen, geçerli değerdir.")

KAYDEDILDI_MS = 2000          # "Kaydedildi ✓" görünme süresi
SEVIYE_KOKLER = ("goruntule", "tikla", "tam")  # dosya biçimi sözcükleri (çevrilmez)
_BOSLUK, _KENAR = 8, 12       # aralık birimi (tokens.json aralık değerlerinin EBOB'u 2) katları
_HEDEF = 28                   # tıklama hedefi alt sınırı (WCAG 2.5.8: 24) üstü


def _duzen(lay, kenar: int = _KENAR, bosluk: int = _BOSLUK):
    lay.setContentsMargins(kenar, kenar, kenar, kenar)
    if isinstance(lay, QFormLayout):
        lay.setHorizontalSpacing(bosluk * 2)
        lay.setVerticalSpacing(bosluk)
    else:
        lay.setSpacing(bosluk)
    return lay


def desen_adi(desen: str) -> str:
    """Kural deseninin kullanıcıya gösterilecek adı: düz (kaçışlı) bir addan üretildiyse ad, değilse desenin kendisi."""
    d = desen.strip()
    ic = d[1:] if d.startswith("^") else d
    ic = ic[:-1] if ic.endswith("$") and not ic.endswith("\\$") else ic
    duz = re.sub(r"\\(.)", r"\1", ic)
    return duz if re.escape(duz) == ic else d


def ad_deseni(sinif: str, baslik: str) -> str:
    """Açık pencereden seçilen uygulama → kural deseni (sınıf varsa sınıf, yoksa tam başlık; özel karakterler kaçışlı)."""
    return re.escape(sinif) if sinif else "^" + re.escape(baslik) + "$"


def _kural_satirlari(metin: str, seviye: bool) -> list[tuple[int, str, str]]:
    """Metindeki kural satırları → [(satır no 0-tabanlı, desen, seviye kökü | "")]; yorum/boş satır atlanır."""
    from ...guvenlik import SEVIYELER
    cik = []
    for i, satir in enumerate(metin.splitlines()):
        s = satir.strip()
        if not s or s.startswith("#"):
            continue
        if not seviye:
            cik.append((i, s, ""))
            continue
        desen, ayrac, sev = s.rpartition("=")
        kok = SEVIYE_KOKLER[SEVIYELER[sev.strip().lower()]] if ayrac and sev.strip().lower() in SEVIYELER else ""
        cik.append((i, desen.strip() if ayrac else s, kok))
    return cik


def acik_pencereler() -> list[tuple[str, str]]:
    """Açık pencereler (var olan pencere listeleme API'si) → [(gösterilecek ad, desen)], tekrarsız; yasak pencere yok."""
    from ... import api
    cik, gorulen = [], set()
    for p in api.pencereler():
        if p.get("forbidden"):
            continue
        sinif, baslik = (p.get("class") or "").strip(), (p.get("title") or "").strip()
        if not (sinif or baslik):
            continue
        desen = ad_deseni(sinif, baslik)
        if desen in gorulen:
            continue
        gorulen.add(desen)
        ad = sinif.rsplit(".", 1)[-1] if sinif else baslik
        cik.append((f"{ad} — {baslik}" if baslik and baslik != ad else ad, desen))
    return sorted(cik, key=lambda x: x[0].lower())


class _Ileti(QWidget):
    """Bölüm iletisi (hata/uyarı), iki katman (UX-F O5): üstte sade cümle + ne yapılacak; ham ayrıntı (istisna
    metni) yalnız katlı "Ayrıntı" altında. Boşken yer kaplamaz. QLabel gibi text()/setText() verir."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(_BOSLUK // 2)
        sat = QHBoxLayout()
        sat.setSpacing(_BOSLUK)
        self.l = QLabel("")
        self.l.setWordWrap(True)
        sat.addWidget(self.l, 1)
        self.b_ayrinti = QToolButton()
        self.b_ayrinti.setCheckable(True)
        self.b_ayrinti.setMinimumHeight(_HEDEF)
        self.b_ayrinti.setText(_(T.D_AYRINTI_DUGME))
        self.b_ayrinti.toggled.connect(lambda acik: self.l_ayrinti.setVisible(acik and bool(self._ayrinti)))
        self.b_ayrinti.setVisible(False)
        sat.addWidget(self.b_ayrinti, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(sat)
        self.l_ayrinti = QLabel("")
        self.l_ayrinti.setWordWrap(True)
        self.l_ayrinti.setTextFormat(Qt.TextFormat.PlainText)
        self.l_ayrinti.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.l_ayrinti.setVisible(False)
        lay.addWidget(self.l_ayrinti)
        self._ayrinti = ""
        self.setVisible(False)

    def setText(self, metin: str, ayrinti: str = "") -> None:  # noqa: N802
        self.l.setText(metin)
        self._ayrinti = ayrinti if metin else ""
        self.l_ayrinti.setText(self._ayrinti)
        self.b_ayrinti.setText(_(T.D_AYRINTI_DUGME))
        self.b_ayrinti.setChecked(False)
        self.b_ayrinti.setVisible(bool(self._ayrinti))
        self.l_ayrinti.setVisible(False)
        self.setVisible(bool(metin))

    def hata(self, ozet: str, e: BaseException) -> None:
        """Sade cümle üstte, ham istisna katlı ayrıntıda."""
        self.setText(ozet, T.hata_ayrinti(e))

    def text(self) -> str:
        return self.l.text()

    def ayrinti_metni(self) -> str:
        return self._ayrinti

    def setTextFormat(self, bicim) -> None:  # noqa: N802
        self.l.setTextFormat(bicim)


class _Aciklama(QWidget):
    """Ayar açıklaması, katlı (UX-F O9): "ⓘ Açıklama" düğmesi (ipucu = metin) tıklanınca metin açılır. Metin normal
    renkte (soluk gri WCAG kontrastını geçmiyordu)."""

    def __init__(self, mt: Metinler, msgid: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(_BOSLUK // 2)
        self.b_bilgi = QToolButton()
        self.b_bilgi.setCheckable(True)
        self.b_bilgi.setMinimumHeight(_HEDEF)
        self.b_bilgi.setAutoRaise(True)
        mt(lambda m: self.b_bilgi.setText("ⓘ " + m), T.Y_ACIKLAMA)
        mt(lambda m: self.b_bilgi.setAccessibleName(m), T.Y_ACIKLAMA)
        lay.addWidget(self.b_bilgi, 0, Qt.AlignmentFlag.AlignLeft)
        self.l_metin = QLabel()
        self.l_metin.setWordWrap(True)
        self.l_metin.setVisible(False)
        lay.addWidget(self.l_metin)
        mt(self._yaz, msgid)
        self.b_bilgi.toggled.connect(self.l_metin.setVisible)

    def _yaz(self, m: str) -> None:
        self.l_metin.setText(m)
        self.b_bilgi.setToolTip(m)

    def text(self) -> str:
        return self.l_metin.text()


class PencereSecDiyalog(QDialog):
    def __init__(self, secenekler: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(_(T.Y_PENCERE_SEC_BASLIK))
        lay = _duzen(QVBoxLayout(self))
        lay.addWidget(QLabel(_(T.Y_PENCERE_SEC)))
        self.liste = QListWidget()
        for ad, desen in secenekler:
            it = QListWidgetItem(ad)
            it.setData(Qt.ItemDataRole.UserRole, desen)
            self.liste.addItem(it)
        self.liste.setCurrentRow(0)
        self.liste.itemDoubleClicked.connect(lambda *_a: self.accept())
        lay.addWidget(self.liste)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(460, 360)

    def secim(self) -> tuple[str, str] | None:
        it = self.liste.currentItem()
        return (it.text(), it.data(Qt.ItemDataRole.UserRole)) if it is not None else None


class AyarlarSekmesi(QWidget):
    kisayol_degisti = pyqtSignal(bool, str)
    dil_degisti = pyqtSignal(str)  # yeni etkin dil kodu (i18n yeniden yüklendikten SONRA)

    def __init__(self, parent=None, karar: A.KararAyarlari | None = None, cakisma_f=cakismalar, pencere_f=None,
                 simge_sor=None, gizli_arka_uc: ArkaUc | None = None):
        super().__init__(parent)
        self._gizli_arka_uc = gizli_arka_uc
        self.aciklamalar: list[_Aciklama] = []
        self._simge_sor = simge_sor
        self.karar = karar if karar is not None else A.KararAyarlari()
        self.cakisma_f = cakisma_f
        self.pencere_f = pencere_f or acik_pencereler
        self._liste_kilitli: dict[str, bool] = {}
        self._kayitli: dict = {}
        self._yukleniyor = 0
        self._durum: tuple = ("", {})       # (tür, biçim değerleri): dil değişince yeniden yazılır
        self._durum_saat = QTimer(self)
        self._durum_saat.setSingleShot(True)
        self._durum_saat.timeout.connect(self._kaydedildi_sil)
        self._ust_sekme = None
        self._ust_onceki = -1
        self._geri_donuyor = False
        self._pencere_suzgec = None
        self.mt = Metinler()
        self._yukleniyor += 1
        # onay kutusunun tıklama alanı (erişilebilirlik ağacındaki boyutu: kutu + metin) ≥ 24 px (WCAG 2.5.8)
        self.setStyleSheet("QCheckBox::indicator { width: 24px; height: 24px; }")

        kok = QVBoxLayout(self)
        kok.setContentsMargins(0, 0, 0, 0)
        kok.setSpacing(_BOSLUK)
        self.bolumler = QTabWidget()
        self.bolumler.setDocumentMode(True)
        yigin = self.bolumler.findChild(QStackedWidget)
        if yigin is not None and yigin.layout() is not None:
            yigin.layout().setContentsMargins(0, 0, 0, 0)  # aralık birimi dışı varsayılan kenar (9) yok
        temel, self._temel = self._sayfa()
        gelismis, self._gelismis = self._sayfa()
        self.bolumler.addTab(temel, "")
        self.bolumler.addTab(gelismis, "")
        self.mt(lambda m: self.bolumler.setTabText(0, m), T.Y_TEMEL)
        self.mt(lambda m: self.bolumler.setTabText(1, m), T.Y_GELISMIS)
        kok.addWidget(self.bolumler, 1)

        self._dil_kur(self._temel)
        self._onay_kur(self._temel)
        self._mesgul_kur(self._temel)
        self._gorev_kur(self._temel)
        self._temel.addStretch(1)
        self._yasak_kur(self._gelismis)
        self._seviye_kur(self._gelismis)
        self._hesap_kur(self._gelismis)
        self._gizli_kur(self._gelismis)
        self._kisayol_kur(self._gelismis)
        self._simge_kur(self._gelismis)
        g = self._grup(T.Y_IZINLER)  # ana planın P4'ü: yer tutucu (işlev yok)
        _duzen(QVBoxLayout(g)).addWidget(self._not_duz(T.Y_IZINLER_YAKINDA))
        self._gelismis.addWidget(g)
        self._gelismis.addStretch(1)

        # ---- alt çubuk: durum + Sıfırla + Uygula
        cubuk = QFrame()
        cubuk.setFrameShape(QFrame.Shape.NoFrame)
        cl = QHBoxLayout(cubuk)
        cl.setContentsMargins(_KENAR, 0, _KENAR, _KENAR)
        cl.setSpacing(_BOSLUK)
        self.l_durum = QLabel("")
        self.l_durum.setWordWrap(True)
        self.l_durum.setTextFormat(Qt.TextFormat.PlainText)
        cl.addWidget(self.l_durum, 1)
        self.b_sifirla = QPushButton()
        self.mt(self.b_sifirla.setText, T.Y_SIFIRLA)
        self.b_sifirla.clicked.connect(self.sifirla)
        self.b_uygula = QPushButton()
        self.mt(self.b_uygula.setText, T.Y_UYGULA)
        self.b_uygula.setDefault(True)
        self.b_uygula.clicked.connect(self.uygula)
        for b in (self.b_sifirla, self.b_uygula):
            b.setMinimumHeight(_HEDEF)
            cl.addWidget(b)
        kok.addWidget(cubuk)

        self.yasak_yukle()
        self.seviye_yukle()
        self.cakisma_goster()
        self._yukleniyor -= 1
        self._kayitli = self._anlik()
        self._degisti()

    # =================================================================== kurulum
    def _sayfa(self) -> tuple[QScrollArea, QVBoxLayout]:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.verticalScrollBar().setMinimumWidth(24)  # tıklama hedefi ≥ 24 px (WCAG 2.5.8)
        govde = QWidget()
        lay = _duzen(QVBoxLayout(govde), bosluk=_BOSLUK * 2)
        sa.setWidget(govde)
        return sa, lay

    def _dil_kur(self, kok):
        g = self._grup(T.Y_DIL)
        gl = _duzen(QFormLayout(g))
        self.c_dil = QComboBox()
        for kod, ad in dil_secenekleri():
            self.c_dil.addItem(ad, kod)
        self.mt.fn(self._dil_adlari)
        self._dil_secili()
        self.c_dil.activated.connect(lambda _i: self._degisti())
        gl.addRow(self._etiket(T.Y_DIL), self.c_dil)
        self.l_dil = _Ileti()
        gl.addRow(self.l_dil)
        gl.addRow(self._not(T.Y_DIL_NOT_UYGULA))
        # UX-K: panel teması (panel.json "tema"; kayıt yoksa koyu); Uygula'da hemen uygulanır
        self.c_tema = QComboBox()
        self._doldur(self.c_tema, tuple(T.Y_TEMA_SECENEK), T.Y_TEMA_SECENEK)
        self._sec(self.c_tema, A.tema_tercihi())
        self.c_tema.activated.connect(lambda _i: self._degisti())
        gl.addRow(self._etiket(T.Y_TEMA), self.c_tema)
        kok.addWidget(g)

    def _onay_kur(self, kok):
        g = self._grup(T.Y_ONAY)
        gl = _duzen(QFormLayout(g))
        self.c_onay = QComboBox()
        self._doldur(self.c_onay, A.ONAY_KAPSAMLARI, T.Y_ONAY_SECENEK)
        self._sec(self.c_onay, A.onay_kapsami_oku())
        self.c_onay.activated.connect(lambda _i: self._degisti())
        gl.addRow(self._etiket(T.Y_ONAY_SORULARI), self.c_onay)
        self.l_onay = _Ileti()
        gl.addRow(self.l_onay)
        gl.addRow(self._not(T.Y_ONAY_NOT))
        kok.addWidget(g)

    def _mesgul_kur(self, kok):
        g = self._grup(T.Y_MESGUL)
        gl = _duzen(QFormLayout(g))
        self.k_tam = None
        if self.karar.var:
            mevcut = self.karar.oku()
            self.c_mesgul = QComboBox()
            self._doldur(self.c_mesgul, self.karar.mesgulken_secenek, T.Y_MESGUL_SECENEK)
            self.s_sure = QSpinBox()
            self.s_sure.setMinimumHeight(_HEDEF + 4)
            self.s_sure.setRange(*[int(v) for v in self.karar.sor_sure_aralik])
            self.mt.fn(lambda: self.s_sure.setSuffix(" " + _(T.Y_SN)))
            self.c_cevapsiz = QComboBox()
            self._doldur(self.c_cevapsiz, self.karar.cevapsiz_secenek, T.Y_CEVAPSIZ_SECENEK)
            gl.addRow(self._etiket(T.Y_MESGULKEN), self.c_mesgul)
            gl.addRow(self._etiket(T.Y_SOR_SURE), self.s_sure)
            gl.addRow(self._etiket(T.Y_CEVAPSIZ), self.c_cevapsiz)
            if "tam_ekranda_sor" in self.karar.anahtarlar:
                self.k_tam = self._kutu(T.Y_TAM_EKRAN)
                self.mt(self.k_tam.setToolTip, T.Y_TAM_EKRAN_NOT)
                gl.addRow(self.k_tam)
                self.k_tam.toggled.connect(lambda _d: self._degisti())
            self._karar_goster(mevcut)
            self.c_mesgul.activated.connect(lambda _i: self._degisti())
            self.s_sure.valueChanged.connect(lambda _v: self._degisti())
            self.c_cevapsiz.activated.connect(lambda _i: self._degisti())
            self.l_karar = _Ileti()
            gl.addRow(self.l_karar)
        else:
            gl.addRow(self._not_duz(T.Y_MESGUL_YOK))
        kok.addWidget(g)

    def _liste_dugmeleri(self, gl, tur: str):
        sat = QHBoxLayout()
        sat.setSpacing(_BOSLUK)
        ekle, kaldir = QPushButton(), QPushButton()
        self.mt(ekle.setText, T.Y_UYGULAMA_EKLE)
        self.mt(kaldir.setText, T.Y_KALDIR)
        ekle.clicked.connect(lambda: self.uygulama_ekle(tur))
        kaldir.clicked.connect(lambda: self.secili_kaldir(tur))
        metin = self._kutu(T.Y_METIN_KIPI)
        metin.toggled.connect(lambda d: self._metin_kipi(tur, d))
        for w in (ekle, kaldir):
            w.setMinimumHeight(_HEDEF)
            sat.addWidget(w)
        sat.addStretch(1)
        sat.addWidget(metin)
        gl.addLayout(sat)
        return ekle, kaldir, metin

    @staticmethod
    def _metin_alani(yukseklik: int) -> QPlainTextEdit:
        e = QPlainTextEdit()
        f = e.font()
        f.setFamily("monospace")
        f.setStyleHint(f.StyleHint.Monospace)
        e.setFont(f)
        e.setMinimumHeight(yukseklik)
        e.setVisible(False)
        return e

    def _yasak_kur(self, kok):
        g = self._grup(T.Y_YASAK)
        gl = _duzen(QVBoxLayout(g))
        gl.addWidget(self._not(T.Y_YASAK_LISTE_NOT))
        self.yasak_liste = QListWidget()
        self.yasak_liste.setMinimumHeight(120)
        self.mt(self.yasak_liste.setAccessibleName, T.Y_YASAK)
        gl.addWidget(self.yasak_liste)
        self.yasak = self._metin_alani(150)  # metin kipi (ileri düzey): tek doğruluk kaynağı
        self.mt(self.yasak.setAccessibleName, T.Y_YASAK)
        self.yasak_metin_not = self._not_duz(T.Y_YASAK_ACIKLAMA)
        self.yasak_metin_not.setVisible(False)
        gl.addWidget(self.yasak_metin_not)
        gl.addWidget(self.yasak)
        self.b_yasak_ekle, self.b_yasak_kaldir, self.k_yasak_metin = self._liste_dugmeleri(gl, "yasak")
        self.b_yasak_kaydet = self.b_yasak_ekle  # uyumluluk: doğrulanmamış listede düzenleme düğmesi kapalı (EK-2)
        self.l_yasak = _Ileti()
        gl.addWidget(self.l_yasak)
        self.yasak.textChanged.connect(lambda: self._metin_degisti("yasak"))
        kok.addWidget(g)

    def _seviye_kur(self, kok):
        g = self._grup(T.Y_SEVIYE)
        gl = _duzen(QVBoxLayout(g))
        gl.addWidget(self._not(T.Y_SEVIYE_LISTE_NOT))
        self.seviye_tablo = QTableWidget(0, 2)
        self.seviye_tablo.setMinimumHeight(120)
        self.seviye_tablo.verticalHeader().setVisible(False)
        self.seviye_tablo.verticalHeader().setDefaultSectionSize(_HEDEF + 8)
        self.seviye_tablo.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.seviye_tablo.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.seviye_tablo.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.seviye_tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mt.fn(lambda: self.seviye_tablo.setHorizontalHeaderLabels([_(T.Y_UYGULAMA), _(T.Y_SEVIYE_SUTUN)]))
        self.mt(self.seviye_tablo.setAccessibleName, T.Y_SEVIYE)
        gl.addWidget(self.seviye_tablo)
        self.seviye = self._metin_alani(110)
        self.mt(self.seviye.setAccessibleName, T.Y_SEVIYE)
        self.seviye_metin_not = self._not_duz(T.Y_SEVIYE_ACIKLAMA)
        self.seviye_metin_not.setVisible(False)
        gl.addWidget(self.seviye_metin_not)
        gl.addWidget(self.seviye)
        self.b_seviye_ekle, self.b_seviye_kaldir, self.k_seviye_metin = self._liste_dugmeleri(gl, "seviye")
        self.b_seviye_kaydet = self.b_seviye_ekle  # uyumluluk (EK-2)
        self.l_seviye = _Ileti()
        gl.addWidget(self.l_seviye)
        self.seviye.textChanged.connect(lambda: self._metin_degisti("seviye"))
        kok.addWidget(g)

    def _hesap_kur(self, kok):
        g = self._grup(T.Y_HESAP)
        gl = _duzen(QVBoxLayout(g))
        uyari = QLabel()
        uyari.setWordWrap(True)
        self.mt(lambda m, e=uyari: e.setText("⚠ " + m), T.Y_HESAP_UYARI)
        gl.addWidget(uyari)
        self.k_hesap_hepsi = self._kutu(T.Y_HESAP_HEPSI)  # ana anahtar: üçünü birlikte işaretler
        self.k_hesap_hepsi.toggled.connect(self._hesap_hepsi_isaretle)
        gl.addWidget(self.k_hesap_hepsi)
        self.k_hesap: dict[str, QCheckBox] = {}
        for sag in A.HESAP_SAGLAYICILARI:
            k = self._kutu(T.Y_HESAP_SECENEK[sag])
            k.toggled.connect(lambda _d: self._hesap_tek_isaretle())
            k.setStyleSheet("QCheckBox { margin-left: 22px; }")  # ana anahtarın altında girintili
            self.k_hesap[sag] = k
            gl.addWidget(k)
        self._hesap_kutulari()
        self.l_hesap = _Ileti()
        gl.addWidget(self.l_hesap)
        gl.addWidget(self._not(T.Y_HESAP_NOT))
        kok.addWidget(g)

    def _gizli_kur(self, kok):
        """Gizli bilgiler (anahtar deposu): arka uç sekme ilk görününce okunur (açılışta D-Bus/cüzdan yok)."""
        self.gizli = GizliBilgiler(self.mt, self._gizli_arka_uc)
        self.gizli.degisti.connect(self._degisti)
        self.gizli.yuklendi.connect(self._gizli_yuklendi)
        kok.addWidget(self.gizli)

    def _gizli_yuklendi(self) -> None:
        """Arka uç okundu: kayıtlı taban arka ucun değeri (bekleyen seçim yoksa ekranda da o)."""
        if self._kayitli:
            self._kayitli["gizli"] = self.gizli.kayitli()
        self._degisti()

    def _kisayol_kur(self, kok):
        panel = A.panel_oku()
        g = self._grup(T.Y_KISAYOL)
        gl = _duzen(QFormLayout(g))
        self.k_acik = self._kutu(T.Y_KISAYOL_AC)
        self.k_acik.setChecked(panel["kisayol_acik"])
        self.k_tus = QKeySequenceEdit(QKeySequence(panel["kisayol"]))
        self.k_tus.setMaximumWidth(340)
        self.k_tus.setMinimumHeight(_HEDEF + 4)
        self.mt(self.k_tus.setAccessibleName, T.Y_KISAYOL_TUS)
        if hasattr(self.k_tus, "setMaximumSequenceLength"):
            self.k_tus.setMaximumSequenceLength(1)
        # Qt tuş adlarını NativeText ile, Qt'nin kendi (sistem dili) çevirisiyle gösterir: Türkçe Qt çevirisi
        # "Meta+Seçenek+Vazgeç" yazıyordu. Kutu, KDE'nin ve kglobalshortcutsrc'nin kullandığı PortableText'i
        # (Meta+Alt+Esc) gösterir; kaydedilen değer zaten PortableText. Temizle düğmesi yok (adsız küçük hedef);
        # Sıfırla kayıtlı tuşa döndürür.
        self.k_tus.keySequenceChanged.connect(self._tus_degisti)
        self.k_tus.editingFinished.connect(self._tus_yaz)
        self._tus_yaz()
        self.l_kisayol = _Ileti()
        gl.addRow(self.k_acik)
        gl.addRow(self._etiket(T.Y_KISAYOL_TUS), self.k_tus)
        gl.addRow(self.l_kisayol)
        gl.addRow(self._not(T.Y_KISAYOL_NOT))
        self.k_acik.toggled.connect(lambda _d: self._degisti())
        kok.addWidget(g)

    def _gorev_kur(self, kok):
        """Görev başlatma onayı (UX-F): Görev penceresinde "Bir daha sorma" denince buradan yeniden açılır."""
        g = self._grup(T.Y_GOREV)
        gl = _duzen(QVBoxLayout(g))
        self.k_gorev_onay = self._kutu(T.Y_GOREV_ONAY)
        self.k_gorev_onay.setChecked(self._gorev_onay_oku())
        self.k_gorev_onay.toggled.connect(lambda _d: self._degisti())
        gl.addWidget(self.k_gorev_onay)
        self.l_gorev = _Ileti()
        gl.addWidget(self.l_gorev)
        gl.addWidget(self._not(T.Y_GOREV_ONAY_NOT))
        kok.addWidget(g)

    @staticmethod
    def _gorev_onay_oku() -> bool:
        try:
            return AY.al("gorev", "baslat_onayi") is not False
        except Exception:  # noqa: BLE001 - okunamadı: güvenli taraf (sorulur)
            return True

    def _gorev_onay_yukle(self) -> None:
        """Görev penceresi tercihi değiştirmiş olabilir: bekleyen değişiklik yoksa kayıtlı değeri göster."""
        if self._kayitli and "gorev" in self.degisenler():
            return
        v = self._gorev_onay_oku()
        self._yukleniyor += 1
        try:
            self.k_gorev_onay.setChecked(v)
        finally:
            self._yukleniyor -= 1
        self._kayitli["gorev"] = v
        self._degisti()

    def _gorev_onay_kaydet(self) -> bool:
        v = self.k_gorev_onay.isChecked()
        try:
            AY.ayarla("gorev", "baslat_onayi", v)
        except Exception as e:  # noqa: BLE001
            self.l_gorev.hata(T.hata_ozeti(e), e)
            return False
        self.l_gorev.setText("")
        self._kayitli["gorev"] = v
        return True

    def _simge_kur(self, kok):
        """Kayıtlı simgeler (UX-F O7: ayrı sekme yerine Gelişmiş altında)."""
        g = self._grup(T.Y_SIMGELER)
        gl = _duzen(QVBoxLayout(g))
        gl.addWidget(self._not(T.Y_SIMGELER_NOT))
        self.simgeler = SimgelerSekmesi(sor=self._simge_sor)
        self.simgeler.setMinimumHeight(220)
        gl.addWidget(self.simgeler)
        kok.addWidget(g)

    # -------- metin yardımcıları (dil değişince tazele() hepsini yeniden yazar)
    def _grup(self, msgid: str) -> QGroupBox:
        g = QGroupBox()
        self.mt(g.setTitle, msgid)
        return g

    def _etiket(self, msgid: str) -> QLabel:
        e = QLabel()
        self.mt(e.setText, msgid)
        return e

    def _not(self, msgid: str) -> _Aciklama:
        """Açıklama: katlı "ⓘ Açıklama" (UX-F O9, yoğunluk); açılınca normal renk (D5/O9 kontrast)."""
        a = _Aciklama(self.mt, msgid)
        self.aciklamalar.append(a)
        return a

    def _not_duz(self, msgid: str) -> QLabel:
        """Her zaman görünen kısa bilgi (durum iletisi, metin kipinin açıklaması): normal renk."""
        e = QLabel()
        e.setWordWrap(True)
        self.mt(e.setText, msgid)
        return e

    _soluk = _not_duz  # eski ad

    def _kutu(self, msgid: str) -> QCheckBox:
        k = QCheckBox()
        k.setMinimumHeight(_HEDEF)
        self.mt(k.setText, msgid)
        return k

    def _doldur(self, c: QComboBox, anahtarlar, adlar: dict) -> None:
        c.setMinimumHeight(_HEDEF)
        for i, k in enumerate(anahtarlar):
            c.addItem("", k)
            self.mt.fn(lambda c=c, i=i, k=k: c.setItemText(i, _(adlar[k]) if k in adlar else str(k)))

    def _tus_yaz(self, *_a) -> None:
        kutu = self.k_tus.findChild(QLineEdit)
        if kutu is not None:
            kutu.setText(self.k_tus.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def _tus_degisti(self, *_a) -> None:
        self._tus_yaz()
        self.cakisma_goster()
        self._degisti()

    def tazele(self) -> None:
        self.mt.tazele()
        self.simgeler.tazele()
        self.gizli.ileti("")
        self._tus_yaz()
        self.cakisma_goster()
        etiketler = [getattr(self, "l_karar", None), self.l_onay, self.l_gorev]  # eski dildeki iletiler
        etiketler += [e for t, e in (("yasak", self.l_yasak), ("seviye", self.l_seviye))
                      if not self._liste_kilitli.get(t)]  # DOĞRULANMADI etiketi kalır
        for e in etiketler:
            if e is not None:
                e.setText("")
        self._yukleniyor += 1
        try:
            self._liste_yenile("yasak")
            self._liste_yenile("seviye")
        finally:
            self._yukleniyor -= 1
        self._durum_yaz()

    # =================================================================== kaydetme modeli
    def _anlik(self) -> dict:
        d = {"dil": self.c_dil.currentData(), "tema": self.c_tema.currentData(), "onay": self.c_onay.currentData(),
             "hesap": frozenset(s for s, k in self.k_hesap.items() if k.isChecked()),
             "yasak": self.yasak.toPlainText(), "seviye": self.seviye.toPlainText(),
             "kisayol": (self.k_acik.isChecked(), self.tus()), "gorev": self.k_gorev_onay.isChecked(),
             "gizli": self.gizli.anlik()}
        if self.karar.var:
            d["karar"] = self._karar_degerleri()
        return d

    def degisenler(self) -> list[str]:
        """Kaydedilmemiş bölümler (Uygula sırası)."""
        a = self._anlik()
        return [k for k in ("onay", "hesap", "gizli", "karar", "gorev", "yasak", "seviye", "kisayol", "tema", "dil")
                if k in a and a[k] != self._kayitli.get(k)]

    def kaydedilmemis_var(self) -> bool:
        return bool(self.degisenler())

    def _degisti(self) -> None:
        """Herhangi bir değer değişti: 'Kaydedildi ✓' hemen kalkar; bekleyen değişiklik varsa gösterge çıkar."""
        if self._yukleniyor:
            return
        var = self.kaydedilmemis_var()
        self.b_uygula.setEnabled(var)
        self.b_sifirla.setEnabled(var)
        if var and self._durum[0] != "hata":
            self._durum_ayarla("degisiklik")
        elif not var and self._durum[0] == "degisiklik":
            self._durum_ayarla("")

    def _durum_ayarla(self, tur: str, **deger) -> None:
        self._durum = (tur, deger)
        self._durum_saat.stop()
        if tur == "kaydedildi":
            self._durum_saat.start(KAYDEDILDI_MS)
        self._durum_yaz()

    def _durum_yaz(self) -> None:
        tur, d = self._durum
        if tur == "degisiklik":
            m = _(T.Y_DEGISIKLIK_VAR)
        elif tur == "kaydedildi":
            m = _(T.Y_KAYDEDILDI_TIK)
        elif tur == "hata":
            m = "  ".join(d.get("iletiler", ()))
        else:
            m = ""
        self.l_durum.setText(m)
        self.l_durum.setVisible(bool(m))

    def _kaydedildi_sil(self) -> None:
        if self._durum[0] == "kaydedildi":
            self._durum_ayarla("")

    def durum_metni(self) -> str:
        return self.l_durum.text() if self.l_durum.isVisibleTo(self) else ""

    def uygula(self) -> bool:
        """Bekleyen bölümleri mevcut kayıt yollarından yazar (güvenlik ayarları: imzalı panel kaydı + onay diyaloğu).
        Yazılamayan bölüm kayıtlı değerine döner; geçersiz giriş (bozuk satır) düzeltilsin diye ekranda kalır.
        → hepsi kaydedildi mi."""
        iletiler, tamam = [], True
        bolum_adi = {"onay": T.Y_ONAY, "hesap": T.Y_HESAP, "gizli": Y_GIZLI, "karar": T.Y_MESGUL, "gorev": T.Y_GOREV, "yasak": T.Y_YASAK,
                     "seviye": T.Y_SEVIYE, "kisayol": T.Y_KISAYOL, "tema": T.Y_TEMA, "dil": T.Y_DIL}
        for k in self.degisenler():
            sonuc, hata = self._bolum_uygula(k)
            if sonuc == "tamam":
                continue
            tamam = False
            bolum = _(bolum_adi[k])
            if sonuc == "gecersiz":
                iletiler.append(_(T.Y_UYGULA_GECERSIZ).format(bolum=bolum))
            elif sonuc == "red":
                iletiler.append(_(T.Y_UYGULA_RED).format(bolum=bolum))
                self._bolum_geri(k)
            else:
                iletiler.append(_(T.Y_UYGULA_HATA).format(bolum=bolum, hata=hata))
                self._bolum_geri(k)
        if tamam:
            self._durum_ayarla("kaydedildi")
        else:
            self._durum_ayarla("hata", iletiler=iletiler)
        self._degisti()
        return tamam

    def _bolum_uygula(self, k: str) -> tuple[str, str]:
        """→ ("tamam" | "gecersiz" | "red" | "hata", hata metni)."""
        if k == "onay":
            return self._sonuc(self.onay_kapsami_sec(self.c_onay.currentData()), self.l_onay)
        if k == "hesap":
            return self.hesap_uygula()
        if k == "gizli":
            sonuc = self.gizli.uygula()
            self._kayitli["gizli"] = self.gizli.kayitli()  # arka ucun değeri (kısmi yazmada da doğru taban)
            return sonuc
        if k == "karar":
            return self._sonuc(self.karar_kaydet(), self.l_karar)
        if k == "gorev":
            return self._sonuc(self._gorev_onay_kaydet(), self.l_gorev)
        if k == "yasak":
            if self._liste_kilitli.get("yasak") or A.yasak_dogrula(self.yasak.toPlainText()):
                self.yasak_kaydet()
                return "gecersiz", ""
            return self._sonuc(self.yasak_kaydet(), self.l_yasak)
        if k == "seviye":
            if self._liste_kilitli.get("seviye") or A.seviye_dogrula(self.seviye.toPlainText()):
                self.seviye_kaydet()
                return "gecersiz", ""
            return self._sonuc(self.seviye_kaydet(), self.l_seviye)
        if k == "kisayol":
            return self._sonuc(self._kisayol_kaydet(), self.l_kisayol)
        if k == "tema":
            return self._sonuc(self._tema_kaydet(), self.l_dil)
        if k == "dil":
            kod = self.c_dil.currentData()
            sonuc = self.dil_sec(kod)
            if sonuc or i18n.ayar_oku() == kod:
                self._kayitli["dil"] = kod
                return "tamam", ""
            return "hata", self.l_dil.text()
        return "tamam", ""

    @staticmethod
    def _sonuc(basarili: bool, etiket) -> tuple[str, str]:
        return ("tamam", "") if basarili else ("hata", etiket.text() if etiket is not None else "")

    def _bolum_geri(self, k: str) -> None:
        """Yazılamayan bölümü kayıtlı değerine döndür (sinyal üretmeden)."""
        self._yukleniyor += 1
        try:
            v = self._kayitli.get(k)
            if k == "onay":
                self._sec(self.c_onay, v)
            elif k == "hesap":
                self._hesap_kutulari(v)
            elif k == "gizli":
                self.gizli.goster(v)
            elif k == "karar":
                self._karar_goster(dict(zip(("mesgulken", "sor_sure", "cevapsiz", "tam_ekranda_sor"), v, strict=True)))
            elif k == "yasak":
                self.yasak.setPlainText(v)
            elif k == "seviye":
                self.seviye.setPlainText(v)
            elif k == "gorev":
                self.k_gorev_onay.setChecked(bool(v))
            elif k == "kisayol":
                self.k_acik.setChecked(v[0])
                self.k_tus.setKeySequence(QKeySequence(v[1]))
                self._tus_yaz()
            elif k == "tema":
                self._sec(self.c_tema, v)
            elif k == "dil":
                self._dil_secili()
        finally:
            self._yukleniyor -= 1

    def sifirla(self) -> None:
        """Ekrandaki bütün değerleri kayıtlı haline döndür."""
        self._yukleniyor += 1
        try:
            self._dil_secili()
            self._sec(self.c_tema, A.tema_tercihi())
            self._sec(self.c_onay, A.onay_kapsami_oku())
            self._hesap_kutulari()
            self.gizli.goster(self.gizli.kayitli())
            self.gizli.ileti("")
            if self.karar.var:
                self._karar_goster(self.karar.oku())
            self.k_gorev_onay.setChecked(self._gorev_onay_oku())
            panel = A.panel_oku()
            self.k_acik.setChecked(panel["kisayol_acik"])
            self.k_tus.setKeySequence(QKeySequence(panel["kisayol"]))
            self._tus_yaz()
            for e in (getattr(self, "l_karar", None), self.l_onay, self.l_hesap, self.l_kisayol, self.l_gorev):
                if e is not None:
                    e.setText("")
        finally:
            self._yukleniyor -= 1
        self.yasak_yukle()
        self.seviye_yukle()
        self.cakisma_goster()
        self._kayitli = self._anlik()
        self._durum_ayarla("")
        self._degisti()

    # -------- çıkış sorusu: sekmeden / pencereden ayrılırken
    def cikis_sorusu(self) -> str:
        """Uygula / Değişiklikleri at / İptal → "uygula" | "at" | "iptal". Testler bu yöntemi değiştirir."""
        k = QMessageBox(QMessageBox.Icon.Question, _(T.Y_CIKIS_BASLIK), _(T.Y_CIKIS_SORU),
                        QMessageBox.StandardButton.NoButton, self)
        uygula = k.addButton(_(T.Y_UYGULA), QMessageBox.ButtonRole.AcceptRole)
        at = k.addButton(_(T.Y_CIKIS_AT), QMessageBox.ButtonRole.DestructiveRole)
        iptal = k.addButton(_(T.Y_IPTAL), QMessageBox.ButtonRole.RejectRole)
        k.setDefaultButton(uygula)
        k.setEscapeButton(iptal)
        k.exec()
        return {uygula: "uygula", at: "at"}.get(k.clickedButton(), "iptal")

    def ayrilabilir_mi(self) -> bool:
        """Bekleyen değişiklik yoksa True; varsa sorar: Uygula (başarılıysa True), At (Sıfırla + True), İptal (False)."""
        if not self.kaydedilmemis_var():
            return True
        cevap = self.cikis_sorusu()
        if cevap == "uygula":
            return self.uygula()
        if cevap == "at":
            self.sifirla()
            return True
        return False

    def _ust_bagla(self) -> None:
        if self._ust_sekme is None:
            w = self.parentWidget()
            while w is not None and not isinstance(w, QTabWidget):
                w = w.parentWidget()
            if w is not None:
                self._ust_sekme = w
                self._ust_onceki = w.currentIndex()
                w.currentChanged.connect(self._ust_sekme_degisti)
        pen = self.window()
        if pen is not self and self._pencere_suzgec is not pen:
            pen.installEventFilter(self)
            self._pencere_suzgec = pen

    def _ust_sekme_degisti(self, i: int) -> None:
        tw = self._ust_sekme
        benim = tw.indexOf(self)
        onceki, self._ust_onceki = self._ust_onceki, i
        if self._geri_donuyor or onceki != benim or i == benim:
            return
        if not self.ayrilabilir_mi():
            self._geri_donuyor = True
            try:
                tw.setCurrentIndex(benim)
            finally:
                self._geri_donuyor = False
            self._ust_onceki = benim

    def eventFilter(self, nesne, olay):  # noqa: N802
        # yalnız kullanıcının kapatması (spontane); programın close() çağrısı sormaz
        if (nesne is self._pencere_suzgec and olay.type() == QEvent.Type.Close and olay.spontaneous()
                and not self.ayrilabilir_mi()):
            olay.ignore()
            return True
        return super().eventFilter(nesne, olay)

    # =================================================================== dil
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
            self.l_dil.hata(T.hata_ozeti(e), e)
            return False
        yeni = i18n.yeniden_yukle()
        istenen = i18n.sistem_dili() if kod == i18n.OTOMATIK else kod
        self._dil_secili()
        self._kayitli["dil"] = kod
        self.dil_degisti.emit(yeni)  # → AnaPencere.tazele → bu sekmenin tazele()'si
        if yeni != istenen:  # DESKHAND_DIL bu süreçte dili zorluyor
            self.l_dil.setText(_(T.Y_DIL_ZORLA).format(dil=i18n.DILLER.get(yeni, yeni)))
        else:
            self.l_dil.setText("")
        self._degisti()
        return True

    @staticmethod
    def _sec(c: QComboBox, deger):
        i = c.findData(deger)
        if i >= 0:
            c.setCurrentIndex(i)

    # =================================================================== yetkili değerler (onay, hesap)
    def panel_degerleri_yukle(self) -> None:
        """Onay kapsamı + hesap oturumları: arka ucun UYGULADIĞI (panelin yetkili) değer, sinyal üretmeden. Sekme
        panel koruyucusundan (liste_koruma.panel_baslat) ÖNCE kurulur: panel açılışta ve sekme her gösterildiğinde
        bunu çağırır. Bekleyen (uygulanmamış) seçim ekranda kalır; kayıtlı taban güncellenir. Dosyada başka
        (doğrulanmamış) değer yazıyorsa boş kutuyla gizlenmez, etiketlenir."""
        from ... import liste_koruma
        bekleyen = set(self.degisenler()) if self._kayitli else set()
        kapsam = A.onay_kapsami_oku()
        acik = A.hesap_oturumlari_oku()
        self._yukleniyor += 1
        try:
            if "onay" not in bekleyen:
                self._sec(self.c_onay, kapsam)
            if "hesap" not in bekleyen:
                self._hesap_kutulari(acik)
        finally:
            self._yukleniyor -= 1
        self._kayitli["onay"], self._kayitli["hesap"] = kapsam, frozenset(acik)
        dosya_kapsam = liste_koruma._kapsam_dosyadan()
        self._farkli_etiket(self.l_onay, dosya_kapsam != kapsam,
                            _(T.Y_ONAY_SECENEK.get(dosya_kapsam, dosya_kapsam)))
        dosya_kimlik = liste_koruma.kimlik_dosyada()
        self._farkli_etiket(self.l_hesap, dosya_kimlik != acik,
                            ", ".join(_(T.Y_HESAP_AD[s]) for s in A.HESAP_SAGLAYICILARI if s in dosya_kimlik) or "—")
        self._degisti()

    def _farkli_etiket(self, etiket: QLabel, farkli: bool, dosyadaki: str) -> None:
        if farkli:
            etiket.setText(_(Y_DOSYADA_FARKLI).format(deger=dosyadaki))
        elif etiket.property("dosyada_farkli"):
            etiket.setText("")
        etiket.setProperty("dosyada_farkli", farkli)

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._ust_bagla()
        self._gorev_onay_yukle()
        from ... import liste_koruma
        if liste_koruma.AKTIF is not None:  # panel sürecinde: bellek okuması (kanal çağrısı yok)
            self.panel_degerleri_yukle()

    # =================================================================== kayıt yolları (Uygula bunları çağırır)
    def _karar_degerleri(self) -> tuple:
        return (self.c_mesgul.currentData(), self.s_sure.value(), self.c_cevapsiz.currentData(),
                self.k_tam.isChecked() if self.k_tam is not None else None)

    def _karar_goster(self, mevcut: dict) -> None:
        self._sec(self.c_mesgul, mevcut.get("mesgulken"))
        try:
            self.s_sure.setValue(int(mevcut.get("sor_sure") or 30))
        except (TypeError, ValueError):
            self.s_sure.setValue(30)
        self._sec(self.c_cevapsiz, mevcut.get("cevapsiz"))
        if self.k_tam is not None:
            self.k_tam.setChecked(bool(mevcut.get("tam_ekranda_sor")))

    def karar_kaydet(self) -> bool:
        try:
            d = {"mesgulken": self.c_mesgul.currentData(), "sor_sure": self.s_sure.value(),
                 "cevapsiz": self.c_cevapsiz.currentData()}
            if self.k_tam is not None:
                d["tam_ekranda_sor"] = self.k_tam.isChecked()
            self.karar.yaz(d)
        except Exception as e:  # noqa: BLE001
            self.l_karar.hata(T.hata_ozeti(e), e)
            return False
        self.l_karar.setText("")
        self._kayitli["karar"] = self._karar_degerleri()
        self._degisti()
        return True

    def onay_kapsami_sec(self, kapsam: str) -> bool:
        try:
            A.onay_kapsami_yaz(kapsam)  # panel: tek yetkili yazar (imzalı)
        except Exception as e:  # noqa: BLE001
            self._sec(self.c_onay, A.onay_kapsami_oku())
            self.l_onay.hata(T.hata_ozeti(e), e)
            return False
        self.l_onay.setText("")
        self._kayitli["onay"] = kapsam
        self._degisti()
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

    def _hesap_kutulari(self, acik=None) -> None:
        """Kutuları verilen (yoksa panelin yetkili) değere çek (sinyal üretmeden)."""
        acik = A.hesap_oturumlari_oku() if acik is None else acik
        for sag, k in [*self.k_hesap.items(), ("*", self.k_hesap_hepsi)]:
            k.blockSignals(True)
            k.setChecked(set(A.HESAP_SAGLAYICILARI) <= set(acik) if sag == "*" else sag in acik)
            k.blockSignals(False)

    def _hesap_hepsi_isaretle(self, acik: bool) -> None:
        self._hesap_kutulari(A.HESAP_SAGLAYICILARI if acik else ())
        self._degisti()

    def _hesap_tek_isaretle(self) -> None:
        self._hesap_kutulari(frozenset(s for s, k in self.k_hesap.items() if k.isChecked()))
        self._degisti()

    def hesap_uygula(self) -> tuple[str, str]:
        """İstenen hesap kümesini yaz. Yeni açılan her hesap için onay diyaloğu (üçü birden açılıyorsa tek soru);
        Hayır → o hesap açılmaz. Yazma panelin imzalı kimlik kaydından (liste_koruma.panel_kimlik_kaydet) geçer."""
        istenen = {s for s, k in self.k_hesap.items() if k.isChecked()}
        kayitli = set(A.hesap_oturumlari_oku())
        yeni = istenen - kayitli
        red = False
        if yeni == set(A.HESAP_SAGLAYICILARI) and len(yeni) > 1:
            if not self.hesap_onay_sor("hepsi"):
                istenen -= yeni
                red = True
        else:
            for sag in [s for s in A.HESAP_SAGLAYICILARI if s in yeni]:
                if not self.hesap_onay_sor(sag):
                    istenen.discard(sag)
                    red = True
        try:
            if istenen != kayitli:
                if istenen in (set(A.HESAP_SAGLAYICILARI), set()):
                    A.hesap_oturumlari_hepsi_yaz(bool(istenen))
                else:
                    for sag in A.HESAP_SAGLAYICILARI:
                        if (sag in istenen) != (sag in kayitli):
                            A.hesap_oturumu_yaz(sag, sag in istenen)
        except Exception as e:  # noqa: BLE001
            self.l_hesap.hata(T.hata_ozeti(e), e)
            self._kayitli["hesap"] = frozenset(A.hesap_oturumlari_oku())
            return "hata", T.hata_ozeti(e)
        self._kayitli["hesap"] = frozenset(A.hesap_oturumlari_oku())
        self.l_hesap.setText("")
        self._yukleniyor += 1
        try:
            self._hesap_kutulari()
        finally:
            self._yukleniyor -= 1
        return ("red", "") if red else ("tamam", "")

    # eski adlar (kutu tıklamasında kaydeden model): artık yalnız işaretler, Uygula yazar
    def hesap_oturumu_sec(self, saglayici: str, acik: bool) -> None:
        self.k_hesap[saglayici].setChecked(acik)

    def hesap_hepsi_sec(self, acik: bool) -> None:
        self.k_hesap_hepsi.setChecked(acik)

    # =================================================================== yasak / seviye listeleri
    def _alan(self, tur: str) -> QPlainTextEdit:
        return self.yasak if tur == "yasak" else self.seviye

    def _liste_kilidi(self, tur: str) -> bool:
        """An unverified list (wallet unreadable, the user said No; liste_koruma) is shown READ-ONLY with a label and
        cannot be saved: saving would sign the unapproved file content (review EK-2). → locked."""
        from ... import liste_koruma
        kilitli = liste_koruma.dogrulanmamis(tur)
        alan, etiket = (self.yasak, self.l_yasak) if tur == "yasak" else (self.seviye, self.l_seviye)
        alan.setReadOnly(kilitli)
        for w in ((self.b_yasak_ekle, self.b_yasak_kaldir, self.yasak_liste) if tur == "yasak" else
                  (self.b_seviye_ekle, self.b_seviye_kaldir, self.seviye_tablo)):
            w.setEnabled(not kilitli)
        if kilitli:
            # the same display as the panel's question (review INC4 O3): every applied entry numbered, invisible /
            # look-alike characters visible; the fixed label (entry count) is outside the content field
            g = liste_koruma.dogrulanmamis_gosterim(tur, liste_koruma.AKTIF.metin(tur) if liste_koruma.AKTIF else None)
            b = g.bolumler[0]
            self._yukleniyor += 1
            try:
                alan.setPlainText("\n".join(b.satirlar))
            finally:
                self._yukleniyor -= 1
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

    def _metin_kipi(self, tur: str, acik: bool) -> None:
        if tur == "yasak":
            liste, alan, not_ = self.yasak_liste, self.yasak, self.yasak_metin_not
        else:
            liste, alan, not_ = self.seviye_tablo, self.seviye, self.seviye_metin_not
        liste.setVisible(not acik)
        alan.setVisible(acik)
        not_.setVisible(acik)

    def _metin_degisti(self, tur: str) -> None:
        self._liste_yenile(tur)
        etiket = self.l_yasak if tur == "yasak" else self.l_seviye
        if not self._liste_kilitli.get(tur):
            etiket.setText("")
        self._degisti()

    def _liste_yenile(self, tur: str) -> None:
        """Metinden (tek doğruluk kaynağı) görsel listeyi kur: uygulama adı (+ seviye açılır kutusu)."""
        satirlar = _kural_satirlari(self._alan(tur).toPlainText(), tur == "seviye")
        if tur == "yasak":
            self.yasak_liste.clear()
            for no, desen, _k in satirlar:
                it = QListWidgetItem(desen_adi(desen))
                it.setData(Qt.ItemDataRole.UserRole, no)
                self.yasak_liste.addItem(it)
            return
        t = self.seviye_tablo
        t.setRowCount(0)
        for no, desen, kok in satirlar:
            r = t.rowCount()
            t.insertRow(r)
            it = QTableWidgetItem(desen_adi(desen))
            it.setData(Qt.ItemDataRole.UserRole, no)
            t.setItem(r, 0, it)
            c = QComboBox()
            c.setMinimumHeight(_HEDEF)
            for kk in SEVIYE_KOKLER:
                c.addItem(_(T.Y_SEVIYE_AD[kk]), kk)
            self._sec(c, kok or "goruntule")
            c.setAccessibleName(_(T.Y_SEVIYE_SUTUN))
            c.setEnabled(not self._liste_kilitli.get("seviye", False))
            c.activated.connect(lambda _i, no=no, c=c: self._seviye_degistir(no, c.currentData()))
            t.setCellWidget(r, 1, c)

    def _satir_degistir(self, tur: str, no: int, yeni: str | None) -> None:
        """Metnin `no`. satırını değiştir (yeni None → sil); görsel liste textChanged ile yeniden kurulur."""
        satirlar = self._alan(tur).toPlainText().splitlines()
        if not 0 <= no < len(satirlar):
            return
        if yeni is None:
            del satirlar[no]
        else:
            satirlar[no] = yeni
        self._alan(tur).setPlainText("\n".join(satirlar) + ("\n" if satirlar else ""))

    def _seviye_degistir(self, no: int, kok: str) -> None:
        satir = self.seviye.toPlainText().splitlines()[no]
        desen = satir.rpartition("=")[0].strip() if "=" in satir else satir.strip()
        self._satir_degistir("seviye", no, f"{desen} = {kok}")

    def pencere_sec(self, tur: str) -> tuple[str, str] | None:
        """Açık pencerelerden uygulama seç (diyalog) → (ad, desen) | None. Testler bu yöntemi değiştirir."""
        etiket = self.l_yasak if tur == "yasak" else self.l_seviye
        try:
            secenekler = self.pencere_f()
        except Exception as e:  # noqa: BLE001 - masaüstü okunamadı: panel çökmesin, görünür ileti
            etiket.setText(_(T.Y_PENCERE_OKUNAMADI), T.hata_ayrinti(e))
            return None
        if not secenekler:
            etiket.setText(_(T.Y_PENCERE_YOK))
            return None
        d = PencereSecDiyalog(secenekler, self)
        return d.secim() if d.exec() == QDialog.DialogCode.Accepted else None

    def uygulama_ekle(self, tur: str, secim: tuple[str, str] | None = None) -> bool:
        """Listeye uygulama ekle (seviye listesine 'Yalnız göster' ile; kutudan değiştirilir). Kaydetmez: Uygula."""
        if self._liste_kilitli.get(tur):
            return False
        secim = secim or self.pencere_sec(tur)
        if not secim:
            return False
        desen = secim[1]
        if any(d == desen for _n, d, _k in _kural_satirlari(self._alan(tur).toPlainText(), tur == "seviye")):
            return False
        metin = self._alan(tur).toPlainText()
        if metin and not metin.endswith("\n"):
            metin += "\n"
        self._alan(tur).setPlainText(metin + (f"{desen} = goruntule" if tur == "seviye" else desen) + "\n")
        return True

    def secili_kaldir(self, tur: str) -> bool:
        if self._liste_kilitli.get(tur):
            return False
        if tur == "yasak":
            it = self.yasak_liste.currentItem()
        else:
            r = self.seviye_tablo.currentRow()
            it = self.seviye_tablo.item(r, 0) if r >= 0 else None
        if it is None:
            return False
        self._satir_degistir(tur, it.data(Qt.ItemDataRole.UserRole), None)
        return True

    def yasak_yukle(self):
        self._yukleniyor += 1
        try:
            self.yasak.setPlainText(A.yasak_metni())
        finally:
            self._yukleniyor -= 1
        self._liste_yenile("yasak")
        self.l_yasak.setText("")
        self._liste_kilidi("yasak")
        self._kayitli["yasak"] = self.yasak.toPlainText()
        self._degisti()

    def yasak_kaydet(self) -> bool:
        if self._liste_kilidi("yasak"):
            return False
        metin = self.yasak.toPlainText()
        h = A.yasak_dogrula(metin)
        if h:
            self.l_yasak.setText(_(T.Y_DESEN_HATA).format(no=h[0], hata=h[1]), h[2])  # ham regex iletisi Ayrıntı'da
            return False
        try:
            A.yasak_kaydet(metin)  # panel: tek yetkili, imzalı kayıt
        except OSError as e:  # disk dolu / salt okunur: slottan fırlamasın (panel çökmesin)
            self.l_yasak.hata(T.hata_ozeti(e), e)
            return False
        self.l_yasak.setText("")
        self._kayitli["yasak"] = metin
        self._degisti()
        return True

    def seviye_yukle(self):
        self._yukleniyor += 1
        try:
            self.seviye.setPlainText(A.seviye_metni())
        finally:
            self._yukleniyor -= 1
        self._liste_yenile("seviye")
        self.l_seviye.setText("")
        self._liste_kilidi("seviye")
        self._kayitli["seviye"] = self.seviye.toPlainText()
        self._degisti()

    def seviye_kaydet(self) -> bool:
        if self._liste_kilidi("seviye"):
            return False
        metin = self.seviye.toPlainText()
        h = A.seviye_dogrula(metin)
        if h:
            self.l_seviye.setText(_(T.Y_SEVIYE_HATA).format(no=h[0], hata=h[1]), h[2])  # ham regex iletisi Ayrıntı'da
            return False
        try:
            A.seviye_kaydet(metin)  # panel: tek yetkili, imzalı kayıt
        except OSError as e:  # disk dolu / salt okunur: slottan fırlamasın (panel çökmesin)
            self.l_seviye.hata(T.hata_ozeti(e), e)
            return False
        self.l_seviye.setText("")
        self._kayitli["seviye"] = metin
        self._degisti()
        return True

    # =================================================================== kısayol
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

    def _tema_kaydet(self) -> bool:
        """Görünüm seçimi → panel.json "tema" + hemen uygula (gui.tema.tema_uygula)."""
        kip = self.c_tema.currentData()
        d = A.panel_oku()
        d["tema"] = kip
        try:
            A.panel_yaz(d)
        except OSError as e:
            self.l_dil.hata(T.hata_ozeti(e), e)
            return False
        from PyQt6.QtWidgets import QApplication

        from ..tema import tema_uygula
        app = QApplication.instance()
        if app is not None:
            tema_uygula(app, kip)
        self._kayitli["tema"] = kip
        return True

    def _kisayol_kaydet(self, *_a) -> bool:
        d = A.panel_oku()
        d["kisayol_acik"], d["kisayol"] = self.k_acik.isChecked(), self.tus()
        try:
            A.panel_yaz(d)
        except OSError as e:  # disk dolu / salt okunur: slottan fırlamasın (panel çökmesin)
            self.l_kisayol.hata(T.hata_ozeti(e), e)
            return False
        self.cakisma_goster()
        self._kayitli["kisayol"] = (d["kisayol_acik"], d["kisayol"])
        self.kisayol_degisti.emit(d["kisayol_acik"], d["kisayol"])
        self._degisti()
        return True

    def kisayol_durumu(self, metin: str, ayrinti: str = ""):
        """Sade cümle; ham hata (varsa) katlı Ayrıntı'da (iki katman, UX-L)."""
        self.l_kisayol.setText(metin, ayrinti)
