#!/usr/bin/env python3
"""
Clalit Zimunet appointment crawler.

Tier 1 (default): for each specialization x city, POST /Zimunet/Diary/SearchDiaries,
walk the pager, and record every doctor/clinic with their NEXT AVAILABLE DATE.
Cheap: ~1 + n_pages requests per (spec, city) pair.

Tier 2 (--slots): for rows selected by --slots-filter, open
/Zimunet/AvailableVisit/Index/{guid}, read availableDays from the page, and
record every individual time slot. Expensive: 1+ requests per doctor.

Requires the logged-in profile created earlier:
    pip3 install playwright beautifulsoup4 lxml
    python3 -m playwright install chromium

Examples:
    # Discover taxonomy, then dry-run one pair to check everything works
    python3 clalit_crawl.py --dry-run

    # Tier 1 over a few specializations in Tel Aviv
    python3 clalit_crawl.py --specs 58,31,61 --cities "תל אביב יפו"

    # Tier 1 nationally (anchor cities), then slots for anything within 14 days
    python3 clalit_crawl.py --all-specs --anchor-cities
    python3 clalit_crawl.py --all-specs --anchor-cities --slots --slots-within-days 14

Output (./data/):
    diaries.csv     one row per (spec, city, doctor) with next_available_date
    slots.csv       one row per individual appointment slot (Tier 2)
    taxonomy.json   group + specialization code tables
    facets.csv      gender/language/visit-type counts per search
    raw/            raw responses when --save-raw
    state.json      resume checkpoint
"""

import argparse
import csv
import json
import pathlib
import random
import re
import sys
import time
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

import zimunet_parse as zp

BASE = "https://e-services.clalit.co.il"
TAMUZ_URL = f"{BASE}/OnlineWeb/Services/Tamuz/TamuzTransfer.aspx"
DIARY_URL = f"{BASE}/Zimunet/Diary"
SEARCH_URL = f"{BASE}/Zimunet/Diary/SearchDiaries"
PAGING_URL = f"{BASE}/Zimunet/Diary/Paging"
KEEPALIVE_URL = f"{BASE}/OnlineWeb/Services/tamuz/SyncSession.aspx"

PROFILE_DIR = "./clalit-profile"
OUT = pathlib.Path("./data")

# "כולל יישובים בסביבה" pulls in neighbouring localities, so a couple of dozen
# anchor cities cover the country instead of ~1,200 individual localities.
ANCHOR_CITIES = [
    "תל אביב יפו", "ירושלים", "חיפה", "באר שבע", "ראשון לציון",
    "פתח תקווה", "נתניה", "אשדוד", "אשקלון", "רחובות",
    "חולון", "בת ים", "רמת גן", "הרצליה", "כפר סבא",
    "רעננה", "מודיעין מכבים רעות", "בית שמש", "אילת", "טבריה",
    "צפת", "כרמיאל", "עפולה", "נצרת", "עכו",
    "חדרה", "קרית גת", "דימונה", "יבנה", "לוד",
]

DIARY_FIELDS = [
    "scraped_at", "group_code", "group_name", "spec_code", "spec_name",
    "search_city", "include_district", "result_total", "page",
    "stable_key", "diary_guid", "doctor_name", "profession",
    "next_available_date", "days_until", "clinic_name", "clinic_address",
    "distance", "phone", "visit_types", "map_url", "slots_link",
]

SLOT_FIELDS = [
    "scraped_at", "diary_guid", "doctor_name", "spec_code", "spec_name",
    "search_city", "clinic_name", "clinic_code", "day", "day_part", "time",
    "slot_guid", "zohar_visit_type", "doctor_license", "doctor_gender",
    "family_profession", "patient_age",
]


# ---------------------------------------------------------------- utilities

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def parse_dmy(s):
    """'30.07.2026' or '30.7.2026' -> date"""
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def days_until(datestr):
    d = parse_dmy(datestr)
    return (d - datetime.now().date()).days if d else None


def stable_key(row):
    """diary_guid is a SESSION-SCOPED handle - the same doctor gets a different
    GUID on every login, so it cannot be used to join across runs. Build a key
    from the fields that actually persist."""
    parts = [
        (row.get("doctor_name") or "").strip(),
        (row.get("profession") or "").strip(),
        (row.get("clinic_name") or "").strip(),
        (row.get("clinic_address") or "").strip(),
    ]
    return "|".join(re.sub(r"\s+", " ", p) for p in parts)


