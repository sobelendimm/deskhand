# Deskhand — Session bridge (research on session transfer)

> **Türkçe sürüm:** [SESSIONS.tr.md](SESSIONS.tr.md) (the original text; the code comments are in Turkish).
> Research notes behind Deskhand's "session bridge": how apps running on the invisible second desktop (Xvfb + openbox, same Linux
> user, same `$HOME`, private D-Bus session) can reuse the user's existing account sessions without logging in again. It covers
> per-app session storage and single-instance behaviour, Chromium/Electron cookie encryption, safe snapshotting of Firefox
> profiles, refresh-token rotation risks, how to detect that an app is running in the user's session, and the default per-app
> policy (`deskhand/data/oturum.toml`). Source code refers to sections by number (§2, §3, §3.2, §4, §6, §8), so the numbering is
> stable. Policy values keep their Turkish names (`paylas`, `kopya`, `bekle`, `kapali`, `on`).

Scope: letting applications that run on the invisible second desktop (Xvfb + openbox, the same Linux user, the same `$HOME`, a
PRIVATE D-Bus session) use the user's existing account sessions without logging in again.

Method note: during the research only file/directory NAMES were listed in real profiles; cookie/password/token content was not
read. `busctl --user tree/list` shows only object paths (no content). Source code was read with `curl`/WebFetch. Everything that
could not be verified is marked **UNVERIFIED** (**DOĞRULANMADI** in the Turkish text). The paths of a specific application are
general knowledge; they may vary with the installation and version.

---

## 0. Environment note

The findings were verified on Arch/CachyOS + KDE Plasma 6. On other distributions or desktop environments the file paths, the
keyring service (KWallet / GNOME Keyring) and the Flatpak permissions may differ.

Short general reminders:
- Profile directories can be symbolic links (e.g. profiles moved to tmpfs with `profile-sync-daemon`); Deskhand must resolve
  `realpath` and must NOT USE stale backup folders on disk (`*-backup` etc.) as a source.
