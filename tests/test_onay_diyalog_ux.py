"""Onay diyaloğu UX (UX-C, denetim Y4): sade insan dili, güvenlik bilgisi korunur.

Her eylem türü (ödeme, hassas düğme, tuş, uçbirim komutu, pano, insan doğrulaması devri, sistem istemi, diğer) için
guvenlik.onay_iletisi TR + EN üstte tek cümle "ne olacak" + tek satır risk üretir; ham ayrıntı (eylem dizgisi, PID,
ham ayrıntı) yalnız katlanır "Ayrıntılar" alanında ve o alan varsayılan kapalı; geri sayım Reddet düğmesinin
metninde; zaman aşımı → red; varsayılan odak/düğme Reddet; izin düğmesinin güvenlik beklemesi görünür;
gizli yazı / pencere başlığındaki önizleme ve yasak pencere başlığı diyalog metninin HİÇBİR yerinde yok (ayrıntı dahil);
"Not" metni normal renkte, kontrast ≥ tokens.json kontrast_min (açık + koyu tema).

Qt GÖRÜNMEZ (offscreen), geçici HOME/XDG (_yalitim). Çalıştır:  python3 tests/test_onay_diyalog_ux.py"""
import os
import re
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_NO_GLIB", "1")
import _yalitim  # noqa: E402,F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

os.environ["DESKHAND_DIL"] = "tr"

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QPalette  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget  # noqa: E402

from deskhand import guvenlik, i18n, onay  # noqa: E402
from deskhand.gui import tema  # noqa: E402
from deskhand.gui.tema import uret  # noqa: E402

app = QApplication([])
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


def dil(kod):
    i18n.sifirla(kod, i18n.katalog_oku(kod))


_ = i18n._
S = 1_900_000_000.0
TR_HARF = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


def istek(ad, **ek):
    d = {"id": ad * 32 if len(ad) == 1 else ad, "eylem": "", "hedef": "Pencere", "ayrinti": "", "masaustu": "ekran",
         "masa": "", "zaman": S, "son_zaman": S + 118, "pid": 4242, "tur": ""}
    d.update(ek)
    return d


def ornekler():
    """Her tür için guvenlik'in GERÇEK şablonlarıyla (istekçi dilinde) üretilmiş istekler."""
    return {
        "odeme": istek("a", konu="odeme", eylem=_("Düğmeye tıkla: “{dugme}”").format(dugme="Öde"), hedef="Trendyol — Sepetim — Firefox",
                       masaustu="arka", ayrinti=_("Ödeme/yetki/hesap silme gibi hassas bir düğme") + "\n" +
                       _("{x},{y} noktasındaki yazı: {yazi}").format(x=300, y=200, yazi="Öde | Siparişi tamamla")),
        "odeme_sayfa": istek("b", konu="odeme", eylem=_("Hassas sayfada {eylem}").format(eylem=_("Enter/boşluk")),
                             hedef="Ödeme — Firefox",
                             ayrinti=_("Sayfa başlığı ödeme/onay sayfası gibi: {eslesen}").format(eslesen="'odeme'")),
        "kart": istek("c", konu="odeme", eylem=_("Kart bilgisi yaz"), hedef="Kart — Firefox",
                      ayrinti=_("kart numarası: **** {son4}").format(son4="4242")),
        "dugme": istek("d", konu="dugme", eylem=_("Düğmeye tıkla: “{dugme}”").format(dugme="Hesabı sil"), hedef="Ayarlar — Firefox",
                       ayrinti=_("Ödeme/yetki/hesap silme gibi hassas bir düğme")),
        "tus": istek("e", konu="tus", eylem=_("Riskli tuş: {kombinasyon}").format(kombinasyon="ctrl+w"), hedef="Belge — KWrite",
                     ayrinti="pencere kapatma kısayolu\n" + _("tuş: {kombinasyon}").format(kombinasyon="ctrl+w")),
        "ucbirim": istek("f", konu="ucbirim", eylem=_("Uçbirime komut yaz: {komut}").format(komut=repr("rm -rf ~/x")),
                         hedef="~ : zsh — Konsole", ayrinti="rm -r\nuçbirim: konsole"),
        "ucbirim_baslat": istek("g", konu="ucbirim", eylem=_("Komut başlat: {komut}").format(komut=repr("sudo rm -rf /x")),
                                hedef=_("uygulama başlatma"), ayrinti="sudo"),
        "pano": istek("h", konu="pano", eylem=_("Panoyu yapıştır"), hedef="Belge — KWrite",
                      ayrinti=_("Ajan kullanıcının panosundaki metni ({n} karakter) bu pencereye yapıştırmak istiyor "
                                "({ne}).").format(n=12, ne=_("panodan yapıştırma"))),
        "pano_mcp": istek("i", konu="pano", eylem="clipboard", hedef=_("kullanıcının panosu"),
                          ayrinti=_("Ajan panonun metnini okumak istiyor ({n} karakter)").format(n=12)),
        "devir": istek("j", tur=onay.TUR_DEVIR, eylem="human_verification", hedef="Giriş — Firefox", masaustu="arka",
                       ayrinti="CAPTCHA"),
        "sistem": istek("k", konu="sistem", eylem=_("Sistem istemine girdi: {ad}").format(ad="polkit"), hedef="Kimlik doğrulama",
                        ayrinti="polkit"),
        "diger": istek("l", konu="diger", eylem="run_flow", hedef="Firefox", ayrinti="akış 'x' önceden onaylı adımlar içeriyor"),
    }


