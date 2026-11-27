"""Web sayfası ögelerini erişilebilirlik ağacından (AT-SPI) KESİN okuma: bağlantı, düğme, giriş alanı, onay/radyo/seçim
kutusu, sekme/menü ögesi; adı, rolü, durumu ve PENCERE koordinatlı kutusuyla. Yalnız OKUMA katmanı: tıklama/yazı yine
gerçek girdi yolundan (tüm güvenlik denetimleriyle) gider.

Neden AT-SPI (uzaktan denetim protokolü değil): yeni ağ kapısı açılmaz, sayfa otomasyon görmez (navigator.webdriver
false kalır), Chromium/Electron da aynı arayüzü sunar. Ölçümler: tests/web_olcum.py.

Uygulama: libatspi yerine erişilebilirlik veri yoluna doğrudan D-Bus (jeepney) ile bağlanır ve istekleri BORU HATTINDA
(yanıt beklemeden art arda) gönderir: ~1.000 bağlantılı sayfa yüzlerce ms'de okunur. Bu yüzden süreç geneli libatspi
durumuna (kullanıcının oturum veri yolu) dokunmaz; arka plan masaüstünün kendi erişilebilirlik veri yolu
(SanalArkaUc.atspi_adresi) aynı süreçte güvenle okunur. Kayıt defteri (at-spi2-registryd) gerekmez: uygulama, pencerenin
süreç kimliğinden (GetConnectionUnixProcessID) bulunur.

Tarayıcının erişilebilirliği açık olmalı: Firefox için ortamda GNOME_ACCESSIBILITY=1 (ya da veri yolunda
org.a11y.Status.IsEnabled), Chromium/Electron için --force-renderer-accessibility.
"""
from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Container

from .arka_uc import EKRAN, sec
from .hata import ARAC_EKSIK, BELIRSIZ, BULUNAMADI, Dur
from .i18n import _

KOK_YOL = "/org/a11y/atspi/accessible/root"
ERISIM = "org.a11y.atspi.Accessible"
BILESEN = "org.a11y.atspi.Component"
SCREEN, WINDOW = 0, 1  # AtspiCoordType

# AtspiStateType bit numaraları (GetState iki uint32 döndürür: 0-31, 32-63)
_DURUM_BIT = {"active": 1, "busy": 3, "checked": 4, "collapsed": 5, "defunct": 6, "editable": 7, "enabled": 8,
              "expandable": 9, "expanded": 10, "focusable": 11, "focused": 12, "pressed": 20, "selected": 23,
              "sensitive": 24, "showing": 25, "visible": 30, "indeterminate": 32, "required": 33,
              "invalid_entry": 36, "visited": 40, "checkable": 41, "has_popup": 42, "read_only": 43}
# Çıktıdaki durum belirteçleri (API değerleri; çevrilmez): AT-SPI durumu → kısa Türkçe belirteç
_DURUM_ADI = (("checked", "isaretli"), ("indeterminate", "karisik"), ("focused", "odakli"), ("selected", "secili"),
              ("pressed", "basili"), ("expanded", "acik"), ("read_only", "salt_okunur"), ("required", "zorunlu"),
              ("invalid_entry", "gecersiz"), ("visited", "ziyaret_edildi"))

# Varsayılan çıktı: etkileşimli web ögeleri (AT-SPI rol adları; at-spi2 2.5x "push button" yerine "button" der)
ETKILESIMLI = frozenset({
    "button", "push button", "toggle button", "link", "entry", "password text", "spin button", "combo box",
    "check box", "radio button", "page tab", "menu item", "check menu item", "radio menu item", "slider", "switch",
    "toggle switch", "list box", "tree item", "option", "list item selectable"})
# Türkçe/kısa rol takma adları (roller=… parametresi)
ROL_TAKMA = {
    "düğme": {"button", "push button", "toggle button"}, "dugme": {"button", "push button", "toggle button"},
    "bağlantı": {"link"}, "baglanti": {"link"},
    "giriş": {"entry", "password text", "spin button"}, "giris": {"entry", "password text", "spin button"},
    "metin kutusu": {"entry", "password text"}, "onay kutusu": {"check box"}, "radyo": {"radio button"},
    "seçim kutusu": {"combo box", "list box"}, "secim kutusu": {"combo box", "list box"},
    "sekme": {"page tab"}, "menü": {"menu item", "check menu item", "radio menu item"},
    "menu": {"menu item", "check menu item", "radio menu item"}, "başlık": {"heading"}, "baslik": {"heading"},
    # at-spi2 sürümüne göre düğme "button" ya da "push button" olur: ikisi de aynı
    "button": {"button", "push button", "toggle button"}, "push button": {"button", "push button", "toggle button"},
}
# Bu rollerin altına inilmez (etkileşimli alt öge taşımazlar; 1.000 bağlantılı sayfada çağrı sayısını yarıya indirir)
_YAPRAK = frozenset({"button", "push button", "toggle button", "link", "entry", "password text", "spin button",
                     "check box", "radio button", "page tab", "slider", "image", "static",
                     "separator", "menu item", "check menu item", "radio menu item"})
# Tarayıcı arayüzünde (belge dışı) inilmeyen dallar: araç çubukları, sekme şeridi, menüler
_KROM_BUDA = frozenset({"tool bar", "menu bar", "page tab list", "menu", "status bar", "popup menu", "tool tip"})
_BELGE = frozenset({"document web", "document frame"})
_AD_SINIRI = 80
_PARCA = 4000  # tek seferde boru hattına konan istek


# ---------------------------------------------------------------- D-Bus (boru hattı)

class _Yol:
    """Erişilebilirlik veri yoluna jeepney bağlantısı + boru hatlı toplu çağrı."""

    def __init__(self, adres: str):
        from jeepney.io.blocking import open_dbus_connection
        try:
            self.c = open_dbus_connection(bus=adres)
        except Exception as e:  # noqa: BLE001
            raise Dur(ARAC_EKSIK, _("erişilebilirlik veri yoluna bağlanılamıyor ({ayrinti})").format(ayrinti=e))

    def kapat(self) -> None:
        try:
            self.c.close()
        except Exception:  # noqa: BLE001
            pass

    def toplu(self, mesajlar: list, sure: float = 10.0, yeniden: bool = True) -> list:
        """İstekleri yanıt beklemeden gönder, yanıtları sırayla topla. Hata yanıtı → None. yeniden: hata yanıtı alan
        istekler BİR kez daha sorulur (sayfa değişirken geçici hata alt ağacı sessizce düşürmesin)."""
        sonuc = self._toplu(mesajlar, sure)
        if yeniden:
            hatali = [i for i, v in enumerate(sonuc) if v is None]
            if hatali:
                for i, v in zip(hatali, self._toplu([mesajlar[i] for i in hatali], sure)):
                    sonuc[i] = v
        return sonuc

    def _toplu(self, mesajlar: list, sure: float) -> list:
        from jeepney import MessageType
        from jeepney.low_level import HeaderFields
        sonuc: list = [None] * len(mesajlar)
        for bas in range(0, len(mesajlar), _PARCA):
            son = getattr(_SINIR, "bitis", None)
            if son is not None and time.monotonic() >= son:  # tarama_siniri: toplam süre aşıldı (girdi kapısı taraması)
                raise Dur(ARAC_EKSIK, _("erişilebilirlik ağacı süre sınırı içinde okunamadı"))
            bekleyen = {}
            for i in range(bas, min(bas + _PARCA, len(mesajlar))):
                s = next(self.c.outgoing_serial)
                self.c.send(mesajlar[i], serial=s)
                bekleyen[s] = i
            bitis = time.monotonic() + sure
            if son is not None:
                bitis = min(bitis, son)
            while bekleyen:
                try:
                    m = self.c.receive(timeout=max(0.0, bitis - time.monotonic()))
                except (TimeoutError, OSError, EOFError) as e:
                    raise Dur(ARAC_EKSIK, _("erişilebilirlik ağacı yanıt vermedi ({sayi} istek bekliyor: {hata})").format(
                        sayi=len(bekleyen), hata=type(e).__name__))
                i = bekleyen.pop(m.header.fields.get(HeaderFields.reply_serial, -1), None)
                if i is not None and m.header.message_type == MessageType.method_return:
                    sonuc[i] = m.body
        return sonuc


