# Changelog

*Türkçe: [CHANGELOG.tr.md](CHANGELOG.tr.md)*

Versions 0.6.0 to 0.9.1 were local builds and were never published; 0.10.0 is the first public
release after 0.5.4. Every entry between them is listed here so a 0.5.4 user sees the whole change.
Security fixes are marked **Security**.

## 0.10.0 (2026-11-28)

The first public release after 0.5.4. **If you run 0.5.4 or older, please update:** MCP `open_app(args)` could run
commands without approval there (closed in 0.6.0, see below).

### New in 0.10.0

- **New: key store, "Deskhand vault" or KDE Wallet.** Saved passwords and the panel's signed settings record live in
  one of two stores. The vault (default for new installs) keeps each item as a file sealed with `systemd-creds`
  (bound to the TPM2 when there is one, otherwise to the host key; the sealed name is part of the seal, so a copy
  under another name does not open) and makes no D-Bus or wallet call. KDE Wallet is the Secret Service path used
  until now. An install that already used the wallet stays on it until you choose the vault. Switching asks for your
  Yes in the panel, copies and re-reads every item first, and changes nothing if the old store cannot be read.
  The choice is sealed in the vault, so editing `[anahtar] depo` in `ayarlar.toml` by hand does not switch stores (the
  panel then treats the store as unverified and stops with exit code 10).
- **New: Settings, Advanced, "Secrets".** A status badge for the chosen store (ready with TPM, ready with the machine
  key, open, locked, unavailable with the reason), a switch between the two stores, the list of saved passwords
  (names and bindings only, never values) with **Add password** and **Delete**, and **Open KDE Wallet at login**.
- **New: saved passwords with per-site binding and per-use approval.** `deskhand secret set NAME [--site DOMAIN]
  [--app WINDOW_CLASS]` (value from stdin; hidden prompt on a terminal), `secret list`, `secret rm`, `secret status
  [--json]`. An agent types one with `deskhand type <window> --secret-ref NAME` or the MCP `type_text` argument
  `secret_ref` (not together with `text` or `element`). The value goes from the store to the keyboard layer and
  never appears in a result, the log or the panel feed. It is typed only into a field the accessibility tree calls a
  password field, and every use asks in the panel (name, window class, site, never the value; refusal or unattended
  mode exits with code 10). The site is read from the page address right before typing and checked again after your
  Yes; a password bound to a site or app that does not match is refused.
- **New: unlock KDE Wallet at login.** `deskhand wallet open|status|remove` (Settings has the switch). Deskhand seals
  the key derived from the wallet password (not the password) in the vault; the user service
  `deskhand-cuzdan-ac.service` starts `ksecretd --pam-login` with it at login, using `kwallet-pam`'s own protocol,
  but only if nothing owns the Secret Service yet. If the wallet was already started and is locked, it logs one line
  and tries again at the next login; Settings shows which of these happened. Needs the wallet to exist and its salt
  file to be present.
- **Known limits of the vault** (also in the README, "Security model"): code running as you can decrypt vault items
  with `systemd-creds`, like it could read an unlocked wallet; a rolled-back copy of the panel record is detected only
  while a Deskhand process has seen the newer one (a TPM counter was not available); `secret_ref` needs the
  accessibility tree (`deskhand a11y on`) and is refused otherwise; between the last check and the first key, a page
  change inside the same window is not noticed.

Documentation and upgrade notes for the changes since 0.9.1. Where a sentence in an older entry below says the
panel "removes" or "lifts" something, the rules in this section and in the README's "Security model" apply.

- **Security: the panel's settings are anchored in your Secret Service.** The forbidden-window list, the access
  levels, the approval scope, account sessions, persistent sessions and your STOP have their last approved value
  in one signed record the panel keeps in KDE Wallet; a settings file plus marker forged on disk no longer
  replaces it. Tightening is accepted, loosening waits for your Yes in the panel (default No). The questions show
  the exact entries that will be applied (non-ASCII and invisible characters written as `\u{XXXX}` with a warning
  mark) and a Yes counts only for that text. With an unreadable record the lists are asked in one dialog, and on No
  clients stop with exit code 10 until the wallet can be read. Settings shows an unverified list read-only.
- **Security: lifting STOP needs your Yes.** `deskhand resume` asks the panel (default No; panel closed or
  unattended mode: exit code 13; `--approved` is not an answer). STOP is a set of sources: an agent's
  `resume` removes only a STOP the agent set. If the panel cannot read its signed STOP record at start it sets its
  own STOP and removes it once the record can be read.
- **Security: approval requests carry a fingerprint.** The requester sends the sha256 of the request file it wrote;
  a file that does not match, or a second different fingerprint, is refused.
- **Security: `secret=true` typing.** Text is typed key by key, never through the clipboard, with the active window
  checked before and after every key; titles and text stay out of results, log and panel feed. Limits (README,
  "Activity log"): the focus check before an Enter leaves a gap of a few milliseconds, nothing is checked after
  the submit key, a separate `observe` afterwards can show a window title that contains the text, and tab switches
  inside one window are not noticed.