BEKLENEN_TUR = {"odeme": "odeme", "odeme_sayfa": "odeme", "kart": "odeme", "dugme": "dugme", "tus": "tus",
                "ucbirim": "ucbirim", "ucbirim_baslat": "ucbirim", "pano": "pano", "pano_mcp": "pano",
                "devir": "devir", "sistem": "sistem", "diger": "diger"}

# ================================================================ 1. ileti şablonu: tür × dil
print("1) guvenlik.onay_iletisi: tür, tek cümle + tek satır risk, TR + EN")
dil("tr")
tr_istekler = ornekler()
tr = {ad: guvenlik.onay_iletisi(i) for ad, i in tr_istekler.items()}
for ad, ileti in tr.items():
    kontrol(f"TR {ad}: tür = {BEKLENEN_TUR[ad]}", ileti["tur"] == BEKLENEN_TUR[ad], ileti["tur"])
    kontrol(f"TR {ad}: başlık tek satır, 'Claude' ile, ham eylem/PID yok",
            ileti["baslik"] and "\n" not in ileti["baslik"] and "Claude" in ileti["baslik"]
            and "PID" not in ileti["baslik"] and tr_istekler[ad]["eylem"] not in ileti["baslik"], ileti["baslik"])
    kontrol(f"TR {ad}: risk tek satır", ileti["risk"] and "\n" not in ileti["risk"], ileti["risk"])
    kontrol(f"TR {ad}: ham eylem + PID ayrıntıda", tr_istekler[ad]["eylem"] in ileti["ayrinti"]
            and "4242" in ileti["ayrinti"], ileti["ayrinti"][:200])
kontrol("ödeme: düğme adı ayrı içerik satırında, tırnak içinde", tr["odeme"]["icerik"] == _("Düğme") + ": “Öde”",
        tr["odeme"]["icerik"])
kontrol("başlık cümlesi sabit (veri taşımaz)", "Öde" not in tr["odeme"]["baslik"].replace("Ödeme", "").replace("ödeme", ""),
        tr["odeme"]["baslik"])
kontrol("ödeme riski para der", "para" in tr["odeme"]["risk"].lower(), tr["odeme"]["risk"])
kontrol("tuş: içerik satırı kısayolu söyler", tr["tus"]["icerik"] == _("Tuş") + ": ctrl+w", tr["tus"]["icerik"])
kontrol("uçbirim: içerik satırı komutu söyler", "rm -rf ~/x" in tr["ucbirim"]["icerik"]
        and tr["ucbirim"]["icerik"].startswith(_("Komut") + ": "), tr["ucbirim"]["icerik"])
kontrol("isteyen satırı PID taşır", "PID 4242" in tr["odeme"]["isteyen"], tr["odeme"]["isteyen"])
kontrol("tür başına ayrı risk satırı (ödeme ≠ tuş ≠ uçbirim ≠ pano ≠ devir)",
        len({tr[a]["risk"] for a in ("odeme", "tus", "ucbirim", "pano", "devir", "diger")}) == 6)

