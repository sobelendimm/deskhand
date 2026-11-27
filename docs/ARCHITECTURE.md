# Deskhand — Architecture and the contract between modules

> **Türkçe sürüm:** [ARCHITECTURE.tr.md](ARCHITECTURE.tr.md) (the original text; the code comments and most identifiers are in Turkish).
> This document is the internal contract of Deskhand: the package layout, the `ArkaUc` (backend) interface shared
> by the real-desktop (KDE) and virtual-desktop (Xvfb/KWin) backends, the input language, target selection, the
> safety rules, the exit codes, the working rules for contributors, and the human-approval protocol. Source code
> refers to sections by number (§2, §4, §5, §6, §8), so the numbering is stable. Module, function and file names
> are kept exactly as in the code (many are Turkish: `arka_uc` = backend, `guvenlik` = safety, `eylem` = action,
> `onay` = approval, `masalar` = desktops).

If a need arises that changes an interface, do not change the code unilaterally: first write it into §7 as a design
decision and settle it with the project maintainer.

## 1. Package layout

```
deskhand/
  __init__.py      __version__
  __main__.py      python -m deskhand → cli.main()
  yollar.py        ALL file paths live here. Overridable through environment variables (for tests):
                   DESKHAND_CONFIG_DIR (default ~/.config/deskhand), DESKHAND_STATE_DIR (~/.local/state/deskhand),
                   DESKHAND_CACHE_DIR (~/.cache/deskhand), DESKHAND_DATA_DIR (~/.local/share/deskhand),
                   DESKHAND_RUNTIME_DIR ($XDG_RUNTIME_DIR/deskhand).
                   MIGRATION: if the directories of the predecessor `ekran` tool (~/.config/ekran,
                   ~/.local/share/ekran/simgeler and ~/.local/state/ekran) exist and the new ones do not, they are
                   COPIED on first start (not moved; the old tool keeps working).
  hata.py          Dur(kod, mesaj) + exit codes (§5)
  gunluk.py        log (0600; the STATE/CACHE directories are 0700, fixed at start-up) + cleanup
  guvenlik.py      forbidden windows, sensitive button, payment page, approval for risky keys/terminal commands,
                   application access levels, title/class lock, denetle(), the DUR (stop) switch
  insan.py         Wayland activity watcher (ekran-etkinlik C helper) + insan_bekle
  kendi.py         the agent's own client: ancestor process set (/proc), tmux clients, foreground process (§4)
  ucbirim.py       terminal Enter gate: reading the input line (AT-SPI/OCR) + typing buffer (§4)
  ocr.py           oku, satirla, ara, derin_oku, cache, preprocessing
  gorsel.py        icon (NCC), colour regions, grid
  eylem.py         tikla/yaz/tus/kaydir/bas/surukle/dizi: the upper layer, INDEPENDENT of the backend
  akis.py, erisim.py (AT-SPI), uygulama.py (ac)
  web.py           elements of a web page: reading from the browser's accessibility tree (§9); MCP
                   read_text(source="web"), CLI `web`, the web path of click-element
  cli.py           argparse; command names in English + Turkish aliases. `deskhand --help` sub-command table
                   (`KISA_ACIKLAMA`); `screenshot` without an id (`varsayilan_foto_hedefi`: the whole desktop on the
                   invisible desktop, the active window + real-screen lock 17 in the foreground), `windows` without a
                   pattern (forbidden window titles are masked)
  gezin.py         `goto ID URL`: address-bar path (ctrl+l → address → Return) through `api.tus`/`api.yaz`; NO new
                   safety path (title lock, sensitive page, CAPTCHA gate, DUR, human priority all unchanged); http(s) only
  dosya_sec.py     `choose-file ID PATH`: ctrl+l → AT-SPI focused input (erisim.odakli_metin) → path → the value is
                   READ BACK (≠ path → Dur 8, no Enter) → Return → did the dialog close; in the background only an
                   XDG/test share
  surum.py         installed version on disk ↔ running code: get_status `stale_server`, doctor `deskhand mcp` processes
  ipucu.py         complete runnable command in hints (`deskhand --desktop-name NAME --background tree K`)
  arka_uc/__init__.py   ArkaUc interface + sec(target)
  arka_uc/kde.py        kdotool + dotool + kscreen-doctor (+ spectacle only as a screenshot fallback)
  arka_uc/kde_goruntu.py  screenshots: yardimci/deskhand-goruntu (C, sd-bus) → KWin ScreenShot2
                        (org.kde.KWin.ScreenShot2, raw pixels over a pipe; ~8 ms). Authorisation: KWin < 6.8 matches
                        the caller's /proc/<pid>/exe path against the same .desktop file as the first word of Exec=
                        and looks for the interface in X-KDE-DBUS-Restricted-Interfaces → install.sh installs
                        ~/.local/share/applications/deskhand-goruntu.desktop (KWin 6.8 removed the check).
                        If the helper is not built/not authorised, the internal fallback is spectacle (logged).
  arka_uc/sanal.py      the Xvfb type of the background desktop: Xvfb + python-xlib
  arka_uc/kwin.py       the KWin type of the background desktop: kdotool (+ KWin scripts) + yardimci/deskhand-eis (EIS input)
                        + deskhand-goruntu + wl-copy/wl-paste, all through the session's private data path / Wayland socket
  masaustu.py      lifecycle of the background desktop (the SINGLE entry point, two types): type selection,
                   start/stop/status/list, application launch; state is masalar.durum_yolu() ("tur": "kwin" | "xvfb";
                   the default desktop is RUNTIME_DIR/sanal.json); `ad` parameter (None = context), automatic desktop cleanup
  masalar.py       multiple invisible desktops: name validation (`[a-z0-9][a-z0-9-]{0,15}`, "" = default, `gorev`
                   reserved), context (`secili()`: masa_sabit > DESKHAND_MASAUSTU > ""), per-desktop paths
                   ("" → the old paths UNCHANGED; named → RUNTIME_DIR/masa/<name>/{sanal.json, sanal.lock, devral,
                   girdi.lock, sahip, oturum/}), ownership + access gate, `[masaustu] azami`. The singular path constants
                   ("sanal.json", "sanal.lock", "devral") live ONLY in masaustu.py/masalar.py (tests/test_masalar.py checks)
  kwin_oturum.py   building blocks of the KWin type: kwin_wayland --virtual + private D-Bus + private Wayland socket +
                   XWayland, safety gates (guvenlik_kapilari, baglanti_denetle), GPU selection, readiness check, the Eis class
  arka_ortak.py    internal building blocks COMMON to both types: memory cage, priority, empty audio output, base of the
                   application environment (ortam_tabani), private D-Bus configuration, Xauthority, starting the priority guard
  bellek_bekcisi.py   memory watch of the invisible desktop: `memory_warning` at 80% (anonymous + shared), idle Firefox-only restart with session restore at 85% (README "Memory watch" has the limits), `memory.reclaim` at 60%
  oncelik_bekcisi.py  guard that keeps every thread in the cage at nice >= 10 / non-realtime / idle I/O;
                   if the display server (KWin/Xvfb) dies from SIGKILL/OOM it closes the session (cage, X socket/lock, directory)
  ses_bekcisi.py   (no longer started: background applications never reach the user's sound server)
  ses.py           SESSION-PRIVATE sound server (pipewire + wireplumber `policy` + pipewire-pulse; no hardware, only the
                   empty `deskhand-sessiz` output + its monitor): set-up/tear-down/health, client environment
  dinleme.py       core of `listen`: in-memory recording from the monitor of the private output (parec) → whisper-cli → text
  pano_sahibi.py   helper process that serves the CLIPBOARD selection of the virtual desktop (in the cage, started on the
                   first clipboard write)
  oturum/          session bridge (see docs/SESSIONS.md)
  mesgul.py        protection for "is the user busy" (game / film)
  onay.py          human-approval protocol (§8): request file + the panel's verified approval channel (Unix socket)
  onay_hedef.py    summary of the approved target (id, title, geometry, region image) + post-approval verification (§8)
  liste_koruma.py  forbidden/level lists, approval scope, account sessions: the panel is the authoritative source (memory,
                   write-back, marker, reading over the channel; §4)
  girdi_merkezi.py the single dotool kept ready inside the panel + RUNTIME_DIR/girdi.sock (no Qt; §2, §4)
  gui/             panel, tray, approval dialog; gui/gorev.py = the "Task" tab (task box, live steps, live image of the
                   invisible desktop, history). A general exception catcher at panel start-up
                   (panel.istisna_yakalayici_kur: sys/threading excepthook → log + tray warning; no PyQt6 SIGABRT)
  gorev.py         task runner (no Qt): has the task the user typed carried out with `claude -p --output-format stream-json`
                   ONLY through the `deskhand mcp --desktop background` tools. The privilege boundary is in argv:
                   temporary --mcp-config (a single server deskhand-gorev, env DESKHAND_GERCEK_EKRAN=kapali) +
                   --strict-mcp-config + --allowedTools mcp__deskhand-gorev__* + built-in tools via --disallowedTools +
                   --permission-mode dontAsk + --setting-sources project; empty temporary working directory; prompt from
                   stdin; events {tur, zaman, ozet}; history STATE_DIR/gorevler/*.jsonl (0600, last 50); only one task at a
                   time (flock RUNTIME_DIR/gorev.lock); settings [gorev] model / azami_dakika / azami_tur; MCP server IN
                   TASK MODE (§11)
  gorev_kipi.py    task-mode rules (DESKHAND_GOREV=1): browser policy, site permission, open_app filter, masking,
                   task-desktop gate, window limit, identity-variable filter (§11)
  fark.py          screen difference before/after an action (changed, changed_region, changed_ratio; NumPy, cursor-tolerant)
  dongu.py         loop breaker: warning at the 3rd fruitless repeat of the same action, refusal after 5 (MCP, per-session memory)
  gozlem.py        MCP observe: normalising elements, query/ancestors, OCR extraction, snapshot cache
                   (snapshot_id, ref), difference (since), numbered image (§10)
  gonderim.py      counter of the input actually sent during an action (thread-specific; MCP `sent`, §10)
  mcp_sunucu.py    MCP surface
bin/ekran          compatibility: `python3 -m deskhand "$@"` (Turkish commands unchanged)
tests/             screenless tests: test_ocr.py, test_mantik.py ...; with a screen: tests/ekranli/ (manual only)
```

## 2. The ArkaUc interface (deskhand/arka_uc/__init__.py)

Coordinates: `geometri()` and `goruntu()` are SCREEN pixels (the backend's own screen). The upper layer converts window
coordinates to screen coordinates with `geometri()`.

Window id: a backend-specific string. kde: `{uuid}`; sanal: `arka:0x1a00007` for the Xvfb type, `arka:{uuid}` for the
KWin type (always with the `arka:` prefix, so an id cannot go to the wrong backend). The special id `EKRAN` = desktop
mode (the whole screen).

**The two types of the background desktop.** Two backends sit behind the `sanal` target: the isolated KWin session
(`arka_uc/kwin.py`, `KwinArkaUc`) and Xvfb + openbox (`arka_uc/sanal.py`, `SanalArkaUc`). Both have `ad` = `"sanal"`;
the type is in the `tur` attribute ("kwin" | "xvfb"). The upper layer (eylem, guvenlik, erisim, MCP, CLI) does not know
the type; commands, MCP tools, id prefix and exit codes are the same. In both types the geometry is the CLIENT area
(without title bar/frame; in the KWin type `clientGeometry` through a KWin script); `tasi`/`boyutlandir` give the corner/size
of the client area.

| Method | Returns | Note |
|---|---|---|
| `ad` | "kde" \| "sanal" | `sanal` backends also have `tur`: "kwin" \| "xvfb" |
| `pencere_coz(arg)` | id | the name pattern must match a single window (none: Dur 8, several: Dur 5) |
| `pencereler(desen=None)` | [(id, title, (x,y,w,h))] | the `bul` (find) command |
| `geometri(k)` | (x, y, w, h) | Dur 8 if missing |
| `baslik(k)`, `sinif(k)` | str | |
| `aktif()` | id \| "" | empty = could not be verified → the caller STOPS |
| `one_getir(k)` | None | Dur 3 if it does not become active |
| `kapat(k)` | None | |
| `fare()` | (x, y, id_underneath) | |
| `baslik_ve_fare(k)` | (title, fare()) | a single call for the watcher |
| `ekran_alani()` | (x0, y0, x1, y1) | |
| `goruntu()` | PIL.Image (RGB, whole screen) | the window crop is made in the upper layer |
| `girdi(etiket, gizli, etk, denetle)` | Girdi object | `denetle(k, desen)` = the upper layer's safety check; before every line `hata.dur_denetle()` + `denetle()` |
| `insan_var_mi()` | bool | kde: Wayland activity; sanal: True if "Take over" (Devral) is on |
| `baslat(argv, env=None, cikti=None)` | Popen | starts the application in THIS backend's session |
| `atspi_adresi()` | str \| None | accessibility bus path |

Optional (defaulted) methods: `kimlikler()`, `klavye_duzeni()`, `yazilabilir_mi(c)`, `gecerli_tuslar()`,
`pid(k)`, `etkinlestir(k)`, `etkinlik()`, `oturum_veri_yolu()` (the session data path of org.a11y.Bus; None = the user's
session), `ekran_korumasi(ne)` (kde: game/film → 15; called by paths that send no input but still affect the application).

Window management (optional; default = not supported → Dur 9): `tasi(k, x, y)`, `boyutlandir(k, w, h)`,
`kucult(k)` (minimise), `buyut(k)` (fill the work area), `geri_yukle(k)` (from minimised/maximised back to normal); returns None.
KWin type: KWin scripts (`kdotool kwinscript`, private data path) — move/resize in terms of the client area, the state
(`pencere_durumu`: hidden/maximized) is verified (at most ~1 s, like the Xvfb type, otherwise Dur 9).
Coordinates are screen pixels. The checks are in the upper layer (`eylem.pencere_yonet`: DUR 13, forbidden 10, -s/-b lock 4,
target position/size outside the screen area 2); the kde backend additionally applies the same screen protection as
`one_getir` (15/12).
kde: kdotool `windowmove`/`windowsize`/`windowminimize`/`windowstate`; sanal: EWMH (`_NET_MOVERESIZE_WINDOW`,
`_NET_WM_STATE`, `WM_CHANGE_STATE`).

**Clipboard (optional; default Dur 9 "not supported"):** `pano_oku() -> str | None` (text; empty/non-text = None),
`pano_yaz(metin, hassas=True)` ("" = clear; `hassas` = must not be written to the clipboard manager history; the DUR and
foreground protection are HERE), `pano_yedekle()` → opaque snapshot (before typing by pasting; if it cannot be read, Dur 9 →
the upper layer types letter by letter) and `pano_geri_yukle(yedek) -> warning | None` (UNCHECKED: the old clipboard must
come back even on DUR/interruption). kde: `wl-paste`/`wl-copy` (`--sensitive`; a non-text clipboard is restored with its
primary MIME type). sanal: the X11 selection lives in its owner → the helper `deskhand/pano_sahibi.py`, started on first
use in the desktop's cage (python-xlib, ICCCM + INCR; 0600 `pano.sock` in the working folder; a TOTAL of 5 s per
connection, header ≤ 64 bytes, if `YAZ n` has n > AZAMI_VERI then "hata cok-buyuk" without reading the data); reading is
in-process. KWin type: `wl-copy`/`wl-paste` with the session's ABSOLUTE Wayland socket and a minimal environment (none of
the user's variables); the server child of `wl-copy` lives in the desktop's cage; reading at most 32 MB, writing at most
64 MB. The three backends never touch each other's clipboard.

`baslat(argv, env, cikti)`: in both backends `env` holds the variables to be ADDED to / changed in `os.environ` (not the full
environment). For the virtual desktop, the desktop values (DISPLAY, private D-Bus, audio...) always take precedence.

**Girdi object:** `gonder(k, desen, *satirlar)` (before every call `guvenlik.denetle`, right after it
`guvenlik.girdi_seviye_denetle(k, satirlar)`: application access level, §4), `zorla(satir)` (release;
unchecked, even on interruption), `ham(satir)`, `izle(k, desen)` / `izle_bitir()` (watcher), `etk_denetle()`,
`insan_kontrol()`, `kapat()`.

**Input language = the dotool line language** (both backends understand the same lines):
`mouseto FX FY` (0..1 fraction, whole screen), `buttondown|buttonup|click left|right|middle`, `key K`,
`keydown K`, `keyup K` (K: `ctrl+s`, `enter`, `leftshift`…), `type TEXT`, `wheel N` (positive = up),
`hwheel N` (positive = right), `typedelay MS`, `typehold MS`. The Xvfb type translates them to XTEST (including Turkish
characters: xkb layout `tr` or keysym mapping). The KWin type hands them to the persistent `deskhand-eis` helper
(libei, KWin EIS): ONE connection per process (shared under a lock), `type` is ALL OR NOTHING (a character not in the
session's keyboard map → `hata yazilamaz` → Dur 1; `yazilabilir_mi` answers from the same map without sending input, and the
upper layer falls back to the clipboard path for such characters). Helper: the wait before the first button/scroll after a
movement can be enabled with `hareketbekle MS` (default 0: on KWin 6.8.3 there was no wrong surface in 50 fast two-window
clicks, and the wait added +20 ms per click); if the cursor is already on the target it first moves to a neighbouring pixel
("parked cursor"; a cheap precaution); scrolling uses discrete units of 120 + `scroll_stop`; when the keyboard device
changes (layout change), anything still held down with the old one is released with press+release from the new device;
on close, ei_ping synchronisation + `disconnect(cookie)`.

