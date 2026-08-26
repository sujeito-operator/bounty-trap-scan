#!/usr/bin/env python3
"""Diff two `bounty_scan.py --json` runs and say what actually changed.

WHY THIS EXISTS, AND WHY IT IS PUBLISHED RATHER THAN KEPT. `bounty_scan.py` produces a
photograph. The interesting question about a hazard is not "how many are there today" but
"is this the same hazard as last month, or a new one" -- and a count cannot answer that.
Two runs can hold the same total while every row underneath has been replaced, and a
falling total can hide a growing trap. So this compares the *sets of issues*, by
`(repo, number)` identity, not the summary figures.

It exists because the operation selling a monthly re-scan owed its readers the tool that
checks its own claim. On 2026-08-26 that check came back against the claim: across three
runs and seventeen days, the exfiltration set and the agent-targeted set were identical.
That answer is published in the README with the same weight it would have had if it had
gone the other way.

WHAT IT REPORTS.
  1. the headline figures side by side, with deltas
  2. set-identity for the two populations that matter: exfil, and agent-targeted
     -- ADDED and REMOVED by `(repo, number)`, not by count
  3. board churn: every issue that joined or left, so a stable count built out of
     wholesale replacement cannot read as "nothing happened"
  4. repos that appeared or disappeared from the exfil set

EXIT CODES. 0 = ran. 2 = a file was unreadable or was not a scan JSON. There is
deliberately no "changed = nonzero" code: whether a change is bad is the reader's call,
not this script's.

  python3 bounty_diff.py --selftest                  # no network, no files
  python3 bounty_diff.py OLD.json NEW.json
  python3 bounty_diff.py OLD.json NEW.json --json d.json
"""
import argparse
import json
import pathlib
import sys

# The summary keys worth a side-by-side. Every one of these is produced by
# `bounty_scan.analyse`. A key missing from a file is reported as "-" rather than
# crashing, because an older scan predates later keys and is still worth diffing.
HEADLINE = [
    ('total', 'open issues carrying the label'),
    ('repos', 'distinct repositories'),
    ('agent_targeted_n', 'labelled for agents only'),
    ('exfil_n', 'asking for the agent\'s own prompt'),
    ('rest_n', 'the honest remainder'),
    ('rest_repos', 'repositories in the remainder'),
]


def key(row):
    """Identity of an issue. `number` is per-repo, so the repo is part of the key.

    Deliberately NOT the URL: a repository rename changes every URL while the issues
    underneath are the same issues, and a diff that reports 563 removals and 563
    additions because an owner renamed itself is worse than useless.
    """
    return (row['repo'], row['number'])


DATE_RE = __import__('re').compile(r'(\d{4}-\d{2}-\d{2})')


def load(path):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise SystemExit(f'{path}: not readable as JSON ({exc})')
    if not isinstance(data, dict) or 'rows' not in data:
        raise SystemExit(f'{path}: not a bounty_scan --json file (no "rows")')
    # `bounty_scan.analyse` does not stamp a date into the payload -- the date lives in
    # the FILENAME the run was written to. Read it from there rather than printing
    # "None", and label it as derived so nobody later quotes it as if the scanner
    # asserted it. If the name carries no date, say so instead of inventing one.
    if not data.get('date'):
        m = DATE_RE.search(pathlib.Path(path).name)
        data['date'] = m.group(1) if m else f'(undated: {pathlib.Path(path).name})'
    return data


def populations(data):
    """-> (all, exfil, agent_targeted) as sets of keys.

    A row missing the boolean is treated as False rather than skipped: an older scan
    that never classified is honestly reported as "none found", and the ADDED list then
    shows the whole population, which is the truthful reading of comparing against a
    file that did not measure it.
    """
    rows = data['rows']
    return (
        {key(r) for r in rows},
        {key(r) for r in rows if r.get('exfil')},
        {key(r) for r in rows if r.get('agent_targeted')},
    )


def exfil_repo_counts(data):
    out = {}
    for r in data['rows']:
        if r.get('exfil'):
            out[r['repo']] = out.get(r['repo'], 0) + 1
    return out


def diff(old, new):
    a_all, a_exf, a_agt = populations(old)
    b_all, b_exf, b_agt = populations(new)
    return {
        'old_date': old.get('date'), 'new_date': new.get('date'),
        'headline': [
            {'key': k, 'label': lbl, 'old': old.get(k), 'new': new.get(k)}
            for k, lbl in HEADLINE
        ],
        'exfil': {
            'added': sorted(b_exf - a_exf), 'removed': sorted(a_exf - b_exf),
            'stable': len(a_exf & b_exf), 'identical': a_exf == b_exf,
        },
        'agent_targeted': {
            'added': sorted(b_agt - a_agt), 'removed': sorted(a_agt - b_agt),
            'stable': len(a_agt & b_agt), 'identical': a_agt == b_agt,
        },
        'board': {
            'joined': sorted(b_all - a_all), 'left': sorted(a_all - b_all),
            'stable': len(a_all & b_all),
        },
        'exfil_repos': {'old': exfil_repo_counts(old), 'new': exfil_repo_counts(new)},
    }


