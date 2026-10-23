"""Alpha.76: build while running, release directories with link switch, pre-update requirements."""
import json
import os
import pwd
import subprocess
from pathlib import Path

import pytest

from pengucoach.maintenance.drivers import RELEASE_MARKER, Driver
from pengucoach.maintenance.engine import Engine, atomic_json, utc

from tests.test_alpha73_maintenance import PASSWORD, host  # noqa: F401  (fixture reuse)


def update(host, monkeypatch, tmp_path, commit='b'*40, files=None):
    source=tmp_path/('release-'+commit[:6]);source.mkdir(exist_ok=True)
    for name,content in (files or {}).items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    monkeypatch.setattr(host.engine,'fetch_source',lambda driver:(source,commit,{'source':'release','tag':'v0.1.0-alpha.76','version':'0.1.0-alpha.76','newer':True}))
    return host.engine.submit({'operation':'update','confirmation':'UPDATE'},asynchronous=False)


def plain(calls):return [c for c in calls if isinstance(c,str)]


def test_new_version_is_built_before_anything_stops(host,monkeypatch,tmp_path):
    job=update(host,monkeypatch,tmp_path)
    assert job['status']=='succeeded',job
    calls=plain(host.shared['calls'])
    built='build_release' if host.config['deployment']=='native' else 'build'
    assert calls.index(built)<calls.index('maintenance_on')<calls.index('stop')
    assert host.shared['head']=='b'*40


def test_native_release_directory_replaces_the_legacy_checkout_behind_a_link(host,monkeypatch,tmp_path):
    if host.config['deployment']!='native':pytest.skip('native layout')
    project=Path(host.config['project'])
    assert project.is_dir() and not project.is_symlink()
    assert update(host,monkeypatch,tmp_path)['status']=='succeeded'
    releases=Path(str(project)+'-releases')
    assert project.is_symlink() and project.resolve()==(releases/('b'*12)).resolve()
    legacy=releases/('legacy-'+'a'*12)
    assert (legacy/'.git').is_dir()  # previous version kept, ready for a quick return
    assert json.loads((project/RELEASE_MARKER).read_text())['commit']=='b'*40
    assert host.engine.updatable()


@pytest.mark.parametrize('failure',['migrate','step','health'])
def test_failure_after_switch_points_back_without_rebuilding(host,monkeypatch,tmp_path,failure):
    if host.config['deployment']!='native':pytest.skip('native layout')
    before=json.loads(json.dumps(host.shared['db']['pengucoach']))
    host.shared['fail'].add(failure)
    files={'install/host-steps/076-x.all.sh':'#'} if failure=='step' else None
    job=update(host,monkeypatch,tmp_path,files=files)
    assert job['status']=='failed' and job['rolled_back'] and not job.get('recovery_required'),job
    project=Path(host.config['project'])
    assert project.resolve().name=='legacy-'+'a'*12 and host.shared['head']=='a'*40
    assert not (Path(str(project)+'-releases')/('b'*12)).exists()
    assert host.shared['db']=={'pengucoach':before} and not host.shared['paused']
    assert 'build' not in plain(host.shared['calls'])  # the previous version is not rebuilt


def test_failed_build_never_stops_services_or_enters_maintenance(host,monkeypatch,tmp_path):
    host.shared['fail'].add('build')
    job=update(host,monkeypatch,tmp_path)
    assert job['status']=='failed' and job['rolled_back'],job
    calls=plain(host.shared['calls'])
    assert 'stop' not in calls and 'start' not in calls and 'maintenance_on' not in calls
    assert host.shared['head']=='a'*40
    if host.config['deployment']=='docker':
        assert ('rollback_images',[{'tag':'api','id':'old-image'}]) in host.shared['calls']
    else:
        assert not (Path(host.config['project']+'-releases')/('b'*12)).exists()
    assert not host.engine.backups()  # nothing to roll back, so no safety backup was needed


def test_interrupted_update_after_switch_is_rolled_back_at_startup(host,monkeypatch,tmp_path):
    if host.config['deployment']!='native':pytest.skip('native layout')
    driver=host.factory(host.config,lambda _:None)
    job={'id':'f'*32,'status':'running','created_at':utc(),'operation':'update'}
    host.engine.save(job);work=host.engine.state/'work'/job['id'];work.mkdir()
    (work/'safety').mkdir();(work/'safety/database.pgdump').write_text(json.dumps(host.shared['db']['pengucoach']))
    old=str(driver.link_target())
    release=driver.prepare_release(tmp_path,'b'*40,'0.1.0-alpha.76')
    atomic_json(work/'transaction.json',{'mode':'release','stopped':True,'database_may_have_changed':True,'release':str(release),'old_target':old})
    driver.point_link(release);host.shared['db']['pengucoach']['schema']='new'
    Engine(host.config,host.factory).recover()
    assert Path(host.config['project']).resolve()==Path(old).resolve() and not release.exists()
    assert host.shared['db']['pengucoach']['schema']=='old'
    assert host.engine.jobs()[0]['rolled_back']


def test_old_releases_are_pruned_but_current_and_previous_stay(host,monkeypatch,tmp_path):
    if host.config['deployment']!='native':pytest.skip('native layout')
    for index,commit in enumerate(['b'*40,'c'*40,'d'*40,'e'*40]):
        assert update(host,monkeypatch,tmp_path,commit=commit)['status']=='succeeded'
        releases=Path(host.config['project']+'-releases')
        os.utime(releases/commit[:12],(1000+index,1000+index))
        if (releases/('legacy-'+'a'*12)).exists():os.utime(releases/('legacy-'+'a'*12),(900,900))
    names=sorted(p.name for p in releases.iterdir())
    assert names==['d'*12,'e'*12]


