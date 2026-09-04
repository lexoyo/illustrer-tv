# illustrer-tv — les tests

Ce que je mesure, pourquoi, et ce que ça ne mesure pas. Complète `PLAN.md`, qui
dit ce qu'on construit. Méthode héritée de `microturn/bench/BOUCLE.md`.

## QC du dispositif, faite AVANT de mesurer

La règle : *si ce que je m'apprête à mesurer était entièrement faux, est-ce que
je m'en apercevrais ?* Quatre réponses, et deux ont déjà changé le plan.

**1. Le piège de l'agrégat — il est ici, exactement comme dans microturn.**
Le jeu ci-dessous compte 10 « non » pour 6 « oui ». Un décideur qui répondrait
**toujours non** obtiendrait donc 10/16, soit 0,63 : un chiffre d'apparence
honnête pour un système parfaitement inutile. Conséquence tenue partout :
**jamais de score agrégé, les deux taux séparés, toujours.** Et deux témoins
mesurés en même temps que les modèles, pour situer les bornes : *toujours non*
(0 faux positif, 6 faux négatifs) et *toujours oui* (10 faux positifs).

**2. Le pouvoir de résolution est faible et il faut le dire.**
16 cas : un cas vaut 6 points. Aucun écart d'un seul cas ne conclut quoi que ce
soit. Pour trancher du réglage fin (bloc D), le jeu devra monter à ~40 cas.

**3. Ce que le prompt rend faux ailleurs.** Le prompt suppose un texte
**ponctué** — c'est vrai de whisper, faux d'un ASR en flux. Si le moteur change
un jour, cette hypothèse devient un mensonge, et dans microturn le même mensonge
a coûté 0,103 de justesse. À réécrire en même temps que le moteur, jamais après.

**4. Ce sur quoi je me repose sans l'avoir mesuré — et c'est le vrai risque du
projet.** Tout suppose que **whisper `tiny` rend un texte exploitable sur une
conversation de salon**, à deux ou trois mètres, captée par le micro d'une
webcam dont le gain n'est pas réglable. Si ce texte est de la bouillie, le
décideur, le prompt et le style ne servent à rien. D'où le test 0, qui passe
avant tout le reste.

## Test 0 — la transcription tient-elle debout ? (bloquant)

Le seul test dont l'échec arrête le projet. Sur le Pi, avec le vrai micro :

1. 45 s de conversation normale à ~2 m, deux personnes, sans articuler pour la
   machine.
2. Transcrire, **lire le texte**, et le comparer à ce qui a été dit.
3. Rejouer le même WAV avec `base` q5 pour situer ce que `tiny` coûte.

Critère : les **noms propres et les noms concrets** doivent survivre. C'est tout
ce dont le décideur a besoin — la grammaire et la ponctuation peuvent être
approximatives. Si « éléphant » devient « et le femme », rien de ce qui suit ne
peut fonctionner.
⚠️ Ce test demande la voix d'Alex : c'est un **blocage**, pas de la validation
courante. Je ne peux pas le faire seul.

## Tests de fumée (avant chaque mesure)

Rapides, et ils attrapent la panne qui ressemble à un mauvais résultat :

- le micro est détecté **par son nom** (l'index ALSA a déjà changé de 1 à 2) ;
- `arecord` produit un WAV non vide, 16 kHz mono ;
- whisper charge et rend du texte sur un WAV de référence ;
- le décideur rend un **JSON valide** sur un cas trivial ;
- Commons répond et l'image se télécharge ;
- `fb0` n'est pas en veille (`blank` valait 4 au premier essai, et l'écran
  restait noir sans le moindre message d'erreur) ;
- une trame écrite se relit à l'identique (`probe`).

## Le jeu de cas — décision

Écrit à la main, façon whisper : ponctué, avec parfois un mot faux. La majorité
attendue est **non** : c'est la réalité d'une conversation.

| # | Transcription | Attendu | Ce que le cas teste |
|---|---|---|---|
| 1 | « Tu peux passer prendre le pain ? Ah non c'est fait, il est sur la table. » | non | logistique |
| 2 | « Franchement je trouve ça n'importe quoi, ils exagèrent complètement. » | non | opinion |
| 3 | « Je suis crevé, j'ai pas dormi cette nuit. » | non | état, pas sujet |
| 4 | « enfin bon voilà quoi je sais pas si tu ouais non mais c'est ça » | non | **texte abîmé** |
| 5 | « Il faut qu'on rappelle les balances demain matin. » | non | **mot faux de whisper** (banques) |
| 6 | « Non mais t'as vu sa tête quand il a dit ça ! » | non | blague |
| 7 | « Attends, ça écoute là ? Il affiche un truc sur la télé. » | non | **on parle du système lui-même** |
| 8 | « C'est une question de justice sociale, pas d'argent. » | non | abstrait |
| 9 | « Oui l'éléphant il était vraiment énorme. » *(déjà affiché : éléphant Afrique)* | non | **anti-répétition** |
| 10 | « On part à quelle heure ? Sept heures et demie sinon on rate le train. » | non | chiffres |
| 11 | « Tu savais que la tour Eiffel devait être démontée après vingt ans ? » | **oui** | monument |
| 12 | « Les éléphants d'Asie ont les oreilles bien plus petites que ceux d'Afrique. » | **oui** | animal, comparaison |
| 13 | « Elle fait un couscous royal incroyable, avec la merguez et tout. » | **oui** | plat |
| 14 | « C'est le tableau avec la vague, là, de Hokusai. » | **oui** | œuvre |
| 15 | « On a vu des aurores boréales en Norvège, en février. » | **oui** | phénomène + lieu |
| 16 | « Les éléphants en captivité c'est d'une tristesse absolue, ils deviennent fous. » | **oui** | **sujet + ton sombre** (bloc B) |

Le cas 16 est celui qui porte la demande d'Alex : même sujet que le 12, ton
opposé. Une requête identique sur les deux cas est un échec du bloc B, même si
la décision est bonne.

Le jeu machine (celui qu'exécute le banc) doit rester **le même fichier** que
ce tableau décrit, sinon les deux divergent en trois itérations.

## Les métriques, et l'ordre dans lequel elles comptent

| Métrique | Pourquoi c'est celle-là |
|---|---|
| **Faux positifs** (oui alors que non) | **Le chiffre qui décide.** Une image sans rapport toutes les 45 s rend le produit insupportable ; un silence, non |
| Faux négatifs (non alors que oui) | Le système est terne, mais utilisable |
| JSON valide | En dessous de 100 %, c'est la grammaire GBNF qu'il faut, pas un meilleur prompt |
| Pertinence de la requête | **Jugement, pas métrique** : lue à l'œil, cas par cas |
| Latence du décideur, durée du cycle | Décide la part de conversation qu'on rate |
| Température, `get_throttled` | Le Pi bride à 80 °C. Toute mesure démarre sous 60 °C |

## Ce que ces tests ne mesurent pas — à répéter dans chaque verdict

- **La pertinence des images réellement affichées.** Il n'y a aucune annotation
  réelle : la boucle s'optimise contre des exemples inventés (cf. `PLAN.md`, « le
  trou connu »).
- **Le ton perçu.** Personne ne peut dire à ma place si une photo virée au
  clair-obscur « fait éléphant triste ». C'est le jugement d'Alex sur son écran.
- **La tenue dans la durée** : rien ne dit ce que fait le système après deux
  heures d'écoute continue (chaleur, fuites mémoire, dérive de l'anti-répétition).
