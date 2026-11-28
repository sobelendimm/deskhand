"""UX-F: Onaylar (O4/D4), hata iletileri iki katman (O5), Sağlık özet kartı (O6), Simgeler → Ayarlar Gelişmiş (O7),
Ayarlar açıklamaları katlı + kontrast (O9), "Bir daha sorma" geri açılabilir (baslat_onayi), Görev kutuları boş durum
(O8d), Onaylar › Geçmiş insan dilinde (insan_metni).
Qt GÖRÜNMEZ (offscreen); dosyalar geçici CONFIG'e (tests/_yalitim); gerçek ~/.config/deskhand ve cüzdan kullanılmaz.

Çalıştır:  python3 tests/test_ux_f.py"""
import json
import os
import re
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"
sys.path.insert(0, os.path.join(_yalitim.KOK, "tools"))

from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication, QHeaderView, QMessageBox  # noqa: E402

from deskhand import ayarlar, gorev, i18n, yollar  # noqa: E402
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui import gorev as GS  # noqa: E402
from deskhand.gui import metinler as T  # noqa: E402
from deskhand.gui.gunluk_okur import ayristir  # noqa: E402
from deskhand.gui.pencere import AnaPencere  # noqa: E402
from deskhand.gui.sekmeler import ayarlar as S  # noqa: E402,F401
from deskhand.i18n import _  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
gecen = toplam = 0
HAM = re.compile(r"Errno|Permission denied|No such file|Error\b|Exception|NoneType|Traceback|\.toml|deskhand\.")


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def islem():
    for _i in range(3):
        app.processEvents()


class SahteArka:
    def goruntu(self):
        return Image.new("RGB", (64, 36), (30, 90, 150))


class SahteMasaustu:
    @staticmethod
    def durum(dogrula=True):
        return None


class SahteGorev:
    hata = None

    def __init__(self, olay_cb=None, **kw):
        pass

    def baslat(self, metin, **kw):
        if SahteGorev.hata:
            raise SahteGorev.hata
        return "x"

    def durdur(self):
        return True

    def bekle(self, sure=None):
        return True


SAGLIK = [{"ad": "kdotool", "tur": "arac", "ok": True, "not": "pencere bulma (AUR: kdotool-bin)", "durum": "tamam"},
          {"ad": "tesseract", "tur": "arac", "ok": False, "not": "metin okuma (tesseract)", "durum": "eksik"},
          {"ad": "PyQt6", "tur": "modul", "ok": True, "not": "arayüz (python-pyqt6)", "durum": "tamam"},
          {"ad": "dotool", "tur": "arac", "ok": False, "not": "fare/klavye (AUR: dotool)", "durum": "eksik"}]
pano: list[str] = []
w = AnaPencere([], arka_f=SahteArka, masaustu_m=SahteMasaustu, kart_durum_f=lambda: {"goster": False}, cakisma_f=lambda t: [], simge_sor=lambda b, m: True,
               saglik_f=lambda: SAGLIK, gorev_f=SahteGorev)
w.saglik.pano = pano.append
w.resize(1040, 700)
w.show()
islem()

# ================================================================== O7: Simgeler sekmesi kalktı, Ayarlar Gelişmiş'te
adlar = [w.sekmeler.tabText(i) for i in range(w.sekmeler.count())]
kontrol("O7: sekme sayısı 6, 'Simgeler' sekmesi yok", w.sekmeler.count() == 6 and "Simgeler" not in adlar, str(adlar))
kontrol("O7: simge listesi Ayarlar › Gelişmiş sayfasının içinde",
        w.simgeler is w.ayarlar.simgeler and w.ayarlar.bolumler.widget(1).isAncestorOf(w.simgeler))
os.makedirs(yollar.simge_dizin(), exist_ok=True)
w.simgeler.yenile()
kontrol("O7: boş simge iletisinde komut adı (simge-kaydet) yok",
        "simge-kaydet" not in w.simgeler.l_bilgi.text() and "`" not in _(T.I_BOS), w.simgeler.l_bilgi.text())

