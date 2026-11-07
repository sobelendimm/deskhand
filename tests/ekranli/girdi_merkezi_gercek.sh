#!/bin/bash
# Girdi merkezi (panel açıkken) gerçek ekran ölçümü + güvenlik: ./girdi_merkezi_gercek.sh [guvenlik]
# Gerçek ekranı kullanır: bilgisayar boştayken çalıştırın. Ortalama komut süreleri + SIGKILL/DUR bırakma denetimi.
S=$(mktemp -d)
K=$(cd "$(dirname "$0")/../.." && pwd); D="$K/bin/deskhand"; T="$K/tests/ekranli/test_pencere.py"
EV=$S/hiz-ev.log; : > $EV
BASLIK="deskhand-hiz-test" LOG=$EV setsid python3 $T >/dev/null 2>&1 & PP=$!
for i in $(seq 1 40); do W=$($D windows deskhand-hiz-test 2>/dev/null | head -1 | cut -d' ' -f1); [ -n "$W" ] && break; sleep 0.25; done
echo "pencere $W"; sleep 1
olc() { local ad=$1; shift; local top=0; for i in 1 2 3 4 5; do t0=$(date +%s%N); "$@" >/dev/null 2>&1; k=$?; t1=$(date +%s%N); top=$((top + (t1-t0)/1000000)); done; echo "$ad: ort $((top/5)) ms (son kod $k)"; }
olc "click-text Kaydet" $D -b deskhand-hiz-test click-text "$W" Kaydet
olc "key a" $D -b deskhand-hiz-test key "$W" a
olc "click (koordinat)" $D -b deskhand-hiz-test click "$W" 30 30
echo "olaylar: $(grep -c 'tık: Kaydet' $EV) tık"
if [ "$1" = "guvenlik" ]; then
  $D -b deskhand-hiz-test click-text "$W" "OYUN ALANI" >/dev/null 2>&1
  $D -b deskhand-hiz-test hold "$W" w 4 >/dev/null 2>&1 & HP=$!; sleep 1.2; kill -9 $HP; sleep 0.6
  echo "SIGKILL testi: bas=$(grep -c 'tus_bas w' $EV) bırak=$(grep -c 'tus_birak w' $EV)"
  $D -b deskhand-hiz-test drag "$W" 300 470 500 520 --duration 3 >/dev/null 2>&1 & DP=$!; sleep 1.0; $D stop >/dev/null 2>&1; wait $DP; echo "DUR testi: sürükleme kodu $? | fare_bas=$(grep -c 'fare_bas sol' $EV) fare_birak=$(grep -c 'fare_birak sol' $EV)"; $D resume >/dev/null 2>&1
fi
kill $PP 2>/dev/null; wait $PP 2>/dev/null
