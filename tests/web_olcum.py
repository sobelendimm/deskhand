"""Web ögesi okuma: A (erişilebilirlik ağacı, deskhand.web) ve B (Marionette uzaktan denetim protokolü) ÖLÇÜMÜ.

Karar için yalnız ölçüm betiği (test değil; her zaman 0 ile çıkar, Firefox yoksa atlar). Aynı yerel test sayfalarında
(tests/ornek/web/) iki yolun kapsaması, kutu uyuşması, gerçek tıklamayla koordinat doğruluğu, süreleri, iframe /
sonradan eklenen içerik / kaydırma davranışı; B için ayrıca sayfanın gördüğü navigator.webdriver, kapının başka bir
süreçten (aynı kullanıcı) sürülebilirliği ve azaltma önerilerinin etkisi. Firefox YALNIZ arka plan masaüstünde, yeni
boş geçici profille (tests/yardimci/web_tarayici.py); kullanıcının profil kökü önce/sonra karşılaştırılır (fark =
HEMEN dur). B'nin Marionette istemcisi YALNIZ bu betikte; Deskhand'e bağlı değil.

Çalıştır:  python3 tests/web_olcum.py   (JSON çıktı: DESKHAND_WEB_OLCUM=dosya.json)"""
import atexit
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

import _yalitim  # noqa: F401

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
import web_tarayici as wt  # noqa: E402

if not (shutil.which("firefox") and shutil.which("Xvfb")):
    print("atlandı: firefox ya da Xvfb yok")
    sys.exit(0)

from deskhand import masaustu, web  # noqa: E402
from deskhand.arka_uc import sec  # noqa: E402

# B: sayfadaki etkileşimli ögeler (JS). Ad: aria-label > aria-labelledby > <label> > title > placeholder > metin > alt.
# Rol AT-SPI adına çevrilir ki iki yol aynı ölçütle karşılaştırılsın. Koordinat: mozInnerScreenX/Y (görüş alanının
# EKRAN konumu, CSS px; Xvfb'de devicePixelRatio 1) + getBoundingClientRect.
B_JS = r"""
const SEC = 'a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],' +
            '[role=menuitem],[role=checkbox],[role=radio],[role=combobox],[contenteditable=""],[contenteditable=true]';
function ad(e) {
  let a = e.getAttribute('aria-label');
  if (a) return a.trim();
  const lb = e.getAttribute('aria-labelledby');
  if (lb) return lb.split(/\s+/).map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim();
  if (e.labels && e.labels.length) return Array.from(e.labels).map(l => l.textContent).join(' ').trim();
  if (e.title) return e.title.trim();
  if (e.placeholder) return e.placeholder.trim();
  const t = (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  if (t) return t;
  const img = e.querySelector && e.querySelector('img[alt]');
  return img ? img.alt.trim() : (e.value || '');
}
function rol(e) {
  const r = e.getAttribute('role');
  if (r === 'tab') return 'page tab';
  if (r === 'menuitem') return 'menu item';
  if (r === 'checkbox') return 'check box';
  if (r === 'radio') return 'radio button';
  if (r === 'button') return 'button';
  if (r === 'link') return 'link';
  if (r === 'combobox') return 'combo box';
  const t = e.tagName.toLowerCase();
  if (t === 'a') return 'link';
  if (t === 'button') return 'button';
  if (t === 'select') return 'combo box';
  if (t === 'textarea') return 'entry';
  if (t === 'input') {
    const y = (e.type || 'text').toLowerCase();
    if (y === 'checkbox') return 'check box';
    if (y === 'radio') return 'radio button';
    if (y === 'password') return 'password text';
    if (y === 'number') return 'spin button';
    if (['button', 'submit', 'reset', 'image'].includes(y)) return 'button';
    return 'entry';
  }
  return 'entry';
}
const vx = window.mozInnerScreenX, vy = window.mozInnerScreenY;
const W = document.documentElement.clientWidth, H = document.documentElement.clientHeight;
const out = [];
for (const e of document.querySelectorAll(SEC)) {
  const r = e.getBoundingClientRect();
  const cs = getComputedStyle(e);
  if (r.width === 0 && r.height === 0) continue;  // display:none / gizli
  if (cs.visibility === 'hidden') continue;
  const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
  out.push({ad: ad(e), rol: rol(e), x: vx + r.x, y: vy + r.y, w: r.width, h: r.height,
            gorunur: cx >= 0 && cy >= 0 && cx < W && cy < H, devre_disi: !!e.disabled, isaretli: !!e.checked,
            href: e.href || null});
}
return {ogeler: out, webdriver: navigator.webdriver, cerceveler: document.querySelectorAll('iframe').length};
"""
ELEMAN = "element-6066-11e4-a52e-4f735466cecf"


