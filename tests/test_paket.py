"""Paketleme (PyPI / pipx) testleri: sdist + wheel çalışma anında okunan veri dosyalarını taşır (deskhand/data, i18n
kataloğu, tema belirteçleri, C yardımcılarının kaynakları + Makefile), `deskhand doctor` pip'in getiremediği sistem
araçlarını Arch / Debian / Fedora paket adıyla söyler, kaynak ağacı dışında (pipx) C yardımcıları için `make -C <paket>`
komutunu verir.

Derleme depo kökünün geçici bir KOPYASINDA yapılır (depoya build/, dist/, *.egg-info yazılmaz); `python -m build
--no-isolation` (ağ yok; sistem setuptools). sdist önce, wheel o sdist'ten üretilir: sdist eksikse wheel de eksik çıkar.

Çalıştır:  python3 tests/test_paket.py"""
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import __version__, doktor, yollar
from deskhand.gui import saglik

KOK = _yalitim.KOK
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def _paket_verileri() -> set[str]:
    """Kaynak ağacında çalışma anında okunan veri dosyaları (deskhand/ altına göre): beklenen liste koddan değil
    diskten çıkar, yeni bir veri dosyası eklenince test kendiliğinden genişler."""
    beklenen = set()
    for alt, uzantilar in (("data", None), ("i18n", (".json",)), ("gui/tema", (".json",)),
                           ("yardimci", (".c", ".h"))):
        for f in os.listdir(os.path.join(KOK, "deskhand", alt)):
            yol = os.path.join(KOK, "deskhand", alt, f)
            if os.path.isfile(yol) and (uzantilar is None or f.endswith(uzantilar)):
                beklenen.add(f"{alt}/{f}")
    beklenen.add("yardimci/Makefile")
    return beklenen


def test_wheel_veri_dosyalari():
    gecici = tempfile.mkdtemp(prefix="deskhand-paket-")
    try:
        kopya = os.path.join(gecici, "kaynak")
        shutil.copytree(KOK, kopya, ignore=shutil.ignore_patterns(".git", ".claude", ".serena", "dist", "build",
                                                                   "*.egg-info", "__pycache__", "*.pyc"))
        cikti = os.path.join(gecici, "dist")
        r = subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir", cikti, kopya],
                           capture_output=True, text=True, timeout=120)
        if not kontrol("build: sdist + wheel üretildi (python -m build --no-isolation)", r.returncode == 0,
                       (r.stdout + r.stderr)[-600:]):
            return
        whl = [f for f in os.listdir(cikti) if f.endswith(".whl")]
        sdist = [f for f in os.listdir(cikti) if f.endswith(".tar.gz")]
        kontrol(f"build: adlar sürümü taşır ({__version__})",
                whl == [f"deskhand-{__version__}-py3-none-any.whl"] and sdist == [f"deskhand-{__version__}.tar.gz"],
                f"{whl} {sdist}")
        beklenen = _paket_verileri()
        with zipfile.ZipFile(os.path.join(cikti, whl[0])) as z:
            w_adlar = {n.removeprefix("deskhand/") for n in z.namelist() if n.startswith("deskhand/")}
            giris = next((z.read(n).decode() for n in z.namelist() if n.endswith("entry_points.txt")), "")
        eksik = sorted(beklenen - w_adlar)
        kontrol("wheel: tüm veri dosyaları var (data/, i18n/en.json, gui/tema/tokens.json, yardimci/*.c *.h Makefile)",
                not eksik and "i18n/en.json" in w_adlar and any(n.startswith("data/") for n in w_adlar), str(eksik))
        kontrol("wheel: derlenmiş C yardımcısı ya da __pycache__ taşınmaz",
                not any((n.startswith("yardimci/deskhand-") and not n.endswith((".c", ".h"))) or "__pycache__" in n
                        for n in w_adlar), str(sorted(w_adlar)[:20]))
        kontrol("wheel: `deskhand` komutu (console_scripts → deskhand.cli:main)",
                "deskhand = deskhand.cli:main" in giris, giris)
        with tarfile.open(os.path.join(cikti, sdist[0])) as t:
            onek = f"deskhand-{__version__}/deskhand/"
            s_adlar = {n.removeprefix(onek) for n in t.getnames() if n.startswith(onek)}
        kontrol("sdist: tüm veri dosyaları var", not (beklenen - s_adlar), str(sorted(beklenen - s_adlar)))
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


