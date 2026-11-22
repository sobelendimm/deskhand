"""Yalıtık arka plan KWin oturumu: `kwin_wayland --virtual` + özel D-Bus + özel Wayland soketi (+ XWayland).
Arka plan masaüstünün KWin türünün yaşam döngüsü. Tek giriş noktası masaustu.py'dir (masaustu_baslat koşullar
uygunsa bunu kullanır, durum RUNTIME_DIR/sanal.json'da "tur": "kwin" ile durur; arka uç: arka_uc/kwin.py). Bu modül
masaustu.py'yi içe AKTARMAZ (ortak yapı taşları arka_ortak.py'de); testler doğrudan da kullanabilir:

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

GPU: birden çok render aygıtı varsa oturum boot_vga=0 olan TÜMLEŞİK GPU'yu kullanır
(arka plan masaüstü en çok kullanıcı oyun oynarken çalışır: oyun GPU'sundan zaman çalmasın); KWIN_RENDER_NODES ile
verilir (ölçüldü: KWin 6.8 sanal arka ucu bu değişkeni kabul ediyor; KWIN_DRM_DEVICES yalnız DRM arka ucu içindir).
KWin'in OpenGL oluşturucu adı d["gpu"]'ya yazılır; istemcilerin aygıtı surec_gpu_pci ile doğrulanır (testler). Uygun
aygıt yoksa KWin'in varsayılanı; o GPU'yla açılamazsa bir kez varsayılanla.
"""
from __future__ import annotations

import glob
import json
import os
import re
import secrets
import select
import shutil
import signal
import socket
import subprocess
import time

from . import arka_ortak as ao
from . import yollar
from .hata import ARAC_EKSIK, SANAL_KAPALI, ZAMAN_ASIMI, Dur
from .i18n import _

ASGARI_SURUM = (6, 8)          # EIS + ScreenShot2 yetkisiz (X-KDE-DBUS-Restricted-Interfaces yok) KWin 6.8'den beri
ILK_XEKRAN = 120               # Xvfb masaüstü :90'dan başlar; çakışmasın
OTURUM_ONEK = "kwin-"
DURUM_DOSYASI = "oturum.json"
ASGARI_PATH = ao.GUVENLI_PATH  # yalnız root korumalı dizinler (denetim 12c Y2)
YEDEK_PATH = ASGARI_PATH
# Uygulama araçkiti ipuçları: açıkça verilirse uygulama ortamında değişebilen (güvenlikle ilgisiz) değişkenler
ARAC_IPUCLARI = ("QT_QPA_PLATFORM", "GDK_BACKEND", "MOZ_ENABLE_WAYLAND", "SDL_VIDEODRIVER", "SDL_VIDEO_DRIVER",
                 "ELECTRON_OZONE_PLATFORM_HINT")
# Gecko tarayıcıları (Firefox ve türevleri) KWin türünde XWayland'den çalışır: yerel Wayland'de Gecko'nun erişilebilirlik
# (AT-SPI) ekran koordinatları MUTLAK değildir (Wayland'de genel koordinat yok; SCREEN = WINDOW, köken Gecko'nun
# kendi tahmini: ölçüldü, çerçeve 26,23 ↔ KWin geometrisi 320,54) → ögelere tık konumu doğrulanamaz. XWayland'de
# ekran koordinatı mutlak ve KWin geometrisiyle tutarlıdır (tık/ekran görüntüsü aynı uzay).
GECKO_PROGRAMLAR = frozenset({"firefox", "firefox-esr", "firefox-bin", "firefox-developer-edition", "firefox-nightly",
                              "librewolf", "floorp", "waterfox", "zen", "zen-browser", "icecat", "thunderbird"})
GECKO_IPUCLARI = {"GDK_BACKEND": "x11", "MOZ_ENABLE_WAYLAND": "0"}


# Chromium/Electron ailesi (uygulama.ERISIM_BAYRAGI'nı taşıyan komut) de KWin türünde XWayland'den çalışır: yerel Wayland'de
# Chromium'un AT-SPI çerçeve sınırları pencere geometrisine uymuyor (ölçüldü: web yolu "öge konumu doğrulanamadı", Dur 2,
# konum_coz None); X11'de mutlak ve tutarlı (tık doğru ögeye düşer).
OZONE_X11_BAYRAGI = "--ozone-platform=x11"


def chromium_x11(argv) -> tuple[list, dict]:
    """Komut Chromium/Electron ailesindeyse (erişilebilirlik bayrağı eklenmiş) → (X11 bayraklı komut, X11 ipucu env);
    değilse (komut, {}). Bayrak erişilebilirlik bayrağının hemen arkasına girer (uygulama bayraklarının yeri: Flatpak
    sarmalayıcıda da uygulamaya gider); açıkça --ozone-platform verilmişse dokunulmaz."""
    from .uygulama import ERISIM_BAYRAGI
    argv = list(argv or [])
    if ERISIM_BAYRAGI not in argv or any(str(a).startswith("--ozone-platform") for a in argv):
        return argv, {}
    argv.insert(argv.index(ERISIM_BAYRAGI) + 1, OZONE_X11_BAYRAGI)
    return argv, {"ELECTRON_OZONE_PLATFORM_HINT": "x11"}


def _program_adlari(argv) -> set[str]:
    """Başlatılacak programın olası adları: MCP open_app `gio launch X.desktop` → girdinin Exec'i; `env [VAR=…]`
    öneki atlanır; ad hem yazıldığı gibi hem PATH + sembolik bağ çözülmüş hâliyle (firefox → /usr/lib/firefox/firefox)."""
    argv = [str(a) for a in (argv or [])]
    if len(argv) >= 3 and os.path.basename(argv[0]) == "gio" and argv[1] == "launch" and argv[2].endswith(".desktop"):
        from .uygulama import _desktop_exec
        argv = [str(a) for a in (_desktop_exec(argv[2]) or [])]
    while argv and os.path.basename(argv[0]) == "env":
        argv = argv[1:]
        while argv and (argv[0].startswith("-") or ("=" in argv[0] and not argv[0].startswith("/"))):
            argv = argv[1:]
    if not argv:
        return set()
    adlar = {os.path.basename(argv[0])}
    yol = shutil.which(argv[0])
    if yol:
        adlar.add(os.path.basename(os.path.realpath(yol)))
    return adlar


