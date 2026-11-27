"""Tasarım kalite kapısı (UX-Q1): tools/tasarim_kapi.py.

Denetlenen: her kural sahte bir widget ağacında TAM 1 ihlal yakalar (temiz ağaç 0); eşikler token dosyasından okunur
(token değişince sonuç değişir); CLI bugünkü panelde yalnız bilinen ihlalleri bulur (çıkış 0), boş bilinen listesiyle
çıkış 1; denetim süresi ≤ 2 sn; --pano tek PNG üretir, uzun kenar ≤ 1600 px, süre ≤ 3 sn.
Ekransız (offscreen), geçici HOME/XDG (gerçek ~/.config yazılmaz).
Çalıştır: python3 tests/test_tasarim_kapi.py"""
import json
import os
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
import _yalitim  # noqa: E402,F401
import _gorsel as G  # noqa: E402

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARAC = os.path.join(KOK, "tools", "tasarim_kapi.py")
sys.path.insert(0, os.path.join(KOK, "tools"))

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


try:
    import tasarim_kapi as K
except Exception as e:  # noqa: BLE001 — kırmızı aşama: modül yok
    kontrol("tasarim_kapi içe aktarılır", False, repr(e))
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(1)

from PyQt6.QtGui import QColor, QPalette  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
with open(os.path.join(KOK, "deskhand", "gui", "tema", "tokens.json"), encoding="utf-8") as f:
    HAM = json.load(f)
from deskhand.gui.tema import uret  # noqa: E402

app.setPalette(uret.palet_uret(HAM, "acik"))
TEMEL = app.font().pointSizeF()
E = K.esikler(HAM, TEMEL)


