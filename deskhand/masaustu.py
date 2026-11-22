"""Görünmez ikinci masaüstü (arka plan) yaşam döngüsü: `deskhand masaustu baslat|durdur|durum`. TEK giriş noktası, iki
tür: koşullar uygunsa yalıtık KWin oturumu (kwin_oturum.py; ek güvenceler burada: kancalar, erişilebilirlik kayıt
defteri, bildirim yakalayıcı), değilse aşağıdaki Xvfb masaüstü (secilen_tur; test/tanılama: DESKHAND_ARKA_TUR).
durum() tek durum kaynağıdır (d["tur"]); _kapat_ic / uygulama_ortami / erisim türe göre dağıtır. Ortak yapı taşları
(kafes, ses, ortam tabanı, özel D-Bus, öncelik bekçisi) arka_ortak.py'dedir.

Xvfb türünün bileşenleri (hepsi TEK bellek kafesinde: systemd-run --user --scope -p MemoryMax=… + nice 10 + ionice idle):
  Xvfb :N          görünmez X ekranı (-nolisten tcp, -noreset, -auth: yalnız erişim anahtarını bilen bağlanır),
                   kök zemin düz gri (OCR ön işlemesi siyahta bozuluyor)
  openbox          küçük pencere yöneticisi (akıllı yerleşim, yeni pencere odak alır, menü yok); yoksa uyarıyla çalışır
  dbus-daemon      ÖZEL oturum veri yolu: arka plan uygulamaları kullanıcının oturumundaki tek-örnek uygulamalara
                   devredilmez; yalnız izin verilen servisler (erişilebilirlik) etkinleştirilebilir
  bildirim         org.freedesktop.Notifications yakalayıcı → STATE_DIR/bildirimler.jsonl (kullanıcıya düşmez)
  ses              `deskhand-sessiz` boş çıkış (null sink): arka plan sesi kullanıcının kulaklığına gitmez

  ses              YOK: arka plan uygulamaları kullanıcının ses sunucusuna erişmez (bwrap + ortam; sessiz çalışır)
  uygulamalar      bwrap ad alanında (arka_ortak.korumali_baslat): gerçek runtime dizini görünmez

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
# Ortak yapı taşları (kafes, ses, özel veri yolu, Xauthority): arka_ortak.py. Eski adlar burada da kalır (geriye uyum).
from .arka_ortak import (IZINLI_SERVISLER, KAPI, SILINECEK_ORTAM, SINK, VARSAYILAN_BELLEK,  # noqa: F401
                         VARSAYILAN_TAKAS, _atalar, _bekle, _bellek_siniri, _canli, _cgroup, _dbus_yapilandir,
                         _gunluk_dosyasi, _isaretli_surecler, _kafes_surecleri, _kafese_al, _komut_satiri,
                         _kullanici_bus_ortami, _oncelik, _ortam_oku, _pactl, _satir_bekle, _sink_modulu, _sinyal,
                         _takas_siniri, _xauth_yaz, kafeste_baslat, korumali_baslat, oncelik_bekcisi_baslat, ortam_tabani, pid_dogru,
                         pid_kaydet, runtime_denetle, ses_kaldir, ses_kur, soket_karsi_pid, soket_kimligi,
                         gercek_soket_kimlikleri, GUVENLI_PATH, python_yolu,
                         ses_ortami_uygula, uygulama_runtime)
from .arka_ortak import a11y_bagi, a11y_dizini_hazirla, a11y_kimlik_temizle, a11y_soket_denetle
from .arka_ortak import arac as _arac
from .hata import ARAC_EKSIK, SANAL_KAPALI, Dur
from .i18n import _, h_
from .komutlar import MASAUSTU, SECENEKLER, cevirici, secimler

TURLER = ("kwin", "xvfb")  # arka plan masaüstünün türü: yalıtık KWin oturumu (kwin_oturum.py) ya da Xvfb + openbox
ILK_EKRAN = 90
ZEMIN = 0x8C8C8C  # düz orta gri: siyah kök OCR ön işlemesini (yerel zemin kutupluluğu) bozuyordu
VARSAYILAN_BOYUT = "1920x1080x24"
# WAYLAND_DISPLAY SİLİNMEZ, var olmayan MUTLAK bir yola ayarlanır: değişken yoksa libwayland (ve flatpak'ın
# --socket=wayland bağlaması) varsayılan $XDG_RUNTIME_DIR/wayland-0'a bağlanır = kullanıcının GERÇEK compositor'ı
# (ölçüldü: sahte wayland-0 soketi bağlantı aldı). Mutlak yol hiç oluşturulmaz (çalışma klasörü 0700, sanal-N içinde).
WAYLAND_YOK = "wayland-yok"


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


# ---------------------------------------------------------------- erişim anahtarı (Xauthority)
# Xvfb -auth olmadan açılırsa aynı bilgisayardaki HER yerel istemci (ör. X11 izni olan Flatpak uygulaması) görünmez
# masaüstüne bağlanıp girişli tarayıcının görüntüsünü alabilir/girdi gönderebilirdi. Her masaüstü kendi rastgele
# MIT-MAGIC-COOKIE'siyle açılır; anahtar dosyası çalışma klasöründe (0700) 0600 durur. Uygulamalara XAUTHORITY ile
# verilir; kullanıcının kendi Xauthority dosyasına hiçbir şey yazılmaz.
XAUTH_DOSYA = "Xauthority"


def xauth_yolu(no: int) -> str:
    return os.path.join(_calisma(no), XAUTH_DOSYA)


def _xauth_cerez(no: int) -> bytes | None:
    """Masaüstünün anahtarı (dosya yoksa None: anahtarsız eski masaüstü ya da başka bir ekran)."""
    try:
        with open(xauth_yolu(no), "rb") as f:
            b = f.read()
    except OSError:
        return None
    try:  # ilk kaydın anahtar alanı
        i = 2
        for _alan in range(3):
            i += 2 + int.from_bytes(b[i:i + 2], "big")
        n = int.from_bytes(b[i:i + 2], "big")
        cerez = b[i + 2:i + 2 + n]
        return cerez if len(cerez) == n and n else None
    except (IndexError, ValueError):
        return None


def _xlib_anahtar_kur() -> None:
    """python-xlib bağlantıları (bu süreç) sanal masaüstünün anahtarını kullansın: Xlib'in kimlik arayıcısını
    yalnız Deskhand anahtarı olan ekran numaralarında devralan dar bir sarmalayıcı (ortam değişkeni değişmez;
    başka ekranlar eskisi gibi). Bir kez kurulur."""
    from Xlib.support import connect
    if getattr(connect.get_auth, "_deskhand", False):
        return
    asil = connect.get_auth

    def get_auth(sock, dname, protocol, host, dno):
        cerez = _xauth_cerez(int(dno)) if str(dno).isdigit() else None
        if cerez:
            return b"MIT-MAGIC-COOKIE-1", cerez
        return asil(sock, dname, protocol, host, dno)
    get_auth._deskhand = True
    connect.get_auth = get_auth


def x_ac(ekran):
    """Sanal ekrana python-xlib bağlantısı (doğrulanmış ad + erişim anahtarı)."""
    from Xlib import display
    _xlib_anahtar_kur()
    return display.Display(guvenli_ekran(ekran))


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


def tur(d: dict | None) -> str:
    """Durum kaydının türü: "kwin" | "xvfb" (eski kayıtlarda alan yok = xvfb)."""
    return "kwin" if (d or {}).get("tur") == "kwin" else "xvfb"


def uygulama_ortami(d: dict, env: dict | None = None, izinli: tuple = ()) -> dict:
    """Arka plan uygulamasının ortamı: os.environ + env (ek/değişen değişkenler), kullanıcının oturumuna ait
    değişkenler (arka_ortak.CIKARILACAK_ORTAM) birleştirmeden önce ve sonra silinir, üstüne masaüstü değerleri ZORLA
    yazılır (kullanıcının Wayland ekranına/oturum veri yoluna/sesine kaçamasın). KWin türünde kwin_oturum'unki."""
    if tur(d) == "kwin":
        from . import kwin_oturum
        return kwin_oturum.uygulama_ortami(d, env, izinli)
    e = ortam_tabani(env, izinli)
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
    if d.get("xauth"):  # erişim anahtarı (SILINECEK_ORTAM kullanıcının XAUTHORITY'sini zaten sildi)
        e["XAUTHORITY"] = d["xauth"]
    if d.get("kimlik"):  # durdururken kafes dışındaki/kafessiz süreçler de bulunabilsin (_isaretli_surecler)
        e["DESKHAND_SANAL_KIMLIK"] = d["kimlik"]
    ses_ortami_uygula(e, d.get("ses"), os.path.join(_calisma(d["no"]), "ses-yok"))
    e["XDG_RUNTIME_DIR"] = uygulama_runtime(d.get("calisma") or _calisma(d["no"]))  # masaüstünün kendi klasörü
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


