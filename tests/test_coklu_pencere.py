"""Çok pencere doğruluğu (ABM-F2) testleri. Kullanıcının GERÇEK ekranına hiçbir girdi gitmez; gerçek ~/.config yazılmaz.

 A) Süreç içi sahte kde arka ucu + sahte AT-SPI (tests/yardimci/sahte_masaustu.py), MCP araçları süreç içi:
    - aynı başlıklı iki pencere: kimlikle yazı yalnız hedefe gider; desenle "belirsiz" [5] (S2 gerilemesi)
    - yazı ortasında başka pencere etkinleşir: durur, ileti DÜRÜST ("N/M karakter gönderildi", sent maybe_partial) (B1a)
    - gizli yazı: her harften önce + sonra etkin pencere yoklaması, uyuşmazlıkta HEMEN durur (B1b)
    - başlığa içerik önizlemesi yansıyan düzenleyici (KWrite "Başlıksız (d) *"): kimlik/ref ile uzun yazı tamamlanır;
      kilit = kimlik + pencere sınıfı (B2)
    - batch bir adımda durursa observe_after atlanır (B3)
    - hedef pencere yazı ortasında kapanır → [8] "hedef pencere kapandı" (B4)
 B) KWin gözcüsü (arka_uc/kwin.py KwinGirdi.izle) sahte kdotool/liste ile: kapanan hedef → 8, kardeş etkin → 3.

Çalıştır:  python3 tests/test_coklu_pencere.py"""
import asyncio
import atexit
import os
import re
import sys
import threading
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))

from deskhand import masaustu, mcp_sunucu as s  # noqa: E402

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
gecen = toplam = 0
F = {"desktop": "foreground"}
A, B = "{sahte-1}", "{sahte-2}"


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)
    return bool(kosul)


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


def yapi(r):
    import mcp_metin
    return mcp_metin.yapi(r)


def iki_pencere(sm, baslik="Belge — KWrite"):
    """A ve B: AYNI başlık, aynı sınıf; A etkin. Her girdi satırı (etkin pencere, satır) olarak kaydedilir."""
    au = sm.sifirla(baslik=baslik)
    au.pen[B] = [baslik, "kwrite", (950, 100, 800, 600)]
    au.kayit = []
    return au


def yazi_satiri(x):
    return x.startswith("type ") or x == "key space"


