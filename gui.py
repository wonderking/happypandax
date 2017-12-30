import sys
import os
import multiprocessing as mp
import functools
import signal
import webbrowser

from threading import Thread, Timer
from multiprocessing import Process, queues
from happypanda.common import constants

# This is required to be here or else multiprocessing won't work when running in a frozen state!
# I had a hell of a time debugging this :(


class RedirectProcess(Process):

    def __init__(self, streamqueue, exitqueue=None, initializer=None, **kwargs):
        super().__init__(**kwargs)
        assert initializer is None or callable(initializer)
        self.streamqueue = streamqueue
        self.exitqueue = exitqueue
        self.initializer = initializer

    def run(self):
        sys.stdout = self.streamqueue
        sys.stderr = self.streamqueue
        if self.initializer:
            self.initializer()
        if self._target:  # HACK: don't access private variables!
            e = self._target(*self._args, **self._kwargs)
            if self.exitqueue is not None:
                self.exitqueue.put(e)


class StreamQueue(queues.Queue):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, ctx=mp.get_context())

    def write(self, msg):
        self.put(msg)

    def flush(self):
        pass


def from_gui():
    constants.from_gui = True


if __name__ == "__main__":
    mp.freeze_support()

import psutil  # noqa: E402
import qtawesome as qta  # noqa: E402
from PyQt5.QtWidgets import (QApplication,
                             QMainWindow,
                             QWidget,
                             QVBoxLayout,
                             QHBoxLayout,
                             QTabWidget,
                             QGroupBox,
                             QLineEdit,
                             QFormLayout,
                             QScrollArea,
                             QPushButton,
                             QLabel,
                             QMessageBox,
                             QDialog,
                             QSystemTrayIcon,
                             QMenu,
                             QFileDialog,
                             QPlainTextEdit,
                             QCheckBox)  # noqa: E402
from PyQt5.QtGui import QIcon, QPalette, QMouseEvent  # noqa: E402
from PyQt5.QtCore import Qt, QDir, pyqtSignal, QEvent  # noqa: E402
from i18n import t  # noqa: E402

from happypanda.common import utils, config  # noqa: E402
from happypanda.core.commands import io_cmd  # noqa: E402
from happypanda import main  # noqa: E402
import HPtoHPX  # noqa: E402

app = None
exitcode = None

SQueue = None
SQueueExit = None


def kill_proc_tree(pid, sig=signal.SIGTERM, include_parent=True,
                   timeout=None, on_terminate=None):
    """Kill a process tree (including grandchildren) with signal
    "sig" and return a (gone, still_alive) tuple.
    "on_terminate", if specified, is a callabck function which is
    called as soon as a child terminates.
    """
    if pid == os.getpid():
        raise RuntimeError("I refuse to kill myself")
    parent = psutil.Process(pid)
    children = parent.children(recursive=True)
    if include_parent:
        children.append(parent)
    for p in children:
        p.send_signal(sig)
    gone, alive = psutil.wait_procs(children, timeout=timeout,
                                    callback=on_terminate)
    return (gone, alive)


class TextViewer(QPlainTextEdit):
    """
    A read-only embedded console
    """

    write = pyqtSignal(str)

    def __init__(self, streamqueue, parent=None):
        super().__init__(parent)
        self.stream = streamqueue
        self.setMaximumBlockCount(999)
        self.setReadOnly(True)
        self.write.connect(self.w)
        if self.stream:
            t = Thread(target=self.poll_stream)
            t.daemon = True
            t.start()

    def w(self, s):
        s = s.strip()
        if s:
            self.appendPlainText('>: ' + s if s != '\n' else s)

    def poll_stream(self):
        while True:
            self.write.emit(self.stream.get())


class PathLineEdit(QLineEdit):
    """
    A lineedit which open a filedialog on right/left click
    Set dir to false if you want files.
    """

    def __init__(self, parent=None, dir=True, filters=""):
        super().__init__(parent)
        self.folder = dir
        self.filters = filters
        self.setPlaceholderText('Left-click to open folder explorer')
        self.setToolTip('Left-click to open folder explorer')

    def openExplorer(self):
        if self.folder:
            path = QFileDialog.getExistingDirectory(self,
                                                    'Choose folder', QDir.homePath())
        else:
            path = QFileDialog.getOpenFileName(self,
                                               'Choose file', QDir.homePath(), filter=self.filters)
            path = path[0]
        if len(path) != 0:
            self.setText(path)

    def mousePressEvent(self, event):
        assert isinstance(event, QMouseEvent)
        if len(self.text()) == 0:
            if event.button() == Qt.LeftButton:
                self.openExplorer()
        super().mousePressEvent(event)


