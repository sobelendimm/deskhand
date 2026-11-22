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
# HOME BİLEREK kullanıcınındır (uygulamalar kullanıcının dosyalarıyla çalışır; bkz. docs/ARCHITECTURE.md §4 "sınır").
# Asıl yalıtım ad alanıdır (korumali_argv): değişkenler yalnız ikinci hat.
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


def surec_baslangic(pid) -> str | None:
    """/proc/PID/stat'ın 22. alanı (süreç başlangıç zamanı): PID yeniden kullanımına karşı kimlik."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            s = f.read()
        return s[s.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def pid_dogru(pid, bas, cg: str = "") -> bool:
    """Kayıttaki PID hâlâ AYNI süreç mi: canlı, başlangıç zamanı kayıttakiyle aynı ve (kafes verildiyse) kafesin
    cgroup'unda. Bayat/oynanmış kayıt ilgisiz bir süreci öldürtemesin."""
    if not pid or not bas or not _canli(pid) or surec_baslangic(pid) != str(bas):
        return False
    return not cg or _cgroup(pid) == cg


def pid_kaydet(d: dict, ad: str, pid: int) -> None:
    """Bileşen PID'ini BAŞLANGIÇ ZAMANIYLA kaydet (d["pid"][ad], d["pid_bas"][ad]): kapatma/temizlik yalnız aynı
    sürece sinyal gönderir (pid_dogru)."""
    d.setdefault("pid", {})[ad] = pid
    d.setdefault("pid_bas", {})[ad] = surec_baslangic(pid)


ADRES_RX = re.compile(r"unix:path=([^,;]+)(,guid=[0-9a-f]{32})?")


def bus_yolu_kati(adres: str) -> str | None:
    """Veri yolu adresinin TEK soket yolu: yalnız `unix:path=/yol[,guid=<32 hex>]`. `;` (çoklu adres: sd-bus/libdbus
    ilki olmazsa sonrakine geçer), başka anahtar ya da biçim → None."""
    m = ADRES_RX.fullmatch(adres or "")
    return m.group(1) if m else None


def soket_karsi_pid(yol: str) -> int | None:
    """Unix soketine bağlan, karşı tarafın PID'ini (SO_PEERCRED) al, kapat. Bağlanılamazsa None."""
    import socket
    import struct
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(yol)
        pid, _uid, _gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return pid
    except OSError:
        return None
    finally:
        s.close()


def _a11y_dizin_denetle(dizin: str, kimlik=None) -> os.stat_result:
    """a11y dizini: gerçek dizin (sembolik bağ değil), kullanıcının, 0700; kimlik ([st_dev, st_ino], masaüstü
    açılışında kaydedilen) verilmişse AYNI dizin. Değilse Dur(14). → lstat sonucu."""
    import stat as _stat
    try:
        st = os.lstat(dizin)
    except OSError as e:
        raise Dur(14, _("erişilebilirlik dizini yok: {hata}").format(hata=e))
    if not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise Dur(14, _("erişilebilirlik dizini güvensiz (sembolik bağ / dizin değil / başkasının / gevşek izinli): "
                        "{dizin}").format(dizin=dizin))
    if kimlik is not None and [st.st_dev, st.st_ino] != [int(kimlik[0]), int(kimlik[1])]:
        raise Dur(14, _("erişilebilirlik dizini masaüstü açıldığından beri değişmiş (başka dizin): {dizin}").format(
            dizin=dizin))
    return st


def a11y_kimlik_temizle(d: dict) -> list[int] | None:
    """Kayıttaki a11y dizin kimliği: yalnız iki tamsayı ([st_dev, st_ino]); başka biçim yok sayılır (None)."""
    k = (d or {}).get("a11y_dizin_kimlik")
    if isinstance(k, (list, tuple)) and len(k) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in k):
        return [k[0], k[1]]
    return None


def a11y_dizini_hazirla(dizin: str, kalinti_sil: bool = False) -> list[int]:
    """Masaüstü açılışında, HİÇBİR uygulama başlamadan ÖNCE: a11y dizinini Deskhand kendisi 0700 olarak oluşturur
    (erişilebilirlik hazırlığı sonradan başarısız olsa bile): yazılabilir runtime'ın altında uygulama onu kendisi
    yaratıp soketin sahte kopyasını koyabilirdi (denetim ile bağlantı arası TOCTOU). Zaten varsa kabul edilmez
    (açılışta temiz oturum dizini; var olan = başkası koymuş). → [st_dev, st_ino] (kayıtta saklanır, her denetimde
    karşılaştırılır). kalinti_sil: çökmüş eski oturumdan kalan dizin/bağ silinip yeniden yaratılır (Xvfb: çalışma
    dizini ekran numarasına göre yeniden kullanılabilir)."""
    if kalinti_sil:
        import shutil
        if os.path.islink(dizin) or os.path.isfile(dizin):
            os.unlink(dizin)
        elif os.path.isdir(dizin):
            shutil.rmtree(dizin, ignore_errors=True)
    try:
        os.mkdir(dizin, 0o700)
    except FileExistsError:
        raise Dur(14, _("erişilebilirlik dizini zaten var (açılışta olmamalı): {dizin}").format(dizin=dizin))
    os.chmod(dizin, 0o700)  # umask'tan bağımsız
    st = _a11y_dizin_denetle(dizin)
    return [st.st_dev, st.st_ino]


def a11y_bagi(dizin: str, kimlik=None) -> tuple[str, bool]:
    """Korumalı başlatmada a11y dizininin SALT OKUNUR bağı (fail-closed: bağ kurulamıyorsa uygulama BAŞLATILMAZ,
    Dur 14). kimlik kayıtlıysa dizin yoksa/başka dizinse reddedilir; kimlik yoksa (eski sürümle açılmış masaüstü)
    dizin yoksa şimdi, uygulama başlamadan önce 0700 oluşturulur; dizin ZATEN varsa reddedilir (Dur 14: yeniden açın)."""
    if kimlik is None:
        if os.path.lexists(dizin):  # kimliksiz ama dizin ZATEN var: eski masaüstünde uygulama/başkası yaratmış olabilir
            raise Dur(14, _("erişilebilirlik dizini zaten var ama masaüstünün kaydında kimliği yok ({dizin}); arka plan "
                            "masaüstünü yeniden açın").format(dizin=dizin))
        a11y_dizini_hazirla(dizin)
    _a11y_dizin_denetle(dizin, kimlik)
    return dizin, True