async def sahte_testler():
    from mcp import Client
    import sahte_masaustu as sm
    sm.kur()
    async with Client(s.mcp) as c:
        # ---- S2 gerilemesi: aynı başlık, kimlikle ayrılır
        au = iki_pencere(sm)
        au.kanca_satir = lambda x: au.kayit.append((au.aktif_, x))
        r = await c.call_tool("type_text", {"window": A, "text": "merhaba dunya", **F})
        yazi = [p for p, x in au.kayit if yazi_satiri(x)]
        kontrol("S2: aynı başlıklı B varken A kimliğiyle yazı → her harf A etkinken gitti, B hiç etkin olmadı",
                not r.is_error and len(yazi) == 13 and set(yazi) == {A}, f"{metin(r)[:200]} {set(yazi)} {len(yazi)}")
        au = iki_pencere(sm)
        r = await c.call_tool("type_text", {"window": "KWrite", "text": "x", **F})
        kontrol("S2: aynı başlıklı iki pencere + desen → [5] belirsiz, girdi yok",
                r.is_error and "[5]" in metin(r) and not any(yazi_satiri(x) for x in au.satirlar), metin(r)[:200])

        # ---- B1a: yazı ortasında başka pencere etkinleşir → dürüst ileti
        au = iki_pencere(sm)

        def odak_calinir(x, n=3):
            if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) >= n:
                au.aktif_ = B
        au.kanca_satir = odak_calinir
        r = await c.call_tool("type_text", {"window": A, "text": "abcdef ghijkl", **F})
        m = metin(r)
        kontrol("B1a: yazı ortasında odak kaçtı → durdu, sent maybe_partial",
                r.is_error and yapi(r).get("sent") == "maybe_partial", m[:300])
        kontrol("B1a: ileti 'girdi gönderilmedi' diye YANLIŞ GÜVENCE vermez: kaç karakter gittiği + son harf uyarısı",
                "6/13" in m and "yeni yere gitmiş olabilir" in m, m[:400])

        # ---- B1b: gizli yazı, harf başı çift yoklama
        au = iki_pencere(sm)
        au.kanca_satir = odak_calinir
        r = await c.call_tool("type_text", {"window": A, "text": "qzxjkw", "secret": True, **F})
        m = metin(r)
        n_type = sum(x.startswith("type ") for x in au.satirlar)
        kontrol("B1b: gizli yazıda odak kaçınca SONRAKİ harf gönderilmez (kelime sonunu beklemez)",
                r.is_error and n_type == 3, f"type satırı {n_type}; {m[:300]}")
        kontrol("B1b: gizli ileti harf içermez, kaç karakter gittiğini ve son harf uyarısını söyler",
                "3/6" in m and "yeni yere gitmiş olabilir" in m and not any(x in m for x in ("qz", "zx", "jk", "kw")), m[:400])

        # ---- B2: başlığa içerik önizlemesi yansıyan düzenleyici
        au = iki_pencere(sm, baslik="Başlıksız — KWrite")
        yazilan = []

        def onizleme(x):
            if x.startswith("type "):
                yazilan.append(x[5:])
                au.pen[A][0] = f"Başlıksız ({''.join(yazilan)[:12]}) * — KWrite"
        au.kanca_satir = onizleme
        uzun = "deneme yazisi tamamlanmali bitti"
        r = await c.call_tool("type_text", {"window": A, "text": uzun, **F})
        n = sum(yazi_satiri(x) for x in au.satirlar)
        kontrol("B2: kimlikle uzun yazı, başlık içerik önizlemesiyle değişse de TAMAMLANIR",
                not r.is_error and n == len(uzun), f"{n}/{len(uzun)} {metin(r)[:300]}")
        au = iki_pencere(sm, baslik="Başlıksız — KWrite")
        yazilan.clear()
        au.kanca_satir = onizleme
        r = await c.call_tool("observe", {"window": A, **F})
        mref = re.search(r"\[(\d+)\] text \"Ad\"", metin(r))
        sid = re.search(r"snapshot ([0-9a-f]{4}-\d+)", metin(r))
        ref = f"{sid.group(1)}:{mref.group(1)}" if (mref and sid) else None
        r = await c.call_tool("type_text", {"ref": ref, "text": uzun, **F}) if ref else None
        n = sum(yazi_satiri(x) for x in au.satirlar)
        kontrol("B2: ref ile uzun yazı (alanı tıkla + yaz), başlık önizlemesi kesmez",
                r is not None and not r.is_error and n == len(uzun), f"ref={ref} {n} {metin(r)[:300] if r else ''}")
        kontrol("B2: kimlik verilen eylemde başlık kilidi yok; desen verilince desen",
                s.baslik_kilidi(A, A) is None and s.baslik_kilidi("KWrite", A) == "KWrite")
        au = iki_pencere(sm)

        def sinif_degisir(x):
            if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) >= 3:
                au.pen[A][1] = "konsole"  # aynı kimlik başka uygulamaya geçti (X kimliği yeniden kullanımı)
        au.kanca_satir = sinif_degisir
        r = await c.call_tool("type_text", {"window": A, "text": "abcdef ghijkl", **F})
        n = sum(yazi_satiri(x) for x in au.satirlar)
        kontrol("B2: kimlik kilidi pencere SINIFINI da tutar: sınıf değişince kelime başında durur",
                r.is_error and "[4]" in metin(r) and n < 13, f"{n} {metin(r)[:300]}")

        # ---- B3: batch durunca observe_after
        au = iki_pencere(sm)
        au.pen[B][0] = "Başka — Kate"
        r = await c.call_tool("batch", {"steps": [
            {"tool": "press_key", "args": {"window": A, "keys": "a"}},
            {"tool": "click", "args": {"window": B, "ref": "zzzz-9:1"}}], "observe_after": True, **F})
        m = metin(r)
        kontrol("B3: batch durdu → observe_after ATLANDI (başarılı adımın penceresi başarısızınki sanılmasın)",
                r.is_error and "batch stopped" in m and "observe_after skipped" in m and "snapshot " not in m, m[:500])
        au = iki_pencere(sm)
        r = await c.call_tool("batch", {"steps": [{"tool": "press_key", "args": {"window": A, "keys": "a"}}],
                                        "observe_after": True, **F})
        kontrol("B3: batch başarılı → observe_after yine eklenir", not r.is_error and
                (yapi(r).get("observe") or {}).get("snapshot_id"), metin(r)[:300])

        # ---- B4: hedef yazı ortasında kapanır
        au = iki_pencere(sm)

        def kapanir(x):
            if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) >= 3:
                au.pen.pop(A, None)
                au.aktif_ = B
        au.kanca_satir = kapanir
        r = await c.call_tool("type_text", {"window": A, "text": "abcdef ghijkl", **F})
        m = metin(r)
        kontrol("B4: hedef yazı ortasında kapandı → [8] 'hedef pencere kapandı' (aktif değişti değil) + 6/13",
                r.is_error and "[8]" in m and "hedef pencere kapandı" in m and "6/13" in m, m[:400])
        au.kanca_satir = None

        await r2_testleri(c, sm)


