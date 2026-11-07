"""Sanal arka uç: görünmez ikinci masaüstü (Xvfb + openbox, deskhand/masaustu.py) üzerinde pencere, görüntü, girdi.

Hepsi python-xlib ile süreç İÇİNDE (alt süreç yok): pencere sorguları ~0,1 ms, tüm ekran görüntüsü
(1920x1080) ~5 ms, girdi XTEST. Kullanıcının gerçek ekranına/faresine/klavyesine hiçbir şey gitmez: tek
bağlantı sanal ekranın DISPLAY'idir (:90…).

Girdi dili = dotool satır dili (docs/ARCHITECTURE.md §2). Tuş adları Linux evdev adlarıdır (enter, leftshift,
pageup, f5…; `x:Keysym`, `k:KOD` de olur): Xvfb'nin xkb düzeni evdev kurallı olduğundan X tuş kodu = evdev
kodu + 8 (dotool'la aynı fiziksel tuş). `type` karakteri keysym'e çevirir; düzende olmayanlar (Türkçe
harfler masaüstü açılışında boş tuş kodlarına kalıcı eşlenir) için boş bir tuş kodu GEÇİCİ eşlenir ve
girdi nesnesi kapanınca geri alınır (xdotool yöntemi; geri alma sona bırakılır: uygulama eşlemeyi tuştan
önce okusun).
"""
from __future__ import annotations

import fcntl
import os
import re
import threading
import time
from collections import OrderedDict

from .. import hata, masaustu
from ..hata import (AKTIF_DEGIL, ARAC_EKSIK, BASLIK_SINIF, BELIRSIZ, INSAN, KULLANICI_DUR, PENCERE_YOK,
                    SANAL_KAPALI, Dur)
from ..i18n import _
from . import ARKA_ONEK, EKRAN, ArkaUc

EKRAN_ADLARI = {"ekran", "masaustu", "masaüstü", "tum-ekran", "tüm-ekran"}
ATOMLAR = ("_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW", "_NET_WM_NAME", "UTF8_STRING", "WM_NAME", "WM_CLASS",
           "_NET_CLOSE_WINDOW", "WM_PROTOCOLS", "WM_DELETE_WINDOW", "_NET_SUPPORTING_WM_CHECK", "_NET_WM_PID")
DEVRAL_BEKLE = 8.0  # "Devral" açıkken ilk girdiden önce en çok bu kadar beklenir, sonra 12

# dotool değiştiricileri (akorda) → Linux tuş adı
DEGISTIRICI = {"ctrl": "leftctrl", "shift": "leftshift", "alt": "leftalt", "super": "leftmeta", "altgr": "rightalt"}
TUS_TAKMA = {"return": "enter", "escape": "esc", "page_up": "pageup", "prior": "pageup", "page_down": "pagedown",
             "next": "pagedown", "del": "delete", "ins": "insert", "control": "ctrl", "meta": "super",
             "win": "super", "bksp": "backspace", "print": "sysrq"}
DUGME = {"left": 1, "middle": 2, "right": 3}
# input-event-codes.h yoksa: kod 1..83 sırası + sık kullanılan diğerleri
_YEDEK_SIRA = ("esc 1 2 3 4 5 6 7 8 9 0 minus equal backspace tab q w e r t y u i o p leftbrace rightbrace "
               "enter leftctrl a s d f g h j k l semicolon apostrophe grave leftshift backslash z x c v b n m "
               "comma dot slash rightshift kpasterisk leftalt space capslock f1 f2 f3 f4 f5 f6 f7 f8 f9 f10 "
               "numlock scrolllock kp7 kp8 kp9 kpminus kp4 kp5 kp6 kpplus kp1 kp2 kp3 kp0 kpdot").split()
_YEDEK_EK = {"102nd": 86, "f11": 87, "f12": 88, "kpenter": 96, "rightctrl": 97, "kpslash": 98, "sysrq": 99,
             "rightalt": 100, "home": 102, "up": 103, "pageup": 104, "left": 105, "right": 106, "end": 107,
             "down": 108, "pagedown": 109, "insert": 110, "delete": 111, "mute": 113, "volumedown": 114,
             "volumeup": 115, "pause": 119, "leftmeta": 125, "rightmeta": 126, "compose": 127, "menu": 139}
# Masaüstü açılışında boş tuş kodlarına KALICI eşlenenler (alt düzey, Shift düzeyi): yazarken eşleme yarışı olmasın
KALICI_ESLEME = (("ğ", "Ğ"), ("ü", "Ü"), ("ş", "Ş"), ("ö", "Ö"), ("ç", "Ç"), ("ı", "İ"),
                 ("—", "–"), ("…", "€"), ("“", "”"), ("‘", "’"))

_TUSLAR: dict[str, int] | None = None


def linux_tuslari() -> dict[str, int]:
    """dotool/Linux tuş adı → evdev kodu (linux/input-event-codes.h; yoksa gömülü yedek)."""
    global _TUSLAR
    if _TUSLAR is not None:
        return _TUSLAR
    t: dict[str, int] = {}
    try:
        with open("/usr/include/linux/input-event-codes.h") as f:
            tanim = re.findall(r"^#define\s+KEY_(\w+)\s+(\S+)", f.read(), re.M)
        ham = dict(tanim)
        for ad, deger in tanim:
            for _ in range(4):  # KEY_HANGUEL KEY_HANGEUL gibi takma adlar
                if deger.startswith("KEY_"):
                    deger = ham.get(deger[4:], "")
            try:
                t[ad.lower()] = int(deger, 0)
            except ValueError:
                pass
    except OSError:
        pass
    if "enter" not in t:
        t = {ad: i + 1 for i, ad in enumerate(_YEDEK_SIRA)} | _YEDEK_EK
    t.pop("max", None)
    t.pop("cnt", None)
    _TUSLAR = t
    return t


