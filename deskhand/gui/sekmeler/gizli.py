"""Ayarlar › Gelişmiş › "Gizli bilgiler" grubu (anahtar deposu ve KDE Cüzdanı arayüzü).

Yukarıdan aşağı, tek kart dili:
  1. Parolaları nerede sakla: Deskhand kasası (önerilen) / KDE Cüzdanı — biri açıkken öteki kapalı (depo seçimi);
     durum rozeti + kasa için dürüst uyarı.
  2. KDE Cüzdanı kartı: rozet (Açık / Kilitli / Yok) + Cüzdanı aç · Cüzdan parolasını değiştir · Cüzdan Yöneticisi;
     ipucu + "Parolamı bilmiyorum" (3 adımlı yardım penceresi; sıfırlama/silme düğmesi YOK).
  3. Girişte KDE Cüzdanı'nı aç (+ cüzdan parolası gizli alanı; yalnız açılırken).
  4. Kayıtlı parolalar tablosu: Ad · Site/Uygulama · Son değişim (değer ASLA gösterilmez); Ekle / Değiştir / Sil.

Kayıt modeli Ayarlar sekmesininki (UX-A): anahtarlar yalnız ekrandaki değeri değiştirir, Uygula yazar, Sıfırla geri alır.
Depo değişimi ve girişte otomatik açma GEVŞETME sayılır → Uygula'da Evet/Hayır sorusu (varsayılan Hayır). Parola listesi
(Ekle/Değiştir/Sil) kendi diyaloğunda onaylanınca hemen yazılır. Parolalar yalnız QLineEdit(Password) alanından doğrudan
arka uca gider; iş bitince alan temizlenir; günlüğe, ipucuna, hata iletisine yazılmaz.

Cüzdanı açma ve parola değiştirme YALNIZ kullanıcının tıkladığı düğmeden çağrılır (arka plan/MCP/CLI asla); uzun süren
bu çağrılar ayrı iş parçacığında koşar (panel donmaz); iptal ya da zaman aşımı → rozet değişmez, yeniden deneme döngüsü
yok. Arka uç (deskhand.anahtar_deposu, deskhand.cuzdan_ac) ince bir bağlayıcıyla çağrılır: modül ya da işlev yoksa
"kullanılamıyor" gösterilir, düğme gri olur (kapalı-başarısızlık; panel çökmez). Arka uç sekme ilk GÖRÜNDÜĞÜNDE okunur."""
from __future__ import annotations

import html
import os
import threading
import time

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

from ...i18n import N_, _
from .. import metinler as T
from ..dil import Metinler

_BOSLUK, _KENAR, _HEDEF = 8, 12, 28   # ayarlar.py ile aynı aralık birimi / tıklama hedefi
KILIT_SURE_SN = 120                    # cuzdan_ac.kullanici_kilit_ac(zaman_asimi=…)
_PAYLI = 10                            # arka uç kendi süresini aşarsa panel bu kadar sonra vazgeçer
DEGISTIR_SURE_SN = 300                 # KDE parola penceresi açık kalabilir; panel bu süreden sonra beklemez
YONETICI_ADLARI = ("kwalletmanager6", "kwalletmanager5")

# ---------------------------------------------------------------- metinler (iki dilli; en.json)
G_BASLIK = N_("Gizli bilgiler")
G_GIRIS = N_("Deskhand'in sakladığı parolalar ve ayar koruma anahtarı nerede dursun? Seçimi Uygula ile kaydedin.")
G_NEREDE = N_("Parolaları nerede sakla")
G_KASA = N_("Deskhand kasası")
G_KASA_NOT = N_("Önerilen. Parolalar bu bilgisayara kilitli bir dosyada durur; girişte cüzdan sorusu çıkmaz.")
G_KASA_UYARI = N_("Kasa bu bilgisayardaki bir dosyadır: dosyalarınızı silebilen bir program onu silerse kayıtlı "
                  "parolalar kaybolur ve Deskhand siz yeniden onaylayana kadar durur; KDE Cüzdanı buna karşı daha "
                  "dayanıklıdır.")
G_CUZDAN = N_("KDE Cüzdanı")
G_CUZDAN_NOT = N_("Parolalar KDE Cüzdanı'nda durur. Cüzdan kilitliyse Deskhand onu açmaz; siz açana kadar bekler.")
G_OTO = N_("Girişte cüzdanı otomatik aç (soru çıkmaz)")
# otomatik giriş açıkken (oto_giris.otomatik_giris_acik): Girişte aç sorusunda ve panelin cüzdan kartında aynı satır
G_OTO_UYARI = N_("Otomatik giriş açık: bu bilgisayarı açan herkes cüzdandaki parolalara ulaşır.")
G_OTO_NOT = N_("Oturum açılınca cüzdan parola sormadan açılır. Cüzdan parolası bu bilgisayara kilitli olarak saklanır.")
G_OTO_PAROLA = N_("Cüzdan parolası")
G_LISTE = N_("Kayıtlı parolalar")
G_LISTE_BOS = N_("Henüz kayıtlı parola yok. Bir site ya da uygulama için parola eklemek üzere Ekle'ye basın.")
G_EKLE = N_("Ekle…")
G_DEGISTIR = N_("Değiştir…")
G_SIL = N_("Sil")
G_SUTUN_AD = N_("Ad")
G_SUTUN_HEDEF = N_("Site / uygulama")
G_SUTUN_DEGISIM = N_("Son değişim")
G_HEDEF_YOK = N_("Her yerde")

# KDE Cüzdanı kartı
C_KART = N_("KDE Cüzdanı'nı yönet")
C_NOT = N_("Cüzdan parolası çoğunlukla bilgisayara giriş parolanızdır.")
C_AC = N_("Cüzdanı aç")
C_DEGISTIR = N_("Cüzdan parolasını değiştir")
C_YONETICI = N_("Cüzdan Yöneticisi")
C_BILMIYORUM = N_("Parolamı bilmiyorum")
C_YONETICI_YOK = N_("KDE Cüzdan Yöneticisi kurulu değil: kwalletmanager paketi")
C_ACILIYOR = N_("KDE cüzdan parolanızı soruyor…")
C_DEGISIYOR = N_("KDE parola değiştirme penceresi açık…")
C_ACILDI = N_("KDE Cüzdanı açıldı.")
C_ACILMADI = N_("Cüzdan açılmadı (vazgeçildi ya da süre doldu). Durum değişmedi.")
C_DEGISTI = N_("Cüzdan parolası değiştirildi.")
C_DEGISMEDI = N_("Cüzdan parolası değişmedi (vazgeçildi ya da süre doldu).")
C_YONETICI_ACIK = N_("Cüzdan Yöneticisi zaten açık.")
C_ACILAMADI = N_("Açılamadı. Ayrıntıdaki nedene bakıp yeniden deneyin.")

