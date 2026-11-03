"""Real-browser benchmark. Start the app first; Python standard library only."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess

root=Path(__file__).resolve().parents[1]
artifacts=root/os.environ.get('STEPFUN_BENCH_DIR','evidence/raw')
artifacts.mkdir(parents=True,exist_ok=True)
node=shutil.which('node')
cli=root/'node_modules/@playwright/cli/playwright-cli.js'
sessions=('stepfun-bench-gpu','stepfun-bench-wasm')
report={'startedAt':datetime.datetime.now().astimezone().isoformat(),'status':'running','results':[]}

def save():
    (artifacts/'benchmark-state.json').write_bytes(json.dumps(report,ensure_ascii=False,indent=2).encode())

def command(session,args,label):
    result=subprocess.run([node,str(cli),'-s='+session,*args],cwd=root,capture_output=True,
                          encoding='utf-8',timeout=900)
    (artifacts/(label+'.txt')).write_bytes((result.stdout+'\n'+result.stderr).encode())
    if result.returncode:raise RuntimeError(label+': '+result.stdout[-1500:])
    return result.stdout

def value(session,kind,script,label):
    text=command(session,[kind,script],label)
    if '### Result\n' not in text:raise RuntimeError('Missing browser result: '+label)
    return json.JSONDecoder().raw_decode(text.split('### Result\n',1)[1].lstrip())[0]

try:
    for index,session in enumerate(sessions):
        launch={'headless':True}
        if os.environ.get('CHROME_EXECUTABLE'):launch['executablePath']=os.environ['CHROME_EXECUTABLE']
        else:launch['channel']='chrome'
        if index:launch['args']=['--disable-features=WebGPU','--disable-gpu']
        config={'browser':{'browserName':'chromium','isolated':True,'launchOptions':launch,
                           'contextOptions':{'viewport':{'width':1440,'height':1100}}}}
        path=artifacts/(session+'-config.json');path.write_bytes(json.dumps(config).encode())
        command(session,['open','http://localhost:'+os.environ.get('PORT','18380'),'--config',str(path)],session+'-open')
        setup='''async(page)=>{
          page.__stepfunAudit=[];
          await page.context().route('**/*',route=>{
            const r=route.request(),u=new URL(r.url());
            page.__stepfunAudit.push({url:r.url(),method:r.method(),type:r.resourceType()});
            return u.origin===new URL(page.url()).origin?route.continue():route.abort();
          });
          return {browserVersion:page.context().browser().version(),cacheKeys:await page.evaluate(()=>caches.keys())};
        }'''
        report[session]=value(session,'run-code',setup,session+'-setup')
    cases=[(sessions[0],'fp32-wasm',1,'baseline-fp32-wasm'),
           (sessions[0],'q8-wasm',1,'int8-wasm-batch1'),
           (sessions[0],'q8-wasm',4,'int8-wasm-batch4'),
           (sessions[0],'auto',4,'fp16-webgpu-batch4'),
           (sessions[1],'auto',4,'automatic-wasm-fallback')]
    for session,profile,batch,label in cases:
        report['phase']=label;save()
        script='async()=>await(await import("/benchmark.js")).run('+json.dumps(profile)+','+str(batch)+','+json.dumps(label)+')'
        result=value(session,'eval',script,label)
        path=artifacts/(label+'.json');path.write_bytes(json.dumps(result,ensure_ascii=False,indent=2).encode())
        assert len(result['queries'])==36 and result['corpusCount']==24
        expected='webgpu' if label=='fp16-webgpu-batch4' else 'wasm'
        assert result['state']['device']==expected,(label,result['state']['device'])
        assert result['state']['dtype']==('fp32' if profile=='fp32-wasm' else 'fp16' if expected=='webgpu' else 'q8')
        if label=='automatic-wasm-fallback':assert result['state']['reason']
        report['results'].append({'label':label,'summary':result['summary'],
                                  'dtype':result['state']['dtype'],'device':result['state']['device'],
                                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        save()
    base=report['results'][0]['summary']
    assert base['recallAt5']>=.75 and base['ndcgAt5']>=.65
    for item in report['results'][1:]:
        assert item['summary']['recallAt5']>=base['recallAt5']-.05
        assert item['summary']['ndcgAt5']>=base['ndcgAt5']-.05
    for session in sessions:
        audit=value(session,'run-code','async(page)=>page.__stepfunAudit',session+'-network')
        origin='http://localhost:'+os.environ.get('PORT','18380')+'/'
        assert all(item['url'].startswith(origin) for item in audit)
        (artifacts/(session+'-network.json')).write_bytes(json.dumps(audit,indent=2).encode())
        command(session,['screenshot','--filename='+str(artifacts/(session+'.png'))],session+'-screenshot')
    report['status']='passed'
except Exception as error:
    report['status']='failed';report['error']=repr(error);raise
finally:
    save()
    for session in sessions:
        subprocess.run([node,str(cli),'-s='+session,'close'],cwd=root,capture_output=True,timeout=30)
