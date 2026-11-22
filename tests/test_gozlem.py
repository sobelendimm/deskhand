"""MCP gözlem yüzeyi (Faz 10) testleri: observe, ref ile eylem, wait_for, sonuç sözleşmesi, araç açıklamaları.
Kullanıcının GERÇEK ekranına hiçbir girdi gitmez; gerçek ~/.config yazılmaz (_yalitim).

 A) Saf birim: gozlem.py (temizleme, satır/yapı biçimi, sorgu + atalar, OCR ayıklama, önbellek sınırları/ömür, fark,
    Set-of-Marks çizimi), erisim.ref_oge_sec (kimlik + ad/rol/kutu ±3 px).
 B) Araç listesi: 18 araç, observe/wait_for salt-okunur, outputSchema (observe/batch/wait_for/click), açıklamalarda
    komut enjeksiyonu kalıbı ve "sandbox/isolated/secure" iddiası yok; tools/list boyutu ölçülür.
 C) GÖRÜNMEZ masaüstünde (Xvfb) gerçek Qt pencereleri: observe (ağaç, sorgu, since, OCR, numaralı görüntü),
    ref ile tık/eylem/yazı/kaydırma, durum değişimi = confirmed, bayat ref (pencere boyutu), wait_for (text, element,
    window, stable, gone, zaman aşımı); token/karakter ölçümü (tam ağaç / interactive_only / query).
 C2) GÖRÜNMEZ masaüstünde YALITIK Firefox (geçici profil; kullanıcı profil kökü önce/sonra sha1): web ögesi ref'i (yazısız
    düğme, via=action), ödeme sayfasında ref tıklaması onay ister, 1.000 bağlantılı sayfada sayfalama/sorgu/süre.
 D) Süreç içi sahte kde arka ucu + sahte AT-SPI (tests/yardimci/sahte_masaustu.py): ref yolunda her güvenlik kapısı
    (DUR, hassas öge, hassas sayfa, onay sonrası öge değişimi, bekleyen onay, kendi istemci, seviye, sistem istemi,
    parola alanı, uçbirim Enter kapısı, insan önceliği), bayatlığın üç nedeni (snapshot / window / element) ve
    hiçbirinde girdi gönderilmediği; sent/next; OCR'a düşme ve OCR satırı ref'i.

Çalıştır:  python3 tests/test_gozlem.py"""
import asyncio
import copy
import atexit
import base64
import io
import json
import os
import re
import shutil
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))

from PIL import Image  # noqa: E402

from deskhand import erisim, gozlem, masaustu, mcp_sunucu as s  # noqa: E402
from deskhand.hata import Dur  # noqa: E402

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
gecen = toplam = 0
OLCUM: dict = {}


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


def yapi(r):
    """structuredContent; observe/batch'te yok (yalnız metin) → metin ayrıştırılır (tests/yardimci/mcp_metin.py)."""
    import mcp_metin
    return mcp_metin.yapi(r)


# ================================================================ A) saf birim

def birim_testleri():
    kontrol("temiz: U+FFFC ve fazla boşluk atılır; yalnız boşluk → ''",
            gozlem.temiz("a￼  b \n") == "a b" and gozlem.temiz(" ￼ \t") == "")
    o = {"rol": "push button", "ad": "Kaydet", "kutu": [1, 2, 3, 4], "durumlar": ["focused"], "kaynak": "tree",
         "deger": "x" * 100, "hassas": True, "eylemler": ["Press"]}
    sat = gozlem.satir(o, 7)
    kontrol("satir: [N] rol \"ad\" @kutu durum = değer !sensitive",
            sat.startswith('[7] push button "Kaydet" @1,2,3,4 focused = "') and sat.endswith("!sensitive") and "…" in sat,
            sat)
    import mcp_metin
    e = mcp_metin._oge("ab12-3", 7, sat.split(" ", 1)[1])
    kontrol("satir → ayrıştırma: rol/ad/kutu/durum/değer/hassas metinden geri okunur",
            e["role"] == "push button" and e["name"] == "Kaydet" and e["frame"] == [1, 2, 3, 4] and
            e["states"] == ["focused"] and e["value"].endswith("…") and e["sensitive"] is True, str(e))
    e = mcp_metin._oge("ab12-3", 8, gozlem.satir({"rol": "push button", "ad": "", "kutu": [5, 6, 7, 8],
                                                   "durumlar": ["disabled"], "kaynak": "tree"}, 8).split(" ", 1)[1])
    kontrol("satir: adsız ögede rol (boşluklu) ile durum @kutu ile ayrılır", e == {
        "ref": "ab12-3:8", "role": "push button", "frame": [5, 6, 7, 8], "states": ["disabled"]}, str(e))
    y = gozlem.yapisal({"rol": "label", "ad": "", "kutu": [0, 0, 5, 5], "durumlar": [], "kaynak": "tree"}, "ab12-3", 2)
    kontrol("yapisal: boş/varsayılan alanlar atılır (ad, durum, değer, eylem yok)",
            y == {"ref": "ab12-3:2", "role": "label", "frame": [0, 0, 5, 5]}, str(y))
    y = gozlem.yapisal({"rol": "ocr_text", "ad": "Merhaba", "kutu": [0, 0, 5, 5], "durumlar": [], "kaynak": "ocr"},
                       "ab12-3", 9)
    kontrol("yapisal: OCR satırı source=ocr", y.get("source") == "ocr" and y["name"] == "Merhaba")
    kontrol("ref_ayir: biçim", gozlem.ref_ayir("ab12-3:9") == ("ab12-3", 9) and gozlem.ref_ayir("x:1") is None
            and gozlem.ref_ayir("ab12-3:") is None)

    def g(rol, ad, yol, etk=True, kaynak="tree"):
        return {"rol": rol, "ad": ad, "kutu": [0, 0, 10, 10], "durumlar": [], "kaynak": kaynak, "yol": yol,
                "etkilesimli": etk, "kimlik": None}
    agac = [g("dialog", "Kaydet iletişim", [0], False), g("panel", "", [0, 0], False),
            g("push button", "Kaydet", [0, 0, 1]), g("push button", "İptal", [0, 0, 2]), g("label", "Başka", [1], False)]
    r = gozlem.sorgu_suz(agac, "kaydet|yok", True)
    kontrol("sorgu: eşleşen + ADI OLAN atası (adsız panel yok), interactive_only eşleşmede",
            [x["ad"] for x in r] == ["Kaydet iletişim", "Kaydet"], str([x["ad"] for x in r]))
    r = gozlem.sorgu_suz(agac, "İPTAL", True)
    kontrol("sorgu: büyük/küçük + Türkçe harf duyarsız (İPTAL → İptal)", [x["ad"] for x in r] == ["Kaydet iletişim", "İptal"])
    r = gozlem.sorgu_suz(agac, "başka", False)
    kontrol("sorgu: interactive_only=false etkileşimsiz eşleşmeyi de alır", [x["ad"] for x in r] == ["Başka"])
    kontrol("gorunur_suz: interactive_only / adsız kapsayıcı atılır",
            [x["ad"] for x in gozlem.gorunur_suz(agac, True)] == ["Kaydet", "İptal"] and
            [x["ad"] for x in gozlem.gorunur_suz(agac, False)] == ["Kaydet iletişim", "Kaydet", "İptal", "Başka"])
    ocr = [{"rol": "ocr_text", "ad": "Kaydet", "kutu": [2, 2, 5, 5], "kaynak": "ocr", "durumlar": []},
           {"rol": "ocr_text", "ad": "Serbest yazı", "kutu": [50, 50, 30, 10], "kaynak": "ocr", "durumlar": []}]
    kontrol("ocr_ayikla: ağaçtaki ögenin kutusunda aynı yazı atılır, ağaçta olmayan kalır",
            [x["ad"] for x in gozlem.ocr_ayikla([g("push button", "Kaydet", [0])], ocr)] == ["Serbest yazı"])

    depo = gozlem.Depo()
    sidler = []
    for i in range(6):
        sid = depo.yeni_kimlik()
        depo.ekle(gozlem.Anlik(sid, "{w}", "kde", (10, 10), "t", []))
        sidler.append(sid)
    kontrol("önbellek: pencere başına en çok 4 (eski ikisi bilinmiyor)",
            [depo.al(x)[1] for x in sidler] == ["unknown", "unknown", "", "", "", ""])
    for i in range(20):
        depo.ekle(gozlem.Anlik(depo.yeni_kimlik(), f"{{p{i}}}", "kde", (10, 10), "t", []))
    kontrol("önbellek: toplam en çok 16", len(depo._d) == 16)
    a = gozlem.Anlik(depo.yeni_kimlik(), "{w}", "kde", (10, 10), "t", [])
    depo.ekle(a)
    a.zaman -= gozlem.OMUR + 1
    kontrol("önbellek: 120 sn sonra 'expired'", depo.al(a.sid) == (None, "expired"))
    kontrol("snapshot_id: sunucu öneki + sayaç", re.fullmatch(r"[0-9a-f]{4}-\d+", a.sid) is not None, a.sid)

    def t(ad, kimlik, kutu=(0, 0, 10, 10), durum=()):
        return {"rol": "push button", "ad": ad, "kutu": list(kutu), "durumlar": list(durum), "kaynak": "tree",
                "kimlik": list(kimlik), "yol": []}
    eski = gozlem.Anlik("ab12-1", "{w}", "kde", (10, 10), "t", [t("A", (":1", "/1")), t("B", (":1", "/2")),
                                                                 t("C", (":1", "/3"))])
    yeni = [t("A", (":1", "/1"), (2, 2, 10, 10)), t("B2", (":1", "/2")), t("D", (":1", "/4"))]
    kontrol("fark: + eklenen, ~ değişen (ad), - kaybolan; kutu ±3 px oynama değişim sayılmaz",
            gozlem.fark(eski, yeni) == ([2], [1], [2]), str(gozlem.fark(eski, yeni)))
    yeni[0]["kutu"] = [5, 0, 10, 10]
    kontrol("fark: kutu > 3 px oynadı → değişen", gozlem.fark(eski, yeni)[1] == [0, 1])
    kontrol("durum_degisti: checked eklendi", gozlem.durum_degisti({"durumlar": ["focused"]},
                                                                   {"durumlar": ["focused", "checked"]})
            and not gozlem.durum_degisti({"durumlar": []}, {"durumlar": ["focused"]}))

    im = Image.new("RGB", (200, 100), (255, 255, 255))
    im2 = gozlem.isaretle(im, [(3, {"kutu": [10, 10, 50, 20]})], (0, 0), 1.0)
    kontrol("isaretle: kutu ve numara çizilir (görüntü değişti, özgün korunur)",
            im2.getpixel((10, 20)) != (255, 255, 255) and im.getpixel((10, 20)) == (255, 255, 255))

    # erisim.ref_oge_sec: kimlik + ad/rol/kutu
    ogeler = [{"rol": "push button", "ad": "Kaydet", "x": 10, "y": 10, "w": 50, "h": 20, "kimlik": [":1", "/1"],
               "yol": [0]},
              {"rol": "push button", "ad": "Kaydet", "x": 100, "y": 10, "w": 50, "h": 20, "kimlik": [":1", "/2"],
               "yol": [1]}]
    ref = {"kaynak": "tree", "kimlik": [":1", "/2"], "yol": [1], "ad": "Kaydet", "rol": "push button",
           "kutu": [102, 11, 50, 20]}
    kontrol("ref_oge_sec: AYNI ADLI iki düğmeden kimliği tutan seçilir (±3 px)", erisim.ref_oge_sec(ogeler, ref) is ogeler[1])

    def tur(r_):
        try:
            erisim.ref_oge_sec(ogeler, r_)
            return None
        except Dur as e:
            return (e.kod, e.tur)
    kontrol("ref_oge_sec: kimlik yok → Dur 8 ref-yok", tur({**ref, "kimlik": [":1", "/9"]}) == (8, "ref-yok"))
    kontrol("ref_oge_sec: ad farklı → Dur 8 ref-farkli", tur({**ref, "ad": "Sil"}) == (8, "ref-farkli"))
    kontrol("ref_oge_sec: rol farklı → ref-farkli", tur({**ref, "rol": "link"}) == (8, "ref-farkli"))
    kontrol("ref_oge_sec: kutu 4 px oynadı → ref-farkli", tur({**ref, "kutu": [96, 10, 50, 20]}) == (8, "ref-farkli"))
    kontrol("ref_oge_sec: kimliksiz ögede çocuk-sıra yolu", erisim.ref_oge_sec(
        [{**ogeler[0], "kimlik": None}], {**ref, "kimlik": None, "yol": [0], "kutu": [10, 10, 50, 20]})["x"] == 10)


