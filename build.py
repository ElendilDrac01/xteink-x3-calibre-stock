#!/usr/bin/env python3

import zipfile

PLUGIN_NAME = "Xteink_X3.zip"

FILES = {
    "plugin-import-name-xteink_x3.txt":
        "plugin-import-name-xteink_x3.txt",

    "src/calibre_plugins/xteink_x3/__init__.py":
        "__init__.py",

    "src/calibre_plugins/xteink_x3/action.py":
        "action.py",

    "src/calibre_plugins/xteink_x3/network.py":
        "network.py",

    "src/calibre_plugins/xteink_x3/translations/fr.mo":
        "translations/fr.mo",
}

with zipfile.ZipFile(
    PLUGIN_NAME,
    "w",
    zipfile.ZIP_DEFLATED
) as z:

    for source, target in FILES.items():
        z.write(source, target)

print("Créé :", PLUGIN_NAME)
