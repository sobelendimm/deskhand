"""Meşgul algılama + karar (Faz 4): kullanıcı şu an bilgisayarı kullanıyor mu, iş nerede yapılsın?

durum()  → {mesgul, nedenler, ayrinti}. Sinyallerin HEPSİ SALT OKUMA (kullanıcının ekranına girdi yok):
  tam_ekran  etkin pencere tam ekran (KWin fullScreen özelliği, kde arka ucunun kd() ile salt okuma bir KWin
             betiği) ya da bir çıkışı tümüyle kaplıyor (kenarlıksız oyun penceresi). Betik çalışmazsa kde arka
             ucunun aktif/geometri/ekran_alani sorguları.
  medya      MPRIS: PlaybackStatus == "Playing" olan oynatıcı (oturum veri yolu, jeepney).
  girdi      insan klavye/fare etkinliği: Wayland ext-idle-notify (insan.Etkinlik) ile ANLIK_SN izleme, artı
             (varsa) RUNTIME_DIR/son-etkinlik.json kaydı (sürekli çalışan bir izleyicinin yazdığı son insan
             girdisi zamanı; girdi_esik_sn içinde mi).
  oyun       etkin pencere yasak listesinde ya da sınıfı oyun biçiminde (steam_app_N, gamescope, wine, .exe).
  kullanici_yok  ekran kilitli (logind LockedHint / ScreenSaver.GetActive / kilit ekranı penceresi) ya da oturum
             boşta (IdleHint, insan girdisi yokken). Bu durumda mesgul=False; kilitliyse karar yine "arka"
             (kilit ekranına ön planda girdi gönderilmez).

karar(ozet) → "on" | "arka" | "sonra". Ayar: ayarlar.toml [karar] (deskhand/ayarlar.py).
  Meşgul + mesgulken="sor" → bildirim (org.freedesktop.Notifications, jeepney): **Arka planda yap / Ekranımda
  yap / Sonra**; süre dolarsa `cevapsiz`. Plasma 6 tam ekran pencere odaktayken (varsayılan: Rahatsız Etme
  "WhenFullscreen") normal bildirimleri göstermez; kritik olanları tam ekranın ÜSTÜNDE gösterir. Film/oyun
  ortasında kullanıcıyı bölmemek için varsayılan tam_ekranda_sor=false: sormadan `cevapsiz`. true ise kritik
  bildirimle sorulur. Kullanıcının elle açtığı Rahatsız Etme de aynı kurala bağlıdır.
Son karar RUNTIME_DIR/karar-son.json'a yazılır (arayüz tepsi rozeti için).
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import threading
import time

from . import ayarlar, yollar
from .hata import calisma_dizini
from .i18n import N_, _

ANLIK_SN = 0.3  # girdi: insan etkinliği bu kadar izlenir (diğer sorgularla eşzamanlı)
MPRIS = "org.mpris.MediaPlayer2."
MPRIS_YOL = "/org/mpris/MediaPlayer2"
MPRIS_OYNATICI = "org.mpris.MediaPlayer2.Player"
BILDIRIM_AD = "org.freedesktop.Notifications"
BILDIRIM_YOL = "/org/freedesktop/Notifications"
OYUN_SINIF = re.compile(r"^steam_app_\d+$|^gamescope|\.exe$|^wine|^steam_proton|^proton", re.I)
KILIT_SINIF = re.compile(r"kscreenlocker", re.I)
KARAR_KOD = {"on": 0, "arka": 20, "sonra": 21}
EYLEMLER = (("arka", N_("Arka planda yap")), ("on", N_("Ekranımda yap")), ("sonra", N_("Sonra")))  # düğme: _()
BILDIRIM_BASLIK = N_("Deskhand bir iş yapmak istiyor")
UYGULAMA_AD = "Deskhand"
DBUS_SURE = 0.5  # tek D-Bus sorgusu için üst sınır (sn)

# Etkin pencere: tek KWin betiğinde (salt okuma) tam ekran bayrağı, sınıf, başlık, geometri, çıkış geometrisi.
KWIN_BETIK = (
    "let w = workspace.activeWindow; output_result(JSON.stringify(w ? {"
    "fs: w.fullScreen, sinif: w.resourceClass, ad: w.resourceName, baslik: w.caption, "
    "g: [w.frameGeometry.x, w.frameGeometry.y, w.frameGeometry.width, w.frameGeometry.height], "
    "cikis: w.output ? w.output.name : '', "
    "cg: w.output ? [w.output.geometry.x, w.output.geometry.y, w.output.geometry.width, w.output.geometry.height] "
    ": null, kimlik: String(w.internalId)} : null))")


# ---------------------------------------------------------------- yardımcılar (testler değiştirir)

def _calis(argv, sure=1.5) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=sure).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _etkinlik_yap():
    from .insan import Etkinlik
    return Etkinlik()


def _dbus_ac():
    """Oturum veri yolu (DBUS_SESSION_BUS_ADDRESS). Açılamazsa None."""
    try:
        from jeepney.io.blocking import open_dbus_connection
        return open_dbus_connection(bus="SESSION", auth_timeout=DBUS_SURE)
    except Exception:  # noqa: BLE001 — veri yolu yoksa sinyal 'bilinmiyor'
        return None


def plasma_rc_yolu() -> str:
    kok = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(kok, "plasmanotifyrc")


def _cagir(conn, ad, yol, arayuz, uye, imza=None, govde=(), otobaslatma=False):
    """D-Bus yöntem çağrısı → gövde (tuple) ya da None (hata/zaman aşımı)."""
    from jeepney import DBusAddress, MessageFlag, MessageType, new_method_call
    m = new_method_call(DBusAddress(yol, bus_name=ad, interface=arayuz), uye, imza, govde)
    if not otobaslatma:
        m.header.flags |= MessageFlag.no_auto_start
    try:
        r = conn.send_and_get_reply(m, timeout=DBUS_SURE)
    except Exception:  # noqa: BLE001
        return None
    if r.header.message_type == MessageType.error:
        return None
    return r.body


def _ozellik(conn, ad, yol, arayuz, ozellik):
    g = _cagir(conn, ad, yol, "org.freedesktop.DBus.Properties", "Get", "ss", (arayuz, ozellik))
    return g[0][1] if g else None  # variant → (imza, değer)


# ---------------------------------------------------------------- pencere / tam ekran

def kwin_coz(metin):
    """kwinscript çıktısı → dict | None (etkin pencere yok) | False (okunamadı)."""
    for satir in reversed((metin or "").splitlines()):
        satir = satir.strip()
        if satir == "null":
            return None
        if satir.startswith("{"):
            try:
                p = json.loads(satir)
            except ValueError:
                return False
            return p if isinstance(p, dict) else False
    return False


def _kd(*a):
    """kdotool çağrısı arka uç üzerinden (ham araç çağrısı yalnız arka_uc/ içinde, CONTRACT §4)."""
    from .arka_uc import kde
    return kde.kd(*a)


def _yedek_pencere():
    """kwinscript çalışmazsa: kde arka ucunun okuma sorguları (tam ekran bayrağı yok → geometri karşılaştırması)."""
    from .arka_uc import kde
    from .hata import Dur
    k = kde.aktif()
    if not k:
        return None
    try:
        geo = list(kde.geometri(k))
    except Dur:
        geo = None
    return {"fs": False, "sinif": kde.sinif(k), "ad": "", "baslik": kde.baslik(k), "g": geo, "cikis": "",
            "cg": None, "kimlik": k}


def _cikislar():
    """Yedek yol için ekran alanı (kde arka ucu; çok ekranda tüm ekranların birleşimi)."""
    from .arka_uc import kde
    from .hata import Dur
    try:
        x0, y0, x1, y1 = kde.ekran_alani()
    except Dur:
        return []
    return [(x0, y0, x1 - x0, y1 - y0)]


def etkin_pencere():
    """→ dict (fs, sinif, ad, baslik, g, cikis, cg, kimlik) | None. Yalnız okuma."""
    p = kwin_coz(_kd("kwinscript", "--inline", KWIN_BETIK))
    return _yedek_pencere() if p is False else p


def kapliyor_mu(g, c, pay=1):
    """Pencere dikdörtgeni g, çıkış dikdörtgeni c'yi tümüyle kaplıyor mu?"""
    if not g or not c:
        return False
    return (g[0] <= c[0] + pay and g[1] <= c[1] + pay and g[0] + g[2] >= c[0] + c[2] - pay
            and g[1] + g[3] >= c[1] + c[3] - pay)


