#!/usr/bin/env python3
"""V25 SUPPLY, MEASURED FROM BEHAVIOUR INSTEAD OF FROM MARKETING PAGES.

Four supply surfaces have been walked for V25 (agent-trap monitoring, $750/mo) and
every one came back dry: company websites, GitHub org profiles, package manifests,
and the VS Code Marketplace.  All four ask the same question -- *does this vendor
SAY it ships an agent?* -- and all four therefore find the same small set of
companies that market an agent loudly.

This asks a different question, and it is the question the SKU is actually about:
**whose agent has been observed ACTING on the GitHub bounty board?**

An account that has commented on a bounty issue is on the exact surface V25 monitors.
An account that has commented on an issue this corpus already grades `agent_targeted`
or `exfil` has been exposed to a real trap, on a real date, with a permalink -- which
is a fact about the buyer, not a claim about the product.  That is the strongest
qualification available for this offer and it cannot be reached from a marketing page.

Input is the newest `evidence/bounty-scan-*.json` (the corpus behind bounty-trap-scan).
Output is `evidence/bounty-actors-<date>.json` plus a printed table.

NOT A DOOR LIST.  This finds *accounts*, and an account is not a company and a company
is not a business door.  Mapping account -> vendor -> commercial door is a separate,
manual, evidence-carrying step; `pps.commercial()` still governs what may be written to,
and no address discovered downstream of this file may skip that screen.

    python3 scripts/agentvendor_bounty_actors.py --selftest
    python3 scripts/agentvendor_bounty_actors.py --limit 40     # cheap probe
    python3 scripts/agentvendor_bounty_actors.py               # full corpus
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVID = ROOT / "evidence"
API = "https://api.github.com"

# Accounts that are infrastructure rather than a vendor's agent working the board.
# Kept explicit: a silent "looks like CI" heuristic would drop the one row that matters.
INFRA = {
    "github-actions[bot]", "dependabot[bot]", "renovate[bot]", "codecov[bot]",
    "sonarcloud[bot]", "netlify[bot]", "vercel[bot]", "stale[bot]",
    "allcontributors[bot]", "semantic-release-bot", "imgbot[bot]",
    "pre-commit-ci[bot]", "mergify[bot]", "snyk-bot", "greenkeeper[bot]",
    "cla-bot[bot]", "dosubot[bot]", "welcome[bot]", "release-drafter[bot]",
}

# Our own account never counts as supply.
SELF = (os.environ.get("GITHUB_USER") or "sujeito-operator").lower()


def _tok() -> str:
    t = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_CLASSIC_PAT") or ""
    if not t:
        sys.exit("REFUSING: no GITHUB_PAT in the environment; source .env first.")
    return t


def _get(url: str, tok: str, tries: int = 3):
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {tok}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "bounty-actor-sweep",
    })
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and n + 1 < tries:
                time.sleep(20 * (n + 1))
                continue
            if e.code in (404, 410, 451):
                return None
            if n + 1 == tries:
                return None
        except Exception:
            if n + 1 == tries:
                return None
            time.sleep(3)
    return None


def newest_corpus() -> pathlib.Path:
    """The newest census, wherever it lives.

    Two layouts on purpose. In this repository the censuses are
    `evidence/bounty-scan-<date>.json`; in the PUBLISHED `bounty-trap-scan` repository
    the same files sit beside this script as `scan-<date>.json`. This file is copied
    into that repository verbatim so the letter's promise -- *you can reproduce every
    number above yourself* -- is true of the exact code that produced them, rather than
    of a re-typed cousin of it.
    """
    here = pathlib.Path(__file__).resolve().parent
    for d, pat in ((EVID, "bounty-scan-*.json"), (here, "scan-*.json"),
                   (here.parent, "scan-*.json")):
        cands = sorted(p for p in d.glob(pat) if re.search(r"\d{4}-\d{2}-\d{2}", p.name))
        if cands:
            return cands[-1]
    sys.exit("REFUSING: no bounty-scan-<date>.json / scan-<date>.json to read.")


def is_agentish(login: str) -> bool:
    """A bot that is plausibly a vendor's coding agent rather than repo plumbing."""
    lo = login.lower()
    if lo in INFRA or lo == SELF:
        return False
    return lo.endswith("[bot]") or bool(re.search(
        r"(agent|devin|sweep|codegen|autofix|copilot|coder|swe|ai-?bot|llm|mentat|"
        r"cosine|factory|tusk|greptile|codium|qodo|ellipsis|sourcery|cubic)", lo))