dil("en")
en = {ad: guvenlik.onay_iletisi(i) for ad, i in tr_istekler.items()}  # istekçi TR, panel EN
en_istekler = ornekler()  # istekçi EN
en2 = {ad: guvenlik.onay_iletisi(i) for ad, i in en_istekler.items()}
for ad in tr:
    kontrol(f"EN {ad}: tür aynı (TR istek) ve (EN istek)",
            en[ad]["tur"] == BEKLENEN_TUR[ad] == en2[ad]["tur"], f"{en[ad]['tur']} / {en2[ad]['tur']}")
    temiz = en[ad]["baslik"]
    for v in ("Öde", "Hesabı sil", "Ödeme", "Kimlik doğrulama", "Giriş"):
        temiz = temiz.replace(v, "")
    kontrol(f"EN {ad}: başlık + risk İngilizce", en[ad]["baslik"] != tr[ad]["baslik"] and en[ad]["risk"] != tr[ad]["risk"]
            and not TR_HARF.search(en[ad]["risk"]) and not TR_HARF.search(temiz), f"{en[ad]['baslik']} | {en[ad]['risk']}")
dil("tr")

# ================================================================ 2. gizlilik: gizli yazı + başlık önizlemesi + yasak başlık
print("2) gizli yazı ve yasak pencere başlığı diyalogda hiçbir yerde yok")
SIR = "rm -rf ~/Gizli-Parola-Xyz9"
ON_IZLEME = "Başlıksız (Gizli-Parola-Xyz9) — Konsole"
YAKALANAN = []


class SahteAU:
    ad = "kde"

    def aktif(self):
        return "w1"

    def baslik(self, k):
        return ON_IZLEME

    def sinif(self, k):
        return "org.kde.konsole"


eski = (guvenlik.sec, guvenlik.ucbirim_penceresi_mi, guvenlik._panelden_onay, guvenlik.hedef_goruntusu,
        guvenlik.onaysiz_serbest, guvenlik.onayli_gecerli)
guvenlik.sec = lambda: SahteAU()
guvenlik.ucbirim_penceresi_mi = lambda pen: True
guvenlik.hedef_goruntusu = lambda *a, **k: None
guvenlik.onaysiz_serbest = lambda *a, **k: False
guvenlik.onayli_gecerli = lambda o: False
guvenlik._panelden_onay = lambda eylem, hedef, ayrinti, goruntu=None, ajan_eylem=None, konu=None: (
    YAKALANAN.append({"eylem": eylem, "hedef": hedef, "ayrinti": ayrinti, "konu": konu}) or (True, "izin"))
try:
    guvenlik.ucbirim_komut_engel("w1", False, SIR, gizli=True)
finally:
    (guvenlik.sec, guvenlik.ucbirim_penceresi_mi, guvenlik._panelden_onay, guvenlik.hedef_goruntusu,
     guvenlik.onaysiz_serbest, guvenlik.onayli_gecerli) = eski
kontrol("gizli uçbirim komutu onay istedi", len(YAKALANAN) == 1, str(YAKALANAN))
kontrol("üretici türü yapısal alanla bildirir (konu=ucbirim)", YAKALANAN and YAKALANAN[0]["konu"] == "ucbirim",
        str(YAKALANAN))

from deskhand.gui.onay_diyalog import OnayDiyalog  # noqa: E402


def tum_metin(d, pencere_basligi=True) -> str:
    """Diyalogdaki HER metin: etiketler (gizli alanlar dahil), düğmeler, ipuçları, pencere başlığı (diyaloğun kendi
    sabit başlığı onay.ONAY_BASLIK; yerleşik yasak desenle sınarken dışarıda bırakılır)."""
    parca = [d.windowTitle() if pencere_basligi else "", d.toolTip()]
    for w in d.findChildren(QWidget):
        parca.append(w.toolTip())
        if isinstance(w, (QLabel, QAbstractButton)):
            parca.append(w.text())
    return "\n".join(parca)


def gorunen_metin(d) -> str:
    return "\n".join(w.text() for w in d.findChildren(QLabel) if w.isVisible())


def diyalog(i, **k):
    k.setdefault("kurma_ms", 0)
    d = OnayDiyalog(i, yanitla=k.pop("yanitla", lambda a, b: True), istek_var=lambda: True,
                    saat=k.pop("saat", lambda: S), **k)
    d.show()
    app.processEvents()
    return d


