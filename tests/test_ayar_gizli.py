"""Ayarlar › Gelişmiş › Gizli bilgiler (anahtar deposu arayüzü, plan P2).

Kapsam: açılışta arka uca gidilmez (grup ilk görününce okunur); durum rozetleri (kasa hazır/TPM, cüzdan açık/kilitli,
girişte aç açık/kapalı, arka uç yok → kullanılamıyor + anahtarlar kapalı); kasa ↔ cüzdan anahtarları birbirini
kapatır; tek kayıt modeli (Uygula/Sıfırla, "Kaydedilmemiş değişiklikler var"); depo değişimi ve girişte otomatik açma
Evet/Hayır sorar (Hayır → geri döner, arka uç çağrılmaz; Evet → depo_degistir / cuzdan_otomatik_kur); parola boşken
geçersiz; parola alanı iş bitince temizlenir, günlükte/ekranda görünmez; kayıtlı parolalar yalnız adla (Ekle/Sil);
arka uç hatası → görünür ileti, panel çökmez; tasarım kapısı (koyu) grupta 0 ihlal.
Qt GÖRÜNMEZ (offscreen); arka uç SAHTE nesne; gerçek kasa/cüzdan/~/.config kullanılmaz (tests/_yalitim).

Çalıştır:  python3 tests/test_ayar_gizli.py      (GIZLI_EKRAN=dosya.png → koyu tema grubu ekran görüntüsü)"""
import io
import logging
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"

from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget  # noqa: E402

from deskhand import liste_koruma  # noqa: E402
from deskhand.gui.sekmeler import ayarlar as S  # noqa: E402
from deskhand.gui.sekmeler import gizli as G  # noqa: E402
from deskhand.i18n import _  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
gecen = toplam = 0
GIZLI_DEGER = "Sır-Parola-9f3!"     # hiçbir metinde/günlükte görünmemeli
CUZDAN_PAROLA = "Cuzdan-Parola-77#"

gunluk = io.StringIO()
_h = logging.StreamHandler(gunluk)
_h.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_h)
logging.getLogger().setLevel(logging.DEBUG)


class SahteKasa:
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


# ---------------------------------------------------------------- sahte arka uç (P1/P3 imzaları)
class SahteDepo:
    def __init__(self, arka):
        self.a = arka

    def durum(self):
        self.a.cagri.append("durum")
        return {"tur": self.a.tur, "hazir": self.a.hazir, "neden": self.a.neden, "tpm": self.a.tpm}

    def listele(self):
        return list(self.a.ogeler)

    def oku(self, ad):
        return self.a.ogeler.get(ad)

    def yaz(self, ad, veri):
        self.a.cagri.append(("yaz", ad))
        self.a.ogeler[ad] = veri

    def sil(self, ad):
        self.a.cagri.append(("sil", ad))
        self.a.ogeler.pop(ad, None)


class SahteDepoMod:
    def __init__(self):
        self.tur, self.hazir, self.neden, self.tpm = "kasa", True, None, True
        self.ogeler = {"github": b"x", "eposta": b"y"}
        self.cagri: list = []
        self.hata = None

    def secili_depo(self):
        return SahteDepo(self)

    def depo_degistir(self, yeni):
        self.cagri.append(("depo_degistir", yeni))
        if self.hata:
            raise self.hata
        self.tur = yeni


class SahteCuzdanMod:
    def __init__(self):
        self.kurulu, self.acik, self.neden = False, False, None
        self.cagri: list = []
        self.parola = None

    def durum(self):
        return {"kurulu": self.kurulu, "acik": self.acik, "neden": self.neden}

    def cuzdan_otomatik_kur(self, parola):
        self.cagri.append("kur")
        self.parola = parola
        self.kurulu = True

    def kaldir(self):
        self.cagri.append("kaldir")
        self.kurulu = False


def kur(depo=None, cuzdan=None, sor=None):
    depo = depo or SahteDepoMod()
    cuzdan = cuzdan or SahteCuzdanMod()
    s = S.AyarlarSekmesi(cakisma_f=lambda tus: [], gizli_arka_uc=G.ArkaUc(depo=depo, cuzdan=cuzdan))
    cevaplar = list(sor or [])
    sorular: list = []
    s.gizli.sorular = sorular  # type: ignore[attr-defined]

    def onay(baslik, metin):
        sorular.append(baslik)
        return cevaplar.pop(0) if cevaplar else False
    s.gizli.onay_sor = onay
    return s, depo, cuzdan


def metinler(w: QWidget) -> str:
    parcalar = []
    for c in [w, *w.findChildren(QWidget)]:
        for ad in ("text", "toolTip", "accessibleName", "placeholderText", "title", "windowTitle"):
            f = getattr(c, ad, None)
            if callable(f):
                try:
                    v = f()
                except TypeError:
                    continue
                if isinstance(v, str):
                    parcalar.append(v)
    return "\n".join(parcalar)


