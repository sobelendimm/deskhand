"""Yalıtık arka plan KWin oturumu (Faz 12a yapı taşı): `kwin_wayland --virtual` + özel D-Bus + özel Wayland soketi
(+ isteğe bağlı XWayland). Xvfb + openbox masaüstünün (masaustu.py) yerine geçecek altyapının yaşam döngüsü; CLI'ye ve
ArkaUc'a BAĞLI DEĞİL, bağımsız kullanılır:

    bilgi = kwin_oturum.baslat((1920, 1080))        # dict (adres, soket, pid'ler, XWayland ekranı…)
    env = kwin_oturum.uygulama_ortami(bilgi)         # bu oturumda açılacak uygulamaların ortamı
    p = kwin_oturum.uygulama_baslat(bilgi, ["kcalc"])
    im = kwin_oturum.goruntu(bilgi)                  # PIL RGB (deskhand-goruntu + özel veri yolu adresi)
    with kwin_oturum.Eis(bilgi) as e: e.gonder("mouseto 0.5 0.5", "click left"); e.yaz("Merhaba ş")
    kwin_oturum.durdur(bilgi)

YALITIM (hepsi `_kwin_ortami` + `guvenlik_kapilari` içinde, tek yerde): KWin `env -i` eşdeğeri ASGARİ ortamla açılır;
kullanıcının WAYLAND_DISPLAY / DISPLAY / DBUS_SESSION_BUS_ADDRESS değerleri ASLA aktarılmaz. Kendi dbus-daemon'u
(standart servis dizinleri YOK; `dbus-run-session` YASAK: ikinci cüzdan/portal servisleri başlatırdı), kendi
XDG_RUNTIME_DIR'i (DESKHAND_RUNTIME_DIR altında 0700), geçici HOME + XDG_*_HOME'ları var; KWin kendi kwinrc /
kwinoutputconfig.json / kglobalshortcutsrc dosyalarını YAZAR, bunlar bu geçici klasöre gider (gerçek ~/.config'e
dokunulmaz). Klavye düzeni yalıtık kxkbrc'ye yazılır. Gerçek oturuma bağlanmak kapılarla imkânsızdır (Dur 14).

Süreçler tek bellek kafesinde (masaustu.py ile aynı: systemd-run --user --scope MemoryMax=…, nice 10, ionice idle).
XWayland: X soketlerini (+ kilit dosyalarını, Xauthority) biz kurar ve KWin'e `--xwayland-fd/-display/-xauthority`
ile veririz (kwin_wayland_wrapper'ın yaptığı gibi); böylece ekran adı kesin bilinir ve temizlenir.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import sys
import time

from . import hata, masaustu, yollar
from .hata import ARAC_EKSIK, SANAL_KAPALI, ZAMAN_ASIMI, Dur
from .i18n import _

ASGARI_SURUM = (6, 8)          # EIS + ScreenShot2 yetkisiz (X-KDE-DBUS-Restricted-Interfaces yok) KWin 6.8'den beri
ILK_XEKRAN = 120               # Xvfb masaüstü :90'dan başlar; çakışmasın
OTURUM_ONEK = "kwin-"
DURUM_DOSYASI = "oturum.json"
ASGARI_PATH = "/usr/local/bin:/usr/bin:/bin"
YEDEK_PATH = ASGARI_PATH
# Uygulama araçkiti ipuçları: açıkça verilirse uygulama ortamında değişebilen (güvenlikle ilgisiz) değişkenler
ARAC_IPUCLARI = ("QT_QPA_PLATFORM", "GDK_BACKEND", "MOZ_ENABLE_WAYLAND", "SDL_VIDEODRIVER", "SDL_VIDEO_DRIVER",
                 "ELECTRON_OZONE_PLATFORM_HINT")


# ---------------------------------------------------------------- yolların / adreslerin gerçek değerleri

def _gercek_runtime() -> str:
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def _gercek_degerler() -> dict:
    """Kullanıcının GERÇEK oturumuna ait değerler (ortamdan + bilinen yerlerden): kapılar bunlara karşı denetler."""
    rt = _gercek_runtime()
    bus = {os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""), f"unix:path={rt}/bus",
           f"unix:path=/run/user/{os.getuid()}/bus"} - {""}
    wl = {os.environ.get("WAYLAND_DISPLAY", ""), "wayland-0"} - {""}
    home = os.path.expanduser("~")
    config = {os.path.join(home, ".config")}
    if os.environ.get("XDG_CONFIG_HOME"):
        config.add(os.environ["XDG_CONFIG_HOME"])
    return {"bus": bus, "wayland": wl, "runtime": rt, "home": home, "config": config,
            "display": os.environ.get("DISPLAY", "")}


def _bus_yolu(adres: str) -> str | None:
    """unix:path=/yol[,guid=…] → /yol (başka biçimlerde None)."""
    if not adres.startswith("unix:path="):
        return None
    return adres[len("unix:path="):].split(",", 1)[0]


def _ayni_yol(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def _icinde(yol: str, ust: str) -> bool:
    yol, ust = os.path.realpath(yol), os.path.realpath(ust)
    return yol == ust or yol.startswith(ust.rstrip("/") + "/")


def guvenlik_kapilari(bus_adres: str, soket_adi: str, config_dizini: str, home: str | None = None,
                      calisma: str | None = None, xekran: str | None = None) -> None:
    """KWin'e verilecek değerler kullanıcının GERÇEK oturumunu gösteriyorsa Dur(14). masaustu.guvenli_ekran ile aynı ruh:
    yanlışlıkla gerçek oturuma bağlanmak/yazmak imkânsız olmalı. Süreç başlatmadan çağrılabilir (testler)."""
    g = _gercek_degerler()
    yol = _bus_yolu(bus_adres or "")
    if yol is None:
        raise Dur(SANAL_KAPALI, _("özel veri yolu adresi unix:path= biçiminde olmalı: {adres}").format(adres=repr(bus_adres)))
    for gercek in g["bus"]:
        gy = _bus_yolu(gercek)
        if (gy is not None and _ayni_yol(yol, gy)) or gercek.split(",", 1)[0] == bus_adres.split(",", 1)[0]:
            raise Dur(SANAL_KAPALI, _("özel veri yolu adresi kullanıcının gerçek oturum adresiyle aynı ({adres}); "
                                      "bağlanılmadı").format(adres=bus_adres))
    if not re.fullmatch(r"[A-Za-z0-9._-]+", soket_adi or ""):
        raise Dur(SANAL_KAPALI, _("geçersiz Wayland soket adı: {ad}").format(ad=repr(soket_adi)))
    if soket_adi in g["wayland"] or os.path.exists(os.path.join(g["runtime"], soket_adi)):
        raise Dur(SANAL_KAPALI, _("Wayland soket adı kullanıcının gerçek oturumuyla aynı ({ad}); bağlanılmadı").format(
            ad=soket_adi))
    if not config_dizini or any(_icinde(config_dizini, c) or _icinde(c, config_dizini) for c in g["config"]):
        raise Dur(SANAL_KAPALI, _("KWin yapılandırma dizini kullanıcının gerçek yapılandırma dizini (~/.config); "
                                  "yazılmadı: {dizin}").format(dizin=config_dizini))
    if home is not None and _ayni_yol(home, g["home"]):
        raise Dur(SANAL_KAPALI, _("KWin HOME'u kullanıcının gerçek ev dizini; verilmedi"))
    if calisma is not None and _ayni_yol(calisma, g["runtime"]):
        raise Dur(SANAL_KAPALI, _("KWin çalışma dizini kullanıcının gerçek XDG_RUNTIME_DIR'i; verilmedi"))
    if xekran is not None:
        e = xekran.strip()
        gd = g["display"].split(".")[0]
        if not re.fullmatch(r":\d+", e) or (gd and e == gd):
            raise Dur(SANAL_KAPALI, _("XWayland ekran adı geçersiz ya da kullanıcının gerçek ekranıyla aynı: {ekran}").format(
                ekran=repr(xekran)))


# ---------------------------------------------------------------- sürüm / kullanılabilirlik

def kwin_surumu() -> tuple[int, ...] | None:
    try:
        c = subprocess.run(["kwin_wayland", "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", c)
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def kullanilabilir() -> tuple[bool, str]:
    """→ (olur mu, neden). Testler / seçici bunu kullanır: KWin >= 6.8, araçlar, deskhand-eis ve deskhand-goruntu."""
    s = kwin_surumu()
    if s is None:
        return False, _("kwin_wayland yok")
    if s[:2] < ASGARI_SURUM:
        return False, _("KWin {surum} < 6.8 (EIS/ScreenShot2 yetkisi için 6.8 gerekir)").format(
            surum=".".join(map(str, s)))
    for arac in ("dbus-daemon", "nice", "ionice", "sh", "busctl", "env"):
        if not shutil.which(arac):
            return False, _("{arac} yok").format(arac=arac)
    if not yollar.eis_bin():
        return False, _("deskhand-eis yok (make -C deskhand/yardimci deskhand-eis; libei + libxkbcommon gerekir)")
    if not yollar.goruntu_bin():
        return False, _("deskhand-goruntu yok (make -C deskhand/yardimci deskhand-goruntu)")
    return True, ""


# ---------------------------------------------------------------- ortam (yalıtımın tek yeri)

def _oturum_dizini(kimlik: str) -> str:
    return os.path.join(yollar.runtime_dir(), OTURUM_ONEK + kimlik)


def _kwin_ortami(d: dict) -> dict:
    """KWin ve özel dbus-daemon'un TAM ortamı (env -i eşdeğeri: os.environ'dan HİÇBİR ŞEY alınmaz). Kullanıcının
    WAYLAND_DISPLAY / DISPLAY / DBUS_SESSION_BUS_ADDRESS değerleri burada yoktur ve asla eklenmez."""
    ev = os.path.join(d["calisma"], "ev")
    return {
        "PATH": ASGARI_PATH,
        "HOME": ev,
        "LANG": os.environ.get("LANG") or "C.UTF-8",
        "XDG_RUNTIME_DIR": d["calisma"],
        "XDG_CONFIG_HOME": os.path.join(ev, "config"),
        "XDG_CACHE_HOME": os.path.join(ev, "cache"),
        "XDG_DATA_HOME": os.path.join(ev, "data"),
        "XDG_STATE_HOME": os.path.join(ev, "state"),
        "DBUS_SESSION_BUS_ADDRESS": d["dbus_adres"],
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "KDE",
        "KDE_SESSION_VERSION": "6",
    }


def kdotool_ortami(d: dict) -> dict:
    """kdotool / goruntu / busctl gibi İSTEMCİ araçlar için asgari ortam (özel veri yolu)."""
    return {"PATH": ASGARI_PATH, "HOME": os.path.join(d["calisma"], "ev"), "XDG_RUNTIME_DIR": d["calisma"],
            "DBUS_SESSION_BUS_ADDRESS": d["dbus_adres"], "KDE_SESSION_VERSION": "6", "XDG_CURRENT_DESKTOP": "KDE",
            "XDG_SESSION_TYPE": "wayland", "LANG": os.environ.get("LANG") or "C.UTF-8"}


def uygulama_ortami(d: dict, env: dict | None = None) -> dict:
    """Bu oturumda başlatılacak uygulamaların ortamı: os.environ + env, üstüne oturum değerleri ZORLA (kullanıcının
    Wayland/X ekranına, oturum veri yoluna, sesine kaçamasın). masaustu.uygulama_ortami ile aynı güvenceler; ses
    bölümü (PULSE_SINK/PULSE_PROP/PIPEWIRE_*) aynı işlevden gelir. `env` yalnız araç takımı ipuçlarını
    (QT_QPA_PLATFORM, GDK_BACKEND…) değiştirebilir; ağ/ekran/veri yolu/ses değişkenleri her zaman oturumundur."""
    sahte = {"no": OTURUM_ONEK + d["kimlik"], "ekran": d.get("xwayland") or ":0", "dbus_adres": d["dbus_adres"],
             "ses": d.get("ses"), "xauth": d.get("xauth"), "kimlik": d.get("kimlik")}
    e = masaustu.uygulama_ortami(sahte, {k: v for k, v in (env or {}).items()})
    # masaustu X11 kipine göre kurar; Wayland kipine çevir
    e.pop("DESKHAND_SANAL", None)
    e["WAYLAND_DISPLAY"] = d["wayland_yol"]  # MUTLAK yol: değişken yoksa libwayland kullanıcının wayland-0'ına düşerdi
    e["XDG_SESSION_TYPE"] = "wayland"
    for k, v in {"QT_QPA_PLATFORM": "wayland", "GDK_BACKEND": "wayland", "MOZ_ENABLE_WAYLAND": "1",
                 "SDL_VIDEODRIVER": "wayland", "SDL_VIDEO_DRIVER": "wayland",
                 "ELECTRON_OZONE_PLATFORM_HINT": "wayland"}.items():
        e[k] = (env or {}).get(k, v) if k in ARAC_IPUCLARI else v
    if d.get("xwayland"):
        e["DISPLAY"] = d["xwayland"]
        e["XAUTHORITY"] = d["xauth"]
    else:  # XWayland yok: kullanıcının gerçek DISPLAY'i KALMAMALI
        e.pop("DISPLAY", None)
        e.pop("XAUTHORITY", None)
    e["DESKHAND_KWIN"] = d["kimlik"]
    return e


# ---------------------------------------------------------------- X soketleri (XWayland'i biz kurarız)

X_DIZIN = "/tmp/.X11-unix"


class _XSoketleri:
    """XWayland için dinleyen soketler (ana ekran: dosya + soyut; init ekranı: dosya) ve /tmp/.X<N>-lock kilitleri.
    kwin_wayland_wrapper'ın yaptığıyla aynı; KWin bunları --xwayland-fd/--xwayland-initfd ile alır."""

    def __init__(self, ana: int):
        self.ana, self.init = ana, ana + 1
        self.soketler: list[socket.socket] = []
        self.dosyalar: list[str] = []
        self.kilitler: list[str] = []

    @staticmethod
    def _dinle(ad: bytes | str) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(ad)
            s.listen(1)
        except OSError:
            s.close()
            raise
        return s

    def _kilit(self, no: int) -> None:
        yol = f"/tmp/.X{no}-lock"
        fd = os.open(yol, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid():10d}\n")
        self.kilitler.append(yol)

    def ac(self) -> None:
        try:
            os.makedirs(X_DIZIN, exist_ok=True)
            for no in (self.ana, self.init):
                self._kilit(no)
            yol_a, yol_i = f"{X_DIZIN}/X{self.ana}", f"{X_DIZIN}/X{self.init}"
            s = self._dinle(yol_a)
            self.soketler.append(s)
            self.dosyalar.append(yol_a)
            os.chmod(yol_a, 0o777)
            self.soketler.append(self._dinle("\0" + yol_a))
            s = self._dinle(yol_i)
            self.soketler.append(s)
            self.dosyalar.append(yol_i)
            os.chmod(yol_i, 0o777)
        except BaseException:
            self.kapat()
            raise

    def fdler(self) -> tuple[list[int], int]:
        return [self.soketler[0].fileno(), self.soketler[1].fileno()], self.soketler[2].fileno()

    def kilit_pid(self, pid: int) -> None:
        for yol in self.kilitler:
            try:
                with open(yol, "w") as f:
                    f.write(f"{pid:10d}\n")
            except OSError:
                pass

    def kapat(self) -> None:
        """Bizim dinleyen soketlerimizi kapat (KWin kendi kopyasını tutar)."""
        for s in self.soketler:
            try:
                s.close()
            except OSError:
                pass
        self.soketler.clear()

    def temizle(self) -> None:
        self.kapat()
        for yol in self.dosyalar:
            try:
                os.unlink(yol)
            except OSError:
                pass
        for yol in self.kilitler:
            try:
                os.unlink(yol)
            except OSError:
                pass


