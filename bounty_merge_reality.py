#!/usr/bin/env python3
"""Does a posted GitHub bounty ever actually get MERGED? Measured, per issue.

`bounty_scan.py`, next to this file, measures the SUPPLY side of GitHub's
`💎 Bounty` label: how many open issues, how concentrated, how many are
agent-bait, and what the honest remainder is worth from its `$NNN` price labels.
On 2026-08-28 it read 560 open bounty issues, 22 priced outside the top-3
repositories, $14,933 advertised.

Nobody had measured the DEMAND side: whether anybody who does that work is paid.
This file asks that of every priced, unpaid, open row on the whole label.

WHAT IT MEASURES, per bounty:

  attempts   distinct pull requests that reference the issue number
  merged     how many of those were actually merged
  authors    distinct accounts that filed one
  oldest     the date of the first attempt

and, across the pool, the only number that matters: the merge rate, and the
dollars advertised against the dollars a contributor could actually collect.

WHY THE JOIN IS BY ISSUE NUMBER AND NOT BY GitHub's LINKED-PR FIELD. GitHub
records a formal link only when the PR body uses a closing keyword ("fixes #290")
AND the author has push access, which almost no bounty claimant does. Counting
formal links reports ~0 attempts on issues that visibly have sixty. So the join
is textual: a PR counts as an attempt when the issue number appears as a `#NNN`
token in its title or body. That over-counts an incidental mention and
under-counts a PR that names the issue only in a comment; both are small against
the effect size measured here, and every row is printed and written to the JSON
so the call can be argued with rather than taken on trust.

A ZERO MERGE RATE IS THE FINDING, NOT A BUG -- so check it the way you would
check any zero. `--control` runs the same query shape on the same repositories
with no bounty issue: do they merge anything at all? If they do, the join works.

  python3 bounty_merge_reality.py --selftest   # 16 cases, no network
  GITHUB_CLASSIC_PAT=... python3 bounty_merge_reality.py
  GITHUB_CLASSIC_PAT=... python3 bounty_merge_reality.py --control
  GITHUB_CLASSIC_PAT=... python3 bounty_merge_reality.py --json out.json

Reads only. No repository is cloned, no issue is answered, nothing is written to
GitHub. MIT licensed, same as the rest of the scripts here.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

SCAN_DIR = pathlib.Path(__file__).resolve().parent
API = "https://api.github.com/search/issues"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"


def latest_scan(d=SCAN_DIR):
    """-> path of the newest published scan next to this script, or None.

    Both spellings are accepted: `scan-YYYY-MM-DD.json` is how the scans are
    named in this repository, `bounty-scan-*.json` is what `bounty_scan.py`
    writes by default.
    """
    xs = sorted(d.glob("scan-*.json")) + sorted(d.glob("bounty-scan-*.json"))
    return sorted(xs, key=lambda p: p.name[-15:])[-1] if xs else None


def references(issue_number, title, body):
    """-> True when this PR names the issue as a `#NNN` token.

    Bounded so `#29` does not match `#290`, and so a bare `290` in prose (a port
    number, a line number, a dollar figure) is not counted as a claim.
    """
    hay = f"{title or ''}\n{body or ''}"
    return re.search(rf"#{issue_number}(?!\d)", hay) is not None


def _get(url, token, tries=3):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:                                        # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))                              # never a tight loop
    return {}


def attempts_on(repo, number, token, pages=3):
    """-> list of attempt rows (dicts) for one bounty issue."""
    out, seen = [], set()
    for page in range(1, pages + 1):
        q = urllib.parse.quote(f"repo:{repo} type:pr {number}", safe=":/")
        d = _get(f"{API}?q={q}&per_page=100&page={page}", token)
        items = d.get("items") or []
        for i in items:
            if i["number"] in seen:
                continue
            if not references(number, i.get("title"), i.get("body")):
                continue
            seen.add(i["number"])
            pr = i.get("pull_request") or {}
            out.append({"number": i["number"], "state": i["state"],
                        "merged": bool(pr.get("merged_at")),
                        "author": (i.get("user") or {}).get("login", "?"),
                        "created": (i.get("created_at") or "")[:10],
                        "title": i.get("title", "")[:70]})
        if len(items) < 100:
            break
        time.sleep(2)
    return out


def summarise(rows):
    """-> pool-level totals over a list of per-bounty result dicts."""
    att = sum(r["attempts"] for r in rows)
    mrg = sum(r["merged"] for r in rows)
    return {
        "bounties": len(rows),
        "attempts": att,
        "merged": mrg,
        "merge_rate": (mrg / att) if att else None,
        "usd_advertised": sum(r["price"] for r in rows),
        "usd_collectable": sum(r["price"] for r in rows if r["merged"]),
        "bounties_with_any_merge": sum(1 for r in rows if r["merged"]),
    }


def selftest():
    ok = fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {name}")

    # --- the reference join. These are the calls the finding rests on.
    check("plain body reference", references(290, "x", "fixes #290"))
    check("title reference", references(290, "BOUNTY: redactor (issue #290)", ""))
    check("prefix is not a match", not references(29, "t", "fixes #290"))
    check("suffix is not a match", not references(290, "t", "see #2900"))
    check("bare number is not a claim", not references(290, "port 290 is open", ""))
    check("None body is safe", references(1, "fix (#1)", None))
    check("None title is safe", references(1, None, "closes #1"))
    check("unrelated issue not counted", not references(8072, "fix #13573", ""))

    # --- the arithmetic. A zero merge rate must not become a crash or a 100%.
    rows = [{"attempts": 96, "merged": 0, "price": 50.0},
            {"attempts": 58, "merged": 0, "price": 50.0},
            {"attempts": 30, "merged": 0, "price": 200.0}]
    s = summarise(rows)
    check("attempts summed", s["attempts"] == 184)
    check("zero merges is a zero rate, not a crash", s["merge_rate"] == 0.0)
    check("advertised summed", s["usd_advertised"] == 300.0)
    check("collectable is zero when nothing merged", s["usd_collectable"] == 0.0)
    check("no bounty credited a merge", s["bounties_with_any_merge"] == 0)

    s2 = summarise([{"attempts": 4, "merged": 1, "price": 12.0}])
    check("a real merge reads through", s2["merge_rate"] == 0.25)
    check("collectable counts the paid row", s2["usd_collectable"] == 12.0)

    check("empty pool does not divide by zero", summarise([])["merge_rate"] is None)

    print(f"\n  selftest: {ok} ok / {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--control", action="store_true",
                    help="negative control: do the same repos merge NON-bounty PRs?")
    ap.add_argument("--scan", help="bounty-scan json (default: newest on disk)")
    ap.add_argument("--json", help="write the full reading here")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    token = os.environ.get("GITHUB_CLASSIC_PAT") or os.environ.get("GITHUB_PAT")
    if not token:
        print("need GITHUB_CLASSIC_PAT (a read-only token is enough)")
        return 2

    path = pathlib.Path(a.scan) if a.scan else latest_scan()
    if not path:
        print("no scan-*.json found next to this script")
        return 2
    scan = json.loads(path.read_text())
    print(f"scan: {path.name}  ({scan['total']} open bounty issues on the label)\n")

    pool = [r for r in scan["rest_priced"] if not r["rewarded"]]
    pool.sort(key=lambda r: -r["price"])

    if a.control:
        # Same repos, same query shape, NO bounty issue -- do they merge anything?
        repos = sorted({r["repo"] for r in pool})
        print("NEGATIVE CONTROL — merged PRs in the same repos, any subject:\n")
        for repo in repos:
            q = urllib.parse.quote(f"repo:{repo} type:pr is:merged", safe=":/")
            d = _get(f"{API}?q={q}&per_page=1", token)
            print(f"  {d.get('total_count', '?'):>6} merged PRs all-time   {repo}")
            time.sleep(2)
        return 0

    rows = []
    print(f"{'BOUNTY':<44} {'$':>7}  {'ATT':>4} {'MRG':>4} {'AUTH':>5}  OLDEST")
    print("-" * 84)
    for r in pool:
        try:
            at = attempts_on(r["repo"], r["number"], token)
        except Exception as exc:                                 # noqa: BLE001
            print(f"  [{r['repo']}#{r['number']} unreadable: {exc!r}]")
            continue
        merged = sum(1 for x in at if x["merged"])
        authors = len({x["author"] for x in at})
        oldest = min((x["created"] for x in at), default="-")
        rows.append({"repo": r["repo"], "number": r["number"], "price": r["price"],
                     "title": r["title"], "url": r["url"], "attempts": len(at),
                     "merged": merged, "authors": authors, "oldest": oldest,
                     "rows": at})
        tag = f"{r['repo']}#{r['number']}"
        print(f"{tag:<44} {r['price']:>7.0f}  {len(at):>4} {merged:>4} {authors:>5}  {oldest}")
        time.sleep(2)

    s = summarise(rows)
    print("\n" + "=" * 84)
    print(f"  priced open bounties measured : {s['bounties']}")
    print(f"  distinct PRs filed at them    : {s['attempts']}")
    print(f"  of those, MERGED              : {s['merged']}")
    rate = "n/a" if s["merge_rate"] is None else f"{s['merge_rate'] * 100:.1f}%"
    print(f"  MERGE RATE                    : {rate}")
    print(f"  bounties with any merge at all: {s['bounties_with_any_merge']} of {s['bounties']}")
    print(f"  USD advertised                : ${s['usd_advertised']:,.0f}")
    print(f"  USD a contributor collected   : ${s['usd_collectable']:,.0f}")
    print("=" * 84)
    print("\n  A zero here is a reading about the LABEL, not about any one repo.")
    print("  Confirm it with --control before quoting it: the same query on the")
    print("  same repos must return merged non-bounty PRs, or the join is broken.")

    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(
            {"scan": path.name, "summary": s, "bounties": rows}, indent=1))
        print(f"\n  wrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