# ================================================================ B) araç listesi ve açıklamalar

ENJEKSIYON = re.compile(r"ignore (all |the )?(previous|prior|above)|disregard|you must|system prompt|<\s*/?\s*(system|"
                        r"instructions?|important)|hidden instruction|do not (tell|inform) the user|override|jailbreak",
                        re.I)
IDDIA = re.compile(r"\b(sandbox(ed|ing)?|isolated|isolation|secure(ly)?|security)\b", re.I)


async def liste_testleri():
    from mcp import Client
    async with Client(s.mcp) as c:
        r = await c.list_tools()
        talimat = (c.initialize_result.instructions if getattr(c, "initialize_result", None) else None) or s.TALIMAT
    araclar = {t.name: t for t in r.tools}
    kontrol("liste: 18 araç (en çok 18)", len(araclar) == 18, str(sorted(araclar)))
    for ad in ("observe", "wait_for"):
        a = araclar[ad].annotations
        kontrol(f"liste: {ad} salt-okunur", a.read_only_hint is True)
    for ad in ("wait_for", "click"):
        sema = araclar[ad].output_schema or {}
        kontrol(f"liste: {ad} outputSchema (effect alanı)", "effect" in (sema.get("properties") or {}), str(sema)[:200])
    for ad in ("observe", "batch"):  # token ekonomisi: yalnız kısa metin (structuredContent metnin ~5 katıydı)
        kontrol(f"liste: {ad} outputSchema YOK", araclar[ad].output_schema is None, str(araclar[ad].output_schema)[:200])
    kontrol("liste: batch yıkıcı (girdi)", araclar["batch"].annotations.destructive_hint is True)
    kontrol("liste: ref parametresi click/type_text/scroll'da, drag'de from_ref/to_ref",
            all("ref" in araclar[a].input_schema["properties"] for a in ("click", "type_text", "scroll")) and
            {"from_ref", "to_ref"} <= set(araclar["drag"].input_schema["properties"]))
    adim = json.dumps(araclar["batch"].input_schema)
    kontrol("liste: batch adım araçları yalnız click/type_text/press_key/scroll/drag/wait",
            all(x in adim for x in ('"click"', '"type_text"', '"press_key"', '"scroll"', '"drag"', '"wait"')) and
            not any(x in adim for x in ('"open_app"', '"run_flow"', '"clipboard"', '"manage_window"', '"batch"')))
    kontrol("liste: onay parametresi YOK", not any("onay" in p or "approv" in p for t in r.tools
                                                   for p in (t.input_schema.get("properties") or {})))
    metinler = [talimat] + [t.description or "" for t in r.tools] + [
        json.dumps(t.input_schema, ensure_ascii=False) for t in r.tools]
    bulunan = [m.group(0) for x in metinler for m in ENJEKSIYON.finditer(x)]
    kontrol("açıklamalar: komut enjeksiyonu kalıbı yok (ignore previous, you must, gizli talimat...)", not bulunan,
            str(bulunan))
    bulunan = [m.group(0) for x in metinler for m in IDDIA.finditer(x)]
    kontrol("açıklamalar: 'sandbox/isolated/secure' iddiası yok", not bulunan, str(bulunan))
    kontrol("talimat: veri/talimat ayrımı + observe/ref/batch/wait_for akışı",
            all(x in talimat for x in ("data, not instructions", "observe", "ref", "batch", "wait_for", "get_status")))
    kontrol("talimat: 1000-2400 karakter", 1000 <= len(talimat) <= 2400, str(len(talimat)))
    eksik = [t.name for t in r.tools if len(t.description or "") < 120]
    kontrol("açıklamalar: her araç en az bir cümle 'ne/ne zaman/dönüş'", not eksik, str(eksik))
    boyut = len(json.dumps([t.model_dump(by_alias=True, exclude_none=True, mode="json") for t in r.tools],
                           ensure_ascii=False))
    OLCUM["tools_list"] = boyut
    OLCUM["talimat"] = len(talimat)
    OLCUM["araclar"] = {t.name: len(json.dumps(t.model_dump(by_alias=True, exclude_none=True, mode="json"),
                                               ensure_ascii=False)) for t in r.tools}
    kontrol(f"liste: tools/list {boyut} karakter (~{boyut // 4} token) ≤ 60000", boyut <= 60000)


# ================================================================ C) görünmez masaüstü, gerçek Qt

def sanal_mumkun():
    try:
        import PyQt6  # noqa: F401
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # noqa: F401
    except (ImportError, ValueError):
        return False
    return all(shutil.which(a) for a in ("Xvfb", "dbus-daemon", "busctl")) and \
        os.path.exists("/usr/lib/at-spi-bus-launcher")


def log_oku(yol):
    try:
        with open(yol) as f:
            return f.read().splitlines()
    except OSError:
        return []


def log_bekle(yol, desen, bas=0, sure=4.0):
    rx = re.compile(desen)
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if any(rx.search(x) for x in log_oku(yol)[bas:]):
            return True
        time.sleep(0.05)
    return False