def canli_mi(d: dict) -> bool:
    """Durum kaydındaki masaüstü yaşıyor mu: xvfb → Xvfb (PID + komut satırı + soket); kwin → KWin (PID + komut
    satırındaki özel soket adı + soket dosyası)."""
    if tur(d) == "kwin":
        from . import kwin_oturum
        return kwin_oturum.canli_mi(d)
    return _xvfb_mi(d) and os.path.exists(f"/tmp/.X11-unix/X{d.get('no')}")


def guvenli_kayit(d: dict) -> dict:
    """Kayıttan YALNIZ tür + numara/kimlik alınır; yollar/adresler masaüstünün çalışma dizininden KURULUR (kayıttaki
    `dbus_adres`, `calisma`, `xauth`… yok sayılır: `;` çoklu adres ya da başka yol hiçbir şeyi yönlendiremez).
    kwin → kwin_oturum.guvenli_kayit; xvfb → RUNTIME_DIR/sanal-<no> (0700, kullanıcının). Geçersizse Dur(14)."""
    if tur(d) == "kwin":
        from . import kwin_oturum
        return kwin_oturum.guvenli_kayit(d)
    import stat as _stat
    no = d.get("no")
    if not (isinstance(no, int) and ILK_EKRAN <= no < ILK_EKRAN + 200):
        raise Dur(SANAL_KAPALI, _("sanal masaüstü kaydı geçersiz (ekran no): {no}").format(no=repr(no)))
    kok = os.path.realpath(yollar.runtime_dir())
    runtime_denetle(kok)
    cdir = os.path.join(kok, f"sanal-{no}")
    try:
        st = os.lstat(cdir)
    except OSError:
        raise Dur(SANAL_KAPALI, _("sanal masaüstü dizini yok: {dizin}").format(dizin=cdir))
    if not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o700:
        raise Dur(SANAL_KAPALI, _("sanal masaüstü dizini güvensiz: {dizin}").format(dizin=cdir))
    g = dict(d)
    g.update(tur="xvfb", no=no, ekran=f":{no}", calisma=cdir, dbus_adres=f"unix:path={cdir}/bus",
             xauth=os.path.join(cdir, XAUTH_DOSYA))
    a11y = d.get("a11y_adres") or ""
    if a11y and not re.fullmatch(re.escape(f"unix:path={cdir}/run/at-spi/bus") + r"(_\d+)?(,guid=[0-9a-f]{32})?",
                                 a11y):
        g["a11y_adres"] = None
    g["a11y_dizin_kimlik"] = a11y_kimlik_temizle(d)
    kafes = d.get("kafes")
    if kafes and not re.fullmatch(rf"deskhand-sanal-{no}-\d+\.scope", str(kafes)):
        raise Dur(SANAL_KAPALI, _("sanal masaüstü kaydı geçersiz (kafes): {kafes}").format(kafes=repr(kafes)))
    if (d.get("cgroup") or "") and not (kafes and str(d["cgroup"]).endswith("/" + kafes)):
        g["cgroup"] = ""
    return g


