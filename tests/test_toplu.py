"""MCP `batch` (toplu adımlar) testleri. Kullanıcının GERÇEK ekranına hiçbir girdi gitmez; gerçek ~/.config yazılmaz.

 A) Süreç içi sahte kde arka ucu + sahte AT-SPI (tests/yardimci/sahte_masaustu.py): sıra ve adım sonuçları; HİÇBİR
    şey göndermeden önce tüm adımların doğrulanması (şema, desktop, wait, en çok 20, izinli araçlar); ilk hatada durma
    + not_sent + sent; adımlar arasında DUR / bekleyen onay / insan önceliği; adımın onay istemesi (red = dur, izin =
    devam); döngü kesici; wait adımında DUR; observe_after.
 B) GÖRÜNMEZ masaüstünde gerçek Qt penceresi: ref'li adımlar sırayla gerçekten uygulanır.

Çalıştır:  python3 tests/test_toplu.py"""
import asyncio
import atexit
import os
import re
import shutil
import sys
import time

import _yalitim  # noqa: F401  (DESKHAND_* geçici klasörler; Deskhand'den ÖNCE)

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))

from deskhand import guvenlik, masaustu, mcp_sunucu as s  # noqa: E402

atexit.register(lambda: masaustu.durum_oku() is not None and masaustu.masaustu_durdur())
KOK = _yalitim.KOK
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
    """structuredContent; observe/batch'te yok (yalnız metin) → metin ayrıştırılır (tests/yardimci/mcp_metin.py)."""
    import mcp_metin
    return mcp_metin.yapi(r)


