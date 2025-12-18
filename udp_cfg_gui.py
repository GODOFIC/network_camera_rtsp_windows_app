import socket
import sys
import os
import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, Slot, QRect, QSize, QObject
from PySide6.QtGui import QImage, QIcon, QPainter, QPaintEvent, QColor
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QTextEdit,
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QComboBox
)

# ==========================================
# 0. 多语言配置
# ==========================================
LANG_TEXTS = {
    "title": {"en": "Device Configurator & Stream Viewer", "zh": "设备配置与高清预览工具"},
    "grp_conn": {"en": "Device Target", "zh": "设备连接参数"},
    "lbl_ip": {"en": "IP Address", "zh": "IP 地址"},
    "lbl_port": {"en": "Command Port", "zh": "命令端口"},
    "grp_cfg": {"en": "Image Sensor Parameters", "zh": "图像传感器参数 (SET)"},
    "lbl_w": {"en": "Res Width", "zh": "分辨率宽"},
    "lbl_h": {"en": "Res Height", "zh": "分辨率高"},
    "lbl_bit": {"en": "Bitrate (Mbps)", "zh": "码率 (Mbps)"},
    "lbl_fps": {"en": "Frame Rate", "zh": "帧率 (FPS)"},
    "btn_apply": {"en": "Apply Settings", "zh": "应用配置"},
    "btn_read": {"en": "Read Config", "zh": "读取参数"},
    "grp_preview": {"en": "Live Preview Control", "zh": "RTSP 预览控制"},
    "lbl_source": {"en": "Stream Source:", "zh": "流地址:"},
    "btn_start": {"en": "Start Live View", "zh": "开始拉流"},
    "btn_stop": {"en": "Stop Live View", "zh": "停止拉流"},
    "grp_log": {"en": "System Logs", "zh": "系统日志"},
    "grp_monitor": {"en": "Live Monitor", "zh": "实时监控画面"},
    "no_signal": {"en": "NO SIGNAL", "zh": "无信号 / 等待连接"},
    "lang_sel": {"en": "Language/语言", "zh": "语言/Language"}
}


# ==========================================
# 1. UDP 模块 (保持不变)
# ==========================================
@dataclass
class UdpRequest:
    host: str
    port: int
    payload: str
    timeout_ms: int = 1200


class UdpWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, req: UdpRequest, parent=None):
        super().__init__(parent)
        self.req = req

    def run(self) -> None:
        try:
            reply = udp_exchange(
                self.req.host,
                self.req.port,
                self.req.payload,
                self.req.timeout_ms,
            )
            self.finished.emit(reply)
        except Exception as e:
            self.error.emit(str(e))


def udp_exchange(host: str, port: int, payload: str, timeout_ms: int = 1200) -> str:
    if not host:
        raise ValueError("Host is empty")
    data = payload.encode("ascii", errors="strict")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout_ms / 1000.0)
        s.sendto(data, (host, port))
        resp, _ = s.recvfrom(2048)
        return resp.decode("ascii", errors="replace").strip()
    except socket.timeout:
        raise TimeoutError(f"Timeout (>{timeout_ms}ms)")
    finally:
        s.close()


# ==========================================
# 2. 视频解码线程 (已移除锐化，调亮画面)
# ==========================================
class VideoStreamWorker(QThread):
    frame_received = Signal(QImage)
    log_message = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.running = True
        self._cap = None

    def run(self):
        self.log_message.emit(f"[System] Connecting to: {self.url}")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

        try:
            self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not self._cap.isOpened():
                self.log_message.emit("[Error] Unable to open stream.")
                return

            self.log_message.emit("[System] Stream locked. Decoding...")

            while self.running:
                ret, frame = self._cap.read()

                if not self.running:
                    break

                if not ret:
                    if self.running:
                        self.log_message.emit("[System] Stream signal lost. Retrying...")
                        QThread.msleep(500)
                        self._cap.release()
                        self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                        continue
                    else:
                        break


                try:
                    frame = cv2.convertScaleAbs(frame, alpha=1.00, beta=-25)

                    # BGR 转 RGB
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w

                    qt_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()

                    if self.running:
                        self.frame_received.emit(qt_img)
                except Exception:
                    pass

        except Exception as e:
            self.log_message.emit(f"[Error] Thread crash: {e}")
        finally:
            if self._cap:
                self._cap.release()
            self.log_message.emit("[System] Worker thread stopped.")

    def stop(self):
        self.running = False
        self.wait()


