"""Denetim 12c (bwrap ad alanı katmanı) — REGRESYON testi: denetimin kaçışları (docs/denetim/12c/: denetim12b_aygit,
denetim12b_path, denetim12b_kacis + ad alanı içi ic_kacis/ic_aygit → tests/yardimci/ic_kacis.py) düzeltmeden sonra
HEPSİ başarısız olmalı. Arka plan masaüstü türü DESKHAND_ARKA_TUR'a göre (iki türle de koşulur: kwin, xvfb).

Y1 /dev: uinput, input, snd, hidraw, usb, video YOK; yalnız /dev/dri.
Y2 araçlar PATH'ten değil güvenli mutlak yoldan (sahte `bwrap` PATH'in başında olsa da yalıtım sürer).
Y3 ayrı PID ad alanı: ana makine süreçleri görünmez; kill/ptrace/environ/proc-root erişimi yok.
HOME geçici katman: autostart/.local/bin/systemd/.bashrc yazılanlar oturumla ATILIR; veri klasörleri gerçek yazılır;
   veri klasörü içindeki gizli dizinler (.git/hooks, .vscode) salt okunur; gizli/ev kökü girdisi yazılabilir bağlanmaz.
Y4 /tmp boş (yalnız kendi X soketi), ev dizinindeki FIFO/soketler maskeli.
Y5 Flatpak örneği ad alanında masaüstünün kafesinde kalır; ana makine kaydı yazılmaz (çalışma zamanı kuruluysa).
Y6 bağlanan kopya yalnız politikanın verdiği (komut satırında başka kopya geçse de görünmez).
Y7 karşı taraf doğrulaması önbelleği; K4 gevşek izinli RUNTIME_DIR reddedilir; O3 bekçi "kesin ölü" ayrımı.

Gerçek ev dizini KULLANILMAZ: testler sahte ev dizini (arka_ortak._EV_ZORLA, süreç içi) kurar. Kullanıcının gerçek
oturumuna bağlantı/girdi yok.   Çalıştır:  DESKHAND_ARKA_TUR=kwin python3 tests/test_denetim12c.py"""
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time

import _yalitim  # noqa: F401

from deskhand import arka_ortak as ao, masaustu, oncelik_bekcisi, yollar  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

KOK = _yalitim.KOK
G = _yalitim.GECICI
IC = os.path.join(KOK, "tests", "yardimci", "ic_kacis.py")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod
    return None


RT = yollar.runtime_dir()
os.makedirs(RT, mode=0o700, exist_ok=True)

# ---------------------------------------------------------------- Y2: güvenli araç yolları (süreçsiz)
print("Y2) güvenli araç yolları")
SAHTE = tempfile.mkdtemp(prefix="dh12c-bin-", dir=G)
IZ = os.path.join(SAHTE, "iz.txt")
for ad_ in ("bwrap", "nice", "ionice", "sh", "busctl", "systemd-run", "kdotool", "find"):
    with open(os.path.join(SAHTE, ad_), "w") as f:
        f.write(f'#!/bin/sh\necho "sahte {ad_}" >> {IZ}\nwhile [ "$1" != "--" ] && [ $# -gt 0 ]; do shift; done; '
                'shift; exec "$@"\n')
    os.chmod(os.path.join(SAHTE, ad_), 0o755)
ESKI_PATH = os.environ["PATH"]
os.environ["PATH"] = SAHTE + ":" + ESKI_PATH  # denetimin saldırısı: PATH'in başında yazılabilir dizin
ao._ARAC_ONBELLEK.clear()
for ad_ in ("bwrap", "nice", "ionice", "sh", "busctl", "systemd-run"):
    y_ = ao.arac(ad_)
    kontrol(f"arac({ad_}) PATH'teki sahteyi değil güvenli dizindekini seçer", y_.startswith(("/usr/bin/", "/bin/")), y_)
kontrol("güvensiz dosya (kullanıcıya ait) güvenli sayılmaz", not ao.guvenli_yol(os.path.join(SAHTE, "bwrap")))
bag = os.path.join(SAHTE, "bag")
os.symlink("/usr/bin/true", bag)
kontrol("kullanıcı dizinindeki bağ (root dosyaya da gösterse) güvenli sayılmaz", not ao.guvenli_yol(bag))
kontrol("mutlak olmayan / bilinmeyen araç → Dur 9", dur_kodu(ao.arac, "dh12c-yok-boyle-arac") == 9 and
        dur_kodu(ao.arac, "../bin/sh") == 9)
