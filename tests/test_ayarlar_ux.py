"""Ayarlar: tek kaydetme modeli (Uygula · Sıfırla), Temel/Gelişmiş bölümleri, yasak/seviye görsel düzenleyici (UX-A).

Kapsam: değer değişince "Kaydedildi ✓" hemen kalkar ve "Kaydedilmemiş değişiklikler var" çıkar; Uygula kaydeder ve
göstergeyi kaldırır; "Kaydedildi ✓" ~2 sn sonra kendiliğinden kalkar; Sıfırla kayıtlı değere döner; kayıt hatası →
görünür hata (ne oldu + ne yapmalı) + değer kayıtlı haline döner; sekmeden ayrılırken Uygula / At / İptal sorusu;
güvenlik ayarları Uygula'da panelin imzalı kayıt yolundan (liste_koruma.panel_*) ve hesap onay diyaloğundan geçer,
Uygula'sız hiçbir yazma olmaz; kapat-aç sonrası kayıtlı değer görünür; açık pencerelerden "Uygulama ekle" + seviye
açılır kutusu; kullanıcıya regex/kaçış karakteri gösterilmez.
Qt GÖRÜNMEZ (offscreen); dosyalar geçici CONFIG'e (tests/_yalitim); gerçek ~/.config/deskhand ve cüzdan kullanılmaz.

Çalıştır:  python3 tests/test_ayarlar_ux.py"""
import os
import re
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"  # kglobalshortcutsrc gerçek dosyası okunmasın
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"

from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QGroupBox, QLabel, QTabWidget, QWidget  # noqa: E402

from deskhand import guvenlik, liste_koruma  # noqa: E402
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui import metinler as T  # noqa: E402
from deskhand.gui.sekmeler import ayarlar as S  # noqa: E402
from deskhand.i18n import _  # noqa: E402

app = QApplication([])
gecen = toplam = 0


class SahteKasa:  # panelin imzalı durumu (Secret Service yerine bellek); gerçek cüzdana dokunulmaz
    v = None

    def oku(self):
        return self.v

    def yaz(self, v):
        self.v = v


liste_koruma.isaret_anahtarlik_ayarla(SahteKasa())


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def yeni():
    return S.AyarlarSekmesi(cakisma_f=lambda tus: [])


DEGISIKLIK, KAYDEDILDI = _(T.Y_DEGISIKLIK_VAR), _(T.Y_KAYDEDILDI_TIK)
y = yeni()

# ---------------------------------------------------------------- bölümler
basliklar = [y.bolumler.tabText(i) for i in range(y.bolumler.count())]
kontrol("iki bölüm: Temel / Gelişmiş", basliklar == ["Temel", "Gelişmiş"], str(basliklar))


def gruplar(i):
    return [g.title() for g in y.bolumler.widget(i).findChildren(QGroupBox)]


kontrol("Temel: Dil (üstte), Onay soruları, Meşgulken", gruplar(0) == ["Dil", "Onay soruları", "Meşgulken davranış"],
        str(gruplar(0)))
kontrol("Gelişmiş: Yasaklar, Seviyeler, Hesap oturumları, Kısayol, İzinler (yer tutucu)", gruplar(1) == [
    "Yasak pencereler", "Uygulama erişim seviyeleri", "Hesap oturumları", "Genel kısayol", "İzinler"], str(gruplar(1)))

# ---------------------------------------------------------------- tek kaydetme modeli
kontrol("başlangıç: bekleyen değişiklik yok, Uygula/Sıfırla kapalı, durum boş",
        not y.kaydedilmemis_var() and not y.b_uygula.isEnabled() and not y.b_sifirla.isEnabled() and
        y.durum_metni() == "")
if not y.karar.var:
    print("ATLANDI  meşgulken (deskhand.ayarlar yok)")
    sys.exit(1)
from deskhand import ayarlar as AY  # noqa: E402

ilk_sure = AY.al("karar", "sor_sure")
y.s_sure.setValue(41)
kontrol("değer değişince: 'Kaydedilmemiş değişiklikler var' + Uygula açık, diske yazılmadı",
        y.durum_metni() == DEGISIKLIK and y.b_uygula.isEnabled() and AY.al("karar", "sor_sure") == ilk_sure,
        y.durum_metni())
kontrol("Uygula → kaydedildi", y.uygula() and AY.al("karar", "sor_sure") == 41)
kontrol("Uygula sonrası: 'Kaydedildi ✓', gösterge kalktı, Uygula kapalı",
        y.durum_metni() == KAYDEDILDI and not y.kaydedilmemis_var() and not y.b_uygula.isEnabled(), y.durum_metni())
y.s_sure.setValue(42)
kontrol("değer yeniden değişince 'Kaydedildi' HEMEN kalkar (bayat ileti yok)",
        y.durum_metni() == DEGISIKLIK and KAYDEDILDI not in y.durum_metni(), y.durum_metni())