async def sahte_testler():
    from mcp import Client
    import sahte_masaustu as sm
    F = {"desktop": "foreground"}
    au = sm.kur()
    async with Client(s.mcp) as c:
        async def refler():
            r = await c.call_tool("observe", {"window": "KWrite", **F})
            return {e.get("name"): e["ref"] for e in yapi(r).get("elements", [])}

        async def toplu(adimlar, **k):
            return await c.call_tool("batch", {"steps": adimlar, **F, **k})

        ref = await refler()
        n0 = len(au.satirlar)
        r = await toplu([{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                         {"tool": "type_text", "args": {"ref": ref["Ad"], "text": "Veli"}},
                         {"tool": "press_key", "args": {"window": "KWrite", "keys": "tab"}},
                         {"tool": "wait", "args": {"seconds": 0.1}},
                         {"tool": "scroll", "args": {"ref": ref["Liste bir"], "direction": "down"}}])
        st = yapi(r)
        sat = au.satirlar[n0:]
        sira = [i for i, x in enumerate(sat) if x in ("click left", "key tab", "wheel -3") or x.startswith("type ")]
        t = [sat[i].split()[0] for i in sira]
        kontrol("batch: 5 adım sırayla (tık, tık+yazı, tuş, bekle, kaydır), her adımın ok/effect sonucu",
                not r.is_error and st.get("status") == "ok" and [x["tool"] for x in st["steps"]] ==
                ["click", "type_text", "press_key", "wait", "scroll"] and all(x["ok"] for x in st["steps"]) and
                all("effect" in x for x in st["steps"] if x["tool"] != "wait") and
                [x for j, x in enumerate(t) if j == 0 or t[j - 1] != x] == ["click", "type", "key", "wheel"] and
                sat.count("click left") == 2,
                f"{metin(r)[:400]} {sat}")
        kontrol("batch: metin özeti adım adım", "batch ok: 5/5 steps ok" in metin(r) and "4. wait" in metin(r),
                metin(r)[:300])

        # ---- doğrulama: hiçbir şey göndermeden önce
        async def gonderimsiz(ad, adimlar, beklenen="[1]", **k):
            n0 = len(au.satirlar)
            r = await toplu(adimlar, **k)
            kontrol(f"batch doğrulama [{ad}] → hata, HİÇBİR adım gönderilmedi", r.is_error and beklenen in metin(r) and
                    len(au.satirlar) == n0, metin(r)[:300])
        await gonderimsiz("3. adımda eksik argüman (keys)", [{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                                                              {"tool": "wait", "args": {"seconds": 0}},
                                                              {"tool": "press_key", "args": {"window": "KWrite"}}])
        await gonderimsiz("adımda başka desktop", [{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                                                    {"tool": "press_key", "args": {"window": "KWrite", "keys": "a",
                                                                                   "desktop": "background"}}])
        await gonderimsiz("wait 11 sn (> 10)", [{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                                                 {"tool": "wait", "args": {"seconds": 11}}])
        await gonderimsiz("izinsiz araç open_app", [{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                                                     {"tool": "open_app", "args": {"app": "firefox"}}], beklenen="")
        await gonderimsiz("iç içe batch", [{"tool": "batch", "args": {}}], beklenen="")
        await gonderimsiz("21 adım (> 20)", [{"tool": "wait", "args": {"seconds": 0}}] * 21, beklenen="")
        await gonderimsiz("adımda bilinmeyen argüman türü (amount='çok')",
                          [{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                           {"tool": "scroll", "args": {"window": "KWrite", "amount": "çok"}}])

        # ---- ilk hatada dur
        n0 = len(au.satirlar)
        r = await toplu([{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                         {"tool": "click", "args": {"window": "KWrite", "element": "Olmayan öge"}},
                         {"tool": "press_key", "args": {"window": "KWrite", "keys": "enter"}},
                         {"tool": "press_key", "args": {"window": "KWrite", "keys": "esc"}}])
        st = yapi(r)
        kontrol("batch: 2. adım hata → dur; failed_step 2, not_sent [3, 4], batch sent maybe_partial (1. adım gitti)",
                r.is_error and st.get("status") == "stopped" and st.get("failed_step") == 2 and
                st.get("not_sent") == [3, 4] and st.get("sent") == "maybe_partial" and
                st["steps"][1]["sent"] == "nothing_sent" and "key enter" not in au.satirlar[n0:], metin(r)[:400])
        kontrol("batch: hata metninde hangi adım + kalanlar + next", "stopped at step 2" in metin(r) and
                "not sent: steps [3, 4]" in metin(r) and "next:" in metin(r), metin(r)[-300:])
        r = await toplu([{"tool": "click", "args": {"window": "KWrite", "element": "Olmayan öge"}},
                         {"tool": "press_key", "args": {"window": "KWrite", "keys": "enter"}}])
        kontrol("batch: İLK adım hata → batch sent nothing_sent, effect refused", yapi(r).get("sent") == "nothing_sent"
                and yapi(r).get("effect") == "refused", str(yapi(r))[:300])

        # ---- adımlar arası denetimler
        async def arada(ad, kanca, kod, geri):
            n0 = len(au.satirlar)
            ilk = {"v": True}

            def k_(satir):
                if satir == "click left" and ilk["v"]:
                    ilk["v"] = False
                    kanca()
            au.kanca_satir = k_
            t0 = time.monotonic()
            r = await toplu([{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                             {"tool": "press_key", "args": {"window": "KWrite", "keys": "enter"}},
                             {"tool": "press_key", "args": {"window": "KWrite", "keys": "esc"}}])
            au.kanca_satir = None
            geri()
            sat = au.satirlar[n0:]
            kontrol(f"batch adımlar arası [{ad}] → 2. adım [{kod}], tuşlar gönderilmedi, not_sent [3]",
                    r.is_error and yapi(r).get("failed_step") == 2 and f"[{kod}]" in yapi(r)["steps"][1]["error"] and
                    "key enter" not in sat and "key esc" not in sat and yapi(r).get("not_sent") == [3],
                    f"{metin(r)[:300]} {sat}")
            return time.monotonic() - t0
        await arada("DUR", lambda: guvenlik.dur_ac("kullanici"), 13, lambda: guvenlik.dur_kapat("kullanici"))
        await arada("bekleyen onay", lambda: s._BEKLEYEN.__setitem__("kde", 1), 7, s._BEKLEYEN.clear)
        sure = await arada("insan önceliği (8 sn bekler)", lambda: setattr(au, "insan", True), 12,
                           lambda: setattr(au, "insan", False))
        kontrol("batch: insan önceliğinde en çok ~8 sn beklendi", 7.5 <= sure <= 20, f"{sure:.1f}")

        # ---- adım onay ister: red = dur, izin = devam
        au = sm.sifirla()
        ref = await refler()
        adimlar = [{"tool": "click", "args": {"ref": ref["Kaydet"]}},
                   {"tool": "click", "args": {"ref": ref["Satın al"]}},
                   {"tool": "press_key", "args": {"window": "KWrite", "keys": "esc"}}]
        n0 = len(au.satirlar)
        r = await toplu(adimlar)
        sat = au.satirlar[n0:]
        kontrol("batch: hassas adım + red → o adımda dur ([10]), onay istendi, 'Satın al' ve sonrası gönderilmedi",
                r.is_error and yapi(r).get("failed_step") == 2 and "[10]" in yapi(r)["steps"][1]["error"] and
                len(sm.ISTEKLER) == 1 and sat.count("click left") == 1 and "key esc" not in sat, f"{metin(r)[:300]} {sat}")
        sm.YANIT["izin"] = True
        sm.ISTEKLER.clear()
        ref = await refler()
        adimlar[0]["args"]["ref"], adimlar[1]["args"]["ref"] = ref["Kaydet"], ref["Satın al"]
        n0 = len(au.satirlar)
        r = await toplu(adimlar)
        sat = au.satirlar[n0:]
        kontrol("batch: hassas adım + izin → bekler, sonra devam; approved_by_user o adımda",
                not r.is_error and yapi(r)["steps"][1].get("approved_by_user") is True and len(sm.ISTEKLER) == 1 and
                sat.count("click left") == 2 and "key esc" in sat, f"{metin(r)[:300]} {sat}")
        sm.YANIT["izin"] = False

        # ---- döngü kesici (aynı çekirdek)
        s._DONGU.temizle()
        r = await toplu([{"tool": "press_key", "args": {"window": "KWrite", "keys": "a"}}] * 7)
        st = yapi(r)
        kontrol("batch: döngü kesici aynı — 3. adımda uyarı, 6. adım [7] ile durdu",
                st.get("failed_step") == 6 and "[7]" in st["steps"][5]["error"] and st["steps"][2].get("warning"),
                metin(r)[:400])
        s._DONGU.temizle()

        # ---- wait adımında DUR
        def dur_sonra():
            time.sleep(0.3)
            guvenlik.dur_ac("kullanici")
        import threading
        threading.Thread(target=dur_sonra, daemon=True).start()
        t0 = time.monotonic()
        r = await toplu([{"tool": "wait", "args": {"seconds": 5}}, {"tool": "press_key",
                                                                     "args": {"window": "KWrite", "keys": "a"}}])
        guvenlik.dur_kapat("kullanici")
        kontrol("batch: wait sırasında DUR → [13] hemen (5 sn beklenmez)", r.is_error and "[13]" in metin(r) and
                time.monotonic() - t0 < 3, f"{time.monotonic() - t0:.1f} {metin(r)[:200]}")

        # ---- observe_after
        ref = await refler()
        r = await toplu([{"tool": "click", "args": {"ref": ref["Kaydet"]}}], observe_after=True)
        kontrol("batch observe_after: son adımın penceresinin gözlemi (snapshot_id + ögeler) eklendi",
                not r.is_error and yapi(r).get("observe", {}).get("snapshot_id") and
                re.search(r"snapshot [0-9a-f]{4}-\d+", metin(r)), metin(r)[:400])


async def sanal_test():
    from mcp import Client
    LOG = os.path.join(_yalitim.GECICI, "a11y-toplu.log")
    import importlib
    from deskhand import erisim, eylem, onay
    importlib.reload(erisim)  # A'nın sahteleri temizlensin: gerçek AT-SPI
    importlib.reload(eylem)
    importlib.reload(onay)
    masaustu.masaustu_baslat()
    masaustu.baslat([sys.executable, os.path.join(KOK, "tests/yardimci/a11y_pencere.py")],
                    {"LOG": LOG, "PENCERE_BASLIK": "toplu-a11y"})
    for _ in range(100):
        if os.path.exists(LOG) and "hazir" in open(LOG).read():
            break
        time.sleep(0.2)
    B = {"desktop": "background"}
    async with Client(s.mcp) as c:
        ref = {}
        for _ in range(40):
            r = await c.call_tool("observe", {"window": "toplu-a11y", **B})
            ref = {e.get("name"): e["ref"] for e in yapi(r).get("elements", [])}
            if "Kaydet" in ref:
                break
            await asyncio.sleep(0.25)
        r = await c.call_tool("batch", {"steps": [
            {"tool": "click", "args": {"ref": ref.get("Tamam", "")}},
            {"tool": "click", "args": {"ref": ref.get("Onayla", ""), "via": "action"}},
            {"tool": "type_text", "args": {"ref": ref.get("Ad", ""), "text": "Toplu ğüş"}},
            {"tool": "click", "args": {"ref": ref.get("Gelişmiş", "")}}], **B})
        time.sleep(0.3)
        olay = [x for x in open(LOG).read().splitlines() if x.split(":")[0] in ("tikla", "isaret", "metin", "sekme")]
        kontrol("sanal batch: ref'li 4 adım sırayla uygulandı (Tamam, Onayla, Ad, Gelişmiş)",
                not r.is_error and olay[:1] == ["tikla:Tamam"] and "isaret:Onayla:1" in olay and
                "metin:Ad:Toplu ğüş" in olay and olay[-1:] == ["sekme:Gelişmiş"] and
                yapi(r)["steps"][1].get("effect") == "confirmed", f"{metin(r)[:400]} {olay}")
    masaustu.masaustu_durdur()


def sanal_mumkun():
    try:
        import PyQt6  # noqa: F401
        import gi
        gi.require_version("Atspi", "2.0")
    except (ImportError, ValueError):
        return False
    return all(shutil.which(a) for a in ("Xvfb", "dbus-daemon")) and os.path.exists("/usr/lib/at-spi-bus-launcher")


def main():
    t0 = time.monotonic()
    asyncio.run(sahte_testler())
    if sanal_mumkun():
        asyncio.run(sanal_test())
    else:
        print("ATLANDI (B): Xvfb / PyQt6 / at-spi2-core yok")
    print(f"\n{gecen}/{toplam} toplu adım testi geçti ({time.monotonic() - t0:.1f} sn)")
    sys.exit(0 if gecen == toplam else 1)


if __name__ == "__main__":
    main()
