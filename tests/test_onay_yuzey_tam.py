"""Bulgu sınıfı "onay yüzeyinde içerik kesilmesi" (UX-C-R1c): otomatik kural.

300+ karakterlik komut (sonu benzersiz işaret) ve 5000 karakterlik ayrıntıyla istek kurulur; HER onay yüzeyinde
(diyalog görünür metni, tepsi bildirimi gövdesi, Onaylar sekmesi tablosu, CLI, istek dosyası) ya işaret GÖRÜNÜR ya
da yüzey açıkça "kısaltıldı / tamamı onay penceresinde" der VE o yüzeyden izin VERİLEMEZ. AYRINTI_SINIR aşımında
sessiz kesme yok; eylem sınırı aşılırsa istek kapalı-başarısız (red + görünür neden). Taşan komut kutusunda "Son kısım"
satırı görünür ve izin düğmesi kutu sona kaydırılana dek pasif. Gizli yazı hiçbir yüzeyde yok.

Qt GÖRÜNMEZ (offscreen), geçici HOME/XDG (_yalitim). Çalıştır:  python3 tests/test_onay_yuzey_tam.py"""
import inspect
import json
import os
import re
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QPlainTextEdit, QWidget  # noqa: E402

from deskhand import cli, guvenlik, i18n, onay  # noqa: E402
from deskhand.gui import tepsi  # noqa: E402
from deskhand.gui.onay_diyalog import OnayDiyalog  # noqa: E402
from deskhand.gui.sekmeler.onaylar import OnaylarSekmesi  # noqa: E402

app = QApplication([])
gecen = toplam = 0
_ = i18n._
i18n.sifirla("tr", i18n.katalog_oku("tr"))


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


SON = "#SON"
KOMUT = "echo " + "zararsiz-" * 40 + "; rm -rf ~ " + SON            # ~375 karakter: tehlike + işaret SONDA
UZUN_KOMUT = "echo " + "zararsiz-" * 200 + "; rm -rf ~ " + SON       # kutuyu taşırır
AYRINTI = "yikici olabilir\n" + "A" * 4990 + " #AYRSON"
S = time.time()
KISALTILDI = re.compile(r"kısaltıldı|tamamı onay penceresinde")


def istek(komut, **ek):
    d = {"id": "c" * 32, "konu": "ucbirim", "eylem": _("Uçbirime komut yaz: {komut}").format(
        komut=guvenlik._yazilacak(komut, False)), "hedef": "~ : zsh — Konsole",
        "ayrinti": onay.ayrinti_sinirla(AYRINTI), "masaustu": "ekran", "masa": "", "zaman": S, "son_zaman": S + 118,
        "pid": 4242, "tur": ""}
    d.update(ek)
    return d


def gorunen(d) -> str:
    return "\n".join([w.text() for w in d.findChildren(QLabel) if w.isVisible()] +
                     [w.toPlainText() for w in d.findChildren(QPlainTextEdit) if w.isVisible()])


def tum(d) -> str:
    out = [d.windowTitle()]
    for w in d.findChildren(QWidget):
        out.append(w.toolTip())
        if isinstance(w, (QLabel, QAbstractButton)):
            out.append(w.text())
        if isinstance(w, QPlainTextEdit):
            out.append(w.toPlainText())
    return "\n".join(out)


def diyalog(i, **k):
    k.setdefault("kurma_ms", 0)
    yan = k.pop("yanitlar", [])
    d = OnayDiyalog(i, yanitla=lambda a, b: yan.append(b) or True, istek_var=lambda: True, saat=lambda: S, **k)
    d.show()
    app.processEvents()
    return d


# ================================================================ 1. istek dosyası (onay.py)
print("1) istek dosyası: sessiz kesme yok; eylem sınırı aşımı kapalı-başarısız")
a = onay.ayrinti_sinirla(AYRINTI)
kontrol("5000 karakterlik ayrıntı: sınırda + görünür '(kısaltıldı…)' işareti", len(a) <= onay.AYRINTI_SINIR
        and KISALTILDI.search(a[-80:]) is not None, a[-80:])
