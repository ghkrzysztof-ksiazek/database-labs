"""Behavior checks for retention selection and storage failure handling."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


schedule_watch = load('schedule_watch', 'ansible/roles/t05_backup_scheduled/files/watch.py')
watch = load('retention_watch', 'ansible/roles/t06_backup_retention/files/watch.py')


def backup(name, cluster='lab', schedule='hash-suite-fast', state='Succeeded'):
    return {'metadata': {'name': name, 'labels': {
        'percona.com/backup-type': 'cron',
        'percona.com/backup-ancestor': schedule}},
        'spec': {'clusterName': cluster},
        'status': {'state': state, 'destination': 's3://bucket/' + name}}


class RetentionTests(unittest.TestCase):
    def test_scheduled_success_requires_exact_cluster_schedule_and_new_name(self):
        self.assertTrue(schedule_watch.eligible(backup('new'), 'lab', 'suite-fast', set()))
        for item in (backup('old'), backup('new', cluster='verify'),
                     backup('new', schedule='hash-other-suite-fast'),
                     backup('new', state='Running'), backup('new', state='Failed')):
            self.assertFalse(schedule_watch.eligible(item, 'lab', 'suite-fast', {'old'}))

    def test_selection_uses_cluster_and_exact_schedule_suffix(self):
        items = [backup('wanted'), backup('other', cluster='verify'),
                 backup('suffix', schedule='hash-suite-fast-long'),
                 backup('prefix', schedule='hash-other-suite-fast')]
        # Upstream ancestor is <hash>-<schedule>; suffix comparison avoids
        # selecting suite-fast-long. Cluster filtering excludes verify.
        result = watch.matching(items, 'lab', 'suite-fast')
        self.assertEqual(set(result), {'wanted'})

    def test_failed_or_incomplete_backups_do_not_count_as_produced(self):
        self.assertFalse(watch.succeeded(backup('bad', state='Failed')))
        item = backup('empty')
        item['status']['destination'] = ''
        self.assertFalse(watch.succeeded(item))
        self.assertTrue(watch.succeeded(backup('good')))

    def test_minio_error_cannot_be_mistaken_for_empty_prefix(self):
        env = {'NS': 'mysql', 'MC_USER': 'minio', 'MC_PASSWORD': 'test', 'MC_IMAGE': 'mc'}
        with patch.dict(watch.os.environ, env), patch.object(watch, 'kubectl', return_value='{"status":"error","error":"denied"}'), patch.object(watch.subprocess, 'run'):
            with self.assertRaisesRegex(RuntimeError, 'MinIO listing failed'):
                watch.objects('bucket/prefix/')

    def test_mc_script_is_separated_from_kubectl_flags(self):
        env = {'NS': 'mysql', 'MC_USER': 'minio', 'MC_PASSWORD': 'test', 'MC_IMAGE': 'mc'}
        with patch.dict(watch.os.environ, env), patch.object(watch, 'kubectl', return_value='') as call, patch.object(watch.subprocess, 'run'):
            self.assertEqual(watch.objects('bucket/prefix/'), [])
            args = call.call_args_list[0].args
            self.assertEqual(args[args.index('--command') + 1:][:3], ('--', 'sh', '-c'))
            self.assertNotIn('--rm', args)
            self.assertEqual([c.args[0] for c in call.call_args_list], ['run', 'wait', 'logs'])

    def test_multiline_names_are_compared_as_sets(self):
        seen = {'cron-a': 'a', 'cron-b': 'b', 'cron-c': 'c'}
        current = watch.matching([backup('cron-b'), backup('cron-c')], 'lab', 'suite-fast')
        self.assertEqual(set(seen) - set(current), {'cron-a'})


if __name__ == '__main__':
    unittest.main()
