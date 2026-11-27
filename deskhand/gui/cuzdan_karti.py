"""Panel kartı: otomatik giriş + KDE Cüzdanı (plan A2). Durum şeridinin altında, sekmelerin üstünde; modal değil.

Ne zaman görünür: deskhand.oto_giris.kart_durumu() karar verir (otomatik giriş, KDE Cüzdanı var, "girişte aç" kurulu
değil ya da kayıtlı parola son girişte cüzdanı açmadı; bilinmeyen her durumda GİZLİ). Durum ayrı iş parçacığında okunur
(birkaç busctl çağrısı sürebilir): panelin açılışı beklemez; sonuç Qt sinyaliyle gelir.

Seçenekler (kartın düğmesine tıklamak onaydır; ikinci Evet/Hayır sorusu yok, uyarı düğmenin üstünde yazılı):
  1. cüzdan parolası + "Kaydet, bir daha sorulmasın" → gizli.ArkaUc.oto_kur(parola) iş parçacığında; iş sürerken düğme
     gri (çift tık tek çağrı); parola alanı iş başlarken temizlenir; hata iletisi yalnız sade cümle (T.hata_ozeti),
     parola ASLA metinde/ipucunda/günlükte yok. Başarı → "Kuruldu · sonraki girişte denenecek", kart birkaç saniye sonra
     gizlenir.
  2. "Cüzdanı Deskhand için kullanma" → seçili depo KDE Cüzdanı ise depo_degistir("kasa"), sonra oto_giris.kart_kapat().
  "Bir daha gösterme" → kart_kapat(); "×" → yalnız bu panel çalışmasında gizler (işaret yazmaz).
Kart panel penceresinde (YERLESIK_YASAK: ajan tıklayamaz); düğmeleri arka plan / MCP / CLI'dan çağrılmaz
(tests/test_cuzdan_yardim.py kaynak taraması)."""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout

from .. import oto_giris
from ..i18n import N_, _
from . import metinler as T
from .dil import Metinler
from .sekmeler.gizli import (_BOSLUK, _HEDEF, _KENAR, B_KAPAT, D_OTO_SONRAKI, G_OTO_PAROLA, G_OTO_UYARI,
                             H_PAROLA_GEREKLI, ArkaUc, Rozet, _dugme, _kalin, _not)

K_BASLIK_ILK = N_("Girişte KDE Cüzdanı parola soruyor")
K_BASLIK_YENIDEN = N_("Kaydedilen parola cüzdanı açmadı")
K_METIN = N_("Bilgisayarınız parolasız açılıyor, bu yüzden KDE Cüzdanı her girişte parolasını soruyor. Bu soru KDE'den "
             "gelir ve yalnız aşağıdaki ilk seçenekle kalkar.")
K_YENIDEN_NOT = N_("Son girişte kayıtlı parola cüzdanı açmadı; cüzdan parolası değişmiş olabilir. Güncel parolayı yazıp "
                   "yeniden kaydedin.")
K_KAYDET = N_("Kaydet, bir daha sorulmasın")
K_KASA = N_("Cüzdanı Deskhand için kullanma")
K_KASA_NOT = N_("Deskhand parolalarını kendi kasasında tutar; KDE'nin açılış sorusu sürer.")
K_GOSTERME = N_("Bir daha gösterme")
K_DISK_UYARI = N_("Disk şifreli değil: diski söken biri de kayıtlı anahtarı okuyabilir.")
K_KAYDEDILEMEDI = N_("Kaydedilemedi.")
K_KASA_HATA = N_("Kasaya geçilemedi.")
K_ISARET_HATA = N_("Bu seçim kaydedilemedi; kart bir sonraki açılışta yeniden görünebilir.")
VARYANTLAR = ("ilk", "yeniden")


