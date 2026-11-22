"""DENETİM 3 (salt okuma): sistemde MCP open_app'in ONAYSIZ başlatacağı girdiler (girdi_denetle + girdi_guvenilir
geçen) ve bunların Exec programı #! BETİK olanları; betiğin argümanı nasıl kullandığına bakmak için ilk satırlar."""
import glob
import os

import _yalitim  # noqa: F401

from deskhand import uygulama
from deskhand.oturum.cozum import exec_argv


def exec_satiri(yol):
    bolum = None
    try:
        for s in open(yol, errors="replace"):
            s = s.strip()
            if s.startswith("["):
                bolum = s
            elif bolum == "[Desktop Entry]" and s.startswith("Exec="):
                return s[5:].strip()
    except OSError:
        pass
    return None


onaysiz, betikler = [], []
for d in uygulama.SISTEM_UYGULAMA_DIZINLERI:
    for yol in sorted(glob.glob(os.path.join(d, "*.desktop"))):
        ex = exec_satiri(yol)
        if not ex:
            continue
        g = {"yol": yol, "exec": ex, "kimlik": os.path.basename(yol)[:-8], "kategoriler": [], "ucbirimde": False}
        try:
            g["ucbirimde"] = "Terminal=true" in open(yol, errors="replace").read()
        except OSError:
            pass
        if uygulama.girdi_denetle(g) or uygulama.girdi_guvenilir(g):
            continue
        onaysiz.append(g)
        for p in uygulama._exec_programlari(exec_argv(ex)):
            yolp = p if os.path.isabs(p) else __import__("shutil").which(p)
            if yolp and open(os.path.realpath(yolp), "rb").read(2) == b"#!":
                betikler.append((g["kimlik"], ex, os.path.realpath(yolp)))
print(f"onaysız başlatılabilen girdi: {len(onaysiz)}; Exec programı betik olan: {len(betikler)}")
for kimlik, ex, b in betikler:
    print(f"\n== {kimlik} | Exec={ex} | {b}")
    try:
        satirlar = open(b, errors="replace").read().splitlines()
    except OSError:
        continue
    print("   " + satirlar[0])
    for s in satirlar[1:]:
        if any(x in s for x in ('"$@"', "$@", "$1", "$*", "exec ", "eval", "source", " . ")):
            print("   | " + s.strip()[:160])
