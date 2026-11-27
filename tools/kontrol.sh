#!/bin/bash
# Deskhand quality gate (pre-commit hook via lefthook.yml, and CI).
# Usage: tools/kontrol.sh [file…]     no arguments: the whole tree; with arguments: only those files
#        tools/kontrol.sh --taban-uret  scan the whole tree, print baseline lines ("file:code") to stdout
# Checks: shellcheck -S warning · ruff (pyproject.toml [tool.ruff]) · gitleaks
# BASELINE: ruff-taban.txt ($KONTROL_TABAN overrides). A finding in the baseline does not block; a new one does.
# Counting is per file and code: N findings of one code in one file = N baseline lines; more than that is new.
# The test suites are NOT run here (they are standalone scripts; see tests/ci_kos.sh).
# Last output line: KONTROL GEÇTİ  or  KONTROL KALDI: <summary>   (machine-read words, not translated)
set -u
# C locale: under tr_TR the regex range [A-Za-z] does not match "I", which silently dropped every
# SIM/PIE… ruff code; sort/comm also need one fixed collation for the baseline comparison.
export LC_ALL=C
CAGRI_DIZINI=$PWD
KOK=$(cd "$(dirname "$(realpath "$0")")/.." && pwd) || exit 2
cd "$KOK" || exit 2
TABAN=${KONTROL_TABAN:-$KOK/ruff-taban.txt}
[ -n "${KONTROL_TABAN:-}" ] && case "$TABAN" in /*) ;; *) TABAN=$CAGRI_DIZINI/$TABAN ;; esac
uret=0
if [ "${1:-}" = "--taban-uret" ]; then uret=1; shift; fi

tmp=$(mktemp -d) || exit 2
trap 'rm -rf "$tmp"' EXIT

if [ $# -gt 0 ] && [ $uret -eq 0 ]; then
  # arguments are relative to the caller's directory; turn them into repository-relative paths (baseline keys)
  dosyalar=(); yok=()
  for a in "$@"; do
    case "$a" in /*) tam_yol=$a ;; *) tam_yol=$CAGRI_DIZINI/$a ;; esac
    if [ ! -f "$tam_yol" ]; then yok+=("$a"); continue; fi
    tam_yol=$(realpath -m "$tam_yol")
    case "$tam_yol" in "$KOK"/*) dosyalar+=("${tam_yol#"$KOK"/}") ;; *) dosyalar+=("$tam_yol") ;; esac
  done
else
  yok=()
  if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    mapfile -d '' -t dosyalar < <(git ls-files -z --cached --others --exclude-standard)
  else
    mapfile -d '' -t dosyalar < <(find . -type f -not -path './.git/*' -not -path '*/__pycache__/*' -not -path './.*_cache/*' \
      -not -path '*/.venv/*' -printf '%P\0')
  fi
fi

sh_list=(); py_list=()
for f in "${dosyalar[@]}"; do
  [ -f "$f" ] || continue
  # not lint targets: other agents' worktrees, Serena cache, sample data
  case "$f" in
    .claude/* | .serena/* | .venv/* | *.ornek) continue ;;
  esac
  bas=$(head -c 200 "$f" 2>/dev/null | head -1)
  case "$bas" in
    '#!'*python*) py_list+=("$f") ;;
    '#!'*bash* | '#!'*/sh | '#!'*/sh' '* | '#!'*' sh' | '#!'*' sh '*) sh_list+=("$f") ;;
    '#!'*) ;;   # other interpreters: not scanned
    *) case "$f" in *.py) py_list+=("$f") ;; *.sh) sh_list+=("$f") ;; esac ;;
  esac
done

: > "$tmp/bulgu.txt"     # file:code
: > "$tmp/ayrinti.txt"   # file:code TAB line: code message
hata_arac=""

