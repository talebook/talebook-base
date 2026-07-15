from __future__ import annotations

import sys

from talebook_calibre_env import configure


configure("calibredb")

from calibre.db.cli.main import main


raise SystemExit(main(["calibredb", *sys.argv[1:]]))
