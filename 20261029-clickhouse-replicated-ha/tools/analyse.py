#!/usr/bin/env python3
"""Summarise one results/<label>/ directory written by run-experiments.sh.
Times are the host's local clock. Resolution is one load line (1 s) unless noted."""
import json, re, sys, pathlib

def secs(t):
    h, m, s = t.split(':'); return int(h) * 3600 + int(m) * 60 + float(s)

def load(R):
    L = []
    for line in (R / 'loadgen.log').read_text().splitlines():
        m = re.match(r'(\d\d:\d\d:\d\d) \[ (\d+)s \] inserts/s: (\d+) ins_err/s: (\d+) selects/s: (\d+) sel_err/s: (\d+)', line)
        if m: L.append(dict(t=secs(m[1]), ins=int(m[3]), ierr=int(m[4]), sel=int(m[5]), serr=int(m[6])))
    E = []
    for line in (R / 'events.log').read_text().splitlines():
        m = re.match(r'(\d\d:\d\d:\d\d\.\d+) (.*)', line)
        if m: E.append((secs(m[1]), m[2]))
    return L, E

def ev(E, prefix):
    for t, s in E:
        if s.startswith(prefix): return t, s
    raise KeyError(prefix)

def window(L, a, b): return [x for x in L if a <= x['t'] < b]

def analyse(R):
    R = pathlib.Path(R); L, E = load(R); out = {'label': R.name}
    base = window(L, ev(E, 'A kill')[0] - 15, ev(E, 'A kill')[0] - 1)
    out['baseline_ins'] = [min(x['ins'] for x in base), max(x['ins'] for x in base)]
    out['baseline_sel'] = [min(x['sel'] for x in base), max(x['sel'] for x in base)]
    # A
    tA = ev(E, 'A kill')[0]; w = window(L, int(tA), int(tA) + 15)
    out['A_zero_insert_s'] = sum(1 for x in w if x['ins'] == 0)
    out['A_ins_err'] = sum(x['ierr'] for x in w); out['A_sel_err'] = sum(x['serr'] for x in w)
    for line in (R / 'A-haproxy.txt').read_text().splitlines():
        if 'ch-1=DOWN' in line: out['A_haproxy_down_s'] = round(secs(line.split()[0]) - tA, 1); break
    tAs = ev(E, 'A start')[0]
    for line in (R / 'A-haproxy-back.txt').read_text().splitlines():
        if re.search(r'ch-1=UP(?! )', line) or 'ch-1=UP ch-2' in line:
            out['A_haproxy_up_after_start_s'] = round(secs(line.split()[0]) - tAs, 1); break
    wb = window(L, int(tAs), int(tAs) + 20); out['A_return_errors'] = sum(x['ierr'] + x['serr'] for x in wb)
    # B
    tB, sB = ev(E, 'B kill'); w = window(L, int(tB), int(tB) + 16)
    out['B_killed'] = sB.split()[-1]
    bs = R / 'B-sessions.txt'
    if bs.exists(): out['B_sessions'] = bs.read_text().strip().splitlines()
    out['B_zero_insert_s'] = sum(1 for x in w if x['ins'] == 0)
    out['B_errors'] = sum(x['ierr'] + x['serr'] for x in w)
    for line in (R / 'B-mntr.txt').read_text().splitlines()[1:]:
        if '=leader' in line: out['B_new_leader_by_s'] = round(secs(line.split()[0]) - tB, 1); break
    # C
    tC, sC = ev(E, 'C kill'); tCs = ev(E, 'C start')[0]
    w = window(L, int(tC), int(tCs))
    errs = [x['t'] for x in w if x['ierr'] > 0]
    out['C_insert_errors_before_restore'] = sum(x['ierr'] for x in w)
    out['C_first_error_after_kill_s'] = round(errs[0] - tC) if errs else None
    out['C_gap_between_errors_s'] = round(errs[1] - errs[0]) if len(errs) > 1 else None
    out['C_sel_err'] = sum(x['serr'] for x in w)
    out['C_sel_range'] = [min(x['sel'] for x in w), max(x['sel'] for x in w)]
    st = (R / 'C-state.txt').read_text(); out['C_state'] = st.strip().splitlines()
    m = re.search(r'max_retries=0: ([\d.]+)', ev(E, 'C insert with')[1]); out['C_retries0_s'] = float(m[1])
    last = (R / 'C-back.txt').read_text().splitlines()
    first_ok = {}
    for line in last:
        t = secs(line.split()[0])
        for h in ('ch-1', 'ch-2'):
            if f'{h} ro=0' in line and h not in first_ok: first_ok[h] = round(t - tCs, 1)
    out['C_writable_after_restore_s'] = first_ok
    w2 = window(L, int(tCs), int(tCs) + 30); out['C_ins_err_after_restore'] = sum(x['ierr'] for x in w2)
    # D
    for key, pre in (('D_healthy', 'D healthy'), ('D_1s_after_kill', 'D quorum insert 900002'),
                     ('D_after_expiry', 'D quorum insert 900003'), ('D_dedup_first', 'D dedup first'),
                     ('D_dedup_retry', 'D dedup retry')):
        s = ev(E, pre)[1]; m = re.search(r': ([\d.]+) (.*)$', s)
        code = re.search(r'\(([A-Z_]+)\)', m[2]); out[key] = [float(m[1]), code[1] if code else 'ok']
    tD = ev(E, 'D kill ch-2')[0]; w = window(L, int(tD), int(tD) + 6)
    out['D_loader_errors'] = [sum(x['ierr'] for x in w), sum(x['serr'] for x in w)]
    out['final'] = (R / 'final.txt').read_text().strip().splitlines()
    mem = {}
    for line in (R / 'mem.txt').read_text().splitlines():
        p = line.split()
        if len(p) >= 5 and p[2].isdigit(): mem.setdefault(p[1], []).append((int(p[2]), int(p[3]), int(p[4])))
    out['peak_rss_MiB'] = {h: max(v[0] for v in vs) for h, vs in mem.items()}
    out['peak_tracked_MiB'] = {h: max(v[1] for v in vs) for h, vs in mem.items()}
    out['peak_outdated_parts'] = {h: max(v[2] for v in vs) for h, vs in mem.items()}
    return out

if __name__ == '__main__':
    for d in sys.argv[1:]: print(json.dumps(analyse(d), indent=1))
