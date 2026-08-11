# -*- coding: utf-8 -*-

# ======================================================================
# INTERNATIONALISATION CALIBRE
# ======================================================================

from calibre.customize.zipplugin import load_translations

# Dans un plugin Calibre installé, __file__ ressemble à :
# /.../Xteink X3.zip/action.py
#
# load_translations() attend le chemin du ZIP.
_plugin_zip = __file__.split(".zip/")[0] + ".zip"

load_translations(
    globals(),
    _plugin_zip,
)

# ======================================================================
# CALIBRE / QT
# ======================================================================

import os

from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import info_dialog, error_dialog

from qt.core import (
    QInputDialog,
    QThread,
    pyqtSignal,
    QProgressDialog,
    QMessageBox,
    QMenu,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QLabel,
    QScrollArea,
    QWidget,
    QPlainTextEdit,
    QApplication,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QListWidget,
)

from .network import (
    get_info,
    upload,
    scan_network,
    load_saved_ip,
    save_ip,
    load_devices,
    save_device,
    delete_device,
    list_files,
    delete_file,
    download_file,
    verify_file_exists,
    clean_info_field,
    find_duplicates,
    XteinkError,
)


# ======================================================================
# CONVERSION
# ======================================================================

# Ordre de préférence des formats déjà présents dans Calibre à utiliser
# comme source de conversion quand aucun EPUB n'existe. Les formats en
# tête donnent généralement une meilleure conversion vers EPUB que le
# PDF (mise en page fixe, peu adapté à un e-reader).
CONVERSION_SOURCE_PRIORITY = (
    "AZW3",
    "MOBI",
    "AZW",
    "FB2",
    "DOCX",
    "ODT",
    "RTF",
    "HTMLZ",
    "HTML",
    "TXT",
    "PDF",
)


class ConversionWorker(QThread):

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, to_convert, parent=None):
        super().__init__(parent)

        # Liste de (filename, source_path, source_format)
        self.to_convert = to_convert

    def run(self):

        # Import différé : Plumber tire pas mal de dépendances de
        # conversion Calibre, inutile de payer ce coût au démarrage
        # du plugin alors que la conversion est un cas rare.
        import tempfile

        from calibre.ebooks.conversion.plumber import Plumber
        from calibre.utils.logging import Log

        converted = []
        temp_files = []

        try:

            for filename, source_path, source_format in self.to_convert:

                fd, tmp_path = tempfile.mkstemp(
                    suffix=".epub",
                    prefix="xteink_x3_",
                )

                os.close(fd)

                temp_files.append(tmp_path)

                log = Log()

                plumber = Plumber(
                    source_path,
                    tmp_path,
                    log,
                )

                plumber.run()

                converted.append(
                    (
                        filename,
                        tmp_path,
                    )
                )

            self.finished.emit(converted)

        except Exception as e:

            # Conversion ratée : on nettoie les fichiers temporaires
            # déjà produits avant de faire remonter l'erreur.
            for tmp_path in temp_files:

                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            self.failed.emit(str(e))


# ======================================================================
# ENVOI
# ======================================================================

class UploadWorker(QThread):

    finished = pyqtSignal(int, str, str, str, list)
    failed = pyqtSignal(str)
    progress_updated = pyqtSignal(int)

    def __init__(self, ip, books, target_folder=None, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.books = books
        self.target_folder = target_folder

    def run(self):

        sent_books = 0
        unverified_books = []

        try:

            info = get_info(self.ip)

            version = clean_info_field(
                info,
                "Version",
                _("unknown"),
            )

            device_id = clean_info_field(
                info,
                "ID",
                _("unknown"),
            )

            # Taille totale de tous les livres à envoyer, pour calculer
            # un pourcentage global plutôt qu'un pourcentage par fichier
            # (sinon la barre repartirait de 0% à chaque livre).
            total_bytes = sum(
                os.path.getsize(epub)
                for _filename, epub in self.books
            ) or 1

            cumulative_sent = 0

            for filename, epub in self.books:

                book_size = os.path.getsize(epub)

                def on_progress(sent, total, base=cumulative_sent):

                    percent = int(
                        (base + sent) / total_bytes * 100
                    )

                    self.progress_updated.emit(percent)

                upload(
                    self.ip,
                    filename,
                    epub,
                    progress_callback=on_progress,
                    target_folder=self.target_folder,
                )

                # Le firmware peut répondre "OK" en HTTP sans avoir
                # réellement écrit le fichier (observé en pratique avec
                # un dossier cible inexistant) : on ne déclare un envoi
                # réussi qu'après l'avoir confirmé par une relecture du
                # dossier concerné.
                basename = os.path.basename(filename)

                verified = verify_file_exists(
                    self.ip,
                    self.target_folder,
                    basename,
                )

                if verified is False:

                    unverified_books.append(filename)

                else:

                    # True (confirmé) ou None (impossible à vérifier,
                    # ex. connexion perdue juste après l'envoi) : dans
                    # le doute on ne le compte pas comme un échec avéré,
                    # seul un "False" explicite (fichier absent) l'est.
                    sent_books += 1

                cumulative_sent += book_size

            self.finished.emit(
                sent_books,
                self.ip,
                version,
                device_id,
                unverified_books,
            )

        except Exception as e:

            self.failed.emit(str(e))


# ======================================================================
# SCAN
# ======================================================================

class ScanWorker(QThread):

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):

        try:

            results = scan_network()

            self.finished.emit(results)

        except Exception as e:

            self.failed.emit(str(e))


# ======================================================================
# LISTE DES FICHIERS
# ======================================================================

class ListFilesWorker(QThread):

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, ip, directory="/", parent=None):
        super().__init__(parent)

        self.ip = ip
        self.directory = directory

    def run(self):

        try:

            files = list_files(
                self.ip,
                self.directory,
            )

            self.finished.emit(files)

        except Exception as e:

            self.failed.emit(str(e))


# ======================================================================
# SUPPRESSION
# ======================================================================

class DeleteWorker(QThread):

    finished = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, ip, paths, parent=None):
        super().__init__(parent)

        self.ip = ip
        self.paths = paths

    def run(self):

        deleted = 0

        try:

            for path in self.paths:

                deleted += self.delete_tree(path)

            self.finished.emit(deleted)

        except Exception as e:

            self.failed.emit(str(e))

    def delete_tree(self, path):

        """
        Delete a file or directory recursively.

        The Xteink refuses to delete a non-empty directory.
        Therefore, directory contents are deleted first.
        """

        try:

            items = list_files(
                self.ip,
                path,
            )

        except NotADirectoryError:

            # Réponse non-JSON : ce chemin est un fichier,
            # pas un dossier. Cas normal, on le supprime directement.
            delete_file(
                self.ip,
                path,
            )

            return 1

        # Toute autre exception (XteinkError réseau, timeout,
        # appareil injoignable...) n'est PAS interceptée ici :
        # elle remonte jusqu'à run(), qui émet le signal "failed"
        # avec un message clair, au lieu d'être masquée par une
        # tentative de suppression qui échouerait de toute façon.

        deleted = 0

        for item in items:

            if not isinstance(item, dict):
                continue

            name = item.get(
                "name",
                "",
            )

            item_type = item.get(
                "type",
                "",
            )

            if not name:
                continue

            child_path = (
                path.rstrip("/")
                + "/"
                + name
            )

            if item_type == "dir":

                deleted += self.delete_tree(
                    child_path,
                )

            else:

                delete_file(
                    self.ip,
                    child_path,
                )

                deleted += 1

        # The directory is now empty.
        delete_file(
            self.ip,
            path,
        )

        deleted += 1

        return deleted


