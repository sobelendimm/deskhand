"""test_gozlem.py / test_toplu.py ortak sahte masaüstü: süreç içi sahte kde arka ucu + sahte AT-SPI yürütücüsü + sahte
onay. Gerçek ekrana, panele, dotool'a, AT-SPI veri yoluna ve kullanıcının oturum ayarlarına HİÇBİR şey gitmez:
girdi satırları `au.satirlar` listesine yazılır, erişilebilirlik istekleri `ISLEMLER`'e, onay istekleri `ISTEKLER`'e.

Kullanım (testin başında, _yalitim'den SONRA):  import sahte_masaustu as sm; au = sm.kur()"""
from __future__ import annotations

import copy
import os
import re
import time

from PIL import Image, ImageDraw

from deskhand import arka_uc, erisim, eylem, guvenlik, hata, onay, yollar
from deskhand.arka_uc import EKRAN, ArkaUc
from deskhand.hata import Dur

PENCERE = "{sahte-1}"
GEO = (100, 100, 800, 600)


class SahteGirdi:
    def __init__(self, au, etiket="", gizli=False, etk=None, denetle=None):
        self.au, self.etiket, self.gizli, self.denetle = au, etiket, gizli, denetle
        self.etk, self.kesildi, self.hazir = None, None, True
        self.son_etk = time.monotonic()
        self.son_fare = au.fare()[:2]

    def _satir(self, s):
        if s.startswith("mouseto "):
            fx, fy = map(float, s.split()[1:3])
            x0, y0, x1, y1 = self.au.ekran_alani()
            self.au.imlec = (int(x0 + fx * (x1 - x0)), int(y0 + fy * (y1 - y0)))
        self.au.satirlar.append(s)
        if self.au.kanca_satir:
            self.au.kanca_satir(s)

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        self.au.ekran_korumasi("girdi")  # kde Girdi.gonder: oyun/film koruması (15)
        self.etk_denetle()
        for s in satirlar:
            self._satir(s)

    def ham(self, s):
        hata.dur_denetle()
        self._satir(s)

    def zorla(self, s):
        self.au.satirlar.append(s)

    def izle(self, k, desen, fare_izle=True):
        pass

    def izle_bitir(self):
        pass

    def etk_denetle(self, ne="girdi gönderilmedi"):
        if self.au.insan:
            raise Dur(12, f"kullanıcı klavye/fare kullanıyor; {ne}")

    def insan_kontrol(self):
        self.etk_denetle()

    def kapat(self):
        self.au.kapanan += 1


class SahtePopen:
    pid = 4242

    def poll(self):
        return None


def oge(rol, ad, x, y, w=120, h=30, kimlik=None, etkin=True, durumlar=(), eylemler=("Press",), deger=None, yol=None):
    o = {"rol": rol, "ad": ad, "x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2, "etkin": etkin,
         "derinlik": len(yol or [0]), "yol": list(yol or [0]), "kimlik": list(kimlik) if kimlik else None,
         "durumlar": list(durumlar), "eylemler": list(eylemler)}
    if deger is not None:
        o["deger"] = deger
    return o


def varsayilan_agac():
    return [
        oge("label", "Form başlığı", 20, 10, 300, 24, kimlik=(":1.9", "/a/0"), eylemler=(), yol=[0]),
        oge("push button", "Kaydet", 80, 100, 160, 40, kimlik=(":1.9", "/a/1"), yol=[1, 0]),
        oge("push button", "Satın al", 400, 100, 160, 40, kimlik=(":1.9", "/a/2"), yol=[1, 1]),
        oge("text", "Ad", 80, 200, 300, 30, kimlik=(":1.9", "/a/3"), eylemler=("Set Focus",), deger="Ali", yol=[1, 2]),
        oge("password text", "Parola", 80, 250, 300, 30, kimlik=(":1.9", "/a/4"), eylemler=("Set Focus",), yol=[1, 3]),
        oge("check box", "Onayla", 80, 300, 160, 30, kimlik=(":1.9", "/a/5"), eylemler=("Toggle",), yol=[1, 4]),
        oge("list item", "Liste bir", 80, 400, 200, 30, kimlik=(":1.9", "/a/6"), eylemler=(), yol=[2, 0]),
        oge("list item", "Liste iki", 80, 440, 200, 30, kimlik=(":1.9", "/a/7"), eylemler=(), yol=[2, 1]),
        oge("push button", "Bırak", 500, 400, 160, 40, kimlik=(":1.9", "/a/8"), yol=[2, 2]),
    ]