async def sanal_testleri():
    from mcp import Client
    LOG = os.path.join(_yalitim.PAYLASIM, "a11y.log")  # bwrap ad alanında yalnız PAYLASIM görünür
    LOG2 = os.path.join(_yalitim.PAYLASIM, "pencere.log")
    masaustu.masaustu_baslat()
    masaustu.baslat([sys.executable, os.path.join(KOK, "tests/yardimci/a11y_pencere.py")],
                    {"LOG": LOG, "PENCERE_BASLIK": "gozlem-a11y"})
    for _ in range(100):
        if "hazir" in log_oku(LOG):
            break
        time.sleep(0.2)
    B = {"desktop": "background"}
    async with Client(s.mcp) as c:
        st = None
        for _ in range(40):  # uygulamanın ağaca girmesi
            r = await c.call_tool("observe", {"window": "gozlem-a11y", **B})
            st = yapi(r)
            if not r.is_error and any(e.get("name") == "Kaydet" for e in st.get("elements", [])):
                break
            await asyncio.sleep(0.25)
        txt = metin(r)
        kontrol("sanal observe: başlık satırı snapshot_id + kaynak tree, Qt ögeleri satır satır",
                re.match(r"snapshot [0-9a-f]{4}-\d+ \| window \S+ \"gozlem-a11y\" \d+x\d+ \| sources tree", txt) is not None
                and '] push button "Kaydet"' in txt.replace("] button", "] push button") or '] button "Kaydet"' in txt,
                txt[:400])
        ogeler = {e.get("name"): e for e in st.get("elements", [])}
        kontrol("sanal observe: metindeki alanlar (ref, role, @frame; disabled, sensitive); structuredContent YOK",
                ogeler.get("Kaydet", {}).get("ref", "").startswith(st.get("snapshot_id", "?") + ":") and
                len(ogeler.get("Kaydet", {}).get("frame", [])) == 4 and r.structured_content is None and
                "disabled" in ogeler.get("Pasif düğme", {}).get("states", []) and
                ogeler.get("Satın al", {}).get("sensitive") is True, json.dumps(st.get("elements", [])[:4])[:400])
        kontrol("sanal observe: parola alanının değeri yok; sayı kutusunun değeri var",
                "value" not in ogeler.get("Parola", {}) and ogeler.get("Adet", {}).get("value") == "0",
                str(ogeler.get("Parola")) + str(ogeler.get("Adet")))
        OLCUM["sanal_interactive"] = (len(txt), len(json.dumps(st, ensure_ascii=False)), st.get("total"))
        print("\n# observe örnek çıktısı (gerçek Qt penceresi, görünmez masaüstü):\n" + txt + "\n", flush=True)
        r = await c.call_tool("observe", {"window": "gozlem-a11y", "interactive_only": False, **B})
        OLCUM["sanal_tam"] = (len(metin(r)), len(json.dumps(yapi(r), ensure_ascii=False)), yapi(r).get("total"))
        kontrol("sanal observe interactive_only=false: etiketler de", 'label "Erişilebilirlik deneme penceresi"' in
                metin(r), metin(r)[:300])
        r = await c.call_tool("observe", {"window": "gozlem-a11y", "query": "kaydet|onay", **B})
        OLCUM["sanal_query"] = (len(metin(r)), len(json.dumps(yapi(r), ensure_ascii=False)), yapi(r).get("total"))
        adlar = [e.get("name") for e in yapi(r).get("elements", [])]
        kontrol("sanal observe query='kaydet|onay': yalnız eşleşenler", set(adlar) == {"Kaydet", "Onayla"}, str(adlar))
        r = await c.call_tool("observe", {"window": "gozlem-a11y", "max_elements": 5, **B})
        kontrol("sanal observe sayfalama: 5 öge + next_offset", yapi(r).get("count") == 5 and
                yapi(r).get("next_offset") == 5 and "next_offset 5" in metin(r), metin(r)[-200:])
        r2 = await c.call_tool("observe", {"window": "gozlem-a11y", "max_elements": 5, "offset": 5, **B})
        kontrol("sanal observe offset=5: numaralar 6'dan başlar", yapi(r2).get("elements", [{}])[0].get("ref", "")
                .endswith(":6"), str(yapi(r2).get("elements", [{}])[:1]))

        r = await c.call_tool("observe", {"window": "gozlem-a11y", **B})  # pencere başına 4 anlık görüntü: tazele
        st = yapi(r)
        ogeler = {e.get("name"): e for e in st.get("elements", [])}
        n0 = len(log_oku(LOG))
        r = await c.call_tool("click", {"ref": ogeler["Kaydet"]["ref"], **B})
        kontrol("sanal click(ref) → fare tıklaması, olay 'tikla:Kaydet', effect changed/no_change ölçüldü",
                not r.is_error and log_bekle(LOG, r"^tikla:Kaydet$", n0) and
                yapi(r).get("effect") in ("changed", "no_change", "confirmed"), metin(r)[:300])
        n0 = len(log_oku(LOG))
        r = await c.call_tool("click", {"ref": ogeler["Onayla"]["ref"], "via": "action", **B})
        kontrol("sanal click(ref, via=action) onay kutusu → effect confirmed (checked durumu değişti)",
                not r.is_error and log_bekle(LOG, r"^isaret:Onayla:1$", n0) and yapi(r).get("effect") == "confirmed",
                metin(r)[:300])
        r = await c.call_tool("observe", {"window": "gozlem-a11y", "since": st["snapshot_id"], **B})
        kontrol("sanal observe since: yalnız değişenler (~ Onayla checked)", "~ [" in metin(r) and
                any(e.get("name") == "Onayla" and "checked" in e.get("states", []) for e in yapi(r).get("changed", []))
                and yapi(r).get("since") == st["snapshot_id"], metin(r)[:400])
        n0 = len(log_oku(LOG))
        r = await c.call_tool("type_text", {"ref": ogeler["Ad"]["ref"], "text": "Çağrı", "clear_first": True, **B})
        kontrol("sanal type_text(ref) → alan tıklanıp yazıldı (metin:Ad:Çağrı)",
                not r.is_error and log_bekle(LOG, r"^metin:Ad:Çağrı$", n0), metin(r)[:300] + str(log_oku(LOG)[n0:]))
        r = await c.call_tool("scroll", {"ref": ogeler["Liste"]["ref"] if "Liste" in ogeler else
                                         ogeler["Birinci"]["ref"], "direction": "down", **B})
        kontrol("sanal scroll(ref) → öge üstünde kaydırma, effect var", not r.is_error and yapi(r).get("effect") in
                ("confirmed", "no_change"), metin(r)[:300])
        r = await c.call_tool("observe", {"window": "gozlem-a11y", "include_screenshot": True, **B})
        img = next((x for x in r.content if getattr(x, "type", "") == "image"), None)
        kontrol("sanal observe include_screenshot: numaralı PNG + shot_id", img is not None and yapi(r).get("shot_id")
                and Image.open(io.BytesIO(base64.b64decode(img.data))).size[0] > 100)
        # bayat ref: pencere boyutu değişti → [8] window, girdi yok
        st2 = yapi(await c.call_tool("observe", {"window": "gozlem-a11y", **B}))
        ref_k = next(e["ref"] for e in st2["elements"] if e.get("name") == "Kaydet")
        await c.call_tool("manage_window", {"window": "gozlem-a11y", "action": "resize", "width": 600, "height": 640, **B})
        await asyncio.sleep(0.4)
        n0 = len(log_oku(LOG))
        r = await c.call_tool("click", {"ref": ref_k, **B})
        kontrol("sanal bayat ref (pencere boyutu değişti) → [8] reason=window, sent nothing_sent, tık yok",
                r.is_error and yapi(r).get("error", {}).get("reason") == "window" and "sent: nothing_sent" in metin(r)
                and "next: " in metin(r) and not log_bekle(LOG, r"^tikla", n0, 0.5), metin(r)[:300])

        # wait_for
        r = await c.call_tool("wait_for", {"condition": "element", "value": "Gelişmiş", "role": "page tab",
                                           "window": "gozlem-a11y", "timeout_s": 3, **B})
        kontrol("wait_for element: ağaçta var → satisfied", not r.is_error and yapi(r).get("satisfied") is True,
                metin(r)[:200])
        t0 = time.monotonic()
        r = await c.call_tool("wait_for", {"condition": "element", "value": "Olmayan düğme xyz", "window": "gozlem-a11y",
                                           "timeout_s": 1.5, **B})
        kontrol("wait_for zaman aşımı → hata DEĞİL, satisfied=false (~1.5 sn)", not r.is_error and
                yapi(r).get("satisfied") is False and 1.0 <= time.monotonic() - t0 <= 6, metin(r)[:200])
        masaustu.baslat([sys.executable, os.path.join(KOK, "tests/yardimci/test_pencere.py")],
                        {"LOG": LOG2, "BASLIK": "gozlem-ikinci", "HAZIR_MS": "2500"})
        r = await c.call_tool("wait_for", {"condition": "window", "value": "^gozlem-ikinci$", "timeout_s": 20, **B})
        kontrol("wait_for window: yeni pencere başlık deseniyle belirdi", yapi(r).get("satisfied") is True and
                yapi(r).get("window", "").startswith("arka:"), metin(r)[:200])
        r = await c.call_tool("wait_for", {"condition": "text", "value": "Durum: Hazır", "window": "gozlem-ikinci",
                                           "timeout_s": 15, **B})
        kontrol("wait_for text: 'Durum: Hazır' göründü (ağaç/OCR)", yapi(r).get("satisfied") is True, metin(r)[:300])
        r = await c.call_tool("wait_for", {"condition": "gone", "value": "Yükleniyor", "window": "gozlem-ikinci",
                                           "timeout_s": 5, **B})
        kontrol("wait_for gone: 'Yükleniyor' kayboldu", yapi(r).get("satisfied") is True, metin(r)[:300])
        r = await c.call_tool("wait_for", {"condition": "stable", "window": "gozlem-ikinci", "stable_ms": 400,
                                           "timeout_s": 8, **B})
        kontrol("wait_for stable: pencere durgun", yapi(r).get("satisfied") is True, metin(r)[:300])

        # OCR satırı ref'i: boyanmış yazı (ağaçta yok) → OCR ögesi → tık
        r = await c.call_tool("observe", {"window": "gozlem-ikinci", "include_ocr": True, **B})
        oyun = next((e for e in yapi(r).get("elements", []) if e.get("source") == "ocr" and "OYUN" in e.get("name", "")),
                    None)
        kontrol("sanal observe include_ocr: ağaçta olmayan boyalı yazı 'OYUN ALANI' (ocr) ögesi; ağaçtaki 'Kaydet' OCR'da "
                "yinelenmez", oyun is not None and "ocr" in yapi(r).get("sources", []) and
                not any(e.get("source") == "ocr" and e.get("name") == "Kaydet" for e in yapi(r).get("elements", [])),
                metin(r)[:600])
        if oyun:
            n0 = len(log_oku(LOG2))
            r = await c.call_tool("click", {"ref": oyun["ref"], **B})
            kontrol("sanal click(OCR ref) → yazının üstüne tık (fare_bas)", not r.is_error and
                    log_bekle(LOG2, r"^fare_bas sol", n0), metin(r)[:300])
        st3 = yapi(await c.call_tool("observe", {"window": "gozlem-ikinci", **B}))
        ep = next((e for e in st3.get("elements", []) if e.get("role") in ("text", "entry")), None)
        n0 = len(log_oku(LOG2))
        if ep:
            r = await c.call_tool("type_text", {"ref": ep["ref"], "text": "deneme@ornek", **B})
            kontrol("sanal type_text(ref) effect=confirmed (yazı değişen bölgede görüldü)", not r.is_error and
                    log_bekle(LOG2, r"^eposta=deneme@ornek$", n0) and yapi(r).get("effect") == "confirmed",
                    metin(r)[:400])
        else:
            kontrol("sanal: E-posta alanı ağaçta", False, metin(r)[:300])
    masaustu.masaustu_durdur()


# ================================================================ C2) görünmez masaüstü, YALITIK Firefox (web ref)

def web_mumkun():
    try:
        import jeepney  # noqa: F401
    except ImportError:
        return False
    return bool(shutil.which("firefox") and shutil.which("Xvfb"))