**Atomicity.** The DUR check is made per `gonder()` call, not per line: the lines of one call are ATOMIC (the two clicks
of a double-click are not split). In letter-by-letter typing (`ham`) the check is made before every letter. A watcher
interruption (the `kesildi` flag) stays until the next `izle()` (the same in both backends).

**Input hub.** While the panel is open a single dotool is kept READY inside it (`deskhand/girdi_merkezi.py`); kde sends its
`Girdi` lines to it over `RUNTIME_DIR/girdi.sock` and does not open its own dotool (no ~0.66 s device set-up per command).
Protocol: `merhaba 1 <layout> <variant|->` → `tamam 1 <pid>`; `parti <n>` + n lines → `tamam` | `mesgul <s>` |
`hata <code> <message>`; `bekle` → when the input is finished, `tamam <n>` + n dotool warnings. One `gonder()` call is ONE
batch (atomic, never mixed with the lines of another connection). ALL the checks on the client side (DUR, `denetle`,
foreground protection, human priority, watcher, the agent's own client, session lock) stay on the client unchanged; on
`mesgul` the client redoes all the checks and retries. If there is no hub or the handshake fails, `Girdi` opens its own dotool
(internal fallback: when the panel is closed). If the keyboard layout differs, the hub reopens dotool with the new layout
while idle.

**Take over (Devral).** `RUNTIME_DIR/devral`: if Devral is on at the FIRST `gonder()` of a Girdi object, it waits at most
8 s and then stops with 12; later calls stop with 12 without waiting. Notifications are written to
`STATE_DIR/bildirimler.jsonl` (when it exceeds 2 MB the last 1 MB is kept, `gunluk.temizle`).

## 3. Target selection
The global `--arka` flag / `DESKHAND_HEDEF=arka|on|oto` / the `arka:` id prefix → `arka_uc.sec()`. For the `sanal` target
`sec()` looks at the type in the state record (`arka_tur()`): KWin → `KwinArkaUc`, Xvfb (or no record) → `SanalArkaUc`.

**Type selection (a single path, no option is offered).** `masaustu.secilen_tur()`: if `kwin_oturum.kullanilabilir()` (KWin >= 6.8,
an accessible render device, `deskhand-eis` + `deskhand-goruntu` built, kdotool, dbus-daemon…) then KWin; otherwise Xvfb.
If a KWin that was chosen automatically CANNOT BE OPENED, it falls back to Xvfb (warning + log). Only for testing/diagnostics:
`DESKHAND_ARKA_TUR=kwin|xvfb` (if a forced kwin is unusable, Dur 9; no silent fallback).

**Multiple invisible desktops (core of stage 1).** PRINCIPLE: a process (an MCP session or a CLI call) is bound to ONE
invisible desktop; at most `[masaustu] azami` (1..6, default 3) desktops at the same time, Dur 7 if exceeded. Every desktop
has its own state record + lock + input lock + Devral flag + session-copy root (`masalar`); the lower layer (KWin session
`RUNTIME_DIR/kwin-<id>`, cage, Wayland socket, D-Bus, private PipeWire) is already per desktop. A named desktop exists
ONLY in the KWin type (the Xvfb type only with the default name; shared null sink name). The `arka_uc.sec()` cache is keyed
by `(desktop, type)`. Context: CLI `--desktop-name NAME` (before the command) / `desktop … --name NAME` / environment
`DESKHAND_MASAUSTU`; MCP binds AUTOMATICALLY (at the first `desktop=background` resolution): if `--desktop-name`/the environment
is fixed, that one; otherwise the default if the default has no live owner; otherwise the smallest free `oturum-N` (auto). On
binding `os.environ["DESKHAND_MASAUSTU"]` is written (child processes inherit it; the `erisim` helper process carries `masa` in
its request); `name` in the `get_status`/`manage_desktop` reply. An MCP in task mode ALWAYS binds to the default desktop (it
does not touch ownership). The MCP remembers its first parent; if the parent died and was re-parented to systemd it does not
bind (Dur 14). OWNERSHIP: the `sahip` file (`RUNTIME_DIR/sanal-sahip` for the default) = `mcp <pid> <start> <first_parent_pid>
<parent_start> <auto> <pid namespace>`; the GATE is `masalar.erisim_kapisi` (called from the gorev_kipi gates, reading
included): if the default desktop is reserved for a task (task marker alive) the task marker comes FIRST: task mode → allowed,
panel → allowed, everyone else (the owner included) → Dur 14 (task desktop); when the task ends, ownership comes back as it
was. Then: owner dead/corrupt/PID reused → free; owner in another PID namespace (cannot be checked) → Dur 14; the caller is the
owner → allowed; the owner's parent is in the caller's ancestor chain (with start time) → allowed (the Bash of the same Claude
session); NO `claude` process in the ancestor chain at all (a human: own terminal, KDE shortcut) → allowed; panel (GOZLEMCI) →
allowed; anything else → Dur 14. This is a COORDINATION rule (agent sessions must not disturb each other's desktop); it is NOT A
SECURITY BOUNDARY against shell code of the same user (the same uid can delete the file and forge the ancestor chain). In the
panel's approval hand-over (CAPTCHA) "Take over" (Devral) switches the Background tab to the request's desktop (the panel
process's context) and returns to the default when a decision is made; the approval dialog shows the desktop name. A Flatpak
instance is recorded only by child-PID match (no match by application name: the instance of another desktop must not get
recorded and killed). LIFETIME: when the MCP closes only ownership is released; for an `oto` (auto) desktop a detached cleaner
(start_new_session, `DESKHAND_OTO_BEKLE` or 120 s) stops it if it is ownerless; every start and `desktop list` stops ownerless
autos. The default and fixed-name desktops never close by themselves. Stopping (`masaustu_durdur(ad)`) closes ONLY that
desktop's processes, session copies and Flatpak instances (`oturum.kapanis(ad)`, `politika.kopya_dizini(ad)`). An approval
request carries a `masa` field; `onay.bekleyen_var(..., masa)` and the MCP `_BEKLEYEN[(backend, masa)]`: a pending approval on one
desktop does not lock another. The task-mode marker (`gorev-masaustu`) reserves only the default desktop (it will move to the
`gorev` name in stage 2). The panel shows only the default desktop (except for the switch during a hand-over; stage 2). GPU: if
there are several render devices, boot_vga=0 + the integrated device (the "connected output" information is not trusted)
(`KWIN_RENDER_NODES`); if it cannot be opened with that device, once more with the default. Before a session counts as "ready":
Wayland socket, the `org.kde.KWin` name, the ScreenShot2 interface, one frame of the session size (scale 1), EIS devices of the
same size; if KWin dies while waiting, an immediate error.
SCALE 2 (HiDPI, `desktop start --scale 2` / `manage_desktop(scale=2)`, KWin only; `olcek` in the record, an old record = 1):
`kwin_wayland --virtual --width W --height H --scale 2` opens the frame buffer at 2W×2H but KWin's output store gives the new
virtual output scale 1 (measured: the EIS region is 2W×2H, the layout grows) → before the readiness check `kscreen-doctor
output.<name>.scale.2` through the session's OWN Wayland socket (`_ekran_ortami`: absolute WAYLAND_DISPLAY, private data path,
KSCREEN_BACKEND_INPROCESS; it cannot reach the user's screen). Ready: frame 2W×2H, EIS region W×H. CONTRACT: window geometry,
click/EIS coordinates, AT-SPI boxes, OCR boxes are LOGICAL pixels (the same layout as scale 1); `ArkaUc.goruntu()` is the
physical frame. `gorsel.pencere_goruntusu(tam=False)` (default; OCR, observe, difference, approval) shrinks the physical frame
to logical with LANCZOS; `tam=True` does not shrink, `im.info["deskhand_olcek"]` (`gorsel.piksel_olcegi`) = image pixel / window
pixel. Users of the full resolution: the CLI `screenshot` (the `--out` file is 2×, `--width` shrinks; `son_foto.olcek` = total
scale, `--foto` maps it) and the MCP `screenshot` (the full frame is shrunk to `max_edge`; the `shot_id` scale = shrink × pixel
scale → `cekim_noktasi` gives a logical coordinate; small regions come back with 2× detail). XWayland: KWin `[Xwayland] Scale=2`
(clients scale themselves, the X11 coordinate is physical) → `GDK_SCALE=2` for session applications (Firefox dpr 2),
`--force-device-scale-factor=2` for Chromium/Electron; AT-SPI boxes are divided by the scale ONLY on a desktop with scale > 1
(`olcek` in the request, `ArkaUc.masaustu_olcegi()`) and if the frame window geometry is ~a multiple of the scale (|ratio − scale|
< 0.35 in both dimensions; `erisim.xwayland_orani`); at scale 1 they are never divided (so that an application reporting an
oversized frame does not cause a wrong click). On the Xvfb type scale 2 is refused with Dur(9) (no output scale; per-application
flags are inconsistent in a Qt/GTK/X11 mix). Memory: a 2× frame is ~4× the frame buffer (a cage with Firefox at 1280x800 ~500 MiB;
a 4 GB cage is enough).
The default is `on` (the user's real desktop). `oto` is tied to the `deskhand decide` command: if the user's screen is busy it
suggests doing the work in the background, otherwise in the foreground.

## 4. Safety (UNCHANGED in both backends)
- Forbidden windows (`yasak-pencereler.txt`): no input + no launch (10). **The list is empty by default** (only the built-in
  panel/approval window ban exists); the user adds their own bans.
- Sensitive button / payment page title → 10 unless `--onayli`. `--onayli` ONLY if the user explicitly approved in the chat.
- **Risky key combinations → human approval** (NOT a ban). `guvenlik.riskli_tus(combination) -> reason | None`:
  ctrl+alt+delete, ctrl+alt+backspace, ctrl+alt+f1…f12 (virtual terminal), meta+l and ctrl+alt+l (screen lock),
  alt+sysrq+key. `k_tus` / `k_bas` use the sensitive-action path (`riskli_tus_engel`): without `--onayli` approval from the
  panel, 10 if the panel is closed; `dizi`/flow steps go through the same functions and are therefore covered unchanged.
  Independent of the window class. Because `k_bas` holds keys down at the same time, space-separated keys count as a single set
  (`birlikte=True`).
- **RUNNING A COMMAND IN A TERMINAL ALWAYS REQUIRES HUMAN APPROVAL; the blacklist (`riskli_komut`) is only for WARNING.**
  EVERY Enter going to a window that hosts a terminal (or an embedded terminal) — enter, kpenter, linefeed, `x:Return`, `k:28`,
  ctrl+j/ctrl+m/ctrl+o, `\n` inside text, line breaks in AT-SPI value typing — asks for panel approval INDEPENDENT of the
  line content (`ucbirim.enter_kapisi`): one Enter = one approval (an earlier approval in the same action is not carried over;
  `yaz "a\nb\n"` is two approvals, `tus "l s enter p w d enter"` is two approvals); refusal in unattended mode (10); in the CLI
  `--onayli` (the user approved in the chat) passes. NO exceptions: it asks even if vim/less/a REPL is in the foreground (the
  foreground process found with tpgid only enters the approval text as the note "not a shell in the foreground: …"). The
  approval request: "A command will be run in the terminal (Enter)", the current line (if readable; only the length for
  `--gizli`/passwords; "line could not be read" if unreadable), "MAY BE DESTRUCTIVE: <reason>" if `riskli_komut` or a history
  expansion (`!!`, `!n`, `^a^b`, `fc`, `r`, `history -s`) matches, the terminal type (embedded or not). Reading the line:
  AT-SPI if accessibility is ALREADY on (the cursor line of the element whose role is `terminal` + the previous two lines;
  accessibility is not turned on for this), otherwise the window's OCR (the bottom four written lines; the part after the prompt
  marker, the union of wrapped lines and individual lines are candidates); the BUFFER of what Deskhand typed
  (`RUNTIME_DIR/ucbirim/<sha1(backend:window:pid)>.json`, 0600, directory 0700, flock; printable keys/`type` are appended,
  BackSpace deletes, Enter/ctrl+c/ctrl+u/Esc clear; arrow keys, ctrl+a/e/r/w, Tab, click, paste, switching to another terminal and
  120 s of inactivity make it "dirty") is added to the warning candidates. Timing: a `tus`/`bas` sequence is sent split at Enters
  and the window is recomputed IMMEDIATELY before EVERY Enter (also in the middle of the sequence); Enters inside text are
  approved one by one before typing; an Enter not approved beforehand is recomputed right before sending and asked then if
  necessary. Covered paths: `tus`/`bas`, `yaz` (letter by letter + by pasting), `dizi`/flow steps, AT-SPI value typing. A window
  that does not host a terminal gets no Enter handling (the number of approvals does not change).
- **Do not TYPE a destructive command into a terminal** (without Enter): if the target hosts a terminal and the text produces a
  `riskli_komut` warning, approval is asked (`guvenlik.ucbirim_komut_engel`, `eylem._yazi_hassas`); if the text has an Enter this
  is not asked separately (the Enter approval carries the same warning: two dialogs are not opened). `riskli_komut` (the
  warning) splits the text into words with shell rules (quotes/backslashes removed, `$'…'` expanded, the insides of `$(…)`/`` `…` ``/
  `<(…)` are checked separately; shell keywords and assignments skipped; an assignment in the same text is resolved; brace
  expansion; `busybox X` → X; wrapper options; `env -S`); warning patterns: destruction (rm -r, find -delete/-exec, mkfs, dd,
  shred, truncate -s 0, git clean -f, rsync --delete ~, mv ~), privilege (sudo/doas/pkexec/run0), power/session
  (shutdown/reboot…, systemctl/loginctl, D-Bus `login1 … Reboot/PowerOff/Suspend`, `org.kde.Shutdown`, ksmserver), terminating the
  desktop/Deskhand (`killall`/`pkill`/`kquitapp*` plasmashell/kwin/deskhand, `systemctl stop plasma-*`), touching Deskhand's
  settings/state files, indirect execution (`… | sh`, `base64 -d | …`, `<`/`<<`/`<<<` into a shell, `source`/`.`, `eval`,
  `alias`/`trap`, `PROMPT_COMMAND`/`PS0`/`BASH_ENV`/`LD_PRELOAD`, history, `${…}`/`$(…)` in the command name), scripts/programs
  whose content cannot be checked (`./x.sh`, `~/x.sh`, `bash x.sh`, `python3 x.py`, a program from a temporary directory),
  GTFOBins options (`--checkpoint-action`, `ProxyCommand`, `rsync -e`, sed `e`, `man -P`, `zip -TT`, vim `:!`), persistence
  (start-up files, autostart, `~/.ssh`, `~/.local/bin`, crontab), detached launchers (`systemd-run`, `at`, `tmux new`,
  `screen -dm`, `flock -c`, `watch`), piping a download into a shell, fork bomb, forced git push, `:w !sudo`. The warning list
  may be incomplete: the safety boundary is the Enter approval above.
- **Terminal recognition** (`guvenlik.ucbirim_penceresi_mi`): if the window class is a terminal emulator; OR among the
  DESCENDANTS of the window's owner process there is a shell with a controlling terminal (tty) (an EMBEDDED terminal: Dolphin F4,
  the Kate terminal panel, VS Code/IDE — the whole window counts as a terminal); if the PID is unknown and the class is an
  application that can embed a terminal (`GOMULU_UCBIRIM_SINIFLARI`), the safe side; if accessibility is already on and the
  window has an element with role `terminal`. Only a "terminal" result is cached for 2 s; a "NOT a terminal" result is not cached
  (recomputed before every Enter). After a key that can open a terminal (F4, shift+F4, ctrl+`, ctrl+shift+`, ctrl+alt+t,
  ctrl+shift+t, alt+F12) is sent to a window of an embedding class, the window counts as "may be a terminal" for 30 s
  (`RUNTIME_DIR/ucbirim/ucbirim-<sha1>`; during that time every Enter is approved); if in the same call the terminal-opening key
  comes before the Enter, that Enter also asks for approval.
- **The agent's own client** (`deskhand/kendi.py`): the Deskhand process (CLI and MCP server) walks up through ppid in
  `/proc/<pid>/stat` to 1 (session infrastructure — systemd, kwin, plasmashell, krunner… — excluded); in the MCP server the set
  is refreshed every 15 s. If the owner PID of a window (kde: `kdotool getwindowpid`; sanal: `_NET_WM_PID`) is in this set, EVERY
  input to that window is 10 ("the agent's own client"; the agent must not be able to approve its own permission prompt);
  reading/screenshots are free. Terminals often keep many windows in ONE process (Ghostty, Konsole): ALL windows of that process
  are covered. If tmux is in the chain, with read-only `tmux list-clients -F '#{client_pid}'` through `$TMUX` the ancestors of the
  clients (the emulator) are added; if it cannot be resolved (screen, zellij, dtach, a failed tmux query) ALL windows of terminal
  class (kde). Windows with an unknown PID (kde): environment hints (`KONSOLE_DBUS_WINDOW`, `WINDOWID`, `TERM_PROGRAM`,
  `GHOSTTY_RESOURCES_DIR`, `KITTY_PID`, `ALACRITTY_WINDOW_ID`) and the name of the emulator in the chain → the PID-less terminal
  windows of that class too. If we run in a PID namespace (flatpak/bwrap: `/.flatpak-info`, bwrap in the chain, or several NSpid
  entries in `/proc/<pid>/status`): the outer PID of the ancestors (the first NSpid field) is added to the set and terminal
  windows of the same class whose PID does not match are covered as well (the window manager sees the outer PID). A remote client
  connecting over ssh is out of scope. Windows on the invisible desktop cannot be the agent's client: there only the PID rule
  exists (which naturally comes to nothing). Check places: `denetle`, `pencere_denetle` (AT-SPI), `imlec_alti_denetle` (the window
  under which a click/drag lands), in desktop mode the active window to which keyboard input goes (`girdi_seviye_denetle`),
  `pencere_yonet`, `k_kapat`, the process of the AT-SPI frame; typing by pasting goes through `denetle` for every chunk.
- **System privilege/password/permission prompts → human approval** (not a ban): the polkit authentication agent, KWallet
  (`kwalletd5/6`, `ksecretd`), password askers (`ksshaskpass`, `pinentry-*`, `ssh-askpass`), `xdg-desktop-portal-*` permission
  dialogs (`org.freedesktop.impl.portal…`), `kdesu`/`sudo`/`pkexec` prompts (`guvenlik.SISTEM_ISTEMLERI`, a single constant
  list; on the window class and on the name of the owner process). Every kind of input to these windows (mouse, keyboard, paste,
  AT-SPI action/value typing, drag, window management, closing) asks for approval at the start of the action
  (`sistem_istemi_engel`; CLI `--onayli`, in MCP always the panel, refusal in unattended mode); the approval is valid for that
  window during that action. Right before every send `sistem_istemi_denetle` gives 10 for an unapproved prompt — also for the
  window at the screen point WHERE the input LANDS (`imlec_alti_denetle`: if another window was targeted and a prompt is open at
  the point, refusal even if permission exists; on a click in desktop mode approval is asked for the prompt at the point).
- **Pasting = reading the clipboard** (kde): `ctrl+v`, `ctrl+shift+v`, `shift+insert`/`shift+kpinsert`, the Paste key
  (`XF86Paste`, `k:207`), pasting through the keyboard menu (`shift+F10` / `menu` / `alt+e` followed by `p`/`y` or navigating the
  menu and Enter — in the same call or in a separate call within 3 s), middle click (primary selection), if the name/action name of
  an AT-SPI element CONTAINS "paste/yapıştır" (the accessible name of an icon button) and pasting from a MENU (the clicked text or
  AT-SPI element name Yapıştır/Paste/Einfügen/Coller/Pegar…, "Panodan ekle", "Insert from clipboard", "Paste as…", "Özel
  yapıştır", 📋 or a "Ctrl+V" hint; short text; inside `guvenlik.hassas_engel` — mouse, AT-SPI action and the web paths that call
  the same function) carries the user's clipboard to a place the agent can see: if the clipboard is not empty and is not text that
  Deskhand wrote in this session (`guvenlik.kendi_pano_ekle/kendi_pano_mu`: process memory + `RUNTIME_DIR/pano-ozetleri`, 0600,
  sha256 only) approval is asked (also if it cannot be read). Deskhand's own typing-by-pasting path (`eylem._yapistirarak_yaz`)
  is exempt. The clipboard of the virtual desktop is separate: no check. KNOWN LIMIT: a mouse click on an icon "paste" button whose
  text cannot be read by OCR AND which has no accessible name cannot be recognised (a click by coordinate; no approval is asked).
- **Password field** (AT-SPI role `password text`, the target element for value typing, the focused element for keyboard typing —
  if accessibility is on): typing / pasting / value typing ask for approval (CLI `--onayli`); its value is NEVER read (not even for
  verification); the text is not written to the log, error message or approval request (length only), it is hidden automatically
  even if `--gizli` was not given.
- **Session lock** (kde): if `org.freedesktop.ScreenSaver.GetActive` (otherwise logind `LockedHint`) is locked or cannot be read,
  no input goes to the user's screen (15, "session locked"; fail-closed; `--ekranimda` does not override): text that accidentally
  goes to the lock screen counts as a password attempt and can lock the account. The state is cached for 0.5 s; absent on the
  virtual desktop.
- **The approved target must not change**: if a sensitive click was approved from the panel, right before the click the text at
  the point is OCR'd again and fuzzily compared with the text in the approval request (similarity < 0.85 → the click is not made,
  10 "approved target changed"). On a click on a tree element (`click-element`, web elements included) the element is additionally
  found again in the tree (`erisim._onay_sonrasi_oge`): if its name, role, centre (±3 px; on the web the bus name + object path)
  are not the same or it is missing, 10. If there was no OCR text at the point at approval time (a text-less icon / an
  `aria-label` button: the element name is not visible in OCR) the point comparison becomes "there is no text now either"; the
  identity is verified from the tree. In a web accessibility action (`via="action"`) the same element check comes before the action.
- **The end of a drag** is checked like the start: one approval carries the text of both points; during intermediate movements the
  watcher (active window + title lock); right before release the window under the end point (forbidden / own client / unapproved
  system prompt / another application) — if it does not fit, the cursor is taken back to the start and released (the drag is cancelled).
- **Application access levels** (default NONE): `CONFIG_DIR/uygulama-seviyeleri.txt`, line `PATTERN = goruntule | tikla | tam`
  (PATTERN is a title/class regex like in the forbidden list; English aliases view/click/full). goruntule = no input at all (10;
  reading/screenshots free), tikla = mouse free, keyboard (yaz/tus/bas) and closing the window not allowed (10), tam = no
  restriction. If the file is missing/empty there is no restriction at all (the tool does not restrict applications on its own);
  the file is not created while being read, only Save in the panel writes it. If several patterns match the MOST RESTRICTIVE wins;
  a malformed line (= missing, unknown level) counts as goruntule on the safe side (the panel does not save a malformed line).
  The check is the same in both backends: `Girdi.gonder` calls `guvenlik.girdi_seviye_denetle(k, satirlar)` right after
  `denetle(k, desen)` (key/keydown/type = keyboard; mouseto/click/button/wheel = mouse; typedelay/typehold setting lines are not
  checked); in desktop mode the keyboard looks at the active window, the mouse at the window under the cursor via `imlec_alti_denetle`.
  Launching with `ac` is not affected. A level refusal is given BEFORE the approval (no empty dialog is opened). Window management
  (`eylem.pencere_yonet`: move/resize/minimise/maximise/restore) counts as "mouse" input (10 at goruntule, free at tikla); a click
  with a modifier key ("keydown") and typing by pasting count as keyboard (10 at tikla). The clipboard itself (`clipboard`) is not
  tied to a window and is therefore outside the level check.
- **Launching a risky command.** The raw command line of `ac --komut` goes through `guvenlik.riskli_komut`: human approval for a
  destructive pattern (in the CLI `--onayli`, does not pass in unattended mode), refusal → 10 and nothing is started. `ac --komut`
  is for a user/agent that has a shell; the MCP surface NEVER reaches this path.
- **MCP application launch (`open_app`).** An MCP agent that has NO shell must not be able to run code (`uygulama.mcp_uygulama`,
  the single entry point; `api.uygulama_komutu` → `gio launch ENTRY.desktop [documents…]`): `app` is only an installed desktop
  entry (`uygulama_bul`); a name containing `/` (path/command) → 10. The entry is refused (10) if in the program position of Exec
  (skipping pass-through wrappers nice/prime-run/gamemoderun…) or in any element, as a path/bare name, there is an interpreter, shell,
  wrapper (`env setsid nohup systemd-run flatpak-spawn xargs`…), privilege escalator, launcher (`xdg-open gio kioclient`…),
  `deskhand`/`ekran`, a terminal emulator (`guvenlik.ucbirim_mi` + an extra list); `Terminal=true`, `Categories=…TerminalEmulator`;
  for Flatpak a sub-command other than `run`, a terminal id or a forbidden `--command`; those that run another program through a
  sub-command/option (`git -c`, `flock -c`, `tmux`, `screen`, `setpriv`, `script`, `expect`…); shell metacharacters in an Exec
  element (`; | & $ \` < >`), command text starting with `!`/`=!` or containing spaces (if it is not an existing path) and a program
  after `--`. **Allow list:** an entry that passes the blacklist starts WITHOUT approval only under this condition: the file is in
  `SISTEM_UYGULAMA_DIZINLERI` (`/usr/share/applications`, `/usr/local/share/applications`, `/var/lib/flatpak/exports/share/applications`)
  and it itself + all its parent directories (symbolic links resolved) are root-owned and not writable by group/others; every program in
  Exec (pass-through wrappers included, resolved through PATH and `os.stat`) is a root-owned, non-writable, executable ELF binary or a
  `#!` script under the same condition (wrappers installed by the system: libreoffice, steam, vivaldi…) — the script's interpreter
  (absolute path) and, for `#!/usr/bin/env PROG`, PROG too must be a root-owned, non-writable ELF; no option (`-S`) or assignment may be
  given to env.
  The blacklist applies unchanged (if the Exec itself is `bash`/`ldd`/…, 10). Otherwise (the user directory
  `~/.local/share/applications`, a user Flatpak, a program or interpreter owned by the user, a user file that comes earlier in
  PATH) human approval is requested from the panel (`guvenlik._panelden_onay`; one action = one approval; 10 in unattended
  mode / when the panel is closed / on refusal, kind "hassas"); the approval request shows the entry path and the Exec; at
  permission time the entry is read once and verified to be identical to the approved Exec, and it is launched from its 0600
  copy under `RUNTIME_DIR/uygulama/` (changing the file after approval is useless). Arguments are documents only: an http/https
  URL (`=` in the query is allowed), a local `file://` URL or the ABSOLUTE path of an existing file/folder; an argument that
  starts with `-`, contains `=` (outside a URL), has another scheme, has control characters, or points to an executable file or
  a `.desktop` → 10 (at most 16). The agent cannot give variables to the environment of the launched process (only the session
  policy's `env_ek`). If there is no session bridge on the invisible desktop no application is started (10). **Applications
  that host code** (`uygulama.KOD_BARINDIRAN`, a single constant list; compared after stripping the parts of the .desktop id,
  the Exec programs and the version suffixes of the Flatpak id: lutris, protontricks, winetricks, wine, steam, heroic,
  gameconqueror/scanmem, libreoffice, gimp, blender, krita, inkscape, godot, IDEs (code/codium/kdevelop/qtcreator/JetBrains…),
  jupyter, IDLE, obs, darktable…) ask for human approval even if they are system entries (they process a document as code or run
  code from their interface). Executable types in a document argument (`YURUTULEBILIR_TURLER`: .bat .cmd .exe .msi .ps1 .py .sh
  .bash .lua .pl .rb .js .jar .AppImage .desktop .yml/.yaml .docm .xlsm .pptm …; path and file:// URL) are 10 for every
  application. For an approved user entry, if the Exec program belongs to the user, the sha256 of its content is taken at approval
  time and compared right before launch (`api.uygulama_ac` → `uygulama.onayli_program_denetle`); if it changed, 10. **Limit:** an
  MCP-only agent cannot run code; GUI script consoles (macro editor, Python console, IDE terminal) are only inside applications
  the human approved. Applications with an embedded terminal (file manager, kate) open without approval; typing into terminal
  panels is protected by the Enter rule.
- **Settings files: the panel is the authoritative source** (`liste_koruma.py`). The forbidden list and the level file cannot be
  removed with the agent's own tools (`rm` in a terminal, deleting in a file manager, emptying in an editor): at start-up the
  panel reads the two files and keeps them IN MEMORY; only its own Save writes the file; if the file is changed from outside or
  deleted (QFileSystemWatcher + 2 s polling) the panel keeps its own content, writes the file back and warns (log line + tray
  notification). On every write the panel leaves `STATE_DIR/liste-<kind>.isaret` {sha256, icerik} (the marker); at start-up if the
  file does not match the marker, the record in the marker is restored. CLI and MCP take the lists from the approval channel
  (`liste yasak|seviye` → `icerik <n>` + text | `yok`; channel verification is the same as §8; the client caches for 0.3 s). If the
  panel is closed it is read from the file; if the marker EXISTS but the file is missing or does not match the marker, Dur 10
  ("the Deskhand settings file is missing or was changed outside the panel; … open the panel"), no input is sent. If there is no
  marker (first installation) the old behaviour. Editing the file by hand is not supported: changes are made from the panel's
  Settings. The same panel-authoritative pattern applies to the two loosening settings in `ayarlar.toml`: the approval scope
  (`liste onaylar`) and the account sessions (`liste kimlik`; see "Approval scope" and "Account sessions" below).
- **Pending approval = no input (MCP).** While human approval is awaited on a desktop (kde/sanal), every input tool going to THAT
  desktop (click, type_text, press_key, scroll, drag, manage_window, clipboard write, run_flow, open_app) is refused without
  waiting, as soon as it takes the lock, with `[7] approval pending` (`mcp_sunucu.kilitli(girdi=True)`); the record is opened
  before the lock is released and closed after the lock is taken again after approval. Requests of other live Deskhand processes
  on the same desktop are also counted (`onay.bekleyen_var`; an unusually long-lived fake request is not counted). Reading tools
  and DUR are always free. The same gate exists for CLI/flow input: `eylem.girdi_al` (every mouse/keyboard path) and the guards of
  the accessibility action path (`erisim._atspi_korumalari`, the web action included) give 7 when ANOTHER live Deskhand process has
  a pending approval for that desktop (the process's own requests are not counted). `bekleyen_var` takes the desktop as
  "ekran"/"arka" or as a backend name ("kde"/"sanal").
- **Unattended mode.** `DESKHAND_GOZETIMSIZ=1` or the global flag `--unattended` (`--gozetimsiz`): every action that requires
  approval is refused without opening a panel dialog and without waiting (10, "no sensitive action is performed in unattended
  operation"). A single point `onay.iste_sonuc` (CLI, MCP and flow all pass through it). Since there is no chat/human, `--onayli`
  is also considered invalid (`guvenlik.onayli_gecerli`). For scheduled flows.
- The title (`-b`) and class (`-s`) lock right before every input (4).
- The DUR (stop) switch: if `DESKHAND_RUNTIME_DIR/dur` exists, Dur(13) before every input call; everything held down is released.
  Turning DUR ON is free (`deskhand dur`, the UI/tray/shortcut). Removing it is the user's decision only: `deskhand devam`
  (`guvenlik.dur_kaldir_iste`) asks the panel (request type `dur`: the panel shows its own fixed text "Remove STOP?", default No, and on Yes the PANEL removes DUR; the requester never does); panel closed / unattended mode / No → Dur 13; a
  command-line `--approved` is not an answer. Messages never tell an agent how to remove it. A DUR the user set in the panel
  and that disappears without the panel's Devam (a process deleted the file) is put back with a visible warning
  (`gui/panel._dur_koru`). Out of scope: a process that deletes the file while the panel is closed.
  `guvenlik.dur_ac(source)` / `dur_kapat(source)` / `dur_kaynagi()`: the first word of the dur file is `kullanici` (user) or
  `cli`.
- The input hub (§2) gives guarantees IN ADDITION to the client checks: socket 0600 / directory 0700 and only the same user
  through SO_PEERCRED (the client also checks the server's user and the socket permission); the DUR switch right before every
  batch (if on, press lines are refused with 13, `keyup`/`buttonup` and delay settings pass); only the known verbs of the dotool
  language. Held keys/buttons are tracked per connection: when the connection drops (client died, SIGKILL) whatever is held is
  released (except a key another connection also holds); if the input of the dropped connection continues in the queue, dotool
  is restarted (no unchecked input continues). When DUR is turned on the held keys of all connections are released, and if there
  is input in the queue dotool is restarted (the queue is dropped). If the panel dies the input of dotool is closed, dotool exits,
  the device disappears.
- Human priority (12): in the kde backend if the user is using the keyboard/mouse; on the virtual desktop (both types) only while
  "Take over" (Devral) is on. Take over in the panel works in both types (preview `goruntu()`, input `Girdi.insan_ham`; over EIS in
  the KWin type).
- Window management, closing windows and (kde) clipboard writing also obey human priority (12) (`guvenlik.insan_onceligi`;
  clipboard: CLI `pano yaz` and MCP `clipboard(write)` → `api.pano_yaz`); closing checks DUR (13). The digests of the texts
  Deskhand wrote to the clipboard are in a SINGLE place (`guvenlik.kendi_pano_ekle/kendi_pano_mu`): the CLI, MCP `clipboard(read)`
  and the paste approval look at the same list.
- No foreground while the user is busy (15): the kde backend calls `mesgul.ekran_korumasi()` before input, bringing a window to
  the front and opening an application. If the active window is full screen / game-like or a video is playing on MPRIS,
  Dur(15). The exception is only the user's explicit permission (`--ekranimda`, `DESKHAND_EKRANIMDA=1` or the "Do it on my screen"
  button in the notification → 10 min). The virtual desktop is unaffected.
- **The AT-SPI frame is chosen only from the PID of the target window**; if there is no exact PID match, ONLY among the
  DESCENDANTS of the window process, a frame with the same executable and a title that is ≥ 0.9 similar (multi-process
  application). NEVER the ANCESTORS (so that an action does not go to the frame of another application that launched the window's
  owner); if none is found or the PID is unknown, Dur 6 — it never falls to the frame of another application by title similarity.
  The identity of the chosen frame itself is also checked: a frame that belongs to the process of the Deskhand panel/approval
  dialog is always 10 (reading included), a forbidden pattern (application name/frame name) 10; for action/value typing, the agent's
  own client and the application access level. In the tree scan the identity of the frame (bus name + object path, TOGETHER) is
  stored; if it is a different object at action time, Dur 8.
- The accessibility action path (`ogeye-tikla --eylem`, `ogeye-yaz`; `erisim.py`): there is no real mouse/keyboard input and no
  focus, so the checks of the mouse path (except under-cursor) are applied EXPLICITLY: DUR (13), forbidden window (10), title/class
  lock (4), sensitive button name / payment page (10 or approval from the panel; the approval request has no image), game/film
  protection in kde (15), application access level (action/click = "mouse" class: 10 at goruntule; value typing = "keyboard": 10
  at tikla as well; BEFORE approval), human priority (12: in kde, if the user is using the keyboard/mouse, it waits at most 8 s for
  idleness and then 12; on the virtual desktop only while Devral is on), log. In value typing the destructive-command check for
  terminals is applied unchanged too (`_yazi_hassas`). These checks are redone right before the action (approval may have been
  waited for). libatspi connects to a single bus in the process; the work for another desktop runs in a helper process. When a
  virtual desktop is opened `masaustu._erisim_hazirla_ic` sets IsEnabled=true on the private bus and starts the registry
  (at-spi2-registryd) in its own cage.
- Automatic turning on of accessibility (kde): IsEnabled=true is written on the user's session bus; this can change a persistent
  desktop setting (`toolkit-accessibility`). If Deskhand turned it on, the marker `STATE_DIR/erisim-deskhand-acti` is written and
  ONE note is put in the log; `deskhand doctor` shows the difference "on (Deskhand turned it on)" / "on" / "off"; `deskhand a11y
  off` also deletes the marker. Tests fake `_erisim_yaz` (the real session setting is not touched).
- A raw `dotool`/`xdotool` call ONLY inside a backend. NEVER anywhere else, tests included.
- A virtual X connection is opened only with `masaustu.guvenli_ekran()`: an empty name falls to `$DISPLAY` in Xlib (the user's real
  XWayland) and XTEST input could go to the real desktop. Only a display of the form `:N` that differs from the real `DISPLAY` is
  accepted.
- **The state record is untrusted (both types).** From the record ONLY the type + id/display number is taken; all paths and
  addresses are BUILT from the working directory (`kwin_oturum.guvenli_kayit`, `masaustu.guvenli_kayit`; `masaustu.durum()` applies
  this): KWin `RUNTIME_DIR/kwin-<8 hex>` (not a symbolic link, the user's, 0700) → `unix:path=<dir>/bus`, `<dir>/deskhand-<id>`,
  Xauthority, XWayland `:120+`; Xvfb `RUNTIME_DIR/sanal-<no>`. The strict form of the bus address is `unix:path=/path[,guid=<32 hex>]`
  (Python `arka_ortak.bus_yolu_kati`, C `adres_coz`): multiple addresses with `;` (sd-bus/libdbus moves on to the NEXT one if the
  first fails) are rejected. If RUNTIME_DIR is an existing directory it must be owned by the user, not a symbolic link and 0700;
  a loosely-permissioned directory is NOT silently tightened (someone may have left a file/socket in between): Dur 14, `deskhand
  doctor` shows the reason and a `chmod 700` suggestion in the "Working directory" line.
- **Peer verification (hard link / replacement).** Before connecting (`kwin_oturum.baglanti_denetle`,
  `masaustu.xvfb_karsi_denetle`): the SO_PEERCRED PID of the session sockets is the process in the record (same start time) —
  dbus-daemon for the bus (`--config-file=<dir>/bus.conf` on its command line), KWin for Wayland, Xvfb for X; if the socket's
  (st_dev, st_ino) is one of the user's real sockets, refusal. After connecting, `deskhand-eis` does the same itself (`--dbus-pid` +
  bus.conf; otherwise `hata bus-karsi`, exit 2).
- **KWin type gates.** `kwin_oturum.guvenlik_kapilari` (before the process starts): Dur 14 if the bus address is the user's real
  address (the same inode included), the Wayland socket name is the user's, the configuration directory is the real `~/.config`,
  HOME/working directory is the real one, or the XWayland display is the real `DISPLAY`. `arka_uc/kwin.py` uses the SAFE record
  returned by `baglanti_denetle` before EVERY connection; `deskhand-eis` connects only with `--bus <private address>`, it does not
  inherit from the environment. KWin is opened with a minimal environment equivalent to `env -i`, with a temporary
  HOME/XDG_*_HOME (KWin writes its own kwinrc / kwinoutputconfig.json / kglobalshortcutsrc / kxkbrc files here);
  KDE_FULL_SESSION/KDE_SESSION_VERSION are not given to KWin.
- **Application namespace (both types, a SINGLE launch path: `arka_ortak.korumali_baslat` → `korumali_argv`).** A background
  application (everything OTHER than KWin/Xvfb, dbus-daemon and Deskhand's own helpers: `ac --arka`, `open_app`, session-bridge
  commands) starts with `bwrap` (the model after audit 12c):
  - **Separate user + PID namespace** (`--unshare-user --unshare-pid`, its own `/proc`): the user's other processes (the real KWin,
    a game, a terminal) are invisible; there is no signal, ptrace, `/proc/<pid>/root|environ|mem` access to them (ESRCH).
  - **Read-only root** (`--ro-bind / /`); `/dev` is bwrap's minimal /dev (`null`, `zero`, `random`, `tty`, `pts`, `shm`…) + only
    `/dev/dri` (GPU; WebGL/GL in hardware). NO `/dev/uinput` (virtual keyboard/mouse), `/dev/input/event*` (key recording),
    `/dev/snd` (direct ALSA microphone/speakers), `hidraw`, `/dev/bus/usb`, camera nodes. `/dev/udmabuf` is not given (KWin is
    outside the cage anyway).
  - **Empty tmpfs:** `/tmp` (the user's Steam/Chromium SingletonSockets in /tmp, the `.ICE-unix` ksmserver, Kulak Kesil sockets,
    other X sockets are invisible), `/run/user/<UID>` (Wayland, D-Bus, pipewire/pulse, kwallet, gnupg, ssh, xauth, at-spi, portal,
    systemd sockets) and (if elsewhere) Deskhand's RUNTIME_DIR (girdi.sock, sanal.json, other sessions).
  - **The home directory is an EMPTY tmpfs + a WHITELIST** (`arka_ortak.ev_baglari`, `EV_BEYAZ_LISTE`; 0700, `--size` = min(2 GiB,
    cage memory/4), cage default 8G → 2 GiB; the `/tmp` in the namespace has the same limit): of the real home directory ONLY the
    desktop/toolkit appearance is visible, READ-ONLY — `~/.config/kdeglobals`, `kdedefaults/`, `kcminputrc`, `kcmfonts`,
    `Trolltech.conf`, `plasma-localerc`, `breezerc`, `Kvantum`, `qt5ct`/`qt6ct`, `gtk-3.0`, `gtk-4.0`, `gtkrc`, `gtkrc-2.0`,
    `~/.gtkrc-2.0`, `xsettingsd`, `fontconfig`, `~/.local/share/fonts`, `~/.fonts`, `~/.cache/fontconfig`, `~/.icons`,
    `~/.local/share/icons`, `~/.themes`, `~/.local/share/themes`, `~/.local/share/color-schemes`, `user-dirs.dirs`,
    `user-dirs.locale`, `mimeapps.list`, `~/.local/share/mime`, `~/.local/share/applications` and `~/.local/share/flatpak` (user
    .desktop entries and the Flatpak installation). The OWN settings/data of no application (token, session, history) are visible:
    EVERY hidden file not in the list and every directory/file in the home root that is not a data folder DOES NOT EXIST in the
    namespace (measured: `.config/<random>/token`, `.netrc`, `.git-credentials`, `gh/hosts.yml`, `.docker`, `.kube`, `.pypirc`,
    `.local/share/<unknown>`, `.cache/<app>`, `~/projects/.env`, `~/notes.txt` cannot be read; `tests/test_ev_beyaz_liste.py`). A
    whitelist entry that is a symbolic link is bound from its TARGET; an entry whose target is the home directory itself/above it or
    a SIR_YOLLARI path is rejected. Symbolic-link rules (`_beyaz_ham`): if the source (realpath) is inside / is / is above an XDG
    data folder it is REFUSED (data folders are bound writable: an application in the namespace could create a `-> ~/.config` link
    there and have the whole configuration opened in later launches); if the source is OUTSIDE home and under `/tmp`,
    `/run/user/UID` or RUNTIME_DIR it is REFUSED; if the source of a whitelist entry is inside home and lexically different, it is
    accepted ONLY if the source is under an entry of the whitelist (not a link) (dotfiles-manager links `~/dotfiles/...` are
    refused; policy `ev` if needed); for a policy `ev` entry only the first two rules. The second line (SIR_YOLLARI) also covers by
    source→target mapping (a secret inside the source is at `target + relative path`). A policy `ev` entry is also filtered with
    `gecerli_politika_ev_girdisi`: glob characters, a hidden entry with a depth below 2 (`.ssh`, `.netrc`…) and the hubs themselves
    (`.config`, `.local`, `.local/share`, `.local/state`, `.cache`, `.var`) are REFUSED. Thin overlays (SIR_YOLLARI):
    `.local/share/flatpak/overrides` (empty directory), `.config/gtk-3.0/bookmarks` and `servers` (/dev/null);
    `flatpak/repo/config` is DELIBERATELY not overlaid (measured: a /dev/null overlay breaks a `flatpak --user` installation).
    TOCTOU: sources are opened as an `O_PATH|O_NOFOLLOW` fd, `(dev,ino)` and the `/proc/self/fd` path are checked, bwrap binds with
    `--ro-bind-fd` (the fds are passed with `pass_fds`, they do not leak to the application); if bwrap does not know it, the
    resolved real path is `--ro-bind`ed and a race between check and bind remains (only on paths writable by the home owner's own
    account). Package/`sys.prefix` binds are added AFTER the data folders, a path that is the ROOT of a `.git` repository is
    refused. Diagnostics: if the resolved exec (the .desktop Exec for `gio launch`) is under home but not visible in the
    namespace, `korumali_baslat` gives `Dur(9)` IMMEDIATELY (the message carries the hint `oturum.toml` `[uygulama.<name>] ev =
    [...]`; MCP `open_app` and CLI `ac` pass through the same gate).
    CLI `ac --background`, like MCP `open_app`, starts the invisible desktop itself if it is closed (`masaustu_baslat`: the same
    cage, lock and task-mode gate) and checks BEFORE the session copy is prepared (no copy in vain).
    `ac APP [ADDRESS]` / `--url`: the address goes through `uygulama.web_adresi_denetle` (http/https only, no space/control
    character/`-`; `file:`, `about:`, `javascript:`, `data:` → 10), it is appended as a single argument to the END of the
    policy's command (since it starts with http(s):// it cannot be in option position; in Chromium the accessibility flag comes
    before the address); it cannot be given together with `--komut`; in task mode `open_app_denetle` and the ban on raw commands
    also apply in the CLI.
    What the application writes (`~/.config/autostart`, `~/.bashrc`, `~/.config/systemd/user`, `~/.local/bin`, its own settings,
    cache…) is DISCARDED with the session → no persistence escape. If an application needs its own settings, `ev = [...]` per
    application in the session policy (relative to the home directory; read-only; there is NO DEFAULT for any application; the
    `ev` in `_varsayilan` is not given to unknown applications; `..`/absolute paths are dropped; it cannot open SIR_YOLLARI):
    `Hazirlik.ev` → `baslat(..., ev=)` → `korumali_argv(ev_ek=)`. Selection measurement (after 0.6.1; fake home, KWin type; 0 =
    empty home, A = whitelist, B = layer + extended blacklist, C = layer + covering unknown hidden directories): KWrite, Dolphin,
    Konsole, Gwenview, Firefox, Chromium, zenity, Meld, Electron open in A; KDE applications with the user's theme/font (on a dark
    theme the average brightness A = B = C, a light theme at 0 without a whitelist), OCR accuracy the same as B/C; B and C leaked
    unlisted secrets, A did not. The only writable REAL binds: the user's XDG data folders (`~/.config/user-dirs.dirs`; only INSIDE
    the home directory, not the home root, no component starting with a dot in the path — an entry pointing to the home root, a
    hidden directory, `/` or the outside is ignored) and the application's own session copy. Existing hidden directories/files
    INSIDE the data folders (`.git` — hooks/config, `.vscode`, `.envrc`, `.venv`…; depth 6, outermost ones) are overlaid read-only;
    a folder where this count exceeds 3000 is bound entirely read-only. Sockets/FIFOs in the home directory (depth 4) and in data
    folders + known ones (`~/.steam/steam.pipe`) are masked with `/dev/null` (measured: connecting to a real socket/FIFO through the
    layer is not possible anyway; the mask is a second line).
  - **Secret paths are UNREADABLE** (`arka_ortak.SIR_YOLLARI`, a single constant list; may be globs): `~/.ssh`, `~/.gnupg`,
    `~/.local/share/keyrings`, `~/.local/share/kwalletd`, `~/.password-store`, real Firefox profiles (`~/.config/mozilla`,
    `~/.mozilla`), profile roots of the Chromium family (`~/.config/chromium`, `google-chrome*`, `vivaldi*`, `BraveSoftware`,
    `microsoft-edge*`), agent/cloud/repository credentials (`~/.claude`, `~/.claude.json`, `~/.config/gh`, `~/.git-credentials`,
    `~/.netrc`, `~/.aws`, `~/.docker/config.json`, `~/.config/rclone`, `~/.kube`), Deskhand's own settings/log
    (`~/.config/deskhand`, `~/.local/state/deskhand`), Flatpak application data (`~/.var/app`), messaging sessions
    (`~/.local/share/TelegramDesktop`, `~/.config/discord*`, `Signal`, `Element*`, `Slack`, `WhatsApp*`, `teams*`, `Mattermost`),
    game platform tokens (`~/.steam/steam/config`, `~/.local/share/Steam/config`, `ssfn*`, `~/.config/heroic`,
    `~/.config/lutris`), KDE Connect pairing keys, qBittorrent (WebUI password; the Flatpak too), Syncthing keys, the OBS stream key
    (`~/.config/obs-studio/basic/profiles`), RustDesk, Thunderbird, FileZilla, Remmina, package-registry tokens (`~/.npmrc`,
    `~/.pypirc`, `~/.cargo/credentials*`) and shell histories. A separately listed path inside an overlaid directory is not bound
    again. Directory → empty tmpfs (the application can write, it is discarded), file → `/dev/null`; if it is a symbolic link (e.g.
    profile-sync-daemon) its TARGET is overlaid (not needed if the target is under /run/user or /tmp, which are already empty in the
    namespace). The overlay is bound AFTER the data folder binds and the session copy AFTER that: the background Firefox runs with
    its own copy (`--profile <copy>`, `XDG_CONFIG_HOME=<copy>/.xdg-config`), the Flatpak Electron copy with
    `--filesystem=<copy>` + XDG_* (measured: Firefox opens/downloads in both types; the Flatpak runtime opens in the namespace).
  - **What is bound back** is only the session's own paths (`uygulama_baglari`: its own runtime directory, private bus and Wayland
    socket, the accessibility bus, its own X socket + Xauthority read-only) and, of the session copies, ONLY the copy that the
    policy gave to this application (`Hazirlik.kopya_yolu` → `baslat(..., kopya=)` → `arka_ortak.kopya_bagi`: it must be a direct
    subdirectory of the copy root, otherwise Dur 14). The copy is NOT taken from the command line/environment: even if the path of
    another copy appears in the command, that copy is not visible. The approved user entry of MCP `open_app` (a .desktop outside the
    allow list) starts with `gio launch <RUNTIME_DIR/uygulama/private copy>`: that SINGLE file is bound read-only (`baslat(...,
    girdi=)` → `arka_ortak.girdi_kopyasi_bagi`: a direct child of that directory, a plain `.desktop` owned by the user, otherwise Dur
    14); other copies in the same directory are invisible. The order: `open_app` allow list + KOD_BARINDIRAN approval + the document
    argument rules (`uygulama.mcp_uygulama`) → the digest check of the approved program (`onayli_program_denetle`) → this isolated
    launch (the SINGLE path: `masaustu.baslat` → `korumali_baslat`).
  - The application's `PATH` and `LD_PRELOAD/LD_LIBRARY_PATH/LD_AUDIT` go only to the final command (`--setenv`); the helper chain
    (sh, nice, ionice, bwrap) runs with a safe PATH and absolute paths (see "Safe helper binaries" below).
  - `--new-session` (no TIOCSTI). NO `--die-with-parent` (the desktop outlives the CLI); the cage and PID cleanup are unchanged; when
    the first process of the namespace dies the kernel kills everything inside. If bwrap is missing or not on a safe path, the
    application is not started (Dur 9).
  - **Flatpak:** `flatpak run` works in the namespace (nested bwrap; measured) but since there is no bus path to the user's systemd
    user manager it CANNOT move to its own scope: the instance stays in the desktop's memory cage and PID namespace and closes when
    the desktop closes (measured). The wrapper (`oturum/flatpak_ornek.py`) verifies this in the namespace and does not write the
    host-machine record (`DESKHAND_AD_ALANI=1`); if the instance left the cage it closes it. What Flatpak writes (`~/.var/app`)
    stays in the empty home tmpfs (discarded); the user installation (`~/.local/share/flatpak`) is read-only.
  - **Measured:** Firefox (empty temporary profile + a copy similar to a session copy) opens in both types, loads a page, WebGL is in
    hardware in the KWin type (integrated GPU), it serves the accessibility tree; a Qt test window; click/typing times did not
    change. Details in `tests/test_denetim12c.py`. Download: the session COPY Firefox runs with its own `XDG_CONFIG_HOME`
    (`<copy>/.xdg-config`); the user's `user-dirs.dirs`/`user-dirs.locale`/`mimeapps.list` and the GTK/fontconfig appearance (0600)
    are copied there and user.js writes `browser.download.dir` = the XDG Downloads (the task folder in task mode). Before 0.9.0 these
    files did not exist and downloads went to the namespace's temporary `~/Downloads` and vanished when the browser closed (a real
    incident; the GLib test in the namespace is `tests/test_oturum_tamir.py`).
  - **Not visible in the background:** `/tmp` (empty tmpfs: `/tmp/claude-*`, scratchpad included), non-XDG home folders and the
    user's `~/Downloads` (if the XDG name is different) are INVISIBLE to the application. Put the file to be given to a file picker/an
    upload in an XDG folder such as `~/Downloads` and type the full path with Ctrl+L in the file dialog.
  - **Cache:** copies live in RUNTIME_DIR (memory); the Firefox disk cache is 64 MB (user.js `browser.cache.disk.capacity`), Chromium
    `--disk-cache-size`. Live copies are not deleted when they exceed the count/size limit, a warning is added to the description.

  **What it does not protect (deliberate / remaining risks):**
  - **Reading:** the application CAN READ the XDG data folders (documents, downloads, desktop…) and the whitelisted appearance
    settings; secrets placed in data folders (e.g. `~/Desktop/passwords.txt`) are open. The rest of the home directory (each
    application's settings/session files, other directories in the home root) is invisible. The price: programs in the home
    directory (`~/.local/bin` scripts, `~/Games`, `~/Applications` AppImages) and the application's own settings (Dolphin bookmarks,
    Kate sessions, Konsole profiles) are NOT in the background — if needed `ev` per application in the policy. Which application opens
    in the background is the business of the session policy (copy/wait/off/on).
  - **Data folders are writable:** the application can change/delete the NORMAL files in `~/Downloads`, `~/Documents`, `~/Projects`…;
    it can create NEW hidden entries (e.g. a new `.git/` or `.envrc` in a subdirectory that has no `.git`: if the user runs git/direnv in
    that directory, code can run outside the isolation) and it can write files that the user may run later, such as `Makefile`, `*.desktop`
    (in the Desktop folder, visible on the user's desktop). Existing hidden entries are read-only; new hidden entries created after
    start-up and anything below depth 6 are not overlaid.
  - **Network:** the network namespace is shared (so that a browser can reach the network; no `--unshare-net`): the application can
    connect to local network services (ports on 127.0.0.1: e.g. the qBittorrent WebUI, development servers) and to ABSTRACT unix
    sockets. On this machine abstract sockets were found only as ICE and X (`:0`, keyed: since the Xauthority is not visible the
    connection is REFUSED, measured); the ICE (ksmserver) abstract socket requires ICE authentication.
  - **The IPC namespace is shared** (for X MIT-SHM): SysV shared memory/semaphores/message queues are common with the same user's other
    processes.
  - `/dev/dri` (GPU) is open: the GPU driver is an attack surface.
  - Sockets/FIFOs that appear AFTER start-up in data folders or in whitelisted directories are not masked (they can be connected to
    because the directory is real); the rest of the home directory does not exist at all in the namespace.
- **Audio (both types).** Background applications NEVER reach the user's sound server (pipewire/pulse): neither playback nor recording
  (microphone). The sockets are invisible in the namespace (`/run/user/UID` is an empty tmpfs). Two cases (`ses_ortami_uygula`):
  (1) default: the environment is redirected to a non-existent socket, applications play silently; (2) LISTENING (round 3): if the
  session's private sound server was set up (`ses.kur`; with `manage_desktop(start, audio=true)`, the first `listen` call or the setting
  `[dinleme] ozel_ses = true`) the environment points ONLY to its PULSE socket. The private instance: `ses/` in the session directory
  (0700; PipeWire sockets `pipewire-0`/`-manager`, configuration, logs) and `ses/pulse/` (0700; only `native`), its own configuration
  (ALSA/Bluetooth/camera plug-ins and device factories are NOT loaded, WirePlumber only the `policy` profile, XDG/HOME in the session
  directory: the user's settings/filter chains are not read). Module loading in pipewire-pulse is OFF (`pulse.allow-module-loading =
  false`, `pulse.cmd` empty): `load-module` (tunnel, LADSPA, pipe, TCP…) is refused. Inside there is only the `deskhand-sessiz` output +
  its monitor: no microphone, sound NEVER goes to the user's speaker/headphones, the user's default output/level/modules do not change.
  ONLY `ses/pulse/` is bound READ-ONLY into the application's namespace (`ses_bagi`); PipeWire's fully privileged sockets,
  configuration and logs are not bound, PIPEWIRE_REMOTE is a non-existent path. The socket path is built from the working directory,
  not from the record, and is checked against the real file system (`ses.soket_hazir`); before Deskhand's `parec` connects,
  `ses.soket_denetle` (directory/socket type, owner, hard link, peer = the recorded `ses_pulse`). Defence in depth: the three sound
  processes in a SINGLE bwrap namespace (`ses.sunucu_argv`: separate user/PID/network/IPC/UTS — no network; read-only root; /run, /tmp,
  /var/tmp, /home and home, /mnt, /media, /srv, RUNTIME_DIR empty tmpfs; minimal /dev: no snd/dri/video/hidraw; the only writable path
  is `ses/`; RLIMIT_NICE/RTPRIO 0), process number 1 a small supervisor shell (`ses_pw`; when it dies the kernel kills all), in the
  desktop's memory cage with nice 10 + ionice idle. The three processes are in the same PID namespace: PipeWire data flow cannot be
  established across separate PID namespaces (measured). If it cannot be set up (tool missing, did not start, unexpected device) the
  feature stays off and a warning is returned. Flatpak applications stay with `--nosocket=pulseaudio` (it would override their own
  sockets): their sound cannot be listened to. The old empty-output (null sink) arrangement and the sound guard are no longer set up.
- **Listening (`listen`).** `dinleme.dinle`: recording IN MEMORY from the monitor of the private output with `parec` at 16 kHz mono s16
  (at most 120 s; `until_silence`: ends early on silence after sound was heard) → if no sound was ever heard the engine does not run →
  `whisper-cli` (`-mc 0`, silero VAD if present, model `[dinleme] model`; if missing an explicit error + an installation hint, NOTHING is
  downloaded) → `{text, segments[{t0,t1,text}], language, duration}`. Temporary WAV/JSON only in `<session>/dinleme/` (0700, files 0600;
  applications do not see it) and deleted when the job ends; old recordings left after a crash are deleted at the next recognition.
  whisper-cli runs in the desktop's memory cage with nice 10 + ionice idle; the engine's absolute path only from a chain owned by root
  (`arka_ortak.arac`); `HSA_OVERRIDE_GFX_VERSION` is passed on only if it is defined in the user's environment. If the user is in a game/
  full screen the GPU is not used (`-ng`, CPU, at most 4 threads). The recognised text is NOT WRITTEN to the log (only duration/language/
  segment count). The result is labelled "untrusted data" through the `warning` field (command injection through audio). The user's REAL
  screen audio does not exist in this version: `desktop="foreground"` is refused.
- **Application environment (both types).** `arka_ortak.ortam_tabani`: the variables that belong to the user's session (the real bus
  path, WAYLAND_DISPLAY/DISPLAY/XAUTHORITY, AT_SPI_BUS_ADDRESS, SSH_AUTH_SOCK/SSH_AGENT_PID, GNOME_KEYRING_CONTROL,
  LIBEI_SOCKET/EIS_SOCKET, SESSION_MANAGER, KDE_FULL_SESSION, PULSE_*/PIPEWIRE_*/IBUS_*) are removed BEFORE and AFTER merging;
  `GSETTINGS_BACKEND=memory` (nothing is written to the real dconf), `ATSPI_DBUS_IMPLEMENTATION=dbus-daemon` (so that the accessibility
  launcher cannot reuse the user's real a11y bus with `dbus-broker --scope user`). `XDG_RUNTIME_DIR` is the desktop's own folder
  (`<work>/run`, 0700). The HOME variable is the user's; the directory itself is an empty tmpfs + whitelist in the namespace (above).
- **Safe helper binaries (both types).** Every helper Deskhand runs (bwrap, nice, ionice, sh, systemd-run, busctl, env, dbus-daemon, Xvfb,
  openbox, kwin_wayland, Xwayland, prlimit, setpriv, kdotool, wl-copy/wl-paste, find, pactl, at-spi2-registryd, the python3 that runs the
  guards/the clipboard owner/the notification catcher) is found with `arka_ortak.arac()` NOT through PATH but with an absolute path only
  from `/usr/bin`, `/bin`; the path is resolved component by component and every component (every symbolic link in the chain included) must
  be owned by root, directories not writable by group/others, the final file owned by root, not writable by others, executable; otherwise
  Dur 9. The cage gate with `/usr/bin/sh`; the application's PATH only to the final command. (Audit 12c Y2: the head of PATH was the
  writable `~/.local/bin`; a fake `bwrap` left there made all later launches unisolated.) The Python interpreter is the running
  interpreter if it is safe, otherwise `/usr/bin/python3`. The Flatpak wrapper looks for `flatpak`/`systemctl` only in `/usr/bin`, `/bin`.
- **Test share (test suite only).** `DESKHAND_TEST_PAYLASIM` (set by tests/_yalitim.py) is bound writable into the namespace — so that the
  event logs of the test windows reach the test (/tmp is empty in the namespace). Only a directory named `deskhand-test-*/paylasim` in the
  temporary directory, owned by the user, 0700, not a symbolic link is accepted; any other value is ignored (the home directory and sockets
  cannot be opened through this path).
- **Closing with a stale/tampered record (both types).** A signal goes to a PID only if its start time is the same as in the record
  (`arka_ortak.pid_kaydet` / `pid_dogru`) and, if there is a cage, it is in the cage; the cage is emptied only if it has the form
  `deskhand-kwin-<id>-N.scope` / `deskhand-sanal-<no>-N.scope`; the deleted directory is `RUNTIME_DIR/kwin-<id>` / `sanal-<no>`, not the path
  in the record; the X lock/socket only for :120+ (Xvfb :90+) and if the lock is dead or belongs to the server in the record.
- **Dead server.** The priority guard watches the display server (KWin/Xvfb; PID + start time): if it dies from SIGKILL/OOM it empties the
  cage (SIGTERM, 2 s, SIGKILL), deletes its own X socket/locks and the working directory, and exits. Only on "certainly dead"
  (`oncelik_bekcisi.kesin_olu`: no process/ESRCH, zombie, or a different start time); if `/proc/<pid>/stat` is TEMPORARILY unreadable
  (EACCES, memory pressure…) a live session is not closed.
- **Peer verification cache (KWin).** The successful result of `_karsi_denetle` (socket inodes, PIDs, start times) is valid for ~1 s under its
  key: with frequent commands a socket is not reopened for every connection; if the socket changes or the process is reborn the key changes
  and it is verified again.
- **Private D-Bus hardening (both types).** `UpdateActivationEnvironment` and `ReloadConfig` are refused; there are no standard service
  directories, only org.a11y.Bus can be activated.
- **Low priority (both types).** The cage starts with nice 10 + ionice idle; KWin is opened with `no_new_privs` (the file capability
  cap_sys_nice is NOT GIVEN), RLIMIT_RTPRIO=0 and RLIMIT_NICE (lowest nice 10); against name-based system rules (ananicy: `kwin_wayland` →
  nice -12) the cage's priority guard (`oncelik_bekcisi.py`) drops every thread within ~0.5 s back to nice >= 10, non-real-time scheduling
  and idle I/O. XWayland runs under an alias (`deskhand-xwayland`).
- **Approval scope** (`ayarlar.toml` `[guvenlik] onaylar`; panel Settings → "Approval questions"; `guvenlik.onay_kapsami()` is the ONLY place that
  reads the mode, ~1 s cache; an unreadable/invalid value = `hepsi` (all)). THE PANEL IS AUTHORITATIVE (`liste_koruma.kapsam`): CLI/MCP get the
  value not from the file but from the panel's verified approval channel (`liste onaylar`); panel closed / channel cannot be verified / old
  panel → `hepsi`. At start-up the panel accepts the `kart` (card) in the file only if its own marker (`liste-onaylar.isaret`) is also `kart`;
  `kart` without a marker → `hepsi` + the file is written back + a warning. If the file is changed by hand while the panel is open, the panel's
  value is kept. The only way to change is the panel's Settings (agent input cannot go to the panel window). The default is **`hepsi`**: ALL the
  approvals above unchanged (today's behaviour). **`kart`** (a conscious choice for the user's own computer: "ask only for card payments") asks for
  approval only in these two classes: (1) money buttons (`guvenlik.PARA_DUGMESI`: satın al, hemen al, öde, ödemeyi tamamla, siparişi onayla/tamamla,
  buy now, pay, place order, complete purchase, confirm payment… — the money subset of HASSAS + the final order/subscription/donation buttons:
  place/submit/complete order, confirm (and) pay, siparişi ver/gönder/onayla/tamamla, onayla ve öde, bağış yap/donate, ödemeyi yap/tamamla;
  "Devam Et"/"Continue", "Abone ol"/"Subscribe"/"Subscriptions", "Onayla ve Bitir", and the status text "Siparişiniz onaylandı/gönderildi" are NOT
  counted as money buttons (the user: ask only when paying with a card); also outside the payment page) and EVERY click plus Enter/space on a
  payment/order page — the page pattern is NARROW in `kart` mode (`guvenlik.HASSAS_SAYFA_KART`: checkout, ödeme [except payment history/my
  methods], sipariş özeti, siparişi onayla/tamamla, order review/summary, place order, payment details/information/page/step, billing
  details/information, 3D Secure/Doğrulama; NO `kasa`, and no `billing`/`payment` alone: "PC Kasa Modelleri", "Payment Request API", "Google Cloud
  Billing" do not ask), in `hepsi` mode the broad `HASSAS_SAYFA` unchanged (`hassas_sayfa_kalibi()`) — even if the button text can be read, the name
  the agent gives or the text next to the point ("Toplam 249,90 TL") does not enter the decision, there is NO exemption (with a saved card the
  card-typing gate never triggers; this gate catches the final order click) (`hassas_engel`, `hassas_sayfa_engel`, `hassas_nokta`, AT-SPI/web
  sensitive element); (2) typing card information (`guvenlik.kart_bilgisi_engel`: typing, typing by pasting, AT-SPI value typing; if the target
  field is a card field — AT-SPI/web name, label, description or autocomplete/id/placeholder: kart numarası, card number, cc-number, cvc/cvv,
  güvenlik kodu, son kullanma, expiry — or the text contains a 13–19 digit number that passes Luhn: with space/dot/dash/slash separators, double
  spaces, with extra digits/expiry/CVV attached). FALSE ALARM rules (`guvenlik.kart_numarasi`): the separator is only space/dot/dash/slash (at
  most 3; a line end/Tab ENDS the sequence, and so does the buffer); sequence ≤23 digits; the window must match a card-family prefix + length
  (Visa/MC/Amex/Troy/Diners/JCB/Discover/UnionPay/Maestro) AND Luhn, starts only AT A GROUP START, every group except the LAST must be 4–6 digits;
  a date (`22.11.2026`) and a valid IBAN (mod-97, `TR33…`) are not candidates. Measurement (4000 samples each): random 30/50 digits, TR/DE IBAN, two
  dates, a table of 20 numbers, TC id + phone, small numbers with spaces 0%; an order number of 10–14 digits 0.03% (formerly 69%/94%, 48%, 10%,
  100%, 38%, 30%, 4%). Known limit: an attached 16-digit order number with a card prefix (4/5/34/37/6…) can still raise an alarm by Luhn chance (~10%
  × prefix probability).) Text WRITTEN to the clipboard also goes through the same check (`guvenlik.pano_yazma_engel`: API `pano_yaz`, MCP
  `clipboard write`, CLI `pano yaz`); chunks written to the same window within 60 s and digit keys (`tus`/`bas`) are merged and tried in a small
  in-process buffer (only the digit sequence of ≤48 characters at the END of the text, memory only) (`guvenlik.kart_tampon_denetle`; in the CLI every
  call is a separate process: the buffer works only in the MCP/Python API process; a click empties the buffer of that window, an expired record is deleted
  when read; the text length is not truncated). In the approval request only the last 4 digits are visible; in `kart` mode EVERY `yaz`/`tus` input that
  puts a digit into the buffer (and text with ≥8 digits) counts as `gizli` (hidden): in the log `type ***(n)`, `key/keydown/keyup ***`, label `tus ***`
  (`guvenlik.gizli_satir`/`gizli_etiket`; kde/kwin/sanal backends) — the full number or a card digit is not written to the log. In these two classes the CLI
  `--onayli`/`--approved` is IGNORED (`guvenlik.onayli_gecerli_kati`): approval always comes from the panel (so that an agent with a free terminal cannot
  bypass it by calling the CLI with `--onayli`); refusal (10) when the panel is closed or in unattended mode. What stays free without approval
  (`guvenlik.onaysiz_serbest`: a single condition, a single log line `approval scope kart: passed without approval | …`): account deletion and OAuth
  "Authorize/Allow/Yetkilendir/İzin ver" buttons, system privilege/password prompts (`sistem_istemi_engel`/`_denetle`: polkit, KWallet, askpass, portal),
  typing into a password field (`parola_alani_engel`), Enter in a terminal/embedded terminal (`ucbirim.enter_kapisi`; the line warning only to the log, no
  OCR), typing a destructive command into a terminal, risky key chords, paste keys/menu paste and clipboard reading (MCP `clipboard read`, CLI `pano oku`),
  the MCP `open_app` approval of an unverified entry (`uygulama.mcp_uygulama`: the private copy + YN5 content digest check unchanged), the CLI `ac --komut`
  destructive-command approval. UNCHANGED (not approvals, refusal/protection): the agent's own client, the `open_app` blacklist, the ban on the
  panel/approval window, list protection, the forbidden window list and access levels, DUR, human priority, game/film protection (15), session lock,
  the refusal to read the VALUE of a password field, the pending-approval gate, post-approval target verification, background isolation. Limits: in `kart`
  mode the card approval IS NOT A HARD BOUNDARY: since the terminal is free it can be bypassed with raw input tools (dotool, xdotool, wtype…); chords
  such as `alt+sysrq`, `ctrl+alt+backspace` are also free; in unattended mode everything other than cards runs without approval. As with list protection,
  a process that, WHILE the panel is CLOSED, forges both the settings file and the marker consistently (computing the sha256 and writing it to STATE_DIR)
  can get `kart` through the next time the panel opens; a number written piece by piece in separate calls (in the CLI, separate processes), spread beyond the
  buffer time (60 s), or written in another form (encoded, in letters) into a field not marked as a card field cannot be caught; the pre-approved
  (`--onayli`) step approval of `run_flow` is not affected by this setting.
- **Account sessions** (`ayarlar.toml` `[guvenlik] hesap_oturumlari` = a comma-separated subset of `microsoft`/`google`/`edevlet`; panel Settings →
  "Account sessions"; the default is **empty = all closed**). The site refusal list of the session policy (`data/oturum.toml` `[site] reddet`) also filters
  identity-provider sessions in the Firefox copy on the invisible desktop: `login.live.com` / `login.microsoftonline.com` (with the domain-cookie rule
  `.live.com` MSPAuth/WLSSC too), `accounts.google.com` / `securetoken.googleapis.com` (`.google.com` SID…), government entries. If the user permits a
  provider, `firefox.hazirla` copies with the policy `Politika.kimlik_izni_uygula`: ONLY the full entries of that provider (`politika.KIMLIK_ALANLARI`:
  microsoft → 2 sign-in domains; google → 2; edevlet → `*e-devlet*`, `*edevlet*`, `turkiye.gov.tr`, `gib.gov.tr`, `sgk.gov.tr`, `*.gov.tr`; the US `*.gov` is
  NOT) leave the refusal list → the cookies of those domains (session cookies included), the saved logins (`logins.json`/`logins.db`; Firefox fills the
  password, the agent does not read it; `key4.db` is copied anyway) and, if `--site` was given, its storage enter the copy. Bank/payment patterns (`*bank*`,
  `*odeme*`, `*payment*`, `*checkout*`, `*paypal*`, `*stripe*`, banks, iyzico, PayTR…) are in no provider: if a domain matches any remaining entry it is
  still refused (`ebank.gov.tr` is refused even with the e-Devlet permission). **In task mode (`DESKHAND_GOREV=1`) the permission is NEVER applied**: `hazirla`
  does not ask for the permission, identity cookies are always filtered. The copy description (`open` output, `oturum hazirla`) and the `doctor` line give a
  summary ("identity sessions: Microsoft transferred (5 cookies, 1 saved login); Google filtered (… permission off)"); the last summary is in
  `RUNTIME_DIR/oturum/kimlik-son.json` (information only, not read for decisions). Since the permission goes in the direction of LOOSENING, the same PANEL
  AUTHORITATIVE model as the approval scope (`liste_koruma` KIMLIK): CLI/MCP take the value not from the file but from the panel's verified channel (`liste
  kimlik`; the channel is read-only, there is no write command); panel closed / cannot be verified / old panel → NO permission. At start-up the panel accepts of
  the providers in the file only those that are also in its own marker (`liste-kimlik.isaret`); a provider without a marker → the file is written back +
  a warning. A provider added to the file by hand while the panel is open is rolled back (`denetle`); removing it from the file or deleting the file is
  accepted (tightening). The only way to turn it on is the panel's Settings: the master switch ("Accounts I am signed in to … except bank and payment sites")
  opens the three together, the boxes one by one; on opening a confirmation dialog (default No), closing without a question. Limit (the same as the approval
  scope): a process that, WHILE the panel is CLOSED, forges both the settings file and the marker consistently can get the permission through the next time the
  panel opens. While the permission is on, the background browser can reach the e-mail/files of that account; an untrusted page can fool the agent (the panel's
  warning text says this).
### 4.z Input and privacy details (0.9.0)

- **deskhand-eis character mapping**: first a key that exists in X11 (evdev ≤ 247; xkb code ≤ 255), then the fewest modifiers; if a
  printable character is only on a non-X11 key it is `yazilamaz` (clipboard path). Diagnostics: `plan TEXT`, `--harita-sina`.
- **Power/lock keys** (`guvenlik._GUC_TUSLARI`): power, sleep, wakeup, screenlock (coffee/XF86ScreenSaver), suspend, hibernate,
  logoff — canonical names from `_TUS_ESANLAM`/`_EVDEV_AD`/`_KEYSYM_AD`; a single key without a modifier is also `riskli_tus`
  (approval). So are `ctrl+alt+shift+delete/pageup/pagedown`.
- **Control characters**: `eylem.denetim_karakteri_denetle` (k_yaz, yaz_ic, yazima_hazirla, erisim.k_ogeye_yaz); the backends'
  `yazilabilir_mi` is False for Cc.
- **Hidden text**: `yazima_hazirla(gizli=True)` does not change characters; a sequence/flow step is masked with `eylem.adim_metni`;
  `girdi_merkezi.uyari_maskele` masks dotool character warnings always in the hub log and, for hidden sending, on the client; the log has
  no hidden-chunk length (`gizli_satir` → `type ***`); `_gizli_pano_temizle` deletes the hidden chunk from a clipboard that cannot be restored.
- **Unreadable browser page (R1)**: `dogrulama_sinamasi.okunamayan_klavye_engeli(k=…)`: input after Tab is always refused; if the sequence has
  Enter/Space, `erisim.odak_bilgisi(k)` (a single bounded DFS, the value is not read: `rol`, `belge_ici`, `duzenlenebilir`) → outside the document
  or editable: allowed; otherwise/unknown: refused.
- **Real-screen lock and approval**: `onay.iste_sonuc` applies the lock only when the target is the user's screen; `guvenlik.sayfadan_cikis`
  (only `gezin.adrese_git`): address + Enter, if the focus is outside the document it is exempt from the payment-page approval.
- **Web value mask** (§9): `web._ayrinti_ekle` filters the input value with `erisim._deger_temizle`; since Firefox may give an empty attribute on the
  first query it is asked once more. The `web.tarayici_mi` class is split by `. - _` and spaces.
- **CLI read commands** `gorsel.korumali_goruntu` → `api.goruntu_al` (forbidden target 10, other forbidden ones black).
- **Masked-image path rule (0.9.1, SINIF-MASKE)**: every frame whose pixels, or text derived from them (OCR, a colour-region coordinate,
  `text at the point`, a match list, a Dur message), leave the process (to the agent, into an MCP result) is taken through the
  `gorsel.korumali_goruntu` / `api.goruntu_al` path. This path reads the forbidden-window list BEFORE and AFTER the frame
  (`maske_kare.iki_okumali_kare`). The union of the two positions is blacked out; the position before the frame of a window that became
  forbidden after the frame also enters the union (`Geometriler.tum`). A window that closed or left the forbidden list during the frame and an
  unreadable list give `Dur(8, tur=maske-yarisi|maske-okunamadi)`; the frame is not sent. In this case `korumali_goruntu` tries at most 3 frames
  with a short wait; retrying starts only before a 2 s deadline and the stability wait (`son_tarih`) ends at that deadline (total ≈ 2 s + one
  frame/list read); a long flow and `bekle` do not fall in a single race. In the terminal Enter gate the Dur messages returned to the agent (10 and
  the real-screen lock 17) carry a generic action text, the line that was read stays only in the panel. The raw frame (`gorsel.pencere_goruntusu`,
  `_pencere_goruntusu`, the backend `.goruntu`) is used only in internal work where the pixels do not leave the process. These are: the approval
  target fingerprint (`onay_hedef._goruntu`), the image of the human approval panel (`guvenlik.hedef_goruntusu`), the line reading of the terminal
  Enter gate (`ucbirim._ocr_satirlar`; the Dur message to the agent carries no word derived from OCR, the detail is only in the panel), the
  re-check before a click in desktop mode (`eylem.k_metne_tikla`, bool only; an accepted 1-bit limit) and the panel preview. The allow list, its
  justification and the number of references in each function are kept in `tests/test_guv_sinif_maske.py` (`IZINLI`). The test turns red however the
  name appears: name, attribute, import alias, string constant or getattr/vars/`__dict__` (a new caller and a new frame added to an allowed
  function included). Known limits: this gate is a trip wire, not a sandbox (a name built at run time is not seen); the intermediate position of a
  forbidden window that is DRAGGED between the two reads is not blacked out; the cost of the two list reads was not measured.
- **CLI automatic title lock**: `cli.otomatik_baslik_kilidi` (yaz/tus/tikla/dizi/kaydir given with an id and without `-b` → `^…$`; `--no-title-lock`).
- **MCP result contract** (§10): the `arac` and `okuma_araci` wrappers also turn an unexpected exception into `hata_sonucu` (`[9]`); `mcp_adlari`
  turns CLI options into MCP parameter names.
- **Human priority**: after a window, settling is awaited for a single short 'active' (`YANSIMA_PAY` 0.5 s, `YANSIMA_SURE` 0.04 s); if the activity
  helper reports v1 the watcher is ignored.
### Desktop ownership (CLI) and desktop selection (0.9.0)
- The desktop that `desktop start` and `open --background` open on their own is written to the nearest `claude` process in the caller's ancestor
  chain (`masalar.cli_sahiplen`; the owner file kind is `cli`; human/task mode/panel excluded). Another Claude session → 14; a named `cli` desktop
  whose owner died is swept like `oto` (`masaustu.oto_temizle`). `desktop stop` deletes the `masa/<name>` directory of a named desktop (if there
  is no live MCP owner).
- MCP automatic binding: if the default desktop is ownerless but alive and has an application in its cage (the topmost `bwrap` process,
  `masaustu.uygulama_pidleri`) it counts as BUSY → `oturum-N` (if the same Claude session opened the desktop — `baslatan_ajan` in the state record
  is in the ancestor chain — it is shared).
- CLI: `--desktop-name NAME` is accepted in every position up to the command name and after the command; if given (or `DESKHAND_MASAUSTU`) the target
  is automatically the background. zsh note: a variable with spaces is not split — use `export DESKHAND_HEDEF=arka DESKHAND_MASAUSTU=name` or an
  array (`ENV="A=1 B=2"; $ENV command` does not work).
- In an identity session copy, going to Microsoft/Google SIGN-OUT addresses does not yet ask for approval (an open item; signing out of the copy can
  also close the main session at the provider — do not sign out in the copy while the identity permission is on).

## 5. Exit codes
0 ok · 1 usage error · 2 point outside window/screen · 3 not active/another window · 4 title/class lock did not match · 5 ambiguous (several matches) ·
6 not found · 7 timeout · 8 window missing/moved · 9 tool missing (dotool/tesseract/Xvfb…) · 10 forbidden/sensitive · 11 flow error screen ·
12 a human is using it ·
**13 the user said STOP (DUR)** · **14 virtual desktop closed** · **15 the user is in a game/watching a film, no interference with their screen** ·
**16 the application cannot be opened in the background** (open on the user's screen or foreground only) ·
**17 the real screen is closed in this process** (`DESKHAND_GERCEK_EKRAN`, see §6) ·
**18 human verification (CAPTCHA) pending: agent input refused, hand over to the user (`request_human`)** ·
20 / 21 `decide` decision codes: 0 = the user's screen, 20 = background, 21 = later.

Calling automation must stop at 10, 12, 13, 15, 16, 17 and 18 and notify the user. On the MCP surface the same codes appear as an error
`[code] name: detail`. This table is kept consistent with the "Exit codes" table in the README.

## 6. Working rules
- Tests redirect the `DESKHAND_*_DIR`s to a temporary folder; the real `~/.config`, `~/.local/state` etc. are not written.
  Compare the sha1 of `~/.config/deskhand` (and the old `~/.config/ekran` if it exists) before/after a long run.
  When adding a new write path, verify that the tests really simulate it.
- Real-screen tests: no test/command that sends input to the REAL screen (tikla/yaz/tus with the kde backend, `tests/ekranli/`) is run while the user is
  using the computer (film, game…); they are run only by hand, when the machine is idle. Virtual desktop (Xvfb) tests are free.
- **Real-screen lock (structural):** if `DESKHAND_GERCEK_EKRAN=kapali` is set, every path that affects the user's REAL session is refused with
  `hata.gercek_ekran_denetle()` IMMEDIATELY before the real tool is run (Dur 17, explicit message): input (the `kde.Girdi` set-up, `kde.dotool_ac`,
  the input-hub connection), `kdotool` words with side effects (activate/move/resize/minimise/close… `kde.calis`), application launch (`kde.baslat`),
  clipboard writing (`kde._wl`), notification (`mesgul.sor`), the accessibility setting on the user's session bus and AT-SPI action/writing (`erisim`).
  Paths that read the CONTENT of the user's screen/clipboard (screenshot, `wl-paste`) are also closed; the value `salt-okuma` (read-only) leaves these
  (reading only) free. Window list/title/geometry, lock/idle state and AT-SPI reading stay open. An unrecognised value counts as `kapali`. When it is
  not set the behaviour is exactly the same; `doctor` shows the "Real screen" line if it is set. The invisible desktop (`sanal`, `kwin`) and the
  test fake backends are not affected. RULE: measurement/test scripts import `tests/_yalitim` (which sets the lock) or set the variable themselves; only
  `tests/ekranli/`, which deliberately touches the real screen, removes it. Tests that replace the real tool with a fake binary set the lock to `acik`
  themselves.
- Do not use `pkill -f PATTERN` (it can kill your own shell); stop processes by PID.
- Personal data: no user name, real home directory, account name or dated personal incident note in code, comments, tests and documents. The design
  reason may remain in a comment; without date and person.
- Run heavy jobs (long scans, big tests) in a cage with limited memory (e.g. `systemd-run --user -p MemoryMax=…`) and one at a time.
- Git: run the tests before committing changes; if several people/tools work in parallel, each commits only its own files.

## 7. Design decisions
A summary of the decisions that entered the interface contract over time (details in the relevant sections):
- **ArkaUc extension.** Optional methods have defaults (`kimlikler`, `klavye_duzeni`, `yazilabilir_mi`, `gecerli_tuslar`, `pid`, `etkinlestir`,
  `etkinlik`); `baslat` takes a `cikti` parameter and `env` is ADDED to the current environment in both backends (§2).
- **DUR atomicity.** DUR is checked per `gonder()` call, not per line; so sequences that must not be split, such as a double-click, are not left half
  done (§2).
- **DUR ownership.** A DUR set by the user cannot be lifted by the CLI; the dur file carries the source (`kullanici`/`cli`) (§4).
- **Clipboard + typing by pasting (phase 9a).** `eylem.yaz_ic`: a character not in the keyboard layout (emoji…) or text longer than 200 characters is put
  on the clipboard and pasted (ctrl+shift+v in a terminal, otherwise ctrl+v); `\n` stays Enter and `\t` stays the Tab key (between the chunks). The old
  clipboard is taken first and restored also on error/DUR/interruption; all safety checks (sensitive-page approval on the full text, title/class lock,
  DUR, watcher, human priority, foreground protection) run in every `gonder()`; the paste key goes through `Girdi`. MCP `clipboard`, CLI `pano`: reading
  in the foreground asks for human approval (except for text Deskhand wrote in this session), free in the background (§2, §4).
- **No foreground during a game/film.** While the user plays a game or watches a video Deskhand does not interfere with the real screen (code 15); the
  only exception is explicit user permission. The virtual desktop is not affected (§4).
- **The forbidden list is empty by default.** Deskhand is a "click tool"; the user decides what to forbid. Only Deskhand's own panel/approval window is
  always forbidden (§4).
- **Risky action = approval, not a ban.** Forbidden lists stay empty by default; keys that end the session and destructive commands typed into a terminal
  ask for human approval (against indirect command injection), and application access levels also do not exist by default (§4). In unattended mode
  approval is never asked, it becomes a refusal.
- **Virtual screen safety.** A virtual X connection is opened only to a verified `:N` display; an empty `DISPLAY` never falls to the real desktop (§4).
- **Take over and notifications.** On the virtual desktop the user can take control with "Take over" (Devral); this state and the notifications are kept in
  the state directory (§2).
- **Input hub.** The kde backend sends input through the panel's ready dotool (no set-up wait); the safety checks stay on the client unchanged, the hub
  checks DUR separately and releases the held keys of a dropped connection (§2, §4).
- **KWin type of the background desktop (phase 12b).** When the conditions are met the background desktop is an isolated KWin session (Wayland-native
  applications, GPU acceleration, those wanting X11 use the session's XWayland); otherwise Xvfb. The external surface does not change (§2, §3, §4). Known
  limits: a Wayland pop-up menu/drop-down list (xdg_popup) opens only with a real input event → the AT-SPI "Show Menu" action cannot open a menu (the mouse
  path works), the items of a drop-down list are not visible in the tree; a Wayland client can set the clipboard only after an input event; the root
  background is KWin's (not grey).
- **Session bridge.** Letting applications in the background use the user's account sessions is managed with a per-application policy (copy / share / wait /
  on / off); if the application is open in the user's session and cannot be opened in the background, code 16 is returned (see docs/SESSIONS.md).
- **Observe + ref + batch step (phase 10).** The MCP agent gets numbered elements and a `ref` with `observe`; in an action with a `ref` the element is
  re-verified BY ITS IDENTITY in the current tree and then goes through the EXISTING safe path. `batch` calls the same tool cores in order; no parallel gate
  is written. Every input result carries `effect`, every error `sent` + `next` (§10).

## 8. Approval protocol (common to UI + MCP + CLI)
For a sensitive action (sensitive button, payment page, `ac` that is not forbidden but risky, session transfer) approval comes ONLY from a human:
- `deskhand/onay.py`: `iste(eylem, hedef, ayrinti, masaustu, sure=120) -> bool`.
  Panel record: `RUNTIME_DIR/panel.pid` {pid, baslangic (field 22 of /proc/<pid>/stat), exe (/proc/<pid>/exe), cmdline (argv from /proc/<pid>/cmdline: since
  exe is the Python interpreter, the panel's module path/entry point), zaman}.
  **Approval channel:** the panel listens on the Unix socket `RUNTIME_DIR/onay/kanal.sock` (0600, directory 0700; `panel_kaydet` opens it, `panel_sil` closes it;
  a Qt-free threaded server). The requester FIRST connects to the channel and verifies the other side: the socket file and directory are its own and closed to
  others; SO_PEERCRED uid = its own uid, pid = the pid in panel.pid, the same start time, the same exe, EXACTLY the same cmdline and cwd as in the record, the
  deskhand package directory loaded by the panel (`paket` in the record) the same as the requester's. If it cannot be verified, refusal ("approval channel
  could not be verified", the reason in the log).
  The request: `RUNTIME_DIR/onay/istek-<uuid>.json` {id, eylem, hedef, ayrinti, masaustu, zaman, son_zaman, pid, goruntu}; then `bekle <uuid>` on the channel.
  The panel compares the SO_PEERCRED pid of the connecting party with the `pid` field of the request (another process cannot take someone else's decision). The
  panel (QFileSystemWatcher) opens a dialog: **Allow once / Refuse** (+ a small screenshot of the target). The decision comes back over the SAME connection:
  `karar izin|red <uuid>` (if the requester has not connected yet the panel stores it). **Permission comes only from the channel;** `yanit-<uuid>.json` {id,
  karar: "red", kaynak: "arayuz", zaman} is written only for a refusal and the requester counts every reply file (whatever its content) as a REFUSAL: a process
  of the same user that can only write files cannot produce a fake permission. If the time runs out, if the panel is closed/closes (the connection drops) or if DUR
  is turned on → refusal (message: "the Deskhand panel is closed, approval could not be obtained"). Single use; request/reply files are deleted when used. The panel
  hides the dialog before sending the permission (so that it does not cover the target during post-approval verification).
- **Re-verification after approval (MCP, `onay_hedef.py`).** Right before the approval request (while holding the lock) `yakala(k, bolge)` → `OnayHedefi` {k,
  masaustu, baslik, geometri, bolge (window pixels), ozet (fark.Once), zaman}; after the permission, under the lock, before the action `dogrula_dur(h)`: if the window
  is missing, the title/geometry differ or the image of the region changed (fark.py threshold; for a temporary overlay it looks again at 0/0.15/0.3 s) → Dur 10
  "the approved target changed; re-approval is required", the action is not performed. The region: for a click with coordinates the surroundings of the point (480×200,
  the same as the approval image), if the core's image carries `info["deskhand_bolge"]` that one, otherwise the whole window. In kde the image is taken only if the core
  already took the target image (focus is not stolen; otherwise only id/title/geometry); the full screen without a region is not compared with an image.
- CLI `--onayli` remains (if the user explicitly approved in the chat), NOT on the MCP surface. A risky key and terminal command also use this protocol (action text "Risky
  key: …" / "Type a command into the terminal: …"); in unattended mode `iste_sonuc` returns a refusal for the reason `gozetimsiz` without writing to the panel at all.
- **Request fingerprint and list verification (H3 review).** The requester writes `istek-<uuid>.json` and sends `bekle <uuid> <sha256 of the bytes it wrote>` (`onay.py`, `iste_sonuc`). The panel keeps the first hash per uuid; a file that does not match it, a second different hash, or no hash is refused (red, visible warning). The dialog gives back `(Yes, token)` where the token is the sha256 of the canonical entry lists it showed (`liste_koruma.gosterim()`); a Yes is applied only when that equals the requester's fingerprint, and the dialog never hashes widget text. `liste <kind>` may answer `dogrulanamadi` (list not verified: no signed record to compare with and no Yes from the user); a client then stops with Dur 10. A refused Yes comes back as `red` with the reason.
- **STOP is a set of sources** (`guvenlik.dur_ac` / `dur_kapat` / `dur_kaynaklari`): `kullanici` (the user's), `cli` (an agent's), `panel-kapali-basarisiz` (the panel could not read its signed record) and unknown labels. A source other than the user's removes only itself; the user's Resume removes all. `dur_kaldir_iste` (CLI `resume`) asks the panel with the request type `dur` (default No; panel closed, unattended mode or no answer → Dur 13; `--approved` is not an answer). The MCP `stop_by` field can return `panel-kapali-basarisiz`. Writes take a short lock that never blocks the STOP button.
- Warnings from the approval channel reach the tray through a queued Qt signal (at most one notification per reason per 10 s).
- The approval dialog window is automatically added to the forbidden list (class/title): no automation input goes to it.
- Threat model: approval prevents the agent (by mistake or through prompt injection) from giving itself permission and prevents a process that can only write files from
  producing a fake permission. It is not a sandbox for an agent that has a shell: a process that can run arbitrary code as the same user can kill the panel and take its
  place, or attach with ptrace.

## 9. Web page elements (the browser accessibility tree)
**Path.** `deskhand/web.py` reads the interactive elements of the page in a browser window (link, button, field, check/radio/select box, tab, menu item; name, role, state, a
box in WINDOW coordinates, link address, field value) from the AT-SPI tree. Tools: MCP `read_text(source="web")` (+ `role`, `offset`/`next`, `hidden`; page title, address,
`sensitive_page`), CLI `web <id> [query] [--rol R] [--hepsi] [--sayfa N]`, MCP `click(element=…, role=…)` and CLI `click-element`.
**Click path (`erisim._web_sec/_web_tikla`).** If the target window class is a browser/Electron, `element` is first looked for in the page (visible ones first, then invisible
ones; if not found, the general tree path = the browser UI). The `merkez` (centre) of the found element is given to the EXISTING `tikla_ic` path: a real mouse click, so DUR 13,
forbidden 10, title/class lock 4, access level 10, game/film 15 in kde, human priority 12 and the under-cursor check (`tikla_ic` → `Girdi.gonder`, `imlec_alti_denetle`) work
unchanged; the loop breaker and the difference summary are in the MCP `click` wrapper. The sensitive check is in `eylem.hassas_nokta`: the element's NAME is appended to the
target text (for a text-less `aria-label` button approval is asked even if OCR does not read the text), the document title comes from the tree and is checked IN ADDITION to
the window title (`hassas_sayfa_engel(ek_basliklar=…)`). A disabled element 6 (the same as the message of the general `ogeye-tikla`); an element outside the viewport is brought
into view with the existing scrolling path (`kaydir_ic`, with all input checks, at most 8 rounds, an error if there is no progress) and clicked. `via="action"`: through the Action
interface (NActions + GetName), no mouse/focus; the checks are the same as `_ogeye_eylem` (the element identity is kept as bus name + object path TOGETHER; also the system-prompt
approval).
**Frame (rule B2 on the web as well).** `web._cerceve_bul` chooses the frame ONLY among the connections in the window's process tree (the window's process or its descendants;
ancestors — the terminal/launcher that started the window — and Deskhand's own connection do not count); if the PID is unknown or there is no application in the tree 6, it does
not fall to another application by title similarity. The chosen frame is checked with `erisim._cerceve_denetle`: for reading (`read_text(source="web")`, CLI `web`, the search
before a click) the panel process / forbidden pattern 10; for an action (`web.eylem_yap`, the frame is re-chosen right before DoAction, the element must be in that frame's
connection, otherwise 8) additionally the agent's own client and the application access level 10. The value of a password field (`password text`) is not read. In the mouse path
the window-level checks are in `tikla_ic` (own client, system prompt, level, B3).
**Position verification (fail-closed).** On Wayland, elements can come in window-local coordinates, global client-area coordinates or global decorated-frame coordinates,
depending on the application. `web.konum_coz` determines the frame by comparing the bounds of the top-level frame (GetExtents SCREEN and WINDOW) with the window's known geometry
within ±1 px; if none matches the reading reports `konum_dogrulandi=false` and the click is REFUSED (code 2: "element position could not be verified; try clicking the text with
OCR"). On the virtual desktop (X11, a single frame) the check passes automatically.
**Why the accessibility tree.** A remote-control protocol (Marionette/BiDi) opens an unauthenticated local door and the page sees automation (`navigator.webdriver`); AT-SPI opens no
new door, is invisible to the page, and is the same in Chromium/Electron. Measurement (tests/web_olcum.py): coverage 100%, box difference ≤ 1 px, 1,000 elements ~0.25 s. The
Marionette client is ONLY in the measurement script.
**Background Firefox.** Since the virtual desktop starts its own accessibility registry before the applications and writes `IsEnabled=true`, Firefox opened with `ac --arka` serves
the tree without an extra environment variable (GNOME_ACCESSIBILITY) (test_web_bag.py).
**Limits.** An element that covers the TOP of another element (modal, sticky header) cannot be told apart from the tree; the under-cursor check is only at window level. On a real
(kde, Wayland) screen the coordinate frame has not yet been verified on the real screen: the assumptions of `konum_coz` (three frames, ±1 px, decoration margin limits) must be tried by
hand. If the window class is not in the list of known browsers `click-element` does not look at the page (the `web` reading and a click with coordinates still work). `ogeye-yaz` does
not exist for web fields.

## 10. The MCP observation surface: observe, ref, batch, wait_for, the result contract
**`observe` (read-only, `deskhand/gozlem.py` + `mcp_sunucu.observe`).** The elements of a window in a single call: in a browser the page (`web.oku`, `yol_ver=True`), otherwise the general
tree (`erisim.erisim_ogeleri(ayrinti=True)`: states, action names, value); if there is no tree / it is too small (< 3 elements with a name) or `include_ocr=true`, the OCR lines
(`api.metin_oku`; the same text is dropped in the box of an element in the tree). There is NO new read path: frame selection and its check (§4, §9: process tree, panel/forbidden
10) unchanged; a forbidden window 10; the value of a password field (`password text`) is never read on any path. If no window is given, the OCR of the whole screen. Output: a header line
(`snapshot <id> | window … | sources tree+ocr | N items`), on the web a page line (payment-page warning, "element clicks are refused" if the position was not verified), every element
`[N] role "name" state = "value" !sensitive (ocr)`; structured fields `ref`, `role`, `name`, `value`, `states`, `frame` (window pixels), `actions`, `sensitive`, `href`, `source`;
empty/default fields are dropped, U+FFFC and whitespace-only texts are dropped. `query="a|b"`: elements whose name/value/role matches + their ancestors THAT HAVE A NAME (child-order path
prefix). `max_elements` (150, ≤1000) + `offset` → `next_offset`. `since=<snapshot_id>` (same window): only `+` added, `~` changed (name, value, state, box > 3 px), `-` disappeared.
`include_screenshot`: element boxes + numbers are drawn on the masked window image (Set-of-Marks) and a `shot_id` is saved.
**Snapshot cache.** `snapshot_id` = a random 4-hex prefix per server (process) + a counter; at most 4 per window, 16 DIFFERENT contents in total, lifetime 120 s (an observation with the same
content as the previous one, e.g. a paged `observe(offset=…)`, joins the same group: the refs of the first page do not drop). Element identity: for an accessibility element bus name + object
path (TOGETHER; `_tara` reads them from the fields of the libatspi object, if unreadable the child-order path) + window; for an OCR line text + box.
**Action with `ref`.** `click(ref)`, `type_text(ref)` (the field is clicked first, then the keyboard path), `scroll(ref)`, `drag(from_ref, to_ref)`. Staleness is refused for three separate
reasons, WITHOUT sending any input (`[8]`, `error.reason`): `snapshot` (unknown / expired / dropped from the cache), `window` (another desktop or window, the window closed, its size changed),
`element` (the element is missing, its name/role changed, its box moved more than ±3 px, no such number). Element-level verification is done IN THE CORE and from the current tree (TOCTOU):
`erisim.ref_oge_sec` does NOT SEARCH the element BY NAME, it finds it by identity and compares name/role/box (it never falls to another button with the same name); `k_ogeye_tikla` / `_ogeye_eylem` /
`_web_sec` (`a.ref_oge`) continue with this selection through the EXISTING path: mouse → `hassas_nokta` (the element name in the target text) + `_onay_sonrasi_oge` + `tikla_ic` (`Girdi.gonder`: DUR,
`denetle`, level, own client, system prompt, under-cursor, human priority, kde game/film); `via="action"` → `_atspi_korumalari` + `_hassas_oge` + system-prompt approval; web → `_web_tikla` /
`_web_eylem` (re-finding by identity after approval `_web_yeniden`). The ref of an OCR line → `k_metne_tikla` (the text is read again within ±12 px around the ref box; if absent `[8] element`).
`scroll`/`drag` re-verify the ref's CURRENT centre under the lock (`_ref_nokta`), then `kaydir_ic` / `k_surukle`. There is NO approval parameter on the `ref` path; the pending-approval gate
(`kilitli(girdi=True)`), the loop breaker (target = element identity) and post-approval target verification (§8) apply unchanged.
**`batch` (at most 20 steps).** Tools only `click`, `type_text`, `press_key`, `scroll`, `drag`, `wait` (`{"seconds": 0-10}`, checks DUR every 0.1 s). All steps are verified WITHOUT sending anything
(the tool's own argument model, the same as the desktop batch's, the wait duration). Every step calls the CORE tool function in the module (`arac()` registers only the wrapper with MCP; the core
is the same lock/gate/approval/loop breaker). From the second step on, before every step DUR, a pending approval and human priority (`guvenlik.insan_onceligi`, at most 8 s) are checked again.
It stops at the first error: `failed_step`, `not_sent`, the `sent` value of the step and of the batch. If a step asks for approval the batch waits at that step; refusal = stop. `observe_after`
observes the window of the last step.
**`wait_for` (read-only).** `text` (name/value in the tree, otherwise OCR), `gone`, `element` (name + optional role), `window` (title pattern, a forbidden window does not count), `stable` (the
window image is the same for `stable_ms`, fark.py). The lock is taken and released at every poll; a timeout is not an error but `satisfied:false`.
In the foreground (kde) `text`/`gone`/`stable` do NOT BRING THE WINDOW TO THE FRONT: if the target is active, image/OCR; otherwise only the AT-SPI tree (if there is no tree `satisfied:false` + a
`note` once); while the user is active (`insan_var_mi`) polling is skipped and the time is counted. The behaviour is the same in the background. `batch` resolves `desktop=auto` ONCE at the start;
`click`/`type_text`/`scroll`/`drag` refuse a ref ([8]) if the window title changed since the snapshot and set up the title lock from that title.
**Result contract.** The result of the input tools has `effect`: `confirmed` (the expected change was seen: the checked/selected/expanded state of the clicked ref element changed, the typed text was
seen in the OCR of the changed region or the value was read back, the view changed on scrolling, the window geometry changed), `changed`, `no_change` (consistent with the loop breaker),
`unverifiable` (could not be measured: `via=action` in kde, `verify=false`), `refused` (error and nothing was sent). The error result (`isError`) text: `[code] what happened` + `sent:
nothing_sent | maybe_partial` + `next: what to do (with the tool name)`; the same in the fields `structuredContent.error` {code, message, reason, next}, `sent`, `effect`. The `sent` counter
(`gonderim.py`) increases on the return of `gonder()`/`ham()` of the `api.arka()` input object and right before an accessibility action/value-typing call; releasing (`zorla`) is not counted.
outputSchema: a TypedDict with fields for `wait_for` and `click`, a general object for the other input tools; NO outputSchema in `observe` and `batch` and a successful result is ONLY a short text
(structuredContent is not sent: the structured copy was ~5 times the tokens of the text). The observe line `[N] role "name" @x,y,w,h states = "value" !sensitive (ocr) (offscreen) href="…"`; in the
header snapshot_id, window id, sources; a `shot_id` line with include_screenshot. The batch text carries per step effect/changed_region/approved_by_user/warning and the stopping line. Error results
(in every tool) keep a small structuredContent. The automatic `title` texts in the schemas are removed.
**Limits.** In a browser window observe lists only the page (document): for the address bar/tabs `press_key` (ctrl+l) or `read_text(source="tree")`. Web elements are only the visible ones (those
outside the scroll area `read_text(source="web", hidden=true)`). In a system-prompt window (polkit, KWallet, a password asker) every kind of click — ref, text, element, icon, colour, coordinate,
`via=action` — asks for human approval before the target is searched (`eylem.sistem_istemi_on`; in unattended mode refusal → 10). `type_text(ref=…)` is two core actions (a field click + typing):
on a system prompt two approvals are asked.

## 11. Task mode (the panel's "Task" tab; `deskhand/gorev_kipi.py`)

The task agent (`claude -p`) reads UNTRUSTED web content (prompt injection): the mode limits the leakage of local files and saved passwords/sessions. `gorev.mcp_ortami()` → the mcp.json `env` is
ONLY `{"DESKHAND_GERCEK_EKRAN": "kapali", "DESKHAND_GOREV": "1"}`; the sites allowed in the task come from claude's environment through `DESKHAND_GOREV_SITELER`.
- **open_app** only a browser: a local package Firefox; the Chromium family only if a policy root (/etc/chromium etc.) exists (the session policy is already `on`); a Flatpak/Snap browser, terminal,
  file manager, editor, interpreter → 10. A document argument only http(s).
- **Home directory**: the XDG data folders (Desktop, Documents, Downloads…) are NOT BOUND to the background application; only the appearance whitelist + `RUNTIME_DIR/gorev-indirilenler` (at the user's
  XDG_DOWNLOAD_DIR path, writable). When the task ends the downloads are reported to the user (the `bitti` event: `indirilenler`, `indirme_dizini`).
- **Browser policy** is bound read-only into the namespace: for Firefox, in place of `<installation>/distribution/` a `policies.json` (+ the original distribution.ini): BlockAboutConfig/Profiles/Addons/Support,
  PasswordManagerEnabled=false (about:logins blocked), DisableDeveloperTools (about:debugging), WebsiteFilter `file:///*`, extension installation closed, a fixed download directory. The Chromium family: in place
  of `/etc/chromium` etc., `policies/managed/deskhand-gorev.json` (URLBlocklist `file://*`, `chrome://*`, password manager and developer tools closed).
- **Session copy** (Firefox): logins.json, logins-backup.json, logins.db, key4.db, extensions and their data are NOT COPIED; cookies/session cookies/storage ONLY of the allowed sites (if empty a COOKIE-LESS clean
  profile); user.js `signon.rememberSignons=false`.
- **Approval**: even if the scope is `kart`, the password-field + system-prompt approvals are ON (an exception to `guvenlik.onaysiz_serbest`).
- **Defence in depth**: observe/read_text/screenshot refuse (10) if the browser document is `file:`/`about:`/`chrome:`…
- **claude argv**: `--tools ""` (no built-in tools; the blacklist is a second layer), `--no-chrome`, `--max-turns` (`[gorev] azami_tur`, default 60). Environment: `ANTHROPIC_*` is removed;
  `ENABLE_CLAUDEAI_MCP_SERVERS=false`, `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. The temporary working directory is under `XDG_RUNTIME_DIR`.
- **History**: the `type_text` text is `[N characters]`; password/card patterns in the task text are masked; in the task box a "do not type passwords" hint, a short confirmation before Start (task +
  allowed sites + "browser only").
- **Task desktop (the distinction in the single-desktop architecture)**: since the state is in a single file (`sanal.json`, `sanal.lock`, a single audio output, the panel's watcher/Devral look at the same
  record) the task does NOT open a SEPARATE desktop; instead (1) if the invisible desktop is OPEN the task DOES NOT START: `GorevHatasi(kod="masaustu_acik")` → the panel asks "The invisible desktop is
  open for another job; close it and start?", with approval `masaustu_durdur()` and the task starts with a clean desktop (the mode-less Firefox/Dolphin windows of earlier sessions are NOT in the task); (2)
  when the task starts the marker `RUNTIME_DIR/gorev-masaustu` (owner PID + start time) is written, FIRST the marker then the open-desktop check (no race); the record of a desktop opened in task mode is
  `"gorev": true`; (3) `gorev_kipi.masaustu_kapisi` on every connection (arka_uc sanal/kwin, accessibility, `masaustu.baslat`, `masaustu_baslat`): task mode CANNOT USE a desktop without the `gorev` mark (14);
  a mode-less client (another Claude session, CLI `--background`) cannot connect to the marked desktop or while the marker exists / open an application / open a desktop (14, "try again when the task ends").
  The panel preview is free with `gorev_kipi.GOZLEMCI=True`. When the task ends only the desktop marked `gorev` is closed, the marker is removed.
- **Window limit** (`gorev_kipi.pencere_denetle`, `guvenlik.yasak_denetle` + from the reading tools): in task mode every input/read target is only a browser window — a class whitelist (firefox, navigator,
  chromium…) AND the window's process binary (`/proc/PID/exe`; the PID from X-Resource/KWin, the client cannot write it) is a browser. The class alone is not enough (it can be imitated). Another window
  ("Open" from the downloads panel → Kate, Konsole…) → the window is closed, if its process is in the desktop cage SIGKILL, an event in the log, Dur 10. Whole-screen (no window given) reading/input: only when
  there is no non-browser window on the screen and at least one task browser window. If the browser document is at a forbidden address (`file:`, `jar:`, `about:*` including `about:preferences`) both reading
  and input are refused.
- **Firefox policy addition**: `browser.download.forbid_open_with` (locked true: a downloaded file cannot be opened with an external application), `always_ask_before_handling_new_types` false,
  `open_pdf_attachments_inline` false, `alwaysOpenPanel` false; since Linux Firefox looks at `/etc/firefox/policies` first, if that directory exists the same policy is bound there as well. WebsiteFilter is in
  MatchPattern syntax (Firefox 160 WebsiteFilter.sys.mjs): `file:///*` is valid; the patterns `file://*/*`, `jar:`, `about:` are INVALID (Firefox discards them) → there is no policy path for `jar:file:` and
  `about:preferences`; the address check (above) closes them. Measurement: `tests/test_gorev_kipi.py` headless Firefox + Marionette (in the measurement only DisableDeveloperTools is removed, because that policy
  also closes remote control).
- **Namespace**: in task mode `xdotool`, `kdotool`, `ydotool`, `wtype`, `xauth`, `xdg-open`, `gio`, `kioclient`, `kde-open` are covered with an empty file (cannot be run); PATH `/usr/bin:/bin`.
- **Identity variables**: `gorev_kipi.KIMLIK_ORTAM_DENEN` (TOKEN, SECRET, PASSWORD, KEY, AUTH, COOKIE…) is removed from claude's environment (only `CLAUDE_CODE_OAUTH_TOKEN` stays; claude reads its login from
  `~/.claude/.credentials.json`), from the MCP server's environment (at start-up) and from the application environment (`ortam_tabani`).