g = G.GizliBilgiler  # kısaltma
DEGISIKLIK = _(S.T.Y_DEGISIKLIK_VAR)

# =========================================================================== 1) açılış: arka uca gidilmez
s, d, c = kur()
kontrol("açılışta arka uç okunmaz (D-Bus/cüzdan yok; grup ilk görününce okunur)", d.cagri == [], str(d.cagri))
kontrol("okunmadan: rozet 'Okunuyor…', anahtarlar kapalı",
        s.gizli.s_kasa.rozet.metin() == _(G.D_OKUNMADI) and not s.gizli.s_kasa.anahtar.isEnabled())
kontrol("okunmadan: kaydedilmemiş değişiklik yok", not s.kaydedilmemis_var(), str(s.degisenler()))
s.bolumler.setCurrentIndex(1)
s.resize(900, 1400)
s.show()
app.processEvents()
kontrol("Gelişmiş görününce arka uç okunur", "durum" in d.cagri, str(d.cagri))
kontrol("okununca kayıtlı taban arka ucun değeri, değişiklik yok", not s.kaydedilmemis_var(), str(s.degisenler()))

# =========================================================================== 2) durum rozetleri
kontrol("kasa: 'Hazır · TPM ile korunuyor' (başarı)",
        s.gizli.s_kasa.rozet.metin() == _(G.D_HAZIR_TPM) and s.gizli.s_kasa.rozet.tur() == "basari")
kontrol("kasa anahtarı açık, cüzdan anahtarı kapalı",
        s.gizli.s_kasa.anahtar.isChecked() and not s.gizli.s_cuzdan.anahtar.isChecked())
kontrol("KDE Cüzdanı: 'Kilitli'", s.gizli.s_cuzdan.rozet.metin() == _(G.D_KILITLI))
kontrol("girişte aç: 'Kapalı', anahtar kapalı, parola alanı gizli",
        s.gizli.s_oto.rozet.metin() == _(G.D_OTO_KAPALI) and not s.gizli.s_oto.anahtar.isChecked()
        and not s.gizli.e_oto.isVisible())
kontrol("kayıtlı parolalar yalnız adla listelenir (sıralı)",
        [s.gizli.liste.item(i).text() for i in range(s.gizli.liste.count())] == ["eposta", "github"])
kontrol("rozetin noktası token rengi (tokens.json durum.basari)",
        G._renkler()["basari"] in s.gizli.s_kasa.rozet.text())
d2 = SahteDepoMod()
d2.tpm = False
s2, _d, _c = kur(depo=d2)
s2.gizli.yukle()
kontrol("kasa TPM yok: 'Hazır · bu bilgisayarın anahtarıyla korunuyor'", s2.gizli.s_kasa.rozet.metin() == _(G.D_HAZIR))
d3 = SahteDepoMod()
d3.hazir, d3.neden = False, "systemd-creds yok"
s3, _d, _c = kur(depo=d3)
s3.gizli.yukle()
kontrol("kasa hazır değil: 'Kullanılamıyor: <neden>' (hata), Ekle kapalı",
        s3.gizli.s_kasa.rozet.metin() == _(G.D_KULLANILAMIYOR).format(neden="systemd-creds yok")
        and s3.gizli.s_kasa.rozet.tur() == "hata" and not s3.gizli.b_ekle.isEnabled())

# =========================================================================== 3) arka uç yok (P1 birleşmeden)
class ArkaUcYok(G.ArkaUc):  # modül import edilemiyormuş gibi (ImportError → _ArkaUcYok)
    def _depo(self):
        raise G._ArkaUcYok("yok")

    _cuzdan = _depo


yok = S.AyarlarSekmesi(cakisma_f=lambda tus: [], gizli_arka_uc=ArkaUcYok())
yok.gizli.yukle()
kontrol("arka uç yok: 'Kullanılamıyor: bu sürümde yok', anahtarlar kapalı, panel çökmez",
        _(G.D_ARKA_UC_YOK) in yok.gizli.s_kasa.rozet.metin() and not yok.gizli.s_kasa.anahtar.isEnabled()
        and not yok.gizli.s_oto.anahtar.isEnabled() and not yok.kaydedilmemis_var())

# =========================================================================== 4) depo değişimi: Hayır → geri döner
s, d, c = kur(sor=[False])
s.gizli.yukle()
s.gizli.s_kasa.anahtar.click()
kontrol("kasa kapatılınca cüzdan açılır (tek seçim)",
        not s.gizli.s_kasa.anahtar.isChecked() and s.gizli.s_cuzdan.anahtar.isChecked())
kontrol("bekleyen değişiklik göstergesi", "gizli" in s.degisenler() and s.durum_metni() == DEGISIKLIK,
        str(s.degisenler()))
