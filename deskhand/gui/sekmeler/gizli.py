"""Ayarlar › Gelişmiş › "Gizli bilgiler" grubu (anahtar deposu arayüzü).

Üç seçenek, her biri bir satır kartı: ad + DURUM rozeti (renkli nokta + sade metin) + kısa açıklama + aç/kapa anahtarı.
  1. Deskhand kasası (önerilen; cüzdan sorusu yok)     ┐ biri açıkken öteki kapalı: depo seçimi
  2. KDE Cüzdanı                                       ┘
  3. Girişte KDE Cüzdanı'nı aç (+ cüzdan parolası gizli alanı; yalnız açılırken)
Altında kayıtlı parolalar (yalnız adlar; değer ASLA gösterilmez) Ekle / Sil ve cüzdan kilitli/yoksa yönlendirme.

Kayıt modeli Ayarlar sekmesininki (UX-A): anahtarlar yalnız ekrandaki değeri değiştirir, Uygula yazar, Sıfırla geri alır.
Depo değişimi ve girişte otomatik açma GEVŞETME sayılır → Uygula'da Evet/Hayır sorusu (varsayılan Hayır; Hayır → anahtar
kayıtlı değerine döner). Parola listesi (Ekle/Sil) kendi diyaloğunda onaylanınca hemen yazılır (parola panel belleğinde
Uygula'ya kadar bekletilmez). Parolalar yalnız QLineEdit(Password) alanından doğrudan arka uca gider; iş bitince alan
temizlenir; günlüğe, ipucuna, hata iletisine yazılmaz.

Arka uç (deskhand.anahtar_deposu, deskhand.cuzdan_ac) ince bir bağlayıcıyla çağrılır: modül yoksa ya da çağrı hata
verirse "kullanılamıyor" durumu gösterilir ve anahtarlar kapanır (kapalı-başarısızlık; panel çökmez). Arka uç sekme ilk
GÖRÜNDÜĞÜNDE okunur (panel açılışı cüzdana/D-Bus'a gitmez)."""
from __future__ import annotations

import html
import shutil

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ...i18n import N_, _
from .. import metinler as T
from ..dil import Metinler

_BOSLUK, _KENAR, _HEDEF = 8, 12, 28   # ayarlar.py ile aynı aralık birimi / tıklama hedefi

# ---------------------------------------------------------------- metinler (iki dilli; en.json)
G_BASLIK = N_("Gizli bilgiler")
G_GIRIS = N_("Deskhand'in sakladığı parolalar ve ayar koruma anahtarı nerede dursun? Seçimi Uygula ile kaydedin.")
G_KASA = N_("Deskhand kasası")
G_KASA_NOT = N_("Önerilen. Parolalar bu bilgisayara kilitli bir dosyada durur; girişte cüzdan sorusu çıkmaz.")
G_CUZDAN = N_("KDE Cüzdanı")
G_CUZDAN_NOT = N_("Parolalar KDE Cüzdanı'nda durur. Cüzdan kilitliyse Deskhand onu açmaz; siz açana kadar bekler.")
G_OTO = N_("Girişte KDE Cüzdanı'nı aç")
G_OTO_NOT = N_("Oturum açılınca cüzdan parola sormadan açılır. Cüzdan parolası bu bilgisayara kilitli olarak saklanır.")
G_OTO_PAROLA = N_("Cüzdan parolası")
G_LISTE = N_("Kayıtlı parolalar")
G_LISTE_BOS = N_("Henüz kayıtlı parola yok.")
G_EKLE = N_("Parola ekle…")
G_SIL = N_("Sil")
G_YONETICI = N_("Cüzdan yöneticisini aç")
G_YONLENDIR = N_("KDE Cüzdanı kilitli ya da kurulu değil. Cüzdan yöneticisinden cüzdan oluşturup açın.")

# durum rozetleri
D_HAZIR_TPM = N_("Hazır · TPM ile korunuyor")
D_HAZIR = N_("Hazır · bu bilgisayarın anahtarıyla korunuyor")
D_KULLANILMIYOR = N_("Kullanılmıyor")
D_KULLANILAMIYOR = N_("Kullanılamıyor: {neden}")
D_ACIK = N_("Açık")
D_KILITLI = N_("Kilitli")
D_BILINMIYOR = N_("Durumu bilinmiyor")
D_SECILI_ACIK = N_("Seçili · açık")
D_SECILI_KILITLI = N_("Seçili · kilitli")
D_OTO_ACIK = N_("Açık · girişte cüzdan kendiliğinden açılır")
D_OTO_KAPALI = N_("Kapalı")
D_OTO_BEKLIYOR = N_("Uygula'ya basınca açılacak")
D_ARKA_UC_YOK = N_("bu sürümde yok")
D_OKUNMADI = N_("Okunuyor…")

