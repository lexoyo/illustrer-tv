#!/usr/bin/env bash
# Installe les dépendances Python SUR LE PI, sans toucher au système.
#   ./install.sh
# Debian 13 refuse `pip install` sur le python système (PEP 668) : on crée donc
# un venv local. --system-site-packages sert à réutiliser le numpy 2.2.4 déjà
# présent en système au lieu de recompiler. Pillow vient de piwheels en wheel
# aarch64, pas de compilation.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install --disable-pip-version-check --quiet pillow
./.venv/bin/python -c 'import PIL, numpy; print("PIL", PIL.__version__, "/ numpy", numpy.__version__)'
echo "OK — utilise ./.venv/bin/python show.py ..."
