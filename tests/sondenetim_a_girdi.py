"""Son denetim A (girdi/onay yolları) kanıt testleri. Gerçek ekrana girdi YOK: süreç içi sahte kde arka ucu.

 1) OCR ref bayatlığı: observe'dan sonra pencerenin BAŞLIĞI değişti (başka belge/sekme), aynı yazı aynı yerde →
    click(ref) yine tıklıyor mu? (Anlik.baslik saklanıyor ama _ref_coz karşılaştırmıyor.)
 2) wait_for ön planda: kullanıcı klavye/fare kullanırken (insan önceliği) her yoklamada hedef pencere öne getiriliyor mu?

Çalıştır:  python3 tests/sondenetim_a_girdi.py"""
import asyncio
import os
import sys

import _yalitim  # noqa: F401

sys.path.insert(0, os.path.join(_yalitim.KOK, "tests", "yardimci"))

from deskhand import mcp_sunucu as s  # noqa: E402

sonuc = []


def kontrol(ad, kosul, ek=""):
    sonuc.append(bool(kosul))
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""), flush=True)


def metin(r):
    return "\n".join(getattr(c, "text", "") for c in r.content)


async def main():
    from mcp import Client
    import re
    import sahte_masaustu as sm
    F = {"desktop": "foreground"}
    sm.kur()
    async with Client(s.mcp) as c:
        # ---- 1) OCR ref: başlık değişince ref bayat sayılmalı
        au = sm.sifirla()
        sm.AGACSIZ.add("Belge — KWrite")
        r = await c.call_tool("observe", {"window": "KWrite", **F})
        m = re.search(r"\[(\d+)\] ocr_text \"Kaydet\"", metin(r))
        sid = re.search(r"snapshot ([0-9a-f]{4}-\d+)", metin(r))
        if not (m and sid):
            kontrol("ön koşul: OCR ögesi 'Kaydet' gözlendi", False, metin(r)[:300])
            return
        ref = f"{sid.group(1)}:{m.group(1)}"
        au.pen[sm.PENCERE][0] = "GİZLİ başka belge — KWrite"  # pencere başka içeriğe geçti, aynı yazı aynı yerde
        sm.AGACSIZ.add("GİZLİ başka belge — KWrite")
        n0 = len(au.satirlar)
        r = await c.call_tool("click", {"ref": ref, **F})
        tik = [x for x in au.satirlar[n0:] if x.startswith("click")]
        kontrol("OCR ref: observe sonrası başlık değişti → click(ref) reddedilmeli ([8], tık yok)",
                r.is_error and not tik, f"is_error={r.is_error} tıklar={tik} {metin(r)[:200]}")

        # ---- 2) wait_for ön planda + kullanıcı etkin
        au = sm.sifirla()
        au.pen["{diger}"] = ["Kullanıcının penceresi", "firefox", (900, 100, 600, 600)]
        au.aktif_ = "{diger}"
        au.insan = True
        say = {"n": 0}
        asil = au.one_getir

        def sayan(k):
            if k != au.aktif_:
                say["n"] += 1
            asil(k)
        au.one_getir = sayan
        r = await c.call_tool("wait_for", {"condition": "stable", "window": "KWrite", "timeout_s": 2,
                                           "stable_ms": 5000, **F})
        kontrol("wait_for(stable) ön planda, kullanıcı etkin → hedef pencere öne GETİRİLMEMELİ (odak çalınmamalı)",
                say["n"] == 0, f"öne getirme (odak değişimi) sayısı: {say['n']} / 2 sn; {metin(r)[:160]}")
    print(f"\n{sum(sonuc)}/{len(sonuc)} geçti")


if __name__ == "__main__":
    asyncio.run(main())
