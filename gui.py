import os, sys, time
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QProgressBar
from PyQt5.QtGui import QIcon

from utils import (
    adb_path_ok, adb_devices, get_screen_size, get_device_model,
    adb_restart_server, run_adb_batch
)
from draw_core import (
    preprocess_image, extract_contours, sample_points, make_preview, generate_swipe_commands
)

APP_TITLE = "InsDraw ADB"

# ---------- theme ----------
ACCENT = "#22c55e"; BG0 = "#1c1c20"; BG1 = "#121216"; FG = "#ffffff"
def apply_theme(app):
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(BG0))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(BG1))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(FG))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(FG))
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor(BG1))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(FG))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(ACCENT))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QWidget {{ color:{FG}; background:{BG0}; font-size:13px; }}
        QLineEdit, QComboBox, QTextEdit {{ background:{BG1}; border:1px solid #2a2a30; border-radius:6px; padding:6px; }}
        QPushButton {{ background:#2b2f35; border:1px solid #3a3f46; border-radius:8px; padding:6px 10px; }}
        QPushButton:hover {{ border-color:{ACCENT}; }}
        QProgressBar {{ border:1px solid #2a2a30; border-radius:6px; text-align:center; background:{BG1}; height:18px; }}
        QProgressBar::chunk {{ background:{ACCENT}; border-radius:6px; }}
        QLabel#title {{ font-size:16px; font-weight:600; }}
    """)


class DrawWorker(QtCore.QThread):
    log = QtCore.pyqtSignal(str)
    percent = QtCore.pyqtSignal(int)
    done = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(self, serial, filepath, blur, step, seg_ms):
        super().__init__()
        self.serial = serial; self.filepath = filepath
        self.blur = blur; self.step = step; self.seg_ms = seg_ms
        self._stop = False

    def stop(self): self._stop = True
    def _canceled(self): return self._stop

    def run(self):
        try:
            size = get_screen_size(self.serial)
            if not size: self.failed.emit("ไม่พบขนาดหน้าจอ"); return
            W, H = size
            self.log.emit(f"Screen {W}x{H}")

            mask = preprocess_image(self.filepath, W, H, blur=self.blur)
            contours = extract_contours(mask, min_area=80)
            if not contours:
                self.failed.emit("ไม่พบเส้น (Contours=0)"); return

            cmds = []
            for c in contours:
                pts = sample_points(c, step=self.step)
                cmds.extend(generate_swipe_commands(pts, seg_ms=self.seg_ms))
            if not cmds:
                self.failed.emit("ไม่มีคำสั่ง swipe"); return

            self.log.emit(f"Total sub-swipes: {len(cmds)}")

            def on_progress(p): self.percent.emit(min(int(p), 99))
            rc, err = run_adb_batch(
                self.serial, cmds,
                progress_cb=on_progress,
                cancel_check=self._canceled,
                sleep_ms=8
            )
            if self._canceled():
                self.log.emit("stop rn"); self.done.emit(); return
            if rc != 0: self.log.emit(f"adb batch rc={rc} err={err}")
            self.percent.emit(100)
            self.done.emit()
        except Exception as e:
            self.failed.emit(str(e))

# ui
class Main(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE); self.resize(900, 650)
        self.serial=None; self.worker=None

        root = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(APP_TITLE); title.setObjectName("title"); root.addWidget(title)

        top = QtWidgets.QGridLayout()
        root.addLayout(top)
        top.addWidget(QtWidgets.QLabel("Devices:"), 0, 0)
        self.combo = QtWidgets.QComboBox(); self.combo.addItem("No device")
        top.addWidget(self.combo, 0, 1)

        self.btnRefresh = QtWidgets.QPushButton("Refresh")
        self.btnRestart = QtWidgets.QPushButton("Restart ADB")
        top.addWidget(self.btnRefresh, 0, 2); top.addWidget(self.btnRestart, 0, 3)

        self.lblModel = QtWidgets.QLabel("Model: -"); self.lblSize = QtWidgets.QLabel("Screen: -")
        top.addWidget(self.lblModel, 1, 1); top.addWidget(self.lblSize, 1, 2, 1, 2)

        row = QtWidgets.QHBoxLayout(); root.addLayout(row)
        self.fileLine = QtWidgets.QLineEdit()
        self.btnBrowse = QtWidgets.QPushButton("Browse PNG")
        row.addWidget(self.fileLine); row.addWidget(self.btnBrowse)

        form = QtWidgets.QFormLayout(); root.addLayout(form)
        self.spinBlur = QtWidgets.QSpinBox(); self.spinBlur.setRange(0,31); self.spinBlur.setValue(3)
        self.spinStep = QtWidgets.QSpinBox(); self.spinStep.setRange(1,30); self.spinStep.setValue(6)
        self.spinSeg  = QtWidgets.QSpinBox(); self.spinSeg.setRange(5,250); self.spinSeg.setValue(18)
        form.addRow("Blur:", self.spinBlur); form.addRow("Sample step:", self.spinStep); form.addRow("Segment duration (ms):", self.spinSeg)

        ctrl = QtWidgets.QHBoxLayout(); root.addLayout(ctrl)
        self.btnPrep = QtWidgets.QPushButton("Prepare")
        self.btnStart = QtWidgets.QPushButton("Start drawing")
        self.btnStop  = QtWidgets.QPushButton("Stop")
        ctrl.addWidget(self.btnPrep); ctrl.addWidget(self.btnStart); ctrl.addWidget(self.btnStop)

        # progress bar green
        self.bar = QProgressBar(); self.bar.setRange(0,100); self.bar.setValue(0)
        root.addWidget(self.bar)

        hl = QtWidgets.QHBoxLayout(); root.addLayout(hl)
        self.preview = QtWidgets.QLabel("Preview / mask will appear here")
        self.preview.setMinimumSize(420, 320)
        self.preview.setFrameShape(QtWidgets.QFrame.Box)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        hl.addWidget(self.preview, 0)

        self.log = QtWidgets.QTextEdit(); self.log.setReadOnly(True); hl.addWidget(self.log, 1)

        # signals
        self.btnBrowse.clicked.connect(self.onBrowse)
        self.btnRefresh.clicked.connect(self.refresh_devices)
        self.btnRestart.clicked.connect(self.onRestartADB)
        self.combo.currentIndexChanged.connect(self.onSelect)
        self.btnPrep.clicked.connect(self.onPrep)
        self.btnStart.clicked.connect(self.onStart)
        self.btnStop.clicked.connect(self.onStop)

        # autoscan
        self.timer = QtCore.QTimer(self); self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh_devices); self.timer.start()

        if not adb_path_ok():
            QMessageBox.critical(self, "ADB not found", "ไม่พบ adb.exe ใน PATH")
        self.refresh_devices(initial=True)

    def logmsg(self, s):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {s}")
        self.log.moveCursor(QtGui.QTextCursor.End)

    def set_preview(self, mask):
        img = make_preview(mask)
        h, w = img.shape[:2]
        qimg = QtGui.QImage(img.data, w, h, 3*w, QtGui.QImage.Format_BGR888)
        self.preview.setPixmap(QtGui.QPixmap.fromImage(qimg))

    # devicee
    def refresh_devices(self, initial=False):
        devs = adb_devices()
        cur = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        if devs:
            self.combo.addItems(devs)
            i = self.combo.findText(cur); 
            if i >= 0: self.combo.setCurrentIndex(i)
            if self.timer.isActive():
                self.timer.stop()
                self.logmsg("✅ Device detected — stop scanning to reduce load.")
        else:
            self.combo.addItem("No device")
            self.lblModel.setText("Model: -"); self.lblSize.setText("Screen: -")
        self.combo.blockSignals(False)
        self.logmsg("Devices: " + (", ".join(devs) if devs else "none"))

        if devs and (self.serial is None or self.serial not in devs):
            self.serial = devs[0]; self.update_device_info()
        if initial and not devs:
            self.logmsg("if u see unauthorized pls Allow USB debugging!!!")

    def update_device_info(self):
        if not self.serial: return
        model = get_device_model(self.serial) or "-"
        size  = get_screen_size(self.serial)
        self.lblModel.setText(f"Model: {model}")
        self.lblSize.setText(f"Screen: {size[0]}x{size[1]}" if size else "Screen: -")
        self.logmsg(f"Selected: {self.serial} | Model: {model} | Size: {size}")

    def onSelect(self, _i):
        t = self.combo.currentText()
        self.serial = None if (not t or t=="No device") else t
        if self.serial: self.update_device_info()

    # actions
    def onRestartADB(self):
        self.logmsg("Restarting ADB server…")
        ok = adb_restart_server()
        self.logmsg("ADB restarted" if ok else "ADB restart failed")
        self.timer.start(); self.refresh_devices()

    def onBrowse(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Select PNG/JPG", "", "Images (*.png *.jpg *.jpeg)")
        if not fn: return
        fn = os.path.normpath(fn)
        self.fileLine.setText(fn)
        try:
            size = get_screen_size(self.serial) if self.serial else (1080,1920)
            mask = preprocess_image(fn, size[0], size[1], blur=self.spinBlur.value())
            self.set_preview(mask)
        except Exception as e:
            self.logmsg(f"Preview error: {e}")

    def onPrep(self):
        QMessageBox.information(self, "Prepare",
            "1) open ig\n" \
            "2) go to draw\n" \
            "3) press Start drawing")

    def onStart(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "drawing"); return
        if not self.serial:
            QMessageBox.warning(self, "No device", "No connect"); return
        fn = os.path.normpath(self.fileLine.text().strip())
        if not fn or not os.path.exists(fn):
            QMessageBox.warning(self, "No file", "pick file PNG/JPG"); return

        self.bar.setValue(0)
        self.btnStart.setEnabled(False)

        self.worker = DrawWorker(
            self.serial, fn,
            blur=self.spinBlur.value(),
            step=self.spinStep.value(),
            seg_ms=self.spinSeg.value()
        )
        self.worker.log.connect(self.logmsg)
        self.worker.percent.connect(self.bar.setValue)
        self.worker.done.connect(self.onDone)
        self.worker.failed.connect(self.onFailed)
        self.worker.start()
        self.logmsg("Drawing thread started")

    def onDone(self):
        self.logmsg("Finished ✅")
        self.btnStart.setEnabled(True)
        self.worker = None

    def onFailed(self, msg):
        self.logmsg("ERROR: " + msg)
        self.btnStart.setEnabled(True)
        self.worker = None

    def onStop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.logmsg("Stopping…")
        else:
            self.logmsg("No running job")

if __name__ == "__main__":
    import os, sys
    from PyQt5 import QtWidgets, QtGui
    app = QtWidgets.QApplication(sys.argv)
    base_dir = os.path.dirname(__file__)
    icon_path = os.path.join(base_dir, "hka.png")
    icon = QtGui.QIcon(icon_path)
    app.setWindowIcon(icon)
    apply_theme(app)
    w = Main()
    w.setWindowIcon(icon)
    w.setWindowTitle("InsDraw ADB")
    w.show()
    sys.exit(app.exec_())

