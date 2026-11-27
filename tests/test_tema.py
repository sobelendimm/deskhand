"""Tasarım token'ları → Qt teması köprüsü (deskhand/gui/tema): tokens.json → QPalette + QSS.

Denetlenen: şema (bilinen anahtarlar, geçerli renk, geçerli QPalette rolü), açık/koyu kip onaylı tasarım A + Renk 1
değerlerini üretir (tokens.json = kod varsayılanı), sistem kipi sistem paleti koyuysa koyu, açıksa açık token'ları
seçer, eksik/bozuk anahtar → varsayılan, metin/arka plan + soluk + devre dışı etiket kontrastı ≥ kontrast_min
(WCAG AA), QSS renkleri token'dan, panel tema_uygula'yı çağırır. Ekransız (offscreen), gerçek ~/.config yazılmaz.
Çalıştır: python3 tests/test_tema.py"""
import json
import os
import re
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

# ---------------------------------------------------------------- açık = onaylı Renk 1 açık
kontrol("tokens.json = kod varsayılanı (dosya silinse de aynı görünüm)",
        {k: v for k, v in ham.items() if k != "$aciklama"} == uret.VARSAYILAN)
kontrol("eşikler token'da: min_tiklama_hedefi_px 24, kontrast_min 4,5",
        ham.get("min_tiklama_hedefi_px") == 24 and ham.get("kontrast_min") == 4.5)
p = uret.palet_uret(T, "acik")
farklar = [r for r, v in T["renk"]["acik"]["palet"].items() if p.color(G.Active, R[r]).name() != v.lower()]
kontrol("açık palet: her rol token'dan (Active)", not farklar, str(farklar))
kontrol("açık: pencere arka planı açık", p.color(R.Window).lightness() > 200, p.color(R.Window).name())
kontrol("açık: devre dışı metin token'dan", p.color(G.Disabled, R.WindowText).name()
        == T["renk"]["acik"]["devre_disi"]["WindowText"].lower())

# ---------------------------------------------------------------- koyu
pk = uret.palet_uret(T, "koyu")
kontrol("koyu: pencere arka planı koyu", pk.color(R.Window).lightness() < 100, pk.color(R.Window).name())
kontrol("koyu: metin açık", pk.color(R.WindowText).lightness() > 180, pk.color(R.WindowText).name())
kontrol("koyu: palet token'dan gelir", pk.color(R.Window).name() == T["renk"]["koyu"]["palet"]["Window"].lower())
kontrol("sistem_kipi: koyu palet → koyu", uret.sistem_kipi(pk) == "koyu")
kontrol("sistem_kipi: açık palet → acik", uret.sistem_kipi(p) == "acik")
kontrol("sistem_kipi: Fusion standart (bugünkü ekransız) → acik", uret.sistem_kipi(STD) == "acik")

# ---------------------------------------------------------------- kontrast (WCAG AA, metin/arka plan)
CIFTLER = [("WindowText", "Window"), ("Text", "Base"), ("ButtonText", "Button"), ("ToolTipText", "ToolTipBase"),
           ("Text", "AlternateBase"), ("PlaceholderText", "Window"), ("PlaceholderText", "Base"),
           ("HighlightedText", "Highlight"), ("Link", "Base")]
KMIN = T["kontrast_min"]
for kip, pal in (("acik", p), ("koyu", pk)):
    for on, arka in CIFTLER:
        o = uret.kontrast(pal.color(G.Active, R[on]), pal.color(G.Active, R[arka]))
        kontrol(f"{kip}: {on}/{arka} kontrastı ≥ {KMIN}", o >= KMIN, f"{o:.2f}")
    o = uret.kontrast(pal.color(G.Disabled, R.WindowText), pal.color(G.Active, R.Window))
    kontrol(f"{kip}: devre dışı etiket (soluk not) / Window ≥ {KMIN}", o >= KMIN, f"{o:.2f}")
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
qss_renk = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{3,8}\b", q)}
token_renk = {v.lower() for v in T["durum"].values()}
kontrol("QSS: bütün renkler token'dan (QSS_RENK)", qss_renk <= token_renk, str(qss_renk - token_renk))
kontrol("QSS: DUR üzerinde rengi token'dan", T["durum"]["dur_uzerinde"].lower() in q.lower())
kontrol("QSS: açık ve koyu aynı yapıda üretilir", uret.qss_uret(T, "koyu").count("{") == q.count("{"))
try:
    uret.qss_uret(T, "mor")
    kontrol("bilinmeyen kip reddedilir", False)
except ValueError:
    kontrol("bilinmeyen kip reddedilir", True)

# ---------------------------------------------------------------- tema_uygula
tema.tema_uygula(app, "sistem")  # ekransız Fusion = açık sistem
kontrol("tema_uygula(sistem) açık sistemde açık token'lar",
        app.palette().color(R.Window).name() == T["renk"]["acik"]["palet"]["Window"].lower())