y.sifirla()
kontrol("Sıfırla → kayıtlı değere döner, bekleyen yok", y.s_sure.value() == 41 and not y.kaydedilmemis_var())
y.s_sure.setValue(43)
y.uygula()
QTest.qWait(S.KAYDEDILDI_MS + 400)
kontrol("'Kaydedildi ✓' ~2 sn sonra kendiliğinden kalkar", y.durum_metni() == "", y.durum_metni())

# ---------------------------------------------------------------- kayıt hatası: görünür + geri
asil_panel_yaz = A.panel_yaz


def bozuk_yaz(_d):
    raise OSError(28, "No space left on device")


A.panel_yaz = bozuk_yaz
try:
    kayitli_acik = A.panel_oku()["kisayol_acik"]
    y.k_acik.setChecked(not kayitli_acik)
    sonuc = y.uygula()
    kontrol("kayıt hatası → Uygula başarısız, görünür hata (ne oldu + ne yapmalı)",
            not sonuc and "kaydedilemedi" in y.durum_metni() and "yeniden deneyin" in y.durum_metni() and
            "No space" in y.durum_metni(), y.durum_metni())
    kontrol("kayıt hatası → değer kayıtlı haline döndü", y.k_acik.isChecked() == kayitli_acik and
            not y.kaydedilmemis_var())
finally:
    A.panel_yaz = asil_panel_yaz

# ---------------------------------------------------------------- güvenlik ayarları Uygula içinde imzalı yoldan
cagrilar = []
asil = {ad: getattr(liste_koruma, ad) for ad in ("panel_kaydet", "panel_kapsam_kaydet", "panel_kimlik_kaydet")}


def kaydedici(ad):
    def f(*a, **k):
        cagrilar.append((ad, a))
        if ad != "panel_kimlik_kaydet":  # kimlik: sahte (cüzdan yok); diğerleri gerçek imzalı yol
            return asil[ad](*a, **k)
    return f


for ad in asil:
    setattr(liste_koruma, ad, kaydedici(ad))
sorulan = []
try:
    y.uygulama_ekle("yasak", ("Örnek", re.escape("org.ornek.Uygulama")))
    y._sec(y.c_onay, "kart")
    y.c_onay.activated.emit(y.c_onay.currentIndex())
    y.hesap_onay_sor = lambda sag: sorulan.append(sag) or False  # kullanıcı Hayır der
    y.k_hesap["google"].setChecked(True)
    kontrol("Uygula'dan önce hiçbir güvenlik yazması yok (yalnız ekranda)", cagrilar == [] and sorulan == [] and
            y.kaydedilmemis_var(), str(cagrilar))
    y.uygula()
    adlar = [c[0] for c in cagrilar]
    kontrol("Uygula: yasak listesi panelin imzalı kaydından (liste_koruma.panel_kaydet)",
            ("panel_kaydet", ("yasak", y.yasak.toPlainText())) in cagrilar and
            re.escape("org.ornek.Uygulama") in guvenlik._kullanici_yasaklari(), str(cagrilar))
    kontrol("Uygula: onay soruları panelin kaydından (panel_kapsam_kaydet) + kip geçerli",
            "panel_kapsam_kaydet" in adlar and AY.al("guvenlik", "onaylar") == "kart")
    kontrol("Uygula: hesap açarken onay diyaloğu sorar; Hayır → açılmaz, imzalı kimlik yazılmaz, görünür ileti",
            sorulan == ["google"] and "panel_kimlik_kaydet" not in adlar and not y.k_hesap["google"].isChecked() and
            "izin vermediniz" in y.durum_metni(), f"{sorulan} {adlar} {y.durum_metni()}")
    cagrilar.clear()
    y.hesap_onay_sor = lambda sag: sorulan.append(sag) or True  # Evet
    y.k_hesap["google"].setChecked(True)
    y.uygula()
    kontrol("Evet → imzalı kimlik kaydı (panel_kimlik_kaydet) Uygula'da",
            [c[0] for c in cagrilar] == ["panel_kimlik_kaydet"] and "google" in cagrilar[0][1][0], str(cagrilar))
finally:
    for ad, f in asil.items():
        setattr(liste_koruma, ad, f)
    A.onay_kapsami_yaz("hepsi")
y.sifirla()

# ---------------------------------------------------------------- yasak / seviye görsel düzenleyici
liste_adlari = [y.yasak_liste.item(i).text() for i in range(y.yasak_liste.count())]
kontrol("yasak listesi uygulama adını gösterir (kaçış karakteri / regex yok)",
        "org.ornek.Uygulama" in liste_adlari and not any("\\" in a for a in liste_adlari), str(liste_adlari))
kontrol("liste kipinde ham metin gizli (metin kipi ileri düzey, kapalı)",
        y.yasak.isHidden() and not y.k_yasak_metin.isChecked())
y.uygulama_ekle("seviye", ("KeePassXC", re.escape("org.keepassxc.KeePassXC")))
t = y.seviye_tablo
son = t.rowCount() - 1
kutu = t.cellWidget(son, 1)
kontrol("seviye: eklenen uygulama 'Yalnız göster' ile; seçenekler Yalnız göster / Yalnız fare / Tam",
        t.item(son, 0).text() == "org.keepassxc.KeePassXC" and kutu.currentText() == "Yalnız göster" and
        [kutu.itemText(i) for i in range(kutu.count())] == ["Yalnız göster", "Yalnız fare", "Tam"])
