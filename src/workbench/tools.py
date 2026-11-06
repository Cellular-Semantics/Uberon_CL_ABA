"""Locate or download ROBOT and Owlery."""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from .config import Config


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"   downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.rename(dest)


def robot_cmd(cfg: Config) -> list[str]:
    explicit = cfg.tools.get("robot")
    if explicit:
        return [str(Path(explicit).expanduser())]
    jar = cfg.root / ".tools" / f"robot-{cfg.tools.get('robot_version', '1.9.10')}.jar"
    if jar.exists():
        return ["java", "-jar", str(jar)]
    if shutil.which("robot"):
        return ["robot"]
    raise SystemExit("ROBOT not found: run `wb setup`, put `robot` on PATH, or set tools.robot")


def robot(cfg: Config, *args, log=None) -> None:
    env = dict(os.environ)
    heap = cfg.tools.get("robot_heap", "16G")
    env.setdefault("ROBOT_JAVA_ARGS", f"-Xmx{heap}")
    cmd = robot_cmd(cfg)
    if cmd[0] == "java":  # the jar path ignores ROBOT_JAVA_ARGS; pass the heap directly
        cmd = ["java", f"-Xmx{heap}", *cmd[1:]]
    r = subprocess.run([*cmd, *map(str, args)], env=env, stdout=log, stderr=subprocess.STDOUT
                       if log else None)
    if r.returncode:
        raise RuntimeError(f"robot {args[0]} failed (exit {r.returncode})"
                           + (f"; see {log.name}" if log else ""))


def owlery_bin(cfg: Config) -> Path:
    v = cfg.tools.get("owlery_version", "0.17.2")
    b = cfg.root / ".tools" / f"owlery-{v}" / "bin" / "owlery"
    if not b.exists():
        raise SystemExit("Owlery not installed: run `wb setup`")
    return b


def setup(cfg: Config) -> None:
    java = shutil.which("java")
    if not java:
        raise SystemExit("Java (11+) is required for ROBOT and Owlery")
    print("java:", subprocess.run(["java", "-version"], capture_output=True, text=True)
          .stderr.splitlines()[0])
    tools = cfg.root / ".tools"
    rv = cfg.tools.get("robot_version", "1.9.10")
    if cfg.tools.get("robot"):
        print(f"robot: {cfg.tools['robot']} (tools.robot)")
    else:
        jar = tools / f"robot-{rv}.jar"
        if not jar.exists():
            _download(f"https://github.com/ontodev/robot/releases/download/v{rv}/robot.jar", jar)
        print(f"robot: {jar}")
    ov = cfg.tools.get("owlery_version", "0.17.2")
    if not (tools / f"owlery-{ov}" / "bin" / "owlery").exists():
        tgz = tools / f"owlery-{ov}.tgz"
        _download(f"https://github.com/phenoscape/owlery/releases/download/v{ov}/owlery-{ov}.tgz", tgz)
        with tarfile.open(tgz) as t:
            t.extractall(tools, filter="data")
        tgz.unlink()
    print(f"owlery: {tools / f'owlery-{ov}'}")
