"""Faz 9b testleri: eylem sonrası doğrulama (fark kutusu), döngü kesici, sürükleme, üçlü tık, değiştirici tuşlar.
Kullanıcının GERÇEK ekranına hiçbir girdi gitmez:

A) Birim: deskhand/dongu.py (saf), deskhand/fark.py (sentetik görüntüler), eylem.mod_coz, CLI ayrıştırma, MCP şemaları.
B) GÖRÜNMEZ masaüstünde (Xvfb) tests/yardimci/dogrulama_pencere.py ile MCP araçları süreç içinde:
   changed/changed_region/changed_ratio/new_text, döngü kesici (uyarı 3., ret 6.), verify=False, meşru tekrar (10 tuş),
   gerçek sürükleme, üçlü tık (metin seçimi), ctrl/shift+tık, değiştirici bırakma güvenceleri (DUR/hata), CLI uçtan uca.

Çalıştır:  python3 tests/test_dogrulama.py      (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import asyncio
import atexit
import base64
import io
import json
import os
import re
import subprocess
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from PIL import Image, ImageDraw

from deskhand import api, cli, dongu, eylem, fark, guvenlik, hata, masaustu
from deskhand.arka_uc import sec
from deskhand.hata import Dur

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
PENCERE = os.path.join(KOK, "tests", "yardimci", "dogrulama_pencere.py")
LOG = os.path.join(GECICI, "dogrulama.log")
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


# ================================================================ A) birim: döngü kesici

H1 = ("click", "text", "kaydet", None, "left", (), None)
H2 = ("click", "text", "iptal", None, "left", (), None)


def seri(k, n, hedef=H1, pencere="w1", once="A"):
    return [k.kaydet("click", pencere, hedef, once, False) for _ in range(n)]


k_ = dongu.DonguKesici(ayni_ekran=lambda a, b: a == b)
sayilar = seri(k_, 5)
kontrol("dongu: ardışık sonuçsuz sayaç 1..5", sayilar == [1, 2, 3, 4, 5], str(sayilar))
kontrol("dongu: 3. sonuçsuzda uyarı eşiği (≥3)", sayilar[2] >= dongu.UYARI_ESIK and sayilar[1] < dongu.UYARI_ESIK)
try:
    k_.kontrol("click", "w1", H1, "A")
    red = None
except dongu.DonguReddi as e:
    red = e.sayi
kontrol("dongu: DonguReddi(5)", red == 5, str(red))
k_ = dongu.DonguKesici()
seri(k_, 4)
try:
    k_.kontrol("click", "w1", H1, "A")
    ok4 = True
except dongu.DonguReddi:
    ok4 = False
kontrol("dongu: 4 sonuçsuzdan sonra hâlâ serbest (ret 6. çağrıda)", ok4)

k_ = dongu.DonguKesici()
seri(k_, 5)
k_.kaydet("click", "w1", H2, "A", False)
kontrol("dongu: farklı hedefli eylem sayacı sıfırlar", k_.sayac("click", "w1", H1) == 0)
try:
    k_.kontrol("click", "w1", H1, "A")
    ok = True
except dongu.DonguReddi:
    ok = False
kontrol("dongu: farklı eylemden sonra özdeş eylem yeniden serbest", ok)
k_ = dongu.DonguKesici()
seri(k_, 5)
kontrol("dongu: farklı araç / farklı pencere ayrı sayılır",
        k_.sayac("scroll", "w1", H1) == 0 and k_.sayac("click", "w2", H1) == 0 and k_.sayac("click", "w1", H1) == 5)

k_ = dongu.DonguKesici()
seri(k_, 2)
k_.kaydet("click", "w1", H1, "A", True)
seri(k_, 2)
kontrol("dongu: arada ekranı değiştiren (changed) tekrar seriyi böler (2+2 ≠ 4)", k_.sayac("click", "w1", H1) == 2)

k_ = dongu.DonguKesici()
sonuc = [k_.kaydet("press_key", "w1", ("keys", "down", 1, 0), "A", True) for _ in range(30)]
red = False
try:
    k_.kontrol("press_key", "w1", ("keys", "down", 1, 0), "A")
except dongu.DonguReddi:
    red = True
kontrol("dongu: ekranı değiştiren meşru tekrar (aşağı ok ×30) uyarı/ret üretmez", set(sonuc) == {0} and not red)

k_ = dongu.DonguKesici()
k_.kaydet("click", "w1", H1, "A", False)
k_.kaydet("click", "w1", H1, "A", False)
n_olcumsuz = k_.kaydet("click", "w1", H1, None, None)
kontrol("dongu: ölçümsüz (verify=False) kayıt sayacı artırmaz", n_olcumsuz == 0 and k_.sayac("click", "w1", H1) == 2)
for _i in range(10):
    k_.kaydet("click", "w1", H1, None, None)
kontrol("dongu: ölçümsüz kayıtlar seriyi bozmaz ve sayacı şişirmez", k_.sayac("click", "w1", H1) == 2)
n3 = k_.kaydet("click", "w1", H1, "A", False)
kontrol("dongu: ölçümsüz kayıtların ardından ölçülen sonuçsuz sayılmaya devam eder (3)", n3 == 3)

# ekran değişince kısıt kalkar
k_ = dongu.DonguKesici(ayni_ekran=lambda a, b: a == b)
seri(k_, 5, once="A")
cagri = []
try:
    k_.kontrol("click", "w1", H1, lambda: cagri.append(1) or "A")
    r1 = None
except dongu.DonguReddi as e:
    r1 = e.sayi
kontrol("dongu: ekran aynıyken reddedilir (ekran görüntüsü gerektiğinde ÖLÇÜLÜR)", r1 == 5 and cagri == [1])
try:
    k_.kontrol("click", "w1", H1, "B")
    r2 = None
except dongu.DonguReddi as e:
    r2 = e.sayi
kontrol("dongu: ekran değişince (A→B) kısıt kalkar, sayaç sıfırlanır", r2 is None and k_.sayac("click", "w1", H1) == 0)
k_ = dongu.DonguKesici()
seri(k_, 3)
cagri = []
k_.kontrol("click", "w1", H1, lambda: cagri.append(1) or "A")
kontrol("dongu: 5'ten az sonuçsuzda ekran HİÇ ölçülmez (ucuz)", cagri == [])
k_ = dongu.DonguKesici()
seri(k_, 5)
try:
    k_.kontrol("click", "w1", H1, None)
    r3 = None
except dongu.DonguReddi as e:
    r3 = e.sayi
kontrol("dongu: ekran ölçülemiyorsa (None) güvenli taraf: reddedilir", r3 == 5)

kontrol("dongu: Nokta toleransı (≤6 px aynı hedef)", dongu.Nokta(100, 100) == dongu.Nokta(104, 98) and
        dongu.Nokta(100, 100) != dongu.Nokta(110, 100) and ("xy", dongu.Nokta(0, 0)) == ("xy", dongu.Nokta(3, 3)))
kontrol("dongu: metin_norm büyük/küçük harf + boşluk + Türkçe İ/I",
        dongu.metin_norm("  KAYDET  İşlem ") == dongu.metin_norm("kaydet işlem") and
        dongu.metin_norm("ISIT") == dongu.metin_norm("ısıt"))
k_ = dongu.DonguKesici()
for _i in range(5):
    k_.kaydet("click", "w1", ("xy", dongu.Nokta(100 + _i, 100)), "A", False)
kontrol("dongu: 1 px kayık koordinat tekrarları aynı eylem sayılır", k_.sayac("click", "w1", ("xy", dongu.Nokta(100, 100))) == 5)

# ================================================================ A) birim: fark


def duz(w=400, h=300, v=200):
    return Image.new("RGB", (w, h), (v, v, v))


def cizim(im, kutu, v=0):
    c = im.copy()
    ImageDraw.Draw(c).rectangle([kutu[0], kutu[1], kutu[0] + kutu[2] - 1, kutu[1] + kutu[3] - 1], fill=(v, v, v))
    return c


a0 = duz()
O = fark.once_al
kontrol("fark: aynı görüntü → None", fark.fark(O(a0), O(a0.copy())) is None)
d = fark.fark(O(a0), O(cizim(a0, (100, 50, 40, 20))))
kontrol("fark: küçük kutu doğru bulundu", d and abs(d["region"][0] - 100) <= 2 and abs(d["region"][1] - 50) <= 2 and
        abs(d["region"][2] - 40) <= 4 and abs(d["region"][3] - 20) <= 4, str(d))
kontrol("fark: oran = kutu alanı / görüntü alanı", d and abs(d["ratio"] - 800 / 120000) < 0.004, str(d))
kontrol("fark: eşik altı (10 gri düzey) fark değişiklik sayılmaz", fark.fark(O(a0), O(cizim(a0, (10, 10, 100, 100), 190))) is None)
kontrol("fark: ince dikey çizgi (yanıp sönen imleç, 2×16 px) değişiklik DEĞİL",
        fark.fark(O(a0), O(cizim(a0, (200, 100, 2, 16)))) is None)
kontrol("fark: 1 px genişlikte imleç değişiklik DEĞİL", fark.fark(O(a0), O(cizim(a0, (200, 100, 1, 18)))) is None)
kontrol("fark: ince YATAY çizgi (alt çizgi/ilerleme çubuğu) değişiklik",
        fark.fark(O(a0), O(cizim(a0, (50, 100, 120, 2)))) is not None)
imlecli = cizim(a0, (200, 100, 2, 16))
d = fark.fark(O(imlecli), O(cizim(imlecli, (20, 20, 60, 30))))
kontrol("fark: imleç + gerçek değişiklik → gerçek değişiklik bulunur (imleç dışarıda kalmaz ama bulunur)", d is not None and
        d["region"][0] <= 22 and d["region"][1] <= 22, str(d))
d = fark.fark(O(a0), O(cizim(cizim(a0, (10, 10, 20, 20)), (350, 250, 30, 30))))
kontrol("fark: iki uzak değişiklik → sınır kutusu ikisini de kapsar", d and d["region"][0] <= 12 and d["region"][1] <= 12 and
        d["region"][0] + d["region"][2] >= 378 and d["region"][1] + d["region"][3] >= 278, str(d))
d = fark.fark(O(a0), O(cizim(a0, (0, 0, 400, 150))))
kontrol("fark: yarım pencere → oran ≈ 0,5", d and abs(d["ratio"] - 0.5) < 0.02, str(d))
d = fark.fark(O(a0), O(duz(500, 300)))
kontrol("fark: boyut değişti → tüm alan, oran 1", d and d["ratio"] == 1.0 and d["region"] == [0, 0, 500, 300], str(d))
kontrol("fark: ayni_ekran()", fark.ayni_ekran(O(a0), O(a0.copy())) and not fark.ayni_ekran(O(a0), O(cizim(a0, (5, 5, 50, 50))))
        and not fark.ayni_ekran(None, O(a0)))
kontrol("fark: sağda taşan kutu pencereye kırpılır",
        all(v >= 0 for v in fark.fark(O(a0), O(cizim(a0, (390, 290, 10, 10))))["region"]) and
        (lambda r: r[0] + r[2] <= 400 and r[1] + r[3] <= 300)(fark.fark(O(a0), O(cizim(a0, (390, 290, 10, 10))))["region"]))
kontrol("fark: new_text yalnız küçük+ucuz bölgede (en çok %25, 70k piksel, en az 16x10)",
        fark.yeni_metin_uygun({"region": [0, 0, 190, 50], "ratio": 0.02}) and
        not fark.yeni_metin_uygun({"region": [0, 0, 640, 400], "ratio": 0.25}) and
        not fark.yeni_metin_uygun({"region": [0, 0, 300, 100], "ratio": 0.4}) and
        not fark.yeni_metin_uygun({"region": [0, 0, 8, 12], "ratio": 0.001}) and
        not fark.yeni_metin_uygun({"region": [0, 0, 300, 12], "ratio": 1.0}))
tam = Image.effect_noise((1920, 1080), 60).convert("RGB")
tam2 = cizim(tam, (800, 400, 200, 100), 255)
t = time.perf_counter()
for _i in range(5):
    o1, o2 = O(tam), O(tam2)
    fark.fark(o1, o2)
olcum["fark: once_al ×2 + fark (1920x1080)"] = f"{(time.perf_counter() - t) / 5 * 1000:.1f} ms"
kontrol("fark: tam ekran için ucuz (< 60 ms: 2 gri küçültme + fark)", (time.perf_counter() - t) / 5 < 0.06,
        olcum["fark: once_al ×2 + fark (1920x1080)"])

# ================================================================ A) birim: mod_coz, CLI, şema

kontrol("mod_coz: 'ctrl+shift' → dotool adları", eylem.mod_coz("ctrl+shift") == ["leftctrl", "leftshift"])
kontrol("mod_coz: liste + yinelenen + meta/alt", eylem.mod_coz(["alt", "meta", "alt"]) == ["leftalt", "leftmeta"])
kontrol("mod_coz: boş/None → []", eylem.mod_coz(None) == [] and eylem.mod_coz("") == [] and eylem.mod_coz([]) == [])
kontrol("mod_coz: bilinmeyen tuş → Dur 1", dur_kodu(eylem.mod_coz, "ctrl+x") == 1 and dur_kodu(eylem.mod_coz, ["f5"]) == 1)

p = cli.ayristirici(sessiz=True)
a = p.parse_args(["click", "W", "10", "20", "triple", "--mod", "ctrl+shift"])
kontrol("cli: click ... triple --mod ctrl+shift", a.dugme == "uclu" and a.mod == "ctrl+shift" and a.komut == "tikla", str(a))
a = p.parse_args(["tikla", "W", "10", "20", "uclu", "--degistirici", "alt"])
kontrol("cli: Türkçe tikla ... uclu --degistirici alt", a.dugme == "uclu" and a.mod == "alt", str(a))
a = p.parse_args(["click", "W", "10", "20"])
kontrol("cli: varsayılan düğme sol, mod yok", a.dugme == "sol" and a.mod is None)
a = p.parse_args(["click-text", "W", "Kaydet", "triple", "--mod", "ctrl"])
b = p.parse_args(["click-element", "W", "Tamam", "double", "--mod", "shift"])
c = p.parse_args(["click-icon", "W", "simge", "--mod", "meta"])
kontrol("cli: click-text / click-element / click-icon da --mod ve triple alır",
        a.dugme == "uclu" and a.mod == "ctrl" and b.dugme == "cift" and b.mod == "shift" and c.mod == "meta")
kontrol("api: DUGME triple → uclu", api.DUGME["triple"] == "uclu")


async def semalar():
    from mcp import Client
    from deskhand import mcp_sunucu as s
    async with Client(s.mcp) as c:
        araclar = {t.name: t for t in (await c.list_tools()).tools}
    return s, araclar


s_mod, araclar = asyncio.run(semalar())
cs = araclar["click"].input_schema["properties"]
kontrol("şema: click.button 'triple' içerir", "triple" in json.dumps(cs["button"]), json.dumps(cs["button"]))
kontrol("şema: click.modifiers = ctrl|shift|alt|meta listesi", all(m in json.dumps(cs["modifiers"]) for m in
        ("ctrl", "shift", "alt", "meta")), json.dumps(cs["modifiers"]))
alanlar = list(cs)
kontrol("şema: modifiers imzada button'ın HEMEN ardında", alanlar.index("modifiers") == alanlar.index("button") + 1,
        str(alanlar))
dr = araclar.get("drag")
kontrol("şema: drag aracı var; window/from/to/shot_id zorunlu", dr is not None and
        set(dr.input_schema.get("required", [])) >= {"window", "from_x", "from_y", "to_x", "to_y", "shot_id"} and
        {"hold_s", "button", "desktop"} <= set(dr.input_schema["properties"]), str(dr and dr.input_schema))
adlar = list(araclar)
kontrol("şema: drag, scroll'dan hemen sonra", adlar.index("drag") == adlar.index("scroll") + 1, str(adlar))
kontrol("yönerge: changed_region, warning, drag, modifiers, triple anlatılıyor",
        all(x in s_mod.TALIMAT for x in ("changed_region", "changed_ratio", "new_text", "warning", "drag", "modifiers",
                                         "triple")))

# ================================================================ B) görünmez masaüstü

d_ = masaustu.masaustu_baslat()
au = sec(arka_bayragi=True)
p1 = au.baslat([sys.executable, PENCERE], env={"LOG": LOG, "BASLIK": "dogrulama-test"})


def bekle(kosul, sure=5.0, aralik=0.05):
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        v = kosul()
        if v:
            return v
        time.sleep(aralik)
    return kosul()


def log_satirlari():
    try:
        with open(LOG) as f:
            return [l.rstrip("\n") for l in f]
    except OSError:
        return []


def log_bekle(desen, sure=4.0, bas=0):
    rx = re.compile(desen)
    return bekle(lambda: next((l for l in log_satirlari()[bas:] if rx.search(l)), None), sure)


kid = bekle(lambda: next((w for w, b, _g in au.pencereler("dogrulama-test")), None), 25)
kontrol("pencere: sanal masaüstünde açıldı", kid is not None)
if kid is None:
    masaustu.masaustu_durdur()
    sys.exit(1)
bekle(lambda: au.aktif() == kid, 3)
time.sleep(0.5)
geo = au.geometri(kid)
kontrol("pencere: 760x640", geo[2:] == (760, 640), str(geo))


def yapi(r):
    return r.structured_content or {}


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


async def senaryo():
    from mcp import Client
    from deskhand import mcp_sunucu as s
    s._DONGU.temizle()
    PEN = "dogrulama-test"

    async def arac(c, ad, **kw):
        kw.setdefault("desktop", "background")
        return await c.call_tool(ad, kw)

    async with Client(s.mcp) as c:
        r = await arac(c, "screenshot", window=PEN)
        sid = yapi(r)["shot_id"]
        im = Image.open(io.BytesIO(base64.b64decode(r.content[0].data)))
        kontrol("ekran görüntüsü 760x640, ölçek 1", im.size == (760, 640) and yapi(r)["scale"] == 1.0)

        # ---- fark özeti: küçük bölge değişimi
        n0 = len(log_satirlari())
        t = time.perf_counter()
        r = await arac(c, "click", x=120, y=125, shot_id=sid)
        olcum["click(x,y) toplam (0,35 sn bekleme + fark + OCR dahil)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms"
        y = yapi(r)
        sonra = y.get("after") or {}
        kontrol("fark: click sonrası changed=true + changed_region + changed_ratio",
                not r.is_error and sonra.get("changed") is True and len(sonra.get("changed_region", [])) == 4 and
                0 < sonra.get("changed_ratio", 0) <= 1, metin(r)[:400])
        reg = sonra.get("changed_region") or [0, 0, 0, 0]
        kontrol("fark: bölge değişen sayaç etiketi satırını (x 100-250, y 40-70) kapsar ve pencere içinde",
                reg[0] <= 110 and reg[1] <= 45 and reg[0] + reg[2] >= 220 and reg[1] + reg[3] >= 65 and
                reg[0] >= 0 and reg[1] >= 0 and reg[0] + reg[2] <= 760 and reg[1] + reg[3] <= 640, str(reg))
        kontrol("fark: küçük bölge (≤ %25) → oran küçük", sonra.get("changed_ratio", 1) <= 0.25, str(sonra))
        yeni = sonra.get("new_text")
        kontrol("fark: küçük bölgede new_text (≤ 8 satır) 'degisti' okundu",
                isinstance(yeni, list) and 0 < len(yeni) <= 8 and any("degisti" in x or "isti" in x for x in yeni), str(yeni))
        kontrol("fark: tıklama gerçekten sayacı artırdı (günlük)", log_bekle(r"^arttir 1$", 2, n0) is not None)
        kontrol("fark: ilk tıklamada uyarı yok", "warning" not in y)

        # ---- döngü kesici: ölü alanda aynı tıklama
        sonuclar, ardisik, uyari_ilk, ret_no = [], 0, None, None
        ozet = []
        for i in range(1, 9):
            r = await arac(c, "click", x=190, y=450, shot_id=sid)
            if r.is_error:
                ret_no = (i, ardisik, metin(r))
                break
            y = yapi(r)
            ch = (y.get("after") or {}).get("changed")
            ardisik = ardisik + 1 if ch is False else 0
            ozet.append((ch, "warning" in y))
            if "warning" in y and uyari_ilk is None:
                uyari_ilk = (i, ardisik, y["warning"])
            kontrol(f"dongu: ölü alan tıklaması {i} → uyarı yalnız ≥3. ardışık sonuçsuzda",
                    ("warning" in y) == (ardisik >= 3), f"changed={ch} ardisik={ardisik}")
        kontrol("dongu: uyarı tam 3. ardışık sonuçsuzda başladı (Türkçe, 'tekrarlama')",
                uyari_ilk is not None and uyari_ilk[1] == 3 and "tekrarlama" in uyari_ilk[2], str(uyari_ilk))
        kontrol("dongu: 5 sonuçsuzdan sonra 6. özdeş çağrı ToolError [7] ile reddedildi (yürütülmeden)",
                ret_no is not None and ret_no[1] == 5 and "[7]" in ret_no[2], str(ret_no))
        n_olu = len([l for l in log_satirlari() if l.startswith("olu_tik")])
        kontrol("dongu: reddedilen çağrı ekrana HİÇ girdi göndermedi (olu_tik sayısı = yürütülen)",
                ret_no is not None and n_olu == ret_no[0] - 1, f"olu_tik={n_olu} ret_no={ret_no and ret_no[0]}")
        r = await arac(c, "click", x=190, y=450, shot_id=sid)
        kontrol("dongu: ısrarla aynı çağrı yine reddedilir", r.is_error and "[7]" in metin(r))

        # ---- ekran DIŞARIDAN değişince (Deskhand dışı eylem) kısıt kalkar
        with api.hedef("sanal"):
            api.tikla(kid, 120, 125, "left", None)  # MCP halkasında yok: ekranı değiştirir (sayaç 2)
        time.sleep(0.4)
        r = await arac(c, "click", x=190, y=450, shot_id=sid)
        kontrol("dongu: ekran değişince (başka eylemle) özdeş çağrı yeniden serbest", not r.is_error and
                "warning" not in yapi(r), metin(r)[:300])

        # ---- farklı eylem sayacı sıfırlar
        r = await arac(c, "click", x=120, y=125, shot_id=sid)  # Arttir (farklı hedef)
        r1 = await arac(c, "click", x=190, y=450, shot_id=sid)
        r2 = await arac(c, "click", x=190, y=450, shot_id=sid)
        kontrol("dongu: farklı eylemden sonra seri baştan (ilk iki sonuçsuzda uyarı yok)",
                not r1.is_error and not r2.is_error and "warning" not in yapi(r1) and "warning" not in yapi(r2))
        # ---- verify=False: ölçüm yok → sayaç artmaz, reddedilmez
        await arac(c, "click", x=120, y=125, shot_id=sid)
        sonuclar = []
        for i in range(8):
            r = await arac(c, "click", x=190, y=450, shot_id=sid, verify=False)
            sonuclar.append((r.is_error, "warning" in yapi(r), "after" in yapi(r)))
        kontrol("dongu: verify=False tıklamalar (×8) asla uyarı/ret üretmez, 'after' yok",
                all(not e and not w and not a_ for e, w, a_ in sonuclar), str(sonuclar))

        # ---- üçlü tık: metin kutusunda tüm satır seçilir
        n0 = len(log_satirlari())
        r = await arac(c, "click", x=190, y=200, shot_id=sid, button="triple")
        kontrol("üçlü tık: click(button=triple) hata vermedi", not r.is_error, metin(r)[:300])
        log_bekle(r"^secim=alfa beta gama delta", 3, n0)
        sec_satirlari = [l for l in log_satirlari()[n0:] if l.startswith("secim=")]
        kontrol("üçlü tık: önce kelime (çift tık), sonra TÜM satır seçildi",
                len(sec_satirlari) >= 2 and sec_satirlari[-1].startswith("secim=alfa beta gama delta") and
                len(sec_satirlari[0]) < len(sec_satirlari[-1]), str(sec_satirlari))
        n0 = len(log_satirlari())
        r = await arac(c, "click", x=190, y=200, shot_id=sid, button="double")
        kontrol("üçlü tık karşılaştırması: çift tık yalnız kelime seçer",
                log_bekle(r"^secim=", 3, n0) is not None and
                not any(l.startswith("secim=alfa beta gama delta") for l in log_satirlari()[n0:]),
                str(log_satirlari()[n0:]))

        # ---- meşru tekrar: metin kutusuna 10 kez 'x' → her biri ekranı değiştirir
        r = await arac(c, "click", x=200, y=200, shot_id=sid)
        uyarilar, degisen = 0, 0
        for i in range(10):
            r = await arac(c, "press_key", window=PEN, keys="x")
            y = yapi(r)
            uyarilar += "warning" in y or r.is_error
            degisen += (y.get("after") or {}).get("changed") is True
        kontrol("dongu: meşru tekrar (aynı tuş ×10, her biri ekranı değiştirir) tetiklemez",
                uyarilar == 0 and degisen >= 9, f"uyari={uyarilar} degisen={degisen}")
        kontrol("fark: tek harflik değişiklik algılandı (press_key after.changed + region)",
                degisen >= 9 and (yapi(r).get("after") or {}).get("changed_region"), metin(r)[:300])

        # ---- scroll: kaydırılacak şey yok → sonuçsuz; uyarı + ret
        sc = []
        for i in range(7):
            r = await arac(c, "scroll", window=PEN, direction="down", amount=1)
            sc.append((r.is_error, "warning" in yapi(r), yapi(r).get("changed")))
        kontrol("dongu: scroll sonuçsuz tekrar → 3. kez uyarı, 6. çağrı reddedildi",
                sc[2][1] and not sc[1][1] and sc[3][1] and not sc[4][0] and sc[5][0], str(sc))

        # ---- değiştirici tuşlar
        def mod_tikleri(bas):
            return [l for l in log_satirlari()[bas:] if l.startswith("mod_tik")]
        n0 = len(log_satirlari())
        r = await arac(c, "click", x=190, y=310, shot_id=sid, modifiers=["ctrl"])
        log_bekle(r"^mod_tik", 3, n0)
        l = mod_tikleri(n0)
        kontrol("değiştirici: ctrl+tık → uygulama ctrl=1 shift=0 gördü", len(l) == 1 and "ctrl=1 shift=0 alt=0 meta=0" in l[0],
                str(l))
        n0 = len(log_satirlari())
        r = await arac(c, "click", x=190, y=310, shot_id=sid, modifiers=["ctrl", "shift"], button="right")
        log_bekle(r"^mod_tik", 3, n0)
        l = mod_tikleri(n0)
        kontrol("değiştirici: ctrl+shift+sağ tık → ctrl=1 shift=1", len(l) == 1 and "sag ctrl=1 shift=1" in l[0], str(l))
        n0 = len(log_satirlari())
        r = await arac(c, "click", x=190, y=310, shot_id=sid)
        log_bekle(r"^mod_tik", 3, n0)
        l = mod_tikleri(n0)
        kontrol("değiştirici: sonraki sade tık → ctrl=0 shift=0 (tuşlar bırakıldı)",
                len(l) == 1 and "ctrl=0 shift=0 alt=0 meta=0" in l[0], str(l))
        n0 = len(log_satirlari())
        r = await arac(c, "click", x=190, y=310, shot_id=sid, modifiers=["shift"], button="triple")
        time.sleep(0.5)
        l = mod_tikleri(n0)
        kontrol("değiştirici + üçlü: shift basılıyken 3 tık", len(l) == 3 and all("shift=1" in x for x in l), str(l))
        r = await arac(c, "click", x=190, y=310, shot_id=sid, modifiers=["ctrl"], text="BOS ALAN")
        kontrol("click: iki hedef (text + x,y) hâlâ reddedilir", r.is_error)

        # ---- sürükleme
        n0 = len(log_satirlari())
        t = time.perf_counter()
        r = await arac(c, "drag", window=PEN, from_x=460, from_y=100, to_x=620, to_y=250, shot_id=sid, hold_s=0.4)
        olcum["drag toplam (0,4 sn hareket + 0,35 sn bekleme)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms"
        y = yapi(r)
        kontrol("sürükleme: drag hata vermedi, status=dragged", not r.is_error and y.get("status") == "dragged", metin(r)[:400])
        log_bekle(r"^surukle_birak ", 3, n0)
        satirlar = log_satirlari()[n0:]
        bas = next((l.split() for l in satirlar if l.startswith("surukle_bas")), None)
        birak = next((l.split() for l in satirlar if l.startswith("surukle_birak")), None)
        hareket = [l for l in satirlar if l.startswith("surukle_hareket")]
        # sürükleme alanı pencere içinde (400,40) başlar
        kontrol("sürükleme: basma noktası doğru (±2 px)", bas and bas[1] == "sol" and abs(float(bas[2]) - (460 - 400)) <= 2 and
                abs(float(bas[3]) - (100 - 40)) <= 2, str(bas))
        kontrol("sürükleme: bırakma noktası doğru (±3 px)", birak and abs(float(birak[2]) - (620 - 400)) <= 3 and
                abs(float(birak[3]) - (250 - 40)) <= 3, str(birak))
        kontrol("sürükleme: ara hareketler var (düz çekiş değil gerçek sürükleme)", len(hareket) >= 5, str(len(hareket)))
        sonra = y.get("after") or {}
        reg = sonra.get("changed_region") or [0, 0, 0, 0]
        kontrol("sürükleme: after.changed + changed_region çizilen çerçeveyi kapsar",
                sonra.get("changed") is True and reg[0] <= 465 and reg[1] <= 105 and reg[0] + reg[2] >= 615 and
                reg[1] + reg[3] >= 245, str(sonra))
        r = await arac(c, "drag", window=PEN, from_x=460, from_y=100, to_x=2000, to_y=250, shot_id=sid)
        kontrol("sürükleme: görüntü dışı hedef → [2], girdi yok", r.is_error and "[2]" in metin(r))
        r = await arac(c, "drag", window=PEN, from_x=460, from_y=100, to_x=500, to_y=250, shot_id="yok")
        kontrol("sürükleme: bilinmeyen shot_id → [8]", r.is_error and "[8]" in metin(r), metin(r)[:200])
        n0 = len(log_satirlari())
        r = await arac(c, "drag", window=PEN, from_x=460, from_y=100, to_x=500, to_y=250, shot_id=sid, button="right")
        time.sleep(0.3)
        kontrol("sürükleme: sağ düğmeyle sürükleme", any(l.startswith("surukle_bas sag") for l in log_satirlari()[n0:]),
                metin(r)[:200])

        # ---- DUR: sürükleme/tıklama yok
        guvenlik.dur_ac("cli")
        n0 = len(log_satirlari())
        r = await arac(c, "drag", window=PEN, from_x=460, from_y=100, to_x=500, to_y=250, shot_id=sid)
        r2 = await arac(c, "click", x=190, y=310, shot_id=sid, modifiers=["ctrl"])
        guvenlik.dur_kapat("cli")
        time.sleep(0.2)
        kontrol("güvenlik: DUR → drag ve değiştiricili click [13], ekrana girdi yok",
                r.is_error and "[13]" in metin(r) and r2.is_error and "[13]" in metin(r2) and len(log_satirlari()) == n0,
                metin(r)[:100] + metin(r2)[:100])
        r = await arac(c, "click", x=190, y=310, shot_id=sid, modifiers=["ctrl"], desktop="background", window="yok-boyle-pencere")
        kontrol("güvenlik: yanlış pencere + değiştirici → hata, girdi yok", r.is_error)

    return sid


sid = asyncio.run(senaryo())

# ---- değiştirici bırakma güvenceleri (gerçek sanal girdi + araya giren hata/DUR)


class KesikGirdi:
    """Gerçek sanal Girdi'yi sarar: belirtilen satırda Dur fırlatır (hata/DUR/kesinti taklidi)."""

    def __init__(self, g, ne):
        self.g, self.ne = g, ne

    def gonder(self, k, desen, *satirlar):
        if any(s.startswith(self.ne) for s in satirlar):
            raise Dur(13, "test kesintisi")
        return self.g.gonder(k, desen, *satirlar)

    def __getattr__(self, a):
        return getattr(self.g, a)


