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
from .eylem import (_bekleyen_onay_kapisi, _yazi_hassas, girdi_al, girdi_birak, hassas_nokta, sistem_istemi_on,
                    sistem_istemi_onay, tikla_ic)
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
    """libatspi'nin bağlanacağı ERİŞİLEBİLİRLİK veri yolu: '' = kullanıcının oturumu (kde); sanal → özel adres.
    Kayıt GÜVENLİ kayıt (masaustu.durum: adres oturum dizininden kurulur) ve bağlanmadan önce soket denetlenir
    (sembolik bağ / sert bağ / karşı taraf: masaustu.a11y_denetle) → Dur(14)."""
    if sec().ad != "sanal":
        return ""
    from . import masaustu
    d = masaustu.durum(saglik=False) or {}
    adres, p = d.get("a11y_adres"), (d.get("pid") or {}).get("a11y")
    yol = (re.search(r"unix:path=([^,]+)", adres or "") or [None, ""])[1]
    if adres and p and masaustu._canli(p) and os.path.exists(yol):
        masaustu.a11y_denetle(adres, d)
        return adres
    adres = masaustu.erisim_hazirla()  # eski sürümle açılmış masaüstü ya da kayıt defteri ölmüş: hazırla
    if not adres:
        raise Dur(9, _("görünmez masaüstünde erişilebilirlik hazırlanamadı (at-spi2-core kurulu mu?)"))
    masaustu.a11y_denetle(adres)
    return adres


def _atspi_veri_yolu_saglam(a11y=""):
    """Erişilebilirlik veri yolunun soketine gerçekten bağlanılabiliyor mu? libatspi bağlanamayınca süreci
    abort() ile ÖLDÜRÜYOR (kod -6) — önce biz denetleyip anlaşılır bir hata verelim. → (tamam, ayrıntı)."""
    import socket
    if a11y:  # özel (sanal) veri yolu: soket oturumun kendisi mi (sembolik bağ/sert bağ/sahte soket reddedilir)
        from . import masaustu
        try:
            masaustu.a11y_denetle(a11y)
        except Dur as e:
            return False, str(e)
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
    """Uygulama süreci a, pencere süreci b'nin KENDİSİ ya da TORUNU mu? (Çok süreçli uygulamalar — tarayıcı, Electron —
    erişilebilirlik ağacını penceresinin sahibinin alt sürecinden bildirebilir.) Atalar SAYILMAZ: pencerenin sahibini
    başlatan başka bir uygulamanın çerçevesine eylem gitmesin."""
    from . import kendi
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError):
        return False
    return a == b or any(p == b for p, _c in kendi.atalar(a)[1:])


def _exe(pid):
    try:
        return os.path.realpath(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError, TypeError):
        return None


TORUN_BENZERLIK = 0.9  # tam PID eşleşmesi yokken torun süreçteki çerçevenin başlığa en düşük benzerliği


def _cerceve_bul(Atspi, pid, baslik):
    """Pencere → AT-SPI çerçevesi: YALNIZ hedef pencerenin PID'inden seçilir; aynı süreçte birden çok çerçeve varsa
    başlık benzerliğiyle. Tam PID eşleşmesi yoksa yalnız pencere sürecinin TORUNLARINDAN, AYNI çalıştırılabilir dosyaya
    sahip ve başlığı ≥ TORUN_BENZERLIK benzeyen çerçeve. Atalar ve başka uygulamalar asla (denetimler X/KWin penceresinde
    yapılır, eylem BAŞKA uygulamada olurdu): PID bilinmiyor ya da eşleşme yoksa Dur 6. → (çerçeve, uygulama pid, ad)."""
    if not pid:
        raise Dur(6, _("pencerenin süreç kimliği (PID) bilinmiyor: erişilebilirlik çerçevesi güvenle eşlenemez ({baslik})"
                       ).format(baslik=repr(baslik)), tur="agacta_yok")
    adaylar = []
    masa = Atspi.get_desktop(0)
    pencere_exe = None
    for i in range(masa.get_child_count()):
        app = masa.get_child_at_index(i)
        if app is None:
            continue
        try:
            app_pid = app.get_process_id()
            if not _surec_akrabasi(app_pid, pid):
                continue
            tam = str(app_pid) == str(pid)
            if not tam:
                pencere_exe = pencere_exe or _exe(pid)
                if pencere_exe is None or _exe(app_pid) != pencere_exe:
                    continue  # torun ama başka program (ör. pencerenin başlattığı ayrı bir uygulama)
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
            oran = difflib.SequenceMatcher(None, katla(ad), katla(baslik)).ratio()
            if not tam and oran < TORUN_BENZERLIK and ad != baslik:
                continue
            benz = 1.0 if ad and (ad == baslik or ad in baslik or baslik in ad) else oran
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


# observe (MCP) için ögenin durum belirteçleri: AT-SPI durum adı → API belirteci (çevrilmez)
GOZLEM_DURUMLARI = (("FOCUSED", "focused"), ("CHECKED", "checked"), ("INDETERMINATE", "mixed"),
                    ("SELECTED", "selected"), ("PRESSED", "pressed"), ("EXPANDED", "expanded"),
                    ("READ_ONLY", "readonly"), ("REQUIRED", "required"), ("INVALID_ENTRY", "invalid"),
                    ("VISITED", "visited"))
