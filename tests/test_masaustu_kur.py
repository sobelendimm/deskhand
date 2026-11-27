"""`deskhand install-desktop` (masaustu_kur): pip/pipx kurulumunda menü girdisi, simge, oturum açılışında panel ve KWin < 6.8
ekran görüntüsü izni; `--remove` yalnız kendi (imzalı) dosyalarını siler; install.sh kurulumu (git klonu) bozulmaz.
doctor: pip/pipx'te eksik menü/autostart için `deskhand install-desktop`, GPU OCR için ocr-venv komutları.

Bütün yazımlar geçici HOME / XDG_DATA_HOME / XDG_CONFIG_HOME altında (gerçek ~/.local/share'e yazılmaz); kbuildsycoca6
çağrısı sahtelenir; KWin sürümü enjekte edilir.

Çalıştır:  python3 tests/test_masaustu_kur.py"""
import contextlib
import io
import os
import shutil
import stat
import sys
import tempfile

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import cli, doktor, masaustu_kur as mk, ocr_gpu, yollar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def oku(yol):
    with open(yol, encoding="utf-8") as f:
        return f.read()


def yaz(yol, metin):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        f.write(metin)


def calistir(f, *a, **kw):
    """(dönüş, stdout+stderr) — f'in çıktısını yakalar."""
    tampon = io.StringIO()
    with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
        try:
            r = f(*a, **kw)
        except SystemExit as e:
            r = e.code
    return r, tampon.getvalue()