def xvfb_karsi_denetle(g: dict) -> None:
    """Xvfb türünde bağlanmadan önce karşı taraf (sert bağ / yer değiştirmeye karşı): özel veri yolu soketinin SO_PEERCRED
    PID'i kayıttaki dbus-daemon (başlangıç zamanı aynı, komut satırında bu masaüstünün bus.conf'u), X soketininki
    kayıttaki Xvfb; soketler kullanıcının gerçek soketlerinin sert bağı değil. Değilse Dur(14)."""
    pid, bas = g.get("pid") or {}, g.get("pid_bas") or {}
    gercek = gercek_soket_kimlikleri()
    for yol, ad in ((os.path.join(g["calisma"], "bus"), "dbus"), (f"/tmp/.X11-unix/X{g['no']}", "xvfb")):
        if soket_kimligi(yol) in gercek:
            raise Dur(SANAL_KAPALI, _("masaüstü soketi kullanıcının gerçek soketinin sert bağı: {yol}").format(yol=yol))
        karsi = soket_karsi_pid(yol)
        if not karsi or karsi != pid.get(ad) or (bas.get(ad) and not pid_dogru(karsi, bas.get(ad))):
            raise Dur(SANAL_KAPALI, _("masaüstü soketinin karşı tarafı bu masaüstünün {ad} süreci değil ({karsi})").format(
                ad=ad, karsi=karsi))
    if f"--config-file={g['calisma']}/bus.conf" not in _komut_satiri(pid.get("dbus")):
        raise Dur(SANAL_KAPALI, _("özel veri yolu süreci bu masaüstünün yapılandırmasıyla çalışmıyor"))


def baglanti_denetle(d: dict) -> dict:
    """Türüne göre bağlantı kapısı → GÜVENLİ kayıt (yollar çalışma dizininden; karşı taraf doğrulanmış)."""
    if tur(d) == "kwin":
        from . import kwin_oturum
        return kwin_oturum.baglanti_denetle(d)
    g = guvenli_kayit(d)
    xvfb_karsi_denetle(g)
    return g


def a11y_denetle(adres: str, d: dict | None = None) -> str:
    """Erişilebilirlik veri yolu soketine bağlanmadan önce karşı taraf denetimi (arka_ortak.a11y_soket_denetle): soket
    yalnız oturumun at-spi dizininde (kwin: <çalışma>/at-spi; xvfb: <çalışma>/run/at-spi). Dur(14) → bağlanılmaz."""
    d = d or durum(saglik=False)
    if d is None:
        raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
    g = guvenli_kayit(d)
    dizin = os.path.join(g["calisma"], "at-spi" if tur(g) == "kwin" else os.path.join("run", "at-spi"))
    return a11y_soket_denetle(adres, dizin, g.get("cgroup") or "", g.get("a11y_dizin_kimlik"))