- The Firefox profile location can be `~/.mozilla/firefox` or (in the XDG layout) `~/.config/mozilla/firefox`; both locations
  must be scanned. Firefox 147 added support for XDG directories ([OMG Ubuntu](https://www.omgubuntu.co.uk/2026/01/firefox-147-released),
  [Phoronix](https://phoronix.com/news/Firefox-147-Beta)); the sources say "new installations", and whether old profiles are
  moved is **UNVERIFIED** in the official notes (<https://www.firefox.com/en-US/firefox/147.0/releasenotes/>).
- The `profiles.ini` trap: the real default profile is the `Default=` key in the `[Install*]` section; `Default=1` in a
  `[Profile*]` section can point to a different profile.
- A Firefox profile may contain `signedInUser.json` (the Firefox Account/Sync session); if it stays in the copy the background
  Firefox behaves like the SAME Sync device (see §3.6). Together with `logins.json`, a `logins.db` may also be seen in the profile;
  the role of `logins.db` is **UNVERIFIED** → copy both (passing them through the site filter).
- Most Flatpak Electron applications (Discord, Spotify, Ferdium) do not have the `org.freedesktop.secrets` / `kwalletd` `talk`
  permission → they cannot use the keyring directly and their sessions can be copied WITHOUT a keyring bridge (the exact encryption
  mode is **UNVERIFIED**: portal Secret or basic — it can be seen at run time with `safeStorage.getSelectedStorageBackend()`). The
  VS Code Flatpak has these permissions.
- KDE wallet topology (Plasma 6, kwallet 6.x): a single process, **ksecretd**, holds the names `org.freedesktop.secrets`,
  `org.kde.ksecretd`, `org.kde.secretservicecompat` and `org.freedesktop.impl.portal.desktop.kwallet`; `org.kde.kwalletd6` is only
  "activatable". The official README of the KWallet repository: "kwalletd exposes the KWallet API and proxies it to Secret Service";
  "ksecretd exposes the Secret Service DBus API" ([README](https://invent.kde.org/frameworks/kwallet/-/blob/master/README.md)). The
  `main.cpp` of kwalletd: "A KWallet compatibility service, wrapping upon Secret Service"
  ([source](https://invent.kde.org/frameworks/kwallet/-/raw/master/src/runtime/kwalletd/main.cpp)). That is, the old
  `org.kde.kwalletd6` API is a separate wrapper process activated over D-Bus; the real store is on the Secret Service side.
- Plasma environment: `XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6` (Chromium's automatic backend selection depends on this, §2).

---

## 1. Application table

Policy vocabulary: **paylas** (share) = while the application is CLOSED in the user's session, directly with the same files (under
lock/protection) · **kopya** (copy) = concurrent with an instant, consistent, one-way copy · **bekle** (wait) = NEVER concurrent; wait
until the user closes it / ask the foreground · **kapali** (off) = never run.

### 1.1 Summary table

| Application | Where the session is | Single-instance mechanism | Is a concurrent copy safe | Recommendation (when open) |
|---|---|---|---|---|
| Firefox | Profile: `cookies.sqlite`, `key4.db`+`logins.json`(+`logins.db`), `cert9.db`, `permissions.sqlite`, `storage/default/<origin>`; session cookies only in `sessionstore-backups/recovery.jsonlz4`. NO keyring (if there is no primary password) | profile lock (`.parentlock` fcntl + `lock` symlink `ip:+pid`) + remote command (D-Bus/X11) | Yes, copy + `--no-remote --new-instance`; Sync identity and token-rotation risk | **kopya** |
| Chromium / Chrome / Vivaldi / Brave | `Default/Cookies` (+journal), `Login Data`, `Local Storage`, `IndexedDB`, `Local State`; cookie/password encryption v10/v11 → the key is in KWallet/Secret Service | `SingletonLock` (symlink `host-pid`), `SingletonSocket` (symlink under /tmp), `SingletonCookie` | In a copy directory yes (a keyring bridge is a must); NEVER in the SAME directory: the 2nd instance steals the lock / SIGKILLs the first | **on** (no bridge, §5) |
| Discord (official Flatpak / native) + Vesktop | Electron userData: `Local Storage`, `Cookies`; Flatpak: `~/.var/app/com.discordapp.Discord/config/discord` | Electron `requestSingleInstanceLock` | Yes (multiple sessions are normal); joining a voice channel is forbidden | **kopya** |
| Slack | Electron userData `~/.config/Slack` (path UNVERIFIED) | Electron single-instance | Yes (multiple clients are normal); a keyring is needed | **on** (no keyring bridge) |
| VS Code | `User/globalStorage/state.vscdb` (secrets with safeStorage), `Cookies`; Flatpak: `~/.var/app/com.visualstudio.code/config/Code` | Electron + `--user-data-dir` | Yes; a keyring bridge is needed | **on** (no bridge) |
| Spotify | Flatpak `~/.var/app/com.spotify.Client/config/spotify` (`prefs`, `Users/`) | D-Bus `org.mpris.MediaPlayer2.spotify` (own) | Technically yes, BUT playback on a 2nd client pauses the first | **kopya** (playback forbidden) |
| Obsidian | Vault = plain files (`filesystem=home`); the Sync token is in Electron localStorage | Electron | Vault files can be shared but the background instance writes to the real vault; Sync with two clients is risky | **on** (foreground only) |
| Element Desktop | Matrix `access_token`+`device_id`+E2EE keys in IndexedDB; keyring | Electron | **NO**: the same device_id in two clients → OTK collision / undecryptable messages | **bekle** |
| Signal Desktop | `~/.config/Signal`: `config.json` (`encryptedKey`+`safeStorageBackend`), `sql/db.sqlite` | Electron | **NO**: the server drops the old connection (4409), Desktop does not reconnect | **bekle** |
| Telegram Desktop | `~/.local/share/TelegramDesktop/tdata` (auth key) | Qt `QLocalServer` ABSTRACT socket `md5(workdir)-TelegramDesktop` + `QLockFile` in /tmp | **NO**: AUTH_KEY_DUPLICATED → the session dies on the server; also, because of the abstract socket, a 2nd instance opens the user's window | **bekle** |
| WhatsApp wrappers (ZapZap, whatsapp-for-linux, the Ferdium service) | WhatsApp Web linked device = browser storage (IndexedDB) | Depends on the application | The same linked-device identity in two places: behaviour **UNVERIFIED**, cautious | **bekle** |
| Steam | `~/.local/share/Steam/config/{loginusers.vdf,config.vdf}` | `~/.steam/steam.pid` + `steam.pipe` | The single-session rule is unclear/contradictory; online play on a single machine | **bekle** |
| Thunderbird | Same as Firefox: `logins.json`+`key4.db`, OAuth tokens in `logins.json`; the mailbox is large | profile lock (the same as Firefox) | The mail store cannot be shared; OAuth rotation risk | **bekle** (optional light copy) |
| Heroic | `~/.config/heroic/{legendaryConfig/legendary/user.json,gog_store,nile_store}` + Electron `Partitions` | Electron `requestSingleInstanceLock` (source: main.ts:298) | Epic/GOG/Amazon token refresh: **UNVERIFIED** | **bekle** |
| Lutris | `~/.local/share/lutris/pga.db`, `~/.config/lutris`; site token `~/.cache/lutris` (**UNVERIFIED**) | GtkApplication `net.lutris.Lutris` (D-Bus) | A separate instance opens on the private D-Bus (on the same pga.db) | **bekle** / paylas when closed |
| Dolphin | `dolphinrc`, `~/.local/share/dolphin`; SFTP/SMB passwords KIO→KWallet | KDE D-Bus | No account; a configuration race is harmless | **paylas** |
| KMail / Akonadi | `~/.local/share/akonadi` (MySQL data directory) + `$XDG_RUNTIME_DIR/akonadi` sockets; passwords in KWallet | `org.freedesktop.Akonadi.Control` (D-Bus) | **NO**: a 2nd Akonadi on the private bus → the same MySQL data directory | **kapali** |
| Nextcloud client | `~/.config/Nextcloud/nextcloud.cfg`; token QtKeychain→Secret Service/KWallet | `KDSingleApplication` (source: application.cpp:433) | Two clients on the same sync folder → conflicts | **kapali** |
| Ferdium | Electron `Partitions/service-*`: WhatsApp/Telegram/Discord services inside | Electron | As risky as the worst of the services inside | **bekle** |

This table is a summary of the research findings; the default policy Deskhand actually applies is in §8 (since there is no keyring bridge in this version, applications that want a keyring are `on`, i.e. foreground only). Even for browsers, **kopya** (copy) is the principle when closed (§1.2).

### 1.2 Details and evidence

**General principle 1 — copy browsers even when they are closed.** Chromium's `process_singleton_posix.cc` source: the second process sends its
command line to the first over the socket in the profile directory; if the first process does not ACK within 20 s it **kills the first with SIGKILL** and
takes over; if the lock belongs to another hostname it gives a "profile in use" error
([process_singleton_posix.cc, tag 139.0.7258.138](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/chrome/browser/process_singleton_posix.cc)).
If the PID of the lock owner cannot be resolved in another PID namespace (Flatpak) it counts as an "orphan lock" and is deleted → two processes
write the same profile. Also, if the user clicks the icon while the background share continues, their own instance connects over the `/tmp` socket to the BACKGROUND
instance and the window opens on the invisible desktop. So never use `paylas` for the Chromium family and Electron applications; use `--user-data-dir=COPY`.

**General principle 2 — abstract Unix sockets and `$XDG_RUNTIME_DIR` are independent of D-Bus.** The private D-Bus isolates only D-Bus-based single-instance
mechanisms (Lutris/GApplication, KDE/KDBusService, the Firefox remote command). Telegram Desktop uses `QLocalServer::AbstractNamespaceOption` (its name is
`md5(working directory)-TelegramDesktop`) and its lock file is under `QDir::tempPath()` ([sandbox.cpp](https://raw.githubusercontent.com/telegramdesktop/tdesktop/dev/Telegram/SourceFiles/core/sandbox.cpp)).
An abstract socket is global to the network namespace → if a 2nd Telegram on Xvfb is opened with the same `tdata`, it connects to the user's Telegram (the window is on the
user's screen). Solution: `bekle`; also giving the background session a separate `XDG_RUNTIME_DIR` (adding the audio/pipewire sockets by symlink) separates path-based
sockets but not abstract sockets (**UNVERIFIED**: the applicability of `unshare --net` was not evaluated because it needs the network).

**Firefox** — see §3. Lock: `nsProfileLock.cpp` first tries `fcntl(F_SETLK)` on `.parentlock`, and if that fails falls back to the `lock` symlink (`ip:+pid`)
([nsProfileLock.cpp](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/toolkit/profile/nsProfileLock.cpp)).
The session is NOT in a keyring; if a primary password is used `key4.db` is protected (**UNVERIFIED**: whether the user has a primary password cannot be known).

**The Chromium family** — see §2. Depending on the version the path of the cookie DB can be `Default/Cookies` or `Default/Network/Cookies`; Deskhand must try both. The cookie DB uses
`Cookies-journal` (a rollback journal), not WAL. In the Chromium cookie store source there are the parameters `enable_exclusive_access` and `restore_old_session_cookies`; with
`restore_old_session_cookies` off, session cookies are **deleted** from the DB at start-up (`DeleteSessionCookiesOnStartup`)
([sqlite_persistent_cookie_store.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/net/extras/sqlite/sqlite_persistent_cookie_store.cc))
→ copied session cookies are lost in the background Chromium unless there is a "restore the last session" setting (which user setting this flag is tied to is **UNVERIFIED**).
- Copy INCLUDES: `Local State`, `Default/{Cookies,Cookies-journal,Login Data,Login Data For Account,Web Data,Preferences,Secure Preferences,Local Storage,IndexedDB,Session Storage,Sessions*,Service Worker (optional)}`, the extensions in use (`Extensions`).
- EXCLUDES: `Singleton*`, `Cache`, `Code Cache`, `GPUCache`, `DawnGraphiteCache`, `Crash Reports`, `Safe Browsing`, `component_crx_cache`, `OptimizationHints`, `WidevineCdm`, `BrowserMetrics*`, `LOCK`, lock/`LOCK` files other than `*-journal`.
- Sync: account sync must not run in the copy in Chrome (`--disable-sync`); also turn it off for the own sync chains of Vivaldi/Brave (detail **UNVERIFIED**).
- Vivaldi: yt-dlp maps Vivaldi's keyring name on Linux to `Chrome` (i.e. "Chrome Safe Storage")
  ([cookies.py](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/cookies.py), the comment "determined by listening on D-Bus") — **UNVERIFIED** for current Vivaldi versions.

**Discord (official + Vesktop).** The session is in `Local Storage` and `Cookies` in the application's Electron user data directory. In Flatpak: `~/.var/app/com.discordapp.Discord/config/discord` (most of it is
`Cache`, `logs`, `Dictionaries` and cache directories). The Vesktop configuration is under XDG config in `vesktop/` ([Home Manager options](https://mynixos.com/home-manager/option/programs.vesktop.settings); the claim of an internal structure
`settings/settings.json` is **UNVERIFIED**). Since Flatpak Discord has no keyring permission, no keyring bridge is needed. That several concurrent Discord sessions do not lead to an account lock: no official Discord document was
**found for this report → UNVERIFIED** (common as application practice; since the copy runs with the same token and the same device fingerprint, a new-device login is not triggered). EXCLUDE from the COPY: `Cache`, `Code Cache`, `GPUCache`,
`GPUPersistentCache`, `DawnGraphiteCache`, `DawnWebGPUCache`, `logs`, `discord_asset_cache`, `Crashpad`, `blob_storage`, `Dictionaries`; if the versioned module directory (e.g. `1.0.x/`) is not copied, the application downloads its modules again.
Rule: Deskhand does not join a voice channel (it would appear "online/in voice" on the user's behalf).

**VS Code.** With `code --verbose --vmodule="*/components/os_crypt/*=1"` you can see which keyring was chosen; the run-time flag is `"password-store"` in `argv.json` (`kwallet5`, `gnome-libsecret`, `kwallet`, `basic`; `kwallet6` is not listed in the
documentation) ([official document](https://code.visualstudio.com/docs/configure/settings-sync)). Secrets (`secret://…`) are encrypted with safeStorage in `state.vscdb` (**UNVERIFIED**: the internal format was not read, only the known architecture).
Copy: `User/globalStorage/state.vscdb` (+wal), `Cookies`, `Local State`, `User/settings.json`; EXCLUDE `Cache*`, `CachedData`, `logs`, `User/workspaceStorage` (large). Sharing the extensions directory read-only with `--extensions-dir` instead of copying it is **UNVERIFIED** (VS Code writes to the extension directory).

**Slack.** Electron. The `d` cookie is known as a long-lived session cookie but no official source was found for this report → the path (`~/.config/Slack`) and cookie behaviour are **UNVERIFIED**. Since Slack supports multiple clients a copy makes sense; token-rotation risk §4.

**Spotify.** Flatpak `~/.var/app/com.spotify.Client/config/spotify` (`prefs`, `Users/`). The manifest has `org.mpris.MediaPlayer2.spotify=own`: no name collision on the private D-Bus. The real risk: only one device can play on the same account;
starting playback on a second client pauses the first (Spotify community answers: [example 1](https://community.spotify.com/t5/Accounts/Listening-on-two-devices-simultaneously/m-p/4992140),
[example 2](https://community.spotify.com/t5/Desktop-Windows/Music-keeps-pausing-when-Spotify-is-open-on-two-devices/m-p/6479920/highlight/true); no official support article was found → the rule comes from forums). The internal structure of the copy files is **UNVERIFIED**.

**Obsidian.** The vault is plain files; accessed from Flatpak with `filesystem=home`; the configuration is `~/.var/app/md.obsidian.Obsidian/config/obsidian`. The account is only for Sync/Publish. The background instance can read the vault; the write race (last writer wins) and the Sync two-client behaviour are
**UNVERIFIED** → Sync off, vault shared.

**Element Desktop.** In Matrix the device id (`device_id`) and the Olm/Megolm keys are client-specific. If two live clients run with the same `device_id`, the one-time key (OTK) upload collides and an "One time key … already exists" error /
undecryptable messages (UTD) occur ([matrix-rust-sdk #1415](https://github.com/matrix-org/matrix-rust-sdk/issues/1415): "two OlmMachine created … same deviceId but different keys"). This coincides exactly with the copy scenario. → `bekle`; the alternative
is a separate Element Web session (a new device), which means "log in again".

**Signal Desktop.** In `config.json` the fields `encryptedKey` and `safeStorageBackend`: the database key is protected with Electron safeStorage; a GNOME↔KDE switch gives "Database Error", the fix is `--password-store="kwallet6"`
([yingtongli.me](https://www.yingtongli.me/blog/2025/08/13/signal-secrets.html), [Signal-Desktop commit](https://ayakael.net/mirrors/signal-desktop/commit/405ecfdcf8eb491e1684530b13948da758c906bd)).
Server behaviour (source): libsignal `ConnectedElsewhere` → WebSocket close code **4409**; Desktop's `SocketManager` on 4409 does `log.error('got 4409, connected on another device'); return;` and **does not reconnect**
([WebsocketResources.preload.ts](https://raw.githubusercontent.com/signalapp/Signal-Desktop/main/ts/textsecure/WebsocketResources.preload.ts),
[SocketManager.preload.ts, lines 391-394](https://raw.githubusercontent.com/signalapp/Signal-Desktop/main/ts/textsecure/SocketManager.preload.ts)).
So if the background copy connects the user's Signal drops and does not reconnect until restarted; also the Double Ratchet state diverges in the two copies (this second point is an architectural inference, **UNVERIFIED**). The Signal-Server
`ClientPresenceManager` source could not be read (404) → the server-side "drop the old connection" behaviour is only an inference from the client source. → `bekle`.

**Telegram Desktop.** Official document: `AUTH_KEY_DUPLICATED` (406) — "only when a non-media DC sees requests sent over parallel TCP connections of an authorised session"; if the error was received the session is already invalidated on the server and "the user must
generate a new auth key and log in again" ([core.telegram.org/api/errors](https://core.telegram.org/api/errors)). → running a copy of tdata concurrently can kill the user's REAL session (copy or original makes no difference, the auth key is the same).
For sequential use (while one is closed) the same document sees no problem but support for "use while closed and put back" was not specifically verified in the tdesktop source (**UNVERIFIED**). The `-many -workdir` flag is for a separate account, not for
opening the same tdata a second time. → `bekle`; `paylas` is possible when closed.

**WhatsApp wrappers.** ZapZap: PyQt6 + PyQt6-WebEngine ([github.com/zapzap-linux/zapzap](https://github.com/zapzap-linux/zapzap)); the session directory is **UNVERIFIED**. whatsapp-for-linux: `$HOME/.config/whatsapp-for-linux/settings.conf` and `web.css`
([wiki](https://github.com/eneshecan/whatsapp-for-linux/wiki)); the WebKit session directory is **UNVERIFIED**. WhatsApp Web keeps its key in the browser IndexedDB as a "linked device"; no source was **found in the research → UNVERIFIED** about the server behaviour
(forced sign-out, "open in another window") when two clients use the same store; because of the same logic as Element/Signal (the same device identity in two places) cautious → `bekle`.

**Steam.** `loginusers.vdf` and `config.vdf` are the session files (content not read). The official Steam Support FAQ says a single account cannot be used by several people at the same time but does not say whether a second login kicks the first
([support](https://help.steampowered.com/en/faqs/view/71EA-CDCE-FB5C-82B3)); forum reports are contradictory: some say "the other one signs out", some say "the session stays open, the game session conflicts", "the online library is single-machine" is common
([community threads](https://steamcommunity.com/discussions/forum/0/3874842132571689460)). The official rule is unclear → cautious `bekle`. Single instance: `~/.steam/steam.pid` / `steam.pipe` (known architecture; the source was not read in this report → **UNVERIFIED**).

**Thunderbird.** The same profile/lock architecture as Firefox; OAuth tokens in `logins.json` (known architecture, **UNVERIFIED**). The mail store (mbox/Maildir, `global-messages-db.sqlite`) cannot be shared between two processes; for IMAP-only accounts a light copy (`prefs.js`,
`logins.json`, `key4.db`, `cert9.db`, `abook.sqlite`, NOT the mail) is possible but it downloads the headers again at first start. For a Microsoft OAuth token the rotation risk is low because the old token is not revoked (§4).

**Heroic.** Uses `requestSingleInstanceLock` ([main.ts:298](https://raw.githubusercontent.com/Heroic-Games-Launcher/HeroicGamesLauncher/main/src/backend/main.ts)). Directories: `legendaryConfig/legendary/user.json` (the Epic session), `gog_store`, `nile_store`, `gogdlConfig`, `Partitions`,
`Cache`, `tools`. Heroic says it moved Legendary's configuration into its own `legendaryConfig` directory ([PR #2803 summary](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/pull/2803)). Whether the Epic refresh token is rotated is **UNVERIFIED**. The automation's need is very small → `bekle`.

**Lutris.** `Gtk.Application(application_id="net.lutris.Lutris", flags=HANDLES_COMMAND_LINE)` ([application.py](https://raw.githubusercontent.com/lutris/lutris/master/lutris/gui/application.py)): D-Bus-based single instance → a second, independent instance opens on the private D-Bus and
uses the same `pga.db`. → `bekle` when open.

**KDE applications.** Dolphin keeps no account; SFTP/SMB passwords go to the wallet through KIO, which needs a bridge. Akonadi/KMail: search results show that Akonadi keeps its MySQL data directory under `~/.local/share/akonadi` and its sockets under `$XDG_RUNTIME_DIR/akonadi`,
and that a second mysqld using the same data files gives `InnoDB: Unable to lock ./ibdata1, error: 11` ([KDE forum](https://forum.kde.org/viewtopic.php%3Ff=309&t=161559.html); the "one instance per user" rule is not written explicitly → **UNVERIFIED**). On the private D-Bus, Akonadi D-Bus activation starts a
second server → `kapali`.

**Nextcloud client.** Credentials are written to GNOME Keyring / KWallet / libsecret through QtKeychain ([QtKeychain README quote](https://help.nextcloud.com/t/kwallet-in-3-14-0-package/205341)); single instance `KDSingleApplication` ([application.cpp:433](https://raw.githubusercontent.com/nextcloud/desktop/master/src/gui/application.cpp)).
Two clients sync the same folder → `kapali`.

---

## 2. Chromium family and Electron cookie/password encryption (Linux)

### 2.1 Format and key

Source: `components/os_crypt/sync/os_crypt_linux.cc` (tag 139.0.7258.138) ([source](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/os_crypt_linux.cc)):

- Prefix `v10` = the fixed password `"peanuts"`; `v11` = a password coming from the system key store. Derivation: PBKDF2-HMAC-SHA1, salt `"saltysalt"`, **1 iteration**, 16-byte key; AES-128-CBC, IV = 16 spaces; PKCS7 padding. Source comment: "V11 will not be used if such a library is not available."
  If decryption fails it tries again with an empty password (`kEmptyKey`). If the key cannot be obtained for `v11` data, decryption **fails** (the cookie silently drops). The same derivation is also seen in third-party code (yt-dlp `derive_key`: salt `saltysalt`, 1 iteration, 16 bytes).
- If there is no key, NEW data is written with `v10`.
- Key storage: `KeyStorageLinux` — Chromium (unbranded): folder **"Chromium Keys"**, entry **"Chromium Safe Storage"**; in the Google Chrome branded build **"Chrome Keys" / "Chrome Safe Storage"**
  ([key_storage_linux.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_linux.cc)).
- The libsecret branch: schema `chrome_libsecret_os_crypt_password_v2`, a single attribute `application` (`chromium` or `chrome`; in Electron the application name at run time). If the entry is NOT FOUND it **generates and writes a new random 16-byte password**
  ([key_storage_libsecret.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_libsecret.cc)).
- The KWallet branch: the `org.kde.KWallet` interface; folder/key names are the constants above; if `HasEntry` is false, if the type is not a password (calls `RemoveEntry`) or if the password is empty it **generates and writes a new password**
  ([key_storage_kwallet.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_kwallet.cc)). Wallet name: the `networkWallet` reply (usually `kdewallet`) (yt-dlp: `dbus-send … org.kde.KWallet.networkWallet`).
- The names yt-dlp found by listening on D-Bus (Linux): chrome→`Chrome`, chromium→`Chromium`, brave→`Brave`, edge→`Chromium`, opera→`Chromium`, vivaldi→`Chrome`; the KWallet call `kwallet-query --read-password "<Name> Safe Storage" --folder "<Name> Keys" <wallet>`;
  KWallet services: `org.kde.kwalletd` (`/modules/kwalletd`), `…kwalletd5` (`/modules/kwalletd5`), `…kwalletd6` (`/modules/kwalletd6`) ([cookies.py](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/cookies.py)).

### 2.2 Backend selection (critical in a private session)

- `--password-store=gnome-libsecret|kwallet|kwallet5|kwallet6|basic|detect`; if the requested/automatically chosen backend is missing it falls back to `basic` ([password_storage.md](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/password_storage.md)).
- Automatic selection from the environment variables `XDG_CURRENT_DESKTOP`/`DESKTOP_SESSION`: KDE4→KWALLET, KDE5→KWALLET5, **KDE6→KWALLET6**; GNOME/Cinnamon/XFCE/COSMIC→libsecret; LXQt/other→**basic**
  ([key_storage_util_linux.cc](https://chromium.googlesource.com/chromium/src/+/refs/tags/139.0.7258.138/components/os_crypt/sync/key_storage_util_linux.cc)). yt-dlp also looks at `XDG_CURRENT_DESKTOP`+`KDE_SESSION_VERSION`.
- **Result / trap:** in an Xvfb+openbox session, if these variables are absent Chromium falls back to `basic` → `v11` cookies cannot be decrypted (they drop) and new cookies are written as `v10`. Deskhand must give the background session **`XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6`**
  and in addition pass `--password-store=kwallet6` explicitly (Chromium/Vivaldi) or whatever the user's real backend is. To detect the real backend, only the first 3 bytes of `encrypted_value` (`v10`/`v11`) in the cookie DB of the copy can be counted (the value is not read).

### 2.3 How the copy reaches the key on a private D-Bus

The copy asks for the key by the same route: libsecret (`org.freedesktop.secrets`, attribute `application`) or KWallet (`org.kde.kwalletd6`, `/modules/kwalletd6`). These names do not exist on the private bus → **a bridge is a must**; since there is no bridge in this version these applications run only in the foreground (§5). Without a bridge:
(a) it falls back to `basic`, cookies are lost; (b) if the user's wallet can enter the "generate a new password and write it" path while INACCESSIBLE (a wrong/empty store), the user's REAL `Chromium Safe Storage` entry can be overwritten and the `v11` data of the real Chromium becomes undecryptable. That is why the bridge must be **read-only**: Secret Service `CreateItem`,
`Item.Delete`, `SetSecret`, `CreateCollection`; KWallet `writePassword`, `writeEntry`, `removeEntry`, `removeFolder`, `createFolder`, `changePassword`, `closeAllWallets`, `deleteWallet` must be blocked.

Fallback route (without a bridge): Deskhand decrypts the `v11` values in the copy DB only inside its own process with the user's key and re-encrypts them to `v10` (fixed key). The price: in the copy the cookies are protected only at the obfuscation level (no confidentiality);
the copy must be 0700 + tmpfs + deleted at the end of the session. This method was not tried (**UNVERIFIED**).

### 2.4 Is Electron `safeStorage` the same?

Partly. The Electron main source (`shell/browser/browser_process_impl.cc`): the `--password-store` values are the same as in Chromium (`kwallet`, `kwallet5`, `kwallet6`, `gnome-libsecret`, `basic`), if not chosen from the desktop environment (KDE6→kwallet6). **The new asynchronous path** (Electron's `safeStorage`): for the
`FreedesktopSecretKeyProvider` `kwallet_folder = "<application name> Keys"`, `key_name = "<application name> Safe Storage"`; before that an optional **Secret Portal** provider (`org.freedesktop.portal.Secret.RetrieveSecret`, gives the key over a pipe/FD, keeps a `token` in `Local State`) is tried with higher priority; if all fail, the fixed password (`PosixKeyProvider`)
([browser_process_impl.cc](https://raw.githubusercontent.com/electron/electron/main/shell/browser/browser_process_impl.cc),
[secret_portal_key_provider.cc](https://chromium.googlesource.com/chromium/src/+/main/components/os_crypt/async/browser/secret_portal_key_provider.cc),
[freedesktop_secret_key_provider.cc](https://chromium.googlesource.com/chromium/src/+/main/components/os_crypt/async/browser/freedesktop_secret_key_provider.cc)).
This new provider uses the **"plain"** algorithm for `OpenSession` with the Secret Service, prefix `v11`. Electron documents: `isEncryptionAvailable`, `getSelectedStorageBackend()` (if `basic_text`, "unprotected"), the supported backends `kwallet`, `kwallet5`, `kwallet6`, `gnome-libsecret`
([safe-storage](https://www.electronjs.org/docs/latest/api/safe-storage)).
Notes:
- KDE bug report 510038 shows that the `Chromium Safe Storage` entry in the `Chromium Keys` folder is shared by Chromium-based applications and sometimes appears twice ([KDE #510038](https://bugs.kde.org/show_bug.cgi?id=510038)); the old synchronous OSCrypt path (for cookies/local storage) uses the application name as the `application` attribute, the folder/key names are the
  fixed "Chromium …". Which Electron version uses which path for which data is **UNVERIFIED** → Deskhand must not hard-code the names, the bridge must forward in a name-independent way.
- If the portal provider is enabled (its default state is **UNVERIFIED**; the code looks at the flags `features::kDbusSecretPortal` and `kSecretPortalKeyProviderUseForEncryption`) the key comes through `org.freedesktop.portal.Desktop`. There is no portal on the private D-Bus → the provider drops with "kNoService"; data encrypted with this key cannot be decrypted.
  The portal recognises the client by `/proc/<pid>`; a call that comes through a relay appears with the relay's identity → an application-specific portal secret cannot be obtained (**UNVERIFIED**, an architectural inference). For now the bridge must NOT cover the portal; in that case for the application concerned the old path must be forced with `--password-store=kwallet6` (or `gnome-libsecret`) and the
  portal token in `Local State` must be cleaned from the copy (**UNVERIFIED**).
- Flatpak Electron applications (Discord, Spotify, Ferdium) cannot benefit from the bridge since they have no `talk` permission to the keyring; the notes in §0 apply to them.

---

## 3. Firefox instant copy — good practices

### 3.1 Files needed for a session (profile root)

| File / directory | What for | Note |
|---|---|---|
| `cookies.sqlite` + `cookies.sqlite-wal` | PERSISTENT cookies | Session cookies (no `expiry`) are NOT here |
| `storage/default/<origin>/` (`ls/data.sqlite`=localStorage, `idb/*.sqlite`, `cache/`) | site stores | The directory name is `https+++github.com`; container/partition: `^userContextId=N`, `^partitionKey=…`. `storage/` can hold hundreds of origins and take a lot of space → ONLY the needed origins |
| `storage/permanent`, `storage.sqlite`, `storage/ls-archive.sqlite` | quota/archive metadata | The `.metadata-v2` file of the origins you copy must also come (inside the directory) |
| `key4.db` + `logins.json` (+ `logins.db`, `logins-backup.json`) | saved passwords | Not needed for session cookies; needed for autofill. These file names were seen in real profiles |
| `cert9.db`, `pkcs11.txt` | client certificates / security modules | |
| `permissions.sqlite` | site permissions (including cookie exceptions) | |
| `containers.json` | Multi-Account Containers mapping | Links the container of the cookies with `userContextId` |
| `sessionstore-backups/recovery.jsonlz4` | **session cookies** + open tabs | see §3.4 |
| `prefs.js` / `user.js` | settings | Sync must be turned off in the copy (§3.6) |
| `extensions/`, `extensions.json`, `addonStartup.json.lz4` | extensions (ad blocker etc.) | |
| `SiteSecurityServiceState.bin`, `AlternateServices.bin` | HSTS / alt-svc | not needed |

EXCLUDE: `lock`, `.parentlock`, `parent.lock`, `signedInUser.json`, `weave/`, `synced-tabs.db*`, `places.sqlite*` (history — not needed), `formhistory.sqlite`,
`datareporting/`, `crashes/`, `minidumps/`, `saved-telemetry-pings/`, `Telemetry.FailedProfileLocks.txt`, `sessionstore-logs/`, `bounce-tracking-protection.sqlite` (if necessary).
The cache is already under `~/.cache/mozilla` (not in the profile).

### 3.2 Copying a locked SQLite safely while it runs

- Firefox opens connections with the "exclusive" VFS by default: in `Connection::initialize` `bool exclusive = StaticPrefs::storage_sqlite_exclusiveLock_enabled() && !mOpenNotExclusive;` and if it
  gets SQLITE_BUSY/LOCKED **when opening** it falls back to the non-exclusive VFS
  ([mozStorageConnection.cpp](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/storage/mozStorageConnection.cpp);
  the default value of the pref was not visible in the source → **UNVERIFIED**; see [Bug 1650201](https://bugzilla.mozilla.org/show_bug.cgi?id=1650201)).
  That the cookie DB cannot be read from outside is an old problem: [Bug 449987](https://bugzilla.mozilla.org/show_bug.cgi?id=449987),
  the solution of [pycookiecheat #48](https://github.com/n8henrie/pycookiecheat/issues/48) is "copy the file (and its WAL) to a temporary place, read from the copy".
- Therefore: **a raw copy + the SQLite backup API from the copy** (verified by experiment to work).
- For consistency (engineering judgement, not sourced): (1) take `stat` (mtime_ns, size) of `.sqlite` and `-wal`; (2) copy the main file and the `-wal` quickly one after the other; (3) DO NOT COPY `-shm` (it is recreated);
  (4) `stat` again: if changed, start over; (5) open the copy normally (writable) and produce a clean single file with `PRAGMA integrity_check` + `.backup`/`VACUUM INTO`. Why: if a WAL checkpoint falls between the two copies the
  main file may be new and the WAL old.
- The `immutable=1` URI ignores the WAL → the latest transactions are lost; do not use it.
- The same loop for `storage/default/<origin>/ls/data.sqlite` and `idb/*.sqlite`; for IndexedDB also take the `.files/` blob directory.

### 3.3 Which profile, which location

The `[Install*] Default=` key in `profiles.ini` is authoritative (`Default=1` in a `[Profile*]` section can point to another profile, §0). The profile directory can be a symlink (e.g. a profile moved to tmpfs) → `realpath`.
Whether it is running: the `lock` symlink `ip:+pid` and `.parentlock` (fcntl) — see §6.

### 3.4 Session cookies

- Only persistent cookies are written to the cookie DB; session cookies are written to the sessionstore (`recovery.jsonlz4`, the `cookies` array at the root) and re-added on "restore session". Source: `SessionCookies.sys.mjs` collects only
  those with `cookie.isSession`; `restore()` adds them with `Services.cookies.add(... isSession=true ...)` and depends on `browser.sessionstore.privacy_level`
  ([SessionCookies.sys.mjs](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/browser/components/sessionstore/SessionCookies.sys.mjs)).
  `recovery.jsonlz4` is updated continuously during the session and becomes `sessionstore.jsonlz4` on close
  ([Mozilla support](https://support.mozilla.org/en-US/questions/1189759)).
- Practical route: put `recovery.jsonlz4` in the copy as `sessionstore.jsonlz4` + `browser.startup.page = 3` ("open the previous session") in the copy's `user.js`. **Side effect:** ALL of the user's tabs are opened in the background (heavy,
  notifications/sound). Better: Deskhand opens the `.jsonlz4` (`mozLz40\0` + LZ4), reduces `windows[*].tabs` to a single empty tab, and keeps `cookies`. Whether `restore()` is called without the window being restored is **UNVERIFIED** →
  experimental verification is needed. Under `sessionstore-backups/` the files `recovery.jsonlz4`, `recovery.baklz4`, `previous.jsonlz4` and `upgrade.jsonlz4-*` can be found.
- It is hard to know beforehand which sites use only session cookies; therefore the "keep this site logged in" list (`oturum.toml`) must be determined by the user, or by trial.

### 3.4.1 Session cookies without expiry: the implemented route and `sessions check`

**The implemented route** (`deskhand/oturum/firefox.py` `_oturum_cerezleri_ekle`): tabs are not restored; `recovery.jsonlz4` is decoded, and those in the root `cookies` array that pass the refusal list / site permission / task-mode filter are
written into the copy's `cookies.sqlite` as **persistent cookies with a 1-day lifetime** (if expiry 0 were written Firefox would discard them at start-up). If there is an **expired** persistent row under the same key (name, host, path,
`originAttributes`) it is deleted: Firefox deletes an expired row from the database late, and the old code (`INSERT OR IGNORE`) skipped the live session cookie because of this stale row. A valid persistent conflicting row stays. For a partitioned (CHIPS)
cookie `isPartitionedAttributeSet` is also written. The values go only to the copy; they are not written to the log or the output; the copy is 0700, its files 0600.

**Example incident (a marketplace seller panel, evidenced):** the seller panel asked for a login in the copy. The cause was NOT that cookies without expiry were not carried: the site's login cookies (`sec_session_id` and a `…_buyer` cookie) are persistent, their lifetime is **2 hours** from the last
request (sliding); only `PHPSESSID` has no expiry and it was being carried to the copy. The user's last login to the panel was the previous evening; when the copy was taken the login cookies had expired ~12 hours earlier. In the user's own Firefox history the panel address also
redirected to the login page first (`/orders` → `/login`), i.e. their own browser was also logged out (the open tab showed the old page). The copy taken after logging in again opened logged in.

**`deskhand sessions check <site>`** (`oturum denetle`; read-only): copies the profile's `cookies.sqlite` consistently into a temporary 0700 folder and reads it, decodes `recovery.jsonlz4`, looks at the newest Firefox copy (first the desktop in the context). Per cookie: name, host,
persistent/no-expiry, remaining time or "expired", same/missing/old in the copy. Values are compared only in memory by SHA-256 digest; neither the value nor the digest is written. The login cookie is guessed by a name pattern (`session`, `sid`, `auth`, `token`, `login`, `user`, `buyer`…) or
given with `--cerez NAME` (fnmatch, repeatable). If there is an expired persistent login cookie and no valid persistent one (if only the no-expiry `PHPSESSID` is left) the session counts as ABSENT: this is the case in the example incident above. The "is it carried to the copy" decision is the same as the copy's rules
(refusal list, account-session permission, task mode, domain-cookie rule; §8 "Site refusal list"): a domain cookie that could go to a refused subdomain counts as `politika_disi` (outside policy). For known hosts as well, no connection is made to the profile's `cookies.sqlite` and `places.sqlite` (read from a temporary
0700 copy including the WAL).

| Exit | Meaning | What to do |
|---|---|---|
| 0 | the copy is up to date and logged in, or there is no copy but the profile is logged in (the next `open firefox` will take it) | continue |
| 1 | no session in the profile / expired / outside policy, the copy has no session or there is a newer login in the profile | have the user log in in their own Firefox, then refresh the copy (`deskhand open firefox`) |
| 2 | invalid domain name | — |

Pre-check for publishing agents: `deskhand sessions check example.com --cerez sec_session_id || <have the user log in>`. Limit: if Firefox has already deleted the expired row and only a no-expiry cookie is left, this cannot be told apart (the server-side timeout is unknown); for a definite
result give the site's login cookie with `--cerez`.

### 3.5 Changes in Firefox 140+

- 147: XDG Base Directory support (§0). The old layout with `MOZ_LEGACY_HOME=1` (a single source, issoh.co.jp/desdelinux news, **UNVERIFIED**).
- `logins.db` is seen in new Firefox versions (§0). No official source explaining this file was **found** in the research.
- No breaking-change report in the cookie/storage format between 140-159 was **found** (the search gave no result) → **UNVERIFIED**; as a precaution open the copy with the SAME Firefox binary (version mismatch: the Mozilla community reports that a `recovery.jsonlz4` written in another
  version cannot be restored in an older version).
- The new profile manager ("selectable profiles"): the `StoreID=` key in `profiles.ini` shows that profile groups are in use (the `Profile Groups/` structure is **UNVERIFIED**).

### 3.6 Sync / Firefox Account risk

A copied profile carries the same device identity; the Mozilla community says "two machines look like a single device, Send Tab / the device manager gets confused, syncs overwrite each other" and recommends deleting `signedInUser.json` as a solution
([support 1202057](https://support.mozilla.org/bm/questions/1202057), [Bug 1234181](https://bugzilla.mozilla.org/show_bug.cgi?id=1234181)). `signedInUser.json` is found in a profile with Sync on. So: do not copy `signedInUser.json`; in addition put
`identity.fxaccounts.enabled = false` in the copy's `user.js` (effect **UNVERIFIED**, confirm by experiment) and leave the `weave/` directory out.

### 3.7 Start-up flags

`firefox --profile COPY --no-remote --new-instance` (verified by experiment to work). Since the Wayland/X11 remote command and the D-Bus name `org.mozilla.firefox.*` are in the private session, the user's Firefox is not affected.

---

## 4. Refresh token rotation risk

General verdict: **If the copy uses and renews a CONSUMABLE secret it shares with the source (a refresh token / a rotating session cookie), the old one held by the original browser can become invalid.** The risk depends on the design of the site:

| Service / class | Evidence | If the copy renews, the main session? |
|---|---|---|
| OAuth 2.x, public client, rotation + reuse detection | RFC 9700 §2.2.2: "Refresh tokens for public clients MUST be sender-constrained or use refresh token rotation"; §4.14.2: if a reused old token is seen the server must "revoke the active refresh token" ([RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)) | **YES, it drops**: the identity of the stale holder cannot be distinguished, the active token is revoked |
| Auth0 (if rotation is on) | reuse → "invalidates the refresh token family, including refresh token 2", re-authentication is needed ([Auth0](https://auth0.com/docs/secure/tokens/refresh-tokens/refresh-token-rotation)) | **YES**, family revocation |
| Okta (if rotation is on) | the previous token is valid during `leeway` (default 30 s, 0-60); then the old token is revoked ([Okta](https://developer.okta.com/docs/guides/refresh-tokens/refresh-token-rotation/)) | **May drop** after the window; family revocation **UNVERIFIED** |
| GitHub App user tokens (expiring) | "Once you use a refresh token, that refresh token and the old user access token will no longer work"; 6 months ([GitHub](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens)) | **YES** (single use) |
| Microsoft identity platform | "Refresh tokens replace themselves with a fresh token upon every use. The Microsoft identity platform doesn't revoke old refresh tokens"; 24 hours for SPA, 90 days for others ([Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)) | Low risk (the old token stays valid); a password change/sign-out is separate |
| Google account cookies (YouTube included) | yt-dlp: "YouTube rotates account cookies frequently on open YouTube browser tabs as a security measure" → exported cookies stop working; recommended: log in in a private window, export, close the window ([yt-dlp wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors)) | The rotation is REAL. Whether the main browser's cookie can go stale and the session drop if the copy renews: **UNVERIFIED** (no document; the yt-dlp evidence shows the copy going stale, the symmetric case is an inference) |
| Discord / Slack / Telegram (user token) | no rotation document **found** | Token rotation **UNVERIFIED**; for Telegram also §1 (key duplication) |
| Banks / payment | no source | **UNVERIFIED**; common practice: a single concurrent session, device/IP binding, OTP per transaction → NEVER copy |
| Device-bound session cookie (DBSC) | Google: general availability on Windows with Chrome 146, to extend to macOS; Linux is not mentioned ([Google blog](https://blog.google/security/protecting-cookies-with-device-bound-session-credentials/)) | Not applied on Linux for now (the sources are inconsistent: other secondary sources list Linux as "phased", **UNVERIFIED**); the copy may break in the future |

Suggestions to reduce the risk:
1. **Site allow/refusal list:** the `deny` default: banks, payment/finance, e-government, health, central identity providers such as `accounts.google.com` / `login.microsoftonline.com`. `allow`: only the sites the task needs; the copy carries ONLY these origins
   (Firefox: `storage/default/<origin>` and the `cookies.sqlite` rows are filtered).
2. **Read-only mode:** navigation and reading free; do not allow requests that renew the session token (such as `/oauth/token`, `/token`, `/api/auth/refresh`, `securetoken.googleapis.com`). For blocking inside the browser the Firefox `WebsiteFilter` policy /
   Chromium `URLBlocklist` can be considered; but whether these policies cover XHR/fetch sub-requests is **UNVERIFIED**.
3. **Short life + one direction:** the copy is deleted as soon as the task ends; it is NEVER written back to the main profile (already in the plan).
4. **Change detection:** at the end of the session compare the digest (hash) of the authentication cookies/stores in the copy with the start; report those that changed to the user as "the token was renewed on this site, your main session may ask for a login once".
5. For SPAs with rotating tokens (Auth0 etc.), if possible trust only cookie-based server sessions (like GitHub web `user_session`; verified by experiment) — if the token sits in `localStorage`/IndexedDB do not copy that origin's store.

---

## 5. Secret Service / KWallet bridge

**Not done in this version; applications that want a password store run only in the foreground.** For applications that need a keyring (Secret Service / KWallet), such as the Chromium family, VS Code and Slack, the policy is `on` (§8): Deskhand does not open them on the background desktop, only on the user's own
screen (in the foreground) (exit code 16).

The reason, briefly: in the private D-Bus session the names `org.freedesktop.secrets` / `org.kde.kwalletd6` do not exist; without a bridge Chromium falls back to the `basic` backend and `v11` cookies cannot be decrypted (§2.2). If a bridge were written its mandatory principles would be: that it be read-only
(if there is no entry the Chromium source goes into the "generate a new password and write it" path, which could overwrite the user's real entry, §2.1, §2.3), that it not open a password window on the user's screen for a locked wallet, and that the private `dbus-daemon` not use the standard activation directories
(a second `ksecretd` could open the same wallet file). Also, no ready-made "single-name relay" tool was found; since `xdg-dbus-proxy` can connect only a single upstream bus per listening socket it cannot do this job alone ([man](https://man.archlinux.org/man/xdg-dbus-proxy.1)).
Because of this cost and risk the relay design is postponed.

---

## 6. Detecting whether an application is running in the user's session

A single signal is not reliable; **treat "running" as true if any is positive** and exclude processes that belong to Deskhand.

1. **Process scan** (`/proc/<pid>`, own `uid`): a `comm`/`exe`/`cmdline` match; for Flatpak `flatpak ps --columns=application,pid,instance`
   (instance directories `$XDG_RUNTIME_DIR/.flatpak/<instance>/info`, [flatpak-ps](https://raw.githubusercontent.com/flatpak/flatpak/main/doc/flatpak-ps.xml));
   filter out what Deskhand started by the `DBUS_SESSION_BUS_ADDRESS` in their environment (the private path) or the `deskhand-app-*.scope` cgroup.
2. **Profile lock:**
   - Firefox/Thunderbird: QUERY the lock with `fcntl(F_GETLK)` on `.parentlock` (WITHOUT taking the lock); fallback: the `lock` symlink `ip:+pid` → `kill(pid,0)` (`nsProfileLock.cpp` does the same).
   - Chromium/Electron: the `SingletonLock` symlink `hostname-pid` → does `/proc/pid` exist and does `exe` match (Chromium's own `IsChromeProcess` logic). Inside Flatpak the PID is in another namespace → this check gives a false negative, use `flatpak ps`.
   - Telegram: the abstract name `@<md5>-TelegramDesktop` in `/proc/net/unix` (source: sandbox.cpp) and the `QLockFile` in /tmp.
   - Steam: `~/.steam/steam.pid` + `steam.pipe` (**UNVERIFIED**).
3. **D-Bus names (real bus):** `NameHasOwner`/`ListNames`: `net.lutris.Lutris`, `org.mozilla.firefox.*`, `org.mpris.MediaPlayer2.<application>` (Spotify is `own` in the manifest), `org.freedesktop.Akonadi.Control`, `org.kde.StatusNotifierItem-<pid>-N`;
   the owner's PID is obtained with `GetConnectionUnixProcessID`. Since Flatpak applications are behind xdg-dbus-proxy, the PID is the proxy's PID → find the application by cgroup/`flatpak ps`.
4. **systemd user units:** Plasma starts applications in `app-*.scope|service` units (<https://systemd.io/DESKTOP_ENVIRONMENTS/>, not read in this report → the validity of the naming is **UNVERIFIED**); `systemctl --user list-units 'app-*'` is extra evidence.
5. **KWin window list** (`resourceClass`): it may be the only way to see an application that is minimised to the tray but running.

Concurrency: there is a race between the check and the start (TOCTOU) → query again AFTER the copy is taken and right before the start; in `paylas` mode additionally Deskhand's own "in use" lock (e.g. `$XDG_RUNTIME_DIR/deskhand/kilit/<application>`) and Deskhand must warn if the user tries to open
that application (the locks of the user's instance do not know this scheme).

---

## 7. Checklist for the background session environment (summary)

- `DBUS_SESSION_BUS_ADDRESS=unix:path=…/deskhand/bus`; `DISPLAY=:77`; remove `WAYLAND_DISPLAY` and `XDG_SESSION_TYPE` / `x11`; `XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6`.
- Private `dbus-daemon`: only Deskhand's service directory; the standard session activation directories CLOSED (otherwise a second `ksecretd` could open the same wallet file).
- There is no keyring bridge in this version (§5): applications that need a keyring are not opened in the background.
- Electron (Flatpak Discord/Spotify): `--user-data-dir=COPY` (in Flatpak the copy must be under `~/.var/app/<id>/…` so that it is visible from the sandbox); Firefox: `--profile COPY --no-remote --new-instance`.
- Sync off (Firefox Account, Chrome/Vivaldi/Brave sync).
- The copy 0700, tmpfs (`$XDG_RUNTIME_DIR`), reset with `deskhand oturum sil` (delete session); stale profile backups (`*-backup` etc.) are not used as a source.
- Audio: silent output (`deskhand-sessiz`); live sound/playback such as a Spotify/Discord/WhatsApp call is forbidden.

---

## 8. Default `oturum.toml` policy

Source: `deskhand/data/oturum.toml`. The user can override it with `CONFIG_DIR/oturum.toml` (only the keys given are merged). The policy is computed not from the raw name the caller wrote but from the RESOLVED application: the `.desktop` id, the binary name in `Exec` (also the real path), the
Flatpak id and the given name. If an application matches several sections the MOST RESTRICTIVE decision wins: `kapali` > `on` > `bekle` > `kopya` > `paylas`.

Decision values:
- `kopya` — open in the background with a consistent, one-way instant copy (the source is never written).
- `paylas` — directly with the user's files (only while the application is CLOSED in the user's session).
- `bekle` — two clients at the same time break the session; wait until the user closes it.
- `on` — only on the user's screen (in the foreground); cannot be opened in the background (applications that need a password store; Obsidian, whose vault writes to the real files). Exit code 16.
- `kapali` — never run.

`kapali_iken`: while the application is NOT RUNNING in the user's session; `acik_iken`: while it is running. `keyring`: whether the application needs a keyring (there is no bridge in this version, §5).

| Key | kapali_iken | acik_iken | keyring | Note |
|---|---|---|---|---|
| `firefox` | kopya | kopya | no | except `lock*`, `signedInUser.json`, `weave/`, `places*`, `sessionstore.jsonlz4`, `formhistory.sqlite`; only the permitted `storage/default/<origin>`; Sync off |
| `discord` (Flatpak) | kopya | kopya | no | except caches |
| `spotify` (Flatpak) | kopya | kopya | no | playback forbidden (when a second device plays on the same account the first pauses) |
| `chromium`, `vivaldi`, `chrome`, `brave`, `edge`, `opera` | on | on | yes | foreground only |
| `vscode` | on | on | yes | foreground only |
| `slack` | on | on | yes | foreground only |
| `obsidian` | on | on | no | the vault writes to the real files; a background instance would corrupt it → foreground only |
| `telegram` (+ derivatives), `signal`, `element`, `whatsapp` (wrappers) | bekle | bekle | no | a second client drops the user's main session |
| `steam`, `heroic`, `lutris`, `thunderbird` | bekle | bekle | no | single session / shared data |
| `ferdium` | bekle | bekle | no | as risky as the riskiest of the services inside |
| `keepassxc`, `bitwarden` | kapali | kapali | — | password manager: the single-instance lock brings the vault to the user's screen |
| `kmail`, `akonadi` | kapali | kapali | yes | a single MySQL data directory |
| `nextcloud` | kapali | kapali | yes | two sync clients |
| `_varsayilan` (unknown application) | paylas | bekle | no | see below |

**Unknown application.** If the application is DEFINITELY not running in the user's session (the `Exec` binary is not in `/proc`, no Flatpak instance) a normal start (`paylas`: with its own data, as if the user opened it). If it is running OR it cannot be known (the binary was not found, a
launcher shell script, an AppImage, `/proc` was unreadable) `bekle`: the single-instance lock can hand the window over to the user's screen.

**Site refusal list** (`[site].reddet`): the cookies/store of these domain names are NOT TAKEN into the copy; a plain domain name also covers its subdomains. Saved passwords (`logins.json` / `logins.db`) are filtered with the same list.

**Domain cookie** (`.example.com`, a leading dot) is sent to ALL subdomains of `example.com`; so if it can go to a refused subdomain it is also refused (`Politika.cerez_reddedildi`). The meaning of the rule is split in two according to the end of the pattern:
- **A rule with a fixed end** (a plain domain `accounts.google.com`, `*.bank.com`, `*.gov.tr`, `login?.example.com`): the cookie is refused if the rule can match ANY subdomain the domain cookie can go to (`X.example.com`). The decision is made only from the rule, the profile is not looked at (fail-safe):
  `accounts.google.com` → `.google.com`, `*.bank.com` → `.bank.com`, `*.secret.example.com` → `.example.com` are refused; `*.gov.tr` does not touch `.example.com`. A rule that has `*` in the middle and a fixed end keeps it wide: `*bank*.com.tr` drops the domain cookie of ALL domains ending with `.com.tr`
  (`bank.example.com.tr` is a possible subdomain for each of them).
- **A rule that ends with `*`** (`*bank*`, `*checkout*`, `bank.*`): this rule can match a subdomain of every domain (`bank.<domain>`). If applied literally, in the default list all domain cookies (including `.google.com` / `.live.com` for which an account-session permission was given) would drop. So it refuses only **with evidence**:
  if there is a host known from the profile that is a subdomain of the domain and that matches the refusal list (`*bank*` + the known `bank.example.com` → `.example.com`). Known hosts: cookie hosts, site store folders (`storage/default`), the session cookie and open-tab hosts in `recovery.jsonlz4`, the `places.sqlite` origin list.
  `places.sqlite` is read from a temporary 0700 copy together with its WAL; new visits sitting in the WAL while Firefox is open also count, no file is created in the profile. When the trailing `*`s are dropped the remaining fixed part is still decided from the rule (`*` also matches the empty string):
  `*.bank.com*`, `*.bank.com` refuse `.bank.com` without evidence; `*bank*` → `*bank` fits no `.com` domain, it asks for evidence.
- **Known limit (deliberately left so):** a rule ending with `*` drops the domain cookie only of subdomains SEEN in the profile; a subdomain never seen (not visited, with no cookie/store) is not covered. To keep such a subdomain out for certain, add a rule with a fixed end (`bank.example.com` or `*.bank.example.com`).
- **Spelling equivalence:** both the rule and the host/cookie domain are reduced to the same forms: lower case, trailing dot(s) dropped, IDNA dots (`。` `．` `｡`) become `.`; every name is handled in three spellings: as written, nameprep'd Unicode and punycode (`xn--…`). In the refusal list a match of ANY spelling is enough:
  the rule `*.bankası.com` also refuses the cookie `.xn--bankas-u9a.com` (and the reverse), `*xn--*` refuses all IDN domains, `*bank*` refuses `xn--bank-cpa.com` (`baénk.com`). In the allow list (task sites) both the Unicode AND the punycode spelling of the name must match. A leading dot in a plain rule
  (`.bank.com`) means the same as `bank.com` (the domain + its subdomains). A host/cookie domain that carries an IDNA label that cannot be resolved (a broken punycode, an `xn--` label that encodes upper case or non-normalised text) is refused (fail-closed).
- **Bank/payment sessions are not carried at all in this version:** the bank/payment entries in the default list are not opened by any panel permission (Account sessions) or by a task. In 1.0.0 they will be carried with the user's explicit approval and ONLY for that task (per-task authorisation keys).

The copy (`firefox.hazirla`) and `sessions check` use the same rule and the same set of known hosts. After filtering, the copy's `cookies.sqlite` is rebuilt with `VACUUM INTO`: deleted values do not remain in the file bytes. The list contains:
- general patterns: `*bank*`, `*banka*`, `*odeme*`, `*payment*`, `*checkout*`, `*paypal*`, `*stripe*`, `*e-devlet*`, `*edevlet*`;
- Turkish banks and payment institutions (e.g. İş Bankası, Garanti BBVA, Yapı Kredi, Akbank, Ziraat, Halkbank, Vakıfbank, QNB, DenizBank, ING, TEB, Kuveyt Türk, Enpara, Papara, ininal, Param, iyzico, PayTR);
- international payment: PayPal, Stripe, Wise/TransferWise, Revolut;
- government: `turkiye.gov.tr`, `gib.gov.tr`, `sgk.gov.tr`, `*.gov.tr`, `*.gov` (the e-Devlet permission does NOT open `*.gov`);
- central identity: `accounts.google.com`, `login.microsoftonline.com`, `login.live.com`, `securetoken.googleapis.com`.

**Account sessions (user permission):** if Microsoft, Google or the e-Devlet/government group is turned on from the panel Settings → "Account sessions" (ONLY from there; ARCHITECTURE §4) the refusal entries of that group leave the refusal list in the Firefox copy (cookies + saved login + store). The bank/payment
entries leave with no permission; in task mode the permission is not applied. Default off.

Example override:

```toml
[genel]
kopya_dizini = "$XDG_RUNTIME_DIR/deskhand/oturum"   # 0700, tmpfs
origin_boyut_siniri_mb = 50                         # upper limit per storage/default/<origin>

[site]
reddet = ["*bank*", "*odeme*", "*paypal*", "accounts.google.com", "login.microsoftonline.com", "*.gov.tr"]
izin = []                                           # filled per task

[uygulama.firefox]
kapali_iken = "kopya"
acik_iken   = "kopya"
senkron     = false
disla       = ["signedInUser.json", "weave", "lock", ".parentlock", "places.sqlite"]

[uygulama.telegram]
kapali_iken = "bekle"
acik_iken   = "bekle"
```

---

## 9. UNVERIFIED summary (to be closed by experiment)

1. The real backend of Chromium/Vivaldi (`kwallet6` / libsecret / basic) changes from installation to installation; Vivaldi's keyring name must be verified per version.
2. Which Electron version uses the old/new key path and the Secret Portal for which data (the `kDbusSecretPortal` default).
3. Firefox: restoring only the cookies from `recovery.jsonlz4`, the effect of `identity.fxaccounts.enabled=false`, the role of `logins.db`, the default of `storage.sqlite.exclusiveLock.enabled`, format changes between 140-159.
4. Whether the copy rotating cookies at Google drops the MAIN browser; Discord/Slack/Telegram token rotation; banks.
5. Steam concurrent-login behaviour; two clients from the same store in WhatsApp Web; Signal double-ratchet corruption; Heroic/Epic token rotation.
6. The `app-*.scope` naming in Plasma and the content of `systemd.io/DESKTOP_ENVIRONMENTS`.

## 10. Practical outcome

- **Works and low risk:** Firefox (copy) and Flatpak Electron applications (Discord, Spotify; no keyring needed).
- **Foreground only:** applications that need a keyring (the Chromium family, VS Code, Slack) and Obsidian, whose vault writes to the real files. If background opening is requested, exit code 16.
- **NEVER concurrent:** Telegram, Signal, Element, WhatsApp wrappers, Steam, Akonadi, Nextcloud, Ferdium. For these the price of a mistake is the death of the user's main session (Telegram AUTH_KEY_DUPLICATED, Signal 4409, Element UTD).
- **The biggest hidden risk:** token rotation (Auth0/GitHub App/RFC 9700 style) and Google cookie rotation: if the copy renews, the main session can drop. A site refusal list + a short life + change detection are a must.
