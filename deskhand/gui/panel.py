"""Panel denetleyicisi: izleyici + tepsi + pencere + onay diyalogları + genel kısayol + tek örnek."""
from __future__ import annotations

import fcntl
import os
import time

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from .. import guvenlik, onay, yollar
from ..gunluk import gunluk
from ..i18n import _
from . import ayar as A
from . import metinler as T
from .durum import Durum
from .izleyici import Izleyici
from .kisayol import GenelKisayol
from .onay_diyalog import OnayDiyalog
from .pencere import AnaPencere
from .tepsi import Tepsi, durum_simgesi

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIMGE_SVG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "deskhand.svg")


def soket_adi() -> str:
    """Tek örnek soketi (çalışma dizininde: testlerde geçici dizine düşer)."""
    return os.path.join(yollar.runtime_dir(), "panel.sock")


def kilit_adi() -> str:
    return os.path.join(yollar.runtime_dir(), "panel.lock")


def _mesaj_gonder(ad: str, mesaj: bytes, sure_ms: int = 400) -> bool:
    s = QLocalSocket()
    s.connectToServer(ad)
    if not s.waitForConnected(sure_ms):
        return False
    s.write(mesaj)
    s.flush()
    s.waitForBytesWritten(sure_ms)
    s.disconnectFromServer()
    return True