def a11y_soket_denetle(adres: str, dizin: str, cgroup: str = "", kimlik=None) -> str:
    """Erişilebilirlik (at-spi) veri yolu soketi bağlanmadan önce (_karsi_denetle deseninin a11y'ye genişlemesi):
    adres TEK `unix:path=<dizin>/bus[_N][,guid=…]`; dizin gerçek dizin (sembolik bağ değil, kullanıcının); soket
    sembolik bağ DEĞİL, S_ISSOCK, kullanıcının; (st_dev, st_ino) kullanıcının gerçek soketlerinden biri değil
    (sert bağ); SO_PEERCRED PID'i Deskhand ile AYNI PID ad alanında (bwrap'teki uygulamanın kendi açtığı sahte soket
    değil) ve (kayıtlıysa) oturum kafesinin cgroup'unda. Değilse Dur(14). → soket yolu."""
    import stat as _stat
    yol = bus_yolu_kati(adres)
    if not yol or os.path.dirname(yol) != dizin or not re.fullmatch(r"bus(_\d+)?", os.path.basename(yol)):
        raise Dur(14, _("erişilebilirlik adresi oturumun at-spi dizini dışında ya da geçersiz: {adres}; "
                        "bağlanılmadı").format(adres=repr(adres)))
    try:
        sd, ss = os.lstat(dizin), os.lstat(yol)
    except OSError as e:
        raise Dur(14, _("erişilebilirlik soketi yok: {hata}").format(hata=e))
    if not _stat.S_ISDIR(sd.st_mode) or sd.st_uid != os.getuid():
        raise Dur(14, _("erişilebilirlik dizini güvensiz: {dizin}").format(dizin=dizin))
    if kimlik is not None:  # açılışta kaydedilen (st_dev, st_ino): dizin değiştirilmiş/yeniden yaratılmış olamaz
        _a11y_dizin_denetle(dizin, kimlik)
    if _stat.S_ISLNK(ss.st_mode) or not _stat.S_ISSOCK(ss.st_mode) or ss.st_uid != os.getuid():
        raise Dur(14, _("erişilebilirlik soketi güvensiz (sembolik bağ / soket değil / başkasının): {yol}; "
                        "bağlanılmadı").format(yol=yol))
    if (ss.st_dev, ss.st_ino) in gercek_soket_kimlikleri():
        raise Dur(14, _("erişilebilirlik soketi kullanıcının gerçek soketinin sert bağı: {yol}; "
                        "bağlanılmadı").format(yol=yol))
    karsi = soket_karsi_pid(yol)
    try:
        ayni_ad_alani = bool(karsi) and os.stat(f"/proc/{karsi}/ns/pid").st_ino == os.stat("/proc/self/ns/pid").st_ino
    except OSError:
        ayni_ad_alani = False
    if not karsi or not ayni_ad_alani or (cgroup and _cgroup(karsi) != cgroup):
        raise Dur(14, _("erişilebilirlik soketinin karşı tarafı bu oturumun süreci değil ({karsi}); "
                        "bağlanılmadı").format(karsi=karsi))
    return yol


def soket_kimligi(yol: str) -> tuple[int, int] | None:
    try:
        st = os.stat(yol)
        return st.st_dev, st.st_ino
    except OSError:
        return None


def gercek_soket_kimlikleri() -> set[tuple[int, int]]:
    """Kullanıcının gerçek runtime dizinindeki soketlerin (veri yolu, Wayland, ses, erişilebilirlik…) (st_dev, st_ino)
    kümesi: bir oturum soketi bunlardan birinin SERT BAĞI ise reddedilir."""
    import glob
    import stat as _stat
    rt = gercek_runtime()
    sonuc = set()
    for y in glob.glob(os.path.join(rt, "*")) + glob.glob(os.path.join(rt, "*", "*")):
        try:
            st = os.stat(y)
        except OSError:
            continue
        if _stat.S_ISSOCK(st.st_mode):
            sonuc.add((st.st_dev, st.st_ino))
    return sonuc


def runtime_durumu(yol: str) -> str | None:
    """RUNTIME_DIR'in güvenlik durumu (doktor ve runtime_denetle ortak): None = uygun (yok ya da kullanıcıya ait,
    sembolik bağ olmayan, 0700 dizin); değilse kullanıcıya gösterilecek neden."""
    try:
        st = os.lstat(yol)
    except FileNotFoundError:
        return None
    except OSError as e:
        return str(e)
    import stat as _stat
    if not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        return _("çalışma dizini güvensiz (sahibi/türü): {yol}").format(yol=yol)
    if st.st_mode & 0o077:
        return _("çalışma dizini gevşek izinli ({izin}; 0700 olmalı): {yol} — `chmod 700 {yol}` ile düzeltin").format(
            izin=oct(st.st_mode & 0o777), yol=yol)
    return None


def runtime_denetle(yol: str) -> None:
    """Deskhand'in RUNTIME_DIR'i (var olan dizin) kullanıcıya ait, sembolik bağ olmayan, 0700 dizin olmalı; değilse
    Dur 14. Gevşek izinli dizin sessizce sıkılaştırılmaz: arada başkası soket/dosya bırakmış olabilir (doktor gösterir)."""
    neden = runtime_durumu(yol)
    if neden:
        raise Dur(14, neden)


# ---------------------------------------------------------------- güvenli yardımcı ikililer