kontrol("sınır içindeki ayrıntı olduğu gibi", onay.ayrinti_sinirla("kisa #X") == "kisa #X")
s = onay.iste_sonuc("x" * (onay.EYLEM_SINIR + 1), "h", "a")
kontrol("eylem sınırı aşımı → red, neden 'cok-uzun', görünür ileti 'çok uzun'", not s.izin and s.neden == "cok-uzun"
        and "çok uzun" in s.mesaj, str(s))
with tempfile.TemporaryDirectory() as td:
    def oku(**alan):
        kid = "d" * 32
        yol = os.path.join(td, f"istek-{kid}.json")
        with open(yol, "w", encoding="utf-8") as f:
            json.dump({"id": kid, "hedef": "", "son_zaman": S + 10, **alan}, f)
        return onay.istek_oku(yol)
    r = oku(eylem="x", ayrinti="B" * 6000 + SON)
    kontrol("istek_oku: sınırı aşan ayrıntı sessiz kesilmez (görünür işaret)", r is not None
            and KISALTILDI.search(r["ayrinti"][-80:]) is not None, (r or {}).get("ayrinti", "")[-80:])
    r = oku(eylem="y" * (onay.EYLEM_SINIR + 1), ayrinti="")
    kontrol("istek_oku: eylem sınırı aşımı → geçersiz istek (gösterilmez, onaylanamaz)", r is None)
    i = istek(KOMUT)
    r = oku(eylem=i["eylem"], ayrinti=i["ayrinti"])
    kontrol("istek dosyası: 375 karakterlik komutun işareti eylem alanında tam", r and r["eylem"].endswith(SON + "'"),
            (r or {}).get("eylem", "")[-40:])

# ================================================================ 2. diyalog
print("2) diyalog: işaret görünür; taşan kutuda 'Son kısım' + izin yalnız sona kaydırınca")
d = diyalog(istek(KOMUT))
kontrol("komut: işaret görünür (kutu)", SON in gorunen(d), gorunen(d)[-200:])
d.close()
d = diyalog(istek("x", eylem="Tamamen bilinmeyen " + KOMUT, konu=""))
kontrol("bilinmeyen istek: eylem kesilmez, işaret görünür", d.ileti["tur"] == "bilinmeyen" and SON in gorunen(d)
        and "…" not in d.k_icerik.toPlainText(), gorunen(d)[:300])
d.close()
d = diyalog(istek("x", hedef="Pencere " + "b" * 300 + SON))
kontrol("uzun pencere adı: kesilirse görünür '(kısaltıldı)'", SON in d.l_hedef.text()
        or _("(kısaltıldı)") in d.l_hedef.text(), d.l_hedef.text()[-60:])
d.close()

yan = []
d = diyalog(istek(UZUN_KOMUT), yanitlar=yan)
sb = d.k_icerik.verticalScrollBar()
kontrol("taşan kutu: 'Son kısım' satırı görünür ve işareti taşır", sb.maximum() > 0 and d.l_son.isVisible()
        and SON in d.l_son.text() and d.l_son.textFormat() == Qt.TextFormat.PlainText, d.l_son.text())
kontrol("taşan kutu: izin pasif, düğme 'önce sona kaydırın' der", not d.b_izin.isEnabled()
        and _("önce sona kaydırın") in d.b_izin.text(), d.b_izin.text())
QTest.mouseClick(d.b_izin, Qt.MouseButton.LeftButton)
d._karar("izin")
kontrol("kaydırmadan izin tıklaması izin üretmez", "izin" not in yan and not d.bitti, str(yan))
QTest.keyClick(d, Qt.Key.Key_Return)
kontrol("Enter → red (izin değil)", yan == ["red"], str(yan))
d.close()

yan = []
d = diyalog(istek(UZUN_KOMUT), yanitlar=yan, kurma_ms=400, hareket_px=0)
sb = d.k_icerik.verticalScrollBar()
sb.setValue(sb.maximum())
app.processEvents()
kontrol("sona kaydırıldı ama bekleme sürüyor → izin hâlâ pasif", not d.b_izin.isEnabled(), d.b_izin.text())
d._kur()
kontrol("sona kaydırıldı + bekleme bitti → izin etkin", d.b_izin.isEnabled(), d.b_izin.text())
d._karar("izin")
kontrol("…ve izin verilebilir", yan == ["izin"], str(yan))
kontrol("Reddet her zaman etkin", d.b_red.isEnabled())

