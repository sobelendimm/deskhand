#!/usr/bin/env bash
# Deskhand ekranlı test takımlarının HEPSİ, tek komutla. GERÇEK ekrana pencere açar, tıklar, yazar:
# yalnız kullanıcı müsaitken çalıştırın (~15 dk bilgisayara dokunmayın; onay takımında iki kez fareyle
# düğmeye basmanız istenir, --insansiz ile atlanır).
#
#   tests/ekranli/hepsi.sh                 # hepsi
#   tests/ekranli/hepsi.sh --insansiz      # insan adımları atlanır (onay diyaloğunda 'Reddet' / 'Bir kez izin ver')
#   tests/ekranli/hepsi.sh qt web          # yalnız seçilen takımlar (adlar: qt oyun v32 web gercek yeni)
#   tests/ekranli/hepsi.sh --liste         # takımları ve tahmini süreleri göster, çalıştırma
#
# Her takım DESKHAND_* geçici klasörleri kullanır (tests/_yalitim.py); yine de her takımdan önce/sonra gerçek
# ~/.config/deskhand ve ~/.config/ekran sağlaması karşılaştırılır. Kullanıcı test sırasında klavye/fareye dokunursa
# Deskhand 12 (insan önceliği) ile durur: bu beklenmeyen 12'ler takım özetinde ayrıca gösterilir.
set -u

DIZIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KOK="$(cd "$DIZIN/../.." && pwd)"
PY="${PYTHON:-python3}"
GERI_SAYIM="${HEPSI_GERI_SAYIM:-10}"
TAKIM_SURESI="${HEPSI_TAKIM_SURESI:-900}"   # tek takım için üst sınır (sn); aşılırsa SIGINT (finally blokları çalışır)

# ad | dosya | tahmini süre (sn) | açıklama
TAKIMLAR=(
  "qt|testler.py|60|Qt test penceresi: OCR, tıklama, yazma, hassas düğme, yasak pencere, insan önceliği"
  "oyun|testler_oyun.py|60|oyun girdisi: hold/drag/move/batch, takılı tuş yok"
  "v32|testler_v32.py|120|open/ac, klavye insan önceliği, flow/akis, erişilebilirlik ağacı"
  "web|testler_web.py|70|ayrı Firefox örneği (geçici profil) + yerel test sayfası"
  "gercek|testler_gercek.py|200|ayrı Firefox: Vikipedi, DuckDuckGo, Kitapyurdu (ağ) + KDE masaüstü"
  "yeni|testler_yeni.py|300|ekran koruması (15), MPRIS, onay diyaloğu, tepsi/DUR, arka+ön plan"
)

INSANSIZ=0
SECILEN=()
for a in "$@"; do
  case "$a" in
    --insansiz) INSANSIZ=1 ;;
    --liste)
      for t in "${TAKIMLAR[@]}"; do IFS='|' read -r ad dosya sure acik <<<"$t"; printf "  %-7s %-20s ~%3s sn  %s\n" "$ad" "$dosya" "$sure" "$acik"; done
      exit 0 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "bilinmeyen seçenek: $a" >&2; exit 2 ;;
    *) SECILEN+=("$a") ;;
  esac
done

secili_mi() {
  [ "${#SECILEN[@]}" -eq 0 ] && return 0
  local s; for s in "${SECILEN[@]}"; do [ "$s" = "$1" ] && return 0; done
  return 1
}
for s in "${SECILEN[@]}"; do
  bulundu=0
  for t in "${TAKIMLAR[@]}"; do [ "${t%%|*}" = "$s" ] && bulundu=1; done
  [ "$bulundu" = 1 ] || { echo "bilinmeyen takım: $s (qt oyun v32 web gercek yeni)" >&2; exit 2; }
done

ayar_sagla() {
  # gerçek ayar klasörlerinin sağlaması (yoksa boş girdi; hata çıktısı bastırılır)
  find "$HOME/.config/deskhand" "$HOME/.config/ekran" -type f -exec sha1sum {} + 2>/dev/null | sort | sha1sum | cut -d' ' -f1
}

# ---------------------------------------------------------------- ön denetim (salt okuma)
eksik=()
for arac in kdotool dotool spectacle tesseract firefox Xvfb busctl; do
  command -v "$arac" >/dev/null 2>&1 || eksik+=("$arac")
done
"$PY" -c "import PyQt6, jeepney" 2>/dev/null || eksik+=("python: PyQt6/jeepney")
if [ "${#eksik[@]}" -gt 0 ]; then
  echo "UYARI: eksik araçlar: ${eksik[*]} (ilgili testler KALIR)" >&2
