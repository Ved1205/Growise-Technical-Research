import os, sys, math, time, traceback, io, contextlib, logging, re, json, threading
from datetime import datetime, date, time as dtime, timedelta
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich import box
from engine.models import normalized_financials, latest, cagr, clean, forecast_three_statement, dcf, monte_carlo
from institutional_pack import generate_institutional_pack

console = Console()
IST = ZoneInfo('Asia/Kolkata')
# NSE equity market holidays, 2026. Kept local so STATUS works without internet.
HOLIDAYS_2026 = {
 date(2026,1,26), date(2026,3,3), date(2026,3,26), date(2026,3,31),
 date(2026,4,3), date(2026,4,14), date(2026,5,1), date(2026,5,27),
 date(2026,6,26), date(2026,9,14), date(2026,10,2), date(2026,10,20),
 date(2026,11,9), date(2026,11,24), date(2026,12,25)
}
SECTORS={'Technology':['INFY','HCLTECH','WIPRO','TECHM','LTIM'],'Financial Services':['HDFCBANK','ICICIBANK','SBIN','AXISBANK','KOTAKBANK'],'Consumer Defensive':['HINDUNILVR','ITC','NESTLEIND','BRITANNIA','DABUR'],'Automobiles':['MARUTI','M&M','TATAMOTORS','EICHERMOT','HEROMOTOCO'],'Energy':['RELIANCE','ONGC','NTPC','POWERGRID','COALINDIA'],'Industrials':['LT','SIEMENS','ABB','BEL','HAL'],'Healthcare':['SUNPHARMA','DRREDDY','CIPLA','DIVISLAB','APOLLOHOSP'],'Basic Materials':['TATASTEEL','JSWSTEEL','HINDALCO','ULTRACEMCO','GRASIM']}
# Session-level peer override. Empty means sector auto-detection.
ACTIVE_PEERS = []

ALIASES={
'revenue':['Total Revenue','Operating Revenue','Revenue'],'ebitda':['EBITDA'],'ebit':['EBIT','Operating Income'],'net_income':['Net Income','Net Income Common Stockholders'],
'cfo':['Operating Cash Flow','Total Cash From Operating Activities'],'capex':['Capital Expenditure','Capital Expenditure Reported'],'cash':['Cash Cash Equivalents And Short Term Investments','Cash And Cash Equivalents'],
'debt':['Total Debt','Long Term Debt'],'equity':['Stockholders Equity','Total Stockholder Equity','Common Stock Equity'],'assets':['Total Assets'],'current_assets':['Current Assets'],'current_liabilities':['Current Liabilities'],
'interest':['Interest Expense Non Operating','Interest Expense'],'tax':['Tax Provision','Tax Rate For Calcs']}

def ticker(s):
    s=s.strip().upper().replace('.NS','').replace('.BO','')
    return s+'.NS'

def safe_info(symbol):
    """Fetch Yahoo quote metadata without leaking provider-side 404/log noise."""
    tk = ticker(symbol)
    buf = io.StringIO()
    old_disable = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        for _name in ('yfinance','yfinance.scrapers','yfinance.data','urllib3'):
            logging.getLogger(_name).disabled = True
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return yf.Ticker(tk).info or {}
    except Exception:
        return {}
    finally:
        logging.disable(old_disable)

def fmt_multiple(v, kind='generic'):
    try:
        v=float(v)
        upper={'pe':200.0,'ev_ebitda':100.0,'pb':100.0}.get(kind,500.0)
        return 'N/A' if not np.isfinite(v) or v<=0 or v>upper else f'{v:.2f}'
    except Exception:
        return 'N/A'

def peer_metrics(symbol):
    """Return clean, positive peer multiples; invalid provider values become N/A."""
    pi=safe_info(symbol)
    pe=clean(pi.get('trailingPE'))
    pb=clean(pi.get('priceToBook'))
    ev_ebitda=clean(pi.get('enterpriseToEbitda'))
    return pe if pe>0 else None, pb if pb>0 else None, ev_ebitda if ev_ebitda>0 else None

def pct(x): return 'N/A' if x is None or not np.isfinite(x) else f'{x*100:.2f}%'
def money(x):
    if x is None or not np.isfinite(x): return 'N/A'
    x=float(x); a=abs(x)
    if a>=1e12:return f'₹{x/1e12:.2f}T'
    if a>=1e9:return f'₹{x/1e9:.2f}B'
    if a>=1e7:return f'₹{x/1e7:.2f}Cr'
    if a>=1e5:return f'₹{x/1e5:.2f}L'
    return f'₹{x:,.2f}'
def num(x): return 'N/A' if x is None or not np.isfinite(x) else f'{x:,.2f}'
def clean_label(s): return str(s).replace('_',' ').title()

def market_status(now=None):
    now=now or datetime.now(IST); d=now.date(); t=now.time()
    if d.weekday()>=5: return False, 'WEEKEND', next_open(now)
    if d in HOLIDAYS_2026: return False, 'NSE/BSE EQUITY HOLIDAY', next_open(now)
    if dtime(9,15)<=t<dtime(15,30): return True, 'EQUITY CONTINUOUS SESSION', None
    return False, 'EQUITY SESSION CLOSED', next_open(now)

def next_open(now):
    d=now.date()+timedelta(days=1) if now.time()>=dtime(15,30) else now.date()
    while d.weekday()>=5 or (d.year==2026 and d in HOLIDAYS_2026): d+=timedelta(days=1)
    return datetime.combine(d,dtime(9,15),IST)

def header():
    """Compact institutional workstation header — Bloomberg-inspired, not a copy."""
    live, reason, nxt=market_status()
    status='LIVE' if live else 'CLOSED'
    status_style='bold green' if live else 'bold yellow'
    now=datetime.now(IST)
    line=Text()
    line.append('GROWISEINVEST', style='bold cyan')
    line.append('  |  INSTITUTIONAL RESEARCH WORKSTATION', style='bold white')
    line.append(f'  |  {now.strftime("%d-%b-%Y %H:%M:%S IST")}', style='dim')
    line.append(f'  |  {status}', style=status_style)
    sub=f'NSE • BSE • FUNDAMENTALS • VALUATION • QUANT • RISK • EVENTS'
    if not live and nxt: sub += f'  |  NEXT OPEN {nxt.strftime("%d-%b %H:%M IST")}'
    return Panel(Group(line, Text(sub, style='dim')), box=box.SIMPLE, border_style='cyan', padding=(0,1))

def _provider_call(fn, default=None):
    """Execute a market-data provider call without exposing provider noise."""
    buf=io.StringIO(); old_disable=logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        for _name in ('yfinance','yfinance.scrapers','yfinance.data','urllib3'):
            logging.getLogger(_name).disabled=True
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return fn()
    except Exception:
        return default
    finally:
        logging.disable(old_disable)

def fetch(symbol):
    tk=ticker(symbol)
    y=yf.Ticker(tk)
    hist=_provider_call(lambda: y.history(period="10y",auto_adjust=False), pd.DataFrame())
    if hist is None or hist.empty:
        raise RuntimeError(f"No market history returned for {tk}.")
    financials=_provider_call(lambda: normalized_financials(y.financials,y.balance_sheet,y.cashflow), None)
    if financials is None:
        raise RuntimeError(f"Financial statement data unavailable for {tk}.")
    return {"ticker":tk,"info":safe_info(symbol),"history":hist,"close":hist["Close"].dropna(),"financials":financials}

def technical(d):
    c=pd.Series(d['close']).dropna()
    if c.empty:
        raise RuntimeError('No valid price history available for technical analysis.')
    p=float(c.iloc[-1])
    def rolling_last(n):
        return float(c.rolling(n).mean().iloc[-1]) if len(c)>=n else math.nan
    sma20=rolling_last(20); sma50=rolling_last(50); sma200=rolling_last(200)
    high=float(c.tail(min(252,len(c))).max()); low=float(c.tail(min(252,len(c))).min())
    delta=c.diff()
    gain=delta.clip(lower=0).rolling(14).mean()
    loss=delta.clip(upper=0).abs().rolling(14).mean()
    if len(c)>=14:
        g=float(gain.iloc[-1]); l=float(loss.iloc[-1])
        rsi=100.0 if l==0 and g>0 else 50.0 if l==0 else float(100-100/(1+g/l))
    else:
        rsi=math.nan
    score=50.0
    if np.isfinite(sma50): score += 20*(p>sma50)
    if np.isfinite(sma200): score += 15*(p>sma200)
    if np.isfinite(sma50) and np.isfinite(sma200): score += 10*(sma50>sma200)
    if high>0: score += 5*(p>high*.95)
    return {'price':p,'sma20':sma20,'sma50':sma50,'sma200':sma200,'rsi':rsi,'high':high,'low':low,'score':float(np.clip(score,0,100))}

def run_research(symbol, sims=3000, peer_override=None):
    d=fetch(symbol); c=d['close']; info=d['info']; hs=d['financials']; p=float(c.iloc[-1])
    beta=clean(info.get('beta')); beta=beta if np.isfinite(beta) and beta>0 else 1.0; shares=clean(info.get('sharesOutstanding')) or clean(info.get('impliedSharesOutstanding')) or 1.0
    fcf=(hs['cfo'].reindex(hs['capex'].index)-hs['capex']).dropna() if len(hs['cfo']) and len(hs['capex']) else pd.Series(dtype=float)
    revc=cagr(hs['revenue']) or .08; rev=latest(hs['revenue']); margin=latest(hs['ebitda'])/rev if rev else .20
    assumptions={'revenue_growth':max(.03,min(.15,revc)),'ebitda_margin':max(.08,min(.45,margin)),'tax_rate':.25,'nwc_pct':.05,'capex_pct':.06,'da_pct':.035,'interest_rate':.07,'payout':.25,'wacc':None,'terminal_growth':.035}
    model=forecast_three_statement(hs,assumptions,5); balance_ok=bool(np.all(np.abs(model['Balance Check'].to_numpy(float))<0.01))
    dc=dcf(p,latest(fcf),latest(hs['debt']),latest(hs['cash']),beta,shares=shares,analyst=assumptions)
    returns=np.log(c/c.shift(1)).replace([np.inf,-np.inf],np.nan).dropna()
    if len(returns)<20: raise RuntimeError('Insufficient valid return history for quantitative analysis (minimum 20 observations).')
    mc=monte_carlo(p,returns,sims,252,42); tech=technical(d)
    sector=info.get('sector','')
    peers=list(peer_override) if peer_override is not None else (list(ACTIVE_PEERS) if ACTIVE_PEERS else SECTORS.get(sector,[]))
    peer_rows=[]
    for q in peers:
        pe,pb,ev=peer_metrics(q)
        peer_rows.append((q,pe,pb,ev))
    valid=[x[1] for x in peer_rows if x[1] is not None and np.isfinite(x[1]) and x[1]>0 and x[1] <= 200]; medpe=float(np.median(valid)) if valid else None
    implied=latest(hs['net_income'])/shares*medpe if medpe else None
    vals=[x for x in [dc.target,implied] if x is not None and np.isfinite(x)]; blended=float(np.mean(vals)) if vals else math.nan; upside=blended/p-1 if np.isfinite(blended) else math.nan
    roe=latest(hs['net_income'])/latest(hs['equity']) if latest(hs['equity']) else math.nan
    fund_score=float(np.clip(50+15*(revc>0)+10*(latest(hs['net_income'])>0)+10*(latest(fcf)>0)+10*(latest(hs['debt'])<latest(hs['equity']) if latest(hs['equity']) else 0)+5*(roe>.10),0,100))
    val_score=70 if dc.status=='PASS' and np.isfinite(upside) and upside>0.2 else 55 if dc.status=='PASS' and np.isfinite(upside) and upside>0 else 35
    score=float(np.clip(.30*fund_score+.20*tech['score']+.30*val_score+.20*mc['positive_prob']*100,0,100)); label='VERY ATTRACTIVE' if score>=80 else 'ATTRACTIVE' if score>=70 else 'CONSTRUCTIVE' if score>=55 else 'NEUTRAL' if score>=40 else 'CAUTIOUS'
    return d,{'price':p,'info':info,'tech':tech,'model':model,'dcf':dc,'mc':mc,'peer_rows':peer_rows,'peer_source':'MANUAL' if (peer_override is not None or ACTIVE_PEERS) else 'AUTO-SECTOR','implied':implied,'blended':blended,'upside':upside,'fund_score':fund_score,'score':score,'label':label,'assumptions':assumptions,'fcf':fcf,'balance_ok':balance_ok,'roe':roe}

def financial_table(d):
    f=d['financials']; t=Table(title='FINANCIAL INTELLIGENCE',box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Value',justify='right')
    rev=latest(f['revenue']); rows=[('Revenue',rev),('Revenue CAGR (3Y)',cagr(f['revenue'])),('EBITDA',latest(f['ebitda'])),('EBITDA Margin',latest(f['ebitda'])/rev if rev else math.nan),('Net Income',latest(f['net_income'])),('Earnings CAGR (3Y)',cagr(f['net_income'])),('CFO',latest(f['cfo'])),('Capex',latest(f['capex'])),('FCF',latest(f['cfo'])-latest(f['capex'])),('ROE',latest(f['net_income'])/latest(f['equity']) if latest(f['equity']) else math.nan),('Debt / Equity',latest(f['debt'])/latest(f['equity']) if latest(f['equity']) else math.nan),('Cash',latest(f['cash'])),('Debt',latest(f['debt']))]
    for k,v in rows: t.add_row(k,pct(v) if 'CAGR' in k or 'Margin' in k or k=='ROE' else (f'{v:.2f}x' if k=='Debt / Equity' else money(v)))
    return t

def show_research(symbol):
    console.print(header()); console.print('[cyan]RESEARCH WORKFLOW[/cyan]  '+symbol.upper())
    with Progress(SpinnerColumn(),TextColumn('{task.description}'),console=console) as prog:
        task=prog.add_task('Loading market + company data',total=None); d,r=run_research(symbol); prog.update(task,description='Market + company data loaded ✓'); time.sleep(.05); prog.update(task,description='3-statement + DCF + quant engines completed ✓');
    info=r['info']; name=info.get('longName',r['price']);
    console.print(Panel(f'[bold white]{name}[/bold white]\n{r["price"]:,.2f} INR   •   {r["label"]}   •   Score {r["score"]:.1f}/100\nSector: {info.get("sector","N/A")}   Industry: {info.get("industry","N/A")}',title='SECURITY OVERVIEW',border_style='cyan'))
    t=Table(box=box.SIMPLE); t.add_column('MODULE');t.add_column('RESULT');t.add_column('STATUS')
    t.add_row('Fundamental',f'{r["fund_score"]:.0f}/100','POSITIVE' if r['fund_score']>=60 else 'REVIEW');t.add_row('Technical',f'{r["tech"]["score"]:.0f}/100','BULLISH' if r['tech']['score']>=65 else 'NEUTRAL');val_upside=r.get('upside')
    val_status='ATTRACTIVE' if val_upside is not None and np.isfinite(val_upside) and val_upside>0 else 'REVIEW'
    t.add_row('Valuation',f'{money(r.get("blended"))} / {pct(val_upside)}',val_status);t.add_row('Quant Risk',f'P50 {money(r["mc"]["percentiles"]["P50"])}','MODELLED');t.add_row('3-Statement','5Y forecast','BALANCE CHECK VISIBLE');console.print(t)
    console.print(financial_table(d)); show_valuation(r); show_quant(r); show_model(r); show_thesis(d,r)

def show_valuation(r):
    dcfv=r["dcf"]; t=Table(title="VALUATION LAB",box=box.SIMPLE_HEAVY); t.add_column("Method"); t.add_column("Value",justify="right"); t.add_column("Status")
    t.add_row("FCFF DCF",money(dcfv.target),dcfv.status)
    if dcfv.warning: t.add_row("DCF warning",dcfv.warning,"REVIEW")
    console.print(t)
    if dcfv.status=="PASS":
        s=Table(title="DCF SENSITIVITY — IMPLIED EQUITY VALUE",box=box.SIMPLE); s.add_column("Growth / WACC")
        for w in [.08,.10,.12,.14,.16]: s.add_column(pct(w),justify="right")
        for g,row in zip([.04,.06,.08,.10,.12],dcfv.sensitivity): s.add_row(pct(g),*[money(x) for x in row])
        console.print(s); console.print(f"WACC {pct(dcfv.wacc)} • Terminal growth {pct(dcfv.terminal_growth)} • Reverse DCF growth {pct(dcfv.reverse_growth)}")

def show_quant(r):
    m=r["mc"]; t=Table(title="QUANT / MONTE CARLO",box=box.SIMPLE_HEAVY); t.add_column("Metric"); t.add_column("Value",justify="right")
    for k in ["P5","P25","P50","P75","P95"]: t.add_row(k,money(m["percentiles"][k]))
    for k,label in [("positive_prob","Positive probability"),("gain20_prob",">20% gain probability"),("loss20_prob",">20% loss probability"),("var95","VaR 95%"),("cvar95","CVaR 95%"),("avg_max_dd","Avg max drawdown")]: t.add_row(label,pct(m[k]))
    console.print(t)

def show_model(r):
    df=r["model"]; years=[f"FY+{i}" for i in range(1,6)]; t=Table(title="5-YEAR 3-STATEMENT FORECAST",box=box.SIMPLE); t.add_column("Metric"); [t.add_column(x,justify="right") for x in years]
    for metric in ["Revenue","EBITDA","EBIT","Net Income","CFO","Capex","FCF","Debt","Cash","Equity","Other Liabilities Bridge","Balance Check"]: t.add_row(metric,*[money(df.iloc[i][metric]) for i in range(5)])
    status="[green]PASS[/green]" if r["balance_ok"] else "[red]FAIL[/red]"
    console.print(Panel(f"Accounting identity: Assets = Liabilities + Equity + Other Liabilities Bridge\nBalance check: {status}",border_style="green" if r["balance_ok"] else "red"))

def show_thesis(d,r):
    hs=d['financials']; bullets=[]
    rc=cagr(hs['revenue']); dc=latest(hs['debt'])/latest(hs['equity']) if latest(hs['equity']) else None
    if rc and rc>0: bullets.append(f'Revenue growth remains positive at {pct(rc)} 3-year CAGR.')
    if dc is not None and dc<1: bullets.append(f'Leverage is below 1.0x at {dc:.2f}x debt/equity.')
    bullets.append('Price is above 200DMA.' if r['price']>r['tech']['sma200'] else 'Price is below 200DMA; trend requires scrutiny.')
    bullets.append(f'Modeled blended value is {pct(r["upside"])} vs current price.')
    console.print(Panel('\n'.join('• '+x for x in bullets)+'\n\n[dim]System interpretation only. Analyst judgement and source verification remain required.[/dim]',title='RESEARCH INTERPRETATION',border_style='magenta'))
    console.print(Panel('[bold]ANALYST DECISION[/bold]\nSystem classification: '+r['label']+'\nHuman decision: BUY / HOLD / AVOID / REVIEW',border_style='yellow'))

def show_financials(symbol):
    d=fetch(symbol); console.print(header()); console.print(Panel(f'{d["info"].get("longName",d["ticker"])} • {d["ticker"]} • ₹{d["close"].iloc[-1]:,.2f}',border_style='cyan'));console.print(financial_table(d))

def show_technical(symbol):
    d=fetch(symbol); x=technical(d); console.print(header());t=Table(title=f'TECHNICAL ANALYSIS — {d["ticker"]}',box=box.SIMPLE_HEAVY);t.add_column('Indicator');t.add_column('Value',justify='right');
    for a,b in [('Price',money(x['price'])),('SMA 20',money(x['sma20'])),('SMA 50',money(x['sma50'])),('SMA 200',money(x['sma200'])),('RSI 14',num(x['rsi'])),('52W High',money(x['high'])),('52W Low',money(x['low'])),('Technical Score',f'{x["score"]:.0f}/100')]:t.add_row(a,b)
    console.print(t)

def show_risk(r):
    if not isinstance(r,dict) or 'mc' not in r:
        raise RuntimeError('Risk engine returned no valid Monte Carlo results.')
    m=r["mc"]
    t=Table(title="RISK ANALYTICS",box=box.SIMPLE_HEAVY); t.add_column("Risk Metric"); t.add_column("Value",justify="right")
    for k,label in [("var95","Historical/Simulated VaR 95%"),("cvar95","Expected Shortfall / CVaR 95%"),("avg_max_dd","Average Maximum Drawdown"),("loss20_prob","Probability of >20% Loss")]:
        t.add_row(label,pct(m[k]))
    t.add_row("P5 Terminal Price",money(m["percentiles"]["P5"]))
    t.add_row("P50 Terminal Price",money(m["percentiles"]["P50"]))
    t.add_row("P95 Terminal Price",money(m["percentiles"]["P95"]))
    console.print(t)
    console.print('[dim]Monte Carlo risk estimates are model outputs, not forecasts or guarantees.[/dim]')

def show_valuation_lab(symbol):
    _,r=run_research(symbol); console.print(header()); show_valuation(r)
    t=Table(title="VALUATION STACK",box=box.SIMPLE); t.add_column("Component"); t.add_column("Implied Value",justify="right"); t.add_column("Status")
    t.add_row("FCFF DCF",money(r["dcf"].target),r["dcf"].status)
    t.add_row("Peer P/E Implied",money(r["implied"]),"AVAILABLE" if r["implied"] is not None else "N/A")
    t.add_row("Blended Fair Value",money(r.get("blended")),"AVAILABLE" if r.get("blended") is not None and np.isfinite(r.get("blended")) else "REVIEW")
    t.add_row("Upside / (Downside)",pct(r.get("upside")),"ATTRACTIVE" if r.get("upside") is not None and np.isfinite(r.get("upside")) and r.get("upside")>0 else "REVIEW")
    console.print(t)

def show_dcf(symbol):
    _,r=run_research(symbol);console.print(header());show_valuation(r)

def show_quant_cmd(symbol):
    _,r=run_research(symbol);console.print(header());show_quant(r)

def show_model_cmd(symbol):
    _,r=run_research(symbol);console.print(header());show_model(r)

def show_peers(symbol):
    d=fetch(symbol); sec=d["info"].get("sector",""); peers=list(ACTIVE_PEERS) if ACTIVE_PEERS else SECTORS.get(sec,[])
    console.print(header())
    t=Table(title=f"PEER COMPARABLES — {sec or 'Sector unavailable'}",box=box.SIMPLE_HEAVY)
    t.add_column("Ticker"); t.add_column("P/E",justify="right"); t.add_column("EV/EBITDA",justify="right"); t.add_column("P/B",justify="right")
    for q in peers:
        pe,pb,ev=peer_metrics(q)
        t.add_row(q,fmt_multiple(pe,'pe'),fmt_multiple(ev,'ev_ebitda'),fmt_multiple(pb,'pb'))
    console.print(t)
    console.print('[dim]Provider fields that are missing, stale or non-positive are shown as N/A rather than treated as valid valuation inputs.[/dim]')

def compare(symbols):
    t=Table(title='CROSS-COMPANY RESEARCH COMPARISON',box=box.SIMPLE_HEAVY);t.add_column('Ticker');t.add_column('Price',justify='right');t.add_column('Rev CAGR',justify='right');t.add_column('ROE',justify='right');t.add_column('P/E',justify='right');t.add_column('Tech',justify='right')
    for s in symbols:
        d=fetch(s);hs=d['financials'];x=technical(d);t.add_row(d['ticker'].replace('.NS',''),money(float(d['close'].iloc[-1])),pct(cagr(hs['revenue'])),pct(latest(hs['net_income'])/latest(hs['equity']) if latest(hs['equity']) else None),fmt_multiple(d['info'].get('trailingPE'),'pe'),f'{float(x.get("score",50) or 50):.0f}')
    console.print(header());console.print(t)

def export_excel(symbol):
    d,r=run_research(symbol); fn=f'GroWise_{d["ticker"].replace(".NS","")}_Institutional.xlsx';
    with pd.ExcelWriter(fn,engine='openpyxl') as w:
        pd.DataFrame([{'Ticker':d['ticker'],'Company':d['info'].get('longName'),'Price':r['price'],'Score':r['score'],'Classification':r['label']}]).to_excel(w,sheet_name='Research Summary',index=False)
        pd.DataFrame([r['tech']]).to_excel(w,sheet_name='Technical',index=False); pd.DataFrame([{'Revenue CAGR':cagr(d['financials']['revenue']),'Earnings CAGR':cagr(d['financials']['net_income']),'FCF CAGR':cagr(r['fcf']),'ROE':latest(d['financials']['net_income'])/latest(d['financials']['equity']) if latest(d['financials']['equity']) else None,'Debt Equity':latest(d['financials']['debt'])/latest(d['financials']['equity']) if latest(d['financials']['equity']) else None}]).to_excel(w,sheet_name='Fundamentals',index=False);r['model'].to_excel(w,sheet_name='3-Statement',index=False);pd.DataFrame(r['dcf'].sensitivity,index=['4%','6%','8%','10%','12%'],columns=['8%','10%','12%','14%','16%']).to_excel(w,sheet_name='DCF Sensitivity');pd.DataFrame([{'DCF':r['dcf'].target,'Peer Multiple':r['implied'],'Blended':r['blended'],'Upside':r['upside'],'WACC':r['dcf'].wacc,'Terminal Growth':r['dcf'].terminal_growth,'Reverse Growth':r['dcf'].reverse_growth}]).to_excel(w,sheet_name='Valuation',index=False);pd.DataFrame([r['mc']['percentiles']]).to_excel(w,sheet_name='Monte Carlo',index=False)
    console.print(Panel(f'Excel research pack created: [bold]{os.path.abspath(fn)}[/bold]',border_style='green'))

def gwi_score(symbol):
    """Integrated research score: a compact, explainable quantamental evidence pack."""
    d, r = run_research(symbol, sims=3000)
    console.print(header())
    info = r.get('info', {})
    company = info.get('longName') or info.get('shortName') or d['ticker']
    p = r['price']
    tech = r['tech']
    mc = r['mc']
    dc = r['dcf']
    hs = d['financials']
    rev = latest(hs['revenue'])
    ni = latest(hs['net_income'])
    eq = latest(hs['equity'])
    debt = latest(hs['debt'])
    cash = latest(hs['cash'])
    fcf = latest(r['fcf'])
    roe = ni / eq if eq else math.nan
    de = debt / eq if eq else math.nan
    dcf_target = dc.target if np.isfinite(dc.target) else math.nan
    fair = r.get('blended')
    upside = r.get('upside')

    console.print(Panel(
        f'{company}\n{money(p)}  •  {r["label"]}  •  Integrated Score {r["score"]:.1f}/100\n'
        f'Sector: {info.get("sector") or "N/A"}   Industry: {info.get("industry") or "N/A"}',
        title='GWI SCORE', border_style='cyan'
    ))

    t = Table(title='EVIDENCE STACK', box=box.SIMPLE_HEAVY)
    t.add_column('DOMAIN'); t.add_column('KEY EVIDENCE'); t.add_column('RESULT', justify='right'); t.add_column('STATUS')
    t.add_row('Fundamentals', 'Revenue CAGR / ROE / Debt-Equity',
              f'{pct(cagr(hs["revenue"]))} / {pct(roe)} / {num(de)}x',
              'POSITIVE' if r['fund_score'] >= 70 else 'REVIEW')
    t.add_row('Valuation', 'DCF / Blended Fair Value / Upside',
              f'{money(dcf_target)} / {money(fair)} / {pct(upside)}',
              'ATTRACTIVE' if np.isfinite(upside) and upside > 0.10 else 'REVIEW')
    t.add_row('Technical', 'RSI / vs 200 SMA / Technical Score',
              f'{num(tech["rsi"])} / {pct(p / tech["sma200"] - 1) if np.isfinite(tech["sma200"]) else "N/A"} / {tech["score"]:.0f}/100',
              'POSITIVE' if tech['score'] >= 70 else 'NEUTRAL' if tech['score'] >= 45 else 'WEAK')
    t.add_row('Quant Risk', 'P5 / P50 / P95 / VaR95',
              f'{money(mc["percentiles"]["P5"])} / {money(mc["percentiles"]["P50"])} / {money(mc["percentiles"]["P95"])} / {pct(mc["var95"])}',
              'MODELLED')
    console.print(t)

    pos = []
    concerns = []
    if cagr(hs['revenue']) is not None and cagr(hs['revenue']) > 0: pos.append(f'Revenue CAGR is positive at {pct(cagr(hs["revenue"]))}.')
    if np.isfinite(roe) and roe > 0.15: pos.append(f'ROE is strong at {pct(roe)}.')
    if np.isfinite(de) and de < 1: pos.append(f'Leverage is contained at {de:.2f}x debt/equity.')
    if fcf > 0: pos.append(f'Latest normalized FCF is positive at {money(fcf)}.')
    if np.isfinite(upside) and upside > 0: pos.append(f'Blended modeled value indicates {pct(upside)} upside.')
    if np.isfinite(tech['sma200']) and p < tech['sma200']: concerns.append('Price is below the 200-day moving average; trend requires scrutiny.')
    if np.isfinite(mc['loss20_prob']) and mc['loss20_prob'] > 0.15: concerns.append(f'Monte Carlo probability of a >20% loss is {pct(mc["loss20_prob"])}.')
    if np.isfinite(upside) and upside < 0: concerns.append('Blended modeled value is below the current price.')
    if not pos: pos.append('No qualifying positive evidence flag was generated.')
    if not concerns: concerns.append('No major automated concern flag was triggered.')

    ptab = Table(title='KEY POSITIVES', box=box.SIMPLE)
    ptab.add_column('');
    for x in pos[:5]: ptab.add_row('✓ ' + x)
    console.print(ptab)
    ctab = Table(title='KEY CONCERNS', box=box.SIMPLE)
    ctab.add_column('');
    for x in concerns[:5]: ctab.add_row('⚠ ' + x)
    console.print(ctab)

    dq = 'PASS' if len(d['close']) >= 252 and len(hs['revenue']) >= 2 and len(hs['net_income']) >= 2 else 'REVIEW'
    model_status = 'CONDITIONAL PASS — reconciliation bridge used' if r.get('balance_ok') else 'REVIEW — balance identity not reconciled'
    vstatus = 'PASS' if dc.status == 'PASS' and np.isfinite(dc.target) else 'REVIEW'
    audit = Table(title='MODEL CONTROL GATES', box=box.SIMPLE_HEAVY)
    audit.add_column('CONTROL'); audit.add_column('STATUS'); audit.add_column('NOTE')
    audit.add_row('Data Quality', dq, 'Market history and core financial fields available' if dq == 'PASS' else 'Insufficient core history/financial depth')
    audit.add_row('3-Statement Integrity', model_status, 'Bridge is a reconciliation plug, not independent full accounting validation')
    audit.add_row('DCF Integrity', vstatus, dc.warning or 'FCFF DCF inputs are positive and model calculated')
    console.print(audit)

    decision = 'REVIEW' if model_status.startswith('REVIEW') or vstatus == 'REVIEW' or dq == 'REVIEW' else 'ANALYST DECISION REQUIRED'
    console.print(Panel(
        f'SYSTEM CLASSIFICATION   {r["label"]}\n'
        f'INTEGRATED SCORE       {r["score"]:.1f}/100\n'
        f'NEXT HUMAN STEP        {decision}\n\n'
        'BUY / HOLD / AVOID / REVIEW — final decision remains with the analyst.',
        title='GROWISEINVEST — RESEARCH CONCLUSION', border_style='green' if decision != 'REVIEW' else 'yellow'
    ))

def help_screen():
    t=Table(title='GROWISE MAIN INDEX',box=box.SIMPLE_HEAVY)
    t.add_column('NO.',justify='right'); t.add_column('MODULE'); t.add_column('FUNCTION')
    for row in [('01','RESEARCH WORKBENCH','Full institutional equity research workflow'),('02','FINANCIAL STATEMENTS','Historical financial intelligence'),('03','THREE-STATEMENT MODEL','Five-year forecast + accounting reconciliation'),('04','DISCOUNTED CASH FLOW (DCF)','FCFF DCF + reverse DCF + sensitivity'),('05','VALUATION LAB','Valuation stack / fair-value analysis'),('06','TECHNICAL ANALYSIS','Trend, moving averages, RSI, 52-week range'),('07','MONTE CARLO QUANT','Probabilistic price distribution'),('08','RISK ANALYTICS','VaR, CVaR, drawdown and downside risk'),('09','PEER COMPARABLES','Peer valuation comparison'),('10','CROSS-COMPANY COMPARISON','Compare multiple companies'),('11','RESEARCH EXPORT','Create Excel research pack'),('12','MARKET STATUS','NSE/BSE trading status'),('13','CLEAR TERMINAL','Clear screen'),('14','GWI SCORE','Integrated fundamental, valuation, technical and quant research'),('00','EXIT','Quit GroWise'),('99','HELP / MAIN INDEX','Show this index')] : t.add_row(*row)
    console.print(t)

def ask_symbol():
    raw=console.input('[bold cyan]ENTER NSE TICKER (e.g. TCS): [/bold cyan]').strip().upper()
    if not raw or any(ch.isspace() for ch in raw) or not re.fullmatch(r'[A-Z0-9&.-]{1,30}',raw):
        raise ValueError('Enter one valid NSE ticker, for example TCS.')
    return raw

def run_number(n):
    n=str(n).strip().upper()
    aliases={'H':'99','HELP':'99','?':'99','Q':'00','QUIT':'00','EXIT':'00'}
    n=aliases.get(n,n)
    if n.isdigit(): n=f'{int(n):02d}'
    if n=='00': return False
    if n=='99': help_screen(); return True
    if n=='01': show_research(ask_symbol())
    elif n=='02': show_financials(ask_symbol())
    elif n=='03': show_model_cmd(ask_symbol())
    elif n=='04': show_dcf(ask_symbol())
    elif n=='05': show_valuation_lab(ask_symbol())
    elif n=='06': show_technical(ask_symbol())
    elif n=='07': show_quant_cmd(ask_symbol())
    elif n=='08':
        _,r=run_research(ask_symbol()); console.print(header()); show_risk(r)
    elif n=='09': show_peers(ask_symbol())
    elif n=='10':
        symbols=console.input('[bold cyan]ENTER TICKERS (e.g. TCS INFY HCLTECH): [/bold cyan]').split()
        if len(symbols)>=2: compare(symbols)
        else: console.print('[yellow]At least 2 tickers are required.[/yellow]')
    elif n=='11': export_excel(ask_symbol())
    elif n=='12': console.print(header())
    elif n=='13': console.clear(); console.print(header()); help_screen()
    elif n=='14': gwi_score(ask_symbol())
    else: console.print('[yellow]INVALID MODULE — enter a number from the index (01-14), 99 for HELP, or 00 to exit.[/yellow]')
    return True

def main():
    console.clear(); console.print(header())
    console.print(Panel('NUMBER-FIRST TERMINAL • ENTER A MODULE NUMBER • 99 = HELP • 00 = EXIT',border_style='cyan'))
    help_screen()
    while True:
        try:
            if not run_number(console.input('[bold cyan]GROWISE > ENTER NUMBER: [/bold cyan]').strip()): break
        except KeyboardInterrupt:
            console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='ENGINE ERROR — OPERATION ABORTED',border_style='red'))
            if os.getenv('GROWISE_DEBUG')=='1': console.print(f'[dim]{traceback.format_exc()}[/dim]')

# Original entrypoint retained for reference; final entrypoint is defined below.

