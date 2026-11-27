"""Panelin tek seferlik "otomatik giriş + KDE Cüzdanı" kartı (deskhand/gui/cuzdan_karti.py, plan A2).

Kapsam: ilk / yeniden varyant metinleri; Kaydet'e çift tık → tek oto_kur; hata iletisinde parola yok, alan temizlenir;
"Cüzdanı Deskhand için kullanma" → depo cüzdan ise depo_degistir("kasa") + kapat, kasa ise yalnız kapat; "Bir daha
gösterme" işaret yazar (yazılamazsa kart gizlenir, panel çökmez); "×" işaret yazmaz; disk uyarısı yalnız şifresiz VE
TPM'siz; durum okunamazsa kart gizli; durum okuması panel açılışını bloklamaz; tasarım kapısı (açık/koyu) 0 ihlal;
görsel taban (tests/gorsel_taban/kart/, ayrı süreçte sabit ortam).
Qt GÖRÜNMEZ (offscreen); arka uç SAHTE; işaret dosyası _yalitim'in geçici DESKHAND_STATE_DIR'ünde.

Çalıştır:  python3 tests/test_cuzdan_karti.py
  GORSEL_GUNCELLE=1  kart tabanlarını yeniden yaz · KART_PNG=DIZIN  çekilen kart PNG'lerini oraya da kopyala"""
import json
import os
import shutil
import sys
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
os.environ["XDG_CONFIG_HOME"] = "/nonexistent-deskhand-test"
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"

from PIL import Image  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from deskhand import oto_giris as OG  # noqa: E402
from deskhand import yollar  # noqa: E402
from deskhand.cuzdan_ac import CuzdanHatasi  # noqa: E402
from deskhand.gui import cuzdan_karti as CK  # noqa: E402
from deskhand.gui.dil import Metinler  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
gecen = toplam = 0
PAROLA = "Kart-Parola-31!x"
TESTLER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTLER)
import _gorsel as GR  # noqa: E402


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def bekle(kosul, sure=3.0):
    son = time.monotonic() + sure
    while time.monotonic() < son:
        app.processEvents()
        if kosul():
            return True
        time.sleep(0.01)
    app.processEvents()
    return kosul()


class SahteArkaUc:
    """gizli.ArkaUc'un kartın kullandığı iki işlevi: oto_kur(parola), depo_degistir(tur)."""

    def __init__(self, hata=None, kilit=None):
        self.kur, self.degistir = [], []
        self.hata, self.kilit = hata, kilit

    def oto_kur(self, parola):
        self.kur.append(len(parola))  # değer saklanmaz
        if self.kilit is not None:
            self.kilit.wait(5)
        if self.hata is not None:
            raise self.hata

    def depo_degistir(self, tur):
        self.degistir.append(tur)


def durum(varyant="ilk", disk=True, tpm=False, depo="kasa", kilitli=False):
    return {"goster": True, "varyant": varyant, "neden": "kurulu_degil" if varyant == "ilk" else "anahtar_acmadi",
            "oto_giris": True, "cuzdan_var": True, "kurulu": varyant == "yeniden",
            "son_sonuc": "anahtar_acmadi" if varyant == "yeniden" else None, "disk_sifreli": disk, "tpm": tpm,
            "depo": depo, "cuzdan_kilitli": kilitli}


def soru_cevabi(k, cevap):
    """k.onay_sor → kaydeder, `cevap` döner (gerçek QMessageBox açılmaz)."""
    sorular = []
    k.onay_sor = lambda baslik, metin: (sorular.append((baslik, metin)), cevap)[1]
    return sorular


def isaret_sil():
    try:
        os.unlink(os.path.join(yollar.state_dir(), OG.KAPALI_ISARET))
    except FileNotFoundError:
        pass


