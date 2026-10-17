import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/team'))
spec = importlib.util.spec_from_file_location('ec2_lanes', ROOT / 'scripts/team/ec2_lanes.py')
lanes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lanes)


class FakeAWS:
    def __init__(self):
        self.account = '123456789012'
        self.instances = {'i-aaaaaaaaaaaaaaaaa': 'stopped', 'i-bbbbbbbbbbbbbbbbb': 'running'}
        self.calls = []
        self.tokens = {}
        self.interrupt_create = False

    def __call__(self, service, operation, *arguments):
        self.calls.append((operation, arguments))
        if service == 'sts':
            return {'Account': self.account}
        if operation == 'describe-images':
            return {'Images': [{'RootDeviceName': '/dev/sda1', 'BlockDeviceMappings': [
                {'DeviceName': '/dev/sda1', 'Ebs': {'Encrypted': False}}]}]}
        if operation == 'describe-instances':
            instance = arguments[1]
            return {'Reservations': [{'Instances': [{'InstanceId': instance, 'State': {'Name': self.instances[instance]},
                                                      'PrivateIpAddress': '10.0.0.1'}]}]}
        if operation in ('start-instances', 'stop-instances'):
            self.instances[arguments[1]] = 'running' if operation == 'start-instances' else 'stopped'
            return {}
        if operation == 'run-instances':
            request = json.loads(arguments[1])
            instance = self.tokens.setdefault(request['ClientToken'], 'i-ccccccccccccccccc')
            self.instances[instance] = 'running'
            if self.interrupt_create:
                self.interrupt_create = False
                raise ValueError('response lost after AWS created instance')
            return {'Instances': [{'InstanceId': instance}]}
        raise AssertionError(operation)


def config():
    return {'account': '123456789012', 'region': 'ap-northeast-1', 'study': 'test-study',
            'excluded_instance_ids': ['i-fffffffffffffffff'],
            'lanes': {'lane-a': {'app': {'instance_id': 'i-aaaaaaaaaaaaaaaaa'},
                                 'bench': {'instance_id': 'i-bbbbbbbbbbbbbbbbb'}}}}


