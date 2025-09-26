# PortWatchPro
Check your network ports on your pc with ports in docker while using
# PortWatch Pro — Modern Port Monitor with Docker Integration (GUI)

**PortWatch Pro** is a lightweight Python (PySide6) application that lets you inspect TCP/UDP ports on your machine and automatically detect ports published by Docker containers. It ships with a clean, modern UI, a details panel, and one‑click actions for common tasks.

> **Built for developers and ops.** Quickly answer “what’s holding this port?”, kill the process, see Docker port mappings, and manage containers without leaving a friendly GUI.

---

## ✨ Features
- **Port range scan** for both **TCP** and **UDP** (e.g., 1–1024 or any custom range).
- **Auto‑refresh** (network every 5s, Docker every 10s by default).
- **Filters**:
  - **Only used** — show occupied ports only.
  - **Only Docker** — show only ports published by containers.
  - **Quick text filter** across port, process, status, container name, image, etc.
- **Docker integration**
  - Reads mappings via **Docker SDK** (preferred) with **CLI fallback** (`docker ps`).
  - **Docker** column with container name, image, and mapping `host→container/proto`.
  - Context actions: **Stop** / **Restart** container, **Open** `http://localhost:<port>`.
- **Details panel**: right‑side card with all info about the selected row plus action buttons.
- **Modern UI**: card‑style layout, readable status badges, **Light/Dark theme toggle**.
- **Terminate process** that blocks a port (with extra warning if it looks Docker‑related).

---

## 🧩 Requirements
- **Python**: 3.10+ (3.11/3.12 recommended)
- **OS**: Windows 11 (tested) / Linux / macOS (Docker features depend on your environment)
- **Packages:**
  - `PySide6` — GUI
  - `psutil` — process/network enumeration
  - `docker` — Docker SDK (optional; CLI fallback used if SDK is missing)
- **Docker** (optional): Docker Desktop / Docker Engine with `docker` available in `PATH`.

---

## 📦 Installation
### 1) Get the file
Make sure `port_monitor.py` is in your project folder.

### 2) (Optional) Virtual environment
```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
```
On bash (Linux/macOS):
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3) Dependencies
```bash
pip install PySide6 psutil docker
```
> The `docker` package is optional. If not installed, the app will use Docker CLI if available, or skip Docker features otherwise.

---

## ▶️ Run
```bash
python port_monitor.py
```
> **Windows note:** to terminate system/other users’ processes, run the terminal **as Administrator**.

---

## 🖥️ Using the App
- **Port range** — set From/To and press **Scan Range** (or simply refresh; the view is built for the current range).
- **Filters** — toggle **Only used** / **Only Docker**, or type into the quick filter.
- **Sorting** — click table headers.
- **Context menu** (right‑click a row):
  - **Terminate process holding this port**
  - *(Docker)* **Stop container**, **Restart container**, **Open http://localhost:PORT**
- **Details panel** (right side):
  - Select a row to see the card: port, proto, status, PID, process, local/remote, Docker (name, image).
  - Action buttons: **Open**, **Terminate**, **Stop**, **Restart** (context‑dependent).
- **Theme** — use the **Theme** button in the toolbar to toggle Light/Dark.

---

## 🐳 Docker Integration
- **SDK first**: if Docker SDK is available and the daemon is running, the app uses `docker.from_env()` to collect mappings.
- **CLI fallback**: if SDK fails or is missing, it parses `docker ps --format "{{json .}}"` for mappings.
- **Mapping join** happens on `(PROTO, HOST_PORT)` to enrich table rows.

> If Docker is unavailable or no ports are published, the **Docker** column stays empty and the status bar shows: *“Docker: no mappings or not available.”*

---

## 🛠️ Build a standalone EXE (Windows)
Use PyInstaller for a single‑file build:
```bash
pyinstaller --onefile --noconsole port_monitor.py
```
Your binary will appear in `dist/port_monitor.exe`.

**Tips:**
- Some AVs flag one‑file binaries — add an exception if needed.
- If Qt plugins aren’t bundled (rare), try:
  - `--collect-all PySide6` *or* `--collect-submodules PySide6`
- For a custom icon: add `--icon=app.ico`.

---

## 🔌 Permissions & Limitations
- **Terminating processes** may require Administrator/root privileges.
- **UDP** sockets often don’t report a rich state (status may be empty/“LISTEN”).
- **System processes** may not expose names without elevation.
- **Docker via WSL2**: mind PATH and that Windows Docker CLI can control a daemon in WSL.

---

## 🧪 Troubleshooting (FAQ)
**Q: `AttributeError: 'QTableView' object has no attribute 'SingleSelection'`**  
A: The app uses `QAbstractItemView.SingleSelection`. Update to the latest `port_monitor.py` where this is fixed and ensure PySide6 is up‑to‑date.

**Q: Docker isn’t detected**  
A: Check `docker version` in your terminal. If the command is missing, add Docker to `PATH` or start Docker Desktop. SDK mode requires a running daemon.

**Q: I can’t see process names/PIDs**  
A: Run your terminal as Administrator (Windows) or with elevated privileges (Linux/macOS) and try again.

**Q: PyInstaller build fails**  
A: Upgrade PyInstaller (`pip install -U pyinstaller`) and add `--collect-all PySide6`. You can also test with `python -m PySide6.scripts.pyside6-deploy` to detect missing plugins.

---

## 📚 Minimal Project Structure
```
.
├─ port_monitor.py      # Main application file (GUI + logic)
├─ README.md            # This file (EN)
└─ requirements.txt     # (optional) pinned deps
```

Example `requirements.txt`:
```
PySide6>=6.6
psutil>=5.9
docker>=7.0
```

---

## 🗺️ Roadmap Ideas
- Bottom **log panel** for recent actions and errors.
- **Range presets** (e.g., *web* 80/443/3000/5173, *db* 5432/3306/6379, *dev* 8000/8080/9000).
- **System tray** icon + background scan + conflict notifications.
- **docker‑compose** helper: edit `docker-compose.yaml` and start/stop stacks.

---

## 📄 License
MIT — free for commercial use and modification. Please keep author credits.

---

## 🏷️ Credits
UI/UX and Docker integration crafted in collaboration with **Dominik** (SOFT&SERVICE YOUR CHOICE‑YOUR FUTURE KOMPSERV).

