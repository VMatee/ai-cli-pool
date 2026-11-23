"""End-to-end isolated tests (no real accounts, secrets, or network)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = Path(__file__).resolve().parents[1] / "aifull.py"

FAKE_CLI = r'''import json, os, pathlib, re, sys, uuid, time
provider=sys.argv[1]
args=sys.argv[2:]
folder=pathlib.Path(os.environ['CLAUDE_CONFIG_DIR' if provider=='claude' else 'CODEX_HOME'])
folder.mkdir(parents=True, exist_ok=True)
record=pathlib.Path(os.environ['MOCK_LOG'])
with record.open('a',encoding='utf-8') as f:
    f.write(json.dumps({'provider':provider,'args':args,'profile':str(folder)})+'\n')
if (provider=='claude' and args[:2]==['auth','login']) or (provider=='codex' and args==['login']):
    (folder/'logged').write_text('yes')
    sys.exit(0)
if (provider=='claude' and args[:2]==['auth','status']) or (provider=='codex' and args[:2]==['login','status']):
    print('authenticated' if (folder/'logged').is_file() else 'not authenticated')
    sys.exit(0 if (folder/'logged').is_file() else 1)
if provider=='claude':
    slug=re.sub(r'[^A-Za-z0-9]','-',os.getcwd())
    dest=folder/'projects'/slug
    dest.mkdir(parents=True, exist_ok=True)
    if '--resume' in args and '--fork-session' not in args:
        session=pathlib.Path(args[args.index('--resume')+1])
    else:
        session=dest/(str(uuid.uuid4())+'.jsonl')
    with session.open('a') as f:f.write(json.dumps({'args':args,'cwd':os.getcwd()})+'\n')
else:
    dest=folder/'sessions'/'2026'/'11'/'23'
    dest.mkdir(parents=True,exist_ok=True)
    if 'resume' in args:
        sid=args[args.index('resume')+1]
        session=next(p for p in dest.glob('rollout-*.jsonl') if sid in p.name)
    else:
        sid=str(uuid.uuid4())
        session=dest/('rollout-2026-11-23T12-00-00-'+sid+'.jsonl')
        with session.open('w') as f:
            f.write(json.dumps({'type':'session_meta','payload':{'id':sid,'cwd':os.getcwd()}})+'\n')
    with session.open('a') as f:f.write(json.dumps({'type':'message','args':args})+'\n')
'''

ACCOUNTS = [
    {"provider":p,"account":("claude" if p=="claude" else "account")+str(i),
     "status":"ready", "headroom": 70 if i==2 else 35,
     "fiveHour":{"remainingPercent": 70 if i==2 else 35}, "weekly":{"remainingPercent":90}}
    for p in ("claude","codex") for i in (1,2,3)
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!='/api/accounts':
            self.send_error(404)
            return
        body=json.dumps(self.server.payload).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self,*_):
        pass


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.project=self.root/'example'
        self.project.mkdir()
        self.fake=self.root/'fake_cli.py'
        self.fake.write_text(FAKE_CLI,encoding='utf-8')
        self.mock_log=self.root/'invocations.jsonl'
        self.mock_log.write_text('')
        self.server=ThreadingHTTPServer(('127.0.0.1',0), Handler)
        self.server.daemon_threads = True
        self.server.payload={'recommended':{'claude':'claude:claude2','codex':'codex:account2'},'accounts':ACCOUNTS}
        worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cfg=self.root/'config.json'
        self.state=self.root/'state'
        self.env=os.environ.copy()
        self.env.update({'AIFULL_CONFIG':str(self.cfg),'AIFULL_STATE_DIR':str(self.state),'AIFULL_HOME':str(self.root/'home'),'MOCK_LOG':str(self.mock_log)})
        self.run_cmd('init','--yolo')
        cfg=json.loads(self.cfg.read_text())
        cfg['dashboard_url']=f"http://127.0.0.1:{self.server.server_address[1]}/api/accounts"
        for provider in ('claude','codex'):
            cfg['providers'][provider]['command']=[sys.executable,str(self.fake),provider]
        self.cfg.write_text(json.dumps(cfg),encoding='utf-8')

    def run_cmd(self,*argv,ok=True):
        proc=subprocess.run([sys.executable,str(APP),*argv],cwd=self.project,env=self.env,
                            capture_output=True,text=True,timeout=15)
        if ok:
            self.assertEqual(proc.returncode,0,(proc.stdout,proc.stderr))
        return proc

    def entries(self,provider=None):
        items=[json.loads(line) for line in self.mock_log.read_text().splitlines()]
        return [row for row in items if row['provider']==provider] if provider else items

    def project_state(self):
        states=list(self.state.glob('*.json'))
        self.assertEqual(len(states),1)
        return json.loads(states[0].read_text())

    def test_default_config_six_profiles(self):
        cfg=json.loads(self.cfg.read_text())
        for p in ('claude','codex'):
            self.assertEqual(len(cfg['providers'][p]['profiles']),3)
        self.assertTrue(cfg['yolo'])

    def test_claude_auto_resume_and_fork(self):
        proc=self.run_cmd('claude')
        self.assertIn('account 2',proc.stdout)
        first=self.project_state()['sessions']['claude']['session']
        self.assertTrue(Path(first).is_file())
        self.run_cmd('claude')
        self.assertIn('--resume',self.entries('claude')[-1]['args'])
        proc=self.run_cmd('claude','3')
        self.assertIn('Forking Claude transcript',proc.stdout)
        self.assertIn('--fork-session',self.entries('claude')[-1]['args'])
        self.assertIn('--dangerously-skip-permissions',self.entries('claude')[-1]['args'])
        state=self.project_state()['sessions']['claude']
        self.assertEqual(state['slot'],'3')
        self.assertNotEqual(state['session'],first)
        self.assertTrue(Path(state['session']).exists())

    def test_codex_auto_resume_and_switch(self):
        self.run_cmd('codex')
        first=self.project_state()['sessions']['codex']['session']
        self.run_cmd('codex')
        self.assertIn('resume',self.entries('codex')[-1]['args'])
        self.assertIn(first,self.entries('codex')[-1]['args'])
        self.run_cmd('handoff')
        target=self.project/'.ai-cli-pool-handoff.md'
        self.assertTrue(target.is_file())
        self.run_cmd('codex','1')
        last=self.entries('codex')[-1]['args']
        self.assertNotIn('resume',last)
        self.assertIn('--dangerously-bypass-approvals-and-sandbox',last)
        self.assertIn('.ai-cli-pool-handoff.md',last[-1])
        new=self.project_state()['sessions']['codex']
        self.assertEqual(new['slot'],'1')
        self.assertNotEqual(new['session'],first)

    def test_both_providers_and_independent_sessions(self):
        self.run_cmd('claude')
        self.run_cmd('codex')
        obj=self.project_state()['sessions']
        self.assertEqual(obj['claude']['slot'],'2')
        self.assertEqual(obj['codex']['slot'],'2')
        self.assertEqual(self.project_state()['active']['provider'],'codex')
        self.run_cmd('status')
        self.assertIn('CLAUDE',self.run_cmd('status').stdout)
        self.assertIn('CODEX',self.run_cmd('status').stdout)

    def test_login_all_and_auth(self):
        self.run_cmd('login-all')
        self.assertEqual(len(self.entries()),6)
        self.run_cmd('auth','claude','all')
        self.run_cmd('auth','codex','all')
        self.assertEqual(len(self.entries()),12)

    def test_mode_toggle_and_forwarding(self):
        self.run_cmd('mode','safe')
        self.run_cmd('claude','1','--','--model','sonnet')
        args=self.entries('claude')[-1]['args']
        self.assertNotIn('--dangerously-skip-permissions',args)
        self.assertEqual(args[-2:],['--model','sonnet'])
        self.run_cmd('mode','yolo')
        self.run_cmd('codex','3','--','-m','gpt-test')
        args=self.entries('codex')[-1]['args']
        self.assertIn('--dangerously-bypass-approvals-and-sandbox',args)
        self.assertEqual(args[-2:],['-m','gpt-test'])

    def test_quota_unavailable_uses_prior_slot(self):
        self.run_cmd('claude','3')
        cfg=json.loads(self.cfg.read_text())
        cfg['dashboard_url']='http://127.0.0.1:1/api/accounts'
        self.cfg.write_text(json.dumps(cfg))
        p=self.run_cmd('claude')
        self.assertIn('account 3',p.stdout)
        self.assertIn('Quota dashboard unavailable',p.stderr)
        self.run_cmd('codex')  # First-use fallback slot1
        self.assertIn('account 1',self.run_cmd('codex').stdout)

    def test_quota_limited_blocks_auto_but_manual_works(self):
        self.server.payload={'recommended':{},'accounts':[{**x,'status':'limited'} for x in ACCOUNTS]}
        p=self.run_cmd('claude',ok=False)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('no healthy claude',p.stderr)
        self.run_cmd('claude','1')

    def test_new_session(self):
        self.run_cmd('claude','1')
        first=self.project_state()['sessions']['claude']['session']
        self.run_cmd('claude','new')
        self.assertNotEqual(self.project_state()['sessions']['claude']['session'],first)

    def test_handoff_preserves_existing(self):
        self.run_cmd('handoff')
        handoff=self.project/'.ai-cli-pool-handoff.md'
        handoff.write_text('keep existing')
        proc=self.run_cmd('handoff')
        self.assertIn('NOT overwritten',proc.stdout)
        self.assertEqual(handoff.read_text(),'keep existing')


if __name__=='__main__':
    unittest.main()
