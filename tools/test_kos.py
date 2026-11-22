#!/usr/bin/env python3
"""Test takımlarını PARALEL koşar (her takım kendi geçici dizini + kendi görünmez masaüstüyle yalıtılı: tests/_yalitim.py).

Kullanım:
  python3 tools/test_kos.py                 # tüm tests/test_*.py, 4 işçi
  python3 tools/test_kos.py -j 3 test_web test_mcp
  python3 tools/test_kos.py --tur xvfb      # DESKHAND_ARKA_TUR=xvfb ile
  python3 tools/test_kos.py --degisen main  # yalnız `git diff main` ile değişen dosyalara dokunan takımlar (kaba eşleme)

Takım dosyasının ilk 40 satırında `test_kos: tek-basina` işareti varsa o takım paralel havuzdan SONRA tek başına koşar
(gerçek sistemi önce/sonra ölçen takımlar: X ekran numaraları, kullanıcının gerçek ses sunucusu — paralel takımlar
ölçümü bozar).

Ağır iş kuralı: tek başına çağırmayın, `agir-is python3 tools/test_kos.py` (bellek kafesi). İşçi sayısı en çok 4.
Çıkış kodu: hepsi geçtiyse 0, değilse 1. En yavaş 5 takım sonda listelenir (kısaltma adayı).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import time

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OZET = re.compile(r"\d+/\d+ .*(geçti|testi)")
HATA = re.compile(r"✗|KALDI|Traceback|Error:")


def takimlar() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(os.path.join(KOK, "tests")) if f.startswith("test_") and f.endswith(".py"))


def tek_basina_mi(t: str) -> bool:
    try:
        with open(os.path.join(KOK, "tests", t + ".py"), encoding="utf-8") as f:
            return any("test_kos: tek-basina" in next(f, "") for _ in range(40))
    except OSError:
        return False


def degisen_takimlar(taban: str) -> list[str]:
    """Kaba eşleme: değişen modül adı (deskhand/x.py → x) takım dosyasında geçiyorsa o takım; test dosyası değiştiyse
    kendisi; tests/_yalitim.py, arka_ortak.py, eylem.py gibi çekirdek dosyalar değiştiyse HEPSİ."""
    cikti = subprocess.run(["git", "-C", KOK, "diff", "--name-only", taban], capture_output=True, text=True).stdout
    dosyalar = [d for d in cikti.split() if d.endswith(".py")]
    hepsi = takimlar()
    CEKIRDEK = {"tests/_yalitim.py", "deskhand/arka_ortak.py", "deskhand/eylem.py", "deskhand/api.py", "deskhand/hata.py"}
    if any(d in CEKIRDEK for d in dosyalar):
        return hepsi
    secim = set()
    for d in dosyalar:
        ad = os.path.splitext(os.path.basename(d))[0]
        if d.startswith("tests/test_"):
            secim.add(ad)
            continue
        for t in hepsi:
            try:
                with open(os.path.join(KOK, "tests", t + ".py"), encoding="utf-8") as f:
                    if re.search(rf"\b{re.escape(ad)}\b", f.read()):
                        secim.add(t)
            except OSError:
                pass
    return sorted(secim)


def kos(t: str, zaman: int, env: dict) -> tuple[str, int, float, str, list[str]]:
    bas = time.monotonic()
    try:
        p = subprocess.run([sys.executable, os.path.join("tests", t + ".py")], cwd=KOK, env=env, capture_output=True,
                           text=True, timeout=zaman)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), 124
        out += f"\nZAMAN AŞIMI ({zaman} sn)"
    sure = time.monotonic() - bas
    ozet = [s for s in out.splitlines() if OZET.search(s)]
    hatalar = [s[:200] for s in out.splitlines() if HATA.search(s)][:6] if rc else []
    return t, rc, sure, (ozet[-1] if ozet else (out.strip().splitlines() or [""])[-1][:150]), hatalar


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("takim", nargs="*")
    a.add_argument("-j", type=int, default=4, help="paralel işçi (1-4)")
    a.add_argument("--tur", choices=("kwin", "xvfb"), help="DESKHAND_ARKA_TUR")
    a.add_argument("--zaman", type=int, default=600, help="takım başına zaman aşımı (sn)")
    a.add_argument("--degisen", metavar="TABAN", help="yalnız git diff TABAN ile ilgili takımlar")
    g = a.parse_args()
    liste = g.takim or (degisen_takimlar(g.degisen) if g.degisen else takimlar())
    if not liste:
        print("koşulacak takım yok")
        return 0
    env = dict(os.environ)
    if g.tur:
        env["DESKHAND_ARKA_TUR"] = g.tur
    os.umask(0o077)
    j = max(1, min(4, g.j))
    bas = time.monotonic()
    sonuc = []
    def yaz(r):
        t, rc, sure, ozet, hatalar = r
        print(f"{'✓' if rc == 0 else '✗'} {t} rc={rc} {sure:.0f}s | {ozet}", flush=True)
        for s in hatalar:
            print("      " + s, flush=True)
        sonuc.append(r)

    tek = [t for t in liste if tek_basina_mi(t)]
    with cf.ThreadPoolExecutor(j) as h:
        for r in h.map(lambda t: kos(t, g.zaman, env), [t for t in liste if t not in tek]):
            yaz(r)
    for t in tek:  # gerçek sistemi ölçenler: havuz bittikten sonra, tek başına
        yaz(kos(t, g.zaman, env))
    kalan = [r for r in sonuc if r[1] != 0]
    print(f"\n{len(sonuc) - len(kalan)}/{len(sonuc)} takım geçti — {time.monotonic() - bas:.0f} sn ({j} işçi"
          f"{', tür ' + g.tur if g.tur else ''})")
    print("en yavaş: " + ", ".join(f"{r[0]} {r[2]:.0f}s" for r in sorted(sonuc, key=lambda r: -r[2])[:5]))
    if kalan:
        print("KALAN: " + " ".join(r[0] for r in kalan))
    return 1 if kalan else 0


if __name__ == "__main__":
    sys.exit(main())