def _x_temizle(d: dict) -> list[str]:
    """Durum kaydından: bu oturumun X soketlerini ve kilitlerini sil (yalnız kilit bu oturumun süreçlerinden
    birine ya da ölü bir sürece aitse; başkasının kilidine dokunulmaz)."""
    notlar = []
    ana = d.get("x_ana")
    if ana is None:
        return notlar
    sahipler = {int(p) for p in (d.get("pid") or {}).values() if p} | {d.get("baslatan_pid")}
    for no in (ana, ana + 1):
        yol = f"/tmp/.X{no}-lock"
        try:
            with open(yol) as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            pid = None
        if pid is not None and (pid in sahipler or not masaustu._canli(pid)):
            for y in (yol, f"{X_DIZIN}/X{no}"):
                try:
                    os.unlink(y)
                except OSError:
                    pass
    return notlar


def _bos_x_cifti(bas: int = ILK_XEKRAN) -> int:
    for n in range(bas, bas + 200, 2):
        if all(not os.path.exists(f"{X_DIZIN}/X{k}") and not os.path.exists(f"/tmp/.X{k}-lock") for k in (n, n + 1)):
            return n
    raise Dur(ARAC_EKSIK, _("boş X ekran numarası bulunamadı"))


# ---------------------------------------------------------------- yardımcı: bekle, kafes, başlat

