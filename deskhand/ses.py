"""Görünmez masaüstü için OTURUMA ÖZEL ses sunucusu (dinleme, docs/PLAN_TUR3.md §5).

Her masaüstü kendi küçük PipeWire + WirePlumber + pipewire-pulse örneğini alır (oturum dizininde). Örnek
DONANIM bilmez: yapılandırma ALSA/Bluetooth/kamera eklentisini ve aygıt fabrikalarını yüklemez, WirePlumber yalnız
`policy` profiliyle (bağlantı politikası; donanım izleyicisi yok) çalışır. İçinde yalnız `deskhand-sessiz` boş çıkışı
(ve onun monitörü) vardır: mikrofon yok.

Dizin düzeni (oturum çalışma dizini `cdir` altında; HEPSİ 0700, gerçek dizin):
  ses/           sunucunun YAZABİLDİĞİ tek alan (PipeWire soketleri, durum, `ses_*.log`). Ele geçirilmiş bir sunucu
                 buraya sembolik bağ vb. koyabilir: Deskhand bu dizinde HİÇBİR dosyayı açmaz/okumaz/değiştirmez; her
                 kurulumda `shutil.rmtree` ile silinip sıfırdan yaratılır.
  ses-conf/      pw.conf, pulse.conf, ses.log: Deskhand yazar, sunucuya SALT OKUNUR bağlanır (günlük Deskhand'de açılıp
                 stdout olarak verilir; boyutu LOG_SINIRI ile sınırlı).
  ses-pulse/     pulse soketi (`native`): sunucuya yazılabilir, uygulamaya SALT OKUNUR bağlanan TEK dizin. Dizin girdisinin
                 kendisini yalnız Deskhand değiştirebilir (sunucunun ad alanında bağ noktasıdır); uygulama başlatılırken
                 (dev, ino) kimliği bağdan önce ve sonra denetlenir.
  ses-istemci/   Deskhand'in KENDİ istemcileri (pactl/parec) için HOME/XDG_CONFIG_HOME/cookie; sunucuya bağlanmaz.

Güvenlik sınırı:
  - Uygulamaya YALNIZ pulse soketi: `ses-pulse/native` (bwrap ad alanına yalnız bu dizin, SALT OKUNUR). PipeWire'ın
    kendi soketleri (`ses/pipewire-0`, `-manager`: tam yetkili, düğüm/aygıt yaratabilir), yapılandırma ve günlükler
    uygulamanın ad alanında GÖRÜNMEZ; uygulama ortamında PIPEWIRE_REMOTE var olmayan bir yoldur.
  - pipewire-pulse'ta modül yükleme KAPALI (`pulse.allow-module-loading = false`, `pulse.cmd` boş): uygulama
    `load-module` ile tünel (kullanıcının gerçek mikrofonu/hoparlörü), LADSPA (keyfi .so), pipe (dosya yazma) ya da TCP
    modülü yükletemez.
  - Derinlemesine savunma: üç ses süreci tek ORTAK bwrap ad alanında çalışır (sunucu_argv): ayrı kullanıcı/PID/ağ/IPC ad
    alanı (ağ yok), kök salt okunur, /run, /tmp, ev dizinleri boş tmpfs (kullanıcının gerçek /run/user/UID soketleri ve
    ev dizini sırları görünmez), asgari /dev (/dev/snd, /dev/dri, video, hidraw YOK), yazılabilir yollar yalnız `ses/` ve
    `ses-pulse/`. Bir sonraki yapılandırma hatası bile sunucuya gerçek ses aygıtı / kullanıcı oturumu açtıramaz.
  - Sunucuya GÜVENİLMEZ (ele geçirilmiş olabilir): Deskhand'in kendi istemcileri sunucunun yazabildiği hiçbir dizinden
    yapılandırma/cookie okumaz (ses-istemci), soket denetimi sonrası bağlantı Deskhand'in kendi dizinindeki SERT BAĞ
    üzerinden kurulur (denetle-bağlan arası değiştirilemez).
Sonuç: uygulamanın sesi kullanıcının hoparlörüne/kulaklığına ASLA gitmez; Deskhand aynı örneğin monitöründen kayıt alır
(dinleme.py; bağlanmadan önce soket_denetle). Kurulamıyorsa özellik kapalı kalır (uyarı), uygulamalar eskisi gibi hiç
ses sunucusu görmez.

Süreçler masaüstünün bellek kafesinde nice 10 + ionice idle ile başlar (arka_ortak.kafeste_baslat); `ses_pw` olarak
kaydedilen PID bwrap ad alanının 1 numaralı süreci olan YÖNETİCİ KABUKTUR (`--as-pid-1`, `--info-fd`); `ses_wp`/`ses_pulse`
gerçek sunucu süreçleridir. Yönetici kabuk çocuklardan biri ölünce hepsini kapatıp çıkar (bayat soket/yarım sunucu
kalmaz); hazir() ölü ya da yarım sunucuyu algılar, sonraki kurulum onu yeniden kurar. Kapatmada çekirdek süreç listesiyle
(`ses_pulse`, `ses_wp`, `ses_pw`) sinyallenir; oturum dizini silinince soketler de gider."""
from __future__ import annotations

