"""`deskhand doctor` (doktor) testleri. Salt okunur denetim: hiçbir şey başlatılmaz/değiştirilmez; DESKHAND_*_DIR'ler
geçici klasörde (tests/_yalitim.py). Denetimler sahte araç/oturum bilgisiyle sınanır; en sonda gerçek bir alt süreç
(`python3 -m deskhand doctor --json`) çalışır ve yalıtılmış klasörlere yazmadığı doğrulanır.

Çalıştır:  python3 tests/test_doktor.py"""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from deskhand import __version__, doktor, hata, masaustu, ocr_gpu, onay, yollar

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def kos(f, *a, **k):
    """→ (çıkış kodu | None, stdout)."""
    cikti = io.StringIO()
    kod = None
    with contextlib.redirect_stdout(cikti):
        try:
            f(*a, **k)
        except SystemExit as e:
            kod = e.code
    return kod, cikti.getvalue()


# ---------------------------------------------------------------- bağımlılık satırları (Sağlık sekmesiyle ortak)

SAGLIK = [
    {"ad": "tesseract", "tur": "arac", "ok": True, "not": "metin okuma (tesseract)"},
    {"ad": "kdotool", "tur": "arac", "ok": False, "not": "pencere bulma (AUR: kdotool-bin)"},
    {"ad": "openbox", "tur": "arac", "ok": False, "not": "arka plan pencere yöneticisi (openbox)"},
    {"ad": "scipy", "tur": "modul", "ok": False, "not": "simge eşleme (python-scipy)"},
    {"ad": "spectacle", "tur": "arac", "ok": False, "not": "ekran görüntüsü (spectacle)"},
    {"ad": "tesseract: tur", "tur": "dil", "ok": False, "not": "Türkçe OCR (tesseract-data-tur)"},
]
asil_denetle = doktor.saglik.denetle
doktor.saglik.denetle = lambda: SAGLIK
b = {s["ad"]: s for s in doktor.bagimlilik_satirlari()}
kontrol("bağımlılık: var → tamam", b["tesseract"]["durum"] == "tamam" and b["tesseract"]["zorunlu"])
kontrol("bağımlılık: zorunlu eksik → eksik + AUR önerisi", b["kdotool"]["durum"] == "eksik" and b["kdotool"]["zorunlu"] and
        "kdotool-bin" in b["kdotool"]["oneri"] and "AUR" in b["kdotool"]["oneri"], str(b["kdotool"]))
kontrol("bağımlılık: zorunlu eksik → resmî paket önerisi", b["openbox"]["durum"] == "eksik" and "openbox" in b["openbox"]["oneri"]
        and "AUR" not in b["openbox"]["oneri"], str(b["openbox"]))
kontrol("bağımlılık: isteğe bağlı eksik (scipy, spectacle) → uyarı, zorunlu değil",
        b["scipy"]["durum"] == "uyari" and not b["scipy"]["zorunlu"] and b["spectacle"]["durum"] == "uyari")
kontrol("bağımlılık: tesseract dil verisi eksik → eksik, paket tesseract-data-tur",
        b["tesseract: tur"]["durum"] == "eksik" and "tesseract-data-tur" in b["tesseract: tur"]["oneri"])

# ---------------------------------------------------------------- ek satırlar