def kart(d=None, au=None, **kw):
    isaret_sil()
    k = CK.CuzdanGirisKarti(Metinler(), arka_uc=au if au is not None else SahteArkaUc(),
                            durum_f=kw.pop("durum_f", lambda: d or durum()))
    k.gizle_ms = kw.pop("gizle_ms", 50)
    sinyal = []
    k.bitti.connect(sinyal.append)
    k.resize(900, 400)
    if d is not None:
        k.goster_durum(d)
    k.show() if d is not None and d.get("goster") else None
    app.processEvents()
    return k, sinyal


def gorunur(k):
    return not k.isHidden()


def tum_metin(k):
    from PyQt6.QtWidgets import QAbstractButton, QLabel
    parca = [w.text() for w in k.findChildren(QLabel) + k.findChildren(QAbstractButton)]
    parca += [w.accessibleName() for w in k.findChildren(QLabel) + k.findChildren(QAbstractButton)]
    parca += [w.toolTip() for w in k.findChildren(QLabel) + k.findChildren(QAbstractButton)]
    return "\n".join(parca)


# ---------------------------------------------------------------- metinler

def test_ilk_varyant_metinleri():
    k, _s = kart(durum("ilk"))
    kontrol("objectName cuzdanGirisKarti, görünür", k.objectName() == "cuzdanGirisKarti" and gorunur(k))
    kontrol("ilk: başlık", k.l_baslik.text() == "Girişte KDE Cüzdanı parola soruyor", k.l_baslik.text())
    kontrol("ilk: açıklama", k.l_metin.text().startswith("Bilgisayarınız parolasız açılıyor, bu yüzden KDE Cüzdanı her "
                                                         "girişte parolasını soruyor. Bu soru KDE'den gelir ve yalnız "
                                                         "aşağıdaki ilk seçenekle kalkar."), k.l_metin.text())
    kontrol("ilk: Kaydet düğmesi", k.b_kaydet.text() == "Kaydet, bir daha sorulmasın", k.b_kaydet.text())
    kontrol("ilk: parola alanı Password + erişilebilir ad",
            k.e_parola.echoMode() == QLineEdit.EchoMode.Password and k.e_parola.accessibleName() == "Cüzdan parolası")
    kontrol("ilk: otomatik giriş uyarısı görünür (düğmenin üstünde)",
            gorunur(k.u_oto) and k.u_oto.metin() == "Otomatik giriş açık: bu bilgisayarı açan herkes cüzdandaki "
            "parolalara ulaşır." and k.u_oto.geometry().bottom() < k.b_kaydet.mapTo(k, k.b_kaydet.rect().topLeft()).y(),
            k.u_oto.metin())
    kontrol("ilk: kasa düğmesi + alt not", k.b_kasa.text() == "Cüzdanı Deskhand için kullanma" and
            k.l_kasa_not.text() == "Deskhand parolalarını kendi kasasında tutar; KDE'nin açılış sorusu sürer.",
            f"{k.b_kasa.text()} | {k.l_kasa_not.text()}")
    kontrol("ilk: Bir daha gösterme + × (erişilebilir ad)", k.b_gosterme.text() == "Bir daha gösterme" and
            k.b_carpi.accessibleName() == "Kapat", f"{k.b_gosterme.text()} | {k.b_carpi.accessibleName()}")
    # İngilizce
    from deskhand import i18n
    os.environ["DESKHAND_DIL"] = "en"
    i18n.yeniden_yukle()
    k.tazele()
    kontrol("en: başlık ve düğmeler çevrildi",
            k.l_baslik.text() == "KDE Wallet asks for its password at login" and
            k.b_kaydet.text() == "Save, don't ask again" and k.b_kasa.text() == "Don't use the wallet for Deskhand" and
            k.b_gosterme.text() == "Don't show again", f"{k.l_baslik.text()} | {k.b_kaydet.text()}")
    os.environ["DESKHAND_DIL"] = "tr"
    i18n.yeniden_yukle()
    k.tazele()
    kontrol("tr'ye dönüş", k.l_baslik.text() == "Girişte KDE Cüzdanı parola soruyor")


