"""
PortWatch Pro — Nowoczesny monitor portów + integracja z Dockerem (GUI)
Autor: Ty & Twoja asystentka ;)

Nowości UI (przyjazny, nowoczesny wygląd):
- Układ z panelem szczegółów (QSplitter): tabela + prawy panel „Karta portu/kontenera”.
- Estetyczny pasek narzędzi z szybkim filtrem, segmentami filtrów (Tylko zajęte / Tylko Docker), zakresem portów.
- Kolorowe „chip-y” statusu (FREE/LISTEN/ESTABLISHED) i odznaka 🐳 dla pozycji Docker.
- Menu kontekstowe + przyciski akcji również w panelu szczegółów (Stop/Restart kontenera, Otwórz w przeglądarce, Zakończ proces).
- Przełącznik motywu (Jasny/Ciemny) bez dodatkowych zależności (dwa arkusze QSS).
- Zachowane: skan zakresu, auto-odświeżanie, Docker SDK z fallbackiem na CLI, zabijanie procesu.

Wymagania:
    pip install PySide6 psutil docker

Uruchomienie:
    python port_monitor.py

Pakowanie (Windows):
    pyinstaller --onefile --noconsole port_monitor.py
"""
from __future__ import annotations

import sys
import os
import re
import json
import socket
import webbrowser
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

# --- opcjonalne zależności ---
try:
    import psutil  # type: ignore
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

try:
    import docker  # type: ignore
    HAS_DOCKER_SDK = True
except Exception:
    HAS_DOCKER_SDK = False

# --- Qt ---
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QTimer, QSortFilterProxyModel,
    Signal, QSettings, QSize
)
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap, QBrush
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QPushButton,
    QTableView, QHeaderView, QLabel, QSpinBox, QCheckBox, QMessageBox, QToolBar,
    QStatusBar, QMenu, QHBoxLayout, QSplitter, QFrame, QGridLayout, QStyle,
    QStyleOptionButton
)
from PySide6.QtWidgets import QAbstractItemView

# ------------------ Struktury danych ------------------
@dataclass
class PortRecord:
    port: int
    protocol: str  # TCP/UDP
    status: str    # LISTEN, ESTABLISHED, FREE, ...
    pid: Optional[int]
    process: str
    local_addr: str
    remote_addr: str
    docker_name: str = ""
    docker_id: str = ""
    docker_image: str = ""
    docker_cport: Optional[int] = None

    @property
    def is_free(self) -> bool:
        return self.status.upper() == "FREE"

@dataclass
class DockerPortInfo:
    container_id: str
    container_name: str
    image: str
    host_ip: str
    host_port: int
    container_port: int
    protocol: str  # TCP/UDP

# ------------------ Enumeracja połączeń ------------------

def _safe_proc_name(pid: Optional[int]) -> str:
    if not pid:
        return ""
    if HAS_PSUTIL:
        try:
            return psutil.Process(pid).name()
        except Exception:
            return f"PID {pid}"
    return f"PID {pid}"


def list_used_ports_psutil() -> List[PortRecord]:
    records: List[PortRecord] = []
    try:
        conns = psutil.net_connections(kind="inet")  # TCP i UDP
    except Exception:
        return records

    for c in conns:
        laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
        raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
        proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
        status = c.status or ("LISTEN" if proto == "UDP" else "")
        pid = c.pid if c.pid and c.pid > 0 else None
        name = _safe_proc_name(pid)
        if c.laddr:
            records.append(PortRecord(
                port=c.laddr.port,
                protocol=proto,
                status=status or "",
                pid=pid,
                process=name,
                local_addr=laddr,
                remote_addr=raddr,
            ))
    return records