async def web_testleri():
    """Firefox YALNIZ görünmez masaüstünde, yeni boş geçici profille (tests/yardimci/web_tarayici.py); kullanıcının
    profil kökü önce/sonra karşılaştırılır (fark = HEMEN dur). Sayfalar yerel ve sentetik (tests/ornek/web/)."""
    from mcp import Client
    import web_tarayici as wt
    from deskhand import onay
    from deskhand.arka_uc import sec
    bekci = wt.ProfilBekcisi()
    masaustu.masaustu_baslat()
    au = sec(arka_bayragi=True)
    srv = wt.Sunucu()
    acik = []
    istekler = []
    gercek_onay = onay.iste_sonuc

    def red(eylem_, hedef, ayrinti="", masaustu="ekran", sure=120, goruntu=None, gunluge_yaz=True):
        istekler.append(ayrinti)
        return onay.OnaySonucu(False, "red")
    onay.iste_sonuc = red

    def profil():
        f = bekci.fark()
        if f:
            print(f"!!! KULLANICI FIREFOX PROFİL KÖKÜ DEĞİŞTİ: {f}; test durduruldu", flush=True)
            for x in acik:
                x.kapat()
            masaustu.masaustu_durdur()
            os._exit(2)

    def tik(k):
        m = re.match(r"TIK (.+) #(\d+)", au.baslik(k) or "")
        return (m.group(1), int(m.group(2))) if m else (None, 0)

    B = {"desktop": "background"}
    try:
        async with Client(s.mcp) as c:
            ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("form.html"), erisilebilirlik=False)
            acik.append(ff)
            profil()
            k = ff.k
            st = {}
            for _ in range(60):
                r = await c.call_tool("observe", {"window": k, **B})
                st = yapi(r)
                if any(e.get("name") == "Kaydet" for e in st.get("elements", [])) and st.get("page", {}).get("title"):
                    break
                await asyncio.sleep(0.25)
            og = {e.get("name"): e for e in st.get("elements", [])}
            kontrol("web observe: sayfa ögeleri (kaynak web, sayfa başlığı/adres, yazısız aria-label düğmesi)",
                    st.get("sources", [None])[0] == "web" and "Kaydet" in og and "Ayarlar" in og and
                    st.get("page", {}).get("title") == "Deskhand Form Testi" and "page " in metin(r), metin(r)[:500])
            n0 = tik(k)[1]
            r = await c.call_tool("click", {"ref": og["Ayarlar"]["ref"], **B})
            await asyncio.sleep(0.3)
            kontrol("web click(ref) yazısız düğme → sayfanın günlüğü 'TIK Ayarlar'", not r.is_error and
                    tik(k)[0] == "Ayarlar" and tik(k)[1] == n0 + 1, metin(r)[:300] + str(tik(k)))
            r = await c.call_tool("click", {"ref": og["Kaydet"]["ref"], "via": "action", **B})
            await asyncio.sleep(0.3)
            kontrol("web click(ref, via=action) → 'TIK Kaydet'", not r.is_error and tik(k)[0] == "Kaydet",
                    metin(r)[:300] + str(tik(k)))
            ff.kapat()
            acik.remove(ff)
            profil()

            ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("odeme.html"), erisilebilirlik=False)
            acik.append(ff)
            profil()
            k = ff.k
            st = {}
            for _ in range(60):
                r = await c.call_tool("observe", {"window": k, **B})
                st = yapi(r)
                if st.get("sources", [None])[0] == "web" and st.get("elements") and st.get("page", {}).get("title"):
                    break
                await asyncio.sleep(0.25)
            kontrol("web observe ödeme sayfası: page.sensitive_page + başlıkta uyarı",
                    st.get("page", {}).get("sensitive_page") is True and "sensitive_page" in metin(r), metin(r)[:300])
            hedef = next((e for e in st.get("elements", []) if e.get("role") in ("button", "push button")), None)
            n0 = tik(k)[1]
            istekler.clear()
            r = await c.call_tool("click", {"ref": hedef["ref"] if hedef else "x", **B})
            await asyncio.sleep(0.3)
            kontrol("web click(ref) ödeme sayfasında sıradan düğme → onay istendi, red → [10], tık yok",
                    r.is_error and "[10]" in metin(r) and istekler and tik(k)[1] == n0, metin(r)[:300])
            ff.kapat()
            acik.remove(ff)
            profil()

            ff = wt.Firefox(au, _yalitim.PAYLASIM, srv.url("liste.html"), erisilebilirlik=False)
            acik.append(ff)
            profil()
            k = ff.k
            for _ in range(60):
                r = await c.call_tool("observe", {"window": k, **B})
                if (yapi(r).get("total") or 0) > 50 and yapi(r).get("sources", [None])[0] == "web":
                    break
                await asyncio.sleep(0.25)
            t0 = time.monotonic()
            r = await c.call_tool("observe", {"window": k, **B})
            sure = time.monotonic() - t0
            OLCUM["web_buyuk"] = (len(metin(r)), len(json.dumps(yapi(r), ensure_ascii=False)), yapi(r).get("total"),
                                  round(sure, 2))
            kontrol("web observe 1.000 bağlantılı sayfa: yalnız GÖRÜNEN ögeler (>100), ≤ 3 sn",
                    100 < (yapi(r).get("total") or 0) < 1000 and sure <= 3.0, f"{yapi(r).get('total')} {sure:.2f}")
            r = await c.call_tool("observe", {"window": k, "max_elements": 40, **B})
            kontrol("web observe max_elements=40: 40 satır + next_offset 40", yapi(r).get("count") == 40 and
                    yapi(r).get("next_offset") == 40 and "next_offset 40" in metin(r), metin(r)[-200:])
            OLCUM["web_buyuk_40"] = (len(metin(r)), len(json.dumps(yapi(r), ensure_ascii=False)), yapi(r).get("count"))
            t0 = time.monotonic()
            r = await c.call_tool("read_text", {"window": k, "source": "web", "hidden": True, "max_items": 300, **B})
            OLCUM["web_read_text_300"] = (len(metin(r)), len(json.dumps(yapi(r), ensure_ascii=False)),
                                          len(yapi(r).get("items", [])), round(time.monotonic() - t0, 2))
            r = await c.call_tool("observe", {"window": k, "query": "0012|yenile", **B})
            OLCUM["web_buyuk_query"] = (len(metin(r)), len(json.dumps(yapi(r), ensure_ascii=False)), yapi(r).get("total"))
            adlar = [e.get("name") for e in yapi(r).get("elements", [])]
            kontrol("web observe query='0012|yenile': yalnız eşleşenler", "Listeyi yenile" in adlar and
                    any("0012" in (a or "") for a in adlar) and len(adlar) <= 4, str(adlar))
            ff.kapat()
            acik.remove(ff)
            profil()
    finally:
        onay.iste_sonuc = gercek_onay
        for x in acik:
            x.kapat()
        srv.kapat()
        masaustu.masaustu_durdur()
        profil()


# ================================================================ D) sahte kde + sahte AT-SPI: kapılar ref yolunda