KOK = tempfile.mkdtemp(prefix="deskhand-mk-")
ESKI_ORTAM = {k: os.environ.get(k) for k in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME")}
ESKI = {"kaynak": mk._kaynak_kurulumu, "kwin": mk.kwin_surumu, "sycoca": mk._sycoca, "site": mk._kullanici_sitesi,
        "ice": mk._ice_aktarilabilir}
SYCOCA = []


def ortam_kur(ad):
    """Her senaryoya taze, boş bir ev dizini."""
    ev = os.path.join(KOK, ad)
    os.makedirs(ev)
    os.environ["HOME"] = ev
    os.environ["XDG_DATA_HOME"] = os.path.join(ev, "veri")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(ev, "ayar")
    return ev


mk._kaynak_kurulumu = lambda: False  # pip/pipx kurulumu gibi
mk.kwin_surumu = lambda: "6.7.2"
mk._sycoca = lambda: SYCOCA.append(1)
mk._kullanici_sitesi = lambda: False
mk._ice_aktarilabilir = lambda: True  # gerçek denetim: aşağıda ayrıca
try:
    # ---------------------------------------------------------------- 1) Exec kaçışı (install.sh desktop_exec ile aynı)
    print("1) Exec kaçışı")
    kontrol("güvenli yol tırnaksız", mk.exec_kacis("/usr/bin/python3") == "/usr/bin/python3")
    kontrol("boşluklu yol çift tırnakta", mk.exec_kacis("/a b/py") == '"/a b/py"', mk.exec_kacis("/a b/py"))
    kontrol("% ikilenir (tırnaksız)", mk.exec_kacis("/a%b") == "/a%%b", mk.exec_kacis("/a%b"))
    s = mk.exec_kacis('/x$y"z`w\\v')
    kontrol("$ \" ` \\ çift kaçışla tırnakta", s == '"/x\\\\$y\\\\"z\\\\`w\\\\\\\\v"', s)
    for kotu in ("/a\nb", "/a\tb", "/a\x7fb"):
        try:
            mk.exec_kacis(kotu)
            kontrol(f"denetim karakteri reddedilir: {kotu!r}", False)
        except mk.KurulumHatasi:
            kontrol(f"denetim karakteri reddedilir: {kotu!r}", True)
    kontrol("komut: mutlak yorumlayıcı + -I -m deskhand", mk.exec_satiri("panel --tepsi") ==
            f"{mk.exec_kacis(sys.executable)} -I -m deskhand panel --tepsi", mk.exec_satiri("panel --tepsi"))
    mk._kullanici_sitesi = lambda: True
    kontrol("kullanıcı site-packages kurulumu: -I yerine -E -P (kullanıcı sitesi görünür kalır)",
            mk.exec_satiri("panel") == f"{mk.exec_kacis(sys.executable)} -E -P -m deskhand panel")
    mk._kullanici_sitesi = lambda: False

    # ---------------------------------------------------------------- 2) kurulum
    print("2) kurulum (KWin 6.7)")
    ev = ortam_kur("kur")
    h = mk.hedefler()
    kontrol("hedefler XDG altında", h["menu"] == os.path.join(ev, "veri", "applications", "deskhand.desktop")
            and h["acilis"] == os.path.join(ev, "ayar", "autostart", "deskhand.desktop")
            and h["simge"] == os.path.join(ev, "veri", "icons", "hicolor", "scalable", "apps", "deskhand.svg"), str(h))
    r, cikti = calistir(mk.main, [])
    kontrol("çıkış 0", r == 0, cikti)
    for ad in ("menu", "gorev", "acilis", "goruntu", "simge"):
        kontrol(f"yazıldı: {ad}", os.path.isfile(h[ad]), cikti)
    menu, acilis, gorev, goruntu = (oku(h[a]) for a in ("menu", "acilis", "gorev", "goruntu"))
    kontrol("menü Exec = mutlak yorumlayıcı … panel", f"\nExec={mk.exec_satiri('panel')}\n" in menu, menu)
    kontrol("açılış Exec … panel --tepsi", f"\nExec={mk.exec_satiri('panel --tepsi')}\n" in acilis, acilis)
    kontrol("görev Exec … panel --gorev", f"\nExec={mk.exec_satiri('panel --gorev')}\n" in gorev, gorev)
    kontrol("şablon yorumları yazılmaz, ad/simge kalır", "TASLAK" not in menu and "\nName=Deskhand\n" in menu
            and "\nIcon=deskhand\n" in menu and menu.startswith("[Desktop Entry]\n"), menu[:200])
    kontrol("imza + install.sh işareti her dosyada", all(mk.IMZA in t and mk.ISARET in t for t in (menu, acilis, gorev, goruntu)))
    yardimci = os.path.join(yollar.PAKET_DIZIN, "yardimci", yollar.GORUNTU_AD)
    kontrol("görüntü izni: Exec = paketteki deskhand-goruntu (mutlak) + ScreenShot2",
            f"\nExec={mk.exec_kacis(yardimci)}\n" in goruntu
            and "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2" in goruntu, goruntu)
    with open(h["simge"], "rb") as a, open(os.path.join(yollar.PAKET_DIZIN, "data", "deskhand.svg"), "rb") as b:
        kontrol("simge = paketteki svg", a.read() == b.read())
    kontrol("izinler 0644", all(stat.S_IMODE(os.stat(h[a]).st_mode) == 0o644 for a in ("menu", "acilis", "simge")))
    kontrol("geçici dosya kalmadı", not [f for f in os.listdir(os.path.dirname(h["menu"])) if f.startswith(".")])
    kontrol("kbuildsycoca6 çağrıldı", SYCOCA)
    r, _c = calistir(mk.main, [])
    kontrol("yeniden çalıştırma güvenli (çıkış 0, içerik aynı)", r == 0 and oku(h["menu"]) == menu)

    # ---------------------------------------------------------------- 3) --no-autostart, KWin 6.8
    print("3) --no-autostart, KWin 6.8")
    r, cikti = calistir(mk.main, ["--no-autostart"])
    kontrol("--no-autostart: bizim açılış girdimiz silinir, menü kalır", r == 0 and not os.path.exists(h["acilis"])
            and os.path.isfile(h["menu"]), cikti)
    r, _c = calistir(mk.main, ["--acilissiz"])
    kontrol("Türkçe takma ad --acilissiz", r == 0 and not os.path.exists(h["acilis"]))
    ev = ortam_kur("kwin68")
    mk.kwin_surumu = lambda: "6.8.3"
    r, _c = calistir(mk.main, [])
    kontrol("KWin 6.8: görüntü izni girdisi yazılmaz", r == 0 and not os.path.exists(mk.hedefler()["goruntu"]))
    mk.kwin_surumu = lambda: ""
    ev = ortam_kur("kwinyok")
    r, _c = calistir(mk.main, [])
    kontrol("KWin sürümü bilinmiyor: görüntü izni yazılır (zararsız)", r == 0 and os.path.isfile(mk.hedefler()["goruntu"]))
    mk.kwin_surumu = lambda: "6.7.2"

    # ---------------------------------------------------------------- 4) yabancı dosya ve install.sh kurulumu
    print("4) yabancı dosya / install.sh kurulumu")
    ev = ortam_kur("yabanci")
    h = mk.hedefler()
    yaz(h["menu"], "[Desktop Entry]\nName=Başkasının\nExec=foo\n")
    r, cikti = calistir(mk.main, [])
    kontrol("imzasız yabancı menü girdisine dokunulmaz, kalanlar yazılır",
            r == 0 and oku(h["menu"]).endswith("Exec=foo\n") and os.path.isfile(h["acilis"]) and h["menu"] in cikti, cikti)

    ev = ortam_kur("installsh")
    h = mk.hedefler()
    yaz(h["menu"], "[Desktop Entry]\nExec=/home/x/.local/bin/deskhand panel\nX-Deskhand-Installed=true\n")
    r, cikti = calistir(mk.main, [])
    kontrol("install.sh girdisi varken: çıkış 1, hiçbir şey yazılmaz",
            r == 1 and not os.path.exists(h["acilis"]) and not os.path.exists(h["simge"])
            and oku(h["menu"]).startswith("[Desktop Entry]\nExec=/home/x"), cikti)
    kontrol("install.sh mesajı ne yapılacağını söyler", "install.sh" in cikti and "uninstall.sh" in cikti, cikti)
    r, cikti = calistir(mk.main, ["--remove"])
    kontrol("--remove install.sh girdisine dokunmaz", os.path.isfile(h["menu"]), cikti)

    ev = ortam_kur("sarmalayici")
    yaz(os.path.join(ev, ".local", "bin", "deskhand"), "#!/usr/bin/python3 -I\n# deskhand wrapper (install.sh)\n")
    r, cikti = calistir(mk.main, [])
    kontrol("install.sh sarmalayıcısı varken: çıkış 1, hiçbir şey yazılmaz",
            r == 1 and not os.path.exists(mk.hedefler()["menu"]), cikti)

    ev = ortam_kur("klon")
    mk._kaynak_kurulumu = lambda: True
    r, cikti = calistir(mk.main, [])
    kontrol("git klonundan çalışınca: çıkış 1, ./install.sh önerilir, hiçbir şey yazılmaz",
            r == 1 and "./install.sh" in cikti and not os.path.exists(mk.hedefler()["menu"]), cikti)
    mk._kaynak_kurulumu = lambda: False

    ev = ortam_kur("bulunamaz")
    mk._ice_aktarilabilir = lambda: False
    r, cikti = calistir(mk.main, [])
    kontrol("yorumlayıcı paketi kendi başına bulamıyorsa (PYTHONPATH/çalışma klasörü): çıkış 1, hiçbir şey yazılmaz",
            r == 1 and "pipx" in cikti and not os.path.exists(mk.hedefler()["menu"]), cikti)
    mk._ice_aktarilabilir = ESKI["ice"]
    kontrol("gerçek denetim: depo kökü / dışında sys.path'te değil → bulunamaz (False)", mk._ice_aktarilabilir() is False)
    mk._ice_aktarilabilir = lambda: True

    # ---------------------------------------------------------------- 5) --remove
    print("5) --remove")
    ev = ortam_kur("kaldir")
    h = mk.hedefler()
    calistir(mk.main, [])
    yaz(h["gorev"], "[Desktop Entry]\nName=Başkası\n")  # yabancı (imzasız) → kalır
    r, cikti = calistir(mk.main, ["--remove"])
    kontrol("--remove: imzalı girdiler ve simge silinir", r == 0 and not any(os.path.exists(h[a]) for a in
                                                                           ("menu", "acilis", "goruntu", "simge")), cikti)
    kontrol("--remove: imzasız dosya kalır", os.path.isfile(h["gorev"]), cikti)
    calistir(mk.main, [])
    with open(h["simge"], "a") as f:
        f.write("<!-- değişti -->")
    r, cikti = calistir(mk.main, ["--kaldir"])
    kontrol("--kaldir (TR): paketteki svg'den farklı simge silinmez", r == 0 and os.path.isfile(h["simge"])
            and not os.path.exists(h["menu"]), cikti)

    # ---------------------------------------------------------------- 6) CLI yönlendirmesi
    print("6) CLI")
    ev = ortam_kur("cli")
    r, cikti = calistir(cli.main, ["install-desktop"])
    kontrol("deskhand install-desktop → kurulum (çıkış 0)", r == 0 and os.path.isfile(mk.hedefler()["menu"]), cikti)
    r, cikti = calistir(cli.main, ["masaustu-kur", "--remove"])
    kontrol("deskhand masaustu-kur --remove (takma ad)", r == 0 and not os.path.exists(mk.hedefler()["menu"]), cikti)
    r, cikti = calistir(cli.main, ["install-desktop", "--bilinmeyen"])
    kontrol("bilinmeyen seçenek: çıkış 1", r == 1, cikti)
    kontrol("yardım metninde install-desktop (masaustu-kur)", "install-desktop (masaustu-kur)" in cli.yardim_metni())

    # ---------------------------------------------------------------- 7) doctor
    print("7) doctor")
    eski_dk = doktor._kaynak_kurulumu
    eski_ocr = ocr_gpu.eksikler
    try:
        doktor._kaynak_kurulumu = lambda: True
        kontrol("doctor (git klonu): masaüstü satırı yok (install.sh yazar)", doktor.satir_masaustu() is None)
        doktor._kaynak_kurulumu = lambda: False
        ev = ortam_kur("doktor")
        s = doktor.satir_masaustu()
        kontrol("doctor (pipx, girdi yok): uyarı → deskhand install-desktop",
                s["durum"] == "uyari" and s["oneri"] == "deskhand install-desktop", str(s))
        calistir(mk.main, ["--no-autostart"])
        s = doktor.satir_masaustu()
        kontrol("doctor (pipx, açılış yok): uyarı → deskhand install-desktop",
                s["durum"] == "uyari" and "deskhand install-desktop" in s["oneri"], str(s))
        calistir(mk.main, [])
        s = doktor.satir_masaustu()
        kontrol("doctor (pipx, kurulu): tamam", s["durum"] == "tamam", str(s))
        kontrol("doctor topla() satırı içerir", any(x["ad"] == s["ad"] for x in doktor.topla()))

        ocr_gpu.eksikler = lambda: ["python", "model"]
        s = doktor.satir_gpu_ocr()
        kontrol("GPU OCR (pipx): install.sh yok; ocr-venv + easyocr + model komutları",
                "install.sh" not in s["oneri"] and "-m venv --system-site-packages" in s["oneri"]
                and "pip install --no-deps easyocr python-bidi" in s["oneri"]
                and "-m deskhand.ocr_gpu indir" in s["oneri"] and ocr_gpu.venv_dizin() in s["oneri"], s["oneri"])
        ocr_gpu.eksikler = lambda: ["model"]
        s = doktor.satir_gpu_ocr()
        kontrol("GPU OCR (pipx, yalnız model): yalnız indirme komutu",
                "indir" in s["oneri"] and "pip install" not in s["oneri"], s["oneri"])
        doktor._kaynak_kurulumu = lambda: True
        s = doktor.satir_gpu_ocr()
        kontrol("GPU OCR (git klonu): ./install.sh", "./install.sh" in s["oneri"], s["oneri"])
    finally:
        doktor._kaynak_kurulumu = eski_dk
        ocr_gpu.eksikler = eski_ocr
finally:
    mk._kaynak_kurulumu, mk.kwin_surumu, mk._sycoca, mk._kullanici_sitesi, mk._ice_aktarilabilir = (
        ESKI[k] for k in ("kaynak", "kwin", "sycoca", "site", "ice"))
    for k, v in ESKI_ORTAM.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(KOK, ignore_errors=True)

print(f"\n{gecen}/{toplam} masaüstü kurulum testi geçti")
sys.exit(0 if gecen == toplam else 1)