# Deskhand'in çalıştırdığı her yardımcı ikili (bwrap, nice, ionice, sh, systemd-run, busctl, dbus-daemon, Xvfb, KWin,
# kdotool, wl-copy…) PATH'ten DEĞİL yalnız bu dizinlerden, mutlak yolla bulunur ve dosya + bütün üst dizinleri root'a
# ait, grup/diğerleri yazamaz olmalı. Neden (denetim 12c, Y2): PATH'in başı kullanıcının yazılabilir ~/.local/bin'i;
# oraya bırakılan sahte `bwrap` sonraki bütün başlatmaları yalıtımsız yapıyordu.
GUVENLI_DIZINLER = ("/usr/bin", "/bin")
GUVENLI_PATH = ":".join(GUVENLI_DIZINLER)
_ARAC_ONBELLEK: dict[str, str] = {}


def guvenli_yol(yol: str) -> bool:
    """Mutlak yol güvenli bir çalıştırılabilir mi: yol BİLEŞEN BİLEŞEN çözülür; her bileşen (sembolik bağlar ve
    zincirdeki her ara bağ dahil) root'a ait, dizinler grup/diğerleri tarafından yazılamaz, son öğe root'a ait,
    başkası yazamaz, çalıştırılabilir normal dosya. Böylece zincirin hiçbir halkası root olmayan biri tarafından
    değiştirilemez."""
    import stat as _stat
    if not os.path.isabs(yol):
        return False
    kalan = [p for p in yol.split("/") if p]
    mevcut = "/"
    try:
        st = os.lstat("/")
    except OSError:
        return False
    if st.st_uid != 0 or st.st_mode & 0o022:
        return False
    bag_sayisi = 0
    while kalan:
        p = kalan.pop(0)
        if p == ".":
            continue
        if p == "..":
            mevcut = os.path.dirname(mevcut) or "/"
            continue
        aday = os.path.join(mevcut, p)
        try:
            st = os.lstat(aday)
        except OSError:
            return False
        if st.st_uid != 0:
            return False
        if _stat.S_ISLNK(st.st_mode):
            bag_sayisi += 1
            if bag_sayisi > 40:
                return False
            hedef = os.readlink(aday)
            if hedef.startswith("/"):
                mevcut = "/"
            kalan = [x for x in hedef.split("/") if x] + kalan
            continue
        if st.st_mode & 0o022:
            return False
        if _stat.S_ISDIR(st.st_mode):
            mevcut = aday
            continue
        return not kalan and _stat.S_ISREG(st.st_mode) and bool(st.st_mode & 0o111)
    return False


def arac(ad: str, zorunlu: bool = True) -> str | None:
    """Yardımcı ikilinin GÜVENLİ mutlak yolu (yalnız GUVENLI_DIZINLER; ad mutlak yolsa yalnız o). Bulunamazsa ya da
    güvenli değilse zorunlu → Dur(9), değilse None. Uygun yol süreç boyunca önbellekte (root dizinleri değişmez)."""
    if ad in _ARAC_ONBELLEK:
        return _ARAC_ONBELLEK[ad]
    adaylar = [ad] if os.path.isabs(ad) else [os.path.join(d, ad) for d in GUVENLI_DIZINLER] if "/" not in ad else []
    for a in adaylar:
        if not os.path.lexists(a):
            continue
        if guvenli_yol(a):
            _ARAC_ONBELLEK[ad] = a
            return a
        break  # var ama güvensiz: başka dizindeki kopyasına düşülmez
    if zorunlu:
        raise Dur(ARAC_EKSIK, _("güvenli araç bulunamadı: {ad} (yalnız /usr/bin ve /bin; dosya ve üst dizinleri root'a "
                                "ait, başkası yazamaz olmalı)").format(ad=ad))
    return None


def python_yolu() -> str:
    """Deskhand'in kendi yardımcı betiklerini (bekçiler, pano sahibi, bildirim yakalayıcı) çalıştıracak yorumlayıcı:
    çalışan yorumlayıcı güvenliyse o, değilse (ör. kullanıcının sanal ortamı) /usr/bin/python3."""
    import sys
    return sys.executable if sys.executable and guvenli_yol(sys.executable) else arac("python3")


# ---------------------------------------------------------------- uygulama ad alanı yalıtımı (bwrap)

def bwrap_var() -> bool:
    return arac("bwrap", zorunlu=False) is not None


_EV_ZORLA: str | None = None  # yalnız testler (süreç içi): sahte ev dizini; gerçek kullanıcı dosyalarına dokunmadan sınama


def gercek_ev() -> str:
    """Kullanıcının GERÇEK ev dizini (parola veritabanından; ortamdaki HOME değil)."""
    if _EV_ZORLA:
        return os.path.realpath(_EV_ZORLA)
    import pwd
    try:
        return os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return os.path.realpath(os.path.expanduser("~"))


VARSAYILAN_VERI = ("Desktop", "Downloads", "Templates", "Public", "Documents", "Music", "Pictures", "Videos")


def _nokta_yok(ev: str, yol: str) -> bool:
    """yol ev dizininin İÇİNDE (kendisi değil) ve göreli yolunun hiçbir bileşeni nokta ile başlamıyor."""
    if not yol.startswith(ev.rstrip("/") + "/"):
        return False
    return not any(p.startswith(".") for p in os.path.relpath(yol, ev).split("/"))


def veri_klasorleri(ev: str | None = None) -> list[str]:
    """Arka plan uygulamasının YAZABİLECEĞİ gerçek klasörler: kullanıcının XDG veri klasörleri (~/.config/user-dirs.dirs;
    dosya yoksa standart İngilizce adlar). Yalnız ev dizininin İÇİNDE, ev dizininin kendisi olmayan, yolunda nokta ile
    başlayan bileşen bulunmayan, var olan dizinler (gerçek yolları). Ev dizinini/gizli dizini gösteren girdi yok sayılır."""
    ev = ev or gercek_ev()
    adaylar: list[str] = []
    try:
        with open(os.path.join(ev, ".config", "user-dirs.dirs"), encoding="utf-8", errors="replace") as f:
            for satir in f:
                m = re.fullmatch(r'\s*XDG_[A-Z]+_DIR="(.*)"\s*', satir)
                if not m:
                    continue
                v = m.group(1)
                if v.startswith("$HOME"):
                    v = ev + v[len("$HOME"):]
                if os.path.isabs(v):
                    adaylar.append(v)
    except OSError:
        adaylar = [os.path.join(ev, a) for a in VARSAYILAN_VERI]
    sonuc = []
    for a in adaylar:
        g = os.path.realpath(a)
        if g not in sonuc and os.path.isdir(g) and _nokta_yok(ev, os.path.normpath(a)) and _nokta_yok(ev, g):
            sonuc.append(g)
    return sonuc