def test_yeniden_varyant():
    k, _s = kart(durum("yeniden"))
    kontrol("yeniden: başlık", k.l_baslik.text() == "Kaydedilen parola cüzdanı açmadı", k.l_baslik.text())
    kontrol("yeniden: Kaydet ve kasa seçeneği yine var", gorunur(k.b_kaydet) and gorunur(k.b_kasa))
    k.goster_durum(durum("ilk"))
    kontrol("varyant değişince başlık güncellenir", k.l_baslik.text() == "Girişte KDE Cüzdanı parola soruyor")


# ---------------------------------------------------------------- Kaydet

def test_cift_tik_tek_cagri():
    kilit = threading.Event()
    au = SahteArkaUc(kilit=kilit)
    k, sinyal = kart(durum("ilk"), au=au)
    k.e_parola.setText(PAROLA)
    k.b_kaydet.click()
    k.b_kaydet.click()
    k.kaydet()  # iş sürerken doğrudan çağrı da ikinci iş başlatmaz
    app.processEvents()
    kontrol("iş sürerken düğme gri, alan boş", not k.b_kaydet.isEnabled() and k.e_parola.text() == "")
    kilit.set()
    kontrol("iş bitti → 'Kuruldu · sonraki girişte denenecek'",
            bekle(lambda: k.l_durum.text() == "Kuruldu · sonraki girişte denenecek"), k.l_durum.text())
    kontrol("çift tık → TEK oto_kur", au.kur == [len(PAROLA)], au.kur)
    kontrol("bitti('kuruldu')", sinyal == ["kuruldu"], sinyal)
    kontrol("kart bir süre sonra gizlenir", bekle(lambda: not gorunur(k)))
    kontrol("kurulum işaret dosyası yazmaz", OG.kart_kapali() is False)
    k2, _s = kart(durum("ilk"), au=SahteArkaUc())
    k2.b_kaydet.click()
    app.processEvents()
    kontrol("boş parola → oto_kur çağrılmaz, ileti", k2.au.kur == [] and k2.l_durum.text() ==
            "Girişte açmak için cüzdan parolasını yazın.", k2.l_durum.text())


def test_hata_metninde_parola_yok_alan_temiz():
    au = SahteArkaUc(hata=CuzdanHatasi(f"kötü arka uç iletisi {PAROLA}"))
    k, sinyal = kart(durum("ilk"), au=au)
    k.e_parola.setText(PAROLA)
    k.b_kaydet.click()
    kontrol("hata → iş bitti, düğme yeniden etkin", bekle(lambda: k.b_kaydet.isEnabled() and k.l_durum.text()))
    kontrol("hata iletisinde parola yok", PAROLA not in tum_metin(k) and k.l_durum.text(), k.l_durum.text())
    kontrol("hata: alan temiz, kart görünür, sinyal yok", k.e_parola.text() == "" and gorunur(k) and not sinyal)
    au.hata = OSError(13, "izin yok")
    k.e_parola.setText(PAROLA)
    k.b_kaydet.click()
    kontrol("OSError: sade cümle (hata_ozeti)", bekle(lambda: k.b_kaydet.isEnabled()) and
            "Klasör izinlerini" in k.l_durum.text() and PAROLA not in tum_metin(k), k.l_durum.text())


# ---------------------------------------------------------------- kasa seçeneği, kapatma

