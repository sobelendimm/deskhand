"""Alt süreç komutları paket klasörünü (pip/pipx'te site-packages) sys.path'in BAŞINA koymaz.

- ocr_gpu sunucusu (başka yorumlayıcı: OCR venv'i) ve masaüstü oto temizleyicisi (arka_ortak.python_yolu: sistem
  python3'ü olabilir): yalnız bu deskhand paketi kendi klasöründen yüklenir, sys.path değişmez; çalışma klasörü de
  yola girmez (-P / -I).
- gorev (MCP komutu) ve erisim yardımcısı (aynı yorumlayıcı, -I): paket kökü yalnız yorumlayıcının kendi yolunda
  değilse eklenir (kaynak klasörü, pip --user); venv/sistem site-packages altındaysa eklenmez.

Çalıştır:  python3 tests/test_paket_yolu.py"""
import os
import subprocess
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import erisim, gorev, masaustu, ocr_gpu, yollar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


TUZAK = tempfile.mkdtemp(prefix="deskhand-yol-")
os.makedirs(os.path.join(TUZAK, "deskhand"))
with open(os.path.join(TUZAK, "deskhand", "__init__.py"), "w") as f:
    f.write("raise SystemExit('golge')\n")
UST = os.path.realpath(os.path.dirname(yollar.PAKET_DIZIN))
DENETIM = ("import os, sys\nfrom deskhand import ocr_gpu as _o\nprint(os.path.realpath(_o.__file__))\n"
           f"print(any(os.path.realpath(p or '.') == {UST!r} for p in sys.path))\n")


def kos(bayraklar, kod):
    """Kodu bu yorumlayıcıyla, gölgeleyici sahte deskhand/ içeren çalışma klasöründe koşar → (rc, satırlar)."""
    ortam = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}  # _yalitim depo kökünü PYTHONPATH yapar
    r = subprocess.run([sys.executable, *bayraklar, "-c", kod], cwd=TUZAK, capture_output=True, text=True, timeout=60,
                       env=ortam)
    return r.returncode, r.stdout.splitlines(), r.stderr


GERCEK = os.path.realpath(ocr_gpu.__file__)

# ---------------------------------------------------------------- 1) ocr_gpu sunucu komutu
eski_which = ocr_gpu.shutil.which
ocr_gpu.shutil.which = lambda ad: None  # düz komut (gpu-is / systemd-run yok)
try:
    k = ocr_gpu._baslat_komutu("/opt/ocr-venv/bin/python")
finally:
    ocr_gpu.shutil.which = eski_which
kod = k[k.index("-c") + 1]
kontrol("ocr sunucu: sys.path.insert yok", "sys.path.insert" not in kod, kod)
kontrol("ocr sunucu: çalışma klasörü yola girmez (-P), kullanıcı sitesi yok (-s)",
        "-P" in k[:k.index("-c")] and "-s" in k[:k.index("-c")], str(k[:4]))
kontrol("ocr sunucu: kodun tamamı derlenir", bool(compile(kod, "<ocr>", "exec")))
yukleme = kod.split("from deskhand import ocr_gpu")[0]
rc, satir, hata = kos(["-s", "-P"], yukleme + "\n" + DENETIM)
kontrol("ocr sunucu kodu: gerçek paket yüklenir, paket üst klasörü sys.path'te yok",
        rc == 0 and satir == [GERCEK, "False"], f"{satir} {hata[-300:]}")

# ---------------------------------------------------------------- 2) masaüstü oto temizleyici
yakalanan = []
eski_popen = masaustu.subprocess.Popen
masaustu.subprocess.Popen = lambda a, **kw: yakalanan.append((a, kw))
try:
    masaustu.oto_temizleyici_baslat("oto-deneme", bekle=0)
finally:
    masaustu.subprocess.Popen = eski_popen