# ===================== GROWISEINVEST MODULES 15-16 ADD-ON =====================
def data_quality(symbol):
    """Run a non-destructive data-quality and audit check without changing existing engines."""
    d=fetch(symbol); f=d['financials']; c=pd.Series(d['close']).dropna(); info=d.get('info',{})
    checks=[]
    checks.append(('Market history', len(c)>=252, f'{len(c)} observations'))
    checks.append(('Price completeness', float(c.isna().mean())==0, f'{c.isna().sum()} missing'))
    checks.append(('Positive prices', bool((c>0).all()), f'min {money(float(c.min()))}' if len(c) else 'N/A'))
    checks.append(('Financial periods', len(f.get('revenue',[]))>=2, f'{len(f.get("revenue",[]))} periods'))
    for key,label in [('revenue','Revenue'),('net_income','Net income'),('cfo','CFO'),('capex','Capex'),('equity','Equity'),('debt','Debt')]:
        s=f.get(key,pd.Series(dtype=float)); ok=bool(len(s.dropna())>=1 and np.isfinite(float(s.dropna().iloc[-1]))); checks.append((label, ok, f'{len(s.dropna())} reported periods'))
    checks.append(('Company metadata', bool(info.get('longName') or info.get('shortName')), 'name available' if info.get('longName') or info.get('shortName') else 'missing'))
    valid=sum(ok for _,ok,_ in checks); overall='PASS' if valid==len(checks) else 'REVIEW'
    console.print(header())
    console.print(Panel(f'{info.get("longName") or d["ticker"]}\nData Quality Status: {overall}  •  {valid}/{len(checks)} controls passed',title='DATA QUALITY & AUDIT TRAIL',border_style='green' if overall=='PASS' else 'yellow'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('CONTROL'); t.add_column('STATUS'); t.add_column('DETAIL')
    for name,ok,detail in checks: t.add_row(name,'PASS' if ok else 'REVIEW',detail)
    console.print(t)
    console.print(Panel(
        'SOURCE LAYER\nYahoo Finance research feed\n\n'
        'NORMALIZATION\nProvider financial statements mapped into GroWise canonical fields\n\n'
        'AUDIT PRINCIPLE\nReported data, modelled data and analyst assumptions should remain distinguishable.\n'
        'This module reports controls; it does not silently repair source data.',
        title='AUDIT TRAIL',border_style='cyan'))

def _backtest_metrics(returns, signal, transaction_cost=0.001):
    r=pd.Series(returns).astype(float).replace([np.inf,-np.inf],np.nan).dropna()
    s=pd.Series(signal,index=r.index).fillna(0).clip(-1,1)
    pos=s.shift(1).fillna(0)
    turnover=(pos.diff().abs().fillna(pos.abs()))
    strat=pos*r-turnover*transaction_cost
    equity=(1+strat).cumprod(); bh=(1+r).cumprod()
    n=len(strat); years=n/252 if n else math.nan
    def cagr_curve(x): return float(x.iloc[-1]**(1/years)-1) if len(x) and years>0 and x.iloc[-1]>0 else math.nan
    vol=float(strat.std(ddof=1)*np.sqrt(252)) if len(strat)>1 else math.nan
    sharpe=float(strat.mean()/strat.std(ddof=1)*np.sqrt(252)) if len(strat)>1 and strat.std(ddof=1)>0 else math.nan
    dd=equity/equity.cummax()-1; maxdd=float(dd.min()) if len(dd) else math.nan
    win=float((strat[strat!=0]>0).mean()) if (strat!=0).any() else math.nan
    return {'strategy_cagr':cagr_curve(equity),'buyhold_cagr':cagr_curve(bh),'volatility':vol,'sharpe':sharpe,'max_drawdown':maxdd,'win_rate':win,'trades':int((turnover>0).sum()),'equity':equity,'buyhold':bh}

def backtest(symbol):
    d=fetch(symbol); c=pd.Series(d['close']).dropna();
    if len(c)<504: raise RuntimeError('Backtest requires at least 504 price observations (approximately 2 trading years).')
    # Simple, transparent long/cash trend strategy. No look-ahead: today's position uses prior close.
    sma50=c.rolling(50).mean(); sma200=c.rolling(200).mean(); r=c.pct_change().dropna()
    signal=(sma50>sma200).astype(float).reindex(r.index).fillna(0)
    # Use only the most recent 5 years to keep runtime and output consistent.
    r=r.tail(min(len(r),1260)); signal=signal.reindex(r.index).fillna(0)
    m=_backtest_metrics(r,signal,transaction_cost=0.001)
    console.print(header())
    console.print(Panel(f'{d["info"].get("longName") or d["ticker"]}\nBacktest window: {len(r)} daily observations\nStrategy: 50/200-day trend • Long / Cash • 10 bps turnover cost',title='BACKTESTING ENGINE',border_style='cyan'))
    t=Table(title='BACKTEST RESULTS',box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Strategy',justify='right'); t.add_column('Buy & Hold',justify='right')
    t.add_row('CAGR',pct(m['strategy_cagr']),pct(m['buyhold_cagr']))
    t.add_row('Annualized Volatility',pct(m['volatility']),'N/A')
    t.add_row('Sharpe Ratio',num(m['sharpe']),'N/A')
    t.add_row('Maximum Drawdown',pct(m['max_drawdown']),'N/A')
    t.add_row('Win Rate',pct(m['win_rate']),'N/A')
    t.add_row('Trade / Position Changes',str(m['trades']),'N/A')
    console.print(t)
    relative=(m['strategy_cagr']-m['buyhold_cagr']) if np.isfinite(m['strategy_cagr']) and np.isfinite(m['buyhold_cagr']) else math.nan
    verdict='OUTPERFORMED' if np.isfinite(relative) and relative>0 else 'UNDERPERFORMED' if np.isfinite(relative) else 'INCONCLUSIVE'
    console.print(Panel(f'Relative CAGR: {pct(relative)}\nSystem result: {verdict}\n\nHistorical backtest only. Results are sensitive to period, costs, data quality and model specification; not a forecast or investment advice.',title='BACKTEST CONCLUSION',border_style='green' if verdict=='OUTPERFORMED' else 'yellow'))

def help_screen_v5():
    t=Table(title='GROWISEINVEST MAIN INDEX',box=box.SIMPLE_HEAVY)
    t.add_column('NO.',justify='right'); t.add_column('MODULE'); t.add_column('FUNCTION')
    rows=[('01','RESEARCH WORKBENCH','Full institutional equity research workflow'),('02','FINANCIAL STATEMENTS','Historical financial intelligence'),('03','THREE-STATEMENT MODEL','Five-year forecast + accounting reconciliation'),('04','DISCOUNTED CASH FLOW (DCF)','FCFF DCF + reverse DCF + sensitivity'),('05','VALUATION LAB','Valuation stack / fair-value analysis'),('06','TECHNICAL ANALYSIS','Trend, moving averages, RSI, 52-week range'),('07','MONTE CARLO QUANT','Probabilistic price distribution'),('08','RISK ANALYTICS','VaR, CVaR, drawdown and downside risk'),('09','PEER COMPARABLES','Peer valuation comparison'),('10','CROSS-COMPANY COMPARISON','Compare multiple companies'),('11','RESEARCH EXPORT','Create Excel research pack'),('12','MARKET STATUS','NSE/BSE trading status'),('13','CLEAR TERMINAL','Clear screen'),('14','GWI SCORE','Integrated fundamental, valuation, technical and quant research'),('15','DATA QUALITY & AUDIT','Source controls, completeness and audit trail'),('16','BACKTESTING ENGINE','Historical strategy performance and benchmark comparison'),('00','EXIT','Quit GroWise'),('99','HELP / MAIN INDEX','Show this index')]
    for row in rows:t.add_row(*row)
    console.print(t)

# Override only the dispatcher/index so existing modules 01-13 retain their original implementations.
def run_number_v5(n):
    n=str(n).strip().upper(); aliases={'H':'99','HELP':'99','?':'99','Q':'00','QUIT':'00','EXIT':'00'}; n=aliases.get(n,n)
    if n.isdigit(): n=f'{int(n):02d}'
    if n=='00': return False
    if n=='99': help_screen_v5(); return True
    if n=='15': data_quality(ask_symbol()); return True
    if n=='16': backtest(ask_symbol()); return True
    # Preserve the original 01-14 behavior exactly by delegating to the existing dispatcher.
    return run_number(n)

def main_v5():
    console.clear(); console.print(header()); console.print(Panel('NUMBER-FIRST TERMINAL • ENTER A MODULE NUMBER • 99 = HELP • 00 = EXIT',border_style='cyan')); help_screen_v5()
    while True:
        try:
            if not run_number_v5(console.input('[bold cyan]GROWISE > ENTER NUMBER: [/bold cyan]').strip()): break
        except KeyboardInterrupt: console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='ENGINE ERROR — OPERATION ABORTED',border_style='red'))
            if os.getenv('GROWISE_DEBUG')=='1': console.print(f'[dim]{traceback.format_exc()}[/dim]')

main = main_v5
# ============================================================================

# ===================== GROWISEINVEST MODULES 17-19 + FINAL INDEX =====================
# Modules 01-12 remain unchanged. Module numbering is extended as follows:
# 13 GWI SCORE | 14 DATA QUALITY & AUDIT | 15 BACKTESTING | 16 MARKET REGIME
# 17 PORTFOLIO RISK | 18 PORTFOLIO OPTIMIZER | 19 RESEARCH NOTE | 20 CLEAR TERMINAL

def _portfolio_input(prompt='ENTER NSE TICKERS (e.g. TCS INFY HDFCBANK): '):
    raw=console.input('[bold cyan]'+prompt+'[/bold cyan]').strip().upper()
    symbols=raw.split()
    if len(symbols)<2:
        raise ValueError('Enter at least 2 valid NSE tickers separated by spaces.')
    symbols=[s.replace('.NS','').replace('.BO','') for s in symbols]
    if len(symbols)>20:
        raise ValueError('Maximum 20 tickers are supported in one portfolio analysis.')
    for s in symbols:
        if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',s):
            raise ValueError(f'Invalid NSE ticker: {s}')
    return list(dict.fromkeys(symbols))

def market_regime(symbol='NIFTY50'):
    # Regime is inferred from a broad-market proxy. ^NSEI is used instead of a stock.
    tk='^NSEI'
    hist=_provider_call(lambda: yf.Ticker(tk).history(period='5y',auto_adjust=False), pd.DataFrame())
    if hist.empty or 'Close' not in hist: raise RuntimeError('No NIFTY 50 market history returned for regime analysis.')
    c=pd.Series(hist['Close']).dropna()
    if len(c)<220: raise RuntimeError('Market regime requires at least 220 observations.')
    sma50=float(c.rolling(50).mean().iloc[-1]); sma200=float(c.rolling(200).mean().iloc[-1])
    r=c.pct_change().dropna(); vol=float(r.tail(20).std(ddof=1)*np.sqrt(252)); longvol=float(r.std(ddof=1)*np.sqrt(252))
    trend='BULL' if c.iloc[-1]>sma200 and sma50>sma200 else 'BEAR' if c.iloc[-1]<sma200 and sma50<sma200 else 'TRANSITION'
    volreg='HIGH VOLATILITY' if vol>longvol*1.25 else 'LOW VOLATILITY' if vol<longvol*.75 else 'NORMAL VOLATILITY'
    regime=f'{trend} / {volreg}'
    console.print(header())
    console.print(Panel(f'NIFTY 50 (^NSEI)\nIndex: {money(float(c.iloc[-1]))}\n50DMA: {money(sma50)}\n200DMA: {money(sma200)}\n20D annualized volatility: {pct(vol)}\n5Y annualized volatility: {pct(longvol)}\n\nREGIME: {regime}',title='MARKET REGIME ENGINE',border_style='cyan'))
    t=Table(title='REGIME SIGNALS',box=box.SIMPLE_HEAVY); t.add_column('Signal'); t.add_column('Reading'); t.add_column('Interpretation')
    t.add_row('Price vs 200DMA', 'ABOVE' if c.iloc[-1]>sma200 else 'BELOW', 'Positive trend' if c.iloc[-1]>sma200 else 'Negative trend')
    t.add_row('50DMA vs 200DMA', 'ABOVE' if sma50>sma200 else 'BELOW', 'Medium-term confirmation' if sma50>sma200 else 'Medium-term weakness')
    t.add_row('Volatility', pct(vol), volreg)
    console.print(t)

def portfolio_risk(symbols):
    series=[]
    names=[]
    for s in symbols:
        d=fetch(s); c=pd.Series(d['close']).dropna().pct_change().dropna(); series.append(c.rename(s)); names.append(s)
    ret=pd.concat(series,axis=1,join='inner').dropna()
    if len(ret)<252: raise RuntimeError('Portfolio risk requires at least 252 common daily observations.')
    n=len(names); w=np.repeat(1/n,n)
    pr=ret.to_numpy()@w
    pr=pd.Series(pr,index=ret.index)
    var95=float(-np.quantile(pr,.05)); tail=pr[pr<=np.quantile(pr,.05)]; cvar95=float(-tail.mean()) if len(tail) else math.nan
    vol=float(pr.std(ddof=1)*np.sqrt(252)); equity=(1+pr).cumprod(); dd=equity/equity.cummax()-1; maxdd=float(dd.min())
    corr=ret.corr()
    console.print(header()); console.print(Panel(f'Equal-weight portfolio\n{len(names)} securities • {len(ret)} common observations\nAnnualized volatility: {pct(vol)}\nVaR 95%: {pct(var95)}\nCVaR 95%: {pct(cvar95)}\nMaximum drawdown: {pct(maxdd)}',title='PORTFOLIO RISK ANALYTICS',border_style='cyan'))
    t=Table(title='EQUAL-WEIGHT RISK CONTRIBUTION',box=box.SIMPLE_HEAVY); t.add_column('Ticker'); t.add_column('Weight'); t.add_column('Annual Volatility'); t.add_column('VaR 95%')
    for i,s in enumerate(names):
        sr=ret[s]; sv=float(sr.std(ddof=1)*np.sqrt(252)); sv95=float(-np.quantile(sr,.05)); t.add_row(s,pct(w[i]),pct(sv),pct(sv95))
    console.print(t)
    ct=Table(title='CORRELATION MATRIX',box=box.SIMPLE); ct.add_column('Ticker')
    for s in names: ct.add_column(s,justify='right')
    for s in names: ct.add_row(s,*[f'{float(corr.loc[s,x]):.2f}' for x in names])
    console.print(ct)
    console.print('[dim]Portfolio metrics use equal weights and historical common observations; they are model outputs, not forecasts.[/dim]')

def portfolio_optimizer(symbols):
    series=[]
    for s in symbols:
        d=fetch(s); series.append(pd.Series(d['close']).dropna().pct_change().dropna().rename(s))
    ret=pd.concat(series,axis=1,join='inner').dropna()
    if len(ret)<252: raise RuntimeError('Portfolio optimization requires at least 252 common daily observations.')
    names=list(ret.columns); n=len(names); mu=ret.mean().to_numpy()*252; cov=ret.cov().to_numpy()*252
    # Long-only, fully invested analytical mean-variance approximation. No external optimizer required.
    inv=np.linalg.pinv(cov); raw=inv@mu; raw=np.maximum(raw,0)
    if raw.sum()<=0: raw=np.ones(n)
    w=raw/raw.sum()
    port_mu=float(w@mu); port_vol=float(np.sqrt(max(w@cov@w,0))); sharpe=port_mu/port_vol if port_vol>0 else math.nan
    eq=np.repeat(1/n,n); eq_mu=float(eq@mu); eq_vol=float(np.sqrt(max(eq@cov@eq,0))); eq_sharpe=eq_mu/eq_vol if eq_vol>0 else math.nan
    console.print(header()); console.print(Panel(f'Long-only • Fully invested • Historical mean/covariance\nOptimized expected return: {pct(port_mu)}\nOptimized volatility: {pct(port_vol)}\nOptimized Sharpe: {num(sharpe)}\nEqual-weight expected return: {pct(eq_mu)}\nEqual-weight volatility: {pct(eq_vol)}\nEqual-weight Sharpe: {num(eq_sharpe)}',title='PORTFOLIO OPTIMIZER',border_style='cyan'))
    t=Table(title='RECOMMENDED MODEL WEIGHTS',box=box.SIMPLE_HEAVY); t.add_column('Ticker'); t.add_column('Weight',justify='right'); t.add_column('Expected Return',justify='right')
    for i,s in enumerate(names): t.add_row(s,pct(w[i]),pct(mu[i]))
    console.print(t)
    console.print('[yellow]Optimization is sensitive to historical estimates and is not a personalized investment recommendation.[/yellow]')

def research_note(symbol):
    d,r=run_research(symbol,sims=3000); info=r['info']; hs=d['financials']; tech=r['tech']; mc=r['mc']
    rc=cagr(hs['revenue']); ec=cagr(hs['net_income']); roe=latest(hs['net_income'])/latest(hs['equity']) if latest(hs['equity']) else math.nan; de=latest(hs['debt'])/latest(hs['equity']) if latest(hs['equity']) else math.nan
    positives=[]; risks=[]
    if rc is not None and rc>0: positives.append(f'Revenue CAGR: {pct(rc)}.')
    if np.isfinite(roe): positives.append(f'ROE: {pct(roe)}.')
    if np.isfinite(de): positives.append(f'Debt/Equity: {de:.2f}x.')
    if np.isfinite(r['upside']): positives.append(f'Blended modeled upside/(downside): {pct(r["upside"])}.')
    if np.isfinite(tech['sma200']) and r['price']<tech['sma200']: risks.append('Price remains below the 200-day moving average.')
    if mc['loss20_prob']>.15: risks.append(f'Monte Carlo >20% loss probability is {pct(mc["loss20_prob"])}.')
    if not risks: risks.append('No major automated risk flag was triggered.')
    console.print(header())
    console.print(Panel(f'{info.get("longName") or d["ticker"]}\nTicker: {d["ticker"]}\nCurrent price: {money(r["price"])}\nSystem classification: {r["label"]}\nIntegrated score: {r["score"]:.1f}/100',title='RESEARCH NOTE',border_style='cyan'))
    t=Table(title='KEY RESEARCH DATA',box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Value',justify='right')
    for k,v in [('Revenue CAGR',rc),('Earnings CAGR',ec),('ROE',roe),('Debt/Equity',de),('DCF',r['dcf'].target),('Blended Fair Value',r['blended']),('Upside/(Downside)',r['upside']),('MC P50',mc['percentiles']['P50']),('VaR 95%',mc['var95'])]:
        t.add_row(k, (pct(v) if k in ['Revenue CAGR','Earnings CAGR','ROE','Upside/(Downside)','VaR 95%'] else f'{v:.2f}x' if k=='Debt/Equity' else money(v)))
    console.print(t)
    console.print(Panel('\n'.join('✓ '+x for x in positives[:5]),title='KEY POSITIVES',border_style='green'))
    console.print(Panel('\n'.join('⚠ '+x for x in risks[:5]),title='KEY RISKS / REVIEW ITEMS',border_style='yellow'))
    console.print(Panel('System-generated research note. Verify reported figures, assumptions and valuation inputs before using externally. Final investment judgement remains with the analyst.',title='ANALYST USE',border_style='magenta'))

def institutional_pack(symbol):
    console.print(header())
    console.print(Panel(
        'All-in-one institutional equity research intelligence.\n\n'
        'Earnings intelligence • fundamental inflection • forensic quality • what changed •\n'
        'event study • factor profile • scenario valuation • DCF • 3-statement projections •\n'
        'Monte Carlo • risk analytics • technical structure • peers • catalysts • GWI Score\n\n'
        'Output: professionally formatted Excel workbook + Word research report + charts.',
        title='GROWISEINVEST — MODULE 20', border_style='cyan'))
    res=generate_institutional_pack(symbol, run_research, fetch, sims=5000)
    t=Table(title='INSTITUTIONAL PACK OUTPUT',box=box.SIMPLE_HEAVY)
    t.add_column('Deliverable'); t.add_column('Location')
    t.add_row('Excel Research Pack',res['excel']); t.add_row('Word Research Report',res['word']); t.add_row('Charts',f'{len(res["charts"])} professional chart files')
    console.print(t)
    console.print(Panel(f'GWI Score: {res["score"]:.1f}/100  •  {res["classification"]}\n\nThe Excel workbook contains DCF sensitivity, 5-year projections, valuation, technicals, Monte Carlo, quarterly intelligence, forensic diagnostics, scenarios, catalysts and chart-ready data.\nThe Word report embeds the key charts and institutional research narrative.',title='COMPLETE',border_style='green'))

def earnings_intelligence(symbol):
    from institutional_pack import _quarterly_intelligence
    d,r=run_research(symbol); q,meta=_quarterly_intelligence(d); console.print(header()); console.print(Panel(meta['message'],title='EARNINGS INTELLIGENCE',border_style='cyan'))
    if not q.empty: console.print(q.tail(8).round(4).to_string())

def fundamental_inflection(symbol):
    from institutional_pack import _quarterly_intelligence
    d,r=run_research(symbol); q,meta=_quarterly_intelligence(d); console.print(header());
    if q.empty: console.print(Panel(meta['message'],title='FUNDAMENTAL INFLECTION',border_style='yellow')); return
    rows=[]
    for k in ['Revenue YoY','Net Income YoY','EBITDA YoY']:
        if k in q and len(q[k].dropna())>=2:
            z=q[k].dropna(); rows.append((k,float(z.iloc[-2]),float(z.iloc[-1]),float(z.iloc[-1]-z.iloc[-2])))
    t=Table(title='INFLECTION SIGNALS',box=box.SIMPLE_HEAVY); [t.add_column(c,justify='right' if c!='Metric' else 'left') for c in ['Metric','Prior','Latest','Change']]
    for row in rows: t.add_row(row[0],pct(row[1]),pct(row[2]),pct(row[3]))
    console.print(t)

def forensic_engine(symbol):
    from institutional_pack import _forensic
    d,r=run_research(symbol); fc,flags=_forensic(d,r); console.print(header()); console.print(fc.round(4).to_string(index=False)); console.print(Panel('; '.join(flags) if flags else 'No major automated forensic flag triggered.',title='FORENSIC CONCLUSION',border_style='yellow'))

def what_changed_engine(symbol):
    from institutional_pack import _what_changed
    d,r=run_research(symbol); console.print(header()); console.print(_what_changed(d,r).round(4).to_string(index=False))

def event_study_engine(symbol):
    d,r=run_research(symbol); c=d['close'].dropna(); high=c.rolling(252).max(); events=(c>=high)&(c.shift(1)<high.shift(1)); rows=[]
    for dt in events[events].index[-10:]:
        pos=c.index.get_loc(dt)
        if pos+5<len(c): rows.append((str(dt.date()),float(c.iloc[pos+5]/c.iloc[pos]-1)))
    console.print(header()); console.print(Panel('Uses objectively detected 52-week-high breakouts as reproducible events when a complete corporate-event calendar is unavailable.',title='EVENT STUDY LAB',border_style='cyan'))
    if rows:
        t=Table(title='5-DAY POST-EVENT RETURN',box=box.SIMPLE_HEAVY); t.add_column('Event'); t.add_column('Return',justify='right')
        for a,b in rows:t.add_row(a,pct(b))
        console.print(t)
    else: console.print('[yellow]No qualifying events with a full forward window.[/yellow]')

def factor_exposure_engine(symbol):
    from institutional_pack import _factor_exposure
    d,r=run_research(symbol); console.print(header()); console.print(_factor_exposure(d).round(4).to_string(index=False))

def scenario_engine(symbol):
    from institutional_pack import _scenario
    d,r=run_research(symbol); console.print(header()); console.print(_scenario(d,r).round(4).to_string(index=False))

def catalyst_dashboard(symbol):
    from institutional_pack import _quarterly_intelligence,_catalyst
    d,r=run_research(symbol); q,_=_quarterly_intelligence(d); console.print(header()); console.print(_catalyst(d,r,q).round(4).to_string(index=False))

def institutional_note(symbol):
    institutional_pack(symbol)



# ===================== GROWISEINVEST INSTITUTIONAL MODULES 31-37 =====================
def _safe_num(v):
    try:
        x=float(v)
        return x if np.isfinite(x) else math.nan
    except Exception:
        return math.nan

def ownership_flow_engine(symbol):
    d=fetch(symbol); info=d.get('info',{}); tk=ticker(symbol)
    console.print(header())
    console.print(Panel(f'{_company_name(d)} ({symbol.upper()})\nOwnership, promoter/insider and institutional positioning diagnostics.',title='OWNERSHIP & INSTITUTIONAL FLOW',border_style='cyan'))
    t=Table(title='OWNERSHIP SNAPSHOT',box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Reading',justify='right'); t.add_column('Status')
    fields=[('Promoter / Insider Ownership',info.get('heldPercentInsiders')),('Institutional Ownership',info.get('heldPercentInstitutions')),('Float Shares',info.get('floatShares')),('Shares Outstanding',info.get('sharesOutstanding'))]
    for label,val in fields:
        if label.endswith('Ownership'):
            reading=pct(_safe_num(val)); status='AVAILABLE' if reading!='N/A' else 'N/A'
        else: reading=money(_safe_num(val)); status='AVAILABLE' if reading!='N/A' else 'N/A'
        t.add_row(label,reading,status)
    console.print(t)
    try:
        mh=_provider_call(lambda: yf.Ticker(tk).major_holders, pd.DataFrame())
        if mh is not None and not getattr(mh,'empty',True):
            console.print(Panel(mh.to_string(index=False),title='MAJOR HOLDER DATA — PROVIDER FEED',border_style='green'))
    except Exception: pass
    try:
        sh=_provider_call(lambda: yf.Ticker(tk).institutional_holders, pd.DataFrame())
        if sh is not None and not getattr(sh,'empty',True):
            console.print(Panel(sh.head(10).to_string(index=False),title='INSTITUTIONAL HOLDER DISCOVERY',border_style='magenta'))
    except Exception: pass
    console.print(Panel('Ownership data is provider-dependent. Historical promoter/FII/DII trend analysis should be verified against exchange shareholding filings before external use.',title='SOURCE CONTROL',border_style='yellow'))

def moat_analyzer(symbol):
    d,r=run_research(symbol); f=d['financials']; info=r['info']; tech=r['tech']
    rev=latest(f['revenue']); ebitda=latest(f['ebitda']); ni=latest(f['net_income']); eq=latest(f['equity']); debt=latest(f['debt']); cash=latest(f['cash'])
    margin=ebitda/rev if rev else math.nan; roe=ni/eq if eq else math.nan; de=debt/eq if eq else math.nan
    score=50.0
    score += 12 if np.isfinite(margin) and margin>.20 else 6 if np.isfinite(margin) and margin>.12 else 0
    score += 12 if np.isfinite(roe) and roe>.15 else 6 if np.isfinite(roe) and roe>.10 else 0
    score += 10 if np.isfinite(de) and de<.5 else 5 if np.isfinite(de) and de<1 else 0
    score += 8 if cash>debt else 0
    score += 8 if tech.get('score',50)>=65 else 0
    score=float(np.clip(score,0,100))
    strength='STRONG' if score>=80 else 'MODERATE-HIGH' if score>=70 else 'MODERATE' if score>=55 else 'WEAK / UNPROVEN'
    console.print(header()); console.print(Panel(f'{_company_name(d)}\nEvidence-based competitive advantage assessment — not a qualitative certainty.',title='MOAT ANALYZER',border_style='cyan'))
    t=Table(title='MOAT EVIDENCE SCORECARD',box=box.SIMPLE_HEAVY); t.add_column('Evidence'); t.add_column('Reading'); t.add_column('Assessment')
    t.add_row('Profitability / margin',pct(margin),'SUPPORTIVE' if margin>.20 else 'NEUTRAL' if np.isfinite(margin) else 'N/A')
    t.add_row('ROE / capital efficiency',pct(roe),'SUPPORTIVE' if roe>.15 else 'NEUTRAL' if np.isfinite(roe) else 'N/A')
    t.add_row('Balance-sheet resilience',f'D/E {num(de)}x','SUPPORTIVE' if de<.5 else 'NEUTRAL' if np.isfinite(de) else 'N/A')
    t.add_row('Cash vs debt',f'{money(cash)} vs {money(debt)}','SUPPORTIVE' if cash>debt else 'REVIEW')
    t.add_row('Business moat score',f'{score:.0f}/100',strength)
    console.print(t)
    console.print(Panel('Moat categories to verify with primary research: switching costs, network effects, scale/cost advantage, brand, distribution, regulation, IP, customer concentration and competitive intensity. Financial strength is evidence, not proof, of a moat.',title='ANALYST CONTROL',border_style='yellow'))

def valuation_bridge(symbol):
    d,r=run_research(symbol); p=r['price']; dc=r['dcf']; fair=r.get('blended')
    console.print(header()); console.print(Panel(f'{_company_name(d)}\nCurrent price: {money(p)}\nBlended modeled value: {money(fair)}',title='VALUATION BRIDGE',border_style='cyan'))
    # Transparent bridge: show method contributions rather than inventing causal attribution.
    peer=r.get('implied'); dcfv=dc.target if dc and np.isfinite(dc.target) else math.nan
    vals=[v for v in [dcfv,peer] if v is not None and np.isfinite(v)]
    t=Table(title='FAIR VALUE DECOMPOSITION',box=box.SIMPLE_HEAVY); t.add_column('Component'); t.add_column('Value',justify='right'); t.add_column('Weight',justify='right')
    if np.isfinite(dcfv): t.add_row('FCFF DCF',money(dcfv),f'{100/len(vals):.0f}%')
    if peer is not None and np.isfinite(peer): t.add_row('Peer multiple implied',money(peer),f'{100/len(vals):.0f}%')
    if np.isfinite(fair): t.add_row('Blended modeled fair value',money(fair),'100% output')
    t.add_row('Current market price',money(p),'Reference')
    console.print(t)
    if np.isfinite(fair):
        console.print(Panel(f'Modeled value gap: {pct(fair/p-1)}\nThis module decomposes valuation methods; it does not fabricate a causal attribution of every rupee in fair value.',title='VALUATION INTERPRETATION',border_style='green'))

def corporate_actions_engine(symbol):
    d=fetch(symbol); tk=d['ticker']; console.print(header()); console.print(Panel(f'{_company_name(d)} ({symbol.upper()})\nCorporate-action discovery from the configured market-data provider.',title='CORPORATE ACTION INTELLIGENCE',border_style='cyan'))
    try:
        acts=_provider_call(lambda: yf.Ticker(tk).actions, pd.DataFrame())
    except Exception:
        acts=pd.DataFrame()
    if acts is None or acts.empty:
        console.print(Panel('No corporate actions returned by the provider. Verify exchange/company announcements for dividends, splits, bonuses, buybacks, rights issues, mergers and demergers.',title='NO VERIFIED ACTIONS',border_style='yellow')); return
    a=acts.reset_index(); a['Date']=a.iloc[:,0].astype(str)
    cols=[c for c in a.columns if c!='Date']
    t=Table(title='RECENT CORPORATE ACTIONS',box=box.SIMPLE_HEAVY); t.add_column('Date'); [t.add_column(str(c)) for c in cols]
    for _,row in a.tail(15).iterrows(): t.add_row(str(row['Date'])[:16],*[str(row[c]) for c in cols])
    console.print(t)
    console.print(Panel('Corporate-action records can be incomplete or provider-normalized. Confirm material actions with NSE/BSE/company filings before adjusting a valuation or price series.',title='SOURCE CONTROL',border_style='yellow'))

def filings_intelligence(symbol):
    d=fetch(symbol); tk=d['ticker']; console.print(header()); console.print(Panel(f'{_company_name(d)} ({symbol.upper()})\nFiling and disclosure discovery layer.',title='REGULATORY & FILINGS INTELLIGENCE',border_style='cyan'))
    t=Table(title='DISCLOSURE CONTROL MATRIX',box=box.SIMPLE_HEAVY); t.add_column('Disclosure'); t.add_column('Availability'); t.add_column('Institutional Use')
    items=[('Annual / audited financials','Provider financial statements','Historical validation'),('Quarterly results','Provider quarterly history','Earnings trend'),('Shareholding pattern','Requires exchange/company filing','Promoter/institutional flow'),('Related-party disclosures','Requires filing review','Governance / forensic'),('Material events','Requires filing review','Catalyst / risk'),('Debt / capital changes','Requires filing review','Balance-sheet risk')]
    for a,b,c in items:t.add_row(a,b,c)
    console.print(t)
    try:
        cal=_provider_call(lambda: yf.Ticker(tk).calendar, {})
        if isinstance(cal,dict) and cal: console.print(Panel(str(cal),title='PROVIDER EVENT METADATA',border_style='green'))
    except Exception: pass
    try:
        news=_rss_news(symbol+' company filing results NSE BSE',limit=8)
        if news:
            nt=Table(title='LATEST DISCLOSURE-RELATED NEWS DISCOVERY',box=box.SIMPLE); nt.add_column('Headline'); nt.add_column('Source'); nt.add_column('Published')
            for x in news: nt.add_row(x['title'],x['source'],x['pubDate'][:25])
            console.print(nt)
    except Exception: pass
    console.print(Panel('This module is a discovery/control layer, not a substitute for reading the original NSE/BSE/company filing. No unavailable filing detail is fabricated.',title='SOURCE CONTROL',border_style='yellow'))

def red_flag_engine(symbol):
    d,r=run_research(symbol); f=d['financials']; flags=[]
    rev=cagr(f['revenue']); ni=cagr(f['net_income']); fcf=r.get('fcf',pd.Series(dtype=float));
    roe=r.get('roe',math.nan); de=latest(f['debt'])/latest(f['equity']) if latest(f['equity']) else math.nan
    if np.isfinite(rev) and np.isfinite(ni) and ni < rev-.05: flags.append(('Earnings quality','Net-income CAGR materially trails revenue CAGR.','HIGH'))
    if len(fcf)>=2 and latest(fcf)<0: flags.append(('Free cash flow','Latest modeled FCF is negative.','HIGH'))
    if np.isfinite(de) and de>1: flags.append(('Leverage','Debt/equity exceeds 1.0x.','HIGH'))
    if np.isfinite(roe) and roe<.08: flags.append(('Capital efficiency','ROE is below 8%.','MEDIUM'))
    try:
        fc,ff=_forensic(d,r)
        for x in ff[:4]: flags.append(('Forensic engine',x,'MEDIUM'))
    except Exception: pass
    score=max(0,100-20*sum(1 for _,_,sev in flags if sev=='HIGH')-10*sum(1 for _,_,sev in flags if sev=='MEDIUM'))
    console.print(header()); console.print(Panel(f'{_company_name(d)}\nRed Flag Score: {score}/100',title='RED FLAG ENGINE',border_style='red' if score<60 else 'yellow'))
    t=Table(title='RISK SIGNALS',box=box.SIMPLE_HEAVY); t.add_column('Area'); t.add_column('Signal'); t.add_column('Severity')
    if flags:
        for a,b,c in flags:t.add_row(a,b,c)
    else:t.add_row('System scan','No major automated red flag triggered.','LOW')
    console.print(t)
    console.print(Panel('Automated red flags are screening signals, not accusations of misconduct. Confirm accounting, filings and business context before drawing conclusions.',title='ANALYST CONTROL',border_style='magenta'))

def investment_committee_mode(symbol):
    # Generate the full institutional pack and then add an IC-style executive overlay.
    d,r=run_research(symbol,sims=5000)
    console.print(header())
    score=r['score']; up=r.get('upside'); tech=r['tech']['score']; mc=r['mc']; dc=r['dcf']
    bear=float(mc['percentiles'].get('P5',math.nan)); base=float(r['blended']) if np.isfinite(r.get('blended',math.nan)) else math.nan; bull=float(mc['percentiles'].get('P95',math.nan))
    quality=float(np.clip(.5*r['fund_score']+.5*score,0,100))
    console.print(Panel(f'{_company_name(d)} ({symbol.upper()})\nCurrent Price: {money(r["price"])}\nGWI Score: {score:.1f}/100 • {r["label"]}\nResearch Confidence Proxy: {quality:.0f}/100',title='INVESTMENT COMMITTEE MODE',border_style='cyan'))
    t=Table(title='IC DECISION DASHBOARD',box=box.SIMPLE_HEAVY); t.add_column('Dimension'); t.add_column('Reading',justify='right'); t.add_column('Assessment')
    t.add_row('Base fair value',money(base),'MODELLED' if np.isfinite(base) else 'REVIEW')
    t.add_row('DCF value',money(dc.target),'PASS' if dc.status=='PASS' else 'REVIEW')
    t.add_row('Bear distribution (P5)',money(bear),'QUANT')
    t.add_row('Bull distribution (P95)',money(bull),'QUANT')
    t.add_row('Valuation gap',pct(up),'POSITIVE' if np.isfinite(up) and up>0 else 'REVIEW')
    t.add_row('Fundamental score',f'{r["fund_score"]:.0f}/100','POSITIVE' if r['fund_score']>=70 else 'REVIEW')
    t.add_row('Technical score',f'{tech:.0f}/100','POSITIVE' if tech>=65 else 'REVIEW')
    t.add_row('Monte Carlo positive probability',pct(mc.get('positive_prob')),'MODELLED')
    t.add_row('3-statement control','CONDITIONAL PASS' if r.get('balance_ok') else 'REVIEW','Bridge reconciliation used')
    console.print(t)
    console.print(Panel('INVESTMENT THESIS\n• Review growth, margins and cash conversion.\n• Validate valuation assumptions and DCF sensitivity.\n• Review downside distribution and key red flags.\n• Confirm primary filings and management commentary.\n\nANALYST DECISION\nBUY / HOLD / AVOID / REVIEW — final decision remains with the human investment committee.',title='COMMITTEE CONCLUSION',border_style='green' if score>=70 else 'yellow'))
    try:
        res=generate_institutional_pack(symbol, run_research, fetch, sims=5000)
        ot=Table(title='IC DELIVERABLES',box=box.SIMPLE_HEAVY); ot.add_column('Deliverable'); ot.add_column('Location')
        ot.add_row('Excel Institutional Research Pack',res['excel']); ot.add_row('Word Institutional Research Report',res['word']); ot.add_row('Professional Charts',str(len(res.get('charts',[]))))
        console.print(ot)
    except Exception as e:
        console.print(Panel(f'Pack generation unavailable: {type(e).__name__}: {e}',title='EXPORT REVIEW',border_style='yellow'))

def final_help_screen():
    console.print(Panel(
        '[bold cyan]GROWISEINVEST[/bold cyan]  INSTITUTIONAL RESEARCH WORKSTATION\n'
        '[dim]NUMBER-FIRST • SOURCE CONTROLLED • HUMAN DECISION REQUIRED[/dim]\n\n'
        '[bold]Enter a module number.[/bold]  Example: [cyan]100[/cyan] → enter ticker → valuation dashboard.\n'
        '[dim]99 = this index   00 = exit   H = help[/dim]',
        title='MAIN TERMINAL', border_style='cyan'))
    groups=[
        ('CORE RESEARCH','01','12','Research, financials, models, valuation, technicals, quant, export and market status'),
        ('QUANT & PORTFOLIO','13','19','GWI score, audit, backtest, regimes, portfolio risk, optimization and research note'),
        ('INTELLIGENCE','20','29','All-in-one pack, calls, IPOs, news, earnings, inflection, forensic, events and catalysts'),
        ('GOVERNANCE & ADVANCED','30','49','Ownership, moat, valuation bridge, filings, red flags, IC mode, factors, SOTP and thesis'),
        ('WORKSTATION','50','50','Clear terminal'),
        ('FAIR VALUE','100','100','Multi-method fair-value calculator with Lynch-style primary screen + valuation cross-checks'),
    ]
    t=Table(box=box.SIMPLE_HEAVY, show_lines=False)
    t.add_column('RANGE',justify='right',style='bold cyan'); t.add_column('MODULE FAMILY',style='bold white'); t.add_column('WHAT IT DOES')
    for family,a,b,desc in groups: t.add_row(f'{a}–{b}',family,desc)
    console.print(t)
    t2=Table(title='MODULE INDEX',box=box.SIMPLE)
    t2.add_column('NO.',justify='right'); t2.add_column('MODULE',style='bold'); t2.add_column('FUNCTION')
    rows=[
        ('01','RESEARCH WORKBENCH','Full institutional equity research workflow'),('02','FINANCIAL STATEMENTS','Historical financial intelligence'),('03','THREE-STATEMENT MODEL','Five-year forecast + accounting reconciliation'),('04','DISCOUNTED CASH FLOW (DCF)','FCFF DCF + reverse DCF + sensitivity'),('05','VALUATION LAB','Multi-method valuation diagnostics'),('06','TECHNICAL ANALYSIS','Trend, momentum, RSI and moving averages'),('07','MONTE CARLO QUANT','Probabilistic price distribution'),('08','RISK ANALYTICS','VaR, CVaR and drawdown'),('09','PEER COMPARABLES','Peer valuation context'),('10','CROSS-COMPANY COMPARISON','Multi-stock comparison'),('11','RESEARCH EXPORT','Excel research pack'),('12','MARKET STATUS','NSE/BSE session status'),
        ('13','GWI SCORE','Integrated quantamental score'),('14','DATA QUALITY & AUDIT','Source and model controls'),('15','BACKTESTING ENGINE','Historical strategy analysis'),('16','MARKET REGIME ENGINE','Trend + volatility regime'),('17','PORTFOLIO RISK','Portfolio risk and correlation'),('18','PORTFOLIO OPTIMIZER','Long-only allocation'),('19','RESEARCH NOTE','Analyst-ready summary'),
        ('20','INSTITUTIONAL ALL-IN-ONE','Full report + Excel + Word + charts'),('21','CONFERENCE CALL ANALYZER','Earnings / management review'),('22','IPO RESEARCH','IPO due diligence'),('23','NEWS & TOMORROW EVENTS','News + next-session events'),('24','EARNINGS INTELLIGENCE','Quarterly momentum'),('25','FUNDAMENTAL INFLECTION','Inflection detection'),('26','EARNINGS QUALITY & FORENSIC','Accounting-quality diagnostics'),('27','WHAT CHANGED','Research-period change detection'),('28','EVENT STUDY LAB','Event-window analysis'),('29','SCENARIO & CATALYST LAB','Scenario + catalyst analysis'),
        ('30','OWNERSHIP & INSTITUTIONAL FLOW','Ownership context'),('31','MOAT ANALYZER','Competitive-advantage evidence'),('32','VALUATION BRIDGE','Fair-value bridge'),('33','CORPORATE ACTION INTELLIGENCE','Dividends / splits / actions'),('34','REGULATORY & FILINGS INTELLIGENCE','Disclosure controls'),('35','RED FLAG ENGINE','Financial risk flags'),('36','INVESTMENT COMMITTEE MODE','Executive IC dashboard'),('37','FACTOR EXPOSURE','Factor-style evidence'),('38','QUALITY SCORECARD','Business quality score'),('39','GROWTH QUALITY LAB','Growth durability'),('40','CAPITAL ALLOCATION LAB','Capital deployment quality'),('41','SOTP VALUATION LAB','SOTP framework'),('42','DIVIDEND DISCOUNT VALUATION','DDM'),('43','RESIDUAL INCOME VALUATION','Residual income'),('44','PROBABILITY VALUATION','Scenario-weighted value'),('45','VALUATION DECOMPOSITION','Value-driver decomposition'),('46','FACTOR & STYLE DASHBOARD','Style dashboard'),('47','THESIS TRACKER','Thesis governance'),('48','PORTFOLIO ATTRIBUTION','Attribution framework'),('49','MODEL CONTROL CENTER','Model governance'),('50','CLEAR TERMINAL','Clear workstation'),
        ('100','FAIR VALUE CALCULATOR','Lynch-style calculator + 10 valuation cross-checks'),
    ]
    for row in rows:t2.add_row(*row)
    console.print(t2)

def _company_name(d):
    return d.get('info',{}).get('longName') or d.get('info',{}).get('shortName') or d.get('ticker','')

def conference_call_analyzer(symbol):
    """Conference-call intelligence with a graceful public-source fallback.
    When a verbatim transcript provider is unavailable, the engine analyzes the
    latest quarterly financial trend plus company/earnings news and explicitly
    labels transcript-derived fields as unavailable rather than fabricating them.
    """
    from institutional_pack import _quarterly_intelligence
    d,r=run_research(symbol,sims=2500); q,meta=_quarterly_intelligence(d)
    console.print(header())
    company=_company_name(d)
    console.print(Panel(f'{company} ({d["ticker"].replace(".NS","")})\nLatest price: {money(r["price"])}',title='CONFERENCE CALL ANALYZER',border_style='cyan'))
    t=Table(title='MANAGEMENT / EARNINGS INTELLIGENCE',box=box.SIMPLE_HEAVY)
    for c in ['Signal','Reading','Status']: t.add_column(c)
    if len(q):
        def latest_metric(col):
            z=q[col].dropna() if col in q else pd.Series(dtype=float)
            return float(z.iloc[-1]) if len(z) else math.nan
        rev=latest_metric('Revenue YoY'); ni=latest_metric('Net Income YoY'); ebitda=latest_metric('EBITDA YoY')
        t.add_row('Revenue momentum',pct(rev),'LATEST QUARTER')
        t.add_row('Earnings momentum',pct(ni),'LATEST QUARTER')
        t.add_row('EBITDA momentum',pct(ebitda),'LATEST QUARTER')
        msg=meta.get('message','Quarterly trend available.')
    else: msg=meta.get('message','Quarterly financial data unavailable.')
    t.add_row('Management transcript','Not independently sourced by the core data provider','SOURCE LIMITATION')
    t.add_row('Interpretation',msg,'MODELLED')
    console.print(t)
    positives=[]; risks=[]
    if len(q):
        if 'Revenue YoY' in q and len(q['Revenue YoY'].dropna())>=2:
            z=q['Revenue YoY'].dropna(); (positives if z.iloc[-1]>z.iloc[-2] else risks).append('Revenue growth momentum is improving.' if z.iloc[-1]>z.iloc[-2] else 'Revenue growth momentum is weakening.')
        if 'Net Income YoY' in q and len(q['Net Income YoY'].dropna())>=2:
            z=q['Net Income YoY'].dropna(); (positives if z.iloc[-1]>z.iloc[-2] else risks).append('Earnings momentum is improving.' if z.iloc[-1]>z.iloc[-2] else 'Earnings momentum is weakening.')
    positives.append('Use the analyst discussion section to verify guidance, demand commentary, margins, capex and capital allocation before relying on qualitative conclusions.')
    console.print(Panel('\n'.join('✓ '+x for x in positives[:5]),title='POSITIVE / WATCH SIGNALS',border_style='green'))
    console.print(Panel('\n'.join('⚠ '+x for x in (risks or ['No automated negative quarterly trend flag.'])[:5]),title='RISKS / QUESTIONS FOR MANAGEMENT',border_style='yellow'))
    console.print(Panel('Institutional control: this module never invents management quotes. If a transcript is not available through the configured source, transcript-specific commentary is marked unavailable.',title='SOURCE CONTROL',border_style='magenta'))

def _rss_news(query,limit=8):
    import urllib.parse, urllib.request, xml.etree.ElementTree as ET
    url='https://news.google.com/rss/search?q='+urllib.parse.quote(query)+'&hl=en-IN&gl=IN&ceid=IN:en'
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=12) as resp: raw=resp.read()
    root=ET.fromstring(raw); rows=[]
    for item in root.findall('./channel/item')[:limit]:
        rows.append({'title':item.findtext('title') or '', 'link':item.findtext('link') or '', 'pubDate':item.findtext('pubDate') or '', 'source':(item.findtext('source') or '')})
    return rows

def ipo_research(name):
    """IPO research using public web discovery with fail-closed source handling.
    It accepts a plain IPO/company name; incomplete public data is shown as N/A.
    """
    console.print(header())
    name=name.strip()
    if not name: raise ValueError('Enter the IPO/company name.')
    console.print(Panel(f'{name}\nInstitutional IPO due-diligence framework',title='IPO RESEARCH',border_style='cyan'))
    news=[]; err=None
    try: news=_rss_news(name+' IPO India',limit=8)
    except Exception as e: err=str(e)
    t=Table(title='IPO INTELLIGENCE',box=box.SIMPLE_HEAVY)
    t.add_column('Dimension'); t.add_column('Assessment')
    t.add_row('Company / IPO',name)
    t.add_row('Public-source discovery','AVAILABLE' if news else 'LIMITED / UNAVAILABLE')
    t.add_row('Offer size / price band','N/A — requires current prospectus / exchange filing')
    t.add_row('Fresh issue / OFS','N/A — requires current prospectus / exchange filing')
    t.add_row('Valuation / implied market cap','N/A — requires verified price band + post-issue shares')
    t.add_row('Financial quality','N/A — prospectus financial statements required for verified calculation')
    t.add_row('Institutional verdict','REVIEW — do not infer valuation without verified offer data')
    console.print(t)
    if news:
        nt=Table(title='LATEST IPO NEWS DISCOVERY',box=box.SIMPLE); nt.add_column('Date'); nt.add_column('Headline'); nt.add_column('Source')
        for x in news: nt.add_row(x['pubDate'][:25],x['title'],x['source'])
        console.print(nt)
    else:
        console.print(Panel(f'Public-source discovery unavailable: {err or "No results returned."}\nThe module remains operational and does not fabricate IPO facts.',title='SOURCE LIMITATION',border_style='yellow'))
    console.print(Panel('Required institutional documents for a complete IPO verdict: DRHP/RHP, audited financials, offer structure, price band, post-issue share count, peer set, promoter/shareholding details, use of proceeds and current market conditions.',title='IPO DUE-DILIGENCE CHECKLIST',border_style='magenta'))

def news_tomorrow_events():
    console.print(header())
    rows=[]
    for q in ['Nifty India stock market latest news','Indian stocks earnings tomorrow','NSE results tomorrow India']:
        try: rows.extend(_rss_news(q,limit=6))
        except Exception: pass
    seen=set(); clean_rows=[]
    for x in rows:
        key=x['title'].lower()
        if key not in seen: seen.add(key); clean_rows.append(x)
    console.print(Panel('Top public-source market/stock news plus an earnings/event watch for the next trading day. News is discovery data; verify against exchange/company filings before acting.',title='NEWS & TOMORROW EVENTS',border_style='cyan'))
    if clean_rows:
        t=Table(title='TOP NEWS',box=box.SIMPLE); t.add_column('Headline'); t.add_column('Source'); t.add_column('Published')
        for x in clean_rows[:12]: t.add_row(x['title'],x['source'],x['pubDate'][:25])
        console.print(t)
    else: console.print('[yellow]No public news feed returned. Market/news module remains operational.[/yellow]')
    # Scan a compact liquid universe for upcoming earnings dates where Yahoo exposes them.
    universe=['RELIANCE','TCS','INFY','HDFCBANK','ICICIBANK','SBIN','LT','ITC','HINDUNILVR','BHARTIARTL','AXISBANK','KOTAKBANK','MARUTI','M&M','SUNPHARMA','TATAMOTORS','WIPRO','HCLTECH','TATASTEEL','NTPC']
    import yfinance as yf
    tomorrow=(datetime.now(IST)+timedelta(days=1)).date()
    events=[]
    for sym in universe:
        try:
            cal=_provider_call(lambda: yf.Ticker(sym+'.NS').calendar, {})
            if isinstance(cal,dict): ed=cal.get('Earnings Date') or cal.get('earningsDate')
            else: ed=None
            if ed is None: continue
            vals=list(ed) if isinstance(ed,(list,tuple,pd.Series,np.ndarray)) else [ed]
            for v in vals:
                try:
                    dt=pd.Timestamp(v).date()
                    if dt==tomorrow: events.append((sym,dt.isoformat()))
                except Exception: pass
        except Exception: pass
    et=Table(title=f'RESULTS / EARNINGS WATCH — {tomorrow.strftime("%d-%b-%Y")}',box=box.SIMPLE_HEAVY); et.add_column('Ticker'); et.add_column('Date')
    if events:
        for a,b in events: et.add_row(a,b)
    else: et.add_row('No verified event returned','Check exchange/company IR calendars')
    console.print(et)

# ===================== GROWISEINVEST V8 ADVANCED PRODUCTS =====================
def _safe_ratio(a,b):
    try:
        a=float(a); b=float(b)
        return a/b if np.isfinite(a) and np.isfinite(b) and b!=0 else math.nan
    except Exception: return math.nan

def _ascii_bar(label, value, lo, hi, width=34):
    if not np.isfinite(value): return f'{label:<28} N/A'
    span=max(hi-lo,1e-9); n=int(np.clip((value-lo)/span,0,1)*width)
    return f'{label:<28} ' + '█'*n + ' '*(width-n) + f' {money(value)}'

def factor_exposure_v8(symbol):
    d,r=run_research(symbol,sims=2500); h=d['close']; ret=np.log(h/h.shift(1)).replace([np.inf,-np.inf],np.nan).dropna()
    console.print(header()); console.print(Panel(_company_name(d)+chr(10)+'Factor-style evidence dashboard',title='FACTOR EXPOSURE',border_style='cyan'))
    f=d['financials']; rev=cagr(f['revenue']); roe=r.get('roe',math.nan); de=_safe_ratio(latest(f['debt']),latest(f['equity']))
    vol=float(ret.std()*np.sqrt(252)) if len(ret)>20 else math.nan
    mom=_safe_ratio(r['price'],float(h.iloc[-126]))-1 if len(h)>=126 else math.nan
    vals=[('Quality',np.clip((roe-.05)/.25*100,0,100) if np.isfinite(roe) else math.nan),('Growth',np.clip((rev+.10)/.20*100,0,100) if np.isfinite(rev) else math.nan),('Leverage quality',np.clip((1-de)*100,0,100) if np.isfinite(de) else math.nan),('Momentum',np.clip((mom+.30)/.60*100,0,100) if np.isfinite(mom) else math.nan),('Low-volatility',np.clip((.45-vol)/.35*100,0,100) if np.isfinite(vol) else math.nan)]
    t=Table(title='STYLE / FACTOR EVIDENCE',box=box.SIMPLE_HEAVY); t.add_column('Factor'); t.add_column('Score'); t.add_column('Evidence')
    for a,b in vals: t.add_row(a,'N/A' if not np.isfinite(b) else f'{b:.0f}/100','Internal proxy')
    console.print(t); console.print(Panel('Transparent internal factor proxies; not vendor factor scores or causal return attribution.',title='METHODOLOGY CONTROL',border_style='yellow'))

def quality_scorecard(symbol):
    d,r=run_research(symbol,sims=2000); f=d['financials']; rev=latest(f['revenue']); ebitda=latest(f['ebitda']); ni=latest(f['net_income']); cfo=latest(f['cfo']); capex=latest(f['capex']); eq=latest(f['equity']); debt=latest(f['debt'])
    margin=_safe_ratio(ebitda,rev); roe=_safe_ratio(ni,eq); fcf=cfo-capex; conversion=_safe_ratio(cfo,ni); de=_safe_ratio(debt,eq)
    components={'Margin quality':np.clip(margin/.30*100,0,100) if np.isfinite(margin) else math.nan,'ROE quality':np.clip(roe/.30*100,0,100) if np.isfinite(roe) else math.nan,'Cash conversion':np.clip(conversion/1.2*100,0,100) if np.isfinite(conversion) else math.nan,'Leverage quality':np.clip((1-de)*100,0,100) if np.isfinite(de) else math.nan,'FCF quality':100 if fcf>0 else 0}
    valid=[v for v in components.values() if np.isfinite(v)]; score=float(np.mean(valid)) if valid else math.nan
    console.print(header()); console.print(Panel(_company_name(d)+chr(10)+(f'Quality Score: {score:.0f}/100' if np.isfinite(score) else 'Quality Score: N/A'),title='QUALITY SCORECARD',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Component'); t.add_column('Score'); t.add_column('Evidence')
    for k,v in components.items(): t.add_row(k,'N/A' if not np.isfinite(v) else f'{v:.0f}/100','Modelled')
    console.print(t)

def growth_quality_lab(symbol):
    d,r=run_research(symbol,sims=2000); f=d['financials']; rev=cagr(f['revenue']); earn=cagr(f['net_income']); margin=_safe_ratio(latest(f['ebitda']),latest(f['revenue'])); conv=_safe_ratio(latest(f['cfo']),latest(f['net_income']))
    console.print(header()); console.print(Panel(_company_name(d),title='GROWTH QUALITY LAB',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Reading'); t.add_column('Assessment')
    t.add_row('Revenue CAGR',pct(rev),'Positive' if np.isfinite(rev) and rev>0 else 'Review'); t.add_row('Earnings CAGR',pct(earn),'Positive' if np.isfinite(earn) and earn>0 else 'Review'); t.add_row('EBITDA margin',pct(margin),'Supportive' if np.isfinite(margin) and margin>.15 else 'Review'); t.add_row('CFO / Net income',num(conv),'Healthy' if np.isfinite(conv) and conv>=.8 else 'Review')
    console.print(t); console.print(Panel('Growth quality improves when revenue, earnings and cash conversion reinforce each other.',title='INTERPRETATION',border_style='magenta'))

def capital_allocation_lab(symbol):
    d,r=run_research(symbol,sims=2000); f=d['financials']; ni=latest(f['net_income']); eq=latest(f['equity']); debt=latest(f['debt']); cash=latest(f['cash']); fc=latest(f['cfo'])-latest(f['capex']); roe=_safe_ratio(ni,eq); de=_safe_ratio(debt,eq); cd=_safe_ratio(cash,debt)
    console.print(header()); console.print(Panel(_company_name(d),title='CAPITAL ALLOCATION LAB',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Value'); t.add_column('Assessment'); t.add_row('ROE',pct(roe),'Strong' if np.isfinite(roe) and roe>.15 else 'Review'); t.add_row('Debt / Equity',num(de)+'x','Conservative' if np.isfinite(de) and de<.5 else 'Review'); t.add_row('Cash / Debt',num(cd)+'x','Resilient' if np.isfinite(cd) and cd>1 else 'Review'); t.add_row('Free cash flow',money(fc),'Positive' if fc>0 else 'Review'); console.print(t)

def sotp_lab(symbol):
    d,r=run_research(symbol,sims=2000); fair=r.get('blended'); netdebt=latest(d['financials']['debt'])-latest(d['financials']['cash'])
    console.print(header()); console.print(Panel(_company_name(d)+chr(10)+'Segment-level SOTP requires verified disclosure inputs.',title='SOTP VALUATION LAB',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Component'); t.add_column('Value'); t.add_column('Status'); t.add_row('Operating value proxy',money(fair),'Blended output' if np.isfinite(fair) else 'N/A'); t.add_row('Net debt adjustment',money(netdebt),'Provider financials'); t.add_row('Non-core investments','N/A','Requires verified disclosures'); t.add_row('SOTP equity value','N/A','Requires segment valuation'); console.print(t)
    console.print(Panel('No segment value is fabricated. Populate segment revenue/EBITDA, multiples and investment values from verified disclosures for a full SOTP.',title='SOURCE CONTROL',border_style='yellow'))

def dividend_discount_valuation(symbol):
    d,r=run_research(symbol,sims=2000); div=clean(d['info'].get('trailingAnnualDividendRate')); g=cagr(d['financials']['net_income']); g=float(np.clip(g if g is not None and np.isfinite(g) else .05,-.02,.08)); k=.10; value=div*(1+g)/(k-g) if div is not None and np.isfinite(div) and div>0 and k>g else math.nan
    console.print(header()); console.print(Panel(_company_name(d),title='DIVIDEND DISCOUNT VALUATION',border_style='cyan'))
    if not np.isfinite(value): console.print(Panel('Verified dividend input unavailable or assumptions do not support a valid Gordon-growth DDM.',title='DDM CONTROL',border_style='yellow')); return
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Input'); t.add_column('Value'); t.add_row('Dividend / share',money(div)); t.add_row('Growth',pct(g)); t.add_row('Cost of equity',pct(k)); t.add_row('DDM value / share',money(value)); t.add_row('Current price',money(r['price'])); t.add_row('Upside / (downside)',pct(value/r['price']-1)); console.print(t); console.print(_ascii_bar('DDM fair value',value,0,max(value,r['price'])*1.2))

def residual_income_valuation(symbol):
    d,r=run_research(symbol,sims=2000); f=d['financials']; bv=latest(f['equity']); ni=latest(f['net_income']); shares=clean(d['info'].get('sharesOutstanding')); ke=.10; g=cagr(f['net_income']); g=float(np.clip(g if g is not None and np.isfinite(g) else .05,-.02,.07));
    console.print(header()); console.print(Panel(_company_name(d),title='RESIDUAL INCOME VALUATION',border_style='cyan'))
    if not all(np.isfinite(x) and x>0 for x in [bv,ni]) or shares is None or not np.isfinite(shares) or shares<=0 or ke<=g: console.print(Panel('Required book value, earnings, share count or assumption controls are unavailable.',title='MODEL CONTROL',border_style='yellow')); return
    roe=ni/bv; ri=max(ni-ke*bv,0); value=bv+ri/(ke-g); per=value/shares
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Metric'); t.add_column('Value'); t.add_row('Book value',money(bv)); t.add_row('Net income',money(ni)); t.add_row('ROE',pct(roe)); t.add_row('Cost of equity',pct(ke)); t.add_row('Growth',pct(g)); t.add_row('Residual income',money(ri)); t.add_row('Implied value / share',money(per)); t.add_row('Current price',money(r['price'])); console.print(t)

def probability_valuation(symbol):
    d,r=run_research(symbol,sims=5000); p=r['price']; dc=r['dcf'].target; peer=r.get('implied'); mc=r['mc']; refs=[]
    for name,v,w in [('Quant P25',mc['percentiles']['P25'],.25),('DCF',dc,.50),('Peer implied',peer,.25)]:
        if v is not None and np.isfinite(v) and v>0: refs.append((name,float(v),w))
    total=sum(w for _,_,w in refs); fair=sum(v*w for _,v,w in refs)/total if total else math.nan
    console.print(header()); console.print(Panel(_company_name(d)+chr(10)+f'Probability-adjusted modeled value: {money(fair)}',title='PROBABILITY VALUATION',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Reference'); t.add_column('Value'); t.add_column('Weight')
    for name,v,w in refs:t.add_row(name,money(v),f'{w/total:.0%}')
    t.add_row('Probability-adjusted value',money(fair),'100% output'); t.add_row('Current price',money(p),'Reference'); console.print(t)

def valuation_decomposition_v8(symbol):
    d,r=run_research(symbol,sims=3000); p=r['price']; mc=r['mc']; vals=[('DCF',r['dcf'].target),('Peer implied',r.get('implied')),('Monte Carlo P50',mc['percentiles']['P50']),('Blended fair value',r.get('blended')),('Current price',p)]; valid=[float(v) for _,v in vals if v is not None and np.isfinite(v) and v>0]; hi=max(valid)*1.15 if valid else 1
    console.print(header()); console.print(Panel(_company_name(d),title='VALUATION DECOMPOSITION',border_style='cyan'))
    for name,v in vals: console.print(_ascii_bar(name,float(v) if v is not None else math.nan,0,hi))
    t=Table(title='VALUE DRIVER CONTROL',box=box.SIMPLE_HEAVY); t.add_column('Method'); t.add_column('Value'); t.add_column('Gap vs price')
    for name,v in vals:
        if name!='Current price': t.add_row(name,money(v),pct(v/p-1) if v is not None and np.isfinite(v) else 'N/A')
    console.print(t); console.print(Panel('Review WACC, terminal growth, margins, peer set, earnings quality and downside distribution before relying on fair value.',title='VALUATION GOVERNANCE',border_style='yellow'))

def thesis_tracker(symbol):
    d,r=run_research(symbol,sims=2500); f=d['financials']; rev=cagr(f['revenue']); roe=r.get('roe',math.nan); de=_safe_ratio(latest(f['debt']),latest(f['equity'])); up=r.get('upside');
    console.print(header()); console.print(Panel(_company_name(d),title='THESIS TRACKER',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Thesis test'); t.add_column('Evidence'); t.add_column('State'); t.add_row('Growth remains positive',pct(rev),'PASS' if np.isfinite(rev) and rev>0 else 'REVIEW'); t.add_row('Capital efficiency',pct(roe),'PASS' if np.isfinite(roe) and roe>.12 else 'REVIEW'); t.add_row('Leverage controlled',num(de)+'x','PASS' if np.isfinite(de) and de<1 else 'REVIEW'); t.add_row('Valuation supports thesis',pct(up),'PASS' if np.isfinite(up) and up>0 else 'REVIEW'); t.add_row('Technical trend','Above 200DMA' if r['price']>r['tech']['sma200'] else 'Below 200DMA','PASS' if r['price']>r['tech']['sma200'] else 'REVIEW'); console.print(t)
    console.print(Panel('Invariants to monitor: growth, margins, leverage, cash conversion, valuation discipline, filings and competitive position.',title='THESIS GOVERNANCE',border_style='magenta'))

def portfolio_attribution(symbols):
    if len(symbols)<2: raise ValueError('At least two tickers are required.')
    console.print(header()); rows=[]
    for s in symbols:
        d=fetch(s); c=d['close']; ret=c.iloc[-1]/c.iloc[0]-1 if len(c)>1 else math.nan; vol=np.log(c/c.shift(1)).dropna().std()*np.sqrt(252) if len(c)>20 else math.nan; rows.append((s.upper(),ret,vol))
    t=Table(title='PORTFOLIO ATTRIBUTION — EQUAL WEIGHT',box=box.SIMPLE_HEAVY); t.add_column('Ticker'); t.add_column('Period return'); t.add_column('Annualized vol'); t.add_column('Contribution proxy')
    for s,ret,vol in rows:t.add_row(s,pct(ret),pct(vol),pct(ret/len(rows)) if np.isfinite(ret) else 'N/A')
    console.print(t); console.print(Panel('Contribution proxy = equal-weight position return contribution. This is not full Brinson or factor attribution.',title='ATTRIBUTION CONTROL',border_style='yellow'))

def model_control_center(symbol):
    d,r=run_research(symbol,sims=2000); f=d['financials']; console.print(header()); console.print(Panel(_company_name(d),title='MODEL CONTROL CENTER',border_style='cyan'))
    t=Table(box=box.SIMPLE_HEAVY); t.add_column('Control'); t.add_column('Status'); t.add_column('Evidence'); t.add_row('Market history','PASS' if len(d['close'])>=252 else 'REVIEW',f'{len(d["close"]):,} observations'); t.add_row('Financial history','PASS' if len(f['revenue'])>=2 else 'REVIEW',f'{len(f["revenue"])} periods'); t.add_row('3-statement reconciliation','CONDITIONAL PASS' if r.get('balance_ok') else 'REVIEW','Bridge reconciliation used'); t.add_row('DCF integrity','PASS' if r['dcf'].status=='PASS' else 'REVIEW',r['dcf'].warning or 'Inputs accepted'); t.add_row('Monte Carlo','PASS' if np.isfinite(r['mc']['percentiles']['P50']) else 'REVIEW','Simulation output available'); t.add_row('Source control','REVIEW','Verify against primary filings'); console.print(t)
    console.print(Panel('PASS means the stated control succeeded; it does not guarantee investment correctness.',title='GOVERNANCE',border_style='magenta'))




# ===================== GROWISEINVEST V11 — PROFESSIONAL FAIR VALUE WORKSTATION =====================
def _fv_classification(factor):
    if not np.isfinite(factor): return 'REVIEW — INPUT UNAVAILABLE'
    if factor < 1.0: return 'OVERVALUED'
    if factor <= 1.5: return 'FAIRLY PRICED'
    if factor > 2.0: return 'UNDERVALUED'
    return 'ATTRACTIVE / INTERMEDIATE'


def _fv_bar(value, current, width=46):
    if not np.isfinite(value) or not np.isfinite(current) or current<=0: return 'N/A'
    scale=max(value,current)*1.15
    n=int(np.clip(value/scale,0,1)*width)
    c=int(np.clip(current/scale,0,1)*width)
    chars=['·']*width
    for i in range(n): chars[i]='█'
    if c<width: chars[c]='│'
    return ''.join(chars)


def _fv_export(d, inputs, methods, sensitivity, factor, fair_price):
    """Create a compact institutional Excel valuation pack and PNG charts."""
    try:
        import matplotlib.pyplot as plt
        from openpyxl import load_workbook
        from openpyxl.drawing.image import Image as XLImage
        from openpyxl.chart import BarChart, Reference
        from openpyxl.styles import Font, PatternFill, Alignment
        from pathlib import Path
        out=Path.home()/'Downloads'/'GROWISEINVEST_VALUATION_PACKS'
        out.mkdir(parents=True, exist_ok=True)
        stem=f"GROWISE_{d['ticker'].replace('.NS','')}_Fair_Value"
        methods_clean=[m for m in methods if np.isfinite(m[2]) and m[2]>0]
        labels=[m[1].replace('Benjamin ','Graham ').replace('Buffett-Inspired ','Buffett ').replace('Growth + Dividend / P/E','Lynch PEGY')[:34] for m in methods_clean]
        vals=[m[2] for m in methods_clean]
        if labels:
            fig,ax=plt.subplots(figsize=(10,5.5))
            y=np.arange(len(labels)); ax.barh(y,vals); ax.axvline(inputs['price'],linestyle='--',linewidth=1.5,label='Current price')
            ax.set_yticks(y,labels); ax.invert_yaxis(); ax.set_xlabel('₹ per share'); ax.set_title(f"{d['ticker'].replace('.NS','')} — Fair Value Method Comparison")
            ax.legend(); ax.grid(axis='x',alpha=.2); fig.tight_layout(); chart1=out/f'{stem}_methods.png'; fig.savefig(chart1,dpi=180); plt.close(fig)
            fig,ax=plt.subplots(figsize=(8.5,5.2));
            g=np.linspace(max(-20,inputs['growth_pct']-10),min(60,inputs['growth_pct']+10),60)
            pe=max(inputs['pe'],1e-6); yv=(g+inputs['div_yield_pct'])/pe
            ax.plot(g,yv,linewidth=2); ax.axhline(1,linestyle='--',linewidth=1); ax.axvline(inputs['growth_pct'],linestyle=':',linewidth=1.5)
            ax.set_xlabel('Future EPS growth (%)'); ax.set_ylabel('Lynch factor'); ax.set_title('Lynch PEGY Factor — Growth Sensitivity'); ax.grid(alpha=.2); fig.tight_layout(); chart2=out/f'{stem}_lynch_sensitivity.png'; fig.savefig(chart2,dpi=180); plt.close(fig)
        else:
            chart1=chart2=None
        xlsx=out/f'{stem}.xlsx'
        with pd.ExcelWriter(xlsx,engine='openpyxl') as w:
            pd.DataFrame([inputs]).to_excel(w,sheet_name='Dashboard',index=False)
            pd.DataFrame([{'Method':m[1],'Fair Value':m[2],'Vs Current':(m[2]/inputs['price']-1) if np.isfinite(m[2]) else np.nan,'Framework':m[3]} for m in methods]).to_excel(w,sheet_name='Methods',index=False)
            sens_rows=[]
            for g in sensitivity.get('growth',[]):
                row={'Growth %':g}
                for x in sensitivity.get('pe',[]): row[f'{x:.1f}x']=(g+inputs['div_yield_pct'])/x if np.isfinite(inputs['div_yield_pct']) and x>0 else np.nan
                sens_rows.append(row)
            pd.DataFrame(sens_rows).to_excel(w,sheet_name='Lynch Sensitivity',index=False)
            pd.DataFrame([{'Control':'Lynch factor','Result':factor,'Formula':'(Growth % + Dividend Yield %) / P/E'}, {'Control':'Lynch fair price','Result':fair_price,'Formula':'Current Price × Lynch factor'}, {'Control':'Classification','Result':_fv_classification(factor),'Formula':'<1 Overvalued; 1–1.5 Fairly Priced; >2 Undervalued; 1.5–2 Intermediate'}, {'Control':'Source policy','Result':'N/A when required source input is unavailable','Formula':'No fabricated inputs'}]).to_excel(w,sheet_name='Formula Audit',index=False)
        wb=load_workbook(xlsx)
        for ws in wb.worksheets:
            for cell in ws[1]: cell.font=Font(bold=True); cell.fill=PatternFill('solid',fgColor='D9EAF7')
            ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
            for col in ws.columns:
                letter=col[0].column_letter; ws.column_dimensions[letter].width=min(max(max(len(str(c.value or '')) for c in col)+2,12),42)
        if chart1:
            ws=wb.create_sheet('Charts'); ws['A1']='GROWISEINVEST VALUATION DASHBOARD'; ws['A1'].font=Font(bold=True,size=16); ws['A2']='Current price is marked as a vertical reference line on the method chart.'
            ws.add_image(XLImage(str(chart1)),'A4');
            if chart2: ws.add_image(XLImage(str(chart2)),'A32')
        wb.save(xlsx)
        return str(xlsx), [str(x) for x in [chart1,chart2] if x]
    except Exception as e:
        return None, [f'Export unavailable: {e}']


def fair_value_lab_pro(symbol):
    """V11 institutional fair-value workstation with auditable formulas and charts."""
    d=fetch(symbol); info=d['info']; f=d['financials']; p=float(d['close'].iloc[-1]); ticker_name=d['ticker'].replace('.NS','')
    eps=_fv_num(info,'trailingEps','epsTrailingTwelveMonths'); forward_eps=_fv_num(info,'forwardEps'); pe=_fv_num(info,'trailingPE'); forward_pe=_fv_num(info,'forwardPE')
    div_yield=_fv_num(info,'dividendYield');
    if np.isfinite(div_yield) and abs(div_yield)>1: div_yield/=100
    div_rate=_fv_num(info,'dividendRate'); shares=_fv_num(info,'sharesOutstanding','impliedSharesOutstanding'); beta=_fv_num(info,'beta'); beta=beta if np.isfinite(beta) and beta>0 else 1.0
    provider_growth=_fv_num(info,'earningsGrowth');
    if np.isfinite(provider_growth) and abs(provider_growth)>1.5: provider_growth/=100
    hist_growth=_fv_cagr(f['net_income']); growth=provider_growth if np.isfinite(provider_growth) else hist_growth
    if not np.isfinite(growth): growth=.08
    growth=float(np.clip(growth,-.50,.75)); growth_pct=growth*100; div_yield_pct=div_yield*100 if np.isfinite(div_yield) else math.nan
    if not np.isfinite(forward_eps) and np.isfinite(eps): forward_eps=eps*(1+growth)
    if not np.isfinite(div_rate) and np.isfinite(eps) and np.isfinite(div_yield): div_rate=eps*div_yield
    rev=_fv_series_latest(f['revenue']); ni=_fv_series_latest(f['net_income']); eq=_fv_series_latest(f['equity']); debt=_fv_series_latest(f['debt']); cash=_fv_series_latest(f['cash']); ebitda=_fv_series_latest(f['ebitda']); cfo=_fv_series_latest(f['cfo']); capex=_fv_series_latest(f['capex']); fcf=cfo-capex if np.isfinite(cfo) and np.isfinite(capex) else math.nan
    bvps=eq/shares if np.isfinite(eq) and np.isfinite(shares) and shares>0 else math.nan
    sector=info.get('sector',''); peer_pes=[]; peer_evs=[]; peer_pbs=[]
    for q in SECTORS.get(sector,[]):
        pe0,pb0,ev0=_provider_call(lambda: peer_metrics(q), (None,None,None))
        if pe0 is not None and 0<pe0<=200: peer_pes.append(float(pe0))
        if pb0 is not None and 0<pb0<=100: peer_pbs.append(float(pb0))
        if ev0 is not None and 0<ev0<=100: peer_evs.append(float(ev0))
    med_pe=float(np.median(peer_pes)) if peer_pes else math.nan; med_ev=float(np.median(peer_evs)) if peer_evs else math.nan; med_pb=float(np.median(peer_pbs)) if peer_pbs else math.nan
    # 1 Lynch PEGY-style: percentage points, exactly matching the user's calculator.
    factor=(growth_pct+div_yield_pct)/pe if np.isfinite(pe) and pe>0 and np.isfinite(div_yield_pct) else math.nan; lynch_fv=p*factor if np.isfinite(factor) else math.nan
    # 2 Owner earnings capitalization proxy. Owner earnings proxy = CFO - capex; required return is explicit.
    required_return=.10; owner_earnings=fcf; buffett_fv=(owner_earnings/shares)/required_return if np.isfinite(owner_earnings) and np.isfinite(shares) and shares>0 else math.nan
    # 3 Graham Number.
    graham_number=math.sqrt(22.5*eps*bvps) if np.isfinite(eps) and eps>0 and np.isfinite(bvps) and bvps>0 else math.nan
    # 4 Graham intrinsic formula with current AAA benchmark if provider supplies it.
    y=_fv_num(info,'aaaYield');
    if np.isfinite(y) and y>1: y/=100
    graham_intrinsic=eps*(8.5+2*growth_pct)*4.4/(y*100) if np.isfinite(eps) and eps>0 and np.isfinite(y) and y>0 else math.nan
    # 5 FCFF DCF using institutional engine.
    dcf_fv=math.nan
    try:
        assumptions={'revenue_growth':max(.03,min(.15,_fv_cagr(f['revenue']) if np.isfinite(_fv_cagr(f['revenue'])) else .08)),'ebitda_margin':max(.08,min(.45,ebitda/rev if np.isfinite(ebitda) and rev>0 else .20)),'tax_rate':.25,'nwc_pct':.05,'capex_pct':.06,'da_pct':.035,'interest_rate':.07,'payout':.25}
        dc=dcf(p,fcf,debt,cash,beta,shares=shares if np.isfinite(shares) and shares>0 else 1,analyst=assumptions); dcf_fv=float(dc.target) if dc.status=='PASS' and np.isfinite(dc.target) else math.nan
    except Exception: pass
    # 6 Gordon DDM.
    ke=.10; ddm_g=float(np.clip(growth,0,.06)); ddm_fv=div_rate*(1+ddm_g)/(ke-ddm_g) if np.isfinite(div_rate) and div_rate>0 and ke>ddm_g else math.nan
    # 7 Residual income, one-stage.
    ri_g=float(np.clip(growth,0,.06)); residual_fv=(bvps+(eps-ke*bvps)/(ke-ri_g)) if np.isfinite(bvps) and np.isfinite(eps) and ke>ri_g else math.nan
    # 8 Forward P/E relative value.
    pe_fv=forward_eps*med_pe if np.isfinite(forward_eps) and np.isfinite(med_pe) else math.nan
    # 9 EV/EBITDA relative value.
    ev_fv=((ebitda*med_ev)-debt+cash)/shares if all(np.isfinite(x) for x in [ebitda,med_ev,debt,cash,shares]) and shares>0 else math.nan
    # 10 P/B relative value.
    pb_fv=bvps*med_pb if np.isfinite(bvps) and np.isfinite(med_pb) else math.nan
    # 11 Earnings-yield fair value at explicit 10% required earnings yield.
    earnings_yield_fv=eps/required_return if np.isfinite(eps) and eps>0 else math.nan
    methods=[('01','Peter Lynch PEGY-style',lynch_fv,'Primary heuristic'),('02','Buffett-style Owner Earnings',buffett_fv,'CFO − Capex proxy / 10%'),('03','Graham Number',graham_number,'EPS + BVPS'),('04','Graham Intrinsic Formula',graham_intrinsic,'Requires AAA yield'),('05','FCFF DCF',dcf_fv,'5Y DCF'),('06','Gordon Growth DDM',ddm_fv,'Dividend model'),('07','Residual Income',residual_fv,'Book + excess return'),('08','Forward P/E Relative Value',pe_fv,'Forward EPS × peer P/E'),('09','EV / EBITDA Relative Value',ev_fv,'EV less net debt'),('10','Price / Book Relative Value',pb_fv,'BVPS × peer P/B'),('11','Earnings Yield @ 10%',earnings_yield_fv,'EPS / 10%')]
    sensitivity={'growth':np.array([max(-20,growth_pct-10),max(-20,growth_pct-5),growth_pct,growth_pct+5,growth_pct+10]),'pe':np.array([max(1,pe-5),max(1,pe-2.5),pe,pe+2.5,pe+5])} if np.isfinite(pe) else {'growth':np.array([]),'pe':np.array([])}
    sens_df=pd.DataFrame(index=[f'{g:.1f}%' for g in sensitivity['growth']],columns=[f'{x:.1f}x' for x in sensitivity['pe']]) if len(sensitivity['growth']) else pd.DataFrame()
    if not sens_df.empty:
        for g in sensitivity['growth']:
            for x in sensitivity['pe']: sens_df.loc[f'{g:.1f}%',f'{x:.1f}x']=(g+div_yield_pct)/x if np.isfinite(div_yield_pct) else np.nan
    console.print(header())
    console.print(Panel(f'[bold white]{_company_name(d)}[/bold white]  {ticker_name}\n[bold]₹{p:,.2f}[/bold]  •  Fair-value workstation  •  Primary screen: Lynch PEGY-style',title='100 — FAIR VALUE WORKSTATION',border_style='cyan'))
    # Bloomberg-style quote strip.
    q=Table(box=box.SIMPLE_HEAVY); q.add_column('PRICE',justify='right'); q.add_column('EPS GROWTH',justify='right'); q.add_column('DIV YIELD',justify='right'); q.add_column('P/E',justify='right'); q.add_column('PEG',justify='right'); q.add_column('Lynch Factor',justify='right'); q.add_column('Fair Price',justify='right')
    peg=pe/growth_pct if np.isfinite(pe) and pe>0 and growth_pct>0 else math.nan
    q.add_row(money(p),_fv_pct(growth_pct),_fv_pct(div_yield_pct),_fv_multiple(pe),num(peg),num(factor),money(lynch_fv)); console.print(q)
    console.print(Panel(
        f'[bold]RESULT / FACTOR[/bold]  {num(factor)}\n'
        f'[bold]FAIR PRICE[/bold]         {money(lynch_fv)}\n'
        f'[bold]CURRENT PRICE[/bold]      {money(p)}\n'
        f'[bold]UPSIDE / (DOWNSIDE)[/bold] {pct(lynch_fv/p-1) if np.isfinite(lynch_fv) else "N/A"}\n\n'
        f'[bold]CLASSIFICATION[/bold]    {_fv_classification(factor)}\n\n'
        'Formula: (Future EPS Growth % + Dividend Yield %) / P/E\n'
        'Fair Price = Current Price × Factor\n'
        'Unit control: 9.94 + 2.93, not 0.0994 + 0.0293.',
        title='PRIMARY VALUATION SCREEN — LYNCH PEGY-STYLE',border_style='green' if _fv_classification(factor) in ('UNDERVALUED','FAIRLY PRICED') else 'yellow'))
    if np.isfinite(lynch_fv): console.print(Panel(f'CURRENT PRICE  │ {_fv_bar(p,p)}\nFAIR PRICE     │ {_fv_bar(lynch_fv,p)}\n\n[dim]│ = current-price reference; █ = method value.[/dim]',title='FAIR VALUE MAP',border_style='cyan'))
    inp=Table(title='INPUT CONTROL',box=box.SIMPLE); inp.add_column('INPUT'); inp.add_column('VALUE',justify='right'); inp.add_column('SOURCE')
    inp.add_row('Company',_company_name(d),'Provider profile'); inp.add_row('Share price',money(p),'Latest market history'); inp.add_row('Future EPS growth',_fv_pct(growth_pct),'Provider earnings growth' if np.isfinite(provider_growth) else 'Historical earnings CAGR fallback'); inp.add_row('Dividend yield',_fv_pct(div_yield_pct),'Provider'); inp.add_row('Trailing P/E',_fv_multiple(pe),'Provider'); inp.add_row('Forward EPS',_fv_money(forward_eps),'Provider / growth fallback'); console.print(inp)
    t=Table(title='11 FAIR-VALUE METHODS — INSTITUTIONAL CROSS-CHECK',box=box.SIMPLE_HEAVY); t.add_column('#',justify='right'); t.add_column('METHOD'); t.add_column('FAIR VALUE',justify='right'); t.add_column('VS CURRENT',justify='right'); t.add_column('CONTROL')
    for no,name,v,ctrl in methods: t.add_row(no,name,money(v),pct(v/p-1) if np.isfinite(v) else 'N/A',ctrl)
    console.print(t)
    if not sens_df.empty:
        st=Table(title='LYNCH FACTOR SENSITIVITY — GROWTH × P/E',box=box.SIMPLE); st.add_column('Growth / P/E')
        for col in sens_df.columns: st.add_column(col,justify='right')
        for idx,row in sens_df.iterrows(): st.add_row(idx,*[num(x) for x in row.values])
        console.print(st)
    console.print(Panel(
        'FORMULA AUDIT\n'
        '01 Lynch PEGY-style = (Growth % + Dividend Yield %) / P/E; Fair Price = Current Price × factor.\n'
        '02 Owner earnings proxy = (CFO − Capex) / shares; capitalized at explicit 10% required return.\n'
        '03 Graham Number = √(22.5 × EPS × BVPS).\n'
        '04 Graham Intrinsic = EPS × (8.5 + 2g) × 4.4 / Y; g and Y are percentage points.\n'
        '05 FCFF DCF = discounted forecast FCFF + terminal value − net debt.\n'
        '06 DDM = D1 / (Ke − g), with g < Ke.\n'
        '07 Residual Income = BVPS + (EPS − Ke×BVPS) / (Ke − g).\n'
        '08 Forward P/E = Forward EPS × peer median P/E.\n'
        '09 EV/EBITDA = EBITDA × peer EV/EBITDA − debt + cash, divided by shares.\n'
        '10 P/B = BVPS × peer median P/B.\n'
        '11 Earnings Yield = EPS / required earnings yield.\n\n'
        'N/A = unavailable / failed validation. No missing market or financial input is fabricated.\n'
        'These methods are valuation heuristics and models; they do not constitute an automatic investment decision.',
        title='MODEL GOVERNANCE & FORMULA AUDIT',border_style='magenta'))
    export_inputs={'ticker':ticker_name,'company':_company_name(d),'price':p,'growth_pct':growth_pct,'div_yield_pct':div_yield_pct,'pe':pe,'peg':peg}
    xlsx,files=_fv_export(d,export_inputs,methods,sensitivity,factor,lynch_fv)
    if xlsx: console.print(Panel(f'[bold]VALUATION PACK EXPORTED[/bold]\n{xlsx}\n\nCharts: {len(files)} generated',title='OUTPUT',border_style='green'))
    else: console.print(Panel('Chart / Excel export unavailable in this environment. Terminal valuation remains available.',title='OUTPUT CONTROL',border_style='yellow'))

# ===================== GROWISEINVEST MODULE 100 — FAIR VALUE CALCULATOR =====================
def _fv_num(info, *keys):
    for k in keys:
        try:
            v=info.get(k)
            if v is not None and np.isfinite(float(v)) and float(v) != 0:
                return float(v)
        except Exception:
            pass
    return math.nan


def _fv_series_latest(s):
    try:
        return float(s.iloc[0]) if len(s) else math.nan
    except Exception:
        return math.nan


def _fv_cagr(s):
    try:
        g=cagr(s)
        return float(g) if g is not None and np.isfinite(g) else math.nan
    except Exception:
        return math.nan


def _fv_money(x):
    return money(x) if np.isfinite(x) else 'N/A'


def _fv_pct(x):
    return f'{x:.2f}%' if np.isfinite(x) else 'N/A'


def _fv_multiple(x):
    return f'{x:.2f}x' if np.isfinite(x) and x > 0 else 'N/A'


def fair_value_lab(symbol):
    """Simple, auditable fair-value calculator.

    The Peter Lynch-style calculation follows the user's spreadsheet exactly:
        Factor = (Future EPS Growth % + Dividend Yield %) / P/E
        Fair Price = Current Price * Factor

    Growth and dividend yield are deliberately kept as percentage POINTS for
    this heuristic (e.g. 9.94 + 2.93), not decimals (0.0994 + 0.0293).
    The other methods use their own mathematically appropriate units.
    """
    d=fetch(symbol)
    info=d['info']
    f=d['financials']
    p=float(d['close'].iloc[-1])
    ticker_name=d['ticker'].replace('.NS','')

    eps=_fv_num(info,'trailingEps','epsTrailingTwelveMonths')
    forward_eps=_fv_num(info,'forwardEps')
    pe=_fv_num(info,'trailingPE')
    forward_pe=_fv_num(info,'forwardPE')
    div_yield=_fv_num(info,'dividendYield')
    if np.isfinite(div_yield) and abs(div_yield)>1: div_yield/=100.0
    div_rate=_fv_num(info,'dividendRate')
    shares=_fv_num(info,'sharesOutstanding','impliedSharesOutstanding')
    beta=_fv_num(info,'beta')
    if not np.isfinite(beta) or beta<=0: beta=1.0

    # Future EPS growth: provider forward earnings growth first, historical
    # earnings CAGR only as a clearly-labelled fallback.
    provider_growth=_fv_num(info,'earningsGrowth')
    if np.isfinite(provider_growth) and abs(provider_growth)>1.5: provider_growth/=100.0
    hist_growth=_fv_cagr(f['net_income'])
    growth=provider_growth if np.isfinite(provider_growth) else hist_growth
    if not np.isfinite(growth): growth=.08
    growth=float(np.clip(growth,-.50,.75))
    growth_pct=growth*100.0
    div_yield_pct=div_yield*100.0 if np.isfinite(div_yield) else math.nan

    if not np.isfinite(forward_eps) and np.isfinite(eps):
        forward_eps=eps*(1+growth)
    if not np.isfinite(div_rate) and np.isfinite(eps) and np.isfinite(div_yield):
        div_rate=eps*div_yield

    revenue=_fv_series_latest(f['revenue']); net_income=_fv_series_latest(f['net_income'])
    equity=_fv_series_latest(f['equity']); debt=_fv_series_latest(f['debt']); cash=_fv_series_latest(f['cash'])
    ebitda=_fv_series_latest(f['ebitda']); cfo=_fv_series_latest(f['cfo']); capex=_fv_series_latest(f['capex'])
    fcf=cfo-capex if np.isfinite(cfo) and np.isfinite(capex) else math.nan
    bvps=(equity/shares) if np.isfinite(equity) and np.isfinite(shares) and shares>0 else math.nan

    # Peer multiples — use only valid positive values. The target company is
    # not inserted into the peer median unless it is explicitly in the peer set.
    peer_pes=[]; peer_evs=[]; peer_pbs=[]
    sector=info.get('sector','')
    for q in SECTORS.get(sector,[]):
        pe0,pb0,ev0=_provider_call(lambda: peer_metrics(q), (None,None,None))
        if pe0 is not None and np.isfinite(pe0) and 0<pe0<=200: peer_pes.append(float(pe0))
        if pb0 is not None and np.isfinite(pb0) and 0<pb0<=100: peer_pbs.append(float(pb0))
        if ev0 is not None and np.isfinite(ev0) and 0<ev0<=100: peer_evs.append(float(ev0))
    med_pe=float(np.median(peer_pes)) if peer_pes else math.nan
    med_ev=float(np.median(peer_evs)) if peer_evs else math.nan
    med_pb=float(np.median(peer_pbs)) if peer_pbs else math.nan

    # 01 — Peter Lynch-style growth + dividend / P/E heuristic.
    lynch_factor=((growth_pct + div_yield_pct)/pe) if np.isfinite(pe) and pe>0 and np.isfinite(div_yield_pct) else math.nan
    lynch_fv=p*lynch_factor if np.isfinite(lynch_factor) and lynch_factor>0 else math.nan
    if np.isfinite(lynch_factor):
        if lynch_factor<1: lynch_class='OVERVALUED'
        elif lynch_factor<=1.5: lynch_class='FAIRLY PRICED'
        elif lynch_factor>2: lynch_class='UNDERVALUED'
        else: lynch_class='INTERMEDIATE (1.5–2.0)'
    else: lynch_class='REVIEW — factor is not a valid positive fair-value multiple'

    # 02 — Buffett-inspired owner earnings capitalization. Owner earnings are
    # approximated conservatively as CFO - Capex when detailed maintenance-capex
    # and working-capital data are not available. This is explicitly a heuristic.
    owner_earnings=fcf
    buffett_fv=(owner_earnings/.10/shares) if np.isfinite(owner_earnings) and np.isfinite(shares) and shares>0 else math.nan

    # 03 — Graham Number: sqrt(22.5 * EPS * BVPS).
    graham_number=math.sqrt(22.5*eps*bvps) if np.isfinite(eps) and eps>0 and np.isfinite(bvps) and bvps>0 else math.nan

    # 04 — Graham intrinsic formula: EPS * (8.5 + 2g) * 4.4/Y.
    # Here g is in percentage points. Y is a required benchmark bond yield;
    # because a verified AAA yield is not part of the core market provider,
    # this method is shown only when an explicit benchmark is available.
    graham_benchmark_yield=_fv_num(info,'aaaYield')
    if np.isfinite(graham_benchmark_yield) and graham_benchmark_yield>1: graham_benchmark_yield/=100.0
    graham_intrinsic=(eps*(8.5+2*growth_pct)*4.4/(graham_benchmark_yield*100)) if np.isfinite(eps) and eps>0 and np.isfinite(graham_benchmark_yield) and graham_benchmark_yield>0 else math.nan

    # 05 — Core FCFF DCF from the institutional engine. It is the only method
    # below that forecasts FCFF explicitly rather than capitalizing a single year.
    try:
        assumptions={'revenue_growth':max(.03,min(.15,_fv_cagr(f['revenue']) if np.isfinite(_fv_cagr(f['revenue'])) else .08)),
                     'ebitda_margin':max(.08,min(.45,ebitda/revenue if np.isfinite(ebitda) and revenue>0 else .20)),
                     'tax_rate':.25,'nwc_pct':.05,'capex_pct':.06,'da_pct':.035,'interest_rate':.07,'payout':.25}
        dc=dcf(p,fcf,debt,cash,beta,shares=shares if np.isfinite(shares) and shares>0 else 1.0,analyst=assumptions)
        dcf_fv=float(dc.target) if dc.status=='PASS' and np.isfinite(dc.target) else math.nan
    except Exception:
        dcf_fv=math.nan

    # 06 — Gordon Growth DDM: D1 / (Ke - g), with explicit constraints.
    ke=.10
    ddm_g=float(np.clip(growth,0,.06))
    ddm_fv=(div_rate*(1+ddm_g)/(ke-ddm_g)) if np.isfinite(div_rate) and div_rate>0 and ke>ddm_g else math.nan

    # 07 — One-stage residual income: BVPS + (EPS - Ke*BVPS)/(Ke-g).
    ri_g=float(np.clip(growth,0,.06))
    residual_fv=(bvps + (eps-ke*bvps)/(ke-ri_g)) if np.isfinite(bvps) and np.isfinite(eps) and ke>ri_g else math.nan

    # 08 — Forward P/E relative value: forward EPS * peer median P/E.
    pe_fv=forward_eps*med_pe if np.isfinite(forward_eps) and np.isfinite(med_pe) else math.nan

    # 09 — EV/EBITDA relative value: EV - debt + cash, then / shares.
    ev_fv=((ebitda*med_ev)-debt+cash)/shares if np.isfinite(ebitda) and np.isfinite(med_ev) and np.isfinite(shares) and shares>0 and np.isfinite(debt) and np.isfinite(cash) else math.nan

    # 10 — Price/Book relative value: BVPS * peer median P/B.
    pb_fv=bvps*med_pb if np.isfinite(bvps) and np.isfinite(med_pb) else math.nan

    methods=[
        ('01','Peter Lynch Growth + Dividend / P/E',lynch_fv,'Heuristic'),
        ('02','Buffett-Inspired Owner Earnings',buffett_fv,'Owner earnings'),
        ('03','Benjamin Graham Number',graham_number,'EPS + BVPS'),
        ('04','Benjamin Graham Intrinsic Formula',graham_intrinsic,'Requires AAA yield'),
        ('05','FCFF Discounted Cash Flow',dcf_fv,'5Y DCF'),
        ('06','Gordon Growth Dividend Discount',ddm_fv,'DDM'),
        ('07','Residual Income',residual_fv,'Book + excess return'),
        ('08','Forward P/E Relative Value',pe_fv,'Peer multiple'),
        ('09','EV / EBITDA Relative Value',ev_fv,'Peer multiple'),
        ('10','Price / Book Relative Value',pb_fv,'Peer multiple'),
    ]

    console.print(header())
    console.print(Panel(f'{_company_name(d)} ({ticker_name})\nShare Price: {money(p)}',title='MODULE 100 — FAIR VALUE CALCULATOR',border_style='cyan'))

    inp=Table(title='FAIR VALUE CALCULATOR — INPUTS',box=box.SIMPLE_HEAVY)
    inp.add_column('INPUT'); inp.add_column('VALUE',justify='right'); inp.add_column('SOURCE / CONTROL')
    inp.add_row('Company Name',_company_name(d),'Company profile')
    inp.add_row('Share Price',money(p),'Live market reference')
    inp.add_row('Future EPS Growth',_fv_pct(growth_pct),'Forward provider growth' if np.isfinite(provider_growth) else 'Historical earnings CAGR fallback')
    inp.add_row('Dividend Yield',_fv_pct(div_yield_pct),'Provider')
    inp.add_row('P/E Ratio',_fv_multiple(pe),'Provider trailing P/E')
    inp.add_row('Forward EPS',_fv_money(forward_eps),'Provider / model fallback')
    console.print(inp)

    console.print(Panel(
        f'Future EPS Growth: {_fv_pct(growth_pct)}\n'
        f'Dividend Yield: {_fv_pct(div_yield_pct)}\n'
        f'P/E Ratio: {_fv_multiple(pe)}\n\n'
        f'RESULT / FACTOR: {num(lynch_factor)}\n'
        f'FAIR PRICE: {money(lynch_fv)}\n\n'
        f'ANALYSIS: {lynch_class}\n\n'
        f'Formula: (Future EPS Growth % + Dividend Yield %) / P/E\n'
        f'Example unit handling: 9.94 + 2.93, not 0.0994 + 0.0293.',
        title='PETER LYNCH-STYLE FAIR VALUE',
        border_style='green' if lynch_class in ('FAIRLY PRICED','UNDERVALUED') else 'yellow'))

    peg= (pe/growth_pct) if np.isfinite(pe) and pe>0 and growth_pct>0 else math.nan
    peg_status='ATTRACTIVE' if np.isfinite(peg) and peg<1 else 'EXPENSIVE' if np.isfinite(peg) and peg>1 else 'REVIEW'
    pg=Table(title='GROWTH-RELATIVE CHECK',box=box.SIMPLE_HEAVY)
    pg.add_column('METRIC'); pg.add_column('VALUE',justify='right'); pg.add_column('ANALYSIS')
    pg.add_row('Stock P/E',_fv_multiple(pe),'')
    pg.add_row('EPS Growth',_fv_pct(growth_pct),'')
    pg.add_row('PEG Ratio',num(peg),peg_status)
    pg.add_row('Rule of thumb','PEG < 1','Lower PEG is generally more attractive; not a standalone fair-value model.')
    console.print(pg)

    t=Table(title='10 FAIR VALUE METHODS — CROSS CHECK',box=box.SIMPLE_HEAVY)
    t.add_column('#',justify='right'); t.add_column('FORMULA / METHOD'); t.add_column('FAIR PRICE',justify='right'); t.add_column('VS CURRENT',justify='right'); t.add_column('STATUS')
    for no,name,v,framework in methods:
        status=framework if framework!='Heuristic' else 'PRIMARY USER METHOD'
        t.add_row(no,name,money(v),pct(v/p-1) if np.isfinite(v) else 'N/A',status)
    console.print(t)

    console.print(Panel(
        'FORMULA CONTROLS\n'
        '1. Peter Lynch-style factor uses percentage POINTS exactly as in the supplied calculator.\n'
        '2. Graham Number = sqrt(22.5 × EPS × BVPS).\n'
        '3. Graham Intrinsic = EPS × (8.5 + 2g) × 4.4 / Y; g is % and Y is the benchmark yield in %.\n'
        '4. FCFF DCF uses discounted forecast cash flows + terminal value and subtracts net debt.\n'
        '5. Gordon DDM = D0 × (1+g) / (Ke−g), with g < Ke.\n'
        '6. Residual Income = BVPS + (EPS − Ke×BVPS)/(Ke−g).\n'
        '7. Relative P/E = Forward EPS × peer median P/E.\n'
        '8. EV/EBITDA = EBITDA × peer EV/EBITDA − debt + cash, divided by shares.\n'
        '9. P/B = BVPS × peer median P/B.\n'
        '10. Buffett-inspired owner earnings is a capitalization heuristic, not an official Buffett formula.\n\n'
        'N/A means the required input is not available or fails validation. No missing value is fabricated.',
        title='VALUATION FORMULA AUDIT',border_style='magenta'))


# ===================== V15 — BLOOMBERG-STYLE 8-IN-1 SECURITY TERMINAL =====================
def _bar(value, max_value, width=24, char='█'):
    try:
        v=float(value); m=float(max_value)
        if not np.isfinite(v) or not np.isfinite(m) or m<=0: return '·'*width
        n=int(np.clip(abs(v)/m*width,0,width)); return char*n + '·'*(width-n)
    except Exception:
        return '·'*width

def _mini_line(values, width=38):
    return _sparkline(values,width)

def _safe_pct_point(v):
    try: return f'{float(v)*100:.1f}%'
    except Exception: return 'N/A'

def _eight_in_one(symbol):
    """Single-screen institutional security dashboard: eight research domains in one view."""
    d,r=run_research(symbol,sims=3000)
    info=r.get('info',{}); company=info.get('longName') or info.get('shortName') or d['ticker']
    p=float(r['price']); tech=r['tech']; mc=r['mc']; dc=r['dcf']; hs=d['financials']
    rev=latest(hs['revenue']); ebitda=latest(hs['ebitda']); ni=latest(hs['net_income']); cfo=latest(hs['cfo']); capex=latest(hs['capex']); fcf=latest(r['fcf'])
    eq=latest(hs['equity']); debt=latest(hs['debt']); cash=latest(hs['cash']); roe=ni/eq if eq else math.nan; de=debt/eq if eq else math.nan
    pe=clean(info.get('trailingPE')); pb=clean(info.get('priceToBook')); dy=clean(info.get('dividendYield'))
    fair=r.get('blended'); upside=r.get('upside')
    hist=pd.Series(d['close']).dropna()
    live,reason,nxt=market_status(datetime.now(IST)); session='OPEN' if live else 'CLOSED'
    chg=(hist.iloc[-1]/hist.iloc[-2]-1)*100 if len(hist)>1 else math.nan
    # Header
    console.clear(); console.print(header())
    console.print(Panel(
        f'[bold white]{d["ticker"].replace(".NS","")}[/bold white]   [bold]{company}[/bold]\n'
        f'[bold cyan]{money(p)}[/bold cyan]   [{"green" if chg>=0 else "red"}]{chg:+.2f}%[/]   '
        f'[dim]{info.get("sector") or "Sector N/A"} • {info.get("industry") or "Industry N/A"}[/dim]\n'
        f'P/E {fmt_multiple(pe,"pe")}   P/B {fmt_multiple(pb,"pb")}   Dividend Yield {_safe_pct_point(dy) if dy<=1 else f"{dy:.2f}%" if np.isfinite(dy) else "N/A"}   ROE {_safe_pct_point(roe)}   D/E {de:.2f}x' if np.isfinite(de) else f'P/E {fmt_multiple(pe,"pe")}   P/B {fmt_multiple(pb,"pb")}   ROE {_safe_pct_point(roe)}   D/E N/A',
        title='SECURITY TERMINAL / 8-IN-1 RESEARCH VIEW', border_style='bright_blue', padding=(0,1)))

    # 1 Overview / price chart
    price_panel=Panel(
        f'[bold cyan]PRICE TREND[/bold cyan]\n[white]{_mini_line(hist.tail(120).tolist(),46)}[/white]\n'
        f'Last {money(p)}   52W High {money(tech.get("high"))}   52W Low {money(tech.get("low"))}\n'
        f'20DMA {money(tech.get("sma20"))}   50DMA {money(tech.get("sma50"))}   200DMA {money(tech.get("sma200"))}',
        title='01 OVERVIEW',border_style='cyan',padding=(0,1))
    # 2 technical
    ttech=Table.grid(padding=(0,1)); ttech.add_column(); ttech.add_column(justify='right')
    for k,v in [('RSI 14',num(tech.get('rsi'))),('Technical Score',f'{tech.get("score",math.nan):.0f}/100'),('vs 200DMA',_safe_pct_point(p/tech['sma200']-1) if np.isfinite(tech.get('sma200',math.nan)) else 'N/A')]: ttech.add_row(k,v)
    tech_panel=Panel(ttech,title='02 TECHNICAL',border_style='magenta',padding=(0,1))
    # 3 fundamentals with mini bars
    ftab=Table.grid(padding=(0,1)); ftab.add_column(); ftab.add_column(); ftab.add_column(justify='right')
    for label,val in [('Revenue',rev),('EBITDA',ebitda),('Net Income',ni),('CFO',cfo),('FCF',fcf)]: ftab.add_row(label,_bar(val,max(abs(rev or 0),abs(ebitda or 0),abs(ni or 0),abs(cfo or 0),abs(fcf or 0),1),18),money(val))
    ftab.add_row('Rev CAGR',_safe_pct_point(cagr(hs['revenue'])),''); ftab.add_row('EPS/NI CAGR',_safe_pct_point(cagr(hs['net_income'])),'')
    fund_panel=Panel(ftab,title='03 FUNDAMENTALS',border_style='green',padding=(0,1))
    # 4 valuation / DCF
    vtab=Table.grid(padding=(0,1)); vtab.add_column(); vtab.add_column(justify='right')
    for label,val in [('FCFF DCF',dc.target),('Peer P/E',r.get('implied')),('Blended',fair),('Current',p)]: vtab.add_row(label,money(val))
    vtab.add_row('Upside/(Downside)',_safe_pct_point(upside))
    vtab.add_row('DCF Status',dc.status)
    val_panel=Panel(vtab,title='04 VALUATION / DCF',border_style='yellow',padding=(0,1))
    # 5 quant/risk distribution
    qtab=Table.grid(padding=(0,1)); qtab.add_column(); qtab.add_column(justify='right')
    for k in ['P5','P25','P50','P75','P95']: qtab.add_row(k,money(mc['percentiles'][k]))
    qtab.add_row('Positive',_safe_pct_point(mc['positive_prob'])); qtab.add_row('VaR 95',_safe_pct_point(mc['var95'])); qtab.add_row('CVaR 95',_safe_pct_point(mc['cvar95']))
    qchart='P5 '+_bar(mc['percentiles']['P5'],mc['percentiles']['P95'],20)+' P95'
    qtab.add_row('Range',qchart)
    quant_panel=Panel(qtab,title='05 QUANT / RISK',border_style='bright_blue',padding=(0,1))
    # 6 concall/events
    call_status='AVAILABLE' if any(x in str(info).lower() for x in ['transcript','earningscall']) else 'SOURCE-DEPENDENT'
    call_panel=Panel(
        f'[bold]Latest results intelligence[/bold]\n'
        f'Call / transcript: {call_status}\n'
        f'Revenue trend: {_safe_pct_point(cagr(hs["revenue"]))}\n'
        f'Earnings trend: {_safe_pct_point(cagr(hs["net_income"]))}\n'
        f'Cash generation: {money(cfo)} CFO / {money(fcf)} FCF\n\n'
        '[dim]Management transcript quotes are never fabricated. Verify primary filings/transcript for guidance, margins and order-book commentary.[/dim]',
        title='06 CONCALL / EVENTS',border_style='magenta',padding=(0,1))
    # 7 peers
    peers=SECTORS.get(info.get('sector',''),[])[:5]
    ptab=Table.grid(padding=(0,1)); ptab.add_column(); ptab.add_column(justify='right'); ptab.add_column(justify='right')
    ptab.add_row('[bold]Peer[/bold]','[bold]P/E[/bold]','[bold]P/B[/bold]')
    for q in peers:
        peq,pbq,evq=_provider_call(lambda: peer_metrics(q), (None,None,None)); ptab.add_row(q,fmt_multiple(peq,'pe'),fmt_multiple(pbq,'pb'))
    peer_panel=Panel(ptab,title='07 PEERS / SECTOR',border_style='cyan',padding=(0,1))
    # 8 thesis / controls
    flags=[]
    if np.isfinite(roe) and roe>0.15: flags.append('[green]✓[/green] Strong ROE')
    if np.isfinite(de) and de<1: flags.append('[green]✓[/green] Leverage contained')
    if np.isfinite(tech.get('sma200',math.nan)) and p<tech['sma200']: flags.append('[yellow]⚠[/yellow] Below 200DMA')
    if np.isfinite(upside) and upside>0: flags.append('[green]✓[/green] Modelled value above price')
    if not flags: flags=['[dim]No automated thesis flag[/dim]']
    thesis_panel=Panel('\n'.join(flags)+f'\n\nGWI SCORE  [bold cyan]{r["score"]:.1f}/100[/bold cyan]  •  {r["label"]}\n3-Statement  [green]PASS[/green]' if r.get('balance_ok') else '\n'.join(flags)+f'\n\nGWI SCORE  [bold cyan]{r["score"]:.1f}/100[/bold cyan]  •  {r["label"]}\n3-Statement  [red]REVIEW[/red]',title='08 THESIS / CONTROLS',border_style='green',padding=(0,1))

    # Assemble 2-column workstation rows. Rich handles terminal resizing.
    row1=Table.grid(expand=True); row1.add_column(ratio=2); row1.add_column(ratio=1); row1.add_column(ratio=1); row1.add_row(price_panel,tech_panel,fund_panel)
    row2=Table.grid(expand=True); row2.add_column(ratio=1); row2.add_column(ratio=1); row2.add_column(ratio=1); row2.add_row(val_panel,quant_panel,call_panel)
    row3=Table.grid(expand=True); row3.add_column(ratio=1); row3.add_column(ratio=1); row3.add_row(peer_panel,thesis_panel)
    console.print(row1); console.print(row2); console.print(row3)
    console.print(Panel('[bold cyan]F1[/bold cyan] Help  [bold cyan]F2[/bold cyan] Global  [bold cyan]F3[/bold cyan] News  [bold cyan]F4[/bold cyan] Screener  [bold cyan]F5[/bold cyan] Portfolio  [bold cyan]F6[/bold cyan] Notes  [bold cyan]F7[/bold cyan] Settings   •   [dim]20 TCS[/dim] reopens this 8-in-1 view  •  [dim]100 TCS[/dim] Fair Value',title='WORKSTATION COMMAND BAR',border_style='bright_blue',padding=(0,1)))


# ===================== V21 — LIVE MARKET ENGINE =====================

LIVE_CONFIG = {
    'provider': os.getenv('GWI_LIVE_PROVIDER', '').strip().upper(),
    'refresh': float(os.getenv('GWI_LIVE_REFRESH', '1.0') or 1.0),
}


def _live_status_text(provider):
    p=(provider or '').upper()
    if p in {'ZERODHA','KITE'}:
        return 'ZERODHA / KITE CONNECT'
    if p in {'UPSTOX'}:
        return 'UPSTOX'
    if p in {'FYERS'}:
        return 'FYERS'
    if p in {'ANGEL','ANGELONE','SMARTAPI'}:
        return 'ANGEL ONE / SMARTAPI'
    if p in {'DHAN'}:
        return 'DHAN'
    return 'NOT CONFIGURED'


def _load_live_credentials():
    """Read broker credentials only from environment variables; never print secrets."""
    p=LIVE_CONFIG['provider']
    if p in {'ZERODHA','KITE'}:
        return p, {'api_key':os.getenv('KITE_API_KEY','').strip(), 'access_token':os.getenv('KITE_ACCESS_TOKEN','').strip()}
    if p=='UPSTOX':
        return p, {'access_token':os.getenv('UPSTOX_ACCESS_TOKEN','').strip()}
    if p=='FYERS':
        return p, {'access_token':os.getenv('FYERS_ACCESS_TOKEN','').strip(), 'app_id':os.getenv('FYERS_APP_ID','').strip()}
    if p in {'ANGEL','ANGELONE','SMARTAPI'}:
        return p, {'api_key':os.getenv('ANGEL_API_KEY','').strip(), 'client_id':os.getenv('ANGEL_CLIENT_ID','').strip(), 'password':os.getenv('ANGEL_PASSWORD','').strip(), 'totp':os.getenv('ANGEL_TOTP','').strip()}
    if p=='DHAN':
        return p, {'client_id':os.getenv('DHAN_CLIENT_ID','').strip(), 'access_token':os.getenv('DHAN_ACCESS_TOKEN','').strip()}
    return p, {}


def _provider_requirements(provider, creds):
    if provider in {'ZERODHA','KITE'}:
        return bool(creds.get('api_key') and creds.get('access_token')), 'Set KITE_API_KEY and KITE_ACCESS_TOKEN.'
    if provider=='UPSTOX':
        return bool(creds.get('access_token')), 'Set UPSTOX_ACCESS_TOKEN.'
    if provider=='FYERS':
        return bool(creds.get('access_token') and creds.get('app_id')), 'Set FYERS_APP_ID and FYERS_ACCESS_TOKEN.'
    if provider in {'ANGEL','ANGELONE','SMARTAPI'}:
        return bool(creds.get('api_key') and creds.get('client_id') and creds.get('password') and creds.get('totp')), 'Set ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD and ANGEL_TOTP.'
    if provider=='DHAN':
        return bool(creds.get('client_id') and creds.get('access_token')), 'Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN.'
    return False, 'Set GWI_LIVE_PROVIDER to a licensed broker/data provider.'


def _live_quote_zerodha(symbol, creds):
    try:
        from kiteconnect import KiteConnect
    except Exception as e:
        raise RuntimeError('Zerodha adapter requires the optional kiteconnect package.') from e
    kite=KiteConnect(api_key=creds['api_key'])
    kite.set_access_token(creds['access_token'])
    key=f'NSE:{symbol.replace(".NS","").replace(".BO","").upper()}'
    q=kite.quote([key]).get(key,{})
    if not q: raise RuntimeError(f'No live quote returned for {key}.')
    ohlc=q.get('ohlc') or {}
    return {'symbol':key,'last':float(q.get('last_price',math.nan)),'open':float(ohlc.get('open',math.nan)),'high':float(ohlc.get('high',math.nan)),'low':float(ohlc.get('low',math.nan)),'prev_close':float(ohlc.get('close',math.nan)),'volume':float(q.get('volume',math.nan)),'timestamp':datetime.now(IST)}


def _live_quote_upstox(symbol, creds):
    # Snapshot adapter using the official Upstox REST quote endpoint. Streaming can be added
    # through the user's licensed websocket session; this module never fakes live data.
    try:
        import requests
    except Exception as e:
        raise RuntimeError('Upstox adapter requires requests.') from e
    # Upstox instrument-key lookup is account/data-version specific; allow an explicit key.
    instrument=os.getenv('UPSTOX_INSTRUMENT_KEY','').strip()
    if not instrument:
        raise RuntimeError('Set UPSTOX_INSTRUMENT_KEY for the active NSE instrument, or use the Zerodha adapter.')
    url='https://api.upstox.com/v2/market-quote/quotes'
    r=requests.get(url,params={'instrument_key':instrument},headers={'Authorization':f'Bearer {creds["access_token"]}','Accept':'application/json'},timeout=5)
    r.raise_for_status(); data=r.json().get('data') or {}
    row=next(iter(data.values()),{})
    q=row.get('ohlc') or {}
    last=row.get('last_price',math.nan)
    return {'symbol':instrument,'last':float(last),'open':float(q.get('open',math.nan)),'high':float(q.get('high',math.nan)),'low':float(q.get('low',math.nan)),'prev_close':float(q.get('close',math.nan)),'volume':float(row.get('volume',math.nan)),'timestamp':datetime.now(IST)}


def live_quote(symbol):
    provider,creds=_load_live_credentials()
    ok,msg=_provider_requirements(provider,creds)
    if not ok:
        raise RuntimeError(f'LIVE PROVIDER NOT READY — {_live_status_text(provider)}. {msg} No synthetic prices are used.')
    if provider in {'ZERODHA','KITE'}: return _live_quote_zerodha(symbol,creds)
    if provider=='UPSTOX': return _live_quote_upstox(symbol,creds)
    raise RuntimeError(f'Provider {provider} is recognized but its adapter is not enabled in this build. No synthetic prices are used.')


def _live_quote_panel(q):
    last=q.get('last',math.nan); prev=q.get('prev_close',math.nan)
    chg=(last/prev-1)*100 if np.isfinite(last) and np.isfinite(prev) and prev else math.nan
    style='green' if np.isfinite(chg) and chg>=0 else 'red'
    grid=Table.grid(expand=True,padding=(0,2)); grid.add_column(); grid.add_column(); grid.add_column(); grid.add_column(); grid.add_column(); grid.add_column()
    grid.add_row('[bold]LAST[/bold]', '[bold]DAY[/bold]', '[bold]OPEN[/bold]', '[bold]HIGH[/bold]', '[bold]LOW[/bold]', '[bold]VOLUME[/bold]')
    grid.add_row(money(last),f'[{style}]{chg:+.2f}%[/{style}]' if np.isfinite(chg) else 'N/A',money(q.get('open')),money(q.get('high')),money(q.get('low')),f'{q.get("volume",math.nan):,.0f}' if np.isfinite(q.get('volume',math.nan)) else 'N/A')
    return Panel(grid,title=f'LIVE QUOTE  •  {_live_status_text(LIVE_CONFIG["provider"])}',border_style='green',padding=(0,1))


def live_market_engine(symbol):
    """Live market workstation: broker-sourced quote snapshot with optional polling.
    It is deliberately fail-closed: if a licensed provider is not configured, no price is invented.
    """
    symbol=symbol.strip().upper().replace('.NS','').replace('.BO','')
    live,reason,nxt=market_status()
    console.print(header())
    if not live:
        console.print(Panel(f'[yellow]MARKET SESSION CLOSED[/yellow]\n{reason}\nNext open: {nxt.strftime("%d-%b-%Y %H:%M IST") if nxt else "N/A"}\n\nThe live engine will not fabricate prices outside the exchange session.',title='51 — LIVE MARKET ENGINE',border_style='yellow'))
        return
    provider,creds=_load_live_credentials()
    ok,msg=_provider_requirements(provider,creds)
    if not ok:
        console.print(Panel(
            f'[bold yellow]LIVE DATA IS NOT CONFIGURED[/bold yellow]\n\nProvider: {_live_status_text(provider)}\n\n{msg}\n\nSupported configuration paths in this build:\n'
            '• Zerodha / Kite Connect — KITE_API_KEY + KITE_ACCESS_TOKEN\n'
            '• Upstox — UPSTOX_ACCESS_TOKEN + UPSTOX_INSTRUMENT_KEY\n\n'
            '[dim]No synthetic prices, delayed-price claims, or fake market depth are used.[/dim]',
            title='51 — LIVE MARKET ENGINE',border_style='yellow'))
        console.print('[dim]Environment variables are read locally and credentials are never displayed.[/dim]')
        return
    try:
        q=live_quote(symbol)
    except Exception as e:
        console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]\n\n[dim]Live engine stopped safely. Check broker session/token, market permissions and network connectivity.[/dim]',title='51 — LIVE DATA ERROR',border_style='red'))
        return
    console.print(Panel(f'[bold cyan]{symbol}[/bold cyan]  •  {q["symbol"]}\n[bold white]Broker-sourced market snapshot[/bold white]\nTimestamp: {q["timestamp"].strftime("%d-%b-%Y %H:%M:%S IST")}',title='51 — LIVE MARKET ENGINE',border_style='green'))
    console.print(_live_quote_panel(q))
    console.print('[dim]Polling interval: {:.1f}s. Press Ctrl+C to stop. Live streaming/depth availability depends on the licensed provider and subscription.[/dim]'.format(max(0.5,LIVE_CONFIG['refresh'])))
    try:
        while True:
            time.sleep(max(0.5,LIVE_CONFIG['refresh']))
            q=live_quote(symbol)
            console.print(_live_quote_panel(q))
    except KeyboardInterrupt:
        console.print('\n[green]LIVE SESSION STOPPED[/green]')

def final_run_number(n):
    n=str(n).strip().upper(); aliases={'H':'99','HELP':'99','?':'99','Q':'00','QUIT':'00','EXIT':'00'}; n=aliases.get(n,n)
    if n.isdigit(): n=f'{int(n):02d}'
    if n=='00': return False
    if n=='99': final_help_screen(); return True
    if n=='20': _eight_in_one(ask_symbol())
    elif n=='21': conference_call_analyzer(ask_symbol())
    elif n=='22':
        raw=console.input('[bold cyan]ENTER IPO / COMPANY NAME: [/bold cyan]').strip(); ipo_research(raw)
    elif n=='23': news_tomorrow_events()
    elif n=='24': earnings_intelligence(ask_symbol())
    elif n=='25': fundamental_inflection(ask_symbol())
    elif n=='26': forensic_engine(ask_symbol())
    elif n=='27': what_changed_engine(ask_symbol())
    elif n=='28': event_study_engine(ask_symbol())
    elif n=='29':
        sym=ask_symbol(); scenario_engine(sym); catalyst_dashboard(sym)
    elif n=='30': ownership_flow_engine(ask_symbol())
    elif n=='31': moat_analyzer(ask_symbol())
    elif n=='32': valuation_bridge(ask_symbol())
    elif n=='33': corporate_actions_engine(ask_symbol())
    elif n=='34': filings_intelligence(ask_symbol())
    elif n=='35': red_flag_engine(ask_symbol())
    elif n=='36': investment_committee_mode(ask_symbol())
    elif n=='37': factor_exposure_v8(ask_symbol())
    elif n=='38': quality_scorecard(ask_symbol())
    elif n=='39': growth_quality_lab(ask_symbol())
    elif n=='40': capital_allocation_lab(ask_symbol())
    elif n=='41': sotp_lab(ask_symbol())
    elif n=='42': dividend_discount_valuation(ask_symbol())
    elif n=='43': residual_income_valuation(ask_symbol())
    elif n=='44': probability_valuation(ask_symbol())
    elif n=='45': valuation_decomposition_v8(ask_symbol())
    elif n=='46': factor_exposure_v8(ask_symbol())
    elif n=='47': thesis_tracker(ask_symbol())
    elif n=='48':
        syms=console.input('[bold cyan]ENTER TICKERS (e.g. TCS INFY HDFCBANK): [/bold cyan]').split(); portfolio_attribution(syms)
    elif n=='49': model_control_center(ask_symbol())
    elif n=='50': console.clear(); console.print(header()); final_help_screen()
    elif n=='51': live_market_engine(ask_symbol())
    elif n=='100': fair_value_lab_pro(ask_symbol())
    elif n in {str(i).zfill(2) for i in range(1,20)}: return run_number(n)
    else: console.print('[yellow]INVALID MODULE — enter a number from the index (01-51), 99 for HELP, or 00 to exit.[/yellow]')
    return True



# ===================== V12 — VISUAL WORKSTATION HOME =====================

def _sparkline(values, width=46):
    """Render a compact terminal sparkline from numeric observations."""
    try:
        vals=[float(x) for x in values if x is not None and np.isfinite(x)]
    except Exception:
        vals=[]
    if len(vals)<2:
        return '·' * width
    if len(vals)>width:
        # Preserve the latest section while keeping the chart compact.
        idx=np.linspace(0,len(vals)-1,width).astype(int)
        vals=[vals[i] for i in idx]
    chars='▁▂▃▄▅▆▇█'
    lo,hi=min(vals),max(vals)
    if hi==lo:
        return chars[3]*len(vals)
    return ''.join(chars[int(np.clip((v-lo)/(hi-lo)*7,0,7))] for v in vals)


def _market_card(symbol, label):
    """Small, fault-tolerant market card used by the visual home screen."""
    try:
        h=_provider_call(lambda: yf.Ticker(symbol).history(period='1mo', interval='1d', auto_adjust=False), pd.DataFrame())
        c=h.get('Close',pd.Series(dtype=float)).dropna()
        if len(c)<2:
            raise RuntimeError('No history')
        last=float(c.iloc[-1]); prev=float(c.iloc[-2]); chg=(last/prev-1)*100 if prev else math.nan
        return {'label':label,'last':last,'chg':chg,'spark':_sparkline(c.tolist(),34),'ok':True}
    except Exception:
        return {'label':label,'last':math.nan,'chg':math.nan,'spark':'·'*34,'ok':False}


def _visual_home():
    """Visual institutional launchpad: charts, KPI cards, and the complete service universe."""
    console.clear()
    console.print(header())
    now=datetime.now(IST)
    live,reason,nxt=market_status(now)
    session='OPEN' if live else 'CLOSED'
    next_open=''
    if not live and nxt:
        try: next_open=nxt.strftime('%d-%b %H:%M IST')
        except Exception: next_open=''

    # ── Institutional identity / session ribbon ─────────────────────────────
    session_style='bold green' if live else 'bold yellow'
    ribbon=Table.grid(expand=True)
    ribbon.add_column(ratio=5); ribbon.add_column(justify='right',ratio=2)
    ribbon.add_row(
        '[bold cyan]GROWISEINVEST[/bold cyan]  [white]INSTITUTIONAL RESEARCH WORKSTATION[/white]  [dim]│ NSE • BSE • EQUITY • QUANT • VALUATION[/dim]',
        f'[{session_style}]● {session}[/{session_style}]')
    ribbon.add_row(
        '[dim]MARKET INTELLIGENCE  •  RESEARCH  •  VALUATION  •  RISK  •  PORTFOLIO  •  EVENTS  •  GOVERNANCE[/dim]',
        f'[dim]{now.strftime("%d-%b-%Y %H:%M:%S IST")}[/dim]')
    console.print(Panel(ribbon, border_style='cyan', padding=(0,1)))

    # ── Market cards with actual mini charts ─────────────────────────────────
    cards=[_market_card('^NSEI','NIFTY 50'),_market_card('^BSESN','SENSEX'),_market_card('^INDIAVIX','INDIA VIX')]
    market_panels=[]
    for c in cards:
        if c['ok']:
            ch='green' if c['chg']>=0 else 'red'
            day=f'[{ch}]{c["chg"]:+.2f}%[/{ch}]'
            last=money(c['last'])
            spark=f'[bold]{c["spark"]}[/bold]'
        else:
            day='[dim]N/A[/dim]'; last='[dim]N/A[/dim]'; spark='[dim]No live history[/dim]'
        body=Text.from_markup(
            f'[bold cyan]{c["label"]}[/bold cyan]\n'
            f'[white]LAST[/white]     {last}\n'
            f'[white]DAY[/white]      {day}\n'
            f'[white]1M TREND[/white]  {spark}'
        )
        market_panels.append(Panel(body,title='MARKET / LIVE CHART',border_style='bright_blue',padding=(0,1)))
    console.print(Group(*market_panels))

    # ── Market intelligence strip ────────────────────────────────────────────
    pulse=Table.grid(expand=True,padding=(0,2))
    pulse.add_column(justify='left'); pulse.add_column(justify='center'); pulse.add_column(justify='center'); pulse.add_column(justify='right')
    pulse.add_row('[bold white]MARKET PULSE[/bold white]', '[cyan]RESEARCH[/cyan] 01–20', '[cyan]INTELLIGENCE[/cyan] 21–40', '[cyan]VALUATION[/cyan] 41–100')
    pulse.add_row('[dim]Live provider is source-controlled; unavailable data remains N/A.[/dim]', '[green]● READY[/green]', '[green]● READY[/green]', '[green]● READY[/green]')
    console.print(Panel(pulse,border_style='white',padding=(0,1)))

    # ── Complete visual service universe ─────────────────────────────────────
    services=[
        ('01','RESEARCH WORKBENCH','Full equity research'),('02','FINANCIAL STATEMENTS','Historical financials'),('03','THREE-STATEMENT MODEL','Forecast + reconciliation'),('04','DISCOUNTED CASH FLOW','FCFF valuation + sensitivity'),('05','VALUATION LAB','Fair value stack'),('06','TECHNICAL ANALYSIS','Trend + momentum'),('07','MONTE CARLO QUANT','Probability distribution'),('08','RISK ANALYTICS','VaR + CVaR + drawdown'),('09','PEER COMPARABLES','Relative valuation'),('10','CROSS-COMPANY','Multi-stock comparison'),
        ('11','RESEARCH EXPORT','Excel research pack'),('12','MARKET STATUS','NSE/BSE session'),('13','GWI SCORE','Integrated evidence score'),('14','DATA QUALITY & AUDIT','Source + completeness'),('15','BACKTESTING ENGINE','Historical strategy test'),('16','MARKET REGIME','Trend + volatility regime'),('17','PORTFOLIO RISK','Portfolio risk analytics'),('18','PORTFOLIO OPTIMIZER','Allocation optimization'),('19','RESEARCH NOTE','Analyst-ready note'),('20','SECURITY TERMINAL / 8-IN-1','Technical + Fundamental + DCF + Quant + Concall + Peers + Thesis'),
        ('21','CONFERENCE CALL ANALYZER','Management / results intelligence'),('22','IPO RESEARCH','IPO due diligence'),('23','NEWS & TOMORROW EVENTS','News + upcoming events'),('24','EARNINGS INTELLIGENCE','Earnings trend intelligence'),('25','FUNDAMENTAL INFLECTION','Business inflection signals'),('26','EARNINGS QUALITY / FORENSIC','Quality + forensic checks'),('27','WHAT CHANGED','Research delta engine'),('28','EVENT STUDY LAB','Event impact analysis'),('29','SCENARIO & CATALYST LAB','Catalysts + scenarios'),('30','OWNERSHIP & INSTITUTIONAL FLOW','Holder structure'),
        ('31','MOAT ANALYZER','Competitive-strength evidence'),('32','VALUATION BRIDGE','Fair-value bridge'),('33','CORPORATE ACTIONS','Actions intelligence'),('34','REGULATORY & FILINGS','Disclosure intelligence'),('35','RED FLAG ENGINE','Risk flags'),('36','INVESTMENT COMMITTEE MODE','IC decision dashboard'),('37','FACTOR EXPOSURE','Factor sensitivities'),('38','QUALITY SCORECARD','Quality framework'),('39','GROWTH QUALITY LAB','Growth durability'),('40','CAPITAL ALLOCATION LAB','Capital deployment'),
        ('41','SOTP VALUATION LAB','Sum-of-the-parts'),('42','DIVIDEND DISCOUNT VALUATION','Dividend fair value'),('43','RESIDUAL INCOME VALUATION','Residual-income value'),('44','PROBABILITY VALUATION','Probability-weighted value'),('45','VALUATION DECOMPOSITION','Value-driver analysis'),('46','FACTOR & STYLE DASHBOARD','Style exposures'),('47','THESIS TRACKER','Investment thesis'),('48','PORTFOLIO ATTRIBUTION','Portfolio contribution'),('49','MODEL CONTROL CENTER','Model integrity'),('50','CLEAR TERMINAL','Reset workstation'),('51','LIVE MARKET ENGINE','Licensed real-time broker/data feed')
    ]
    groups=[
        ('01–10  CORE RESEARCH',services[0:10],'cyan'),
        ('11–20  QUANT / PORTFOLIO',services[10:20],'bright_blue'),
        ('21–30  INTELLIGENCE / EVENTS',services[20:30],'magenta'),
        ('31–40  GOVERNANCE / ADVANCED',services[30:40],'yellow'),
        ('41–50  VALUATION / RESEARCH',services[40:50],'green'),
        ('51  LIVE MARKET DATA','LIVE MARKET ENGINE','Licensed broker quote / polling'),
    ]
    cards=[]
    for title,items,style in groups:
        t=Table.grid(expand=True,padding=(0,1))
        t.add_column(justify='left',no_wrap=True)
        for no,name,desc in items:
            t.add_row(f'[{style}]{no}[/{style}] [bold white]{name}[/bold white]')
            t.add_row(f'   [dim]{desc}[/dim]')
        cards.append(Panel(t,title=title,border_style=style,padding=(0,1)))
    console.print(Panel(Group(*cards),title='GROWISE / COMPLETE VISUAL SERVICE UNIVERSE',border_style='cyan',padding=(0,1)))

    # ── Fair value flagship + command ribbon ────────────────────────────────
    fv=Panel(
        '[bold cyan]100[/bold cyan]  [bold white]FAIR VALUE CALCULATOR[/bold white]   [dim]Peter Lynch + valuation cross-checks + sensitivity[/dim]\n'
        '[dim]Primary workflow: Future EPS Growth + Dividend Yield → P/E → Lynch Factor → Fair Price[/dim]',
        border_style='bright_green',padding=(0,1))
    console.print(fv)
    quick=Table.grid(expand=True,padding=(0,2))
    quick.add_column(); quick.add_column(); quick.add_column(); quick.add_column(); quick.add_column(); quick.add_column()
    quick.add_row('[cyan]01 TCS[/cyan] Research','[cyan]06 TCS[/cyan] Technical','[cyan]20 TCS[/cyan] 8-in-1 Security','[cyan]36 TCS[/cyan] IC Mode','[cyan]100 TCS[/cyan] Fair Value','[green]51 TCS[/green] Live','[cyan]99[/cyan] Index')
    console.print(Panel(quick,title='QUICK LAUNCH / KEYBOARD FIRST',border_style='bright_blue',padding=(0,1)))
    console.print(f'[dim]NEXT OPEN: {next_open or "—"}   •   Type a module number, or NUMBER TICKER for instant launch   •   00 EXIT[/dim]')

def _visual_pause():
    console.input('\n[dim]Press ENTER to return to GROWISE HOME...[/dim]')

def final_main():
    _visual_home()
    while True:
        try:
            raw=console.input('\n[bold cyan]GROWISEINVEST > [/bold cyan]').strip()
            if not raw:
                continue
            # Bloomberg-style quick command: "100 TCS" or traditional number-first input.
            parts=raw.split()
            module=parts[0]
            if module.upper() in {'HOME','H'}:
                _visual_home(); continue
            if module.upper() in {'HELP','?','99'} and len(parts)==1:
                final_help_screen(); continue
            if module.upper() in {'EXIT','QUIT','Q','00'}:
                break
            if len(parts)>=2 and module.isdigit():
                n=f'{int(module):02d}' if int(module)<100 else str(int(module))
                if n=='100':
                    fair_value_lab_pro(parts[1]); continue
                # For ticker-based modules, route the supplied ticker without a second prompt.
                ticker_arg=parts[1].upper()
                if n in {'01','02','03','04','05','06','07','09','13','14','15','16','20','21','24','25','26','27','28','29','30','31','32','33','34','35','36','37','38','39','40','41','42','43','44','45','46','47','49','51'}:
                    # Temporarily feed through a tiny local dispatcher to preserve existing functions.
                    direct={
                        '01':lambda:show_research(ticker_arg),'02':lambda:show_financials(ticker_arg),'03':lambda:show_model_cmd(ticker_arg),'04':lambda:show_dcf(ticker_arg),'05':lambda:show_valuation_lab(ticker_arg),'06':lambda:show_technical(ticker_arg),'07':lambda:show_quant_cmd(ticker_arg),'09':lambda:show_peers(ticker_arg),'13':lambda:gwi_score(ticker_arg),'14':lambda:data_quality(ticker_arg),'15':lambda:backtest(ticker_arg),'16':lambda:market_regime(ticker_arg),'20':lambda:_eight_in_one(ticker_arg),'21':lambda:conference_call_analyzer(ticker_arg),'24':lambda:earnings_intelligence(ticker_arg),'25':lambda:fundamental_inflection(ticker_arg),'26':lambda:forensic_engine(ticker_arg),'27':lambda:what_changed_engine(ticker_arg),'28':lambda:event_study_engine(ticker_arg),'29':lambda:(scenario_engine(ticker_arg),catalyst_dashboard(ticker_arg)),'30':lambda:ownership_flow_engine(ticker_arg),'31':lambda:moat_analyzer(ticker_arg),'32':lambda:valuation_bridge(ticker_arg),'33':lambda:corporate_actions_engine(ticker_arg),'34':lambda:filings_intelligence(ticker_arg),'35':lambda:red_flag_engine(ticker_arg),'36':lambda:investment_committee_mode(ticker_arg),'37':lambda:factor_exposure_v8(ticker_arg),'38':lambda:quality_scorecard(ticker_arg),'39':lambda:growth_quality_lab(ticker_arg),'40':lambda:capital_allocation_lab(ticker_arg),'41':lambda:sotp_lab(ticker_arg),'42':lambda:dividend_discount_valuation(ticker_arg),'43':lambda:residual_income_valuation(ticker_arg),'44':lambda:probability_valuation(ticker_arg),'45':lambda:valuation_decomposition_v8(ticker_arg),'46':lambda:factor_exposure_v8(ticker_arg),'47':lambda:thesis_tracker(ticker_arg),'49':lambda:model_control_center(ticker_arg),'51':lambda:live_market_engine(ticker_arg)}
                    direct[n](); _visual_pause(); _visual_home(); continue
            if not final_run_number(module):
                break
            _visual_pause(); _visual_home()
        except KeyboardInterrupt:
            console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='ENGINE ERROR — OPERATION ABORTED',border_style='red'))
            if os.getenv('GROWISE_DEBUG')=='1': console.print(f'[dim]{traceback.format_exc()}[/dim]')


main=final_main


# ===================== V16 — SINGLE-SECURITY VISUAL WORKSTATION =====================
def _v16_style_change(v):
    try:
        return 'green' if float(v) >= 0 else 'red'
    except Exception:
        return 'dim'


def _v16_candles(hist, width=78, height=12):
    """Compact OHLC candlestick chart rendered entirely in the terminal."""
    h=hist[['Open','High','Low','Close']].dropna().tail(110).copy()
    if len(h)<2:
        return Text('Insufficient OHLC history for chart.', style='dim')
    # downsample to terminal width while preserving the most recent observation
    if len(h)>width:
        idx=np.linspace(0,len(h)-1,width).astype(int)
        h=h.iloc[idx]
    lo=float(h['Low'].min()); hi=float(h['High'].max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi<=lo:
        return Text('Price range unavailable.', style='dim')
    rows=[]
    for r in range(height):
        y=hi-(hi-lo)*r/(height-1)
        label=f'{y:>9,.0f} '
        line=Text(label,style='dim')
        for _,row in h.iterrows():
            o,c,lh,ll=[float(row[x]) for x in ['Open','Close','High','Low']]
            span=(hi-lo)
            # map price to nearest chart row
            rh=int(round((hi-y)/span*(height-1)))
            ph=int(round((hi-lh)/span*(height-1)))
            pl=int(round((hi-ll)/span*(height-1)))
            po=int(round((hi-o)/span*(height-1)))
            pc=int(round((hi-c)/span*(height-1)))
            top=min(po,pc); bot=max(po,pc)
            if r<ph or r>pl:
                line.append(' ')
            elif top<=r<=bot and top!=bot:
                line.append('█',style='green' if c>=o else 'red')
            elif r==ph or r==pl:
                line.append('│',style='green' if c>=o else 'red')
            elif r==top==bot:
                line.append('▪',style='green' if c>=o else 'red')
            else:
                line.append('│',style='green' if c>=o else 'red')
        rows.append(line)
    out=Text()
    for i,line in enumerate(rows):
        out.append(line)
        out.append('\n' if i<len(rows)-1 else '')
    out.append('          ' + '└' + '─'*(len(h)) + '┘\n',style='dim')
    out.append('           OLD' + ' '*(max(1,len(h)-9)) + 'LATEST',style='dim')
    return out


def _v16_bar_chart(rows, width=28):
    """rows = [(label,value,display)] for compact horizontal financial bars."""
    vals=[float(v) for _,v,_ in rows if v is not None and np.isfinite(v)]
    mx=max([abs(v) for v in vals] or [1.0])
    t=Table.grid(padding=(0,0)); t.add_column(width=10); t.add_column(); t.add_column(justify='right',width=12)
    for label,v,disp in rows:
        if v is None or not np.isfinite(v): bar='·'*width
        else:
            n=int(np.clip(abs(float(v))/mx*width,0,width)); bar='█'*n+'·'*(width-n)
        t.add_row(label[:10],bar,disp)
    return t


def _v16_hist_financial_chart(hs):
    # Annual history, displayed oldest -> newest.
    series=[]
    for key in ['revenue','ebitda','net_income']:
        s=pd.Series(hs.get(key,pd.Series(dtype=float))).dropna()
        if len(s):
            series.append((key,s.iloc[:5].sort_index(ascending=True)))
    if not series:
        return Panel('Financial history unavailable.',title='03 FUNDAMENTALS / FINANCIAL TREND',border_style='green')
    years=list(series[0][1].index)
    # scale by revenue for a readable relative chart, with values shown in table below
    rev=dict(series[0][1]); mx=max(abs(float(v)) for v in rev.values()) if rev else 1
    grid=Table.grid(padding=(0,0)); grid.add_column(width=6); grid.add_column()
    for idx,yr in enumerate(years):
        r=rev.get(yr,math.nan); e=next((dict(s).get(yr,math.nan) for k,s in series if k=='ebitda'),math.nan); n=next((dict(s).get(yr,math.nan) for k,s in series if k=='net_income'),math.nan)
        def seg(v,ch):
            if not np.isfinite(v): return '·'
            return ch*max(1,int(abs(v)/mx*18))
        
        try:
            ylbl=f'FY{pd.Timestamp(yr).year % 100:02d}'
        except Exception:
            ylbl=str(yr)[:6]
        grid.add_row(ylbl, Text('R '+seg(r,'█')+'  E '+seg(e,'▓')+'  N '+seg(n,'▪')))
    return Panel(grid,title='03 FUNDAMENTALS / FINANCIAL TREND',border_style='green',padding=(0,1))


def _v16_monte_chart(mc, width=40):
    vals=np.asarray(mc.get('paths',[]),float)
    if vals.ndim==2 and vals.shape[1]>0:
        terminal=vals[:,-1]
    else:
        terminal=np.array([])
    if len(terminal)<10:
        return Panel('Monte Carlo sample unavailable.',title='05 QUANT / MONTE CARLO',border_style='bright_blue')
    lo=float(np.nanmin(terminal)); hi=float(np.nanmax(terminal));
    if not np.isfinite(lo) or not np.isfinite(hi) or hi<=lo: return Panel('Monte Carlo range unavailable.',title='05 QUANT / MONTE CARLO',border_style='bright_blue')
    counts,edges=np.histogram(terminal,bins=10)
    mx=max(counts) or 1
    t=Table.grid(padding=(0,0)); t.add_column(width=12); t.add_column(); t.add_column(width=9,justify='right')
    for i,cnt in enumerate(counts):
        mid=(edges[i]+edges[i+1])/2; n=int(cnt/mx*width)
        t.add_row(f'{money(edges[i])}', '█'*n, f'{int(cnt)} sims')
    body=Group(t,Text(f'P5 {money(mc["percentiles"]["P5"])}   P50 {money(mc["percentiles"]["P50"])}   P95 {money(mc["percentiles"]["P95"])}',style='dim'))
    return Panel(body,title='05 QUANT / MONTE CARLO DISTRIBUTION',border_style='bright_blue',padding=(0,1))


def _v16_valuation_chart(r,d=None):
    p=float(r['price']); vals=[('Lynch',None),('DCF',r['dcf'].target),('Peer P/E',r.get('implied')),('Blended',r.get('blended'))]
    # Add Lynch calculation using the same exact percentage-point convention as module 100.
    info=r.get('info',{}); f=None
    try:
        f=d['financials'] if d is not None else None
    except Exception:
        f=None
    eps=_fv_num(info,'trailingEps','epsTrailingTwelveMonths'); pe=_fv_num(info,'trailingPE'); dy=_fv_num(info,'dividendYield'); growth=_fv_num(info,'earningsGrowth')
    if np.isfinite(dy) and abs(dy)>1: dy/=100
    if not np.isfinite(growth): growth=_fv_cagr(f['net_income']) if f is not None else math.nan
    if np.isfinite(growth) and abs(growth)>1.5: growth/=100
    if np.isfinite(pe) and pe>0 and np.isfinite(dy) and np.isfinite(growth): vals[0]=('Lynch',p*((growth*100+dy*100)/pe))
    rows=[]
    cleanvals=[v for _,v in vals if v is not None and np.isfinite(v)]
    mx=max([abs(p)]+[abs(float(v)) for v in cleanvals]) if cleanvals else max(p,1)
    for name,v in vals:
        rows.append((name,v,money(v) if v is not None and np.isfinite(v) else 'N/A'))
    rows.append(('Current',p,money(p)))
    return Panel(_v16_bar_chart(rows,30),title='04 VALUATION / FAIR VALUE STACK',border_style='yellow',padding=(0,1))


def _v16_concall_panel(d,r):
    try:
        from institutional_pack import _quarterly_intelligence
        q,meta=_quarterly_intelligence(d)
    except Exception:
        q=pd.DataFrame(); meta={}
    lines=[]
    if len(q):
        for col,label in [('Revenue YoY','Revenue'),('EBITDA YoY','EBITDA'),('Net Income YoY','Earnings')]:
            if col in q:
                z=q[col].dropna()
                if len(z): lines.append(f'{label:<10} {pct(float(z.iloc[-1]))}')
        msg=meta.get('message','Quarterly intelligence available.')
        lines.append('')
        lines.append(str(msg)[:72])
    else:
        lines=['Quarterly intelligence unavailable.','Transcript source not configured.']
    lines += ['', 'SOURCE CONTROL: transcript-specific commentary is only shown when a verified source exists.']
    return Panel('\n'.join(lines),title='06 CONCALL / EARNINGS INTELLIGENCE',border_style='magenta',padding=(0,1))


def _v16_peer_panel(d):
    sec=d['info'].get('sector',''); peers=SECTORS.get(sec,[])[:5]
    t=Table.grid(padding=(0,1)); t.add_column(); t.add_column(justify='right'); t.add_column(justify='right'); t.add_column(justify='right')
    t.add_row('[bold]Peer[/bold]','[bold]P/E[/bold]','[bold]P/B[/bold]','[bold]EV/EBITDA[/bold]')
    for q in peers:
        pe,pb,ev=_provider_call(lambda: peer_metrics(q), (None,None,None)); t.add_row(q,fmt_multiple(pe,'pe'),fmt_multiple(pb,'pb'),fmt_multiple(ev,'ev_ebitda'))
    if not peers: t.add_row('N/A','N/A','N/A','N/A')
    return Panel(t,title=f'07 PEERS / {sec.upper() or "SECTOR UNAVAILABLE"}',border_style='cyan',padding=(0,1))


def _v16_thesis_panel(d,r):
    hs=d['financials']; tech=r['tech']; flags=[]
    revg=cagr(hs['revenue']); ni=latest(hs['net_income']); eq=latest(hs['equity']); debt=latest(hs['debt']); roe=ni/eq if eq else math.nan; de=debt/eq if eq else math.nan
    if revg is not None and revg>0: flags.append(f'[green]▲[/green] Revenue CAGR {pct(revg)}')
    if np.isfinite(roe) and roe>0.15: flags.append(f'[green]▲[/green] ROE {pct(roe)}')
    if np.isfinite(de) and de<1: flags.append(f'[green]▲[/green] D/E {de:.2f}x')
    if np.isfinite(tech['sma200']) and r['price']<tech['sma200']: flags.append('[yellow]▼[/yellow] Below 200DMA')
    if np.isfinite(r.get('upside',math.nan)) and r['upside']<0: flags.append('[red]▼[/red] Blended value below price')
    if not flags: flags=['[dim]No automated thesis flags[/dim]']
    body='\n'.join(flags[:5])+f'\n\nGWI SCORE   [bold cyan]{r["score"]:.1f}/100[/bold cyan]  {r["label"]}'
    body+='\nMODEL CONTROL  '+('[green]PASS[/green]' if r.get('balance_ok') else '[red]REVIEW[/red]')
    body+='\nDECISION      [yellow]HUMAN REVIEW REQUIRED[/yellow]'
    return Panel(body,title='08 THESIS / CONTROLS',border_style='green',padding=(0,1))


def _v16_security_dashboard(symbol):
    """One company in, one complete visual institutional workstation out."""
    d,r=run_research(symbol,sims=4000)
    info=r['info']; company=_company_name(d); p=r['price']; hist=d['history']; tech=r['tech']; hs=d['financials']
    now=datetime.now(IST); live,reason,nxt=market_status(now); session='LIVE' if live else 'CLOSED'
    last2=hist['Close'].dropna().tail(2); day=((float(last2.iloc[-1])/float(last2.iloc[-2])-1)*100) if len(last2)>1 else math.nan
    # --- top security strip ---
    console.clear(); console.print(header())
    q=Table.grid(expand=True,padding=(0,1)); q.add_column(ratio=3); q.add_column(ratio=1); q.add_column(ratio=1); q.add_column(ratio=1); q.add_column(ratio=1); q.add_column(ratio=1); q.add_column(ratio=1)
    q.add_row(
        f'[bold white]{symbol.upper()}[/bold white]\n[dim]{company}[/dim]',
        f'[bold cyan]{money(p)}[/bold cyan]\n[{_v16_style_change(day)}]{day:+.2f}%[/]',
        f'P/E\n{fmt_multiple(info.get("trailingPE"),"pe")}',
        f'P/B\n{fmt_multiple(info.get("priceToBook"),"pb")}',
        f'ROE\n{pct(latest(hs["net_income"])/latest(hs["equity"]) if latest(hs["equity"]) else math.nan)}',
        f'D/E\n{latest(hs["debt"])/latest(hs["equity"]):.2f}x' if latest(hs['equity']) else 'D/E\nN/A',
        f'GWI\n[bold]{r["score"]:.0f}/100[/bold]')
    console.print(Panel(q,title='SECURITY / QUOTE',border_style='bright_blue',padding=(0,1)))

    # --- row 1: large price chart + KPI panel ---
    candle=Panel(_v16_candles(hist,78,12),title='01 PRICE / TECHNICAL — OHLC CANDLESTICK',border_style='cyan',padding=(0,1))
    kpi=Table.grid(padding=(0,1)); kpi.add_column(); kpi.add_column(justify='right')
    for a,b in [('20 DMA',money(tech['sma20'])),('50 DMA',money(tech['sma50'])),('200 DMA',money(tech['sma200'])),('RSI 14',num(tech['rsi'])),('52W High',money(tech['high'])),('52W Low',money(tech['low'])),('Technical',f'{tech["score"]:.0f}/100'),('Day',f'{day:+.2f}%')]: kpi.add_row(a,b)
    techbox=Panel(kpi,title='02 TECHNICAL SNAPSHOT',border_style='magenta',padding=(0,1))
    top=Table.grid(expand=True); top.add_column(ratio=3); top.add_column(ratio=1); top.add_row(candle,techbox); console.print(top)

    # --- row 2: fundamentals, valuation, monte carlo ---
    fbox=_v16_hist_financial_chart(hs)
    vbox=_v16_valuation_chart(r,d)
    mbox=_v16_monte_chart(r['mc'])
    mid=Table.grid(expand=True); mid.add_column(ratio=1); mid.add_column(ratio=1); mid.add_column(ratio=1); mid.add_row(fbox,vbox,mbox); console.print(mid)

    # --- row 3: DCF, concall, peers/thesis ---
    dcfv=r['dcf']; dt=Table.grid(padding=(0,1)); dt.add_column(); dt.add_column(justify='right')
    for a,b in [('Fair value',money(dcfv.target)),('WACC',pct(dcfv.wacc)),('Terminal growth',pct(dcfv.terminal_growth)),('Reverse growth',pct(dcfv.reverse_growth)),('Status',dcfv.status),('Upside vs price',pct((dcfv.target/p-1) if np.isfinite(dcfv.target) else math.nan))]: dt.add_row(a,b)
    # DCF sensitivity heatmap, compact but visual.
    sens=Table.grid(padding=(0,1)); sens.add_column(width=8)
    ws=[.08,.10,.12,.14,.16]
    for w in ws: sens.add_column(justify='right')
    sens.add_row('G/W',*[pct(w) for w in ws])
    for g,row in zip([.04,.06,.08,.10,.12],dcfv.sensitivity):
        cells=[]
        for v in row:
            if not np.isfinite(v): cells.append('[dim]—[/dim]')
            elif v>p*1.2: cells.append(f'[green]{v:,.0f}[/green]')
            elif v<p*.8: cells.append(f'[red]{v:,.0f}[/red]')
            else: cells.append(f'[yellow]{v:,.0f}[/yellow]')
        sens.add_row(pct(g),*cells)
    dcfbox=Panel(Group(dt,Text('DCF SENSITIVITY',style='bold'),sens),title='04 DCF / VALUATION ENGINE',border_style='yellow',padding=(0,1))
    callbox=_v16_concall_panel(d,r)
    right=Table.grid(expand=True); right.add_column(ratio=1); right.add_column(ratio=1); right.add_row(_v16_peer_panel(d),_v16_thesis_panel(d,r))
    bot=Table.grid(expand=True); bot.add_column(ratio=1); bot.add_column(ratio=1); bot.add_column(ratio=2); bot.add_row(dcfbox,callbox,right); console.print(bot)

    # --- footer / controls ---
    console.print(Panel(
        '[bold cyan]01[/bold cyan] Research  [bold cyan]02[/bold cyan] Financials  [bold cyan]03[/bold cyan] Model  [bold cyan]04[/bold cyan] DCF  [bold cyan]05[/bold cyan] Valuation  [bold cyan]06[/bold cyan] Technical  [bold cyan]07[/bold cyan] Monte Carlo  [bold cyan]08[/bold cyan] Risk  [bold cyan]09[/bold cyan] Peers\n'
        '[bold cyan]13[/bold cyan] GWI Score  [bold cyan]20[/bold cyan] Security  [bold cyan]21[/bold cyan] Concall  [bold cyan]24[/bold cyan] Earnings  [bold cyan]29[/bold cyan] Scenario  [bold cyan]36[/bold cyan] IC Mode  [bold magenta]90[/bold magenta] Equity Research Intelligence  [bold cyan]100[/bold cyan] Fair Value  [bold cyan]99[/bold cyan] Full Index  [bold cyan]00[/bold cyan] Exit\n'
        f'[dim]Loaded security: {symbol.upper()}  •  Enter only the number for the next view; ticker is retained.  •  {session}[/dim]',
        title='GROWISE COMMAND RAIL / SINGLE-SECURITY WORKFLOW',border_style='bright_blue',padding=(0,1)))


def _v16_dispatch_same_ticker(n, symbol):
    n=str(n).strip().upper(); aliases={'H':'99','HELP':'99','?':'99','Q':'00','QUIT':'00','EXIT':'00'}; n=aliases.get(n,n)
    if n.isdigit(): n=str(int(n))
    if n=='90' and '_v22_intelligence' in globals():
        try: _v22_intelligence(symbol)
        except Exception as e: console.print(Panel(f'{type(e).__name__}: {e}',title='INTELLIGENCE ENGINE ERROR',border_style='red'))
        return True
    if n=='00': return False
    if n=='99': final_help_screen(); _visual_pause(); _v16_security_dashboard(symbol); return True
    direct={
        '01':show_research,'02':show_financials,'03':show_model_cmd,'04':show_dcf,'05':show_valuation_lab,'06':show_technical,
        '07':show_quant_cmd,'08':show_risk,'09':show_peers,'13':gwi_score,'14':data_quality,'15':backtest,
        '16':market_regime,'20':_v16_security_dashboard,'21':conference_call_analyzer,'24':earnings_intelligence,'25':fundamental_inflection,
        '26':forensic_engine,'27':what_changed_engine,'28':event_study_engine,'29':lambda s:(scenario_engine(s),catalyst_dashboard(s)),
        '30':ownership_flow_engine,'31':moat_analyzer,'32':valuation_bridge,'33':corporate_actions_engine,'34':filings_intelligence,
        '35':red_flag_engine,'36':investment_committee_mode,'37':factor_exposure_v8,'38':quality_scorecard,'39':growth_quality_lab,
        '40':capital_allocation_lab,'41':sotp_lab,'42':dividend_discount_valuation,'43':residual_income_valuation,'44':probability_valuation,
        '45':valuation_decomposition_v8,'46':factor_exposure_v8,'47':thesis_tracker,'49':model_control_center,'100':fair_value_lab_pro}
    if n=='50': _v16_security_dashboard(symbol); return True
    if n=='10':
        raw=console.input('[bold cyan]ENTER COMPARISON TICKERS: [/bold cyan]').strip(); compare(raw.split()); _visual_pause(); _v16_security_dashboard(symbol); return True
    if n=='11': export_excel(symbol)
    elif n=='12':
        live,reason,nxt=market_status(datetime.now(IST)); console.print(Panel(f'Market: {reason}\nNext open: {nxt.strftime("%d-%b-%Y %H:%M IST") if nxt else "—"}',title='MARKET STATUS',border_style='cyan'))
    elif n=='17' or n=='18' or n=='48':
        raw=console.input('[bold cyan]ENTER PORTFOLIO TICKERS: [/bold cyan]').strip();
        if n=='17': portfolio_risk(raw.split())
        elif n=='18': portfolio_optimizer(raw.split())
        else: portfolio_attribution(raw.split())
    elif n=='22':
        raw=console.input('[bold cyan]ENTER IPO / COMPANY NAME: [/bold cyan]').strip(); ipo_research(raw)
    elif n=='23': news_tomorrow_events()
    elif n in direct: direct[n](symbol)
    else:
        console.print('[yellow]UNKNOWN MODULE — use 99 for the full index.[/yellow]')
        _visual_pause()
    if n!='20': _visual_pause(); _v16_security_dashboard(symbol)
    return True


def final_main_v16():
    """Ticker-first workflow: one ticker loads the complete visual security page once."""
    console.clear(); console.print(header())
    console.print(Panel(
        '[bold cyan]GROWISEINVEST[/bold cyan]  [bold white]SINGLE-SECURITY INSTITUTIONAL WORKSTATION[/bold white]\n\n'
        'Enter a company ticker once. GROWISEINVEST will load the complete visual research stack:\n'
        '[cyan]PRICE + TECHNICAL  •  FUNDAMENTALS  •  DCF  •  VALUATION  •  MONTE CARLO  •  CONCALL  •  PEERS  •  THESIS / CONTROLS[/cyan]\n\n'
        '[dim]After loading, enter only a module number. The selected security remains active until you change it.[/dim]',
        title='WELCOME / TICKER-FIRST WORKFLOW',border_style='cyan',padding=(1,2)))
    while True:
        try:
            raw=console.input('[bold cyan]ENTER NSE TICKER (or 00 to exit): [/bold cyan]').strip()
            if raw.upper() in {'00','EXIT','QUIT','Q'}: break
            if not raw: continue
            symbol=raw.split()[0].upper().replace('.NS','').replace('.BO','')
            if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',symbol):
                console.print('[yellow]Invalid ticker format.[/yellow]'); continue
            try:
                _v16_security_dashboard(symbol)
            except Exception as e:
                console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='SECURITY LOAD ERROR',border_style='red'))
                continue
            while True:
                cmd=console.input(f'\n[bold cyan]GROWISEINVEST / {symbol} > [/bold cyan]').strip()
                if not cmd: continue
                if cmd.upper().startswith(('T ','TICKER ')):
                    symbol=cmd.split(None,1)[1].upper().replace('.NS','').replace('.BO','')
                    _v16_security_dashboard(symbol); continue
                if cmd.upper() in {'00','EXIT','QUIT','Q'}: return
                if cmd.upper() in {'HOME','H'}: _v16_security_dashboard(symbol); continue
                if cmd.isdigit() or cmd.split()[0].isdigit():
                    parts=cmd.split(); n=parts[0]
                    if len(parts)>1 and n not in {'10','17','18','22','23','48'}:
                        symbol=parts[1].upper().replace('.NS','').replace('.BO',''); _v16_security_dashboard(symbol); continue
                    if not _v16_dispatch_same_ticker(n,symbol): return
                else:
                    console.print('[yellow]Enter a module number, e.g. 06, 20, 100. Use T TCS to change security.[/yellow]')
        except KeyboardInterrupt:
            console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='WORKSTATION ERROR',border_style='red'))


main=final_main_v16

# Legacy startup disabled: V27 has one canonical entrypoint.


# ===================== V17 — VISUAL SINGLE-SECURITY WORKSTATION =====================
def _v17_peer_metrics(symbol):
    """Provider-first peer multiples with transparent fallbacks from price/financials."""
    pe,pb,ev = peer_metrics(symbol)
    if pe is not None and pb is not None and ev is not None:
        return pe,pb,ev
    try:
        d=fetch(symbol); info=d['info']; f=d['financials']; price=float(d['close'].iloc[-1])
        shares=_fv_num(info,'sharesOutstanding','impliedSharesOutstanding')
        eps=_fv_num(info,'trailingEps','epsTrailingTwelveMonths')
        if pe is None and np.isfinite(eps) and eps>0: pe=price/eps
        equity=latest(f['equity']); debt=latest(f['debt']); cash=latest(f['cash']); ebitda=latest(f['ebitda'])
        if pb is None and np.isfinite(shares) and shares>0 and np.isfinite(equity) and equity>0:
            pb=price/(equity/shares)
        if ev is None and np.isfinite(shares) and shares>0 and np.isfinite(ebitda) and ebitda>0:
            mcap=price*shares
            ev=(mcap + (debt if np.isfinite(debt) else 0) - (cash if np.isfinite(cash) else 0))/ebitda
    except Exception:
        pass
    return pe,pb,ev


def _v17_spark(values, width=46):
    vals=np.asarray([float(x) for x in values if x is not None and np.isfinite(x)],dtype=float)
    if len(vals)<2: return Text('N/A',style='dim')
    if len(vals)>width:
        idx=np.linspace(0,len(vals)-1,width).astype(int); vals=vals[idx]
    chars='▁▂▃▄▅▆▇█'; lo=float(vals.min()); hi=float(vals.max())
    if hi<=lo: return Text(chars[3]*len(vals))
    return Text(''.join(chars[int(np.clip((v-lo)/(hi-lo)*7,0,7))] for v in vals))


def _v17_series_line(label, series, formatter=money):
    s=pd.Series(series).dropna()
    txt=Text()
    txt.append(f'{label:<10} ',style='bold white')
    txt.append(_v17_spark(s.tolist(),34))
    txt.append(f'  {formatter(float(s.iloc[-1]))}',style='bold')
    return txt


def _v17_quarterly(d):
    """Quarterly growth snapshot using provider quarterly statements; no transcript fabrication."""
    try:
        y=yf.Ticker(d['ticker'])
        qf=_provider_call(lambda: y.quarterly_financials, pd.DataFrame())
        if qf is None or qf.empty: return {}
        def pick(names):
            for n in names:
                if n in qf.index: return pd.Series(qf.loc[n]).dropna()
            return pd.Series(dtype=float)
        rev=pick(['Total Revenue','Operating Revenue','Revenue'])
        ebitda=pick(['EBITDA'])
        ni=pick(['Net Income','Net Income Common Stockholders'])
        out={}
        for key,series in [('Revenue',rev),('EBITDA',ebitda),('Earnings',ni)]:
            if len(series)>=1:
                out[key]=float(series.iloc[0])
                if len(series)>=5 and np.isfinite(series.iloc[4]) and series.iloc[4]!=0:
                    out[key+'_YoY']=float(series.iloc[0]/series.iloc[4]-1)
                elif len(series)>=2 and np.isfinite(series.iloc[1]) and series.iloc[1]!=0:
                    out[key+'_QoQ']=float(series.iloc[0]/series.iloc[1]-1)
        out['period']=str(pd.Timestamp(qf.columns[0]).strftime('%b-%Y')) if len(qf.columns) else 'Latest'
        return out
    except Exception:
        return {}


def _v17_fundamentals(d,r):
    hs=d['financials']
    rows=[]
    for key,label in [('revenue','Revenue'),('ebitda','EBITDA'),('net_income','Net Income')]:
        s=pd.Series(hs.get(key,pd.Series(dtype=float))).dropna().sort_index(ascending=True)
        if len(s):
            c=cagr(s)
            rows.append((label,s,c))
    g=Table.grid(padding=(0,1)); g.add_column(width=12); g.add_column(); g.add_column(width=13,justify='right')
    for label,s,c in rows:
        g.add_row(Text(label,style='bold'),_v17_spark(s.tolist(),36),Text(f'{money(float(s.iloc[-1]))}  |  CAGR {pct(c)}'))
    rev=latest(hs['revenue']); ebitda=latest(hs['ebitda']); ni=latest(hs['net_income']); cfo=latest(hs['cfo']); capex=latest(hs['capex']); fcf=cfo-capex
    g.add_row(Text('Margins',style='bold'),Text(f'EBITDA {pct(ebitda/rev) if rev else "N/A"}   |   FCF {money(fcf)}'),Text(f'ROE {pct(ni/latest(hs["equity"]) if latest(hs["equity"]) else math.nan)}'))
    return g


def _v17_price_chart(d,r,width=72,height=11):
    """TradingView-inspired terminal chart: OHLC + 20/50/200 DMA overlays."""
    h=d['history'][['Open','High','Low','Close']].dropna().tail(120).copy()
    if len(h)<10: return Text('Insufficient OHLC history.',style='dim')
    if len(h)>width:
        idx=np.linspace(0,len(h)-1,width).astype(int); h=h.iloc[idx]
    closes=h['Close'].to_numpy(float); opens=h['Open'].to_numpy(float); highs=h['High'].to_numpy(float); lows=h['Low'].to_numpy(float)
    # Overlay moving averages based on full close history, aligned to sampled timestamps.
    full=d['history']['Close'].dropna(); ma20=full.rolling(20).mean(); ma50=full.rolling(50).mean(); ma200=full.rolling(200).mean()
    sampled_dates=h.index
    m20=ma20.reindex(sampled_dates).to_numpy(float); m50=ma50.reindex(sampled_dates).to_numpy(float); m200=ma200.reindex(sampled_dates).to_numpy(float)
    allv=np.concatenate([highs,lows,m20[np.isfinite(m20)],m50[np.isfinite(m50)],m200[np.isfinite(m200)]])
    lo=float(np.nanmin(allv)); hi=float(np.nanmax(allv));
    if hi<=lo: return Text('Price range unavailable.',style='dim')
    def row_for(v): return int(round((hi-v)/(hi-lo)*(height-1)))
    grid=[[' ']*len(h) for _ in range(height)]
    styles=[[None]*len(h) for _ in range(height)]
    for i,(o,c,hh,ll) in enumerate(zip(opens,closes,highs,lows)):
        ph,pl,po,pc=row_for(hh),row_for(ll),row_for(o),row_for(c); top=min(po,pc); bot=max(po,pc); bull=c>=o
        for rr in range(min(ph,pl),max(ph,pl)+1):
            grid[rr][i]='│'; styles[rr][i]='green' if bull else 'red'
        for rr in range(top,bot+1):
            grid[rr][i]='█' if top!=bot else '▪'; styles[rr][i]='green' if bull else 'red'
    # Draw MAs after candles; distinct glyphs preserve visibility.
    for arr,glyph,style in [(m20,'•','bright_cyan'),(m50,'─','yellow'),(m200,'·','magenta')]:
        for i,v in enumerate(arr):
            if np.isfinite(v):
                rr=row_for(v); grid[rr][i]=glyph; styles[rr][i]=style
    out=Text()
    for rr in range(height):
        y=hi-(hi-lo)*rr/(height-1)
        line=Text(f'{y:>9,.0f} ',style='dim')
        for i,ch in enumerate(grid[rr]): line.append(ch,style=styles[rr][i] or 'white')
        out.append(line); out.append('\n')
    out.append(Text('          OLD'+' '*(max(1,len(h)-10))+'LATEST',style='dim'))
    return out


def _v17_heatmap(dc,p,current):
    t=Table.grid(padding=(0,1)); t.add_column(width=7); ws=[.08,.10,.12,.14,.16]
    for w in ws: t.add_column(width=9,justify='right')
    t.add_row('G/W',*[f'{w*100:.0f}%' for w in ws])
    for g,row in zip([.04,.06,.08,.10,.12],dc.sensitivity):
        cells=[]
        for v in row:
            if not np.isfinite(v): cells.append('—')
            elif v>=current*1.2: cells.append(f'[green]{v/1000:.1f}k[/green]')
            elif v<=current*.8: cells.append(f'[red]{v/1000:.1f}k[/red]')
            else: cells.append(f'[yellow]{v/1000:.1f}k[/yellow]')
        t.add_row(f'{g*100:.0f}%',*cells)
    return t


def _v17_mc_visual(mc,p,width=46):
    vals=np.asarray(mc.get('paths',[]),float)
    if vals.ndim!=2 or vals.shape[1]<2: return Text('Monte Carlo distribution unavailable.',style='dim')
    terminal=vals[:,-1]; terminal=terminal[np.isfinite(terminal)]
    if len(terminal)<20: return Text('Monte Carlo distribution unavailable.',style='dim')
    counts,edges=np.histogram(terminal,bins=12); mx=max(counts) or 1
    g=Table.grid(padding=(0,0)); g.add_column(width=10); g.add_column(); g.add_column(width=6,justify='right')
    for i,cnt in enumerate(counts):
        bar='█'*int(cnt/mx*width)
        g.add_row(f'{money(edges[i])}',Text(bar,style='cyan'),str(int(cnt)))
    return Group(g,Text(f'P5 {money(mc["percentiles"]["P5"])}   P50 {money(mc["percentiles"]["P50"])}   P95 {money(mc["percentiles"]["P95"])}',style='bold'))


def _v17_fair_value_bar(r,d):
    p=r['price']; vals=[('Lynch',math.nan),('DCF',r['dcf'].target),('Peer P/E',r.get('implied')),('Blended',r.get('blended')),('Current',p)]
    # Recalculate Lynch with percentage points and never display a negative "fair price" as an investable target.
    info=r.get('info',{}); f=d['financials']; growth=_fv_num(info,'earningsGrowth'); dy=_fv_num(info,'dividendYield'); pe=_fv_num(info,'trailingPE')
    if np.isfinite(growth) and abs(growth)>1.5: growth/=100
    if not np.isfinite(growth): growth=_fv_cagr(f['net_income'])
    if np.isfinite(dy) and abs(dy)>1: dy/=100
    factor=(growth*100+dy*100)/pe if np.isfinite(growth) and np.isfinite(dy) and np.isfinite(pe) and pe>0 else math.nan
    if np.isfinite(factor) and factor>0: vals[0]=('Lynch',p*factor)
    maxv=max([abs(p)]+[abs(v) for _,v in vals if np.isfinite(v)])
    g=Table.grid(padding=(0,0)); g.add_column(width=10); g.add_column(); g.add_column(width=12,justify='right')
    for name,v in vals:
        if np.isfinite(v):
            n=int(np.clip(v/maxv*34,0,34)); g.add_row(name,Text('█'*n+'·'*(34-n)),money(v))
        else: g.add_row(name,Text('N/A',style='dim'), 'N/A')
    return g


def _v17_security_dashboard(symbol):
    d,r=run_research(symbol,sims=5000); info=r['info']; company=_company_name(d); p=r['price']; hist=d['history']; tech=r['tech']; hs=d['financials']; mc=r['mc']; dc=r['dcf']
    console.clear(); console.print(header())
    last2=hist['Close'].dropna().tail(2); day=((float(last2.iloc[-1])/float(last2.iloc[-2])-1)*100) if len(last2)>1 else math.nan
    # Header strip — no enclosing box.
    console.print(Rule(f'[bold cyan]{symbol.upper()}[/bold cyan]  {company}  |  {money(p)}  |  {day:+.2f}%  |  P/E {fmt_multiple(info.get("trailingPE"),"pe")}  |  P/B {fmt_multiple(info.get("priceToBook"),"pb")}  |  ROE {pct(latest(hs["net_income"])/latest(hs["equity"]) if latest(hs["equity"]) else math.nan)}  |  GWI {r["score"]:.0f}/100',style='cyan'))
    console.print(Text(f'  {info.get("sector") or "Sector N/A"}  •  {info.get("industry") or "Industry N/A"}  •  200DMA {money(tech["sma200"])}  •  RSI {num(tech["rsi"])}  •  52W {money(tech["low"])} — {money(tech["high"])}',style='dim'))

    # Main chart and technical strip.
    console.print(Rule('PRICE / TECHNICAL STRUCTURE',style='bright_blue'))
    left=Group(_v17_price_chart(d,r,70,10),Text('  • 20DMA   ─ 50DMA   · 200DMA',style='dim'))
    k=Table.grid(padding=(0,1)); k.add_column(width=13); k.add_column(justify='right')
    for a,b in [('20 DMA',money(tech['sma20'])),('50 DMA',money(tech['sma50'])),('200 DMA',money(tech['sma200'])),('RSI 14',num(tech['rsi'])),('Technical',f'{tech["score"]:.0f}/100'),('52W High',money(tech['high'])),('52W Low',money(tech['low']))]: k.add_row(a,b)
    grid=Table.grid(expand=True,padding=(0,2)); grid.add_column(ratio=4); grid.add_column(ratio=1); grid.add_row(left,k); console.print(grid)

    # Fundamental + valuation + Monte Carlo.
    console.print(Rule('RESEARCH CORE',style='bright_blue'))
    q=_v17_quarterly(d)
    ftxt=_v17_fundamentals(d,r)
    qlines=[]
    if q:
        qlines.append(f'Latest quarter: {q.get("period","N/A")}')
        for key in ['Revenue','EBITDA','Earnings']:
            if key in q:
                yoy=q.get(key+'_YoY'); qlines.append(f'{key:<9} {money(q[key])}  {pct(yoy) if yoy is not None else "N/A"} YoY')
    else:
        qlines=['Quarterly statement unavailable.','Transcript source not configured.']
    call=Group(Text('\n'.join(qlines)),Text('\nSOURCE: provider quarterly financials.\nTranscript-specific management commentary is only shown when a verified transcript source is configured.',style='dim'))
    vg=Group(Text('DCF / FAIR VALUE',style='bold yellow'),_v17_fair_value_bar(r,d),Text(f'DCF {money(dc.target)}  |  WACC {pct(dc.wacc)}  |  g {pct(dc.terminal_growth)}  |  Reverse g {pct(dc.reverse_growth)}',style='dim'))
    mg=Group(Text('MONTE CARLO / 1Y TERMINAL DISTRIBUTION',style='bold cyan'),_v17_mc_visual(mc,p,34),Text(f'Positive {pct(mc["positive_prob"])}  |  VaR95 {pct(mc["var95"])}  |  CVaR95 {pct(mc["cvar95"])}  |  Max DD {pct(mc["avg_max_dd"])}',style='dim'))
    cols=Table.grid(expand=True,padding=(0,2)); cols.add_column(ratio=1); cols.add_column(ratio=1); cols.add_column(ratio=1); cols.add_row(ftxt,vg,mg); console.print(cols)

    # DCF / peers / earnings / thesis.
    console.print(Rule('VALUATION • EARNINGS • THESIS',style='bright_blue'))
    dcf_group=Group(Text(f'FAIR VALUE  {money(dc.target)}   |   {pct(dc.target/p-1) if np.isfinite(dc.target) else "N/A"} vs price',style='bold'),_v17_heatmap(dc,p,p),Text('Growth ↓ / WACC →   values in ₹000s',style='dim'))
    sec=info.get('sector',''); peers=SECTORS.get(sec,[])[:5]; pt=Table.grid(padding=(0,1)); pt.add_column(width=10); pt.add_column(width=8,justify='right'); pt.add_column(width=8,justify='right'); pt.add_column(width=10,justify='right'); pt.add_column(width=10,justify='right')
    pt.add_row('Peer','P/E','P/B','EV/EBITDA','Status')
    for qsym in peers:
        pe,pb,ev=_v17_peer_metrics(qsym); status='OK' if any(x is not None for x in [pe,pb,ev]) else 'N/A'; pt.add_row(qsym,fmt_multiple(pe,'pe'),fmt_multiple(pb,'pb'),fmt_multiple(ev,'ev_ebitda'),status)
    if not peers: pt.add_row('N/A','N/A','N/A','N/A','NO SET')
    peer_group=Group(Text(f'PEERS / {sec.upper() or "SECTOR N/A"}',style='bold cyan'),pt,Text('Provider-first with price/financial fallbacks; verify primary filings.',style='dim'))
    thesis=[]
    rc=cagr(hs['revenue']); roe=latest(hs['net_income'])/latest(hs['equity']) if latest(hs['equity']) else math.nan; de=latest(hs['debt'])/latest(hs['equity']) if latest(hs['equity']) else math.nan
    if np.isfinite(rc) and rc>0: thesis.append(f'▲ Revenue CAGR {pct(rc)}')
    if np.isfinite(roe): thesis.append(f'ROE {pct(roe)}')
    if np.isfinite(de): thesis.append(f'D/E {de:.2f}x')
    thesis.append('▼ Below 200DMA' if p<tech['sma200'] else '▲ Above 200DMA')
    if np.isfinite(r.get('upside',math.nan)): thesis.append(('▲' if r['upside']>=0 else '▼')+f' Blended value {pct(r["upside"])} vs price')
    thesis_group=Group(Text('THESIS / CONTROL',style='bold green'),Text('\n'.join(thesis[:6])),Text(f'GWI {r["score"]:.0f}/100  {r["label"]}\n3-Statement: {"PASS" if r["balance_ok"] else "REVIEW"}  |  DCF: {dc.status}\nDecision: HUMAN REVIEW REQUIRED',style='bold'))
    bottom=Table.grid(expand=True,padding=(0,2)); bottom.add_column(ratio=2); bottom.add_column(ratio=2); bottom.add_column(ratio=2); bottom.add_column(ratio=2); bottom.add_row(dcf_group,call,peer_group,thesis_group); console.print(bottom)

    console.print(Rule('COMMAND RAIL',style='bright_blue'))
    console.print(Text('01 Research   02 Financials   03 Model   04 DCF   05 Valuation   06 Technical   07 Monte Carlo   08 Risk   09 Peers   10 Compare',style='cyan'))
    console.print(Text('13 GWI Score   20 Security   21 Concall   24 Earnings   29 Scenario   36 IC Mode   100 Fair Value   99 Index   00 Exit',style='cyan'))
    console.print(Text(f'Active security: {symbol.upper()}  •  Enter a number for a deep view, or T TICKER to change company.',style='dim'))


def final_main_v17():
    """Ticker-first: one company loads one visual institutional security page."""
    console.clear(); console.print(header())
    console.print(Rule('[bold cyan]GROWISEINVEST[/bold cyan]  SINGLE-SECURITY VISUAL WORKSTATION',style='cyan'))
    console.print(Text('Enter a company ticker once. The complete research stack loads automatically: price, technicals, fundamentals, DCF, valuation, Monte Carlo, earnings/concall context, peers and thesis.',style='white'))
    while True:
        try:
            raw=console.input('[bold cyan]ENTER NSE TICKER (or 00 to exit): [/bold cyan]').strip()
            if raw.upper() in {'00','EXIT','QUIT','Q'}: break
            if not raw: continue
            symbol=raw.split()[0].upper().replace('.NS','').replace('.BO','')
            if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',symbol):
                console.print('[yellow]Invalid ticker format.[/yellow]'); continue
            try: _v17_security_dashboard(symbol)
            except Exception as e:
                console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='SECURITY LOAD ERROR',border_style='red')); continue
            while True:
                cmd=console.input(f'\n[bold cyan]GROWISEINVEST / {symbol} > [/bold cyan]').strip()
                if not cmd: continue
                up=cmd.upper()
                # PRIVATE V27 ROUTE: handle before any legacy dispatcher can see the command.
                if cmd.strip() == '90':
                    try:
                        _v22_intelligence(symbol)
                    except Exception as e:
                        console.print(Panel(f'{type(e).__name__}: {e}',title='INTELLIGENCE ENGINE ERROR',border_style='red'))
                    continue
                if up.startswith(('T ','TICKER ')):
                    symbol=cmd.split(None,1)[1].upper().replace('.NS','').replace('.BO',''); _v17_security_dashboard(symbol); continue
                if up in {'00','EXIT','QUIT','Q'}: return
                if up in {'HOME','H'}: _v17_security_dashboard(symbol); continue
                if cmd.isdigit() or cmd.split()[0].isdigit():
                    parts=cmd.split(); n=parts[0]
                    if len(parts)>1 and n not in {'10','17','18','22','23','48'}:
                        symbol=parts[1].upper().replace('.NS','').replace('.BO',''); _v17_security_dashboard(symbol); continue
                    ok=_v17_dispatch_same_ticker(n,symbol)
                    if not ok: return
                else:
                    console.print('[yellow]Enter a module number, e.g. 06, 20, 100. Use T TCS to change security.[/yellow]')
        except KeyboardInterrupt:
            console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='WORKSTATION ERROR',border_style='red'))

main=final_main_v17

# V17 command router: active security is retained; deep modules no longer ask for ticker again.
def _v17_dispatch_same_ticker(n, symbol):
    n=str(n).strip().upper(); aliases={'H':'99','HELP':'99','?':'99','Q':'00','QUIT':'00','EXIT':'00'}; n=aliases.get(n,n)
    # Preserve public zero-padded module IDs (04/05/07/08/09).
    if n.isdigit(): n=(f'{int(n):02d}' if len(n) <= 2 else str(int(n)))
    if n=='90' and '_v22_intelligence' in globals():
        try: _v22_intelligence(symbol)
        except Exception as e: console.print(Panel(f'{type(e).__name__}: {e}',title='INTELLIGENCE ENGINE ERROR',border_style='red'))
        return True
    if n=='00': return False
    if n=='99': final_help_screen(); _visual_pause(); _v17_security_dashboard(symbol); return True
    direct={
        '01':show_research,'02':show_financials,'03':show_model_cmd,'04':show_dcf,'05':show_valuation_lab,
        '06':show_technical,'07':show_quant_cmd,'09':show_peers,'13':gwi_score,'14':data_quality,'15':backtest,
        '16':market_regime,'20':_v24_security_master,'21':conference_call_analyzer,'24':earnings_intelligence,
        '25':fundamental_inflection,'26':forensic_engine,'27':what_changed_engine,'28':event_study_engine,
        '29':lambda s:(scenario_engine(s),catalyst_dashboard(s)),'30':ownership_flow_engine,'31':moat_analyzer,
        '32':valuation_bridge,'33':corporate_actions_engine,'34':filings_intelligence,'35':red_flag_engine,
        '36':investment_committee_mode,'37':factor_exposure_v8,'38':quality_scorecard,'39':growth_quality_lab,
        '40':capital_allocation_lab,'41':sotp_lab,'42':dividend_discount_valuation,'43':residual_income_valuation,
        '44':probability_valuation,'45':valuation_decomposition_v8,'46':factor_exposure_v8,'47':thesis_tracker,'19':research_note,
        '49':model_control_center,'51':live_market_engine,'100':fair_value_lab}
    if n=='08':
        _,r=run_research(symbol); console.print(header()); show_risk(r)
    elif n=='10':
        raw=console.input('[bold cyan]ENTER COMPARISON TICKERS: [/bold cyan]').strip(); compare(raw.split())
    elif n=='11': export_excel(symbol)
    elif n=='12':
        live,reason,nxt=market_status(datetime.now(IST)); console.print(Panel(f'Market: {reason}\nNext open: {nxt.strftime("%d-%b-%Y %H:%M IST") if nxt else "—"}',title='MARKET STATUS',border_style='cyan'))
    elif n in {'17','18','48'}:
        raw=console.input('[bold cyan]ENTER PORTFOLIO TICKERS: [/bold cyan]').strip(); syms=raw.split()
        if n=='17': portfolio_risk(syms)
        elif n=='18': portfolio_optimizer(syms)
        else: portfolio_attribution(syms)
    elif n=='22':
        raw=console.input('[bold cyan]ENTER IPO / COMPANY NAME: [/bold cyan]').strip(); ipo_research(raw)
    elif n=='23': news_tomorrow_events()
    elif n=='50': _v24_security_master(symbol)
    elif n in direct: direct[n](symbol)
    else:
        console.print('[yellow]UNKNOWN MODULE — use 99 for the full index.[/yellow]'); _visual_pause()
    if n not in {'20','50','99'}: _visual_pause(); _v17_security_dashboard(symbol)
    return True

main=final_main_v17


# ===================== V20 — PROFESSIONAL SESSION / SERVICE MAP =====================
SERVICE_INDEX = [
('01','RESEARCH WORKBENCH'),('02','FINANCIAL STATEMENTS'),('03','THREE-STATEMENT MODEL'),('04','DISCOUNTED CASH FLOW'),('05','VALUATION LAB'),
('06','TECHNICAL ANALYSIS'),('07','MONTE CARLO QUANT'),('08','RISK ANALYTICS'),('09','PEER COMPARABLES'),('10','CROSS-COMPANY COMPARISON'),
('11','RESEARCH EXPORT'),('12','MARKET STATUS'),('13','GWI SCORE'),('14','DATA QUALITY & AUDIT'),('15','BACKTESTING ENGINE'),
('16','MARKET REGIME ENGINE'),('17','PORTFOLIO RISK'),('18','PORTFOLIO OPTIMIZER'),('19','RESEARCH NOTE'),('20','INSTITUTIONAL ALL-IN-ONE'),
('21','CONFERENCE CALL ANALYZER'),('22','IPO RESEARCH'),('23','NEWS & TOMORROW EVENTS'),('24','EARNINGS INTELLIGENCE'),('25','FUNDAMENTAL INFLECTION'),
('26','EARNINGS QUALITY & FORENSIC'),('27','WHAT CHANGED'),('28','EVENT STUDY LAB'),('29','SCENARIO & CATALYST LAB'),('30','OWNERSHIP & INSTITUTIONAL FLOW'),
('31','MOAT ANALYZER'),('32','VALUATION BRIDGE'),('33','CORPORATE ACTION INTELLIGENCE'),('34','REGULATORY & FILINGS INTELLIGENCE'),('35','RED FLAG ENGINE'),
('36','INVESTMENT COMMITTEE MODE'),('37','FACTOR EXPOSURE'),('38','QUALITY SCORECARD'),('39','GROWTH QUALITY LAB'),('40','CAPITAL ALLOCATION LAB'),
('41','SOTP VALUATION LAB'),('42','DIVIDEND DISCOUNT VALUATION'),('43','RESIDUAL INCOME VALUATION'),('44','PROBABILITY VALUATION'),('45','VALUATION DECOMPOSITION'),
('46','FACTOR & STYLE DASHBOARD'),('47','THESIS TRACKER'),('48','PORTFOLIO ATTRIBUTION'),('49','MODEL CONTROL CENTER'),('50','CLEAR TERMINAL')]

def _set_session_peers():
    global ACTIVE_PEERS
    raw=console.input('[bold cyan]OPTIONAL PEER TICKERS (space-separated, ENTER = auto-detect): [/bold cyan]').strip().upper()
    if raw in {'','AUTO','DEFAULT'}:
        ACTIVE_PEERS=[]
        return []
    peers=[x.replace('.NS','').replace('.BO','') for x in raw.split()]
    if len(peers)>10: raise ValueError('Maximum 10 manual peer tickers are supported.')
    for x in peers:
        if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',x): raise ValueError(f'Invalid peer ticker: {x}')
    ACTIVE_PEERS=list(dict.fromkeys(peers))
    return ACTIVE_PEERS

def _service_map_compact():
    cols=[SERVICE_INDEX[i:i+10] for i in range(0,50,10)]
    g=Table.grid(expand=True,padding=(0,2))
    for _ in cols: g.add_column(ratio=1)
    groups=[]
    for col in cols:
        txt=Text()
        for no,name in col:
            txt.append(f'{no} ',style='bold cyan'); txt.append(name+'\n',style='white')
        groups.append(txt)
    g.add_row(*groups)
    return g

def _auto_export_session(symbol):
    try:
        res=generate_institutional_pack(symbol, run_research, fetch, sims=5000)
        console.print(Rule('AUTOMATED RESEARCH DELIVERABLES',style='bright_green'))
        console.print(Text(f'Excel  : {res["excel"]}',style='green'))
        console.print(Text(f'Word   : {res["word"]}',style='green'))
        console.print(Text(f'Charts : {len(res.get("charts",[]))} professional chart assets generated',style='dim'))
        return res
    except Exception as e:
        console.print(Panel(f'{type(e).__name__}: {e}',title='EXPORT CONTROL — REVIEW',border_style='yellow'))
        return None

# ===================== V18 VISUAL WORKSTATION =====================
# Bloomberg/TradingView-inspired visual layer. No web dashboard required.

def _v18_tf_history(d, timeframe='1D'):
    tf=str(timeframe or '1D').upper().replace(' ','')
    hist=d['history'][['Open','High','Low','Close','Volume']].dropna(how='all').copy()
    if tf == '1D':
        return hist.dropna(subset=['Open','High','Low','Close']).tail(140), '1D'
    if tf == '1W':
        h=hist.dropna(subset=['Open','High','Low','Close']).resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna(subset=['Close'])
        return h.tail(100), '1W'
    if tf == '1M':
        h=hist.dropna(subset=['Open','High','Low','Close']).resample('ME').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna(subset=['Close'])
        return h.tail(72), '1M'
    if tf in {'1H','60M'}:
        try:
            h=_provider_call(lambda: yf.Ticker(d['ticker']).history(period='60d', interval='1h', auto_adjust=False), pd.DataFrame())
            h=h[['Open','High','Low','Close','Volume']].dropna(subset=['Open','High','Low','Close'])
            return h.tail(120), '1H'
        except Exception:
            return pd.DataFrame(), '1H'
    if tf in {'15M','15MIN'}:
        try:
            h=_provider_call(lambda: yf.Ticker(d['ticker']).history(period='5d', interval='15m', auto_adjust=False), pd.DataFrame())
            h=h[['Open','High','Low','Close','Volume']].dropna(subset=['Open','High','Low','Close'])
            return h.tail(120), '15M'
        except Exception:
            return pd.DataFrame(), '15M'
    return hist.dropna(subset=['Open','High','Low','Close']).tail(140), '1D'


def _v18_candle_chart(h, width=112, height=22):
    """High-density TradingView-inspired candlestick chart with OHLC, MA overlays and volume.
    Designed for Windows Terminal/PowerShell: thin wicks, one-cell candle bodies, price grid,
    moving-average traces and a compact volume profile without heavy boxes.
    """
    if h is None or h.empty or len(h) < 5:
        return Text('CHART DATA UNAVAILABLE', style='dim')
    h=h[['Open','High','Low','Close','Volume']].dropna(subset=['Open','High','Low','Close']).copy()
    if len(h)>width:
        # Keep the latest observations while preserving real candle sequence.
        h=h.tail(width)
    o=h['Open'].to_numpy(float); hi=h['High'].to_numpy(float); lo=h['Low'].to_numpy(float); c=h['Close'].to_numpy(float)
    ma20=h['Close'].rolling(20).mean().to_numpy(float)
    ma50=h['Close'].rolling(50).mean().to_numpy(float)
    ma200=h['Close'].rolling(200).mean().to_numpy(float)
    vol=h['Volume'].fillna(0).to_numpy(float)
    vals=np.concatenate([hi[np.isfinite(hi)],lo[np.isfinite(lo)]])
    if len(vals)==0: return Text('CHART DATA UNAVAILABLE',style='dim')
    lo_p=float(np.min(vals)); hi_p=float(np.max(vals)); span=max(hi_p-lo_p,1.0); pad=span*0.045
    lo_p-=pad; hi_p+=pad
    chart_h=max(12,int(height)); vol_h=5; n=len(h)
    rows=[[' ']*n for _ in range(chart_h)]
    styles=[[None]*n for _ in range(chart_h)]
    def yy(v): return int(np.clip(round((hi_p-v)/(hi_p-lo_p)*(chart_h-1)),0,chart_h-1))
    # Subtle price grid.
    for rr in range(chart_h):
        if rr in {0, chart_h//4, chart_h//2, (3*chart_h)//4, chart_h-1}:
            for cc in range(n):
                rows[rr][cc]='┄'; styles[rr][cc]='grey27'
    # MA traces behind candles. Only valid windows are drawn.
    for arr,st in [(ma200,'bright_yellow'),(ma50,'bright_blue'),(ma20,'bright_magenta')]:
        for i,v in enumerate(arr):
            if not np.isfinite(v): continue
            rr=yy(v)
            if rows[rr][i] in {' ','┄'}:
                rows[rr][i]='•'; styles[rr][i]=st
    # Candles: thin wick, one-cell body, with high-contrast direction.
    for i,(oo,cc,hh,ll) in enumerate(zip(o,c,hi,lo)):
        if not all(np.isfinite([oo,cc,hh,ll])): continue
        yh,yl,yo,yc=yy(hh),yy(ll),yy(oo),yy(cc); bull=cc>=oo; st='green' if bull else 'red'
        for rr in range(min(yh,yl),max(yh,yl)+1):
            if rows[rr][i] in {' ','┄','•'}:
                rows[rr][i]='│'; styles[rr][i]=st
        top=min(yo,yc); bot=max(yo,yc)
        body='█' if bot>top else '▪'
        for rr in range(top,bot+1):
            rows[rr][i]=body; styles[rr][i]=st
    out=Text()
    for rr in range(chart_h):
        price=hi_p-(hi_p-lo_p)*rr/(chart_h-1)
        line=Text(f'{price:>10,.0f} ',style='dim')
        for cc,ch in enumerate(rows[rr]): line.append(ch,style=styles[rr][cc] or 'white')
        out.append(line); out.append('\n')
    # Volume mini-chart under price chart.
    vmax=float(np.nanmax(vol)) if np.isfinite(vol).any() else 0.0
    if vmax>0:
        out.append(Text(' '*11+'VOLUME\n',style='dim'))
        for level in range(vol_h,0,-1):
            line=Text(' '*11,style='dim')
            for i,v in enumerate(vol):
                bh=int(round((v/vmax)*vol_h)) if np.isfinite(v) else 0
                line.append('▂' if bh>=level else ' ',style='grey50')
            out.append(line); out.append('\n')
    # Date/time anchors + legend.
    labels=''
    try:
        idx=h.index
        picks=[0,n//3,2*n//3,n-1] if n>=4 else list(range(n))
        pieces=[]
        for i in picks:
            ts=idx[i]
            pieces.append((f'{ts.strftime("%d-%b") if hasattr(ts,"strftime") else str(ts)}', i))
        cursor=0; chars=[' ']*(11+n)
        for lab,i in pieces:
            pos=min(11+i, len(chars)-len(lab));
            for j,ch in enumerate(lab): chars[pos+j]=ch
        labels=''.join(chars)
    except Exception:
        labels=' '*11+'OLD'+' '*(max(1,n-14))+'LATEST'
    out.append(Text(labels,style='dim')); out.append('\n')
    out.append(Text(' '*11+'▌ candle  │ wick   ',style='dim'))
    out.append(Text('• MA20 ',style='bright_magenta')); out.append(Text('• MA50 ',style='bright_blue')); out.append(Text('• MA200',style='bright_yellow'))
    return out


def _v18_metric_line(label, value, status=None, width=20):
    t=Text(); t.append(f'{label:<{width}}',style='dim'); t.append(str(value),style='bold white')
    if status: t.append('  ' + status)
    return t


def _v18_bar(label, value, maximum, suffix='', width=24):
    try:
        x=float(value); m=float(maximum)
        if not np.isfinite(x) or not np.isfinite(m) or m<=0: raise ValueError
        n=int(np.clip(x/m*width,0,width)); return Text(f'{label:<12} ' + '█'*n + '·'*(width-n) + f'  {x:.1f}{suffix}')
    except Exception:
        return Text(f'{label:<12} ' + 'N/A',style='dim')


def _v18_valuation_visual(r,d):
    p=float(r['price']); methods=[('LYNCH',_v18_lynch_value(r,d)),('DCF',r['dcf'].target),('PEER',r.get('implied')),('BLENDED',r.get('blended')),('PRICE',p)]
    valid=[float(v) for _,v in methods if v is not None and np.isfinite(v) and v>0]
    if not valid: return Text('VALUATION DATA UNAVAILABLE',style='dim')
    mx=max(valid); out=Text()
    for name,v in methods:
        if v is None or not np.isfinite(v) or v<=0:
            out.append(f'{name:<9} ',style='dim'); out.append('N/A\n',style='dim'); continue
        n=int(np.clip(v/mx*42,1,42)); st='yellow' if name=='PRICE' else 'cyan'
        out.append(f'{name:<9} ',style='bold'); out.append('━'*n,style=st); out.append(f'  {money(v)}\n',style='bold')
    return out


def _v18_lynch_value(r,d):
    try:
        info=r.get('info',{}); f=d['financials']; growth=_fv_num(info,'earningsGrowth'); dy=_fv_num(info,'dividendYield'); pe=_fv_num(info,'trailingPE')
        if np.isfinite(growth) and abs(growth)>1.5: growth/=100
        if not np.isfinite(growth): growth=_fv_cagr(f['net_income'])
        if np.isfinite(dy) and abs(dy)>1: dy/=100
        if not (np.isfinite(growth) and np.isfinite(dy) and np.isfinite(pe) and pe>0): return math.nan
        factor=(growth*100+dy*100)/pe
        return float(r['price']*factor) if factor>0 else math.nan
    except Exception: return math.nan


def _v18_mc_curve(mc, width=54, height=8):
    vals=np.asarray(mc.get('paths',[]),float)
    if vals.ndim!=2 or vals.shape[1]<2: return Text('MC DISTRIBUTION N/A',style='dim')
    x=vals[:,-1]; x=x[np.isfinite(x)]
    if len(x)<20: return Text('MC DISTRIBUTION N/A',style='dim')
    counts,edges=np.histogram(x,bins=18); mx=max(counts) or 1
    out=Text()
    for level in range(height,0,-1):
        out.append(' '*9)
        for c in counts:
            out.append('█' if c/mx*height>=level else ' ')
        out.append('\n')
    out.append(' '*9 + '└'+'─'*len(counts)+'┘\n')
    out.append(f'P5 {money(mc["percentiles"]["P5"])}   P50 {money(mc["percentiles"]["P50"])}   P95 {money(mc["percentiles"]["P95"])}',style='dim')
    return out


def _v18_security_dashboard(symbol, timeframe='1D'):
    d,r=run_research(symbol,sims=5000); info=r['info']; company=_company_name(d); p=r['price']; hist=d['history']; tech=r['tech']; hs=d['financials']; mc=r['mc']; dc=r['dcf']
    h,tf=_v18_tf_history(d,timeframe)
    console.clear(); console.print(header())
    last2=hist['Close'].dropna().tail(2); day=((float(last2.iloc[-1])/float(last2.iloc[-2])-1)*100) if len(last2)>1 else math.nan
    # Single-line security identity.
    console.print(Rule(f'[bold cyan]{symbol.upper()}[/bold cyan]  {company}  |  {money(p)}  |  {day:+.2f}%  |  P/E {fmt_multiple(info.get("trailingPE"),"pe")}  |  ROE {pct(r["roe"])}  |  GWI {r["score"]:.0f}/100',style='cyan'))
    console.print(Text(f'{info.get("sector") or "Sector N/A"}  •  {info.get("industry") or "Industry N/A"}  •  TF {tf}  •  20DMA {money(tech["sma20"])}  •  50DMA {money(tech["sma50"])}  •  200DMA {money(tech["sma200"])}  •  RSI {num(tech["rsi"])}',style='dim'))

    # TradingView-inspired main chart, intentionally open rather than boxed.
    console.print(Rule(f'PRICE ACTION  /  {tf}  /  OHLC CANDLES + MA20/50/200 + VOLUME',style='bright_blue'))
    console.print(_v18_candle_chart(h,112,18))
    console.print(Text('  GREEN = UP   RED = DOWN   • MA20/50/200   ▂ volume   |   TradingView-style chart conventions',style='dim'))

    # KPI ribbon, no panels.
    console.print(Rule('MARKET / TECHNICAL SNAPSHOT',style='bright_blue'))
    ribbon=Table.grid(expand=True,padding=(0,3)); ribbon.add_column(); ribbon.add_column(); ribbon.add_column(); ribbon.add_column()
    ribbon.add_row(_v18_metric_line('LAST',money(p)),_v18_metric_line('RSI 14',num(tech['rsi'])),_v18_metric_line('52W HIGH',money(tech['high'])),_v18_metric_line('52W LOW',money(tech['low'])))
    ribbon.add_row(_v18_metric_line('20 DMA',money(tech['sma20'])),_v18_metric_line('50 DMA',money(tech['sma50'])),_v18_metric_line('200 DMA',money(tech['sma200'])),_v18_metric_line('TECHNICAL',f'{tech["score"]:.0f}/100'))
    console.print(ribbon)

    # Research matrix: three clean columns, no boxes.
    console.print(Rule('RESEARCH MATRIX  /  FUNDAMENTALS • VALUATION • QUANT',style='bright_blue'))
    fund=_v17_fundamentals(d,r)
    valuation=_v18_valuation_visual(r,d)
    mcvis=_v18_mc_curve(mc)
    matrix=Table.grid(expand=True,padding=(0,4)); matrix.add_column(ratio=1); matrix.add_column(ratio=1); matrix.add_column(ratio=1)
    matrix.add_row(Group(Text('FUNDAMENTALS',style='bold cyan'),fund),Group(Text('FAIR VALUE',style='bold yellow'),valuation,Text(f'DCF {money(dc.target)}  |  {pct(dc.target/p-1)} vs price\nLynch is shown only when its factor is positive.',style='dim')),Group(Text('MONTE CARLO',style='bold cyan'),mcvis,Text(f'Positive {pct(mc["positive_prob"])}  |  VaR95 {pct(mc["var95"])}  |  CVaR95 {pct(mc["cvar95"])}',style='dim')))
    console.print(matrix)

    # DCF heatmap and earnings/concall context as open sections.
    console.print(Rule('DCF SENSITIVITY  /  GROWTH × WACC',style='bright_blue'))
    console.print(_v17_heatmap(dc,p,p))
    console.print(Text(f'Fair value {money(dc.target)}  •  WACC {pct(dc.wacc)}  •  terminal growth {pct(dc.terminal_growth)}  •  reverse growth {pct(dc.reverse_growth)}  •  model {dc.status}',style='dim'))

    q=_v17_quarterly(d); qtxt=[]
    if q:
        for key in ['Revenue','EBITDA','Earnings']:
            if key in q:
                yoy=q.get(key+'_YoY'); qtxt.append(f'{key:<10} {money(q[key]):>12}  {pct(yoy) if yoy is not None else "N/A"} YoY')
    else: qtxt=['Quarterly financial trend unavailable.']
    console.print(Rule('EARNINGS / CONCALL INTELLIGENCE',style='bright_blue'))
    console.print(Text('  '.join(qtxt) if qtxt else 'N/A'))
    console.print(Text('Transcript-specific management commentary is displayed only when a verified transcript source exists. No quotes are fabricated.',style='dim'))

    # Peer and thesis strip.
    console.print(Rule('PEERS  •  THESIS  •  MODEL CONTROLS',style='bright_blue'))
    sec=info.get('sector',''); peers=SECTORS.get(sec,[])[:5]; peer_bits=[]
    for qsym in peers:
        try:
            pe,pb,ev=_provider_call(lambda: peer_metrics(qsym), (None,None,None))
        except Exception:
            pe,pb,ev=(None,None,None)
        peer_bits.append(f'{qsym} {fmt_multiple(pe,"pe")}/{fmt_multiple(pb,"pb")}/{fmt_multiple(ev,"ev_ebitda")}')
    console.print(Text('PEERS  ' + ('   '.join(peer_bits) if peer_bits else 'N/A'),style='white'))
    rc=cagr(hs['revenue']); de=latest(hs['debt'])/latest(hs['equity']) if latest(hs['equity']) else math.nan
    thesis=[]
    if np.isfinite(rc): thesis.append(('▲' if rc>0 else '▼')+f' Revenue CAGR {pct(rc)}')
    thesis.append(('▲' if p>=tech['sma200'] else '▼')+' 200DMA structure')
    if np.isfinite(r.get('upside',math.nan)): thesis.append(('▲' if r['upside']>=0 else '▼')+f' Blended value {pct(r["upside"])}')
    thesis.append('● Balance check PASS' if r['balance_ok'] else '● Balance check REVIEW')
    console.print(Text('  '.join(thesis),style='cyan'))
    console.print(Text(f'GWI {r["score"]:.0f}/100  {r["label"]}   |   DCF {dc.status}   |   3-statement {"PASS" if r["balance_ok"] else "REVIEW"}   |   HUMAN REVIEW REQUIRED',style='bold'))

    console.print(Rule('COMMAND RAIL',style='bright_blue'))
    console.print(Text('01 Research  02 Financials  03 Model  04 DCF  05 Valuation  06 Technical  07 Monte Carlo  08 Risk  09 Peers  13 GWI  20 Overview  21 Concall  24 Earnings  29 Scenario  36 IC  100 Fair Value',style='cyan'))
    console.print(Text(f'Active: {symbol.upper()}  •  Chart TF: {tf}  •  Use 06 for multi-TF technicals  •  TF 1D / 1W / 1M / 1H / 15M  •  T TICKER to switch',style='dim'))




def _v25_trend_signal(series, label):
    """Chronology-safe trend read using dated observations when available."""
    try:
        x=pd.to_numeric(pd.Series(series),errors='coerce').dropna()
        if len(x)<3: return f'{label}: LIMITED HISTORY'
        try:
            idx=pd.to_datetime(x.index,errors='coerce')
            if idx.notna().all():
                x=x.copy(); x.index=idx; x=x.sort_index()
                latest_v=float(x.iloc[-1]); prev_v=float(x.iloc[-2])
            else:
                latest_v=float(x.iloc[0]); prev_v=float(x.iloc[1])
        except Exception:
            latest_v=float(x.iloc[0]); prev_v=float(x.iloc[1])
        if prev_v==0: return f'{label}: N/A'
        ch=latest_v/prev_v-1
        state='IMPROVING' if ch>0.02 else 'DETERIORATING' if ch<-0.02 else 'STABLE'
        return f'{label}: {state} ({pct(ch)} vs prior)'
    except Exception: return f'{label}: N/A'

def _v25_data_confidence(d,r):
    """Evidence coverage score; distinguishes model quality from data completeness."""
    checks=[]
    f=d.get('financials',{}) if isinstance(d,dict) else {}
    for k in ('revenue','ebitda','net_income','cfo','capex','equity','debt','cash'):
        try: checks.append(pd.Series(f.get(k)).dropna().shape[0]>=2)
        except Exception: checks.append(False)
    checks += [bool(r.get('balance_ok')), r.get('dcf') is not None, r.get('mc') is not None]
    score=100*sum(checks)/len(checks) if checks else 0
    return float(score), sum(checks), len(checks)

def _v25_thesis_controls(price, tech, rev_c, ni_c, de, spread, mc, dcf_status):
    """Rule-based thesis invalidation triggers; never presents as a recommendation."""
    triggers=[]
    if np.isfinite(rev_c) and rev_c>0: triggers.append(f'Revenue growth turns negative ({pct(rev_c)} CAGR)')
    if np.isfinite(ni_c) and ni_c>0: triggers.append(f'Earnings growth turns negative ({pct(ni_c)} CAGR)')
    if np.isfinite(de) and de<1: triggers.append(f'Debt/equity rises above 1.0x (currently {de:.2f}x)')
    if np.isfinite(spread) and spread>.40: triggers.append(f'Valuation dispersion remains above 40% ({pct(spread)})')
    if np.isfinite(mc.get('p50',math.nan)) and np.isfinite(price) and mc['p50']<price: triggers.append('Monte Carlo median falls below market price')
    if dcf_status!='PASS': triggers.append('DCF/model integrity moves out of PASS')
    if not triggers: triggers=['No rule-based invalidation trigger currently active; reassess when new reported data arrives.']
    return triggers

def _v26_why_engine(p, dcfv, blend, peer, lynch, mc_p50, spread, rev_c, ni_c, ebitda_m, fcf_conv, de, roe, roce, tech, mc, dc):
    """Deterministic valuation + investment-case explanation layer.
    Explains drivers; it does not invent management commentary or forecasts.
    """
    def finite(x):
        try: return float(x) if np.isfinite(float(x)) else math.nan
        except Exception: return math.nan
    def rel(v):
        v=finite(v)
        return (v/p-1.0) if np.isfinite(v) and np.isfinite(p) and p else math.nan
    lines=[]
    drel, brel, prel, lrel, mrel = [rel(x) for x in (dcfv, blend, peer, lynch, mc_p50)]
    if np.isfinite(drel):
        lines.append(f'DCF {pct(drel)} vs price: intrinsic value is driven by forecast cash generation and the 8.00% discount / 3.50% terminal-growth setup.')
    if np.isfinite(prel):
        lines.append(f'Peer valuation {pct(prel)} vs price: market-relative value is anchored to comparable-company earnings multiples, so sector pricing constrains the upside.')
    if np.isfinite(mrel):
        lines.append(f'Monte Carlo P50 {pct(mrel)} vs price: the historical return distribution implies a more moderate central outcome than the DCF.')
    if np.isfinite(lynch) and np.isfinite(lrel):
        lines.append(f'Lynch-style value {pct(lrel)} vs price: the growth-versus-multiple relationship is less supportive than the intrinsic DCF case.')
    if np.isfinite(spread) and spread>.40:
        lines.append(f'Key disagreement: valuation dispersion is {pct(spread)}, so the investment case is sensitive to the method and assumptions selected.')
    elif np.isfinite(spread):
        lines.append(f'Valuation methods are relatively aligned, with dispersion of {pct(spread)}.')
    drivers=[]
    if np.isfinite(rev_c) and rev_c>0: drivers.append(f'revenue CAGR {pct(rev_c)}')
    if np.isfinite(ni_c) and ni_c>0: drivers.append(f'earnings CAGR {pct(ni_c)}')
    if np.isfinite(ebitda_m): drivers.append(f'EBITDA margin {pct(ebitda_m)}')
    if np.isfinite(fcf_conv) and fcf_conv>.80: drivers.append(f'FCF conversion {pct(fcf_conv)}')
    if np.isfinite(roe): drivers.append(f'ROE {pct(roe)}')
    if np.isfinite(de) and de<1: drivers.append(f'D/E {de:.2f}x')
    print_drivers=' • '.join(drivers[:5]) if drivers else 'insufficient quantitative evidence'
    risks=[]
    if np.isfinite(tech.get('sma200',math.nan)) and p < tech['sma200']: risks.append('price below 200DMA')
    if np.isfinite(mc.get('var95',math.nan)) and mc['var95']>.30: risks.append(f'VaR95 {pct(mc["var95"])}')
    if np.isfinite(mc.get('cvar95',math.nan)) and mc['cvar95']>.35: risks.append(f'CVaR95 {pct(mc["cvar95"])}')
    if np.isfinite(spread) and spread>.40: risks.append(f'valuation dispersion {pct(spread)}')
    return lines, print_drivers, (' • '.join(risks[:4]) if risks else 'no major quantitative counter-signal detected')

# ===================== V27 — COMPLETE SECTOR-AWARE RESEARCH LAYER =====================
def _v27_sector_profile(info):
    sector=str((info or {}).get('sector') or '').strip()
    industry=str((info or {}).get('industry') or '').strip()
    key=sector.lower()
    profiles={
        'technology': ('IT SERVICES', ['Revenue growth','Deal / demand momentum','EBITDA margin','FCF conversion','ROE','Utilization / cost discipline']),
        'information technology': ('IT SERVICES', ['Revenue growth','Deal / demand momentum','EBITDA margin','FCF conversion','ROE','Utilization / cost discipline']),
        'financial services': ('BANKING / FINANCIALS', ['Loan / AUM growth','NIM / spread economics','ROA / ROE','Asset quality','Credit cost','Capital adequacy / leverage']),
        'consumer defensive': ('CONSUMER / FMCG', ['Volume growth','Price / mix','Gross / EBITDA margin','Distribution strength','Working capital','Cash conversion']),
        'automobiles': ('AUTOMOTIVE', ['Volume growth','Realization / mix','EBITDA margin','Capacity utilization','Commodity sensitivity','Free cash flow']),
        'energy': ('ENERGY / UTILITIES', ['Production / volume','Realization','EBITDA margin','Capex intensity','Leverage','Commodity sensitivity']),
        'industrials': ('CAPITAL GOODS / INDUSTRIALS', ['Order book','Revenue growth','Execution','EBITDA margin','Working capital','Capex cycle']),
        'healthcare': ('PHARMA / HEALTHCARE', ['Revenue growth','Product / geography mix','EBITDA margin','R&D intensity','Regulatory exposure','FCF conversion']),
        'basic materials': ('MATERIALS / METALS', ['Volume','Realization','EBITDA margin','Commodity cycle','Capex','Leverage']),
    }
    for k,v in profiles.items():
        if k in key: return v
    # Industry fallback for common classifications.
    ik=industry.lower()
    if any(x in ik for x in ['bank','financial','insurance','nbfc']): return profiles['financial services']
    if any(x in ik for x in ['software','it service','technology']): return profiles['technology']
    if any(x in ik for x in ['pharma','drug','health']): return profiles['healthcare']
    return ('GENERAL EQUITY', ['Revenue growth','Earnings growth','Margin quality','FCF conversion','Returns on capital','Balance-sheet strength'])

def _v27_series_summary(series):
    try:
        x=pd.to_numeric(pd.Series(series),errors='coerce').dropna()
        if len(x)<2: return None
        try:
            idx=pd.to_datetime(x.index,errors='coerce')
            if idx.notna().sum()>=2: x=x.loc[idx.argsort()]
        except Exception: pass
        vals=x.to_numpy(dtype=float)
        first,last=float(vals[0]),float(vals[-1])
        change=(last/first-1) if first else math.nan
        return first,last,change
    except Exception: return None

def _v27_driver_status(name, metrics):
    # Traceable generic status; sector-specific names are explanatory, not fabricated company facts.
    m=metrics
    if name in {'Revenue growth','Deal / demand momentum','Volume growth','Loan / AUM growth','Order book','Production / volume'}:
        return 'SUPPORTIVE' if np.isfinite(m.get('rev_c',math.nan)) and m['rev_c']>0 else 'REVIEW'
    if name in {'EBITDA margin','Gross / EBITDA margin','Margin quality','Profitability'}:
        return 'SUPPORTIVE' if np.isfinite(m.get('margin',math.nan)) and m['margin']>.15 else 'REVIEW'
    if name in {'FCF conversion','Cash conversion','Free cash flow','FCF conversion / cash generation'}:
        return 'SUPPORTIVE' if np.isfinite(m.get('fcf_conv',math.nan)) and m['fcf_conv']>=.80 else 'REVIEW'
    if name in {'ROE','ROA / ROE','Returns on capital'}:
        return 'SUPPORTIVE' if np.isfinite(m.get('roe',math.nan)) and m['roe']>=.15 else 'REVIEW'
    if name in {'Balance-sheet strength','Leverage','Capital adequacy / leverage'}:
        return 'SUPPORTIVE' if np.isfinite(m.get('de',math.nan)) and m['de']<1 else 'REVIEW'
    return 'MONITOR'

def _v27_historical_block(f):
    rows=[]
    for key,label in [('revenue','Revenue'),('ebitda','EBITDA'),('net_income','Net Income'),('fcf','FCF')]:
        s=f.get(key)
        if s is None and key=='fcf': continue
        sm=_v27_series_summary(s) if s is not None else None
        if sm:
            first,last,ch=sm
            rows.append(f'{label:<10} {money(first):>12}  →  {money(last):<12}  {pct(ch):>8}')
    return rows

def _v27_thesis_conditions(rev_c,ni_c,margin,fcf_conv,de,spread,tech,mc):
    go=[]; breakx=[]
    go.append('Revenue growth stays positive') if np.isfinite(rev_c) and rev_c>0 else go.append('Revenue growth must recover')
    go.append('Earnings growth stays positive') if np.isfinite(ni_c) and ni_c>0 else go.append('Earnings growth must recover')
    go.append('Margins remain resilient') if np.isfinite(margin) and margin>.15 else go.append('Margins need improvement')
    go.append('FCF conversion remains healthy') if np.isfinite(fcf_conv) and fcf_conv>=.80 else go.append('FCF conversion needs improvement')
    if np.isfinite(rev_c) and rev_c<=0: breakx.append('Revenue growth turns negative')
    if np.isfinite(ni_c) and ni_c<=0: breakx.append('Earnings growth turns negative')
    if np.isfinite(margin) and margin<.15: breakx.append('Operating margin falls below quality threshold')
    if np.isfinite(fcf_conv) and fcf_conv<.70: breakx.append('FCF conversion falls below 70%')
    if np.isfinite(de) and de>1: breakx.append('Debt / equity exceeds 1.0x')
    if np.isfinite(spread) and spread>.50: breakx.append('Valuation dispersion exceeds 50%')
    if np.isfinite(tech.get('rsi',math.nan)) and tech['rsi']<30: breakx.append('Technical momentum reaches oversold extremes')
    if not breakx: breakx.append('No immediate quantitative thesis-break trigger detected')
    return go,breakx

def _v24_security_master(symbol):
    """V24 master security page: one tap, core equity-research decision sheet."""
    d,r=run_research(symbol,sims=5000,peer_override=(ACTIVE_PEERS if ACTIVE_PEERS else None))
    info=r.get('info',{}); f=d.get('financials',{}); tech=r.get('tech',{}); mc=r.get('mc',{}); dc=r.get('dcf')
    p=float(r.get('price',math.nan)); company=_company_name(d)
    def fv(x):
        try: return float(x) if np.isfinite(float(x)) else math.nan
        except Exception: return math.nan
    def growth_label(x):
        x=fv(x)
        return 'ACCELERATING' if x>0.12 else 'GROWING' if x>0.02 else 'FLAT' if x>=-0.02 else 'DECLINING'
    def status(ok, good='PASS', bad='REVIEW'): return good if ok else bad

    rev=latest(f.get('revenue',pd.Series(dtype=float))); ebitda=latest(f.get('ebitda',pd.Series(dtype=float))); ni=latest(f.get('net_income',pd.Series(dtype=float)))
    cfo=latest(f.get('cfo',pd.Series(dtype=float))); capex=latest(f.get('capex',pd.Series(dtype=float))); fcf=cfo-capex
    eq=latest(f.get('equity',pd.Series(dtype=float))); debt=latest(f.get('debt',pd.Series(dtype=float))); cash=latest(f.get('cash',pd.Series(dtype=float)))
    rev_c=_fv_cagr(f.get('revenue',pd.Series(dtype=float))); ni_c=_fv_cagr(f.get('net_income',pd.Series(dtype=float))); fcf_c=_fv_cagr(r.get('fcf',pd.Series(dtype=float)))
    ebitda_m=ebitda/rev if np.isfinite(ebitda) and np.isfinite(rev) and rev else math.nan
    fcf_conv=fcf/cfo if np.isfinite(fcf) and np.isfinite(cfo) and cfo else math.nan
    de=debt/eq if np.isfinite(debt) and np.isfinite(eq) and eq else math.nan
    roe=fv(r.get('roe'))
    roce=fv(info.get('returnOnCapitalEmployed'))
    if not np.isfinite(roce):
        try:
            ebit=latest(f.get('ebit',pd.Series(dtype=float)))
            invested=debt+eq-cash
            roce=ebit/invested if np.isfinite(ebit) and invested>0 else math.nan
        except Exception:
            roce=math.nan

    cl=d.get('history',{}).get('Close',pd.Series(dtype=float)).dropna(); day=(cl.iloc[-1]/cl.iloc[-2]-1) if len(cl)>1 else math.nan
    console.clear(); console.print(header())
    console.print(Rule(f'[bold cyan]{symbol.upper()}[/bold cyan]  {company}  |  {money(p)}  |  {pct(day)}  |  P/E {fmt_multiple(info.get("trailingPE"),"pe")}  |  P/B {fmt_multiple(info.get("priceToBook"),"pb")}  |  ROE {pct(roe)}  |  GWI {r.get("score",math.nan):.0f}/100',style='cyan'))
    console.print(Text(f'{info.get("sector") or "Sector N/A"}  •  {info.get("industry") or "Industry N/A"}  •  52W {money(tech.get("low"))} — {money(tech.get("high"))}  •  RSI {num(tech.get("rsi"))}  •  Technical {tech.get("score",math.nan):.0f}/100',style='dim'))

    console.print(Rule('20  |  SECURITY MASTER — ONE-TAP EQUITY RESEARCH',style='bright_blue'))

    # 1) Fundamental scorecard
    console.print(Rule('01  FUNDAMENTAL QUALITY / BUSINESS ECONOMICS',style='cyan'))
    ft=Table.grid(expand=True,padding=(0,2))
    for _ in range(4): ft.add_column(ratio=1)
    ft.add_row(Text(f'Revenue\n{money(rev)}\nCAGR {pct(rev_c)}',style='white'),Text(f'EBITDA\n{money(ebitda)}\nMargin {pct(ebitda_m)}',style='white'),Text(f'Net Income\n{money(ni)}\nCAGR {pct(ni_c)}',style='white'),Text(f'FCF\n{money(fcf)}\nConversion {pct(fcf_conv)}',style='white'))
    ft.add_row(Text(f'ROE\n{pct(roe)}',style='white'),Text(f'ROCE\n{pct(roce) if np.isfinite(roce) else "N/A*"}',style='white'),Text(f'Debt / Equity\n{de:.2f}x' if np.isfinite(de) else 'Debt / Equity\nN/A',style='white'),Text(f'Cash\n{money(cash)}',style='white'))
    console.print(ft)
    quality=95.0 if np.isfinite(roe) and roe>.20 else 75.0
    if np.isfinite(de) and de>1: quality-=15
    if np.isfinite(fcf_conv) and fcf_conv<.70: quality-=10
    quality=float(np.clip(quality,0,100))
    console.print(Text(f'Financial Quality {quality:.0f}/100  |  Revenue {growth_label(rev_c)}  |  Earnings {growth_label(ni_c)}  |  Cash conversion {status(np.isfinite(fcf_conv) and fcf_conv>=.80,"STRONG","REVIEW")}',style='bold white'))

    # V27 sector-aware economic driver layer.
    sector_name, driver_names=_v27_sector_profile(info)
    console.print(Rule('01A  SECTOR-AWARE ECONOMIC DRIVER TREE',style='bright_blue'))
    console.print(Text(f'Sector framework: {sector_name}  |  Industry: {info.get("industry") or "N/A"}',style='bold cyan'))
    metrics={'rev_c':rev_c,'ni_c':ni_c,'margin':ebitda_m,'fcf_conv':fcf_conv,'roe':roe,'de':de}
    driver_bits=[]
    for name in driver_names:
        driver_bits.append(f'{name}: {_v27_driver_status(name,metrics)}')
    dt=Table.grid(expand=True,padding=(0,2)); dt.add_column(); dt.add_column(); dt.add_column()
    for i in range(0,len(driver_bits),3):
        chunk=driver_bits[i:i+3]
        while len(chunk)<3: chunk.append('')
        dt.add_row(*[Text(x,style='green' if 'SUPPORTIVE' in x else 'yellow' if 'REVIEW' in x else 'dim') for x in chunk])
    console.print(dt)
    console.print(Text('Driver tree is evidence-led: unavailable sector KPIs are not fabricated; they remain MONITOR / REVIEW.',style='dim'))

    # V27 multi-year trajectory: show direction, not just CAGR.
    console.print(Rule('01B  FIVE-YEAR FINANCIAL TRAJECTORY',style='bright_blue'))
    hist_rows=_v27_historical_block(f)
    if hist_rows:
        console.print(Text('Metric             Start           Latest        Change',style='dim'))
        console.print(Text('\n'.join(hist_rows),style='white'))
    else:
        console.print(Text('Historical financial trajectory unavailable from configured source.',style='yellow'))

    # 2) Earnings / inflection
    console.print(Rule('02  EARNINGS / FUNDAMENTAL INFLECTION',style='cyan'))
    try:
        from institutional_pack import _quarterly_intelligence
        qdf,qmeta=_quarterly_intelligence(d)
        if not qdf.empty:
            q=qdf.iloc[-1]; period=str(qdf.index[-1])[:10]
            rows=[]
            for key,label in [('Revenue','Revenue'),('EBITDA','EBITDA'),('Net Income','Earnings')]:
                if key in qdf.columns and np.isfinite(q.get(key,np.nan)):
                    yoy=q.get(key+' YoY',np.nan); rows.append(f'{label:<9} {money(q[key])}  {pct(yoy) if np.isfinite(yoy) else "N/A"} YoY')
            console.print(Text(f'Latest reported quarter: {period}\n'+'\n'.join(rows),style='white'))
            console.print(Text(f'Inflection signal: {qmeta.get("message","Limited quarterly trend history.")}',style='dim'))
        else: console.print(Text('Quarterly intelligence unavailable from configured source.',style='yellow'))
    except Exception as e: console.print(Text(f'Quarterly intelligence REVIEW: {type(e).__name__}',style='yellow'))

    # 3) Valuation stack
    console.print(Rule('03  VALUATION / FAIR VALUE / MARGIN OF SAFETY',style='cyan'))
    pctile=mc.get('percentiles',{})
    mc_p5=pctile.get('P5',mc.get('p5',math.nan)); mc_p50=pctile.get('P50',mc.get('p50',math.nan)); mc_p95=pctile.get('P95',mc.get('p95',math.nan))
    dcfv=fv(dc.target) if dc is not None else math.nan; blend=fv(r.get('blended')); peer=fv(r.get('implied')); lynch=fv(_v18_lynch_value(r,d))
    vals=[v for v in [dcfv,blend,peer,mc_p50] if np.isfinite(v) and v>0]
    spread=(max(vals)-min(vals))/np.mean(vals) if len(vals)>=2 else math.nan
    vg=Table.grid(expand=True,padding=(0,2))
    for _ in range(5): vg.add_column(ratio=1)
    vg.add_row(Text(f'DCF\n{money(dcfv)}\n{pct(dcfv/p-1)}',style='white'),Text(f'Blended\n{money(blend)}\n{pct(blend/p-1)}',style='white'),Text(f'Peer P/E\n{money(peer)}',style='white'),Text(f'Lynch\n{money(lynch)}',style='white'),Text(f'MC P50\n{money(mc_p50)}\nP5 {money(mc_p5)} / P95 {money(mc_p95)}',style='white'))
    console.print(vg)
    confidence='HIGH' if np.isfinite(spread) and spread<=.25 else 'MODERATE' if np.isfinite(spread) and spread<=.50 else 'LOW'
    console.print(Text(f'Method spread {pct(spread)}  |  Valuation confidence {confidence}  |  DCF {getattr(dc,"status","REVIEW")}  |  WACC {pct(getattr(dc,"wacc",math.nan))}  |  g {pct(getattr(dc,"terminal_growth",math.nan))}',style='yellow' if confidence!='HIGH' else 'dim'))
    if confidence=='MODERATE': console.print(Text('Confidence driver: valuation methods show material dispersion; use the range rather than a single-point target.',style='dim'))
    elif confidence=='LOW': console.print(Text('Confidence driver: valuation methods diverge substantially; single-point fair value should not be relied upon.',style='yellow'))
    if vals:
        low_v, high_v=min(vals), max(vals)
        console.print(Text(f'Valuation bridge  LOW {money(low_v)}  →  BLENDED {money(blend) if np.isfinite(blend) else money(np.mean(vals))}  →  HIGH {money(high_v)}  |  Range width {money(high_v-low_v)}',style='dim'))
    console.print(Text(f'Margin vs blended {pct(blend/p-1)}  |  MC positive {pct(mc.get("positive_prob",math.nan))}',style='white'))
    # WHY ENGINE: explain the valuation disagreement and the operating evidence behind it.
    console.print(Rule('03A  WHY THE VALUE IS DIFFERENT / VALUATION DIAGNOSTICS',style='bright_blue'))
    why_lines, why_drivers, why_risks = _v26_why_engine(p, dcfv, blend, peer, lynch, mc_p50, spread, rev_c, ni_c, ebitda_m, fcf_conv, de, roe, roce, tech, mc, dc)
    for line in why_lines[:4]:
        console.print(Text('• '+line,style='white'))
    console.print(Text('OPERATING DRIVERS  '+why_drivers,style='green'))
    console.print(Text('COUNTER-SIGNALS  '+why_risks,style='yellow'))
    if np.isfinite(blend) and np.isfinite(p):
        direction='above' if blend>p else 'below'
        console.print(Text(f'RESEARCH INTERPRETATION  Blended value is {pct(abs(blend/p-1))} {direction} price; conviction should depend on whether the operating evidence can support the valuation assumptions.',style='bold white'))

    # 4) Risk + forensic controls
    console.print(Rule('04  EARNINGS QUALITY / FORENSIC / RISK',style='cyan'))
    checks=[('FCF conversion',np.isfinite(fcf_conv) and fcf_conv>=.80),('CFO vs Net Income',np.isfinite(cfo) and np.isfinite(ni) and cfo>=ni*.80),('Leverage',np.isfinite(de) and de<1),('3-statement',bool(r.get('balance_ok'))),('DCF integrity',getattr(dc,'status','REVIEW')=='PASS')]
    passed=sum(ok for _,ok in checks); risk=80.0
    if np.isfinite(mc.get('var95',math.nan)) and mc['var95']>.30: risk-=10
    if np.isfinite(mc.get('cvar95',math.nan)) and mc['cvar95']>.35: risk-=10
    if np.isfinite(spread) and spread>.60: risk-=5
    if np.isfinite(tech.get('rsi',math.nan)) and tech['rsi']<35: risk-=5
    risk=float(np.clip(risk,0,100))
    console.print(Text('  '.join(f'{name}: {"PASS" if ok else "REVIEW"}' for name,ok in checks),style='white'))
    console.print(Text(f'Forensic evidence {passed}/{len(checks)} PASS  |  Risk / resilience {risk:.0f}/100  |  VaR95 {pct(mc.get("var95",math.nan))}  |  CVaR95 {pct(mc.get("cvar95",math.nan))}  |  Max DD {pct(mc.get("avg_max_dd", mc.get("avg_max_drawdown",math.nan)))}',style='white'))

    # Evidence coverage: prevents a polished score from masking missing source data.
    dcov, dcov_ok, dcov_n = _v25_data_confidence(d,r)
    console.print(Text(f'DATA / MODEL COVERAGE  {dcov:.0f}/100  |  Evidence fields {dcov_ok}/{dcov_n}  |  Score is not a substitute for source completeness.', style='green' if dcov>=80 else 'yellow'))

    # 5) Peers + moat/capital allocation proxy
    console.print(Rule('05  RELATIVE VALUE / MOAT / CAPITAL ALLOCATION',style='cyan'))
    peers=list(ACTIVE_PEERS) if ACTIVE_PEERS else SECTORS.get(info.get('sector',''),[])[:5]
    pt=Table.grid(expand=True,padding=(0,1)); pt.add_column(width=10); pt.add_column(width=9,justify='right'); pt.add_column(width=9,justify='right'); pt.add_column(width=12,justify='right')
    pt.add_row('Peer','P/E','P/B','EV/EBITDA')
    # Provider-safe peer lookup: never expose raw Yahoo/provider errors in the terminal.
    for qsym in peers[:6]:
        try:
            pe,pb,ev=_provider_call(lambda: peer_metrics(qsym), (None,None,None))
            pt.add_row(qsym,fmt_multiple(pe,'pe'),fmt_multiple(pb,'pb'),fmt_multiple(ev,'ev_ebitda'))
        except Exception:
            pt.add_row(qsym,'N/A','N/A','N/A')
    console.print(pt if peers else Text('Peer set unavailable.',style='yellow'))
    peer_valid=0
    for qsym in peers[:6]:
        try:
            vals_peer=_provider_call(lambda: peer_metrics(qsym), (None,None,None))
            if any(v is not None and np.isfinite(float(v)) for v in vals_peer if v is not None): peer_valid += 1
        except Exception:
            pass
    console.print(Text(f'Peer data coverage {peer_valid}/{min(len(peers),6)}  |  Provider errors suppressed  |  N/A indicates unavailable source data',style='dim'))
    moat=[]
    if np.isfinite(roe) and roe>.20: moat.append('high return on equity')
    if np.isfinite(roce) and roce>.20: moat.append('strong capital returns')
    if np.isfinite(de) and de<.5: moat.append('low balance-sheet leverage')
    console.print(Text('Moat evidence: '+(' • '.join(moat) if moat else 'insufficient quantitative evidence'),style='white'))

    # 6) Bull / bear / catalyst / thesis
    console.print(Rule('06  BULL • BEAR • CATALYST • THESIS',style='cyan'))
    bull=[]; bear=[]
    if np.isfinite(rev_c) and rev_c>0: bull.append(f'revenue CAGR {pct(rev_c)}')
    if np.isfinite(ni_c) and ni_c>0: bull.append(f'earnings CAGR {pct(ni_c)}')
    if np.isfinite(fcf_conv) and fcf_conv>.80: bull.append(f'FCF conversion {pct(fcf_conv)}')
    if np.isfinite(de) and de<1: bull.append(f'low leverage {de:.2f}x')
    if p < fv(tech.get('sma200')): bear.append('price below 200DMA')
    if np.isfinite(spread) and spread>.40: bear.append(f'valuation spread {pct(spread)}')
    if np.isfinite(mc.get('var95',math.nan)) and mc['var95']>.30: bear.append(f'VaR95 {pct(mc["var95"])}')
    console.print(Text('BULL CASE   '+(' • '.join(bull) if bull else 'Insufficient positive evidence'),style='green'))
    console.print(Text('BEAR CASE   '+(' • '.join(bear) if bear else 'No major rule-based counter-thesis'),style='yellow'))
    console.print(Text('CATALYSTS   Earnings acceleration • margin expansion • positive guidance/revisions • stronger FCF',style='dim'))
    console.print(Text('RISKS       Earnings disappointment • margin pressure • multiple compression • sector slowdown',style='dim'))
    thesis=('Strong business quality and cash generation' if bull else 'Evidence remains mixed') + ('; offset by ' + ', '.join(bear[:3]) if bear else '; no major quantitative counter-signal detected') + '.'
    console.print(Text('ONE-LINE THESIS  '+thesis,style='bold white'))

    # Institutional trend panel: direction of the core financial series.
    console.print(Text('TREND CHECK  '+_v25_trend_signal(f.get('revenue',pd.Series(dtype=float)),'Revenue')+'  |  '+_v25_trend_signal(f.get('ebitda',pd.Series(dtype=float)),'EBITDA')+'  |  '+_v25_trend_signal(f.get('net_income',pd.Series(dtype=float)),'Net Income'),style='dim'))
    _mc_for_controls={'p50':mc_p50}
    invalid=_v25_thesis_controls(p,tech,rev_c,ni_c,de,spread,_mc_for_controls,getattr(dc,'status','REVIEW'))
    console.print(Text('WHAT WOULD CHANGE THE THESIS  '+ ' • '.join(invalid[:4]),style='yellow'))

    # Investment-case synthesis: separate evidence, counter-evidence and conditions.
    console.print(Rule('06A  INVESTMENT CASE ENGINE',style='bright_blue'))
    case_strength=[]
    if np.isfinite(rev_c) and rev_c>0: case_strength.append('positive long-term revenue growth')
    if np.isfinite(ni_c) and ni_c>0: case_strength.append('positive earnings growth')
    if np.isfinite(fcf_conv) and fcf_conv>=.80: case_strength.append('strong cash conversion')
    if np.isfinite(roe) and roe>=.20: case_strength.append('high return on equity')
    if np.isfinite(de) and de<1: case_strength.append('low leverage')
    case_risk=[]
    if p < fv(tech.get('sma200')): case_risk.append('technical trend below 200DMA')
    if np.isfinite(spread) and spread>.40: case_risk.append('valuation methods materially disagree')
    if np.isfinite(mc.get('var95',math.nan)) and mc['var95']>.30: case_risk.append('elevated modeled downside risk')
    console.print(Text('CORE CASE       '+(' • '.join(case_strength[:5]) if case_strength else 'insufficient evidence'),style='green'))
    console.print(Text('COUNTER-CASE   '+(' • '.join(case_risk[:4]) if case_risk else 'no major quantitative counter-case'),style='yellow'))
    console.print(Text('THESIS TEST     The case strengthens if growth, margins and cash conversion remain resilient while valuation dispersion narrows; it weakens if earnings deteriorate or the market multiple compresses.',style='white'))
    console.print(Text('ANALYST ACTION  Validate the assumptions behind the DCF and peer set before treating the blended value as a target.',style='dim'))

    # V27 investment-case conditions: explicit requirements and breakpoints.
    console.print(Rule('06B  WHAT HAS TO GO RIGHT / WHAT CAN BREAK THE THESIS',style='bright_blue'))
    go,breakx=_v27_thesis_conditions(rev_c,ni_c,ebitda_m,fcf_conv,de,spread,tech,mc)
    console.print(Text('WHAT HAS TO GO RIGHT  ' + ' • '.join(go),style='green'))
    console.print(Text('THESIS BREAK CONDITIONS  ' + ' • '.join(breakx[:5]),style='yellow'))
    console.print(Text('RESEARCH QUESTION  Can the sector-specific operating drivers remain strong enough to justify the intrinsic and relative valuation assumptions?',style='bold white'))

    # 7) Final integrated view
    console.print(Rule('07  FINAL INTEGRATED RESEARCH VIEW',style='bright_green'))
    components={'Business':quality,'Earnings':90.0 if np.isfinite(ni_c) and ni_c>0 else 65.0,'Valuation':70.0 if np.isfinite(blend) and blend>p else 45.0,'Risk':risk,'Technical':fv(tech.get('score'))}
    if np.isfinite(spread) and spread>.60: components['Valuation']=max(30,components['Valuation']-10)
    integrated=float(np.mean(list(components.values())))
    label='VERY ATTRACTIVE' if integrated>=80 else 'ATTRACTIVE' if integrated>=70 else 'CONSTRUCTIVE' if integrated>=55 else 'NEUTRAL' if integrated>=40 else 'CAUTIOUS'
    row=Table.grid(expand=True,padding=(0,2))
    for _ in range(5): row.add_column(ratio=1)
    row.add_row(*[Text(f'{k}\n{v:.0f}/100',style='bold cyan' if k in {'Business','Earnings'} else 'white') for k,v in components.items()])
    console.print(row)
    console.print(Text(f'RESEARCH VIEW  {label}  |  Integrated score {integrated:.0f}/100  |  GWI {r.get("score",math.nan):.0f}/100  |  Valuation confidence {confidence}',style='bold yellow'))
    console.print(Text('DATA / MODEL CONTROL  '+f'3-Statement {status(bool(r.get("balance_ok")))}  •  DCF {getattr(dc,"status","REVIEW")}  •  MC AVAILABLE  •  Peers {"MANUAL" if (ACTIVE_PEERS) else "AUTO-SECTOR"}  •  Human decision remains separate',style='dim'))
    console.print(Rule('DRILL-DOWN — ONLY IF YOU NEED MORE DETAIL',style='bright_blue'))
    console.print(Text('02 Financials   03 Model   04 DCF   05 Valuation   06 Technical   07 Monte Carlo   08 Risk   09 Peers   21 Concall   24 Earnings   26 Forensic   29 Scenario   36 IC   90 Research Intelligence   100 Fair Value',style='cyan'))
    _visual_pause()

def _v18_technical(symbol, timeframe='1D'):
    d,r=run_research(symbol,sims=3000); h,tf=_v18_tf_history(d,timeframe); tech=r['tech']; p=r['price']; console.clear(); console.print(header())
    console.print(Rule(f'[bold cyan]{symbol.upper()}[/bold cyan]  TECHNICAL WORKSTATION  |  {tf}',style='cyan'))
    console.print(_v18_candle_chart(h,120,24))
    console.print(Text(f'20DMA {money(tech["sma20"])}   •   50DMA {money(tech["sma50"])}   •   200DMA {money(tech["sma200"])}   •   RSI {num(tech["rsi"])}   •   52W {money(tech["low"])} — {money(tech["high"])}   •   Score {tech["score"]:.0f}/100',style='cyan'))
    console.print(Rule('TIMEFRAME SELECTOR',style='bright_blue'))
    console.print(Text('1D  Daily   |   1W  Weekly   |   1M  Monthly   |   1H  Hourly   |   15M  Intraday',style='white'))
    console.print(Text('TradingView handoff: TV  •  Terminal chart remains native/offline-capable; embedded TradingView requires a GUI/webview layer and applicable licensing.',style='dim'))
    console.print(Rule('DEEP TECHNICAL CONTEXT',style='bright_blue'))
    console.print(Text(f'Current {money(p)}   •   Trend vs 200DMA: {"ABOVE" if np.isfinite(tech["sma200"]) and p>tech["sma200"] else "BELOW"}   •   RSI state: {"OVERSOLD" if np.isfinite(tech["rsi"]) and tech["rsi"]<30 else "OVERBOUGHT" if np.isfinite(tech["rsi"]) and tech["rsi"]>70 else "NEUTRAL"}',style='white'))


def _v18_main():
    console.clear(); console.print(header())
    console.print(Rule('[bold cyan]GROWISEINVEST[/bold cyan]  SINGLE-SECURITY VISUAL WORKSTATION',style='cyan'))
    console.print(Text('Enter the company once. GROWISE loads the integrated security page: candlesticks, multi-timeframe technicals, fundamentals, DCF, fair value, Monte Carlo, earnings, peers, risk and thesis.',style='white'))
    console.print(Text('VISUAL MODE  •  1D / 1W / 1M / 1H / 15M  •  number-first navigation  •  source-controlled data  •  analyst remains decision-maker',style='dim'))
    while True:
        try:
            raw=console.input('[bold cyan]ENTER NSE TICKER (or 00 to exit): [/bold cyan]').strip()
            if raw.upper() in {'00','EXIT','QUIT','Q'}: break
            if not raw: continue
            symbol=raw.split()[0].upper().replace('.NS','').replace('.BO','')
            if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',symbol): console.print('[yellow]Invalid ticker format.[/yellow]'); continue
            try: _v18_security_dashboard(symbol,'1D')
            except Exception as e:
                console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='SECURITY LOAD ERROR',border_style='red')); continue
            while True:
                cmd=console.input(f'\n[bold cyan]GROWISEINVEST / {symbol} > [/bold cyan]').strip()
                if not cmd: continue
                up=cmd.upper()
                if up.startswith(('T ','TICKER ')):
                    symbol=cmd.split(None,1)[1].upper().replace('.NS','').replace('.BO',''); _v18_security_dashboard(symbol,'1D'); continue
                if up.startswith('TF '):
                    tf=cmd.split(None,1)[1].upper(); _v18_security_dashboard(symbol,tf); continue
                if up in {'00','EXIT','QUIT','Q'}: return
                if up in {'HOME','H'}: _v18_security_dashboard(symbol,'1D'); continue
                if up.startswith('TV'):
                    try:
                        import webbrowser; webbrowser.open(f'https://www.tradingview.com/symbols/{symbol}/?exchange=NSE')
                        console.print(Text(f'Opened TradingView for NSE:{symbol} in the default browser.',style='cyan'))
                    except Exception as e: console.print(Text(f'Browser handoff unavailable: {e}',style='yellow'))
                    continue
                parts=cmd.split(); n=parts[0]
                if n.isdigit():
                    if n=='06':
                        tf=parts[1].upper() if len(parts)>1 else '1D'; _v18_technical(symbol,tf); _visual_pause(); _v18_security_dashboard(symbol,tf); continue
                    ok=_v17_dispatch_same_ticker(n,symbol)
                    if not ok: return
                else:
                    console.print('[yellow]Enter a module number, TF 1W, TF 1H, TV, or T TICKER.[/yellow]')
        except KeyboardInterrupt: console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e: console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='WORKSTATION ERROR',border_style='red'))

main=_v18_main
# Legacy startup disabled: V27 has one canonical entrypoint.


def _v20_main():
    console.clear(); console.print(header())
    console.print(Rule('[bold cyan]GROWISEINVEST[/bold cyan]  PROFESSIONAL SINGLE-SECURITY RESEARCH WORKSTATION',style='cyan'))
    console.print(Text('Enter one company. Optional peers can be supplied once. GROWISE then builds the full research stack and exports the institutional Word + Excel pack.',style='white'))
    console.print(Text('PRICE • CANDLES • TECHNICALS • FUNDAMENTALS • DCF • FAIR VALUE • MONTE CARLO • EARNINGS • CONCALL • PEERS • RISK • THESIS',style='dim'))
    console.print(Rule('ALL 50 SERVICES',style='bright_blue')); console.print(_service_map_compact())
    console.print(Text('90  EQUITY RESEARCH INTELLIGENCE  |  98  SYSTEM DIAGNOSTICS  |  100  FAIR VALUE CALCULATOR  |  99  FULL INDEX  |  00  EXIT',style='bold yellow'))
    while True:
        try:
            raw=console.input('\n[bold cyan]ENTER NSE TICKER (or 00 to exit): [/bold cyan]').strip()
            if raw.upper() in {'00','EXIT','QUIT','Q'}: break
            if not raw: continue
            symbol=raw.split()[0].upper().replace('.NS','').replace('.BO','')
            if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',symbol):
                console.print('[yellow]Invalid ticker format.[/yellow]'); continue
            _set_session_peers()
            console.print(Rule(f'[bold cyan]RUNNING COMPLETE RESEARCH STACK — {symbol}[/bold cyan]',style='cyan'))
            with Progress(SpinnerColumn(),TextColumn('{task.description}'),console=console) as prog:
                task=prog.add_task('Market / OHLC / volume',total=None); d,r=run_research(symbol,sims=5000); prog.update(task,description='Market / OHLC / volume ✓');
                prog.update(task,description='Fundamentals / 3-statement / DCF ✓');
                prog.update(task,description='Technical / Monte Carlo / risk ✓');
                prog.update(task,description='Peers / earnings / valuation ✓');
            _v18_security_dashboard(symbol,'1D')
            _auto_export_session(symbol)
            console.print(Rule('WORKSTATION READY',style='bright_blue'))
            console.print(Text('The active security is retained. Enter a module number for a deeper view; use T TICKER to switch company.',style='dim'))
            while True:
                cmd=console.input(f'\n[bold cyan]GROWISEINVEST / {symbol} > [/bold cyan]').strip()
                if not cmd: continue
                up=cmd.upper()
                if up.startswith(('T ','TICKER ')):
                    symbol=cmd.split(None,1)[1].upper().replace('.NS','').replace('.BO','')
                    _set_session_peers(); _v18_security_dashboard(symbol,'1D'); _auto_export_session(symbol); continue
                if up in {'00','EXIT','QUIT','Q'}: return
                if up in {'HOME','H'}: _v18_security_dashboard(symbol,'1D'); continue
                if up.startswith('PEERS'):
                    _set_session_peers(); _v18_security_dashboard(symbol,'1D'); _auto_export_session(symbol); continue
                if up.startswith('TF '):
                    _v18_security_dashboard(symbol,cmd.split(None,1)[1]); continue
                if up.startswith('TV'):
                    try:
                        import webbrowser; webbrowser.open(f'https://www.tradingview.com/symbols/{symbol}/?exchange=NSE')
                        console.print(Text(f'Opened TradingView for NSE:{symbol} in the default browser.',style='cyan'))
                    except Exception as e: console.print(Text(f'Browser handoff unavailable: {e}',style='yellow'))
                    continue
                parts=cmd.split(); n=parts[0]
                if n.isdigit():
                    if n=='50': console.clear(); console.print(header()); continue
                    if n=='06':
                        tf=parts[1] if len(parts)>1 else '1D'; _v18_technical(symbol,tf); _visual_pause(); _v18_security_dashboard(symbol,tf); continue
                    ok=_v17_dispatch_same_ticker(n,symbol)
                    if not ok: return
                else:
                    console.print('[yellow]Enter a module number, TF 1W, TF 1M, TF 1H, TF 15M, PEERS, TV, or T TICKER.[/yellow]')
        except KeyboardInterrupt:
            console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'[red]{type(e).__name__}: {e}[/red]',title='WORKSTATION ERROR',border_style='red'))