def list_used_ports_netstat() -> List[PortRecord]:
    records: List[PortRecord] = []
    try:
        if os.name == 'nt':
            out = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.STDOUT, encoding='utf-8', errors='ignore')
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("TCP") or line.startswith("UDP"):
                    parts = re.split(r"\s+", line)
                    if len(parts) < 4:
                        continue
                    proto = parts[0].upper()
                    local = parts[1]
                    remote = parts[2] if len(parts) > 2 else ""
                    state = parts[3] if (proto == 'TCP' and len(parts) > 3) else ("" if proto == 'UDP' else "")
                    pid = None
                    if len(parts) >= 5:
                        try:
                            pid = int(parts[-1])
                        except Exception:
                            pid = None
                    try:
                        port = int(local.rsplit(":", 1)[-1])
                    except Exception:
                        continue
                    name = _safe_proc_name(pid)
                    records.append(PortRecord(
                        port=port,
                        protocol=proto,
                        status=state,
                        pid=pid,
                        process=name,
                        local_addr=local,
                        remote_addr=remote,
                    ))
        else:
            out = subprocess.check_output(["lsof", "-nP", "-i"], text=True, stderr=subprocess.STDOUT)
            for line in out.splitlines()[1:]:
                if not line.strip():
                    continue
                parts = re.split(r"\s+", line, maxsplit=8)
                if len(parts) < 9:
                    continue
                command, pid_s, user, fd, typ, device, sizeoff, node, name = parts
                pid = None
                try:
                    pid = int(pid_s)
                except Exception:
                    pass
                proto = "TCP" if "TCP" in name else ("UDP" if "UDP" in name else "?")
                status = "LISTEN" if "LISTEN" in name else ("ESTABLISHED" if "ESTABLISHED" in name else "")
                m = re.search(r":(\d+)", name)
                if not m:
                    continue
                port = int(m.group(1))
                local_addr = name
                remote_addr = ""
                records.append(PortRecord(
                    port=port,
                    protocol=proto,
                    status=status,
                    pid=pid,
                    process=command,
                    local_addr=local_addr,
                    remote_addr=remote_addr,
                ))
    except Exception:
        pass
    return records


def collect_used_ports() -> List[PortRecord]:
    if HAS_PSUTIL:
        recs = list_used_ports_psutil()
        if recs:
            return recs
    return list_used_ports_netstat()

# ------------------ Docker: porty ------------------

def docker_available_via_cli() -> bool:
    try:
        subprocess.check_output(["docker", "version"], stderr=subprocess.STDOUT, text=True, timeout=3)
        return True
    except Exception:
        return False


def collect_docker_ports() -> Dict[Tuple[str, int], List[DockerPortInfo]]:
    index: Dict[Tuple[str, int], List[DockerPortInfo]] = {}

    if HAS_DOCKER_SDK:
        try:
            client = docker.from_env()
            for c in client.containers.list():
                attrs = c.attrs or {}
                ns = attrs.get("NetworkSettings", {})
                ports = ns.get("Ports", {}) or {}
                image = ""
                try:
                    tags = c.image.tags or []
                    image = tags[0] if tags else c.image.short_id
                except Exception:
                    image = ""
                for key, binds in ports.items():
                    try:
                        cport_str, proto = key.split("/")
                        proto = proto.upper()
                        cport = int(cport_str)
                    except Exception:
                        continue
                    if not binds:
                        continue
                    for bind in binds:
                        try:
                            host_port = int(bind.get("HostPort", ""))
                        except Exception:
                            continue
                        host_ip = bind.get("HostIp", "")
                        info = DockerPortInfo(
                            container_id=c.id[:12],
                            container_name=c.name,
                            image=image,
                            host_ip=host_ip,
                            host_port=host_port,
                            container_port=cport,
                            protocol=proto,
                        )
                        index.setdefault((proto, host_port), []).append(info)
            return index
        except Exception:
            pass

    if docker_available_via_cli():
        try:
            out = subprocess.check_output(["docker", "ps", "--format", "{{json .}}"], text=True, stderr=subprocess.STDOUT)
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                cid = (obj.get("ID") or "")[:12]
                name = obj.get("Names") or ""
                image = obj.get("Image") or ""
                ports_str = obj.get("Ports") or ""
                for entry in [e.strip() for e in ports_str.split(",") if e.strip()]:
                    if "->" not in entry:
                        continue
                    left, right = entry.split("->", 1)
                    try:
                        proto = right.split("/", 1)[1].upper()
                        cport = int(right.split("/", 1)[0])
                    except Exception:
                        continue
                    try:
                        hport = int(left.split(":")[-1])
                    except Exception:
                        continue
                    hip = left.rsplit(":", 1)[0] if ":" in left else ""
                    info = DockerPortInfo(
                        container_id=cid,
                        container_name=name,
                        image=image,
                        host_ip=hip,
                        host_port=hport,
                        container_port=cport,
                        protocol=proto,
                    )
                    index.setdefault((proto, hport), []).append(info)
        except Exception:
            pass

    return index