def basili_mod(g):
    from Xlib import X
    q = g.x.kok.query_pointer()
    return bool(q.mask & (X.ControlMask | X.ShiftMask | X.Mod1Mask | X.Mod4Mask))


for ne, ad in (("click", "tıklama satırında"), ("keydown leftshift", "ikinci keydown'da"), ("mouseto", "hiç basmadan")):
    g = au.girdi("test", False, None, guvenlik.denetle)
    try:
        with api.hedef("sanal"):
            kod = dur_kodu(eylem.tikla_ic, KesikGirdi(g, ne), kid, None, 190, 310, "uclu", None, 0.0, 1,
                           ["leftctrl", "leftshift", "leftalt"])
        time.sleep(0.1)
        kontrol(f"bırakma: {ad} kesilince (Dur 13) basılı değiştirici KALMADI", kod == 13 and not g._basili_tus and
                not basili_mod(g), f"kod={kod} basili={getattr(g, '_basili_tus', None)}")
    finally:
        g.kapat()

g = au.girdi("test", False, None, guvenlik.denetle)
satirlar = []
asil_gonder, asil_zorla = g.gonder, g.zorla


class Kayit:
    def __init__(self, g):
        self.g = g

    def gonder(self, k, desen, *s):
        satirlar.append(("g", s))
        return self.g.gonder(k, desen, *s)

    def zorla(self, s):
        satirlar.append(("z", s))
        return self.g.zorla(s)

    def __getattr__(self, a):
        return getattr(self.g, a)