# ======================================================================
# DIALOGUE DE GESTION
# ======================================================================

# Dossiers systèmes du firmware Xteink à ne jamais proposer à la
# suppression (ni dans le dialogue de gestion, ni dans "vider
# l'appareil") : les effacer casserait le fonctionnement du firmware.
PROTECTED_SYSTEM_FOLDERS = {
    "XTCache",
}


class XteinkFilesDialog(QDialog):

    def __init__(self, parent, files):

        super().__init__(parent)

        self.files = files
        self.checkboxes = []

        self.setWindowTitle(
            _("X3 reader management"),
        )

        self.resize(
            650,
            550,
        )

        layout = QVBoxLayout(self)

        label = QLabel(
            _("Select the files or folders to delete:"),
        )

        layout.addWidget(label)

        # --------------------------------------------------------------
        # Scroll area
        # --------------------------------------------------------------

        scroll = QScrollArea()

        scroll.setWidgetResizable(True)

        container = QWidget()

        self.files_layout = QVBoxLayout(
            container,
        )

        self.files_layout.setContentsMargins(
            8,
            8,
            8,
            8,
        )

        self.populate()

        self.files_layout.addStretch()

        scroll.setWidget(container)

        layout.addWidget(scroll)

        # --------------------------------------------------------------
        # Buttons
        # --------------------------------------------------------------

        buttons = QHBoxLayout()

        select_all = QPushButton(
            _("Select all"),
        )

        select_none = QPushButton(
            _("Select none"),
        )

        delete_button = QPushButton(
            _("Delete"),
        )

        cancel_button = QPushButton(
            _("Cancel"),
        )

        select_all.clicked.connect(
            self.select_all,
        )

        select_none.clicked.connect(
            self.select_none,
        )

        delete_button.clicked.connect(
            self.accept,
        )

        cancel_button.clicked.connect(
            self.reject,
        )

        buttons.addWidget(select_all)
        buttons.addWidget(select_none)

        buttons.addStretch()

        buttons.addWidget(delete_button)
        buttons.addWidget(cancel_button)

        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------

    def populate(self):

        for item in self.files:

            if not isinstance(item, dict):
                continue

            name = item.get(
                "name",
                "",
            )

            item_type = item.get(
                "type",
                "",
            )

            size = item.get(
                "size",
                0,
            )

            if not name:
                continue

            if item_type == "dir":

                text = "📁 %s" % name

                checkbox = QCheckBox(text)

                # Protect the Xteink system cache.
                if name in PROTECTED_SYSTEM_FOLDERS:

                    checkbox.setChecked(False)

                    checkbox.setEnabled(False)

                    checkbox.setToolTip(
                        _("Xteink X3 system folder"),
                    )

            else:

                try:

                    size_mb = (
                        float(size)
                        / (1024 * 1024)
                    )

                    text = _(
                        "📄 %s  (%.1f MB)",
                    ) % (
                        name,
                        size_mb,
                    )

                except Exception:

                    text = _(
                        "📄 %s",
                    ) % name

                checkbox = QCheckBox(text)

            checkbox._xteink_item = item

            self.checkboxes.append(checkbox)

            self.files_layout.addWidget(checkbox)

    # ------------------------------------------------------------------
    # Sélection
    # ------------------------------------------------------------------

    def select_all(self):

        for checkbox in self.checkboxes:

            if checkbox.isEnabled():

                checkbox.setChecked(True)

    def select_none(self):

        for checkbox in self.checkboxes:

            checkbox.setChecked(False)

    # ------------------------------------------------------------------
    # Résultat
    # ------------------------------------------------------------------

    def selected_items(self):

        result = []

        for checkbox in self.checkboxes:

            if not checkbox.isChecked():
                continue

            item = getattr(
                checkbox,
                "_xteink_item",
                None,
            )

            if item:

                result.append(item)

        return result


# ======================================================================
# ACTION CALIBRE
# ======================================================================

# ======================================================================
# EXPLORATION (DEBUG / RÉTRO-INGÉNIERIE)
# ======================================================================

class ExploreWorker(QThread):
    """
    Parcourt récursivement l'arborescence du Xteink X3 et construit un
    arbre texte indenté. Outil de diagnostic : utile par exemple pour
    repérer où (et si) le firmware stocke une progression de lecture,
    en l'absence de toute documentation sur le sujet.
    """

    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    # Profondeur maximale de parcours, pour éviter un scan infini en
    # cas de structure de fichiers inattendue (boucle, dossier
    # generated dynamiquement, etc.)
    MAX_DEPTH = 6

    def __init__(self, ip, parent=None):
        super().__init__(parent)
        self.ip = ip

    def run(self):

        lines = []

        try:

            self.walk(
                "/",
                0,
                lines,
            )

            self.finished.emit(
                "\n".join(lines)
            )

        except Exception as e:

            self.failed.emit(str(e))

    def walk(self, path, depth, lines):

        if depth > self.MAX_DEPTH:

            lines.append(
                ("  " * depth) + "… (profondeur maximale atteinte)"
            )

            return

        try:

            items = list_files(
                self.ip,
                path,
            )

        except NotADirectoryError:

            return

        if not isinstance(items, list):
            return

        items = sorted(
            items,
            key=lambda x: (
                0 if x.get("type") == "dir" else 1,
                x.get("name", "").lower(),
            )
        )

        for item in items:

            name = item.get(
                "name",
                "",
            )

            if not name:
                continue

            item_type = item.get(
                "type",
                "",
            )

            size = item.get(
                "size",
                "",
            )

            indent = "  " * depth

            if item_type == "dir":

                lines.append(
                    "%s📁 %s/" % (
                        indent,
                        name,
                    )
                )

                child_path = (
                    path.rstrip("/") + "/" + name
                )

                self.walk(
                    child_path,
                    depth + 1,
                    lines,
                )

            else:

                file_path = (
                    path.rstrip("/") + "/" + name
                )

                lines.append(
                    "%s📄 %s (%s)  →  %s" % (
                        indent,
                        name,
                        size,
                        file_path,
                    )
                )


