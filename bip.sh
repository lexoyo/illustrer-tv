#!/bin/bash
# Notifications sonores pour les tests d'écoute : Alex ne voit pas le terminal
# depuis le canapé, donc c'est le son qui pilote le protocole.
case "$1" in
  parle) play -qn synth 0.15 sine 1200 vol 0.5 2>/dev/null
         sleep 0.12
         play -qn synth 0.15 sine 1200 vol 0.5 2>/dev/null ;;
  stop)  play -qn synth 0.5 sine 350 vol 0.5 2>/dev/null ;;
esac