def _ucuncu_harfte(au, eylem_):
    """3. 'type' satırından sonra eylem_() (kelime sonu = 6/13: ilk kelime 'abcdef' 6 harf)."""
    def kanca(x):
        if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) == 3:
            eylem_()
    return kanca


async def r2_testleri(c, sm):
    """ABM-F2 inceleme düzeltmeleri (R2): PoC P1/P1b/P2/P3 + run_flow/manage_window sınıf kilidi."""
    from deskhand import api, guvenlik

    # ---- R2-1 (P1): yazı ortasında sınıf kilidi reddi → "girdi gönderilmedi" DENMEZ, kaç karakter gittiği söylenir
    au = iki_pencere(sm)
    au.kanca_satir = _ucuncu_harfte(au, lambda: au.pen[A].__setitem__(1, "konsole"))
    r = await c.call_tool("type_text", {"window": A, "text": "abcdef ghijkl", **F})
    m = metin(r)
    kontrol("R2-1 P1: sınıf değişti (6 harf gitti) → ileti 'girdi gönderilmedi' İÇERMEZ, '6/13 karakter gönderildi' der",
            r.is_error and "[4]" in m and "girdi gönderilmedi" not in m and "6/13 karakter gönderildi" in m
            and yapi(r).get("sent") == "maybe_partial", m[:400])

    # ---- R2-1 (P1b): başlık deseni yazı ortasında uymaz
    au = sm.sifirla(baslik="Belge — KWrite")
    au.kanca_satir = _ucuncu_harfte(au, lambda: au.pen[A].__setitem__(0, "Odeme — Firefox"))
    r = await c.call_tool("type_text", {"window": "Belge", "text": "abcdef ghijkl", **F})
    m = metin(r)
    kontrol("R2-1 P1b: başlık deseni ortada uymadı → 'girdi gönderilmedi' YOK, '6/13 karakter gönderildi' var",
            r.is_error and "[4]" in m and "girdi gönderilmedi" not in m and "6/13 karakter gönderildi" in m, m[:400])

    # ---- R2-1 gerileme: yazı başında ret (hiç harf gitmedi) → "girdi gönderilmedi" kalır
    au = iki_pencere(sm)
    au.aktif_ = B
    au.one_getir = lambda k: None  # odak geri alınamaz: ilk kelimede dur
    r = await c.call_tool("type_text", {"window": A, "text": "abcdef", **F})
    m = metin(r)
    kontrol("R2-1: hiç harf gitmeden ret → 'girdi gönderilmedi' (gerileme)",
            r.is_error and "girdi gönderilmedi" in m and not any(x.startswith("type ") for x in au.satirlar), m[:300])
    del au.one_getir

    # ---- R2-2 (P2): gizli + submit, Enter giriş penceresini kapatır / odağı taşır → BAŞARI, uyarı yok
    for ad, sonra in (("odak değişti", lambda au: setattr(au, "aktif_", B)),
                      ("pencere kapandı", lambda au: (au.pen.pop(A, None), setattr(au, "aktif_", B)))):
        au = iki_pencere(sm)
        au.pen[B][0] = "Diğer — Kate"

        def enter(x, au=au, sonra=sonra):
            if x == "key enter":
                sonra(au)
        au.kanca_satir = enter
        r = await c.call_tool("type_text", {"window": A, "text": "parola12", "submit": True, "secret": True,
                                            "verify": False, **F})
        m = metin(r)
        n = sum(x.startswith("type ") for x in au.satirlar)
        kontrol(f"R2-2 P2: secret + submit, Enter sonrası {ad} → başarı (8 harf + Enter), kesildi/uyarı yok",
                not r.is_error and n == 8 and au.satirlar.count("key enter") == 1 and "kesildi" not in m
                and "warning" not in m and "gitmiş olabilir" not in m, m[:400])
    # harf sırasındaki çift yoklama aynen: son harften SONRA odak kaçarsa Enter gönderilmez
    au = iki_pencere(sm)

    def son_harf(x, au=au):
        if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) == 8:
            au.aktif_ = B
    au.kanca_satir = son_harf
    r = await c.call_tool("type_text", {"window": A, "text": "parola12", "submit": True, "secret": True, **F})
    m = metin(r)
    kontrol("R2-2: secret + submit, son harften sonra odak kaçtı → Enter GÖNDERİLMEZ, '8/9 karakter gönderildi'",
            r.is_error and "key enter" not in au.satirlar and "8/9 karakter gönderildi" in m, m[:400])

    # ---- R2-3 (P3): gizli yazıda odağı çalan pencerenin BAŞLIĞI iletiye girmez
    au = iki_pencere(sm)
    gizli = "qzxjkw"

    def calar(x, au=au):
        if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) == 4:
            au.aktif_ = B
            au.pen[B][0] = f"Başlıksız ({x[5:]}) * — KWrite"  # sızan harf B'nin başlık önizlemesinde
    au.kanca_satir = calar
    r = await c.call_tool("type_text", {"window": A, "text": gizli, "secret": True, **F})
    m = metin(r)
    kontrol("R2-3 P3: gizli yazıda odak çalındı → iletide çalanın başlığı YOK ('başlık gizlendi'), harf yok",
            r.is_error and "Başlıksız" not in m and "(j)" not in m and "başlık gizlendi" in m and "4/6" in m, m[:400])
    # gizli OLMAYAN yazıda başlık kalır
    au = iki_pencere(sm)
    au.pen[B][0] = "Diğer — Kate"
    au.kanca_satir = _ucuncu_harfte(au, lambda: setattr(au, "aktif_", B))
    r = await c.call_tool("type_text", {"window": A, "text": "abcdef ghijkl", **F})
    kontrol("R2-3: gizli olmayan yazıda odağı çalanın başlığı iletide kalır", "Diğer — Kate" in metin(r), metin(r)[:300])
    # gizli + başlık deseni: yazı ortasında hedefin başlığı (önizleme) uymaz → başlık iletiye girmez
    au = sm.sifirla(baslik="Belge — KWrite")
    au.kanca_satir = _ucuncu_harfte(au, lambda: au.pen[A].__setitem__(0, "Odeme (abc) — Firefox"))
    r = await c.call_tool("type_text", {"window": "Belge", "text": "abcdef ghijkl", "secret": True, **F})
    m = metin(r)
    kontrol("R2-3: gizli + desen, başlık ortada uymadı → başlık iletide YOK ('başlık gizlendi')",
            r.is_error and "Odeme" not in m and "(abc)" not in m and "başlık gizlendi" in m, m[:400])

    # ---- R2-4: run_flow / manage_window kimlikle çağrılınca da sınıf kilidi kurulur
    gorulen = {}

    def yonet(k, *a, **kw):
        gorulen["yonet"] = getattr(guvenlik._KIMLIK_KILIDI, "sinif", None)
        return {"baslik": "Belge — KWrite", "geometri": (1, 2, 3, 4), "onceki": (1, 2, 3, 4), "uyari": None}

    def akis(k, *a, **kw):
        gorulen["akis"] = getattr(guvenlik._KIMLIK_KILIDI, "sinif", None)
        return "tamam"
    eski = api.pencere_yonet, api.akis_calistir, api.akis_yolu, api.akis_onayli_adimlar
    api.pencere_yonet, api.akis_calistir = yonet, akis
    api.akis_yolu, api.akis_onayli_adimlar = (lambda ad: "/yok/" + ad), (lambda yol: [])
    try:
        au = iki_pencere(sm)
        await c.call_tool("manage_window", {"window": A, "action": "maximize", **F})
        await c.call_tool("run_flow", {"action": "run", "name": "x", "window": A, **F})
    finally:
        api.pencere_yonet, api.akis_calistir, api.akis_yolu, api.akis_onayli_adimlar = eski
    kontrol("R2-4: manage_window kimlikle → sınıf kilidi kurulu (A, kwrite)", gorulen.get("yonet") == (A, "kwrite"),
            repr(gorulen))
    kontrol("R2-4: run_flow kimlikle → sınıf kilidi kurulu (A, kwrite)", gorulen.get("akis") == (A, "kwrite"),
            repr(gorulen))
    kontrol("R2-4: eylem bitince sınıf kilidi kalkar", getattr(guvenlik._KIMLIK_KILIDI, "sinif", None) is None)

    await ek1_testleri(c, sm)