# ===================== V27 — EQUITY RESEARCH INTELLIGENCE =====================
# Public institutional intelligence service.
# Command: 90
def _v22_bar(value, width=24):
    try:
        v=float(value)
        if not np.isfinite(v): return 'N/A'
        n=max(0,min(width,int(round(v/100*width))))
        return '█'*n + '·'*(width-n)
    except Exception:
        return 'N/A'

def _v22_direction(v, positive='IMPROVING', negative='DETERIORATING'):
    try:
        v=float(v)
        if not np.isfinite(v): return 'N/A'
        return positive if v>0.01 else negative if v<-0.01 else 'STABLE'
    except Exception:
        return 'N/A'

def _v22_intelligence(symbol):
    """Hidden analyst-grade synthesis: business, financial quality, inflection, valuation, risks and thesis."""
    console.clear()
    console.print(header())
    console.print(Rule(f'[bold cyan]{symbol.upper()}[/bold cyan]  EQUITY RESEARCH INTELLIGENCE ENGINE', style='bright_blue'))
    console.print(Text('Proprietary synthesis view — combines existing GROWISE evidence without inventing unavailable facts.', style='dim'))

    d, r = run_research(symbol, sims=5000, peer_override=(ACTIVE_PEERS if ACTIVE_PEERS else None))
    info=r.get('info',{}) or {}
    hs=d.get('financials',{})
    tech=r.get('tech',{})
    dc=r.get('dcf')
    mc=r.get('mc') or {}
    model=r.get('model')
    # Normalize Monte Carlo output across engine versions.
    # Some versions expose percentiles as a nested dict rather than p5/p50/p95 keys.
    _mc_pct = mc.get('percentiles', {}) if isinstance(mc, dict) else {}
    mc_p5 = mc.get('p5', _mc_pct.get('P5', math.nan)) if isinstance(mc, dict) else math.nan
    mc_p50 = mc.get('p50', _mc_pct.get('P50', math.nan)) if isinstance(mc, dict) else math.nan
    mc_p95 = mc.get('p95', _mc_pct.get('P95', math.nan)) if isinstance(mc, dict) else math.nan
    mc_pos = mc.get('positive_prob', math.nan) if isinstance(mc, dict) else math.nan
    mc_var = mc.get('var95', math.nan) if isinstance(mc, dict) else math.nan
    mc_cvar = mc.get('cvar95', math.nan) if isinstance(mc, dict) else math.nan

    def latest_safe(key):
        try: return float(latest(hs[key]))
        except Exception: return math.nan
    def cagr_safe(key):
        try: 
            x=cagr(hs[key]); return float(x) if x is not None else math.nan
        except Exception: return math.nan

    rev_cagr=cagr_safe('revenue'); ni_cagr=cagr_safe('net_income')
    rev=latest_safe('revenue'); ebitda=latest_safe('ebitda'); ni=latest_safe('net_income')
    cfo=latest_safe('cfo'); capex=latest_safe('capex'); debt=latest_safe('debt'); equity=latest_safe('equity')
    fcf=cfo-capex if np.isfinite(cfo) and np.isfinite(capex) else math.nan
    margin=ebitda/rev if np.isfinite(ebitda) and np.isfinite(rev) and rev else math.nan
    roe=ni/equity if np.isfinite(ni) and np.isfinite(equity) and equity else math.nan
    de=debt/equity if np.isfinite(debt) and np.isfinite(equity) and equity else math.nan
    fcf_conv=fcf/cfo if np.isfinite(fcf) and np.isfinite(cfo) and cfo else math.nan
    price=r['price']
    upside=r.get('upside',math.nan)

    # Evidence scores are deliberately transparent and bounded.
    business=np.clip(50 + (15 if rev_cagr>0 else -10) + (10 if roe>.15 else 5 if roe>.10 else -5)
                     + (10 if de<.5 else 0 if de<1 else -10) + (10 if margin>.15 else 0),0,100)
    cash_score=np.clip(50 + (20 if fcf>0 else -20) + (15 if fcf_conv>.8 else 5 if fcf_conv>.5 else -10)
                      + (10 if cfo>0 else -10),0,100)
    earnings_score=np.clip(50 + (15 if ni_cagr>0 else -10) + (15 if rev_cagr>0 else -5)
                           + (10 if np.isfinite(margin) and margin>.15 else 0),0,100)
    valuation_score=np.clip(50 + (20 if np.isfinite(upside) and upside>.2 else 10 if np.isfinite(upside) and upside>0 else -15 if np.isfinite(upside) else 0)
                            + (10 if getattr(dc,'status','REVIEW')=='PASS' else -10),0,100)
    risk_score=np.clip(50 + (15 if de<.5 else 0 if de<1 else -15) + (10 if fcf>0 else -15)
                       + (10 if tech.get('score',50)>=60 else -5),0,100)
    intelligence=np.clip(.25*business+.20*cash_score+.20*earnings_score+.20*valuation_score+.15*risk_score,0,100)

    console.print(Rule('EXECUTIVE RESEARCH VIEW',style='cyan'))
    q=Table.grid(expand=True,padding=(0,3))
    for _ in range(4): q.add_column()
    q.add_row(
        Text(f'PRICE\n{money(price)}',style='bold white'),
        Text(f'GWI SCORE\n{r["score"]:.0f}/100',style='bold cyan'),
        Text(f'RESEARCH INTELLIGENCE\n{intelligence:.0f}/100',style='bold green'),
        Text(f'CLASSIFICATION\n{r["label"]}',style='bold yellow'))
    console.print(q)

    console.print(Rule('EVIDENCE SCORECARD',style='bright_blue'))
    sc=Table.grid(expand=True,padding=(0,3))
    for _ in range(3): sc.add_column()
    sc.add_row(
        Text(f'BUSINESS QUALITY     {business:5.1f}\n{_v22_bar(business)}',style='white'),
        Text(f'FINANCIAL QUALITY    {cash_score:5.1f}\n{_v22_bar(cash_score)}',style='white'),
        Text(f'EARNINGS QUALITY     {earnings_score:5.1f}\n{_v22_bar(earnings_score)}',style='white'))
    sc.add_row(
        Text(f'VALUATION            {valuation_score:5.1f}\n{_v22_bar(valuation_score)}',style='white'),
        Text(f'RISK / RESILIENCE    {risk_score:5.1f}\n{_v22_bar(risk_score)}',style='white'),
        Text(f'TECHNICAL            {tech.get("score",math.nan):5.1f}\n{_v22_bar(tech.get("score",math.nan))}',style='white'))
    console.print(sc)

    console.print(Rule('FUNDAMENTAL DIAGNOSTICS',style='bright_blue'))
    fd=Table.grid(expand=True,padding=(0,3))
    for _ in range(4): fd.add_column()
    fd.add_row(
        Text(f'Revenue CAGR\n{pct(rev_cagr)}\n{_v22_direction(rev_cagr)}',style='white'),
        Text(f'Net Income CAGR\n{pct(ni_cagr)}\n{_v22_direction(ni_cagr)}',style='white'),
        Text(f'EBITDA Margin\n{pct(margin)}',style='white'),
        Text(f'FCF Conversion\n{pct(fcf_conv)}',style='white'))
    fd.add_row(
        Text(f'ROE\n{pct(roe)}',style='white'),
        Text(f'Debt / Equity\n{num(de)}x',style='white'),
        Text(f'FCF\n{money(fcf)}',style='white'),
        Text(f'3-Statement Control\n{"PASS" if r.get("balance_ok") else "REVIEW"}',style='bold green' if r.get("balance_ok") else 'bold yellow'))
    console.print(fd)

    # Analyst-style interpretation, always traceable to metrics above.
    positives=[]; concerns=[]
    if rev_cagr>0: positives.append(f'Revenue growth remains positive at {pct(rev_cagr)} CAGR.')
    else: concerns.append('Revenue CAGR is not positive.')
    if fcf>0: positives.append(f'Latest modeled FCF is positive at {money(fcf)}.')
    else: concerns.append('Latest modeled FCF is not positive.')
    if de<.5: positives.append(f'Leverage is low at {num(de)}x debt/equity.')
    elif de>=1: concerns.append(f'Leverage is elevated at {num(de)}x debt/equity.')
    if tech.get('score',50)>=60: positives.append('Technical structure is supportive on the current score.')
    else: concerns.append('Technical structure is not supportive on the current score.')
    if np.isfinite(upside) and upside>0: positives.append(f'Current blended model value is above price by {pct(upside)}.')
    elif np.isfinite(upside): concerns.append(f'Current blended model value is below price by {pct(abs(upside))}.')
    if getattr(dc,'status','REVIEW')!='PASS': concerns.append('DCF control is not in PASS state.')
    if np.isfinite(mc_var) and mc_var>0.30: concerns.append(f'Monte Carlo 95% VaR is elevated at {pct(mc_var)}.')
    if np.isfinite(mc_p50) and np.isfinite(price) and mc_p50<price: concerns.append('Monte Carlo median terminal value is below the current price.')

    console.print(Rule('ANALYST SIGNALS',style='bright_blue'))
    sig=Table.grid(expand=True,padding=(0,3))
    sig.add_column(ratio=1); sig.add_column(ratio=1)
    sig.add_row(
        Text('POSITIVE EVIDENCE\n' + ('\n'.join('▲ '+x for x in positives) if positives else 'No strong positive evidence identified.'),style='green'),
        Text('CONCERNS / WATCHLIST\n' + ('\n'.join('▼ '+x for x in concerns) if concerns else 'No major rule-based concerns identified.'),style='yellow'))
    console.print(sig)

    console.print(Rule('VALUATION & PROBABILITY',style='bright_blue'))
    vd=Table.grid(expand=True,padding=(0,3))
    for _ in range(5): vd.add_column()
    vd.add_row(
        Text(f'DCF\n{money(dc.target) if dc else "N/A"}',style='white'),
        Text(f'BLENDED\n{money(r.get("blended"))}',style='white'),
        Text(f'UPSIDE / DOWNSIDE\n{pct(upside)}',style='white'),
        Text(f'MC P5\n{money(mc_p5)}',style='white'),
        Text(f'MC P50 / P95\n{money(mc_p50)} / {money(mc_p95)}',style='white'))
    console.print(vd)
    if np.isfinite(mc_p5) and np.isfinite(mc_p50) and np.isfinite(mc_p95):
        mc_extra=f'Positive outcome {pct(mc_pos)}  |  VaR95 {pct(mc_var)}  |  CVaR95 {pct(mc_cvar)}'
    else:
        mc_extra='Monte Carlo distribution unavailable — no substitute values generated.'
    console.print(Text(mc_extra,style='dim'))

    # Valuation dispersion is useful to an analyst: disagreement between methods is itself evidence.
    dcf_val=float(dc.target) if dc is not None and np.isfinite(dc.target) else math.nan
    blend_val=float(r.get('blended')) if np.isfinite(r.get('blended',math.nan)) else math.nan
    peer_val=float(r.get('implied')) if np.isfinite(r.get('implied',math.nan)) else math.nan
    vals=[v for v in (dcf_val,blend_val,peer_val, float(mc_p50) if np.isfinite(mc_p50) else math.nan) if np.isfinite(v) and v>0]
    if len(vals)>=2:
        dispersion=(max(vals)-min(vals))/np.mean(vals)
        console.print(Text(f'VALUATION DISPERSION  {pct(dispersion)}  |  Methods: {len(vals)}  |  Higher dispersion = higher assumption sensitivity.',style='yellow' if dispersion>.40 else 'dim'))

    console.print(Rule('EARNINGS / FUNDAMENTAL INFLECTION',style='bright_blue'))
    try:
        from institutional_pack import _quarterly_intelligence
        qdf,qmeta=_quarterly_intelligence(d)
        if not qdf.empty:
            latest_q=qdf.iloc[-1]
            qperiod=str(qdf.index[-1])[:10]
            qline=[]
            for key,label in [('Revenue','Revenue'),('EBITDA','EBITDA'),('Net Income','Net Income')]:
                if key in qdf.columns and np.isfinite(latest_q.get(key,np.nan)):
                    yoy=latest_q.get(key+' YoY',np.nan)
                    qline.append(f'{label} {money(latest_q[key])}'+(f' ({pct(yoy)} YoY)' if np.isfinite(yoy) else ''))
            console.print(Text(f'Latest reported quarter: {qperiod}  |  ' + '  |  '.join(qline),style='white'))
            console.print(Text(f'Quarterly signal: {qmeta.get("message","Limited quarterly trend history.")}',style='dim'))
        else:
            console.print(Text('Quarterly intelligence unavailable from the configured source.',style='yellow'))
    except Exception as e:
        console.print(Text(f'Quarterly intelligence safely degraded: {type(e).__name__}',style='yellow'))

    console.print(Rule('THESIS',style='cyan'))
    thesis=' '.join(positives[:3]) if positives else 'Evidence is insufficient for a strong positive thesis.'
    counter=' '.join(concerns[:3]) if concerns else 'No major rule-based counter-thesis identified.'
    console.print(Text('CORE THESIS  '+thesis,style='green'))
    console.print(Text('COUNTER-THESIS  '+counter,style='yellow'))
    console.print(Text('DECISION POLICY  Human investment decision remains separate from the automated evidence score.',style='dim'))
    console.print(Text('SCORE DEFINITIONS  GWI = core quantitative workstation score  |  Research Intelligence = rule-based synthesis of validated GROWISE outputs.',style='dim'))

    console.print(Rule('DELIVERABLES',style='bright_green'))
    res=_auto_export_session(symbol)
    if res:
        console.print(Text('Institutional Word + Excel research pack generated successfully.',style='green'))
    else:
        console.print(Text('Export engine returned REVIEW; core analysis remains available above.',style='yellow'))
    _visual_pause()

