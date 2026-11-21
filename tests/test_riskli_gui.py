"""Panel: Ayarlar sekmesindeki 'Uygulama erişim seviyeleri' düzenleyicisi (Faz 9d). Qt GÖRÜNMEZ çalışır
(QT_QPA_PLATFORM=offscreen; gerçek ekrana pencere açılmaz, girdi gitmez). Dosya geçici CONFIG'e yazılır.

Çalıştır:  python3 tests/test_riskli_gui.py"""
import hashlib
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"  # kglobalshortcutsrc gerçek dosyası okunmasın
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

os.environ.setdefault("DESKHAND_DIL", "tr")

from PyQt6.QtWidgets import QApplication, QPlainTextEdit  # noqa: E402

from deskhand import guvenlik, yollar  # noqa: E402
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui import metinler as T  # noqa: E402
from deskhand.gui.pencere import AyarlarSekmesi  # noqa: E402
from deskhand.i18n import _  # noqa: E402

app = QApplication([])
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def ozet(yol):
    h = hashlib.sha1()
    for d, _x, dosyalar in sorted(os.walk(os.path.expanduser(yol))):
        for f in sorted(dosyalar):
            p = os.path.join(d, f)
            try:
                with open(p, "rb") as fp:
                    h.update(p.encode() + fp.read())
            except OSError:
                pass
    return h.hexdigest()


gercek0 = ozet("~/.config/deskhand")
y = AyarlarSekmesi(cakisma_f=lambda tus: [])
kontrol("Ayarlar sekmesinde seviye düzenleyicisi var (yasak düzenleyicisinin yanında)",
        isinstance(y.seviye, QPlainTextEdit) and isinstance(y.yasak, QPlainTextEdit))
kontrol("yasak ve seviye kutuları ayrı", y.seviye is not y.yasak)
kontrol("sekme açılınca dosya OLUŞTURULMAZ (varsayılan kurulumda dosya yok)", not os.path.exists(yollar.seviye_dosya()))
kontrol("boş şablon açıklama gösterir, kural satırı YOK",
        "goruntule" in y.seviye.toPlainText() and "tikla" in y.seviye.toPlainText() and
        not [l for l in y.seviye.toPlainText().splitlines() if l.strip() and not l.lstrip().startswith("#")])
kontrol("şablonu olduğu gibi kaydetmek kısıt koymaz", y.seviye_kaydet() and guvenlik.seviye_kurallari() == [] and
        yollar.seviye_dosya().startswith(_yalitim.GECICI), str(guvenlik.seviye_kurallari()))
os.remove(yollar.seviye_dosya())
for baslik in (T.Y_SEVIYE, T.Y_SEVIYE_ACIKLAMA, T.Y_SEVIYE_HATA):
    kontrol(f"metin metinler.py'de Türkçe ve _() ile çevrilebilir: {baslik[:30]!r}", isinstance(_(baslik), str) and
            hasattr(T, "Y_SEVIYE"))
kontrol("grup başlığı", _(T.Y_SEVIYE) == "Uygulama erişim seviyeleri")

# geçersiz satırlar kaydedilmez
for metin, satir in (("# a\nDefter = bilinmeyen", 2), ("Defter", 1), ("= tikla", 1), ("# a\n\n(bozuk[ = tikla", 3)):
    y.seviye.setPlainText(metin)
    kontrol(f"geçersiz kural kaydedilmez ({satir}. satır): {metin!r}",
            not y.seviye_kaydet() and f"{satir}. satır" in y.l_seviye.text() and not os.path.exists(yollar.seviye_dosya()),
            y.l_seviye.text())
# geçerli kurallar kaydedilir (eş adlar dahil) ve hemen geçerli olur
y.seviye.setPlainText("# not\nKeePassXC = goruntule\nkonsole = click\n^Belge = view\nkwrite = full\n")
kontrol("geçerli kurallar geçici CONFIG'e kaydedildi", y.seviye_kaydet() and os.path.exists(yollar.seviye_dosya())
        and yollar.seviye_dosya().startswith(_yalitim.GECICI))
kontrol("kaydedilen kurallar okunuyor (eş adlar dahil)", guvenlik.seviye_kurallari() ==
        [("KeePassXC", 0), ("konsole", 1), ("^Belge", 0), ("kwrite", 2)], str(guvenlik.seviye_kurallari()))
kontrol("'Kaydedildi.' iletisi", y.l_seviye.text() == _(T.Y_KAYDEDILDI))
kontrol("seviye kaydı yasak-pencereler dosyasını OLUŞTURMAZ/DEĞİŞTİRMEZ", not os.path.exists(yollar.yasak_dosya()))
y.seviye.setPlainText("başka bir şey")
y.seviye_yukle()
kontrol("Geri al: dosyadaki metne döner", "KeePassXC = goruntule" in y.seviye.toPlainText() and y.l_seviye.text() == "")
y2 = AyarlarSekmesi(cakisma_f=lambda tus: [])
kontrol("yeni sekme kaydedileni gösterir", "konsole = click" in y2.seviye.toPlainText())
y.seviye.setPlainText("# yalnız yorum\n")
kontrol("tüm kuralları silip kaydetmek kısıtı kaldırır", y.seviye_kaydet() and guvenlik.seviye_kurallari() == [])
y.tazele()
kontrol("dil/tazele: durum etiketi temizlenir", y.l_seviye.text() == "")
os.remove(yollar.seviye_dosya())
kontrol("gerçek ~/.config/deskhand DEĞİŞMEDİ (sha1)", ozet("~/.config/deskhand") == gercek0)
print(f"\n{gecen}/{toplam} panel seviye testi geçti")
sys.exit(0 if gecen == toplam else 1)