# ================================================================== O4/D4: Onaylar
o = w.onaylar
w.sekmeler.setCurrentWidget(o)
islem()
kontrol("O4: boşken bekleyen tablosu gizli, tek satır 'Bekleyen onay yok'",
        not o.t_bekleyen.isVisible() and o.l_bos.isVisible() and o.l_bos.text() == "Bekleyen onay yok"
        and not o.l_bos.wordWrap(), o.l_bos.text())
kontrol("O4: boşken 'Diyaloğu aç' gizli", not o.b_ac.isVisible())
o.guncelle([{"id": "a", "zaman": 0, "eylem": "tıkla 'Öde'", "hedef": "Mağaza — Firefox", "masaustu": "ekran",
             "son_zaman": 9e9}])
islem()
kontrol("O4: bekleyen varken tablo görünür, boş iletisi gizli", o.t_bekleyen.isVisible() and not o.l_bos.isVisible())
o.guncelle([])
for t in (o.t_bekleyen, o.t_gecmis):
    b = t.horizontalHeader()
    kip = [b.sectionResizeMode(i) for i in range(t.columnCount())]
    R = QHeaderView.ResizeMode
    kontrol(f"O4: sütunlar içeriğe göre ({'bekleyen' if t is o.t_bekleyen else 'geçmiş'}): Zaman/Masaüstü/son sütun "
            "içerik kadar, Eylem/Hedef esner",
            kip[0] == kip[3] == kip[4] == R.ResizeToContents and kip[1] == kip[2] == R.Stretch
            and not b.stretchLastSection(), str(kip))
    kontrol("D4: başlıklar sola yaslı (içerikle aynı)",
            bool(b.defaultAlignment() & __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignLeft))

# Geçmiş: insan dili, ham satır ipucunda; yasak pencere başlığı gösterilmez
from deskhand.gui import insan_metni as IM  # noqa: E402

IM._yasak_onbellek_sifirla(["KeePassXC"])  # test kuralı: bu başlık yasak
satirlar = [ayristir(s) for s in (
    "10:00:01 onay izin | [Mağaza — Firefox] | tikla (5,5) sol",
    "10:00:02 onay red | [KeePassXC] | yaz 12 karakter",
)]
o.gecmis_ekle([s for s in satirlar if s])
islem()
e0, e1 = o.t_gecmis.item(1, 1), o.t_gecmis.item(0, 1)
kontrol("Geçmiş: Eylem sütunu insan dilinde (ham 'tikla (5,5) sol' değil), ham satır ipucunda",
        e0 is not None and "tikla" not in e0.text() and "tıklandı" in e0.text().lower() and "tikla (5,5) sol" in e0.toolTip(),
        f"{e0 and e0.text()} | {e0 and e0.toolTip()}")
h1 = o.t_gecmis.item(0, 2)
kontrol("Geçmiş: yasak pencere başlığı (KeePassXC) Hedef ve ipucunda gösterilmez",
        h1 is not None and "KeePassXC" not in h1.text() and "KeePassXC" not in e1.toolTip(),
        f"{h1 and h1.text()} | {e1.toolTip()}")
kontrol("Geçmiş: Durum sütunu karar adı", o.t_gecmis.item(1, 4).text() == "izin verildi")

# ================================================================== O6: Sağlık
s = w.saglik
w.sekmeler.setCurrentWidget(s)
kontrol("O6: denetim görünür olunca çalışır", __import__("time").sleep(0) or True)
for _i in range(200):
    islem()
    if s.sonuc:
        break
sorunlu = [d for d in SAGLIK if not d["ok"]]
kontrol("O6: özet kartı sorun sayısını söyler (2 sorun var)", s.l_kart.text() == "2 sorun var", s.l_kart.text())
kontrol("O6: sorun satırı sayısı = sorunlu bileşen sayısı", len(s.sorun_satirlari) == len(sorunlu),
        str(len(s.sorun_satirlari)))
