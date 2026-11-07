"""Ekran kartında OCR (EasyOCR, tr+en latin modeli): tesseract'ın okuyamadığı renkli web düğmeleri, soluk ve küçük
yazılar için OCR hattının bir parçası. Ekran kartı ve kurulum varsa KENDİLİĞİNDEN kullanılır; yoksa, kullanıcı
oyundaysa ya da tam ekrandaysa hat yalnız tesseract'la çalışır (kullanıcı seçimi değil, iç kural: oyunun VRAM'ine
ve kare hızına dokunulmaz).

Ölçüm (orta sınıf bir AMD ekran kartı, ROCm; 6 depo örneği + 6 sentetik web/tam ekran görüntüsü, 55 beklenen ifade):
  sentetik düğme/soluk/küçük: tesseract arama zinciri (5 okuma) 32/38, EasyOCR 38/38, birleşik 38/38;
  Türkçe harf birebir: tesseract 29/38, EasyOCR 27/38, BİRLEŞİK 36/38 (bu yüzden tesseract'ın yerini almaz,
  yanına eklenir). Sıcak istek ortanca 0,2 sn (tesseract tek okuma 0,3 sn), soğuk açılış ~2,5 sn, VRAM ~1,5 GB.

Süreçler:
  istemci (Deskhand, her komut ayrı süreç)  ──unix soketi──►  sunucu (model bir kez yüklenir)
                                                              └─ bekçi (sunucudan önce çatallanır, torch'suz)
  - Soket RUNTIME_DIR/ocr-gpu.sock, 0600; her bağlantıda SO_PEERCRED ile aynı kullanıcı denetlenir (iki yönde).
  - Boşta: ROCm'un olay iş parçacığı CUDA bağlamı açık her süreçte bir çekirdeği %100 döndürüyor (ölçüldü).
    Bu yüzden sunucu her istekten BOSTA_DUR_SN sonra kendini SIGSTOP ile dondurur (işlemci 0); istemci isteği
    gönderirken SIGCONT yollar (yanıt gelene kadar tekrarlar: dondurma ile bağlantı yarışına karşı).
  - Bekçi: BOSTA_KAPAN_SN (5 dk) istek yoksa ya da kullanıcı oyuna/tam ekrana geçtiyse sunucuyu kapatır (VRAM
    bırakılır). Sunucu ölürse bekçi de çıkar.
  - Başlatma: bellek kafesinde (gpu-is varsa o: kafes + çekirdek bağlama; yoksa systemd-run --scope MemoryMax).
  - Her hata (kurulum yok, sunucu çökmesi, zaman aşımı) sessizce None döner → tesseract.

Kurulum: README "Requirements"; sunucu yorumlayıcısı DATA_DIR/ocr-venv/bin/python (sistem torch'unu görür),
model DATA_DIR/easyocr (indirme: `python -m deskhand.ocr_gpu indir`). Sunucu tarafı yalnız stdlib + torch/easyocr
kullanır; istemci tarafı torch içe aktarmaz.
"""
from __future__ import annotations

import fcntl
import glob
import importlib.util
import json
import mmap
import select
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

SURUM = "1"  # model/ön işlem/protokol değişince OCR önbelleği geçersizleşsin
DILLER = ["tr", "en"]
MODELLER = ("craft_mlt_25k.pth", "latin_g2.pth")
BOSTA_DUR_SN = 1.5      # istekten sonra bu kadar boşsa sunucu kendini dondurur (işlemci 0)
BOSTA_KAPAN_SN = 300    # bu kadar istek yoksa kapanır (VRAM bırakılır)
BEKCI_SN = 2.0          # bekçi bu aralıkla oyun/boşta denetler
ISTEK_SN = 10.0         # tek istek için üst sınır (büyük görüntü sıcakta ~1,2 sn)
SOGUK_SN = 8.0          # sunucunun ilk açılışı (torch + model + ilk çekirdekler ~2,5 sn) için beklenecek en çok süre
EN_BUYUK = 4096 * 4096  # piksel
BELLEK = "4G"           # sunucu bellek kafesi (ölçüm: ~1,5 GB)
HATA_SN = 600           # sunucu açılamadıysa bu kadar süre yeniden denenmez (her okuma beklemesin)
_PAKET = os.path.dirname(os.path.abspath(__file__))
_KOK = os.path.dirname(_PAKET)


