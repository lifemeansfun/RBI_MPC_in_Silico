import subprocess,json,sys,datetime,os
from pathlib import Path
out=Path('peer_review_output'); name=sys.argv[1]; cmd=sys.argv[2:]
with (out/'commands.jsonl').open('a') as f:f.write(json.dumps({'time':datetime.datetime.now().isoformat(),'name':name,'argv':cmd})+'\n')
env={'PATH':'/usr/bin:/bin','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'};env['PYTHONDONTWRITEBYTECODE']='1';env['TMPDIR']=str(Path('peer_review_output/tmp').absolute());env['MPLCONFIGDIR']=str(Path('peer_review_output/mpl').absolute())
Path(env['TMPDIR']).mkdir(exist_ok=True)
r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env)
(out/(name+'.log')).write_bytes(r.stdout)
print(r.stdout.decode(errors='replace'));print('EXIT',r.returncode)