import json
import os
import select
import shutil
import stat
import subprocess
import time

from . import arka_ortak as ao
from .hata import ARAC_EKSIK, Dur
from .i18n import _

SINK = "deskhand-sessiz"
DIZIN = "ses"                # <oturum çalışma dizini>/ses: sunucunun YAZABİLDİĞİ alan (Deskhand içinden hiçbir şey okumaz)
CONF_DIZIN = "ses-conf"      # <çalışma>/ses-conf: pw.conf, pulse.conf, ses.log (sunucuya SALT OKUNUR)
PULSE_DIZIN = "ses-pulse"    # <çalışma>/ses-pulse: uygulamaya bağlanan TEK dizin (salt okunur); sunucuya yazılabilir
ISTEMCI_DIZIN = "ses-istemci"  # <çalışma>/ses-istemci: Deskhand'in kendi pactl/parec ortamı (sunucuya bağlanmaz)
PULSE_SOKET = "native"       # <çalışma>/ses-pulse/native  (PULSE_SERVER=unix:...)
PW_SOKET = "pipewire-0"      # <çalışma>/ses/pipewire-0  (yalnız ses süreçleri; uygulamaya görünmez)
LOG_SINIRI = 5 * 1024 * 1024  # ses.log bu boyutu aşarsa kesilir (kurulumda ve hazir()/saglik() çağrılarında)
SURECLER = ("ses_pulse", "ses_wp", "ses_pw")  # kapatma sırası
ARACLAR = ("pipewire", "wireplumber", "pipewire-pulse", "pactl", "parec", "bwrap", "prlimit", "bash")

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
      args = { server.address = [ "unix:%(dizin)s/%(soket)s" ] } }
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


def conf_dizini(cdir: str) -> str:
    return os.path.join(cdir, CONF_DIZIN)


def pulse_dizini(cdir: str) -> str:
    return os.path.join(cdir, PULSE_DIZIN)


def pulse_soketi(cdir: str) -> str:
    return os.path.join(pulse_dizini(cdir), PULSE_SOKET)


def istemci_dizini(cdir: str) -> str:
    return os.path.join(cdir, ISTEMCI_DIZIN)


def _ozel_dizin_mi(st: os.stat_result) -> bool:
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and (st.st_mode & 0o777) == 0o700


def _izinleri_ac(yol: str) -> None:
    """rmtree'nin giremediği (0000 izinli vb.) alt dizinleri kullanıcı olarak açılabilir yap (sembolik bağlar izlenmez)."""
    for kok, dizinler, _d in os.walk(yol, topdown=True, followlinks=False):
        for ad in dizinler:
            y = os.path.join(kok, ad)
            if not os.path.islink(y):
                try:
                    os.chmod(y, 0o700)
                except OSError:
                    pass


