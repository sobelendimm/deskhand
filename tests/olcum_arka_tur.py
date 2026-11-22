"""Arka plan masaüstü türlerinin (KWin / Xvfb) ölçümü — karar verisi (Faz 12b). Test değil, ölçüm betiği.

    DESKHAND_ARKA_TUR=kwin python3 tests/olcum_arka_tur.py [--bosta SN] [--firefox]
    DESKHAND_ARKA_TUR=xvfb python3 tests/olcum_arka_tur.py [--bosta SN] [--firefox]

Ölçülen: açılış, boş bellek (kafes memory.current), tık / yazı / ekran görüntüsü / pencere listesi süreleri, MCP
click(text=…) uçtan uca, Firefox (BOŞ geçici profil + oturum köprüsüyle aynı yalıtım: XDG_CONFIG_HOME, MOZ_LEGACY_PROFILES,
profil grubu/yedekleme kapalı user.js; kullanıcının profili/Firefox'u kullanılmaz) açılışı ve yerel WebGL sayfasından
oluşturucu adı, isteğe bağlı boşta bellek (--bosta 600 = 10 dk). Sonuç JSON olarak stdout'un son satırında.
Kullanıcının gerçek ekranına girdi gitmez; gerçek profiles.ini/installs.ini sha1 önce/sonra karşılaştırılır."""
import asyncio
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time

import _yalitim  # noqa: F401

from deskhand import masaustu  # noqa: E402
from deskhand.arka_uc import EKRAN, sec  # noqa: E402

KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
PENCERE = os.path.join(KOK, "tests", "yardimci", "kwin_test_pencere.py")
BOSTA = int(sys.argv[sys.argv.index("--bosta") + 1]) if "--bosta" in sys.argv else 0
FIREFOX = "--firefox" in sys.argv
sonuc = {"tur_istenen": os.environ.get("DESKHAND_ARKA_TUR", "")}


def bekle(kosul, sure=10.0, aralik=0.01):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


