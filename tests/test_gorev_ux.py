"""Görev sekmesi UX testleri (UX-E; UX denetimi Y5 + O8): DUR açıkken TÜM başlatma yolları kapalı + görünür şerit,
DUR kalkınca hemen açık (durum sinyaliyle, yoklama yok); boş metinde görünür geri bildirim; "Görevi durdur" adı;
başlatma onayında "Bir daha sorma" tercihinin ayar API'siyle saklanıp okunması; model kaydı hatasının görünmesi.
Qt GÖRÜNMEZ (offscreen); gerçek claude çalışmaz (sahte yürütücü); ayarlar geçici klasörde (_yalitim).

Çalıştır:  python3 tests/test_gorev_ux.py"""
import json
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ.setdefault("DESKHAND_DIL", "tr")

from PIL import Image  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from deskhand import ayarlar, gorev  # noqa: E402
from deskhand.gui import gorev as GS  # noqa: E402
from deskhand.gui.durum import Durum  # noqa: E402
from deskhand.gui.pencere import AnaPencere  # noqa: E402

app = QApplication([])
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def bekle(kosul, sure=3.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        app.processEvents()
        if kosul():
            return True
        time.sleep(0.01)
    app.processEvents()
    return kosul()


class SahteArka:
    def goruntu(self):
        return Image.new("RGB", (64, 36), (30, 90, 150))


class SahteGorev:
    """Yürütücü yerine: başlatma çağrılarını sayar."""
    baslatma = 0
    son = None

    def __init__(self, olay_cb=None, **kw):
        self.olay_cb, self.kw = olay_cb, kw
        SahteGorev.son = self

    def baslat(self, metin, **kw):
        SahteGorev.baslatma += 1
        self.metin = metin
        return "abc"

    def durdur(self):
        return True

    def bekle(self, sure=None):
        return True


class SahteMasaustu:
    @staticmethod
    def durum(dogrula=True):
        return None


def bitir(sek):
    sek._olay({"tur": "bitti", "durum": "tamam"})


def ctrl_enter(sek):
    sek.kutu.setFocus()
    QTest.keyClick(sek.kutu, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()


w = AnaPencere([], arka_f=SahteArka, masaustu_m=SahteMasaustu, gorev_f=SahteGorev,
               kart_durum_f=lambda: {"goster": False})  # A3 D5: gerçek /etc, busctl, kasa okunmaz
w.resize(1000, 700)
w.show()
sek = w.gorev
app.processEvents()

# ------------------------------------------------------------------ 3) adlandırma
kontrol("koşan görevi durduran düğmenin adı 'Görevi durdur' (DUR ile karışmaz)", sek.b_durdur.text() == "Görevi durdur",
        sek.b_durdur.text())

# ------------------------------------------------------------------ 1) DUR açıkken başlatma yolları kapalı
kontrol("başta: DUR şeridi gizli, Başlat etkin", not sek.l_dur.isVisible() and sek.b_baslat.isEnabled())
w.durum_guncelle(Durum(ad="dur", dur_kaynak="kullanici"))  # panelin durum sinyali yolu (pencere → sekme)
app.processEvents()
kontrol("DUR: Başlat pasif", not sek.b_baslat.isEnabled())
kontrol("DUR: şerit görünür ve 'Devam et'e yönlendirir",
        sek.l_dur.isVisible() and "durduruldu" in sek.l_dur.text() and "Devam et" in sek.l_dur.text(), sek.l_dur.text())
sek.kutu.setPlainText("Trendyol'da şu kasayı sepete ekle")
SahteGorev.baslatma = 0
sek.b_baslat.click()
ctrl_enter(sek)
sek.kutu.setFocus()
QTest.keyClick(sek.kutu, Qt.Key.Key_Enter, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier)
sek.baslat()  # doğrudan çağrı (ör. başka bir yol) da korunur
app.processEvents()
kontrol("DUR: düğme + Ctrl+Enter + tuş takımı Enter + doğrudan çağrı → başlatma 0",
        SahteGorev.baslatma == 0 and not sek.calisiyor, str(SahteGorev.baslatma))
kontrol("DUR: çelişen 'Hazır… Başlat'a basın' satırı gizli", not sek.l_durum.isVisible())
kontrol("DUR: kutudaki metin korunur", sek.kutu.toPlainText() == "Trendyol'da şu kasayı sepete ekle")

w.durum_guncelle(Durum(ad="bos"))
app.processEvents()
kontrol("DUR kalktı: Başlat hemen etkin, şerit gizli, durum satırı geri", sek.b_baslat.isEnabled()
        and not sek.l_dur.isVisible() and sek.l_durum.isVisible())
ctrl_enter(sek)
kontrol("DUR kalktı: Ctrl+Enter görevi başlatır", SahteGorev.baslatma == 1 and sek.calisiyor)
w.durum_guncelle(Durum(ad="dur", dur_kaynak="kullanici"))
app.processEvents()
kontrol("görev koşarken DUR: 'Görevi durdur' yine etkin (durdurmak güvenli)", sek.b_durdur.isEnabled())
bitir(sek)
app.processEvents()
kontrol("görev bitti, DUR hâlâ açık: Başlat pasif kalır", not sek.b_baslat.isEnabled() and sek.l_dur.isVisible())
w.durum_guncelle(Durum(ad="bos"))
app.processEvents()

# ------------------------------------------------------------------ 2) boş metin geri bildirimi
SahteGorev.baslatma = 0
sek.kutu.setPlainText("   ")
sek._bitis_durumu = ""
sek.baslat()
app.processEvents()
kontrol("boş metin: görev başlamaz", SahteGorev.baslatma == 0 and not sek.calisiyor)
kontrol("boş metin: kısa ileti görünür", sek.l_durum.text() == GS._(GS.G_BOS_METIN) and "yazın" in sek.l_durum.text(),
        sek.l_durum.text())
kontrol("boş metin: kutu vurgulu + odakta", sek.kutu.property("hata") is True and sek.kutu.styleSheet() != ""
        and sek.kutu.hasFocus())
sek.kutu.setPlainText("İndirilenler'i düzenle")
app.processEvents()
kontrol("yazınca vurgu kalkar, ileti 'Hazır'a döner", sek.kutu.property("hata") is False and sek.kutu.styleSheet() == ""
        and sek.l_durum.text().startswith("Hazır"))

# ------------------------------------------------------------------ 4) "Bir daha sorma"
acilan = []


def sahte_exec(isaretle):
    def exec_(k):
        acilan.append(k)
        cb = k.checkBox()
        if cb is not None and isaretle:
            cb.setChecked(True)
        kabul = [b for b in k.buttons() if k.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole]
        kabul[0].click()
        return 0
    return exec_


eski_exec = QMessageBox.exec
try:
    sek.onay_iste = True
    # (a) ayar çekirdeğinde anahtar YOKSA: kutucuk gösterilmez (boş vaat yok), onay her seferinde sorulur
    anahtar_var = "baslat_onayi" in ayarlar.VARSAYILAN["gorev"]
    if not anahtar_var:
        QMessageBox.exec = sahte_exec(True)
        sek.baslat()
        kontrol("anahtar yok: onay soruldu, 'Bir daha sorma' kutucuğu YOK", len(acilan) == 1 and acilan[0].checkBox() is None)
        bitir(sek)
        sek.baslat()
        kontrol("anahtar yok: onay yine soruldu", len(acilan) == 2)
        bitir(sek)
        # ANA'nın ENT adımını taklit et: çekirdekte anahtar ([gorev] baslat_onayi = true)
        ayarlar.VARSAYILAN["gorev"]["baslat_onayi"] = True
    acilan.clear()
    QMessageBox.exec = sahte_exec(True)
    sek.baslat()
    kontrol("anahtar var: kutucuk 'Bir daha sorma' görünür", len(acilan) == 1 and acilan[0].checkBox() is not None
            and acilan[0].checkBox().text() == "Bir daha sorma")
    kontrol("işaretlendi → ayar dosyasına yazıldı ([gorev] baslat_onayi=false)",
            ayarlar.al("gorev", "baslat_onayi") is False and "baslat_onayi = false" in open(ayarlar.dosya()).read())
    bitir(sek)
    sek.baslat()
    kontrol("tercih okunur: ikinci görevde onay sorulmaz", len(acilan) == 1 and sek.calisiyor)
    bitir(sek)
    ayarlar.ayarla("gorev", "baslat_onayi", True)
    sek.baslat()
    kontrol("tercih geri açılınca onay yine sorulur", len(acilan) == 2)
    bitir(sek)
    # okuma hatası → güvenli taraf: sorulur
    eski_al = ayarlar.al
    ayarlar.al = lambda b, a: (_ for _ in ()).throw(OSError("okunamadı"))
    try:
        ayarlar.ayarla("gorev", "baslat_onayi", False)
        sek.baslat()
        kontrol("tercih okunamazsa onay sorulur (güvenli taraf)", len(acilan) == 3)
        bitir(sek)
    finally:
        ayarlar.al = eski_al
finally:
    QMessageBox.exec = eski_exec
    sek.onay_iste = False

# ------------------------------------------------------------------ 4b) UX-FIX D-4: onay penceresi açıkken DUR
def dur_acip_kabul(k):
    """Kullanıcı onay penceresine bakarken DUR açıldı (panel durum sinyali), sonra 'Başlat'a bastı."""
    acilan.append(k)
    w.durum_guncelle(Durum(ad="dur", dur_kaynak="kullanici"))
    kabul = [b for b in k.buttons() if k.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole]
    kabul[0].click()
    return 0


class MasaustuAcikGorev(SahteGorev):
    kapatarak = 0

    def baslat(self, metin, **kw):
        if not kw.get("masaustu_kapat"):
            raise gorev.GorevHatasi("Görünmez masaüstü başka bir iş için açık; kapatıp başlatılsın mı?",
                                    kod="masaustu_acik")
        MasaustuAcikGorev.kapatarak += 1
        return super().baslat(metin, **kw)


try:
    ayarlar.ayarla("gorev", "baslat_onayi", True)
    sek.onay_iste = True
    acilan.clear()
    SahteGorev.baslatma = 0
    sek.kutu.setPlainText("Trendyol'da şu kasayı sepete ekle")
    QMessageBox.exec = dur_acip_kabul
    sek.baslat()
    app.processEvents()
    kontrol("UX-FIX D-4: başlatma onayı açıkken DUR → onaylansa da görev başlamaz",
            len(acilan) == 1 and SahteGorev.baslatma == 0 and not sek.calisiyor, f"{len(acilan)} {SahteGorev.baslatma}")
    w.durum_guncelle(Durum(ad="bos"))
    app.processEvents()
    sek.onay_iste = False
    acilan.clear()
    eski_f = sek.gorev_f
    sek.gorev_f = MasaustuAcikGorev
    sek.baslat()
    app.processEvents()
    kontrol("UX-FIX D-4: 'masaüstünü kapatıp başlat' onayı açıkken DUR → masaüstü kapatılmaz, görev başlamaz",
            len(acilan) == 1 and MasaustuAcikGorev.kapatarak == 0 and not sek.calisiyor,
            f"{len(acilan)} {MasaustuAcikGorev.kapatarak}")
    sek.gorev_f = eski_f
finally:
    QMessageBox.exec = eski_exec
    sek.onay_iste = False
    w.durum_guncelle(Durum(ad="bos"))
    app.processEvents()

# ------------------------------------------------------------------ 5) model kaydı hatası görünür
kontrol("başta: model hata alanı gizli", not sek.l_hata.isVisible())
eski_ayarla = ayarlar.ayarla


def bozuk_ayarla(bolum, anahtar, deger):
    raise OSError(30, "Salt okunur dosya sistemi", "/x/ayarlar.toml")


ayarlar.ayarla = bozuk_ayarla
try:
    sek.c_model.setCurrentIndex(sek.c_model.findData("opus"))
    app.processEvents()
finally:
    ayarlar.ayarla = eski_ayarla
kontrol("model kaydı hatası: ne oldu + ne yapmalı görünür",
        sek.l_hata.isVisible() and "kaydedilemedi" in sek.l_hata.text() and "yazılabilir" in sek.l_hata.text(),
        sek.l_hata.text())
kontrol("ayrıntı katlı: başta gizli, 'Ayrıntı' ile açılır ve hatayı içerir",
        sek.b_ayrinti.isVisible() and not sek.l_ayrinti.isVisible())
sek.b_ayrinti.click()
app.processEvents()
kontrol("ayrıntı açık: hata metni", sek.l_ayrinti.isVisible() and "Salt okunur" in sek.l_ayrinti.text(), sek.l_ayrinti.text())
SahteGorev.son = None
sek.kutu.setPlainText("Bir şey yap")
sek.baslat()
kontrol("kaydedilemeyen seçim yine de bu görevde kullanılır (model=opus)",
        SahteGorev.son is not None and SahteGorev.son.kw.get("model") == "opus", str(SahteGorev.son and SahteGorev.son.kw))
bitir(sek)
sek.c_model.setCurrentIndex(sek.c_model.findData("sonnet"))
app.processEvents()
kontrol("sonraki başarılı kayıt hata alanını kapatır", not sek.l_hata.isVisible() and ayarlar.al("gorev", "model") == "sonnet")

# ------------------------------------------------------------------ 6) TR + EN metinler
en = json.load(open(os.path.join(_yalitim.KOK, "deskhand", "i18n", "en.json"), encoding="utf-8"))
yeni = [GS.G_DUR_SERIDI, GS.G_BOS_METIN, GS.G_GOREVI_DURDUR, GS.G_GOREVI_DURDUR_IPUCU, GS.G_BIR_DAHA_SORMA,
        GS.G_MODEL_KAYIT_HATA, GS.G_TERCIH_KAYIT_HATA, GS.G_AYRINTI, GS.G_KUTU_AD, GS.G_SITELER_AD, GS.G_SONUC_AD]
eksik = [m for m in yeni if not en.get(m)]
kontrol("yeni metinlerin hepsinin İngilizcesi var", not eksik, str(eksik))

w.close()
print(f"\n{gecen}/{toplam} görev UX testi geçti")
sys.exit(0 if gecen == toplam else 1)