def baska_panel_var() -> bool:
    """Tek örnek kilidini başka bir (canlı) panel tutuyor mu."""
    try:
        with open(kilit_adi(), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def tek_ornek(mesaj: bytes = b"goster\n", deneme_ms: int = 3000) -> QLocalServer | None:
    """Başka panel çalışıyorsa ona `mesaj` gönder → None. Değilse dinleyen sunucu döner.

    Tek örnek ölçütü soket değil, panelin ÖMRÜ boyunca tuttuğu flock kilidi (RUNTIME_DIR/panel.lock; süreç ölünce
    çekirdek bırakır). Böylece meşgul (yanıt veremeyen) ya da henüz açılmakta olan bir panelin soketi silinip ikinci
    panel açılmaz (iki panel → panel.pid ezilir → onaylar "panel yok"/uyuşmaz sayılırdı)."""
    ad = soket_adi()
    os.makedirs(os.path.dirname(ad), mode=0o700, exist_ok=True)
    kilit = open(kilit_adi(), "a")
    try:
        fcntl.flock(kilit, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        kilit.close()
        # başka panel canlı (ya da açılıyor): ona ilet; soketine DOKUNMA
        bitis = time.monotonic() + deneme_ms / 1000
        while not _mesaj_gonder(ad, mesaj) and time.monotonic() < bitis:
            time.sleep(0.1)
        return None
    QLocalServer.removeServer(ad)  # kilit bizde: soket varsa ölü panelden kalmıştır
    sunucu = QLocalServer()
    sunucu.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not sunucu.listen(ad):
        kilit.close()
        return None
    sunucu._kilit = kilit  # sunucu yaşadıkça kilit tutulur
    return sunucu


HATA_BILDIRIM_ARALIK_SN = 30.0  # aynı hata döngüde tekrarlarsa tepsi bildirimi en çok bu sıklıkla


def istisna_yakalayici_kur(panel: "Panel | None" = None) -> None:
    """Panelin genel istisna yakalayıcısı. PyQt6, bir slotta (QTimer, düğme, soket) yakalanmayan istisnada
    sys.excepthook varsayılansa qFatal → SIGABRT ile süreci öldürür (ör. disk dolu: OSError(28) → çıkış 134; panel
    ölünce DUR düğmesi ve onaylar da gider). Burada: istisna günlüğe (ve stderr'e) yazılır, tepsiden kısa bir uyarı
    gösterilir (en çok HATA_BILDIRIM_ARALIK_SN'de bir) ve süreç SÜRER. İş parçacığı istisnaları da günlüğe yazılır."""
    import sys
    import threading
    import traceback

    son = [0.0]

    def yaz(tur, deger, iz, kaynak: str) -> None:
        try:
            metin = "".join(traceback.format_exception(tur, deger, iz))
            sys.stderr.write(metin)
            ozet = f"{tur.__name__}: {deger}"
            gunluk(f"PANEL HATASI ({kaynak}): {ozet} | {metin.strip().splitlines()[-2].strip() if iz else ''}")
            t = getattr(panel, "tepsi", None) if panel is not None else None
            if t is not None and time.monotonic() - son[0] >= HATA_BILDIRIM_ARALIK_SN:
                son[0] = time.monotonic()
                from PyQt6.QtWidgets import QSystemTrayIcon
                t.ikon.showMessage("Deskhand", _(T.P_BEKLENMEYEN_HATA).format(hata=ozet[:200]),
                                   QSystemTrayIcon.MessageIcon.Warning, 8000)
        except Exception:  # noqa: BLE001 - yakalayıcının kendisi asla fırlatmamalı (yoksa PyQt yine abort eder)
            pass

    def kanca(tur, deger, iz):
        if issubclass(tur, KeyboardInterrupt):
            sys.__excepthook__(tur, deger, iz)
            return
        yaz(tur, deger, iz, "slot")

    def is_kanca(a):
        if a.exc_type is SystemExit:
            return
        yaz(a.exc_type, a.exc_value, a.exc_traceback, f"iş parçacığı {getattr(a.thread, 'name', '?')}")

    sys.excepthook = kanca
    threading.excepthook = is_kanca


def uygulama_simgesi() -> QIcon:
    yedek = QIcon(SIMGE_SVG) if os.path.isfile(SIMGE_SVG) else durum_simgesi(Durum())
    return QIcon.fromTheme(onay.PANEL_SINIF, yedek)


class Panel(QObject):
    def __init__(self, app: QApplication, sunucu: QLocalServer | None = None, tepsi: bool = True,
                 izleyici: Izleyici | None = None, kisayol: GenelKisayol | None = None, diyalog_kurma_ms=None,
                 girdi_merkezi: bool = False, **pencere_kw):
        super().__init__()
        self.app = app
        self.merkez = self._merkez_baslat() if girdi_merkezi else None  # gerçek açılışta (gui.__main__) açık
        self.izleyici = izleyici or Izleyici(self)
        self.pencere = AnaPencere(self.izleyici.ilk_satirlar, **pencere_kw)
        self.pencere.setWindowIcon(uygulama_simgesi())
        self.tepsi = Tepsi(self) if tepsi else None
        self.kisayol = kisayol or GenelKisayol(self)
        self.diyaloglar: dict[str, OnayDiyalog] = {}
        self.diyalog_kurma_ms = diyalog_kurma_ms
        self.sunucu = sunucu
        if sunucu is not None:
            sunucu.newConnection.connect(self._baglanti)

        iz = self.izleyici
        iz.satirlar_geldi.connect(self.pencere.satirlar_geldi)
        iz.durum_degisti.connect(self._durum)
        iz.onaylar_degisti.connect(self._onaylar)
        iz.sanal_degisti.connect(self.pencere.arka.sanal_guncelle)
        iz.sanal_degisti.connect(self.pencere.gorev.sanal_guncelle)
        self.pencere.dur_istendi.connect(self.dur)
        self.pencere.devam_istendi.connect(self.devam)
        self.pencere.onaylar.ac_istendi.connect(self.diyalog_one)
        self.pencere.ayarlar.kisayol_degisti.connect(self.kisayol_ayarla)
        self.kisayol.basildi.connect(self.dur)
        self.kisayol.hata.connect(lambda m: self.pencere.ayarlar.kisayol_durumu(_(T.Y_KISAYOL_HATA).format(hata=m)))
        self.pencere.ayarlar.dil_degisti.connect(self.dil_degisti)  # pencere kendini zaten tazeler
        if self.tepsi is not None:
            self.tepsi.dur_istendi.connect(self.dur)
            self.tepsi.devam_istendi.connect(self.devam_sor)  # menüyü plasmashell çizer: doğrudan kaldırma
            self.tepsi.panel_istendi.connect(self.ac_kapat)
            self.tepsi.arka_istendi.connect(self.arka_goster)
            self.tepsi.gorev_istendi.connect(self.gorev_goster)
            self.tepsi.cikis_istendi.connect(self.cik)
            # 0.9.1 (Faz A): bekleyen isteğin tepsi bildirimine tıklamak yalnız paneli ve diyaloğu öne getirir (karar üretmez)
            self.tepsi.onay_istendi.connect(lambda k: (self.goster(), self.diyalog_one(k)))
        app.aboutToQuit.connect(self.kapanis)

        onay.panel_kaydet()
        self._liste_koruma_baslat()
        try:  # önceki (çökmüş / SIGKILL) panelden kalan sahipsiz Devral bayrağı ajanı bekletmesin
            from .durum import devral_sahipsiz_sil
            devral_sahipsiz_sil()
        except Exception:  # noqa: BLE001
            pass
        self._durum(iz.durum)
        self.pencere.arka.sanal_guncelle(iz.sanal)
        self.pencere.gorev.sanal_guncelle(iz.sanal)
        ayarlar = A.panel_oku()
        if ayarlar["kisayol_acik"]:  # yalnız kullanıcı Ayarlar'da açtıysa
            QTimer.singleShot(0, lambda: self.kisayol_ayarla(True, ayarlar["kisayol"]))
        if self.tepsi is not None:
            self.tepsi.goster()

    # -------- yasak/seviye listeleri: panel yetkili kaynak (deskhand/liste_koruma.py)
    LISTE_YOKLA_MS = 2000

    def _liste_koruma_baslat(self):
        from PyQt6.QtCore import QFileSystemWatcher

        from .. import liste_koruma
        self.liste_uyarilari: list[str] = []
        self.koruyucu = liste_koruma.panel_baslat(self._liste_uyari, self._kalici_onayla, self._degisiklik_onayla)
        self._liste_izci = QFileSystemWatcher(self)
        self._liste_izle()
        self._liste_izci.fileChanged.connect(self._liste_degisti)
        self._liste_izci.directoryChanged.connect(self._liste_degisti)
        self._liste_zaman = QTimer(self)  # izleyici silinen dosyayı bırakır / kaçırabilir: düşük sıklıkta yoklama
        self._liste_zaman.setInterval(self.LISTE_YOKLA_MS)
        self._liste_zaman.timeout.connect(self._liste_degisti)
        self._liste_zaman.start()

    def _liste_izle(self):
        from .. import liste_koruma
        istenen = [yollar.config_dir()] + [liste_koruma.dosya(t) for t in liste_koruma.TURLER]
        var = set(self._liste_izci.files()) | set(self._liste_izci.directories())
        yeni = [y for y in istenen if y not in var and os.path.exists(y)]
        if yeni:
            self._liste_izci.addPaths(yeni)

    def _liste_degisti(self, *_a):
        k = getattr(self, "koruyucu", None)
        if k is None:
            return
        k.denetle()
        self._liste_izle()  # geri yazılan dosya yeni inode: yeniden izle

    def _kalici_onayla(self, siteler: list[str]) -> bool:
        """A site was added to [oturum] kalici outside the panel (the user editing ayarlar.toml, or an agent): only
        the user can let it keep its background session (encrypted, 30–365 days). Default answer: No."""
        from PyQt6.QtWidgets import QMessageBox
        metin = _("Görünmez masaüstündeki tarayıcının şu sitelerdeki oturumu kalıcı saklansın mı (şifreli, KDE "
                  "Cüzdanı anahtarıyla; banka/ödeme siteleri hiçbir zaman)?\n\n{siteler}\n\nBu isteği siz "
                  "yapmadıysanız Hayır deyin.").format(siteler="\n".join(siteler))
        cevap = QMessageBox.question(None, "Deskhand — Onay", metin,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        evet = cevap == QMessageBox.StandardButton.Yes
        gunluk(f"kalıcı oturum sitesi onayı: {'evet' if evet else 'hayır'}: {', '.join(siteler)}")
        return evet

    def _degisiklik_onayla(self, tur: str, aciklama: str) -> bool:
        """A panel-authoritative setting changed while the panel was closed (or its mark cannot be verified) in the
        LOOSENING direction (liste_koruma): it is not used until the user says Yes. Default answer: No."""
        from PyQt6.QtWidgets import QMessageBox
        metin = _("Deskhand ayarı panel kapalıyken değişti ya da panelin imzası doğrulanamadı:\n\n{aciklama}\n\n"
                  "Bu değişiklik uygulansın mı? Siz yapmadıysanız Hayır deyin (panelin son kaydı kullanılır)."
                  ).format(aciklama=aciklama)
        cevap = QMessageBox.question(None, "Deskhand — Onay", metin,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        evet = cevap == QMessageBox.StandardButton.Yes
        gunluk(f"panel ayarı değişiklik onayı ({tur}): {'evet' if evet else 'hayır'}")
        return evet

    def _liste_uyari(self, metin: str):
        """Ayar dosyası panel dışında değişti/silindi ve geri yüklendi: günlük satırı (panel penceresinde görünür) +
        tepsi bildirimi."""
        self.liste_uyarilari.append(metin)
        gunluk("UYARI: " + metin)
        if self.tepsi is not None:
            try:
                from PyQt6.QtWidgets import QSystemTrayIcon
                self.tepsi.ikon.showMessage("Deskhand", metin, QSystemTrayIcon.MessageIcon.Warning, 8000)
            except Exception:  # noqa: BLE001 - bildirim isteğe bağlı
                pass

    # -------- girdi merkezi (panel yaşadıkça hazır bekleyen tek dotool; deskhand/girdi_merkezi.py)
    @staticmethod
    def _merkez_baslat():
        from ..arka_uc import kde
        from ..girdi_merkezi import GirdiMerkezi
        if not kde.dotool_var():
            return None  # dotool yok: girdi komutları zaten 9 ile durur
        try:
            return GirdiMerkezi().baslat()
        except OSError as e:  # merkez açılamazsa Girdi kendi dotool'unu açar (eski yol)
            gunluk(f"girdi merkezi başlatılamadı: {e}")
            return None

    def _merkez_durdur(self):
        m, self.merkez = self.merkez, None
        if m is not None:
            m.durdur()  # dotool kapanır: aygıt yok olur, basılı her şey bırakılır

    # -------- DUR / devam (insanın kararı: kaynak "kullanici")
    def dur(self):
        guvenlik.dur_ac("kullanici")
        self.pencere.gorev.durdur()  # çalışan görev varsa o da dursun (ajan DUR hatalarıyla boşuna beklemesin)
        gunluk("DUR anahtarı açıldı (panel)")
        self.izleyici.yenile()

    def devam(self):
        """Panel penceresindeki Devam (yerleşik yasak pencere: ajan tıklayamaz) → DUR kalkar."""
        acikti = guvenlik.dur_kapat("kullanici")
        if acikti:
            gunluk("DUR anahtarı kaldırıldı (panel)")
        self.izleyici.yenile()

    def devam_sor(self):
        """Tepsi menüsündeki Devam: menüyü plasmashell çizer (yasak listesinde değil; bir ajan tıklayabilir).
        DUR doğrudan kalkmaz: panel penceresi açılır ve orada (ajan tıklayamaz) onay sorulur."""
        self.goster()
        self.pencere.devam_sor()

    # -------- durum
    def _durum(self, d: Durum):
        self.pencere.durum_guncelle(d)
        if self.tepsi is not None:
            self.tepsi.guncelle(d)

    # -------- onaylar
    def _onaylar(self, bekleyen: list[dict]):
        kimlikler = {b["id"] for b in bekleyen}
        for k, dlg in list(self.diyaloglar.items()):
            if k not in kimlikler:
                dlg.geri_cekildi()
        for b in bekleyen:
            if b["id"] not in self.diyaloglar:
                self._diyalog_ac(b)
                if self.tepsi is not None:  # tam ekran oyun/film altında kalan diyalog için kalıcı tepsi bildirimi
                    try:
                        self.tepsi.onay_bildir(b)
                    except Exception:  # noqa: BLE001 — bildirim gösterilemese de diyalog açık kalır
                        pass
        self.pencere.onaylar.guncelle(bekleyen)

    def _diyalog_ac(self, istek: dict) -> OnayDiyalog:
        kw = {} if self.diyalog_kurma_ms is None else {"kurma_ms": self.diyalog_kurma_ms}
        dlg = OnayDiyalog(istek, **kw)
        dlg.setWindowIcon(self.pencere.windowIcon())
        dlg.karar_verildi.connect(self._karar)
        dlg.devral_istendi.connect(self.devral_ac)
        self.diyaloglar[istek["id"]] = dlg
        dlg.show()
        dlg.raise_()
        return dlg

    def _masa_sec(self, masa: str) -> None:
        """Panelin Arka plan sekmesini (önizleme, Devral, başlat/durdur) `masa` görünmez masaüstüne çevir ("" =
        varsayılan): pencere.ArkaPlanSekmesi.masa_sec (sekmedeki masaüstü listesi de aynı yolu kullanır)."""
        self.pencere.arka.masa_sec(masa)

    def devral_ac(self, _istek_id: str = ""):
        """İnsan doğrulaması devri: panel Arka plan sekmesinde Devral açılır (önizleme + girdi aktarımı; ajan bekler);
        insan sınamayı çözer, diyalogda Bitti der. Devral'ı panel (yerleşik yasak pencere) açar: ajan açamaz. Sekme
        önce isteğin görünmez masaüstüne çevrilir (adlı masaüstündeki devir de çözülebilsin)."""
        dlg = self.diyaloglar.get(_istek_id)
        masa = (getattr(dlg, "istek", None) or {}).get("masa", "") if dlg is not None else ""
        self.pencere.arka.devir_masa = masa or None  # devrin masaüstünde Devral serbest (yalnız bu devir süresince)
        self._masa_sec(masa)
        self.arka_goster()
        b = self.pencere.arka.b_devral
        if b.isEnabled() and not b.isChecked():
            b.setChecked(True)
            self._devral_acan = _istek_id  # bu diyaloğun açtığı Devral: karar verilince (Bitti/Vazgeç/süre) kapanır

    def diyalog_one(self, istek_id: str):
        dlg = self.diyaloglar.get(istek_id)
        if dlg is not None and not dlg.bitti:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

    def _karar(self, istek_id: str, _neden: str):
        self.diyaloglar.pop(istek_id, None)
        arka = self.pencere.arka
        if arka.devir_masa and not any((getattr(d, "istek", None) or {}).get("masa", "") == arka.devir_masa
                                       for d in self.diyaloglar.values()):
            arka.devir_masa = None  # o masaüstünde bekleyen devir kalmadı: Devral yeniden yalnız varsayılanda
        if getattr(self, "_devral_acan", None) == istek_id:  # devir bitti: Devral açık kalıp ajanı/kullanıcıyı şaşırtmasın
            self._devral_acan = None
            self.pencere.arka.devir_masa = None
            b = self.pencere.arka.b_devral
            if b.isChecked():
                b.setChecked(False)
            self._masa_sec("")  # devir bitti: Arka plan sekmesi varsayılan masaüstüne döner
        QTimer.singleShot(50, self.izleyici.yenile)

    # -------- pencere
    def goster(self):
        self.pencere.show()
        self.pencere.showNormal() if self.pencere.isMinimized() else None
        self.pencere.raise_()
        self.pencere.activateWindow()

    def ac_kapat(self):
        if self.pencere.isVisible() and not self.pencere.isMinimized():
            self.pencere.hide()
        else:
            self.goster()

    def arka_goster(self):
        self.pencere.arka_goster()
        self.goster()

    def gorev_goster(self):
        self.pencere.gorev_goster()
        self.goster()

    def _baglanti(self):
        s = self.sunucu.nextPendingConnection()
        if s is None:
            return

        def oku():
            veri = bytes(s.readAll()).decode(errors="replace").strip()
            if veri == "arka":
                self.arka_goster()
            elif veri == "gorev":
                self.gorev_goster()
            else:
                self.goster()
            s.disconnectFromServer()

        s.readyRead.connect(oku)
        s.disconnected.connect(s.deleteLater)

    # -------- kısayol
    def kisayol_ayarla(self, acik: bool, tus: str):
        try:
            if acik:
                self.kisayol.ac(tus)
                self.pencere.ayarlar.kisayol_durumu(_(T.Y_KISAYOL_TAMAM).format(tus=tus))
            elif self.kisayol.acik:
                self.kisayol.kapat(kaydi_sil=True)
                self.pencere.ayarlar.cakisma_goster()
        except Exception as e:  # noqa: BLE001 - KDE/D-Bus yok: tepsi yeterli
            self.pencere.ayarlar.kisayol_durumu(_(T.Y_KISAYOL_HATA).format(hata=e))

    # -------- dil
    def dil_degisti(self, _kod: str = ""):
        """Ayarlar'da dil değişti (i18n zaten yeniden yüklendi): tepsi + açık onay diyalogları yeni dilde.
        Açık genel kısayolun KDE'deki görünen adı bir sonraki kayıtta (aç/kapat ya da yeniden başlatma) güncellenir."""
        if self.tepsi is not None:
            self.tepsi.tazele()
        for dlg in list(self.diyaloglar.values()):
            if not dlg.bitti:
                dlg.tazele()

    # -------- çıkış
    def _diyaloglari_kapat(self):
        for k in list(self.diyaloglar):
            onay.yanitla(k, "red")  # panel kapanıyor: bekleyen istek açık kalmasın
        for dlg in list(self.diyaloglar.values()):
            dlg.geri_cekildi()
        self.diyaloglar.clear()

    def kapanis(self):
        self.pencere.gorev.kapat()  # çalışan görev panelle birlikte durur
        self._merkez_durdur()  # önce: kapanış sırasında girdi kabul edilmesin
        self._diyaloglari_kapat()
        if self.pencere.arka.b_devral.isChecked():
            self.pencere.arka.b_devral.setChecked(False)  # devral dosyası silinir, girdi kapanır
        from .pencere import isciler_bekle
        isciler_bekle()  # masaüstü durdurma sürüyorsa bitsin (QThread çalışırken yok edilmesin)
        self.izleyici.durdur()
        self.kisayol.kapat(kaydi_sil=False)
        z = getattr(self, "_liste_zaman", None)
        if z is not None:
            z.stop()
        from .. import liste_koruma
        liste_koruma.panel_durdur()
        onay.panel_sil()
        if self.sunucu is not None:
            self.sunucu.close()
            k = getattr(self.sunucu, "_kilit", None)
            if k is not None:
                k.close()  # tek örnek kilidi bırakılır

    def cik(self):
        self._diyaloglari_kapat()
        self.pencere.kapaninca_gizle = False
        self.app.quit()
