"""AJANIN KENDİ İSTEMCİSİ (docs/ARCHITECTURE.md §4): Deskhand'i çalıştıran ajanın penceresi (ör. Claude Code'un izin
istemini gösteren uçbirim) hiçbir girdi almaz; yoksa ajan kendi izin istemini kendisi onaylayabilirdi.

Ata kümesi: bu süreçten /proc/<pid>/stat ppid ile 1'e kadar yürünür (claude → fish → ghostty → systemd …). Penceresinin
sahibi PID'i bu kümedeyse o pencereye her girdi 10. Uçbirim öykünücüleri çoğu zaman TEK süreçte birden çok pencere
tutar (Ghostty, Konsole): o sürecin TÜM pencereleri kapsanır (bilerek; hangi pencerenin bizimki olduğu bilinemez).

Çoklayıcılar: zincirde tmux varsa `$TMUX` soketiyle (salt okunur) `tmux list-clients -F '#{client_pid}'` → istemcilerin
ataları da kümeye eklenir (ajanın uçbirimi tmux istemcisinin öykünücüsüdür). Çözülemezse (screen, zellij, dtach, tmux
sorgusu başarısız) TÜM uçbirim sınıflı pencereler kapsanır. ssh üzerinden bağlanan uzak istemci kapsam dışıdır.

PID'i bilinmeyen pencereler (kde: kdotool pid veremedi): ortam ipuçları (KONSOLE_DBUS_WINDOW, WINDOWID, TERM_PROGRAM,
GHOSTTY_RESOURCES_DIR, KITTY_PID, ALACRITTY_WINDOW_ID) ve ata zincirindeki öykünücünün adı → o sınıftaki PID'siz
pencereler de kapsanır. Bu sınıf yedeği yalnız kullanıcının masaüstünde (kde) uygulanır: görünmez masaüstündeki
pencereler ajanın istemcisi olamaz (orada kural doğal olarak boşa çıkar).

Yalnız /proc OKUNUR; hiçbir sürece sinyal/girdi gönderilmez. Sonuç TAZELEME_SN boyunca önbellekte (MCP sunucusu uzun
yaşar: küme periyodik tazelenir)."""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time

TAZELEME_SN = 15.0
PROC = "/proc"  # testler sahte /proc ağacı verir

# Masaüstü oturumunun altyapı süreçleri: ata zincirinde bulunsalar da "ajanın istemcisi" sayılmazlar (yoksa ör. paneli
# başlatan plasmashell zincirdeyse tüm masaüstü kilitlenirdi). Uçbirimin kendisi bu listede DEĞİLDİR.
ALTYAPI = {"systemd", "init", "kwin_wayland", "kwin_x11", "kwin_wayland_wrapper", "plasmashell", "ksmserver",
           "startplasma-wayland", "startplasma-x11", "plasma_session", "sddm", "sddm-helper", "gdm", "gdm-session-wor",
           "gnome-shell", "gnome-session-b", "login", "sshd", "dbus-daemon", "dbus-broker", "dbus-broker-lau", "Xwayland",
           "kded6", "kded5", "krunner", "kwrapper5", "kwrapper6", "xdg-desktop-por", "kdeinit5", "kdeinit6", "lightdm",
           "agetty", "su", "sudo", "doas", "run0", "flatpak-session", "bwrap"}
# ata zincirinde bulununca "kendi öykünücümüz" sayılan süreç adları → pencere sınıfında aranacak sözcük
OYKUNUCU_AD = {"ghostty": "ghostty", "konsole": "konsole", "yakuake": "yakuake", "kitty": "kitty",
               "alacritty": "alacritty", "foot": "foot", "footclient": "foot", "wezterm-gui": "wezterm",
               "wezterm": "wezterm", "xterm": "xterm", "uxterm": "xterm", "gnome-terminal-": "gnome-terminal",
               "gnome-terminal": "gnome-terminal", "tilix": "tilix", "terminator": "terminator", "ptyxis": "ptyxis",
               "ptyxis-agent": "ptyxis", "kgx": "kgx", "xfce4-terminal": "xfce4-terminal", "lxterminal": "lxterminal",
               "qterminal": "qterminal", "mate-terminal": "mate-terminal", "urxvt": "urxvt", "rxvt": "rxvt",
               "guake": "guake", "tilda": "tilda", "terminology": "terminology", "sakura": "sakura",
               "cool-retro-term": "cool-retro-term", "contour": "contour", "rio": "rio", "st": "st-256color",
               "code": "code", "codium": "codium", "electron": "electron"}
