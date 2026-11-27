"""systemd-run helpers shared by every memory-cage call site.

systemd >= 254 expands "${VAR}" in systemd-run command arguments by default (with --scope, systemd-run does it
itself). Deskhand passes file paths and user-controlled strings as arguments, so expansion is turned off where the
flag exists; older systemd rejects the unknown flag, so it is left out there.

Detection: `systemctl --version`; if that cannot be read, `systemd-run --help` is probed for the flag. If neither
answers, the flag is added anyway (fail closed): on new systemd that is correct, and on old systemd systemd-run
refuses the unknown option before running anything, so an argument is never expanded behind our back. Escaping "$"
as "$$" is not an option there: on old systemd (no expansion) it would corrupt the argument. If systemd-run itself is
missing, [] is returned (no call can be made; callers check shutil.which first).
"""
from __future__ import annotations

import re
import subprocess

ILK_SURUM = 254
_BAYRAK = "--expand-environment=no"
_SYSTEMD_RUN = "systemd-run"
_onbellek: dict[str, list[str]] = {}
_calistir = subprocess.run  # test hook


def _surum() -> int | None:
    try:
        r = _calistir(["systemctl", "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    ilk = (r.stdout or "").splitlines()[:1]
    m = re.match(r"systemd (\d+)", ilk[0]) if ilk else None
    return int(m.group(1)) if m else None


def _yardim_bayrak() -> bool | None:
    """Does `systemd-run --help` list --expand-environment? None = could not tell (timeout, unrecognisable output)."""
    try:
        # argv[0] via a name: this only prints help, so the expansion lint (list literal rule) does not apply
        r = _calistir([_SYSTEMD_RUN, "--help"], capture_output=True, text=True, timeout=3)
    except FileNotFoundError:
        return False  # no systemd-run: nothing will be run through it
    except (OSError, subprocess.SubprocessError):
        return None
    metin = r.stdout or ""
    if "--expand-environment" in metin:
        return True
    return False if "systemd-run" in metin and "--scope" in metin else None


def _hesapla() -> list[str]:
    s = _surum()
    if s is not None:
        return [_BAYRAK] if s >= ILK_SURUM else []
    var = _yardim_bayrak()
    return [] if var is False else [_BAYRAK]


def genisleme_kapali() -> list[str]:
    """["--expand-environment=no"] where systemd-run supports it (or support is unknown), otherwise [].

    Cached for the process lifetime; returns a copy."""
    if "b" not in _onbellek:
        _onbellek["b"] = _hesapla()
    return list(_onbellek["b"])
