"""Görünmez masaüstü için OTURUMA ÖZEL ses sunucusu (dinleme, docs/PLAN_TUR3.md §5).

Her masaüstü kendi küçük PipeWire + WirePlumber + pipewire-pulse örneğini alır (oturum dizininde `ses/`). Örnek
DONANIM bilmez: yapılandırma ALSA/Bluetooth/kamera eklentisini ve aygıt fabrikalarını yüklemez, WirePlumber yalnız
`policy` profiliyle (bağlantı politikası; donanım izleyicisi yok) çalışır. İçinde yalnız `deskhand-sessiz` boş çıkışı
(ve onun monitörü) vardır: mikrofon yok.

Güvenlik sınırı:
  - Uygulamaya YALNIZ pulse soketi: `ses/pulse/native` (ayrı dizin; bwrap ad alanına yalnız bu dizin, SALT OKUNUR).
    PipeWire'ın kendi soketleri (`ses/pipewire-0`, `-manager`: tam yetkili, düğüm/aygıt yaratabilir), yapılandırma ve
    günlükler `ses/` altında kalır ve uygulamanın ad alanında GÖRÜNMEZ; uygulama ortamında PIPEWIRE_REMOTE var olmayan
    bir yoldur.
  - pipewire-pulse'ta modül yükleme KAPALI (`pulse.allow-module-loading = false`, `pulse.cmd` boş): uygulama
    `load-module` ile tünel (kullanıcının gerçek mikrofonu/hoparlörü), LADSPA (keyfi .so), pipe (dosya yazma) ya da TCP
    modülü yükletemez.
  - Derinlemesine savunma: üç ses süreci de KENDİ bwrap ad alanında çalışır (sunucu_argv): ayrı kullanıcı/PID/ağ/IPC ad
    alanı (ağ yok), kök salt okunur, /run, /tmp, ev dizinleri boş tmpfs (kullanıcının gerçek /run/user/UID soketleri ve
    ev dizini sırları görünmez), asgari /dev (/dev/snd, /dev/dri, video, hidraw YOK), yazılabilir tek yol `ses/`. Bir
    sonraki yapılandırma hatası bile sunucuya gerçek ses aygıtı / kullanıcı oturumu açtıramaz.
Sonuç: uygulamanın sesi kullanıcının hoparlörüne/kulaklığına ASLA gitmez; Deskhand aynı örneğin monitöründen kayıt alır
(dinleme.py; bağlanmadan önce soket_denetle). Kurulamıyorsa özellik kapalı kalır (uyarı), uygulamalar eskisi gibi hiç
ses sunucusu görmez.

Süreçler masaüstünün bellek kafesinde nice 10 + ionice idle ile başlar (arka_ortak.kafeste_baslat); kaydedilen PID
bwrap içindeki gerçek sunucu sürecidir (`--as-pid-1`, `--info-fd`). Kapatmada çekirdek süreç listesiyle (`ses_pulse`,
`ses_wp`, `ses_pw`) sinyallenir; oturum dizini silinince soketler de gider."""
from __future__ import annotations

import json
import os
import select
import stat
import subprocess
import time

from . import arka_ortak as ao
from .hata import ARAC_EKSIK, Dur
from .i18n import _

SINK = "deskhand-sessiz"
DIZIN = "ses"            # <oturum çalışma dizini>/ses  (yalnız ses süreçleri)
PULSE_DIZIN = "pulse"    # <dizin>/pulse: uygulamaya bağlanan TEK dizin (salt okunur)
PULSE_SOKET = "native"   # <dizin>/pulse/native  (PULSE_SERVER=unix:...)
PW_SOKET = "pipewire-0"  # <dizin>/pipewire-0  (yalnız ses süreçleri; uygulamaya görünmez)
SURECLER = ("ses_pulse", "ses_wp", "ses_pw")  # kapatma sırası
ARACLAR = ("pipewire", "wireplumber", "pipewire-pulse", "pactl", "parec", "bwrap", "prlimit")

