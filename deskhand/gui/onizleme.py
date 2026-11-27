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
        # Yazı KARAKTER olarak gider (`type`): arka uç kendi klavye haritasında karakteri üreten tuşu (+Shift/AltGr)
        # bulur. `key i` tuş ADI olarak KEY_I'ye gidiyordu → Türkçe Q düzeninde "ı" çıkıyordu (Devral'da parola!).
        return ["key space" if c == " " else f"type {c}" for c in metin]
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

    def __init__(self, parent=None, oranli: bool = False):
        super().__init__(parent)
        self.oranli = oranli  # True: yükseklik genişlikten (en-boy oranı) → görüntü alanı doldurur, gri bant yok
        self.resim: QImage | None = None
        self.kaynak = QSize(0, 0)  # sanal ekranın gerçek boyutu (koordinat ölçeği)
        self.devral = False
        self.bos_metin = _(T.A_ONIZLEME_YOK)
        self._son_fare = 0.0
        self.setMinimumSize(320, 180)
        pol = QSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Preferred if oranli else QSizePolicy.Policy.Expanding)
        pol.setHeightForWidth(oranli)
        self.setSizePolicy(pol)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)

    def sizeHint(self):  # noqa: N802 - Qt API
        return QSize(800, self.heightForWidth(800) if self.oranli else 450)

    def hasHeightForWidth(self):  # noqa: N802 - Qt API
        return self.oranli

    def heightForWidth(self, w):  # noqa: N802 - Qt API
        g, y = self.kaynak.width(), self.kaynak.height()
        return max(1, round(w * (y / g if g > 0 and y > 0 else 9 / 16)))

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
        eski = QSize(self.kaynak)
        if kaynak is not None:
            self.kaynak = kaynak
        elif resim is not None:
            self.kaynak = resim.size()
        if self.oranli and self.kaynak != eski:
            self.updateGeometry()  # en-boy oranı değişti: yerleşim yüksekliği yeniden hesaplasın
        self.update()

    def paintEvent(self, _e):  # noqa: N802 - Qt API
        p = QPainter(self)
        pal = self.palette()
        bos = self.resim is None or self.resim.isNull()
        if bos or not self.oranli:  # oranlı görünümde görüntünün yanına gri bant boyanmaz (yer kısıtlıysa zemin görünür)
            p.fillRect(self.rect(), pal.color(QPalette.ColorRole.Window).darker(115))
        if bos:
            p.setPen(pal.color(QPalette.ColorRole.PlaceholderText))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.bos_metin)
        else:
            r = self.hedef_rect()
            # küçültmede düzgün (yumuşatma), büyütmede keskin (en yakın piksel: metin bulanıklaşmaz)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                            r.width() * self.devicePixelRatioF() < self.resim.width())
            p.drawImage(r, self.resim)
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


