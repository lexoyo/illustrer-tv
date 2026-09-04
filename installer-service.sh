#!/bin/bash
# Installe l'app en service qui démarre au boot. À lancer sur le Pi, avec sudo.
set -e
[ "$EUID" = 0 ] || { echo "à lancer avec sudo"; exit 1; }
D=$(cd "$(dirname "$0")" && pwd)

install -m 644 "$D/illustrer-tv.service" /etc/systemd/system/illustrer-tv.service
systemctl daemon-reload
systemctl enable illustrer-tv.service
echo "service installé et activé au démarrage."
echo
echo "  démarrer   : sudo systemctl start illustrer-tv"
echo "  arrêter    : sudo systemctl stop illustrer-tv"
echo "  suivre     : journalctl -u illustrer-tv -f"
echo "  au boot ?  : systemctl is-enabled illustrer-tv"
echo
echo "⚠️  le journal de cette machine n'est pas persistant"
echo "    (/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf)"
echo "    donc les logs d'avant le dernier redémarrage sont perdus."