class DownloadFileWorker(QThread):

    finished = pyqtSignal(bytes)
    failed = pyqtSignal(str)

    def __init__(self, ip, path, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.path = path

    def run(self):

        try:

            content = download_file(
                self.ip,
                self.path,
            )

            self.finished.emit(content)

        except Exception as e:

            self.failed.emit(str(e))


class ExploreDialog(QDialog):

    def __init__(self, parent, ip, tree_text):
        super().__init__(parent)

        self.ip = ip
        self.preview_worker = None

        self.setWindowTitle(
            _("Xteink X3 filesystem (debug)"),
        )

        self.resize(700, 650)

        layout = QVBoxLayout(self)

        info_label = QLabel(
            _(
                "Full recursive listing of the Xteink X3's storage. "
                "Mainly useful for troubleshooting or looking for "
                "undocumented files (e.g. a reading-progress file)."
            )
        )

        info_label.setWordWrap(True)

        layout.addWidget(info_label)

        self.text_edit = QPlainTextEdit(tree_text)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )

        layout.addWidget(self.text_edit)

        button_layout = QHBoxLayout()

        copy_button = QPushButton(
            _("Copy to clipboard"),
        )

        copy_button.clicked.connect(
            self.copy_to_clipboard,
        )

        close_button = QPushButton(
            _("Close"),
        )

        close_button.clicked.connect(
            self.accept,
        )

        button_layout.addWidget(copy_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

        # --------------------------------------------------------------
        # Aperçu du contenu d'un fichier (le chemin complet de chaque
        # fichier est indiqué après la flèche "→" dans l'arbre ci-dessus,
        # copiable-collable directement ici).
        # --------------------------------------------------------------

        preview_label = QLabel(
            _(
                "File path to preview (copy it from the tree above, "
                "after the \"→\"):"
            )
        )

        preview_label.setWordWrap(True)

        layout.addWidget(preview_label)

        preview_input_layout = QHBoxLayout()

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText(
            "/XTCache/epub/.../progress.txt"
        )

        preview_button = QPushButton(
            _("Preview"),
        )

        preview_button.clicked.connect(
            self.start_preview,
        )

        preview_input_layout.addWidget(self.path_input)
        preview_input_layout.addWidget(preview_button)

        layout.addLayout(preview_input_layout)

        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setMaximumHeight(150)
        self.preview_edit.setPlaceholderText(
            _("File content will appear here.")
        )

        layout.addWidget(self.preview_edit)

    def start_preview(self):

        path = self.path_input.text().strip()

        if not path:
            return

        self.preview_edit.setPlainText(
            _("Loading…")
        )

        self.preview_worker = DownloadFileWorker(
            self.ip,
            path,
            self,
        )

        self.preview_worker.finished.connect(
            self.preview_finished,
        )

        self.preview_worker.failed.connect(
            self.preview_failed,
        )

        self.preview_worker.start()

    def preview_finished(self, content):

        self.preview_worker = None

        # On tente un décodage texte (UTF-8 puis latin-1 en repli) ;
        # si le fichier est binaire, on retombe sur une représentation
        # hexadécimale plutôt que de planter ou d'afficher du charabia.
        try:

            text = content.decode("utf-8")

        except UnicodeDecodeError:

            try:

                text = content.decode("latin-1")

            except UnicodeDecodeError:

                text = content[:512].hex(" ")

                text = _(
                    "(binary content, showing first bytes as hex)\n\n"
                ) + text

        self.preview_edit.setPlainText(text)

    def preview_failed(self, message):

        self.preview_worker = None

        self.preview_edit.setPlainText(
            _("Error: %s") % message
        )

    def copy_to_clipboard(self):

        QApplication.clipboard().setText(
            self.text_edit.toPlainText()
        )


# ======================================================================
# PROGRESSION DE LECTURE (basé sur XTCache/, non documenté par Xteink)
# ======================================================================

class ReadingProgressWorker(QThread):
    """
    Lit XTCache/epub/<livre>/progress.txt (et quelques fichiers voisins)
    pour chaque livre suivi par le firmware, afin d'afficher une
    progression de lecture côté Calibre.

    Format déduit par observation (non documenté par Xteink) :
    - progress.txt : 2 lignes, "% dans le chapitre courant" puis
      "% dans l'ensemble du livre".
    - 阅读记录.txt ("registre de lecture") : ligne 2 = titre du
      chapitre courant.
    - readTime/epub/<livre>/readTime.txt : temps de lecture cumulé,
      en secondes.
    """

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, ip, parent=None):
        super().__init__(parent)
        self.ip = ip

    def run(self):

        try:

            try:

                entries = list_files(
                    self.ip,
                    "/XTCache/epub",
                )

            except NotADirectoryError:

                # Le dossier peut ne pas exister (aucun livre encore
                # ouvert sur l'appareil) : ce n'est pas une erreur.
                entries = []

            if not isinstance(entries, list):
                entries = []

            results = []

            for item in entries:

                if not isinstance(item, dict):
                    continue

                if item.get("type") != "dir":
                    continue

                name = item.get(
                    "name",
                    "",
                )

                if not name:
                    continue

                book_percent = None
                chapter_percent = None
                chapter_title = None
                read_time_seconds = None

                try:

                    raw = download_file(
                        self.ip,
                        "/XTCache/epub/%s/progress.txt" % name,
                    )

                    lines = raw.decode(
                        "utf-8",
                        errors="replace",
                    ).strip().splitlines()

                    if len(lines) >= 1:
                        chapter_percent = float(lines[0].strip())

                    if len(lines) >= 2:
                        book_percent = float(lines[1].strip())

                except Exception:
                    pass

                try:

                    raw = download_file(
                        self.ip,
                        "/XTCache/epub/%s/阅读记录.txt" % name,
                    )

                    lines = raw.decode(
                        "utf-8",
                        errors="replace",
                    ).splitlines()

                    if len(lines) >= 2:
                        chapter_title = lines[1].strip()

                except Exception:
                    pass

                try:

                    raw = download_file(
                        self.ip,
                        "/XTCache/readTime/epub/%s/readTime.txt" % name,
                    )

                    read_time_seconds = int(
                        raw.decode(
                            "utf-8",
                            errors="replace",
                        ).strip()
                    )

                except Exception:
                    pass

                results.append(
                    {
                        "title": name,
                        "book_percent": book_percent,
                        "chapter_percent": chapter_percent,
                        "chapter_title": chapter_title,
                        "read_time_seconds": read_time_seconds,
                    }
                )

            results.sort(
                key=lambda r: r["title"].lower()
            )

            self.finished.emit(results)

        except Exception as e:

            self.failed.emit(str(e))


def format_read_time(seconds):

    if seconds is None:
        return "—"

    minutes = seconds // 60
    hours = minutes // 60
    minutes = minutes % 60

    if hours:
        return "%d h %02d min" % (hours, minutes)

    return "%d min" % minutes


def format_percent(value):

    if value is None:
        return "—"

    return "%.1f %%" % value