NOKTA_AZAMI = 3000      # bir veri klasöründe salt okunur örtülecek en çok gizli girdi (aşarsa klasör salt okunur)
NOKTA_DERINLIK = 6


def _bul(kok: str, *ifade: str, zaman: float = 10.0) -> list[tuple[str, str]] | None:
    """find (güvenli yol) → [(tür harfi, yol)]; çalışmazsa None. -xdev: başka dosya sistemine inmez."""
    try:
        r = subprocess.run([arac("find"), kok, "-xdev", *ifade], capture_output=True, timeout=zaman,
                           env={"PATH": GUVENLI_PATH, "LC_ALL": "C"}, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired, Dur):
        return None
    sonuc = []
    for p in r.stdout.split(b"\0"):
        if len(p) > 2 and p[1:2] == b" ":
            sonuc.append((chr(p[0]), os.fsdecode(p[2:])))
    return sonuc


def veri_nokta_girdileri(klasor: str) -> list[tuple[str, str]] | None:
    """Veri klasörünün İÇİNDEKİ gizli (nokta ile başlayan) dizin/dosyalar (en dıştakiler; içlerine inilmez) ve
    soket/FIFO'lar: [(tür, yol)] (tür: d dizin, f dosya, s soket, p FIFO; sembolik bağlar yok). Sayı NOKTA_AZAMI'yı
    aşar ya da tarama başarısızsa None (çağıran klasörü salt okunur bağlar)."""
    r = _bul(klasor, "-mindepth", "1", "-maxdepth", str(NOKTA_DERINLIK), "(", "-name", ".*", "(", "-type", "d", "-o",
             "-type", "f", ")", "-printf", r"%y %p\0", "-prune", ")", "-o", "(", "-type", "s", "-o", "-type", "p", ")",
             "-printf", r"%y %p\0")
    if r is None or len(r) > NOKTA_AZAMI:
        return None
    return r


# Ev dizininde her zaman maskelenen IPC uçları ve kimlik bilgileri: Steam komut borusu; ICE/X yetki dosyaları (ağ
# ad alanı paylaşıldığından ksmserver ICE ve X :0 SOYUT soketlerine erişilebilir — anahtarları görünmesin)
BILINEN_MASKELER = (".steam/steam.pipe", ".ICEauthority", ".Xauthority")


def ev_soketleri(ev: str | None = None) -> list[str]:
    """Ev dizininde (derinlik 4, gizli dizinler dahil) soket ve FIFO'lar + bilinenler (BILINEN_MASKELER): ad alanında
    /dev/null ile maskelenir (katman yazılabilir olsa da gerçek sokete/boruya bağlanılmasın, yetki anahtarı okunmasın)."""
    ev = ev or gercek_ev()
    bulunan = {y for _t, y in (_bul(ev, "-maxdepth", "4", "(", "-type", "s", "-o", "-type", "p", ")", "-printf",
                                     r"%y %p\0") or [])}
    for b in BILINEN_MASKELER:
        y = os.path.join(ev, b)
        if os.path.exists(y) and not os.path.islink(y):
            bulunan.add(y)
    return sorted(bulunan)


# Ad alanında OKUNAMAYAN sır yolları (ev dizinine göreli; glob olabilir): dizin → boş tmpfs (uygulama yazabilir,
# atılır), dosya → /dev/null. Uygulamanın kendi oturum kopyası bu örtünün ÜSTÜNE bağlanır (korumali_argv sırası).
# Yeni öge eklemek için listeye bir satır yeter.
SIR_YOLLARI = (
    ".ssh", ".gnupg", ".local/share/keyrings", ".local/share/kwalletd", ".password-store",
    ".config/mozilla", ".mozilla",                                     # gerçek Firefox profilleri (arka plan: kopya)
    ".config/chromium*", ".config/google-chrome*", ".config/vivaldi*", ".config/BraveSoftware*",  # * : profile-sync-daemon
    # disk kopyaları (<ad>-back-ovfs, <ad>-backup, -backup-crashrecovery-*) da örtülür: canlı profilin çerezleri orada
    ".config/microsoft-edge*",                                         # Chromium ailesi profil kökleri
    ".claude", ".claude.json", ".config/gh", ".git-credentials", ".netrc", ".aws", ".docker/config.json",
    ".config/rclone", ".kube",                                         # ajan / bulut / depo kimlik bilgileri
    ".config/deskhand", ".local/state/deskhand",                      # Deskhand'in kendi ayar ve günlüğü
    ".var/app",                                                        # Flatpak uygulama verileri (Electron: kopya)
    ".local/share/TelegramDesktop", ".config/discord*", ".config/Signal", ".config/Element*", ".config/Slack",
    ".config/WhatsApp*", ".config/teams*", ".config/Mattermost",      # mesajlaşma oturumları
    ".steam/steam/config", ".local/share/Steam/config", ".local/share/Steam/ssfn*", ".config/heroic",
    ".config/lutris",                                                  # oyun platformu hesap jetonları
    ".config/kdeconnect",                                              # KDE Connect eşleşme anahtarları
    ".config/qBittorrent", ".var/app/org.qbittorrent.qBittorrent",     # qBittorrent (WebUI parolası)
    ".config/syncthing", ".local/state/syncthing",                     # Syncthing aygıt anahtarı / API anahtarı
    ".config/obs-studio/basic/profiles",                               # OBS yayın anahtarı
    ".config/rustdesk",                                                # uzak masaüstü kimliği/parolası
    ".thunderbird", ".config/filezilla", ".config/remmina", ".local/share/remmina",  # e-posta / FTP / uzak bağlantı
    ".npmrc", ".pypirc", ".cargo/credentials", ".cargo/credentials.toml",  # paket deposu jetonları
    ".bash_history", ".zsh_history", ".local/share/fish/fish_history",  # kabuk geçmişi (komutlarda jeton olabilir)
)


