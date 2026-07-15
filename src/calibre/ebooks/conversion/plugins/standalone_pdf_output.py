__license__ = 'GPL 3'
__copyright__ = '2026, Kovid Goyal <kovid at kovidgoyal.net>'

'''
Small PDF output plugin for the standalone ebook-convert binary.

This intentionally avoids QtWebEngine. It favors a small dependency surface over
pixel-perfect HTML/CSS rendering.
'''

import os
import re
import struct
import sys
from io import BytesIO
from urllib.parse import urldefrag

from calibre.customize.conversion import OptionRecommendation, OutputFormatPlugin


PAPER_SIZES = {
    'letter': (612, 792),
    'a4': (595, 842),
}
STANDALONE_CJK_FONT_NAMES = ('standalone-cjk.ttf', 'standalone-cjk.ttc', 'wqy-microhei.ttc', 'Arial Unicode.ttf')


def utf16be_hex(text, bom=False):
    prefix = '\ufeff' if bom else ''
    return '<' + (prefix + text).encode('utf-16-be', 'replace').hex().upper() + '>'


class TextEncoder:
    '''
    Maps document characters to 2-byte CIDs. BMP characters use their own code
    point as CID; non-BMP characters get spare CIDs (starting in the Private
    Use Area) so ToUnicode can map one CID to the full surrogate pair — text
    extractors cannot reassemble a character split across two CIDs.
    '''

    def __init__(self, text):
        chars = sorted(set(text))
        used = {ord(c) for c in chars if ord(c) <= 0xffff}
        self.cid_of = {}
        next_cid = 0xE000
        for c in chars:
            cp = ord(c)
            if cp <= 0xffff:
                self.cid_of[c] = cp
                continue
            while next_cid <= 0xffff and next_cid in used:
                next_cid += 1
            if next_cid > 0xffff:  # more distinct non-BMP chars than free CIDs
                self.cid_of[c] = 0xfffd
                continue
            self.cid_of[c] = next_cid
            used.add(next_cid)
        if not self.cid_of:
            self.cid_of[' '] = 0x20

    def cids(self, text):
        return [self.cid_of.get(c, 0xfffd) for c in text]

    def hex_string(self, text):
        return '<' + ''.join(f'{x:04X}' for x in self.cids(text)) + '>'

    def items(self):
        return sorted(self.cid_of.items(), key=lambda x: x[1])


def metadata_text(value, default='Unknown'):
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        value = ', '.join(str(x) for x in value if x)
    return str(value or default)


def wrap_words(text, max_chars):
    def pieces(word):
        if len(word) <= max_chars:
            return [word]
        return [word[i:i + max_chars] for i in range(0, len(word), max_chars)]

    ans = []
    for para in re.split(r'\n{2,}', text):
        words = []
        for word in para.split():
            words.extend(pieces(word))
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


def make_tounicode_cmap(encoder):
    entries = [
        (cid, char.encode('utf-16-be').hex().upper())
        for char, cid in encoder.items()
    ]
    chunks = []
    for i in range(0, len(entries), 100):
        group = entries[i:i + 100]
        chunks.append(f'{len(group)} beginbfchar')
        chunks.extend(f'<{cid:04X}> <{dest}>' for cid, dest in group)
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


def checksum(data):
    extra = (-len(data)) % 4
    if extra:
        data += b'\0' * extra
    return sum(struct.unpack(f'>{len(data) // 4}I', data)) & 0xffffffff


def rebuild_ttf_from_ttc(data, font_offset):
    sfnt_version, num_tables, search_range, entry_selector, range_shift = struct.unpack_from('>IHHHH', data, font_offset)
    records = []
    pos = font_offset + 12
    for _ in range(num_tables):
        tag, _check, offset, length = struct.unpack_from('>4sIII', data, pos)
        records.append((tag, data[offset:offset + length]))
        pos += 16
    out = bytearray(struct.pack('>IHHHH', sfnt_version, num_tables, search_range, entry_selector, range_shift))
    data_offset = 12 + (16 * num_tables)
    table_data = bytearray()
    record_positions = []
    for tag, raw in records:
        aligned = (-len(table_data)) % 4
        if aligned:
            table_data.extend(b'\0' * aligned)
        offset = data_offset + len(table_data)
        q = bytearray(raw)
        if tag == b'head' and len(q) >= 12:
            q[8:12] = b'\0\0\0\0'
        record_positions.append((len(out), tag, offset, len(raw), bytes(q)))
        out.extend(b'\0' * 16)
        table_data.extend(q)
    out.extend(table_data)
    for record_pos, tag, offset, length, raw in record_positions:
        struct.pack_into('>4sIII', out, record_pos, tag, checksum(raw), offset, length)
    total = checksum(bytes(out))
    adjustment = (0xB1B0AFBA - total) & 0xffffffff
    for _record_pos, tag, offset, length, _raw in record_positions:
        if tag == b'head' and length >= 12:
            struct.pack_into('>I', out, offset + 8, adjustment)
            break
    return bytes(out)


