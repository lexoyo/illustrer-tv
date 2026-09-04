#!/usr/bin/env bash
# Un cycle complet, REJOUABLE, sur le Pi : parole → whisper → décideur local →
# image → télé. À lancer SUR le Pi, depuis ~/illustrer-tv.
#
#   sudo ./console.sh          # une fois, pour rallumer l'écran
#   ./bout-en-bout.sh
#
# La parole est SYNTHÉTISÉE (piper, voix fr, déjà sur la machine) au lieu d'être
# dite dans la pièce. Deux raisons : une mesure doit pouvoir être refaite à
# l'identique, et personne n'a besoin d'être là. Ce que ça ne mesure pas : le
# micro, la réverbération de la pièce, et la dégradation de whisper sur une
# vraie voix à trois mètres — le RTF, lui, ne change pas.
set -euo pipefail
cd "$(dirname "$0")"
PIPER=~/bench/piper/piper/piper
VOIX=~/bench/piper/fr.onnx
OUT=/tmp/bout-en-bout
mkdir -p "$OUT"

TEXTE="Bon alors, du coup, la semaine dernière on est partis à Rome avec Julie. \
On avait réservé un petit appartement pas très loin du centre. Et le deuxième \
jour on est allés voir le Colisée. Franchement, je m'attendais pas à ça. C'est \
absolument immense en vrai, les arcades sur trois étages, la pierre toute jaune \
au soleil. On a fait la queue une heure et demie mais ça valait vraiment le \
détour. Après on a mangé une pizza dans une petite rue à côté, et le soir on \
est rentrés à pied."

if [ ! -f "$OUT/parole16k.wav" ]; then
  echo "→ synthèse piper…"
  printf '%s\n' "$TEXTE" | LD_LIBRARY_PATH=~/bench/piper/piper \
    "$PIPER" --model "$VOIX" --output_file "$OUT/parole.wav" 2>/dev/null
  # whisper.cpp veut du 16 kHz mono ; piper sort en 22,05 kHz.
  ffmpeg -y -loglevel error -i "$OUT/parole.wav" -ar 16000 -ac 1 "$OUT/parole16k.wav"
fi
/usr/bin/python3 - "$OUT/parole16k.wav" <<'PYEOF'
import sys, wave
w = wave.open(sys.argv[1])
print(f"  parole : {w.getnframes()/w.getframerate():.1f} s, "
      f"{w.getframerate()} Hz, {w.getnchannels()} canal")
PYEOF

echo "temp av.: $(/usr/bin/vcgencmd measure_temp)"
T0=$(date +%s%N)
./.venv/bin/python ecouter.py --une-fois --wav "$OUT/parole16k.wav" \
  --decideur local --trace "$OUT/trace" "$@"
T1=$(date +%s%N)
awk -v a="$T0" -v b="$T1" 'BEGIN{printf "cycle complet (hors 45 s de micro) : %.1f s\n", (b-a)/1e9}'
echo "temp ap.: $(/usr/bin/vcgencmd measure_temp) · $(/usr/bin/vcgencmd get_throttled)"
echo "→ preuve à l'écran : ./grab.py $OUT/ecran.png"