def test_kasa_secenegi_depo_degistirir_ve_kapatir():
    au = SahteArkaUc()
    k, sinyal = kart(durum("ilk", depo="cuzdan", kilitli=False), au=au)
    sorular = soru_cevabi(k, True)
    k.b_kasa.click()
    kontrol("depo cüzdan + açık → Ayarlar'daki depo sorusu (S_DEPO) bir kez",
            len(sorular) == 1 and sorular[0][0] == "Parola deposu değişsin mi?" and
            sorular[0][1].startswith("Parolalar ve ayar koruma anahtarı Deskhand kasası konumuna taşınacak. "
                                     "KDE Cüzdanı artık kullanılmayacak."), sorular)
    kontrol("Evet → depo_degistir('kasa') bir kez", bekle(lambda: sinyal == ["kasa"]) and
            au.degistir == ["kasa"], f"{au.degistir} {sinyal}")
    kontrol("kasa → işaret yazıldı, kart gizli", OG.kart_kapali() is True and not gorunur(k))
    # Hayır → hiçbir şey değişmez
    au3 = SahteArkaUc()
    k3, s3 = kart(durum("ilk", depo="cuzdan", kilitli=False), au=au3)
    sorular3 = soru_cevabi(k3, False)
    k3.b_kasa.click()
    app.processEvents()
    kontrol("Hayır → depo_degistir yok, işaret yok, kart görünür, sinyal yok",
            len(sorular3) == 1 and au3.degistir == [] and OG.kart_kapali() is False and gorunur(k3) and
            not s3 and k3._is is None and k3.b_kasa.isEnabled(), f"{au3.degistir} {s3}")
    au2 = SahteArkaUc(hata=None)
    def tasinamadi(tur):
        raise RuntimeError("taşınamadı")
    au2.depo_degistir = tasinamadi
    k2, s2 = kart(durum("ilk", depo="cuzdan", kilitli=False), au=au2)
    soru_cevabi(k2, True)
    k2.b_kasa.click()
    kontrol("depo_degistir hatası → kart görünür, ileti, işaret YOK", bekle(lambda: k2.b_kasa.isEnabled() and
            k2.l_durum.text() != "") and gorunur(k2) and OG.kart_kapali() is False and not s2, k2.l_durum.text())


def test_kasa_zaten_secili_yalniz_kapatir():
    for depo in ("kasa", None):
        au = SahteArkaUc()
        k, sinyal = kart(durum("ilk", depo=depo), au=au)
        k.b_kasa.click()
        kontrol(f"depo {depo} → depo_degistir yok, yalnız işaret", bekle(lambda s=sinyal: s == ["kasa"]) and
                au.degistir == [] and OG.kart_kapali() is True and not gorunur(k), f"{au.degistir} {sinyal}")


def test_kasa_cuzdan_kilitli_tasima_denenmez():
    """A3 B2: depo cüzdan ve cüzdan kilitli / durumu bilinmiyor → soru yok, taşıma yok, işaret yok; kart kapanır ve tek
    satır yol gösterir."""
    for kilit in (True, None):
        au = SahteArkaUc()
        k, sinyal = kart(durum("ilk", depo="cuzdan", kilitli=kilit), au=au, gizle_ms=300)
        sorular = soru_cevabi(k, True)
        k.b_kasa.click()
        app.processEvents()
        kontrol(f"kilitli={kilit}: tek satır 'önce cüzdanı açın', seçenekler gizli",
                k.l_durum.text() == "Parolaları kasaya taşımak için önce cüzdanı açın: Ayarlar › Gizli bilgiler." and
                gorunur(k.l_durum) and not gorunur(k.b_kaydet) and not gorunur(k.b_kasa), k.l_durum.text())
        kontrol(f"kilitli={kilit}: soru yok, depo_degistir yok, iş yok", sorular == [] and au.degistir == [] and
                k._is is None, f"{sorular} {au.degistir}")
        kontrol(f"kilitli={kilit}: kart kısa süre sonra gizlenir, işaret YAZILMAZ, bitti('gizlendi')",
                bekle(lambda k=k: not gorunur(k)) and sinyal == ["gizlendi"] and OG.kart_kapali() is False, sinyal)
        k.goster_durum(durum("ilk", depo="cuzdan", kilitli=False))
        kontrol(f"kilitli={kilit}: bu çalışmada yeniden açılmaz", not gorunur(k))
    # en
    from deskhand import i18n
    os.environ["DESKHAND_DIL"] = "en"
    i18n.yeniden_yukle()
    try:
        k, _s = kart(durum("ilk", depo="cuzdan", kilitli=True), gizle_ms=300)
        k.b_kasa.click()
        app.processEvents()
        kontrol("en: kilitli iletisi çevrildi", k.l_durum.text() == "To move the passwords to the vault, unlock the "
                "wallet first: Settings › Secrets.", k.l_durum.text())
    finally:
        os.environ["DESKHAND_DIL"] = "tr"
        i18n.yeniden_yukle()


