"""Test yalıtımı: kullanıcının GERÇEK oturumundaki bekleyen onay/devir isteği (request_human) teste sızmaz.

Olay (28 Kas 2026): tam takım koşarken gerçek oturumda bir MCP request_human bekliyordu; test_odeme_kilit 2 kontrolde
"7 onay bekleniyor: başka bir Deskhand sürecinin insan onayı sürerken girdi gönderilmez" ile düştü. Kök neden: test,
onay.iste_sonuc'un "kullanıcının gerçek paneli" dalını sınamak için DESKHAND_RUNTIME_DIR'i ortamdan siliyordu; o anda
hata.calisma_dizini() $XDG_RUNTIME_DIR/deskhand'e (gerçek /run/user/UID/deskhand) düşüyor, eylem._bekleyen_onay_kapisi
oradaki canlı istek dosyasını görüyordu.

Bu test gerçek kullanıcının dizinine DOKUNMAZ: "gerçek" kök, GECICI altında sahte bir XDG_RUNTIME_DIR'dir.
1. Üretim davranışı: DESKHAND_RUNTIME_DIR yokken $XDG_RUNTIME_DIR/deskhand'deki başka bir canlı sürecin isteği girdiyi
   keser (bekleyen_var True, eylem kapısı Dur 7) — iki Deskhand süreci arasındaki kilit değişmedi.
2. Yalıtım: _yalitim.gercek_calisma_dizini() içinde DESKHAND_RUNTIME_DIR yok (gerçek panel dalı korunur) ama çalışma
   dizini GECICI altındadır; sahte "gerçek" kökteki istek görünmez.
3. Olayın yeniden üretimi: test_odeme_kilit, XDG_RUNTIME_DIR'inde canlı ekran + arka devir isteği olan bir ortamda
   alt süreç olarak koşar ve geçer.

Çalıştır:  python3 tests/test_yalitim_kilit.py"""
import _yalitim

import json
import os
import subprocess
import sys
import time
import uuid

from deskhand import eylem, hata, onay
from deskhand.hata import Dur

GECEN = TOPLAM = 0


def kontrol(ad, kosul, ayrinti=""):
    global GECEN, TOPLAM
    TOPLAM += 1
    GECEN += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ayrinti})" if ayrinti and not kosul else ""), flush=True)
    return bool(kosul)


# ---------------------------------------------------------------- sahte "gerçek" XDG_RUNTIME_DIR + canlı istekler
SAHTE_XDG = os.path.join(_yalitim.GECICI, "sahte-gercek-xdg")
os.makedirs(os.path.join(SAHTE_XDG, "deskhand", "onay"), mode=0o700)
os.chmod(os.path.join(SAHTE_XDG, "deskhand"), 0o700)
SAHIP = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL)


def istek_yaz(masaustu):
    simdi = time.time()
    istek_id = uuid.uuid4().hex
    veri = {"id": istek_id, "eylem": "insan doğrulaması", "hedef": "deneme", "ayrinti": "", "masaustu": masaustu,
            "masa": "", "zaman": simdi, "son_zaman": simdi + 600, "pid": SAHIP.pid,
            "pid_bas": onay._baslangic(SAHIP.pid), "goruntu": None, "tur": onay.TUR_DEVIR}
    yol = os.path.join(SAHTE_XDG, "deskhand", "onay", f"istek-{istek_id}.json")
    with open(yol, "w") as f:
        json.dump(veri, f)
    os.chmod(yol, 0o600)


istek_yaz("ekran")
istek_yaz("arka")


class _AU:
    def __init__(self, ad):
        self.ad = ad


def kapi_kodu(ad):
    """eylem._bekleyen_onay_kapisi'nin sonucu: 0 (geçti) ya da Dur kodu."""
    eski = eylem._au
    eylem._au = lambda: _AU(ad)
    try:
        eylem._bekleyen_onay_kapisi()
        return 0
    except Dur as e:
        return e.kod
    finally:
        eylem._au = eski