class EmbeddedFont:

    def __init__(self, path):
        raw = open(path, 'rb').read()
        self.path = path
        if raw[:4] == b'ttcf':
            font_offset = struct.unpack_from('>I', raw, 12)[0]
            raw = rebuild_ttf_from_ttc(raw, font_offset)
        self.raw = raw
        self.tables = {}
        _version, num_tables, _search_range, _entry_selector, _range_shift = struct.unpack_from('>IHHHH', raw, 0)
        pos = 12
        for _ in range(num_tables):
            tag, _check, offset, length = struct.unpack_from('>4sIII', raw, pos)
            self.tables[tag.decode('ascii')] = (offset, length)
            pos += 16
        self.units_per_em = self.u16('head', 18)
        self.x_min = self.i16('head', 36)
        self.y_min = self.i16('head', 38)
        self.x_max = self.i16('head', 40)
        self.y_max = self.i16('head', 42)
        self.ascent = self.i16('hhea', 4)
        self.descent = self.i16('hhea', 6)
        self.number_of_hmetrics = self.u16('hhea', 34)
        self.advance_widths = self.read_advance_widths()
        self.cmap = self.read_cmap()

    def table(self, name):
        offset, length = self.tables[name]
        return self.raw[offset:offset + length]

    def u16(self, table, offset):
        base, _length = self.tables[table]
        return struct.unpack_from('>H', self.raw, base + offset)[0]

    def i16(self, table, offset):
        base, _length = self.tables[table]
        return struct.unpack_from('>h', self.raw, base + offset)[0]

    def scale(self, value):
        return int(round((value * 1000) / (self.units_per_em or 1000)))

    def read_advance_widths(self):
        data = self.table('hmtx')
        ans = []
        for i in range(self.number_of_hmetrics):
            ans.append(struct.unpack_from('>H', data, i * 4)[0])
        return ans or [self.units_per_em]

    def width_for_gid(self, gid):
        if gid < len(self.advance_widths):
            width = self.advance_widths[gid]
        else:
            width = self.advance_widths[-1]
        return self.scale(width)

    def read_cmap(self):
        data = self.table('cmap')
        _version, num_tables = struct.unpack_from('>HH', data, 0)
        records = []
        for i in range(num_tables):
            platform, encoding, offset = struct.unpack_from('>HHI', data, 4 + (i * 8))
            fmt = struct.unpack_from('>H', data, offset)[0]
            records.append((fmt, platform, encoding, offset))
        for fmt, platform, encoding, offset in sorted(records, key=lambda x: (x[0] != 12, x[1] != 3, x[2] not in {10, 1, 0})):
            if fmt == 12:
                return self.read_cmap_format12(data, offset)
            if fmt == 4:
                return self.read_cmap_format4(data, offset)
        return {}

    def read_cmap_format12(self, data, offset):
        _fmt, _reserved, _length, _language, groups = struct.unpack_from('>HHIII', data, offset)
        ans = {}
        pos = offset + 16
        for _ in range(groups):
            start, end, start_gid = struct.unpack_from('>III', data, pos)
            pos += 12
            for cp in range(start, end + 1):
                ans[cp] = start_gid + cp - start
        return ans

    def read_cmap_format4(self, data, offset):
        _fmt, length, _language, seg_count_x2 = struct.unpack_from('>HHHH', data, offset)
        seg_count = seg_count_x2 // 2
        end_codes = struct.unpack_from(f'>{seg_count}H', data, offset + 14)
        start_pos = offset + 16 + (2 * seg_count)
        start_codes = struct.unpack_from(f'>{seg_count}H', data, start_pos)
        delta_pos = start_pos + (2 * seg_count)
        id_deltas = struct.unpack_from(f'>{seg_count}h', data, delta_pos)
        range_pos = delta_pos + (2 * seg_count)
        id_range_offsets = struct.unpack_from(f'>{seg_count}H', data, range_pos)
        ans = {}
        table_end = offset + length
        for i, (start, end, delta, roff) in enumerate(zip(start_codes, end_codes, id_deltas, id_range_offsets)):
            if start == 0xffff and end == 0xffff:
                continue
            for cp in range(start, min(end, 0xffff) + 1):
                if roff == 0:
                    gid = (cp + delta) & 0xffff
                else:
                    glyph_offset = range_pos + (2 * i) + roff + (2 * (cp - start))
                    if glyph_offset + 2 > table_end:
                        gid = 0
                    else:
                        gid = struct.unpack_from('>H', data, glyph_offset)[0]
                        if gid:
                            gid = (gid + delta) & 0xffff
                if gid:
                    ans[cp] = gid
        return ans

    def glyph_id(self, cp):
        return self.cmap.get(cp, 0)


