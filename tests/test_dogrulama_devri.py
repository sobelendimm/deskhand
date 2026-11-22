"""İnsan doğrulaması (CAPTCHA) devri testleri (docs/ARCHITECTURE.md §13). CAPTCHA ÇÖZÜLMEZ: algıla → girdiyi reddet [17] →
kullanıcıya devret (request_human) → çözülünce devam.

A) Saf birim: algı kalıpları/adresleri/başlıkları, yanlış pozitif örnekleri, girdi kapısı mantığı.
B) GÖRÜNMEZ arka plan masaüstünde (Xvfb) YALITIK Firefox (geçici profil; tests/yardimci/web_tarayici.py) 127.0.0.1'den
   sentetik sayfalar açar (sahte reCAPTCHA / Turnstile iframe'i ve metni; DIŞ AĞ YOK, gerçek CAPTCHA sitesi YOK):
   observe → human_verification; sınama ögesine click/type_text/press_key/drag → [17] ve HİÇBİR GİRDİ gönderilmez
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
s = ds.incele([oge("check box", "hCaptcha checkbox", cerceve=1), oge("entry", "Kullanıcı adı"), oge("link", "Gizlilik", 1)],
              "x", {"cerceveler": [{"ad": "", "adres": "https://newassets.hcaptcha.com/captcha/v1/x/hcaptcha.html"}]})
kontrol("çerçeve adresi + ögeler: tür hcaptcha; çerçevedeki ögeler işaretli, kullanıcı adı alanı DEĞİL",
        s and s["kind"] == "hcaptcha" and 0 in s["elements"] and 2 in s["elements"] and 1 not in s["elements"], str(s))
s = ds.incele([oge("static", "Verifying...")], "Just a moment...", {})
kontrol("başlık 'Just a moment...' → cloudflare_interstitial, sayfanın tamamı", s and s["kind"] ==
        "cloudflare_interstitial" and s["page_wide"], str(s))
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
kontrol("ara sayfa başlığı: hedefsiz klavye reddedilir", ds.girdi_engeli("arka:2", klavye=True, baslik="Just a moment...") is not None)
kontrol("TTL dolunca durum kalkar", ds.durum(K, simdi=time.monotonic() + ds.TTL + 1) is None)
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
        kontrol(f"{ad_}: sınama ögesine REDDEDİLDİ [17], hiçbir şey gönderilmedi",
                r is None and e is not None and hata_kodu(e) == 17 and "request_human" in str(e) and
                getattr(e, "ek", None) and e.ek["human_verification"]["detected"], f"{r!r:.200} {e}")
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
    kontrol("press_key (hedefsiz klavye) ara sayfada REDDEDİLDİ [17]", r is None and hata_kodu(e) == 17, f"{r!r:.200} {e}")
    r, e = arac(mcp_sunucu.type_text, text="x", window=pencere, desktop="background")
    kontrol("type_text (hedefsiz) ara sayfada REDDEDİLDİ [17]", r is None and hata_kodu(e) == 17, f"{r!r:.200} {e}")

    # ============================================================ C) request_human
    print("== C) request_human (sahte/yalıtık panel; bildirim SAHTE)")
    bildirimler = []
    from deskhand import mesgul  # noqa: E402
    mesgul.bildir = lambda baslik, govde, kritik=True, sure=30: bildirimler.append((baslik, govde, kritik)) or True
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
    kontrol("request_human: KDE bildirimi (sahte) gönderildi", bildirimler and "reCAPTCHA" in bildirimler[-1][1] and
            bildirimler[-1][2], str(bildirimler))
    kontrol("request_human: Bitti → status=resolved (resolved_by=user)", r is not None and r.get("status") == "resolved" and
            r.get("resolved_by") == "user", f"{r!r:.300} {e}")
    kontrol("request_human: sınama işareti hâlâ varsa still_detected=True (ajan yeniden bakmalı)",
            r is not None and r.get("still_detected") is True)

    # C2: Vazgeç → declined
    t, gorulen = panel_yanit("red")
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=20, desktop="background")
    t.join(3)
    kontrol("request_human: Vazgeç → status=declined", r is not None and r.get("status") == "declined", f"{r!r:.200} {e}")

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
            hata_kodu(be) in (7, 17), f"{br!r:.200} {be}")
    kontrol("bekleme bitince devir kaydı temiz (yeniden istenebilir)", not ds.devir_acik(pencere))

    # C5: sınama sayfadan kalkınca (ana sayfa → sınamasız sayfa) otomatik resolved
    ff.kapat()
    acik.remove(ff)
    ds.temizle()
    ff = ac("sahte_recaptcha.html")
    pencere = ff.k
    arac(mcp_sunucu.observe, window=pencere, desktop="background")
    onay.KONTROL_ARALIK = 0.5
    mcp_sunucu.DEVIR_ARALIK_SAYISI = 2

    def sayfayi_degistir():
        time.sleep(1.5)
        # sayfanın kendi yönlendirmesi yok: adres çubuğu yerine pencereyi kapatmak sınamayı kaldırır (pencere yok → algı yok)
        ff.au.kapat(ff.k)
    th = threading.Thread(target=sayfayi_degistir, daemon=True)
    th.start()
    r, e = arac(mcp_sunucu.request_human, reason="x", window=pencere, timeout_s=30, desktop="background")
    th.join(5)
    kontrol("sınama işareti kaybolunca status=resolved (resolved_by=challenge_cleared)",
            r is not None and r.get("status") == "resolved" and r.get("resolved_by") == "challenge_cleared", f"{r!r:.300} {e}")
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
    kontrol("blog: 'reCAPTCHA nedir?' bağlantısına tık serbest (17 değil)", r is not None or hata_kodu(e) != 17, str(e))
    ff.kapat()
    acik.remove(ff)
finally:
    kapat_hepsi()

f_ = bekci.fark()
kontrol("kullanıcı Firefox profil kökü değişmedi", not f_, str(f_))
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
