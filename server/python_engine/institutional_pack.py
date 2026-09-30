from __future__ import annotations
import os, math, warnings
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.chart import LineChart, BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.drawing.image import Image as XLImage
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.utils import get_column_letter

warnings.filterwarnings('ignore')

OUT = Path(__file__).resolve().parent / 'reports'
OUT.mkdir(parents=True, exist_ok=True)
CHART_DIR = OUT / '_charts'
CHART_DIR.mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------
def _safe(v, default=np.nan):
    try:
        x=float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default

def _money(v):
    x=_safe(v)
    if not np.isfinite(x): return 'N/A'
    a=abs(x)
    if a>=1e12: return f'₹{x/1e12:.2f}T'
    if a>=1e9: return f'₹{x/1e9:.2f}B'
    if a>=1e7: return f'₹{x/1e7:.2f}Cr'
    return f'₹{x:,.0f}'

def _pct(v):
    x=_safe(v)
    return 'N/A' if not np.isfinite(x) else f'{x*100:.1f}%'

def _norm_series(s):
    if s is None: return pd.Series(dtype=float)
    s=pd.to_numeric(pd.Series(s),errors='coerce').dropna()
    return s

def _series_years(s):
    s=_norm_series(s)
    return s

def _safe_name(s):
    return ''.join(c if c.isalnum() or c in '._-' else '_' for c in str(s))

def _savefig(fig, name):
    p=CHART_DIR / name
    fig.tight_layout()
    fig.savefig(p, dpi=180, bbox_inches='tight')
    plt.close(fig)
    return p

def _add_doc_title(doc, title, subtitle=''):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    r=p.add_run(title); r.bold=True; r.font.size=Pt(22); r.font.color.rgb=RGBColor(25,45,75)
    if subtitle:
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        r=p.add_run(subtitle); r.font.size=Pt(10); r.font.color.rgb=RGBColor(90,90,90)

def _shade(cell, fill):
    tcPr=cell._tc.get_or_add_tcPr(); shd=OxmlElement('w:shd'); shd.set(qn('w:fill'),fill); tcPr.append(shd)

def _doc_table(doc, df, title=None, max_rows=20):
    if title: doc.add_heading(title, level=2)
    d=df.copy().head(max_rows)
    table=doc.add_table(rows=1, cols=len(d.columns)); table.alignment=WD_TABLE_ALIGNMENT.CENTER
    table.style='Table Grid'
    for j,c in enumerate(d.columns):
        cell=table.rows[0].cells[j]; cell.text=str(c); _shade(cell,'1F4E78')
        for run in cell.paragraphs[0].runs: run.font.bold=True; run.font.color.rgb=RGBColor(255,255,255)
    for _,row in d.iterrows():
        cells=table.add_row().cells
        for j,v in enumerate(row):
            cells[j].text=str(v); cells[j].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    return table

def _format_excel(wb):
    dark='17365D'; blue='1F4E78'; light='D9EAF7'; white='FFFFFF'; grey='E7E6E6'
    thin=Side(style='thin',color='B7B7B7')
    for ws in wb.worksheets:
        ws.freeze_panes='A2'
        ws.sheet_view.showGridLines=False
        ws.auto_filter.ref=ws.dimensions if ws.max_row>1 and ws.max_column>1 else None
        for cell in ws[1]:
            cell.font=Font(bold=True,color=white,size=10)
            cell.fill=PatternFill('solid',fgColor=dark)
            cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
            cell.border=Border(bottom=thin)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment=Alignment(vertical='center',wrap_text=True)
        for col in range(1,ws.max_column+1):
            vals=[str(ws.cell(r,col).value or '') for r in range(1,min(ws.max_row,30)+1)]
            width=min(42,max(12,max((len(v) for v in vals),default=12)+2))
            ws.column_dimensions[get_column_letter(col)].width=width
        ws.row_dimensions[1].height=30
    if 'Cover' in wb.sheetnames:
        ws=wb['Cover']; ws.freeze_panes='A1'; ws.sheet_view.showGridLines=False
        for cell in ws[1]: cell.fill=PatternFill('solid',fgColor=dark); cell.font=Font(bold=True,color=white,size=14)

