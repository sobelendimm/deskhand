"""Frame/list race guard shared by the panel preview (gui/onizleme.maskeli_goruntu) and the agent path
(api.goruntu_al). Qt-free: api must not import the GUI.

The forbidden-window list is read BEFORE and AFTER the frame. A window that opens, moves or closes while the frame
is taken is then known at both positions; the caller masks the union and decides what a closed window means (the
agent path drops the frame, the preview masks the old position). Which windows count as forbidden stays with each
caller (api: yasak_mi; preview: title/class patterns). Residual limit: a window that both appears and disappears
between the two reads (shorter than one grab) is not seen.

A read may also carry the geometry of EVERY window (Geometriler.tum): a window that is not forbidden before the
frame (title "Loading…") but forbidden after it may have moved meanwhile; its place before the frame is then masked
too (Z3D review). Every caller whose frame (or text read from it) leaves the process goes through this guard via
api.goruntu_al / gorsel.korumali_goruntu (tests/test_guv_sinif_maske.py keeps the raw grab on an allowlist)."""
from __future__ import annotations

from collections.abc import Callable


class Geometriler(dict):
    """{window id: geometry} of the forbidden windows; .tum = {window id: geometry} of ALL windows of the same read
    (empty when the caller does not know them)."""

    def __init__(self, yasak=(), tum=None):
        super().__init__(yasak)
        self.tum = dict(tum or {})


class ListeOkunamadi(Exception):
    """The forbidden-window list could not be read (before or after the frame): the frame must not be used."""

    def __init__(self, neden: BaseException):
        super().__init__(str(neden))
        self.neden = neden


def iki_okumali_kare(oku: Callable[[], dict], al: Callable[[], object]):
    """oku() → {window id: screen geometry (x, y, w, h)} of the forbidden windows; al() → the frame.
    → (frame, union [(id, geometry)], closed ids). The union holds every geometry seen for a window (before and
    after, duplicates dropped) and, when oku() returns Geometriler, the pre-frame place of a window that became
    forbidden only after the frame. closed = forbidden before the frame, absent from the forbidden list after it
    (closed, or no longer forbidden: the caller tells them apart with its own read).
    A failing oku() raises ListeOkunamadi (before the frame: al() is never called); al() errors propagate as they are."""
    try:
        once = oku()
        once_tum = dict(getattr(once, "tum", None) or {})
        once = dict(once)
    except Exception as e:  # noqa: BLE001 - unreadable list: the frame must not be used (safe side)
        raise ListeOkunamadi(e) from e
    kare = al()
    try:
        sonra = dict(oku())
    except Exception as e:  # noqa: BLE001
        raise ListeOkunamadi(e) from e
    birlesim = [(k, tuple(g)) for k, g in once.items()]
    for k, g in sonra.items():
        if (k, tuple(g)) not in birlesim:
            birlesim.append((k, tuple(g)))
        if k not in once and k in once_tum and (k, tuple(once_tum[k])) not in birlesim:
            birlesim.append((k, tuple(once_tum[k])))  # forbidden only after the frame: where it was before it
    return kare, birlesim, set(once) - set(sonra)