kontrol("yönlendirme görünür (cüzdan kilitli, cüzdan seçildi)", s.gizli.w_yon.isVisibleTo(s.gizli))
sonuc = s.uygula()
kontrol("Hayır: soru soruldu, depo_degistir ÇAĞRILMADI",
        s.gizli.sorular == [_(G.S_DEPO_BASLIK)] and not any(isinstance(x, tuple) and x[0] == "depo_degistir"
                                                            for x in d.cagri), str(d.cagri))
kontrol("Hayır: anahtar kasaya geri döner, bekleyen değişiklik yok, Uygula 'reddedildi' iletisi",
        s.gizli.s_kasa.anahtar.isChecked() and not s.gizli.s_cuzdan.anahtar.isChecked()
        and not s.kaydedilmemis_var() and sonuc is False)

# =========================================================================== 5) depo değişimi: Evet → depo_degistir
s, d, c = kur(sor=[True])
s.gizli.yukle()
s.gizli.s_cuzdan.anahtar.click()
s.uygula()
kontrol("Evet: depo_degistir('cuzdan') çağrıldı", ("depo_degistir", "cuzdan") in d.cagri, str(d.cagri))
kontrol("Evet: rozetler yeni durumu gösterir (cüzdan 'Seçili · kilitli', kasa 'Kullanılmıyor')",
        s.gizli.s_cuzdan.rozet.metin() == _(G.D_SECILI_KILITLI)
        and s.gizli.s_kasa.rozet.metin() == _(G.D_KULLANILMIYOR), s.gizli.s_cuzdan.rozet.metin())
kontrol("Evet: kaydedildi, bekleyen yok", not s.kaydedilmemis_var() and s.durum_metni() == _(S.T.Y_KAYDEDILDI_TIK))

# depo değişimi arka uç hatası
s, d, c = kur(sor=[True])
s.gizli.yukle()
d.hata = OSError("disk dolu")
s.gizli.s_cuzdan.anahtar.click()
s.uygula()
kontrol("arka uç hatası: anahtar kayıtlı değere döner, görünür ileti",
        s.gizli.s_kasa.anahtar.isChecked() and s.gizli.l_ileti.isVisibleTo(s.gizli) and s.gizli.l_ileti.text())

# Sıfırla
s, d, c = kur()
s.gizli.yukle()
s.gizli.s_kasa.anahtar.click()
s.sifirla()
kontrol("Sıfırla: anahtar kayıtlı değere döner", s.gizli.s_kasa.anahtar.isChecked() and not s.kaydedilmemis_var())

# =========================================================================== 6) girişte cüzdanı aç
s, d, c = kur(sor=[False])
s.gizli.yukle()
s.gizli.s_oto.anahtar.click()
kontrol("aç: parola alanı görünür (Password kipinde), rozet 'Uygula'ya basınca açılacak'",
        s.gizli.e_oto.isVisibleTo(s.gizli) and s.gizli.e_oto.echoMode() == QLineEdit.EchoMode.Password
        and s.gizli.s_oto.rozet.metin() == _(G.D_OTO_BEKLIYOR))
s.uygula()
kontrol("parola boş: geçersiz, soru sorulmaz, kur çağrılmaz, alan açık kalır",
        s.gizli.sorular == [] and c.cagri == [] and s.gizli.s_oto.anahtar.isChecked()
        and _(G.H_PAROLA_GEREKLI) in s.gizli.l_ileti.text())
s.gizli.e_oto.setText(CUZDAN_PAROLA)
s.uygula()
kontrol("Hayır: kur çağrılmaz, anahtar kapanır, parola alanı temizlenir",
        c.cagri == [] and not s.gizli.s_oto.anahtar.isChecked() and s.gizli.e_oto.text() == ""
        and s.gizli.sorular == [_(G.S_OTO_BASLIK)])

s, d, c = kur(sor=[True])
s.gizli.yukle()
s.gizli.s_oto.anahtar.click()
s.gizli.e_oto.setText(CUZDAN_PAROLA)
s.uygula()
kontrol("Evet: cuzdan_otomatik_kur(parola) çağrıldı (parola aynen)", c.cagri == ["kur"] and c.parola == CUZDAN_PAROLA)
kontrol("Evet: alan temizlendi, rozet 'Açık · …' (başarı), kaydedildi",
        s.gizli.e_oto.text() == "" and s.gizli.s_oto.rozet.metin() == _(G.D_OTO_ACIK)
        and s.gizli.s_oto.rozet.tur() == "basari" and not s.kaydedilmemis_var())
s.gizli.s_oto.anahtar.click()
s.uygula()
kontrol("kapatma (sıkılaştırma): soru sormadan kaldir()", c.cagri == ["kur", "kaldir"] and len(s.gizli.sorular) == 1,
        str(c.cagri))

