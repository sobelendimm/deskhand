"""README ekran görüntüleri: panelin offscreen render'ı, SAHTE örnek günlük/yasak listesi/onay isteğiyle.
Gerçek ~/.config, günlük, ekran KULLANILMAZ (tests/_yalitim tüm DESKHAND_*_DIR'leri geçici klasöre yönlendirir).

    python3 tools/ekran-goruntuleri.py                     # İngilizce → docs/img/{activity,background,approval,tray}.png
    python3 tools/ekran-goruntuleri.py --dil tr --cikti /tmp/x
    python3 tools/ekran-goruntuleri.py --hepsi --koyu      # + approvals, settings, health, stop; koyu tema (-dark)

Dosya adlarına dil eklenmez (README.md ve README.tr.md aynı docs/img/*.png'yi gösterir); başka dilde üretmek için
--cikti ile ayrı klasör verin. Dil DESKHAND_DIL ile zorlanır; sahte günlük/ekran/onay metinleri de o dilde
(günlük satırlarının komut/etiket kısmı Deskhand'in yazdığı gibi Türkçe kalır, yalnız serbest metin değişir)."""
import argparse
import os
import sys
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(description="Deskhand paneli README ekran görüntüleri (offscreen, sahte veri)")
ap.add_argument("--dil", choices=("en", "tr"), default="en", help="arayüz dili (varsayılan en: README görüntüleri)")
ap.add_argument("--cikti", default=os.path.join(KOK, "docs", "img"), help="çıktı klasörü (varsayılan docs/img)")
ap.add_argument("--koyu", action="store_true", help="koyu palet (dosya adına -dark eklenir)")
ap.add_argument("--hepsi", action="store_true", help="README'de olmayan sekmeleri de kaydet")
a = ap.parse_args()

