"""MCP sunucusu testleri. Kullanıcının GERÇEK ekranına hiçbir girdi gitmez:

A) Ön plan yolu SÜREÇ İÇİNDE, sahte bir ArkaUc ile (arka_uc._ORNEKLER["kde"] = SahteArkaUc): gerçek kde arka ucu
   hiç kurulmaz. Ekran görüntüsü ölçeği, metne tıklama, Türkçe yazı, tuş, basılı tut, DUR (13), insan önceliği (12),
   deskhand-bg kipi (foreground yasak), auto kararı (on/sonra).
B) Uçtan uca STDIO: python-mcp istemcisi sunucuyu alt süreç olarak başlatır (tests/yardimci/mcp_test_sunucu.py:
   sahte meşgul/onay; bildirim yok) → araç listesi/şemalar → GÖRÜNMEZ masaüstünde manage_desktop start → open_app
   (test penceresi) → read_text → click(text) → koordinatlı click + bayat shot_id reddi → type_text (Türkçe) →
   press_key → screenshot (≤1280, shot_id) → DUR (13) → hassas "Satın al" (panel kapalı / modül yok / red / izin)
   → yasak pencere maskesi → SIGTERM'de basılı tuş bırakma (<500 ms) → manage_desktop stop.

Çalıştır:  python3 tests/test_mcp.py      (DESKHAND_TEST_SAKLA=1: geçici klasör silinmesin)"""
import asyncio
import atexit
import base64
import io
import json
import os
import re
import signal
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)
from PIL import Image, ImageDraw

from deskhand import arka_uc, guvenlik, hata, masaustu, yollar
from deskhand.arka_uc import ArkaUc
from deskhand.hata import Dur

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
GECICI = _yalitim.GECICI
TEST_PENCERE = os.path.join(KOK, "tests", "yardimci", "test_pencere.py")
SUNUCU = os.path.join(KOK, "tests", "yardimci", "mcp_test_sunucu.py")
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


def yapi(r):
    return r.structured_content or {}


# ================================================================ A) ön plan: sahte arka uç (süreç içi)

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

    def gonder(self, k, desen, *satirlar):
        hata.dur_denetle()
        if self.denetle:
            self.denetle(k, desen)
        self.etk_denetle()
        for s in satirlar:
            self._satir(s)

    def ham(self, s):
        hata.dur_denetle()
        self._satir(s)

    def zorla(self, s):
        self._satir(s)

    def izle(self, k, desen):
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


class SahteArkaUc(ArkaUc):
    """Ön plan (kde) yerine: 1920x1080 ekran, tek pencere, yazılı düğmeler. Hiçbir gerçek araç çağrılmaz."""
    ad = "kde"

    def __init__(self):
        self.pen = {"{sahte-1}": ["Sahte Pencere", "sahte", (100, 100, 800, 600)]}
        self.aktif_ = "{sahte-1}"
        self.imlec = (5, 5)
        self.satirlar, self.kapanan, self.insan, self.baslatilan = [], 0, False, []

    def pencere_coz(self, arg):
        if arg in self.pen:
            return arg
        if arg.lower() in ("ekran", "masaustu"):
            return arka_uc.EKRAN
        uy = [k for k, (b, _, _) in self.pen.items() if re.search(arg, b, re.I)]
        if not uy:
            raise Dur(8, f"'{arg}' yok")
        if len(uy) > 1:
            raise Dur(5, "birden çok")
        return uy[0]

    def pencereler(self, desen=None):
        return [(k, b, g) for k, (b, _, g) in self.pen.items() if not desen or re.search(desen, b, re.I)]

    def geometri(self, k):
        if k == arka_uc.EKRAN:
            return (0, 0, 1920, 1080)
        if k not in self.pen:
            raise Dur(8, "pencere yok")
        return self.pen[k][2]

    def baslik(self, k):
        return self.pen.get(k, [""])[0] if k != arka_uc.EKRAN else "EKRAN"

    def sinif(self, k):
        return self.pen.get(k, ["", ""])[1]

    def aktif(self):
        return self.aktif_

    def one_getir(self, k):
        if k != arka_uc.EKRAN:
            self.aktif_ = k

    def kapat(self, k):
        self.pen.pop(k, None)

    def fare(self):
        x, y = self.imlec
        alt = next((k for k, (_, _, (X, Y, W, H)) in self.pen.items() if X <= x < X + W and Y <= y < Y + H), "")
        return x, y, alt

    def ekran_alani(self):
        return (0, 0, 1920, 1080)

    def goruntu(self):
        from deskhand.gorsel import font
        im = Image.new("RGB", (1920, 1080), (60, 60, 60))
        d = ImageDraw.Draw(im)
        X, Y, W, H = self.pen["{sahte-1}"][2]
        d.rectangle([X, Y, X + W - 1, Y + H - 1], fill=(245, 245, 245))
        f = font(30)
        d.text((X + 80, Y + 100), "Kaydet", fill=(0, 0, 0), font=f)
        d.text((X + 400, Y + 100), "Vazgeç", fill=(0, 0, 0), font=f)
        d.text((X + 80, Y + 300), "Not alanı", fill=(0, 0, 0), font=f)
        return im

    def girdi(self, etiket="", gizli=False, etk=None, denetle=None):
        return SahteGirdi(self, etiket, gizli, etk, denetle)

    def insan_var_mi(self):
        return self.insan

    def baslat(self, argv, env=None, cikti=None):
        self.baslatilan.append((list(argv), dict(env or {})))
        self.pen["{sahte-2}"] = ["Yeni Uygulama", "yeni", (300, 200, 400, 300)]
        return SahtePopen()


