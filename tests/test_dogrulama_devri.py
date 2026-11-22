"""İnsan doğrulaması (CAPTCHA) devri testleri (docs/ARCHITECTURE.md §13). CAPTCHA ÇÖZÜLMEZ: algıla → girdiyi reddet [18] →
kullanıcıya devret (request_human) → çözülünce devam.

A) Saf birim: algı kalıpları/adresleri/başlıkları, yanlış pozitif örnekleri, girdi kapısı mantığı.
B) GÖRÜNMEZ arka plan masaüstünde (Xvfb) YALITIK Firefox (geçici profil; tests/yardimci/web_tarayici.py) 127.0.0.1'den
   sentetik sayfalar açar (sahte reCAPTCHA / Turnstile iframe'i ve metni; DIŞ AĞ YOK, gerçek CAPTCHA sitesi YOK):
   observe → human_verification; sınama ögesine click/type_text/press_key/drag → [18] ve HİÇBİR GİRDİ gönderilmez
   (sayfanın günlüğü/odak değişmez); sayfanın geri kalanı (kullanıcı adı alanı) hâlâ kullanılabilir; blog yazısı
   (CAPTCHA'dan bahseder) ALGILANMAZ.
C) request_human: sahte/yalıtık panelle (test süreci panel gibi davranır; gerçek panele DOKUNULMAZ) resolved
   (Bitti ve sınama kalktı), timeout, declined; bildirim SAHTE (kullanıcının ekranına bildirim gitmez).
Kullanıcının ekranına girdi/pencere/bildirim gitmez; arka uç kde ise test HEMEN çıkar. Kullanıcı Firefox profili
karşılaştırılır. Firefox/Xvfb yoksa B bölümü atlanır.

Çalıştır:  python3 tests/test_dogrulama_devri.py"""
import atexit
import os
import shutil
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))

from deskhand import dogrulama_sinamasi as ds  # noqa: E402
from deskhand import hata, mcp_sunucu, onay  # noqa: E402

gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def bekle(kosul, sure=5.0, aralik=0.05):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


def oge(rol, ad, cerceve=0, kaynak="web"):
    return {"rol": rol, "ad": ad, "ad_ham": ad, "kutu": [10, 10, 100, 20], "cerceve": cerceve, "kaynak": kaynak,
            "etkilesimli": True, "durumlar": []}


# ================================================================ A) saf birim
print("== A) algı kalıpları (saf)")
kontrol("başlık: 'Just a moment...' / 'Bir dakika lütfen…' / 'Attention Required! | Cloudflare'",
        all(ds.baslik_mi(b) for b in ("Just a moment...", "Bir dakika lütfen…", "Attention Required! | Cloudflare",
                                      "Verifying you are human. This may take a few seconds.")))
kontrol("başlık: blog başlığı / uzun başlık ALGILANMAZ", not ds.baslik_mi("Why CAPTCHAs fail users - a blog") and
        not ds.baslik_mi("Just a moment " + "x" * 120) and not ds.baslik_mi("Anasayfa") and not ds.baslik_mi(""))
kontrol("adres: reCAPTCHA anchor/bframe → recaptcha",
        ds.adres_turu("https://www.google.com/recaptcha/api2/anchor?ar=1&k=abc&size=normal") == "recaptcha" and
        ds.adres_turu("https://www.google.com/recaptcha/api2/bframe?hl=en") == "recaptcha")
kontrol("adres: GÖRÜNMEZ reCAPTCHA v3 rozeti (size=invisible) sınama DEĞİL",
        ds.adres_turu("https://www.google.com/recaptcha/api2/anchor?ar=1&k=abc&size=invisible") is None and
        ds.adres_turu("https://www.google.com/recaptcha/enterprise/anchor?size=invisible") is None)
kontrol("adres: hCaptcha / Turnstile / Arkose / GeeTest",
        ds.adres_turu("https://newassets.hcaptcha.com/captcha/v1/abc/static/hcaptcha.html") == "hcaptcha" and
        ds.adres_turu("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv/") ==
        "turnstile" and ds.adres_turu("https://client-api.arkoselabs.com/fc/gc/?pkey=1") == "arkose" and
        ds.adres_turu("https://gt4.geetest.com/captcha") == "geetest")
kontrol("adres: sıradan iframe (video, harita) sınama değil",
        ds.adres_turu("https://www.youtube.com/embed/abc") is None and ds.adres_turu("http://127.0.0.1:1/x.html") is None
        and ds.adres_turu("") is None and ds.adres_turu(None) is None)

s = ds.incele([oge("check box", "I'm not a robot", cerceve=1)], "Giriş", {})
kontrol("öge: iframe içinde 'I'm not a robot' onay kutusu → human_checkbox",
        s and s["kind"] == "human_checkbox" and s["elements"] == [0] and s["confidence"] == "high", str(s))
for ad in ("Ben robot değilim", "Verify you are human", "İnsan olduğunuzu doğrulayın", "I am not a robot"):
    s = ds.incele([oge("check box", ad)], "x", {})
    kontrol(f"öge: onay kutusu '{ad}'", s and s["kind"] == "human_checkbox", str(s))
s = ds.incele([oge("push button", "Slide to verify", cerceve=1)], "x", {})
kontrol("öge: sürükle-bulmaca ('Slide to verify') → slider_puzzle", s and s["kind"] == "slider_puzzle", str(s))
HC = "https://newassets.hcaptcha.com/captcha/v1/x/hcaptcha.html"
s = ds.incele([oge("check box", "hCaptcha checkbox", cerceve=1), oge("entry", "Kullanıcı adı"),
               {**oge("link", "Gizlilik", 1), "belge_adres": HC}],
              "x", {"cerceveler": [{"ad": "", "adres": HC}]})
kontrol("çerçeve adresi + ögeler: tür hcaptcha; çerçevedeki ögeler işaretli, kullanıcı adı alanı DEĞİL",
        s and s["kind"] == "hcaptcha" and 0 in s["elements"] and 2 in s["elements"] and 1 not in s["elements"], str(s))
s = ds.incele([oge("check box", "I'm not a robot", 1)], "Just a moment...", {})
kontrol("başlık 'Just a moment...' + sınama ögesi → cloudflare_interstitial, sayfanın tamamı", s and s["kind"] ==
        "cloudflare_interstitial" and s["page_wide"], str(s))
kontrol("başlık TEK BAŞINA yetmez ('Just a Moment (Official Video) - YouTube', 'One more step - Create account')",
        ds.incele([oge("entry", "Yorum")], "Just a Moment (Official Video) - YouTube", {}) is None and
        ds.incele([oge("entry", "E-posta")], "One more step - Create account", {}) is None)
s = ds.incele([oge("entry", "x")], "Just a moment...", {"adres": "https://site.test/cdn-cgi/challenge-platform/h/b"})
kontrol("başlık + /cdn-cgi/ adresi → ara sayfa", s and s["page_wide"], str(s))
s = ds.incele([oge("ocr_text", "I'm not a robot", kaynak="ocr")], "x", {})
kontrol("OCR: kısa tek başına satır → düşük güvenle algılanır", s and s["confidence"] == "low", str(s))

print("== A) yanlış pozitif örnekleri")
blog = [oge("heading", "Why CAPTCHAs fail users"),
        oge("static", "Many sites ask visitors to tick \"I'm not a robot\" or to verify you are human by sliding"),
        oge("link", "reCAPTCHA nedir?"), oge("link", "Verify you are human: a history"), oge("button", "Yorum gönder"),
        oge("ocr_text", "This article explains why the I'm not a robot checkbox of a reCAPTCHA annoys people", kaynak="ocr")]
kontrol("blog yazısı (CAPTCHA'dan bahseder; bağlantı/başlık/uzun paragraf) ALGILANMAZ",
        ds.incele(blog, "Why CAPTCHAs fail users - a blog", {}) is None)
kontrol("'Captcha' adlı üst düzey bağlantı ALGILANMAZ", ds.incele([oge("link", "CAPTCHA settings")], "Ayarlar", {}) is None)
kontrol("boş sayfa / ögesiz ALGILANMAZ", ds.incele([], "", {}) is None and ds.incele(None, None, None) is None)

print("== A) girdi kapısı (saf)")
ds.temizle()
K = "arka:1"
kontrol("durum yokken sıradan hedef serbest", ds.girdi_engeli(K, ad="Giriş yap", klavye=True, baslik="Giriş") is None)
kontrol("durum yokken KUTU ROLÜNDEKİ 'I'm not a robot' öge adı reddedilir (rol yoksa serbest: KÜÇÜK-7)",
        ds.girdi_engeli(K, ad="I'm not a robot", baslik="x", rol="check box") is not None and
        ds.girdi_engeli(K, ad="I'm not a robot", baslik="x") is None)
kontrol("sinama bayraklı ref reddedilir", ds.girdi_engeli(K, oge={"sinama": True}, baslik="x") is not None)
snc = ds.incele([oge("check box", "I'm not a robot", 1)], "x", {})
og = [oge("check box", "I'm not a robot", 1)]
ds.kaydet(K, snc, og)
kontrol("durum var: kutu içindeki nokta reddedilir, dışı serbest",
        ds.girdi_engeli(K, nokta=(50, 20), baslik="x") is not None and ds.girdi_engeli(K, nokta=(500, 500), baslik="x") is None)
kontrol("durum var (sayfa geneli DEĞİL): hedefsiz klavye serbest", ds.girdi_engeli(K, klavye=True, baslik="x") is None)
_og2 = [oge("check box", "I'm not a robot", 1)]
ds.kaydet("arka:2", ds.incele(_og2, "Just a moment...", {}), _og2, baslik="Just a moment...")
kontrol("ara sayfa (sayfa geneli sınama): hedefsiz klavye reddedilir",
        ds.girdi_engeli("arka:2", klavye=True, baslik="Just a moment...") is not None)
kontrol("başlık değişince durum atılır (sayfa değişti)", ds.girdi_engeli("arka:2", klavye=True, baslik="Hos geldiniz") is None
        and ds.durum("arka:2") is None)
kontrol("TTL dolunca durum kalkar", ds.durum(K, simdi=time.monotonic() + ds.TTL + 1) is None)
ds.temizle()

def _gunluk_metni():
    from deskhand import yollar
    d_ = yollar.gunluk_dizin()
    return "".join(open(os.path.join(d_, f_), errors="replace").read() for f_ in os.listdir(d_)) if os.path.isdir(d_) else ""


