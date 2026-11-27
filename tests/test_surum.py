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

basliklar = {}
for dosya in sorted(glob.glob(os.path.join(KOK, "CHANGELOG*.md"))):
    for satir in open(dosya, encoding="utf-8"):
        if satir.startswith("## "):
            basliklar[os.path.basename(dosya)] = satir[3:].strip()
            break
kontrol("CHANGELOG ilk başlık __version__",
        bool(basliklar) and all(b.split()[0] == S for b in basliklar.values()), f"{S} vs {basliklar}")

print(f"\n{gecen}/{toplam} geçti")
sys.exit(0 if gecen == toplam else 1)
