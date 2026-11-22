"""Erişilebilirlik ağacı (AT-SPI): Qt/GTK düğmeleri AD ve KONUMLA; ögeye FARESİZ eylem ve değer yazma.
Komutlar: erisim, agac, ogeye-tikla (fare ya da --eylem), ogeye-yaz.

İki arka uçta da çalışır: kde → kullanıcının erişilebilirlik veri yolu; sanal → görünmez masaüstünün ÖZEL
erişilebilirlik veri yolu (masaustu.erisim_hazirla). libatspi bir süreçte TEK veri yoluna bağlanabilir (yeniden
bağlanma güvenilir değil): süreç başka veri yoluna bağlıysa iş küçük bir yardımcı süreçte (aynı kod) yürütülür.

Güvenlik: odak çalmayan eylem yolunda (ogeye-tikla --eylem, ogeye-yaz) gerçek fare/klavye girdisi yoktur; fare yolundaki
denetimlerin imleç altı hariç HEPSİ burada AÇIKÇA uygulanır (DUR 13, yasak pencere 10, başlık/sınıf kilidi 4, hassas
düğme/ödeme sayfası 10 ya da panelden onay, kde'de oyun/film koruması 15, günlük kaydı)."""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import time
import types

from .arka_uc import EKRAN, sec
from . import guvenlik, ucbirim
from .eylem import _bekleyen_onay_kapisi, _yazi_hassas, girdi_al, girdi_birak, hassas_nokta, tikla_ic
from .gunluk import gunluk
from .guvenlik import (denetle, hassas_engel, hassas_sayfa_engel, pencere_denetle, seviye_denetle,
                       yazi_onay_ister_mi)
from .hata import Dur, dur_denetle
from .i18n import _
from .ocr import katla, nokta_metni, norm


