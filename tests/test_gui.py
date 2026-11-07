"""Panel (PyQt6) testleri: Qt GÖRÜNMEZ çalışır (QT_QPA_PLATFORM=offscreen; gerçek ekrana pencere açılmaz, girdi
gitmez). Günlük ayrıştırma + kuyruk okuma, durum türetme, tepsi simgeleri, sekmeler, Etkinlik modeli/süzgeci,
onay diyaloğunun düğme mantığı (QTest tıklaması), uçtan uca onay (iste ↔ panel), DUR/Devam, önizleme (sahte ArkaUc)
+ Devral girdisi, Simgeler/Ayarlar/Sağlık, kısayol çakışma okuma, tek örnek. Genel kısayol KAYDEDİLMEZ (sahte).

Çalıştır:  python3 tests/test_gui.py"""
import os, sys, threading, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"  # kglobalshortcutsrc gerçek dosyası okunmasın
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ.setdefault("DESKHAND_DIL", "tr")  # metin denetimleri Türkçe msgid'lere göre (sistem dilinden bağımsız)

from PyQt6.QtCore import QPoint, QPointF, QSize, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand import guvenlik, hata, onay, yollar  # noqa: E402
from deskhand.gui import durum as D  # noqa: E402
from deskhand.gui import gunluk_okur as G  # noqa: E402

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


def gunluk_yolu():
    return os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))


def gunluk_ekle(*satirlar):
    os.makedirs(yollar.gunluk_dizin(), exist_ok=True)
    with open(gunluk_yolu(), "a") as f:
        for s in satirlar:
            f.write(s + "\n")


# =========================================================================== 1) günlük ayrıştırma
d = G.ayristir("17:55:59 tikla (856,657) sol | [GitHub | Ayarlar — Firefox] | mouseto 0.33 0.45")
kontrol("ayrıştır: ekran satırı", d and d["arka"] == "ekran" and d["pencere"] == "GitHub | Ayarlar — Firefox" and
        d["eylem"] == "tikla (856,657) sol: mouseto 0.33 0.45" and d["tur"] == "girdi" and d["zaman"] == "17:55:59", str(d))
d = G.ayristir("10:00:00 yaz 3 karakter | arka :90 [Belge — KWrite] | type 'şğı'")
kontrol("ayrıştır: arka satırı", d["arka"] == "arka" and d["pencere"] == "Belge — KWrite" and "type 'şğı'" in d["eylem"])
d = G.ayristir("17:45:27 DUR 4 | yaz {d7bf} | başlık değişti: 'x' (beklenen /y/)")
kontrol("ayrıştır: DUR satırı", d["tur"] == "dur" and d["eylem"].startswith("DUR 4 · yaz:") and d["pencere"] == "{d7bf}")
d = G.ayristir("17:45:27 DUR 13 | tikla arka:0x1a | kullanıcı DUR dedi")
kontrol("ayrıştır: arka kimlikli DUR", d["tur"] == "dur" and d["arka"] == "arka")
kontrol("ayrıştır: DUR anahtarı satırı", G.ayristir("10:00:00 DUR anahtarı açıldı")["tur"] == "dur")
d = G.ayristir("10:00:00 bas w | bırak | keyup w")
kontrol("ayrıştır: bırak", d["arka"] == "ekran" and "bırak keyup w" in d["eylem"])
d = G.ayristir("10:00:00 bas w | arka bırak | keyup w")
kontrol("ayrıştır: arka bırak", d["arka"] == "arka")
d = G.ayristir("10:00:00 ac | kcalc | kcalc")
kontrol("ayrıştır: ac", d["pencere"] == "kcalc" and d["eylem"] == "ac: kcalc" and d["tur"] == "girdi")
d = G.ayristir("10:00:00 onay izin | arka sanal [Ödeme] | tıkla 'Öde'")
kontrol("ayrıştır: onay", d["tur"] == "onay" and d["arka"] == "arka" and d["pencere"] == "Ödeme")
g = G.onay_gecmisi([d])
kontrol("onay geçmişi", g == [{"zaman": "10:00:00", "eylem": "tıkla 'Öde'", "hedef": "Ödeme", "masaustu": "arka",
                               "sonuc": "izin"}], str(g))
kontrol("ayrıştır: biçimsiz satır → None", G.ayristir("çöp satır") is None)
kontrol("ayrıştır: erisim (2 parça)", G.ayristir("10:00:00 erisim | ac")["eylem"] == "erisim: ac")

# =========================================================================== 2) kuyruk okuma
tmpd = os.path.join(_yalitim.GECICI, "kuyruk")
os.makedirs(tmpd)
saat = [time.mktime((2026, 11, 7, 12, 0, 0, 0, 0, -1))]
ok = G.GunlukOkuyucu(dizin_f=lambda: tmpd, saat=lambda: saat[0])
yol1 = os.path.join(tmpd, "gunluk-20261107.log")
with open(yol1, "w") as f:
    for i in range(600):
        f.write(f"12:00:00 tikla {i} | [P] | click left\n")
ilk = ok.ilk()
kontrol("ilk(): son 500 satır", len(ilk) == 500 and ilk[0]["eylem"].startswith("tikla 100") and
        ilk[-1]["eylem"].startswith("tikla 599"), f"{len(ilk)}")
kontrol("yeni(): değişiklik yok → boş", ok.yeni() == [])
with open(yol1, "a") as f:
    f.write("12:00:01 tikla A | [P] | click left\n12:00:01 tikla B | [P] | cli")
y = ok.yeni()
kontrol("yeni(): tam satır gelir, yarım satır bekler", [x["eylem"][:7] for x in y] == ["tikla A"], str(y))
with open(yol1, "a") as f:
    f.write("ck left\n")
y = ok.yeni()
kontrol("yeni(): yarım satır tamamlanınca gelir", [x["eylem"] for x in y] == ["tikla B: click left"], str(y))
with open(yol1, "w") as f:
    f.write("12:00:02 tikla K | [P] | click left\n")
y = ok.yeni()
kontrol("yeni(): dosya kırpıldı → baştan okur", [x["eylem"][:7] for x in y] == ["tikla K"], str(y))
with open(yol1, "a") as f:
    f.write("23:59:59 tikla S | [P] | click left\n")
saat[0] += 86400
with open(os.path.join(tmpd, "gunluk-20261108.log"), "w") as f:
    f.write("00:00:01 tikla Y | [P] | click left\n")
y = ok.yeni()
kontrol("yeni(): gün dönümü: eskinin kalanı + yeni dosya", [x["eylem"][:7] for x in y] == ["tikla S", "tikla Y"], str(y))
ok2 = G.GunlukOkuyucu(dizin_f=lambda: tmpd, saat=lambda: saat[0])
kontrol("ilk(): bugün az satır → dünün sonu da", [x["eylem"][:7] for x in ok2.ilk(3)] == ["tikla K", "tikla S", "tikla Y"])