with api.hedef("sanal"):
    eylem.tikla_ic(Kayit(g), kid, None, 190, 450, "cift", None, 0.0, 1, ["leftctrl", "leftalt"])
g.kapat()
kontrol("sıra: mouseto → keydown ctrl → keydown alt → click×2 → keyup alt → keyup ctrl",
        [(x, s) for x, s in satirlar][1:] == [("g", ("keydown leftctrl",)), ("g", ("keydown leftalt",)),
                                              ("g", ("click left", "click left")), ("z", "keyup leftalt"),
                                              ("z", "keyup leftctrl")], str(satirlar))
g = au.girdi("test", False, None, guvenlik.denetle)
satirlar.clear()
with api.hedef("sanal"):
    eylem.tikla_ic(Kayit(g), kid, None, 190, 450, "uclu")
g.kapat()
kontrol("sıra: uclu → tek gonder çağrısında 3 'click left' (bölünemez)",
        ("g", ("click left", "click left", "click left")) in satirlar, str(satirlar))

# ---- CLI uçtan uca (sanal masaüstü: --arka)
n0 = len(log_satirlari())
r = subprocess.run([sys.executable, "-m", "deskhand", "--arka", "tikla", kid, "190", "310", "uclu", "--mod", "ctrl+shift"],
                   capture_output=True, text=True, timeout=60, cwd=KOK)
