"""Bağımsız güvenlik denetiminin MCP bulguları (docs/denetim/denetim_sanal.py 1a/1b/1c, 4a/4b) — REGRESYON testi:
her saldırı artık BAŞARISIZ olmalı; meşru kullanım çalışmalı. Kullanıcının gerçek ekranına/panosuna girdi yok
(yalnız görünmez masaüstü, Xvfb); gerçek uygulama başlatılmaz (sistemdeki .desktop girdileri yalnız OKUNUR);
gerçek ~/.config yazılmaz (_yalitim).

 A) open_app doğrulaması (ekransız): yalnız kurulu .desktop girdisi; yorumlayıcı/kabuk/sarmalayıcı/uçbirim girdisi
    ve belge olmayan argüman → 10. Meşru: firefox + https URL, kate + var olan dosya.
 B) 1a/1b/1c: open_app(python3 -c KOD) MCP'den → [10], kod ÇALIŞMAZ (yasak listesi silinmez, ortam dökülmez).
 C) 4a: onay beklerken AYNI masaüstüne girdi araçları (press_key, type_text, scroll, drag, manage_window, clipboard
    write, open_app, run_flow) beklemeden [7] "onay bekleniyor"; okuma araçları serbest. Hedef değişmediği için
    onaylanan tıklama yapılır ("Ürün A").
 D) 4b: onay beklerken sayfa BAŞKA yoldan değişti → onaydan sonra hedef yeniden doğrulanır → [10] "yeniden onay
    gerekir", hiçbir şey tıklanmaz (ne A ne B).

Çalıştır: python3 tests/test_denetim_mcp.py"""
import atexit
import json
import os
import sys
import threading
import time

import _yalitim

from deskhand import masaustu, mcp_sunucu, onay, uygulama, yollar
from deskhand.hata import Dur

G = _yalitim.GECICI
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def hata_al(f, *a, **k):
    try:
        return f(*a, **k), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def kod_al(f, *a, **k):
    try:
        f(*a, **k)
        return 0
    except Dur as e:
        return e.kod


def bekle(kosul, sure=20, adim=0.1):
    t = time.monotonic() + sure
    while time.monotonic() < t:
        if kosul():
            return True
        time.sleep(adim)
    return False


def oku(yol):
    try:
        with open(yol) as f:
            return f.read().splitlines()
    except OSError:
        return []