# sorular ve iletiler
S_DEPO_BASLIK = N_("Parola deposu değişsin mi?")
S_DEPO = N_("Parolalar ve ayar koruma anahtarı {yeni} konumuna taşınacak. {eski} artık kullanılmayacak.\n\n"
            "Devam edilsin mi?")
S_OTO_BASLIK = N_("Cüzdan girişte otomatik açılsın mı?")
S_OTO = N_("Oturum açılınca KDE Cüzdanı parola sormadan açılacak. Bu bilgisayarda oturumunuzu açan herkes cüzdandaki "
           "parolalara erişebilir.\n\nDevam edilsin mi?")
S_SIL_BASLIK = N_("Parola silinsin mi?")
S_SIL = N_("\"{ad}\" adlı kayıtlı parola silinecek. Bu geri alınamaz.")
H_PAROLA_GEREKLI = N_("Girişte açmak için cüzdan parolasını yazın.")
H_KAYIT = N_("Kaydedilemedi. Ayrıntıdaki nedene bakıp yeniden deneyin.")
E_BASLIK = N_("Parola ekle")
E_AD = N_("Ad")
E_PAROLA = N_("Parola")
E_TEKRAR = N_("Parola (tekrar)")
E_AD_GECERSIZ = N_("Ad yalnız harf, rakam, nokta, tire ve alt çizgi içerebilir (en çok 64 karakter).")
E_UYUSMUYOR = N_("İki parola aynı değil.")
E_BOS = N_("Parola boş olamaz.")
E_VAR = N_("Bu adla kayıtlı bir parola zaten var.")

KASA, CUZDAN = "kasa", "cuzdan"        # dosya/arka uç sözcükleri (çevrilmez)
_AD_IZINLI = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def ad_gecerli(ad: str) -> bool:
    return 0 < len(ad) <= 64 and set(ad) <= _AD_IZINLI and not ad.startswith(".")


# ---------------------------------------------------------------- arka uç bağlayıcısı
class _ArkaUcYok(Exception):
    pass


class ArkaUc:
    """deskhand.anahtar_deposu + deskhand.cuzdan_ac için ince bağlayıcı. Testler sahte modül verir (depo=, cuzdan=).
    Modül yoksa her çağrı _ArkaUcYok fırlatır → arayüz "kullanılamıyor" gösterir."""

    def __init__(self, depo=None, cuzdan=None):
        self._depo_mod, self._cuzdan_mod = depo, cuzdan

    def _depo(self):
        if self._depo_mod is None:
            try:
                from ... import anahtar_deposu as m
            except ImportError as e:
                raise _ArkaUcYok(str(e)) from None
            self._depo_mod = m
        return self._depo_mod

    def _cuzdan(self):
        if self._cuzdan_mod is None:
            try:
                from ... import cuzdan_ac as m
            except ImportError as e:
                raise _ArkaUcYok(str(e)) from None
            self._cuzdan_mod = m
        return self._cuzdan_mod

    def depo(self):
        return self._depo().secili_depo()

    def depo_durum(self) -> dict:
        return dict(self.depo().durum())

    def depo_degistir(self, tur: str) -> None:
        self._depo().depo_degistir(tur)

    def listele(self) -> list[str]:
        return sorted(self.depo().listele())

    def yaz(self, ad: str, veri: bytes) -> None:
        self.depo().yaz(ad, veri)

    def sil(self, ad: str) -> None:
        self.depo().sil(ad)

    def cuzdan_durum(self) -> dict:
        return dict(self._cuzdan().durum())

    def oto_kur(self, parola: str) -> None:
        self._cuzdan().cuzdan_otomatik_kur(parola)

    def oto_kaldir(self) -> None:
        self._cuzdan().kaldir()


