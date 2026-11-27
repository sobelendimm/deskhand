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

from PyQt6.QtWidgets import QApplication, QLineEdit, QWidget  # noqa: E402

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
        self.hedefler: dict = {}
        self.cagri: list = []
        self.hata = None
        self.araclar = {"kwalletmanager6": "/usr/bin/kwalletmanager6"}

    def secili_depo(self):
        return SahteDepo(self)

    def sir_yaz(self, ad, veri, uygulama=None, site=None):  # anahtar_deposu.sir_yaz (binding inside the value)
        self.cagri.append(("sir_yaz", ad, uygulama, site))
        self.ogeler[ad] = veri
        self.hedefler[ad] = {k: v for k, v in (("uygulama", uygulama), ("site", site)) if v}

    def sir_hedefi_oku(self, ad):
        return dict(self.hedefler.get(ad, {}))

    def sir_listesi(self):  # B1: değersiz liste
        return [{"ad": a, "site": self.hedefler.get(a, {}).get("site"),
                 "uygulama": self.hedefler.get(a, {}).get("uygulama"), "degisim": 1764200000 + i}
                for i, a in enumerate(sorted(self.ogeler))]

    def sir_degistir(self, ad, deger):  # B1: bağ korunur (sahte: hedefler'e dokunmaz)
        self.cagri.append(("sir_degistir", ad))
        self.ogeler[ad] = deger

    def sir_istegi_kapat(self, istek):
        self.cagri.append(("istek_kapat", istek.get("id")))
        return True

    def yardimci_arac(self, ad, zorunlu=True):
        self.cagri.append(("yardimci_arac", ad))
        return self.araclar.get(ad)

    def temiz_ortam(self):
        return {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-home"}

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

    # B1 (yalnız GUI düğmesinden çağrılır)
    var, kilit_sonuc, degistir_sonuc, kilit_bekle = True, False, False, None

    def cuzdan_durumu(self):
        return {"var": self.var, "kilitli": not self.acik, "giris_parolasi_olasi": True}

    def kullanici_kilit_ac(self, zaman_asimi=120):
        self.cagri.append(("kilit_ac", zaman_asimi))
        if self.kilit_bekle is not None:
            self.kilit_bekle.wait(5)
        if self.kilit_sonuc:
            self.acik = True
        return self.kilit_sonuc

    def parola_degistir_baslat(self, wid):
        self.cagri.append(("parola_degistir", type(wid).__name__))
        return self.degistir_sonuc

    def kullanici_ayari_ac(self):
        self.cagri.append("kullanici_ayari")
        return True


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
kontrol("KDE Cüzdanı kartı: 'Kilitli' (uyarı); depo satırı 'Kullanılmıyor'",
        s.gizli.k_cuzdan.rozet.metin() == _(G.D_KILITLI) and s.gizli.k_cuzdan.rozet.tur() == "uyari"
        and s.gizli.s_cuzdan.rozet.metin() == _(G.D_KULLANILMIYOR))
kontrol("girişte aç: 'Kapalı', anahtar kapalı, parola alanı gizli",
        s.gizli.s_oto.rozet.metin() == _(G.D_OTO_KAPALI) and not s.gizli.s_oto.anahtar.isChecked()
        and not s.gizli.e_oto.isVisible())
kontrol("kayıtlı parolalar yalnız adla listelenir (sıralı)",
        s.gizli.adlar() == ["eposta", "github"])
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

# mühürlü seçim ≠ ayar (anahtar_deposu.SecimsizDepo): neden görünür, kullanıcı depoyu yeniden seçebilir
d4 = SahteDepoMod()
d4.tur, d4.hazir, d4.neden = "dogrulanamadi", False, "seçim uyuşmuyor"
s4, _d, _c = kur(depo=d4, sor=[True])
s4.gizli.yukle()
kontrol("seçim doğrulanamadı: 'Kullanılamıyor: <neden>', depo anahtarları ETKİN (yeniden seçim)",
        "seçim uyuşmuyor" in s4.gizli.s_kasa.rozet.metin() and s4.gizli.s_kasa.anahtar.isEnabled()
        and not s4.gizli.s_kasa.anahtar.isChecked() and not s4.kaydedilmemis_var())
s4.gizli.s_kasa.anahtar.click()
s4.uygula()
kontrol("seçim doğrulanamadı: kasa seçip Evet → depo_degistir('kasa')", ("depo_degistir", "kasa") in d4.cagri,
        str(d4.cagri))

# =========================================================================== 4) depo değişimi: Hayır → geri döner
s, d, c = kur(sor=[False])
s.gizli.yukle()
s.gizli.s_kasa.anahtar.click()
kontrol("kasa kapatılınca cüzdan açılır (tek seçim)",
        not s.gizli.s_kasa.anahtar.isChecked() and s.gizli.s_cuzdan.anahtar.isChecked())
kontrol("bekleyen değişiklik göstergesi", "gizli" in s.degisenler() and s.durum_metni() == DEGISIKLIK,
        str(s.degisenler()))
kontrol("cüzdan kilitli: Cüzdanı aç etkin", s.gizli.b_cuzdan_ac.isEnabled())
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
kontrol("Evet: alan temizlendi; cüzdan bu oturumda kilitli → dürüst rozet 'sonraki girişte yeniden denenecek' (uyarı)",
        s.gizli.e_oto.text() == "" and s.gizli.s_oto.rozet.metin() == _(G.D_OTO_ERKEN)
        and s.gizli.s_oto.rozet.tur() == "uyari" and not s.kaydedilmemis_var())
c.acik = None
s.gizli.yukle()
kontrol("girişte aç kurulu, cüzdan henüz çalışmıyor → 'Kuruldu · sonraki girişte denenecek'",
        s.gizli.s_oto.rozet.metin() == _(G.D_OTO_SONRAKI))
c.acik = True
s.gizli.yukle()
kontrol("girişte aç kurulu + cüzdan açık → 'Açık · …' (başarı)",
        s.gizli.s_oto.rozet.metin() == _(G.D_OTO_ACIK) and s.gizli.s_oto.rozet.tur() == "basari")
c.acik = False
s.gizli.yukle()
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
dlg.e_site.setText("ornekbanka.com.tr")
s.gizli.ekle_diyalogu = lambda **k: dlg
adlar_ = s.gizli.adlar
kontrol("Ekle: sir_yaz(ad, bayt, uygulama, site) çağrılır (Depo.yaz DEĞİL), liste tazelenir",
        s.gizli.parola_ekle() and d.ogeler.get("banka") == GIZLI_DEGER.encode() and "banka" in adlar_()
        and ("sir_yaz", "banka", None, "ornekbanka.com.tr") in d.cagri
        and not any(isinstance(x, tuple) and x[0] == "yaz" for x in d.cagri), str(d.cagri))
metin_ = [s.gizli.satir_metni(i) for i in range(s.gizli.tablo.rowCount())]
kontrol("Tablo: Ad · Site/Uygulama · Son değişim; bağlı site görünür, değer görünmez",
        any(m.startswith("banka | ornekbanka.com.tr | ") for m in metin_)
        and any(m.startswith("github | " + _(G.G_HEDEF_YOK)) for m in metin_)
        and not any(GIZLI_DEGER in m for m in metin_), str(metin_))
kontrol("Ekle: diyaloğun parola alanları temizlendi", dlg.e_p1.text() == "" and dlg.e_p2.text() == "")
ad0 = s.gizli.adlar()[0]
s.gizli.sec(ad0)
kontrol("Sil: Hayır → silinmez", not s.gizli.secili_sil() and ad0 in d.ogeler)
kontrol("Sil: Evet → silinir", s.gizli.secili_sil() and ad0 not in d.ogeler)

# =========================================================================== 8) parola hiçbir yerde görünmez
butun = metinler(s) + metinler(s.gizli) + s.durum_metni()
kontrol("parola değeri ekranda yok (etiket/ipucu/erişilebilir ad)",
        GIZLI_DEGER not in butun and CUZDAN_PAROLA not in butun)
kontrol("parola değeri günlükte yok", GIZLI_DEGER not in gunluk.getvalue()
        and CUZDAN_PAROLA not in gunluk.getvalue())
kontrol("tablo satırları yalnız ad/bağ/tarih (değer gösterilmez)",
        all(a in d.ogeler for a in s.gizli.adlar())
        and not any(GIZLI_DEGER in s.gizli.satir_metni(i) for i in range(s.gizli.tablo.rowCount())))

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

# =========================================================================== 9b) G1: KDE Cüzdanı kartı (sahte B1)
import tempfile  # noqa: E402
import threading  # noqa: E402
import time as _time  # noqa: E402


def bekle(gz, ad, sn=5.0):
    son = _time.monotonic() + sn
    while ad in gz._isler and _time.monotonic() < son:
        app.processEvents()
        _time.sleep(0.01)
    app.processEvents()
    return ad not in gz._isler


s, d, c = kur()
s.gizli.yukle()
kontrol("yükleme cüzdanı AÇMAZ (kilit_ac / parola_degistir çağrılmaz)",
        not any(isinstance(x, tuple) and x[0] in ("kilit_ac", "parola_degistir") for x in c.cagri), str(c.cagri))
kontrol("kart düğmeleri: Cüzdanı aç · Cüzdan parolasını değiştir · Cüzdan Yöneticisi görünür ve etkin",
        all(b.isEnabled() and not b.isHidden() for b in (s.gizli.b_cuzdan_ac, s.gizli.b_parola_degistir,
                                                          s.gizli.b_yonetici))
        and s.gizli.b_yonetici.text() == _(G.C_YONETICI))
kontrol("ipucu: cüzdan parolası çoğunlukla giriş parolası; 'Parolamı bilmiyorum' bağlantısı var",
        s.gizli.k_cuzdan.l_not.text() == _(G.C_NOT) and s.gizli.b_bilmiyorum.text() == _(G.C_BILMIYORUM))

# iptal (False) → rozet değişmez, tek çağrı (döngü yok)
r0 = s.gizli.k_cuzdan.rozet.metin()
kontrol("Cüzdanı aç: iş arka planda başlar (panel beklemez)", s.gizli.cuzdan_ac() and "kilit" in s.gizli._isler)
kontrol("Cüzdanı aç sürerken düğme gri, ikinci tıklama yeni iş başlatmaz",
        not s.gizli.b_cuzdan_ac.isEnabled() and not s.gizli.cuzdan_ac())
bekle(s.gizli, "kilit")
kontrol("iptal → rozet 'Kilitli' kalır, 'değişmedi' iletisi, kilit_ac TAM BİR kez",
        s.gizli.k_cuzdan.rozet.metin() == r0 == _(G.D_KILITLI) and s.gizli.l_ileti.text() == _(G.C_ACILMADI)
        and sum(1 for x in c.cagri if isinstance(x, tuple) and x[0] == "kilit_ac") == 1, str(c.cagri))
# zaman aşımı → rozet değişmez; geç gelen True yok sayılır
c.kilit_bekle = threading.Event()
c.kilit_sonuc = True
eski = (G.KILIT_SURE_SN, G._PAYLI)
G.KILIT_SURE_SN, G._PAYLI = 0, 0.2
s.gizli.cuzdan_ac()
G.KILIT_SURE_SN, G._PAYLI = eski
son = _time.monotonic() + 3
while "kilit" in s.gizli._isler and _time.monotonic() < son:
    app.processEvents()
    _time.sleep(0.01)
kontrol("zaman aşımı → rozet 'Kilitli', ileti 'değişmedi'",
        s.gizli.k_cuzdan.rozet.metin() == _(G.D_KILITLI) and s.gizli.l_ileti.text() == _(G.C_ACILMADI))
c.kilit_bekle.set()
_time.sleep(0.1)
app.processEvents()
kontrol("zaman aşımından sonra gelen sonuç rozeti değiştirmez",
        s.gizli.k_cuzdan.rozet.metin() == _(G.D_KILITLI))
c.kilit_bekle, c.acik = None, False
s.gizli.yukle()
# başarı → Açık
s.gizli.cuzdan_ac()
bekle(s.gizli, "kilit")
kontrol("Cüzdanı aç başarılı → rozet 'Açık' (başarı), düğme gri (zaten açık)",
        s.gizli.k_cuzdan.rozet.metin() == _(G.D_ACIK) and s.gizli.k_cuzdan.rozet.tur() == "basari"
        and not s.gizli.b_cuzdan_ac.isEnabled() and s.gizli.l_ileti.text() == _(G.C_ACILDI))
# parola değiştir: iptal → değişmedi; wid int
c.degistir_sonuc = False
s.gizli.cuzdan_parola_degistir()
bekle(s.gizli, "degistir")
kontrol("Parolayı değiştir iptal → 'değişmedi', parola_degistir_baslat(int wid) bir kez, rozet aynı",
        s.gizli.l_ileti.text() == _(G.C_DEGISMEDI) and c.cagri.count(("parola_degistir", "int")) == 1
        and s.gizli.k_cuzdan.rozet.metin() == _(G.D_ACIK), str(c.cagri))
c.degistir_sonuc = True
s.gizli.cuzdan_parola_degistir()
bekle(s.gizli, "degistir")
kontrol("Parolayı değiştir tamam → 'değiştirildi'", s.gizli.l_ileti.text() == _(G.C_DEGISTI))
# cüzdan yok
c.var = False
s.gizli.yukle()
kontrol("cüzdan yok → rozet 'Yok', Cüzdanı aç ve Parolayı değiştir gri",
        s.gizli.k_cuzdan.rozet.metin() == _(G.D_YOK) and not s.gizli.b_cuzdan_ac.isEnabled()
        and not s.gizli.b_parola_degistir.isEnabled())


# B1 yoksa (eski arka uç): düğmeler gri, panel çökmez
class EskiCuzdan(SahteCuzdanMod):
    cuzdan_durumu = kullanici_kilit_ac = parola_degistir_baslat = kullanici_ayari_ac = None


class EskiDepo(SahteDepoMod):
    sir_listesi = sir_degistir = yardimci_arac = temiz_ortam = sir_istegi_kapat = None


s5, d5, c5 = kur(depo=EskiDepo(), cuzdan=EskiCuzdan())
s5.gizli.yukle()
kontrol("B1 yok: Cüzdanı aç / Parolayı değiştir / Değiştir gri; liste yine adla",
        not s5.gizli.b_cuzdan_ac.isEnabled() and not s5.gizli.b_parola_degistir.isEnabled()
        and not s5.gizli.b_degistir.isEnabled() and s5.gizli.adlar() == ["eposta", "github"]
        and not s5.gizli.cuzdan_ac())

# =========================================================================== 9c) Cüzdan Yöneticisi: PATH araması yok
sahte_dizin = tempfile.mkdtemp(prefix="dh-g1-path-")
iz = os.path.join(sahte_dizin, "calisti")
for ad in G.YONETICI_ADLARI:
    with open(os.path.join(sahte_dizin, ad), "w") as f:
        f.write(f"#!/bin/sh\ntouch {iz}\n")
    os.chmod(os.path.join(sahte_dizin, ad), 0o755)
eski_path = os.environ["PATH"]
os.environ["PATH"] = sahte_dizin + ":" + eski_path
baslatilan: list = []
try:
    s6, d6, c6 = kur(depo=EskiDepo())   # yardimci_arac yok → arka_ortak.arac (yalnız /usr/bin, /bin)
    s6.gizli._baslat_ayrik = lambda yol, ortam: (baslatilan.append((yol, ortam)), 4242)[1]
    s6.gizli.yukle()
    yol6 = s6.gizli._yonetici_yol
    kontrol("Cüzdan Yöneticisi yolu PATH'teki sahte kopya DEĞİL (güvenli dizin ya da yok)",
            yol6 is None or (os.path.dirname(yol6) in ("/usr/bin", "/bin") and sahte_dizin not in yol6), str(yol6))
    if yol6:
        s6.gizli.yonetici_ac()
        kontrol("başlatma: güvenli yol + temiz ortam (PATH=/usr/bin:/bin, sahte dizin yok)",
                baslatilan and baslatilan[0][0] == yol6 and baslatilan[0][1]["PATH"] == "/usr/bin:/bin"
                and sahte_dizin not in str(baslatilan[0][1]), str(baslatilan))
    else:
        kontrol("kurulu değil: Cüzdan Yöneticisi gri + neden", not s6.gizli.b_yonetici.isEnabled()
                and s6.gizli.k_cuzdan.l_neden.text() == _(G.C_YONETICI_YOK))
    kontrol("PATH'teki sahte kwalletmanager hiç çalışmadı", not os.path.exists(iz))
finally:
    os.environ["PATH"] = eski_path

# yardimci_arac (B1) ile; ikinci tıklama ikinci kopya açmaz
s7, d7, c7 = kur()
baslatilan = []
s7.gizli._baslat_ayrik = lambda yol, ortam: (baslatilan.append(yol), os.getpid())[1]
s7.gizli._yasiyor = lambda pid: pid == os.getpid()
s7.gizli.yukle()
kontrol("yardimci_arac('kwalletmanager6') ile bulunur; düğme etkin",
        ("yardimci_arac", "kwalletmanager6") in d7.cagri and s7.gizli.b_yonetici.isEnabled())
ilk = s7.gizli.yonetici_ac()
ikinci = s7.gizli.yonetici_ac()
kontrol("ikinci tıklama ikinci kopya açmaz ('zaten açık' iletisi)",
        ilk and not ikinci and baslatilan == ["/usr/bin/kwalletmanager6"]
        and s7.gizli.l_ileti.text() == _(G.C_YONETICI_ACIK), str(baslatilan))
d8 = SahteDepoMod()
d8.araclar = {}
s8, _d8, _c8 = kur(depo=d8)
s8.gizli.yukle()
kontrol("kwalletmanager yok → düğme gri + neden 'kwalletmanager paketi'",
        not s8.gizli.b_yonetici.isEnabled() and s8.gizli.k_cuzdan.l_neden.text() == _(G.C_YONETICI_YOK)
        and not s8.gizli.k_cuzdan.l_neden.isHidden())

# =========================================================================== 9d) Parolamı bilmiyorum
s9, d9, c9 = kur(depo=None)
d9.tur = "cuzdan"
s9.gizli.yukle()
s9.gizli._baslat_ayrik = lambda yol, ortam: 4343
bp = s9.gizli.bilmiyorum_ac()
app.processEvents()
butun_b = metinler(bp)
kontrol("Parolamı bilmiyorum: 3 adım + düğmeler (Cüzdanı aç, Kasaya geç, Kullanıcı ayarlarını aç, Cüzdan Yöneticisi)",
        all(_(m) in butun_b for m in (G.B_ADIM1, G.B_ADIM2, G.B_ADIM3, G.B_KASAYA_GEC, G.B_KULLANICI,
                                      G.C_YONETICI, G.B_KURTARILAMAZ)))
kontrol("Parolamı bilmiyorum: sıfırla/sil düğmesi YOK",
        not any(k in butun_b.lower() for k in ("sıfırla", "sil\n", "yeni cüzdan")))
bp.b_kullanici.click()
bekle(s9.gizli, "kullanici")
kontrol("adım 3: kullanici_ayari_ac çağrılır (yalnız tıklamayla)", "kullanici_ayari" in c9.cagri)
bp.b_ac.click()
bekle(s9.gizli, "kilit")
kontrol("adım 1: Cüzdanı aç aynı yol (kilit_ac bir kez; iptal → Kilitli)",
        sum(1 for x in c9.cagri if isinstance(x, tuple) and x[0] == "kilit_ac") == 1
        and s9.gizli.k_cuzdan.rozet.metin() == _(G.D_KILITLI))
bp = s9.gizli.bilmiyorum_ac()
bp.b_kasa.click()
kontrol("adım 2: Kasaya geç → kasa SEÇİLİR (bekleyen), depo_degistir henüz çağrılmaz, Uygula iletisi",
        s9.gizli.s_kasa.anahtar.isChecked() and "gizli" in s9.degisenler()
        and not any(isinstance(x, tuple) and x[0] == "depo_degistir" for x in d9.cagri)
        and s9.gizli.l_ileti.text() == _(G.H_KASA_SECILDI))
bp2 = s9.gizli.bilmiyorum_ac()
kontrol("kasa zaten seçili → Kasaya geç gri", not bp2.b_kasa.isEnabled())
bp2.close()

# =========================================================================== 9e) Değiştir (bağ korunur) ve sir_kaydet isteği
s, d, c = kur()
d.hedefler["github"] = {"site": "github.com"}
s.gizli.yukle()
kontrol("seçim yokken Değiştir/Sil gri", not s.gizli.b_degistir.isEnabled() and not s.gizli.b_sil.isEnabled())
s.gizli.sec("github")
kontrol("seçince Değiştir etkin", s.gizli.b_degistir.isEnabled())
dg = G.DegistirDiyalog("github")
kontrol("Değiştir: yalnız yeni değer + tekrar (ikisi de Password), ad alanı yok",
        [e.echoMode() for e in dg.findChildren(QLineEdit)] == [QLineEdit.EchoMode.Password] * 2)
dg.e_p1.setText(GIZLI_DEGER)
dg.e_p2.setText(GIZLI_DEGER + "y")
kontrol("Değiştir: iki değer farklı → hata", dg.hata() == _(G.E_UYUSMUYOR))
dg.e_p2.setText(GIZLI_DEGER)
s.gizli.degistir_diyalogu = lambda ad: dg
kontrol("Değiştir: sir_degistir(ad, bayt); bağ (github.com) korunur; alanlar temizlenir",
        s.gizli.secili_degistir() and ("sir_degistir", "github") in d.cagri
        and d.ogeler["github"] == GIZLI_DEGER.encode()
        and any(m.startswith("github | github.com") for m in (s.gizli.satir_metni(i)
                                                              for i in range(s.gizli.tablo.rowCount())))
        and dg.e_p1.text() == "" and dg.e_p2.text() == "", str(d.cagri))
kontrol("Değiştir: sir_yaz ÇAĞRILMAZ (bağ yeniden yazılmaz)",
        not any(isinstance(x, tuple) and x[0] == "sir_yaz" for x in d.cagri))

acilan: list = []


def ekle_sahte(ad="", site=""):
    acilan.append((ad, site))
    e = G.EkleDiyalog(s.gizli._liste, ad=ad, site=site)
    e.e_p1.setText(GIZLI_DEGER)
    e.e_p2.setText(GIZLI_DEGER)
    return e if e.hata() == "" else None


s.gizli.ekle_diyalogu = ekle_sahte
istek = {"id": "ab12cd34", "tur": "sir_kaydet", "ad": "penpot", "site": "penpot.example"}
kontrol("sir_kaydet isteği → Ekle formu ad/site ön dolu açılır, kaydedilir, istek kapanır",
        s.gizli.sir_kaydet_istegi(istek) and acilan == [("penpot", "penpot.example")]
        and ("sir_yaz", "penpot", None, "penpot.example") in d.cagri and ("istek_kapat", "ab12cd34") in d.cagri,
        str(d.cagri))
kontrol("sir_kaydet isteği: ileti adı söyler, değer içermez",
        "penpot" in s.gizli.l_ileti.text() or s.gizli.l_ileti.text() == "")
acilan.clear()
kontrol("sir_kaydet: geçersiz ad / başka tür → form açılmaz",
        not s.gizli.sir_kaydet_istegi({"tur": "sir_kaydet", "ad": "../x"})
        and not s.gizli.sir_kaydet_istegi({"tur": "onay", "ad": "x"}) and acilan == [])
s.gizli.ekle_diyalogu = lambda **k: None
kontrol("sir_kaydet: vazgeç → istek kapatılmaz",
        not s.gizli.sir_kaydet_istegi({"id": "ff00ff00", "tur": "sir_kaydet", "ad": "yeni1"})
        and ("istek_kapat", "ff00ff00") not in d.cagri)
butun = metinler(s.gizli) + gunluk.getvalue()
kontrol("G1: parola değeri ekranda/günlükte yok", GIZLI_DEGER not in butun)

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
s.gizli.s_cuzdan.anahtar.click()  # cüzdan seçili + kilitli rozet de denetlensin
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
s.gizli._baslat_ayrik = lambda yol, ortam: None
bp = s.gizli.bilmiyorum_ac()
bp.resize(520, bp.sizeHint().height())
app.processEvents()
ihlal_b = K.denetle([bp], esik, "ayarlar-gizli-bilmiyorum")
resim_b = bp.grab()
ihlal_b += K.doygunluk_denetle(resim_b.toImage(), esik, "ayarlar-gizli-bilmiyorum")
kontrol("tasarım kapısı (koyu): 'Parolamı bilmiyorum' penceresinde 0 ihlal", not ihlal_b,
        "; ".join(f"{i['kural']} {i['sinif']} '{i['metin']}' {i['deger']}" for i in ihlal_b[:6]))
if os.environ.get("GIZLI_EKRAN_BILMIYORUM"):
    resim_b.save(os.environ["GIZLI_EKRAN_BILMIYORUM"])
    print("EKRAN:", os.environ["GIZLI_EKRAN_BILMIYORUM"])
bp.close()

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
