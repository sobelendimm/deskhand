"""UX-L: kalan küçük UX bulguları — bozuk regex iletisi iki katman (O5/O-A), Arka plan modül/kısayol hatası iki katman
(ENT-UX-F), Onaylar › Geçmiş'te karar tek sütunda, Etkinlik "Ayrıntı" panel dilinde (D-A), Sağlık "Denetleniyor…"
ve kısa doctor ayrıntısı + Kopyala (D-B, D-C).
Qt GÖRÜNMEZ (offscreen); dosyalar geçici CONFIG'e (tests/_yalitim); gerçek ~/.config/deskhand ve cüzdan kullanılmaz.

Çalıştır:  python3 tests/test_ux_l.py"""
import os
import re
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"

from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from deskhand import i18n, yollar  # noqa: E402
from deskhand.gui import ayar as A  # noqa: E402
from deskhand.gui import metinler as T  # noqa: E402
from deskhand.gui.gunluk_okur import ayristir  # noqa: E402
from deskhand.gui.sekmeler.arka_plan import ArkaPlanSekmesi  # noqa: E402
from deskhand.gui.sekmeler.ayarlar import AyarlarSekmesi  # noqa: E402
from deskhand.gui.sekmeler.etkinlik import EtkinlikModel  # noqa: E402
from deskhand.gui.sekmeler.onaylar import OnaylarSekmesi  # noqa: E402
from deskhand.gui.sekmeler.saglik import KISA_SINIR, SaglikSekmesi  # noqa: E402
from deskhand.i18n import _  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
gecen = toplam = 0
HAM_REGEX = re.compile(r"unterminated|position \d|missing \)|bad escape|nothing to repeat")
HAM = re.compile(r"Errno|No module named|Error\b|Exception|Traceback")
KOORDINAT = re.compile(r"\(\d+,\s*\d+\)|\b(click|tikla|left|sol)\b")


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dil(kod):
    """Etkin dili değiştir (panelin dil değişimi gibi: ortam + katalog yeniden okunur)."""
    os.environ["DESKHAND_DIL"] = kod
    i18n.yeniden_yukle()


# ================================================================== (a) bozuk regex: iki katman, TR/EN
y = AyarlarSekmesi(cakisma_f=lambda tus: [])
for ad, alan, kaydet, ileti, metin, no in (
        ("yasak", y.yasak, y.yasak_kaydet, y.l_yasak, "# a\n[bozuk", 2),
        ("seviye", y.seviye, y.seviye_kaydet, y.l_seviye, "# a\n\n(bozuk[ = tikla", 3)):
    alan.setPlainText(metin)
    kontrol(f"(a) {ad}: bozuk regex kaydedilmez", not kaydet())
    ust, ayr = ileti.text(), ileti.ayrinti_metni()
    kontrol(f"(a) {ad}: üstte satır no + 'düzenli ifade hatalı', ham Python iletisi YOK",
            f"{no}. satır" in ust and "düzenli ifade hatalı" in ust and not HAM_REGEX.search(ust), ust)
    kontrol(f"(a) {ad}: ham regex iletisi katlı Ayrıntı'da", bool(HAM_REGEX.search(ayr))
            and ileti.b_ayrinti.isVisibleTo(ileti) and not ileti.l_ayrinti.isVisibleTo(ileti), ayr)
kontrol("(a) biçim hatası (regex değil): Ayrıntı düğmesi yok", A.seviye_dogrula("Defter")[2] == "")
kontrol("(a) doğrulayıcı: geçerli metin None", A.yasak_dogrula("^Kee\n# x") is None
        and A.seviye_dogrula("^Kee = tam") is None)
dil("en")
y.seviye.setPlainText("(bozuk[ = tikla")
y.seviye_kaydet()
kontrol("(a) EN panel: sade İngilizce ileti, ham metin Ayrıntı'da", "regular expression" in y.l_seviye.text()
        and not HAM_REGEX.search(y.l_seviye.text()) and HAM_REGEX.search(y.l_seviye.ayrinti_metni()),
        y.l_seviye.text())
dil("tr")

# ================================================================== (b) kısayol / arka plan modülü: iki katman
y.kisayol_durumu(_(T.Y_KISAYOL_HATA), "org.kde.kglobalaccel: No such interface")
kontrol("(b) kısayol hatası: üst satır sade", "kaydedilemedi" in y.l_kisayol.text()
        and "kglobalaccel" not in y.l_kisayol.text(), y.l_kisayol.text())
kontrol("(b) kısayol hatası: ham metin Ayrıntı'da", "kglobalaccel" in y.l_kisayol.ayrinti_metni())


class SahteArka:
    def goruntu(self):
        return Image.new("RGB", (64, 36), (30, 90, 150))


class SahteMasaustu:
    @staticmethod
    def durum(dogrula=True):
        return None


a = ArkaPlanSekmesi(arka_f=lambda: SahteArka(), masaustu_m=SahteMasaustu, masalar_f=lambda: [])
a.m, a.m_hata = None, ModuleNotFoundError("No module named 'Xlib'")
a.sanal_guncelle(None)
kontrol("(b) arka plan modülü yok: üst satır sade (ham istisna yok)", a.l_durum.text() == _(T.A_YOK)
        and not HAM.search(a.l_durum.text()), a.l_durum.text())
kontrol("(b) arka plan modülü yok: ham istisna ipucunda", "Xlib" in a.l_durum.toolTip()
        and "Xlib" in a.b_baslat.toolTip(), a.l_durum.toolTip())
