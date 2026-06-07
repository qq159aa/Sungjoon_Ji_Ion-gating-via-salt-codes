import sys
import time
import os
import re
import pyvisa
import serial
import pandas as pd
import numpy as np
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QHBoxLayout, QFileDialog, QSplitter
)
from PyQt5.QtCore import QTimer, QThread, pyqtSignal, Qt

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


# ============================================================
# USER SETTINGS
# ============================================================

# Keithley measurement settings
MEASUREMENT_COUNT = 1000000
SAMPLING_INTERVAL_SEC = 0.1
SOURCE_VOLTAGE = 1.0
CURRENT_RANGE = 1e-7
NPLC = 0.01

# Arduino settings
ARDUINO_PORT = "COMX"  # Update with your Arduino port (e.g., "COM3" on Windows or "/dev/ttyACM0" on Linux)
ARDUINO_BAUDRATE = 9600

# N2 / Arduino trigger timing# 
ARDUINO_START_DELAY_SEC = 60.0

# Arduino trigger command
ARDUINO_START_COMMAND = b"1"

# Plot settings
PLOT_UPDATE_INTERVAL_MS = 1000
LIVE_PLOT_MAX_POINTS = 1000
FULL_PLOT_MAX_POINTS = 840

# Safety stop
MAX_MEASUREMENT_TIME_SEC = 1000000


# ============================================================
# Measurement Thread
# ============================================================

class MeasurementThread(QThread):
    arduino_start_signal = pyqtSignal()
    data_collected = pyqtSignal(list, list)
    log_signal = pyqtSignal(str)
    new_data_signal = pyqtSignal(float, float)

    def __init__(self, inst, count, interval, arduino_start_delay):
        super().__init__()
        self.inst = inst
        self.count = count
        self.interval = interval
        self.arduino_start_delay = arduino_start_delay

        self.running = True
        self.data = []
        self.timestamps = []
        self.start_time = None

    def run(self):
        self.start_time = time.time()
        arduino_triggered = False

        for _ in range(self.count):
            if not self.running:
                break

            timestamp = time.time() - self.start_time

            if timestamp >= MAX_MEASUREMENT_TIME_SEC:
                self.log_signal.emit(
                    f" {MAX_MEASUREMENT_TIME_SEC}."
                )
                break

            try:
                val = float(self.inst.query("print(smua.measure.i())").strip())
                
                if (not arduino_triggered) and (timestamp >= self.arduino_start_delay):
                    self.arduino_start_signal.emit()
                    arduino_triggered = True

                self.data.append(val)
                self.timestamps.append(timestamp)

                self.log_signal.emit(f"{timestamp:.3f} s: {val:.5e} A")
                self.new_data_signal.emit(timestamp, val)

            except Exception as e:
                self.log_signal.emit(f"Error {e}")
                break

            time.sleep(self.interval)

        self.data_collected.emit(self.data, self.timestamps)

    def stop(self):
        self.running = False


# ============================================================
# Arduino Read Thread
# ============================================================

class ArduinoReadThread(QThread):
    message_signal = pyqtSignal(str)

    def __init__(self, serial_obj):
        super().__init__()
        self.serial = serial_obj
        self.running = True

    def run(self):
        while self.running:
            try:
                if self.serial and self.serial.in_waiting:
                    line = self.serial.readline().decode(
                        "utf-8",
                        errors="replace"
                    ).strip()

                    if line:
                        self.message_signal.emit(line)

            except Exception as e:
                self.message_signal.emit(f"Error reading Arduino: {e}")

            time.sleep(0.05)

    def stop(self):
        self.running = False


# ============================================================
# Main GUI
# ============================================================

class KeithleyGUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Keithley 2600 GPIB GUI")
        self.resize(1000, 900)

        self.init_ui()

        self.rm = pyvisa.ResourceManager()
        self.inst = None

        self.thread = None
        self.arduino = None
        self.arduino_thread = None

        # Arduino raw messages
        # [(timestamp, raw_message), ...]
        self.arduino_messages = []

        # Temperature / humidity data
        # [(timestamp, temp_C, hum_RH, raw_message), ...]
        self.th_data = []

        # Measurement settings
        self.measurement_count = MEASUREMENT_COUNT
        self.sampling_interval = SAMPLING_INTERVAL_SEC
        self.source_voltage = SOURCE_VOLTAGE
        self.current_range = CURRENT_RANGE
        self.nplc = NPLC

        # Arduino settings
        self.arduino_port = ARDUINO_PORT
        self.arduino_baudrate = ARDUINO_BAUDRATE
        self.arduino_start_delay = ARDUINO_START_DELAY_SEC
        self.arduino_start_command = ARDUINO_START_COMMAND

        # Live plot data
        self.live_data = []
        self.live_timestamps = []

        self.plot_timer = QTimer()
        self.plot_timer.setInterval(PLOT_UPDATE_INTERVAL_MS)
        self.plot_timer.timeout.connect(self.update_plot)

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------

    def init_ui(self):
        layout = QVBoxLayout()

        self.status_label = QLabel("No connection")
        self.status_label.setMaximumHeight(50)
        layout.addWidget(self.status_label)

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(400)

        self.ax1 = self.figure.add_subplot(211)
        self.ax2 = self.figure.add_subplot(212)

        layout.addWidget(self.canvas)

        splitter = QSplitter(Qt.Horizontal)

        self.keithley_log_output = QPlainTextEdit(readOnly=True)
        self.keithley_log_output.setMinimumHeight(200)

        self.arduino_log_output = QPlainTextEdit(readOnly=True)
        self.arduino_log_output.setMinimumHeight(200)

        splitter.addWidget(self.keithley_log_output)
        splitter.addWidget(self.arduino_log_output)

        layout.addWidget(splitter)

        button_layout = QHBoxLayout()

        self.connect_button = QPushButton("Connect and Start Measurement")
        self.connect_button.setMinimumSize(200, 50)

        self.stop_button = QPushButton("Stop Experiment")
        self.stop_button.setMinimumSize(200, 50)

        self.connect_button.clicked.connect(self.run_measurement)
        self.stop_button.clicked.connect(self.stop_measurement)

        self.stop_button.setEnabled(False)

        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.stop_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    # --------------------------------------------------------
    # Log
    # --------------------------------------------------------

    def log(self, message):
        self._append_log(self.keithley_log_output, message)

    def log_arduino(self, message):
        self._append_log(self.arduino_log_output, message)

    def _append_log(self, widget, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {message}"

        widget.appendPlainText(full_message)

        scrollbar = widget.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 10:
            scrollbar.setValue(scrollbar.maximum())

    # --------------------------------------------------------
    # Arduino message parsing
    # --------------------------------------------------------

    def parse_temp_humidity(self, msg):
        """
        Parse temperature and humidity from Arduino message

        Supported formats:
        1) TH,TEMP:25.84,HUMID:38.91
        2) TEMP:25.84,HUMID:38.91
        3) 25.84,38.91
        """

        text = msg.strip()

        th_match = re.search(
            r"TH\s*,\s*TEMP\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*HUMID\s*:\s*(-?\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE
        )

        if th_match:
            return float(th_match.group(1)), float(th_match.group(2))

        generic_match = re.search(
            r"TEMP\s*:\s*(-?\d+(?:\.\d+)?)\s*,?\s*HUMID\s*:\s*(-?\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE
        )

        if generic_match:
            return float(generic_match.group(1)), float(generic_match.group(2))

        pair_match = re.match(
            r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$",
            text
        )

        if pair_match:
            return float(pair_match.group(1)), float(pair_match.group(2))

        return None, None

    # --------------------------------------------------------
    # Measurement start
    # --------------------------------------------------------

    def run_measurement(self):
        self.ax1.clear()
        self.ax2.clear()

        self.live_data.clear()
        self.live_timestamps.clear()
        self.arduino_messages.clear()
        self.th_data.clear()

        self.canvas.draw_idle()

        try:
            addresses = [
                r for r in self.rm.list_resources()
                if r.startswith("GPIB")
            ]

            if not addresses:
                self.log("GPIB device not found.")
                return

            self.inst = self.rm.open_resource(addresses[0])
            self.inst.timeout = 20000

            self.log(f"GPIB device connected: {addresses[0]}")

            # Arduino connection
            try:
                self.arduino = serial.Serial(
                    self.arduino_port,
                    self.arduino_baudrate,
                    timeout=1
                )

                time.sleep(2)

                self.log(
                    f"Arduino connected: {self.arduino_port}, "
                    f"start delay: {self.arduino_start_delay:.1f} s"
                )

            except Exception as e:
                self.arduino = None
                self.log(f"Failed to connect Arduino: {e}")

            self._setup_keithley()

            self.plot_timer.start()

            self.thread = MeasurementThread(
                self.inst,
                self.measurement_count,
                self.sampling_interval,
                self.arduino_start_delay
            )

            self.thread.data_collected.connect(self.on_data_collected)
            self.thread.log_signal.connect(self.log)
            self.thread.arduino_start_signal.connect(self.trigger_arduino)
            self.thread.new_data_signal.connect(self.add_live_data)

            self.thread.start()

            if self.arduino:
                self.arduino_thread = ArduinoReadThread(self.arduino)
                self.arduino_thread.message_signal.connect(self.handle_arduino_message)
                self.arduino_thread.start()

            self.connect_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.status_label.setText("Device Status: Measuring")

        except Exception as e:
            self.status_label.setText("Device Status: Error")
            self.log(f"Error occurred: {e}")

            try:
                if self.inst:
                    self.log(f"Device error queue: {self.inst.query('errorqueue.next()')}")
            except Exception:
                self.log("Failed to retrieve error queue")

    # --------------------------------------------------------
    # Keithley setup
    # --------------------------------------------------------

    def _setup_keithley(self):
        self.inst.write("abort")
        self.inst.write("smua.source.output = smua.OUTPUT_OFF")
        self.inst.write("*CLS")
        self.inst.write("smua.reset()")

        time.sleep(0.5)

        setup_cmds = [
            "smua.source.func = smua.OUTPUT_DCVOLTS",
            f"smua.source.levelv = {self.source_voltage}",
            "smua.source.output = smua.OUTPUT_ON",
            "smua.measure.func = smua.MEASURE_DCAMPS",
            "smua.measure.autorangei = smua.AUTO_OFF",
            f"smua.measure.rangei = {self.current_range}",
            "smua.nvbuffer1.clear()",
            "smua.nvbuffer1.appendmode = 1",
            f"smua.nvbuffer1.nplc = {self.nplc}"
        ]

        for cmd in setup_cmds:
            self.inst.write(cmd)

    # --------------------------------------------------------
    # Arduino trigger
    # --------------------------------------------------------

    def trigger_arduino(self):
        if self.arduino:
            try:
                self.arduino.write(self.arduino_start_command)

                self.log(
                    f"{self.arduino_start_delay:.1f}sec elapsed: "
                    f"Arduino start signal sent"
                )

            except Exception as e:
                self.log(f"Arduino transmission error: {e}")

        else:
            self.log(
                f"{self.arduino_start_delay:.1f}sec elapsed: "
                f"Arduino is not connected, failed to send start signal"
            )

    # --------------------------------------------------------
    # Arduino receive
    # --------------------------------------------------------

    def handle_arduino_message(self, msg):
        timestamp = (
            time.time() - self.thread.start_time
            if self.thread and self.thread.start_time
            else 0.0
        )
        
        self.arduino_messages.append((timestamp, msg))
        self.log_arduino(msg)
        if msg.strip().upper().startswith("TH"):
            temp_c, rh = self.parse_temp_humidity(msg)

            if temp_c is not None and rh is not None:
                self.th_data.append((timestamp, temp_c, rh, msg))

    # --------------------------------------------------------
    # Live plot
    # --------------------------------------------------------

    def add_live_data(self, timestamp, current):
        self.live_timestamps.append(timestamp)
        self.live_data.append(current)

        ts = self.live_timestamps[-LIVE_PLOT_MAX_POINTS:]
        data = self.live_data[-LIVE_PLOT_MAX_POINTS:]

        self.ax1.clear()
        self.ax1.plot(ts, data, label="Real time data")
        self.ax1.set_ylabel("Current (A)")
        self.ax1.set_title("Real-time Current Measurement")
        self.ax1.grid(True)
        self.ax1.legend()

        self.canvas.draw_idle()

    def update_plot(self):
        if not self.thread or not self.thread.timestamps:
            return

        def downsample(timestamps, data, max_points=FULL_PLOT_MAX_POINTS):
            if len(timestamps) <= max_points:
                return timestamps, data

            idx = np.linspace(
                0,
                len(timestamps) - 1,
                max_points,
                dtype=int
            )

            return [timestamps[i] for i in idx], [data[i] for i in idx]

        full_ts = self.thread.timestamps.copy()
        full_data = self.thread.data.copy()

        full_ts, full_data = downsample(full_ts, full_data)

        self.ax2.clear()
        self.ax2.plot(full_ts, full_data, label="Full data", linestyle="--")
        self.ax2.set_xlabel("Time (s)")
        self.ax2.set_ylabel("Current (A)")
        self.ax2.set_title("Full Current Data")
        self.ax2.grid(True)
        self.ax2.legend()

        self.canvas.draw_idle()

    # --------------------------------------------------------
    # Stop measurement
    # --------------------------------------------------------

    def stop_measurement(self):
        if self.thread:
            self.thread.stop()
            self.thread.wait()

        if self.arduino_thread:
            self.arduino_thread.stop()
            self.arduino_thread.wait()

        self.plot_timer.stop()

        self.ax1.clear()
        self.ax1.set_title("Real-time Current Measurement")
        self.ax1.set_ylabel("Current (A)")
        self.ax1.grid(True)

        self.ax2.clear()
        self.ax2.set_title("Full Current Data")
        self.ax2.set_xlabel("Time (s)")
        self.ax2.set_ylabel("Current (A)")
        self.ax2.grid(True)

        self.canvas.draw_idle()

        try:
            if self.inst:
                self.inst.write("smua.source.output = smua.OUTPUT_OFF")
        except Exception as e:
            self.log(f"Keithley output OFF fail: {e}")

        try:
            if self.arduino:
                self.arduino.close()
                self.arduino = None
        except Exception as e:
            self.log(f"Arduino port close fail: {e}")

        self.connect_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        self.status_label.setText("Instrument state: Stopped")

    # --------------------------------------------------------
    # Data collected
    # --------------------------------------------------------

    def on_data_collected(self, data, timestamps):
        self.status_label.setText("Instrument state: Measurement completed and output OFF")

        try:
            if self.inst:
                self.inst.write("smua.source.output = smua.OUTPUT_OFF")
        except Exception as e:
            self.log(f"Keithley output OFF fail: {e}")

        default_filename = (
            f"keithley_gui_data_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )

        default_path = os.path.join(
            os.path.expanduser("~"),
            "Desktop",
            default_filename
        )

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save as Excel file",
            default_path,
            "Excel Files (*.xlsx)"
        )

        if filepath:
            if not filepath.lower().endswith(".xlsx"):
                filepath += ".xlsx"

            base, ext = os.path.splitext(filepath)
            version = 1

            while os.path.exists(filepath):
                filepath = f"{base}_v{version}{ext}"
                version += 1

            self._save_to_excel(filepath, data, timestamps)

        else:
            self.log("Save cancelled")

        try:
            if self.arduino_thread:
                self.arduino_thread.stop()
                self.arduino_thread.wait()
        except Exception:
            pass

        try:
            if self.arduino:
                self.arduino.close()
                self.arduino = None
        except Exception:
            pass

        self.connect_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    # --------------------------------------------------------
    # Save Excel
    # --------------------------------------------------------

    def _save_to_excel(self, filepath, data, timestamps):
        try:
            current_df = pd.DataFrame({
                "Timestamps (sec)": timestamps,
                "Current (A)": data
            })

            th_df = pd.DataFrame(
                self.th_data,
                columns=[
                    "Timestamps (sec)",
                    "Temperature (C)",
                    "Humidity (%RH)",
                    "Raw Message"
                ]
            )

            if not th_df.empty:
                th_df["Timestamps (sec)"] = pd.to_numeric(
                    th_df["Timestamps (sec)"],
                    errors="coerce"
                )

                th_df["Temperature (C)"] = pd.to_numeric(
                    th_df["Temperature (C)"],
                    errors="coerce"
                )

                th_df["Humidity (%RH)"] = pd.to_numeric(
                    th_df["Humidity (%RH)"],
                    errors="coerce"
                )

                th_df = th_df.dropna(
                    subset=["Temperature (C)", "Humidity (%RH)"]
                ).reset_index(drop=True)
                
                th_df = th_df[
                    [
                        "Timestamps (sec)",
                        "Temperature (C)",
                        "Humidity (%RH)"
                    ]
                ]

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                current_df.to_excel(
                    writer,
                    sheet_name="Current",
                    index=False
                )

                th_df.to_excel(
                    writer,
                    sheet_name="Temp_Humidity",
                    index=False
                )

            self.log(f"Excel save completed: {filepath}")
            self.log(f"Current data count: {len(current_df)}")
            self.log(f"Temperature/Humidity data count: {len(th_df)}")

        except Exception as e:
            self.log(f"Excel save failed: {e}")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = KeithleyGUI()
    gui.show()
    sys.exit(app.exec_())