# ---------------------------------------------------------------- yollar / kurulum denetimi (istemci)

def _yollar():
    from . import yollar
    return yollar


def soket_yolu() -> str:
    return os.path.join(_yollar().runtime_dir(), "ocr-gpu.sock")


def kilit_yolu() -> str:
    return os.path.join(_yollar().runtime_dir(), "ocr-gpu.kilit")


def model_dizin() -> str:
    return os.path.join(_yollar().data_dir(), "easyocr")


def venv_dizin() -> str:
    return os.path.join(_yollar().data_dir(), "ocr-venv")


def hata_yolu() -> str:
    return os.path.join(_yollar().runtime_dir(), "ocr-gpu.hata")


def _hata_yaz(neden: str, yol: str | None = None):
    try:
        with open(yol or hata_yolu(), "w") as f:
            f.write(neden[:500])
    except OSError:
        pass


def gunluk_yolu() -> str:
    return os.path.join(_yollar().state_dir(), "ocr-gpu.log")


def python_yolu() -> str | None:
    """Sunucu yorumlayıcısı: Deskhand'in OCR venv'i, yoksa (easyocr sistemde kuruluysa) bu yorumlayıcı."""
    p = os.path.join(venv_dizin(), "bin", "python")
    if os.access(p, os.X_OK):
        return p
    if importlib.util.find_spec("easyocr") and importlib.util.find_spec("torch"):
        return sys.executable
    return None


def gpu_var() -> bool:
    """AMD (ROCm: /dev/kfd) ya da NVIDIA aygıtı."""
    return os.path.exists("/dev/kfd") or bool(glob.glob("/dev/nvidia[0-9]*"))


def eksikler() -> list[str]:
    """GPU OCR'ın neden kullanılamadığı (boş = kullanılabilir). install.sh ve testler için."""
    e = []
    if not gpu_var():
        e.append("gpu")
    if not python_yolu():
        e.append("python")
    if not all(os.path.isfile(os.path.join(model_dizin(), m)) for m in MODELLER):
        e.append("model")
    try:
        if time.time() - os.path.getmtime(hata_yolu()) < HATA_SN:
            e.append("hata")  # son açılış başarısız (ayrıntı: hata dosyası + günlük)
    except OSError:
        pass
    return e


def oyunda() -> bool:
    """Kullanıcı oyunda ya da tam ekranda mı (salt okuma KWin sorgusu, ~2-10 ms)? Sorgu çalışmazsa False."""
    try:
        from . import mesgul
        p = mesgul.etkin_pencere()
        return bool(mesgul.tam_ekran_mi(p) or mesgul.oyun_mu(p, []))
    except Exception:  # noqa: BLE001 — algı hatası OCR'ı bozmasın
        return False


# ---------------------------------------------------------------- protokol (iki taraf)

def _tam_oku(s, n):
    parca = []
    while n:
        b = s.recv(min(n, 1 << 20))
        if not b:
            raise ConnectionError("bağlantı kapandı")
        parca.append(b)
        n -= len(b)
    return b"".join(parca)


def ileti_yaz(s, baslik: dict, veri: bytes = b""):
    """[4 bayt uzunluk][JSON başlık][ham veri (başlıktaki 'n' bayt)]"""
    b = json.dumps({**baslik, "n": len(veri)}, ensure_ascii=False).encode()
    s.sendall(struct.pack(">I", len(b)) + b + veri)


def ileti_oku(s, en_cok=EN_BUYUK * 3) -> tuple[dict, bytes]:
    (n,) = struct.unpack(">I", _tam_oku(s, 4))
    if n > 1 << 20:
        raise ValueError("başlık çok büyük")
    baslik = json.loads(_tam_oku(s, n))
    m = int(baslik.get("n", 0))
    if not 0 <= m <= en_cok:
        raise ValueError("veri çok büyük")
    return baslik, _tam_oku(s, m) if m else b""


def _es_kullanici(s) -> int | None:
    """Karşı uç aynı kullanıcı mı? → karşı ucun PID'i ya da None."""
    pid, uid, _gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    return pid if uid == os.getuid() else None