if YAKALANAN:
    gi = istek("m", **YAKALANAN[0])
    d = diyalog(gi)
    d.ayrinti_ac(True)
    app.processEvents()
    metin = tum_metin(d)
    kontrol("gizli içerik diyalogda (ayrıntı dahil) YOK", "Gizli-Parola-Xyz9" not in metin and SIR not in metin,
            metin[:400])
    kontrol("gizli pencere başlığı (önizleme) YOK", ON_IZLEME not in metin)
    kontrol("gizli yer tutucu görünür: (gizli yazı: gizlendi)", guvenlik.gizli_yer() in metin, metin[:400])
    d.close()

eski_yasak = guvenlik.yasak_desenler
guvenlik.yasak_desenler = lambda: [*guvenlik.YERLESIK_YASAK, r"Banka Gizli"]
try:
    for hedef in ("Banka Gizli — Firefox", "Deskhand — Onay"):
        d = diyalog(istek("n", eylem=_("Panoyu yapıştır"), hedef=hedef, ayrinti="x"))
        d.ayrinti_ac(True)
        app.processEvents()
        kontrol(f"yasak pencere başlığı ({hedef}) diyalogda YOK", hedef not in tum_metin(d, False),
                tum_metin(d, False)[:300])
        kontrol("yerine sabit '(başlık gizlendi)'", _("(başlık gizlendi)") in tum_metin(d))
        d.close()
finally:
    guvenlik.yasak_desenler = eski_yasak

# ================================================================ 3. diyalog sunumu
print("3) diyalog: başlık + risk üstte, ayrıntı katlı, geri sayım düğmede, zaman aşımı → red, odak Reddet")
for ad, i in tr_istekler.items():
    ileti = tr[ad]
    d = diyalog(i)
    kontrol(f"{ad}: üstte başlık cümlesi + risk satırı", d.l_baslik.text() == ileti["baslik"] and d.l_baslik.isVisible()
            and d.l_risk.text() == ileti["risk"] and d.l_risk.isVisible(), f"{d.l_baslik.text()} | {d.l_risk.text()}")
    kontrol(f"{ad}: Ayrıntılar varsayılan kapalı", not d.w_ayrinti.isVisible() and d.b_ayrinti.isVisible())
    gor = gorunen_metin(d)
    kontrol(f"{ad}: isteyen (PID) üstte görünür, katlı değil", "PID 4242" in gor and d.l_isteyen.isVisible(), gor[:300])
    kontrol(f"{ad}: içerik satırı (varsa) üstte görünür",
            (not ileti["icerik"] and not d.l_icerik.isVisible()) or (d.l_icerik.isVisible()
                                                                     and d.l_icerik.text() == ileti["icerik"]),
            f"{ileti['icerik']!r} | {d.l_icerik.text()!r}")
    kontrol(f"{ad}: ham ayrıntı kapalıyken görünmez",
            (len(i["ayrinti"].splitlines()[0] if i["ayrinti"] else "") < 12
             or i["ayrinti"].splitlines()[0] not in gor), gor[:300])
    d.ayrinti_ac(True)
    app.processEvents()
    kontrol(f"{ad}: açılınca ham eylem + PID görünür", d.w_ayrinti.isVisible() and "4242" in gorunen_metin(d)
            and i["eylem"] in gorunen_metin(d))
    d.close()

d = diyalog(tr_istekler["odeme"])
kontrol("hedef pencere + masaüstü sade adla", "Trendyol — Sepetim — Firefox" in d.l_hedef.text()
        and _("Arka plan (görünmez masaüstü)") in d.l_masaustu.text(), f"{d.l_hedef.text()} | {d.l_masaustu.text()}")
kontrol("ajan metni HTML yorumlanmaz", all(w.textFormat() == Qt.TextFormat.PlainText
                                           for w in (d.l_baslik, d.l_hedef, d.l_ayrinti)))
kontrol("not etiketi devre dışı (soluk) DEĞİL", d.l_not.isEnabled() and d.l_not.objectName() != "muted")
d.close()

saat = [S]
yanitlar, nedenler = [], []
d = diyalog(istek("o", eylem="x", son_zaman=S + 118), saat=lambda: saat[0],
            yanitla=lambda k, karar: yanitlar.append(karar) or True)
d.karar_verildi.connect(lambda i, n: nedenler.append(n))
kontrol("geri sayım Reddet düğmesinde (1:58)", "1:58" in d.b_red.text() and _("Reddet") in d.b_red.text(),
        d.b_red.text())