ASIL_XDG = os.environ.get("XDG_RUNTIME_DIR")
ASIL_RT = os.environ["DESKHAND_RUNTIME_DIR"]
try:
    os.environ["XDG_RUNTIME_DIR"] = SAHTE_XDG
    # ============================================================ 1. üretim: gerçek oturumda iki süreç arası kilit
    os.environ.pop("DESKHAND_RUNTIME_DIR")
    try:
        kontrol("üretim: çalışma dizini $XDG_RUNTIME_DIR/deskhand",
                hata.calisma_dizini() == os.path.join(SAHTE_XDG, "deskhand"), hata.calisma_dizini())
        kontrol("üretim: başka canlı sürecin ekran isteği görülür (bekleyen_var)",
                onay.bekleyen_var("ekran", haric_pid=os.getpid()))
        kontrol("üretim: başka canlı sürecin arka (görünmez masaüstü) isteği görülür",
                onay.bekleyen_var("arka", haric_pid=os.getpid()))
        kontrol("üretim: eylem kapısı ekranda Dur 7", kapi_kodu("kde") == 7, str(kapi_kodu("kde")))
        kontrol("üretim: eylem kapısı görünmez masaüstünde Dur 7", kapi_kodu("sanal") == 7, str(kapi_kodu("sanal")))
        kontrol("üretim: sahibin kendi isteği kendisini kilitlemez (haric_pid)",
                not onay.bekleyen_var("ekran", haric_pid=SAHIP.pid))
    finally:
        os.environ["DESKHAND_RUNTIME_DIR"] = ASIL_RT

    # ============================================================ 2. yalıtım
    kontrol("yalıtım: DESKHAND_RUNTIME_DIR varken sahte gerçek kökteki istek görünmez",
            not onay.bekleyen_var("ekran") and not onay.bekleyen_var("arka") and kapi_kodu("kde") == 0)
    yardimci = getattr(_yalitim, "gercek_calisma_dizini", None)
    if kontrol("yalıtım: _yalitim.gercek_calisma_dizini var", yardimci is not None) and yardimci is not None:
        with yardimci():
            kontrol("gercek_calisma_dizini: DESKHAND_RUNTIME_DIR yok (iste_sonuc gerçek panel dalı)",
                    "DESKHAND_RUNTIME_DIR" not in os.environ)
            kontrol("gercek_calisma_dizini: çalışma dizini GECICI altında, sahte gerçek kökte değil",
                    hata.calisma_dizini().startswith(_yalitim.GECICI + os.sep) and
                    not hata.calisma_dizini().startswith(SAHTE_XDG), hata.calisma_dizini())
            kontrol("gercek_calisma_dizini: gerçek oturumdaki bekleyen istek görünmez (ekran + arka)",
                    not onay.bekleyen_var("ekran") and not onay.bekleyen_var("arka"))
            kontrol("gercek_calisma_dizini: eylem kapısı Dur 7 vermez", kapi_kodu("kde") == 0 and kapi_kodu("sanal") == 0)
        kontrol("gercek_calisma_dizini: çıkışta ortam geri gelir",
                os.environ.get("DESKHAND_RUNTIME_DIR") == ASIL_RT and os.environ.get("XDG_RUNTIME_DIR") == SAHTE_XDG)

    # ============================================================ 3. olay: test_odeme_kilit gerçek istek varken
    ortam = dict(os.environ, XDG_RUNTIME_DIR=SAHTE_XDG)
    ortam.pop("DESKHAND_MASAUSTU", None)
    r = subprocess.run([sys.executable, os.path.join(_yalitim.KOK, "tests", "test_odeme_kilit.py")], env=ortam,
                       cwd=os.path.join(_yalitim.KOK, "tests"), capture_output=True, text=True, timeout=120)
    kaldi = [s for s in r.stdout.splitlines() if s.startswith("KALDI")]
    kontrol("olay: gerçek oturumda canlı onay/devir isteği varken test_odeme_kilit geçer",
            r.returncode == 0 and not kaldi, "; ".join(kaldi) or r.stderr[-500:])
    kontrol("olay: sahte gerçek köke test yazmadı (yalnız iki istek dosyası)",
            sorted(os.listdir(os.path.join(SAHTE_XDG, "deskhand"))) == ["onay"] and
            len(os.listdir(os.path.join(SAHTE_XDG, "deskhand", "onay"))) == 2,
            str(os.listdir(os.path.join(SAHTE_XDG, "deskhand"))))
finally:
    if ASIL_XDG is None:
        os.environ.pop("XDG_RUNTIME_DIR", None)
    else:
        os.environ["XDG_RUNTIME_DIR"] = ASIL_XDG
    os.environ["DESKHAND_RUNTIME_DIR"] = ASIL_RT
    SAHIP.kill()
    SAHIP.wait()

print(f"\n{GECEN}/{TOPLAM} yalıtım/kilit testi geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
