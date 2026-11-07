#!/usr/bin/env bash
# Deskhand kurulumu (kullanıcı başına, sudo yok). Tekrar çalıştırmak güvenlidir (idempotent).
# Paket KURMAZ: eksik bağımlılıkları listeler ve kurulum komutunu gösterir.
#   ./install.sh                 kur / güncelle
#   ./install.sh --dry-run       hiçbir şey yapmadan yapılacakları yazdır
#   ./install.sh --no-autostart  panel oturum açılışında başlamasın
set -euo pipefail

# UI language: the first non-empty of LC_ALL / LC_MESSAGES / LANG decides;
# a value starting with "tr" gives Turkish, anything else English.
TR=0
for _loc in "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
    if [[ -n "$_loc" ]]; then
        if [[ "$_loc" == tr* ]]; then TR=1; fi
        break
    fi
done
unset _loc
# L TURKISH ENGLISH: print the text in the UI language
L() { if (( TR )); then printf '%s' "$1"; else printf '%s' "$2"; fi; }
DRYTAG="$(L '[deneme]' '[dry-run]')"

usage() {
    if (( TR )); then
        cat <<'EOF'
Deskhand kurulumu (kullanıcı başına, sudo yok). Tekrar çalıştırmak güvenlidir.
  ./install.sh                 kur / güncelle
  ./install.sh --dry-run       hiçbir şey yapmadan yapılacakları yazdır
  ./install.sh --no-autostart  panel (tepsi) oturum açılışında başlamasın
  ./install.sh --help          bu yardımı göster
Paket kurmaz: eksikleri listeler, kurulum komutunu gösterir.
Kaynak klasörü herhangi bir yerde olabilir; taşırsan ./install.sh'i yeniden çalıştır.
EOF
    else
        cat <<'EOF'
Deskhand installer (per user, no sudo). Safe to run again.
  ./install.sh                 install / update
  ./install.sh --dry-run       print what would be done, change nothing
  ./install.sh --no-autostart  do not start the panel (tray) at login
  ./install.sh --help          show this help
It installs no packages: it lists what is missing and shows the command.
The source folder can live anywhere; if you move it, run ./install.sh again.
EOF
    fi
}

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PKG_DIR="$SRC_DIR/deskhand"
CFG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="$HOME/.local/bin"
WRAPPER="$BIN_DIR/deskhand"
APP_FILE="$DATA_HOME/applications/deskhand.desktop"
AUTOSTART_FILE="$CFG_HOME/autostart/deskhand.desktop"
ICON_FILE="$DATA_HOME/icons/hicolor/scalable/apps/deskhand.svg"
MARK="# deskhand wrapper (install.sh)"
DESKTOP_MARK="X-Deskhand-Installed=true"
PY=/usr/bin/python3

DRY=0
AUTOSTART=1
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY=1 ;;
        --no-autostart) AUTOSTART=0 ;;
        -h|--help) usage; exit 0 ;;
        *) printf '%s\n' "$(L "Bilinmeyen seçenek: $arg" "Unknown option: $arg")" >&2; exit 2 ;;
    esac
done

quiet() { "$@" >/dev/null 2>&1; }
say()  { printf '==> %s\n' "$*"; }
warn() { printf '%s %s\n' "$(L 'UYARI:' 'WARNING:')" "$*" >&2; }
die()  { printf '%s %s\n' "$(L 'HATA:' 'ERROR:')" "$*" >&2; exit 1; }

# run CMD...: execute, or print it in --dry-run mode
run() {
    if (( DRY )); then
        printf '%s' "$DRYTAG"; printf ' %q' "$@"; printf '\n'
    else
        "$@"
    fi
}

# write_file DEST MODE  (content on stdin)
write_file() {
    local dest="$1" mode="$2" content
    content="$(cat)"
    if (( DRY )); then
        printf '%s %s\n' "$DRYTAG" "$(L "yaz $dest (izin $mode):" "write $dest (mode $mode):")"
        printf '%s\n' "$content" | sed 's/^/           | /'
        return 0
    fi
    mkdir -p "$(dirname "$dest")"
    printf '%s\n' "$content" > "$dest.tmp.$$"
    chmod "$mode" "$dest.tmp.$$"
    mv -f "$dest.tmp.$$" "$dest"
}

