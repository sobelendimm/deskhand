"""Panelin "Arka plan ekranı" sekmesi, çoklu görünmez masaüstü İZLEME (Faz B): masaüstü seçici (çalışan bütün arka plan
masaüstleri, ne zamandır açık, son etkinlik), seçilen masaüstünün canlı önizlemesi (gizliyken yenileme yok, yasak
pencereler karartılır), "ajan şu an ne yapıyor" satırı (gizli alana yazılan metin ASLA görünmez) ve önizlemeden adlı
masaüstüne yeni girdi yolu OLMADIĞI. Qt GÖRÜNMEZ (QT_QPA_PLATFORM=offscreen), arka uçlar ve masaustu modülü SAHTE: gerçek
masaüstü açılmaz, girdi gönderilmez.

Çalıştır:  python3 tests/test_masa_izleme.py   (DESKHAND_EKRAN_GORUNTUSU=<yol.png>: sekmenin ekransız görüntüsünü kaydet)"""
import json
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

from PIL import Image, ImageDraw  # noqa: E402
from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand import masalar  # noqa: E402
from deskhand.gui import durum as D  # noqa: E402
from deskhand.gui import gunluk_okur as G  # noqa: E402
from deskhand.gui import metinler as T  # noqa: E402

app = QApplication([])
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def bekle(kosul, sure=3.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        app.processEvents()
        if kosul():
            return True
        time.sleep(0.01)
    app.processEvents()
    return kosul()


# =========================================================================== 1) günlük: masaüstü + etiket + maske
d = G.ayristir("10:00:00 tikla (617,761) sol | arka deskhand-d51df383 [Netlify — Firefox] | click left")
kontrol("ayrıştır: KWin masaüstünün ekran adı ve etiketi", d["ekran"] == "deskhand-d51df383" and
        d["etiket"] == "tikla (617,761) sol" and d["gizli"] is False, str(d))
d = G.ayristir("10:00:01 yaz 8 karakter | arka :91 [Giriş] | type ***")
kontrol("ayrıştır: gizli yazı işaretlenir", d["gizli"] is True and d["ekran"] == ":91")
d = G.ayristir("10:00:02 tus *** | arka :91 [Giriş] | key ***")
kontrol("ayrıştır: gizli tuş işaretlenir", d["gizli"] is True)
d = G.ayristir("10:00:03 tikla (1,1) sol | [Kendi Ekranım] | click left")
kontrol("ayrıştır: kullanıcının ekranında ekran adı boş", d["ekran"] == "" and d["arka"] == "ekran")

# =========================================================================== 2) süre + son eylem + gizlilik
kontrol("süre metni", (D.sure_metni(12), D.sure_metni(300), D.sure_metni(7380)) == ("12 sn", "5 dk", "2 sa 3 dk"))
simdi = time.mktime(time.strptime("2026-11-24 12:00:30", "%Y-%m-%d %H:%M:%S"))
kontrol("saat → epoch (bugün)", D.saat_epoch("12:00:18", simdi) == simdi - 12)
kontrol("saat → epoch (gece yarısından önce = dün)", D.saat_epoch("23:59:00", simdi) < simdi)

se = D.SonEylemler()
se.ekle([G.ayristir(s) for s in (
    "12:00:10 tikla (5,5) sol | arka :91 [Belge] | click left",
    "12:00:18 ogeye-tikla 'Kaydet' sol | arka :91 [Belge — KWrite] | click left",
    "12:00:20 yaz 6 karakter | arka :92 [Giriş — Firefox] | type ***",
    "12:00:21 tikla (9,9) sol | [Kendi Ekranım] | click left",
    "12:00:22 DUR 13 | tikla arka:0x1 | kullanıcı DUR dedi",
    "12:00:23 yaz 6 karakter | arka :93 [Not] | type gizliparola123",
)], simdi)
s91 = D.eylem_satiri(se.son(":91"), simdi)
kontrol("ajan şu an: son eylem + pencere + 'N sn önce'", "ogeye-tikla 'Kaydet' sol" in s91 and "Belge — KWrite" in s91
        and "12 sn önce" in s91, s91)
s92 = D.eylem_satiri(se.son(":92"), simdi)
kontrol("ajan şu an: gizli alana yazı → içerik yok, gizli metni", T.A_EYLEM_GIZLI in s92 and "***" not in s92,
        s92)
s93 = D.eylem_satiri(se.son(":93"), simdi)
kontrol("ajan şu an: günlüğün satırlar kısmı (type …) HİÇ gösterilmez", "gizliparola123" not in s93 and
        "yaz 6 karakter" in s93, s93)
kontrol("ajan şu an: kullanıcının ekranı ve DUR satırları sayılmaz", se.son("") is None and len(se._son) == 3)
kontrol("ajan şu an: masaüstü açılışından önceki kayıt (aynı ekran adı) yok sayılır", se.son(":91", simdi) is None)
kontrol("ajan şu an: eylem yoksa açık ileti", D.eylem_satiri(None, simdi) == T.A_EYLEM_YOK)
kontrol("etikette yazı satırı izi (savunma) → gizli", D.guvenli_eylem({"etiket": "dizi: type sır"}) == T.A_EYLEM_GIZLI)

# =========================================================================== 3) masaüstü listesi (salt okuma)
EKRAN = {"": ":91", "k7": ":92", "yayin": "deskhand-ab12"}
ACIK = {"": True, "k7": True, "yayin": True}
BAS = time.time() - 125


def kayit_yaz(ad):
    """Adlı masaüstünün sanal.json'u (masalar.adlar() dizinden okur)."""
    os.makedirs(masalar.kok(ad), mode=0o700, exist_ok=True)
    with open(masalar.durum_yolu(ad), "w") as f:
        json.dump({"ekran": EKRAN[ad]}, f)


for ad_ in ("k7", "yayin"):
    kayit_yaz(ad_)


class SahteMasaustu:
    """masaustu modülünün SALT OKUMA yüzü: durum(saglik, ad). Başlat/durdur çağrısı sayılır (olmamalı)."""
    yazma = 0

    @staticmethod
    def durum(dogrula=True, saglik=True, ad=None):
        ad = masalar.secili() if ad is None else ad
        if not ACIK.get(ad):
            return None
        return {"ekran": EKRAN[ad], "boyut": [1280, 720, 24], "tur": "kwin", "baslangic": BAS}

    @classmethod
    def masaustu_baslat(cls, *a, **k):
        cls.yazma += 1

    @classmethod
    def masaustu_durdur(cls, *a, **k):
        cls.yazma += 1
        return True, []


liste = D.masa_listesi(SahteMasaustu)
kontrol("liste: varsayılan + adlı masaüstleri (sıralı)", [m["ad"] for m in liste] == ["", "k7", "yayin"],
        str([m["ad"] for m in liste]))
kontrol("liste: ekran adı ve açılış zamanı", liste[2]["ekran"] == "deskhand-ab12" and liste[1]["baslangic"] == BAS)
ACIK["yayin"] = False
kontrol("liste: kapanan masaüstü listelenmez", [m["ad"] for m in D.masa_listesi(SahteMasaustu)] == ["", "k7"])
ACIK["yayin"] = True
kontrol("liste hiçbir masaüstünü başlatmadı/durdurmadı", SahteMasaustu.yazma == 0)


class EskiMasaustu:  # `ad` parametresi olmayan eski modül: yalnız varsayılan okunur
    @staticmethod
    def durum(dogrula=True):
        return {"ekran": ":91"}


kontrol("liste: ad parametresiz modülde yalnız varsayılan", [m["ad"] for m in D.masa_listesi(EskiMasaustu)] == [""])

# =========================================================================== 4) sekme: seçici + canlı önizleme
RENK = {"": (200, 40, 40), "k7": (40, 200, 40), "yayin": (40, 40, 200)}
PENCERELER = {"": [], "k7": [], "yayin": []}


class SahteGirdi:
    def __init__(self, masa):
        self.masa, self.satirlar = masa, []

    def ham(self, s):
        self.satirlar.append(s)

    insan_ham = ham

    def kapat(self):
        pass


class SahteArka:
    """Masaüstü başına sahte arka uç (masalar.secili() bağlamına göre: sec(arka_bayragi=True) gibi)."""

    def __init__(self):
        self.kareler = {"": 0, "k7": 0, "yayin": 0}
        self.girdiler = []
        self.pencere_hatasi = False

    def goruntu(self):
        masa = masalar.secili()
        self.kareler[masa] += 1
        return Image.new("RGB", (1280, 720), RENK[masa])

    def ekran_alani(self):
        return (0, 0, 1280, 720)

    def pencereler(self, desen=None):
        if self.pencere_hatasi:
            raise RuntimeError("kdotool yanıt vermedi")
        return PENCERELER[masalar.secili()]

    def sinif(self, k):
        return "firefox"

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        g = SahteGirdi(masalar.secili())
        self.girdiler.append(g)
        return g


from deskhand.gui.pencere import ArkaPlanSekmesi  # noqa: E402

arka = SahteArka()
saat = [time.time()]
a = ArkaPlanSekmesi(arka_f=lambda: arka, masaustu_m=SahteMasaustu, saat=lambda: saat[0])
a.resize(1000, 760)
a.etkinlik_ekle([G.ayristir(time.strftime("%H:%M:%S", time.localtime(saat[0] - 4)) +
                            " ogeye-tikla 'Yayınla' sol | arka :92 [Panel — Firefox] | click left"),
                 G.ayristir(time.strftime("%H:%M:%S", time.localtime(saat[0] - 2)) +
                            " yaz 9 karakter | arka deskhand-ab12 [Giriş] | type ***")])
a.show()
kontrol("sekme açılınca masaüstü listesi kendiliğinden okundu", bekle(lambda: a.agac.topLevelItemCount() == 3) and
        a.liste_zaman.isActive())
satirlar = [[a.agac.topLevelItem(i).text(c) for c in range(3)] for i in range(a.agac.topLevelItemCount())]
kontrol("liste sütunları: ad (ekran), ne zamandır açık, son etkinlik",
        satirlar[0][0].startswith("varsayılan") and satirlar[1][0] == "k7  (:92)" and satirlar[1][1] == "2 dk" and
        satirlar[1][2] == "4 sn önce" and satirlar[0][2] == T.A_SON_YOK, str(satirlar))
kontrol("varsayılan seçili, önizleme onun görüntüsü", masalar.secili() == "" and
        bekle(lambda: a.onizleme.resim is not None and a.onizleme.resim.pixelColor(5, 5).red() > 150))
kontrol("varsayılanda Devral serbest", a.b_devral.isEnabled())

# k7'yi seç → önizleme ve "ajan şu an" k7'nin
a.agac.setCurrentItem(a.agac.topLevelItem(1))
a.agac.topLevelItem(1).setSelected(True)
kontrol("listeden k7 seçildi → panel bağlamı k7", masalar.secili() == "k7")
k0 = arka.kareler["k7"]
kontrol("k7'nin canlı önizlemesi düzenli yenileniyor", bekle(lambda: arka.kareler["k7"] >= k0 + 2, 3.5) and
        a.onizleme.resim.pixelColor(5, 5).green() > 150)
kontrol("ajan şu an (k7): son eylem satırı", "ogeye-tikla 'Yayınla' sol" in a.l_eylem.text() and
        "Panel — Firefox" in a.l_eylem.text(), a.l_eylem.text())
kontrol("izleme aralığı makul (Devral kapalı: 1 sn)", a.zaman.interval() == 1000)

# yalnız İZLEME: adlı masaüstünde Devral kapalı, önizlemeye tık/tuş girdi oluşturmaz
kontrol("adlı masaüstünde Devral kapalı (yalnız izleme)", not a.b_devral.isEnabled() and
        a.l_not.text() == T.A_DEVRAL_ADLI)
on = a.onizleme
QTest.mouseClick(on, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(on.width() // 2, on.height() // 2))
QTest.keyClick(on, Qt.Key.Key_A)
kontrol("önizlemeye tık/tuş → hiçbir girdi nesnesi açılmadı", arka.girdiler == [] and not on.devral)
a.b_devral.click()
kontrol("devre dışı Devral düğmesine tık etkisiz", not a.b_devral.isChecked() and arka.girdiler == [])

# gizli yazı: yayin masaüstü
a.agac.setCurrentItem(a.agac.topLevelItem(2))
a.agac.topLevelItem(2).setSelected(True)
kontrol("yayin seçildi: gizli alana yazı içeriksiz gösterilir", masalar.secili() == "yayin" and
        T.A_EYLEM_GIZLI in a.l_eylem.text() and "***" not in a.l_eylem.text(), a.l_eylem.text())

# yasak pencere önizlemede karartılır
PENCERELER["yayin"] = [("arka:{1}", "Deskhand — Onay", (100, 100, 300, 200))]
a.kare()
r = a.onizleme.resim
kx, ky = r.width() / 1280, r.height() / 720
ic = r.pixelColor(int(200 * kx), int(200 * ky))
dis = r.pixelColor(int(600 * kx), int(500 * ky))
kontrol("yasak pencere (onay penceresi) önizlemede siyah", ic.red() < 10 and ic.green() < 10 and ic.blue() < 10 and
        dis.blue() > 150, f"{ic.getRgb()} {dis.getRgb()}")
PENCERELER["yayin"] = [("arka:{2}", "Sıradan Sayfa", (100, 100, 300, 200))]
a.kare()
kontrol("yasak olmayan pencere karartılmaz", a.onizleme.resim.pixelColor(int(200 * kx), int(200 * ky)).blue() > 150)
arka.pencere_hatasi = True
a.kare()
kontrol("yasak denetimi yapılamazsa kare HİÇ gösterilmez", a.onizleme.resim is None and
        a.onizleme.bos_metin.startswith(T.A_MASKE_HATA.split("{")[0]), a.onizleme.bos_metin)
arka.pencere_hatasi = False
PENCERELER["yayin"] = []
a.kare()

# liste kendiliğinden yenilenir: masaüstü kapanınca düşer, seçili kapanınca varsayılana dönülür
ACIK["yayin"] = False
kontrol("masaüstü kapanınca liste kendiliğinden yenilendi + varsayılana dönüldü",
        bekle(lambda: a.agac.topLevelItemCount() == 2, 3.5) and masalar.secili() == "" and a.b_devral.isEnabled())
ACIK["yayin"] = True
kontrol("masaüstü açılınca listeye geldi", bekle(lambda: a.agac.topLevelItemCount() == 3, 3.5))

# ekransız ekran görüntüsü (isteğe bağlı)
a.agac.setCurrentItem(a.agac.topLevelItem(1))
a.agac.topLevelItem(1).setSelected(True)
bekle(lambda: a.onizleme.resim is not None and a.onizleme.resim.pixelColor(5, 5).green() > 150)
yol = os.environ.get("DESKHAND_EKRAN_GORUNTUSU")
if yol:
    kontrol("ekransız sekme görüntüsü kaydedildi", a.grab().save(yol))

# gizliyken yenileme yok
a.hide()
app.processEvents()
k1 = dict(arka.kareler)
time.sleep(1.3)
app.processEvents()
kontrol("sekme gizliyken önizleme + liste yenilemesi DURUR", arka.kareler == k1 and not a.zaman.isActive() and
        not a.liste_zaman.isActive())

# hiç masaüstü yok
a.show()
for k_ in ACIK:
    ACIK[k_] = False
a.masalar_yenile()
kontrol("hiç masaüstü yok: açık ileti, liste gizli, önizleme durur", not a.l_masa_yok.isHidden() and
        a.agac.isHidden() and a.sanal is None and not a.zaman.isActive() and masalar.secili() == "")
kontrol("sekme hiçbir masaüstünü başlatmadı/durdurmadı", SahteMasaustu.yazma == 0)

# =========================================================================== 5) panel: devir masaüstünde Devral serbest
for k_ in ACIK:
    ACIK[k_] = True
a.masalar_yenile()
a.devir_masa = "k7"
a.masa_sec("k7")
kontrol("onay devrinin masaüstünde Devral serbest (mevcut devir akışı)", a.b_devral.isEnabled())
a.devir_masa = None
a.masa_sec("")
a.masa_sec("k7")
kontrol("devir bitince adlı masaüstünde Devral yine kapalı", not a.b_devral.isEnabled())
a.masa_sec("")

print(f"{gecen}/{toplam} masaüstü izleme testi geçti")
sys.exit(0 if gecen == toplam else 1)