- **Site list**: a wildcard (`*`), a generic suffix alone (`com`, `com.tr`, `co.uk`, `gov.tr`…; a small list `GENEL_SON_EKLER`) and an invalid name are REFUSED; the panel does not start the task, with an explicit
  message. UI warning: "On these sites the agent can act on your behalf (change settings, post, delete); untrusted page content can fool the agent."
- **The download folder** is emptied at the start of every task. **History**: in nested inputs such as `batch(steps=[{"text": …}])` secret keys are masked recursively.
- Remaining risk: while the task runs, the user can say `deskhand masaustu durdur` (`desktop stop`) with the CLI (closing only; no access). The window limit is applied at check time: a foreign window opened by
  Firefox lives on the screen until the next tool call (milliseconds–seconds); in the meantime it can run on its own (e.g. Kate) but the namespace (empty home, no XDG, input tools covered) and the policy
  (`forbid_open_with`) already close this path. The `about:preferences` page can open but cannot be read/take input.

## 12. Human verification (CAPTCHA) hand-over: detect, refuse, hand over, continue

**Policy (unchanging):** CAPTCHA / "verify you are human" challenges are NOT solved and not bypassed (visually, by audio or any other way). Deskhand only detects, refuses agent input, hands over to the user, and continues when it is solved.

