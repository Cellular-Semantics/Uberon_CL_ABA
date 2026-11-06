"""wb: CL + Uberon reasoning workbench.

  wb setup                     download ROBOT and Owlery into .tools/
  wb sync [SOURCE...]          clone / add worktrees / fetch / fast-forward (per `sync`)
  wb status                    checkouts, KBs, servers
  wb kbs                       KBs the config expands to, with their parts
  wb build [KB...] [--force]   build KBs (glob patterns ok); unchanged inputs are skipped
  wb serve [KB...]             start proxy + one Owlery per KB (default: serve.kbs)
  wb restart [KB...]           restart backends (picks up rebuilt KBs)
  wb stop [KB...]              stop backends (all: also the proxy)
  wb up                        sync + build + serve
  wb watch [--interval S] [--sync-every S]
                               rebuild + restart KBs whose checkouts change
  wb q KB EXPR [--super|--equiv|--inst] [--direct]
                               DL query; EXPR may use CURIEs and 'labels'
  wb compare KB_A KB_B EXPR [--super|--equiv] [--direct]
                               what a query returns in one KB but not the other
  wb unsat KB                  unsatisfiable classes
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback

from . import build, config, query, serve, sources, tools


def _cfg():
    return config.load()


def _sel(cfg, names):
    return cfg.select_kbs(names or None)


def cmd_setup(a):
    tools.setup(_cfg())


def cmd_sync(a):
    cfg = _cfg()
    for name, src in cfg.sources.items():
        if a.sources and name not in a.sources:
            continue
        print(f"== {name} ({'managed' if src.managed else src.path}; sync={src.sync})")
        for m in sources.sync_source(src) + (sources.prune_worktrees(src) if a.prune else []):
            print("   " + m)
    if a.sources:
        return
    for n in build.clean_orphans(_cfg()):
        print(f"   removed built files of KB {n} (no longer in config)")


def cmd_status(a):
    cfg = _cfg()
    print("\n".join(sources.status(cfg)))
    print()
    print("\n".join(serve.status(cfg)))


def cmd_kbs(a):
    cfg = _cfg()
    for kb in cfg.kbs:
        st = "stale" if build.stale(cfg, kb) else "current"
        print(f"{kb.name}  [{st}, heap {kb.heap}]")
        for p in kb.parts:
            drop = f"  (imports minus {', '.join(x.rsplit('/', 1)[-1] for x in p.drop_import_subjects)}*)" \
                if p.drop_import_subjects else ""
            where = f"  {p.checkout.path}" if p.checkout else ""
            print(f"    {p.label()}{drop}{where}")


def cmd_build(a):
    cfg = _cfg()
    failed = []
    for kb in _sel(cfg, a.kbs):
        try:
            build.build_kb(cfg, kb, force=a.force)
        except Exception as e:
            print(f"!! {kb.name}: {e}", file=sys.stderr)
            failed.append(kb.name)
    if failed:
        raise SystemExit(f"FAILED: {' '.join(failed)} (previous builds kept; see build/logs/)")


def _served(cfg, names):
    return cfg.select_kbs(names or cfg.serve.get("kbs", "*"))


def cmd_serve(a):
    cfg = _cfg()
    tools.owlery_bin(cfg)
    serve.start_proxy(cfg)
    kbs = _served(cfg, a.kbs)
    for kb in kbs:
        serve.start_backend(cfg, kb, wait=False)
    if not a.no_wait:
        st = serve.load_state(cfg)
        for kb in kbs:
            b = st["backends"].get(kb.name)
            if b:
                serve.wait_ready(cfg, kb.name, b["port"], b["pid"], a.timeout)


def cmd_restart(a):
    cfg = _cfg()
    serve.start_proxy(cfg)
    kbs = _served(cfg, a.kbs)
    for kb in kbs:
        serve.stop_backend(cfg, kb.name)
        serve.start_backend(cfg, kb, wait=False)
    st = serve.load_state(cfg)
    for kb in kbs:
        b = st["backends"].get(kb.name)
        if b:
            serve.wait_ready(cfg, kb.name, b["port"], b["pid"], a.timeout)


def cmd_stop(a):
    cfg = _cfg()
    st = serve.load_state(cfg)
    names = [k.name for k in cfg.select_kbs(a.kbs)] if a.kbs else list(st["backends"])
    for n in names:
        serve.stop_backend(cfg, n)
    if not a.kbs:
        serve.stop_proxy(cfg)


def cmd_up(a):
    cmd_sync(argparse.Namespace(sources=[], prune=False))
    cmd_build(argparse.Namespace(kbs=None, force=False))
    cmd_serve(argparse.Namespace(kbs=None, no_wait=False, timeout=1800))


def cmd_watch(a):
    """Poll checkouts; rebuild and restart any served KB whose inputs changed."""
    last_sync = 0.0
    print(f"watching every {a.interval}s"
          + (f", syncing remotes every {a.sync_every}s" if a.sync_every else "")
          + "; Ctrl-C to stop")
    while True:
        try:
            cfg = _cfg()
            if a.sync_every and time.time() - last_sync >= a.sync_every:
                for src in cfg.sources.values():
                    for m in sources.sync_source(src):
                        print(f"[{time.strftime('%H:%M:%S')}] {m}")
                last_sync = time.time()
            st = serve.load_state(cfg)
            for kb in _served(cfg, a.kbs):
                if not build.stale(cfg, kb):
                    continue
                print(f"[{time.strftime('%H:%M:%S')}] {kb.name}: inputs changed")
                if build.build_kb(cfg, kb) and kb.name in st["backends"]:
                    serve.stop_backend(cfg, kb.name)
                    serve.start_backend(cfg, kb, wait=False)
        except KeyboardInterrupt:
            raise
        except SystemExit as e:
            print(f"!! {e}", file=sys.stderr)
        except Exception:
            traceback.print_exc()
        time.sleep(a.interval)


def _kind(a):
    return "super" if a.super else "equiv" if a.equiv else "inst" if getattr(a, "inst", False) else "sub"


def cmd_q(a):
    cfg = _cfg()
    res = query.ask(cfg, a.kb, _kind(a), a.expr, a.direct)
    print("\n".join(query.render(cfg, a.kb, res)) or "(none)")


def cmd_compare(a):
    cfg = _cfg()
    k = _kind(a)
    ra = set(query.ask(cfg, a.kb_a, k, a.expr, a.direct))
    rb = set(query.ask(cfg, a.kb_b, k, a.expr, a.direct))
    for title, kb, xs in ((f"only in {a.kb_a}", a.kb_a, ra - rb),
                          (f"only in {a.kb_b}", a.kb_b, rb - ra)):
        print(f"## {title} ({len(xs)})")
        print("\n".join(query.render(cfg, kb, sorted(xs))) or "(none)")
    print(f"## in both: {len(ra & rb)}")


def cmd_unsat(a):
    cfg = _cfg()
    res = [i for i in query.ask(cfg, a.kb, "equiv", "owl:Nothing")
           if not i.endswith("#Nothing")]
    print("\n".join(query.render(cfg, a.kb, res)) or "(none)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("setup").set_defaults(f=cmd_setup)
    p = sp.add_parser("sync")
    p.add_argument("sources", nargs="*")
    p.add_argument("--prune", action="store_true",
                   help="remove clean managed worktrees no longer in the config")
    p.set_defaults(f=cmd_sync)
    sp.add_parser("status").set_defaults(f=cmd_status)
    sp.add_parser("kbs").set_defaults(f=cmd_kbs)
    p = sp.add_parser("build")
    p.add_argument("kbs", nargs="*")
    p.add_argument("--force", action="store_true")
    p.set_defaults(f=cmd_build)
    for name, f in (("serve", cmd_serve), ("restart", cmd_restart)):
        p = sp.add_parser(name)
        p.add_argument("kbs", nargs="*")
        p.add_argument("--timeout", type=int, default=1800)
        if name == "serve":
            p.add_argument("--no-wait", action="store_true")
        p.set_defaults(f=f)
    p = sp.add_parser("stop")
    p.add_argument("kbs", nargs="*")
    p.set_defaults(f=cmd_stop)
    sp.add_parser("up").set_defaults(f=cmd_up)
    p = sp.add_parser("watch")
    p.add_argument("kbs", nargs="*")
    p.add_argument("--interval", type=int, default=20)
    p.add_argument("--sync-every", type=int, default=0,
                   help="also run `wb sync` this often (seconds; 0 = never)")
    p.set_defaults(f=cmd_watch)
    for name, f in (("q", cmd_q), ("compare", cmd_compare)):
        p = sp.add_parser(name)
        if name == "q":
            p.add_argument("kb")
        else:
            p.add_argument("kb_a")
            p.add_argument("kb_b")
        p.add_argument("expr")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--super", action="store_true")
        g.add_argument("--equiv", action="store_true")
        if name == "q":
            g.add_argument("--inst", action="store_true")
        p.add_argument("--direct", action="store_true")
        p.set_defaults(f=f)
    p = sp.add_parser("unsat")
    p.add_argument("kb")
    p.set_defaults(f=cmd_unsat)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # `wb watch > log` shows progress live
    try:
        a.f(a)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
