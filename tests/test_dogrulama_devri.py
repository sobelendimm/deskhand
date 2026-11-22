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
kontrol("durum yokken 'I'm not a robot' metin hedefi YİNE reddedilir",
        ds.girdi_engeli(K, ad="I'm not a robot", baslik="x") is not None)
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