tema.tema_uygula(app, "koyu")
kontrol("tema_uygula(koyu) koyu palet", app.palette().color(R.Window).lightness() < 100)
tema.tema_uygula(app, "sistem")  # uygulama paleti koyu (KDE BreezeDark karşılığı) → koyu token'lar
kontrol("tema_uygula(sistem) koyu sistemde koyu token'lar",
        app.palette().color(R.Window).name() == T["renk"]["koyu"]["palet"]["Window"].lower())
tema.tema_uygula(app, "acik")
kontrol("tema_uygula(acik) açık palet",
        app.palette().color(R.Window).name() == T["renk"]["acik"]["palet"]["Window"].lower())
kontrol("tema_uygula QSS'i uygular", app.styleSheet() == uret.qss_uret(T, "acik"))

# ---------------------------------------------------------------- panel bağlantısı
with open(os.path.join(KOK, "deskhand", "gui", "panel.py"), encoding="utf-8") as f:
    kaynak = f.read()
kontrol("panel tema_uygula'yı çağırır", "tema_uygula(" in kaynak)

# ---------------------------------------------------------------- UX-K: varsayılan koyu, kayıtlı tercih korunur
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui.panel import Panel  # noqa: E402

yol = A.panel_yolu()
if os.path.exists(yol):
    os.remove(yol)
kontrol("tema tercihi yok → koyu", A.tema_tercihi() == "koyu", A.tema_tercihi())


def _acilis_temasi() -> str:
    """Panel.__init__ açılışta seçtiği temayı uygular; kurulumun geri kalanı burada kesilir (yalnız tema adımı)."""
    import deskhand.gui.panel as P

    class Kes(Exception):
        pass

    eski = P.AnaPencere
    P.AnaPencere = lambda *a, **k: (_ for _ in ()).throw(Kes())
    eski_merkez, P.Panel._merkez_baslat = P.Panel._merkez_baslat, lambda self: None
    eski_iz = P.Izleyici
    P.Izleyici = lambda *a, **k: type("I", (), {"ilk_satirlar": []})()
    try:
        Panel(app, tepsi=False)
    except Kes:
        pass
    finally:
        P.AnaPencere, P.Panel._merkez_baslat, P.Izleyici = eski, eski_merkez, eski_iz
    return uret.sistem_kipi(app.palette())


tema.tema_uygula(app, "acik")
kontrol("açılış: tercih yok → panel koyu açılır", _acilis_temasi() == "koyu")
kontrol("açılış: tercih yokken panel.json'a tema yazılmaz", not os.path.exists(yol))
A.panel_yaz({**A.panel_oku(), "tema": "acik"})
with open(yol, encoding="utf-8") as f:
    once = f.read()
kontrol("açılış: kayıtlı tercih 'acik' → panel açık kalır", _acilis_temasi() == "acik")
with open(yol, encoding="utf-8") as f:
    kontrol("açılış: kayıtlı tercih değiştirilmez", f.read() == once)
A.panel_yaz({**A.panel_oku(), "tema": "mor"})
kontrol("geçersiz kayıtlı tercih → koyu", A.tema_tercihi() == "koyu")
A.panel_yaz({**A.panel_oku(), "tema": "sistem"})
kontrol("kayıtlı tercih 'sistem' okunur", A.tema_tercihi() == "sistem")
d = A.panel_oku()
d["kisayol_acik"] = True
A.panel_yaz(d)
kontrol("başka panel ayarı yazılınca tema tercihi korunur", A.tema_tercihi() == "sistem")
os.remove(yol)

# ---------------------------------------------------------------- UX-K: renk ayrımı (ΔE2000)
sys.path.insert(0, os.path.join(KOK, "tests", "yardimci"))
import kwin_renk as KR  # noqa: E402

from deskhand.masaustu import ZEMIN as XVFB_KOK  # noqa: E402

DE_MIN = T["renk_ayrim_min_de"]
kontrol("renk_ayrim_min_de tokens.json'da (20)", DE_MIN == 20, str(DE_MIN))
zeminler = {"pencere": KR.ZEMIN, "kwin_kok": (0, 0, 0),
            "xvfb_kok": ((XVFB_KOK >> 16) & 255, (XVFB_KOK >> 8) & 255, XVFB_KOK & 255)}
hepsi = {**KR.ALGILANAN, **zeminler}
adlar = list(hepsi)
for i, a1 in enumerate(adlar):
    for a2 in adlar[i + 1:]:
        if a1 in zeminler and a2 in zeminler:
            continue
        de = uret.de2000(KR.hex_(hepsi[a1]), KR.hex_(hepsi[a2]))
        kontrol(f"test penceresi: {a1} ~ {a2} ΔE2000 ≥ {DE_MIN}", de >= DE_MIN, f"{de:.1f}")
for ad, r in KR.ALGILANAN.items():
    kontrol(f"test penceresi: {ad} sert renk değil (macenta/camgöbeği/sarı yok: kanal 0/255 ikilisi değil)",
            not all(c in (0, 255) for c in r), str(r))
with open(os.path.join(KOK, "tests", "yardimci", "kwin_test_pencere.py"), encoding="utf-8") as f:
    kp = f.read().lower()
kontrol("test penceresi eski sert renkleri kullanmaz", not any(h in kp for h in ("#ff00ff", "#00ffff", "#ffff00")))

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
