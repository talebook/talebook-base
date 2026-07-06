__license__ = 'GPL v3'
__copyright__ = '2026, Kovid Goyal <kovid at kovidgoyal.net>'

from io import BytesIO


class NotImage(ValueError):
    pass


class AnimatedGIF(ValueError):
    pass


class ImageWrapper:

    def __init__(self, img):
        self.img = img

    def width(self):
        return self.img.width

    def height(self):
        return self.img.height

    def isNull(self):
        return self.img is None


def _pil(img):
    return img.img if isinstance(img, ImageWrapper) else img


def image_from_data(data):
    from PIL import Image
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Exception as err:
        raise NotImage(str(err))
    return ImageWrapper(img)


def image_and_format_from_data(data):
    ans = image_from_data(data)
    fmt = (ans.img.format or '').lower()
    return ans, fmt


def _flatten_for_jpeg(img, bgcolor='white'):
    from PIL import Image
    img = _pil(img)
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        base = Image.new('RGB', img.size, bgcolor)
        base.paste(img.convert('RGBA'), mask=img.convert('RGBA').split()[-1])
        return base
    return img.convert('RGB')


def image_to_data(img, compression_quality=95, fmt='JPEG', png_compression_level=9, **kwargs):
    img = _pil(img)
    fmt = fmt.upper()
    if fmt == 'JPG':
        fmt = 'JPEG'
    if fmt == 'JPEG':
        img = _flatten_for_jpeg(img)
    elif fmt == 'PNG':
        img = img.convert('RGBA') if img.mode in ('RGBA', 'LA', 'P') else img
    out = BytesIO()
    save_kwargs = {}
    if fmt == 'JPEG':
        save_kwargs.update(quality=compression_quality, optimize=True)
    elif fmt == 'PNG':
        save_kwargs.update(compress_level=max(0, min(9, png_compression_level)))
    img.save(out, fmt, **save_kwargs)
    return out.getvalue()


def resize_image(img, width, height):
    from PIL import Image
    return ImageWrapper(_pil(img).resize((int(width), int(height)), Image.Resampling.LANCZOS))


def resize_to_fit(data, width, height):
    img = _pil(image_from_data(data))
    if img.width <= width and img.height <= height:
        return False, ImageWrapper(img)
    img.thumbnail((int(width), int(height)))
    return True, ImageWrapper(img)


def scale_image(data, width=60, height=80, compression_quality=70, as_png=False, preserve_aspect_ratio=True):
    from PIL import Image
    img = _pil(image_from_data(data))
    if preserve_aspect_ratio:
        img.thumbnail((int(width), int(height)), Image.Resampling.LANCZOS)
    else:
        img = img.resize((int(width), int(height)), Image.Resampling.LANCZOS)
    fmt = 'PNG' if as_png else 'JPEG'
    return img.width, img.height, image_to_data(ImageWrapper(img), compression_quality=compression_quality, fmt=fmt)


def save_cover_data_to(data, path=None, compression_quality=90, minify_to=None, resize_to=None, data_fmt='jpeg', **kwargs):
    from PIL import Image
    img = _pil(image_from_data(data))
    if resize_to is not None:
        img = img.resize((int(resize_to[0]), int(resize_to[1])), Image.Resampling.LANCZOS)
    elif minify_to is not None:
        img.thumbnail((int(minify_to[0]), int(minify_to[1])), Image.Resampling.LANCZOS)
    fmt = (data_fmt if path is None else path.rpartition('.')[-1] or data_fmt).upper()
    if fmt == 'JPG':
        fmt = 'JPEG'
    raw = image_to_data(ImageWrapper(img), compression_quality=compression_quality, fmt=fmt)
    if path is not None:
        with open(path, 'wb') as f:
            f.write(raw)
    return raw


def png_data_to_gif_data(data):
    from PIL import Image
    img = Image.open(BytesIO(data))
    out = BytesIO()
    if img.mode in ('p', 'P'):
        transparency = img.info.get('transparency')
        if transparency is not None:
            img.save(out, 'GIF', transparency=transparency)
        else:
            img.save(out, 'GIF')
    elif img.mode in ('rgba', 'RGBA'):
        alpha = img.split()[3]
        mask = Image.eval(alpha, lambda a: 255 if a <= 128 else 0)
        img = img.convert('RGB').convert('P', palette=Image.Palette.ADAPTIVE, colors=255)
        img.paste(255, mask)
        img.save(out, 'GIF', transparency=255)
    else:
        img.convert('P', palette=Image.Palette.ADAPTIVE).save(out, 'GIF')
    return out.getvalue()


def gif_data_to_png_data(data, discard_animation=False):
    from PIL import Image
    img = Image.open(BytesIO(data))
    if getattr(img, 'is_animated', False) and not discard_animation:
        raise AnimatedGIF()
    out = BytesIO()
    img.save(out, 'PNG')
    return out.getvalue()


def optimize_png(file_path, level=7):
    from PIL import Image
    img = Image.open(file_path)
    img.save(file_path, 'PNG', optimize=True)
