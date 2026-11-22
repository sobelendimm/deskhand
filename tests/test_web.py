"""deskhand.web testleri: web sayfası ögelerini erişilebilirlik ağacından (AT-SPI) okuma.

GÖRÜNMEZ arka plan masaüstünde (Xvfb) YALITIK Firefox (yeni boş geçici profil; tests/yardimci/web_tarayici.py) yerel
test sayfalarını (tests/ornek/web/, tamamen sentetik; testin açtığı 127.0.0.1 sunucusundan) açar. Denetlenenler:
kapsama (etkileşimli ögelerin ad + rolü), koordinat doğruluğu (bildirilen merkeze GERÇEK tıklama → sayfanın kendi
günlüğü başlıkta doğru ögeyi gösteriyor), durumlar (devre dışı/işaretli/seçili), görünmeyen/gizli ögeler, kaydırma
sonrası güncel koordinat, iframe (aynı + başka köken), sonradan (JS ile 1 sn sonra) eklenen içerik, sekme/menü,
hassas düğme işareti, sayfa bilgisi, oge_bul, süreler (~1.000 ögede ≤ 1,5 sn, ~200 ögede ≤ 0,4 sn) ve sayfanın
otomasyon görmediği (navigator.webdriver false).
Kullanıcının Firefox profil kökü (profiles.ini / installs.ini sha1 + dizin adları) önce/sonra karşılaştırılır; fark
varsa test HEMEN durur (hiçbir şey düzeltilmez). Kullanıcının ekranına girdi gitmez; Firefox yoksa test atlanır.

Çalıştır:  python3 tests/test_web.py"""
import atexit
import os
import shutil
import statistics
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))
import web_tarayici as wt  # noqa: E402

if not (shutil.which("firefox") and shutil.which("Xvfb")):
    print("atlandı: firefox ya da Xvfb yok")
    sys.exit(0)
try:
    import jeepney  # noqa: F401
except ImportError:
    print("atlandı: jeepney yok")
    sys.exit(0)

from deskhand import masaustu, web  # noqa: E402
from deskhand.arka_uc import sec  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

gecen = toplam = 0
olcum = {}


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def dur_kodu(f, *a, **k):
    try:
        f(*a, **k)
    except Dur as e:
        return e.kod
    return None


def bekle(kosul, sure=5.0, aralik=0.05):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


bekci = wt.ProfilBekcisi()
acik_firefoxlar = []


def profil_denetle(an):
    """Kullanıcının profil kökü değiştiyse HEMEN dur (kendi süreçlerimizi kapat, hiçbir şeyi düzeltme)."""
    f = bekci.fark()
    if f:
        print(f"\n!!! KULLANICI FIREFOX PROFİL KÖKÜ DEĞİŞTİ ({an}): {f}\n!!! test durduruldu; hiçbir şey düzeltilmedi",
              flush=True)
        for ff_ in acik_firefoxlar:
            ff_.kapat()
        masaustu.masaustu_durdur()
        os._exit(2)
    return True


def kapat_hepsi():
    for ff_ in acik_firefoxlar:
        try:
            ff_.kapat()
        except Exception:  # noqa: BLE001
            pass
    if masaustu.durum_oku() is not None:
        masaustu.masaustu_durdur()


atexit.register(kapat_hepsi)

from web_tarayici import BILESEN, DATA_AD, FORM, FORM_GIZLI, MENU, SATIN, SONRADAN  # noqa: E402  (beklenen ögeler)
kapsama = {}  # sayfa → (bulunan, beklenen)


def eslestir(ogeler, beklenen):
    """Beklenen (rol, ad) → öge (birebir ad + rol)."""
    sozluk = {}
    for o in ogeler:
        sozluk.setdefault((o["rol"], o["ad"]), o)
    return {b: sozluk.get(b) for b in beklenen}