- **Detection** (`deskhand/dogrulama_sinamasi.py`; `incele` is pure; text alone is NOT ENOUGH). Sources: (1) the address of an embedded document (iframe): `google.com/recaptcha`, `hcaptcha.com`,
  `challenges.cloudflare.com`, `arkoselabs`/`funcaptcha`, `geetest` (the invisible reCAPTCHA v3 badge `size=invisible` and hCaptcha `#frame=checkbox-invisible` are exempt). `web.oku` carries the address of the document
  each ELEMENT belongs to (`_belge_adres`): only the elements of the challenge document are marked (a YouTube embed, a Stripe card field, a chat box are not affected) and the WHOLE box of that iframe is the
  challenge area (clicking the label next to the checkbox also ticks the box); (2) element name + role: "I'm not a robot", "Ben robot değilim", "Verify you are human", "Slide to verify"… (a label of at most 6 words
  OUTSIDE a frame; the settings "Require human verification" / "Move the slider to set the price" / "Enable CAPTCHA" do not count), a vendor name (reCAPTCHA, hCaptcha, Turnstile…) only in an embedded document; (3) a
  classic text-in-image CAPTCHA: an input field named "Security code / Verification code / captcha" + an image nearby (or the phrase "characters in the image"); an image-less code field in an SMS/e-mail/app (2FA)
  context does not count; (4) a title "Just a moment…", "Attention Required"… is NOT enough ALONE: together with a challenge frame/element or a Cloudflare address (`/cdn-cgi/`, `__cf_chl`) the whole page becomes the
  challenge (`cloudflare_interstitial`); (5) OCR: only a short line, ≥60% of the line is the pattern (low confidence). A SOLVED challenge (a ticked checkbox, Turnstile "Success!") does not count. The result is
  `human_verification: {detected, kind, window, hint}`; in the results of `observe`, `read_text`, `wait_for`, `click`, `type_text`, `press_key`, `drag`. `read_text` does not give the FULL address of iframes (only kind +
  domain name); in the critical notification the domain name is written, not the page title.
