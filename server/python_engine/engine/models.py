from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

ALIASES = {
    'revenue':['Total Revenue','Operating Revenue','Total Operating Income'],
    'ebit':['Operating Income','EBIT'],
    'ebitda':['EBITDA'],
    'net_income':['Net Income','Net Income Common Stockholders','Net Income Including Noncontrolling Interests'],
    'cfo':['Operating Cash Flow','Total Cash From Operating Activities','Cash Flow From Continuing Operating Activities'],
    'capex':['Capital Expenditure','Capital Expenditure Reported','Capital Expenditure Capitalized'],
    'cash':['Cash Cash Equivalents And Short Term Investments','Cash And Cash Equivalents','Cash Financial'],
    'debt':['Total Debt','Long Term Debt','Current Debt And Capital Lease Obligation'],
    'equity':['Stockholders Equity','Total Stockholder Equity','Common Stock Equity'],
    'assets':['Total Assets'], 'current_assets':['Current Assets'], 'current_liabilities':['Current Liabilities'],
    'interest':['Interest Expense Non Operating','Interest Expense'], 'tax':['Tax Provision'],
    'da':['Reconciled Depreciation','Depreciation And Amortization','Depreciation']}

def clean(v):
    try:
        if v is None or (isinstance(v,float) and np.isnan(v)): return 0.0
        return float(v)
    except Exception: return 0.0

def _norm(x): return ''.join(ch.lower() for ch in str(x) if ch.isalnum())

def stmt(df,key):
    if df is None or getattr(df,'empty',True): return pd.Series(dtype=float)
    wanted={_norm(x) for x in ALIASES.get(key,[key])}
    for idx in df.index:
        if _norm(idx) in wanted:
            row=pd.to_numeric(df.loc[idx],errors='coerce').dropna()
            if not row.empty: return row.astype(float)
    return pd.Series(dtype=float)

def latest(s): return clean(s.iloc[0]) if len(s) else 0.0

def cagr(s,n=3):
    """Chronology-safe CAGR for financial-provider series."""
    if s is None: return None
    x=pd.to_numeric(pd.Series(s),errors='coerce').dropna()
    if len(x)<2: return None
    try:
        idx=pd.to_datetime(x.index,errors='coerce')
        if idx.notna().all():
            x=x.copy(); x.index=idx; x=x.sort_index()
    except Exception:
        pass
    x=x.tail(min(n+1,len(x)))
    vals=x.tolist()
    if len(vals)<2 or vals[0]<=0 or vals[-1]<=0: return None
    return (vals[-1]/vals[0])**(1/(len(vals)-1))-1

def normalized_financials(income,balance,cashflow):
    out={}
    for key in ['revenue','ebit','ebitda','net_income','interest','tax']: out[key]=stmt(income,key)
    for key in ['cfo','capex','da']: out[key]=stmt(cashflow,key)
    for key in ['cash','debt','equity','assets','current_assets','current_liabilities']: out[key]=stmt(balance,key)
    if len(out['ebitda'])==0 and len(out['ebit']) and len(out['da']):
        idx=out['ebit'].index.intersection(out['da'].index); out['ebitda']=(out['ebit'].reindex(idx)+out['da'].reindex(idx)).dropna()
    if len(out['capex']): out['capex']=out['capex'].abs()
    if len(out['cfo']) and len(out['revenue']):
        keep=[]
        for idx,v in out['cfo'].items():
            rev=clean(out['revenue'].get(idx,0)); keep.append(not(rev>0 and abs(clean(v))>rev*1.75))
        out['cfo']=out['cfo'][keep]
    return out

@dataclass
class DCF:
    target:float; enterprise_value:float; equity_value:float; wacc:float; terminal_growth:float
    base_growth:float; reverse_growth:float|None; sensitivity:list; status:str; warning:str=''

def _fcff_forecast(fcf,growth,years=5):
    x=float(fcf); vals=[]
    for i in range(years):
        g=growth[i] if isinstance(growth,(list,tuple)) else growth; x*=1+g; vals.append(x)
    return vals

