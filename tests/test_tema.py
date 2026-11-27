"""Tasarım token'ları → Qt teması köprüsü (deskhand/gui/tema): tokens.json → QPalette + QSS.

Denetlenen: şema (bilinen anahtarlar, geçerli renk, geçerli QPalette rolü), açık kip bugünkü Fusion paletini birebir
üretir, koyu kip koyu, sistem kipi paleti değiştirmez, eksik/bozuk anahtar → varsayılan, metin/arka plan kontrastı
≥ 4,5:1 (WCAG AA), panel tema_uygula'yı çağırır. Ekransız (offscreen), gerçek ~/.config yazılmaz.
Çalıştır: python3 tests/test_tema.py"""
import json
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
import _yalitim  # noqa: E402,F401

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)

from PyQt6.QtGui import QColor, QPalette  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


app = QApplication([])
app.setStyle("Fusion")
STD = QPalette(app.style().standardPalette())
G, R = QPalette.ColorGroup, QPalette.ColorRole
ROLLER = [r for r in R if r != R.NColorRoles]

try:
    from deskhand.gui import tema
    from deskhand.gui.tema import uret
except Exception as e:  # noqa: BLE001 — kırmızı aşama: modül yok
    kontrol("tema modülü içe aktarılır", False, repr(e))
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(1)

# ---------------------------------------------------------------- şema
yol = os.path.join(KOK, "deskhand", "gui", "tema", "tokens.json")
with open(yol, encoding="utf-8") as f:
    ham = json.load(f)
kontrol("tokens.json üst anahtarları", set(ham) >= {"surum", "renk", "durum", "yazi", "aralik", "kose", "odak"},
        str(sorted(ham)))
kontrol("tokens.json yalnız bilinen üst anahtarlar", set(ham) <= set(uret.VARSAYILAN) | {"$aciklama"},
        str(set(ham) - set(uret.VARSAYILAN)))
rol_adlari = {r.name for r in ROLLER}
for kip in ("acik", "koyu"):
    k = ham["renk"][kip]
    for bolum in ("palet", "devre_disi"):
        roller = set(k.get(bolum, {}))
        kontrol(f"{kip}.{bolum} rolleri geçerli QPalette rolü", roller <= rol_adlari, str(roller - rol_adlari))
        bozuk = [v for v in k.get(bolum, {}).values() if not uret.renk_gecerli(v)]
        kontrol(f"{kip}.{bolum} renkleri geçerli", not bozuk, str(bozuk))
bozuk = [a for a, v in ham["durum"].items() if not uret.renk_gecerli(v)]
kontrol("durum renkleri geçerli", not bozuk, str(bozuk))
kontrol("şema denetimi temiz", uret.sema_denetle(ham) == [], str(uret.sema_denetle(ham)))
kontrol("şema denetimi bilinmeyen anahtarı yakalar", uret.sema_denetle({"renk": {"acik": {"palet": {"Yok": "#fff"}}}}) != [])
kontrol("şema denetimi bozuk rengi yakalar", uret.sema_denetle({"durum": {"dur": "kırmızı"}}) != [])

T = uret.yukle()

# ---------------------------------------------------------------- açık = bugünkü Fusion paleti (birebir)
p = uret.palet_uret(T, "acik")
farklar = [(g.name, r.name) for g in (G.Active, G.Inactive, G.Disabled) for r in ROLLER
           if p.color(g, r).rgba() != STD.color(g, r).rgba()]
kontrol("açık palet = bugünkü Fusion paleti (tüm grup × rol)", not farklar, str(farklar[:6]))

# ---------------------------------------------------------------- koyu
pk = uret.palet_uret(T, "koyu")
kontrol("koyu: pencere arka planı koyu", pk.color(R.Window).lightness() < 100, pk.color(R.Window).name())
kontrol("koyu: metin açık", pk.color(R.WindowText).lightness() > 180, pk.color(R.WindowText).name())
kontrol("koyu: palet token'dan gelir", pk.color(R.Window).name() == T["renk"]["koyu"]["palet"]["Window"].lower())
kontrol("sistem: palet üretilmez", uret.palet_uret(T, "sistem") is None)

