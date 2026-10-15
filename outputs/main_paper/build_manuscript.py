"""Build the manuscript using only a supplied frozen main-branch archive.

Document runtime: python-docx, Pillow, NumPy, matplotlib.
Equations: first run render_equations.cjs with the bundled Node runtime.
No provider calls, research-result rewriting, or source-tree mutations.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import math
import platform
import re
import sys
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

HERE = Path(__file__).resolve().parent
SHA = '7f2436bc4f32d6021b1e885eb49286c850de9139'


def read_csv(path):
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def member_set(text):
    return set(filter(None, text.split(';')))


def evaluate(rows, pred='sim_rate_bps', stance='sim_stance', labels=None):
    n=len(rows); exact=direction=stance_ok=0; err=0;tp=fp=fn=set_ok=0
    sign=lambda x:(x>0)-(x<0)
    for r in rows:
        a,p=int(r['actual_rate_bps']),int(r[pred])
        exact+=a==p;direction+=sign(a)==sign(p);err+=abs(a-p)
        stance_ok+=r['actual_stance']==r[stance]
        if 'sim_dissenters' in r:
            observed=member_set(r['actual_dissenters']) if labels is None else set(labels[r['meeting_date']])
            predicted=member_set(r['sim_dissenters'])
            tp+=len(predicted&observed);fp+=len(predicted-observed);fn+=len(observed-predicted)
            set_ok+=predicted==observed
    return {'n':n,'exact_rate':exact/n,'directional_rate':direction/n,'stance':stance_ok/n,'rate_mae_bps':err/n,
            'dissent_tp':tp,'dissent_fp':fp,'dissent_fn':fn,'dissent_f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0,'dissent_exact_match':set_ok/n}


def facts(source):
    audit=source/'results/methodology_audit_2026-10-05'
    mock=read_csv(source/'results/tables/meeting_by_meeting_comparison.csv')
    live=read_csv(source/'results/tables/holdout_meeting_by_meeting_comparison.csv')
    taylor=read_csv(source/'results/tables/rational_taylor_panel_results.csv')
    baselines=read_csv(audit/'stat_baseline_metrics.csv')
    adjud=json.loads((audit/'stat_adjudicated_results.json').read_text())
    formal={r['date']:r['formal_true'] for r in adjud['live_predictions']['union']}
    checks={'mock':evaluate(mock),'saved_provider_attributed':evaluate(live),
            'formal_union':evaluate(live,labels=formal),
            'taylor':evaluate(taylor,pred='taylor_modal_rate_bps',stance='taylor_modal_stance')}
    for k,v in [('mock',.76),('saved_provider_attributed',1),('taylor',.16)]:
        assert math.isclose(checks[k]['exact_rate'],v)
    assert math.isclose(checks['formal_union']['dissent_f1'],.6)
    assert math.isclose(checks['saved_provider_attributed']['dissent_f1'],5/6)
    assert len(mock)==25 and len(live)==8 and sum(r['panel_subset']=='calibration' for r in mock)==17
    assert Counter(int(r['actual_rate_bps']) for r in mock)=={0:19,40:1,50:3,35:1,25:1}
    assert all(int(r['sim_rate_bps'])==0 for r in mock)
    assert all(int(r['actual_rate_bps'])==0 for r in live)
    assert all(r['actual_stance']=='withdrawal_of_accommodation' for r in live)
    for key,metric in checks.items():
        if key=='formal_union': continue
        predictor={'mock':'saved_mock_panel','saved_provider_attributed':'saved_live_holdout','taylor':'taylor_saved_rate_dissent_probability_ge_0_5'}[key]
        subset='holdout' if key=='saved_provider_attributed' else 'all'
        recorded=next(b for b in baselines if b['subset']==subset and b['predictor']==predictor)
        for field in ['exact_rate','directional_rate','stance','rate_mae_bps']:
            assert math.isclose(metric[field],float(recorded[field])),(key,field)
    expected=json.loads((audit/'stat_results.json').read_text())['input_files']
    hashes={p:hashlib.sha256((source/p).read_bytes()).hexdigest() for p in expected}
    assert hashes==expected,'Source data changed from the frozen audit hashes'
    return mock,live,taylor,baselines,adjud,checks,hashes


def charts(assets, baselines, adjud):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(8.0,3.15),gridspec_kw={'width_ratios':[1.05,1]})
    labels=['Offline panel','Persistence','Lagged decision','Taylor rule','Saved provider outputs','Persistence']
    specifications=[('all','saved_mock_panel'),('all','always_hold_prev_stance_no_dissent'),
        ('all','lag_previous_observed_decision'),('all','taylor_saved_rate_dissent_probability_ge_0_5'),
        ('holdout','saved_live_holdout'),('holdout','always_hold_prev_stance_no_dissent')]
    values=[100*float(get_base(baselines,s,p)['exact_rate']) for s,p in specifications];positions=[0,1,2,3,5,6]
    colors=['#38586a','#b4b4b4','#777777','#b4b4b4','#38586a','#b4b4b4']
    a=axes[0];a.barh(positions,values,color=colors,height=.62)
    a.set_yticks(positions,labels);a.set_ylim(6.65,-1.0);a.set_xlim(0,114)
    a.set_xticks([0,25,50,75,100]);a.set_xlabel('Exact rate agreement (%)')
    for y,v in zip(positions,values):a.text(v+1.6,y,f'{v:g}',va='center',fontsize=9)
    a.axhline(4,color='#999999',lw=.65);a.text(0,4.45,'Eight-meeting saved evaluation',fontsize=8,color='#444444')
    a.set_title('A  Committee outcomes',loc='left',fontweight='bold',fontsize=10)
    a.text(0,-.73,'25-meeting offline panel',fontsize=8,color='#444444')
    b=axes[1];y=np.arange(2);width=.26
    original=[float(get_base(baselines,'holdout',p)['dissent_f1']) for p in ['saved_live_holdout','lag_previous_observed_decision']]
    strict=[next(r['f1'] for r in adjud['metrics'] if r['subset']=='holdout' and r['dimension']=='union' and r['predictor']==p) for p in ['saved_live_holdout','lag_previous_formal_ballot']]
    b.barh(y-width/2,original,height=width,color='#38586a',label='Original labels')
    b.barh(y+width/2,strict,height=width,color='#aaaaaa',label='Formal ballot labels')
    b.set_yticks(y,['Saved provider outputs','Lagged ballots']);b.set_ylim(1.9,-.65);b.set_xlim(0,1.16)
    b.set_xticks([0,.25,.5,.75,1]);b.set_xlabel('Micro union-dissent F1')
    for ys,vs in [(y-width/2,original),(y+width/2,strict)]:
        for yy,v in zip(ys,vs):b.text(v+.018,yy,f'{v:.3f}',va='center',fontsize=8)
    b.legend(loc='lower left',bbox_to_anchor=(0,.025),frameon=False,fontsize=8)
    b.set_title('B  Eight-meeting dissent',loc='left',fontweight='bold',fontsize=10)
    for ax in axes:ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0)
    fig.tight_layout(w_pad=2.6);fig.savefig(assets/'performance_plot.png',dpi=350,bbox_inches='tight',facecolor='white');plt.close(fig)

    fig,ax=plt.subplots(figsize=(8,3.35));ax.set_xlim(0,10);ax.set_ylim(0,4.3);ax.axis('off')
    def box(x,y,w,h,label,fill='#f2f2f2',edge='#777777'):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.06,rounding_size=0.07',lw=.8,edgecolor=edge,facecolor=fill))
        ax.text(x+w/2,y+h/2,label,ha='center',va='center',fontsize=9)
    def arrow(xy1,xy2,dashed=False):ax.annotate('',xy=xy2,xytext=xy1,arrowprops={'arrowstyle':'->','lw':.95,'color':'#444444','linestyle':'--' if dashed else '-'})
    box(.15,2.6,1.65,.92,'Personas and\nmacro briefing')
    box(2.25,2.6,1.7,.92,'Round 1\nInitial assessments')
    box(4.45,2.6,1.8,.92,'Round 2\nPeer responses')
    box(4.45,.75,1.8,.88,'Round 3\nGenerated and logged')
    box(6.78,2.42,2.9,1.25,'Round 4\nFive parallel ballots\nGovernor last with five votes',fill='#e9eff2')
    box(6.78,.55,2.9,.92,'Rule engine\nRate stance and dissent')
    arrow((1.9,3.06),(2.15,3.06));arrow((4.02,3.06),(4.37,3.06));arrow((6.33,3.06),(6.68,3.06))
    arrow((5.35,2.52),(5.35,1.7));arrow((8.23,2.33),(8.23,1.55))
    arrow((3.1,3.62),(7.0,3.62));ax.text(5.0,3.94,'Initial assessments also reach final prompts',ha='center',fontsize=8)
    ax.text(4.75,.18,'Round 3 has no outgoing path to the final vote',ha='center',fontsize=8,color='#444444')
    ax.text(.2,.9,'Later rounds receive\nsynthetic staff inputs',fontsize=9,color='#444444')
    fig.tight_layout();fig.savefig(assets/'architecture.png',dpi=350,bbox_inches='tight',facecolor='white');plt.close(fig)


def pct(x):return f'{100*float(x):.1f}'
def get_base(b,subset,predictor):return next(r for r in b if r['subset']==subset and r['predictor']==predictor)


def table_data(baselines,adjud,live):
    perf=[]
    for subset,predictor,name in [
        ('all','saved_mock_panel','Offline behavioral panel'),('all','always_hold_prev_stance_no_dissent','Hold rate and previous stance'),
        ('all','lag_previous_observed_decision','Lag previous observed decision'),('all','taylor_saved_rate_dissent_probability_ge_0_5','Configured Taylor rule'),
        ('holdout','saved_live_holdout','Saved provider attributed'),('holdout','always_hold_prev_stance_no_dissent','Hold rate and previous stance'),
        ('holdout','lag_previous_observed_decision','Lag previous observed decision'),('holdout','taylor_saved_rate_dissent_probability_ge_0_5','Configured Taylor rule')]:
        r=get_base(baselines,subset,predictor)
        perf.append([name,r['n'],pct(r['exact_rate']),pct(r['directional_rate']),f"{float(r['rate_mae_bps']):.3f}".rstrip('0').rstrip('.'),pct(r['stance'])])
    dissent=[]
    for predictor,label in [('saved_live_holdout','Saved outputs original union'),('lag_previous_observed_decision','Lag ballots original union'),('always_hold_prev_stance_varma','Fixed Varma original union')]:
        r=get_base(baselines,'holdout',predictor)
        dissent.append([label,r['dissent_tp'],r['dissent_fp'],r['dissent_fn'],f"{float(r['dissent_precision']):.3f}",f"{float(r['dissent_recall']):.3f}",f"{float(r['dissent_f1']):.3f}",pct(r['dissent_exact_match'])])
    for predictor,dimension,label in [('saved_live_holdout','union','Saved outputs formal union'),('lag_previous_formal_ballot','union','Lag ballots formal union'),('saved_live_holdout','rate','Saved outputs formal rate')]:
        r=next(x for x in adjud['metrics'] if x['subset']=='holdout' and x['predictor']==predictor and x['dimension']==dimension)
        dissent.append([label,r['tp'],r['fp'],r['fn'],f"{r['precision']:.3f}",f"{r['recall']:.3f}",f"{r['f1']:.3f}",pct(r['exact_match'])])
    abbrev=lambda members:' + '.join('V' if 'varma' in m else 'G' for m in sorted(members)) or 'None'
    formal={r['date']:r['formal_true'] for r in adjud['live_predictions']['union']}
    rates={r['date']:r['predicted'] for r in adjud['live_predictions']['rate']}
    return {
      'design':(['Evidence track','Scope','Settings and interpretation'],[
        ['Archived minutes','25 meetings\n150 statements','October 2020 to August 2024; includes roster replacement'],
        ['Nominal chronological split','17 calibration\n8 evaluation','Through 6 April 2023 versus June 2023 to August 2024; personas are not restricted to calibration'],
        ['Offline behavioral panel','25 saved outcomes','Mock or heuristic output; all predicted rate changes are holds'],
        ['Saved provider attributed','8 saved outcomes','Runner requests Gemini 3.1 Flash Lite; temperature 0.1; one replicate; incomplete effective call linkage'],
        ['Numerical comparator','25 meetings','1,000 draws per meeting; assumed heterogeneous Taylor coefficients and rho 0.75'],
        ['Retained methodology audit','Offline checks','Baseline reanalysis, formal ballot sensitivity, software probes and numerical stress checks']], [1.55,1.15,3.8]),
      'performance':(['Track or comparator','n','Exact\nrate %','Direction\n%','MAE\nbps','Stance\n%'],perf,[2.55,.35,.85,.85,1.0,.9]),
      'dissent':(['Prediction and target','TP','FP','FN','Precision','Recall','F1','Set exact\n%'],dissent,[2.25,.35,.35,.35,.85,.75,.65,.95]),
      'interventions':(['Intervention','Saved rate response','Stance response'],[
        ['Monsoon and vegetable shock\n10 August 2023','Behavioral 0 to +25 bps\nTaylor +50 to +50 bps','Unchanged in both tracks'],
        ['US tightening +75 bps\n5 August 2022','Behavioral +50 to +50 bps\nTaylor +50 to +50 bps','Unchanged in both tracks'],
        ['Withhold Varma material','0 to 0 bps','Withdrawal unchanged'],['Withhold Patra material','0 to 0 bps','Withdrawal unchanged'],
        ['Casting vote removed untied','0 to 0 bps','Withdrawal unchanged'],['Casting vote removed constructed tie','0 to 0 bps','Withdrawal to neutral'],
        ['Food inflation muted','0 to 0 bps','Withdrawal unchanged'],['Monsoon information muted','0 to 0 bps','Withdrawal unchanged']], [2.65,2.1,1.75]),
      'meetings':(['Decision date','Original observed\nunion','Formal observed\nunion','Predicted\nunion','Predicted\nrate dissent'],[
        [r['meeting_date'],abbrev(member_set(r['actual_dissenters'])),abbrev(formal[r['meeting_date']]),abbrev(member_set(r['sim_dissenters'])),abbrev(rates[r['meeting_date']])] for r in live],[1.15,1.35,1.35,1.2,1.25]),
      'coefficients':(['Member','Alpha','Beta','Gamma'],[
        ['Shaktikanta Das','1.2','0.4','0.2'],['Michael Debabrata Patra','1.8','0.6','0.3'],['Mridul K. Saggar','1.3','0.5','0.2'],
        ['Rajiv Ranjan','1.4','0.5','0.2'],['Shashanka Bhide','1.3','0.4','0.2'],['Ashima Goyal','0.8','0.3','0.1'],['Jayanth R. Varma','0.5','0.2','0.0']], [3.25,1.1,1.1,1.05]),
      'evidence':(['Retained artifact','Quantity or verification supported'],[
        ['results/tables/\nmeeting_by_meeting_comparison.csv','Full panel offline rate, stance and supplied dissent predictions'],
        ['results/tables/\nholdout_meeting_by_meeting_comparison.csv','Eight saved provider attributed committee outcomes and supplied dissent predictions'],
        ['results/tables/\nrational_taylor_panel_results.csv','Original numerical modal rate and stance outputs'],
        ['results/methodology_audit_2026-10-05/\nstat_baseline_metrics.csv','Persistence, lagged decisions and fixed member baselines'],
        ['Same audit directory\nstat_adjudicated_results.json\ndata_adjudicated_truth.json','Formal ballot sensitivity counts, source excerpts and label conventions'],
        ['Same audit directory\nstat_taylor_rho_metrics.csv\nstat_results.json','Smoothing sensitivity, small sample diagnostics and initial round comparison'],
        ['Same audit directory\naudit_results.json\narch_probe_results.json','Finite profiles, numerical stress, prompt flow, cache, fallback and budget checks'],
        ['results/tables/\ntable3_counterfactual_shock_responses.csv\ntable4_attribution_ablation_effects.csv','Saved scenario and ablation output changes including null results'],
        ['Same audit directory\ninput_hashes.json and raw logs','Input inventory, measured environment and stdout or stderr for checks actually run']], [3.2,3.3])
    }


def style_document(doc):
    sec=doc.sections[0];sec.page_width=Inches(8.5);sec.page_height=Inches(11)
    sec.top_margin=sec.bottom_margin=Inches(.9);sec.left_margin=sec.right_margin=Inches(1)
    sec.header_distance=sec.footer_distance=Inches(.4)
    normal=doc.styles['Normal'];normal.font.name='Times New Roman';normal.font.size=Pt(11.5);normal.font.color.rgb=RGBColor(0,0,0)
    normal.paragraph_format.line_spacing=1.15;normal.paragraph_format.space_after=Pt(6);normal.paragraph_format.widow_control=True
    for name,size,bold in [('Title',18,True),('Heading 1',13,True),('Heading 2',11.5,True),('Caption',10.5,False)]:
        s=doc.styles[name];s.font.name='Times New Roman';s.font.size=Pt(size);s.font.bold=bold;s.font.color.rgb=RGBColor(0,0,0)
        fonts=s.element.get_or_add_rPr().find(qn('w:rFonts'))
        if fonts is not None:
            for theme in ['asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme']:
                fonts.attrib.pop(qn('w:'+theme),None)
        s.paragraph_format.space_before=Pt(12 if name=='Heading 1' else 8);s.paragraph_format.space_after=Pt(6)
        s.paragraph_format.keep_with_next=True;s.paragraph_format.line_spacing=1.05
        if s.element.pPr is not None:
            for e in list(s.element.pPr):
                if e.tag==qn('w:pBdr'):s.element.pPr.remove(e)
    doc.styles['Title'].paragraph_format.space_before=Pt(0);doc.styles['Title'].paragraph_format.space_after=Pt(12)
    # Institutional article running header, without borders or decorative rules.
    hp=sec.header.paragraphs[0];hp.text='RBI MPC In Silico';hp.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    hp.runs[0].font.size=Pt(9);hp.runs[0].font.color.rgb=RGBColor(0,0,0)
    fp=sec.footer.paragraphs[0];fp.alignment=WD_ALIGN_PARAGRAPH.CENTER
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');fp._p.append(field)
    doc.core_properties.title='RBI MPC In Silico Simulation and Retrospective Validation'
    doc.core_properties.subject='Original main branch retrospective research manuscript'
    doc.core_properties.author='';doc.core_properties.last_modified_by=''
    doc.core_properties.keywords='RBI; MPC; language models; simulation; retrospective validation'


def add_image(p,path,width,alt):
    inline=p.add_run().add_picture(str(path),width=Inches(width))
    props=inline._inline.docPr;props.set('descr',alt);props.set('title',alt[:100])


def add_table(doc,headers,rows,widths):
    t=doc.add_table(rows=1,cols=len(headers));t.autofit=False
    for c,w in zip(t.columns,widths):c.width=Inches(w)
    props=t._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
    props.append(borders)
    margins=OxmlElement('w:tblCellMar')
    for edge,value in [('top','75'),('bottom','75'),('left','85'),('right','85')]:
        e=OxmlElement('w:'+edge);e.set(qn('w:w'),value);e.set(qn('w:type'),'dxa');margins.append(e)
    props.append(margins)
    repeat=OxmlElement('w:tblHeader');repeat.set(qn('w:val'),'true');t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for cells,values,ishead in [(t.rows[0].cells,headers,True)]+[(t.add_row().cells,r,False) for r in rows]:
        for idx,(c,value,w) in enumerate(zip(cells,values,widths)):
            c.width=Inches(w);c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p=c.paragraphs[0];p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.06
            p.paragraph_format.keep_with_next=False
            p.alignment=WD_ALIGN_PARAGRAPH.LEFT if idx==0 or len(headers)<=3 else WD_ALIGN_PARAGRAPH.CENTER
            run=p.add_run(str(value));run.font.name='Times New Roman';run.font.size=Pt(10.5 if len(headers)<=6 else 10);run.bold=ishead
            if ishead:
                shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'EDEDED');c._tc.get_or_add_tcPr().append(shade)
    for row in t.rows:
        keep=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(keep)
    # Header stays with the next row; remaining rows may paginate normally.
    for p in t.rows[0].cells[0].paragraphs:p.paragraph_format.keep_with_next=True
    return t


def add_hyperlink(paragraph,text,url):
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    rel=paragraph.part.relate_to(url,RT.HYPERLINK,is_external=True)
    link=OxmlElement('w:hyperlink');link.set(qn('r:id'),rel)
    run=OxmlElement('w:r');pr=OxmlElement('w:rPr')
    color=OxmlElement('w:color');color.set(qn('w:val'),'000000');pr.append(color)
    size=OxmlElement('w:sz');size.set(qn('w:val'),'21');pr.append(size);run.append(pr)
    txt=OxmlElement('w:t');txt.text=text;run.append(txt);link.append(run);paragraph._p.append(link)


def build(source,assets,output):
    source=source.resolve();assets.mkdir(parents=True,exist_ok=True)
    manuscript=json.loads((HERE/'manuscript_source.json').read_text())
    mock,live,taylor,base,adjud,checks,hashes=facts(source)
    charts(assets,base,adjud);tables=table_data(base,adjud,live)
    eqsizes=json.loads((assets/'equation_sizes.json').read_text())
    doc=Document();style_document(doc)
    title=doc.add_paragraph(manuscript['title'],style='Title');title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph('Abstract',style='Heading 1')
    p=doc.add_paragraph(manuscript['abstract']);p.paragraph_format.line_spacing=1.08
    p=doc.add_paragraph();p.add_run('Keywords  ').bold=True;p.add_run(manuscript['keywords']);p.paragraph_format.space_after=Pt(10)
    for block in manuscript['blocks']:
        kind=block['type']
        if kind in ['h1','h2']:
            heading=re.sub(r'^\d+ \d+ ','',block['text']) if kind=='h2' else block['text']
            p=doc.add_paragraph(heading,style='Heading 1' if kind=='h1' else 'Heading 2')
        elif kind=='p':
            p=doc.add_paragraph(block['text']);p.alignment=WD_ALIGN_PARAGRAPH.LEFT
        elif kind=='code':
            p=doc.add_paragraph(block['text']);p.paragraph_format.space_before=Pt(5);p.paragraph_format.space_after=Pt(8)
            p.runs[0].font.name='Courier New';p.runs[0].font.size=Pt(9.5)
        elif kind=='table':
            p=doc.add_paragraph(block['caption'],style='Caption');p.runs[0].bold=True
            add_table(doc,*tables[block['id']])
            p=doc.add_paragraph(block['note']);p.paragraph_format.space_before=Pt(5);p.paragraph_format.space_after=Pt(9)
            p.paragraph_format.line_spacing=1.08
            for r in p.runs:r.font.size=Pt(10)
        elif kind=='figure':
            p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.keep_with_next=True
            p.paragraph_format.space_before=Pt(6);p.paragraph_format.space_after=Pt(4)
            add_image(p,assets/(block['id']+'.png'),6.5,block['caption'])
            p=doc.add_paragraph(block['caption'],style='Caption');p.runs[0].bold=True
            p=doc.add_paragraph(block['note']);p.paragraph_format.line_spacing=1.08;p.paragraph_format.space_after=Pt(9)
            for r in p.runs:r.font.size=Pt(10)
        elif kind=='equation':
            p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.space_before=Pt(4);p.paragraph_format.space_after=Pt(9)
            width=min(eqsizes[block['id']]['width_inches']*.65,5.9)
            add_image(p,assets/('equation_'+block['id']+'.png'),width,block['alt'])
            p.add_run(f"    ({block['number']})")
        elif kind=='references':
            for ref in manuscript['references']:
                p=doc.add_paragraph(ref['text']+' ');p.paragraph_format.left_indent=Inches(.22);p.paragraph_format.first_line_indent=Inches(-.22)
                p.paragraph_format.line_spacing=1.08;p.paragraph_format.space_after=Pt(7)
                for r in p.runs:r.font.size=Pt(10.5)
                # Short linked labels avoid lengthy web addresses disrupting the bibliography.
                label='doi: '+ref['url'].split('doi.org/')[1] if 'doi.org' in ref['url'] else 'Official source'
                add_hyperlink(p,label,ref['url'])
    output.parent.mkdir(parents=True,exist_ok=True);doc.save(output)
    provenance={'source_commit':SHA,'source_archive':str(source),'analysis':'Frozen artifacts recomputed; no new provider calls or simulation reruns',
        'recomputed_metrics':checks,'source_sha256':hashes,'python':sys.version,'platform':platform.platform(),
        'document_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'word_count':sum(len(b.get('text','').split()) for b in manuscript['blocks'])+len(manuscript['abstract'].split()),
        'references':len(manuscript['references']),'tables':len(tables),'figures':2,'equations':4}
    (HERE/'manuscript_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps({k:provenance[k] for k in ['source_commit','word_count','references','tables','figures','equations']}))
    print(output)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=HERE/'RBI_MPC_In_Silico_Research_Manuscript.docx');args=parser.parse_args()
    build(args.source,args.assets,args.output)