def test_is_hatasi_iz_tutmaz():
    """A3 B6: istisna yolunda parola referansı kalmaz — GUI'ye gelen istisnanın (ve zincirinin) yığın izi yok."""
    def ic():
        raise ValueError("iç")

    class Patlayan(SahteArkaUc):
        def oto_kur(self, parola):
            yerel = parola  # noqa: F841 - çerçevede parola tutan yerel
            try:
                ic()
            except ValueError as x:
                raise CuzdanHatasi("dış") from x
    k, _s = kart(durum("ilk"), au=Patlayan())
    alinan = []
    k._is_bitti.connect(lambda ad, e: alinan.append(e))
    k.e_parola.setText(PAROLA)
    k.b_kaydet.click()
    kontrol("hata geldi", bekle(lambda: bool(alinan) and k.b_kaydet.isEnabled()), alinan)
    e = alinan[0] if alinan else None
    kontrol("istisnada ve __cause__'da yığın izi yok", e is not None and e.__traceback__ is None and
            e.__cause__ is not None and e.__cause__.__traceback__ is None, repr(e))
    kontrol("alan temiz, iletide parola yok", k.e_parola.text() == "" and PAROLA not in tum_metin(k))


def test_pencere_kart_bitince_gizli_yeniden_okunur():
    """A3 B4: kart 'kuruldu' / 'kasa' → Ayarlar › Gizli bilgiler okunduysa yeniden okunur; bekleyen değişiklik ezilmez;
    okunmadıysa okunmaz; 'kapatildi' / 'gizlendi' okutmaz."""
    from deskhand.gui.pencere import AnaPencere
    from deskhand.gui.sekmeler import gizli as G

    class SahteDepoMod:   # gizli.ArkaUc'un yukle() için kullandığı anahtar_deposu yüzü
        def __init__(self):
            self.tur, self.cagri = "kasa", []

        def secili_depo(self):
            mod = self

            class D:
                def durum(self):
                    mod.cagri.append("durum")
                    return {"tur": mod.tur, "hazir": True, "neden": None, "tpm": False}

                def listele(self):
                    return []
            return D()

        def sir_listesi(self):
            return []

        def yardimci_arac(self, ad, zorunlu=True):
            return None

    class SahteCuzdanMod:  # cuzdan_ac yüzü
        def __init__(self):
            self.kurulu = False

        def durum(self):
            return {"kurulu": self.kurulu, "acik": True, "neden": None}

        def cuzdan_durumu(self):
            return {"var": True, "kilitli": False, "giris_parolasi_olasi": True}

    class SahteArka:
        def goruntu(self):
            return Image.new("RGB", (64, 36), (30, 90, 150))

    class SahteMasaustu:
        @staticmethod
        def durum(dogrula=True):
            return None

    def pencere():
        w = AnaPencere([], arka_f=SahteArka, masaustu_m=SahteMasaustu, kart_durum_f=lambda: {"goster": False})
        depo, cuzdan = SahteDepoMod(), SahteCuzdanMod()
        depo.tur = "cuzdan"
        w.ayarlar.gizli.au = G.ArkaUc(depo=depo, cuzdan=cuzdan)
        return w, w.ayarlar.gizli, depo, cuzdan

    w, g, depo, cuzdan = pencere()
    w.cuzdan_karti.bitti.emit("kasa")
    kontrol("gizli okunmadıysa kart sinyali okutmaz", "durum" not in depo.cagri and not g._okundu, depo.cagri)
    g.yukle()
    kontrol("başta kayıtlı (cuzdan, False)", g.kayitli() == ("cuzdan", False), g.kayitli())
    depo.tur = "kasa"
    for s in ("kapatildi", "gizlendi"):
        w.cuzdan_karti.bitti.emit(s)
    kontrol("kapatildi/gizlendi → yeniden okunmaz", g.kayitli() == ("cuzdan", False), g.kayitli())
    w.cuzdan_karti.bitti.emit("kasa")
    kontrol("kasa → yeniden okundu: (kasa, False), bekleyen değişiklik yok",
            g.kayitli() == ("kasa", False) and g.anlik() == ("kasa", False) and not w.ayarlar.kaydedilmemis_var(),
            f"{g.kayitli()} {g.anlik()}")
    cuzdan.kurulu = True
    w.cuzdan_karti.bitti.emit("kuruldu")
    kontrol("kuruldu → yeniden okundu: oto True", g.kayitli() == ("kasa", True) and g.s_oto.anahtar.isChecked(),
            g.kayitli())
    # bekleyen kullanıcı değişikliği ezilmez: kullanıcı depoyu cüzdana çevirdi (Uygula'ya basmadı); kart kurulum yaptı
    w, g, depo, cuzdan = pencere()
    g.yukle()
    g.s_kasa.anahtar.setChecked(True)   # bekleyen: kasa
    kontrol("bekleyen değişiklik var", g.anlik() == ("kasa", False) and w.ayarlar.kaydedilmemis_var(), g.anlik())
    cuzdan.kurulu = True
    w.cuzdan_karti.bitti.emit("kuruldu")
    kontrol("kuruldu → kayıtlı (cuzdan, True), bekleyen kasa seçimi korunur",
            g.kayitli() == ("cuzdan", True) and g.anlik() == ("kasa", True) and w.ayarlar.kaydedilmemis_var(),
            f"{g.kayitli()} {g.anlik()}")
    # bekleyen 'girişte aç' + yazılmış parola: kart depoyu kasaya çevirdi → işaret ve parola alanı korunur
    w, g, depo, cuzdan = pencere()
    g.yukle()
    g.s_oto.anahtar.setChecked(True)
    g.e_oto.setText(PAROLA)
    depo.tur = "kasa"
    w.cuzdan_karti.bitti.emit("kasa")
    kontrol("kasa → kayıtlı (kasa, False); bekleyen oto True ve yazılmış parola korunur",
            g.kayitli() == ("kasa", False) and g.anlik() == ("kasa", True) and g.e_oto.text() == PAROLA and
            w.ayarlar.kaydedilmemis_var(), f"{g.kayitli()} {g.anlik()}")
    g.e_oto.clear()