- **Change: the background desktop memory cap is 8 GB** (was 6 GB). Tool results carry `memory_warning` at 80%; an
  idle desktop at 85% gets a Firefox-only restart with session restore (at most 3 per 24 hours, backing off up to 24
  hours when it frees little; `DESKHAND_FF_YENIDEN=off` disables it). Details and the ~15 second tab-loss limit:
  README, "Memory watch".
- **Change: browsers.** A second window of a running Firefox or Chromium opens in the same process. Native
  `chromium` opens on the background desktop with an empty profile (no saved logins); Flatpak Chrome does not
  open there (exit code 16 with the reason). `open_app` returns status `address_unverified` when the typed page
  address could not be confirmed. Two windows with the same title in one process stop with exit code 6 instead
  of reading the wrong one.
- **Fix: Settings showed the default instead of the saved approval scope and account sessions after a panel
  restart.** The panel now reloads them once its protection is running and on every show.
- **Change: `sessions forget` when it cannot take the store lock** exits with code 7
  and says nothing was forgotten; it never answers "no record" then.

### Upgrading

- Restart the panel and the MCP server **together**, right after updating the code. A panel left running from the
  old code can overwrite the STOP file.
- Run `install.sh` again: the `deskhand` wrapper now starts Python with `-I` (no user site-packages, no `PYTHON*`
  variables). Until then the panel re-executes itself with `-I`, but the MCP server does not.
- Old sha256 markers are not accepted any more. The first panel start asks one combined question about the old
  values (default No; one Yes is enough). Answering No keeps the defaults and tightenings only.
- A record written by an earlier version has no STOP field. The first start after the update therefore sets a
  STOP of the panel's own, and Deskhand stays stopped until you press **Resume** in the panel once.
- Do not update a machine that runs unattended while nobody is at it: both the question and the Resume need you.
- The memory-watch counters were reset by the new format; the first restart limits start from zero.

### Also in 0.10.0 (changes since 0.9.1)

Changes since 0.9.1:

- **Security: MCP `open_app(args)` could run commands without approval in 0.5.4 and earlier; closed since
  0.6.0 (see below).** Updating is recommended.
- **Fix: `systemd-run` argument expansion.** On systemd 254 and newer, a `$` in a path handed to `systemd-run`
  could be expanded; the flag that turns expansion off is now added on those versions, not added on older
  versions or when the version cannot be read, and the version is read from a single place (fail closed).
- **New: the browser accessibility tree also on the foreground desktop.** Deskhand starts Chromium-family
  browsers with `--force-renderer-accessibility` and Firefox-family browsers with `GNOME_ACCESSIBILITY=1` in the
  environment; if the tree is still off, `observe` results say so (`tree: {available: false, reason, fix}`) with a full,
  untruncated hint, and `deskhand doctor` warns about a running browser that is not on the accessibility bus (it never writes your environment files itself).
- **New: persistent background sessions (opt-in).** `[oturum] kalici = "site1.com, site2.com"` in
  `ayarlar.toml` keeps the session of a site that you log in to only on the background desktop between copies.
  Saved encrypted (AES-256-GCM) with a key held in your KDE Wallet, fail-closed (no wallet, no write and no
  plain-text fallback), never for banking/payment/government/central-login sites, not in task mode. The list is
  panel-authoritative: a site written into the file by hand is used only after you answer Yes in the panel.
  `deskhand sessions forget <domain>` / `--all` deletes records; `deskhand doctor` and `sessions check` show the
  state (never a value). Details: [docs/SESSIONS.md §3.8](docs/SESSIONS.md).
- **Change: the background desktop memory cap went from 4 GB to 6 GB (20 OOM kills in 17–24 hour sessions) and is now 8 GB, see above.**
- **Docs: English is the primary documentation language.** `README.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`
  and `docs/SESSIONS.md` are English; the Turkish originals are `README.tr.md`, `CHANGELOG.tr.md`,
  `docs/ARCHITECTURE.tr.md` and `docs/SESSIONS.tr.md`. README now has a "Security model" section and the MCP
  tool count (20) matches the code.
- **Tooling: personal-trace scanner** (`tools/iz_tara.py`), a lefthook pre-commit gate (`tools/kontrol.sh`) and a
  ruff baseline.

## 0.9.1 (24 November 2026)

- **Fix: a human handover (`request_human`) request could stay locked for 15 minutes.** Waiting is now
  cancellable (it ends in ≤1 s when the client cancels, the request is deleted, `devir-iptal` is logged). A request
  whose owner died or that gave no heartbeat for 30 s holds no lock. A pending request raises a persistent tray
  notification; clicking it only raises the panel and the dialog, the decision is still given with Done / Cancel.
- **Fix: when the panel's identity record went stale, the account-session permission stayed silently off** (Python
  updated while the panel ran, so `/proc/<pid>/exe` read "(deleted)"). The panel refreshes its record once a
  minute from its own live values; verification was not loosened. Doctor states the reason.
- **New: an idle background desktop closes itself** (default 30 min; `ayarlar.toml` → `[masaustu]
  bosta_kapat_dk`, 0 = off). Not while you are taking over, while an approval or handover is pending, in task
  mode, or while the panel is watching; it opens again on next use.
- **New: desktop picker and live view in the panel.** The "Background desktop" tab lists every running invisible
  desktop (named ones included) and shows the selected one live (view only, no input path) with an "Agent now: …"
  line for the last action (content typed into a secret field is not shown).