DEGERLI_ROLLER = {"entry", "text", "spin button", "slider", "combo box"}  # değeri okunan roller (parola alanı ASLA)
DEGER_SINIRI = 200


def _hizli_kimlik(o):
    """Ögenin (veri yolu adı, nesne yolu) kimliği; önce libatspi nesnesinin kendi alanları (çağrısız), yoksa
    _nesne_kimligi. Okunamazsa None."""
    try:
        yol = getattr(o, "path", None)
        ad = getattr(getattr(o, "app", None), "bus_name", None)
        if ad and yol:
            return [str(ad), str(yol)]
    except Exception:  # noqa: BLE001
        pass
    k = _nesne_kimligi(o)
    return list(k) if k else None


def _ayrinti(Atspi, o, rol, ss, S):
    """observe ayrıntısı: durum belirteçleri, eylem adları (etkileşimli rollerde), değer (parola alanı ASLA)."""
    durumlar = [ad for at, ad in GOZLEM_DURUMLARI if getattr(S, at, None) is not None and ss.contains(getattr(S, at))
                and (ad != "readonly" or rol in DEGERLI_ROLLER or rol == "password text")]  # etiket hep salt okunur
    if (getattr(S, "EXPANDABLE", None) is not None and ss.contains(S.EXPANDABLE) and "expanded" not in durumlar):
        durumlar.append("collapsed")
    if "readonly" not in durumlar and rol in ("entry", "text") and getattr(S, "EDITABLE", None) is not None \
            and not ss.contains(S.EDITABLE):
        durumlar.append("readonly")
    e = {"durumlar": durumlar}
    if rol in ETKILESIMLI:
        try:
            e["eylemler"] = eylem_listesi(o)[1]
        except Exception:  # noqa: BLE001
            pass
    if rol in DEGERLI_ROLLER and rol != "password text":
        deger = None
        try:
            vi = o.get_value_iface() if rol in ("spin button", "slider") else None
            if vi is not None:
                v = vi.get_current_value()
                deger = str(int(v)) if float(v).is_integer() else f"{v:g}"
            elif rol in ("entry", "text", "spin button"):
                ti = o.get_text_iface()
                if ti is not None:
                    deger = Atspi.Text.get_text(ti, 0, DEGER_SINIRI + 1)
        except Exception:  # noqa: BLE001
            deger = None
        if deger:
            deger = _deger_temizle(deger, *_deger_ipuclari(o))
        if deger:
            e["deger"] = deger if len(deger) <= DEGER_SINIRI else deger[:DEGER_SINIRI - 1] + "…"
    return e


# Alan adı/açıklaması/niteliği (autocomplete, id, placeholder) gizli bir alanı gösteriyorsa değer ASLA döndürülmez
# (observe ve read_text(tree) ortak; yalnız `password text` rolüne güvenilmez: web/Electron parola alanları `entry` olabilir).
# Metin ocr.katla ile katlanır (Türkçe harf/büyük-küçük duyarsız); kısa kısaltmalar kelime sınırlı (spin, shipping, otp≠hotpot).
_GIZLI_ALAN = re.compile(r"parola|sifre|pass|\b(?:pin|otp|cvv\d?|cvc\d?)\b|guvenlik kodu|"
                         r"one ?time ?code|tek kullanimlik|dogrulama kodu|onay kodu|sms kodu|verification code|"
                         r"security code|auth(?:entication)? code|\botp\w*|\bpin ?code|2fa|mfa|totp")
_DEGER_NITELIKLERI = ("autocomplete", "id", "placeholder", "placeholder-text")
_DENETIM = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]")
_MASKE_KARAKTERI = frozenset("•●*·∗⁎")  # parola maskesi: yalnız bunlardan oluşan değer anlamsız (atlanır)


def _deger_ipuclari(o) -> tuple[str, ...]:
    """Ögenin ad/açıklama/nitelik (autocomplete, id, placeholder) metinleri (okunamayan boş)."""
    ipucu = []
    for al in ("get_name", "get_description"):
        try:
            ipucu.append(getattr(o, al)() or "")
        except Exception:  # noqa: BLE001
            pass
    try:
        nit = o.get_attributes() or {}
        ipucu += [str(nit[k]) for k in _DEGER_NITELIKLERI if nit.get(k)]
        if str(nit.get("text-input-type", "")).lower() == "password":
            ipucu.append("parola")
    except Exception:  # noqa: BLE001
        pass
    return tuple(ipucu)


def _deger_temizle(deger: str, *ipuclari: str) -> str | None:
    """Alan değerini döndürmeden önce: kart/parola/PIN/OTP/CVV alanıysa "***"; yalnız parola maskesi karakterlerinden
    oluşuyorsa None (değer yok); denetim/biçim karakterleri ayıklanır (satır sonu/sekme boşluğa çevrilir)."""
    if any(c in _MASKE_KARAKTERI for c in deger) and all(c in _MASKE_KARAKTERI or c.isspace() for c in deger):
        return None
    if guvenlik.kart_alani_mi(*ipuclari) or any(_GIZLI_ALAN.search(katla(i)) for i in ipuclari if i):
        return "***"
    deger = _DENETIM.sub("", deger.replace("\r", " ").replace("\n", " ").replace("\t", " "))
    return deger or None