class ConvertHP(QDialog):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._parent = parent
        self._source = ""
        self._destination = ""
        self._rar = ""
        self._process = 0
        self._archive = False
        self._dev = False
        self._args_label = QLabel()
        self._args_label.setWordWrap(True)
        self.args = []
        self.create_ui()
        self.setMinimumWidth(500)

    def create_ui(self):
        lf = QFormLayout(self)

        source_edit = PathLineEdit(self, False, "happypanda.db")
        source_edit.textChanged.connect(self.on_source)
        lf.addRow(t("", default="Old HP database file") + ':', source_edit)

        rar_edit = PathLineEdit(self, False)
        rar_edit.setPlaceholderText(t("", default="Optional"))
        rar_edit.textChanged.connect(self.on_rar)
        lf.addRow(t("", default="RAR tool path") + ':', rar_edit)
        rar_edit.setText(config.unrar_tool_path.value)

        archive_box = QCheckBox(self)
        archive_box.stateChanged.connect(self.on_archive)
        lf.addRow(t("", default="Skip archives") + ':', archive_box)

        dev_box = QCheckBox(self)
        dev_box.stateChanged.connect(self.on_dev)
        lf.addRow(t("", default="Dev Mode") + ':', dev_box)

        lf.addRow(t("", default="Command") + ':', self._args_label)
        convert_btn = QPushButton(t("", default="Convert"))
        convert_btn.clicked.connect(self.convert)
        lf.addRow(convert_btn)

    def on_source(self, v):
        self._source = v
        self.update_label()

    def on_rar(self, v):
        self._rar = v
        self.update_label()

    def on_process(self, v):
        self._process = v
        self.update_label()

    def on_archive(self, v):
        self._archive = v
        self.update_label()

    def on_dev(self, v):
        self._dev = v
        self.update_label()

    def update_label(self):
        self.args = []
        self.args .append(os.path.normpath(self._source))
        if self._dev:
            self.args .append(os.path.join("data", "happypanda_dev.db"))
        else:
            self.args .append(os.path.join("data", "happypanda.db"))
        if self._rar:
            self.args .append("--rar")
            self.args .append(os.path.normpath(self._rar))
        if self._archive:
            self.args .append("--skip-archive")

        self._args_label.setText(" ".join(self.args))
        self.adjustSize()

    def convert(self):
        if self.args:
            self._parent.activate_output.emit()
            p = RedirectProcess(SQueue, target=HPtoHPX.main, args=(self.args,))
            p.start()
            self._parent.processes.append(p)
            Thread(target=self._parent.watch_process, args=(None, p)).start()
            self.close()