# ---------------------------------------------------------------- görsel parçalar
class Anahtar(QCheckBox):
    """Aç/kapa anahtarı (QCheckBox tabanlı: klavye, erişilebilirlik, toggled sinyali aynı). Renkler paletten
    (tokens.json → QPalette): açık = Highlight izi, kapalı = Mid izi; topuz Base. Metinsiz; ad setAccessibleName."""

    G, Y = 44, 24  # genişlik × yükseklik (tıklama hedefi ≥ 24 px, WCAG 2.5.8)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(self.G, _HEDEF)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.G, _HEDEF)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        grup = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        acik = self.isChecked()
        iz = pal.color(grup, QPalette.ColorRole.Highlight if acik else QPalette.ColorRole.Mid)
        y0 = (self.height() - self.Y) / 2
        r = QRectF(0.5, y0 + 0.5, self.G - 1, self.Y - 1)
        p.setPen(pal.color(grup, QPalette.ColorRole.Dark) if not acik else iz)
        p.setBrush(iz)
        p.drawRoundedRect(r, self.Y / 2, self.Y / 2)
        cap = self.Y - 6
        x = self.G - cap - 3 if acik else 3
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(pal.color(grup, QPalette.ColorRole.HighlightedText if acik else QPalette.ColorRole.WindowText))
        p.drawEllipse(QRectF(x, y0 + 3, cap, cap))
        if self.hasFocus():
            p.setPen(pal.color(grup, QPalette.ColorRole.Highlight))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.5, y0 - 1.5, self.G - 1, self.Y + 3), self.Y / 2 + 2, self.Y / 2 + 2)
        p.end()


def _renkler() -> dict:
    from ..tema.uret import yukle
    return yukle()["durum"]   # tek renk kaynağı: tokens.json (basari/uyari/hata/soluk)


class Rozet(QLabel):
    """Durum rozeti: renkli nokta (token rengi, grafik öğe) + normal renkte sade metin (kontrast metinde)."""

    TURLER = ("basari", "uyari", "hata", "soluk")

    def __init__(self):
        super().__init__()
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        self._tur, self._metin = "soluk", ""

    def ayarla(self, tur: str, metin: str) -> None:
        self._tur, self._metin = (tur if tur in self.TURLER else "soluk"), metin
        renk = _renkler().get(self._tur, "#8a8f98")
        self.setText(f'<span style="color:{renk}">●</span>&nbsp;{html.escape(metin)}')
        self.setAccessibleName(metin)

    def tur(self) -> str:
        return self._tur

    def metin(self) -> str:
        return self._metin


