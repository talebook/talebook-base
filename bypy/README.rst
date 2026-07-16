Build the calibre installers, including all dependencies from scratch
=======================================================================

This folder contains code to automate the process of building calibre,
including all its dependencies, from scratch, for all platforms that calibre
supports.

In general builds proceed in two steps, first build all the dependencies, then
build the calibre installer itself.

Requirements
---------------

Building *must* run on a Linux computer.

First create some empty top level directory and run the following commands::

    git clone https://github.com/kovidgoyal/bypy.git
    git clone https://github.com/kovidgoyal/calibre.git
    cd calibre

Now we need to bootstrap calibre, for which all its Linux build dependencies
must have already been installed (see the `Dependencies
<https://calibre-ebook.com/download_linux>`_ section of the Linux installation
page for details). Once the dependencies are installed, run::

    ./setup.py bootstrap

All building is done inside QEMU VMs. Linux VMs are auto-created as needed,
Windows and macOS VMs must be created manually. Instructions on
creating the VMs are in the bypy repo under :file:`virtual_machine/README.rst`.
Required software for the VMs are listed in :file:`bypy/windows.conf` and
:file:`bypy/macos.conf`.

Linux
-------

To build the Intel and ARM dependencies for calibre, run::

    ./setup.py build_dep linux
    ./setup.py build_dep linux-arm64

The output (after a very long time) will be in :literal:`bypy/b/linux/[32|64]`

Now you can build the calibre Linux tarballs with::

    ./setup.py linux

The output will be in :file:`dist`

To build a standalone Linux package that exposes only the ``ebook-convert``
binary for EPUB, MOBI, PDF and TXT conversions, run::

    ./setup.py linux_ebook_convert

To build only one architecture, run::

    ./setup.py linux_ebook_convert64

    ./setup.py linux_ebook_convertarm64

The output tarball is named
``calibre-ebook-convert-<version>-<arch>.txz`` and is written to
:file:`dist`.

Verify the archive package surface with::

    python3 setup/standalone_ebook_convert_smoke.py --archive dist/calibre-ebook-convert-<version>-<arch>.txz

Verify the standalone validation helpers without building a package with::

    python3 setup/standalone_ebook_convert_smoke.py --self-test

After extracting the tarball on Linux, verify the extracted package surface and
supported conversion matrix with::

    python3 setup/standalone_ebook_convert_smoke.py --forbid-qt-imports /path/to/extracted/ebook-convert

These standalone smoke checks reject Qt/PyQt/``libQt`` artifacts, Qt dynamic
dependencies, calibre GUI/server/device/scraper code surfaces, extra calibre
commands, unsafe archives, unsupported DOCX/recipe conversion, and failures in
the EPUB/MOBI/PDF/TXT conversion matrix.


macOS
--------------

Name the QEMU VM using ``vm_name`` from :literal:`bypy/macos.conf`.
Make sure all software mentioned in :file:`bypy/macos.conf` is installed.
To build the dependencies for calibre, run::

    ./setup.py build_dep macos

The output (after a very long time) will be in :literal:`bypy/b/macos`.
Now you can build the calibre ``.dmg`` with::

    ./setup.py osx --dont-sign --dont-notarize

The output will be in :file:`dist`

To build a standalone macOS package that exposes only the ``ebook-convert``
binary for EPUB, MOBI, PDF and TXT conversions, run::

    ./setup.py osx_ebook_convert --dont-sign --dont-notarize

This command requires Python 3.14 or newer, a bypy checkout pointed to by
``BYPY_LOCATION`` when bypy is not checked out next to calibre, and the macOS
bypy VM files under :file:`bypy/b/macos/vm` in the calibre checkout. The VM
directory must contain the :file:`machine-spec` file described in bypy's
:file:`virtual_machine/README.rst` and :file:`virtual_machine/README-macos.rst`.

The output ``.dmg`` is named ``calibre-ebook-convert-<version>.dmg`` and is
written to :file:`dist`.

Verify the standalone validation helpers without building a package with::

    python3 setup/standalone_ebook_convert_smoke.py --self-test

After mounting the ``.dmg`` on macOS, verify the app package surface and
supported conversion matrix with::

    python3 setup/standalone_ebook_convert_smoke.py --package-root /Volumes/calibre-ebook-convert-<version>/ebook-convert.app
    python3 setup/standalone_ebook_convert_smoke.py /Volumes/calibre-ebook-convert-<version>/ebook-convert.app/Contents/MacOS/ebook-convert

For local macOS development without the bypy VM, an already-built checkout can
be packed into a no-Qt standalone directory with::

    python3 setup/build_standalone_ebook_convert_local.py --output /private/tmp/calibre-ebook-convert-noqt-macos

This developer packager produces a self-contained directory and a matching
``.tar.xz`` archive. It requires a Python 3.14 framework build, the Python
packages used by the conversion pipeline in the ``--venv`` environment, the
native calibre plugins already built under :file:`src/calibre/plugins`, and the
Poppler command line helpers ``pdftohtml``, ``pdfinfo``, ``pdftoppm`` and
``pdftotext`` on ``PATH``. It intentionally excludes Qt/PyQt, GUI commands,
recipes, device integration and non-EPUB/MOBI/PDF/TXT conversion plugins.

Verify the local package with::

    python3 setup/standalone_ebook_convert_smoke.py --archive /private/tmp/calibre-ebook-convert-noqt-macos.tar.xz --max-archive-mb 30
    python3 setup/standalone_ebook_convert_smoke.py --forbid-qt-imports --max-package-mb 150 /private/tmp/calibre-ebook-convert-noqt-macos/ebook-convert


Windows
-------------

Name the QEMU VM using ``vm_name`` from :file:`bypy/windows.conf`.
Make sure all software mentioned in :file:`bypy/windows.conf` is installed.

To build the dependencies for calibre, run::

    ./setup.py build_dep windows

The output (after a very long time) will be in :literal:`bypy/b/windows/64`.
Now you can build the calibre windows installers with::

    ./setup.py win64 --dont-sign

The output will be in :file:`dist`