def _tara(Atspi, cerceve, geo, en_cok, sure, cocuk_siniri, kimlik_ver=False, ayrinti=False):
    """Penceredeki GÖRÜNEN ögeler: rol, ad, pencere koordinatlı kutu, etkin mi, çerçeveden çocuk-sıra yolu. Wayland'de
    ekran koordinatı yok → çerçeveye göre (WINDOW) konum + pencere dekorasyonu payı (pencere boyutu − AT-SPI boyutu).
    kimlik_ver: her ögeye `kimlik` = [veri yolu adı, nesne yolu] (MCP ref doğrulaması); ayrinti: + durumlar, eylemler,
    değer (observe). Parola alanının (`password text`) değeri hiçbir koşulda okunmaz.
    etkin = SENSITIVE: GTK4 (zenity, Nautilus…) ENABLED durumunu HİÇ bildirmez (ölçüldü: tüm düğmeler 'devre dışı'
    görünüp tıklama reddediliyordu); Qt/GTK3 devre dışı ögede SENSITIVE'i de kaldırır."""
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
            oge = {"rol": rol, "ad": ad, "x": kutu_[0], "y": kutu_[1], "w": kutu_[2], "h": kutu_[3],
                   "cx": kutu_[0] + kutu_[2] / 2, "cy": kutu_[1] + kutu_[3] / 2,
                   "etkin": ss.contains(S.SENSITIVE), "derinlik": d, "yol": yol}
            if kimlik_ver or ayrinti:
                oge["kimlik"] = _hizli_kimlik(o)
            if ayrinti:
                oge.update(_ayrinti(Atspi, o, rol, ss, S))
            sonuc.append(oge)
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
            "cocuklar": cocuklar, "eylemler": eylem_listesi(oge)[1], "nitelikler": _oge_nitelikleri(oge),
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
    if islem == "odak_kart":
        return _odakli_kart(Atspi, cerceve)
    if islem == "tara":
        r = _tara(Atspi, cerceve, istek["geo"], istek["en_cok"], istek["sure"], istek["cocuk_siniri"],
                  bool(istek.get("kimlik_ver")), bool(istek.get("ayrinti")))
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


def _oge_nitelikleri(oge) -> str:
    """Web ögesinin autocomplete/id/placeholder/xml-roles gibi nitelik DEĞERLERİ (boşlukla birleşik; yoksa "")."""
    try:
        n = oge.get_attributes() or {}
        return " ".join(str(v) for k, v in dict(n).items() if k in ("autocomplete", "id", "placeholder", "name",
                                                                    "class", "xml-roles"))
    except Exception:  # noqa: BLE001
        return ""


def _odakli_kart(Atspi, cerceve):
    """Çerçevede odaklı yazma alanı kart bilgisi alanı mı (ad, açıklama, autocomplete/id/placeholder)? Değeri OKUNMAZ."""
    o = _uclar(Atspi, cerceve, lambda o, rol, ss, S: ss.contains(S.FOCUSED) and rol in ("password text", "text",
                                                                                          "entry"))
    try:
        return bool(o is not None and guvenlik.kart_alani_mi(o.get_name(), o.get_description(), _oge_nitelikleri(o)))
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


def odakli_kart_mi(k):
    """Pencerede odaklı öge kart bilgisi alanı mı? Erişilebilirlik kapalıysa AÇMAZ (bilinmez → False)."""
    try:
        if not erisim_acik():
            return False
        return bool(_atspi_calistir(_pencere_istegi(k, "odak_kart")))
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


def erisim_ogeleri(k, en_cok=4000, sure=8.0, cocuk_siniri=400, kimlik_ver=False, ayrinti=False):
    """Penceredeki GÖRÜNEN ögeler: rol, ad, pencere koordinatlı kutu, etkin mi (+ `yol`; kimlik_ver: `kimlik`;
    ayrinti: + durumlar/eylemler/değer). Erişilebilirlik kapalıysa kendiliğinden açılır (kullanıcıdan komut
    beklenmez). → (ögeler, süre)."""
    yeni = erisim_ac_garanti()
    ek = {}
    if kimlik_ver:
        ek["kimlik_ver"] = True
    if ayrinti:
        ek["ayrinti"] = True
    istek = _pencere_istegi(k, "tara", geo=list(sec().geometri(k)), en_cok=en_cok, sure=sure, cocuk_siniri=cocuk_siniri,
                            **ek)
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


def erisim_ara(ogeler, ad, rol=None, rol_tam=False):
    """Ada göre: tam (Türkçe harf/büyük-küçük duyarsız) > içerir > benzer (≥0,85). Yalnız en iyi kademe döner.
    rol süzgeci varsayılan olarak ALT DİZGE (`role="text"` → "password text" da); rol_tam=True: yalnız TAM eşleşme
    (değer yazma yolu: `text` parola alanını kapsamasın)."""
    q = norm(ad)
    r_ = {"password": "password text"}.get((rol or "").lower(), (rol or "").lower())  # yaygın kısa ad
    aday = [o for o in ogeler if o["ad"] and (not rol or (r_ == o["rol"] if rol_tam else rol.lower() in o["rol"]))]
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


REF_PAYI = 3  # px: observe'daki kutu ile güncel kutu arasındaki en çok fark (her kenar/boyut)
REF_YOK, REF_FARKLI = "ref-yok", "ref-farkli"  # Dur.tur: ref ögesi artık yok / başka öge (MCP: "observe çağır")