def gecko_ipuclari(argv) -> dict:
    """Başlatılan program bir Gecko tarayıcısıysa XWayland ipuçları (açıkça verilen env bunları ezer), değilse {}.
    MCP open_app'in `gio launch firefox.desktop` yolu da (girdinin Exec'i) tanınır — ortam gio'dan uygulamaya geçer."""
    return dict(GECKO_IPUCLARI) if _program_adlari(argv) & set(GECKO_PROGRAMLAR) else {}


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
    """KATI biçim: yalnız `unix:path=/yol[,guid=<32 hex>]` → /yol. `;` ile çoklu adres (sd-bus/libdbus ilki
    olmazsa SONRAKİNE geçer: kapıyı atlatıyordu) ya da başka biçim → None."""
    return ao.bus_yolu_kati(adres)


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
        if (gy is not None and _ayni_yol(yol, gy)) or gercek.split(",", 1)[0] == bus_adres.split(",", 1)[0] or \
                (gy is not None and ao.soket_kimligi(gy) is not None and ao.soket_kimligi(yol) == ao.soket_kimligi(gy)):
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


KIMLIK_RX = re.compile(r"[0-9a-f]{8}")


def guvenli_kayit(d: dict) -> dict:
    """Durum kaydından YALNIZ oturum kimliği ve sayılar alınır; bütün yollar/adresler oturum çalışma dizininden KURULUR
    (çalışma dizini = RUNTIME_DIR/kwin-<kimlik>, sembolik bağ değil, kullanıcıya ait, 0700): veri yolu
    `unix:path=<dizin>/bus`, Wayland soketi `<dizin>/deskhand-<kimlik>`, Xauthority, XWayland ekranı (:120+),
    erişilebilirlik adresi (yalnız <dizin>/at-spi altındaysa). Oynanmış kayıt (`;` çoklu adres, başka yol) böylece hiçbir
    şeyi yönlendiremez. Geçersizse Dur(14). Süreç başlatmaz, bağlanmaz (~0,05 ms)."""
    kimlik = str((d or {}).get("kimlik") or "")
    if not KIMLIK_RX.fullmatch(kimlik):
        raise Dur(SANAL_KAPALI, _("KWin oturum kaydı geçersiz (kimlik): {kimlik}").format(kimlik=repr(kimlik)))
    kok = os.path.realpath(yollar.runtime_dir())
    ao.runtime_denetle(kok)
    cdir = os.path.join(kok, OTURUM_ONEK + kimlik)
    try:
        st = os.lstat(cdir)
    except OSError:
        raise Dur(SANAL_KAPALI, _("KWin oturum dizini yok: {dizin}").format(dizin=cdir))
    import stat as _stat
    if not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o700:
        raise Dur(SANAL_KAPALI, _("KWin oturum dizini güvensiz: {dizin}").format(dizin=cdir))
    g = dict(d)
    wad = f"deskhand-{kimlik}"
    g.update(kimlik=kimlik, calisma=cdir, wayland=wad, wayland_yol=os.path.join(cdir, wad), ekran=wad,
             dbus_adres=f"unix:path={cdir}/bus")
    x = d.get("x_ana")
    if x is not None:
        if not (isinstance(x, int) and ILK_XEKRAN <= x < ILK_XEKRAN + 400):
            raise Dur(SANAL_KAPALI, _("KWin oturum kaydı geçersiz (XWayland ekranı): {x}").format(x=repr(x)))
        g.update(x_ana=x, xwayland=f":{x}", xauth=os.path.join(cdir, "Xauthority"))
    else:
        g.update(x_ana=None, xwayland=None, xauth=None)
    a11y = d.get("a11y_adres") or ""
    if a11y and not re.fullmatch(re.escape(f"unix:path={cdir}/at-spi/bus") + r"(_\d+)?(,guid=[0-9a-f]{32})?", a11y):
        g["a11y_adres"] = None
    g["a11y_dizin_kimlik"] = ao.a11y_kimlik_temizle(d)
    kafes = d.get("kafes")
    if kafes and not re.fullmatch(rf"deskhand-kwin-{kimlik}-\d+\.scope", str(kafes)):
        raise Dur(SANAL_KAPALI, _("KWin oturum kaydı geçersiz (kafes): {kafes}").format(kafes=repr(kafes)))
    if (d.get("cgroup") or "") and not (kafes and str(d["cgroup"]).endswith("/" + kafes)):
        g["cgroup"] = ""
    return g


_KARSI_ONBELLEK: dict = {}
KARSI_SURE = 1.0  # sn: aynı soketler + aynı süreçler için doğrulama sonucu bu kadar geçerli (sık komutlarda ~ms kazanç)


def _karsi_denetle(g: dict) -> None:
    """Bağlanılacak soketlerin KARŞI TARAFI bu oturumun süreçleri mi (sert bağ / yer değiştirme ile kullanıcının
    gerçek veri yoluna/compositor'ına yönlendirmeye karşı): veri yolu soketinin SO_PEERCRED PID'i kayıttaki
    dbus-daemon (başlangıç zamanı aynı, komut satırında `--config-file=<dizin>/bus.conf`), Wayland soketininki kayıttaki
    KWin; iki soket de kullanıcının gerçek soketlerinden birinin (st_dev, st_ino) kopyası olmamalı. Başarılı sonuç
    (soket inode'ları, PID'ler, başlangıç zamanları) anahtarıyla KARSI_SURE boyunca önbellekte: soket değişirse ya da
    süreç yeniden doğarsa anahtar değişir, yeniden doğrulanır."""
    pid = g.get("pid") or {}
    bas = g.get("pid_bas") or {}
    bus_yol = os.path.join(g["calisma"], "bus")
    anahtar = (g["calisma"], ao.soket_kimligi(bus_yol), ao.soket_kimligi(g["wayland_yol"]), pid.get("dbus"),
               bas.get("dbus"), pid.get("kwin"), bas.get("kwin"))
    t = _KARSI_ONBELLEK.get(anahtar)
    if t is not None and time.monotonic() - t < KARSI_SURE and None not in anahtar[1:3]:
        return
    gercek = ao.gercek_soket_kimlikleri()
    for yol, ad in ((os.path.join(g["calisma"], "bus"), "dbus"), (g["wayland_yol"], "kwin")):
        if ao.soket_kimligi(yol) in gercek:
            raise Dur(SANAL_KAPALI, _("oturum soketi kullanıcının gerçek soketinin sert bağı: {yol}; bağlanılmadı").format(
                yol=yol))
        karsi = ao.soket_karsi_pid(yol)
        if not karsi or karsi != pid.get(ad) or not ao.pid_dogru(karsi, bas.get(ad)):
            raise Dur(SANAL_KAPALI, _("oturum soketinin karşı tarafı bu oturumun {ad} süreci değil ({karsi}); "
                                      "bağlanılmadı").format(ad=ad, karsi=karsi))
    if f"--config-file={g['calisma']}/bus.conf" not in ao._komut_satiri(pid.get("dbus")):
        raise Dur(SANAL_KAPALI, _("özel veri yolu süreci bu oturumun yapılandırmasıyla çalışmıyor; bağlanılmadı"))
    _KARSI_ONBELLEK.clear()
    _KARSI_ONBELLEK[anahtar] = time.monotonic()


