"""Firefox profilinin tutarlı, tek yönlü anlık kopyası (docs/SESSIONS.md §3).

Kaynak = gerçek profil (tespit.firefox_profil_dizini, realpath; psd'nin *-backup/*-back-ovfs bayat kopyaları ASLA).
Kopyalanan: cookies.sqlite (tutarlı), key4.db, cert9.db, logins.json (+ logins.db [Rust aynası], logins-backup.json),
permissions.sqlite, containers.json, pkcs11.txt, yalnız İZİN VERİLEN sitelerin storage/default/<origin>,
uzantılar. KOPYALANMAZ: signedInUser.json, weave, lock/.parentlock, places*, sessionstore'un kendisi, telemetri.

Oturum çerezleri (yalnız recovery.jsonlz4'te) mozlz4 çözülüp kopyanın cookies.sqlite'ına eklenir (ret hariç).
Ret listesindeki alanların çerezi (alan çerezi ".google.com" ret listesindeki alt alana da gidiyorsa o da),
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
"""


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


# ------------------------------------------------------------------ ana kopya

def hazirla(politika: Politika, gorev_siteleri=None) -> dict:
    """Firefox profilini kopyala. Döner: {kopya_yolu, argv, kaynak, origin_sayisi, cerez_sayisi,
    oturum_cerez_eklendi, ret_silindi, durum}. Kaynak yazılmaz. 'durum'=hata açıklaması (None=tamam)."""
    kaynak = tespit.firefox_profil_dizini()
    if not kaynak or not os.path.isdir(kaynak):
        return {"durum": _("Firefox profili bulunamadı (profiles.ini)"), "kopya_yolu": None, "argv": []}

    hedef = kopya_mod.yeni_kopya_dizini("firefox")
    disla = set(politika.disla)
    bilgi = {"kopya_yolu": hedef, "kaynak": kaynak, "durum": None,
             "cerez_sayisi": 0, "oturum_cerez_eklendi": 0, "ret_silindi": 0, "origin_sayisi": 0,
             "giris_silindi": 0, "izin_silindi": 0}

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
    if os.path.isfile(kopya_cookies):
        bilgi["cerez_sayisi"], bilgi["ret_silindi"], izinli_alanlar = _cookies_suz(
            kopya_cookies, politika, gorev_siteleri)

    # 5) oturum çerezleri (recovery.jsonlz4 → kopya cookies.sqlite)
    rec = os.path.join(kaynak, "sessionstore-backups", "recovery.jsonlz4")
    if os.path.isfile(rec) and os.path.isfile(kopya_cookies):
        eklendi, ek_alanlar = _oturum_cerezleri_ekle(rec, kopya_cookies, politika, gorev_siteleri)
        bilgi["oturum_cerez_eklendi"] = eklendi
        izinli_alanlar |= ek_alanlar

    # 6) yalnız izin verilen origin'lerin storage/default/<origin> klasörleri
    # Görev sitesi verilmediyse site deposu kopyalanmaz: ~575 alan × yerel depo yüzlerce MB olabiliyordu;
    # çoğu sitede oturum çerezle açılır. Site verilirse (ac --site github.com) yalnız onların deposu gelir.
    bilgi["origin_sayisi"] = (_storage_kopyala(kaynak, hedef, izinli_alanlar, politika) if gorev_siteleri else 0)

    # 7) user.js
    _user_js_yaz(hedef, kaynak)

    bilgi["argv"] = ["firefox", "--profile", hedef, "--no-remote", "--new-instance"]
    # Kopya Firefox kullanıcının profil kökünü (~/.config/mozilla/firefox: profiles.ini, installs.ini, Profile Groups)
    # HİÇ görmesin: kendi boş yapılandırma kökü + eski tip profil yönetimi (kuruluma özel varsayılan yazmaz).
    xdg = os.path.join(hedef, ".xdg-config")
    os.makedirs(xdg, mode=0o700, exist_ok=True)
    bilgi["env_ek"] = {"XDG_CONFIG_HOME": xdg, "MOZ_LEGACY_PROFILES": "1"}
    return bilgi


def _cookies_suz(cookies_db: str, politika: Politika, gorev_siteleri) -> tuple[int, int, set]:
    """Kopya cookies.sqlite'ındaki ret alanlarını SİL; kalan çerez alanlarını (izinli) döndür.
    Döner: (kalan_çerez, silinen, izinli_alanlar). Değer okunmaz; yalnız host."""
    con = sqlite3.connect(cookies_db)
    try:
        hostlar = [r[0] for r in con.execute("SELECT DISTINCT host FROM moz_cookies")]
        silinecek = [h for h in hostlar if politika.cerez_reddedildi(h)]
        for h in silinecek:
            con.execute("DELETE FROM moz_cookies WHERE host=?", (h,))
        con.commit()
        kalan = con.execute("SELECT COUNT(*) FROM moz_cookies").fetchone()[0]
        izinli = {_alan(h) for h in hostlar
                  if h not in silinecek and politika.site_izinli(_alan(h), gorev_siteleri)}
        return kalan, len(silinecek), izinli
    finally:
        con.close()


def _oturum_cerezleri_ekle(recovery: str, cookies_db: str, politika: Politika, gorev_siteleri):
    """recovery.jsonlz4 kökündeki `cookies` dizisini kopya cookies.sqlite'ına ekle (ret hariç).
    Döner: (eklenen, eklenen_alanlar). Firefox oturum çerezi biçimi: {host,name,value,path,...}."""
    ham = mozlz4_coz(recovery)
    if ham is None:
        return 0, set()
    try:
        veri = json.loads(ham)
    except (ValueError, UnicodeDecodeError):
        return 0, set()
    cerezler = veri.get("cookies") or []
    if not cerezler:
        return 0, set()
    con = sqlite3.connect(cookies_db)
    eklenen = 0
    alanlar: set[str] = set()
    try:
        for c in cerezler:
            host = c.get("host", "")
            alan = _alan(host)
            if not alan or politika.cerez_reddedildi(host) or not politika.site_izinli(alan, gorev_siteleri):
                continue
            oa = c.get("originAttributes", "")
            if isinstance(oa, dict):
                oa = ""  # basit: varsayılan bağlam
            try:
                cur = con.execute(
                    "INSERT OR IGNORE INTO moz_cookies "
                    "(originAttributes,name,value,host,path,expiry,lastAccessed,creationTime,"
                    "isSecure,isHttpOnly,sameSite,schemeMap) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (oa, c.get("name", ""), c.get("value", ""), host, c.get("path", "/"),
                     0, 0, 0, int(bool(c.get("secure"))), int(bool(c.get("httponly"))),
                     int(c.get("sameSite", 0) or 0), int(c.get("schemeMap", 0) or 0)))
                if cur.rowcount > 0:  # IGNORE ile atlanan (zaten var) sayılmaz
                    eklenen += 1
                    alanlar.add(alan)
            except sqlite3.Error:
                pass
        con.commit()
    finally:
        con.close()
    return eklenen, alanlar


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


def _user_js_yaz(hedef: str, kaynak: str) -> None:
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
        f.write(_USER_JS)
