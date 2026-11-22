"""Check every link on the portfolio page and report the broken ones.

Why custom instead of a stock link checker: a deleted or renamed Streamlit app
does not return an error code. It redirects to share.streamlit.io/errors/not_found,
which loads normally (HTTP 200). This script follows redirects and also flags
any link that lands on that page.

Usage:  python check_links.py index.html [report.md]
Exit code 0 = all links OK, 1 = at least one broken link (report written).
Standard library only, so the workflow needs no installs.
"""

from __future__ import annotations

import re
import sys
import time
import http.cookiejar
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

TIMEOUT = 25        # seconds per request; sleeping Streamlit apps can be slow
RETRIES = 2         # transient network failures get one more try
USER_AGENT = "Mozilla/5.0 (portfolio link check; +https://github.com/MarusFaulkner)"

# Sites that refuse automated visitors (403/429/999) even when the link is fine.
# A refusal from these is "unverified", not "broken", to avoid false alarms.
BOT_BLOCKING_HOSTS = ("linkedin.com",)

# Streamlit sends visitors through a sign-in hop that sets a cookie and redirects
# back. The cookie jar below handles that. If a Streamlit link still loops for
# some other reason, report it for a hand check instead of raising a false alarm;
# a truly deleted app is still caught because it lands on the not-found page.
STREAMLIT_HOSTS = ("streamlit.app",)

# Final addresses that mean "this app does not exist" even with HTTP 200.
DEAD_ENDS = (
    re.compile(r"share\.streamlit\.io/errors/not_found"),
    re.compile(r"huggingface\.co/404"),
)


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith(("http://", "https://")):
                self.links.append(href)


def check(url: str) -> tuple[str, str]:
    """Return (status, detail). status is OK, BROKEN or UNVERIFIED."""
    last_error = ""
    for attempt in range(RETRIES):
        try:
            # Fresh cookie jar per link, like a new browser visit.
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with opener.open(req, timeout=TIMEOUT) as resp:
                final = resp.geturl()
                if any(p.search(final) for p in DEAD_ENDS):
                    return "BROKEN", f"redirects to a not-found page ({final})"
                return "OK", f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            if any(h in url for h in STREAMLIT_HOSTS) and 300 <= e.code < 400:
                return "UNVERIFIED", f"redirect loop at Streamlit sign-in (HTTP {e.code}); open it by hand"
            if any(h in url for h in BOT_BLOCKING_HOSTS) and e.code in (403, 429, 999):
                return "UNVERIFIED", f"HTTP {e.code} (site blocks automated checks)"
            if e.code in (429, 500, 502, 503, 504) and attempt + 1 < RETRIES:
                last_error = f"HTTP {e.code}"; time.sleep(5); continue
            return "BROKEN", f"HTTP {e.code}"
        except Exception as e:  # DNS failure, timeout, connection reset
            last_error = f"{type(e).__name__}: {e}"
            if attempt + 1 < RETRIES:
                time.sleep(5); continue
    return "BROKEN", last_error


def main() -> int:
    page = Path(sys.argv[1])
    report = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("link-report.md")
    parser = LinkCollector(); parser.feed(page.read_text(encoding="utf-8"))
    links = sorted(set(parser.links))

    results = [(u, *check(u)) for u in links]
    for url, status, detail in results:
        print(f"{status:10} {url}  [{detail}]")

    broken = [r for r in results if r[1] == "BROKEN"]
    unverified = [r for r in results if r[1] == "UNVERIFIED"]
    lines = [f"Checked **{len(results)}** links on `{page}`.", ""]
    if broken:
        lines += ["### Broken", "", "| Link | Problem |", "|---|---|"]
        lines += [f"| {u} | {d} |" for u, _, d in broken] + [""]
    if unverified:
        lines += ["### Could not verify automatically (check these by hand)", ""]
        lines += [f"- {u}" for u, _, _ in unverified] + [""]
    lines += ["Fix the links, then close this issue. Run the check again from the Actions tab to confirm."]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(broken)} broken, {len(unverified)} unverified, {len(results)} checked")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
