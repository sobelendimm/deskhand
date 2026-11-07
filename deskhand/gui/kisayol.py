"""Genel kısayolla DUR: KDE KGlobalAccel (org.kde.kglobalaccel) D-Bus API'si, jeepney ile (GLib döngüsü yok).

VARSAYILAN KAPALI: kullanıcı Ayarlar'dan açmadan hiçbir genel kısayol kaydedilmez. Açılınca
`doRegister` + `setShortcut` ile bileşen "deskhand" / eylem "dur" kaydedilir ve
/component/deskhand üzerindeki `globalShortcutPressed` sinyali ayrı bir iş parçacığında dinlenir.
Kapatılınca `unRegister` ile kayıt silinir.

Çakışma denetimi YALNIZ OKUR: ~/.config/kglobalshortcutsrc (ve varsa D-Bus `action(int)` sorgusu).
Meta+Shift+Esc KWin'in "Etkin Giriş Yakalamasını Devre Dışı Bırak" (disableInputCapture) varsayılanıdır; bu yüzden
öneri Meta+Alt+Esc.
"""
from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QKeySequence

from ..i18n import N_, _

BILESEN = "deskhand"
BILESEN_AD = "Deskhand"
EYLEM = "dur"
EYLEM_AD = N_("DUR (tüm girdileri durdur)")  # KDE Sistem Ayarları > Kısayollar'da görünen ad
VARSAYILAN_TUS = "Meta+Alt+Esc"
KAYIT_BAYRAK = 0x2 | 0x4  # SetPresent | NoAutoloading: kullanıcının Ayarlar'da seçtiği tuş geçerli olsun


def kisayol_dosyasi() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kglobalshortcutsrc")


def _normal(tus: str) -> str:
    """'Meta+Shift+Esc' / 'Shift+Meta+Escape' → karşılaştırılabilir biçim (QKeySequence PortableText)."""
    ks = QKeySequence.fromString(tus.strip(), QKeySequence.SequenceFormat.PortableText)
    return ks.toString(QKeySequence.SequenceFormat.PortableText).lower() if not ks.isEmpty() else tus.strip().lower()


def tus_kodu(tus: str) -> int:
    """QKeySequence'in ilk akoru → Qt tamsayı kodu (KGlobalAccel 'ai' biçimi). Boşsa 0."""
    ks = QKeySequence.fromString(tus, QKeySequence.SequenceFormat.PortableText)
    if ks.isEmpty():
        return 0
    return ks[0].toCombined()


def cakismalar(tus: str, yol: str | None = None) -> list[tuple[str, str, str]]:
    """kglobalshortcutsrc'de bu tuşu kullanan eylemler → [(bileşen, eylem, açıklama)]. SALT OKUR.
    Satır biçimi: eylem=etkin\\tikinci,varsayılan,açıklama ("none" = atanmamış)."""
    hedef = _normal(tus)
    sonuc = []
    bolum, ters = "", False
    try:
        with open(yol or kisayol_dosyasi(), encoding="utf-8", errors="replace") as f:
            for satir in f:
                satir = satir.rstrip("\n")
                if satir.startswith("["):
                    bolum = satir.strip("[]").split("][")[0]
                    ters = "$InverseAction" in satir  # ters eylem eşlemesi, tuş değil
                    continue
                if "=" not in satir or satir.startswith("_k_friendly_name") or ters:
                    continue
                anahtar, _, deger = satir.partition("=")
                parcalar = deger.split(",")
                etkin = parcalar[0] if parcalar else ""
                aciklama = parcalar[2] if len(parcalar) > 2 else anahtar
                for t in etkin.split("\t"):
                    if t and t != "none" and _normal(t) == hedef:
                        if bolum == BILESEN and anahtar == EYLEM:
                            continue  # kendi kaydımız
                        sonuc.append((bolum, anahtar, aciklama))
    except OSError:
        pass
    return sonuc


# ---------------------------------------------------------------- D-Bus (jeepney)