def _sir_ham(ev: str) -> tuple[list[str], list[str]]:
    """SIR_YOLLARI'nın ev dizininde VAR olanları (glob açılmış) → (örtülecek yollar, ad alanında BOŞ hedefler).
    Sembolik bağsa (ör. profile-sync-daemon profili /run/user/UID/psd/…'ye taşır) HEDEFİ örtülür (bwrap bağ üstüne
    bağlayamaz). Hedef ad alanında zaten boş olan yerdeyse (/run/user/UID, /tmp) örtülecek gerçek bir şey yok, ama bağ
    boşta asılı kalırdı (Chromium: crashpad `--database is required`, çıkış 133): bu hedefler ikinci listede döner,
    ev_baglari oraya ad alanına ÖZEL boş dizin açar (gerçek psd verisi görünmez, yalıtım aynı)."""
    import glob
    gizli = (f"/run/user/{os.getuid()}", "/tmp")
    sonuc: list[str] = []
    bos: list[str] = []
    for d in SIR_YOLLARI:
        for y in sorted(glob.glob(os.path.join(glob.escape(ev), d))):
            if os.path.islink(y):
                y = os.path.realpath(y)
                if y in ("/", ev):
                    continue
                # hedef ad alanında zaten boş olan yerdeyse (psd tmpfs'i): hedef ŞU AN yoksa da (psd durmuş) bağ
                # boşta asılı kalmasın → ad alanına özel boş dizin (bkz. ev_baglari)
                if any(_ic_ice(y, g) for g in gizli) and not _ic_ice(y, ev):
                    if not any(y == g for g in gizli) and y not in bos:
                        bos.append(y)
                    continue
                if not os.path.exists(y):
                    continue
            elif not os.path.lexists(y) or not _ic_ice(y, ev) or y == ev:
                continue
            if y not in sonuc:
                sonuc.append(y)
    return sonuc, bos


def sir_yollari(ev: str | None = None) -> list[str]:
    """SIR_YOLLARI'nın örtülecek yolları (sıralı; bkz. _sir_ham). Zaten örtülen bir dizinin İÇİNDEKİ yol ayrıca
    bağlanmaz (ör. .var/app altındaki bir uygulama): üst örtü yeter."""
    sonuc = _sir_ham(ev or gercek_ev())[0]
    return [y for y in sonuc if not any(u != y and _ic_ice(y, u) for u in sonuc)]


def sir_bos_hedefler(ev: str | None = None) -> list[str]:
    """Sır yolu sembolik bağlarının, ad alanında boş /run/user/UID ya da /tmp altına giden HEDEFLERİ (gerçek yol; başka
    hedefin içindekiler elenir). Çıkarımı ev_baglari yapar: bwrap `--dir` ile ad alanına özel, boş, yazılabilir dizin."""
    bos = _sir_ham(ev or gercek_ev())[1]
    return sorted(y for y in bos if not any(u != y and _ic_ice(y, u) for u in bos))


_KATMAN: dict[str, bool] = {}


def katman_destekli(ev: str | None = None) -> bool:
    """bwrap ev dizininin üstüne geçici katman (overlayfs, kullanıcı ad alanında) kurabiliyor mu (süreç başına bir kez
    ölçülür, ~15 ms). Kurulamıyorsa korumali_argv ev dizinini salt okunur bağlar."""
    ev = ev or gercek_ev()
    if ev not in _KATMAN:
        try:
            r = subprocess.run([arac("bwrap"), "--unshare-user", "--ro-bind", "/", "/", "--overlay-src", ev,
                                "--tmp-overlay", ev, "--", arac("true")], capture_output=True, timeout=10,
                               env={"PATH": GUVENLI_PATH}, stdin=subprocess.DEVNULL)
            _KATMAN[ev] = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _KATMAN[ev] = False
    return _KATMAN[ev]


def _ic_ice(yol: str, ust: str) -> bool:
    return yol == ust or yol.startswith(ust.rstrip("/") + "/")


def ev_baglari(ev: str | None = None) -> tuple[list[str], dict]:
    """Ev dizini için bwrap argümanları → (argümanlar, bilgi). Ev dizini GEÇİCİ katmanla örtülür (gerçek dosyalar
    okunur, yazılanlar oturumla atılır: ~/.config/autostart, ~/.bashrc, ~/.local/bin… kalıcı olarak değiştirilemez);
    katman kurulamazsa ev dizini salt okunur + ~/.cache tmpfs. Yazılabilir GERÇEK bağlar yalnız veri klasörleri
    (veri_klasorleri); onların içindeki gizli dizin/dosyalar (.git, .vscode, .envrc…) salt okunur örtülür, soket/FIFO'lar
    /dev/null ile maskelenir; gizli girdisi çok olan klasör bütünüyle salt okunur. Ev dizinindeki soket/FIFO'lar da
    maskelenir."""
    ev = ev or gercek_ev()
    a: list[str] = []
    bilgi: dict = {"katman": katman_destekli(ev), "yazilabilir": [], "salt_okunur_klasor": [], "nokta": 0, "maske": 0,
                   "sir": []}
    if bilgi["katman"]:
        a += ["--overlay-src", ev, "--tmp-overlay", ev]
    else:
        a += ["--ro-bind", ev, ev]
        if os.path.isdir(os.path.join(ev, ".cache")):
            a += ["--tmpfs", os.path.join(ev, ".cache")]
    maske = set(ev_soketleri(ev))
    for k in veri_klasorleri(ev):
        girdiler = veri_nokta_girdileri(k)
        if girdiler is None:
            a += ["--ro-bind", k, k]
            bilgi["salt_okunur_klasor"].append(k)
            continue
        a += ["--bind", k, k]
        bilgi["yazilabilir"].append(k)
        for tur, y in girdiler:
            if tur in ("s", "p"):
                maske.add(y)
            elif tur in ("d", "f"):
                a += ["--ro-bind", y, y]
                bilgi["nokta"] += 1
    for y in sorted(maske):
        if _ic_ice(y, ev):
            a += ["--ro-bind", "/dev/null", y]
            bilgi["maske"] += 1
    for y in sir_yollari(ev):  # EN SON: veri klasörü bağlarının da üstüne (oturum kopyası bundan SONRA bağlanır)
        a += ["--tmpfs", y] if os.path.isdir(y) else ["--ro-bind", "/dev/null", y]
        bilgi["sir"].append(y)
    bilgi["bos_dizin"] = []
    for y in sir_bos_hedefler(ev):  # boşta asılı bağ olmasın (korumali_argv: /run/user/UID ve /tmp bu noktada boş tmpfs)
        # dosya olan hedef → /dev/null; dizin ya da (psd durmuşken) hiç olmayan hedef → boş dizin (yapılandırma kökü)
        a += ["--ro-bind", "/dev/null", y] if os.path.lexists(y) and not os.path.isdir(y) else ["--perms", "0700", "--dir", y]
        bilgi["bos_dizin"].append(y)
    return a, bilgi