def calis(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


ETKILESIMLI = {"push button", "toggle button", "check box", "radio button", "menu item", "check menu item",
               "radio menu item", "link", "page tab", "combo box", "entry", "text", "password text", "spin button",
               "list item", "tree item", "table cell", "slider", "menu", "button", "switch", "toggle switch"}

# Birincil eylem: ögenin Action arayüzündeki ilk bulunan (büyük/küçük harf duyarsız). Odağı alan / menü açan / kaydıran
# eylemler (SetFocus, ShowMenu, Increase…) birincil sayılmaz: istenirse --eylem ADI ile seçilir.
BIRINCIL_EYLEMLER = ("click", "press", "activate", "toggle")
# Bu adlar mutlak değil: Qt "Press"/"Toggle", GTK "click"/"activate"/"toggle", Electron "click" bildirir.

# ---------------------------------------------------------------- veri yolu (kde: kullanıcınınki; sanal: özel)

A11Y_NESNE = ("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled")


def _busctl_taban():
    """busctl'in bağlanacağı OTURUM veri yolu: kde → kullanıcının oturumu; sanal → görünmez masaüstünün özel veri yolu."""
    adres = sec().oturum_veri_yolu()
    return ["busctl", f"--address={adres}"] if adres else ["busctl", "--user"]


def erisim_acik():
    return calis(*_busctl_taban(), "get-property", *A11Y_NESNE) == "b true"


def _erisim_yaz(deger: bool):
    try:
        subprocess.run([*_busctl_taban(), "set-property", *A11Y_NESNE, "b", "true" if deger else "false"],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _isaret_yaz():
    """kde'de erişilebilirliği Deskhand açtı: durum dizinine işaret + günlüğe BİR kez (kalıcı masaüstü ayarı
    toolkit-accessibility değişebilir; `deskhand doctor` gösterir, `deskhand a11y off` temizler)."""
    from . import yollar
    yol = yollar.erisim_isareti()
    if os.path.exists(yol):
        return
    try:
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    except OSError:
        return
    gunluk("erisim | Deskhand erişilebilirliği açtı (kalıcı masaüstü ayarı toolkit-accessibility değişmiş olabilir; "
           "kapatmak için: deskhand a11y off)")


def _isaret_sil():
    from . import yollar
    try:
        os.remove(yollar.erisim_isareti())
    except OSError:
        pass


def erisim_ac_garanti():
    """Erişilebilirlik kapalıysa KULLANICIDAN KOMUT BEKLEMEDEN aç (kde: veri yolunda IsEnabled=true; sanal: masaüstünün
    özel veri yolu + kayıt defteri). Açıkken hiçbir şey yapmaz. → bu çağrıda açıldı mı (uygulamaların ağaca girmesi
    için kısa bekleme gerekir)."""
    if erisim_acik():
        return False
    au = sec()
    if au.ad == "sanal":
        from . import masaustu
        masaustu.erisim_hazirla()
    else:
        _erisim_yaz(True)
        _isaret_yaz()
    gunluk("erisim | otomatik ac" + (" | arka" if au.ad == "sanal" else ""))
    for _i in range(15):  # özellik değişikliği yansıyana dek (uygulamalar PropertiesChanged ile haberdar olur)
        if erisim_acik():
            break
        time.sleep(0.1)
    time.sleep(0.3)
    return erisim_acik()


def _a11y_adresi():
    """libatspi'nin bağlanacağı ERİŞİLEBİLİRLİK veri yolu: '' = kullanıcının oturumu (kde); sanal → özel adres."""
    if sec().ad != "sanal":
        return ""
    from . import masaustu
    d = masaustu.durum_oku() or {}
    adres, p = d.get("a11y_adres"), (d.get("pid") or {}).get("a11y")
    yol = (re.search(r"unix:path=([^,]+)", adres or "") or [None, ""])[1]
    if adres and p and masaustu._canli(p) and os.path.exists(yol):
        return adres
    adres = masaustu.erisim_hazirla()  # eski sürümle açılmış masaüstü ya da kayıt defteri ölmüş: hazırla
    if not adres:
        raise Dur(9, _("görünmez masaüstünde erişilebilirlik hazırlanamadı (at-spi2-core kurulu mu?)"))
    return adres


def _atspi_veri_yolu_saglam(a11y=""):
    """Erişilebilirlik veri yolunun soketine gerçekten bağlanılabiliyor mu? libatspi bağlanamayınca süreci
    abort() ile ÖLDÜRÜYOR (kod -6) — önce biz denetleyip anlaşılır bir hata verelim. → (tamam, ayrıntı)."""
    import socket
    adres = a11y or calis("busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress")
    m = re.search(r'unix:path=([^,"]+)', adres or "")
    if not m:
        return False, adres or "org.a11y.Bus yanıt vermedi"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(m.group(1))
        return True, m.group(1)
    except OSError as e:
        return False, f"{m.group(1)}: {e}"
    finally:
        s.close()


class _BaskaVeriYolu(Exception):
    """Bu süreçte libatspi başka bir erişilebilirlik veri yoluna bağlı (iş yardımcı süreçte yapılır)."""


_BAGLI = [None]  # libatspi'nin bu süreçte bağlandığı veri yolu: None = henüz yok, '' = kullanıcının oturumu, adres = özel


def _atspi(a11y=None):
    """Atspi modülü, bu süreçte `a11y` veri yoluna bağlı (ilk çağrıda bağlanır). Süreç başka veri yoluna bağlıysa
    _BaskaVeriYolu. a11y None = geçerli arka ucun veri yolu."""
    if a11y is None:
        a11y = _a11y_adresi()
    if _BAGLI[0] is not None and _BAGLI[0] != a11y:
        raise _BaskaVeriYolu(a11y)
    tamam, ayrinti = _atspi_veri_yolu_saglam(a11y)
    if not tamam:
        raise Dur(9, _("erişilebilirlik veri yoluna bağlanılamıyor ({ayrinti}); oturumu yeniden açmak ya da "
                       "at-spi-bus-launcher'ı yeniden başlatmak gerekir").format(ayrinti=ayrinti))
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except (ImportError, ValueError) as e:
        raise Dur(9, _("AT-SPI kullanılamıyor (python-gobject + at-spi2-core): {hata}").format(hata=e))
    if _BAGLI[0] is None:
        # libatspi adresi yalnız ilk bağlanmada okur: ortam değişkenini yalnız o an koy (başlatılan uygulamalara sızmasın)
        onceki = os.environ.get("AT_SPI_BUS_ADDRESS")
        try:
            if a11y:
                os.environ["AT_SPI_BUS_ADDRESS"] = a11y
            Atspi.get_desktop(0).get_child_count()
        finally:
            if onceki is None:
                os.environ.pop("AT_SPI_BUS_ADDRESS", None)
            else:
                os.environ["AT_SPI_BUS_ADDRESS"] = onceki
        _BAGLI[0] = a11y
    return Atspi


# ---------------------------------------------------------------- uygulama türü (yalnız ipucu için)

def uygulama_turu(pid):
    """Süreç → "firefox" | "chromium" (Chromium/Electron) | "qt" | "gtk" | "diger". Yalnız /proc okunur."""
    try:
        pid = int(pid)
        exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            kom = f.read().replace(b"\0", b" ").decode(errors="replace")
        with open(f"/proc/{pid}/maps") as f:
            maps = f.read()
    except (OSError, ValueError, TypeError):
        return "diger"
    ad = f"{exe} {kom}".lower()
    if "firefox" in ad:
        return "firefox"
    if any(x in ad for x in ("electron", "chrom", "vivaldi", "app.asar", "--type=renderer", "--no-sandbox")):
        return "chromium"
    if "libQt6Core" in maps or "libQt5Core" in maps:
        return "qt"
    if "libgtk-4" in maps or "libgtk-3" in maps:
        return "gtk"
    return "diger"


def _girmeyen_ipucu(pid):
    """Çalışan uygulama ağaçta yoksa ne yapılacağı (uygulama türüne göre)."""
    tur = uygulama_turu(pid)
    if tur == "firefox":
        return _("Firefox çalışırken açılan erişilebilirliği algılamıyor: Firefox'u kapatıp yeniden başlat")
    if tur == "chromium":
        return _("Chromium/Electron --force-renderer-accessibility ile başlatılmalı (görünmez masaüstünde `ac` bunu "
                 "kendiliğinden ekler; çalışan uygulamayı bu bayrakla yeniden başlat)")
    return _("uygulama erişilebilirlik açılmadan önce başladıysa yeniden başlat")


# ---------------------------------------------------------------- pencere / ağaç (libatspi'nin bağlı olduğu yerde)

def _surec_akrabasi(a, b):
    """İki PID aynı uygulamanın süreç ağacında mı (eşit, biri diğerinin atası)? Çok süreçli uygulamalar (tarayıcı,
    Electron) erişilebilirlik ağacını penceresinin sahibinden farklı bir süreçten bildirebilir."""
    from . import kendi
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError):
        return False
    if a == b:
        return True
    return any(p == b for p, _c in kendi.atalar(a)[1:]) or any(p == a for p, _c in kendi.atalar(b)[1:])


def _cerceve_bul(Atspi, pid, baslik):
    """Pencere → AT-SPI çerçevesi: YALNIZ hedef pencerenin PID'inden (çok süreçli uygulamada aynı süreç ağacından:
    ata/torun) seçilir; aynı süreçte birden çok çerçeve varsa başlık benzerliğiyle. Başka uygulamanın çerçevesine
    başlık benzerliğiyle düşülmez (denetimler X/KWin penceresinde yapılır, eylem BAŞKA uygulamada olurdu): PID
    bilinmiyor ya da eşleşme yoksa Dur 6. → (çerçeve, uygulama pid, uygulama adı)."""
    if not pid:
        raise Dur(6, _("pencerenin süreç kimliği (PID) bilinmiyor: erişilebilirlik çerçevesi güvenle eşlenemez ({baslik})"
                       ).format(baslik=repr(baslik)), tur="agacta_yok")
    adaylar = []
    masa = Atspi.get_desktop(0)
    for i in range(masa.get_child_count()):
        app = masa.get_child_at_index(i)
        if app is None:
            continue
        try:
            app_pid = app.get_process_id()
            if not _surec_akrabasi(app_pid, pid):
                continue
            tam = str(app_pid) == str(pid)
            app_ad = app.get_name() or ""
            cerceveler = [app.get_child_at_index(j) for j in range(app.get_child_count())]
        except Exception:
            continue
        for f in cerceveler:
            if f is None:
                continue
            try:
                ad = f.get_name() or ""
            except Exception:
                continue
            benz = 1.0 if ad and (ad == baslik or ad in baslik or baslik in ad) else \
                difflib.SequenceMatcher(None, katla(ad), katla(baslik)).ratio()
            adaylar.append((tam, benz, f, app_pid, app_ad))
    if not adaylar:
        raise Dur(6, _("pencere erişilebilirlik ağacında yok ({baslik}, pid {pid}): {ipucu}").format(
            baslik=repr(baslik), pid=pid, ipucu=_girmeyen_ipucu(pid)), tur="agacta_yok")
    secim = sorted(adaylar, key=lambda x: (not x[0], -x[1]))[0]
    return secim[2], secim[3], secim[4]


def _cerceve_denetle(app_pid, app_ad, cerceve_ad, islem):
    """Seçilen çerçevenin KENDİ kimliğiyle denetim (X/KWin penceresinin denetimi yetmez): Deskhand paneli/onay
    diyaloğu sürecine ait çerçeve her zaman 10; yasak desen (uygulama adı / çerçeve adı) 10; eylem/değer yazmada
    ayrıca ajanın kendi istemcisi (10), uygulama erişim seviyesi (10). Okumada (tara/incele) yalnız panel + yasak."""
    from . import guvenlik, kendi, onay
    try:
        panel = onay.panel_pid()
    except Exception:  # noqa: BLE001
        panel = None
    if panel and str(app_pid) == str(panel):
        raise Dur(10, _("YASAK: erişilebilirlik çerçevesi Deskhand panelinin/onay diyaloğunun sürecine ait"))
    for d in guvenlik.yasak_desenler():
        if re.search(d, cerceve_ad or "", re.I) or re.search(d, app_ad or "", re.I):
            raise Dur(10, _("YASAK pencere (erişilebilirlik çerçevesi): {baslik} (uygulama {uygulama}) /{desen}/ ile "
                            "eşleşti; hiçbir girdi gönderilmez").format(baslik=repr(cerceve_ad), uygulama=repr(app_ad),
                                                                         desen=d))
    if islem not in ("eylem", "yaz"):
        return
    if kendi.kendi_mi(app_pid, "", "sanal", lambda s: False):  # yalnız PID kuralı (sınıf yedeği pencerede yapıldı)
        raise Dur(10, _("AJANIN KENDİ İSTEMCİSİ: erişilebilirlik çerçevesi ({baslik}) bu ajanı çalıştıran süreç "
                        "zincirindeki bir sürece ait; girdi gönderilmez").format(baslik=repr(cerceve_ad)))
    s = guvenlik.seviye_coz(cerceve_ad or "", app_ad or "")
    if s == 0 or (s == 1 and islem == "yaz"):
        raise Dur(10, _("UYGULAMA SEVİYESİ (erişilebilirlik çerçevesi): {baslik} ({uygulama}) bu eylemi kabul etmiyor"
                        ).format(baslik=repr(cerceve_ad), uygulama=repr(app_ad)))


def _tara(Atspi, cerceve, geo, en_cok, sure, cocuk_siniri):
    """Penceredeki GÖRÜNEN ögeler: rol, ad, pencere koordinatlı kutu, etkin mi, çerçeveden çocuk-sıra yolu. Wayland'de
    ekran koordinatı yok → çerçeveye göre (WINDOW) konum + pencere dekorasyonu payı (pencere boyutu − AT-SPI boyutu)."""
    X, Y, W, H = geo
    WIN = Atspi.CoordType.WINDOW
    fe = cerceve.get_extents(WIN)
    ox = max(0, round((W - fe.width) / 2)) if W > fe.width else 0
    oy = max(0, H - fe.height - ox) if H > fe.height else 0
    S = Atspi.StateType
    t0 = time.monotonic()
    sonuc, yigin, sayi = [], [(cerceve, 0, [])], 0
    while yigin and sayi < en_cok and time.monotonic() - t0 < sure:
        o, d, yol = yigin.pop()
        sayi += 1
        try:
            ss = o.get_state_set()
            if d > 0 and not ss.contains(S.SHOWING):
                continue  # görünmeyen dal (kapalı menü, gizli sekme)
            rol, ad = o.get_role_name(), (o.get_name() or "").strip()
            n = min(o.get_child_count(), cocuk_siniri)
        except Exception:
            continue
        try:
            e = o.get_extents(WIN)
            kutu_ = (e.x - fe.x + ox, e.y - fe.y + oy, e.width, e.height)
        except Exception:
            kutu_ = None
        if d > 0 and kutu_ and kutu_[2] > 0 and kutu_[3] > 0:
            sonuc.append({"rol": rol, "ad": ad, "x": kutu_[0], "y": kutu_[1], "w": kutu_[2], "h": kutu_[3],
                          "cx": kutu_[0] + kutu_[2] / 2, "cy": kutu_[1] + kutu_[3] / 2,
                          "etkin": ss.contains(S.ENABLED) and ss.contains(S.SENSITIVE), "derinlik": d, "yol": yol})
        for i in range(n - 1, -1, -1):
            try:
                c = o.get_child_at_index(i)
            except Exception:
                c = None
            if c is not None:
                yigin.append((c, d + 1, yol + [i]))
    return {"ogeler": [o for o in sonuc if 0 <= o["cx"] < W and 0 <= o["cy"] < H], "sure": time.monotonic() - t0}


def _yoldan_bul(Atspi, cerceve, yol, rol, ad):
    """Ağaç taramasının verdiği çocuk-sıra yolundaki öge; rol/ad hâlâ aynı mı (arayüz arada değiştiyse Dur 8)."""
    o = cerceve
    for i in yol:
        try:
            o = o.get_child_at_index(i)
        except Exception:
            o = None
        if o is None:
            break
    try:
        ayni = o is not None and o.get_role_name() == rol and (o.get_name() or "").strip() == ad
    except Exception:
        ayni = False
    if not ayni:
        raise Dur(8, _("öge artık yok ya da değişti (arayüz güncellendi): yeniden ara"))
    return o


def _modul():
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    return Atspi


def _ad_norm(ad):
    """Eylem adı karşılaştırması: büyük/küçük harf, boşluk, '_' ve '-' yok sayılır (Qt "Set Focus", GTK "set-focus")."""
    return re.sub(r"[\s_-]+", "", ad or "").lower()


def eylem_listesi(oge):
    """→ (Action arayüzü | None, [eylem adları])."""
    ai = oge.get_action_iface()
    if ai is None:
        return None, []
    return ai, [ai.get_action_name(i) or "" for i in range(ai.get_n_actions())]


def birincil_eylem(liste):
    """Eylem adları → birincil eylemin sırası (BIRINCIL_EYLEMLER'den ilk bulunan) | None."""
    norm_ = [_ad_norm(x) for x in liste]
    for ad in BIRINCIL_EYLEMLER:
        if ad in norm_:
            return norm_.index(ad)
    return None


def eylem_sirasi(liste, ad):
    """İstenen eylem adının sırası (ad_norm eşitliği) | None."""
    n = _ad_norm(ad)
    return next((i for i, x in enumerate(liste) if _ad_norm(x) == n), None)


def oge_eylem(oge, ad=None):
    """Ögenin Action arayüzündeki eylemi çalıştırır (gerçek fare/klavye girdisi YOK, odak alınmaz). ad verilmezse
    birincil eylem (click/press/activate/toggle hangisi varsa). → {"eylem": çalışan, "eylemler": tümü, "tamam": bool}.
    Güvenlik denetimleri ÇAĞIRANDA (k_ogeye_tikla): bu işlev yalnız uygular."""
    ai, liste = eylem_listesi(oge)
    if not liste:
        raise Dur(6, _("öge eylem arayüzü sunmuyor (Action yok)"))
    if ad:
        sira = eylem_sirasi(liste, ad)
        if sira is None:
            raise Dur(6, _("'{eylem}' eylemi yok; ögenin eylemleri: {liste}").format(eylem=ad, liste=", ".join(liste)))
    else:
        sira = birincil_eylem(liste)
        if sira is None:
            raise Dur(6, _("birincil eylem yok (click/press/activate/toggle); ögenin eylemleri: {liste}; "
                           "--eylem ADI ile seç").format(liste=", ".join(liste)))
    tamam = bool(ai.do_action(sira))
    return {"eylem": liste[sira], "eylemler": liste, "tamam": tamam}


def oge_deger_yaz(oge, metin):
    """Ögenin değerini yazar: EditableText (metin alanı) ya da yoksa Value (kaydırgaç, sayı kutusu; metin sayı olmalı).
    Gerçek klavye girdisi YOK. → {"yontem", "dogrulandi": okunan değer yazılana eşit mi | None}.
    Güvenlik denetimleri ÇAĞIRANDA (k_ogeye_yaz): bu işlev yalnız uygular."""
    et = oge.get_editable_text_iface()
    if et is not None:
        if not et.set_text_contents(metin):
            raise Dur(6, _("metin yazılamadı (alan salt okunur ya da devre dışı)"))
        try:
            parola = oge.get_role_name() == "password text"
        except Exception:  # noqa: BLE001
            parola = False
        if parola:  # parola alanının değeri ASLA okunmaz (doğrulama için bile)
            return {"yontem": "EditableText", "dogrulandi": None}
        ti = oge.get_text_iface()
        okunan = _modul().Text.get_text(ti, 0, -1) if ti is not None else None
        return {"yontem": "EditableText", "dogrulandi": None if okunan is None else okunan == metin}
    vi = oge.get_value_iface()
    if vi is not None:
        try:
            deger = float(metin.strip().replace(",", "."))
        except ValueError:
            raise Dur(1, _("bu öge sayısal değer ister ({n} karakterlik metin sayı değil)").format(n=len(metin)))
        en_az, en_cok = vi.get_minimum_value(), vi.get_maximum_value()
        if not en_az <= deger <= en_cok:
            raise Dur(1, _("değer aralık dışı ({en_az}..{en_cok})").format(en_az=en_az, en_cok=en_cok))
        if not vi.set_current_value(deger):
            raise Dur(6, _("değer yazılamadı (öge salt okunur ya da devre dışı)"))
        return {"yontem": "Value", "dogrulandi": abs(vi.get_current_value() - deger) < 1e-6}
    raise Dur(6, _("öge yazılabilir değil (EditableText ya da Value arayüzü yok)"))


def oge_incele(oge):
    """Güvenlik denetimi için ögenin okunabilir bilgisi: ad, rol, açıklama, çocukların adları, eylemler."""
    cocuklar = []
    try:
        for i in range(min(oge.get_child_count(), 6)):
            c = oge.get_child_at_index(i)
            ad = (c.get_name() or "").strip() if c is not None else ""
            if ad:
                cocuklar.append(ad)
    except Exception:
        pass
    try:
        aciklama = (oge.get_description() or "").strip()
    except Exception:
        aciklama = ""
    return {"ad": (oge.get_name() or "").strip(), "rol": oge.get_role_name(), "aciklama": aciklama,
            "cocuklar": cocuklar, "eylemler": eylem_listesi(oge)[1],
            "yazilabilir": oge.get_editable_text_iface() is not None or oge.get_value_iface() is not None}


# ---------------------------------------------------------------- yürütme: bu süreçte ya da yardımcı süreçte

def _atspi_is(istek):
    """libatspi'nin bu süreçte bağlı olduğu yerde iş yürüt. istek: {a11y, pid, baslik, islem, ...}; JSON uyumlu."""
    Atspi = _atspi(istek["a11y"])
    cerceve, app_pid, app_ad = _cerceve_bul(Atspi, istek["pid"], istek["baslik"])
    islem = istek["islem"]
    try:
        cerceve_ad = cerceve.get_name() or ""
    except Exception:  # noqa: BLE001
        cerceve_ad = ""
    _cerceve_denetle(app_pid, app_ad, cerceve_ad, islem)
    beklenen = istek.get("cerceve_kimlik")
    if beklenen and _nesne_kimligi(cerceve) not in (None, tuple(beklenen)):
        raise Dur(8, _("erişilebilirlik çerçevesi tarandıktan sonra değişti (başka nesne): yeniden ara"))
    if islem == "satir":
        return _imlec_satirlari(Atspi, cerceve)
    if islem == "odak_parola":
        return _odakli_parola(Atspi, cerceve)
    if islem == "tara":
        r = _tara(Atspi, cerceve, istek["geo"], istek["en_cok"], istek["sure"], istek["cocuk_siniri"])
        r["cerceve_kimlik"] = _nesne_kimligi(cerceve)
        return r
    oge = _yoldan_bul(Atspi, cerceve, istek["yol"], istek["rol"], istek["ad"])
    if islem == "incele":
        return oge_incele(oge)
    if islem == "eylem":
        return oge_eylem(oge, istek.get("eylem") or None)
    if islem == "yaz":
        return oge_deger_yaz(oge, istek["metin"])
    raise Dur(1, f"bilinmeyen erişilebilirlik işlemi: {islem}")


def _nesne_kimligi(o):
    """AT-SPI nesnesinin kimliği: (veri yolu adı, nesne yolu) — ikisi BİRLİKTE (aynı nesne yolu başka uygulamada da
    olabilir). Okunamazsa None."""
    try:
        app = o.get_application() if hasattr(o, "get_application") else None
        ad = getattr(getattr(o, "app", None), "bus_name", None) or (getattr(app, "bus_name", None) if app else None)
        yol = getattr(o, "path", None)
        return (str(ad), str(yol)) if ad and yol else None
    except Exception:  # noqa: BLE001
        return None


def _uclar(Atspi, cerceve, kosul, en_cok=4000, sure=0.4):
    """Çerçevede GÖRÜNEN ögeler arasında kosul(o, rol, durumlar) sağlayan ilk öge (zaman/öge sınırlı DFS) | None."""
    S = Atspi.StateType
    t0 = time.monotonic()
    yigin, sayi = [cerceve], 0
    while yigin and sayi < en_cok and time.monotonic() - t0 < sure:
        o = yigin.pop()
        sayi += 1
        try:
            ss = o.get_state_set()
            rol = o.get_role_name()
            if kosul(o, rol, ss, S):
                return o
            if o is not cerceve and not ss.contains(S.SHOWING):
                continue
            n = min(o.get_child_count(), 400)
        except Exception:  # noqa: BLE001
            continue
        for i in range(n - 1, -1, -1):
            try:
                c = o.get_child_at_index(i)
            except Exception:  # noqa: BLE001
                c = None
            if c is not None:
                yigin.append(c)
    return None


def _imlec_satirlari(Atspi, cerceve):
    """Uçbirim ögesinin (rol 'terminal') imleç satırı + önceki iki satır → [satır] | None. Yalnız uçbirim rolü
    okunur (başka metin alanlarının değeri okunmaz)."""
    o = _uclar(Atspi, cerceve, lambda o, rol, ss, S: rol == "terminal" and ss.contains(S.FOCUSED)) or \
        _uclar(Atspi, cerceve, lambda o, rol, ss, S: rol == "terminal")
    if o is None:
        return None
    ti = o.get_text_iface()
    if ti is None:
        return None
    T = Atspi.Text
    imlec = T.get_caret_offset(ti)
    if imlec is None or imlec < 0:
        return None
    once = T.get_text(ti, max(0, imlec - 2000), imlec) or ""
    sonra = (T.get_text(ti, imlec, imlec + 400) or "").split("\n", 1)[0]
    satirlar = (once + sonra).split("\n")
    return [x for x in satirlar[-3:]]


def _odakli_parola(Atspi, cerceve):
    """Çerçevede odaklı öge parola alanı mı (rol 'password text')? Değeri OKUNMAZ."""
    o = _uclar(Atspi, cerceve, lambda o, rol, ss, S: ss.contains(S.FOCUSED) and rol in ("password text", "text",
                                                                                          "entry", "terminal"))
    try:
        return bool(o is not None and o.get_role_name() == "password text")
    except Exception:  # noqa: BLE001
        return False


def imlec_satirlari(k):
    """Uçbirim penceresinin giriş satırı (Enter kapısı; ucbirim.py). Erişilebilirliği AÇMAZ. → [satır] | None."""
    try:
        r = _atspi_calistir(_pencere_istegi(k, "satir"))
    except Dur:
        return None
    return r or None


def odakli_parola_mi(k):
    """Pencerede odaklı öge parola alanı mı? Erişilebilirlik kapalıysa AÇMAZ (bilinmez → False)."""
    try:
        if not erisim_acik():
            return False
        return bool(_atspi_calistir(_pencere_istegi(k, "odak_parola")))
    except Dur:
        return False
    except Exception:  # noqa: BLE001
        return False


def _yardimci_ana():
    """Yardımcı süreç girişi (`-I -c`): stdin'den JSON istek, stdout'a tek satır JSON yanıt."""
    istek = json.load(sys.stdin)
    try:
        yanit = {"sonuc": _atspi_is(istek)}
    except Dur as e:
        yanit = {"dur": [e.kod, e.mesaj, e.tur]}
    except _BaskaVeriYolu:
        yanit = {"dur": [9, "yardımcı süreç beklenmedik veri yolu", None]}
    except Exception as e:  # noqa: BLE001
        yanit = {"dur": [9, f"{type(e).__name__}: {e}", None]}
    sys.stdout.write("\n" + json.dumps(yanit) + "\n")


def _yardimci_calistir(istek):
    kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    kod = "import sys; sys.path.insert(0, sys.argv[1]); from deskhand import erisim; erisim._yardimci_ana()"
    try:
        r = subprocess.run([sys.executable, "-I", "-c", kod, kok], input=json.dumps(istek), capture_output=True,
                           text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise Dur(7, _("erişilebilirlik yardımcı süreci zaman aşımına uğradı"))
    yanit = None
    for satir in reversed(r.stdout.strip().splitlines()):
        try:
            yanit = json.loads(satir)
            break
        except ValueError:
            continue
    if yanit is None:
        raise Dur(9, _("erişilebilirlik yardımcı süreci yanıt vermedi (çıkış {kod}): {hata}").format(
            kod=r.returncode, hata=r.stderr.strip()[-200:]))
    if "dur" in yanit:
        kod_, mesaj, tur = yanit["dur"]
        raise Dur(kod_, mesaj, tur=tur)
    return yanit["sonuc"]


def _atspi_calistir(istek):
    """İşi bu süreçte yürüt; libatspi başka veri yoluna bağlıysa (MCP: iki masaüstü) yardımcı süreçte."""
    try:
        return _atspi_is(istek)
    except _BaskaVeriYolu:
        return _yardimci_calistir(istek)


def _pencere_istegi(k, islem, **ek):
    """kdotool/X penceresi → AT-SPI isteği (pencere eşleme verisi: pid, başlık)."""
    if k == EKRAN:
        raise Dur(1, _("erişilebilirlik ağacı pencere ister (masaüstü kipi değil)"))
    au = sec()
    pid = au.pid(k) if hasattr(au, "pid") else ""
    try:
        pid = int(pid) if pid not in (None, "") else ""
    except (TypeError, ValueError):
        pid = ""
    return {"a11y": _a11y_adresi(), "pid": str(pid or ""), "baslik": au.baslik(k), "islem": islem, **ek}


def erisim_ogeleri(k, en_cok=4000, sure=8.0, cocuk_siniri=400):
    """Penceredeki GÖRÜNEN ögeler: rol, ad, pencere koordinatlı kutu, etkin mi (+ `yol`). Erişilebilirlik kapalıysa
    kendiliğinden açılır (kullanıcıdan komut beklenmez). → (ögeler, süre)."""
    yeni = erisim_ac_garanti()
    istek = _pencere_istegi(k, "tara", geo=list(sec().geometri(k)), en_cok=en_cok, sure=sure, cocuk_siniri=cocuk_siniri)
    bitis = time.monotonic() + (4.0 if yeni else 0.0)  # az önce açıldı: çalışan uygulamalar ağaca kısa sürede girer
    while True:
        try:
            r = _atspi_calistir(istek)
            if r.get("cerceve_kimlik"):
                for o in r["ogeler"]:
                    o["cerceve"] = r["cerceve_kimlik"]
            return r["ogeler"], r["sure"]
        except Dur as e:
            if getattr(e, "tur", None) != "agacta_yok" or time.monotonic() >= bitis:
                raise
            time.sleep(0.4)


def _oge_istegi(k, o, islem, **ek):
    return _pencere_istegi(k, islem, yol=o["yol"], rol=o["rol"], ad=o["ad"], cerceve_kimlik=o.get("cerceve"), **ek)


def erisim_ara(ogeler, ad, rol=None):
    """Ada göre: tam (Türkçe harf/büyük-küçük duyarsız) > içerir > benzer (≥0,85). Yalnız en iyi kademe döner."""
    q = norm(ad)
    aday = [o for o in ogeler if o["ad"] and (not rol or rol.lower() in o["rol"])]
    tam = [o for o in aday if norm(o["ad"]) == q]
    if tam:
        return tam, "tam"
    icerir = [o for o in aday if len(q) > 3 and q in norm(o["ad"])]
    if icerir:
        return icerir, "içerir"
    benzer = [o for o in aday if len(q) > 4 and difflib.SequenceMatcher(None, norm(o["ad"]), q).ratio() >= 0.85]
    return benzer, "benzer"


def oge_yaz(o, no=None):
    on = f"#{no} " if no else ""
    durum = "" if o["etkin"] else " [devre dışı]"
    print(f"  {on}({o['cx']:.0f},{o['cy']:.0f}) {o['rol']}: {o['ad'] or '(adsız)'}{durum}  {o['w']}x{o['h']}")


# ---------------------------------------------------------------- komutlar

def k_erisim(a):
    """Erişilebilirlik veri yolunu aç/kapat. Açıkken Qt/GTK uygulamaları düğmelerini AD ve KONUMLA bildirir → ekran
    agac / ogeye-tikla. `agac`/`ogeye-tikla`/`ogeye-yaz` kapalıyken bunu KENDİLİĞİNDEN açar. Qt/GTK çalışırken de
    ağaca girer; Firefox ve Chromium/Electron girmez (yeniden başlat; Chromium --force-renderer-accessibility ister).
    Not: kde'de at-spi-bus-launcher ayarı kullanıcı ayarlarına (dconf toolkit-accessibility) yazar: oturumla sınırlı
    kalmayabilir; görünmez masaüstünde yalnız o masaüstü için açılır."""
    if a.islem in ("ac", "kapat"):
        if sec().ad == "sanal" and a.islem == "ac":
            from . import masaustu
            masaustu.erisim_hazirla()
        else:
            once_acikti = erisim_acik()
            _erisim_yaz(a.islem == "ac")
            if sec().ad != "sanal":
                if a.islem == "ac" and not once_acikti:
                    _isaret_yaz()
                elif a.islem == "kapat":
                    _isaret_sil()
        gunluk(f"erisim | {a.islem}")
        time.sleep(0.3)
    acik = erisim_acik()
    print(_("erişilebilirlik: AÇIK") if acik else _("erişilebilirlik: KAPALI"))
    if acik:
        Atspi = _atspi()
        masa = Atspi.get_desktop(0)
        for i in range(masa.get_child_count()):
            app = masa.get_child_at_index(i)
            if app is not None:
                try:
                    print(_("  {ad} (pid {pid}, {sayi} pencere)").format(
                        ad=app.get_name() or "?", pid=app.get_process_id(), sayi=app.get_child_count()))
                except Exception:
                    pass
        if a.islem == "ac":
            print(_("not: Firefox ve Chromium/Electron çalışırken ağaca girmez; yeniden başlat"))


def k_agac(a):
    ogeler, sure = erisim_ogeleri(a.kimlik)
    if a.desen:
        bulunan, kademe = erisim_ara(ogeler, a.desen, a.rol)
        print(_("# '{desen}': {sayi} öge ({kademe} eşleşme, {sn} sn)").format(
            desen=a.desen, sayi=len(bulunan), kademe=kademe, sn=f"{sure:.2f}"))
        for i, o in enumerate(bulunan, 1):
            oge_yaz(o, i)
        if not bulunan:
            raise Dur(6, _("bulunamadı"))
        return
    secili = [o for o in ogeler if (a.hepsi or (o["rol"] in ETKILESIMLI or (o["ad"] and o["rol"] == "label")))
              and (not a.rol or a.rol.lower() in o["rol"])]
    print(_("# {sayi} öge ({gorunen} görünen, {sn} sn); (merkez x,y) rol: ad").format(
        sayi=len(secili), gorunen=len(ogeler), sn=f"{sure:.2f}"))
    for o in secili:
        oge_yaz(o)


def _oge_secimi(a, ogeler, sure):
    """Ada göre ögeyi seç (fare ve eylem yolu AYNI): bulunamadı 6, birden çok 5, --sira, devre dışı 6. → (öge, kademe)."""
    bulunan, kademe = erisim_ara(ogeler, a.ad, a.rol)
    if not bulunan:
        raise Dur(6, _("'{ad}' erişilebilirlik ağacında yok ({sayi} öge, {sn} sn). İpucu: `ekran agac {kimlik}`"
                       ).format(ad=a.ad, sayi=len(ogeler), sn=f"{sure:.2f}", kimlik=a.kimlik))
    if a.sira is None and len(bulunan) > 1:
        print(_("# '{ad}' için {sayi} öge:").format(ad=a.ad, sayi=len(bulunan)))
        for i, o in enumerate(bulunan, 1):
            oge_yaz(o, i)
        raise Dur(5, _("birden çok öge; --sira N ile seç"))
    sira = a.sira or 1
    if not 1 <= sira <= len(bulunan):
        raise Dur(1, _("--sira 1..{en_cok} olmalı").format(en_cok=len(bulunan)))
    o = bulunan[sira - 1]
    if not o["etkin"]:
        raise Dur(6, _("'{ad}' devre dışı (tıklanamaz)").format(ad=o["ad"]))
    return o, kademe


def k_ogeye_tikla(a):
    """Erişilebilirlik ağacındaki ögeye ADIYLA tıkla: OCR'ın okuyamadığı düğmeler (renkli/orta ton zemin) dahil.
    Varsayılan: gerçek fare tıklaması (tüm denetimler: pencere, başlık, yasak, hassas düğme, insan önceliği).
    --eylem [AD]: fare/klavye YOK, odak alınmaz; ögenin Action arayüzündeki eylem çalıştırılır (denetimler aynen,
    imleç altı hariç)."""
    from .eylem import mod_coz
    mod = mod_coz(getattr(a, "mod", None))
    if getattr(a, "eylem", None) is not None:
        if a.dugme not in ("sol", None):
            raise Dur(1, _("--eylem ile fare düğmesi (sağ/çift/orta) birlikte kullanılamaz"))
        if mod:
            raise Dur(1, _("--eylem ile değiştirici tuş (--mod) birlikte kullanılamaz"))
        return _ogeye_eylem(a)
    g = girdi_al(f"ogeye-tikla '{a.ad}' {a.dugme}")
    try:
        sec().one_getir(a.kimlik)
        denetle(a.kimlik, a.baslik)
        ogeler, sure = erisim_ogeleri(a.kimlik)
        o, kademe = _oge_secimi(a, ogeler, sure)
        # öge bulunduktan SONRA tek onay: istek ögenin adını, noktadaki yazıyı ve çevresinin görüntüsünü taşır
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), o["cx"], o["cy"],
                     nokta_metni(a.kimlik, o["cx"], o["cy"]), ek_metinler=(a.ad, o["ad"]))
        print(_("bulundu: {rol} '{ad}' ({x},{y}) {kademe} eşleşme, {sn} sn").format(
            rol=o["rol"], ad=o["ad"], x=f"{o['cx']:.0f}", y=f"{o['cy']:.0f}", kademe=kademe, sn=f"{sure:.2f}"))
        tikla_ic(g, a.kimlik, a.baslik, o["cx"], o["cy"], a.dugme, sec().geometri(a.kimlik), mod=mod)
    finally:
        girdi_birak(g)


