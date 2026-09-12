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

def main():
    cluster = os.environ['CLUSTER']
    backup = json.loads(kubectl('get', 'ps-backup', 't01-full', '-o', 'json'))
    assert backup['spec']['clusterName'] == cluster
    assert backup['status']['state'].lower() == 'succeeded'
    destination = backup['status']['destination']
    listing = objects(destination.removeprefix('s3://') + '/')
    chunks = [x for x in listing if not x['key'].endswith('.md5')]
    assert any('xtrabackup' in x['key'] for x in chunks), 'XtraBackup metadata chunks missing'
    checksums = [x for x in listing if x['key'].endswith('.md5')]
    # xbcloud may store its checksum sidecar next to the destination prefix.
    if not checksums:
        checksums = [x for x in objects(destination.removeprefix('s3://') + '.md5') if x['key'].endswith('.md5')]
    assert chunks and all(x['size'] > 0 for x in chunks), 'No nonzero backup chunks'
    assert checksums and all(x['size'] > 0 for x in checksums), 'No nonzero MD5 objects'
    evidence('BACKUP_DESTINATION', destination)
    evidence('BACKUP_CHUNKS', len(chunks))
    evidence('BACKUP_BYTES', sum(x['size'] for x in chunks))
    evidence('MD5_OBJECTS', len(checksums))
    active = json.loads(kubectl('get', 'ps', cluster, '-o', 'json'))['spec']['backup']['pitr']['binlogServer']['storage']['s3']
    prefix = active['bucket'] + '/' + active.get('prefix', '').strip('/') + '/'
    before = sum(x['size'] for x in objects(prefix))
    assert before > 0, 'Binlog prefix is empty'
    pods = json.loads(kubectl('get', 'pods', '-l', 'app.kubernetes.io/instance=' + cluster + ',app.kubernetes.io/component=database', '-o', 'json'))['items']
    def sql(pod, statement):
        return kubectl('exec', pod, '-c', 'mysql', '--', 'mysql', '-uroot', '-p' + os.environ['MYSQL_PASSWORD'], '-N', '-e', statement).strip()
    primaries = [p['metadata']['name'] for p in pods if sql(p['metadata']['name'], 'SELECT @@read_only') == '0']
    assert len(primaries) == 1
    database = os.environ['DATABASE']
    assert database.replace('_', '').isalnum()
    sql(primaries[0], f"CREATE TABLE IF NOT EXISTS `{database}`.t04_stream_probe (id BIGINT AUTO_INCREMENT PRIMARY KEY, pad VARBINARY(2048)); INSERT INTO `{database}`.t04_stream_probe(pad) SELECT RANDOM_BYTES(1024) FROM `{database}`.sbtest1 LIMIT 20000; FLUSH BINARY LOGS;")
    evidence('CONTROLLED_WRITE_ROWS', 20000)
    evidence('BINLOG_BYTES_BEFORE', before)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        after = sum(x['size'] for x in objects(prefix))
        if after > before:
            evidence('BINLOG_BYTES_AFTER', after)
            evidence('BINLOG_BYTE_GROWTH', after - before)
            return
        time.sleep(10)
    raise RuntimeError('Binlog bytes did not grow after controlled writes and rotation')


if __name__ == '__main__':
    main()