def kelimelere(kutular) -> list[dict]:
    """Sunucunun kutuları [[x0, y0, x1, y1, metin, güven 0-1], …] → Deskhand kelime biçimi. Her kutu bir satır
    (anahtar 900+i: tesseract'ın blok numaralarıyla karışmaz); kutudaki kelimelere x payı harf sayısıyla bölünür."""
    out = []
    for i, (x0, y0, x1, y1, metin, guven) in enumerate(kutular):
        parca = str(metin).split()
        if not parca:
            continue
        toplam = sum(len(p) for p in parca) + len(parca) - 1
        bas = 0
        for p in parca:
            a = x0 + (x1 - x0) * bas / toplam
            b = x0 + (x1 - x0) * (bas + len(p)) / toplam
            out.append({"anahtar": (900 + i, 0, 0), "x": a, "y": float(y0), "g": b - a, "y2": float(y1), "x2": b,
                        "conf": round(float(guven) * 100, 1), "t": p})
            bas += len(p) + 1
    return out


def buyutme(w: int, h: int) -> float:
    """Küçük/orta görüntüde 2x (ölçüm: soluk/küçük yazıda birebir 24→27/38, bulunan 37→38), büyükte 1x."""
    return 2.0 if w * h <= 1_200_000 else 1.0


# ---------------------------------------------------------------- istemci

def _baglan(sure=0.5):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(sure)
    try:
        s.connect(soket_yolu())
        pid = _es_kullanici(s)
        if pid is None:
            raise PermissionError("soket başka kullanıcının")
        return s, pid
    except BaseException:
        s.close()
        raise


def calisiyor() -> bool:
    """Sunucu ayakta mı ya da açılıyor mu (kilit tutuluyor)?"""
    try:
        fd = os.open(kilit_yolu(), os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def _baslat_komutu(py: str) -> list[str]:
    """Bellek kafesi: gpu-is (yerel GPU iş sarmalayıcısı: kafes + çekirdek bağlama) > systemd-run --scope > düz."""
    kod = (f"import sys; sys.path.insert(0, {_KOK!r}); from deskhand import ocr_gpu; "
           f"ocr_gpu.sunucu({soket_yolu()!r}, {kilit_yolu()!r}, {model_dizin()!r}, {float(BOSTA_KAPAN_SN)!r})")
    temel = [py, "-s", "-c", kod]
    if shutil.which("gpu-is"):
        return ["gpu-is", "-m", BELLEK] + temel
    if shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "-q", "--nice=5", "-p", f"MemoryMax={BELLEK}",
                "-p", "MemorySwapMax=1G", "--"] + temel
    return temel


_son_baslatma = [0.0]


def baslat() -> bool:
    """Sunucuyu arka planda başlatır (beklemez). Kurulum yoksa, kullanıcı oyundaysa, zaten çalışıyorsa ya da bu süreç
    az önce başlattıysa (sunucu kilidi almadan ikinci kopya açılmasın) False."""
    if eksikler() or calisiyor() or time.monotonic() - _son_baslatma[0] < SOGUK_SN or oyunda():
        return False
    py = python_yolu()
    if not py:
        return False
    _son_baslatma[0] = time.monotonic()
    os.makedirs(os.path.dirname(soket_yolu()), mode=0o700, exist_ok=True)
    os.makedirs(os.path.dirname(gunluk_yolu()), exist_ok=True)
    ortam = dict(os.environ)
    ortam["MIOPEN_FIND_MODE"] = "FAST"  # yoksa MIOpen her yeni görüntü boyutunda dakikalarca çekirdek arar (ölçüldü)
    ortam.pop("PYTHONPATH", None)
    try:
        with open(gunluk_yolu(), "w") as gunluk:
            surec = subprocess.Popen(_baslat_komutu(py), stdin=subprocess.DEVNULL, stdout=gunluk, stderr=gunluk,
                                     env=ortam, start_new_session=True, close_fds=True)
        # uzun yaşayan istemcide (MCP sunucusu, panel) kapanan sunucu zombi kalmasın
        threading.Thread(target=surec.wait, daemon=True).start()
        return True
    except OSError:
        return False


def _uyandirici(pid: int):
    """Yanıt gelene kadar her 0,25 sn SIGCONT: sunucu donmuşsa (ya da tam o an kendini donduruyorsa) uyanır.
    Göndermeden ÖNCE başlamalı: donmuş sunucu okumadığı için büyük görüntünün gönderimi tıkanır (ölçüldü)."""
    dur = threading.Event()

    def dongu():
        while not dur.is_set():
            try:
                os.kill(pid, signal.SIGCONT)
            except OSError:
                return
            dur.wait(0.25)
    threading.Thread(target=dongu, daemon=True).start()
    return dur