print("== A) yeni birim: iframe ayrımı, çözülmüş, ayar kutuları, metin CAPTCHA, gizlilik, durum dosyası")
YT = "https://www.youtube.com/embed/abc"
RC = "https://www.google.com/recaptcha/api2/anchor?ar=1&k=abc&size=normal"
ogs = [{**oge("button", "Oynat", 1), "belge_adres": YT}, {**oge("check box", "I'm not a robot", 1), "belge_adres": RC},
       {**oge("link", "Gizlilik", 1), "belge_adres": RC}, {**oge("entry", "Kart numarası", 1), "belge_adres": "https://js.stripe.com/v3/x"}]
s = ds.incele(ogs, "Sayfa", {"adres": "https://site.test/", "cerceveler": [{"adres": YT}, {"adres": RC}]})
kontrol("C1: yalnız SINAMA belgesinin ögeleri işaretli (YouTube/Stripe iframe ögeleri DEĞİL)",
        s and s["elements"] == [1, 2], str(s))
ck = oge("check box", "I'm not a robot", 1)
ck["durumlar"] = ["checked"]
kontrol("C3: çözülmüş sınama (işaretli onay kutusu) algılanmaz", ds.incele([ck], "x", {}) is None)
kontrol("C3: Turnstile 'Success!' algılanmaz",
        ds.incele([oge("static", "Success!", 1)], "Just a moment...", {"cerceveler": [{"adres": "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv/"}]}) is None)
kontrol("C6: 'Require human verification' ayar kutusu sınama değil",
        ds.incele([oge("check box", "Require human verification")], "Ayarlar", {}) is None and
        ds.ad_kalibi_mi("Require human verification") is None)
kontrol("C6: 'Move the slider to set the maximum price' fiyat kaydırıcısı sınama değil",
        ds.incele([oge("slider", "Move the slider to set the maximum price")], "Fiyat", {}) is None)
kontrol("C6: 'Enable CAPTCHA' ayar kutusu / 'Captcha settings' düğmesi sınama değil",
        ds.incele([oge("check box", "Enable CAPTCHA"), oge("button", "Captcha settings")], "Ayarlar", {}) is None)
kontrol("C6: görünmez hCaptcha (#frame=checkbox-invisible) muaf",
        ds.adres_turu("https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha.html#frame=checkbox-invisible&id=1") is None)
kontrol("C6: OCR satırında yan yana başka bağlantı ('reCAPTCHA nedir? Verify you are human: a history') kalıp oranı düşük",
        ds.ad_kalibi_mi("reCAPTCHA nedir? Verify you are human: a history", oran=ds.KALIP_ORANI) is None and
        ds.ad_kalibi_mi("I'm not a robot", oran=ds.KALIP_ORANI) == "human_checkbox")
# A4: klasik metin CAPTCHA'sı ve 2FA ayrımı
resim = {"rol": "image", "ad": "", "ad_ham": "", "kutu": [10, 40, 120, 40], "cerceve": 0, "kaynak": "web"}
kod = {"rol": "entry", "ad": "Güvenlik kodu", "ad_ham": "Güvenlik kodu", "kutu": [10, 90, 200, 30], "cerceve": 0, "kaynak": "web"}
sms = {"rol": "entry", "ad": "Doğrulama kodu", "ad_ham": "Doğrulama kodu", "kutu": [10, 90, 200, 30], "cerceve": 0, "kaynak": "web"}
mesaj = {"rol": "static", "ad": "Telefonunuza SMS ile gönderilen doğrulama kodunu girin", "ad_ham": "Telefonunuza SMS ile gönderilen doğrulama kodunu girin", "kutu": [10, 50, 300, 20], "cerceve": 0, "kaynak": "web"}
s = ds.incele([resim, kod], "e-Devlet giriş", {})
kontrol("A4: resim + 'Güvenlik kodu' giriş alanı → text_captcha, alan işaretli", s and s["kind"] == "text_captcha" and 1 in s["elements"], str(s))
kontrol("A4: 2FA 'Doğrulama kodu' alanı (SMS bağlamı, resimsiz) serbest", ds.incele([mesaj, sms], "Giriş", {}) is None)
kontrol("A4: resimsiz 'Doğrulama kodu' alanı serbest", ds.incele([sms], "Giriş", {}) is None)
# D: gizlilik
ozet = ds.cerceve_ozeti([{"ad": "", "adres": "https://www.google.com/recaptcha/api2/anchor?ar=1&k=GIZLI&co=aHR0cHM6Ly9ldi5leGFtcGxlOjQ0Mw"}])
kontrol("D: frame_documents yalnız tür + alan adı (sorgu dizgesi YOK)",
        ozet == [{"kind": "recaptcha", "host": "www.google.com"}] and "GIZLI" not in str(ozet), str(ozet))
# durum dosyası (CLI süreciyle paylaşım)
import subprocess  # noqa: E402
ds.temizle()
og3 = [oge("check box", "I'm not a robot", 1)]
ds.kaydet("arka:77", ds.incele(og3, "Giriş", {"adres": "https://a.test/"}), og3, baslik="Giriş", adres="https://a.test/")
yol_ = ds._yol()
kontrol("A3: durum çalışma dizininde JSON, 0600", os.path.isfile(yol_) and (os.stat(yol_).st_mode & 0o777) == 0o600)
cikti = subprocess.run([sys.executable, "-I", "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); from deskhand import dogrulama_sinamasi as d;"
                        "print(d.girdi_engeli('arka:77', nokta=(50, 20), baslik='Giriş') is not None)", _yalitim.KOK],
                       capture_output=True, text=True, env=os.environ).stdout.strip()
kontrol("A3: başka süreç (CLI) aynı sınama kutusunu görür", cikti == "True", cikti)
kontrol("C5: adres değişince durum atılır", ds.durum("arka:77", adres="https://b.test/") is None)
ds.temizle()
kontrol("B4: devir_baslat ATOMİK (ikincisi False)", ds.devir_baslat("arka:9") and not ds.devir_baslat("arka:9") and
        (ds.devir_bitir("arka:9") or True) and ds.devir_baslat("arka:9") and (ds.devir_bitir("arka:9") or True))
kontrol("C3: bastir → aynı imza bastırılır, farklı imza değil", (ds.bastir("arka:8", "abc") or True) and
        ds.bastirilmis_mi("arka:8", "abc") and not ds.bastirilmis_mi("arka:8", "xyz"))
ds.temizle()
# B1: bekleyen_var devir isteğini 125 sn sınırında "sahte" saymaz
_simdi = time.time()
_d = {"id": "a" * 32, "masaustu": "arka", "pid": os.getpid() + 1, "zaman": _simdi, "son_zaman": _simdi + 600, "tur": "devir"}
_once_b = onay.bekleyenler
onay.bekleyenler = lambda simdi=None: [dict(_d)]
kontrol("B1: 600 sn'lik DEVİR isteği girdiyi kapatır (bekleyen_var)", onay.bekleyen_var("arka") is True)
_d["tur"] = ""
kontrol("B1: 600 sn'lik sıradan istek 'sahte' sayılır", onay.bekleyen_var("arka") is False)
onay.bekleyenler = _once_b


# ================================================================ A) ikinci inceleme düzeltmeleri (saf birim)
print("== A) ikinci inceleme: kısa metin kuralı (KÜÇÜK-7)")
ds.temizle()
K7 = "arka:70"
kontrol("K7: sınama YOKKEN 'I'm Not a Robot (2017)' dizi adı serbest",
        ds.girdi_engeli(K7, ad="I'm Not a Robot (2017)", baslik="x") is None and
        ds.girdi_engeli(K7, ad="I'm Not a Robot (2017)", baslik="x", rol="link") is None)
kontrol("K7: sınama yokken 'Ben Robot Değilim' / 'Are you human?' metin hedefi serbest (rol yok)",
        ds.girdi_engeli(K7, ad="Ben Robot Değilim", baslik="x") is None and
        ds.girdi_engeli(K7, ad="Are you human?", baslik="x") is None)
kontrol("K7: 'Slide right to unlock' artık sürükle-bulmaca kalıbı DEĞİL", ds.ad_kalibi_mi("Slide right to unlock") is None and
        ds.incele([oge("button", "Slide right to unlock")], "Ekran kilidi", {}) is None)
kontrol("K7: sınama yokken KUTU ROLÜNDEKİ öge adı hâlâ reddedilir",
        ds.girdi_engeli(K7, ad="I'm not a robot", baslik="x", rol="check box") is not None)
kontrol("K7: sayfa OKUNAMADIYSA (metin_kati) kısa cümle doğrulanamadığı için reddedilir",
        ds.girdi_engeli(K7, ad="I'm not a robot", baslik="x", metin_kati=True) is not None)

print("== A) ikinci inceleme: durum dosyası doğrulama (ORTA-5), önbellek TTL (ORTA-4), eski durum (KÜÇÜK-8)")
import json  # noqa: E402


def dosya_yaz(d_):
    with open(ds._yol(), "w", encoding="utf-8") as f_:
        json.dump(d_, f_)


simdi0 = time.monotonic()
boot = ds._boot_id()
gecerli = {"kind": "recaptcha", "window": "w", "hint": "h", "confidence": "high", "page_wide": False, "imza": "i", "site": "",
           "kutular": [[10, 10, 100, 20]], "zaman": simdi0, "baslik": "", "adres": ""}
dosya_yaz({"boot": boot, "sinama": {"arka:81": dict(gecerli)}, "yok": {}, "bastir": {}})
kontrol("O5: geçerli kayıt okunur", ds.durum("arka:81") is not None)
dosya_yaz({"boot": boot, "sinama": {}, "yok": {"arka:82": {"baslik": "", "zaman": 1e12}}, "bastir": {}})
kontrol("O5: ajanın yazdığı yok[k].zaman=1e12 (gelecek) kapıyı kalıcı AÇMAZ", ds.yok_mu("arka:82", "") is False)
dosya_yaz({"boot": boot, "sinama": {}, "yok": {"arka:83": {"baslik": "", "zaman": simdi0 - ds.YOK_TTL - 5}}, "bastir": {}})
kontrol("O5: süresi geçmiş yok kaydı geçersiz (TTL üst sınırı kesin)", ds.yok_mu("arka:83", "") is False)
dosya_yaz({"boot": boot, "sinama": {"arka:84": {**gecerli, "kutular": "bozuk"}, "arka:85": {"zaman": simdi0},
                                     "arka:86": {**gecerli, "zaman": 1e12}, "arka:87": {**gecerli, "zaman": "x"},
                                     "arka:88": "yok", "arka:89": {**gecerli, "zaman": simdi0 - ds.TTL - 5}},
           "yok": {"arka:90": {"zaman": None}}, "bastir": {"arka:91": {"zaman": simdi0}}})