ortam0 = {a: os.environ.get(a) for a in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP")}


def oturum(tur, masaustu_adi):
    for a, v in (("XDG_SESSION_TYPE", tur), ("XDG_CURRENT_DESKTOP", masaustu_adi)):
        if v is None:
            os.environ.pop(a, None)
        else:
            os.environ[a] = v
    return doktor.satir_oturum()


s = oturum("wayland", "KDE")
kontrol("oturum: Wayland + KDE → tamam", s["durum"] == "tamam" and "Wayland" in s["ayrinti"], str(s))
s = oturum("x11", "KDE")
kontrol("oturum: X11 → uyarı (ön plan desteklenmez, arka plan çalışır)", s["durum"] == "uyari" and "X11" in s["ayrinti"], str(s))
s = oturum(None, None)
kontrol("oturum: bilinmiyor → uyarı, çökmez", s["durum"] == "uyari", str(s))
for a, v in ortam0.items():
    if v is None:
        os.environ.pop(a, None)
    else:
        os.environ[a] = v

kontrol("sürüm: Deskhand sürümü satırı", doktor.satir_surum()["ayrinti"] == __version__)

cagrilar = []
asil_run = doktor.subprocess.run


class Sonuc:
    def __init__(self, cikti, kod=0):
        self.stdout, self.returncode = cikti, kod


_qpa0 = os.environ.get("QT_QPA_PLATFORM")
ortamlar = []


def sahte_run(cmd, **k):
    cagrilar.append(list(cmd))
    ortamlar.append((os.path.basename(cmd[0]), (k.get("env") or {}).get("QT_QPA_PLATFORM")))
    ad = os.path.basename(cmd[0])
    if ad == "kwin_wayland":
        return Sonuc("kwin 6.9.1\n")
    if ad == "plasmashell":
        return Sonuc("plasmashell 6.9.1\n")
    if ad == "busctl" and "NameHasOwner" in cmd:
        return Sonuc(sahte_a11y["sahip"] + "\n")
    if ad == "busctl" and "get-property" in cmd:
        return Sonuc(sahte_a11y["durum"] + "\n")
    return Sonuc("", 1)


sahte_a11y = {"sahip": "b true", "durum": "b true"}
doktor.subprocess.run = sahte_run
asil_which = doktor.shutil.which
doktor.shutil.which = lambda a: "/usr/bin/" + a
s = doktor.satir_kwin()
kontrol("KWin/Plasma: sürümler tek satırda", s["durum"] == "tamam" and "kwin 6.9.1" in s["ayrinti"] and
        "plasmashell 6.9.1" in s["ayrinti"], str(s))
kontrol("KWin/Plasma yoklaması alt sürece QT_QPA_PLATFORM=offscreen verir (ekransız çökme/coredump yok)",
        ("plasmashell", "offscreen") in ortamlar and ("kwin_wayland", "offscreen") in ortamlar, str(ortamlar))
kontrol("offscreen YALNIZ alt sürece: süreç ortamı değişmedi", os.environ.get("QT_QPA_PLATFORM") != "offscreen" or
        os.environ.get("QT_QPA_PLATFORM") == _qpa0)
s = doktor.satir_erisim()
kontrol("erişilebilirlik: IsEnabled true → tamam", s["durum"] == "tamam", str(s))
sahte_a11y["durum"] = "b false"
s = doktor.satir_erisim()
kontrol("erişilebilirlik: IsEnabled false → uyarı + `deskhand a11y on` önerisi", s["durum"] == "uyari" and "a11y on" in s["oneri"], str(s))
sahte_a11y["sahip"] = "b false"
cagrilar.clear()
s = doktor.satir_erisim()
kontrol("erişilebilirlik: veri yolu çalışmıyorsa uyarı ve özellik SORGULANMAZ (hizmeti başlatmasın)",
        s["durum"] == "uyari" and not any("get-property" in c for c in cagrilar), f"{s} {cagrilar}")
cagrilar.clear()
doktor.shutil.which = lambda a: None
kontrol("KWin/Plasma: araçlar yoksa uyarı, çökmez", doktor.satir_kwin()["durum"] == "uyari")
doktor.shutil.which = asil_which
doktor.subprocess.run = asil_run

# panel + girdi merkezi (yalıtılmış RUNTIME_DIR)
s = doktor.satir_panel()
kontrol("panel: çalışmıyor → uyarı + başlatma komutu", s["durum"] == "uyari" and "panel" in s["oneri"], str(s))
onay.panel_kaydet()  # bu sürecin pid'iyle, yalıtılmış klasörde
s = doktor.satir_panel()
kontrol("panel: pid dosyası canlı süreçte → tamam", s["durum"] == "tamam" and str(os.getpid()) in s["ayrinti"], str(s))
onay.panel_sil()
s = doktor.satir_girdi_merkezi()
kontrol("girdi merkezi: soket yok → uyarı", s["durum"] == "uyari", str(s))
from deskhand import girdi_merkezi  # noqa: E402
os.makedirs(os.path.dirname(girdi_merkezi.soket_yolu()), mode=0o700, exist_ok=True)
sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sk.bind(girdi_merkezi.soket_yolu())
s = doktor.satir_girdi_merkezi()
kontrol("girdi merkezi: soket var → tamam", s["durum"] == "tamam", str(s))
sk.close()
os.remove(girdi_merkezi.soket_yolu())
with open(girdi_merkezi.soket_yolu(), "w") as f:
    f.write("")
kontrol("girdi merkezi: aynı adlı sıradan dosya soket sayılmaz → uyarı", doktor.satir_girdi_merkezi()["durum"] == "uyari")
os.remove(girdi_merkezi.soket_yolu())

# C yardımcıları
asil_e, asil_g, asil_i = yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin
yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin = lambda: "/yok/etkinlik", lambda: None, lambda: None
s = doktor.satir_yardimcilar()
kontrol("C yardımcıları: üçü de yok → uyarı, üçü de anılır", s["durum"] == "uyari" and "deskhand-etkinlik" in s["ayrinti"] and
        "deskhand-goruntu" in s["ayrinti"] and "deskhand-eis" in s["ayrinti"], str(s))
kontrol("C yardımcıları: sonuç da söylenir (Xvfb kullanılacak)", "Xvfb kullanılacak" in s["ayrinti"], str(s))
sh = sys.executable  # çalıştırılabilir bir dosya
yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin = lambda: sh, lambda: sh, lambda: None
s = doktor.satir_yardimcilar()
kontrol("C yardımcıları: yalnız deskhand-eis yok → uyarı, yalnız o anılır", s["durum"] == "uyari" and
        "deskhand-eis" in s["ayrinti"] and "deskhand-etkinlik" not in s["ayrinti"] and
        "deskhand-goruntu" not in s["ayrinti"], str(s))
yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin = lambda: sh, lambda: sh, lambda: sh
kontrol("C yardımcıları: üçü de çalıştırılabilir → tamam", doktor.satir_yardimcilar()["durum"] == "tamam")
yollar.etkinlik_bin, yollar.goruntu_bin, yollar.eis_bin = asil_e, asil_g, asil_i

# arka plan masaüstü
asil_durum = masaustu.durum
masaustu.durum = lambda *a, **k: None
s = doktor.satir_arka_plan()
kontrol("arka plan: kapalı → tamam (istek üzerine açılır), açma komutu anılır", s["durum"] == "tamam" and "desktop start" in s["ayrinti"], str(s))
masaustu.durum = lambda *a, **k: {"ekran": ":91", "boyut": [1920, 1080, 24], "saglik": {"xvfb": True, "openbox": True}}
s = doktor.satir_arka_plan()
kontrol("arka plan: çalışıyor → ekran + boyut", s["durum"] == "tamam" and ":91" in s["ayrinti"] and "1920x1080" in s["ayrinti"], str(s))
masaustu.durum = lambda *a, **k: {"ekran": ":91", "boyut": [1920, 1080, 24], "saglik": {"xvfb": True, "openbox": False}}
s = doktor.satir_arka_plan()
kontrol("arka plan: bileşen ölü → uyarı, hangisi", s["durum"] == "uyari" and "openbox" in s["ayrinti"], str(s))
masaustu.durum = asil_durum

# GPU OCR
asil_ek = ocr_gpu.eksikler
ocr_gpu.eksikler = lambda: []
kontrol("GPU OCR: kurulu → tamam", doktor.satir_gpu_ocr()["durum"] == "tamam")
ocr_gpu.eksikler = lambda: ["gpu", "python", "model"]
kontrol("GPU OCR: kart yok (diğer eksikler anlamsız) → tamam, tesseract yeter", doktor.satir_gpu_ocr()["durum"] == "tamam")
ocr_gpu.eksikler = lambda: ["gpu"]
ocr_gpu.eksikler = lambda: ["python", "model"]
s = doktor.satir_gpu_ocr()
kontrol("GPU OCR: kart var, kurulum eksik → uyarı, ne eksik", s["durum"] == "uyari" and "EasyOCR" in s["ayrinti"] and
        "model" in s["ayrinti"], str(s))
ocr_gpu.eksikler = asil_ek

# ---------------------------------------------------------------- toplama, özet, çıkış kodu, JSON

asil_satirlar = doktor.SATIRLAR


def patlayan():
    raise RuntimeError("deneme")


doktor.SATIRLAR = (patlayan,)
doktor.saglik.denetle = lambda: [{"ad": "tesseract", "tur": "arac", "ok": True, "not": "metin okuma (tesseract)"}]
t = doktor.topla()
kontrol("topla: patlayan denetim → 'denetlenemedi' uyarısı", t[-1]["durum"] == "uyari" and "denetlenemedi" in t[-1]["ayrinti"], str(t[-1]))
doktor.SATIRLAR = asil_satirlar

ornek = [doktor._satir("A", "tamam", "iyi"), doktor._satir("B", "uyari", "yarım", "şunu yap"),
         doktor._satir("C", "eksik", "yok", "kur: x", zorunlu=True)]
m = doktor.metin(ornek)
satirlar = m.splitlines()
kontrol("metin: her denetim tek satır, ✓ / ! / ✗ imleri", satirlar[0].startswith("✓ A") and satirlar[1].startswith("! B") and
        satirlar[2].startswith("✗ C") and len(satirlar) == 4, m)
kontrol("metin: eksikse ne yapılacağı → ile satırda; tamamda öneri yok", "→ şunu yap" in satirlar[1] and "→ kur: x" in satirlar[2]
        and "→" not in satirlar[0])
kontrol("metin: sonda özet satırı", satirlar[-1] == "Özet: 1 tamam, 1 uyarı, 1 eksik zorunlu bağımlılık", satirlar[-1])


def kosu(satirlar_):
    doktor.topla, asil = (lambda: satirlar_), doktor.topla
    try:
        return kos(doktor.k_doktor, type("A", (), {"json": False})()), kos(doktor.k_doktor, type("A", (), {"json": True})())
    finally:
        doktor.topla = asil


(kod_m, cikti_m), (kod_j, cikti_j) = kosu(ornek)
kontrol("çıkış: zorunlu bağımlılık eksik → 9 (metin ve json)", kod_m == hata.ARAC_EKSIK == 9 and kod_j == 9, f"{kod_m} {kod_j}")
j = json.loads(cikti_j)
kontrol("json: makinece okunur (sürüm, tamam=false, özet, denetimler)", j["surum"] == __version__ and j["tamam"] is False and
        j["ozet"] == {"tamam": 1, "uyari": 1, "eksik": 1} and len(j["denetimler"]) == 3 and
        set(j["denetimler"][0]) == {"ad", "durum", "zorunlu", "ayrinti", "oneri"}, cikti_j)
(kod_m, _), (kod_j, cikti_j) = kosu(ornek[:2])
kontrol("çıkış: yalnız uyarı varsa 0 (uyarılar çıkışı etkilemez)", kod_m is None and kod_j is None)
kontrol("json: tamam=true", json.loads(cikti_j)["tamam"] is True)
doktor.saglik.denetle = asil_denetle

# ---------------------------------------------------------------- gerçek alt süreç: salt okunur + yalıtılmış

def dosyalar(dizin):
    if not os.path.isdir(dizin):
        return set()
    return {os.path.join(d, f) for d, _, fs in os.walk(dizin) for f in fs}


izlenen = [yollar.config_dir(), yollar.state_dir(), yollar.cache_dir(), yollar.data_dir()]
once = {d: dosyalar(d) for d in izlenen}
env = dict(os.environ)
r = subprocess.run([sys.executable, "-m", "deskhand", "doctor", "--json"], capture_output=True, text=True, env=env,
                   cwd=_yalitim.KOK, timeout=60)
try:
    j = json.loads(r.stdout)
except ValueError:
    j = None
kontrol("alt süreç: doctor --json geçerli JSON verir", j is not None and "denetimler" in j, r.stdout[:300] + r.stderr[-300:])
kontrol("alt süreç: çıkış kodu ile json.tamam tutarlı (eksik zorunlu varsa 9, yoksa 0)",
        j is not None and r.returncode == (0 if j["tamam"] else 9), f"{r.returncode} {j and j['ozet']}")
ad_ = {d["ad"] for d in (j or {}).get("denetimler", [])}
kontrol("alt süreç: bağımlılık + ek satırlar hep var (sürüm, oturum, KWin, panel, girdi merkezi, C, AT-SPI, arka plan, GPU OCR)",
        {"Deskhand sürümü", "Masaüstü oturumu", "KWin / Plasma sürümü", "Panel", "Girdi merkezi soketi", "C yardımcıları",
         "Erişilebilirlik (AT-SPI)", "Arka plan masaüstü", "GPU metin okuma (OCR)", "kdotool", "tesseract"} <= ad_, str(sorted(ad_)))
r2 = subprocess.run([sys.executable, "-m", "deskhand", "doktor"], capture_output=True, text=True, env=env, cwd=_yalitim.KOK,
                    timeout=60)
kontrol("alt süreç: Türkçe `doktor` metin çıktısı: ✓/✗/! imleri + Özet satırı",
        r2.stdout.splitlines()[-1].startswith("Özet: ") and any(l[:1] in "✓!✗" for l in r2.stdout.splitlines()), r2.stdout[-300:])
sonra = {d: dosyalar(d) for d in izlenen}
yeni = {d: sorted(sonra[d] - once[d]) for d in izlenen if sonra[d] - once[d]}
# yollar.gecis() / günlük temizliği yalnız yalıtılmış klasörlerde dizin açabilir; doctor kendisi dosya yazmaz
kontrol("alt süreç: doctor hiçbir dosya yazmadı (yalıtılmış klasörler değişmedi)", not yeni, str(yeni))
kontrol("alt süreç: doctor arka plan masaüstü / panel BAŞLATMADI", masaustu.durum_oku() is None and onay.panel_pid() is None)

print(f"\n{gecen}/{toplam} doctor testi geçti")
sys.exit(0 if gecen == toplam else 1)
