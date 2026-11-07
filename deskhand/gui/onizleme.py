"""Arka plan masaüstünün canlı önizlemesi ve "Devral" girdisi.

Önizleme: arka_uc.sec(arka_bayragi=True).goruntu(), ~2 fps, YALNIZ sekme ve pencere görünürken (gizliyken yoklama
yok). Devral açıkken önizleme alanındaki fare/klavye olayları sanal arka ucun Girdi nesnesine (dotool satır dili)
çevrilir: koordinatlar ekran kesrine ölçeklenir (mouseto FX FY), Türkçe karakterler `key ç` gibi tek karakter
tuşu olarak gider (sanal arka uç keysym eşler). Girdi denetle=None ile açılır (insan girdisi: pencere kilidi yok)
ama Girdi.ham() her satırdan önce DUR'a bakar (hata.dur_denetle).
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPalette
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..i18n import _
from . import metinler as T

FARE_ARALIK = 1 / 60  # fare hareketi en çok 60 Hz gönderilir

# Qt tuşu → dotool/Linux tuş adı
_K = Qt.Key
TUS_ADLARI = {
    _K.Key_Return: "enter", _K.Key_Enter: "kpenter", _K.Key_Escape: "esc", _K.Key_Tab: "tab", _K.Key_Backtab: "tab",
    _K.Key_Backspace: "backspace", _K.Key_Delete: "delete", _K.Key_Insert: "insert", _K.Key_Home: "home",
    _K.Key_End: "end", _K.Key_PageUp: "pageup", _K.Key_PageDown: "pagedown", _K.Key_Left: "left",
    _K.Key_Right: "right", _K.Key_Up: "up", _K.Key_Down: "down", _K.Key_Space: "space", _K.Key_Menu: "compose",
    _K.Key_Print: "sysrq", _K.Key_Pause: "pause", _K.Key_CapsLock: "capslock",
    **{getattr(_K, f"Key_F{i}"): f"f{i}" for i in range(1, 13)},
}
DEGISTIRICI_TUSLAR = {_K.Key_Shift, _K.Key_Control, _K.Key_Alt, _K.Key_Meta, _K.Key_AltGr, _K.Key_Super_L,
                      _K.Key_Super_R}
DUGMELER = {Qt.MouseButton.LeftButton: "left", Qt.MouseButton.RightButton: "right",
            Qt.MouseButton.MiddleButton: "middle"}


def _karakter_tusu(c: str) -> str:
    if c == " ":
        return "space"
    if c == "+":
        return "x:plus"  # akor ayırıcısıyla karışmasın
    return c


def tus_satirlari(tus: int, metin: str, mods: Qt.KeyboardModifier) -> list[str]:
    """Qt tuş olayı → dotool satırları ([] = gönderilecek bir şey yok)."""
    tus = Qt.Key(tus) if not isinstance(tus, Qt.Key) else tus
    if tus in DEGISTIRICI_TUSLAR:
        return []
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    if not (ctrl or alt or meta) and metin and tus not in TUS_ADLARI and all(c.isprintable() for c in metin):
        return [f"key {_karakter_tusu(c)}" for c in metin]  # Türkçe/büyük harf: sanal arka uç keysym ile (Shift dahil)
    ad = TUS_ADLARI.get(tus)
    if ad is None:
        v = int(tus.value)
        if 0x41 <= v <= 0x5A:
            ad = chr(v).lower()
        elif 0x30 <= v <= 0x39:
            ad = chr(v)
        elif metin and len(metin) == 1 and metin.isprintable():
            ad = _karakter_tusu(metin.lower())
        else:
            return []
    on = [m for m, var in (("ctrl", ctrl), ("alt", alt), ("super", meta), ("shift", shift or tus == _K.Key_Backtab))
          if var]
    return ["key " + "+".join(on + [ad])]


class Onizleme(QWidget):
    """Görüntüyü en-boy oranını koruyarak ortalar; Devral açıkken girdileri `satir` sinyaliyle bildirir."""
    satirlar = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resim: QImage | None = None
        self.kaynak = QSize(0, 0)  # sanal ekranın gerçek boyutu (koordinat ölçeği)
        self.devral = False
        self.bos_metin = _(T.A_ONIZLEME_YOK)
        self._son_fare = 0.0
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)

    def sizeHint(self):  # noqa: N802 - Qt API
        return QSize(800, 450)

    # -------- görüntü
    def hedef_boyut(self) -> QSize:
        """Görüntünün çizileceği boyut (kaynağı bu boyuta küçültmek yeter)."""
        r = self.hedef_rect()
        return QSize(max(1, int(r.width() * self.devicePixelRatioF())), max(1, int(r.height() * self.devicePixelRatioF())))

    def hedef_rect(self) -> QRectF:
        g, y = self.kaynak.width(), self.kaynak.height()
        if g <= 0 or y <= 0:
            return QRectF(self.rect())
        olcek = min(self.width() / g, self.height() / y)
        w, h = g * olcek, y * olcek
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def goster(self, resim: QImage | None, kaynak: QSize | None = None) -> None:
        self.resim = resim
        if kaynak is not None:
            self.kaynak = kaynak
        elif resim is not None:
            self.kaynak = resim.size()
        self.update()

    def paintEvent(self, _e):  # noqa: N802 - Qt API
        p = QPainter(self)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Window).darker(115))
        if self.resim is None or self.resim.isNull():
            p.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.bos_metin)
        else:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(self.hedef_rect(), self.resim)
        if self.devral:
            kalem = p.pen()
            kalem.setColor(pal.color(QPalette.ColorRole.Highlight))
            kalem.setWidth(3)
            p.setPen(kalem)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.hedef_rect().adjusted(1, 1, -1, -1))
        p.end()

    # -------- koordinat
    def kesir(self, pos: QPointF) -> tuple[float, float] | None:
        r = self.hedef_rect()
        if r.width() <= 0 or r.height() <= 0 or not r.contains(pos):
            return None
        fx = (pos.x() - r.x()) / r.width()
        fy = (pos.y() - r.y()) / r.height()
        return min(max(fx, 0.0), 0.999999), min(max(fy, 0.0), 0.999999)

    def _git(self, pos: QPointF) -> list[str]:
        k = self.kesir(pos)
        return [f"mouseto {k[0]:.6f} {k[1]:.6f}"] if k else []

    # -------- olaylar (yalnız Devral açıkken)
    def mouseMoveEvent(self, e):  # noqa: N802
        if not self.devral:
            return
        t = time.monotonic()
        if t - self._son_fare < FARE_ARALIK and e.buttons() == Qt.MouseButton.NoButton:
            return
        self._son_fare = t
        s = self._git(e.position())
        if s:
            self.satirlar.emit(s)

    def mousePressEvent(self, e):  # noqa: N802
        if not self.devral:
            return super().mousePressEvent(e)
        self.setFocus()
        d = DUGMELER.get(e.button())
        s = self._git(e.position())
        if d and s:
            self.satirlar.emit(s + [f"buttondown {d}"])

    def mouseReleaseEvent(self, e):  # noqa: N802
        if not self.devral:
            return super().mouseReleaseEvent(e)
        d = DUGMELER.get(e.button())
        if d:
            self.satirlar.emit(self._git(e.position()) + [f"buttonup {d}"])

    def wheelEvent(self, e):  # noqa: N802
        if not self.devral:
            return super().wheelEvent(e)
        a = e.angleDelta()
        satir = []
        if a.y():
            satir.append(f"wheel {1 if a.y() > 0 else -1}")
        if a.x():
            satir.append(f"hwheel {1 if a.x() < 0 else -1}")
        if satir:
            self.satirlar.emit(self._git(e.position()) + satir)

    def keyPressEvent(self, e):  # noqa: N802
        if not self.devral:
            return super().keyPressEvent(e)
        s = tus_satirlari(e.key(), e.text(), e.modifiers())
        if s:
            self.satirlar.emit(s)
        e.accept()

    def keyReleaseEvent(self, e):  # noqa: N802
        if not self.devral:
            return super().keyReleaseEvent(e)
        e.accept()

    def focusNextPrevChild(self, ileri):  # noqa: N802 - Devral'da Tab sanal masaüstüne gitsin
        if self.devral:
            return False
        return super().focusNextPrevChild(ileri)


def pil_qimage(im, boyut: QSize | None = None) -> tuple[QImage, QSize]:
    """PIL.Image → (QImage, kaynak boyutu). boyut verilirse önce küçültülür (aktarım/çizim ucuz)."""
    kaynak = QSize(im.width, im.height)
    if im.mode != "RGB":
        im = im.convert("RGB")
    if boyut is not None and boyut.width() > 0 and (boyut.width() < im.width or boyut.height() < im.height):
        from PIL import Image
        oran = min(boyut.width() / im.width, boyut.height() / im.height)
        im = im.resize((max(1, int(im.width * oran)), max(1, int(im.height * oran))), Image.Resampling.BILINEAR)
    veri = im.tobytes("raw", "RGB")
    q = QImage(veri, im.width, im.height, 3 * im.width, QImage.Format.Format_RGB888).copy()
    return q, kaynak

