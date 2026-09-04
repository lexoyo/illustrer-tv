# Le décideur en local sur le Pi — ce qui a été mesuré

> ⚠️ **Document historique depuis le 04/09/2026 au soir.** Tout ce que ce banc a
> construit — la consigne, les douze exemples, les huit catégories, la grammaire
> GBNF, le préfixe en cache — a été **supprimé**. Le décideur reçoit désormais la
> transcription du bloc et rien d'autre, et ce qu'il écrit part verbatim dans la
> recherche d'image ; il ne décide plus s'il faut illustrer. La raison est une
> soirée de six heures, 136 cycles et une seule image affichée : voir `JOURNAL.md`
> § « 17h30 », et l'en-tête de `decideur_local.py` pour les mesures d'après.
>
> Ce qui survit d'ici et qu'il ne faut pas défaire : `llama-server` plutôt qu'un
> process par bloc, le serveur lié à `127.0.0.1`, le contexte à 1024 tokens, et
> la règle « jamais un score agrégé, les deux classes séparées ». Le reste se lit
> comme le récit de ce qui a été essayé.


Question posée : le `decider()` du prototype appelle un modèle distant, et ce
qu'il lui envoie est la transcription d'une conversation privée. **Peut-on le
remplacer par un modèle qui tourne sur le Pi, sans rien perdre de la retenue ?**

Sorties brutes : `mesures/` (rapatriées du `/tmp` du Pi, qui ne survit pas à un
reboot). Code : `decideur_local.py`, jeu de test `cas.json`, banc
`bench_decideur.py`.

Machine : `raspi2`, Pi 3B, 4× Cortex-A53 @1,2 GHz, 905 Mio de RAM, pas de GPU,
Raspberry Pi OS Lite trixie arm64. `llama.cpp` build `b1-6fe7498` déjà présent
dans `~/lcpp`, modèles dans `~/bench/models`.

## Le jeu de test

`cas.json` — 17 blocs écrits à la main, façon whisper `tiny` en français :
ponctués, parfois un mot faux, parfois tronqués. **12 « non » pour 5 « oui »**,
volontairement : la qualité qui compte est la retenue, et un décideur qui dit
toujours non obtient déjà 12/17 = 0,71 sans rien comprendre. **Le chiffre qui
tranche est donc le nombre de FAUX POSITIFS** — chacun est une image sans
rapport qui s'affiche dans le salon.

Trois des « non » sont des pièges : un nom de gare cité en passant, un nom de
rue dans une course à faire, et le sujet déjà affiché à l'écran.

## Ce qui a fallu changer dans l'architecture, et pourquoi

### 1. Un serveur, pas un appel par bloc — facteur 5 à 8

La première mesure a réglé la question de la forme. `llama-cli`, un process par
décision, consigne complète à relire chaque fois :

| modèle | lecture du prompt | génération | un appel de bout en bout |
|---|---|---|---|
| smollm2-135m-q4 | 29,1 t/s | 8,3 t/s | **19,2 s** |
| smollm2-360m-q4 | 8,3 t/s | 3,7 t/s | **55,8 s** |

(mesure faite avec une consigne de ~340 tokens ; le 360m tournait déjà bridé,
la machine étant montée à 83,8 °C — voir le thermique plus bas.)

À 55 s par décision, le décideur coûte plus que les 45 s de micro qu'il commente.
La cause est unique : **sur un Cortex-A53, relire la consigne est le poste
principal**, pas la génération. Le remède est de ne la relire jamais.

`llama-server` conserve le cache KV du **préfixe commun** d'une requête à
l'autre (`cache_prompt: true`). La consigne et ses exemples sont lus une seule
fois, au démarrage ; un bloc ne paie plus que ses propres tokens :

| modèle | préfixe (une fois) | par bloc, médiane | max |
|---|---|---|---|
| smollm2-135m-q4 | 29,6 s | **3,9 s** | 7,0 s |
| qwen25-05b-q4 | 87,7 s | **10,5 s** | 17,6 s |