try:
    sonuclar_ = [ds.durum(f"arka:{n}") for n in (84, 85, 86, 87, 88, 89)] + [ds.yok_mu("arka:90", ""),
                                                                              ds.bastirilmis_mi("arka:91", "x")]
    hata_ = None
except Exception as e_:  # noqa: BLE001
    sonuclar_, hata_ = None, e_
kontrol("O5: bozuk kayıt (tip, eksik alan, gelecek/eski zaman) KeyError atmaz, atılır",
        hata_ is None and sonuclar_ is not None and not any(sonuclar_), f"{sonuclar_} {hata_!r}")
dosya_yaz({"boot": "baska-boot-kimligi", "sinama": {"arka:81": dict(gecerli)}, "yok": {}, "bastir": {}})
kontrol("O5: önyükleme kimliği farklıysa (monotonic sıfırlandı) tüm kayıtlar atılır", ds.durum("arka:81") is None)
dosya_yaz(["liste", "bozuk"])
kontrol("O5: kök sözlük değilse sıfırlanır", ds.durum("arka:81") is None and ds.yok_mu("arka:81", "") is False)
ds.temizle()
kontrol("O4: YOK_TTL en çok 3 sn", ds.YOK_TTL <= 3.0)
ds.yok_kaydet("arka:60", "b")
kontrol("O4: yok önbelleği yazıldı", ds.yok_mu("arka:60", "b") is True)
ds.girdi_oldu()
kontrol("O4: girdi gönderilince (girdi_oldu) yok önbelleği silinir", ds.yok_mu("arka:60", "b") is False)
ds.yok_kaydet("arka:60", "b", simdi=time.monotonic() - 100)
kontrol("O4: eski zamanlı yok kaydı geçersiz", ds.yok_mu("arka:60", "b") is False)

# K8: durum eskiyse hazir yeniden tarar; yeniyse taramaz; okunamazsa eski durum korunur (kapı açılmaz)
ds.temizle()
sayac = {"tara": 0}
_tara_once, _tm_once = ds.tara, ds.tarayici_mi


def _sahte_tara(k_, baslik=None, kapi=False):
    sayac["tara"] += 1
    return None, False


ds.tara, ds.tarayici_mi = _sahte_tara, lambda k_: True
og_ = [oge("check box", "I'm not a robot", 1)]
ds.kaydet("arka:61", ds.incele(og_, "x", {}), og_, baslik="x")
d_ = ds.hazir("arka:61", "x")
kontrol("K8: yeni durum için yeniden tarama YOK", d_ is not None and sayac["tara"] == 0, str(sayac))
ds.kaydet("arka:61", ds.incele(og_, "x", {}), og_, baslik="x", simdi=time.monotonic() - ds.YENI_TTL - 5)
d_ = ds.hazir("arka:61", "x")
kontrol("K8: YENI_TTL'den eski durum yeniden taranır; okunamayınca eski durum KORUNUR (kapı açılmaz)",
        sayac["tara"] == 1 and d_ is not None, str(sayac))
ds.tara, ds.tarayici_mi = _tara_once, _tm_once
ds.temizle()

print("== A) ikinci inceleme: tarama hatası/belge yok önbelleği, erişilebilirlik kapalıyken fail-open (ORTA-3)")
from deskhand import api as _api, erisim as _erisim, web as _web  # noqa: E402

_once = (ds.tarayici_mi, ds.baslik_simdi, _web.oku, _web.hazirla, _erisim.erisim_acik, _api.yasak_mi)
acik_ = {"v": True}
cagri = {"oku": 0, "hazirla": 0}
mod_ = {"c": "hata"}


def _oku(k_, *a_, **kw_):
    cagri["oku"] += 1
    if mod_["c"] == "hata":
        raise hata.Dur(hata.ARAC_EKSIK, "yanıt yok")
    return {"ogeler": [], "sayfa": {"belge": 0, "adres": ""}}


def _hazirla(k_):
    cagri["hazirla"] += 1


ds.tarayici_mi, ds.baslik_simdi = (lambda k_: True), (lambda k_: "T")
_web.oku, _web.hazirla, _erisim.erisim_acik, _api.yasak_mi = _oku, _hazirla, (lambda: acik_["v"]), (lambda k_: None)
_ag_once = _erisim.erisim_ac_garanti
ac_say = {"n": 0}
_erisim.erisim_ac_garanti = lambda: ac_say.__setitem__("n", ac_say["n"] + 1)  # SAHTE: gerçek erişilebilirlik açılmaz
ds._ERISIM_DENENDI.clear()
try:
    ds.temizle()
    r1 = [ds.hazir_oku("arka:62", "T") for _i in range(5)]
    kontrol("O3: okunamayan pencere 5 girdide YALNIZ BİR kez taranır (okunamadı önbelleği)", cagri["oku"] == 1 and
            all(r_ == (None, False) for r_ in r1), f"{cagri} {r1}")
    mod_["c"] = "belge0"
    cagri["oku"] = 0
    ds.temizle()
    r2 = [ds.hazir_oku("arka:63", "T") for _i in range(5)]
    kontrol("O3: web belgesi olmayan (Electron arayüzü, belge=0) pencere her girdide DEĞİL, bir kez taranır",
            cagri["oku"] == 1 and all(r_ == (None, False) for r_ in r2), f"{cagri} {r2}")
    acik_["v"] = False
    cagri.update(oku=0, hazirla=0)
    ds.temizle()
    r3 = ds.hazir_oku("arka:64", "T")
    kontrol("O3: erişilebilirlik KAPALI kalırsa sayfa OKUNAMADI sayılır (web.hazirla/oku çağrılmaz); açma BİR kez denendi",
            r3 == (None, False) and cagri == {"oku": 0, "hazirla": 0} and ac_say["n"] == 1, f"{cagri} {r3} {ac_say}")
    for n_ in (65, 66, 67):
        ds.temizle()
        ds.hazir_oku(f"arka:{n_}", "T")
    kontrol("O2: tarayıcıda kapı için erişilebilirlik süreç başına YALNIZ BİR kez açılır (erisim_ac_garanti)",
            ac_say["n"] == 1, str(ac_say))
    ds._ERISIM_DENENDI.clear()
    ds.temizle()
    ac_say["n"] = 0
    _acildi = {"v": False}

    def _ag():
        ac_say["n"] += 1
        acik_["v"] = _acildi["v"] = True

    _erisim.erisim_ac_garanti = _ag
    mod_["c"] = "tamam"
    _oku_eski = _web.oku
    _web.oku = lambda k_, *a_, **kw_: {"ogeler": [], "sayfa": {"belge": 1, "adres": "http://x.test/"}}
    cagri.update(oku=0, hazirla=0)
    r4 = ds.hazir_oku("arka:68", "T")
    kontrol("O2: erişilebilirlik kapıda açılınca tarama ilerler ve sayfa okunur", r4 == (None, True) and ac_say["n"] == 1,
            f"{r4} {ac_say}")
    _web.oku = _oku_eski
    acik_["v"] = False
    kontrol("O3: kapı taraması toplam süre sınırı <= 2 sn", ds.TARAMA_SURESI <= 2.0)
    with _web.tarama_siniri(1.0):
        ic_ = getattr(_web._SINIR, "bitis", None)
    kontrol("O3: tarama_siniri bitiş koyar ve çıkışta geri alır", ic_ is not None and getattr(_web._SINIR, "bitis", None) is None)
finally:
    ds.tarayici_mi, ds.baslik_simdi, _web.oku, _web.hazirla, _erisim.erisim_acik, _api.yasak_mi = _once
    _erisim.erisim_ac_garanti = _ag_once
    ds.temizle()

print("== A) ikinci inceleme: klavye Tab dizisi (BÜYÜK-2), odak önbelleği (KÜÇÜK-9)")
kontrol("B2: dizi kuralı: tab,space → ret; space,tab / tab,tab / tab → serbest; shift+tab,x → ret",
        ds.tab_sonrasi_girdi(["tab", "space"]) and ds.tab_sonrasi_girdi(["shift+tab", "x"]) and
        not ds.tab_sonrasi_girdi(["space", "tab"]) and not ds.tab_sonrasi_girdi(["tab", "tab"]) and
        not ds.tab_sonrasi_girdi(["tab"]) and not ds.tab_sonrasi_girdi([]) and not ds.tab_sonrasi_girdi(None))
kontrol("B2: yazı TAB+boşluk / TAB+AB12C ret, AB+TAB / abc serbest",
        ds.tab_sonrasi_girdi(ds.metin_dizisi("\t ")) and ds.tab_sonrasi_girdi(ds.metin_dizisi("\tAB12C")) and
        not ds.tab_sonrasi_girdi(ds.metin_dizisi("AB\t")) and not ds.tab_sonrasi_girdi(ds.metin_dizisi("abc")))
ds.temizle()
og_ = [oge("check box", "I'm not a robot", 1)]
ds.kaydet("arka:65", ds.incele(og_, "x", {}), og_, baslik="x")
_bs = ds.baslik_simdi
ds.baslik_simdi = lambda k_: "x"
odak_sayaci = {"n": 0}


def _odak_yok():
    odak_sayaci["n"] += 1
    return None


r_tab = ds.klavye_engeli("arka:65", odak_sorgu=_odak_yok, dizi=["tab", "space"])
kontrol("B2: sınama varken odak dışındayken 'tab space' → ret (odağa bakmadan)", r_tab is not None and odak_sayaci["n"] == 0,
        str(r_tab))
kontrol("B2: 'tab' tek başına / 'space' (odak BİLİNİYOR ve sınama dışında) serbest",
        ds.klavye_engeli("arka:65", odak_sorgu=_odak_yok, dizi=["tab"]) is None and
        ds.klavye_engeli("arka:65", odak_sorgu=lambda: {"kutu": [500, 500, 5, 5]}, dizi=["space"]) is None)
ds.temizle()
ds.baslik_simdi = _bs
# K9: odak sorgusu kısa önbellekli; girdi_oldu siler
_o2 = (ds.tarayici_mi, _web.oku, _web.hazirla)
oc = {"n": 0}