# Plasma kabuğu: hiçbir pencere seçili değilken etkin "pencere" masaüstü yüzeyidir (tüm çıkışı kaplar) → geometriye
# bakıp tam ekran saymak, kullanıcı masaüstündeyken ön planı tümden kilitliyordu. Gerçek tam ekran (fs) yine sayılır.
KABUK_SINIFLARI = {"plasmashell", "org.kde.plasmashell", "krunner", "org.kde.krunner", "ksmserver",
                   "org.kde.ksmserver", "ksplashqml", "kwin_wayland", "kwin"}


def tam_ekran_mi(p, cikislar=None):
    """KWin fullScreen bayrağı YA DA pencere bir çıkışı tümüyle kaplıyor. cikislar: None → gerekirse okunur."""
    if not p:
        return False
    if p.get("fs"):
        return True
    if (p.get("sinif") or "").lower() in KABUK_SINIFLARI:
        return False  # masaüstü yüzeyi/panel/başlatıcı tüm ekranı kaplar ama oyun/film değildir
    if p.get("cg"):
        return kapliyor_mu(p.get("g"), p["cg"])
    if cikislar is None:
        cikislar = _cikislar()
    return any(kapliyor_mu(p.get("g"), c) for c in cikislar)


# ---------------------------------------------------------------- oyun / yasak pencere

