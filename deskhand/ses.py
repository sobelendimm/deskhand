"""Görünmez masaüstü için OTURUMA ÖZEL ses sunucusu (dinleme, docs/PLAN_TUR3.md §5).

Her masaüstü kendi küçük PipeWire + WirePlumber + pipewire-pulse örneğini alır (oturum dizininde `ses/`, soketler
orada). Örnek DONANIM bilmez: yapılandırma ALSA/Bluetooth/kamera eklentisini yüklemez, WirePlumber yalnız `policy`
profiliyle (bağlantı politikası; donanım izleyicisi yok) çalışır. İçinde yalnız `deskhand-sessiz` boş çıkışı (ve onun
monitörü) vardır: mikrofon yok. Arka plan uygulamalarına bwrap ad alanında YALNIZ bu dizin (salt okunur) bağlanır;
kullanıcının gerçek ses sunucusu soketi ad alanında görünmez (arka_ortak.korumali_argv: /run/user/UID boş tmpfs).
Sonuç: uygulamanın sesi kullanıcının hoparlörüne/kulaklığına ASLA gitmez; Deskhand aynı örneğin monitöründen kayıt alır
(dinleme.py). Kurulamıyorsa özellik kapalı kalır (uyarı), uygulamalar eskisi gibi hiç ses sunucusu görmez.

Süreçler masaüstünün bellek kafesinde başlar (arka_ortak.kafeste_baslat) ve kapatmada çekirdek süreç listesiyle
(`ses_pulse`, `ses_wp`, `ses_pw`) sinyallenir; oturum dizini silinince soketler de gider."""
from __future__ import annotations

import os
import stat
import subprocess
import time

from . import arka_ortak as ao
from .i18n import _

SINK = "deskhand-sessiz"
DIZIN = "ses"            # <oturum çalışma dizini>/ses
PULSE_SOKET = "native"   # <dizin>/native  (PULSE_SERVER=unix:...)
PW_SOKET = "pipewire-0"  # <dizin>/pipewire-0  (PIPEWIRE_REMOTE)
SURECLER = ("ses_pulse", "ses_wp", "ses_pw")  # kapatma sırası
ARACLAR = ("pipewire", "wireplumber", "pipewire-pulse", "pactl", "parec")

PW_YAPILANDIRMA = """\
# Deskhand: oturuma özel PipeWire (donanım yok: yalnız boş çıkış)
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
    { name = libpipewire-module-access args = { } }
    { name = libpipewire-module-spa-device-factory }
    { name = libpipewire-module-spa-node-factory }
    { name = libpipewire-module-client-node }
    { name = libpipewire-module-client-device }
    { name = libpipewire-module-adapter }
    { name = libpipewire-module-link-factory }
    { name = libpipewire-module-session-manager }
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
# Deskhand: oturuma özel pipewire-pulse (yalnız bu dizindeki soket)
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
}
pulse.rules = [ ]
"""


def dizin(cdir: str) -> str:
    return os.path.join(cdir, DIZIN)


def soket_hazir(cdir: str | None) -> bool:
    """`<oturum>/ses/native` kullanıcıya ait gerçek bir soket mi? (Kayıttaki alanlara GÜVENİLMEZ: yol çalışma
    dizininden kurulur; uygulama ortamı ve bağları bu denetime dayanır.)"""
    if not cdir:
        return False
    try:
        st = os.lstat(os.path.join(dizin(cdir), PULSE_SOKET))
        dt = os.lstat(dizin(cdir))
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid() and stat.S_ISDIR(dt.st_mode) and \
        (dt.st_mode & 0o777) == 0o700


def eksik_araclar() -> list[str]:
    return [a for a in ARACLAR if not ao.arac(a, zorunlu=False)]


