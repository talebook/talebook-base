__license__ = 'GPL 3'
__copyright__ = '2026, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

'''
Internal WeasyPrint PDF backend for the public ebook-convert command.

The public ebook-convert router selects this backend for .pdf outputs. It uses
calibre's input pipeline to normalize supported book formats into OEB, then
renders that OEB with WeasyPrint. This module is not a separate public command.
'''

import argparse
import html
import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

os.environ.setdefault('CALIBRE_STANDALONE_CONVERTER', '1')

from calibre.ebooks.conversion.standalone_common import SUPPORTED_INPUT_FORMATS, extension_of, install_qt_import_guard

if os.environ.get('CALIBRE_STANDALONE_FORBID_QT') == '1':
    install_qt_import_guard('ebook-convert')

XHTML_MEDIA_TYPES = frozenset({'application/xhtml+xml', 'text/html'})
CSS_MEDIA_TYPES = frozenset({'text/css'})
IMAGE_MEDIA_PREFIX = 'image/'
SPACE_RE = re.compile(r'\s+')


def safe_file_url(path):
    return Path(path).resolve().as_uri()


def rel_url(path, base):
    rel = os.path.relpath(path, base).replace(os.sep, '/')
    return quote(rel, safe='/#:%?&=@+,;!$()*[]')


def parse_opf(opf_path):
    root = ET.parse(opf_path).getroot()
    manifest = {}
    for item in root.findall('.//{*}manifest/{*}item'):
        item_id = item.get('id')
        href = item.get('href')
        if not item_id or not href:
            continue
        manifest[item_id] = {
            'href': href,
            'media_type': item.get('media-type', ''),
            'properties': item.get('properties', ''),
        }
    spine = [item.get('idref') for item in root.findall('.//{*}spine/{*}itemref') if item.get('idref')]
    title = ''
    title_el = root.find('.//{*}metadata/{*}title')
    if title_el is not None and title_el.text:
        title = SPACE_RE.sub(' ', title_el.text).strip()
    return manifest, spine, title


def find_opf(oeb_dir):
    opfs = sorted(Path(oeb_dir).glob('*.opf'))
    if not opfs:
        opfs = sorted(Path(oeb_dir).rglob('*.opf'))
    if not opfs:
        raise RuntimeError(f'No OPF file found in generated OEB directory: {oeb_dir}')
    return opfs[0]


def rewrite_attr_urls(soup, attr, doc_path, opf_dir):
    opf_dir = Path(opf_dir).resolve()
    for tag in soup.find_all(attrs={attr: True}):
        value = tag.get(attr)
        if not value or value.startswith(('http:', 'https:', 'data:', 'mailto:', '#')):
            continue
        if value.startswith('file:'):
            continue
        parts = urlsplit(value)
        path = unquote(parts.path)
        resolved = (doc_path.parent / path).resolve()
        rewritten = rel_url(resolved, opf_dir)
        tag[attr] = urlunsplit(('', '', rewritten, parts.query, parts.fragment))


def extract_body_html(doc_path, opf_dir):
    from bs4 import BeautifulSoup

    raw = doc_path.read_text(encoding='utf-8', errors='replace')
    soup = BeautifulSoup(raw, 'html.parser')
    rewrite_attr_urls(soup, 'src', doc_path, opf_dir)
    rewrite_attr_urls(soup, 'href', doc_path, opf_dir)
    rewrite_attr_urls(soup, 'xlink:href', doc_path, opf_dir)
    body = soup.find('body')
    if body is None:
        return ''.join(str(x) for x in soup.contents)
    return ''.join(str(x) for x in body.children)


def standalone_cjk_font_face():
    resources = getattr(sys, 'resources_location', '') or os.environ.get('CALIBRE_RESOURCES_PATH', '')
    fonts_dir = Path(resources) / 'fonts' if resources else None
    if not fonts_dir or not fonts_dir.exists():
        return ''
    fonts = sorted(fonts_dir.glob('standalone-cjk.*'))
    if not fonts:
        return ''
    return (
        '@font-face { font-family: "Standalone CJK"; '
        f'src: url("{safe_file_url(fonts[0])}"); font-weight: normal; font-style: normal; }}\n'
    )


