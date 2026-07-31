#!/usr/bin/env python3
"""Enumerate every city known to Clalit's GetCities autocomplete.

GetCities?term=X returns cities whose name CONTAINS X (substring match).
A single letter caps results (the endpoint truncates long lists), so we sweep
all Hebrew one- and two-letter prefixes, union everything, and write a sorted
unique list.

    python3 dump_cities.py                 # -> data/cities.txt
    python3 dump_cities.py --out ./data --delay 0.1

Feed the result to the crawler with --cities-file.
"""

import argparse
import json
import pathlib
import time

from playwright.sync_api import sync_playwright
import clalit_crawl as cc

BASE = "https://e-services.clalit.co.il"
GETCITIES = f"{BASE}/Zimunet/Diary/GetCities"
HDR = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/Zimunet/Diary"}

HE = "אבגדהוזחטיכלמנסעפצקרשת"          # 22 Hebrew letters
FINALS = "ךםןףץ"                         # final forms appear mid-response, not as prefixes


def parse_cities(raw):
    """GetCities returns JSON. Shape unknown up front, so handle list-of-str,
    list-of-dict, or a data-wrapped variant."""
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    if isinstance(obj, dict):
        obj = obj.get("data", obj)
    out = []
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, str):
                out.append(item.strip())
            elif isinstance(item, dict):
                # common keys: label / value / name / Text
                for k in ("label", "value", "name", "Text", "text", "City", "cityName"):
                    if k in item and isinstance(item[k], str):
                        out.append(item[k].strip())
                        break
    return [c for c in out if c]


def fetch(pg, term):
    r = pg.request.get(GETCITIES, headers=HDR,
                       params={"term": term, "_": str(int(time.time() * 1000))})
    if r.status != 200:
        return None, r.status
    return parse_cities(r.text()), 200


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data")
    ap.add_argument("--delay", type=float, default=0.1)
    ap.add_argument("--single-letter-only", action="store_true",
                    help="only sweep 22 single letters (faster, may miss some)")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Build the term list: single letters, then two-letter combos to defeat
    # any per-query result cap.
    terms = list(HE)
    if not args.single_letter_only:
        terms += [a + b for a in HE for b in HE]   # 22 + 484 = 506 queries

    cities = set()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(pathlib.Path("./clalit-profile")), headless=False, locale="he-IL")
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        sess = cc.Session(ctx, pg, args.delay, 0)
        if not cc.ensure_session(sess):
            print("no session"); ctx.close(); return

        # sanity: dump the raw shape once so we know the parser is right
        first, st = fetch(pg, "או")
        print(f"probe term=או -> status {st}, {len(first or [])} cities")
        if first:
            print("  sample:", first[:5])
        cities.update(first or [])

        for i, t in enumerate(terms, 1):
            got, st = fetch(pg, t)
            if got is None:
                print(f"[{i}/{len(terms)}] term={t!r} HTTP {st} - skipping")
            else:
                new = len(set(got) - cities)
                cities.update(got)
                if i % 25 == 0 or new:
                    print(f"[{i}/{len(terms)}] term={t!r} +{new} (total {len(cities)})")
            time.sleep(args.delay)

        ctx.close()

    path = out / "cities.txt"
    path.write_text("\n".join(sorted(cities)), encoding="utf-8")
    print(f"\n{len(cities)} unique cities -> {path}")


if __name__ == "__main__":
    main()