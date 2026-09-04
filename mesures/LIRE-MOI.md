# Sorties brutes du banc du décideur — 04/09/2026

Rapatriées de `/tmp` sur `raspi2` (elles n'y survivraient pas à un reboot).
Analyse et conclusions : `../MESURES-DECIDEUR.md`.

| fichier | ce que c'est |
|---|---|
| `res-135m.json` | `smollm2-135m-q4`, grammaire libre |
| `res-smollm2-360m-q4.json` | `smollm2-360m-q4`, grammaire libre — répond « non » 17 fois sur 17 |
| `res-qwen25-05b-q4.json` | `qwen25-05b-q4`, grammaire libre — **le modèle retenu** |
| `res-qwen-ancre.json` | `qwen25-05b-q4`, grammaire ancrée — écartée (serveur tombé au 15ᵉ cas) |
| `bench.log`, `run2.log` | les journaux des deux séries, avec les températures d'attente |

Chaque JSON porte le détail par cas dans `lignes` : décision attendue, décision
obtenue, requête produite, latence, température, et l'erreur éventuelle.
