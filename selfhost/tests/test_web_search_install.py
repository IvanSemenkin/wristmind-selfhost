import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
from unittest.mock import patch, AsyncMock
import asyncio
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'selfhost'))
sys.path.insert(0,str(ROOT/'server/src'))
import web_search
from wristmind_server import web_search_setup

@pytest.mark.parametrize('existing_secret',['','keep-this-secret'])
def test_existing_install_configured_in_one_command(tmp_path,existing_secret):
    original='OTHER=test-value\nCOMPOSE_PROFILES=telegram\n'
    if existing_secret: original+='SEARXNG_SECRET='+existing_secret+'\n'
    (tmp_path/'.env').write_text(original)
    values={'COMPOSE_PROFILES':'telegram','SEARXNG_SECRET':existing_secret}
    calls=[]
    with patch.object(web_search.installer,'manifest_at',return_value={'phase':'ready','project':'wristmind-123456789abc'}),patch.object(web_search.installer,'validate_saved',return_value=values),patch.object(web_search.installer,'run_step',side_effect=lambda command,*args:calls.append(command)),patch.object(web_search.installer,'search_health') as health:
        web_search.install(tmp_path)
    configured=web_search.installer.read_env(tmp_path)
    assert configured['OTHER']=='test-value'
    assert configured['COMPOSE_PROFILES']=='telegram,search'
    assert configured['WRISTMIND_SEARXNG_URL']=='http://searxng:8080'
    assert configured['SEARXNG_SECRET']==existing_secret if existing_secret else len(configured['SEARXNG_SECRET'])==64
    assert (tmp_path/'.env').stat().st_mode & 0o777 == 0o600
    health.assert_called_once()
    assert len(calls)==2 and calls[1][-1]=='wristmind_server.web_search_setup'
    assert not any('down' in call or '-v' in call for call in calls)


def test_failure_restores_exact_original_configuration(tmp_path):
    original='# preserve comment\nOTHER=private-test-value\n'
    (tmp_path/'.env').write_text(original)
    with patch.object(web_search.installer,'manifest_at',return_value={'phase':'ready','project':'wristmind-123456789abc'}),patch.object(web_search.installer,'validate_saved',return_value={}),patch.object(web_search.installer,'run_step') as run,patch.object(web_search.installer,'search_health',side_effect=RuntimeError('not ready')):
        with pytest.raises(RuntimeError): web_search.install(tmp_path)
        assert run.call_count==2
    assert (tmp_path/'.env').read_text()==original


def test_existing_external_search_is_not_overwritten(tmp_path):
    with patch.object(web_search.installer,'manifest_at',return_value={'phase':'ready'}),patch.object(web_search.installer,'validate_saved',return_value={'WRISTMIND_SEARXNG_URL':'https://other.example'}),patch.object(web_search.installer,'run_step') as run:
        (tmp_path/'.env').write_text('OTHER=value\n')
        with pytest.raises(ValueError,match='другой'): web_search.install(tmp_path)
        run.assert_not_called()


def test_cli_enables_only_web_search():
    values={'selfhost_features':{'rag':False,'voice':False},'model_roles':{'vision':'old'},'models':[]}
    with patch.object(web_search_setup,'locked_config',new=AsyncMock()),patch.object(web_search_setup,'snapshot',return_value=values),patch.object(web_search_setup,'persist',new=AsyncMock()) as persist:
        asyncio.run(web_search_setup.setup(SimpleNamespace(selfhost_enabled=True,searxng_url='http://searxng:8080'),object()))
        persist.assert_awaited_once()
    assert values['selfhost_features']=={'rag':False,'voice':False,'web_search':True}
    assert values['model_roles']=={'vision':'old'}


def test_compose_reads_automatic_profile_from_install_env(tmp_path):
    config=tmp_path/'.env'
    config.write_text('COMPOSE_PROFILES=search\nPOSTGRES_PASSWORD=test\nWRISTMIND_BOOTSTRAP_SECRET=test\nWRISTMIND_TOKEN_PEPPER=test\nSEARXNG_SECRET=test\nWRISTMIND_SEARXNG_URL=http://searxng:8080\n')
    result=subprocess.run(['docker','compose','--env-file',str(config),'-f',str(ROOT/'compose.yaml'),'config','--format','json'],env=web_search.installer.docker_environment(),capture_output=True,text=True,check=True)
    services=json.loads(result.stdout)['services']
    assert 'searxng' in services and not services['searxng'].get('ports')
    assert services['api']['environment']['WRISTMIND_SEARXNG_URL']=='http://searxng:8080'