time.sleep(0.5)
l = [x for x in log_satirlari()[n0:] if x.startswith("mod_tik")]
kontrol("cli: tikla ... uclu --mod ctrl+shift → 3 tık, ctrl=1 shift=1", r.returncode == 0 and len(l) == 3 and
        all("ctrl=1 shift=1" in x for x in l), f"rc={r.returncode} {r.stdout[-200:]} {r.stderr[-200:]} {l}")
r = subprocess.run([sys.executable, "-m", "deskhand", "--arka", "tikla", kid, "190", "310", "--mod", "f5"],
                   capture_output=True, text=True, timeout=60, cwd=KOK)
kontrol("cli: bilinmeyen değiştirici → çıkış 1, hiçbir tık gitmedi", r.returncode == 1 and
        len([x for x in log_satirlari()[n0:] if x.startswith("mod_tik")]) == 3, f"rc={r.returncode} {r.stderr[-200:]}")
n0 = len(log_satirlari())
r = subprocess.run([sys.executable, "-m", "deskhand", "--arka", "drag", kid, "470", "100", "600", "200"],
                   capture_output=True, text=True, timeout=60, cwd=KOK)
time.sleep(0.3)
kontrol("cli: drag (var olan komut) hâlâ çalışıyor", r.returncode == 0 and log_bekle(r"^surukle_birak", 2, n0) is not None,
        f"rc={r.returncode} {r.stderr[-200:]}")

# ---- temizlik
try:
    p1.terminate()
except Exception:  # noqa: BLE001
    pass
masaustu.masaustu_durdur()

print()
for ad, v in olcum.items():
    print(f"ÖLÇÜM  {ad}: {v}")
print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