# ---------- analytical engines ----------
def _quarterly_intelligence(d):
    q=None
    try:
        # yfinance quarterly income statement is often available; tolerate absence.
        import yfinance as yf
        tk=d['ticker']; q=yf.Ticker(tk).quarterly_financials
    except Exception: q=None
    if q is None or q.empty:
        return pd.DataFrame(), {'status':'N/A','message':'Quarterly income statement unavailable from source.'}
    aliases={
      'Revenue':['Total Revenue','Operating Revenue','Total Operating Income'],
      'EBITDA':['EBITDA'], 'EBIT':['Operating Income','EBIT'],
      'Net Income':['Net Income','Net Income Common Stockholders','Net Income Including Noncontrolling Interests']}
    out={}
    for key,names in aliases.items():
        row=None
        for n in names:
            if n in q.index: row=q.loc[n]; break
        if row is not None: out[key]=pd.to_numeric(row,errors='coerce')
    df=pd.DataFrame(out).sort_index()
    if df.empty: return df, {'status':'N/A','message':'No usable quarterly fields.'}
    for c in ['Revenue','EBITDA','Net Income']:
        if c in df: df[c+' QoQ']=df[c].pct_change()
        if c in df: df[c+' YoY']=df[c].pct_change(4)
    rev_yoy=df['Revenue YoY'].dropna() if 'Revenue YoY' in df else pd.Series(dtype=float)
    ni_yoy=df['Net Income YoY'].dropna() if 'Net Income YoY' in df else pd.Series(dtype=float)
    trend=[]
    if len(rev_yoy)>=2: trend.append('Revenue YoY momentum improving' if rev_yoy.iloc[-1]>rev_yoy.iloc[-2] else 'Revenue YoY momentum weakening')
    if len(ni_yoy)>=2: trend.append('Earnings YoY momentum improving' if ni_yoy.iloc[-1]>ni_yoy.iloc[-2] else 'Earnings YoY momentum weakening')
    return df, {'status':'AVAILABLE','message':'; '.join(trend) if trend else 'Limited quarterly trend history.'}

def _forensic(d,r):
    hs=d['financials']; fcf=_safe(r.get('fcf').iloc[0] if len(r.get('fcf',[])) else np.nan)
    cfo=_safe(hs['cfo'].iloc[0] if len(hs['cfo']) else np.nan)
    ni=_safe(hs['net_income'].iloc[0] if len(hs['net_income']) else np.nan)
    debt=_safe(hs['debt'].iloc[0] if len(hs['debt']) else np.nan); eq=_safe(hs['equity'].iloc[0] if len(hs['equity']) else np.nan)
    accrual=ni-cfo if np.isfinite(ni) and np.isfinite(cfo) else np.nan
    cash_conv=cfo/ni if np.isfinite(cfo) and np.isfinite(ni) and ni!=0 else np.nan
    leverage=debt/eq if np.isfinite(debt) and np.isfinite(eq) and eq!=0 else np.nan
    flags=[]
    if np.isfinite(cash_conv) and cash_conv<0.8: flags.append('Weak cash conversion')
    if np.isfinite(cash_conv) and cash_conv>1.1: flags.append('Strong cash conversion')
    if np.isfinite(accrual) and ni!=0 and abs(accrual/ni)>0.25: flags.append('Material accrual spread')
    if np.isfinite(leverage) and leverage>1.0: flags.append('Elevated leverage')
    if np.isfinite(fcf) and fcf<0: flags.append('Negative latest FCF')
    return pd.DataFrame([{'Metric':'Net Income','Value':ni},{'Metric':'CFO','Value':cfo},{'Metric':'FCF','Value':fcf},{'Metric':'Cash Conversion (CFO/NI)','Value':cash_conv},{'Metric':'Accrual Spread (NI-CFO)','Value':accrual},{'Metric':'Debt/Equity','Value':leverage}]), flags

def _factor_exposure(d):
    c=d['close'].dropna(); rets=np.log(c/c.shift(1)).dropna()
    windows={'1M':21,'3M':63,'6M':126,'1Y':252,'3Y':756}
    rows=[]
    for name,n in windows.items():
        if len(rets)>=n:
            x=float(np.exp(rets.tail(n).sum())-1); vol=float(rets.tail(n).std()*np.sqrt(252));
            rows.append((name,x,vol))
    return pd.DataFrame(rows,columns=['Window','Return','Volatility'])

def _scenario(d,r):
    p=r['price']; dc=r['dcf']; hs=d['financials']; base_g=r['assumptions'].get('revenue_growth',.08); w=dc.wacc; tg=dc.terminal_growth
    scenarios=[('Bear',max(.02,base_g-.05),min(.16,w+.02)),('Base',base_g,w),('Bull',min(.18,base_g+.05),max(.08,w-.02))]
    rows=[]
    fcf=_safe(r['fcf'].iloc[0] if len(r['fcf']) else np.nan)
    debt=_safe(hs['debt'].iloc[0] if len(hs['debt']) else 0); cash=_safe(hs['cash'].iloc[0] if len(hs['cash']) else 0)
    shares=_safe(r['info'].get('sharesOutstanding'),1)
    for label,g,ww in scenarios:
        if not np.isfinite(fcf) or fcf<=0 or ww<=tg:
            val=np.nan
        else:
            vals=[]; x=fcf
            for i in range(5): x*=1+max(.01,g-.0125*i); vals.append(x)
            pv=sum(v/(1+ww)**(i+1) for i,v in enumerate(vals)); tv=vals[-1]*(1+tg)/(ww-tg); val=(pv+tv/(1+ww)**5-debt+cash)/shares
        rows.append((label,g,ww,val,val/p-1 if np.isfinite(val) else np.nan))
    return pd.DataFrame(rows,columns=['Scenario','Growth','WACC','Fair Value','Upside'])