def sifirla(yol: str) -> None:
    """`yol`u silip (sembolik bağ/dosya/dizin; dizin `shutil.rmtree` ile, bağlar İZLENMEZ) sıfırdan 0700 dizin yarat
    (mkdir: yoksa yaratır, VARSA hata: sembolik bağ üzerinden yaratma yok). Eski sunucudan kalan hiçbir şey sağ kalmaz."""
    try:
        st = os.lstat(yol)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISDIR(st.st_mode):
            try:
                shutil.rmtree(yol)
            except OSError:
                _izinleri_ac(yol)
                shutil.rmtree(yol)
        else:
            os.unlink(yol)
    os.mkdir(yol, 0o700)
    os.chmod(yol, 0o700)
    if not _ozel_dizin_mi(os.lstat(yol)):
        raise OSError(_("dizin güvenli yaratılamadı: {yol}").format(yol=yol))


def soket_hazir(cdir: str | None) -> bool:
    """`<oturum>/ses-pulse/native` kullanıcıya ait gerçek bir soket mi; `ses-pulse/` gerçek (sembolik bağ olmayan) 0700
    dizin mi? (Kayıttaki alanlara GÜVENİLMEZ: yol çalışma dizininden kurulur; uygulama ortamı ve bağları bu denetime
    dayanır.) Yalnız dosya sistemi bakışı: sunucunun yaşadığını göstermez (bkz. hazir)."""
    if not cdir:
        return False
    try:
        pt = os.lstat(pulse_dizini(cdir))
        st = os.lstat(pulse_soketi(cdir))
    except OSError:
        return False
    return _ozel_dizin_mi(pt) and stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def pulse_kimlik(cdir: str | None) -> tuple[int, int] | None:
    """Uygulamaya bağlanacak pulse dizininin (st_dev, st_ino) kimliği (hazır değilse None)."""
    if not soket_hazir(cdir):
        return None
    try:
        st = os.lstat(pulse_dizini(cdir))
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


SON_KIMLIK: dict[str, tuple[int, int] | None] = {}


def kimlik_kaydet(cdir: str) -> tuple[int, int] | None:
    """Uygulamanın bağ listesi (arka_ortak.ses_bagi) kurulurken pulse dizininin kimliğini not et: bwrap bağından hemen
    önce (arka_ortak.korumali_baslat) ve sonra yeniden karşılaştırılır; dizin arada değiştirilirse uygulama başlamaz."""
    k = pulse_kimlik(cdir)
    SON_KIMLIK[cdir] = k
    return k


def _log_yolu(cdir: str) -> str:
    return os.path.join(conf_dizini(cdir), "ses.log")