def _oku2(k_, *a_, **kw_):
    oc["n"] += 1
    return {"ogeler": [{"durum": ["odakli"], "kutu": [0, 0, 5, 5], "rol": "entry", "ad": "x"}], "sayfa": {"belge": 1}}


ds.tarayici_mi, _web.oku, _web.hazirla = (lambda k_: True), _oku2, (lambda k_: None)
try:
    ds._ODAK.clear()
    a1, a2 = ds.odakli_oge("arka:66"), ds.odakli_oge("arka:66")
    kontrol("K9: odak sorgusu önbellekli: iki klavye komutu tek tarama", oc["n"] == 1 and a1 == a2 and a1["kutu"] == [0, 0, 5, 5],
            str(oc))
    ds.girdi_oldu()
    ds.odakli_oge("arka:66")
    kontrol("K9: girdi gönderilince odak önbelleği silinir (odak değişmiş olabilir)", oc["n"] == 2, str(oc))
finally:
    ds.tarayici_mi, _web.oku, _web.hazirla = _o2
    ds._ODAK.clear()

print("== A) ikinci inceleme: tüm ekran kipi (BÜYÜK-1), sınama çerçevesi ögesi (ORTA-6)")


class SahteAu:
    """Masaüstü kipi arka ucu: imleç altındaki pencere + geometrisi."""
    def __init__(self, w, geo):
        self.w, self.geo = w, geo

    def fare(self):
        return (0, 0, self.w)

    def geometri(self, k_):
        return self.geo


ds.temizle()
og_ = [{**oge("check box", "I'm not a robot", 1), "kutu": [100, 100, 50, 20]}]
ds.kaydet("arka:67", ds.incele(og_, "x", {}), og_, baslik="x")
_tm = ds.tarayici_mi
ds.tarayici_mi = lambda k_: True
_bs = ds.baslik_simdi
ds.baslik_simdi = lambda k_: "x"
au_ = SahteAu("arka:67", (200, 300, 800, 600))
r_ = ds.ekran_nokta_engeli(au_, 200 + 110, 300 + 110)
kontrol("B1: EKRAN: imleç altındaki pencere + pencereye göre nokta sınama kutusundaysa → ret", r_ is not None, str(r_))
kontrol("B1: EKRAN: aynı pencerede sınama dışı nokta serbest", ds.ekran_nokta_engeli(au_, 200 + 500, 300 + 400) is None)
kontrol("B1: EKRAN: pencereye göreli nokta (ekran pikseli ile KARIŞTIRILMAZ): ekran (110,110) kutu dışı",
        ds.ekran_nokta_engeli(au_, 110, 110) is None)
kontrol("B1: EKRAN: pencere çözülemezse kısa insan-doğrulama cümlesi reddedilir (doğrulanamadı)",
        ds.ekran_nokta_engeli(SahteAu("", None), 5, 5, ["I'm not a robot"]) is not None and
        ds.ekran_nokta_engeli(SahteAu("", None), 5, 5, ["Kaydet"]) is None)
ds.tarayici_mi, ds.baslik_simdi = _tm, _bs
ds.temizle()
RC2 = "https://www.google.com/recaptcha/api2/anchor?ar=1&k=abc&size=normal"
from deskhand import erisim, eylem  # noqa: E402

try:
    eylem.insan_dogrulama_oge("arka:1", {"ad": "Gizlilik", "rol": "link", "_belge_adres": RC2, "gorunur": False})
    kod_oge = 0
except hata.Dur as e_:
    kod_oge = e_.kod
kontrol("O6: görünmeyen web ögesi sınama çerçevesinin içindeyse (_belge_adres) → 18", kod_oge == 18, str(kod_oge))
try:
    erisim._hassas_oge("arka:1", False, "x", {"ad": "Gizlilik", "cx": None, "cy": None, "_belge_adres": RC2}, {})
    kod_oge2 = 0
except hata.Dur as e_:
    kod_oge2 = e_.kod
kontrol("O6: via=action yolu (_hassas_oge) aynı kapıdan geçer → 18", kod_oge2 == 18, str(kod_oge2))
try:
    eylem.insan_dogrulama_oge("arka:1", {"ad": "Oynat", "rol": "button", "_belge_adres": "https://www.youtube.com/embed/abc"})
    kod_oge3 = 0
except hata.Dur as e_:
    kod_oge3 = e_.kod
kontrol("O6: sıradan iframe (video) ögesi 18 DEĞİL", kod_oge3 == 0, str(kod_oge3))
ds.temizle()

# ================================================================ A) ÜÇÜNCÜ İNCELEME düzeltmeleri (saf birim, sahte arka uç)
print("== A) üçüncü inceleme: O1 durum dosyası yalnız engel ekler (yok/okunamadi yalnız bellek)")
ds.temizle()
ds.yok_kaydet("arka:40", "b")
ds.okunamadi_kaydet("arka:41", "b")
ham_ = open(ds._yol(), encoding="utf-8").read()
kontrol("O1: yok / okunamadi kayıtları dosyaya YAZILMAZ", '"yok"' not in ham_ and '"okunamadi"' not in ham_ and
        "arka:40" not in ham_ and "arka:41" not in ham_, ham_)
kontrol("O1: ama süreç içinde etkin (bellek)", ds.yok_mu("arka:40", "b") and ds.okunamadi_mu("arka:41", "b"))
ds.temizle()
simdi1 = time.monotonic()
dosya_yaz({"boot": ds._boot_id(), "sinama": {}, "bastir": {}, "girdi": {},
           "yok": {"arka:42": {"baslik": "b", "zaman": simdi1}}, "okunamadi": {"arka:43": {"baslik": "b", "zaman": simdi1}}})
kontrol("O1: dosyadaki taze `yok` / `okunamadi` kaydı OKUNMAZ (kapıyı açamaz)",
        ds.yok_mu("arka:42", "b") is False and ds.okunamadi_mu("arka:43", "b") is False)
with ds._depo() as d_:
    kontrol("O1: eski sürümün yok/okunamadi bölümleri temizlenir", set(d_) <= {"boot", "sinama", "bastir", "girdi"}, str(set(d_)))
# dosyadaki sinama kaydını silmek 'engel yok' kararı VERMEZ: süreç kendi taramasını yapar
ds.temizle()
sayac2 = {"tara": 0}
_t0_, _tm0_, _bs0_ = ds.tara, ds.tarayici_mi, ds.baslik_simdi


def _sahte_tara2(k_, baslik=None, kapi=False):
    sayac2["tara"] += 1
    return None, False


ds.tara, ds.tarayici_mi, ds.baslik_simdi = _sahte_tara2, (lambda k_: True), (lambda k_: "x")
og_ = [oge("check box", "I'm not a robot", 1)]
ds.kaydet("arka:44", ds.incele(og_, "x", {}), og_, baslik="x")
dosya_yaz({"boot": ds._boot_id(), "sinama": {}, "bastir": {}, "girdi": {}})
ds.hazir_oku("arka:44", "x")
kontrol("O1: dosyadan sınama kaydını silmek kapıyı açmaz: süreç kendi taramasını yapar", sayac2["tara"] == 1, str(sayac2))
ds.tara, ds.tarayici_mi, ds.baslik_simdi = _t0_, _tm0_, _bs0_
ds.temizle()

print("== A) üçüncü inceleme: B1 kaydırma/girdi sonrası kutular bayatlamaz (kirli kayıt)")
ds.temizle()
yeni_kutu = {"v": [10, 10, 100, 20]}


def _tara_b1(k_, baslik=None, kapi=False):
    """Sahte tarama: sayfanın o anki kutusunu yazar (kaydırılınca kutu yer değiştirir)."""
    sayac2["tara"] += 1
    t0_ = time.monotonic()
    if mod_b1["okunamaz"]:
        return None, False
    og2 = [{**oge("check box", "I'm not a robot", 1), "kutu": list(yeni_kutu["v"])}]
    sn_ = ds.incele(og2, "x", {})
    ds.kaydet(k_, sn_, og2, baslik="x", simdi=t0_)
    return sn_, True


mod_b1 = {"okunamaz": False}
sayac2["tara"] = 0
ds.tara, ds.tarayici_mi, ds.baslik_simdi = _tara_b1, (lambda k_: True), (lambda k_: "x")
try:
    _tara_b1("arka:45")
    sayac2["tara"] = 0
    d_, ok_ = ds.hazir_oku("arka:45", "x")
    kontrol("B1: girdi YOKKEN taze kayıt yeniden taranmadan kullanılır", sayac2["tara"] == 0 and d_ is not None, str(sayac2))
    ds.girdi_oldu("arka:99")
    ds.hazir_oku("arka:45", "x")
    kontrol("B1: başka pencereye girdi bu pencerenin kaydını kirletmez", sayac2["tara"] == 0, str(sayac2))
    ds.girdi_oldu("arka:45")  # kaydırma / tuş / pencere boyutu: girdi_oldu(pencere)
    yeni_kutu["v"] = [10, 400, 100, 20]  # sayfa kaydı: kutu aşağı indi
    d_, ok_ = ds.hazir_oku("arka:45", "x")
    kontrol("B1: girdiden SONRA kayıt yeniden taranır ve kutular güncellenir", sayac2["tara"] == 1 and ok_ and
            d_["kutular"] == [[10, 400, 100, 20]], f"{sayac2} {d_}")
    kontrol("B1: eski konum artık sınama değil, yeni konum sınama",
            ds.nokta_engeli("arka:45", 50, 20) is None and ds.nokta_engeli("arka:45", 50, 410) is not None)
    # masaüstü kipi / pencere bilinmeyen girdi (JOKER): tüm pencereler kirli
    sayac2["tara"] = 0
    ds.girdi_oldu(None)
    ds.hazir_oku("arka:45", "x")
    kontrol("B1: pencere bilinmeyen girdi (masaüstü kipi, k=None) TÜM kayıtları kirletir", sayac2["tara"] == 1, str(sayac2))
    # girdi kaydı dosyaya da gider (başka süreç/MCP aynı kirliliği görür)
    ds.girdi_oldu("arka:45")
    with ds._depo() as d_:
        kontrol("B1: girdi zamanı dosyada (süreçler arası): tarayıcı penceresi", "arka:45" in d_["girdi"], str(d_["girdi"]))
    # yeniden tarama OKUNAMAZSA eski kutulara güvenilmez: o pencerede TÜM fare girdisi reddedilir
    mod_b1["okunamaz"] = True
    ds.girdi_oldu("arka:45")
    d_, ok_ = ds.hazir_oku("arka:45", "x")
    kontrol("B1: kirli kayıt yeniden okunamadı → durum kirli=True", d_ is not None and d_.get("kirli") and not ok_, str(d_))
    kontrol("B1: okunamayan kirli pencerede kutu DIŞI nokta bile reddedilir (page_wide gibi)",
            ds.nokta_engeli("arka:45", 900, 900) is not None and ds.nokta_engeli("arka:45", 1, 1, ["Kaydet"]) is not None)
    kontrol("B1: kirli+okunamadı: ref/öge yolu (girdi_engeli kayit=) de reddeder",
            ds.girdi_engeli("arka:45", oge={"rol": "button"}, baslik="x", kayit=d_) is not None)
    kontrol("B1: kirli+okunamadı klavye: Tab sonrası girdi / tek başına Boşluk reddedilir, PageDown serbest",
            ds.klavye_engeli("arka:45", dizi=["tab", "space"]) is not None and ds.klavye_engeli("arka:45", dizi=["space"]) is not None and
            ds.klavye_engeli("arka:45", dizi=["pagedown"]) is None)