def dcf(price,fcf,debt,cash,beta=1.0,riskfree=.065,terminal_growth=.035,base_growth=.08,shares=1.0,analyst=None):
    analyst=analyst or {}; wacc=min(max(riskfree+max(beta,.1)*.06,.08),.16)
    if analyst.get('wacc') is not None: wacc=min(max(float(analyst['wacc']),.08),.16)
    tg=min(max(float(analyst.get('terminal_growth',terminal_growth)),.02),.06)
    g=min(max(float(analyst.get('growth',base_growth)),.02),.18)
    if fcf<=0:
        sens=[[math.nan]*5 for _ in range(5)]
        return DCF(math.nan,math.nan,math.nan,wacc,tg,g,None,sens,'REVIEW','Current normalized FCFF is non-positive; simple FCFF DCF suppressed.')
    growth_path=[max(.01,g-.0125*i) for i in range(5)]; fs=_fcff_forecast(fcf,growth_path)
    pv=sum(v/(1+wacc)**(i+1) for i,v in enumerate(fs)); tv=fs[-1]*(1+tg)/(wacc-tg)
    ev=pv+tv/(1+wacc)**5; eq=ev-debt+cash; target=eq/shares if shares else math.nan
    def value(gx,sw=wacc):
        ff=_fcff_forecast(fcf,gx,5); p=sum(v/(1+sw)**(i+1) for i,v in enumerate(ff)); tv2=ff[-1]*(1+tg)/(sw-tg)
        return (p+tv2/(1+sw)**5-debt+cash)/shares if shares else math.nan
    reverse=None
    if np.isfinite(target) and value(.30)>=price:
        lo,hi=0,.30
        for _ in range(80):
            mid=(lo+hi)/2
            if value(mid)<price: lo=mid
            else: hi=mid
        reverse=(lo+hi)/2
    gs=[.04,.06,.08,.10,.12]; ws=[.08,.10,.12,.14,.16]; sens=[]
    for sg in gs:
        row=[]
        for sw in ws:
            if sw<=tg: row.append(math.nan); continue
            ff=_fcff_forecast(fcf,sg,5); p=sum(v/(1+sw)**(i+1) for i,v in enumerate(ff)); tv2=ff[-1]*(1+tg)/(sw-tg)
            row.append((p+tv2/(1+sw)**5-debt+cash)/shares if shares else math.nan)
        sens.append(row)
    return DCF(target,ev,eq,wacc,tg,g,reverse,sens,'PASS')

def forecast_three_statement(hist,assumptions,years=5):
    last={k:latest(v) for k,v in hist.items()}; rg=assumptions['revenue_growth']; margin=assumptions['ebitda_margin']; tax=assumptions['tax_rate']; nwc_pct=assumptions['nwc_pct']; capex_pct=assumptions['capex_pct']; da_pct=assumptions['da_pct']; ir=assumptions['interest_rate']; payout=assumptions['payout']
    prev_rev=last['revenue']; prev_nwc=last['current_assets']-last['current_liabilities']; prev_debt=last['debt']; prev_cash=last['cash']; prev_equity=last['equity']; prev_ppe=max(0,last['assets']-last['current_assets']); rows=[]
    for i in range(1,years+1):
        revenue=prev_rev*(1+rg); ebitda=revenue*margin; da=revenue*da_pct; ebit=ebitda-da; interest=prev_debt*ir; ebt=ebit-interest; taxv=max(0,ebt*tax); net=max(0,ebt-taxv); nwc=revenue*nwc_pct; dnwc=nwc-prev_nwc; capex=revenue*capex_pct; cfo=net+da-dnwc; fcf=cfo-capex; div=max(0,net*payout); borrowing=0.0; cash_end=prev_cash+cfo-capex-div+borrowing; debt_end=prev_debt+borrowing; equity_end=prev_equity+net-div; ppe_end=prev_ppe+capex-da; assets=cash_end+nwc+ppe_end; liabilities=debt_end+nwc; other=assets-liabilities-equity_end; check=assets-(liabilities+equity_end+other)
        rows.append({'FY+%d'%i:i,'Revenue':revenue,'EBITDA':ebitda,'EBIT':ebit,'Interest':interest,'Tax':taxv,'Net Income':net,'CFO':cfo,'Capex':capex,'FCF':fcf,'Dividends':div,'Debt':debt_end,'Cash':cash_end,'Equity':equity_end,'Assets':assets,'Other Liabilities Bridge':other,'Balance Check':check})
        prev_rev,prev_nwc,prev_debt,prev_cash,prev_equity,prev_ppe=revenue,nwc,debt_end,cash_end,equity_end,ppe_end
    return pd.DataFrame(rows)

def monte_carlo(price,returns,sims=10000,horizon=252,seed=42):
    rng=np.random.default_rng(seed); r=np.asarray(pd.Series(returns).dropna(),float); mu=float(r.mean()); sig=float(r.std(ddof=1)); z=rng.normal(mu,sig,(3,sims,horizon)); paths=price*np.exp(np.cumsum(z,axis=2)); terminal=paths[:,:,-1].ravel(); ps=[1,5,10,25,50,75,90,95,99]; q5=np.percentile(terminal,5); tail=terminal[terminal<=q5]; maxdd=[]
    for mp in paths:
        peak=np.maximum.accumulate(mp,axis=1); maxdd.extend(np.min(mp/peak-1,axis=1))
    return {'percentiles':{f'P{p}':float(np.percentile(terminal,p)) for p in ps},'positive_prob':float((terminal>price).mean()),'gain20_prob':float((terminal>=price*1.2).mean()),'loss20_prob':float((terminal<=price*.8).mean()),'var95':float((price-q5)/price),'cvar95':float((price-np.mean(tail))/price),'avg_max_dd':float(np.mean(maxdd)),'paths':paths[0,:min(100,sims),:]}
