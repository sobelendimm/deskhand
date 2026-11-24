"""Test yalıtımı: deskhand içe aktarılmadan ÖNCE tüm DESKHAND_*_DIR'leri geçici bir klasöre yönlendirir (gerçek ~/.config,
~/.local/state, ~/.cache, ~/.local/share yazılmaz), arayüz dilini Türkçeye sabitler (DESKHAND_DIL=tr) ve depo kökünü
sys.path'e ekler. Alt süreçler ortamı devralır.

GERÇEK EKRAN KİLİDİ: içe aktarılınca DESKHAND_GERCEK_EKRAN=kapali ayarlanır (deskhand/hata.py gercek_ekran_denetle):
hedef vermeyi unutan bir ölçüm/test çağrısı kullanıcının GERÇEK masaüstüne (dotool, kdotool eylemi, uygulama açma, pano,
bildirim, ekran görüntüsü) EN ALT katmanda ulaşamaz → Dur 17. Görünmez masaüstü ve sahte arka uçlar etkilenmez. Gerçek
aracı SAHTE bir ikili/subprocess ile değiştiren bir test (ör. sahte dotool) kilidi kendi başına açar:
os.environ["DESKHAND_GERCEK_EKRAN"] = "acik"  (yalnız o testin içinde, gerekçesiyle). tests/ekranli/ kilidi kaldırır.

Kullanım (her testin EN BAŞINDA):  import _yalitim  (ya da tests/ dışından: from tests import _yalitim)"""
import atexit
import os
import shutil
import sys
import tempfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GECICI = tempfile.mkdtemp(prefix="deskhand-test-")
DIZINLER = {ad: os.path.join(GECICI, ad.split("_")[1].lower())
            for ad in ("DESKHAND_CONFIG_DIR", "DESKHAND_STATE_DIR", "DESKHAND_CACHE_DIR", "DESKHAND_DATA_DIR", "DESKHAND_RUNTIME_DIR")}
os.environ.update(DIZINLER)
# Arka plan uygulamaları bwrap ad alanında (/tmp boş tmpfs): test pencerelerinin olay günlükleri (LOG) ve teste
# okunacak çıktıları YALNIZ bu dizine yazılır (arka_ortak.test_paylasimi ad alanına bağlar; dar: yalnız bu dizin).
PAYLASIM = os.path.join(GECICI, "paylasim")
os.mkdir(PAYLASIM, 0o700)
os.environ["DESKHAND_TEST_PAYLASIM"] = PAYLASIM
os.environ.pop("DESKHAND_HEDEF", None)
os.environ["DESKHAND_GERCEK_EKRAN"] = "kapali"  # alt süreçler devralır
# ajanın kendi istemcisi ipuçları (deskhand/kendi.py): testleri çalıştıran uçbirimin türü sonuçları değiştirmesin
for _ad in ("KONSOLE_DBUS_WINDOW", "WINDOWID", "TERM_PROGRAM", "GHOSTTY_RESOURCES_DIR", "KITTY_PID",
            "ALACRITTY_WINDOW_ID", "TMUX", "STY", "ZELLIJ"):
    os.environ.pop(_ad, None)
os.environ["DESKHAND_DIL"] = "tr"  # testler Türkçe metin bekler (kaynak dil); sistem dili ne olursa olsun
os.environ["PYTHONPATH"] = KOK + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
if KOK not in sys.path:
    sys.path.insert(0, KOK)

# ---------------------------------------------------------------- SÜREÇ SIZINTISI (0.9.1)
# Kök neden: görünmez masaüstü süreçleri (kwin_wayland --virtual, özel dbus-daemon, oncelik_bekcisi, bildirim_yakalayici,
# ayrık oto temizleyici) start_new_session ile AYRIK başlar; takımın sökümü (masaustu_durdur / atexit) yalnız süreç
# DÜZGÜN biterse çalışır. Takım zaman aşımında SIGKILL ile öldürülünce (tools/test_kos.py), çökünce ya da sökümü atlayan
# bir hata olunca bu süreçler GECICI altındaki dizinlerle birlikte sahipsiz kalıp çalışmayı sürdürüyordu. Önlem: (1) çıkışta
# GECICI'ye bağlı tüm süreçler süpürülür; (2) ayrık bir BEKÇİ süreç test sürecinin ölümünü bekler (SIGKILL dahil) ve
# aynı süpürmeyi yapıp GECICI'yi siler. Ölçüt DAR: komut satırında ya da ortamında bu takımın GECICI yolu geçen, aynı
# kullanıcının süreçleri (GECICI rastgele ve takıma özel: kullanıcının başka süreçlerine dokunulmaz).
_SUPUR_KOD = r'''
import os, signal, sys, time, shutil
def surecler(kok, haric):
    kb = kok.encode()
    uid = os.getuid()
    for ad in os.listdir("/proc"):
        if not ad.isdigit() or int(ad) in haric:
            continue
        try:
            if os.stat("/proc/" + ad).st_uid != uid:
                continue
            with open("/proc/%s/cmdline" % ad, "rb") as f:
                cmd = f.read()
            try:
                with open("/proc/%s/environ" % ad, "rb") as f:
                    env = f.read()
            except OSError:
                env = b""
        except OSError:
            continue
        if kb in cmd or kb in env:
            yield int(ad)
def supur(kok, haric):
    haric = set(haric) | {os.getpid()}
    hedef = list(surecler(kok, haric))
    for s in (signal.SIGTERM, signal.SIGKILL):
        for p in hedef:
            try:
                os.kill(p, s)
            except OSError:
                pass
        son = time.monotonic() + 3
        while time.monotonic() < son and any(os.path.exists("/proc/%d" % p) for p in hedef):
            time.sleep(0.05)
        hedef = [p for p in hedef if os.path.exists("/proc/%d" % p)]
        if not hedef:
            break
    return hedef
if __name__ == "__main__" and len(sys.argv) >= 4:
    ebeveyn, kok, sakla = int(sys.argv[1]), sys.argv[2], sys.argv[3] == "1"
    try:
        import select
        fd = os.pidfd_open(ebeveyn)
        select.select([fd], [], [])
    except OSError:
        while os.path.exists("/proc/%d" % ebeveyn):
            time.sleep(0.5)
    supur(kok, ())
    if not sakla:
        shutil.rmtree(kok, True)
'''