class SahteArkaUc(ArkaUc):
    """kde yerine: 1920x1080 ekran, pencereler, yazılı görüntü. Hiçbir gerçek araç çağrılmaz."""
    ad = "kde"

    def __init__(self):
        self.pen = {PENCERE: ["Belge — KWrite", "kwrite", GEO]}
        self.aktif_ = PENCERE
        self.imlec = (5, 5)
        self.satirlar, self.kapanan, self.insan, self.baslatilan = [], 0, False, []
        self.pid_ = {}
        self.koruma = None
        self.kanca_satir = None
        self.yazilar = {PENCERE: [("Kaydet", 90, 105), ("Satın al", 410, 105), ("Bırak", 510, 405)]}

    def pencere_coz(self, arg):
        if arg in self.pen:
            return arg
        if arg.lower() in ("ekran", "masaustu"):
            return EKRAN
        uy = [k for k, (b, _s, _g) in self.pen.items() if re.search(arg, b, re.I)]
        if not uy:
            raise Dur(8, f"'{arg}' yok")
        if len(uy) > 1:
            raise Dur(5, "birden çok")
        return uy[0]

    def pencereler(self, desen=None):
        return [(k, b, g) for k, (b, _s, g) in self.pen.items() if not desen or re.search(desen, b, re.I)]

    def geometri(self, k):
        if k == EKRAN:
            return (0, 0, 1920, 1080)
        if k not in self.pen:
            raise Dur(8, "pencere yok")
        return self.pen[k][2]

    def baslik(self, k):
        return self.pen.get(k, [""])[0] if k != EKRAN else "EKRAN"

    def sinif(self, k):
        return self.pen.get(k, ["", ""])[1]

    def aktif(self):
        return self.aktif_

    def one_getir(self, k):
        if k != EKRAN:
            self.aktif_ = k

    def kapat(self, k):
        self.pen.pop(k, None)

    def pid(self, k):
        return self.pid_.get(k, "4242")

    def fare(self):
        x, y = self.imlec
        alt = next((k for k, (_b, _s, (X, Y, W, H)) in self.pen.items() if X <= x < X + W and Y <= y < Y + H), "")
        return x, y, alt

    def ekran_alani(self):
        return (0, 0, 1920, 1080)

    def goruntu(self):
        from deskhand.gorsel import font
        im = Image.new("RGB", (1920, 1080), (60, 60, 60))
        d = ImageDraw.Draw(im)
        f = font(30)
        for k, (_b, _s, (X, Y, W, H)) in self.pen.items():
            d.rectangle([X, Y, X + W - 1, Y + H - 1], fill=(245, 245, 245))
            for t, x, y in self.yazilar.get(k, []):
                d.text((X + x, Y + y), t, fill=(0, 0, 0), font=f)
        return im

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        return SahteGirdi(self, etiket, gizli, etk, denetle)

    def insan_var_mi(self):
        return self.insan

    def ekran_korumasi(self, ne):
        if self.koruma:
            raise Dur(*self.koruma)

    def baslat(self, argv, env=None, cikti=None):
        self.baslatilan.append((list(argv), dict(env or {})))
        return SahtePopen()


# ---------------------------------------------------------------- sahte AT-SPI (erisim._atspi_calistir yerine)

AGAC: dict[str, list] = {}  # pencere başlığı → ögeler (erisim._tara biçimi)
AGACSIZ: set[str] = set()  # bu başlıklı pencerelerin uygulaması ağaçta yok (Dur 6 agacta_yok → OCR)
ISLEMLER: list = []
TERMINAL_SATIR = ["kullanici@makine:~$ sud"]
AU: list = []  # [SahteArkaUc]


def _bul(baslik, istek):
    for o in AGAC.get(baslik, []):
        if o["yol"] == istek.get("yol") and o["rol"] == istek.get("rol") and o["ad"] == istek.get("ad"):
            return o
    raise Dur(8, "öge artık yok ya da değişti (arayüz güncellendi): yeniden ara")