kontrol("(b) kullanılmayan A_DEVRAL/A_BIRAK kaldırıldı", not hasattr(T, "A_DEVRAL") and not hasattr(T, "A_BIRAK"))

# ================================================================== (b) Onaylar › Geçmiş: karar tek sütunda
o = OnaylarSekmesi()
o.gecmis_ekle([s for s in (ayristir("10:00:01 onay izin | [Belge — Kate] | kapat"),
                           ayristir("10:00:02 onay red | [Belge — Kate] | tikla (856,657) sol")) if s])
for satir, karar in ((1, "izin verildi"), (0, "reddedildi")):
    eylem, durum = o.t_gecmis.item(satir, 1).text(), o.t_gecmis.item(satir, 4).text()
    kontrol(f"(b) Geçmiş: karar yalnız Durum sütununda ({karar})", karar in durum.lower()
            and karar not in eylem.lower() and "onay sorusu" not in eylem.lower(), f"{eylem!r} | {durum!r}")
kontrol("(b) Geçmiş: bilinmeyen komut işlem adıyla", o.t_gecmis.item(1, 1).text() == "Pencereyi kapatma",
        o.t_gecmis.item(1, 1).text())

# ================================================================== (c) Etkinlik "Ayrıntı": panel dilinde, koordinatsız
m = EtkinlikModel()
satirlar = [s for s in (ayristir("10:00:01 tikla (856,657) sol | [Mağaza — Firefox] | ok"),
                        ayristir("10:00:02 tikla (5,5) sol | arka :90 [Belge] | ok"),
                        ayristir("10:00:03 onay izin | [Belge — Kate] | kapat"),
                        ayristir("10:00:04 DUR 12 | tikla x:1 | yasak pencere"),
                        ayristir("10:00:05 PANEL açıldı")) if s]
m.ekle(satirlar)
hucre = [m.data(m.index(i, 3)) for i in range(m.rowCount())]
ipucu = m.data(m.index(0, 3), 3)  # ToolTipRole
kontrol("(c) Ayrıntı: koordinat/komut sözcüğü yok", not any(KOORDINAT.search(h) for h in hucre), str(hucre))
kontrol("(c) Ayrıntı: masaüstü + işlem türü", hucre[0] == "Ekran · tıklama işlemi"
        and hucre[1] == "Arka plan · tıklama işlemi" and hucre[2] == "Ekran · onay sorusu"
        and hucre[3].endswith("durdurma, kod 12") and hucre[4] == "Günlük kaydı", str(hucre))
kontrol("(c) ham satır ipucunda kalır (katlı)", "tikla (856,657) sol" in str(ipucu), str(ipucu))
dil("en")
hucre_en = [m.data(m.index(i, 3)) for i in range(m.rowCount())]
dil("tr")
kontrol("(c) EN panelde Türkçe metin yok", not any(re.search(r"[çğışöüÇĞİŞÖÜ]|tıklama|onay|günlük", h)
                                                  for h in hucre_en) and hucre_en[0] == "Screen · a click",
        str(hucre_en))

# ================================================================== (d) Sağlık: Denetleniyor…, kısa ayrıntı + Kopyala
pano = []
UZUN = ("deskhand-eis yok; C yardımcıları derlenmemiş: /usr/lib/deskhand/eis bulunamadı, make -C c/ ile derleyin ve "
        "yeniden kurun. Ayrıca libei 1.3 gerekir; sürüm 1.2 bulundu.")
s = SaglikSekmesi(denetle=lambda: [], pano=pano.append)
kontrol("(d) D-B: ilk denetim dönmeden 'Denetleniyor…' (Her şey hazır değil)",
        s.l_kart.text() == "Denetleniyor…" and "0/0" not in s.l_ozet.text(), f"{s.l_kart.text()} {s.l_ozet.text()}")
s.goster([])
kontrol("(d) D-B: boş sonuç 'Her şey hazır ✓ 0/0' DEĞİL", s.l_kart.text() != _(T.H_HEPSI_TAMAM)
        and "0/0" not in s.l_ozet.text(), f"{s.l_kart.text()} {s.l_ozet.text()}")
s.goster([{"ad": "C yardımcıları", "tur": "ek", "ok": False, "durum": "eksik", "not": UZUN},
          {"ad": "kdotool", "tur": "arac", "ok": True, "not": "n"}])
sat = s.sorun_satirlari[0]
kontrol("(d) D-C: C yardımcıları satırı kısa özet", len(sat["ne"].text()) <= KISA_SINIR
        and sat["ne"].text().startswith("deskhand-eis yok"), sat["ne"].text())
kontrol("(d) D-C: tam metin ipucunda", sat["ne"].toolTip() == UZUN)
kontrol("(d) D-C: Kopyala tam ayrıntıyı panoya koyar", sat["kopyala"] is not None
        and (sat["kopyala"].click() or pano == [UZUN]), str(pano))
kontrol("(d) tablo Not sütunu da kısa, tamamı ipucunda", len(s.tablo.item(0, 2).text()) <= KISA_SINIR
        and s.tablo.item(0, 2).toolTip() == UZUN)
kontrol("(d) sağlam satır özeti 1/2", "1/2" in s.l_ozet.text(), s.l_ozet.text())

kontrol("gerçek yollar kullanılmadı (geçici CONFIG)", yollar.seviye_dosya().startswith(_yalitim.GECICI))
print(f"\n{gecen}/{toplam} UX-L testi geçti")
sys.exit(0 if gecen == toplam else 1)
