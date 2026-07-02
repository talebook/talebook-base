__license__ = 'GPL v3'
__copyright__ = '2026, Kovid Goyal <kovid at kovidgoyal.net>'

from calibre.customize import MetadataReaderPlugin, MetadataWriterPlugin
from calibre.ebooks.conversion.plugins.epub_input import EPUBInput
from calibre.ebooks.conversion.plugins.epub_output import EPUBOutput
from calibre.ebooks.conversion.plugins.html_input import HTMLInput
from calibre.ebooks.conversion.plugins.mobi_input import MOBIInput
from calibre.ebooks.conversion.plugins.mobi_output import MOBIOutput
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
        from calibre.ebooks.metadata import MetaInformation
        return MetaInformation(_('Unknown'), [_('Unknown')])


class TXTMetadataReader(MetadataReaderPlugin):

    name = 'Read TXT metadata'
    file_types = {'txt'}
    description = _('Read metadata from %s files') % 'TXT'
    author = 'John Schember'

    def get_metadata(self, stream, ftype):
        from calibre.ebooks.metadata.txt import get_metadata
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


from calibre.customize.profiles import input_profiles, output_profiles


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
    EPUBMetadataWriter,
    MOBIMetadataWriter,
    PDFMetadataWriter,
    EPUBInput,
    MOBIInput,
    StandalonePDFInput,
    TXTInput,
    HTMLInput,
    EPUBOutput,
    MOBIOutput,
    StandalonePDFOutput,
    TXTOutput,
    OEBOutput,
] + input_profiles + output_profiles
