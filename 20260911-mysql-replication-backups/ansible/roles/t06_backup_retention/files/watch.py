import json
import os
import shlex
import subprocess
import time
import uuid


def kubectl(*args):
    return subprocess.check_output(['kubectl', '-n', os.environ['NS'], *args], text=True, timeout=180)


def objects(path):
    script = 'set -eu\nmc alias set local http://minio:9000 ' + shlex.quote(os.environ['MC_USER']) + ' ' + shlex.quote(os.environ['MC_PASSWORD']) + ' >/dev/null\nmc ls --json --recursive ' + shlex.quote('local/' + path)
    name = 'mc-probe-' + uuid.uuid4().hex[:10]
    try:
        kubectl('run', name, '--restart=Never', '--quiet', '--image=' + os.environ['MC_IMAGE'], '--command', '--', 'sh', '-c', script)
        try:
            kubectl('wait', '--for=jsonpath={.status.phase}=Succeeded', 'pod/' + name, '--timeout=120s')
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('MinIO probe failed: ' + kubectl('logs', name)) from exc
        output = kubectl('logs', name)
    finally:
        subprocess.run(['kubectl', '-n', os.environ['NS'], 'delete', 'pod', name, '--ignore-not-found', '--wait=false'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    result = []
    for line in output.splitlines():
        if not line.startswith('{'):
            continue
        item = json.loads(line)
        if item.get('status') == 'error':
            raise RuntimeError('MinIO listing failed: ' + str(item))
        if item.get('type') == 'file':
            result.append(item)
    return result


def evidence(key, value):
    print(key + '=' + str(value), flush=True)

def matching(items, cluster, schedule):
    return {x['metadata']['name']: x for x in items
            if x.get('spec', {}).get('clusterName') == cluster
            and x['metadata'].get('labels', {}).get('percona.com/backup-type') == 'cron'
            and x['metadata'].get('labels', {}).get('percona.com/backup-ancestor', '').partition('-')[2] == schedule}


def succeeded(item):
    return item.get('status', {}).get('state', '').lower() == 'succeeded' and bool(item.get('status', {}).get('destination'))


def main():
    keep = int(os.environ['KEEP'])
    seen = {}
    deadline = time.monotonic() + 1500
    while time.monotonic() < deadline:
        current = matching(json.loads(kubectl('get', 'ps-backup', '-o', 'json'))['items'], os.environ['CLUSTER'], os.environ['SCHEDULE'])
        for name, item in current.items():
            if succeeded(item):
                seen[name] = item['status']['destination']
        pruned = sorted(set(seen) - set(current))
        surviving = [name for name, item in current.items() if succeeded(item)]
        if len(seen) >= keep + 1 and len(surviving) == keep and pruned:
            # Each removed CR was observed successfully completed, so failed jobs
            # and transient name-list changes cannot masquerade as retention.
            absent = []
            leftovers = []
            for name in pruned:
                path = seen[name].removeprefix('s3://').rstrip('/')
                parent, basename = path.rsplit('/', 1)
                listing = objects(parent + '/')
                remaining = [x for x in listing if x['key'].startswith(basename + '/')]
                if remaining:
                    break
                absent.append(name)
                leftovers.extend(x['key'] for x in listing if x['key'] == basename + '.md5')
            else:
                evidence('KEEP', keep)
                evidence('PRODUCED_COUNT', len(seen))
                evidence('PRODUCED', ','.join(sorted(seen)))
                evidence('SURVIVING_COUNT', len(surviving))
                evidence('SURVIVING', ','.join(sorted(surviving)))
                evidence('PRUNED', ','.join(absent))
                for name in absent:
                    evidence('REMOVED_DATA_PREFIX', seen[name] + '/')
                evidence('MD5_SIDECARS_REMAINING', json.dumps(leftovers))
                evidence('RETENTION_SCOPE', 'successful backup CRs and data prefixes; sibling MD5 sidecars reported separately')
                return
        time.sleep(5)
    raise RuntimeError('Retention failed to leave exactly keep successful backups with removed data prefixes; observed=' + json.dumps(seen))


if __name__ == '__main__':
    main()