argv_ = ao.korumali_argv(["/usr/bin/true"], RT, [])
kontrol("korumali_argv: bwrap mutlak + ayrı kullanıcı/PID ad alanı + salt okunur kök + asgari /dev + kendi /proc",
        argv_[0] == "/usr/bin/bwrap" and "--unshare-user" in argv_ and "--unshare-pid" in argv_ and
        argv_[argv_.index("--ro-bind"):argv_.index("--ro-bind") + 3] == ["--ro-bind", "/", "/"] and
        ["--dev", "/dev"] == argv_[argv_.index("--dev"):argv_.index("--dev") + 2] and "--proc" in argv_ and
        "--dev-bind" not in argv_[:argv_.index("--dev")], " ".join(argv_[:12]))
kontrol("korumali_argv: --dev-bind yalnız /dev/dri", all(argv_[i + 1] == "/dev/dri" for i, x in enumerate(argv_)
                                                       if x == "--dev-bind"))
kontrol("korumali_argv: /tmp ve /run/user/UID boş tmpfs", ["--tmpfs", "/tmp"] in [argv_[i:i + 2] for i in range(len(argv_))]
        and ["--tmpfs", f"/run/user/{os.getuid()}"] in [argv_[i:i + 2] for i in range(len(argv_))])
e_ = {"PATH": SAHTE + ":/usr/bin", "LD_PRELOAD": "/yok.so", "X": "1"}
argv_ = ao.korumali_argv(["true"], RT, [], e_)
kontrol("uygulamanın PATH/LD_PRELOAD'u yalnız son komuta (--setenv)",
        ["--setenv", "PATH", e_["PATH"]] == argv_[argv_.index("PATH") - 1:argv_.index("PATH") + 2] and
        "LD_PRELOAD" in argv_)

# ---------------------------------------------------------------- K4: gevşek izinli RUNTIME_DIR
print("\nK4) RUNTIME_DIR izinleri")
os.chmod(RT, 0o755)
kontrol("K4: 0755 RUNTIME_DIR → Dur 14 (sessizce sıkılaştırılmaz)", dur_kodu(ao.runtime_denetle, RT) == 14 and
        (os.stat(RT).st_mode & 0o777) == 0o755)
from deskhand import doktor  # noqa: E402
s_ = doktor.satir_calisma_dizini()
kontrol("K4: doctor gevşek izni gösterir (uyarı + chmod önerisi)", s_["durum"] == "uyari" and "chmod 700" in s_["oneri"],
        str(s_))
os.chmod(RT, 0o700)
kontrol("K4: 0700 → geçer, doctor tamam", dur_kodu(ao.runtime_denetle, RT) is None and
        doktor.satir_calisma_dizini()["durum"] == "tamam")

# ---------------------------------------------------------------- O3: bekçinin "kesin ölü" ayrımı
print("\nO3) öncelik bekçisi: kesin ölü")
uy = subprocess.Popen(["/usr/bin/sleep", "60"])
bas = ao.surec_baslangic(uy.pid)
kontrol("O3: canlı süreç ölü sayılmaz", not oncelik_bekcisi.kesin_olu(uy.pid, bas))
kontrol("O3: başlangıç zamanı farklı → ölü (PID başkasına geçmiş)", oncelik_bekcisi.kesin_olu(uy.pid, "1"))
import builtins  # noqa: E402
_asil_open = builtins.open


def _gecici_hata(yol, *a, **k):
    if str(yol) == f"/proc/{uy.pid}/stat":
        raise PermissionError(13, "geçici")
    return _asil_open(yol, *a, **k)


builtins.open = _gecici_hata
try:
    kontrol("O3: /proc/<pid>/stat GEÇİCİ okunamıyor → ölü SAYILMAZ (canlı oturum kapanmaz)",
            not oncelik_bekcisi.kesin_olu(uy.pid, bas))
finally:
    builtins.open = _asil_open
uy.kill()
uy.wait()
kontrol("O3: süreç yok → kesin ölü", oncelik_bekcisi.kesin_olu(uy.pid, bas))

