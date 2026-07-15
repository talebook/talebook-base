__license__ = 'GPL v3'
__copyright__ = '2026, Kovid Goyal <kovid at kovidgoyal.net>'

import os

from calibre.customize import MetadataReaderPlugin, MetadataWriterPlugin
from calibre.customize.profiles import input_profiles, output_profiles
from calibre.ebooks.conversion.plugins.docx_input import DOCXInput
from calibre.ebooks.conversion.plugins.epub_input import EPUBInput
from calibre.ebooks.conversion.plugins.epub_output import EPUBOutput
from calibre.ebooks.conversion.plugins.html_input import HTMLInput
from calibre.ebooks.conversion.plugins.mobi_input import MOBIInput
from calibre.ebooks.conversion.plugins.mobi_output import AZW3Output, MOBIOutput
from calibre.ebooks.conversion.plugins.oeb_output import OEBOutput
from calibre.ebooks.conversion.plugins.pdf_input import PDFInput
from calibre.ebooks.conversion.plugins.standalone_pdf_output import StandalonePDFOutput
from calibre.ebooks.conversion.plugins.txt_input import TXTInput
from calibre.ebooks.conversion.plugins.txt_output import TXTOutput


class EPUBMetadataReader(MetadataReaderPlugin):

    name = 'Read EPUB metadata'
    file_types = {'epub', 'kepub'}
    description = _('Read metadata from EPUB and KEPUB files')

    def get_metadata(self, stream, ftype):
        from calibre.ebooks.metadata.epub import get_metadata, get_quick_metadata
        if self.quick:
            return get_quick_metadata(stream, ftype=ftype)
        return get_metadata(stream, ftype=ftype)


class MOBIMetadataReader(MetadataReaderPlugin):

    name = 'Read MOBI metadata'
    file_types = {'mobi', 'prc', 'azw', 'azw3', 'azw4', 'pobi'}
    description = _('Read metadata from %s files') % 'MOBI'

    def get_metadata(self, stream, ftype):
        from calibre.ebooks.metadata.mobi import get_metadata
        return get_metadata(stream)


class PDFMetadataReader(MetadataReaderPlugin):

    name = 'Read PDF metadata'
    file_types = {'pdf'}
    description = _('Read metadata from %s files') % 'PDF'

    def get_metadata(self, stream, ftype):
        # The regular PDF reader runs read_info() via fork_job, worker
        # infrastructure the standalone binary does not ship. pdfinfo is
        # bundled, so call read_info() in-process (it chdirs, restore cwd).
        import shutil

        from calibre.ebooks.metadata import MetaInformation, string_to_authors
        from calibre.ebooks.metadata.pdf import read_info
        from calibre.ptempfile import TemporaryDirectory
        with TemporaryDirectory('_standalone_pdf_metadata') as pdfpath:
            stream.seek(0)
            with open(os.path.join(pdfpath, 'src.pdf'), 'wb') as f:
                shutil.copyfileobj(stream, f)
            cwd = os.getcwd()
            try:
                info = read_info(pdfpath, False)
            finally:
                os.chdir(cwd)
        if not info:
            return MetaInformation(_('Unknown'), [_('Unknown')])
        title = info.get('Title') or _('Unknown')
        author = info.get('Author')
        mi = MetaInformation(title, string_to_authors(author) if author else [_('Unknown')])
        if info.get('Creator'):
            mi.book_producer = info['Creator']
        if info.get('Subject'):
            mi.tags = [info['Subject']]
        return mi


class TXTMetadataReader(MetadataReaderPlugin):

    name = 'Read TXT metadata'
    file_types = {'txt'}
    description = _('Read metadata from %s files') % 'TXT'
    author = 'John Schember'

    def get_metadata(self, stream, ftype):
        from calibre.ebooks.metadata.txt import get_metadata
        return get_metadata(stream)


class DocXMetadataReader(MetadataReaderPlugin):

    name = 'Read DOCX metadata'
    file_types = {'docx'}
    description = _('Read metadata from %s files') % 'DOCX'

    def get_metadata(self, stream, ftype):
        from calibre.ebooks.metadata.docx import get_metadata
        return get_metadata(stream)


class EPUBMetadataWriter(MetadataWriterPlugin):

    name = 'Set EPUB metadata'
    file_types = {'epub', 'kepub'}
    description = _('Set metadata in EPUB and KEPUB files')

    def set_metadata(self, stream, mi, ftype):
        from calibre.ebooks.metadata.epub import set_metadata
        q = self.site_customization or ''
        set_metadata(stream, mi, apply_null=self.apply_null, force_identifiers=self.force_identifiers, ftype=ftype,
                     add_missing_cover='disable-add-missing-cover' != q or ftype == 'kepub')

    def customization_help(self, gui=False):
        h = 'disable-add-missing-cover'
        if gui:
            h = '<i>' + h + '</i>'
        return _('Enter {0} below to have the EPUB metadata writer plugin not'
                 ' add cover images to EPUB files that have no existing cover image.').format(h)


class MOBIMetadataWriter(MetadataWriterPlugin):

    name = 'Set MOBI metadata'
    file_types = {'mobi', 'prc', 'azw', 'azw3', 'azw4'}
    description = _('Set metadata in %s files') % 'MOBI'
    author = 'Marshall T. Vandegrift'

    def set_metadata(self, stream, mi, type):
        from calibre.ebooks.metadata.mobi import set_metadata
        set_metadata(stream, mi)


class PDFMetadataWriter(MetadataWriterPlugin):

    name = 'Set PDF metadata'
    file_types = {'pdf'}
    description = _('Set metadata in %s files') % 'PDF'
    author = 'Kovid Goyal'

    def set_metadata(self, stream, mi, type):
        from calibre.ebooks.metadata.pdf import set_metadata
        set_metadata(stream, mi)


def standalone_pdf_options():
    ans = set()
    for opt in PDFInput.options:
        q = opt.clone()
        if q.option.name == 'pdf_engine':
            q.recommended_value = 'pdftohtml'
        ans.add(q)
    return ans


class StandalonePDFInput(PDFInput):

    name = 'PDF Input'
    options = standalone_pdf_options()


plugins = [
    EPUBMetadataReader,
    MOBIMetadataReader,
    PDFMetadataReader,
    TXTMetadataReader,
    DocXMetadataReader,
    EPUBMetadataWriter,
    MOBIMetadataWriter,
    PDFMetadataWriter,
    EPUBInput,
    MOBIInput,
    StandalonePDFInput,
    TXTInput,
    HTMLInput,
    DOCXInput,
    EPUBOutput,
    MOBIOutput,
    AZW3Output,
    StandalonePDFOutput,
    TXTOutput,
    OEBOutput,
] + input_profiles + output_profiles
