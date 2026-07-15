__license__ = 'GPL v3'
__copyright__ = '2026, Kovid Goyal <kovid at kovidgoyal.net>'

'''
Dispatch between the Qt image helpers and the PIL based standalone ones.
Code that must also run inside the standalone ebook-convert binary imports
image helpers from here, so the switch lives in exactly one place.
'''

import os

if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':
    from calibre.utils.standalone_img import (
        AnimatedGIF,
        gif_data_to_png_data,
        image_and_format_from_data,
        image_from_data,
        image_to_data,
        optimize_png,
        png_data_to_gif_data,
        resize_image,
        resize_to_fit,
        save_cover_data_to,
        scale_image,
    )
else:
    from calibre.utils.img import (
        AnimatedGIF,
        gif_data_to_png_data,
        image_and_format_from_data,
        image_from_data,
        image_to_data,
        optimize_png,
        png_data_to_gif_data,
        resize_image,
        resize_to_fit,
        save_cover_data_to,
        scale_image,
    )