# =========================================================================== 3) durum türetme
simdi = 1000.0
girdi = {"tur": "girdi", "arka": "ekran", "eylem": "tikla"}
kontrol("durum: boşta", D.durum_turet(None, None, None, simdi).ad == "bos")
kontrol("durum: yeni girdi → ekran", D.durum_turet(None, girdi, simdi - 1, simdi).ad == "ekran")
kontrol("durum: arka girdi → arka", D.durum_turet(None, dict(girdi, arka="arka"), simdi - 1, simdi).ad == "arka")
kontrol("durum: eski girdi → boşta", D.durum_turet(None, girdi, simdi - 10, simdi).ad == "bos")
kontrol("durum: son satır DUR → çalışmıyor", D.durum_turet(None, {"tur": "dur", "arka": "ekran"}, simdi, simdi).ad == "bos")
dd = D.durum_turet("kullanici", girdi, simdi, simdi, bekleyen=2, sanal={"ekran": ":90"}, devral=True)
kontrol("durum: DUR her şeyin önünde + rozet + sanal + devral", dd.ad == "dur" and dd.bekleyen == 2 and
        dd.sanal_acik and dd.sanal_ekran == ":90" and dd.devral and "siz durdurdunuz" in dd.ipucu(), dd.ipucu())

# =========================================================================== 4) tepsi simgeleri
from deskhand.gui.tepsi import Tepsi, durum_pixmap  # noqa: E402


def renk(pm, x, y):
    return QColor(pm.toImage().pixel(x, y))


for ad in ("bos", "ekran", "arka", "dur"):
    pm = durum_pixmap(D.Durum(ad=ad), 64)
    c = renk(pm, 10, 32)  # dairenin sol kenarı: işaretin dışı
    kontrol(f"tepsi simgesi rengi: {ad}", c.name() == D.RENK[ad], c.name())
pm = durum_pixmap(D.Durum(ad="bos", bekleyen=1), 64)
c = renk(pm, 58, 13)
kontrol("onay bekliyor: sarı rozet", abs(c.red() - 0xfa) < 30 and abs(c.green() - 0xb0) < 40 and c.blue() < 60, c.name())
pm = durum_pixmap(D.Durum(ad="dur"), 64)
kontrol("DUR: ortada beyaz çarpı", renk(pm, 32, 32).name() == "#ffffff")
t = Tepsi()
t.guncelle(D.Durum(ad="dur", dur_kaynak="kullanici"))
kontrol("tepsi menüsü DUR açıkken: Devam görünür, DUR gizli", t.a_devam.isVisible() and not t.a_dur.isVisible())
t.guncelle(D.Durum())
kontrol("tepsi menüsü boşta: DUR görünür", t.a_dur.isVisible() and not t.a_devam.isVisible())
kontrol("tepsi ipucu durum metni", "Boşta" in t.ikon.toolTip())
basildi = []
t.panel_istendi.connect(lambda: basildi.append(1))
t._etkin(t.ikon.ActivationReason.Trigger)
kontrol("tepsi sol tık → panel aç/kapat", basildi == [1])

# =========================================================================== 5) panel (sahte arka uç, sahte kısayol)
from PIL import Image, ImageDraw  # noqa: E402


class SahteGirdi:
    def __init__(self):
        self.satirlar, self.kapandi = [], False

    def ham(self, s):
        hata.dur_denetle()
        if s.startswith("wheel") and os.path.exists(D.devral_yolu()):
            raise hata.Dur(12, "devral")  # bugünkü sanal arka ucun davranışı
        self.satirlar.append(s)

    def insan_ham(self, s):  # sanal arka uç gibi: bırakma satırları DUR'da da geçer
        if s.split(" ", 1)[0] not in ("buttonup", "keyup"):
            hata.dur_denetle()
        if s.startswith("wheel") and os.path.exists(D.devral_yolu()):
            raise hata.Dur(12, "devral")
        self.satirlar.append(s)

    def kapat(self):
        self.kapandi = True


class SahteArka:
    def __init__(self):
        self.kareler, self.girdiler = 0, []

    def goruntu(self):
        self.kareler += 1
        im = Image.new("RGB", (1920, 1080), (140, 140, 140))
        ImageDraw.Draw(im).rectangle((100, 100, 300, 200), fill=(20, 120, 200))
        return im

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        g = SahteGirdi()
        g.denetle = denetle
        self.girdiler.append(g)
        return g


class SahteMasaustu:
    acik = False
    baslatildi = 0

    @classmethod
    def durum(cls, dogrula=True):
        return {"ekran": ":91", "boyut": [1920, 1080, 24]} if cls.acik else None

    @classmethod
    def masaustu_baslat(cls):
        cls.baslatildi += 1
        cls.acik = True
        return cls.durum()

    @classmethod
    def masaustu_durdur(cls):
        cls.acik = False
        return True, []


from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402


class SahteKisayol(QObject):
    """GenelKisayol yerine: KDE'ye HİÇBİR kayıt yapılmaz, yalnız çağrılar kaydedilir."""
    basildi = pyqtSignal()
    hata = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.cagri = []
        self.acik = False

    def ac(self, tus):
        self.cagri.append(("ac", tus))
        self.acik = True

    def kapat(self, kaydi_sil=True):
        self.cagri.append(("kapat", kaydi_sil))
        self.acik = False


cakisma_sorulan = []


def sahte_cakisma(tus):
    cakisma_sorulan.append(tus)
    return [("kwin", "disableInputCapture", "Etkin Giriş Yakalamasını Devre Dışı Bırak")] if "Shift" in tus else []


sor_cevap = [False]
gunluk_ekle("09:00:00 tikla (1,1) sol | [İlk Pencere] | click left", "09:00:01 DUR 3 | tikla {x} | aktif değil")
from deskhand.gui.panel import Panel, tek_ornek  # noqa: E402
from deskhand.gui.izleyici import Izleyici  # noqa: E402

arka = SahteArka()
kis = SahteKisayol()
from deskhand.gui.panel import baska_panel_var, soket_adi  # noqa: E402

kontrol("tek örnek: panel yokken kilit boşta", not baska_panel_var())
sunucu = tek_ornek()
kontrol("tek örnek: ilk çağrı sunucu açar", sunucu is not None and sunucu.isListening())
kontrol("tek örnek: kilit panelin ömrü boyunca tutuluyor", baska_panel_var())
os.makedirs(os.path.dirname(D.devral_yolu()), exist_ok=True)
with open(D.devral_yolu(), "w") as f_:
    f_.write("panel 999999 12345\n")  # çökmüş panelden kalan (sahibi yok)
