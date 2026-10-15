from pathlib import Path
import concurrent.futures, datetime, hashlib, json, platform, subprocess, sys, urllib.request, urllib.error
base=Path(__file__).resolve().parent
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
run=base/('acquisition_'+stamp)
run.mkdir(exist_ok=False)
raw=run/'raw'; raw.mkdir()
textdir=run/'text'; textdir.mkdir()
sources=[
('ovn_1999','The Reliability of Output Gap Estimates in Real Time',['Athanasios Orphanides','Simon van Norden'],'1999-08','Federal Reserve FEDS 1999-38; working-paper version','https://www.federalreserve.gov/pubs/feds/1999/199938/199938pap.pdf'),
('hamilton_2017','Why You Should Never Use the Hodrick-Prescott Filter',['James D. Hamilton'],'2017-05-13','Author working paper; first dated 2016-07-30, revised 2017-05-13; journal version REStat 100(5), 2018, 831-843','https://econweb.ucsd.edu/~jhamilto/hp.pdf'),
('gruen_robinson_stone_2002','Output Gaps in Real Time: Are They Reliable Enough to Use for Monetary Policy?',['David Gruen','Tim Robinson','Andrew Stone'],'2002-09','Reserve Bank of Australia RDP 2002-06','https://www.rba.gov.au/publications/rdp/2002/pdf/rdp2002-06.pdf'),
('kamber_morley_wong_2016_legacy','Intuitive and Reliable Estimates of the Output Gap from a Beveridge-Nelson Filter',['Gunes Kamber','James Morley','Benjamin Wong'],'2016-09-20','BIS Working Paper 584; legacy URL may redirect to landing page','https://www.bis.org/publ/work584.pdf'),
('kamber_morley_wong_2016_pdf','Intuitive and Reliable Estimates of the Output Gap from a Beveridge-Nelson Filter',['Gunes Kamber','James Morley','Benjamin Wong'],'2016-09-20','BIS Working Paper 584; PDF href inspected on primary landing page','https://www.bis.org/publications/working-paper-584-intuitive-and-reliable-estimates-output-gap-beveridge-nelson-filter.pdf'),
('edge_rudd_2012','Real-Time Properties of the Federal Reserve\u2019s Output Gap',['Rochelle M. Edge','Jeremy B. Rudd'],'2012-12-03','Federal Reserve FEDS 2012-86','https://www.federalreserve.gov/pubs/feds/2012/201286/201286pap.pdf'),
('champagne_poulin_sekkel_2016','The Real-Time Properties of the Bank of Canada\u2019s Staff Output Gap Estimates',['Julien Champagne','Guillaume Poulin-Bellisle','Rodrigo Sekkel'],'2016-06','Bank of Canada Staff Working Paper 2016-28','https://www.bankofcanada.ca/wp-content/uploads/2016/06/swp2016-28.pdf'),
('eurostat_2009','ESS Guidelines on Seasonal Adjustment',['Eurostat, European Commission'],'2009-06-05','2009 edition; DOI 10.2785/20152','https://ec.europa.eu/eurostat/documents/3859598/5910549/KS-RA-09-006-EN.PDF.pdf/0a9893a6-3e69-45c4-8328-6fc5a3497c13?t=1414781563000'),
('eurostat_2024','ESS Guidelines on Seasonal Adjustment',['Eurostat, European Commission'],'2024-06-13','2024 edition; DOI 10.2785/705102','https://ec.europa.eu/eurostat/documents/3859598/19355229/KS-GQ-24-012-EN-N.pdf'),
('census_x13_2017','X-13ARIMA-SEATS Reference Manual: Accessible HTML Output Version',['Time Series Research Staff, U.S. Census Bureau'],'2017-01-18','Version 1.1 manual; freeze actual executable/version separately if used','https://www.census.gov/content/dam/Census/library/working-papers/2017/adrm/docx13ashtml.pdf'),
('imf_qna_2017','Quarterly National Accounts Manual 2017 Edition',['International Monetary Fund, Statistics Department'],'2017','ISBN 9781475589870; retrieved source version publication day unavailable in this record','https://www.imf.org/external/pubs/ft/qna/pdf/2017/QNAManual2017text.pdf'),
('imf_qna_2017_ch7','Quarterly National Accounts Manual 2017 Edition: Chapter 7 Seasonal Adjustment',['International Monetary Fund, Statistics Department'],'2017','Primary IMF eLibrary chapter; PDF/index returned web 403, preserve failure','https://www.elibrary.imf.org/display/book/9781475589870/ch007.xml')]
def fetch(item):
    key,title,authors,published,version,url=item
    d=dict(id=key,title=title,authors=authors,publication_date_as_verified=published,version=version,requested_url=url,retrieved_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),publication_date_is_data_vintage=False)
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (methodological-source archival research)','Accept':'application/pdf,text/html;q=0.9,*/*;q=0.8'})
        with urllib.request.urlopen(req,timeout=25) as response:
            blob=response.read(); d.update(http_status=response.status,final_url=response.url,response_headers=dict(response.headers.items()))
        ext='.pdf' if blob.startswith(b'%PDF-') else '.response.bin'
        dest=raw/(key+ext)
        with dest.open('xb') as f:f.write(blob)
        d.update(status='downloaded_pdf' if ext=='.pdf' else 'downloaded_non_pdf_response',raw_path=str(dest.relative_to(base)),sha256=hashlib.sha256(blob).hexdigest(),bytes=len(blob))
        if ext=='.pdf':
            proc=subprocess.run(['pdftotext','-layout',str(dest),'-'],capture_output=True)
            d['pdftotext_exit_code']=proc.returncode
            d['pdftotext_stderr']=proc.stderr.decode('utf-8',errors='replace')
            if proc.returncode==0:
                out=textdir/(key+'.txt')
                with out.open('xb') as f:f.write(proc.stdout)
                d['text_path']=str(out.relative_to(base));d['text_sha256']=hashlib.sha256(proc.stdout).hexdigest()
        return d
    except Exception as e:
        d.update(status='retrieval_failed',error_type=type(e).__name__,error=str(e))
        if isinstance(e,urllib.error.HTTPError):
            blob=e.read();dest=raw/(key+'.http_error.bin')
            with dest.open('xb') as f:f.write(blob)
            d.update(http_status=e.code,raw_error_path=str(dest.relative_to(base)),error_sha256=hashlib.sha256(blob).hexdigest(),error_bytes=len(blob))
        return d
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(fetch,sources))
ledger=dict(retrieved_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),environment=dict(python=sys.version,platform=platform.platform(),source_script=str(Path(__file__).relative_to(base)),source_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),command='python3 research/source_ledgers/output_gap_round002/methodology_sources/acquire_primary_sources_20261009.py'),sources=results)
with (run/'retrieval_ledger.json').open('x') as f:json.dump(ledger,f,ensure_ascii=False,indent=2)
print(json.dumps({'run_directory':str(run),'sources':[{k:x.get(k) for k in ('id','status','bytes','error','sha256')} for x in results]},ensure_ascii=False,indent=2))