sys.path.insert(0, os.path.join(KOK, "tests"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["DESKHAND_DIL"] = a.dil
import _yalitim  # noqa: E402,F401
os.environ["DESKHAND_DIL"] = a.dil  # _yalitim test için "tr" koymuş olabilir: bu betikte seçilen dil geçerli
from deskhand import guvenlik, i18n, onay, yollar  # noqa: E402

i18n.sifirla()  # dil bir sonraki _()'de DESKHAND_DIL'den okunur
if i18n.dil() != a.dil:
    sys.exit(f"dil {a.dil} etkinleşmedi (etkin: {i18n.dil()})")
oran = i18n.kapsama(a.dil)
if oran is not None and oran < 1:
    print(f"UYARI: {a.dil} kataloğu %{oran * 100:.0f} çevrilmiş; eksik metinler Türkçe görünür", file=sys.stderr)
OUT = a.cikti
os.makedirs(OUT, exist_ok=True)
koyu = a.koyu

# ---- sahte veriler (dil başına). Kişisel veri YOK: örnek alan adı, örnek mağaza, örnek kitap.
ORNEK = {
    "tr": {
        "yasak": "# Bu desenlere uyan pencerelere hiçbir girdi gönderilmez.\n"
                 "# örnek: çevrim içi bir oyun, parola yöneticisi\nOrnek Oyun\n^keepassxc$\n",
        "sayfa": "Örnek Sayfa — Mozilla Firefox", "sayfa_baska": "Başka Sekme", "sayfa_desen": "Örnek",
        "kwrite": "Adsız 1 - KWrite", "yazi": "Merhaba dünya",
        "dur_mesaj": "başlık değişti: 'Başka Sekme' (beklenen /Örnek/); yazma kesildi",
        "odeme": "Ödeme - Örnek Mağaza", "dugme": "Siparişi onayla", "ayar_pencere": "Ayarlar", "hesap_sil": "hesap sil",
        "kaydet": "Kaydet", "baslik": "Ödeme", "url": "https://magaza.example/odeme",
        "satirlar": (("Ürün", "Örnek kitap"), ("Adet", "1"), ("Kargo", "Standart"), ("Toplam", "249,90 TL")),
        "onay_log": "tıkla 'Siparişi onayla'", "onay_eylem": "Düğmeye tıkla: “Siparişi onayla”", "onay_hedef": "Firefox — Ödeme - Örnek Mağaza",
        "onay_ayrinti": "Ödeme sayfasında hassas düğme. Tıklanırsa sipariş verilir.",
    },
    "en": {
        "yasak": "# No input is ever sent to windows matching these patterns.\n"
                 "# e.g. an online game, a password manager\nExample Game\n^keepassxc$\n",
        "sayfa": "Example Page — Mozilla Firefox", "sayfa_baska": "Other Tab", "sayfa_desen": "Example",
        "kwrite": "Untitled 1 - KWrite", "yazi": "Hello world",
        "dur_mesaj": "title changed: 'Other Tab' (expected /Example/); typing stopped",
        "odeme": "Checkout - Example Store", "dugme": "Place order", "ayar_pencere": "Settings",
        "hesap_sil": "delete account", "kaydet": "Save", "baslik": "Checkout", "url": "https://store.example/checkout",
        "satirlar": (("Item", "Example book"), ("Quantity", "1"), ("Shipping", "Standard"), ("Total", "$24.90")),
        "onay_log": "click 'Place order'", "onay_eylem": "Click button: “Place order”", "onay_hedef": "Firefox — Checkout - Example Store",
        "onay_ayrinti": "Sensitive button on a payment page. Clicking it places the order.",
    },
}[a.dil]
O = ORNEK

# ---- sahte yasak listesi (gerçek varsayılan liste ekrana girmesin)
os.makedirs(yollar.config_dir(), exist_ok=True)
with open(yollar.yasak_dosya(), "w") as f:
    f.write(O["yasak"])

# ---- sahte günlük (biçim deskhand/gunluk.py + eylem.py: etiket | [pencere] | dotool satırı)
os.makedirs(yollar.gunluk_dizin(), exist_ok=True)
gun = os.path.join(yollar.gunluk_dizin(), time.strftime("gunluk-%Y%m%d.log"))
with open(gun, "w") as f:
    f.write(f"""10:01:02 tikla (856,657) sol | [{O['sayfa']}] | mouseto 0.334570 0.456597
10:01:02 tikla (856,657) sol | [{O['sayfa']}] | click left
10:01:05 yaz {len(O['yazi'])} karakter | arka :90 [{O['kwrite']}] | type {O['yazi']!r}
10:01:07 DUR 4 | yaz {{d7bf8f8e}} | {O['dur_mesaj']}
10:01:09 ac | kcalc | kcalc
10:01:12 onay izin | [{O['odeme']}] | {O['onay_log']}
10:01:13 onay sure | arka sanal [{O['ayar_pencere']}] | {O['hesap_sil']}
10:01:15 metne-tikla '{O['kaydet']}' | arka :90 [{O['kwrite']}] | mouseto 0.5 0.4 ; click left
""")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

os.makedirs(yollar.simge_dizin(), exist_ok=True)
for i, (ad, c) in enumerate((("save-button", (40, 120, 200)), ("menu-icon", (200, 80, 40)),
                             ("green-check", (40, 160, 80)))):
    im = Image.new("RGB", (48 + i * 10, 32), c)
    ImageDraw.Draw(im).rectangle((6, 6, 30, 22), outline=(255, 255, 255), width=3)
    im.save(os.path.join(yollar.simge_dizin(), ad + ".png"))

FONT = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
FONTB = "/usr/share/fonts/noto/NotoSans-Bold.ttf"


def ft(n, b=False):
    try:
        return ImageFont.truetype(FONTB if b else FONT, n)
    except OSError:
        return ImageFont.load_default()


from PyQt6.QtGui import QColor, QPalette  # noqa: E402
from PyQt6.QtWidgets import QApplication, QStyleFactory  # noqa: E402

app = QApplication(sys.argv[:1])
app.setStyle("Breeze" if "Breeze" in QStyleFactory.keys() else "Fusion")
if koyu:
    p = QPalette()
    for rol, c in ((QPalette.ColorRole.Window, "#202326"), (QPalette.ColorRole.WindowText, "#fcfcfc"),
                   (QPalette.ColorRole.Base, "#141618"), (QPalette.ColorRole.AlternateBase, "#1d1f22"),
                   (QPalette.ColorRole.Text, "#fcfcfc"), (QPalette.ColorRole.Button, "#292c30"),
                   (QPalette.ColorRole.ButtonText, "#fcfcfc"), (QPalette.ColorRole.Highlight, "#3daee9"),
                   (QPalette.ColorRole.PlaceholderText, "#a1a9b1")):
        p.setColor(rol, QColor(c))
    app.setPalette(p)

DUGME = (1180, 760, 1520, 830)  # onay istenen düğme (sahte ekran pikseli)


class SahteArka:
    def goruntu(self):
        im = Image.new("RGB", (1920, 1080), (140, 140, 140))
        d = ImageDraw.Draw(im)
        # arkadaki KWrite
        d.rectangle((120, 120, 900, 700), fill=(252, 252, 252), outline=(60, 60, 60), width=2)
        d.rectangle((120, 120, 900, 160), fill=(222, 224, 226))
        d.text((140, 128), O["kwrite"], fill=(30, 30, 30), font=ft(20))
        d.text((150, 190), O["yazi"], fill=(20, 20, 20), font=ft(22))
        # öndeki tarayıcı: örnek mağaza ödeme sayfası
        d.rectangle((560, 220, 1700, 900), fill=(255, 255, 255), outline=(50, 50, 50), width=2)
        d.rectangle((560, 220, 1700, 262), fill=(230, 232, 235))
        d.text((580, 228), f"{O['odeme']} — Mozilla Firefox", fill=(30, 30, 30), font=ft(20))
        d.rectangle((560, 262, 1700, 306), fill=(246, 246, 248))
        d.rounded_rectangle((600, 270, 1660, 298), 12, fill=(255, 255, 255), outline=(200, 200, 205))
        d.text((620, 272), O["url"], fill=(90, 90, 90), font=ft(18))
        d.text((620, 340), O["baslik"], fill=(20, 20, 20), font=ft(40, True))
        for i, (k, v) in enumerate(O["satirlar"]):
            y = 430 + i * 60
            son = i == len(O["satirlar"]) - 1
            d.text((620, y), k, fill=(90, 90, 90), font=ft(24))
            d.text((900, y), v, fill=(20, 20, 20), font=ft(24, son))
            d.line((620, y + 46, 1640, y + 46), fill=(225, 225, 228), width=1)
        d.rounded_rectangle(DUGME, 10, fill=(32, 120, 70))
        w = d.textlength(O["dugme"], font=ft(28, True))
        d.text(((DUGME[0] + DUGME[2] - w) / 2, DUGME[1] + 16), O["dugme"], fill=(255, 255, 255), font=ft(28, True))
        return im


SANAL = {"ekran": ":90", "boyut": [1920, 1080, 24]}


class SahteMasaustu:
    @staticmethod
    def durum(dogrula=True):
        return SANAL

    @staticmethod
    def masaustu_baslat():
        return {}

    @staticmethod
    def masaustu_durdur():
        return (True, [])

    @staticmethod
    def devral_yolu():
        return os.path.join(yollar.runtime_dir(), "devral")


from deskhand.gui import saglik  # noqa: E402
from deskhand.gui.durum import Durum  # noqa: E402
from deskhand.gui.izleyici import Izleyici  # noqa: E402
from deskhand.gui.panel import Panel  # noqa: E402

iz = Izleyici(None, sanal_f=lambda dogrula=True: SANAL, baslat=False)
p = Panel(app, None, tepsi=False, izleyici=iz, arka_f=lambda: SahteArka(), masaustu_m=SahteMasaustu,
          cakisma_f=lambda t: [], diyalog_kurma_ms=0)
w = p.pencere
w.resize(1040, 600)
w.show()
app.processEvents()
ek = "-dark" if koyu else ""
yazilan = []


def kaydet(ad, widget=None, readme=True):
    """readme=False: yalnız --hepsi ile kaydedilir."""
    for _i in range(8):
        app.processEvents()
        time.sleep(0.02)
    if readme or a.hepsi:
        yol = os.path.join(OUT, ad + ek + ".png")
        (widget or w).grab().save(yol)
        yazilan.append(yol)


SON = f"metne-tikla '{O['kaydet']}': click left"
os.utime(gun, None)
iz.yenile(sanal_zorla=True)
DA = dict(sanal_acik=True, sanal_ekran=":90")
w.durum_guncelle(Durum(ad="arka", son_eylem=SON, **DA))
kaydet("activity")
w.sekmeler.setCurrentWidget(w.arka)
w.arka.sanal_guncelle(SANAL)
kaydet("background")
# onay isteği: bu süreci panel say, istek dosyası yaz (yalnız geçici RUNTIME_DIR)
onay.panel_kaydet()
iid = "a" * 32
im = SahteArka().goruntu().crop((DUGME[0] - 60, DUGME[1] - 40, DUGME[2] + 60, DUGME[3] + 40))
gy = onay.goruntu_yolu(iid)
onay._dizin_hazirla()
im.save(gy)
onay._yaz_atomik(onay.istek_yolu(iid), {"id": iid, "eylem": O["onay_eylem"], "hedef": O["onay_hedef"],
                                        "ayrinti": O["onay_ayrinti"], "masaustu": "arka", "zaman": time.time(),
                                        "son_zaman": time.time() + 95, "pid": os.getpid(), "goruntu": gy})
iz.yenile()
w.durum_guncelle(Durum(ad="arka", bekleyen=1, son_eylem=SON, **DA))
w.sekmeler.setCurrentWidget(w.onaylar)
kaydet("approvals", readme=False)
dlg = p.diyaloglar.get(iid)
kaydet("approval", dlg)
dlg.b_red.click()
app.processEvents()
w.durum_guncelle(Durum(ad="arka", son_eylem=SON, **DA))
w.sekmeler.setCurrentWidget(w.ayarlar)
kaydet("settings", readme=False)
w.saglik.goster(saglik.denetle())
w.saglik._ilk = False
w.sekmeler.setCurrentWidget(w.saglik)
kaydet("health", readme=False)
guvenlik.dur_ac("kullanici")
iz.yenile()
w.durum_guncelle(Durum(ad="dur", dur_kaynak="kullanici", **DA))
w.sekmeler.setCurrentWidget(w.etkinlik)
kaydet("stop", readme=False)

from PyQt6.QtGui import QPainter, QPixmap  # noqa: E402

from deskhand.gui.tepsi import durum_pixmap  # noqa: E402

sira = [Durum(), Durum(ad="ekran"), Durum(ad="arka"), Durum(ad="dur", dur_kaynak="kullanici"), Durum(ad="arka", bekleyen=1)]
tuval = QPixmap(len(sira) * 72, 72)
tuval.fill(QColor("#ffffff" if not koyu else "#202326"))
qp = QPainter(tuval)
for i, d in enumerate(sira):
    qp.drawPixmap(i * 72 + 4, 4, durum_pixmap(d, 64))
qp.end()
yol = os.path.join(OUT, "tray" + ek + ".png")
tuval.save(yol)
yazilan.append(yol)
print(f"tamam ({a.dil}):", *yazilan, sep="\n  ")