def keysym(c: str) -> int:
    """Karakter → X keysym (Latin-1 doğrudan, diğerleri Unicode keysym 0x01000000+U)."""
    o = ord(c)
    if c == "\n":
        return 0xFF0D
    if c == "\t":
        return 0xFF09
    if 0x20 <= o <= 0x7E or 0xA0 <= o <= 0xFF:
        return o
    return 0x01000000 | o


def kimlik_yap(wid: int) -> str:
    return f"{ARKA_ONEK}0x{wid:x}"


def kimlik_coz(k: str) -> int:
    if not isinstance(k, str) or not k.startswith(ARKA_ONEK):
        raise Dur(PENCERE_YOK, _("bu kimlik sanal masaüstüne ait değil: {kimlik} (sanal kimlikler '{onek}0x…')").format(kimlik=repr(k), onek=ARKA_ONEK))
    try:
        return int(k[len(ARKA_ONEK):], 16)
    except ValueError:
        raise Dur(PENCERE_YOK, _("geçersiz sanal pencere kimliği: {kimlik}").format(kimlik=repr(k)))


def _devral_var() -> bool:
    """Devral açık: dosya var VE yazan panel yaşıyor (panel çöktüyse bayat dosya ajanı kalıcı 12'de tutmasın)."""
    return masaustu.devral_var()


def _girdi_kilidi_yolu() -> str:
    return os.path.join(os.path.dirname(masaustu.durum_yolu()), "sanal-girdi.lock")


# ---------------------------------------------------------------- X bağlantısı

class _X:
    """Tek X bağlantısı (python-xlib iş parçacığı güvenli değil: her iş parçacığı kendi _X'ini açar)."""

    def __init__(self, ekran: str):
        try:
            self.d = masaustu.x_ac(ekran)
        except Exception as e:  # noqa: BLE001 - Xlib bağlantı hataları çeşitli
            raise Dur(SANAL_KAPALI, _("sanal ekrana ({ekran}) bağlanılamadı: {hata}").format(ekran=ekran, hata=e))
        self.ekran = ekran
        ek = self.d.screen()
        self.kok = ek.root
        self.W, self.H = ek.width_in_pixels, ek.height_in_pixels
        self.a = {n: self.d.intern_atom(n) for n in ATOMLAR}

    def kapat(self) -> None:
        try:
            self.d.close()
        except Exception:  # noqa: BLE001
            pass

    def pencere(self, wid: int):
        return self.d.create_resource_object("window", wid)

    def _ozellik(self, w, ad: str, tur=0):
        from Xlib import error as xerror
        try:
            return w.get_full_property(self.a[ad], tur)
        except (xerror.BadWindow, xerror.BadAtom, xerror.BadMatch):
            return None

    def wm_var(self) -> bool:
        p = self._ozellik(self.kok, "_NET_SUPPORTING_WM_CHECK")
        return bool(p is not None and len(p.value) and p.value[0])

    def istemciler(self) -> list[int]:
        """Üst düzey uygulama pencereleri: pencere yöneticisi varsa _NET_CLIENT_LIST, yoksa kökün görünür,
        override-redirect olmayan çocukları."""
        p = self._ozellik(self.kok, "_NET_CLIENT_LIST")
        if p is not None and self.wm_var():
            return [int(w) for w in p.value]
        from Xlib import X
        from Xlib import error as xerror
        sonuc = []
        for c in self.kok.query_tree().children:
            try:
                at = c.get_attributes()
            except xerror.BadWindow:
                continue
            if at.map_state == X.IsViewable and not at.override_redirect:
                sonuc.append(c.id)
        return sonuc

    def baslik(self, wid: int) -> str:
        if not wid:
            return ""
        w = self.pencere(wid)
        p = self._ozellik(w, "_NET_WM_NAME", self.a["UTF8_STRING"])
        if p is not None and p.value:
            v = p.value
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
        p = self._ozellik(w, "WM_NAME")
        if p is not None and p.value:
            v = p.value
            if isinstance(v, bytes):
                try:
                    return v.decode("utf-8")
                except UnicodeDecodeError:
                    return v.decode("latin-1")
            return str(v)
        return ""

    def sinif(self, wid: int) -> str:
        """WM_CLASS'ın sınıf kısmı, küçük harf (KWin resourceClass gibi); yoksa örnek adı."""
        p = self._ozellik(self.pencere(wid), "WM_CLASS") if wid else None
        if p is None or not p.value:
            return ""
        v = p.value.decode("utf-8", "replace") if isinstance(p.value, bytes) else str(p.value)
        parca = [x for x in v.split("\0") if x]
        return (parca[1] if len(parca) > 1 else parca[0] if parca else "").lower()

    def geometri(self, wid: int) -> tuple[int, int, int, int]:
        from Xlib import error as xerror
        try:
            w = self.pencere(wid)
            g = w.get_geometry()
            t = self.kok.translate_coords(w, 0, 0)
        except (xerror.BadWindow, xerror.BadDrawable):
            raise Dur(PENCERE_YOK, _("pencere bulunamadı: {kimlik}").format(kimlik=kimlik_yap(wid)))
        return (int(t.x), int(t.y), int(g.width), int(g.height))

    def var_mi(self, wid: int) -> bool:
        from Xlib import error as xerror
        try:
            self.pencere(wid).get_geometry()
            return True
        except (xerror.BadWindow, xerror.BadDrawable):
            return False

    def _ust_duzey(self, wid: int, istemciler: set[int]) -> int:
        """Bir pencereyi (odak alt penceresi) üst düzey istemcisine çevir; bulunamazsa 0."""
        from Xlib import error as xerror
        w = wid
        for _ in range(32):
            if w in istemciler:
                return w
            try:
                t = self.pencere(w).query_tree()
            except xerror.BadWindow:
                return 0
            if not t.parent or int(t.parent.id) == int(self.kok.id):
                return self._icindeki_istemci(w, istemciler)
            w = int(t.parent.id)
        return 0

    def _icindeki_istemci(self, wid: int, istemciler: set[int], derinlik: int = 3) -> int:
        """Pencere yöneticisi çerçevesi → içindeki istemci (openbox çerçevesinin torunu)."""
        from Xlib import error as xerror
        if wid in istemciler:
            return wid
        yigin = [(wid, 0)]
        while yigin:
            w, der = yigin.pop()
            try:
                cocuklar = self.pencere(w).query_tree().children
            except xerror.BadWindow:
                continue
            for c in cocuklar:
                if c.id in istemciler:
                    return c.id
                if der < derinlik:
                    yigin.append((c.id, der + 1))
        return 0

    def aktif(self) -> int:
        """Etkin istemci penceresi: _NET_ACTIVE_WINDOW (pencere yöneticisi), yoksa giriş odağı. 0 = yok."""
        ist = set(self.istemciler())
        if self.wm_var():
            p = self._ozellik(self.kok, "_NET_ACTIVE_WINDOW")
            if p is not None and len(p.value) and p.value[0] and int(p.value[0]) in ist:
                return int(p.value[0])
        f = self.d.get_input_focus().focus
        fid = f if isinstance(f, int) else int(f.id)
        if fid in (0, 1) or fid == int(self.kok.id):  # None / PointerRoot / kök
            return 0
        return self._ust_duzey(fid, ist)

    def fare(self) -> tuple[int, int, int]:
        q = self.kok.query_pointer()
        cocuk = int(q.child.id) if q.child and not isinstance(q.child, int) else int(q.child or 0)
        w = 0
        if cocuk:
            w = self._icindeki_istemci(cocuk, set(self.istemciler())) or cocuk  # menü/ipucu: kendisi
        return int(q.root_x), int(q.root_y), w

    def istemci_mesaji(self, hedef, wid: int, tur: str, veri: list[int], maske=None) -> None:
        from Xlib import X
        from Xlib.protocol import event as xevent
        ev = xevent.ClientMessage(window=self.pencere(wid), client_type=self.a[tur], data=(32, (veri + [0] * 5)[:5]))
        if maske is None:
            maske = X.SubstructureRedirectMask | X.SubstructureNotifyMask
        hedef.send_event(ev, event_mask=maske)
        self.d.flush()

    def goruntu(self):
        from PIL import Image
        from Xlib import X
        im = self.kok.get_image(0, 0, self.W, self.H, X.ZPixmap, 0xFFFFFFFF)
        veri = im.data
        if len(veri) != self.W * self.H * 4:
            raise Dur(ARAC_EKSIK, _("beklenmeyen görüntü biçimi (derinlik {derinlik}, {bayt} bayt)").format(derinlik=im.depth, bayt=len(veri)))
        return Image.frombuffer("RGB", (self.W, self.H), veri, "raw", "BGRX", 0, 1)  # salt okunur: değişirse PIL kopyalar