def test_real_driver_exports_release_and_switches_link_atomically(tmp_path):
    repo=tmp_path/'upstream';repo.mkdir()
    run=lambda *a:subprocess.run(['git','-c','user.email=t@t','-c','user.name=t',*a],cwd=repo,check=True,stdout=subprocess.PIPE,text=True).stdout.strip()
    run('init','-q');(repo/'pyproject.toml').write_text('[project]\nname="p"\nversion="0.1.0-alpha.76"\n');(repo/'app.py').write_text('print(1)')
    run('add','-A');run('commit','-qm','x');commit=run('rev-parse','HEAD')
    project=tmp_path/'opt/pengucoach';project.mkdir(parents=True);(project/'.git').mkdir();(project/'old.txt').write_text('legacy')
    user=pwd.getpwuid(os.getuid()).pw_name
    driver=Driver({'project':str(project),'environment':str(tmp_path/'env'),'data':str(tmp_path/'data'),'deployment':'native','user':user})
    driver.installed_commit=lambda:'a'*40
    release=driver.prepare_release(repo,commit,'0.1.0-alpha.76')
    assert (release/'app.py').read_text()=='print(1)' and not (release/'.git').exists()
    assert json.loads((release/RELEASE_MARKER).read_text())['commit']==commit
    assert driver.link_target()==tmp_path/'opt/pengucoach-releases'/('legacy-'+'a'*12)
    driver.point_link(release)
    assert project.is_symlink() and (project/'app.py').is_file()
    assert (tmp_path/'opt/pengucoach-releases'/('legacy-'+'a'*12)/'old.txt').read_text()=='legacy'
    assert Driver({'project':str(project),'environment':str(tmp_path/'env'),'data':str(tmp_path),'deployment':'native'}).installed_commit()==commit
    with pytest.raises(ValueError,match='UPDATE_RELEASE_ACTIVE'):driver.prepare_release(repo,commit,'x')
    driver.point_link(tmp_path/'opt/pengucoach-releases'/('legacy-'+'a'*12))
    assert (project/'old.txt').is_file()


REQUIREMENTS={'min_upgrade_from':'0.1.0-alpha.73','docker_compose_min':'2.24.0','python_min':'3.12.0','node_min':'20.0.0'}


@pytest.mark.parametrize('tools,installed,error',[
    ({'docker_compose':'2.20.2','python':'3.12.3','node':'22.1.0'},'0.1.0-alpha.75','DOCKER_COMPOSE_TOO_OLD:2.24.0'),
    ({'python':'3.11.2','node':'22.1.0'},'0.1.0-alpha.75','PYTHON_TOO_OLD:3.12.0'),
    ({'python':'3.12.3','node':'18.19.1'},'0.1.0-alpha.75','NODE_TOO_OLD:20.0.0'),
    ({},'0.1.0-alpha.70','UPDATE_REQUIRES_INTERMEDIATE:0.1.0-alpha.73'),
])
def test_unmet_requirements_stop_before_anything_changes(host,monkeypatch,tmp_path,tools,installed,error):
    if 'docker_compose' in tools and host.config['deployment']!='docker':tools={k:v for k,v in tools.items() if k!='docker_compose'}
    if 'docker_compose' not in tools and error.startswith('DOCKER'):pytest.skip('docker only')
    host.shared['tools']={k:v for k,v in tools.items() if (k=='docker_compose')==(host.config['deployment']=='docker')}
    if error.startswith(('PYTHON','NODE')) and host.config['deployment']!='native':pytest.skip('native only')
    monkeypatch.setattr(type(host.factory(host.config,lambda _:None)),'version',lambda self:installed)
    job=update(host,monkeypatch,tmp_path,files={'install/release-requirements.json':json.dumps(REQUIREMENTS)})
    assert job['status']=='failed' and job['error']==error,job
    calls=plain(host.shared['calls'])
    assert not {'prepare_release','build','build_release','stop','maintenance_on'}&set(calls)


def test_met_requirements_and_preview_report_checks(host,monkeypatch,tmp_path):
    host.shared['tools']={'docker_compose':'2.29.7'} if host.config['deployment']=='docker' else {'python':'3.12.3','node':'22.11.0'}
    job=update(host,monkeypatch,tmp_path,files={'install/release-requirements.json':json.dumps(REQUIREMENTS)})
    assert job['status']=='succeeded',job
    driver=host.factory(host.config,lambda _:None)
    checks=host.engine.requirement_checks(driver,REQUIREMENTS,'0.1.0-alpha.72')
    assert checks[0]=={'key':'upgrade_path','ok':False,'required':'0.1.0-alpha.73','actual':'0.1.0-alpha.72'}
    assert all(c['ok'] for c in checks[1:])


def test_shipped_requirements_file_is_valid_and_reachable_for_preview():
    value=json.loads(Path('install/release-requirements.json').read_text())
    assert set(value)<={'min_upgrade_from','docker_compose_min','python_min','node_min'}
    engine=Engine.__new__(Engine);engine.config={'repository':'https://github.com/Borderlane-HA/PenguCoach.git'}
    import urllib.request
    seen=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return json.dumps(value).encode()
    original=urllib.request.urlopen
    urllib.request.urlopen=lambda url,timeout:seen.append(url) or Response()
    try:assert engine.remote_requirements('v0.1.0-alpha.76')==value
    finally:urllib.request.urlopen=original
    assert seen==['https://raw.githubusercontent.com/Borderlane-HA/PenguCoach/v0.1.0-alpha.76/install/release-requirements.json']
    engine.config={'repository':'/srv/local/repo'}
    assert engine.remote_requirements('v1')is None
