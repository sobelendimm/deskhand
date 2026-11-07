"""Görünmez ikinci masaüstü (sanal arka uç) yaşam döngüsü: `deskhand masaustu baslat|durdur|durum`.

Bileşenler (hepsi TEK bellek kafesinde: systemd-run --user --scope -p MemoryMax=… + nice 10 + ionice idle):
  Xvfb :N          görünmez X ekranı (-nolisten tcp, -noreset), kök zemin düz gri (OCR ön işlemesi siyahta bozuluyor)
  openbox          küçük pencere yöneticisi (akıllı yerleşim, yeni pencere odak alır, menü yok); yoksa uyarıyla çalışır
  dbus-daemon      ÖZEL oturum veri yolu: arka plan uygulamaları kullanıcının oturumundaki tek-örnek uygulamalara
                   devredilmez; yalnız izin verilen servisler (erişilebilirlik) etkinleştirilebilir
  bildirim         org.freedesktop.Notifications yakalayıcı → STATE_DIR/bildirimler.jsonl (kullanıcıya düşmez)
  ses              `deskhand-sessiz` boş çıkış (null sink): arka plan sesi kullanıcının kulaklığına gitmez

  ses bekçisi      ses_bekcisi.py: arka plan akışı boş çıkıştan başka bir çıkışa düşerse susturur ve kapatır

Durum: RUNTIME_DIR/sanal.json. Uygulama başlatma: `baslat(argv, env)` (ortam + kafes).
Tek seferde tek sanal masaüstü (aynı null sink adı, aynı durum dosyası).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time

from . import yollar
from .hata import ARAC_EKSIK, SANAL_KAPALI, Dur
from .i18n import _, h_
from .komutlar import MASAUSTU, SECENEKLER, cevirici, secimler

SINK = "deskhand-sessiz"
ILK_EKRAN = 90
ZEMIN = 0x8C8C8C  # düz orta gri: siyah kök OCR ön işlemesini (yerel zemin kutupluluğu) bozuyordu
VARSAYILAN_BOYUT = "1920x1080x24"
VARSAYILAN_BELLEK = "4G"
VARSAYILAN_TAKAS = "0"  # kafes takasa taşmasın (DESKHAND_SANAL_TAKAS): sınırda kafes içinde OOM, sistem yavaşlamaz
# Özel veri yolunda etkinleştirilebilecek servisler (gerisi kapalı: kwalletd, kded, kdeconnect, plasma
# bildirimleri… ikinci örnekleri kullanıcının dosyalarını/oturumunu bozabilir).
IZINLI_SERVISLER = {"org.a11y.Bus": "/usr/lib/at-spi-bus-launcher"}
# Kullanıcının Wayland oturumuna ait, arka plan uygulamasına geçmemesi gereken değişkenler
SILINECEK_ORTAM = ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY", "DESKTOP_STARTUP_ID",
                   "XDG_ACTIVATION_TOKEN", "SESSION_MANAGER", "DBUS_SESSION_BUS_PID", "DBUS_STARTER_ADDRESS",
                   "DBUS_STARTER_BUS_TYPE", "GDK_SCALE", "QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS")
# WAYLAND_DISPLAY SİLİNMEZ, var olmayan MUTLAK bir yola ayarlanır: değişken yoksa libwayland (ve flatpak'ın
# --socket=wayland bağlaması) varsayılan $XDG_RUNTIME_DIR/wayland-0'a bağlanır = kullanıcının GERÇEK compositor'ı
# (ölçüldü: sahte wayland-0 soketi bağlantı aldı). Mutlak yol hiç oluşturulmaz (çalışma klasörü 0700, sanal-N içinde).
WAYLAND_YOK = "wayland-yok"
# Kafes kapısı: süreç kafese alınana dek bekler (borudan bir satır), sonra programı çalıştırır. Böylece
# erken çatallanan uygulamaların (tarayıcı içerik süreçleri) çocukları da kafesin içinde doğar.
# {fd}: kapı borusunun okuma ucu (pass_fds numarayı korur)
KAPI = 'read -r _ <&{fd} && exec {fd}<&- && exec "$@"'


# Özel veri yolu hazır olunca (bildirim yakalayıcıdan ve pencere yöneticisinden ÖNCE) çağrılan kancalar:
# f(adres: str, durum: dict). Faz 3 anahtarlık rölesi (deskhand/oturum/) buraya takılır. Kanca hatası masaüstünü
# düşürmez, uyarı olur; kanca süreç başlatacaksa kafes için kafeste_baslat(durum, argv, env) kullanmalı.
OZEL_VERI_YOLU_KANCALARI: list = []


def ozel_veri_yolu_kancasi(f):
    """Kanca ekle (bezeyici olarak da kullanılabilir). Aynı işlev iki kez eklenmez."""
    if f not in OZEL_VERI_YOLU_KANCALARI:
        OZEL_VERI_YOLU_KANCALARI.append(f)
    return f


# ---------------------------------------------------------------- yollar

def durum_yolu() -> str:
    return os.path.join(yollar.runtime_dir(), "sanal.json")


def devral_yolu() -> str:
    """Arayüzün "Devral" bayrağı: varsa insan sanal masaüstünü kullanıyor (ajan bekler / 12)."""
    return os.path.join(yollar.runtime_dir(), "devral")


def _surec_baslangic(pid) -> str | None:
    """/proc/PID/stat'ın 22. alanı (süreç başlangıç zamanı): PID yeniden kullanımına karşı."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            s = f.read()
        return s[s.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def devral_icerik(pid: int | None = None) -> str:
    """Devral dosyasının içeriği: "panel <pid> <başlangıç>\\n" (panel çökerse bayrak sahipsiz kalır → devral_var False)."""
    pid = os.getpid() if pid is None else int(pid)
    return f"panel {pid} {_surec_baslangic(pid) or '-'}\n"


def devral_yaz(pid: int | None = None, yol: str | None = None) -> str:
    """Devral bayrağını (atomik) yaz. → yol."""
    yol = yol or devral_yolu()
    os.makedirs(os.path.dirname(yol), mode=0o700, exist_ok=True)
    gecici = f"{yol}.{os.getpid()}"
    with open(gecici, "w") as f:
        f.write(devral_icerik(pid))
    os.replace(gecici, yol)
    return yol


def devral_sahibi(yol: str | None = None) -> int | None:
    """Devral dosyasını yazan CANLI sürecin PID'i; dosya yok / bozuk / süreç ölmüş / PID başka sürece geçmişse None."""
    try:
        with open(yol or devral_yolu()) as f:
            p = f.read(200).split()
    except OSError:
        return None
    if len(p) < 3 or p[0] != "panel":
        return None
    try:
        pid = int(p[1])
    except ValueError:
        return None
    if pid <= 0 or _surec_baslangic(pid) != p[2] or not _canli(pid):
        return None
    return pid


def devral_var(yol: str | None = None) -> bool:
    """İnsan sanal masaüstünü kullanıyor mu: dosya VAR ve yazan süreç (panel) yaşıyor."""
    return devral_sahibi(yol) is not None


def devral_sil(yalniz_kendi: bool = True, yol: str | None = None) -> bool:
    """Devral dosyasını sil. yalniz_kendi: yalnız bu süreç yazdıysa ya da sahipsizse (sahibi ölmüş/bozuk).
    → silindi mi."""
    yol = yol or devral_yolu()
    if not os.path.exists(yol):
        return False
    if yalniz_kendi:
        sahip = devral_sahibi(yol)
        if sahip is not None and sahip != os.getpid():
            return False
    try:
        os.remove(yol)
        return True
    except FileNotFoundError:
        return False


def bildirim_yolu() -> str:
    return os.path.join(yollar.state_dir(), "bildirimler.jsonl")


def _calisma(no: int) -> str:
    return os.path.join(yollar.runtime_dir(), f"sanal-{no}")


def _kilit():
    os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
    f = open(os.path.join(yollar.runtime_dir(), "sanal.lock"), "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


# ---------------------------------------------------------------- yardımcılar

def boyut_coz(s: str | None = None) -> tuple[int, int, int]:
    s = (s or os.environ.get("DESKHAND_SANAL_BOYUT") or VARSAYILAN_BOYUT).lower().strip()
    p = s.split("x")
    try:
        g, y = int(p[0]), int(p[1])
        d = int(p[2]) if len(p) > 2 else 24
    except (ValueError, IndexError):
        raise Dur(1, _("DESKHAND_SANAL_BOYUT GENxYÜK[x24] olmalı: {deger}").format(deger=repr(s)))
    if not (320 <= g <= 8192 and 240 <= y <= 8192) or d != 24:
        raise Dur(1, _("geçersiz sanal ekran boyutu: {deger} (derinlik yalnız 24)").format(deger=repr(s)))
    return g, y, d


def bos_ekran(bas: int = ILK_EKRAN) -> int:
    """:90'dan başlayarak soketi ve kilit dosyası olmayan ilk X ekran numarası."""
    for n in range(bas, bas + 200):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
            return n
    raise Dur(ARAC_EKSIK, _("boş X ekran numarası bulunamadı"))


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


def kafeste_baslat(d: dict, argv: list[str], env: dict, **popen) -> subprocess.Popen:
    """argv'yi nice 10 + ionice idle ile, kafese ALINDIKTAN SONRA çalıştır (kapı: fd 3)."""
    if not argv:
        raise Dur(1, _("başlatılacak komut boş"))
    tam = [*_oncelik(), *argv]
    kafes = d.get("kafes")
    if not kafes:  # kafes kapalı (DESKHAND_SANAL_BELLEK=0): yalnız öncelik
        return subprocess.Popen(tam, env=env, start_new_session=True, **popen)
    r, w = os.pipe()
    try:
        p = subprocess.Popen(["sh", "-c", KAPI.format(fd=r), "deskhand-kapi", *tam], env=env, pass_fds=(r,),
                             start_new_session=True, **popen)
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


def uygulama_ortami(d: dict, env: dict | None = None) -> dict:
    """Arka plan uygulamasının ortamı: os.environ + env (ek/değişen değişkenler), üstüne sanal masaüstü
    değerleri ZORLA yazılır (kullanıcının Wayland ekranına/oturum veri yoluna/sesine kaçamasın)."""
    e = dict(os.environ)
    if env:
        e.update(env)
    for k in SILINECEK_ORTAM:
        e.pop(k, None)
    e.update({
        "WAYLAND_DISPLAY": os.path.join(_calisma(d["no"]), WAYLAND_YOK),  # var olmayan mutlak yol (yukarıya bkz.)
        "DISPLAY": d["ekran"],
        "DBUS_SESSION_BUS_ADDRESS": d["dbus_adres"],
        "XDG_SESSION_TYPE": "x11",
        # Chromium/Electron anahtarlık arka ucunu bunlardan seçer (Faz 3 anahtarlık rölesi aynı veri yolunda)
        "XDG_CURRENT_DESKTOP": "KDE",
        "KDE_SESSION_VERSION": "6",
        "QT_QPA_PLATFORM": "xcb",
        "GDK_BACKEND": "x11",
        "MOZ_ENABLE_WAYLAND": "0",
        "SDL_VIDEODRIVER": "x11",
        "SDL_VIDEO_DRIVER": "x11",
        "ELECTRON_OZONE_PLATFORM_HINT": "x11",
        "DESKHAND_SANAL": d["ekran"],
    })
    if d.get("kimlik"):  # durdururken kafes dışındaki/kafessiz süreçler de bulunabilsin (_isaretli_surecler)
        e["DESKHAND_SANAL_KIMLIK"] = d["kimlik"]
    ses = d.get("ses") or {}
    if ses.get("sink"):
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
        yok = os.path.join(_calisma(d["no"]), "ses-yok")
        e["PULSE_SERVER"] = f"unix:{yok}"
        e["PIPEWIRE_REMOTE"] = yok
        e.pop("PULSE_SINK", None)
    return e


# ---------------------------------------------------------------- durum

def durum_oku() -> dict | None:
    try:
        with open(durum_yolu()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _durum_yaz(d: dict) -> None:
    os.makedirs(yollar.runtime_dir(), mode=0o700, exist_ok=True)
    gecici = durum_yolu() + f".{os.getpid()}"
    with open(gecici, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(gecici, durum_yolu())


def _xvfb_mi(d: dict) -> bool:
    pid = (d.get("pid") or {}).get("xvfb")
    kom = _komut_satiri(pid)
    return _canli(pid) and any(os.path.basename(k) == "Xvfb" for k in kom) and d.get("ekran") in kom


def durum(dogrula: bool = True, saglik: bool = True) -> dict | None:
    """Çalışan sanal masaüstünün durumu; yoksa None. dogrula: Xvfb (PID + komut satırı + soket) canlı mı.
    saglik: bileşen ayrıntısı d["saglik"] içinde (pactl çağırır; girdi yolunda saglik=False: <1 ms)."""
    d = durum_oku()
    if d is None or not dogrula:
        return d
    if not (_xvfb_mi(d) and os.path.exists(f"/tmp/.X11-unix/X{d.get('no')}")):
        return None
    if not saglik:
        return d
    pid = d.get("pid") or {}
    saglik = {ad: _canli(p) for ad, p in pid.items()}
    ses = d.get("ses") or {}
    if ses.get("modul") is not None:
        saglik["ses"] = _sink_modulu(ses.get("sink")) == ses.get("modul")
    d["saglik"] = saglik
    return d


def gerekli() -> dict:
    """Çalışan masaüstü ya da Dur(14)."""
    d = durum()
    if d is None:
        raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
    return d


# ---------------------------------------------------------------- ses

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


# ---------------------------------------------------------------- openbox / dbus yapılandırması

RC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!-- deskhand: sanal masaüstü için en küçük openbox yapılandırması (otomatik yazılır) -->
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance><strength>0</strength><screen_edge_strength>0</screen_edge_strength></resistance>
  <focus><focusNew>yes</focusNew><followMouse>no</followMouse><focusLast>yes</focusLast>
    <underMouse>no</underMouse><raiseOnFocus>no</raiseOnFocus></focus>
  <placement><policy>Smart</policy><center>yes</center><monitor>Primary</monitor>
    <primaryMonitor>1</primaryMonitor></placement>
  <theme><name>Clearlooks</name><titleLayout>NLIMC</titleLayout><keepBorder>yes</keepBorder>
    <animateIconify>no</animateIconify></theme>
  <desktops><number>1</number><firstdesk>1</firstdesk><popupTime>0</popupTime></desktops>
  <resize><drawContents>yes</drawContents><popupShow>Never</popupShow></resize>
  <margins><top>0</top><bottom>0</bottom><left>0</left><right>0</right></margins>
  <keyboard>
    <keybind key="A-F4"><action name="Close"/></keybind>
  </keyboard>
  <mouse>
    <dragThreshold>3</dragThreshold><doubleClickTime>400</doubleClickTime>
    <!-- Frame bağlamı istemciyi de kapsar ve tıklamayı uygulamaya GERİ VERMEZ: düz Left burada tıklamaları
         yutuyordu. Yalnız Alt+sürükle (taşı); tıkla-odakla Client bağlamında (olay uygulamaya iletilir). -->
    <context name="Frame">
      <mousebind button="A-Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="A-Left" action="Drag"><action name="Move"/></mousebind>
    </context>
    <context name="Client">
      <mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="Middle" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="Right" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
    </context>
    <context name="Titlebar">
      <mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="Left" action="Drag"><action name="Move"/></mousebind>
      <mousebind button="Left" action="DoubleClick"><action name="ToggleMaximize"/></mousebind>
    </context>
    <context name="Top"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="Bottom"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="Left"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="Right"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="BLCorner"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="BRCorner"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="TLCorner"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="TRCorner"><mousebind button="Left" action="Drag"><action name="Resize"/></mousebind></context>
    <context name="Close"><mousebind button="Left" action="Click"><action name="Close"/></mousebind></context>
    <context name="Maximize"><mousebind button="Left" action="Click"><action name="ToggleMaximize"/></mousebind></context>
    <context name="Iconify"><mousebind button="Left" action="Click"><action name="Iconify"/></mousebind></context>
  </mouse>
  <menu><file>{menu}</file><hideDelay>200</hideDelay></menu>
  <applications/>
</openbox_config>
"""
MENU_XML = """<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu"><menu id="root-menu" label="deskhand"></menu></openbox_menu>
"""


def _openbox_yapilandir() -> str:
    d = os.path.join(yollar.data_dir(), "sanal")
    os.makedirs(d, exist_ok=True)
    menu = os.path.join(d, "openbox-menu.xml")
    rc = os.path.join(d, "openbox-rc.xml")
    for yol, ic in ((menu, MENU_XML), (rc, RC_XML.replace("{menu}", menu))):
        try:
            with open(yol) as f:
                if f.read() == ic:
                    continue
        except OSError:
            pass
        with open(yol, "w") as f:
            f.write(ic)
    return rc


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
  </policy>
  <limit name="service_start_timeout">60000</limit>
</busconfig>
""")
    return conf, f"unix:path={soket}"


# ---------------------------------------------------------------- başlat / durdur


def guvenli_ekran(ekran) -> str:
    """Sanal ekran adını doğrular. Boş/None ekran adıyla Xlib $DISPLAY'e (kullanıcının GERÇEK XWayland ekranı)
    bağlanır ve XTEST girdisi kullanıcının masaüstüne gidebilir → bu asla olmamalı. Yalnız ':N' biçimi ve
    kullanıcının oturum ekranından farklı bir ekran kabul edilir."""
    e = (ekran or "").strip()
    if not re.fullmatch(r":\d+", e):
        raise Dur(SANAL_KAPALI, _("geçersiz sanal ekran adı: {ekran}").format(ekran=repr(ekran)))
    gercek = {os.environ.get("DESKHAND_GERCEK_DISPLAY", ""), os.environ.get("DISPLAY", "")} - {""}
    if any(e == g.split(".")[0] for g in gercek) and os.environ.get("DESKHAND_SANAL_ICINDE") != "1":
        raise Dur(SANAL_KAPALI, _("sanal ekran adı kullanıcının gerçek ekranıyla aynı ({ekran}); bağlanılmadı").format(ekran=e))
    return e


def _bekle(kosul, sure: float, aralik: float = 0.02) -> bool:
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if kosul():
            return True
        time.sleep(aralik)
    return bool(kosul())


def _x_baglan(ekran: str):
    from Xlib import display
    return display.Display(guvenli_ekran(ekran))


def _zemin_boya(ekran: str) -> None:
    dp = _x_baglan(ekran)
    try:
        kok = dp.screen().root
        kok.change_attributes(background_pixel=ZEMIN)
        kok.clear_area(0, 0, 0, 0)
        dp.sync()
    finally:
        dp.close()


def _wm_hazir(ekran: str) -> bool:
    try:
        dp = _x_baglan(ekran)
    except Exception:
        return False
    try:
        a = dp.intern_atom("_NET_SUPPORTING_WM_CHECK")
        p = dp.screen().root.get_full_property(a, 0)
        return bool(p and p.value and p.value[0])
    except Exception:
        return False
    finally:
        dp.close()


def _gunluk_dosyasi(cdir: str, ad: str):
    return open(os.path.join(cdir, f"{ad}.log"), "ab")


def masaustu_baslat(boyut: str | None = None, openbox: bool = True) -> dict:
    """Sanal masaüstünü başlat (zaten açıksa durumunu döndürür). Hata olursa başlatılan her şeyi kapatır."""
    with _kilit():
        d = durum()
        if d is not None:
            d["zaten"] = True
            return d
        eski = durum_oku()
        if eski is not None:  # ölü masaüstünden kalanlar (çökme): temizle
            _kapat_ic(eski)
        for arac in ("Xvfb", "dbus-daemon", "nice", "ionice", "sh"):
            if not shutil.which(arac):
                raise Dur(ARAC_EKSIK, _("{arac} yok (Xvfb: xorg-server-xvfb paketi)").format(arac=arac))
        g, y, derinlik = boyut_coz(boyut)
        bellek = _bellek_siniri()
        takas = _takas_siniri() if bellek else None
        if bellek and not shutil.which("systemd-run"):
            raise Dur(ARAC_EKSIK, _("systemd-run yok: bellek kafesi kurulamaz (bilerek kapatmak için DESKHAND_SANAL_BELLEK=0)"))
        no = bos_ekran()
        cdir = _calisma(no)
        os.makedirs(cdir, mode=0o700, exist_ok=True)
        d = {"surum": 1, "no": no, "ekran": f":{no}", "boyut": [g, y, derinlik], "kafes": None, "cgroup": "",
             "bellek": bellek, "takas": takas, "pid": {}, "dbus_adres": "", "ses": None, "openbox": False,
             "baslangic": time.time(), "kimlik": secrets.token_hex(8), "calisma": cdir, "uyarilar": []}
        try:
            _baslat_ic(d, cdir, openbox)
        except BaseException:
            try:
                _kapat_ic(d)
            finally:
                shutil.rmtree(cdir, ignore_errors=True)
            raise
        _durum_yaz(d)
        return d


def _baslat_ic(d: dict, cdir: str, openbox: bool) -> None:
    no, (g, y, derinlik) = d["no"], d["boyut"]
    xvfb = ["Xvfb", d["ekran"], "-screen", "0", f"{g}x{y}x{derinlik}", "-nolisten", "tcp", "-noreset",
            "-dpi", "96"]
    ortam_x = {k: v for k, v in os.environ.items() if k not in SILINECEK_ORTAM}
    with _gunluk_dosyasi(cdir, "xvfb") as log:
        if d["bellek"]:
            kafes = f"deskhand-sanal-{no}-{os.getpid()}.scope"
            komut = ["systemd-run", "--user", "--scope", "--quiet", f"--unit={kafes}",
                     "-p", f"MemoryMax={d['bellek']}", "-p", f"MemorySwapMax={d.get('takas') or '0'}",
                     "-p", "Delegate=yes", "-p", "TimeoutStopSec=5",
                     "--", *_oncelik(), *xvfb]
            p = subprocess.Popen(komut, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 env=ortam_x | {"DBUS_SESSION_BUS_ADDRESS":
                                                _kullanici_bus_ortami()["DBUS_SESSION_BUS_ADDRESS"]},
                                 start_new_session=True)
            d["kafes"] = kafes
        else:
            d["uyarilar"].append(_("bellek kafesi KAPALI (DESKHAND_SANAL_BELLEK=0)"))
            p = subprocess.Popen([*_oncelik(), *xvfb], stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, env=ortam_x, start_new_session=True)
    d["pid"]["xvfb"] = p.pid
    soket = f"/tmp/.X11-unix/X{no}"
    if not _bekle(lambda: os.path.exists(soket) or p.poll() is not None, 8):
        raise Dur(ARAC_EKSIK, _("Xvfb 8 sn içinde açılmadı"))
    if p.poll() is not None:
        with open(os.path.join(cdir, "xvfb.log"), errors="replace") as f:
            raise Dur(ARAC_EKSIK, _("Xvfb çalışmadı: {hata}").format(hata=f.read()[-400:].strip()))
    # systemd-run --scope ve nice/ionice exec eder: PID artık Xvfb'nin kendisi
    if not _bekle(lambda: _xvfb_mi(d), 2):
        raise Dur(ARAC_EKSIK, _("Xvfb süreci doğrulanamadı (pid {pid}: {komut})").format(pid=p.pid, komut=_komut_satiri(p.pid)))
    if d["kafes"]:
        d["cgroup"] = _cgroup(p.pid)
        if not d["cgroup"].endswith("/" + d["kafes"]):
            raise Dur(ARAC_EKSIK, _("Xvfb bellek kafesinde değil: {cgroup}").format(cgroup=repr(d["cgroup"])))
    bagli = False
    for _i in range(100):
        try:
            _zemin_boya(d["ekran"])
            bagli = True
            break
        except Exception:
            time.sleep(0.03)
    if not bagli:
        raise Dur(ARAC_EKSIK, _("Xvfb {ekran} ekranına bağlanılamadı").format(ekran=d["ekran"]))

    try:  # Türkçe harfler + sık noktalama boş tuş kodlarına (yazarken eşleme yarışı olmasın)
        from .arka_uc.sanal import kalici_klavye
        kalici_klavye(d["ekran"])
    except Exception as e:  # noqa: BLE001 - yalnız hız/sağlamlık; yoksa yazarken geçici eşlenir
        d["uyarilar"].append(_("kalıcı klavye eşlemesi yapılamadı: {hata}").format(hata=e))
    try:  # temiz başlangıç: basılı kalmış tuş/düğme olmasın (taze Xvfb'de normalde hiç yok)
        from .arka_uc.sanal import takili_birak
        takili_birak(d["ekran"])
    except Exception:  # noqa: BLE001
        pass

    # ses: özel D-Bus'tan ÖNCE (etkinleştirilen servisler dbus-daemon'un ortamını, yani sessiz çıkışı alır)
    ses, uyari = ses_kur(str(d["ekran"]).lstrip(":"))
    d["ses"] = ses
    if uyari:
        d["uyarilar"].append(uyari)
    if ses:  # ses bekçisi: arka plan akışı başka bir çıkışa düşerse sustur + kapat (ikinci savunma hattı)
        from . import ses_bekcisi
        with _gunluk_dosyasi(cdir, "ses-bekcisi") as log:
            p = kafeste_baslat(d, [sys.executable, "-I", ses_bekcisi.__file__, d.get("kafes") or ""],
                                uygulama_ortami(d), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log)
        d["pid"]["ses_bekcisi"] = p.pid
        satir = _satir_bekle(p, 5)
        if p.stdout:
            p.stdout.close()
        if satir != "hazir":
            d["uyarilar"].append(_("ses bekçisi hazır olmadı ({yanit})").format(yanit=satir or _("yanıt yok")))

    # özel D-Bus
    conf, adres = _dbus_yapilandir(cdir)
    d["dbus_adres"] = adres
    with _gunluk_dosyasi(cdir, "dbus") as log:
        p = kafeste_baslat(d, ["dbus-daemon", f"--config-file={conf}", "--nofork", "--nopidfile",
                                "--nosyslog"], uygulama_ortami(d), stdin=subprocess.DEVNULL, stdout=log,
                            stderr=log)
    d["pid"]["dbus"] = p.pid
    bus_soket = adres.split("=", 1)[1]
    if not _bekle(lambda: os.path.exists(bus_soket) or p.poll() is not None, 5) or p.poll() is not None:
        raise Dur(ARAC_EKSIK, _("özel D-Bus (dbus-daemon) açılmadı"))
    for kanca in list(OZEL_VERI_YOLU_KANCALARI):
        try:
            kanca(adres, d)
        except Exception as e:  # noqa: BLE001
            d["uyarilar"].append(_("özel veri yolu kancası {kanca} başarısız: {hata}").format(
                kanca=getattr(kanca, "__name__", kanca), hata=e))

    # bildirim yakalayıcı
    from . import bildirim_yakalayici
    os.makedirs(os.path.dirname(bildirim_yolu()), exist_ok=True)
    p = kafeste_baslat(d, [sys.executable, "-I", bildirim_yakalayici.__file__, adres, bildirim_yolu()],
                        uygulama_ortami(d), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=_gunluk_dosyasi(cdir, "bildirim"))
    d["pid"]["bildirim"] = p.pid
    satir = _satir_bekle(p, 5)
    if satir != "hazir":
        d["uyarilar"].append(_("bildirim yakalayıcı hazır olmadı ({yanit}): bildirimler kaybolabilir").format(
            yanit=satir or _("yanıt yok")))
    if p.stdout:
        p.stdout.close()

    # pencere yöneticisi
    if openbox and shutil.which("openbox"):
        rc = _openbox_yapilandir()
        ob_ortam = uygulama_ortami(d) | {"XDG_CACHE_HOME": os.path.join(cdir, "cache"),
                                         "XDG_CONFIG_HOME": os.path.join(cdir, "config")}
        with _gunluk_dosyasi(cdir, "openbox") as log:
            p = kafeste_baslat(d, ["openbox", "--config-file", rc, "--sm-disable"], ob_ortam,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        d["pid"]["openbox"] = p.pid
        if _bekle(lambda: _wm_hazir(d["ekran"]) or p.poll() is not None, 5) and p.poll() is None:
            d["openbox"] = True
        else:
            d["uyarilar"].append(_("openbox başlamadı: pencereler 0,0'da üst üste açılır"))
    elif openbox:
        d["uyarilar"].append(_("openbox yok (sudo pacman -S openbox): pencereler 0,0'da üst üste açılır"))


def _satir_bekle(p: subprocess.Popen, sure: float) -> str:
    import select
    if p.stdout is None:
        return ""
    r, _, _ = select.select([p.stdout], [], [], sure)
    if not r:
        return ""
    return p.stdout.readline().decode(errors="replace").strip()


def _sinyal(pids, sig) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _kapat_ic(d: dict) -> list[str]:
    """PID ile kapat: önce kafesteki uygulamalar, sonra çekirdek (bildirim, openbox, dbus, Xvfb). Ses modülü
    EN SON: akışı hâlâ açık bir uygulama varken boş çıkış kaldırılırsa ses varsayılan çıkışa düşerdi."""
    notlar = []
    pid = {k: int(v) for k, v in (d.get("pid") or {}).items() if v}
    cg = d.get("cgroup") or ""
    if cg and not (d.get("kafes") and cg.endswith("/" + d["kafes"])):
        cg = ""  # beklenmeyen kafes yolu: içindekilere dokunma
    haric = _atalar()
    cekirdek = []
    for ad in ("bildirim", "ses_bekcisi", "openbox", "dbus", "xvfb"):
        p = pid.get(ad)
        if p and _canli(p) and (ad != "xvfb" or _xvfb_mi(d)):
            cekirdek.append(p)

    def surecler() -> list[int]:
        """Kafesteki + ortam işaretli (kafessiz / kafesten kaçmış) süreçler; bu süreç ve ataları hariç."""
        return sorted({p for p in _kafes_surecleri(cg) + _isaretli_surecler(d) if p not in haric})

    # 1) uygulamalar (ses akışları onlarda), 2) çekirdek, 3) kalan SIGKILL, 4) EN SON boş ses çıkışı
    uygulamalar = [p for p in surecler() if p not in cekirdek]
    if uygulamalar:
        _sinyal(uygulamalar, signal.SIGTERM)
        _bekle(lambda: not any(_canli(p) for p in uygulamalar), 3, 0.05)
    _sinyal(cekirdek, signal.SIGTERM)
    _bekle(lambda: not any(_canli(p) for p in cekirdek + surecler()), 3, 0.05)
    kalan = [p for p in set(cekirdek + surecler()) if _canli(p)]
    if kalan:
        _sinyal(kalan, signal.SIGKILL)
        _bekle(lambda: not any(_canli(p) for p in kalan), 2, 0.05)
        notlar.append(_("{sayi} süreç SIGKILL ile kapatıldı").format(sayi=len(kalan)))
    canli = [p for p in set(cekirdek + surecler()) if _canli(p)]
    if canli:
        notlar.append(_("kapanmayan süreçler: {surecler}; boş ses çıkışı bu yüzden KALDIRILMADI").format(surecler=canli))
    else:
        n = ses_kaldir(d.get("ses"))
        if n:
            notlar.append(n)
    cdir = d.get("calisma")
    if cdir and os.path.isdir(cdir) and os.path.basename(cdir).startswith("sanal-"):
        shutil.rmtree(cdir, ignore_errors=True)
    for yol in (f"/tmp/.X{d.get('no')}-lock",):  # Xvfb SIGKILL ile öldüyse kilit kalır
        try:
            if not _xvfb_mi(d) and os.path.exists(yol):
                with open(yol) as f:
                    if int(f.read().strip() or 0) == pid.get("xvfb"):
                        os.remove(yol)
        except (OSError, ValueError):
            pass
    return notlar


def masaustu_durdur() -> tuple[bool, list[str]]:
    """→ (bir şey kapatıldı mı, notlar)."""
    with _kilit():
        d = durum_oku()
        if d is None:
            return False, []
        notlar = _kapat_ic(d)
        try:  # oturum kopyaları: jeton döndürme uyarısı + silme (uygulamalar kapandıktan SONRA)
            from .oturum import kapanis
            notlar += kapanis()
        except Exception as e:  # noqa: BLE001
            notlar.append(_("oturum kopyaları temizlenemedi: {hata}").format(hata=e))
        try:
            os.remove(durum_yolu())
        except OSError:
            pass
        return True, notlar


# ---------------------------------------------------------------- uygulama başlatma

def baslat(argv: list[str], env: dict | None = None, **popen) -> subprocess.Popen:
    """Uygulamayı sanal masaüstünde başlat: DISPLAY, özel DBUS_SESSION_BUS_ADDRESS, WAYLAND_DISPLAY yok,
    x11 arka uçları, sessiz ses çıkışı; süreç bellek kafesinin içinde (nice 10, ionice idle).
    env: os.environ'a eklenecek/değişecek değişkenler (sanal masaüstü değerleri her zaman üstün)."""
    d = gerekli()
    if not argv or not (shutil.which(argv[0]) or os.path.isfile(argv[0])):
        raise Dur(ARAC_EKSIK, _("başlatılamadı: {komut} bulunamadı").format(komut=argv[0] if argv else _("(boş komut)")))
    popen.setdefault("stdin", subprocess.DEVNULL)
    if "stdout" not in popen or "stderr" not in popen:
        log = _gunluk_dosyasi(d["calisma"], "uygulamalar")
        popen.setdefault("stdout", log)
        popen.setdefault("stderr", log)
    else:
        log = None
    argv = list(argv)
    if not (d.get("ses") or {}).get("sink") and _flatpak_run_mi(argv) and "--nosocket=pulseaudio" not in argv:
        # boş çıkış yok → ses PULSE_SERVER ile kapatıldı; ama flatpak --socket=pulseaudio sandbox içinde
        # PULSE_SERVER'ı kendi soketine EZER (ölçüldü) → ses kullanıcının kulaklığına giderdi
        argv.insert(argv.index("run") + 1, "--nosocket=pulseaudio")
    try:
        return kafeste_baslat(d, argv, uygulama_ortami(d, env), **popen)
    except FileNotFoundError as e:
        raise Dur(ARAC_EKSIK, _("başlatılamadı: {hata}").format(hata=e))
    finally:
        if log is not None:
            log.close()


def _flatpak_run_mi(argv: list[str]) -> bool:
    return bool(argv) and os.path.basename(argv[0]) == "flatpak" and "run" in argv[1:3]


# ---------------------------------------------------------------- komut satırı

def _yazdir_durum(d: dict) -> None:
    g, y, _derinlik = d["boyut"]
    s = d.get("saglik") or {}
    bilesen = " ".join(f"{ad}:{'✓' if ok else '✗'}" for ad, ok in s.items())
    print(_("sanal masaüstü AÇIK: {ekran} {genislik}x{yukseklik} | kafes {kafes} (bellek {bellek}) | ses {ses} | "
            "openbox {openbox}").format(
        ekran=d["ekran"], genislik=g, yukseklik=y, kafes=d.get("kafes") or _("YOK"),
        bellek=f"{d.get('bellek')}, swap {d.get('takas') or '-'}" if d.get("bellek") else _("sınırsız"),
        ses=(d.get("ses") or {}).get("sink") or _("kapalı"),
        openbox=_("var") if d.get("openbox") else _("yok")))
    if bilesen:
        print(_("bileşenler: {bilesenler}").format(bilesenler=bilesen))
    print(f"D-Bus: {d['dbus_adres']}")
    for u in d.get("uyarilar") or []:
        print(_("UYARI: {uyari}").format(uyari=u))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deskhand desktop", description=h_("görünmez ikinci masaüstü (arka plan kipi)"))
    ap.add_argument("islem", type=cevirici(MASAUSTU), choices=secimler(MASAUSTU, ["baslat", "durdur", "durum"]),
                    metavar="{start,stop,status}")
    ap.add_argument(SECENEKLER["--boyut"], "--boyut", dest="boyut", metavar="SIZE",
                    help=h_("GENxYÜK[xDERİNLİK] (varsayılan $DESKHAND_SANAL_BOYUT ya da {boyut})").format(
                        boyut=VARSAYILAN_BOYUT))
    ap.add_argument(SECENEKLER["--openbox-yok"], "--openbox-yok", dest="openbox_yok", action="store_true",
                    help=h_("pencere yöneticisi başlatma"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.islem == "baslat":
            d = masaustu_baslat(a.boyut, openbox=not a.openbox_yok)
            if a.json:
                print(json.dumps(d, ensure_ascii=False))
            else:
                if d.get("zaten"):
                    print(_("zaten açık"))
                _yazdir_durum(durum() or d)
            return 0
        if a.islem == "durdur":
            ok, notlar = masaustu_durdur()
            for n in notlar:
                print(_("UYARI: {uyari}").format(uyari=n))
            print(_("sanal masaüstü kapatıldı") if ok else _("sanal masaüstü zaten kapalı"))
            return 0
        d = durum()
        if a.json:
            print(json.dumps(d, ensure_ascii=False))
        elif d is None:
            print(_("sanal masaüstü KAPALI"))
        else:
            _yazdir_durum(d)
        return 0 if d is not None else SANAL_KAPALI
    except Dur as e:
        print(_("DURDURULDU ({kod}): {mesaj}").format(kod=e.kod, mesaj=e.mesaj), file=sys.stderr)
        return e.kod


if __name__ == "__main__":
    sys.exit(main())