def test_paylasimi() -> str | None:
    """YALNIZ test takımı (tests/_yalitim.py): DESKHAND_TEST_PAYLASIM ad alanına yazılabilir bağlanır — test pencerelerinin
    olay günlükleri ana makinedeki teste ulaşsın (ad alanında /tmp boş). Dar tutulur: yalnız geçici dizindeki
    `deskhand-test-*/paylasim` adlı, kullanıcıya ait, 0700, sembolik bağ olmayan dizin; başka her değer yok sayılır
    (ev dizini, soketler, başka yollar bu yolla açılamaz)."""
    y = os.environ.get("DESKHAND_TEST_PAYLASIM")
    if not y:
        return None
    import stat as _stat
    import tempfile
    g = os.path.realpath(y)
    ust = os.path.dirname(g)
    if os.path.basename(g) != "paylasim" or not os.path.basename(ust).startswith("deskhand-test-") or \
            os.path.dirname(ust) != os.path.realpath(tempfile.gettempdir()):
        return None
    try:
        st = os.lstat(y)
    except OSError:
        return None
    if not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o700:
        return None
    return g


# Uygulamanın ortamından YALNIZ son komuta (bwrap --setenv) giden değişkenler: yardımcı zincir (sh, nice, ionice,
# bwrap) bunlarla ÇALIŞMAZ (PATH araç çözümü, LD_* yükleyici)
SON_KOMUT_ORTAMI = ("PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT")


RUN_USER_BOYUT = 1 << 30   # ad alanındaki /run/user/UID tmpfs'inin boyut sınırı (1 GiB)
_SIZE: list[bool] = []


def bwrap_size_var() -> bool:
    """bwrap `--size` (tmpfs boyutu; bubblewrap >= 0.9) destekliyor mu (süreç başına bir kez ölçülür)."""
    if not _SIZE:
        try:
            r = subprocess.run([arac("bwrap"), "--help"], capture_output=True, timeout=10, text=True,
                               env={"PATH": GUVENLI_PATH}, stdin=subprocess.DEVNULL)
            _SIZE.append("--size" in (r.stdout + r.stderr))
        except (OSError, subprocess.TimeoutExpired):
            _SIZE.append(False)
    return _SIZE[0]


def korumali_argv(argv: list[str], runtime_kok: str, baglar: list[tuple[str, bool]], env: dict | None = None,
                  ev: str | None = None) -> list[str]:
    """Arka plan UYGULAMASININ komutu bwrap ad alanında (denetim 12c: Y1 aygıtlar, Y3 süreçler, HOME, Y4 IPC):
      - ayrı kullanıcı + PID ad alanı (`--unshare-user --unshare-pid`, kendi /proc): kullanıcının başka süreçleri
        görünmez, sinyal/ptrace gönderilemez;
      - kök dosya sistemi SALT OKUNUR (`--ro-bind / /`), /dev bwrap'in asgari /dev'i + yalnız /dev/dri (GPU): uinput,
        input/event*, snd, hidraw, usb, video düğümleri YOK;
      - /tmp, /run/user/UID ve (başka yerdeyse) Deskhand'in RUNTIME_DIR'i BOŞ tmpfs: kullanıcının Wayland/D-Bus/ses/
        kwallet/gnupg/ssh soketleri, /tmp'deki Steam/Chromium/ICE/Kulak Kesil soketleri görünmez;
      - ev dizini geçici katman (ev_baglari): okunur, yazılanlar atılır; yalnız veri klasörleri gerçek yazılır;
      - yalnız `baglar` (oturumun kendi soketleri/dizinleri; (yol, salt_okunur)) geri bağlanır;
      - env verilirse PATH/LD_* YALNIZ son komuta `--setenv` ile gider.
    --die-with-parent YOK (masaüstü CLI'den uzun yaşar); kafes ve PID temizliği aynen geçerli."""
    uid = os.getuid()
    ev = ev or gercek_ev()
    a = [arac("bwrap"), "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev"]
    if os.path.isdir("/dev/dri"):
        a += ["--dev-bind", "/dev/dri", "/dev/dri"]
    a += ["--proc", "/proc", "--tmpfs", "/tmp"]
    if bwrap_size_var():  # /run/user/UID'ye profil/önbellek yazan uygulama (sembolik bağ → --dir) belleği şişirmesin
        a += ["--size", str(RUN_USER_BOYUT)]
    a += ["--tmpfs", f"/run/user/{uid}"]
    a += ev_baglari(ev)[0]
    rk = os.path.realpath(runtime_kok)
    if not (_ic_ice(rk, f"/run/user/{uid}") or _ic_ice(rk, "/tmp")):
        a += ["--tmpfs", rk]
    a += ["--new-session"]
    paylasim = test_paylasimi()
    if paylasim:
        a += ["--bind", paylasim, paylasim]
    for yol, ro in baglar:
        if yol and os.path.exists(yol):
            a += ["--ro-bind" if ro else "--bind", yol, yol]
    for k in SON_KOMUT_ORTAMI:
        if env and env.get(k):
            a += ["--setenv", k, env[k]]
    a += ["--setenv", "DESKHAND_AD_ALANI", "1"]  # oturum/flatpak_ornek: ana makine kaydı yazılmaz (ad alanı)
    return [*a, "--", *argv]