Le binaire `llama-server` n'existait pas sur la machine : il a été **lié** depuis
l'arbre `~/lcpp/build` déjà compilé (`cmake --build ~/lcpp/build --target
llama-server`) — seul `main.cpp` restait à compiler, tout le reste était déjà là.
Aucun paquet système installé.

**Corollaire de conception, à ne pas casser :** ce qui varie d'un bloc à l'autre
doit être en **fin** de prompt. Le sujet déjà affiché est donc placé après les
exemples. Le mettre dans la consigne invaliderait le cache à chaque changement
d'image, et rendrait un bloc sur trois aussi cher que le démarrage.

Le serveur n'écoute que sur `127.0.0.1`. Ce n'est pas une précaution de
principe : c'est la contrainte du projet.

### 2. Une grammaire GBNF, pas du JSON demandé poliment

Aucun de ces modèles ne tient un format de sortie sur consigne. `llama.cpp`
contraint la sortie par grammaire, et c'est le levier le plus rentable à cette
taille : le format devient **impossible à rater** (17/17 réponses exploitables
sur les trois modèles, 0 erreur de parsing) et surtout la génération tombe à
**1 token** pour un « non » — le cas courant — contre une trentaine pour un
objet JSON complet.

La sortie n'est donc pas du JSON mais `non` / `oui|<catégorie>|<requête>` ; le
dict du contrat est reconstruit en Python. La **catégorie est produite avant la
requête**, choisie dans une liste fermée de huit classes : le critère de retenue
devient une obligation de la grammaire au lieu d'une phrase de la consigne.

Deux détails qui ont coûté du temps :
- `--json-schema` en ligne de commande **échoue** sur ce build
  (`error initializing grammar sampler ... std::exception`) alors que la **même**
  grammaire passée par `--grammar-file` fonctionne. C'est un problème de
  passage d'argument, pas de grammaire.
- La grammaire doit autoriser l'**espace** avant la réponse (`root ::= " " …`).
  Les exemples du prompt s'écrivent `R: non`, et ` non` est un seul token là où
  `:`+`non` en fait deux : forcer la réponse collée aux deux points fait
  produire au modèle une forme qu'il n'a jamais vue.

### 3. La requête ancrée dans les mots du bloc — essayée, écartée

Le défaut le plus visible des petits modèles ici n'est pas la décision, c'est la
**requête** : ils recopient des morceaux de leurs propres exemples. Relevé tel
quel sur le banc, grammaire libre :

- `smollm2-135m` sur le couscous → requête `tarte Tatin avec elle-m`
  (« tarte Tatin » est un exemple du prompt) ;
- `qwen25-05b` sur une discussion de tarifs → `tarte Tatin auge deTarifs` ;
- `qwen25-05b` sur le Colisée → `Colisée Rome aube etnelle` (« aube » vient de
  l'exemple du Taj Mahal).

D'où l'idée : **reconstruire la grammaire à chaque bloc** pour n'autoriser dans
la requête que des mots **présents dans la transcription**
(`decideur_local.grammaire()`). L'hallucination devient improductible.

Ça a été implémenté et mesuré. **Ça ne tient pas** — voir « la variante ancrée »
plus bas : le serveur tombe, et la décision empire. L'option existe mais n'est
pas le défaut.

## Les trois modèles sur `cas.json`

`llama-server`, 4 threads, grammaire libre, `--temp 0`, chaque passe démarrée
sous 60 °C. Les latences sont **par bloc, cache du préfixe chaud**.

| modèle | RAM (RSS) | JSON exploitable | **faux positifs** /12 | faux négatifs /5 | requêtes justes /5 | justesse | latence méd. | max |
|---|---|---|---|---|---|---|---|---|
| smollm2-135m-q4 | ~180 Mio | 17/17 | **2** | 2 | 1 | 0,765 | 3,9 s | 7,0 s |
| smollm2-360m-q4 | ~330 Mio | 17/17 | **0** | 5 | 0 | 0,706 | 10,9 s | 14,3 s |
| **qwen25-05b-q4** | ~510 Mio | 17/17 | **2** | **0** | **5** | **0,882** | 10,5 s | 17,6 s |

**Le 0 de smollm2-360m est un piège, pas un résultat.** Il répond « non » aux
**dix-sept** cas. Sa justesse de 0,706 est exactement celle d'un `return False`,
et son taux de faux positifs celui d'un fil débranché. C'est le même travers que
`microturn` avait relevé sur les Llama 3.2 (JOURNAL, § comparaison des
décideurs) : sur un jeu déséquilibré, un modèle qui ne dit jamais la classe rare
obtient mécaniquement un bon score global. **C'est pourquoi les deux classes sont
comptées séparément ici.**

`smollm2-135m` décide au hasard : deux faux positifs, deux « oui » manqués, et
une seule requête sur cinq qui ressemble au sujet. Il est trois fois plus rapide,
et il ne sert à rien.

**`qwen25-05b-q4` est le seul des trois qui décide.** Il trouve les cinq sujets
illustrables, avec cinq requêtes reconnaissables, et il tient les trois pièges
(le nom de gare, le nom de rue, le sujet déjà affiché). Il reste **deux faux
positifs sur douze** : une blague sur un chat, et une discussion de tarifs.

### La variante ancrée : mesurée en entier, et écartée

Deuxième passe de `qwen25-05b-q4`, grammaire reconstruite à chaque bloc pour
n'autoriser que des mots du bloc (+ l'espace initial, + `ctx` 1024) :

| | grammaire libre | grammaire **ancrée** |
|---|---|---|
| faux positifs /12 | **2** | **3** |
| faux négatifs /5 | **0** | 3 |
| requêtes justes /5 | **5** | 1 |
| erreurs | 0 | **3** |
| justesse | **0,882** | 0,647 |
| latence médiane | 10,5 s | 10,1 s |

**L'ancrage a été écarté, et c'est la mesure qui l'a écarté.** Trois choses, dans
l'ordre de gravité :

1. **Il fait tomber le serveur.** Au bloc `o03-couscous`, `llama-server` a rendu
   l'âme (`Remote end closed connection without response`), puis les deux blocs
   suivants ont reçu `Connection refused` : le process était mort. Trois décisions
   perdues sur dix-sept. Cause non identifiée — la grammaire d'un bloc compte
   vingt à trente alternatives littérales avec apostrophes et accents, et cette
   machine n'a pas de marge mémoire. **C'est un bug à isoler avant de réessayer**,
   pas une limite de principe.
2. **Il n'améliore pas la décision, il l'abîme.** Trois faux positifs au lieu de
   deux : `n12` — « je passe à la pharmacie de la place Gambetta » — était tenu
   sans ancrage et devient `place Gambetta pharmacie pharmacie`. Explication la
   plus simple, **non vérifiée** : la grammaire ne contraint que ce qui vient
   APRÈS `oui|`, elle ne peut pas rendre le « oui » plus coûteux ; un vocabulaire
   tiré du bloc rend au contraire un « oui » plausible plus facile à écrire.
3. **Il n'améliore même pas la requête là où on l'attendait.** Il supprime bien
   toute contamination par les exemples — plus un mot de « tarte Tatin » nulle
   part, c'est net. Mais sur les « oui » réellement évalués : `Colisée Rome allés
   dernier` (juste), puis `pattes des avec des` pour l'axolotl (à côté). Choisir
   parmi les mots du bloc ne garantit pas de choisir les bons.

D'où le défaut du code livré : **`ancrage=False`**. La configuration entièrement
mesurée et la meilleure sur les trois chiffres qui comptent est la grammaire
libre. L'option reste dans `decideur_local.grammaire()` et
`bench_decideur.py --ancrage`, avec ce résultat écrit à côté.

Point positif quand même : la grammaire reconstruite à chaque bloc **ne coûte
rien de mesurable** (10,1 s de médiane contre 10,5 s). Si le crash est corrigé et
le « oui » rendu plus coûteux autrement, l'idée reste disponible.


## Le thermique, qui n'est pas un détail

Cette machine passe de 59 à 84 °C en une minute et demie de génération, bride à
80 °C et retombe à 600 MHz. Relevé autour de chaque passe :

| passe | départ | fin | `get_throttled` en fin |
|---|---|---|---|
| smollm2-135m | 55 °C | 83,8 °C | `0x20002` |
| qwen25-05b | 59,1 °C | 84,4 °C | `0x60002` |
| smollm2-360m | 59,1 °C | 84,9 °C | `0x60002` |

`0x…2` = **bridé au moment de la mesure**. Les latences du tableau sont donc
celles d'un Pi bridé, c'est-à-dire celles d'une vraie soirée et non d'un banc :
c'est le bon régime à mesurer, mais il faut savoir que le premier bloc d'une
soirée froide sera plus rapide que les suivants.

À noter : le banc est un **pire cas**. Il enchaîne 17 décisions sans respirer, là
où la boucle réelle fait ~10 s de LLM pour ~75 s de cycle. Redescendre sous
60 °C entre deux passes a demandé **5 minutes** de repos complet, et la machine
plafonne autour de 62-65 °C dès qu'on la sollicite un peu — un simple `ssh`
toutes les vingt secondes suffit à l'empêcher de refroidir.

## Ce qui a été essayé et écarté

**`llama-cli` en mode conversation, piloté par tuyaux.** Ce serait la façon la
plus légère de garder un modèle chaud sans serveur HTTP. Ça ne marche pas : avec
stdin qui n'est pas un terminal, `llama-cli` (même avec `--simple-io`) consomme
l'entrée d'un coup, réaffiche trente invites vides et ne génère rien. Écarté au
profit de `llama-server`.

**Un modèle de 1 à 1,5 B.** Pas tenté, et pas par prudence : `qwen25-05b-q4`
occupe déjà 510 Mio sur les 905 de la machine, et whisper `tiny` doit rester
résident à côté. Le contexte du décideur a d'ailleurs été ramené de 2048 à
**1024 tokens** pour cette raison — le préfixe pèse ~600 tokens et un bloc ~150,
le reste était du cache KV payé pour rien.

**Un pré-filtre non-LLM** (rejeter un bloc qui n'a aucun mot capitalisé hors
début de phrase, par exemple) : pas mesuré. Il économiserait du temps mais ne
corrigerait pas les faux positifs restants, qui portent tous sur des blocs où le
modèle avait bel et bien de quoi s'accrocher.

## Verdict

**Le décideur peut être local, et `qwen25-05b-q4` est le seul candidat qui
tienne.** C'est mesuré sur les 17 cas : cinq sujets sur cinq trouvés, cinq
requêtes reconnaissables, les trois pièges tenus, 10,5 s par bloc. Les deux
autres modèles ne décident pas — l'un au hasard, l'autre jamais.

**Mais il reste deux faux positifs sur douze**, soit une image sans rapport
environ un bloc sur six. À 45 s le bloc, c'est une image de travers toutes les
cinq à huit minutes. Ce n'est pas « oui à tout », ce n'est pas la retenue non
plus : **en l'état, c'est un prototype à regarder, pas un objet à laisser tourner
dans un salon.**

### Le cycle de bout en bout n'a PAS été mesuré

`bout-en-bout.sh` est écrit et déployé, et il a échoué à sa première exécution :
**piper avorte** (`Aborted`) sur le texte long de 45 s, alors qu'il synthétise
sans broncher une phrase courte (« Le Colisée à Rome. », RTF 0,94). Cause non
cherchée — sans doute la longueur, ou un caractère du texte. La suite du script
(whisper → décideur → image → écran) n'a donc jamais tourné.

**Aucun chiffre de cycle complet n'existe.** Ce qui manque, précisément : le temps
whisper d'un bloc de 45 s, la RSS simultanée de whisper et de `llama-server`, et
la preuve à l'écran. Ce sont les trois choses à faire en premier à la reprise.

Ce qui EST prouvé sur la chaîne : `--decideur local|distant` et `--wav` sont en
place dans `ecouter.py`, le décideur local répond au contrat sur 17 cas, et
l'affichage était déjà mesuré par ailleurs (369 ms/image, cf. `README.md`).

### Deux constats du 04/09/2026 qui invalident une partie de ce qui précède

1. **whisper `tiny` est disqualifié.** Sur un vrai enregistrement du micro, il
   rend « les élèves fonds d'Asie » là où `base` rend « les éléphants d'Asie ».
   Les noms concrets ne survivent pas — et ce sont précisément ceux que le
   décideur cherche. Conséquence directe : **`cas.json` mesure le décideur sur du
   texte propre, pas sur ce que la chaîne réelle lui donnera.** Les chiffres du
   tableau sont donc un **plafond**, pas une prévision.
2. **`base` q5 coûte 4 à 6 fois le temps réel sur ce Pi** (RTF 1,00 sur shiao en
   beam search ; le greedy le ramène à 0,61 mais détruit les noms propres, donc
   il est inutilisable ici). Un bloc de 45 s demanderait 3 à 4,5 minutes de STT.
   Deux conséquences :
   - **la latence du décideur cesse d'être le problème** : 10,5 s à côté de
     200 s de STT ne se voit pas. L'argument « facteur 5 à 8 grâce au serveur »
     reste vrai mais n'est plus ce qui décide ;
   - **le cycle passe de ~75 s à ~4 minutes**, donc on ne rate plus la moitié de
     la conversation mais les quatre cinquièmes, et l'image arrive plusieurs
     minutes après le sujet. C'est le prototype entier qui est en question, pas
     le décideur.
3. **La RAM redevient la contrainte dure, et elle n'est PAS mesurée.**
   `qwen25-05b-q4` occupe 510 Mio (RSS, ctx 1024). `base` q5 pèse 60 Mio sur
   disque, sans doute 200 à 250 Mio résidents. 760 Mio sur 905 : ça peut passer,
   ça peut swapper — et le swap sur carte SD ferait exploser les deux latences.
   **À mesurer avant tout le reste.** Si ça ne passe pas, le repli n'existe pas :
   `smollm2-360m` tient dans la RAM mais ne décide rien.
4. Le micro sort à −12 dBFS de crête et demande un **gain numérique** avant
   whisper. Le cycle de bout en bout de ce banc utilise de la parole
   **synthétisée** (piper, plein niveau) : il n'a donc jamais rencontré ce
   problème, et ne dit rien sur la chaîne audio réelle.

### Ce qui reste à faire, dans cet ordre

1. Installer `ggml-base-q5_1.bin` sur le Pi et **mesurer la coexistence**
   whisper `base` + `llama-server` qwen 0,5 B dans 905 Mio (RSS des deux,
   `si_swap` non nul ou non). C'est ce qui décide si le décideur retenu est
   utilisable du tout.
2. Refaire `cas.json` avec de **vraies sorties whisper `base`** sur des
   enregistrements du micro de la pièce, gain appliqué. Les 17 cas actuels
   restent utiles comme jeu de non-régression sur texte propre.
3. Attaquer les faux positifs — 2 sur 12 en grammaire libre, 3 sur 12 en
   grammaire ancrée. La grammaire a montré sa limite : elle contraint la FORME
   de la réponse, jamais le fait de dire oui. Le levier non essayé le plus
   probable est une **deuxième passe de vérification** sur les seuls blocs où la
   première a dit oui (« parle-t-on vraiment de X ? »), qui ne coûte que sur le
   cas rare — et dont le préfixe est déjà en cache.
4. Comparer au décideur distant sur le **même** jeu. Non fait ici, volontairement :
   l'exercice interdit d'envoyer du texte d'exemple à une API tierce.