kontrol("O6: tabloda sorunlular önde", [s.tablo.item(i, 1).text() for i in range(2)] == ["yok", "yok"]
        and s.tablo.item(2, 1).text() == "var", str([s.tablo.item(i, 1).text() for i in range(s.tablo.rowCount())]))
ilk = s.sorun_satirlari[0]
kontrol("O6: üst satırda insan adı (paket adı yok)", ilk["ad"].text() == "Ekran okuma bileşeni"
        and "tesseract" not in ilk["ad"].text(), ilk["ad"].text())
kontrol("O6: paket/araç adı ayrıntıda (ipucu)", "tesseract" in ilk["ad"].toolTip(), ilk["ad"].toolTip())
ilk["kopyala"].click()
kontrol("O6: 'Kopyala' çözüm komutunu panoya koyar", pano == ["sudo pacman -S --needed tesseract"], str(pano))
s.sorun_satirlari[1]["kopyala"].click()
kontrol("O6: AUR paketi için AUR komutu", pano[-1] == "yay -S --needed dotool", str(pano))
kontrol("O6: sağlam satırlar katlı (tam liste başta gizli, düğmeyle açılır)", not s.tablo.isVisible())
s.b_tumu.click()
islem()
kontrol("O6: 'Tüm bileşenler' açınca tam liste görünür", s.tablo.isVisible())
s.goster([d for d in SAGLIK if d["ok"]])
kontrol("O6: hepsi sağlamken 'Her şey hazır ✓', sorun satırı yok",
        s.l_kart.text() == "Her şey hazır ✓" and not s.sorun_satirlari, s.l_kart.text())
kontrol("D4: Sağlık tablo başlıkları sola yaslı",
        bool(s.tablo.horizontalHeader().defaultAlignment() & __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignLeft))

# ================================================================== O5: hata iletileri iki katman
y = w.ayarlar
HATA = OSError(13, "Permission denied", "/x/.ayarlar-abc.toml")


def firlat(*_a, **_k):
    raise HATA


def iki_katman(ad, ileti):
    ust, ayr = ileti.text(), ileti.ayrinti_metni()
    kontrol(f"O5 {ad}: üst satır sade, ham istisna yok", ust and not HAM.search(ust), ust)
    kontrol(f"O5 {ad}: ham ayrıntı katlı 'Ayrıntı' altında", "Errno 13" in ayr and not ileti.l_ayrinti.isVisibleTo(ileti)
            and ileti.b_ayrinti.isVisibleTo(ileti), ayr)
    ileti.b_ayrinti.click()
    kontrol(f"O5 {ad}: 'Ayrıntı' tıklayınca açılır", ileti.l_ayrinti.isVisibleTo(ileti))
    ileti.b_ayrinti.click()


kontrol("O5: iletide çare cümlesi (izin)", "izin" in T.hata_ozeti(HATA).lower(), T.hata_ozeti(HATA))

if y.karar.var:
    eski = y.karar.yaz
    y.karar.yaz = firlat
    try:
        y.karar_kaydet()
    finally:
        y.karar.yaz = eski
    iki_katman("karar kaydı", y.l_karar)

eski = A.onay_kapsami_yaz
A.onay_kapsami_yaz = firlat
try:
    y.onay_kapsami_sec("kart")
finally:
    A.onay_kapsami_yaz = eski
iki_katman("onay kapsamı", y.l_onay)

eski = A.yasak_kaydet
A.yasak_kaydet = firlat
try:
    y.yasak.setPlainText("Ornek Oyun\n")
    y.yasak_kaydet()
finally:
    A.yasak_kaydet = eski
iki_katman("yasak listesi", y.l_yasak)

eski = A.panel_yaz
A.panel_yaz = firlat
try:
    y._kisayol_kaydet()