- **State**: under a key of window id + title/address, `RUNTIME_DIR/insan-dogrulama.json` (0600, flock) — CLI and MCP processes see the same boxes. The file ONLY ADDS BLOCKS: detected challenge boxes (`sinama`), warning
  suppression (`bastir`) and the window's last input time (`girdi`; it only forces a RESCAN). The decisions "no challenge" and "unreadable" are ONLY in process memory (not written to the file, NOT READ from the file;
  ~3 s / ~10 s): for a "no block" decision the process's OWN scan is needed. The file is verified every time it is read (type, 0 ≤ age ≤ TTL, boot id), but the guarantee against keeping the gate permanently open rests
  not on the correctness of the file but on this rule: writing a fake "none" into the file or deleting a challenge record does NOT open the gate (the process rescans); the worst case is an extra refusal or scan. It is
  deleted when the title/address changes or after 300 s. **No stale box:** every input (click, key, text, scrolling, window move/resize/maximise, accessibility action) marks the challenge record of that window "dirty"
  (last input time, across processes; in desktop mode all windows since the window is unknown); before the next input, if the record is older than the last input (or older than 15 s) the page is RESCANNED (~0.25 s settling
  is awaited for scroll animation). If a dirty record CANNOT be read again, ALL mouse input in that window is refused (like `page_wide`) and on the keyboard input after Tab + a lone Space/Enter are refused.