def durum(dogrula: bool = True, saglik: bool = True) -> dict | None:
    """Çalışan arka plan masaüstünün durumu (TEK durum kaynağı; tür d["tur"]: kwin | xvfb); yoksa None. dogrula:
    ekran sunucusu canlı mı (canli_mi) ve kayıt geçerli mi (guvenli_kayit: yollar çalışma dizininden kurulur).
    saglik: bileşen ayrıntısı d["saglik"] içinde (girdi yolunda saglik=False: <1 ms)."""
    d = durum_oku()
    if d is None or not dogrula:
        if d is not None:
            d.setdefault("tur", "xvfb")
        return d
    d.setdefault("tur", "xvfb")
    try:
        d = guvenli_kayit(d)
    except Dur:
        return None
    if not canli_mi(d):
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


def _x_baglan(ekran: str):
    return x_ac(ekran)


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


def secilen_tur() -> tuple[str, bool, str]:
    """Açılacak arka plan masaüstünün türü → (tür, zorlandı mı, KWin olmama nedeni). TEK YOL: KWin oturumu
    kullanılabiliyorsa (kwin_oturum.kullanilabilir: KWin >= 6.8, render aygıtı, deskhand-eis + deskhand-goruntu,
    kdotool) kwin, değilse xvfb. Yalnız test ve tanılama için zorlanabilir: DESKHAND_ARKA_TUR=kwin|xvfb."""
    z = (os.environ.get("DESKHAND_ARKA_TUR") or "").strip().lower()
    if z in ("", "oto", "auto"):
        from . import kwin_oturum
        ok, neden = kwin_oturum.kullanilabilir()
        return ("kwin" if ok else "xvfb"), False, neden
    if z not in TURLER:
        raise Dur(1, _("DESKHAND_ARKA_TUR geçersiz: {deger} (kwin | xvfb)").format(deger=repr(z)))
    if z == "kwin":
        from . import kwin_oturum
        ok, neden = kwin_oturum.kullanilabilir()
        if not ok:
            raise Dur(ARAC_EKSIK, _("KWin arka plan oturumu zorlandı ama kullanılamıyor: {neden}").format(neden=neden))
    return z, True, ""


def masaustu_baslat(boyut: str | None = None, openbox: bool = True) -> dict:
    """Arka plan masaüstünü başlat (zaten açıksa durumunu döndürür): türü secilen_tur() belirler. KWin oturumu
    kendiliğinden seçilip AÇILAMAZSA Xvfb'ye düşülür (uyarıyla). Hata olursa başlatılan her şeyi kapatır.
    openbox: yalnız Xvfb türünde (KWin kendi pencere yöneticisidir)."""
    with _kilit():
        d = durum()
        if d is not None:
            d["zaten"] = True
            return d
        eski = durum_oku()
        if eski is not None:  # ölü masaüstünden kalanlar (çökme): temizle
            _kapat_ic(eski)
            try:
                os.remove(durum_yolu())
            except OSError:
                pass
        t, zorla, _neden = secilen_tur()
        if t == "kwin":
            try:
                d = _kwin_baslat(boyut)
            except Dur as e:
                if zorla:
                    raise
                from .gunluk import gunluk
                gunluk(f"masaustu | KWin oturumu açılamadı, Xvfb'ye düşüldü: {e.mesaj}")
                d = _xvfb_baslat(boyut, openbox)
                d["uyarilar"].insert(0, _("KWin oturumu açılamadı ({hata}); Xvfb kullanılıyor").format(hata=e.mesaj))
        else:
            d = _xvfb_baslat(boyut, openbox)
        _durum_yaz(d)
        return d


def _klavye_duzeni() -> tuple[str, str]:
    """KWin oturumunun klavye düzeni: kullanıcının etkin düzeni (ön planla aynı yazı davranışı), okunamazsa tr."""
    try:
        from .arka_uc.kde import klavye_duzeni
        duzen, varyant = klavye_duzeni()
        if re.fullmatch(r"[a-z]{2,8}", duzen or "") and re.fullmatch(r"[A-Za-z0-9_-]*", varyant or ""):
            return duzen, varyant or ""
    except Exception:  # noqa: BLE001 - düzen okunamadı: güvenli varsayılan
        pass
    return "tr", ""


def _kwin_baslat(boyut: str | None) -> dict:
    """Yalıtık KWin oturumu (kwin_oturum.baslat: kafes, sessiz ses + ses bekçisi, özel D-Bus, KWin, XWayland, hazır
    olma denetimi) + Xvfb yolundaki diğer güvenceler: özel veri yolu kancaları, oturumun KENDİ erişilebilirlik kayıt
    defteri (uygulamalardan ÖNCE), bildirim yakalayıcı. Hata olursa oturum kapatılır."""
    from . import kwin_oturum
    g, y, _derinlik = boyut_coz(boyut)
    d = kwin_oturum.baslat((g, y), xwayland=True, duzen=_klavye_duzeni())
    try:
        for kanca in list(OZEL_VERI_YOLU_KANCALARI):
            try:
                kanca(d["dbus_adres"], d)
            except Exception as e:  # noqa: BLE001
                d["uyarilar"].append(_("özel veri yolu kancası {kanca} başarısız: {hata}").format(
                    kanca=getattr(kanca, "__name__", kanca), hata=e))
        _erisim_hazirla_ic(d)
        _bildirim_baslat(d, d["calisma"])
    except BaseException:
        kwin_oturum.durdur(d)
        raise
    return d


