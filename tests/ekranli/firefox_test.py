"""Ekranlı tarayıcı testleri için AYRI Firefox örneği. Kullanıcının Firefox'una/profiline ASLA dokunmaz:

- Geçici profil (_yalitim geçici klasörü altında, `deskhand-ff-` önekli); user.js ile ilk açılış sayfaları,
  varsayılan tarayıcı sorusu, oturum geri yükleme, telemetri, çeviri çubuğu, kapatma onayı KAPALI.
- `firefox --new-instance --no-remote --profile <geçici> <url>`: kullanıcının çalışan Firefox'una bağlanmaz.
- Pencere bulma: başlık deseni + BU örneğin süreç ağacı (kdotool getwindowpid). Kullanıcının aynı başlıklı
  penceresi seçilmez.
- Kapatma: yalnız kendi PID'i (SIGTERM; 15 sn içinde kapanmazsa yalnız kendi ağacına SIGKILL). Kullanıcının
  Firefox'u açık kalır; "Çıkmayı onayla" gibi diyaloglar yalnız bu örnekte (zaten kapalı) olurdu.
- Profil kapanınca silinir.
"""
import os
import shutil
import signal
import subprocess
import tempfile
import time

import ortak

# Yalnız bu test profilinde geçerli ayarlar (user.js). Bilinmeyen bir anahtar Firefox'ta zararsızdır.
USER_JS = {
    # ilk açılış / karşılama / yenilikler sayfaları
    "browser.aboutwelcome.enabled": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "",
    "startup.homepage_welcome_url.additional": "",
    "startup.homepage_override_url": "",
    "browser.startup.firstrunSkipsHomepage": True,
    "browser.startup.upgradeDialog.enabled": False,
    "browser.messaging-system.whatsNewPanel.enabled": False,
    "browser.uitour.enabled": False,
    "trailhead.firstrun.didSeeAboutWelcome": True,
    "termsofuse.bypassNotification": True,
    "termsofuse.acceptedVersion": 999,
    "browser.startup.page": 0,
    "browser.newtabpage.enabled": False,
    "browser.newtab.preload": False,
    # varsayılan tarayıcı sorusu
    "browser.shell.checkDefaultBrowser": False,
    "browser.shell.didSkipDefaultBrowserCheckOnFirstRun": True,
    # oturum geri yükleme / çökme sonrası geri yükleme
    "browser.sessionstore.resume_from_crash": False,
    "browser.sessionstore.max_resumed_crashes": 0,
    "browser.sessionstore.resume_session_once": False,
    "toolkit.startup.max_resumed_crashes": -1,
    # telemetri / veri gönderimi / çalışmalar
    "datareporting.policy.dataSubmissionEnabled": False,
    "datareporting.policy.firstRunURL": "",
    "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
    "datareporting.healthreport.uploadEnabled": False,
    "toolkit.telemetry.enabled": False,
    "toolkit.telemetry.unified": False,
    "toolkit.telemetry.archive.enabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "app.shield.optoutstudies.enabled": False,
    "app.normandy.enabled": False,
    "browser.discovery.enabled": False,
    "browser.crashReports.unsubmittedCheck.autoSubmit2": False,
    # güncelleme / eklenti güncellemesi (test sırasında ağ ve açılır pencere olmasın)
    "app.update.auto": False,
    "extensions.update.enabled": False,
    "extensions.pocket.enabled": False,
    # kapatma onayları (SIGTERM ile kapatılır; yine de)
    "browser.warnOnQuit": False,
    "browser.tabs.warnOnClose": False,
    "browser.tabs.warnOnCloseOtherTabs": False,
    "browser.sessionstore.warnOnQuit": False,
    # sayfayı kaplayan çubuklar/paneller (OCR koordinatları sabit kalsın)
    "browser.translations.enable": False,
    "browser.translations.automaticallyPopup": False,
    "signon.rememberSignons": False,
    "browser.toolbars.bookmarks.visibility": "never",
    "sidebar.revamp": False,
    "sidebar.verticalTabs": False,
    "browser.download.panel.shown": True,
    "media.autoplay.default": 5,  # sesli/sessiz otomatik oynatma yok (MPRIS oynatıcısı doğmasın)
}
PROFIL_ONEK = "deskhand-ff-"