- **Refusal (CORE gate)**: the SINGLE common point of the mouse paths `eylem.hassas_nokta` (coordinate, text, element, icon, colour, web, drag start; drag end and `erisim._hassas_oge` and `ogeye-yaz` too) calls
  `nokta_engeli`: if the clicked POINT is in a challenge box (or the short text is a challenge sentence) **Dur(18)** — an unobserved call, the CLI (`ekran click`), MCP and flow steps all pass through the same gate.
  Keyboard (`k_tus`/`k_yaz`/`k_bas`): 18 if the whole page is a challenge or the FOCUS is in a challenge box (including ticking with Tab+Space). If there is no state and the window is a browser it is scanned once BEFORE
  the input (the scan ~`hazir`; "none" is cached for 10 s). In MCP additionally the ref flag (`!human-verification`) and the text target; `human_verification` in a `batch` step error. **code 18**, `sent: nothing_sent`.
- **Hand-over** (`request_human(reason, window, timeout_s=600)`): a KDE notification (`mesgul.bildir`, critical) + a `tur="devir"` request on the approval channel (panel dialog: **Take over** [background desktop only; the
  panel's existing Devral: preview + input transfer], **Done**, **Cancel**). During the wait agent input to that desktop is closed ([7]); the request is closed only from the panel (a channel verified with SO_PEERCRED, §8:
  Done = permission) or by the page itself (the challenge mark that existed at the start is absent in 2 consecutive polls while the page is READ and the ADDRESS has not changed → `resolved_by=challenge_cleared`; an unreadable
  page or a changed address does not count as "disappeared"); the agent cannot close its own request. Result: `resolved | timeout | declined | unavailable`. If the mark is still there after `resolved`, `still_detected: true`;
  after the user says Done, the warning and a re-call are suppressed for the SAME challenge (address + frame set) (`suppressed`; the input gate stays OPEN). For challenges that pass by themselves (the Cloudflare interstitial,
  a managed Turnstile) it is only polled for ~10 s before the notification; the notification is sent unless the panel is alive/attended/DUR, and is silent if the user is in a game/full screen. An atomic hand-over record (a
  concurrent second request [7]); after a refusal/timeout a new request for the same window within 60 s is refused (`retry_after_s`). `bekleyen_var` counts hand-over requests as live for up to 3600 s (during the wait the input
  of OTHER processes is also closed). In the log/history the label is `devir-tamam` (hand-over done) (not "approval permitted"); with "Done/Cancel/time" the Devral that the dialog opened is closed.
- **Unreadable page (no fail-open):** in a BROWSER window whose accessibility tree cannot be read (closed/unresponsive, no document) input after Tab and a lone Space/Enter or text containing spaces is refused (the focus may
  be in a challenge box); if the focus cannot be known while a challenge state EXISTS (the query failed, there is no boxed element in the focus) a sequence containing Space/Enter/text is refused. The gate scan calls
  `erisim_ac_garanti` ONCE per process for a browser window when accessibility is off. **Side effect in kde:** this turns accessibility on SESSION-WIDE in the user's session (the AT-SPI bus `IsEnabled` +
  `toolkit-accessibility`) and it stays on (all applications produce an accessibility tree; a small performance cost); it is visible in the log and by the marker in the state directory, `deskhand a11y off` undoes it. On the
  virtual (background) desktop only that desktop's private bus is affected. Raw key codes (`k:N`) only 1-255 (0x100+ are BTN_* mouse buttons). In desktop mode (EKRAN) the window that the gate tested is re-checked right after the
  gate and BEFORE EVERY click/press (Dur 3 if the window under the cursor and the cursor are not the same); a double/triple click and `tekrar>1` are sent one by one, in a drag it is also checked before `buttondown`.
- **Threat model:** the gate is a BEST-EFFORT second line to stop CAPTCHA interaction by an agent that has been fooled accidentally or by page text (prompt injection); the real guarantee is the agent's rule (a CAPTCHA is not solved, it
  is handed over with `request_human`). An agent that has a shell can bypass these gates (and the other tool-level gates) anyway by writing directly to `girdi.sock`; this is the existing general limit in the document (§2, §8) and is
  outside the scope of these gates.
- **Limits:** new CAPTCHA types can escape detection; if the tree cannot be read (accessibility off/unresponsive) there is no detection — in that case the browser paths do not click an element whose position cannot be verified
  (fail-closed) and the keyboard rules above come into play. The keyboard focus query is for browser pages.
