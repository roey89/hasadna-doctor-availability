# Clalit appointment-availability crawler

Sweeps Clalit's Zimunet booking app (specialization × city) and records every
doctor/clinic with their **next available date**. Read-only: searches and paged
reads only, never a booking. Research goal in `summary.md`.

## Setup

```bash
pip3 install playwright beautifulsoup4 lxml
python3 -m playwright install chromium
```

Login is manual (ID, password, CAPTCHA, SMS) in a visible browser window;
cookies persist in `./clalit-profile`. **Run setup with a real terminal** — the
login step blocks on Enter.

## Use

```bash
python3 clalit_crawl.py --dry-run                      # login + one pair, sanity check
python3 clalit_crawl.py --specs 58 --cities "תל אביב יפו"
python3 dump_cities.py                                 # -> data/cities.txt (1,141 localities)

# parallel: one login per worker, then run
python3 run_parallel.py --setup --workers 10
python3 run_parallel.py --workers 10 --cities-file data/cities.txt
python3 run_parallel.py --merge --workers 10
```

Useful flags: `--no-district` (see findings), `--skip-referral-gated` (drops 57
of 96 specs that usually return nothing), `--slots` (Tier 2: individual time
slots, 1+ request per doctor), `--out`, `--headless`, `--restart`.

`clalit_scrape.py` is recon only — dumps a page and logs its XHR endpoints.

## Output (`data/`, or `--out`)

| file | contents |
|---|---|
| `diaries.csv` | one row per (spec, city, doctor); `next_available_date`, `days_until`, clinic, phone. `result_total=0, page=0` marks a searched pair with no availability |
| `facets.csv` | gender / language / visit-type counts per search (free with each search) |
| `slots.csv` | one row per time slot (`--slots` only) |
| `taxonomy.json` | 34 groups, 96 specialization codes |
| `state.json` | resume checkpoint, per (spec, city) pair — rerun the same command to continue |

Join across runs on `stable_key` (name+profession+clinic+address), **not**
`diary_guid`.

## Findings

* **`diary_guid` is minted per response**, not per doctor — useless as a key,
  and it makes the in-crawl page dedup in `clalit_crawl.py:691` inoperative
  (so the `stall >= 2` wrap detection never fires). Dedup at analysis time.
* **Anchor cities are not sufficient.** `--anchor-cities` + the 30km
  "כולל יישובים בסביבה" radius silently misses localities outside every radius
  (e.g. קצרין, which has doctors in 8+ specialisations). For a defensible
  national dataset use `--no-district` over the full `data/cities.txt`:
  ~115k requests, no duplication, each diary attributed to one city.
* **Sessions die after roughly an hour** of continuous use, so any national run
  needs mid-run re-authentication.
* **Paging is server-side stateful**, keyed by the `__zn` cookie: one session =
  one serial lane. Two workers sharing a session corrupt each other's paging,
  and threads inside one session buy nothing (server-side session lock). Scale
  by logins, not threads.
* **Page size is fixed at 7 rows** (6 on page 1 — one slot is an ad); no
  parameter changes it. There is **no nationwide query**: an empty city
  silently falls back to a default city.
* Same-day availability churns within minutes. Compare runs by timestamp.
* **Always keep positive controls** in coverage tests — a dead session returns
  "0 doctors" indistinguishably from a genuine zero.

## Known bug

If a session expires mid-run while a terminal is attached, headless workers
block forever on the login prompt instead of failing. Watch for stalled
`worker-*.log` tails.
