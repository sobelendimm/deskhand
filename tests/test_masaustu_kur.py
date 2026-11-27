"""`deskhand install-desktop` (masaustu_kur): pip/pipx kurulumunda menü girdisi, simge, oturum açılışında panel ve KWin < 6.8
ekran görüntüsü izni; `--remove` yalnız kendi (imzalı) dosyalarını siler; install.sh kurulumu (git klonu) bozulmaz.
doctor: pip/pipx'te eksik menü/autostart için `deskhand install-desktop`, GPU OCR için ocr-venv komutları.

Bütün yazımlar geçici HOME / XDG_DATA_HOME / XDG_CONFIG_HOME altında (gerçek ~/.local/share'e yazılmaz); kbuildsycoca6
çağrısı sahtelenir; KWin sürümü enjekte edilir.

Çalıştır:  python3 tests/test_masaustu_kur.py"""
import contextlib
import io
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading

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
    kapali = oku(h["acilis"]) if os.path.isfile(h["acilis"]) else ""
    kontrol("--no-autostart: tercih kalıcı (imzalı Hidden=true açılış girdisi), menü kalır",
            r == 0 and "\nHidden=true\n" in kapali and mk.IMZA in kapali and os.path.isfile(h["menu"])
            and mk.acilis_kapali(h["acilis"]), cikti + kapali)
    r, cikti = calistir(mk.main, [])
    kontrol("sonraki install-desktop (seçeneksiz) tercihe uyar: açılış girdisi kapalı kalır",
            r == 0 and mk.acilis_kapali(h["acilis"]), cikti)
    r, cikti = calistir(mk.main, ["--autostart"])
    kontrol("--autostart: açılış yeniden açılır", r == 0 and os.path.isfile(h["acilis"])
            and not mk.acilis_kapali(h["acilis"]) and "Hidden=" not in oku(h["acilis"]), cikti)
    r, _c = calistir(mk.main, ["--acilissiz"])
    kontrol("Türkçe takma ad --acilissiz", r == 0 and mk.acilis_kapali(h["acilis"]))
    r, _c = calistir(mk.main, ["--acilisli"])
    kontrol("Türkçe takma ad --acilisli", r == 0 and not mk.acilis_kapali(h["acilis"]))
    r, cikti = calistir(mk.main, ["--autostart", "--no-autostart"])
    kontrol("--autostart ile --no-autostart birlikte: kullanım hatası", r not in (0, None), cikti)
    ev = ortam_kur("kapali-kaldir")
    calistir(mk.main, ["--no-autostart"])
    r, cikti = calistir(mk.main, ["--remove"])
    kontrol("--remove kapalı (imzalı) açılış girdisini de siler", r == 0 and not os.path.exists(mk.hedefler()["acilis"]),
            cikti)
    ev = ortam_kur("kapali-yabanci")
    h2 = mk.hedefler()
    yaz(h2["acilis"], "[Desktop Entry]\nName=Benim\nExec=foo\n")
    r, cikti = calistir(mk.main, ["--no-autostart"])
    kontrol("--no-autostart yabancı açılış girdisine dokunmaz", r == 0 and oku(h2["acilis"]).endswith("Exec=foo\n"), cikti)
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

    # ---------------------------------------------------------------- 4b) simge, symlink, FIFO, tuhaf yol
    print("4b) yabancı simge / symlink / FIFO / tuhaf yol")
    ev = ortam_kur("yabanci-simge")
    h = mk.hedefler()
    yaz(h["simge"], "<svg>MY OWN ICON</svg>")
    r, cikti = calistir(mk.main, [])
    kontrol("paketteki svg'den farklı simge ezilmez, uyarılır (kaldir ile tutarlı)",
            r == 0 and oku(h["simge"]) == "<svg>MY OWN ICON</svg>" and h["simge"] in cikti
            and os.path.isfile(h["menu"]), cikti)

    ev = ortam_kur("symlink")
    h = mk.hedefler()
    dis = os.path.join(ev, "dis.desktop")
    yaz(dis, "[Desktop Entry]\nName=Dış\nExec=foo\n")
    os.makedirs(os.path.dirname(h["menu"]), exist_ok=True)
    os.symlink(dis, h["menu"])
    os.symlink(os.path.join(ev, "olmayan"), h["gorev"])  # kırık bağ
    r, cikti = calistir(mk.main, [])
    kontrol("symlink (imzasız hedef): bağ ve hedefi dokunulmaz", r == 0 and os.path.islink(h["menu"])
            and oku(dis).endswith("Exec=foo\n"), cikti)
    kontrol("kırık symlink: dokunulmaz", os.path.islink(h["gorev"]) and not os.path.exists(h["gorev"]), cikti)
    r, cikti = calistir(mk.main, ["--remove"])
    kontrol("--remove symlink'e ve hedefine dokunmaz", os.path.islink(h["menu"]) and os.path.isfile(dis), cikti)

    ev = ortam_kur("fifo")
    h = mk.hedefler()
    os.makedirs(os.path.dirname(h["acilis"]), exist_ok=True)
    os.mkfifo(h["acilis"])
    sonuc = []
    t = threading.Thread(target=lambda: sonuc.append(mk.durum(h["acilis"])), daemon=True)
    t.start()
    t.join(5)
    kontrol("durum(): FIFO'da bloklanmaz, yabancı sayılır", not t.is_alive() and sonuc == ["yabanci"], str(sonuc))
    sonuc.clear()
    t = threading.Thread(target=lambda: sonuc.append(mk.acilis_kapali(h["acilis"])), daemon=True)
    t.start()
    t.join(5)
    kontrol("acilis_kapali(): FIFO'da bloklanmaz", not t.is_alive() and sonuc == [False], str(sonuc))

    def exec_coz(deger):
        """Masaüstü girdisi okuyucusu gibi: önce string değer kaçışları, sonra Exec tırnak kuralları, sonra %%."""
        d, i = "", 0
        while i < len(deger):
            c = deger[i]
            if c == "\\" and i + 1 < len(deger):
                d += {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(deger[i + 1], "\\" + deger[i + 1])
                i += 2
                continue
            d += c
            i += 1
        if d.startswith('"'):
            assert d.endswith('"')
            ic, s, i = d[1:-1], "", 0
            while i < len(ic):
                if ic[i] == "\\" and i + 1 < len(ic) and ic[i + 1] in '"`$\\':
                    s += ic[i + 1]
                    i += 2
                    continue
                s += ic[i]
                i += 1
            d = s
        return d.replace("%%", "%")

    for yol in ('/a b/py', '/x$y"z`w\\v', "/yüz %f/ş", "/a'b;c|d#e~f>g", "/çok  boşluk/\\\\iki"):
        kontrol(f"tuhaf yol gidiş-dönüş: {yol!r}", exec_coz(mk.exec_kacis(yol)) == yol, mk.exec_kacis(yol))

    ev = ortam_kur("vekil")
    asil_py = sys.executable
    sys.executable = "/opt/py\udcff/bin/python3"  # geçersiz UTF-8 (surrogateescape) yol
    try:
        r, cikti = calistir(mk.main, [])
    finally:
        sys.executable = asil_py
    kontrol("geçersiz UTF-8 yorumlayıcı yolu: temiz hata (çıkış 1, traceback yok), hiçbir şey yazılmaz",
            r == 1 and "Traceback" not in cikti and not os.path.exists(mk.hedefler()["menu"]), cikti)

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
    satirlar = cli.yardim_metni().splitlines()
    i = next(i for i, s in enumerate(satirlar) if "install-desktop (masaustu-kur)" in s)
    kontrol("yardım hizası: install-desktop satırı seçeneklerle biter, açıklama 42. sütundan sürer",
            satirlar[i].rstrip().endswith("]") and satirlar[i + 1].startswith(" " * 42)
            and not satirlar[i + 1].startswith(" " * 43), "\n".join(satirlar[i:i + 3]))

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
        calistir(mk.main, [])
        os.unlink(mk.hedefler()["acilis"])
        s = doktor.satir_masaustu()
        kontrol("doctor (pipx, açılış yok): uyarı → deskhand install-desktop",
                s["durum"] == "uyari" and "deskhand install-desktop" in s["oneri"], str(s))
        calistir(mk.main, ["--no-autostart"])
        s = doktor.satir_masaustu()
        kontrol("doctor (pipx, --no-autostart seçilmiş): uyarı yok (tercih kalıcı), ayrıntıda kapalı",
                s["durum"] == "tamam" and "--autostart" in s["ayrinti"], str(s))
        calistir(mk.main, ["--autostart"])
        s = doktor.satir_masaustu()
        kontrol("doctor (pipx, kurulu): tamam", s["durum"] == "tamam", str(s))
        kontrol("doctor topla() satırı içerir", any(x["ad"] == s["ad"] for x in doktor.topla()))

        ocr_gpu.eksikler = lambda: ["python", "model"]
        s = doktor.satir_gpu_ocr()
        kontrol("GPU OCR (pipx): install.sh yok; ocr-venv + easyocr + model komutları",
                "install.sh" not in s["oneri"] and "-m venv --system-site-packages" in s["oneri"]
                and "pip install --no-deps easyocr python-bidi" in s["oneri"]
                and "indir" in s["oneri"] and ocr_gpu.venv_dizin() in s["oneri"], s["oneri"])
        kontrol("GPU OCR (pipx): venv sistemin (dağıtımın) python3'ü ile kurulur (install.sh PY gibi; pyenv/uv değil)",
                s["oneri"].startswith(shlex.join([doktor._sistem_python(), "-m", "venv"]))
                and doktor._sistem_python() == (shutil.which("python3", path=os.defpath) or doktor._sistem_python()),
                s["oneri"])
        eski_bp = sys.base_prefix
        try:
            sahte = os.path.join(KOK, "uv-python")
            yaz(os.path.join(sahte, "bin", "python3"), "")
            sys.base_prefix = sahte
            kontrol("uv/pyenv base_prefix'i dağıtım python3'ünün önüne geçmez",
                    not doktor._sistem_python().startswith(sahte) or not shutil.which("python3", path=os.defpath),
                    doktor._sistem_python())
        finally:
            sys.base_prefix = eski_bp
        ocr_gpu.eksikler = lambda: ["model"]
        s = doktor.satir_gpu_ocr()
        parca = shlex.split(s["oneri"])
        kontrol("GPU OCR indirme: cd yok, yorumlayıcı -I ile (çalışma klasörü/PYTHON* yola girmez)",
                "cd" not in parca and "&&" not in parca and parca[0] == os.path.join(ocr_gpu.venv_dizin(), "bin", "python")
                and parca[1] == "-I" and parca[2] == "-c" and parca[-1] == ocr_gpu.model_dizin(), s["oneri"])
        # komutu bu yorumlayıcıyla, gölgeleyici sahte deskhand içeren bir çalışma klasöründe dene: gerçek paket yüklenir,
        # paketin üst klasörü (site-packages) sys.path'e girmez
        tuzak = os.path.join(KOK, "tuzak")
        yaz(os.path.join(tuzak, "deskhand", "__init__.py"), "raise SystemExit('golge')\n")
        kod = parca[3].replace("ocr_gpu.indir(sys.argv[1])",
                               "print(ocr_gpu.__file__); print(any(os.path.realpath(p) == os.path.realpath("
                               f"{os.path.dirname(yollar.PAKET_DIZIN)!r}) for p in sys.path))")
        kod = "import os\n" + kod
        r =subprocess.run([sys.executable, "-I", "-c", kod, ocr_gpu.model_dizin()], cwd=tuzak, capture_output=True,
                           text=True, timeout=60)
        cikti = r.stdout.splitlines()
        kontrol("indirme kodu: gerçek deskhand.ocr_gpu yüklenir, site-packages yola eklenmez",
                r.returncode == 0 and cikti[:1] == [os.path.realpath(ocr_gpu.__file__)] and cikti[1:2] == ["False"],
                r.stdout + r.stderr)
        sahte_on = os.path.join(KOK, "venv-on")
        yaz(os.path.join(sahte_on, "pyvenv.cfg"), "home = /x\n")
        os.symlink(sahte_on, sahte_on + "-bag")
        eski_p = sys.prefix, sys.base_prefix
        try:
            sys.prefix = sys.base_prefix = sahte_on
            kontrol("sanal ortam: pyvenv.cfg varsa base_prefix eşit olsa da venv", doktor._sanal_ortam())
            bos = os.path.join(KOK, "duz-python")
            os.makedirs(bos)
            os.symlink(bos, bos + "-bag")
            sys.prefix, sys.base_prefix = bos + "-bag", bos
            kontrol("sanal ortam: prefix base_prefix'e bağ (pyenv) → venv değil", not doktor._sanal_ortam())
        finally:
            sys.prefix, sys.base_prefix = eski_p
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