def _gunluk_metni():
    from deskhand import yollar
    d = yollar.gunluk_dizin()
    try:
        return "".join(open(os.path.join(d, f)).read() for f in sorted(os.listdir(d)) if f.startswith("gunluk-"))
    except OSError:
        return ""


def _sizinti(metin_, sir):
    """Gizli metnin 3'lük parçalarından ya da önizleme biçiminden (ilk harf parantezde) biri metinde mi."""
    return [sir[i:i + 3] for i in range(len(sir) - 2) if sir[i:i + 3] in metin_] + (["(" + sir[0]] if "(" + sir[0] in metin_ else [])


async def ek1_testleri(c, sm):
    """EK-1: KWrite önizlemeli başlıkta secret=true → sonuçta, günlükte ve etkinlik akışında gizli harf yok."""
    from deskhand.gui import gunluk_okur
    sir = "qzxjkw"

    def onizlemeli():
        au = iki_pencere(sm, baslik="Başlıksız — KWrite")
        yazilan = []

        def onizleme(x):
            if x.startswith("type "):
                yazilan.append(x[5:])
                au.pen[A][0] = f"Başlıksız ({''.join(yazilan)}) * — KWrite"
        au.kanca_satir = onizleme
        return au

    g0 = _gunluk_metni()
    au = onizlemeli()
    r = await c.call_tool("type_text", {"window": A, "text": sir, "secret": True, **F})
    m = metin(r)
    kontrol("EK-1: secret=true önizlemeli başlık → MCP sonucunda gizli harf yok, after.title gizlendi",
            not r.is_error and not _sizinti(m, sir) and "(gizli yazı: gizlendi)" in m
            and au.pen[A][0].startswith("Başlıksız (qzxjkw)"), m[:400])
    yeni = _gunluk_metni()[len(g0):]
    kontrol("EK-1: günlükte gizli harf yok", yeni and not _sizinti(yeni, sir), yeni[-400:])
    akis = [gunluk_okur.ayristir(x) for x in yeni.splitlines()]
    akis_metni = " ".join(f"{d.get('pencere')} {d.get('eylem')}" for d in akis if d)
    kontrol("EK-1: etkinlik akışında (gunluk_okur) gizli harf yok", akis_metni and not _sizinti(akis_metni, sir),
            akis_metni[-400:])
    # gizli olmayan yazıda after.title kalır (gerileme)
    au = onizlemeli()
    r = await c.call_tool("type_text", {"window": A, "text": "acik", **F})
    kontrol("EK-1: gizli olmayan yazıda after.title kalır", "Başlıksız (acik)" in metin(r), metin(r)[:300])
    # batch: gizli adım + observe_after → gözlem gizli önizlemeyi döndürmez
    au = onizlemeli()
    r = await c.call_tool("batch", {"steps": [{"tool": "type_text", "args": {"window": A, "text": sir, "secret": True}}],
                                    "observe_after": True, **F})
    m = metin(r)
    kontrol("EK-1: batch gizli adım + observe_after → çıktıda gizli harf yok, gözlem atlandı",
            not r.is_error and not _sizinti(m, sir) and "observe_after skipped" in m, m[:500])
    # gizli yazı hata yolunda (yasak/sistem istemi gibi başlıklı ret) hedefin önizlemeli başlığı iletiye girmez
    au = onizlemeli()
    au.kanca_satir = None
    au.pen[A][0] = "Başlıksız (qzx) * — KWrite"  # önceki gizli yazının önizlemesi başlıkta
    from deskhand import guvenlik
    eski = guvenlik.yasak_desenler
    guvenlik.yasak_desenler = lambda: [r"Başlıksız"]
    try:
        r = await c.call_tool("type_text", {"window": A, "text": sir, "secret": True, **F})
    finally:
        guvenlik.yasak_desenler = eski
    m = metin(r)
    kontrol("EK-1: gizli yazıda yasak pencere reddi → [10], iletide önizlemeli başlık yok",
            r.is_error and "[10]" in m and not _sizinti(m, sir), m[:400])
    au.kanca_satir = None


