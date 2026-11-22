"""İnsan doğrulaması (CAPTCHA) sınamalarını ALGILAR; ÇÖZMEZ, atlatmaz (docs/ARCHITECTURE.md §12).

Politika (değişmez): "insan olduğunuzu doğrulayın" sınamaları görsel, sesli ya da başka yolla çözülmez. Bu modül yalnız
ALGILAR; araç katmanı (mcp_sunucu) algılanınca ajan girdisini REDDEDER (kod 18), `request_human` kullanıcıya DEVRETTİĞİNDE
çözülünce DEVAM edilir.

Algı kaynakları (yanlış pozitif düşük: yalnız metin geçmesi YETMEZ, etkileşimli öge/çerçeve + kalıp birlikte aranır):
  1. Pencere ya da sayfa başlığı: "Just a moment…" / "Bir dakika lütfen…" / "Attention Required" / "Verifying you are human"
     (Cloudflare ara sayfası) → tüm sayfa sınamadır (kind=cloudflare_interstitial).
  2. Gömülü belge (iframe) adresi: google.com/recaptcha, hcaptcha.com, challenges.cloudflare.com, arkoselabs/funcaptcha,
     geetest… (görünmez/`size=invisible` reCAPTCHA v3 rozeti sınama DEĞİLDİR). Algılanınca çerçeve içindeki tüm
     etkileşimli ögeler sınama sayılır.
  3. Öge adı + rol: onay kutusu/düğme/kaydırıcı ("I'm not a robot", "Ben robot değilim", "Verify you are human", "İnsan
     olduğunuzu doğrulayın", sürükle-bulmaca "Slide to verify"…) ya da satıcı adı (reCAPTCHA, hCaptcha, Turnstile,
     Arkose…); çerçeve içindeyse her rol. Üst düzey bağlantı/başlık/paragraf (blog yazısı, belge) SAYILMAZ.
  4. OCR satırı: YALNIZ kısa, tek başına duran satır (≤ 8 sözcük) kalıpla eşleşirse (düşük güven).
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import threading
import time

from .i18n import _
from .ocr import katla

# ---------------------------------------------------------------- kalıplar (katla'lı metne: küçük harf, aksansız, noktalama boşluk)

BASLIK_KALIBI = re.compile(
    r"^(just a moment|bir dakika lutfen|un instant|einen moment|un momento|um momento|attention required|"
    r"verifying you are human|performing security verification|checking your browser|checking if the site connection is secure|"
    r"ddos protection by|guvenlik dogrulamasi)\b")
CDN_ADRES = re.compile(r"/cdn-cgi/|[?&]__cf_chl")  # Cloudflare ara sayfası adresi: başlık kalıbı yalnız bununla/çerçeveyle geçerli
BASLIK_UZUNLUK = 90  # daha uzun başlık "Just a moment…" ara sayfası olamaz (blog başlığı)

ROBOT_DEGIL = re.compile(
    r"\b(i m not a robot|i am not a robot|im not a robot|i am not a bot|i m not a bot|i am human|i m human|"
    r"verify you are human|verify you re human|verify that you are human|verify you are not a robot|"
    r"verify you are not a bot|verifying you are human|confirm you are human|confirm you are not a robot|"
    r"prove you are human|prove you re human|please verify you are a human|are you human|are you a human|"
    r"ben robot degilim|robot degilim|bot degilim|insan oldugunuzu dogrulay[a-z]*|"
    r"insan oldugunuzu onaylay[a-z]*|insan oldugunuzu kanitlay[a-z]*|insan oldugunuzdan emin|"
    r"ich bin kein roboter|je ne suis pas un robot|no soy un robot)\b")
SURUKLE = re.compile(
    r"\b(slide to verify|slide to complete|slide the (puzzle|slider)|drag the puzzle|"
    r"drag the piece|drag to complete|complete the puzzle to|(move|drag) the slider (to|until) (the )?(verify|complete|"
    r"fit|match|solve|unlock|puzzle|right)|kaydirarak dogrula|surukleyerek dogrula|"
    r"bulmacayi tamamla|parcayi surukle|slide to unlock to verify)\b")
SATICI_AD = re.compile(
    r"\b(re ?captcha|h ?captcha|fun ?captcha|arkose( labs)?|geetest|turnstile|captcha|"
    r"cloudflare security challenge|security challenge|challenge expires)\b")
SATICI_TURU = {"recaptcha": "recaptcha", "hcaptcha": "hcaptcha", "turnstile": "turnstile", "funcaptcha": "arkose",
               "arkose": "arkose", "arkoselabs": "arkose", "geetest": "geetest", "cloudflaresecuritychallenge": "turnstile"}

ADRES_KALIPLARI = (  # (desen, tür)
    (re.compile(r"google\.com/recaptcha/|recaptcha\.net/recaptcha/|gstatic\.com/recaptcha/", re.I), "recaptcha"),
    (re.compile(r"(?:^|[/.])hcaptcha\.com/", re.I), "hcaptcha"),
    (re.compile(r"challenges\.cloudflare\.com|/cdn-cgi/challenge-platform/", re.I), "turnstile"),
    (re.compile(r"arkoselabs\.com|funcaptcha\.(?:com|co)|arkose\.com", re.I), "arkose"),
    (re.compile(r"geetest\.com|gt4\.geetest", re.I), "geetest"),
    (re.compile(r"captcha-delivery\.com|datadome\.co/captcha|perimeterx\.net/|px-cdn\.net/.*captcha", re.I), "captcha"),
)
GORUNMEZ_ADRES = re.compile(r"[?&#]size=invisible\b|[?&]badge=|[?&#]frame=checkbox-invisible\b", re.I)  # reCAPTCHA v3 / görünmez hCaptcha

KUTU_ROLLERI = frozenset({"check box", "toggle button", "button", "push button", "switch", "toggle switch", "slider",
                          "radio button", "internal frame", "document frame", "image map", "canvas", "image", "entry"})
SURUKLE_ROLLERI = frozenset({"slider", "button", "push button", "toggle button", "image", "canvas", "internal frame"})
KALIP_ORANI = 0.6  # metinle hedeflemede kalıp, metnin en az bu kesrini kaplamalı
OCR_KISA = 8  # OCR satırı en çok bu kadar sözcük: tek başına duran etiket, paragraf değil

NEDEN_YOK = "no_challenge"

IPUCU = ("A human-verification challenge ({kind}) is on this page. Never click, type or drag in it and never try to "
         "solve it. Call request_human(reason, window): the user solves it in the Deskhand panel (or on their screen) "
         "and the call returns when it is done. The rest of the page can still be read.")


def ad_kalibi_mi(ad: str, satici: bool = False, oran: float = 0.0) -> str | None:
    """Öge adı sınama kalıbıyla eşleşiyor mu? → tür ("human_checkbox" | "slider_puzzle" | satıcı türü) | None.
    satici=False: yalnız insan-doğrulama CÜMLELERİ (metinle tıklama/yazı hedefi için yeterince özgül).
    oran: kalıp metnin en az bu kesrini kaplamalı (OCR satırında yan yana duran başka bağlantı/cümle yanlış alarm
    vermesin: "reCAPTCHA nedir? Verify you are human: a history" → kalıp 4/8 sözcük)."""
    n = katla(ad or "")
    if not n:
        return None
    toplam = max(1, len(n.split()))
    for desen, tur in ((ROBOT_DEGIL, "human_checkbox"), (SURUKLE, "slider_puzzle")):
        m = desen.search(n)
        if m and len(m.group(0).split()) / toplam >= oran:
            return tur
    if satici:
        m = SATICI_AD.search(n)
        if m:
            return SATICI_TURU.get(m.group(0).replace(" ", ""), "captcha")
    return None


def baslik_mi(baslik: str | None) -> bool:
    """Pencere/sayfa başlığı bir ara doğrulama sayfası mı ("Just a moment…")? Kısa ve başı kalıpla başlamalı."""
    b = (baslik or "").strip()
    if not b or len(b) > BASLIK_UZUNLUK:
        return False
    return bool(BASLIK_KALIBI.match(katla(b)))


def adres_turu(adres: str | None) -> str | None:
    """Gömülü belge adresi bir sınama çerçevesi mi → tür | None. Görünmez reCAPTCHA v3 / hCaptcha rozeti sayılmaz."""
    a = adres or ""
    if not a or GORUNMEZ_ADRES.search(a):
        return None
    for desen, tur in ADRES_KALIPLARI:
        if desen.search(a):
            return tur
    return None


def cerceve_ozeti(cerceveler) -> list[dict]:
    """Gömülü belgeler → AJANA verilebilir özet: algılanan tür + alan adı (TAM adres/sorgu dizgesi verilmez: gizlilik)."""
    cikti = []
    for c in cerceveler or ():
        adres = c.get("adres") if isinstance(c, dict) else str(c)
        cikti.append({"kind": adres_turu(adres), "host": site_adi(adres)})
    return cikti


def site_adi(adres: str | None) -> str:
    """Adresin yalnız alan adı (bildirimde sayfa başlığı yerine; başlık kişisel olabilir). Yoksa ''."""
    a = (adres or "").strip()
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]*)", a, re.I)
    if not m:
        return ""
    ana = m.group(1).rsplit("@", 1)[-1]
    return ana.split(":")[0].lower()[:80]


def _cerceve_icinde(o: dict) -> bool:
    try:
        return int(o.get("cerceve") or 0) >= 1
    except (TypeError, ValueError):
        return False


def _rol(o: dict) -> str:
    return str(o.get("rol") or o.get("role") or "")


def _ad(o: dict) -> str:
    return str(o.get("ad_ham") or o.get("ad") or o.get("name") or o.get("text") or "")


def _belge_turu(o: dict) -> str | None:
    """Ögenin ait olduğu iç belge (iframe) bir sınama çerçevesi mi → tür | None."""
    return o.get("belge_tur") or adres_turu(o.get("belge_adres"))


COZULDU = re.compile(r"^(success|basarili|verified|dogrulandi|dogrulama basarili|verification (successful|complete)|"
                     r"you are verified|you re verified|insan oldugunuz dogrulandi)\b")
UST_KUTU_SOZCUK = 6  # çerçeve DIŞINDAKİ onay kutusu adı en çok bu kadar sözcük (ayar kutusu cümlesi değil, etiket)

# Klasik metin CAPTCHA'sı: resim + "Güvenlik kodu / Doğrulama kodu / captcha" adlı GİRİŞ alanı
KOD_ALANI = re.compile(r"\b(captcha|guvenlik kodu|dogrulama kodu|security code|verification code|guvenlik sorusu|"
                       r"karakterleri|resimdeki|gorseldeki|enter the (code|characters|text)|type the (code|characters|text))\b")
IKI_ASAMALI = re.compile(r"\b(sms|e ?posta|e ?mail|email|mail|telefon|cep|mobil|phone|text message|authenticator|"
                         r"dogrulama uygulamasi|otp|tek kullanimlik|one time|gonderildi|sent to|2fa|iki adimli|"
                         r"two factor|two step|2 adimli)\b")
RESIM_IFADESI = re.compile(r"\b(resimdeki|resimde gorunen|gorseldeki|gorselde gorunen|karakterleri (girin|yazin)|"
                           r"characters (shown )?(in|from) the (image|picture)|(type|enter) the (characters|code|text) "
                           r"(you see|shown|in the image|from the image)|case sensitive|buyuk kucuk harf)\b")
RESIM_AD = re.compile(r"\b(captcha|guvenlik|dogrulama|security|kod|code|resim|image|karakter|verify)\b")
RESIM_ROLLERI = frozenset({"image", "img", "canvas", "image map"})
YAKIN_PX = 170  # resim/ifade bu kadar piksel yakında sayılır (aynı form satırı)


def _yakin(o: dict, e: dict) -> bool:
    try:
        a, b = o["kutu"], e["kutu"]
        return abs((a[1] + a[3] / 2) - (b[1] + b[3] / 2)) <= YAKIN_PX
    except (KeyError, TypeError, IndexError):
        return False


def metin_captcha_alanlari(ogeler: list[dict]) -> list[int]:
    """Klasik resimli metin CAPTCHA'sının giriş alanları (sıra numaraları). Yanlış pozitif düşük: alan adı güvenlik/doğrulama
    kodu kalıbında olmalı VE yakında resim ("resimdeki karakterler" ifadesi ya da CAPTCHA/güvenlik/kod adlı/adsız resim)
    bulunmalı; SMS / e-posta / uygulama bağlamı (2 aşamalı doğrulama kodu) resimsiz ise SAYILMAZ. Adı doğrudan "captcha"
    olan giriş alanı tek başına yeter."""
    bulunan = []
    for i, o in enumerate(ogeler):
        if _rol(o) not in ("entry", "text") or o.get("kaynak") == "ocr":
            continue
        ad = katla(_ad(o))
        if not ad or not KOD_ALANI.search(ad):
            continue
        if "captcha" in ad:
            bulunan.append(i)
            continue
        if IKI_ASAMALI.search(ad):
            continue
        yakin = [e for j, e in enumerate(ogeler) if j != i and _yakin(o, e)]
        if RESIM_IFADESI.search(ad) or any(RESIM_IFADESI.search(katla(_ad(e))) for e in yakin) or any(
                _rol(e) in RESIM_ROLLERI and (not katla(_ad(e)).strip() or RESIM_AD.search(katla(_ad(e)))) for e in yakin):
            if not any(IKI_ASAMALI.search(katla(_ad(e))) for e in yakin if _rol(e) not in RESIM_ROLLERI):
                bulunan.append(i)
    return bulunan


def incele(ogeler, baslik: str = "", sayfa: dict | None = None) -> dict | None:
    """Gözlem ögeleri (gozlem.web_ogesi/agac_ogesi/ocr_ogesi biçimi: rol, ad, kutu, cerceve, belge_adres; ham web/read_text
    ögeleri de olur), pencere başlığı ve sayfa özeti (web.oku()["sayfa"]: baslik, adres, cerceveler) → algılanan sınama
    ya da None.

    Sonuç: {"detected": True, "kind", "window", "hint", "confidence", "page_wide": bool, "elements": [ögeler listesindeki
    sıra numaraları (sınama ögeleri)], "imza": sınamanın kimliği (adres + çerçeve kümesi)}. Saf işlev (G/Ç yok).
    ÇÖZÜLMÜŞ sınama (işaretli onay kutusu, "Success!") sayılmaz. Başlık kalıbı ("Just a moment…") TEK BAŞINA yetmez:
    sınama çerçevesi / sınama ögesi / Cloudflare adresi (/cdn-cgi/) ile birlikte geçerlidir."""
    sayfa = sayfa or {}
    ogeler = list(ogeler or ())
    turler: list[str] = []
    tam_sayfa = False
    guven = "high"
    aday: set[int] = set()   # ad + rol (+ metin CAPTCHA) ile bulunan sınama ögeleri
    isaretli: set[int] = set()
    cerceve_var = False
    cerceve_adresleri: list[str] = []
    adres = str(sayfa.get("adres") or "")
    for c in sayfa.get("cerceveler") or ():
        if isinstance(c, dict):
            t = c.get("kind") or adres_turu(c.get("adres"))
            a = c.get("adres") or c.get("host") or ""
        else:
            t, a = adres_turu(c), str(c)
        if t:
            cerceve_var = True
            turler.append(t)
            cerceve_adresleri.append(str(a))
    for i, o in enumerate(ogeler):
        rol, ad = _rol(o), _ad(o)
        if not ad:
            continue
        kapta = _cerceve_icinde(o)
        ocr = rol == "ocr_text" or o.get("kaynak") == "ocr"
        sozcuk = len(katla(ad).split())
        kisa = sozcuk <= OCR_KISA
        kutu_rolu = rol in KUTU_ROLLERI
        t = None
        k = ad_kalibi_mi(ad, satici=False, oran=KALIP_ORANI if ocr else 0.0)
        if k == "human_checkbox" and ((kutu_rolu and (kapta or sozcuk <= UST_KUTU_SOZCUK)) or kapta or (ocr and kisa)):
            t = "human_checkbox"
            if ocr and not kapta:
                guven = "low" if not turler else guven
        elif k == "slider_puzzle" and (rol in SURUKLE_ROLLERI or kapta or (ocr and kisa)):
            t = "slider_puzzle"
        elif k is None:
            s = ad_kalibi_mi(ad, satici=True)
            if s and kapta and (kutu_rolu or rol in ("label", "static")):  # satıcı adı: yalnız gömülü belgede ("Enable CAPTCHA" ayarı değil)
                t = s
        if t:
            aday.add(i)
            turler.append(t)
    for i in metin_captcha_alanlari(ogeler):
        aday.add(i)
        turler.append("text_captcha")
    # çözülmüş sınama: aday kutuların hepsi işaretli ya da "Success!" işareti ve işaretsiz aday yok → sınama değil
    isaretsiz = [i for i in aday if "checked" not in (ogeler[i].get("durumlar") or ())]
    isaretli_var = len(aday) > len(isaretsiz)
    basari = any(_cerceve_icinde(o) and COZULDU.search(katla(_ad(o))) for o in ogeler)
    if (isaretli_var or basari) and not isaretsiz:
        return None
    isaretli |= set(isaretsiz)
    baslik_kalibi = False
    for b in (baslik, sayfa.get("baslik"), sayfa.get("pencere")):
        if baslik_mi(b):
            baslik_kalibi = True
            break
    if baslik_kalibi and (turler or CDN_ADRES.search(adres)):
        tam_sayfa = True
        turler.append("cloudflare_interstitial")
    if not turler:
        return None
    if cerceve_var:  # sınama çerçevesi var: O BELGENİN etkileşimli ögeleri sınamanın parçası (başka iframe'ler DEĞİL)
        for i, o in enumerate(ogeler):
            if _cerceve_icinde(o) and _belge_turu(o) and (_rol(o) in KUTU_ROLLERI or o.get("etkilesimli") or _rol(o) in (
                    "entry", "link", "list item selectable", "combo box", "list box")):
                isaretli.add(i)
    oncelik = ("recaptcha", "hcaptcha", "turnstile", "arkose", "geetest", "captcha", "cloudflare_interstitial",
               "text_captcha", "human_checkbox", "slider_puzzle")
    tur = min(turler, key=lambda t: oncelik.index(t) if t in oncelik else 99)
    if tur in ("human_checkbox", "slider_puzzle") and not cerceve_var and any(
            t in ("recaptcha", "hcaptcha", "turnstile", "arkose", "geetest", "captcha") for t in turler):
        tur = next(t for t in turler if t not in ("human_checkbox", "slider_puzzle"))
    pencere = (baslik or sayfa.get("baslik") or sayfa.get("pencere") or "")[:120]
    imza = hashlib.sha1("\n".join([adres, *sorted(cerceve_adresleri), tur]).encode("utf-8", "replace")).hexdigest()[:16]
    # etiket/çerçeve dolgusu: sınama ögesi bir iframe içindeyse O ÇERÇEVENİN TÜM kutusu sınama alanı (onay kutusunun yanındaki
    # "I'm not a robot" yazısına/etikete tıklamak da kutuyu işaretler: yalnız küçük onay kutusu kutusu yetmez)
    ek_kutular = []
    for c in sayfa.get("cerceveler") or ():
        kb = c.get("kutu") if isinstance(c, dict) else None
        if kb and len(kb) == 4 and any(
                _cerceve_icinde(ogeler[i]) and ogeler[i].get("kutu") and len(ogeler[i]["kutu"]) == 4 and
                kb[0] <= ogeler[i]["kutu"][0] + ogeler[i]["kutu"][2] / 2 <= kb[0] + kb[2] and
                kb[1] <= ogeler[i]["kutu"][1] + ogeler[i]["kutu"][3] / 2 <= kb[1] + kb[3] for i in isaretli):
            ek_kutular.append([round(v) for v in kb])
    return {"detected": True, "kind": tur, "window": pencere, "hint": IPUCU.format(kind=tur), "confidence": guven,
            "page_wide": tam_sayfa, "elements": sorted(isaretli), "imza": imza, "site": site_adi(adres),
            "ek_kutular": ek_kutular}


def acik_sonuc(s: dict | None) -> dict | None:
    """Araç sonucuna konan `human_verification` alanı: {detected, kind, window, hint} (+ confidence)."""
    if not s:
        return None
    return {"detected": True, "kind": s["kind"], "window": s["window"], "hint": s["hint"],
            **({"confidence": s["confidence"]} if s.get("confidence") == "low" else {}),
            **({"unreadable": True} if s.get("unreadable") else {})}


def ogeleri_isaretle(ogeler: list[dict], s: dict | None) -> None:
    """Sınama ögelerine `sinama=True` koy (observe: bu ögelere ref ile girdi gönderilmez [18])."""
    for i in (s or {}).get("elements", ()):
        if 0 <= i < len(ogeler):
            ogeler[i]["sinama"] = True


# ---------------------------------------------------------------- pencere başına durum (girdi kapısı)
# DOSYA (çalışma dizininde JSON; CLI süreci ve MCP süreci aynı kutuları görür; 0600, flock ile atomik) YALNIZ ENGEL EKLER:
#   sinama (algılanmış sınama kutuları), bastir (uyarı bastırma), girdi (pencerenin son girdi zamanı: yalnız YENİDEN TARAMA
#   zorlar). "Sınama yok" (yok) ve "okunamadı" kararları YALNIZ süreç belleğindedir: dosyaya yazılmaz, dosyadan OKUNMAZ;
#   "engel yok" kararı için sürecin KENDİ taraması gerekir (dosyayı düzenlemek kapıyı açamaz; en kötü ihtimal fazladan
#   ret ya da tarama).

TTL = 300.0  # algının en uzun ömrü (sn); ayrıca başlık/adres değişince durum SİLİNİR
YENI_TTL = 15.0  # sınama durumu bundan eskiyse girdiden önce YENİDEN taranır (sayfa değişmiş olabilir; kalıcı kapı kalmaz)
YOK_TTL = 3.0  # "bu pencerede sınama yok" sonucu önbelleği (sn): yalnız TARAMA maliyetini düşürür; üst sınır KESİN
OKUNAMADI_TTL = 10.0  # "bu pencere okunamadı" (erişilebilirlik kapalı/yanıtsız, belge yok) önbelleği: her tıkta 10 sn beklenmesin
TARAMA_SURESI = 2.0  # girdi kapısı taramasının TOPLAM süre sınırı (sn)
BASTIR_TTL = 1800.0  # kullanıcı Bitti dedikten sonra aynı sınama imzası için uyarı bastırma süresi (sn)
ODAK_TTL = 1.0  # odaktaki öge sorgusu önbelleği (sn); her girdiden sonra silinir
YERLESME = 0.25  # girdiden sonra sayfanın yerleşmesi (kaydırma animasyonu, yeniden boyama) için yeniden taramadan önce beklenir (sn)
BOLUM_TAVAN = {"sinama": TTL, "bastir": BASTIR_TTL, "girdi": TTL}  # DOSYADAKİ bölümler
EN_COK_KAYIT = 64  # bölüm başına (bozuk/kötü niyetli dosya şişmesin)
JOKER = "*"  # girdi kaydı: pencere bilinmeyen girdi (masaüstü kipi) → tüm pencereler kirli
_KILIT = threading.Lock()
_BELLEK = threading.Lock()  # süreç belleği önbellekleri (_KILIT'ten ayrı: iç içe kilitlenme yok)
_DEVIR: dict[str, float] = {}
_YOK: dict[str, dict] = {}  # pencere → {"baslik", "zaman"}: SÜREÇ BELLEĞİ (dosyaya yazılmaz, dosyadan okunmaz)
_OKUNAMADI: dict[str, dict] = {}  # aynı: yalnız süreç belleği
_GIRDI: dict[str, float] = {}  # pencere → bu süreçte son girdi zamanı (dosyadaki `girdi` bölümünün bellek eşi)
DOSYA_AD = "insan-dogrulama.json"


def _yol() -> str:
    from .hata import calisma_dizini
    return os.path.join(calisma_dizini(), DOSYA_AD)


def _boot_id() -> str:
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return ""


def _sayi(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _kayit_gecerli(bolum: str, k, v, simdi: float) -> bool:
    """Durum dosyasındaki bir kaydı DOĞRULA (dosya ajan tarafından değiştirilebilir): tipler + 0 ≤ yaş ≤ TTL. Bozuk kayıt atılır
    (KeyError/sonsuz ömür yok)."""
    if not isinstance(k, str) or not isinstance(v, dict) or not _sayi(v.get("zaman")):
        return False
    yas = simdi - v["zaman"]
    if yas < 0 or yas > BOLUM_TAVAN[bolum] + 1.0:
        return False
    if bolum == "sinama":
        ku = v.get("kutular")
        if not isinstance(ku, list) or not all(isinstance(b, list) and len(b) == 4 and all(_sayi(c) for c in b) for b in ku):
            return False
        if not all(isinstance(v.get(a), str) for a in ("kind", "window", "hint", "baslik", "adres")):
            return False
        return v.get("imza") is None or isinstance(v.get("imza"), str)
    if bolum == "girdi":
        return True
    return isinstance(v.get("imza"), str)  # bastir


def _temizle_dosya(d: dict) -> dict:
    """Okunan sözlüğü doğrula: önyükleme kimliği farklıysa (monotonic sıfırlandı) hepsi atılır; bozuk kayıtlar ve BİLİNMEYEN
    bölümler (eski sürümün `yok` / `okunamadi` bölümleri dahil: kapıyı AÇAN kararlar dosyadan okunmaz) atılır."""
    boot = _boot_id()
    if not isinstance(d, dict) or d.get("boot") != boot:
        d = {"boot": boot}
    simdi = time.monotonic()
    d = {"boot": d.get("boot"), **{ad: d[ad] for ad in BOLUM_TAVAN if ad in d}}
    for ad in BOLUM_TAVAN:
        b = d.get(ad)
        if not isinstance(b, dict):
            d[ad] = {}
            continue
        for k in [k for k, v in b.items() if not _kayit_gecerli(ad, k, v, simdi)]:
            del b[k]
        for k in sorted(b, key=lambda x: b[x]["zaman"])[:max(0, len(b) - EN_COK_KAYIT)]:
            del b[k]
    return d


@contextlib.contextmanager
def _depo():
    """Durum dosyasını kilitleyip oku (DOĞRULANARAK) → sözlük; çıkışta (değiştiyse) atomik yaz. İş parçacığı + süreç kilidi."""
    from .hata import alan_dolu_denetle
    yol = _yol()
    with _KILIT:
        try:
            fd = os.open(yol + ".kilit", os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            alan_dolu_denetle(e, os.path.dirname(yol))  # geçici alan dolu: çökme yerine anlaşılır Dur 9
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                with open(yol, encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = {}
            ham = json.dumps(d, sort_keys=True) if isinstance(d, dict) else None
            d = _temizle_dosya(d)
            once = json.dumps(d, sort_keys=True)
            yield d
            if json.dumps(d, sort_keys=True) != once or once != ham:
                gecici = f"{yol}.{os.getpid()}.tmp"
                try:
                    g = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(g, "w", encoding="utf-8") as f:
                        json.dump(d, f)
                    os.replace(gecici, yol)
                except OSError as e:
                    try:
                        os.unlink(gecici)  # yarım geçici dosya alanı daha da doldurmasın
                    except OSError:
                        pass
                    alan_dolu_denetle(e, os.path.dirname(yol))  # geçici alan dolu: anlaşılır Dur 9
                    raise
        finally:
            os.close(fd)


def _zaman(simdi: float | None) -> float:
    return time.monotonic() if simdi is None else simdi


def kaydet(k: str, s: dict | None, ogeler: list[dict] | None = None, simdi: float | None = None,
           baslik: str | None = None, adres: str | None = None) -> None:
    """Pencere k için sınama durumunu yaz (s None = sınama yok → durum silinir). Kutular PENCERE pikseli. simdi: sayfanın
    OKUNDUĞU an (taramanın BAŞLANGICI; sonradan gelen girdi kaydı daha yeni sayılır → kayıt kirli)."""
    with _depo() as d:
        if not s:
            d["sinama"].pop(k, None)
            return
        kutular = [list(ogeler[i]["kutu"]) for i in s.get("elements", ()) if ogeler and 0 <= i < len(ogeler)
                   and ogeler[i].get("kutu") and len(ogeler[i]["kutu"]) == 4 and ogeler[i]["kutu"][2] > 0
                   and ogeler[i]["kutu"][3] > 0] + [list(x) for x in s.get("ek_kutular", ())]
        d["sinama"][k] = {**{a: s.get(a) for a in ("kind", "window", "hint", "confidence", "page_wide", "imza", "site")},
                          "kutular": kutular, "zaman": _zaman(simdi), "baslik": baslik or "", "adres": adres or ""}
    with _BELLEK:
        _YOK.pop(k, None)
        _OKUNAMADI.pop(k, None)


def yok_kaydet(k: str, baslik: str | None, simdi: float | None = None) -> None:
    """Bu SÜREÇ taradı ve sınama çıkmadı: bu pencere+başlık için YOK_TTL sn tekrar taranmasın (yalnız tarama maliyeti; yalnız
    süreç belleği: dosyaya yazılmaz, dosyadan okunmaz). Dosyadaki sınama kaydı silinir (kendi taramamız daha yeni)."""
    with _depo() as d:
        d["sinama"].pop(k, None)
    with _BELLEK:
        _OKUNAMADI.pop(k, None)
        _YOK[k] = {"baslik": baslik or "", "zaman": _zaman(simdi)}


def _bellek_son_girdi(k: str) -> float:
    with _BELLEK:
        return max(_GIRDI.get(k, 0.0), _GIRDI.get(JOKER, 0.0))


def son_girdi(k: str) -> float:
    """Pencerenin son girdi zamanı (bu süreç + dosyadaki `girdi` bölümü; pencereye özgü ya da JOKER). 0 = bilinmiyor."""
    m = _bellek_son_girdi(k)
    with _depo() as d:
        g = d["girdi"]
        return max(m, g.get(k, {}).get("zaman", 0.0), g.get(JOKER, {}).get("zaman", 0.0))


def yok_mu(k: str, baslik: str | None, simdi: float | None = None) -> bool:
    """Bu süreç bu pencereyi yakın zamanda taradı ve sınama yoktu mu (YOK_TTL, başlık aynı, TARAMADAN SONRA girdi yok)?"""
    with _BELLEK:
        y = _YOK.get(k)
    if not y:
        return False
    yas = _zaman(simdi) - y["zaman"]
    if yas < 0 or yas > YOK_TTL or (baslik or "") != y.get("baslik", "") or son_girdi(k) > y["zaman"]:
        with _BELLEK:
            _YOK.pop(k, None)
        return False
    return True


def okunamadi_kaydet(k: str, baslik: str | None, simdi: float | None = None) -> None:
    """Pencere taranamadı (erişilebilirlik kapalı/yanıtsız, web belgesi yok): OKUNAMADI_TTL sn tekrar denenmesin (yalnız süreç
    belleği). Mevcut sınama durumu KORUNUR."""
    with _BELLEK:
        _OKUNAMADI[k] = {"baslik": baslik or "", "zaman": _zaman(simdi)}


def okunamadi_mu(k: str, baslik: str | None, simdi: float | None = None) -> bool:
    with _BELLEK:
        y = _OKUNAMADI.get(k)
        if not y:
            return False
        yas = _zaman(simdi) - y["zaman"]
        if yas < 0 or yas > OKUNAMADI_TTL or (baslik or "") != y.get("baslik", ""):
            _OKUNAMADI.pop(k, None)
            return False
        return True


def _girdi_dosyaya_yazilsin(anahtar: str) -> bool:
    """Girdi kaydı diğer süreçlere de (dosya) gitsin mi: yalnız tarayıcı penceresinde (tarayıcı dışı uygulamalarda her
    tıkta dosya yazılmaz: tık gecikmesi artmaz). JOKER (masaüstü kipi): bu süreç bir tarayıcı penceresiyle ilgilendiyse."""
    try:
        if anahtar == JOKER:
            return any(v[1] for v in list(_TARAYICI.values()))
        return tarayici_mi(anahtar)
    except Exception:  # noqa: BLE001 - belirsizse yaz (yalnız yeniden tarama zorlar)
        return True


def girdi_oldu(k: str | None = None) -> None:
    """Bir pencereye girdi GÖNDERİLDİ (tık/tuş/yazı/kaydırma/pencere yönetimi/eylem): sayfa değişmiş olabilir → o pencerenin
    sınama kaydı KİRLİ olur (son girdi zamanı; kutular artık eski yerinde olmayabilir: sonraki girdi yeniden tarar, tarayıcı
    kayıttan eskiyse hazir_oku yeniden bakar), "sınama yok" önbelleği ve odak önbelleği silinir ("okunamadı" 10 sn süreyle yenilenir). k yok ya da
    masaüstü kipi (EKRAN) → pencere bilinmiyor: TÜM pencereler kirli sayılır (JOKER)."""
    from .arka_uc import EKRAN
    simdi = time.monotonic()
    anahtar = k if k and k != EKRAN else JOKER
    _ODAK.clear()
    with _BELLEK:
        if len(_GIRDI) > 256:
            _GIRDI.clear()
        _GIRDI[anahtar] = simdi
        _YOK.clear()  # `okunamadi` SİLİNMEZ: 10 sn süre + başlık değişimiyle yenilenir (her girdide yeniden tarama yok)
    if _girdi_dosyaya_yazilsin(anahtar):
        with _depo() as d:
            d["girdi"][anahtar] = {"zaman": simdi}


def temizle(k: str | None = None) -> None:
    with _depo() as d:
        for ad in BOLUM_TAVAN:
            if k is None:
                d[ad].clear()
            else:
                d[ad].pop(k, None)
    with _BELLEK:
        for b in (_YOK, _OKUNAMADI, _GIRDI):
            if k is None:
                b.clear()
            else:
                b.pop(k, None)


def durum(k: str, simdi: float | None = None, baslik: str | None = None, adres: str | None = None) -> dict | None:
    """Pencerenin yakın zamanda algılanmış sınaması (TTL içinde) ya da None. Başlık/adres verilmişse ve algı anındakinden
    farklıysa (sayfa değişti) durum SİLİNİR."""
    with _depo() as d:
        v = d["sinama"].get(k)
        if v is None:
            return None
        yas = _zaman(simdi) - v["zaman"]
        eski = yas > TTL or yas < 0
        degisti = (baslik is not None and v.get("baslik") and baslik != v["baslik"]) or (
            adres and v.get("adres") and adres != v["adres"])
        if eski or degisti:
            del d["sinama"][k]
            return None
        return dict(v)


def bastir(k: str, imza: str | None, simdi: float | None = None) -> None:
    """Kullanıcı 'Bitti' dedi: aynı imzalı sınama için uyarı/yeniden çağrı bastırılır (girdi kapısı AÇIK kalır)."""
    if not imza:
        return
    with _depo() as d:
        d["bastir"][k] = {"imza": imza, "zaman": _zaman(simdi)}


def bastirilmis_mi(k: str, imza: str | None, simdi: float | None = None) -> bool:
    if not imza:
        return False
    with _depo() as d:
        b = d["bastir"].get(k)
        if not b:
            return False
        if not 0 <= _zaman(simdi) - b["zaman"] <= BASTIR_TTL:
            d["bastir"].pop(k, None)
            return False
        return b["imza"] == imza


# ---------------------------------------------------------------- tarama (çekirdek): tarayıcı penceresini oku → algı → durum

def baslik_simdi(k: str) -> str | None:
    try:
        from . import api
        from .arka_uc import EKRAN
        return api.arka().baslik(k) if k and k != EKRAN else None
    except Exception:  # noqa: BLE001 - başlık okunamazsa yalnız önbellekteki algıya bakılır
        return None


_SON_OKUMA: dict[str, str] = {}  # pencere → son OKUNAN sayfanın adresi (bu süreçte; sayfa değişti mi karşılaştırması)
_TARAYICI: dict[str, tuple[float, bool]] = {}  # pencere → (zaman, tarayıcı mı): sınıf değişmez; her tıkta sorulmasın
_ODAK: dict[str, tuple[float, dict | None]] = {}  # pencere → (zaman, odaktaki öge): ODAK_TTL; girdi_oldu siler


def son_adres(k: str) -> str:
    """Pencerenin en son başarıyla taranan sayfasının adresi ('' = hiç taranmadı)."""
    return _SON_OKUMA.get(k, "")


def tarayici_mi(k: str) -> bool:
    """web.tarayici_mi, kısa önbellekli (tarayıcı dışı uygulamalarda her tıkta pencere sınıfı sorulmasın)."""
    simdi = time.monotonic()
    t = _TARAYICI.get(k)
    if t is not None and simdi - t[0] < 60.0:
        return t[1]
    from . import web
    v = bool(web.tarayici_mi(k))
    if len(_TARAYICI) > 256:
        _TARAYICI.clear()
    _TARAYICI[k] = (simdi, v)
    return v


def _gunluk(satir: str) -> None:
    try:
        from .gunluk import gunluk
        gunluk(satir)
    except Exception:  # noqa: BLE001 - günlük yazılamazsa kapı yine çalışır
        pass


def tara(k: str, baslik: str | None = None, kapi: bool = False) -> tuple[dict | None, bool]:
    """Tarayıcı penceresinin sayfasını (erişilebilirlik ağacı; ekran görüntüsü/öne getirme YOK) oku, sınama durumunu yaz.
    → (sonuç | None, okundu). Pencere tarayıcı değilse ya da sayfa okunamazsa okundu=False (mevcut durum KORUNUR: iki
    geçici zaman aşımı yanlış 'kayboldu' üretmesin); okunamayan pencere OKUNAMADI_TTL sn tekrar denenmez. Yasak (10) ve DUR
    (13) yükselir. kapi=True (girdi kapısı): erişilebilirlik KAPALIYSA tarayıcı penceresi için süreç başına BİR kez açılır
    (erisim_ac_garanti; kde'de oturum geneli yan etki: docs/ARCHITECTURE.md §12); yine kapalıysa sayfa OKUNAMADI sayılır
    (klavye_engeli: Tab sonrası girdi / tek başına Boşluk-Enter reddedilir) ve toplam süre TARAMA_SURESI ile sınırlı."""
    import contextlib
    from . import gozlem, web
    from .hata import Dur
    if not k or not tarayici_mi(k):
        return None, False
    t0 = time.monotonic()  # sayfanın OKUNDUĞU an: bundan sonra gelen girdi bu kaydı kirletir
    try:
        if kapi:
            from . import api
            from .erisim import erisim_acik
            if api.yasak_mi(k):
                raise Dur(10, _("YASAK pencere: ağacı okunmaz"))
            if not erisim_acik():
                _erisim_bir_kez_ac()
            if not erisim_acik():
                _gunluk("insan-dogrulama | erisim kapali: kapi taramasi yapilamadi (sayfa okunamadi sayilir)")
                okunamadi_kaydet(k, baslik)
                return None, False
        else:
            web.hazirla(k)
        roller = sorted(web.ETKILESIMLI | {"image"})
        with (web.tarama_siniri(TARAMA_SURESI) if kapi else contextlib.nullcontext()):
            s = web.oku(k, roller=roller, gorunur=True, en_cok=0, ad_siniri=0, ayrinti=False, cerceve_metni=True)
    except Dur as e:
        if e.kod in (10, 13):
            raise
        okunamadi_kaydet(k, baslik if baslik is not None else baslik_simdi(k))
        return None, False
    except Exception:  # noqa: BLE001
        okunamadi_kaydet(k, baslik if baslik is not None else baslik_simdi(k))
        return None, False
    baslik = baslik if baslik is not None else baslik_simdi(k) or ""
    if not s["sayfa"].get("belge"):  # web belgesi yok (Electron arayüzü, yüklenmemiş sayfa): sonuç önbelleğe
        okunamadi_kaydet(k, baslik)
        return None, False
    ogeler = [gozlem.web_ogesi(o, web.ETKILESIMLI) for o in s["ogeler"]]
    _SON_OKUMA[k] = s["sayfa"].get("adres") or ""
    sonuc = incele(ogeler, baslik, s["sayfa"])
    ogeleri_isaretle(ogeler, sonuc)
    if sonuc:
        kaydet(k, sonuc, ogeler, baslik=baslik, adres=s["sayfa"].get("adres") or "", simdi=t0)
    else:
        yok_kaydet(k, baslik, simdi=t0)
    return sonuc, True


_ERISIM_DENENDI = threading.Event()  # erişilebilirlik kapı için bu süreçte bir kez açılmayı denedi


def _erisim_bir_kez_ac() -> None:
    """Kapı taramasında erişilebilirlik KAPALI: tarayıcıda sınama kutuları ancak ağaçtan okunur; bu yüzden süreç başına BİR kez
    açılır (erisim_ac_garanti). kde'de bu kullanıcının oturumunda erişilebilirliği açar (oturum geneli yan etki; `deskhand
    a11y off` geri alır, docs/ARCHITECTURE.md §12); sanal masaüstünde yalnız özel veri yolu."""
    if _ERISIM_DENENDI.is_set():
        return
    _ERISIM_DENENDI.set()
    try:
        from .erisim import erisim_ac_garanti
        erisim_ac_garanti()
        _gunluk("insan-dogrulama | kapi icin erisilebilirlik acildi")
    except Exception as e:  # noqa: BLE001 - açılamazsa sayfa okunamadı sayılır (klavye/fare kuralları sıkılaşır)
        _gunluk(f"insan-dogrulama | erisilebilirlik acilamadi: {type(e).__name__}")


def _yerles(girdi: float) -> None:
    """Son girdiden sonra sayfa yerleşsin (kaydırma animasyonu, yeniden boyama): yeniden taramadan önce kalan süre beklenir."""
    kalan = YERLESME - (time.monotonic() - girdi)
    if kalan > 0:
        time.sleep(min(kalan, YERLESME))


def hazir_oku(k: str, baslik: str | None = None) -> tuple[dict | None, bool]:
    """Girdiden ÖNCE: pencerenin sınama durumu + sayfanın şu an (ya da çok yakın zamanda) OKUNABİLDİĞİ. Durum yoksa ve pencere
    tarayıcıysa BİR kez tarar; "sınama yok" sonucu YOK_TTL (3 sn), "okunamadı" OKUNAMADI_TTL sn önbellekte (yalnız süreç
    belleği). Sınama kaydı YENI_TTL'den eskiyse YA DA kayıttan SONRA o pencereye girdi gittiyse (tık, tuş, kaydırma, pencere
    boyutu: kutular artık yerinde olmayabilir) yeniden taranır. Kirli kayıt yeniden OKUNAMAZSA eski kutulara güvenilmez: dönen
    durumda kirli=True (o pencerede TÜM fare girdisi reddedilir). → (durum | None, okundu)."""
    if not k:
        return None, False
    from .arka_uc import EKRAN
    if k == EKRAN:
        return None, False
    baslik = baslik if baslik is not None else baslik_simdi(k)
    d = durum(k, baslik=baslik)
    kirli = False
    girdi = 0.0
    if d is not None:
        girdi = son_girdi(k)
        kirli = d["zaman"] < girdi
        if not kirli and _zaman(None) - d["zaman"] <= YENI_TTL:
            return d, True
    elif yok_mu(k, baslik):
        return None, True
    elif okunamadi_mu(k, baslik):
        return None, False
    if kirli:
        _yerles(girdi)
    _sonuc, okundu = tara(k, baslik, kapi=True)
    d = durum(k, baslik=baslik)
    if kirli and not okundu and d is not None and d["zaman"] < girdi:
        d = {**d, "kirli": True}
    return d, okundu


def hazir(k: str, baslik: str | None = None) -> dict | None:
    """hazir_oku'nun yalnız durum kısmı."""
    return hazir_oku(k, baslik)[0]


# ---------------------------------------------------------------- girdi kapısı

def _kutuda(kutu, nokta) -> bool:
    x, y, w, h = kutu
    return x - 4 <= nokta[0] <= x + w + 4 and y - 4 <= nokta[1] <= y + h + 4


def girdi_engeli(k: str, *, oge: dict | None = None, ad: str | None = None, nokta=None, noktalar=(),
                 klavye: bool = False, baslik: str | None = None, odak_kutusu=None,
                 simdi: float | None = None, rol: str | None = None, metin_kati: bool = False,
                 kayit: dict | None = None) -> dict | None:
    """Girdi sınama ögesine mi gidiyor? Evetse sınama sonucu (acik_sonuc biçimi), değilse None.
      oge: observe ögesi (sinama bayrağı); ad: metin/öge adı hedefi (sınama algılanmış pencerede kısa insan-doğrulama cümlesi
      ya da satıcı adı; sınama YOKKEN yalnız KUTU ROLÜNDEKİ ögenin adı [rol] ya da sayfa okunamadığı için doğrulanamayan
      hedefin kısa yazısı [metin_kati]: "I'm Not a Robot (2017)" dizi adı, "Ben Robot Değilim" film adı serbest);
      nokta/noktalar: pencere pikseli (algılanan sınama kutularından biri); odak_kutusu: odaktaki ögenin kutusu (klavye
      girdisi: odak sınama kutusundaysa ret: Tab+Boşluk ile işaretleme); klavye: hedefsiz klavye girdisi — yalnız sayfanın
      TAMAMI sınamaysa (ara sayfa) engellenir; baslik: pencerenin güncel başlığı (değiştiyse eski algı atılır);
      kayit: hazir_oku'nun verdiği durum (kirli=True: girdiden sonra yeniden OKUNAMADI → o pencerede TÜM fare girdisi ret)."""
    d = kayit if kayit is not None else durum(k, simdi, baslik=baslik)
    if oge is not None and oge.get("sinama"):
        return acik_sonuc({"kind": (d or {}).get("kind", "captcha"), "window": (d or {}).get("window", baslik or ""),
                           "hint": IPUCU.format(kind=(d or {}).get("kind", "captcha")),
                           "confidence": (d or {}).get("confidence", "high")})
    if d is None:
        if ad and (metin_kati or rol in KUTU_ROLLERI) and len(katla(ad).split()) <= OCR_KISA \
                and ad_kalibi_mi(ad, oran=KALIP_ORANI):
            return acik_sonuc({"kind": ad_kalibi_mi(ad), "window": baslik or "", "hint": IPUCU.format(
                kind=ad_kalibi_mi(ad)), "confidence": "high"})
        return None
    kind = d.get("kind") or "captcha"
    sonuc = acik_sonuc({"kind": kind, "window": d.get("window") or baslik or "", "hint": IPUCU.format(kind=kind),
                        "confidence": d.get("confidence") or "high"})
    if ad and ad_kalibi_mi(ad, satici=True):
        return sonuc
    if d.get("kirli") and not klavye:  # girdiden sonra yeniden okunamadı: kutuların yeri bilinmiyor → tüm fare girdisi ret
        return sonuc
    pts = [p for p in ([nokta] if nokta is not None else []) + list(noktalar) if p is not None]
    for kutu in d["kutular"]:
        if any(_kutuda(kutu, p) for p in pts):
            return sonuc
        if odak_kutusu is not None and _kutuda(kutu, (odak_kutusu[0] + odak_kutusu[2] / 2,
                                                       odak_kutusu[1] + odak_kutusu[3] / 2)):
            return sonuc
    if klavye and d.get("page_wide"):
        return sonuc
    if d.get("page_wide") and (pts or ad):  # ara sayfa: sayfa bir bütün sınama (kutular okunmamış olabilir)
        return sonuc
    return None


def dur(r: dict):
    """Çekirdek için hata: Dur(18) + makinece okunur sonuç (MCP: human_verification alanı)."""
    from .hata import INSAN_DOGRULAMA, Dur
    e = Dur(INSAN_DOGRULAMA, red_metni(r), tur="insan-dogrulama")
    e.insan_dogrulama = r
    return e


def _kisa_metinler(metinler) -> list:
    return [m for m in (metinler or ()) if m and len(katla(m).split()) <= OCR_KISA]


def nokta_engeli(k: str, x, y, metinler=()) -> dict | None:
    """ÇEKİRDEK fare kapısı (eylem.hassas_nokta: koordinat, metin, öge, simge, renk, web ve sürükleme başlangıcı için TEK
    nokta): tıklanan NOKTA sınama kutusundaysa → sonuç. Ajanın verdiği ada DEĞİL noktaya bakılır. Pencerede durum yoksa ve
    pencere tarayıcıysa girdiden önce bir kez taranır (hazir_oku); sayfa OKUNAMADIYSA (tarayıcı değil, a11y kapalı…) kısa
    insan-doğrulama cümlesi (öge adı + noktadaki yazı) doğrulanamadığı için reddedilir, okunduysa yalnız nokta. Masaüstü
    kipinde (EKRAN) pencere noktadan önce bilinmez: eylem.tikla_ic imleci koyduktan sonra ekran_nokta_engeli çağırır."""
    from .arka_uc import EKRAN
    if not k or k == EKRAN:
        return None
    nokta = (x, y) if x is not None and y is not None else None
    if tarayici_mi(k):
        baslik = baslik_simdi(k)
        _d, okundu = hazir_oku(k, baslik)
    else:  # tarayıcı değil: ağaç taranmaz (tık gecikmesi yok); observe'un yazdığı durum varsa o kullanılır
        okundu = False
        _d = None
        baslik = baslik_simdi(k) if durum(k) is not None else None
    for m in _kisa_metinler(metinler) or (None,):
        r = girdi_engeli(k, ad=m, nokta=nokta, baslik=baslik, metin_kati=not okundu, kayit=_d)
        if r is not None:
            return r
    return None


def oge_engeli(k: str, oge: dict | None) -> dict | None:
    """ÇEKİRDEK öge kapısı: ögenin ait olduğu iç belge (iframe) adresi (`_belge_adres` / `belge_adres`) sınama çerçevesiyse →
    sonuç. Görünür/görünmez ayrımı yok; erişilebilirlik eylemi (via=action) ve gerçek tık AYNI kapıdan geçer."""
    tur = adres_turu((oge or {}).get("_belge_adres") or (oge or {}).get("belge_adres"))
    if not tur:
        return None
    return acik_sonuc({"kind": tur, "window": baslik_simdi(k) or "", "hint": IPUCU.format(kind=tur), "confidence": "high"})


def ekran_nokta_engeli(au, px, py, metinler=(), pencere=None) -> dict | None:
    """MASAÜSTÜ kipi (EKRAN) fare kapısı: imleç (px, py) ekran pikselinde DURUYOR (mouseto sonrası); imlecin altındaki pencere
    çözülür (`pencere` verilmediyse au.fare()[2]) ve kapı O pencere + pencereye göre nokta ile çağrılır (tarayıcıda
    sınama kutusu, tarayıcı değilse yazı kuralı). Pencere çözülemezse yalnız yazı kuralı (doğrulanamadı)."""
    w = pencere if pencere is not None else au.fare()[2]
    geo = None
    if w:
        try:
            geo = au.geometri(w)
        except Exception:  # noqa: BLE001 - geometri yoksa pencere-göreli nokta bilinmez
            geo = None
    if not w or geo is None:
        for m in _kisa_metinler(metinler) or (None,):
            r = girdi_engeli("", ad=m, metin_kati=True)
            if r is not None:
                return r
        return None
    return nokta_engeli(w, px - geo[0], py - geo[1], metinler)


def odakli_oge(k: str) -> dict | None:
    """Tarayıcı sayfasında ODAKTAKİ ögenin {"rol","ad","kutu"} (pencere pikseli) | None. Yalnız sınama durumu VARKEN çağrılır
    (Tab+Boşluk ile sınama kutusunu işaretlemeyi kapatmak için); erişilebilirlik ağacının 'focused' durumu kullanılır.
    Sonuç ODAK_TTL sn önbellekte (her klavye komutunda ek tam tarama yapılmasın); girdi gönderilince silinir."""
    from . import web
    simdi = time.monotonic()
    t = _ODAK.get(k)
    if t is not None and simdi - t[0] < ODAK_TTL:
        return t[1]
    if not tarayici_mi(k):
        return None
    sonuc = None
    with web.tarama_siniri(TARAMA_SURESI * 2):
        web.hazirla(k)
        s = web.oku(k, roller=sorted(web.ETKILESIMLI | {"image"}), gorunur=True, en_cok=0, ad_siniri=0, ayrinti=False)
    for o in s["ogeler"]:
        if "odakli" in (o.get("durum") or ()) and o.get("kutu"):
            sonuc = {"rol": o["rol"], "ad": o["ad"], "kutu": list(o["kutu"])}
            break
    _ODAK[k] = (simdi, sonuc)
    return sonuc


TAB_TUSLARI = frozenset({"tab", "iso_left_tab", "k:15", "x:tab", "x:iso_left_tab"})


def _tab_mu(akor: str) -> bool:
    return str(akor).lower().split("+")[-1] in TAB_TUSLARI


def metin_dizisi(metin: str) -> list[str]:
    """Yazılacak metin → klavye dizisi parçaları: her TAB karakteri "tab", aradaki boş olmayan yazı "metin:…"."""
    cikti: list[str] = []
    for parca in re.split("(\t)", metin or ""):
        if parca == "\t":
            cikti.append("tab")
        elif parca:
            cikti.append("metin:" + parca)
    return cikti


def tab_sonrasi_girdi(dizi) -> bool:
    """Dizide Tab/Shift+Tab'dan SONRA başka bir tuş/metin var mı? (Tab odağı sınama kutusuna taşır, ardından Boşluk/Enter/yazı
    ona gider: odak bu çağrının BAŞINDA sınama dışında göründüğü için ayrı denetim yetmez.) Yalnız art arda Tab serbest."""
    gordu = False
    for t in dizi or ():
        if _tab_mu(t):
            gordu = True
        elif gordu:
            return True
    return False


def klavye_engeli(k: str, odak_sorgu=None, dizi=None, odak_bilgi_sorgu=None) -> dict | None:
    """ÇEKİRDEK klavye kapısı (tuş / yazı / bas): sayfanın tamamı sınamaysa ya da ODAK sınama kutusundaysa (onay kutusu,
    kaydırıcı, sınama çerçevesi içi, resimli güvenlik kodu giriş alanı) → sonuç. odak_sorgu: çağıranın verdiği, odaktaki
    ögenin {"kutu": [x,y,w,h]} bilgisini döndüren işlev (AT-SPI; yalnız sınama durumu VARKEN çağrılır: durum yoksa ek maliyet
    yok). dizi: gönderilecek tuş/metin parçaları (tuş akorları; yazı için metin_dizisi): sayfada sınama durumu varken Tab/
    Shift+Tab'dan sonra başka tuş ya da yazı da içeriyorsa ret (Tab odağı sınama kutusuna taşıyıp devamı ona gönderirdi).
    FAIL-OPEN YOK: (1) sayfa OKUNAMAYAN tarayıcı penceresinde (erişilebilirlik kapalı/yanıtsız, kirli kayıt yeniden okunamadı)
    okunamayan_klavye_engeli (odak sorgusu; odak bilinmiyorsa dizinin HERHANGİ yerindeki Boşluk/Enter reddedilir); (2) sınama durumu VARKEN odak bilinemiyorsa (sorgu hata
    verdi / odakta kutulu öge yok) Boşluk/Enter/yazı içeren dizi reddedilir."""
    from .arka_uc import EKRAN
    if not k or k == EKRAN:
        return None
    baslik = baslik_simdi(k)
    d, okundu = hazir_oku(k, baslik)
    if d is None:
        if not okundu and tarayici_mi(k):
            from .erisim import yerel_diyalog_mu  # tarayıcının yerel diyaloğu (dosya seçici): sayfa yok, sınama olamaz
            return None if yerel_diyalog_mu(k) else okunamayan_klavye_engeli(dizi, baslik, k=k,
                                                                            odak_bilgi_sorgu=odak_bilgi_sorgu)
        return None
    if d.get("page_wide"):
        return girdi_engeli(k, klavye=True, baslik=baslik, kayit=d)
    if d.get("kirli"):  # girdiden sonra yeniden okunamadı: odak/kutular bilinmiyor
        return okunamayan_klavye_engeli(dizi, baslik, d, k=k, odak_bilgi_sorgu=odak_bilgi_sorgu)
    if dizi and tab_sonrasi_girdi(dizi):
        return _sonuc_d(d, baslik)
    kutu = None
    bilinmiyor = True
    try:
        kutu = ((odak_sorgu or (lambda: odakli_oge(k)))() or {}).get("kutu")
        bilinmiyor = not (kutu and len(kutu) == 4)
    except Exception:  # noqa: BLE001 - odak okunamadı: bilinmiyor (aşağıda Boşluk/Enter/yazı reddedilir)
        kutu = None
    if bilinmiyor and dizi and dizi_etkilesimli(dizi):
        return _sonuc_d(d, baslik)
    return girdi_engeli(k, klavye=True, baslik=baslik, odak_kutusu=kutu if kutu and len(kutu) == 4 else None, kayit=d)


def _sonuc_d(d: dict, baslik: str | None) -> dict:
    kind = d.get("kind") or "captcha"
    return acik_sonuc({"kind": kind, "window": d.get("window") or baslik or "", "hint": IPUCU.format(kind=kind),
                       "confidence": d.get("confidence") or "high"})


def dizi_bosluk_enter(dizi) -> bool:
    """Dizide Boşluk/Enter eşdeğeri bir tuş (ham k:57, x:Return… dahil) ya da boşluk/satır sonu içeren yazı var mı?"""
    from . import guvenlik
    for t in dizi or ():
        t = str(t)
        if t.startswith("metin:"):
            if any(c.isspace() for c in t[6:]):
                return True
        elif guvenlik.onay_tusu_mu(t):
            return True
    return False


def dizi_etkilesimli(dizi) -> bool:
    """Dizide Boşluk/Enter ya da herhangi bir yazı (`metin:`) var mı? (Odaktaki sınama kutusunu işaretleyebilecek girdi.)"""
    return dizi_bosluk_enter(dizi) or any(str(t).startswith("metin:") and len(str(t)) > 6 for t in dizi or ())


def tek_basina_bosluk_enter(dizi) -> bool:
    """Dizi TEK bir girdi mi ve o Boşluk/Enter (ya da yalnız boşluk/satır sonu yazısı) mi? (Odaktaki onay kutusunu işaretler.)"""
    parcalar = [t for t in (dizi or ()) if t]
    if len(parcalar) != 1:
        return False
    t = str(parcalar[0])
    if t.startswith("metin:"):
        return t[6:] != "" and t[6:].strip() == ""
    return dizi_bosluk_enter(parcalar)


IPUCU_OKUNAMADI = _("Sayfa okunamadı, bu yüzden CAPTCHA olmadığı doğrulanamıyor (olmayabilir) ve odak sayfa içinde ya da "
                    "bilinmiyor: Enter/Boşluk içeren girdi ve Tab'dan sonra gelen girdi reddedildi. Yapılacak: önce hedef "
                    "yazı alanına tıkla, sonra yaz (odak yazı alanındaysa izin verilir); adrese gitmek için goto kullan; "
                    "ya da tarayıcıyı erişilebilirlik açıkken yeniden başlat (ac --arka). Kullanıcıya devir gerekmez.")


def _odak_guvenli(odak, d) -> bool:
    """Okunamayan sayfada odak bilgisi Enter/Boşluk'a izin veriyor mu: odak belge DIŞINDA (adres/araç çubuğu) ya da
    (bilinen sınama kaydı yokken) düzenlenebilir yazı alanında."""
    if not isinstance(odak, dict):
        return False
    return not odak.get("belge_ici") or bool(odak.get("duzenlenebilir"))


def okunamayan_klavye_engeli(dizi, baslik: str | None = None, d: dict | None = None, bosluk: bool = True,
                             k: str | None = None, odak_bilgi_sorgu=None) -> dict | None:
    """Sayfası OKUNAMAYAN tarayıcı penceresinde klavye kuralı. Tab'dan sonra gelen girdi HER ZAMAN reddedilir (odak sınama
    kutusuna taşınabilir). bosluk=True: dizinin HERHANGİ yerinde Boşluk/Enter (['a','enter'], 'metin:abc\\n' dahil) varsa
    ucuz odak sorgusu (erisim.odak_bilgisi; k verildiyse) yapılır: odak belge dışında (adres çubuğu) ya da düzenlenebilir
    yazı alanındaysa izin, odak sayfa içinde başka bir ögedeyse ya da bilinmiyorsa ret. d: bilinen (kirli) sınama kaydı
    (ret sonucu onun türüyle döner)."""
    if not dizi:
        return None
    tab = tab_sonrasi_girdi(dizi)
    if not tab:
        if not (bosluk and dizi_bosluk_enter(dizi)):
            return None
        odak = None
        if k is not None:
            try:
                if odak_bilgi_sorgu is not None:
                    odak = odak_bilgi_sorgu()
                else:
                    from .erisim import odak_bilgisi
                    odak = odak_bilgisi(k)
            except Exception:  # noqa: BLE001 - bilinmiyor
                odak = None
        if _odak_guvenli(odak, d):
            return None
    if d is not None:
        return _sonuc_d(d, baslik)
    return acik_sonuc({"kind": "captcha", "window": baslik or "", "hint": IPUCU_OKUNAMADI, "confidence": "low",
                       "unreadable": True})


# ---------------------------------------------------------------- request_human için kapı (bekleyen devir)

def devir_acik(k: str) -> bool:
    with _KILIT:
        return k in _DEVIR


def devir_baslat(k: str) -> bool:
    """ATOMİK: bu pencere için devir yoksa kaydı aç → True; zaten varsa False (ikinci eşzamanlı istek reddedilir)."""
    with _KILIT:
        if k in _DEVIR:
            return False
        _DEVIR[k] = time.monotonic()
        return True


def devir_bitir(k: str) -> None:
    with _KILIT:
        _DEVIR.pop(k, None)


def red_metni(s: dict) -> str:
    """[18] hata iletisi (kullanıcıya/ajana; çevrilir). Okunamayan tarayıcı sayfası (CAPTCHA olmayabilir) AYRI ileti: request_human
    önerilmez."""
    if s.get("unreadable"):
        from .web import IPUCU_ERISIM
        return _("sayfa okunamadı (CAPTCHA olmayabilir) ve odak sayfa içinde ya da bilinmiyor: Enter/Boşluk ve Tab "
                 "sonrası girdi gönderilmedi. Önce hedef yazı alanına tıkla, sonra yaz (odak yazı alanındaysa izin "
                 "verilir); adres için goto; ya da tarayıcıyı erişilebilirlik açıkken yeniden başlat (`ac --arka`)"
                 ) + "\n" + IPUCU_ERISIM
    return _("insan doğrulaması ({kind}): kullanıcıya devret — request_human kullan; girdi gönderilmedi").format(
        kind=s["kind"])
