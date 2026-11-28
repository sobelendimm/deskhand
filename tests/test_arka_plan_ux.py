"""Arka plan ekranı UX (UX-D: O1, O2, O3): önizleme sekmenin tam genişliğinde ve gri bantsız, masaüstü listesi yalnız
≥2 masaüstünde, "Kontrolü al / Geri ver" + belirgin "Kontrol sizde" bandı, kontrol sizdeyken hızlı kare (≤150 ms) +
girdiden hemen sonra kare, izlemede değişmeyen karede yeniden çizim yok, yasak pencere maskesi hızlı yolda ve
büyütülmüş görünümde de, DUR'da girdi gönderilmez ve bant DUR'u gösterir, önizleme hatası insan diliyle.

Qt GÖRÜNMEZ (offscreen), arka uç ve masaustu modülü SAHTE: gerçek masaüstü açılmaz, girdi gönderilmez.
Çalıştır:  python3 tests/test_arka_plan_ux.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand import guvenlik  # noqa: E402

app = QApplication([])
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def bekle(kosul, sure=3.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        app.processEvents()
        if kosul():
            return True
        time.sleep(0.005)
    app.processEvents()
    return kosul()


EKRAN = (1280, 720)
YASAK = (100, 100, 400, 300)  # yasak pencerenin geometrisi (x, y, g, y)


class SahteGirdi:
    def __init__(self):
        self.satirlar = []

    def ham(self, s):
        self.satirlar.append(s)

    insan_ham = ham

    def kapat(self):
        pass


class SahteArka:
    """1280x720 gri ekran; `yasak` açıkken YASAK geometrisinde kırmızı, sınıfı 'deskhand' (yasak) bir pencere."""

    def __init__(self):
        self.renk = (90, 90, 90)
        self.yasak = False
        self.kareler = 0
        self.liste_cagri = 0
        self.girdiler = []

    def goruntu(self):
        self.kareler += 1
        im = Image.new("RGB", EKRAN, self.renk)
        if self.yasak:
            x, y, g, h = YASAK
            im.paste((255, 0, 0), (x, y, x + g, y + h))
        return im

    def ekran_alani(self):
        return (0, 0, *EKRAN)

    def pencereler(self, desen=None):
        self.liste_cagri += 1
        return [("w1", "gizli", YASAK)] if self.yasak else []

    def sinif(self, k):
        return "deskhand"

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        g = SahteGirdi()
        self.girdiler.append(g)
        return g


MASALAR = [{"ad": "", "ekran": ":90", "baslangic": time.time() - 60, "durum": {"ekran": ":90", "boyut": [*EKRAN, 24]}}]


class SahteMasaustu:
    @staticmethod
    def durum(dogrula=True, saglik=True, ad=None):
        return {"ekran": ":90", "boyut": [*EKRAN, 24]}

    @staticmethod
    def masaustu_baslat(*a, **k):
        pass

    @staticmethod
    def masaustu_durdur(*a, **k):
        return True, []


from deskhand.gui.pencere import ArkaPlanSekmesi  # noqa: E402

arka = SahteArka()
liste = list(MASALAR)
devral_yol = os.path.join(_yalitim.GECICI, "devral")
a = ArkaPlanSekmesi(arka_f=lambda: arka, masaustu_m=SahteMasaustu, masalar_f=lambda: list(liste),
                    devral_yolu_f=lambda: devral_yol)
a.resize(1000, 900)
a.show()
a.sanal_guncelle(SahteMasaustu.durum())
kontrol("önizleme görüntüsü geldi", bekle(lambda: a.onizleme.resim is not None))
app.processEvents()

# ---- O2: tam genişlik, bant yok, liste yalnız ≥2 masaüstünde
on = a.onizleme
oran = on.width() / a.width()
kontrol("önizleme sekme genişliğinin ≥%95'i", oran >= 0.95, f"{on.width()}/{a.width()} = {oran:.3f}")
r = on.hedef_rect()
kontrol("gri bant yok (görüntü önizleme alanını doldurur)", abs(r.width() - on.width()) <= 1 and
        abs(r.height() - on.height()) <= 1, f"rect {r.width():.0f}x{r.height():.0f} alan {on.width()}x{on.height()}")
a.masalar_yenile()
kontrol("tek masaüstünde liste gizli", a.agac.isHidden())
liste.append({"ad": "k7", "ekran": ":92", "baslangic": time.time() - 30, "durum": {"ekran": ":92", "boyut": [*EKRAN, 24]}})
a.masalar_yenile()
kontrol("iki masaüstünde liste görünür", not a.agac.isHidden())
liste.pop()
a.masalar_yenile()
kontrol("yeniden tek masaüstü: liste gizli", a.agac.isHidden())

# ---- O3 (izleme): değişmeyen karede yeniden çizim yok
cizim = []
asil_goster = on.goster
on.goster = lambda *x, **k: (cizim.append(x[0] if x else None), asil_goster(*x, **k))
a.kare()
n0 = len(cizim)
a.kare()
a.kare()
kontrol("izleme: değişmeyen karede yeniden çizim yok", len(cizim) == n0, f"{len(cizim)} çizim")
arka.renk = (30, 120, 30)
a.kare()
kontrol("izleme: ekran değişince çizilir", len(cizim) == n0 + 1)
kontrol("izleme aralığı değişmedi (1 sn)", a.zaman.interval() == 1000, str(a.zaman.interval()))

# ---- güvenlik: maske hızlı yolda ve büyütülmüş görünümde


def kirmizi_var(q) -> bool:
    if q is None or q.isNull():
        return False
    sx, sy = q.width() / EKRAN[0], q.height() / EKRAN[1]
    x, y, g, h = YASAK
    return any(q.pixelColor(int((x + i * g / 10) * sx), int((y + j * h / 10) * sy)).red() > 200 and
               q.pixelColor(int((x + i * g / 10) * sx), int((y + j * h / 10) * sy)).green() < 60
               for i in range(1, 10) for j in range(1, 10))


arka.yasak = True
l0 = arka.liste_cagri
a.kare()
kontrol("yasak pencere: önizlemede karartılmış", on.resim is not None and not kirmizi_var(on.resim))
n1 = len(cizim)
a.kare()
a.kare()
kontrol("hızlı yol (çizimsiz kare) de maskeyi her karede denetler",
        len(cizim) == n1 and arka.liste_cagri >= l0 + 6 and not kirmizi_var(on.resim), f"liste {arka.liste_cagri - l0}")
a.b_buyut.click()
kontrol("Büyüt: büyük görünüm açıldı", bekle(lambda: a.buyuk is not None and a.buyuk.isVisible(), 2))
a.kare()
kontrol("büyütülmüş görünümde de yasak pencere karartılmış",
        a.buyuk.onizleme.resim is not None and not kirmizi_var(a.buyuk.onizleme.resim))
kontrol("büyük görünüm kaynak boyutunda keskin (küçültülmemiş ya da büyük)",
        a.buyuk.onizleme.resim.width() >= min(EKRAN[0], a.buyuk.onizleme.hedef_boyut().width()) - 1,
        f"{a.buyuk.onizleme.resim.width()}")
a.buyuk.close()
app.processEvents()
arka.yasak = False

# ---- büyük görünümden çıkış (kullanıcı 28 Kas: "küçültüp çıkamıyorum")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

b = a.buyuk
assert b is not None
a._son_imza = None
a.kare()
kontrol("kapatılan büyük görünüm kare() ile kendiliğinden yeniden açılmaz", not b.isVisible())
a.b_buyut.click()
kontrol("şerit: başlık ve Küçült düğmesi görünür",
        bekle(b.isVisible) and b.l_baslik.text() == "Arka plan masaüstü — büyük görünüm" and
        b.b_kucult.text() == "Küçült" and b.b_kucult.isVisible(), f"{b.l_baslik.text()!r} {b.b_kucult.text()!r}")
kontrol("Devral kapalı: şerit uyarısı gizli", b.l_devral.isHidden())
b.onizleme.setFocus()
QTest.keyClick(b.onizleme, Qt.Key.Key_Escape)
kontrol("Devral kapalı: Esc büyük görünümü kapatır", bekle(lambda: not b.isVisible(), 1))
a.b_buyut.click()
bekle(b.isVisible)
QTest.mouseClick(b.b_kucult, Qt.MouseButton.LeftButton)
kontrol("Küçült büyük görünümü kapatır", bekle(lambda: not b.isVisible(), 1))
arka.renk = (40, 160, 40)
a.kare()
kontrol("Küçült sonrası sekmedeki küçük önizleme sürer",
        on.resim is not None and on.resim.pixelColor(5, 5).green() > 120 and a.zaman.isActive(),
        str(on.resim.pixelColor(5, 5).getRgb() if on.resim is not None else None))
for _ in range(3):
    a._son_imza = None
    a.kare()
    a._zamanlayici()
    app.processEvents()
kontrol("Küçült sonrası kareler büyük görünümü yeniden açmaz", not b.isVisible())
a.b_buyut.click()
bekle(b.isVisible)
a.b_devral.setChecked(True)
app.processEvents()
kontrol("Devral açık: şerit Esc'in arka plana gittiğini ve Küçült'ü söyler",
        not b.l_devral.isHidden() and b.l_devral.text() == "Devral açık: Esc arka plana gider; çıkmak için Küçült",
        b.l_devral.text())
gelen = []
b.onizleme.satirlar.connect(gelen.append)
b.onizleme.setFocus()
QTest.keyClick(b.onizleme, Qt.Key.Key_Escape)
app.processEvents()
kontrol("Devral açık: Esc arka plana gider, pencere açık kalır", gelen == [["key esc"]] and b.isVisible(), str(gelen))
b.onizleme.satirlar.disconnect(gelen.append)
QTest.mouseClick(b.b_kucult, Qt.MouseButton.LeftButton)
kontrol("Devral açık: Küçült yine kapatır", bekle(lambda: not b.isVisible(), 1))
a.b_devral.setChecked(False)
app.processEvents()
kontrol("Devral kapanınca şerit uyarısı gizlenir", b.l_devral.isHidden())
a.zaman.stop()

# ---- O1: Kontrolü al / Geri ver + bant
kontrol("düğme adı: Kontrolü al", a.b_devral.text() == "Kontrolü al", a.b_devral.text())
kontrol("kontrol ajandayken bant gizli", a.bant.isHidden())
a.b_devral.setChecked(True)
app.processEvents()
kontrol("kontrol sizde: düğme Geri ver", a.b_devral.text() == "Geri ver", a.b_devral.text())
kontrol("kontrol sizde: belirgin bant görünür", not a.bant.isHidden() and "Kontrol sizde" in a.l_bant.text(),
        a.l_bant.text())
kontrol("kontrol sizde: kare aralığı 100–150 ms", 100 <= a.zaman.interval() <= 150, str(a.zaman.interval()))
a.zaman.stop()
k0 = arka.kareler
a.gonder(["key a"])
kontrol("girdiden hemen sonra kare (≤100 ms)", bekle(lambda: arka.kareler > k0, 0.1), f"{arka.kareler - k0}")
g = arka.girdiler[-1] if arka.girdiler else SahteGirdi()
kontrol("kontrol sizde: girdi iletildi", g.satirlar == ["key a"], str(g.satirlar))

# ---- DUR: girdi iletimi 0, bant DUR'u gösterir
g.satirlar.clear()
guvenlik.dur_ac("kullanici")
try:
    a.gonder(["key b", "mouseto 0.5 0.5"])
    a.kare()
    kontrol("DUR açık: girdi iletimi çağrısı 0", g.satirlar == [], str(g.satirlar))
    kontrol("DUR açık: bant DUR durumunu gösterir", not a.bant.isHidden() and "DUR" in a.l_bant.text(), a.l_bant.text())
finally:
    guvenlik.dur_kapat("kullanici")
a.kare()
kontrol("DUR kalkınca bant yine 'Kontrol sizde'", "Kontrol sizde" in a.l_bant.text() and "DUR" not in a.l_bant.text(),
        a.l_bant.text())
a.b_bant_geri.click()
app.processEvents()
kontrol("bandın Geri ver düğmesi kontrolü bırakır", not a.b_devral.isChecked() and a.bant.isHidden() and
        a.b_devral.text() == "Kontrolü al" and not os.path.exists(devral_yol))

# ---- yer tutucular (işlevsiz)
kontrol("yer tutucu: Durdur ve Duraklat düğmeleri pasif, ipucu var",
        not a.b_ajan_durdur.isEnabled() and not a.b_duraklat.isEnabled() and a.b_ajan_durdur.toolTip() and
        a.b_duraklat.toolTip())

# ---- O-hata: insan dili, ham istisna yok
a.arka_f = lambda: None
a.kare()
m = on.bos_metin
kontrol("önizleme hatası insan dili (ham Python iletisi yok)", m and "NoneType" not in m and "attribute" not in m
        and "object" not in m, m)
kontrol("hata ayrıntısı katlı (varsayılan gizli)", a.l_hata_ayrinti.isHidden())


class Patlayan(SahteArka):
    def pencereler(self, desen=None):
        raise RuntimeError("kdotool: dbus org.kde.KWin hata 0x5")


a.arka_f = lambda: Patlayan()
a.kare()
m = on.bos_metin
kontrol("maske hatası insan dili, ham metin yok", m and "kdotool" not in m and "0x5" not in m and on.resim is None, m)

print(f"\n{gecen}/{toplam} arka plan UX testi geçti")
sys.exit(0 if gecen == toplam else 1)