finally:
    ds.tara, ds.tarayici_mi, ds.baslik_simdi = _t0_, _tm0_, _bs0_
    ds.temizle()

# kaydırma / tuş / pencere yönetimi çekirdekte girdi_oldu(pencere) çağırır
from deskhand import eylem as _ey  # noqa: E402
_go0 = ds.girdi_oldu
gor_ = []
ds.girdi_oldu = lambda k_=None: gor_.append(k_)


class _SahteG:
    def kapat(self):
        pass


try:
    _ey.girdi_birak(_SahteG(), "arka:46")
    _ey.girdi_birak(_SahteG())
finally:
    ds.girdi_oldu = _go0
kontrol("B1: eylem.girdi_birak girdinin gittiği pencereyi girdi_oldu'ya iletir (k yoksa None = JOKER)", gor_ == ["arka:46", None], str(gor_))

print("== A) üçüncü inceleme: O2/O3 klavye (okunamayan tarayıcı, odak bilinmiyor), KÜÇÜK-1 ham tuş kodu")
ds.temizle()
_t0_, _tm0_, _bs0_ = ds.tara, ds.tarayici_mi, ds.baslik_simdi
ds.tara, ds.tarayici_mi, ds.baslik_simdi = (lambda k_, baslik=None, kapi=False: (None, False)), (lambda k_: True), (lambda k_: "x")
try:
    ret_ = {n_: ds.klavye_engeli("arka:47", dizi=d_) is not None for n_, d_ in (
        ("tab+space", ["tab", "space"]), ("space", ["space"]), ("enter", ["enter"]), ("k:57", ["k:57"]), ("x:Return", ["x:Return"]),
        ("yazı ' '", ["metin: "]), ("tab+yazı", ["tab", "metin:ab"]), ("a", ["a"]), ("tab", ["tab"]), ("pagedown", ["pagedown"]),
        ("yazı 'abc'", ["metin:abc"]))}
    kontrol("O2: okunamayan tarayıcıda Tab sonrası girdi + tek başına Boşluk/Enter (ham kod dahil) reddedilir",
            all(ret_[n_] for n_ in ("tab+space", "space", "enter", "k:57", "x:Return", "yazı ' '", "tab+yazı")), str(ret_))
    kontrol("O2: okunamayan tarayıcıda sıradan tuş/yazı/PageDown/tek Tab serbest",
            not any(ret_[n_] for n_ in ("a", "tab", "pagedown", "yazı 'abc'")), str(ret_))
    ds.tarayici_mi = lambda k_: False
    kontrol("O2: tarayıcı OLMAYAN pencerede kural yok", ds.klavye_engeli("arka:48", dizi=["tab", "space"]) is None and
            ds.klavye_engeli("arka:48", dizi=["space"]) is None)
    ds.tarayici_mi = lambda k_: True
    ds.okunamadi_kaydet("arka:49", "x")
    ds.girdi_oldu("arka:49")
    kontrol("O2: girdi_oldu `okunamadi` önbelleğini de siler", ds.okunamadi_mu("arka:49", "x") is False)
finally:
    ds.tara, ds.tarayici_mi, ds.baslik_simdi = _t0_, _tm0_, _bs0_
    ds.temizle()

ds.temizle()
og_ = [oge("check box", "I'm not a robot", 1)]
ds.kaydet("arka:50", ds.incele(og_, "x", {}), og_, baslik="x")
_bs0_ = ds.baslik_simdi
ds.baslik_simdi = lambda k_: "x"


def _odak_hata():
    raise TimeoutError("odak sorgusu yanıtsız")


try:
    o3_ = {}
    for ad_, sorgu_ in (("yok(None)", lambda: None), ("hata", _odak_hata), ("kutusuz", lambda: {"rol": "x"})):
        o3_[ad_] = [ds.klavye_engeli("arka:50", odak_sorgu=sorgu_, dizi=d_) is not None
                    for d_ in (["space"], ["enter"], ["metin:abc"], ["x:Return"], ["pagedown"], ["tab"])]
    kontrol("O3: sınama varken odak BİLİNEMİYORSA Boşluk/Enter/yazı reddedilir; PageDown/Tab serbest",
            all(v_ == [True, True, True, True, False, False] for v_ in o3_.values()), str(o3_))
    kontrol("O3: odak bilinip sınama dışındaysa Boşluk/yazı serbest",
            all(ds.klavye_engeli("arka:50", odak_sorgu=lambda: {"kutu": [500, 500, 5, 5]}, dizi=d_) is None
                for d_ in (["space"], ["metin:abc"])))
    kontrol("O3: odak sınama kutusundaysa hâlâ reddedilir",
            ds.klavye_engeli("arka:50", odak_sorgu=lambda: {"kutu": [10, 10, 100, 20]}, dizi=["a"]) is not None)
finally:
    ds.baslik_simdi = _bs0_
    ds.temizle()

print("== A) üçüncü inceleme: B2 masaüstü kipinde pencere değişimi (sahte arka uç)")


class _AuB2:
    """EKRAN kipi sahte arka ucu: fare() ilk `dogru` çağrıda pencere A, sonra B (üstteki pencere kapandı/değişti)."""
    ad = "sahte"

    def __init__(self, degis_sonra):
        self.say, self.degis = 0, degis_sonra

    def fare(self):
        self.say += 1
        return (500, 500, "A" if self.say <= self.degis else "B")

    def geometri(self, k_):
        return (0, 0, 1000, 1000)

    def ekran_alani(self):
        return (0, 0, 1000, 1000)

    def one_getir(self, k_):
        pass


class _GB2:
    def __init__(self):
        self.gidenler = []
        self.etiket, self.gizli, self.onayli, self.son_fare, self.onay_hedefi = "t", False, False, None, None
        self.kesildi = None

    def kapat(self):
        pass

    def gonder(self, k_, desen, *komutlar):
        self.gidenler.extend(komutlar)

    ham = zorla = gonder

    def izle(self, *a_, **kw_):
        pass

    def izle_bitir(self):
        pass


_ey_yedek = {n_: getattr(_ey, n_) for n_ in ("_au", "insan_dogrulama_ekran", "imlec_alti_denetle", "onay_hedefi_dogrula",
                                              "hassas_nokta", "nokta_metni", "dur_denetle", "girdi_al")}
from deskhand import guvenlik as _gv  # noqa: E402
_sim0_ = _gv.sistem_istemi_mi
_gv.sistem_istemi_mi = lambda w_: False
for n_ in ("insan_dogrulama_ekran", "imlec_alti_denetle", "onay_hedefi_dogrula", "hassas_nokta", "dur_denetle"):
    setattr(_ey, n_, lambda *a_, **kw_: None)
_ey.nokta_metni = lambda *a_, **kw_: []
_g_hedef = {}
_ey.girdi_al = lambda *a_, **kw_: _g_hedef["g"]
from deskhand.arka_uc import EKRAN as _EKR  # noqa: E402
try:
    # (1) kapıdan hemen sonra pencere zaten değişmiş → Dur 3, hiçbir şey tıklanmadı
    au_ = _AuB2(1)  # çözümleme A, kapı sonrası denetim B
    _ey._au = lambda: au_
    g_ = _GB2()
    try:
        _ey.tikla_ic(g_, _EKR, None, 500, 500, "sol")
        kod_ = 0
    except hata.Dur as e_:
        kod_ = e_.kod
    kontrol("B2: kapıdan hemen sonra imlecin altındaki pencere değiştiyse → Dur 3, tık gitmedi",
            kod_ == 3 and not any(c_.startswith("click") for c_ in g_.gidenler), f"{kod_} {g_.gidenler}")
    # (2) çift tık: BİRİNCİ tıktan sonra pencere değişir → ikinci tık GİTMEZ (tek tek gönderilir)
    for dugme_, beklenen_ in (("cift", 1), ("uclu", 1)):
        au_ = _AuB2(2)  # 1: tikla_ic w çözümü, 2: kapı sonrası denetim; 3.: ilk tıktan önce → B
        au_.degis = 3  # w çözümü + kapı sonrası + ilk tık öncesi = A; ikinci tık öncesi = B
        _ey._au = lambda au_=au_: au_
        g_ = _GB2()
        try:
            _ey.tikla_ic(g_, _EKR, None, 500, 500, dugme_)
            kod_ = 0
        except hata.Dur as e_:
            kod_ = e_.kod
        n_tik_ = sum(c_.startswith("click") for c_ in g_.gidenler)
        kontrol(f"B2: masaüstü kipinde '{dugme_}' tık TEK TEK gider; pencere değişince kalanı gitmez (Dur 3)",
                kod_ == 3 and n_tik_ == beklenen_, f"{kod_} {g_.gidenler}")
    # (3) tekrar>1: ikinci tekrar öncesi pencere değişir
    au_ = _AuB2(0)
    au_.degis = 99
    _ey._au = lambda: au_
    g_ = _GB2()
    _ey.tikla_ic(g_, _EKR, None, 500, 500, "cift")
    kontrol("B2: pencere değişmediyse çift tık iki ayrı click olarak gider", sum(c_.startswith("click") for c_ in g_.gidenler) == 2 and
            all(len(c_.split()) == 2 for c_ in g_.gidenler if c_.startswith("click")), str(g_.gidenler))
    au_ = _AuB2(0)
    au_.degis = 4
    _ey._au = lambda: au_
    g_ = _GB2()
    try:
        _ey.tikla_ic(g_, _EKR, None, 500, 500, "sol", tekrar=3)
        kod_ = 0
    except hata.Dur as e_:
        kod_ = e_.kod
    kontrol("B2: tekrar>1: her tıktan önce pencere denetlenir (değişince kalan tekrarlar gitmez)",
            kod_ == 3 and 1 <= sum(c_.startswith("click") for c_ in g_.gidenler) < 3, f"{kod_} {g_.gidenler}")
    # (4) imleç hedefte değilse (kullanıcı oynattı) Dur 3
    class _AuImlec(_AuB2):
        def fare(self):
            self.say += 1
            return (500 if self.say < 2 else 700, 500, "A")
    au_ = _AuImlec(99)
    _ey._au = lambda: au_
    g_ = _GB2()
    try:
        _ey.tikla_ic(g_, _EKR, None, 500, 500, "sol")
        kod_ = 0
    except hata.Dur as e_:
        kod_ = e_.kod
    kontrol("B2: kapıdan sonra imleç hedef noktada değilse → Dur 3", kod_ == 3 and not any(
        c_.startswith("click") for c_ in g_.gidenler), f"{kod_} {g_.gidenler}")
    # (5) sürükleme: kapıdan sonra buttondown ÖNCESİ pencere yeniden denetlenir
    au_ = _AuB2(1)  # w1 çözümü A, kapı sonrası denetim B
    _ey._au = lambda: au_
    g_ = _GB2()
    _g_hedef["g"] = g_
    a_ = type("A", (), dict(kimlik=_EKR, baslik=None, x1=500.0, y1=500.0, x2=600.0, y2=500.0, dugme="sol", sure=0.05,
                            onayli=False))()
    try:
        _ey.k_surukle(a_)
        kod_ = 0
    except hata.Dur as e_:
        kod_ = e_.kod
    kontrol("B2: sürüklemede kapıdan sonra pencere değiştiyse buttondown GİTMEZ (Dur 3)",
            kod_ == 3 and not any(c_.startswith("buttondown") for c_ in g_.gidenler), f"{kod_} {g_.gidenler}")