kontrol("sahipsiz Devral dosyası: devral_var False", not D.devral_var())
saglik_sonuc = [{"ad": "kdotool", "tur": "arac", "ok": True, "not": "n"}, {"ad": "mcp", "tur": "modul", "ok": False,
                                                                          "not": "m"}]
p = Panel(app, sunucu, tepsi=False, kisayol=kis, diyalog_kurma_ms=0, arka_f=lambda: arka, masaustu_m=SahteMasaustu,
          cakisma_f=sahte_cakisma, simge_sor=lambda b, m: sor_cevap[0], saglik_f=lambda: saglik_sonuc)
w = p.pencere
kontrol("panel.pid yazıldı ve canlı", onay.panel_canli() and onay.panel_pid() == os.getpid())
kontrol("panel açılışı sahipsiz Devral dosyasını sildi", not os.path.exists(D.devral_yolu()))
kontrol("pencere başlığı sabit", w.windowTitle() == onay.PANEL_BASLIK == "Deskhand")
kontrol("6 sekme", w.sekmeler.count() == 6 and [w.sekmeler.tabText(i) for i in range(6)][0] == "Etkinlik",
        str([w.sekmeler.tabText(i) for i in range(6)]))
kontrol("kısayol varsayılan KAPALI: hiç kaydedilmedi", kis.cagri == [] and not w.ayarlar.k_acik.isChecked())
kontrol("ilk günlük satırları Etkinlik'te", w.etkinlik.model.rowCount() == 2 and
        w.etkinlik.model.satirlar[1]["tur"] == "dur")
w.show()
bekle(lambda: w.isVisible())

# ---- tek örnek: ikinci başlatma mevcut olanı öne getirir
w.hide()
kontrol("ikinci tek_ornek → None (mevcut panele mesaj)", tek_ornek() is None)
kontrol("mevcut panel öne geldi (pencere görünür)", bekle(lambda: w.isVisible()))
# yarış: mevcut panel yanıt veremiyor (soketi yok/meşgul) → ikinci örnek soketi SİLİP açılmaz
sunucu.close()
t_ = time.monotonic()
ikinci = tek_ornek(deneme_ms=300)
kontrol("tek örnek: yanıt vermeyen canlı panel varken ikinci panel AÇILMAZ (kilit)", ikinci is None and
        not os.path.exists(soket_adi()) and time.monotonic() - t_ < 2)
kontrol("tek örnek: yeniden dinleme", sunucu.listen(soket_adi()))

# ---- Etkinlik: canlı akış, DUR vurgusu, süzgeç
gunluk_ekle("09:00:02 yaz 2 karakter | arka :91 [Belge] | type 'çş'")
p.izleyici.yenile()
m = w.etkinlik.model
kontrol("yeni günlük satırı akışa eklendi", m.rowCount() == 3 and m.satirlar[-1]["pencere"] == "Belge")
idx = m.index(1, 0)
bg = m.data(idx, Qt.ItemDataRole.BackgroundRole)
kontrol("DUR satırı vurgulu (kırmızı zemin)", isinstance(bg, QColor) and bg.red() > 200 and bg.green() < 100)
kontrol("normal satır vurgusuz", m.data(m.index(0, 0), Qt.ItemDataRole.BackgroundRole) is None)
kontrol("durum: arka planda çalışıyor", p.izleyici.durum.ad == "arka", p.izleyici.durum.ad)
w.etkinlik.tur.setCurrentIndex([k for k, _ in __import__("deskhand.gui.metinler", fromlist=["E_TUR"]).E_TUR].index("dur"))
kontrol("süzgeç: yalnız DUR", w.etkinlik.suzgec.rowCount() == 1)
w.etkinlik.tur.setCurrentIndex(0)
w.etkinlik.filtre.setText("belge")
kontrol("süzgeç: metin (büyük/küçük harf duyarsız)", w.etkinlik.suzgec.rowCount() == 1)
w.etkinlik.filtre.setText("")
m.ekle([G.ayristir(f"09:01:00 tikla {i} | [P] | click left") for i in range(600)])
kontrol("Etkinlik en çok 500 satır tutar", m.rowCount() == 500 and m.satirlar[-1]["eylem"].startswith("tikla 599"))

# ---- DUR / Devam
w.serit.b_dur.click()
kontrol("DUR düğmesi → dur dosyası (kaynak kullanici)", guvenlik.dur_kaynagi() == "kullanici")
kontrol("DUR açıkken şeritte Devam görünür", bekle(lambda: w.serit.b_devam.isVisible() and not w.serit.b_dur.isVisible()))
kontrol("durum: dur", p.izleyici.durum.ad == "dur")
try:
    guvenlik.dur_kapat("cli")
    cli_kaldirdi = True
except hata.Dur as e:
    cli_kaldirdi = e.kod != 13
kontrol("kullanıcının DUR'unu CLI kaldıramaz (13)", not cli_kaldirdi and guvenlik.dur_acik())
w.serit.b_devam.click()
kontrol("Devam düğmesi → DUR kalktı", not guvenlik.dur_acik())
kontrol("DUR/Devam günlüğe yazıldı", any("DUR anahtarı açıldı (panel)" in d["ham"] for d in m.satirlar) or
        "DUR anahtarı açıldı (panel)" in open(gunluk_yolu()).read())
guvenlik.dur_ac("cli")
p.izleyici.yenile()
kontrol("ajanın DUR'u: şerit 'ajan/komut satırı durdurdu'", "ajan" in w.serit.l_durum.text(), w.serit.l_durum.text())
p.devam()
kontrol("panel ajanın DUR'unu da kaldırabilir", not guvenlik.dur_acik())
kis.basildi.emit()
kontrol("genel kısayol sinyali → DUR (kullanici)", bekle(lambda: guvenlik.dur_kaynagi() == "kullanici"))
# tepsi menüsündeki Devam (plasmashell çizer: ajan tıklayabilir) DUR'u doğrudan KALDIRMAZ, panelde sorar
from deskhand.gui.tepsi import Tepsi as _Tepsi  # noqa: E402

tt = _Tepsi()
tt.devam_istendi.connect(p.devam_sor)
w.hide()
tt.a_devam.trigger()
kutu = w.devam_kutusu
kontrol("tepsi Devam → DUR hâlâ açık, panel penceresinde onay kutusu", guvenlik.dur_acik() and kutu is not None and
        bekle(lambda: kutu.isVisible()) and w.isVisible() and kutu.window() is kutu and kutu.parent() is w)
kontrol("onay kutusu: varsayılan/Esc = DUR açık kalsın, Devam odak almaz", kutu.defaultButton() is kutu.b_hayir and
        kutu.escapeButton() is kutu.b_hayir and kutu.b_evet.focusPolicy() == Qt.FocusPolicy.NoFocus)
QTest.keyClick(kutu, Qt.Key.Key_Return)
from PyQt6 import sip  # noqa: E402

