"""MCP `observe`: tek çağrıda birleşik gözlem (erişilebilirlik ağacı + web sayfası + gerektiğinde OCR) ve anlık görüntü
önbelleği (`snapshot_id`, öge kimliği `ref` = `<snapshot_id>:N`). docs/ARCHITECTURE.md §10.

- Kaynaklar MEVCUT güvenli okuyuculardır (yeni okuma yolu yok): genel uygulamalar `erisim.erisim_ogeleri` (çerçeve
  yalnız pencerenin süreç ağacından; panel/yasak çerçeve 10), tarayıcı belgesi `web.oku` (aynı kurallar), OCR
  `api.metin_oku` (yasak pencereler maskeli/çıkarılmış). Parola alanının (`password text`) değeri hiçbir yolda okunmaz.
- Öge kimliği: erişilebilirlik ögesinde veri yolu adı + nesne yolu (BİRLİKTE) + pencere; OCR satırında metin + kutu.
- Önbellek: pencere başına en çok 4, toplam 16 anlık görüntü, ömür 120 sn. `ref` ile eylemde öge güncel ağaçtan
  YENİDEN doğrulanır (erisim.ref_oge_sec); bu modül yalnız anlık görüntü düzeyini (bilinmiyor/eski/pencere) çözer.
Saf kısımlar (biçim, süzme, fark, önbellek) ekran bilmez; testler sentetik ögelerle çalışır."""
from __future__ import annotations

import difflib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict

from .ocr import katla

ONEK = secrets.token_hex(2)  # sunucu (süreç) başına: başka/yeniden başlamış sunucunun ref'i tanınmaz
OMUR = 120.0
PENCERE_BASINA = 4
TOPLAM = 16
AD_SINIRI = 80  # satır içi ad kırpma (yapılandırılmış alanda da); doğrulama tam adla yapılır
DEGER_SINIRI = 60
KUCUK_AGAC = 3  # adı olan bu kadardan az ağaç ögesi varsa OCR kendiliğinden eklenir
KUTU_PAYI = 3  # px: fark (~) ve ref doğrulamasında kutu toleransı (erisim.REF_PAYI ile aynı)
REF_DESEN = re.compile(r"^([0-9a-f]{4}-\d+):(\d+)$")

# Web belgesinde interactive_only=false iken ek okunan roller (başlık, görsel, etiket, kapsayıcılar: sorgu ataları)
WEB_EK_ROLLER = frozenset({"heading", "image", "label", "static", "dialog", "alert", "form", "list", "list item",
                           "section", "landmark", "table", "row", "cell", "table cell", "paragraph", "article",
                           "grid", "tree", "tool bar", "menu bar", "menu", "status bar", "group", "panel"})
# web.py durum belirteçleri (Türkçe, çevrilmez) → observe belirteçleri
WEB_DURUM = {"devre_disi": "disabled", "isaretli": "checked", "karisik": "mixed", "odakli": "focused",
             "secili": "selected", "basili": "pressed", "acik": "expanded", "kapali": "collapsed",
             "salt_okunur": "readonly", "zorunlu": "required", "gecersiz": "invalid", "ziyaret_edildi": "visited"}
# durum değişince tıklamanın "beklenen etkisi" sayılan roller (effect=confirmed)
DURUMLU_ROLLER = frozenset({"check box", "radio button", "toggle button", "switch", "toggle switch", "page tab",
                            "check menu item", "radio menu item", "tree item", "combo box", "list item",
                            "list item selectable", "option"})
DURUM_ANAHTAR = ("checked", "mixed", "selected", "pressed", "expanded", "collapsed")


def temiz(s) -> str:
    """Görünen metin: nesne yer tutucusu (U+FFFC) ve fazla boşluk atılır; yalnız boşluksa ''."""
    return " ".join(str(s or "").replace("￼", " ").split())