class SettingsTabs(QTabWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_ui()

    def create_ui(self):
        cfg = config.ConfigNode.get_all()
        for ns in sorted(config.ConfigNode.default_namespaces):
            w = QWidget()
            wlayout = QFormLayout(w)
            for k, n in sorted(cfg[ns].items()):
                if not n.hidden:
                    help_w = QPushButton(qta.icon("fa.question-circle"), "")
                    help_w.setFlat(True)
                    help_w.setToolTip(n.description)
                    help_w.setToolTipDuration(9999999999)
                    q = QWidget()
                    q_l = QHBoxLayout(q)
                    q_l.addWidget(help_w)
                    q_l.addWidget(QLabel(k))
                    wlayout.addRow(q, self.get_setting_input(k, n))
            sarea = QScrollArea(self)
            sarea.setWidget(w)
            sarea.setWidgetResizable(True)
            sarea.setBackgroundRole(QPalette.Light)
            self.addTab(sarea, ns)

    def get_setting_input(self, ns, node):
        input_w = None
        if node.type_ == dict:
            input_w = QWidget()
            input_l = QFormLayout(input_w)
            for k, v in sorted(node.default.items()):
                real_v = node.value.get(k, v)
                if type(v) == bool:
                    i = QCheckBox()
                    i.setChecked(real_v)
                    i.stateChanged.connect(
                        functools.partial(lambda w, key, value, s: self.set_dict_value(key, s, node, type(value), w),
                                          i, k, v))
                else:
                    i = QLineEdit()
                    i.setText(str(real_v))
                    i.textChanged.connect(
                        functools.partial(lambda w, key, value, s: self.set_dict_value(key, s, node, type(value), w),
                                          i, k, v))
                input_l.addRow(k, i)
        elif node.type_ == bool:
            input_w = QCheckBox()
            input_w.setChecked(node.value)
            input_w.stateChanged.connect(lambda s: self.set_value(node, s, input_w))
        else:
            input_w = QLineEdit()
            input_w.setText(str(node.value))
            input_w.textChanged.connect(lambda s: self.set_value(node, s, input_w))
        q = QWidget()
        q_l = QHBoxLayout(q)
        q_l.addWidget(input_w)
        return q

    def set_dict_value(self, k, v, node, type_, widget):
        try:
            v = type_(v)
            d = node.value.copy()
            d.update({k: v})
            node.value = d
            widget.setStyleSheet("background: rgba(137, 244, 66, 0.2);")
        except BaseException:
            widget.setStyleSheet("background: rgba(244, 92, 65, 0.2);")
        config.config.save()

    def set_value(self, node, value, widget):
        try:
            v = node.type_(value)
            node.value = v
            config.config.save()
            widget.setStyleSheet("background: rgba(137, 244, 66, 0.2);")
        except BaseException:
            widget.setStyleSheet("background: rgba(244, 92, 65, 0.2);")


class Window(QMainWindow):

    activate_output = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.processes = []
        self.tray = QSystemTrayIcon(self)
        self.closing = False
        self.forcing = False
        self.server_started = False
        self.client_started = False
        self.output_tab_idx = 0
        self.force_kill = False
        self.start_ico = QIcon(os.path.join(constants.dir_static, "favicon.ico")
                               )  # qta.icon("fa.play", color="#41f46b")
        self.stop_ico = qta.icon("fa.stop", color="#f45f42")
        self.server_process = None
        self.webclient_process = None
        self.create_ui()

        self.activate_output.connect(lambda: self.main_tab.setCurrentIndex(self.output_tab_idx))

        if config.gui_autostart_server.value:
            self.toggle_server()

    def create_ui(self):
        w = QWidget(self)
        self.main_tab = QTabWidget(self)
        self.viewer = TextViewer(SQueue, self.main_tab)
        settings_widget = QWidget(self.main_tab)
        self.output_tab_idx = self.main_tab.addTab(self.viewer, t("", default="Output"))
        self.main_tab.addTab(settings_widget, t("", default="Configuration"))

        settings_group_l = QVBoxLayout(settings_widget)
        settings = SettingsTabs()
        settings_group_l.addWidget(settings)
        settings_group_l.addWidget(
            QLabel("<i>{}</i>".format(t("", default="Hover the question mark icon to see setting description tooltip"))))

        buttons = QGroupBox(w)
        self.server_btn = QPushButton(self.start_ico, t("", default="Start server"))
        self.server_btn.clicked.connect(self.toggle_server)
        self.server_btn.setShortcut(Qt.CTRL | Qt.Key_S)

        #self.webclient_btn = QPushButton(self.start_ico, t("", default="Start webclient"))
        # self.webclient_btn.clicked.connect(self.toggle_client)
        # self.webclient_btn.setShortcut(Qt.CTRL|Qt.Key_W)

        open_client_btn = QPushButton(qta.icon("fa.external-link"), t("", default="Open Webclient"))
        open_client_btn.clicked.connect(self.open_client)
        open_client_btn.setShortcut(Qt.CTRL | Qt.Key_O)

        open_config_btn = QPushButton(qta.icon("fa.cogs"), t("", default="Open configuration"))
        open_config_btn.clicked.connect(self.open_cfg)
        open_config_btn.setShortcut(Qt.CTRL | Qt.Key_C)

        convert_btn = QPushButton(qta.icon("fa.refresh"), t("", default="HP to HPX"))
        convert_btn.clicked.connect(self.convert_hp)

        for b in (self.server_btn, open_config_btn, convert_btn, open_client_btn):
            b.setFixedHeight(40)
        button_layout = QHBoxLayout(buttons)
        button_layout.addWidget(self.server_btn)
        button_layout.addWidget(open_client_btn)
        # button_layout.addWidget(self.webclient_btn)
        button_layout.addWidget(open_config_btn)
        button_layout.addWidget(convert_btn)

        infos = QGroupBox(t("", default="Info"))
        info_layout = QHBoxLayout(infos)
        version_layout = QFormLayout()
        version_layout.addRow(t("", default="Server version") +
                              ':', QLabel(".".join(str(x) for x in constants.version)))
        version_layout.addRow(t("", default="Webclient version") +
                              ':', QLabel(".".join(str(x) for x in constants.version_web)))
        version_layout.addRow(t("", default="Database version") +
                              ':', QLabel(".".join(str(x) for x in constants.version_db)))

        connect_layout = QFormLayout()
        connect_layout.addRow(t("", default="Server") + '@', QLabel(config.host.value + ':' + str(config.port.value)))
        connect_layout.addRow(t("", default="Webclient") + '@',
                              QLabel(config.host_web.value + ':' + str(config.port_web.value)))
        info_layout.addLayout(connect_layout)
        info_layout.addLayout(version_layout)

        main_layout = QVBoxLayout(w)
        main_layout.addWidget(self.main_tab)
        main_layout.addWidget(infos)
        main_layout.addWidget(buttons)
        self.setCentralWidget(w)

        self.tray.setIcon(QIcon(os.path.join(constants.dir_static, "favicon.ico")))
        self.tray.activated.connect(self.tray_activated)
        tray_menu = QMenu()
        tray_menu.addAction(t("", default="Show"), lambda: all((self.showNormal(), self.activateWindow())))
        tray_menu.addSeparator()
        tray_menu.addAction(t("", default="Quit"), lambda: self.real_close())
        self.tray.setContextMenu(tray_menu)

    def real_close(self):
        self.closing = True
        self.close()

    def force_close(self):
        self.forcing = True
        self.real_close()

    def tray_activated(self, reason):
        if reason != QSystemTrayIcon.Context:
            self.showNormal()
            self.activateWindow()

    def open_cfg(self):
        if not os.path.exists(constants.config_path):
            with open(constants.config_path, 'x'):
                pass
        io_cmd.CoreFS.open_with_default(constants.config_path)

    def convert_hp(self):
        c = ConvertHP(self)
        c.setWindowTitle(self.windowTitle())
        c.exec()

    def toggle_server(self, ecode=None):
        self.server_started = not self.server_started
        if ecode and ecode in (constants.ExitCode.Restart.value,
                               constants.ExitCode.Exit.value,
                               constants.ExitCode.Update.value,
                               ):
            global exitcode
            exitcode = ecode
            self.force_close()
        if self.server_started:
            self.server_btn.setText(t("", default="Stop server"))
            self.server_btn.setIcon(self.stop_ico)
            self.server_process = self.start_server()
            self.activate_output.emit()
            if config.gui_open_webclient_on_server_start.value:
                Timer(3, self.open_client).start()
        else:
            self.force_kill = True
            self.server_btn.setText(t("", default="Start server"))
            self.server_btn.setIcon(self.start_ico)
            if self.server_process:
                self.stop_process(self.server_process)
                self.server_process = None

    def toggle_client(self, exitcode=None):
        self.client_started = not self.client_started
        if self.client_started:
            self.webclient_btn.setText(t("", default="Stop webclient"))
            self.webclient_btn.setIcon(self.stop_ico)

        else:
            self.webclient_btn.setText(t("", default="Start webclient"))
            self.webclient_btn.setIcon(self.start_ico)

    def open_client(self):
        u = utils.get_qualified_name(config.host_web.value, config.port_web.value)
        webbrowser.open('http://' + u)

    def stop_process(self, p):
        if p:
            try:
                kill_proc_tree(p.pid)
                # p.kill()
            except psutil.NoSuchProcess:
                pass

    def watch_process(self, cb, p):
        p.join()
        if cb and not self.force_kill:
            cb(SQueueExit.get_nowait() if not p.exitcode else p.exitcode)
        else:
            self.force_kill = False

    def start_server(self):
        p = RedirectProcess(SQueue, SQueueExit, from_gui, target=main.start)
        p.start()
        Thread(target=self.watch_process, args=(self.toggle_server, p)).start()
        return p

    def changeEvent(self, ev):
        if ev.type() == QEvent.WindowStateChange:
            if self.windowState() == Qt.WindowMinimized:
                self.to_tray()
        return super().changeEvent(ev)

    def to_tray(self):
        self.tray.show()
        self.hide()

    def closeEvent(self, ev):
        if config.gui_minimize_on_close and not self.closing:
            self.to_tray()
            ev.ignore()
            return
        self.closing = False
        if not self.forcing and any((self.server_started, self.client_started)):
            if not self.isVisible():
                self.show()
            if QMessageBox.warning(self,
                                   self.windowTitle(),
                                   t("", default="Server or client is still running\nAre you sure you want to quit?"),
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)\
               == QMessageBox.No:
                ev.ignore()
                return
        [self.stop_process(x) for x in self.processes + [self.server_process, self.webclient_process]]
        super().closeEvent(ev)


if __name__ == "__main__":

    SQueue = StreamQueue()
    SQueueExit = StreamQueue()

    utils.setup_i18n()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(constants.dir_static, "favicon.ico")))
    app.setApplicationDisplayName("HappyPanda X")
    app.setApplicationName("HappyPanda X")
    app.setApplicationVersion(".".join(str(x) for x in constants.version))
    app.setOrganizationDomain("Twiddly")
    app.setOrganizationName("Twiddly")
    app.setDesktopFileName("HappyPanda X")
    window = Window()
    window.resize(600, 650)
    sys.stdout = SQueue
    sys.stderr = SQueue
    if config.gui_start_minimized.value:
        window.tray.show()
    else:
        window.show()
        window.activateWindow()
    e = app.exec()
    if exitcode == constants.ExitCode.Restart.value:
        utils.restart_process()
    elif exitcode == constants.ExitCode.Update.value:
        utils.launch_updater()
    sys.exit(e)