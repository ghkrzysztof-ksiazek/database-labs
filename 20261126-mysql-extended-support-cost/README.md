# 20261126-mysql-extended-support-cost

Estimate what RDS Extended Support costs for RDS for MySQL and Aurora MySQL instances over a date window.

Blog post: MySQL 8.0 to 8.4, part 1 – what waiting costs on RDS and Aurora

## What's here

| File | What it is |
|---|---|
| `es_cost.py` | The calculator. Reads `describe-db-instances` JSON, prints cost per instance and a total |
| `calendar.json` | End of standard support and Extended Support dates, copied from the AWS docs on 19 Nov 2026 |
| `vcpus.json` | vCPU count per DB instance class, parsed from the AWS instance class page on 19 Nov 2026 |
| `sample-instances.json` | A made-up fleet used in the post. Not a real account |
| `simulated-instances.json` | A simulated sa-east-1 fleet (RDS 8.0, Aurora v3, one opted-out cluster, one PostgreSQL). Not a real account |
| `test_es_cost.py` | Unit tests for the arithmetic |

## Run it

```
aws rds describe-db-instances --output json > instances.json
python3 es_cost.py --instances instances.json --rate-y1 0.100 --rate-y3 0.200 --from 2026-11-26
```

Take the two rates from the RDS for MySQL or Aurora pricing page for your region. The script doesn't call the pricing API.

Run the tests with `python3 -m unittest -v test_es_cost`.

## Limits

- Aurora Serverless (billed per ACU-hour) isn't covered.
- An instance class missing from `vcpus.json` is skipped with a note. Add it from the AWS docs, don't guess.
- A Multi-AZ RDS instance counts twice, because AWS bills Extended Support on the standby too.
- For Aurora, the Extended Support flag lives on the cluster. The script reads the instance field and treats a missing one as enrolled (the API default). Remove instances of a cluster that has it disabled.
- Check `calendar.json` against `aws rds describe-db-major-engine-versions` before you trust it.
