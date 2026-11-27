#!/bin/bash
# Deskhand canlıya alma (yalnız yerel kurulum): ileri sarma + C yardımcıları + gerekirse install.sh + panel yeniden
# başlatma + duman testi. Kullanım: tools/canliya_al.sh HEDEF_DAL [--kuru]
#   --kuru : yalnız denetimler; hiçbir şey değiştirilmez, panele dokunulmaz.
set -uo pipefail
DEPO="$HOME/.local/src/deskhand"
HEDEF_DAL="${1:?kullanım: canliya_al.sh HEDEF_DAL [--kuru]}"
KURU=0; [[ "${2:-}" == "--kuru" ]] && KURU=1
DH="$HOME/.local/bin/deskhand"
HELPER="$DEPO/deskhand/yardimci"
PANEL_RE="^/usr/bin/python3 ($HOME/.local/bin|$HOME/.local/src/deskhand/bin)/deskhand panel"
ESKI_SURUM="?"; ESKI_UC="?"; YEDEK_TAR=""

adim() { echo; echo "=== [$(date +%H:%M:%S)] $* $( ((KURU)) && echo '(KURU)')==="; }
yap()  { if ((KURU)); then printf '[kuru] %s\n' "$*"; else printf '+ %s\n' "$*"; "$@"; fi; }
geri_alma_metni() {
cat <<TXT

--- GERİ ALMA (yalnız metin; kullanıcı onayıyla elle yapılır) ---
1) Paneli kapat:          kill \$(pgrep -f '$PANEL_RE')   (pkill -f kullanma)
2) Kodu eski sürüme al:   git -C $DEPO reset --hard yedek-$ESKI_SURUM   (main eski ucu = $ESKI_UC)
3) Yardımcıları derle:    make -C $HELPER
4) Paneli aç:             setsid -f $DH panel --tepsi >/dev/null 2>&1
5) Ayar/durum yedeği:     tar -xzf ${YEDEK_TAR:-<yedek>} -C \$HOME   (önce mevcutları ayrı yere kopyala)
TXT
}
dur() { echo "DUR: $*"; geri_alma_metni; exit 1; }

cd "$DEPO" || exit 1
echo "Deskhand canlıya alma | hedef=$HEDEF_DAL | kuru=$KURU | $(date '+%F %T')"

adim "1) Ön denetim"
[[ "$(git rev-parse --abbrev-ref HEAD)" == "main" ]] || dur "ana çalışma ağacı main'de değil"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || dur "ana çalışma ağacında commit'lenmemiş değişiklik var"
git rev-parse --verify -q "$HEDEF_DAL" >/dev/null || dur "dal yok: $HEDEF_DAL"
git merge-base --is-ancestor main "$HEDEF_DAL" || dur "main, $HEDEF_DAL'ın atası değil (ileri sarılamaz)"
echo "ileri sarılabilir: main $(git rev-parse --short main) -> $HEDEF_DAL $(git rev-parse --short "$HEDEF_DAL") ($(git rev-list --count main.."$HEDEF_DAL") commit)"
MESGUL="$("$DH" busy 2>/dev/null | sed -n 1p)"; echo "$MESGUL"
# panel yeniden başlatma kullanıcının ekranına dokunur (tepsi, bildirim): oyun/film/tam ekranda KURMA
if [[ $MESGUL == *"meşgul: evet"* && ${ZORLA:-0} != 1 ]]; then
    ((KURU)) && echo "UYARI: kullanıcı meşgul — gerçek kurulum duracak (ZORLA=1 ile geçilebilir)" || dur "kullanıcı meşgul ($MESGUL): kurulum ertelendi"