yan = []
d = diyalog(istek(UZUN_KOMUT), yanitlar=yan, kurma_ms=400, hareket_px=0)
d._kur()
kontrol("bekleme bitti ama sona kaydırılmadı → izin pasif", not d.b_izin.isEnabled(), d.b_izin.text())
sb = d.k_icerik.verticalScrollBar()
sb.setValue(sb.maximum())
app.processEvents()
kontrol("sonra sona kaydırınca → etkin", d.b_izin.isEnabled(), d.b_izin.text())
d.close()

d = diyalog(istek("ls -la"))
kontrol("taşmayan kutu: davranış aynı (kurma_ms=0 → izin etkin, Son kısım yok)", d.b_izin.isEnabled()
        and not d.l_son.isVisible())
d.close()

# ================================================================ 3. tepsi bildirimi
print("3) tepsi: gövde kesilirse 'tamamı onay penceresinde'; tepsiden izin yok")
for ad_, i in (("komut", istek(KOMUT)), ("devir", istek(KOMUT, tur="devir", ayrinti="neden " * 60 + SON)),
               ("kısa devir", istek(KOMUT, tur="devir", ayrinti="kısa neden " + SON))):
    g = tepsi.bildirim_govdesi(i)
    kontrol(f"tepsi ({ad_}): işaret görünür ya da 'tamamı onay penceresinde'", SON in g or KISALTILDI.search(g), g)
kontrol("tepsi kodu izin vermez (yanitla yok; tık yalnız diyaloğu açar)",
        "yanitla" not in inspect.getsource(tepsi) and "onay_istendi.emit" in inspect.getsource(tepsi.Tepsi))

# ================================================================ 4. Onaylar sekmesi
print("4) Onaylar sekmesi: yalnız görüntü (izin yok), hücrede tam + temiz metin")
o = OnaylarSekmesi()
i = istek(KOMUT + "\u202e")
o.guncelle([{**i, "eylem": i["eylem"] + "\u202e\u200b"}])
h = o.t_bekleyen.item(0, 1)
kontrol("tablo hücresi: komut tam (işaret var), yön/sıfır genişlik yok, ipucu tam", SON in h.text()
        and not re.search("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", h.text()) and SON in h.toolTip(), h.text()[-60:])
kaynak = inspect.getsource(sys.modules[OnaylarSekmesi.__module__])
kontrol("Onaylar sekmesi izin veremez (yanitla yok; yalnız 'Diyaloğu aç')", "yanitla" not in kaynak
        and "ac_istendi.emit" in kaynak)

# ================================================================ 5. CLI
print("5) CLI: onay listeleme/yanıt yolu yok")
ck = inspect.getsource(cli)
kontrol("cli.py bekleyen onayları listelemez/yanıtlamaz (bekleyenler/yanitla yok)",
        "bekleyenler(" not in ck and "yanitla(" not in ck)

# ================================================================ 6. gizli yazı hiçbir yüzeyde yok
print("6) gizli yazı hiçbir yüzeyde yok")
SIR = "gizli-sir-Q9 #SON"
gi = istek("x", eylem=_("Uçbirime komut yaz: {komut}").format(komut=guvenlik._yazilacak(SIR, True)),
           hedef=_("(başlık gizlendi)"), ayrinti="x\n" + _("yazılacak: {metin}").format(metin=guvenlik._yazilacak(SIR, True)))
d = diyalog(gi)
d.ayrinti_ac(True)
app.processEvents()
o.guncelle([gi])
yuzey = tum(d) + tepsi.bildirim_govdesi(gi) + "".join(
    (o.t_bekleyen.item(0, j).text() + o.t_bekleyen.item(0, j).toolTip()) for j in range(o.t_bekleyen.columnCount())
    if o.t_bekleyen.item(0, j))
kontrol("gizli içerik diyalog/tepsi/tablo yüzeylerinde YOK", "gizli-sir" not in yuzey)
d.close()

print(f"\n{gecen}/{toplam} test geçti")
sys.exit(0 if gecen == toplam else 1)
