"""Arka planda Chromium ailesi çökmesi (crashpad `--database is required`, çıkış 133) regresyon testi.

Kök neden: ad alanında gizlenen ~/.config/chromium (profile-sync-daemon'da /run/user/UID altına giden sembolik bağ,
ad alanında boşta asılı kalır) → varsayılan yapılandırma dizini yazılamaz → crashpad veritabanı yolu boş. Düzeltme:
arka_ortak.chromium_ortami (uygulamanın kendi XDG_RUNTIME_DIR'i altında yazılabilir XDG_CONFIG_HOME).

A) birim: chromium_ortami yalnız Chromium/Electron ailesine, Flatpak'a dokunmaz.
B) GÖRÜNMEZ masaüstünde (DESKHAND_ARKA_TUR=kwin|xvfb) gerçek Chromium: (1) ham başlatma (MCP open_app'in politikasız
   `paylas` yolundaki hâl: profilsiz), (2) api.uygulama_ac (open_app'in son adımı; erişilebilirlik bayrağı eklenir),
   (3) oturum kopyası yolu: SAHTE profil kaynağından kopya + chromium_argv (kullanıcının gerçek profili KULLANILMAZ).
   Her biri 12 sn ayakta kalır, pencere "arka:" önekli, çıkış kodu 133 değil. Hedef her başta denetlenir (sanal).
Kullanıcının tarayıcı profillerine dokunulmaz; kullanıcının ekranına hiçbir pencere açılmaz.

Çalıştır:  python3 tests/test_arka_chromium.py"""
import atexit
import os
import shutil
import sys
import tempfile
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import api, arka_ortak, masaustu
from deskhand.arka_uc import sec
from deskhand.hata import Dur
from deskhand.oturum import chromium, kopya

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


# ---------------------------------------------------------------- A) birim
RT = "/rt/app"
e0 = {"XDG_RUNTIME_DIR": RT, "XDG_CONFIG_HOME": "/home/x/.config", "A": "1"}
ortak_dizin = tempfile.mkdtemp(prefix="deskhand-chr-birim-", dir=_yalitim.PAYLASIM)
e1 = {**e0, "XDG_RUNTIME_DIR": ortak_dizin}
r = arka_ortak.chromium_ortami(["/usr/bin/chromium", "--foo"], e1)
kontrol("birim: chromium → XDG_CONFIG_HOME uygulamanın runtime dizini altında (0700), kullanıcınınki ezildi",
        r["XDG_CONFIG_HOME"] == os.path.join(ortak_dizin, "xdg-yapilandirma") and
        os.path.isdir(r["XDG_CONFIG_HOME"]) and (os.stat(r["XDG_CONFIG_HOME"]).st_mode & 0o777) == 0o700 and
        r["A"] == "1" and e1["XDG_CONFIG_HOME"] == "/home/x/.config", str(r))
kontrol("birim: Electron (code) ve vivaldi de kapsanır",
        all("xdg-yapilandirma" in arka_ortak.chromium_ortami([a], e1)["XDG_CONFIG_HOME"]
            for a in ("/usr/bin/code", "vivaldi-stable", "/opt/electron43/electron")))
kontrol("birim: Chromium DEĞİLSE env aynen döner (firefox, kwrite)",
        arka_ortak.chromium_ortami(["/usr/bin/firefox"], e1) == e1 and
        arka_ortak.chromium_ortami(["kwrite", "x"], e1) == e1)
kontrol("birim: Flatpak komutu ve Deskhand'in Flatpak sarmalayıcısı değişmez",
        arka_ortak.chromium_ortami(["flatpak", "run", "com.discordapp.Discord"], e1) == e1 and
        arka_ortak.chromium_ortami(["python3", "/x/flatpak_ornek.py", "--", "discord"], e1) == e1)
kontrol("birim: XDG_RUNTIME_DIR yoksa / komut boşsa dokunulmaz",
        arka_ortak.chromium_ortami(["chromium"], {"A": "1"}) == {"A": "1"} and
        arka_ortak.chromium_ortami([], e1) == e1)

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
            f"çıkış {kod}, pencere {w}, günlük {log.name}")
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
finally:
    masaustu.masaustu_durdur()

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
