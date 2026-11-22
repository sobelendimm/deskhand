"""Arka plan masaüstlerinin (Xvfb: masaustu.py, yalıtık KWin: kwin_oturum.py) ORTAK iç yapı taşları.

Burada yalnız iki tür için AYNI olan güvenceler durur: süreç/kafes yardımcıları (bellek kafesi: systemd-run --user
--scope MemoryMax=…, nice 10 + ionice idle, kafese ALINDIKTAN SONRA exec eden kapı), boş ses çıkışı (null sink) ve
uygulama ortamının ses bölümü, özel D-Bus yapılandırması (standart servis dizinleri YOK), Xauthority yazımı.
Yaşam döngüsü ve ekran türüne özgü her şey masaustu.py / kwin_oturum.py içindedir. Bu modül ikisini de içe AKTARMAZ
(döngü yok); masaustu.py eski adları geriye uyumluluk için yeniden dışa aktarır.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from .hata import ARAC_EKSIK, Dur
from .i18n import _

SINK = "deskhand-sessiz"
VARSAYILAN_BELLEK = "4G"
VARSAYILAN_TAKAS = "0"  # kafes takasa taşmasın (DESKHAND_SANAL_TAKAS): sınırda kafes içinde OOM, sistem yavaşlamaz
# Özel veri yolunda etkinleştirilebilecek servisler (gerisi kapalı: kwalletd, kded, kdeconnect, plasma
# bildirimleri… ikinci örnekleri kullanıcının dosyalarını/oturumunu bozabilir).
IZINLI_SERVISLER = {"org.a11y.Bus": "/usr/lib/at-spi-bus-launcher"}
# Kullanıcının Wayland oturumuna ait, arka plan uygulamasına geçmemesi gereken değişkenler
SILINECEK_ORTAM = ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY", "DESKTOP_STARTUP_ID",
                   "XDG_ACTIVATION_TOKEN", "SESSION_MANAGER", "DBUS_SESSION_BUS_PID", "DBUS_STARTER_ADDRESS",
                   "DBUS_STARTER_BUS_TYPE", "GDK_SCALE", "QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS")
# Uygulama ortamından KESİN çıkarılanlar (os.environ'dan gelen değer de, çağıranın env'iyle verilen de: birleştirmeden
# SONRA ikinci kez uygulanır). Masaüstüne ait değerleri (özel veri yolu, ekran, ses) çağıran bunların ÜSTÜNE yazar.
# AT_SPI_BUS_ADDRESS: kullanıcının erişilebilirlik veri yolu (erisim.py süreç ortamına geçici koyar) asla geçmez;
# yalnız masaüstünün KENDİ kayıt defteri izinli_env ile alır. SSH_AUTH_SOCK/SSH_AGENT_PID: arka plan uygulaması
# kullanıcının SSH anahtarlarını kullanamaz. XDG_RUNTIME_DIR masaüstünün kendi klasörüne çevrilir (uygulama_runtime);
# HOME BİLEREK kullanıcınındır (uygulamalar kullanıcının dosyalarıyla çalışır; bkz. docs/ARCHITECTURE.md §4).
CIKARILACAK_ORTAM = frozenset({
    *SILINECEK_ORTAM, "DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS", "DISPLAY", "LIBEI_SOCKET", "EIS_SOCKET",
    "GNOME_KEYRING_CONTROL", "KDE_FULL_SESSION", "SSH_AUTH_SOCK", "SSH_AGENT_PID", "PULSE_SERVER", "PULSE_SINK",
    "PULSE_SOURCE", "PULSE_PROP", "PULSE_COOKIE", "PULSE_CLIENTCONFIG", "PULSE_RUNTIME_PATH",
})
CIKARILACAK_ONEKLER = ("PULSE_", "PIPEWIRE_", "IBUS_")
KULLANICI_A11Y = ("AT_SPI_BUS_ADDRESS",)
# Kafes kapısı: süreç kafese alınana dek bekler (borudan bir satır), sonra programı çalıştırır. Böylece
# erken çatallanan uygulamaların (tarayıcı içerik süreçleri) çocukları da kafesin içinde doğar.
# {fd}: kapı borusunun okuma ucu (pass_fds numarayı korur)
KAPI = 'read -r _ <&{fd} && exec {fd}<&- && exec "$@"'


# ---------------------------------------------------------------- süreçler

def _bekle(kosul, sure: float, aralik: float = 0.02) -> bool:
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if kosul():
            return True
        time.sleep(aralik)
    return bool(kosul())


def _canli(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    try:  # zombi = ölü
        with open(f"/proc/{int(pid)}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _komut_satiri(pid) -> list[str]:
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return [p.decode(errors="replace") for p in f.read().split(b"\0") if p]
    except (OSError, ValueError, TypeError):
        return []


def _cgroup(pid) -> str:
    try:
        with open(f"/proc/{int(pid)}/cgroup") as f:
            for satir in f:
                if satir.startswith("0::"):
                    return satir[3:].strip()
    except (OSError, ValueError, TypeError):
        pass
    return ""


def _kafes_surecleri(cg: str) -> list[int]:
    if not cg:
        return []
    try:
        with open(os.path.join("/sys/fs/cgroup", cg.lstrip("/"), "cgroup.procs")) as f:
            return [int(x) for x in f.read().split()]
    except OSError:
        return []


def _bellek_siniri() -> str | None:
    b = (os.environ.get("DESKHAND_SANAL_BELLEK") or VARSAYILAN_BELLEK).strip()
    return None if b.lower() in ("0", "yok", "none", "off") else b


def _takas_siniri() -> str:
    """Kafesin takas sınırı (MemorySwapMax). Varsayılan 0: bellek sınırında kafesin içinde OOM, takasa taşıp
    sistemi yavaşlatmaz. DESKHAND_SANAL_TAKAS=512M gibi; 'sinirsiz'/'infinity' = sınır yok."""
    t = (os.environ.get("DESKHAND_SANAL_TAKAS") or VARSAYILAN_TAKAS).strip()
    if t.lower() in ("sinirsiz", "sınırsız", "infinity", "yok", "none", "off"):
        return "infinity"
    if not re.fullmatch(r"\d+(\.\d+)?[KMGT%]?", t, re.I):
        raise Dur(1, _("DESKHAND_SANAL_TAKAS geçersiz: {deger} (ör. 0, 512M, 1G)").format(deger=repr(t)))
    return t


def _ortam_oku(pid) -> dict[str, str]:
    try:
        with open(f"/proc/{int(pid)}/environ", "rb") as f:
            ham = f.read()
    except (OSError, ValueError, TypeError):
        return {}
    e = {}
    for p in ham.split(b"\0"):
        k, ayrac, v = p.partition(b"=")
        if ayrac:
            e[k.decode(errors="replace")] = v.decode(errors="replace")
    return e


def _atalar() -> set[int]:
    """Bu süreç ve tüm ataları (kafes içinden çağrılan `masaustu durdur` kendini/kabuğunu öldürmesin)."""
    s, pid = set(), os.getpid()
    for _i in range(64):
        if pid <= 1 or pid in s:
            break
        s.add(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return s


def _isaretli_surecler(d: dict) -> list[int]:
    """Ortamında bu masaüstünün işareti olan süreçler (kafes kapalıyken ya da kafesten kaçan çocuklar için):
    DESKHAND_SANAL_KIMLIK (masaüstüne özgü rastgele), eski durum dosyalarında DESKHAND_SANAL + özel veri yolu adresi.
    Yalnız okunabilen (kendi) süreçler; bu süreç ve ataları hariç."""
    kimlik, ekran, bus = d.get("kimlik"), d.get("ekran"), d.get("dbus_adres")
    if not kimlik and not (ekran and bus):
        return []
    haric = _atalar()
    sonuc = []
    for ad in os.listdir("/proc"):
        if not ad.isdigit() or int(ad) in haric:
            continue
        e = _ortam_oku(ad)
        if not e:
            continue
        if kimlik:
            if e.get("DESKHAND_SANAL_KIMLIK") == kimlik:
                sonuc.append(int(ad))
        elif e.get("DESKHAND_SANAL") == ekran and e.get("DBUS_SESSION_BUS_ADDRESS") == bus:
            sonuc.append(int(ad))
    return sonuc


def _sinyal(pids, sig) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _satir_bekle(p: subprocess.Popen, sure: float) -> str:
    import select
    if p.stdout is None:
        return ""
    r, _w, _x = select.select([p.stdout], [], [], sure)
    if not r:
        return ""
    return p.stdout.readline().decode(errors="replace").strip()


def _gunluk_dosyasi(cdir: str, ad: str):
    return open(os.path.join(cdir, f"{ad}.log"), "ab")


# ---------------------------------------------------------------- bellek kafesi

def _kullanici_bus_ortami() -> dict:
    """systemd kullanıcı yöneticisine (kafes işlemleri) her zaman GERÇEK kullanıcı veri yolundan git:
    süreç sanal masaüstünün içinden çağrılsa bile (özel DBUS_SESSION_BUS_ADDRESS) doğru yer."""
    e = dict(os.environ)
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    e["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={rt}/bus"
    return e


def _kafese_al(kafes: str, pid: int) -> None:
    r = subprocess.run(["busctl", "--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                        "org.freedesktop.systemd1.Manager", "AttachProcessesToUnit", "ssau", kafes, "/", "1",
                        str(pid)], capture_output=True, text=True, env=_kullanici_bus_ortami(), timeout=5)
    if r.returncode != 0:
        raise Dur(ARAC_EKSIK, _("süreç bellek kafesine alınamadı ({kafes}): {hata}").format(kafes=kafes, hata=r.stderr.strip()))


def _oncelik() -> list[str]:
    """nice MUTLAK 10 (nice -n göreli: çağıran -4'teyse 6 olurdu) + ionice idle."""
    fark = 10 - os.getpriority(os.PRIO_PROCESS, 0)
    return [*(["nice", "-n", str(fark)] if fark > 0 else []), "ionice", "-c", "3"]


def kafeste_baslat(d: dict, argv: list[str], env: dict, pass_fds=(), **popen) -> subprocess.Popen:
    """argv'yi nice 10 + ionice idle ile, kafese ALINDIKTAN SONRA çalıştır (kapı borusu). pass_fds: süreçte açık
    kalacak ek dosya tanıtıcıları (XWayland soketleri)."""
    if not argv:
        raise Dur(1, _("başlatılacak komut boş"))
    tam = [*_oncelik(), *argv]
    kafes = d.get("kafes")
    if not kafes:  # kafes kapalı (DESKHAND_SANAL_BELLEK=0): yalnız öncelik
        return subprocess.Popen(tam, env=env, pass_fds=tuple(pass_fds), start_new_session=True, **popen)
    r, w = os.pipe()
    try:
        p = subprocess.Popen(["sh", "-c", KAPI.format(fd=r), "deskhand-kapi", *tam], env=env,
                             pass_fds=(r, *pass_fds), start_new_session=True, **popen)
    finally:
        os.close(r)
    try:
        _kafese_al(kafes, p.pid)
    except BaseException:
        os.close(w)
        p.kill()
        p.wait()
        raise
    os.write(w, b"\n")
    os.close(w)
    return p


# ---------------------------------------------------------------- ses (boş çıkış)

def _pactl(*a, timeout=5) -> subprocess.CompletedProcess | None:
    if not shutil.which("pactl"):
        return None
    try:
        return subprocess.run(["pactl", *a], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _sink_modulu(sink: str | None) -> int | None:
    """`sink_name=<sink>` ile yüklenmiş module-null-sink'in numarası (yoksa None)."""
    if not sink:
        return None
    r = _pactl("list", "short", "modules")
    if r is None or r.returncode != 0:
        return None
    for satir in r.stdout.splitlines():
        p = satir.split("\t")
        if len(p) >= 3 and p[1] == "module-null-sink" and f"sink_name={sink}" in p[2].split():
            try:
                return int(p[0])
            except ValueError:
                pass
    return None


def ses_kur(ek: str = "") -> tuple[dict | None, str | None]:
    """→ (ses bilgisi, uyarı). Her sanal masaüstünün KENDİ boş çıkışı var (deskhand-sessiz-<ekran no>): biri kapanınca
    öbürünün sesi varsayılan çıkışa (kullanıcının kulaklığına) düşmesin. Önceden kalmış aynı adlı çıkış kullanılır
    ama durdurmada KALDIRILMAZ (sahibi biz değiliz)."""
    if not shutil.which("pactl"):
        return None, _("pactl yok: arka plan sesi tamamen kapatıldı")
    sink = f"{SINK}-{ek}" if ek else SINK
    m = _sink_modulu(sink)
    if m is not None:
        return {"sink": sink, "modul": m, "onceden": True}, None
    r = _pactl("load-module", "module-null-sink", f"sink_name={sink}",
               "sink_properties=device.description=Deskhand-sessiz node.virtual=true priority.session=0 "
               "priority.driver=0 deskhand.sanal=1")
    if r is None or r.returncode != 0:
        return None, _("boş ses çıkışı kurulamadı ({hata}): arka plan sesi kapatıldı").format(
            hata=r.stderr.strip() if r else "")
    try:
        return {"sink": sink, "modul": int(r.stdout.strip()), "onceden": False}, None
    except ValueError:
        return {"sink": sink, "modul": _sink_modulu(sink), "onceden": False}, None


def ses_kaldir(ses: dict | None) -> str | None:
    if not ses or ses.get("modul") is None or ses.get("onceden"):
        return None  # önceden vardı: sahibi biz değiliz, başka bir masaüstü kullanıyor olabilir
    if _sink_modulu(ses.get("sink")) != ses["modul"]:
        return None  # zaten yok (ya da başka biri yeniden yükledi: dokunma)
    r = _pactl("unload-module", str(ses["modul"]))
    if r is None or r.returncode != 0:
        return _("ses modülü kaldırılamadı: {hata}").format(hata=r.stderr.strip() if r else _("pactl yok"))
    return None


def gercek_runtime() -> str:
    """Kullanıcının GERÇEK XDG_RUNTIME_DIR'i (ses sunucusu soketleri burada): /run/user/UID, yoksa ortamdaki."""
    rt = f"/run/user/{os.getuid()}"
    return rt if os.path.isdir(rt) else (os.environ.get("XDG_RUNTIME_DIR") or rt)


def uygulama_runtime(cdir: str) -> str:
    """Arka plan uygulamalarının XDG_RUNTIME_DIR'i: masaüstünün KENDİ klasörü (<çalışma>/run, 0700). Uygulamalar
    kullanıcının gerçek runtime dizinindeki soketleri (Wayland, veri yolu, erişilebilirlik…) varsayılan yoldan bulamaz;
    ses yalnız açık soket yoluyla (ses_ortami_uygula) boş çıkışa gider."""
    yol = os.path.join(cdir, "run")
    os.makedirs(yol, mode=0o700, exist_ok=True)
    return yol


def ses_ortami_uygula(e: dict, ses: dict | None, yok_yolu: str) -> None:
    """Uygulama ortamının SES bölümü (iki tür için aynı): boş çıkış varsa ona yönlendir, yoksa sesi tamamen kapat.
    Uygulamanın XDG_RUNTIME_DIR'i masaüstünün kendi klasörü olduğundan ses sunucusu AÇIK yolla verilir
    (PULSE_SERVER + PIPEWIRE_RUNTIME_DIR: kullanıcının ses sunucusu; akış yine yalnız boş çıkışa gider)."""
    ses = ses or {}
    if ses.get("sink"):
        rt = gercek_runtime()
        e["PULSE_SERVER"] = f"unix:{rt}/pulse/native"
        e["PIPEWIRE_RUNTIME_DIR"] = rt
        s = ses["sink"]
        e["PULSE_SINK"] = s
        e["PULSE_SOURCE"] = f"{s}.monitor"  # kayıt da sessizlikten: arka plan uygulaması mikrofonu duymaz
        # PULSE_PROP: işaret (ses yönlendiricileri bu akışları tanıyıp dokunmasın) +
        # dont-fallback/dont-reconnect: boş çıkış kalkarsa akış varsayılan çıkışa (kullanıcının kulaklığına)
        # TAŞINMAZ, öldürülür. Ölçüldü (pipewire-pulse): yalnız işaretle akış kulaklığa düştü; bunlarla "Entity
        # killed". PULSE_* değişkenleri flatpak sandbox'ına da geçiyor (ölçüldü).
        e["PULSE_PROP"] = "deskhand.sanal=1 node.dont-fallback=true node.dont-reconnect=true"
        e["PIPEWIRE_NODE"] = s
        e["PIPEWIRE_PROPS"] = (f'{{ target.object = "{s}" node.dont-fallback = true node.dont-reconnect = true '
                               f'deskhand.sanal = 1 }}')
    else:  # boş çıkış kurulamadı: ses tamamen kapalı (varsayılan çıkışa, yani kullanıcının kulağına düşmesin)
        e["PULSE_SERVER"] = f"unix:{yok_yolu}"
        e["PIPEWIRE_REMOTE"] = yok_yolu
        e["PIPEWIRE_RUNTIME_DIR"] = os.path.dirname(yok_yolu)
        e.pop("PULSE_SINK", None)


def _cikarilacak_mi(k: str) -> bool:
    return k in CIKARILACAK_ORTAM or k.startswith(CIKARILACAK_ONEKLER)


def ortam_tabani(env: dict | None = None, izinli: tuple = ()) -> dict:
    """Uygulama ortamının başlangıcı: os.environ + env; ikisinden gelen CIKARILACAK_ORTAM değişkenleri (kullanıcının
    oturum veri yolu, ekranı, sesi, erişilebilirlik adresi, SSH ajanı…) birleştirmeden ÖNCE ve SONRA silinir.
    izinli: env ile açıkça verilince kalabilecek adlar (yalnız Deskhand'in iç yolları; ör. kayıt defterine oturumun
    kendi AT_SPI_BUS_ADDRESS'i). Çağıran üstüne masaüstü değerlerini ZORLA yazar. GSETTINGS_BACKEND=memory: arka plan
    uygulaması kullanıcının gerçek dconf/GSettings ayarlarına yazamaz."""
    e = {k: v for k, v in os.environ.items() if not _cikarilacak_mi(k)}
    if env:
        e.update(env)
    for k in [k for k in e if _cikarilacak_mi(k) and not (k in izinli and env and k in env)]:
        del e[k]
    e["GSETTINGS_BACKEND"] = "memory"
    # özel veri yolunun etkinleştirdiği at-spi-bus-launcher kendi dbus-daemon'unu açsın: dbus-broker --scope=user
    # kullanıcının GERÇEK erişilebilirlik veri yolunu yeniden kullanabiliyor
    e["ATSPI_DBUS_IMPLEMENTATION"] = "dbus-daemon"
    return e


# ---------------------------------------------------------------- özel D-Bus + Xauthority

def _dbus_yapilandir(cdir: str) -> tuple[str, str]:
    """Özel veri yolu: kendi soketi, yalnız izinli servis dosyaları (standart servis dizinleri YOK)."""
    sd = os.path.join(cdir, "dbus-servisler")
    os.makedirs(sd, exist_ok=True)
    for ad, exe in IZINLI_SERVISLER.items():
        if os.path.exists(exe):
            with open(os.path.join(sd, f"{ad}.service"), "w") as f:
                f.write(f"[D-BUS Service]\nName={ad}\nExec={exe}\n")
    soket = os.path.join(cdir, "bus")
    conf = os.path.join(cdir, "bus.conf")
    with open(conf, "w") as f:
        f.write(f"""<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <keep_umask/>
  <listen>unix:path={soket}</listen>
  <auth>EXTERNAL</auth>
  <servicedir>{sd}</servicedir>
  <policy context="default">
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
    <allow own="*"/>
    <!-- sertleştirme: oturumdaki bir istemci etkinleştirilen servislerin ortamını (ör. DISPLAY/WAYLAND_DISPLAY'i
         kullanıcınınkine) değiştiremez, yapılandırmayı yeniden yükletemez -->
    <deny send_destination="org.freedesktop.DBus" send_interface="org.freedesktop.DBus"
          send_member="UpdateActivationEnvironment"/>
    <deny send_destination="org.freedesktop.DBus" send_interface="org.freedesktop.DBus" send_member="ReloadConfig"/>
  </policy>
  <limit name="service_start_timeout">60000</limit>
</busconfig>
""")
    return conf, f"unix:path={soket}"


# Xvfb -auth olmadan açılırsa aynı bilgisayardaki HER yerel istemci (ör. X11 izni olan Flatpak uygulaması) görünmez
# masaüstüne bağlanıp girişli tarayıcının görüntüsünü alabilir/girdi gönderebilirdi. Her masaüstü kendi rastgele
# MIT-MAGIC-COOKIE'siyle açılır; anahtar dosyası çalışma klasöründe (0700) 0600 durur. Uygulamalara XAUTHORITY ile
# verilir; kullanıcının kendi Xauthority dosyasına hiçbir şey yazılmaz.
_AILE_YEREL, _AILE_HEPSI = 256, 0xFFFF


def _xauth_yaz(yol: str, no: int, cerez: bytes) -> None:
    """Xauthority biçimi (libXau): aile(2) + [uzunluk(2) + veri] × (adres, ekran no, ad, anahtar), büyük uçlu.
    İki kayıt: FamilyLocal + makine adı (python-xlib yalnız bunu eşler) ve FamilyWild (makine adı değişse de)."""
    import socket as _soket

    def alan(v: bytes) -> bytes:
        return len(v).to_bytes(2, "big") + v

    ad, numara = b"MIT-MAGIC-COOKIE-1", str(no).encode()
    veri = b"".join(aile.to_bytes(2, "big") + alan(adres) + alan(numara) + alan(ad) + alan(cerez)
                    for aile, adres in ((_AILE_YEREL, _soket.gethostname().encode()), (_AILE_HEPSI, b"")))
    fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(veri)