# ==========================================
# 3. 渲染控件 (保持不变)
# ==========================================
class VideoCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_image: Optional[QImage] = None
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: #111;")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.no_signal_text = "NO SIGNAL"

    @Slot(QImage)
    def set_frame(self, image: QImage):
        self.current_image = image
        self.update()

    def set_placeholder_text(self, text: str):
        self.no_signal_text = text
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        if self.current_image and not self.current_image.isNull():
            target_rect = self._calculate_aspect_ratio_rect(
                self.current_image.size(), self.size()
            )
            painter.fillRect(self.rect(), QColor(17, 17, 17))
            painter.drawImage(target_rect, self.current_image)
        else:
            painter.setPen(QColor(150, 150, 150))
            font = painter.font()
            font.setPointSize(16)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, self.no_signal_text)

    def _calculate_aspect_ratio_rect(self, img_size: QSize, widget_size: QSize) -> QRect:
        if img_size.isEmpty() or widget_size.isEmpty():
            return QRect(0, 0, 0, 0)
        img_ratio = img_size.width() / img_size.height()
        widget_ratio = widget_size.width() / widget_size.height()
        new_w, new_h = 0, 0
        if widget_ratio > img_ratio:
            new_h = widget_size.height()
            new_w = int(new_h * img_ratio)
        else:
            new_w = widget_size.width()
            new_h = int(new_w / img_ratio)
        x = (widget_size.width() - new_w) // 2
        y = (widget_size.height() - new_h) // 2
        return QRect(x, y, new_w, new_h)

    def clear_screen(self):
        self.current_image = None
        self.update()


