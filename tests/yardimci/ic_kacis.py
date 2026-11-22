"""Denetim 12c kaçış sondası: arka plan uygulamasının bwrap ad alanı İÇİNDE çalışır (tests/test_denetim12c.py başlatır).
Denetimin docs/denetim/12c/ic_kacis.py + ic_aygit.py betiklerinin birleşimi; sonuç JSON olarak stdout'a (ad alanında
/tmp boş tmpfs: dosyaya yazılan rapor ana makineye ulaşmazdı).

Kullanıcının gerçek oturumuna BAĞLANMAZ, girdi göndermez: aygıtlar yalnız os.access + /dev/uinput aç-kapat (aygıt
OLUŞTURULMAZ); sinyal/ptrace yalnız testin KENDİ `sleep` sürecine ve kill(0); yazmalar yalnız testin sahte ev
dizinine (argv) ve kendi oluşturduğu geçici adlara.

    python3 -I ic_kacis.py '<json yapılandırma>'
    yapılandırma: {"ev": sahte ev, "uyku": testin sleep PID'i, "ana": [ana makine PID'leri], "rt": RUNTIME_DIR,
                   "tmp_soket": /tmp'deki test soketi, "gercek_ev": gerçek ev dizini, "ad": benzersiz ek}
"""
import ctypes
import errno
import glob
import json
import os
import signal
import socket
import sys

y = json.loads(sys.argv[1])
ev, ad = y["ev"], y["ad"]
uid = os.getuid()
r = {}


def hata_adi(e):
    return errno.errorcode.get(e.errno, str(e.errno)) if isinstance(e, OSError) else str(e)


# ---- Y1 aygıtlar
r["aygit"] = {d: len(glob.glob(d)) for d in ("/dev/uinput", "/dev/input/*", "/dev/snd/*", "/dev/hidraw*",
                                               "/dev/bus/usb/*/*", "/dev/video*", "/dev/dri/renderD*")}
try:
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    os.close(fd)
    r["uinput_acildi"] = True
except OSError as e:
    r["uinput_acildi"] = hata_adi(e)

# ---- Y3 süreçler: ana makine PID'leri görünmez, sinyal/ptrace/proc erişimi yok
r["proc_pidler"] = sorted(int(x) for x in os.listdir("/proc") if x.isdigit())
r["ana_gorunur"] = [p for p in y["ana"] if os.path.exists(f"/proc/{p}")]
r["kill0"] = {}
for p in y["ana"]:
    try:
        os.kill(p, 0)
        r["kill0"][str(p)] = "İZİNLİ"
    except OSError as e:
        r["kill0"][str(p)] = hata_adi(e)
try:
    os.kill(y["uyku"], signal.SIGTERM)  # yalnız testin kendi sleep'i
    r["uyku_sigterm"] = "GÖNDERİLDİ"
except OSError as e:
    r["uyku_sigterm"] = hata_adi(e)
libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.restype = ctypes.c_long
rc = libc.ptrace(16, y["uyku"], None, None)  # PTRACE_ATTACH
r["ptrace"] = "BAŞARILI" if rc == 0 else errno.errorcode.get(ctypes.get_errno())
if rc == 0:
    libc.ptrace(17, y["uyku"], None, None)
try:
    r["uyku_environ"] = "SIR=" in open(f"/proc/{y['uyku']}/environ", "rb").read().decode(errors="replace")
except OSError as e:
    r["uyku_environ"] = hata_adi(e)
try:
    r["proc_root_rt"] = os.listdir(f"/proc/{y['ana'][0]}/root{y['rt']}")
except OSError as e:
    r["proc_root_rt"] = hata_adi(e)

# ---- Y4 IPC: /tmp boş, test soketi görünmez, gerçek runtime dizini boş
r["tmp"] = sorted(os.listdir("/tmp"))
r["tmp_soket_var"] = os.path.exists(y["tmp_soket"])
r["gercek_bus"] = os.path.exists(f"/run/user/{uid}/bus")
r["ice"] = os.path.exists("/tmp/.ICE-unix")

# ---- HOME: boş tmpfs + beyaz liste (yazılanlar atılır), veri klasörü yazılır, içindeki gizli dizin salt okunur


def yaz(yol, icerik="dh12c\n", kip="w"):
    try:
        os.makedirs(os.path.dirname(yol), exist_ok=True)
        with open(yol, kip) as f:
            f.write(icerik)
        return "YAZILDI"
    except OSError as e:
        return hata_adi(e)


r["yaz"] = {
    "autostart": yaz(os.path.join(ev, ".config/autostart", f"dh12c-{ad}.desktop"), "[Desktop Entry]\nExec=false\n"),
    "local_bin": yaz(os.path.join(ev, ".local/bin", "bwrap"), "#!/bin/sh\nexit 0\n"),
    "systemd": yaz(os.path.join(ev, ".config/systemd/user", f"dh12c-{ad}.service")),
    "bashrc": yaz(os.path.join(ev, ".bashrc"), "echo kacis\n", "a"),
    "indir": yaz(os.path.join(ev, "Indirilenler", f"dh12c-{ad}.txt")),
    "proje": yaz(os.path.join(ev, "Belgeler/proje", f"normal-{ad}.txt")),
    "git_hook": yaz(os.path.join(ev, "Belgeler/proje/.git/hooks/pre-commit"), "#!/bin/sh\necho kacis\n"),
    "git_config": yaz(os.path.join(ev, "Belgeler/proje/.git/config"), "[core]\n\tfsmonitor = kacis\n", "a"),
    "vscode": yaz(os.path.join(ev, "Belgeler/proje/.vscode/tasks.json"), "{}"),
    "gizli_veri": yaz(os.path.join(ev, ".gizli", f"dh12c-{ad}.txt")),
    "ev_kok": yaz(os.path.join(ev, f"dh12c-{ad}.txt")),
    "gercek_ev_config": yaz(os.path.join(y["gercek_ev"], ".config", f"dh12c-{ad}.tmp")),
}
# soket / FIFO maskeleri: steam.pipe (ev) ve veri klasöründeki soket
try:
    fd = os.open(os.path.join(ev, ".steam/steam.pipe"), os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, b"kacis\n")
    os.close(fd)
    r["steam_pipe"] = "YAZILDI"
except OSError as e:
    r["steam_pipe"] = hata_adi(e)
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    s.connect(os.path.join(ev, "Belgeler/proje/dinle.sock"))
    s.sendall(b"kacis\n")
    r["veri_soketi"] = "BAĞLANDI"
except OSError as e:
    r["veri_soketi"] = hata_adi(e)
finally:
    s.close()
# sır yolları: okunamamalı (dizin boş tmpfs, dosya /dev/null)
r["sir"] = {}
for y_ in y.get("sirlar", []):
    try:
        r["sir"][y_] = sorted(os.listdir(y_)) if os.path.isdir(y_) else open(y_, errors="replace").read()
    except OSError as e:
        r["sir"][y_] = hata_adi(e)
r["kopya_kok"] = sorted(os.listdir(y["kopya_kok"])) if y.get("kopya_kok") and os.path.isdir(y["kopya_kok"]) else None
for k in ("kopya_ben", "kopya_oteki"):
    if y.get(k):
        r[k] = os.path.exists(os.path.join(y[k], "gizli-cerez.txt"))
print(json.dumps(r, ensure_ascii=False))