def _xvfb_baslat(boyut: str | None, openbox: bool) -> dict:
    for arac in ("Xvfb", "dbus-daemon", "nice", "ionice", "sh"):
        if not _arac(arac, zorunlu=False):
            raise Dur(ARAC_EKSIK, _("{arac} yok (Xvfb: xorg-server-xvfb paketi)").format(arac=arac))
    g, y, derinlik = boyut_coz(boyut)
    bellek = _bellek_siniri()
    takas = _takas_siniri() if bellek else None
    if bellek and not _arac("systemd-run", zorunlu=False):
        raise Dur(ARAC_EKSIK, _("systemd-run yok: bellek kafesi kurulamaz (bilerek kapatmak için DESKHAND_SANAL_BELLEK=0)"))
    runtime_denetle(yollar.runtime_dir())
    no = bos_ekran()
    cdir = _calisma(no)
    os.makedirs(cdir, mode=0o700, exist_ok=True)
    os.chmod(cdir, 0o700)
    d = {"surum": 1, "tur": "xvfb", "no": no, "ekran": f":{no}", "boyut": [g, y, derinlik], "kafes": None, "cgroup": "",
         "bellek": bellek, "takas": takas, "pid": {}, "dbus_adres": "", "ses": None, "openbox": False,
         "baslangic": time.time(), "kimlik": secrets.token_hex(8), "calisma": cdir, "uyarilar": []}
    try:
        # a11y dizinini Deskhand kendisi yaratır, HİÇBİR uygulama başlamadan önce (erisim_hazirla başarısız olsa bile
        # uygulama <run>/at-spi'yi yaratıp sahte soket koyamasın); kimliği kayıtta, her denetimde karşılaştırılır
        d["a11y_dizin_kimlik"] = a11y_dizini_hazirla(os.path.join(uygulama_runtime(cdir), "at-spi"),
                                                      kalinti_sil=True)
        _baslat_ic(d, cdir, openbox)
    except BaseException:
        try:
            _kapat_ic(d)
        finally:
            shutil.rmtree(cdir, ignore_errors=True)
        raise
    return d