fi
if [ "${XDG_SESSION_TYPE:-}" != "wayland" ] || [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "HATA: KDE Plasma Wayland oturumunda çalıştırın (XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-?})." >&2
  exit 3
fi
# Çalan medya: ekran koruması, etkin pencerenin uygulaması MPRIS'te 'Playing' ise 15 verir (ör. kendi Firefox'unuzda
# video çalıyorsa test Firefox'u da 'firefox' sınıfındadır → web/gercek takımları 15 alır).
calan=()
while read -r ad; do
  [ -n "$ad" ] || continue
  d=$(busctl --user get-property "$ad" /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player PlaybackStatus 2>/dev/null | awk '{print $2}' | tr -d '"')
  [ "$d" = "Playing" ] && calan+=("${ad#org.mpris.MediaPlayer2.}")
done < <(busctl --user list --no-legend 2>/dev/null | awk '{print $1}' | grep '^org\.mpris\.MediaPlayer2\.')
if [ "${#calan[@]}" -gt 0 ]; then
  echo "UYARI: şu an medya çalıyor: ${calan[*]}. Lütfen durdurun (ör. YouTube'u duraklatın); yoksa aynı uygulamanın" >&2
  echo "       test penceresi 'video izliyor' sayılır ve testler 15 alır." >&2
fi

TOPLAM_TAHMIN=0
for t in "${TAKIMLAR[@]}"; do IFS='|' read -r ad dosya sure acik <<<"$t"; secili_mi "$ad" && TOPLAM_TAHMIN=$((TOPLAM_TAHMIN + sure)); done

cat <<EOF

=====================================================================================
  Deskhand EKRANLI TESTLER — yaklaşık $(( (TOPLAM_TAHMIN + 59) / 60 )) dk.
  Bu sürede KLAVYE ve FAREYE DOKUNMAYIN: testler ekranınızda pencere açıp tıklar/yazar.
  Dokunursanız Deskhand durur (insan önceliği, kod 12) ve o test kalır; zararı yok.
EOF
if [ "$INSANSIZ" = 0 ] && secili_mi yeni; then
cat <<EOF
  ELLE ADIM (yeni/onay): sarı şeritte ve burada "ŞİMDİ ... basın" yazınca 'Deskhand — Onay'
  penceresinde önce 'Reddet'e, sonra 'Bir kez izin ver'e FAREYLE basın ve fareyi bırakın.
  (İstemiyorsanız Ctrl+C ile çıkıp --insansiz ile yeniden başlatın.)
EOF
fi
cat <<EOF
  Kendi Firefox'unuza dokunulmaz: testler ayrı bir Firefox örneği (geçici profil) açar.
  İptal: Ctrl+C (açık test pencereleri kapatılır).
=====================================================================================
EOF
for ((i = GERI_SAYIM; i > 0; i--)); do printf "\r  başlıyor: %2d sn " "$i"; sleep 1; done
printf "\r  başladı.          \n"

GUNLUK_DIZIN="$(mktemp -d -t deskhand-hepsi-XXXXXX)"
OZET=()
GENEL=0
BASLANGIC=$(date +%s)
YARIDA=0
trap 'YARIDA=1' INT

for t in "${TAKIMLAR[@]}"; do
  IFS='|' read -r ad dosya sure acik <<<"$t"
  secili_mi "$ad" || continue
  [ "$YARIDA" = 1 ] && break
  echo
  echo "################ $ad ($dosya) — $acik"
  sagla_once=$(ayar_sagla)
  kod12="$GUNLUK_DIZIN/$ad.kod12"; : >"$kod12"
  log="$GUNLUK_DIZIN/$ad.log"
  ek=()
  [ "$ad" = yeni ] && [ "$INSANSIZ" = 1 ] && ek+=(--insansiz)
  t0=$(date +%s)
  ( cd "$KOK" && HEPSI_KOD12="$kod12" PYTHONUNBUFFERED=1 \
      timeout --signal=INT --kill-after=30 "$TAKIM_SURESI" "$PY" "$DIZIN/$dosya" "${ek[@]}" ) 2>&1 | tee -i "$log"   # tee -i: Ctrl+C çıktıyı kesmesin (test kapanışı görünsün)
  rc=${PIPESTATUS[0]}
  t1=$(date +%s)
  sagla_sonra=$(ayar_sagla)
  ozet_satir=$(grep -aE '^[0-9]+/[0-9]+ ' "$log" | tail -n1)
  gecen=$(sed -nE 's#^([0-9]+)/([0-9]+) .*#\1#p' <<<"$ozet_satir")
  toplam=$(sed -nE 's#^([0-9]+)/([0-9]+) .*#\2#p' <<<"$ozet_satir")
  notlar=()
  if [ -z "$gecen" ]; then
    gecen="?"; toplam="?"; notlar+=("özet yok (kod $rc)")
  fi
  [ "$rc" = 124 ] && notlar+=("ZAMAN AŞIMI (${TAKIM_SURESI} sn)")
  [ "$rc" = 130 ] && notlar+=("Ctrl+C ile kesildi")
  n12=$(grep -c . "$kod12" 2>/dev/null || true)
  if [ "${n12:-0}" -gt 0 ]; then
    notlar+=("İNSAN MÜDAHALESİ: $n12 komut 12 ile durdu (test sırasında klavye/fare kullanıldı?)")
  fi
  [ "$sagla_once" != "$sagla_sonra" ] && notlar+=("!!! GERÇEK AYARLAR DEĞİŞTİ (~/.config/deskhand|ekran)")
  [ "$rc" != 0 ] && GENEL=1
  [ "$sagla_once" != "$sagla_sonra" ] && GENEL=1
  nota=""; for n in "${notlar[@]}"; do nota="${nota:+$nota; }$n"; done
  OZET+=("$ad|$gecen/$toplam|$((t1 - t0))|$nota")
done
trap - INT

echo
echo "=================================== ÖZET ==================================="
printf "%-9s %-11s %-9s %s\n" "takım" "geçen" "süre" "not"  # çok baytlı harf: +1
printf "%-8s %-10s %-8s %s\n" "--------" "----------" "--------" "------------------------------"
for s in "${OZET[@]}"; do
  IFS='|' read -r ad sonuc sn nota <<<"$s"
  printf "%-8s %-10s %-8s %s\n" "$ad" "$sonuc" "${sn} sn" "$nota"
done
echo "toplam süre: $(( $(date +%s) - BASLANGIC )) sn; ayrıntılı çıktılar: $GUNLUK_DIZIN"
[ "$YARIDA" = 1 ] && echo "(Ctrl+C ile yarıda kesildi; kalan takımlar çalıştırılmadı)"
exit "$GENEL"
