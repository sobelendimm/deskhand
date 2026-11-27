#!/usr/bin/env python3
"""Personal-trace scanner: keeps user names, home paths, private e-mail addresses and Claude session links out of
the public tree and commit messages.

Usage:  python3 tools/iz_tara.py [--ek FILE] [--ileti TEXT] [path…]
  path…      files (or directories, walked recursively) to scan; with neither paths nor --ileti: `git ls-files`
  --ileti    also scan this text (a commit message); lines starting with '#' and everything after git's
             scissors line are ignored, as git itself drops them
  --ek FILE  extra private patterns, one literal word per line ('#' comments, blank lines skipped), matched
             case-insensitively (Turkish I/ı/İ/i folded together). The file lives OUTSIDE the repository
             (~/.config/deskhand/iz-desenleri.txt); a missing file is a warning, not an error. Findings never
             print the matched word, so the private list does not leak into logs.

Output: one line per finding, `file:line · kind`  (kind: home-path, email, claude-tmp, session-id, session-trailer,
extra-pattern; machine-read, not translated). Exit 0 = clean, 1 = findings, 2 = usage error.

General patterns (in the repository) are written so that this file does not match itself.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# placeholder home names allowed in examples and tests ("kullanici"/"kisi" = Turkish "user"/"person")
SERBEST_EV = {"u", "x", "user", "kullanici", "kisi"}
EV = re.compile(r"(?<![\w.~-])/home/([\w.-]+)")
EPOSTA = re.compile(r"(?<![\w.+-])[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
# example domains (also Turkish "örnek"), reserved TLDs, Firefox extension ids (name@x.xpi), systemd units
SERBEST_ALAN = re.compile(r"(?:^|\.)(?:(?:example|örnek)\.(?:com|org|net)|users\.noreply\.github\.com)$"
                          r"|\.(?:test|invalid|example|localhost|xpi|service|slice|scope)$", re.IGNORECASE)
DESENLER = [
    ("claude-tmp", re.compile(r"\bclaude-\d{3,}(?![\w-])")),           # /tmp/claude-<uid>/… scratch dirs
    ("session-id", re.compile(r"(?<![\w])session_[A-Za-z0-9]{16,}")),  # Claude session ids
    ("session-trailer", re.compile(r"Claude-Session\s*:", re.IGNORECASE)),
]
MAKAS = "# ------------------------ >8 ------------------------"


def kisa(metin: str) -> str:
    """Fold case the Turkish-safe way: I, ı, İ and i all compare equal."""
    return metin.replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()


def ek_oku(yol: str) -> list[str]:
    try:
        with open(os.path.expanduser(yol), encoding="utf-8") as f:
            satirlar = f.read().splitlines()
    except FileNotFoundError:
        print(f"iz_tara: warning: --ek file not found, only general patterns: {yol}", file=sys.stderr)
        return []
    return [kisa(s.strip()) for s in satirlar if s.strip() and not s.strip().startswith("#")]


def satir_tara(satir: str, ekler: list[str]) -> list[str]:
    turler = []
    if any(m.group(1) not in SERBEST_EV for m in EV.finditer(satir)):
        turler.append("home-path")
    for m in EPOSTA.finditer(satir):
        yerel = m.group(0).split("@", 1)[0].lower()
        if "noreply" not in yerel and not SERBEST_ALAN.search(m.group(1)):
            turler.append("email")
            break
    turler += [tur for tur, d in DESENLER if d.search(satir)]
    if ekler:
        k = kisa(satir)
        if any(e in k for e in ekler):
            turler.append("extra-pattern")
    return turler


def metin_tara(ad: str, metin: str, ekler: list[str]) -> list[str]:
    return [f"{ad}:{no} · {tur}" for no, satir in enumerate(metin.splitlines(), 1) for tur in satir_tara(satir, ekler)]


def dosyalari_ac(yollar: list[str]):
    for yol in yollar:
        if os.path.isdir(yol):
            for kok, dizinler, adlar in os.walk(yol):
                dizinler[:] = sorted(d for d in dizinler if d != ".git")
                for a in sorted(adlar):
                    yield os.path.join(kok, a)
        else:
            yield yol


def dosya_oku(yol: str) -> str | None:
    try:
        with open(yol, "rb") as f:
            veri = f.read()
    except FileNotFoundError:
        print(f"iz_tara: warning: file not found, skipped: {yol}", file=sys.stderr)
        return None
    except OSError as e:
        print(f"iz_tara: warning: cannot read {yol}: {e}", file=sys.stderr)
        return None
    if b"\0" in veri[:8192]:
        return None  # binary
    return veri.decode("utf-8", errors="replace")


def ileti_temizle(metin: str) -> str:
    satirlar = []
    for s in metin.splitlines():
        if s.startswith(MAKAS):
            break
        satirlar.append("" if s.startswith("#") else s)  # keep numbering
    return "\n".join(satirlar)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iz_tara.py", description="personal-trace scanner")
    p.add_argument("--ek", action="append", default=[], metavar="FILE", help="extra private pattern file")
    p.add_argument("--ileti", action="append", default=[], metavar="TEXT", help="commit message text to scan")
    p.add_argument("yollar", nargs="*", metavar="path")
    a = p.parse_args(argv)

    ekler = [e for yol in a.ek for e in ek_oku(yol)]
    yollar = a.yollar
    if not yollar and not a.ileti:
        r = subprocess.run(["git", "ls-files", "-z"], capture_output=True, timeout=60)
        if r.returncode != 0:
            print("iz_tara: not a git checkout; give paths", file=sys.stderr)
            return 2
        yollar = [d for d in r.stdout.decode().split("\0") if d]

    bulgular = []
    for metin in a.ileti:
        bulgular += metin_tara("<ileti>", ileti_temizle(metin), ekler)
    n = 0
    for yol in dosyalari_ac(yollar):
        metin = dosya_oku(yol)
        if metin is None:
            continue
        n += 1
        bulgular += metin_tara(yol, metin, ekler)
    for b in bulgular:
        print(b)
    print(f"iz_tara: {n} files, {len(a.ileti)} messages, {len(bulgular)} findings", file=sys.stderr)
    return 1 if bulgular else 0


if __name__ == "__main__":
    sys.exit(main())