def kopya_bagi(kopya: str | None, kok: str) -> list[tuple[str, bool]]:
    """Oturum politikasının bu uygulama için hazırladığı kopya (Hazirlik.kopya_yolu) → bağ. Yalnız kopya kökünün
    DOĞRUDAN alt dizini (sembolik bağ değil); başka yol Dur 14. Komut satırı/ortamdan kopya ÇIKARILMAZ: bir uygulama
    yalnız politikanın ona verdiği kopyayı görür."""
    if not kopya:
        return []
    k = os.path.realpath(kok)
    if os.path.islink(kopya) or not os.path.isdir(kopya) or os.path.dirname(os.path.realpath(kopya)) != k:
        raise Dur(14, _("oturum kopyası geçersiz (kopya kökünün alt dizini değil): {yol}").format(yol=kopya))
    return [(os.path.realpath(kopya), False)]


def girdi_kopyasi_bagi(yol: str | None) -> list[tuple[str, bool]]:
    """MCP open_app'in onaylı kullanıcı girdisi için yazdığı ÖZEL .desktop kopyası (uygulama._ozel_kopya: RUNTIME_DIR/
    uygulama/, 0600) → SALT OKUNUR bağ (ad alanında RUNTIME_DIR boş tmpfs: `gio launch KOPYA` onu görmeli). Yalnız o
    dizinin DOĞRUDAN çocuğu, kullanıcıya ait, sembolik bağ olmayan düz `.desktop` dosyası; başka yol Dur 14."""
    if not yol:
        return []
    import stat as _stat
    from . import yollar
    kok = os.path.realpath(os.path.join(yollar.runtime_dir(), "uygulama"))
    try:
        st = os.lstat(yol)
    except OSError:
        st = None
    if st is None or not _stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or not yol.endswith(".desktop") or \
            os.path.dirname(os.path.realpath(yol)) != kok:
        raise Dur(14, _("uygulama girdisi kopyası geçersiz: {yol}").format(yol=yol))
    return [(os.path.realpath(yol), True)]


def korumali_baslat(d: dict, argv: list[str], env: dict, baglar: list[tuple[str, bool]], kopya: str | None = None,
                    girdi: str | None = None, **popen) -> subprocess.Popen:
    """Arka plan UYGULAMASINI başlatmanın TEK yolu (iki tür): bwrap ad alanı (korumali_argv) + bellek kafesi + düşük
    öncelik. kopya: oturum politikasının hazırladığı kopya dizini (yalnız o bağlanır, kopya_bagi); girdi: onaylı
    girdinin özel .desktop kopyası (salt okunur, girdi_kopyasi_bagi). bwrap yoksa ya da
    güvenli yolda değilse Dur(9): yalıtımsız başlatma yok. Yardımcı zincir güvenli PATH ile çalışır; uygulamanın PATH'i
    yalnız son komuta gider."""
    if not bwrap_var():
        raise Dur(ARAC_EKSIK, _("bwrap (bubblewrap) yok: arka plan uygulaması yalıtılamaz, başlatılmadı"))
    from . import yollar
    from .oturum import politika
    baglar = [*baglar, *kopya_bagi(kopya, politika.kopya_dizini()), *girdi_kopyasi_bagi(girdi)]
    popen.setdefault("stdin", subprocess.DEVNULL)
    dis = {k: v for k, v in env.items() if k not in SON_KOMUT_ORTAMI}
    dis["PATH"] = GUVENLI_PATH
    return kafeste_baslat(d, korumali_argv(list(argv), yollar.runtime_dir(), baglar, env), dis, **popen)


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
    r = subprocess.run([arac("busctl"), "--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                        "org.freedesktop.systemd1.Manager", "AttachProcessesToUnit", "ssau", kafes, "/", "1",
                        str(pid)], capture_output=True, text=True, env=_kullanici_bus_ortami(), timeout=5)
    if r.returncode != 0:
        raise Dur(ARAC_EKSIK, _("süreç bellek kafesine alınamadı ({kafes}): {hata}").format(kafes=kafes, hata=r.stderr.strip()))


def _oncelik() -> list[str]:
    """nice MUTLAK 10 (nice -n göreli: çağıran -4'teyse 6 olurdu) + ionice idle."""
    fark = 10 - os.getpriority(os.PRIO_PROCESS, 0)
    return [*([arac("nice"), "-n", str(fark)] if fark > 0 else []), arac("ionice"), "-c", "3"]