# ================================================================ A) open_app doğrulaması (ekransız)
UYG = os.path.join(G, "uygulamalar")
os.makedirs(UYG, exist_ok=True)
GIRDILER = {  # kimlik: (Name, Exec, ek satırlar)
    "python3": ("Python (v3)", "python3", ""),
    "py-yol": ("Python yol", "/usr/bin/python3.12 -i", ""),
    "org.kde.konsole": ("Konsole", "konsole", "Categories=Qt;KDE;System;TerminalEmulator;\n"),
    "kategori-ucbirim": ("Bir Uçbirim", "/usr/bin/benim-ucbirimim", "Categories=System;TerminalEmulator;\n"),
    "htop": ("Htop", "htop", "Terminal=true\n"),
    "env-sarili": ("Env Sarılı", "env FOO=1 /usr/bin/kate %U", ""),
    "nice-python": ("Nice Python", "nice -n 5 python3 /tmp/x.py", ""),
    "sh-c": ("Kabuk", "sh -c 'echo hi'", ""),
    "bash-yol": ("Bash Yol", "/usr/bin/bash", ""),
    "flatpak-bash": ("Flatpak Kabuk", "/usr/bin/flatpak run --command=bash org.example.App", ""),
    "flatpak-console": ("Konsol", "/usr/bin/flatpak run org.gnome.Console", ""),
    "flatpak-spawn": ("Spawn", "flatpak-spawn --host sh", ""),
    "deskhand-panel": ("Deskhand", "deskhand panel", ""),
    "wine-calistir": ("Wine", "wine start /unix %f", ""),
    "xdg": ("Aç", "xdg-open %u", ""),
    "pkexec-uyg": ("Yetkili", "pkexec /usr/bin/kate", ""),
    # meşru
    "firefox": ("Firefox", "/usr/lib/firefox/firefox %u", ""),
    "org.kde.kate": ("Kate", "kate -b %U", ""),
    "org.mozilla.firefox-flatpak": ("Firefox Flatpak", "/usr/bin/flatpak run --branch=stable --arch=x86_64 "
                                    "--command=firefox --file-forwarding org.mozilla.firefox @@u %u @@", ""),
    "oyun-gamemode": ("Oyun", "gamemoderun /opt/oyun/oyun.bin", ""),
}
for kimlik, (ad, ex, ek) in GIRDILER.items():
    with open(os.path.join(UYG, kimlik + ".desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={ad}\nExec={ex}\n{ek}")
eski_dizinler = uygulama.UYGULAMA_DIZINLERI
uygulama.UYGULAMA_DIZINLERI = (UYG,)
BELGE = os.path.join(G, "not.txt")
open(BELGE, "w").write("merhaba\n")
CALISIR = os.path.join(G, "betik.sh")
open(CALISIR, "w").write("#!/bin/sh\necho x\n")
os.chmod(CALISIR, 0o755)

for kimlik in ("python3", "py-yol", "org.kde.konsole", "kategori-ucbirim", "htop", "env-sarili", "nice-python", "sh-c",
               "bash-yol", "flatpak-bash", "flatpak-console", "flatpak-spawn", "deskhand-panel", "wine-calistir", "xdg",
               "pkexec-uyg"):
    kontrol(f"A: '{kimlik}' girdisi ({GIRDILER[kimlik][1]!r}) MCP'den başlatılamaz → 10",
            kod_al(uygulama.mcp_uygulama, kimlik) == 10)
for ad in ("/usr/bin/python3", sys.executable, "/bin/sh", "./python3", "~/bin/x"):
    kontrol(f"A: ham yol {ad!r} → 10 (yol/komut verilemez)", kod_al(uygulama.mcp_uygulama, ad) == 10)
for arg in (["-c", "print(1)"], ["--new-instance"], ["FOO=bar"], ["javascript:alert(1)"], ["data:text/html,x"],
            ["steam://run/1"], [f"file://{CALISIR}"], [CALISIR], ["not.txt"], [os.path.join(G, "yok.txt")],
            [os.path.join(UYG, "firefox.desktop")], ["https://ex.com/\nrm"], ["http://"], [" -c"], ["/usr/bin/python3"]):
    kontrol(f"A: firefox argümanı {arg!r} → 10", kod_al(uygulama.mcp_uygulama, "firefox", arg) == 10)
kontrol("A: en çok 16 argüman", kod_al(uygulama.mcp_uygulama, "firefox", ["https://a.b"] * 17) == 10)
g, b = uygulama.mcp_uygulama("firefox", ["https://example.com/ara?q=a=b&x=1", f"file://{BELGE}"])
kontrol("A: meşru firefox + https URL (= sorgu içinde) + file:// belge", g["kimlik"] == "firefox" and len(b) == 2)
g, b = uygulama.mcp_uygulama("kate", [BELGE, G])
kontrol("A: meşru kate + var olan dosya ve klasör", g["kimlik"] == "org.kde.kate" and b == [BELGE, G])
kontrol("A: Flatpak firefox (--command=firefox, @@u) başlatılabilir",
        kod_al(uygulama.mcp_uygulama, "org.mozilla.firefox-flatpak") == 0)
kontrol("A: gamemoderun sarmalı oyun başlatılabilir (geçirgen sarmalayıcı)", kod_al(uygulama.mcp_uygulama, "oyun") == 0)
from deskhand import api  # noqa: E402

argv, _ad, _y, _g = api.uygulama_komutu("kate", [BELGE])
kontrol("A: api.uygulama_komutu → gio launch GIRDI.desktop BELGE (ortam yok)",
        argv == ["gio", "launch", os.path.join(UYG, "org.kde.kate.desktop"), BELGE], str(argv))
uygulama.UYGULAMA_DIZINLERI = eski_dizinler

# sistemdeki gerçek girdiler (yalnız OKUNUR, başlatılmaz): yorumlayıcı/uçbirim olanlar reddedilir
gercek = uygulama.masaustu_girdileri()
from deskhand.oturum.cozum import exec_argv  # noqa: E402

tehlikeli = [x for x in gercek if exec_argv(x["exec"]) and (
    os.path.basename(exec_argv(x["exec"])[0]) in ("python3", "python", "konsole", "bash", "sh", "xterm", "ghostty")
    or "TerminalEmulator" in x["kategoriler"])]
kontrol(f"A: sistemdeki {len(tehlikeli)} yorumlayıcı/uçbirim girdisinin hepsi reddedilir (salt okuma)",
        all(uygulama.girdi_denetle(x) for x in tehlikeli), str([x["kimlik"] for x in tehlikeli
                                                              if not uygulama.girdi_denetle(x)]))
print("   örnek:", [x["kimlik"] for x in tehlikeli][:8])

# ================================================================ B) 1a/1b/1c: open_app → keyfi kod YOK
atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
d = masaustu.masaustu_baslat()
os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True)
with open(yollar.yasak_dosya(), "w") as f:
    f.write("GizliKasa\n")