kutu.setCurrentIndex(1)
kutu.activated.emit(1)
kontrol("seviye kutusu metni günceller (dosya biçimi değişmez)",
        "org\\.keepassxc\\.KeePassXC = tikla" in y.seviye.toPlainText(), y.seviye.toPlainText()[-120:])
kontrol("seviye Uygula ile kaydedilir ve kural geçerli", y.uygula() and
        any(lvl == 1 for _d, lvl in guvenlik.seviye_kurallari()), str(guvenlik.seviye_kurallari()))
y.seviye_tablo.setCurrentCell(y.seviye_tablo.rowCount() - 1, 0)
kontrol("Kaldır → satır silinir (Uygula bekler)", y.secili_kaldir("seviye") and
        "org\\.keepassxc" not in y.seviye.toPlainText() and y.kaydedilmemis_var())
y.sifirla()

# açık pencerelerden seçim (var olan pencere listeleme API'si; yasak pencere listede yok)
from deskhand import api  # noqa: E402

asil_pencereler = api.pencereler
api.pencereler = lambda desen=None: [
    {"id": "1", "title": "Belge — Kate", "class": "org.kde.kate", "forbidden": False},
    {"id": "2", "title": "Başka belge", "class": "org.kde.kate", "forbidden": False},
    {"id": "3", "title": "(yasak pencere)", "class": "", "forbidden": True},
    {"id": "4", "title": "Hesap Makinesi", "class": "", "forbidden": False}]
try:
    secenek = S.acik_pencereler()
finally:
    api.pencereler = asil_pencereler
kontrol("açık pencereler: tekrar yok, yasak pencere yok, sınıfsızda başlık deseni",
        [d for _a, d in secenek] == ["^Hesap\\ Makinesi$", "org\\.kde\\.kate"] and
        S.desen_adi("^Hesap\\ Makinesi$") == "Hesap Makinesi", str(secenek))
y.pencere_f = lambda: []
kontrol("açık pencere yoksa görünür ileti, liste değişmez", not y.uygulama_ekle("yasak") and
        "açık pencere yok" in y.l_yasak.text(), y.l_yasak.text())

# jargon: liste kipinde görünen metinlerde regex/DESEN yok
y.bolumler.setCurrentIndex(1)
y.resize(900, 2400)
y.show()
app.processEvents()
gorunen = " ".join(e.text() for e in y.findChildren(QLabel) if e.isVisible())
kontrol("görünen açıklamalarda 'regex' / 'DESEN' / 'goruntule' yok", not re.search(r"regex|DESEN|goruntule", gorunen),
        gorunen[:200])
y.hide()

# ---------------------------------------------------------------- çıkış sorusu (üst sekmeden ayrılırken)
tw = QTabWidget()
z = yeni()
tw.addTab(z, "Ayarlar")
tw.addTab(QWidget(), "Başka")
tw.show()
app.processEvents()
for cevap, beklenen_sekme in (("iptal", 0), ("at", 1)):
    tw.setCurrentIndex(0)
    app.processEvents()
    sorulanlar = []
    z.cikis_sorusu = lambda c=cevap, s=sorulanlar: s.append(c) or c
    z.s_sure.setValue(z.s_sure.value() + 1)
    tw.setCurrentIndex(1)
    app.processEvents()
    kontrol(f"ayrılırken soru: {cevap} → sekme {beklenen_sekme}", sorulanlar == [cevap] and
            tw.currentIndex() == beklenen_sekme and z.kaydedilmemis_var() == (cevap == "iptal"),
            f"{sorulanlar} {tw.currentIndex()}")
tw.setCurrentIndex(0)
z.cikis_sorusu = lambda: "uygula"
z.s_sure.setValue(57)
tw.setCurrentIndex(1)
app.processEvents()
kontrol("ayrılırken soru: Uygula → kaydedilir, geçilir", tw.currentIndex() == 1 and AY.al("karar", "sor_sure") == 57)
z.cikis_sorusu = lambda: (_ for _ in ()).throw(AssertionError("sorulmamalıydı"))
tw.setCurrentIndex(0)
tw.setCurrentIndex(1)
kontrol("bekleyen değişiklik yoksa sorulmaz", tw.currentIndex() == 1)
tw.hide()

# ---------------------------------------------------------------- kapat-aç: kayıtlı değer görünür
y.uygulama_ekle("yasak", ("Oyun", re.escape("Ornek Oyun")))
y.k_tus.setKeySequence(__import__("PyQt6.QtGui", fromlist=["QKeySequence"]).QKeySequence("Meta+F9"))
y.uygula()
y2 = yeni()
kontrol("kapat-aç: yeni sekme kayıtlı değerleri gösterir (süre, yasak listesi, kısayol)",
        y2.s_sure.value() == 57 and "Ornek Oyun" in [y2.yasak_liste.item(i).text() for i in range(y2.yasak_liste.count())]
        and y2.tus() == "Meta+F9" and not y2.kaydedilmemis_var())

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