def find_cjk_font():
    paths = []
    env_path = os.environ.get('CALIBRE_STANDALONE_CJK_FONT')
    if env_path:
        paths.append(env_path)
    resources = getattr(sys, 'resources_location', None)
    if resources:
        for name in STANDALONE_CJK_FONT_NAMES:
            paths.append(os.path.join(resources, 'fonts', name))
    paths.extend((
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/System/Library/Fonts/STHeiti Light.ttc',
    ))
    for path in paths:
        if path and os.path.exists(path):
            return path
    raise RuntimeError('No standalone CJK font found for PDF output')


def pdf_stream(data, attrs=''):
    if isinstance(data, str):
        data = data.encode('ascii')
    attrs = (' ' + attrs.strip()) if attrs.strip() else ''
    return b'<< /Length %d%s >>\nstream\n' % (len(data), attrs.encode('ascii')) + data + b'\nendstream'


def make_cid_to_gid_map(font, encoder):
    max_cid = max(cid for _char, cid in encoder.items())
    raw = bytearray((max_cid + 1) * 2)
    for char, cid in encoder.items():
        struct.pack_into('>H', raw, cid * 2, font.glyph_id(ord(char)))
    return bytes(raw)


def make_widths(font, encoder):
    pairs = []
    for char, cid in encoder.items():
        pairs.append(f'{cid} [{font.width_for_gid(font.glyph_id(ord(char)))}]')
    return '[' + ' '.join(pairs) + ']'


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