dok = os.path.join(G, "ortam.txt")
kod = ("import os,json;open(os.environ['DESKHAND_CONFIG_DIR']+'/yasak-pencereler.txt','w').write('');"
       f"json.dump(dict(os.environ),open({dok!r},'w'))")
for app, args in ((sys.executable, ["-c", kod]), ("python3", ["-c", kod]), ("/bin/sh", ["-c", f"python3 -c \"{kod}\""]),
                  ("env", ["python3", "-c", kod])):
    _r, h = hata_al(mcp_sunucu.open_app, app=app, args=args, wait_s=2, desktop="background")
    kontrol(f"1a: open_app({app!r}, {args[0]!r}…) → [10] reddedildi", h is not None and "[10]" in h, h or "")
time.sleep(1.0)
kontrol("1a: yasak listesi SİLİNMEDİ (kod çalışmadı)", open(yollar.yasak_dosya()).read().strip() == "GizliKasa")
kontrol("1b/1c: arka plan uygulamasının ortamı dökülemedi (kod çalışmadı)", not os.path.exists(dok))

# ================================================================ C/D) 4a/4b: onay beklerken eşzamanlı girdi + hedef değişimi
YARDIM = os.path.join(G, "odeme_pencere.py")
LOG4 = os.path.join(G, "odeme.log")
TETIK = os.path.join(G, "sayfa-b")
with open(YARDIM, "w") as f:
    f.write('''import os, sys
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QPushButton, QStackedWidget
LOG, TETIK = os.environ["LOG"], os.environ["TETIK"]
def log(s):
    open(LOG, "a").write(s + "\\n")
app = QApplication(sys.argv)
w = QStackedWidget(); w.setWindowTitle("Ödeme — Kasa"); w.resize(500, 300)
for ad in ("Ürün A 1 TL", "Ürün B 999 TL"):
    b = QPushButton(ad); b.clicked.connect(lambda _=False, ad=ad: log("tikla:" + ad)); w.addWidget(b)
QShortcut(QKeySequence("N"), w, activated=lambda: (w.setCurrentIndex(1), log("sayfa:B")))
def tetik():  # sayfa MCP DIŞINDAN değişir (ör. sayfanın kendi betiği)
    if os.path.exists(TETIK) and w.currentIndex() == 0:
        w.setCurrentIndex(1); log("sayfa:B-dis")
QTimer(w, timeout=tetik, interval=50).start()
w.show(); log("hazir"); sys.exit(app.exec())
''')


def odeme_ac():
    open(LOG4, "w").close()
    try:
        os.remove(TETIK)
    except FileNotFoundError:
        pass
    p = masaustu.baslat([sys.executable, YARDIM], {"LOG": LOG4, "TETIK": TETIK})
    kontrol("4: ödeme penceresi hazır", bekle(lambda: "hazir" in oku(LOG4)))
    time.sleep(1.0)
    return p


gercek_iste_sonuc = onay.iste_sonuc
araya = {}


