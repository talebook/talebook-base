from __future__ import annotations

import sys

from talebook_calibre_env import configure


configure("ebook-convert-pdf")

from calibre.ebooks.conversion.weasy_pdf_binary import main


raise SystemExit(main(["ebook-convert-pdf", *sys.argv[1:]]))