def yasak_desenleri():
    """Yasak listesi (SALT OKUMA: dosya yoksa oluşturulmaz, varsayılan liste kullanılır)."""
    try:
        with open(yollar.yasak_dosya()) as f:
            metin = f.read()
    except OSError:
        from .guvenlik import VARSAYILAN_YASAK
        metin = _(VARSAYILAN_YASAK)
    return [l.strip() for l in metin.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def oyun_mu(p, desenler=None):
    """→ neden (str) | None. Yasak liste eşleşmesi ya da oyun biçimli pencere sınıfı."""
    if not p:
        return None
    sinif, ad, baslik = p.get("sinif") or "", p.get("ad") or "", p.get("baslik") or ""
    for d in (yasak_desenleri() if desenler is None else desenler):
        try:
            if re.search(d, baslik, re.I) or re.search(d, sinif, re.I):
                return _("yasak listesi /{desen}/").format(desen=d)
        except re.error:
            continue
    if OYUN_SINIF.search(sinif) or OYUN_SINIF.search(ad):
        return _("oyun sınıfı ({sinif})").format(sinif=sinif or ad)
    return None


# ---------------------------------------------------------------- medya (MPRIS)

def oynatici_adi(bus_adi):
    ad = bus_adi[len(MPRIS):] if bus_adi.startswith(MPRIS) else bus_adi
    return re.sub(r"\.instance.*$", "", ad)


def medya(conn):
    """→ [{oynatici, durum, baslik}] tüm MPRIS oynatıcıları (conn None → [])."""
    if conn is None:
        return []
    from jeepney import message_bus
    try:
        adlar = conn.send_and_get_reply(message_bus.ListNames(), timeout=DBUS_SURE).body[0]
    except Exception:  # noqa: BLE001
        return []
    sonuc = []
    for ad in sorted(a for a in adlar if a.startswith(MPRIS)):
        durum_ = _ozellik(conn, ad, MPRIS_YOL, MPRIS_OYNATICI, "PlaybackStatus")
        baslik = ""
        if durum_ == "Playing":
            meta = _ozellik(conn, ad, MPRIS_YOL, MPRIS_OYNATICI, "Metadata")
            if isinstance(meta, dict) and "xesam:title" in meta:
                baslik = str(meta["xesam:title"][1])
        sonuc.append({"oynatici": oynatici_adi(ad), "durum": durum_ or "bilinmiyor", "baslik": baslik})
    return sonuc


# ---------------------------------------------------------------- oturum (kilit / boşta)

def loginctl_coz(metin):
    d = dict(l.split("=", 1) for l in (metin or "").splitlines() if "=" in l)
    return {"kilitli": d.get("LockedHint") == "yes", "bosta": d.get("IdleHint") == "yes",
            "okundu": bool(d)}


def oturum(conn, p=None):
    o = loginctl_coz(_calis(["loginctl", "show-session", "auto", "-p", "LockedHint", "-p", "IdleHint"]))
    if conn is not None:
        g = _cagir(conn, "org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", "GetActive")
        if g and g[0]:
            o["kilitli"] = True
    if p and KILIT_SINIF.search(p.get("sinif") or ""):
        o["kilitli"] = True
    return o


# ---------------------------------------------------------------- bildirim sunucusu durumu

def plasma_rc():
    """plasmanotifyrc (SALT OKUMA) → {grup: {anahtar: değer}}."""
    gruplar, grup = {}, None
    try:
        with open(plasma_rc_yolu(), encoding="utf-8", errors="replace") as f:
            for satir in f:
                satir = satir.strip()
                if satir.startswith("[") and satir.endswith("]"):
                    grup = satir[1:-1]
                    gruplar.setdefault(grup, {})
                elif grup is not None and "=" in satir and not satir.startswith("#"):
                    a, d = satir.split("=", 1)
                    gruplar[grup][re.sub(r"\[\$\w+\]$", "", a.strip())] = d.strip()
    except OSError:
        pass
    return gruplar


def _rc_bool(gruplar, grup, anahtar, varsayilan):
    d = gruplar.get(grup, {}).get(anahtar)
    return varsayilan if d is None else d.lower() in ("true", "1", "yes")


def bildirim_durumu(conn):
    """Plasma: 'Inhibited' (Rahatsız Etme şu an etkin mi — tam ekran kaynaklı dahil), WhenFullscreen (tam
    ekranda otomatik Rahatsız Etme, vars. açık), CriticalInDndMode (Rahatsız Etme'de kritik bildirimler, vars. açık)."""
    rc = plasma_rc()
    bastir = None
    if conn is not None:
        bastir = _ozellik(conn, BILDIRIM_AD, BILDIRIM_YOL, BILDIRIM_AD, "Inhibited")
    return {"bastiriliyor": bool(bastir), "okundu": bastir is not None,
            "dnd_tam_ekran": _rc_bool(rc, "DoNotDisturb", "WhenFullscreen", True),
            "kritik_dnd": _rc_bool(rc, "Notifications", "CriticalInDndMode", True)}


# ---------------------------------------------------------------- girdi

def etkinlik_kaydi_yolu():
    return os.path.join(calisma_dizini(), "son-etkinlik.json")


def etkinlik_kaydi():
    """Sürekli izleyicinin kaydı {pid, basla, son_insan} (zamanlar time.time()); izleyici yaşamıyorsa None."""
    try:
        with open(etkinlik_kaydi_yolu()) as f:
            k = json.load(f)
        os.kill(int(k["pid"]), 0)
        return k
    except (OSError, ValueError, KeyError, TypeError):
        return None


class AnlikGirdi:
    """ANLIK_SN boyunca insan girdisi izler; diğer sorgularla eşzamanlı (başlat → ... → sonuc)."""

    def __init__(self):
        try:
            self.etk = _etkinlik_yap()
        except Exception as e:  # noqa: BLE001
            self.etk, self.hata = None, str(e)
        else:
            self.hata = None
        self.bas = time.monotonic()

    def sonuc(self, sure=ANLIK_SN):
        if self.etk is None:
            return None
        try:
            if not self.etk.calisiyor():
                return None
            bas = self.etk.hazir_an or self.bas
            kalan = bas + sure - time.monotonic()
            if kalan > 0:
                time.sleep(kalan)
            return bool(self.etk.insan(bas))
        finally:
            self.etk.kapat()


def girdi_birlestir(anlik, kayit, esik, simdi=None):
    """anlik: True/False/None (izlenemedi); kayit: etkinlik_kaydi() → {var, kaynak, son_sn}."""
    simdi = time.time() if simdi is None else simdi
    son_sn = None
    kayit_var = False
    if kayit and kayit.get("son_insan") is not None:
        son_sn = round(simdi - float(kayit["son_insan"]), 1)
        kayit_var = son_sn <= esik
    kaynak = "+".join(k for k, v in (("anlik", anlik is not None), ("kayit", kayit is not None)) if v) or "yok"
    return {"var": bool(anlik) or kayit_var, "anlik": anlik, "son_sn": son_sn, "esik_sn": esik, "kaynak": kaynak}


# ---------------------------------------------------------------- durum

def durum(esik=None):
    """Tüm sinyaller (salt okuma), hedef < 0,5 sn. → {mesgul, nedenler, ayrinti}."""
    t0 = time.monotonic()
    if esik is None:
        esik = ayarlar.al("karar", "girdi_esik_sn")
    anlik = AnlikGirdi()  # izleme diğer sorgularla eşzamanlı sürer
    p = etkin_pencere()
    tam = tam_ekran_mi(p)
    oyun = oyun_mu(p)
    conn = _dbus_ac()
    try:
        oynaticilar = medya(conn)
        otr = oturum(conn, p)
        bld = bildirim_durumu(conn)
    finally:
        if conn is not None:
            conn.close()
    gir = girdi_birlestir(anlik.sonuc(), etkinlik_kaydi(), esik)
    calan = [o for o in oynaticilar if o["durum"] == "Playing"]

    nedenler = [n for n, v in (("tam_ekran", tam), ("medya", calan), ("girdi", gir["var"]), ("oyun", oyun)) if v]
    kullanici_yok = otr["kilitli"] or (otr["bosta"] and not gir["var"])
    pencere = None if not p else {"sinif": p.get("sinif") or "", "baslik": p.get("baslik") or "",
                                  "geometri": p.get("g"), "cikis": p.get("cikis") or "", "tam_ekran_bayragi": bool(p.get("fs"))}
    ayrinti = {"pencere": pencere, "tam_ekran": tam, "medya": oynaticilar, "girdi": gir, "oyun": oyun,
               "oturum": otr, "bildirim": bld, "sure_ms": round((time.monotonic() - t0) * 1000)}
    if kullanici_yok:
        return {"mesgul": False, "nedenler": ["kullanici_yok"], "ayrinti": ayrinti}
    return {"mesgul": bool(nedenler), "nedenler": nedenler, "ayrinti": ayrinti}


# ---------------------------------------------------------------- bildirimle sorma

def karar_bekliyor_yolu(pid=None):
    """Her soru KENDİ dosyası: RUNTIME_DIR/karar-bekliyor-<pid>-<iş parçacığı> (iki süreç aynı anda sorarsa biri
    diğerinin korumasını silmesin/ezmesin)."""
    pid = os.getpid() if pid is None else pid
    return os.path.join(calisma_dizini(), f"karar-bekliyor-{pid}-{threading.get_ident()}")


def surec_baslangici(pid):
    """/proc/PID/stat başlangıç zamanı (saat tıkı) | None (süreç yok). PID yeniden kullanımına karşı kimlik."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _karar_bekliyor_yaz():
    """Bildirim açıkken: kendi karar-bekliyor-* dosyamız = "PID BAŞLANGIÇ". Herhangi biri geçerliyken kullanıcının
    ekranına (kde) girdi gönderilmez: ajan bildirimdeki "Ekranımda yap" düğmesine kendisi basamasın. → yol | None."""
    try:
        yol = karar_bekliyor_yolu()
        os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
        gecici = f"{yol}.yaz"
        with open(gecici, "w") as f:
            f.write(f"{os.getpid()} {surec_baslangici(os.getpid())}\n")
        os.replace(gecici, yol)
        return yol
    except OSError:
        return None


def _karar_bekliyor_sil(yol):
    """Yalnız kendi dosyamızı sil."""
    if yol:
        try:
            os.remove(yol)
        except OSError:
            pass


def karar_bekliyor():
    """Kullanıcıya şu an bildirimle "nerede yapılsın?" soruluyor mu (herhangi bir süreçte)? Yazan süreç ölmüşse
    (ya da PID başka bir sürece geçmişse) o dosya yok sayılır ve temizlenir. ~50 µs."""
    d = calisma_dizini()
    try:
        adlar = [a for a in os.listdir(d) if a.startswith("karar-bekliyor-") and not a.endswith(".yaz")]
    except OSError:
        return False
    for ad in adlar:
        yol = os.path.join(d, ad)
        try:
            with open(yol) as f:
                parca = f.read().split()
            pid, bas = int(parca[0]), parca[1]
        except (OSError, ValueError, IndexError):
            continue
        gercek = surec_baslangici(pid)
        if gercek is not None and str(gercek) == bas:
            return True
        try:
            os.remove(yol)  # ölü sürecin artığı
        except OSError:
            pass
    return False


def sor(ozet, sure=45, kritik=False):
    """Bildirim: Arka planda yap / Ekranımda yap / Sonra. → (cevap | None, açıklama).
    Kullanıcı bildirimi kapatırsa "sonra"; süre dolarsa bildirim geri çekilir, None.
    Bildirim açıkken RUNTIME_DIR/karar-bekliyor durur (kullanıcının ekranına girdi yok, kde.on_plan_korumasi)."""
    from jeepney import MatchRule, message_bus
    from jeepney.low_level import HeaderFields
    conn = _dbus_ac()
    if conn is None:
        return None, _("oturum veri yolu açılamadı")
    bekliyor = _karar_bekliyor_yaz()
    try:
        sahip = _cagir(conn, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                       "GetNameOwner", "s", (BILDIRIM_AD,))
        if not sahip:
            return None, _("bildirim hizmeti yok")
        sahip = sahip[0]
        kural = MatchRule(type="signal", sender=sahip, interface=BILDIRIM_AD, path=BILDIRIM_YOL)
        conn.send_and_get_reply(message_bus.AddMatch(kural), timeout=DBUS_SURE)
        with conn.filter(kural, bufsize=64) as kuyruk:  # sinyaller Notify yanıtından önce de gelebilir
            eylemler = [x for anahtar, etiket in EYLEMLER for x in (anahtar, _(etiket))]
            ipuclari = {"urgency": ("y", 2 if kritik else 1), "suppress-sound": ("b", True)}
            govde = html.escape((ozet or "").strip()[:400], quote=False)
            r = _cagir(conn, BILDIRIM_AD, BILDIRIM_YOL, BILDIRIM_AD, "Notify", "susssasa{sv}i",
                       (UYGULAMA_AD, 0, "", _(BILDIRIM_BASLIK), govde, eylemler, ipuclari, int(sure * 1000)),
                       otobaslatma=True)
            if not r:
                return None, _("bildirim gönderilemedi")
            nid = r[0]
            bitis = time.monotonic() + sure
            while True:
                kalan = bitis - time.monotonic()
                if kalan <= 0:
                    _cagir(conn, BILDIRIM_AD, BILDIRIM_YOL, BILDIRIM_AD, "CloseNotification", "u", (nid,))
                    return None, _("{sn} sn içinde yanıt yok").format(sn=f"{sure:g}")
                try:
                    m = conn.recv_until_filtered(kuyruk, timeout=kalan)
                except TimeoutError:
                    continue
                if m.header.fields.get(HeaderFields.sender) != sahip or not m.body or m.body[0] != nid:
                    continue
                uye = m.header.fields.get(HeaderFields.member)
                if uye == "ActionInvoked" and m.body[1] in KARAR_KOD:
                    return m.body[1], _("kullanıcı seçti")
                if uye == "NotificationClosed":
                    if m.body[1] == 2:
                        return "sonra", _("kullanıcı bildirimi kapattı")
                    return None, _("bildirim kapandı (süre doldu)") if m.body[1] == 1 else _("bildirim kapandı")
    except Exception as e:  # noqa: BLE001 — bildirim yolu çökerse karar 'cevapsiz'a düşer
        return None, _("bildirim hatası: {hata}").format(hata=e)
    finally:
        _karar_bekliyor_sil(bekliyor)
        conn.close()


# ---------------------------------------------------------------- karar

def karar_ayrintili(ozet, d=None, ayar=None, sor_f=None):
    """→ {karar, neden, soruldu, durum}. d: durum() (verilmezse ölçülür), ayar: ayarlar.oku()."""
    ayar = (ayar or ayarlar.oku())["karar"]
    d = d if d is not None else durum(ayar["girdi_esik_sn"])
    sor_f = sor_f or sor
    a = d["ayrinti"]
    soruldu = False
    cevapsiz = ayar["cevapsiz"]

    if a["oturum"]["kilitli"]:
        k, neden = "arka", _("ekran kilitli: kilit ekranına ön planda girdi gönderilmez")
    elif not d["mesgul"]:
        k, neden = "on", (_("kullanıcı yok (oturum boşta)") if "kullanici_yok" in d["nedenler"]
                          else _("kullanıcı meşgul değil"))
    elif ayar["mesgulken"] == "arka":
        k, neden = "arka", _("meşgul ({nedenler}); ayar mesgulken=arka").format(nedenler=", ".join(d["nedenler"]))
    elif ayar["mesgulken"] == "bekle":
        k, neden = "sonra", _("meşgul ({nedenler}); ayar mesgulken=bekle").format(nedenler=", ".join(d["nedenler"]))
    else:
        b = a["bildirim"]
        sessiz = a["tam_ekran"] or b["bastiriliyor"]  # tam ekran (film/oyun) ya da Rahatsız Etme
        gorunmez = (b["bastiriliyor"] or (a["tam_ekran"] and b["dnd_tam_ekran"])) and not b["kritik_dnd"]
        if sessiz and not ayar["tam_ekranda_sor"]:
            k, neden = cevapsiz, _("{durum}: kullanıcı bölünmedi, sorulmadı (tam_ekranda_sor=false)").format(
                durum=_("tam ekran") if a["tam_ekran"] else _("Rahatsız Etme açık"))
        elif gorunmez:
            k, neden = cevapsiz, _("Rahatsız Etme'de kritik bildirimler kapalı: bildirim görünmezdi, sorulmadı")
        else:
            soruldu = True
            cevap, aciklama = sor_f(ozet, ayar["sor_sure"], kritik=sessiz)
            k, neden = (cevap, aciklama) if cevap else (cevapsiz, f"{aciklama} → cevapsiz={cevapsiz}")
    sonuc = {"karar": k, "neden": neden, "soruldu": soruldu, "durum": d}
    _son_karar_yaz(ozet, sonuc)
    return sonuc


def karar(gorev_ozeti):
    """→ "on" | "arka" | "sonra"."""
    return karar_ayrintili(gorev_ozeti)["karar"]


def son_karar_yolu():
    return os.path.join(calisma_dizini(), "karar-son.json")


def _son_karar_yaz(ozet, sonuc):
    """Arayüz (tepsi rozeti) için son karar. Hata sessiz."""
    try:
        yol = son_karar_yolu()
        os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
        kayit = {"zaman": time.time(), "ozet": (ozet or "")[:400], "karar": sonuc["karar"], "neden": sonuc["neden"],
                 "soruldu": sonuc["soruldu"], "nedenler": sonuc["durum"]["nedenler"]}
        gecici = yol + f".{os.getpid()}"
        with open(gecici, "w") as f:
            json.dump(kayit, f, ensure_ascii=False)
        os.replace(gecici, yol)
    except OSError:
        pass


# ---------------------------------------------------------------- ekran koruması (kullanıcı kuralı)

EKRANIMDA_IZIN_SN = 600  # kullanıcı bildirimde "Ekranımda yap" dediyse bu süre boyunca ön plan serbest


def _kullanici_ekranimda_dedi(simdi=None):
    try:
        with open(son_karar_yolu()) as f:
            k = json.load(f)
    except (OSError, ValueError):
        return False
    simdi = time.time() if simdi is None else simdi
    return k.get("karar") == "on" and bool(k.get("soruldu")) and 0 <= simdi - float(k.get("zaman", 0)) < EKRANIMDA_IZIN_SN


def ekran_korumasi(p=None, oynaticilar=None):
    """KULLANICI KURALI: kullanıcı oyun oynarken ya da film/video izlerken ekranına HİÇBİR müdahale yok (girdi,
    pencere öne getirme, uygulama açma). → neden (str) | None. Hızlı (~10 ms; girdi izleme YOK):
      - etkin pencere tam ekran (oyun/film çoğunlukla)
      - etkin pencere oyun biçimli (steam_app_N, gamescope, wine/.exe)
      - etkin pencerenin uygulaması MPRIS'te ÇALIYOR (pencerede video/film; arka planda müzik engel DEĞİL)
    İstisna: kullanıcı açıkça izin verdi (DESKHAND_EKRANIMDA=1 ya da son 10 dk'da bildirimde "Ekranımda yap")."""
    if os.environ.get("DESKHAND_EKRANIMDA") == "1" or _kullanici_ekranimda_dedi():
        return None
    p = etkin_pencere() if p is None else p
    if not p:
        return None
    sinif = (p.get("sinif") or "").lower()
    if tam_ekran_mi(p):
        return _("tam ekranda ({sinif}: oyun/film)").format(sinif=sinif or _("pencere"))
    oyun = oyun_mu(p, [])
    if oyun:
        return _("oyunda ({oyun})").format(oyun=oyun)
    if oynaticilar is None:
        conn = _dbus_ac()
        try:
            oynaticilar = medya(conn)
        finally:
            if conn is not None:
                conn.close()
    adlar = {sinif, (p.get("ad") or "").lower()} - {""}
    for o in oynaticilar or []:
        oy = (o.get("oynatici") or "").lower()
        if o.get("durum") == "Playing" and oy and any(oy in a or a in oy for a in adlar):
            return _("video/film izliyor ({oynatici})").format(oynatici=oy)
    return None


# ---------------------------------------------------------------- CLI

def _evet(v):
    return _("evet") if v else _("hayır")


def ozet_metni(d):
    a = d["ayrinti"]
    sat = [_("meşgul: {evet}").format(evet=_evet(d["mesgul"])) + (f" — {', '.join(d['nedenler'])}" if d["nedenler"] else "")]
    p = a["pencere"]
    if p:
        sat.append(_("  etkin pencere: {sinif} | tam ekran: {evet}").format(sinif=p["sinif"] or "?", evet=_evet(a["tam_ekran"]))
                   + (f" ({p['cikis']})" if p["cikis"] else ""))
    else:
        sat.append(_("  etkin pencere: yok | tam ekran: {evet}").format(evet=_evet(a["tam_ekran"])))
    calan = [o for o in a["medya"] if o["durum"] == "Playing"]
    if calan:
        sat += [_("  medya: {oynatici} çalıyor").format(oynatici=o["oynatici"]) + (f" — {o['baslik']}" if o["baslik"] else "")
                for o in calan]
    else:
        sat.append(_("  medya: çalan yok ({sayi} oynatıcı)").format(sayi=len(a["medya"])))
    g = a["girdi"]
    sat.append(_("  girdi: {evet} (kaynak {kaynak}{son})").format(
        evet=_evet(g["var"]), kaynak=g["kaynak"],
        son=_(", son insan girdisi {sn} sn önce").format(sn=g["son_sn"]) if g["son_sn"] is not None else ""))
    sat.append(_("  oyun/yasak: {oyun}").format(oyun=a["oyun"] or _("hayır")))
    o = a["oturum"]
    sat.append(_("  oturum: kilitli {kilitli}, boşta {bosta}").format(kilitli=_evet(o["kilitli"]), bosta=_evet(o["bosta"])))
    b = a["bildirim"]
    sat.append(_("  bildirimler: Rahatsız Etme şu an {simdi} (tam ekranda otomatik: {tam_ekran}, kritikler gösterilir: "
                 "{kritik})").format(simdi=_evet(b["bastiriliyor"]), tam_ekran=_evet(b["dnd_tam_ekran"]),
                                     kritik=_evet(b["kritik_dnd"])))
    sat.append(_("  süre: {ms} ms").format(ms=a["sure_ms"]))
    return "\n".join(sat)


def k_mesgul(a):
    d = durum()
    print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else ozet_metni(d))


def k_karar(a):
    s = karar_ayrintili(a.ozet)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        print(s["karar"])
        print(_("neden: {neden}").format(neden=s["neden"]), file=sys.stderr)
    sys.exit(KARAR_KOD[s["karar"]])