def _kutu(o):
    if o.get("kutu"):
        return [float(v) for v in o["kutu"]]
    if o.get("x") is not None:
        return [float(o["x"]), float(o["y"]), float(o["w"]), float(o["h"])]
    return None


def _oge_kimligi(o):
    if o.get("kimlik"):
        return list(o["kimlik"])
    if o.get("_bus") and o.get("_yol"):
        return [o["_bus"], o["_yol"]]
    return None


def ref_oge_sec(ogeler, ref):
    """MCP `ref` (observe ögesi) → güncel ağaçtaki AYNI öge. Kimlik (veri yolu adı + nesne yolu, BİRLİKTE; okunamamışsa
    çocuk-sıra yolu) ile bulunur, sonra adı, rolü ve kutusu (±REF_PAYI px) beklenenle karşılaştırılır. Ad ARANMAZ
    (başka "Kaydet" düğmesine düşülmez). Yoksa Dur 8 (tur REF_YOK), farklıysa Dur 8 (tur REF_FARKLI): eylem yok."""
    kimlik = ref.get("kimlik")
    if kimlik:
        aday = [o for o in ogeler if _oge_kimligi(o) == list(kimlik)]
    else:
        aday = [o for o in ogeler if o.get("yol") is not None and list(o["yol"]) == list(ref.get("yol") or [None])]
    if not aday:
        raise Dur(8, _("ref'teki öge artık yok (arayüz değişti): eylem yapılmadı; observe çağırıp yeni ref kullan"),
                  tur=REF_YOK)
    o = aday[0]
    k1 = _kutu(o)
    k2 = [float(v) for v in ref["kutu"]] if ref.get("kutu") else None
    neden = None
    if (o.get("ad") or "") != (ref.get("ad") or ""):
        neden = _("adı değişti")
    elif o.get("rol") != ref.get("rol"):
        neden = _("rolü değişti")
    elif k2 is not None and (k1 is None or any(abs(a_ - b_) > REF_PAYI for a_, b_ in zip(k1, k2))):
        neden = _("yeri/boyutu değişti")
    if neden:
        raise Dur(8, _("ref'teki öge farklı ({neden}): eylem yapılmadı; observe çağırıp yeni ref kullan").format(
            neden=neden), tur=REF_FARKLI)
    return o


YAZILABILIR_ROLLER = ("entry", "text", "password text", "spin button")  # değeri doğrudan yazılabilen roller (label DEĞİL)


def _oge_secimi(a, ogeler, sure):
    """Ada göre ögeyi seç (fare ve eylem yolu AYNI): bulunamadı 6, birden çok 5, --sira, devre dışı 6. → (öge, kademe).
    a.ref_oge varsa ad aranmaz: kimlikle seçilip doğrulanır (ref_oge_sec). a.yazilabilir_tercih (değer yazma): ad
    birden çok ögeye TAM ad eşleşmesiyle uyup yalnız biri yazılabilirse (YAZILABILIR_ROLLER) belirsizlik sorulmadan o
    seçilir (bulanık kademelerde değil); rol süzgeci de TAM eşleşmedir."""
    ref = getattr(a, "ref_oge", None)
    if ref:
        o = ref_oge_sec(ogeler, ref)
        if not o["etkin"]:
            raise Dur(6, _("'{ad}' devre dışı (tıklanamaz)").format(ad=o["ad"]))
        return o, "ref"
    tercih = bool(getattr(a, "yazilabilir_tercih", False))
    bulunan, kademe = erisim_ara(ogeler, a.ad, a.rol, rol_tam=tercih)
    if not bulunan:
        from . import web
        ipucu = ("\n" + _("Web sayfası ögeleri için: `web {kimlik} '{ad}'`").format(kimlik=a.kimlik, ad=a.ad)
                 if web.tarayici_mi(a.kimlik) else "")
        raise Dur(6, _("'{ad}' erişilebilirlik ağacında yok ({sayi} öge, {sn} sn). İpucu: `ekran agac {kimlik}`"
                       ).format(ad=a.ad, sayi=len(ogeler), sn=f"{sure:.2f}", kimlik=a.kimlik) + ipucu)
    if a.sira is None and len(bulunan) > 1 and tercih and kademe == "tam":
        # değer yazma: etiket (label) ile giriş alanı aynı ADI (TAM eşleşme) taşırsa yalnız BİRİ yazılabilirse
        # (entry/text…) o seçilir; bulanık (içerir/benzer) eşleşmede eski davranış: belirsizlik (5) sorulur
        yazilabilir = [o for o in bulunan if o["rol"] in YAZILABILIR_ROLLER]
        if len(yazilabilir) == 1:
            bulunan = yazilabilir
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
        sistem_istemi_on(g, a.kimlik, a.onayli)  # polkit/KWallet: aramadan önce onay (koordinatlı tık/eylem gibi)
        denetle(a.kimlik, a.baslik)
        w = _web_sec(a, "fare")  # tarayıcı penceresi: önce sayfa ögeleri (tarayıcının erişilebilirlik ağacı)
        if w is not None:
            return _web_tikla(g, a, w, mod)
        ref = bool(getattr(a, "ref_oge", None))
        ogeler, sure = erisim_ogeleri(a.kimlik, kimlik_ver=ref)
        o, kademe = _oge_secimi(a, ogeler, sure)
        # öge bulunduktan SONRA tek onay: istek ögenin adını, noktadaki yazıyı ve çevresinin görüntüsünü taşır
        yakin = nokta_metni(a.kimlik, o["cx"], o["cy"])
        hassas_nokta(g, a.kimlik, a.onayli, _("tıklama"), o["cx"], o["cy"], yakin, ek_metinler=(a.ad, o["ad"]))
        if guvenlik.yapistirma_ogesi_mi(a.ad, o["ad"]):  # simgeli "yapıştır" düğmesinin erişilebilir adı
            guvenlik.yapistirma_engel(a.kimlik, a.onayli)
        if getattr(g, "onay_hedefi", None):  # panelden onaylandı: öge ağaçta hâlâ aynı yerde ve aynı mı
            def yeniden():
                ogeler2, sure2 = erisim_ogeleri(a.kimlik, kimlik_ver=ref)
                return _oge_secimi(a, ogeler2, sure2)[0]
            _onay_sonrasi_oge(g, o, yeniden, yakin)
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