def b_oku(mn, X, Y, cerceveler=True):
    """B: üst belge + (SwitchToFrame ile) her iframe. Koordinat → pencere pikseli."""
    sonuc = mn.js(B_JS)
    ogeler = [dict(o, cerceve=0) for o in sonuc["ogeler"]]
    if cerceveler and sonuc["cerceveler"]:
        refs = mn.js("return Array.from(document.querySelectorAll('iframe'));")
        for i, ref in enumerate(refs):
            mn.komut("WebDriver:SwitchToFrame", {"element": ref[ELEMAN]})
            try:
                ogeler += [dict(o, cerceve=i + 1) for o in mn.js(B_JS)["ogeler"]]
            finally:
                mn.komut("WebDriver:SwitchToParentFrame")
    for o in ogeler:
        o["kutu"] = [o["x"] - X, o["y"] - Y, o["w"], o["h"]]
        o["merkez"] = [round(o["x"] - X + o["w"] / 2), round(o["y"] - Y + o["h"] / 2)]
    return ogeler, sonuc["webdriver"]


def medyan_sure(f, n=3):
    s = []
    for _ in range(n):
        t0 = time.perf_counter()
        f()
        s.append(time.perf_counter() - t0)
    return statistics.median(s)


def kapsama(ogeler, beklenen):
    var = {(o["rol"], o["ad"]) for o in ogeler}
    return sum(b in var for b in beklenen), len(beklenen)


def kutu_farki(a_ogeler, b_ogeler):
    """Aynı (rol, ad) ögelerin A ve B merkezleri arasındaki en büyük / medyan fark (px)."""
    b = {(o["rol"], o["ad"]): o for o in b_ogeler}
    farklar = []
    for o in a_ogeler:
        x = b.get((o["rol"], o["ad"]))
        if x and o["merkez"]:
            farklar.append(max(abs(o["merkez"][0] - x["merkez"][0]), abs(o["merkez"][1] - x["merkez"][1]),
                               max(abs(p - q) for p, q in zip(o["kutu"], x["kutu"]))))
    return (max(farklar), statistics.median(farklar), len(farklar)) if farklar else (None, None, 0)


def tikla_say(t, ogeler):
    dogru = 0
    for o in ogeler:
        ad = t.tikla(*o["merkez"], tus="Escape" if o["rol"] == "combo box" else None)
        dogru += ad == wt.DATA_AD.get(o["ad"], o["ad"])
    return dogru, len(ogeler)


bekci = wt.ProfilBekcisi()
acik = []


def profil_denetle(an):
    f = bekci.fark()
    if f:
        print(f"\n!!! KULLANICI FIREFOX PROFİL KÖKÜ DEĞİŞTİ ({an}): {f} — durduruldu, hiçbir şey düzeltilmedi", flush=True)
        for ff_ in acik:
            ff_.kapat()
        masaustu.masaustu_durdur()
        os._exit(2)


def kapat_hepsi():
    for ff_ in list(acik):
        try:
            ff_.kapat()
        except Exception:  # noqa: BLE001
            pass
        acik.remove(ff_)
    if masaustu.durum_oku() is not None:
        masaustu.masaustu_durdur()


atexit.register(kapat_hepsi)


def firefox(url, **kw):
    ff = wt.Firefox(au, _yalitim.GECICI, url, **kw)
    acik.append(ff)
    profil_denetle("Firefox açıldı")
    return ff


def kapat(ff):
    ff.kapat()
    acik.remove(ff)
    profil_denetle("Firefox kapandı")


DIS_ISTEMCI = r"""
import json, socket, sys
port = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", port), timeout=10)
def oku():
    b = b""
    while b":" not in b:
        c = s.recv(1)
        if not c: raise SystemExit("KAPANDI")
        b += c
    n, k = b.split(b":", 1); v = k
    while len(v) < int(n): v += s.recv(int(n) - len(v))
    return json.loads(v)
def komut(no, ad, p):
    v = json.dumps([0, no, ad, p]).encode(); s.sendall(str(len(v)).encode() + b":" + v)
    while True:
        y = oku()
        if y[0] == 1 and y[1] == no: return y
oku()
y = komut(1, "WebDriver:NewSession", {"capabilities": {}})
if y[2]: print("OTURUM-RED", y[2].get("error")); raise SystemExit
y = komut(2, "WebDriver:ExecuteScript", {"script": "return [document.title, location.href, document.cookie]", "args": []})
print("SURDU", json.dumps(y[3]["value"], ensure_ascii=False))
komut(3, "WebDriver:DeleteSession", {})
"""