saat[0] = S + 60
d._tik()
kontrol("geri sayım düğmede ilerler (0:58)", "0:58" in d.b_red.text(), d.b_red.text())
kontrol("varsayılan düğme Reddet, izin odak almaz", d.b_red.isDefault() and not d.b_izin.isDefault()
        and not d.b_izin.autoDefault() and d.b_izin.focusPolicy() == Qt.FocusPolicy.NoFocus)
saat[0] = S + 200
d._tik()
kontrol("zaman dolunca RED (neden 'sure')", yanitlar == ["red"] and nedenler == ["sure"], f"{yanitlar} {nedenler}")

yanitlar.clear()
d = diyalog(istek("p", eylem="x"), kurma_ms=400, yanitla=lambda k, karar: yanitlar.append(karar) or True)
kontrol("güvenlik beklemesi görünür: izin pasif + düğmede bekleme metni",
        not d.b_izin.isEnabled() and d.b_izin.text() != _("Bir kez izin ver") and _("Bir kez izin ver") in d.b_izin.text(),
        d.b_izin.text())
QTest.keyClick(d, Qt.Key.Key_Return)
kontrol("Enter → red", yanitlar == ["red"], str(yanitlar))

dv = diyalog(tr_istekler["devir"])
kontrol("devir: Devral/Bitti/Vazgeç düğmeleri korunur", dv.b_devral is not None and _("Bitti") in dv.b_izin.text())
dv.close()

# ================================================================ 4. not kontrastı (açık + koyu)
print("4) Not metni normal renkte, kontrast ≥ kontrast_min")
esik = uret.yukle()["kontrast_min"]
for kip in ("acik", "koyu"):
    tema.tema_uygula(app, kip)
    d = diyalog(istek("q", eylem="x"))
    on = d.l_not.palette().color(QPalette.ColorGroup.Active, d.l_not.foregroundRole())
    arka = d.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
    oran = uret.kontrast(on, arka)
    kontrol(f"{kip}: not kontrastı {oran:.2f} ≥ {esik}", oran >= esik)
    d.close()

# ================================================================ 5. UX-C-R1: inceleme PoC'leri (K2 YÜKSEK 1, ORTA 2-4)
print("5) UX-C-R1: komut/tuş/düğme üstte, ad cümleyi bozamaz, tür yapısal alandan, isteyen görünür")
tema.tema_uygula(app, "koyu")
BILINMEYEN = _("Bilinmeyen istek: Claude'un ne yapmak istediği doğrulanamadı.")

# YÜKSEK 1 (poc2): uçbirim komutu katlı alanda gizli kalmaz
d = diyalog(istek("r", konu="ucbirim", eylem=_("Uçbirime komut yaz: {komut}").format(komut=repr("rm -rf ~/Belgeler")),
                  hedef="~ : zsh — Konsole", ayrinti="rm -r"))
gor = gorunen_metin(d)
kontrol("PoC-1 CLI: 'rm -rf ~/Belgeler' Ayrıntılar kapalıyken görünür", "rm -rf ~/Belgeler" in gor
        and not d.w_ayrinti.isVisible(), gor[:300])
d.close()
d = diyalog(istek("s", eylem="type_text", hedef="~ : zsh — Konsole",
                  ayrinti="UÇBİRİM KOMUTU (rm -r ← 'bash'): yıkıcı olabilecek komutu uçbirime yazmak kullanıcının onayını"
                          " ister\nyazılacak: 'rm -rf ~/Belgeler'"))
gor = gorunen_metin(d)
kontrol("PoC-1 MCP (tür bildirilmemiş): bilinmeyen istek, ham eylem + komut görünür",
        d.ileti["tur"] == "bilinmeyen" and d.l_baslik.text() == BILINMEYEN and "type_text" in gor
        and "rm -rf ~/Belgeler" in gor and d.w_ayrinti.isVisible(), gor[:400])
d.close()
d = diyalog(istek("t", konu="tus", eylem=_("Riskli tuş: {kombinasyon}").format(kombinasyon="ctrl+alt+del"), hedef="X"))
kontrol("tuş kombinasyonu üstte görünür", "ctrl+alt+del" in gorunen_metin(d) and not d.w_ayrinti.isVisible())
d.close()