COKLAYICI = {"tmux", "tmux: server", "tmux: client", "screen", "SCREEN", "zellij", "dtach", "abduco"}
# ortam ipucu → pencere sınıfı sözcüğü (None = hangi öykünücü olduğu bilinmiyor: tüm uçbirim sınıfları)
ORTAM_IPUCU = {"KONSOLE_DBUS_WINDOW": "konsole", "GHOSTTY_RESOURCES_DIR": "ghostty", "KITTY_PID": "kitty",
               "ALACRITTY_WINDOW_ID": "alacritty", "WINDOWID": None}
TERM_PROGRAM_SINIF = {"ghostty": "ghostty", "wezterm": "wezterm", "vscode": "code", "kitty": "kitty",
                      "alacritty": "alacritty", "konsole": "konsole", "tmux": None, "screen": None, "zellij": None}


def _stat(pid, proc=None):
    """/proc/<pid>/stat → (ppid, pgrp, tpgid, comm, tty_nr) | None. comm parantezli ve boşluk içerebilir: son ')' ile
    bölünür. tty_nr 0 = denetim uçbirimi yok."""
    try:
        with open(f"{proc or PROC}/{int(pid)}/stat") as f:
            s = f.read()
        comm = s[s.index("(") + 1:s.rindex(")")]
        alan = s[s.rindex(")") + 2:].split()
        return int(alan[1]), int(alan[2]), int(alan[5]), comm, int(alan[4])
    except (OSError, ValueError, IndexError):
        return None


def surec_adi(pid, proc=None):
    """Sürecin adı: comm (15 karakterle kısalır) + exe'nin taban adı; okunamazsa ("", "")."""
    st = _stat(pid, proc)
    comm = st[3] if st else ""
    try:
        exe = os.path.basename(os.readlink(f"{proc or PROC}/{int(pid)}/exe"))
    except (OSError, ValueError):
        exe = ""
    return comm, exe


def atalar(pid=None, proc=None, sinir=64):
    """pid (varsayılan: bu süreç) ve ataları: [(pid, comm)] — kendisi dahil, 1'e (ya da okunamayana) dek."""
    pid = os.getpid() if pid is None else int(pid)
    zincir = []
    for _i in range(sinir):
        if pid <= 1:
            break
        st = _stat(pid, proc)
        if st is None:
            break
        zincir.append((pid, st[3]))
        pid = st[0]
    return zincir


def dis_pid(pid, proc=None):
    """PID ad alanındaysak (flatpak/bwrap) sürecin EN DIŞ PID'i (/proc/<pid>/status NSpid ilk alanı) | None."""
    try:
        with open(f"{proc or PROC}/{int(pid)}/status") as f:
            for satir in f:
                if satir.startswith("NSpid:"):
                    pidler = [int(x) for x in satir.split()[1:]]
                    return pidler[0] if len(pidler) > 1 else None
    except (OSError, ValueError):
        pass
    return None