def _supur_modulu():
    ns = {"__name__": "_supur"}
    exec(compile(_SUPUR_KOD, "_supur", "exec"), ns)  # noqa: S102 - kendi sabit kodumuz (bekçiyle ortak)
    return ns


def gecici_surecleri() -> list[int]:
    """Bu takımın GECICI'sine bağlı (bu süreç, atalar ve bekçi hariç) yaşayan süreçler."""
    return list(_supur_modulu()["surecler"](GECICI, _haric()))


def _haric() -> set[int]:
    h = {os.getpid()}
    p = os.getppid()
    while p > 1:
        h.add(p)
        try:
            with open(f"/proc/{p}/stat") as f:
                p = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    if _BEKCI is not None:
        h.add(_BEKCI.pid)
    return h


def surecleri_supur() -> list[int]:
    """GECICI'ye bağlı süreçleri SIGTERM → SIGKILL ile kapat (bu süreç, atalar ve bekçi hariç). → kapanmayanlar."""
    return _supur_modulu()["supur"](GECICI, _haric())


def _bekci_baslat():
    import subprocess
    try:
        return subprocess.Popen([sys.executable, "-I", "-c", _SUPUR_KOD, str(os.getpid()), GECICI,
                                 "1" if os.environ.get("DESKHAND_TEST_SAKLA") == "1" else "0"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, cwd="/", close_fds=True)
    except OSError:
        return None


_BEKCI = _bekci_baslat()


def _cikis_supur():
    try:
        surecleri_supur()
    except Exception:  # noqa: BLE001 - çıkışta asla fırlatma (bekçi yine süpürür)
        pass


if os.environ.get("DESKHAND_TEST_SAKLA") != "1":
    atexit.register(shutil.rmtree, GECICI, True)
atexit.register(_cikis_supur)  # atexit ters sırada çalışır: önce süpürme, sonra dizin silme


# ---------------------------------------------------------------- gerçek masaüstü araçları için TUZAK ikililer
# Gerçek ekran kilidini dosya boyunca açan testler (test_girdi_merkezi, test_goruntu) için ikinci güvence: PATH'in başına
# kdotool / wl-copy / wl-paste / spectacle / busctl adlı "çalıştırılırsa işaret dosyasına yaz + 99 ile çık" sahteleri konur;
# test sonunda işaret dosyası YOKSA geçer (gerçek araç bir yerden sızmış olsaydı gerçek ekrana dokunurdu).
TUZAK_ARACLAR = ("kdotool", "wl-copy", "wl-paste", "spectacle", "busctl")
TUZAK_ISARET = os.path.join(GECICI, "tuzak-isareti.log")


def tuzak_araclari_kur(dizin, haric=()):
    """`dizin`e tuzak ikilileri yazar (var olan sahtelere dokunmaz) ve dizini PATH'in başına koyar."""
    os.makedirs(dizin, exist_ok=True)
    for ad in TUZAK_ARACLAR:
        yol = os.path.join(dizin, ad)
        if ad in haric or os.path.exists(yol):
            continue
        with open(yol, "w") as f:
            f.write(f'#!/bin/sh\necho "{ad} $*" >> "{TUZAK_ISARET}"\nexit 99\n')
        os.chmod(yol, 0o755)
    yollar = os.environ.get("PATH", "").split(os.pathsep)
    if not yollar or yollar[0] != dizin:
        os.environ["PATH"] = dizin + os.pathsep + os.environ.get("PATH", "")


def tuzak_cagrilari():
    """Tuzak ikililerinin çağrı satırları (boş liste = hiçbiri çalıştırılmadı)."""
    try:
        with open(TUZAK_ISARET) as f:
            return [s.rstrip("\n") for s in f if s.strip()]
    except OSError:
        return []