def gozcu_kesintisi_testleri():
    """kde/sanal gözcüsü başlıklı Dur bırakırsa (kesildi): gizli yazıda başlık iletiye taşınmaz; hiç harf gitmeden
    gelen kesintide ileti 'girdi gönderilmedi' der (yazilan==0 tutarlılığı)."""
    import sahte_masaustu as sm
    from deskhand import eylem, guvenlik
    from deskhand.hata import Dur
    au = iki_pencere(sm)
    g = sm.SahteGirdi(au, gizli=True, denetle=guvenlik.denetle)

    def kanca(x):
        if x.startswith("type ") and sum(y.startswith("type ") for y in au.satirlar) == 4:
            g.kesildi = Dur(3, "aktif pencere değişti → 'Başlıksız (j) * — KWrite'")  # gözcünün bıraktığı
    au.kanca_satir = kanca
    try:
        eylem._harf_harf_yaz(g, A, None, "qzxjkw", False)
        m = "(durmadı)"
    except Dur as e:
        m = e.mesaj
    kontrol("R2-3 gözcü: gizli yazıda gözcünün başlıklı iletisi → başlık gizlenir, harf yok",
            "(j)" not in m and "Başlıksız" not in m and "başlık gizlendi" in m, m)
    au = iki_pencere(sm)
    g = sm.SahteGirdi(au, gizli=False, denetle=guvenlik.denetle)
    au.kanca_satir = lambda x: x.startswith("typedelay") and setattr(g, "kesildi", Dur(3, "aktif pencere değişti → 'X'"))
    try:
        eylem._harf_harf_yaz(g, A, None, "abc", False)
        m = "(durmadı)"
    except Dur as e:
        m = e.mesaj
    kontrol("R2-5 nit: hiç harf gitmeden gözcü kesintisi → 'girdi gönderilmedi' eki (tutarlı)",
            "girdi gönderilmedi" in m and not any(x.startswith("type ") for x in au.satirlar), m)
    au.kanca_satir = None