# ---------------------------------------------------------------- faresiz yol: güvenlik + günlük

INSAN_BEKLE_AZAMI = 8.0  # kullanıcı bilgisayarı kullanıyorsa en çok bu kadar bekle, sonra 12 (fare yolundaki gibi)


def _insan_onceligi():
    """İNSAN ÖNCELİĞİ (12), fare/klavye yolundaki kuralla aynı: kde'de kullanıcı klavye/fare kullanıyorsa durgunluğu
    bekle (en çok INSAN_BEKLE_AZAMI sn), sonra vazgeç; sanalda yalnız 'Devral' açıkken (guvenlik.insan_onceligi)."""
    from .guvenlik import insan_onceligi
    insan_onceligi(_("erişilebilirlik eylemi"), azami=INSAN_BEKLE_AZAMI)


def _atspi_korumalari(k, desen, tur="fare"):
    """Fare/klavye yolundaki Girdi.gonder'in denetimleri, odak şartı olmadan: DUR 13 → bekleyen onay 7 → yasak
    pencere 10 / başlık 4 / sınıf 4 → uygulama erişim seviyesi (tur: "fare" = eylem/tık, "klavye" = değer yazma; goruntule'de ikisi de 10,
    tikla'da yalnız klavye 10) → (kde) oyun/film ya da karar bildirimi 15/12 → insan önceliği 12. Eylemden HEMEN önce
    ve her bekleyen adımdan (onay) sonra çağrılır."""
    dur_denetle()
    _bekleyen_onay_kapisi()  # başka bir Deskhand sürecinin insan onayı sürerken bu masaüstüne eylem yok (7)
    pencere_denetle(k, desen)
    seviye_denetle(k, tur)
    sec().ekran_korumasi(_("erişilebilirlik eylemi"))
    _insan_onceligi()