class CsvSink:
    """Append-only CSV writer that flushes every row so a crash keeps prior work."""

    def __init__(self, path, fields):
        self.path = pathlib.Path(path)
        self.fields = fields
        new = not self.path.exists()
        self.fh = open(self.path, "a", newline="", encoding="utf-8-sig")
        self.w = csv.DictWriter(self.fh, fieldnames=fields, extrasaction="ignore")
        if new:
            self.w.writeheader()
            self.fh.flush()
        self.count = 0

    def write(self, row):
        self.w.writerow(row)
        self.count += 1
        self.fh.flush()

    def close(self):
        self.fh.close()


class Session:
    """Wraps the browser context; all requests reuse its cookies."""

    def __init__(self, ctx, page, delay, jitter):
        self.ctx = ctx
        self.page = page
        self.delay = delay
        self.jitter = jitter
        self.n_requests = 0
        self.last_keepalive = time.time()

    def throttle(self):
        time.sleep(self.delay + random.uniform(0, self.jitter))

    def keepalive_if_due(self):
        # Session dies after 15 min idle; ping well inside that.
        if time.time() - self.last_keepalive > 300:
            try:
                self.page.request.get(KEEPALIVE_URL)
                self.last_keepalive = time.time()
            except Exception as e:
                log(f"  keepalive failed: {e}")

    def _request(self, method, url, **kw):
        """Single request with retry + backoff on transient network errors
        (timeouts, resets). A multi-day crawl WILL hit these; one slow page
        must not kill the run. Raises only after all attempts fail."""
        from playwright.sync_api import Error as PWError
        kw.setdefault("timeout", 45000)
        last = None
        for attempt in range(1, 5):   # 4 tries
            try:
                if method == "post":
                    r = self.page.request.post(url, **kw)
                else:
                    r = self.page.request.get(url, **kw)
                self.n_requests += 1
                self.throttle()
                return r
            except PWError as e:
                last = e
                wait = 2 ** attempt          # 2, 4, 8, 16s
                log(f"    request error ({type(e).__name__}), retry {attempt}/4 in {wait}s")
                time.sleep(wait)
        # exhausted - re-warm the session once, it may have died
        log("    all retries failed; re-establishing session")
        if ensure_session(self):
            try:
                r = (self.page.request.post if method == "post"
                     else self.page.request.get)(url, **kw)
                self.n_requests += 1
                self.throttle()
                return r
            except PWError as e:
                last = e
        raise last

    def post_search(self, spec_code, group_code, city, include_district):
        self.keepalive_if_due()
        form = {
            "SelectedGroupCode": str(group_code),
            "SelectedSpecializationCode": str(spec_code),
            "SelectedCityName": city,
            "IsSearchDiariesByDistricts": "true" if include_district else "false",
            "SelectedDoctorName": "",
        }
        return self._request("post", SEARCH_URL, form=form,
                             headers={"X-Requested-With": "XMLHttpRequest",
                                      "Referer": DIARY_URL})

    def get_page(self, page_number):
        self.keepalive_if_due()
        return self._request("get", f"{PAGING_URL}?pageNumber={page_number}",
                             headers={"X-Requested-With": "XMLHttpRequest",
                                      "Referer": DIARY_URL})

    def get_visit_page(self, diary_guid):
        self.keepalive_if_due()
        return self._request(
            "get", f"{BASE}/Zimunet/AvailableVisit/Index/{diary_guid}?isUpdateVisit=False",
            headers={"Referer": DIARY_URL})

    def looks_logged_out(self, body):
        return ("Login.aspx" in body or "login.aspx" in body.lower()
                or "כניסה לכללית" in body
                or "HomeRegistrationLogin" in body)


# ---------------------------------------------------------------- session