def istemci_ortami(dz: str) -> dict:
    """pactl/parec gibi Deskhand'in kendi istemcileri için TEMİZ ortam: yalnız özel sunucu (kullanıcınınki yok)."""
    return {"PATH": ao.GUVENLI_PATH, "HOME": dz, "XDG_RUNTIME_DIR": dz, "XDG_CONFIG_HOME": os.path.join(dz, "cfg"),
            "PULSE_SERVER": f"unix:{os.path.join(dz, PULSE_SOKET)}", "PULSE_RUNTIME_PATH": dz,
            "PIPEWIRE_REMOTE": os.path.join(dz, PW_SOKET), "PIPEWIRE_RUNTIME_DIR": dz,
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _sunucu_ortami(dz: str) -> dict:
    e = istemci_ortami(dz)
    e.update({"XDG_STATE_HOME": os.path.join(dz, "state"), "XDG_CACHE_HOME": os.path.join(dz, "cache"),
              "XDG_DATA_HOME": os.path.join(dz, "data")})
    return e


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


def _baslat(d: dict, dz: str, ad: str, argv: list[str]) -> subprocess.Popen:
    with open(os.path.join(dz, f"{ad}.log"), "ab") as log:
        p = ao.kafeste_baslat(d, argv, _sunucu_ortami(dz), stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    ao.pid_kaydet(d, ad, p.pid)
    return p


def kur(d: dict, cdir: str) -> str | None:
    """Oturumun özel ses sunucusunu başlat (zaten hazırsa dokunma). → uyarı metni | None (hazır). Başarısızlıkta
    kurulan süreçler kapatılır, d["ses"] = None (özellik kapalı: uygulamalar hiç ses sunucusu görmez)."""
    if soket_hazir(cdir) and (d.get("pid") or {}).get("ses_pw"):
        return None
    eksik = eksik_araclar()
    if eksik:
        d["ses"] = None
        return _("dinleme kapalı: {araclar} yok (özel ses sunucusu kurulamadı)").format(araclar=", ".join(eksik))
    dz = dizin(cdir)
    try:
        os.makedirs(dz, mode=0o700, exist_ok=True)
        os.chmod(dz, 0o700)
        for alt in ("cfg", "state", "cache", "data"):
            os.makedirs(os.path.join(dz, alt), mode=0o700, exist_ok=True)
        if len(os.path.join(dz, PW_SOKET + "-manager")) >= 100:  # AF_UNIX yol sınırı (108)
            raise OSError(_("oturum dizini yolu çok uzun (soket yolu 108 bayt sınırı)"))
        with open(os.path.join(dz, "pw.conf"), "w") as f:
            f.write(PW_YAPILANDIRMA % {"sink": SINK})
        with open(os.path.join(dz, "pulse.conf"), "w") as f:
            f.write(PULSE_YAPILANDIRMA % {"dizin": dz, "pulse": PULSE_SOKET})
        pw = _baslat(d, dz, "ses_pw", [ao.arac("pipewire"), "-c", os.path.join(dz, "pw.conf")])
        if not _bekle(lambda: os.path.exists(os.path.join(dz, PW_SOKET)) or pw.poll() is not None, 5):
            raise OSError(_("pipewire açılmadı"))
        if pw.poll() is not None:
            raise OSError(_("pipewire çalışmadı (bkz. {log})").format(log=os.path.join(dz, "ses_pw.log")))
        _baslat(d, dz, "ses_wp", [ao.arac("wireplumber"), "-p", "policy"])
        pp = _baslat(d, dz, "ses_pulse", [ao.arac("pipewire-pulse"), "-c", os.path.join(dz, "pulse.conf")])
        if not _bekle(lambda: soket_hazir(cdir) or pp.poll() is not None, 5):
            raise OSError(_("pipewire-pulse soketi açılmadı"))
        if not _bekle(lambda: SINK in kaynaklar_ve_cikislar(dz)[0], 8, 0.15):
            raise OSError(_("özel boş çıkış ({sink}) görünmedi").format(sink=SINK))
        sinks, sources = kaynaklar_ve_cikislar(dz)
        if sinks != [SINK] or any(not s.endswith(".monitor") for s in sources):
            raise OSError(_("özel ses sunucusunda beklenmeyen aygıt var: {a}").format(a=sinks + sources))
    except (OSError, ao.Dur) as e:
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
