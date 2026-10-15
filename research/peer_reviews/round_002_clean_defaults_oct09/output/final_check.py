from pathlib import Path
import json,hashlib,re
root=Path.cwd();out=root/'peer_review_output'
m=json.loads((root/'SNAPSHOT_SHA256.json').read_text())
bad=[p for p,h in m.items() if not (root/p).is_file() or hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
review=(out/'REVIEW.md').read_text()
links=re.findall(r'\]\(([^)]+)\)',review);missing=[x for x in links if not x.startswith('https://') and not (out/x).exists()]
result={'original_files':len(m),'original_mismatches':bad,'missing_review_links':missing,'terminal_verdict_count':review.count('Not fully elite research grade'),'last_line':review.strip().splitlines()[-1],'review_words':len(review.split())}
print(json.dumps(result,indent=2))
assert not bad and not missing and result['terminal_verdict_count']==1
(out/'final_check.json').write_text(json.dumps(result,indent=2)+'\n')
files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name not in ['OUTPUT_SHA256.json','final_check.log','commands.jsonl']}
(out/'OUTPUT_SHA256.json').write_text(json.dumps(files,indent=2)+'\n')
