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

import difflib
import time

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
            bekleyen = {}
            for i in range(bas, min(bas + _PARCA, len(mesajlar))):
                s = next(self.c.outgoing_serial)
                self.c.send(mesajlar[i], serial=s)
                bekleyen[s] = i
            bitis = time.monotonic() + sure
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


def _baglam(k):
    """→ (arka uç, _Yol, uygulama veri yolu adı, çerçeve yolu, koordinat türü, köken (ox, oy), konum: çerçeve adı | None).
    konum None = çerçeve sınırı pencere geometrisiyle eşleşmedi: koordinatlar doğrulanamadı (okuma uyarır, tık reddeder)."""
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
    yol = _Yol(adres)
    try:
        bus, cerceve = _cerceve_bul(yol, pid, baslik)
        geo = tuple(au.geometri(k))
        ekran, pencere = yol.toplu([_m(bus, cerceve, BILESEN, "GetExtents", "u", (SCREEN,)),
                                    _m(bus, cerceve, BILESEN, "GetExtents", "u", (WINDOW,))])
        cozum = konum_coz(geo, _deg(ekran), _deg(pencere))
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


def _cerceve_bul(yol: _Yol, pid: int, baslik: str) -> tuple[str, str]:
    """Pencerenin süreç kimliğine ait uygulamanın, başlığı pencereye en çok uyan üst düzey çerçevesi."""
    dbus = ("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus")
    adlar = [a for a in (_deg(yol.toplu([_m(*dbus, "ListNames")])[0], []) or []) if a.startswith(":")]
    pidler = yol.toplu([_m(*dbus, "GetConnectionUnixProcessID", "s", (a,)) for a in adlar])
    uygulamalar = [a for a, p in zip(adlar, pidler) if p and (not pid or int(p[0]) == pid)]
    if not uygulamalar:
        raise Dur(BULUNAMADI, _("pencerenin uygulaması erişilebilirlik ağacında yok (pid {pid}). Firefox "
                                "GNOME_ACCESSIBILITY=1 ile, Chromium --force-renderer-accessibility ile "
                                "başlatılmalı").format(pid=pid))
    cocuklar = yol.toplu([_m(a, KOK_YOL, ERISIM, "GetChildren") for a in uygulamalar])
    adaylar = [(b_, y) for c in cocuklar if c for b_, y in c[0]]
    if not adaylar:
        raise Dur(BULUNAMADI, _("uygulamanın erişilebilirlik ağacında pencere yok (pid {pid})").format(pid=pid))
    adlar_ = yol.toplu([_ozellik(a, y, "Name") for a, y in adaylar])
    durum = yol.toplu([_m(a, y, ERISIM, "GetState") for a, y in adaylar])

    def puan(i):
        ad = _ozd(adlar_[i], "") or ""
        benz = 1.0 if ad and baslik and (ad == baslik or ad in baslik or baslik in ad) else \
            difflib.SequenceMatcher(None, ad, baslik).ratio()
        d = _durumlar(durum[i])
        return (benz, "active" in d, "showing" in d)
    en_iyi = max(range(len(adaylar)), key=puan)
    if len(adaylar) > 1 and puan(en_iyi)[0] < 0.6:
        raise Dur(BULUNAMADI, _("pencere erişilebilirlik ağacında bulunamadı ({baslik})").format(baslik=repr(baslik)))
    return adaylar[en_iyi]


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