def _bekle(kosul, sure: float, aralik: float = 0.02) -> bool:
    return masaustu._bekle(kosul, sure, aralik)


def _gunluk(cdir: str, ad: str):
    return open(os.path.join(cdir, f"{ad}.log"), "ab")


def _log_sonu(cdir: str, ad: str, n: int = 400) -> str:
    try:
        with open(os.path.join(cdir, f"{ad}.log"), errors="replace") as f:
            return f.read()[-n:].strip()
    except OSError:
        return ""


def _kapida_baslat(d: dict, argv: list[str], env: dict, pass_fds=(), **popen) -> subprocess.Popen:
    """masaustu.kafeste_baslat ile aynı (nice 10 + ionice idle, kafese ALINDIKTAN SONRA exec) + pass_fds
    (masaustu.kafeste_baslat ek dosya tanıtıcısı geçirmeye izin vermiyor: XWayland soketleri için gerekli)."""
    tam = [*masaustu._oncelik(), *argv]
    kafes = d.get("kafes")
    if not kafes:
        return subprocess.Popen(tam, env=env, pass_fds=tuple(pass_fds), start_new_session=True, **popen)
    r, w = os.pipe()
    try:
        p = subprocess.Popen(["sh", "-c", masaustu.KAPI.format(fd=r), "deskhand-kapi", *tam], env=env,
                             pass_fds=(r, *pass_fds), start_new_session=True, **popen)
    finally:
        os.close(r)
    try:
        masaustu._kafese_al(kafes, p.pid)
    except BaseException:
        os.close(w)
        p.kill()
        p.wait()
        raise
    os.write(w, b"\n")
    os.close(w)
    return p