def kap(*ogeler, spacing=None):
    """Temiz kap: kenar 0, boşluk aralık biriminin katı."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(E["aralik_birim"] * 4 if spacing is None else spacing)
    for o in ogeler:
        lay.addWidget(o)
    w.show()
    app.processEvents()
    return w


def temiz_dugme(metin="Tamam"):
    b = QPushButton(metin)
    b.setMinimumSize(E["hedef_min"] + 8, E["hedef_min"] + 8)
    return b


def kurallar(w, esik=E):
    return [i["kural"] for i in K.denetle([w], esik)]


# ---------------------------------------------------------------- eşikler token'dan
kontrol("eşik: tıklama hedefi tokens'tan (yoksa WCAG 24)", E["hedef_min"] == HAM.get("min_tiklama_hedefi_px", 24))
kontrol("eşik: aralık birimi = aralık değerlerinin EBOB'u",
        E["aralik_birim"] == __import__("math").gcd(*[int(v) for v in HAM["aralik"].values()]), str(E["aralik_birim"]))
kontrol("eşik: yazı ölçeği temel × yazi.*_olcek",
        any(abs(p - TEMEL * HAM["yazi"]["baslik_olcek"]) < 1e-6 for p in E["yazi_pt"]), str(E["yazi_pt"]))
kontrol("eşik: palet token renklerini içerir", HAM["durum"]["dur"].lower() in E["palet"])
kontrol("eşik: kontrast alt sınırı tokens'tan (4,5)", E["kontrast_min"] == HAM["kontrast_min"] == 4.5)
kontrol("eşik: tokens'ta eşik yoksa token şeması varsayılanı",
        (K.esikler({}, TEMEL)["hedef_min"], K.esikler({}, TEMEL)["kontrast_min"])
        == (uret.VARSAYILAN["min_tiklama_hedefi_px"], uret.VARSAYILAN["kontrast_min"]))
kontrol("eşik: kontrast_min değişince eşik değişir", K.esikler({**HAM, "kontrast_min": 7}, TEMEL)["kontrast_min"] == 7)
kontrol("diyalog örnek istekleri tek kaynak (_gorsel.diyalog_istekleri)",
        not hasattr(K, "_diyalog_istekleri") and list(G.diyalog_istekleri()) == list(G.DIYALOGLAR))

# ---------------------------------------------------------------- temiz ağaç
temiz = kap(QLabel("Merhaba"), temiz_dugme())
kontrol("temiz ağaçta 0 ihlal", kurallar(temiz) == [], str(K.denetle([temiz], E)))

# ---------------------------------------------------------------- her kural tam 1 ihlal
lb = QLabel("Bu metin dar bir etikete sığmayacak kadar uzundur")
lb.setFixedWidth(40)
r = kurallar(kap(lb, temiz_dugme()))
kontrol("KESIK: dar etiket tam 1 ihlal", r == ["KESIK"], str(r))

kucuk = QPushButton()
kucuk.setFixedSize(E["hedef_min"] - 8, E["hedef_min"] - 8)
r = kurallar(kap(QLabel("a"), kucuk))
kontrol("HEDEF_KUCUK: küçük düğme tam 1 ihlal", r == ["HEDEF_KUCUK"], str(r))

yz = QLabel("Başlık")
f = yz.font()
f.setPointSizeF(TEMEL * 1.6)
yz.setFont(f)
r = kurallar(kap(yz, temiz_dugme()))
kontrol("YAZI_BOYUTU: ölçek dışı yazı tam 1 ihlal", r == ["YAZI_BOYUTU"], str(r))

qs = QLabel("Renkli")
qs.setStyleSheet("QLabel { color: #123456; }")
r = kurallar(kap(qs, temiz_dugme()))
kontrol("QSS_RENK: palet dışı QSS rengi tam 1 ihlal", r == ["QSS_RENK"], str(r))

qs_ok = QLabel("Renkli")
qs_ok.setStyleSheet(f"QLabel {{ color: {HAM['renk']['acik']['palet']['Text']}; }}")
r = kurallar(kap(qs_ok, temiz_dugme()))
kontrol("QSS_RENK: token rengi ihlal değil", r == [], str(r))

kt = QLabel("Soluk")
p = kt.palette()
p.setColor(QPalette.ColorRole.WindowText, QColor("#bbbbbb"))
kt.setPalette(p)
r = kurallar(kap(kt, temiz_dugme()))
kontrol("KONTRAST: soluk metin tam 1 ihlal", r == ["KONTRAST"], str(r))

r = kurallar(kap(QLabel("a"), temiz_dugme(), spacing=E["aralik_birim"] * 3 + 1))
kontrol("ARALIK: birim katı olmayan boşluk tam 1 ihlal", r == ["ARALIK"], str(r))

# ---------------------------------------------------------------- token değişince sonuç değişir (sabit gömme yok)
ham2 = json.loads(json.dumps(HAM))
ham2["min_tiklama_hedefi_px"] = 40
ham2["aralik_px"] = [4, 8, 12, 16]
E2 = K.esikler(ham2, TEMEL)
orta1, orta2 = QPushButton(), QPushButton()
orta1.setFixedSize(32, 32)
orta2.setFixedSize(32, 32)
k1, k2 = kap(QLabel("a"), orta1), kap(QLabel("a"), orta2)
r1, r2 = kurallar(k1), kurallar(k2, E2)
kontrol("hedef eşiği tokens'tan: 32 px 24'te temiz, 40'ta ihlal", r1 == [] and r2 == ["HEDEF_KUCUK"], f"{r1} {r2}")
genis = QPushButton()
genis.setFixedSize(48, 48)
k3 = kap(QLabel("a"), genis, spacing=6)
r = kurallar(k3, E2)
kontrol("aralık ölçeği tokens'tan (aralik_px 4'ün katı): 6 ihlal", r == ["ARALIK"], str(r))

# ---------------------------------------------------------------- CLI: bugünkü panel
ev = tempfile.mkdtemp(prefix="tasarim-kapi-")
ortam = G.sabit_ortam(ev)
ortam["PYTHONPATH"] = KOK
p = subprocess.run([sys.executable, ARAC, "--json"], env=ortam, capture_output=True, text=True, timeout=60, cwd=ev)
try:
    J = json.loads(p.stdout)
except ValueError:
    J = {}
kontrol("CLI --json: bugünkü panel yalnız bilinen ihlal (çıkış 0)", p.returncode == 0 and J.get("yeni") == [],
        f"rc={p.returncode} yeni={len(J.get('yeni', []) or [])} {p.stderr[-400:]}")
kontrol("CLI: panel sekmeleri ve diyaloglar denetlendi", J.get("ekran", 0) >= 10, str(J.get("ekran")))
kontrol("CLI: denetim süresi ≤ 2 sn", 0 < J.get("sure_ms", 1e9) <= 2000, str(J.get("sure_ms")))
bos = os.path.join(ev, "bos.json")
with open(bos, "w") as f:
    f.write("[]")
p2 = subprocess.run([sys.executable, ARAC, "--bilinen", bos], env=ortam, capture_output=True, text=True, timeout=60,
                    cwd=ev)
kontrol("CLI: boş bilinen listesiyle yeni ihlal → çıkış 1", p2.returncode == (1 if J.get("toplam") else 0),
        f"rc={p2.returncode} toplam={J.get('toplam')}")

# ---------------------------------------------------------------- pano
cikti = os.path.join(ev, "pano.png")
p3 = subprocess.run([sys.executable, ARAC, "--json", "--pano", cikti], env=ortam, capture_output=True, text=True,
                    timeout=60, cwd=ev)
try:
    J3 = json.loads(p3.stdout)
except ValueError:
    J3 = {}
kontrol("--pano PNG yazıldı", os.path.isfile(cikti) and os.path.getsize(cikti) > 0, p3.stderr[-400:])
if os.path.isfile(cikti):
    from PIL import Image
    with Image.open(cikti) as im:
        boyut = im.size
    kontrol("--pano uzun kenar ≤ 1600 px", max(boyut) <= 1600, str(boyut))
    kontrol("--pano en az 10 ekran içerir", J3.get("pano", {}).get("ekran", 0) >= 10, str(J3.get("pano")))
    kontrol("--pano süresi ≤ 3 sn", 0 < J3.get("pano", {}).get("sure_ms", 1e9) <= 3000, str(J3.get("pano")))
    print(f"pano: {boyut[0]}x{boyut[1]} {os.path.getsize(cikti)} bayt {J3.get('pano', {}).get('sure_ms')} ms")

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
