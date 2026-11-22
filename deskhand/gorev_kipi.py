"""GÖREV KİPİ: panelin "Görev" sekmesinden başlatılan `claude -p` ajanının MCP sunucusu (DESKHAND_GOREV=1) bu kipte.

Görev ajanı GÜVENİLMEZ web içeriği okur (istem enjeksiyonu). Kip yerel dosya ve kayıtlı parola/oturum sızıntısını
sınırlar (tek doğruluk kaynağı bu modül; ARCHITECTURE "Görev kipi"):
  - open_app YALNIZ tarayıcı (Firefox; Chromium ailesi ilkesi bağlanabiliyorsa) ve belge argümanı yalnız http(s);
  - arka plan uygulamasına XDG veri klasörleri BAĞLANMAZ; ev dizini yalnız görünüm beyaz listesi + görev indirme
    klasörü (RUNTIME_DIR/gorev-indirilenler, kullanıcının İndirilenler yolunda görünür; görev bitince bildirilir);
  - tarayıcıya kurumsal ilke (Firefox distribution/policies.json, Chromium policies/managed) ad alanında bağlanır:
    file://, about:config/profiles/logins/debugging… ENGELLİ, parola yöneticisi KAPALI;
  - Firefox oturum kopyasına kayıtlı parolalar (logins.json, logins.db, key4.db) KOPYALANMAZ; çerez/depo yalnız
    görevde izin verilen sitelerin (DESKHAND_GOREV_SITELER; boşsa ÇEREZSİZ);
  - onay kapsamı `kart` olsa bile parola alanı + sistem istemi onayları AÇIK;
  - observe/read_text/screenshot: tarayıcı belgesi file:/about:/chrome:… ise RET (savunma derinliği);
  - GÖREV MASAÜSTÜ: görev yalnız KENDİ açtığı görünmez masaüstünü kullanır (durum kaydında "gorev": true); görev
    sürerken (RUNTIME_DIR/gorev-masaustu işareti, sahibi canlı panel) kipsiz istemciler (başka Claude oturumu, CLI)
    o masaüstüne bağlanamaz/uygulama açamaz (masaustu_kapisi). Panel önizlemesi (GOZLEMCI) serbest;
  - PENCERE SINIRI: görev kipinde her girdi/okuma hedefi yalnız tarayıcı penceresi (sınıf + süreç ikilisi beyaz
    listesi); başka pencere (Firefox'un açtığı Kate/Konsole…) belirirse RET + pencere kapatılır (pencere_denetle);
    tüm ekran hedefi yalnız ekranda tarayıcı dışı pencere yokken ve en az bir tarayıcı penceresi varken.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import signal
import threading

from . import yollar
from .hata import Dur
from .i18n import N_, _

ORTAM = "DESKHAND_GOREV"
SITE_ORTAM = "DESKHAND_GOREV_SITELER"

# kipte "hepsi" gibi davranan onay sınıfları (guvenlik.onaysiz_serbest `ne` değerleri)
ONAYI_ACIK = ("parola alanına yazma", "sistem istemi girdisi")

# Tarayıcı belgesi bu şemalardan biriyse okuma/görüntü REDDEDİLİR (yerel dosya, tarayıcının iç sayfaları)
YASAK_SEMALAR = ("file:", "about:", "chrome:", "resource:", "view-source:", "jar:", "moz-extension:",
                 "chrome-extension:", "devtools:", "edge:", "brave:", "vivaldi:", "opera:")
SERBEST_ADRESLER = ("about:blank", "about:newtab", "about:home", "about:privatebrowsing")

FIREFOX_ILKE = {
    "BlockAboutConfig": True,
    "BlockAboutProfiles": True,
    "BlockAboutAddons": True,
    "BlockAboutSupport": True,
    "PasswordManagerEnabled": False,   # about:logins da engellenir
    "OfferToSaveLogins": False,
    "DisableDeveloperTools": True,     # about:debugging, devtools
    "DisableFirefoxAccounts": True,
    "DisableProfileImport": True,
    "DisableProfileRefresh": True,
    "DisableSafeMode": True,
    "DisableTelemetry": True,
    "ExtensionSettings": {"*": {"installation_mode": "blocked"}},
    # WebsiteFilter kalıpları MatchPattern sözdizimi (Firefox 160 WebsiteFilter.sys.mjs: geçersiz kalıp atılır,
    # about:policies'te hata). file:///* geçerli; jar:/about: şemaları MatchPattern'de YOK (kalıp olarak eklenemez):
    # jar:file: ve about:preferences adres denetimiyle (adres_yasak) okuma/girdi tarafında reddedilir.
    "WebsiteFilter": {"Block": ["file:///*"]},
    "PromptForDownloadLocation": False,
    "Preferences": {"signon.rememberSignons": {"Value": False, "Status": "locked"},
                    "signon.autofillForms": {"Value": False, "Status": "locked"},
                    "browser.download.useDownloadDir": {"Value": True, "Status": "locked"},
                    # indirilen dosya dış uygulamayla AÇILMAZ (Kate → Konsole → kabuk zinciri; ORTA-2)
                    "browser.download.forbid_open_with": {"Value": True, "Status": "locked"},
                    "browser.download.always_ask_before_handling_new_types": {"Value": False, "Status": "locked"},
                    "browser.download.open_pdf_attachments_inline": {"Value": False, "Status": "locked"},
                    "browser.download.alwaysOpenPanel": {"Value": False, "Status": "locked"}},
}
CHROMIUM_ILKE = {
    "URLBlocklist": ["file://*", "chrome://*", "view-source:*", "devtools://*", "chrome-extension://*"],
    "PasswordManagerEnabled": False,
    "DeveloperToolsAvailability": 2,
    "BrowserSignin": 0,
    "SyncDisabled": True,
    "PromptForDownloadLocation": False,
    "AllowFileSelectionDialogs": False,
    "ExtensionInstallBlocklist": ["*"],
}
# Firefox kurulumunun distribution dizini adayları (yerel paket; Flatpak/Snap Firefox görev kipinde AÇILMAZ)
FIREFOX_KURULUM = ("/usr/lib/firefox*", "/usr/lib64/firefox*", "/opt/firefox*", "/usr/lib/firefox-esr*")
FIREFOX_ETC_ILKE = "/etc/firefox/policies"
CHROMIUM_ILKE_KOKLERI = ("/etc/chromium", "/etc/opt/chrome", "/etc/brave", "/etc/opt/brave.com", "/etc/opt/edge",
                         "/etc/vivaldi", "/etc/opt/vivaldi")
TARAYICI_ANAHTAR = {"firefox": "firefox", "chromium": "chromium", "chrome": "chromium", "brave": "chromium",
                    "edge": "chromium", "vivaldi": "chromium", "opera": "chromium"}


def etkin() -> bool:
    return os.environ.get(ORTAM) == "1"


def siteler() -> tuple[str, ...]:
    """Görevde oturumla girilebilecek siteler (alan adları; boş → çerezsiz temiz profil)."""
    return site_ayristir(os.environ.get(SITE_ORTAM, ""))


_ALAN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
# Tek başına izin verilmeyen genel son ekler (küçük liste; tam PSL değil): "com.tr" tüm Türk ticari sitelerinin
# çerezini görev profiline taşırdı.
GENEL_SON_EKLER = frozenset("""com net org edu gov mil int info biz io co me tv app dev xyz eu tr uk de fr us
com.tr net.tr org.tr edu.tr gov.tr k12.tr av.tr bel.tr gen.tr web.tr biz.tr info.tr tv.tr pol.tr tsk.tr
co.uk org.uk ac.uk gov.uk me.uk ltd.uk plc.uk com.au net.au org.au co.jp co.kr com.br com.cn co.in co.nz co.za
com.mx com.ar github.io blogspot.com herokuapp.com""".split())


def site_ayristir_ayrintili(metin: str) -> tuple[tuple[str, ...], list[str]]:
    """→ (geçerli alan adları, reddedilenler [(girdi, neden)] metinleri). Joker (*), tek başına genel son ek
    (com, com.tr, co.uk…), noktasız ad RET."""
    sonuc: list[str] = []
    ret: list[str] = []
    for ham in re.split(r"[,\s;]+", metin or ""):
        p = ham.strip().lower()
        if not p:
            continue
        p = re.sub(r"^[a-z][a-z0-9+.-]*://", "", p).split("/")[0].split(":")[0].strip(".")
        if "*" in p:
            ret.append(_("{site}: joker (*) kullanılamaz, tam alan adı yazın").format(site=ham))
            continue
        if not _ALAN.match(p) or "." not in p:
            if p in GENEL_SON_EKLER:
                ret.append(_("{site}: tek başına genel son ek olamaz").format(site=ham))
            else:
                ret.append(_("{site}: geçersiz alan adı").format(site=ham))
            continue
        if p in GENEL_SON_EKLER:
            ret.append(_("{site}: tek başına genel son ek olamaz").format(site=ham))
            continue
        if p not in sonuc:
            sonuc.append(p)
    return tuple(sonuc[:50]), ret


def site_ayristir(metin: str) -> tuple[str, ...]:
    """'github.com, https://www.isbank.com.tr/x' → ('github.com', 'www.isbank.com.tr'). Geçersizler atılır; joker
    ('*'), tek başına genel son ek (com, com.tr, co.uk…) izin vermez (site_ayristir_ayrintili: neden metinleri)."""
    return site_ayristir_ayrintili(metin)[0]


def indirme_dizini(olustur: bool = True) -> str:
    d = os.path.join(yollar.runtime_dir(), "gorev-indirilenler")
    if olustur:
        os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def indirme_dizini_bosalt() -> None:
    """Görev BAŞINDA: önceki görevin indirdikleri yeni görevin tarayıcısına görünmesin (klasör boşaltılır)."""
    d = indirme_dizini(olustur=False)
    if os.path.islink(d):
        os.unlink(d)
    elif os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    indirme_dizini()


def indirilenler() -> list[str]:
    """Görev indirme klasöründeki dosyalar (görev bitince kullanıcıya bildirilir)."""
    d = indirme_dizini(olustur=False)
    try:
        return sorted(f for f in os.listdir(d) if not f.endswith(".part"))
    except OSError:
        return []


def adres_yasak(adres: str | None) -> bool:
    a = (adres or "").strip().lower()
    if not a or a.split("#")[0].split("?")[0] in SERBEST_ADRESLER:
        return False
    return a.startswith(YASAK_SEMALAR)


# ---------------------------------------------------------------- tarayıcı ilkesi (ad alanında bağlanır)

def firefox_dagitim_dizinleri() -> list[str]:
    sonuc = []
    for kalip in FIREFOX_KURULUM:
        for k in sorted(glob.glob(kalip)):
            d = os.path.join(k, "distribution")
            if os.path.isfile(os.path.join(k, "application.ini")) and os.path.isdir(d) and not os.path.islink(d):
                g = os.path.realpath(d)
                if g not in sonuc:
                    sonuc.append(g)
    return sonuc


def chromium_ilke_kokleri() -> list[str]:
    return [k for k in CHROMIUM_ILKE_KOKLERI if os.path.isdir(k) and not os.path.islink(k)]


def _yaz(yol: str, veri: str) -> None:
    os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
    gecici = yol + ".yeni"
    with open(gecici, "w", encoding="utf-8") as f:
        f.write(veri)
    os.chmod(gecici, 0o644)  # ad alanındaki tarayıcı okur (aynı kullanıcı)
    os.replace(gecici, yol)


def ilke_baglari() -> list[tuple[str, str]]:
    """Görev kipi tarayıcı ilkeleri → [(kaynak, ad alanındaki hedef)] (salt okunur bağlanacak dizinler). Firefox:
    kurulumun distribution/ dizini yerine policies.json (+ özgün distribution.ini) içeren bir dizin; Chromium ailesi:
    /etc/chromium vb. yerine policies/managed/deskhand-gorev.json. Kaynaklar RUNTIME_DIR/gorev-ilke altında."""
    kok = os.path.join(yollar.runtime_dir(), "gorev-ilke")
    baglar: list[tuple[str, str]] = []
    ff = dict(FIREFOX_ILKE)
    ff["DownloadDirectory"] = indirme_hedefi()
    for i, d in enumerate(firefox_dagitim_dizinleri()):
        hedef = os.path.join(kok, f"firefox-{i}")
        _yaz(os.path.join(hedef, "policies.json"), json.dumps({"policies": ff}, indent=1))
        ini = os.path.join(d, "distribution.ini")
        if os.path.isfile(ini):
            try:
                with open(ini, encoding="utf-8", errors="replace") as f:
                    _yaz(os.path.join(hedef, "distribution.ini"), f.read())
            except OSError:
                pass
        baglar.append((hedef, d))
    if baglar and os.path.isdir(FIREFOX_ETC_ILKE) and not os.path.islink(FIREFOX_ETC_ILKE):
        # Linux Firefox ÖNCE /etc/firefox/policies/policies.json'a bakar; varsa distribution/ hiç okunmaz → aynı
        # görev ilkesi oraya da bağlanır (kullanıcının sistem ilkesi görevde yerini alır)
        baglar.append((baglar[0][0], FIREFOX_ETC_ILKE))
    ch = dict(CHROMIUM_ILKE)
    ch["DownloadDirectory"] = indirme_hedefi()
    for i, d in enumerate(chromium_ilke_kokleri()):
        hedef = os.path.join(kok, f"chromium-{i}")
        _yaz(os.path.join(hedef, "policies", "managed", "deskhand-gorev.json"), json.dumps(ch, indent=1))
        baglar.append((hedef, d))
    return baglar


def indirme_hedefi(ev: str | None = None) -> str:
    """Ad alanında görev indirme klasörünün göründüğü yol: kullanıcının XDG_DOWNLOAD_DIR'i (ev içinde), yoksa
    ~/Downloads."""
    from .arka_ortak import gercek_ev, _nokta_yok
    ev = os.path.realpath(ev or gercek_ev())
    try:
        with open(os.path.join(ev, ".config", "user-dirs.dirs"), encoding="utf-8", errors="replace") as f:
            for satir in f:
                m = re.fullmatch(r'\s*XDG_DOWNLOAD_DIR="(.*)"\s*', satir)
                if m:
                    v = m.group(1)
                    if v.startswith("$HOME"):
                        v = ev + v[len("$HOME"):]
                    v = os.path.normpath(v)
                    if v.startswith(ev + "/") and _nokta_yok(ev, v):
                        return v
    except OSError:
        pass
    return os.path.join(ev, "Downloads")


# ---------------------------------------------------------------- open_app

def tarayici_anahtari(politika_anahtarlari) -> str | None:
    """Çözülmüş uygulamanın oturum politikası anahtarları → 'firefox' | 'chromium' | None (tarayıcı değil)."""
    turler = {TARAYICI_ANAHTAR.get(k) for k in politika_anahtarlari}
    if len(turler) == 1 and None not in turler:
        return turler.pop()
    return None


def open_app_denetle(kimlik: str, belgeler) -> str | None:
    """Görev kipinde open_app izinli mi? → None (izinli) | ret nedeni. Yalnız yerel paket Firefox (ilke bağlanabilen)
    ya da ilke kökü olan Chromium ailesi; Flatpak/Snap tarayıcı, uçbirim, dosya yöneticisi, düzenleyici RET. Belge
    argümanları yalnız http(s) adresi."""
    from .oturum import cozum, politika
    yap = politika.yukle()
    c = cozum.coz(kimlik)
    anahtarlar: list[str] = []
    for ad in c.adlar:
        for k in politika.eslesen_anahtarlar(ad, yap):
            if k not in anahtarlar:
                anahtarlar.append(k)
    tur = tarayici_anahtari(anahtarlar)
    if tur is None:
        return N_("görev kipinde yalnız web tarayıcısı açılabilir")
    if c.flatpaklar:
        return N_("görev kipinde Flatpak tarayıcı açılmaz (tarayıcı ilkesi bağlanamaz)")
    if tur == "firefox" and not firefox_dagitim_dizinleri():
        return N_("Firefox kurulumunda distribution dizini yok: görev ilkesi bağlanamıyor")
    if tur == "chromium" and not chromium_ilke_kokleri():
        return N_("Chromium ilke dizini (/etc/chromium vb.) yok: görev ilkesi bağlanamıyor")
    for b in belgeler or ():
        if not re.match(r"^https?://", str(b), re.I):
            return N_("görev kipinde yalnız http(s) adresi açılabilir")
    return None


# ---------------------------------------------------------------- maskeleme (geçmiş/günlük)

_KART = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_PAROLA = re.compile(r"(?i)\b(parola|şifre|sifre|password|passwd|pass|pin|token|api[ _-]?key)(\s*[:=]\s*|\s+)(\S+)")


def maskele(metin: str) -> tuple[str, bool]:
    """Görev metninde kart numarası / 'parola: X' kalıbı → maskelenmiş metin, bulundu mu."""
    bulundu = False

    def kart(m):
        nonlocal bulundu
        rakam = re.sub(r"\D", "", m.group(0))
        if not _luhn(rakam):
            return m.group(0)
        bulundu = True
        return "[kart ****" + rakam[-4:] + "]"

    def parola(m):
        nonlocal bulundu
        bulundu = True
        return f"{m.group(1)}{m.group(2)}[gizli]"

    s = _KART.sub(kart, metin or "")
    s = _PAROLA.sub(parola, s)
    return s, bulundu


def _luhn(r: str) -> bool:
    if not 13 <= len(r) <= 19:
        return False
    t = 0
    for i, c in enumerate(reversed(r)):
        d = int(c) * (2 if i % 2 else 1)
        t += d - 9 if d > 9 else d
    return t % 10 == 0


# Görev uygulama ad alanında boş dosyayla örtülen ikililer (ORTA-2 iii): tarayıcıdan bir kabuk açılsa bile girdi
# enjeksiyonu (xdotool/kdotool/ydotool/wtype), X anahtarı dökümü (xauth) ve dış uygulama açıcı (xdg-open) yok.
MASKELI_IKILILER = ("xdotool", "kdotool", "ydotool", "wtype", "xauth", "xdg-open", "gio", "kioclient", "kioclient5",  # ad listesi, çağrı değil
                    "kde-open", "kde-open5")


def maskeli_ikililer() -> list[str]:
    sonuc = []
    for d in ("/usr/bin", "/usr/local/bin"):
        for ad in MASKELI_IKILILER:
            y = os.path.join(d, ad)
            if os.path.isfile(y) and os.path.realpath(y) not in sonuc:
                sonuc.append(y)
    return sonuc


# ---------------------------------------------------------------- görev ortamı: kimlik bilgisi değişkenleri

# Görev kipinde claude'a, MCP sunucusuna ve uygulamalara GEÇMEYEN değişkenler (ad deseni). claude girişini
# ~/.claude/.credentials.json'dan okur (OAuth); CLAUDE_ORTAM_IZINLI ile yalnız claude'un kendi giriş değişkeni kalır.
KIMLIK_ORTAM_DENEN = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIAL|API_?KEY|ACCESS_?KEY|"
                                r"PRIVATE_?KEY|(^|_)KEY($|_)|AUTH|COOKIE|SESSION_?ID)", re.I)
CLAUDE_ORTAM_IZINLI = ("CLAUDE_CODE_OAUTH_TOKEN",)


def ortam_temizle(ortam: dict, izinli: tuple = ()) -> dict:
    """KIMLIK_ORTAM_DENEN desenine uyan değişkenler atılmış kopya (izinli adlar kalır)."""
    return {k: v for k, v in ortam.items() if k in izinli or not KIMLIK_ORTAM_DENEN.search(k)}


# ---------------------------------------------------------------- görev masaüstü (BÜYÜK-1)

# Panel önizlemesi (kullanıcının kendi süreci) görev masaüstünü görebilir; panel başlarken True yapar.
GOZLEMCI = False


def masaustu_isaret_yolu() -> str:
    return os.path.join(yollar.runtime_dir(), "gorev-masaustu")


def _surec_baslangic(pid) -> str | None:
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            s = f.read()
        return s[s.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def masaustu_ayir() -> None:
    """Görev başlarken: görünmez masaüstü bu görevin (sahip: bu süreç + başlangıç zamanı; sahip ölürse işaret
    geçersiz)."""
    yol = masaustu_isaret_yolu()
    os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
    gecici = f"{yol}.{os.getpid()}"
    fd = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{os.getpid()} {_surec_baslangic(os.getpid()) or '-'}\n")
    os.replace(gecici, yol)


def masaustu_birak() -> None:
    try:
        os.remove(masaustu_isaret_yolu())
    except OSError:
        pass


def masaustu_ayrildi() -> bool:
    """Bir görev şu an görünmez masaüstünü ayırmış mı (işaret var ve sahibi canlı)."""
    try:
        with open(masaustu_isaret_yolu()) as f:
            pid, bas = (f.read().split() + ["", ""])[:2]
    except OSError:
        return False
    if not pid.isdigit():
        return False
    simdi = _surec_baslangic(pid)
    return simdi is not None and (bas == "-" or simdi == bas)


def masaustu_kapisi(d: dict | None) -> None:
    """Görünmez masaüstüne bağlanma/uygulama açma kapısı (tüm arka uç bağlantıları ve masaustu.baslat çağırır).
    Görev kipinde: kayıt görevin kendi masaüstü değilse ("gorev" yok) Dur(14). Kipsiz istemcide: masaüstü görevin ya
    da bir görev masaüstünü ayırmışsa Dur(14) (panel önizlemesi GOZLEMCI hariç)."""
    if d is None:
        return
    if etkin():
        if not d.get("gorev"):
            raise Dur(14, _("görev kipi: görünmez masaüstü başka bir iş için açık (görevin kendi masaüstü değil); "
                            "görev ona erişmez. Kullanıcı panelden kapatıp görevi yeniden başlatmalı."))
        return
    if (d.get("gorev") or masaustu_ayrildi()) and not GOZLEMCI:
        raise Dur(14, _("görünmez masaüstü şu an panelin görev ajanına ayrılmış; görev bitince yeniden deneyin "
                        "(ya da panelden görevi durdurun)"))


def baslatma_kapisi(acik: dict | None) -> None:
    """masaustu_baslat: kipsiz istemci görev sürerken masaüstü AÇAMAZ; görev kipi açık başka masaüstünü
    kullanamaz (acik: zaten çalışan masaüstünün kaydı ya da None)."""
    if acik is not None:
        masaustu_kapisi(acik)
    elif not etkin() and masaustu_ayrildi() and not GOZLEMCI:
        raise Dur(14, _("görünmez masaüstü şu an panelin görev ajanına ayrılmış; görev bitince yeniden deneyin "
                        "(ya da panelden görevi durdurun)"))


# ---------------------------------------------------------------- pencere sınırı (ORTA-2)

TARAYICI_SINIFLARI = frozenset({"firefox", "navigator", "firefox-esr", "chromium", "chromium-browser",
                                "google-chrome", "brave-browser", "microsoft-edge", "vivaldi-stable", "opera"})
TARAYICI_IKILILERI = frozenset({"firefox", "firefox-bin", "firefox-esr", "chromium", "chrome", "brave", "msedge",
                                "vivaldi-bin", "opera"})
_YEREL = threading.local()


def _surec_ikilisi(pid) -> str:
    try:
        return os.path.basename(os.readlink(f"/proc/{int(pid)}/exe")).removesuffix(" (deleted)")
    except (OSError, ValueError, TypeError):
        try:
            with open(f"/proc/{int(pid)}/comm") as f:
                return f.read().strip()
        except (OSError, ValueError, TypeError):
            return ""


def pencere_izinli(au, k) -> tuple[bool, str, str, int | None]:
    """→ (izinli mi, sınıf, süreç ikilisi, pid). İzinli = sınıf tarayıcı sınıfı VE penceresinin süreci (X sunucusunun/
    KWin'in bildiği PID) bir tarayıcı ikilisi. Sınıf istemcinin yazdığı bir değerdir: tek başına yetmez."""
    try:
        sinif = (au.sinif(k) or "").lower()
    except Dur:
        sinif = ""
    try:
        pid = au.pid(k)
    except (Dur, AttributeError):
        pid = None
    ikili = _surec_ikilisi(pid) if pid else ""
    return sinif in TARAYICI_SINIFLARI and ikili in TARAYICI_IKILILERI, sinif, ikili, pid


def _yabanci_kapat(au, k, pid, ikili) -> None:
    try:
        au.kapat(k)
    except Exception:  # noqa: BLE001
        pass
    if pid and ikili not in TARAYICI_IKILILERI:
        try:  # yalnız görünmez masaüstü kafesindeki süreç (kullanıcının oturumundaki bir süreç ASLA)
            with open(f"/proc/{int(pid)}/cgroup") as f:
                cg = f.read()
            if re.search(r"deskhand-(sanal|kwin)-", cg):
                os.kill(int(pid), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def _olay_yaz(metin: str) -> None:
    try:
        from .gunluk import gunluk
        gunluk("gorev-kipi | " + metin)
    except Exception:  # noqa: BLE001
        pass


def pencere_denetle(au, k, adres=None) -> None:
    """GÖREV KİPİ: girdi/okuma hedefi yalnız görev tarayıcısının penceresi. Tarayıcı dışı pencere → kapatılır + Dur(10).
    Tüm ekran (EKRAN): ekranda tarayıcı dışı pencere varsa hepsi kapatılır + Dur(10); hiç tarayıcı penceresi yoksa
    Dur(10). adres: pencerenin web belgesi adresini veren işlev (yasak adreste girdi de reddedilir)."""
    if not etkin() or getattr(_YEREL, "icinde", False):
        return
    _YEREL.icinde = True
    try:
        from .arka_uc import EKRAN
        if not k or k == EKRAN:
            yabanci, izinli = [], 0
            for w, _b, _g in au.pencereler():
                ok, sinif, ikili, pid = pencere_izinli(au, w)
                if ok:
                    izinli += 1
                else:
                    yabanci.append(f"{sinif or '?'}/{ikili or '?'}")
                    _yabanci_kapat(au, w, pid, ikili)
            if yabanci:
                _olay_yaz(f"tarayıcı dışı pencere kapatıldı: {', '.join(yabanci)}")
                raise Dur(10, _("görev kipi: görev masaüstünde tarayıcı dışı pencere belirdi ({pencereler}); "
                                "kapatıldı, işlem yapılmadı").format(pencereler=", ".join(yabanci)))
            if not izinli:
                raise Dur(10, _("görev kipi: görev masaüstünde görev tarayıcısının penceresi yok; tüm ekran "
                                "okunmaz/girdi gönderilmez"))
            return
        ok, sinif, ikili, pid = pencere_izinli(au, k)
        if not ok:
            _yabanci_kapat(au, k, pid, ikili)
            _olay_yaz(f"tarayıcı dışı pencere kapatıldı: {sinif or '?'}/{ikili or '?'}")
            raise Dur(10, _("görev kipi: yalnız görev tarayıcısının pencereleri kullanılır; bu pencere ({sinif}/"
                            "{ikili}) kapatıldı, işlem yapılmadı").format(sinif=sinif or "?", ikili=ikili or "?"))
        if adres is not None:
            a = adres(k)
            if adres_yasak(a):
                raise Dur(10, _("görev kipi: yerel dosya / tarayıcı iç sayfası ({adres}); okuma ve girdi "
                                "yapılmaz").format(adres=(a or "")[:60]))
    finally:
        _YEREL.icinde = False
