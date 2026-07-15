from __future__ import annotations

import sys

from talebook_calibre_env import configure


configure("ebook-convert")

from calibre.ebooks.conversion.standalone_binary import main


raise SystemExit(main(["ebook-convert", *sys.argv[1:]]))