def _js_deger(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def user_js_metni(ayarlar=None):
    ayarlar = USER_JS if ayarlar is None else ayarlar
    return "".join(f'user_pref("{k}", {_js_deger(v)});\n' for k, v in ayarlar.items())


def profil_guvenli_mi(yol, taban=None):
    """Profil yolu bu testin geçici klasöründe mi ve bizim önekimizle mi? (kullanıcı profili ASLA)."""
    taban = os.path.realpath(taban or ortak._yalitim.GECICI)
    gercek = os.path.realpath(yol)
    return (gercek.startswith(taban + os.sep) and os.path.basename(gercek).startswith(PROFIL_ONEK)
            and ".mozilla" not in gercek.split(os.sep))


def profil_olustur(taban=None):
    taban = taban or ortak._yalitim.GECICI
    yol = tempfile.mkdtemp(prefix=PROFIL_ONEK, dir=taban)
    if not profil_guvenli_mi(yol, taban):
        raise RuntimeError(f"güvensiz profil yolu: {yol}")
    with open(os.path.join(yol, "user.js"), "w") as f:
        f.write(user_js_metni())
    return yol


def argv_olustur(profil, url):
    return ["firefox", "--new-instance", "--no-remote", "--profile", profil, url]


class TestFirefox:
    """Kendi profiliyle ayrı Firefox örneği. Kullanım:
        ff = TestFirefox(url, "ekran-test web"); K = ff.ac(); ...; ff.kapat()"""

    def __init__(self, url, desen, boyut=(1400, 1000), konum=(300, 150)):
        self.url, self.desen, self.boyut, self.konum = url, desen, boyut, konum
        self.profil = None
        self.p = None
        self.pidler = set()  # bu örneğin bilinen tüm süreçleri (kapatırken torunlar için)
        self.K = None

    def ac(self, sure=40):
        self.profil = profil_olustur()
        env = dict(os.environ, MOZ_CRASHREPORTER_DISABLE="1")
        self.p = subprocess.Popen(argv_olustur(self.profil, self.url), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                  start_new_session=True)
        bitis = time.monotonic() + sure
        while time.monotonic() < bitis:
            if self.p.poll() is not None:
                return None  # firefox hemen çıktı (ör. profil kilitli)
            self.pidler |= ortak.soy_pidleri(self.p.pid)
            k = ortak.pencere_bekle(self.desen, sure=0.5, kok_pid=self.p.pid)
            if k:
                self.K = k
                if self.boyut:
                    ortak.kd("windowsize", k, str(self.boyut[0]), str(self.boyut[1]))
                if self.konum:
                    ortak.kd("windowmove", k, str(self.konum[0]), str(self.konum[1]))
                time.sleep(0.8)
                return k
        return None

    def bizim_pencereler(self):
        """Bu örneğin şu an açık pencereleri (tüm pencereler taranır, pid ile süzülür)."""
        if self.p is not None and self.p.poll() is None:
            self.pidler |= ortak.soy_pidleri(self.p.pid)
        return [k for k in ortak.sec().kimlikler() if ortak.bizim_mi(ortak.pid(k), self.pidler)]

    def kapat(self):
        """Yalnız kendi süreçleri: SIGTERM ana süreç → bekle → kalan kendi süreçlerine SIGKILL. Profil silinir."""
        notlar = []
        if self.p is not None:
            if self.p.poll() is None:
                self.pidler |= ortak.soy_pidleri(self.p.pid)
                try:
                    os.kill(self.p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.p.wait(timeout=15)
                    notlar.append("SIGTERM ile kapandı")
                except subprocess.TimeoutExpired:
                    notlar.append("15 sn'de kapanmadı → SIGKILL (yalnız kendi süreçleri)")
                    for p in sorted(self.pidler):
                        try:
                            os.kill(p, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                    try:
                        self.p.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        notlar.append("ana süreç hâlâ yaşıyor!")
            else:
                notlar.append(f"zaten kapalıydı (kod {self.p.returncode})")
            # içerik süreçleri ana süreçle kapanır; kalan olursa (yalnız kendi ağacımız) bekle
            for _ in range(20):
                kalan = [p for p in self.pidler if os.path.exists(f"/proc/{p}")]
                if not kalan:
                    break
                time.sleep(0.25)
        if self.profil and profil_guvenli_mi(self.profil):
            shutil.rmtree(self.profil, ignore_errors=True)
            notlar.append("geçici profil silindi" if not os.path.exists(self.profil) else "profil SİLİNEMEDİ")
        return "; ".join(notlar)


def kullanici_firefox_pencereleri(bizim_pidler=()):
    """Kullanıcının (bu testin olmayan) Firefox pencereleri: kimlik kümesi. Test başı/sonu karşılaştırılır."""
    sonuc = set()
    for k in ortak.sec().kimlikler():
        try:
            if "firefox" not in (ortak.sinif(k) or "").lower():
                continue
        except Exception:  # noqa: BLE001 - kapanan pencere
            continue
        if not ortak.bizim_mi(ortak.pid(k), set(bizim_pidler)):
            sonuc.add(k)
    return sonuc