async def kapi_testleri():
    from mcp import Client
    import sahte_masaustu as sm
    from deskhand import guvenlik, kendi, yollar
    au = sm.kur()
    F = {"desktop": "foreground"}
    async with Client(s.mcp) as c:
        async def gozle(**k):
            r = await c.call_tool("observe", {"window": "KWrite", **F, **k})
            return {e.get("name"): e for e in yapi(r).get("elements", [])}, yapi(r), r

        og, st, r = await gozle()
        kontrol("sahte observe: ağaç ögeleri + ref'ler, label interactive_only'de yok",
                {"Kaydet", "Satın al", "Ad", "Parola", "Onayla"} <= set(og) and "Form başlığı" not in og, metin(r)[:400])
        kontrol("sahte observe: değer (Ad=Ali) var, parola alanında değer yok", og["Ad"].get("value") == "Ali" and
                "value" not in og["Parola"])

        # --- temel ref yolları
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"ref": og["Kaydet"]["ref"], **F})
        X, Y = sm.GEO[:2]
        kontrol("ref click: fare öge merkezine (pencere 160,120) gitti, tık atıldı",
                not r.is_error and "click left" in au.satirlar[n0:] and abs(au.imlec[0] - (X + 160)) <= 2 and
                abs(au.imlec[1] - (Y + 120)) <= 2, f"{au.imlec} {metin(r)[:300]}")
        kontrol("ref click: sonuç effect + ref alanı", yapi(r).get("effect") in ("no_change", "changed") and
                yapi(r).get("ref") == og["Kaydet"]["ref"], str(yapi(r))[:300])
        sm.ISLEMLER.clear()
        r = await c.call_tool("click", {"ref": og["Onayla"]["ref"], "via": "action", **F})
        kontrol("ref click via=action (kde): AT-SPI eylemi, fare yok; durum değişti → effect confirmed",
                not r.is_error and sm.eylemler() == [("eylem", "Onayla", "Toggle")] and
                yapi(r).get("effect") == "confirmed", metin(r)[:300])
        n0 = len(au.satirlar)
        r = await c.call_tool("type_text", {"ref": og["Ad"]["ref"], "text": "Veli", **F})
        sat = au.satirlar[n0:]
        kontrol("ref type_text: önce alan tıklanır, sonra yazılır", not r.is_error and "click left" in sat and
                any(x.startswith("type ") for x in sat) and sat.index("click left") <
                next(i for i, x in enumerate(sat) if x.startswith("type ")), str(sat))
        n0 = len(au.satirlar)
        r = await c.call_tool("scroll", {"ref": og["Liste bir"]["ref"], "direction": "down", **F})
        kontrol("ref scroll: öge merkezinde tekerlek", not r.is_error and "wheel -3" in au.satirlar[n0:] and
                abs(au.imlec[0] - (X + 180)) <= 2, str(au.satirlar[n0:]))
        n0 = len(au.satirlar)
        r = await c.call_tool("drag", {"from_ref": og["Liste bir"]["ref"], "to_ref": og["Bırak"]["ref"], "hold_s": 0.1,
                                       **F})
        sat = au.satirlar[n0:]
        kontrol("ref drag: from_ref'te bas, to_ref'te bırak", not r.is_error and "buttondown left" in sat and
                "buttonup left" in sat and abs(au.imlec[0] - (X + 580)) <= 3, f"{sat[:3]} {au.imlec} {metin(r)[:200]}")

        # --- bayatlık: üç neden ayrı, hiçbirinde girdi yok
        async def bayat(ad, arg, neden, hazirla=None):
            if hazirla:
                hazirla()
            n0 = len(au.satirlar)
            sm.ISLEMLER.clear()
            r = await c.call_tool("click", {**arg, **F})
            kontrol(f"bayat ref [{ad}] → [8] reason={neden}, sent nothing_sent, next satırı, girdi YOK",
                    r.is_error and "[8]" in metin(r) and yapi(r).get("error", {}).get("reason") == neden and
                    yapi(r).get("sent") == "nothing_sent" and "sent: nothing_sent" in metin(r) and "observe" in metin(r)
                    and len(au.satirlar) == n0 and not sm.eylemler(), metin(r)[:300])

        og, st, _r = await gozle()
        await bayat("bilinmeyen anlık görüntü", {"ref": "ffff-999:1"}, "snapshot")
        s.GOZLEM.al(st["snapshot_id"])[0].zaman -= 500
        await bayat("süresi doldu", {"ref": og["Kaydet"]["ref"]}, "snapshot")
        og, st, _r = await gozle()
        for _i in range(4):  # pencere başına 4: en eskisi düşer
            await gozle()
        await bayat("pencere başına sınırdan düştü", {"ref": og["Kaydet"]["ref"]}, "snapshot")
        og, st, _r = await gozle()
        au.pen["{diger}"] = ["Başka Pencere", "baska", (900, 100, 400, 300)]
        await bayat("başka pencere (window verildi)", {"ref": og["Kaydet"]["ref"], "window": "Başka Pencere"}, "window")
        au.pen.pop("{diger}")
        await bayat("pencere boyutu değişti", {"ref": og["Kaydet"]["ref"]}, "window",
                    lambda: au.pen[sm.PENCERE].__setitem__(2, (100, 100, 820, 600)))
        au.pen[sm.PENCERE][2] = sm.GEO
        og, st, _r = await gozle()
        kaydet = next(o for o in sm.AGAC["Belge — KWrite"] if o["ad"] == "Kaydet")
        await bayat("öge kayboldu", {"ref": og["Kaydet"]["ref"]}, "element",
                    lambda: sm.AGAC["Belge — KWrite"].remove(kaydet))
        sm.AGAC["Belge — KWrite"].insert(1, kaydet)
        await bayat("öge adı değişti (aynı kimlik)", {"ref": og["Kaydet"]["ref"]}, "element",
                    lambda: kaydet.update(ad="Sil"))
        kaydet["ad"] = "Kaydet"
        await bayat("öge 5 px kaydı", {"ref": og["Kaydet"]["ref"]}, "element", lambda: kaydet.update(x=85, cx=165))
        kaydet.update(x=80, cx=160)
        await bayat("öge numarası anlık görüntüde yok", {"ref": st["snapshot_id"] + ":999"}, "element")
        kaydet.update(x=82, cx=162)
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"ref": og["Kaydet"]["ref"], **F})
        kontrol("ref: öge 2 px kaydı (±3 içinde) → tıklandı, GÜNCEL merkeze", not r.is_error and "click left" in
                au.satirlar[n0:] and abs(au.imlec[0] - (X + 162)) <= 2, f"{au.imlec} {metin(r)[:200]}")
        kaydet.update(x=80, cx=160)
        # adla aramaya düşülmez: aynı adlı başka bir düğme var, ref'inki kayboldu → yine ret
        og, st, _r = await gozle()
        sm.AGAC["Belge — KWrite"].remove(kaydet)
        sm.AGAC["Belge — KWrite"].append(sm.oge("push button", "Kaydet", 600, 500, kimlik=(":1.9", "/b/1"), yol=[3]))
        await bayat("aynı adlı BAŞKA düğme var ama ref'inki yok (adla aramaya düşülmez)",
                    {"ref": og["Kaydet"]["ref"]}, "element")

        # --- kapılar (ref yolunda): her biri için girdi gitmez / onay istenir
        async def kapi(ad, arac, arg, kod, hazirla, onay_beklenir=False, sent="nothing_sent", baslik="Belge — KWrite",
                       sinif="kwrite", girdi_yok=("click", "type ")):
            au_ = sm.sifirla(baslik, sinif)
            og_, _st, _r = await gozle_(baslik)
            hazirla(au_)
            n0 = len(au_.satirlar)
            sm.ISLEMLER.clear()
            a = {**arg, **F}
            for anahtar_ in ("ref", "from_ref"):
                if anahtar_ in a:
                    a[anahtar_] = og_[a[anahtar_]]["ref"]
            r = await c.call_tool(arac, a)
            sat = au_.satirlar[n0:]
            gitti = [x for x in sat if any(x.startswith(g) for g in girdi_yok)]
            ok = (r.is_error and f"[{kod}]" in metin(r) and not gitti and not sm.eylemler() and
                  yapi(r).get("sent") == sent and (onay_beklenir is None or bool(sm.ISTEKLER) == onay_beklenir))
            kontrol(f"kapı [{ad}] ref yolunda → [{kod}]" + (", onay istendi" if onay_beklenir else "") +
                    f", {sent}, hedefe girdi yok", ok, f"{metin(r)[:300]} | {sat} | {sm.ISTEKLER[:1]}")
            return au_, r

        async def gozle_(baslik):
            r = await c.call_tool("observe", {"window": re.escape(baslik), **F})
            return {e.get("name"): e for e in yapi(r).get("elements", [])}, yapi(r), r

        await kapi("DUR", "click", {"ref": "Kaydet"}, 13, lambda a: guvenlik.dur_ac("cli"))
        guvenlik.dur_kapat("cli")
        await kapi("hassas öge 'Satın al' (red)", "click", {"ref": "Satın al"}, 10, lambda a: None, onay_beklenir=True)
        await kapi("hassas öge via=action (red)", "click", {"ref": "Satın al", "via": "action"}, 10, lambda a: None,
                   onay_beklenir=True)
        await kapi("hassas sayfa başlığı (red)", "click", {"ref": "Kaydet"}, 10, lambda a: None, onay_beklenir=True,
                   baslik="Checkout - Ödeme - Shop")

        def degistir_onayda(a):
            sm.YANIT["izin"] = True
            sm.YANIT["kanca"] = lambda: next(o for o in sm.AGAC["Belge — KWrite"] if o["ad"] == "Satın al").update(
                ad="Satın al (2)")
        await kapi("onaydan sonra öge değişti (izin)", "click", {"ref": "Satın al"}, 10, degistir_onayda,
                   onay_beklenir=True)

        def bekleyen(a):
            s._BEKLEYEN["kde"] = 1
        await kapi("bekleyen onay", "click", {"ref": "Kaydet"}, 7, bekleyen)
        s._BEKLEYEN.clear()

        def kendi_(a):
            a.pid_[sm.PENCERE] = str(kendi.atalar()[1][0])
            kendi.sifirla()
        await kapi("ajanın kendi istemcisi", "click", {"ref": "Kaydet"}, 10, kendi_)
        kendi.sifirla()

        def seviye(a):
            os.makedirs(os.path.dirname(yollar.seviye_dosya()), exist_ok=True)
            with open(yollar.seviye_dosya(), "w") as f:
                f.write("KWrite = goruntule\n")
        await kapi("uygulama seviyesi goruntule", "click", {"ref": "Kaydet"}, 10, seviye)
        await kapi("uygulama seviyesi goruntule (via=action)", "click", {"ref": "Kaydet", "via": "action"}, 10, seviye)
        os.remove(yollar.seviye_dosya())
        # sistem istemi: ref tıklaması da (koordinatlı tık / via=action gibi) önce onay sorar; red → 10, girdi yok
        await kapi("sistem istemi (polkit)", "click", {"ref": "Kaydet"}, 10, lambda a: None, onay_beklenir=True,
                   baslik="Kimlik doğrulama gerekli", sinif="polkit-kde-authentication-agent-1")
        _au, r = await kapi("parola alanı (red): tık gitti, YAZI gitmedi", "type_text", {"ref": "Parola", "text": "gizli1"},
                            10, lambda a: None, onay_beklenir=True, sent="maybe_partial", girdi_yok=("type ",))
        kontrol("parola alanı: parola metni ileti/onay isteğinde yok", "gizli1" not in metin(r) and
                not any("gizli1" in x["ayrinti"] for x in sm.ISTEKLER))
        await kapi("uçbirim Enter kapısı ('sud' + 'o reboot' + Enter) (red)", "type_text",
                   {"ref": "Ad", "text": "o reboot", "submit": True}, 10, lambda a: None, onay_beklenir=True,
                   sent="maybe_partial", baslik="kullanici@makine: ~", sinif="konsole", girdi_yok=("type ", "key "))

        def insan(a):
            a.insan = True
        await kapi("insan önceliği", "click", {"ref": "Kaydet"}, 12, insan)
        await kapi("oyun/film koruması", "click", {"ref": "Kaydet"}, 15,
                   lambda a: setattr(a, "koruma", (15, "kullanıcı oyunda")))
        await kapi("oyun/film koruması (via=action)", "click", {"ref": "Kaydet", "via": "action"}, 15,
                   lambda a: setattr(a, "koruma", (15, "kullanıcı oyunda")))
        await kapi("DUR (via=action)", "click", {"ref": "Kaydet", "via": "action"}, 13, lambda a: guvenlik.dur_ac("cli"))
        guvenlik.dur_kapat("cli")
        await kapi("sistem istemi via=action", "click", {"ref": "Kaydet", "via": "action"}, 10, lambda a: None,
                   onay_beklenir=None, baslik="Kimlik doğrulama gerekli", sinif="polkit-kde-authentication-agent-1")
        await kapi("sistem istemi type_text(ref)", "type_text", {"ref": "Ad", "text": "x"}, 10, lambda a: None,
                   onay_beklenir=None, baslik="Kimlik doğrulama gerekli", sinif="polkit-kde-authentication-agent-1",
                   girdi_yok=("click", "type ", "mouseto"))

        # izinle hassas öge: BİR kez tıklanır
        au = sm.sifirla()
        og, st, _r = await gozle()
        sm.YANIT["izin"] = True
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"ref": og["Satın al"]["ref"], **F})
        kontrol("hassas öge + izin → bir kez tıklandı, approved_by_user", not r.is_error and
                au.satirlar[n0:].count("click left") == 1 and yapi(r).get("approved_by_user") is True,
                metin(r)[:300])

        # --- OCR'a düşme + OCR satırı ref'i (ağaç yok)
        au = sm.sifirla()
        sm.AGACSIZ.add("Belge — KWrite")
        r = await c.call_tool("observe", {"window": "KWrite", **F})
        st = yapi(r)
        kay = next((e for e in st.get("elements", []) if e.get("source") == "ocr" and e.get("name") == "Kaydet"), None)
        kontrol("ağaç yok → OCR'a kendiliğinden düşer (sources ocr, not satırı, 'Kaydet' ocr ögesi)",
                not r.is_error and st.get("sources") == ["ocr"] and kay is not None and st.get("notes"), metin(r)[:400])
        if kay:
            n0 = len(au.satirlar)
            r = await c.call_tool("click", {"ref": kay["ref"], **F})
            kontrol("OCR ref click → yazının üstüne tık", not r.is_error and "click left" in au.satirlar[n0:] and
                    X + 85 <= au.imlec[0] <= X + 220, f"{au.imlec} {metin(r)[:300]}")
            au.yazilar[sm.PENCERE] = [("Başka", 300, 300)]
            n0 = len(au.satirlar)
            r = await c.call_tool("click", {"ref": kay["ref"], **F})
            kontrol("OCR ref: yazı yerinde değil → [8] element, tık yok", r.is_error and
                    yapi(r).get("error", {}).get("reason") == "element" and "click left" not in au.satirlar[n0:],
                    metin(r)[:300])
            r = await c.call_tool("click", {"ref": kay["ref"], "via": "action", **F})
            kontrol("OCR ref + via=action → [1]", r.is_error and "[1]" in metin(r))

        # --- sonuç sözleşmesi: hata metni ve yapı
        au = sm.sifirla()
        r = await c.call_tool("click", {"window": "KWrite", "text": "Kaydet", "ref": "ab12-1:1", **F})
        kontrol("iki hedef → [1] + sent nothing_sent + next", r.is_error and "[1]" in metin(r) and
                "sent: nothing_sent" in metin(r) and yapi(r).get("error", {}).get("code") == 1)
        guvenlik.dur_ac("cli")
        r = await c.call_tool("press_key", {"window": "KWrite", "keys": "enter", **F})
        kontrol("DUR → next satırı 'STOP' yönergesi, effect refused", r.is_error and "next: the user pressed STOP" in
                metin(r) and yapi(r).get("effect") == "refused")
        guvenlik.dur_kapat("cli")
        og, st, _r = await gozle()
        n0 = len(au.satirlar)

        def dur_yarida(satir):  # yazının ortasında kullanıcı DUR'a basar
            if satir.startswith("type ") and sum(x.startswith("type ") for x in au.satirlar) >= 2:
                guvenlik.dur_ac("kullanici")
        au.kanca_satir = dur_yarida
        r = await c.call_tool("type_text", {"window": "KWrite", "text": "abcdef", **F})
        au.kanca_satir = None
        guvenlik.dur_kapat("kullanici")
        kontrol("yazı ortasında DUR → [13], sent maybe_partial, effect unverifiable", r.is_error and "[13]" in metin(r)
                and yapi(r).get("sent") == "maybe_partial" and yapi(r).get("effect") == "unverifiable", metin(r)[:300])
        r = await c.call_tool("press_key", {"window": "KWrite", "keys": "a", **F})
        kontrol("press_key sonucu effect (sahte görüntü değişmez → no_change)", yapi(r).get("effect") == "no_change",
                str(yapi(r))[:200])

        # döngü kesici ref ile: aynı ögeye sonuçsuz tık → uyarı, 6.'sı ret
        uyari = ret = None
        for i in range(6):
            r = await c.call_tool("click", {"ref": og["Kaydet"]["ref"], **F})
            if yapi(r).get("warning") and uyari is None:
                uyari = i + 1
            if r.is_error:
                ret = (i + 1, metin(r)[:120])
                break
        kontrol("döngü kesici ref yolunda: 3. sonuçsuzda uyarı, 6.'sı [7]", uyari == 3 and ret and ret[0] == 6 and
                "[7]" in ret[1], f"{uyari} {ret}")
        s._DONGU.temizle()


def baslik_norm_testleri():
    n = gozlem.baslik_norm
    kontrol("baslik_norm: '(3) Gmail' ≡ '(4) Gmail' ≡ 'Gmail'", n("(3) Gmail") == n("(4) Gmail") == n("Gmail") == "Gmail")
    kontrol("baslik_norm: 'İndiriliyor %45' ≡ 'İndiriliyor %46' ≡ 'İndiriliyor 7 %'",
            n("İndiriliyor %45") == n("İndiriliyor %46") == n("İndiriliyor 7 %") == "İndiriliyor #")
    kontrol("baslik_norm: 'A.txt — KWrite' ≠ 'B.txt — KWrite'; 'A — Dolphin' ≠ 'B — Dolphin'",
            n("A.txt — KWrite") != n("B.txt — KWrite") and n("A — Dolphin") != n("B — Dolphin"))
    kontrol("baslik_norm: None/boş güvenli; boşluklar sadeleşir", n(None) == "" and n("  a   b ") == "a b")