def _busctl(d: dict, *a, zaman: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(["busctl", f"--address={d['dbus_adres']}", "--no-pager", *a], capture_output=True, text=True,
                          timeout=zaman, env=kdotool_ortami(d))


def _kwin_hazir(d: dict) -> bool:
    try:
        return _busctl(d, "status", "org.kde.KWin", zaman=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _kxkbrc(cfg: str, duzen: tuple[str, str]) -> None:
    layout, variant = duzen
    with open(os.path.join(cfg, "kxkbrc"), "w") as f:
        f.write(f"[Layout]\nLayoutList={layout}\nVariantList={variant}\nUse=true\nOptions=\n")


# ---------------------------------------------------------------- durum

def _durum_yolu(cdir: str) -> str:
    return os.path.join(cdir, DURUM_DOSYASI)


def _durum_yaz(d: dict) -> None:
    yol = _durum_yolu(d["calisma"])
    gecici = f"{yol}.{os.getpid()}"
    with open(gecici, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)


def _durum_oku(cdir: str) -> dict | None:
    try:
        with open(_durum_yolu(cdir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _kwin_mi(d: dict) -> bool:
    pid = (d.get("pid") or {}).get("kwin")
    kom = masaustu._komut_satiri(pid)
    return masaustu._canli(pid) and any(os.path.basename(k) == "kwin_wayland" for k in kom) and d["wayland"] in kom


def _oturum_dizinleri() -> list[str]:
    kok = yollar.runtime_dir()
    try:
        return sorted(os.path.join(kok, a) for a in os.listdir(kok) if a.startswith(OTURUM_ONEK))
    except OSError:
        return []


def durum() -> dict | None:
    """Çalışan (KWin süreci + soketi canlı) en son KWin oturumunun bilgisi; yoksa None."""
    canli = []
    for cdir in _oturum_dizinleri():
        d = _durum_oku(cdir)
        if d and _kwin_mi(d) and os.path.exists(d.get("wayland_yol", "")):
            canli.append(d)
    return max(canli, key=lambda d: d.get("baslangic", 0)) if canli else None


def gerekli() -> dict:
    d = durum()
    if d is None:
        raise Dur(SANAL_KAPALI, _("KWin arka plan oturumu kapalı"))
    return d


# ---------------------------------------------------------------- başlat

def baslat(boyut: tuple[int, int] = (1920, 1080), xwayland: bool = True,
           duzen: tuple[str, str] = ("tr", "")) -> dict:
    """Yalıtık KWin oturumunu başlat → bilgi dict'i. Hata olursa başlatılan her şeyi kapatır."""
    ok, neden = kullanilabilir()
    if not ok:
        raise Dur(ARAC_EKSIK, neden)
    g, y = int(boyut[0]), int(boyut[1])
    if not (320 <= g <= 8192 and 240 <= y <= 8192):
        raise Dur(1, _("geçersiz ekran boyutu: {boyut}").format(boyut=repr(boyut)))
    bellek = masaustu._bellek_siniri()
    takas = masaustu._takas_siniri() if bellek else None
    if bellek and not shutil.which("systemd-run"):
        raise Dur(ARAC_EKSIK, _("systemd-run yok: bellek kafesi kurulamaz (bilerek kapatmak için DESKHAND_SANAL_BELLEK=0)"))
    temizle_kalintilar()
    kimlik = secrets.token_hex(4)
    cdir = _oturum_dizini(kimlik)
    os.makedirs(os.path.dirname(cdir), mode=0o700, exist_ok=True)
    os.makedirs(cdir, mode=0o700)
    soket_adi = f"deskhand-{kimlik}"
    d = {"surum": 1, "tur": "kwin", "kimlik": kimlik, "calisma": cdir, "boyut": [g, y], "duzen": list(duzen),
         "wayland": soket_adi, "wayland_yol": os.path.join(cdir, soket_adi), "dbus_adres": f"unix:path={cdir}/bus",
         "xwayland": None, "xauth": None, "x_ana": None, "kafes": None, "cgroup": "", "bellek": bellek,
         "takas": takas, "pid": {}, "ses": None, "uyarilar": [], "baslangic": time.time(),
         "baslatan_pid": os.getpid(), "kwin_surum": ".".join(map(str, kwin_surumu() or ()))}
    try:
        if len(d["wayland_yol"]) > 100 or len(f"{cdir}/bus") > 100:
            raise Dur(ARAC_EKSIK, _("çalışma dizini yolu çok uzun (soket yolu 108 bayt sınırı): {dizin}").format(dizin=cdir))
        ev = os.path.join(cdir, "ev")
        for a in ("config", "cache", "data", "state"):
            os.makedirs(os.path.join(ev, a), mode=0o700)
        xekran = None
        if xwayland:
            no = _bos_x_cifti()
            xekran = f":{no}"
        # KAPILAR: hiçbir süreç başlamadan, gerçek oturumu gösteren değer var mı
        guvenlik_kapilari(d["dbus_adres"], soket_adi, os.path.join(ev, "config"), home=ev, calisma=cdir, xekran=xekran)
        _kxkbrc(os.path.join(ev, "config"), duzen)
        _durum_yaz(d)  # çökerse kalıntı temizliği bulabilsin
        _baslat_ic(d, cdir, xekran)
    except BaseException:
        try:
            _kapat_ic(d)
        finally:
            shutil.rmtree(cdir, ignore_errors=True)
        raise
    _durum_yaz(d)
    return d


def _baslat_ic(d: dict, cdir: str, xekran: str | None) -> None:
    ortam = _kwin_ortami(d)
    # ses: boş çıkış (masaustu ile aynı); özel D-Bus'tan ÖNCE
    ses, uyari = masaustu.ses_kur(OTURUM_ONEK + d["kimlik"])
    d["ses"] = ses
    if uyari:
        d["uyarilar"].append(uyari)
    # 1) özel dbus-daemon: kafesin İLK süreci (systemd-run --scope exec eder: PID dbus-daemon'un kendisi).
    #    Komut `env -i …` ile açılır: systemd-run'ın kendi ortamı (gerçek veri yolu adresi!) dbus-daemon'a GEÇMEZ.
    conf, adres = masaustu._dbus_yapilandir(cdir)
    if adres != d["dbus_adres"]:
        raise Dur(ARAC_EKSIK, _("özel veri yolu adresi beklenenden farklı: {adres}").format(adres=adres))
    env_args = [f"{k}={v}" for k, v in ortam.items()]
    dbus_cmd = ["env", "-i", *env_args, "dbus-daemon", f"--config-file={conf}", "--nofork", "--nopidfile", "--nosyslog"]
    with _gunluk(cdir, "dbus") as log:
        if d["bellek"]:
            kafes = f"deskhand-kwin-{d['kimlik']}-{os.getpid()}.scope"
            komut = ["systemd-run", "--user", "--scope", "--quiet", f"--unit={kafes}",
                     "-p", f"MemoryMax={d['bellek']}", "-p", f"MemorySwapMax={d.get('takas') or '0'}",
                     "-p", "Delegate=yes", "-p", "TimeoutStopSec=5", "--", *masaustu._oncelik(), *dbus_cmd]
            p = subprocess.Popen(komut, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 env=masaustu._kullanici_bus_ortami(), start_new_session=True)
            d["kafes"] = kafes
        else:
            d["uyarilar"].append(_("bellek kafesi KAPALI (DESKHAND_SANAL_BELLEK=0)"))
            p = subprocess.Popen([*masaustu._oncelik(), *dbus_cmd], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 env={"PATH": ASGARI_PATH}, start_new_session=True)
    d["pid"]["dbus"] = p.pid
    _durum_yaz(d)
    bus_soket = adres.split("=", 1)[1]
    if not _bekle(lambda: os.path.exists(bus_soket) or p.poll() is not None, 8) or p.poll() is not None:
        raise Dur(ARAC_EKSIK, _("özel D-Bus (dbus-daemon) açılmadı: {hata}").format(hata=_log_sonu(cdir, "dbus")))
    if d["kafes"]:
        d["cgroup"] = masaustu._cgroup(p.pid)
        if not d["cgroup"].endswith("/" + d["kafes"]):
            raise Dur(ARAC_EKSIK, _("dbus-daemon bellek kafesinde değil: {cgroup}").format(cgroup=repr(d["cgroup"])))

    # 2) XWayland soketleri + Xauthority
    kwin = ["kwin_wayland", "--virtual", "--no-lockscreen", "--no-global-shortcuts", "--no-kactivities",
            "--socket", d["wayland"], "--width", str(d["boyut"][0]), "--height", str(d["boyut"][1])]
    xs = None
    fdler: list[int] = []
    try:
        if xekran:
            no = int(xekran[1:])
            xs = _XSoketleri(no)
            xs.ac()  # çakışırsa OSError (baslat temizler)
            d["xwayland"], d["x_ana"] = xekran, no
            d["xauth"] = os.path.join(cdir, "Xauthority")
            masaustu._xauth_yaz(d["xauth"], no, secrets.token_bytes(16))
            ana_fd, init_fd = xs.fdler()
            kwin += ["--xwayland", "--xwayland-display", xekran, "--xwayland-init-display", f":{no + 1}",
                     "--xwayland-xauthority", d["xauth"], "--xwayland-initfd", str(init_fd)]
            for fd in ana_fd:
                kwin += ["--xwayland-fd", str(fd)]
            fdler = [*ana_fd, init_fd]
        _durum_yaz(d)
        # 3) KWin (aynı kafeste)
        with _gunluk(cdir, "kwin") as log:
            k = _kapida_baslat(d, kwin, ortam, pass_fds=fdler, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    finally:
        if xs is not None:
            xs.kapat()  # KWin kendi kopyalarını tutar
    d["pid"]["kwin"] = k.pid
    if xs is not None:
        xs.kilit_pid(k.pid)
    _durum_yaz(d)
    ok = _bekle(lambda: os.path.exists(d["wayland_yol"]) or k.poll() is not None, 15)
    if not ok or k.poll() is not None:
        raise Dur(ARAC_EKSIK, _("KWin açılmadı: {hata}").format(hata=_log_sonu(cdir, "kwin")))
    if not _bekle(lambda: _kwin_hazir(d) or k.poll() is not None, 15, 0.05) or k.poll() is not None:
        raise Dur(ARAC_EKSIK, _("KWin özel veri yoluna bağlanmadı: {hata}").format(hata=_log_sonu(cdir, "kwin")))
    if not _kwin_mi(d):
        raise Dur(ARAC_EKSIK, _("KWin süreci doğrulanamadı (pid {pid})").format(pid=k.pid))

    # 4) ses bekçisi (masaustu ile aynı ikinci savunma hattı)
    if ses:
        from . import ses_bekcisi
        with _gunluk(cdir, "ses-bekcisi") as log:
            p = masaustu.kafeste_baslat(d, [sys.executable, "-I", ses_bekcisi.__file__, d.get("kafes") or ""],
                                        uygulama_ortami(d), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=log)
        d["pid"]["ses_bekcisi"] = p.pid
        satir = masaustu._satir_bekle(p, 5)
        if p.stdout:
            p.stdout.close()
        if satir != "hazir":
            d["uyarilar"].append(_("ses bekçisi hazır olmadı ({yanit})").format(yanit=satir or _("yanıt yok")))


# ---------------------------------------------------------------- durdur / temizlik

def _kapat_ic(d: dict) -> list[str]:
    """PID ile kapat: önce kafesteki uygulamalar, sonra çekirdek (ses bekçisi, KWin, dbus); X soketleri/kilitleri,
    boş ses çıkışı ve çalışma dizini temizlenir. masaustu._kapat_ic ile aynı sıra."""
    notlar = []
    pid = {k: int(v) for k, v in (d.get("pid") or {}).items() if v}
    cg = d.get("cgroup") or ""
    if cg and not (d.get("kafes") and cg.endswith("/" + d["kafes"])):
        cg = ""
    haric = masaustu._atalar()
    cekirdek = [p for ad in ("ses_bekcisi", "atspi_registryd", "kwin", "dbus") if (p := pid.get(ad)) and masaustu._canli(p)]

    def surecler() -> list[int]:
        return sorted({p for p in masaustu._kafes_surecleri(cg) if p not in haric})

    uygulamalar = [p for p in surecler() if p not in cekirdek]
    if uygulamalar:
        masaustu._sinyal(uygulamalar, signal.SIGTERM)
        _bekle(lambda: not any(masaustu._canli(p) for p in uygulamalar), 3, 0.05)
    # KWin temiz kapansın (XWayland'i kapatır, kendi dosyalarını yazar), sonra ses bekçisi ve dbus
    for ad in ("kwin", "ses_bekcisi", "atspi_registryd", "dbus"):
        p = pid.get(ad)
        if p and masaustu._canli(p):
            masaustu._sinyal([p], signal.SIGTERM)
            if ad == "kwin":
                _bekle(lambda p=p: not masaustu._canli(p), 4, 0.05)
    _bekle(lambda: not any(masaustu._canli(p) for p in cekirdek + surecler()), 3, 0.05)
    kalan = [p for p in set(cekirdek + surecler()) if masaustu._canli(p)]
    if kalan:
        masaustu._sinyal(kalan, signal.SIGKILL)
        _bekle(lambda: not any(masaustu._canli(p) for p in kalan), 2, 0.05)
        notlar.append(_("{sayi} süreç SIGKILL ile kapatıldı").format(sayi=len(kalan)))
    canli = [p for p in set(cekirdek + surecler()) if masaustu._canli(p)]
    if canli:
        notlar.append(_("kapanmayan süreçler: {surecler}; boş ses çıkışı bu yüzden KALDIRILMADI").format(surecler=canli))
    else:
        n = masaustu.ses_kaldir(d.get("ses"))
        if n:
            notlar.append(n)
    notlar += _x_temizle(d)
    cdir = d.get("calisma")
    if cdir and os.path.isdir(cdir) and os.path.basename(cdir).startswith(OTURUM_ONEK):
        shutil.rmtree(cdir, ignore_errors=True)
    return notlar


def durdur(bilgi: dict | None = None) -> bool:
    """Oturumu kapat (bilgi verilmezse çalışan en son oturum). → bir şey kapatıldı mı. Süreçler yalnız kayıtlı PID ile
    durdurulur (pkill yok)."""
    d = bilgi or durum()
    if not d:
        return False
    _kapat_ic(d)
    return True


def temizle_kalintilar() -> list[str]:
    """Yarım kalmış önceki oturumların kalıntılarını temizle: çalışma dizini var ama KWin süreci ölü (çökme,
    SIGKILL). Canlı oturumlara dokunmaz. → temizlenen oturum kimlikleri."""
    yapilan = []
    for cdir in _oturum_dizinleri():
        d = _durum_oku(cdir)
        if d is None:
            if time.time() - os.path.getmtime(cdir) > 30:  # durum yazılamadan kalmış (başlatma sürerken dokunma)
                shutil.rmtree(cdir, ignore_errors=True)
                yapilan.append(os.path.basename(cdir))
            continue
        bas = d.get("baslatan_pid")
        if _kwin_mi(d) or (bas and masaustu._canli(bas) and not d["pid"].get("kwin") and bas != os.getpid()):
            continue  # canlı ya da başka bir süreç şu an başlatıyor
        if bas == os.getpid() and not d["pid"].get("kwin") and time.time() - d["baslangic"] < 60:
            continue
        _kapat_ic(d)
        yapilan.append(d.get("kimlik") or os.path.basename(cdir))
    return yapilan


# ---------------------------------------------------------------- uygulama başlatma

def uygulama_baslat(d: dict, argv: list[str], env: dict | None = None, **popen) -> subprocess.Popen:
    """Uygulamayı bu oturumda (bellek kafesinde) başlat; ortam uygulama_ortami(d, env)."""
    if not argv or not (shutil.which(argv[0]) or os.path.isfile(argv[0])):
        raise Dur(ARAC_EKSIK, _("başlatılamadı: {komut} bulunamadı").format(komut=argv[0] if argv else _("(boş komut)")))
    popen.setdefault("stdin", subprocess.DEVNULL)
    log = None
    if "stdout" not in popen or "stderr" not in popen:
        log = _gunluk(d["calisma"], "uygulamalar")
        popen.setdefault("stdout", log)
        popen.setdefault("stderr", log)
    try:
        return masaustu.kafeste_baslat(d, list(argv), uygulama_ortami(d, env), **popen)
    finally:
        if log is not None:
            log.close()


# ---------------------------------------------------------------- ince sarmalayıcılar

def goruntu(d: dict, bolge=None):
    """Tüm oturum ekranı (ya da bolge=(x,y,g,y)) PIL RGB: deskhand-goruntu + özel veri yolu adresi."""
    from .arka_uc import kde_goruntu
    yol = yollar.goruntu_bin()
    if not yol:
        raise Dur(ARAC_EKSIK, _("ekran görüntüsü yardımcısı yok (make -C deskhand/yardimci deskhand-goruntu)"))
    argv = [yol] + (["-a", *(str(int(v)) for v in bolge)] if bolge else [])
    try:
        p = subprocess.run(argv, capture_output=True, timeout=kde_goruntu.ZAMAN_ASIMI, env=kdotool_ortami(d))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Dur(ZAMAN_ASIMI, _("ekran görüntüsü yardımcısı çalışmadı: {hata}").format(hata=e))
    if p.returncode:
        raise Dur(ARAC_EKSIK, _("ekran görüntüsü yardımcısı başarısız (kod {kod}): {ayrinti}").format(
            kod=p.returncode, ayrinti=p.stderr.decode("utf-8", "replace").strip()[-300:]))
    try:
        return kde_goruntu.ayristir(p.stdout)[0]
    except kde_goruntu.GoruntuHatasi as e:
        raise Dur(ARAC_EKSIK, str(e))


def _kd(d: dict, *a) -> str:
    """kdotool (özel veri yolunda). Salt okuma sorguları boş dönerse 3 kez yeniden dener (kde.kd gibi)."""
    for _i in range(4):
        r = subprocess.run(["kdotool", *a], capture_output=True, text=True, env=kdotool_ortami(d), timeout=10)
        if r.stdout.strip() or not a or a[0] not in ("search", "getwindowname", "getwindowgeometry",
                                                      "getwindowclassname", "getactivewindow"):
            return r.stdout.strip()
        time.sleep(0.01)
    return ""


def pencereler(d: dict) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """[(kimlik, başlık, (x, y, g, y))] — kdotool özel veri yolunda."""
    kimlikler = sorted(set(_kd(d, "search", "--name", ".").split()) | set(_kd(d, "search", "--class", ".").split()))
    sonuc = []
    for w in kimlikler:
        geo = _kd(d, "getwindowgeometry", w)
        p = re.search(r"Position:\s*(-?[\d.]+),(-?[\d.]+)", geo)
        s = re.search(r"Geometry:\s*([\d.]+)x([\d.]+)", geo)
        if not (p and s):
            continue  # listelenirken kapanan pencere
        sonuc.append((w, _kd(d, "getwindowname", w),
                      tuple(round(float(v)) for v in (*p.groups(), *s.groups()))))
    return sonuc


def atspi_adresi(d: dict) -> str | None:
    """Oturumun KENDİ erişilebilirlik veri yolu adresi (org.a11y.Bus.GetAddress; at-spi-bus-launcher özel veri yolunda
    etkinleştirilir). Yoksa None."""
    try:
        r = _busctl(d, "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress", zaman=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r's\s+"([^"]+)"', r.stdout)
    return m.group(1) if r.returncode == 0 and m else None


ATSPI_REGISTRYD = "/usr/lib/at-spi2-registryd"


def atspi_baslat(d: dict) -> str | None:
    """Oturumun KENDİ erişilebilirlik veri yolunu kullanıma hazırla (idempotent) → adres ya da None.
    ÖLÇÜM: at-spi-bus-launcher özel veri yolunda etkinleşir (org.a11y.Bus) ama a11y veri yolunun
    `org.a11y.atspi.Registry` etkinleştirmesi "unit failed" ile çöker (servis dosyası `at-spi2-registryd
    --use-gnome-session` ister, GNOME oturumu yok). Çare: kayıt defterini (bayraksız) kafeste biz başlatırız; ardından
    Qt/GTK uygulamaları oturumun AT-SPI ağacına girer (KWin'in kendisi de). IsEnabled=true yazılır."""
    adres = atspi_adresi(d)
    if not adres:
        return None
    pid = (d["pid"] or {}).get("atspi_registryd")
    if not (pid and masaustu._canli(pid)):
        if not os.path.exists(ATSPI_REGISTRYD):
            return None
        with _gunluk(d["calisma"], "atspi") as log:
            p = masaustu.kafeste_baslat(d, [ATSPI_REGISTRYD], kdotool_ortami(d), stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=log)
        d["pid"]["atspi_registryd"] = p.pid
        _durum_yaz(d)

        def a11y_kayit():  # kayıt defteri a11y veri yolunda: --address ile ona bağlan
            try:
                r = subprocess.run(["busctl", f"--address={adres}", "--no-pager", "status", "org.a11y.atspi.Registry"],
                                   capture_output=True, text=True, timeout=3, env=kdotool_ortami(d))
                return r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                return False
        if not _bekle(lambda: a11y_kayit() or p.poll() is not None, 6, 0.1) or p.poll() is not None:
            d["uyarilar"].append(_("at-spi2-registryd başlamadı: {hata}").format(hata=_log_sonu(d["calisma"], "atspi")))
            return None
    _busctl(d, "set-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled", "b", "true")
    return adres


class EisHatasi(Dur):
    """deskhand-eis `hata <neden>` dedi. neden: yardımcının kısa nedeni (ör. "yazilamaz şğ")."""

    def __init__(self, neden: str):
        kod = 1 if neden.startswith(("yazilamaz", "bilinmeyen", "mouseto", "mousemove", "MS-", "sayi")) else ARAC_EKSIK
        super().__init__(kod, _("girdi yardımcısı: {neden}").format(neden=neden))
        self.neden = neden

    @property
    def yazilamayanlar(self) -> str:
        return self.neden.split(" ", 1)[1] if self.neden.startswith("yazilamaz ") else ""


class Eis:
    """Kalıcı deskhand-eis süreci (KWin EIS). gonder(*satirlar) dotool satır dilini yollar, her satırın yanıtını bekler.
    Kapanışta (kapat / with çıkışı / gc) süreç stdin EOF alır ve basılı kalan her şeyi bırakır."""

    def __init__(self, d: dict, zaman_asimi: float = 10.0):
        yol = yollar.eis_bin()
        if not yol:
            raise Dur(ARAC_EKSIK, _("deskhand-eis yok (make -C deskhand/yardimci deskhand-eis)"))
        self.zaman_asimi = zaman_asimi
        self._d = d
        self.basili_dugme: set[str] = set()  # gönderdiğimiz buttondown/buttonup'tan: çökme kurtarması için
        self._log = _gunluk(d["calisma"], "eis")
        # ortam: asgari; veri yolu YALNIZ --bus argümanıyla (yardımcı ortamdan devralmaz)
        self.p = subprocess.Popen([yol, "--bus", d["dbus_adres"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self._log, env={"PATH": ASGARI_PATH}, start_new_session=True)
        self.pid = self.p.pid
        self._tampon = b""
        try:
            ilk = self._satir_oku(max(zaman_asimi, 15.0))
        except BaseException:
            self.kapat()
            raise
        m = re.fullmatch(r"hazir (\d+) (\d+)", ilk)
        if not m:
            self.kapat()
            raise Dur(ARAC_EKSIK, _("girdi yardımcısı hazır olmadı: {yanit}").format(yanit=ilk or _("yanıt yok")))
        self.boyut = (int(m.group(1)), int(m.group(2)))

    def _satir_oku(self, sure: float) -> str:
        fd = self.p.stdout.fileno()
        bitis = time.monotonic() + sure
        while b"\n" not in self._tampon:
            kalan = bitis - time.monotonic()
            if kalan <= 0:
                raise Dur(ZAMAN_ASIMI, _("girdi yardımcısı {sn} sn içinde yanıt vermedi").format(sn=f"{sure:.0f}"))
            if not select.select([fd], [], [], kalan)[0]:
                continue
            b = os.read(fd, 65536)
            if not b:
                kod = self.p.poll()
                raise Dur(ARAC_EKSIK, _("girdi yardımcısı kapandı (çıkış {kod})").format(kod=kod))
            self._tampon += b
        satir, _ayrac, self._tampon = self._tampon.partition(b"\n")
        return satir.decode("utf-8", "replace")

    def satir(self, satir: str, sure: float | None = None) -> str:
        """Tek satır gönder, yanıtın "tamam" sonrası kısmını döndür; "hata …" → EisHatasi."""
        if "\n" in satir:
            raise Dur(1, _("girdi satırında satır sonu olamaz"))
        try:
            self.p.stdin.write(satir.encode() + b"\n")
            self.p.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            raise Dur(ARAC_EKSIK, _("girdi yardımcısı kapandı (çıkış {kod})").format(kod=self.p.poll()))
        # type uzun sürebilir: süre = temel + karakter başına
        y = self._satir_oku(sure or self.zaman_asimi + len(satir) * 0.05)
        if y == "tamam" or y.startswith("tamam "):
            self._basili_izle(satir)
            return y[6:]
        if y.startswith("hata "):
            raise EisHatasi(y[5:])
        return y  # yazilamaz … (sorgu sonucu)

    def _basili_izle(self, satir: str) -> None:
        k, _a, arg = satir.strip().partition(" ")
        k, arg = k.lower(), arg.strip().lower()
        if k == "buttondown":
            self.basili_dugme.add(arg)
        elif k == "buttonup":
            self.basili_dugme.discard(arg)
        elif k == "birak":
            self.basili_dugme.clear()

    def gonder(self, *satirlar: str) -> list[str]:
        """Satırları sırayla gönder (hata olursa durur ve basılı kalanları bırakır)."""
        yanitlar = []
        try:
            for s in satirlar:
                yanitlar.append(self.satir(s))
        except BaseException:
            try:
                self.birak()
            except Exception:  # noqa: BLE001
                pass
            raise
        return yanitlar

    def yaz(self, metin: str) -> None:
        """Metni yaz: satır sonları Enter tuşuna bölünür; yazılamayan karakterde EisHatasi (hiçbir şey yazılmaz
        o parçada; çağıran pano yoluna düşebilir)."""
        for i, parca in enumerate(metin.split("\n")):
            if i:
                self.satir("key enter")
            if parca:
                self.satir("type " + parca)

    def yazilamayanlar(self, metin: str) -> str:
        """Klavye düzeninde olmayan karakterler (girdi göndermez)."""
        y = self.satir("yazilabilir " + metin.replace("\n", " "))
        return y.split(" ", 1)[1] if y.startswith("yazilamaz ") else ""

    def birak(self) -> None:
        self.satir("birak")

    def kurtar(self) -> list[str]:
        """Yardımcı SIGKILL/çökmeyle öldüyse: KWin 6.8'de EIS kopunca basılı TUŞLAR bırakılır ama basılı fare DÜĞMESİ
        bırakılmaz (ölçüldü); yeni bir istemciden `buttonup` da etkisizdir (düğme bağlantıya bağlı izlenir).
        Çare: yeni bağlantıdan o düğmeye bir `click` (bas + bırak): son bırakma uygulamaya ulaşır. → bırakılanlar.
        Yardımcı canlıysa yalnız `birak` gönderilir."""
        if self.p.poll() is None:
            try:
                self.birak()
            except Dur:
                pass
            return []
        kalan = sorted(self.basili_dugme)
        if kalan:
            try:
                with Eis(self._d, self.zaman_asimi) as yeni:
                    for b in kalan:
                        yeni.satir(f"click {b}")
            except Dur:
                return []
        self.basili_dugme.clear()
        return kalan

    def kapat(self) -> None:
        p = self.p
        if p.poll() is not None and self.basili_dugme:  # çökmüş: basılı düğmeyi kurtar
            try:
                self.kurtar()
            except Exception:  # noqa: BLE001
                pass
        try:
            if p.stdin and not p.stdin.closed:
                p.stdin.close()  # EOF: yardımcı basılı her şeyi bırakıp çıkar
        except OSError:
            pass
        try:
            p.wait(3)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for f in (p.stdout, self._log):
            try:
                f.close()
            except (OSError, AttributeError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.kapat()