def sweep(rows, tok, limit=None, sleep=0.0, log=print):
    """Return {login: record} over the issue comments of `rows`."""
    actors: dict[str, dict] = {}
    todo = rows if limit is None else rows[:limit]
    for i, row in enumerate(todo, 1):
        url = f"{API}/repos/{row['repo']}/issues/{row['number']}/comments?per_page=100"
        comments = _get(url, tok)
        if comments is None:
            continue
        for c in comments:
            u = (c.get("user") or {})
            login = u.get("login") or ""
            if not login or login.lower() == SELF or login.lower() in INFRA:
                continue
            rec = actors.setdefault(login, {
                "login": login,
                "type": u.get("type"),
                "agentish": is_agentish(login),
                "issues": 0, "repos": set(),
                "trap_hits": [],      # comments on issues this corpus grades as traps
                "sample": None,
            })
            rec["issues"] += 1
            rec["repos"].add(row["repo"])
            if rec["sample"] is None:
                rec["sample"] = c.get("html_url")
            if row.get("agent_targeted") or row.get("exfil"):
                rec["trap_hits"].append({
                    "issue": row["url"],
                    "comment": c.get("html_url"),
                    "at": (c.get("created_at") or "")[:10],
                    "exfil": bool(row.get("exfil")),
                })
        if sleep:
            time.sleep(sleep)
        if i % 25 == 0:
            log(f"  ... {i}/{len(todo)} issues read, {len(actors)} distinct actors")
    for rec in actors.values():
        rec["repos"] = sorted(rec["repos"])
    return actors


def aggregate(actors: dict, corpus: dict, issues_read: int) -> dict:
    """-> the PUBLISHABLE reading: counts only, and not one account name.

    `bounty-trap-scan`'s README already draws this line for the compliance half --
    *"a list of who complied is a list of people who have already been caught by this,
    and republishing it moves the harm onto them a second time."*  This measurement is
    the same shape and gets the same treatment: the repository gets the tool and the
    aggregates, and the logins stay on this box.  The local evidence file keeps them
    because deciding whether a vendor is a prospect needs them; nothing published does.
    """
    tainted = set(corpus.get("tainted_owners") or [])
    rows = list(actors.values())
    exposed = [r for r in rows if r["trap_hits"]]
    outside = [r for r in exposed
               if any(h["issue"].split("/")[3] not in tainted for h in r["trap_hits"])]
    return {
        "measured": str(dt.date.today()),
        "corpus_issues": issues_read,
        "corpus_repos": corpus.get("repos"),
        "tainted_owners": sorted(tainted),
        "distinct_accounts": len(rows),
        "accounts_on_an_asking_issue": len(exposed),
        "accounts_on_an_asking_issue_from_outside_those_owners": len(outside),
        "accounts_shaped_like_a_vendor_agent": sum(1 for r in rows if r["agentish"]),
        "note": ("Counts only. No account name appears in this file, for the reason the "
                 "README gives for the compliance data: a list of accounts caught by "
                 "this is a second harm to the same people. Re-run bounty_actors.py "
                 "against the published scan to derive it yourself."),
        "floor_not_total": ("An agent can read an asking issue, be caught by it, and "
                            "never leave a comment. This counts comments, so it is a "
                            "lower bound on exposure and not a measure of it."),
    }


