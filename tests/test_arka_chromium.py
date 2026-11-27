"""Arka planda Chromium ailesi çökmesi (crashpad `--database is required`, çıkış 133) regresyon testi.

Kök neden: ~/.config/chromium, profile-sync-daemon'da /run/user/UID/psd/… altına giden sembolik bağdır; ad alanında
/run/user/UID BOŞ tmpfs olduğundan bağ boşta asılı kalır → varsayılan yapılandırma dizini yazılamaz → crashpad veritabanı
yolu boş. Düzeltme (arka_ortak.sir_bos_hedefler + ev_baglari): sembolik bağ hedefi ad alanında boş /run/user/UID ya da
/tmp altındaysa bwrap `--dir` ile ad alanına ÖZEL, boş, yazılabilir dizin açılır (gerçek psd verisi görünmez; yalıtım
aynı; XDG_CONFIG_HOME'a DOKUNULMAZ: user-dirs.dirs/kdeglobals/gtk/mimeapps okunur, indirmeler gerçek klasöre).
/run/user/UID tmpfs'i `--size` ile sınırlı (RUN_USER_BOYUT).

A) birim (ekransız): `--dir` argümanı, ad alanından GERÇEK psd dizini GÖRÜNMEZ (içerik + yazılanlar ana makineye
   sızmaz), boyut sınırı, /tmp hedefi, ev içi hedef/gerçek dizin eski yoldan, chromium_ortami KALDIRILDI.
B) GÖRÜNMEZ masaüstünde (DESKHAND_ARKA_TUR=kwin|xvfb) gerçek Chromium: (1) ham başlatma, (2) api.uygulama_ac,
   (3) oturum kopyası yolu, (4) SAHTE ev dizini (user-dirs.dirs + psd benzeri sembolik bağ): Chromium ayakta (133
   değil) ve yerel http sunucusundan inen dosya XDG indirme klasörüne (sahte ev) düşer; gerçek ~/İndirilenler kirlenmez.
Kullanıcının tarayıcı profillerine dokunulmaz; kullanıcının ekranına hiçbir pencere açılmaz.

Çalıştır:  python3 tests/test_arka_chromium.py"""
import atexit
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import api, arka_ortak, masaustu
from deskhand.arka_uc import sec
from deskhand.oturum import chromium, kopya

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


# ---------------------------------------------------------------- A) birim
UID = os.getuid()
kontrol("birim: chromium_ortami KALDIRILDI (XDG_CONFIG_HOME artık ezilmez)", not hasattr(arka_ortak, "chromium_ortami"))
kok = tempfile.mkdtemp(prefix="deskhand-chr-birim-", dir=_yalitim.GECICI)
EV = os.path.join(kok, "ev")
os.makedirs(os.path.join(EV, ".config"))
os.makedirs(os.path.join(EV, "Indirilenler"))
RT_HEDEF = tempfile.mkdtemp(prefix="deskhand-test-psd-", dir=f"/run/user/{UID}")      # psd benzeri (gerçek psd DEĞİL)
TMP_HEDEF = tempfile.mkdtemp(prefix="deskhand-test-psd-", dir="/tmp")
atexit.register(shutil.rmtree, RT_HEDEF, True)
atexit.register(shutil.rmtree, TMP_HEDEF, True)
for h, m in ((RT_HEDEF, "GIZLI-PSD-RT"), (TMP_HEDEF, "GIZLI-PSD-TMP")):
    with open(os.path.join(h, "Cookies"), "w") as f:
        f.write(m)
os.symlink(RT_HEDEF, os.path.join(EV, ".config/chromium"))
os.symlink(TMP_HEDEF, os.path.join(EV, ".config/vivaldi-snapshot"))
# ev içinde bir hedef (eski yol: örtülür, --dir değil) ve sembolik bağ olmayan gerçek profil dizini
os.makedirs(os.path.join(EV, ".psd-brave/x"))
os.symlink("../.psd-brave", os.path.join(EV, ".config/BraveSoftware"))
os.makedirs(os.path.join(EV, ".config/microsoft-edge"))
RT = os.path.join(EV, "rt")
ORT = {"HOME": EV, "PATH": "/usr/bin"}


def ad_alani(komut, ek_argv=None):
    return subprocess.run(arka_ortak.korumali_argv(["/usr/bin/sh", "-c", komut], RT, [], ev=EV),
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, env=ORT)


bos = arka_ortak.sir_bos_hedefler(EV)
kontrol("birim: sir_bos_hedefler = /run/user/UID ve /tmp altındaki sembolik bağ hedefleri (ev içi/gerçek dizin değil)",
        bos == sorted([RT_HEDEF, TMP_HEDEF]), str(bos))
yollar = arka_ortak.sir_yollari(EV)
kontrol("birim: sir_yollari bu hedefleri İÇERMEZ; ev içi hedef (.psd-brave) ve gerçek dizin (edge) örtülür",
        RT_HEDEF not in yollar and TMP_HEDEF not in yollar and os.path.join(EV, ".psd-brave") in yollar
        and os.path.join(EV, ".config/microsoft-edge") in yollar, str(yollar))
a_, bilgi = arka_ortak.ev_baglari(EV)
kontrol("birim: ev_baglari her hedef için `--perms 0700 --dir <gerçek yol>` ekler",
        any(a_[i:i + 4] == ["--perms", "0700", "--dir", RT_HEDEF] for i in range(len(a_))) and
        any(a_[i:i + 4] == ["--perms", "0700", "--dir", TMP_HEDEF] for i in range(len(a_))) and
        sorted(bilgi["bos_dizin"]) == sorted([RT_HEDEF, TMP_HEDEF]), str(a_))
_yok = os.path.join(f"/run/user/{UID}", "deskhand-test-psd-YOK-" + str(os.getpid()))
_bag = os.path.join(EV, ".config", "vivaldi-psd-yok")
os.symlink(_yok, _bag)
try:
    kontrol("birim: psd hedefi YOKKEN de (psd durmuş) bağ boşta kalmaz → boş dizin olarak eklenir",
            _yok in arka_ortak.sir_bos_hedefler(EV) and
            any(a_[i:i + 4] == ["--perms", "0700", "--dir", _yok]
                for a_ in [arka_ortak.ev_baglari(EV)[0]] for i in range(len(a_))))
finally:
    os.unlink(_bag)
argv = arka_ortak.korumali_argv(["/usr/bin/true"], RT, [], ev=EV)
i_tmp, i_run, i_dir = argv.index("/tmp"), argv.index(f"/run/user/{UID}"), argv.index(RT_HEDEF)
kontrol("birim: --dir, /tmp ve /run/user/UID tmpfs'lerinden SONRA gelir (bwrap sırası)", i_dir > i_run and i_dir > i_tmp)
if arka_ortak.bwrap_size_var():
    kontrol("birim: /run/user/UID tmpfs'inin boyutu sınırlı (--size hemen önce)",
            argv[i_run - 3:i_run] == ["--size", str(arka_ortak.RUN_USER_BOYUT), "--tmpfs"],
            str(argv[i_run - 3:i_run + 1]))
    r = ad_alani(f"df -B1 --output=size /run/user/{UID} | tail -1")
    kontrol("birim: ad alanındaki /run/user/UID gerçekten sınırlı", r.stdout.strip() == str(arka_ortak.RUN_USER_BOYUT),
            r.stdout + r.stderr)