def test_bir_daha_gosterme_isaret():
    k, sinyal = kart(durum("ilk"))
    k.b_gosterme.click()
    app.processEvents()
    kontrol("Bir daha gösterme → işaret, gizli, bitti('kapatildi')",
            OG.kart_kapali() is True and not gorunur(k) and sinyal == ["kapatildi"], sinyal)
    # işaret yazılamazsa: kart gizlenir, sade ileti, panel çökmez
    k2, s2 = kart(durum("ilk"))
    eski = CK.oto_giris.kart_kapat

    def patla():
        raise PermissionError(13, "izin yok")
    CK.oto_giris.kart_kapat = patla
    try:
        k2.b_gosterme.click()
        app.processEvents()
        kontrol("işaret yazılamadı → tek satır sade ileti, seçenekler gizli",
                k2.l_durum.text() != "" and "\n" not in k2.l_durum.text() and not gorunur(k2.b_kaydet) and
                OG.kart_kapali() is False, k2.l_durum.text())
        kontrol("işaret yazılamadı → kart kısa süre sonra gizlenir", bekle(lambda: not gorunur(k2)) and
                s2 == ["gizlendi"], s2)
    finally:
        CK.oto_giris.kart_kapat = eski


def test_carpi_isaret_yazmaz():
    k, sinyal = kart(durum("ilk"))
    k.b_carpi.click()
    app.processEvents()
    kontrol("× → gizli, işaret YOK, bitti('gizlendi')", not gorunur(k) and OG.kart_kapali() is False and
            sinyal == ["gizlendi"], sinyal)
    k.goster_durum(durum("ilk"))
    app.processEvents()
    kontrol("× sonrası yeni durum bu çalışmada kartı yeniden açmaz", not gorunur(k))


