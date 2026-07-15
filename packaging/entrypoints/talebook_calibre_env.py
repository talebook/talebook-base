"""Shared Calibre runtime environment for the talebook-base image."""

from __future__ import annotations

import os
import sys
import tempfile


RUNTIME_ROOT = os.environ.get("TALEBOOK_CALIBRE_PRIVATE_RUNTIME", "/usr/lib/talebook-calibre-runtime")
SITE_PACKAGES = os.path.join(RUNTIME_ROOT, "lib", "python", "site-packages")
PUBLIC_RESOURCES = os.environ.get("TALEBOOK_CALIBRE_RESOURCES", "/usr/share/calibre")
PUBLIC_PLUGINS = os.environ.get("TALEBOOK_CALIBRE_PLUGINS", "/usr/lib/calibre/calibre/plugins")
PUBLIC_EXECUTABLES = os.environ.get("TALEBOOK_CALIBRE_BIN", "/usr/bin")


def configure(command_name: str) -> None:
    state_root = os.path.join(tempfile.gettempdir(), f"{command_name}-standalone")
    os.environ.setdefault("CALIBRE_CONFIG_DIRECTORY", os.path.join(state_root, "config"))
    os.environ.setdefault("CALIBRE_CACHE_DIRECTORY", os.path.join(state_root, "cache"))
    os.environ["CALIBRE_STANDALONE_CONVERTER"] = "1"
    os.environ.setdefault("CALIBRE_STANDALONE_FORBID_QT", "1")
    os.environ.setdefault("TALEBOOK_CALIBRE_PRIVATE_RUNTIME", RUNTIME_ROOT)

    if SITE_PACKAGES not in sys.path:
        sys.path.insert(0, SITE_PACKAGES)
    sys.extensions_location = PUBLIC_PLUGINS
    sys.resources_location = PUBLIC_RESOURCES
    sys.executables_location = PUBLIC_EXECUTABLES
    sys.system_plugins_location = None
    sys.frozen = False
    sys.calibre_basename = command_name
