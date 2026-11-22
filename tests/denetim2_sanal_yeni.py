"""DENETİM 2 (yalnız Xvfb): tur3'te MCP-yalnız ajan için kalan yollar.
 A) open_app("dolphin") → F4 (gömülü Konsole) → type_text "touch <işaret>\\n": kabuksuz ajan kabuk komutu çalıştırır;
    Enter kapısı / uçbirim komut denetimi pencere sınıfına (org.kde.dolphin) bakar, gömülü uçbirimi görmez.
 B) erisim._surec_akrabasi: AT-SPI'siz bir pencerenin eylemi ATASI olan başka bir uygulamanın çerçevesine gider.
Çalıştır: python3 tests/denetim2_sanal_yeni.py"""
import atexit
import os
import subprocess
import sys
import time

import _yalitim

from deskhand import masaustu, mcp_sunucu

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
G, KOK = _yalitim.GECICI, _yalitim.KOK


def rapor(ad, acik, ek=""):
    print(f"{'AÇIK ' if acik else 'sağlam'}  {ad}" + (f"  ({ek})" if ek else ""), flush=True)


def hata_al(f, *a, **k):
    try:
        return f(*a, **k), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:300]


def oku(yol):
    try:
        return open(yol).read().splitlines()
    except OSError:
        return []


d = masaustu.masaustu_baslat()
print("masaüstü", d["ekran"])

# ---------------------------------------------------------------- A) Dolphin F4
isaret = os.path.join(G, "kabuk-calisti")
r, h = hata_al(mcp_sunucu.open_app, app="dolphin", args=[G], wait_s=25, desktop="background")
print("open_app:", r, h)
if r and r.get("window"):
    w = r["window"]["id"]
    time.sleep(2)
    print("F4:", hata_al(mcp_sunucu.press_key, window=w, keys="F4", verify=False, desktop="background"))
    time.sleep(3)
    print("yaz:", hata_al(mcp_sunucu.type_text, window=w, text=f"touch {isaret}\n", desktop="background"))
    for _i in range(20):
        if os.path.exists(isaret):
            break
        time.sleep(0.25)
    rapor("A MCP-yalnız ajan Dolphin'in gömülü uçbiriminde kabuk komutu çalıştırdı (onaysız)", os.path.exists(isaret))
else:
    rapor("A Dolphin başlatılamadı (sınanamadı)", False, h or str(r))

# ---------------------------------------------------------------- B) ata uygulamanın çerçevesi
LOG = os.path.join(G, "a11y.log")
SAR = os.path.join(G, "ebeveyn.py")
XPEN = os.path.join(G, "x_cocuk.py")
open(XPEN, "w").write("""import sys
from Xlib import X, display
d = display.Display(); s = d.screen()
w = s.root.create_window(600, 0, 600, 600, 0, s.root_depth, X.InputOutput, X.CopyFromParent,
                         background_pixel=s.white_pixel)
w.set_wm_name("Cocuk Notlar"); w.set_wm_class("cocuk", "Cocuk")
w.change_property(d.intern_atom("_NET_WM_PID"), d.intern_atom("CARDINAL"), 32, [__import__("os").getpid()])
w.map(); d.flush()
while True:
    d.next_event()
""")
# Qt a11y uygulaması (a11y_pencere) önce AT-SPI'siz çocuğu başlatır, sonra kendisi olur (exec yok: aynı süreç)
open(SAR, "w").write(f"""import subprocess, sys, runpy
subprocess.Popen([sys.executable, {XPEN!r}])
runpy.run_path({os.path.join(KOK, 'tests/yardimci/a11y_pencere.py')!r}, run_name="__main__")
""")
masaustu.baslat([sys.executable, SAR], {"LOG": LOG, "PENCERE_BASLIK": "Ebeveyn Uygulama"})
for _i in range(60):
    if "hazir" in oku(LOG):
        break
    time.sleep(0.25)
time.sleep(2)


def cli(*argv):
    p = subprocess.run([sys.executable, "-m", "deskhand", "--arka", *argv], capture_output=True, text=True, timeout=60,
                       cwd=KOK)
    return p.returncode, (p.stdout + p.stderr).strip()


for _i in range(20):
    k_, c_ = cli("tree", "Ebeveyn Uygulama", "--all")
    if "Onayla" in c_:
        break
    time.sleep(0.5)
n0 = len(oku(LOG))
k_, c_ = cli("click-element", "Cocuk Notlar", "Onayla", "--action")
time.sleep(0.4)
rapor("B 'Cocuk Notlar' penceresine istenen AT-SPI eylemi ATA uygulamanın ('Ebeveyn Uygulama') onay kutusunu değiştirdi",
      "isaret:Onayla:1" in oku(LOG)[n0:], f"kod {k_} {c_[-200:]}")
masaustu.masaustu_durdur()
