"""observe / batch sonuçlarının METİN içeriğini sözlüğe çevirir (testler için).

Bu iki araç token ekonomisi için outputSchema'sız ve structuredContent'siz döner (docs/ARCHITECTURE.md §10): model
yalnız metni görür. Testler metni ayrıştırarak hem davranışı sınar hem de modelin ihtiyaç duyduğu her alanın METİNDE
olduğunu doğrular (metinde olmayan bir alan burada da yoktur). Biçim: deskhand/gozlem.py `satir`, mcp_sunucu.observe
başlığı ve batch özeti."""
from __future__ import annotations

import ast
import json
import re

_DEC = json.JSONDecoder()
_BASLIK = re.compile(r"snapshot (\S+) \| window (\S+) (\".*?\"(?<!\\\")) (\d+)x(\d+) \| sources (\S+) \| (\d+) items(.*)$")
_OGE = re.compile(r"^(?:([+~]) )?\[(\d+)\] (.*)$")
_KALDIRILAN = re.compile(r"^- \[(\S+):(\d+)\] (.*)$")


def _oge(sid: str, n: int, govde: str) -> dict:
    """`rol "ad" @x,y,w,h durumlar = "değer" !sensitive (ocr) (offscreen) href="…"` → gözlem ögesi (yapisal biçimi)."""
    i_ad, i_kutu = govde.find(' "'), govde.find(" @")
    e: dict = {"ref": f"{sid}:{n}"}
    if i_ad != -1 and (i_kutu == -1 or i_ad < i_kutu):
        e["role"] = govde[:i_ad]
        ad, son = _DEC.raw_decode(govde, i_ad + 1)
        e["name"] = ad
        kalan = govde[son:].lstrip()
    else:
        e["role"] = govde[:i_kutu] if i_kutu != -1 else govde
        kalan = govde[i_kutu + 1:] if i_kutu != -1 else ""
    if kalan.startswith("@"):
        k, _s, kalan = kalan[1:].partition(" ")
        e["frame"] = [int(v) for v in k.split(",")]
    while kalan:
        if kalan.startswith("= "):
            deger, son = _DEC.raw_decode(kalan, 2)
            e["value"] = deger
            kalan = kalan[son:].lstrip()
            continue
        if kalan.startswith("href="):
            href, son = _DEC.raw_decode(kalan, 5)
            e["href"] = href
            kalan = kalan[son:].lstrip()
            continue
        t, _s, kalan = kalan.partition(" ")
        if t == "!sensitive":
            e["sensitive"] = True
        elif t == "(ocr)":
            e["source"] = "ocr"
        elif t == "(offscreen)":
            e["visible"] = False
        elif t:
            e["states"] = t.split(",")
    return e


def gozlem(metin: str) -> dict:
    """observe metni → {snapshot_id, window, sources, total, elements | added/changed/removed, page, notes,
    next_offset, count, shot_id, since}."""
    satirlar = metin.splitlines()
    if not satirlar:
        return {}
    m = _BASLIK.match(satirlar[0])
    if not m:
        return {}
    sid = m.group(1)
    s: dict = {"status": "ok", "snapshot_id": sid,
               "window": {"id": m.group(2), "title": json.loads(m.group(3)), "size": [int(m.group(4)), int(m.group(5))]},
               "sources": [] if m.group(6) == "none" else m.group(6).split("+"), "total": int(m.group(7))}
    ek = m.group(8)
    ms = re.search(r"\| since (\S+): \+(\d+) ~(\d+) -(\d+)", ek)
    if ms:
        s["since"] = ms.group(1)
        s["added"], s["changed"], s["removed"] = [], [], []
    else:
        s["elements"] = []
    for sat in satirlar[1:]:
        if sat.startswith("page "):
            baslik, son = _DEC.raw_decode(sat, 5)
            url, _s, kalan = sat[son:].strip().partition(" | ")
            s["page"] = {"title": baslik, "url": url, "position_verified": "positions unverified" not in sat}
            if "sensitive_page" in sat:
                s["page"]["sensitive_page"] = True
            continue
        if sat.startswith("note: "):
            s.setdefault("notes", []).append(sat[6:])
            continue
        mn = re.match(r"next_offset (\d+):", sat)
        if mn:
            s["next_offset"] = int(mn.group(1))
            continue
        mn = re.match(r"shot_id (\S+):", sat)
        if mn:
            s["shot_id"] = mn.group(1)
            continue
        mk = _KALDIRILAN.match(sat)
        if mk and "removed" in s:
            e = {"ref": f"{mk.group(1)}:{mk.group(2)}"}
            govde = mk.group(3)
            i = govde.find(' "')
            e["role"] = govde if i == -1 else govde[:i]
            if i != -1:
                e["name"] = json.loads(govde[i + 1:])
            s["removed"].append(e)
            continue
        mo = _OGE.match(sat)
        if mo:
            e = _oge(sid, int(mo.group(2)), mo.group(3))
            if mo.group(1) == "+":
                s["added"].append(e)
            elif mo.group(1) == "~":
                s["changed"].append(e)
            else:
                s["elements"].append(e)
    s["count"] = len(s.get("elements", [])) if "elements" in s else \
        len(s["added"]) + len(s["changed"]) + len(s["removed"])
    if "elements" in s:
        s.setdefault("offset", (int(s["elements"][0]["ref"].rsplit(":", 1)[1]) - 1) if s["elements"] else 0)
    return s