def kalici_klavye(ekran: str) -> int:
    """Türkçe harfleri ve sık noktalama işaretlerini boş tuş kodlarına KALICI eşle (masaüstü açılışında bir
    kez). Böylece `type` çoğu metinde geçici eşleme yapmaz (eşleme–tuş yarışı yok). → eşlenen tuş sayısı."""
    x = _X(ekran)
    try:
        mn, mx = x.d.display.info.min_keycode, x.d.display.info.max_keycode
        harita = x.d.get_keyboard_mapping(mn, mx - mn + 1)
        var = {s for satir in harita for s in satir[:2] if s}
        bos = [mn + i for i, satir in enumerate(harita) if not any(satir)]
        bos = [k for k in bos if k > mn]  # 8: bazı istemciler en küçük kodu yok sayar
        n = 0
        for alt, ust in KALICI_ESLEME:
            ka, ku = keysym(alt), keysym(ust)
            if ka in var and ku in var:
                continue
            if len(bos) <= 4:  # geçici eşlemeler için birkaç boş kod kalsın
                break
            kc = bos.pop()
            x.d.change_keyboard_mapping(kc, [(ka, ku)])
            n += 1
        x.d.sync()
        return n
    finally:
        x.kapat()


def _takili_birak_x(x: "_X") -> tuple[int, int]:
    """Sunucuda BASILI görünen her tuşu ve fare düğmesini XTEST ile bırak. → (tuş, düğme) sayısı.
    Girdi gönderen süreç SIGKILL/OOM ile ölürse Xvfb XTEST basışlarını kendiliğinden bırakmaz: sonraki ajanın
    yazısı Ctrl/Shift basılıyken gitmesin (ctrl+w…)."""
    from Xlib import X
    from Xlib.ext import xtest
    harita = x.d.query_keymap()
    tuslar = [i * 8 + b for i, bayt in enumerate(harita) for b in range(8) if bayt & (1 << b)]
    for kc in tuslar:
        xtest.fake_input(x.d, X.KeyRelease, kc)
    maske = x.kok.query_pointer().mask
    dugmeler = [n for n in range(1, 6) if maske & (X.Button1Mask << (n - 1))]
    for b in dugmeler:
        xtest.fake_input(x.d, X.ButtonRelease, b)
    x.d.sync()
    return len(tuslar), len(dugmeler)


def takili_birak(ekran: str) -> tuple[int, int]:
    """takili_birak_x, kendi bağlantısıyla (masaüstü açılışı)."""
    x = _X(ekran)
    try:
        return _takili_birak_x(x)
    finally:
        x.kapat()


# ---------------------------------------------------------------- arka uç

