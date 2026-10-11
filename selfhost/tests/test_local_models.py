"""Local search installation and automatic assignment without downloads."""
from pathlib import Path
from types import SimpleNamespace
import asyncio
import sys
from unittest.mock import patch, AsyncMock
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'selfhost'))
sys.path.insert(0, str(ROOT / 'server/src'))
import local_models
from wristmind_server import local_model_setup as setup
from wristmind_server.provider_connections import ProviderConnection


def test_install_commands_include_automatic_assignment(tmp_path):
    calls = []
    data = {'phase':'ready','project':'wristmind-123456789abc'}
    with patch.object(local_models.installer,'manifest_at',return_value=data), patch.object(local_models.installer,'validate_saved',return_value={}), patch.object(local_models,'inspect_resources',return_value={'cpu':4,'ram_gib':8,'disk_free_gib':20}), patch.object(local_models.installer,'run_step',side_effect=lambda command,*args:calls.append(command)):
        local_models.install(tmp_path,'embedding',True)
    assert len(calls) == 3
    assert 'ollama' in calls[0] and '--wait' in calls[0]
    assert calls[1][-3:] == ['ollama','pull','embeddinggemma']
    assert calls[2][-4:] == ['api','python','-m','wristmind_server.local_model_setup']
    assert all('wristmind-123456789abc' in call for call in calls)
    assert not any('down' in call or '-v' in call for call in calls)

@pytest.mark.parametrize('role',['vision','speech','text'])
def test_non_search_roles_cannot_be_installed(tmp_path,role):
    with patch.object(local_models.installer,'run_step') as run:
        with pytest.raises(ValueError,match='только поиск'): local_models.install(tmp_path,role,True)
        run.assert_not_called()


def test_insufficient_resources_stop_before_docker(tmp_path):
    with patch.object(local_models.installer,'manifest_at',return_value={'phase':'ready'}), patch.object(local_models.installer,'validate_saved',return_value={}), patch.object(local_models,'inspect_resources',return_value={'cpu':1,'ram_gib':2,'disk_free_gib':20}), patch.object(local_models.installer,'run_step') as run:
        with pytest.raises(ValueError,match='RAM'): local_models.install(tmp_path,'embedding',True)
        run.assert_not_called()


def test_assignment_is_idempotent_preserves_other_roles_and_models():
    values={'providers':[], 'models':[{'id':'old','provider':'old','roles':['text']}], 'model_roles':{'vision':'remote-image','speech':'remote-voice'},'default_model_id':'old'}
    setup.configure(values); setup.configure(values)
    assert len(values['providers']) == 1 and len(values['models']) == 2
    assert values['model_roles']['embedding'] == setup.PROVIDER + ':embeddinggemma'
    assert values['model_roles']['vision'] == 'remote-image'
    assert values['model_roles']['speech'] == 'remote-voice'
    assert values['default_model_id'] == 'old'
    provider=ProviderConnection.model_validate(values['providers'][0])
    assert provider.allow_local and not provider.api_key.get_secret_value()


def test_failed_probe_cannot_persist_settings():
    settings=SimpleNamespace(selfhost_enabled=True,mock_providers=False)
    with patch.object(setup,'embeddings',new=AsyncMock(side_effect=RuntimeError('unavailable'))), patch.object(setup,'persist',new=AsyncMock()) as persist, patch.object(setup,'locked_config',new=AsyncMock()) as lock:
        with pytest.raises(RuntimeError): asyncio.run(setup.setup(settings,object()))
        persist.assert_not_awaited(); lock.assert_not_awaited()


def test_successful_probe_assigns_without_user_model_selection():
    settings=SimpleNamespace(selfhost_enabled=True,mock_providers=False)
    values={'providers':[],'models':[]}
    with patch.object(setup,'embeddings',new=AsyncMock(return_value=[[1,0]])), patch.object(setup,'snapshot',return_value=values), patch.object(setup,'persist',new=AsyncMock()) as persist, patch.object(setup,'locked_config',new=AsyncMock()):
        asyncio.run(setup.setup(settings,object()))
        persist.assert_awaited_once()
        assert values['model_roles']['embedding'] == setup.PROVIDER + ':embeddinggemma'


def test_local_profile_is_private_and_has_no_vision_or_speech_service():
    import os,json,subprocess
    env={**os.environ,'POSTGRES_PASSWORD':'test','WRISTMIND_BOOTSTRAP_SECRET':'test','WRISTMIND_TOKEN_PEPPER':'test'}
    result=subprocess.run(['docker','compose','--env-file','/dev/null','-f',str(ROOT/'compose.yaml'),'--profile','local-ai','config','--format','json'],cwd=ROOT,env=env,capture_output=True,text=True,check=True)
    services=json.loads(result.stdout)['services']
    assert not services['ollama'].get('ports')
    assert not services['ollama'].get('privileged')
    assert services['ollama']['environment']['OLLAMA_NO_CLOUD'] == '1'
    assert 'local-speech' not in services