# ---------------------------------------------------------------- kontrast (WCAG AA, metin/arka plan)
CIFTLER = [("WindowText", "Window"), ("Text", "Base"), ("ButtonText", "Button"), ("ToolTipText", "ToolTipBase"),
           ("Text", "AlternateBase")]
for kip, pal in (("acik", p), ("koyu", pk)):
    for on, arka in CIFTLER:
        o = uret.kontrast(pal.color(G.Active, R[on]), pal.color(G.Active, R[arka]))
        kontrol(f"{kip}: {on}/{arka} kontrastı ≥ 4,5", o >= 4.5, f"{o:.2f}")
d = T["durum"]
o = uret.kontrast(QColor(d["dur_metin"]), QColor(d["dur"]))
kontrol("DUR düğmesi metin/arka plan kontrastı ölçülür (bilgi)", o > 1, f"{o:.2f}")
kontrol("kontrast formülü: siyah/beyaz = 21", abs(uret.kontrast(QColor("#000"), QColor("#fff")) - 21) < 0.01)

# ---------------------------------------------------------------- eksik anahtar → varsayılan
bos = uret.birlestir({})
kontrol("boş token → varsayılan", bos == uret.VARSAYILAN)
kismi = uret.birlestir({"durum": {"dur": "#123456"}, "kose": {}})
kontrol("kısmi token: verilen değer kullanılır", kismi["durum"]["dur"] == "#123456")
kontrol("kısmi token: eksik kardeş anahtar varsayılan", kismi["durum"]["arka"] == uret.VARSAYILAN["durum"]["arka"])
kontrol("kısmi token: eksik bölüm varsayılan", kismi["kose"] == uret.VARSAYILAN["kose"])
bozuk = uret.birlestir({"durum": {"dur": "kırmızı"}, "aralik": {"girinti": "çok"}})
kontrol("bozuk renk → varsayılan", bozuk["durum"]["dur"] == uret.VARSAYILAN["durum"]["dur"])
kontrol("bozuk sayı → varsayılan", bozuk["aralik"]["girinti"] == uret.VARSAYILAN["aralik"]["girinti"])
kontrol("qss_uret boş token ile çalışır", "QPushButton#dur" in uret.qss_uret({}, "acik"))
kontrol("palet_uret boş token ile çalışır", uret.palet_uret({}, "koyu").color(R.Window).lightness() < 100)
eksik_yol = os.path.join(os.environ.get("TMPDIR", "/tmp"), "deskhand-tema-yok.json")
kontrol("tokens.json yoksa varsayılan", uret.yukle(eksik_yol) == uret.VARSAYILAN)

# ---------------------------------------------------------------- QSS
q = uret.qss_uret(T, "acik")
kontrol("QSS: DUR düğmesi rengi token'dan", T["durum"]["dur"].lower() in q.lower(), q[:200])
kontrol("QSS: köşe token'dan", f"border-radius: {T['kose']['dugme']}px" in q)
kontrol("QSS: açık ve koyu aynı yapıda üretilir", uret.qss_uret(T, "koyu").count("{") == q.count("{"))
try:
    uret.qss_uret(T, "mor")
    kontrol("bilinmeyen kip reddedilir", False)
except ValueError:
    kontrol("bilinmeyen kip reddedilir", True)

# ---------------------------------------------------------------- tema_uygula
tema.tema_uygula(app, "sistem")
kontrol("tema_uygula(sistem) paleti değiştirmez", app.palette() == STD)
tema.tema_uygula(app, "koyu")
kontrol("tema_uygula(koyu) koyu palet", app.palette().color(R.Window).lightness() < 100)
tema.tema_uygula(app, "acik")
kontrol("tema_uygula(acik) bugünkü palet", all(app.palette().color(g, r).rgba() == STD.color(g, r).rgba()
                                              for g in (G.Active, G.Inactive, G.Disabled) for r in ROLLER))
kontrol("tema_uygula QSS'i uygular", app.styleSheet() == uret.qss_uret(T, "acik"))

# ---------------------------------------------------------------- panel bağlantısı
with open(os.path.join(KOK, "deskhand", "gui", "panel.py"), encoding="utf-8") as f:
    kaynak = f.read()
kontrol("panel tema_uygula'yı çağırır", "tema_uygula(" in kaynak)

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
