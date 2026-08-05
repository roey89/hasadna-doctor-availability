#!/usr/bin/env python3
"""
Clalit scraper - first pass.

Usage:
    python3 clalit_scrape.py

First run: a browser window opens. Log in by hand (ID, user code, password,
CAPTCHA, SMS code). Then press Enter in the terminal.
Later runs: your session is reused from ./clalit-profile, so it goes straight
to the page. If the session has expired you'll be asked to log in again.

Outputs into ./data/raw/clalit/output/ :
    page.html   - full HTML of the page, for inspecting selectors later
    page.txt    - visible text
    tables.csv  - any HTML tables found
    api_log.txt - JSON/XHR endpoints the page called (READ THIS ONE)
"""

import csv
import json
import pathlib
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://e-services.clalit.co.il/OnlineWeb/Services/Tamuz/TamuzTransfer.aspx"
PROFILE_DIR = "./data/raw/clalit/clalit-profile"   # session cookies persist here
OUT = pathlib.Path("./data/raw/clalit/output")


def main():
    OUT.mkdir(exist_ok=True)
    api_calls = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            viewport={"width": 1400, "height": 900},
            locale="he-IL",
        )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Log every JSON response the site makes. These endpoints are usually
        # far easier to work with than scraping the rendered HTML.
        def on_response(resp):
            ctype = (resp.headers.get("content-type") or "").lower()
            if "json" in ctype:
                api_calls.append(f"{resp.status}  {resp.request.method}  {resp.url}")

        page.on("response", on_response)

        print(f"\nOpening {URL}")
        page.goto(URL, wait_until="domcontentloaded")

        # Are we logged in? The login redirect is the reliable signal.
        if "Login.aspx" in page.url or "login.aspx" in page.url.lower():
            print("\n" + "=" * 60)
            print("NOT LOGGED IN.")
            print("Log in in the browser window that just opened:")
            print("  ID number -> user code -> password -> CAPTCHA -> SMS code")
            print("Once you can see your records, come back here.")
            print("=" * 60)
            input("\nPress Enter when you are logged in... ")
            page.goto(URL, wait_until="domcontentloaded")

            if "login" in page.url.lower():
                print("\nStill on the login page. Nothing was saved.")
                print("Re-run the script and complete the login before pressing Enter.")
                ctx.close()
                sys.exit(1)
        else:
            print("Existing session reused - already logged in.")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            print("(page still chattering after 15s, continuing anyway)")

        print(f"Landed on: {page.url}")

        # --- save raw page ---
        (OUT / "page.html").write_text(page.content(), encoding="utf-8")
        (OUT / "page.txt").write_text(page.inner_text("body"), encoding="utf-8")

        # --- pull any tables ---
        rows_written = 0
        with open(OUT / "tables.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            for t_idx, table in enumerate(page.query_selector_all("table")):
                trs = table.query_selector_all("tr")
                if len(trs) < 2:
                    continue
                w.writerow([f"--- table {t_idx} ---"])
                for tr in trs:
                    cells = tr.query_selector_all("th, td")
                    vals = [c.inner_text().strip() for c in cells]
                    if any(vals):
                        w.writerow(vals)
                        rows_written += 1
                w.writerow([])

        # --- save the API log ---
        (OUT / "api_log.txt").write_text(
            "\n".join(api_calls) if api_calls else "(no JSON responses seen)",
            encoding="utf-8",
        )

        print("\n" + "-" * 60)
        print(f"Saved to {OUT.resolve()}")
        print(f"  page.html    ({len(page.content()):,} bytes)")
        print(f"  tables.csv   ({rows_written} rows)")
        print(f"  api_log.txt  ({len(api_calls)} JSON calls seen)")
        print("-" * 60)

        if api_calls:
            print("\nJSON endpoints found - these are your best target:")
            for c in api_calls[:15]:
                print("  " + c)

        print("\nBrowser stays open so you can click around and find more data.")
        print("Navigate to the section you actually want, then press Enter to")
        print("re-capture that page and log its API calls.")
        input()

        # second capture, wherever the user navigated to
        (OUT / "page2.html").write_text(page.content(), encoding="utf-8")
        (OUT / "page2.txt").write_text(page.inner_text("body"), encoding="utf-8")
        (OUT / "api_log.txt").write_text("\n".join(api_calls), encoding="utf-8")
        print(f"Second capture saved. Final URL: {page.url}")
        print(f"Total JSON calls logged: {len(api_calls)}")

        ctx.close()


if __name__ == "__main__":
    main()