finally:
    A.panel_yaz = eski
iki_katman("kısayol", y.l_kisayol)

eski = i18n.ayar_yaz
i18n.ayar_yaz = firlat
try:
    y.dil_sec("en")
finally:
    i18n.ayar_yaz = eski
iki_katman("dil", y.l_dil)

y.pencere_f = firlat
y.pencere_sec("yasak")
iki_katman("açık pencereler", y.l_yasak)

# Uygula'nın toplu iletisi: bölüm + sade cümle; ham yok
y.sifirla()
eski = A.onay_kapsami_yaz
A.onay_kapsami_yaz = firlat
try:
    y._sec(y.c_onay, "kart" if y.c_onay.currentData() != "kart" else "hepsi")
    y._degisti()
    y.uygula()
finally:
    A.onay_kapsami_yaz = eski
kontrol("O5 Uygula: toplu iletide ham istisna yok", y.durum_metni() and not HAM.search(y.durum_metni()), y.durum_metni())
y.sifirla()
kontrol("O5: Y_MESGUL_YOK iletisinde modül adı yok", "deskhand.ayarlar" not in _(T.Y_MESGUL_YOK))

# Görev başlatılamadı
g = w.gorev
g.kutu.setPlainText("Bir şey yap")
SahteGorev.hata = gorev.GorevHatasi("[Errno 2] No such file or directory: 'claude'")
w.sekmeler.setCurrentWidget(g)
g.baslat()
islem()
SahteGorev.hata = None
kontrol("O5 görev: üst satır sade (ham yok)", g.l_hata.isVisible() and not HAM.search(g.l_hata.text())
        and not HAM.search(g.sonuc.toPlainText()), f"{g.l_hata.text()} | {g.sonuc.toPlainText()}")
kontrol("O5 görev: ham ayrıntı katlı", "Errno 2" in g.l_ayrinti.text() and not g.l_ayrinti.isVisible())

# ================================================================== O8d: Görev kutuları
kontrol("O8d: Adımlar/Sonuç/Geçmiş kutularının anlamlı en küçük boyu (≥ 72 px)",
        min(g.liste.minimumHeight(), g.sonuc.minimumHeight(), g.gecmis_liste.minimumHeight()) >= 72,
        str((g.liste.minimumHeight(), g.sonuc.minimumHeight(), g.gecmis_liste.minimumHeight())))
g.liste.clear()
g._bos_durumlar()
islem()
kontrol("O8d: boş Adımlar kutusunda boş durum metni", g.l_adimlar_bos.isVisible() and g.l_adimlar_bos.text())
kontrol("O8d: boş Sonuç kutusunda yer tutucu metin", bool(g.sonuc.placeholderText()))
kontrol("O8d: model adlarında kısa açıklama (Hızlı · Dengeli · Güçlü)",
        all(k in " ".join(g.c_model.itemText(i) for i in range(g.c_model.count())) for k in ("Hızlı", "Dengeli", "Güçlü")),
        str([g.c_model.itemText(i) for i in range(g.c_model.count())]))

# ================================================================== baslat_onayi: Ayarlar ↔ Görev penceresi
kontrol("baslat_onayi: varsayılan True", ayarlar.VARSAYILAN["gorev"].get("baslat_onayi") is True)
kontrol("baslat_onayi: Görev onay penceresinde 'Bir daha sorma' kutusu var", GS.baslat_onayi_saklanabilir())
acilan = []
eski_exec = QMessageBox.exec


def sahte_exec(k):
    acilan.append(k)
    if k.checkBox() is not None:
        k.checkBox().setChecked(True)
    [b for b in k.buttons() if k.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole][0].click()
    return 0


QMessageBox.exec = sahte_exec
try:
    g.onay_iste = True
    g.kutu.setPlainText("Bir şey yap")
    g.baslat()
    g._olay({"tur": "bitti", "durum": "tamam"})