def _tmux_istemcileri(ortam):
    """$TMUX soketiyle salt okunur istemci PID'leri → [pid] | None (çözülemedi)."""
    tmux = ortam.get("TMUX", "")
    soket = tmux.split(",", 1)[0] if tmux else ""
    if not soket:
        return None
    try:
        r = subprocess.run(["tmux", "-S", soket, "list-clients", "-F", "#{client_pid}"], capture_output=True,
                           text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return [int(x) for x in r.stdout.split() if x.strip()]
    except ValueError:
        return None


class Kume:
    """Ajanın kendi istemcisini tanıma bilgisi."""

    def __init__(self, pidler=(), siniflar=(), tum_ucbirim=False, ipucu_genel=False, zincir=(), neden="",
                 ad_alani=False):
        self.pidler = set(pidler)          # bu PID'lerin pencerelerine girdi yok
        self.siniflar = set(siniflar)      # PID'i bilinmeyen pencerelerde bu sınıf sözcükleri (kde)
        self.tum_ucbirim = tum_ucbirim     # çoklayıcı çözülemedi: TÜM uçbirim sınıflı pencereler (kde)
        self.ipucu_genel = ipucu_genel     # uçbirimde çalışıyoruz ama hangisi bilinmiyor (PID'siz uçbirim pencereleri)
        self.zincir = list(zincir)
        self.neden = neden
        self.ad_alani = ad_alani            # PID ad alanındayız (flatpak/bwrap): pencere PID'i eşleşmeyebilir


def hesapla(pid=None, proc=None, ortam=None, tmux_sorgu=None):
    """Ata kümesini hesapla (önbelleksiz). tmux_sorgu(ortam) → [istemci pid] | None (testler taklit eder)."""
    ortam = os.environ if ortam is None else ortam
    tmux_sorgu = tmux_sorgu or _tmux_istemcileri
    zincir = atalar(pid, proc)
    pidler, siniflar = set(), set()
    tum_ucbirim = False
    notlar = []

    ad_alani = os.path.exists("/.flatpak-info") or any(c in ("bwrap", "flatpak-session", "flatpak") for _p, c in zincir)

    def ekle(z):
        nonlocal ad_alani
        for p, comm in z:
            if comm in ALTYAPI:
                continue
            pidler.add(p)
            dis = dis_pid(p, proc)  # ad alanındaysa pencere yöneticisinin gördüğü dış PID
            if dis is not None:
                pidler.add(dis)
                ad_alani = True
            s = OYKUNUCU_AD.get(comm) or OYKUNUCU_AD.get(surec_adi(p, proc)[1])
            if s:
                siniflar.add(s)
    ekle(zincir)
    adlar = [c for _p, c in zincir]
    coklayici = [c for c in adlar if c in COKLAYICI or c.startswith("tmux")]
    if coklayici:
        if any(c.startswith("tmux") for c in coklayici):
            istemciler = tmux_sorgu(ortam)
            if istemciler is None:
                tum_ucbirim = True
                notlar.append("tmux istemcileri çözülemedi")
            for ip in istemciler or ():
                ekle(atalar(ip, proc))
        if any(not c.startswith("tmux") for c in coklayici):
            tum_ucbirim = True
            notlar.append("çoklayıcı çözülemez: " + ", ".join(sorted(set(coklayici))))
    ipucu_genel = False
    for ad, sinif in ORTAM_IPUCU.items():
        if ortam.get(ad):
            if sinif:
                siniflar.add(sinif)
            else:
                ipucu_genel = True
    tp = (ortam.get("TERM_PROGRAM") or "").lower()
    if tp:
        if tp in TERM_PROGRAM_SINIF and TERM_PROGRAM_SINIF[tp] is None:
            ipucu_genel = True
        else:
            siniflar.add(TERM_PROGRAM_SINIF.get(tp, tp))
    if ortam.get("KITTY_PID", "").isdigit():
        pidler.add(int(ortam["KITTY_PID"]))
    if ortam.get("TMUX") and not coklayici:  # zincir okunamadı ama tmux içindeyiz
        istemciler = tmux_sorgu(ortam)
        if istemciler is None:
            tum_ucbirim = True
        for ip in istemciler or ():
            ekle(atalar(ip, proc))
    if ortam.get("STY") or ortam.get("ZELLIJ"):  # screen / zellij oturumu
        tum_ucbirim = True
    return Kume(pidler, siniflar, tum_ucbirim, ipucu_genel, zincir, "; ".join(notlar), ad_alani)


_ONBELLEK = {"zaman": -1e9, "kume": None}
_KILIT = threading.Lock()


def kume(tazele=False):
    """Önbellekli ata kümesi (TAZELEME_SN'de bir yeniden hesaplanır)."""
    with _KILIT:
        if tazele or _ONBELLEK["kume"] is None or time.monotonic() - _ONBELLEK["zaman"] > TAZELEME_SN:
            _ONBELLEK["kume"] = hesapla()
            _ONBELLEK["zaman"] = time.monotonic()
        return _ONBELLEK["kume"]


def sifirla():
    with _KILIT:
        _ONBELLEK["kume"] = None


def _sinif_sozcugu(sinif, sozcuk):
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(sozcuk) + r"(?![a-z0-9])", sinif or "", re.I))