class SanalArkaUc(ArkaUc):
    ad = "sanal"

    def __init__(self):
        self._kilit = threading.RLock()
        self._x_ = None
        self._imza = None

    # -------- bağlantı
    def _durum(self) -> dict:
        d = masaustu.durum_oku()
        if d is None:
            raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
        return d

    def _x(self) -> _X:
        d = self._durum()
        imza = (d.get("ekran"), d.get("baslangic"))
        if self._x_ is None or imza != self._imza:
            if self._x_ is not None:
                self._x_.kapat()
            if masaustu.durum(saglik=False) is None:
                raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
            self._x_, self._imza = _X(d["ekran"]), imza
        return self._x_

    def ekran_adi(self) -> str:
        """DOĞRULANMIŞ sanal ekran adı: durum dosyasındaki Xvfb yaşıyor (PID + komut satırı + soket). Bayat
        sanal.json + aynı numarada başka bir X sunucusu → girdi oraya gitmesin: Dur 14."""
        d = masaustu.durum(saglik=False)
        if d is None:
            raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
        return d["ekran"]

    def _cagir(self, f, *a):
        """Kilitli X çağrısı; bağlantı koptuysa bir kez yeniden bağlan."""
        from Xlib import error as xerror
        with self._kilit:
            for deneme in (0, 1):
                try:
                    return f(self._x(), *a)
                except (xerror.ConnectionClosedError, BrokenPipeError, ConnectionError, OSError) as e:
                    self._x_ = None
                    if deneme:
                        raise Dur(SANAL_KAPALI, _("sanal masaüstü bağlantısı koptu: {hata}").format(hata=e))

    # -------- pencere
    def pencere_coz(self, arg: str) -> str:
        if (arg or "").lower() in EKRAN_ADLARI or arg == EKRAN:
            return EKRAN
        if not arg:
            raise Dur(PENCERE_YOK, _("pencere kimliği boş"))
        if arg.startswith(ARKA_ONEK) or re.fullmatch(r"0x[0-9a-fA-F]+", arg):
            k = arg if arg.startswith(ARKA_ONEK) else ARKA_ONEK + arg.lower()
            self.geometri(k)  # yoksa Dur(8)
            return kimlik_yap(kimlik_coz(k))
        adaylar = self.pencereler(arg)
        if not adaylar:
            raise Dur(PENCERE_YOK, _("'{ad}' adlı pencere yok (sanal masaüstü; deskhand --arka bul …)").format(ad=arg))
        if len(adaylar) > 1:
            liste = "\n".join(f"  {k} | {b}" for k, b, _ in adaylar)
            raise Dur(BELIRSIZ, _("'{ad}' {sayi} pencereye uyuyor; kimlik ver:\n{liste}").format(ad=arg, sayi=len(adaylar), liste=liste))
        return adaylar[0][0]

    def pencereler(self, desen: str | None = None):
        try:
            rx = re.compile(desen, re.I) if desen else None
        except re.error:
            rx = re.compile(re.escape(desen), re.I)

        def f(x: _X):
            sonuc = []
            for wid in x.istemciler():
                b = x.baslik(wid)
                if rx is not None and not rx.search(b):
                    continue
                try:
                    g = x.geometri(wid)
                except Dur:
                    continue
                sonuc.append((kimlik_yap(wid), b, g))
            return sonuc
        return self._cagir(f)

    def geometri(self, k: str) -> tuple[int, int, int, int]:
        if k == EKRAN:
            x0, y0, x1, y1 = self.ekran_alani()
            return (x0, y0, x1 - x0, y1 - y0)
        wid = kimlik_coz(k)
        return self._cagir(lambda x: x.geometri(wid))

    def baslik(self, k: str) -> str:
        if k == EKRAN:
            return f"EKRAN (aktif: {self._cagir(lambda x: x.baslik(x.aktif()))})"
        if not k:
            return ""
        wid = kimlik_coz(k)
        return self._cagir(lambda x: x.baslik(wid))

    def sinif(self, k: str) -> str:
        if not k or k == EKRAN:
            return ""
        wid = kimlik_coz(k)
        return self._cagir(lambda x: x.sinif(wid))

    def aktif(self) -> str:
        wid = self._cagir(lambda x: x.aktif())
        return kimlik_yap(wid) if wid else ""

    def one_getir(self, k: str) -> None:
        """Pencereyi etkinleştir ve DOĞRULA. Pencere yöneticisi: _NET_ACTIVE_WINDOW isteği (kaynak=2, araç);
        olmazsa raise + set_input_focus. Etkin olmazsa Dur 3."""
        if k == EKRAN:
            return
        wid = kimlik_coz(k)

        def f(x: _X):
            from Xlib import X
            from Xlib import error as xerror
            if x.aktif() == wid:
                return True
            if not x.var_mi(wid):
                raise Dur(PENCERE_YOK, _("pencere bulunamadı: {kimlik}").format(kimlik=k))
            if x.wm_var():
                x.istemci_mesaji(x.kok, wid, "_NET_ACTIVE_WINDOW", [2, X.CurrentTime, 0])
                for _i in range(25):
                    if x.aktif() == wid:
                        return True
                    time.sleep(0.01)
            w = x.pencere(wid)
            hata_yakala = xerror.CatchError(xerror.BadMatch, xerror.BadWindow)
            w.configure(stack_mode=X.Above, onerror=hata_yakala)
            w.set_input_focus(X.RevertToParent, X.CurrentTime, onerror=hata_yakala)
            x.d.sync()
            for _i in range(30):
                if x.aktif() == wid:
                    return True
                time.sleep(0.01)
            return False
        if self._cagir(f):
            time.sleep(0.05)  # öne gelen pencere yeniden çizilsin
            return
        a = self.aktif()
        raise Dur(AKTIF_DEGIL, _("hedef pencere aktif olmadı (aktif: {baslik})").format(baslik=repr(self.baslik(a))))

    def kapat(self, k: str) -> None:
        """Kibar kapatma: _NET_CLOSE_WINDOW (pencere yöneticisi) ya da WM_DELETE_WINDOW."""
        if k == EKRAN:
            raise Dur(PENCERE_YOK, _("masaüstü kipi kapatılamaz"))
        wid = kimlik_coz(k)

        def f(x: _X):
            from Xlib import X
            if not x.var_mi(wid):
                raise Dur(PENCERE_YOK, _("pencere bulunamadı: {kimlik}").format(kimlik=k))
            if x.wm_var():
                x.istemci_mesaji(x.kok, wid, "_NET_CLOSE_WINDOW", [X.CurrentTime, 2])
                return
            w = x.pencere(wid)
            prot = w.get_wm_protocols() or []
            if x.a["WM_DELETE_WINDOW"] not in prot:
                raise Dur(AKTIF_DEGIL, _("pencere kapatma isteğini desteklemiyor (WM_DELETE_WINDOW yok): {kimlik}").format(kimlik=k))
            x.istemci_mesaji(w, wid, "WM_PROTOCOLS", [x.a["WM_DELETE_WINDOW"], X.CurrentTime], maske=0)
        self._cagir(f)

    # -------- fare / ekran
    def fare(self):
        fx, fy, w = self._cagir(lambda x: x.fare())
        return fx, fy, (kimlik_yap(w) if w else "")

    def baslik_ve_fare(self, k: str):
        return self.baslik(k), self.fare()

    def ekran_alani(self) -> tuple[int, int, int, int]:
        x = self._cagir(lambda x: (x.W, x.H))
        return (0, 0, x[0], x[1])

    def goruntu(self):
        return self._cagir(lambda x: x.goruntu())

    # -------- girdi
    def girdi(self, etiket: str = "", gizli: bool = False, etk=None, denetle=None):
        return SanalGirdi(self, etiket, gizli, etk, denetle)

    def insan_var_mi(self) -> bool:
        return _devral_var()

    # -------- uygulama
    def baslat(self, argv: list[str], env: dict | None = None, cikti=None):
        """Sanal masaüstünde (kafes + sanal ortam) başlat. env: os.environ'a eklenecek/değişecek değişkenler;
        cikti: açık dosya (stdout+stderr), yoksa masaüstünün uygulamalar.log'u."""
        if cikti is not None:
            return masaustu.baslat(argv, env, stdout=cikti, stderr=cikti)
        return masaustu.baslat(argv, env)

    # -------- CHANGE 1 isteğe bağlı yöntemler
    def kimlikler(self) -> list[str]:
        return [kimlik_yap(w) for w in self._cagir(lambda x: x.istemciler())]

    def klavye_duzeni(self) -> tuple[str, str]:
        return ("us", "")  # Xvfb düzeni; düzende olmayan her karakter keysym eşlemesiyle yazılır

    def yazilabilir_mi(self, c: str) -> bool:
        return c in "\n\t" or c.isprintable()

    def gecerli_tuslar(self) -> set[str]:
        return set(linux_tuslari()) | set(DEGISTIRICI)

    def pid(self, k: str) -> int | None:
        if not k or k == EKRAN:
            return None
        wid = kimlik_coz(k)

        def f(x: _X):
            p = x._ozellik(x.pencere(wid), "_NET_WM_PID")
            return int(p.value[0]) if p is not None and len(p.value) else None
        return self._cagir(f)

    def etkinlestir(self, k: str) -> None:
        try:
            self.one_getir(k)
        except Exception:  # noqa: BLE001 - doğrulamasız: okuma sonrası geri verme
            pass

    def etkinlik(self):
        return _DevralEtkinlik()

    def atspi_adresi(self) -> str | None:
        """Özel veri yolundaki erişilebilirlik veri yolunun adresi (org.a11y.Bus; gerekirse etkinleşir)."""
        try:
            from jeepney import DBusAddress, new_method_call
            from jeepney.io.blocking import open_dbus_connection
            d = self._durum()
            hedef = DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.a11y.Bus")
            with open_dbus_connection(bus=d["dbus_adres"]) as c:
                r = c.send_and_get_reply(new_method_call(hedef, "GetAddress"), timeout=5)
            return str(r.body[0]) if r.body else None
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------- girdi

