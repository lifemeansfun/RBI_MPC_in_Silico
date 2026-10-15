"""Offline review harness: no dotenv traversal, provider transport, or writes outside outputs."""
import os,sys,socket
from pathlib import Path
ROOT=Path.cwd(); OUT=ROOT/'peer_review_output'
sys.path.insert(0,str(ROOT))
import dotenv
dotenv.load_dotenv=lambda *a,**k: False
dotenv.find_dotenv=lambda *a,**k: ''
def no_network(*a,**k): raise RuntimeError('Review forbids network/provider transport')
socket.socket.connect=no_network
socket.create_connection=no_network

def audit(event,args):
    if event=='open':
        path,mode,flags=args
        if isinstance(path,(str,bytes,os.PathLike)) and (flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
            p=Path(os.fsdecode(path)).absolute()
            if str(p) != '/dev/null' and not p.is_relative_to(OUT): raise RuntimeError('Review write outside output forbidden: '+str(p))
sys.addaudithook(audit)