async def on_plan_testleri():
    from mcp import Client
    from deskhand import mcp_sunucu as s
    au = SahteArkaUc()
    arka_uc._ORNEKLER["kde"] = au
    karar = {"v": "on"}
    import deskhand.mesgul as mesgul
    mesgul.karar = lambda ozet: karar["v"]
    mesgul.durum = lambda esik=None: {"mesgul": False, "nedenler": [], "ayrinti": {}}
    os.environ.pop("DESKHAND_MCP_SADECE_ARKA", None)
    async with Client(s.mcp) as c:
        r = await c.call_tool("screenshot", {"window": "Sahte", "desktop": "foreground"})
        im = Image.open(io.BytesIO(base64.b64decode(r.content[0].data)))
        m = yapi(r)
        kontrol("ön: pencere görüntüsü 800x600 ölçek 1, shot_id", not r.is_error and im.size == (800, 600) and
                m.get("scale") == 1.0 and m.get("shot_id") and m.get("desktop") == "foreground", metin(r)[:300])
        r = await c.call_tool("screenshot", {"desktop": "foreground"})
        im = Image.open(io.BytesIO(base64.b64decode(r.content[0].data)))
        kontrol("ön: tüm ekran 1920x1080 → 1280x720 (uzun kenar 1280)", im.size == (1280, 720) and
                abs(yapi(r)["scale"] - 2 / 3) < 1e-3, str(im.size))
        tam_shot = yapi(r)["shot_id"]

        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"window": "Sahte", "text": "Kaydet", "desktop": "foreground"})
        sat = au.satirlar[n0:]
        kontrol("ön: click(text) → mouseto + click left", not r.is_error and any(x.startswith("mouseto") for x in sat)
                and "click left" in sat, metin(r)[:400])
        X, Y, _, _ = au.pen["{sahte-1}"][2]
        kontrol("ön: tıklama noktası 'Kaydet' üstünde", X + 70 <= au.imlec[0] <= X + 200 and Y + 95 <= au.imlec[1] <= Y + 140,
                str(au.imlec))

        # tüm ekran görüntüsü koordinatı (ölçek 2/3) → ekran pikseli
        n0 = len(au.satirlar)
        hx, hy = (X + 450) * 2 / 3, (Y + 300) * 2 / 3
        r = await c.call_tool("click", {"x": hx, "y": hy, "shot_id": tam_shot, "desktop": "foreground"})
        kontrol("ön: koordinatlı click (tüm ekran, ölçek geri çevrilir)", not r.is_error and
                abs(au.imlec[0] - (X + 450)) <= 2 and abs(au.imlec[1] - (Y + 300)) <= 2, f"{au.imlec} {metin(r)[:300]}")

        n0 = len(au.satirlar)
        r = await c.call_tool("type_text", {"window": "Sahte", "text": "Çağrı ığüşöç", "desktop": "foreground"})
        yazilan = "".join(x[5:] if x.startswith("type ") else " " if x == "key space" else "" for x in au.satirlar[n0:])
        kontrol("ön: type_text Türkçe harf harf", not r.is_error and yazilan == "Çağrı ığüşöç", repr(yazilan))

        n0 = len(au.satirlar)
        r = await c.call_tool("press_key", {"window": "Sahte", "keys": "ctrl+s", "desktop": "foreground"})
        kontrol("ön: press_key ctrl+s", not r.is_error and au.satirlar[n0:] == ["key ctrl+s"], str(au.satirlar[n0:]))
        n0 = len(au.satirlar)
        r = await c.call_tool("press_key", {"window": "Sahte", "keys": "w", "hold_s": 0.3, "desktop": "foreground"})
        sat = au.satirlar[n0:]
        kontrol("ön: basılı tut → keydown + keyup", not r.is_error and sat[:1] == ["keydown w"] and sat[-1:] == ["keyup w"],
                str(sat))

        guvenlik.dur_ac("cli")
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"window": "Sahte", "text": "Kaydet", "desktop": "foreground"})
        kontrol("ön: DUR → [13], hiçbir satır gönderilmedi", r.is_error and "[13]" in metin(r) and
                len(au.satirlar) == n0, metin(r)[:300])
        guvenlik.dur_kapat("cli")

        au.insan = True
        r = await c.call_tool("press_key", {"window": "Sahte", "keys": "enter", "desktop": "foreground"})
        kontrol("ön: insan önceliği → [12] 'kullanıcı bilgisayarı kullanıyor'", r.is_error and "[12]" in metin(r) and
                "kullanıcı bilgisayarı kullanıyor" in metin(r), metin(r)[:300])
        au.insan = False

        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"window": "Sahte", "text": "Kaydet", "x": 3, "desktop": "foreground"})
        kontrol("ön: iki hedef birden → hata, girdi yok", r.is_error and len(au.satirlar) == n0)

        r = await c.call_tool("open_app", {"app": sys.executable, "args": ["-c", "pass"], "desktop": "foreground"})
        kontrol("ön: open_app yeni pencereyi bekler", not r.is_error and yapi(r).get("status") == "opened" and
                yapi(r)["window"]["id"] == "{sahte-2}" and au.baslatilan, metin(r)[:300])
        au.pen.pop("{sahte-2}", None)

        r = await c.call_tool("click", {"window": "Sahte", "text": "Kaydet", "desktop": "auto"})
        kontrol("ön: auto + karar 'on' → foreground", not r.is_error and yapi(r).get("desktop") == "foreground",
                metin(r)[:300])
        s._SECIM.clear()
        karar["v"] = "sonra"
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"window": "Sahte", "text": "Kaydet", "desktop": "auto"})
        kontrol("ön: auto + karar 'sonra' → araç çalışmaz, 'sonra dedi'", r.is_error and "sonra dedi" in metin(r) and
                len(au.satirlar) == n0, metin(r)[:300])
        s._SECIM.clear()

        os.environ["DESKHAND_MCP_SADECE_ARKA"] = "1"
        r = await c.call_tool("click", {"window": "Sahte", "text": "Kaydet", "desktop": "foreground"})
        kontrol("ön: deskhand-bg kipinde foreground reddedilir", r.is_error and "yalnız görünmez" in metin(r), metin(r)[:200])
        r = await c.call_tool("get_status", {})
        kontrol("ön: deskhand-bg get_status only_background", yapi(r).get("only_background") is True)
        os.environ.pop("DESKHAND_MCP_SADECE_ARKA", None)
    del arka_uc._ORNEKLER["kde"]
    kontrol("ön: hiçbir girdi nesnesi açık kalmadı", au.kapanan > 0)