def sahte_onay_4a(eylem, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    """İnsan panelde "Ürün A" görüntüsünü inceliyor; bu sırada başka iş parçacıkları aynı masaüstüne girdi dener."""
    araya["goruntu"] = goruntu
    denemeler = {
        "press_key": lambda: mcp_sunucu.press_key(window="Ödeme", keys="n", verify=False, desktop="background"),
        "type_text": lambda: mcp_sunucu.type_text(window="Ödeme", text="x", desktop="background"),
        "scroll": lambda: mcp_sunucu.scroll(window="Ödeme", desktop="background"),
        "manage_window": lambda: mcp_sunucu.manage_window(window="Ödeme", action="move", x=10, y=10,
                                                          desktop="background"),
        "clipboard_write": lambda: mcp_sunucu.clipboard(action="write", text="x", desktop="background"),
        "click": lambda: mcp_sunucu.click(window="Ödeme", text="Ürün", verify=False, desktop="background"),
        "open_app": lambda: mcp_sunucu.open_app(app="firefox", desktop="background", wait_s=1),
        "run_flow": lambda: mcp_sunucu.run_flow(action="run", name="yok", window="Ödeme", desktop="background"),
        "screenshot": lambda: mcp_sunucu.screenshot(window="Ödeme", desktop="background"),
        "read_text": lambda: mcp_sunucu.read_text(window="Ödeme", desktop="background"),
        "get_status": lambda: mcp_sunucu.get_status(windows=True, desktop="background"),
    }
    sonuc = {}

    def is_(ad, f):
        t0 = time.monotonic()
        r, h = hata_al(f)
        sonuc[ad] = (h, time.monotonic() - t0)
    ipler = [threading.Thread(target=is_, args=(a, f)) for a, f in denemeler.items()]
    for t in ipler:
        t.start()
    for t in ipler:
        t.join(60)
    araya["sonuc"] = sonuc
    time.sleep(0.3)
    return onay.OnaySonucu(True, "izin")  # kullanıcı GÖRDÜĞÜ "Ürün A" için izin verdi


def sahte_onay_4b(eylem, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    open(TETIK, "w").close()  # insan "Ürün A"yı incelerken sayfa kendiliğinden B'ye geçer
    bekle(lambda: "sayfa:B-dis" in oku(LOG4), 5)
    time.sleep(0.3)
    return onay.OnaySonucu(True, "izin")


p4 = odeme_ac()
s = mcp_sunucu.screenshot(window="Ödeme", desktop="background").structured_content
onay.iste_sonuc = sahte_onay_4a
try:
    _r, h4 = hata_al(mcp_sunucu.click, window="Ödeme", x=250 * s["scale"], y=150 * s["scale"], shot_id=s["shot_id"],
                     verify=False, desktop="background")
finally:
    onay.iste_sonuc = gercek_iste_sonuc
time.sleep(0.5)
l4 = oku(LOG4)
sn = araya.get("sonuc", {})
for ad in ("press_key", "type_text", "scroll", "manage_window", "clipboard_write", "click", "open_app", "run_flow"):
    h, sure_ = sn.get(ad, ("yok", 0))
    kontrol(f"4a: onay beklerken {ad} → [7] 'onay bekleniyor' (beklemeden)", h is not None and "[7]" in h and
            "onay bekleniyor" in h and sure_ < 5, f"{h} {sure_:.1f} sn")
for ad in ("screenshot", "read_text", "get_status"):
    h, _s = sn.get(ad, ("yok", 0))
    kontrol(f"4a: onay beklerken okuma aracı {ad} serbest", h is None, str(h))
kontrol("4a: eşzamanlı press_key sayfayı DEĞİŞTİREMEDİ", "sayfa:B" not in l4, str(l4))
kontrol("4a: hedef değişmedi → onaylanan 'Ürün A' bir kez tıklandı", h4 is None and l4.count("tikla:Ürün A 1 TL") == 1
        and "tikla:Ürün B 999 TL" not in l4, f"{h4} {l4}")
kontrol("4a: onay sonrası kayıt kapandı (girdi kapısı açık)", not mcp_sunucu.onay_bekliyor_mu("sanal"))
p4.terminate()
p4.wait(5)
time.sleep(0.5)

p4 = odeme_ac()
s = mcp_sunucu.screenshot(window="Ödeme", desktop="background").structured_content
onay.iste_sonuc = sahte_onay_4b
try:
    _r, h4 = hata_al(mcp_sunucu.click, window="Ödeme", x=250 * s["scale"], y=150 * s["scale"], shot_id=s["shot_id"],
                     verify=False, desktop="background")
finally:
    onay.iste_sonuc = gercek_iste_sonuc
time.sleep(0.5)
l4 = oku(LOG4)
kontrol("4b: sayfa onay beklerken dışarıdan değişti (senaryo kuruldu)", "sayfa:B-dis" in l4, str(l4))
kontrol("4b: onaydan sonra hedef değişti → [10] 'yeniden onay gerekir'", h4 is not None and "[10]" in h4 and
        "yeniden onay" in h4, str(h4))
kontrol("4b: hiçbir ürün tıklanmadı (ne A ne 999 TL'lik B)", not [x for x in l4 if x.startswith("tikla:")], str(l4))
p4.terminate()
p4.wait(5)

# meşru: onay yokken ödeme dışı pencerede girdi araçları çalışır (kapı kapalı)
kontrol("kapı: bekleyen onay yokken girdi serbest", not mcp_sunucu.onay_bekliyor_mu("sanal") and
        not mcp_sunucu.onay_bekliyor_mu("kde"))

# küçük iş: ön ölçümsüz doğrulama (kde via='action') sabit 0,35 sn yerine ölçülmüş üst sınır
p4 = odeme_ac()
with api.hedef("sanal"):
    k4 = api.pencere("Ödeme")
    t0 = time.monotonic()
    r = mcp_sunucu._sonra(k4, None)
    sure_ = time.monotonic() - t0
kontrol("küçük: ön ölçümsüz _sonra en çok ~0,2 sn bekler (0,35 değil) ve başlığı döner",
        r.get("title") == "Ödeme — Kasa" and 0.15 <= sure_ < 0.3, f"{r} {sure_:.3f}")
p4.terminate()
p4.wait(5)

masaustu.masaustu_durdur()
print(f"\n{gecen}/{toplam} denetim (MCP) testi geçti")
sys.exit(0 if gecen == toplam else 1)