def test_disk_uyarisi_yalniz_sifresiz_tpmsiz():
    k, _s = kart(durum("ilk", disk=False, tpm=False))
    kontrol("disk şifresiz + TPM yok → disk uyarısı görünür",
            gorunur(k.u_disk) and k.u_disk.metin() == "Disk şifreli değil: diski söken biri de kayıtlı anahtarı "
            "okuyabilir.", k.u_disk.metin())
    for disk, tpm in ((True, False), (False, True), (None, False), (None, True), (True, True)):
        k.goster_durum(durum("ilk", disk=disk, tpm=tpm))
        app.processEvents()
        kontrol(f"disk {disk} tpm {tpm} → disk uyarısı yok", not gorunur(k.u_disk))


def test_durum_hatasinda_kart_gizli():
    def patla():
        raise RuntimeError("busctl")
    for ad, f in (("istisna", patla), ("goster False", lambda: {**durum(), "goster": False}),
                  ("sözlük değil", lambda: None), ("bilinmeyen varyant", lambda: {**durum(), "varyant": "x"})):
        k, sinyal = kart(durum_f=f)
        k.yukle()
        kontrol(f"durum {ad} → kart gizli, hata yok", bekle(lambda k=k: k._okundu, 2) and not gorunur(k) and not sinyal)
    k, _s = kart(durum_f=lambda: durum("yeniden"))
    k.yukle()
    kontrol("durum geldi → kart görünür (yeniden)", bekle(lambda: gorunur(k)) and
            k.l_baslik.text() == "Kaydedilen parola cüzdanı açmadı")


def test_pencere_acilisi_bloklanmaz():
    from deskhand.gui.pencere import AnaPencere

    class SahteArka:
        def goruntu(self):
            return Image.new("RGB", (64, 36), (30, 90, 150))

    class SahteMasaustu:
        @staticmethod
        def durum(dogrula=True):
            return None

    def yavas():
        time.sleep(3)
        return durum("ilk")
    t = time.monotonic()
    w = AnaPencere([], arka_f=SahteArka, masaustu_m=SahteMasaustu, kart_durum_f=yavas)
    sure = time.monotonic() - t
    kontrol("durum okuması 3 sn sürerken AnaPencere kurulumu < 0,5 sn", sure < 0.5, f"{sure:.2f} sn")
    kontrol("kart şeritten sonra, sekmelerden önce; başta gizli",
            w.centralWidget().layout().indexOf(w.cuzdan_karti) == 1 and w.cuzdan_karti.isHidden())
    w.show()
    kontrol("durum gelince pencerede kart görünür", bekle(lambda: not w.cuzdan_karti.isHidden(), 6))
    w.hide()


# ---------------------------------------------------------------- tasarım kapısı + görsel taban

