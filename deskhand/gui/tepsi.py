"""Tepsi simgesi (QSystemTrayIcon; KDE'de StatusNotifierItem) ve durum simgelerinin çizimi.

Renkler: boşta gri · ekranınızda turuncu · arka planda mavi · DUR kırmızı çarpı · onay bekliyor sarı rozet.
Sol tık: paneli aç/kapat. Menü: DUR / Devam, Görev ver…, Paneli aç, Arka plan ekranını göster, Çık.
Menüdeki "Devam" DUR'u doğrudan KALDIRMAZ (menüyü plasmashell çizer, yasak pencere değildir): panel penceresinde
onay sorulur (Panel.devam_sor).
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..i18n import N_, _
from . import metinler as T
from .dil import Metinler
from .durum import RENK, Durum

BILDIRIM_SINIR = 200
TB_TAMAMI = N_("(tamamı onay penceresinde)")


def bildirim_govdesi(istek: dict) -> str:
    """Tepsi bildirimi gövdesi (UX-C-R1c): devirde isteğin nedeni, diğerlerinde onay iletisinin içerik satırı (temiz,
    gizli yazı/başlık kuralıyla); BILDIRIM_SINIR'ı aşarsa "…" + görünür "(tamamı onay penceresinde)". Bildirimden
    izin VERİLEMEZ (tık yalnız diyaloğu açar), tam metin diyalogda."""
    from .. import guvenlik
    if istek.get("tur") == "devir":
        metin = guvenlik.onay_tek_satir(str(istek.get("ayrinti") or istek.get("eylem") or ""), None)
    else:
        ileti = guvenlik.onay_iletisi(istek)
        metin = ileti["icerik"] or ileti["baslik"]
    if len(metin) > BILDIRIM_SINIR:
        metin = metin[:BILDIRIM_SINIR - 1].rstrip() + "… " + _(TB_TAMAMI)
    return _(T.TB_ONAY_GOVDE).format(neden=metin)


def durum_pixmap(d: Durum, boyut: int = 64) -> QPixmap:
    """Durum simgesi: renkli daire + beyaz işaret (+ onay bekliyorsa sağ üstte sarı rozet)."""
    pm = QPixmap(boyut, boyut)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = boyut
    kenar = s * 0.06
    daire = QRectF(kenar, kenar, s - 2 * kenar, s - 2 * kenar)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(RENK[d.ad]))
    p.drawEllipse(daire)
    beyaz = QColor("#ffffff")
    kalem = QPen(beyaz, s * 0.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    c = s / 2
    if d.ad == "dur":
        p.setPen(kalem)
        r = s * 0.17
        p.drawLine(QPointF(c - r, c - r), QPointF(c + r, c + r))
        p.drawLine(QPointF(c - r, c + r), QPointF(c + r, c - r))
    elif d.ad == "ekran":  # oynat üçgeni: ekranınızda çalışıyor
        yol = QPainterPath()
        yol.moveTo(c - s * 0.12, c - s * 0.18)
        yol.lineTo(c + s * 0.2, c)
        yol.lineTo(c - s * 0.12, c + s * 0.18)
        yol.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(beyaz)
        p.drawPath(yol)
    elif d.ad == "arka":  # üst üste iki ekran: arka planda
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(beyaz, s * 0.065))
        g, y = s * 0.3, s * 0.22
        p.drawRoundedRect(QRectF(c - g / 2 + s * 0.07, c - y / 2 - s * 0.07, g, y), s * 0.03, s * 0.03)
        p.setBrush(QColor(RENK["arka"]))
        p.drawRoundedRect(QRectF(c - g / 2 - s * 0.05, c - y / 2 + s * 0.05, g, y), s * 0.03, s * 0.03)
    else:  # boşta: içi boş halka
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(beyaz, s * 0.08))
        r = s * 0.15
        p.drawEllipse(QPointF(c, c), r, r)
    if d.bekleyen:
        r = s * 0.2
        merkez = QPointF(s - r - kenar * 0.2, r + kenar * 0.2)
        p.setPen(QPen(QColor("#ffffff"), s * 0.04))
        p.setBrush(QColor(RENK["rozet"]))
        p.drawEllipse(merkez, r, r)
        p.setPen(QPen(QColor("#2b2b2b"), s * 0.06, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(merkez.x(), merkez.y() - r * 0.5), QPointF(merkez.x(), merkez.y() + r * 0.12))
        p.drawPoint(QPointF(merkez.x(), merkez.y() + r * 0.5))
    p.end()
    return pm


def durum_simgesi(d: Durum) -> QIcon:
    ikon = QIcon()
    for b in (16, 22, 24, 32, 48, 64):
        ikon.addPixmap(durum_pixmap(d, b))
    return ikon


class Tepsi(QObject):
    """Tepsi simgesi + menü. Eylemleri sinyallerle bildirir; durumu `guncelle(Durum)` ile alır."""
    dur_istendi = pyqtSignal()
    devam_istendi = pyqtSignal()
    panel_istendi = pyqtSignal()        # aç/kapat
    arka_istendi = pyqtSignal()
    gorev_istendi = pyqtSignal()
    cikis_istendi = pyqtSignal()
    onay_istendi = pyqtSignal(str)      # (istek id): kullanıcı tepsi bildirimine tıkladı → panel diyaloğu öne getirir

    def __init__(self, parent=None):
        super().__init__(parent)
        self.durum = Durum()
        self.ikon = QSystemTrayIcon(self)
        self.menu = QMenu()
        self.mt = Metinler()
        self.a_dur, self.a_devam, self.a_gorev, self.a_panel, self.a_arka, self.a_cik = (
            self._eylem(T.M_DUR, self.dur_istendi), self._eylem(T.M_DEVAM, self.devam_istendi),
            self._eylem(T.M_GOREV, self.gorev_istendi),
            self._eylem(T.M_PANEL, self.panel_istendi), self._eylem(T.M_ARKA, self.arka_istendi),
            self._eylem(T.M_CIK, self.cikis_istendi))
        for a in (self.a_dur, self.a_devam):
            self.menu.addAction(a)
        self.menu.addSeparator()
        self.menu.addAction(self.a_gorev)
        self.menu.addAction(self.a_panel)
        self.menu.addAction(self.a_arka)
        self.menu.addSeparator()
        self.menu.addAction(self.a_cik)
        self.ikon.setContextMenu(self.menu)
        self.ikon.activated.connect(self._etkin)
        self.ikon.messageClicked.connect(self._mesaj_tiklandi)
        self._bildirilen = ""
        self.guncelle(self.durum)

    def _eylem(self, msgid: str, sinyal) -> QAction:
        a = QAction(self.menu)
        self.mt(a.setText, msgid)
        a.triggered.connect(sinyal.emit)
        return a

    def tazele(self) -> None:
        """Dil değişti: menü ve ipucu yeni dilde."""
        self.mt.tazele()
        self.guncelle(self.durum)

    def _etkin(self, neden):
        if neden == QSystemTrayIcon.ActivationReason.Trigger:
            self.panel_istendi.emit()

    def guncelle(self, d: Durum) -> None:
        self.durum = d
        self.ikon.setIcon(durum_simgesi(d))
        self.ikon.setToolTip(d.ipucu())
        dur = d.ad == "dur"
        self.a_dur.setVisible(not dur)
        self.a_devam.setVisible(dur)

    def goster(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.ikon.show()

    # -------- bekleyen onay / insan devri bildirimi (0.9.1)
    def onay_bildir(self, istek: dict) -> bool:
        """Panelin KENDİ tepsi bildirimi: yeni bekleyen istek (özellikle insan devri). MCP'nin KDE bildirimi tek yönlüdür
        (düğmesiz: "Tamam" yalnız kapatır); diyalog tam ekran bir pencerenin altında kalırsa kullanıcı isteği bulamıyordu
        (22 Kas). Bu bildirime tıklamak YALNIZ diyaloğu öne getirir (onay_istendi): karar yine diyalogdaki Bitti /
        Vazgeç ile verilir (bildirim plasmashell'de; ajanın tıklayabileceği bir yerden karar çıkmaz). → gösterildi mi."""
        k = str(istek.get("id") or "")
        if not k:
            return False
        self._bildirilen = k
        devir = istek.get("tur") == "devir"
        baslik = _(T.TB_DEVIR_BASLIK if devir else T.TB_ONAY_BASLIK)
        govde = bildirim_govdesi(istek)
        try:
            self.ikon.showMessage(baslik, govde, QSystemTrayIcon.MessageIcon.Warning, 60000)
        except Exception:  # noqa: BLE001 - bildirim isteğe bağlı: diyalog ve panel listesi asıl kanal
            return False
        return True

    def _mesaj_tiklandi(self) -> None:
        k = getattr(self, "_bildirilen", "")
        if k:
            self.onay_istendi.emit(k)