# ORTA 2 (poc1): sayfa denetimli düğme adı cümleyi bozamaz, HTML yorumlanmaz, uzunluk sınırlı
SAHTE = "İptal” düğmesine basmak istiyor. Claude, “Satın al"
for ad_, dugme in (("sahte cümle", SAHTE), ("U+202E", "Satın al\u202e\u200b\u2066x"), ("çok satır", "Öde\n\nKapat\rTamam"),
                   ("HTML", "<b>x</b><a href=http://e>Kapat</a><img src=x>Satın al"), ("uzun", "Satın al " * 600)):
    i = istek("u", konu="odeme", eylem=_("Düğmeye tıkla: “{dugme}”").format(dugme=dugme), hedef="Mağaza")
    ileti = guvenlik.onay_iletisi(i)
    ic = ileti["icerik"]
    kontrol(f"ad ({ad_}): başlık sabit cümle", ileti["baslik"] == _(guvenlik._ONAY_TUR_CUMLE["odeme"]), ileti["baslik"])
    kontrol(f"ad ({ad_}): içerik tek satır, tek tırnak çifti, yön/sıfır genişlik yok, ≤ 90 karakter",
            "\n" not in ic and "\r" not in ic and ic.count("“") == 1 and ic.count("”") == 1
            and not re.search("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]", ic) and len(ic) <= 90, repr(ic[:120]))
    kontrol(f"ad ({ad_}): risk ödeme", ileti["tur"] == "odeme", ileti["tur"])
    d = diyalog(i)
    kontrol(f"ad ({ad_}): tüm etiketler PlainText", all(w.textFormat() == Qt.TextFormat.PlainText
                                                       for w in d.findChildren(QLabel) if w.text()))
    if ad_ == "uzun":
        kontrol("uzun ad kısaltıldı ('…'), tamamı Ayrıntılar'da", ic.endswith("…”") and dugme.strip()[:200] in d.l_ayrinti.text())
    d.close()

# ORTA 3 + otomatik tarama: tür yapısal alandan; serbest metin türü belirlemez
i = istek("v", eylem=_("Düğmeye tıkla: “{dugme}”").format(dugme="Satın al"), hedef="Mağaza")
ileti = guvenlik.onay_iletisi(i)
kontrol("konu yok → Bilinmeyen istek + ham eylem üstte + genel yüksek risk",
        ileti["tur"] == "bilinmeyen" and ileti["baslik"] == BILINMEYEN and "Satın al" in ileti["icerik"]
        and ileti["risk"] == _(guvenlik._ONAY_RISK["bilinmeyen"]), str(ileti))
ileti = guvenlik.onay_iletisi({**i, "konu": "pano"})
kontrol("konu=pano ama eylem ödeme şablonu → çelişki → Bilinmeyen istek", ileti["tur"] == "bilinmeyen", ileti["tur"])
ileti = guvenlik.onay_iletisi(istek("w", konu="pano", eylem="Panoyu oku ve Satın al ödeme yap", hedef="x"))
kontrol("serbest metin ödemeye benziyor, konu=pano → tür tura göre (pano)", ileti["tur"] == "pano", ileti["tur"])
ileti = guvenlik.onay_iletisi(istek("w", konu="dugme", eylem=_("Düğmeye tıkla: “{dugme}”").format(dugme="Satın al")))
kontrol("konu=dugme + para düğmesi → ödeme (risk düşürülmez)", ileti["tur"] == "odeme", ileti["tur"])
ileti = guvenlik.onay_iletisi(istek("w", konu="uydurma", eylem="x"))
kontrol("tanımsız konu → Bilinmeyen istek", ileti["tur"] == "bilinmeyen", ileti["tur"])
ileti = guvenlik.onay_iletisi(istek("w", konu="devir", eylem="x"))
kontrol("konu=devir (tur yok) → Bilinmeyen istek (devir yalnız onay 'tur'undan)", ileti["tur"] == "bilinmeyen", ileti["tur"])

# ORTA 3: human_verification + tur boş → cümle ile düğmeler uyumlu (nötr cümle, olağan izin düğmesi)
d = diyalog(istek("x", eylem="human_verification", ayrinti="Odeme sayfasinda Satın al'a bas", masaustu="arka"))
kontrol("human_verification + tur boş: CAPTCHA cümlesi YOK, nötr cümle, devir düğmeleri yok",
        d.ileti["tur"] == "bilinmeyen" and "CAPTCHA" not in d.l_baslik.text() and d.b_devral is None
        and _("Bitti") not in d.b_izin.text() and _("Bir kez izin ver") in d.b_izin.text(), d.l_baslik.text())