# ad alanında: bağ boşta asılı DEĞİL, hedef BOŞ ve yazılabilir; gerçek içerik görünmez; yazılanlar ana makineye sızmaz
# ev dizini boş tmpfs + beyaz liste: sembolik bağ ad alanında YOK (asılı bağ yok); Chromium dizini kendisi açar
bet = ('for d in .config/chromium .config/vivaldi-snapshot; do p="$HOME/$d"; [ -L "$p" ] && echo asili:$d; '
       'mkdir -p "$p" && [ -d "$p/" ] && echo dizin:$d; '
       'ls -A "$p/" | sed "s|^|ic:$d:|"; echo YAZILDI > "$p/Yeni" && echo yazildi:$d; done; '
       f"cat {RT_HEDEF}/Cookies {TMP_HEDEF}/Cookies 2>&1; ls -A {RT_HEDEF} | sed 's/^/rt:/'")
r = ad_alani(bet)
cikti = r.stdout
kontrol("birim: ad alanında ~/.config/chromium ve ~/.config/vivaldi-snapshot çözülüyor (dizin) ve yazılabilir",
        "dizin:.config/chromium" in cikti and "dizin:.config/vivaldi-snapshot" in cikti and
        "yazildi:.config/chromium" in cikti and "yazildi:.config/vivaldi-snapshot" in cikti and "asili:" not in cikti,
        cikti + r.stderr)
kontrol("birim: ad alanından GERÇEK psd dizini GÖRÜNMEZ (Cookies yok, sır okunmuyor)",
        "ic:.config/chromium:Cookies" not in cikti and "GIZLI-PSD" not in cikti and "rt:Cookies" not in cikti, cikti)
kontrol("birim: ad alanında yazılanlar ana makinedeki hedefe SIZMAZ; gerçek içerik değişmedi",
        sorted(os.listdir(RT_HEDEF)) == ["Cookies"] and sorted(os.listdir(TMP_HEDEF)) == ["Cookies"] and
        open(os.path.join(RT_HEDEF, "Cookies")).read() == "GIZLI-PSD-RT")
r2 = ad_alani('ls -A "$HOME/.config/chromium/" | wc -l')
kontrol("birim: başka bir başlatma önceki başlatmanın yazdığını görmez (ad alanına özel)", r2.stdout.strip() == "0",
        r2.stdout + r2.stderr)

# ---------------------------------------------------------------- A2) ABM-F3 birim: tarayıcı kararları (ekransız)
from deskhand import uygulama  # noqa: E402
from deskhand.hata import Dur  # noqa: E402
from deskhand.oturum import Hazirlik  # noqa: E402

yk = chromium.yerli_hazirla("chromium", ["about:blank"])
kontrol("F3 birim: yerli Chromium boş profil kopyası + --password-store=basic (anahtarlık rölesi yok)",
        os.path.isdir(yk["kopya_yolu"]) and not {"Default", "Local State"} & set(os.listdir(yk["kopya_yolu"])) and
        "--password-store=basic" in yk["argv"] and not any("kwallet" in a for a in yk["argv"]) and
        f"--user-data-dir={yk['kopya_yolu']}" in yk["argv"], str(yk))
kontrol("F3 birim: yerli Chromium erişilebilirlik bayrağıyla açılır", uygulama.ERISIM_BAYRAGI in yk["argv"], str(yk))
kontrol("F3 birim: yerli Chromium notu 'kayıtlı girişler yok' der", "kayıtlı girişler yok" in yk["not"], yk["not"])
kopya.temizle(yk["kopya_yolu"])


def _on(politikalar, flatpak=()):
    return Hazirlik(karar="on", aciklama="eski", gerekli_keyring=True,
                    ayrinti={"politikalar": list(politikalar), "cozum": {"flatpak": list(flatpak)}})


t0 = time.monotonic()
try:
    chromium.on_karari(_on(["chrome"], ["com.google.Chrome"]))
    e = None
except Dur as x:
    e = x
kontrol("Flatpak Chrome (birim): 30 sn içinde kod 16 + kök neden + yerli chromium önerisi",
        e is not None and e.kod == 16 and "~/.var/app/com.google.Chrome" in e.mesaj and "X yetkisi" in e.mesaj and
        "chromium" in e.mesaj and time.monotonic() - t0 < 30, repr(e and e.mesaj))
h = chromium.on_karari(_on(["chromium"]))
kontrol("F3 birim: politika 'on' + yerli Chromium → kopya kararı (boş profil, a11y)",
        h is not None and h.karar == "kopya" and h.kopya_yolu and uygulama.ERISIM_BAYRAGI in h.argv and
        "kayıtlı girişler yok" in h.aciklama, repr(h))
if h is not None and h.kopya_yolu:
    kopya.temizle(h.kopya_yolu)
kontrol("F3 birim: başka 'on' uygulaması (vivaldi, brave, Flatpak olmayan chrome) değişmez",
        chromium.on_karari(_on(["vivaldi"])) is None and chromium.on_karari(_on(["chrome"])) is None)
kontrol("F3 birim: uzak komut/ad alanı yolu YOK (uzak_acik, kumda_baslat kaldırıldı)",
        not hasattr(uygulama, "uzak_acik") and not hasattr(arka_ortak, "kumda_baslat"))
# EK-2: istemci kimliği PID'i, tam bir yeni pencere, yetkili kayıt sandbox dışında
from deskhand import api as _api  # noqa: E402
from deskhand.oturum import kopya_bekcisi, politika  # noqa: E402


class _SahteAu:
    def __init__(self, pen):
        self.pen, self.etkin = list(pen), (pen[0] if pen else "")

    def pencereler(self):
        return [(w, "t", (0, 0, 1, 1)) for w in self.pen]

    def pid(self, w):
        return os.getpid()  # _NET_WM_PID taklidi: her pencere "tarayıcının" PID'ini söylüyor

    def sinif(self, w):
        return "firefox"

    def baslik(self, w):
        return "Mozilla Firefox"

    def aktif(self):
        return self.etkin

    def kapat(self, w):
        pass


_girdi = []
_eski = (masaustu.durum, uygulama._kayitli_tarayicilar, _api.tus, _api.yaz)
_kp_e2 = kopya.yeni_kopya_dizini("firefox")
try:
    uygulama._kayitli_tarayicilar = lambda d_, tur_, h_: [(os.getpid(), _kp_e2)]
    _api.yaz = lambda w, m, **k: _girdi.append(("yaz", w, m))
    # (a) Xvfb türü: istemci kimliği PID'i yok → bu yol kullanılmaz, HİÇBİR girdi gönderilmez
    masaustu.durum = lambda *a, **k: {"tur": "xvfb", "calisma": _yalitim.GECICI, "cgroup": ""}
    _api.tus = lambda w, t, **k: _girdi.append(("tus", w, t))
    au_ = _SahteAu(["{a}"])
    sonuc = uygulama.ayni_surecte_ac(au_, ["firefox", "--profile", "/x", "--no-remote", "https://a.b/"], "/x")
    kontrol("_NET_WM_PID sahte, credentials yok → adres yazılmaz (girdi yok, yeni örnek yolu)",
            sonuc is None and _girdi == [], str(_girdi))
    # (b) KWin: Ctrl+N sonrası İKİ yeni pencere → iptal (Dur 7), adres yazılmaz
    masaustu.durum = lambda *a, **k: {"tur": "kwin", "calisma": _yalitim.GECICI, "cgroup": ""}
    au_ = _SahteAu(["{a}"])

    def _tus(w, t, **k):
        _girdi.append(("tus", w, t))
        if t == "ctrl+n":
            au_.pen += ["{b}", "{c}"]
    _api.tus = _tus
    _girdi.clear()
    try:
        uygulama.ayni_surecte_ac(au_, ["firefox", "--profile", "/x", "--no-remote", "https://a.b/"], "/x")
        e = None
    except Dur as x:
        e = x
    kontrol("iki yeni pencere → iptal (Dur 7), adres yazılmaz",
            e is not None and e.kod == 7 and not any(g[0] == "yaz" or g[2] == "ctrl+l" for g in _girdi),
            f"{e and e.mesaj} {_girdi}")