a = yakalanan[0][0] if yakalanan else []
kod = a[a.index("-c") + 1] if "-c" in a else ""
kontrol("oto temizleyici: sys.path.insert yok, -I", "sys.path.insert" not in kod and "-I" in a, str(a))
rc, satir, hata = kos(["-I"], kod.split("import time")[0] + "\n" + DENETIM)
kontrol("oto temizleyici kodu: gerçek paket yüklenir, paket üst klasörü sys.path'te yok",
        rc == 0 and satir == [GERCEK, "False"], f"{satir} {hata[-300:]}")
kontrol("oto temizleyici: kodun tamamı derlenir", bool(compile(kod, "<oto>", "exec")))
kontrol("oto temizleyici: argümanlar ad + süre", a[-2:] == ["oto-deneme", "0"], str(a))

# ---------------------------------------------------------------- 3) aynı yorumlayıcı: gorev / erisim
kontrol("kok_eklenmeli: sys.prefix altındaki site-packages → hayır",
        ocr_gpu.kok_eklenmeli(os.path.join(sys.prefix, "lib", "python3", "site-packages")) is False)
kontrol("kok_eklenmeli: sys.base_prefix altındaki → hayır",
        ocr_gpu.kok_eklenmeli(os.path.join(sys.base_prefix, "lib", "python3", "dist-packages")) is False)
kontrol("kok_eklenmeli: kaynak klasörü / kullanıcı sitesi → evet", ocr_gpu.kok_eklenmeli(TUZAK) is True)

eski = (gorev.shutil.which, gorev.os.path.isfile, yollar.PAKET_DIZIN)
gorev.shutil.which = lambda ad: None
gorev.os.path.isfile = lambda y: False if y.endswith("/deskhand") else eski[1](y)
try:
    yollar.PAKET_DIZIN = os.path.join(sys.prefix, "lib", "python3", "site-packages", "deskhand")
    kod = gorev.deskhand_komutu()[3]
    kontrol("gorev MCP komutu (pip/pipx): site-packages yola eklenmez", "sys.path.insert" not in kod, kod)
    yollar.PAKET_DIZIN = eski[2]
    kod = gorev.deskhand_komutu()[3]
    kontrol("gorev MCP komutu (kaynak klasörü): kök eklenir (eski davranış)", f"sys.path.insert(0, {UST!r})" in kod
            or f"sys.path.insert(0, {os.path.dirname(yollar.PAKET_DIZIN)!r})" in kod, kod)
finally:
    gorev.shutil.which, gorev.os.path.isfile, yollar.PAKET_DIZIN = eski

yakalanan.clear()


class _Sonuc:
    stdout = '{"dur": null, "sonuc": 1}\n'
    returncode = 0


eski_run = erisim.subprocess.run
erisim.subprocess.run = lambda a, **kw: (yakalanan.append(a), _Sonuc())[1]
eski_ek = ocr_gpu.kok_eklenmeli
try:
    ocr_gpu.kok_eklenmeli = lambda kok=None: False
    try:
        erisim._yardimci_calistir({"islem": "deneme"})
    except Exception:  # noqa: BLE001 - yalnız komut yakalanır
        pass
    kod = yakalanan[0][yakalanan[0].index("-c") + 1] if yakalanan else ""
    kontrol("erisim yardımcısı (pip/pipx): sys.path.insert yok", kod and "sys.path.insert" not in kod, kod)
    yakalanan.clear()
    ocr_gpu.kok_eklenmeli = lambda kok=None: True
    try:
        erisim._yardimci_calistir({"islem": "deneme"})
    except Exception:  # noqa: BLE001
        pass
    kod = yakalanan[0][yakalanan[0].index("-c") + 1] if yakalanan else ""
    kontrol("erisim yardımcısı (kaynak klasörü): kök eklenir (eski davranış)", "sys.path.insert" in kod, kod)
finally:
    erisim.subprocess.run = eski_run
    ocr_gpu.kok_eklenmeli = eski_ek

import shutil  # noqa: E402
shutil.rmtree(TUZAK, ignore_errors=True)
print(f"\n{gecen}/{toplam} paket yolu testi geçti")
sys.exit(0 if gecen == toplam else 1)