def test_tasarim_kapisi_ve_taban():
    sys.path.insert(0, os.path.join(os.path.dirname(TESTLER), "tools"))
    import tasarim_kapi as K

    from deskhand.gui.tema import tema_uygula, uret
    with open(uret.TOKENS_YOLU, encoding="utf-8") as f:
        ham = json.load(f)
    for tema in ("acik", "koyu"):
        tema_uygula(app, tema)
        esik = K.esikler(ham, app.font().pointSizeF())
        for varyant in ("ilk", "yeniden"):
            k, _s = kart(durum(varyant, disk=False, tpm=False))
            k.resize(GR.KART_GENISLIK, k.heightForWidth(GR.KART_GENISLIK) if k.hasHeightForWidth() else
                     k.sizeHint().height())
            app.processEvents()
            ihlal = K.denetle([k], esik, f"kart-{varyant}")
            ihlal += K.doygunluk_denetle(k.grab().toImage(), esik, f"kart-{varyant}")
            kontrol(f"tasarım kapısı ({tema}, {varyant}): kartta 0 ihlal", not ihlal,
                    "; ".join(f"{i['kural']} {i['sinif']} '{i['metin']}' {i['deger']}" for i in ihlal[:6]))
            k.hide()
    # görsel taban: ayrı süreçte sabit ortam (kullanıcı yazı tipi/teması sızmaz)
    taban = os.path.join(TESTLER, "gorsel_taban", "kart")
    cikti = os.path.join(_yalitim.GECICI, "kart-cekim")
    r = GR.kart_cek(cikti, os.path.join(_yalitim.GECICI, "kart-ev"))
    kontrol("kart çekimi süreci başarılı", r.returncode == 0 and r.stdout.count("CEKILDI") == 4,
            f"rc {r.returncode}: {(r.stdout + r.stderr)[-400:]}")
    guncelle = os.environ.get("GORSEL_GUNCELLE") == "1"
    os.makedirs(taban, exist_ok=True)
    pngler = sorted(f for f in os.listdir(cikti) if f.endswith(".png")) if os.path.isdir(cikti) else []
    for f in pngler:
        t, y = os.path.join(taban, f), os.path.join(cikti, f)
        if guncelle or not os.path.exists(t):
            shutil.copyfile(y, t)
            print(f"TABAN YAZILDI: {t}", flush=True)
        n = GR.kiyasla(t, y, os.path.join(_yalitim.GECICI, f + ".fark.png"))
        kontrol(f"kart tabanı: {f} birebir", n == 0, f"{'boyut farklı' if n < 0 else f'{n} piksel'}")
        if os.environ.get("KART_PNG"):
            os.makedirs(os.environ["KART_PNG"], exist_ok=True)
            shutil.copyfile(y, os.path.join(os.environ["KART_PNG"], f))
    kontrol("kart tabanı: 4 ekran (ilk/yeniden × açık/koyu)", len(pngler) == 4, str(pngler))


for _t in (test_ilk_varyant_metinleri, test_yeniden_varyant, test_cift_tik_tek_cagri,
           test_hata_metninde_parola_yok_alan_temiz, test_kasa_secenegi_depo_degistirir_ve_kapatir,
           test_kasa_zaten_secili_yalniz_kapatir, test_kasa_cuzdan_kilitli_tasima_denenmez, test_is_hatasi_iz_tutmaz,
           test_pencere_kart_bitince_gizli_yeniden_okunur, test_bir_daha_gosterme_isaret, test_carpi_isaret_yazmaz,
           test_disk_uyarisi_yalniz_sifresiz_tpmsiz, test_durum_hatasinda_kart_gizli, test_pencere_acilisi_bloklanmaz,
           test_tasarim_kapisi_ve_taban):
    print(f"--- {_t.__name__}", flush=True)
    try:
        _t()
    except Exception as e:  # noqa: BLE001 - bir testin istisnası KALDI sayılır, kalanlar koşar
        import traceback
        traceback.print_exc()
        kontrol(f"{_t.__name__}: istisna yok", False, f"{type(e).__name__}: {e}")
isaret_sil()
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