# ================================================================ B) uçtan uca stdio, görünmez masaüstü

LOG = os.path.join(GECICI, "pencere.log")
LOG2 = os.path.join(GECICI, "gizli.log")


def log_satirlari(yol=LOG):
    try:
        with open(yol) as f:
            return [l.rstrip("\n") for l in f]
    except OSError:
        return []


def log_bekle(desen, sure=5.0, bas=0, yol=LOG):
    rx = re.compile(desen)
    bitis = time.monotonic() + sure
    while True:
        for l in log_satirlari(yol)[bas:]:
            if rx.search(l):
                return l
        if time.monotonic() > bitis:
            return None
        time.sleep(0.05)


def sahte(ad, deger):
    yol = os.path.join(yollar.runtime_dir(), ad)
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    if deger is None:
        try:
            os.remove(yol)
        except FileNotFoundError:
            pass
    else:
        with open(yol, "w") as f:
            f.write(deger)


def sunucu_pidleri():
    """Bu testin başlattığı sunucu süreçleri (/proc; ebeveyn = bu süreç)."""
    sonuc = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            with open(f"/proc/{p}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            with open(f"/proc/{p}/cmdline", "rb") as f:
                kom = f.read().split(b"\0")
        except (OSError, ValueError, IndexError):
            continue
        if ppid == os.getpid() and any(SUNUCU.encode() == k for k in kom):
            sonuc.append(int(p))
    return sonuc


def x_tasi(kimlik, dx):
    """Testin kendisi: pencereyi görünmez masaüstünde taşı (girdi değil; bayat shot_id sınaması)."""
    from Xlib import display
    d = masaustu.durum()
    dp = display.Display(masaustu.guvenli_ekran(d["ekran"]))
    try:
        w = dp.create_resource_object("window", int(kimlik.split(":", 1)[1], 16))
        g = w.get_geometry()
        t = dp.screen().root.translate_coords(w, 0, 0)
        w.configure(x=t.x + dx, y=t.y)
        dp.sync()
    finally:
        dp.close()
    _ = g


async def stdio_testleri():
    from mcp import Client, StdioServerParameters
    env = dict(os.environ)
    env.update({"LOG": LOG, "BASLIK": "deskhand-mcp ANA", "HAZIR_MS": "300"})
    with open(yollar.yasak_dosya() if os.path.exists(os.path.dirname(yollar.yasak_dosya())) else
              (os.makedirs(os.path.dirname(yollar.yasak_dosya()), exist_ok=True) or yollar.yasak_dosya()), "w") as f:
        f.write(guvenlik.VARSAYILAN_YASAK + "gizli-pencere\n")
    param = StdioServerParameters(command=sys.executable, args=[SUNUCU], env=env, cwd=GECICI)
    async with Client(param) as c:
        r = await c.list_tools()
        adlar = sorted(t.name for t in r.tools)
        beklenen = sorted(["get_status", "choose_desktop", "manage_desktop", "screenshot", "read_text", "find", "click",
                           "type_text", "press_key", "scroll", "open_app", "run_flow"])
        kontrol("stdio: 12 araç, adlar doğru", adlar == beklenen, str(adlar))
        masaustulu = [t.name for t in r.tools if "desktop" in (t.input_schema.get("properties") or {})]
        kontrol("stdio: masaüstüne dokunan 10 araçta desktop parametresi (enum foreground/background/auto)",
                len(masaustulu) == 10 and all(
                    set(t.input_schema["properties"]["desktop"].get("enum", [])) == {"foreground", "background", "auto"}
                    for t in r.tools if t.name in masaustulu), str(masaustulu))
        cl = next(t for t in r.tools if t.name == "click")
        kontrol("stdio: onay parametresi YOK (--onayli MCP yüzeyinde değil)",
                not any("onay" in p or "approv" in p for t in r.tools for p in (t.input_schema.get("properties") or {})))
        kontrol("stdio: annotations (screenshot salt-okunur, click yıkıcı)",
                next(t for t in r.tools if t.name == "screenshot").annotations.read_only_hint is True and
                cl.annotations.read_only_hint is False and cl.annotations.destructive_hint is True)
        talimat = (c.initialize_result.instructions if getattr(c, "initialize_result", None) else None) or ""
        if talimat:
            kontrol("stdio: talimat 1000-2000 karakter", 1000 <= len(talimat) <= 2000, str(len(talimat)))

        r = await c.call_tool("get_status", {"windows": True, "desktop": "background"})
        st = yapi(r)
        kontrol("stdio: get_status (DUR kapalı, kullanıcı meşgul, arka kapalı)", not r.is_error and
                st.get("stop_switch") is False and st.get("user", {}).get("busy") is True and
                st["background"]["running"] is False, metin(r)[:300])

        r = await c.call_tool("read_text", {"window": "deskhand", "desktop": "background"})
        kontrol("stdio: masaüstü kapalıyken → [14]", r.is_error and "[14]" in metin(r), metin(r)[:200])

        r = await c.call_tool("manage_desktop", {"action": "start"})
        kontrol("stdio: manage_desktop start", not r.is_error and yapi(r).get("running") is True, metin(r)[:300])

        r = await c.call_tool("open_app", {"app": sys.executable, "args": [TEST_PENCERE], "title": "deskhand-mcp ANA",
                                           "desktop": "background", "wait_s": 20})
        w = (yapi(r).get("window") or {}).get("id", "")
        kontrol("stdio: open_app → arka: kimlikli pencere", not r.is_error and yapi(r).get("status") == "opened" and
                w.startswith("arka:"), metin(r)[:400])
        kontrol("stdio: oturum köprüsü yokken uyarı notu", any("oturum" in n for n in yapi(r).get("notes", [])),
                str(yapi(r).get("notes")))
        # oturum köprüsü yokken mutlak yolsuz ad başlatılmaz (var olmayan bir ad: hiçbir gerçek uygulama açılmaz)
        r2 = await c.call_tool("open_app", {"app": "olmayan-uygulama-xyz", "desktop": "background"})
        kontrol("stdio: oturum köprüsü yok + mutlak yolsuz ad → reddedildi", r2.is_error and "mutlak yol" in metin(r2),
                metin(r2)[:200])

        r = await c.call_tool("read_text", {"window": w, "query": "Hazır", "wait_s": 8, "desktop": "background"})
        kontrol("stdio: read_text query+wait ('Hazır')", not r.is_error and yapi(r).get("items"), metin(r)[:300])
        r = await c.call_tool("read_text", {"window": w, "desktop": "background"})
        ogeler = yapi(r).get("items", [])
        metinler = " | ".join(o["text"] for o in ogeler)
        kontrol("stdio: read_text tüm metin (Kaydet, E-posta, OYUN ALANI)", all(x in metinler for x in
                ("Kaydet", "E-posta", "OYUN")), metinler[:300])
        okuma_shot = yapi(r).get("shot_id")

        n0 = len(log_satirlari())
        r = await c.call_tool("click", {"window": w, "text": "Kaydet", "desktop": "background"})
        kontrol("stdio: click(text='Kaydet') → test log 'tık: Kaydet'", not r.is_error and
                log_bekle(r"^tık: Kaydet$", 3, n0), metin(r)[:300])
        kontrol("stdio: click sonrası doğrulama (after.title)", "title" in (yapi(r).get("after") or {}))

        ep = next((o for o in ogeler if o["text"].startswith("E-posta")), None)
        ip = next((o for o in ogeler if o["text"] == "İptal"), None)  # 2. sütun (alan) ortası
        n0 = len(log_satirlari())
        if ep and ip:
            r = await c.call_tool("click", {"x": ip["center"][0], "y": ep["center"][1],
                                            "shot_id": okuma_shot, "desktop": "background"})
            kontrol("stdio: koordinatlı click (read_text shot_id, pencere pikseli)", not r.is_error, metin(r)[:300])
            r = await c.call_tool("type_text", {"window": w, "text": "Çağrı şöyle: ığüşöç İĞÜŞÖÇ", "desktop": "background"})
            kontrol("stdio: type_text Türkçe → eposta=…", not r.is_error and
                    log_bekle(r"^eposta=Çağrı şöyle: ığüşöç İĞÜŞÖÇ$", 4, n0), metin(r)[:300] + str(log_satirlari()[-3:]))
        else:
            kontrol("stdio: E-posta etiketi bulundu", False, metinler[:300])

        r = await c.call_tool("click", {"window": w, "text": "OYUN ALANI", "desktop": "background"})
        n0 = len(log_satirlari())
        r = await c.call_tool("press_key", {"window": w, "keys": "w", "desktop": "background"})
        kontrol("stdio: press_key 'w' → tus_bas w", not r.is_error and log_bekle(r"^tus_bas w ", 3, n0), metin(r)[:300])

        r = await c.call_tool("screenshot", {"window": w, "desktop": "background"})
        img = next((x for x in r.content if getattr(x, "type", "") == "image"), None)
        im = Image.open(io.BytesIO(base64.b64decode(img.data))) if img else None
        m = yapi(r)
        kontrol("stdio: screenshot pencere (≤1280, shot_id, PNG)", im is not None and max(im.size) <= 1280 and
                m.get("shot_id") and img.mime_type == "image/png", metin(r)[:300])
        pen_shot = m.get("shot_id")
        r = await c.call_tool("screenshot", {"desktop": "background"})
        img = next((x for x in r.content if getattr(x, "type", "") == "image"), None)
        im = Image.open(io.BytesIO(base64.b64decode(img.data)))
        tm = yapi(r)
        kontrol("stdio: screenshot tüm masaüstü 1920x1080 → 1280x720", im.size == (1280, 720) and
                abs(tm["scale"] - 2 / 3) < 1e-3, str(im.size))

        # tüm masaüstü görüntüsünde 'Kaydet'e koordinatla tıkla (ölçek geri çevrilir)
        kay = next((o for o in ogeler if o["text"] == "Kaydet"), None)
        st = yapi(await c.call_tool("get_status", {"windows": True, "desktop": "background"}))
        geo = next(p["geometry"] for p in st["background"]["windows"] if p["id"] == w)
        n0 = len(log_satirlari())
        if kay:
            sx, sy = (geo[0] + kay["center"][0]) * tm["scale"], (geo[1] + kay["center"][1]) * tm["scale"]
            r = await c.call_tool("click", {"x": sx, "y": sy, "shot_id": tm["shot_id"], "desktop": "background"})
            kontrol("stdio: tüm masaüstü shot_id ile koordinatlı click → 'tık: Kaydet'", not r.is_error and
                    log_bekle(r"^tık: Kaydet$", 3, n0), metin(r)[:300])

        # bayat shot_id: pencere taşındı → reddedilir
        x_tasi(w, 37)
        time.sleep(0.4)
        n0 = len(log_satirlari())
        r = await c.call_tool("click", {"window": w, "x": 50, "y": 50, "shot_id": pen_shot, "desktop": "background"})
        kontrol("stdio: bayat shot_id (pencere taşındı) → reddedildi", r.is_error and "bayat" in metin(r) and
                not log_bekle(r"^(tık|fare_bas)", 0.5, n0), metin(r)[:300])
        r = await c.call_tool("click", {"window": w, "x": 50, "y": 50, "shot_id": "yok123", "desktop": "background"})
        kontrol("stdio: bilinmeyen shot_id → reddedildi", r.is_error and "shot_id" in metin(r))

        # DUR
        guvenlik.dur_ac("cli")
        n0 = len(log_satirlari())
        r = await c.call_tool("click", {"window": w, "text": "Kaydet", "desktop": "background"})
        r2 = await c.call_tool("type_text", {"window": w, "text": "x", "desktop": "background"})
        kontrol("stdio: DUR → click ve type_text [13] 'kullanıcı DUR dedi'", r.is_error and r2.is_error and
                "[13]" in metin(r) and "kullanıcı DUR dedi" in metin(r2), metin(r)[:200])
        kontrol("stdio: DUR → hiçbir olay yok", not log_bekle(r".", 0.5, n0))
        guvenlik.dur_kapat("cli")

        # hassas düğme: onay yalnız insandan
        satin0 = sum(l == "tık: Satın al" for l in log_satirlari())
        sahte("sahte-onay", None)
        r = await c.call_tool("click", {"window": w, "text": "Satın al", "desktop": "background"})
        kontrol("stdio: 'Satın al' + panel kapalı → 'kullanıcı onayı alınamadı' (panel)", r.is_error and
                "kullanıcı onayı alınamadı" in metin(r) and "panel" in metin(r), metin(r)[:300])
        sahte("sahte-onay", "modul-yok")
        r = await c.call_tool("click", {"window": w, "text": "Satın al", "desktop": "background"})
        kontrol("stdio: 'Satın al' + onay modülü yok → red", r.is_error and "onay modülü yok" in metin(r), metin(r)[:300])
        sahte("sahte-onay", "red")
        r = await c.call_tool("click", {"window": w, "text": "Satın al", "desktop": "background"})
        kontrol("stdio: 'Satın al' + kullanıcı reddetti → red", r.is_error and "alınamadı" in metin(r))
        time.sleep(0.3)
        kontrol("stdio: üç redde de 'Satın al' tıklanmadı", sum(l == "tık: Satın al" for l in log_satirlari()) == satin0)
        sahte("sahte-onay", "izin")
        r = await c.call_tool("click", {"window": w, "text": "Satın al", "desktop": "background"})
        time.sleep(0.4)
        kontrol("stdio: 'Satın al' + insan izni → BİR kez tıklandı", not r.is_error and
                yapi(r).get("approved_by_user") is True and
                sum(l == "tık: Satın al" for l in log_satirlari()) == satin0 + 1, metin(r)[:300])
        sahte("sahte-onay", None)
        with open(os.path.join(yollar.runtime_dir(), "onay-istekleri.log")) as f:
            istekler = f.read().splitlines()
        kontrol("stdio: onay isteği görünmez masaüstünü bildirir", bool(istekler) and
                re.search(r"\| (arka|sanal) \|", istekler[0]) if istekler else False,
                str(istekler[:1]))

        # auto → sahte karar 'arka'
        r = await c.call_tool("read_text", {"window": w, "query": "Kaydet", "desktop": "auto"})
        kontrol("stdio: desktop=auto → (karar arka) background", not r.is_error and yapi(r).get("desktop") == "background",
                metin(r)[:200])

        # yasak pencere: maske + OCR'dan çıkarma + girdi yok
        r = await c.call_tool("open_app", {"app": "/bin/sh", "args": ["-c", f'LOG={LOG2} BASLIK="gizli-$(echo pencere)" '
                                                                     f'HAZIR_MS=100 exec {sys.executable} {TEST_PENCERE}'],
                                           "title": "gizli", "desktop": "background", "wait_s": 20})
        gw = (yapi(r).get("window") or {})
        kontrol("stdio: yasak pencere açıldı, başlığı gizli", not r.is_error and gw.get("forbidden") is True and
                gw.get("title") == "(yasak pencere)", metin(r)[:300])
        time.sleep(0.8)
        st = yapi(await c.call_tool("get_status", {"windows": True, "desktop": "background"}))
        ggeo = next((p["geometry"] for p in st["background"]["windows"] if p["id"] == gw.get("id")), None)
        r = await c.call_tool("screenshot", {"desktop": "background"})
        img = next((x for x in r.content if getattr(x, "type", "") == "image"), None)
        im = Image.open(io.BytesIO(base64.b64decode(img.data))).convert("RGB")
        m = yapi(r)
        siyah = False
        if m.get("redacted") and ggeo:
            s_ = m["scale"]
            kut = im.crop((round(ggeo[0] * s_) + 2, round(ggeo[1] * s_) + 2, round((ggeo[0] + ggeo[2]) * s_) - 2,
                           round((ggeo[1] + ggeo[3]) * s_) - 2))
            uc = kut.getextrema()
            siyah = max(b[1] for b in uc) == 0
        kontrol("stdio: tüm masaüstü görüntüsünde yasak pencere siyah kutu", siyah,
                f"{m.get('redacted')} geo {ggeo} ölçek {m.get('scale')} uç {uc if m.get('redacted') and ggeo else None}")
        r = await c.call_tool("read_text", {"desktop": "background"})
        ic = [o for o in yapi(r).get("items", []) if ggeo and ggeo[0] <= o["center"][0] < ggeo[0] + ggeo[2] and
              ggeo[1] <= o["center"][1] < ggeo[1] + ggeo[3]]
        kontrol("stdio: OCR sonucunda yasak pencereden metin yok", not r.is_error and yapi(r).get("redacted", 0) >= 1 and
                not ic, str(ic[:3]))
        r = await c.call_tool("read_text", {"window": gw.get("id", "x"), "desktop": "background"})
        kontrol("stdio: yasak pencere doğrudan okunamaz → [10]", r.is_error and "[10]" in metin(r), metin(r)[:200])
        n2 = len(log_satirlari(LOG2))
        r = await c.call_tool("click", {"window": gw.get("id", "x"), "text": "Kaydet", "desktop": "background"})
        kontrol("stdio: yasak pencereye tıklama → [10], olay yok", r.is_error and "[10]" in metin(r) and
                not log_bekle(r"^tık", 0.5, n2, LOG2), metin(r)[:200])

        # kapanış: basılı tuş SIGTERM'de 500 ms içinde bırakılır (ikinci sunucu; aynı masaüstü)
        once_pid = set(sunucu_pidleri())
        async with Client(param) as c2:
            pid = next(iter(set(sunucu_pidleri()) - once_pid), None)
            await c2.call_tool("click", {"window": w, "text": "OYUN ALANI", "desktop": "background"})
            n0 = len(log_satirlari())
            gorev = asyncio.ensure_future(c2.call_tool("press_key", {"window": w, "keys": "d", "hold_s": 8,
                                                                     "desktop": "background"}))
            bas = None
            for _ in range(60):
                await asyncio.sleep(0.05)
                bas = next((l for l in log_satirlari()[n0:] if l.startswith("tus_bas d ")), None)
                if bas:
                    break
            await asyncio.sleep(0.3)
            t_kill = time.monotonic()
            if pid:
                os.kill(pid, signal.SIGTERM)
            birak = None
            for _ in range(40):
                await asyncio.sleep(0.05)
                birak = next((l for l in log_satirlari()[n0:] if l.startswith("tus_birak d ")), None)
                if birak:
                    break
            gecikme = float(birak.split()[-1]) - t_kill if birak else None
            kontrol("stdio: SIGTERM → basılı 'd' 500 ms içinde bırakıldı", bas and birak and gecikme is not None and
                    gecikme < 0.5, f"pid {pid} bas {bas} bırak {birak} gecikme {gecikme}")
            olu = False
            for _ in range(20):
                await asyncio.sleep(0.05)
                if pid and not os.path.exists(f"/proc/{pid}") or (pid and open(f"/proc/{pid}/stat").read().split()[2] == "Z"):
                    olu = True
                    break
            kontrol("stdio: sunucu süreci SIGTERM ile çıktı", olu)
            gorev.cancel()
            try:
                await gorev
            except BaseException:  # noqa: BLE001 - bağlantı koptu: beklenen
                pass

        r = await c.call_tool("manage_desktop", {"action": "stop"})
        kontrol("stdio: manage_desktop stop", not r.is_error and yapi(r).get("running") is False, metin(r)[:200])
        r = await c.call_tool("manage_desktop", {"action": "status"})
        kontrol("stdio: masaüstü kapalı", yapi(r).get("running") is False and masaustu.durum() is None)


def main():
    t0 = time.monotonic()
    asyncio.run(on_plan_testleri())
    try:
        asyncio.run(stdio_testleri())
    except BaseExceptionGroup as eg:  # noqa: F821
        kontrol(f"stdio: beklenmeyen hata {eg!r}", False)
        raise
    print(f"\n{gecen}/{toplam} geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if gecen == toplam else 1)


if __name__ == "__main__":
    main()