class ReadingProgressDialog(QDialog):

    def __init__(self, parent, results):
        super().__init__(parent)

        self.setWindowTitle(
            _("Reading progress (X3)"),
        )

        self.resize(750, 400)

        layout = QVBoxLayout(self)

        info_label = QLabel(
            _(
                "Reading progress as tracked by the Xteink X3 itself, "
                "based on undocumented internal files — treat the "
                "exact percentages as approximate."
            )
        )

        info_label.setWordWrap(True)

        layout.addWidget(info_label)

        table = QTableWidget()

        table.setColumnCount(4)

        table.setHorizontalHeaderLabels(
            [
                _("Book"),
                _("Overall progress"),
                _("Current chapter"),
                _("Chapter progress"),
            ]
        )

        table.setRowCount(
            len(results),
        )

        table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers,
        )

        for row, entry in enumerate(results):

            table.setItem(
                row,
                0,
                QTableWidgetItem(entry["title"]),
            )

            table.setItem(
                row,
                1,
                QTableWidgetItem(
                    format_percent(entry["book_percent"])
                ),
            )

            table.setItem(
                row,
                2,
                QTableWidgetItem(
                    entry["chapter_title"] or "—"
                ),
            )

            table.setItem(
                row,
                3,
                QTableWidgetItem(
                    format_percent(entry["chapter_percent"])
                ),
            )

        table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )

        layout.addWidget(table)

        # Temps de lecture cumulé en bonus, sous forme de résumé texte
        # (pas de colonne dédiée pour ne pas surcharger le tableau).
        time_lines = [
            "%s — %s"
            % (
                entry["title"],
                format_read_time(entry["read_time_seconds"]),
            )
            for entry in results
            if entry["read_time_seconds"] is not None
        ]

        if time_lines:

            time_label = QLabel(
                _("Cumulative reading time:")
            )

            layout.addWidget(time_label)

            time_text = QPlainTextEdit(
                "\n".join(time_lines)
            )

            time_text.setReadOnly(True)
            time_text.setMaximumHeight(100)

            layout.addWidget(time_text)

        close_button = QPushButton(
            _("Close"),
        )

        close_button.clicked.connect(
            self.accept,
        )

        layout.addWidget(close_button)


# ======================================================================
# APPAREILS NOMMÉS
# ======================================================================