class _Satir(QFrame):
    """Seçenek kartı: [ad / rozet / açıklama] [anahtar]."""

    def __init__(self, mt: Metinler, baslik: str, aciklama: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(_KENAR, _BOSLUK, _KENAR, _BOSLUK)
        lay.setSpacing(_KENAR)
        sol = QVBoxLayout()
        sol.setSpacing(_BOSLUK // 2)
        self.l_ad = QLabel()
        f = self.l_ad.font()
        f.setBold(True)
        self.l_ad.setFont(f)
        mt(self.l_ad.setText, baslik)
        self.rozet = Rozet()
        self.l_not = QLabel()
        self.l_not.setWordWrap(True)
        mt(self.l_not.setText, aciklama)
        for w in (self.l_ad, self.rozet, self.l_not):
            sol.addWidget(w)
        lay.addLayout(sol, 1)
        self.anahtar = Anahtar()
        mt(self.anahtar.setAccessibleName, baslik)
        lay.addWidget(self.anahtar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.ek = QVBoxLayout()            # satıra özel ek alanlar (parola alanı)
        self.ek.setSpacing(_BOSLUK // 2)
        sol.addLayout(self.ek)


class EkleDiyalog(QDialog):
    """Ad + parola + tekrar. Değer yalnız parola() ile bir kez alınır; temizle() iki alanı da boşaltır."""

    def __init__(self, mevcut: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(_(E_BASLIK))
        self._mevcut = set(mevcut)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _KENAR, _KENAR, _KENAR)
        lay.setSpacing(_BOSLUK)
        form = QFormLayout()
        form.setHorizontalSpacing(_BOSLUK * 2)
        form.setVerticalSpacing(_BOSLUK)
        self.e_ad = QLineEdit()
        self.e_ad.setMaxLength(64)
        self.e_p1, self.e_p2 = QLineEdit(), QLineEdit()
        for e, ad in ((self.e_p1, E_PAROLA), (self.e_p2, E_TEKRAR)):
            e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setAccessibleName(_(ad))
        for e in (self.e_ad, self.e_p1, self.e_p2):
            e.setMinimumHeight(_HEDEF)
        self.e_ad.setAccessibleName(_(E_AD))
        form.addRow(_(E_AD), self.e_ad)
        form.addRow(_(E_PAROLA), self.e_p1)
        form.addRow(_(E_TEKRAR), self.e_p2)
        lay.addLayout(form)
        self.l_hata = QLabel("")
        self.l_hata.setWordWrap(True)
        self.l_hata.setVisible(False)
        lay.addWidget(self.l_hata)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._tamam)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.finished.connect(lambda _r: self.temizle() if self.result() != QDialog.DialogCode.Accepted else None)

    def hata(self) -> str:
        ad = self.e_ad.text().strip()
        if not ad_gecerli(ad):
            return _(E_AD_GECERSIZ)
        if ad in self._mevcut:
            return _(E_VAR)
        if not self.e_p1.text():
            return _(E_BOS)
        if self.e_p1.text() != self.e_p2.text():
            return _(E_UYUSMUYOR)
        return ""

    def _tamam(self) -> None:
        h = self.hata()
        self.l_hata.setText(h)
        self.l_hata.setVisible(bool(h))
        if not h:
            self.accept()

    def ad(self) -> str:
        return self.e_ad.text().strip()

    def parola(self) -> str:
        return self.e_p1.text()

    def temizle(self) -> None:
        for e in (self.e_p1, self.e_p2):
            e.clear()


# ---------------------------------------------------------------- grup
class GizliBilgiler(QGroupBox):
    degisti = pyqtSignal()     # kullanıcı bir anahtarı değiştirdi (Ayarlar: "Kaydedilmemiş değişiklikler var")
    yuklendi = pyqtSignal()    # arka uç okundu: kayıtlı taban yenilenmeli

    def __init__(self, mt: Metinler, arka_uc: ArkaUc | None = None, parent=None):
        super().__init__(parent)
        self.mt = mt
        self.au = arka_uc if arka_uc is not None else ArkaUc()
        self._kayitli: tuple = (None, None)      # (depo türü, otomatik açma) — arka uçtan
        self._depo: dict = {}
        self._cuzdan: dict = {}
        self._liste: list[str] = []
        self._okundu = False
        self._yukleniyor = 0
        mt(self.setTitle, G_BASLIK)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _KENAR, _KENAR, _KENAR)
        lay.setSpacing(_BOSLUK)
        giris = QLabel()
        giris.setWordWrap(True)
        mt(giris.setText, G_GIRIS)
        lay.addWidget(giris)

        self.s_kasa = _Satir(mt, G_KASA, G_KASA_NOT)
        self.s_cuzdan = _Satir(mt, G_CUZDAN, G_CUZDAN_NOT)
        self.s_oto = _Satir(mt, G_OTO, G_OTO_NOT)
        self.e_oto = QLineEdit()
        self.e_oto.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_oto.setMinimumHeight(_HEDEF)
        mt(self.e_oto.setPlaceholderText, G_OTO_PAROLA)
        mt(self.e_oto.setAccessibleName, G_OTO_PAROLA)
        self.e_oto.setVisible(False)
        self.s_oto.ek.addWidget(self.e_oto)
        for s in (self.s_kasa, self.s_cuzdan, self.s_oto):
            lay.addWidget(s)
        # kasa ↔ cüzdan: biri açılınca öteki kapanır (depo seçimi tek değer)
        self.s_kasa.anahtar.toggled.connect(lambda d: self._depo_sec(KASA if d else CUZDAN))
        self.s_cuzdan.anahtar.toggled.connect(lambda d: self._depo_sec(CUZDAN if d else KASA))
        self.s_oto.anahtar.toggled.connect(self._oto_degisti)

        self.l_ileti = QLabel("")
        self.l_ileti.setWordWrap(True)
        self.l_ileti.setTextFormat(Qt.TextFormat.PlainText)
        self.l_ileti.setVisible(False)
        lay.addWidget(self.l_ileti)

        # yönlendirme: cüzdan kilitli/yok
        self.w_yon = QWidget()
        yl = QHBoxLayout(self.w_yon)
        yl.setContentsMargins(0, 0, 0, 0)
        yl.setSpacing(_BOSLUK)
        self.l_yon = QLabel()
        self.l_yon.setWordWrap(True)
        mt(self.l_yon.setText, G_YONLENDIR)
        self.b_yonetici = QPushButton()
        self.b_yonetici.setMinimumHeight(_HEDEF)
        mt(self.b_yonetici.setText, G_YONETICI)
        self.b_yonetici.clicked.connect(self.yonetici_ac)
        yl.addWidget(self.l_yon, 1)
        yl.addWidget(self.b_yonetici, 0, Qt.AlignmentFlag.AlignTop)
        self.w_yon.setVisible(False)
        lay.addWidget(self.w_yon)

        # kayıtlı parolalar (yalnız adlar)
        lb = QLabel()
        f = lb.font()
        f.setBold(True)
        lb.setFont(f)
        mt(lb.setText, G_LISTE)
        lay.addWidget(lb)
        self.liste = QListWidget()
        self.liste.setMinimumHeight(96)
        mt(self.liste.setAccessibleName, G_LISTE)
        lay.addWidget(self.liste)
        self.l_bos = QLabel()
        mt(self.l_bos.setText, G_LISTE_BOS)
        lay.addWidget(self.l_bos)
        sat = QHBoxLayout()
        sat.setSpacing(_BOSLUK)
        self.b_ekle, self.b_sil = QPushButton(), QPushButton()
        mt(self.b_ekle.setText, G_EKLE)
        mt(self.b_sil.setText, G_SIL)
        self.b_ekle.clicked.connect(lambda: self.parola_ekle())
        self.b_sil.clicked.connect(lambda: self.secili_sil())
        for b in (self.b_ekle, self.b_sil):
            b.setMinimumHeight(_HEDEF)
            sat.addWidget(b)
        sat.addStretch(1)
        lay.addLayout(sat)
        mt.fn(self._durum_yaz)
        self._etkin()

    # ------------------------------------------------------------ arka uç okuma
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if not self._okundu:
            self.yukle()

    def yukle(self) -> None:
        """Arka ucu oku: depo durumu, cüzdan durumu, parola adları → ekran + kayıtlı taban. Hata → kullanılamıyor."""
        self._okundu = True
        try:
            self._depo = self.au.depo_durum()
        except _ArkaUcYok:
            self._depo = {"tur": None, "hazir": False, "neden": _(D_ARKA_UC_YOK), "tpm": False}
        except Exception as e:  # noqa: BLE001 - panel çökmesin; kapalı-başarısız
            self._depo = {"tur": None, "hazir": False, "neden": T.hata_ozeti(e), "tpm": False}
        try:
            self._cuzdan = self.au.cuzdan_durum()
        except _ArkaUcYok:
            self._cuzdan = {"kurulu": None, "acik": None, "neden": _(D_ARKA_UC_YOK)}
        except Exception as e:  # noqa: BLE001
            self._cuzdan = {"kurulu": None, "acik": None, "neden": T.hata_ozeti(e)}
        try:
            self._liste = self.au.listele() if self._depo.get("hazir") else []
        except Exception:  # noqa: BLE001
            self._liste = []
        tur = self._depo.get("tur") if self._depo.get("tur") in (KASA, CUZDAN) else None
        oto = bool(self._cuzdan.get("kurulu")) if self._cuzdan.get("kurulu") is not None else None
        self._kayitli = (tur, oto)
        self.goster(self._kayitli)
        self._liste_yaz()
        self.yuklendi.emit()

    # ------------------------------------------------------------ değer (Ayarlar kayıt modeli)
    def anlik(self) -> tuple:
        if not self._okundu or self._kayitli[0] is None:
            return self._kayitli
        tur = KASA if self.s_kasa.anahtar.isChecked() else CUZDAN
        oto = self.s_oto.anahtar.isChecked() if self._kayitli[1] is not None else None
        return (tur, oto)

    def kayitli(self) -> tuple:
        return self._kayitli

    def goster(self, deger: tuple) -> None:
        """Anahtarları verilen değere çek (sinyal üretmeden)."""
        tur, oto = deger if deger else (None, None)
        self._yukleniyor += 1
        try:
            for a, v in ((self.s_kasa.anahtar, tur == KASA), (self.s_cuzdan.anahtar, tur == CUZDAN),
                         (self.s_oto.anahtar, bool(oto))):
                a.blockSignals(True)
                a.setChecked(v)
                a.blockSignals(False)
                a.update()
            self.e_oto.clear()
        finally:
            self._yukleniyor -= 1
        self._etkin()
        self._durum_yaz()

    def _depo_sec(self, tur: str) -> None:
        if self._yukleniyor:
            return
        self.goster((tur, self.s_oto.anahtar.isChecked() if self._kayitli[1] is not None else None))
        self.degisti.emit()

    def _oto_degisti(self, _d: bool) -> None:
        if self._yukleniyor:
            return
        if not self.s_oto.anahtar.isChecked():
            self.e_oto.clear()
        self._etkin()
        self._durum_yaz()
        self.degisti.emit()

    def _etkin(self) -> None:
        depo_var = self._kayitli[0] is not None
        for a in (self.s_kasa.anahtar, self.s_cuzdan.anahtar):
            a.setEnabled(depo_var)
        self.s_oto.anahtar.setEnabled(self._kayitli[1] is not None)
        bekleyen_oto = self.s_oto.anahtar.isChecked() and not self._kayitli[1]
        self.e_oto.setVisible(bekleyen_oto)
        hazir = bool(self._depo.get("hazir"))
        self.b_ekle.setEnabled(hazir)
        self.b_sil.setEnabled(hazir and bool(self._liste))

    # ------------------------------------------------------------ durum metinleri
    def _durum_yaz(self) -> None:
        d, c = self._depo, self._cuzdan
        if not self._okundu:
            for s in (self.s_kasa, self.s_cuzdan, self.s_oto):
                s.rozet.ayarla("soluk", _(D_OKUNMADI))
            self.w_yon.setVisible(False)
            return
        secili = d.get("tur")
        neden = d.get("neden") or ""
        # kasa
        if secili == KASA:
            if d.get("hazir"):
                self.s_kasa.rozet.ayarla("basari", _(D_HAZIR_TPM) if d.get("tpm") else _(D_HAZIR))
            else:
                self.s_kasa.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=neden))
        elif secili is None:
            self.s_kasa.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=neden))
        else:
            self.s_kasa.rozet.ayarla("soluk", _(D_KULLANILMIYOR))
        # cüzdan (açık/kilitli cuzdan_ac.durum()["acik"])
        acik = c.get("acik")
        if secili == CUZDAN and not d.get("hazir"):
            self.s_cuzdan.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=neden))
        elif secili == CUZDAN:
            self.s_cuzdan.rozet.ayarla("basari" if acik else "uyari",
                                       _(D_SECILI_ACIK) if acik else _(D_SECILI_KILITLI))
        elif acik is True:
            self.s_cuzdan.rozet.ayarla("soluk", _(D_ACIK))
        elif acik is False:
            self.s_cuzdan.rozet.ayarla("soluk", _(D_KILITLI))
        else:
            self.s_cuzdan.rozet.ayarla("soluk", _(D_BILINMIYOR))
        # girişte aç
        kurulu = c.get("kurulu")
        if kurulu is None:
            self.s_oto.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=c.get("neden") or ""))
        elif self.s_oto.anahtar.isChecked() and not kurulu:
            self.s_oto.rozet.ayarla("uyari", _(D_OTO_BEKLIYOR))
        elif kurulu:
            if c.get("neden"):
                self.s_oto.rozet.ayarla("uyari", _(D_OTO_ACIK) + " · " + str(c.get("neden")))
            else:
                self.s_oto.rozet.ayarla("basari", _(D_OTO_ACIK))
        else:
            self.s_oto.rozet.ayarla("soluk", _(D_OTO_KAPALI))
        istek = self.s_cuzdan.anahtar.isChecked() or self.s_oto.anahtar.isChecked()
        self.w_yon.setVisible(istek and acik is not True)

    def _liste_yaz(self) -> None:
        self.liste.clear()
        self.liste.addItems(self._liste)
        self.liste.setVisible(bool(self._liste))
        self.l_bos.setVisible(not self._liste)
        self._etkin()

    def ileti(self, metin: str) -> None:
        self.l_ileti.setText(metin)
        self.l_ileti.setVisible(bool(metin))

    # ------------------------------------------------------------ sorular (testler değiştirir)
    def onay_sor(self, baslik: str, metin: str) -> bool:
        """Evet/Hayır (varsayılan Hayır)."""
        k = QMessageBox(QMessageBox.Icon.Warning, baslik, metin, QMessageBox.StandardButton.NoButton, self)
        evet = k.addButton(_(T.EVET), QMessageBox.ButtonRole.YesRole)
        hayir = k.addButton(_(T.HAYIR), QMessageBox.ButtonRole.NoRole)
        k.setDefaultButton(hayir)
        k.setEscapeButton(hayir)
        k.exec()
        return k.clickedButton() is evet

    def ekle_diyalogu(self) -> EkleDiyalog | None:
        """Ekle diyaloğu; kabul → diyalog (değer içinde), iptal → None. Testler değiştirir."""
        d = EkleDiyalog(self._liste, self)
        return d if d.exec() == QDialog.DialogCode.Accepted else None

    def yonetici_ac(self) -> bool:
        from PyQt6.QtCore import QProcess
        for ad in ("kwalletmanager6", "kwalletmanager5"):
            yol = shutil.which(ad)
            if yol:
                ok, _pid = QProcess.startDetached(yol, [])
                if ok:
                    return True
        return False

    # ------------------------------------------------------------ Uygula
    def uygula(self) -> tuple[str, str]:
        """Bekleyen depo / otomatik açma değişikliğini yaz → ("tamam" | "red" | "gecersiz" | "hata", ileti).
        Gevşetme (depo değişimi, otomatik açma) önce Evet/Hayır sorar; Hayır → o değer yazılmaz (geri döner)."""
        hedef = self.anlik()
        tur0, oto0 = self._kayitli
        red = False
        self.ileti("")
        try:
            if hedef[0] is not None and hedef[0] != tur0:
                adlar = {KASA: _(G_KASA), CUZDAN: _(G_CUZDAN)}
                if self.onay_sor(_(S_DEPO_BASLIK), _(S_DEPO).format(yeni=adlar[hedef[0]], eski=adlar[tur0])):
                    self.au.depo_degistir(hedef[0])
                else:
                    red = True
            if hedef[1] is not None and hedef[1] != oto0:
                if hedef[1]:
                    if not self.e_oto.text():
                        self.ileti(_(H_PAROLA_GEREKLI))
                        self._yeniden_oku(koru_oto=True)
                        return "gecersiz", _(H_PAROLA_GEREKLI)
                    if self.onay_sor(_(S_OTO_BASLIK), _(S_OTO)):
                        self.au.oto_kur(self.e_oto.text())
                    else:
                        red = True
                else:
                    self.au.oto_kaldir()
        except Exception as e:  # noqa: BLE001 - nedeni sade cümle; parola iletide yok (yalnız istisna türü/özeti)
            self.e_oto.clear()
            self._yeniden_oku()
            ozet = T.hata_ozeti(e)
            self.ileti(_(H_KAYIT) + " " + ozet)
            return "hata", ozet
        self.e_oto.clear()
        self._yeniden_oku()
        return ("red", "") if red else ("tamam", "")

    def _yeniden_oku(self, koru_oto: bool = False) -> None:
        """Arka uçtan yeniden oku; koru_oto → bekleyen 'girişte aç' seçimi ekranda kalsın (parola yazılsın diye)."""
        bekleyen = self.anlik()
        self.yukle()
        if koru_oto and bekleyen[1]:
            self.goster((self._kayitli[0] if bekleyen[0] is None else bekleyen[0], True))

    # ------------------------------------------------------------ parola listesi (hemen yazılır)
    def parola_ekle(self) -> bool:
        d = self.ekle_diyalogu()
        if d is None:
            return False
        try:
            ad = d.ad()
            self.au.yaz(ad, d.parola().encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self.ileti(_(H_KAYIT) + " " + T.hata_ozeti(e))
            return False
        finally:
            d.temizle()
        self.ileti("")
        self._liste_tazele()
        return True

    def secili_sil(self) -> bool:
        it = self.liste.currentItem()
        if it is None:
            return False
        ad = it.text()
        if not self.onay_sor(_(S_SIL_BASLIK), _(S_SIL).format(ad=ad)):
            return False
        try:
            self.au.sil(ad)
        except Exception as e:  # noqa: BLE001
            self.ileti(_(H_KAYIT) + " " + T.hata_ozeti(e))
            return False
        self.ileti("")
        self._liste_tazele()
        return True

    def _liste_tazele(self) -> None:
        try:
            self._liste = self.au.listele()
        except Exception:  # noqa: BLE001
            self._liste = []
        self._liste_yaz()