# "Parolamı bilmiyorum" penceresi
B_BASLIK = N_("Cüzdan parolamı bilmiyorum")
B_ADIM1 = N_("1. Bilgisayara giriş parolanızı deneyin")
B_ADIM1_NOT = N_("KDE Cüzdanı genellikle giriş parolanızla açılır. Cüzdanı aç'a basın; KDE parolayı soracak.")
B_ADIM2 = N_("2. Olmadıysa Deskhand kasasına geçin")
B_ADIM2_NOT = N_("Deskhand kasası parola sormaz. Deskhand'in parolaları bundan sonra kasada durur.")
B_ADIM2_ZATEN = N_("Deskhand zaten kasayı kullanıyor.")
B_KASAYA_GEC = N_("Kasaya geç")
B_ADIM3 = N_("3. Giriş parolanızı da bilmiyorsanız")
B_ADIM3_NOT = N_("Kullanıcı ayarlarından giriş parolanızı değiştirin (yönetici izni KDE'de istenir).")
B_KULLANICI = N_("Kullanıcı ayarlarını aç")
B_YONETICI_NOT = N_("Cüzdanları görmek ya da KDE'nin kendi ayarlarını değiştirmek için Cüzdan Yöneticisi'ni açın.")
B_KURTARILAMAZ = N_("Cüzdan parolası kurtarılamaz; eski cüzdan silinmez, parolayı hatırlarsanız yeniden açılır.")
B_KAPAT = N_("Kapat")
H_KASA_SECILDI = N_("Deskhand kasası seçildi. Kaydetmek için Uygula'ya basın.")

# durum rozetleri
D_HAZIR_TPM = N_("Hazır · TPM ile korunuyor")
D_HAZIR = N_("Hazır · bu bilgisayarın anahtarıyla korunuyor")
D_KULLANILMIYOR = N_("Kullanılmıyor")
D_KULLANILAMIYOR = N_("Kullanılamıyor: {neden}")
D_ACIK = N_("Açık")
D_KILITLI = N_("Kilitli")
D_YOK = N_("Yok · bu kullanıcıda KDE Cüzdanı oluşturulmamış")
D_BILINMIYOR = N_("Durumu bilinmiyor")
D_SECILI_ACIK = N_("Seçili · açık")
D_SECILI_KILITLI = N_("Seçili · kilitli")
D_OTO_ACIK = N_("Açık · girişte cüzdan kendiliğinden açılır")
D_OTO_KAPALI = N_("Kapalı")
D_OTO_BEKLIYOR = N_("Uygula'ya basınca açılacak")
D_DEPO_KULLANILACAK = N_("Uygula'ya basınca kullanılacak")
D_DEPO_BIRAKILACAK = N_("Uygula'ya basınca bırakılacak")
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
H_SIR_ISTEGI = N_("Bir görev \"{ad}\" parolasını istedi ama kayıtlı değil. Parolayı buraya kaydedin; görev sonra "
                  "yeniden deneyebilir.")
E_BASLIK = N_("Parola ekle")
E_ONERI = N_("Ajanın önerdiği site (doğrulayın)")
E_ONERI_KULLAN = N_("Bu siteyi kullan")
E_BAG_ZORUNLU = N_("Bu istek için parola bir siteye ya da uygulamaya bağlanmalı: önerilen siteyi doğrulayıp işaretleyin "
                   "ya da siteyi kendiniz yazın.")
E_AD = N_("Ad")
E_PAROLA = N_("Parola")
E_TEKRAR = N_("Parola (tekrar)")
E_SITE = N_("Yalnız bu site (isteğe bağlı)")
E_SITE_IPUCU = N_("ör. ornekbanka.com.tr; alt alan adları dahil")
E_UYGULAMA = N_("Yalnız bu uygulama (isteğe bağlı)")
E_UYGULAMA_IPUCU = N_("pencere sınıfı, ör. firefox")
L_BAGLI = N_("{ad} · yalnız {hedef}")
D_OTO_SONRAKI = N_("Kuruldu · sonraki girişte denenecek")
D_OTO_ERKEN = N_("Kuruldu · bu oturumda cüzdan Deskhand'den önce başlatıldı ve kilitli; sonraki girişte yeniden "
                 "denenecek")
E_AD_GECERSIZ = N_("Ad yalnız harf, rakam, nokta, tire ve alt çizgi içerebilir (en çok 64 karakter).")
E_UYUSMUYOR = N_("İki parola aynı değil.")
E_BOS = N_("Parola boş olamaz.")
E_VAR = N_("Bu adla kayıtlı bir parola zaten var.")
DG_BASLIK = N_("Parolayı değiştir")
DG_BILGI = N_("\"{ad}\" için yeni parolayı yazın. Bağlı olduğu site ya da uygulama değişmez.")
DG_YENI = N_("Yeni parola")

