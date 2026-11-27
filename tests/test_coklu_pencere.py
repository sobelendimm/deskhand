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

    def gozle(liste):
        g = kwin.KwinGirdi.__new__(kwin.KwinGirdi)
        g.arka, g.kesildi, g._izleyici = SahteArka(liste), None, None
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


def main():
    t0 = time.monotonic()
    asyncio.run(sahte_testler())
    kwin_gozcu_testleri()
    print(f"\n{gecen}/{toplam} çok pencere testi geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if gecen == toplam else 1)


if __name__ == "__main__":
    main()
