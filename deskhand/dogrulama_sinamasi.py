"""İnsan doğrulaması (CAPTCHA) sınamalarını ALGILAR; ÇÖZMEZ, atlatmaz (docs/ARCHITECTURE.md §13).

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
    r"\b(slide to verify|slide to complete|slide right to|slide the (puzzle|slider)|drag the puzzle|"
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
            **({"confidence": s["confidence"]} if s.get("confidence") == "low" else {})}


def ogeleri_isaretle(ogeler: list[dict], s: dict | None) -> None:
    """Sınama ögelerine `sinama=True` koy (observe: bu ögelere ref ile girdi gönderilmez [18])."""
    for i in (s or {}).get("elements", ()):
        if 0 <= i < len(ogeler):
            ogeler[i]["sinama"] = True


# ---------------------------------------------------------------- pencere başına durum (girdi kapısı): ÇALIŞMA DİZİNİNDE JSON
# (CLI süreci ve MCP süreci aynı kutuları görür; 0600, flock ile atomik; pencere kimliği + başlık/adres anahtarı)

TTL = 300.0  # algının en uzun ömrü (sn); ayrıca başlık/adres değişince durum SİLİNİR
YOK_TTL = 10.0  # "bu pencerede sınama yok" sonucu önbelleği (sn): her tıkta ağaç taraması yapılmasın
BASTIR_TTL = 1800.0  # kullanıcı Bitti dedikten sonra aynı sınama imzası için uyarı bastırma süresi (sn)
_KILIT = threading.Lock()
_DEVIR: dict[str, float] = {}
DOSYA_AD = "insan-dogrulama.json"


def _yol() -> str:
    from .hata import calisma_dizini
    return os.path.join(calisma_dizini(), DOSYA_AD)


@contextlib.contextmanager
def _depo():
    """Durum dosyasını kilitleyip oku → sözlük; çıkışta (değiştiyse) atomik yaz. İş parçacığı + süreç kilidi."""
    yol = _yol()
    with _KILIT:
        fd = os.open(yol + ".kilit", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                with open(yol, encoding="utf-8") as f:
                    d = json.load(f)
                if not isinstance(d, dict):
                    d = {}
            except (OSError, ValueError):
                d = {}
            for ad in ("sinama", "yok", "bastir"):
                if not isinstance(d.get(ad), dict):
                    d[ad] = {}
            once = json.dumps(d, sort_keys=True)
            yield d
            if json.dumps(d, sort_keys=True) != once:
                gecici = f"{yol}.{os.getpid()}.tmp"
                g = os.open(gecici, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(g, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                os.replace(gecici, yol)
        finally:
            os.close(fd)


def _zaman(simdi: float | None) -> float:
    return time.monotonic() if simdi is None else simdi


def kaydet(k: str, s: dict | None, ogeler: list[dict] | None = None, simdi: float | None = None,
           baslik: str | None = None, adres: str | None = None) -> None:
    """Pencere k için sınama durumunu yaz (s None = sınama yok → durum silinir). Kutular PENCERE pikseli."""
    with _depo() as d:
        if not s:
            d["sinama"].pop(k, None)
            return
        kutular = [list(ogeler[i]["kutu"]) for i in s.get("elements", ()) if ogeler and 0 <= i < len(ogeler)
                   and ogeler[i].get("kutu") and len(ogeler[i]["kutu"]) == 4 and ogeler[i]["kutu"][2] > 0
                   and ogeler[i]["kutu"][3] > 0] + [list(x) for x in s.get("ek_kutular", ())]
        d["sinama"][k] = {**{a: s.get(a) for a in ("kind", "window", "hint", "confidence", "page_wide", "imza", "site")},
                          "kutular": kutular, "zaman": _zaman(simdi), "baslik": baslik or "", "adres": adres or ""}
        d["yok"].pop(k, None)


def yok_kaydet(k: str, baslik: str | None, simdi: float | None = None) -> None:
    """Taramada sınama çıkmadı: bu pencere+başlık için YOK_TTL sn tekrar taranmasın."""
    with _depo() as d:
        d["sinama"].pop(k, None)
        d["yok"][k] = {"baslik": baslik or "", "zaman": _zaman(simdi)}


def yok_mu(k: str, baslik: str | None, simdi: float | None = None) -> bool:
    with _depo() as d:
        y = d["yok"].get(k)
        if not y:
            return False
        if _zaman(simdi) - y["zaman"] > YOK_TTL or (baslik or "") != y.get("baslik", ""):
            d["yok"].pop(k, None)
            return False
        return True


def temizle(k: str | None = None) -> None:
    with _depo() as d:
        for ad in ("sinama", "yok", "bastir"):
            if k is None:
                d[ad].clear()
            else:
                d[ad].pop(k, None)


def durum(k: str, simdi: float | None = None, baslik: str | None = None, adres: str | None = None) -> dict | None:
    """Pencerenin yakın zamanda algılanmış sınaması (TTL içinde) ya da None. Başlık/adres verilmişse ve algı anındakinden
    farklıysa (sayfa değişti) durum SİLİNİR."""
    with _depo() as d:
        v = d["sinama"].get(k)
        if v is None:
            return None
        eski = (_zaman(simdi) - v["zaman"]) > TTL
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
        if _zaman(simdi) - b["zaman"] > BASTIR_TTL:
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


def son_adres(k: str) -> str:
    """Pencerenin en son başarıyla taranan sayfasının adresi ('' = hiç taranmadı)."""
    return _SON_OKUMA.get(k, "")


def tara(k: str, baslik: str | None = None) -> tuple[dict | None, bool]:
    """Tarayıcı penceresinin sayfasını (erişilebilirlik ağacı; ekran görüntüsü/öne getirme YOK) oku, sınama durumunu yaz.
    → (sonuç | None, okundu). Pencere tarayıcı değilse ya da sayfa okunamazsa okundu=False (mevcut durum KORUNUR: iki
    geçici zaman aşımı yanlış 'kayboldu' üretmesin). Yasak (10) ve DUR (13) yükselir."""
    from . import gozlem, web
    from .hata import Dur
    if not k or not web.tarayici_mi(k):
        return None, False
    try:
        web.hazirla(k)
        roller = sorted(web.ETKILESIMLI | {"image"})
        s = web.oku(k, roller=roller, gorunur=True, en_cok=0, ad_siniri=0, ayrinti=False, cerceve_metni=True)
    except Dur as e:
        if e.kod in (10, 13):
            raise
        return None, False
    except Exception:  # noqa: BLE001
        return None, False
    if not s["sayfa"].get("belge"):
        return None, False
    ogeler = [gozlem.web_ogesi(o, web.ETKILESIMLI) for o in s["ogeler"]]
    _SON_OKUMA[k] = s["sayfa"].get("adres") or ""
    baslik = baslik if baslik is not None else baslik_simdi(k) or ""
    sonuc = incele(ogeler, baslik, s["sayfa"])
    ogeleri_isaretle(ogeler, sonuc)
    if sonuc:
        kaydet(k, sonuc, ogeler, baslik=baslik, adres=s["sayfa"].get("adres") or "")
    else:
        yok_kaydet(k, baslik)
    return sonuc, True


def hazir(k: str, baslik: str | None = None) -> dict | None:
    """Girdiden ÖNCE: pencerenin sınama durumu. Durum yoksa ve pencere tarayıcıysa BİR kez tarar; 'sınama yok' sonucu
    pencere+başlık başına YOK_TTL sn önbellekte (her tıkta ağaç taraması yapılmaz). → durum | None."""
    if not k:
        return None
    from .arka_uc import EKRAN
    if k == EKRAN:
        return None
    baslik = baslik if baslik is not None else baslik_simdi(k)
    d = durum(k, baslik=baslik)
    if d is not None or yok_mu(k, baslik):
        return d
    tara(k, baslik)
    return durum(k, baslik=baslik)


# ---------------------------------------------------------------- girdi kapısı

def _kutuda(kutu, nokta) -> bool:
    x, y, w, h = kutu
    return x - 4 <= nokta[0] <= x + w + 4 and y - 4 <= nokta[1] <= y + h + 4


def girdi_engeli(k: str, *, oge: dict | None = None, ad: str | None = None, nokta=None, noktalar=(),
                 klavye: bool = False, baslik: str | None = None, odak_kutusu=None,
                 simdi: float | None = None) -> dict | None:
    """Girdi sınama ögesine mi gidiyor? Evetse sınama sonucu (acik_sonuc biçimi), değilse None.
      oge: observe ögesi (sinama bayrağı); ad: metin/öge adı hedefi (kısa insan-doğrulama cümlesi ise HER durumda, satıcı
      adı ise yalnız sınama algılanmış pencerede); nokta/noktalar: pencere pikseli (algılanan sınama kutularından biri);
      odak_kutusu: odaktaki ögenin kutusu (klavye girdisi: odak sınama kutusundaysa ret: Tab+Boşluk ile işaretleme);
      klavye: hedefsiz klavye girdisi — yalnız sayfanın TAMAMI sınamaysa (ara sayfa) engellenir; baslik: pencerenin
      güncel başlığı (değiştiyse eski algı atılır)."""
    d = durum(k, simdi, baslik=baslik)
    if oge is not None and oge.get("sinama"):
        return acik_sonuc({"kind": (d or {}).get("kind", "captcha"), "window": (d or {}).get("window", baslik or ""),
                           "hint": IPUCU.format(kind=(d or {}).get("kind", "captcha")),
                           "confidence": (d or {}).get("confidence", "high")})
    if d is None:
        if ad and len(katla(ad).split()) <= OCR_KISA and ad_kalibi_mi(ad, oran=KALIP_ORANI):
            return acik_sonuc({"kind": ad_kalibi_mi(ad), "window": baslik or "", "hint": IPUCU.format(
                kind=ad_kalibi_mi(ad)), "confidence": "high"})
        return None
    kind = d.get("kind") or "captcha"
    sonuc = acik_sonuc({"kind": kind, "window": d.get("window") or baslik or "", "hint": IPUCU.format(kind=kind),
                        "confidence": d.get("confidence") or "high"})
    if ad and ad_kalibi_mi(ad, satici=True):
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


def nokta_engeli(k: str, x, y, metinler=()) -> dict | None:
    """ÇEKİRDEK fare kapısı (eylem.hassas_nokta: koordinat, metin, öge, simge, renk, web ve sürükleme başlangıcı için TEK
    nokta): tıklanan NOKTA sınama kutusundaysa → sonuç. Ajanın verdiği ada DEĞİL noktaya bakılır; yalnız kısa metinlerde
    (öge adı + noktadaki yazı) insan-doğrulama cümlesi de reddedilir. Pencerede durum yoksa ve pencere tarayıcıysa girdiden
    önce bir kez taranır (hazir). Pencere kimliği yoksa/masaüstü kipindeyse None."""
    from .arka_uc import EKRAN
    if not k or k == EKRAN:
        return None
    baslik = baslik_simdi(k)
    hazir(k, baslik)
    kisa = [m for m in (metinler or ()) if m and len(katla(m).split()) <= OCR_KISA]
    nokta = (x, y) if x is not None and y is not None else None
    for m in kisa or (None,):
        r = girdi_engeli(k, ad=m, nokta=nokta, baslik=baslik)
        if r is not None:
            return r
    return None


def odakli_oge(k: str) -> dict | None:
    """Tarayıcı sayfasında ODAKTAKİ ögenin {"rol","ad","kutu"} (pencere pikseli) | None. Yalnız sınama durumu VARKEN çağrılır
    (Tab+Boşluk ile sınama kutusunu işaretlemeyi kapatmak için); erişilebilirlik ağacının 'focused' durumu kullanılır."""
    from . import web
    if not web.tarayici_mi(k):
        return None
    web.hazirla(k)
    s = web.oku(k, roller=sorted(web.ETKILESIMLI | {"image"}), gorunur=True, en_cok=0, ad_siniri=0, ayrinti=False)
    for o in s["ogeler"]:
        if "odakli" in (o.get("durum") or ()) and o.get("kutu"):
            return {"rol": o["rol"], "ad": o["ad"], "kutu": list(o["kutu"])}
    return None


def klavye_engeli(k: str, odak_sorgu=None) -> dict | None:
    """ÇEKİRDEK klavye kapısı (tuş / yazı / bas): sayfanın tamamı sınamaysa ya da ODAK sınama kutusundaysa (onay kutusu,
    kaydırıcı, sınama çerçevesi içi, resimli güvenlik kodu giriş alanı) → sonuç. odak_sorgu: çağıranın verdiği, odaktaki
    ögenin {"kutu": [x,y,w,h]} bilgisini döndüren işlev (AT-SPI; yalnız sınama durumu VARKEN çağrılır: durum yoksa
    ek maliyet yok)."""
    from .arka_uc import EKRAN
    if not k or k == EKRAN:
        return None
    baslik = baslik_simdi(k)
    d = hazir(k, baslik)
    if d is None:
        return None
    if d.get("page_wide"):
        return girdi_engeli(k, klavye=True, baslik=baslik)
    kutu = None
    try:
        kutu = ((odak_sorgu or (lambda: odakli_oge(k)))() or {}).get("kutu")
    except Exception:  # noqa: BLE001 - odak okunamadıysa yalnız sayfa geneli kuralı
        kutu = None
    return girdi_engeli(k, klavye=True, baslik=baslik, odak_kutusu=kutu if kutu and len(kutu) == 4 else None)


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
    """[18] hata iletisi (kullanıcıya/ajana; çevrilir)."""
    return _("insan doğrulaması ({kind}): kullanıcıya devret — request_human kullan; girdi gönderilmedi").format(
        kind=s["kind"])