d.close()

# ORTA 4: isteyen görünür (süreç adı + PID)
import os as _os  # noqa: E402
with open(f"/proc/{_os.getpid()}/comm", encoding="utf-8") as f:
    KOMUT_AD = f.read().strip()
d = diyalog(istek("y", konu="pano", eylem=_("Panoyu oku"), pid=_os.getpid(), pid_bas=onay._baslangic(_os.getpid())))
kontrol("isteyen: süreç adı + PID üstte", d.l_isteyen.isVisible() and KOMUT_AD in d.l_isteyen.text()
        and d.l_isteyen.text() == f"{KOMUT_AD} (PID {_os.getpid()})", d.l_isteyen.text())
d.close()

d.close()
d = diyalog(istek("y", konu="pano", eylem=_("Panoyu oku"), pid=_os.getpid(), pid_bas="1"))
kontrol("isteyen: başlangıç zamanı uymuyor (PID yeniden kullanımı) → yalnız PID, ad yok",
        d.l_isteyen.text() == f"PID {_os.getpid()}", d.l_isteyen.text())
d.close()

# gizli yazı: içerik satırında da yalnız yer tutucu
SIR2 = "gizli-sir-Q7"
i = istek("z", konu="ucbirim", eylem=_("Uçbirime komut yaz: {komut}").format(komut=f"***({len(SIR2)})"), hedef="vim x.txt",
          ayrinti="x\n" + _("yazılacak: {metin}").format(metin=f"***({len(SIR2)})"))
d = diyalog(i)
d.ayrinti_ac(True)
app.processEvents()
kontrol("gizli: içerik satırı yer tutucu, başlık gizli", guvenlik.gizli_yer() in d.l_icerik.text()
        and "vim x.txt" not in tum_metin(d), d.l_icerik.text())
d.close()

# üretici: konu isteğe yazılır (onay.iste_sonuc 'konu' destekliyse), panel dosyadan okur (sha kapsamında)
yakalanan = {}


class _S:
    ad = "kde"


eski2 = (guvenlik.sec, onay.iste_sonuc)
guvenlik.sec = lambda: _S()


def sahte_iste(eylem, hedef, ayrinti="", masaustu="ekran", sure=0, goruntu=None, gunluge_yaz=True, tur="", konu=""):
    yakalanan.update(eylem=eylem, konu=konu)
    return onay.OnaySonucu(False, "red")


onay.iste_sonuc = sahte_iste
try:
    guvenlik.eylem_basladi()
    guvenlik._panelden_onay(_("Riskli tuş: {kombinasyon}").format(kombinasyon="ctrl+q"), "x", "y", konu="tus")
    kontrol("üretici: _panelden_onay konu'yu isteğe geçirir", yakalanan.get("konu") == "tus", str(yakalanan))
    onay.iste_sonuc = lambda eylem, hedef, ayrinti="", masaustu="ekran", sure=0, goruntu=None: (
        yakalanan.update(eski=True) or onay.OnaySonucu(False, "red"))
    guvenlik._panelden_onay("x", "x", "y", konu="tus")
    kontrol("üretici: konu desteklemeyen iste_sonuc ile de çalışır", yakalanan.get("eski"), str(yakalanan))
finally:
    guvenlik.sec, onay.iste_sonuc = eski2
import json as _json  # noqa: E402
import tempfile as _tf  # noqa: E402
with _tf.TemporaryDirectory() as td:
    kid = "f" * 32
    yol = _os.path.join(td, f"istek-{kid}.json")
    with open(yol, "w", encoding="utf-8") as f:
        _json.dump({"id": kid, "eylem": "Panoyu oku", "hedef": "", "son_zaman": S + 10, "konu": "pano"}, f)
    oku = onay.istek_oku(yol)
    kontrol("panel: istek_oku 'konu' alanını korur (karma kapsamında)", oku and oku.get("konu") == "pano"
            and guvenlik.onay_iletisi(oku)["tur"] == "pano", str(oku)[:200])

print(f"\n{gecen}/{toplam} test geçti")
sys.exit(0 if gecen == toplam else 1)