_SINIR = threading.local()  # bu iş parçacığında ağaç taramasının TOPLAM süre sınırı (monotonic bitiş; yoksa sınırsız)


@contextlib.contextmanager
def tarama_siniri(sure: float):
    """with bloğundaki ağaç taraması (toplu) en çok `sure` sn sürer; aşılırsa Dur(ARAC_EKSIK). İç içe geçerse en sıkı sınır."""
    onceki = getattr(_SINIR, "bitis", None)
    yeni = time.monotonic() + sure
    _SINIR.bitis = yeni if onceki is None else min(onceki, yeni)
    try:
        yield
    finally:
        _SINIR.bitis = onceki


def _m(bus, yol, arayuz, uye, imza=None, govde=()):
    from jeepney import DBusAddress, new_method_call
    return new_method_call(DBusAddress(yol, bus_name=bus, interface=arayuz), uye, imza, govde)


def _ozellik(bus, yol, ad, arayuz=ERISIM):
    from jeepney import DBusAddress, Properties
    return Properties(DBusAddress(yol, bus_name=bus, interface=arayuz)).get(ad)


def _deg(govde, varsayilan=None):
    """Yöntem yanıtının ilk değeri (hata yanıtı / boş → varsayılan)."""
    return govde[0] if govde else varsayilan


def _ozd(govde, varsayilan=None):
    """Özellik (Properties.Get) yanıtı: varyant ('s', değer) → değer."""
    return govde[0][1] if govde and isinstance(govde[0], tuple) and len(govde[0]) == 2 else varsayilan


def _durumlar(govde) -> set[str]:
    if not govde or not govde[0] or len(govde[0]) < 2:
        return set()
    bitler = int(govde[0][0]) | (int(govde[0][1]) << 32)
    return {ad for ad, b in _DURUM_BIT.items() if bitler >> b & 1}


# ---------------------------------------------------------------- pencere → erişilebilirlik çerçevesi

