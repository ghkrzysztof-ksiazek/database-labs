#!/usr/bin/env python3
"""Estimate RDS Extended Support charges for RDS for MySQL and Aurora MySQL.

Input: the JSON from `aws rds describe-db-instances --output json`.
You pass the rates yourself (USD per vCPU-hour, from the AWS pricing page
for your region). The script never calls AWS and never guesses a vCPU count.
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(HERE, name)) as f:
        return json.load(f)


def d(s):
    return date.fromisoformat(s) if s else None


def major_of(engine, version):
    # mysql: "8.0.42" -> "8.0"; aurora-mysql: "5.7.mysql_aurora.2.12.5" -> "5.7"
    return ".".join(version.split(".")[:2])


def hours_between(start, end):
    """Hours in [start, end), both dates, zero if empty."""
    return max(0, (end - start).days) * 24


def cost_window(cal, vcpus, start, end, rate_y1, rate_y3):
    """Return (hours_y1, hours_y3, cost, note) for [start, end)."""
    y1, y3, es_end = d(cal.get("year1")), d(cal.get("year3")), d(cal.get("es_end"))
    if y1 is None:
        return 0, 0, 0.0, "no Extended Support dates published"
    stop = es_end + timedelta(days=1)          # es_end is the last billed day
    note = ""
    if end > stop:
        note = "AWS upgrades it after " + es_end.isoformat()
    y3_start = y3 if y3 else stop               # no year 3 rate for this version
    h1 = hours_between(max(start, y1), min(end, y3_start, stop))
    h3 = hours_between(max(start, y3_start), min(end, stop)) if y3 else 0
    return h1, h3, vcpus * (h1 * rate_y1 + h3 * rate_y3), note


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--instances", required=True, help="describe-db-instances JSON")
    p.add_argument("--rate-y1", type=float, required=True,
                   help="USD per vCPU-hour in years 1 and 2, from the AWS pricing page")
    p.add_argument("--rate-y3", type=float, required=True,
                   help="USD per vCPU-hour from year 3, from the AWS pricing page")
    p.add_argument("--from", dest="start", default=date.today().isoformat(),
                   help="first day of the window, YYYY-MM-DD (default: today)")
    p.add_argument("--to", dest="end", help="day after the window, default: one year later")
    a = p.parse_args(argv)

    start = d(a.start)
    end = d(a.end) if a.end else start.replace(year=start.year + 1)
    calendar = load("calendar.json")
    vcpu_table = load("vcpus.json")["vcpus"]
    with open(a.instances) as f:
        instances = json.load(f)["DBInstances"]

    print(f"Window {start} to {end} ({(end - start).days} days), "
          f"rates {a.rate_y1:.3f} / {a.rate_y3:.3f} USD per vCPU-hour\n")
    print(f"{'instance':<17}{'version':<26}{'class':<16}{'vCPU':>4}  "
          f"{'status on ' + start.isoformat():<28}{'USD':>10}")
    total, problems = 0.0, []
    for i in instances:
        name, engine, cls = i["DBInstanceIdentifier"], i["Engine"], i["DBInstanceClass"]
        if engine not in calendar:
            problems.append(f"{name}: engine {engine} is not covered")
            continue
        major = major_of(engine, i["EngineVersion"])
        cal = calendar[engine].get(major)
        if cal is None:
            problems.append(f"{name}: {engine} {major} is not in calendar.json")
            continue
        if cls == "db.serverless":
            problems.append(f"{name}: Aurora Serverless is billed per ACU-hour, not covered")
            continue
        if cls not in vcpu_table:
            problems.append(f"{name}: unknown class {cls}, add it to vcpus.json from the AWS docs")
            continue
        vcpus = vcpu_table[cls]
        # A Multi-AZ instance deployment has a standby, and AWS bills it too.
        copies = 2 if engine == "mysql" and i.get("MultiAZ") else 1
        enrolled = i.get("EngineLifecycleSupport", "open-source-rds-extended-support")
        if enrolled.endswith("-disabled"):
            status, cost = "not enrolled", 0.0
        else:
            h1, h3, cost, note = cost_window(cal, vcpus * copies, start, end, a.rate_y1, a.rate_y3)
            y1, y3 = d(cal.get("year1")), d(cal.get("year3"))
            if y1 is None or start < y1:
                until = cal.get("std_end") or cal.get("std_end_text")
                status = f"standard to {until}"
            elif y3 and start >= y3:
                status = "ES, year 3 rate"
            else:
                status = "ES, year 1-2 rate"
                if y3 and y3 < end:
                    status = f"ES, year 3 from {y3}"
            if note:
                problems.append(f"{name}: {note}")
        label = cal["label"] + (" (M-AZ)" if copies == 2 else "")
        print(f"{name:<17}{label:<26}{cls:<16}{vcpus * copies:>4}  {status:<28}{cost:>10,.2f}")
        total += cost
    print(f"\n{'total':<17}{'':<26}{'':<16}{'':>4}  {'':<28}{total:>10,.2f}")
    for msg in problems:
        print("NOTE " + msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
