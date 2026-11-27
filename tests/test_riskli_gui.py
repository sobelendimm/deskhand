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

from deskhand import guvenlik, liste_koruma, yollar  # noqa: E402
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui import metinler as T  # noqa: E402
from deskhand.gui.pencere import AyarlarSekmesi  # noqa: E402
from deskhand.hata import Dur  # noqa: E402
from deskhand.i18n import _  # noqa: E402
from deskhand.oturum.kalici import AnahtarYok  # noqa: E402


class SahteKasa:
    """Açık cüzdan yerine bellekteki panel kaydı (Secret Service sahtesi; gerçek cüzdana dokunulmaz). Panel kaydı
    imzalar → otomasyon dosyayı panelin onaylı değeriyle doğrular (H3: imzasız işaretli dosyada kapalı-başarısız)."""
    veri = None

    def oku(self):
        return self.veri

    def yaz(self, v):
        self.veri = bytes(v)


class KilitliKasa:
    def oku(self):
        raise AnahtarYok("cüzdan kilitli")

    def yaz(self, v):
        raise AnahtarYok("cüzdan kilitli")


liste_koruma.isaret_anahtarlik_ayarla(SahteKasa())
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
# tek kaydetme modeli (UX-A, f792c6a): kullanıcı Uygula'ya basar; başarı ortak durum satırında "Kaydedildi ✓"
kontrol("bekleyen değişiklik: seviye", y.degisenler() == ["seviye"], str(y.degisenler()))
kontrol("geçerli kurallar geçici CONFIG'e kaydedildi (Uygula)", y.uygula() and os.path.exists(yollar.seviye_dosya())
        and yollar.seviye_dosya().startswith(_yalitim.GECICI))
kontrol("kaydedilen kurallar okunuyor (eş adlar dahil)", guvenlik.seviye_kurallari() ==
        [("KeePassXC", 0), ("konsole", 1), ("^Belge", 0), ("kwrite", 2)], str(guvenlik.seviye_kurallari()))
kontrol("kullanıcı 'Kaydedildi ✓' görür, bölümde hata iletisi kalmaz, bekleyen değişiklik yok",
        y.durum_metni() == _(T.Y_KAYDEDILDI_TIK) and y.l_seviye.text() == "" and not y.kaydedilmemis_var(),
        f"{y.durum_metni()!r} {y.l_seviye.text()!r}")
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
# bilinçli güvenlik davranışı (H3): panelin imzalı kaydı okunamıyorsa (kilitli/yok cüzdan) işaretli dosya kullanılmaz
liste_koruma.isaret_anahtarlik_ayarla(KilitliKasa())
try:
    guvenlik.seviye_kurallari()
    kod = None
except Dur as e:
    kod = e.kod
kontrol("cüzdan kilitliyken kayıtlı seviye dosyası doğrulanamaz → Dur 10 (kapalı-başarısız)", kod == 10, str(kod))
liste_koruma.isaret_anahtarlik_ayarla(SahteKasa())
os.remove(yollar.seviye_dosya())
kontrol("gerçek ~/.config/deskhand DEĞİŞMEDİ (sha1)", ozet("~/.config/deskhand") == gercek0)
print(f"\n{gecen}/{toplam} panel seviye testi geçti")
sys.exit(0 if gecen == toplam else 1)
