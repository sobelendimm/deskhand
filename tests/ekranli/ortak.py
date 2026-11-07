"""Ekranlı test takımlarının ortak yardımcıları. Bu takımlar GERÇEK ekrana girdi gönderir: yalnız kullanıcı
müsaitken, elle çalıştırılır (docs/ARCHITECTURE.md §6; hepsi: tests/ekranli/hepsi.sh). Ham dotool YOK: her girdi
Deskhand'in güvenlik denetiminden geçer.

- DESKHAND_*_DIR'ler geçici klasörde (tests/_yalitim.py); alt süreçler devralır.
- EKRAN: deskhand komutu ([python, -m, deskhand]); IS: günlük/çıktı dosyaları için geçici çalışma klasörü.
- Pencere arama/öne getirme gibi test kurulum işleri arka uç üzerinden (ham kdotool çağrısı yok).
- PID ayrımı (soy_pidleri / pid / pencere_bekle): testin kendi başlattığı süreçlerin pencereleri, kullanıcının
  aynı uygulamadaki pencerelerinden (ör. kendi Firefox'u) ayrılır.
- kod12_bildir: beklenmeyen 12 (insan önceliği: kullanıcı test sırasında klavye/fareye dokundu) HEPSI_KOD12
  dosyasına yazılır; hepsi.sh bunu takım özetinde ayrıca gösterir."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _yalitim  # noqa: E402,F401  (Deskhand'den ÖNCE)

from deskhand import yollar  # noqa: E402
from deskhand.arka_uc import sec  # noqa: E402

DIZIN = os.path.dirname(os.path.abspath(__file__))  # test_pencere.py, akis_pencere.py, test.akis
EKRAN = [sys.executable, "-m", "deskhand"]
IS = os.path.join(_yalitim.GECICI, "is")
os.makedirs(IS, exist_ok=True)
os.makedirs(yollar.cikti(), exist_ok=True)
TAKLIT = dict(os.environ, DESKHAND_INSAN_TAKLIDI="1")  # bu süreç İNSANI taklit ediyor: kendisi insan önceliği beklemez
INSAN_KODU = 12


def ara(desen):
    """Başlığı desene uyan pencere kimlikleri (deskhand bul)."""
    return [w for w, _, _ in sec().pencereler(desen)]


def aktif():
    return sec().aktif()


def baslik(k):
    return sec().baslik(k)


def sinif(k):
    return sec().sinif(k)


def kd(*a):
    """Test kurulumu için pencere işlemi (boyut/konum/öne getirme). Yalnız kde arka ucunda."""
    from deskhand.arka_uc.kde import kd as _kd
    return _kd(*a)


# ---------------------------------------------------------------- PID ayrımı

def pid_coz(deger):
    """Arka ucun pid() dönüşü (kde: kdotool çıktısı, dize) → int | None."""
    try:
        p = int(str(deger).strip())
    except (TypeError, ValueError):
        return None
    return p if p > 0 else None


def pid(k):
    """Pencerenin süreç kimliği (kdotool getwindowpid) → int | None."""
    try:
        return pid_coz(sec().pid(k))
    except Exception:  # noqa: BLE001 - pencere kapanmış olabilir
        return None


def ebeveynler(proc="/proc"):
    """{pid: ppid} tüm süreçler (/proc/N/stat; süreç adı parantezli ve boşluk içerebilir → son ')' sonrası)."""
    sonuc = {}
    try:
        adlar = os.listdir(proc)
    except OSError:
        return sonuc
    for ad in adlar:
        if not ad.isdigit():
            continue
        try:
            with open(os.path.join(proc, ad, "stat")) as f:
                stat = f.read()
        except OSError:
            continue  # süreç bu arada bitti
        try:
            alanlar = stat.rsplit(")", 1)[1].split()
            sonuc[int(ad)] = int(alanlar[1])  # alanlar[0] durum, [1] ppid
        except (IndexError, ValueError):
            continue
    return sonuc


def soy_pidleri(kok, ebeveyn=None):
    """kok ve onun tüm torunlarının pid kümesi. ebeveyn: {pid: ppid} (verilmezse /proc okunur; birim testi için)."""
    ebeveyn = ebeveynler() if ebeveyn is None else ebeveyn
    cocuklar = {}
    for p, pp in ebeveyn.items():
        cocuklar.setdefault(pp, []).append(p)
    kume, yigin = set(), [kok]
    while yigin:
        p = yigin.pop()
        if p in kume:
            continue
        kume.add(p)
        yigin.extend(cocuklar.get(p, ()))
    return kume


def bizim_mi(pencere_pid, kume):
    """Pencere bu testin süreç ağacına mı ait? pid bilinmiyorsa HAYIR (kullanıcının penceresi sayılır)."""
    return pencere_pid is not None and pencere_pid in kume


def pencere_bekle(desen, sure=20.0, kok_pid=None, aralik=0.15):
    """Başlığı desene uyan pencereyi bekle → kimlik | None. kok_pid verilirse YALNIZ o sürecin (ve
    torunlarının) penceresi kabul edilir: kullanıcının aynı başlıklı penceresi asla seçilmez."""
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        adaylar = ara(desen)
        if adaylar and kok_pid is None:
            return adaylar[0]
        if adaylar:
            kume = soy_pidleri(kok_pid)
            for k in adaylar:
                if bizim_mi(pid(k), kume):
                    return k
        time.sleep(aralik)
    return None


# ---------------------------------------------------------------- geçici ayarlar

def yasak_yaz(*desenler):
    """GEÇİCİ yasak pencere listesi (varsayılan liste boş: yasak testleri kendi desenini yazar)."""
    yol = yollar.yasak_dosya()
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w") as f:
        f.write("# ekranlı test (geçici)\n" + "".join(f"{d}\n" for d in desenler))
    return yol


# ---------------------------------------------------------------- insan müdahalesi kaydı

def kod12_bildir(kod, argv, beklenen=False):
    """Beklenmeyen 12'yi hepsi.sh için kaydet (HEPSI_KOD12 ortam değişkeni varsa)."""
    yol = os.environ.get("HEPSI_KOD12")
    if kod != INSAN_KODU or beklenen or not yol:
        return
    try:
        with open(yol, "a") as f:
            f.write(" ".join(str(x) for x in argv)[:200] + "\n")
    except OSError:
        pass
