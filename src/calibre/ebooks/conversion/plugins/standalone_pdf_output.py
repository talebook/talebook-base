__license__ = 'GPL 3'
__copyright__ = '2026, Kovid Goyal <kovid at kovidgoyal.net>'

'''
Small PDF output plugin for the standalone ebook-convert binary.

This intentionally avoids QtWebEngine. It favors a small dependency surface over
pixel-perfect HTML/CSS rendering.
'''

import os
import re

from calibre.customize.conversion import OptionRecommendation, OutputFormatPlugin


PAPER_SIZES = {
    'letter': (612, 792),
    'a4': (595, 842),
}


def utf16be_hex(text, bom=False):
    prefix = 'FEFF' if bom else ''
    return '<' + prefix + ''.join(f'{ord(x) if ord(x) <= 0xffff else 0xfffd:04X}' for x in text) + '>'


def metadata_text(value, default='Unknown'):
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        value = ', '.join(str(x) for x in value if x)
    return str(value or default)


def wrap_words(text, max_chars):
    ans = []
    for para in re.split(r'\n{2,}', text):
        words = para.split()
        if not words:
            ans.append('')
            continue
        line = words[0]
        for word in words[1:]:
            if len(line) + 1 + len(word) > max_chars:
                ans.append(line)
                line = word
            else:
                line += ' ' + word
        ans.append(line)
        ans.append('')
    while ans and not ans[-1]:
        ans.pop()
    return ans or ['']


def make_tounicode_cmap(chars):
    chars = sorted({ord(x) for x in chars if ord(x) <= 0xffff})
    if not chars:
        chars = [0x20]
    chunks = []
    for i in range(0, len(chars), 100):
        group = chars[i:i + 100]
        chunks.append(f'{len(group)} beginbfchar')
        chunks.extend(f'<{x:04X}> <{x:04X}>' for x in group)
        chunks.append('endbfchar')
    body = '\n'.join(chunks)
    return f'''/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /StandaloneEbookConvert-UTF16 def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
{body}
endcmap
CMapName currentdict /CMap defineresource pop
end
end
'''


def barename(tag):
    if not isinstance(tag, str):
        return ''
    return tag.rpartition('}')[-1].lower()


BLOCK_TAGS = frozenset({'address', 'article', 'aside', 'blockquote', 'br', 'dd', 'div', 'dl', 'dt', 'figcaption',
                        'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main',
                        'nav', 'ol', 'p', 'pre', 'section', 'table', 'td', 'th', 'tr', 'ul'})
SKIP_TAGS = frozenset({'script', 'style', 'head'})


def extract_element_text(elem, out):
    tag = barename(getattr(elem, 'tag', ''))
    if tag in SKIP_TAGS:
        return
    if tag in BLOCK_TAGS and out and out[-1] != '\n':
        out.append('\n')
    if elem.text:
        out.append(elem.text)
    for child in elem:
        extract_element_text(child, out)
        if child.tail:
            out.append(child.tail)
    if tag in BLOCK_TAGS:
        out.append('\n')