# ---------------------------------------------------------------- veri klasörleri (sahte ev)
print("\nHOME) sahte ev dizini")
EV = os.path.join(G, "ev")
for alt in (".config/autostart", ".local/bin", ".steam", ".gizli", "Indirilenler", "Belgeler/proje/.git/hooks",
            "Belgeler/proje/.vscode", "Resimler"):
    os.makedirs(os.path.join(EV, alt), exist_ok=True)
with open(os.path.join(EV, ".config/user-dirs.dirs"), "w") as f:
    f.write('XDG_DOWNLOAD_DIR="$HOME/Indirilenler"\nXDG_DOCUMENTS_DIR="$HOME/Belgeler"\nXDG_DESKTOP_DIR="$HOME"\n'
            'XDG_MUSIC_DIR="$HOME/.gizli"\nXDG_PICTURES_DIR="/"\nXDG_VIDEOS_DIR="$HOME/../disari"\n'
            'XDG_TEMPLATES_DIR="$HOME/Resimler"\n')
with open(os.path.join(EV, ".bashrc"), "w") as f:
    f.write("# sahte\n")
with open(os.path.join(EV, "Belgeler/proje/.git/config"), "w") as f:
    f.write("[core]\n")
os.mkfifo(os.path.join(EV, ".steam/steam.pipe"))
ao._EV_ZORLA = EV
vk = ao.veri_klasorleri()
kontrol("veri klasörleri: yalnız ev İÇİNDEKİ, gizli olmayan klasörler (ev kökü, .gizli, /, ../ dışarı reddedilir)",
        vk == [os.path.join(EV, "Indirilenler"), os.path.join(EV, "Belgeler"), os.path.join(EV, "Resimler")], str(vk))
a_, bilgi = ao.ev_baglari()
kontrol("ev katmanı (overlayfs, kullanıcı ad alanında) kuruluyor", bilgi["katman"], str(bilgi))
kontrol("veri klasörü içindeki gizli girdiler (.git, .vscode) salt okunur örtülür; steam.pipe maskeli",
        bilgi["nokta"] == 2 and bilgi["maske"] >= 1, str(bilgi))
# veri klasöründe dinleyen soket (ana makinede): ad alanından bağlanılamamalı
gelen = []
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(os.path.join(EV, "Belgeler/proje/dinle.sock"))
srv.listen(4)
threading.Thread(target=lambda: gelen.append(srv.accept()), daemon=True).start()
# /tmp'de dinleyen soket (Steam/Chromium SingletonSocket, ICE rolünde)
tmp_soket = tempfile.mktemp(prefix="dh12c-", suffix=".sock", dir="/tmp")
srv2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv2.bind(tmp_soket)
srv2.listen(4)
threading.Thread(target=lambda: gelen.append(srv2.accept()), daemon=True).start()
# steam.pipe okuyucusu (ana makine): ad alanından yazılan HİÇBİR ŞEY gelmemeli
pipe_okunan = []


def pipe_oku():
    fd = os.open(os.path.join(EV, ".steam/steam.pipe"), os.O_RDONLY | os.O_NONBLOCK)
    bitis = time.monotonic() + 30
    while time.monotonic() < bitis and not pipe_bitir:
        try:
            v = os.read(fd, 64)
            if v:
                pipe_okunan.append(v)
        except BlockingIOError:
            pass
        time.sleep(0.05)
    os.close(fd)


pipe_bitir = False
threading.Thread(target=pipe_oku, daemon=True).start()
bashrc0 = open(os.path.join(EV, ".bashrc")).read()
gitcfg0 = open(os.path.join(EV, "Belgeler/proje/.git/config")).read()
gercek_ev = os.path.realpath(os.path.expanduser("~"))

# ---------------------------------------------------------------- canlı: arka plan masaüstü
from deskhand.oturum import politika  # noqa: E402
KOPYA = politika.kopya_dizini()
os.makedirs(KOPYA, mode=0o700, exist_ok=True)
kA, kB = os.path.join(KOPYA, "firefox-dh12cA"), os.path.join(KOPYA, "chromium-dh12cB")
for k_, ad_ in ((kA, "A"), (kB, "B")):
    os.makedirs(k_, mode=0o700, exist_ok=True)
    with open(os.path.join(k_, "gizli-cerez.txt"), "w") as f:
        f.write(ad_)