PW_YAPILANDIRMA = """\
# Deskhand: oturuma özel PipeWire (donanım yok: yalnız boş çıkış; aygıt fabrikası yok)
context.properties = {
    link.max-buffers = 16
    core.daemon = true
    core.name = pipewire-0
    support.dbus = false
    mem.allow-mlock = false
    default.clock.rate = 48000
    default.clock.allowed-rates = [ 48000 ]
}
context.spa-libs = {
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}
context.modules = [
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-metadata }
    # soketlere YALNIZ ses süreçleri ulaşır (uygulamanın ad alanında görünmezler); PID tabanlı (eski) denetim ayrı PID
    # ad alanlarında çalışmaz → soket tabanlı kip
    { name = libpipewire-module-access
      args = { access.legacy = false
               access.socket = { pipewire-0 = "unrestricted", pipewire-0-manager = "unrestricted" } } }
    { name = libpipewire-module-spa-node-factory }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-link-factory }
]
context.objects = [
    { factory = spa-node-factory
      args = { factory.name = support.node.driver
               node.name = Dummy-Driver
               node.group = pipewire.dummy
               node.sync-group = sync.dummy
               priority.driver = 200000 } }
    { factory = adapter
      args = { factory.name = support.null-audio-sink
               node.name = %(sink)s
               node.description = Deskhand-sessiz
               media.class = Audio/Sink
               object.linger = true
               audio.position = [ FL FR ]
               monitor.channel-volumes = true
               monitor.passthrough = true
               priority.session = 2000 } }
]
"""

PULSE_YAPILANDIRMA = """\
# Deskhand: oturuma özel pipewire-pulse (yalnız bu dizindeki soket; modül yükleme KAPALI)
context.properties = {
    mem.allow-mlock = false
    support.dbus = false
}
context.spa-libs = {
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}
context.modules = [
    { name = libpipewire-module-protocol-native }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-metadata }
    { name = libpipewire-module-protocol-pulse
      args = { server.address = [ "unix:%(dizin)s/%(pulse)s" ] } }
]
pulse.properties = {
    pulse.min.req = 256/48000
    pulse.allow-module-loading = false
}
pulse.cmd = [ ]
pulse.rules = [ ]
"""


def dizin(cdir: str) -> str:
    return os.path.join(cdir, DIZIN)


def pulse_dizini(cdir: str) -> str:
    return os.path.join(dizin(cdir), PULSE_DIZIN)


def pulse_soketi(cdir: str) -> str:
    return os.path.join(pulse_dizini(cdir), PULSE_SOKET)


def _ozel_dizin_mi(st: os.stat_result) -> bool:
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and (st.st_mode & 0o777) == 0o700


def soket_hazir(cdir: str | None) -> bool:
    """`<oturum>/ses/pulse/native` kullanıcıya ait gerçek bir soket mi; `ses/` ve `ses/pulse/` gerçek (sembolik bağ
    olmayan) 0700 dizinler mi? (Kayıttaki alanlara GÜVENİLMEZ: yol çalışma dizininden kurulur; uygulama ortamı ve bağları
    bu denetime dayanır.)"""
    if not cdir:
        return False
    try:
        dt, pt = os.lstat(dizin(cdir)), os.lstat(pulse_dizini(cdir))
        st = os.lstat(pulse_soketi(cdir))
    except OSError:
        return False
    return _ozel_dizin_mi(dt) and _ozel_dizin_mi(pt) and stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def soket_denetle(cdir: str, d: dict | None) -> str:
    """Deskhand'in KENDİ istemcisi (parec) bağlanmadan önce (arka_ortak.a11y_soket_denetle deseni): dizinler gerçek 0700
    ve kullanıcının (soket_hazir); soket sembolik bağ değil + S_ISSOCK + kullanıcının; (st_dev, st_ino) kullanıcının
    gerçek soketlerinden birinin SERT BAĞI değil; karşı uç (SO_PEERCRED) durum kaydındaki `ses_pulse` süreci (başlangıç
    zamanı + oturum kafesi doğrulanmış). Değilse Dur(14). → soket yolu."""
    yol = pulse_soketi(cdir)
    if not soket_hazir(cdir):
        raise Dur(14, _("özel ses soketi güvensiz ya da yok (sembolik bağ / soket değil / başkasının / gevşek izinli "
                        "dizin): {yol}; bağlanılmadı").format(yol=yol))
    st = os.lstat(yol)
    if (st.st_dev, st.st_ino) in ao.gercek_soket_kimlikleri():
        raise Dur(14, _("özel ses soketi kullanıcının gerçek soketinin sert bağı: {yol}; bağlanılmadı").format(yol=yol))
    d = d or {}
    pid, bas = d.get("pid") or {}, d.get("pid_bas") or {}
    beklenen = pid.get("ses_pulse")
    karsi = ao.soket_karsi_pid(yol)
    if not isinstance(beklenen, int) or karsi != beklenen or \
            not ao.pid_dogru(karsi, bas.get("ses_pulse"), d.get("cgroup") or ""):
        raise Dur(14, _("özel ses soketinin karşı tarafı bu oturumun ses süreci değil ({karsi}); "
                        "bağlanılmadı").format(karsi=karsi))
    return yol