async def duzeltme_a_testleri():
    """Son denetim A düzeltmeleri (sahte kde + sahte AT-SPI; gerçek ekrana girdi YOK):
    - ref'in anlık görüntüsündeki pencere başlığı değişince eylem reddedilir ([8]); ref yollarında başlık kilidi
      anlık görüntünün başlığından kurulur;
    - wait_for ön planda pencereyi ÖNE GETİRMEZ (hedef etkin değilse yalnız ağaç; ağaç yoksa satisfied=false + not;
      kullanıcı etkinken yoklama atlanır, süre sayılır);
    - batch desktop='auto' başta BİR kez çözülür."""
    from mcp import Client
    import sahte_masaustu as sm
    F = {"desktop": "foreground"}
    sm.kur()

    def oge_sayaci(au):
        say = {"n": 0}
        asil = au.one_getir

        def sayan(k):
            if k != au.aktif_:
                say["n"] += 1
            asil(k)
        au.one_getir = sayan
        return say

    def baska_pencere(au):
        au.pen["{diger}"] = ["Kullanıcının penceresi", "firefox", (900, 100, 600, 600)]
        au.aktif_ = "{diger}"

    async with Client(s.mcp) as c:
        # --- 1) ref + başlık
        kontrol("baslik_kilidi: ref başlığı verilince tam eşleşen desen (kimlikle değil anlık görüntüyle)",
                s.baslik_kilidi(None, "{w}", "Eski [başlık]") == "^" + re.escape("Eski [başlık]") + "$" and
                s.baslik_kilidi("^x$", "{w}", "Eski") == "^x$")
        kd = s.degisiklik_toleransli("kw.txt — KWrite")
        kontrol("kimlik başlık kilidi: düzenleyicinin 'kaydedilmedi' işareti (* ●) kilidi düşürmez, başka belge düşürür",
                all(re.search(kd, t) for t in ("kw.txt — KWrite", "kw.txt * — KWrite", "*kw.txt — KWrite",
                                                "● kw.txt — KWrite")) and
                not any(re.search(kd, t) for t in ("başka.txt — KWrite", "kw.txt — Kate", "kw.txt — KWrite 2")), kd)
        au = sm.sifirla()
        r = await c.call_tool("observe", {"window": "KWrite", **F})
        m = re.search(r"\[(\d+)\] push button \"Kaydet\"", metin(r))
        sid = re.search(r"snapshot ([0-9a-f]{4}-\d+)", metin(r))
        ref = f"{sid.group(1)}:{m.group(1)}" if (m and sid) else None
        kontrol("ön koşul: observe 'Kaydet' ögesini verdi", ref is not None, metin(r)[:200])
        if ref:
            sm.AGAC["(3) Belge — KWrite"] = sm.AGAC.pop("Belge — KWrite")
            au.pen[sm.PENCERE][0] = "(3) Belge — KWrite"
            n0 = len(sm.eylemler())
            r = await c.call_tool("click", {"ref": ref, **F})
            kontrol("ağaç ref'i: başlıkta YALNIZ sayaç değişti ('(3) Belge' ≡ 'Belge') → öge kimliğiyle doğrulandı, click gitti",
                    not r.is_error and "[8]" not in metin(r), metin(r)[:200])
            sm.AGAC["Yeni belge — KWrite"] = sm.AGAC.pop("(3) Belge — KWrite")
            au.pen[sm.PENCERE][0] = "Yeni belge — KWrite"
            n0 = len(sm.eylemler())
            nk = len([x for x in au.satirlar if x.startswith("click")])
            r = await c.call_tool("click", {"ref": ref, **F})
            kontrol("ağaç ref'i: başlık BAŞKA belgeye değişti → [8] 'başlığı değişti', eylem yok",
                    r.is_error and "[8]" in metin(r) and "başlığı değişti" in metin(r) and len(sm.eylemler()) == n0 and
                    len([x for x in au.satirlar if x.startswith("click")]) == nk, metin(r)[:200])
            au = sm.sifirla()
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            m = re.search(r"\[(\d+)\] push button \"Kaydet\"", metin(r))
            sid = re.search(r"snapshot ([0-9a-f]{4}-\d+)", metin(r))
            r = await c.call_tool("click", {"ref": f"{sid.group(1)}:{m.group(1)}", **F})
            kontrol("kontrol: başlık değişmediyse ref tıklaması yine çalışır", not r.is_error, metin(r)[:200])

        # --- 2) wait_for ön planda
        au = sm.sifirla()
        baska_pencere(au)
        say = oge_sayaci(au)
        r = await c.call_tool("wait_for", {"condition": "text", "value": "Kaydet", "window": "KWrite",
                                           "timeout_s": 2, **F})
        sy = r.structured_content or {}
        kontrol("wait_for(text) ön plan, hedef etkin değil, ağaç var → ağaçtan bulundu, pencere öne getirilmedi",
                sy.get("satisfied") is True and say["n"] == 0 and au.aktif_ == "{diger}", f"{say} {metin(r)[:200]}")
        r = await c.call_tool("wait_for", {"condition": "gone", "value": "Kaydet", "window": "KWrite",
                                           "timeout_s": 1, **F})
        kontrol("wait_for(gone) etkin değil: öge ağaçta duruyor → satisfied=false, öne getirme yok",
                (r.structured_content or {}).get("satisfied") is False and say["n"] == 0)
        # gone + ağaç kipi: yalnız OCR'la görünen metin ağaçta hiç yoktur → ilk yoklamada sahte "kayboldu" olmaz
        r = await c.call_tool("wait_for", {"condition": "gone", "value": "Yalnız boyalı yazı", "window": "KWrite",
                                           "timeout_s": 1.2, **F})
        sy = r.structured_content or {}
        kontrol("wait_for(gone) etkin değil: metin ağaçta hiç görülmedi → satisfied=false + not, öne getirme yok",
                sy.get("satisfied") is False and sy.get("note") and say["n"] == 0 and sy.get("polls", 0) > 1,
                f"{say} {sy}")
        kay_oge = next((o for o in sm.AGAC["Belge — KWrite"] if o["ad"] == "Kaydet"), None)
        kontrol("ön koşul: sahte ağaçta 'Kaydet' ögesi var", kay_oge is not None)
        if kay_oge is not None:
            zamanlayici = threading.Timer(0.6, lambda: sm.AGAC["Belge — KWrite"].remove(kay_oge))
            zamanlayici.start()
            r = await c.call_tool("wait_for", {"condition": "gone", "value": "Kaydet", "window": "KWrite",
                                               "timeout_s": 5, **F})
            zamanlayici.join()
            sy = r.structured_content or {}
            kontrol("wait_for(gone) etkin değil: metin önce ağaçta görüldü, sonra kayboldu → satisfied, not yok, "
                    "öne getirme yok", sy.get("satisfied") is True and not sy.get("note") and say["n"] == 0,
                    f"{say} {sy}")
            sm.AGAC["Belge — KWrite"].append(kay_oge)
        r = await c.call_tool("wait_for", {"condition": "stable", "window": "KWrite", "timeout_s": 3,
                                           "stable_ms": 300, **F})
        kontrol("wait_for(stable) etkin değil: ağaç imzası durgun → satisfied, öne getirme yok",
                (r.structured_content or {}).get("satisfied") is True and say["n"] == 0, metin(r)[:200])
        sm.AGACSIZ.add("Belge — KWrite")
        r = await c.call_tool("wait_for", {"condition": "text", "value": "Kaydet", "window": "KWrite",
                                           "timeout_s": 1.5, **F})
        sy = r.structured_content or {}
        kontrol("wait_for(text) etkin değil + ağaç yok → satisfied=false, tek 'not', öne getirme yok",
                sy.get("satisfied") is False and say["n"] == 0 and str(sy.get("note", "")).count("pencere önde değil") == 1,
                f"{say} {sy}")
        au.insan = True
        sm.AGACSIZ.clear()
        t0 = time.monotonic()
        r = await c.call_tool("wait_for", {"condition": "text", "value": "Kaydet", "window": "KWrite",
                                           "timeout_s": 1.5, **F})
        sy = r.structured_content or {}
        kontrol("wait_for kullanıcı etkinken: yoklama atlanır (satisfied=false), süre sayılır, odak değişmez",
                sy.get("satisfied") is False and say["n"] == 0 and time.monotonic() - t0 >= 1.0 and sy.get("polls", 0) > 1,
                f"{say} {sy}")
        au.insan = False
        au.aktif_ = sm.PENCERE  # hedef etkin: eski yol (görüntü/OCR) çalışır
        sm.AGACSIZ.add("Belge — KWrite")
        r = await c.call_tool("wait_for", {"condition": "text", "value": "Kaydet", "window": "KWrite",
                                           "timeout_s": 5, **F})
        kontrol("wait_for(text) hedef zaten etkin: OCR yolu aynı kaldı (satisfied)",
                (r.structured_content or {}).get("satisfied") is True, metin(r)[:200])

        # --- 3) batch auto bir kez
        au = sm.sifirla()
        cagri = []
        asil = s.masaustu_coz

        def sayac(desktop, ozet):
            cagri.append(desktop)
            return asil(desktop, ozet)
        s.masaustu_coz = sayac
        try:
            r = await c.call_tool("batch", {"steps": [{"tool": "wait", "args": {"seconds": 0}}] * 3})
        finally:
            s.masaustu_coz = asil
        kontrol("batch desktop='auto': başta bir kez çözüldü, adımlara somut masaüstü gitti",
                not r.is_error and cagri.count("auto") == 1 and set(cagri) <= {"auto", "foreground"}, str(cagri))

        # --- 3b) batch: "sonra" kararı yapılandırılmış stopped (tur6 gibi); masaüstü notu sonuca note olarak eklenir
        au = sm.sifirla()
        import deskhand.mesgul as mesgul
        asil_karar, asil_mesgul = mesgul.karar, s._mesgul
        mesgul.karar = lambda ozet: "sonra"
        try:
            n0 = len(sm.eylemler())
            r = await c.call_tool("batch", {"steps": [{"tool": "press_key", "args": {"window": "KWrite", "keys": "a"}},
                                                      {"tool": "wait", "args": {"seconds": 0}}]})
        finally:
            mesgul.karar = asil_karar
        sy = yapi(r)
        kontrol("batch 'sonra' kararı: çıplak hata değil, yapılandırılmış stopped (failed_step=1, not_sent=[2], "
                "nothing_sent), girdi yok", r.is_error and sy.get("status") == "stopped" and sy.get("failed_step") == 1
                and sy.get("not_sent") == [2] and sy.get("sent") == "nothing_sent" and sy.get("effect") == "refused"
                and sy.get("steps") and sy["steps"][0].get("ok") is False and len(sm.eylemler()) == n0
                and not [x for x in au.satirlar if x.startswith("key")], f"{metin(r)[:300]} {sy}")
        au = sm.sifirla()
        s._mesgul = lambda: None
        try:
            r = await c.call_tool("batch", {"steps": [{"tool": "wait", "args": {"seconds": 0}}]})
        finally:
            s._mesgul = asil_mesgul
        sy = yapi(r)
        kontrol("batch auto: masaüstü notu ('meşgul modülü yok…') sonuca note olarak eklenir",
                not r.is_error and "note: " in metin(r) and "batch ok" in metin(r),
                f"{metin(r)[:300]} {sy}")

        # --- 4) tüm ekran anlık görüntüsü: ref başlık denetimi (başlık pencere_bilgi'den; au.baslik(EKRAN) ≠ "")
        au = sm.sifirla()
        r = await c.call_tool("observe", {**F})
        st = yapi(r)
        kay = next((e for e in st.get("elements", []) if e.get("source") == "ocr" and e.get("name") == "Kaydet"), None)
        kontrol("tüm ekran observe (pencere yok): OCR 'Kaydet' ögesi + ref", not r.is_error and kay is not None,
                metin(r)[:300])
        if kay:
            n0 = len(au.satirlar)
            r = await c.call_tool("click", {"ref": kay["ref"], **F})
            kontrol("tüm ekran ref ile click: [8] YOK, tık gitti (başlık pencere_bilgi'den, EKRAN başlığı '')",
                    not r.is_error and "[8]" not in metin(r) and "click left" in au.satirlar[n0:], metin(r)[:300])
        au = sm.sifirla()
        sm.AGACSIZ.add("Belge — KWrite")  # ağaç yok → pencerenin ögeleri yalnız OCR
        r = await c.call_tool("observe", {"window": "KWrite", "include_ocr": True, **F})
        st = yapi(r)
        kay = next((e for e in st.get("elements", []) if e.get("source") == "ocr"), None)
        kontrol("pencere observe include_ocr: en az bir OCR ögesi + ref", not r.is_error and kay is not None,
                metin(r)[:300])
        if kay:
            au.pen[sm.PENCERE][0] = "Başka başlık — KWrite"
            n0 = len(au.satirlar)
            r = await c.call_tool("click", {"ref": kay["ref"], **F})
            kontrol("pencere OCR ref'i: başlık değişince yine [8] + ipucu (window deseni + text/koordinat), tık yok",
                    r.is_error and "[8]" in metin(r) and "window" in metin(r) and "click left" not in au.satirlar[n0:],
                    metin(r)[:300])
        sm.AGACSIZ.discard("Belge — KWrite")

        # --- web ref'i: bağlam = belge ADRESİ (parça dahil); başlık serbest ("(3) Gmail", tık günlüğü)
        au = sm.sifirla()
        adres = ["https://posta.ornek/#inbox/A"]

        class SahteWeb:
            ETKILESIMLI = frozenset({"push button"})

            @staticmethod
            def sayfa_bilgisi(k):
                if adres[0] is None:
                    raise Dur(6, "adres yok")
                return {"adres": adres[0], "baslik": "x", "belge": 1}
        web_oge = gozlem.web_ogesi({"rol": "push button", "ad": "Sil", "kutu": [10, 10, 60, 20], "_bus": ":1.9",
                                    "_yol": "/o/1", "_anahtar": [0]}, {"push button"})
        asil_topla, asil_web = s._agac_topla, s._web
        s._agac_topla = lambda k, genis=False: ([dict(web_oge)], "web", {"adres": adres[0], "baslik": "A", "belge": 1}, [])
        s._web = lambda: SahteWeb
        try:
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            sil = next((e for e in yapi(r).get("elements", []) if e.get("name") == "Sil"), None)
            kontrol("web ref: observe sahte web ögesi + ref", sil is not None, metin(r)[:300])
            if sil:
                ref = sil["ref"]
                au.pen[sm.PENCERE][0] = "(3) Gmail — Firefox"  # başlık değişti, adres aynı
                try:
                    k_, o_, b_ = s._ref_coz(ref, None)
                    kontrol("web ref: başlık değişti ama adres aynı → ref çözüldü (başlık denetimi yok)",
                            o_["kaynak"] == "web" and b_ is None)
                except Exception as e:  # noqa: BLE001
                    kontrol("web ref: başlık değişti ama adres aynı → ref çözüldü", False, repr(e)[:200])
                adres[0] = "https://posta.ornek/#inbox/B"  # SPA gezinmesi: yalnız parça değişti
                n0 = len(au.satirlar)
                r = await c.call_tool("click", {"ref": ref, **F})
                kontrol("web ref: adres (yalnız #parça) değişti → [8] 'sayfası değişti', eylem yok",
                        r.is_error and "[8]" in metin(r) and "sayfası değişti" in metin(r) and
                        "click left" not in au.satirlar[n0:], metin(r)[:300])
                adres[0] = None  # adres okunamıyor → normalize başlığa düşülür (başlık başka belge → [8])
                try:
                    s._ref_coz(ref, None)
                    kontrol("web ref: adres okunamaz → başlık denetimine düştü (başlık değişmiş → [8])", False,
                            "reddedilmeliydi")
                except Exception as e:  # noqa: BLE001
                    kontrol("web ref: adres okunamaz → başlık denetimine düştü (başlık değişmiş → [8])",
                            "[8]" in str(e) and "başlığı değişti" in str(e), repr(e)[:200])
        finally:
            s._agac_topla, s._web = asil_topla, asil_web