def _has_tty():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def _wait_for_login(page, timeout_s=300):
    """Wait for the user to finish logging in in the browser window, WITHOUT
    needing an Enter keypress. Polls until the Diary form appears. Works for
    parallel workers that have no terminal stdin. Returns True if the form
    showed up in time."""
    log(f"  waiting up to {timeout_s}s for login to complete in the browser...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            # If they've landed anywhere with the form, we're in.
            if page.query_selector("#SelectedGroupCode"):
                return True
            # Nudge toward the diary page periodically in case login finished
            # on the OnlineWeb side but Zimunet wasn't synced yet.
            if "login" not in page.url.lower():
                try:
                    page.request.get(KEEPALIVE_URL)
                except Exception:
                    pass
                page.goto(DIARY_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(1000)
                if page.query_selector("#SelectedGroupCode"):
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _prompt_or_wait(page, msg):
    """Block on Enter if we have a terminal; otherwise poll for the form."""
    if _has_tty():
        input(msg)
        return True
    return _wait_for_login(page)


def ensure_session(session, attempts=3):
    """Zimunet is a SEPARATE app with its own session, seeded from the
    OnlineWeb session via SyncSession.aspx. Hitting /Zimunet/Diary cold gives
    a page with no form and no 'login' in the URL, so warm up properly:
        TamuzTransfer.aspx  ->  SyncSession.aspx  ->  /Zimunet/Diary
    Returns True once the search form is actually present.
    """
    page = session.page

    for attempt in range(1, attempts + 1):
        log(f"Establishing session (attempt {attempt}/{attempts}) ...")

        # 1. OnlineWeb + the Tamuz auth transfer (the iframe does the handoff)
        page.goto(TAMUZ_URL, wait_until="domcontentloaded")
        if "login" in page.url.lower():
            _prompt_or_wait(page,
                "  Log in in the browser window (ID, password, CAPTCHA, SMS), "
                "then press Enter... ")
            # after waiting, check whether we already reached the form
            if page.query_selector("#SelectedGroupCode"):
                log(f"  Session OK - form present at {page.url}")
                session.last_keepalive = time.time()
                return True
            continue

        page.wait_for_timeout(4000)   # let ifrmMainTamuz complete the transfer

        # 2. Explicitly sync the Zimunet session
        try:
            r = page.request.get(KEEPALIVE_URL)
            log(f"  SyncSession -> HTTP {r.status}")
        except Exception as e:
            log(f"  SyncSession failed: {e}")

        # 3. Now the Zimunet diary page should render the form
        page.goto(DIARY_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        if page.query_selector("#SelectedGroupCode"):
            log(f"  Session OK - form present at {page.url}")
            session.last_keepalive = time.time()
            return True

        # Diagnose instead of silently continuing with an empty taxonomy.
        OUT.mkdir(exist_ok=True)
        dbg = OUT / f"session_debug_{attempt}.html"
        dbg.write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(OUT / f"session_debug_{attempt}.png"))
        except Exception:
            pass

        log(f"  No search form. url={page.url}")
        log(f"  title={page.title()!r}")
        log(f"  saved {dbg.name} (+ .png)")

        body = page.content()
        if session.looks_logged_out(body):
            log("  -> looks logged out")
        elif "/Zimunet/" in page.url and "Diary" not in page.url:
            log("  -> redirected away from Diary")

        if _prompt_or_wait(page,
                "  Fix it in the browser window (log in, and click through to "
                "זימון תורים -> רפואה יועצת if needed), then press Enter... "):
            if page.query_selector("#SelectedGroupCode"):
                log(f"  Session OK - form present at {page.url}")
                session.last_keepalive = time.time()
                return True

    return False


# ---------------------------------------------------------------- taxonomy

def load_taxonomy(session, force=False):
    path = OUT / "taxonomy.json"
    if path.exists() and not force:
        tax = json.loads(path.read_text(encoding="utf-8"))
        if tax.get("specializations"):
            log(f"Taxonomy from cache: {len(tax['specializations'])} specializations")
            return tax
        log("Cached taxonomy is empty - reloading")

    if not ensure_session(session):
        log("Could not establish a session. Aborting.")
        sys.exit(1)

    log("Reading taxonomy from the live form ...")

    tax = session.page.evaluate("""() => {
        const out = {groups: [], specializations: []};
        document.querySelectorAll('#SelectedGroupCode option').forEach(o => {
            out.groups.push({code: o.value, name: o.textContent.trim()});
        });
        document.querySelectorAll('#SelectedSpecializationCode option').forEach(o => {
            if (o.value === '0') return;
            let groups = [];
            try { groups = JSON.parse(o.dataset.groups || '[]'); } catch(e) {}
            out.specializations.push({
                code: o.value,
                name: o.textContent.trim(),
                groups: groups,
                sourceSystem: o.dataset.sourceSystem || null,
            });
        });
        const html = document.documentElement.innerHTML;
        const m = html.match(/specializationsWithMedicalReferrals:\\s*\\[([^\\]]*)\\]/);
        out.withReferrals = m && m[1].trim()
            ? m[1].split(',').map(s => s.trim()) : [];
        const m2 = html.match(/specializationsWithoutMedicalReferrals:\\s*\\[([^\\]]*)\\]/);
        out.withoutReferrals = m2 && m2[1].trim()
            ? m2[1].split(',').map(s => s.trim()) : [];
        return out;
    }""")

    if not tax.get("specializations"):
        log("  Taxonomy is EMPTY - the form was not readable.")
        log("  Not writing taxonomy.json. Check data/session_debug_*.html")
        sys.exit(1)

    OUT.mkdir(exist_ok=True)
    path.write_text(json.dumps(tax, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  {len(tax['groups'])} groups, {len(tax['specializations'])} specializations")
    log(f"  referral-gated: {len(tax.get('withoutReferrals', []))} codes")
    return tax


def select_specs(tax, args):
    specs = tax["specializations"]
    by_code = {s["code"]: s for s in specs}

    if args.specs:
        wanted = [c.strip() for c in args.specs.split(",") if c.strip()]
        chosen = [by_code[c] for c in wanted if c in by_code]
        missing = [c for c in wanted if c not in by_code]
        if missing:
            log(f"  unknown spec codes ignored: {missing}")
    else:
        chosen = list(specs)

    if args.skip_referral_gated:
        gated = set(tax.get("withoutReferrals", []))
        before = len(chosen)
        chosen = [s for s in chosen
                  if s["code"] not in gated and "נדרשת הפניה" not in s["name"]]
        log(f"  skipped {before - len(chosen)} referral-gated specializations")

    return chosen


def group_name_for(tax, spec):
    if not spec.get("groups"):
        return ""
    gc = str(spec["groups"][0])
    for g in tax["groups"]:
        if g["code"] == gc:
            return g["name"]
    return ""


# ---------------------------------------------------------------- crawl

def crawl(args):
    global OUT
    OUT = pathlib.Path(args.out)
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    raw_dir = OUT / "raw"
    if args.save_raw:
        raw_dir.mkdir(exist_ok=True)

    state_path = OUT / "state.json"
    done = set()
    if state_path.exists() and not args.restart:
        done = set(json.loads(state_path.read_text(encoding="utf-8")).get("done", []))
        log(f"Resuming: {len(done)} (spec, city) pairs already done")

    with sync_playwright() as p:
        if args.session:
            # Shared-login mode: load one exported storage_state. No profile,
            # no login prompt - every worker reuses the same session.json.
            browser = p.chromium.launch(headless=args.headless)
            ctx = browser.new_context(storage_state=args.session,
                                      viewport={"width": 1400, "height": 900},
                                      locale="he-IL")
        else:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=args.profile,
                headless=args.headless,
                viewport={"width": 1400, "height": 900},
                locale="he-IL",
            )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        session = Session(ctx, page, args.delay, args.jitter)

        tax = load_taxonomy(session, force=args.refresh_taxonomy)
        specs = select_specs(tax, args)

        # Warm up the Zimunet search context (GET /Zimunet/Diary) before any
        # POST. In shared-session mode there's no login to wait for, so if the
        # shared session is dead we abort immediately rather than polling.
        if not session.page.query_selector("#SelectedGroupCode"):
            if args.session:
                page.goto(DIARY_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                if not page.query_selector("#SelectedGroupCode"):
                    try:
                        page.request.get(KEEPALIVE_URL)
                        page.goto(DIARY_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                if not page.query_selector("#SelectedGroupCode"):
                    log("Shared session appears dead - re-export session.json. Aborting.")
                    ctx.close()
                    return
                session.last_keepalive = time.time()
            elif not ensure_session(session):
                log("Could not establish a Zimunet session. Aborting.")
                ctx.close()
                return

        if args.cities_file:
            cities = [ln.strip() for ln in
                      pathlib.Path(args.cities_file).read_text(encoding="utf-8").splitlines()
                      if ln.strip()]
            log(f"Loaded {len(cities)} cities from {args.cities_file}")
        elif args.cities:
            cities = [c.strip() for c in args.cities.split(",") if c.strip()]
        elif args.anchor_cities:
            cities = ANCHOR_CITIES
        else:
            cities = ["תל אביב יפו"]

        pairs = [(s, c) for s in specs for c in cities]
        todo = [(s, c) for s, c in pairs if f"{s['code']}|{c}" not in done]

        est = len(todo) * (1 + args.max_pages / 2)
        log(f"{len(specs)} specializations x {len(cities)} cities = {len(pairs)} pairs")
        log(f"{len(todo)} remaining; roughly {est:.0f} requests "
            f"at ~{args.delay}s apart = ~{est * args.delay / 60:.0f} min")

        if args.dry_run:
            todo = todo[:1]
            log("DRY RUN: one pair only")
        elif not args.yes:
            if input("Proceed? [y/N] ").strip().lower() != "y":
                ctx.close()
                return

        diaries = CsvSink(OUT / "diaries.csv", DIARY_FIELDS)
        facets = CsvSink(OUT / "facets.csv",
                         ["scraped_at", "spec_code", "spec_name", "search_city",
                          "facet_type", "facet_value", "count"])
        slots_sink = CsvSink(OUT / "slots.csv", SLOT_FIELDS) if args.slots else None

        harvested = []   # rows eligible for Tier 2

        try:
            for i, (spec, city) in enumerate(todo, 1):
                pair_key = f"{spec['code']}|{city}"
                gname = group_name_for(tax, spec)
                log(f"[{i}/{len(todo)}] {spec['name'][:38]} @ {city}")

                r = session.post_search(
                    spec["code"],
                    spec["groups"][0] if spec.get("groups") else 0,
                    city,
                    not args.no_district,
                )

                # Re-establish and retry once if the session dropped.
                if r.status != 200 or session.looks_logged_out(r.text()):
                    log(f"    HTTP {r.status} / logged out - re-establishing session")
                    if not ensure_session(session):
                        log("    Could not recover session. Stopping.")
                        break
                    r = session.post_search(
                        spec["code"],
                        spec["groups"][0] if spec.get("groups") else 0,
                        city,
                        not args.no_district,
                    )
                    if r.status != 200:
                        log(f"    still HTTP {r.status} - skipping this pair")
                        continue

                body = r.text()
                if session.looks_logged_out(body):
                    log("    still logged out - skipping this pair")
                    continue

                html = zp.unwrap(body)

                # "No appointments here" popup (errorType 3). VERY common on a
                # national crawl - niche specialty in a small town. Must be
                # checked BEFORE the non-HTML guard: it carries HTML (a modal),
                # so it would otherwise slip past, and it must NOT trigger a
                # session re-warm. Record a zero-row and move on.
                if zp.is_no_results(body, html):
                    log("    0 results (no availability)")
                    diaries.write({
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                        "group_code": (spec["groups"][0] if spec.get("groups") else ""),
                        "group_name": group_name_for(tax, spec),
                        "spec_code": spec["code"], "spec_name": spec["name"],
                        "search_city": city, "include_district": not args.no_district,
                        "result_total": 0, "page": 0,
                    })
                    done.add(pair_key)
                    state_path.write_text(
                        json.dumps({"done": sorted(done)}, ensure_ascii=False),
                        encoding="utf-8")
                    continue

                # On errors/redirects the envelope's "data" is not HTML. Most
                # often the Zimunet search context has gone stale, so re-warm
                # and retry the pair once before giving up on it.
                if not html.strip() or "<" not in html:
                    info = zp.envelope_info(body)
                    log(f"    Non-HTML payload {info} - re-warming session")
                    OUT.mkdir(exist_ok=True)
                    (OUT / f"unexpected_{spec['code']}_{city}.json").write_text(
                        body if isinstance(body, str) else str(body),
                        encoding="utf-8")

                    if not ensure_session(session):
                        log("    Could not recover. Stopping.")
                        break
                    r = session.post_search(
                        spec["code"],
                        spec["groups"][0] if spec.get("groups") else 0,
                        city,
                        not args.no_district,
                    )
                    body = r.text()
                    html = zp.unwrap(body)
                    if zp.is_no_results(body, html):
                        log("    0 results (no availability)")
                        done.add(pair_key)
                        continue
                    if not html.strip() or "<" not in html:
                        log(f"    Still non-HTML {zp.envelope_info(body)} - skipping")
                        continue
                    log("    recovered")

                if args.save_raw:
                    (raw_dir / f"search_{spec['code']}_{city}.html").write_text(
                        html, encoding="utf-8")

                total, header = zp.parse_result_header(html)

                # Genuine "no doctors here" - extremely common on a national
                # crawl (niche specialty in a small town). Record it and move on
                # without walking the pager. total==0 comes back as valid HTML;
                # total is None with blank body is an empty/odd response.
                if total == 0 or (total is None and not html.strip()):
                    log(f"    0 results")
                    diaries.write({
                        "scraped_at": datetime.now().isoformat(timespec="seconds"),
                        "group_code": (spec["groups"][0] if spec.get("groups") else ""),
                        "group_name": group_name_for(tax, spec),
                        "spec_code": spec["code"], "spec_name": spec["name"],
                        "search_city": city, "include_district": not args.no_district,
                        "result_total": 0, "page": 0,
                    })
                    done.add(pair_key)
                    continue

                # facet counts come free with the search
                for ftype, items in zp.parse_filter_counts(html).items():
                    for val, cnt in items.items():
                        facets.write({
                            "scraped_at": datetime.now().isoformat(timespec="seconds"),
                            "spec_code": spec["code"], "spec_name": spec["name"],
                            "search_city": city, "facet_type": ftype,
                            "facet_value": val, "count": cnt,
                        })

                # The pager is a SLIDING WINDOW: page 1 only links pages 2-5,
                # so we cannot trust it as the page count. Walk forward until
                # we have result_total rows, a page returns nothing, or we see
                # only GUIDs/keys we already have.
                n_rows = 0
                seen_keys = set()
                pno = 1
                stall = 0

                while pno <= args.max_pages:
                    if pno == 1:
                        page_html = html
                    else:
                        pr = session.get_page(pno)
                        if pr.status != 200:
                            log(f"    page {pno}: HTTP {pr.status} - stopping")
                            break
                        page_html = zp.unwrap(pr.text())

                    rows = zp.parse_diaries(page_html)
                    if not rows:
                        break

                    new_on_page = 0
                    for row in rows:
                        skey = stable_key(row)
                        # Dedup on diary_guid: it's unique per diary, so a
                        # doctor with two calendars at one clinic (same
                        # stable_key) keeps both rows. Fall back to stable_key
                        # only if a guid is somehow missing.
                        dkey = row.get("diary_guid") or skey
                        if dkey in seen_keys:
                            continue
                        seen_keys.add(dkey)
                        new_on_page += 1

                        rec = {
                            "scraped_at": datetime.now().isoformat(timespec="seconds"),
                            "group_code": (spec["groups"][0] if spec.get("groups") else ""),
                            "group_name": gname,
                            "spec_code": spec["code"],
                            "spec_name": spec["name"],
                            "search_city": city,
                            "include_district": not args.no_district,
                            "result_total": total,
                            "page": pno,
                            "days_until": days_until(row.get("next_available_date")),
                            "stable_key": skey,
                            **row,
                        }
                        diaries.write(rec)
                        n_rows += 1
                        harvested.append(rec)

                    # A page of pure duplicates means the pager has wrapped.
                    if new_on_page == 0:
                        stall += 1
                        if stall >= 2:
                            break
                    else:
                        stall = 0

                    if total and n_rows >= total:
                        break
                    pno += 1

                last_page = pno

                shortfall = ""
                if total and n_rows < total:
                    shortfall = f"  (MISSING {total - n_rows})"
                log(f"    {total} total, {n_rows} rows over {last_page} page(s){shortfall}")
                done.add(pair_key)
                state_path.write_text(
                    json.dumps({"done": sorted(done)}, ensure_ascii=False),
                    encoding="utf-8")

            # ---------------- Tier 2 ----------------
            if args.slots:
                targets = pick_slot_targets(harvested, args)
                log(f"\nTier 2: fetching slots for {len(targets)} diaries")
                seen = set()
                for j, rec in enumerate(targets, 1):
                    guid = rec["diary_guid"]
                    if not guid or guid in seen:
                        continue
                    seen.add(guid)
                    log(f"  [{j}/{len(targets)}] {rec['doctor_name'][:30]}")
                    vr = session.get_visit_page(guid)
                    if vr.status != 200:
                        log(f"      HTTP {vr.status}")
                        continue
                    vhtml = vr.text()
                    if session.looks_logged_out(vhtml):
                        log("      SESSION EXPIRED")
                        input("      Log in, then press Enter... ")
                        continue

                    meta = zp.parse_visit_page_meta(vhtml)
                    slots = zp.parse_slots(vhtml)
                    for s in slots:
                        slots_sink.write({
                            "scraped_at": datetime.now().isoformat(timespec="seconds"),
                            "diary_guid": guid,
                            "doctor_name": rec["doctor_name"],
                            "spec_code": rec["spec_code"],
                            "spec_name": rec["spec_name"],
                            "search_city": rec["search_city"],
                            "clinic_name": meta.get("clinic_name") or rec["clinic_name"],
                            "clinic_code": meta.get("clinic_code"),
                            **s,
                        })
                    log(f"      {len(slots)} slots; "
                        f"available days: {meta.get('available_days')}")

        except KeyboardInterrupt:
            log("\nInterrupted - progress saved.")
        finally:
            log(f"\nRequests made: {session.n_requests}")
            log(f"diaries.csv: {diaries.count} rows")
            if slots_sink:
                log(f"slots.csv:   {slots_sink.count} rows")
            diaries.close()
            facets.close()
            if slots_sink:
                slots_sink.close()
            state_path.write_text(
                json.dumps({"done": sorted(done)}, ensure_ascii=False),
                encoding="utf-8")
            log(f"Output in {OUT.resolve()}")
            ctx.close()


def pick_slot_targets(rows, args):
    """Narrow Tier 1 output down to the diaries worth a slot fetch."""
    out = rows
    if args.slots_within_days is not None:
        out = [r for r in out
               if r.get("days_until") is not None
               and 0 <= r["days_until"] <= args.slots_within_days]
    if args.slots_limit:
        out = sorted(out, key=lambda r: r.get("days_until") or 9999)
        out = out[:args.slots_limit]
    return out


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--specs", help="comma-separated specialization codes (default: all)")
    ap.add_argument("--all-specs", action="store_true", help="explicit 'all specializations'")
    ap.add_argument("--cities", help="comma-separated city names")
    ap.add_argument("--anchor-cities", action="store_true",
                    help=f"use the built-in {len(ANCHOR_CITIES)} anchor cities")
    ap.add_argument("--cities-file",
                    help="path to a newline-separated city list (e.g. data/cities.txt)")
    ap.add_argument("--no-district", action="store_true",
                    help="turn OFF 'כולל יישובים בסביבה' (many more cities needed)")
    ap.add_argument("--max-pages", type=int, default=20,
                    help="max result pages per search (default 20)")

    ap.add_argument("--slots", action="store_true", help="Tier 2: fetch time slots")
    ap.add_argument("--slots-within-days", type=int, default=None,
                    help="only fetch slots when next date is within N days")
    ap.add_argument("--slots-limit", type=int, default=None,
                    help="cap the number of diaries fetched in Tier 2")

    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds between requests (default 3)")
    ap.add_argument("--jitter", type=float, default=1.5,
                    help="extra random delay up to N seconds (default 1.5)")
    ap.add_argument("--headless", action="store_true",
                    help="run headless (login must already be valid)")
    ap.add_argument("--save-raw", action="store_true", help="keep raw HTML responses")
    ap.add_argument("--refresh-taxonomy", action="store_true")
    ap.add_argument("--skip-referral-gated", action="store_true",
                    help="skip 'נדרשת הפניה' specializations (usually return nothing)")
    ap.add_argument("--restart", action="store_true", help="ignore the resume checkpoint")
    ap.add_argument("--dry-run", action="store_true", help="one pair only, then stop")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--out", default="./data",
                    help="output directory (default ./data)")
    ap.add_argument("--profile", default="./clalit-profile",
                    help="browser profile dir (default ./clalit-profile)")
    ap.add_argument("--session",
                    help="path to a shared storage_state JSON (skips login; "
                         "run headless). Create with test_share.py / --setup.")

    args = ap.parse_args()
    crawl(args)


if __name__ == "__main__":
    main()