def oku(im, bekle: float = 0.0):
    """PIL görüntüsü → kelime listesi (Deskhand biçimi) ya da None (kullanılamıyor / oyunda / hata → tesseract).
    Sunucu ayakta değilse başlatılır; bekle > 0 ise açılması o kadar beklenir, değilse hemen None."""
    if eksikler():
        return None
    if oyunda():
        kapat()
        return None
    bitis = time.monotonic() + max(0.0, bekle)
    while True:
        try:
            s, pid = _baglan()
            break
        except (OSError, PermissionError):
            if not calisiyor():
                if _son_baslatma[0] and 3.0 < time.monotonic() - _son_baslatma[0] < 4 * SOGUK_SN:
                    # bu süreç az önce başlattı, sunucu açılırken öldü (ör. bellek kafesi): bir süre yeniden deneme
                    # (çok sonra kapanmışsa boşta kapanmadır: yeniden başlatılır)
                    _hata_yaz("sunucu hazır olmadan kapandı (günlük: ocr-gpu.log)")
                    return None
                baslat()
            if time.monotonic() >= bitis:
                return None
            time.sleep(0.1)
    dur = _uyandirici(pid)
    try:
        im = im.convert("RGB")
        s.settimeout(ISTEK_SN)
        ileti_yaz(s, {"komut": "oku", "w": im.width, "h": im.height, "mag": buyutme(im.width, im.height)}, im.tobytes())
        baslik, _veri = ileti_oku(s)
        if "hata" in baslik:
            return None
        return kelimelere(baslik.get("kutular", []))
    except (OSError, ValueError, ConnectionError):
        return None
    finally:
        dur.set()
        s.close()


def pid_yolu() -> str:
    return os.path.join(_yollar().runtime_dir(), "ocr-gpu.pid")


def _sunucu_pid() -> int | None:
    """PID dosyasındaki süreç bizim sunucumuz mu (aynı kullanıcı + komut satırında ocr_gpu.sunucu)?"""
    try:
        pid = int(open(pid_yolu()).read().strip())
        if os.stat(f"/proc/{pid}").st_uid != os.getuid():
            return None
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return pid if b"ocr_gpu.sunucu" in f.read() else None
    except (OSError, ValueError):
        return None


def kapat() -> bool:
    """Çalışan sunucuyu kapatır (oyuna geçildiğinde): SIGTERM (donmuşsa SIGCONT ile teslim edilir). → kapatıldı mı."""
    pid = _sunucu_pid()
    if pid is None:
        try:
            s, pid = _baglan(0.3)
            s.close()
        except (OSError, PermissionError):
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        os.kill(pid, signal.SIGCONT)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- sunucu (OCR venv yorumlayıcısında çalışır)

def _bekci(sunucu_pid: int, durum: mmap.mmap, kfd: int, bosta_kapan: float):
    """Torch'suz çocuk süreç: boşta 5 dk ya da oyun → sunucuyu kapat. Sunucu ölünce çıkar."""
    os.close(kfd)  # kilit yalnız sunucunun ömrü boyunca tutulsun (flock: kopyayı kapatmak kilidi bırakmaz)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    while True:
        time.sleep(BEKCI_SN)
        if os.getppid() != sunucu_pid:
            os._exit(0)
        (son,) = struct.unpack_from("d", durum, 0)
        if time.time() - son > bosta_kapan or oyunda():
            for sig in (signal.SIGTERM, signal.SIGCONT):
                try:
                    os.kill(sunucu_pid, sig)
                except OSError:
                    pass
            os._exit(0)