kontrol("onay kutusu: Enter → DUR açık kaldı", guvenlik.dur_acik() and
        bekle(lambda: sip.isdeleted(kutu) or not kutu.isVisible()))
tt.a_devam.trigger()
kutu = w.devam_kutusu
bekle(lambda: kutu.isVisible())
QTest.mouseClick(kutu.b_evet, Qt.MouseButton.LeftButton)
kontrol("onay kutusu: panelde 'Devam et' tıklandı → DUR kalktı", bekle(lambda: not guvenlik.dur_acik()))
p.devam()

# ---- Onay diyaloğu: düğme mantığı (doğrudan)
from deskhand.gui.onay_diyalog import OnayDiyalog  # noqa: E402

yanitlar = []
istek = {"id": "a" * 32, "eylem": "tıkla 'Öde'", "hedef": "<b>Mağaza</b>", "ayrinti": "x", "masaustu": "arka",
         "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()}
dlg = OnayDiyalog(istek, istek_var=lambda: True, yanitla=lambda k, karar: yanitlar.append((k, karar)) or True, kurma_ms=300)
dlg.show()
app.processEvents()
kontrol("diyalog başlığı sabit", dlg.windowTitle() == onay.ONAY_BASLIK == "Deskhand — Onay")
kontrol("varsayılan düğme Reddet", dlg.b_red.isDefault() and not dlg.b_izin.isDefault() and not dlg.b_izin.autoDefault())
kontrol("İzin klavye odağı almaz", dlg.b_izin.focusPolicy() == Qt.FocusPolicy.NoFocus)
kontrol("ajan metni HTML yorumlanmaz", dlg.l_hedef.textFormat() == Qt.TextFormat.PlainText)
kontrol("üstte kalır, modal değil", bool(dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) and not dlg.isModal())
from PyQt6.QtGui import QMouseEvent  # noqa: E402


def fare_gezdir(dlg_, noktalar):
    for x_, y_ in noktalar:
        yerel = QPointF(x_, y_)
        QApplication.sendEvent(dlg_, QMouseEvent(QEvent.Type.MouseMove, yerel, dlg_.mapToGlobal(yerel),
                                                 Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                                 Qt.KeyboardModifier.NoModifier))
        app.processEvents()


from deskhand.gui import onay_diyalog as OD  # noqa: E402
from PyQt6.QtCore import QEvent  # noqa: E402

kontrol("kurma süresi varsayılanı ≥ 1,5 sn", OD.KURMA_MS >= 1500)
QTest.mouseClick(dlg.b_izin, Qt.MouseButton.LeftButton)
kontrol("kurulma süresinde İzin tıklaması işlemez", yanitlar == [] and not dlg.bitti)
fare_gezdir(dlg, [(10, 10), (200, 120), (20, 30)])  # kurma süresi İÇİNDEKİ hareket sayılmaz
time.sleep(0.4)
app.processEvents()
kontrol("kurma süresi doldu ama fare hareketsiz → İzin hâlâ KAPALI (durağan imleç altında açılan diyalog)",
        not dlg.b_izin.isEnabled())
fare_gezdir(dlg, [(100, 100), (100, 100), (104, 103)])  # aynı nokta (yapay) + küçük titreme
kontrol("yapay/küçük (< 12 px) hareket → İzin hâlâ KAPALI", not dlg.b_izin.isEnabled())
QTest.mouseClick(dlg.b_izin, Qt.MouseButton.LeftButton)
kontrol("hareketsiz tık izne dönüşmez", yanitlar == [] and not dlg.bitti)
fare_gezdir(dlg, [(130, 120)])
kontrol("kurulma sonrası gerçek fare hareketi → İzin etkin", dlg.b_izin.isEnabled())
QTest.keyClick(dlg, Qt.Key.Key_Return)
kontrol("Enter → RED (izin değil)", yanitlar == [("a" * 32, "red")] and dlg.bitti, str(yanitlar))

yanitlar.clear()
dlg = OnayDiyalog(dict(istek, id="b" * 32), istek_var=lambda: True, yanitla=lambda k, karar: yanitlar.append((k, karar)) or True, kurma_ms=0)
dlg.show()
app.processEvents()
QTest.keyClick(dlg, Qt.Key.Key_Space)
kontrol("boşluk tuşu izin vermez (odak Reddet'te → red)", yanitlar in ([], [("b" * 32, "red")]) and
        ("b" * 32, "izin") not in yanitlar, str(yanitlar))
dlg2 = OnayDiyalog(dict(istek, id="c" * 32), istek_var=lambda: True, yanitla=lambda k, karar: yanitlar.append((k, karar)) or True, kurma_ms=0)
dlg2.show()
app.processEvents()
QTest.mouseClick(dlg2.b_izin, Qt.MouseButton.LeftButton)
kontrol("fareyle 'Bir kez izin ver' → izin", ("c" * 32, "izin") in yanitlar, str(yanitlar))
saat_d = [time.time()]
dlg3 = OnayDiyalog(dict(istek, id="d" * 32, son_zaman=saat_d[0] + 2), saat=lambda: saat_d[0],
                   istek_var=lambda: True, yanitla=lambda k, karar: yanitlar.append((k, karar)) or True, kurma_ms=0)
dlg3.show()
kontrol("geri sayım metni", "0:02" in dlg3.l_kalan.text(), dlg3.l_kalan.text())
saat_d[0] += 3
bekle(lambda: dlg3.bitti, 1)
kontrol("süre dolunca otomatik RED", ("d" * 32, "red") in yanitlar)
dlg4 = OnayDiyalog(dict(istek, id="e" * 32), istek_var=lambda: True, yanitla=lambda k, karar: yanitlar.append((k, karar)) or True, kurma_ms=0)
dlg4.show()
app.processEvents()
dlg4.close()
kontrol("pencereyi kapatmak = RED", ("e" * 32, "red") in yanitlar)

# ---- Uçtan uca: iste() (iş parçacığı) ↔ panel diyaloğu
sonuc = {}


def isteyen(karar_key):
    sonuc[karar_key] = onay.iste_sonuc("tıkla 'Satın al'", "Mağaza — Firefox", "test", masaustu="ekran", sure=10)


th = threading.Thread(target=isteyen, args=("izin",), daemon=True)
th.start()
kontrol("panel isteği gördü → diyalog açıldı", bekle(lambda: len(p.diyaloglar) == 1, 4))
kontrol("Onaylar sekmesinde bekleyen 1", bekle(lambda: w.onaylar.t_bekleyen.rowCount() == 1, 2))
kontrol("tepsi/şerit rozeti: 1 onay bekliyor", bekle(lambda: p.izleyici.durum.bekleyen == 1, 2))
dlg = next(iter(p.diyaloglar.values()))
QTest.mouseClick(dlg.b_izin, Qt.MouseButton.LeftButton)
th.join(5)
kontrol("uçtan uca: insan tıkladı → iste() True", sonuc.get("izin") and sonuc["izin"].izin, str(sonuc.get("izin")))
kontrol("diyalog kapandı, bekleyen kalmadı", bekle(lambda: not p.diyaloglar and not onay.bekleyenler(), 3))
kontrol("onay geçmişi panelde", bekle(lambda: w.onaylar.t_gecmis.rowCount() >= 1, 3) and
        w.onaylar.t_gecmis.item(0, 4).text() == "izin verildi")
th = threading.Thread(target=isteyen, args=("red",), daemon=True)
th.start()
bekle(lambda: len(p.diyaloglar) == 1, 4)
dlg = next(iter(p.diyaloglar.values()))
QTest.mouseClick(dlg.b_red, Qt.MouseButton.LeftButton)
th.join(5)
kontrol("uçtan uca: Reddet → iste() False", sonuc.get("red") and not sonuc["red"].izin and sonuc["red"].neden == "red")
th = threading.Thread(target=lambda: sonuc.__setitem__("kisa", onay.iste_sonuc("x", "y", sure=1)), daemon=True)
th.start()
bekle(lambda: len(p.diyaloglar) == 1, 3)
th.join(4)
kontrol("uçtan uca: isteyen süre doldu → diyalog kendiliğinden kapanır",
        sonuc["kisa"].neden == "sure" and bekle(lambda: not p.diyaloglar, 5), str(sonuc.get("kisa")))

# ---- Arka plan ekranı: önizleme yalnız görünürken; Başlat; Devral girdisi
a = w.arka
kontrol("sanal kapalı: Başlat görünür, Devral kapalı", not a.b_baslat.isHidden() and not a.b_devral.isEnabled())
w.sekmeler.setCurrentWidget(w.etkinlik)
app.processEvents()
a.b_baslat.click()
kontrol("Başlat → masaustu_baslat çağrıldı", bekle(lambda: SahteMasaustu.baslatildi == 1 and a._isci is None, 3))
kontrol("açık: Durdur görünür, Devral etkin", bekle(lambda: a.sanal is not None) and not a.b_durdur.isHidden() and
        a.b_devral.isEnabled())
app.processEvents()
k0 = arka.kareler
time.sleep(0.6)
app.processEvents()
kontrol("sekme gizliyken önizleme yoklaması YOK", arka.kareler == k0 and not a.zaman.isActive(), f"{arka.kareler}")
w.sekmeler.setCurrentWidget(a)
kontrol("sekme görünürken ~2 fps önizleme", bekle(lambda: arka.kareler >= k0 + 2, 2.5) and a.zaman.isActive())
kontrol("önizleme görüntüsü oranı korunmuş", a.onizleme.kaynak == QSize(1920, 1080) and a.onizleme.resim is not None)
w.hide()
app.processEvents()
k1 = arka.kareler
time.sleep(0.6)
app.processEvents()
kontrol("pencere gizliyken yoklama YOK", arka.kareler == k1 and not a.zaman.isActive())
w.show()
w.sekmeler.setCurrentWidget(a)
bekle(lambda: a.zaman.isActive(), 1)

on = a.onizleme
on.resize(960, 540)
app.processEvents()
QTest.mouseClick(on, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(480, 270))
kontrol("Devral kapalıyken girdi gönderilmez", arka.girdiler == [])
a.b_devral.setChecked(True)
kontrol("Devral → devral dosyası", os.path.exists(D.devral_yolu()) and a.b_devral.text() == "Bırak")
kontrol("Devral dosyası sahibi bu panel (pid + başlangıç) → devral_var", D.devral_var() and
        open(D.devral_yolu()).read().split()[:2] == ["panel", str(os.getpid())])
r = on.hedef_rect()
QTest.mouseClick(on, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 QPoint(int(r.x() + r.width() * 0.25), int(r.y() + r.height() * 0.5)))
g = arka.girdiler[0] if arka.girdiler else SahteGirdi()
kontrol("tıklama → mouseto (ölçekli) + buttondown/up left",
        len(g.satirlar) >= 3 and g.satirlar[0].startswith("mouseto 0.25") and " 0.5" in g.satirlar[0] and
        "buttondown left" in g.satirlar and g.satirlar[-1] == "buttonup left", str(g.satirlar))
kontrol("Devral girdisi denetle=None (insan)", g.denetle is None)
g.satirlar.clear()
from PyQt6.QtCore import QEvent  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402

for tus, metin in ((Qt.Key.Key_A, "a"), (Qt.Key.Key_unknown, "ş")):  # QTest.keyClicks Latin-1 dışını kabul etmiyor
    QApplication.sendEvent(on, QKeyEvent(QEvent.Type.KeyPress, tus, Qt.KeyboardModifier.NoModifier, metin))
kontrol("Türkçe karakter: key a, key ş", g.satirlar == ["key a", "key ş"], str(g.satirlar))
g.satirlar.clear()
QTest.keyClick(on, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
QTest.keyClick(on, Qt.Key.Key_Return)
QTest.keyClick(on, Qt.Key.Key_Tab)
kontrol("ctrl+s, Enter, Tab (Tab odak değiştirmez)", g.satirlar == ["key ctrl+s", "key enter", "key tab"],
        str(g.satirlar))
g.satirlar.clear()
QTest.keyClick(on, Qt.Key.Key_Space)
QTest.keyClick(on, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier)
kontrol("boşluk ve + doğru adla", g.satirlar[:1] == ["key space"] and (len(g.satirlar) == 1 or
                                                                      g.satirlar[1] in ("key x:plus",)), str(g.satirlar))
g.satirlar.clear()
guvenlik.dur_ac("kullanici")
QTest.keyClick(on, Qt.Key.Key_A)
kontrol("DUR açıkken Devral girdisi gönderilmez + uyarı", g.satirlar == [] and "DUR" in a.l_not.text(), a.l_not.text())
p.devam()
nokta_ = QPoint(int(r.x() + r.width() * 0.5), int(r.y() + r.height() * 0.5))
QTest.mousePress(on, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, nokta_)
guvenlik.dur_ac("kullanici")
QTest.mouseRelease(on, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, nokta_)
kontrol("DUR basılıyken açılırsa: bırakma (buttonup) yine gider, hareket gitmez, uyarı",
        g.satirlar[-2:] == ["buttondown left", "buttonup left"] and sum(x.startswith("mouseto") for x in g.satirlar) == 1
        and "DUR" in a.l_not.text(), str(g.satirlar))
p.devam()
a.b_devral.setChecked(False)
kontrol("Bırak → devral dosyası silindi, girdi kapandı", not os.path.exists(D.devral_yolu()) and g.kapandi)
a.b_durdur.click()
kontrol("Durdur → kapalı, önizleme durdu", bekle(lambda: a.sanal is None and a._isci is None, 3) and
        not a.zaman.isActive())

# Isci: bitince silinir; isciler_bekle çalışanları bekler (kapanışta "QThread destroyed while running" yok)
from deskhand.gui.pencere import Isci, isciler_bekle  # noqa: E402

ii = Isci(lambda: time.sleep(0.3) or 7)
ii.start()
kontrol("isciler_bekle: çalışan iş bitene dek bekler", ii in Isci.calisanlar and isciler_bekle(3000) and
        not ii.isRunning())
kontrol("Isci bitince listeden çıkar", bekle(lambda: ii not in Isci.calisanlar, 2))

# izleyici: dünün günlük dosyası izlemeden çıkarılır (QFileSystemWatcher'da yol birikmez)
eski_gunluk = os.path.join(yollar.gunluk_dizin(), "2000-01-01.log")
open(eski_gunluk, "w").close()
p.izleyici.fsw.addPath(eski_gunluk)
p.izleyici.yenile()
kontrol("izleyici: eski günlük dosyası izlemeden çıkarıldı", eski_gunluk not in p.izleyici.fsw.files(),
        str(p.izleyici.fsw.files()))

# tus_satirlari (saf)
from deskhand.gui.onizleme import tus_satirlari  # noqa: E402

M = Qt.KeyboardModifier
kontrol("tuş: Shift tek başına → yok", tus_satirlari(Qt.Key.Key_Shift, "", M.ShiftModifier) == [])
kontrol("tuş: büyük Ç → key Ç", tus_satirlari(Qt.Key.Key_Ccedilla, "Ç", M.ShiftModifier) == ["key Ç"])
kontrol("tuş: ctrl+shift+t", tus_satirlari(Qt.Key.Key_T, "\x14", M.ControlModifier | M.ShiftModifier) ==
        ["key ctrl+shift+t"])
kontrol("tuş: alt+F4", tus_satirlari(Qt.Key.Key_F4, "", M.AltModifier) == ["key alt+f4"])
kontrol("tuş: shift+Tab (Backtab)", tus_satirlari(Qt.Key.Key_Backtab, "", M.ShiftModifier) == ["key shift+tab"])

# ---- Simgeler
os.makedirs(yollar.simge_dizin(), exist_ok=True)
Image.new("RGB", (30, 20), (1, 2, 3)).save(os.path.join(yollar.simge_dizin(), "dugme.png"))
s = w.simgeler
s.yenile()
kontrol("simge listelendi", s.liste.count() == 1 and s.liste.item(0).text() == "dugme")
s.liste.setCurrentRow(0)
sor_cevap[0] = False
kontrol("silme onayı Hayır → silinmez", not s.sil() and os.path.exists(os.path.join(yollar.simge_dizin(), "dugme.png")))
sor_cevap[0] = True
s.liste.setCurrentRow(0)
kontrol("silme onayı Evet → silinir", s.sil() and s.liste.count() == 0 and
        not os.path.exists(os.path.join(yollar.simge_dizin(), "dugme.png")))

# ---- Ayarlar
y = w.ayarlar
y.yasak.setPlainText("# yorum\nOrnek Oyun\n(bozuk")
kontrol("geçersiz desen kaydedilmez", not y.yasak_kaydet() and "3. satır" in y.l_yasak.text())
y.yasak.setPlainText("# yorum\nOrnek Oyun\n^deskhand$")
kontrol("geçerli yasak listesi geçici CONFIG'e kaydedildi", y.yasak_kaydet() and
        guvenlik._kullanici_yasaklari() == ["Ornek Oyun", "^deskhand$"] and
        guvenlik.yasak_desenler()[:len(guvenlik.YERLESIK_YASAK)] == list(guvenlik.YERLESIK_YASAK))
kontrol("yasak dosyası geçici dizinde", yollar.yasak_dosya().startswith(_yalitim.GECICI))
from PyQt6.QtGui import QKeySequence  # noqa: E402

y.k_tus.setKeySequence(QKeySequence("Meta+Shift+Esc"))
c = y.cakisma_goster()
kontrol("kısayol çakışması gösterilir", c and "Çakışma" in y.l_kisayol.text(), y.l_kisayol.text())
y.k_tus.setKeySequence(QKeySequence("Meta+Alt+Esc"))
y.k_acik.setChecked(True)
from deskhand.gui import ayar as A  # noqa: E402

kontrol("kısayol aç → panel.json (geçici) + kayıt çağrısı (sahte)", A.panel_oku()["kisayol_acik"] and
        kis.cagri and kis.cagri[-1][0] == "ac" and "Meta+Alt+Esc" in kis.cagri[-1][1], str(kis.cagri))
y.k_acik.setChecked(False)
kontrol("kısayol kapat → kayıt silme çağrısı", kis.cagri[-1] == ("kapat", True) and not A.panel_oku()["kisayol_acik"])
kontrol("panel.json geçici dizinde", A.panel_yolu().startswith(_yalitim.GECICI))
if y.karar.var:
    i = y.c_mesgul.findData("bekle")
    y.c_mesgul.setCurrentIndex(i)
    y.s_sure.setValue(33)
    y.karar_kaydet()
    from deskhand import ayarlar as AY  # noqa: E402

    kontrol("meşgulken ayarı deskhand.ayarlar'a yazıldı (geçici)", AY.al("karar", "mesgulken") == "bekle" and
            AY.al("karar", "sor_sure") == 33 and AY.dosya().startswith(_yalitim.GECICI), str(AY.oku()))
else:
    kontrol("deskhand.ayarlar yok → bilgilendirme", True)


class SahteAyarlar:
    d = {}

    @classmethod
    def al(cls, b, k):
        return cls.d.get((b, k))

    @classmethod
    def ayarla(cls, b, k, v):
        cls.d[(b, k)] = v


ka = A.KararAyarlari(SahteAyarlar)
ka.yaz({"mesgulken": "sor", "sor_sure": 10, "cevapsiz": "sonra", "yabanci": 1})
kontrol("KararAyarlari: al/ayarla köprüsü (yabancı anahtar yazılmaz)", ka.var and SahteAyarlar.d == {
    ("karar", "mesgulken"): "sor", ("karar", "sor_sure"): 10, ("karar", "cevapsiz"): "sonra"}, str(SahteAyarlar.d))
kontrol("KararAyarlari: modül yok → var=False", not A.KararAyarlari(object()).var)

# kglobalshortcutsrc çakışma okuma (salt okuma, örnek dosya)
from deskhand.gui import kisayol as K  # noqa: E402

ornek = os.path.join(_yalitim.GECICI, "kglobalshortcutsrc")
with open(ornek, "w") as f:
    f.write("[kwin]\n_k_friendly_name=KWin\ndisableInputCapture=Meta+Shift+Esc,Meta+Shift+Esc,Girişi bırak\n"
            "Kill Window=Meta+Ctrl+Esc,Meta+Ctrl+Esc,Pencereyi Öldür\nview_zoom_in=Meta++\tMeta+=,Meta++,Yakınlaştır\n"
            "[kwin][$InverseAction]\nx=Meta+Alt+Esc\n[deskhand]\ndur=Meta+Alt+Esc,none,DUR\n")
kontrol("çakışma: Meta+Shift+Esc → kwin", K.cakismalar("Meta+Shift+Esc", ornek) == [("kwin", "disableInputCapture",
                                                                                    "Girişi bırak")])
kontrol("çakışma: Shift+Meta+Escape aynı tuş", len(K.cakismalar("Shift+Meta+Escape", ornek)) == 1)
kontrol("çakışma: Meta+Alt+Esc boş (kendi kaydı ve ters eylem sayılmaz)", K.cakismalar("Meta+Alt+Esc", ornek) == [])
kontrol("çakışma: sekmeyle ayrılmış ikinci tuş", len(K.cakismalar("Meta+=", ornek)) == 1)
kontrol("tuş kodu Meta+Alt+Esc", K.tus_kodu("Meta+Alt+Esc") == 0x10000000 | 0x08000000 | 0x01000000)
kontrol("dosya yok → boş", K.cakismalar("Meta+Alt+Esc", "/yok/kglobalshortcutsrc") == [])

# ---- Sağlık
w.sekmeler.setCurrentWidget(w.saglik)
kontrol("sağlık denetimi görünür olunca çalışır", bekle(lambda: w.saglik.tablo.rowCount() == 2, 3))
kontrol("sağlık özeti 1/2", "1/2" in w.saglik.l_ozet.text(), w.saglik.l_ozet.text())
from deskhand.gui import saglik as S  # noqa: E402

sd = S.denetle(which=lambda a: a in ("kdotool", "Xvfb"), find_spec=lambda m: object() if m == "numpy" else None,
               diller_f=lambda: {"tur"})
ok_ = {d["ad"]: d["ok"] for d in sd}
kontrol("sağlık: araç/dil/modül denetimi", ok_["kdotool"] and ok_["Xvfb"] and not ok_["dotool"] and
        ok_["tesseract: tur"] and not ok_["tesseract: eng"] and ok_["numpy"] and not ok_["mcp"] and len(sd) == 16,
        str(ok_))

# ---- Dil (i18n): seçici arayuz.json'a yazar; sahte en kataloğu; dil değişince metinler yerinde tazelenir
import json  # noqa: E402

from PyQt6.QtCore import QTranslator  # noqa: E402
from PyQt6.QtWidgets import QGroupBox, QLineEdit  # noqa: E402

from deskhand import i18n  # noqa: E402

SAHTE_EN = {"Etkinlik": "Activity", "Arka plan ekranı": "Background screen", "Ayarlar": "Settings",
            "Onaylar": "Approvals", "Onaylar ({n})": "Approvals ({n})", "Zaman": "Time", "Boşta": "Idle",
            "DUR": "STOP", "Devam et": "Resume", "DUR — tüm girdileri durdur": "STOP — halt all input",
            "Dil": "Language", "Reddet": "Deny", "Bir kez izin ver": "Allow once", "izin verildi": "allowed",
            "Otomatik kaydır": "Auto-scroll", "DUR anahtarı açıldı (panel)": "STOP switch on (panel)",
            "Yeniden denetle": "Check again", "var": "found", "Başlat": "Start", "Hepsi": "All"}
y = w.ayarlar


def sekme_adlari():
    return [w.sekmeler.tabText(i) for i in range(w.sekmeler.count())]


def dil_etkinlestir(kod):
    i = y.c_dil.findData(kod)
    y.c_dil.setCurrentIndex(i)
    y.c_dil.activated.emit(i)  # kullanıcının seçimi (activated) ile aynı yol


kontrol("dil seçici: Otomatik / Türkçe / English", [y.c_dil.itemData(i) for i in range(y.c_dil.count())] ==
        ["otomatik", "tr", "en"] and y.c_dil.itemText(2).startswith("English") and y.c_dil.isEnabled())
kontrol("dil seçici başlangıçta Otomatik (ayar dosyası yok)", y.c_dil.currentData() == "otomatik")
eski_env = os.environ.pop("DESKHAND_DIL", None)
eski_katalog = i18n.katalog_oku
i18n.katalog_oku = lambda dil, directory=None: dict(SAHTE_EN) if dil == "en" else {}
eski_tepsi, p.tepsi = p.tepsi, Tepsi()
yayilan = []
y.dil_degisti.connect(yayilan.append)
dlg_dil = OnayDiyalog(dict(istek, id="f" * 32), istek_var=lambda: True, yanitla=lambda k, karar: True, kurma_ms=0)
p.diyaloglar["f" * 32] = dlg_dil
try:
    dil_etkinlestir("en")
    ayar_yolu = os.path.join(yollar.config_dir(), "arayuz.json")
    kontrol("dil seçimi geçici CONFIG/arayuz.json'a yazıldı", ayar_yolu.startswith(_yalitim.GECICI) and
            json.load(open(ayar_yolu)) == {"dil": "en"} and i18n.ayar_oku() == "en")
    kontrol("dil_degisti yayıldı, etkin dil en", yayilan == ["en"] and i18n.dil() == "en", str(yayilan))
    ad = sekme_adlari()
    kontrol("dil değişince sekme adları tazelendi", ad[0] == "Activity" and ad[1] == "Background screen" and
            ad[3] == "Settings" and ad[2] == "Approvals", str(ad))
    kontrol("İngilizce: Etkinlik sütunu / süzgeç / onay kutusu", w.etkinlik.model.headerData(
        0, Qt.Orientation.Horizontal) == "Time" and w.etkinlik.tur.itemText(0) == "All" and
        w.etkinlik.kaydir.text() == "Auto-scroll")
    kontrol("İngilizce: şerit (DUR düğmesi, durum)", w.serit.b_dur.text() == "STOP" and
            w.serit.b_devam.text() == "Resume" and w.serit.l_durum.text() == "Idle", w.serit.l_durum.text())
    kontrol("İngilizce: Ayarlar grup başlığı, Arka plan düğmesi, Sağlık", any(
        g.title() == "Language" for g in y.findChildren(QGroupBox)) and w.arka.b_baslat.text() == "Start" and
        w.saglik.b_yenile.text() == "Check again" and w.saglik.tablo.item(0, 1).text() == "found")
    kararlar = [w.onaylar.t_gecmis.item(i, 4).text() for i in range(w.onaylar.t_gecmis.rowCount())]
    kontrol("İngilizce: onay geçmişi kararı yeniden yazıldı", "allowed" in kararlar and
            "izin verildi" not in kararlar, str(kararlar))
    m = w.etkinlik.model
    sira = next((i for i, d in enumerate(m.satirlar) if d["eylem"] == "DUR anahtarı açıldı (panel)"), None)
    kontrol("sabit günlük satırı görüntüde çevrilir, ham satır Türkçe kalır", sira is not None and
            m.data(m.index(sira, 3)) == "STOP switch on (panel)" and "DUR anahtarı" in m.satirlar[sira]["ham"])
    w.durum_guncelle(D.Durum(bekleyen=2))
    kontrol("İngilizce: Onaylar sekmesi sayılı ad", w.sekmeler.tabText(2) == "Approvals (2)", w.sekmeler.tabText(2))
    w.durum_guncelle(p.izleyici.durum)
    kontrol("tepsi menüsü + ipucu tazelendi", p.tepsi.a_dur.text() == "STOP — halt all input" and
            "Idle" in p.tepsi.ikon.toolTip(), p.tepsi.a_dur.text())
    kontrol("açık onay diyaloğu tazelendi", dlg_dil.b_red.text() == "Deny" and dlg_dil.b_izin.text() == "Allow once")
    kontrol("çevrilmeyen metin Türkçe kalır (eksik katalog bozmaz)", w.onaylar.b_ac.text() == "Diyaloğu aç")
    kontrol("pencere başlığı dil değişse de sabit", w.windowTitle() == "Deskhand")
    dil_etkinlestir("tr")
    kontrol("Türkçe'ye dönüş: sekmeler, tepsi, şerit", sekme_adlari()[0] == "Etkinlik" and
            p.tepsi.a_dur.text() == "DUR — tüm girdileri durdur" and w.serit.b_dur.text() == "DUR" and
            i18n.ayar_oku() == "tr" and yayilan == ["en", "tr"])
    kontrol("aynı dili yeniden seçmek bir şey yapmaz", not y.dil_sec("tr") and yayilan == ["en", "tr"])
    os.environ["DESKHAND_DIL"] = "tr"
    kontrol("DESKHAND_DIL zorluyorsa: seçim kaydedilir + uyarı", y.dil_sec("en") and i18n.ayar_oku() == "en" and
            i18n.dil() == "tr" and not y.l_dil.isHidden() and "DESKHAND_DIL" in y.l_dil.text(), y.l_dil.text())
    del os.environ["DESKHAND_DIL"]
    y.dil_sec("otomatik")
    kontrol("Otomatik seçimi yazıldı, uyarı kalktı", json.load(open(ayar_yolu)) == {"dil": "otomatik"} and
            y.c_dil.currentData() == "otomatik" and y.l_dil.isHidden())
finally:
    i18n.katalog_oku = eski_katalog
    if eski_env is not None:
        os.environ["DESKHAND_DIL"] = eski_env
    i18n.sifirla()
    w.tazele()
    p.tepsi = eski_tepsi
    p.diyaloglar.pop("f" * 32, None)
    dlg_dil.geri_cekildi()


class SahteQtCevirisi(QTranslator):
    """Qt'nin Türkçe çevirisini taklit eder (KDE sistem dili Türkçe iken yüklenen qtbase_tr)."""

    def translate(self, baglam, metin, ayrim=None, n=-1):
        return {"Alt": "Seçenek", "Esc": "Vazgeç"}.get(metin, "") if baglam == "QShortcut" else ""


cevirmen = SahteQtCevirisi()
app.installTranslator(cevirmen)
yerel = QKeySequence("Meta+Alt+Esc").toString(QKeySequence.SequenceFormat.NativeText)
y.k_tus.setKeySequence(QKeySequence("Meta+F12"))
y.k_tus.setKeySequence(QKeySequence("Meta+Alt+Esc"))
kutu = y.k_tus.findChild(QLineEdit)
kontrol("kısayol kutusu PortableText gösterir (Qt çevirisi 'Seçenek+Vazgeç' değil)", "Seçenek" in yerel and
        kutu is not None and kutu.text() == "Meta+Alt+Esc" and y.tus() == "Meta+Alt+Esc",
        f"{yerel} / {kutu.text() if kutu else None}")
app.removeTranslator(cevirmen)

# ---- kapanış: bekleyen istekler reddedilir, panel.pid silinir
k = "9" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "ekran",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()})
p.izleyici.yenile()
kontrol("kapanış öncesi diyalog açık", k in p.diyaloglar)
p.kapanis()
y_ = onay._json_oku(onay.yanit_yolu(k))
kontrol("kapanışta bekleyen istek RED yanıtlandı", y_ and y_["karar"] == "red")
kontrol("kapanışta panel.pid silindi", not os.path.exists(onay.panel_pid_yolu()) and not onay.panel_canli())
kontrol("kapanışta tek örnek kilidi bırakıldı", not baska_panel_var())
kontrol("kapanışta kısayol kaydı silinmez (yalnız dinleme durur)", kis.cagri[-1] == ("kapat", False))