def kendi_mi(pid, sinif, arka_uc_ad, ucbirim_mi, k=None):
    """Pencere ajanın kendi istemcisi mi? → neden metni (çevrilmemiş anahtar: 'pid' | 'coklayici' | 'sinif') | None.
    pid: pencerenin sahibi (None/"" = bilinmiyor), ucbirim_mi(sinif) → bool."""
    K = kume()
    try:
        p = int(pid) if pid not in (None, "") else None
    except (TypeError, ValueError):
        p = None
    if p is not None and p in K.pidler:
        return ("pid", p)
    if arka_uc_ad != "kde":
        return None  # görünmez masaüstündeki pencereler ajanın istemcisi olamaz
    if K.tum_ucbirim and ucbirim_mi(sinif):
        return ("coklayici", K.neden)
    sinif_uyar = ucbirim_mi(sinif) and (K.ipucu_genel or any(_sinif_sozcugu(sinif, s) for s in K.siniflar))
    if sinif_uyar and (p is None or K.ad_alani):  # PID yok ya da ad alanı yüzünden eşleşmeyebilir: sınıf yedeği
        return ("sinif", sinif)
    return None


# ---------------------------------------------------------------- süreç tablosu (ön plan süreci)

def surec_tablosu(proc=None):
    """{pid: (ppid, pgrp, tpgid, comm)} — tüm süreçler (yalnız okuma)."""
    tablo = {}
    try:
        adlar = os.listdir(proc or PROC)
    except OSError:
        return tablo
    for ad in adlar:
        if ad.isdigit():
            st = _stat(ad, proc)
            if st:
                tablo[int(ad)] = st
    return tablo


KABUK_ADLARI = {"bash", "zsh", "fish", "sh", "dash", "ksh", "mksh", "tcsh", "csh", "nu", "xonsh", "elvish", "yash",
                "ion", "pwsh", "osh", "busybox", "ash"}


def _torunlar(pid, tablo):
    cocuklar = {}
    for p, st in tablo.items():
        cocuklar.setdefault(st[0], []).append(p)
    sonuc, yigin = [], list(cocuklar.get(pid, []))
    while yigin and len(sonuc) < 4096:
        p = yigin.pop()
        sonuc.append(p)
        yigin += cocuklar.get(p, [])
    return sonuc


def kabuk_torunlari(pid, proc=None, tablo=None):
    """Pencere süreci pid'in torunlarında DENETİM UÇBİRİMİ (tty) olan kabuklar → [pid]. Boş değilse pencere bir uçbirim
    barındırıyor (Dolphin F4 / Kate uçbirim paneli / VS Code uçbirimi: gömülü uçbirim). pid bilinmiyorsa None."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    tablo = surec_tablosu(proc) if tablo is None else tablo
    return [p for p in _torunlar(pid, tablo) if tablo[p][3] in KABUK_ADLARI and tablo[p][4] != 0]


def on_plan_surecleri(pid, proc=None):
    """Pencere süreci pid'in uçbirimlerinde ÖN PLANDAKİ süreçlerin adları → [comm] | None (pid bilinmiyor / kabuk yok).
    Torunlardaki uçbirimli kabukların (gömülü uçbirim dahil) tpgid'i; yoksa doğrudan çocuklar (eski davranış). Tek
    süreçte çok pencere (Ghostty): tüm kabukların ön planı döner."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    tablo = surec_tablosu(proc)
    kabuklar = [p for p in kabuk_torunlari(pid, tablo=tablo) or () if p in tablo]
    cocuklar = kabuklar or [p for p, st in tablo.items() if st[0] == pid]
    if not cocuklar:
        return None
    gruplar = {}
    for p, st in tablo.items():
        gruplar.setdefault(st[1], []).append(p)
    adlar = []
    for c in cocuklar:
        tpgid = tablo[c][2]
        if tpgid <= 0:
            adlar.append(tablo[c][3])  # denetim uçbirimi yok: çocuğun kendisi
            continue
        uyeler = gruplar.get(tpgid) or []
        lider = tpgid if tpgid in tablo else (uyeler[0] if uyeler else None)
        adlar.append(tablo[lider][3] if lider is not None else tablo[c][3])
    return adlar
