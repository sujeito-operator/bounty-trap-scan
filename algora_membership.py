#!/usr/bin/env python3
"""Which owners in the bounty scan actually have an Algora profile?

    python3 scripts/algora_membership.py --selftest      # no network
    python3 scripts/algora_membership.py                 # probes algora.io, writes evidence

WHY THIS EXISTS, AND IT IS A CORRECTION TO OUR OWN PUBLISHED CLAIM.

`bounty-trap-scan`'s README, the vendor pitch and the press pitch all say the corpus is
"every open issue carrying Algora's `Bounty` label". That sentence has a hole in it that
nobody checked for three days: **a GitHub label is per-repository.** Anybody can create a
label called `Bounty` with the same emoji in their own repo and never touch Algora. The
scan's query matches the LABEL TEXT. It has never matched a platform.

So "Algora's board" was an inference, not a measurement, and it names a real company
next to a corpus about prompt exfiltration. That is the one kind of error worth stopping
a session for: every other stale figure in this operation's history was about us.

THE INSTRUMENT. `https://algora.io/<owner>` — 200 if the org has a profile, 404 if not.
Rendered client-side, so the owner's name never appears in the HTML and only the STATUS
is readable. That is enough for the one bit we need, and it is all this claims to read.

IT IS CONTROL-TESTED BOTH WAYS BEFORE ANY NEGATIVE IS BELIEVED, per next.md §L-4 — an
absence measured with the wrong instrument is not an absence, and a negative sweep is
exactly the shape of result that never announces its own failure. `--selftest` proves the
classifier; the live run refuses to write a result at all unless the positive controls
come back 200 AND the negative controls come back 404 in the same pass.

WHAT A 404 DOES AND DOES NOT MEAN. It means: this owner has no public Algora profile at
this path, today. It does NOT mean the owner never used Algora, and it does not say who
is behind the repository. The scan already carries that caveat about names and it applies
here unchanged. This measures ATTRIBUTION OF OUR OWN SENTENCE, not culpability.
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "algora-membership-2026-08-10.json"
BASE = "https://algora.io/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/127.0 Safari/537.36")

# CONTROLS. Positives are owners seen on Algora's own site; negatives are strings that
# cannot be anybody. If a positive 404s the instrument is blocked; if a negative 200s the
# route answers 200 for everything and every "member" reading is worthless.
POS_CONTROLS = ("triggerdotdev", "go-gitea")
# TWO KINDS OF NEGATIVE, AND THE SECOND KIND WAS MISSING UNTIL 2026-08-26 (§WR).
# The first two are strings that cannot be anybody. They prove the route 404s for
# GARBAGE — which is a weaker claim than the one this instrument makes. If Algora
# provisioned a page for every real GitHub org it had ever imported, nonsense strings
# would still 404 and every real owner would read `member`, and the guard would not
# notice. The named orgs below are large, real, and certainly not Algora customers;
# they are the control that actually bites. Measured 2026-08-26: all seven 404.
# This is what §UB-0c claimed was impossible. It was wrong — see the note in main().
NEG_CONTROLS = ("zzz-not-a-real-org-97531", "qqq-control-46802",
                "microsoft", "facebook", "torvalds", "apache",
                "rust-lang", "angular", "numpy")

MEMBER, ABSENT, UNREADABLE = "member", "absent", "unreadable"


def classify(status):
    """Status -> verdict. The whole judgement, in one place, so it can be tested."""
    if status == 200:
        return MEMBER
    if status == 404:
        return ABSENT
    return UNREADABLE


def probe(owner, opener=None, pause=0.4):
    """-> (verdict, status). Never raises; an unreadable owner is a result, not a crash."""
    req = urllib.request.Request(BASE + owner, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = None
    time.sleep(pause)
    return classify(status), status


def owners(scan):
    """Distinct repo owners in the scan, with issue and exfil counts for each."""
    agg = {}
    for row in scan["rows"]:
        owner = row["repo"].split("/", 1)[0]
        a = agg.setdefault(owner, {"owner": owner, "issues": 0, "exfil": 0, "repos": set()})
        a["issues"] += 1
        a["exfil"] += 1 if row.get("exfil") else 0
        a["repos"].add(row["repo"])
    for a in agg.values():
        a["repos"] = sorted(a["repos"])
    return sorted(agg.values(), key=lambda a: (-a["exfil"], -a["issues"], a["owner"]))


def controls_ok(results):
    """Both directions, in the same pass, or the run is refused."""
    bad = []
    for c in POS_CONTROLS:
        if results.get(c, (None,))[0] != MEMBER:
            bad.append(f"positive control {c} did not read 200 — the instrument is blocked")
    for c in NEG_CONTROLS:
        if results.get(c, (None,))[0] != ABSENT:
            bad.append(f"negative control {c} did not read 404 — the route answers 200 "
                       "for everything and no 'member' reading means anything")
    return bad


def selftest():
    ok = fail = 0

    def chk(name, cond):
        nonlocal ok, fail
        print(("  ok    " if cond else "  FAIL  ") + name)
        globals()  # noqa
        return cond

    def run(name, cond):
        nonlocal ok, fail
        if chk(name, cond):
            ok += 1
        else:
            fail += 1

    run("200 is a member", classify(200) == MEMBER)
    run("404 is absent", classify(404) == ABSENT)
    # Everything else is UNREADABLE rather than absent. A 403, a 429 or a timeout is the
    # instrument failing, and calling that "not on Algora" is the §L-4 defect exactly.
    run("403 is UNREADABLE, not absent", classify(403) == UNREADABLE)
    run("429 is UNREADABLE, not absent", classify(429) == UNREADABLE)
    run("530 is UNREADABLE, not absent", classify(530) == UNREADABLE)
    run("a timeout (None) is UNREADABLE, not absent", classify(None) == UNREADABLE)

    # The control gate must BITE in both directions, or it is decoration.
    good = {c: (MEMBER, 200) for c in POS_CONTROLS}
    good.update({c: (ABSENT, 404) for c in NEG_CONTROLS})
    run("a clean control pass is accepted", controls_ok(good) == [])

    blocked = dict(good)
    blocked[POS_CONTROLS[0]] = (ABSENT, 404)
    run("A BLOCKED INSTRUMENT IS REFUSED (positive control 404s)",
        any("instrument is blocked" in b for b in controls_ok(blocked)))

    catchall = dict(good)
    catchall[NEG_CONTROLS[0]] = (MEMBER, 200)
    run("A 200-FOR-EVERYTHING ROUTE IS REFUSED (negative control 200s)",
        any("answers 200 for everything" in b for b in controls_ok(catchall)))

    run("missing controls are refused, not silently passed", controls_ok({}) != [])

    # The aggregator, against a fixture whose answer is countable by hand.
    fixture = {"rows": [
        {"repo": "a/one", "exfil": True}, {"repo": "a/two", "exfil": False},
        {"repo": "b/one", "exfil": False},
    ]}
    o = owners(fixture)
    run("owners are distinct and counted", [x["owner"] for x in o] == ["a", "b"])
    run("issues are summed per owner", o[0]["issues"] == 2 and o[1]["issues"] == 1)
    run("exfil is summed per owner", o[0]["exfil"] == 1 and o[1]["exfil"] == 0)
    run("owners are ranked by exfil first", o[0]["owner"] == "a")
    run("repos are deduplicated per owner", o[0]["repos"] == ["a/one", "a/two"])

    print(f"\nalgora_membership selftest: {ok} passed, {fail} failed")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default=str(ROOT / "scan-2026-08-09.json"),
                    help="scan JSON with a 'rows' list (the published scan file)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    scan = json.load(open(a.scan))
    agg = owners(scan)
    print(f"{len(agg)} distinct owners across {scan['total']} issues "
          f"in {scan['repos']} repositories\n")

    results = {}
    # CONTROLS FIRST AND CONTROLS AGAIN. Interleaving them would be better still; running
    # them at both ends catches an instrument that degrades partway through a long sweep,
    # which is the failure a single up-front control cannot see.
    for c in POS_CONTROLS + NEG_CONTROLS:
        results[c] = probe(c)
    bad = controls_ok(results)
    if bad:
        raise SystemExit("CONTROLS FAILED, refusing to record anything: " + "; ".join(bad))
    print(f"controls ok before the sweep: {[(c, results[c]) for c in results]}\n")

    for entry in agg:
        verdict, status = probe(entry["owner"])
        entry["algora"] = verdict
        entry["status"] = status
        flag = "" if verdict == MEMBER else ("   <-- " + verdict.upper())
        print(f"  {entry['owner']:<28} {str(status):<5} {verdict:<10} "
              f"issues={entry['issues']:<4} exfil={entry['exfil']}{flag}")

    after = {c: probe(c) for c in POS_CONTROLS + NEG_CONTROLS}
    bad = controls_ok(after)
    if bad:
        raise SystemExit("CONTROLS FAILED AFTER THE SWEEP, refusing to record it: "
                         + "; ".join(bad))

    tot = {v: sum(1 for e in agg if e["algora"] == v) for v in (MEMBER, ABSENT, UNREADABLE)}
    iss = {v: sum(e["issues"] for e in agg if e["algora"] == v) for v in tot}
    exf = {v: sum(e["exfil"] for e in agg if e["algora"] == v) for v in tot}
    print(f"\nowners:  {tot}")
    print(f"issues:  {iss}")
    print(f"exfil:   {exf}")

    # THE DATE AND THE PATH ARE DERIVED, NOT TYPED (§WR, 2026-08-26).
    # Both were hardcoded to 2026-08-10. A re-run therefore did two silent things at
    # once: it stamped TODAY's sweep with the ORIGINAL date, and it overwrote the
    # original evidence file with it. The 08-10 reading is the basis of a published
    # correction naming a real company, so losing it is not a cosmetic loss — and a
    # backdated re-run is indistinguishable from the reading it destroyed. Refuse to
    # clobber a different day's record rather than trusting the next caller to notice.
    today = dt.date.today().isoformat()
    out = OUT.parent / f"algora-membership-{today}.json"
    if out.exists():
        prior = json.loads(out.read_text()).get("measured")
        if prior and prior != today:
            raise SystemExit(f"{out.name} already holds a sweep measured {prior}. Refusing.")
    out.write_text(json.dumps({
        "measured": today,
        "instrument": BASE + "<owner>",
        "census": a.scan,
        "note": "200=profile exists, 404=no public profile at this path today. "
                "Client-rendered, so only the status is readable. This measures whether "
                "OUR sentence attributing the corpus to Algora is accurate; it says "
                "nothing about who is behind any repository.",
        "controls_before": {c: results[c] for c in POS_CONTROLS + NEG_CONTROLS},
        "controls_after": {c: after[c] for c in POS_CONTROLS + NEG_CONTROLS},
        "owner_totals": tot, "issue_totals": iss, "exfil_totals": exf,
        "owners": agg,
    }, indent=1))
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