# is_ours FILE MARKER: FILE exists and carries our marker
is_ours() { [[ -e "$1" ]] && grep -qF "$2" "$1" 2>/dev/null; }

# desktop_exec PATH: the program of a desktop-entry Exec= key (quoted when it has a reserved character)
DESKTOP_SAFE_RE='[^-[:alnum:]_./+,:=@%]'
desktop_exec() {
    local s="${1//%/%%}"
    if [[ "$s" =~ $DESKTOP_SAFE_RE ]]; then
        s="${s//\\/\\\\\\\\}"; s="${s//\"/\\\\\"}"; s="${s//\`/\\\\\`}"; s="${s//\$/\\\\\$}"
        s="\"$s\""
    fi
    printf '%s' "$s"
}

# ---------------------------------------------------------------- checks
if (( EUID == 0 )); then
    die "$(L 'root olarak çalıştırma: Deskhand kullanıcı başına kurulur (sudo olmadan ./install.sh)' \
             'do not run as root: Deskhand installs per user (run ./install.sh without sudo)')"
fi
for p in "$HOME" "$SRC_DIR" "$CFG_HOME" "$DATA_HOME"; do
    [[ "$p" != *$'\n'* ]] || die "$(L 'yol satır sonu içeriyor, desteklenmiyor' 'a path contains a newline; not supported')"
done
say "$(L "Kaynak: $SRC_DIR" "Source: $SRC_DIR")"
if (( DRY )); then say "$(L 'DENEME MODU: hiçbir değişiklik yapılmayacak' 'DRY-RUN MODE: nothing will be changed')"; fi
[[ -x "$PY" ]] || die "$(L "gerekli program yok: $PY" "required program not found: $PY")"
if ! quiet "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    pyver="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
    die "$(L "Python >= 3.11 gerekli (bulunan: ${pyver:-?})" "Python >= 3.11 is required (found: ${pyver:-?})")"
fi
for f in deskhand/__init__.py deskhand/cli.py deskhand/yardimci/Makefile deskhand/data/deskhand.desktop deskhand/data/deskhand.svg; do
    if [[ ! -e "$SRC_DIR/$f" ]]; then
        if (( DRY )); then warn "$(L "eksik dosya (gerçek kurulumda hata olur): $f" "missing file (a real install would fail): $f")"
        else die "$(L "eksik dosya: $SRC_DIR/$f" "missing file: $SRC_DIR/$f")"; fi
    fi
done
# our command must not replace someone else's: checked BEFORE anything is changed
if [[ -e "$WRAPPER" ]] && ! is_ours "$WRAPPER" "$MARK"; then
    msg="$(L "$WRAPPER var ve bizim değil; elle kaldırıp tekrar dene" "$WRAPPER exists and is not ours; remove it by hand and try again")"
    if (( DRY )); then warn "$msg $(L '(gerçek kurulumda hata olur)' '(a real install would fail)')"
    else die "$msg"; fi
fi
# an earlier install: a missing autostart entry then means the user turned it off
PREV_INSTALL=0
if is_ours "$WRAPPER" "$MARK"; then PREV_INSTALL=1; fi

# ---------------------------------------------------------------- session
if [[ "${XDG_SESSION_TYPE:-}" != wayland || "${XDG_CURRENT_DESKTOP:-}" != *KDE* ]]; then
    warn "$(L "oturum KDE Plasma (Wayland) görünmüyor (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-?}, XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-?}); ön plan (kendi ekranın) yalnız Plasma 6 Wayland'de desteklenir" \
              "the session does not look like KDE Plasma (Wayland) (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-?}, XDG_CURRENT_DESKTOP=${XDG_CURRENT_DESKTOP:-?}); the foreground (your own screen) is supported on Plasma 6 Wayland only")"
fi