def gunluk_sinirla(cdir: str) -> None:
    """ses.log LOG_SINIRI'ni aşmışsa kes (Deskhand'e ait, sunucuya salt okunur dizinde; sembolik bağ izlenmez)."""
    try:
        fd = os.open(_log_yolu(cdir), os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return
    try:
        st = os.fstat(fd)
        if stat.S_ISREG(st.st_mode) and st.st_size > LOG_SINIRI:
            os.ftruncate(fd, 0)
    except OSError:
        pass
    finally:
        os.close(fd)


def hazir(d: dict | None, cdir: str | None) -> bool:
    """Özel sunucu GERÇEKTEN kullanılabilir mi: pulse dizini/soketi güvenli (soket_hazir) + yönetici kabuk (ses_pw) ve
    pipewire-pulse (ses_pulse) kayıttaki süreçler (başlangıç zamanı + kafes doğrulanmış) + soketin karşı ucu o
    pipewire-pulse (bağlanılabilir). Ölü/yarım sunucu ya da bayat soket → False (çağıran yeniden kurar)."""
    if not cdir or not soket_hazir(cdir):
        return False
    gunluk_sinirla(cdir)
    d = d or {}
    pid, bas, cg = d.get("pid") or {}, d.get("pid_bas") or {}, d.get("cgroup") or ""
    for ad in ("ses_pw", "ses_pulse"):
        if not isinstance(pid.get(ad), int) or not ao.pid_dogru(pid.get(ad), bas.get(ad), cg):
            return False
    return ao.soket_karsi_pid(pulse_soketi(cdir)) == pid["ses_pulse"]


def _istemci_hazirla(cdir: str) -> str:
    """Deskhand'in kendi pactl/parec istemcilerinin ev dizini (`ses-istemci`, 0700; sunucuya BAĞLANMAZ, sunucunun
    yazdığı yapılandırma/cookie buradan okunmaz). Gerçek 0700 dizin değilse silinip yeniden yaratılır."""
    ic = istemci_dizini(cdir)
    try:
        ok = _ozel_dizin_mi(os.lstat(ic))
    except OSError:
        ok = False
    if not ok:
        sifirla(ic)
    try:
        os.mkdir(os.path.join(ic, "cfg"), 0o700)
    except FileExistsError:
        pass
    bos = os.path.join(ic, "client.conf")  # PULSE_CLIENTCONFIG: BOŞ yapılandırma (hiçbir cookie-file/default-server yok)
    try:
        os.close(os.open(bos, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
    except OSError:
        pass
    return ic


def soket_denetle(cdir: str, d: dict | None) -> str:
    """Deskhand'in KENDİ istemcisi (parec/pactl) bağlanmadan önce (arka_ortak.a11y_soket_denetle deseni): `ses-pulse` gerçek
    0700 dizin ve soket kullanıcının (soket_hazir); soket Deskhand'in KENDİ dizinine (`ses-istemci`) SERT BAĞLANIR ve
    tüm denetimler o bağ üzerinde yapılır: sembolik bağ değil + S_ISSOCK + kullanıcının; (st_dev, st_ino) kullanıcının
    gerçek soketlerinden birinin sert bağı değil; karşı uç (SO_PEERCRED) durum kaydındaki `ses_pulse` süreci (başlangıç
    zamanı + oturum kafesi doğrulanmış). İstemci bu bağ üzerinden bağlanır: sunucu `native`'i denetimden sonra başka bir
    şeye (sembolik bağ) çevirse de bağlantı denetlenen soketedir (denetle-bağlan arası TOCTOU yok). Değilse Dur(14).
    → istemcinin bağlanacağı yol."""
    yol = pulse_soketi(cdir)
    if not soket_hazir(cdir):
        raise Dur(14, _("özel ses soketi güvensiz ya da yok (sembolik bağ / soket değil / başkasının / gevşek izinli "
                        "dizin): {yol}; bağlanılmadı").format(yol=yol))
    ozel = os.path.join(_istemci_hazirla(cdir), "pulse-native")
    try:
        os.unlink(ozel)
    except FileNotFoundError:
        pass
    try:
        os.link(yol, ozel, follow_symlinks=False)
        st = os.lstat(ozel)
    except OSError as e:
        raise Dur(14, _("özel ses soketi denetime alınamadı ({hata}): {yol}; bağlanılmadı").format(hata=e, yol=yol))
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        raise Dur(14, _("özel ses soketi güvensiz ya da yok (sembolik bağ / soket değil / başkasının / gevşek izinli "
                        "dizin): {yol}; bağlanılmadı").format(yol=yol))
    if (st.st_dev, st.st_ino) in ao.gercek_soket_kimlikleri():
        raise Dur(14, _("özel ses soketi kullanıcının gerçek soketinin sert bağı: {yol}; bağlanılmadı").format(yol=yol))
    d = d or {}
    pid, bas = d.get("pid") or {}, d.get("pid_bas") or {}
    beklenen = pid.get("ses_pulse")
    karsi = ao.soket_karsi_pid(ozel)
    if not isinstance(beklenen, int) or karsi != beklenen or \
            not ao.pid_dogru(karsi, bas.get("ses_pulse"), d.get("cgroup") or ""):
        raise Dur(14, _("özel ses soketinin karşı tarafı bu oturumun ses süreci değil ({karsi}); "
                        "bağlanılmadı").format(karsi=karsi))
    return ozel


def eksik_araclar() -> list[str]:
    return [a for a in ARACLAR if not ao.arac(a, zorunlu=False)]


def istemci_ortami(cdir: str, soket: str | None = None) -> dict:
    """pactl/parec gibi Deskhand'in kendi istemcileri için TEMİZ ortam: HOME/XDG_CONFIG_HOME/cookie/istemci yapılandırması
    SUNUCUYA BAĞLANMAYAN Deskhand dizininde (`ses-istemci`); sunucunun yazabildiği hiçbir yol yok (client.conf'a
    `cookie-file=~/.ssh/...` koyarak dosya okutamaz). PULSE_CLIENTCONFIG boş dosya. soket: soket_denetle'nin döndürdüğü
    denetlenmiş yol (verilmezse ses-pulse/native). PipeWire soketi verilmez."""
    ic = _istemci_hazirla(cdir)
    return {"PATH": ao.GUVENLI_PATH, "HOME": ic, "XDG_RUNTIME_DIR": ic, "XDG_CONFIG_HOME": os.path.join(ic, "cfg"),
            "PULSE_SERVER": f"unix:{soket or pulse_soketi(cdir)}", "PULSE_RUNTIME_PATH": ic,
            "PULSE_COOKIE": os.path.join(ic, "cookie"), "PULSE_CLIENTCONFIG": os.path.join(ic, "client.conf"),
            "PIPEWIRE_REMOTE": os.path.join(ic, "yok"), "PIPEWIRE_RUNTIME_DIR": ic,
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _sunucu_ortami(dz: str) -> dict:
    return {"PATH": ao.GUVENLI_PATH, "HOME": dz, "XDG_RUNTIME_DIR": dz, "XDG_CONFIG_HOME": os.path.join(dz, "cfg"),
            "XDG_STATE_HOME": os.path.join(dz, "state"), "XDG_CACHE_HOME": os.path.join(dz, "cache"),
            "XDG_DATA_HOME": os.path.join(dz, "data"), "PIPEWIRE_REMOTE": os.path.join(dz, PW_SOKET),
            "PIPEWIRE_RUNTIME_DIR": dz, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _alti(yol: str, kok: str) -> bool:
    return yol == kok or yol.startswith(kok.rstrip("/") + "/")


def sunucu_argv(argv: list[str], cdir: str, info_fd: int) -> list[str]:
    """Ses SUNUCULARININ bwrap ad alanı (derinlemesine savunma; uygulamanınkinden DAR):
      - ayrı kullanıcı + PID + ağ + IPC + UTS ad alanı: AĞ YOK (yalnız lo), kullanıcının süreçleri görünmez. Üç ses
        süreci AYNI ad alanındadır (PipeWire istemcileri farklı PID ad alanlarında veri akışı kuramıyor, ölçüldü);
        1 numaralı süreç küçük yönetici kabuktur (`--as-pid-1`, YONETICI): ölürse çekirdek hepsini öldürür;
      - kök SALT OKUNUR; /run (kullanıcının gerçek /run/user/UID soketleri, sistem soketleri), /tmp, /var/tmp, /home ve
        gerçek ev dizini, /mnt, /media, /srv ve (başka yerdeyse) Deskhand'in RUNTIME_DIR'i BOŞ tmpfs;
      - /dev bwrap'in asgari /dev'i: /dev/snd, /dev/dri, video, hidraw, input YOK;
      - yazılabilir YALNIZ `ses/` (PipeWire soketleri, durum, süreç günlükleri) ve `ses-pulse/` (pulse soketi);
        `ses-conf/` (yapılandırma, ses.log) SALT OKUNUR;
      - RLIMIT_NICE/RTPRIO 0 (prlimit): WirePlumber'ın rt modülü önceliği yükseltemez (nice 10 kalır);
      - `--info-fd`: gerçek PID'i bildirir."""
    from . import yollar
    dz = dizin(cdir)
    a = [ao.arac("bwrap"), "--unshare-user", "--unshare-pid", "--as-pid-1", "--unshare-net", "--unshare-ipc",
         "--unshare-uts", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run"]
    maske: list[str] = []
    for m in ("/var/tmp", "/home", ao.gercek_ev(), "/mnt", "/media", "/srv", yollar.runtime_dir()):
        m = os.path.realpath(m) if m else ""
        if m and m != "/" and os.path.isdir(m) and not any(_alti(m, k) for k in ("/run", "/tmp", *maske)):
            maske.append(m)
            a += ["--tmpfs", m]
    a += ["--bind", dz, dz, "--bind", pulse_dizini(cdir), pulse_dizini(cdir), "--ro-bind", conf_dizini(cdir),
          conf_dizini(cdir), "--chdir", dz, "--new-session", "--info-fd", str(info_fd), "--",
          ao.arac("prlimit"), "--nice=0", "--rtprio=0", "--", *argv]
    return a


def pactl(cdir: str, *a, sure: float = 5.0, soket: str | None = None) -> subprocess.CompletedProcess | None:
    p = ao.arac("pactl", zorunlu=False)
    if not p:
        return None
    try:
        return subprocess.run([p, *a], capture_output=True, text=True, timeout=sure, env=istemci_ortami(cdir, soket))
    except (OSError, subprocess.TimeoutExpired):
        return None


def kaynaklar_ve_cikislar(cdir: str, d: dict | None = None) -> tuple[list[str], list[str]]:
    """Özel sunucudaki (cikislar, kaynaklar) adları. d (durum kaydı) verilirse bağlantı soket_denetle'nin denetlenmiş
    bağı üzerinden kurulur; denetim geçmezse ([], [])."""
    soket = None
    if d is not None:
        try:
            soket = soket_denetle(cdir, d)
        except (Dur, OSError):
            return [], []

    def adlar(tur):
        r = pactl(cdir, "list", "short", tur, soket=soket)
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


# Ad alanının 1 numaralı süreci (bash): üç sunucuyu başlatır, SIGTERM'de onları kapatır (ata ad alanından gelen sinyal
# yalnız işleyicisi olan init'e ulaşır), biri ölürse (`wait -n`: bash'e özgü; dash'te yok) diğerlerini de kapatıp çıkar
# (yarım sunucu/bayat soket kalmaz; hazir() ölü sunucuyu görür, sonraki listen yeniden kurar). Sunucu çıktıları ayrı
# dosyaya değil, yöneticinin stdout'una (Deskhand'in açıp verdiği, boyutu sınırlanan ses.log) gider.
YONETICI = """\
trap 'kill -TERM $c $b $a 2>/dev/null; wait; exit 0' TERM INT HUP
"$1" -c "$4" & a=$!
i=0
while [ ! -S pipewire-0 ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i+1)); done
"$2" -p policy & b=$!
"$3" -c "$5" & c=$!
wait -n
kill -TERM $c $b $a 2>/dev/null
( sleep 3; kill -KILL $c $b $a 2>/dev/null ) & k=$!
wait $a $b $c 2>/dev/null
kill $k 2>/dev/null
exit 1
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


def _gunluk_ac(cdir: str):
    """ses.log: Deskhand açar (`ses-conf/` taze, sunucuya salt okunur), O_EXCL|O_NOFOLLOW; sunucunun stdout/stderr'i olarak
    verilir (sunucu günlük dosyasını kendisi açmaz). Boyutu LOG_SINIRI ile sınırlıdır (gunluk_sinirla)."""
    fd = os.open(_log_yolu(cdir), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    return os.fdopen(fd, "ab")


def _baslat(d: dict, cdir: str) -> subprocess.Popen:
    """Üç ses sürecini TEK bwrap ad alanında (sunucu_argv; PipeWire istemcileri farklı PID ad alanlarında veri akışı
    kuramıyor, ölçüldü), kafeste, nice 10 + ionice idle başlat. Kaydedilen PID'ler: `ses_pw` = ad alanının 1 numaralı
    süreci (yönetici kabuk; öldürülünce çekirdek ad alanındaki her şeyi öldürür), `ses_wp`/`ses_pulse` = gerçek sunucu
    süreçleri (soket_denetle karşı uç denetimi). Bulunamazsa OSError."""
    dz, cf = dizin(cdir), conf_dizini(cdir)
    argv = [ao.arac("bash"), "-c", YONETICI, "deskhand-ses", ao.arac("pipewire"), ao.arac("wireplumber"),
            ao.arac("pipewire-pulse"), os.path.join(cf, "pw.conf"), os.path.join(cf, "pulse.conf")]
    r, w = os.pipe()
    try:
        with _gunluk_ac(cdir) as log:
            p = ao.kafeste_baslat(d, sunucu_argv(argv, cdir, w), _sunucu_ortami(dz), pass_fds=(w,),
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
        raise OSError(_("ses ad alanı kurulamadı (bkz. {log})").format(log=_log_yolu(cdir)))
    ao.pid_kaydet(d, "ses_pw", init)
    if not _bekle(lambda: set(SUREC_ADLARI.values()) <= set(_ad_alani_surecleri(init)) or p.poll() is not None, 8):
        raise OSError(_("ses süreçleri başlamadı (bkz. {log})").format(log=os.path.join(dz, "ses_*.log")))
    bulunan = _ad_alani_surecleri(init)
    for ad, comm in SUREC_ADLARI.items():
        if comm not in bulunan:
            raise OSError(_("{ad} çalışmadı (bkz. {log})").format(ad=comm, log=os.path.join(dz, f"{ad}.log")))
        ao.pid_kaydet(d, ad, bulunan[comm])
    return p


def _yaz_yeni(yol: str, metin: str) -> None:
    """Yeni dosya (O_EXCL|O_NOFOLLOW: var olan dosya/sembolik bağ üzerine yazma yok), 0600."""
    fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(metin)


def kur(d: dict, cdir: str) -> str | None:
    """Oturumun özel ses sunucusunu başlat (zaten HAZIRSA dokunma: hazir = güvenli soket + doğrulanmış süreçler +
    bağlanılabilir; ölü/yarım sunucu ya da bayat soket yeniden kurulur). → uyarı metni | None (hazır). Yeniden kurulumda
    önce eski kayıtlı süreçler kapatılır, sonra sunucunun yazabildiği `ses/` ve `ses-pulse/` (ve Deskhand'in kendi
    `ses-conf/`, `ses-istemci/` dizinleri) `shutil.rmtree` ile SİLİNİP sıfırdan 0700 yaratılır: eski örneğin bıraktığı
    sembolik bağ/dosya hiçbir adımda izlenmez. Başarısızlıkta kurulan süreçler kapatılır, d["ses"] = None (özellik
    kapalı: uygulamalar hiç ses sunucusu görmez)."""
    if hazir(d, cdir):
        return None
    kapat(d)  # yarım kalmış/eski kurulumun kayıtlı süreçleri (doğrulanmış PID'ler)
    eksik = eksik_araclar()
    if eksik:
        d["ses"] = None
        return _("dinleme kapalı: {araclar} yok (özel ses sunucusu kurulamadı)").format(araclar=", ".join(eksik))
    dz, cf = dizin(cdir), conf_dizini(cdir)
    try:
        for y in (dz, cf, pulse_dizini(cdir), istemci_dizini(cdir)):
            sifirla(y)
        for alt in ("cfg", "state", "cache", "data"):
            os.mkdir(os.path.join(dz, alt), 0o700)
        _istemci_hazirla(cdir)
        if max(len(pulse_soketi(cdir)), len(os.path.join(dz, PW_SOKET + "-manager")),
               len(os.path.join(istemci_dizini(cdir), "pulse-native"))) >= 100:  # AF_UNIX sınırı (108)
            raise OSError(_("oturum dizini yolu çok uzun (soket yolu 108 bayt sınırı)"))
        _yaz_yeni(os.path.join(cf, "pw.conf"), PW_YAPILANDIRMA % {"sink": SINK})
        _yaz_yeni(os.path.join(cf, "pulse.conf"), PULSE_YAPILANDIRMA % {"dizin": pulse_dizini(cdir), "soket": PULSE_SOKET})
        pp = _baslat(d, cdir)
        if not _bekle(lambda: soket_hazir(cdir) or pp.poll() is not None, 8):
            raise OSError(_("pipewire-pulse soketi açılmadı"))
        if not _bekle(lambda: SINK in kaynaklar_ve_cikislar(cdir, d)[0], 8, 0.15):
            raise OSError(_("özel boş çıkış ({sink}) görünmedi").format(sink=SINK))
        sinks, sources = kaynaklar_ve_cikislar(cdir, d)
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


def saglik(cdir: str, d: dict | None = None) -> bool:
    """Özel sunucu soketi hazır ve boş çıkış görünüyor mu. d (durum kaydı) verilirse sunucunun yaşadığı (hazir) da
    denetlenir ve sorgu denetlenmiş bağ üzerinden yapılır."""
    if not (hazir(d, cdir) if d is not None else soket_hazir(cdir)):
        return False
    return SINK in kaynaklar_ve_cikislar(cdir, d)[0]
