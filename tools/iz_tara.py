#!/usr/bin/env python3
"""Personal-trace scanner: keeps user names, home paths, private e-mail addresses and Claude session links out of
the public tree and commit messages.

Usage:  python3 tools/iz_tara.py [--ek FILE] [--ek-zorunlu] [--ileti TEXT] [path…]
  path…        files (or directories, walked recursively) to scan; with neither paths nor --ileti: `git ls-files`
  --ileti      also scan this text (a commit message). Every line is scanned, '#' lines included: `git commit -m`
               (cleanup=whitespace) keeps them in the commit.
  --ek FILE    extra private patterns, one literal word per line ('#' comments, blank lines skipped), matched
               case-insensitively (Turkish I/ı/İ/i folded together). The file lives OUTSIDE the repository
               (~/.config/deskhand/iz-desenleri.txt); a missing file is a warning, not an error. Findings never
               print the matched word, so the private list does not leak into logs.
  --ek-zorunlu fail closed: no --ek, a missing/unreadable --ek file or one without patterns is exit 2
               (the local commit hooks use it; CI has no private file and runs without it).

Output: one line per finding, `file:line · kind`  (kind: home-path, email, claude-tmp, session-id, session-trailer,
extra-pattern; machine-read, not translated). Exit 0 = clean, 1 = findings, 2 = usage error / required --ek missing.

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
# any case: /home/<n>, ../home/<n>, /Users/<n>, URL-encoded %2Fhome%2F<n>; Windows C:\Users\<n> (also escaped
# as C:\\Users\\<n>, or written with /)
EV = re.compile(r"(?:(?<![\w~-])/|%2f)(?:home|users)(?:/|%2f)([\w.-]+)"
                r"|(?<![\w])[a-z]:(?:\\{1,2}|/)users(?:\\{1,2}|/)([\w.-]+)", re.IGNORECASE)
EPOSTA = re.compile(r"(?<![\w.+-])([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)")
# exact example domains (also Turkish "örnek") and the GitHub noreply domain; no subdomains
SERBEST_ALAN = {f"{a}.{t}" for a in ("example", "örnek") for t in ("com", "org", "net")} | {"users.noreply.github.com"}
# one label + reserved TLD (shop.test); more labels could hide a real address in front (name at gmail.com.test)
AYRILMIS = re.compile(r"[\w-]+\.(?:test|invalid|example|localhost)")
DESENLER = [
    ("claude-tmp", re.compile(r"\bclaude-\d{3,}(?![\w-])")),  # /tmp/claude-<uid>/… scratch dirs
    # Claude session ids are session_01 + ~24 chars: a truncated one is still caught through the 01 prefix, while
    # code words such as session_identifier (no 01 prefix, under 16 chars) are not
    ("session-id", re.compile(r"(?<![\w])session_(?:01[A-Za-z0-9]{6,}|[A-Za-z0-9]{16,})")),
    ("session-trailer", re.compile(r"Claude[- ]Session\s*:", re.IGNORECASE)),
]


def kisa(metin: str) -> str:
    """Fold case the Turkish-safe way: I, ı, İ and i all compare equal."""
    return metin.replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()


def eposta_serbest(yerel: str, alan: str) -> bool:
    """Known non-personal address forms only."""
    yerel, alan = yerel.lower(), alan.lower()
    if yerel in ("noreply", "no-reply") or alan in SERBEST_ALAN or AYRILMIS.fullmatch(alan):
        return True
    if yerel == "git":  # ssh remotes: git at github.com:owner/repo.git
        return True
    if yerel == "user" and re.fullmatch(r"\d+\.service", alan):  # systemd unit: user@<uid>.service
        return True
    return bool(re.fullmatch(r"[\w-]+\.xpi", alan))  # Firefox extension file: <id>@<x>.xpi


def ek_oku(yol: str) -> list[str] | None:
    """Patterns of one --ek file; None when it is missing or unreadable (a warning is printed)."""
    try:
        with open(os.path.expanduser(yol), encoding="utf-8") as f:
            satirlar = f.read().splitlines()
    except FileNotFoundError:
        print(f"iz_tara: warning: --ek file not found, only general patterns: {yol}", file=sys.stderr)
        return None
    except (OSError, UnicodeDecodeError) as e:
        print(f"iz_tara: warning: cannot read --ek file {yol}: {type(e).__name__}", file=sys.stderr)
        return None
    return [kisa(s.strip()) for s in satirlar if s.strip() and not s.strip().startswith("#")]


def satir_tara(satir: str, ekler: list[str]) -> list[str]:
    turler = []
    if any((m.group(1) or m.group(2)).lower() not in SERBEST_EV for m in EV.finditer(satir)):
        turler.append("home-path")
    if any(not eposta_serbest(m.group(1), m.group(2)) for m in EPOSTA.finditer(satir)):
        turler.append("email")
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="iz_tara.py", description="personal-trace scanner")
    p.add_argument("--ek", action="append", default=[], metavar="FILE", help="extra private pattern file")
    p.add_argument("--ek-zorunlu", action="store_true", help="exit 2 unless every --ek file is readable with patterns")
    p.add_argument("--ileti", action="append", default=[], metavar="TEXT", help="commit message text to scan")
    p.add_argument("yollar", nargs="*", metavar="path")
    a = p.parse_args(argv)

    okunan = [ek_oku(yol) for yol in a.ek]
    ekler = [e for liste in okunan if liste for e in liste]
    if a.ek_zorunlu and (not a.ek or None in okunan or not ekler):
        print("iz_tara: --ek-zorunlu: private pattern file missing, unreadable or empty; refusing to pass",
              file=sys.stderr)
        return 2
    yollar = a.yollar
    if not yollar and not a.ileti:
        r = subprocess.run(["git", "ls-files", "-z"], capture_output=True, timeout=60)
        if r.returncode != 0:
            print("iz_tara: not a git checkout; give paths", file=sys.stderr)
            return 2
        yollar = [d for d in r.stdout.decode().split("\0") if d]

    bulgular = []
    for metin in a.ileti:
        bulgular += metin_tara("<ileti>", metin, ekler)
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