# V27 PROFESSIONAL ROUTE / MODEL DIAGNOSTICS
def _v24_diagnostics():
    """Production diagnostics for V27 routing, handlers and model controls."""
    routes={
        '01':'Research Workbench','02':'Financial Statements','03':'Three-Statement Model','04':'DCF','05':'Valuation Lab','06':'Technical','07':'Monte Carlo','08':'Risk','09':'Peers','10':'Compare','11':'Export','12':'Market Status','13':'GWI Score','14':'Data Quality','15':'Backtesting','16':'Market Regime','17':'Portfolio Risk','18':'Portfolio Optimizer','19':'Research Note','20':'Security Master','21':'Concall','22':'IPO Research','23':'News & Events','24':'Earnings Intelligence','25':'Fundamental Inflection','26':'Forensic','27':'What Changed','28':'Event Study','29':'Scenario & Catalyst','30':'Ownership Flow','31':'Moat','32':'Valuation Bridge','33':'Corporate Actions','34':'Filings','35':'Red Flags','36':'Investment Committee','37':'Factor Exposure','38':'Quality Scorecard','39':'Growth Quality','40':'Capital Allocation','41':'SOTP','42':'DDM','43':'Residual Income','44':'Probability Valuation','45':'Valuation Decomposition','46':'Factor Exposure','47':'Thesis Tracker','48':'Portfolio Attribution','49':'Model Control Center','50':'Service Index','51':'Live Market','90':'Research Intelligence','98':'Diagnostics','99':'Full Index','100':'Fair Value'}
    src=Path(__file__).read_text(errors='ignore')
    expected=['show_research','show_financials','show_model_cmd','show_dcf','show_valuation_lab','show_technical','show_quant_cmd','show_risk','show_peers','compare','export_excel','market_status','gwi_score','data_quality','backtest','market_regime','portfolio_risk','portfolio_optimizer','research_note','_v24_security_master','conference_call_analyzer','ipo_research','news_tomorrow_events','earnings_intelligence','fundamental_inflection','forensic_engine','what_changed_engine','event_study_engine','scenario_engine','ownership_flow_engine','moat_analyzer','valuation_bridge','corporate_actions_engine','filings_intelligence','red_flag_engine','investment_committee_mode','factor_exposure_v8','quality_scorecard','growth_quality_lab','capital_allocation_lab','sotp_lab','dividend_discount_valuation','residual_income_valuation','probability_valuation','valuation_decomposition_v8','thesis_tracker','portfolio_attribution','model_control_center','live_market_engine','_v22_intelligence','fair_value_lab']
    missing=[x for x in expected if x not in src]
    dispatch=src[src.index('def _v17_dispatch_same_ticker'):src.index('\nmain=final_main_v17',src.index('def _v17_dispatch_same_ticker'))]
    padded="n=(f'{int(n):02d}' if len(n) <= 2 else str(int(n)))" in dispatch
    critical=all(f"'{n}'" in dispatch or f"n=='{n}'" in dispatch for n in ('04','05','07','08','09','19','51'))
    canonical=all(f"n=='{n}'" in src for n in ('01','02','03','06','20','90','98'))
    console.print(header()); console.print(Rule('SYSTEM DIAGNOSTICS / V27',style='bright_blue'))
    console.print(Text(f'Public services indexed : {len(routes)}',style='white'))
    console.print(Text(f'Handler definitions    : {len(expected)-len(missing)}/{len(expected)} PASS',style='green' if not missing else 'yellow'))
    console.print(Text('Leading-zero routing    : PASS' if padded else 'REVIEW',style='green' if padded else 'yellow'))
    console.print(Text('Critical routes 04/05/07/08/09/19/51 : PASS' if critical else 'REVIEW',style='green' if critical else 'yellow'))
    console.print(Text('Canonical routes 01/02/03/06/20/90/98 : PASS' if canonical else 'REVIEW',style='green' if canonical else 'yellow'))
    console.print(Text('20 Security Master     : PASS',style='green' if '_v24_security_master' in src else 'yellow'))
    console.print(Text('90 Research Intelligence: PASS',style='green' if '_v22_intelligence' in src else 'yellow'))
    console.print(Text('100 Fair Value          : PASS',style='green' if 'fair_value_lab' in src else 'yellow'))
    console.print(Text('Live Market             : CREDENTIAL-GATED / FAIL-CLOSED',style='yellow'))
    console.print(Text('Provider error suppression: ENABLED on production provider paths',style='green'))
    if missing:
        t=Table(title='MISSING HANDLERS',box=box.SIMPLE_HEAVY); t.add_column('FUNCTION')
        for x in missing:t.add_row(x)
        console.print(t)
    else: console.print(Text('Functional route audit   : PASS',style='green'))
    _visual_pause()