def selftest() -> int:
    ok = fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {name}")

    check("infra bots are not agentish", not any(is_agentish(b) for b in INFRA))
    check("our own account is never agentish", not is_agentish(SELF))
    check("a plain human login is not agentish", not is_agentish("torvalds"))
    check("an unknown [bot] IS agentish", is_agentish("acme-swe[bot]"))
    check("devin is agentish", is_agentish("devin-ai-integration[bot]"))
    check("greptile is agentish", is_agentish("greptile-apps[bot]"))
    check("case does not matter", is_agentish("Sweep-AI"))
    check("corpus exists", newest_corpus().exists())

    corpus = json.loads(newest_corpus().read_text())
    check("corpus has rows", len(corpus.get("rows", [])) > 0)
    check("rows carry repo/number/url",
          all({"repo", "number", "url"} <= set(r) for r in corpus["rows"][:50]))
    check("corpus grades traps", any(r.get("agent_targeted") for r in corpus["rows"]))

    # sweep() must survive a dead API without inventing actors
    saved = globals()["_get"]
    globals()["_get"] = lambda *a, **k: None
    try:
        check("no API means no actors",
              sweep(corpus["rows"][:3], "x", log=lambda *_: None) == {})
    finally:
        globals()["_get"] = saved

    # a trap row must produce a trap_hit; a clean row must not
    globals()["_get"] = lambda *a, **k: [
        {"user": {"login": "acme-swe[bot]", "type": "Bot"},
         "html_url": "https://example/c1", "created_at": "2026-08-01T00:00:00Z"}]
    try:
        trap = [{"repo": "a/b", "number": 1, "url": "u", "agent_targeted": True}]
        clean = [{"repo": "a/b", "number": 1, "url": "u", "agent_targeted": False}]
        t = sweep(trap, "x", log=lambda *_: None)
        c = sweep(clean, "x", log=lambda *_: None)
        check("a trap row records a trap hit", len(t["acme-swe[bot]"]["trap_hits"]) == 1)
        check("a clean row records none", c["acme-swe[bot]"]["trap_hits"] == [])
        check("self and infra are filtered before counting",
              sweep([{"repo": "a/b", "number": 1, "url": "u"}], "x",
                    log=lambda *_: None).keys() == {"acme-swe[bot]"})
    finally:
        globals()["_get"] = saved

    globals()["_get"] = lambda *a, **k: [
        {"user": {"login": SELF, "type": "User"}, "html_url": "x", "created_at": ""},
        {"user": {"login": "github-actions[bot]", "type": "Bot"},
         "html_url": "x", "created_at": ""}]
    try:
        check("a page of only self+infra yields nothing",
              sweep([{"repo": "a/b", "number": 1, "url": "u"}], "x",
                    log=lambda *_: None) == {})
    finally:
        globals()["_get"] = saved

    # The published artifact must never carry an account name. Feed it a corpus and a
    # set of actors whose logins are distinctive strings, then assert none survives.
    fake = {
        "spamfarm-account": {"login": "spamfarm-account", "type": "User", "agentish": False,
                             "issues": 3, "repos": ["Tainted/x"], "sample": None,
                             "trap_hits": [{"issue": "https://github.com/Tainted/x/issues/1",
                                            "comment": "c", "at": "2026-01-01",
                                            "exfil": True}]},
        "outsider-account": {"login": "outsider-account", "type": "Bot", "agentish": True,
                             "issues": 1, "repos": ["Clean/y"], "sample": None,
                             "trap_hits": [{"issue": "https://github.com/Clean/y/issues/2",
                                            "comment": "c", "at": "2026-01-02",
                                            "exfil": False}]},
        "bystander-account": {"login": "bystander-account", "type": "User",
                              "agentish": False, "issues": 1, "repos": ["Clean/y"],
                              "sample": None, "trap_hits": []},
    }
    agg = aggregate(fake, {"tainted_owners": ["Tainted"], "repos": 2}, 9)
    blob = json.dumps(agg)
    check("the published aggregate names no account",
          not any(k in blob for k in fake))
    check("it counts every distinct account", agg["distinct_accounts"] == 3)
    check("it counts only accounts seen on an asking issue",
          agg["accounts_on_an_asking_issue"] == 2)
    check("it separates the ones from outside the tainted owners",
          agg["accounts_on_an_asking_issue_from_outside_those_owners"] == 1)
    check("it counts agent-shaped accounts",
          agg["accounts_shaped_like_a_vendor_agent"] == 1)
    check("outside can never exceed exposed",
          agg["accounts_on_an_asking_issue_from_outside_those_owners"]
          <= agg["accounts_on_an_asking_issue"])
    check("it says out loud that it is a floor", "floor_not_total" in agg)
    agg0 = aggregate(fake, {"tainted_owners": ["Tainted", "Clean"], "repos": 2}, 9)
    check("widening the tainted set drives outside to zero",
          agg0["accounts_on_an_asking_issue_from_outside_those_owners"] == 0)

    print(f"{ok} ok / {fail} failed")
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    tok = _tok()
    corpus_path = newest_corpus()
    corpus = json.loads(corpus_path.read_text())
    rows = corpus["rows"]
    print(f"corpus {corpus_path.name}: {len(rows)} bounty issues, "
          f"{corpus.get('agent_targeted_n')} graded agent-targeted, "
          f"{corpus.get('exfil_n')} exfil")

    actors = sweep(rows, tok, limit=a.limit, sleep=a.sleep)

    ranked = sorted(actors.values(),
                    key=lambda r: (len(r["trap_hits"]), r["agentish"], r["issues"]),
                    reverse=True)
    agentish = [r for r in ranked if r["agentish"]]
    exposed = [r for r in ranked if r["trap_hits"]]

    print(f"\n{len(actors)} distinct non-infra actors on the board; "
          f"{len(agentish)} look like a vendor agent; "
          f"{len(exposed)} commented on an issue this corpus grades a trap")

    if agentish:
        print("\nAGENT-SHAPED ACTORS (candidate V25 vendors — NOT yet doors):")
        print(f"  {'login':38} {'type':6} {'iss':>4} {'repos':>5} {'traps':>5}")
        for r in agentish[:40]:
            print(f"  {r['login']:38} {str(r['type']):6} {r['issues']:>4} "
                  f"{len(r['repos']):>5} {len(r['trap_hits']):>5}")
    else:
        print("\nNo agent-shaped actor commented anywhere on this corpus. "
              "That is a negative result and it is the honest one: the bounty board "
              "this SKU monitors has no observable vendor agent working it.")

    if exposed:
        print("\nEXPOSED — commented on a trap issue (the qualification that matters):")
        for r in exposed[:20]:
            h = r["trap_hits"][0]
            print(f"  {r['login']:38} {len(r['trap_hits'])} hit(s), first {h['at']}")
            print(f"      issue   {h['issue']}")
            print(f"      comment {h['comment']}")

    issues_read = len(rows) if a.limit is None else min(a.limit, len(rows))
    outdir = EVID if EVID.is_dir() else corpus_path.parent
    out = outdir / f"bounty-actors-{dt.date.today()}.json"
    out.write_text(json.dumps({
        "corpus": corpus_path.name,
        "issues_read": issues_read,
        "actors": len(actors),
        "agentish": [r["login"] for r in agentish],
        "exposed": [r["login"] for r in exposed],
        "rows": ranked,
    }, indent=1, default=str))
    print(f"\nwrote {out}")

    pub = outdir / f"bounty-actors-public-{dt.date.today()}.json"
    pub.write_text(json.dumps(aggregate(actors, corpus, issues_read), indent=1))
    print(f"wrote {pub}  (aggregates only — safe to publish)")
    print("\nA login is not a company and a company is not a door. Any address that "
          "comes out of this must still pass pps.commercial() before anything is sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