finally:
    masaustu.durum, uygulama._kayitli_tarayicilar, _api.tus, _api.yaz = _eski
    kopya.temizle(_kp_e2)

_kp_s = kopya.yeni_kopya_dizini("chromium")
kopya_bekcisi.sahip_yaz(_kp_s, {"pid": os.getpid(), "bas": kopya_bekcisi.baslangic(os.getpid())})
_d_s = {"tur": "kwin", "calisma": tempfile.mkdtemp(dir=_yalitim.GECICI), "cgroup": ""}
kontrol("profil dizinine yazılan sahte sahip kaydı hedef seçilmez",
        uygulama._kayitli_tarayicilar(_d_s, "chromium", None) == [] and
        os.path.dirname(os.path.realpath(_kp_s)) == os.path.realpath(politika.kopya_dizini()))
uygulama.chromium_kaydet(_d_s, _kp_s, os.getpid())
kontrol("F3 birim: çalışma dizinindeki yetkili Chromium kaydı (pid_dogru) seçilir (kontrol)",
        uygulama._kayitli_tarayicilar(_d_s, "chromium", None) == [(os.getpid(), _kp_s)] and
        oct(os.stat(os.path.join(_d_s["calisma"], uygulama.CHROMIUM_KAYIT)).st_mode & 0o777) == "0o600")
kopya.temizle(_kp_s)

kontrol("F3 birim: 2. pencere adresi yalnız belgelerden (profil/bayrak değil)",
        uygulama._belgeler(["firefox", "--profile", "/k1", "--no-remote", "https://a.b/"]) == ["https://a.b/"])

# ---------------------------------------------------------------- A3) ABM-F3-R2 birim: bağımsız inceleme bulguları
import threading as _th  # noqa: E402

from deskhand import erisim as _erisim, web as _web  # noqa: E402

YABANCI = 1  # başka sürecin (kayıtlı tarayıcının soyundan OLMAYAN) penceresi: kimlik PID'i init


class _SahteAu2:
    """Sahte KWin arka ucu: pencere → (başlık, sınıf, pid). pid os.getpid() = kayıtlı tarayıcının soyu."""

    def __init__(self, pen):
        self.pen = dict(pen)  # w → [başlık, sınıf, pid]
        self.etkin = next(iter(self.pen), "")
        self.gec = {}  # w → başlık/sınıf daha kaç okumada boş (pencere yeni açılıyor)
        self.kapatilan = []
        self.baslatilan = []
        self.kilit = _th.Lock()

    def pencereler(self):
        with self.kilit:
            return [(w, v[0], (0, 0, 1, 1)) for w, v in sorted(self.pen.items())]

    def pid(self, w):
        return self.pen[w][2] if w in self.pen else None

    def baslik(self, w):
        if self.gec.get(w, 0) > 0:
            self.gec[w] -= 1
            return ""
        return self.pen[w][0] if w in self.pen else ""

    def sinif(self, w):
        return "" if self.gec.get(w, 0) > 0 else (self.pen[w][1] if w in self.pen else "")

    def aktif(self):
        return self.etkin

    def kapat(self, w):
        self.kapatilan.append(w)
        self.pen.pop(w, None)

    def baslat(self, argv, env=None, cikti=None, kopya=None):
        self.baslatilan.append((list(argv), kopya, bool(kopya) and os.path.isdir(kopya)))

        class _P:
            pid = os.getpid()
        return _P()


FF = ["Mozilla Firefox", "firefox", os.getpid()]
FF2 = ["Yeni Sekme — Mozilla Firefox", "firefox", os.getpid()]  # Ctrl+N ile açılan yeni pencere (başlığı tek)
_r2_eski = (masaustu.durum, uygulama._kayitli_tarayicilar, _api.tus, _api.yaz, _erisim.odak_bilgisi,
            _web.sayfa_bilgisi, uygulama.YENI_PENCERE_BEKLE_SN, getattr(uygulama, "ADRES_DOGRULA_SN", None),
            _api.arka, uygulama.tum_pencereler, _api.yasak_mi, uygulama.ayni_surecte_ac)
_r2_calisma = tempfile.mkdtemp(dir=_yalitim.GECICI)
_r2_kp1 = kopya.yeni_kopya_dizini("firefox")
_r2_girdi = []


def _r2_kur(au_, ctrl_n=None):
    """Sahte ortam: KWin, kayıtlı tek Firefox (bu süreç), denetimli girdi kaydedilir; ctrl_n(au_, w) Ctrl+N etkisi."""
    _r2_girdi.clear()
    masaustu.durum = lambda *a, **k: {"tur": "kwin", "calisma": _r2_calisma, "cgroup": ""}
    uygulama._kayitli_tarayicilar = lambda d_, tur_, h_: [(os.getpid(), _r2_kp1)]

    def _tus(w, t, **k):
        _r2_girdi.append(("tus", w, t))
        if t == "ctrl+n" and ctrl_n:
            with au_.kilit:
                ctrl_n(au_, w)
    _api.tus = _tus
    _api.yaz = lambda w, m, **k: _r2_girdi.append(("yaz", w, m))


def _r2_kopya():
    return kopya.yeni_kopya_dizini("firefox")


def _r2_dene(f):
    try:
        return f(), None
    except Dur as x:
        return None, x