def _what_changed(d,r):
    hs=d['financials']; rows=[]
    for key,label in [('revenue','Revenue'),('ebitda','EBITDA'),('net_income','Net Income'),('cfo','CFO'),('capex','Capex'),('debt','Debt'),('cash','Cash')]:
        s=pd.to_numeric(hs.get(key,pd.Series(dtype=float)),errors='coerce').dropna()
        if len(s)>=2:
            latest=float(s.iloc[0]); prev=float(s.iloc[1]); delta=latest-prev; pct=delta/abs(prev) if prev else np.nan
            rows.append((label,latest,prev,delta,pct))
    return pd.DataFrame(rows,columns=['Metric','Latest','Prior','Change','Change %'])

def _catalyst(d,r,q):
    items=[]
    if not q.empty:
        items.append(('Quarterly earnings momentum', q['Net Income YoY'].iloc[-1] if 'Net Income YoY' in q and len(q['Net Income YoY'].dropna()) else np.nan))
    items.append(('DCF upside',r.get('upside',np.nan)))
    items.append(('52W position',(r['price']-r['tech']['low'])/(r['tech']['high']-r['tech']['low']) if r['tech']['high']!=r['tech']['low'] else np.nan))
    items.append(('Technical score',r['tech']['score']/100))
    return pd.DataFrame(items,columns=['Catalyst / Signal','Value'])

