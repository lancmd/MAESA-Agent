"""Keep the documented doctor and local-port startup guard available."""

from __future__ import annotations

import subprocess
import sys
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
startup = (ROOT / "scripts" / "start_agent_mcp.ps1").read_text(encoding="utf-8-sig")
assert "Get-NetTCPConnection" in startup and "Port $Port is occupied" in startup and "-Port $($Port + 1)" in startup
doctor = ROOT / "scripts" / "maesa_doctor.ps1"
process = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(doctor),
                          "-Python", sys.executable, "-Project", str(ROOT / "examples" / "huaibei_demo" / "project.json")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", check=False)
assert process.returncode == 0, process.stdout
for label in ("MAESA-Agent Doctor", "Python 3.11+", "MCP package", "Software:", "GPU:", "Data:", "LULC input"):
    assert label in process.stdout, process.stdout
assert "project_readiness.py" in process.stdout, process.stdout

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    listener.bind(("127.0.0.1", 0)); listener.listen(1)
    port = listener.getsockname()[1]
    process = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "start_agent_mcp.ps1"),
                              "-Port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", check=False)
    assert process.returncode != 0 and f"Port {port} is occupied" in process.stdout and f"-Port {port + 1}" in process.stdout, process.stdout
print('{"status":"completed","checks":["doctor","local MCP port guard"]}')