- **Security: previews black out forbidden windows** (Background and Task tabs; same rule as `api.goruntu_al`).
  If it cannot be checked, the frame is not shown at all.
- **New: `deskhand sessions check <site>` (`oturum denetle`).** Does the site session exist in the Firefox profile
  and in the invisible-desktop copy, is it persistent, when does it expire; prints no values. Exit 0 = present,
  1 = login/refresh needed. For a pre-flight check before a release.
- **Fix: an old expired cookie row in the session copy silently blocked a live session cookie from being carried.**
- **Tests: leaked test processes** (KWin, dbus) are cleaned up even when the suite is killed or crashes.
- **Security: races in the handover and approval channel closed.** The heartbeat comes from a separate thread; a
  request whose owner verifiably runs is not dropped on file time alone; when the request file is deleted the
  waiting side stops waiting. Cancellation is checked at decision time: a cancelled `request_human` never returns
  "resolved" and never silences the guard. The handover input lock is set before the first poll; the "verification
  passed" decision is bound to the same document (query and fragment included; Cloudflare `__cf_chl_*` tokens are
  ignored). The panel record and its socket live under one lock; after shutdown a refresh recreates nothing.
- **Security: preview mask tightened.** If the window class cannot be read, the result is not cached and the frame
  is not shown; the window list is read before and after the frame is taken and the union of both is masked. On
  KWin the mask uses the frame geometry (title bar included, `api.goruntu_al` too); a window that cannot be checked
  there is masked. The image that goes to the agent (`api.goruntu_al`: screenshot, read, icon search) uses the same
  before/after read; if a forbidden window closes while the frame is taken, or the list cannot be read, no image is
  sent (retryable error).
- **Security: Firefox session copy cookie fixes.** An expired session cookie in the source is not copied; the
  written lifetime never exceeds the source expiry. A domain cookie (`.example.com`) that could go to any subdomain
  that a fixed reject rule (`*.bank.com`, `accounts.google.com`) may match is not carried. For a rule ending in `*`
  (`*bank*`) the decision looks at the subdomains known from the profile (history WAL included); a never-seen
  subdomain is not covered (docs/SESSIONS.md §8). `deskhand sessions check` decides by the same rule.
  The copy's `cookies.sqlite` is rebuilt with `VACUUM INTO`: deleted values do not remain as bytes in the file.

## 0.9.0 (22 November 2026)

- **Fix (critical): `#`, `$`, `€` typed into Firefox on the invisible desktop (KWin) silently vanished** ("a#b" →
  "ab", the tool still said "typed"). On the Turkish layout these characters also sit on "inet" keys that cannot be
  forwarded to X11, so those keys were chosen; now a key XWayland can forward is chosen (AltGr+3/4/E), and only a
  character on such a key is pasted from the clipboard. Rebuild the helper: `make -C deskhand/yardimci deskhand-eis`.
- **Security: power/sleep/lock keys went through without approval.** A bare `power`, `sleep`, `wakeup`,
  `coffee`/screensaver, `suspend`, hibernate and log-out key without a modifier (dotool names, XF86 names/codes such
  as `x:XF86PowerOff`, `k:116/142/143/152/205`) and KDE's unconfirmed shutdown shortcuts
  `ctrl+alt+shift+delete/pageup/pagedown` now need human approval in `key`/`press_key`.
- **Security: control characters in typed text went out as keys.** C0/C1 and DEL characters other than `\n` and `\t`
  (`\x08` backspace, `\x1b` Esc, `\x7f`…) are refused with exit 1 and nothing sent in typed text (both backends, paste
  path, accessibility value write); the message points to `press_key`.
- **Security: `--secret` text leaks closed.** The secret line of a batch/flow step is not written to stdout, the log or
  an error message (only the command name + `***`); in secret typing a character missing from the layout is not
  substituted (Café → Cafe is gone), it stops with 1 before typing and the message gives only position/length;
  dotool's "impossible character" warning is masked in the central log and in the secret send message; the log keeps
  only the total length instead of piece lengths (6, 6, 4); if the old clipboard cannot be restored after a secret
  paste (for example because it is very large) the clipboard is cleared.
- **Security: the Enter rule on an unreadable browser page was redesigned.** Before, only a bare Space/Enter or an
  input after Tab was refused; `['a','enter']` or `abc\n` went to an unknown focus. Now a cheap focus query runs
  whenever Enter/Space appears anywhere in the sequence: allowed if the focus is outside the document (address bar,
  file chooser and other browser dialogs) or in a text field, refused if it is another element of the page or
  unknown; the message says what to do (click the field, `goto`, `open --background`). The MCP `type_text` gate also
  sees the Enter of `submit=True`; `goto` sends the address and Enter as one typing action.
- **Security: the real-screen lock locked a payment page on the invisible desktop.** With
  `DESKHAND_GERCEK_EKRAN=kapali`, every click/Enter/`goto` on a page with "Ödeme" (payment) in its title was
  refused. Showing the approval in the panel is not input to the real screen: on the invisible desktop target the
  approval is asked, on the user's screen 17 stays as is; the message names the pattern that triggered it. Leaving
  through `goto` is without approval when the focus is verified in the address bar.