def _fmt_keys(keys, limit=40):
    if not keys:
        return ['    (none)']
    out = [f'    {repo}#{num}' for repo, num in keys[:limit]]
    if len(keys) > limit:
        out.append(f'    ... and {len(keys) - limit} more')
    return out


def render(d):
    L = []
    L.append(f"BOUNTY BOARD DIFF   {d['old_date']}  ->  {d['new_date']}")
    L.append('')
    L.append(f"  {'':46} {'old':>8} {'new':>8} {'delta':>8}")
    for h in d['headline']:
        o, n = h['old'], h['new']
        if isinstance(o, (int, float)) and isinstance(n, (int, float)):
            delta = f'{n - o:+g}'
        else:
            delta = '-'
        L.append(f"  {h['label']:46} {str(o) if o is not None else '-':>8} "
                 f"{str(n) if n is not None else '-':>8} {delta:>8}")
    L.append('')

    for name, title in (('exfil', 'ASKS FOR THE AGENT\'S OWN SYSTEM PROMPT'),
                        ('agent_targeted', 'LABELLED FOR AUTONOMOUS AGENTS ONLY')):
        s = d[name]
        L.append(f'  {title}')
        if s['identical'] and s['stable'] == 0:
            # An empty population is trivially "identical" to another empty one and must
            # NOT be dressed up as a stability finding -- that would let a scan that
            # measured nothing read as a scan that measured no change.
            L.append('    EMPTY IN BOTH RUNS — nothing to compare.')
        elif s['identical']:
            L.append(f'    IDENTICAL SET — {s["stable"]} issues, none added, none removed.')
            L.append('    The count did not merely hold; it is the same issues.')
        else:
            L.append(f'    stable {s["stable"]}   added {len(s["added"])}   '
                     f'removed {len(s["removed"])}')
            L.append('    ADDED:')
            L.extend(_fmt_keys(s['added']))
            L.append('    REMOVED:')
            L.extend(_fmt_keys(s['removed']))
        L.append('')

    b = d['board']
    L.append(f"  WHOLE BOARD   stable {b['stable']}   joined {len(b['joined'])}   "
             f"left {len(b['left'])}")
    L.append('    JOINED:')
    L.extend(_fmt_keys(b['joined']))
    L.append('    LEFT:')
    L.extend(_fmt_keys(b['left']))
    L.append('')

    old_r, new_r = d['exfil_repos']['old'], d['exfil_repos']['new']
    L.append('  REPOSITORIES HOLDING THE ASKING ISSUES')
    for repo in sorted(set(old_r) | set(new_r)):
        o, n = old_r.get(repo, 0), new_r.get(repo, 0)
        mark = '' if o == n else '   <-- CHANGED'
        L.append(f'    {repo:44} {o:>4} -> {n:<4}{mark}')
    return '\n'.join(L)


# ---------------------------------------------------------------- selftest
def _scan(date, rows, **extra):
    d = {'date': date, 'rows': rows, 'total': len(rows),
         'exfil_n': sum(1 for r in rows if r.get('exfil')),
         'agent_targeted_n': sum(1 for r in rows if r.get('agent_targeted')),
         'repos': len({r['repo'] for r in rows})}
    d.update(extra)
    return d


def _row(repo, num, exfil=False, agent=False):
    return {'repo': repo, 'number': num, 'exfil': exfil, 'agent_targeted': agent,
            'url': f'https://github.com/{repo}/issues/{num}', 'title': 't',
            'updated': '', 'price': None}