def _yuru(yol: _Yol, bus: str, cerceve: str, koord: int, koken, roller: set[str] | None, gorunur: bool,
          en_cok_dugum: int = 30000):
    """Çerçeveden başlayıp etkin (SHOWING) belge(ler)in ögelerini topla → (ham ögeler, belgeler, düğüm sayısı).
    Seviye seviye iki boru hattı turu: (1) rol + ad + durum, (2) gerekenlere alt ögeler + kutu (+ belge adresi).
    Tarayıcı arayüzünde yalnız görünen dallardan belgeye inilir (arka plan sekmelerinin belgeleri atlanır); belge
    içinde gorunur=True ise görünmeyen (SHOWING olmayan) dallara inilmez. Görüş alanı: en yakın çerçeve/belge kutusu
    (iframe'de üst alanla kesişimi) — kaydırma alanı dışındaki öge gorunur=False olur."""
    istenen = roller if roller is not None else ETKILESIMLI
    seviye = [(cerceve, (), 0, None)]  # (yol, belge sırası anahtarı, belge derinliği, görüş alanı)
    ogeler, belgeler, sayi = [], [], 0
    while seviye and sayi < en_cok_dugum:
        sayi += len(seviye)
        m = []
        for y, *_ in seviye:
            m += [_m(bus, y, ERISIM, "GetRoleName"), _ozellik(bus, y, "Name"), _m(bus, y, ERISIM, "GetState")]
        r = yol.toplu(m)
        isler, ikinci = [], []
        for i, (y, anahtar, derin, alan) in enumerate(seviye):
            rol = _deg(r[3 * i], "") or ""
            d = _durumlar(r[3 * i + 2])
            if not rol or "defunct" in d:
                continue
            belge = rol in _BELGE
            if belge and "showing" not in d and not (derin and not gorunur):
                continue  # arka plandaki sekmenin belgesi (ya da gizli iframe)
            if derin == 0 and not belge:  # tarayıcı arayüzü: yalnız görünen dallar, belgeye doğru
                inilir = rol not in _KROM_BUDA and rol not in _YAPRAK and ("showing" in d or y == cerceve)
                ister = False
            else:
                ister = rol in istenen
                inilir = (rol not in _YAPRAK and not (rol == "combo box" and "expanded" not in d)
                          and (belge or not gorunur or "showing" in d))
            kutu_ister = ister or belge or rol == "internal frame"
            isler.append((y, anahtar, derin, alan, rol, (_ozd(r[3 * i + 1], "") or "").strip(), d, inilir, ister,
                          kutu_ister, belge))
            if inilir:
                ikinci.append(_m(bus, y, ERISIM, "GetChildren"))
            if kutu_ister:
                ikinci.append(_m(bus, y, BILESEN, "GetExtents", "u", (koord,)))
            if belge:
                ikinci.append(_m(bus, y, "org.a11y.atspi.Document", "GetAttributes"))
        r2 = yol.toplu(ikinci)
        j, yeni = 0, []
        for (y, anahtar, derin, alan, rol, ad, d, inilir, ister, kutu_ister, belge) in isler:
            cocuk = kutu = None
            if inilir:
                cocuk, j = _deg(r2[j]), j + 1
            if kutu_ister:
                e, j = _deg(r2[j]), j + 1
                if e and len(e) == 4 and e[2] > 0 and e[3] > 0 and e[0] > -1 and e[1] > -1:
                    kutu = (e[0] + koken[0], e[1] + koken[1], e[2], e[3])
            alt_alan, alt_derin = alan, derin
            if belge:
                oz, j = (_deg(r2[j], {}) or {}), j + 1
                belgeler.append({"ad": ad, "adres": oz.get("DocURL", ""), "durum": d, "derinlik": derin + 1, "kutu": kutu})
                alt_derin = derin + 1
            if kutu and (belge or rol == "internal frame"):
                alt_alan = _kesisim(alan, kutu)
            if ister:
                ogeler.append({"_yol": y, "_anahtar": anahtar, "_alan": alan, "_d": d, "_kutu": kutu,
                               "_derin": derin, "rol": rol, "ad": ad})
            for n, (b_, cy) in enumerate(cocuk or ()):
                if b_ == bus:
                    yeni.append((cy, anahtar + (n,), alt_derin, alt_alan))
        seviye = yeni
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
    if hassas_mi(ad):
        sonuc["hassas"] = True
    if bus:  # erişilebilirlik eylemi için nesne adresi (iç alan; varsayılan çıktıda yok)
        sonuc["_bus"], sonuc["_yol"] = bus, o["_yol"]
    return sonuc


