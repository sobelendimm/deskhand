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
4. Sınıf denetimi (otomatik): tests/ altında DESKHAND_RUNTIME_DIR / XDG_RUNTIME_DIR'i silen ya da değiştiren her kalıp
   (os.environ.pop, del, monkeypatch.delenv/setenv, atama, ortam sözlüğü kopyasında anahtar/kwarg/süzme) yalnız
   tests/_yalitim.py'de serbest; başka yerde ancak IZINLI listesinde (gerekçeli) olabilir, yoksa dosya:satır ile düşer.

Çalıştır:  python3 tests/test_yalitim_kilit.py"""
import _yalitim

import json
import os
import re
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

# ================================================================ 4. sınıf denetimi: runtime ortam değişkeni kalıpları
_V = r"(?:DESKHAND|XDG)_RUNTIME_DIR"
_T = r"[\"']"
KALIP = re.compile("|".join((
    rf"\.pop\(\s*{_T}{_V}{_T}",                          # os.environ.pop / ortam_kopyasi.pop
    rf"\bdel\s+\S*\[\s*{_T}{_V}{_T}\s*\]",              # del os.environ[...] / del ortam[...]
    rf"\b(?:delenv|setenv)\(\s*{_T}{_V}{_T}",            # monkeypatch
    rf"\[\s*{_T}{_V}{_T}\s*\]\s*=(?!=)",                 # os.environ[...] = / ortam[...] =
    rf"{_T}{_V}{_T}\s*:",                                # sözlük anahtarı (alt süreç ortamı, update({...}))
    rf"(?<![\w\"'])\b{_V}\s*=(?!=)",                     # dict(os.environ, X=...) / update(X=...)
    rf"!=\s*{_T}{_V}{_T}",                               # süzerek silme: {k: v ... if k != "X"}
    rf"\bnot\s+in\s*[(\[{{][^)\]}}]*{_T}{_V}{_T}",       # süzerek silme: if k not in ("X", ...)
)))
# Meşru kurulumlar: (dosya, satırın kırpılmış metni). Hepsi değişkeni GEÇİCİ/sahte bir köke yöneltir ya da DESKHAND_RUNTIME_DIR
# ayarlıyken yalnız XDG_RUNTIME_DIR'i değiştirir (calisma_dizini gerçek köke düşmez). Yeni satır eklemek yerine
# _yalitim.gercek_calisma_dizini() kullanın.
IZINLI = {
    # cuzdan_ac XDG_RUNTIME_DIR altında soket açar: S geçici dizin (DESKHAND_RUNTIME_DIR ayarlı kalır)
    ("tests/test_cuzdan_ac.py", 'os.environ["XDG_RUNTIME_DIR"] = os.path.join(S, "run")'),
    # K2-3: XDG_RUNTIME_DIR yok/gevşek/göreli → ret sınaması; Popen sahte, DESKHAND_RUNTIME_DIR ayarlı kalır
    ("tests/test_k2_arac_yolu.py", 'eski_rt = os.environ.pop("XDG_RUNTIME_DIR", None)'),
    ("tests/test_k2_arac_yolu.py", 'os.environ["XDG_RUNTIME_DIR"] = gevsek'),
    ("tests/test_k2_arac_yolu.py", 'os.environ["XDG_RUNTIME_DIR"] = "goreli/yol"'),
    ("tests/test_k2_arac_yolu.py", 'os.environ["XDG_RUNTIME_DIR"] = eski_rt'),
    # görünmez masaüstünün KENDİ çalışma klasörü (D["calisma"]) ile wl-copy / araç alt süreçleri
    ("tests/test_kwin_oturum.py", 'wenv = {"PATH": "/usr/bin", "WAYLAND_DISPLAY": D["wayland_yol"], "XDG_RUNTIME_DIR": D["calisma"]}'),
    ("tests/test_kwin_oturum.py", 'aenv = {"PATH": "/usr/bin", "HOME": os.path.join(D["calisma"], "ev"), "XDG_RUNTIME_DIR": D["calisma"],'),
    # Wayland sızıntı sınaması: sahte_rt geçici klasör (gerçek wayland-0'a bağlanılmasın)
    ("tests/test_sanal.py", 'e0 = {k_: v_ for k_, v_ in ue.items() if k_ != "WAYLAND_DISPLAY"} | {"XDG_RUNTIME_DIR": sahte_rt}'),
    ("tests/test_sanal.py", 'pw = masaustu.baslat([sys.executable, "-c", kod_], {"XDG_RUNTIME_DIR": sahte_rt}, stdout=subprocess.PIPE,'),
    # env -i karşılığı: tüm XDG_* geçici `ev` altında
    ("tests/_gorsel.py", '"XDG_RUNTIME_DIR": os.path.join(ev, "r"), "DESKHAND_ANAHTARLIK": "kapali",'),
    # bu test: sahte "gerçek" kök (SAHTE_XDG, GECICI altında) ile üretim kilidini sınar (bölüm 1 ve 3)
    ("tests/test_yalitim_kilit.py", 'os.environ["XDG_RUNTIME_DIR"] = SAHTE_XDG'),
    ("tests/test_yalitim_kilit.py", 'os.environ.pop("DESKHAND_RUNTIME_DIR")'),
    ("tests/test_yalitim_kilit.py", 'os.environ["DESKHAND_RUNTIME_DIR"] = ASIL_RT'),
    ("tests/test_yalitim_kilit.py", "ortam = dict(os.environ, XDG_RUNTIME_DIR=SAHTE_XDG)"),
    ("tests/test_yalitim_kilit.py", 'os.environ.pop("XDG_RUNTIME_DIR", None)'),
    ("tests/test_yalitim_kilit.py", 'os.environ["XDG_RUNTIME_DIR"] = ASIL_XDG'),
}


def runtime_kaliplari(kok):
    """tests/ altındaki .py dosyalarında runtime değişkenini silen/değiştiren satırlar → [(göreli yol, satır no, metin)]."""
    bulgu = []
    for dizin, alt, dosyalar in os.walk(os.path.join(kok, "tests")):
        alt[:] = sorted(a for a in alt if a != "__pycache__")
        for ad in sorted(dosyalar):
            if not ad.endswith(".py"):
                continue
            yol = os.path.join(dizin, ad)
            goreli = os.path.relpath(yol, kok)
            if goreli == "tests/_yalitim.py":
                continue
            with open(yol, encoding="utf-8", errors="replace") as f:
                for no, satir in enumerate(f, 1):
                    if goreli == "tests/test_yalitim_kilit.py" and satir.startswith("# " + "=" * 64 + " 4."):
                        break  # bu bölümün kendi kalıp/izin/örnek metinleri taranmaz
                    if KALIP.search(satir):
                        bulgu.append((goreli, no, satir.strip()))
    return bulgu


ORNEKLER = ('os.environ.pop("DESKHAND_RUNTIME_DIR")', "del os.environ['XDG_RUNTIME_DIR']",
            'monkeypatch.delenv("DESKHAND_RUNTIME_DIR")', 'os.environ["DESKHAND_RUNTIME_DIR"] = "/x"',
            'env = {"XDG_RUNTIME_DIR": "/run/user/1000"}', "e = dict(os.environ, DESKHAND_RUNTIME_DIR='')",
            'e = {k: v for k, v in os.environ.items() if k != "DESKHAND_RUNTIME_DIR"}',
            'e = {k: v for k, v in os.environ.items() if k not in ("A", "DESKHAND_RUNTIME_DIR")}')
ZARARSIZ = ('d = os.environ.get("DESKHAND_RUNTIME_DIR")', 'rt = os.environ["DESKHAND_RUNTIME_DIR"]',
            'any(s.startswith("XDG_RUNTIME_DIR=") for s in x)', 'if os.environ["XDG_RUNTIME_DIR"] == y: pass')
kontrol("sınıf denetimi: kalıp her silme/değiştirme biçimini yakalar",
        all(KALIP.search(s) for s in ORNEKLER), [s for s in ORNEKLER if not KALIP.search(s)])
kontrol("sınıf denetimi: okuma/karşılaştırma yanlış alarm değil",
        not any(KALIP.search(s) for s in ZARARSIZ), [s for s in ZARARSIZ if KALIP.search(s)])
_bulgu = runtime_kaliplari(_yalitim.KOK)
_ihlal = [f"{y}:{n}: {s}" for y, n, s in _bulgu if (y, s) not in IZINLI]
kontrol("sınıf denetimi: runtime değişkenini silen/değiştiren kalıp yalnız _yalitim'de (ya da gerekçeli izin listesinde)",
        not _ihlal, "; ".join(_ihlal))
_kullanilmayan = sorted(IZINLI - {(y, s) for y, _n, s in _bulgu})
kontrol("sınıf denetimi: izin listesinde bayat satır yok", not _kullanilmayan, str(_kullanilmayan))

print(f"\n{GECEN}/{TOPLAM} yalıtım/kilit testi geçti")
raise SystemExit(0 if GECEN == TOPLAM else 1)