def kisalt(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------------------------------------------------------------- ögeleri tek biçime getirme

def agac_ogesi(o: dict, etkilesimli_roller) -> dict:
    """erisim._tara ögesi → gözlem ögesi."""
    durumlar = list(o.get("durumlar") or [])
    if not o.get("etkin", True):
        durumlar.insert(0, "disabled")
    e = {"rol": o["rol"], "ad": temiz(o.get("ad")), "ad_ham": o.get("ad") or "",
         "kutu": [round(o["x"]), round(o["y"]), round(o["w"]), round(o["h"])], "durumlar": durumlar, "kaynak": "tree", "kimlik": o.get("kimlik"), "yol": list(o.get("yol") or []),
         "etkilesimli": o["rol"] in etkilesimli_roller, "etkin": bool(o.get("etkin", True))}
    if o.get("deger") and o["rol"] != "password text":
        e["deger"] = temiz(o["deger"])
    if o.get("eylemler"):
        e["eylemler"] = [a for a in o["eylemler"] if a]
    return e


def web_ogesi(o: dict, etkilesimli_roller) -> dict:
    """web.oku(yol_ver=True, ad_siniri=0) ögesi → gözlem ögesi."""
    k = o.get("kutu") or [0, 0, 0, 0]
    durumlar = [WEB_DURUM.get(d, d) for d in o.get("durum") or []]
    e = {"rol": o["rol"], "ad": temiz(o.get("ad")), "ad_ham": o.get("ad") or "", "kutu": [round(v) for v in k],
         "durumlar": durumlar, "kaynak": "web", "kimlik": [o["_bus"], o["_yol"]] if o.get("_bus") else None,
         "yol": list(o.get("_anahtar") or []), "etkilesimli": o["rol"] in etkilesimli_roller,
         "etkin": "devre_disi" not in (o.get("durum") or [])}
    if not o.get("gorunur", True):
        e["gorunmez"] = True
    if o.get("cerceve"):
        e["cerceve"] = o["cerceve"]  # iç içe belge (iframe) derinliği: insan doğrulaması algısı kullanır
    if o.get("_belge_adres"):
        e["belge_adres"] = o["_belge_adres"]  # ögenin ait olduğu iframe belgesinin adresi (yalnız iç algı; ajana çıkmaz)
    if o.get("deger") and o["rol"] != "password text":
        e["deger"] = temiz(o["deger"])
    if o.get("href"):
        e["href"] = o["href"]
    return e


def ocr_ogesi(s: dict) -> dict:
    """api.metin_oku satırı → gözlem ögesi ("ögesiz yazı": ağaçta olmayan görünür metin; tıklanabilir hedef)."""
    return {"rol": "ocr_text", "ad": temiz(s["text"]), "kutu": [round(v) for v in s["box"]], "durumlar": [],
            "kaynak": "ocr", "kimlik": None, "yol": [], "etkilesimli": True, "etkin": True}


def anahtar(o: dict) -> tuple:
    """Anlık görüntüler arası öge kimliği (fark için): erişilebilirlik nesnesi ya da OCR metni + kaba konum."""
    if o["kaynak"] == "ocr":
        x, y, w, h = o["kutu"]
        return ("ocr", katla(o["ad"]), round((x + w / 2) / 12), round((y + h / 2) / 12))
    if o.get("kimlik"):
        return ("a11y", *o["kimlik"])
    return ("yol", o["kaynak"], tuple(o.get("yol") or ()), o["rol"])


def ocr_ayikla(agac: list[dict], satirlar: list[dict]) -> list[dict]:
    """Ağaçta zaten olan yazıları OCR'dan çıkar: satırın merkezi bir ögenin kutusunda ve metni o ögenin adı/değeriyle
    örtüşüyorsa (biri ötekini içeriyor ya da benzerlik ≥ 0,8)."""
    sonuc = []
    for s in satirlar:
        x, y, w, h = s["kutu"]
        cx, cy = x + w / 2, y + h / 2
        t = katla(s["ad"])
        if not t:
            continue
        ayni = False
        for o in agac:
            ox, oy, ow, oh = o["kutu"]
            if not (ox <= cx < ox + ow and oy <= cy < oy + oh):
                continue
            for m in (o.get("ad"), o.get("deger")):
                m = katla(m or "")
                if m and (t in m or m in t or difflib.SequenceMatcher(None, t, m).ratio() >= 0.8):
                    ayni = True
                    break
            if ayni:
                break
        if not ayni:
            sonuc.append(s)
    return sorted(sonuc, key=lambda o: (o["kutu"][1], o["kutu"][0]))


def sorgu_suz(ogeler: list[dict], sorgu: str, etkilesimli: bool = False) -> list[dict]:
    """`a|b` (büyük/küçük harf ve Türkçe harf duyarsız): adı, değeri ya da rolü bir seçeneği içeren ögeler (etkilesimli:
    yalnız etkileşimli olanlar) + bunların ADI OLAN ataları (çocuk-sıra yolu önek: hangi iletişim kutusu/bölüm),
    belge sırasında."""
    secenekler = [katla(p) for p in sorgu.split("|") if katla(p)]
    if not secenekler:
        return gorunur_suz(ogeler, etkilesimli)
    eslesen = set()
    for i, o in enumerate(ogeler):
        if etkilesimli and not o["etkilesimli"]:
            continue
        alanlar = (katla(o.get("ad") or ""), katla(o.get("deger") or ""), katla(o["rol"]))
        if any(s in a for s in secenekler for a in alanlar if a):
            eslesen.add(i)
    atalar = set()
    yollar_ = [(tuple(ogeler[i].get("yol") or ()), ogeler[i]["kaynak"]) for i in eslesen]
    for j, o in enumerate(ogeler):
        y = tuple(o.get("yol") or ())
        if j in eslesen or not y or o["kaynak"] == "ocr" or not o.get("ad"):
            continue
        if any(len(y) < len(m) and m[:len(y)] == y and kay == o["kaynak"] for m, kay in yollar_):
            atalar.add(j)
    return [o for i, o in enumerate(ogeler) if i in eslesen or i in atalar]


def gorunur_suz(ogeler: list[dict], etkilesimli: bool) -> list[dict]:
    """interactive_only: yalnız etkileşimli roller; değilse adsız/değersiz etkileşimsiz ögeler (boş kapsayıcılar)
    atılır. Ağaçtan gelmiş ama adı da değeri de olmayan etkileşimli öge (yazısız simge düğmesi) KALIR."""
    if etkilesimli:
        return [o for o in ogeler if o["etkilesimli"]]
    return [o for o in ogeler if o["etkilesimli"] or o.get("ad") or o.get("deger")]


# ---------------------------------------------------------------- biçim

def satir(o: dict, n: int) -> str:
    """Kısa satır (observe'un TEK çıktısı; yapılandırılmış kopyası gönderilmez):
    `[N] rol "ad" @x,y,w,h durum,durum = "değer" !sensitive (ocr) (offscreen) href="…"` (boş alanlar yok). Kutu her
    zaman ad/rolden hemen sonra: adsız ögede rol (boşluk içerebilir) ile durumlar `@` ile ayrılır."""
    p = [f"[{n}]", o["rol"]]
    if o.get("ad"):
        p.append(json.dumps(kisalt(o["ad"], AD_SINIRI), ensure_ascii=False))
    p.append("@" + ",".join(str(int(v)) for v in o["kutu"]))
    if o.get("durumlar"):
        p.append(",".join(o["durumlar"]))
    if o.get("deger"):
        p.append("= " + json.dumps(kisalt(o["deger"], DEGER_SINIRI), ensure_ascii=False))
    if o.get("hassas"):
        p.append("!sensitive")
    if o.get("sinama"):
        p.append("!human-verification")
    if o["kaynak"] == "ocr":
        p.append("(ocr)")
    if o.get("gorunmez"):
        p.append("(offscreen)")
    if o.get("href"):
        p.append("href=" + json.dumps(kisalt(o["href"], 120), ensure_ascii=False))
    return " ".join(p)


def yapisal(o: dict, sid: str, n: int) -> dict:
    """Yapılandırılmış öge (boş/varsayılan alanlar atılır)."""
    e = {"ref": f"{sid}:{n}", "role": o["rol"]}
    if o.get("ad"):
        e["name"] = kisalt(o["ad"], AD_SINIRI)
    if o.get("deger"):
        e["value"] = kisalt(o["deger"], DEGER_SINIRI * 3)
    if o.get("durumlar"):
        e["states"] = list(o["durumlar"])
    e["frame"] = list(o["kutu"])
    if o.get("gorunmez"):
        e["visible"] = False
    if o.get("eylemler"):
        e["actions"] = list(o["eylemler"])
    if o.get("hassas"):
        e["sensitive"] = True
    if o.get("sinama"):
        e["human_verification"] = True
    if o.get("href"):
        e["href"] = kisalt(o["href"], 200)
    if o["kaynak"] == "ocr":
        e["source"] = "ocr"
    return e


# ---------------------------------------------------------------- anlık görüntü önbelleği

_SAYAC = re.compile(r"(?:%\s*)?\d+(?:[.,]\d+)*(?:\s*%)?")
_SAYAC_PAREN = re.compile(r"[(\[]\s*#\s*[)\]]")


def baslik_norm(b: str | None) -> str:
    """Pencere başlığını sayaçlardan arındır: rakam dizileri/yüzdeler → '#', parantez içi salt sayaç atılır, boşluklar
    sadeleşir. "(3) Gmail" ≡ "(4) Gmail" ≡ "Gmail"; "İndiriliyor %45" ≡ "%46"; ama "A.txt — KWrite" ≠ "B.txt — KWrite"."""
    s = _SAYAC.sub("#", b or "")
    s = _SAYAC_PAREN.sub(" ", s)
    return " ".join(s.split())


class Anlik:
    """Bir observe sonucu: pencere, masaüstü, pencere boyutu, ögeler (numara = sıra + 1)."""
    __slots__ = ("sid", "k", "masaustu", "boyut", "baslik", "zaman", "ogeler", "anahtarlar", "adres")

    def __init__(self, sid, k, masaustu, boyut, baslik, ogeler, adres=None):
        self.sid, self.k, self.masaustu, self.boyut, self.baslik = sid, k, masaustu, tuple(boyut), baslik
        self.adres = adres or None  # web belgesinin adresi (parça dahil); web ref'lerinde bağlam denetimi
        self.zaman = time.monotonic()
        self.ogeler = ogeler
        self.anahtarlar = {anahtar(o): i for i, o in enumerate(ogeler)}

    def oge(self, n: int) -> dict | None:
        return self.ogeler[n - 1] if 1 <= n <= len(self.ogeler) else None


class Depo:
    """Anlık görüntüler: pencere başına en çok PENCERE_BASINA, toplam TOPLAM, ömür OMUR sn."""

    def __init__(self, pencere_basina=PENCERE_BASINA, toplam=TOPLAM, omur=OMUR):
        self._d: OrderedDict[str, Anlik] = OrderedDict()
        self._kilit = threading.Lock()
        self._sayac = 0
        self.pencere_basina, self.toplam, self.omur = pencere_basina, toplam, omur

    def yeni_kimlik(self) -> str:
        with self._kilit:
            self._sayac += 1
            return f"{ONEK}-{self._sayac}"

    def ekle(self, a: Anlik) -> None:
        with self._kilit:
            self._d[a.sid] = a
            ayni = [s for s, x in self._d.items() if x.k == a.k and x.masaustu == a.masaustu]
            for s in ayni[:-self.pencere_basina]:
                del self._d[s]
            while len(self._d) > self.toplam:
                self._d.popitem(last=False)

    def al(self, sid: str) -> tuple[Anlik | None, str]:
        """→ (anlık, "") | (None, "unknown" | "expired")."""
        with self._kilit:
            a = self._d.get(sid)
            if a is None:
                return None, "unknown"
            if time.monotonic() - a.zaman > self.omur:
                del self._d[sid]
                return None, "expired"
            return a, ""

    def temizle(self, masaustu: str | None = None) -> None:
        with self._kilit:
            for s in [s for s, a in self._d.items() if masaustu is None or a.masaustu == masaustu]:
                del self._d[s]


def ref_ayir(ref: str) -> tuple[str, int] | None:
    m = REF_DESEN.match((ref or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


# ---------------------------------------------------------------- fark (since)

def _kutu_oynadi(a, b) -> bool:
    return any(abs(x - y) > KUTU_PAYI for x, y in zip(a, b))


def fark(eski: Anlik, yeni_ogeler: list[dict]) -> tuple[list[int], list[int], list[int]]:
    """→ (eklenen yeni sıraları, değişen yeni sıraları, kaybolan ESKİ sıraları); sıralar 0 tabanlı."""
    eklenen, degisen = [], []
    gorulen = set()
    for i, o in enumerate(yeni_ogeler):
        j = eski.anahtarlar.get(anahtar(o))
        if j is None:
            eklenen.append(i)
            continue
        gorulen.add(j)
        e = eski.ogeler[j]
        if (e.get("ad") != o.get("ad") or e.get("deger") != o.get("deger") or e.get("durumlar") != o.get("durumlar")
                or _kutu_oynadi(e["kutu"], o["kutu"])):
            degisen.append(i)
    kaybolan = [j for j in range(len(eski.ogeler)) if j not in gorulen]
    return eklenen, degisen, kaybolan


def durum_degisti(once: dict, sonra: dict) -> bool:
    """Tıklamadan önce/sonra ögenin durum belirteçleri (checked/selected/expanded…) farklı mı?"""
    a = {d for d in once.get("durumlar") or () if d in DURUM_ANAHTAR}
    b = {d for d in sonra.get("durumlar") or () if d in DURUM_ANAHTAR}
    return a != b


# ---------------------------------------------------------------- numaralı ekran görüntüsü (Set-of-Marks)

RENKLER = ((230, 25, 75), (0, 130, 200), (60, 160, 60), (245, 130, 48), (145, 30, 180), (0, 128, 128))


def isaretle(im, numarali: list[tuple[int, dict]], kok=(0, 0), olcek: float = 1.0):
    """Ögelerin kutularını ve numaralarını görüntüye çiz (görüntü pikseli = (pencere pikseli − kök) × ölçek).
    Görüntü önceden maskelenmiş olmalı (yasak pencereler siyah): çizim maskenin ÜSTÜNE yazı koymaz."""
    from PIL import ImageDraw
    from .gorsel import font
    im = im.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    f = font(max(10, round(13 * max(olcek, 0.75))))
    for n, o in numarali:
        x, y, w, h = o["kutu"]
        x0, y0 = (x - kok[0]) * olcek, (y - kok[1]) * olcek
        x1, y1 = x0 + w * olcek, y0 + h * olcek
        if x1 < 0 or y1 < 0 or x0 >= im.width or y0 >= im.height:
            continue
        renk = RENKLER[n % len(RENKLER)]
        d.rectangle([x0, y0, x1, y1], outline=renk, width=2)
        etiket = str(n)
        tx0, ty0, tx1, ty1 = d.textbbox((0, 0), etiket, font=f)
        lw, lh = tx1 - tx0 + 4, ty1 - ty0 + 2
        lx, ly = max(0, min(im.width - lw, x0)), max(0, y0 - lh if y0 - lh >= 0 else y0)
        d.rectangle([lx, ly, lx + lw, ly + lh], fill=renk)
        d.text((lx + 2 - tx0, ly + 1 - ty0), etiket, fill=(255, 255, 255), font=f)
    return im