try:
    uygulama.YENI_PENCERE_BEKLE_SN = 2.0
    uygulama.ADRES_DOGRULA_SN = 1.0
    ODAK_ADRES = {"rol": "entry", "belge_ici": False, "duzenlenebilir": True}
    ODAK_SAYFA = {"rol": "document web", "belge_ici": True, "duzenlenebilir": False}

    # (1) ORTA: doğrulanan pencere çağırana döner; doğrulamadan SONRA açılan sahte Firefox penceresi verilmez
    au2 = _SahteAu2({"{a}": FF})

    def _cn_yeni_b(a_, w):
        a_.pen["{b}"] = list(FF2)
        a_.gec["{b}"] = 3  # gerçek yeni pencerenin başlığı/sınıfı ilk okumalarda henüz boş
        a_.etkin = "{b}"
    _r2_kur(au2, _cn_yeni_b)
    _ic = uygulama.ayni_surecte_ac

    def _sarili(au_, komut_, kopya_):
        s = _ic(au_, komut_, kopya_)
        au_.pen["{0}"] = ["Mozilla Firefox", "firefox", YABANCI]  # saldırgan: doğrulamadan sonra açılan sahte pencere
        return s
    uygulama.ayni_surecte_ac = _sarili
    _api.arka = lambda: au2
    uygulama.tum_pencereler = lambda: set(au2.pen)
    _api.yasak_mi = lambda w: None
    r, e = _r2_dene(lambda: _api.uygulama_ac(["firefox", "--profile", _r2_kopya(), "--no-remote"], "Firefox", [],
                                             None, None, 3.0, kopya=_r2_kopya()))
    kontrol("R2 (1): doğrulamadan sonra açılan sahte firefox penceresi ajana opened diye verilmez (doğrulanan döner)",
            e is None and r.get("status") == "opened" and (r.get("window") or {}).get("id") == "{b}",
            f"{r} {e and e.mesaj}")
    uygulama.ayni_surecte_ac = _ic
    _api.arka, uygulama.tum_pencereler, _api.yasak_mi = _r2_eski[8], _r2_eski[9], _r2_eski[10]

    # (2a) DÜŞÜK: Ctrl+L sonrası odak adres çubuğunda değilse adres YAZILMAZ, dürüst ileti (Dur 7)
    au2 = _SahteAu2({"{a}": FF})
    _r2_kur(au2, lambda a_, w: (a_.pen.__setitem__("{b}", list(FF2)), setattr(a_, "etkin", "{b}")))
    _erisim.odak_bilgisi = lambda k: ODAK_SAYFA
    kp_ = _r2_kopya()
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote", "https://a.b/"],
                                                     kp_))
    kontrol("R2 (2a): Ctrl+L sonrası odak sayfada (adres çubuğu değil) → adres yazılmaz, Dur 7 + 'adres çubuğu' iletisi",
            e is not None and e.kod == 7 and "adres çubuğu" in e.mesaj and not any(g[0] == "yaz" for g in _r2_girdi),
            f"{s} {e and e.mesaj} {_r2_girdi}")
    # (3) Dur 7: kendi açtığımız ve doğruladığımız pencere kapatılır, politika kopyası silinir
    kontrol("R2 (3a): Dur 7 → kendi doğrulanmış yeni penceremiz kapatıldı, politika kopyası silindi",
            au2.kapatilan == ["{b}"] and not os.path.exists(kp_), f"kapatılan {au2.kapatilan} kopya {os.path.exists(kp_)}")

    # (2b) Return sonrası sayfa adresi/başlık hedefe dönmezse "adres doğrulanamadı" (başarı denmez)
    au2 = _SahteAu2({"{a}": FF})
    _r2_kur(au2, lambda a_, w: (a_.pen.__setitem__("{b}", list(FF2)), setattr(a_, "etkin", "{b}")))
    _erisim.odak_bilgisi = lambda k: ODAK_ADRES
    _web.sayfa_bilgisi = lambda k: {"adres": "about:newtab", "baslik": "Yeni Sekme"}
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote",
                                                           "https://a.b/yol"], _r2_kopya()))
    kontrol("R2 (2b): Return sonrası adres hedefe dönmedi → sonuç 'adres doğrulanamadı' (adres_dogrulandi False)",
            e is None and getattr(s, "kimlik", None) == "{b}" and getattr(s, "adres_dogrulandi", None) is False and
            any(g[0] == "yaz" and g[2] == "https://a.b/yol" for g in _r2_girdi), f"{s} {e and e.mesaj}")
    au2 = _SahteAu2({"{a}": FF})
    _r2_kur(au2, lambda a_, w: (a_.pen.__setitem__("{b}", list(FF2)), setattr(a_, "etkin", "{b}")))
    _web.sayfa_bilgisi = lambda k: {"adres": "https://a.b/yol", "baslik": "A"}
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote",
                                                           "https://a.b/yol"], _r2_kopya()))
    kontrol("R2 (2b kontrol): sayfa adresi hedefe döndü → adres_dogrulandi True",
            e is None and getattr(s, "adres_dogrulandi", None) is True, f"{s} {e and e.mesaj}")
    # (2c) yeni pencereyle AYNI başlıklı başka tarayıcı penceresi: AT-SPI çerçevesi (başlıkla seçilir) öbür pencereye
    # gidebilir → odak/adres doğrulanamaz → yazılmaz
    au2 = _SahteAu2({"{a}": FF})
    _r2_kur(au2, lambda a_, w: (a_.pen.__setitem__("{b}", list(FF)), setattr(a_, "etkin", "{b}")))
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote",
                                                           "https://a.b/yol"], _r2_kopya()))
    kontrol("R2 (2c): aynı başlıklı öbür pencere varken adres yazılmaz (Dur 7, eşleme belirsiz), pencere kapatıldı",
            e is not None and e.kod == 7 and "aynı başlıklı" in e.mesaj and
            not any(g[0] == "yaz" or g[2] == "ctrl+l" for g in _r2_girdi) and au2.kapatilan == ["{b}"],
            f"{s} {e and e.mesaj} {_r2_girdi}")

    # (3b) Dur 7 (adres + yabancı ek pencere): yalnız KENDİ penceremiz kapanır, başkasınınkine dokunulmaz
    au2 = _SahteAu2({"{a}": FF})

    def _cn_yabanci(a_, w):
        a_.pen["{b}"] = list(FF2)
        a_.pen["{y}"] = ["Mozilla Firefox", "firefox", YABANCI]
        a_.etkin = "{b}"
    _r2_kur(au2, _cn_yabanci)
    kp_ = _r2_kopya()
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote", "https://a.b/"],
                                                     kp_))
    kontrol("R2 (3b): yabancı ek pencere → Dur 7; yalnız kendi penceremiz kapandı, yabancıya dokunulmadı, kopya silindi",
            e is not None and e.kod == 7 and au2.kapatilan == ["{b}"] and "{y}" in au2.pen and not os.path.exists(kp_),
            f"{e and e.mesaj} kapatılan {au2.kapatilan} kopya {os.path.exists(kp_)}")

    # (5a) Ctrl+N hedefi sıralamadaki ilk pencere (diyalog) değil, tarayıcının etkin/ana penceresi
    au2 = _SahteAu2({"{0}": ["Kitaplık", "firefox", os.getpid()], "{a}": ["Sayfa — Mozilla Firefox", "firefox",
                                                                           os.getpid()],
                     "{k}": ["Belge — Kate", "kate", YABANCI]})
    au2.etkin = "{k}"
    _r2_kur(au2, lambda a_, w: (a_.pen.__setitem__("{b}", list(FF2)), setattr(a_, "etkin", "{b}")))
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote"], _r2_kopya()))
    hedefler = [g[1] for g in _r2_girdi if g[2] == "ctrl+n"]
    kontrol("R2 (5a): Ctrl+N diyalog/ilk pencereye değil tarayıcının ana penceresine gider",
            hedefler == ["{a}"] and getattr(s, "kimlik", None) == "{b}", f"{hedefler} {s} {e and e.mesaj}")

    # (5b) tarayıcı kapanmaktaysa 10 sn sonra Dur 7 değil: hemen yeni örnek yolu (None)
    uygulama.YENI_PENCERE_BEKLE_SN = 4.0
    au2 = _SahteAu2({"{a}": FF})
    _r2_kur(au2, lambda a_, w: a_.pen.pop("{a}", None))  # Ctrl+N gönderildi, pencere kapandı (tarayıcı kapanıyor)
    kp_ = _r2_kopya()
    t0 = time.monotonic()
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote"], kp_))
    sure_ = time.monotonic() - t0
    kontrol("R2 (5b): kapanmakta olan tarayıcı → Dur 7 yok, hemen yeni örnek yolu (None, kopya korunur)",
            e is None and s is None and sure_ < 2.0 and os.path.isdir(kp_), f"{s} {e and e.mesaj} {sure_:.1f} sn")
    kopya.temizle(kp_)
    uygulama.YENI_PENCERE_BEKLE_SN = 2.0

    # (5c) aynı masaüstünde paralel iki open sıraya alınır: ikisi de kendi penceresini alır
    au2 = _SahteAu2({"{a}": FF})
    _say = [0]

    def _cn_paralel(a_, w):
        _say[0] += 1
        yeni_ = "{b%d}" % _say[0]
        a_.pen[yeni_] = list(FF)
        a_.etkin = yeni_
    _r2_kur(au2, _cn_paralel)
    sonuclar = []

    def _paralel():
        sonuclar.append(_r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote"],
                                                                  _r2_kopya())))
    ipler = [_th.Thread(target=_paralel) for _ in range(2)]
    for i_ in ipler:
        i_.start()
    for i_ in ipler:
        i_.join(30)
    kontrol("R2 (5c): paralel 2 open kilitle sıraya alındı: ikisi de başarılı, farklı pencere",
            len(sonuclar) == 2 and all(x[1] is None and x[0] is not None for x in sonuclar) and
            len({x[0].kimlik for x in sonuclar}) == 2, str([(x[0], x[1] and x[1].mesaj) for x in sonuclar]))

    # (6b) birden çok adres: Ctrl+N yolunda açıkça reddedilir (hiçbir girdi gönderilmeden)
    au2 = _SahteAu2({"{a}": FF})
    _r2_kur(au2, lambda a_, w: (a_.pen.__setitem__("{b}", list(FF2)), setattr(a_, "etkin", "{b}")))
    s, e = _r2_dene(lambda: uygulama.ayni_surecte_ac(au2, ["firefox", "--profile", "/x", "--no-remote", "https://a.b/",
                                                           "https://c.d/"], _r2_kopya()))
    kontrol("R2 (6b): birden çok adres sessizce atılmaz: açıkça reddedilir, girdi gönderilmez",
            e is not None and e.kod == 1 and _r2_girdi == [], f"{s} {e and e.mesaj} {_r2_girdi}")
