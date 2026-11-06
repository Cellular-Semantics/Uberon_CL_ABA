"""Run one Owlery process per KB behind a small proxy.

Owlery loads its KBs at start-up and cannot reload one, so a single process holding
every KB would have to restart (and re-classify everything) whenever any KB changes.
With a process per KB, rebuilding cl-x__uberon-y restarts only that KB; the proxy
keeps a single base URL (http://localhost:<port>/kbs/<kb>/...) for all of them.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .config import KB, Config
from .build import kb_dir
from .tools import owlery_bin

LOGBACK = """<configuration>
  <appender name="stdout" class="ch.qos.logback.core.ConsoleAppender">
    <encoder><pattern>%d{HH:mm:ss.SSS} %-5level %logger{20} %msg%n</pattern></encoder>
  </appender>
  <logger name="akka" level="WARN"/>
  <root level="INFO"><appender-ref ref="stdout"/></root>
</configuration>
"""


def run_dir(cfg: Config) -> Path:
    d = cfg.root / "run"
    d.mkdir(exist_ok=True)
    return d


def load_state(cfg: Config) -> dict:
    f = run_dir(cfg) / "state.json"
    return json.loads(f.read_text()) if f.exists() else {"backends": {}, "ports": {}}


def save_state(cfg: Config, st: dict) -> None:
    f = run_dir(cfg) / "state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(f)


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def port_for(cfg: Config, st: dict, name: str) -> int:
    if name in st["ports"]:
        return st["ports"][name]
    used = set(st["ports"].values())
    p = int(cfg.serve.get("backend_port_base", 9100))
    while p in used:
        p += 1
    st["ports"][name] = p
    return p


def http_ok(url: str, timeout=3) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_backend(cfg: Config, kb: KB, wait: bool = True, timeout: int = 1800) -> None:
    st = load_state(cfg)
    b = st["backends"].get(kb.name)
    if b and alive(b.get("pid")):
        print(f"   {kb.name}: already running on :{b['port']}")
        return
    ofn_path = kb_dir(cfg) / f"{kb.name}.ofn"
    if not ofn_path.exists():
        print(f"   {kb.name}: not built; skipped (run `wb build {kb.name}`)")
        return
    rd = run_dir(cfg)
    port = port_for(cfg, st, kb.name)
    conf = rd / f"{kb.name}.conf"
    reasoner = cfg.serve.get("reasoner", "elk")
    conf.write_text(
        "akka.http.server { request-timeout = infinite, idle-timeout = infinite }\n"
        f"owlery {{\n  port = {port}\n  host = localhost\n  kbs = [\n"
        f"    {{ name = \"{kb.name}\", location = \"{ofn_path}\", reasoner = {reasoner} }}\n"
        "  ]\n}\n")
    (rd / "logback.xml").write_text(LOGBACK)
    env = dict(os.environ)
    env["JAVA_OPTS"] = (f"-Xmx{kb.heap} -Dconfig.file={conf} "
                        f"-Dlogback.configurationFile={rd / 'logback.xml'}")
    manifest = kb_dir(cfg) / f"{kb.name}.json"
    key = json.loads(manifest.read_text()).get("key") if manifest.exists() else None
    with open(rd / f"{kb.name}.log", "w") as log:
        # Owlery exits on EOF on stdin, so give it a stdin that never closes.
        p = subprocess.Popen(["sh", "-c", f"tail -f /dev/null | exec '{owlery_bin(cfg)}'"],
                             env=env, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    st["backends"][kb.name] = {"pid": p.pid, "port": port, "key": key, "started": time.time()}
    save_state(cfg, st)
    print(f"   {kb.name}: starting on :{port} (heap {kb.heap}, log run/{kb.name}.log)")
    if wait:
        wait_ready(cfg, kb.name, port, p.pid, timeout)


def wait_ready(cfg: Config, name: str, port: int, pid: int, timeout: int) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not alive(pid):
            print(f"   {name}: Owlery exited; see run/{name}.log")
            return False
        if http_ok(f"http://localhost:{port}/kbs/{name}"):
            print(f"   {name}: ready after {time.time() - t0:.0f}s")
            return True
        time.sleep(3)
    print(f"   {name}: not ready after {timeout}s; still loading? see run/{name}.log")
    return False


def stop_backend(cfg: Config, name: str) -> None:
    st = load_state(cfg)
    b = st["backends"].pop(name, None)
    save_state(cfg, st)
    if b and alive(b.get("pid")):
        try:
            os.killpg(b["pid"], signal.SIGTERM)
        except OSError:
            pass
        for _ in range(30):
            if not alive(b["pid"]):
                break
            time.sleep(0.5)
        print(f"   {name}: stopped")


def start_proxy(cfg: Config) -> None:
    st = load_state(cfg)
    if alive(st.get("proxy_pid")):
        return
    port = int(cfg.serve.get("port", 8090))
    rd = run_dir(cfg)
    with open(rd / "proxy.log", "a") as log:
        p = subprocess.Popen([sys.executable, "-m", "workbench.proxy", str(cfg.root), str(port)],
                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    st = load_state(cfg)
    st["proxy_pid"] = p.pid
    save_state(cfg, st)
    time.sleep(1)
    if not alive(p.pid):
        raise SystemExit(f"proxy failed to start on :{port}; see run/proxy.log")
    print(f"== proxy on http://localhost:{port}/kbs")


def stop_proxy(cfg: Config) -> None:
    st = load_state(cfg)
    pid = st.pop("proxy_pid", None)
    save_state(cfg, st)
    if alive(pid):
        os.killpg(pid, signal.SIGTERM)
        print("   proxy: stopped")


def status(cfg: Config) -> list[str]:
    st = load_state(cfg)
    lines = []
    port = cfg.serve.get("port", 8090)
    lines.append(f"proxy :{port} " + ("running" if alive(st.get("proxy_pid")) else "stopped"))
    for kb in cfg.kbs:
        b = st["backends"].get(kb.name)
        manifest = kb_dir(cfg) / f"{kb.name}.json"
        built_key = json.loads(manifest.read_text()).get("key") if manifest.exists() else None
        if b and alive(b.get("pid")):
            ready = http_ok(f"http://localhost:{b['port']}/kbs/{kb.name}", timeout=2)
            s = f"serving :{b['port']}" + ("" if ready else " (loading)")
            if built_key and b.get("key") != built_key:
                s += ", rebuilt since start: `wb restart` to load"
        else:
            s = "not served"
        lines.append(f"{kb.name}: {'built' if built_key else 'not built'}, {s}")
    return lines