# ------------------ Model tabeli ------------------
class PortsTableModel(QAbstractTableModel):
    headers = ["Port", "Proto", "Status", "PID", "Proces", "Local", "Remote", "Docker"]

    def __init__(self, rows: List[PortRecord]):
        super().__init__()
        self._rows: List[PortRecord] = rows

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        rec = self._rows[index.row()]
        col = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == 0:
                return rec.port
            elif col == 1:
                return rec.protocol
            elif col == 2:
                # Status jako czytelny chip (tekst), kolor nada BackgroundRole
                return rec.status or ("FREE" if rec.is_free else "")
            elif col == 3:
                return rec.pid if rec.pid is not None else ""
            elif col == 4:
                return rec.process
            elif col == 5:
                return rec.local_addr
            elif col == 6:
                return rec.remote_addr
            elif col == 7:
                if rec.docker_name:
                    img = f" @ {rec.docker_image}" if rec.docker_image else ""
                    cport = f"{rec.docker_cport}" if rec.docker_cport else "?"
                    return f"🐳 {rec.docker_name} ({rec.port}->{cport}/{rec.protocol.lower()}){img}"
                return ""

        # Kolorowanie statusów (nowoczesny look)
        if role == Qt.BackgroundRole and col == 2:
            s = (rec.status or ("FREE" if rec.is_free else "")).upper()
            if s == "FREE":
                return QBrush(Qt.transparent)
            if s == "LISTEN":
                return QBrush(Qt.transparent)
            if s == "ESTABLISHED":
                return QBrush(Qt.transparent)
        if role == Qt.ForegroundRole and col == 2:
            s = (rec.status or ("FREE" if rec.is_free else "")).upper()
            if s == "FREE":
                return QBrush(Qt.darkGreen)
            if s == "LISTEN":
                return QBrush(Qt.darkCyan)
            if s == "ESTABLISHED":
                return QBrush(Qt.darkBlue)
        if role == Qt.TextAlignmentRole and col in (0, 3):
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.headers[section]
        return section + 1

    def setRows(self, rows: List[PortRecord]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row(self, r: int) -> PortRecord:
        return self._rows[r]

# ------------------ Style (QSS) ------------------
LIGHT_QSS = """
* { font-size: 13px; }
QMainWindow { background: #f7f8fb; }
QToolBar { background: #ffffff; border: none; padding: 6px; }
QToolBar QToolButton { border-radius: 8px; padding: 6px 10px; }
QLineEdit { border: 1px solid #d8dbe3; border-radius: 10px; padding: 6px 10px; background: #ffffff; }
QCheckBox { spacing: 8px; }
QTableView { background: #ffffff; gridline-color: #eef0f4; alternate-background-color: #fafbfe; }
QHeaderView::section { background: #f0f2f7; padding: 8px; border: none; border-bottom: 1px solid #e6e9f0; }
QStatusBar { background: #ffffff; border-top: 1px solid #e6e9f0; }
QPushButton { background: #2d7ff9; color: white; border: none; border-radius: 10px; padding: 8px 12px; }
QPushButton:hover { filter: brightness(1.05); }
QPushButton:disabled { background: #9fb8f9; }
QFrame#Card { background: #ffffff; border: 1px solid #e6e9f0; border-radius: 16px; }
QLabel#Title { font-size: 16px; font-weight: 600; }
QLabel#Badge { background: #eef4ff; color: #2d7ff9; border-radius: 10px; padding: 2px 8px; }
QLabel#BadgeWarn { background: #fff4ec; color: #ff7d3a; border-radius: 10px; padding: 2px 8px; }
QLabel#BadgeOk { background: #ecfbf2; color: #1a7f55; border-radius: 10px; padding: 2px 8px; }
"""

DARK_QSS = """
* { font-size: 13px; color: #e6e9ef; }
QMainWindow { background: #0f141a; }
QToolBar { background: #111821; border: none; padding: 6px; }
QToolBar QToolButton { border-radius: 8px; padding: 6px 10px; }
QLineEdit { border: 1px solid #2a3441; border-radius: 10px; padding: 6px 10px; background: #0c1117; color: #e6e9ef; }
QCheckBox { spacing: 8px; }
QTableView { background: #0c1117; gridline-color: #1f2a36; alternate-background-color: #0f151c; }
QHeaderView::section { background: #111821; padding: 8px; border: none; border-bottom: 1px solid #1f2a36; }
QStatusBar { background: #111821; border-top: 1px solid #1f2a36; }
QPushButton { background: #2d7ff9; color: white; border: none; border-radius: 10px; padding: 8px 12px; }
QPushButton:hover { filter: brightness(1.05); }
QPushButton:disabled { background: #2a3a55; }
QFrame#Card { background: #0c1117; border: 1px solid #1f2a36; border-radius: 16px; }
QLabel#Title { font-size: 16px; font-weight: 600; color: #f0f3fa; }
QLabel#Badge { background: #1b2840; color: #8fb9ff; border-radius: 10px; padding: 2px 8px; }
QLabel#BadgeWarn { background: #3a2418; color: #ffb38a; border-radius: 10px; padding: 2px 8px; }
QLabel#BadgeOk { background: #15382a; color: #67d29a; border-radius: 10px; padding: 2px 8px; }
"""

# ------------------ Główne okno ------------------
class MainWindow(QMainWindow):
    request_refresh = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PortWatch Pro — nowoczesny monitor portów 🧭")
        self.resize(1340, 820)
        self.settings = QSettings("PortWatchPro", "UIv2")

        # ToolBar (górny pasek)
        tb = QToolBar("Akcje")
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        # Ikony systemowe
        style = self.style()
        ico_refresh = style.standardIcon(QStyle.SP_BrowserReload)
        ico_play = style.standardIcon(QStyle.SP_MediaPlay)
        ico_search = style.standardIcon(QStyle.SP_FileDialogContentsView)
        ico_net = style.standardIcon(QStyle.SP_DriveNetIcon)
        ico_theme = style.standardIcon(QStyle.SP_DialogYesButton)

        # Zakres
        self.range_from = QSpinBox(); self.range_from.setRange(1, 65535); self.range_from.setValue(1)
        self.range_to = QSpinBox(); self.range_to.setRange(1, 65535); self.range_to.setValue(1024)
        tb.addWidget(QLabel("Zakres:"))
        tb.addWidget(self.range_from)
        tb.addWidget(QLabel("—"))
        tb.addWidget(self.range_to)

        # Segmenty filtrów
        self.cb_only_used = QCheckBox("Tylko zajęte")
        self.cb_only_docker = QCheckBox("Tylko Docker")
        tb.addSeparator()
        tb.addWidget(self.cb_only_used)
        tb.addWidget(self.cb_only_docker)

        # Szybki filtr
        self.le_filter = QLineEdit(); self.le_filter.setPlaceholderText("Szukaj: port, proces, status, docker…")
        self.le_filter.setClearButtonEnabled(True)
        self.le_filter.setFixedWidth(360)
        tb.addSeparator(); tb.addWidget(self.le_filter)

        # Przyciski
        btn_scan = QPushButton("Skanuj zakres"); btn_scan.setIcon(ico_search)
        btn_refresh = QPushButton("Odśwież"); btn_refresh.setIcon(ico_refresh)
        btn_docker = QPushButton("Dockera"); btn_docker.setIcon(ico_net)
        self.btn_theme = QPushButton("Motyw"); self.btn_theme.setIcon(ico_theme)
        tb.addSeparator(); tb.addWidget(btn_scan); tb.addWidget(btn_refresh); tb.addWidget(btn_docker); tb.addWidget(self.btn_theme)

        # Splitter: tabela + panel szczegółów
        splitter = QSplitter()

        # Tabela
        self.table = QTableView()
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_ctx)

        self.model = PortsTableModel([])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table.setModel(self.proxy)

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        for i in range(self.model.columnCount()):
            hh.setSectionResizeMode(i, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Panel szczegółów (karta)
        self.detail_card = QFrame(); self.detail_card.setObjectName("Card")
        card_layout = QVBoxLayout(self.detail_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel("Szczegóły"); title.setObjectName("Title")
        card_layout.addWidget(title)

        grid = QGridLayout(); grid.setVerticalSpacing(8); grid.setHorizontalSpacing(12)
        r = 0
        self.lbl_port = QLabel("—"); self.lbl_port.setObjectName("Badge")
        self.lbl_proto = QLabel("—"); self.lbl_proto.setObjectName("Badge")
        self.lbl_status = QLabel("—"); self.lbl_status.setObjectName("BadgeOk")
        grid.addWidget(QLabel("Port"), r, 0); grid.addWidget(self.lbl_port, r, 1); r += 1
        grid.addWidget(QLabel("Proto"), r, 0); grid.addWidget(self.lbl_proto, r, 1); r += 1
        grid.addWidget(QLabel("Status"), r, 0); grid.addWidget(self.lbl_status, r, 1); r += 1

        self.lbl_pid = QLabel("—"); self.lbl_proc = QLabel("—")
        grid.addWidget(QLabel("PID"), r, 0); grid.addWidget(self.lbl_pid, r, 1); r += 1
        grid.addWidget(QLabel("Proces"), r, 0); grid.addWidget(self.lbl_proc, r, 1); r += 1

        self.lbl_local = QLabel("—"); self.lbl_remote = QLabel("—")
        self.lbl_local.setWordWrap(True); self.lbl_remote.setWordWrap(True)
        grid.addWidget(QLabel("Local"), r, 0); grid.addWidget(self.lbl_local, r, 1); r += 1
        grid.addWidget(QLabel("Remote"), r, 0); grid.addWidget(self.lbl_remote, r, 1); r += 1

        self.lbl_docker = QLabel("—"); self.lbl_image = QLabel("—")
        self.lbl_docker.setObjectName("Badge"); self.lbl_image.setObjectName("Badge")
        grid.addWidget(QLabel("Docker"), r, 0); grid.addWidget(self.lbl_docker, r, 1); r += 1
        grid.addWidget(QLabel("Obraz"), r, 0); grid.addWidget(self.lbl_image, r, 1); r += 1

        card_layout.addLayout(grid)

        # Przyciski akcji w karcie
        btn_row = QHBoxLayout()
        self.btn_open = QPushButton("Otwórz http://localhost:PORT")
        self.btn_kill = QPushButton("Zakończ proces")
        self.btn_stop = QPushButton("Zatrzymaj kontener")
        self.btn_restart = QPushButton("Restart kontenera")
        btn_row.addWidget(self.btn_open); btn_row.addWidget(self.btn_kill)
        btn_row.addWidget(self.btn_stop); btn_row.addWidget(self.btn_restart)
        card_layout.addSpacing(8); card_layout.addLayout(btn_row)
        card_layout.addStretch()

        # Po lewej tabela, po prawej karta
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_card)
        splitter.setSizes([900, 420])

        # StatusBar
        self.setStatusBar(QStatusBar())

        # Centralny layout
        central = QWidget(); root = QVBoxLayout(central); root.addWidget(splitter); self.setCentralWidget(central)

        # Sygnały
        btn_refresh.clicked.connect(self.refresh_now)
        btn_scan.clicked.connect(self.scan_range)
        btn_docker.clicked.connect(self.refresh_docker)
        self.cb_only_used.toggled.connect(self.update_view)
        self.cb_only_docker.toggled.connect(self.update_view)
        self.le_filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.btn_theme.clicked.connect(self.toggle_theme)

        self.btn_open.clicked.connect(self._detail_open)
        self.btn_kill.clicked.connect(self._detail_kill)
        self.btn_stop.clicked.connect(self._detail_stop)
        self.btn_restart.clicked.connect(self._detail_restart)

        # Timery odświeżające
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_now); self.timer.start(5000)
        self.timer_docker = QTimer(self); self.timer_docker.timeout.connect(self.refresh_docker); self.timer_docker.start(10000)

        # Dane
        self._all_records: List[PortRecord] = []
        self._docker_index: Dict[Tuple[str, int], List[DockerPortInfo]] = {}

        # Motyw
        self.active_dark = self.settings.value("theme_dark", True, bool)
        self.apply_theme(self.active_dark)

        # Start
        self.refresh_docker(); self.refresh_now()
        if self.proxy.rowCount() > 0:
            self.table.selectRow(0)

    # ---------- Dane ----------
    def refresh_now(self):
        used = collect_used_ports()
        self._all_records = used
        self.statusBar().showMessage(f"Znaleziono {len(used)} aktywnych wpisów (sieć)")
        self.update_view()

    def refresh_docker(self):
        self._docker_index = collect_docker_ports()
        if self._docker_index:
            msg = f"Docker: wykryto {sum(len(v) for v in self._docker_index.values())} mapowań"
        else:
            msg = "Docker: brak mapowań lub niedostępny"
        self.statusBar().showMessage(msg)
        self.update_view()

    def _enrich_with_docker(self, rows: List[PortRecord]) -> List[PortRecord]:
        for r in rows:
            infos = self._docker_index.get((r.protocol.upper(), int(r.port)))
            if not infos and r.protocol.upper() == "UDP":
                infos = self._docker_index.get(("TCP", int(r.port)))
            if infos:
                primary = infos[0]
                r.docker_name = primary.container_name
                r.docker_id = primary.container_id
                r.docker_image = primary.image
                r.docker_cport = primary.container_port
                if len(infos) > 1:
                    r.docker_name += f" (+{len(infos)-1})"
        return rows

    def _build_range_view(self) -> List[PortRecord]:
        start = min(self.range_from.value(), self.range_to.value())
        end = max(self.range_from.value(), self.range_to.value())
        used_ports_map: Dict[Tuple[str, int], PortRecord] = {}
        for r in self._all_records:
            key = (r.protocol.upper(), int(r.port))
            if key not in used_ports_map:
                used_ports_map[key] = r
        rows: List[PortRecord] = []
        for p in ("TCP", "UDP"):
            for port in range(start, end + 1):
                r = used_ports_map.get((p, port))
                if r is not None:
                    rows.append(r)
                else:
                    if not self.cb_only_used.isChecked():
                        rows.append(PortRecord(
                            port=port, protocol=p, status="FREE", pid=None, process="",
                            local_addr=f"*:{port}", remote_addr="",
                        ))
        rows = self._enrich_with_docker(rows)
        if self.cb_only_docker.isChecked():
            rows = [r for r in rows if r.docker_name]
        return rows

    def update_view(self):
        rows = self._build_range_view()
        self.model.setRows(rows)
        self.statusBar().showMessage(f"Wyświetlanych: {len(rows)}")

    def scan_range(self):
        self.update_view()

    # ---------- Wybór i panel szczegółów ----------
    def _on_selection_changed(self, *_):
        rec = self._current_record()
        if not rec:
            self._clear_details(); return
        self._populate_details(rec)

    def _current_record(self) -> Optional[PortRecord]:
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return None
        src_idx = self.proxy.mapToSource(sel[0])
        return self.model.row(src_idx.row())

    def _clear_details(self):
        for w in (self.lbl_port, self.lbl_proto, self.lbl_status, self.lbl_pid, self.lbl_proc,
                  self.lbl_local, self.lbl_remote, self.lbl_docker, self.lbl_image):
            w.setText("—")
        self.btn_open.setEnabled(False)
        self.btn_kill.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_restart.setEnabled(False)

    def _populate_details(self, rec: PortRecord):
        self.lbl_port.setText(str(rec.port))
        self.lbl_proto.setText(rec.protocol)
        st = rec.status or ("FREE" if rec.is_free else "")
        self.lbl_status.setText(st)
        self.lbl_pid.setText(str(rec.pid) if rec.pid else "—")
        self.lbl_proc.setText(rec.process or "—")
        self.lbl_local.setText(rec.local_addr or "—")
        self.lbl_remote.setText(rec.remote_addr or "—")
        self.lbl_docker.setText(rec.docker_name or "—")
        self.lbl_image.setText(rec.docker_image or "—")

        self.btn_open.setText(f"Otwórz http://localhost:{rec.port}")
        self.btn_open.setEnabled(True)
        self.btn_kill.setEnabled(bool(rec.pid))
        self.btn_stop.setEnabled(bool(rec.docker_id))
        self.btn_restart.setEnabled(bool(rec.docker_id))

    def _detail_open(self):
        rec = self._current_record()
        if not rec:
            return
        url = "https://localhost" if rec.port == 443 else f"http://localhost:{rec.port}"
        webbrowser.open(url)

    def _detail_kill(self):
        rec = self._current_record()
        if not rec or not rec.pid:
            return
        extra_warn = ""
        if rec.docker_id or ("docker" in (rec.process or "").lower()) or ("com.docker" in (rec.process or "").lower()):
            extra_warn = "\n\nUWAGA: Ten port wygląda na używany przez Docker. Zabicie procesu może ubić całe środowisko Dockera."
        confirm = QMessageBox.question(
            self, "Potwierdź",
            f"Na pewno zakończyć proces PID {rec.pid} ({rec.process})?{extra_warn}",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        ok, err = kill_process(rec.pid)
        if ok:
            QMessageBox.information(self, "Sukces", f"Proces {rec.pid} zakończony.")
            self.refresh_now()
        else:
            QMessageBox.critical(self, "Błąd", f"Nie udało się zakończyć PID {rec.pid}: {err}")

    def _detail_stop(self):
        rec = self._current_record()
        if rec:
            self.docker_stop(rec)

    def _detail_restart(self):
        rec = self._current_record()
        if rec:
            self.docker_restart(rec)

    # ---------- Menu kontekstowe ----------
    def _on_table_ctx(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        src_idx = self.proxy.mapToSource(idx)
        rec = self.model.row(src_idx.row())

        menu = QMenu(self)
        act_kill = QAction("Zakończ proces blokujący ten port", self)
        act_kill.triggered.connect(lambda: self._detail_kill())
        menu.addAction(act_kill)

        if rec.docker_id:
            menu.addSeparator()
            act_stop = QAction(f"Zatrzymaj kontener [{rec.docker_name}]", self)
            act_stop.triggered.connect(lambda: self._detail_stop())
            menu.addAction(act_stop)

            act_restart = QAction(f"Restartuj kontener [{rec.docker_name}]", self)
            act_restart.triggered.connect(lambda: self._detail_restart())
            menu.addAction(act_restart)

            act_open = QAction(f"Otwórz http://localhost:{rec.port}", self)
            act_open.triggered.connect(lambda: self._detail_open())
            menu.addAction(act_open)

        act_details = QAction("Szczegóły (panel po prawej)", self)
        act_details.triggered.connect(lambda: self._populate_details(rec))
        menu.addAction(act_details)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- Docker akcje ----------
    def docker_stop(self, rec: PortRecord):
        if not rec.docker_id:
            return
        if HAS_DOCKER_SDK:
            try:
                client = docker.from_env()
                c = client.containers.get(rec.docker_id)
                c.stop()
                QMessageBox.information(self, "Docker", f"Kontener {rec.docker_name} zatrzymany.")
                self.refresh_docker(); self.refresh_now()
                return
            except Exception:
                pass
        try:
            subprocess.check_call(["docker", "stop", rec.docker_id], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            QMessageBox.information(self, "Docker", f"Kontener {rec.docker_name} zatrzymany (CLI).")
            self.refresh_docker(); self.refresh_now()
        except Exception as e:
            QMessageBox.critical(self, "Docker", f"Błąd zatrzymania kontenera: {e}")

    def docker_restart(self, rec: PortRecord):
        if not rec.docker_id:
            return
        if HAS_DOCKER_SDK:
            try:
                client = docker.from_env()
                c = client.containers.get(rec.docker_id)
                c.restart()
                QMessageBox.information(self, "Docker", f"Kontener {rec.docker_name} zrestartowany.")
                self.refresh_docker(); self.refresh_now()
                return
            except Exception:
                pass
        try:
            subprocess.check_call(["docker", "restart", rec.docker_id], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            QMessageBox.information(self, "Docker", f"Kontener {rec.docker_name} zrestartowany (CLI).")
            self.refresh_docker(); self.refresh_now()
        except Exception as e:
            QMessageBox.critical(self, "Docker", f"Błąd restartu kontenera: {e}")

    # ---------- Motywy ----------
    def apply_theme(self, dark: bool):
        self.active_dark = bool(dark)
        self.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)
        self.settings.setValue("theme_dark", self.active_dark)

    def toggle_theme(self):
        self.apply_theme(not self.active_dark)

# ------------------ Zabijanie procesu ------------------

def kill_process(pid: int):
    try:
        if HAS_PSUTIL:
            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
            return True, ""
        if os.name == 'nt':
            subprocess.check_call(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            return True, ""
        else:
            os.kill(pid, 15)
            return True, ""
    except subprocess.CalledProcessError as e:
        return False, f"taskkill error: {e}"
    except PermissionError:
        return False, "Brak uprawnień (uruchom jako administrator)."
    except ProcessLookupError:
        return False, "Proces nie istnieje."
    except Exception as e:
        return False, str(e)

# ------------------ Uruchomienie ------------------

def main():
    # MUSI być przed QApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
