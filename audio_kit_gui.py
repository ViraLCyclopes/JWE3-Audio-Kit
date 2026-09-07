"""Small GUI for the JWE3 Audio Kit: point it at cobra-tools once, then merge.

cobra-tools is GPLv3 and is deliberately NOT redistributed with this kit, so
every command needs to be told where your own checkout lives. Passing --cobra on
every invocation gets old fast, and the alternatives (an environment variable, or
hand-editing audio_tools.json) are exactly the kind of setup step people get
wrong once and then debug for an hour.

So: set it here, it is written to audio_tools.json beside this file, and every
command-line tool in the kit picks it up through `audio_paths.configuration()`.
audio_tools.json is gitignored - it holds YOUR paths and is never published.

Deliberately thin. It shells out to the same scripts the command line uses
rather than importing their internals, so there is one code path to keep honest
and the GUI cannot drift from the documented commands.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

KIT = Path(__file__).resolve().parent
CONFIG = KIT / "audio_tools.json"


def load_config() -> dict:
    if not CONFIG.is_file():
        return {}
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data: dict) -> None:
    CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class Worker(QtCore.QThread):
    """Run one kit script, streaming its output.

    A merge shells out to Cobra and can take a while; doing that on the GUI
    thread would freeze the window and look like a hang.
    """
    line = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(int)

    def __init__(self, argv, parent=None):
        super().__init__(parent)
        self.argv = argv

    def run(self):
        try:
            process = subprocess.Popen(
                self.argv, cwd=str(KIT), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        except OSError as exc:
            self.line.emit(f"could not start: {exc}")
            self.done.emit(-1)
            return
        for text in process.stdout:
            self.line.emit(text.rstrip("\n"))
        process.wait()
        self.done.emit(process.returncode)


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JWE3 Audio Kit")
        self.resize(820, 560)
        self.worker = None
        config = load_config()

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "cobra-tools is <b>GPLv3 and not bundled</b> with this kit, so point this at your own "
            "checkout once - the folder containing <tt>ovl_tool_cmd.py</tt>. It is saved to "
            "<tt>audio_tools.json</tt> beside the kit and used by every command-line tool here.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        self.cobra_edit = QtWidgets.QLineEdit(str(config.get("cobra_tools", "")))
        self.cobra_edit.setPlaceholderText(r"…\cobra-tools-master  (contains ovl_tool_cmd.py)")
        form.addRow("Cobra tools", self._with_browse(self.cobra_edit, self.pick_cobra))
        self.game_edit = QtWidgets.QLineEdit(str(config.get("game", "")))
        self.game_edit.setPlaceholderText("leave blank to auto-detect from Steam")
        form.addRow("Game root", self._with_browse(self.game_edit, self.pick_game))
        layout.addLayout(form)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QtWidgets.QHBoxLayout()
        for label, slot, tip in (
                ("Save settings", self.save, "Write these paths to audio_tools.json"),
                ("Check (read-only)", self.check,
                 "Validate the merge without writing any game file"),
                ("Merge registry", self.merge,
                 "Rebuild the audio registry from stock plus every installed fragment"),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QtWidgets.QLabel(
            "Re-run the merge whenever an audio mod is installed <b>or removed</b>. It rebuilds "
            "from stock plus every fragment present, so a stale registry silently erases another "
            "mod's audio.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #ffe075; padding: 4px 0;")
        layout.addWidget(note)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self.log, 1)

        self.validate()
        self.cobra_edit.textChanged.connect(self.validate)

    def _with_browse(self, edit, slot):
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QtWidgets.QPushButton("Browse…")
        button.clicked.connect(slot)
        row.addWidget(button)
        return holder

    def pick_cobra(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select your cobra-tools folder", self.cobra_edit.text() or str(KIT))
        if path:
            self.cobra_edit.setText(path)

    def pick_game(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select the JWE3 game root", self.game_edit.text() or "")
        if path:
            self.game_edit.setText(path)

    def validate(self):
        """Check the path names a real Cobra checkout, before anything runs.

        The same check `audio_paths.cobra_path` makes - catching it here turns a
        stack trace mid-merge into a message before you start.
        """
        text = self.cobra_edit.text().strip()
        if not text:
            self.status.setText("No Cobra folder set — the kit will fall back to auto-detection.")
            self.status.setStyleSheet("color: #ffe075;")
            return False
        if not (Path(text) / "ovl_tool_cmd.py").is_file():
            self.status.setText("That folder has no ovl_tool_cmd.py — not a cobra-tools checkout.")
            self.status.setStyleSheet("color: #ff8080;")
            return False
        self.status.setText("Cobra tools look valid.")
        self.status.setStyleSheet("color: #80c080;")
        return True

    def save(self):
        config = load_config()
        cobra = self.cobra_edit.text().strip()
        game = self.game_edit.text().strip()
        # Store only what is set: an empty string would be read back as a
        # configured-but-invalid path, which the tools treat as an error rather
        # than falling through to auto-detection.
        config.pop("cobra_tools", None)
        config.pop("game", None)
        if cobra:
            config["cobra_tools"] = cobra
        if game:
            config["game"] = game
        try:
            save_config(config)
        except OSError as exc:
            self.append(f"could not write {CONFIG}: {exc}")
            return
        self.append(f"saved {CONFIG}")
        self.validate()

    def check(self):
        self.run_tool(["--check"])

    def merge(self):
        self.run_tool([])

    def run_tool(self, extra):
        if self.worker is not None and self.worker.isRunning():
            self.append("already running")
            return
        if self.cobra_edit.text().strip() and not self.validate():
            return
        self.save()
        argv = [sys.executable, str(KIT / "merge_audio_registry.py"), *extra]
        if self.cobra_edit.text().strip():
            argv += ["--cobra", self.cobra_edit.text().strip()]
        if self.game_edit.text().strip():
            argv += ["--game", self.game_edit.text().strip()]
        self.log.clear()
        self.append("$ " + " ".join(argv))
        self.worker = Worker(argv, self)
        self.worker.line.connect(self.append)
        self.worker.done.connect(self.finished)
        self.worker.start()

    def append(self, text):
        self.log.appendPlainText(text)

    def finished(self, code):
        self.append("")
        self.append(f"--- finished, exit code {code}"
                    + ("" if code == 0 else "  (see the messages above)"))


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