def baglanti_denetle(d: dict) -> dict:
    """HER bağlantıdan önce (arka_uc/kwin.py: kdotool, deskhand-goruntu, deskhand-eis, wl-copy/wl-paste, busctl;
    uygulama başlatma): kayıt → güvenli kayıt (guvenli_kayit: yollar oturum dizininden kurulur), guvenlik_kapilari,
    karşı taraf doğrulaması (_karsi_denetle: SO_PEERCRED + sert bağ). → GÜVENLİ kayıt (çağıran yalnız bunu kullanır).
    Değilse Dur(14)."""
    g = guvenli_kayit(d)
    cdir = g["calisma"]
    guvenlik_kapilari(g["dbus_adres"], g["wayland"], os.path.join(cdir, "ev", "config"), home=os.path.join(cdir, "ev"),
                      calisma=cdir, xekran=g.get("xwayland"))
    gr = _gercek_degerler()
    for w in gr["wayland"]:
        if _ayni_yol(g["wayland_yol"], w if os.path.isabs(w) else os.path.join(gr["runtime"], w)):
            raise Dur(SANAL_KAPALI, _("Wayland soketi kullanıcının gerçek soketi; bağlanılmadı"))
    _karsi_denetle(g)
    return g


def canli_mi(d: dict) -> bool:
    """Kayıttaki KWin süreci (PID + komut satırında özel soket adı) ve Wayland soketi yaşıyor mu."""
    return _kwin_mi(d) and os.path.exists(d.get("wayland_yol") or "")


# ---------------------------------------------------------------- GPU seçimi

def _oku(yol: str) -> str:
    try:
        with open(yol) as f:
            return f.read().strip()
    except OSError:
        return ""


def render_aygitlari() -> list[dict]:
    """Bu makinedeki render aygıtları (sysfs; salt okunur) → [{dugum, kart, boot_vga, bagli, tumlesik, surucu, pci}].
    bagli: karta bağlı (connected) bir ekran çıkışı var mı. tumlesik: amdgpu'da görüntü belleği <= 2 GiB (APU'nun
    ayrılmış belleği), i915'te PCI veri yolu 00 (işlemci içi). Sabit PCI adresi kullanılmaz."""
    sonuc = []
    for kart in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        ad = os.path.basename(kart)
        if not re.fullmatch(r"card\d+", ad):
            continue
        aygit = os.path.join(kart, "device")
        try:
            render = sorted(x for x in os.listdir(os.path.join(aygit, "drm")) if x.startswith("renderD"))
        except OSError:
            continue
        if not render:
            continue
        dugum = os.path.join("/dev/dri", render[0])
        if not os.path.exists(dugum):
            continue
        surucu = os.path.basename(os.path.realpath(os.path.join(aygit, "driver")))
        pci = os.path.basename(os.path.realpath(aygit))
        bagli = any(_oku(os.path.join(c, "status")) == "connected" for c in glob.glob(f"{kart}-*"))
        vram = _oku(os.path.join(aygit, "mem_info_vram_total"))
        tumlesik = (surucu == "amdgpu" and vram.isdigit() and int(vram) <= 2 << 30) or \
            (surucu == "i915" and pci.split(":")[1:2] == ["00"])
        sonuc.append({"dugum": dugum, "kart": ad, "boot_vga": _oku(os.path.join(aygit, "boot_vga")), "bagli": bagli,
                      "tumlesik": tumlesik, "surucu": surucu, "pci": pci,
                      "erisim": os.access(dugum, os.R_OK | os.W_OK)})
    return sonuc


def render_sec(aygitlar: list[dict] | None = None) -> dict | None:
    """Oturumun render aygıtı: birden çok aygıt varsa boot_vga=0 + tümleşik + erişilebilir ilk aygıt (bağlı çıkış
    bilgisi yalnız tanılama içindir: hotplug/sürücüye göre yanıltıcı olabilir); yoksa None (KWin'in varsayılanı: tek aygıt ya da uygun aday yok). DESKHAND_KWIN_GPU=varsayilan ile
    kapatılabilir (tanılama)."""
    if (os.environ.get("DESKHAND_KWIN_GPU") or "").strip().lower() in ("varsayilan", "default", "0"):
        return None
    aygitlar = render_aygitlari() if aygitlar is None else aygitlar
    if len(aygitlar) < 2:
        return None
    for a in aygitlar:
        if a["erisim"] and a["boot_vga"] == "0" and a["tumlesik"]:  # "bağlı çıkış" bilgisine güvenilmez
            return a
    return None


def surec_gpu_pci(pid) -> list[str]:
    """Sürecin kullandığı GPU'ların PCI adresleri (/proc/<pid>/fdinfo, "drm-pdev:"; yalnız kendi süreçlerimiz okunur).
    KWin'in kendisi yetenekli ikili olduğu için okunamaz: oturumdaki bir Wayland istemcisi (dmabuf geri bildirimiyle
    KWin'in aygıtını seçer) üzerinden doğrulanır (testler)."""
    sonuc = set()
    try:
        for fd in os.listdir(f"/proc/{int(pid)}/fdinfo"):
            try:
                with open(f"/proc/{int(pid)}/fdinfo/{fd}") as f:
                    for satir in f:
                        if satir.startswith("drm-pdev:"):
                            sonuc.add(satir.split(":", 1)[1].strip())
            except OSError:
                continue
    except (OSError, ValueError, TypeError):
        pass
    return sorted(sonuc)


# ---------------------------------------------------------------- sürüm / kullanılabilirlik