class CuzdanGirisKarti(QFrame):
    """Tek seferlik kart. `goster_durum(d)` (kart_durumu() sözlüğü) görünümü kurar; `yukle()` durumu iş parçacığında
    okur. `bitti(str)`: "kuruldu" | "kasa" | "kapatildi" | "gizlendi"."""

    bitti = pyqtSignal(str)
    _durum_geldi = pyqtSignal(object, object)   # (sözlük, istisna) — iş parçacığından GUI'ye kuyrukla
    _is_bitti = pyqtSignal(str, object)         # (iş adı, istisna)
    GIZLE_MS = 4000

    def __init__(self, mt: Metinler, arka_uc: ArkaUc | None = None, durum_f=None, parent=None):
        super().__init__(parent)
        self.setObjectName("cuzdanGirisKarti")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.mt = mt
        self.au = arka_uc if arka_uc is not None else ArkaUc()
        self._durum_f = durum_f
        self.gizle_ms = self.GIZLE_MS
        self._durum: dict | None = None
        self._okundu = False
        self._yukleniyor = False
        self._kapatildi = False     # × / Bir daha gösterme / iş bitti: bu çalışmada yeniden gösterilmez
        self._is: str | None = None
        self._durum_geldi.connect(self._durum_al)
        self._is_bitti.connect(self._is_sonu)
        self._zaman = QTimer(self)
        self._zaman.setSingleShot(True)
        self._zaman.timeout.connect(self._sure_doldu)
        self._zaman_sinyal: str | None = None   # süre dolunca gönderilecek bitti değeri (işaret yazılamadıysa)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _KENAR, _KENAR, _KENAR)
        lay.setSpacing(_BOSLUK)
        ust = QHBoxLayout()
        ust.setSpacing(_BOSLUK)
        self.l_baslik = _kalin(QLabel())
        self.l_baslik.setWordWrap(True)
        self.l_baslik.setTextFormat(Qt.TextFormat.PlainText)
        ust.addWidget(self.l_baslik, 1)
        self.b_carpi = QToolButton()
        self.b_carpi.setText("×")
        self.b_carpi.setAutoRaise(True)
        self.b_carpi.setFixedSize(_HEDEF, _HEDEF)
        self.b_carpi.setCursor(Qt.CursorShape.PointingHandCursor)
        mt(self.b_carpi.setAccessibleName, B_KAPAT)
        mt(self.b_carpi.setToolTip, B_KAPAT)
        self.b_carpi.clicked.connect(self.carpi)
        ust.addWidget(self.b_carpi, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(ust)
        self.l_metin = QLabel()
        self.l_metin.setWordWrap(True)
        self.l_metin.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.l_metin)

        # seçenek 1: parolayı bir kez gir (uyarı düğmenin ÜSTÜNDE)
        self.u_oto = Rozet()
        self.u_disk = Rozet()
        lay.addWidget(self.u_oto)
        lay.addWidget(self.u_disk)
        sat = QHBoxLayout()
        sat.setSpacing(_BOSLUK)
        self.e_parola = QLineEdit()
        self.e_parola.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_parola.setMinimumHeight(_HEDEF)
        mt(self.e_parola.setPlaceholderText, G_OTO_PAROLA)
        mt(self.e_parola.setAccessibleName, G_OTO_PAROLA)
        self.e_parola.returnPressed.connect(self.kaydet)
        sat.addWidget(self.e_parola, 1)
        self.b_kaydet = _dugme(mt, K_KAYDET)
        self.b_kaydet.clicked.connect(self.kaydet)
        sat.addWidget(self.b_kaydet)
        lay.addLayout(sat)
        self.l_durum = QLabel("")
        self.l_durum.setWordWrap(True)
        self.l_durum.setTextFormat(Qt.TextFormat.PlainText)
        self.l_durum.setVisible(False)
        lay.addWidget(self.l_durum)

        # seçenek 2: cüzdanı Deskhand için kullanma
        sat2 = QHBoxLayout()
        sat2.setSpacing(_BOSLUK)
        self.b_kasa = _dugme(mt, K_KASA)
        self.b_kasa.clicked.connect(self.kasa)
        sat2.addWidget(self.b_kasa)
        sat2.addStretch(1)
        lay.addLayout(sat2)
        self.l_kasa_not = _not(mt, K_KASA_NOT)
        lay.addWidget(self.l_kasa_not)
        self.b_gosterme = _dugme(mt, K_GOSTERME)
        self.b_gosterme.setFlat(True)
        f = self.b_gosterme.font()
        f.setUnderline(True)    # bağlantı görünümü (gizli.CuzdanKarti "Parolamı bilmiyorum" ile aynı)
        self.b_gosterme.setFont(f)
        self.b_gosterme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_gosterme.clicked.connect(self.bir_daha_gosterme)
        lay.addWidget(self.b_gosterme, 0, Qt.AlignmentFlag.AlignLeft)
        self._icerik = (self.l_metin, self.u_oto, self.u_disk, self.e_parola, self.b_kaydet, self.b_kasa,
                        self.l_kasa_not, self.b_gosterme)
        mt.fn(self._metin_yaz)
        self.setVisible(False)

    # ------------------------------------------------------------ durum
    def tazele(self) -> None:
        self.mt.tazele()

    def yukle(self) -> None:
        """kart_durumu()'nu ayrı (daemon) iş parçacığında oku; sonuç _durum_al'a kuyrukla gelir. Panel beklemez."""
        if self._yukleniyor:
            return
        self._yukleniyor = True
        f = self._durum_f or oto_giris.kart_durumu

        def is_():
            try:
                d, e = f(), None
            except BaseException as x:  # noqa: BLE001 - kapalı-başarısız: kart gizli
                d, e = None, x
            try:
                self._durum_geldi.emit(d, e)
            except RuntimeError:  # kart silinmiş (panel kapandı)
                pass
        threading.Thread(target=is_, name="deskhand-cuzdan-karti", daemon=True).start()

    def _durum_al(self, d, e) -> None:
        self._yukleniyor = False
        self._okundu = True
        self.goster_durum(d if e is None and isinstance(d, dict) else {"goster": False})

    def goster_durum(self, d: dict) -> None:
        """kart_durumu() sözlüğünü uygula. goster True değil / bilinmeyen varyant / bu çalışmada kapatıldı → gizli."""
        if self._is is not None:
            return  # iş sürerken görünüm değişmez
        if (self._kapatildi or not isinstance(d, dict) or d.get("goster") is not True
                or d.get("varyant") not in VARYANTLAR):
            self._durum = None
            self.setVisible(False)
            return
        self._durum = dict(d)
        for w in self._icerik:
            w.setVisible(True)
        self.u_disk.setVisible(d.get("disk_sifreli") is False and d.get("tpm") is False)
        self._ileti("")
        self._metin_yaz()
        self.setVisible(True)

    def _metin_yaz(self) -> None:
        yeniden = (self._durum or {}).get("varyant") == "yeniden"
        self.l_baslik.setText(_(K_BASLIK_YENIDEN if yeniden else K_BASLIK_ILK))
        self.l_metin.setText(_(K_METIN) + ("\n" + _(K_YENIDEN_NOT) if yeniden else ""))
        self.u_oto.ayarla("uyari", _(G_OTO_UYARI))
        self.u_disk.ayarla("uyari", _(K_DISK_UYARI))

    def _ileti(self, metin: str) -> None:
        self.l_durum.setText(metin)
        self.l_durum.setVisible(bool(metin))

    # ------------------------------------------------------------ düğmeler (YALNIZ kullanıcının tıklaması)
    def kaydet(self) -> None:
        if self._is is not None:
            return
        parola = self.e_parola.text()
        self.e_parola.clear()
        if not parola:
            self._ileti(_(H_PAROLA_GEREKLI))
            return
        au = self.au
        self._is_baslat("kur", lambda: au.oto_kur(parola))

    def kasa(self) -> None:
        if self._is is not None:
            return
        if (self._durum or {}).get("depo") == "cuzdan":
            au = self.au
            self._is_baslat("kasa", lambda: au.depo_degistir("kasa"))
        else:
            self._isaretle("kasa")

    def bir_daha_gosterme(self) -> None:
        if self._is is None:
            self._isaretle("kapatildi")

    def carpi(self) -> None:
        """Yalnız bu panel çalışmasında gizle; işaret dosyası YAZILMAZ."""
        self._kapat("gizlendi")

    # ------------------------------------------------------------ iç
    def _is_baslat(self, ad: str, fn) -> None:
        self._is = ad
        self._ileti("")
        for w in (self.e_parola, self.b_kaydet, self.b_kasa, self.b_gosterme):
            w.setEnabled(False)

        def is_():
            try:
                fn()
                e = None
            except BaseException as x:  # noqa: BLE001 - nedeni sade cümleyle gösterilir
                e = x
            try:
                self._is_bitti.emit(ad, e)
            except RuntimeError:
                pass
        threading.Thread(target=is_, name=f"deskhand-cuzdan-karti-{ad}", daemon=True).start()

    def _is_sonu(self, ad: str, e) -> None:
        self._is = None
        for w in (self.e_parola, self.b_kaydet, self.b_kasa, self.b_gosterme):
            w.setEnabled(True)
        self.e_parola.clear()
        if e is not None:  # yalnız sade cümle: istisnanın metni (parola içerebilir) gösterilmez
            self._ileti(_(K_KAYDEDILEMEDI if ad == "kur" else K_KASA_HATA) + " " + T.hata_ozeti(e))
            return
        if ad == "kur":
            self._kapatildi = True
            for w in self._icerik:
                w.setVisible(w is self.l_metin)
            self._ileti(_(D_OTO_SONRAKI))
            self.bitti.emit("kuruldu")
            self._zaman.start(self.gizle_ms)
        else:
            self._isaretle("kasa")

    def _isaretle(self, sinyal: str) -> None:
        """Bir daha gösterme işareti; yazılamazsa kart tek satır sade iletiyle kısa süre kalır, sonra gizlenir."""
        try:
            oto_giris.kart_kapat()
        except Exception:  # noqa: BLE001 - panel çökmez; bir sonraki açılışta kart yeniden görünebilir
            self._kapatildi = True
            for w in self._icerik:
                w.setVisible(False)
            self._ileti(_(K_ISARET_HATA))
            self._zaman_sinyal = "gizlendi"
            self._zaman.start(self.gizle_ms)
            return
        self._kapat(sinyal)

    def _sure_doldu(self) -> None:
        self.setVisible(False)
        sinyal, self._zaman_sinyal = self._zaman_sinyal, None
        if sinyal:
            self.bitti.emit(sinyal)

    def _kapat(self, sinyal: str) -> None:
        self._kapatildi = True
        self._zaman.stop()
        self.setVisible(False)
        self.bitti.emit(sinyal)