# ---------------------------------------------------------------- dependencies (checked, never installed)
PAC=()      # missing official-repo packages (Arch names)
AUR=()      # missing AUR packages
DEP_ANY=0
# dep_miss KIND PKG REPO TURKISH ENGLISH   KIND: req | rec   REPO: pac | aur | ""
dep_miss() {
    local kind="$1" pkg="$2" repo="$3" tag
    DEP_ANY=1
    case "$repo" in
        pac) [[ " ${PAC[*]} " == *" $pkg "* ]] || PAC+=("$pkg") ;;
        aur) [[ " ${AUR[*]} " == *" $pkg "* ]] || AUR+=("$pkg") ;;
    esac
    if [[ "$kind" == req ]]; then tag="$(L 'eksik' 'missing')"
    else tag="$(L 'isteğe bağlı, eksik' 'optional, missing')"; fi
    warn "$tag: $(L "$4" "$5")"
}
has_module() { quiet "$PY" -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec(sys.argv[1]) is None)' "$1"; }

say "$(L 'Bağımlılıklar denetleniyor (hiçbir paket kurulmaz)' 'Checking dependencies (no package is installed)')"
# foreground: your own Plasma screen
command -v kdotool >/dev/null 2>&1 || dep_miss req kdotool-bin aur \
    "kdotool (AUR: kdotool-bin): ön planda pencere bulma" "kdotool (AUR: kdotool-bin): finding windows in the foreground"
command -v dotool >/dev/null 2>&1 || dep_miss req dotool aur \
    "dotool (AUR): ön planda fare/klavye" "dotool (AUR): mouse/keyboard in the foreground"
command -v spectacle >/dev/null 2>&1 || dep_miss req spectacle pac \
    "spectacle: ön planda ekran görüntüsü" "spectacle: screenshots in the foreground"
# OCR (both desktops)
if ! command -v tesseract >/dev/null 2>&1; then
    dep_miss req tesseract pac "tesseract: metin okuma (OCR)" "tesseract: text recognition (OCR)"
    PAC+=(tesseract-data-tur tesseract-data-eng)
else
    langs="$(tesseract --list-langs 2>&1 || true)"
    grep -qx 'tur' <<<"$langs" || dep_miss req tesseract-data-tur pac "Türkçe OCR verisi (tesseract-data-tur)" "Turkish OCR data (tesseract-data-tur)"
    grep -qx 'eng' <<<"$langs" || dep_miss req tesseract-data-eng pac "İngilizce OCR verisi (tesseract-data-eng)" "English OCR data (tesseract-data-eng)"
fi
# background desktop
command -v Xvfb >/dev/null 2>&1 || dep_miss req xorg-server-xvfb pac \
    "Xvfb (xorg-server-xvfb): görünmez arka plan masaüstü" "Xvfb (xorg-server-xvfb): the invisible background desktop"
command -v openbox >/dev/null 2>&1 || dep_miss req openbox pac \
    "openbox: arka plan masaüstünün pencere yöneticisi" "openbox: window manager of the background desktop"
command -v xdotool >/dev/null 2>&1 || dep_miss rec xdotool pac \
    "xdotool: arka planda yedek araç" "xdotool: fallback tool in the background"
command -v pactl >/dev/null 2>&1 || dep_miss rec libpulse pac \
    "pactl (libpulse): arka plan uygulamaları için sessiz ses çıkışı (yoksa ses tamamen kapalı olur)" \
    "pactl (libpulse): a silent audio sink for background apps (without it their audio is cut off entirely)"
command -v systemd-run >/dev/null 2>&1 || dep_miss rec systemd "" \
    "systemd-run: arka plan masaüstü için bellek sınırı" "systemd-run: memory limit for the background desktop"
# Python modules
for pair in "PyQt6:python-pyqt6:panel, tepsi ve onay diyaloğu:panel, tray and approval dialog" \
            "Xlib:python-xlib:arka planda girdi ve görüntü:input and screenshots in the background" \
            "numpy:python-numpy:görüntü işleme:image processing" \
            "PIL:python-pillow:görüntü:images" \
            "jeepney:python-jeepney:D-Bus (bildirimler, meşgul algısı, kısayol):D-Bus (notifications, busy detection, shortcut)" \
            "mcp:python-mcp:MCP sunucusu (deskhand mcp):the MCP server (deskhand mcp)"; do
    IFS=: read -r mod pkg tr en <<<"$pair"
    has_module "$mod" || dep_miss req "$pkg" pac "Python modülü $mod ($pkg): $tr" "Python module $mod ($pkg): $en"
