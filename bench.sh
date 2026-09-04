#!/usr/bin/env bash
# Mesure « fichier image sur disque -> pixels à l'écran ».
# À lancer SUR le Pi :  ./bench.sh [image.jpg]
#
# Deux régimes, parce qu'ils diffèrent d'un facteur 3 sur un Pi 3B :
#   A) un process par image  -> inclut le démarrage de Python et les imports.
#   B) process déjà chaud    -> le seul chiffre pertinent pour un afficheur
#                               qui tourne en continu (le cas du projet).
# `bc` n'est pas installé sur cette machine : les moyennes sont faites en awk.
set -u
cd "$(dirname "$0")"
IMG="${1:-samples/photo.jpg}"
PY="./.venv/bin/python"
[ -x "$PY" ] || PY=python3
VCG=/usr/bin/vcgencmd

echo "image   : $IMG"
$PY - "$IMG" <<'PYEOF'
import os, sys
from PIL import Image
im = Image.open(sys.argv[1])
print(f"          {im.size[0]}x{im.size[1]} = {im.size[0]*im.size[1]/1e6:.2f} Mpx, "
      f"{os.path.getsize(sys.argv[1])/1024:.0f} kio, {im.format}")
PYEOF
echo "temp av.: $($VCG measure_temp 2>/dev/null || echo '?')"

field() { $PY -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }

for BACKEND in pillow ffmpeg; do
  echo
  echo "--- backend $BACKEND"

  # A) 3 process séparés, wall-clock mesuré de l'extérieur
  ACC=""
  for i in 1 2 3; do
    T0=$(date +%s%N)
    J=$($PY show.py --quiet --json --backend "$BACKEND" "$IMG" 2>/dev/null)
    T1=$(date +%s%N)
    [ -z "$J" ] && { echo "  ÉCHEC"; ACC=""; break; }
    WALL=$(awk -v a="$T0" -v b="$T1" 'BEGIN{printf "%.0f", (b-a)/1e6}')
    D2S=$(printf '%s' "$J" | field disk_to_screen_ms)
    echo "  A/passe $i : wall $WALL ms  (dont disque->écran $D2S ms)"
    ACC="$ACC$WALL\n"
  done
  [ -n "$ACC" ] && printf "$ACC" | awk 'NF{s+=$1;n++} END{if(n) printf "  A/MOYENNE  : %.0f ms  (un process par image, imports compris)\n", s/n}'

  # B) un seul process, 3 affichages
  J=$($PY show.py --quiet --json --repeat 3 --backend "$BACKEND" "$IMG" 2>/dev/null)
  if [ -n "$J" ]; then
    D2S=$(printf '%s' "$J" | field disk_to_screen_ms)
    DEC=$(printf '%s' "$J" | field decode_scale_ms)
    WR=$(printf '%s' "$J" | field write_fb_ms)
    ST=$(printf '%s' "$J" | field startup_ms)
    PL=$(printf '%s' "$J" | field preload_ms)
    echo "  B/MOYENNE  : $D2S ms/image (décode+scale $DEC + écriture fb $WR), process chaud"
    echo "               coût unique du process : démarrage $ST ms + imports $PL ms"
  fi
done

echo
echo "temp ap.: $($VCG measure_temp 2>/dev/null || echo '?')"