KASA, CUZDAN = "kasa", "cuzdan"        # dosya/arka uç sözcükleri (çevrilmez)
_AD_IZINLI = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
# yardımcı GUI programına (Cüzdan Yöneticisi) temiz ortama EK olarak geçen ekran/oturum değişkenleri (PATH asla)
_GUI_ORTAM = ("HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY",
              "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "LANG", "LANGUAGE")


def site_goster(site: str) -> str:
    """Punycode (xn--) etiketli alan adını çözülmüş + ham hâliyle göster: "gíthub.com (xn--gthub-2qa.com)"."""
    if not site:
        return ""
    try:
        cozulmus = site.encode("ascii").decode("idna") if "xn--" in site.lower() else site
    except (UnicodeError, ValueError):
        cozulmus = site
    return f"{cozulmus} ({site})" if cozulmus != site else site


def ad_gecerli(ad: str) -> bool:
    return 0 < len(ad) <= 64 and set(ad) <= _AD_IZINLI and not ad.startswith(".")


# ---------------------------------------------------------------- arka uç bağlayıcısı
class _ArkaUcYok(Exception):
    pass


class ArkaUc:
    """deskhand.anahtar_deposu + deskhand.cuzdan_ac için ince bağlayıcı. Testler sahte modül verir (depo=, cuzdan=).
    Modül yoksa her çağrı _ArkaUcYok fırlatır → arayüz "kullanılamıyor" gösterir. B1 işlevleri (kullanici_kilit_ac,
    parola_degistir_baslat, cuzdan_durumu, kullanici_ayari_ac, sir_degistir, sir_listesi, yardimci_arac, temiz_ortam)
    getattr ile bulunur: yoksa ilgili düğme gri (destekler())."""

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

    def _islev(self, mod: str, ad: str):
        try:
            m = self._depo() if mod == "depo" else self._cuzdan()
        except _ArkaUcYok:
            return None
        f = getattr(m, ad, None)
        return f if callable(f) else None

    def destekler(self, mod: str, ad: str) -> bool:
        return self._islev(mod, ad) is not None

    def _gerekli(self, mod: str, ad: str):
        f = self._islev(mod, ad)
        if f is None:
            raise _ArkaUcYok(ad)
        return f

    # -- depo
    def depo(self):
        return self._depo().secili_depo()

    def depo_durum(self) -> dict:
        return dict(self.depo().durum())

    def depo_degistir(self, tur: str) -> None:
        self._depo().depo_degistir(tur)

    def listele(self) -> list[str]:
        return sorted(self.depo().listele())

    def yaz(self, ad: str, veri: bytes, uygulama: str | None = None, site: str | None = None) -> None:
        """anahtar_deposu.sir_yaz: the binding (site / window class) is sealed INSIDE the value (never Depo.yaz)."""
        self._depo().sir_yaz(ad, veri, uygulama, site)

    def degistir(self, ad: str, veri: bytes) -> None:
        """anahtar_deposu.sir_degistir: new value only; the site/app binding is kept by the back end."""
        self._gerekli("depo", "sir_degistir")(ad, veri)

    def hedef(self, ad: str) -> dict:
        """{"uygulama", "site"} the secret is bound to ({}: none / unreadable). Never the value."""
        try:
            return dict(self._depo().sir_hedefi_oku(ad))
        except Exception:  # noqa: BLE001 - display only
            return {}

    def sir_listesi(self) -> list[dict]:
        """[{"ad","site","uygulama","degisim"}] — never a value. B1's sir_listesi(), else names + bindings."""
        f = self._islev("depo", "sir_listesi")
        if f is not None:
            sonuc = []
            for o in f():
                o = dict(o)
                if ad_gecerli(str(o.get("ad") or "")):
                    sonuc.append({k: o.get(k) for k in ("ad", "site", "uygulama", "degisim")})
            return sorted(sonuc, key=lambda o: o["ad"])
        return [{"ad": ad, **{k: self.hedef(ad).get(k) for k in ("site", "uygulama")}, "degisim": None}
                for ad in self.listele()]

    def sil(self, ad: str) -> None:
        self.depo().sil(ad)

    def sir_istekleri(self) -> list[dict]:
        """anahtar_deposu.sir_istekleri(): [{"id","tur","ad","site","zaman"}] (değersiz; RUNTIME_DIR/sir-istek)."""
        f = self._islev("depo", "sir_istekleri")
        if f is None:
            return []
        try:
            return [dict(i) for i in f() if isinstance(i, dict)]
        except Exception:  # noqa: BLE001 - istek kanalı okunamadı: bu tur boş
            return []

    def sir_istegi_kapat(self, istek: dict) -> bool:
        """anahtar_deposu.sir_istegi_kapat(id): YALNIZ kimlik gider (sözlük verilirse arka uç False döner)."""
        f = self._islev("depo", "sir_istegi_kapat")
        kimlik = istek.get("id") if isinstance(istek, dict) else None
        if f is None or not isinstance(kimlik, str):
            return False
        try:
            return bool(f(kimlik))
        except Exception:  # noqa: BLE001 - the request expires on its own
            return False

    def yardimci_arac(self, ad: str) -> str | None:
        """Safe absolute path of a helper program (root-owned /usr/bin, /bin) or None. NEVER a PATH search."""
        f = self._islev("depo", "yardimci_arac")
        try:
            if f is not None:
                return f(ad, zorunlu=False)
            from ...arka_ortak import arac
            return arac(ad, zorunlu=False)
        except Exception:  # noqa: BLE001 - not found / unsafe → button disabled
            return None

    def temiz_ortam(self) -> dict:
        """Environment for a helper GUI program: back end's temiz_ortam() (else PATH + session basics) plus the
        display variables a KDE window needs. PATH is always the safe system PATH."""
        from ...arka_ortak import GUVENLI_PATH
        taban: dict = {}
        f = self._islev("depo", "temiz_ortam")
        if f is not None:
            try:
                taban = {str(k): str(v) for k, v in dict(f()).items()}
            except Exception:  # noqa: BLE001
                taban = {}
        for k in _GUI_ORTAM:
            if k in os.environ and k not in taban:
                taban[k] = os.environ[k]
        for k, v in os.environ.items():
            if k.startswith("LC_") and k not in taban:
                taban[k] = v
        taban["PATH"] = GUVENLI_PATH
        return taban

    # -- cüzdan
    def cuzdan_durum(self) -> dict:
        return dict(self._cuzdan().durum())

    def cuzdan_bilgi(self) -> dict | None:
        """B1 cuzdan_durumu() → {"var","kilitli","giris_parolasi_olasi"} or None (not in this version)."""
        f = self._islev("cuzdan", "cuzdan_durumu")
        return dict(f()) if f is not None else None

    def kilit_ac(self, zaman_asimi: int = KILIT_SURE_SN) -> bool:
        return bool(self._gerekli("cuzdan", "kullanici_kilit_ac")(zaman_asimi=zaman_asimi))

    def parola_degistir(self, wid: int) -> bool:
        return bool(self._gerekli("cuzdan", "parola_degistir_baslat")(int(wid)))

    def kullanici_ayari_ac(self) -> bool:
        return bool(self._gerekli("cuzdan", "kullanici_ayari_ac")())

    def oto_kur(self, parola: str) -> None:
        self._cuzdan().cuzdan_otomatik_kur(parola)

    def oto_kaldir(self) -> None:
        self._cuzdan().kaldir()


class _IsSinyal(QObject):
    bitti = pyqtSignal(object, object)   # (sonuç, istisna) — GUI iş parçacığına kuyrukla gelir


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


def _kalin(lb: QLabel) -> QLabel:
    f = lb.font()
    f.setBold(True)
    lb.setFont(f)
    return lb


def _not(mt: Metinler, metin: str) -> QLabel:
    lb = QLabel()
    lb.setWordWrap(True)
    mt(lb.setText, metin)
    return lb


def _dugme(mt: Metinler, metin: str) -> QPushButton:
    b = QPushButton()
    b.setMinimumHeight(_HEDEF)
    mt(b.setText, metin)
    return b


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
        self.l_ad = _kalin(QLabel())
        mt(self.l_ad.setText, baslik)
        self.rozet = Rozet()
        self.l_not = _not(mt, aciklama)
        for w in (self.l_ad, self.rozet, self.l_not):
            sol.addWidget(w)
        lay.addLayout(sol, 1)
        self.anahtar = Anahtar()
        mt(self.anahtar.setAccessibleName, baslik)
        lay.addWidget(self.anahtar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.ek = QVBoxLayout()            # satıra özel ek alanlar (parola alanı, uyarı)
        self.ek.setSpacing(_BOSLUK // 2)
        sol.addLayout(self.ek)


class CuzdanKarti(QFrame):
    """KDE Cüzdanı kartı: ad + rozet + düğmeler + ipucu + "Parolamı bilmiyorum" bağlantısı (düz düğme)."""

    def __init__(self, mt: Metinler):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _BOSLUK, _KENAR, _BOSLUK)
        lay.setSpacing(_BOSLUK // 2)
        self.l_ad = _kalin(QLabel())
        mt(self.l_ad.setText, C_KART)
        self.rozet = Rozet()
        lay.addWidget(self.l_ad)
        lay.addWidget(self.rozet)
        sat = QHBoxLayout()
        sat.setSpacing(_BOSLUK)
        self.b_ac, self.b_degistir, self.b_yonetici = (_dugme(mt, C_AC), _dugme(mt, C_DEGISTIR),
                                                       _dugme(mt, C_YONETICI))
        for b in (self.b_ac, self.b_degistir, self.b_yonetici):
            sat.addWidget(b)
        sat.addStretch(1)
        lay.addLayout(sat)
        self.l_neden = QLabel("")           # gri düğmenin nedeni (ör. kwalletmanager kurulu değil)
        self.l_neden.setWordWrap(True)
        self.l_neden.setTextFormat(Qt.TextFormat.PlainText)
        self.l_neden.setVisible(False)
        lay.addWidget(self.l_neden)
        self.l_not = _not(mt, C_NOT)
        lay.addWidget(self.l_not)
        self.b_bilmiyorum = _dugme(mt, C_BILMIYORUM)
        self.b_bilmiyorum.setFlat(True)
        # bağlantı görünümü: alt çizgi; renk metin rengi (Link rengi kart zemininde 4.2:1, kapı eşiği altında)
        f = self.b_bilmiyorum.font()
        f.setUnderline(True)
        self.b_bilmiyorum.setFont(f)
        self.b_bilmiyorum.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.b_bilmiyorum, 0, Qt.AlignmentFlag.AlignLeft)


class EkleDiyalog(QDialog):
    """Ad + parola + tekrar. Değer yalnız parola() ile bir kez alınır; temizle() iki alanı da boşaltır."""

    def __init__(self, mevcut: list[str], parent=None, ad: str = "", oneri_site: str = ""):
        """oneri_site: ajanın isteğindeki site — ASLA kendiliğinden bağlanmaz; salt okunur gösterilir (punycode
        çözülmüş + ham), kullanıcı "Bu siteyi kullan"ı işaretlerse bağ olur. Öneri varken bağ zorunludur."""
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
        for e, ad_ in ((self.e_p1, E_PAROLA), (self.e_p2, E_TEKRAR)):
            e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setAccessibleName(_(ad_))
        for e in (self.e_ad, self.e_p1, self.e_p2):
            e.setMinimumHeight(_HEDEF)
        self.e_ad.setAccessibleName(_(E_AD))
        self.e_site, self.e_uyg = QLineEdit(), QLineEdit()
        for e, ad_, ipucu in ((self.e_site, E_SITE, E_SITE_IPUCU), (self.e_uyg, E_UYGULAMA, E_UYGULAMA_IPUCU)):
            e.setMaxLength(128)
            e.setMinimumHeight(_HEDEF)
            e.setAccessibleName(_(ad_))
            e.setPlaceholderText(_(ipucu))
        form.addRow(_(E_AD), self.e_ad)
        form.addRow(_(E_PAROLA), self.e_p1)
        form.addRow(_(E_TEKRAR), self.e_p2)
        self._oneri = oneri_site
        self.l_oneri = QLabel(site_goster(oneri_site))
        self.l_oneri.setTextFormat(Qt.TextFormat.PlainText)
        self.l_oneri.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.c_oneri = QCheckBox(_(E_ONERI_KULLAN))
        self.c_oneri.setMinimumHeight(_HEDEF)
        if oneri_site:
            form.addRow(_(E_ONERI), self.l_oneri)
            form.addRow("", self.c_oneri)
        form.addRow(_(E_SITE), self.e_site)
        form.addRow(_(E_UYGULAMA), self.e_uyg)
        lay.addLayout(form)
        self.e_ad.setText(ad)
        if ad:
            self.e_p1.setFocus()
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
        if self._oneri and not (self.site() or self.uygulama()):
            return _(E_BAG_ZORUNLU)
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

    def site(self) -> str | None:
        """Kullanıcının yazdığı site; boşsa YALNIZ işaretlendiyse ajanın önerisi."""
        return self.e_site.text().strip() or (self._oneri if self._oneri and self.c_oneri.isChecked() else None)

    def uygulama(self) -> str | None:
        return self.e_uyg.text().strip() or None

    def temizle(self) -> None:
        for e in (self.e_p1, self.e_p2):
            e.clear()


class DegistirDiyalog(QDialog):
    """Kayıtlı parolayı değiştir: YALNIZ yeni değer + tekrar (ad ve bağ değişmez). temizle() iki alanı boşaltır."""

    def __init__(self, ad: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_(DG_BASLIK))
        self._ad = ad
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _KENAR, _KENAR, _KENAR)
        lay.setSpacing(_BOSLUK)
        bilgi = QLabel(_(DG_BILGI).format(ad=ad))
        bilgi.setWordWrap(True)
        bilgi.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(bilgi)
        form = QFormLayout()
        form.setHorizontalSpacing(_BOSLUK * 2)
        form.setVerticalSpacing(_BOSLUK)
        self.e_p1, self.e_p2 = QLineEdit(), QLineEdit()
        for e, ad_ in ((self.e_p1, DG_YENI), (self.e_p2, E_TEKRAR)):
            e.setEchoMode(QLineEdit.EchoMode.Password)
            e.setMinimumHeight(_HEDEF)
            e.setAccessibleName(_(ad_))
            form.addRow(_(ad_), e)
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
        return self._ad

    def parola(self) -> str:
        return self.e_p1.text()

    def temizle(self) -> None:
        for e in (self.e_p1, self.e_p2):
            e.clear()


class BilmiyorumDiyalog(QDialog):
    """"Parolamı bilmiyorum": 3 adım, sade dil. Sıfırla/sil düğmesi YOK (cüzdanda başka uygulamaların anahtarları var)."""

    def __init__(self, gizli: "GizliBilgiler"):
        super().__init__(gizli)
        self.setWindowTitle(_(B_BASLIK))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _KENAR, _KENAR, _KENAR)
        lay.setSpacing(_BOSLUK)
        mt = gizli.mt

        def adim(baslik, aciklama, dugme):
            kart = QFrame()
            kart.setFrameShape(QFrame.Shape.StyledPanel)
            k = QVBoxLayout(kart)
            k.setContentsMargins(_KENAR, _BOSLUK, _KENAR, _BOSLUK)
            k.setSpacing(_BOSLUK // 2)
            k.addWidget(_kalin(QLabel(_(baslik))))
            n = QLabel(_(aciklama))
            n.setWordWrap(True)
            k.addWidget(n)
            b = _dugme(mt, dugme)
            k.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            lay.addWidget(kart)
            return n, b

        _n1, self.b_ac = adim(B_ADIM1, B_ADIM1_NOT, C_AC)
        self.l_adim2, self.b_kasa = adim(B_ADIM2, B_ADIM2_NOT, B_KASAYA_GEC)
        _n3, self.b_kullanici = adim(B_ADIM3, B_ADIM3_NOT, B_KULLANICI)
        # adım 3'te ayrıca Cüzdan Yöneticisi (kullanıcı 27 Kas: "Deskhand'in içinden açılabilmeli")
        kart3 = self.b_kullanici.parentWidget()
        self.b_yonetici = _dugme(mt, C_YONETICI)
        self.l_yonetici = QLabel(_(B_YONETICI_NOT))
        self.l_yonetici.setWordWrap(True)
        if kart3 is not None and kart3.layout() is not None:
            kart3.layout().addWidget(self.l_yonetici)
            kart3.layout().addWidget(self.b_yonetici, 0, Qt.AlignmentFlag.AlignLeft)
        son = QLabel(_(B_KURTARILAMAZ))
        son.setWordWrap(True)
        lay.addWidget(son)
        bb = QDialogButtonBox()
        kapat = bb.addButton(_(B_KAPAT), QDialogButtonBox.ButtonRole.RejectRole)
        kapat.setMinimumHeight(_HEDEF)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(460)
        # eylemler grubun kendi yollarından (aynı kurallar: kilit yalnız tıklamayla, depo değişimi Uygula'da sorulur)
        self.b_ac.clicked.connect(gizli.cuzdan_ac)
        self.b_kasa.clicked.connect(lambda: (gizli.kasaya_gec(), self.accept()))
        self.b_kullanici.clicked.connect(gizli.kullanici_ayari_ac)
        self.b_yonetici.clicked.connect(gizli.yonetici_ac)
        self.tazele(gizli)

    def tazele(self, gizli: "GizliBilgiler") -> None:
        au = gizli.au
        self.b_ac.setEnabled(gizli.b_cuzdan_ac_etkin())
        zaten = gizli.anlik()[0] == KASA
        self.b_kasa.setEnabled(not zaten and (gizli._kayitli[0] is not None or gizli._secim_bozuk))
        if zaten:
            self.l_adim2.setText(_(B_ADIM2_ZATEN))
        self.b_kullanici.setEnabled(au.destekler("cuzdan", "kullanici_ayari_ac") and "kullanici" not in gizli._isler)
        self.b_yonetici.setEnabled(bool(gizli._yonetici_yol))
        self.l_yonetici.setText(_(B_YONETICI_NOT) if gizli._yonetici_yol else _(C_YONETICI_YOK))


# ---------------------------------------------------------------- grup
class GizliBilgiler(QGroupBox):
    degisti = pyqtSignal()     # kullanıcı bir anahtarı değiştirdi (Ayarlar: "Kaydedilmemiş değişiklikler var")
    yuklendi = pyqtSignal()    # arka uç okundu: kayıtlı taban yenilenmeli
    is_bitti = pyqtSignal(str)  # arka plan işi bitti (ad) — testler ve durum tazeleme için

    def __init__(self, mt: Metinler, arka_uc: ArkaUc | None = None, parent=None):
        super().__init__(parent)
        self.mt = mt
        self.au = arka_uc if arka_uc is not None else ArkaUc()
        self._kayitli: tuple = (None, None)      # (depo türü, otomatik açma) — arka uçtan
        self._depo: dict = {}
        self._cuzdan: dict = {}
        self._bilgi: dict | None = None          # cuzdan_durumu() (B1) ya da None
        self._liste: list[str] = []
        self._kayitlar: list[dict] = []
        self._okundu = False
        self._secim_bozuk = False  # anahtar_deposu: sealed selection ≠ setting (SecimsizDepo) → the user re-selects
        self._yukleniyor = 0
        self._isler: dict[str, object] = {}     # süren arka plan işleri (ad → işaret): aynı iş iki kez başlamaz
        self._yonetici_pid: int | None = None
        self._yonetici_yol: str | None = None
        self._bilmiyorum: BilmiyorumDiyalog | None = None
        mt(self.setTitle, G_BASLIK)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_KENAR, _KENAR, _KENAR, _KENAR)
        lay.setSpacing(_BOSLUK)
        lay.addWidget(_not(mt, G_GIRIS))

        # (1) Parolaları nerede sakla
        lb = _kalin(QLabel())
        mt(lb.setText, G_NEREDE)
        lay.addWidget(lb)
        self.s_kasa = _Satir(mt, G_KASA, G_KASA_NOT)
        self.l_kasa_uyari = _not(mt, G_KASA_UYARI)
        self.s_kasa.ek.addWidget(self.l_kasa_uyari)
        self.s_cuzdan = _Satir(mt, G_CUZDAN, G_CUZDAN_NOT)
        lay.addWidget(self.s_kasa)
        lay.addWidget(self.s_cuzdan)

        # (2) KDE Cüzdanı kartı
        self.k_cuzdan = CuzdanKarti(mt)
        self.b_cuzdan_ac = self.k_cuzdan.b_ac
        self.b_parola_degistir = self.k_cuzdan.b_degistir
        self.b_yonetici = self.k_cuzdan.b_yonetici
        self.b_bilmiyorum = self.k_cuzdan.b_bilmiyorum
        self.b_cuzdan_ac.clicked.connect(self.cuzdan_ac)
        self.b_parola_degistir.clicked.connect(self.cuzdan_parola_degistir)
        self.b_yonetici.clicked.connect(self.yonetici_ac)
        self.b_bilmiyorum.clicked.connect(self.bilmiyorum_ac)
        lay.addWidget(self.k_cuzdan)

        # (3) Girişte cüzdanı aç
        self.s_oto = _Satir(mt, G_OTO, G_OTO_NOT)
        self.e_oto = QLineEdit()
        self.e_oto.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_oto.setMinimumHeight(_HEDEF)
        mt(self.e_oto.setPlaceholderText, G_OTO_PAROLA)
        mt(self.e_oto.setAccessibleName, G_OTO_PAROLA)
        self.e_oto.setVisible(False)
        self.s_oto.ek.addWidget(self.e_oto)
        lay.addWidget(self.s_oto)
        # kasa ↔ cüzdan: biri açılınca öteki kapanır (depo seçimi tek değer)
        self.s_kasa.anahtar.toggled.connect(lambda d: self._depo_sec(KASA if d else CUZDAN))
        self.s_cuzdan.anahtar.toggled.connect(lambda d: self._depo_sec(CUZDAN if d else KASA))
        self.s_oto.anahtar.toggled.connect(self._oto_degisti)

        self.l_ileti = QLabel("")
        self.l_ileti.setWordWrap(True)
        self.l_ileti.setTextFormat(Qt.TextFormat.PlainText)
        self.l_ileti.setVisible(False)
        lay.addWidget(self.l_ileti)

        # (4) kayıtlı parolalar (ad · bağ · son değişim; değer YOK)
        lb = _kalin(QLabel())
        mt(lb.setText, G_LISTE)
        lay.addWidget(lb)
        self.tablo = QTableWidget(0, 3)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tablo.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.setShowGrid(False)
        self.tablo.setAlternatingRowColors(False)
        bas = self.tablo.horizontalHeader()
        bas.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)   # genişlik _ad_sutunu(): içerik, en az 12 harf
        bas.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bas.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        bas.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tablo.setMinimumHeight(120)
        mt(self.tablo.setAccessibleName, G_LISTE)
        mt.fn(lambda: self.tablo.setHorizontalHeaderLabels([_(G_SUTUN_AD), _(G_SUTUN_HEDEF), _(G_SUTUN_DEGISIM)]))
        self.tablo.itemSelectionChanged.connect(self._etkin)
        lay.addWidget(self.tablo)
        self.l_bos = _not(mt, G_LISTE_BOS)
        lay.addWidget(self.l_bos)
        sat = QHBoxLayout()
        sat.setSpacing(_BOSLUK)
        self.b_ekle, self.b_degistir, self.b_sil = _dugme(mt, G_EKLE), _dugme(mt, G_DEGISTIR), _dugme(mt, G_SIL)
        self.b_ekle.clicked.connect(lambda: self.parola_ekle())
        self.b_degistir.clicked.connect(lambda: self.secili_degistir())
        self.b_sil.clicked.connect(lambda: self.secili_sil())
        for b in (self.b_ekle, self.b_degistir, self.b_sil):
            sat.addWidget(b)
        sat.addStretch(1)
        lay.addLayout(sat)
        mt.fn(self._durum_yaz)
        mt.fn(self._liste_yaz)
        self._etkin()

    # ------------------------------------------------------------ arka uç okuma
    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        if not self._okundu:
            self.yukle()

    def yukle(self) -> None:
        """Arka ucu oku: depo durumu, cüzdan durumu, parola listesi → ekran + kayıtlı taban. Hata → kullanılamıyor.
        Cüzdan AÇILMAZ (yalnız durumu okunur)."""
        self._okundu = True
        try:
            self._depo = self.au.depo_durum()
        except _ArkaUcYok:
            self._depo = {"tur": None, "hazir": False, "neden": _(D_ARKA_UC_YOK), "tpm": False}
        except Exception as e:  # noqa: BLE001 - panel çökmesin; kapalı-başarısız
            self._depo = {"tur": None, "hazir": False, "neden": T.hata_ozeti(e), "tpm": False}
        self._cuzdan_oku()
        self._secim_bozuk = self._depo.get("tur") == "dogrulanamadi"
        tur = self._depo.get("tur") if self._depo.get("tur") in (KASA, CUZDAN) else None
        oto = bool(self._cuzdan.get("kurulu")) if self._cuzdan.get("kurulu") is not None else None
        self._kayitli = (tur, oto)
        self.goster(self._kayitli)
        self._liste_tazele()
        self.yuklendi.emit()

    def _cuzdan_oku(self) -> None:
        try:
            self._cuzdan = self.au.cuzdan_durum()
        except _ArkaUcYok:
            self._cuzdan = {"kurulu": None, "acik": None, "neden": _(D_ARKA_UC_YOK)}
        except Exception as e:  # noqa: BLE001
            self._cuzdan = {"kurulu": None, "acik": None, "neden": T.hata_ozeti(e)}
        try:
            self._bilgi = self.au.cuzdan_bilgi()
        except Exception:  # noqa: BLE001 - B1 yok ya da hata: eski durum() alanlarına düşülür
            self._bilgi = None
        self._yonetici_yol = None
        for ad in YONETICI_ADLARI:
            self._yonetici_yol = self.au.yardimci_arac(ad)
            if self._yonetici_yol:
                break

    def cuzdan_acik(self) -> bool | None:
        """True açık · False kilitli · None bilinmiyor/yok."""
        b = self._bilgi
        if b is not None:
            if not b.get("var", True):
                return None
            if b.get("kilitli") is not None:
                return not b.get("kilitli")
        acik = self._cuzdan.get("acik")
        return acik if acik in (True, False) else None

    def cuzdan_var(self) -> bool | None:
        return None if self._bilgi is None or "var" not in self._bilgi else bool(self._bilgi.get("var"))

    # ------------------------------------------------------------ değer (Ayarlar kayıt modeli)
    def anlik(self) -> tuple:
        if not self._okundu or (self._kayitli[0] is None and not self._secim_bozuk):
            return self._kayitli
        tur = KASA if self.s_kasa.anahtar.isChecked() else CUZDAN if self.s_cuzdan.anahtar.isChecked() else None
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

    def b_cuzdan_ac_etkin(self) -> bool:
        return (self._okundu and self.au.destekler("cuzdan", "kullanici_kilit_ac") and "kilit" not in self._isler
                and self.cuzdan_var() is not False and self.cuzdan_acik() is not True)

    def _etkin(self) -> None:
        depo_var = self._kayitli[0] is not None or self._secim_bozuk
        for a in (self.s_kasa.anahtar, self.s_cuzdan.anahtar):
            a.setEnabled(depo_var)
        self.s_oto.anahtar.setEnabled(self._kayitli[1] is not None)
        bekleyen_oto = self.s_oto.anahtar.isChecked() and not self._kayitli[1]
        self.e_oto.setVisible(bekleyen_oto)
        hazir = bool(self._depo.get("hazir"))
        secili = self._secili_ad() is not None
        self.b_ekle.setEnabled(hazir)
        self.b_degistir.setEnabled(hazir and secili and self.au.destekler("depo", "sir_degistir"))
        self.b_sil.setEnabled(hazir and secili)
        # KDE Cüzdanı kartı
        self.b_cuzdan_ac.setEnabled(self.b_cuzdan_ac_etkin())
        self.b_parola_degistir.setEnabled(self._okundu and self.au.destekler("cuzdan", "parola_degistir_baslat")
                                          and "degistir" not in self._isler and self.cuzdan_var() is not False)
        self.b_yonetici.setEnabled(self._okundu and bool(self._yonetici_yol))
        neden = _(C_YONETICI_YOK) if self._okundu and not self._yonetici_yol else ""
        self.k_cuzdan.l_neden.setText(neden)
        self.k_cuzdan.l_neden.setVisible(bool(neden))
        if self._bilmiyorum is not None:
            self._bilmiyorum.tazele(self)

    # ------------------------------------------------------------ durum metinleri
    def _durum_yaz(self) -> None:
        d, c = self._depo, self._cuzdan
        if not self._okundu:
            for r in (self.s_kasa.rozet, self.s_cuzdan.rozet, self.s_oto.rozet, self.k_cuzdan.rozet):
                r.ayarla("soluk", _(D_OKUNMADI))
            return
        secili = d.get("tur")
        neden = d.get("neden") or ""
        # kasa
        if secili == KASA:
            if d.get("hazir"):
                self.s_kasa.rozet.ayarla("basari", _(D_HAZIR_TPM) if d.get("tpm") else _(D_HAZIR))
            else:
                self.s_kasa.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=neden))
        elif secili not in (KASA, CUZDAN):  # no back end, or the selection is not verified (SecimsizDepo)
            self.s_kasa.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=neden))
        else:
            self.s_kasa.rozet.ayarla("soluk", _(D_KULLANILMIYOR))
        # depo olarak cüzdan
        acik = self.cuzdan_acik()
        if secili == CUZDAN and not d.get("hazir"):
            self.s_cuzdan.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=neden))
        elif secili == CUZDAN:
            self.s_cuzdan.rozet.ayarla("basari" if acik else "uyari",
                                       _(D_SECILI_ACIK) if acik else _(D_SECILI_KILITLI))
        else:
            self.s_cuzdan.rozet.ayarla("soluk", _(D_KULLANILMIYOR))
        # anahtar kayıtlı seçimden farklıysa rozet BEKLEYEN durumu söyler (anahtar ile rozet çelişmesin)
        kayitli_tur = self._kayitli[0]
        for satir, tur in ((self.s_kasa, KASA), (self.s_cuzdan, CUZDAN)):
            if not satir.anahtar.isEnabled() and not self._secim_bozuk:
                continue
            simdi = satir.anahtar.isChecked()
            if simdi and kayitli_tur != tur:
                satir.rozet.ayarla("uyari", _(D_DEPO_KULLANILACAK))
            elif not simdi and kayitli_tur == tur:
                satir.rozet.ayarla("uyari", _(D_DEPO_BIRAKILACAK))
        # KDE Cüzdanı kartı (Açık / Kilitli / Yok)
        if self.cuzdan_var() is False:
            self.k_cuzdan.rozet.ayarla("soluk", _(D_YOK))
        elif acik is True:
            self.k_cuzdan.rozet.ayarla("basari", _(D_ACIK))
        elif acik is False:
            self.k_cuzdan.rozet.ayarla("uyari", _(D_KILITLI))
        else:
            self.k_cuzdan.rozet.ayarla("soluk", _(D_BILINMIYOR))
        # girişte aç
        kurulu = c.get("kurulu")
        acik_eski = c.get("acik")
        if kurulu is None:
            self.s_oto.rozet.ayarla("hata", _(D_KULLANILAMIYOR).format(neden=c.get("neden") or ""))
        elif self.s_oto.anahtar.isChecked() and not kurulu:
            self.s_oto.rozet.ayarla("uyari", _(D_OTO_BEKLIYOR))
        elif kurulu:
            # cuzdan_ac.durum(): acik True = open now; False = the wallet runs locked (ksecretd was started before the
            # login unit, or the saved key did not open it); None = not running yet (the unit acts at the next login)
            if acik_eski is True:
                self.s_oto.rozet.ayarla("basari", _(D_OTO_ACIK))
            elif acik_eski is False:
                self.s_oto.rozet.ayarla("uyari", _(D_OTO_ERKEN))
            else:
                self.s_oto.rozet.ayarla("uyari", _(D_OTO_SONRAKI))
        else:
            self.s_oto.rozet.ayarla("soluk", _(D_OTO_KAPALI))

    @staticmethod
    def _tarih(v) -> str:
        if isinstance(v, (int, float)) and v > 0:
            return time.strftime("%d.%m.%Y %H:%M", time.localtime(v))
        if isinstance(v, str) and v:
            return v[:16].replace("T", " ")
        return "—"

    def _liste_yaz(self) -> None:
        secili = self._secili_ad()
        self.tablo.setRowCount(0)
        for o in self._kayitlar:   # ad + bağ + son değişim; değer ASLA
            r = self.tablo.rowCount()
            self.tablo.insertRow(r)
            hedef = " · ".join(str(v) for v in (o.get("site"), o.get("uygulama")) if v) or _(G_HEDEF_YOK)
            for i, metin in enumerate((o["ad"], hedef, self._tarih(o.get("degisim")))):
                it = QTableWidgetItem(metin)
                it.setData(Qt.ItemDataRole.UserRole, o["ad"])
                self.tablo.setItem(r, i, it)
            if o["ad"] == secili:
                self.tablo.selectRow(r)
        self._ad_sutunu()
        self.tablo.setVisible(bool(self._kayitlar))
        self.l_bos.setVisible(not self._kayitlar)
        self._etkin()

    def _ad_sutunu(self) -> None:
        """Ad sütunu içeriğe göre genişler; en az ~12 karakter (kısa adlarda başlık ve satır sıkışmasın)."""
        self.tablo.resizeColumnToContents(0)
        en_az = self.tablo.fontMetrics().horizontalAdvance("M" * 6 + "n" * 6) + 2 * _BOSLUK
        if self.tablo.columnWidth(0) < en_az:
            self.tablo.setColumnWidth(0, en_az)

    def adlar(self) -> list[str]:
        return [self.tablo.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.tablo.rowCount())]

    def satir_metni(self, r: int) -> str:
        return " | ".join(self.tablo.item(r, i).text() for i in range(self.tablo.columnCount()))

    def sec(self, ad: str) -> None:
        for r, a in enumerate(self.adlar()):
            if a == ad:
                self.tablo.selectRow(r)

    def _secili_ad(self) -> str | None:
        if not hasattr(self, "tablo"):
            return None
        satirlar = self.tablo.selectionModel().selectedRows() if self.tablo.selectionModel() else []
        if not satirlar:
            return None
        it = self.tablo.item(satirlar[0].row(), 0)
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def ileti(self, metin: str) -> None:
        self.l_ileti.setText(metin)
        self.l_ileti.setVisible(bool(metin))

    # ------------------------------------------------------------ sorular (testler değiştirir)
    def _oto_giris_acik(self) -> bool:
        """Bu kullanıcı otomatik girişle mi açılıyor (giriş yöneticisinin dosyaları; süreç başlatmaz). Bilinmiyor → False."""
        try:
            from ... import oto_giris
            return oto_giris.otomatik_giris_acik()
        except Exception:  # noqa: BLE001 - yalnız uyarı satırı; panel çökmesin
            return False

    def onay_sor(self, baslik: str, metin: str) -> bool:
        """Evet/Hayır (varsayılan Hayır)."""
        k = QMessageBox(QMessageBox.Icon.Warning, baslik, metin, QMessageBox.StandardButton.NoButton, self)
        evet = k.addButton(_(T.EVET), QMessageBox.ButtonRole.YesRole)
        hayir = k.addButton(_(T.HAYIR), QMessageBox.ButtonRole.NoRole)
        k.setDefaultButton(hayir)
        k.setEscapeButton(hayir)
        k.exec()
        return k.clickedButton() is evet

    def ekle_diyalogu(self, ad: str = "", oneri_site: str = "") -> EkleDiyalog | None:
        """Ekle diyaloğu; kabul → diyalog (değer içinde), iptal → None. Testler değiştirir."""
        d = EkleDiyalog(self._liste, self, ad=ad, oneri_site=oneri_site)
        return d if d.exec() == QDialog.DialogCode.Accepted else None

    def degistir_diyalogu(self, ad: str) -> DegistirDiyalog | None:
        """Değiştir diyaloğu; kabul → diyalog, iptal → None. Testler değiştirir."""
        d = DegistirDiyalog(ad, self)
        return d if d.exec() == QDialog.DialogCode.Accepted else None

    # ------------------------------------------------------------ arka plan işleri (panel donmaz)
    def arka_planda(self, ad: str, fn, geri, sure_sn: float) -> bool:
        """fn() ayrı iş parçacığında; sonuç geri(sonuç, istisna) ile GUI iş parçacığında. sure_sn dolarsa geri(False,
        TimeoutError) ve geç gelen sonuç yok sayılır. Aynı ad sürerken ikinci kez başlamaz (döngü/çift pencere yok)."""
        if ad in self._isler:
            return False
        sinyal = _IsSinyal(self)
        zaman = QTimer(self)
        zaman.setSingleShot(True)
        isaret = object()
        self._isler[ad] = isaret

        def bitir(sonuc, hata):
            if self._isler.get(ad) is not isaret:
                return
            self._isler.pop(ad, None)
            zaman.stop()
            try:
                geri(sonuc, hata)
            finally:
                self._etkin()
                self.is_bitti.emit(ad)

        sinyal.bitti.connect(bitir)
        zaman.timeout.connect(lambda: bitir(False, TimeoutError()))
        zaman.start(int(sure_sn * 1000))

        def kos():
            try:
                r, h = fn(), None
            except Exception as e:  # noqa: BLE001 - GUI iş parçacığında sade ileti olur
                r, h = None, e
            try:
                sinyal.bitti.emit(r, h)
            except RuntimeError:  # grup kapandı
                pass

        threading.Thread(target=kos, name=f"gizli-{ad}", daemon=True).start()
        self._etkin()
        return True

    def cuzdan_ac(self) -> bool:
        """YALNIZ kullanıcı tıklamasından: KDE'nin kendi parola penceresiyle cüzdanı açar. False/iptal/zaman aşımı →
        rozet değişmez; yeniden deneme yok."""
        if not self.b_cuzdan_ac_etkin():
            return False
        self.ileti(_(C_ACILIYOR))

        def geri(sonuc, hata):
            if hata is not None and not isinstance(hata, TimeoutError):
                self.ileti(_(C_ACILAMADI) + " " + T.hata_ozeti(hata))
            elif sonuc is True:
                self._cuzdan_oku()
                self._durum_yaz()
                self.ileti(_(C_ACILDI))
            else:
                self.ileti(_(C_ACILMADI))
        return self.arka_planda("kilit", lambda: self.au.kilit_ac(KILIT_SURE_SN), geri, KILIT_SURE_SN + _PAYLI)

    def cuzdan_parola_degistir(self) -> bool:
        """KDE'nin kendi "parola değiştir" penceresi (parola Deskhand'e gelmez)."""
        if not self.b_parola_degistir.isEnabled():
            return False
        wid = int(self.window().winId()) if self.window() is not None else 0
        self.ileti(_(C_DEGISIYOR))

        def geri(sonuc, hata):
            if hata is not None and not isinstance(hata, TimeoutError):
                self.ileti(_(C_ACILAMADI) + " " + T.hata_ozeti(hata))
            else:
                self.ileti(_(C_DEGISTI) if sonuc is True else _(C_DEGISMEDI))
        return self.arka_planda("degistir", lambda: self.au.parola_degistir(wid), geri, DEGISTIR_SURE_SN)

    def kullanici_ayari_ac(self) -> bool:
        if not self.au.destekler("cuzdan", "kullanici_ayari_ac"):
            return False

        def geri(sonuc, hata):
            if hata is not None or sonuc is not True:
                self.ileti(_(C_ACILAMADI) + (" " + T.hata_ozeti(hata) if hata is not None else ""))
        return self.arka_planda("kullanici", self.au.kullanici_ayari_ac, geri, 30)

    def kasaya_gec(self) -> None:
        """"Parolamı bilmiyorum" adım 2: kasayı SEÇ (bekleyen değişiklik); yazma ve onay sorusu Uygula'da (mevcut yol)."""
        if self.anlik()[0] == KASA or not (self._kayitli[0] is not None or self._secim_bozuk):
            return
        self.s_kasa.anahtar.setChecked(True)
        self.ileti(_(H_KASA_SECILDI))

    def bilmiyorum_diyalogu(self) -> BilmiyorumDiyalog:
        if self._bilmiyorum is None:
            self._bilmiyorum = BilmiyorumDiyalog(self)
            self._bilmiyorum.finished.connect(lambda _r: setattr(self, "_bilmiyorum", None))
        self._bilmiyorum.tazele(self)
        return self._bilmiyorum

    def bilmiyorum_ac(self) -> BilmiyorumDiyalog:
        d = self.bilmiyorum_diyalogu()
        d.show()
        d.raise_()
        return d

    # ------------------------------------------------------------ Cüzdan Yöneticisi (ayrık süreç)
    @staticmethod
    def _yasiyor(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return b"kwalletmanager" in f.read(4096)
        except OSError:
            return False

    def _baslat_ayrik(self, yol: str, ortam: dict) -> int | None:
        """Ayrık süreç (Deskhand beklemez); yalnız verilen ortam. Testler değiştirir (gerçek pencere açılmaz)."""
        p = QProcess()
        p.setProgram(yol)
        p.setArguments([])
        env = QProcessEnvironment()
        for k, v in ortam.items():
            env.insert(k, v)
        p.setProcessEnvironment(env)
        ok, pid = p.startDetached()
        return int(pid) if ok and pid else None

    def yonetici_ac(self) -> bool:
        """kwalletmanager6/5 yalnız yardimci_arac() yolundan (root sahipli /usr/bin; PATH araması YOK), temiz ortam,
        ayrık süreç. Önceki kopya yaşıyorsa ikincisi açılmaz."""
        if self._yasiyor(self._yonetici_pid):
            self.ileti(_(C_YONETICI_ACIK))
            return False
        if not self._okundu:
            self._cuzdan_oku()
        yol = self._yonetici_yol
        if not yol:
            self._etkin()
            return False
        try:
            pid = self._baslat_ayrik(yol, self.au.temiz_ortam())
        except Exception as e:  # noqa: BLE001
            self.ileti(_(C_ACILAMADI) + " " + T.hata_ozeti(e))
            return False
        if pid is None:
            self.ileti(_(C_ACILAMADI))
            return False
        self._yonetici_pid = pid
        self.ileti("")
        return True

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
                if self.onay_sor(_(S_DEPO_BASLIK), _(S_DEPO).format(yeni=adlar[hedef[0]], eski=adlar.get(tur0, _(D_BILINMIYOR)))):
                    self.au.depo_degistir(hedef[0])
                else:
                    red = True
            if hedef[1] is not None and hedef[1] != oto0:
                if hedef[1]:
                    if not self.e_oto.text():
                        self.ileti(_(H_PAROLA_GEREKLI))
                        self._yeniden_oku(koru_oto=True)
                        return "gecersiz", _(H_PAROLA_GEREKLI)
                    soru = _(S_OTO)
                    if self._oto_giris_acik():
                        soru = _(G_OTO_UYARI) + "\n\n" + soru
                    if self.onay_sor(_(S_OTO_BASLIK), soru):
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
    def _ekle_kaydet(self, d: EkleDiyalog) -> bool:
        try:
            self.au.yaz(d.ad(), d.parola().encode("utf-8"), d.uygulama(), d.site())
        except Exception as e:  # noqa: BLE001
            self.ileti(_(H_KAYIT) + " " + T.hata_ozeti(e))
            return False
        finally:
            d.temizle()
        self.ileti("")
        self._liste_tazele()
        return True

    def parola_ekle(self) -> bool:
        d = self.ekle_diyalogu()
        return d is not None and self._ekle_kaydet(d)

    def sir_kaydet_istegi(self, istek: dict) -> bool:
        """anahtar_deposu.sir_istekleri() öğesi {"id","tur":"sir_kaydet","ad","site"} (değersiz): ileti + Ekle formu
        yalnız AD ön dolu; istekteki site yalnız ÖNERİ (salt okunur; kullanıcı işaretlemezse bağlanmaz; bağ zorunlu).
        Kaydedilince ya da kullanıcı vazgeçince istek kapatılır (sir_istegi_kapat(id)). Geçersiz ad → açılmaz."""
        ad = str(istek.get("ad") or "")
        site = str(istek.get("site") or "")[:128]
        if istek.get("tur") != "sir_kaydet" or not ad_gecerli(ad):
            return False
        if not self._okundu:
            self.yukle()
        self.ileti(_(H_SIR_ISTEGI).format(ad=ad))
        if not self._depo.get("hazir"):
            return False
        d = self.ekle_diyalogu(ad=ad, oneri_site=site)
        if d is None:
            self.au.sir_istegi_kapat(istek)   # kullanıcı vazgeçti: istek 24 sa asılı kalmasın
            return False
        if not self._ekle_kaydet(d):
            return False
        self.au.sir_istegi_kapat(istek)
        return True

    def secili_degistir(self) -> bool:
        ad = self._secili_ad()
        if ad is None or not self.au.destekler("depo", "sir_degistir"):
            return False
        d = self.degistir_diyalogu(ad)
        if d is None:
            return False
        try:
            self.au.degistir(ad, d.parola().encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self.ileti(_(H_KAYIT) + " " + T.hata_ozeti(e))
            return False
        finally:
            d.temizle()
        self.ileti("")
        self._liste_tazele()
        return True

    def secili_sil(self) -> bool:
        ad = self._secili_ad()
        if ad is None:
            return False
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
            self._kayitlar = self.au.sir_listesi() if self._depo.get("hazir") else []
        except Exception:  # noqa: BLE001
            self._kayitlar = []
        self._liste = [o["ad"] for o in self._kayitlar]
        self._liste_yaz()