finally:
    for n_, v_ in _ey_yedek.items():
        setattr(_ey, n_, v_)
    _gv.sistem_istemi_mi = _sim0_
    ds.temizle()

# ================================================================ güvenlik: görünmez masaüstü
from deskhand import api, masaustu  # noqa: E402

if not (shutil.which("firefox") and shutil.which("Xvfb")):
    print("atlandı (B): firefox ya da Xvfb yok")
    print(f"\n{gecen}/{toplam} geçti")
    sys.exit(0 if gecen == toplam else 1)
import web_tarayici as wt  # noqa: E402
from deskhand.arka_uc import sec  # noqa: E402

bekci = wt.ProfilBekcisi()
acik = []


def kapat_hepsi():
    for ff_ in acik:
        try:
            ff_.kapat()
        except Exception:  # noqa: BLE001
            pass
    if masaustu.durum_oku() is not None:
        masaustu.masaustu_durdur()


atexit.register(kapat_hepsi)

d = masaustu.masaustu_baslat()
au = sec(arka_bayragi=True)
if not str(getattr(au, "ad", "")) == "sanal":
    print("DURDU: hedef görünmez masaüstü değil (arka uç:", getattr(au, "ad", "?"), ")")
    sys.exit(2)
srv = wt.Sunucu()


def arac(f, **k):
    """Çekirdek araç işlevi (ToolError → (None, hata iletisi))."""
    try:
        return f(**k), None
    except mcp_sunucu.ToolError as e:
        return None, e


def ac(sayfa):
    t0 = time.monotonic()
    ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url(sayfa))
    acik.append(ff)
    bekle(lambda: sayfa and (lambda b: b and "Firefox" in b)(ff.baslik()), 15)
    time.sleep(1.5)  # erişilebilirlik ağacı otursun
    return ff


def hata_kodu(e):
    return getattr(e, "kod", None)