def test_doctor_paket_adi():
    # her sağlık notunun paketi tabloda (bir araç eklenip tablo unutulursa yakalanır)
    notlar = [*saglik.ARAC_NOT.values(), *saglik.DILLER.values(), *saglik.MODULLER.values()]
    tablosuz = [n for n in notlar if doktor._paket(n)[0] not in doktor.DAGITIM_PAKETLERI]
    kontrol("tablo: her sağlık notunun Arch paketi DAGITIM_PAKETLERI'nde", not tablosuz, str(tablosuz))

    sahte = [
        {"ad": "tesseract", "tur": "arac", "ok": False, "not": saglik.ARAC_NOT["tesseract"]},
        {"ad": "Xvfb", "tur": "arac", "ok": False, "not": saglik.ARAC_NOT["Xvfb"]},
        {"ad": "kdotool", "tur": "arac", "ok": False, "not": saglik.ARAC_NOT["kdotool"]},
        {"ad": "tesseract: tur", "tur": "dil", "ok": False, "not": saglik.DILLER["tur"]},
        {"ad": "mcp", "tur": "modul", "ok": False, "not": saglik.MODULLER["mcp"]},
        {"ad": "openbox", "tur": "arac", "ok": True, "not": saglik.ARAC_NOT["openbox"]},
    ]
    asil = doktor.saglik.denetle
    doktor.saglik.denetle = lambda: sahte
    try:
        b = {s["ad"]: s for s in doktor.bagimlilik_satirlari()}
    finally:
        doktor.saglik.denetle = asil
    o = b["tesseract"]["oneri"]
    kontrol("doctor: tesseract eksik → Arch + Debian/Ubuntu + Fedora adı",
            "tesseract" in o and "Debian/Ubuntu: tesseract-ocr" in o and "Fedora: tesseract" in o, o)
    o = b["Xvfb"]["oneri"]
    kontrol("doctor: Xvfb eksik → xorg-server-xvfb / xvfb / xorg-x11-server-Xvfb",
            "xorg-server-xvfb" in o and "Debian/Ubuntu: xvfb" in o and "Fedora: xorg-x11-server-Xvfb" in o, o)
    o = b["tesseract: tur"]["oneri"]
    kontrol("doctor: Türkçe OCR verisi → tesseract-ocr-tur / tesseract-langpack-tur",
            "tesseract-data-tur" in o and "tesseract-ocr-tur" in o and "tesseract-langpack-tur" in o, o)
    o = b["kdotool"]["oneri"]
    kontrol("doctor: kdotool (AUR) → Fedora adı var, Debian'da paket yok → Debian anılmaz",
            "kdotool-bin" in o and "AUR" in o and "Fedora: kdotool" in o and "Debian" not in o, o)
    o = b["mcp"]["oneri"]
    kontrol("doctor: karşılığı bilinmeyen paket → yalnız Arch adı (uydurma yok)",
            "python-mcp" in o and "Debian" not in o and "Fedora" not in o, o)
    kontrol("doctor: var olan bağımlılıkta öneri yok", b["openbox"]["oneri"] == "", str(b["openbox"]))
    metin = doktor.metin(list(b.values()))
    kontrol("doctor metni: eksik satır paket adlarını gösterir", "Fedora: xorg-x11-server-Xvfb" in metin, metin)