def _hassas_oge(k, onayli, ne, o, bilgi, ek_metinler=(), ek_basliklar=()):
    """Hassas düğme / ödeme sayfası denetimi (fare yolundaki hassas_nokta ile aynı kurallar, OCR yerine AT-SPI
    yazıları: ad, açıklama, çocuk adları). Görüntü eklenmez (pencereyi öne getirirdi). → onay alındı mı."""
    metinler = [*ek_metinler, o["ad"], bilgi.get("aciklama", ""), *bilgi.get("cocuklar", [])]
    metinler = [m for m in metinler if m]
    nokta = (o["cx"], o["cy"]) if o.get("cx") is not None else None
    onayli_oldu = False
    if hassas_sayfa_engel(k, onayli, ne, yakin=metinler, nokta=nokta, goruntu_al=False, ek_basliklar=ek_basliklar):
        onayli, onayli_oldu = True, True
    if hassas_engel(onayli, *metinler, hedef=sec().baslik(k), k=None, nokta=nokta):
        onayli_oldu = True
    return onayli_oldu


def _eylem_baglami(a, tur="fare", basla=True):
    """Her iki faresiz komutun ortak girişi: eylem kimliği sıfırla (basla=False: çağıran zaten sıfırladı ve sistem
    istemi onayını aldı), ilk denetimler, ağaçtan ögeyi seç. → (öge, kademe, süre)."""
    from .guvenlik import eylem_basladi
    if basla:
        eylem_basladi()
    if a.kimlik == EKRAN:
        raise Dur(1, _("erişilebilirlik eylemi pencere ister (masaüstü kipi değil)"))
    from .guvenlik import sistem_istemi_engel
    sistem_istemi_engel(a.kimlik, getattr(a, "onayli", False),
                        _("erişilebilirlik eylemi") if tur == "fare" else _("değer yazma"), goruntu_al=False)
    _atspi_korumalari(a.kimlik, a.baslik, tur)  # ağaca bile bakmadan: yasak/kilitli pencerede hiçbir şey
    ogeler, sure = erisim_ogeleri(a.kimlik, kimlik_ver=bool(getattr(a, "ref_oge", None)))
    o, kademe = _oge_secimi(a, ogeler, sure)
    return o, kademe, sure


# ---------------------------------------------------------------- web sayfası ögeleri (tarayıcı penceresi)

WEB_KAYDIR_EN_COK = 8  # görünmeyen ögeyi görüş alanına getirmek için en çok bu kadar kaydırma turu


def _web_sec(a, tur):
    """Hedef pencere bir tarayıcıysa ögeyi önce SAYFADAN (tarayıcının erişilebilirlik ağacı: deskhand.web) seç: önce
    görünürler, yoksa görünmeyenler de. tur "fare": tıklama yolu, ögenin konumu doğrulanmış olmalı (çerçeve sınırı
    pencere geometrisiyle eşleşmezse tık YOK: fail-closed). Sayfada yoksa / ağaçta belge yoksa None (tarayıcı arayüzü
    için genel ağaç yolu denenir). Birden çok eşleşme 5, devre dışı 6.
    → {"oge", "sayfa", "idx", "sure"} | None"""
    from . import web
    from .hata import ARAC_EKSIK
    k = a.kimlik
    ref = getattr(a, "ref_oge", None)
    if ref and ref.get("kaynak") != "web":
        return None  # ref genel ağaçtan: sayfaya bakılmaz (aynı kaynaktan doğrulanır)
    if not ref and not web.tarayici_mi(k):
        return None
    web.hazirla(k)  # yasak pencere 10 + erişilebilirlik veri yolu
    rol = getattr(a, "rol", None)
    if ref:  # kimlikle bul + ad/rol/kutu doğrula; hiçbir hata yutulmaz (genel ağaca düşülmez)
        oge, sayfa, sure, idx = _web_ref(k, ref)
        if not oge["gorunur"]:
            raise Dur(8, _("ref'teki öge artık görüş alanında değil: eylem yapılmadı; observe çağırıp yeni ref kullan"),
                      tur=REF_FARKLI)
    else:
        try:
            try:
                oge, sayfa, sure, idx = web.oge_ve_sayfa(k, a.ad, rol, a.sira, True, yol_ver=True)
            except Dur as e:
                if e.kod != 6:
                    raise
                oge, sayfa, sure, idx = web.oge_ve_sayfa(k, a.ad, rol, a.sira, False, yol_ver=True)
        except Dur as e:
            if e.kod in (6, ARAC_EKSIK):
                return None
            raise
    if tur == "fare" and not sayfa.get("konum_dogrulandi"):
        raise Dur(2, _("öge konumu doğrulanamadı (erişilebilirlik çerçeve sınırı pencere geometrisine uymuyor); "
                       "tıklanmadı. OCR ile metne tıklamayı dene (click-text)"), tur=web.KONUM_HATA_TURU)
    if "devre_disi" in oge["durum"]:
        raise Dur(6, _("'{ad}' devre dışı (tıklanamaz)").format(ad=oge["ad"]))
    return {"oge": oge, "sayfa": sayfa, "idx": idx, "sure": sure}


