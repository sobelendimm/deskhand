"""Firefox profilinin tutarlı, tek yönlü anlık kopyası (docs/SESSIONS.md §3).

Kaynak = gerçek profil (tespit.firefox_profil_dizini, realpath; psd'nin *-backup/*-back-ovfs bayat kopyaları ASLA).
Kopyalanan: cookies.sqlite (tutarlı), key4.db, cert9.db, logins.json (+ logins.db [Rust aynası], logins-backup.json),
permissions.sqlite, containers.json, pkcs11.txt, yalnız İZİN VERİLEN sitelerin storage/default/<origin>,
uzantılar. KOPYALANMAZ: signedInUser.json, weave, lock/.parentlock, places*, sessionstore'un kendisi, telemetri.

Oturum çerezleri (yalnız recovery.jsonlz4'te) mozlz4 çözülüp kopyanın cookies.sqlite'ına eklenir (ret hariç).
Ret listesindeki alanların çerezi (alan çerezi ".google.com" ret listesindeki alt alana da gidiyorsa o da; kullanıcı
panelden Hesap oturumları iznini açtıysa o sağlayıcının merkezi kimlik alanları hariç [görev kipinde hiç]),
deposu ve KAYITLI PAROLALARI (logins.json / logins-backup.json / logins.db aynası aynı kayıtlar; şifreli değerlere
dokunulmaz, kayıt bütünüyle silinir) kopyadan SİLİNİR. permissions.sqlite'tan kamera/mikrofon/ekran paylaşımı/
konum/bildirim izinleri silinir (arka planda gerçek kamera açılmasın). user.js: Sync/FxA kapalı, bu izinlerin
varsayılanı "engelle", ilk açılış/telemetri/oturum geri yükleme/otomatik oynatma/güncelleme kapalı.

Başlatma: firefox --profile KOPYA --no-remote --new-instance
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import struct

from . import kopya as kopya_mod
from . import tespit
from ..i18n import _
from .politika import Politika

# Profil kökünden kopyalanacak basit dosyalar (SQLite dışı; oturum için gerekenler)
_DUZ_DOSYALAR = ("key4.db", "cert9.db", "logins.json", "logins-backup.json",
                 "pkcs11.txt", "containers.json", "handlers.json", "cert_override.txt",
                 "extensions.json", "extension-settings.json", "extension-preferences.json",
                 "addonStartup.json.lz4", "addons.json", "search.json.mozlz4", "compatibility.ini")
# SQLite (tutarlı yedek gerektiren)
_SQLITE_DOSYALAR = ("cookies.sqlite", "permissions.sqlite", "storage.sqlite", "logins.db")
# Kopyadaki permissions.sqlite'tan silinen izin türleri (arka planda cihaz/konum/bildirim yok)
_SILINEN_IZINLER = ("camera", "microphone", "screen", "geo", "desktop-notification", "persistent-notification",
                    "xr", "speaker-selection", "midi", "midi-sysex", "MediaManagerVideo", "MediaManagerAudio")
# Dizinler (olduğu gibi, dışlamayla)
_DIZINLER = ("extensions", "browser-extension-data", "settings", "security_state")

# user.js: Sync/FxA/telemetri/oturum geri yükleme/otomatik oynatma/güncelleme kapalı
_USER_JS = """// Deskhand oturum köprüsü — arka plan kopyası (tek yönlü, geçici)
user_pref("identity.fxaccounts.enabled", false);
user_pref("services.sync.engine.tabs", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.page", 0);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("media.autoplay.default", 5);
user_pref("media.autoplay.blocking_policy", 2);
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
user_pref("browser.profiles.enabled", false);
user_pref("toolkit.profiles.storeID", "");
user_pref("browser.backup.enabled", false);
user_pref("browser.backup.scheduled.enabled", false);
user_pref("browser.backup.archive.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.firstrunSkipsHomepage", true);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("media.navigator.permission.disabled", false);
user_pref("permissions.default.camera", 2);
user_pref("permissions.default.microphone", 2);
user_pref("permissions.default.desktop-notification", 2);
user_pref("permissions.default.geo", 2);
user_pref("permissions.default.xr", 2);
user_pref("browser.cache.disk.smart_size.enabled", false);
user_pref("browser.cache.disk.capacity", 65536);
"""


# GÖREV KİPİ (gorev_kipi): kopyaya HİÇ girmeyenler (parolalar, anahtar deposu, uzantılar ve verileri)
GOREV_DISLA = ("logins.json", "logins-backup.json", "logins.db", "key4.db", "signedInUser.json",
               "extensions", "browser-extension-data", "extensions.json", "extension-settings.json",
               "extension-preferences.json", "addonStartup.json.lz4", "addons.json")
_GOREV_USER_JS = """// Deskhand GÖREV KİPİ: parola yöneticisi kapalı, yerel dosya/iç sayfa ilkesi distribution/policies.json'da
user_pref("signon.rememberSignons", false);
user_pref("signon.autofillForms", false);
user_pref("signon.generation.enabled", false);
user_pref("signon.management.page.breach-alerts.enabled", false);
user_pref("devtools.policy.disabled", true);
user_pref("browser.download.useDownloadDir", true);
user_pref("extensions.enabledScopes", 0);
"""


def gorev_izinli(politika: Politika, alan: str, gorev_siteleri) -> bool:
    """Görev kipi site izni: görev siteleri BOŞSA hiçbir site (çerezsiz profil); ret listesi her zaman kazanır."""
    from .politika import _alan_eslesir
    return bool(gorev_siteleri) and not politika.site_reddedildi(alan) and _alan_eslesir(alan, gorev_siteleri)


def _cerez_say(cookies_db: str) -> int:
    con = sqlite3.connect(cookies_db)
    try:
        return con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
    finally:
        con.close()


def _gorev_cerez_suz(cookies_db: str, politika: Politika, gorev_siteleri) -> int:
    """Görev kipi: izinli siteler dışındaki TÜM çerezleri sil. Döner: silinen satır."""
    con = sqlite3.connect(cookies_db)
    try:
        silinen = 0
        for (h,) in con.execute("SELECT DISTINCT host FROM moz_cookies").fetchall():
            if not gorev_izinli(politika, _alan(h), gorev_siteleri):
                silinen += con.execute("DELETE FROM moz_cookies WHERE host=?", (h,)).rowcount
        con.commit()
        return silinen
    finally:
        con.close()


# ------------------------------------------------------------------ mozlz4

def mozlz4_coz(yol: str) -> bytes | None:
    """mozLz40 (recovery.jsonlz4 vb.) dosyasını çöz → JSON baytları. python-lz4 gerekir. Hata/eksikte None."""
    try:
        import lz4.block
    except ImportError:
        return None
    try:
        with open(yol, "rb") as f:
            sihir = f.read(8)
            if sihir != b"mozLz40\0":
                return None
            (boyut,) = struct.unpack("<I", f.read(4))
            return lz4.block.decompress(f.read(), uncompressed_size=boyut)
    except (OSError, ValueError, struct.error):
        return None


def _alan(host: str) -> str:
    return (host or "").lstrip(".").lower()


def _recovery_oku(recovery: str) -> dict:
    ham = mozlz4_coz(recovery) if recovery and os.path.isfile(recovery) else None
    if ham is None:
        return {}
    try:
        veri = json.loads(ham)
    except (ValueError, UnicodeDecodeError):
        return {}
    return veri if isinstance(veri, dict) else {}


def _bilinen_konaklar(kaynak: str, cookies_db: str, recovery: dict) -> set[str]:
    """Hosts known from the profile (read only; values are never read): cookie hosts of the copy, site storage
    folders, session-cookie hosts and open-tab hosts of recovery.jsonlz4, and visited origins in places.sqlite
    (opened read-only + immutable: no -wal/-shm is created in the user's profile). Used to decide whether a domain
    cookie (`.example.com`) would also be sent to a rejected subdomain (`*bank*` -> bank.example.com)."""
    from urllib.parse import quote, urlsplit
    konaklar: set[str] = set()
    try:
        con = sqlite3.connect(cookies_db)
        try:
            konaklar |= {_alan(r[0]) for r in con.execute("SELECT DISTINCT host FROM moz_cookies")}
        finally:
            con.close()
    except sqlite3.Error:
        pass
    try:
        for ad in os.listdir(os.path.join(kaynak, "storage", "default")):
            if "+++" in ad:
                konaklar.add(ad.split("+++", 1)[1].split("^", 1)[0].split("+", 1)[0].lower())
    except OSError:
        pass
    for c in recovery.get("cookies") or ():
        if isinstance(c, dict):
            konaklar.add(_alan(c.get("host", "")))
    for p in recovery.get("windows") or ():
        for sekme in (p.get("tabs") or ()) if isinstance(p, dict) else ():
            for g in (sekme.get("entries") or ()) if isinstance(sekme, dict) else ():
                try:
                    konaklar.add((urlsplit(str(g.get("url", ""))).hostname or "").lower())
                except (ValueError, AttributeError):
                    pass
    yer = os.path.join(kaynak, "places.sqlite")
    if os.path.isfile(yer):
        try:
            con = sqlite3.connect(f"file:{quote(yer)}?mode=ro&immutable=1", uri=True)
            try:
                konaklar |= {str(r[0]).lower() for r in con.execute("SELECT DISTINCT host FROM moz_origins")}
            finally:
                con.close()
        except sqlite3.Error:
            pass
    konaklar.discard("")
    return konaklar


def _cookies_yeniden_kur(cookies_db: str) -> bool:
    """Rebuild the copied cookies.sqlite from its remaining rows only (VACUUM INTO a new file): rows removed with
    DELETE can stay as raw bytes in free pages, in the WAL or in page slack when secure_delete is off. The old file
    and its -wal/-shm/-journal are deleted. On any failure the cookie database is removed entirely (no session beats
    leaking a rejected value). Returns True when the rebuilt database is in place."""
    yeni = cookies_db + ".yeni"
    yan = [cookies_db + e for e in ("-wal", "-shm", "-journal")]
    try:
        if os.path.exists(yeni):
            os.remove(yeni)
        con = sqlite3.connect(cookies_db)
        try:
            con.execute("PRAGMA secure_delete=ON")
            con.execute("VACUUM INTO ?", (yeni,))
        finally:
            con.close()
        for y in [cookies_db] + yan:
            if os.path.exists(y):
                os.remove(y)
        os.replace(yeni, cookies_db)
        return True
    except (sqlite3.Error, OSError):
        for y in [cookies_db, yeni] + yan:
            try:
                os.remove(y)
            except OSError:
                pass
        return False


# ------------------------------------------------------------------ ana kopya

def hazirla(politika: Politika, gorev_siteleri=None) -> dict:
    """Firefox profilini kopyala. Döner: {kopya_yolu, argv, kaynak, origin_sayisi, cerez_sayisi,
    oturum_cerez_eklendi, ret_silindi, durum}. Kaynak yazılmaz. 'durum'=hata açıklaması (None=tamam)."""
    kaynak = tespit.firefox_profil_dizini()
    if not kaynak or not os.path.isdir(kaynak):
        return {"durum": _("Firefox profili bulunamadı (profiles.ini)"), "kopya_yolu": None, "argv": []}

    hedef = kopya_mod.yeni_kopya_dizini("firefox")
    disla = set(politika.disla)
    from .. import gorev_kipi
    gorev = gorev_kipi.etkin()
    kimlik_izni: frozenset = frozenset()
    orijinal = politika  # izinsiz ret listesi (kimlik özeti: hangi çerez/giriş izin sayesinde geldi)
    if gorev:  # GÖREV KİPİ: kayıtlı parolalar + anahtar deposu + uzantılar (verileriyle) KOPYALANMAZ; site = görev izni
        disla |= set(GOREV_DISLA)
        gorev_siteleri = gorev_kipi.siteler()
        # hesap oturumu izni görev kipinde HİÇ uygulanmaz: kimlik çerezleri her zaman süzülür (panel izni olsa bile)
    else:
        # Hesap oturumları (panel yetkili; ARCHITECTURE §4): kullanıcı panelden açtıysa o sağlayıcının merkezi kimlik
        # alanları ret listesinden çıkar (çerez + kayıtlı giriş). Panel kapalı / doğrulanamıyor → izin yok.
        from .. import liste_koruma
        try:
            kimlik_izni = liste_koruma.kimlik_izinleri()
        except Exception:  # noqa: BLE001 - doğrulanamadı: güvenli taraf (izin yok)
            kimlik_izni = frozenset()
        politika = politika.kimlik_izni_uygula(kimlik_izni)
    bilgi = {"kopya_yolu": hedef, "kaynak": kaynak, "durum": None,
             "cerez_sayisi": 0, "oturum_cerez_eklendi": 0, "ret_silindi": 0, "origin_sayisi": 0,
             "giris_silindi": 0, "izin_silindi": 0, "kimlik_izni": sorted(kimlik_izni)}

    # 1) SQLite dosyaları (tutarlı)
    for ad in _SQLITE_DOSYALAR:
        k = os.path.join(kaynak, ad)
        if ad in disla or not os.path.isfile(k):
            continue
        try:
            kopya_mod.sqlite_yedek(k, os.path.join(hedef, ad))
        except sqlite3.Error:
            pass

    # 2) düz dosyalar
    for ad in _DUZ_DOSYALAR:
        if ad in disla:
            continue
        kopya_mod.dosya_kopyala(os.path.join(kaynak, ad), os.path.join(hedef, ad))

    # 3) dizinler
    dizin_disla = disla | {"Cache", "cache", "startupCache", "minidumps", "crashes"}
    for d in _DIZINLER:
        if d in disla:
            continue
        kopya_mod.dizin_kopyala(os.path.join(kaynak, d), os.path.join(hedef, d), disla=dizin_disla)

    # 3b) kayıtlı parolalar: ret listesindeki alanların girişleri; izinler: kamera/mikrofon/ekran/konum/bildirim
    bilgi["giris_silindi"] = _girisleri_suz(hedef, politika)
    bilgi["izin_silindi"] = _izinleri_suz(os.path.join(hedef, "permissions.sqlite"))

    # 4) ret listesi alanlarını kopya cookies.sqlite'ından sil, izinli alanları/çerez alanlarını topla
    kopya_cookies = os.path.join(hedef, "cookies.sqlite")
    izinli_alanlar: set[str] = set()
    kimlik_mevcut = _kimlik_cerez_say(kopya_cookies, orijinal) if os.path.isfile(kopya_cookies) else {}
    rec = os.path.join(kaynak, "sessionstore-backups", "recovery.jsonlz4")
    bilinen = _bilinen_konaklar(kaynak, kopya_cookies, _recovery_oku(rec)) if os.path.isfile(kopya_cookies) else set()
    if os.path.isfile(kopya_cookies):
        bilgi["cerez_sayisi"], bilgi["ret_silindi"], izinli_alanlar = _cookies_suz(
            kopya_cookies, politika, gorev_siteleri, bilinen)

    if gorev and os.path.isfile(kopya_cookies):  # görevde izin verilmeyen sitelerin çerezleri SİLİNİR (boş = hepsi)
        bilgi["gorev_cerez_silindi"] = _gorev_cerez_suz(kopya_cookies, politika, gorev_siteleri)
        izinli_alanlar = {a for a in izinli_alanlar if gorev_izinli(politika, a, gorev_siteleri)}
        bilgi["cerez_sayisi"] = _cerez_say(kopya_cookies)
    # 5) oturum çerezleri (recovery.jsonlz4 → kopya cookies.sqlite)
    if os.path.isfile(rec) and os.path.isfile(kopya_cookies) and (not gorev or gorev_siteleri):
        eklendi, ek_alanlar = _oturum_cerezleri_ekle(rec, kopya_cookies, politika, gorev_siteleri, gorev, bilinen)
        bilgi["oturum_cerez_eklendi"] = eklendi
        izinli_alanlar |= ek_alanlar
    # 5a) the copy keeps only the allowed rows: rebuilt so that no removed value survives in the file bytes
    if os.path.isfile(kopya_cookies) and not _cookies_yeniden_kur(kopya_cookies):
        bilgi["cerez_sayisi"] = 0

    # 5b) kimlik oturumu özeti (kullanıcı/ajan neden giriş istendiğini görsün): izinle aktarılan / izinsiz süzülen
    bilgi["kimlik_ozet"] = _kimlik_ozet(kopya_cookies, hedef, orijinal, kimlik_izni, kimlik_mevcut)
    bilgi["kimlik_metni"] = kimlik_ozeti_metni(bilgi["kimlik_ozet"], gorev)
    _kimlik_son_yaz(bilgi["kimlik_ozet"], gorev)

    # 6) yalnız izin verilen origin'lerin storage/default/<origin> klasörleri
    # Görev sitesi verilmediyse site deposu kopyalanmaz: ~575 alan × yerel depo yüzlerce MB olabiliyordu;
    # çoğu sitede oturum çerezle açılır. Site verilirse (ac --site github.com) yalnız onların deposu gelir.
    bilgi["origin_sayisi"] = (_storage_kopyala(kaynak, hedef, izinli_alanlar, politika) if gorev_siteleri else 0)

    # 7) user.js
    _user_js_yaz(hedef, kaynak, gorev)
    bilgi["gorev"] = gorev

    bilgi["argv"] = ["firefox", "--profile", hedef, "--no-remote", "--new-instance"]
    # Kopya Firefox kullanıcının profil kökünü (~/.config/mozilla/firefox: profiles.ini, installs.ini, Profile Groups)
    # HİÇ görmesin: kendi yapılandırma kökü + eski tip profil yönetimi (kuruluma özel varsayılan yazmaz). Kökte
    # kullanıcının XDG klasör adları + GTK/yazı tipi görünümü OLMALI: yoksa GTK "Masaüstü" = var olmayan ~/Desktop,
    # İndirilenler çözülmez ve Firefox ad alanındaki geçici ~/Downloads'a indirir (kapanınca kaybolur; gerçek olay).
    xdg = os.path.join(hedef, ".xdg-config")
    bilgi["indirme_dizini"] = xdg_yapilandirma_kur(xdg, gorev)
    _indirme_prefleri_yaz(hedef, bilgi["indirme_dizini"])
    bilgi["env_ek"] = {"XDG_CONFIG_HOME": xdg, "MOZ_LEGACY_PROFILES": "1"}
    kopya_mod.izinleri_daralt(hedef)
    return bilgi


# Kopyanın kendi XDG_CONFIG_HOME'una alınan kullanıcı ayarları (yalnız GÖRÜNÜM + klasör adları; ev beyaz listesinin
# alt kümesi, arka_ortak.EV_BEYAZ_LISTE): sembolik bağlar izlenmez, dizin başına boyut sınırı.
_XDG_DOSYALAR = ("user-dirs.dirs", "user-dirs.locale", "mimeapps.list")
_XDG_DIZINLER = ("gtk-3.0", "gtk-4.0", "fontconfig")
_XDG_DIZIN_AZAMI = 4 * 1024 * 1024


def indirme_dizini(gorev: bool = False, ev: str | None = None) -> str | None:
    """Arka plan tarayıcısının indirme klasörü (ad alanında göründüğü yol): görev kipinde görevin indirme klasörü
    (gorev_kipi.indirme_hedefi; ad alanında oraya bağlıdır), değilse kullanıcının XDG_DOWNLOAD_DIR'i — YALNIZ ad
    alanında yazılabilir gerçek bir veri klasörüyse (arka_ortak.veri_klasorleri); yoksa None (tercih yazılmaz)."""
    from .. import gorev_kipi
    from ..arka_ortak import gercek_ev, veri_klasorleri
    ev = os.path.realpath(ev or gercek_ev())
    yol = gorev_kipi.indirme_hedefi(ev)
    if gorev:
        return yol
    return yol if os.path.realpath(yol) in veri_klasorleri(ev) else None


def xdg_yapilandirma_kur(xdg: str, gorev: bool = False, ev: str | None = None) -> str | None:
    """Kopyanın XDG_CONFIG_HOME'unu (0700) kur: kullanıcının user-dirs.dirs / user-dirs.locale / mimeapps.list ve
    gtk-3.0 / gtk-4.0 / fontconfig görünüm ayarları (0600 kopya). Görev kipinde user-dirs.dirs'teki XDG_DOWNLOAD_DIR
    görevin indirme klasörünü gösterir. Kaynak yazılmaz. → indirme_dizini()."""
    from ..arka_ortak import gercek_ev
    ev = os.path.realpath(ev or gercek_ev())
    os.makedirs(xdg, mode=0o700, exist_ok=True)
    kaynak = os.path.join(ev, ".config")
    for ad in _XDG_DOSYALAR:
        k = os.path.join(kaynak, ad)
        if not os.path.islink(k):
            kopya_mod.dosya_kopyala(k, os.path.join(xdg, ad))
    for d in _XDG_DIZINLER:
        k = os.path.join(kaynak, d)
        if os.path.isdir(k) and not os.path.islink(k):
            kopya_mod.dizin_kopyala(os.path.dirname(k), xdg, yalnizca={d}, boyut_siniri=_XDG_DIZIN_AZAMI)
    indir = indirme_dizini(gorev, ev)
    if gorev and indir and not re.search(r'["\\\n$`]', indir):
        yol = os.path.join(xdg, "user-dirs.dirs")
        try:
            with open(yol, encoding="utf-8", errors="replace") as f:
                satirlar = [s for s in f if not re.match(r"\s*XDG_DOWNLOAD_DIR=", s)]
        except OSError:
            satirlar = []
        satirlar.append(f'XDG_DOWNLOAD_DIR="{indir}"\n')
        with open(yol, "w", encoding="utf-8") as f:
            f.writelines(satirlar)
    kopya_mod.izinleri_daralt(xdg)
    return indir


def _indirme_prefleri_yaz(hedef: str, indir: str | None) -> None:
    """user.js'e indirme klasörü: browser.download.folderList=2 + browser.download.dir (XDG indirme klasörü)."""
    if not indir:
        return
    with open(os.path.join(hedef, "user.js"), "a", encoding="utf-8") as f:
        f.write('user_pref("browser.download.folderList", 2);\n'
                f'user_pref("browser.download.dir", {json.dumps(indir, ensure_ascii=False)});\n')


def _kimlik_sahibi(orijinal: Politika, saglayici: str):
    """→ f(host) True: host YALNIZ bu sağlayıcının ret girdileri yüzünden reddediliyor (izinle açılan kısım)."""
    acik = orijinal.kimlik_izni_uygula({saglayici})
    return lambda h, cerez=True: ((orijinal.cerez_reddedildi(h) and not acik.cerez_reddedildi(h)) if cerez else
                                  (orijinal.site_reddedildi(h) and not acik.site_reddedildi(h)))


def _kimlik_cerez_say(cookies_db: str, orijinal: Politika) -> dict:
    """Sağlayıcı başına, yalnız o sağlayıcının ret girdileri yüzünden süzülecek çerez satırı sayısı."""
    try:
        con = sqlite3.connect(cookies_db)
        try:
            satirlar = con.execute("SELECT host, COUNT(*) FROM moz_cookies GROUP BY host").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    from .politika import KIMLIK_ALANLARI
    reddedilen = [(h, n) for h, n in satirlar if h and orijinal.cerez_reddedildi(h)]  # önce tek geçiş (yüzlerce konak)
    sonuc = {}
    for s in KIMLIK_ALANLARI:
        acik = orijinal.kimlik_izni_uygula({s})
        sonuc[s] = sum(n for h, n in reddedilen if not acik.cerez_reddedildi(h))
    return sonuc


def _kimlik_ozet(kopya_cookies: str, hedef: str, orijinal: Politika, izin, mevcut: dict) -> dict:
    """{sağlayıcı: {izin, cerez, giris}}: izinliyse kopyaya GİREN çerez (oturum çerezleri dahil) + kayıtlı giriş;
    izinsizse kalıcı çerezlerden SÜZÜLEN sayısı (giris 0). Değer okunmaz; yalnız konak."""
    from .politika import KIMLIK_ALANLARI
    sonra = _kimlik_cerez_say(kopya_cookies, orijinal) if os.path.isfile(kopya_cookies) else {}
    girisler = []
    try:
        with open(os.path.join(hedef, "logins.json")) as f:
            girisler = [g for g in (json.load(f).get("logins") or []) if isinstance(g, dict)]
    except (OSError, ValueError, AttributeError):
        pass
    ozet = {}
    for s in KIMLIK_ALANLARI:
        if s in izin:
            f = _kimlik_sahibi(orijinal, s)
            giris = sum(1 for g in girisler
                        if any(k and f(k, cerez=False) for k in (_url_konak(g.get("hostname")),
                                                                 _url_konak(g.get("formSubmitURL")))))
            ozet[s] = {"izin": True, "cerez": sonra.get(s, 0), "giris": giris}
        else:
            ozet[s] = {"izin": False, "cerez": mevcut.get(s, 0), "giris": 0}
    return ozet


def kimlik_ozeti_metni(ozet: dict, gorev: bool = False) -> str:
    """'kimlik oturumları: Microsoft aktarıldı (5 çerez, 1 kayıtlı giriş); Google süzüldü (izin kapalı …)' ya da ''."""
    from .politika import KIMLIK_ADLARI
    parcalar = []
    for s, d in (ozet or {}).items():
        ad = KIMLIK_ADLARI.get(s, s)
        if gorev:
            if d.get("cerez"):
                parcalar.append(_("{ad} süzüldü (görev kipinde aktarılmaz)").format(ad=ad))
        elif d.get("izin"):
            parcalar.append(_("{ad} aktarıldı ({cerez} çerez, {giris} kayıtlı giriş)").format(
                ad=ad, cerez=d.get("cerez", 0), giris=d.get("giris", 0)))
        elif d.get("cerez"):
            parcalar.append(_("{ad} süzüldü ({cerez} çerez; izin kapalı: panel → Ayarlar → Hesap oturumları)").format(
                ad=ad, cerez=d["cerez"]))
    return _("kimlik oturumları: {ozet}").format(ozet="; ".join(parcalar)) if parcalar else ""


def kimlik_son_yolu() -> str:
    from .politika import kopya_dizini
    return os.path.join(kopya_dizini(), "kimlik-son.json")


def _kimlik_son_yaz(ozet: dict, gorev: bool) -> None:
    """Son Firefox kopyasının kimlik özeti (yalnız BİLGİ: doctor gösterir; karar için kullanılmaz)."""
    import time
    yol = kimlik_son_yolu()
    try:
        os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
        gecici = f"{yol}.{os.getpid()}"
        with open(gecici, "w") as f:
            json.dump({"zaman": time.time(), "gorev": bool(gorev), "ozet": ozet}, f)
        os.chmod(gecici, 0o600)
        os.replace(gecici, yol)
    except OSError:
        pass


def kimlik_son_oku() -> dict | None:
    try:
        with open(kimlik_son_yolu()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("ozet"), dict) else None
    except (OSError, ValueError):
        return None


def _cookies_suz(cookies_db: str, politika: Politika, gorev_siteleri, bilinen_konaklar=None) -> tuple[int, int, set]:
    """Kopya cookies.sqlite'ındaki ret alanlarını SİL; kalan çerez alanlarını (izinli) döndür.
    Döner: (kalan_çerez, silinen, izinli_alanlar). Değer okunmaz; yalnız host.
    bilinen_konaklar: see Politika.cerez_reddedildi (the cookie hosts of this database are always added)."""
    con = sqlite3.connect(cookies_db)
    try:
        hostlar = [r[0] for r in con.execute("SELECT DISTINCT host FROM moz_cookies")]
        bilinen = set(bilinen_konaklar or ()) | {_alan(h) for h in hostlar}
        silinecek = [h for h in hostlar if politika.cerez_reddedildi(h, bilinen)]
        for h in silinecek:
            con.execute("DELETE FROM moz_cookies WHERE host=?", (h,))
        con.commit()
        kalan = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
        izinli = {_alan(h) for h in hostlar
                  if h not in silinecek and politika.site_izinli(_alan(h), gorev_siteleri)}
        return kalan, len(silinecek), izinli
    finally:
        con.close()


def _kaynak_bitis(c: dict) -> float | None:
    """Source expiry of a sessionstore cookie in SECONDS (None = no expiry given). Firefox writes nsICookie.expiry:
    seconds in older releases, milliseconds in newer ones (values above 1e11 are taken as ms). A value that is not a
    number counts as already expired (0) so the cookie is skipped."""
    v = c.get("expiry")
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000 if v > 1e11 else v


def _oturum_cerezleri_ekle(recovery: str, cookies_db: str, politika: Politika, gorev_siteleri, gorev: bool = False,
                           bilinen_konaklar=None):
    """recovery.jsonlz4 kökündeki `cookies` dizisini kopya cookies.sqlite'ına ekle (ret hariç).
    Döner: (eklenen, eklenen_alanlar). Firefox oturum çerezi biçimi: {host,name,value,path,expiry?,...}.
    A cookie whose source `expiry` has passed is skipped; the written lifetime never exceeds the source expiry."""
    veri = _recovery_oku(recovery)
    cerezler = veri.get("cookies") or []
    if not cerezler:
        return 0, set()
    con = sqlite3.connect(cookies_db)
    eklenen = 0
    alanlar: set[str] = set()
    try:
        import time
        sutunlar = {r[1] for r in con.execute("PRAGMA table_info(moz_cookies)")}
        # Oturum çerezi kopyada kalıcı yazılır (kopya zaten oturumluk): bitiş = şimdi + 1 gün, birim mevcut satırlardan
        # (Firefox ≥ ~130 ms yazar; satır yoksa ms — saniye beklenen eski sürümde de yalnız uzun ömür demek). 0 yazmak
        # "süresi geçmiş" demekti: Firefox çerezi açılışta atıyordu (oturum girişleri aktarılmıyordu).
        (enbuyuk,) = con.execute("SELECT MAX(expiry) FROM moz_cookies").fetchone()
        ms = not enbuyuk or enbuyuk > 1e11
        simdi = time.time()
        bitis = int((simdi + 86400) * (1000 if ms else 1))
        mikro = int(simdi * 1e6)
        bilinen = set(bilinen_konaklar or ()) | {_alan(c.get("host", "")) for c in cerezler if isinstance(c, dict)}
        bilinen |= {_alan(r[0]) for r in con.execute("SELECT DISTINCT host FROM moz_cookies")}
        for c in cerezler:
            if not isinstance(c, dict):
                continue
            host = c.get("host", "")
            alan = _alan(host)
            if not alan or politika.cerez_reddedildi(host, bilinen) or not politika.site_izinli(alan, gorev_siteleri):
                continue
            kaynak_bitis = _kaynak_bitis(c)
            if kaynak_bitis is not None and kaynak_bitis <= simdi:
                continue  # expired in the source: must not come back to life in the copy
            c_bitis = bitis if kaynak_bitis is None else min(bitis, int(kaynak_bitis * (1000 if ms else 1)))
            if gorev and not gorev_izinli(politika, alan, gorev_siteleri):
                continue
            oa = oa_soneki(c.get("originAttributes", ""))
            if oa is None:  # çevrilemeyen bağlam (gizli pencere, bilinmeyen alan): yanlış kaba yazmaktansa atla
                continue
            ad, yol_ = c.get("name", ""), c.get("path", "/")
            try:
                # Aynı anahtarda (ad, konak, yol, bağlam) SÜRESİ GEÇMİŞ kalıcı satır varsa (Firefox süresi geçeni
                # cookies.sqlite'tan geç siler) canlı oturum çerezi onun yüzünden ATLANMASIN: bayat satır silinir.
                # Süresi geçmemiş kalıcı satır kalır (IGNORE): ikisi birden varsa canlı tarayıcıda hangisinin
                # geçerli olduğunu bilemeyiz, kalıcı olan güncel cookies.sqlite'tan gelir.
                con.execute("DELETE FROM moz_cookies WHERE name=? AND host=? AND path=? AND originAttributes=? "
                            "AND expiry < ?", (ad, host, yol_, oa, int(simdi * (1000 if ms else 1))))
                ek_sutun, ek_deger = "", ()
                if "isPartitionedAttributeSet" in sutunlar:
                    ek_sutun, ek_deger = ",isPartitionedAttributeSet", (int(bool(c.get("isPartitioned"))),)
                if "updateTime" in sutunlar:
                    ek_sutun, ek_deger = ek_sutun + ",updateTime", ek_deger + (mikro,)
                cur = con.execute(
                    "INSERT OR IGNORE INTO moz_cookies "
                    "(originAttributes,name,value,host,path,expiry,lastAccessed,creationTime,"
                    f"isSecure,isHttpOnly,sameSite,schemeMap{ek_sutun}) "
                    f"VALUES (?,?,?,?,?,?,?,?,?,?,?,?{',?' * len(ek_deger)})",
                    (oa, ad, c.get("value", ""), host, yol_,
                     c_bitis, mikro, mikro, int(bool(c.get("secure"))), int(bool(c.get("httponly"))),
                     int(c.get("sameSite", 0) or 0), int(c.get("schemeMap", 0) or 0), *ek_deger))
                if cur.rowcount > 0:  # IGNORE ile atlanan (zaten var) sayılmaz
                    eklenen += 1
                    alanlar.add(alan)
            except (sqlite3.Error, ValueError, TypeError):
                pass
        con.commit()
    finally:
        con.close()
    return eklenen, alanlar


_OA_BILINEN = {"userContextId", "privateBrowsingId", "firstPartyDomain", "geckoViewSessionContextId", "partitionKey",
               "inIsolatedMozBrowser", "appId"}


def _oa_kodla(deger: str) -> str:
    """Firefox URLParams::Serialize (application/x-www-form-urlencoded): harf/rakam ve *-._ aynen, boşluk +, gerisi %XX."""
    return "".join(chr(b) if (chr(b).isascii() and chr(b).isalnum()) or b in b"*-._" else ("+" if b == 0x20 else f"%{b:02X}")
                   for b in deger.encode("utf-8"))


def oa_soneki(oa) -> str | None:
    """sessionstore originAttributes (sözlük ya da sonek metni) → cookies.sqlite sütunu (Firefox OriginAttributes::
    CreateSuffix: '^userContextId=2&partitionKey=%28https%2Cexample.com%29', varsayılan bağlam ''). Gizli pencere,
    GeckoView bağlamı ya da bilinmeyen dolu alan → None (çerez atlanır)."""
    if isinstance(oa, str):
        return oa if oa == "" or oa.startswith("^") else None
    if not isinstance(oa, dict):
        return None
    if any(k not in _OA_BILINEN and v not in (None, "", 0, False) for k, v in oa.items()):
        return None
    if oa.get("privateBrowsingId") or oa.get("geckoViewSessionContextId") or oa.get("inIsolatedMozBrowser") or \
            oa.get("appId"):
        return None
    parcalar = []
    try:
        uc = int(oa.get("userContextId") or 0)
    except (TypeError, ValueError):
        return None
    if uc < 0:
        return None
    if uc:
        parcalar.append(f"userContextId={uc}")
    fpd, pk = oa.get("firstPartyDomain") or "", oa.get("partitionKey") or ""
    if not isinstance(fpd, str) or not isinstance(pk, str):
        return None
    if fpd:
        parcalar.append("firstPartyDomain=" + _oa_kodla(fpd.replace(":", "+")))
    if pk:
        parcalar.append("partitionKey=" + _oa_kodla(pk.replace("/", "+")))
    return ("^" + "&".join(parcalar)) if parcalar else ""


def _url_konak(url) -> str:
    """'https://www.isbank.com.tr:443/x' → 'www.isbank.com.tr'; konaksız (chrome://, boş) → ''."""
    from urllib.parse import urlsplit
    if not url or not isinstance(url, str):
        return ""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _giris_reddedildi(politika: Politika, *urller) -> bool:
    return any(k and politika.site_reddedildi(k) for k in (_url_konak(u) for u in urller))


def _girisleri_suz(hedef: str, politika: Politika) -> int:
    """Kopyadaki kayıtlı parolalardan ret listesindeki alanların kayıtlarını SİL (şifreli değerler okunmaz/
    değiştirilmez; kayıt bütünüyle çıkar). logins.json + logins-backup.json (hostname/formSubmitURL) ve Rust
    aynası logins.db (origin/formActionOrigin + aynı guid'ler) tutarlı süzülür. Okunamayan/bilinmeyen biçimdeki
    dosya kopyadan tümüyle silinir (sızıntı yerine eksik giriş). Döner: logins.json'dan silinen kayıt sayısı."""
    silinen_guid: set[str] = set()
    silinen = 0
    for ad in ("logins.json", "logins-backup.json"):
        yol = os.path.join(hedef, ad)
        if not os.path.isfile(yol):
            continue
        try:
            with open(yol, encoding="utf-8") as f:
                veri = json.load(f)
            girisler = veri.get("logins")
            if not isinstance(girisler, list):
                raise ValueError("logins yok")
        except (OSError, ValueError, AttributeError):
            _sil(yol)
            continue
        kalan = []
        for g in girisler:
            if isinstance(g, dict) and _giris_reddedildi(politika, g.get("hostname"), g.get("formSubmitURL")):
                if g.get("guid"):
                    silinen_guid.add(str(g["guid"]))
                if ad == "logins.json":
                    silinen += 1
                continue
            kalan.append(g)
        if len(kalan) != len(girisler):
            veri["logins"] = kalan
            for anahtar in ("dismissedBreachAlertsByLoginGUID",):
                if isinstance(veri.get(anahtar), dict):
                    veri[anahtar] = {k: v for k, v in veri[anahtar].items() if k not in silinen_guid}
            with open(yol, "w", encoding="utf-8") as f:
                json.dump(veri, f, separators=(",", ":"))
    db = os.path.join(hedef, "logins.db")
    if os.path.isfile(db):
        try:
            con = sqlite3.connect(db)
            try:
                tablolar = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                suzulen = 0
                for t in tablolar:
                    sutunlar = {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')}
                    if "origin" not in sutunlar:
                        continue
                    suzulen += 1
                    ek = ", formActionOrigin" if "formActionOrigin" in sutunlar else ", NULL"
                    gid = ", guid" if "guid" in sutunlar else ", NULL"
                    for rowid, origin, form, guid in con.execute(
                            f'SELECT rowid, origin{ek}{gid} FROM "{t}"').fetchall():
                        if (guid and str(guid) in silinen_guid) or _giris_reddedildi(politika, origin, form):
                            con.execute(f'DELETE FROM "{t}" WHERE rowid=?', (rowid,))
                con.commit()
            finally:
                con.close()
            if not suzulen:
                raise sqlite3.DatabaseError("bilinmeyen logins.db şeması")
        except sqlite3.Error:
            _sil(db)
    return silinen


def _izinleri_suz(perm_db: str) -> int:
    """Kopya permissions.sqlite'tan kamera/mikrofon/ekran/konum/bildirim (vb.) izinlerini sil. Döner: silinen."""
    if not os.path.isfile(perm_db):
        return 0
    silinen = 0
    try:
        con = sqlite3.connect(perm_db)
        try:
            tablolar = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            yer = ",".join("?" * len(_SILINEN_IZINLER))
            for t in ("moz_perms", "moz_hosts"):
                if t in tablolar:
                    silinen += con.execute(f"DELETE FROM {t} WHERE type IN ({yer})", _SILINEN_IZINLER).rowcount
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        _sil(perm_db)  # süzülemeyen izin DB'si kopyada kalmasın (Firefox boşunu yeniden üretir)
    return silinen


def _sil(yol: str) -> None:
    try:
        os.remove(yol)
    except OSError:
        pass


def _storage_kopyala(kaynak: str, hedef: str, izinli_alanlar: set, politika: Politika) -> int:
    """storage/default/<origin> klasörlerinden YALNIZ izinli alanlara ait olanları kopyala.
    Origin dizin adı 'https+++github.com' biçiminde; alan adı ortadan çözülür. Boyut sınırı uygulanır."""
    kaynak_sd = os.path.join(kaynak, "storage", "default")
    if not os.path.isdir(kaynak_sd):
        return 0
    yap = _origin_boyut_siniri()
    sayac = 0
    for origin in os.listdir(kaynak_sd):
        alan = _origin_alan(origin)
        if not alan or alan not in izinli_alanlar:
            continue
        if politika.site_reddedildi(alan):
            continue
        k = os.path.join(kaynak_sd, origin)
        if not os.path.isdir(k) or os.path.islink(k):
            continue
        h = os.path.join(hedef, "storage", "default", origin)
        n = kopya_mod.dizin_kopyala(k, h, disla={"cache"}, boyut_siniri=yap)
        if n:
            sayac += 1
    return sayac


def _origin_alan(origin: str) -> str:
    """'https+++github.com' / 'https+++api.github.com^partitionKey=...' → 'github.com'."""
    o = origin.split("^")[0]  # partition/userContext eki
    parcalar = o.split("+++")
    if len(parcalar) < 2:
        return ""
    konak = parcalar[1].split(":")[0]  # port ayıkla (https+++host+++443 gibi)
    return konak.lstrip(".").lower()


def _origin_boyut_siniri() -> int | None:
    from . import politika as pol
    try:
        mb = pol.yukle().get("genel", {}).get("origin_boyut_siniri_mb", 50)
        return int(mb) * 1024 * 1024 if mb else None
    except (ValueError, TypeError):
        return 50 * 1024 * 1024


# Profil grubu (Firefox "selectable profiles") tercihleri: kopyada KALIRSA Firefox kopyayı kullanıcının asıl profili
# sanıp onun profiles.ini/installs.ini varsayılan yolunu ve "Profile Groups/<id>.sqlite" listesini KOPYAYA çeviriyordu
# (gerçek olay: üç hayalet profil + silinmiş kopyayı gösteren varsayılan yol). Firefox yedekleme ayarları da
# (browser.backup.*): kopya, kullanıcının yedek klasörüne (~/Belgeler/Restore Firefox) KENDİ yedeğini yazıyordu
# (gerçek olay, 15 MB). Bu satırlar kopyaya ALINMAZ; user.js yedeklemeyi ayrıca kapatır.
_PROFIL_GRUBU_PREF = re.compile(r'user_pref\("(toolkit\.profiles\.|browser\.profiles\.|browser\.backup\.)')


def _user_js_yaz(hedef: str, kaynak: str, gorev: bool = False) -> None:
    """Kopyaya user.js yaz. Kaynaktaki prefs.js'i de alırız (ayarlar korunur) — profil grubu satırları HARİÇ —, üstüne
    user.js gelir."""
    try:
        with open(os.path.join(kaynak, "prefs.js"), encoding="utf-8", errors="replace") as f:
            satirlar = [s for s in f if not _PROFIL_GRUBU_PREF.match(s.strip())]
        with open(os.path.join(hedef, "prefs.js"), "w", encoding="utf-8") as f:
            f.writelines(satirlar)
    except OSError:
        pass
    with open(os.path.join(hedef, "user.js"), "w") as f:
        f.write(_USER_JS + (_GOREV_USER_JS if gorev else ""))