async def tur5_kapi_testleri():
    """tur6 birleştirmesi: Faz 10'un ref/batch/observe yolları tur5'in kapılarından geçer (sahte kde + sahte AT-SPI).
    - type_text(ref) ve batch adımlarındaki HER Enter (uçbirimde) ayrı onay ister (bir Enter = bir onay);
    - click(ref) yapıştırma ögesine (simgeli "Yapıştır" düğmesi) kullanıcının panosu için onay ister;
    - sistem istemi penceresinde click(ref | text | element) koordinatlı tık ve via=action gibi ONAY SORAR;
    - observe'un çerçeve seçimi yalnız pencere süreci + aynı programlı torun (ata uygulamanın ağacı listelenmez);
    - observe/batch: structuredContent yok, metin kısa (çekirdeğin yapılandırılmış sözlüğüyle karşılaştırma)."""
    from mcp import Client
    import sahte_masaustu as sm
    from deskhand import kendi
    F = {"desktop": "foreground"}
    sm.kur()
    UCB, UCB_SINIF = "kullanici@makine: ~", "konsole"

    def enter_istekleri():
        return [x for x in sm.ISTEKLER if "Enter" in x["eylem"] + x["ayrinti"] or "Uçbirim" in x["eylem"]]

    async with Client(s.mcp) as c:
        async def gozle(baslik):
            r = await c.call_tool("observe", {"window": re.escape(baslik), **F})
            return {e.get("name"): e for e in yapi(r).get("elements", [])}, r

        # --- observe/batch token ekonomisi: istemciye yalnız metin
        au = sm.sifirla()
        og, r = await gozle("Belge — KWrite")
        cekirdek = s.observe(window="KWrite", desktop="foreground")
        tam = len(json.dumps(cekirdek.structured_content, ensure_ascii=False))
        OLCUM["sahte_observe"] = (len(metin(r)), tam, len(og))
        kontrol("observe istemciye: structuredContent YOK, metinde ref + @kutu (çekirdekte yapılandırılmış sözlük durur)",
                r.structured_content is None and all(e.get("frame") for e in og.values()) and
                cekirdek.structured_content.get("elements"), metin(r)[:200])

        # --- uçbirim: type_text(ref) içindeki HER Enter ayrı onay
        au = sm.sifirla(UCB, UCB_SINIF)
        og, _r = await gozle(UCB)
        sm.YANIT["izin"] = True
        n0 = len(au.satirlar)
        r = await c.call_tool("type_text", {"ref": og["Ad"]["ref"], "text": "ls\npwd", "submit": True, **F})
        sat = au.satirlar[n0:]
        kontrol("uçbirim type_text(ref='ls\\npwd', submit): 2 Enter → 2 ayrı onay, ikisi de gitti",
                not r.is_error and len(enter_istekleri()) == 2 and sum(x == "key enter" for x in sat) == 2,
                f"{[x['eylem'] for x in sm.ISTEKLER]} {sat}")
        au = sm.sifirla(UCB, UCB_SINIF)
        og, _r = await gozle(UCB)
        sayac = {"n": 0}

        def ilki_evet():  # ilk Enter onaylanır, ikincisi reddedilir: ikinci Enter GİTMEZ (önceki onay taşınmaz)
            sayac["n"] += 1
            sm.YANIT["izin"] = sayac["n"] == 1
        sm.YANIT.update(izin=True, kanca=ilki_evet)
        n0 = len(au.satirlar)
        r = await c.call_tool("type_text", {"ref": og["Ad"]["ref"], "text": "ls\nrm -rf x\n", **F})
        sat = au.satirlar[n0:]
        kontrol("uçbirim type_text(ref): 1. Enter onaylı, 2. Enter reddedildi → [10]; onaylar yazıdan ÖNCE: hiç "
                "yazı/Enter gitmedi", r.is_error and "[10]" in metin(r) and len(enter_istekleri()) == 2 and
                not any(x == "key enter" or x.startswith("type ") for x in sat), f"{metin(r)[:200]} {sat}")

        # --- batch adımlarındaki Enter'lar: adım başına, Enter başına onay
        au = sm.sifirla(UCB, UCB_SINIF)
        og, _r = await gozle(UCB)
        sm.YANIT["izin"] = True
        n0 = len(au.satirlar)
        r = await c.call_tool("batch", {"steps": [
            {"tool": "type_text", "args": {"ref": og["Ad"]["ref"], "text": "echo a\n"}},
            {"tool": "press_key", "args": {"window": re.escape(UCB), "keys": "enter enter"}}], **F})
        sat = au.satirlar[n0:]
        kontrol("batch uçbirim: type_text '\\n' + press_key 'enter enter' → 3 Enter, 3 ayrı onay",
                not r.is_error and len(enter_istekleri()) == 3 and sum(x == "key enter" for x in sat) == 3,
                f"{metin(r)[:300]} {[x['eylem'] for x in sm.ISTEKLER]} {sat}")
        au = sm.sifirla(UCB, UCB_SINIF)
        og, _r = await gozle(UCB)
        n0 = len(au.satirlar)
        r = await c.call_tool("batch", {"steps": [
            {"tool": "type_text", "args": {"ref": og["Ad"]["ref"], "text": "x"}},
            {"tool": "press_key", "args": {"window": re.escape(UCB), "keys": "enter"}},
            {"tool": "type_text", "args": {"ref": og["Ad"]["ref"], "text": "y"}}], **F})
        st = yapi(r)
        sat = au.satirlar[n0:]
        kontrol("batch uçbirim (red): 2. adımın Enter'ı onay istedi, reddedildi → durdu, Enter yok, 3. adım gitmedi",
                r.is_error and st.get("failed_step") == 2 and st.get("not_sent") == [3] and len(enter_istekleri()) == 1
                and "key enter" not in sat and not any(x == "type y" for x in sat), f"{metin(r)[:300]} {sat}")

        # --- click(ref) yapıştırma ögesi: kullanıcının panosu → onay
        for via, ad_ in ((None, "Yapıştır"), ("action", "Yapıştır"), (None, "\U0001f4cb")):
            au = sm.sifirla()
            au.pano_oku = lambda: "kullanıcının gizli metni"
            sm.AGAC["Belge — KWrite"].append(sm.oge("push button", ad_, 600, 200, 80, 30, kimlik=(":1.9", "/a/9"),
                                                    yol=[3, 0]))
            og, _r = await gozle("Belge — KWrite")
            n0 = len(au.satirlar)
            sm.ISLEMLER.clear()
            r = await c.call_tool("click", {"ref": og[ad_]["ref"], **({"via": via} if via else {}), **F})
            kontrol(f"click(ref='{ad_}'{', via=action' if via else ''}): yapıştırma ögesi → pano onayı istendi, red → "
                    "[10], tık/eylem yok", r.is_error and "[10]" in metin(r) and
                    any("pano" in (x["eylem"] + x["ayrinti"]).lower() or "clipboard" in
                        (x["eylem"] + x["ayrinti"]).lower() for x in sm.ISTEKLER) and
                    "click left" not in au.satirlar[n0:] and not sm.eylemler(),
                    f"{metin(r)[:200]} {sm.ISTEKLER[:1]}")
        au = sm.sifirla()
        au.pano_oku = lambda: "kullanıcının gizli metni"
        sm.AGAC["Belge — KWrite"].append(sm.oge("push button", "Yapıştır", 600, 200, 80, 30, kimlik=(":1.9", "/a/9"),
                                                yol=[3, 0]))
        og, _r = await gozle("Belge — KWrite")
        sm.YANIT["izin"] = True
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"ref": og["Yapıştır"]["ref"], **F})
        kontrol("click(ref='Yapıştır') izinle: BİR onay, bir tık, approved_by_user",
                not r.is_error and len(sm.ISTEKLER) == 1 and au.satirlar[n0:].count("click left") == 1 and
                yapi(r).get("approved_by_user") is True, f"{metin(r)[:200]} {len(sm.ISTEKLER)}")

        # --- sistem istemi: ref/text/element tıklaması da ONAY SORAR (koordinatlı tık ve via=action gibi)
        POLKIT, POLKIT_SINIF = "Kimlik doğrulama gerekli", "polkit-kde-authentication-agent-1"
        for ad_, arg in (("ref", None), ("text", {"text": "Kaydet"}), ("element", {"element": "Kaydet"}),
                         ("ref via=action", "action"), ("x/y (shot_id)", "xy")):
            au = sm.sifirla(POLKIT, POLKIT_SINIF)
            og, _r = await gozle(POLKIT)
            if arg is None:
                a = {"ref": og["Kaydet"]["ref"]}
            elif arg == "action":
                a = {"ref": og["Kaydet"]["ref"], "via": "action"}
            elif arg == "xy":
                rs = await c.call_tool("screenshot", {"window": re.escape(POLKIT), **F})
                a = {"x": 160, "y": 120, "shot_id": (rs.structured_content or {}).get("shot_id")}
            else:
                a = {"window": re.escape(POLKIT), **arg}
            n0 = len(au.satirlar)
            sm.ISLEMLER.clear()
            r = await c.call_tool("click", {**a, **F})
            kontrol(f"sistem istemi click({ad_}): onay İSTENDİ, red → [10], tık/eylem yok",
                    r.is_error and "[10]" in metin(r) and len(sm.ISTEKLER) == 1 and
                    "click left" not in au.satirlar[n0:] and not sm.eylemler(),
                    f"{metin(r)[:200]} {len(sm.ISTEKLER)} {au.satirlar[n0:]}")
        for ad_, arg in (("ref", None), ("text", {"text": "Kaydet"}), ("element", {"element": "Kaydet"})):
            au = sm.sifirla(POLKIT, POLKIT_SINIF)
            og, _r = await gozle(POLKIT)
            sm.YANIT["izin"] = True
            a = {"ref": og["Kaydet"]["ref"]} if arg is None else {"window": re.escape(POLKIT), **arg}
            n0 = len(au.satirlar)
            r = await c.call_tool("click", {**a, **F})
            kontrol(f"sistem istemi click({ad_}) izinle: BİR onay, bir tık", not r.is_error and len(sm.ISTEKLER) == 1
                    and au.satirlar[n0:].count("click left") == 1, f"{metin(r)[:200]} {len(sm.ISTEKLER)}")

    # --- observe çerçeve seçimi: yalnız pencere süreci + aynı programlı torun (gerçek erisim._cerceve_bul)
    class Cerceve:
        def __init__(self, ad, ogeler):
            self.ad, self.ogeler = ad, ogeler

        def get_name(self):
            return self.ad

    class Uygulama:
        def __init__(self, pid, ad, cerceveler):
            self.pid, self.ad, self.c = pid, ad, cerceveler

        def get_process_id(self):
            return self.pid

        def get_name(self):
            return self.ad

        def get_child_count(self):
            return len(self.c)

        def get_child_at_index(self, i):
            return self.c[i]

    class Masa:
        def __init__(self):
            self.uygulamalar = []

        def get_child_count(self):
            return len(self.uygulamalar)

        def get_child_at_index(self, i):
            return self.uygulamalar[i]

    masa = Masa()
    SahteAtspi = type("SahteAtspi", (), {"get_desktop": staticmethod(lambda i: masa)})
    ATA, PEN, TORUN, BASKA_TORUN = 7101, 7102, 7103, 7104
    zincir = {PEN: [(PEN, "kwrite"), (ATA, "plasmashell")], TORUN: [(TORUN, "kwrite"), (PEN, "kwrite"), (ATA, "x")],
              BASKA_TORUN: [(BASKA_TORUN, "evil"), (PEN, "kwrite"), (ATA, "x")], ATA: [(ATA, "plasmashell")]}
    exe = {PEN: "/usr/bin/kwrite", TORUN: "/usr/bin/kwrite", BASKA_TORUN: "/usr/bin/evil", ATA: "/usr/bin/plasmashell"}
    eski = (erisim._atspi_calistir, erisim._atspi, erisim._tara, erisim._exe, kendi.atalar)
    erisim._atspi_calistir = erisim._atspi_is
    erisim._atspi = lambda adres: SahteAtspi
    erisim._tara = lambda Atspi, cerceve, *a, **k: {"ogeler": copy.deepcopy(cerceve.ogeler), "sure": 0.0}
    erisim._exe = lambda pid: exe.get(int(pid))
    kendi.atalar = lambda pid=None, proc=None: zincir.get(int(pid), [(int(pid), "?")]) if pid else [(0, "")]
    try:
        au = sm.sifirla()
        au.pid_[sm.PENCERE] = str(PEN)
        ata_ogesi = [sm.oge("push button", "ATA DÜĞMESİ", 10, 10, kimlik=(":1.1", "/ata/1"))]
        masa.uygulamalar = [Uygulama(ATA, "plasmashell", [Cerceve("Belge — KWrite", ata_ogesi)])]
        async with Client(s.mcp) as c:
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            st = yapi(r)
            kontrol("observe çerçevesi: ATA uygulamanın aynı başlıklı çerçevesi SEÇİLMEZ (ağaç yok → OCR)",
                    not r.is_error and not any(e.get("name") == "ATA DÜĞMESİ" for e in st.get("elements", [])) and
                    "tree" not in st.get("sources", []), metin(r)[:300])
            r = await c.call_tool("click", {"window": "KWrite", "element": "ATA DÜĞMESİ", **F})
            kontrol("click(element) ata uygulamanın ögesine gitmez", r.is_error, metin(r)[:200])
            masa.uygulamalar.append(Uygulama(BASKA_TORUN, "evil", [Cerceve("Belge — KWrite", [
                sm.oge("push button", "BAŞKA PROGRAM", 10, 10, kimlik=(":1.2", "/b/1"))])]))
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            kontrol("observe çerçevesi: BAŞKA programlı torun seçilmez",
                    not any(e.get("name") == "BAŞKA PROGRAM" for e in yapi(r).get("elements", [])), metin(r)[:300])
            masa.uygulamalar.append(Uygulama(TORUN, "kwrite", [Cerceve("Belge — KWrite", [
                sm.oge("push button", "TORUN DÜĞMESİ", 10, 10, kimlik=(":1.3", "/t/1"))])]))
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            adlar = [e.get("name") for e in yapi(r).get("elements", [])]
            kontrol("observe çerçevesi: aynı programlı TORUN seçilir (çok süreçli uygulama)", "TORUN DÜĞMESİ" in adlar
                    and "ATA DÜĞMESİ" not in adlar, metin(r)[:300])
            masa.uygulamalar.append(Uygulama(PEN, "kwrite", [Cerceve("Belge — KWrite", [
                sm.oge("push button", "KENDİ DÜĞMESİ", 10, 10, kimlik=(":1.4", "/k/1"))])]))
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            adlar = [e.get("name") for e in yapi(r).get("elements", [])]
            kontrol("observe çerçevesi: tam PID eşleşmesi önce", adlar[:1] == ["KENDİ DÜĞMESİ"], metin(r)[:300])
    finally:
        erisim._atspi_calistir, erisim._atspi, erisim._tara, erisim._exe, kendi.atalar = eski
        sm.kur()