fi
pkg-config --exists libei-1.0 xkbcommon libsystemd || dur "deskhand-eis için libei/xkbcommon/libsystemd geliştirme dosyaları eksik"
ESKI_SURUM="$(git show main:deskhand/__init__.py | sed -n 's/^__version__ = "\(.*\)"/\1/p')"
YENI_SURUM="$(git show "$HEDEF_DAL":deskhand/__init__.py | sed -n 's/^__version__ = "\(.*\)"/\1/p')"
ESKI_UC="$(git rev-parse --short main)"
echo "sürüm: $ESKI_SURUM -> $YENI_SURUM"
mapfile -t PIDS < <(pgrep -f "$PANEL_RE" || true)
((${#PIDS[@]} <= 1)) || dur "en çok bir panel süreci bekleniyordu: ${PIDS[*]}"
ESKI_PID="${PIDS[0]:-}"
[[ -n $ESKI_PID ]] && echo "eski panel PID: $ESKI_PID" || echo "panel çalışmıyor: kurulumdan sonra açılacak"
# install.sh gerekli mi: birleştirmeden ÖNCE hesapla
DEG="$(git diff --name-only main "$HEDEF_DAL" -- install.sh bin/ deskhand/data/ '*.desktop' 2>/dev/null)"

adim "2) Yedek"
YEDEK_TAR="$HOME/.local/share/deskhand/yedek-$(date +%Y%m%d-%H%M%S).tar.gz"
yap git branch -f "yedek-$ESKI_SURUM" main
if ((KURU)); then echo "[kuru] tar -czf $YEDEK_TAR .config/deskhand .local/state/deskhand"
else mkdir -p "$(dirname "$YEDEK_TAR")"; tar -czf "$YEDEK_TAR" -C "$HOME" .config/deskhand .local/state/deskhand 2>/dev/null; ls -la "$YEDEK_TAR"; fi

adim "3) İleri sarma"
yap git merge --ff-only -q "$HEDEF_DAL"

adim "4) C yardımcıları"
yap make -s -C "$HELPER"

adim "5) install.sh gerekli mi?"
if [[ -n "$DEG" ]]; then echo "değişen kurulum dosyaları:"; echo "$DEG" | sed 's/^/  /'; yap bash "$DEPO/install.sh"
else echo "gerekmiyor"; fi

adim "6) Panel yeniden başlatma"
if ((KURU)); then echo "[kuru] kill ${ESKI_PID:-yok}; setsid -f $DH panel --tepsi"
else
    if [[ -n $ESKI_PID ]]; then
        kill "$ESKI_PID"
        for _ in $(seq 10); do kill -0 "$ESKI_PID" 2>/dev/null || break; sleep 0.5; done
        kill -0 "$ESKI_PID" 2>/dev/null && dur "eski panel 5 sn içinde kapanmadı (SIGKILL atılmadı)"
        echo "eski panel kapandı"
    fi
    setsid -f "$DH" panel --tepsi >/dev/null 2>&1
    sleep 3
    mapfile -t YP < <(pgrep -f "$PANEL_RE" || true)
    ((${#YP[@]} == 1)) || dur "yeni panel bulunamadı / birden fazla: ${YP[*]:-yok}"
    echo "yeni panel PID: ${YP[0]}"
fi

adim "7) Duman testi"
if ((KURU)); then echo "[kuru] version, doctor, mcp tools/list"
else
    "$DH" --version
    "$DH" doctor 2>&1 | grep -E "Sürüm|Onay kapsamı|Hesap oturum|Dinleme|✗" | head -8
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"duman","version":"1"}}}' \
        '{"jsonrpc":"2.0","method":"notifications/initialized"}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
      | timeout 15 "$DH" mcp --desktop background 2>/dev/null \
      | python3 -c "import sys,json
for l in sys.stdin:
    try: m=json.loads(l)
    except Exception: continue
    if m.get('id')==1: print('MCP sunucu:', m['result'].get('serverInfo'))
    if m.get('id')==2: print('MCP araç sayısı:', len(m['result']['tools']))"
fi

adim "Bitti"
((KURU)) && echo "KURU ÇALIŞTIRMA TAMAM: hiçbir şey değiştirilmedi."
geri_alma_metni
