"""Version drift class check: every place that states the Deskhand version follows deskhand.__version__.

Run:  python3 tests/test_surum.py"""
import _yalitim  # noqa: F401  (DESKHAND_* temp dirs; before Deskhand)
import ast
import glob
import json
import os
import re
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
import deskhand  # noqa: E402

S = deskhand.__version__
gecen = toplam = 0


def kontrol(ad, kosul, ek=""):
    global gecen, toplam
    toplam += 1
    gecen += bool(kosul)
    print(f"{'GEÇTİ' if kosul else 'KALDI'}  {ad}" + (f"  ({ek})" if ek and not kosul else ""))


# notification catcher: GetServerInformation must not carry a hard-coded version literal
yol = os.path.join(KOK, "deskhand", "bildirim_yakalayici.py")
kaynak = open(yol, encoding="utf-8").read()
sabitler = [n.value for n in ast.walk(ast.parse(kaynak)) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and re.fullmatch(r"\d+\.\d+\.\d+", n.value)]
kontrol("bildirim_yakalayici sürümü __version__", not sabitler and "__version__" in kaynak, f"sabit={sabitler}")

sj = json.load(open(os.path.join(KOK, "server.json"), encoding="utf-8"))
paket = sj.get("packages", [{}])[0]
alanlar = {"version": sj.get("version"), "packages[0].version": paket.get("version"),
           "packages[0].identifier": paket.get("identifier", "")}
kontrol("server.json üç sürüm alanı __version__",
        alanlar["version"] == S and alanlar["packages[0].version"] == S
        and f"/v{S}/" in alanlar["packages[0].identifier"], str(alanlar))

def ilk_surum_basligi(satirlar):
    """First "## " heading that is a release, skipping a leading "## Unreleased" / "## [Unreleased]" section."""
    for satir in satirlar:
        if satir.startswith("## "):
            b = satir[3:].strip()
            if b.strip("[]").split("]")[0].strip().lower() == "unreleased":
                continue
            return b
    return None


_ORNEK = ["# Changelog\n", "## [Unreleased]\n", "- x\n", "## Unreleased\n", "## [1.2.3] - 2026-11-27\n", "## 1.2.2\n"]
kontrol("ilk_surum_basligi Unreleased başlıklarını atlar", ilk_surum_basligi(_ORNEK) == "[1.2.3] - 2026-11-27",
        str(ilk_surum_basligi(_ORNEK)))
kontrol("ilk_surum_basligi düz başlık / başlıksız", ilk_surum_basligi(["## 0.9.1 (24 Kasım 2026)\n"]) == "0.9.1 (24 Kasım 2026)"
        and ilk_surum_basligi(["# x\n", "## Unreleased\n"]) is None)


def surum_no(baslik):
    """'[1.2.3] - date' or '1.2.3 (date)' -> '1.2.3'."""
    return baslik.split()[0].strip("[]") if baslik else ""


kontrol("surum_no köşeli ve düz biçim", surum_no("[1.2.3] - 2026-11-27") == "1.2.3" and surum_no("0.9.1 (x)") == "0.9.1")

basliklar = {}
for dosya in sorted(glob.glob(os.path.join(KOK, "CHANGELOG*.md"))):
    with open(dosya, encoding="utf-8") as f:
        basliklar[os.path.basename(dosya)] = ilk_surum_basligi(f)
kontrol("CHANGELOG ilk başlık __version__",
        bool(basliklar) and all(surum_no(b) == S for b in basliklar.values()), f"{S} vs {basliklar}")

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