class OnizlemePenceresi(QWidget):
    """"Büyüt": önizlemenin ayrı, büyük penceresi. Kendi karesini ALMAZ: sekmenin maskelenmiş karesini gösterir (yasak
    pencere maskesi burada da aynıdır); girdisi sekmenin girdi yoluna (DUR denetimli) gider."""

    def __init__(self, baslik: str, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        from PyQt6.QtWidgets import QVBoxLayout
        self.setWindowTitle(baslik)
        self.onizleme = Onizleme(self)
        kok = QVBoxLayout(self)
        kok.setContentsMargins(0, 0, 0, 0)
        kok.addWidget(self.onizleme)
        self.resize(1280, 760)


class MaskeHatasi(Exception):
    """Forbidden windows could not be determined: the frame must not be shown (safe side)."""

    def __init__(self, neden):
        super().__init__(str(neden))
        self.mesaj = getattr(neden, "mesaj", None) or str(neden)


def _yasak_pencereler(au, desenler, onb: dict) -> dict:
    """{id: geometry (screen coordinates)} of the forbidden windows. A backend with `maske_pencereleri` (KWin) gives title,
    class and FRAME geometry from one listing; otherwise the class is read per window and cached. A failed class
    read raises (the frame is dropped) and is never cached; an empty class is not cached either (read again next
    frame), so a transient failure cannot leave a window permanently unchecked."""
    liste = getattr(au, "maske_pencereleri", None)
    if liste is not None:
        kayitlar = list(liste())
    else:
        kayitlar = []
        for k, baslik, geo in au.pencereler():
            if k in onb:
                sinif = onb[k]
            elif hasattr(au, "sinif"):
                sinif = au.sinif(k)  # raises → caller drops the frame
                if sinif:
                    onb[k] = sinif
            else:
                sinif = ""
            kayitlar.append((k, baslik, sinif, geo))
    return {k: tuple(geo) for k, baslik, sinif, geo in kayitlar
            if any(d.search(baslik or "") or d.search(sinif or "") for d in desenler)}


def _desenler():
    import re
    from .. import guvenlik
    try:
        from ..onay import YASAK_DESENLER as onay_desen
    except ImportError:
        onay_desen = ()
    return [re.compile(d, re.I) for d in list(guvenlik.yasak_desenler()) + list(onay_desen)]


def _kutulara(au, geolar, im_boyut: tuple[int, int]) -> list[tuple[int, int, int, int]]:
    import math
    W, H = im_boyut
    try:
        x0, y0, x1, y1 = au.ekran_alani()
    except Exception:  # noqa: BLE001 - ekran alanı yok: görüntü = ekran
        x0, y0, x1, y1 = 0, 0, W, H
    fx = W / max(1, x1 - x0)
    fy = H / max(1, y1 - y0)
    sonuc = []
    for X, Y, G, Yk in geolar:
        a, b = max(0, math.floor((X - x0) * fx)), max(0, math.floor((Y - y0) * fy))
        c, e = min(W, math.ceil((X - x0 + G) * fx)), min(H, math.ceil((Y - y0 + Yk) * fy))
        if c > a and e > b and (a, b, c, e) not in sonuc:
            sonuc.append((a, b, c, e))
    return sonuc


def yasak_kutulari(au, im_boyut: tuple[int, int], sinif_onbellek: dict | None = None) -> list[tuple[int, int, int, int]]:
    """Önizleme görüntüsüne düşen YASAK pencerelerin kutuları (görüntü pikseli; x0, y0, x1, y1). Kural api.goruntu_al
    ile aynı: guvenlik.yasak_desenler() + onay.YASAK_DESENLER, başlıkta ya da sınıfta (büyük/küçük harf duyarsız).
    Pencere listesi, desenler ya da bir pencerenin sınıfı okunamazsa istisna YÜKSELİR (çağıran kareyi göstermez:
    güvenli taraf). Arka ucun pencere listesi yoksa (sahte arka uç) []. Salt okur: girdi göndermez."""
    if getattr(au, "pencereler", None) is None:
        return []
    onb = sinif_onbellek if sinif_onbellek is not None else {}
    if len(onb) > 256:
        onb.clear()
    return _kutulara(au, list(_yasak_pencereler(au, _desenler(), onb).values()), im_boyut)


def maskeli_goruntu(au, sinif_onbellek: dict | None = None):
    """Frame of the background desktop with forbidden windows blacked out. The window list is read BEFORE and AFTER
    the grab (maske_kare.iki_okumali_kare, the same guard as the agent path api.goruntu_al) and the union is masked,
    so a window that closes, opens or moves while the frame is taken is still covered at both positions (a closed
    window is masked at its last known place; the agent path drops such a frame instead). Grab errors propagate as
    they are; any masking error is raised as MaskeHatasi (the caller must not show the frame)."""
    if getattr(au, "pencereler", None) is None:
        return au.goruntu()
    from ..maske_kare import ListeOkunamadi, iki_okumali_kare
    onb = sinif_onbellek if sinif_onbellek is not None else {}
    if len(onb) > 256:
        onb.clear()
    try:
        desenler = _desenler()
    except Exception as e:  # noqa: BLE001
        raise MaskeHatasi(e) from e
    try:
        im, geolar, _kapanan = iki_okumali_kare(lambda: _yasak_pencereler(au, desenler, onb), au.goruntu)
    except ListeOkunamadi as e:
        raise MaskeHatasi(e.neden) from e
    try:
        return maskele(im, _kutulara(au, [g for _k, g in geolar], (im.width, im.height)))
    except Exception as e:  # noqa: BLE001
        raise MaskeHatasi(e) from e


def maskele(im, kutular) -> object:
    """Kutuları siyahla örter (kopya üzerinde)."""
    if not kutular:
        return im
    from PIL import ImageDraw
    im = im.copy()
    d = ImageDraw.Draw(im)
    for a, b, c, e in kutular:
        d.rectangle([a, b, c - 1, e - 1], fill=(0, 0, 0))
    return im


def pil_qimage(im, boyut: QSize | None = None) -> tuple[QImage, QSize]:
    """PIL.Image → (QImage, kaynak boyutu). boyut verilirse önce küçültülür (aktarım/çizim ucuz)."""
    kaynak = QSize(im.width, im.height)
    if im.mode != "RGB":
        im = im.convert("RGB")
    if boyut is not None and boyut.width() > 0 and (boyut.width() < im.width or boyut.height() < im.height):
        from PIL import Image
        oran = min(boyut.width() / im.width, boyut.height() / im.height)
        # HAMMING: BILINEAR kadar ucuz (1920x1080→1000x562 ≈5 ms), küçük metinde daha keskin; LANCZOS ≈2x pahalı
        im = im.resize((max(1, int(im.width * oran)), max(1, int(im.height * oran))), Image.Resampling.HAMMING)
    veri = im.tobytes("raw", "RGB")
    q = QImage(veri, im.width, im.height, 3 * im.width, QImage.Format.Format_RGB888).copy()
    return q, kaynak

