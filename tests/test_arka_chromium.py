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
bet = ('for d in .config/chromium .config/vivaldi-snapshot; do p="$HOME/$d"; [ -d "$p/" ] && echo dizin:$d; '
       'ls -A "$p/" | sed "s|^|ic:$d:|"; echo YAZILDI > "$p/Yeni" && echo yazildi:$d; done; '
       f"cat {RT_HEDEF}/Cookies {TMP_HEDEF}/Cookies 2>&1; ls -A {RT_HEDEF} | sed 's/^/rt:/'")
r = ad_alani(bet)
cikti = r.stdout
kontrol("birim: ad alanında ~/.config/chromium ve ~/.config/vivaldi-snapshot çözülüyor (dizin) ve yazılabilir",
        "dizin:.config/chromium" in cikti and "dizin:.config/vivaldi-snapshot" in cikti and
        "yazildi:.config/chromium" in cikti and "yazildi:.config/vivaldi-snapshot" in cikti, cikti + r.stderr)
kontrol("birim: ad alanından GERÇEK psd dizini GÖRÜNMEZ (Cookies yok, sır okunmuyor)",
        "ic:.config/chromium:Cookies" not in cikti and "GIZLI-PSD" not in cikti and "rt:Cookies" not in cikti, cikti)
kontrol("birim: ad alanında yazılanlar ana makinedeki hedefe SIZMAZ; gerçek içerik değişmedi",
        sorted(os.listdir(RT_HEDEF)) == ["Cookies"] and sorted(os.listdir(TMP_HEDEF)) == ["Cookies"] and
        open(os.path.join(RT_HEDEF, "Cookies")).read() == "GIZLI-PSD-RT")
r2 = ad_alani('ls -A "$HOME/.config/chromium/" | wc -l')
kontrol("birim: başka bir başlatma önceki başlatmanın yazdığını görmez (ad alanına özel)", r2.stdout.strip() == "0",
        r2.stdout + r2.stderr)

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
                p.poll() is None and p.poll() != 133, f"çıkış {p.poll()}, günlük {log.name}")
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
finally:
    masaustu.masaustu_durdur()

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