# ---- güvenlik: GUI paketinde ham araç çağrısı yok, gerçek yollara yazılmadı
gercek = [os.path.expanduser(y) for y in ("~/.config/deskhand", "~/.local/state/deskhand")]
kontrol("yollar geçici dizinde", all(not yollar.config_dir().startswith(g) for g in gercek) and
        yollar.runtime_dir().startswith(_yalitim.GECICI))

# ---- Çık: açık onay diyaloğu ve gizlenen ana pencere çıkışı ENGELLEMEZ (Qt 6 quit() pencereleri kapatır)
import faulthandler  # noqa: E402

onay.panel_kaydet()
k = "8" * 32
onay._yaz_atomik(onay.istek_yolu(k), {"id": k, "eylem": "e", "hedef": "h", "ayrinti": "", "masaustu": "ekran",
                                    "zaman": time.time(), "son_zaman": time.time() + 60, "pid": os.getpid()})
p.izleyici._yokla.start()
p.izleyici.yenile()
w.show()
kontrol("çıkış öncesi diyalog açık", k in p.diyaloglar)
from PyQt6.QtCore import QTimer  # noqa: E402

QTimer.singleShot(200, p.cik)
faulthandler.dump_traceback_later(10, exit=True)  # takılırsa test asılı kalmasın
t0 = time.monotonic()
kod = app.exec()
faulthandler.cancel_dump_traceback_later()
kontrol("Çık → olay döngüsü hemen biter", kod == 0 and time.monotonic() - t0 < 3, f"{time.monotonic() - t0:.1f}")
y_ = onay._json_oku(onay.yanit_yolu(k))
kontrol("Çık → açık onay isteği RED", y_ and y_["karar"] == "red")
kontrol("Çık → panel.pid silindi", not os.path.exists(onay.panel_pid_yolu()))

print(f"\n{gecen}/{toplam} arayüz testi geçti")
sys.exit(0 if gecen == toplam else 1)
