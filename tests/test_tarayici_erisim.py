import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

# Tarayıcıda erişilebilirlik ağacı (H2): ön planda (kde) da Chromium bayrağı / Firefox GNOME_ACCESSIBILITY=1 ile
# başlatma; ağaç okunamazsa observe sonucunda açık `tree` durumu (available/reason/fix) ve kesilmeyen ipucu; çalışan ama
# AT-SPI'ya bağlı olmayan tarayıcı için doctor uyarısı. Hiçbir gerçek uygulama başlatılmaz (sahte arka uç), gerçek /proc
# yerine sahte ağaç; sahte HOME altında hiçbir dosya yazılmaz (sha1 önce/sonra).
#
# Çalıştır:  python3 tests/test_tarayici_erisim.py
import hashlib
import os
import sys
import tempfile

from deskhand import api, doktor, guvenlik, uygulama  # noqa: E402
from deskhand import mcp_sunucu as s  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


# ---------------------------------------------------------------- sahte HOME (gerçek profil/ortam dosyası taklidi)
EV = tempfile.mkdtemp(prefix="ev-", dir=_yalitim.GECICI)
for yol, icerik in ((".mozilla/firefox/profiles.ini", "[Profile0]\nName=default\nPath=abc.default\n"),
                    (".mozilla/firefox/abc.default/prefs.js", 'user_pref("a", 1);\n'),
                    (".config/environment.d/10-ornek.conf", "FOO=1\n"),
                    (".config/chromium/Default/Preferences", "{}\n")):
    tam = os.path.join(EV, yol)
    os.makedirs(os.path.dirname(tam), exist_ok=True)
    with open(tam, "w") as f:
        f.write(icerik)
os.environ["HOME"] = EV


def ev_ozeti():
    sonuc = {}
    for kok, dizinler, dosyalar in os.walk(EV):
        for d in dizinler:
            sonuc[os.path.relpath(os.path.join(kok, d), EV) + "/"] = ""
        for f in dosyalar:
            p = os.path.join(kok, f)
            with open(p, "rb") as fp:
                sonuc[os.path.relpath(p, EV)] = hashlib.sha1(fp.read()).hexdigest()
    return sonuc


EV_ONCE = ev_ozeti()

