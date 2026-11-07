#!/usr/bin/env bash
# Deskhand kaldırma: install.sh'in yaptığı her şeyi geri alır. Paket kaldırmaz.
#   ./uninstall.sh            kaldır (~/.config/deskhand ayarların, simgelerin ve akışların KORUNUR)
#   ./uninstall.sh --purge    ayarları, günlükleri, önbelleği, kayıtlı simge/akışları da sil
#   ./uninstall.sh --dry-run  hiçbir şey yapmadan yapılacakları yazdır
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
Deskhand kaldırma: install.sh'in yaptığı her şeyi geri alır (paket kaldırmaz).
  ./uninstall.sh            kaldır (~/.config/deskhand ayarların ve kayıtlı simge/akışların KORUNUR)
  ./uninstall.sh --purge    ayarları, günlükleri, önbelleği ve kayıtlı simge/akışları da sil
  ./uninstall.sh --dry-run  hiçbir şey yapmadan yapılacakları yazdır
  ./uninstall.sh --help     bu yardımı göster
EOF
    else
        cat <<'EOF'
Deskhand uninstaller: undoes everything install.sh did (removes no packages).
  ./uninstall.sh            uninstall (your settings in ~/.config/deskhand and saved icons/flows are KEPT)
  ./uninstall.sh --purge    also delete settings, logs, cache and saved icons/flows
  ./uninstall.sh --dry-run  print what would be done, change nothing
  ./uninstall.sh --help     show this help
EOF
    fi
}

CFG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
RUN_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/deskhand"
BIN_DIR="$HOME/.local/bin"
WRAPPER="$BIN_DIR/deskhand"
APP_FILE="$DATA_HOME/applications/deskhand.desktop"
SHOT_FILE="$DATA_HOME/applications/deskhand-goruntu.desktop"
AUTOSTART_FILE="$CFG_HOME/autostart/deskhand.desktop"
ICON_FILE="$DATA_HOME/icons/hicolor/scalable/apps/deskhand.svg"
MARK="# deskhand wrapper (install.sh)"
DESKTOP_MARK="X-Deskhand-Installed=true"
PY=/usr/bin/python3

DRY=0
PURGE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY=1 ;;
        --purge) PURGE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf '%s\n' "$(L "Bilinmeyen seçenek: $arg" "Unknown option: $arg")" >&2; exit 2 ;;
    esac
done

quiet() { "$@" >/dev/null 2>&1; }
say()  { printf '==> %s\n' "$*"; }
warn() { printf '%s %s\n' "$(L 'UYARI:' 'WARNING:')" "$*" >&2; }
run() {
    if (( DRY )); then
        printf '%s' "$DRYTAG"; printf ' %q' "$@"; printf '\n'
    else
        "$@"
    fi
}
# remove FILE only if it contains MARKER (never delete someone else's file)
rm_marked() {
    local f="$1" marker="$2"
    if [[ -e "$f" ]]; then
        if grep -qF "$marker" "$f" 2>/dev/null; then
            run rm -f "$f"
        else
            warn "$(L "$f bizim değil, dokunulmadı" "$f is not ours, left untouched")"
        fi
    fi
}

if (( EUID == 0 )); then
    printf '%s %s\n' "$(L 'HATA:' 'ERROR:')" \
        "$(L 'root olarak çalıştırma: Deskhand kullanıcı başına kurulur (sudo olmadan ./uninstall.sh)' \
             'do not run as root: Deskhand is installed per user (run ./uninstall.sh without sudo)')" >&2
    exit 1
fi
if (( DRY )); then say "$(L 'DENEME MODU: hiçbir değişiklik yapılmayacak' 'DRY-RUN MODE: nothing will be changed')"; fi

# ---------------------------------------------------------------- running parts
# the background desktop first (its apps, Xvfb, the silent audio sink), while our command still exists
if [[ -e "$RUN_DIR/sanal.json" ]] && grep -qF "$MARK" "$WRAPPER" 2>/dev/null; then
    say "$(L 'Görünmez masaüstü durduruluyor' 'Stopping the invisible desktop')"
    run "$WRAPPER" masaustu durdur || warn "$(L 'görünmez masaüstü durdurulamadı' 'could not stop the invisible desktop')"
fi

# the panel: by the PID it wrote (RUN_DIR/panel.pid), checked against /proc; no pattern kill
if [[ -r "$RUN_DIR/panel.pid" ]]; then
    pid="$("$PY" -c 'import json, sys; print(int(json.load(open(sys.argv[1]))["pid"]))' "$RUN_DIR/panel.pid" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && [[ -r "/proc/$pid/cmdline" ]] && \
       tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q 'deskhand'; then
        say "$(L "Panel kapatılıyor (PID $pid)" "Closing the panel (PID $pid)")"
        run kill -TERM "$pid" || true
    fi
fi

# ---------------------------------------------------------------- files
say "$(L 'Komut kaldırılıyor' 'Removing the command')"
rm_marked "$WRAPPER" "$MARK"

say "$(L 'Masaüstü girdileri ve simge kaldırılıyor' 'Removing the desktop entries and the icon')"
rm_marked "$APP_FILE" "$DESKTOP_MARK"
rm_marked "$SHOT_FILE" "$DESKTOP_MARK"
rm_marked "$AUTOSTART_FILE" "$DESKTOP_MARK"
if [[ -e "$ICON_FILE" ]]; then run rm -f "$ICON_FILE"; fi
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    run quiet kbuildsycoca6 --noincremental || true
fi

# runtime state (tmpfs): STOP switch, approval requests, one-way session copies
if [[ -d "$RUN_DIR" ]]; then run rm -rf "$RUN_DIR"; fi

if (( PURGE )); then
    say "$(L 'Ayarlar, günlükler, önbellek ve kayıtlı simge/akışlar siliniyor (--purge)' \
             'Deleting settings, logs, cache and saved icons/flows (--purge)')"
    for d in "$CFG_HOME/deskhand" "$STATE_HOME/deskhand" "$CACHE_HOME/deskhand" "$DATA_HOME/deskhand"; do
        if [[ -d "$d" ]]; then run rm -rf "$d"; fi
    done
else
    say "$(L "Korundu: $CFG_HOME/deskhand (ayarlar), $DATA_HOME/deskhand (simgeler, akışlar); tamamen silmek için --purge" \
             "Kept: $CFG_HOME/deskhand (settings), $DATA_HOME/deskhand (icons, flows); use --purge to delete them")"
fi

say "$(L 'Elle yapılacaklar (varsa):' 'To do by hand (if you set them up):')"
cat <<EOF
    claude mcp remove --scope user deskhand
    claude mcp remove --scope user deskhand-bg
    # $(L 'Panelde DUR kısayolunu açtıysan: Sistem Ayarları > Klavye > Kısayollar > Deskhand' \
          'If you enabled the STOP shortcut in the panel: System Settings > Keyboard > Shortcuts > Deskhand')
EOF
say "$(L 'Kaldırıldı. Kaynak kod ve kurulu paketler yerinde duruyor.' 'Removed. The source code and installed packages are left in place.')"