def _adres():
    from jeepney import DBusAddress
    return DBusAddress("/kglobalaccel", bus_name="org.kde.kglobalaccel", interface="org.kde.KGlobalAccel")


def _eylem_kimligi() -> list[str]:
    return [BILESEN, EYLEM, BILESEN_AD, _(EYLEM_AD)]


def dbus_cakisma(tus: str) -> list[str] | None:
    """KGlobalAccel'e (salt okuma) sor: bu tuş kimin? → eylem kimliği ya da [] (boş) / None (sorulamadı)."""
    try:
        from jeepney import new_method_call
        from jeepney.io.blocking import open_dbus_connection
        kod = tus_kodu(tus)
        if not kod:
            return None
        with open_dbus_connection(bus="SESSION") as c:
            yanit = c.send_and_get_reply(new_method_call(_adres(), "action", "i", (kod,)), timeout=2)
        k = list(yanit.body[0]) if yanit.body else []
        return [] if (not k or k[:2] == [BILESEN, EYLEM]) else k
    except Exception:  # noqa: BLE001 - KDE yok / D-Bus yok
        return None


class GenelKisayol(QObject):
    """Açıkken genel kısayol basılınca `basildi` sinyali (GUI iş parçacığına kuyruklu)."""
    basildi = pyqtSignal()
    hata = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is: threading.Thread | None = None
        self._dur = threading.Event()
        self._baglanti = None
        self.tus = ""

    @property
    def acik(self) -> bool:
        return self._is is not None and self._is.is_alive()

    def ac(self, tus: str) -> None:
        """Kısayolu KAYDET ve dinlemeye başla (yalnız kullanıcı Ayarlar'da açtığında çağrılır)."""
        self.kapat(kaydi_sil=False)
        from jeepney import MatchRule, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        kod = tus_kodu(tus)
        if not kod:
            raise ValueError(f"geçersiz tuş: {tus!r}")
        c = open_dbus_connection(bus="SESSION")
        try:
            kimlik = _eylem_kimligi()
            c.send_and_get_reply(new_method_call(_adres(), "doRegister", "as", (kimlik,)), timeout=3)
            c.send_and_get_reply(new_method_call(_adres(), "setShortcut", "asaiu", (kimlik, [kod], KAYIT_BAYRAK)),
                                 timeout=3)
            kural = MatchRule(type="signal", interface="org.kde.kglobalaccel.Component",
                              member="globalShortcutPressed", path=f"/component/{BILESEN}")
            from jeepney.bus_messages import message_bus
            c.send_and_get_reply(message_bus.AddMatch(kural), timeout=3)
        except Exception:
            c.close()
            raise
        self._baglanti, self.tus = c, tus
        self._dur = threading.Event()
        self._is = threading.Thread(target=self._dinle, args=(c, kural, self._dur), daemon=True)
        self._is.start()

    def _dinle(self, c, kural, dur: threading.Event) -> None:
        try:
            with c.filter(kural) as kuyruk:
                while not dur.is_set():
                    try:
                        m = c.recv_until_filtered(kuyruk, timeout=0.5)
                    except TimeoutError:
                        continue
                    govde = m.body or ()
                    if len(govde) >= 2 and govde[1] == EYLEM:
                        self.basildi.emit()
        except Exception as e:  # noqa: BLE001
            if not dur.is_set():
                self.hata.emit(str(e))

    def kapat(self, kaydi_sil: bool = True) -> None:
        """Dinlemeyi bırak; kaydi_sil: KDE'deki kaydı da kaldır (Ayarlar'da kapatılınca)."""
        if self._is is not None:
            self._dur.set()
            self._is.join(1.5)
            self._is = None
        c, self._baglanti = self._baglanti, None
        if kaydi_sil:
            try:
                from jeepney import new_method_call
                if c is None:
                    from jeepney.io.blocking import open_dbus_connection
                    c = open_dbus_connection(bus="SESSION")
                c.send_and_get_reply(new_method_call(_adres(), "unRegister", "as", (_eylem_kimligi(),)), timeout=3)
            except Exception:  # noqa: BLE001
                pass
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