finally:
    (masaustu.durum, uygulama._kayitli_tarayicilar, _api.tus, _api.yaz, _erisim.odak_bilgisi, _web.sayfa_bilgisi,
     uygulama.YENI_PENCERE_BEKLE_SN, _adres_sn, _api.arka, uygulama.tum_pencereler, _api.yasak_mi,
     uygulama.ayni_surecte_ac) = _r2_eski
    if _adres_sn is not None:
        uygulama.ADRES_DOGRULA_SN = _adres_sn
    kopya.temizle(_r2_kp1)

# (4) Flatpak tespiti eşdeğer yazımlarla atlatılamaz (PoC'deki üç biçim + --branch değeri + app/ ref + kullanıcı exports)
_fp_bicimleri = [
    ["flatpak", "run", "com.google.Chrome/x86_64/stable", "about:blank"],
    ["flatpak", "--verbose", "--user", "run", "com.google.Chrome"],
    ["/var/lib/flatpak/exports/bin/com.google.Chrome"],
    [os.path.join(_yalitim.GECICI, ".local/share/flatpak/exports/bin/com.google.Chrome"), "about:blank"],  # kullanıcı kurulumu
    ["flatpak", "run", "--branch", "stable", "com.google.Chrome"],
    ["flatpak", "run", "--arch=x86_64", "app/com.google.Chrome/x86_64/stable"],
    ["flatpak", "run", "com.github.Eloston.UngoogledChromium"],
]
_fp_sonuc = []
for b_ in _fp_bicimleri:
    _s, e = _r2_dene(lambda b_=b_: uygulama.flatpak_tarayici_denetle(b_))
    _fp_sonuc.append((b_, e and e.kod))
kontrol("R2 (4): Flatpak Chrome eşdeğer yazımları (ref, global seçenek, exports/bin, --branch değeri) → kod 16",
        all(k_ == 16 for _b, k_ in _fp_sonuc), str(_fp_sonuc))
from deskhand.oturum.cozum import _flatpak_kimligi  # noqa: E402

kontrol("R2 (4 kontrol): seçenek DEĞERİ kimlik sayılmaz; Firefox Flatpak'ı 16 almaz",
        _flatpak_kimligi(["flatpak", "run", "--branch", "stable", "org.kde.kate"])[0] == "org.kde.kate" and
        _r2_dene(lambda: uygulama.flatpak_tarayici_denetle(["flatpak", "run", "org.mozilla.firefox"]))[1] is None and
        _flatpak_kimligi(["flatpak", "run", "--command=sh", "org.kde.kate"]) == ("org.kde.kate", "sh"))

# (5d) chromium_kaydet: dosya kilidi (eşzamanlı yazıda kayıt kaybolmaz) + ölü kayıt budanır
_d_k = {"tur": "kwin", "calisma": tempfile.mkdtemp(dir=_yalitim.GECICI), "cgroup": ""}
with open(os.path.join(_d_k["calisma"], uygulama.CHROMIUM_KAYIT), "w") as f:
    f.write('[{"kopya": "/olu", "pid": 999999999, "bas": 1}]')


def _kaydet_n(n0):
    for i_ in range(25):
        uygulama.chromium_kaydet(_d_k, f"/kopya-{n0}-{i_}", os.getpid())


ipler = [_th.Thread(target=_kaydet_n, args=(n_,)) for n_ in range(3)]
for i_ in ipler:
    i_.start()
for i_ in ipler:
    i_.join(30)
_kk = uygulama._chromium_kayitlari(_d_k["calisma"])
kontrol("R2 (5d): chromium_kaydet dosya kilidiyle: 3×25 eşzamanlı yazıda kayıt kaybolmadı, ölü kayıt budandı",
        len(_kk) == 75 and not any(g.get("kopya") == "/olu" for g in _kk), f"{len(_kk)} kayıt")

# (6a) _belgeler: seçenek DEĞERİ (-P work, --class X) adres sayılmaz
kontrol("R2 (6a): _belgeler -P/--class değerlerini adres saymaz",
        uygulama._belgeler(["firefox", "-P", "work", "--class", "x", "https://a"]) == ["https://a"],
        str(uygulama._belgeler(["firefox", "-P", "work", "--class", "x", "https://a"])))

# (6c) on_karari tek kez: uygulama.oturum_hazirla kendisi yeniden çağırmaz
from deskhand import oturum as _oturum  # noqa: E402

_say_on = [0]
_eski_on, _eski_hz = chromium.on_karari, _oturum.hazirla
try:
    chromium.on_karari = lambda h: (_say_on.__setitem__(0, _say_on[0] + 1), None)[1]
    _oturum.hazirla = lambda *a, **k: Hazirlik(karar="paylas", aciklama="", gerekli_keyring=False, ayrinti={})
    uygulama.oturum_hazirla("chromium")