if [ ${#sh_list[@]} -gt 0 ]; then
  if ! command -v shellcheck > /dev/null 2>&1; then
    hata_arac="$hata_arac shellcheck-yok"
  else
    shellcheck -S warning -f gcc "${sh_list[@]}" > "$tmp/sc.txt" 2>&1
    rc=$?
    [ $rc -gt 1 ] && hata_arac="$hata_arac shellcheck-çöktü"
    # gcc format: file:line:col: level: message [SCxxxx]
    sed -nE 's/^(.*):[0-9]+:[0-9]+: (warning|error|note|style): .*\[(SC[0-9]+)\]$/\1:\3/p' "$tmp/sc.txt" >> "$tmp/bulgu.txt"
    sed -nE 's/^(.*):([0-9]+):[0-9]+: (warning|error|note|style): (.*) \[(SC[0-9]+)\]$/\1:\5\t\2: \5 \4/p' "$tmp/sc.txt" >> "$tmp/ayrinti.txt"
    # unparseable output (e.g. a parse error) must not pass silently
    if [ $rc -ne 0 ] && ! grep -qE '\[SC[0-9]+\]$' "$tmp/sc.txt"; then hata_arac="$hata_arac shellcheck-çıktı-okunamadı"; fi
  fi
fi

if [ ${#py_list[@]} -gt 0 ]; then
  if ! command -v ruff > /dev/null 2>&1; then
    hata_arac="$hata_arac ruff-yok"
  else
    # --force-exclude: extend-exclude also applies to explicitly named files
    ruff check --no-cache --force-exclude --config "$KOK/pyproject.toml" --output-format concise "${py_list[@]}" > "$tmp/ruff.txt" 2>&1
    rc=$?
    [ $rc -gt 1 ] && hata_arac="$hata_arac ruff-çöktü"
    # concise: file:line:col: CODE message  (syntax error: "…: invalid-syntax: …")
    sed -nE 's/^(.*):[0-9]+:[0-9]+: (\[\*\] )?([A-Za-z]+[0-9]+|invalid-syntax):? .*/\1:\3/p' "$tmp/ruff.txt" >> "$tmp/bulgu.txt"
    sed -nE 's/^(.*):([0-9]+):[0-9]+: (\[\*\] )?([A-Za-z]+[0-9]+|invalid-syntax):? (.*)/\1:\4\t\2: \4 \5/p' "$tmp/ruff.txt" >> "$tmp/ayrinti.txt"
    if [ $rc -ne 0 ] && ! grep -qE ':[0-9]+:[0-9]+: ' "$tmp/ruff.txt"; then hata_arac="$hata_arac ruff-çıktı-okunamadı"; fi
  fi
fi

sort "$tmp/bulgu.txt" -o "$tmp/bulgu.txt"

if [ $uret -eq 1 ]; then
  cat "$tmp/bulgu.txt"
  [ -z "$hata_arac" ] && exit 0
  echo "taban-uret:$hata_arac" >&2; exit 1
fi

# baseline: drop comment/blank lines
if [ -f "$TABAN" ]; then
  grep -vE '^[[:space:]]*(#|$)' "$TABAN" | sort > "$tmp/taban.txt"
else
  : > "$tmp/taban.txt"
fi
comm -23 "$tmp/bulgu.txt" "$tmp/taban.txt" > "$tmp/yeni.txt"
n_yeni=$(wc -l < "$tmp/yeni.txt")
n_taban=$(comm -12 "$tmp/bulgu.txt" "$tmp/taban.txt" | wc -l)

ozet=()
if [ "$n_yeni" -gt 0 ]; then
  echo "YENİ bulgular (tabanda yok / not in the baseline):"
  while IFS= read -r satir; do
    awk -F'\t' -v k="$satir" -v d="${satir%:*}" '$1 == k { print "  " d ":" $2 }' "$tmp/ayrinti.txt"
  done < <(sort -u "$tmp/yeni.txt")
  ozet+=("$n_yeni yeni shellcheck/ruff bulgusu")
fi
[ -n "$hata_arac" ] && ozet+=("araç hatası:${hata_arac}")
if [ ${#yok[@]} -gt 0 ]; then
  echo "dosya bulunamadı: ${yok[*]}"
  ozet+=("dosya bulunamadı: ${yok[*]}")
fi
[ "$n_taban" -gt 0 ] && echo "bilgi: $n_taban eski bulgu tabanda (engellemez)"

if ! command -v gitleaks > /dev/null 2>&1; then
  ozet+=("gitleaks yok")
else
  gitleaks dir --no-banner --redact --exit-code 2 . > /dev/null 2>&1
  rc=$?
  if [ $rc -eq 2 ]; then
    echo "gitleaks: olası sır bulundu → gitleaks dir --redact ."
    ozet+=("gitleaks: olası sır")
  elif [ $rc -ne 0 ]; then
    ozet+=("gitleaks araç hatası (çıkış $rc)")
  fi
fi

if [ ${#ozet[@]} -eq 0 ]; then
  echo "KONTROL GEÇTİ"
  exit 0
fi
sirali=$(printf '%s; ' "${ozet[@]}")
echo "KONTROL KALDI: ${sirali%; }"
exit 1