# ---------- chart generation ----------
def build_charts(d,r,q,sc,fc,chg,mc):
    ticker=d['ticker'].replace('.NS',''); name=_safe_name(ticker)
    hs=d['financials']; paths={}
    c=d['close'].dropna()
    fig,ax=plt.subplots(figsize=(10,4.8)); ax.plot(c.index,c.values,linewidth=1.4,label='Price')
    for n,style in [(50,'--'),(200,':')]:
        if len(c)>=n: ax.plot(c.index,c.rolling(n).mean(),style,linewidth=1,label=f'SMA {n}')
    ax.set_title(f'{ticker} — Price & Trend'); ax.set_ylabel('Price (₹)'); ax.legend(); paths['price']=_savefig(fig,f'{name}_01_price.png')

    rev=pd.to_numeric(hs['revenue'],errors='coerce').dropna().iloc[::-1] if len(hs['revenue']) else pd.Series(dtype=float)
    ebitda=pd.to_numeric(hs['ebitda'],errors='coerce').dropna().iloc[::-1] if len(hs['ebitda']) else pd.Series(dtype=float)
    ni=pd.to_numeric(hs['net_income'],errors='coerce').dropna().iloc[::-1] if len(hs['net_income']) else pd.Series(dtype=float)
    fig,ax=plt.subplots(figsize=(10,4.8));
    for s,label in [(rev,'Revenue'),(ebitda,'EBITDA'),(ni,'Net Income')]:
        if len(s): ax.plot(range(len(s)),s.values,marker='o',label=label)
    ax.set_title(f'{ticker} — Historical Earnings Profile'); ax.legend(); paths['financials']=_savefig(fig,f'{name}_02_financials.png')

    model=r['model']; years=[f'FY+{i}' for i in model.iloc[:,0]]
    fig,ax=plt.subplots(figsize=(10,4.8)); ax.plot(years,model['Revenue'],marker='o',label='Revenue'); ax.plot(years,model['EBITDA'],marker='o',label='EBITDA'); ax.plot(years,model['Net Income'],marker='o',label='Net Income'); ax.plot(years,model['FCF'],marker='o',label='FCF'); ax.set_title(f'{ticker} — 5-Year Model Projections'); ax.legend(); paths['projections']=_savefig(fig,f'{name}_03_projections.png')

    fig,ax=plt.subplots(figsize=(9,5));
    sens=np.array(r['dcf'].sensitivity,dtype=float); im=ax.imshow(sens,aspect='auto'); ax.set_xticks(range(5)); ax.set_xticklabels(['8%','10%','12%','14%','16%']); ax.set_yticks(range(5)); ax.set_yticklabels(['4%','6%','8%','10%','12%']); ax.set_xlabel('WACC'); ax.set_ylabel('Growth'); ax.set_title(f'{ticker} — DCF Sensitivity');
    for i in range(5):
        for j in range(5):
            if np.isfinite(sens[i,j]): ax.text(j,i,f'{sens[i,j]:,.0f}',ha='center',va='center',fontsize=8)
    fig.colorbar(im,ax=ax,label='Fair Value (₹)'); paths['dcf']=_savefig(fig,f'{name}_04_dcf_sensitivity.png')

    term=np.array([v for v in mc['percentiles'].values()]); labs=list(mc['percentiles'].keys())
    fig,ax=plt.subplots(figsize=(10,4.8)); ax.bar(labs,term); ax.axhline(r['price'],linestyle='--',label='Current Price'); ax.set_title(f'{ticker} — Monte Carlo Terminal Distribution'); ax.set_ylabel('Price (₹)'); ax.legend(); paths['mc']=_savefig(fig,f'{name}_05_monte_carlo.png')

    if len(q):
        fig,ax=plt.subplots(figsize=(10,4.8));
        if 'Revenue YoY' in q: ax.plot(q.index,q['Revenue YoY']*100,marker='o',label='Revenue YoY')
        if 'Net Income YoY' in q: ax.plot(q.index,q['Net Income YoY']*100,marker='o',label='Net Income YoY')
        ax.axhline(0,linewidth=.8); ax.set_title(f'{ticker} — Quarterly Growth Momentum'); ax.set_ylabel('%'); ax.legend(); paths['quarterly']=_savefig(fig,f'{name}_06_quarterly.png')

    fig,ax=plt.subplots(figsize=(8,5)); ax.bar(sc['Scenario'],sc['Fair Value']); ax.axhline(r['price'],linestyle='--',label='Current Price'); ax.set_title(f'{ticker} — Scenario Fair Values'); ax.set_ylabel('Fair Value (₹)'); ax.legend(); paths['scenario']=_savefig(fig,f'{name}_07_scenarios.png')

    if len(fc):
        fig,ax=plt.subplots(figsize=(8,5)); ax.pie([max(r['score'],0),max(100-r['score'],0)],labels=['GWI Score','Remaining'],autopct='%1.0f%%',startangle=90); ax.set_title(f'{ticker} — Integrated GWI Score'); paths['score']=_savefig(fig,f'{name}_08_score.png')

    # Valuation stack: explicit comparison of independent/modelled reference values.
    vals=[]; labels=[]
    for lab,val in [('DCF',r.get('dcf').target),('Peer Multiple',r.get('implied')),('Blended',r.get('blended')),('Current Price',r.get('price'))]:
        if val is not None and np.isfinite(val): labels.append(lab); vals.append(float(val))
    if vals:
        fig,ax=plt.subplots(figsize=(8.5,5)); ax.bar(labels,vals); ax.set_title(f'{ticker} — Valuation Stack'); ax.set_ylabel('Value (₹)'); ax.tick_params(axis='x',rotation=15); paths['valuation']=_savefig(fig,f'{name}_09_valuation_stack.png')

    # Downside/upside probability profile.
    probs=[max(float(mc.get('positive_prob',0))*100,0),max(float(mc.get('loss20_prob',0))*100,0),max(100-float(mc.get('positive_prob',0))*100-float(mc.get('loss20_prob',0))*100,0)]
    fig,ax=plt.subplots(figsize=(7.5,5)); ax.pie(probs,labels=['Positive outcome','>20% loss','Other'],autopct='%1.1f%%',startangle=90); ax.set_title(f'{ticker} — Monte Carlo Outcome Profile'); paths['risk_pie']=_savefig(fig,f'{name}_10_risk_profile.png')

    # Realistic candlestick + volume research chart for Word/Excel deliverables.
    try:
        h=d['history'][['Open','High','Low','Close','Volume']].dropna(subset=['Open','High','Low','Close']).tail(180)
        if len(h):
            fig,(ax,axv)=plt.subplots(2,1,figsize=(12,6),sharex=True,gridspec_kw={'height_ratios':[4,1]})
            x=np.arange(len(h));
            width=0.62
            for i,(op,hi,lo,cl,vol) in enumerate(h[['Open','High','Low','Close','Volume']].to_numpy(float)):
                up=cl>=op
                ax.vlines(i,lo,hi,linewidth=.8)
                lower=min(op,cl); body=max(abs(cl-op),max(abs(cl),abs(op))*0.001)
                ax.bar(i,body,bottom=lower,width=width,fill=up,alpha=.9)
                axv.bar(i,vol,width=width,alpha=.65)
            full=d['history']['Close'].dropna()
            for n in [20,50,200]:
                ma=full.rolling(n).mean().reindex(h.index)
                ax.plot(x,ma.to_numpy(float),linewidth=1,label=f'MA {n}')
            ax.set_title(f'{ticker} — OHLC Candlestick / Moving Averages / Volume')
            ax.set_ylabel('Price (₹)'); axv.set_ylabel('Volume'); ax.legend(loc='upper left',ncol=3,fontsize=8); ax.grid(alpha=.18); axv.grid(alpha=.12)
            ax.set_xticks(np.linspace(0,len(h)-1,min(6,len(h))).astype(int)); ax.set_xticklabels([str(h.index[i].date()) for i in np.linspace(0,len(h)-1,min(6,len(h))).astype(int)],rotation=20,ha='right')
            paths['candlestick']=_savefig(fig,f'{name}_00_candlestick.png')
    except Exception:
        pass

    # Monte Carlo histogram using actual terminal simulation paths when available.
    try:
        vals=np.asarray(mc.get('paths',[]),float)
        if vals.ndim==2 and vals.shape[1]>1:
            terminal=vals[:,-1]; terminal=terminal[np.isfinite(terminal)]
            if len(terminal)>20:
                fig,ax=plt.subplots(figsize=(10,5)); ax.hist(terminal,bins=32,alpha=.82); ax.axvline(r['price'],linestyle='--',linewidth=1.5,label='Current price');
                for k,ls in [('P5',':'),('P50','-'),('P95',':')]: ax.axvline(mc['percentiles'][k],linestyle=ls,linewidth=1,label=k)
                ax.set_title(f'{ticker} — Monte Carlo Terminal Price Distribution'); ax.set_xlabel('Terminal price (₹)'); ax.set_ylabel('Simulation count'); ax.legend(); ax.grid(alpha=.16); paths['mc_hist']=_savefig(fig,f'{name}_05b_monte_carlo_histogram.png')
    except Exception:
        pass

    # Technical momentum chart: RSI with 30/70 control bands.
    try:
        close=d['close'].dropna(); delta=close.diff(); gain=delta.clip(lower=0).rolling(14).mean(); loss=delta.clip(upper=0).abs().rolling(14).mean(); rs=gain/loss.replace(0,np.nan); rsi=100-(100/(1+rs)); rsi=rsi.dropna().tail(180)
        if len(rsi):
            fig,ax=plt.subplots(figsize=(10,4)); ax.plot(rsi.index,rsi.values,linewidth=1.4,label='RSI 14'); ax.axhline(70,linestyle='--',linewidth=.9); ax.axhline(30,linestyle='--',linewidth=.9); ax.set_ylim(0,100); ax.set_title(f'{ticker} — RSI 14 Momentum'); ax.set_ylabel('RSI'); ax.legend(); ax.grid(alpha=.16); paths['rsi']=_savefig(fig,f'{name}_12_rsi.png')
    except Exception:
        pass

    # Peer valuation chart where usable peer observations exist.
    if len(r.get('peer_rows',[])):
        peer_df=pd.DataFrame(r['peer_rows'],columns=['Peer','P/E','P/B','EV/EBITDA'])
        valid_peer=peer_df[pd.to_numeric(peer_df['P/E'],errors='coerce').notna()].copy()
        if len(valid_peer):
            fig,ax=plt.subplots(figsize=(9,5)); ax.bar(valid_peer['Peer'],valid_peer['P/E']); ax.set_title(f'{ticker} — Peer P/E Comparison'); ax.set_ylabel('P/E (x)'); ax.tick_params(axis='x',rotation=30); paths['peers']=_savefig(fig,f'{name}_11_peer_pe.png')
    return paths