done
has_module scipy || dep_miss rec python-scipy pac "Python modülü scipy (python-scipy): simge eşleme" \
                                                  "Python module scipy (python-scipy): icon matching"
# build tools for the activity helper
HELPER_OK=1
for t in cc make pkg-config; do
    command -v "$t" >/dev/null 2>&1 || HELPER_OK=0
done
if (( HELPER_OK )) && ! quiet pkg-config --exists wayland-client; then HELPER_OK=0; fi
if (( ! HELPER_OK )); then
    dep_miss rec base-devel pac \
        "derleyici/make/pkg-config ya da wayland-client yok: klavye etkinliği yardımcısı derlenemez (insan önceliği yalnız fareye bakar)" \
        "no compiler/make/pkg-config or wayland-client: the keyboard-activity helper cannot be built (human priority then watches the mouse only)"
    [[ " ${PAC[*]} " == *" wayland "* ]] || PAC+=(wayland)
fi

if (( ${#PAC[@]} || ${#AUR[@]} )); then
    ids=" $( [[ -r /etc/os-release ]] && . /etc/os-release; printf '%s %s' "${ID:-}" "${ID_LIKE:-}" ) "
    say "$(L 'Eksikler için komut (kendin çalıştır):' 'Command for what is missing (run it yourself):')"
    if (( ${#PAC[@]} )); then printf '    sudo pacman -S --needed %s\n' "${PAC[*]}"; fi
    if (( ${#AUR[@]} )); then
        helper=""
        for h in paru yay; do command -v "$h" >/dev/null 2>&1 && { helper="$h"; break; }; done
        if [[ -n "$helper" ]]; then printf '    %s -S --needed %s\n' "$helper" "${AUR[*]}"
        else printf '    %s %s\n' "$(L 'AUR (paru/yay vb.):' 'AUR (paru/yay etc.):')" "${AUR[*]}"; fi
    fi
    if [[ "$ids" != *" arch "* ]]; then
        say "$(L 'Paket adları Arch/CachyOS içindir; başka dağıtımlarda karşılıklarını kur.' \
                 'Package names are for Arch/CachyOS; on other distros install the equivalents.')"
    fi
elif (( ! DEP_ANY )); then
    say "$(L 'Bağımlılıklar tamam' 'Dependencies OK')"
fi

# dotool writes to /dev/uinput (foreground input)
if [[ ! -e /dev/uinput ]]; then
    warn "$(L '/dev/uinput yok (uinput çekirdek modülü yüklü değil); ön plan girdisi çalışmaz' \
              '/dev/uinput does not exist (the uinput kernel module is not loaded); foreground input will not work')"
    printf '    sudo modprobe uinput\n'
    printf '    echo uinput | sudo tee /etc/modules-load.d/uinput.conf   # %s\n' "$(L 'açılışta yükle' 'load at boot')"
elif [[ ! -w /dev/uinput ]]; then
    warn "$(L '/dev/uinput yazılabilir değil; dotool paketinin udev kuralı input grubuna izin verir' \
              '/dev/uinput is not writable; the dotool package udev rule grants access to the input group')"
    printf '    sudo usermod -aG input "$USER"   # %s\n' "$(L 'sonra oturumu kapatıp aç' 'then log out and back in')"
fi

# ---------------------------------------------------------------- activity helper (C)
if (( HELPER_OK )); then
    say "$(L 'Klavye/fare etkinliği yardımcısı derleniyor' 'Building the keyboard/mouse activity helper')"
    if ! run make -s -C "$PKG_DIR/yardimci"; then
        warn "$(L 'yardımcı derlenemedi; insan önceliği yalnız fareye bakacak' 'the helper could not be built; human priority will watch the mouse only')"
    fi
fi

# ---------------------------------------------------------------- command
say "$(L "Komut: $WRAPPER" "Command: $WRAPPER")"
# a tiny Python launcher instead of PYTHONPATH: PYTHONPATH would leak into every app that
# Deskhand starts. The path is embedded as a Python literal (safe for any characters).
SRC_LIT="$(printf '%s' "$SRC_DIR" | "$PY" -c 'import sys; print(repr(sys.stdin.read()))')"
write_file "$WRAPPER" 0755 <<EOF
#!$PY
$MARK
import sys
sys.path.insert(0, $SRC_LIT)
from deskhand.cli import main
main()
EOF
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$(L "$BIN_DIR PATH içinde değil: çoğu dağıtımda oturumu kapatıp açınca eklenir; ya da bash/zsh: ~/.profile içine export PATH=\"\$HOME/.local/bin:\$PATH\", fish: fish_add_path $BIN_DIR" \
                 "$BIN_DIR is not in PATH: on most distros it is added after logging out and back in; otherwise bash/zsh: add export PATH=\"\$HOME/.local/bin:\$PATH\" to ~/.profile, fish: fish_add_path $BIN_DIR")" ;;
esac

# ---------------------------------------------------------------- icon + desktop entries
say "$(L "Simge: $ICON_FILE" "Icon: $ICON_FILE")"
run install -Dm644 "$SRC_DIR/deskhand/data/deskhand.svg" "$ICON_FILE"

# desktop_entry ARGS: deskhand/data/deskhand.desktop with an absolute Exec, without the template comments, plus our marker
desktop_entry() {
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            '#'*) continue ;;
            Exec=*) line="Exec=$(desktop_exec "$WRAPPER") $1" ;;
        esac
        printf '%s\n' "$line"
    done <"$SRC_DIR/deskhand/data/deskhand.desktop"
    printf '%s\n' "$DESKTOP_MARK"
}

say "$(L "Uygulama menüsü: $APP_FILE" "Application menu entry: $APP_FILE")"
if [[ -e "$APP_FILE" ]] && ! is_ours "$APP_FILE" "$DESKTOP_MARK"; then
    warn "$(L "$APP_FILE bizim değil, dokunulmadı" "$APP_FILE is not ours, left untouched")"
else
    desktop_entry "panel" | write_file "$APP_FILE" 0644
fi

# the panel must be running to answer approval requests: start it (tray only) at login
say "$(L "Oturum açılışında panel (tepsi): $AUTOSTART_FILE" "Panel (tray) at login: $AUTOSTART_FILE")"
if (( ! AUTOSTART )); then
    if is_ours "$AUTOSTART_FILE" "$DESKTOP_MARK"; then run rm -f "$AUTOSTART_FILE"; fi
    say "$(L 'Kapalı (--no-autostart). Onay istekleri için panel açık olmalı: deskhand panel --tepsi' \
             'Off (--no-autostart). The panel must be running to answer approval requests: deskhand panel --tepsi')"
elif [[ -e "$AUTOSTART_FILE" ]] && ! is_ours "$AUTOSTART_FILE" "$DESKTOP_MARK"; then
    warn "$(L "$AUTOSTART_FILE bizim değil, dokunulmadı" "$AUTOSTART_FILE is not ours, left untouched")"
elif (( PREV_INSTALL )) && [[ ! -e "$AUTOSTART_FILE" ]]; then
    say "$(L 'Yok (önceden kapatılmış), yeniden eklenmedi' 'Absent (turned off earlier), not added again')"
else
    desktop_entry "panel --tepsi" | write_file "$AUTOSTART_FILE" 0644
fi
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    run quiet kbuildsycoca6 --noincremental || true
fi

# ---------------------------------------------------------------- next steps
say "$(L 'Bitti. Sıradaki adımlar:' 'Done. Next steps:')"
cat <<EOF
    deskhand panel                 # $(L 'izleme paneli + tepsi (onaylar için açık kalmalı)' 'monitoring panel + tray (keep it running for approvals)')
    deskhand busy                  # $(L 'meşgul algısını dene (yalnız okur)' 'try busy detection (read-only)')
    deskhand desktop start         # $(L 'görünmez masaüstünü başlat' 'start the invisible desktop')

    # $(L 'Claude Code için MCP sunucusu (kullanıcı kapsamı):' 'MCP server for Claude Code (user scope):')
    claude mcp add --scope user --transport stdio deskhand -- $(printf '%q' "$WRAPPER") mcp
    claude mcp add --scope user --transport stdio deskhand-bg -- $(printf '%q' "$WRAPPER") mcp --desktop background
EOF