def finish_pdf(objects, catalog_id, pages_id, page_ids, title, author):
    info_id = len(objects) + 1
    objects.append(
        f'<< /Title {utf16be_hex(title, bom=True)} /Author {utf16be_hex(author, bom=True)} '
        '/Producer (calibre standalone ebook-convert) >>'
    )
    objects[catalog_id - 1] = f'<< /Type /Catalog /Pages {pages_id} 0 R >>'
    kids = ' '.join(f'{x} 0 R' for x in page_ids)
    objects[pages_id - 1] = f'<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>'

    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode('ascii')
        out += obj if isinstance(obj, bytes) else obj.encode('ascii')
        out += b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n'.encode('ascii')
    out += b'0000000000 65535 f \n'
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode('ascii')
    out += (
        f'trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n'
        f'startxref\n{xref}\n%%EOF\n'
    ).encode('ascii')
    return bytes(out)


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
    encoder = TextEncoder(all_text)
    tounicode = make_tounicode_cmap(encoder).encode('ascii')
    tounicode_id = add(pdf_stream(tounicode))
    font = EmbeddedFont(find_cjk_font())
    font_file_id = add(pdf_stream(font.raw, f'/Length1 {len(font.raw)}'))
    cid_to_gid_id = add(pdf_stream(make_cid_to_gid_map(font, encoder)))
    bbox = ' '.join(str(font.scale(x)) for x in (font.x_min, font.y_min, font.x_max, font.y_max))
    descriptor_id = add(
        f'<< /Type /FontDescriptor /FontName /StandaloneCJK /Flags 4 /FontBBox [{bbox}] '
        f'/ItalicAngle 0 /Ascent {font.scale(font.ascent)} /Descent {font.scale(font.descent)} '
        f'/CapHeight {font.scale(font.ascent)} /StemV 80 /FontFile2 {font_file_id} 0 R >>'
    )
    cidfont_id = add(
        f'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /StandaloneCJK '
        f'/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> '
        f'/FontDescriptor {descriptor_id} 0 R /CIDToGIDMap {cid_to_gid_id} 0 R /W {make_widths(font, encoder)} >>'
    )
    font_id = add(
        f'<< /Type /Font /Subtype /Type0 /BaseFont /StandaloneCJK /Encoding /Identity-H '
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
            commands.append(f'{encoder.hex_string(line)} Tj')
        commands.append('ET')
        stream = '\n'.join(commands).encode('ascii')
        content_id = add(pdf_stream(stream))
        page_id = add(
            f'<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] '
            f'/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>'
        )
        page_ids.append(page_id)

    return finish_pdf(objects, catalog_id, pages_id, page_ids, title, author)


def jpeg_image_data(data):
    from PIL import Image
    img = Image.open(BytesIO(data))
    img.load()
    width, height = img.size
    out = BytesIO()
    img.convert('RGB').save(out, 'JPEG', quality=90, optimize=True)
    return out.getvalue(), width, height


def make_image_pdf_bytes(images, title='Unknown', author='Unknown', page_size=(612, 792), margin=18):
    width, height = page_size
    objects = []

    def add(obj):
        objects.append(obj)
        return len(objects)

    catalog_id = add('')
    pages_id = add('')
    page_ids = []
    usable_width = width - (2 * margin)
    usable_height = height - (2 * margin)

    for raw in images:
        try:
            jpeg, img_width, img_height = jpeg_image_data(raw)
        except Exception:
            continue
        image_id = add(
            b'<< /Type /XObject /Subtype /Image /Width %d /Height %d '
            b'/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\n'
            b'stream\n' % (img_width, img_height, len(jpeg)) + jpeg + b'\nendstream'
        )
        scale = min(usable_width / max(1, img_width), usable_height / max(1, img_height))
        draw_width = img_width * scale
        draw_height = img_height * scale
        x = (width - draw_width) / 2
        y = (height - draw_height) / 2
        content = f'q\n{draw_width:.3f} 0 0 {draw_height:.3f} {x:.3f} {y:.3f} cm\n/Im0 Do\nQ'.encode('ascii')
        content_id = add(pdf_stream(content))
        page_id = add(
            f'<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] '
            f'/Resources << /XObject << /Im0 {image_id} 0 R >> >> /Contents {content_id} 0 R >>'
        )
        page_ids.append(page_id)

    if not page_ids:
        return make_pdf_bytes([''], title=title, author=author, page_size=page_size)

    return finish_pdf(objects, catalog_id, pages_id, page_ids, title, author)


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
        # May be empty; the caller decides between the image-page path and a
        # title-only fallback, so no placeholder text is injected here.
        return '\n\n'.join(chunks)

    def image_pages_from_oeb(self, oeb_book, log):
        hrefs = oeb_book.manifest.hrefs
        images = []
        seen = set()
        for item in oeb_book.spine:
            data = item.data
            if not hasattr(data, 'iter'):
                continue
            for elem in data.iter():
                if barename(getattr(elem, 'tag', '')) != 'img':
                    continue
                src = elem.get('src')
                if not src:
                    continue
                href = urldefrag(item.abshref(src))[0]
                if href in seen:
                    continue
                seen.add(href)
                image = hrefs.get(href)
                if image is None:
                    continue
                raw = image.data
                if isinstance(raw, str):
                    raw = raw.encode('utf-8')
                if isinstance(raw, bytes):
                    images.append(raw)
        return images

    def convert(self, oeb_book, output_path, input_plugin, opts, log):
        log.debug('Converting text content to a small standalone PDF without Qt...')
        text = self.text_from_oeb(oeb_book, opts, log)
        page_size = PAPER_SIZES.get(getattr(opts, 'paper_size', 'letter'), PAPER_SIZES['letter'])
        font_size = int(getattr(opts, 'pdf_default_font_size', 11) or 11)
        title = metadata_text(getattr(oeb_book.metadata, 'title', None))
        author = metadata_text(getattr(oeb_book.metadata, 'creator', None))
        image_pages = self.image_pages_from_oeb(oeb_book, log)
        text_chars = len(re.sub(r'\s+', '', text))
        if len(image_pages) >= 3 and text_chars == 0:
            log.debug(f'Converting {len(image_pages)} image pages to a standalone PDF without Qt...')
            raw = make_image_pdf_bytes(image_pages, title=title, author=author, page_size=page_size)
        else:
            # Use a conservative one-em estimate so CJK lines do not run off the
            # page. Overlong lines are clipped by PDF extractors even if the text
            # is present in the content stream.
            max_chars = max(20, int((page_size[0] - 144) / font_size))
            lines = wrap_words(text or title, max_chars)
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