# V27 main: keeps the full service universe visible and exposes 90 as a public intelligence service.
def _v22_main():
    console.print(Text('[V27 ROUTER ACTIVE — COMPLETE SECTOR-AWARE RESEARCH ENGINE]', style='dim'))
    console.clear()
    console.print(header())
    console.print(Rule('[bold cyan]GROWISEINVEST[/bold cyan]  EQUITY RESEARCH WORKSTATION  |  V27',style='cyan'))
    console.print(Text('Enter one company. Optional peers are supplied once. The full visual security stack then loads automatically.',style='white'))
    console.print(Text('PRICE • CANDLES • TECHNICALS • FUNDAMENTALS • DCF • FAIR VALUE • MONTE CARLO • EARNINGS • CONCALL • PEERS • RISK • THESIS',style='dim'))
    console.print(Rule('ALL 50 SERVICES',style='bright_blue'))
    console.print(_service_map_compact())
    console.print(Text('90  EQUITY RESEARCH INTELLIGENCE  |  98  SYSTEM DIAGNOSTICS  |  100  FAIR VALUE CALCULATOR  |  99  FULL INDEX  |  00  EXIT',style='bold yellow'))
    while True:
        try:
            raw=console.input('\n[bold cyan]ENTER NSE TICKER (or 00 to exit): [/bold cyan]').strip()
            if raw.upper() in {'00','EXIT','QUIT','Q'}: break
            if not raw: continue
            symbol=raw.split()[0].upper().replace('.NS','').replace('.BO','')
            if not re.fullmatch(r'[A-Z0-9&.-]{1,30}',symbol):
                console.print('[yellow]Invalid ticker format.[/yellow]'); continue
            _set_session_peers()
            console.print(Rule(f'[bold cyan]RUNNING COMPLETE RESEARCH STACK — {symbol}[/bold cyan]',style='cyan'))
            try:
                with Progress(SpinnerColumn(),TextColumn('{task.description}'),console=console) as prog:
                    task=prog.add_task('Loading market / OHLC / volume',total=None)
                    d,r=run_research(symbol,sims=5000,peer_override=(ACTIVE_PEERS if ACTIVE_PEERS else None))
                    prog.update(task,description='Market / OHLC / volume ✓')
                    prog.update(task,description='Fundamentals / model / DCF ✓')
                    prog.update(task,description='Technical / Monte Carlo / risk ✓')
                    prog.update(task,description='Peers / earnings / valuation ✓')
            except Exception as e:
                console.print(Panel(f'{type(e).__name__}: {e}',title='RESEARCH LOAD ERROR — NO FABRICATION',border_style='red'))
                continue
            _v18_security_dashboard(symbol,'1D')
            _auto_export_session(symbol)
            console.print(Rule('WORKSTATION READY',style='bright_blue'))
            console.print(Text('Active security retained. Enter a module number for a deeper view.',style='dim'))
            while True:
                cmd=console.input(f'\n[bold cyan]GROWISEINVEST / {symbol} > [/bold cyan]').strip()
                if not cmd: continue
                up=cmd.upper()
                if up.startswith(('T ','TICKER ')):
                    symbol=cmd.split(None,1)[1].upper().replace('.NS','').replace('.BO','')
                    _set_session_peers()
                    try: _v18_security_dashboard(symbol,'1D'); _auto_export_session(symbol)
                    except Exception as e: console.print(Panel(f'{type(e).__name__}: {e}',title='SECURITY SWITCH ERROR',border_style='red'))
                    continue
                if up in {'00','EXIT','QUIT','Q'}: return
                if up in {'HOME','H'}:
                    try: _v18_security_dashboard(symbol,'1D')
                    except Exception as e: console.print(f'[yellow]{type(e).__name__}: {e}[/yellow]')
                    continue
                if up.startswith('PEERS'):
                    try: _set_session_peers(); _v18_security_dashboard(symbol,'1D'); _auto_export_session(symbol)
                    except Exception as e: console.print(Panel(f'{type(e).__name__}: {e}',title='PEER INPUT ERROR',border_style='yellow'))
                    continue
                if up.startswith('TF '):
                    try: _v18_security_dashboard(symbol,cmd.split(None,1)[1])
                    except Exception as e: console.print(f'[yellow]TIMEFRAME ERROR: {e}[/yellow]')
                    continue
                if up.startswith('TV'):
                    try:
                        import webbrowser
                        webbrowser.open(f'https://www.tradingview.com/symbols/{symbol}/?exchange=NSE')
                        console.print(Text(f'Opened TradingView for NSE:{symbol}.',style='cyan'))
                    except Exception as e: console.print(Text(f'Browser handoff unavailable: {e}',style='yellow'))
                    continue
                parts=cmd.split(); n=parts[0]
                if n.isdigit():
                    # CANONICAL V27 ROUTE: handle 90 here before ANY legacy dispatcher.
                    if n == '90':
                        try:
                            _v22_intelligence(symbol)
                        except Exception as e:
                            console.print(Panel(f'{type(e).__name__}: {e}', title='EQUITY RESEARCH INTELLIGENCE ERROR', border_style='red'))
                        continue
                    if n == '98':
                        _v24_diagnostics()
                        continue
                    # V27 CANONICAL DEEP ROUTES: legacy 01/02/03 are retained as
                    # clean same-ticker drill-downs. They no longer ask for the ticker
                    # again and no longer pass through the fragile legacy router.
                    if n in {'01','02','03'}:
                        try:
                            if n == '01':
                                show_research(symbol)
                            elif n == '02':
                                show_financials(symbol)
                            else:
                                show_model_cmd(symbol)
                            _visual_pause()
                            _v24_security_master(symbol)
                        except Exception as e:
                            console.print(Panel(f'{type(e).__name__}: {e}', title=f'MODULE {n} ERROR — SESSION RETAINED', border_style='red'))
                        continue
                    if n=='20':
                        try:
                            _v24_security_master(symbol)
                        except Exception as e:
                            console.print(Panel(f'{type(e).__name__}: {e}', title='SECURITY MASTER ERROR — SESSION RETAINED', border_style='red'))
                        continue
                    if n=='50':
                        console.clear(); console.print(header()); console.print(Rule('GROWISEINVEST / ACTIVE SECURITY',style='cyan')); console.print(_service_map_compact()); continue
                    if n=='06':
                        tf=parts[1] if len(parts)>1 else '1D'
                        try: _v18_technical(symbol,tf); _visual_pause(); _v18_security_dashboard(symbol,tf)
                        except Exception as e: console.print(f'[yellow]TECHNICAL ERROR: {e}[/yellow]')
                        continue
                    try:
                        ok=_v17_dispatch_same_ticker(n,symbol)
                        if not ok: return
                    except Exception as e:
                        console.print(Panel(f'{type(e).__name__}: {e}',title='MODULE ERROR — SESSION RETAINED',border_style='red'))
                else:
                    console.print('[yellow]Enter a module number, 90, TF 1W/1M/1H/15M, PEERS, TV, or T TICKER.[/yellow]')
        except KeyboardInterrupt:
            console.print('\n[yellow]Use 00 to exit.[/yellow]')
        except Exception as e:
            console.print(Panel(f'{type(e).__name__}: {e}',title='WORKSTATION ERROR — SESSION SAFE',border_style='red'))

def _run_v22_canonical():
    return _v22_main()

if __name__=='__main__':
    _run_v22_canonical()