class DeviceManagerDialog(QDialog):

    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowTitle(
            _("Saved Xteink X3 devices"),
        )

        self.resize(420, 320)

        self.devices = []

        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()

        layout.addWidget(self.list_widget)

        self.refresh()

        button_layout = QHBoxLayout()

        rename_button = QPushButton(
            _("Rename"),
        )

        rename_button.clicked.connect(
            self.rename_selected,
        )

        delete_button = QPushButton(
            _("Delete"),
        )

        delete_button.clicked.connect(
            self.delete_selected,
        )

        close_button = QPushButton(
            _("Close"),
        )

        close_button.clicked.connect(
            self.accept,
        )

        button_layout.addWidget(rename_button)
        button_layout.addWidget(delete_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

    def refresh(self):

        self.list_widget.clear()

        self.devices = load_devices()

        for device in self.devices:

            self.list_widget.addItem(
                "%s  —  %s" % (
                    device["name"],
                    device["ip"],
                )
            )

    def selected_device(self):

        row = self.list_widget.currentRow()

        if row < 0 or row >= len(self.devices):
            return None

        return self.devices[row]

    def rename_selected(self):

        device = self.selected_device()

        if not device:
            return

        new_name, ok = QInputDialog.getText(
            self,
            _("X3 reader management"),
            _("New name:"),
            text=device["name"],
        )

        if not ok or not new_name.strip():
            return

        new_name = new_name.strip()

        if new_name == device["name"]:
            return

        delete_device(device["name"])
        save_device(new_name, device["ip"])

        self.refresh()

    def delete_selected(self):

        device = self.selected_device()

        if not device:
            return

        answer = QMessageBox.question(
            self,
            _("Confirmation"),
            _('Delete "%s"?') % device["name"],
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        delete_device(device["name"])

        self.refresh()


class XteinkX3Action(InterfaceAction):

    name = "Xteink X3"

    action_spec = (
        _("X3 reader management"),
        None,
        _("Manage books on the Xteink X3"),
        "Ctrl+Shift+X",
    )

    def genesis(self):

        icon = get_icons(
            "images/xteink_x3.png",
            "X3 reader management",
        )

        self.qaction.setIcon(icon)

        self.qaction.triggered.connect(
            self.send_to_x3,
        )

        self.worker = None
        self.scan_worker = None
        self.list_worker = None
        self.empty_list_worker = None
        self.dup_check_worker = None
        self.conversion_worker = None
        self.explore_worker = None
        self.reading_progress_worker = None
        self.folder_list_worker = None
        self.delete_worker = None
        self.progress = None

        self.pending_ids = None
        self.pending_operation = None
        self.pending_upload_ip = None
        self.pending_upload_books = None
        self.pending_upload_target_folder = None
        self.pending_ready_books = None
        self.pending_temp_files = []
        self.pending_explore_ip = None

        # --------------------------------------------------------------
        # Menu
        # --------------------------------------------------------------

        menu = QMenu(
            _("X3 reader management"),
            self.gui,
        )

        send_action = menu.addAction(
            _("Send to Xteink X3"),
        )

        manage_action = menu.addAction(
            _("Manage books on X3"),
        )

        empty_action = menu.addAction(
            _("Empty Xteink X3…"),
        )

        menu.addSeparator()

        explore_action = menu.addAction(
            _("Explore Xteink X3 filesystem (debug)…"),
        )

        progress_action = menu.addAction(
            _("Reading progress (X3)…"),
        )

        menu.addSeparator()

        devices_action = menu.addAction(
            _("Manage saved devices…"),
        )

        send_action.triggered.connect(
            self.send_to_x3,
        )

        manage_action.triggered.connect(
            self.manage_x3,
        )

        empty_action.triggered.connect(
            self.empty_x3,
        )

        explore_action.triggered.connect(
            self.explore_x3,
        )

        devices_action.triggered.connect(
            self.manage_devices,
        )

        progress_action.triggered.connect(
            self.reading_progress_x3,
        )

        self.qaction.setMenu(menu)

    # ==================================================================
    # CHOIX DU XTEINK
    # ==================================================================

    def choose_xteink(self, operation):

        self.pending_operation = operation

        devices = load_devices()

        if not devices:

            return self.choose_xteink_legacy(operation)

        if len(devices) == 1:

            device = devices[0]

            answer = QMessageBox.question(
                self.gui,
                _("X3 reader management"),
                _('Use "%s" (%s)?') % (
                    device["name"],
                    device["ip"],
                ),
                QMessageBox.Yes
                | QMessageBox.No
                | QMessageBox.Cancel,
                QMessageBox.Yes,
            )

            if answer == QMessageBox.Yes:
                return device["ip"]

            if answer == QMessageBox.Cancel:

                self.pending_operation = None

                return None

            # No : proposer un autre choix (scan, IP manuelle, gestion)
            return self.choose_xteink_other(
                operation,
                devices,
            )

        return self.choose_xteink_other(
            operation,
            devices,
        )

    def choose_xteink_other(self, operation, devices):

        scan_label = _("Scan the network...")
        manual_label = _("Enter IP manually...")
        manage_label = _("Manage saved devices...")

        labels = [
            "%s  —  %s" % (
                device["name"],
                device["ip"],
            )
            for device in devices
        ]

        labels += [
            scan_label,
            manual_label,
            manage_label,
        ]

        selected, ok = QInputDialog.getItem(
            self.gui,
            _("X3 reader management"),
            _("Choose a Xteink X3:"),
            labels,
            0,
            False,
        )

        if not ok:

            self.pending_operation = None

            return None

        if selected == scan_label:

            self.start_scan()

            return None

        if selected == manual_label:

            return self.ask_manual_ip(operation)

        if selected == manage_label:

            self.pending_operation = None

            self.manage_devices()

            return None

        index = labels.index(selected)

        return devices[index]["ip"]

    def choose_xteink_legacy(self, operation):

        saved_ip = load_saved_ip()

        if saved_ip:

            answer = QMessageBox.question(
                self.gui,
                _("X3 reader management"),
                _(
                    "Saved Xteink address:\n\n"
                    "%s\n\n"
                    "Do you want to use this address?"
                ) % saved_ip,
                QMessageBox.Yes
                | QMessageBox.No
                | QMessageBox.Cancel,
                QMessageBox.Yes,
            )

            if answer == QMessageBox.Yes:
                return saved_ip

            if answer == QMessageBox.Cancel:

                self.pending_operation = None

                return None

        else:

            answer = QMessageBox.question(
                self.gui,
                _("X3 reader management"),
                _(
                    "No Xteink X3 is saved.\n\n"
                    "Do you want to scan the network?"
                ),
                QMessageBox.Yes
                | QMessageBox.No
                | QMessageBox.Cancel,
                QMessageBox.Yes,
            )

            if answer != QMessageBox.Yes:

                if answer == QMessageBox.No:

                    return self.ask_manual_ip(operation)

                self.pending_operation = None

                return None

        self.start_scan()

        return None

    def maybe_save_new_device(self, ip):

        # On ne propose de nommer l'appareil que s'il n'est pas déjà
        # connu sous un nom existant — pas la peine de redemander à
        # chaque connexion à un appareil déjà mémorisé.
        devices = load_devices()

        if any(device["ip"] == ip for device in devices):
            return

        name, ok = QInputDialog.getText(
            self.gui,
            _("X3 reader management"),
            _(
                "Name this Xteink X3 (leave empty to skip saving it):"
            ),
            text=ip,
        )

        if ok and name.strip():

            save_device(
                name.strip(),
                ip,
            )

    def manage_devices(self):

        dialog = DeviceManagerDialog(
            self.gui,
        )

        dialog.exec()

    def ask_manual_ip(self, operation):

        ip, ok = QInputDialog.getText(
            self.gui,
            _("X3 reader management"),
            _("Xteink X3 IP address:"),
        )

        if not ok or not ip.strip():

            self.pending_operation = None

            return None

        ip = ip.strip()

        save_ip(ip)

        self.maybe_save_new_device(ip)

        self.pending_operation = operation

        return ip

    # ==================================================================
    # SCAN
    # ==================================================================

    def start_scan(self):

        self.progress = QProgressDialog(
            _("Searching for Xteink X3 on the network..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)

        self.progress.setCancelButton(None)

        self.progress.show()

        self.scan_worker = ScanWorker(self.gui)

        self.scan_worker.finished.connect(
            self.scan_finished,
        )

        self.scan_worker.failed.connect(
            self.scan_failed,
        )

        self.scan_worker.start()

    def scan_finished(self, results):

        if self.progress:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

        self.scan_worker = None

        if not results:

            answer = QMessageBox.question(
                self.gui,
                _("X3 reader management"),
                _(
                    "No Xteink X3 found.\n\n"
                    "Do you want to enter an IP address manually?"
                ),
                QMessageBox.Yes
                | QMessageBox.No,
                QMessageBox.Yes,
            )

            if answer == QMessageBox.Yes:

                ip = self.ask_manual_ip(
                    self.pending_operation,
                )

                if ip:

                    self.operation_with_ip(ip)

            else:

                self.pending_operation = None

            return

        # --------------------------------------------------------------
        # One Xteink
        # --------------------------------------------------------------

        if len(results) == 1:

            ip, info = results[0]

            version = clean_info_field(
                info,
                "Version",
            )

            device_id = clean_info_field(
                info,
                "ID",
            )

            answer = QMessageBox.question(
                self.gui,
                _("Xteink X3 found"),
                _(
                    "Xteink X3 found:\n\n"
                    "IP: %s\n"
                    "Version: %s\n"
                    "ID: %s\n\n"
                    "Use this Xteink?"
                ) % (
                    ip,
                    version,
                    device_id,
                ),
                QMessageBox.Yes
                | QMessageBox.No,
                QMessageBox.Yes,
            )

            if answer == QMessageBox.Yes:

                save_ip(ip)

                self.maybe_save_new_device(ip)

                self.operation_with_ip(ip)

            else:

                self.pending_operation = None

            return

        # --------------------------------------------------------------
        # Several Xteinks
        # --------------------------------------------------------------

        labels = []

        for ip, info in results:

            version = clean_info_field(
                info,
                "Version",
            )

            device_id = clean_info_field(
                info,
                "ID",
            )

            labels.append(
                "%s — %s — ID %s"
                % (
                    ip,
                    version,
                    device_id,
                )
            )

        selected, ok = QInputDialog.getItem(
            self.gui,
            _("X3 reader management"),
            _("Several Xteink devices found:"),
            labels,
            0,
            False,
        )

        if not ok:

            self.pending_operation = None

            return

        index = labels.index(selected)

        ip = results[index][0]

        save_ip(ip)

        self.maybe_save_new_device(ip)

        self.operation_with_ip(ip)

    def scan_failed(self, message):

        if self.progress:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

        self.scan_worker = None
        self.pending_operation = None

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while searching:\n\n%s") % message,
            show=True,
        )

    # ==================================================================
    # OPERATION APRES CHOIX
    # ==================================================================

    def operation_with_ip(self, ip):

        operation = self.pending_operation

        self.pending_operation = None

        if operation == "send":

            self.start_upload(ip)

        elif operation == "manage":

            self.start_list_files(ip)

        elif operation == "empty":

            self.start_empty_list(ip)

        elif operation == "explore":

            self.explore_start_with_ip(ip)

        elif operation == "progress":

            self.reading_progress_start_with_ip(ip)

    # ==================================================================
    # ENVOI
    # ==================================================================

    def send_to_x3(self):

        ids = self.gui.library_view.get_selected_ids()

        if not ids:

            info_dialog(
                self.gui,
                _("X3 reader management"),
                _("No book selected."),
                show=True,
            )

            return

        self.pending_ids = list(ids)

        answer = QMessageBox.information(
            self.gui,
            _("X3 reader management"),
            _(
                "Please put the Xteink X3 into\n"
                '"PC Transfer" mode.\n\n'
                "Once the mode is active, click OK."
            ),
            QMessageBox.Ok
            | QMessageBox.Cancel,
            QMessageBox.Ok,
        )

        if answer != QMessageBox.Ok:

            self.pending_ids = None

            return

        ip = self.choose_xteink("send")

        if ip:

            self.start_upload(ip)

    def start_upload(self, ip):

        ids = self.pending_ids

        if not ids:
            return

        self.qaction.setEnabled(False)

        self.pending_upload_ip = ip

        self.progress = QProgressDialog(
            _("Listing folders on the Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.folder_list_worker = ListFilesWorker(
            ip,
            "/",
            self.gui,
        )

        self.folder_list_worker.finished.connect(
            self.folder_choice_finished,
        )

        self.folder_list_worker.failed.connect(
            self.folder_choice_failed,
        )

        self.folder_list_worker.start()

    def folder_choice_finished(self, files):

        self.folder_list_worker = None

        self.close_progress()

        ip = self.pending_upload_ip

        folders = []

        if isinstance(files, list):

            for item in files:

                if not isinstance(item, dict):
                    continue

                if item.get("type") != "dir":
                    continue

                name = item.get(
                    "name",
                    "",
                )

                if not name:
                    continue

                if name in PROTECTED_SYSTEM_FOLDERS:
                    continue

                folders.append(name)

        folders.sort(
            key=str.lower,
        )

        root_label = _("(Root — no folder)")

        labels = [root_label] + folders

        selected, ok = QInputDialog.getItem(
            self.gui,
            _("X3 reader management"),
            _("Send to which folder on the Xteink X3?"),
            labels,
            0,
            False,
        )

        if not ok:

            self.qaction.setEnabled(True)

            return

        if selected == root_label:

            target_folder = None

        else:

            target_folder = selected

        self.continue_upload_with_folder(
            ip,
            target_folder,
        )

    def folder_choice_failed(self, message):

        self.folder_list_worker = None

        self.close_progress()

        self.qaction.setEnabled(True)

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while listing folders:\n\n%s") % message,
            show=True,
        )

    def continue_upload_with_folder(self, ip, target_folder):

        ids = self.pending_ids

        if not ids:
            return

        ready_books = []
        to_convert = []

        for book_id in ids:

            try:

                mi = self.gui.current_db.get_metadata(
                    book_id,
                    index_is_id=True,
                )

                title = mi.title or _("Book")

            except Exception:

                title = _("Book")

            safe_title = title.strip()

            for char in ':\\/*?"<>|':

                safe_title = safe_title.replace(
                    char,
                    "_",
                )

            filename = safe_title + ".epub"

            try:

                epub = self.gui.current_db.format(
                    book_id,
                    "EPUB",
                    as_path=True,
                    index_is_id=True,
                )

            except Exception as e:

                error_dialog(
                    self.gui,
                    _("X3 reader management"),
                    _("Unable to retrieve the EPUB file.\n\n%s") % e,
                    show=True,
                )

                continue

            if epub:

                ready_books.append(
                    (
                        filename,
                        epub,
                    )
                )

                continue

            # Pas de format EPUB disponible : on cherche un autre
            # format déjà présent dans Calibre à convertir plutôt que
            # d'abandonner ce livre silencieusement.
            try:

                available = self.gui.current_db.formats(
                    book_id,
                    index_is_id=True,
                )

            except Exception:

                available = None

            available = [
                fmt.strip().upper()
                for fmt in (available or "").split(",")
                if fmt.strip()
            ]

            source_format = None

            for candidate in CONVERSION_SOURCE_PRIORITY:

                if candidate in available:

                    source_format = candidate

                    break

            if not source_format and available:

                source_format = available[0]

            if not source_format:

                error_dialog(
                    self.gui,
                    _("X3 reader management"),
                    _("The selected book has no EPUB format."),
                    show=True,
                )

                continue

            try:

                source_path = self.gui.current_db.format(
                    book_id,
                    source_format,
                    as_path=True,
                    index_is_id=True,
                )

            except Exception as e:

                error_dialog(
                    self.gui,
                    _("X3 reader management"),
                    _(
                        "Unable to retrieve the %s file.\n\n%s"
                    ) % (
                        source_format,
                        e,
                    ),
                    show=True,
                )

                continue

            to_convert.append(
                (
                    filename,
                    source_path,
                    source_format,
                )
            )

        if not ready_books and not to_convert:

            self.qaction.setEnabled(True)

            return

        save_ip(ip)

        if not to_convert:

            self.start_duplicate_check(
                ip,
                ready_books,
                target_folder,
            )

            return

        # Certains livres n'ont pas de format EPUB : on les convertit
        # d'abord (en arrière-plan) avant d'enchaîner sur la
        # vérification des doublons puis l'envoi.
        self.pending_upload_ip = ip
        self.pending_ready_books = ready_books
        self.pending_upload_target_folder = target_folder

        self.progress = QProgressDialog(
            _("Converting %d book(s) to EPUB...") % len(to_convert),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.conversion_worker = ConversionWorker(
            to_convert,
            self.gui,
        )

        self.conversion_worker.finished.connect(
            self.conversion_finished,
        )

        self.conversion_worker.failed.connect(
            self.conversion_failed,
        )

        self.conversion_worker.start()

    def conversion_finished(self, converted_books):

        self.conversion_worker = None

        self.close_progress()

        ip = self.pending_upload_ip

        books = self.pending_ready_books + converted_books

        # Les fichiers EPUB temporaires créés par la conversion sont
        # nettoyés une fois l'envoi terminé (avec succès ou non) : voir
        # upload_finished / upload_failed.
        self.pending_temp_files = [
            epub for _filename, epub in converted_books
        ]

        if not books:
            return

        self.start_duplicate_check(
            ip,
            books,
            self.pending_upload_target_folder,
        )

    def conversion_failed(self, message):

        self.conversion_worker = None

        self.close_progress()

        self.qaction.setEnabled(True)

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while converting books:\n\n%s") % message,
            show=True,
        )

    def start_duplicate_check(self, ip, books, target_folder=None):

        self.pending_upload_ip = ip
        self.pending_upload_books = books
        self.pending_upload_target_folder = target_folder

        self.progress = QProgressDialog(
            _("Checking for existing files on the Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        list_path = (
            "/" + target_folder.strip("/")
            if target_folder
            else "/"
        )

        self.dup_check_worker = ListFilesWorker(
            ip,
            list_path,
            self.gui,
        )

        self.dup_check_worker.finished.connect(
            self.duplicate_check_finished,
        )

        self.dup_check_worker.failed.connect(
            self.duplicate_check_failed,
        )

        self.dup_check_worker.start()

    def duplicate_check_finished(self, files):

        self.dup_check_worker = None

        self.close_progress()

        ip = self.pending_upload_ip
        books = self.pending_upload_books
        target_folder = self.pending_upload_target_folder

        filenames = [filename for filename, _epub in books]

        duplicates = find_duplicates(files, filenames)

        if not duplicates:

            self.begin_upload(ip, books, target_folder)

            return

        box = QMessageBox(self.gui)

        box.setWindowTitle(
            _("X3 reader management"),
        )

        box.setText(
            _(
                "%d book(s) already exist on the Xteink X3 with the "
                "same file name:\n\n%s\n\nWhat do you want to do?"
            ) % (
                len(duplicates),
                "\n".join(duplicates),
            )
        )

        overwrite_button = box.addButton(
            _("Overwrite"),
            QMessageBox.AcceptRole,
        )

        skip_button = box.addButton(
            _("Skip duplicates"),
            QMessageBox.DestructiveRole,
        )

        box.addButton(
            QMessageBox.Cancel,
        )

        box.setDefaultButton(skip_button)

        box.exec()

        clicked = box.clickedButton()

        if clicked == overwrite_button:

            self.begin_upload(ip, books, target_folder)

        elif clicked == skip_button:

            duplicate_set = set(
                name.lower() for name in duplicates
            )

            filtered_books = [
                (filename, epub)
                for filename, epub in books
                if filename.lower() not in duplicate_set
            ]

            if not filtered_books:

                self.qaction.setEnabled(True)

                self.cleanup_temp_files()

                info_dialog(
                    self.gui,
                    _("X3 reader management"),
                    _(
                        "All selected books already exist on "
                        "the Xteink X3."
                    ),
                    show=True,
                )

                return

            self.begin_upload(ip, filtered_books, target_folder)

        else:

            self.qaction.setEnabled(True)

            self.cleanup_temp_files()

    def duplicate_check_failed(self, message):

        self.dup_check_worker = None

        self.close_progress()

        # La vérification des doublons n'est pas critique : si elle
        # échoue (réseau, appareil qui répond bizarrement...), on
        # continue quand même l'envoi plutôt que de bloquer
        # l'utilisateur pour une fonctionnalité secondaire.
        print(
            "Xteink X3: vérification des doublons impossible, "
            "envoi sans cette vérification :",
            message,
        )

        self.begin_upload(
            self.pending_upload_ip,
            self.pending_upload_books,
            self.pending_upload_target_folder,
        )

    def begin_upload(self, ip, books, target_folder=None):

        self.progress = QProgressDialog(
            _("Sending books to Xteink X3... 0%"),
            None,
            0,
            100,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)
        self.progress.setValue(0)

        self.progress.show()

        self.worker = UploadWorker(
            ip,
            books,
            target_folder,
            self.gui,
        )

        self.worker.progress_updated.connect(
            self.upload_progress_updated,
        )

        self.worker.finished.connect(
            self.upload_finished,
        )

        self.worker.failed.connect(
            self.upload_failed,
        )

        self.worker.start()

    def upload_progress_updated(self, percent):

        if self.progress:

            self.progress.setValue(percent)

            self.progress.setLabelText(
                _("Sending books to Xteink X3... %d%%") % percent
            )

    # ==================================================================
    # GESTION
    # ==================================================================

    # ==================================================================
    # VIDER L'APPAREIL
    # ==================================================================

    def empty_x3(self):

        answer = QMessageBox.information(
            self.gui,
            _("X3 reader management"),
            _(
                "Please put the Xteink X3 into\n"
                '"PC Transfer" mode.\n\n'
                "Once the mode is active, click OK."
            ),
            QMessageBox.Ok
            | QMessageBox.Cancel,
            QMessageBox.Ok,
        )

        if answer != QMessageBox.Ok:
            return

        ip = self.choose_xteink("empty")

        if ip:

            self.start_empty_list(ip)

    def start_empty_list(self, ip):

        save_ip(ip)

        self.progress = QProgressDialog(
            _("Reading books stored on the Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.empty_list_worker = ListFilesWorker(
            ip,
            "/",
            self.gui,
        )

        self.empty_list_worker.finished.connect(
            lambda files, x=ip:
            self.empty_list_finished(x, files)
        )

        self.empty_list_worker.failed.connect(
            self.empty_list_failed,
        )

        self.empty_list_worker.start()

    def empty_list_finished(self, ip, files):

        self.empty_list_worker = None

        self.close_progress()

        if not isinstance(files, list):

            error_dialog(
                self.gui,
                _("X3 reader management"),
                _("Unexpected response from the Xteink X3."),
                show=True,
            )

            return

        # On exclut explicitement les dossiers système (ex. XTCache) :
        # "vider l'appareil" ne doit jamais y toucher, exactement comme
        # le dialogue de gestion les protège déjà.
        paths = []
        lines = []

        for item in files:

            if not isinstance(item, dict):
                continue

            name = item.get(
                "name",
                "",
            )

            if not name:
                continue

            if name in PROTECTED_SYSTEM_FOLDERS:
                continue

            item_type = item.get(
                "type",
                "",
            )

            if item_type not in ("file", "dir"):
                continue

            paths.append("/" + name)

            lines.append(
                ("📁 " if item_type == "dir" else "📄 ") + name
            )

        if not paths:

            info_dialog(
                self.gui,
                _("X3 reader management"),
                _("The Xteink X3 is already empty."),
                show=True,
            )

            return

        answer = QMessageBox.warning(
            self.gui,
            _("Confirmation"),
            _(
                "This will PERMANENTLY delete all %d item(s) "
                "from the Xteink X3:\n\n"
            ) % len(paths)
            + "\n".join(lines)
            + _(
                "\n\n"
                "This cannot be undone. Continue?"
            ),
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        self.start_delete(
            ip,
            paths,
        )

    def empty_list_failed(self, message):

        self.empty_list_worker = None

        self.close_progress()

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while reading files:\n\n%s") % message,
            show=True,
        )

    # ==================================================================
    # EXPLORATION (DEBUG)
    # ==================================================================

    def explore_x3(self):

        answer = QMessageBox.information(
            self.gui,
            _("X3 reader management"),
            _(
                "Please put the Xteink X3 into\n"
                '"PC Transfer" mode.\n\n'
                "Once the mode is active, click OK."
            ),
            QMessageBox.Ok
            | QMessageBox.Cancel,
            QMessageBox.Ok,
        )

        if answer != QMessageBox.Ok:
            return

        ip = self.choose_xteink("explore")

        if not ip:
            return

        self.explore_start_with_ip(ip)

    def explore_start_with_ip(self, ip):

        save_ip(ip)

        self.pending_explore_ip = ip

        self.progress = QProgressDialog(
            _("Exploring the Xteink X3 filesystem..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.explore_worker = ExploreWorker(
            ip,
            self.gui,
        )

        self.explore_worker.finished.connect(
            self.explore_finished,
        )

        self.explore_worker.failed.connect(
            self.explore_failed,
        )

        self.explore_worker.start()

    def explore_finished(self, tree_text):

        self.explore_worker = None

        self.close_progress()

        if not tree_text.strip():

            tree_text = _("(empty)")

        dialog = ExploreDialog(
            self.gui,
            self.pending_explore_ip,
            tree_text,
        )

        dialog.exec()

    def explore_failed(self, message):

        self.explore_worker = None

        self.close_progress()

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while exploring the filesystem:\n\n%s") % message,
            show=True,
        )

    # ==================================================================
    # PROGRESSION DE LECTURE
    # ==================================================================

    def reading_progress_x3(self):

        answer = QMessageBox.information(
            self.gui,
            _("X3 reader management"),
            _(
                "Please put the Xteink X3 into\n"
                '"PC Transfer" mode.\n\n'
                "Once the mode is active, click OK."
            ),
            QMessageBox.Ok
            | QMessageBox.Cancel,
            QMessageBox.Ok,
        )

        if answer != QMessageBox.Ok:
            return

        ip = self.choose_xteink("progress")

        if not ip:
            return

        self.reading_progress_start_with_ip(ip)

    def reading_progress_start_with_ip(self, ip):

        save_ip(ip)

        self.progress = QProgressDialog(
            _("Reading progress data from the Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.reading_progress_worker = ReadingProgressWorker(
            ip,
            self.gui,
        )

        self.reading_progress_worker.finished.connect(
            self.reading_progress_finished,
        )

        self.reading_progress_worker.failed.connect(
            self.reading_progress_failed,
        )

        self.reading_progress_worker.start()

    def reading_progress_finished(self, results):

        self.reading_progress_worker = None

        self.close_progress()

        if not results:

            info_dialog(
                self.gui,
                _("X3 reader management"),
                _(
                    "No reading progress data found on the "
                    "Xteink X3."
                ),
                show=True,
            )

            return

        dialog = ReadingProgressDialog(
            self.gui,
            results,
        )

        dialog.exec()

    def reading_progress_failed(self, message):

        self.reading_progress_worker = None

        self.close_progress()

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _(
                "Error while reading progress data:\n\n%s\n\n"
                "If this is a timeout, the Xteink X3 may have exited "
                "\"PC Transfer\" mode since the last operation — check "
                "the device's screen and try again."
            ) % message,
            show=True,
        )

    def manage_x3(self):

        answer = QMessageBox.information(
            self.gui,
            _("X3 reader management"),
            _(
                "Please put the Xteink X3 into\n"
                '"PC Transfer" mode.\n\n'
                "Once the mode is active, click OK."
            ),
            QMessageBox.Ok
            | QMessageBox.Cancel,
            QMessageBox.Ok,
        )

        if answer != QMessageBox.Ok:
            return

        ip = self.choose_xteink("manage")

        if ip:

            self.start_list_files(ip)

    def start_list_files(self, ip):

        save_ip(ip)

        self.progress = QProgressDialog(
            _("Reading books stored on the Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.list_worker = ListFilesWorker(
            ip,
            "/",
            self.gui,
        )

        self.list_worker.finished.connect(
            lambda files, x=ip:
            self.list_files_finished(x, files)
        )

        self.list_worker.failed.connect(
            self.list_files_failed,
        )

        self.list_worker.start()

    # ==================================================================
    # LISTE
    # ==================================================================

    def list_files_finished(self, ip, files):

        if self.progress:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

        self.list_worker = None

        if not isinstance(files, list):

            error_dialog(
                self.gui,
                _("X3 reader management"),
                _("Unexpected response from the Xteink X3."),
                show=True,
            )

            return

        visible_files = []

        for item in files:

            if not isinstance(item, dict):
                continue

            item_type = item.get(
                "type",
                "",
            )

            name = item.get(
                "name",
                "",
            )

            if not name:
                continue

            if item_type in (
                "file",
                "dir",
            ):

                visible_files.append(item)

        if not visible_files:

            info_dialog(
                self.gui,
                _("X3 reader management"),
                _("No files or folders found on the Xteink X3."),
                show=True,
            )

            return

        visible_files.sort(
            key=lambda x: (
                0 if x.get("type") == "dir" else 1,
                x.get("name", "").lower(),
            )
        )

        dialog = XteinkFilesDialog(
            self.gui,
            visible_files,
        )

        result = dialog.exec()

        if result != QDialog.Accepted:
            return

        selected_items = dialog.selected_items()

        if not selected_items:
            return

        paths = []

        for item in selected_items:

            name = item.get(
                "name",
                "",
            )

            if not name:
                continue

            paths.append("/" + name)

        if not paths:
            return

        lines = []

        for item in selected_items:

            name = item.get(
                "name",
                "",
            )

            if item.get("type") == "dir":

                lines.append(
                    "📁 " + name,
                )

            else:

                lines.append(
                    "📄 " + name,
                )

        answer = QMessageBox.question(
            self.gui,
            _("Confirmation"),
            _(
                "Do you want to delete the following items?\n\n"
            )
            + "\n".join(lines)
            + _(
                "\n\n"
                "For folders, all their contents will also be deleted."
            ),
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )

        if answer != QMessageBox.Yes:
            return

        self.start_delete(
            ip,
            paths,
        )

    def list_files_failed(self, message):

        if self.progress:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

        self.list_worker = None

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while reading files:\n\n%s") % message,
            show=True,
        )

    # ==================================================================
    # SUPPRESSION
    # ==================================================================

    def start_delete(self, ip, paths):

        self.progress = QProgressDialog(
            _("Deleting items from the Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.delete_worker = DeleteWorker(
            ip,
            paths,
            self.gui,
        )

        self.delete_worker.finished.connect(
            self.delete_finished,
        )

        self.delete_worker.failed.connect(
            self.delete_failed,
        )

        self.delete_worker.start()

    def delete_finished(self, deleted):

        if self.progress:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

        self.delete_worker = None

        if deleted == 1:

            message = _(
                "%d item deleted from the Xteink X3."
            ) % deleted

        else:

            message = _(
                "%d items deleted from the Xteink X3."
            ) % deleted

        info_dialog(
            self.gui,
            _("X3 reader management"),
            message,
            show=True,
        )

    def delete_failed(self, message):

        if self.progress:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

        self.delete_worker = None

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while deleting:\n\n%s") % message,
            show=True,
        )

    # ==================================================================
    # FIN ENVOI
    # ==================================================================

    def close_progress(self):

        if self.progress is not None:

            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

    def upload_finished(
        self,
        sent,
        ip,
        version,
        device_id,
        unverified_books,
    ):

        self.close_progress()

        self.qaction.setEnabled(True)

        if sent == 1:

            message = _(
                "Sending completed.\n\n"
                "X3: %s\n"
                "Version: %s\n"
                "ID: %s\n\n"
                "%d book sent."
            ) % (
                ip,
                version,
                device_id,
                sent,
            )

        else:

            message = _(
                "Sending completed.\n\n"
                "X3: %s\n"
                "Version: %s\n"
                "ID: %s\n\n"
                "%d books sent."
            ) % (
                ip,
                version,
                device_id,
                sent,
            )

        if unverified_books:

            message += "\n\n" + _(
                "WARNING: the Xteink X3 accepted the request but the "
                "following %d file(s) could not be confirmed on the "
                "device afterwards — they were likely NOT actually "
                "saved:\n\n%s"
            ) % (
                len(unverified_books),
                "\n".join(unverified_books),
            )

            error_dialog(
                self.gui,
                _("X3 reader management"),
                message,
                show=True,
            )

        else:

            info_dialog(
                self.gui,
                _("X3 reader management"),
                message,
                show=True,
            )

        self.worker = None
        self.pending_ids = None

        self.cleanup_temp_files()

    def upload_failed(self, message):

        self.close_progress()

        self.qaction.setEnabled(True)

        error_dialog(
            self.gui,
            _("X3 reader management"),
            _("Error while sending:\n\n%s") % message,
            show=True,
        )

        self.worker = None
        self.pending_ids = None

        self.cleanup_temp_files()

    def cleanup_temp_files(self):

        # Supprime les EPUB temporaires générés par la conversion
        # automatique (voir ConversionWorker), une fois l'envoi
        # terminé, qu'il ait réussi ou non.
        for tmp_path in self.pending_temp_files:

            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        self.pending_temp_files = []