# ---------- exports ----------
def build_excel(d,r,q,sc,fc,chg,cat,charts,output):
    ticker=d['ticker'].replace('.NS',''); hs=d['financials']; mc=r['mc']; tech=r['tech']; dc=r['dcf']
    summary=pd.DataFrame([
      ['Company',r['info'].get('longName',ticker)],['Ticker',ticker],['Current Price',r['price']],['GWI Score',r['score']],['Classification',r['label']],
      ['Fundamental Score',r['fund_score']],['Technical Score',tech['score']],['DCF Fair Value',dc.target],['Blended Fair Value',r['blended']],['Upside',r['upside']],
      ['WACC',dc.wacc],['Terminal Growth',dc.terminal_growth],['Reverse DCF Growth',dc.reverse_growth],['P5',mc['percentiles']['P5']],['P50',mc['percentiles']['P50']],['P95',mc['percentiles']['P95']],['VaR95',mc['var95']],['CVaR95',mc['cvar95']],['Avg Max Drawdown',mc['avg_max_dd']]
    ],columns=['Metric','Value'])
    hist=pd.DataFrame({'Period':list(pd.to_datetime(hs['revenue'].index).strftime('%Y-%m-%d')) if len(hs['revenue']) else [],'Revenue':list(hs['revenue'].values) if len(hs['revenue']) else [],'EBITDA':list(hs['ebitda'].reindex(hs['revenue'].index).values) if len(hs['revenue']) and len(hs['ebitda']) else [],'Net Income':list(hs['net_income'].reindex(hs['revenue'].index).values) if len(hs['revenue']) and len(hs['net_income']) else []})
    sens=pd.DataFrame(dc.sensitivity,index=['4%','6%','8%','10%','12%'],columns=['8%','10%','12%','14%','16%']); sens.index.name='Growth / WACC'
    peers=pd.DataFrame(r['peer_rows'],columns=['Peer','P/E','P/B','EV/EBITDA'])
    mcdf=pd.DataFrame([mc['percentiles']])
    with pd.ExcelWriter(output,engine='openpyxl') as w:
        summary.to_excel(w,'Cover',index=False); hist.to_excel(w,'Historical Financials',index=False); r['model'].to_excel(w,'5Y Projections',index=False); sens.to_excel(w,'DCF Sensitivity');
        pd.DataFrame([{'DCF':dc.target,'Peer Multiple':r['implied'],'Blended':r['blended'],'Upside':r['upside'],'WACC':dc.wacc,'Terminal Growth':dc.terminal_growth,'Reverse Growth':dc.reverse_growth}]).to_excel(w,'Valuation',index=False)
        pd.DataFrame([tech]).to_excel(w,'Technical',index=False); mcdf.to_excel(w,'Monte Carlo',index=False); peers.to_excel(w,'Peer Comparables',index=False); q.reset_index().to_excel(w,'Quarterly Intelligence',index=False); fc.to_excel(w,'Forensic Quality',index=False); sc.to_excel(w,'Scenario Engine',index=False); chg.to_excel(w,'What Changed',index=False); cat.to_excel(w,'Catalyst Dashboard',index=False)
        pd.DataFrame(list(zip(charts.keys(),[str(v) for v in charts.values()])),columns=['Chart','File']).to_excel(w,'Chart Index',index=False)
    wb=load_workbook(output)
    _format_excel(wb)
    # Cover styling
    ws=wb['Cover']; ws['A1']='GROWISEINVEST — INSTITUTIONAL EQUITY RESEARCH PACK'; ws['A1'].font=Font(bold=True,size=16,color='FFFFFF'); ws['A1'].fill=PatternFill('solid',fgColor='17365D'); ws.merge_cells('A1:B1'); ws['A1'].alignment=Alignment(horizontal='center')
    for row in range(2,ws.max_row+1):
        if str(ws.cell(row,1).value) in ['GWI Score','Classification','Upside']:
            ws.cell(row,1).font=Font(bold=True,color='17365D'); ws.cell(row,2).font=Font(bold=True)
    for s in ['Valuation','Technical','Monte Carlo']:
        if s in wb.sheetnames:
            for row in wb[s].iter_rows():
                for c in row:
                    if isinstance(c.value,float) and abs(c.value)<1 and c.column>1: c.number_format='0.0%'
    if 'DCF Sensitivity' in wb.sheetnames:
        ws=wb['DCF Sensitivity'];
        ws.conditional_formatting.add(f'B2:F6',ColorScaleRule(start_type='min',start_color='F8696B',mid_type='percentile',mid_value=50,mid_color='FFEB84',end_type='max',end_color='63BE7B'))
    # Add charts as Excel charts from native data where useful
    if 'Historical Financials' in wb.sheetnames and wb['Historical Financials'].max_row>2:
        ws=wb['Historical Financials']; ch=LineChart(); ch.title='Historical Financial Profile'; ch.y_axis.title='Value'; ch.x_axis.title='Period'; data=Reference(ws,min_col=2,max_col=4,min_row=1,max_row=ws.max_row); cats=Reference(ws,min_col=1,min_row=2,max_row=ws.max_row); ch.add_data(data,titles_from_data=True); ch.set_categories(cats); ch.height=8; ch.width=15; ws.add_chart(ch,'F2')
    if 'Scenario Engine' in wb.sheetnames:
        ws=wb['Scenario Engine']; ch=BarChart(); ch.title='Scenario Fair Value'; data=Reference(ws,min_col=4,min_row=1,max_row=ws.max_row); cats=Reference(ws,min_col=1,min_row=2,max_row=ws.max_row); ch.add_data(data,titles_from_data=True); ch.set_categories(cats); ch.height=8; ch.width=14; ws.add_chart(ch,'G2')
    # Embed every generated chart as an image in a dedicated visual sheet so the workbook is presentation-ready.
    if 'Charts' in wb.sheetnames: del wb['Charts']
    ws=wb.create_sheet('Charts'); ws.sheet_view.showGridLines=False; ws['A1']='GROWISEINVEST — VISUAL RESEARCH DASHBOARD'; ws['A1'].font=Font(bold=True,size=16,color='FFFFFF'); ws['A1'].fill=PatternFill('solid',fgColor='17365D'); ws.merge_cells('A1:H1')
    row=3
    for chart_name,chart_path in charts.items():
        ws.cell(row,1,chart_name.replace('_',' ').title()).font=Font(bold=True,size=12,color='17365D')
        try:
            img=XLImage(str(chart_path)); img.width=760; img.height=360; ws.add_image(img,f'A{row+1}')
            row += 22
        except Exception:
            ws.cell(row+1,1,str(chart_path))
            row += 2
    wb.save(output)