# ==========================================
# 4. 主窗口 (保持不变)
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.current_lang = "zh"

        icon_path = os.path.join(os.getcwd(), "zh-512x512.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.resize(1150, 700)
        self._worker: Optional[UdpWorker] = None
        self._video_worker: Optional[VideoStreamWorker] = None

        self.init_ui()
        self.update_texts()

    def init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)

        # Left Panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 5, 0)

        # Language
        lang_row = QHBoxLayout()
        self.lbl_lang = QLabel("Language:")
        self.combo_lang = QComboBox()
        self.combo_lang.addItem("简体中文", "zh")
        self.combo_lang.addItem("English", "en")
        self.combo_lang.currentIndexChanged.connect(self.on_lang_changed)
        lang_row.addStretch()
        lang_row.addWidget(self.lbl_lang)
        lang_row.addWidget(self.combo_lang)
        left_layout.addLayout(lang_row)

        # Connection
        self.conn_box = QGroupBox()
        conn_layout = QFormLayout(self.conn_box)
        self.ip_edit = QLineEdit("192.168.144.123")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5600)
        self.lbl_ip_title = QLabel()
        self.lbl_port_title = QLabel()
        conn_layout.addRow(self.lbl_ip_title, self.ip_edit)
        conn_layout.addRow(self.lbl_port_title, self.port_spin)

        # Config
        self.cfg_box = QGroupBox()
        cfg_layout = QFormLayout(self.cfg_box)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 16384)
        self.width_spin.setValue(1920)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 16384)
        self.height_spin.setValue(1080)
        self.bitrate_spin = QDoubleSpinBox()
        self.bitrate_spin.setDecimals(3)
        self.bitrate_spin.setRange(0.001, 9999.999)
        self.bitrate_spin.setSingleStep(0.1)
        self.bitrate_spin.setValue(8.0)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setValue(60)
        self.lbl_w_title = QLabel()
        self.lbl_h_title = QLabel()
        self.lbl_bit_title = QLabel()
        self.lbl_fps_title = QLabel()
        cfg_layout.addRow(self.lbl_w_title, self.width_spin)
        cfg_layout.addRow(self.lbl_h_title, self.height_spin)
        cfg_layout.addRow(self.lbl_bit_title, self.bitrate_spin)
        cfg_layout.addRow(self.lbl_fps_title, self.fps_spin)

        # Buttons
        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton()
        self.get_btn = QPushButton()
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.get_btn.clicked.connect(self.on_get_clicked)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.get_btn)

        # RTSP
        self.rtsp_box = QGroupBox()
        rtsp_layout = QVBoxLayout(self.rtsp_box)
        self.rtsp_url_edit = QLineEdit("rtsp://192.168.144.123/main_stream")
        self.stream_btn = QPushButton()
        self.stream_btn.setCheckable(True)
        self.stream_btn.setStyleSheet("""
            QPushButton:checked { background-color: #d32f2f; color: white; border: none; }
        """)
        self.stream_btn.clicked.connect(self.on_stream_toggle)
        self.lbl_source_title = QLabel()
        rtsp_layout.addWidget(self.lbl_source_title)
        rtsp_layout.addWidget(self.rtsp_url_edit)
        rtsp_layout.addWidget(self.stream_btn)

        # Log
        self.log_box = QGroupBox()
        log_layout = QVBoxLayout(self.log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        log_layout.addWidget(self.log_view)

        left_layout.addWidget(self.conn_box)
        left_layout.addWidget(self.cfg_box)
        left_layout.addLayout(btn_row)
        left_layout.addWidget(self.rtsp_box)
        left_layout.addWidget(self.log_box)

        # Right Panel
        self.video_panel = QGroupBox()
        video_layout = QVBoxLayout(self.video_panel)
        video_layout.setContentsMargins(2, 2, 2, 2)
        self.video_canvas = VideoCanvas()
        video_layout.addWidget(self.video_canvas)

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(self.video_panel, 3)

        self._set_busy(False)

    def on_lang_changed(self, index):
        self.current_lang = self.combo_lang.itemData(index)
        self.update_texts()

    def update_texts(self):
        lang = self.current_lang
        t = LANG_TEXTS
        self.setWindowTitle(t["title"][lang])
        self.conn_box.setTitle(t["grp_conn"][lang])
        self.lbl_ip_title.setText(t["lbl_ip"][lang])
        self.lbl_port_title.setText(t["lbl_port"][lang])
        self.cfg_box.setTitle(t["grp_cfg"][lang])
        self.lbl_w_title.setText(t["lbl_w"][lang])
        self.lbl_h_title.setText(t["lbl_h"][lang])
        self.lbl_bit_title.setText(t["lbl_bit"][lang])
        self.lbl_fps_title.setText(t["lbl_fps"][lang])
        self.apply_btn.setText(t["btn_apply"][lang])
        self.get_btn.setText(t["btn_read"][lang])
        self.rtsp_box.setTitle(t["grp_preview"][lang])
        self.lbl_source_title.setText(t["lbl_source"][lang])
        if self.stream_btn.isChecked():
            self.stream_btn.setText(t["btn_stop"][lang])
        else:
            self.stream_btn.setText(t["btn_start"][lang])
        self.log_box.setTitle(t["grp_log"][lang])
        self.video_panel.setTitle(t["grp_monitor"][lang])
        self.video_canvas.set_placeholder_text(t["no_signal"][lang])
        self.lbl_lang.setText(t["lang_sel"][lang])

    def _append_log(self, line: str) -> None:
        self.log_view.append(line)

    def _set_busy(self, busy: bool) -> None:
        self.apply_btn.setEnabled(not busy)
        self.get_btn.setEnabled(not busy)

    def _start_request(self, payload: str) -> None:
        host = self.ip_edit.text().strip()
        port = int(self.port_spin.value())
        self._append_log(f"> CMD: {payload}")
        self._set_busy(True)
        req = UdpRequest(host=host, port=port, payload=payload)
        self._worker = UdpWorker(req, parent=self)
        self._worker.finished.connect(lambda r: self._append_log(f"< ACK: {r}"))
        self._worker.error.connect(lambda e: self._append_log(f"! ERR: {e}"))
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.error.connect(lambda: self._set_busy(False))
        self._worker.start()

    def on_apply_clicked(self):
        p = f"SET {self.width_spin.value()} {self.height_spin.value()} {self.bitrate_spin.value():.3f} {self.fps_spin.value()}"
        self._start_request(p)

    def on_get_clicked(self):
        self._start_request("GET")

    def on_stream_toggle(self, checked: bool):
        lang = self.current_lang
        if checked:
            # === 开始拉流 ===
            url = self.rtsp_url_edit.text().strip()
            self.stream_btn.setText(LANG_TEXTS["btn_stop"][lang])

            if self._video_worker is not None:
                self.stop_stream_logic()

            self._video_worker = VideoStreamWorker(url, parent=self)
            self._video_worker.frame_received.connect(self.video_canvas.set_frame)
            self._video_worker.log_message.connect(self._append_log)
            self._video_worker.finished.connect(self.on_worker_finished)
            self._video_worker.start()
        else:
            # === 停止拉流 ===
            self.stop_stream_logic()

    def stop_stream_logic(self):
        lang = self.current_lang
        self.stream_btn.setText(LANG_TEXTS["btn_start"][lang])
        self.stream_btn.setChecked(False)
        self.video_canvas.clear_screen()

        if self._video_worker:
            self._video_worker.stop()
            try:
                self._video_worker.frame_received.disconnect()
                self._video_worker.log_message.disconnect()
                self._video_worker.finished.disconnect()
            except Exception:
                pass
            self._video_worker.finished.connect(self._video_worker.deleteLater)
            self._video_worker = None
            self._append_log("[System] Stop command sent.")

    def on_worker_finished(self):
        if self.stream_btn.isChecked():
            self.stop_stream_logic()

    def closeEvent(self, event):
        self.stop_stream_logic()
        super().closeEvent(event)


def main() -> int:
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())