class EC2LanesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ec2-state.json'
        self.aws = FakeAWS()

    def test_wrong_account_does_not_mutate(self):
        self.aws.account = '000000000000'
        with self.assertRaisesRegex(ValueError, 'account'):
            lanes.run(config(), {}, self.path, 'ensure', self.aws)
        self.assertEqual([x[0] for x in self.aws.calls], ['get-caller-identity'])
        self.assertFalse(self.path.exists())

    def test_duplicate_and_official_resources_refused(self):
        for instance in ('i-aaaaaaaaaaaaaaaaa', 'i-fffffffffffffffff'):
            conf = config()
            conf['lanes']['lane-a']['bench']['instance_id'] = instance
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                lanes.run(conf, {}, self.path, 'ensure', self.aws)
        self.assertEqual(self.aws.calls, [])

    def test_stop_only_this_run_and_idempotent_existing(self):
        state = {}
        lanes.run(config(), state, self.path, 'ensure', self.aws)
        lanes.run(config(), state, self.path, 'ensure', self.aws)
        self.assertEqual(sum(x[0] == 'start-instances' for x in self.aws.calls), 1)
        lanes.run(config(), state, self.path, 'stop', self.aws)
        self.assertEqual(self.aws.instances['i-aaaaaaaaaaaaaaaaa'], 'stopped')
        self.assertEqual(self.aws.instances['i-bbbbbbbbbbbbbbbbb'], 'running')
        self.assertFalse(state['hosts']['lane-a/bench']['managed'])

    def test_creation_retry_after_lost_response_reuses_token(self):
        conf = config()
        conf['lanes']['lane-a']['bench'] = {'launch': {
            'ImageId': 'ami-example', 'InstanceType': 'c5.xlarge', 'SubnetId': 'subnet-example',
            'SecurityGroupIds': ['sg-example'],
            'BlockDeviceMappings': [{'DeviceName': '/dev/sda1', 'Ebs': {'Encrypted': True}}]}}
        self.aws.interrupt_create = True
        with self.assertRaisesRegex(ValueError, 'response lost'):
            lanes.run(conf, {}, self.path, 'ensure', self.aws)
        state = json.loads(self.path.read_text())
        self.assertIn('launch_request', state['hosts']['lane-a/bench'])
        lanes.run(conf, state, self.path, 'ensure', self.aws)
        self.assertEqual(len(self.aws.tokens), 1)
        requests = [json.loads(args[1]) for op, args in self.aws.calls if op == 'run-instances']
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(requests[0]['MetadataOptions']['HttpTokens'], 'required')
        self.assertTrue(requests[0]['BlockDeviceMappings'][0]['Ebs']['Encrypted'])
        self.assertTrue(any(x['Key'] == 'Study' for x in requests[0]['TagSpecifications'][0]['Tags']))
        lanes.run(conf, state, self.path, 'stop', self.aws)
        self.assertEqual(self.aws.instances['i-ccccccccccccccccc'], 'stopped')

    def test_startup_import_is_explicit_and_preserves_evidence(self):
        self.aws.instances['i-aaaaaaaaaaaaaaaaa'] = 'running'
        imported = {'study': 'test-study', 'account': '123456789012', 'instances': {
            'i-aaaaaaaaaaaaaaaaa': {'original_state': 'stopped', 'evidence': 'instances-before.json'},
            'i-bbbbbbbbbbbbbbbbb': {'original_state': 'absent', 'evidence': 'ec2-response.json'}}}
        state = {}
        lanes.run(config(), state, self.path, 'ensure', self.aws, imported)
        self.assertEqual(state['hosts']['lane-a/app']['original_state'], 'stopped')
        self.assertTrue(state['hosts']['lane-a/bench']['created'])
        lanes.run(config(), state, self.path, 'stop', self.aws)
        self.assertEqual(set(self.aws.instances.values()), {'stopped'})
        imported['instances']['i-aaaaaaaaaaaaaaaaa']['original_state'] = 'running'
        with self.assertRaisesRegex(ValueError, 'original stopped'):
            lanes.run(config(), state, self.path, 'ensure', self.aws, imported)

    def test_existing_state_cannot_be_reclassified_by_import(self):
        state = {}
        lanes.run(config(), state, self.path, 'ensure', self.aws)
        imported = {'study': 'test-study', 'account': '123456789012', 'instances': {
            'i-bbbbbbbbbbbbbbbbb': {'original_state': 'stopped', 'evidence': 'later claim'}}}
        lanes.run(config(), state, self.path, 'ensure', self.aws, imported)
        self.assertFalse(state['hosts']['lane-a/bench']['managed'])

    def test_configuration_drift_and_unencrypted_launch_refused(self):
        state = {}
        conf = config()
        lanes.run(conf, state, self.path, 'ensure', self.aws)
        conf['region'] = 'us-east-1'
        with self.assertRaisesRegex(ValueError, 'another configuration'):
            lanes.run(conf, state, self.path, 'ensure', self.aws)
        with self.assertRaisesRegex(ValueError, 'encryption'):
            lanes.launch_request(config(), 'lane-a', 'bench', {
                'ImageId': 'ami-x', 'InstanceType': 'c5.xlarge', 'SubnetId': 'subnet-x',
                'SecurityGroupIds': ['sg-x'], 'BlockDeviceMappings': [{'Ebs': {'Encrypted': False}}]})
        with self.assertRaisesRegex(ValueError, 'AMI root'):
            lanes.validate_image_disks(self.aws, {'ImageId': 'ami-x', 'BlockDeviceMappings': [
                {'DeviceName': '/dev/sdf', 'Ebs': {'Encrypted': True}}]})

    def test_idle_refuses_reservation_and_pending_portal(self):
        path = str(Path(self.temp.name) / 'team.sqlite3')
        db = lanes.connect(path)
        db.execute("INSERT INTO reservation VALUES (1,'a','t','test','now')")
        db.commit()
        db.close()
        with self.assertRaisesRegex(ValueError, 'release'):
            with lanes.idle(path, config()):
                self.fail('must not run')
        db = lanes.connect(path)
        db.execute('DELETE FROM reservation')
        db.commit()
        db.close()
        marker = lanes.state_path(path, 'lane-a', '.manual-bench')
        marker.touch()
        with self.assertRaisesRegex(ValueError, 'portal'):
            with lanes.idle(path, config()):
                self.fail('must not run')
        marker.unlink()
        with lanes.idle(path, config()):
            pass


if __name__ == '__main__':
    unittest.main()
