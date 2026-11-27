"""systemd-run helpers shared by every memory-cage call site.

systemd >= 254 expands "${VAR}" in systemd-run command arguments by default (with --scope, systemd-run does it
itself). Deskhand passes file paths and user-controlled strings as arguments, so expansion is turned off where the
flag exists; older systemd rejects the unknown flag, so it is left out there (and when the version cannot be read).
"""
from __future__ import annotations

import re
import subprocess

ILK_SURUM = 254
_BAYRAK = "--expand-environment=no"
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


def genisleme_kapali() -> list[str]:
    """["--expand-environment=no"] on systemd >= 254, otherwise []. Cached for the process lifetime; returns a copy."""
    if "b" not in _onbellek:
        s = _surum()
        _onbellek["b"] = [_BAYRAK] if s is not None and s >= ILK_SURUM else []
    return list(_onbellek["b"])