def tikla_denetle(t, ogeler, etiket):
    """Her ögenin bildirilen merkezine gerçek tıklama; sayfa doğru ögeyi kaydetti mi? → (doğru, toplam, yanlışlar)"""
    dogru, yanlis = 0, []
    for o in ogeler:
        x, y = o["merkez"]
        kutu = o["kutu"]
        icinde = kutu[0] <= x < kutu[0] + kutu[2] and kutu[1] <= y < kutu[1] + kutu[3]
        ad = t.tikla(x, y, tus="Escape" if o["rol"] == "combo box" else None)
        if icinde and ad == DATA_AD.get(o["ad"], o["ad"]):
            dogru += 1
        else:
            yanlis.append(f"{o['ad']}→{ad}")
    kontrol(f"{etiket}: bildirilen merkeze gerçek tıklama doğru ögeye düştü ({dogru}/{len(ogeler)})",
            dogru == len(ogeler), ", ".join(yanlis))
    return dogru, len(ogeler)


def sure_olc(f, n=3):
    sureler = []
    for _ in range(n):
        t0 = time.perf_counter()
        f()
        sureler.append(time.perf_counter() - t0)
    return statistics.median(sureler)


# ---------------------------------------------------------------- 1) masaüstü + sunucu + Firefox
print("kullanıcı profil kökü (önce):", *bekci.satirlar()[:2], sep="\n  ")
d = masaustu.masaustu_baslat()
au = sec(arka_bayragi=True)
srv = wt.Sunucu()
tiklamalar = [0, 0]
try:
    t0 = time.monotonic()
    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("form.html"))
    acik_firefoxlar.append(ff)
    olcum["Firefox açılışı (geçici profil)"] = f"{time.monotonic() - t0:.1f} sn"
    k = ff.k
    profil_denetle("Firefox açıldı")
    kontrol("firefox: pencere arka plan masaüstünde, kendi süreci", k and k.startswith("arka:") and ff.p.pid in wt.ata_pidler(au.pid(k)))
    kontrol("firefox: geçici profil kendi XDG yapılandırma kökünü kullandı (installs.ini oraya yazıldı ya da hiç)",
            not os.path.exists(os.path.join(wt.FF_KOK, os.path.basename(ff.profil))))
    bekle(lambda: "Form" in ff.baslik(), 10)
    bilgi = bekle(lambda: (lambda s: s if s["adres"].endswith("/form.html") and s["yukleniyor"] is False and
                           s["baslik"] else None)(
        web.sayfa_bilgisi(k)), 10)
    kontrol("sayfa_bilgisi: başlık, adres, yüklendi", bilgi and bilgi["baslik"] == "Deskhand Form Testi" and
            bilgi["adres"] == srv.url("form.html") and bilgi["belge"] == 1, str(bilgi))

    # ---------------------------------------------------------------- 2) form: kapsama, durum, gizli, tıklama
    hepsi = web.oku(k, gorunur=False, en_cok=0)
    es = eslestir(hepsi["ogeler"], FORM)
    kapsama["form"] = (sum(v is not None for v in es.values()), len(FORM))
    kontrol(f"form: etkileşimli ögeler ad + rolle bulundu ({kapsama['form'][0]}/{len(FORM)})",
            kapsama["form"][0] == len(FORM), str([b for b, v in es.items() if v is None]))
    kontrol("form: tarayıcı arayüzü (sekme şeridi 'Kapat', adres çubuğu) sayfa ögelerine KARIŞMADI",
            hepsi["toplam"] == len(FORM) and sum(o["ad"] == "Kapat" for o in hepsi["ogeler"]) == 1,
            str([(o["rol"], o["ad"]) for o in hepsi["ogeler"]]))
    kontrol("form: gizli ögeler (display:none, visibility:hidden, hidden) bildirilmedi",
            not any(o["ad"] in FORM_GIZLI for o in hepsi["ogeler"]))
    kontrol("form: kaydırma alanı dışındaki öge gorunur=False", es[("button", "Sayfa sonu düğmesi")] and
            es[("button", "Sayfa sonu düğmesi")]["gorunur"] is False)
    kontrol("form: devre dışı düğme işaretli", es[("button", "Gönder")] and
            "devre_disi" in es[("button", "Gönder")]["durum"])
    kontrol("form: işaretli onay kutusu / radyo, işaretsizler işaretsiz",
            "isaretli" in es[("check box", "Bülten aboneliği")]["durum"] and
            "isaretli" not in es[("check box", "Koşulları kabul ediyorum")]["durum"] and
            "isaretli" in es[("radio button", "Kargo ile")]["durum"] and
            "isaretli" not in es[("radio button", "Mağazadan teslim")]["durum"])
    kontrol("form: seçim kutusu değeri (seçili seçenek) ve kapalı durumu",
            es[("combo box", "Şehir")].get("deger") == "Niğde" and "kapali" in es[("combo box", "Şehir")]["durum"],
            str(es[("combo box", "Şehir")]))
    # href Firefox'un erişilebilirlik önbelleğine yüklemeden hemen sonra kısa bir süre boş gelebiliyor (ölçüldü)
    href = bekle(lambda: web.oge_bul(k, "Yardım", rol="bağlantı").get("href"), 3)
    kontrol("form: bağlantının adresi (href)", href == srv.url("form.html") + "#yardim", str(href))
    kontrol("form: yazısız simge düğmeleri aria-label / title adıyla",
            all(es[("button", a)] for a in ("Ayarlar", "Yazdır", "Kapat")))
    gorunen = web.sayfa_ogeleri(k)
    kontrol("varsayılan çıktı: yalnız görünür ögeler, kısa (iç alan yok)",
            len(gorunen) == len(FORM) - 1 and all(o["gorunur"] for o in gorunen) and
            not any(a.startswith("_") for o in gorunen for a in o), str(len(gorunen)))
    sayfa1 = web.oku(k, en_cok=5)
    sayfa2 = web.oku(k, en_cok=5, atla=5)
    kontrol("sayfalama: en_cok/atla/sonraki/toplam", len(sayfa1["ogeler"]) == 5 and sayfa1["sonraki"] == 5 and
            [o["no"] for o in sayfa2["ogeler"]] == [6, 7, 8, 9, 10] and sayfa1["toplam"] == len(FORM) - 1)
    kontrol("ad kırpma: ad_siniri", web.sayfa_ogeleri(k, sorgu="Koşulları", ad_siniri=10)[0]["ad"] == "Koşulları…")
    kontrol("roller: 'düğme' takma adı yalnız düğmeler", {o["rol"] for o in web.sayfa_ogeleri(k, roller=["düğme"])}
            == {"button"})
    kontrol("roller: 'başlık' → h1 + otomasyon başlığı", any(o["ad"] == "Üyelik formu" for o in
                                                             web.sayfa_ogeleri(k, roller=["başlık"], gorunur=False)))
    otom = web.sayfa_ogeleri(k, roller=["başlık"], sorgu="webdriver", gorunur=False)
    kontrol("otomasyon işareti: sayfa navigator.webdriver = false görüyor (AT-SPI otomasyon izi bırakmaz)",
            otom and otom[0]["ad"] == "webdriver: false", str(otom))
    t = wt.Tiklayici(au, k)
    tiklanan = [o for o in gorunen if "devre_disi" not in o["durum"]]
    a_, b_ = tikla_denetle(t, tiklanan, "form")
    tiklamalar[0] += a_
    tiklamalar[1] += b_
    kontrol("tıklama: devre dışı düğme tıklamayı sayfaya iletmedi",
            t.tikla(*es[("button", "Gönder")]["merkez"], sure=0.6) is None)
    # kaydırma: sayfa sonuna in → koordinatlar güncel mi
    t.tikla(640, 130, sure=0.3)  # başlık (etkileşimsiz) → belge odağı
    t.tus("End")
    son = bekle(lambda: (lambda o: o if o and o[0]["gorunur"] else None)(
        web.sayfa_ogeleri(k, sorgu="Sayfa sonu düğmesi", gorunur=False)), 5)
    kontrol("kaydırma: sayfa sonundaki düğme artık görünür, üstteki ögeler görünmez",
            son and not any(o["ad"] == "Ad Soyad" for o in web.sayfa_ogeleri(k)), str(son))
    if son:
        kontrol("kaydırma: güncel koordinata tıklama doğru ögeye düştü",
                t.tikla(*son[0]["merkez"]) == "Sayfa sonu düğmesi")
    t.kapat()

    ff.kapat()
    acik_firefoxlar.remove(ff)
    profil_denetle("form sayfası kapandı")

    # ---------------------------------------------------------------- 3) uzun liste: süre + kapsama + kaydırma
    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("liste.html"))
    acik_firefoxlar.append(ff)
    k = ff.k
    bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Liste Testi", 10)
    bekle(lambda: web.oku(k, gorunur=False, en_cok=1)["toplam"] >= 1001, 10)
    web.oku(k, gorunur=False, en_cok=0)  # ilk okuma (ısınma)
    s1000 = sure_olc(lambda: web.oku(k, gorunur=False, en_cok=0))
    s1000g = sure_olc(lambda: web.oku(k))
    hepsi = web.oku(k, gorunur=False, en_cok=0)
    beklenen = [("button", "Listeyi yenile")] + [("link", f"Bağlantı {i:04d}") for i in range(1, 1001)]
    es = eslestir(hepsi["ogeler"], beklenen)
    kapsama["liste-1000"] = (sum(v is not None for v in es.values()), len(beklenen))
    olcum["~1.000 öge: tam okuma (görünmeyenler + href dahil)"] = f"{s1000:.3f} sn ({hepsi['dugum']} düğüm)"
    olcum["~1.000 öge: varsayılan (yalnız görünür)"] = f"{s1000g:.3f} sn"
    kontrol(f"liste: 1.001 öge ad + rolle ({kapsama['liste-1000'][0]}/{len(beklenen)})",
            kapsama["liste-1000"][0] == len(beklenen))
    kontrol("liste: belge sırasında", [o["ad"] for o in hepsi["ogeler"][1:4]] == ["Bağlantı 0001", "Bağlantı 0002",
                                                                              "Bağlantı 0003"])
    kontrol(f"liste: ~1.000 öge tam okuma ≤ 1,5 sn ({s1000:.3f} sn)", s1000 <= 1.5)
    gor = [o for o in hepsi["ogeler"] if o["gorunur"]]
    kontrol("liste: görünür/görünmez ayrımı (görünenler ekranda, çoğu görünmez)",
            10 < len(gor) < 400 and all(0 <= o["merkez"][1] < au.geometri(k)[3] for o in gor), str(len(gor)))
    t = wt.Tiklayici(au, k)
    ornek = gor[1::max(1, len(gor) // 12)][:12]
    a_, b_ = tikla_denetle(t, ornek, "liste (görünen bağlantılardan örnek)")
    tiklamalar[0] += a_
    tiklamalar[1] += b_
    t.tikla(300, 130, sure=0.3)
    t.tus("End")
    son = bekle(lambda: (lambda o: o if o and o[0]["gorunur"] else None)(
        web.sayfa_ogeleri(k, sorgu="Bağlantı 1000", gorunur=False)), 5)
    kontrol("liste kaydırma: son bağlantı görünür, ilk bağlantı görünmez", son and not any(
        o["ad"] == "Bağlantı 0001" for o in web.sayfa_ogeleri(k, en_cok=0)))
    if son:
        a_ = t.tikla(*son[0]["merkez"])
        kontrol("liste kaydırma: güncel koordinata tıklama → 'Bağlantı 1000'", a_ == "Bağlantı 1000", str(a_))
    kontrol("oge_bul: tek öge", web.oge_bul(k, "Bağlantı 0999", gorunur=False)["ad"] == "Bağlantı 0999")
    kontrol("oge_bul: birden çok eşleşme → Dur 5", dur_kodu(web.oge_bul, k, "Bağlantı 09", gorunur=False) == 5)
    kontrol("oge_bul: sira ile seçim", web.oge_bul(k, "Bağlantı 09", gorunur=False, sira=2)["ad"] == "Bağlantı 0901")
    kontrol("oge_bul: yok → Dur 6", dur_kodu(web.oge_bul, k, "Böyle bir öge yok") == 6)
    kontrol("oge_bul: rol süzgeci (düğme)", web.oge_bul(k, "Listeyi yenile", rol="düğme", gorunur=False)["rol"] ==
            "button")
    t.kapat()
    ff.kapat()
    acik_firefoxlar.remove(ff)
    profil_denetle("liste kapandı")

    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("liste.html?n=200"))
    acik_firefoxlar.append(ff)
    k = ff.k
    bekle(lambda: web.oku(k, gorunur=False, en_cok=1)["toplam"] >= 201, 10)
    web.oku(k, gorunur=False, en_cok=0)
    s200 = sure_olc(lambda: web.oku(k, gorunur=False, en_cok=0))
    n200 = web.oku(k, gorunur=False, en_cok=0)["toplam"]
    olcum["~200 öge: tam okuma"] = f"{s200:.3f} sn"
    kapsama["liste-200"] = (n200, 201)
    kontrol(f"liste-200: 201 öge, ≤ 0,4 sn ({s200:.3f} sn)", n200 == 201 and s200 <= 0.4)
    ff.kapat()
    acik_firefoxlar.remove(ff)
    profil_denetle("liste-200 kapandı")

    # ---------------------------------------------------------------- 4) bileşenler: sekme, menü, iframe, sonradan
    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("bilesen.html"))
    acik_firefoxlar.append(ff)
    k = ff.k
    bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Bileşen Testi", 10)
    ogeler = bekle(lambda: (lambda o: o if len([x for x in o if x["ad"].startswith("Çerçeve")]) >= 6 else None)(
        web.sayfa_ogeleri(k, en_cok=0)), 10) or web.sayfa_ogeleri(k, en_cok=0)
    es = eslestir(ogeler, BILESEN)
    kapsama["bileşen"] = (sum(v is not None for v in es.values()), len(BILESEN))
    kontrol(f"bileşen: sekmeler, menü düğmesi, iki iframe'in ögeleri ({kapsama['bileşen'][0]}/{len(BILESEN)})",
            kapsama["bileşen"][0] == len(BILESEN), str([b for b, v in es.items() if v is None]) + " | " +
            str([(o["rol"], o["ad"]) for o in ogeler]))
    kontrol("bileşen: seçili sekme 'secili', diğerleri değil",
            es[("page tab", "Genel")] and "secili" in es[("page tab", "Genel")]["durum"] and
            "secili" not in (es[("page tab", "Ayrıntılar")] or {"durum": ["secili"]})["durum"])
    kontrol("bileşen: iframe ögeleri 'cerceve: 1' işaretli (aynı ve başka köken)",
            all((es[(r, f"Çerçeve {n} {a}")] or {}).get("cerceve") == 1 for n in (1, 2)
                for r, a in (("button", "düğmesi"),)))
    kontrol("bileşen: gizli sekme paneli ve kapalı menü ögeleri görünmüyor",
            not any(o["ad"] in ("Ayrıntı ayarı", "Kopyala") for o in ogeler))
    sonra = bekle(lambda: (lambda o: o if all(o.values()) else None)(eslestir(web.sayfa_ogeleri(k, en_cok=0),
                                                                              SONRADAN)), 5)
    kapsama["sonradan"] = (2 if sonra else 0, 2)
    kontrol("bileşen: 1 sn sonra JS ile eklenen düğme + bağlantı yeniden okumada var", bool(sonra))
    t = wt.Tiklayici(au, k)
    ogeler = web.sayfa_ogeleri(k, en_cok=0)
    a_, b_ = tikla_denetle(t, [o for o in ogeler if o["rol"] != "page tab" and o["ad"] != "Düzen"],
                          "bileşen (iframe'ler + sonradan eklenenler)")
    tiklamalar[0] += a_
    tiklamalar[1] += b_
    ayr = web.oge_bul(k, "Ayrıntılar", rol="page tab")
    t.tikla(*ayr["merkez"])
    yeni = bekle(lambda: (lambda o: o if any(x["ad"] == "Ayrıntı ayarı" for x in o) else None)(
        web.sayfa_ogeleri(k)), 3) or []
    kontrol("sekme: 'Ayrıntılar' seçilince paneli görünür, eski panel gizli, sekme 'secili'",
            any(x["ad"] == "Ayrıntı ayarı" for x in yeni) and not any(x["ad"] == "Genel ayarı" for x in yeni) and
            "secili" in web.oge_bul(k, "Ayrıntılar", rol="page tab")["durum"])
    t.tikla(*web.oge_bul(k, "Düzen", rol="düğme")["merkez"])
    menu = bekle(lambda: (lambda o: o if all(o.values()) else None)(eslestir(web.sayfa_ogeleri(k), MENU)), 3)
    kapsama["menü"] = (sum(v is not None for v in (menu or {}).values()), len(MENU))
    kontrol("menü: açılınca menü ögeleri 'menu item' rolüyle görünür", bool(menu))
    if menu:
        a_ = t.tikla(*menu[("menu item", "Yapıştır")]["merkez"])
        kontrol("menü: 'Yapıştır' ögesine gerçek tıklama", a_ == "Yapıştır", str(a_))
    t.kapat()
    ff.kapat()
    acik_firefoxlar.remove(ff)
    profil_denetle("bileşen kapandı")

    # ---------------------------------------------------------------- 5) satın alma sayfası: hassas işareti
    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("satin.html"))
    acik_firefoxlar.append(ff)
    k = ff.k
    bekle(lambda: web.sayfa_bilgisi(k)["baslik"] == "Deskhand Mağaza Testi", 10)
    ogeler = web.sayfa_ogeleri(k, en_cok=0)
    es = eslestir(ogeler, SATIN)
    kapsama["satın alma"] = (sum(v is not None for v in es.values()), len(SATIN))
    kontrol(f"satın alma: ögeler ({kapsama['satın alma'][0]}/{len(SATIN)})", kapsama["satın alma"][0] == len(SATIN),
            str([(o["rol"], o["ad"]) for o in ogeler]))
    hassas = {o["ad"] for o in ogeler if o.get("hassas")}
    kontrol("hassas: 'Satın al', 'Öde' (yazısız, aria-label), 'Siparişi onayla' hassas; diğerleri değil",
            hassas == {"Satın al", "Öde", "Siparişi onayla"}, str(hassas))
    kontrol("satın alma: sayı alanının değeri", (es[("spin button", "Adet")] or {}).get("deger") == "1",
            str(es[("spin button", "Adet")]))
    t = wt.Tiklayici(au, k)
    a_, b_ = tikla_denetle(t, [o for o in ogeler if not o.get("hassas")], "satın alma (hassas olmayanlar)")
    tiklamalar[0] += a_
    tiklamalar[1] += b_
    t.kapat()
    ff.kapat()
    acik_firefoxlar.remove(ff)
    profil_denetle("satın alma kapandı")

    # ---------------------------------------------------------------- 6) hata yolları
    kontrol("masaüstü kipi (EKRAN) → Dur 1", dur_kodu(web.sayfa_ogeleri, "EKRAN") == 1)
finally:
    kapat_hepsi()
    srv.kapat()

bulunan = sum(a for a, _ in kapsama.values())
beklenen_toplam = sum(b for _, b in kapsama.values())
print("\nkapsama (ad + rol birebir):")
for s_, (a, b) in kapsama.items():
    print(f"  {s_}: {a}/{b} = %{100 * a / b:.1f}")
print(f"  TOPLAM: {bulunan}/{beklenen_toplam} = %{100 * bulunan / max(1, beklenen_toplam):.1f}")
kontrol("kapsama: her sayfada ≥ %95", all(a / b >= 0.95 for a, b in kapsama.values()))
print(f"gerçek tıklama: {tiklamalar[0]}/{tiklamalar[1]} doğru ögeye düştü")
print("ölçümler:")
for a, v in olcum.items():
    print(f"  {a}: {v}")
print("kullanıcı Firefox profil kökü (önce/sonra):")
for s_ in bekci.satirlar():
    print("  " + s_)
kontrol("kullanıcı profil kökü DEĞİŞMEDİ (profiles.ini, installs.ini, dizin adları)", not bekci.fark(),
        str(bekci.fark()))
print(f"\n{gecen}/{toplam} web testi geçti")
sys.exit(0 if gecen == toplam else 1)