def kde_sanal_gozcu_testleri():
    """EK-1: kde ve sanal gözcüleri gizli yazıda odağı çalanın / hedefin başlığını kaynakta gizler."""
    from deskhand.arka_uc import kde, sanal

    def bekle(g):
        bitis = time.monotonic() + 3
        while g.kesildi is None and time.monotonic() < bitis:
            time.sleep(0.01)
        g.izle_bitir()
        return g.kesildi

    eski = kde.aktif, kde.fare, kde.baslik, kde.baslik_ve_fare
    kde.aktif, kde.fare = (lambda: "{diger}"), (lambda: (None, None, None))
    kde.baslik = lambda k: "Başlıksız (qzx) * — KWrite"
    kde.baslik_ve_fare = lambda k: ("Başlıksız (qzx) * — KWrite", (None, None, None))
    try:
        sonuc = {}
        for gizli in (False, True):
            g = kde.Girdi.__new__(kde.Girdi)
            g.gizli, g.kesildi = gizli, None
            g.izle("{hedef}", None)
            sonuc[gizli] = bekle(g)
    finally:
        kde.aktif, kde.fare, kde.baslik, kde.baslik_ve_fare = eski
    e0, e1 = sonuc[False], sonuc[True]
    kontrol("EK-1 gözcü (kde): gizli olmayanda başlık var, gizlide yok ('başlık gizlendi')",
            e0 is not None and "(qzx)" in e0.mesaj and e1 is not None and e1.kod == 3 and "(qzx)" not in e1.mesaj
            and "başlık gizlendi" in e1.mesaj, f"{e0 and e0.mesaj} | {e1 and e1.mesaj}")

    class SahteX:
        def __init__(self, ekran):
            pass

        def aktif(self):
            return 0x99

        def baslik(self, w):
            return "Başlıksız (qzx) * — KWrite"

        def kapat(self):
            pass

    class SahteArka:
        def ekran_adi(self):
            return ":99"

    eski_x = sanal._X
    sanal._X = SahteX
    try:
        sonuc = {}
        for gizli in (False, True):
            g = sanal.SanalGirdi.__new__(sanal.SanalGirdi)
            g.gizli, g.kesildi, g._izleyici, g.arka = gizli, None, None, SahteArka()
            g.izle(sanal.kimlik_yap(0x42), None)
            sonuc[gizli] = bekle(g)
    finally:
        sanal._X = eski_x
    e0, e1 = sonuc[False], sonuc[True]
    kontrol("EK-1 gözcü (sanal): gizli olmayanda başlık var, gizlide yok ('başlık gizlendi')",
            e0 is not None and "(qzx)" in e0.mesaj and e1 is not None and e1.kod == 3 and "(qzx)" not in e1.mesaj
            and "başlık gizlendi" in e1.mesaj, f"{e0 and e0.mesaj} | {e1 and e1.mesaj}")