def _ayrinti_ekle(yol: _Yol, bus: str, ogeler: list[dict], ham: list[dict]) -> None:
    """Yalnız döndürülecek ögeler için: bağlantıların adresi (href), giriş alanlarının değeri, seçim kutusunun seçili
    seçeneği. Parola alanının değeri OKUNMAZ."""
    m, hedef = [], []
    for o, h in zip(ogeler, ham):
        if o["rol"] == "link":
            m.append(_m(bus, h["_yol"], "org.a11y.atspi.Hyperlink", "GetURI", "i", (0,)))
            hedef.append((o, "href"))
        elif o["rol"] in ("entry", "spin button"):
            m.append(_m(bus, h["_yol"], "org.a11y.atspi.Text", "GetText", "ii", (0, -1)))
            hedef.append((o, "deger"))
        elif o["rol"] == "combo box":
            m.append(_m(bus, h["_yol"], ERISIM, "GetChildren"))
            hedef.append((o, "_secenek"))
    r = yol.toplu(m)
    secenek_m, secenek_o = [], []
    for (o, alan), v in zip(hedef, r):
        v = _deg(v)
        if alan == "_secenek":
            for b_, y in (v or [])[:1]:  # select → (menü) → seçenekler
                secenek_m.append(_m(b_, y, ERISIM, "GetChildren"))
                secenek_o.append(o)
        elif v:
            o[alan] = v if len(v) <= 300 else v[:299] + "…"
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
        yol_ver=False) -> dict:
    """Sayfa ögeleri + sayfalama bilgisi. → {"ogeler": [...], "toplam": n, "atla": a, "sonraki": a2 | None,
    "sayfa": sayfa bilgisi, "sure": sn, "dugum": yürünen düğüm}. Ögeler belge sırasında.

    sorgu: ada göre süzme (Türkçe harf/büyük-küçük duyarsız; tam > içerir > benzer, erisim.erisim_ara ile aynı)
    roller: AT-SPI rol adları ya da takma adlar ("düğme", "bağlantı", "giriş", "başlık"…); None = etkileşimli ögeler
    gorunur: True = yalnız görünür (kaydırma alanı içinde, gizli değil); False = görünmeyenler de (gorunur: false)
    en_cok / atla: sayfalama (en_cok=0: hepsi); ad_siniri: ad kırpma (0 = kırpma); ayrinti: href / değer / seçili seçenek
    yol_ver: ögelere erişilebilirlik kimliği (_bus + _yol: İKİSİ BİRLİKTE; yalnız yol başka uygulamaya gidebilir) ekle"""
    t0 = time.monotonic()
    au, yol, bus, cerceve, koord, koken, konum = _baglam(k)
    try:
        ham, belgeler, dugum = _yuru(yol, bus, cerceve, koord, koken, _rol_kumesi(roller), gorunur)
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
        sayfa = _sayfa_ozeti(ust, au.baslik(k), len(belgeler))
        sayfa["konum"] = konum  # hangi koordinat çerçevesinde geldiği (None = doğrulanamadı)
        sayfa["konum_dogrulandi"] = konum is not None
        son = atla + len(ogeler)
        return {"ogeler": ogeler, "toplam": toplam, "atla": atla, "sonraki": son if son < toplam else None,
                "sayfa": sayfa, "sure": round(time.monotonic() - t0, 3), "dugum": dugum}
    finally:
        yol.kapat()


def _sayfa_ozeti(belge, pencere_basligi, belge_sayisi) -> dict:
    from .guvenlik import HASSAS_SAYFA
    from .ocr import katla
    if belge is None:
        return {"baslik": "", "adres": "", "yukleniyor": None, "pencere": pencere_basligi, "belge": 0}
    s = {"baslik": belge["ad"], "adres": belge["adres"], "yukleniyor": "busy" in belge["durum"],
         "pencere": pencere_basligi, "belge": belge_sayisi}
    if belge.get("kutu"):
        s["gorus"] = list(belge["kutu"])  # üst belgenin görüş alanı (pencere pikseli): kaydırma yönü için
    if HASSAS_SAYFA.search(katla(belge["ad"] or "")):
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
_TARAYICI_SINIFI = r"firefox|mozilla|librewolf|waterfox|floorp|zen|chrom|brave|vivaldi|opera|edge|thorium|epiphany|falkon|electron"


def tarayici_mi(k) -> bool:
    import re
    if k == EKRAN or not k:
        return False
    try:
        sinif = (sec(k).sinif(k) or "").lower()
    except Dur:
        return False
    if re.search(_TARAYICI_SINIFI, sinif):
        return True
    from .uygulama import CHROMIUM_IKILILERI
    return sinif in CHROMIUM_IKILILERI


IPUCU_ERISIM = _("İpucu: tarayıcı erişilebilirlik açıkken başlamamış olabilir; kapatıp arka planda yeniden aç "
                 "(ac --arka / open_app desktop=background: erişilebilirlik kendiliğinden açılır) ya da Firefox'u "
                 "GNOME_ACCESSIBILITY=1, Chromium'u --force-renderer-accessibility ile başlat")


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
    BİRLİKTE). Güvenlik denetimleri ÇAĞIRANDA. → {"eylem": çalışan, "eylemler": tümü, "tamam": bool}."""
    if not oge.get("_bus") or not oge.get("_yol"):
        raise Dur(1, _("öge kimliği yok (yol_ver)"))
    au = sec(k)
    yol = _Yol(_veri_yolu_adresi(au, getattr(au, "ad", "") == "sanal"))
    try:
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
