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
  - observe/read_text/screenshot: tarayıcı belgesi file:/about:/chrome:… ise RET (savunma derinliği).
"""
from __future__ import annotations

import glob
import json
import os
import re

from . import yollar
from .i18n import N_

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
    "WebsiteFilter": {"Block": ["file:///*", "file://*/*"]},
    "PromptForDownloadLocation": False,
    "Preferences": {"signon.rememberSignons": {"Value": False, "Status": "locked"},
                    "signon.autofillForms": {"Value": False, "Status": "locked"},
                    "browser.download.useDownloadDir": {"Value": True, "Status": "locked"}},
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
CHROMIUM_ILKE_KOKLERI = ("/etc/chromium", "/etc/opt/chrome", "/etc/brave", "/etc/opt/brave.com", "/etc/opt/edge",
                         "/etc/vivaldi", "/etc/opt/vivaldi")
TARAYICI_ANAHTAR = {"firefox": "firefox", "chromium": "chromium", "chrome": "chromium", "brave": "chromium",
                    "edge": "chromium", "vivaldi": "chromium", "opera": "chromium"}


def etkin() -> bool:
    return os.environ.get(ORTAM) == "1"


def siteler() -> tuple[str, ...]:
    """Görevde oturumla girilebilecek siteler (alan adları; boş → çerezsiz temiz profil)."""
    return site_ayristir(os.environ.get(SITE_ORTAM, ""))


_ALAN = re.compile(r"^[a-z0-9*](?:[a-z0-9*.-]{0,251}[a-z0-9])?$")


def site_ayristir(metin: str) -> tuple[str, ...]:
    """'github.com, https://www.isbank.com.tr/x' → ('github.com', 'www.isbank.com.tr'). Geçersizler atılır; tek başına
    '*' ya da üst düzey alan (com) izin vermez."""
    sonuc: list[str] = []
    for p in re.split(r"[,\s;]+", metin or ""):
        p = p.strip().lower()
        if not p:
            continue
        p = re.sub(r"^[a-z][a-z0-9+.-]*://", "", p).split("/")[0].split(":")[0].strip(".")
        if not _ALAN.match(p) or "." not in p.strip("*.") or p.strip("*.") == "":
            continue
        if p not in sonuc:
            sonuc.append(p)
    return tuple(sonuc[:50])


def indirme_dizini(olustur: bool = True) -> str:
    d = os.path.join(yollar.runtime_dir(), "gorev-indirilenler")
    if olustur:
        os.makedirs(d, mode=0o700, exist_ok=True)
    return d


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