def sha1(yol):
    try:
        with open(os.path.expanduser(yol), "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def kafes_bellek(d):
    try:
        with open(os.path.join("/sys/fs/cgroup", d["cgroup"].lstrip("/"), "memory.current")) as f:
            return round(int(f.read()) / 2 ** 20, 1)
    except (OSError, ValueError, KeyError):
        return None


def medyan(liste):
    return round(statistics.median(liste), 2) if liste else None


FF_DOSYALAR = ("~/.config/mozilla/firefox/profiles.ini", "~/.config/mozilla/firefox/installs.ini")
ff0 = {y: sha1(y) for y in FF_DOSYALAR}

t = time.monotonic()
d = masaustu.masaustu_baslat()
sonuc["tur"] = masaustu.tur(d)
sonuc["acilis_sn"] = round(time.monotonic() - t, 2)
sonuc["gpu"] = d.get("gpu") or ("yok (Xvfb: yazılım)" if sonuc["tur"] == "xvfb" else "?")
time.sleep(2)
sonuc["bos_bellek_mib"] = kafes_bellek(d)
au = sec(arka_bayragi=True)
LOG = os.path.join(GECICI, "olcum.log")


def loglar():
    try:
        with open(LOG, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


au.baslat([sys.executable, PENCERE], {"LOG": LOG, "BASLIK": "olcum ANA"})
k = bekle(lambda: next((w for w, b, _ in au.pencereler("olcum ANA")), None), 20, 0.05)
bekle(lambda: "hazir" in loglar(), 10)
time.sleep(0.5)
if sonuc["tur"] == "kwin":  # GPU kanıtı: KWin'in ve Wayland istemcisinin (dmabuf geri bildirimi) kullandığı aygıt
    from deskhand import kwin_oturum
    sonuc["kwin_gpu_pci"] = kwin_oturum.surec_gpu_pci(d["pid"]["kwin"])
    sonuc["qt_istemci_gpu_pci"] = kwin_oturum.surec_gpu_pci(au.pid(k))

# ekran görüntüsü + pencere listesi
s = []
for _ in range(15):
    t = time.perf_counter()
    im = au.goruntu()
    s.append((time.perf_counter() - t) * 1000)
sonuc["goruntu_ms"] = medyan(s)
s = []
for _ in range(10):
    t = time.perf_counter()
    au.pencereler()
    s.append((time.perf_counter() - t) * 1000)
sonuc["pencere_listesi_ms"] = medyan(s)

# düğmenin yeri (eflatun kutu)
import numpy as np  # noqa: E402
a = np.asarray(au.goruntu()).astype(int)
mk = (abs(a[:, :, 0] - 255) <= 6) & (a[:, :, 1] <= 6) & (abs(a[:, :, 2] - 255) <= 6)
ys, xs = np.nonzero(mk)
W, H = au.ekran_alani()[2:]
cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
mk = (a[:, :, 0] <= 6) & (abs(a[:, :, 1] - 255) <= 6) & (abs(a[:, :, 2] - 255) <= 6)
ys2, xs2 = np.nonzero(mk)
kx, ky = (xs2.min() + xs2.max()) / 2, (ys2.min() + ys2.max()) / 2

g = au.girdi("olcum", denetle=lambda k_, d_: None)
s = []
for _ in range(10):
    n0 = loglar().count("tik: Kaydet")
    t = time.perf_counter()
    g.gonder(k, None, f"mouseto {(cx + .5) / W:.6f} {(cy + .5) / H:.6f}", "click left")
    t1 = time.perf_counter()
    bekle(lambda: loglar().count("tik: Kaydet") > n0, 3, 0.002)
    s.append(((time.perf_counter() - t) * 1000, (t1 - t) * 1000))
sonuc["tik_gonder_ms"] = medyan([x[1] for x in s])
sonuc["tik_uygulamaya_ms"] = medyan([x[0] for x in s])
g.gonder(k, None, f"mouseto {(kx + .5) / W:.6f} {(ky + .5) / H:.6f}", "click left")
s = []
for i in range(5):
    g.gonder(k, None, "key ctrl+a", "key backspace")
    metin = "abcdefghijklmnopqrst"
    t = time.perf_counter()
    g.gonder(k, None, f"type {metin}")
    t1 = time.perf_counter()
    bekle(lambda: any(l == "yazi=" + metin for l in loglar()[-3:]), 3, 0.002)
    s.append(((time.perf_counter() - t) * 1000, (t1 - t) * 1000))
sonuc["yazi20_gonder_ms"] = medyan([x[1] for x in s])
sonuc["yazi20_uygulamaya_ms"] = medyan([x[0] for x in s])
g.kapat()


# MCP click(text=…) uçtan uca (süreç içi istemci; OCR + doğrulama dahil)
async def mcp_olc():
    from mcp import Client

    from deskhand import mcp_sunucu as ms
    sureler = []
    async with Client(ms.mcp) as c:
        for _ in range(3):
            n0 = loglar().count("tik: Kaydet")
            t = time.perf_counter()
            r = await c.call_tool("click", {"window": "olcum ANA", "text": "Kaydet", "desktop": "background"})
            sureler.append((time.perf_counter() - t) * 1000)
            if r.is_error or not bekle(lambda: loglar().count("tik: Kaydet") > n0, 3):
                return None, "".join(getattr(x, "text", "") for x in r.content)[:200]
    return medyan(sureler), ""
sonuc["mcp_click_text_ms"], hata_ = asyncio.run(mcp_olc())
if hata_:
    sonuc["mcp_hata"] = hata_
sonuc["bellek_qt_penceresiyle_mib"] = kafes_bellek(d)

# Firefox: boş geçici profil + oturum köprüsüyle aynı yalıtım
if FIREFOX and subprocess.run(["which", "firefox"], capture_output=True).returncode == 0:
    from deskhand.oturum import firefox as ff
    prof = os.path.join(GECICI, "ff-profil")
    xdg = os.path.join(prof, ".xdg-config")
    os.makedirs(xdg, mode=0o700)
    with open(os.path.join(prof, "user.js"), "w") as f:
        f.write(ff._USER_JS)
    sayfa = os.path.join(GECICI, "webgl.html")
    with open(sayfa, "w") as f:
        f.write("""<!doctype html><html><head><title>WEBGL bekliyor</title></head><body><canvas id=c></canvas><script>
var gl = document.getElementById('c').getContext('webgl'); var r = 'YOK';
if (gl) { var e = gl.getExtension('WEBGL_debug_renderer_info');
  r = e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER); }
document.title = 'WEBGL ' + r;</script></body></html>""")
    env = {"XDG_CONFIG_HOME": xdg, "MOZ_LEGACY_PROFILES": "1", "XDG_CACHE_HOME": os.path.join(prof, ".cache")}
    t = time.monotonic()
    pf = au.baslat(["firefox", "--profile", prof, "--no-remote", "--new-instance", f"file://{sayfa}"], env)
    w = bekle(lambda: next(((k_, b) for k_, b, _ in au.pencereler("WEBGL") if "bekliyor" not in b), None), 60, 0.05)
    sonuc["firefox_acilis_sn"] = round(time.monotonic() - t, 2) if w else None
    sonuc["firefox_webgl"] = w[1] if w else "pencere açılmadı"
    time.sleep(3)
    sonuc["bellek_firefox_ile_mib"] = kafes_bellek(d)
    if BOSTA:
        ornek = []
        bitis = time.monotonic() + BOSTA
        while time.monotonic() < bitis:
            time.sleep(30)
            ornek.append(kafes_bellek(d))
        sonuc["bosta_bellek_mib (ilk/son/tepe)"] = (ornek[0], ornek[-1], max(ornek)) if ornek else None
    try:
        au.kapat(w[0]) if w else None
        pf.wait(10)
    except Exception:  # noqa: BLE001
        pass
elif BOSTA:
    time.sleep(BOSTA)
    sonuc["bosta_bellek_mib"] = kafes_bellek(d)

masaustu.masaustu_durdur()
sonuc["firefox_profil_dosyalari_degismedi"] = all(sha1(y) == ff0[y] for y in FF_DOSYALAR)
print(json.dumps(sonuc, ensure_ascii=False))