def kwin_surumu() -> tuple[int, ...] | None:
    try:
        kw = ao.arac("kwin_wayland", zorunlu=False)
        if not kw:
            return None
        c = subprocess.run([kw, "--version"], capture_output=True, text=True, timeout=5,
                           env={"PATH": ASGARI_PATH}).stdout
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
    from .arka_uc.kwin import pencere_araci
    for arac in ("bwrap", "dbus-daemon", "nice", "ionice", "sh", "busctl", "env", "systemd-run", pencere_araci()):
        if not ao.arac(arac, zorunlu=False):
            return False, _("{arac} yok (ya da güvenli dizinde değil: /usr/bin, /bin)").format(arac=arac)
    if not any(a["erisim"] for a in render_aygitlari()):
        return False, _("erişilebilir render aygıtı yok (/dev/dri/renderD*)")
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
    WAYLAND_DISPLAY / DISPLAY / DBUS_SESSION_BUS_ADDRESS değerleri burada yoktur ve asla eklenmez. KDE_FULL_SESSION /
    KDE_SESSION_VERSION KWin'e VERİLMEZ (tam Plasma oturumu yoluna girmesin; uygulamalara ve kdotool'a verilir); yetki
    kapatıcı (KWIN_WAYLAND_NO_PERMISSION_CHECKS) gerekmiyor (6.8: EIS + ScreenShot2 yetkisiz). ATSPI_DBUS_IMPLEMENTATION:
    özel veri yolunun etkinleştirdiği at-spi-bus-launcher kendi dbus-daemon'unu açsın (dbus-broker --scope=user
    kullanıcının GERÇEK erişilebilirlik veri yolunu yeniden kullanabiliyordu)."""
    ev = os.path.join(d["calisma"], "ev")
    gpu = {"KWIN_RENDER_NODES": d["render_dugumu"]} if d.get("render_dugumu") else {}
    return {
        **gpu,
        # özel bin dizini önce: KWin Xwayland'i PATH'ten bulur → takma adlı sarmalayıcı (_ozel_adlar)
        "PATH": f"{os.path.join(d['calisma'], 'bin')}:{ASGARI_PATH}",
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
        "ATSPI_DBUS_IMPLEMENTATION": "dbus-daemon",
    }


def kdotool_ortami(d: dict) -> dict:
    """kdotool / goruntu / busctl gibi İSTEMCİ araçlar için asgari ortam (özel veri yolu). Yollar KAYITTAN değil oturum
    dizininden kurulur (guvenli_kayit)."""
    d = guvenli_kayit(d)
    return {"PATH": ASGARI_PATH, "HOME": os.path.join(d["calisma"], "ev"), "XDG_RUNTIME_DIR": d["calisma"],
            "DBUS_SESSION_BUS_ADDRESS": d["dbus_adres"], "KDE_SESSION_VERSION": "6", "XDG_CURRENT_DESKTOP": "KDE",
            "XDG_SESSION_TYPE": "wayland", "LANG": os.environ.get("LANG") or "C.UTF-8"}


def uygulama_ortami(d: dict, env: dict | None = None, izinli: tuple = ()) -> dict:
    """Bu oturumda başlatılacak uygulamaların ortamı: os.environ + env; kullanıcının oturumuna ait değişkenler
    (arka_ortak.CIKARILACAK_ORTAM: gerçek veri yolu, Wayland/X ekranı, Xauthority, erişilebilirlik adresi, ses
    sunucusu, SSH ajanı, EIS/libei soketi…) birleştirmeden önce ve SONRA silinir, üstüne oturum değerleri ZORLA yazılır.
    Xvfb türüyle aynı güvenceler (ses bölümü aynı işlevden). `env` yalnız araç takımı ipuçlarını (QT_QPA_PLATFORM,
    GDK_BACKEND…) değiştirebilir; ekran/veri yolu/ses değişkenleri her zaman oturumundur."""
    e = ao.ortam_tabani(env, izinli)
    e.update({
        "DBUS_SESSION_BUS_ADDRESS": d["dbus_adres"],
        # Chromium/Electron anahtarlık arka ucunu bunlardan seçer
        "XDG_CURRENT_DESKTOP": "KDE",
        "KDE_SESSION_VERSION": "6",
        # oturumun içinden çalışan süreçler (tespit, kde.pano_ortami) kendilerini arka plan masaüstünde bilsin
        "DESKHAND_SANAL": d.get("ekran") or d.get("wayland") or OTURUM_ONEK + str(d.get("kimlik")),
    })
    if d.get("kimlik"):  # durdururken kafes dışındaki/kafessiz süreçler de bulunabilsin (_isaretli_surecler)
        e["DESKHAND_SANAL_KIMLIK"] = d["kimlik"]
    ao.ses_ortami_uygula(e, d.get("ses"), os.path.join(d["calisma"], "ses-yok"))
    e["XDG_RUNTIME_DIR"] = ao.uygulama_runtime(d["calisma"])  # masaüstünün kendi klasörü (kullanıcınınki değil)
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
            self.temizle()  # yalnız BİZİM oluşturduğumuz soket/kilit dosyaları (başkasınınkine dokunulmaz)
            raise

    def fdler(self) -> tuple[list[int], int]:
        return [self.soketler[0].fileno(), self.soketler[1].fileno()], self.soketler[2].fileno()

    def kilit_pid(self, pid: int) -> None:
        for yol in self.kilitler:  # kilit 0444 açıldı: yazmak için kısa süre sahibine yazma izni
            try:
                os.chmod(yol, 0o644)
                with open(yol, "w") as f:
                    f.write(f"{pid:10d}\n")
                os.chmod(yol, 0o444)
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
    """Durum kaydından: bu oturumun X soketlerini ve kilitlerini sil. Yalnız :120+ (kullanıcının :0/:1'i asla) ve kilit
    ya ölü bir sürece ya da kayıttaki KWin'e (başlangıç zamanı doğrulanmış) aitse; başkasının kilidine dokunulmaz."""
    ana = d.get("x_ana")
    if not (isinstance(ana, int) and ILK_XEKRAN <= ana < ILK_XEKRAN + 400):
        return []
    kwin = (d.get("pid") or {}).get("kwin")
    kwin_bas = (d.get("pid_bas") or {}).get("kwin")
    for no in (ana, ana + 1):
        yol = f"/tmp/.X{no}-lock"
        try:
            with open(yol) as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            continue
        if not ao._canli(pid) or (pid == kwin and ao.pid_dogru(pid, kwin_bas)):
            for y in (yol, f"{X_DIZIN}/X{no}"):
                try:
                    os.unlink(y)
                except OSError:
                    pass
    return []


def _bos_x_cifti(bas: int = ILK_XEKRAN) -> int:
    for n in range(bas, bas + 200, 2):
        if all(not os.path.exists(f"{X_DIZIN}/X{k}") and not os.path.exists(f"/tmp/.X{k}-lock") for k in (n, n + 1)):
            return n
    raise Dur(ARAC_EKSIK, _("boş X ekran numarası bulunamadı"))


# ---------------------------------------------------------------- yardımcı: bekle, kafes, başlat

def _bekle(kosul, sure: float, aralik: float = 0.02) -> bool:
    return ao._bekle(kosul, sure, aralik)


def _gunluk(cdir: str, ad: str):
    return open(os.path.join(cdir, f"{ad}.log"), "ab")


def _log_sonu(cdir: str, ad: str, n: int = 400) -> str:
    try:
        with open(os.path.join(cdir, f"{ad}.log"), errors="replace") as f:
            return f.read()[-n:].strip()
    except OSError:
        return ""


def _busctl(d: dict, *a, zaman: float = 5.0) -> subprocess.CompletedProcess:
    d = guvenli_kayit(d)
    return subprocess.run([ao.arac("busctl"), f"--address={d['dbus_adres']}", "--no-pager", *a], capture_output=True, text=True,
                          timeout=zaman, env=kdotool_ortami(d))


def _kwin_hazir(d: dict) -> bool:
    try:
        return _busctl(d, "status", "org.kde.KWin", zaman=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _kwin_bilgisi(d: dict) -> str:
    """org.kde.KWin.supportInformation (özel veri yolunda; tanılama/ölçüm)."""
    try:
        return _busctl(d, "call", "org.kde.KWin", "/KWin", "org.kde.KWin", "supportInformation", zaman=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _hazir_denetle(d: dict, k: subprocess.Popen) -> None:
    """Oturum "hazır" sayılmadan önce (KWin beklerken ölürse HEMEN hata): ScreenShot2 arayüzü yayında, bir kare
    yakalanabiliyor ve boyutu oturum boyutu (ölçek 1: KWin'in çıkış deposu ölçeği ezmedi), EIS aygıtları hazır ve
    bölgesi aynı boyut; KWin'in OpenGL oluşturucu adı kaydedilir."""
    def oldu():
        if k.poll() is not None:
            raise Dur(ARAC_EKSIK, _("KWin hazırlanırken kapandı: {hata}").format(hata=_log_sonu(d["calisma"], "kwin")))

    def ss2():
        oldu()
        try:
            return _busctl(d, "introspect", "org.kde.KWin", "/org/kde/KWin/ScreenShot2",
                           "org.kde.KWin.ScreenShot2", zaman=3).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if not _bekle(ss2, 10, 0.05):
        raise Dur(ARAC_EKSIK, _("KWin ScreenShot2 arayüzü hazır olmadı"))
    hedef = tuple(d["boyut"][:2])
    son = None
    for _i in range(50):
        oldu()
        try:
            im = goruntu(d)
            if im.size == hedef:
                break
            son = _("kare boyutu {boyut} ≠ oturum {hedef} (ölçek 1 değil?)").format(boyut=im.size, hedef=hedef)
        except Dur as e:
            son = e.mesaj
        time.sleep(0.05)
    else:
        raise Dur(ARAC_EKSIK, _("KWin oturumundan kare alınamadı: {hata}").format(hata=son))
    oldu()
    with Eis(d) as e:
        if e.boyut != hedef:
            raise Dur(ARAC_EKSIK, _("EIS bölgesi {boyut} ≠ oturum {hedef}").format(boyut=e.boyut, hedef=hedef))
    oldu()
    m = re.search(r"OpenGL renderer string:\s*([^\n]+)", _kwin_bilgisi(d).replace("\\n", "\n"))
    d["gpu"] = m.group(1).strip() if m else ""
    if not d["gpu"] or re.search(r"llvmpipe|softpipe|swrast", d["gpu"], re.I):
        d["uyarilar"].append(_("KWin donanım hızlandırması yok ({gpu}): yazılım çizimi").format(gpu=d["gpu"] or "?"))


def oncelik_durumu(pid) -> list[tuple[int, int, int]]:
    """Sürecin iş parçacıkları → [(tid, nice, zamanlama politikası)] (/proc; politika 0 = SCHED_OTHER)."""
    sonuc = []
    try:
        for t in os.listdir(f"/proc/{int(pid)}/task"):
            try:
                with open(f"/proc/{int(pid)}/task/{t}/stat") as f:
                    a = f.read().rsplit(")", 1)[1].split()
                sonuc.append((int(t), int(a[16]), int(a[38])))
            except (OSError, ValueError, IndexError):
                continue
    except (OSError, ValueError, TypeError):
        pass
    return sonuc


def _oncelik_dusur(d: dict, pid: int) -> None:
    """Güvence: KWin'in HER iş parçacığı nice >= 10 ve gerçek zamanlı olmayan zamanlamada. no_new_privs ile normalde
    zaten öyledir; değilse (setpriv yok) iş parçacıkları tek tek düşürülür (kendi süreçlerimiz: izin gerekmez). Yine
    de yükseltilmiş kalan varsa açılış DURUR (arka plan masaüstü kullanıcının önüne geçmesin)."""
    for tid, nice, politika in oncelik_durumu(pid):
        try:
            if politika in (1, 2, 6):  # SCHED_FIFO / SCHED_RR / SCHED_DEADLINE
                # SCHED_RESET_ON_FORK bayrağı yetkisiz temizlenemez: bayrak korunarak SCHED_OTHER'a
                os.sched_setscheduler(tid, os.SCHED_OTHER | getattr(os, "SCHED_RESET_ON_FORK", 0x40000000),
                                      os.sched_param(0))
            if nice < 10:
                os.setpriority(os.PRIO_PROCESS, tid, 10)
        except OSError:
            pass
    tidler = [str(t) for t, _n, _p in oncelik_durumu(pid)]
    if tidler and ao.arac("ionice", zorunlu=False):  # KWin disk iş parçacıklarını best-effort'a çekiyor: hepsi idle
        subprocess.run([ao.arac("ionice"), "-c", "3", "-p", *tidler], capture_output=True, timeout=5,
                       env={"PATH": ASGARI_PATH})
    kalan = [(t, n, p) for t, n, p in oncelik_durumu(pid) if n < 10 or p in (1, 2, 6)]
    if kalan:
        raise Dur(ARAC_EKSIK, _("KWin düşük önceliğe alınamadı (iş parçacığı, nice, politika): {kalan}").format(
            kalan=kalan[:5]))


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


XWAYLAND_AD = "deskhand-xwayland"  # oturumun XWayland'i bu adla çalışır (ad tabanlı öncelik kuralları eşleşmesin)


def _kwin_mi(d: dict) -> bool:
    pid = (d.get("pid") or {}).get("kwin")
    kom = ao._komut_satiri(pid)
    return ao._canli(pid) and any(os.path.basename(k) == "kwin_wayland" for k in kom[:1]) and \
        bool(d.get("wayland")) and d.get("wayland") in kom


def _ozel_adlar(cdir: str) -> str:
    """<çalışma>/bin + süreç adları. Neden (ölçüldü): sistemdeki ananicy-cpp kuralları süreç ADINA göre `kwin_wayland`
    ve `Xwayland`'i LowLatency_RT'ye (nice -12, best-effort G/Ç) çekiyor; arka plan oturumu oyun oynayan kullanıcıdan
    işlemci çalardı. Xwayland: KWin onu PATH'ten bulur → bu dizindeki küçük `Xwayland` betiği takma adlı bağa
    (deskhand-xwayland) exec eder (betik anlık yaşar). KWin'in dosya adı `kwin_wayland` olmak ZORUNDA (ölçüldü: başka
    adla abort) ve başka sürecin adı değiştirilemiyor: KWin'i kafesin öncelik bekçisi (oncelik_bekcisi.py) geri düşürür.
    → KWin'in çalıştırılacak yolu."""
    b = os.path.join(cdir, "bin")
    os.makedirs(b, mode=0o700, exist_ok=True)
    kwin = ao.arac("kwin_wayland")
    xw = ao.arac("Xwayland", zorunlu=False)
    if xw:
        os.symlink(os.path.realpath(xw), os.path.join(b, XWAYLAND_AD))
        betik = os.path.join(b, "Xwayland")
        with open(betik, "w") as f:
            f.write(f'#!/bin/sh\nexec "{os.path.join(b, XWAYLAND_AD)}" "$@"\n')
        os.chmod(betik, 0o700)
    return kwin


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
    """Yalıtık KWin oturumunu başlat → bilgi dict'i. Hata olursa başlatılan her şeyi kapatır. GPU: render_sec()
    tümleşik GPU'yu seçtiyse onunla; o GPU'yla açılamazsa (sürücü/aygıt sorunu) bir kez KWin'in varsayılanıyla."""
    gpu = render_sec()
    if gpu is None:
        return _baslat_tek(boyut, xwayland, duzen, None)
    try:
        return _baslat_tek(boyut, xwayland, duzen, gpu["dugum"])
    except Dur as e:
        d = _baslat_tek(boyut, xwayland, duzen, None)
        d["uyarilar"].append(_("tümleşik GPU ({dugum}) ile açılamadı ({hata}); varsayılan GPU kullanılıyor").format(
            dugum=gpu["dugum"], hata=e.mesaj))
        return d


def _baslat_tek(boyut, xwayland: bool, duzen: tuple[str, str], render_dugumu: str | None) -> dict:
    ok, neden = kullanilabilir()
    if not ok:
        raise Dur(ARAC_EKSIK, neden)
    g, y = int(boyut[0]), int(boyut[1])
    if not (320 <= g <= 8192 and 240 <= y <= 8192):
        raise Dur(1, _("geçersiz ekran boyutu: {boyut}").format(boyut=repr(boyut)))
    bellek = ao._bellek_siniri()
    takas = ao._takas_siniri() if bellek else None
    if bellek and not ao.arac("systemd-run", zorunlu=False):
        raise Dur(ARAC_EKSIK, _("systemd-run yok: bellek kafesi kurulamaz (bilerek kapatmak için DESKHAND_SANAL_BELLEK=0)"))
    temizle_kalintilar()
    kimlik = secrets.token_hex(4)
    cdir = _oturum_dizini(kimlik)
    os.makedirs(os.path.dirname(cdir), mode=0o700, exist_ok=True)
    os.makedirs(cdir, mode=0o700)
    soket_adi = f"deskhand-{kimlik}"
    d = {"surum": 1, "tur": "kwin", "kimlik": kimlik, "calisma": cdir, "boyut": [g, y], "duzen": list(duzen),
         "ekran": soket_adi, "render_dugumu": render_dugumu, "wayland": soket_adi, "wayland_yol": os.path.join(cdir, soket_adi), "dbus_adres": f"unix:path={cdir}/bus",
         "xwayland": None, "xauth": None, "x_ana": None, "kafes": None, "cgroup": "", "bellek": bellek,
         "takas": takas, "pid": {}, "ses": None, "uyarilar": [], "baslangic": time.time(),
         "baslatan_pid": os.getpid(), "kwin_surum": ".".join(map(str, kwin_surumu() or ()))}
    try:
        if len(d["wayland_yol"]) > 100 or len(f"{cdir}/bus") > 100:
            raise Dur(ARAC_EKSIK, _("çalışma dizini yolu çok uzun (soket yolu 108 bayt sınırı): {dizin}").format(dizin=cdir))
        ev = os.path.join(cdir, "ev")
        # XDG_*_HOME'lar + standart yerleri (Qt var olmayan standart veri dizininde qFatal verebiliyor)
        for a in ("config", "cache", "data", "state", ".config", ".cache", ".local/share", ".local/state"):
            os.makedirs(os.path.join(ev, a), mode=0o700)
        # a11y dizinini Deskhand kendisi yaratır (uygulama başlamadan önce); kimliği kayıtta karşılaştırılır
        d["a11y_dizin_kimlik"] = ao.a11y_dizini_hazirla(os.path.join(cdir, "at-spi"))
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
    # ses: arka plan uygulamaları ses sunucusuna HİÇ erişmez (bwrap + ortam; boş çıkış/ses bekçisi gerekmez)
    d["ses"] = None
    # 1) özel dbus-daemon: kafesin İLK süreci (systemd-run --scope exec eder: PID dbus-daemon'un kendisi).
    #    Komut `env -i …` ile açılır: systemd-run'ın kendi ortamı (gerçek veri yolu adresi!) dbus-daemon'a GEÇMEZ.
    conf, adres = ao._dbus_yapilandir(cdir)
    if adres != d["dbus_adres"]:
        raise Dur(ARAC_EKSIK, _("özel veri yolu adresi beklenenden farklı: {adres}").format(adres=adres))
    env_args = [f"{k}={v}" for k, v in ortam.items()]
    dbus_cmd = [ao.arac("env"), "-i", *env_args, ao.arac("dbus-daemon"), f"--config-file={conf}", "--nofork",
                "--nopidfile", "--nosyslog"]
    with _gunluk(cdir, "dbus") as log:
        if d["bellek"]:
            kafes = f"deskhand-kwin-{d['kimlik']}-{os.getpid()}.scope"
            komut = [ao.arac("systemd-run"), "--user", "--scope", "--quiet", f"--unit={kafes}",
                     "-p", f"MemoryMax={d['bellek']}", "-p", f"MemorySwapMax={d.get('takas') or '0'}",
                     "-p", "Delegate=yes", "-p", "TimeoutStopSec=5", "--", *ao._oncelik(), *dbus_cmd]
            p = subprocess.Popen(komut, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 env=ao._kullanici_bus_ortami(), start_new_session=True)
            d["kafes"] = kafes
        else:
            d["uyarilar"].append(_("bellek kafesi KAPALI (DESKHAND_SANAL_BELLEK=0)"))
            p = subprocess.Popen([*ao._oncelik(), *dbus_cmd], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 env={"PATH": ASGARI_PATH}, start_new_session=True)
    ao.pid_kaydet(d, "dbus", p.pid)
    _durum_yaz(d)
    bus_soket = adres.split("=", 1)[1]
    if not _bekle(lambda: os.path.exists(bus_soket) or p.poll() is not None, 8) or p.poll() is not None:
        raise Dur(ARAC_EKSIK, _("özel D-Bus (dbus-daemon) açılmadı: {hata}").format(hata=_log_sonu(cdir, "dbus")))
    if d["kafes"]:
        d["cgroup"] = ao._cgroup(p.pid)
        if not d["cgroup"].endswith("/" + d["kafes"]):
            raise Dur(ARAC_EKSIK, _("dbus-daemon bellek kafesinde değil: {cgroup}").format(cgroup=repr(d["cgroup"])))

    # 2) XWayland soketleri + Xauthority
    # no_new_privs: kwin_wayland'in dosya yeteneği (cap_sys_nice) VERİLMEZ → KWin kendini SCHED_RR + nice -12'ye
    # yükseltemez, kafesin nice 10 / ionice idle önceliğinde kalır (ölçüldü: yeteneğiyle -12 + gerçek zamanlı
    # zamanlama; arka plan masaüstü oyun oynayan kullanıcıdan işlemci çalardı). Yan kazanç: süreç /proc'tan okunabilir.
    # RLIMIT_RTPRIO=0 + RLIMIT_NICE=10 (en düşük nice 10): yetenek olmadan da kullanıcı sınırları (limits.conf) izin
    # veriyorsa SCHED_RR alıp nice -12ye inebiliyordu (ölçüldü)
    prlimit, setpriv = ao.arac("prlimit", zorunlu=False), ao.arac("setpriv", zorunlu=False)
    kwin = [*([prlimit, "--rtprio=0", "--nice=10"] if prlimit else []),
            *([setpriv, "--no-new-privs"] if setpriv else []),
            _ozel_adlar(cdir), "--virtual", "--no-lockscreen", "--no-global-shortcuts", "--no-kactivities",
            "--socket", d["wayland"], "--width", str(d["boyut"][0]), "--height", str(d["boyut"][1])]
    xs = None
    fdler: list[int] = []
    try:
        if xekran:
            no = int(xekran[1:])
            for deneme in range(20):  # başka bir oturum aynı anda aynı numarayı aldıysa (O_EXCL kilit) sonrakine geç
                xs = _XSoketleri(no)
                try:
                    xs.ac()
                    break
                except OSError:
                    xs = None
                    if deneme == 19:
                        raise
                    no = _bos_x_cifti(no + 2)
            xekran = f":{no}"
            guvenlik_kapilari(d["dbus_adres"], d["wayland"], os.path.join(cdir, "ev", "config"), xekran=xekran)
            d["xwayland"], d["x_ana"] = xekran, no
            d["xauth"] = os.path.join(cdir, "Xauthority")
            ao._xauth_yaz(d["xauth"], no, secrets.token_bytes(16))
            ana_fd, init_fd = xs.fdler()
            kwin += ["--xwayland", "--xwayland-display", xekran, "--xwayland-init-display", f":{no + 1}",
                     "--xwayland-xauthority", d["xauth"], "--xwayland-initfd", str(init_fd)]
            for fd in ana_fd:
                kwin += ["--xwayland-fd", str(fd)]
            fdler = [*ana_fd, init_fd]
        _durum_yaz(d)
        # 3) KWin (aynı kafeste)
        with _gunluk(cdir, "kwin") as log:
            k = ao.kafeste_baslat(d, kwin, ortam, pass_fds=fdler, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    finally:
        if xs is not None:
            xs.kapat()  # KWin kendi kopyalarını tutar
    ao.pid_kaydet(d, "kwin", k.pid)
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
    _oncelik_dusur(d, k.pid)
    # ad tabanlı sistem kuralları (ananicy) yükseltirse geri düşürür; KWin SIGKILL/OOM ile ölürse oturumu kapatır
    uyari = ao.oncelik_bekcisi_baslat(d, cdir, izle=k.pid, xno=d.get("x_ana"))
    if uyari:
        d["uyarilar"].append(uyari)
    from . import ses  # oturuma özel ses sunucusu (ayar dinleme.ozel_ses; kurulamazsa yalnız uyarı)
    ses.ayara_gore_kur(d, cdir)
    _durum_yaz(d)
    _hazir_denetle(d, k)


# ---------------------------------------------------------------- durdur / temizlik

def _kapat_ic(d: dict, cdir_kesin: str | None = None) -> list[str]:
    """Kapat: önce kafesteki (ve ortam işaretli: kafesten kaçmış) uygulamalar, sonra çekirdek (KWin, bildirim,
    erişilebilirlik kayıt defteri, bekçiler, dbus) SIGTERM, kısa bekleme, kalan SIGKILL; X soket/kilitleri ve çalışma
    dizini temizlenir. Bayat/oynanmış kayda karşı (ilgisiz süreç öldürülmesin, ilgisiz dizin silinmesin): bir PID'e
    yalnız başlangıç zamanı kayıttakiyle aynıysa (ve kafes varsa kafesteyse) sinyal gider; kafes yalnız
    `deskhand-kwin-<kimlik>-N.scope` biçimindeyse boşaltılır; silinen dizin kayıttaki yol DEĞİL,
    RUNTIME_DIR/kwin-<kimlik> (ya da kalıntı taramasının bulduğu dizin: cdir_kesin)."""
    notlar = []
    kimlik = str(d.get("kimlik") or "")
    kimlik_ok = bool(KIMLIK_RX.fullmatch(kimlik))
    pid = {k: int(v) for k, v in (d.get("pid") or {}).items() if isinstance(v, int) and v > 0}
    bas = d.get("pid_bas") or {}
    kafes = str(d.get("kafes") or "")
    cg = str(d.get("cgroup") or "")
    if not (kimlik_ok and kafes and re.fullmatch(rf"deskhand-kwin-{kimlik}-\d+\.scope", kafes) and cg.endswith("/" + kafes)):
        cg = ""
    haric = ao._atalar()
    sira = ("kwin", "ses_pulse", "ses_wp", "ses_pw", "ses_bekcisi", "bildirim", "a11y", "oncelik_bekcisi", "dbus")
    cekirdek = [p for ad in sira if (p := pid.get(ad)) and ao.pid_dogru(p, bas.get(ad), cg)]

    def surecler() -> list[int]:
        isaretli = ao._isaretli_surecler(d) if kimlik_ok else []
        return sorted({p for p in ao._kafes_surecleri(cg) + isaretli if p not in haric})

    uygulamalar = [p for p in surecler() if p not in cekirdek]
    if uygulamalar:
        ao._sinyal(uygulamalar, signal.SIGTERM)
        _bekle(lambda: not any(ao._canli(p) for p in uygulamalar), 3, 0.05)
    # KWin temiz kapansın (XWayland'i kapatır, kendi dosyalarını yazar), sonra diğerleri
    for p in cekirdek:
        if ao._canli(p):
            ao._sinyal([p], signal.SIGTERM)
            if p == pid.get("kwin"):
                _bekle(lambda p=p: not ao._canli(p), 4, 0.05)
    _bekle(lambda: not any(ao._canli(p) for p in cekirdek + surecler()), 3, 0.05)
    kalan = [p for p in set(cekirdek + surecler()) if ao._canli(p)]
    if kalan:
        ao._sinyal(kalan, signal.SIGKILL)
        _bekle(lambda: not any(ao._canli(p) for p in kalan), 2, 0.05)
        notlar.append(_("{sayi} süreç SIGKILL ile kapatıldı").format(sayi=len(kalan)))
    canli = [p for p in set(cekirdek + surecler()) if ao._canli(p)]
    if canli:
        notlar.append(_("kapanmayan süreçler: {surecler}").format(surecler=canli))
    else:
        n = ao.ses_kaldir(d.get("ses"))  # eski kayıtlar
        if n:
            notlar.append(n)
    notlar += _x_temizle(d)
    kok = os.path.realpath(yollar.runtime_dir())
    cdir = cdir_kesin or (os.path.join(kok, OTURUM_ONEK + kimlik) if kimlik_ok else None)
    if cdir and os.path.isdir(cdir) and not os.path.islink(cdir) and os.path.dirname(os.path.realpath(cdir)) == kok \
            and os.path.basename(cdir).startswith(OTURUM_ONEK):
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
        pid = d.get("pid") if isinstance(d.get("pid"), dict) else {}
        if _kwin_mi(d) or (bas and ao._canli(bas) and not pid.get("kwin") and bas != os.getpid()):
            continue  # canlı ya da başka bir süreç şu an başlatıyor
        if bas == os.getpid() and not pid.get("kwin") and time.time() - float(d.get("baslangic") or 0) < 60:
            continue
        # kayıttaki kimlik dizinin adından gelir (kayıt başka bir dizini/kimliği gösteremez)
        d = {**d, "kimlik": os.path.basename(cdir)[len(OTURUM_ONEK):]}
        _kapat_ic(d, cdir_kesin=cdir)
        yapilan.append(d.get("kimlik") or os.path.basename(cdir))
    return yapilan


# ---------------------------------------------------------------- uygulama başlatma

def uygulama_baglari(g: dict) -> list[tuple[str, bool]]:
    """Uygulamanın bwrap ad alanında görebileceği oturum yolları ((yol, salt_okunur)): kendi runtime dizini, özel veri
    yolu soketi, Wayland soketi, erişilebilirlik veri yolu, XWayland soketi + Xauthority (salt okunur). Başka hiçbir
    şey (oturum.json, kwin.log, ev/, BAŞKA uygulamaların oturum kopyaları) yok; uygulamanın kendi kopyası
    korumali_baslat'ta (politikanın kararından, kopya=) eklenir."""
    c = g["calisma"]
    # a11y dizini SALT OKUNUR + FAIL-CLOSED (yok/başka dizin/sembolik bağ → Dur 14, uygulama başlatılmaz)
    b = [(ao.uygulama_runtime(c), False), (os.path.join(c, "bus"), False), (g["wayland_yol"], False),
         ao.a11y_bagi(os.path.join(c, "at-spi"), ao.a11y_kimlik_temizle(g))]
    if g.get("x_ana") is not None:
        b += [(f"{X_DIZIN}/X{g['x_ana']}", False), (g["xauth"], True)]
    return b + ao.ses_bagi(c)  # oturum kopyası: yalnız politikanın verdiği (arka_ortak.korumali_baslat, kopya=)


def uygulama_baslat(d: dict, argv: list[str], env: dict | None = None, kopya: str | None = None,
                    **popen) -> subprocess.Popen:
    """Uygulamayı bu oturumda başlat: kapı (baglanti_denetle), bwrap ad alanı (arka_ortak.korumali_argv; yalnız
    uygulama_baglari + kopya), bellek kafesi; ortam uygulama_ortami(güvenli kayıt, env)."""
    if not argv or not (shutil.which(argv[0]) or os.path.isfile(argv[0])):
        raise Dur(ARAC_EKSIK, _("başlatılamadı: {komut} bulunamadı").format(komut=argv[0] if argv else _("(boş komut)")))
    g = baglanti_denetle(d)
    popen.setdefault("stdin", subprocess.DEVNULL)
    log = None
    if "stdout" not in popen or "stderr" not in popen:
        log = _gunluk(g["calisma"], "uygulamalar")
        popen.setdefault("stdout", log)
        popen.setdefault("stderr", log)
    try:
        return ao.korumali_baslat(g, list(argv), uygulama_ortami(g, env), uygulama_baglari(g), kopya=kopya, **popen)
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


def pencereler(d: dict) -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """[(kdotool kimliği, başlık, (x, y, g, y))] — kdotool özel veri yolunda. Ham kdotool çağrısı YALNIZ arka_uc/
    içindedir (docs/ARCHITECTURE.md §4): arka_uc/kwin.oturum_pencereleri."""
    from .arka_uc.kwin import oturum_pencereleri
    return oturum_pencereleri(d)


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
    pid = (d["pid"] or {}).get("a11y")
    if not (pid and ao._canli(pid)):
        kayit_exe = ao.arac(ATSPI_REGISTRYD, zorunlu=False)
        if not kayit_exe:
            return None
        with _gunluk(d["calisma"], "atspi") as log:
            p = ao.kafeste_baslat(d, [kayit_exe], kdotool_ortami(d), stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=log)
        ao.pid_kaydet(d, "a11y", p.pid)
        _durum_yaz(d)

        def a11y_kayit():  # kayıt defteri a11y veri yolunda: --address ile ona bağlan
            try:
                r = subprocess.run([ao.arac("busctl"), f"--address={adres}", "--no-pager", "status",
                                    "org.a11y.atspi.Registry"],
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
        d = guvenli_kayit(d)  # adres kayıttan değil oturum dizininden
        self._d = d
        self.basili_dugme: set[str] = set()  # gönderdiğimiz buttondown/buttonup'tan: çökme kurtarması için
        self._log = _gunluk(d["calisma"], "eis")
        # ortam: asgari; veri yolu YALNIZ --bus argümanıyla (yardımcı ortamdan devralmaz). --dbus-pid: yardımcı
        # bağlandıktan sonra karşı tarafı (SO_PEERCRED) bu PID'e karşı doğrular (sert bağ ile gerçek veri yoluna değil)
        dpid = (d.get("pid") or {}).get("dbus")
        if not dpid:  # kayıtta dbus-daemon PID'i yoksa karşı taraf doğrulanamaz → bağlanma
            raise Dur(SANAL_KAPALI, _("KWin oturum kaydında dbus-daemon PID'i yok: girdi yardımcısı başlatılmadı"))
        ek = ["--dbus-pid", str(dpid)]
        self.p = subprocess.Popen([yol, "--bus", d["dbus_adres"], *ek], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