_ADIM = re.compile(r"^(\d+)\. (\w+) (.*)$")


def toplu(metin: str) -> dict:
    """batch metni (ilk içerik) → {status, effect, steps, failed_step, not_sent, sent, error}."""
    satirlar = metin.splitlines()
    m = re.match(r"batch (\w+): (\d+)/(\d+) steps ok(?: \| effect (\w+))?", satirlar[0] if satirlar else "")
    if not m:
        return {}
    s: dict = {"status": m.group(1), "steps": []}
    if m.group(4):
        s["effect"] = m.group(4)
    for sat in satirlar[1:]:
        ma = _ADIM.match(sat)
        if ma:
            i, arac, govde = int(ma.group(1)), ma.group(2), ma.group(3)
            x: dict = {"i": i, "tool": arac}
            if govde.startswith("ERROR "):
                x.update(ok=False, error=govde[6:])
            else:
                x["ok"] = True
                uyari = None
                if " warning: " in govde:
                    govde, _s, uyari = govde.partition(" warning: ")
                if govde.endswith(" approved_by_user") or govde == "approved_by_user":
                    x["approved_by_user"] = True
                    govde = govde[:-len("approved_by_user")].rstrip()
                bolge = re.search(r" changed_region=(\[[^\]]*\])", govde)
                if bolge:
                    x["changed_region"] = json.loads(bolge.group(1))
                    govde = govde[:bolge.start()]
                if arac != "wait" or govde != "ok":
                    x["effect"] = govde.strip()
                if uyari:
                    x["warning"] = uyari
            s["steps"].append(x)
            continue
        md = re.match(r"stopped at step (\d+); not sent: steps (.*); failed step sent: (\w+); batch sent: (\w+)$", sat)
        if md:
            s["failed_step"] = int(md.group(1))
            s["not_sent"] = [] if md.group(2) == "none" else ast.literal_eval(md.group(2))
            s["sent"] = md.group(4)
            for x in s["steps"]:
                if x["i"] == s["failed_step"]:
                    x["sent"] = md.group(3)
                    x["effect"] = "refused" if md.group(3) == "nothing_sent" else "unverifiable"
                    kod = re.match(r"\[(\d+)\]", x.get("error", ""))
                    s["error"] = {"code": int(kod.group(1)) if kod else None, "message": x.get("error", "")}
            continue
        if sat.startswith("next: ") and "error" in s:
            s["error"]["next"] = sat[6:]
    return s


def yapi(r) -> dict:
    """Araç sonucu → sözlük: structuredContent varsa o; yoksa (observe/batch) metin ayrıştırılır. batch'in
    observe_after'ı ayrı metin içeriğidir → s["observe"]."""
    if r.structured_content:
        return r.structured_content
    metinler = [getattr(c, "text", "") for c in r.content if getattr(c, "type", "") == "text"]
    if not metinler:
        return {}
    if metinler[0].startswith("batch "):
        s = toplu(metinler[0])
        if len(metinler) > 1:
            s["observe"] = gozlem(metinler[1])
        return s
    if metinler[0].startswith("snapshot "):
        return gozlem(metinler[0])
    return {}