def build_word(d,r,q,sc,fc,chg,cat,charts,output):
    ticker=d['ticker'].replace('.NS',''); company=r['info'].get('longName',ticker); dc=r['dcf']; mc=r['mc']; hs=d['financials']
    doc=Document(); sec=doc.sections[0]; sec.top_margin=Inches(.55); sec.bottom_margin=Inches(.55); sec.left_margin=Inches(.65); sec.right_margin=Inches(.65)
    _add_doc_title(doc,'GROWISEINVEST — INSTITUTIONAL EQUITY RESEARCH REPORT',f'{company} ({ticker}) • Generated {datetime.now().strftime("%d %b %Y, %H:%M")}')
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; rr=p.add_run(f'Current Price: {_money(r["price"])}   |   GWI Score: {r["score"]:.1f}/100   |   Classification: {r["label"]}'); rr.bold=True; rr.font.size=Pt(12)
    doc.add_heading('Executive Investment Intelligence',level=1)
    bullets=[]
    if np.isfinite(r.get('upside',np.nan)): bullets.append(f'Modeled blended fair value: {_money(r["blended"])} ({_pct(r["upside"])} vs current price).')
    bullets.append(f'DCF: {_money(dc.target)}; WACC {_pct(dc.wacc)}; terminal growth {_pct(dc.terminal_growth)}.')
    bullets.append(f'Monte Carlo P5/P50/P95: {_money(mc["percentiles"]["P5"])}/{_money(mc["percentiles"]["P50"])}/{_money(mc["percentiles"]["P95"])}.')
    bullets.append(f'Risk: VaR95 {_pct(mc["var95"])}, CVaR95 {_pct(mc["cvar95"])}, average max drawdown {_pct(mc["avg_max_dd"])}.')
    bullets.append('Accounting model status: conditional reconciliation; bridge used in the forecast balance identity.' if r.get('balance_ok') else 'Accounting model status: review required.')
    for b in bullets: doc.add_paragraph(b,style='List Bullet')
    doc.add_heading('1. Price & Technical Structure',level=1); doc.add_picture(str(charts['price']),width=Inches(6.9))
    doc.add_heading('2. Historical Financial Profile',level=1); doc.add_picture(str(charts['financials']),width=Inches(6.9))
    hist=pd.DataFrame({'Metric':['Revenue','Revenue CAGR','EBITDA','Net Income','CFO','FCF','ROE','Debt/Equity'], 'Value':[
      _money(hs['revenue'].iloc[0]) if len(hs['revenue']) else 'N/A',_pct(r['assumptions'].get('revenue_growth')), _money(hs['ebitda'].iloc[0]) if len(hs['ebitda']) else 'N/A',_money(hs['net_income'].iloc[0]) if len(hs['net_income']) else 'N/A',_money(hs['cfo'].iloc[0]) if len(hs['cfo']) else 'N/A',_money(r['fcf'].iloc[0]) if len(r['fcf']) else 'N/A',_pct(r.get('roe')), _pct(hs['debt'].iloc[0]/hs['equity'].iloc[0]) if len(hs['debt']) and len(hs['equity']) and hs['equity'].iloc[0] else 'N/A']})
    _doc_table(doc,hist,'Key Financial Metrics')
    doc.add_heading('3. Five-Year Financial Model',level=1); doc.add_picture(str(charts['projections']),width=Inches(6.9)); _doc_table(doc,r['model'][['FY+%d'%i if False else 'FY+%d'%int(i) for i in r['model']['FY+%']]].copy() if False else r['model'].round(0),'Forecast Model',max_rows=10)
    doc.add_heading('4. Discounted Cash Flow & Valuation',level=1); doc.add_picture(str(charts['dcf']),width=Inches(6.5))
    if 'valuation' in charts: doc.add_picture(str(charts['valuation']),width=Inches(6.3))
    val=pd.DataFrame({'Valuation Measure':['DCF Fair Value','Peer Multiple Implied','Blended Fair Value','Current Price','Blended Upside','WACC','Terminal Growth','Reverse DCF Growth'], 'Value':[_money(dc.target),_money(r['implied']),_money(r['blended']),_money(r['price']),_pct(r['upside']),_pct(dc.wacc),_pct(dc.terminal_growth),_pct(dc.reverse_growth)]}); _doc_table(doc,val)
    doc.add_heading('5. Probabilistic Quant & Risk',level=1); doc.add_picture(str(charts['mc']),width=Inches(6.9))
    if 'risk_pie' in charts: doc.add_picture(str(charts['risk_pie']),width=Inches(5.8))
    risk=pd.DataFrame({'Risk Metric':['P5','P50','P95','Positive Probability','>20% Gain Probability','>20% Loss Probability','VaR95','CVaR95','Average Max Drawdown'], 'Value':[_money(mc['percentiles']['P5']),_money(mc['percentiles']['P50']),_money(mc['percentiles']['P95']),_pct(mc['positive_prob']),_pct(mc['gain20_prob']),_pct(mc['loss20_prob']),_pct(mc['var95']),_pct(mc['cvar95']),_pct(mc['avg_max_dd'])]}); _doc_table(doc,risk)
    if len(q) and 'quarterly' in charts:
        doc.add_heading('6. Earnings Intelligence & Fundamental Inflection',level=1); doc.add_picture(str(charts['quarterly']),width=Inches(6.9)); _doc_table(doc,q.reset_index().tail(8).round(4),'Quarterly Trend',max_rows=8)
    doc.add_heading('7. Scenario Engine',level=1); doc.add_picture(str(charts['scenario']),width=Inches(6.0)); _doc_table(doc,sc.round(4),'Bear / Base / Bull Scenarios')
    doc.add_heading('8. Earnings Quality & Forensic Review',level=1); _doc_table(doc,fc.round(4),'Forensic Indicators'); doc.add_paragraph('Interpretation flags: '+('; '.join(_forensic(d,r)[1]) if _forensic(d,r)[1] else 'No major automated forensic flag triggered.') )
    doc.add_heading('9. What Changed',level=1); _doc_table(doc,chg.round(4),'Latest vs Prior Reported Period',max_rows=15)
    doc.add_heading('10. Catalyst & Signal Dashboard',level=1); _doc_table(doc,cat.round(4),'Potential Catalysts / Signals')
    if 'peers' in charts: doc.add_heading('Peer Valuation Context',level=2); doc.add_picture(str(charts['peers']),width=Inches(6.4))
    if 'score' in charts:
        doc.add_heading('11. Integrated GWI Score',level=1); doc.add_picture(str(charts['score']),width=Inches(5.4)); doc.add_paragraph(f'Integrated score: {r["score"]:.1f}/100. This is an analytical classification, not investment advice.')
    doc.add_heading('12. Analyst Control Gates & Limitations',level=1)
    for b in [
      'Source data should be independently verified before investment use.',
      'Forecasts are model outputs, not reported company guidance.',
      'The three-statement balance identity uses a reconciliation bridge and therefore does not constitute independent full accounting validation.',
      'Earnings intelligence is source-data trend analysis; no proprietary sell-side estimate consensus is assumed when unavailable.',
      'Monte Carlo outcomes are probabilistic scenarios, not price targets or guarantees.',
      'Final BUY / HOLD / AVOID / REVIEW judgement remains with the analyst.'
    ]: doc.add_paragraph(b,style='List Bullet')
    doc.save(output)

# ---------- public entry ----------
def generate_institutional_pack(symbol, run_research_fn, fetch_fn, sims=5000):
    d,r=run_research_fn(symbol,sims=sims)
    q,qmeta=_quarterly_intelligence(d)
    sc=_scenario(d,r); fc,flags=_forensic(d,r); chg=_what_changed(d,r); cat=_catalyst(d,r,q)
    charts=build_charts(d,r,q,sc,fc,chg,r['mc'])
    ticker=d['ticker'].replace('.NS','')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    xlsx=OUT/f'GroWise_{ticker}_Institutional_Research_{stamp}.xlsx'
    docx=OUT/f'GroWise_{ticker}_Institutional_Research_{stamp}.docx'
    build_excel(d,r,q,sc,fc,chg,cat,charts,xlsx)
    build_word(d,r,q,sc,fc,chg,cat,charts,docx)
    return {'ticker':ticker,'company':r['info'].get('longName',ticker),'excel':str(xlsx),'word':str(docx),'charts':[str(x) for x in charts.values()],'score':r['score'],'classification':r['label']}