def _atspi_gunluk(k, etiket, ne):
    """Girdi günlüğü satırı (Girdi.gonder ile aynı biçim; sanalda `arka :N` öneki)."""
    au = sec()
    yer = f"arka {au.ekran_adi()} [{au.baslik(k)}]" if au.ad == "sanal" else f"[{au.baslik(k)}]"
    gunluk(f"{etiket} | {yer} | {ne}")


def _hassas_oge(k, onayli, ne, o, bilgi, ek_metinler=()):
    """Hassas düğme / ödeme sayfası denetimi (fare yolundaki hassas_nokta ile aynı kurallar, OCR yerine AT-SPI
    yazıları: ad, açıklama, çocuk adları). Görüntü eklenmez (pencereyi öne getirirdi). → onay alındı mı."""
    metinler = [*ek_metinler, o["ad"], bilgi.get("aciklama", ""), *bilgi.get("cocuklar", [])]
    metinler = [m for m in metinler if m]
    nokta = (o["cx"], o["cy"])
    onayli_oldu = False
    if hassas_sayfa_engel(k, onayli, ne, yakin=metinler, nokta=nokta, goruntu_al=False):
        onayli, onayli_oldu = True, True
    if hassas_engel(onayli, *metinler, hedef=sec().baslik(k), k=None, nokta=nokta):
        onayli_oldu = True
    return onayli_oldu