def dis_surec(port):
    """Başka bir süreç (aynı kullanıcı, yalnız Python + TCP): kapıya bağlanıp tarayıcıyı sürebiliyor mu?"""
    r = subprocess.run([sys.executable, "-I", "-c", DIS_ISTEMCI, str(port)], capture_output=True, text=True, timeout=30)
    satirlar = (r.stdout.strip() or r.stderr.strip()).splitlines()
    return satirlar[-1][:300] if satirlar else "?"


# ---------------------------------------------------------------- ölçüm
d = masaustu.masaustu_baslat()
au = sec(arka_bayragi=True)
srv = wt.Sunucu()
sonuc = {"A": {}, "B": {}, "B_risk": {}}
try:
    SAYFALAR = [("form", "form.html", wt.FORM), ("liste-1000", "liste.html", [("button", "Listeyi yenile")] +
                [("link", f"Bağlantı {i:04d}") for i in range(1, 1001)]),
                ("liste-200", "liste.html?n=200", [("button", "Listeyi yenile")] +
                 [("link", f"Bağlantı {i:04d}") for i in range(1, 201)]),
                ("bileşen", "bilesen.html", wt.BILESEN + wt.SONRADAN), ("satın alma", "satin.html", wt.SATIN)]
    for ad, sayfa, beklenen in SAYFALAR:
        ff = firefox(srv.url(sayfa), marionette=True)
        port = ff.marionette_kapisi()
        mn = wt.Marionette(port)
        mn.oturum()
        time.sleep(1.6)  # bileşen sayfasında sonradan eklenen içerik
        k = ff.k
        X, Y = au.geometri(k)[:2]
        a_hepsi = web.oku(k, gorunur=False, en_cok=0)["ogeler"]
        b_hepsi, wd = b_oku(mn, X, Y)
        ta = medyan_sure(lambda: web.oku(k, gorunur=False, en_cok=0))
        tb = medyan_sure(lambda: b_oku(mn, X, Y))
        mx, med, n = kutu_farki(a_hepsi, b_hepsi)
        a_tekrar = web.oku(k, gorunur=False, en_cok=0)["ogeler"]  # ölçüm sırasındaki ikinci okuma (kararlılık)
        sonuc["A"][ad] = {"kapsama": kapsama(a_hepsi, beklenen), "sure": round(ta, 3),
                          "eksik": sorted(set(beklenen) - {(o["rol"], o["ad"]) for o in a_hepsi})[:5],
                          "kapsama_ikinci_okuma": kapsama(a_tekrar, beklenen),
                          "gizli_bildirildi": sum(o["ad"] in wt.FORM_GIZLI for o in a_hepsi)}
        sonuc["B"][ad] = {"kapsama": kapsama(b_hepsi, beklenen), "sure": round(tb, 3), "webdriver": wd,
                          "kutu_farki_A_B": {"en_cok_px": mx, "medyan_px": med, "eslesen": n},
                          "gizli_bildirildi": sum(o["ad"] in wt.FORM_GIZLI for o in b_hepsi),
                          "fazla": sorted({(o["rol"], o["ad"]) for o in b_hepsi} - set(beklenen))[:8]}
        # gerçek tıklama ile koordinat doğruluğu (görünen, devre dışı olmayan, sekme/menü düğmesi dışı)
        t = wt.Tiklayici(au, k)
        sec_ = [o for o in b_hepsi if o["gorunur"] and not o["devre_disi"] and o["rol"] != "page tab"
                and o["ad"] not in ("Düzen", "Satın al", "Öde", "Siparişi onayla")]
        sec_ = sec_[::max(1, len(sec_) // 15)][:15]
        sonuc["B"][ad]["tiklama"] = tikla_say(t, sec_)
        if ad in ("form", "liste-1000"):  # kaydırma sonrası
            t.tikla(300, 130, sure=0.3)
            t.tus("End")
            time.sleep(0.5)
            X, Y = au.geometri(k)[:2]
            b2 = [o for o in b_oku(mn, X, Y)[0] if o["gorunur"]]
            a2 = web.sayfa_ogeleri(k, en_cok=0)
            sonuc["B"][ad]["kaydirma_tiklama"] = tikla_say(t, b2[-2:])
            sonuc["A"][ad]["kaydirma_tiklama"] = tikla_say(t, a2[-2:])
        t.kapat()
        otom = web.sayfa_ogeleri(k, roller=["başlık"], sorgu="webdriver", gorunur=False)
        sonuc["B"][ad]["sayfanin_gordugu"] = otom[0]["ad"] if otom else None
        mn.kapat()
        kapat(ff)
        print(f"ölçüldü: {ad}", flush=True)

    # ---------------------------------------------------------------- B riskleri
    t0 = time.monotonic()
    ff = firefox(srv.url("form.html"), marionette=True)
    port = ff.marionette_kapisi()
    # azaltma: oturumu başlatır başlatmaz tutmak (Marionette tek bağlantı kabul ediyor); açık kalan pencere = süreç
    # başlangıcından bizim bağlanabildiğimiz ana dek (kapı dosyası okunana dek) geçen süre
    sonuc["B_risk"]["baslangictan_kapiya_sn"] = round(time.monotonic() - t0, 2)
    sonuc["B_risk"]["kapi"] = port
    r = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    sonuc["B_risk"]["dinleyen"] = [s.split()[3] for s in r.splitlines() if f":{port} " in s]
    sonuc["B_risk"]["oturum_yokken_dis_surec"] = dis_surec(port)
    mn = wt.Marionette(port)
    mn.oturum()
    sonuc["B_risk"]["bizim_oturum_acikken_dis_surec"] = dis_surec(port)
    mn.kapat()
    sonuc["B_risk"]["oturum_kapandiktan_sonra_dis_surec"] = dis_surec(port)
    kapat(ff)
    # azaltma 1: dom.webdriver.enabled=false (eski gizleme tercihi) — sayfa ne görüyor?
    ff = firefox(srv.url("form.html"), marionette=True, ek_prefs={"dom.webdriver.enabled": False})
    mn = wt.Marionette(ff.marionette_kapisi())
    mn.oturum()
    sonuc["B_risk"]["azaltma_dom.webdriver.enabled=false"] = mn.js("return String(navigator.webdriver)")
    # azaltma 2: sayfa yüklenmeden önce özelliği gizleme (her belgeye betik) — JS ile tanımı ezmek
    mn.js("Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => false, configurable: true});")
    sonuc["B_risk"]["azaltma_defineProperty_sonrasi"] = mn.js(
        "return [String(navigator.webdriver), String(Object.getOwnPropertyDescriptor(Navigator.prototype,"
        " 'webdriver').get).slice(0, 40)]")
    mn.kapat()
    kapat(ff)
    # karşılaştırma: Marionette KAPALI (A'nın kullandığı) Firefox'ta sayfanın gördüğü
    ff = firefox(srv.url("form.html"))
    otom = None
    for _ in range(30):
        otom = web.sayfa_ogeleri(ff.k, roller=["başlık"], sorgu="webdriver", gorunur=False)
        if otom:
            break
        time.sleep(0.1)
    sonuc["A"]["sayfanin_gordugu"] = otom[0]["ad"] if otom else None
    r = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
    sonuc["A"]["firefox_dinleyen_kapi"] = [s.split()[3] for s in r.splitlines() if f"pid={ff.p.pid}," in s]
    kapat(ff)
finally:
    kapat_hepsi()
    srv.kapat()

print("\n=== A (erişilebilirlik ağacı) / B (Marionette) ===")
print(f"{'sayfa':<12} {'A kapsama':>10} {'A sn':>7} {'B kapsama':>10} {'B sn':>7} {'A-B kutu farkı (en çok/medyan px)':>34}"
      f" {'B tıklama':>10}")
for ad in sonuc["B"]:
    a, b = sonuc["A"][ad], sonuc["B"][ad]
    print(f"{ad:<12} {a['kapsama'][0]:>5}/{a['kapsama'][1]:<4} {a['sure']:>7.3f} {b['kapsama'][0]:>5}/{b['kapsama'][1]:<4}"
          f" {b['sure']:>7.3f} {str(b['kutu_farki_A_B']['en_cok_px']) + ' / ' + str(b['kutu_farki_A_B']['medyan_px']):>34}"
          f" {b['tiklama'][0]:>4}/{b['tiklama'][1]:<4}")
print("ayrıntı:", json.dumps(sonuc, ensure_ascii=False, indent=1))
print("kullanıcı Firefox profil kökü:", *bekci.satirlar(), sep="\n  ")
if os.environ.get("DESKHAND_WEB_OLCUM"):
    with open(os.environ["DESKHAND_WEB_OLCUM"], "w") as f:
        json.dump(sonuc, f, ensure_ascii=False, indent=1)
sys.exit(0)