def selftest():
    ok = fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
        else:
            fail += 1
            print(f'  FAIL  {name}')

    a = _scan('2026-01-01', [_row('o/r', 1, exfil=True), _row('o/r', 2)])
    b = _scan('2026-02-01', [_row('o/r', 1, exfil=True), _row('o/r', 2)])
    d = diff(a, b)
    check('identical exfil set is reported identical', d['exfil']['identical'])
    check('identical set counts as stable', d['exfil']['stable'] == 1)
    check('no board churn when nothing moved', not d['board']['joined']
          and not d['board']['left'])

    # THE CASE THIS SCRIPT EXISTS FOR: the count holds while every row is replaced.
    a = _scan('2026-01-01', [_row('o/r', 1, exfil=True), _row('o/r', 2, exfil=True)])
    b = _scan('2026-02-01', [_row('o/r', 8, exfil=True), _row('o/r', 9, exfil=True)])
    d = diff(a, b)
    check('equal counts do NOT read as identical', not d['exfil']['identical'])
    check('wholesale replacement shows 2 added', len(d['exfil']['added']) == 2)
    check('wholesale replacement shows 2 removed', len(d['exfil']['removed']) == 2)
    check('replacement leaves 0 stable', d['exfil']['stable'] == 0)
    check('headline delta is 0 while the set turned over',
          [h for h in d['headline'] if h['key'] == 'exfil_n'][0]['old'] == 2)

    # A FALLING TOTAL HIDING A GROWING TRAP.
    a = _scan('2026-01-01', [_row('o/r', i) for i in range(5)])
    b = _scan('2026-02-01', [_row('o/r', 0), _row('o/r', 1, exfil=True)])
    d = diff(a, b)
    check('total falls', [h for h in d['headline'] if h['key'] == 'total'][0]['new'] == 2)
    check('exfil grows against a falling total', len(d['exfil']['added']) == 1)

    # IDENTITY IS PER-REPO: same issue number in two repos is two issues.
    a = _scan('2026-01-01', [_row('o/one', 5, exfil=True)])
    b = _scan('2026-02-01', [_row('o/two', 5, exfil=True)])
    d = diff(a, b)
    check('same number in a different repo is not the same issue',
          len(d['exfil']['added']) == 1 and len(d['exfil']['removed']) == 1)

    # A ROW WITHOUT THE FLAG IS FALSE, NOT AN ERROR.
    a = _scan('2026-01-01', [{'repo': 'o/r', 'number': 1}])
    b = _scan('2026-02-01', [_row('o/r', 1, exfil=True)])
    d = diff(a, b)
    check('unclassified old row reads as not-exfil', len(d['exfil']['added']) == 1)

    # AGENT-TARGETED IS DIFFED INDEPENDENTLY OF EXFIL.
    a = _scan('2026-01-01', [_row('o/r', 1, agent=True)])
    b = _scan('2026-02-01', [_row('o/r', 1, agent=True), _row('o/r', 2, agent=True)])
    d = diff(a, b)
    check('agent-targeted diffs on its own', len(d['agent_targeted']['added']) == 1)
    check('agent-targeted not confused with exfil', d['exfil']['identical'])

    # REPO COUNTS FOR THE ASKING ISSUES.
    a = _scan('2026-01-01', [_row('x/a', 1, exfil=True)])
    b = _scan('2026-02-01', [_row('x/a', 1, exfil=True), _row('x/b', 1, exfil=True)])
    d = diff(a, b)
    check('a new asking repo is visible', d['exfil_repos']['new'].get('x/b') == 1)
    check('an old asking repo keeps its count', d['exfil_repos']['old'].get('x/a') == 1)

    # RENDER MUST NOT CRASH AND MUST SAY THE WORD.
    txt = render(diff(_scan('2026-01-01', [_row('o/r', 1, exfil=True)]),
                      _scan('2026-02-01', [_row('o/r', 1, exfil=True)])))
    check('render says IDENTICAL SET when it is', 'IDENTICAL SET' in txt)
    txt = render(diff(_scan('2026-01-01', [_row('o/r', 1, exfil=True)]),
                      _scan('2026-02-01', [_row('o/r', 2, exfil=True)])))
    exfil_block = txt.split('LABELLED FOR AUTONOMOUS AGENTS ONLY')[0]
    check('render does not say IDENTICAL for a set that turned over',
          'IDENTICAL SET' not in exfil_block)
    check('render lists the added issue', 'o/r#2' in txt)
    # An empty population must not masquerade as a stability finding.
    check('empty-in-both is not reported as IDENTICAL SET',
          'EMPTY IN BOTH RUNS' in txt and 'IDENTICAL SET' not in txt)

    # A MISSING HEADLINE KEY IS "-" AND NOT A CRASH.
    a = {'date': 'd1', 'rows': [], 'total': 0}
    b = {'date': 'd2', 'rows': [], 'total': 0}
    check('missing keys render', 'BOUNTY BOARD DIFF' in render(diff(a, b)))

    print(f'{ok} ok / {fail} failed')
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('old', nargs='?')
    ap.add_argument('new', nargs='?')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--json', dest='json_out')
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.old or not args.new:
        ap.error('need OLD.json and NEW.json (or --selftest)')

    d = diff(load(args.old), load(args.new))
    print(render(d))
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(d, indent=2))
        print(f'\nwrote {args.json_out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