- **Security: field values were not masked on the web path.** Reading a browser page returned the value of one-time
  code, card number, CVC, PIN and password fields; the same rule as the desktop path now applies (name,
  description, `id`/`placeholder`/`text-input-type`) → `***`. Limit: Firefox does not give the `autocomplete`
  token to the accessibility tree.
- **Security: CLI read commands obey the forbidden-window list.** `foto`, `metin`, `bekle`, `simge-bul`,
  `simge-kaydet`, `renk-bul`: exit 10 if the target is forbidden, other forbidden windows in the image are black
  (same as MCP).
- **New: CLI automatic title lock.** `yaz`, `tus`, `tikla`, `dizi`, `kaydir` given a window ID and no `-b` lock to
  the current full title; if the tab/page changes while the command runs, it stops with 4 (the message says `-b`
  for a flexible pattern or `--no-title-lock`).
- **MCP: result contract.** An unexpected exception also returns a structured error (`[9]`, `sent`, `next`;
  `maybe_partial` if input went out); `get_status`, `choose_desktop`, `manage_desktop`, `screenshot`, `read_text`,
  `listen`, `find` return structured errors too; messages use MCP parameter names (`region`) instead of CLI options
  (`--region`).
- **Fix: some apps were taken for browsers** (zenity, hedgewars, knowledge-base, citizen, operator, chromatic): the
  browser name must now be a whole part of the class.
- **Fix: human priority.** A single short echo of our own input in the 0.5 s after the window ends is not counted as
  the user (a real key press makes two events and still interrupts); the activity helper is waited for on exit (no
  zombie/fd leak); the priority guard does not mistake a temporarily unreadable cage for "empty".
- **Fix: KDE.** A disabled monitor does not enlarge the screen area; the keyboard layout cache refreshes when kxkbrc
  changes; if ext-idle-notify falls back to v1 the keyboard watcher is ignored (only the mouse is watched).
- **Fix: downloads in the background Firefox vanished.** The copy's own `XDG_CONFIG_HOME` had no `user-dirs.dirs`:
  GTK showed a non-existent `~/Desktop`, Downloads did not resolve, and Firefox saved to a temporary `~/Downloads`
  inside its namespace (deleted when the browser closed). The copy now gets the user's `user-dirs.dirs` /
  `user-dirs.locale` / `mimeapps.list` and the GTK/fontconfig look (0600); user.js pins the download folder
  (`browser.download.dir`, `folderList=2`) to the XDG Downloads folder, and in task mode to the task's download
  folder. Same for the Flatpak Electron copy.
- **Fix: session cookies really reach the background copy.** Cookies added from recovery.jsonlz4 were written with
  `expiry=0` (Firefox dropped them at start as "expired") and partitioned/container contexts (`partitionKey`,
  `userContextId`) were lost. Now expiry = now + 1 day (unit taken from existing rows), the context in Firefox suffix
  form; a context that cannot be converted (private window) is skipped.
- The copy's closing warning lists only identity providers (Google/Microsoft/e-Devlet) and says "the real profile
  was not changed"; changed cookies of other sites go to the log only.
- **Desktop ownership on the command line too.** A desktop started by `desktop start` and by `open --background`
  automatically is recorded for the calling Claude session if Claude is in the caller's ancestor chain: other Claude
  sessions cannot reach or close it (14); a named desktop whose owner died is closed automatically (leaked desktops
  do not eat the limit of 3). When the MCP connects automatically it counts an ownerless default desktop that has a
  running app as full and opens `oturum-N`. `desktop stop` also deletes the named desktop's directory.
- **`--desktop-name` everywhere.** Anywhere before the command (`--background --desktop-name X windows`,
  `-b PATTERN --desktop-name X …`) and after the command (`windows --desktop-name X`); `desktop … --desktop-name X`
  (`--name` alias). `--desktop-name` / `DESKHAND_MASAUSTU` now implies the background (without `--background` the
  user's real windows were listed). A closed or misnamed desktop: "the invisible desktop named 'X' is not open (open
  ones: …)". With `DESKHAND_GERCEK_EKRAN=kapali`, the real session's `windows` / `a11y` listing is 17.