def _oturum_atspi_adresi() -> str | None:
    """Kullanıcının oturum veri yolundaki erişilebilirlik veri yolu adresi (org.a11y.Bus.GetAddress)."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        with open_dbus_connection(bus="SESSION") as c:
            r = c.send_and_get_reply(new_method_call(
                DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.a11y.Bus"), "GetAddress"),
                timeout=5)
        return str(r.body[0]) if r.body else None
    except Exception:  # noqa: BLE001
        return None


_KARDES_YOK = object()  # _cerceve_bul: kardeş listesi verilmedi (erisim.KARDES_VERILMEDI'ye çevrilir)
KONUM_TOLERANS = 1  # px: çerçeve sınırı ile pencerenin bilinen geometrisi arasındaki en çok fark
KONUM_HATA_TURU = "konum"  # Dur.tur: öge konumu doğrulanamadı (tık yolu bunu yutmaz; fail-closed)


def konum_coz(geo, ekran, pencere):
    """Üst düzey çerçevenin ERİŞİLEBİLİRLİK sınırlarını pencerenin bilinen geometrisiyle (geo = x, y, g, y: pencere
    çerçevesi) karşılaştırıp ögelerin hangi koordinat çerçevesinde geldiğini belirle. Wayland'de uygulamaya göre
    (1) KÜRESEL dekorlu çerçeve (ekran sınırı geometriyle ±1 px aynı), (2) KÜRESEL istemci alanı (ekran sınırı geometrinin
    içinde, kenar payları tutarlı: sol/sağ eşit, alt ≥ 0), (3) PENCERE-YEREL (pencere türü sınır 0,0 ve boyut geometriyle
    tutarlı) olabilir; hiçbiri tutmuyorsa None (konum doğrulanamaz: tık YOK). ekran / pencere: GetExtents(SCREEN / WINDOW).
    → (koordinat türü, köken (ox, oy): öge koordinatına eklenince PENCERE pikseli, çerçeve adı) | None."""
    X, Y, W, H = geo
    t = KONUM_TOLERANS
    if ekran and len(ekran) == 4:
        sx, sy, sw, sh = ekran
        if all(abs(a - b) <= t for a, b in zip(ekran, geo)):
            return SCREEN, (-X, -Y), "kuresel_cerceve"
        dx, dy = sx - X, sy - Y
        if (sw > 0 and sh > 0 and 0 <= dx <= 64 and 0 <= dy <= 160 and abs((W - sw) - 2 * dx) <= t
                and -t <= (Y + H) - (sy + sh) <= 64):
            return SCREEN, (-X, -Y), "kuresel_istemci"
    if pencere and len(pencere) == 4:
        wx, wy, ww, wh = pencere
        if (abs(wx) <= t and abs(wy) <= t and 0 < ww <= W + t and 0 < wh <= H + t and W - ww <= 128
                and H - wh <= 192):
            dx = max(0, round((W - ww) / 2))
            dy = max(0, H - wh - dx)
            return WINDOW, (dx - wx, dy - wy), "pencere"
    return None


def _veri_yolu_adresi(au, sanal: bool) -> str:
    adres = au.atspi_adresi() if sanal else _oturum_atspi_adresi()
    if not adres:
        raise Dur(ARAC_EKSIK, _("erişilebilirlik veri yolu bulunamadı (org.a11y.Bus yanıt vermedi)"))
    return adres


def _baglam(k, islem="tara"):
    """→ (arka uç, _Yol, uygulama veri yolu adı, çerçeve yolu, koordinat türü, köken (ox, oy), konum: çerçeve adı | None).
    konum None = çerçeve sınırı pencere geometrisiyle eşleşmedi: koordinatlar doğrulanamadı (okuma uyarır, tık reddeder).
    Çerçeve YALNIZ pencerenin süreç ağacından seçilir ve kendi kimliğiyle denetlenir (erisim._cerceve_denetle):
    islem "tara" = okuma (panel süreci / yasak desen → 10), "eylem" = ek olarak ajanın kendi istemcisi ve uygulama
    erişim seviyesi (10)."""
    if k == EKRAN or not k:
        raise Dur(1, _("web ögeleri pencere ister (masaüstü kipi değil)"))
    au = sec(k)
    sanal = getattr(au, "ad", "") == "sanal"
    adres = _veri_yolu_adresi(au, sanal)
    try:
        pid = int(au.pid(k) or 0) if hasattr(au, "pid") else 0
    except (TypeError, ValueError):
        pid = 0
    baslik = au.baslik(k) or ""
    from .erisim import kardes_basliklari
    kardes = kardes_basliklari(au, k, pid)  # bağımsız kanal: aynı süreçteki öbür pencereler (pencere yöneticisi)
    yol = _Yol(adres)
    try:
        bus, cerceve, app_pid, app_ad, cerceve_ad = _cerceve_bul(yol, pid, baslik, kardes)
        from .erisim import _cerceve_denetle
        _cerceve_denetle(app_pid, app_ad, cerceve_ad, islem)
        geo = tuple(au.geometri(k))
        ekran, pencere = yol.toplu([_m(bus, cerceve, BILESEN, "GetExtents", "u", (SCREEN,)),
                                    _m(bus, cerceve, BILESEN, "GetExtents", "u", (WINDOW,))])
        cozum = konum_coz(geo, _deg(ekran), _deg(pencere))
        if isinstance(kardes, list) and kardes:  # D-1: çok pencerede okumada da çerçeve ↔ pencere geometrisi şart
            from .erisim import cerceve_geometri_denetle
            olcek = au.masaustu_olcegi() if hasattr(au, "masaustu_olcegi") else 1
            cerceve_geometri_denetle(geo, _deg(ekran), _deg(pencere), kardes, baslik, int(olcek or 1))
        if cozum:
            return au, yol, bus, cerceve, cozum[0], cozum[1], cozum[2]
        if sanal:  # X11 tek çerçeve: ekran koordinatı kesin (geometri eşleşmese de pencere piksel dönüşümü bellidir)
            return au, yol, bus, cerceve, SCREEN, (-geo[0], -geo[1]), None
        # Wayland, eşleşme yok: okuma için eski kestirim (tık yolu konum=None görünce REDDEDER)
        X, Y, W, H = geo
        fe = _deg(pencere, (0, 0, W, H))
        ox = max(0, round((W - fe[2]) / 2)) if W > fe[2] else 0
        oy = max(0, H - fe[3] - ox) if H > fe[3] else 0
        return au, yol, bus, cerceve, WINDOW, (ox - fe[0], oy - fe[1]), None
    except BaseException:
        yol.kapat()
        raise


def _cerceve_bul(yol: _Yol, pid: int, baslik: str, kardes=_KARDES_YOK) -> tuple[str, str, int, str, str]:
    """Pencerenin üst düzey erişilebilirlik çerçevesi: YALNIZ pencerenin süreç ağacındaki (pencerenin süreci ya da onun
    torunları: çok süreçli tarayıcı) bağlantılardan; seçim erisim.cerceve_karari (kardes: aynı süreçteki öbür
    pencerelerin başlıkları, pencere yöneticisinden; SOAK-FIX-R1). Atalar (pencereyi
    başlatan uçbirim/başlatıcı, bu süreç) ve bu sürecin kendi bağlantısı sayılmaz. PID bilinmiyorsa ya da ağaçta yoksa
    Dur 6: başka bir uygulamanın çerçevesine başlık benzerliğiyle düşülmez (denetimler pencerede yapılır, eylem BAŞKA
    uygulamada olurdu). → (veri yolu adı, çerçeve yolu, uygulama pid, uygulama adı, çerçeve adı)."""
    import os

    from . import kendi
    from .guvenlik import baslik_goster  # gizli yazı (baslik_gizle) altında başlık iletiye girmez
    if not pid:
        raise Dur(BULUNAMADI, _("pencerenin süreç kimliği (PID) bilinmiyor: web çerçevesi güvenle eşlenemez ({baslik})"
                                ).format(baslik=baslik_goster(baslik)))
    dbus = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")
    adlar = [a for a in (_deg(yol.toplu([_m(*dbus, "ListNames")])[0], []) or []) if a.startswith(":")]
    pidler = yol.toplu([_m(*dbus, "GetConnectionUnixProcessID", "s", (a,)) for a in adlar])
    ben = getattr(yol.c, "unique_name", None)

    def agacta(p_):
        if p_ == os.getpid():
            return False
        return p_ == pid or any(a_ == pid for a_, _c in kendi.atalar(p_)[1:])
    uygulamalar = [(a, int(p[0])) for a, p in zip(adlar, pidler) if p and a != ben and agacta(int(p[0]))]
    if not uygulamalar:
        raise Dur(BULUNAMADI, _("pencerenin uygulaması erişilebilirlik ağacında yok (pid {pid}). Firefox "
                                "GNOME_ACCESSIBILITY=1 ile, Chromium --force-renderer-accessibility ile "
                                "başlatılmalı").format(pid=pid))
    cocuklar = yol.toplu([_m(a, KOK_YOL, ERISIM, "GetChildren") for a, _p in uygulamalar])
    app_adlari = yol.toplu([_ozellik(a, KOK_YOL, "Name") for a, _p in uygulamalar])
    adaylar = [(b_, y, ap, _ozd(an, "") or "") for (a, ap), c, an in zip(uygulamalar, cocuklar, app_adlari) if c
               for b_, y in c[0] if b_ == a]  # çerçeve uygulamanın KENDİ bağlantısında olmalı
    if not adaylar:
        raise Dur(BULUNAMADI, _("uygulamanın erişilebilirlik ağacında pencere yok (pid {pid}). Firefox "
                                "GNOME_ACCESSIBILITY=1 ile, Chromium --force-renderer-accessibility ile "
                                "başlatılmalı").format(pid=pid))
    adlar_ = yol.toplu([_ozellik(a, y, "Name") for a, y, _p, _n in adaylar])
    from .erisim import KARDES_VERILMEDI, cerceve_karari
    i = cerceve_karari([_ozd(n, "") or "" for n in adlar_], baslik,
                       KARDES_VERILMEDI if kardes is _KARDES_YOK else kardes, [ap == pid for _b, _y, ap, _n in adaylar])
    b_, y, ap, an = adaylar[i]
    return b_, y, ap, an, _ozd(adlar_[i], "") or ""


# ---------------------------------------------------------------- ağaç yürüyüşü

def _rol_kumesi(roller) -> set[str] | None:
    if roller is None:
        return None
    if isinstance(roller, str):
        roller = [r for r in roller.split(",") if r.strip()]
    kume: set[str] = set()
    for r in roller:
        r = r.strip().lower()
        kume |= ROL_TAKMA.get(r, {r})
    return kume


_CERCEVE_EK = frozenset({"label", "static", "heading", "paragraph", "image", "text"})  # iframe içi metin ögeleri (cerceve_metni)


class _TumRoller:
    """_yuru roller=: belge içindeki HER rol istenir (hassas düğme bağlamı: listede olmayan rol — canvas, landmark… —
    alana bindirilmiş tıklanır örtü olabilir)."""

    def __contains__(self, _rol) -> bool:
        return True


_TUM_ROLLER = _TumRoller()


def _yuru(yol: _Yol, bus: str, cerceve: str, koord: int, koken, roller: Container[str] | None, gorunur: bool,
          en_cok_dugum: int = 30000, cerceve_metni: bool = False, durum: dict | None = None):
    """Çerçeveden başlayıp etkin (SHOWING) belge(ler)in ögelerini topla → (ham ögeler, belgeler, düğüm sayısı).
    Seviye seviye iki boru hattı turu: (1) rol + ad + durum, (2) gerekenlere alt ögeler + kutu (+ belge adresi).
    Tarayıcı arayüzünde yalnız görünen dallardan belgeye inilir (arka plan sekmelerinin belgeleri atlanır); belge
    içinde gorunur=True ise görünmeyen (SHOWING olmayan) dallara inilmez. Görüş alanı: en yakın çerçeve/belge kutusu
    (iframe'de üst alanla kesişimi) — kaydırma alanı dışındaki öge gorunur=False olur. Ögenin `_kutu`'su negatif
    konumda None'dır; `_hkutu` = okunan ham kutu (pozitif boyutluysa, konumdan bağımsız).
    durum (sözlük) verilirse liste EKSİK olabildiğinde durum["kesik"] = True: düğüm sınırı doldu, düğümün rolü / belge
    içinde çocukları ya da istenen ögenin kutusu okunamadı, belge içinde başka veri yolundaki çocuk atlandı."""
    istenen = roller if roller is not None else ETKILESIMLI
    seviye = [(cerceve, (), 0, None, "")]  # (yol, belge sırası anahtarı, belge derinliği, görüş alanı, belge adresi)
    ogeler, belgeler, sayi, kesik = [], [], 0, False
    while seviye and sayi < en_cok_dugum:
        sayi += len(seviye)
        m = []
        for y, *_ in seviye:
            m += [_m(bus, y, ERISIM, "GetRoleName"), _ozellik(bus, y, "Name"), _m(bus, y, ERISIM, "GetState")]
        r = yol.toplu(m)
        isler, ikinci = [], []
        for i, (y, anahtar, derin, alan, badres) in enumerate(seviye):
            rol = _deg(r[3 * i], "") or ""
            d = _durumlar(r[3 * i + 2])
            if not rol or "defunct" in d:
                kesik = kesik or ("defunct" not in d)  # rolü okunamayan (yok olmamış) düğüm: alt dalı bilinmiyor
                continue
            belge = rol in _BELGE
            if belge and "showing" not in d and not (derin and not gorunur):
                continue  # arka plandaki sekmenin belgesi (ya da gizli iframe)
            if derin == 0 and not belge:  # tarayıcı arayüzü: yalnız görünen dallar, belgeye doğru
                inilir = rol not in _KROM_BUDA and rol not in _YAPRAK and ("showing" in d or y == cerceve)
                ister = False
            else:
                ister = rol in istenen or (cerceve_metni and derin > 1 and rol in _CERCEVE_EK)
                inilir = (rol not in _YAPRAK and not (rol == "combo box" and "expanded" not in d)
                          and (belge or not gorunur or "showing" in d))
            kutu_ister = ister or belge or rol == "internal frame"
            isler.append((y, anahtar, derin, alan, rol, (_ozd(r[3 * i + 1], "") or "").strip(), d, inilir, ister,
                          kutu_ister, belge, badres))
            if inilir:
                ikinci.append(_m(bus, y, ERISIM, "GetChildren"))
            if kutu_ister:
                ikinci.append(_m(bus, y, BILESEN, "GetExtents", "u", (koord,)))
            if belge:
                ikinci.append(_m(bus, y, "org.a11y.atspi.Document", "GetAttributes"))
        r2 = yol.toplu(ikinci)
        j, yeni = 0, []
        for (y, anahtar, derin, alan, rol, ad, d, inilir, ister, kutu_ister, belge, badres) in isler:
            cocuk = kutu = hkutu = None
            if inilir:
                cocuk, j = _deg(r2[j]), j + 1
                if cocuk is None and (derin or belge):
                    kesik = True  # belge içinde çocuklar okunamadı: alt dal listede yok
            if kutu_ister:
                e, j = _deg(r2[j]), j + 1
                if not (e and len(e) == 4):
                    kesik = kesik or ister  # istenen ögenin kutusu okunamadı
                elif e[2] > 0 and e[3] > 0:
                    hkutu = (e[0] + koken[0], e[1] + koken[1], e[2], e[3])
                    if e[0] > -1 and e[1] > -1:
                        kutu = hkutu
            alt_alan, alt_derin = alan, derin
            if belge:
                oz, j = (_deg(r2[j], {}) or {}), j + 1
                belgeler.append({"ad": ad, "adres": oz.get("DocURL") or oz.get("URI", ""), "durum": d, "derinlik": derin + 1, "kutu": kutu})
                alt_derin = derin + 1
                # Firefox belge adresini "DocURL", Chromium "URI" özniteliğinde verir (ABM-F3-R2: Chromium adresi boştu)
                badres = oz.get("DocURL") or oz.get("URI", "") or ""  # çocuklar bu belgeye ait (insan doğrulaması)
            if kutu and (belge or rol == "internal frame"):
                alt_alan = _kesisim(alan, kutu)
            if ister:
                ogeler.append({"_yol": y, "_anahtar": anahtar, "_alan": alan, "_d": d, "_kutu": kutu, "_hkutu": hkutu,
                               "_derin": derin, "_adres": badres, "rol": rol, "ad": ad})
            for n, (b_, cy) in enumerate(cocuk or ()):
                if b_ == bus:
                    yeni.append((cy, anahtar + (n,), alt_derin, alt_alan, badres))
                elif alt_derin:
                    kesik = True  # belge içinde başka veri yolundaki çocuk: okunmadı
        seviye = yeni
    if durum is not None:
        durum["kesik"] = kesik or bool(seviye)  # seviye kaldıysa düğüm sınırı doldu
    return ogeler, belgeler, sayi


def _kesisim(a, b):
    if a is None:
        return b
    x, y = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (x, y, max(0, x2 - x), max(0, y2 - y))


def _icinde(kutu, alan) -> bool:
    if not kutu:
        return False
    if alan is None:
        return True
    cx, cy = kutu[0] + kutu[2] / 2, kutu[1] + kutu[3] / 2
    return alan[0] <= cx < alan[0] + alan[2] and alan[1] <= cy < alan[1] + alan[3]


def _durum_listesi(d: set[str], rol: str) -> list[str]:
    liste = [] if ("enabled" in d and "sensitive" in d) else ["devre_disi"]
    liste += [ad for at, ad in _DURUM_ADI if at in d]
    if rol == "combo box" and "expanded" not in d:
        liste.append("kapali")
    return liste


def _bicimle(o, ad_siniri, bus=None) -> dict:
    from .guvenlik import hassas_mi
    ad = o["ad"]
    kisa = ad if not ad_siniri or len(ad) <= ad_siniri else ad[:ad_siniri - 1] + "…"
    k = o["_kutu"]
    sonuc = {"ad": kisa, "rol": o["rol"], "durum": _durum_listesi(o["_d"], o["rol"]),
             "kutu": list(k) if k else None,
             "merkez": [round(k[0] + k[2] / 2), round(k[1] + k[3] / 2)] if k else None,
             "gorunur": o["_gorunur"]}
    if o["_derin"] > 1:
        sonuc["cerceve"] = o["_derin"] - 1  # iç içe belge (iframe) derinliği
        if o.get("_adres"):
            sonuc["_belge_adres"] = o["_adres"]  # ögenin ait olduğu iç belgenin adresi (iç alan: ajana çıkmaz)
    if hassas_mi(ad):
        sonuc["hassas"] = True
    if bus:  # erişilebilirlik eylemi için nesne adresi (iç alan; varsayılan çıktıda yok) + belge içi çocuk-sıra
        sonuc["_bus"], sonuc["_yol"] = bus, o["_yol"]  # anahtarı (MCP observe: sorgu eşleşmesinin ataları)
        sonuc["_anahtar"] = list(o["_anahtar"])
    return sonuc


def _ayrinti_ekle(yol: _Yol, bus: str, ogeler: list[dict], ham: list[dict]) -> None:
    """Yalnız döndürülecek ögeler için: bağlantıların adresi (href), giriş alanlarının değeri, seçim kutusunun seçili
    seçeneği. Parola alanının değeri OKUNMAZ. Giriş alanı değeri erisim._deger_temizle ile süzülür (masaüstü yoluyla
    AYNI): ad, açıklama ve autocomplete/id/placeholder/text-input-type nitelikleri kart/parola/PIN/OTP/CVC alanı
    gösteriyorsa değer "***"; yalnız maske karakterlerinden oluşan değer atlanır; denetim karakterleri ayıklanır."""
    m, hedef = [], []
    yol_of = {id(o): h["_yol"] for o, h in zip(ogeler, ham)}
    for o, h in zip(ogeler, ham):
        if o["rol"] == "link":
            m.append(_m(bus, h["_yol"], "org.a11y.atspi.Hyperlink", "GetURI", "i", (0,)))
            hedef.append((o, "href"))
        elif o["rol"] in ("entry", "spin button"):
            m.append(_m(bus, h["_yol"], "org.a11y.atspi.Text", "GetText", "ii", (0, -1)))
            hedef.append((o, "deger"))
            # değer maskesi için ipuçları (ad zaten ham["ad"]'da; kırpılmamış hâli)
            m.append(_ozellik(bus, h["_yol"], "Description"))
            hedef.append((o, "_aciklama"))
            m.append(_m(bus, h["_yol"], ERISIM, "GetAttributes"))
            hedef.append((o, "_nitelik"))
        elif o["rol"] == "combo box":
            m.append(_m(bus, h["_yol"], ERISIM, "GetChildren"))
            hedef.append((o, "_secenek"))
    r = yol.toplu(m)
    secenek_m, secenek_o = [], []
    ad_of = {id(o): h.get("ad", "") for o, h in zip(ogeler, ham)}
    degerler = []  # (öge, ham değer, [açıklama], {nitelikler}): süzme tüm ipuçları gelince
    for (o, alan), v in zip(hedef, r):
        if alan == "_aciklama":
            degerler[-1][2].append(_ozd(v, "") or "")
            continue
        if alan == "_nitelik":
            nit = _deg(v, {}) or {}
            degerler[-1][3].update(nit if isinstance(nit, dict) else {})
            continue
        v = _deg(v)
        if alan == "deger":
            degerler.append((o, v, [], {}))
        elif alan == "_secenek":
            for b_, y in (v or [])[:1]:  # select → (menü) → seçenekler
                secenek_m.append(_m(b_, y, ERISIM, "GetChildren"))
                secenek_o.append(o)
        elif v:
            o[alan] = v if len(v) <= 300 else v[:299] + "…"
    if degerler:
        from .erisim import _DEGER_NITELIKLERI, _deger_temizle
        # Firefox, ögenin niteliklerini ilk sorguda BOŞ ({}) döndürebiliyor (ölçüldü: sayfadaki ilk giriş alanı; ikinci
        # sorguda id/placeholder-text/text-input-type gelir) → değeri olan ve niteliği boş alanlar bir kez daha sorulur
        bos = [t for t in degerler if t[1] and not t[3]]
        if bos:
            for t, v in zip(bos, yol.toplu([_m(bus, yol_of[id(t[0])], ERISIM, "GetAttributes") for t in bos])):
                nit = _deg(v, {}) or {}
                t[3].update(nit if isinstance(nit, dict) else {})
        for o, v, aciklama, nit in degerler:
            if not v or not isinstance(v, str):
                continue
            ipucu = [ad_of.get(id(o), "") or o.get("ad", "")] + aciklama
            ipucu += [str(nit[a]) for a in _DEGER_NITELIKLERI if nit.get(a)]
            if str(nit.get("text-input-type", "")).lower() == "password":
                ipucu.append("parola")
            v = _deger_temizle(v, *ipucu)
            if v:
                o["deger"] = v if len(v) <= 300 else v[:299] + "…"
    if not secenek_m:
        return
    listeler = yol.toplu(secenek_m)
    sorgu, sahip = [], []
    for o, v in zip(secenek_o, listeler):
        for b_, y in (_deg(v) or [])[:200]:
            sorgu += [_ozellik(b_, y, "Name"), _m(b_, y, ERISIM, "GetState")]
            sahip.append(o)
    r = yol.toplu(sorgu)
    for i, o in enumerate(sahip):
        if "selected" in _durumlar(r[2 * i + 1]) and "deger" not in o:
            o["deger"] = _ozd(r[2 * i], "") or ""


# ---------------------------------------------------------------- dış arayüz

def oku(k, sorgu=None, roller=None, gorunur=True, en_cok=60, atla=0, ad_siniri=_AD_SINIRI, ayrinti=True,
        yol_ver=False, cerceve_metni=False) -> dict:
    """Sayfa ögeleri + sayfalama bilgisi. → {"ogeler": [...], "toplam": n, "atla": a, "sonraki": a2 | None,
    "sayfa": sayfa bilgisi, "sure": sn, "dugum": yürünen düğüm}. Ögeler belge sırasında.

    sorgu: ada göre süzme (Türkçe harf/büyük-küçük duyarsız; tam > içerir > benzer, erisim.erisim_ara ile aynı)
    roller: AT-SPI rol adları ya da takma adlar ("düğme", "bağlantı", "giriş", "başlık"…); None = etkileşimli ögeler
    gorunur: True = yalnız görünür (kaydırma alanı içinde, gizli değil); False = görünmeyenler de (gorunur: false)
    en_cok / atla: sayfalama (en_cok=0: hepsi); ad_siniri: ad kırpma (0 = kırpma); ayrinti: href / değer / seçili seçenek
    yol_ver: ögelere erişilebilirlik kimliği (_bus + _yol: İKİSİ BİRLİKTE; yalnız yol başka uygulamaya gidebilir) ekle
    cerceve_metni: iç belgelerde (iframe) rolden bağımsız metin ögeleri de gelsin (insan doğrulaması: "Success!" işareti)

    Sayfa belirsizse (çerçeve ↔ pencere kanıtlanamadı ya da belge adı pencere başlığının gerisinde: tıklama/gezinme
    sonrası) kısa yeniden deneme, KESİN üst sınır erisim.BELIRSIZ_SURE (≤ 1 sn); sonra Dur 6, içerik yok."""
    from .erisim import BELIRSIZ_ARA, BELIRSIZ_SURE, SAYFA_BELIRSIZ
    t0 = time.monotonic()
    while True:
        try:
            return _oku_bir(t0, k, sorgu, roller, gorunur, en_cok, atla, ad_siniri, ayrinti, yol_ver, cerceve_metni)
        except Dur as e:
            if e.tur != SAYFA_BELIRSIZ or time.monotonic() + BELIRSIZ_ARA >= t0 + BELIRSIZ_SURE:
                raise
            time.sleep(BELIRSIZ_ARA)


def _oku_bir(t0, k, sorgu, roller, gorunur, en_cok, atla, ad_siniri, ayrinti, yol_ver, cerceve_metni) -> dict:
    au, yol, bus, cerceve, koord, koken, konum = _baglam(k)
    try:
        ham, belgeler, dugum = _yuru(yol, bus, cerceve, koord, koken, _rol_kumesi(roller), gorunur,
                                     cerceve_metni=cerceve_metni)
        for o in ham:
            o["_gorunur"] = ("showing" in o["_d"] and "visible" in o["_d"] and _icinde(o["_kutu"], o["_alan"]))
        ham = [o for o in ham if o["_kutu"] or not gorunur]
        if gorunur:
            ham = [o for o in ham if o["_gorunur"]]
        ham.sort(key=lambda o: o["_anahtar"])
        if sorgu:
            from .erisim import erisim_ara
            ham, _kademe = erisim_ara(ham, sorgu)
        toplam = len(ham)
        atla = max(0, int(atla or 0))
        secili = ham[atla:atla + en_cok] if en_cok else ham[atla:]
        ogeler = [_bicimle(o, ad_siniri, bus if yol_ver else None) for o in secili]
        if ayrinti and ogeler:
            _ayrinti_ekle(yol, bus, ogeler, secili)
        for i, o in enumerate(ogeler):
            o["no"] = atla + i + 1
        ust = min(belgeler, key=lambda b: b["derinlik"]) if belgeler else None
        pencere_basligi = au.baslik(k)
        _belge_pencereye_ait(ust, pencere_basligi)
        sayfa = _sayfa_ozeti(ust, pencere_basligi, len(belgeler))
        sayfa["konum"] = konum  # hangi koordinat çerçevesinde geldiği (None = doğrulanamadı)
        ic = [{"ad": b["ad"], "adres": b["adres"], "kutu": list(b["kutu"]) if b.get("kutu") else None}
              for b in belgeler if b["derinlik"] > 1][:12]
        if ic:  # gömülü belgeler (iframe): insan doğrulaması algısı (dogrulama_sinamasi) adreslerine bakar
            sayfa["cerceveler"] = ic
        sayfa["konum_dogrulandi"] = konum is not None
        son = atla + len(ogeler)
        return {"ogeler": ogeler, "toplam": toplam, "atla": atla, "sonraki": son if son < toplam else None,
                "sayfa": sayfa, "sure": round(time.monotonic() - t0, 3), "dugum": dugum}
    finally:
        yol.kapat()


_AYRAC = ("—", "–", "-", "|", "·", ":")  # tarayıcı pencere başlığında sayfa başlığından sonraki ayraç


def _belge_pencereye_ait(belge, pencere_basligi) -> None:
    """SOAK-FIX ikinci kilit (savunma derinliği; kimlik kanıtı çerçeve seçimindedir, erisim.cerceve_karari): pencere
    başlığı okunan üst belgenin başlığıyla AYNI ya da onunla BAŞLAYIP ayraçla sürmeli ("<sayfa> — Mozilla Firefox",
    "<sayfa> - Chromium"). Alt dizge yetmez (SOAK-FIX-R1 DÜŞÜK 4: "a", "Firefox", "Banka" her başlıkta geçer). Boş
    belge adı (yükleniyor) karşılaştırılamaz; kimlik yine çerçeve seçiminden. Tutmazsa Dur 6 (tur SAYFA_BELIRSIZ); ileti
    OKUNAN belgenin başlığını İÇERMEZ (başka pencereye ait olabilir: ORTA 3), yalnız bu pencerenin başlığı."""
    import unicodedata

    from .erisim import SAYFA_BELIRSIZ
    from .guvenlik import baslik_goster

    def norm(s):
        return " ".join(unicodedata.normalize("NFC", s or "").split())
    ad, pb = norm(belge["ad"]) if belge else "", norm(pencere_basligi)
    if not ad or pb == ad or (pb.startswith(ad) and pb[len(ad):].lstrip().startswith(_AYRAC)):
        return
    raise Dur(BULUNAMADI, _("sayfa belirsiz: okunan sayfa bu pencerenin başlığıyla ({pencere}) uyuşmuyor; sayfa geçişi "
                            "sürüyor ya da sayfa başka pencereye ait; içerik verilmedi, kısa süre sonra yeniden dene"
                            ).format(pencere=baslik_goster(pencere_basligi)), tur=SAYFA_BELIRSIZ)


def _sayfa_ozeti(belge, pencere_basligi, belge_sayisi) -> dict:
    from .guvenlik import hassas_sayfa_kalibi
    from .ocr import katla
    if belge is None:
        return {"baslik": "", "adres": "", "yukleniyor": None, "pencere": pencere_basligi, "belge": 0}
    s = {"baslik": belge["ad"], "adres": belge["adres"], "yukleniyor": "busy" in belge["durum"],
         "pencere": pencere_basligi, "belge": belge_sayisi}
    if belge.get("kutu"):
        s["gorus"] = list(belge["kutu"])  # üst belgenin görüş alanı (pencere pikseli): kaydırma yönü için
    if hassas_sayfa_kalibi().search(katla(belge["ad"] or "")):
        s["hassas_sayfa"] = True
    return s


def sayfa_ogeleri(k, sorgu=None, roller=None, gorunur=True, en_cok=60, atla=0, ad_siniri=_AD_SINIRI,
                  ayrinti=True) -> list[dict]:
    """Penceredeki web sayfasının ögeleri (belge sırasında). Her öge: ad, rol, durum (devre_disi/isaretli/odakli/
    secili/acik/kapali/…), kutu [x, y, genişlik, yükseklik] (PENCERE pikseli; tıklama komutlarıyla aynı sistem),
    merkez [x, y], gorunur, no; varsa href / deger, iframe içindeyse cerceve, hassas düğme adıysa hassas: True.
    Ayrıntılı açıklama: oku()."""
    return oku(k, sorgu, roller, gorunur, en_cok, atla, ad_siniri, ayrinti)["ogeler"]


def sayfa_bilgisi(k) -> dict:
    """Etkin sekmenin belgesi: baslik, adres, yukleniyor, pencere (başlığı), belge (iframe dahil belge sayısı);
    başlık ödeme/sipariş sayfasıysa hassas_sayfa: True."""
    return oku(k, roller=["__yok__"], en_cok=0, ayrinti=False)["sayfa"]


_EYLEM = "org.a11y.atspi.Action"
_EN_COK_EYLEM = 32  # bundan çok eylem bildiren öge "bilinmiyor" sayılır


def _eylemleri_oku(yol, bus, yollar) -> dict:
    """Ögelerin eylem adları {nesne yolu: [ad…]}: Action arayüzü yoksa [] (kanıtlı eylemsiz); arayüz/sayı/ad
    okunamadıysa None (bilinmiyor → çağıran tıklanır sayar)."""
    yollar = list(dict.fromkeys(yollar))
    if not yollar:
        return {}
    sonuc: dict = {}
    sayilacak = []
    for y, a in zip(yollar, yol.toplu([_m(bus, y, ERISIM, "GetInterfaces") for y in yollar]), strict=True):
        arayuzler = _deg(a)
        if arayuzler is None:
            sonuc[y] = None
        elif _EYLEM not in arayuzler:
            sonuc[y] = []
        else:
            sayilacak.append(y)
    if not sayilacak:
        return sonuc
    istek, sahip = [], []
    for y, n_ in zip(sayilacak, yol.toplu([_ozellik(bus, y, "NActions", _EYLEM) for y in sayilacak]), strict=True):
        n = _ozd(n_)
        if not isinstance(n, int) or n < 0 or n > _EN_COK_EYLEM:
            sonuc[y] = None
            continue
        sonuc[y] = []
        for i in range(n):
            istek.append(_m(bus, y, _EYLEM, "GetName", "i", (i,)))
            sahip.append(y)
    for y, g in zip(sahip, yol.toplu(istek) if istek else [], strict=True):
        ad = _deg(g)
        if sonuc[y] is not None:
            if isinstance(ad, str):
                sonuc[y].append(ad)
            else:
                sonuc[y] = None
    return sonuc


def duzenleme_alanlari(k):
    """Hassas düğme denetimi (eylem.hassas_nokta → guvenlik.duzenleme_icerigini_ayikla) için tarayıcı sayfasının ögeleri,
    PENCERE pikseli kutularıyla: (alanlar, digerleri, dugmeler, kaplar). Belge içindeki HER rol, görünmeyen dallar dahil
    okunur (listede olmayan rol ya da gizli kaptaki örtü de satıra değebilir); kutu = ham kutu (negatif konum dahil).
    alanlar = (x, y, w, h, değer): rol entry (textarea dahil), durum editable, read_only değil, görünür, adı hassas değil
    ve kendi tıklama eylemi yok (guvenlik.alan_kanitli_mi; INCELEME-HASSAS D1); kutu görüş alanına kırpılır; değer alanın
    metni (Text.GetText; gizli alan adında — parola/OTP/PIN… — okunmaz, None). dugmeler = öbür etkileşimli ögeler (kanıtsız
    alan dahil); kaplar = alanı kapsayan ve guvenlik.duzenleme_kabi_mi olan ögeler (tıklanmadığı kanıtlı: kendi ya da
    atasının tıklaması yok); digerleri = geri kalan (alanı saran tıklanır öge dahil; INCELEME-HASSAS O2).
    None (çağıran hiçbir satırı ayıklamaz: güvenli taraf): öge konumu doğrulanamadı, okunan sayfa bu pencereye ait
    kanıtlanamadı, ağaç KESİK (düğüm sınırı, okunamayan dal/kutu; INCELEME-HASSAS O1), okuma hatası."""
    from . import guvenlik
    from .erisim import _GIZLI_ALAN
    from .ocr import katla
    try:
        au, yol, bus, cerceve, koord, koken, konum = _baglam(k)
    except Dur:
        return None
    try:
        if konum is None:  # koordinatlar doğrulanamadı: tık yolundaki gibi fail-closed
            return None
        durum: dict = {}
        ham, belgeler, _sayi = _yuru(yol, bus, cerceve, koord, koken, _TUM_ROLLER, False, durum=durum)
        if durum.get("kesik"):
            return None  # eksik liste: alana bindirilmiş düğme okunmamış olabilir
        ust = min(belgeler, key=lambda b: b["derinlik"]) if belgeler else None
        if ust is None:
            return None
        _belge_pencereye_ait(ust, au.baslik(k))
        aday = []  # (öge, görüş alanına kırpılmış kutu)
        for o in ham:
            kutu, d = o["_kutu"], o["_d"]
            if (o["rol"] == "entry" and kutu and "editable" in d and "read_only" not in d and "showing" in d
                    and "visible" in d):
                gorus = tuple(_kesisim(o["_alan"], tuple(kutu)) if o["_alan"] else kutu)
                if gorus[2] > 0 and gorus[3] > 0:
                    aday.append((o, gorus))
        aday_kutu = [g for _o, g in aday]
        kap_aday = [o for o in ham if o["rol"] not in ETKILESIMLI and o.get("_hkutu")
                    and guvenlik.alani_kapsar_mi(o["_hkutu"], aday_kutu)]
        okunur = [o for o, _g in aday if not _GIZLI_ALAN.search(katla(o["ad"] or ""))]
        metin = yol.toplu([_m(bus, o["_yol"], "org.a11y.atspi.Text", "GetText", "ii", (0, -1)) for o in okunur]) \
            if okunur else []
        degerler = {id(o): v for o, v in zip(okunur, (_deg(m_) for m_ in metin), strict=True)}
        eylemler = _eylemleri_oku(yol, bus, [o["_yol"] for o, _g in aday] + [o["_yol"] for o in kap_aday])
    except Dur:
        return None
    finally:
        yol.kapat()
    alanlar, digerleri, dugmeler, kaplar = [], [], [], []
    alan_idleri = set()
    for o, gorus in aday:
        if guvenlik.alan_kanitli_mi(o["ad"], eylemler.get(o["_yol"])):
            deger = degerler.get(id(o))
            alanlar.append((*gorus, deger if isinstance(deger, str) else None))
            alan_idleri.add(id(o))
    kanitli = [a[:4] for a in alanlar]
    for o in ham:
        kutu = o.get("_hkutu")
        if id(o) in alan_idleri or not kutu:
            continue
        kutu = tuple(kutu)
        if o["rol"] in ETKILESIMLI:
            dugmeler.append(kutu)
        elif guvenlik.duzenleme_kabi_mi(kutu, eylemler.get(o["_yol"]), kanitli):
            kaplar.append(kutu)
        else:
            digerleri.append(kutu)
    return alanlar, digerleri, dugmeler, kaplar


def oge_ve_sayfa(k, ad, rol=None, sira=None, gorunur=True, yol_ver=False):
    """oge_bul ile aynı seçim; ek olarak sayfa bilgisi ve okuma bilgisi. → (öge, sayfa, süre, eşleşme sırası 0…)."""
    s = oku(k, sorgu=ad, roller=[rol] if rol else None, gorunur=gorunur, en_cok=0, ad_siniri=0, yol_ver=yol_ver)
    bulunan = s["ogeler"]
    if not bulunan:
        raise Dur(BULUNAMADI, _("'{ad}' sayfada bulunamadı ({sn} sn)").format(ad=ad, sn=f"{s['sure']:.2f}"))
    if sira is None and len(bulunan) > 1:
        liste = "\n".join(f"  #{i} {o['rol']}: {o['ad']} {o['merkez']}" for i, o in enumerate(bulunan[:15], 1))
        raise Dur(BELIRSIZ, _("'{ad}' için {sayi} öge; sira ile seç (CLI --sira, MCP nth):\n{liste}").format(
            ad=ad, sayi=len(bulunan), liste=liste))
    sira = sira or 1
    if not 1 <= sira <= len(bulunan):
        raise Dur(1, _("sira 1..{en_cok} olmalı").format(en_cok=len(bulunan)))
    return bulunan[sira - 1], s["sayfa"], s["sure"], sira - 1


def oge_bul(k, ad, rol=None, sira=None, gorunur=True) -> dict:
    """Ada (ve isteğe bağlı role) göre TEK öge. Birden çok eşleşmede sira (1…) verilmezse Dur 5 (liste iletide);
    yoksa Dur 6."""
    return oge_ve_sayfa(k, ad, rol, sira, gorunur)[0]


def ogeleri_yaz(ogeler, dosya=None) -> None:
    """Kısa metin çıktısı (CLI için): #no (merkez) rol: ad [durum] {hassas} → adres = değer."""
    import sys
    f = dosya or sys.stdout
    for o in ogeler:
        ek = (" [" + ", ".join(o["durum"]) + "]") if o["durum"] else ""
        ek += "" if o["gorunur"] else " " + _("(görünmüyor)")
        ek += (" " + _("HASSAS")) if o.get("hassas") else ""
        ek += f" → {o['href'][:80]}" if o.get("href") else ""
        ek += f" = {o['deger'][:60]!r}" if o.get("deger") else ""
        ek += " " + _("(çerçeve {n})").format(n=o["cerceve"]) if o.get("cerceve") else ""
        m = f"({o['merkez'][0]},{o['merkez'][1]})" if o["merkez"] else "(?)"
        print(f"  #{o['no']} {m} {o['rol']}: {o['ad'] or _('(adsız)')}{ek}", file=f)


# ---------------------------------------------------------------- araçların (MCP / CLI / tık) ortak girişi

# Tarayıcı / Electron pencere sınıfları: click-element önce sayfa ögelerine bakar (başka pencerelerde ağaç taraması
# yapılmaz). Sınıf listede yoksa `web` okuma komutu / read_text(source="web") yine çalışır.
# Eşleşme SINIRLI: sınıf . - _ boşluk ile parçalanır ve tarayıcı adı tam bir parça olmalı ("org.mozilla.firefox",
# "microsoft-edge-dev", "app.zen_browser.zen", "chrome-<uygulama>-Default" evet; zenity, hedgewars, knowledge-base,
# citizen, operator, chromatic HAYIR — tarayıcı sanılırsa tıklamalar sayfa ağacına yönlenir).
_TARAYICI_SINIFI = (r"(?:^|[.\-_ ])(?:firefox\w*|mozilla\w*|librewolf|waterfox\w*|floorp|zen|chrom(?:e|ium)\w*|brave|"
                    r"vivaldi|opera|edge|msedge|thorium|epiphany|falkon|electron\d*)(?=$|[.\-_ ])")


def tarayici_sinifi_mi(sinif: str) -> bool:
    """Pencere sınıfı (WM_CLASS / app_id) bir tarayıcınınki mi (ad parçalarıyla tam eşleşme)."""
    import re
    sinif = (sinif or "").lower()
    if re.search(_TARAYICI_SINIFI, sinif):
        return True
    from .uygulama import CHROMIUM_IKILILERI
    return sinif in CHROMIUM_IKILILERI


def tarayici_mi(k) -> bool:
    if k == EKRAN or not k:
        return False
    try:
        sinif = sec(k).sinif(k) or ""
    except Dur:
        return False
    return tarayici_sinifi_mi(sinif)


IPUCU_ERISIM = _("İpucu: tarayıcı erişilebilirlik açıkken başlamamış olabilir; kapatıp Deskhand ile yeniden aç "
                 "(ac / open_app: Firefox GNOME_ACCESSIBILITY=1, Chromium --force-renderer-accessibility ile başlatılır; "
                 "ön planda tarayıcı zaten açıksa yeni açılış çalışan sürece katılır, önce onu kapat). Kalıcı çözüm: "
                 "deskhand doctor")


def hazirla(k) -> None:
    """Okuma/tık öncesi ortak denetim: pencere kipi, yasak pencere (10), erişilebilirlik veri yolu açık (kendiliğinden)."""
    from . import api
    if k == EKRAN or not k:
        raise Dur(1, _("web ögeleri pencere ister (masaüstü kipi değil)"))
    if api.yasak_mi(k):
        raise Dur(10, _("YASAK pencere: ağacı okunmaz"))
    from .erisim import erisim_ac_garanti
    erisim_ac_garanti()


def oku_korumali(k, sorgu=None, roller=None, gorunur=True, en_cok=60, atla=0, bekle=0.0) -> dict:
    """oku() + araç düzeyi denetimler ve anlaşılır hatalar: yasak pencere 10, pencere kipi 1, uygulaması ağaçta yok ya
    da web belgesi yok → ipucuyla Dur. bekle: sorgu görünene dek en çok bu kadar sn."""
    hazirla(k)
    bitis = time.monotonic() + max(0.0, bekle)
    while True:
        try:
            s = oku(k, sorgu, roller, gorunur, en_cok, atla)
        except Dur as e:
            if e.kod in (BULUNAMADI, ARAC_EKSIK) and "İpucu" not in e.mesaj:
                raise Dur(e.kod, e.mesaj + "\n" + IPUCU_ERISIM, tur=getattr(e, "tur", None))
            raise
        if s["sayfa"]["belge"] == 0:
            raise Dur(BULUNAMADI, _("pencerede web belgesi yok (sayfa yüklenmedi, pencere bir tarayıcı değil ya da "
                                    "tarayıcının erişilebilirliği kapalı)") + "\n" + IPUCU_ERISIM)
        if s["ogeler"] or not sorgu or time.monotonic() >= bitis:
            return s
        time.sleep(0.25)


def _eylem_birincil(liste):
    sira = {a.lower(): i for i, a in enumerate(liste)}
    for ad in ("click", "press", "activate", "toggle", "jump", "check", "uncheck", "select", "open"):
        if ad in sira:
            return sira[ad]
    return None


def eylem_yap(k, oge, eylem=None) -> dict:
    """Öge için erişilebilirlik EYLEMİ (gerçek fare/klavye girdisi yok). oge: oku(yol_ver=True) çıktısı (_bus + _yol
    BİRLİKTE). Pencere düzeyi denetimler ÇAĞIRANDA (erisim._web_eylem); çerçeve düzeyi burada (_baglam "eylem").
    → {"eylem": çalışan, "eylemler": tümü, "tamam": bool}."""
    if not oge.get("_bus") or not oge.get("_yol"):
        raise Dur(1, _("öge kimliği yok (yol_ver)"))
    # eylemden HEMEN önce çerçeve yeniden seçilir ve eylem düzeyinde denetlenir (panel/yasak/kendi istemci/seviye):
    # öge, pencerenin süreç ağacındaki bu çerçevenin bağlantısında olmalı (başka uygulamaya eylem gitmez)
    _au, yol, bus, *_x = _baglam(k, "eylem")
    if getattr(_au, "ad", "") != "sanal":  # gerçek oturumun a11y yoluna DoAction = gerçek ekranda tık
        from .hata import gercek_ekran_denetle
        gercek_ekran_denetle(_("erişilebilirlik eylemi (web)"))
    try:
        if oge["_bus"] != bus:
            raise Dur(8, _("web ögesi artık pencerenin erişilebilirlik bağlantısında değil (uygulama değişti); "
                           "yeniden oku"))
        arayuz = "org.a11y.atspi.Action"
        # GetActions bazı tarayıcılarda anlamsız (';;') döner: NActions + GetName(i) güvenilir yol
        n = int(_ozd(yol.toplu([_ozellik(oge["_bus"], oge["_yol"], "NActions", arayuz)])[0], 0) or 0)
        liste = [(_deg(g_, "") or "") for g_ in yol.toplu([_m(oge["_bus"], oge["_yol"], arayuz, "GetName", "i", (i,))
                                                          for i in range(n)])] if n else []
        if not liste:
            raise Dur(BULUNAMADI, _("öge eylem arayüzü sunmuyor (Action yok): fare ile tıkla"))
        if eylem:
            sira = next((i for i, a in enumerate(liste) if a.lower() == eylem.lower()), None)
            if sira is None:
                raise Dur(BULUNAMADI, _("'{eylem}' eylemi yok; ögenin eylemleri: {liste}").format(
                    eylem=eylem, liste=", ".join(liste)))
        else:
            sira = _eylem_birincil(liste)
            if sira is None:
                raise Dur(BULUNAMADI, _("birincil eylem yok; ögenin eylemleri: {liste}").format(liste=", ".join(liste)))
        r = yol.toplu([_m(oge["_bus"], oge["_yol"], arayuz, "DoAction", "i", (sira,))], yeniden=False)[0]
        return {"eylem": liste[sira], "eylemler": liste, "tamam": bool(r and r[0])}
    finally:
        yol.kapat()


# ---------------------------------------------------------------- CLI: web

SAYFA_BOYUTU = 60


def k_web(a):
    """Tarayıcı penceresindeki sayfa ögeleri (erişilebilirlik ağacından): `web <kimlik> [sorgu] [--rol R] [--hepsi]
    [--sayfa N]`. Çıktı: başlık satırı + `#no (merkez x,y) rol: ad [durum]`; merkez PENCERE pikselidir (click ile aynı)."""
    hepsi = bool(getattr(a, "hepsi", False))
    sayfa_no = max(1, int(getattr(a, "sayfa", 1) or 1))
    atla = 0 if hepsi else (sayfa_no - 1) * SAYFA_BOYUTU
    s = oku_korumali(a.kimlik, getattr(a, "desen", None), getattr(a, "rol", None), not hepsi,
                     0 if hepsi else SAYFA_BOYUTU, atla)
    sf = s["sayfa"]
    toplam_sayfa = max(1, -(-s["toplam"] // SAYFA_BOYUTU))
    print(_("# {baslik} | {adres} | {sayi} öge gösterildi / {toplam} toplam{sayfa}, {sn} sn").format(
        baslik=sf["baslik"] or _("(başlıksız)"), adres=sf["adres"], sayi=len(s["ogeler"]), toplam=s["toplam"],
        sayfa="" if hepsi else _(", sayfa {n}/{t}").format(n=sayfa_no, t=toplam_sayfa), sn=f"{s['sure']:.2f}"))
    if sf.get("hassas_sayfa"):
        print(_("# DİKKAT: ödeme/onay sayfası: bu sayfadaki her tıklama kullanıcının onayını ister"))
    if not sf.get("konum_dogrulandi"):
        print(_("# UYARI: öge konumu doğrulanamadı (çerçeve sınırı pencere geometrisine uymuyor): tıklama yapılmaz; "
                "OCR ile metne tıklamayı dene"))
    if not s["ogeler"] and getattr(a, "desen", None):
        raise Dur(BULUNAMADI, _("bulunamadı"))
    ogeleri_yaz(s["ogeler"])
    if s["sonraki"] is not None:
        print(_("# devamı: --sayfa {n}").format(n=sayfa_no + 1))
