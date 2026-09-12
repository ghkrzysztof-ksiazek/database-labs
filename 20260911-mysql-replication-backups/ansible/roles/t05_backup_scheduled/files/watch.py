"""Wait for a newly created, successful backup belonging to this schedule."""
import json
import os
import subprocess
import time


def eligible(item, cluster, schedule, seen):
    labels = item['metadata'].get('labels', {})
    return (item['metadata']['name'] not in seen
            and item.get('spec', {}).get('clusterName') == cluster
            and labels.get('percona.com/backup-type') == 'cron'
            and labels.get('percona.com/backup-ancestor', '').partition('-')[2] == schedule
            and item.get('status', {}).get('state', '').lower() == 'succeeded'
            and bool(item.get('status', {}).get('destination')))


def main():
    seen = set(json.loads(os.environ['SEEN']))
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        items = json.loads(subprocess.check_output(
            ['kubectl', '-n', os.environ['NS'], 'get', 'ps-backup',
             '-l', 'percona.com/backup-type=cron', '-o', 'json'],
            text=True, timeout=60))['items']
        for item in items:
            if eligible(item, os.environ['CLUSTER'], os.environ['SCHEDULE'], seen):
                print('NEW_BACKUP=' + item['metadata']['name'])
                print('NEW_BACKUP_ANCESTOR=' + item['metadata']['labels']['percona.com/backup-ancestor'])
                for key in ('state', 'destination', 'completed'):
                    print('NEW_BACKUP_' + key.upper() + '=' + str(item['status'].get(key, 'n/a')))
                return
        time.sleep(10)
    raise RuntimeError('No newly successful backup for the exact source cluster and schedule')


if __name__ == '__main__':
    main()
