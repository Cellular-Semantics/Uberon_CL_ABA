"""Git side: one partial clone per source, a worktree per checkout, sync, fingerprints."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .config import Checkout, Config, Source


def git(repo: Path, *args, check=True, capture=True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], check=False,
                       capture_output=capture, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} in {repo}: {r.stderr.strip()}")
    return (r.stdout or "").strip() if capture else ""


def ensure_clone(src: Source) -> None:
    d = src.clone_dir
    if (d / "HEAD").exists() or (d / ".git").exists():
        return
    d.parent.mkdir(parents=True, exist_ok=True)
    print(f"== {src.name}: partial clone of {src.repo} (blobs fetched on demand)")
    # Bare clone + worktrees: no checkout is privileged, each lives in sources/<src>/<name>.
    subprocess.run(["git", "clone", "--bare", "--filter=blob:none", src.repo, str(d)], check=True)
    git(d, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    git(d, "fetch", "origin")


def ensure_worktree(src: Source, co: Checkout) -> None:
    if not co.managed or (co.path / ".git").exists():
        return
    repo = src.clone_dir
    if co.pr is not None:
        git(repo, "fetch", "origin", f"+pull/{co.pr}/head:refs/remotes/origin/pr/{co.pr}")
        git(repo, "worktree", "add", "-B", co.name, str(co.path), f"origin/pr/{co.pr}")
    else:
        have_local = git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{co.branch}", check=False)
        if have_local:
            git(repo, "worktree", "add", str(co.path), co.branch)
            git(repo, "branch", f"--set-upstream-to=origin/{co.branch}", co.branch, check=False)
        else:
            git(repo, "worktree", "add", "--track", "-b", co.branch, str(co.path),
                f"origin/{co.branch}")
    print(f"   {src.name}/{co.name}: worktree at {co.path}")


def is_clean(path: Path) -> bool:
    return not git(path, "status", "--porcelain", "--untracked-files=no")


def sync_source(src: Source, mode: str | None = None) -> list[str]:
    """Bring checkouts in line with the config and the remote. Returns messages."""
    mode = mode or src.sync
    msgs = []
    if src.managed:
        ensure_clone(src)
        for co in src.checkouts:
            ensure_worktree(src, co)
    if mode == "none":
        return msgs
    repo = src.clone_dir
    git(repo, "fetch", "--prune", "origin")
    for co in src.checkouts:
        if co.pr is not None:
            git(repo, "fetch", "origin", f"+pull/{co.pr}/head:refs/remotes/origin/pr/{co.pr}")
            target = f"origin/pr/{co.pr}"
        else:
            target = "@{u}"
            if not git(co.path, "rev-parse", "--abbrev-ref", "-q", "@{u}", check=False):
                msgs.append(f"{src.name}/{co.name}: no upstream; fetched only")
                continue
        if mode != "ff":
            continue
        before = git(co.path, "rev-parse", "HEAD")
        if not is_clean(co.path):
            msgs.append(f"{src.name}/{co.name}: uncommitted changes; not fast-forwarded")
            continue
        r = subprocess.run(["git", "-C", str(co.path), "merge", "--ff-only", "-q", target],
                           capture_output=True, text=True)
        if r.returncode:
            msgs.append(f"{src.name}/{co.name}: diverged from {target}; not fast-forwarded")
            continue
        after = git(co.path, "rev-parse", "HEAD")
        if after != before:
            msgs.append(f"{src.name}/{co.name}: {before[:8]} -> {after[:8]}")
    return msgs


def prune_worktrees(src: Source) -> list[str]:
    """Remove managed worktrees that are no longer in the config (only if clean)."""
    if not src.managed or not (src.clone_dir / "HEAD").exists():
        return []
    keep = {co.path.resolve() for co in src.checkouts}
    msgs = []
    for d in sorted((src.root / "sources" / src.name).iterdir()):
        if d.name.startswith(".") or not (d / ".git").exists() or d.resolve() in keep:
            continue
        if is_clean(d):
            git(src.clone_dir, "worktree", "remove", str(d))
            msgs.append(f"{src.name}/{d.name}: removed (no longer in workbench.yaml)")
        else:
            msgs.append(f"{src.name}/{d.name}: not in workbench.yaml but has changes; left in place")
    return msgs


def fingerprint(src: Source, co: Checkout) -> dict:
    """What a build of this checkout depends on: HEAD plus any uncommitted edits
    under the ontology folder (the edit file, its catalog, imports, components)."""
    ont_dir = str(Path(src.edit).parent)
    head = git(co.path, "rev-parse", "HEAD")
    h = hashlib.sha256()
    h.update(git(co.path, "diff", "HEAD", "--binary", "--", ont_dir).encode())
    for f in git(co.path, "ls-files", "--others", "--exclude-standard", "--", ont_dir).splitlines():
        p = co.path / f
        if p.is_file():
            h.update(f.encode())
            h.update(p.read_bytes())
    branch = git(co.path, "rev-parse", "--abbrev-ref", "HEAD")
    return {"head": head, "branch": branch, "dirty": h.hexdigest()[:16]}


def status(cfg: Config) -> list[str]:
    lines = []
    for src in cfg.sources.values():
        for co in src.checkouts:
            if not (co.path / ".git").exists():
                lines.append(f"{src.name}/{co.name}: not checked out (run `wb sync`)")
                continue
            fp = fingerprint(src, co)
            ahead_behind = git(co.path, "rev-list", "--left-right", "--count", "HEAD...@{u}",
                               check=False)
            ab = ""
            if ahead_behind:
                a, b = ahead_behind.split()
                ab = f" ahead {a} behind {b}" if (a, b) != ("0", "0") else " up to date"
            dirty = "" if is_clean(co.path) else " +uncommitted"
            lines.append(f"{src.name}/{co.name}: {fp['branch']} @ {fp['head'][:8]}{ab}{dirty}"
                         f"  [{co.path}]")
    return lines