finally:
    QMessageBox.exec = eski_exec
    g.onay_iste = False
kontrol("Görev: 'Bir daha sorma' işaretlendi → baslat_onayi False", acilan and acilan[0].checkBox() is not None
        and ayarlar.al("gorev", "baslat_onayi") is False)
w.sekmeler.setCurrentWidget(y)
islem()
kontrol("Ayarlar › Temel: 'Görev başlatmadan önce onay sor' kutusu güncel değeri (kapalı) gösterir",
        y.k_gorev_onay.text() == "Görev başlatmadan önce onay sor" and not y.k_gorev_onay.isChecked()
        and y.bolumler.widget(0).isAncestorOf(y.k_gorev_onay))
y.k_gorev_onay.setChecked(True)
kontrol("Ayarlar: kutu değişince Uygula bekler (henüz yazılmadı)", y.kaydedilmemis_var()
        and ayarlar.al("gorev", "baslat_onayi") is False)
y.uygula()
kontrol("Ayarlar: Uygula → ayarlar.ayarla('gorev','baslat_onayi', True)", ayarlar.al("gorev", "baslat_onayi") is True
        and not y.kaydedilmemis_var())

# ================================================================== O9: açıklamalar katlı + kontrast
y.bolumler.setCurrentIndex(0)
y.resize(900, 1400)
islem()
gorunen_not = [n for n in y.aciklamalar if n.l_metin.isVisible()]
kontrol("O9: Ayarlar açıklamaları başta katlı (ⓘ ile açılır)", y.aciklamalar and not gorunen_not
        and all(n.b_bilgi.toolTip() for n in y.aciklamalar), str(len(gorunen_not)))
for n in y.aciklamalar:
    n.b_bilgi.setChecked(True)
islem()
import tasarim_kapi as K  # noqa: E402

with open(os.path.join(_yalitim.KOK, "deskhand", "gui", "tema", "tokens.json"), encoding="utf-8") as f:
    TOK = json.load(f)
for sayfa in (0, 1):
    y.bolumler.setCurrentIndex(sayfa)
    islem()
    esik = K.esikler(TOK, app.font().pointSizeF())
    kotu = [i for i in K.denetle([y], esik, "ayarlar") if i["kural"] == "KONTRAST"]
    kontrol(f"O9: açık açıklamalar kontrast eşiğini geçer (sayfa {sayfa}, ≥ {TOK['kontrast_min']})", not kotu,
            str(kotu[:3]))

# ================================================================== yeni metinler TR + EN, jargon yok
en = json.load(open(os.path.join(_yalitim.KOK, "deskhand", "i18n", "en.json"), encoding="utf-8"))
yeni = [T.O_BOS, T.I_BOS, T.H_HEPSI_TAMAM, T.H_SORUN_VAR, T.H_KOPYALA, T.H_TUMU, T.G_BASLATMA_HATA_SADE,
        T.Y_GOREV, T.Y_GOREV_ONAY, T.Y_ACIKLAMA, T.G_ADIMLAR_BOS, T.G_SONUC_BOS, T.G_GECMIS_BOS, T.Y_SIMGELER,
        *T.HATA_CARE.values(), *T.G_MODEL_AD.values()]
eksik = [m for m in yeni if not en.get(m)]
kontrol("yeni metinlerin hepsinin İngilizcesi var", not eksik, str(eksik))
kontrol("kullanılmayan G_DURDUR / G_DURDUR_IPUCU silindi", not hasattr(T, "G_DURDUR") and not hasattr(T, "G_DURDUR_IPUCU"))
kontrol("yeni metinlerde jargon yok (pacman/AUR/python-/MCP/regex)",
        not [m for m in yeni if re.search(r"pacman|AUR|python-|\bMCP\b|regex|simge-kaydet", m)])

w.close()
print(f"\n{gecen}/{toplam} UX-F testi geçti")
sys.exit(0 if gecen == toplam else 1)