def _eylem_baglami(a, tur="fare"):
    """Her iki faresiz komutun ortak girişi: eylem kimliği sıfırla, ilk denetimler, ağaçtan ögeyi seç.
    → (öge, kademe, süre)."""
    from .guvenlik import eylem_basladi
    eylem_basladi()
    if a.kimlik == EKRAN:
        raise Dur(1, _("erişilebilirlik eylemi pencere ister (masaüstü kipi değil)"))
    from .guvenlik import sistem_istemi_engel
    sistem_istemi_engel(a.kimlik, getattr(a, "onayli", False),
                        _("erişilebilirlik eylemi") if tur == "fare" else _("değer yazma"), goruntu_al=False)
    _atspi_korumalari(a.kimlik, a.baslik, tur)  # ağaca bile bakmadan: yasak/kilitli pencerede hiçbir şey
    ogeler, sure = erisim_ogeleri(a.kimlik)
    o, kademe = _oge_secimi(a, ogeler, sure)
    return o, kademe, sure


def _ogeye_eylem(a):
    o, kademe, sure = _eylem_baglami(a, "fare")
    k = a.kimlik
    bilgi = _atspi_calistir(_oge_istegi(k, o, "incele"))
    if not bilgi["eylemler"]:
        raise Dur(6, _("öge eylem arayüzü sunmuyor (Action yok): fare ile tıkla (--eylem olmadan)"))
    sira = None
    if a.eylem:
        sira = eylem_sirasi(bilgi["eylemler"], a.eylem)
        if sira is None:
            raise Dur(6, _("'{eylem}' eylemi yok; ögenin eylemleri: {liste}").format(
                eylem=a.eylem, liste=", ".join(bilgi["eylemler"])))
    else:
        sira = birincil_eylem(bilgi["eylemler"])
        if sira is None:
            raise Dur(6, _("birincil eylem yok (click/press/activate/toggle); ögenin eylemleri: {liste}; "
                           "--eylem ADI ile seç").format(liste=", ".join(bilgi["eylemler"])))
    eylem_adi = bilgi["eylemler"][sira]
    etiket = f"ogeye-tikla '{a.ad}' --eylem {eylem_adi}"
    onayli = _hassas_oge(k, a.onayli, _("tıklama (erişilebilirlik eylemi)"), o, bilgi, ek_metinler=(a.ad,))
    if onayli:
        etiket += " --onayli"
    _atspi_korumalari(k, a.baslik, "fare")  # onay beklenmiş olabilir: pencere/başlık/DUR/ekran korumasını yeniden doğrula
    r = _atspi_calistir(_oge_istegi(k, o, "eylem", eylem=eylem_adi))
    _atspi_gunluk(k, etiket, f"atspi action {r['eylem']}" + ("" if r["tamam"] else " (reddedildi)"))
    if not r["tamam"]:
        raise Dur(6, _("eylem çalışmadı: '{eylem}' (öge reddetti)").format(eylem=r["eylem"]))
    print(_("eylem yapıldı: {rol} '{ad}' → {eylem} (eylemler: {liste}), {kademe} eşleşme, {sn} sn").format(
        rol=o["rol"], ad=o["ad"], eylem=r["eylem"], liste=", ".join(r["eylemler"]), kademe=kademe, sn=f"{sure:.2f}"))


