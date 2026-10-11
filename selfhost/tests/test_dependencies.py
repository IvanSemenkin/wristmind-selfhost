import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dependencies', Path(__file__).resolve().parents[1] / 'dependencies.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DependenciesTest(unittest.TestCase):
    def test_compose_minimum_and_new_major_versions(self):
        for version, ready in [('2.23.9',False),('v2.24.0',True),('5.6.0',True),('',False)]:
            with patch.object(m,'probe',return_value=subprocess.CompletedProcess([],0,version,'')):
                self.assertEqual(m.compose_ready(),ready)

    def test_valid_os_and_no_execution_from_os_release(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'os-release'
            path.write_text('ID=ubuntu\nVERSION_CODENAME=noble\n')
            self.assertEqual(m.system(path),('ubuntu','noble'))
            path.write_text('ID=arch\nVERSION_CODENAME="$(touch nope)"\n')
            with self.assertRaises(ValueError): m.system(path)
            self.assertFalse((Path(temp)/'nope').exists())

    def test_ready_system_is_not_modified(self):
        with patch.object(m,'ready',return_value=True),patch.object(m,'run') as run:
            m.ensure();run.assert_not_called()

    def test_new_system_installs_from_official_repo_and_starts_service(self):
        calls=[]
        def which(name): return None if name=='docker' else '/usr/bin/'+name
        def probe(args):
            return subprocess.CompletedProcess(args,1,'','')
        with patch.object(m,'ready',side_effect=[False,True]),patch.object(m.os,'geteuid',return_value=0),patch.object(m,'system',return_value=('debian','bookworm')),patch.object(m.shutil,'which',side_effect=which),patch.object(m,'probe',side_effect=probe),patch.object(m,'compose_ready',return_value=False),patch.object(m,'repository') as repo,patch.object(m,'run',side_effect=calls.append):
            m.ensure()
        repo.assert_called_once_with('debian','bookworm')
        package=next(call for call in calls if 'docker-ce' in call)
        self.assertIn('docker-compose-plugin',package)
        self.assertIn('--no-remove',package)
        self.assertIn(['systemctl','enable','--now','docker'],calls)
        self.assertFalse(any('remove' in call or 'purge' in call or 'prune' in call for call in calls))

    def test_existing_engine_only_gets_missing_plugin(self):
        calls=[]
        with patch.object(m,'ready',side_effect=[False,True]),patch.object(m.os,'geteuid',return_value=0),patch.object(m,'system',return_value=('ubuntu','noble')),patch.object(m.shutil,'which',return_value='/usr/bin/tool'),patch.object(m,'compose_ready',return_value=False),patch.object(m,'repository'),patch.object(m,'probe',return_value=subprocess.CompletedProcess([],0,'','')),patch.object(m,'run',side_effect=calls.append):
            m.ensure()
        self.assertIn(['apt-get','install','-y','--no-remove','docker-compose-plugin','docker-buildx-plugin'],calls)
        self.assertFalse(any('docker-ce' in call or 'systemctl' in call for call in calls))

    def test_conflicting_runtime_is_not_replaced(self):
        def which(name): return None if name=='docker' else '/usr/bin/'+name
        with patch.object(m,'ready',return_value=False),patch.object(m.os,'geteuid',return_value=0),patch.object(m,'system',return_value=('debian','bookworm')),patch.object(m.shutil,'which',side_effect=which),patch.object(m,'compose_ready',return_value=False),patch.object(m,'probe',return_value=subprocess.CompletedProcess([],0,'install ok installed','')),patch.object(m,'run') as run,patch.object(m,'repository') as repo:
            with self.assertRaisesRegex(ValueError,'существующий'): m.ensure()
            repo.assert_not_called()
            self.assertFalse(any('docker-ce' in call.args[0] for call in run.call_args_list))
