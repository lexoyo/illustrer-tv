#!/usr/bin/env bash
# Prépare la console texte pour qu'elle n'efface pas l'image. NÉCESSITE sudo.
#   sudo ./console.sh          # préparer
#   sudo ./console.sh --undo   # remettre comme avant
#
# Trois choses gênent l'affichage sur un Pi Lite sans serveur graphique :
#   1. /sys/class/graphics/fb0/blank vaut souvent 4 (écran éteint). L'écriture
#      dans /dev/fb0 « réussit » alors sans que rien n'apparaisse. C'est LE
#      piège n°1 : tout semble marcher et l'écran reste noir.
#   2. le curseur clignotant de la console repeint un rectangle par-dessus.
#   3. le blanking/DPMS de la console éteint l'écran au bout de N minutes.
#
# Rien de tout ceci n'est persistant : un reboot annule les trois.
set -u
[ "$(id -u)" -eq 0 ] || { echo "à lancer avec sudo" >&2; exit 1; }
TTY=/dev/tty1

if [ "${1:-}" = "--undo" ]; then
  printf '\033[?25h' > "$TTY"                # curseur : réafficher
  setterm --blank 10 --powerdown 10 > "$TTY" # blanking : valeurs Linux par défaut
  echo "console rendue à son état par défaut (le curseur revient, blanking 10 min)"
  exit 0
fi

echo 0 > /sys/class/graphics/fb0/blank      # 1. rallumer   (défaire : echo 4 > ...)
printf '\033[?25l' > "$TTY"                 # 2. curseur    (défaire : \033[?25h)
setterm --blank 0 --powerdown 0 > "$TTY"    # 3. blanking   (défaire : --blank 10)
echo "blank = $(cat /sys/class/graphics/fb0/blank)  (0 = écran allumé)"
echo "console prête. Rien n'est persistant : un reboot remet tout par défaut."