def combined_html_from_oeb(oeb_dir, page_size='A4', margin='0.7in'):
    opf_path = find_opf(oeb_dir)
    opf_dir = opf_path.parent.resolve()
    manifest, spine, title = parse_opf(opf_path)
    css_links = []
    for item in manifest.values():
        if item['media_type'] in CSS_MEDIA_TYPES:
            css_path = (opf_dir / item['href']).resolve()
            if css_path.exists():
                css_links.append(f'<link rel="stylesheet" href="{rel_url(css_path, opf_dir)}">')

    chunks = []
    for idref in spine:
        item = manifest.get(idref)
        if not item or item['media_type'] not in XHTML_MEDIA_TYPES:
            continue
        doc_path = (opf_dir / item['href']).resolve()
        if not doc_path.exists():
            continue
        chunks.append(f'<section class="calibre-weasy-spine-item">{extract_body_html(doc_path, opf_dir)}</section>')

    if not chunks:
        image_chunks = []
        for item in manifest.values():
            if item['media_type'].startswith(IMAGE_MEDIA_PREFIX):
                image_path = (opf_dir / item['href']).resolve()
                if image_path.exists():
                    image_chunks.append(
                        '<section class="calibre-weasy-spine-item image-page">'
                        f'<img src="{rel_url(image_path, opf_dir)}">'
                        '</section>'
                    )
        chunks = image_chunks

    if not chunks:
        raise RuntimeError('Generated OEB has no renderable HTML or image spine content')

    base_css = f'''
{standalone_cjk_font_face()}
@page {{ size: {page_size}; margin: {margin}; }}
html, body {{ font-family: "Standalone CJK", serif; line-height: 1.45; }}
img, svg {{ max-width: 100%; height: auto; }}
.calibre-weasy-spine-item {{ break-before: page; }}
.calibre-weasy-spine-item:first-child {{ break-before: auto; }}
.image-page {{ page-break-inside: avoid; text-align: center; }}
.image-page img {{ max-height: 100vh; object-fit: contain; }}
'''
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{html.escape(title or "ebook-convert")}</title>'
        f'{"".join(css_links)}<style>{base_css}</style></head>'
        f'<body>{"".join(chunks)}</body></html>'
    ), str(opf_dir)


def run_calibre_to_oeb(input_path, oeb_dir, passthrough_args):
    from calibre.ebooks.conversion.cli import main as ebook_convert_main

    args = ['ebook-convert', input_path, oeb_dir, *passthrough_args]
    try:
        rc = ebook_convert_main(args)
    except SystemExit as err:
        rc = err.code if isinstance(err.code, int) else 1
    return int(rc or 0)


def convert(input_path, output_path, passthrough_args=(), page_size='A4', margin='0.7in'):
    try:
        from weasyprint import HTML
    except ImportError as err:
        raise RuntimeError(
            f'WeasyPrint or one of its dependencies is not available in this package: {err}'
        ) from err

    input_fmt = extension_of(input_path)
    if input_fmt not in SUPPORTED_INPUT_FORMATS:
        allowed = ', '.join(sorted(SUPPORTED_INPUT_FORMATS))
        raise ValueError(f'Unsupported PDF input format for ebook-convert: {input_fmt or "open ebook/folder"}. Allowed: {allowed}')
    if extension_of(output_path) != 'pdf':
        raise ValueError('ebook-convert PDF backend requires an output path ending in .pdf')

    output_parent = os.path.dirname(os.path.abspath(output_path))
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)

    with TemporaryDirectory('_ebook_convert_pdf_oeb') as tdir:
        rc = run_calibre_to_oeb(input_path, tdir, passthrough_args)
        if rc != 0:
            return rc
        html_text, base_url = combined_html_from_oeb(tdir, page_size=page_size, margin=margin)
        HTML(string=html_text, base_url=base_url).write_pdf(output_path)
    return 0


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(
        prog='ebook-convert',
        description='Convert supported ebook formats to PDF using calibre input plugins and WeasyPrint.',
    )
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args(argv[1:3])

    weasy_parser = argparse.ArgumentParser(add_help=False)
    weasy_parser.add_argument('--weasy-page-size', default='A4')
    weasy_parser.add_argument('--weasy-margin', default='0.7in')
    option_args = list(argv[3:])
    if '--' in option_args:
        sep = option_args.index('--')
        weasy_args, calibre_args = option_args[:sep], option_args[sep + 1:]
    else:
        weasy_args, calibre_args = option_args, []
    weasy_opts, unknown = weasy_parser.parse_known_args(weasy_args)
    passthrough = [*unknown, *calibre_args]
    try:
        return convert(
            args.input, args.output, passthrough,
            page_size=weasy_opts.weasy_page_size, margin=weasy_opts.weasy_margin,
        )
    except Exception as err:
        print(f'ebook-convert: PDF backend: {err}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
