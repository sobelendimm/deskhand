"""Web okuma testleri için: yerel test sayfası sunucusu + arka plan masaüstünde YALITIK Firefox + kullanıcı profili bekçisi.

Firefox YALNIZ arka plan (Xvfb) masaüstünde, YENİ BOŞ GEÇİCİ profille açılır (kullanıcının profilinden hiçbir şey
kopyalanmaz). Geçmişte zarar veren tuzaklara karşı (docs/SESSIONS.md, deskhand/oturum/firefox.py):
- XDG_CONFIG_HOME geçici klasör + MOZ_LEGACY_PROFILES=1 + `--profile <geçici> --no-remote --new-instance`: Firefox
  kullanıcının profil kökünü (~/.config/mozilla/firefox: profiles.ini, installs.ini, Profile Groups/) görmez/yazmaz;
- user.js: oturum kopyasının tercihleri (profil grupları + zamanlanmış yedekleme KAPALI) + test tercihleri;
- kapatma: yalnız kendi başlattığımız süreç (önce pencereyi kibarca kapat, sonra SIGTERM, en son SIGKILL).
`ProfilBekcisi`: profiles.ini / installs.ini sha1 + profil kökü ve Profile Groups/ dizin adları; her koşu öncesi ve
sonrası karşılaştırılır (fark = HEMEN dur, hiçbir şey düzeltilmez).
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import socket
import subprocess
import tempfile
import threading
import time

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ornek", "web")
FF_KOK = os.path.expanduser("~/.config/mozilla/firefox")

# Test profiline ek tercihler (oturum kopyasının _USER_JS'i üstüne): ilk açılış/yeni sekme/çeviri çubukları
TEST_PREFS = {
    "browser.newtab.preload": False,
    "browser.newtabpage.enabled": False,
    "browser.startup.upgradeDialog.enabled": False,
    "browser.messaging-system.whatsNewPanel.enabled": False,
    "browser.uitour.enabled": False,
    "trailhead.firstrun.didSeeAboutWelcome": True,
    "termsofuse.bypassNotification": True,
    "termsofuse.acceptedVersion": 999,
    "browser.shell.didSkipDefaultBrowserCheckOnFirstRun": True,
    "toolkit.startup.max_resumed_crashes": -1,
    "app.normandy.enabled": False,
    "browser.discovery.enabled": False,
    "extensions.update.enabled": False,
    "extensions.pocket.enabled": False,
    "browser.warnOnQuit": False,
    "browser.tabs.warnOnClose": False,
    "browser.sessionstore.warnOnQuit": False,
    "browser.translations.enable": False,
    "browser.translations.automaticallyPopup": False,
    "signon.rememberSignons": False,
    "browser.toolbars.bookmarks.visibility": "never",
    "sidebar.revamp": False,
    "sidebar.verticalTabs": False,
    "network.dns.disablePrefetch": True,
    "network.prefetch-next": False,
    "browser.safebrowsing.malware.enabled": False,
    "browser.safebrowsing.phishing.enabled": False,
    "browser.safebrowsing.downloads.enabled": False,
    "browser.search.update": False,
    "services.settings.server": "http://127.0.0.1:9/",  # uzak ayar indirmesi yok (dış ağ isteği olmasın)
    "network.captive-portal-service.enabled": False,
    "network.connectivity-service.enabled": False,
    "browser.region.network.url": "",
    "browser.contentblocking.report.lockwise.enabled": False,
    "dom.push.connection.enabled": False,
    "network.trr.mode": 5,
    "extensions.getAddons.cache.enabled": False,
    "extensions.systemAddon.update.enabled": False,
    "media.gmp-manager.updateEnabled": False,
    "geo.provider.network.url": "",
    "browser.topsites.contile.enabled": False,
    "app.update.disabledForTesting": True,
}


# ---------------------------------------------------------------- test sayfalarında beklenen ögeler (rol, ad)
FORM = [("entry", "Ad Soyad"), ("entry", "E-posta adresi"), ("password text", "Parola"), ("entry", "Ürün ara"),
        ("entry", "Posta kodu"), ("entry", "Sipariş notu"), ("check box", "Bülten aboneliği"),
        ("check box", "Koşulları kabul ediyorum"), ("radio button", "Kargo ile"), ("radio button", "Mağazadan teslim"),
        ("combo box", "Şehir"), ("button", "Ayarlar"), ("button", "Yazdır"), ("button", "Kapat"),
        ("button", "Kaydet"), ("button", "Gönder"), ("link", "Yardım"), ("button", "Sayfa sonu düğmesi")]
FORM_GIZLI = ("Gizli düğme", "Saklı düğme", "Gizli bağlantı")
BILESEN = [("page tab", "Genel"), ("page tab", "Ayrıntılar"), ("page tab", "Geçmiş"), ("button", "Genel ayarı"),
           ("button", "Düzen")] + [(r, f"Çerçeve {n} {a}") for n in (1, 2)
                                   for r, a in (("button", "düğmesi"), ("entry", "alanı"), ("link", "bağlantısı"))]
SONRADAN = [("button", "Sonradan eklenen düğme"), ("link", "Yeni bağlantı")]
MENU = [("menu item", "Kopyala"), ("menu item", "Yapıştır"), ("menu item", "Tümünü seç")]
SATIN = [("spin button", "Adet"), ("button", "Sepete ekle"), ("button", "Satın al"), ("button", "Öde"),
         ("button", "Siparişi onayla"), ("button", "Favorilere ekle"), ("link", "İade koşulları")]
DATA_AD = {"Düzen": "Düzen menüsü"}  # sayfanın tıklama günlüğündeki adı farklı olanlar


# ---------------------------------------------------------------- kullanıcı profili bekçisi

def _sha1(yol: str) -> str | None:
    try:
        with open(yol, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def profil_ozeti() -> dict:
    """Kullanıcının GERÇEK Firefox profil kökünün özeti (yalnız okuma)."""
    def adlar(d):
        try:
            return sorted(os.listdir(d))
        except OSError:
            return None
    return {"profiles.ini": _sha1(os.path.join(FF_KOK, "profiles.ini")),
            "installs.ini": _sha1(os.path.join(FF_KOK, "installs.ini")),
            "dizin": adlar(FF_KOK), "Profile Groups": adlar(os.path.join(FF_KOK, "Profile Groups")),
            "~/.mozilla var": os.path.exists(os.path.expanduser("~/.mozilla"))}


class ProfilBekcisi:
    def __init__(self):
        self.ilk = profil_ozeti()

    def fark(self) -> dict:
        simdi = profil_ozeti()
        return {k: (self.ilk[k], simdi[k]) for k in self.ilk if self.ilk[k] != simdi[k]}

    def satirlar(self) -> list[str]:
        s = profil_ozeti()
        return [f"profiles.ini sha1 önce {self.ilk['profiles.ini']} sonra {s['profiles.ini']}",
                f"installs.ini sha1 önce {self.ilk['installs.ini']} sonra {s['installs.ini']}",
                f"profil kökü ({len(self.ilk['dizin'] or [])} ad) {'AYNI' if self.ilk['dizin'] == s['dizin'] else 'FARKLI'}",
                f"Profile Groups/ {'AYNI' if self.ilk['Profile Groups'] == s['Profile Groups'] else 'FARKLI'}",
                f"~/.mozilla var mı: önce {self.ilk['~/.mozilla var']} sonra {s['~/.mozilla var']}"]


# ---------------------------------------------------------------- yerel sayfa sunucusu (dış ağ yok)

class _Isleyici(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Sunucu:
    def __init__(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Isleyici, directory=WEB))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def url(self, sayfa: str) -> str:
        return f"http://127.0.0.1:{self.port}/{sayfa}"

    def kapat(self):
        self.srv.shutdown()
        self.srv.server_close()


# ---------------------------------------------------------------- Firefox (arka plan masaüstünde, geçici profil)

def ata_pidler(pid) -> list[int]:
    """pid ve ataları. Arka plan uygulaması bwrap ad alanında başlar: Popen'in döndürdüğü PID bwrap'in kendisidir,
    pencerenin sahibi (X-Resource / getwindowpid) onun TORUNUdur; bu yüzden `au.pid(k) == p.pid` yerine
    `p.pid in ata_pidler(au.pid(k))` denetlenir."""
    sonuc = []
    while pid and pid > 1 and len(sonuc) < 16:
        sonuc.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return sonuc


def _pref(ad, deger) -> str:
    return f"user_pref({json.dumps(ad)}, {json.dumps(deger)});\n"


class Firefox:
    """Arka plan masaüstünde geçici profilli Firefox. marionette=True: uzaktan denetim kapısı (YALNIZ ölçüm için)."""

    def __init__(self, au, kok: str, url: str, marionette: bool = False, ek_prefs: dict | None = None,
                 erisilebilirlik: bool = True, sure: float = 60.0):
        from deskhand.oturum.firefox import _USER_JS
        self.au = au
        self.profil = tempfile.mkdtemp(prefix="deskhand-ff-", dir=kok)
        self.xdg = tempfile.mkdtemp(prefix="xdg-", dir=kok)
        os.chmod(self.profil, 0o700)
        with open(os.path.join(self.profil, "user.js"), "w") as f:
            f.write(_USER_JS)
            for a, v in {**TEST_PREFS, **({"marionette.port": 0} if marionette else {}), **(ek_prefs or {})}.items():
                f.write(_pref(a, v))
        env = {"XDG_CONFIG_HOME": self.xdg, "XDG_CACHE_HOME": os.path.join(self.xdg, "onbellek"),
               "XDG_DATA_HOME": os.path.join(self.xdg, "veri"), "XDG_STATE_HOME": os.path.join(self.xdg, "durum"),
               "MOZ_LEGACY_PROFILES": "1", "MOZ_CRASHREPORTER_DISABLE": "1", "MOZ_CRASHREPORTER": "0"}
        if erisilebilirlik:
            env["GNOME_ACCESSIBILITY"] = "1"
        argv = ["firefox", "--profile", self.profil, "--no-remote", "--new-instance"]
        if marionette:
            argv.append("--marionette")
        self.log = open(os.path.join(kok, f"firefox-{os.path.basename(self.profil)}.log"), "w")
        self.p = au.baslat(argv + [url], env=env, cikti=self.log)
        self.k = None
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis and self.k is None:
            for w, b, _ in au.pencereler("Mozilla Firefox"):
                if self.p.pid in ata_pidler(au.pid(w)):
                    self.k = w
            if self.p.poll() is not None:
                break
            time.sleep(0.1)
        if self.k is None:
            self.kapat()
            raise RuntimeError(f"Firefox penceresi açılmadı (çıkış {self.p.poll()}, günlük {self.log.name})")

    def baslik(self) -> str:
        return self.au.baslik(self.k)

    def marionette_kapisi(self, sure: float = 30.0) -> int | None:
        yol = os.path.join(self.profil, "MarionetteActivePort")
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            try:
                with open(yol) as f:
                    return int(f.read().strip())
            except (OSError, ValueError):
                time.sleep(0.1)
        return None

    def kapat(self) -> None:
        """Yalnız KENDİ sürecimiz: pencereyi kapat → SIGTERM → SIGKILL."""
        if self.p.poll() is None and self.k:
            try:
                self.au.kapat(self.k)
                self.p.wait(8)
            except Exception:  # noqa: BLE001
                pass
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(8)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait(5)
        self.log.close()


# ---------------------------------------------------------------- en küçük Marionette istemcisi (yalnız ölçüm)

class Marionette:
    """Marionette: TCP üzerinde 'uzunluk:JSON' çerçeveleri. [0, no, komut, parametre] → [1, no, hata, sonuç]."""

    def __init__(self, port: int, konak: str = "127.0.0.1", sure: float = 20.0):
        self.s = socket.create_connection((konak, port), timeout=sure)
        self.no = 0
        self.karsilama = self._oku()

    def _oku(self):
        bas = b""
        while b":" not in bas:
            c = self.s.recv(1)
            if not c:
                raise ConnectionError("bağlantı kapandı")
            bas += c
        n_, kalan = bas.split(b":", 1)
        n = int(n_)
        veri = kalan
        while len(veri) < n:
            c = self.s.recv(n - len(veri))
            if not c:
                raise ConnectionError("bağlantı kapandı")
            veri += c
        return json.loads(veri)

    def komut(self, ad: str, param: dict | None = None):
        self.no += 1
        v = json.dumps([0, self.no, ad, param or {}]).encode()
        self.s.sendall(str(len(v)).encode() + b":" + v)
        while True:
            y = self._oku()
            if isinstance(y, list) and y[0] == 1 and y[1] == self.no:
                if y[2]:
                    raise RuntimeError(f"{ad}: {y[2].get('error')}: {y[2].get('message', '')[:200]}")
                return y[3]

    def oturum(self):
        return self.komut("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}})

    def js(self, betik: str, *args):
        return self.komut("WebDriver:ExecuteScript", {"script": betik, "args": list(args)}).get("value")

    def kapat(self):
        try:
            self.komut("WebDriver:DeleteSession")
        except Exception:  # noqa: BLE001
            pass
        self.s.close()


# ---------------------------------------------------------------- gerçek tıklama + sayfanın kendi günlüğü

class Tiklayici:
    """Ögenin bildirilen merkezine arka plan masaüstünde GERÇEK tıklama (XTEST); sayfa (ortak.js) fare basışını
    "TIK <ad> #<sıra>" olarak başlığa yazar → hangi ögeye düştüğü başlıktan okunur."""

    def __init__(self, au, k):
        self.au, self.k = au, k
        self.g = au.girdi("web-test")
        self.gonderilen = []  # (ekran x, ekran y): gerçek fare bu noktalara gitmemeli

    def _sayac(self):
        import re
        m = re.match(r"TIK (.+) #(\d+)", self.au.baslik(self.k) or "")
        return (m.group(1), int(m.group(2))) if m else (None, 0)

    def tikla(self, x, y, sure: float = 3.0, tus: str | None = None):
        """Pencere pikselinde (x, y) tıkla → başlığa yazılan öge adı (None: hiçbir ögeye düşmedi)."""
        X, Y = self.au.geometri(self.k)[:2]
        W, H = self.au.ekran_alani()[2:]
        _, n0 = self._sayac()
        self.gonderilen.append((int(X + x), int(Y + y)))
        self.g.gonder(self.k, None, f"mouseto {(X + x + 0.5) / W:.6f} {(Y + y + 0.5) / H:.6f}", "click left")
        bitis = time.monotonic() + sure
        ad = None
        while time.monotonic() < bitis:
            a, n = self._sayac()
            if n > n0:
                ad = a
                break
            time.sleep(0.02)
        if tus:
            self.g.gonder(self.k, None, f"key {tus}")
        return ad

    def tus(self, *tuslar):
        self.g.gonder(self.k, None, *[f"key {t}" for t in tuslar])

    def kapat(self):
        self.g.kapat()
