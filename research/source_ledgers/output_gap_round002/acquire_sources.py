"""Acquire exact primary-source responses into immutable batch destinations."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import hashlib, json, sys, concurrent.futures

root=Path(__file__).resolve().parent
catalog_path=Path(sys.argv[1])
catalog=json.loads(catalog_path.read_text())
out=root/'acquisition'/sys.argv[2]
out.mkdir(parents=True,exist_ok=False)
(out/'raw').mkdir()
allowed={'www.mospi.gov.in','mospi.gov.in','api.mospi.gov.in','www.rbi.org.in','rbi.org.in','rbidocs.rbi.org.in','systemhealth.rbi.org.in'}
def fetch(row):
    record={**row,'retrieved_at_utc':datetime.now(timezone.utc).isoformat()}
    try:
        if urlparse(row['url']).hostname not in allowed: raise ValueError('Unapproved primary host')
        req=Request(row['url'],headers={'User-Agent':'Research-vintage-audit/1.0','Accept-Encoding':'identity'})
        with urlopen(req,timeout=35) as response:
            body=response.read(); final=response.geturl()
            record.update(status=response.status,final_url=final,response_headers=dict(response.headers))
        path=out/'raw'/row['filename']
        path.write_bytes(body)
        record.update(local_file=str(path.relative_to(root)),bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),
                      primary_final_host=urlparse(final).hostname in allowed,acquired=True)
    except Exception as exc:
        record.update(acquired=False,error_type=type(exc).__name__,error=str(exc))
    (out/(row['id']+'.metadata.json')).write_text(json.dumps(record,indent=2)+'\n')
    return record
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: records=list(pool.map(fetch,catalog))
receipt={'catalog_file':str(catalog_path),'catalog_sha256':hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
         'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'sources':records}
(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps([{k:v for k,v in row.items() if k not in ('response_headers',)} for row in records],indent=2))