def kafeste_baslat(d: dict, argv: list[str], env: dict, pass_fds=(), **popen) -> subprocess.Popen:
    """argv'yi nice 10 + ionice idle ile, kafese ALINDIKTAN SONRA çalıştır (kapı borusu). pass_fds: süreçte açık
    kalacak ek dosya tanıtıcıları (XWayland soketleri). Zincirin her ikilisi (sh, nice, ionice, argv[0]) güvenli mutlak
    yoldan (arac); argv[0] göreliyse yalnız güvenli dizinlerde aranır, PATH'e bakılmaz."""
    if not argv:
        raise Dur(1, _("başlatılacak komut boş"))
    argv = [argv[0] if os.path.isabs(argv[0]) else arac(argv[0]), *argv[1:]]
    tam = [*_oncelik(), *argv]
    kafes = d.get("kafes")
    if not kafes:  # kafes kapalı (DESKHAND_SANAL_BELLEK=0): yalnız öncelik
        return subprocess.Popen(tam, env=env, pass_fds=tuple(pass_fds), start_new_session=True, **popen)
    r, w = os.pipe()
    try:
        p = subprocess.Popen([arac("sh"), "-c", KAPI.format(fd=r), "deskhand-kapi", *tam], env=env,
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


def oncelik_bekcisi_baslat(d: dict, cdir: str, izle: int | None = None, xno: int | None = None) -> str | None:
    """Kafesin öncelik bekçisi (oncelik_bekcisi.py; iki türde de): kafesteki her iş parçacığını nice >= 10, gerçek
    zamanlı olmayan zamanlama ve idle G/Ç'de tutar (ad tabanlı sistem kuralları yükseltse bile). izle: ekran sunucusu
    PID'i — SIGKILL/OOM ile ölürse bekçi kafesi boşaltır, X soket/kilitlerini (xno) ve çalışma dizinini siler. Kafes
    yoksa başlatılmaz. → uyarı metni | None. PID d["pid"]["oncelik_bekcisi"]."""
    if not d.get("cgroup"):
        return _("bellek kafesi yok: öncelik bekçisi çalışmıyor (ad tabanlı sistem kuralları önceliği yükseltebilir)")
    import sys
    from . import oncelik_bekcisi
    ek = []
    if izle and surec_baslangic(izle):
        ek += ["--izle", str(izle), surec_baslangic(izle)]
    if xno is not None:
        ek += ["--x", str(int(xno))]
    ek += ["--dizin", cdir]
    with _gunluk_dosyasi(cdir, "oncelik-bekcisi") as log:
        p = kafeste_baslat(d, [python_yolu(), "-I", oncelik_bekcisi.__file__, d["cgroup"], *ek],
                           {"PATH": GUVENLI_PATH, "LANG": os.environ.get("LANG") or "C.UTF-8"},
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log)
    pid_kaydet(d, "oncelik_bekcisi", p.pid)
    satir = _satir_bekle(p, 5)
    if p.stdout:
        p.stdout.close()
    if satir != "hazir":
        return _("öncelik bekçisi hazır olmadı ({yanit})").format(yanit=satir or _("yanıt yok"))
    return None


# ---------------------------------------------------------------- ses (boş çıkış)

def _pactl(*a, timeout=5) -> subprocess.CompletedProcess | None:
    pactl = arac("pactl", zorunlu=False)
    if not pactl:
        return None
    try:
        return subprocess.run([pactl, *a], capture_output=True, text=True, timeout=timeout)
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
    if not arac("pactl", zorunlu=False):
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
    """(Eski kayıtlar için) Deskhand'in yüklediği boş çıkışı kaldır. Yalnız `deskhand-sessiz` adlı çıkışın modülü:
    oynanmış kayıt kullanıcının başka bir ses modülünü kaldırtamaz."""
    if not isinstance(ses, dict) or ses.get("modul") is None or ses.get("onceden") or not str(ses.get("sink") or "").startswith(SINK):
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
    if os.path.isdir(cdir) and not os.path.isdir(yol):  # üst dizinler YARATILMAZ (izinleri 0700 olmayabilirdi)
        os.mkdir(yol, 0o700)
    return yol


def ses_ortami_uygula(e: dict, ses: dict | None, yok_yolu: str) -> None:
    """Uygulama ortamının SES bölümü (iki tür için aynı). Uygulamalar kullanıcının ses sunucusuna (pipewire/pulse)
    HİÇ erişmez — çalma da kayıt (mikrofon) da yok: bwrap ad alanında gerçek runtime dizini görünmez. İki durum:
      - oturuma özel ses sunucusu hazırsa (ses.py; `<çalışma>/ses/pulse/native` kullanıcıya ait gerçek soket) ortam
        YALNIZ onun PULSE soketini gösterir: çıkış boş (deskhand-sessiz), mikrofon yok, modül yükleme kapalı, ses
        kullanıcının hoparlörüne gitmez; Deskhand aynı örneğin monitöründen dinler (listen aracı). PipeWire'ın kendi
        (tam yetkili) soketi VERİLMEZ: PIPEWIRE_REMOTE var olmayan yol (ad alanında `ses/` değil yalnız `ses/pulse/`);
      - değilse ortam var olmayan bir sokete yönlendirilir (uygulamalar sessiz çalışır).
    `ses` (durum kaydı) KULLANILMAZ: soket yolu çalışma dizininden kurulur ve varlığı gerçek dosya sisteminden denetlenir
    (oynanmış kayıt başka bir soketi gösteremez)."""
    from . import ses as _ses
    for k in [k for k in e if k.startswith(("PULSE_", "PIPEWIRE_"))]:
        del e[k]
    cdir = os.path.dirname(yok_yolu)
    if _ses.soket_hazir(cdir):
        e["PULSE_SERVER"] = f"unix:{_ses.pulse_soketi(cdir)}"
        e["PULSE_RUNTIME_PATH"] = _ses.pulse_dizini(cdir)
        e["PIPEWIRE_REMOTE"] = yok_yolu
        e["PIPEWIRE_RUNTIME_DIR"] = os.path.dirname(yok_yolu)
        return
    e["PULSE_SERVER"] = f"unix:{yok_yolu}"
    e["PIPEWIRE_REMOTE"] = yok_yolu
    e["PIPEWIRE_RUNTIME_DIR"] = os.path.dirname(yok_yolu)


def ses_bagi(cdir: str) -> list[tuple[str, bool]]:
    """Özel ses sunucusu hazırsa uygulamanın ad alanına bağlanacak TEK ses yolu: `<çalışma>/ses/pulse` (yalnız pulse
    soketi; SALT OKUNUR: connect salt okunur bağda çalışır, uygulama soketi değiştiremez). PipeWire soketleri,
    yapılandırma ve günlükler (`ses/`) bağlanmaz. Hazır değilse hiçbir şey."""
    from . import ses as _ses
    return [(_ses.pulse_dizini(cdir), True)] if _ses.soket_hazir(cdir) else []


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
