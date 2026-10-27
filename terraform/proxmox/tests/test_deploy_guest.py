import argparse
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('deploy_guest', MODULE / 'scripts/deploy_guest.py')
deploy = importlib.util.module_from_spec(loader)
loader.loader.exec_module(deploy)


def example(kind='lxc'):
    return deploy.validate(dict(name='workflow-test', kind=kind, node_name='test-node', vlan_id=40,
                                ipv4_address='192.0.2.10/24', gateway='192.0.2.1', dns_servers=['192.0.2.1'],
                                ssh_public_key_file=str(MODULE / 'tests/install.pub'),
                                **({'template_file_id':'local:vztmpl/debian-test.tar.zst'} if kind=='lxc' else {'iso_filename':'debian-test.iso'})))


def change(address, actions, before=None, after=None):
    return dict(address=address, mode='managed', change=dict(actions=actions, before=before, after=after))


class WorkflowTests(unittest.TestCase):
    def test_existing_guest_addresses_do_not_include_media_metadata(self):
        import ipaddress
        self.assertTrue(deploy.contains_ip({'initialization':[{'ipv4':{'address':'192.0.2.10/24'}}]},ipaddress.ip_address('192.0.2.10')))
        self.assertFalse(deploy.contains_ip({'value':'unrelated'},ipaddress.ip_address('192.0.2.10')))

    def test_recreation_rotates_only_the_selected_guest_host_key(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);(directory/'known_hosts').write_text('previous-key')
            with patch.object(deploy.subprocess,'run') as run:
                deploy.prepare_guest_recreation(example(),directory)
            self.assertEqual((directory/'previous-guest-known_hosts').read_text(),'previous-key')
            self.assertEqual(run.call_args.args[0],['ssh-keygen','-R','192.0.2.10','-f',str(directory/'known_hosts')])

    def test_recreation_archives_identity_and_requests_verified_host_key_rotation(self):
        import uuid
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);identifier=str(uuid.uuid4());cache=root/'artifacts/iso-install'/identifier;cache.mkdir(parents=True)
            verified=cache/'verified.json';verified.write_text(json.dumps({'uuid':identifier}))
            (cache/'known_hosts').write_text('previous-host-key')
            job=root/'job';job.mkdir()
            p=dict(example('vm'),vm_id=132)
            resources=[dict(address='terraform_data.install_identity["workflow-test"]',values={'id':identifier})]
            with patch.object(deploy,'ROOT',root): deploy.prepare_vm_recreation(p,resources,job)
            self.assertFalse(verified.exists())
            self.assertTrue((job/'previous-install-verified.json').exists())
            self.assertEqual((job/'previous-install-known_hosts').read_text(),'previous-host-key')
            self.assertEqual((cache/'known_hosts').read_text(),'previous-host-key')

    def test_new_guest_access_never_passes_token_secret_to_ssh(self):
        p=dict(example(),vm_id=132)
        with patch.dict(deploy.os.environ,{'PROXMOX_VE_API_TOKEN':'terraform@pve!pilot=private-secret'}),patch.object(deploy,'ssh_args',return_value=['ssh','test-node']),patch.object(deploy.subprocess,'run') as run:
            deploy.grant_new_guest_access(p)
        self.assertNotIn('private-secret',str(run.call_args))
        self.assertEqual(json.loads(run.call_args.kwargs['input']),{'vm_id':132,'identity':'terraform@pve!pilot'})
        self.assertIn('TerraformGuest',run.call_args.args[0][-1])

    def test_profile_boundaries(self):
        p=example()
        for key,value in [('name','x;id'),('name','../test'),('kind','qemu'),('app','unknown'),('os','fedora'),
                          ('vm_id',True),('vlan_id','40'),('gateway','198.51.100.1'),('ipv4_address','192.0.2.1/24'),
                          ('ssh_public_key_file',str(Path(__file__))),('template_file_id','../bad'),('on_boot','false'),
                          ('unknown','unused')]:
            with self.subTest(key=key,value=value), self.assertRaises((ValueError,UnicodeDecodeError)):
                deploy.validate(dict(p,**{key:value}))

    def test_new_vm_defaults_to_uefi_and_secure_boot(self):
        p=dict(example('vm'),vm_id=132)
        spec=deploy.vm_spec(p)
        self.assertEqual(spec['firmware'],'uefi')
        self.assertIs(spec['secure_boot'],True)
        self.assertEqual(spec['disk_gb'],24)
        self.assertTrue(spec['on_boot'])
        self.assertTrue(spec['backup'])
        self.assertNotIn('app',spec)

    def test_lxc_bootstrap_and_final_hardware(self):
        p=dict(example(),vm_id=132)
        initial=next(iter(deploy.lxc_config(p,bootstrap=True)['resource']['proxmox_virtual_environment_container'].values()))
        final=next(iter(deploy.lxc_config(p)['resource']['proxmox_virtual_environment_container'].values()))
        self.assertFalse(initial['started'])
        self.assertNotIn('features',initial)
        self.assertIn('--bootstrap-lxc',initial['provisioner'][0]['local-exec']['command'])
        self.assertTrue(final['started'])
        self.assertTrue(final['features']['nesting'])
        self.assertTrue(final['unprivileged'])
        self.assertTrue(final['lifecycle']['prevent_destroy'])
        self.assertNotIn('provisioner',final)

    def test_plan_rejects_other_guest_or_media_changes(self):
        p=dict(example('vm'),vm_id=132)
        own=deploy.address(p)
        allowed=[change(own,['create'],after={'vm_id':132})]
        deploy.review_plan({'resource_changes':allowed},p)
        for c in [change(own,['delete']),change(own,['delete','create']),change(own,['update']),
                  change(own,['create'],after={'vm_id':131}),
                  change('proxmox_virtual_environment_vm.existing',['create'],after={'vm_id':132}),
                  change('proxmox_virtual_environment_file.install_media["other"]',['delete'])]:
            with self.subTest(change=c),self.assertRaises(ValueError):
                deploy.review_plan({'resource_changes':[c]},p)
        for flag in ['deferred_changes','errored']:
            with self.assertRaises(ValueError): deploy.review_plan({flag:True},p)

    def test_only_start_is_allowed_in_second_lxc_plan(self):
        p=dict(example(),vm_id=132);own=deploy.address(p)
        deploy.review_plan({'resource_changes':[change(own,['update'],before={'started':False,'vm_id':132},after={'started':True,'vm_id':132})]},p,start=True)
        with self.assertRaises(ValueError):
            deploy.review_plan({'resource_changes':[change(own,['update'],before={'started':False,'vm_id':132},after={'started':True,'vm_id':131})]},p,start=True)

    def test_inventory_is_exactly_one_guest_and_no_cluster_group(self):
        p=dict(example('vm'),vm_id=132)
        with tempfile.TemporaryDirectory() as d:
            i=deploy.inventory(p,Path(d))
        groups=i['all']['children'];self.assertEqual(set(groups),{'gatus_guests'})
        hosts=groups['gatus_guests']['hosts'];self.assertEqual(len(hosts),1)
        host=next(iter(hosts.values()))
        self.assertEqual(host['ansible_host'],'192.0.2.10')
        self.assertEqual(host['ansible_user'],'ansible')
        self.assertIn('StrictHostKeyChecking=accept-new',host['ansible_ssh_common_args'])
        self.assertLess(len(host['ansible_control_path'].replace('%%C','a'*40)),104)
        self.assertEqual(host['gatus_discord_webhook_url'],'')

    def harness(self,kind='lxc',plan_only=False,owned=False,plans=None,ansible_fails=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)/'repo/terraform/proxmox';root.mkdir(parents=True)
        p=dict(example(kind),vm_id=132)
        profile=root/'profile.json';profile.write_text(json.dumps(p))
        directory=root/'artifacts/deploy'/p['name'];directory.mkdir(parents=True)
        own=deploy.address(p)
        if owned: deploy.write_json(directory/'profile.json',p)
        calls=[]
        resources=[dict(address=own,mode='managed',values=dict(vm_id=132,started=True))] if owned else []
        default=[dict(resource_changes=[change(own,['create'],after={'vm_id':132})])]
        if kind=='lxc': default.append(dict(resource_changes=[change(own,['update'],before={'started':False,'vm_id':132},after={'started':True,'vm_id':132})]))
        plans=copy.deepcopy(plans if plans is not None else default)
        def run(command,**kwargs):
            calls.append(command)
            if command[1:]==['show','-json']:
                json.dump({'values':{'root_module':{'resources':resources}}},kwargs['stdout'])
            elif command[1:3]==['show','-json']:
                json.dump(plans.pop(0),kwargs['stdout'])
            elif command[0]=='ansible-playbook' and ansible_fails:
                return subprocess.CompletedProcess(command,2)
            return subprocess.CompletedProcess(command,0)
        args=argparse.Namespace(profile=profile,terraform='terraform',plan_only=plan_only)
        def execute():
            with patch.object(deploy,'ROOT',root),patch.object(deploy,'load_environment'),patch.object(deploy,'grant_new_guest_access'),patch.object(deploy,'prime_lxc_network'),patch.object(deploy,'cluster_guests',return_value=[{'vmid':132,'name':p['name']}] if owned else []),patch.object(deploy.shutil,'which',return_value='/bin/true'),patch.object(deploy.subprocess,'run',side_effect=run),patch.object(deploy.socket,'create_connection',side_effect=OSError):
                deploy.deploy(args)
        return root,p,directory,calls,execute

    def test_plan_only_restores_existing_vm_map_and_never_runs_ansible(self):
        root,p,d,calls,execute=self.harness('vm',plan_only=True)
        existing=b'{"iso_installations":{"other":{"vm_id":131}}}\n'
        (root/'iso-install.auto.tfvars.json').write_bytes(existing)
        execute()
        self.assertEqual((root/'iso-install.auto.tfvars.json').read_bytes(),existing)
        self.assertFalse(any('apply' in c or c[0]=='ansible-playbook' for c in calls))
        self.assertFalse((d/'profile.json').exists())

    def test_two_stage_lxc_then_ansible(self):
        root,p,d,calls,execute=self.harness()
        execute()
        self.assertEqual(sum('apply' in c for c in calls),2)
        self.assertEqual(calls[-1][0],'ansible-playbook')
        final=json.loads((root/('application-'+p['name']+'.local.tf.json')).read_text())
        resource=next(iter(final['resource']['proxmox_virtual_environment_container'].values()))
        self.assertTrue(resource['started'])
        self.assertTrue(resource['features']['nesting'])
        self.assertTrue((d/'complete.json').exists())
        self.assertEqual((d/'inventory.yml').stat().st_mode & 0o777,0o600)

    def test_failed_guard_restores_config_without_apply(self):
        bad={'resource_changes':[change('existing',['delete'])]}
        root,p,d,calls,execute=self.harness(plans=[bad])
        with self.assertRaises(ValueError): execute()
        self.assertFalse((root/('application-'+p['name']+'.local.tf.json')).exists())
        self.assertFalse(any('apply' in c or c[0]=='ansible-playbook' for c in calls))

    def test_missing_guest_in_plan_aborts_before_apply(self):
        root,p,d,calls,execute=self.harness('vm',plans=[{'resource_changes':[]}])
        with self.assertRaisesRegex(ValueError,'did not declare'): execute()
        self.assertFalse(any('apply' in c for c in calls))

    def test_ansible_failure_keeps_managed_definition_for_retry(self):
        root,p,d,calls,execute=self.harness('vm',ansible_fails=True)
        with self.assertRaises(RuntimeError): execute()
        self.assertTrue((root/'iso-install.auto.tfvars.json').exists())
        self.assertTrue((d/'profile.json').exists())
        self.assertFalse((d/'complete.json').exists())

    def test_repeat_runs_ansible_without_hardware_changes(self):
        root,p,d,calls,execute=self.harness('vm',owned=True,plans=[{'resource_changes':[]}])
        (root/'iso-install.auto.tfvars.json').write_text(json.dumps({'iso_installations':{p['name']:deploy.vm_spec(p)}}))
        execute()
        self.assertEqual(calls[-1][0],'ansible-playbook')

    def test_existing_guest_without_workflow_record_is_rejected(self):
        root,p,d,calls,execute=self.harness('vm',owned=True)
        (d/'profile.json').unlink()
        with self.assertRaisesRegex(ValueError,'not created by this workflow'): execute()
        self.assertFalse(any('apply' in c or c[0]=='ansible-playbook' for c in calls))


if __name__=='__main__':
    unittest.main()