try:
    print("== B) sahte reCAPTCHA sayfası (iframe içinde 'I'm not a robot')")
    ff = ac("sahte_recaptcha.html")
    pencere = ff.k
    gozlem_, h = arac(mcp_sunucu.observe, window=pencere, desktop="background", interactive_only=True)
    sn = (gozlem_.structured_content if gozlem_ is not None else {})
    hv = sn.get("human_verification")
    kontrol("observe: human_verification {detected, kind, window, hint}",
            hv and hv["detected"] and hv["kind"] and "request_human" in hv["hint"] and "window" in hv, f"{sn!r:.600} {h}")
    ogeler = sn.get("elements", [])
    sinama_ref = next((e["ref"] for e in ogeler if e.get("human_verification")), None)
    kul_ref = next((e["ref"] for e in ogeler if e.get("name") == "Kullanıcı adı"), None)
    kontrol("observe: sınama ögesi işaretli (human_verification), kullanıcı adı alanı DEĞİL", sinama_ref and kul_ref and
            kul_ref != sinama_ref, f"{[(e.get('name'), e.get('human_verification')) for e in ogeler]}")

    # A1: GÖZLEMSİZ (durum silinmiş) koordinat tıklaması ÇEKİRDEKTE reddedilir; CLI yolu (api.tikla) ve akış adımı da
    cx_ = cy_ = None
    _og = [o for o in ds.durum(pencere)["kutular"]] if ds.durum(pencere) else []
    if _og:
        x_, y_, w_, h_ = _og[0]
        cx_, cy_ = x_ + w_ / 2, y_ + h_ / 2
    kontrol("A2/A3: observe sınama kutusunu durum dosyasına yazdı", cx_ is not None, str(_og))
    ds.temizle()  # gözlemsiz: durum yok
    t_tara = time.monotonic()
    with api.hedef("sanal"):
        assert sec(arka_bayragi=True).ad == "sanal"
        try:
            api.tikla(pencere, cx_, cy_)
            kod_cli = 0
        except hata.Dur as e_:
            kod_cli = e_.kod
        kontrol("A1: CLI tikla (durum yok) sınama kutusuna → çıkış 18, tarama girdiden önce yapıldı", kod_cli == 18, str(kod_cli))
        olcum_ilk = time.monotonic() - t_tara
        t1 = time.monotonic()
        try:
            api.tikla(pencere, cx_ + 400, cy_ + 300)  # sınama dışı boş nokta: önbellek (tarama yok) → hızlı, ret yok
            kod2 = 0
        except hata.Dur as e_:
            kod2 = e_.kod
        olcum_ikinci = time.monotonic() - t1
        kontrol("A1: sınama dışı nokta 18 DEĞİL", kod2 != 18, str(kod2))
        print(f"   ÖLÇÜM: ilk tık (tarama + tık) {olcum_ilk:.2f} sn; sonraki tık (önbellek) {olcum_ikinci:.2f} sn")
        from deskhand import eylem as _eylem  # noqa: E402
        try:
            _eylem.adimlari_calistir(api.ns(kimlik=pencere, kimlik_ham=pencere), [f"tikla {cx_:.0f} {cy_:.0f}"],
                                     etiket="akis test", etk=None, onek="")
            kod_akis = 0
        except hata.Dur as e_:
            kod_akis = e_.kod
        kontrol("A5: akış adımı (adimlari_calistir) çekirdek kapıdan geçer → 18", kod_akis == 18, str(kod_akis))
    ds.temizle()
    ss, hh = arac(mcp_sunucu.screenshot, window=pencere, desktop="background")
    sid_ = ((ss.structured_content or {}).get("shot_id") if ss is not None else None)
    r, e = arac(mcp_sunucu.click, x=cx_, y=cy_, shot_id=sid_, desktop="background", verify=False) if sid_ else (None, "shot yok")
    kontrol("A1: gözlemsiz screenshot + koordinat tık (MCP) → 18", r is None and hata_kodu(e) == 18, f"{r!r:.200} {e}")

    ff.profil and wt.os.path.isdir(ff.profil)
    for ad_, cagri in (
            ("click(ref)", dict(f=mcp_sunucu.click, ref=sinama_ref, desktop="background")),
            ("click(text)", dict(f=mcp_sunucu.click, window=pencere, text="I'm not a robot", desktop="background")),
            ("type_text(ref)", dict(f=mcp_sunucu.type_text, text="x", ref=sinama_ref, desktop="background")),
            ("drag(from_ref)", dict(f=mcp_sunucu.drag, from_ref=sinama_ref, to_x=5, to_y=5, shot_id="yok",
                                    desktop="background"))):
        if ad_ == "drag(from_ref)":  # to_ref gerekir: aynı ögeden aynı ögeye (kapı bayrağa bakar)
            cagri = dict(f=mcp_sunucu.drag, from_ref=sinama_ref, to_ref=sinama_ref, desktop="background")
        r, e = arac(**cagri)
        kontrol(f"{ad_}: sınama ögesine REDDEDİLDİ [18], hiçbir şey gönderilmedi",
                r is None and e is not None and hata_kodu(e) == 18 and "request_human" in str(e) and
                getattr(e, "ek", None) and e.ek["human_verification"]["detected"], f"{r!r:.200} {e}")
    # ===== İKİNCİ İNCELEME B1: TÜM EKRAN KİPİ (EKRAN) kapıyı atlamasın (imlecin altındaki pencere + nokta)
    from deskhand.arka_uc import EKRAN as _EKRAN  # noqa: E402
    geo_ = au.geometri(pencere)
    sx_, sy_ = geo_[0] + cx_, geo_[1] + cy_
    ds.temizle()
    sonuc_e = {}
    with api.hedef("sanal"):
        assert sec(arka_bayragi=True).ad == "sanal"
        for ad_, f_ in (("tikla", lambda: api.tikla(_EKRAN, sx_, sy_)),
                        ("surukle", lambda: api.surukle(_EKRAN, sx_, sy_, sx_ + 40, sy_)),
                        ("metne_tikla", lambda: api.metne_tikla(_EKRAN, "I'm not a robot"))):
            try:
                f_()
                sonuc_e[ad_] = 0
            except hata.Dur as e_:
                sonuc_e[ad_] = e_.kod
        t_ek = time.monotonic()
        try:
            api.tikla(_EKRAN, sx_ + 400, sy_ + 300)  # sınama dışı boş nokta: 18 DEĞİL
            sonuc_e["disi"] = 0
        except hata.Dur as e_:
            sonuc_e["disi"] = e_.kod
        print(f"   ÖLÇÜM: EKRAN tık (pencere çözümü + önbellekli tarama) {time.monotonic() - t_ek:.2f} sn")
    kontrol("B1: EKRAN: tikla X Y sınama kutusunda → 18", sonuc_e.get("tikla") == 18, str(sonuc_e))
    kontrol("B1: EKRAN: surukle başlangıcı sınama kutusunda → 18", sonuc_e.get("surukle") == 18, str(sonuc_e))
    kontrol("B1: EKRAN: metne-tikla 'I'm not a robot' → 18", sonuc_e.get("metne_tikla") == 18, str(sonuc_e))
    kontrol("B1: EKRAN: sınama dışı nokta 18 DEĞİL", sonuc_e.get("disi") != 18, str(sonuc_e))
    ds.temizle()
    ss2, hh2 = arac(mcp_sunucu.screenshot, desktop="background")  # PENCERE VERMEDEN tüm ekran
    sc_ = (ss2.structured_content or {}) if ss2 is not None else {}
    ea_ = au.ekran_alani()
    olcek_ = min(1.0, 1280 / max(ea_[2] - ea_[0], ea_[3] - ea_[1]))
    r, e = arac(mcp_sunucu.click, x=sx_ * olcek_, y=sy_ * olcek_, shot_id=sc_.get("shot_id"), desktop="background",
                verify=False) if sc_.get("shot_id") else (None, f"shot yok {sc_!r:.200} {hh2}")
    kontrol("B1: EKRAN: screenshot() pencere vermeden + click(x,y,shot_id) → 18", r is None and hata_kodu(e) == 18,
            f"{r!r:.200} {e}")
    ds.temizle()

    # ===== BÜYÜK-2: Tab odağı kutuya taşıyıp devam eden diziler tek çağrıda reddedilir (odak başta sınama dışı)
    arac(mcp_sunucu.observe, window=pencere, desktop="background")
    for ad_, cagri in (("press_key 'tab space'", dict(f=mcp_sunucu.press_key, window=pencere, keys="tab space", desktop="background")),
                       ("press_key 'tab tab tab space'", dict(f=mcp_sunucu.press_key, window=pencere, keys="tab tab tab space",
                                                              desktop="background")),
                       ("type_text TAB+boşluk", dict(f=mcp_sunucu.type_text, window=pencere, text="\t ", desktop="background")),
                       ("type_text TAB+AB12C", dict(f=mcp_sunucu.type_text, window=pencere, text="\tAB12C",
                                                    desktop="background"))):
        r, e = arac(**cagri)
        kontrol(f"B2: {ad_} → [18] (Tab sonrası girdi), hiçbir şey gönderilmedi",
                r is None and hata_kodu(e) == 18, f"{r!r:.200} {e}")
    with api.hedef("sanal"):
        assert sec(arka_bayragi=True).ad == "sanal"
        kodlar_ = {}
        for ad_, f_ in (("tus", lambda: api.tus(pencere, "tab space")), ("yaz", lambda: api.yaz(pencere, "\tAB12C")),
                        ("bas", lambda: api.bas(pencere, "tab space", 0.2))):
            try:
                f_()
                kodlar_[ad_] = 0
            except hata.Dur as e_:
                kodlar_[ad_] = e_.kod
    kontrol("B2: CLI tus/yaz/bas çekirdek kapıdan geçer → 18", all(v_ == 18 for v_ in kodlar_.values()), str(kodlar_))

    # ===== batch: [18] adım hata nesnesinde human_verification
    ds.temizle()
    arac(mcp_sunucu.observe, window=pencere, desktop="background")
    rb, eb = arac(mcp_sunucu.batch, steps=[mcp_sunucu.Adim(tool="click", args={"ref": sinama_ref})], desktop="background")
    sb = (rb.structured_content or {}) if rb is not None else {}
    kontrol("batch: [18] adımı → adım ve error nesnesinde human_verification",
            sb.get("steps") and (sb["steps"][0].get("human_verification") or {}).get("detected") and
            (sb.get("error", {}).get("human_verification") or {}).get("detected") and sb["error"]["code"] == 18,
            f"{sb!r:.500} {eb}")

    # A4: Tab + Space ile sınama kutusunu işaretleme kapalı: odak sınama kutusuna gelince tuş reddedilir
    rr = []
    for _i in range(4):
        r_, e_ = arac(mcp_sunucu.press_key, window=pencere, keys="Tab", desktop="background")
        rr.append(hata_kodu(e_) if e_ is not None else 0)
        if e_ is not None:
            break
    kontrol("A4: Tab ile odak sınama kutusuna gelince tuş [18] ile reddedilir (Tab+Space ile işaretlenemez)",
            18 in rr, str(rr))
    r, e = arac(mcp_sunucu.press_key, window=pencere, keys="space", desktop="background")
    kontrol("A4: odak sınama kutusundayken Space → [18]", r is None and hata_kodu(e) == 18, f"{r!r:.200} {e}")
    # sayfanın geri kalanı kullanılabilir
    r, e = arac(mcp_sunucu.type_text, text="deneme", ref=kul_ref, desktop="background", verify=False)
    kontrol("sayfanın geri kalanı: kullanıcı adı alanına yazı GİDER (sınama dışı)", r is not None, str(e))
    r, e = arac(mcp_sunucu.read_text, window=pencere, source="web", desktop="background")
    kontrol("read_text(web): okunabilir ve human_verification taşır", r is not None and
            (r.get("human_verification") or {}).get("detected"), f"{r!r:.300} {e}")
    # ===== ÜÇÜNCÜ İNCELEME B1: kaydırma / tuş / pencere boyutu sınama kaydını KİRLETİR; sonraki girdi yeniden tarar
    g0_ = au.geometri(pencere)
    with api.hedef("sanal"):
        assert sec(arka_bayragi=True).ad == "sanal"
        for ad_, f_ in (("api.kaydir", lambda: api.kaydir(pencere, "down", 1)),
                        ("api.tus pagedown", lambda: api.tus(pencere, "pagedown")),
                        ("api.pencere_yonet boyut", lambda: api.pencere_yonet(pencere, "boyut", g=g0_[2] - 40, h=g0_[3] - 40)),
                        ("MCP scroll", lambda: mcp_sunucu.scroll(window=pencere, direction="down", amount=1, desktop="background"))):
            ds.temizle()
            arac(mcp_sunucu.observe, window=pencere, desktop="background")
            d0_ = ds.durum(pencere)
            z0_ = d0_["zaman"] if d0_ else None
            try:
                f_()
            except (hata.Dur, mcp_sunucu.ToolError) as e_:
                print(f"   ({ad_}: {type(e_).__name__} {e_})")
            kontrol(f"B1: {ad_} sonrası sınama kaydı kirli (son girdi > kayıt zamanı)",
                    z0_ is not None and ds.son_girdi(pencere) > z0_, f"{z0_} {ds.son_girdi(pencere)}")
            d1_, ok1_ = ds.hazir_oku(pencere)
            kontrol(f"B1: {ad_} sonrası hazir_oku kaydı YENİDEN tarar (kayıt zamanı ilerler)",
                    ok1_ and d1_ is not None and d1_["zaman"] > z0_ and not d1_.get("kirli"), f"{d1_} {ok1_}")
        if tuple(au.geometri(pencere)) != tuple(g0_):
            api.pencere_yonet(pencere, "boyut", g=g0_[2], h=g0_[3])  # sonraki testler için eski boyut
        ds.temizle()
        # KÜÇÜK-1: ham tuş kodları < 0x100 (BTN_* kodları 0x100+ fare düğmesidir)
        kodlar_k = {}
        for kod_ in ("k:57", "k:255", "k:256", "k:272", "k:0", "k:abc"):
            try:
                _ey.tus_coz(kod_)
                kodlar_k[kod_] = 0
            except hata.Dur as e_:
                kodlar_k[kod_] = e_.kod
        kontrol("KÜÇÜK-1: k: ham tuş kodu 1-255 geçer; 256+ (BTN_LEFT=272), 0 ve sayı olmayan Dur(1)",
                kodlar_k == {"k:57": 0, "k:255": 0, "k:256": 1, "k:272": 1, "k:0": 1, "k:abc": 1}, str(kodlar_k))

    ff.kapat()
    acik.remove(ff)
    ds.temizle()

    print("== B) sahte Turnstile ara sayfası (başlık 'Just a moment...')")
    ff = ac("sahte_turnstile.html")
    pencere = ff.k
    bekle(lambda: "Just a moment" in ff.baslik(), 10)
    gozlem_, h = arac(mcp_sunucu.observe, window=pencere, desktop="background")
    sn = gozlem_.structured_content if gozlem_ is not None else {}
    hv = sn.get("human_verification")
    kontrol("observe: ara sayfa algılandı (cloudflare_interstitial ya da sınama çerçevesi)",
            hv and hv["detected"], f"{sn!r:.400} {h}")
    r, e = arac(mcp_sunucu.press_key, window=pencere, keys="space", desktop="background")
    kontrol("press_key (hedefsiz klavye) ara sayfada REDDEDİLDİ [18]", r is None and hata_kodu(e) == 18, f"{r!r:.200} {e}")
    r, e = arac(mcp_sunucu.type_text, text="x", window=pencere, desktop="background")
    kontrol("type_text (hedefsiz) ara sayfada REDDEDİLDİ [18]", r is None and hata_kodu(e) == 18, f"{r!r:.200} {e}")

    # ============================================================ C) request_human
    print("== C) request_human (sahte/yalıtık panel; bildirim SAHTE)")
    bildirimler = []
    from deskhand import mesgul  # noqa: E402
    mesgul.bildir = lambda baslik, govde, kritik=True, sure=30: bildirimler.append((baslik, govde, kritik)) or True
    mesgul.ekran_korumasi = lambda p=None, o=None: None  # kullanıcı oyunda DEĞİL (gerçek KWin'e sorulmaz)
    mcp_sunucu.ON_BEKLE_SN = 1.0
    mcp_sunucu.DEVIR_BEKLEME_ARA = 0.0  # önce sıklık sınırı kapalı (kendi testi aşağıda)
    onay.panel_kaydet()  # test süreci panel gibi davranır (onay kanalı); gerçek panele dokunulmaz

    def panel_yanit(karar, bekle_sn=8.0):
        """Panel taklidi: tur=devir isteği görünce yanıtla (izin=Bitti, red=Vazgeç)."""
        gorulen = {}

        def calis():
            bitis = time.monotonic() + bekle_sn
            while time.monotonic() < bitis:
                for b in onay.bekleyenler():
                    if b.get("tur") == "devir":
                        gorulen.update(b)
                        time.sleep(0.3)
                        onay.yanitla(b["id"], karar)
                        return
                time.sleep(0.05)
        t = threading.Thread(target=calis, daemon=True)
        t.start()
        return t, gorulen

    # C1: kullanıcı Bitti → resolved (sınama hâlâ sayfada: still_detected=True ile)
    t, gorulen = panel_yanit("izin")
    r, e = arac(mcp_sunucu.request_human, reason="reCAPTCHA çözülmeli", window=pencere, timeout_s=20, desktop="background")
    t.join(3)
    kontrol("request_human: panelde görünür istek (tur=devir, masaüstü arka, neden)", gorulen.get("tur") == "devir" and
            gorulen.get("masaustu") == "arka" and "reCAPTCHA" in gorulen.get("ayrinti", ""), str(gorulen))
    kontrol("request_human: KDE bildirimi (sahte) gönderildi, KRİTİK; sayfa başlığı YOK, yalnız site alan adı (D)",
            bildirimler and "reCAPTCHA" in bildirimler[-1][1] and bildirimler[-1][2] and
            "Mozilla" not in bildirimler[-1][1] and "Just a moment" not in bildirimler[-1][1], str(bildirimler))
    kontrol("request_human: Bitti → status=resolved (resolved_by=user)", r is not None and r.get("status") == "resolved" and
            r.get("resolved_by") == "user", f"{r!r:.300} {e}")
    kontrol("request_human: sınama işareti hâlâ varsa still_detected=True (ajan yeniden bakmalı)",
            r is not None and r.get("still_detected") is True)

    kontrol("B8: günlükte 'devir-tamam' etiketi ('onay izin' DEĞİL)", "onay devir-tamam" in _gunluk_metni() and
            "onay izin | arka sanal" not in _gunluk_metni(), _gunluk_metni()[-300:])
    # C3: Bitti sonrası aynı sınama için uyarı/yeniden çağrı bastırılır
    r2, e2 = arac(mcp_sunucu.request_human, reason="tekrar", window=pencere, timeout_s=20, desktop="background")
    kontrol("C3: Bitti sonrası AYNI sınama için yeniden çağrı kullanıcıyı çağırmaz (suppressed)",
            r2 is not None and r2.get("suppressed") is True and r2.get("waited_s") == 0.0, f"{r2!r:.200} {e2}")
    ds.temizle()
    # C2: Vazgeç → declined
    t, gorulen = panel_yanit("red")
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=20, desktop="background")
    t.join(3)
    kontrol("request_human: Vazgeç → status=declined", r is not None and r.get("status") == "declined", f"{r!r:.200} {e}")

    # B7: ret sonrası aynı pencere için 60 sn sıklık sınırı
    mcp_sunucu.DEVIR_BEKLEME_ARA = 60.0
    r_, e_ = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=20, desktop="background")
    kontrol("B7: reddedilen pencere için 60 sn içinde yeni istek ret (retry_after_s)",
            r_ is not None and r_.get("status") == "declined" and r_.get("retry_after_s", 0) > 0, f"{r_!r:.200} {e_}")
    mcp_sunucu.DEVIR_BEKLEME_ARA = 0.0
    mcp_sunucu._SON_DEVIR_RED.clear()
    # C3: zaman aşımı
    t0 = time.monotonic()
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=2, desktop="background")
    kontrol("request_human: kimse gelmez → status=timeout", r is not None and r.get("status") == "timeout" and
            time.monotonic() - t0 < 8, f"{r!r:.200} {e}")

    # C4: bekleme sırasında bu masaüstüne ajan girdisi reddedilir ([7] onay bekleniyor); ajan isteği kapatamaz
    def bekleme_sirasinda():
        time.sleep(1.0)
        r_, e_ = arac(mcp_sunucu.press_key, window=pencere, keys="a", desktop="background")
        bekleme_sirasinda.sonuc = (r_, e_)
    bekleme_sirasinda.sonuc = None
    th = threading.Thread(target=bekleme_sirasinda, daemon=True)
    th.start()
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=3, desktop="background")
    th.join(5)
    br, be = bekleme_sirasinda.sonuc or (None, None)
    kontrol("bekleme sırasında ajan girdisi reddedilir (ajan sonucu kendi değiştiremez)", br is None and be is not None and
            hata_kodu(be) in (7, 18), f"{br!r:.200} {be}")
    kontrol("bekleme bitince devir kaydı temiz (yeniden istenebilir)", not ds.devir_acik(pencere))

    # B2: sayfa OKUNAMAZSA 'kayboldu' sayılmaz (geçici a11y hatası yanlış challenge_cleared üretmesin)
    ff.kapat()
    acik.remove(ff)
    ds.temizle()
    mcp_sunucu._SON_DEVIR_RED.clear()
    ff = ac("sahte_recaptcha.html")
    pencere = ff.k
    arac(mcp_sunucu.observe, window=pencere, desktop="background")
    onay.KONTROL_ARALIK = 0.5
    mcp_sunucu.DEVIR_ARALIK_SAYISI = 2
    _tara0 = ds.tara
    ds.tara = lambda k_, baslik=None: (None, False)  # a11y okunamıyor
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=10, desktop="background")
    ds.tara = _tara0
    kontrol("B2: sayfa okunamayınca challenge_cleared DEĞİL (timeout)", r is not None and r.get("status") == "timeout",
            f"{r!r:.300} {e}")
    ff.kapat()
    acik.remove(ff)

    # C4: kendiliğinden geçen ara sayfa (adres aynı, çerçeve kalkar): kullanıcı çağrılmadan resolved
    print("== C) kendiliğinden geçen sınama / adres değişimi")
    ds.temizle()
    mcp_sunucu._SON_DEVIR_RED.clear()
    mcp_sunucu.ON_BEKLE_SN = 12.0
    bildirimler.clear()
    ff = ac("sahte_kendi_gecen.html")
    pencere = ff.k
    arac(mcp_sunucu.observe, window=pencere, desktop="background")
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=60, desktop="background")
    kontrol("C4: kendiliğinden geçen ara sayfa → resolved (challenge_cleared), bildirim/diyalog ÇIKMADI",
            r is not None and r.get("status") == "resolved" and r.get("resolved_by") == "challenge_cleared" and not bildirimler,
            f"{r!r:.300} {e} {bildirimler}")
    ff.kapat()
    acik.remove(ff)

    # B3: sayfa değişerek (ADRES değişir) sınama kayboldu → challenge_cleared SAYILMAZ
    ds.temizle()
    mcp_sunucu.ON_BEKLE_SN = 1.0
    ff = ac("sahte_yonlendir.html")
    pencere = ff.k
    arac(mcp_sunucu.observe, window=pencere, desktop="background")
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=14, desktop="background")
    kontrol("B3: adres değişince sınama kalkması challenge_cleared SAYILMAZ (timeout)",
            r is not None and r.get("status") == "timeout", f"{r!r:.300} {e}")
    ff.kapat()
    acik.remove(ff)
    ds.temizle()

    # C1/C2 entegrasyon: video+sınama sayfası; 'Just a Moment (Official Video)' başlığı
    print("== B) yanlış pozitif sayfaları")
    mcp_sunucu._SON_DEVIR_RED.clear()
    ff = ac("sahte_cok_cerceve.html")
    pencere = ff.k
    g_, h = arac(mcp_sunucu.observe, window=pencere, desktop="background")
    sn = g_.structured_content if g_ is not None else {}
    oynat = next((x["ref"] for x in sn.get("elements", []) if x.get("name") == "Oynat"), None)
    isaretli_ = [x.get("name") for x in sn.get("elements", []) if x.get("human_verification")]
    kontrol("C1: video iframe'indeki 'Oynat' düğmesi sınama olarak işaretlenmedi", oynat and "Oynat" not in isaretli_,
            str(isaretli_))
    r, e = arac(mcp_sunucu.click, ref=oynat, desktop="background", verify=False) if oynat else (None, "ref yok")
    kontrol("C1: video iframe'indeki düğmeye tık 18 DEĞİL", r is not None or hata_kodu(e) != 18, str(e))
    ff.kapat()
    acik.remove(ff)
    ds.temizle()
    ff = ac("sahte_video_baslik.html")
    pencere = ff.k
    g_, h = arac(mcp_sunucu.observe, window=pencere, desktop="background")
    sn = g_.structured_content if g_ is not None else {}
    kontrol("C2: 'Just a Moment (Official Video) - YouTube' başlıklı sayfa sınama DEĞİL", g_ is not None and
            "human_verification" not in sn, f"{sn!r:.200} {h}")
    r, e = arac(mcp_sunucu.type_text, text="merhaba", window=pencere, desktop="background", verify=False)
    kontrol("C2: o sayfada klavye serbest (18 değil)", r is not None or hata_kodu(e) != 18, str(e))
    ff.kapat()
    acik.remove(ff)

    # ============================================================ blog: yanlış pozitif (gerçek sayfa)
    print("== B) blog yazısı (CAPTCHA'dan bahseder) ALGILANMAZ")
    ds.temizle()
    ff = ac("blog_captcha.html")
    gozlem_, h = arac(mcp_sunucu.observe, window=ff.k, desktop="background", interactive_only=False)
    sn = gozlem_.structured_content if gozlem_ is not None else {}
    kontrol("blog: observe human_verification YOK", gozlem_ is not None and "human_verification" not in sn, f"{sn!r:.300} {h}")
    link = next((x["ref"] for x in sn.get("elements", []) if x.get("name") == "reCAPTCHA nedir?"), None)
    r, e = arac(mcp_sunucu.click, ref=link, desktop="background", verify=False) if link else (None, "link yok")
    kontrol("blog: 'reCAPTCHA nedir?' bağlantısına tık serbest (18 değil)", r is not None or hata_kodu(e) != 18, str(e))
    ff.kapat()
    acik.remove(ff)
finally:
    kapat_hepsi()

f_ = bekci.fark()
kontrol("kullanıcı Firefox profil kökü değişmedi", not f_, str(f_))
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