def kwin_gozcu_testleri():
    """KwinGirdi.izle (gözcü) sahte kdotool + liste ile: oturum açılmaz, EIS'e satır gitmez."""
    from deskhand.arka_uc import kwin
    u, kardes = "{11111111-1111-1111-1111-111111111111}", "{22222222-2222-2222-2222-222222222222}"

    class SahteArka:
        def __init__(self, liste):
            self.liste = liste

        def _d(self):
            return {}

        def _kd(self, *a, d=None):
            if a[0] == "getactivewindow":
                return kardes
            if a[0] == "getwindowname":
                return "Mozilla Firefox"
            return ""

        def _liste(self, d=None):
            return [{"i": i} for i in self.liste]

    def gozle(liste, gizli=False):
        g = kwin.KwinGirdi.__new__(kwin.KwinGirdi)
        g.arka, g.kesildi, g._izleyici, g.gizli = SahteArka(liste), None, None, gizli
        g._izle_dur, g._b_kilit, g._basili_tus, g._basili_dugme = threading.Event(), threading.Lock(), [], []
        g.izle(kwin.kimlik_yap(u), None)
        bitis = time.monotonic() + 3
        while g.kesildi is None and time.monotonic() < bitis:
            time.sleep(0.01)
        g.izle_bitir()
        return g.kesildi

    e = gozle([kardes])
    kontrol("B4 gözcü (kwin): hedef listede yok → 8 'hedef pencere kapandı'",
            e is not None and e.kod == 8 and "hedef pencere kapandı" in e.mesaj, repr(e and e.mesaj))
    e = gozle([u, kardes])
    kontrol("gözcü (kwin): hedef duruyor, kardeş etkin → 3 'aktif pencere değişti' (gerileme)",
            e is not None and e.kod == 3 and "aktif pencere değişti" in e.mesaj, repr(e and e.mesaj))
    kontrol("gözcü (kwin): gizli olmayan yazıda çalanın başlığı iletide", e is not None and "Mozilla Firefox" in e.mesaj,
            repr(e and e.mesaj))
    kde_sanal_gozcu_testleri()
    e = gozle([u, kardes], gizli=True)
    kontrol("R2-3 gözcü (kwin): gizli yazıda odağı çalanın başlığı iletiye girmez",
            e is not None and e.kod == 3 and "Mozilla Firefox" not in e.mesaj and "başlık gizlendi" in e.mesaj,
            repr(e and e.mesaj))


def main():
    t0 = time.monotonic()
    asyncio.run(sahte_testler())
    gozcu_kesintisi_testleri()
    kwin_gozcu_testleri()
    print(f"\n{gecen}/{toplam} çok pencere testi geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if gecen == toplam else 1)


if __name__ == "__main__":
    main()