def sahte_calistir(istek):
    baslik, islem = istek["baslik"], istek["islem"]
    if baslik in AGACSIZ:
        raise Dur(6, f"pencere erişilebilirlik ağacında yok ({baslik!r})", tur="agacta_yok")
    if islem == "tara":
        ISLEMLER.append(("tara", baslik))
        ogeler = copy.deepcopy(AGAC.get(baslik, []))
        if not istek.get("ayrinti"):
            for o in ogeler:
                o.pop("durumlar", None)
                o.pop("eylemler", None)
                o.pop("deger", None)
        if not (istek.get("kimlik_ver") or istek.get("ayrinti")):
            for o in ogeler:
                o.pop("kimlik", None)
        return {"ogeler": ogeler, "sure": 0.01, "cerceve_kimlik": None}
    if islem == "satir":
        return list(TERMINAL_SATIR)
    if islem == "odak_parola":
        au = AU[0]
        k = next((k for k, v in au.pen.items() if v[0] == baslik), None)
        if k is None:
            return False
        X, Y, _w, _h = au.pen[k][2]
        x, y = au.imlec[0] - X, au.imlec[1] - Y
        return any(o["rol"] == "password text" and o["x"] <= x < o["x"] + o["w"] and o["y"] <= y < o["y"] + o["h"]
                   for o in AGAC.get(baslik, []))
    o = _bul(baslik, istek)
    ISLEMLER.append((islem, o["ad"], istek.get("eylem") or istek.get("metin")))
    if islem == "incele":
        return {"ad": o["ad"], "rol": o["rol"], "aciklama": "", "cocuklar": [], "eylemler": o["eylemler"],
                "yazilabilir": o["rol"] in ("text", "password text", "entry")}
    if islem == "eylem":
        if o["rol"] == "check box":
            if "checked" in o["durumlar"]:
                o["durumlar"].remove("checked")
            else:
                o["durumlar"].append("checked")
        return {"eylem": istek.get("eylem") or o["eylemler"][0], "eylemler": o["eylemler"], "tamam": True}
    if islem == "yaz":
        if o["rol"] != "password text":
            o["deger"] = istek["metin"]
        return {"yontem": "EditableText", "dogrulandi": o["rol"] != "password text"}
    raise AssertionError(islem)


def eylemler():
    return [i for i in ISLEMLER if i[0] in ("eylem", "yaz")]


# ---------------------------------------------------------------- sahte onay

ISTEKLER: list = []
YANIT = {"izin": False, "kanca": None}


def sahte_iste_sonuc(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
    ISTEKLER.append({"eylem": eylem_, "hedef": hedef, "ayrinti": ayrinti})
    if YANIT["kanca"]:
        YANIT["kanca"]()
    return onay.OnaySonucu(YANIT["izin"], "izin" if YANIT["izin"] else "red")


def kur():
    """Sahteleri yerleştir → SahteArkaUc (kde). Kullanıcının gerçek erişilebilirlik ayarı okunmaz/yazılmaz."""
    erisim._atspi_calistir = sahte_calistir
    erisim.erisim_ac_garanti = lambda: False
    erisim.erisim_acik = lambda: True
    erisim._a11y_adresi = lambda: ""
    erisim.nokta_metni = lambda k, x, y: []
    eylem.nokta_metni = lambda k, x, y: []
    onay.iste_sonuc = sahte_iste_sonuc
    onay.bekleyen_var = lambda *a, **k: False
    import deskhand.mesgul as mesgul
    mesgul.karar = lambda ozet: "on"
    mesgul.durum = lambda esik=None: {"mesgul": False, "nedenler": [], "ayrinti": {}}
    return sifirla()


def sifirla(baslik="Belge — KWrite", sinif="kwrite"):
    """Her senaryodan önce: yeni sahte arka uç, ağaç, onay yanıtı; DUR/yasak/seviye dosyaları temiz."""
    au = SahteArkaUc()
    au.pen[PENCERE][0], au.pen[PENCERE][1] = baslik, sinif
    arka_uc._ORNEKLER["kde"] = au
    AU[:] = [au]
    AGAC.clear()
    AGAC[baslik] = varsayilan_agac()
    AGACSIZ.clear()
    ISLEMLER.clear()
    ISTEKLER.clear()
    YANIT.update(izin=False, kanca=None)
    for kaynak in ("kullanici", "cli"):
        guvenlik.dur_kapat(kaynak)
    for yol in (yollar.yasak_dosya(), yollar.seviye_dosya()):
        if os.path.exists(yol):
            os.remove(yol)
    from deskhand import kendi, mcp_sunucu
    kendi.sifirla()
    guvenlik._SISTEM_ONBELLEK.clear()  # sistem istemi sınıfı 2 sn önbellekte: senaryolar arası taşınmasın
    mcp_sunucu._BEKLEYEN.clear()
    mcp_sunucu._DONGU.temizle()
    mcp_sunucu._SECIM.clear()
    return au