def sunucu(soket: str, kilit: str, modeller: str, bosta_kapan: float = BOSTA_KAPAN_SN):
    """Kalıcı OCR sunucusu. Aynı anda tek sunucu (kilit dosyası ömür boyu tutulur)."""
    pid_dosyasi = os.path.join(os.path.dirname(soket), "ocr-gpu.pid")
    os.umask(0o077)
    os.makedirs(os.path.dirname(soket), mode=0o700, exist_ok=True)
    kfd = os.open(kilit, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(kfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # başka bir sunucu ayakta / açılıyor
    durum = mmap.mmap(-1, 8)
    struct.pack_into("d", durum, 0, time.time())
    ana = os.getpid()
    if os.fork() == 0:  # bekçi: torch içe aktarılmadan önce
        _bekci(ana, durum, kfd, bosta_kapan)
    t0 = time.monotonic()
    hata = os.path.join(os.path.dirname(soket), "ocr-gpu.hata")
    try:
        import numpy as np
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("torch ekran kartını görmüyor (torch.cuda.is_available() = False)")
        import easyocr
        okuyucu = easyocr.Reader(DILLER, gpu=True, model_storage_directory=modeller, download_enabled=False, verbose=False)
        torch.cuda.empty_cache()
    except Exception as e:  # noqa: BLE001 — açılamadı: istemciler bir süre denemesin, tesseract'la devam
        _hata_yaz(f"{type(e).__name__}: {e}", hata)
        print(f"açılamadı: {type(e).__name__}: {e}", flush=True)
        os._exit(1)
    try:
        os.unlink(soket)
    except FileNotFoundError:
        pass
    ls = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    ls.bind(soket)
    os.chmod(soket, 0o600)
    soket_ino = os.stat(soket).st_ino  # kapanırken yalnız KENDİ soket dosyamızı sil
    ls.listen(8)

    def bitir(*_a):
        try:
            if os.stat(soket).st_ino == soket_ino:
                os.unlink(soket)
        except OSError:
            pass
        try:
            os.unlink(pid_dosyasi)
        except OSError:
            pass
        os._exit(0)
    signal.signal(signal.SIGTERM, bitir)
    with open(pid_dosyasi, "w") as f:
        f.write(str(os.getpid()))
    print(f"hazır ({time.monotonic() - t0:.1f} sn, {torch.cuda.get_device_name(0)})", flush=True)
    while True:
        if not select.select([ls], [], [], BOSTA_DUR_SN)[0]:
            os.kill(os.getpid(), signal.SIGSTOP)  # boşta: dondur (istemci SIGCONT ile uyandırır)
            continue
        c, _adr = ls.accept()
        try:
            c.settimeout(ISTEK_SN)
            if _es_kullanici(c) is None:
                continue
            struct.pack_into("d", durum, 0, time.time())
            baslik, veri = ileti_oku(c)
            if baslik.get("komut") != "oku":
                ileti_yaz(c, {"hata": "bilinmeyen komut"})
                continue
            w, h = int(baslik["w"]), int(baslik["h"])
            if w * h > EN_BUYUK or len(veri) != w * h * 3:
                ileti_yaz(c, {"hata": "boyut"})
                continue
            t = time.monotonic()
            a = np.frombuffer(veri, np.uint8).reshape(h, w, 3)
            # batch_size 32: ölçümde çıktı kalitesi aynı (38/38, birebir 27/38), en kötü süre 1,66 → 0,56 sn
            sonuc = okuyucu.readtext(a, mag_ratio=float(baslik.get("mag", 1.0)), batch_size=32)
            kutular = []
            for kose, metin, guven in sonuc:
                xs, ys = [float(p[0]) for p in kose], [float(p[1]) for p in kose]
                kutular.append([min(xs), min(ys), max(xs), max(ys), metin, float(guven)])
            vram = torch.cuda.max_memory_reserved() / 2**20
            torch.cuda.empty_cache()  # boşta VRAM'i düşük tut
            ileti_yaz(c, {"kutular": kutular, "sure": time.monotonic() - t, "vram_tepe_mb": round(vram)})
        except Exception as e:  # noqa: BLE001 — tek istek sunucuyu düşürmesin
            try:
                ileti_yaz(c, {"hata": f"{type(e).__name__}: {e}"[:300]})
            except OSError:
                pass
        finally:
            c.close()
            struct.pack_into("d", durum, 0, time.time())


def indir(hedef: str | None = None):
    """Model dosyalarını (EasyOCR tespit + latin tanıma, ~100 MB) indirir. OCR venv yorumlayıcısıyla çalıştırılır."""
    hedef = hedef or model_dizin()
    os.makedirs(hedef, exist_ok=True)
    import easyocr
    easyocr.Reader(DILLER, gpu=False, model_storage_directory=hedef, download_enabled=True, verbose=True)
    print(hedef)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "indir":
        indir(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print("kullanım: python -m deskhand.ocr_gpu indir [dizin]")
        sys.exit(2)