finally:
    chromium.on_karari, _oturum.hazirla = _eski_on, _eski_hz
kontrol("R2 (6c): on_karari tek kez (oturum.hazirla içinde); uygulama.oturum_hazirla yeniden çağırmaz",
        _say_on[0] == 0, f"{_say_on[0]} çağrı")

# (6d) tanı (`oturum hazirla`) tmpfs kopyası OLUŞTURMAZ; kopya yalnız gerçek açılışta (_baslat) oluşur
h_ = chromium.on_karari(_on(["chromium"]))
_var_once = bool(h_ and h_.kopya_yolu and os.path.exists(h_.kopya_yolu))
au2 = _SahteAu2({})
_eski_d = masaustu.durum
try:
    masaustu.durum = lambda *a, **k: {"tur": "kwin", "calisma": tempfile.mkdtemp(dir=_yalitim.GECICI), "cgroup": ""}
    uygulama._baslat(au2, [*h_.argv, "about:blank"], None, None, h_.kopya_yolu)
finally:
    masaustu.durum = _eski_d
kontrol("R2 (6d): kararda kopya yok (tanı yan etkisiz); _baslat başlatmadan ÖNCE 0700 kopyayı oluşturur",
        not _var_once and len(au2.baslatilan) == 1 and au2.baslatilan[0][2] and
        oct(os.stat(h_.kopya_yolu).st_mode & 0o777) == "0o700", f"önce {_var_once} {au2.baslatilan}")
kopya.temizle(h_.kopya_yolu)

# ---------------------------------------------------------------- B) görünmez masaüstünde gerçek Chromium
if not (shutil.which("chromium") and shutil.which("bwrap")):
    print("B) atlandı: chromium ya da bwrap yok")
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(0 if gecen == toplam else 1)
tur = (os.environ.get("DESKHAND_ARKA_TUR") or "").strip().lower()
if tur == "xvfb" and not shutil.which("Xvfb"):
    print("B) atlandı: Xvfb yok")
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(0 if gecen == toplam else 1)

print("\nB) görünmez masaüstünde Chromium")
d = masaustu.masaustu_baslat()
au = sec(arka_bayragi=True)
# GÜVENLİK: hedef GÖRÜNMEZ masaüstü olmalı (kullanıcının ekranı değil), yoksa hiçbir şey başlatılmaz
if au.ad != "sanal":
    print(f"!!! hedef sanal değil ({au.ad}); durduruldu")
    masaustu.masaustu_durdur()
    sys.exit(2)
kontrol(f"masaüstü türü {masaustu.tur(d)}, arka uç sanal", au.ad == "sanal")


def ayakta_mi(p, onceki, sure=12.0):
    """Süre dolana dek süreç yaşıyor ve yeni 'arka:' pencere var mı → (ayakta, pencere, çıkış kodu)."""
    bitis = time.monotonic() + sure
    pencere = None
    while time.monotonic() < bitis and p.poll() is None:
        for w, b, _g in au.pencereler():
            if w not in onceki:
                assert w.startswith("arka:"), w  # kullanıcının ekranına kaçma yok
                pencere = pencere or w
        time.sleep(0.4)
    return p.poll() is None and pencere is not None, pencere, p.poll()


def gunluk_sonu(log, n=12):
    """KALDI iletisine günlüğün son satırları (CI'da geçici dizin silinir; tanı ancak çıktıda kalır)."""
    try:
        log.flush()
        with open(log.name, errors="replace") as f:
            return " | son satırlar: " + " ⏎ ".join(f.read().splitlines()[-n:])
    except OSError as e:
        return f" | günlük okunamadı: {e}"