def _baslat_ic(d: dict, cdir: str, openbox: bool) -> None:
    no, (g, y, derinlik) = d["no"], d["boyut"]
    d["xauth"] = xauth_yolu(no)
    _xauth_yaz(d["xauth"], no, secrets.token_bytes(16))
    xvfb = [_arac("Xvfb"), d["ekran"], "-screen", "0", f"{g}x{y}x{derinlik}", "-nolisten", "tcp", "-noreset",
            "-dpi", "96", "-auth", d["xauth"]]
    ortam_x = {k: v for k, v in os.environ.items() if k not in SILINECEK_ORTAM}
    with _gunluk_dosyasi(cdir, "xvfb") as log:
        if d["bellek"]:
            kafes = f"deskhand-sanal-{no}-{os.getpid()}.scope"
            komut = [_arac("systemd-run"), "--user", "--scope", "--quiet", f"--unit={kafes}",
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
    pid_kaydet(d, "xvfb", p.pid)
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

    # kafesteki her şey düşük öncelikte kalsın (ad tabanlı kurallara karşı); Xvfb SIGKILL/OOM ile ölürse oturumu kapatır
    uyari = oncelik_bekcisi_baslat(d, cdir, izle=d["pid"].get("xvfb"), xno=d["no"])
    if uyari:
        d["uyarilar"].append(uyari)
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

    # ses: arka plan uygulamaları ses sunucusuna HİÇ erişmez (bwrap + ortam); boş çıkış / ses bekçisi yok
    d["ses"] = None

    # özel D-Bus
    conf, adres = _dbus_yapilandir(cdir)
    d["dbus_adres"] = adres
    with _gunluk_dosyasi(cdir, "dbus") as log:
        p = kafeste_baslat(d, [_arac("dbus-daemon"), f"--config-file={conf}", "--nofork", "--nopidfile",
                                "--nosyslog"], uygulama_ortami(d), stdin=subprocess.DEVNULL, stdout=log,
                            stderr=log)
    pid_kaydet(d, "dbus", p.pid)
    bus_soket = adres.split("=", 1)[1]
    if not _bekle(lambda: os.path.exists(bus_soket) or p.poll() is not None, 5) or p.poll() is not None:
        raise Dur(ARAC_EKSIK, _("özel D-Bus (dbus-daemon) açılmadı"))
    for kanca in list(OZEL_VERI_YOLU_KANCALARI):
        try:
            kanca(adres, d)
        except Exception as e:  # noqa: BLE001
            d["uyarilar"].append(_("özel veri yolu kancası {kanca} başarısız: {hata}").format(
                kanca=getattr(kanca, "__name__", kanca), hata=e))

    # erişilebilirlik: uygulamalar başlamadan ÖNCE açık olmalı (Qt/GTK açılışta org.a11y.Status IsEnabled'a bakar)
    _erisim_hazirla_ic(d)

    _bildirim_baslat(d, cdir)

    # pencere yöneticisi
    if openbox and _arac("openbox", zorunlu=False):
        rc = _openbox_yapilandir()
        ob_ortam = uygulama_ortami(d) | {"XDG_CACHE_HOME": os.path.join(cdir, "cache"),
                                         "XDG_CONFIG_HOME": os.path.join(cdir, "config")}
        with _gunluk_dosyasi(cdir, "openbox") as log:
            p = kafeste_baslat(d, [_arac("openbox"), "--config-file", rc, "--sm-disable"], ob_ortam,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        pid_kaydet(d, "openbox", p.pid)
        if _bekle(lambda: _wm_hazir(d["ekran"]) or p.poll() is not None, 5) and p.poll() is None:
            d["openbox"] = True
        else:
            d["uyarilar"].append(_("openbox başlamadı: pencereler 0,0'da üst üste açılır"))
    elif openbox:
        d["uyarilar"].append(_("openbox yok (sudo pacman -S openbox): pencereler 0,0'da üst üste açılır"))


def _bildirim_baslat(d: dict, cdir: str) -> None:
    """Bildirim yakalayıcı (özel veri yolunda org.freedesktop.Notifications; iki türde aynı): bildirimler kullanıcının
    ekranına düşmez, STATE_DIR/bildirimler.jsonl'a yazılır."""
    from . import bildirim_yakalayici
    os.makedirs(os.path.dirname(bildirim_yolu()), exist_ok=True)
    with _gunluk_dosyasi(cdir, "bildirim") as log:
        p = kafeste_baslat(d, [python_yolu(), "-I", bildirim_yakalayici.__file__, d["dbus_adres"], bildirim_yolu()],
                           uygulama_ortami(d), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log)
    pid_kaydet(d, "bildirim", p.pid)
    satir = _satir_bekle(p, 5)
    if satir != "hazir":
        d["uyarilar"].append(_("bildirim yakalayıcı hazır olmadı ({yanit}): bildirimler kaybolabilir").format(
            yanit=satir or _("yanıt yok")))
    if p.stdout:
        p.stdout.close()


def _busctl(adres: str, *a, timeout: float = 15) -> str:
    """busctl --address=ADRES …: çıktı (hata → boş). Yalnız verilen özel veri yoluna bağlanır."""
    try:
        r = subprocess.run([_arac("busctl"), f"--address={adres}", *a], capture_output=True, text=True, timeout=timeout,
                           env={"PATH": GUVENLI_PATH, "LANG": os.environ.get("LANG") or "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


A11Y_NESNE = ("org.a11y.Bus", "/org/a11y/bus")
A11Y_KAYIT = "org.a11y.atspi.Registry"


def erisim_adresi(adres: str) -> str:
    """Özel veri yolundaki erişilebilirlik veri yolunun adresi (org.a11y.Bus.GetAddress; at-spi-bus-launcher
    etkinleşir). Alınamazsa boş."""
    m = re.search(r'"([^"]+)"', _busctl(adres, "call", *A11Y_NESNE, "org.a11y.Bus", "GetAddress"))
    return m.group(1) if m else ""


def _erisim_hazirla_ic(d: dict) -> str:
    """Özel veri yolunda erişilebilirliği HAZIRLAR: IsEnabled=true (uygulamalar başlamadan önce; Qt/GTK açılışta
    org.a11y.Status'a bakar, kapalıyken ağaca girmez) ve erişilebilirlik veri yolunun kayıt defteri (at-spi2-registryd).
    Kayıt defterini veri yolunun kendisi etkinleştiremez: dbus-broker kullanan sistemlerde etkinleştirme kullanıcının
    systemd birimine gider (başkasının veri yoluna bağlı, 'unit failed') → kendimiz, bu masaüstünün kafesinde başlatırız.
    Yalnız bu masaüstüne dokunur. → erişilebilirlik veri yolu adresi ('' = hazırlanamadı; d["uyarilar"]'a yazılır).
    KWin türünde kwin_oturum.atspi_baslat (aynı adımlar, oturumun kendi veri yolunda)."""
    if tur(d) == "kwin":
        from . import kwin_oturum
        a11y = kwin_oturum.atspi_baslat(d) or ""
        if not a11y:
            d["uyarilar"].append(_("erişilebilirlik görünmez masaüstünde hazırlanamadı (at-spi2-core): `agac` / "
                                   "`ogeye-tikla` / `--eylem` arka planda çalışmaz"))
            return ""
        d["a11y_adres"] = a11y
        return a11y
    adres = d["dbus_adres"]
    nesne = (*A11Y_NESNE, "org.a11y.Status", "IsEnabled")
    if _busctl(adres, "get-property", *nesne) != "b true":
        _busctl(adres, "set-property", *nesne, "b", "true")
    a11y = erisim_adresi(adres)
    acik = _busctl(adres, "get-property", *nesne) == "b true"
    kayit_exe = _arac("/usr/lib/at-spi2-registryd", zorunlu=False) or "/yok/at-spi2-registryd"
    kayit = False
    if a11y and acik:
        sor = ("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s", A11Y_KAYIT)
        kayit = _busctl(a11y, *sor) == "b true"
        if not kayit and os.path.exists(kayit_exe):
            p = kafeste_baslat(d, [kayit_exe], uygulama_ortami(d, {"AT_SPI_BUS_ADDRESS": a11y},
                                                                 izinli=("AT_SPI_BUS_ADDRESS",)),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pid_kaydet(d, "a11y", p.pid)
            kayit = _bekle(lambda: _busctl(a11y, *sor) == "b true" or p.poll() is not None, 5, 0.1) \
                and _busctl(a11y, *sor) == "b true"
    if not (a11y and acik and kayit):
        d["uyarilar"].append(_("erişilebilirlik görünmez masaüstünde hazırlanamadı (at-spi2-core): `agac` / "
                               "`ogeye-tikla` / `--eylem` arka planda çalışmaz"))
        return ""
    d["a11y_adres"] = a11y
    return a11y


def erisim_hazirla() -> str:
    """Çalışan sanal masaüstünde erişilebilirlik hazır mı (IsEnabled + kayıt defteri); değilse hazırla (eski sürümle
    açılmış masaüstleri için). → erişilebilirlik veri yolu adresi; Dur(14) masaüstü kapalıysa; '' hazırlanamadıysa."""
    with _kilit():
        d = durum()
        if d is None:
            raise Dur(SANAL_KAPALI, _("sanal masaüstü kapalı (deskhand masaustu baslat)"))
        bas = (d.get("a11y_adres"), (d.get("pid") or {}).get("a11y"))
        d.pop("saglik", None)
        d["uyarilar"] = [u for u in d.get("uyarilar", []) if "erişilebilirlik" not in u]
        a11y = _erisim_hazirla_ic(d)
        if (d.get("a11y_adres"), (d.get("pid") or {}).get("a11y")) != bas:
            _durum_yaz(d)
        return a11y


def _kapat_ic(d: dict) -> list[str]:
    """PID ile kapat: önce kafesteki uygulamalar, sonra çekirdek (bildirim, openbox, dbus, Xvfb). Ses modülü
    EN SON: akışı hâlâ açık bir uygulama varken boş çıkış kaldırılırsa ses varsayılan çıkışa düşerdi. KWin türünde
    kwin_oturum._kapat_ic (aynı sıra; XWayland soket/kilit/Xauthority ve çalışma dizini temizliği dahil)."""
    if tur(d) == "kwin":
        from . import kwin_oturum
        return kwin_oturum._kapat_ic(d)
    notlar = []
    pid = {k: int(v) for k, v in (d.get("pid") or {}).items() if isinstance(v, int) and v > 0}
    bas = d.get("pid_bas") or {}
    no = d.get("no")
    no_ok = isinstance(no, int) and ILK_EKRAN <= no < ILK_EKRAN + 200
    kafes, cg = str(d.get("kafes") or ""), str(d.get("cgroup") or "")
    if not (no_ok and kafes and re.fullmatch(rf"deskhand-sanal-{no}-\d+\.scope", kafes) and cg.endswith("/" + kafes)):
        cg = ""  # beklenmeyen kafes yolu: içindekilere dokunma
    haric = _atalar()
    # bayat/oynanmış kayda karşı: PID'e yalnız başlangıç zamanı kayıttakiyle aynıysa (ve kafes varsa kafesteyse) sinyal
    cekirdek = [p for ad in ("bildirim", "ses_bekcisi", "oncelik_bekcisi", "openbox", "a11y", "dbus", "xvfb")
                if (p := pid.get(ad)) and pid_dogru(p, bas.get(ad), cg)]

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
    # silinen dizin kayıttaki yol DEĞİL: RUNTIME_DIR/sanal-<no>
    kok = os.path.realpath(yollar.runtime_dir())
    cdir = os.path.join(kok, f"sanal-{no}") if no_ok else None
    if cdir and os.path.isdir(cdir) and not os.path.islink(cdir):
        shutil.rmtree(cdir, ignore_errors=True)
    for yol in ((f"/tmp/.X{no}-lock",) if no_ok else ()):  # Xvfb SIGKILL ile öldüyse kilit kalır
        try:
            if not _xvfb_mi(d) and os.path.exists(yol):
                with open(yol) as f:
                    if int(f.read().strip() or 0) == pid.get("xvfb") and not _canli(pid.get("xvfb")):
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

def baslat(argv: list[str], env: dict | None = None, kopya: str | None = None, girdi: str | None = None,
           **popen) -> subprocess.Popen:
    """Uygulamayı arka plan masaüstünde başlat: ortam uygulama_ortami(d, env) (xvfb: DISPLAY + x11 arka uçları,
    WAYLAND_DISPLAY var olmayan yol; kwin: oturumun Wayland soketi + Wayland arka uçları, X11 isteyenler oturumun
    XWayland'ine), özel DBUS_SESSION_BUS_ADDRESS, sessiz ses çıkışı; süreç bellek kafesinin içinde (nice 10, ionice
    idle). env: os.environ'a eklenecek/değişecek değişkenler (masaüstü değerleri her zaman üstün). kopya: oturum
    politikasının bu uygulama için hazırladığı kopya (Hazirlik.kopya_yolu): ad alanına YALNIZ o bağlanır. girdi:
    onaylı kullanıcı girdisinin özel .desktop kopyası (salt okunur bağlanır; arka_ortak.girdi_kopyasi_bagi)."""
    d = baglanti_denetle(gerekli())  # kapı: yollar çalışma dizininden, karşı taraf doğrulanmış
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
    if tur(d) == "kwin" and d.get("xwayland"):  # Gecko (Firefox…) XWayland'den: yerel Wayland'de erişilebilirlik koordinatları mutlak değil
        from . import kwin_oturum
        env = {**kwin_oturum.gecko_ipuclari(argv), **(env or {})} or None
    try:
        return korumali_baslat(d, argv, uygulama_ortami(d, env), uygulama_baglari(d), kopya=kopya, girdi=girdi,
                               **popen)
    except FileNotFoundError as e:
        raise Dur(ARAC_EKSIK, _("başlatılamadı: {hata}").format(hata=e))
    finally:
        if log is not None:
            log.close()


def uygulama_baglari(g: dict) -> list[tuple[str, bool]]:
    """Uygulamanın bwrap ad alanında görebileceği masaüstü yolları (iki tür): kwin → kwin_oturum.uygulama_baglari;
    xvfb → kendi runtime dizini, özel veri yolu soketi, X soketi + Xauthority (salt okunur). Oturum kopyası
    korumali_baslat'ta eklenir (yalnız politikanın bu uygulamaya verdiği kopya)."""
    if tur(g) == "kwin":
        from . import kwin_oturum
        return kwin_oturum.uygulama_baglari(g)
    from .arka_ortak import uygulama_runtime
    c = g["calisma"]
    rt = uygulama_runtime(c)
    # <çalışma>/run/at-spi: yazılabilir runtime'ın ALTINDA salt okunur yeniden bağ (soket'e connect salt okunur bağda
    # çalışır; uygulama a11y soketinin yerine sembolik bağ/sahte soket koyamaz: denetim 6 sonrası ORTA-1). FAIL-CLOSED:
    # dizin yok/başka dizin/sembolik bağ ise Dur(14), uygulama başlatılmaz (yoksa uygulama <run>/at-spi'yi kendisi
    # yaratırdı)
    a11y = a11y_bagi(os.path.join(rt, "at-spi"), a11y_kimlik_temizle(g))
    return [(rt, False), a11y, (os.path.join(c, "bus"), False),
            (f"/tmp/.X11-unix/X{g['no']}", False), (os.path.join(c, XAUTH_DOSYA), True)]  # oturum kopyası: yalnız KENDİSİNİNKİ (korumali_baslat)


def _flatpak_run_mi(argv: list[str]) -> bool:
    return bool(argv) and os.path.basename(argv[0]) == "flatpak" and "run" in argv[1:3]


# ---------------------------------------------------------------- komut satırı

def _yazdir_durum(d: dict) -> None:
    g, y = d["boyut"][:2]
    s = d.get("saglik") or {}
    bilesen = " ".join(f"{ad}:{'✓' if ok else '✗'}" for ad, ok in s.items())
    ortak = dict(ekran=d["ekran"], genislik=g, yukseklik=y, kafes=d.get("kafes") or _("YOK"),
                 bellek=f"{d.get('bellek')}, swap {d.get('takas') or '-'}" if d.get("bellek") else _("sınırsız"),
                 ses=(d.get("ses") or {}).get("sink") or _("kapalı"))
    if tur(d) == "kwin":
        print(_("sanal masaüstü AÇIK (KWin {surum}): {ekran} {genislik}x{yukseklik} | kafes {kafes} (bellek {bellek}) | "
                "ses {ses} | XWayland {xwayland} | GPU {gpu}").format(
            surum=d.get("kwin_surum") or "?", xwayland=d.get("xwayland") or _("yok"),
            gpu=d.get("gpu") or "?", **ortak))
    else:
        print(_("sanal masaüstü AÇIK: {ekran} {genislik}x{yukseklik} | kafes {kafes} (bellek {bellek}) | ses {ses} | "
                "openbox {openbox}").format(openbox=_("var") if d.get("openbox") else _("yok"), **ortak))
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