def eksik_araclar() -> list[str]:
    return [a for a in ARACLAR if not ao.arac(a, zorunlu=False)]


def istemci_ortami(dz: str) -> dict:
    """pactl/parec gibi Deskhand'in kendi istemcileri için TEMİZ ortam: yalnız özel sunucunun pulse soketi (kullanıcının
    sunucusu yok; PipeWire soketi verilmez)."""
    return {"PATH": ao.GUVENLI_PATH, "HOME": dz, "XDG_RUNTIME_DIR": dz, "XDG_CONFIG_HOME": os.path.join(dz, "cfg"),
            "PULSE_SERVER": f"unix:{os.path.join(dz, PULSE_DIZIN, PULSE_SOKET)}", "PULSE_RUNTIME_PATH": dz,
            "PIPEWIRE_REMOTE": os.path.join(dz, "yok"), "PIPEWIRE_RUNTIME_DIR": dz,
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _sunucu_ortami(dz: str) -> dict:
    e = istemci_ortami(dz)
    e.update({"XDG_STATE_HOME": os.path.join(dz, "state"), "XDG_CACHE_HOME": os.path.join(dz, "cache"),
              "XDG_DATA_HOME": os.path.join(dz, "data"), "PIPEWIRE_REMOTE": os.path.join(dz, PW_SOKET)})
    return e


def _alti(yol: str, kok: str) -> bool:
    return yol == kok or yol.startswith(kok.rstrip("/") + "/")


def sunucu_argv(argv: list[str], dz: str, info_fd: int) -> list[str]:
    """Ses SUNUCULARININ bwrap ad alanı (derinlemesine savunma; uygulamanınkinden DAR):
      - ayrı kullanıcı + PID + ağ + IPC + UTS ad alanı: AĞ YOK (yalnız lo), kullanıcının süreçleri görünmez. Üç ses
        süreci AYNI ad alanındadır (PipeWire istemcileri farklı PID ad alanlarında veri akışı kuramıyor, ölçüldü);
        1 numaralı süreç küçük yönetici kabuktur (`--as-pid-1`, YONETICI): ölürse çekirdek hepsini öldürür;
      - kök SALT OKUNUR; /run (kullanıcının gerçek /run/user/UID soketleri, sistem soketleri), /tmp, /var/tmp, /home ve
        gerçek ev dizini, /mnt, /media, /srv ve (başka yerdeyse) Deskhand'in RUNTIME_DIR'i BOŞ tmpfs;
      - /dev bwrap'in asgari /dev'i: /dev/snd, /dev/dri, video, hidraw, input YOK;
      - yazılabilir TEK yol `ses/` (soketler, durum, günlük);
      - RLIMIT_NICE/RTPRIO 0 (prlimit): WirePlumber'ın rt modülü önceliği yükseltemez (nice 10 kalır);
      - `--info-fd`: gerçek PID'i bildirir."""
    from . import yollar
    a = [ao.arac("bwrap"), "--unshare-user", "--unshare-pid", "--as-pid-1", "--unshare-net", "--unshare-ipc",
         "--unshare-uts", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run"]
    maske: list[str] = []
    for m in ("/var/tmp", "/home", ao.gercek_ev(), "/mnt", "/media", "/srv", yollar.runtime_dir()):
        m = os.path.realpath(m) if m else ""
        if m and m != "/" and os.path.isdir(m) and not any(_alti(m, k) for k in ("/run", "/tmp", *maske)):
            maske.append(m)
            a += ["--tmpfs", m]
    a += ["--bind", dz, dz, "--chdir", dz, "--new-session", "--info-fd", str(info_fd), "--",
          ao.arac("prlimit"), "--nice=0", "--rtprio=0", "--", *argv]
    return a


def pactl(dz: str, *a, sure: float = 5.0) -> subprocess.CompletedProcess | None:
    p = ao.arac("pactl", zorunlu=False)
    if not p:
        return None
    try:
        return subprocess.run([p, *a], capture_output=True, text=True, timeout=sure, env=istemci_ortami(dz))
    except (OSError, subprocess.TimeoutExpired):
        return None


def kaynaklar_ve_cikislar(dz: str) -> tuple[list[str], list[str]]:
    """Özel sunucudaki (cikislar, kaynaklar) adları."""
    def adlar(tur):
        r = pactl(dz, "list", "short", tur)
        return [s.split("\t")[1] for s in (r.stdout.splitlines() if r and r.returncode == 0 else []) if "\t" in s]
    return adlar("sinks"), adlar("sources")


def _bekle(kosul, sure: float, aralik: float = 0.05) -> bool:
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if kosul():
            return True
        time.sleep(aralik)
    return kosul()


def _bilgi_oku(r: int, p: subprocess.Popen, sure: float = 5.0) -> int | None:
    """bwrap --info-fd JSON'undan ad alanındaki komutun GERÇEK PID'i (child-pid)."""
    veri, bitis = b"", time.monotonic() + sure
    while time.monotonic() < bitis and len(veri) < 65536:
        hazir, _w, _x = select.select([r], [], [], 0.2)
        if hazir:
            parca = os.read(r, 4096)
            if not parca:
                break
            veri += parca
        elif p.poll() is not None:
            break
    try:
        cocuk = json.loads(veri.decode())["child-pid"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    return cocuk if isinstance(cocuk, int) and not isinstance(cocuk, bool) and cocuk > 1 else None


# Ad alanının 1 numaralı süreci (sh): üç sunucuyu başlatır, SIGTERM'de onları kapatır (ata ad alanından gelen sinyal
# yalnız işleyicisi olan init'e ulaşır), biri ölürse diğerlerini de kapatıp çıkar. Günlükler `ses/` altında.
YONETICI = """\
trap 'kill -TERM $c $b $a 2>/dev/null; wait; exit 0' TERM INT HUP
"$1" -c "$4" >ses_pw.log 2>&1 & a=$!
i=0
while [ ! -S pipewire-0 ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i+1)); done
"$2" -p policy >ses_wp.log 2>&1 & b=$!
"$3" -c "$5" >ses_pulse.log 2>&1 & c=$!
wait -n 2>/dev/null || wait
kill -TERM $c $b $a 2>/dev/null
wait
"""
SUREC_ADLARI = {"ses_wp": "wireplumber", "ses_pulse": "pipewire-pulse"}


def _ad_alani_surecleri(init: int) -> dict[str, int]:
    """init (ses ad alanının 1 numaralı süreci) ile AYNI PID ad alanındaki süreçler: comm → gerçek PID."""
    try:
        ns = os.stat(f"/proc/{init}/ns/pid").st_ino
    except OSError:
        return {}
    bulunan: dict[str, int] = {}
    for g in os.listdir("/proc"):
        if not g.isdigit() or int(g) == init:
            continue
        try:
            if os.stat(f"/proc/{g}/ns/pid").st_ino != ns:
                continue
            with open(f"/proc/{g}/comm") as f:
                bulunan.setdefault(f.read().strip(), int(g))
        except OSError:
            continue
    return bulunan


def _baslat(d: dict, dz: str) -> subprocess.Popen:
    """Üç ses sürecini TEK bwrap ad alanında (sunucu_argv; PipeWire istemcileri farklı PID ad alanlarında veri akışı
    kuramıyor, ölçüldü), kafeste, nice 10 + ionice idle başlat. Kaydedilen PID'ler: `ses_pw` = ad alanının 1 numaralı
    süreci (yönetici; öldürülünce çekirdek ad alanındaki her şeyi öldürür), `ses_wp`/`ses_pulse` = gerçek sunucu
    süreçleri (soket_denetle karşı uç denetimi). Bulunamazsa OSError."""
    argv = [ao.arac("sh"), "-c", YONETICI, "deskhand-ses", ao.arac("pipewire"), ao.arac("wireplumber"),
            ao.arac("pipewire-pulse"), os.path.join(dz, "pw.conf"), os.path.join(dz, "pulse.conf")]
    r, w = os.pipe()
    try:
        with open(os.path.join(dz, "ses.log"), "ab") as log:
            p = ao.kafeste_baslat(d, sunucu_argv(argv, dz, w), _sunucu_ortami(dz), pass_fds=(w,),
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    except BaseException:
        os.close(r)
        raise
    finally:
        os.close(w)
    try:
        init = _bilgi_oku(r, p)
    finally:
        os.close(r)
    if init is None:
        p.kill()
        p.wait()
        raise OSError(_("ses ad alanı kurulamadı (bkz. {log})").format(log=os.path.join(dz, "ses.log")))
    ao.pid_kaydet(d, "ses_pw", init)
    if not _bekle(lambda: set(SUREC_ADLARI.values()) <= set(_ad_alani_surecleri(init)) or p.poll() is not None, 8):
        raise OSError(_("ses süreçleri başlamadı (bkz. {log})").format(log=os.path.join(dz, "ses_*.log")))
    bulunan = _ad_alani_surecleri(init)
    for ad, comm in SUREC_ADLARI.items():
        if comm not in bulunan:
            raise OSError(_("{ad} çalışmadı (bkz. {log})").format(ad=comm, log=os.path.join(dz, f"{ad}.log")))
        ao.pid_kaydet(d, ad, bulunan[comm])
    return p


def kur(d: dict, cdir: str) -> str | None:
    """Oturumun özel ses sunucusunu başlat (zaten hazırsa dokunma). → uyarı metni | None (hazır). Yeniden kurulumda
    önce eski kayıtlı süreçler kapatılır. Başarısızlıkta kurulan süreçler kapatılır, d["ses"] = None (özellik kapalı:
    uygulamalar hiç ses sunucusu görmez)."""
    if soket_hazir(cdir) and (d.get("pid") or {}).get("ses_pw"):
        return None
    kapat(d)  # yarım kalmış/eski kurulumun kayıtlı süreçleri (doğrulanmış PID'ler)
    eksik = eksik_araclar()
    if eksik:
        d["ses"] = None
        return _("dinleme kapalı: {araclar} yok (özel ses sunucusu kurulamadı)").format(araclar=", ".join(eksik))
    dz = dizin(cdir)
    try:
        os.makedirs(dz, mode=0o700, exist_ok=True)
        os.chmod(dz, 0o700)
        for alt in ("cfg", "state", "cache", "data", PULSE_DIZIN):
            os.makedirs(os.path.join(dz, alt), mode=0o700, exist_ok=True)
            os.chmod(os.path.join(dz, alt), 0o700)
        for eski in (PW_SOKET, PW_SOKET + ".lock", PW_SOKET + "-manager", PW_SOKET + "-manager.lock"):
            if os.path.lexists(os.path.join(dz, eski)):  # çökmüş eski örnekten kalan soket/kilit
                os.unlink(os.path.join(dz, eski))
        if max(len(pulse_soketi(cdir)), len(os.path.join(dz, PW_SOKET + "-manager"))) >= 100:  # AF_UNIX sınırı (108)
            raise OSError(_("oturum dizini yolu çok uzun (soket yolu 108 bayt sınırı)"))
        with open(os.path.join(dz, "pw.conf"), "w") as f:
            f.write(PW_YAPILANDIRMA % {"sink": SINK})
        with open(os.path.join(dz, "pulse.conf"), "w") as f:
            f.write(PULSE_YAPILANDIRMA % {"dizin": pulse_dizini(cdir), "pulse": PULSE_SOKET})
        pp = _baslat(d, dz)
        if not _bekle(lambda: soket_hazir(cdir) or pp.poll() is not None, 8):
            raise OSError(_("pipewire-pulse soketi açılmadı"))
        if not _bekle(lambda: SINK in kaynaklar_ve_cikislar(dz)[0], 8, 0.15):
            raise OSError(_("özel boş çıkış ({sink}) görünmedi").format(sink=SINK))
        sinks, sources = kaynaklar_ve_cikislar(dz)
        if sinks != [SINK] or any(not s.endswith(".monitor") for s in sources):
            raise OSError(_("özel ses sunucusunda beklenmeyen aygıt var: {a}").format(a=sinks + sources))
    except (OSError, Dur) as e:
        kapat(d)
        d["ses"] = None
        return _("dinleme kapalı: özel ses sunucusu kurulamadı ({hata})").format(hata=e)
    d["ses"] = {"sink": SINK, "ozel": True}
    return None


def ayara_gore_kur(d: dict, cdir: str) -> None:
    """Masaüstü açılırken: ayar `dinleme.ozel_ses` açıksa özel sunucuyu kur; başarısızlık yalnız uyarıdır."""
    from . import ayarlar
    if not ayarlar.al("dinleme", "ozel_ses"):
        d["ses"] = None
        return
    uyari = kur(d, cdir)
    if uyari:
        d.setdefault("uyarilar", []).append(uyari)


def kapat(d: dict) -> None:
    """Özel sunucu süreçlerini kapat (yalnız kayıtlı + başlangıç zamanı doğrulanmış PID'ler)."""
    import signal
    pid, bas = d.get("pid") or {}, d.get("pid_bas") or {}
    for ad in SURECLER:
        p = pid.get(ad)
        if isinstance(p, int) and p > 0 and ao.pid_dogru(p, bas.get(ad), d.get("cgroup") or ""):
            ao._sinyal([p], signal.SIGTERM)
            _bekle(lambda p=p: not ao._canli(p), 2)
            if ao._canli(p):
                ao._sinyal([p], signal.SIGKILL)
        pid.pop(ad, None)
        bas.pop(ad, None)


def saglik(cdir: str) -> bool:
    """Özel sunucu soketi hazır ve boş çıkış görünüyor mu."""
    if not soket_hazir(cdir):
        return False
    return SINK in kaynaklar_ve_cikislar(dizin(cdir))[0]