# =========================================================================== 7) kayıtlı parolalar
s, d, c = kur(sor=[False, True])
s.gizli.yukle()
dlg = G.EkleDiyalog(s.gizli._liste)
dlg.e_ad.setText("github")
dlg.e_p1.setText(GIZLI_DEGER)
dlg.e_p2.setText(GIZLI_DEGER)
kontrol("Ekle: var olan ad reddedilir", dlg.hata() == _(G.E_VAR))
dlg.e_ad.setText("../kaçış")
kontrol("Ekle: geçersiz ad reddedilir (yol/özel karakter)", dlg.hata() == _(G.E_AD_GECERSIZ))
dlg.e_ad.setText("banka")
dlg.e_p2.setText(GIZLI_DEGER + "x")
kontrol("Ekle: iki parola farklı → hata", dlg.hata() == _(G.E_UYUSMUYOR))
dlg.e_p2.setText(GIZLI_DEGER)
kontrol("Ekle: geçerli giriş", dlg.hata() == "")
s.gizli.ekle_diyalogu = lambda: dlg
kontrol("Ekle: yaz(ad, bayt) çağrılır, liste tazelenir", s.gizli.parola_ekle() and d.ogeler.get("banka")
        == GIZLI_DEGER.encode() and "banka" in [s.gizli.liste.item(i).text() for i in range(s.gizli.liste.count())])
kontrol("Ekle: diyaloğun parola alanları temizlendi", dlg.e_p1.text() == "" and dlg.e_p2.text() == "")
s.gizli.liste.setCurrentRow(0)
ad0 = s.gizli.liste.currentItem().text()
kontrol("Sil: Hayır → silinmez", not s.gizli.secili_sil() and ad0 in d.ogeler)
kontrol("Sil: Evet → silinir", s.gizli.secili_sil() and ad0 not in d.ogeler)

# =========================================================================== 8) parola hiçbir yerde görünmez
butun = metinler(s) + metinler(s.gizli) + s.durum_metni()
kontrol("parola değeri ekranda yok (etiket/ipucu/erişilebilir ad)",
        GIZLI_DEGER not in butun and CUZDAN_PAROLA not in butun)
kontrol("parola değeri günlükte yok", GIZLI_DEGER not in gunluk.getvalue()
        and CUZDAN_PAROLA not in gunluk.getvalue())
kontrol("liste öğeleri yalnız ad (değer gösterilmez)",
        all(QLabel is not None and s.gizli.liste.item(i).text() in d.ogeler for i in range(s.gizli.liste.count())))

# =========================================================================== 9) dil: tazele → İngilizce
from deskhand import i18n  # noqa: E402

os.environ["DESKHAND_DIL"] = "en"
i18n.yeniden_yukle()
s.tazele()
kontrol("İngilizce: grup başlığı, rozet ve anahtar adı çevrildi",
        s.gizli.title() != "Gizli bilgiler" and s.gizli.s_kasa.rozet.metin() != "Kullanılmıyor"
        and s.gizli.s_oto.anahtar.accessibleName() != "Girişte KDE Cüzdanı\x27nı aç",
        f"{s.gizli.title()} | {s.gizli.s_kasa.rozet.metin()}")
os.environ["DESKHAND_DIL"] = "tr"
i18n.yeniden_yukle()
s.tazele()

# =========================================================================== 10) tasarım kapısı (koyu)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import json  # noqa: E402

import tasarim_kapi as K  # noqa: E402

from deskhand.gui.tema import tema_uygula, uret  # noqa: E402

tema_uygula(app, "koyu")
s, d, c = kur()
s.bolumler.setCurrentIndex(1)
s.resize(760, 1500)
s.show()
app.processEvents()
s.gizli.s_oto.anahtar.click()   # parola alanı + bekleyen rozet de denetlensin
s.gizli.s_cuzdan.anahtar.click()  # yönlendirme satırı da görünsün
app.processEvents()
with open(uret.TOKENS_YOLU, encoding="utf-8") as f:
    ham = json.load(f)
esik = K.esikler(ham, app.font().pointSizeF())
ihlal = K.denetle([s.gizli], esik, "ayarlar-gizli")
resim = s.gizli.grab()
ihlal += K.doygunluk_denetle(resim.toImage(), esik, "ayarlar-gizli")
kontrol("tasarım kapısı (koyu): Gizli bilgiler grubunda 0 ihlal", not ihlal,
        "; ".join(f"{i['kural']} {i['sinif']} '{i['metin']}' {i['deger']}" for i in ihlal[:6]))
if os.environ.get("GIZLI_EKRAN"):
    resim.save(os.environ["GIZLI_EKRAN"])
    print("EKRAN:", os.environ["GIZLI_EKRAN"])

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