def test_doctor_yardimci_komutu():
    asil_kaynak, asil_bin = doktor._kaynak_kurulumu, (yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin)
    yollar.etkinlik_bin = yollar.goruntu_bin = yollar.eis_bin = lambda: None
    try:
        doktor._kaynak_kurulumu = lambda: False  # pipx / pip: install.sh yok
        s = doktor.satir_yardimcilar()
        beklenen = f"make -C {os.path.join(yollar.PAKET_DIZIN, 'yardimci')}"
        kontrol("C yardımcıları (pipx): öneri paketin yardimci/ dizininde make komutu",
                s["durum"] == "uyari" and beklenen in s["oneri"] and "install.sh" not in s["oneri"], str(s))
        doktor._kaynak_kurulumu = lambda: True  # git klonu: install.sh var
        s = doktor.satir_yardimcilar()
        kontrol("C yardımcıları (kaynak ağacı): öneri ./install.sh", "install.sh" in s["oneri"], str(s))
    finally:
        doktor._kaynak_kurulumu = asil_kaynak
        yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin = asil_bin
    kontrol("kaynak ağacında koşan test: _kaynak_kurulumu() doğru (install.sh depo kökünde)", doktor._kaynak_kurulumu())


def test_libei_surum_siniri():
    """deskhand-eis ei_ping ister: eski libei (ör. Ubuntu 24.04) derlemeyi kırmamalı, Makefile atlar, doctor söyler."""
    en_az = doktor.libei_en_az()
    kontrol("libei: en düşük sürüm Makefile'dan okunur (LIBEI_EN_AZ)", bool(en_az) and en_az[0].isdigit(), en_az)
    asil = doktor._komut_ciktisi, yollar.eis_bin
    try:
        yollar.eis_bin = lambda: None
        doktor._komut_ciktisi = lambda *a, **k: "1.2.1" if a[:2] == ("pkg-config", "--modversion") else ""
        s = doktor.satir_yardimcilar()
        kontrol("doctor: libei eski → eis önerisinde sürüm + libei paket adları",
                doktor.libei_eski() == ("1.2.1", en_az) and f"libei 1.2.1 < {en_az}" in s["oneri"]
                and "Debian/Ubuntu: libei-dev" in s["oneri"] and "Fedora: libei-devel" in s["oneri"], str(s))
        doktor._komut_ciktisi = lambda *a, **k: "99.0" if a[:2] == ("pkg-config", "--modversion") else ""
        kontrol("doctor: libei yeni → libei notu yok", doktor.libei_eski() is None
                and "libei" not in doktor.satir_yardimcilar()["oneri"].split("(make")[0])
    finally:
        doktor._komut_ciktisi, yollar.eis_bin = asil
    if not all(shutil.which(t) for t in ("make", "pkg-config")) or subprocess.run(
            ["pkg-config", "--exists", "xkbcommon", "libsystemd"]).returncode:
        print("ATLANDI  Makefile sahte eski libei denemesi (make/pkg-config/xkbcommon/libsystemd yok)")
        return
    gecici = tempfile.mkdtemp(prefix="deskhand-libei-")
    try:
        with open(os.path.join(gecici, "libei-1.0.pc"), "w") as f:
            f.write("prefix=/usr\nincludedir=${prefix}/include/libei-1.0\n\nName: libei\nDescription: sahte\n"
                    "Version: 1.2.1\nCflags: -I${includedir}\nLibs: -lei\n")
        kopya = os.path.join(gecici, "yardimci")
        shutil.copytree(os.path.join(KOK, "deskhand", "yardimci"), kopya,
                        ignore=shutil.ignore_patterns("deskhand-etkinlik", "deskhand-goruntu", "deskhand-eis"))
        env = {**os.environ, "PKG_CONFIG_PATH": gecici + os.pathsep + os.environ.get("PKG_CONFIG_PATH", "")}
        r = subprocess.run(["make", "-s", "-C", kopya, "deskhand-eis"], capture_output=True, text=True, env=env,
                           timeout=60)
        kontrol("Makefile: sahte eski libei (1.2.1) → deskhand-eis ATLANDI, çıkış 0, ikili yok",
                r.returncode == 0 and "ATLANDI" in r.stderr and "1.2.1" in r.stderr
                and not os.path.exists(os.path.join(kopya, "deskhand-eis")), f"{r.returncode} {r.stderr[-300:]}")
    finally:
        shutil.rmtree(gecici, ignore_errors=True)


test_wheel_veri_dosyalari()
test_doctor_paket_adi()
test_doctor_yardimci_komutu()
test_libei_surum_siniri()
print(f"\n{gecen}/{toplam} paket testi geçti")
sys.exit(0 if gecen == toplam else 1)