- Exit code 1 on a `desktop` usage error (argparse's 2 means "point outside the window" in Deskhand); asking for an
  open desktop with a different scale exits 1 + JSON `olcek_uyusmaz`.
- `scroll ID X Y [direction] [STEP]` form and `--at x,y` alias; a hinted error for a lone numeric second argument.
  **Default scroll step 5 → 3** (same as MCP `scroll(amount)`).
- The background browser cache is limited to 64 MB (Firefox user.js, Chromium `--disk-cache-size`) so copies do not
  fill RUNTIME_DIR (memory); a warning when live copies exceed the limit. Copy files are 0600.
- Half-finished `insan-dogrulama.json.<pid>.tmp` files are deleted in the start-up cleanup.
- **New: `choose-file` (`dosya-sec`).** Picks the file in a file chooser with verification: is the location entry
  focused (AT-SPI), the typed path is read back, Enter is not pressed on a mismatch, and it waits until the dialog
  closes. A clear message for a file outside XDG on the background. Tested against a real Firefox
  `<input type=file>`. Keyboard input in the browser's native dialog (file chooser) is no longer refused as "page
  unreadable".
- **`tree` reads the dialog's own tree:** for a GTK dialog whose title contains the main window's name the main
  Firefox tree was returned (an exact title match now comes first).
- **The panel does not crash:** an uncaught exception in a slot (for example a full disk) killed the panel with
  SIGABRT; it is now logged, warned about from the tray, and the panel and the STOP button keep working. Take-over
  and settings saves return a message if they cannot be written.
- **A stale MCP server is detected:** `get_status` reports `stale_server` + "reconnect with /mcp" when the version
  on disk differs; `doctor` lists running `deskhand mcp` processes and warns about those started before an update.
- **Privacy:** log files 0600, `~/.local/state/deskhand` and `~/.cache/deskhand` 0700 (old permissions are fixed at
  start-up). Text typed without `secret` is visible in the log.
- **observe paging:** snapshots with the same content take one slot; the fifth page does not drop the refs of the
  first. The repeat-limit messages suggest `observe`; the dropped-ref message gives its reason (4 per window).
- Hints give a runnable `deskhand …` command instead of old `ekran …` names; English translations of the security,
  approval, CAPTCHA handover, account session and MCP texts are complete; the `server.json` version matches the
  package.

## 0.8.2 (22 November 2026)

- **New: 2× (HiDPI) invisible desktop — sharp screenshots.** Images taken from the invisible desktop fell apart into
  pixels when scaled for product images (text at 11–12 px on a 1× desktop). `deskhand desktop start --scale 2` (MCP:
  `manage_desktop(action="start", scale=2)`; also with `--desktop-name`) draws the same logical layout (window
  placement, click coordinates) with twice the pixels: `deskhand screenshot --out` saves the full resolution
  (2560x1600 on a 1280x800 desktop), `--width` scales it down; the MCP `screenshot` returns the same size (default
  `max_edge` 1280) but sharper because it is scaled down from the full frame, and `shot_id` clicks land in the right
  place. Measured: the ink height of 14 px text went from 15 to 28 px; Firefox and Chromium `devicePixelRatio` 2
  (GDK_SCALE / `--force-device-scale-factor`), Qt apps scale 2× on their own. `scale` appears in `desktop
  status`/`desktop list`, `get_status` and the `manage_desktop` output. The default scale is 1 (behaviour unchanged).
  KWin type only: refused with a clear message on Xvfb. Limits: OCR and `observe` read the logical image (scaled down
  from 2×); to change the scale, stop and start the desktop; X11 apps under XWayland other than GTK/Chromium may look
  small.

## 0.8.1 (22 November 2026)

- **Fix: typing was cut off with "the user used the keyboard/mouse" although the user did not touch anything.** On the
  foreground (the user's screen) `type_text` stopped at the second word boundary (for example "Satın alımdan
  vazgeçtim." → 12/24). Cause: every command opens a new activity watcher; because the input hub is ready, typing
  starts before the 50 ms idle time is over, and since the gap between letters is shorter than 50 ms the "idle"
  notice never comes; 0.2 s later that state was counted as human unconditionally. Now uninterrupted activity that
  overlaps Deskhand's own input is not counted as human; a short settling wait at the word boundary (at most 0.3 s)
  separates the delayed echo of our own input, our own input allowance goes 0.12 → 0.25 s; before the first input
  the watcher's first "idle" notice is awaited (at most ~0.2 s). If the user really types (or keeps typing), typing
  STILL stops with 12.
- **Fix: mouse-wheel scrolling had no effect in the Steam client (CEF/Chromium, XWayland)** (`scroll`: no_change).
  A "wheel N" sent as one event was swallowed entirely in these apps; notches now go as separate events (at most the
  first notch is lost; with a single notch the End/PageDown key is more reliable).
- **Fix: session copies of closed background browsers filled the temporary area (/run/user, tmpfs).** A copy (225–514
  MB) stayed until the desktop closed; when the area was full `key`/`type` crashed with OSError 28. The owner of each
  copy (browser process + start time) is now recorded and a watchdog deletes the copy when the browser ends;
  ownerless copies are swept when a new copy opens, when a desktop starts and in `deskhand doctor` (a live copy or one
  used by another desktop is NEVER deleted); past 3 copies / 1.5 GB the oldest ownerless ones are deleted. `deskhand
  doctor` shows a "Session copies: N, X MB" line; if the temporary area is full, commands stop with "temporary area
  full … deskhand doctor" (9) instead of crashing.

## 0.8.0 (22 November 2026)

- **Several invisible desktops (core).** More than one invisible desktop can be open at once (KWin type; at most
  `[masaustu] azami = 3`, 1..6): every Claude/MCP session connects to its own desktop automatically (the first
  session takes the default, later ones `oturum-1`, `oturum-2`…; pin one with `deskhand mcp --desktop-name NAME`) and
  cannot reach another session's desktop (Dur 14; the same session's command line can). CLI: global `--desktop-name
  NAME`, `deskhand desktop list`, `desktop start|stop|status --name NAME`. A desktop opened automatically closes
  after the session ends (~2 min); default and named desktops stay open. The default desktop's files are in the same
  place as before (no migration). The panel shows only the default desktop for now.
- **Fix: stopping one desktop does not delete another's browser copies.** Session copies and the Flatpak instance
  record are separated per desktop; `listen` records only the audio of the desktop it is attached to.
- **A pending approval locks only its own desktop** (a CAPTCHA handover on one desktop does not stop another).
- **You, running from your own terminal, reach every desktop.** A `deskhand`/`ekran --background` call with no Claude
  in its ancestor chain (terminal, KDE shortcut) is allowed like the panel; commands of another Claude session cannot
  reach someone else's desktop (Dur 14). This is an order rule between agents, not a security boundary.
- **Task mode works with several desktops.** The panel always runs the task on the default desktop (even if the
  Claude in the chat holds the default); while a task runs, other sessions cannot reach it, and when it ends it
  returns to its old owner.
- **Panel: a human verification on another desktop can be resolved too.** The approval window shows the desktop's
  name; "Take over" switches the Background tab to that desktop and returns to the default when the work is done.
- Hardening: the MCP server does not attach to a desktop when the Claude session closed and it is orphaned; the
  ownership record carries the PID namespace (a record in another namespace is not counted "empty"); a Flatpak
  instance is recorded only with an exact PID match (when two desktops open the same Flatpak app, one does not close
  the other's instance).

## 0.7.1 (22 November 2026)

- **Take-over keyboard fixed.** Typing with Take over in the panel gave "ı" for "i" on a Turkish Q keyboard (it broke
  password entry); typed characters now go as characters and come out right on every keyboard layout (i, ı, İ, ş, ğ,
  @, dot).

- **Account sessions: signed-in Microsoft / Google / e-Devlet on the invisible desktop (opt-in).** The Firefox copy
  filters the cookies of central login (Microsoft, Google) and government sites for safety, so pages such as Excel
  Online asked for a password every time. Panel → Settings → **Account sessions** allows it with one main switch
  ("Accounts I am signed in to stay open on the invisible desktop too — except bank and payment sites") or one by
  one (Microsoft, Google, e-Devlet and government sites): that account's cookies, saved logins (Firefox fills the
  password) and storage enter the copy. Default **off**; turning it on asks for approval and shows a warning ("the
  background browser can reach this account's mail and files"). Only the panel can turn it on: a value written into
  the settings file by hand or by an agent does not pass and the panel reverts it; CLI/MCP take the value only from
  the panel. Bank and payment sites open with no setting; in task mode the permission is never applied. `deskhand
  doctor` and the `open` output say which account was carried or why it was filtered ("identity sessions: Microsoft
  carried (5 cookies, 1 saved login)").
- **CLI friction removed.** Six obstacles that came up in real work on the invisible desktop (going to a web page
  with Firefox):
  - `deskhand --background open firefox` now starts the desktop by itself when it is off ("invisible desktop
    started"), passes through the same cage/lock/task-mode gates as MCP `open_app`; it is checked BEFORE the session
    copy is prepared.
  - `deskhand open firefox https://…` / `--url ADDRESS`: opens a session-copied browser with the address (http/https
    only; Chromium family included; `file:`, `about:`, `javascript:`, `data:` are refused). Task-mode rules apply on
    the CLI too.
  - `deskhand screenshot` works without an ID (`--background`: the whole invisible desktop, otherwise the active
    window; 17 if the real screen is locked) and takes `--out FILE` (the folder is created if missing); `--width N`
    gives a scaled-down image.
  - `deskhand windows` with no pattern lists all windows.
  - New `deskhand goto ID ADDRESS`: goes to an address through the address bar (ctrl+l → address → Return); title
    lock, sensitive-page approval and the human-verification gate pass through the existing `key`/`type` paths
    unchanged; http/https only.
  - `deskhand --help` lists the subcommands and short descriptions as a table.

## 0.7.0 (22 November 2026)

- **A "Task" tab in the panel: give a task, it does it.** The panel has its own agent (`claude -p`) do the job you
  write (for example "find this on that site and summarise it") on the invisible desktop; the steps stream live and
  the result and downloaded files are shown at the end. The agent uses only Deskhand's background tools and does not
  touch your screen.
- **Security: task mode.** The task agent reads untrusted web content, so it is restricted: it can only open a browser
  (no terminal, file manager or editor); it does not see folders such as Documents/Desktop, downloads go to a
  task-specific folder; in Firefox `file://`, `about:logins`/`about:config` are closed by policy and a downloaded file
  cannot be opened with an external app; saved passwords and extensions are not copied and cookies come only for the
  sites you allow; a window that appears outside the browser is closed. If the invisible desktop is open for another
  job the task does not touch it: it asks for your approval to close and start it; while a task runs other clients
  cannot attach to the task desktop. On allowed sites, the fact that the agent can act on your behalf is shown
  explicitly before it starts.
- **Human verification (CAPTCHA) handover.** A CAPTCHA is never solved or bypassed: when detected the agent's input is
  refused (code 18) and `request_human` sends you a notification + panel dialog (Take over / Done / Cancel); the
  agent continues when you solve it. If the page cannot be read (accessibility off), a bare Enter/Space is refused
  and the message says "this may not be a CAPTCHA, restart the browser".
- **Tests 4× faster.** `tools/test_kos.py` runs suites in parallel (full run ~13 min → ~3 min); suites that measure
  the real system run alone at the end.

- **Security: background apps see only a whitelist of the home directory.** An app opened on the invisible desktop now
  has an empty home directory; only appearance settings of the real home (KDE/GTK/Qt theme, colours, fonts, icons,
  cursor, XDG folder names, file associations, user `.desktop` files and Flatpak installs) are visible, read-only.
  Before, the home directory was readable through a temporary layer and only known secret paths (a blacklist) were
  covered: the token of an app not on the list (for example `~/.config/<app>/token`) could be read. Data folders such
  as Documents and Downloads are writable and persistent as before; what is written to the home root is dropped with
  the session. If an app needs its own settings, `ev = [...]` per app in `oturum.toml` (no default). Measured: KWrite,
  Dolphin, Konsole, Gwenview, Firefox, Chromium, zenity, Meld and Electron open; theme and OCR accuracy did not change.
- **Security: the home whitelist was hardened (independent review).** A whitelist/`ev` entry that is a symbolic link is
  refused if its source goes to an XDG data folder, or outside home to `/tmp`, `/run/user/UID` or RUNTIME_DIR;
  whitelist links inside home may only lead to an entry in the whitelist; the second line (secret covers) also covers
  by source→target mapping; the source is opened with an `O_PATH` fd and bound with bwrap `--ro-bind-fd` (the path race
  is closed). In policy `ev` entries, globs, short secret entries and `.config`/`.local`/`.cache`… hubs are refused.
  Flatpak `overrides` and GTK bookmarks/servers are covered. Package binds come after data folders, a `.git` root is
  refused. `/tmp` and the home tmpfs in the namespace are limited to min(2 GiB, cage/4). If a program that is not
  visible under home is started, a clear error with an `oturum.toml` `ev = [...]` hint is given without waiting for a
  timeout.

## 0.6.1 (22 November 2026)

- **The Chromium family opens on the invisible desktop.** On systems with profile-sync-daemon, Chromium/Vivaldi/Electron
  crashed at start in the background; the idle profile link now points to an empty per-namespace directory (the real
  profile is still invisible). Downloads follow the real download-folder rule.
- **Security: browser profile backups hidden.** profile-sync-daemon's Chromium/Brave disk copies (`*-back-ovfs`,
  `*-backup`) are hidden from apps on the invisible desktop (open since 0.5.4).
- **Sensitive field values are masked.** When `observe`/`read_text` return the value of input fields, passwords, PINs,
  one-time codes, verification codes and card fields come back as `***`.
- **`type_text` on same-named elements** takes `role`/`nth`; if the name matches exactly and there is a single
  writable field it picks that.
- **KWrite/Kate text is read from the tree** (`read_text(source="tree")`).
- **Real-screen lock.** With `DESKHAND_GERCEK_EKRAN=kapali` (tests set this automatically) every side effect that goes
  to the user's real screen is refused at the lowest layer (exit code 17); the `salt-okuma` value closes only side
  effects.
- `doctor` leaves no crash record in a screenless environment; a clear message if the panel socket path is too long.

- **`listen` tool.** The AUDIO of apps on the invisible desktop is transcribed with local Whisper (video, voice
  messages). Each desktop gets, if it wants, its own private hardware-free sound server (`manage_desktop(start,
  audio=true)` or the first `listen`); apps see only that, sound does not go to the user's speakers, there is no
  microphone. The recording is kept in memory, the text is not written to the log, and the user's own screen audio is
  not listened to. A `doctor` "Listening" line was added; settings `[dinleme]`.
- **Listening security fixes (independent review).** Apps reach the private sound server only through the pulse socket
  and CANNOT load modules (`load-module` closed: connecting to the real microphone/speaker through a tunnel, arbitrary
  code through LADSPA, writing files through a pipe and opening a TCP socket are blocked). PipeWire's fully
  privileged socket never connects to an app. All three sound processes run in their own bwrap namespace: no network,
  no sound hardware/GPU, the user's real session sockets and home are invisible, only `ses/` is writable, low priority.
  Speech recognition runs in the desktop's memory cage at low priority; while the user is in a game it uses at most 4
  CPU threads.

## 0.6.0 (after 0.5.4)

### Highlights

- **Observe, ref and batch actions.**
  - `observe` lists a window's elements in one call (accessibility tree, OCR if needed). Each element gets a number
    (`ref`).
  - `click`, `type_text`, `scroll` and `drag` now work by `ref` instead of coordinates. If the screen changed (window
    closed, element gone, its name or place changed) the action is refused with no input sent; another button with the
    same name is not clicked.
  - For `observe`, `since` returns only what changed, `query` filters, `include_screenshot` gives a numbered image.
  - `batch` runs up to 20 steps in one call. All are validated first, it stops at the first error, and STOP, pending
    approvals and human priority are re-checked between every step.
  - `wait_for` waits for text, an element, a window, disappearance or the screen to settle.
  - The result of input tools now says what happened: `confirmed`, `changed`, `no_change`, `unverifiable`, `refused`.
    Error messages report the next step and whether input went out (`sent`).
- **Web page elements.** The links, buttons, fields and boxes of a page in the browser are read from the accessibility
  tree (`read_text` `source="web"`, CLI `web`, `click` with `element`). No remote-control port is opened on the
  browser, the page sees no automation. If an element's position cannot be verified, the click is refused.
- **Isolated, GPU-accelerated invisible desktop.** The background desktop now opens as an isolated KWin session
  (GPU-accelerated, separate D-Bus and Wayland socket, low priority). If the required components are missing it opens
  with Xvfb + openbox as before. You can see the type in the `deskhand desktop` status.
- **Approval scope: "card payments only".**
  - Chosen in the panel under Settings → "Approval questions". The default is **all** (nothing changes).
  - With **card**, approval is asked in only two cases: clicks and Enter on money buttons / payment pages, and typing
    card data. Money buttons are read in Turkish and English (satın al, öde, siparişi onayla, buy now, place order…).
  - This setting can only be turned on from the panel; setting the file to `card` by hand does nothing.
  - In an approval request only the last 4 digits of the card number show, and the full number is never logged.
  - Other protections and refusals stay as they were: terminal commands, password fields, system password prompts,
    risky keys.
- **Turkish OCR.** OCR for text clicking and observation keeps working with Turkish and English data; payment-button
  detection also knows Turkish phrases.

### Security

- **The unapproved command execution hole through MCP `open_app(args)` was closed (present in 0.5.4).** `open_app` now
  opens only installed desktop entries; shells, interpreters and terminals cannot be started, executable document
  types are refused. Root-owned system entries run without approval; entries the user can write need panel approval
  and are started from a private copy, re-checking the copy's digest. Code-hosting apps ask for approval.
- **No input into the agent's own terminal.** The agent cannot send input to the terminal it runs in. Embedded
  terminals are found through the process tree; every Enter into a terminal needs approval, and paste keys and
  paste-from-menu are tied to approval.
- **Approval channel.** An approval decision is accepted only from the verified panel socket. A process that can write
  files cannot forge a permission; response files count as a refusal. After approval the target (window, title,
  geometry, image) is verified again; while an approval is pending, input tools are refused.
- **bwrap isolation.** Apps in the background run inside `bubblewrap`: read-only root, separate PID/user namespace,
  empty `/tmp`, temporary HOME, only the app's own session copy. Secret paths (ssh/gpg keys, keyrings, real browser
  profiles, cloud and agent credentials, Deskhand configuration) are masked; there is no access to the sound server.
- **Accessibility socket protection.** Deskhand creates the accessibility directory itself before apps; the bind fails
  closed, the directory identity is checked. Another process cannot get in between.
- **System password prompts.** In polkit, KWallet, askpass and portal windows every click type needs human approval;
  refusal in unattended mode. The value of a password field is never read on any path.
- **Payment page.** A money button (or an unreadable target) click on a payment/order page and Enter/Space need
  approval; page detection also uses the document title in addition to the window title.
- **Card number detection.** Typing into a card field (name, label, `cc-number`, cvc/cvv, expiry…) or a 13–19 digit
  number that passes the Luhn check (typing, paste, value write) needs approval; numbers with separators are caught too.
- Also: forbidden/access-level lists are protected by the panel, the work directory is created 0700, time and size
  limits for the clipboard owner, shell-aware risky-command check, protection against the agent's own client.

### Behaviour changes

- **If the forbidden list and level lists are edited by hand while the panel is closed, commands stop.** If the file
  does not match the panel's marker, commands are refused on the safe side; open the panel and edit the list there.
- **The approval scope is authoritative in the panel.** If the panel is closed or cannot be verified, the scope counts
  as **all**.
- **The `ref` title rule applies only to OCR refs.** Tree and web refs are re-verified by their identity, so pages
  whose title keeps changing now work; for an OCR ref, if the window title changed it is refused.
- **On the KWin type, Firefox and Chromium/Electron open with XWayland.** Gecko browsers are started this way only
  when the session has XWayland; GTK4 elements count as enabled. Window queries survive KWin's temporary list errors.
- The result format of input tools changed (`effect`, `sent`, `next` fields); `observe` and `batch` return only short
  text.
- `wait_for` does not raise the window on the foreground.

### Installation

- New required dependencies: **`bubblewrap`** (background app isolation; without it no app opens in the background),
  **`libei`** and **`libxkbcommon`** (the input helper of the GPU KWin background desktop; without them it falls back
  to Xvfb).
- `make` now builds **three helpers**: keyboard activity (`deskhand-etkinlik`), screenshot (`deskhand-goruntu`) and
  KWin input (`deskhand-eis`). A C compiler, `make` and `pkg-config` are needed.
- `install.sh` checks the new dependencies, prints the package command if something is missing, builds the helpers by
  name and reports gaps as warnings.
- Recommended: `sudo pacman -S --needed bubblewrap libei libxkbcommon`
- CI (GitHub Actions) was added; tests that need KWin are skipped in an unsuitable environment.

### Known limitations

- A card number typed key by key, typed piece by piece into separate fields, or pasted from the clipboard into a field
  not marked as a card field cannot be caught.
- If, while the panel is closed, the settings file and the panel's marker file are forged together (consistently), the
  "card payments only" scope can be let through the next time the panel opens.
- Only KDE Plasma (Wayland) is supported.
- Not a sandbox against an agent that has a shell: a process that can run arbitrary code as the same user can kill the
  panel and take its place (see the threat model in the README, "Security model").
- On web elements, an element covering another (modal, sticky header) cannot be told apart from the tree; the
  coordinate-frame check on a real Wayland screen must be tried by hand.
