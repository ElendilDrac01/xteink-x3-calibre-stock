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
)

from .network import (
    get_info,
    upload,
    scan_network,
    load_saved_ip,
    save_ip,
    list_files,
    delete_file,
    clean_info_field,
    XteinkError,
)


# ======================================================================
# ENVOI
# ======================================================================

class UploadWorker(QThread):

    finished = pyqtSignal(int, str, str, str)
    failed = pyqtSignal(str)

    def __init__(self, ip, books, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.books = books

    def run(self):

        sent = 0

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

            for filename, epub in self.books:

                upload(
                    self.ip,
                    filename,
                    epub,
                )

                sent += 1

            self.finished.emit(
                sent,
                self.ip,
                version,
                device_id,
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
                if name == "XTCache":

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

class XteinkX3Action(InterfaceAction):

    name = "Xteink X3"

    action_spec = (
        _("X3 reader management"),
        _("Manage books on the Xteink X3"),
        None,
        "Ctrl+Shift+X",
    )

    def genesis(self):

        self.qaction.triggered.connect(
            self.send_to_x3,
        )

        self.worker = None
        self.scan_worker = None
        self.list_worker = None
        self.delete_worker = None
        self.progress = None

        self.pending_ids = None
        self.pending_operation = None

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

        send_action.triggered.connect(
            self.send_to_x3,
        )

        manage_action.triggered.connect(
            self.manage_x3,
        )

        self.qaction.setMenu(menu)

    # ==================================================================
    # CHOIX DU XTEINK
    # ==================================================================

    def choose_xteink(self, operation):

        self.pending_operation = operation

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

        books = []

        for book_id in ids:

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

            if not epub:

                error_dialog(
                    self.gui,
                    _("X3 reader management"),
                    _("The selected book has no EPUB format."),
                    show=True,
                )

                continue

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

            books.append(
                (
                    filename,
                    epub,
                )
            )

        if not books:
            return

        save_ip(ip)

        self.qaction.setEnabled(False)

        self.progress = QProgressDialog(
            _("Sending books to Xteink X3..."),
            None,
            0,
            0,
            self.gui,
        )

        self.progress.setWindowTitle(
            _("X3 reader management"),
        )

        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.setMinimumDuration(0)
        self.progress.setCancelButton(None)

        self.progress.show()

        self.worker = UploadWorker(
            ip,
            books,
            self.gui,
        )

        self.worker.finished.connect(
            self.upload_finished,
        )

        self.worker.failed.connect(
            self.upload_failed,
        )

        self.worker.start()

    # ==================================================================
    # GESTION
    # ==================================================================

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

        info_dialog(
            self.gui,
            _("X3 reader management"),
            message,
            show=True,
        )

        self.worker = None
        self.pending_ids = None

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