# ---------------------------------------------------------------- 1. ön planda (kde) başlatma: bayrak + ortam
DT = os.path.join(_yalitim.GECICI, "uyg")
os.makedirs(DT, exist_ok=True)
for ad, exec_ in (("vivaldi", "/usr/bin/vivaldi-stable %U"), ("firefox", "/usr/lib/firefox/firefox %u"),
                  ("okur", "/usr/bin/okular %U")):
    with open(os.path.join(DT, f"{ad}.desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={ad}\nExec={exec_}\n")


class OnPlanAU:
    ad = "kde"

    def kimlikler(self):
        return []


baslatilan = []
asil = (api.arka, uygulama.tum_pencereler, uygulama.onayli_program_denetle, uygulama._baslat,
        guvenlik.baslatma_yasak_denetle, guvenlik.baslatma_komut_engel)
api.arka = lambda: OnPlanAU()
uygulama.tum_pencereler = lambda: set()
uygulama.onayli_program_denetle = lambda: None
uygulama._baslat = lambda au, argv, fp, env=None, kopya=None, girdi=None, ev=(): baslatilan.append((list(argv), env))
guvenlik.baslatma_yasak_denetle = lambda *a, **k: None
guvenlik.baslatma_komut_engel = lambda *a, **k: None


def ac(argv, env=None):
    baslatilan.clear()
    try:
        api.uygulama_ac(argv, "deneme", [], env=env, sure=0)
    except Dur as e:
        return None, f"Dur {e.kod}: {e.mesaj}"
    return (baslatilan[-1] if baslatilan else None), ""


try:
    r, h = ac(["gio", "launch", os.path.join(DT, "vivaldi.desktop"), "https://ornek.test/"])
    kontrol("1a: ön planda chromium komutunda --force-renderer-accessibility",
            r is not None and r[0] == ["/usr/bin/vivaldi-stable", uygulama.ERISIM_BAYRAGI, "https://ornek.test/"],
            h or repr(r))
    r, h = ac(["gio", "launch", os.path.join(DT, "firefox.desktop")])
    kontrol("1b: ön planda firefox ortamında GNOME_ACCESSIBILITY=1",
            r is not None and (r[1] or {}).get("GNOME_ACCESSIBILITY") == "1"
            and r[0] == ["gio", "launch", os.path.join(DT, "firefox.desktop")], h or repr(r))
    r, h = ac(["/usr/bin/firefox", "--new-window"], env={"MOZ_X": "1"})
    kontrol("1c: doğrudan firefox komutu: politika ortamı korunur + GNOME_ACCESSIBILITY=1",
            r is not None and r[1] == {"MOZ_X": "1", "GNOME_ACCESSIBILITY": "1"}, h or repr(r))
    r, h = ac(["gio", "launch", os.path.join(DT, "okur.desktop")])
    kontrol("1d: tarayıcı olmayan uygulama: komut ve ortam aynen",
            r is not None and r[0] == ["gio", "launch", os.path.join(DT, "okur.desktop")] and not r[1], h or repr(r))
finally:
    (api.arka, uygulama.tum_pencereler, uygulama.onayli_program_denetle, uygulama._baslat,
     guvenlik.baslatma_yasak_denetle, guvenlik.baslatma_komut_engel) = asil

hz = getattr(uygulama, "erisim_hazirla", None)
kontrol("1e: erisim_hazirla (CLI ac ile ortak) Flatpak Firefox'u da tanır",
        hz is not None and (hz(["flatpak", "run", "org.mozilla.firefox"], None)[1] or {}).get("GNOME_ACCESSIBILITY") == "1")

# ---------------------------------------------------------------- 2. observe: ağaç durumu
UZUN = "uygulama ağaçta yok " + "x" * 400 + " SON-IPUCU"


class SahteWeb:
    ETKILESIMLI = set()

    @staticmethod
    def tarayici_mi(k):
        return True

    @staticmethod
    def hazirla(k):
        raise Dur(6, UZUN)


class SahteErisim:
    ETKILESIMLI = set()

    @staticmethod
    def erisim_ogeleri(k, ayrinti=True):
        return [], 0.0


asil_web, asil_erisim = s._web, s._erisim
s._web, s._erisim = (lambda: SahteWeb), (lambda: SahteErisim)
try:
    ogeler, kaynak, sayfa, notlar = s._agac_topla("0x1", False)
    durum = s.agac_durumu(kaynak, notlar) if hasattr(s, "agac_durumu") else None
    kontrol("2a: ağaç hatasında tree.available False ve fix dolu",
            isinstance(durum, dict) and durum.get("available") is False and bool(durum.get("fix"))
            and "GNOME_ACCESSIBILITY" in durum.get("fix", "") and "[6]" in durum.get("reason", ""), repr(durum))
    kontrol("2b: ipucu 200 karakterde kesilmiyor",
            any("SON-IPUCU" in n for n in notlar) and "SON-IPUCU" in (durum or {}).get("reason", ""), repr(notlar)[-200:])
    SahteWeb.tarayici_mi = staticmethod(lambda k: False)
    ogeler, kaynak, sayfa, notlar = s._agac_topla("0x1", False)
    durum = s.agac_durumu(kaynak, notlar) if hasattr(s, "agac_durumu") else None
    kontrol("2c: ağaç okunduğunda tree.available True, reason/fix boş",
            durum == {"available": True, "reason": "", "fix": ""}, repr(durum))
finally:
    s._web, s._erisim = asil_web, asil_erisim

# ---------------------------------------------------------------- 3. doctor: AT-SPI'ya bağlı olmayan çalışan tarayıcı
PROC = os.path.join(_yalitim.GECICI, "proc")


def surec(pid, comm, ppid, cgroup="0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-x.scope"):
    d = os.path.join(PROC, str(pid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "stat"), "w") as f:
        f.write(f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 4194560 0 0 0 0\n")
    with open(os.path.join(d, "cgroup"), "w") as f:
        f.write(cgroup + "\n")


surec(1, "systemd", 0)
surec(500, "firefox", 1)
surec(501, "Isolated Web Co", 500)
surec(600, "chromium", 1)
surec(601, "chromium", 600)
surec(700, "firefox", 1, cgroup="0::/user.slice/user-1000.slice/user@1000.service/deskhand-kwin-ab-12.scope")
surec(800, "kwrite", 1)

f = getattr(doktor, "satir_tarayici_erisim", None)
if f is None:
    kontrol("3: AT-SPI bağlantısı olmayan çalışan tarayıcı için doctor uyarısı", False, "satir_tarayici_erisim yok")
else:
    r = f(proc=PROC, bagli_pidler=lambda: {501})
    kontrol("3: AT-SPI bağlantısı olmayan çalışan tarayıcı için doctor uyarısı",
            r["durum"] == "uyari" and "600" in r["ayrinti"] and "500" not in r["ayrinti"] and "700" not in r["ayrinti"]
            and "GNOME_ACCESSIBILITY=1" in r["oneri"] and "environment.d" in r["oneri"], repr(r))
    r = f(proc=PROC, bagli_pidler=lambda: {500, 601})
    kontrol("3b: tüm tarayıcılar ağaçta → tamam (görünmez masaüstündeki tarayıcı sayılmaz)", r["durum"] == "tamam", repr(r))
    r = f(proc=PROC, bagli_pidler=lambda: None)
    kontrol("3c: erişilebilirlik veri yolu yok → çalışan tarayıcılar uyarı", r["durum"] == "uyari" and "500" in r["ayrinti"],
            repr(r))
    bos = os.path.join(_yalitim.GECICI, "proc-bos")
    os.makedirs(bos, exist_ok=True)
    r = f(proc=bos, bagli_pidler=lambda: set())
    kontrol("3d: çalışan tarayıcı yok → tamam", r["durum"] == "tamam", repr(r))
    kontrol("3e: doctor satırlarında yer alıyor", f in doktor.SATIRLAR)

# ---------------------------------------------------------------- 4. yazım yok
kontrol("4: sahte HOME altında hiçbir dosya yazılmadı (sha1 önce/sonra)", ev_ozeti() == EV_ONCE)

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
