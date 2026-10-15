import guard,csv,json
rows=list(csv.DictReader(open('research/source_ledgers/expanded_panel_oct08/member_ballot_ledger.csv')))
for r in rows:
    if (r['decision_date'],r['member_id']) in [('2025-08-06','saugata_bhattacharya'),('2026-02-06','nagesh_kumar')]:
        print(json.dumps({k:r[k] for k in ['decision_date','member_id','explicit_formal_stance_vote','formal_stance_evidence_basis','formal_stance_excerpts']}))