def main():
    t0 = time.monotonic()
    birim_testleri()
    asyncio.run(liste_testleri())
    if sanal_mumkun():
        asyncio.run(sanal_testleri())
    else:
        print("ATLANDI (C): Xvfb / PyQt6 / at-spi2-core yok")
    if web_mumkun():
        asyncio.run(web_testleri())
    else:
        print("ATLANDI (C2): firefox / Xvfb / jeepney yok")
    asyncio.run(kapi_testleri())
    asyncio.run(tur5_kapi_testleri())
    baslik_norm_testleri()
    asyncio.run(duzeltme_a_testleri())
    print("\n# ölçümler:")
    print(f"  tools/list: {OLCUM.get('tools_list')} karakter (~{(OLCUM.get('tools_list') or 0) // 4} token); "
          f"talimat {OLCUM.get('talimat')} karakter")
    if "sahte_observe" in OLCUM:
        m, j, n = OLCUM["sahte_observe"]
        print(f"  observe (sahte, {n} öge): istemciye giden metin {m} karakter; çekirdeğin yapılandırılmış sözlüğü "
              f"(artık GÖNDERİLMEZ) {j} karakter (x{j / max(m, 1):.1f})")
    for ad in ("sanal_tam", "sanal_interactive", "sanal_query", "web_buyuk", "web_buyuk_40", "web_buyuk_query",
               "web_read_text_300"):
        if ad in OLCUM:
            m, j, n = OLCUM[ad][:3]
            print(f"  observe {ad}: {n} öge, metin {m} karakter (~{m // 4} token), metinden ayrıştırılan JSON {j} "
                  "karakter" + (f", {OLCUM[ad][3]} sn" if len(OLCUM[ad]) > 3 else ""))
    print(f"\n{gecen}/{toplam} gözlem testi geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if gecen == toplam else 1)


if __name__ == "__main__":
    main()
