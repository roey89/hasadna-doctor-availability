#!/usr/bin/env python3
"""Run the Clalit crawl in parallel with ONE SESSION PER WORKER.

Sessions are the isolation unit: a shared session corrupts paging (the server
tracks one active search per session). So each worker gets its own session
file. --setup N logs in N times (sequentially - do the SMS codes one at a
time); exported sessions are reused on later runs until they expire.

Usage:
  python3 run_parallel.py --setup --workers 4          # log in 4 times -> session-0..3.json
  python3 run_parallel.py --workers 4 --cities-file data/cities.txt
  python3 run_parallel.py --merge --workers 4

Pick any worker count at run time. --setup N and the run must use the same N
(or fewer - extra sessions are just ignored).
"""

import argparse
import csv
import pathlib
import shutil
import subprocess
import sys

BASE_PROFILE = "./clalit-profile"
CRAWLER = "clalit_crawl.py"
WORKDIR = pathlib.Path("./parallel")


def session_path(w):
    return WORKDIR / f"session-{w}.json"


def setup(n):
    """Log in n times, one after another, exporting a session per worker."""
    from playwright.sync_api import sync_playwright
    import clalit_crawl as cc
    WORKDIR.mkdir(exist_ok=True)
    pathlib.Path("data").mkdir(exist_ok=True)

    for w in range(n):
        prof = WORKDIR / f"profile-{w}"
        print(f"\n=== worker {w}: log in (ID, password, CAPTCHA, SMS) ===")
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(prof), headless=False, locale="he-IL")
            pg = ctx.pages[0] if ctx.pages else ctx.new_page()
            sess = cc.Session(ctx, pg, 0.3, 0.2)
            if not cc.ensure_session(sess):
                print(f"worker {w} login failed - stopping"); ctx.close(); return
            # cache taxonomy once, from the first session
            if w == 0:
                cc.OUT = pathlib.Path("data")
                cc.load_taxonomy(sess, force=True)
            ctx.storage_state(path=str(session_path(w)))
            print(f"  exported {session_path(w)}")
            ctx.close()
    print(f"\n{n} sessions ready.")


def shard(cities_file, n):
    lines = [l.strip() for l in
             pathlib.Path(cities_file).read_text(encoding="utf-8").splitlines()
             if l.strip()]
    shards = [[] for _ in range(n)]
    for i, c in enumerate(lines):
        shards[i % n].append(c)
    return shards


def run(args):
    n = args.workers
    missing = [w for w in range(n) if not session_path(w).exists()]
    if missing:
        print(f"Missing sessions for workers {missing}. "
              f"Run: python3 run_parallel.py --setup --workers {n}")
        sys.exit(1)
    if not pathlib.Path("data/taxonomy.json").exists():
        print("No data/taxonomy.json. Run --setup first."); sys.exit(1)

    WORKDIR.mkdir(exist_ok=True)
    shards = shard(args.cities_file, n)

    procs = []
    for w in range(n):
        out = WORKDIR / f"out-{w}"
        out.mkdir(exist_ok=True)
        cfile = WORKDIR / f"cities-{w}.txt"
        cfile.write_text("\n".join(shards[w]), encoding="utf-8")
        if not (out / "taxonomy.json").exists():
            shutil.copy("data/taxonomy.json", out / "taxonomy.json")

        cmd = [sys.executable, CRAWLER,
               "--session", str(session_path(w)), "--headless",
               "--delay", str(args.delay), "--jitter", str(args.jitter),
               "--cities-file", str(cfile),
               "--out", str(out), "--yes"]
        if args.skip_referral_gated:
            cmd.append("--skip-referral-gated")

        log = open(WORKDIR / f"worker-{w}.log", "w")
        print(f"worker {w}: {len(shards[w])} cities -> {out}")
        procs.append((w, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)))

    print(f"\n{n} headless workers running (one session each).")
    print(f"  tail -f {WORKDIR}/worker-*.log")

    try:
        for w, pr in procs:
            pr.wait()
            print(f"worker {w} done")
    except KeyboardInterrupt:
        print("\ninterrupted - workers checkpoint per pair; rerun to resume")
        for _, pr in procs:
            pr.terminate()
        return

    merge(n)


def merge(n):
    rows, header = [], None
    for w in range(n):
        f = WORKDIR / f"out-{w}" / "diaries.csv"
        if not f.exists():
            continue
        with open(f, encoding="utf-8-sig") as fh:
            r = csv.reader(fh)
            h = next(r, None)
            if header is None:
                header = h
            rows.extend(r)
    if header is None:
        print("no output"); return

    merged = WORKDIR / "diaries_merged.csv"
    with open(merged, "w", newline="", encoding="utf-8-sig") as fh:
        w_ = csv.writer(fh); w_.writerow(header); w_.writerows(rows)
    print(f"merged {len(rows)} rows -> {merged}")

    try:
        si, ti = header.index("stable_key"), header.index("scraped_at")
        latest = {}
        for row in rows:
            k = row[si]
            if k and (k not in latest or row[ti] > latest[k][ti]):
                latest[k] = row
        ded = WORKDIR / "diaries_dedup.csv"
        with open(ded, "w", newline="", encoding="utf-8-sig") as fh:
            w_ = csv.writer(fh); w_.writerow(header); w_.writerows(latest.values())
        print(f"deduped -> {len(latest)} unique doctors -> {ded}")
    except ValueError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true", help="log in N times -> N sessions")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cities-file", default="data/cities.txt")
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--jitter", type=float, default=0.2)
    ap.add_argument("--skip-referral-gated", action="store_true")
    args = ap.parse_args()

    if args.setup:
        setup(args.workers)
    elif args.merge:
        merge(args.workers)
    else:
        run(args)


if __name__ == "__main__":
    main()