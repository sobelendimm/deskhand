"""İnsan doğrulaması (CAPTCHA) sınamalarını ALGILAR; ÇÖZMEZ, atlatmaz (docs/ARCHITECTURE.md §13).

Politika (değişmez): "insan olduğunuzu doğrulayın" sınamaları görsel, sesli ya da başka yolla çözülmez. Bu modül yalnız
ALGILAR; araç katmanı (mcp_sunucu) algılanınca ajan girdisini REDDEDER (kod 17), `request_human` kullanıcıya DEVRETTİĞİNDE
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

import re
import threading
import time

from .i18n import _
from .ocr import katla

# ---------------------------------------------------------------- kalıplar (katla'lı metne: küçük harf, aksansız, noktalama boşluk)

BASLIK_KALIBI = re.compile(
    r"^(just a moment|bir dakika lutfen|un instant|einen moment|un momento|um momento|attention required|"
    r"verifying you are human|performing security verification|checking your browser|checking if the site connection is secure|"
    r"one more step|ddos protection by|security check|bir saniye lutfen|guvenlik dogrulamasi)\b")
BASLIK_UZUNLUK = 90  # daha uzun başlık "Just a moment…" ara sayfası olamaz (blog başlığı)

ROBOT_DEGIL = re.compile(
    r"\b(i m not a robot|i am not a robot|im not a robot|i am not a bot|i m not a bot|i am human|i m human|"
    r"verify you are human|verify you re human|verify that you are human|verify you are not a robot|"
    r"verify you are not a bot|verifying you are human|confirm you are human|confirm you are not a robot|"
    r"prove you are human|prove you re human|please verify you are a human|are you human|are you a human|"
    r"human verification|ben robot degilim|robot degilim|bot degilim|insan oldugunuzu dogrulay[a-z]*|"
    r"insan oldugunuzu onaylay[a-z]*|insan oldugunuzu kanitlay[a-z]*|insan oldugunuzdan emin|"
    r"ich bin kein roboter|je ne suis pas un robot|no soy un robot)\b")
SURUKLE = re.compile(
    r"\b(slide to verify|slide to complete|slide right to|slide the (puzzle|slider)|drag the slider|drag the puzzle|"
    r"drag the piece|drag to complete|complete the puzzle to|move the slider|kaydirarak dogrula|surukleyerek dogrula|"
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
GORUNMEZ_ADRES = re.compile(r"[?&#]size=invisible\b|[?&]badge=", re.I)  # reCAPTCHA v3 / görünmez hCaptcha rozeti

KUTU_ROLLERI = frozenset({"check box", "toggle button", "button", "push button", "switch", "toggle switch", "slider",
                          "radio button", "internal frame", "document frame", "image map", "canvas", "image"})
SURUKLE_ROLLERI = frozenset({"slider", "button", "push button", "toggle button", "image", "canvas", "internal frame"})
OCR_KISA = 8  # OCR satırı en çok bu kadar sözcük: tek başına duran etiket, paragraf değil

NEDEN_YOK = "no_challenge"

IPUCU = ("A human-verification challenge ({kind}) is on this page. Never click, type or drag in it and never try to "
         "solve it. Call request_human(reason, window): the user solves it in the Deskhand panel (or on their screen) "
         "and the call returns when it is done. The rest of the page can still be read.")


def ad_kalibi_mi(ad: str, satici: bool = False) -> str | None:
    """Öge adı sınama kalıbıyla eşleşiyor mu? → tür ("human_checkbox" | "slider_puzzle" | satıcı türü) | None.
    satici=False: yalnız insan-doğrulama CÜMLELERİ (metinle tıklama/yazı hedefi için yeterince özgül)."""
    n = katla(ad or "")
    if not n:
        return None
    if ROBOT_DEGIL.search(n):
        return "human_checkbox"
    if SURUKLE.search(n):
        return "slider_puzzle"
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


def _cerceve_icinde(o: dict) -> bool:
    try:
        return int(o.get("cerceve") or 0) >= 1
    except (TypeError, ValueError):
        return False


def _rol(o: dict) -> str:
    return str(o.get("rol") or o.get("role") or "")


def _ad(o: dict) -> str:
    return str(o.get("ad_ham") or o.get("ad") or o.get("name") or o.get("text") or "")


def incele(ogeler, baslik: str = "", sayfa: dict | None = None) -> dict | None:
    """Gözlem ögeleri (gozlem.web_ogesi/agac_ogesi/ocr_ogesi biçimi: rol, ad, kutu, cerceve; ham web/read_text ögeleri de
    olur), pencere başlığı ve sayfa özeti (web.oku()["sayfa"]: baslik, adres, cerceveler) → algılanan sınama ya da None.

    Sonuç: {"detected": True, "kind", "window", "hint", "confidence", "page_wide": bool, "elements": [ögeler listesindeki
    sıra numaraları (sınama ögeleri)]}. Saf işlev (G/Ç yok)."""
    sayfa = sayfa or {}
    ogeler = list(ogeler or ())
    turler: list[str] = []
    tam_sayfa = False
    guven = "high"
    isaretli: set[int] = set()
    cerceve_var = False
    for b in (baslik, sayfa.get("baslik"), sayfa.get("pencere")):
        if baslik_mi(b):
            tam_sayfa = True
            turler.append("cloudflare_interstitial")
            break
    for c in sayfa.get("cerceveler") or ():
        t = adres_turu(c.get("adres") if isinstance(c, dict) else c)
        if t:
            cerceve_var = True
            turler.append(t)
    for i, o in enumerate(ogeler):
        rol, ad = _rol(o), _ad(o)
        if not ad:
            continue
        kapta = _cerceve_icinde(o)
        ocr = rol == "ocr_text" or o.get("kaynak") == "ocr"
        kisa = len(katla(ad).split()) <= OCR_KISA
        kutu_rolu = rol in KUTU_ROLLERI
        t = None
        k = ad_kalibi_mi(ad, satici=False)
        if k == "human_checkbox" and (kutu_rolu or kapta or (ocr and kisa)):
            t = "human_checkbox"
            if ocr and not kapta:
                guven = "low" if not turler else guven
        elif k == "slider_puzzle" and (rol in SURUKLE_ROLLERI or kapta or (ocr and kisa)):
            t = "slider_puzzle"
        elif k is None:
            s = ad_kalibi_mi(ad, satici=True)
            if s and (kutu_rolu or kapta):
                t = s
        if t:
            isaretli.add(i)
            turler.append(t)
    if not turler:
        return None
    if cerceve_var:  # sınama çerçevesi var: içindeki etkileşimli her öge sınamanın parçası
        for i, o in enumerate(ogeler):
            if _cerceve_icinde(o) and (_rol(o) in KUTU_ROLLERI or o.get("etkilesimli") or _rol(o) in (
                    "entry", "link", "list item selectable", "combo box", "list box")):
                isaretli.add(i)
    oncelik = ("recaptcha", "hcaptcha", "turnstile", "arkose", "geetest", "captcha", "cloudflare_interstitial",
               "human_checkbox", "slider_puzzle")
    tur = min(turler, key=lambda t: oncelik.index(t) if t in oncelik else 99)
    if tur in ("human_checkbox", "slider_puzzle") and not cerceve_var and any(
            t in ("recaptcha", "hcaptcha", "turnstile", "arkose", "geetest", "captcha") for t in turler):
        tur = next(t for t in turler if t not in ("human_checkbox", "slider_puzzle"))
    pencere = (baslik or sayfa.get("baslik") or sayfa.get("pencere") or "")[:120]
    return {"detected": True, "kind": tur, "window": pencere, "hint": IPUCU.format(kind=tur), "confidence": guven,
            "page_wide": tam_sayfa, "elements": sorted(isaretli)}


def acik_sonuc(s: dict | None) -> dict | None:
    """Araç sonucuna konan `human_verification` alanı: {detected, kind, window, hint} (+ confidence)."""
    if not s:
        return None
    return {"detected": True, "kind": s["kind"], "window": s["window"], "hint": s["hint"],
            **({"confidence": s["confidence"]} if s.get("confidence") == "low" else {})}


def ogeleri_isaretle(ogeler: list[dict], s: dict | None) -> None:
    """Sınama ögelerine `sinama=True` koy (observe: bu ögelere ref ile girdi gönderilmez [17])."""
    for i in (s or {}).get("elements", ()):
        if 0 <= i < len(ogeler):
            ogeler[i]["sinama"] = True


# ---------------------------------------------------------------- pencere başına durum (girdi kapısı)

TTL = 300.0  # algının geçerlilik süresi (sn): observe/read_text/wait_for/girdi sonrası kontrol yeniler
_KILIT = threading.Lock()
_DURUM: dict[str, dict] = {}


def kaydet(k: str, s: dict | None, ogeler: list[dict] | None = None, simdi: float | None = None) -> None:
    """Pencere k için sınama durumunu yaz (s None = sınama yok → durum silinir). Kutular PENCERE pikseli."""
    with _KILIT:
        if not s:
            _DURUM.pop(k, None)
            return
        kutular = [list(ogeler[i]["kutu"]) for i in s.get("elements", ()) if ogeler and 0 <= i < len(ogeler)
                   and ogeler[i].get("kutu") and len(ogeler[i]["kutu"]) == 4 and ogeler[i]["kutu"][2] > 0
                   and ogeler[i]["kutu"][3] > 0]
        _DURUM[k] = {**{a: s[a] for a in ("kind", "window", "hint", "confidence", "page_wide")},
                     "kutular": kutular, "zaman": time.monotonic() if simdi is None else simdi}


def temizle(k: str | None = None) -> None:
    with _KILIT:
        if k is None:
            _DURUM.clear()
        else:
            _DURUM.pop(k, None)


def durum(k: str, simdi: float | None = None) -> dict | None:
    """Pencerenin yakın zamanda algılanmış sınaması (TTL içinde) ya da None."""
    with _KILIT:
        d = _DURUM.get(k)
        if d is None:
            return None
        if (time.monotonic() if simdi is None else simdi) - d["zaman"] > TTL:
            del _DURUM[k]
            return None
        return dict(d)


def _kutuda(kutu, nokta) -> bool:
    x, y, w, h = kutu
    return x - 4 <= nokta[0] <= x + w + 4 and y - 4 <= nokta[1] <= y + h + 4


def girdi_engeli(k: str, *, oge: dict | None = None, ad: str | None = None, nokta=None, noktalar=(),
                 klavye: bool = False, baslik: str | None = None, simdi: float | None = None) -> dict | None:
    """Girdi sınama ögesine mi gidiyor? Evetse sınama sonucu (acik_sonuc biçimi), değilse None.
      oge: observe ögesi (sinama bayrağı); ad: metin/öge adı hedefi (insan-doğrulama cümlesi ise HER durumda, satıcı adı
      ise yalnız sınama algılanmış pencerede); nokta/noktalar: pencere pikseli (algılanan sınama kutularından biri);
      klavye: hedefsiz klavye girdisi — yalnız sayfanın TAMAMI sınamaysa (ara sayfa) engellenir (odaktaki öge
      bilinmez; sayfanın başka alanlarına yazmak serbest kalır); baslik: pencerenin güncel başlığı (ara sayfa)."""
    d = durum(k, simdi)
    tam = baslik_mi(baslik)
    if oge is not None and oge.get("sinama"):
        return acik_sonuc({"kind": (d or {}).get("kind", "captcha"), "window": (d or {}).get("window", baslik or ""),
                           "hint": IPUCU.format(kind=(d or {}).get("kind", "captcha")),
                           "confidence": (d or {}).get("confidence", "high")})
    if d is None and not tam:
        if ad and ad_kalibi_mi(ad, satici=False):
            return acik_sonuc({"kind": ad_kalibi_mi(ad), "window": baslik or "", "hint": IPUCU.format(
                kind=ad_kalibi_mi(ad)), "confidence": "high"})
        return None
    kind = (d or {}).get("kind", "cloudflare_interstitial")
    sonuc = acik_sonuc({"kind": kind, "window": (d or {}).get("window") or baslik or "",
                        "hint": IPUCU.format(kind=kind), "confidence": (d or {}).get("confidence", "high")})
    if ad and ad_kalibi_mi(ad, satici=True):
        return sonuc
    pts = [p for p in ([nokta] if nokta is not None else []) + list(noktalar) if p is not None]
    if d is not None:
        for kutu in d["kutular"]:
            if any(_kutuda(kutu, p) for p in pts):
                return sonuc
    if klavye and (tam or (d or {}).get("page_wide")):
        return sonuc
    if tam and (pts or ad):  # ara sayfa: sayfa bir bütün sınama (kutular okunmamış olabilir)
        return sonuc
    return None


# ---------------------------------------------------------------- request_human için kapı (bekleyen devir)

_DEVIR: dict[str, float] = {}


def devir_acik(k: str) -> bool:
    with _KILIT:
        return k in _DEVIR


def devir_baslat(k: str) -> None:
    with _KILIT:
        _DEVIR[k] = time.monotonic()


def devir_bitir(k: str) -> None:
    with _KILIT:
        _DEVIR.pop(k, None)


def red_metni(s: dict) -> str:
    """[17] hata iletisi (kullanıcıya/ajana; çevrilir)."""
    return _("insan doğrulaması ({kind}): kullanıcıya devret — request_human kullan; girdi gönderilmedi").format(
        kind=s["kind"])