def kapat(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(8)
        except Exception:  # noqa: BLE001
            p.kill()


try:
    # (1) ham başlatma: profilsiz (varsayılan yapılandırma dizini → XDG_CONFIG_HOME)
    once = {w for w, _b, _g in au.pencereler()}
    log = open(os.path.join(_yalitim.PAYLASIM, "chromium-1.log"), "w")
    p = au.baslat(["chromium", "--no-first-run", "--no-default-browser-check", "--password-store=basic",
                   "--force-renderer-accessibility", "about:blank"] +
                  (["--ozone-platform=x11"] if masaustu.tur(d) == "kwin" else []), cikti=log)
    ok, w, kod = ayakta_mi(p, once)
    kontrol("(1) ham chromium (profilsiz) ayakta, pencere arka:, çıkış 133 değil", ok and kod != 133,
            f"çıkış {kod}, pencere {w}, günlük {log.name}" + ("" if ok and kod != 133 else gunluk_sonu(log)))
    kapat(p)
    log.close()

    # (2) api.uygulama_ac: MCP open_app'in başlatma adımı (erişilebilirlik + X11 bayrağı eklenir), kullanıcı profilsiz
    with api.hedef("sanal"):
        r = api.uygulama_ac(["chromium", "--no-first-run", "--no-default-browser-check", "--password-store=basic",
                             "about:blank"], "Chromium", [], None, None, 20.0)
    kontrol("(2) api.uygulama_ac: status opened, pencere arka:",
            r.get("status") == "opened" and str((r.get("window") or {}).get("id", "")).startswith("arka:"), str(r))

    # (3) oturum kopyası yolu: SAHTE profil kaynağı → kopya → chromium_argv (kullanıcının gerçek profili yok)
    sahte = os.path.join(_yalitim.GECICI, "sahte-chromium")
    os.makedirs(os.path.join(sahte, "Default"), exist_ok=True)
    with open(os.path.join(sahte, "Local State"), "w") as f:
        f.write("{}")
    kp = kopya.yeni_kopya_dizini("chromium")
    chromium.veri_dizini_kopyala(sahte, kp)
    argv = chromium.chromium_argv("chromium", kp, ["--password-store=basic", "--force-renderer-accessibility",
                                                   "about:blank"] +
                                  (["--ozone-platform=x11"] if masaustu.tur(d) == "kwin" else []))
    argv = [a for a in argv if a != "--password-store=kwallet6"]
    once = {w for w, _b, _g in au.pencereler()}
    log = open(os.path.join(_yalitim.PAYLASIM, "chromium-3.log"), "w")
    p = masaustu.baslat(argv, kopya=kp, stdout=log, stderr=log)
    ok, w, kod = ayakta_mi(p, once)
    kontrol("(3) oturum kopyası (sahte kaynak) + --user-data-dir: ayakta, çıkış 133 değil", ok and kod != 133,
            f"çıkış {kod}, pencere {w}, günlük {log.name}")
    kapat(p)
    log.close()

    # (4) SAHTE ev dizini: user-dirs.dirs (XDG indirme klasörü sahte evde) + psd benzeri sembolik bağ. Chromium ayakta
    # kalır ve yerel http sunucusundan inen dosya XDG indirme klasörüne düşer (kalıcı klasör; atılan katmana değil).
    gercek_indirilenler = os.path.join(os.path.realpath(os.path.expanduser("~")), "İndirilenler")
    once_gercek = sorted(os.listdir(gercek_indirilenler)) if os.path.isdir(gercek_indirilenler) else None
    ev4 = os.path.join(_yalitim.GECICI, "ev4")
    ind = os.path.join(ev4, "İndirilenler")
    psd = tempfile.mkdtemp(prefix="deskhand-test-psd4-", dir=f"/run/user/{os.getuid()}")
    atexit.register(shutil.rmtree, psd, True)
    os.makedirs(os.path.join(ev4, ".config"))
    os.makedirs(ind)
    with open(os.path.join(ev4, ".config/user-dirs.dirs"), "w", encoding="utf-8") as f:
        f.write('XDG_DOWNLOAD_DIR="$HOME/İndirilenler"\nXDG_DOCUMENTS_DIR="$HOME/Belgeler"\n')
    os.symlink(psd, os.path.join(ev4, ".config/chromium"))
    GOVDE = b"deskhand-indirme-denemesi\n" * 100

    class Isleyici(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="deskhand-indir.bin"')
            self.send_header("Content-Length", str(len(GOVDE)))
            self.end_headers()
            self.wfile.write(GOVDE)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Isleyici)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    arka_ortak._EV_ZORLA = ev4
    try:
        once = {w for w, _b, _g in au.pencereler()}
        log = open(os.path.join(_yalitim.PAYLASIM, "chromium-4.log"), "w")
        p = masaustu.baslat(["chromium", "--no-first-run", "--no-default-browser-check", "--password-store=basic",
                             f"--user-data-dir={os.path.join(_yalitim.PAYLASIM, 'chr4-profil')}",
                             f"http://127.0.0.1:{srv.server_address[1]}/indir"] +
                            (["--ozone-platform=x11"] if masaustu.tur(d) == "kwin" else []),
                            {"HOME": ev4}, stdout=log, stderr=log)
        hedef = os.path.join(ind, "deskhand-indir.bin")
        bitis = time.monotonic() + 40
        while time.monotonic() < bitis and p.poll() is None and not \
                (os.path.exists(hedef) and os.path.getsize(hedef) == len(GOVDE)):
            time.sleep(0.4)
        kontrol("(4) sahte ev + psd benzeri sembolik bağ: Chromium ayakta (çıkış 133 değil)",
                p.poll() is None and p.poll() != 133, f"çıkış {p.poll()}, günlük {log.name}" + gunluk_sonu(log))
        kontrol("(4) indirilen dosya XDG indirme klasörüne (sahte ev İndirilenler) düştü, içerik eksiksiz",
                os.path.exists(hedef) and open(hedef, "rb").read() == GOVDE,
                str(sorted(os.listdir(ind))) + f" günlük {log.name}")
        kontrol("(4) gerçek ~/İndirilenler kirlenmedi",
                (sorted(os.listdir(gercek_indirilenler)) if os.path.isdir(gercek_indirilenler) else None) == once_gercek)
        kontrol("(4) sahte psd hedefi (ana makine) Chromium yazılarıyla DOLMADI (ad alanına özel dizin kullanıldı)",
                os.listdir(psd) == [], str(os.listdir(psd)))
        kapat(p)
        log.close()
    finally:
        arka_ortak._EV_ZORLA = None
        srv.shutdown()

    # ---------------------------------------------------------------- C) ABM-F3: aynı süreçte 2. pencere
    # Tür kapısı: Ctrl+N yolu yalnız KWin'de (istemci kimliği PID'i); Xvfb'de tasarım gereği yeni örnek açılır.
    if masaustu.tur(d) != "kwin":
        print("\nC) atlandı: Ctrl+N ile aynı süreçte pencere yalnız KWin türünde (Xvfb: yeni örnek, tasarım gereği)")
        print(f"\n{gecen}/{toplam} geçti")
        raise SystemExit(0 if gecen == toplam else 1)
    print("\nC) ABM-F3 tarayıcılar (gerçek görünmez masaüstü)")
    from deskhand import bellek_bekcisi  # noqa: E402

    def kafes_mb():
        try:
            with open(os.path.join("/sys/fs/cgroup", d["cgroup"].lstrip("/"), "memory.current")) as f:
                return int(f.read()) / 2**20
        except (OSError, KeyError, ValueError):
            return 0.0

    def pencereler():
        return {w for w, _b, _g in au.pencereler()}

    def ana_surecler(tur_, kp):
        """Kafesteki ANA tarayıcı süreçleri (içerik/yardımcı süreçler hariç) bu kopyayla."""
        out = []
        for pid in bellek_bekcisi._kafes_pidleri(d["cgroup"]):
            a = bellek_bekcisi._argv(pid)
            a = " ".join(a).split() if a and " " in a[0] else a  # Chromium argv'yi tek dizgeye yazar
            if not a:
                continue
            if tur_ == "firefox" and os.path.basename(a[0]) in ("firefox", "firefox-bin") and "-contentproc" not in a \
                    and kp in a:
                out.append(pid)
            if tur_ == "chromium" and "chrom" in os.path.basename(a[0]) and f"--user-data-dir={kp}" in a and \
                    not any(x.startswith("--type=") for x in a):
                out.append(pid)
        return out

    def ac(argv, ad, kp):
        with api.hedef("sanal"):
            return api.uygulama_ac(argv, ad, [], None, None, 30.0, kopya=kp)

    def kimlik(r):
        return str((r.get("window") or {}).get("id") or "")

    # pencerelerin başlıkları FARKLI olsun diye ayrı yerel sayfalar (aynı başlıklı iki çerçeve AT-SPI'de ayırt
    # edilemez → erisim._cerceve_bul Dur 6 verir; F3-R2)
    class _Sayfa(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            ad_ = self.path.strip("/").upper()
            govde = f"<html><head><title>F3R2-{ad_}</title></head><body>ok</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(govde.encode())

        def log_message(self, *a):
            pass
    srv_c = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Sayfa)
    threading.Thread(target=srv_c.serve_forever, daemon=True).start()
    atexit.register(srv_c.shutdown)

    def sayfa(y):
        return f"http://127.0.0.1:{srv_c.server_address[1]}/{y}"

    if shutil.which("firefox"):
        time.sleep(2)
        # SAHTE: kafeste komut satırı Firefox gibi görünen ama Deskhand kaydında olmayan süreç (hedef seçilmemeli)
        sahte_kp = kopya.yeni_kopya_dizini("firefox")
        sahte = masaustu.baslat(["/usr/bin/bash", "-c", f'exec -a firefox /usr/bin/python3 -c "import time; '
                                 f'time.sleep(300)" --profile {sahte_kp}'])
        time.sleep(1)
        m0 = kafes_mb()
        k1 = kopya.yeni_kopya_dizini("firefox")
        url_bir, url_iki = sayfa("bir"), sayfa("iki")
        r1 = ac(["firefox", "--profile", k1, "--no-remote", "--new-instance", url_bir], "Firefox", k1)
        time.sleep(5)
        m1, ana1 = kafes_mb(), ana_surecler("firefox", k1)
        kontrol("cmdline'ı tarayıcı gibi görünen sahte süreç hedef seçilmez (1. open yeni Firefox açtı)",
                ana_surecler("firefox", sahte_kp) and len(ana1) == 1 and r1.get("status") == "opened" and
                os.path.isdir(k1) and all(os.path.realpath(kp_) != os.path.realpath(sahte_kp) for _p, kp_ in
                                          uygulama._kayitli_tarayicilar(d, "firefox", None)),
                f"sahte {ana_surecler('firefox', sahte_kp)} ana {ana1} {r1}")
        kontrol("Firefox komut satırında --no-remote var (uzak kanal kapalı)",
                len(ana1) == 1 and "--no-remote" in bellek_bekcisi._argv(ana1[0]), str(ana1 and bellek_bekcisi._argv(ana1[0])))
        kayit1 = bellek_bekcisi._kayitlar(d["calisma"])
        k2 = kopya.yeni_kopya_dizini("firefox")
        t0 = time.monotonic()
        r2 = ac(["firefox", "--profile", k2, "--no-remote", "--new-instance", url_iki], "Firefox", k2)
        sure2 = time.monotonic() - t0
        time.sleep(5)
        m2, ana2 = kafes_mb(), ana_surecler("firefox", k1)
        kayit2 = bellek_bekcisi._kayitlar(d["calisma"])
        print(f"   firefox: kafes {m0:.0f} → 1 pencere {m1:.0f} → 2 pencere {m2:.0f} MB; ana {ana1} → {ana2}; "
              f"2. açılış {sure2:.1f} sn; pencereler {kimlik(r1)} {kimlik(r2)}")
        kontrol("2. open firefox → Ctrl+N ile aynı süreçte yeni pencere, süreç ağacı tek, toplam bellek < 2 örnek",
                r1.get("status") == "opened" and r2.get("status") == "opened" and kimlik(r1) != kimlik(r2) and
                len(ana1) == 1 and ana2 == ana1 and not ana_surecler("firefox", k2) and
                (m2 - m0) < 2 * (m1 - m0), f"{r1} {r2} ana {ana1}/{ana2} MB {m0:.0f}/{m1:.0f}/{m2:.0f}")
        # DH-TUR2: Chromium da kaydedilir (bellek bekçisi onu da yeniden başlatır); burada yalnız Firefox kayıtları
        kayit1, kayit2 = ([g for g in k_ if bellek_bekcisi.tarayici_turu(g.get("argv")) == "firefox"]
                          for k_ in (kayit1, kayit2))
        kontrol("ikinci pencere F1 kaydında (tek Firefox kaydı, ilk kopya, aynı süreç; 2. kopya silindi)",
                len(kayit2) == 1 and kayit2 == kayit1 and os.path.realpath(kayit2[0]["kopya"]) == os.path.realpath(k1)
                and bellek_bekcisi.firefox_ana_pidleri(d["cgroup"], k1) == ana2 and not os.path.exists(k2),
                f"{kayit1} → {kayit2}; k2 var: {os.path.exists(k2)}")
        with api.hedef("sanal"):
            b1_, b2_ = au.baslik(kimlik(r1)), au.baslik(kimlik(r2))
        kontrol("R2 KWin: 2. open firefox + URL → doğrulanan yeni pencere döndü, adres doğrulandı (sayfa F3R2-IKI), "
                "ilk pencere değişmedi",
                r2.get("status") == "opened" and r2.get("same_process") is True and "F3R2-IKI" in b2_ and
                "F3R2-BIR" in b1_, f"{r2} | 1: {b1_!r} 2: {b2_!r}")
        for p_ in ana2 + ana_surecler("firefox", sahte_kp):
            os.kill(p_, 15)
        time.sleep(3)
    else:
        print("C) firefox yok: Firefox 2. pencere atlandı")

    def chromium_analari():
        """Kopya kökünde --user-data-dir'li bütün ANA Chromium süreçleri (B'nin (3) kopyalı örneği dahil)."""
        from deskhand.oturum import politika
        kok_ = os.path.realpath(politika.kopya_dizini())
        out = []
        for pid in bellek_bekcisi._kafes_pidleri(d["cgroup"]):
            a = bellek_bekcisi._argv(pid)
            a = " ".join(a).split() if a and " " in a[0] else a
            if a and "chrom" in os.path.basename(a[0]) and not any(x.startswith("--type=") for x in a) and any(
                    x.startswith("--user-data-dir=") and os.path.dirname(os.path.realpath(x.split("=", 1)[1])) == kok_
                    for x in a):
                out.append(pid)
        return out

    ana0 = chromium_analari()
    h1 = chromium.on_karari(_on(["chromium"]))
    r1 = ac([*h1.argv, sayfa("cr-bir")], "Chromium", h1.kopya_yolu)
    time.sleep(3)
    ana1 = chromium_analari()
    h2 = chromium.on_karari(_on(["chromium"]))
    r2 = ac([*h2.argv, sayfa("cr-iki")], "Chromium", h2.kopya_yolu)
    time.sleep(3)
    ana2 = chromium_analari()
    print(f"   chromium: kopyalı ana süreçler {ana1} → {ana2}; pencereler {kimlik(r1)} {kimlik(r2)}")
    kontrol("2. open chromium → Ctrl+N ile aynı süreçte yeni pencere (kopyalı ana süreç sayısı artmadı, 2. kopya silindi)",
            r1.get("status") == "opened" and r2.get("status") == "opened" and kimlik(r1) != kimlik(r2) and
            len(ana1) <= len(ana0) + 1 and ana2 == ana1 and not os.path.exists(h2.kopya_yolu),
            f"{r1} {r2} ana {ana0}/{ana1}/{ana2}")
    agac = {"items": []}
    bitis = time.monotonic() + 20
    while time.monotonic() < bitis and not agac["items"]:
        try:
            with api.hedef("sanal"):
                agac = api.agac_oku(kimlik(r1), hepsi=True)
        except Dur as e:
            agac = {"items": [], "hata": e.mesaj}
        time.sleep(1)
    roller = sorted({o["role"] for o in agac["items"]})
    print(f"   chromium a11y: {len(agac['items'])} öge, roller {roller[:8]}")
    kontrol("chromium a11y ağacı available (AT-SPI ögeleri okunuyor)", len(agac["items"]) > 0, str(agac)[:300])

    fp = subprocess.run(["flatpak", "info", "com.google.Chrome"], capture_output=True) if shutil.which("flatpak") \
        else None
    if fp is not None and fp.returncode == 0:
        t0 = time.monotonic()
        try:
            uygulama.oturum_hazirla("com.google.Chrome")
            e = None
        except Dur as x:
            e = x
        sure = time.monotonic() - t0
        print(f"   Flatpak Chrome (politika): {sure:.2f} sn, kod {e and e.kod}")
        kontrol("Flatpak Chrome: 30 sn içinde ayakta ya da kod 16 + neden (politika yolu)",
                e is not None and e.kod == 16 and "~/.var/app" in e.mesaj and sure < 30, repr(e and e.mesaj))
        t0 = time.monotonic()
        try:
            ac(["flatpak", "run", "com.google.Chrome", "about:blank"], "Chrome", None)
            e = None
        except Dur as x:
            e = x
        sure = time.monotonic() - t0
        print(f"   Flatpak Chrome (başlatma): {sure:.2f} sn, kod {e and e.kod}")
        kontrol("Flatpak Chrome: 30 sn içinde ayakta ya da kod 16 + neden (başlatma yolu; hiçbir süreç başlamadı)",
                e is not None and e.kod == 16 and "chromium" in e.mesaj and sure < 30 and
                not any("com.google.Chrome" in " ".join(bellek_bekcisi._argv(p_))
                        for p_ in bellek_bekcisi._kafes_pidleri(d["cgroup"])), repr(e and e.mesaj))
    else:
        print("C) Flatpak Chrome kurulu değil: atlandı")
finally:
    masaustu.masaustu_durdur()

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