uyku = subprocess.Popen(["/usr/bin/sleep", "300"], env={"PATH": "/usr/bin", "SIR": "gizli-deger"})
d = masaustu.masaustu_baslat("800x600")
TUR = masaustu.tur(d)
print(f"\ncanlı ({TUR})")
try:
    sunucu = d["pid"].get("kwin") or d["pid"].get("xvfb")
    ana = [os.getpid(), uyku.pid, sunucu, d["pid"]["dbus"]]
    ad = f"{os.getpid()}{int(time.time()) % 100000}"
    yap = {"ev": EV, "uyku": uyku.pid, "ana": ana, "rt": os.path.realpath(RT), "tmp_soket": tmp_soket, "ad": ad,
           "gercek_ev": gercek_ev, "kopya_kok": KOPYA, "kopya_ben": kA, "kopya_oteki": kB}
    t = time.monotonic()
    # Y6: komut satırında B'nin kopyası GEÇİYOR ama politika A'yı verdi → yalnız A bağlanır
    p = masaustu.baslat([sys.executable, "-I", IC, json.dumps(yap), f"--user-data-dir={kB}"],
                        {"HOME": EV}, kopya=kA, stdout=subprocess.PIPE)
    out, _e = p.communicate(timeout=60)
    sure_ = time.monotonic() - t
    ic = json.loads(out.decode().strip().splitlines()[-1])
    print(f"  (başlatma + sonda {sure_:.2f} sn)")
    time.sleep(0.3)
    # Y1
    a_ = ic["aygit"]
    kontrol(f"Y1 ({TUR}): /dev/uinput, input, snd, hidraw, usb, video düğümü YOK",
            all(a_[k] == 0 for k in a_ if k != "/dev/dri/renderD*"), str(a_))
    kontrol(f"Y1 ({TUR}): /dev/uinput açılamaz", ic["uinput_acildi"] in ("ENOENT", "EACCES"), str(ic["uinput_acildi"]))
    kontrol(f"Y1 ({TUR}): GPU render düğümü var (/dev/dri)", a_["/dev/dri/renderD*"] >= 1 or not os.path.isdir("/dev/dri"))
    # Y3
    kontrol(f"Y3 ({TUR}): ana makine PID'leri görünmez (/proc'ta yalnız ad alanı süreçleri)",
            not ic["ana_gorunur"] and max(ic["proc_pidler"]) < 100, f"{ic['ana_gorunur']} {ic['proc_pidler'][:10]}")
    kontrol(f"Y3 ({TUR}): ana makine süreçlerine (test, sleep, ekran sunucusu, dbus) sinyal gönderilemez (ESRCH)",
            all(v in ("ESRCH", "EPERM") for v in ic["kill0"].values()) and ic["uyku_sigterm"] in ("ESRCH", "EPERM"),
            str(ic["kill0"]) + " " + str(ic["uyku_sigterm"]))
    kontrol(f"Y3 ({TUR}): testin sleep'i yaşıyor", uyku.poll() is None)
    kontrol(f"Y3 ({TUR}): ptrace/environ/proc-root ile ana makineye erişilemez",
            ic["ptrace"] in ("ESRCH", "EPERM") and ic["uyku_environ"] in ("ENOENT", "EACCES", "ESRCH") and
            isinstance(ic["proc_root_rt"], str), f"{ic['ptrace']} {ic['uyku_environ']} {ic['proc_root_rt']}")
    # Y4
    beklenen_x = [f"X{d['no']}"] if TUR == "xvfb" else ([f"X{d['x_ana']}"] if d.get("x_ana") is not None else [])
    kontrol(f"Y4 ({TUR}): /tmp boş tmpfs (test soketi, ICE yok; yalnız bağlanan oturum yolları)",
            not ic["tmp_soket_var"] and not ic["ice"] and not ic["gercek_bus"] and
            set(ic["tmp"]) <= {".X11-unix", os.path.relpath(G, "/tmp").split("/")[0]}, str(ic["tmp"]))
    kontrol(f"Y4 ({TUR}): ev dizinindeki FIFO (steam.pipe) maskeli; ana makineye hiçbir şey gitmedi",
            ic["steam_pipe"] != "YAZILDI" or not pipe_okunan, f"{ic['steam_pipe']} {pipe_okunan}")
    kontrol(f"Y4 ({TUR}): veri klasöründeki / /tmp'deki dinleyen sokete bağlanılamaz",
            ic["veri_soketi"] != "BAĞLANDI" and not gelen, f"{ic['veri_soketi']} {gelen}")
    # HOME
    y_ = ic["yaz"]
    kontrol(f"HOME ({TUR}): ad alanında yazma başarılı görünür (katman) — autostart/.local/bin/systemd/.bashrc/ev kökü",
            all(y_[k] == "YAZILDI" for k in ("autostart", "local_bin", "systemd", "bashrc", "ev_kok")), str(y_))
    kontrol(f"HOME ({TUR}): ...ama GERÇEK ev dizininde YOK (kalıcılık kaçışı kapalı)",
            not os.path.exists(os.path.join(EV, ".config/autostart", f"dh12c-{ad}.desktop")) and
            not os.path.exists(os.path.join(EV, ".local/bin/bwrap")) and
            not os.path.exists(os.path.join(EV, ".config/systemd")) and
            not os.path.exists(os.path.join(EV, f"dh12c-{ad}.txt")) and
            open(os.path.join(EV, ".bashrc")).read() == bashrc0)
    kontrol(f"HOME ({TUR}): veri klasörüne (İndirilenler, Belgeler) yazılanlar GERÇEKTEN yazıldı",
            y_["indir"] == "YAZILDI" and y_["proje"] == "YAZILDI" and
            os.path.isfile(os.path.join(EV, "Indirilenler", f"dh12c-{ad}.txt")) and
            os.path.isfile(os.path.join(EV, "Belgeler/proje", f"normal-{ad}.txt")), str(y_))
    kontrol(f"HOME ({TUR}): veri klasörü içindeki .git/hooks, .git/config, .vscode SALT OKUNUR (EROFS)",
            y_["git_hook"] == "EROFS" and y_["git_config"] == "EROFS" and y_["vscode"] == "EROFS" and
            not os.path.exists(os.path.join(EV, "Belgeler/proje/.git/hooks/pre-commit")) and
            open(os.path.join(EV, "Belgeler/proje/.git/config")).read() == gitcfg0, str(y_))
    kontrol(f"HOME ({TUR}): gizli 'veri klasörü' (.gizli) gerçekte yazılmadı",
            not os.path.exists(os.path.join(EV, ".gizli", f"dh12c-{ad}.txt")))
    kontrol(f"HOME ({TUR}): ad alanında görünen gerçek ev dizini de salt okunur (sahte ev dışında)",
            y_["gercek_ev_config"] in ("EROFS", "EACCES") and
            not os.path.exists(os.path.join(gercek_ev, ".config", f"dh12c-{ad}.tmp")), y_["gercek_ev_config"])
    # Y6
    kontrol(f"Y6 ({TUR}): politikanın verdiği kopya görünür, komut satırında geçen BAŞKA kopya görünmez",
            ic["kopya_ben"] and not ic["kopya_oteki"] and ic["kopya_kok"] == ["firefox-dh12cA"], str(ic["kopya_kok"]))
    kontrol(f"Y6 ({TUR}): kopya kökünün dışındaki yol kopya olarak verilemez (Dur 14)",
            dur_kodu(masaustu.baslat, ["/usr/bin/true"], None, kopya=EV) == 14)

    # Y2 canlı: sahte bwrap/nice/sh PATH'in başında → yalıtım sürüyor, sahteler hiç çalışmadı
    p = masaustu.baslat([sys.executable, "-I", "-c", "import os,json;print(json.dumps([os.path.exists('/run/user/%d/bus' "
                         "% os.getuid()), len([x for x in os.listdir('/proc') if x.isdigit()])]))"],
                        stdout=subprocess.PIPE)
    o2 = json.loads(p.communicate(timeout=30)[0].decode().strip().splitlines()[-1])
    kontrol(f"Y2 ({TUR}): PATH'in başında sahte bwrap/nice/sh varken yalıtım sürüyor (gerçek veri yolu yok, ayrı PID)",
            o2[0] is False and o2[1] < 10, str(o2))
    kontrol(f"Y2 ({TUR}): sahte araçların hiçbiri çalışmadı", not os.path.exists(IZ),
            open(IZ).read() if os.path.exists(IZ) else "")

    # Y5: Flatpak örneği ad alanında kafeste kalır, ana makine kaydı yazılmaz
    kayit = politika.flatpak_kayit()
    rt_ok = subprocess.run(["/usr/bin/flatpak", "info", "--system", "org.freedesktop.Platform//25.08"],
                           capture_output=True).returncode == 0 if os.path.exists("/usr/bin/flatpak") else False
    if rt_ok:
        from deskhand.oturum import flatpak_ornek
        argv_f = flatpak_ornek.sarmala(["/usr/bin/flatpak", "run", "--system", "--command=sleep",
                                        "org.freedesktop.Platform//25.08", "120"], "org.freedesktop.Platform", kayit,
                                       "4G", None, sure=15)
        # flatpak run ev dizinine (~/.var, ~/.local/share/flatpak) yazar: sahte ev (salt okunur gerçek ev) değil,
        # gerçek ev dizini + geçici katman (yazılanlar atılır)
        ao._EV_ZORLA = None
        pf = masaustu.baslat(argv_f, stderr=subprocess.PIPE)
        ao._EV_ZORLA = EV
        cg = masaustu.guvenli_kayit(d).get("cgroup") or d.get("cgroup")

        def flatpak_uyku():
            for p_ in ao._kafes_surecleri(cg):
                k_ = ao._komut_satiri(p_)
                if k_[:2] == ["sleep", "120"] or k_[:2] == ["/usr/bin/sleep", "120"]:
                    return p_
            return None
        bitis = time.monotonic() + 30
        fp = None
        while time.monotonic() < bitis and not fp:
            fp = flatpak_uyku()
            time.sleep(0.2)
        kontrol(f"Y5 ({TUR}): Flatpak (sistem çalışma zamanı) ad alanında açıldı ve masaüstünün KAFESİNDE kaldı",
                bool(fp) and ao._cgroup(fp) == cg, f"{fp} {cg}")
        time.sleep(1.0)
        kontrol(f"Y5 ({TUR}): sarmalayıcı ana makine kaydını yazmadı / EBUSY yok", not os.path.exists(kayit) and
                pf.poll() is None, f"{os.path.exists(kayit)} {pf.poll()}")
    else:
        print("ATLANDI  Y5: org.freedesktop.Platform//25.08 (sistem) kurulu değil")
        fp = None

    # Y7: karşı taraf doğrulaması önbelleği (KWin türü)
    if TUR == "kwin":
        from deskhand import kwin_oturum as ko
        g = ko.guvenli_kayit(d)
        ko._KARSI_ONBELLEK.clear()
        t = time.perf_counter()
        ko._karsi_denetle(g)
        ilk = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        for _i in range(20):
            ko._karsi_denetle(g)
        sonra = (time.perf_counter() - t) * 1000 / 20
        kontrol(f"Y7: önbellekli doğrulama hızlı (ilk {ilk:.2f} ms, sonra {sonra:.3f} ms)", sonra < ilk / 3,
                f"{ilk} {sonra}")
        sahte = {**g, "pid": {**g["pid"], "dbus": os.getpid()}}
        kontrol("Y7: PID değişince önbellek kullanılmaz (Dur 14)", dur_kodu(ko._karsi_denetle, sahte) == 14)
finally:
    masaustu.masaustu_durdur()
    pipe_bitir = True
if fp:
    time.sleep(0.5)
    kontrol(f"Y5 ({TUR}): masaüstü kapanınca Flatpak örneği de kapandı", not ao._canli(fp))
kontrol(f"kapanış ({TUR}): sahte ev dizinine kalıcı bir şey yazılmadı (autostart boş, .local/bin boş)",
        os.listdir(os.path.join(EV, ".config/autostart")) == [] and os.listdir(os.path.join(EV, ".local/bin")) == [])
kontrol(f"kapanış ({TUR}): gerçek ~/.config'te testin dosyası yok",
        not os.path.exists(os.path.join(gercek_ev, ".config", f"dh12c-{ad}.tmp")))
uyku.kill()
uyku.wait()
srv.close()
srv2.close()
os.unlink(tmp_soket)
os.environ["PATH"] = ESKI_PATH
ao._EV_ZORLA = None
print(f"\n{gecen}/{toplam} denetim 12c regresyon testi geçti")
sys.exit(0 if gecen == toplam else 1)