def _web_ref(k, ref, gorunur=False):
    """Web ref'i: sayfada kimliğiyle (_bus + _yol) bul ve doğrula → (öge, sayfa, süre, sıra)."""
    from . import web
    s = web.oku(k, roller=[ref["rol"]] if ref.get("rol") else None, gorunur=gorunur, en_cok=0, ad_siniri=0,
                ayrinti=False, yol_ver=True)
    o = ref_oge_sec(s["ogeler"], ref)
    return o, s["sayfa"], s["sure"], s["ogeler"].index(o)


def _web_yeniden(a, w, gorunur):
    """Onaydan/kaydırmadan sonra aynı web ögesini yeniden oku: ref varsa kimlikle, yoksa ad + sıra ile."""
    from . import web
    ref = getattr(a, "ref_oge", None)
    if ref:
        return _web_ref(a.kimlik, ref, gorunur)
    return web.oge_ve_sayfa(a.kimlik, a.ad, getattr(a, "rol", None), w["idx"] + 1, gorunur, yol_ver=True)


def _web_gorunur_yap(g, a, w):
    """Görüş alanı dışındaki ögeyi, bulunduğu yöne fare tekerleğiyle kaydırarak (mevcut kaydırma yolu: kaydir_ic, tüm
    girdi denetimleriyle) görüş alanına getir. Her turdan sonra sayfa yeniden okunur; ilerleme yoksa ya da en çok
    WEB_KAYDIR_EN_COK turda görünmezse anlaşılır hata."""
    from . import web
    from .eylem import kaydir_ic
    k = a.kimlik
    o, idx = w["oge"], w["idx"]
    onceki, tur = None, 0
    while not o["gorunur"] and tur < WEB_KAYDIR_EN_COK:
        if not o["merkez"]:
            raise Dur(6, _("'{ad}' sayfada var ama görünmüyor (kutusu yok: gizli ya da kapalı bir bölümde)").format(
                ad=o["ad"]))
        if o["merkez"] == onceki:
            break  # kaydırma ögeyi oynatmadı: sayfa sonu / kaydırılamayan bölüm
        onceki = o["merkez"]
        gx, gy, gw, gh = w["sayfa"].get("gorus") or (0, 0, *sec().geometri(k)[2:])
        cx, cy = o["merkez"]
        if cy >= gy + gh:
            yon, mesafe = "asagi", cy - (gy + gh) + gh / 2
        elif cy < gy:
            yon, mesafe = "yukari", gy - cy + gh / 2
        elif cx >= gx + gw:
            yon, mesafe = "sag", cx - (gx + gw) + gw / 2
        elif cx < gx:
            yon, mesafe = "sol", gx - cx + gw / 2
        else:
            raise Dur(6, _("'{ad}' görüş alanında ama görünmüyor (gizli ya da üstü örtülü)").format(ad=o["ad"]))
        adim = max(1, min(12, int(mesafe // 150)))
        kaydir_ic(g, k, a.baslik, yon, adim, (int(gx + gw / 2), int(gy + gh / 2)))
        tur += 1
        time.sleep(0.4)  # yumuşak kaydırma bitsin
        oge, sayfa, sure, idx = _web_yeniden(a, {**w, "idx": idx}, False)
        if not sayfa.get("konum_dogrulandi"):
            raise Dur(2, _("öge konumu doğrulanamadı; tıklanmadı"), tur=web.KONUM_HATA_TURU)
        o, w = oge, {**w, "oge": oge, "sayfa": sayfa, "idx": idx}
        print(_("kaydırıldı: {yon} ({adim} adım)").format(yon=yon, adim=adim))
    if not o["gorunur"]:
        raise Dur(6, _("'{ad}' sayfada var ama görüş alanına getirilemedi ({tur} kaydırma)").format(ad=o["ad"], tur=tur))
    return w


ONAY_KONUM_PAYI = 3  # onaydan sonra ögenin merkezi en çok bu kadar piksel oynayabilir


def _ayni_oge(o1, o2):
    """İki okuma aynı ögeyi mi gösteriyor (ad + rol + merkez ±ONAY_KONUM_PAYI; web'de nesne adresi de)?"""
    if o2 is None or o1.get("ad") != o2.get("ad") or o1.get("rol") != o2.get("rol"):
        return False
    if o1.get("_bus") and (o1.get("_bus"), o1.get("_yol")) != (o2.get("_bus"), o2.get("_yol")):
        return False
    m1 = o1.get("merkez") or (o1.get("cx"), o1.get("cy"))
    m2 = o2.get("merkez") or (o2.get("cx"), o2.get("cy"))
    if None in (*m1, *m2):
        return tuple(m1) == tuple(m2)
    return abs(m1[0] - m2[0]) <= ONAY_KONUM_PAYI and abs(m1[1] - m2[1]) <= ONAY_KONUM_PAYI


def _onay_sonrasi_oge(g, o, yeniden_bul, yakin):
    """Ağaç ögesine hassas tık panelden onaylandıktan sonra (B3, öge tarafı): öge ağaçtan yeniden bulunur; adı, rolü,
    konumu (web'de nesne adresi) onaylanandan farklıysa ya da artık yoksa tık YAPILMAZ → Dur 10. Onay anında noktada
    OCR yazısı yoksa (yazısız simge/aria-label düğmesi) noktanın OCR karşılaştırması yalnız "şimdi de yazı yok" olur
    (öge adı OCR'da görünmez; kimlik ağaçtan doğrulandı). Yazı varsa eylem.onay_hedefi_dogrula aynen karşılaştırır."""
    try:
        o2 = yeniden_bul()
    except Dur as e:
        if e.kod in (10, 12, 13, 15):
            raise
        o2 = None
    if not _ayni_oge(o, o2):
        g.onay_hedefi = None
        raise Dur(10, _("onay verilen hedef değişti: öge '{ad}' artık aynı yerde/aynı değil; tıklanmadı").format(
            ad=o.get("ad")), tur="hedef-degisti")
    h = g.onay_hedefi
    if not [t for t in yakin if t and t.strip()]:
        g.onay_hedefi = (h[0], h[1], [])


def _web_tikla(g, a, w, mod):
    """Web ögesine GERÇEK fare tıklaması: ögenin merkezi (pencere pikseli) mevcut tikla_ic yoluna gider; tüm
    denetimler fare yolundakiyle aynı: DUR/yasak/kilit/seviye/oyun-film/imleç altı/insan önceliği tikla_ic ve
    Girdi.gonder'de, hassas düğme + ödeme sayfası denetimi hassas_nokta'da (ögenin ADI de hedef metin: OCR yazıyı
    okuyamasa, ör. yazısız simge düğmesi, yine onay istenir; sayfa başlığı ağaçtan da denetlenir)."""
    k = a.kimlik
    if not w["oge"]["gorunur"]:
        w = _web_gorunur_yap(g, a, w)
    o, sayfa = w["oge"], w["sayfa"]
    cx, cy = o["merkez"]
    basliklar = (sayfa.get("baslik") or "",) if sayfa.get("hassas_sayfa") else ()
    yakin = nokta_metni(k, cx, cy)
    hassas_nokta(g, k, a.onayli, _("tıklama"), cx, cy, yakin, ek_metinler=(a.ad, o["ad"]), ek_basliklar=basliklar)
    if getattr(g, "onay_hedefi", None):  # panelden onaylandı: sayfadaki öge hâlâ aynı mı (yazısız düğme dahil)
        _onay_sonrasi_oge(g, o, lambda: _web_yeniden(a, w, True)[0], yakin)
    print(_("bulundu: web {rol} '{ad}' ({x},{y}) {konum}, {sn} sn").format(
        rol=o["rol"], ad=o["ad"], x=cx, y=cy, konum=sayfa.get("konum"), sn=f"{w['sure']:.2f}"))
    tikla_ic(g, k, a.baslik, cx, cy, a.dugme, sec().geometri(k), mod=mod)


def _web_eylem(a, w):
    """Web ögesinde erişilebilirlik EYLEMİ (via=action / --eylem): gerçek girdi ve odak yok; fare yolundaki
    denetimlerin imleç altı hariç hepsi (_ogeye_eylem ile aynı: hassas ad/ödeme sayfası, korumalar eylemden hemen önce)."""
    from . import web
    k, o, sayfa = a.kimlik, w["oge"], w["sayfa"]
    basliklar = (sayfa.get("baslik") or "",) if sayfa.get("hassas_sayfa") else ()
    merkez = o.get("merkez")
    oz = {"ad": o["ad"], "cx": merkez[0] if merkez else None, "cy": merkez[1] if merkez else None}
    etiket = f"ogeye-tikla '{a.ad}' --eylem" + (f" {a.eylem}" if a.eylem else "")
    from .guvenlik import sistem_istemi_engel
    sistem_istemi_engel(k, getattr(a, "onayli", False), _("erişilebilirlik eylemi"), goruntu_al=False)
    onayli = _hassas_oge(k, a.onayli, _("tıklama (erişilebilirlik eylemi)"), oz, {}, ek_metinler=(a.ad,),
                         ek_basliklar=basliklar)
    if guvenlik.yapistirma_ogesi_mi(a.ad, o.get("ad") or "", a.eylem or "") and guvenlik.yapistirma_engel(k, a.onayli):
        onayli = True  # erişilebilir adı/eylem adı yapıştırma (simgeli düğme dahil): kullanıcının panosu
    if onayli:
        etiket += " --onayli"
    _atspi_korumalari(k, a.baslik, "fare")  # onay beklenmiş olabilir
    if onayli:  # onay beklenirken sayfa değişmiş olabilir: aynı öge (ad, rol, nesne adresi, konum) değilse eylem yok
        try:
            o2 = _web_yeniden(a, w, False)[0]
        except Dur as e:
            if e.kod in (10, 12, 13, 15):
                raise
            o2 = None
        if not _ayni_oge(o, o2):
            raise Dur(10, _("onay verilen hedef değişti: öge '{ad}' artık aynı yerde/aynı değil; eylem yapılmadı"
                            ).format(ad=o["ad"]), tur="hedef-degisti")
    from . import gonderim
    gonderim.artir()  # eylem çağrısı yarıda kalsa da "belki gitti" (MCP sent)
    r = web.eylem_yap(k, o, a.eylem or None)
    _atspi_gunluk(k, etiket, f"atspi action {r['eylem']} (web)" + ("" if r["tamam"] else " (reddedildi)"))
    if not r["tamam"]:
        raise Dur(6, _("eylem çalışmadı: '{eylem}' (öge reddetti)").format(eylem=r["eylem"]))
    print(_("eylem yapıldı: web {rol} '{ad}' → {eylem} (eylemler: {liste}), {sn} sn").format(
        rol=o["rol"], ad=o["ad"], eylem=r["eylem"], liste=", ".join(r["eylemler"]), sn=f"{w['sure']:.2f}"))


def _ogeye_eylem(a):
    from .guvenlik import eylem_basladi
    eylem_basladi()
    if a.kimlik == EKRAN:
        raise Dur(1, _("erişilebilirlik eylemi pencere ister (masaüstü kipi değil)"))
    # sistem istemi (polkit, KWallet…): onay korumalardan ÖNCE sorulur (korumalar onaysız istemi sormadan reddeder)
    sistem_istemi_onay(a.kimlik, getattr(a, "onayli", False), _("erişilebilirlik eylemi"), goruntu_al=False)
    _atspi_korumalari(a.kimlik, a.baslik, "fare")  # ağaca bile bakmadan: yasak/kilitli pencerede hiçbir şey
    w = _web_sec(a, "eylem")
    if w is not None:
        return _web_eylem(a, w)
    o, kademe, sure = _eylem_baglami(a, "fare", basla=False)
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
    if guvenlik.yapistirma_ogesi_mi(a.ad, o["ad"], eylem_adi, bilgi.get("aciklama", "")) and \
            guvenlik.yapistirma_engel(k, a.onayli):
        onayli = True  # erişilebilir adı/eylem adı yapıştırma (simgeli düğme dahil): kullanıcının panosu
    if onayli:
        etiket += " --onayli"
    _atspi_korumalari(k, a.baslik, "fare")  # onay beklenmiş olabilir: pencere/başlık/DUR/ekran korumasını yeniden doğrula
    from . import gonderim
    gonderim.artir()  # eylem çağrısı yarıda kalsa da "belki gitti" (MCP sent)
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
    if guvenlik.onay_kapsami() == "kart":  # kart bilgisi: alan adı/etiketi/autocomplete ya da Luhn'lu numara
        alan_kart = guvenlik.kart_alani_mi(a.ad, bilgi.get("ad"), bilgi.get("aciklama"), bilgi.get("nitelikler"))
        if alan_kart or guvenlik.kart_numarasi(metin):
            gizli = True  # tam numara günlüğe/iletiye yazılmaz
            if guvenlik.kart_bilgisi_engel(k, onayli, metin, alan_kart, _("değer yazma")):
                etiket += " --onayli"
    if yazi_onay_ister_mi(metin):  # yazmadan ÖNCE (bir eylem = bir onay); Enter/Tab/boşluk = formu gönderme riski
        g = types.SimpleNamespace(gizli=gizli)
        if _yazi_hassas(g, k, onayli, metin, goruntu_al=False):
            etiket += " --onayli"
    for i, satir in enumerate(metin.split("\n")[:-1]):  # her satır sonu bir Enter: bir Enter = bir onay
        if ucbirim.enter_kapisi(k, onayli, ek=satir, gizli=gizli, goruntu_al=False, yalniz_ek=i > 0):
            etiket += "" if etiket.endswith(" --onayli") else " --onayli"
    _atspi_korumalari(k, a.baslik, "klavye")  # onay beklenmiş olabilir
    ucbirim.tampon_isle(sec(), k, kirli=True)  # değer doğrudan yazıldı: satırın içeriği artık bilinmez
    from . import gonderim
    gonderim.artir()  # değer yazma yarıda kalsa da "belki gitti" (MCP sent)
    r = _atspi_calistir(_oge_istegi(k, o, "yaz", metin=metin))
    gonderim.not_yaz("dogrulandi", r.get("dogrulandi"))
    goster = f"***({len(metin)})" if gizli else repr(metin if len(metin) <= 200 else metin[:197] + "…")
    _atspi_gunluk(k, etiket, f"atspi set-text {goster}")
    print(_("yazıldı: {rol} '{ad}' ← {karakter} karakter ({yontem}){dogrulandi}, {kademe} eşleşme").format(
        rol=o["rol"], ad=o["ad"], karakter=len(metin), yontem=r["yontem"],
        dogrulandi=_(", doğrulandı") if r["dogrulandi"] else "", kademe=kademe))