class _DevralEtkinlik:
    """kde'deki Etkinlik (Wayland insan girdisi) yerine: sanalda insan = "Devral" bayrağı. Üst katmanın
    klavye_bekle / basili_bekle çağrıları değişmeden çalışsın diye aynı yöntemler."""

    hata = None

    def calisiyor(self) -> bool:
        return True

    def kendi_girdi(self, bas, son) -> None:
        pass

    def insan(self, beri) -> bool:
        return _devral_var()

    def sessiz_mi(self, sure=1.5) -> bool:
        return not _devral_var()

    def kapat(self) -> None:
        pass


class SanalGirdi:
    """kde Girdi sözleşmesi (gonder/zorla/ham/izle/izle_bitir/etk_denetle/insan_kontrol/kapat), XTEST ile.
    Kurulum yok (dotool'un 0,66 sn'si yerine ~2 ms): girdi hemen hazır."""

    devral_bekle = DEVRAL_BEKLE

    def __init__(self, arka: SanalArkaUc, etiket: str = "", gizli: bool = False, etk=None, denetle=None):
        self.arka = arka
        self.etiket, self.gizli = etiket, gizli
        self.denetle = denetle
        self.etk = _DevralEtkinlik()
        self.etk_sahibi = False
        self.x = _X(arka.ekran_adi())
        self.t0 = time.monotonic()
        self.hazir = False
        self.hazir_an = self.t0
        self.uyarilar: list[str] = []
        self.kesildi = None
        self.son_etk = self.t0
        self.fare0 = arka.fare()[:2]
        self.son_fare = self.fare0
        self.typedelay, self.typehold = 0.002, 0.008  # dotool varsayılanları
        self.keydelay, self.keyhold = 0.002, 0.008
        self._basili_tus: list[int] = []
        self._basili_dugme: list[int] = []
        self._gecici: OrderedDict[int, int] = OrderedDict()  # keysym → geçici tuş kodu
        self._izleyici = None
        self._izle_dur = threading.Event()
        self._harita_oku()
        self._kilit_f = None
        self.takili = self._takili_temizle()

    def _takili_temizle(self) -> tuple[int, int]:
        """Önceki (ölmüş) bir girdi sürecinden basılı kalan tuş/düğmeleri bırak, ama YALNIZ başka canlı girdi
        nesnesi yoksa (başkası şu an bir tuşu bilerek basılı tutuyor olabilir). Ölçüt: girdi kilidi; her canlı
        SanalGirdi paylaşımlı kilit tutar, süreç ölünce çekirdek kilidi bırakır."""
        try:
            self._kilit_f = open(_girdi_kilidi_yolu(), "a")
        except OSError:
            return (0, 0)
        sonuc = (0, 0)
        try:
            fcntl.flock(self._kilit_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            pass  # başka bir girdi nesnesi canlı: dokunma
        else:
            try:
                sonuc = _takili_birak_x(self.x)
            except Exception:  # noqa: BLE001
                pass
        try:
            fcntl.flock(self._kilit_f, fcntl.LOCK_SH)
        except OSError:
            pass
        return sonuc

    # -------- klavye eşlemesi
    def _harita_oku(self) -> None:
        d = self.x.d
        mn, mx = d.display.info.min_keycode, d.display.info.max_keycode
        harita = d.get_keyboard_mapping(mn, mx - mn + 1)
        self._ks: dict[int, tuple[int, bool]] = {}
        for i, satir in enumerate(harita):
            for j in (0, 1):
                if j < len(satir) and satir[j] and satir[j] not in self._ks:
                    self._ks[satir[j]] = (mn + i, j == 1)
        self._bos = [mn + i for i, satir in enumerate(harita) if not any(satir) and mn + i > mn]
        self._shift = self._ks.get(0xFFE1, (50, False))[0]  # Shift_L

    def _ks_kodu(self, ks: int) -> tuple[int, bool]:
        if ks in self._ks:
            return self._ks[ks]
        return self._gecici_esle(ks), False

    def _gecici_esle(self, ks: int) -> int:
        if ks in self._gecici:
            self._gecici.move_to_end(ks)
            return self._gecici[ks]
        if self._bos:
            kc = self._bos.pop()
        elif self._gecici:  # en eski geçici eşlemeyi yeniden kullan: önceki tuşu uygulama işlesin
            eski, kc = self._gecici.popitem(last=False)
            self._ks.pop(eski, None)
            self.x.d.sync()
            time.sleep(0.08)
        else:
            raise Dur(ARAC_EKSIK, _("keysym 0x{keysym} için boş tuş kodu yok").format(keysym=f"{ks:x}"))
        self.x.d.change_keyboard_mapping(kc, [(ks, ks)])
        self.x.d.sync()
        time.sleep(0.02)  # istemciler MappingNotify'ı tuştan önce işlesin
        self._gecici[ks] = kc
        self._ks[ks] = (kc, False)
        return kc

    def _gecicileri_geri_al(self) -> None:
        if not self._gecici:
            return
        try:
            self.x.d.sync()
            time.sleep(0.1)  # son tuşlar eşleme değişmeden okunsun
            for kc in self._gecici.values():
                self.x.d.change_keyboard_mapping(kc, [(0, 0)])
            self.x.d.sync()
        except Exception:  # noqa: BLE001
            pass
        self._gecici.clear()

    def _tus_ad_kodu(self, ad: str) -> tuple[int, bool]:
        """dotool tuş adı → (X tuş kodu, Shift gerekir mi)."""
        if ad.startswith("k:"):
            try:
                return int(ad[2:]) + 8, False
            except ValueError:
                raise Dur(1, _("bilinmeyen tuş: {ad}").format(ad=repr(ad)))
        if ad.startswith("x:"):
            from Xlib import XK
            ks = XK.string_to_keysym(ad[2:])
            if not ks:
                raise Dur(1, _("bilinmeyen keysym: {ad}").format(ad=repr(ad)))
            return self._ks_kodu(ks)
        t = ad.lower()
        t = DEGISTIRICI.get(TUS_TAKMA.get(t, t), TUS_TAKMA.get(t, t))
        kod = linux_tuslari().get(t)
        if kod is not None and not (len(ad) == 1 and ad != t):
            return kod + 8, False
        if len(ad) == 1:  # tek karakter (A, @, ı…): keysym ile
            return self._ks_kodu(keysym(ad))
        raise Dur(1, _("bilinmeyen tuş: {ad}").format(ad=repr(ad)))

    # -------- XTEST
    def _tus(self, kc: int, bas: bool) -> None:
        from Xlib import X
        from Xlib.ext import xtest
        xtest.fake_input(self.x.d, X.KeyPress if bas else X.KeyRelease, kc)
        self.x.d.flush()
        if bas:
            self._basili_tus.append(kc)
        elif kc in self._basili_tus:
            self._basili_tus.remove(kc)

    def _dugme(self, b: int, bas: bool) -> None:
        from Xlib import X
        from Xlib.ext import xtest
        xtest.fake_input(self.x.d, X.ButtonPress if bas else X.ButtonRelease, b)
        self.x.d.flush()
        if bas:
            self._basili_dugme.append(b)
        elif b in self._basili_dugme:
            self._basili_dugme.remove(b)

    def _git(self, px: int, py: int) -> None:
        from Xlib import X
        from Xlib.ext import xtest
        xtest.fake_input(self.x.d, X.MotionNotify, x=px, y=py)
        self.x.d.flush()

    def _hepsini_birak(self) -> None:
        for kc in reversed(list(self._basili_tus)):
            try:
                self._tus(kc, False)
            except Exception:  # noqa: BLE001
                self._basili_tus.remove(kc)
        for b in reversed(list(self._basili_dugme)):
            try:
                self._dugme(b, False)
            except Exception:  # noqa: BLE001
                self._basili_dugme.remove(b)
        try:
            self.x.d.sync()
        except Exception:  # noqa: BLE001
            pass

    # -------- satır dili
    def _ara_denetim(self) -> None:
        """Uzun satırların (type, wheel) her adımında: DUR, gözcü, Devral."""
        hata.dur_denetle()
        if self.kesildi:
            raise self.kesildi
        if _devral_var():
            raise Dur(INSAN, _("kullanıcı sanal masaüstünü devraldı (Devral)"))

    def _akorlar(self, metin: str) -> list[list[tuple[int, bool]]]:
        akorlar = []
        for akor in metin.split():
            akorlar.append([self._tus_ad_kodu(t) for t in akor.split("+") if t])
        if not akorlar:
            raise Dur(1, _("tuş verilmedi"))
        return akorlar

    def _calistir(self, satir: str, denetimli: bool = True) -> None:
        s = satir.rstrip("\n")
        if not s.strip():
            return
        komut, _ayrac, arg = s.lstrip().partition(" ")
        komut = komut.lower()
        if komut == "type":
            for c in arg:
                if denetimli:
                    self._ara_denetim()
                kc, shift = self._ks_kodu(keysym(c))
                if shift:
                    self._tus(self._shift, True)
                self._tus(kc, True)
                time.sleep(self.typehold)
                self._tus(kc, False)
                if shift:
                    self._tus(self._shift, False)
                time.sleep(self.typedelay)
        elif komut == "mouseto":
            p = arg.split()
            try:
                fx, fy = float(p[0]), float(p[1])
            except (IndexError, ValueError):
                raise Dur(1, _("mouseto FX FY olmalı: {satir}").format(satir=repr(s)))
            self._git(min(self.x.W - 1, max(0, int(fx * self.x.W))), min(self.x.H - 1, max(0, int(fy * self.x.H))))
        elif komut == "mousemove":
            p = arg.split()
            q = self.x.kok.query_pointer()
            self._git(min(self.x.W - 1, max(0, q.root_x + int(float(p[0])))),
                      min(self.x.H - 1, max(0, q.root_y + int(float(p[1])))))
        elif komut in ("click", "buttondown", "buttonup"):
            b = DUGME.get(arg.strip().lower())
            if b is None:
                raise Dur(1, _("bilinmeyen fare düğmesi: {dugme} (left|right|middle)").format(dugme=repr(arg)))
            if komut != "buttonup":
                self._dugme(b, True)
            if komut == "click":
                time.sleep(self.keyhold)
            if komut != "buttondown":
                self._dugme(b, False)
        elif komut in ("wheel", "hwheel"):
            try:
                n = int(float(arg.strip()))
            except ValueError:
                raise Dur(1, _("{komut} N olmalı: {satir}").format(komut=komut, satir=repr(s)))
            b = (4 if n > 0 else 5) if komut == "wheel" else (7 if n > 0 else 6)  # wheel artı=yukarı, hwheel artı=sağ
            for _i in range(abs(n)):
                if denetimli:
                    self._ara_denetim()
                self._dugme(b, True)
                self._dugme(b, False)
                time.sleep(0.005)
        elif komut == "key":
            for i, akor in enumerate(self._akorlar(arg)):
                if i and denetimli:
                    self._ara_denetim()
                kodlar = []
                for kc, shift in akor:  # Shift gerektiren karakter tuşu (x:at, A): Shift önce
                    if shift and self._shift not in kodlar:
                        kodlar.append(self._shift)
                    kodlar.append(kc)
                for kc in kodlar:
                    self._tus(kc, True)
                time.sleep(self.keyhold)
                for kc in reversed(kodlar):
                    self._tus(kc, False)
                time.sleep(self.keydelay)
        elif komut == "keydown":
            for akor in self._akorlar(arg):
                for kc, shift in akor:
                    if shift:
                        self._tus(self._shift, True)
                    self._tus(kc, True)
        elif komut == "keyup":
            for akor in reversed(self._akorlar(arg)):
                for kc, shift in reversed(akor):
                    if kc in self._basili_tus:
                        self._tus(kc, False)
                    if shift and self._shift in self._basili_tus:
                        self._tus(self._shift, False)
        elif komut in ("typedelay", "typehold", "keydelay", "keyhold"):
            try:
                setattr(self, komut, max(0.0, float(arg.strip()) / 1000))
            except ValueError:
                raise Dur(1, _("{komut} MS olmalı: {satir}").format(komut=komut, satir=repr(s)))
        else:
            raise Dur(1, _("bilinmeyen girdi satırı: {satir}").format(satir=repr(s)))
        self.x.d.sync()

    # -------- insan önceliği (sanalda: Devral bayrağı)
    def _devral_bekle(self, ne: str) -> None:
        if not _devral_var():
            return
        bitis = time.monotonic() + self.devral_bekle
        while time.monotonic() < bitis:
            time.sleep(0.05)
            if not _devral_var():
                return
        raise Dur(INSAN, _("kullanıcı sanal masaüstünü {sn} sn boyunca kullandı (Devral); {ne}").format(
            sn=f"{self.devral_bekle:.0f}", ne=ne))

    def _hazirla(self) -> None:
        if self.hazir:
            return
        self._devral_bekle(_("girdi gönderilmedi"))
        self.son_etk = time.monotonic()
        self.hazir = True

    def etk_denetle(self, ne: str | None = None) -> None:
        if _devral_var():
            raise Dur(INSAN, _("kullanıcı sanal masaüstünü devraldı (Devral); {ne}").format(
                ne=ne or _("girdi gönderilmedi")))
        self.son_etk = time.monotonic()

    def insan_kontrol(self) -> None:
        self._devral_bekle(_("girdi gönderilmedi"))
        self.son_fare = self.arka.fare()[:2]
        self.son_etk = time.monotonic()

    # -------- gözcü
    def izle(self, k: str, desen: str | None) -> None:
        """Yazı GÖZCÜSÜ (~8 ms): etkin pencere, başlık, DUR, Devral. Değişince bayrak kalkar; ham() bir sonraki
        satırdan (harften) önce durur. Kendi X bağlantısıyla (python-xlib iş parçacığı güvenli değil)."""
        self.izle_bitir()
        self.kesildi = None
        self._izle_dur = threading.Event()
        wid = None if k == EKRAN else kimlik_coz(k)
        ekran = self.arka.ekran_adi()
        hazir = threading.Event()

        def dongu():
            try:
                x = _X(ekran)
            except Dur as e:
                self.kesildi = e
                hazir.set()
                return
            hazir.set()
            try:
                while not self._izle_dur.is_set():
                    neden = None
                    if os.path.exists(hata.dur_dosyasi()):
                        neden = (KULLANICI_DUR, _("kullanıcı DUR dedi"))
                    elif _devral_var():
                        neden = (INSAN, _("kullanıcı sanal masaüstünü devraldı (Devral)"))
                    elif wid is not None:
                        a = x.aktif()
                        if a != wid:
                            neden = (AKTIF_DEGIL, _("aktif pencere değişti → {baslik}").format(baslik=repr(x.baslik(a))))
                        elif desen and not re.search(desen, x.baslik(wid), re.I):
                            neden = (BASLIK_SINIF, _("başlık değişti: {baslik} (beklenen /{desen}/)").format(
                                baslik=repr(x.baslik(wid)), desen=desen))
                    if neden:
                        self.kesildi = Dur(*neden)
                        return
                    time.sleep(0.008)
            except Exception as e:  # noqa: BLE001 - gözcü çökerse güvenli taraf: dur
                self.kesildi = Dur(PENCERE_YOK, _("gözcü hatası: {hata}").format(hata=e))
            finally:
                x.kapat()

        self._izleyici = threading.Thread(target=dongu, daemon=True)
        self._izleyici.start()
        hazir.wait(2)

    def izle_bitir(self) -> None:
        if self._izleyici is not None:
            self._izle_dur.set()
            self._izleyici.join()
            self._izleyici = None

    # -------- gönderim
    def _kayit(self, k: str, satirlar) -> None:
        from ..gunluk import gunluk
        kayit = [f"type ***({len(s) - 5})" if self.gizli and s.startswith("type ") else s for s in satirlar]
        try:
            b = self.arka.baslik(k)
        except Dur:
            b = "?"
        gunluk(f"{self.etiket} | arka {self.x.ekran} [{b}] | {' ; '.join(kayit)}")

    def gonder(self, k: str, desen: str | None, *satirlar: str) -> None:
        """kde Girdi.gonder ile aynı sıra: hazırla → DUR → güvenlik denetimi (denetle) → Devral, sonra satırlar.
        Bir gonder() çağrısının satırları ATOMİKTİR (çift tıklamanın iki click'i bölünmez); yalnız uzun satırlar
        (type harfleri, wheel adımları, key akorları) kendi içinde DUR/gözcü/Devral'a bakar. Herhangi bir
        Dur'da basılı tuş/düğmeler bırakılır."""
        try:
            self._hazirla()
            if self.kesildi:
                raise self.kesildi
            hata.dur_denetle()
            if self.denetle is not None:
                self.denetle(k, desen)
            self.etk_denetle()
            for s in satirlar:
                self._calistir(s)
        except Dur:
            self._hepsini_birak()
            raise
        except Exception as e:  # noqa: BLE001 - X bağlantısı vb.
            self._hepsini_birak()
            raise Dur(ARAC_EKSIK, _("sanal girdi gönderilemedi: {hata}").format(hata=e))
        self.son_etk = time.monotonic()
        self._kayit(k, satirlar)

    def ham(self, satir: str) -> None:
        """Denetimsiz tek satır (yaz döngüsü; denetimi gözcü yapar). DUR yine de her satırdan önce bakılır."""
        if self.kesildi:
            self._hepsini_birak()
            raise self.kesildi
        try:
            hata.dur_denetle()
            self._calistir(satir)
        except Dur:
            self._hepsini_birak()
            raise
        except Exception as e:  # noqa: BLE001
            self._hepsini_birak()
            raise Dur(ARAC_EKSIK, _("sanal girdi gönderilemedi: {hata}").format(hata=e))

    def insan_ham(self, satir: str) -> None:
        """Paneldeki "Devral": İNSANIN girdisini sanal masaüstüne aktarır. Devral bayrağını (insan var) yok sayar,
        yalnız DUR'a bakar (bırakma satırları — buttonup/keyup — DUR'da da geçer: düğme basılı kalmasın).
        Günlüğe yazılmaz (kullanıcı orada parola yazıyor olabilir)."""
        if satir.split(" ", 1)[0].lower() not in ("buttonup", "keyup"):
            hata.dur_denetle()
        try:
            self._calistir(satir, denetimli=False)
        except Exception as e:  # noqa: BLE001
            self._hepsini_birak()
            raise Dur(ARAC_EKSIK, _("sanal girdi gönderilemedi: {hata}").format(hata=e))

    def zorla(self, satir: str) -> None:
        """BIRAKMA (keyup/buttonup): hiçbir denetim yok, kesinti olsa bile gönderilir."""
        try:
            self._calistir(satir, denetimli=False)
        except Exception:  # noqa: BLE001
            pass
        from ..gunluk import gunluk
        gunluk(f"{self.etiket} | arka bırak | {satir}")

    def kapat(self) -> None:
        self.izle_bitir()
        self._hepsini_birak()
        self._gecicileri_geri_al()
        self.x.kapat()
        if self._kilit_f is not None:
            self._kilit_f.close()  # kilit bırakılır
            self._kilit_f = None