def k_ogeye_yaz(a):
    """Ögenin değerini AT-SPI ile yaz (EditableText; yoksa Value): fare/klavye YOK, odak alınmaz. Denetimler: DUR,
    yasak pencere, başlık/sınıf kilidi, kde'de oyun/film koruması; ödeme sayfasında Enter/Tab/boşluklu yazı onay
    ister (yaz ile aynı kural)."""
    metin = a.metin.replace("\r\n", "\n").replace("\r", "\n")
    o, kademe, sure = _eylem_baglami(a, "klavye")
    k = a.kimlik
    bilgi = _atspi_calistir(_oge_istegi(k, o, "incele"))
    if not bilgi["yazilabilir"]:
        raise Dur(6, _("öge yazılabilir değil (EditableText ya da Value arayüzü yok): '{ad}'").format(ad=o["ad"]))
    parola = bilgi["rol"] == "password text"
    gizli = bool(getattr(a, "gizli", False)) or parola  # parola alanına giden metin kendiliğinden gizli
    etiket = f"ogeye-yaz '{a.ad}' {len(metin)} karakter"
    onayli = a.onayli
    if parola and guvenlik.parola_alani_engel(k, onayli, len(metin), _("değer yazma")):
        etiket += " --onayli"
    if yazi_onay_ister_mi(metin):  # yazmadan ÖNCE (bir eylem = bir onay); Enter/Tab/boşluk = formu gönderme riski
        g = types.SimpleNamespace(gizli=gizli)
        if _yazi_hassas(g, k, onayli, metin, goruntu_al=False):
            etiket += " --onayli"
    if "\n" in metin and ucbirim.enter_kapisi(k, onayli, ek=metin.split("\n", 1)[0], gizli=gizli, goruntu_al=False):
        etiket += " --onayli"
    _atspi_korumalari(k, a.baslik, "klavye")  # onay beklenmiş olabilir
    ucbirim.tampon_isle(sec(), k, kirli=True)  # değer doğrudan yazıldı: satırın içeriği artık bilinmez
    r = _atspi_calistir(_oge_istegi(k, o, "yaz", metin=metin))
    goster = f"***({len(metin)})" if gizli else repr(metin if len(metin) <= 200 else metin[:197] + "…")
    _atspi_gunluk(k, etiket, f"atspi set-text {goster}")
    print(_("yazıldı: {rol} '{ad}' ← {karakter} karakter ({yontem}){dogrulandi}, {kademe} eşleşme").format(
        rol=o["rol"], ad=o["ad"], karakter=len(metin), yontem=r["yontem"],
        dogrulandi=_(", doğrulandı") if r["dogrulandi"] else "", kademe=kademe))