def collapse_text(text):
    lines = (' '.join(x.split()) for x in text.splitlines())
    text = '\n'.join(x for x in lines if x)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def make_pdf_bytes(lines, title='Unknown', author='Unknown', page_size=(612, 792), margin=72, font_size=11):
    width, height = page_size
    leading = font_size + 4
    usable_height = height - (2 * margin)
    lines_per_page = max(1, int(usable_height // leading))
    pages = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)] or [['']]
    objects = []

    def add(obj):
        objects.append(obj)
        return len(objects)

    catalog_id = add('')  # placeholder
    pages_id = add('')
    all_text = '\n'.join(lines) + '\n' + title + '\n' + author
    tounicode = make_tounicode_cmap(all_text).encode('ascii')
    tounicode_id = add(f'<< /Length {len(tounicode)} >>\nstream\n{tounicode.decode("ascii")}endstream')
    cidfont_id = add(
        '<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light '
        '/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>'
    )
    font_id = add(
        f'<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /Identity-H '
        f'/DescendantFonts [{cidfont_id} 0 R] /ToUnicode {tounicode_id} 0 R >>'
    )
    page_ids = []

    for page_lines in pages:
        y = height - margin
        commands = ['BT', f'/F1 {font_size} Tf', f'{margin} {y} Td']
        first = True
        for line in page_lines:
            if first:
                first = False
            else:
                commands.append(f'0 -{leading} Td')
            commands.append(f'{utf16be_hex(line)} Tj')
        commands.append('ET')
        stream = '\n'.join(commands).encode('ascii')
        content_id = add(f'<< /Length {len(stream)} >>\nstream\n{stream.decode("ascii")}\nendstream')
        page_id = add(
            f'<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] '
            f'/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>'
        )
        page_ids.append(page_id)

    info_id = add(
        f'<< /Title {utf16be_hex(title, bom=True)} /Author {utf16be_hex(author, bom=True)} '
        '/Producer (calibre standalone ebook-convert) >>'
    )
    objects[catalog_id - 1] = f'<< /Type /Catalog /Pages {pages_id} 0 R >>'
    kids = ' '.join(f'{x} 0 R' for x in page_ids)
    objects[pages_id - 1] = f'<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>'

    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode('ascii')
        out += obj.encode('ascii')
        out += b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode('ascii')
    out += b'0000000000 65535 f \n'
    for offset in offsets[1:]:
        out += f'{offset:010d} 00000 n \n'.encode('ascii')
    out += (
        f'trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n'
        f'startxref\n{xref}\n%%EOF\n'
    ).encode('ascii')
    return bytes(out)


class StandalonePDFOutput(OutputFormatPlugin):

    name = 'PDF Output'
    author = 'Kovid Goyal'
    file_type = 'pdf'
    commit_name = 'pdf_output'

    options = {
        OptionRecommendation(name='paper_size', recommended_value='letter', choices=tuple(PAPER_SIZES),
            help=_('The size of the paper. Choices are letter and a4.')),
        OptionRecommendation(name='pdf_default_font_size', recommended_value=11,
            help=_('The default font size in points.')),
    }

    def specialize_options(self, log, opts, input_fmt):
        self.input_fmt = input_fmt

    def text_from_oeb(self, oeb_book, opts, log):
        chunks = []
        for item in oeb_book.spine:
            data = item.data
            if hasattr(data, 'iter'):
                parts = []
                extract_element_text(data, parts)
                text = collapse_text(''.join(parts))
                if text:
                    chunks.append(text)
            elif isinstance(data, bytes):
                text = data.decode('utf-8', 'replace')
                text = collapse_text(re.sub(r'<[^>]+>', ' ', text))
                if text:
                    chunks.append(text)
        return '\n\n'.join(chunks) or metadata_text(getattr(oeb_book.metadata, 'title', None))

    def convert(self, oeb_book, output_path, input_plugin, opts, log):
        log.debug('Converting text content to a small standalone PDF without Qt...')
        text = self.text_from_oeb(oeb_book, opts, log)
        page_size = PAPER_SIZES.get(getattr(opts, 'paper_size', 'letter'), PAPER_SIZES['letter'])
        font_size = int(getattr(opts, 'pdf_default_font_size', 11) or 11)
        max_chars = max(20, int((page_size[0] - 144) / (font_size * 0.52)))
        lines = wrap_words(text, max_chars)
        title = metadata_text(getattr(oeb_book.metadata, 'title', None))
        author = metadata_text(getattr(oeb_book.metadata, 'creator', None))
        raw = make_pdf_bytes(lines, title=title, author=author, page_size=page_size, font_size=font_size)
        close = False
        if not hasattr(output_path, 'write'):
            close = True
            parent = os.path.dirname(output_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            output_path = open(output_path, 'wb')
        try:
            output_path.seek(0)
            output_path.truncate()
            output_path.write(raw)
        finally:
            if close:
                output_path.close()
