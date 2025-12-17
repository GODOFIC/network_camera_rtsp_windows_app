import socket
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIntValidator, QDoubleValidator
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGridLayout,
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
)


@dataclass
class UdpRequest:
    host: str
    port: int
    payload: str
    timeout_ms: int = 1200  # 等待设备回复的超时时间


class UdpWorker(QThread):
    finished = Signal(str)   # 成功/失败信息（带回包）
    error = Signal(str)      # 错误信息

    def __init__(self, req: UdpRequest):
        super().__init__()
        self.req = req

    def run(self) -> None:
        try:
            reply = udp_exchange(
                self.req.host,
                self.req.port,
                self.req.payload,
                timeout_ms=self.req.timeout_ms,
            )
            self.finished.emit(reply)
        except Exception as e:
            self.error.emit(str(e))


def udp_exchange(host: str, port: int, payload: str, timeout_ms: int = 1200) -> str:
    """
    向 udp_cfgd 发送 ASCII 命令，并等待单次 UDP 回复。
    """
    if not host:
        raise ValueError("host is empty")
    if port <= 0 or port > 65535:
        raise ValueError("port out of range (1..65535)")

    data = payload.encode("ascii", errors="strict")

    # Windows 下 UDP socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout_ms / 1000.0)
        s.sendto(data, (host, port))
        resp, _ = s.recvfrom(2048)
        # 服务端返回 ASCII（OK ... / ERR ... / 或 GET 的四元组）
        return resp.decode("ascii", errors="replace").strip()
    except socket.timeout:
        raise TimeoutError(f"timeout waiting reply (>{timeout_ms}ms)")
    finally:
        s.close()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("udp_cfgd 简易上位机（UDP 配置视频流参数）")
        self.resize(720, 420)

        self._worker: Optional[UdpWorker] = None

        root = QWidget()
        self.setCentralWidget(root)

        layout = QGridLayout(root)

        # --- 连接参数 ---
        conn_box = QGroupBox("目标设备")
        conn_layout = QFormLayout(conn_box)

        self.ip_edit = QLineEdit("192.168.144.123")  # 改成你常用的默认 IP
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5600)

        conn_layout.addRow("IP 地址", self.ip_edit)
        conn_layout.addRow("UDP 端口", self.port_spin)

        # --- 配置参数 ---
        cfg_box = QGroupBox("STREAM_LIVE 参数（一次性设置四项）")
        cfg_layout = QFormLayout(cfg_box)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 16384)
        self.width_spin.setValue(1280)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 16384)
        self.height_spin.setValue(720)

        self.bitrate_spin = QDoubleSpinBox()
        self.bitrate_spin.setDecimals(3)
        self.bitrate_spin.setRange(0.001, 9999.999)  # 服务端要求 (0,10000)
        self.bitrate_spin.setSingleStep(0.1)
        self.bitrate_spin.setValue(8.0)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setValue(120)

        cfg_layout.addRow("width", self.width_spin)
        cfg_layout.addRow("height", self.height_spin)
        cfg_layout.addRow("bitrate", self.bitrate_spin)
        cfg_layout.addRow("fps", self.fps_spin)

        # --- 按钮区 ---
        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("应用配置（SET）")
        self.get_btn = QPushButton("读取当前（GET）")  # 可选：如果你要“只做一个功能”，删掉它即可
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.get_btn.clicked.connect(self.on_get_clicked)

        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.get_btn)
        btn_row.addStretch(1)

        # --- 日志 ---
        log_box = QGroupBox("通信日志")
        log_layout = QVBoxLayoutCompat(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)

        # 布局摆放
        layout.addWidget(conn_box, 0, 0)
        layout.addWidget(cfg_box, 1, 0)
        layout.addLayout(btn_row, 2, 0)
        layout.addWidget(log_box, 0, 1, 3, 1)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 2)

        self._set_busy(False)

    def _append_log(self, line: str) -> None:
        self.log_view.append(line)

    def _set_busy(self, busy: bool) -> None:
        self.apply_btn.setEnabled(not busy)
        self.get_btn.setEnabled(not busy)
        self.ip_edit.setEnabled(not busy)
        self.port_spin.setEnabled(not busy)
        self.width_spin.setEnabled(not busy)
        self.height_spin.setEnabled(not busy)
        self.bitrate_spin.setEnabled(not busy)
        self.fps_spin.setEnabled(not busy)

    def _start_request(self, payload: str) -> None:
        host = self.ip_edit.text().strip()
        port = int(self.port_spin.value())

        self._append_log(f">>> {host}:{port} 发送: {payload}")
        self._set_busy(True)

        req = UdpRequest(host=host, port=port, payload=payload, timeout_ms=1200)
        self._worker = UdpWorker(req)
        self._worker.finished.connect(self._on_reply)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda _: self._set_busy(False))
        self._worker.error.connect(lambda _: self._set_busy(False))
        self._worker.start()

    def _on_reply(self, reply: str) -> None:
        self._append_log(f"<<< 收到: {reply}")

    def _on_error(self, msg: str) -> None:
        self._append_log(f"!!! 错误: {msg}")

    def on_apply_clicked(self) -> None:
        # 组装四元组 SET 命令：服务端支持 "SET 1280 720 8.0 120"
        w = int(self.width_spin.value())
        h = int(self.height_spin.value())
        b = float(self.bitrate_spin.value())
        f = int(self.fps_spin.value())

        # 保留最多 3 位小数，符合你服务端 parse_double + format_bitrate 的习惯
        payload = f"SET {w} {h} {b:.3f} {f}"
        self._start_request(payload)

    def on_get_clicked(self) -> None:
        self._start_request("GET")


class QVBoxLayoutCompat(QHBoxLayout):
    """
    兼容性：用 QHBoxLayout 伪装 VBoxLayout 的最小替代，避免额外 import。
    实际上 PySide6 里你也可以直接 from PySide6.QtWidgets import QVBoxLayout。
    """
    def __init__(self, parent=None):
        from PySide6.QtWidgets import QVBoxLayout
        # 运行时替换自身为真正的 QVBoxLayout
        self.__class__ = QVBoxLayout  # type: ignore
        QVBoxLayout.__init__(self, parent)  # type: ignore


def main() -> int:
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
