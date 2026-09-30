import sys, json, math, io, contextlib, traceback, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import GROWISEINVEST as G

MODULES = {
"01":"RESEARCH WORKFLOW","02":"FINANCIAL INTELLIGENCE","03":"3-STATEMENT MODEL",
"04":"DCF","05":"VALUATION LAB","06":"TECHNICAL ANALYSIS","07":"MONTE CARLO QUANT",
"08":"RISK ANALYTICS","09":"PEER COMPARABLES","10":"CROSS-COMPANY COMPARISON",
"11":"EXCEL EXPORT","12":"MARKET STATUS","13":"GWI SCORE","14":"DATA QUALITY",
"15":"BACKTEST","16":"MARKET REGIME","17":"PORTFOLIO RISK","18":"PORTFOLIO OPTIMIZER",
"19":"RESEARCH NOTE","20":"SECURITY MASTER","21":"CONFERENCE CALL ANALYZER",
"22":"IPO RESEARCH","23":"NEWS & TOMORROW EVENTS","24":"EARNINGS INTELLIGENCE",
"25":"FUNDAMENTAL INFLECTION","26":"EARNINGS QUALITY & FORENSIC","27":"WHAT CHANGED",
"28":"EVENT STUDY LAB","29":"SCENARIO & CATALYST LAB","30":"OWNERSHIP & INSTITUTIONAL FLOW",
"31":"MOAT ANALYZER","32":"VALUATION BRIDGE","33":"CORPORATE ACTION INTELLIGENCE",
"34":"REGULATORY & FILINGS INTELLIGENCE","35":"RED FLAG ENGINE","36":"INVESTMENT COMMITTEE MODE",
"37":"FACTOR EXPOSURE","38":"QUALITY SCORECARD","39":"GROWTH QUALITY LAB",
"40":"CAPITAL ALLOCATION LAB","41":"SUM-OF-THE-PARTS","42":"DIVIDEND DISCOUNT",
"43":"RESIDUAL INCOME","44":"PROBABILITY VALUATION","45":"VALUATION DECOMPOSITION",
"46":"FACTOR & STYLE","47":"THESIS TRACKER","48":"PORTFOLIO ATTRIBUTION",
"49":"MODEL CONTROL CENTER","50":"CLEAR TERMINAL","51":"LIVE MARKET",
"77":"ONE STOP TECHNICAL RESEARCH ENGINE","90":"EQUITY RESEARCH INTELLIGENCE","98":"SYSTEM DIAGNOSTICS","99":"FULL INDEX","100":"FAIR VALUE CALCULATOR"
}

FUNCTIONS = {
"01":"show_research","02":"show_financials","03":"show_model_cmd","04":"show_dcf",
"05":"show_valuation_lab","06":"show_technical","07":"show_quant_cmd","09":"show_peers",
"10":"compare","13":"gwi_score","14":"data_quality","15":"backtest","16":"market_regime",
"17":"portfolio_risk","18":"portfolio_optimizer","19":"research_note","20":"_v24_security_master",
"21":"conference_call_analyzer","22":"ipo_research","23":"news_tomorrow_events",
"24":"earnings_intelligence","25":"fundamental_inflection","26":"forensic_engine",
"27":"what_changed_engine","28":"event_study_engine","29":"scenario_engine",
"30":"ownership_flow_engine","31":"moat_analyzer","32":"valuation_bridge",
"33":"corporate_actions_engine","34":"filings_intelligence","35":"red_flag_engine",
"36":"investment_committee_mode","37":"factor_exposure_v8","38":"quality_scorecard",
"39":"growth_quality_lab","40":"capital_allocation_lab","41":"sotp_lab",
"42":"dividend_discount_valuation","43":"residual_income_valuation","44":"probability_valuation",
"45":"valuation_decomposition_v8","46":"factor_exposure_v8","47":"thesis_tracker",
"48":"portfolio_attribution","49":"model_control_center","51":"live_market_engine",
"77":"technical_research","90":"_v22_intelligence","100":"fair_value_lab"
}

def clean(x):
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try: return clean(x.item())
        except Exception: pass
    if isinstance(x, dict):
        return {str(k): clean(v) for k,v in x.items()}
    if isinstance(x, (list,tuple)):
        return [clean(v) for v in x]
    if hasattr(x, "to_dict"):
        try: return clean(x.to_dict(orient="records"))
        except Exception:
            try: return clean(x.to_dict())
            except Exception: pass
    return x

def analysis(symbol):
    d, r = G.run_research(symbol, sims=3000)
    c = d["history"].tail(220)
    tech = r["tech"]
    closes = d["close"].tail(220)
    dates = [str(x)[:10] for x in closes.index]
    prices = [float(x) for x in closes.values]
    # Additional chart indicators are derived from the same historical series for the UI.
    import pandas as pd, numpy as np
    s = pd.Series(prices, index=dates, dtype=float)
    ema20 = s.ewm(span=20, adjust=False).mean()
    ema50 = s.ewm(span=50, adjust=False).mean()
    ema200 = s.ewm(span=200, adjust=False).mean()
    mid = s.rolling(20).mean()
    std = s.rolling(20).std()
    upper = mid + 2*std
    lower = mid - 2*std
    delta=s.diff(); gain=delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    loss=delta.clip(upper=0).abs().ewm(alpha=1/14,adjust=False).mean()
    rs=gain/loss.replace(0,np.nan); rsi=100-(100/(1+rs))
    exp12=s.ewm(span=12,adjust=False).mean(); exp26=s.ewm(span=26,adjust=False).mean()
    macd=exp12-exp26; signal=macd.ewm(span=9,adjust=False).mean()
    hist=macd-signal
    chart=[]
    for i,dte in enumerate(dates):
        chart.append({"date":dte,"close":prices[i],"ema20":ema20.iloc[i],"ema50":ema50.iloc[i],
                      "ema200":ema200.iloc[i],"bbUpper":upper.iloc[i],"bbLower":lower.iloc[i],
                      "rsi":rsi.iloc[i],"macd":macd.iloc[i],"signal":signal.iloc[i],"hist":hist.iloc[i]})
    hs=d["financials"]
    def latest(k):
        try: return float(G.latest(hs[k]))
        except Exception: return None
    rev=latest("revenue"); ebitda=latest("ebitda"); ni=latest("net_income")
    eq=latest("equity"); debt=latest("debt"); cash=latest("cash"); cfo=latest("cfo"); capex=latest("capex")
    fcf=(cfo-capex) if cfo is not None and capex is not None else None
    roe=(ni/eq) if ni is not None and eq else None
    de=(debt/eq) if debt is not None and eq else None
    rev_c=G.cagr(hs["revenue"]); ni_c=G.cagr(hs["net_income"])
    dcf=r["dcf"]; mc=r["mc"]
    return clean({
      "ticker":d["ticker"], "company":r["info"].get("longName") or r["info"].get("shortName") or d["ticker"],
      "sector":r["info"].get("sector"), "industry":r["info"].get("industry"),
      "price":r["price"], "score":r["score"], "classification":r["label"],
      "fundamentalScore":r["fund_score"], "technicalScore":tech["score"],
      "technical":tech, "chart":chart,
      "fundamentals":{"revenue":rev,"ebitda":ebitda,"netIncome":ni,"fcf":fcf,"roe":roe,"de":de,"cash":cash,"debt":debt,
                     "revenueCagr":rev_c,"earningsCagr":ni_c,
                     "ebitdaMargin":(ebitda/rev if ebitda is not None and rev else None),
                     "fcfConversion":(fcf/cfo if fcf is not None and cfo else None)},
      "valuation":{"dcf":dcf.target,"peerImplied":r["implied"],"blended":r["blended"],"upside":r["upside"],
                   "status":dcf.status,"wacc":dcf.wacc,"terminalGrowth":dcf.terminal_growth,
                   "reverseGrowth":dcf.reverse_growth,"sensitivity":dcf.sensitivity},
      "monteCarlo":mc,
      "model":{"balanceOk":r["balance_ok"],"forecast":r["model"]},
      "peers":r["peer_rows"],"peerSource":r["peer_source"],
      "dataQuality":{"historyRows":len(d["history"]),"financialYears":len(hs["revenue"]),
                     "balanceCheck":"PASS" if r["balance_ok"] else "REVIEW"},
      "humanDecision":"System research output only. Final investment decision remains with the analyst."
    })


def technical_research(symbol):
    """Fast, self-contained technical research pipeline for the MERN UI.

    This route deliberately does NOT call the full fundamental/DCF V27 workflow.
    It fetches only the market history required for technical research, so a ticker
    search returns promptly and does not wait for unrelated V27 modules/providers.
    """
    import pandas as pd, numpy as np, requests
    from datetime import datetime, timezone, timedelta
    ticker = str(symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not ticker or not ticker.replace("&", "").replace("-", "").replace(".", "").isalnum():
        raise RuntimeError("Invalid NSE ticker")

    def yahoo_chart(symbol_yahoo, years=5, timeout=(4, 7)):
        # Direct Yahoo Chart API with explicit connect/read timeouts. This avoids
        # yfinance's slower metadata/quoteSummary calls which can hang on Windows.
        end = int(datetime.now(timezone.utc).timestamp())
        start = int((datetime.now(timezone.utc) - timedelta(days=365*years)).timestamp())
        urls = [
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_yahoo}?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true",
            f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol_yahoo}?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true"
        ]
        last=None
        for url in urls:
            try:
                rr=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=timeout)
                rr.raise_for_status()
                payload=rr.json()
                result=(payload.get("chart") or {}).get("result")
                if not result:
                    raise RuntimeError(((payload.get("chart") or {}).get("error") or {}).get("description") or "empty Yahoo response")
                r0=result[0]; ts=r0.get("timestamp") or []
                q=(r0.get("indicators") or {}).get("quote") or []
                if not ts or not q:
                    raise RuntimeError("Yahoo returned no OHLCV rows")
                q=q[0]
                n=min(len(ts),len(q.get("close") or []))
                rows={"Open":q.get("open",[])[:n],"High":q.get("high",[])[:n],"Low":q.get("low",[])[:n],"Close":q.get("close",[])[:n],"Volume":q.get("volume",[])[:n]}
                idx=pd.to_datetime(ts[:n],unit="s",utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
                df=pd.DataFrame(rows,index=idx)
                return df[~df.index.duplicated(keep="last")].sort_index()
            except Exception as exc:
                last=exc
        raise RuntimeError(f"Yahoo market data unavailable: {last}")

    ns=ticker+".NS"
    try:
        raw=yahoo_chart(ns,years=5)
    except Exception as exc:
        raise RuntimeError(f"Could not fetch NSE market data for {ticker}. {exc}")
    close=pd.to_numeric(raw.get("Close"),errors="coerce").dropna()
    if len(close) < 220:
        raise RuntimeError(f"Technical research requires at least 220 daily observations; {ticker} returned {len(close)}.")
    hist = raw.reindex(close.index)
    def col(name):
        if name in hist.columns:
            return pd.to_numeric(hist[name], errors="coerce").reindex(close.index).ffill()
        return pd.Series(index=close.index, dtype=float)
    high = col("High"); low = col("Low"); volume = col("Volume")
    if volume.isna().all(): volume = pd.Series(0.0, index=close.index)
    company_map = {
      "TCS":"Tata Consultancy Services Limited","INFY":"Infosys Limited","HCLTECH":"HCL Technologies Limited",
      "WIPRO":"Wipro Limited","TECHM":"Tech Mahindra Limited","LTIM":"LTIMindtree Limited",
      "RELIANCE":"Reliance Industries Limited","ONGC":"Oil and Natural Gas Corporation Limited",
      "NTPC":"NTPC Limited","POWERGRID":"Power Grid Corporation of India Limited","HDFCBANK":"HDFC Bank Limited",
      "ICICIBANK":"ICICI Bank Limited","SBIN":"State Bank of India","AXISBANK":"Axis Bank Limited",
      "KOTAKBANK":"Kotak Mahindra Bank Limited","ITC":"ITC Limited","HINDUNILVR":"Hindustan Unilever Limited",
      "NESTLEIND":"Nestle India Limited","MARUTI":"Maruti Suzuki India Limited","M&M":"Mahindra & Mahindra Limited",
      "TATAMOTORS":"Tata Motors Limited","SUNPHARMA":"Sun Pharmaceutical Industries Limited","DRREDDY":"Dr. Reddy's Laboratories Limited",
      "CIPLA":"Cipla Limited","DIVISLAB":"Divi's Laboratories Limited","APOLLOHOSP":"Apollo Hospitals Enterprise Limited",
      "LT":"Larsen & Toubro Limited","SIEMENS":"Siemens Limited","ABB":"ABB India Limited","BEL":"Bharat Electronics Limited",
      "HAL":"Hindustan Aeronautics Limited","TATASTEEL":"Tata Steel Limited","JSWSTEEL":"JSW Steel Limited",
      "HINDALCO":"Hindalco Industries Limited","ULTRACEMCO":"UltraTech Cement Limited","GRASIM":"Grasim Industries Limited"
    }
    sector_map = {
      "TCS":"Information Technology","INFY":"Information Technology","HCLTECH":"Information Technology","WIPRO":"Information Technology","TECHM":"Information Technology","LTIM":"Information Technology",
      "RELIANCE":"Oil & Gas","ONGC":"Oil & Gas","NTPC":"Power","POWERGRID":"Power","HDFCBANK":"Financial Services","ICICIBANK":"Financial Services","SBIN":"Financial Services","AXISBANK":"Financial Services","KOTAKBANK":"Financial Services",
      "ITC":"FMCG","HINDUNILVR":"FMCG","NESTLEIND":"FMCG","MARUTI":"Automobiles","M&M":"Automobiles","TATAMOTORS":"Automobiles","SUNPHARMA":"Healthcare","DRREDDY":"Healthcare","CIPLA":"Healthcare","DIVISLAB":"Healthcare","APOLLOHOSP":"Healthcare","LT":"Industrials","SIEMENS":"Industrials","ABB":"Industrials","BEL":"Defence Electronics","HAL":"Defence","TATASTEEL":"Metals","JSWSTEEL":"Metals","HINDALCO":"Metals","ULTRACEMCO":"Cement","GRASIM":"Diversified"
    }
    def ema(n): return close.ewm(span=n, adjust=False).mean()
    def sma(n): return close.rolling(n).mean()
    ema9, ema20, ema50, ema100, ema200 = [ema(n) for n in (9,20,50,100,200)]
    sma20, sma50, sma100, sma200 = [sma(n) for n in (20,50,100,200)]
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100/(1+rs))
    exp12, exp26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
    macd = exp12-exp26; macd_signal=macd.ewm(span=9,adjust=False).mean(); macd_hist=macd-macd_signal
    low14=low.rolling(14).min(); high14=high.rolling(14).max()
    stoch_k=100*(close-low14)/(high14-low14).replace(0,np.nan); stoch_d=stoch_k.rolling(3).mean()
    tr=pd.concat([(high-low),(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean(); atr_pct=atr/close
    mid=sma20; std=close.rolling(20).std(); bb_upper=mid+2*std; bb_lower=mid-2*std; bb_width=(bb_upper-bb_lower)/mid
    ret=close.pct_change().dropna(); hist_vol=float(ret.tail(252).std(ddof=1)*np.sqrt(252)) if len(ret)>2 else np.nan
    vol20=volume.rolling(20).mean(); vol50=volume.rolling(50).mean(); vol_ratio=volume/vol20.replace(0,np.nan)
    obv=(np.sign(close.diff()).fillna(0)*volume.fillna(0)).cumsum()
    # ADX / directional movement
    up=high.diff(); down=-low.diff(); plus_dm=up.where((up>down)&(up>0),0.0); minus_dm=down.where((down>up)&(down>0),0.0)
    atr14=atr.replace(0,np.nan)
    plus_di=100*plus_dm.rolling(14).mean()/atr14; minus_di=100*minus_dm.rolling(14).mean()/atr14
    dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan); adx=dx.rolling(14).mean()
    roc20=close.pct_change(20)
    # Market structure from local extrema.
    window=5
    swing_highs=[]; swing_lows=[]
    for i in range(window,len(close)-window):
        if close.iloc[i] == close.iloc[i-window:i+window+1].max(): swing_highs.append((close.index[i],float(close.iloc[i])))
        if close.iloc[i] == close.iloc[i-window:i+window+1].min(): swing_lows.append((close.index[i],float(close.iloc[i])))
    sh=swing_highs[-4:]; sl=swing_lows[-4:]
    recent_high=max([x[1] for x in sh],default=float(close.tail(60).max()))
    recent_low=min([x[1] for x in sl],default=float(close.tail(60).min()))
    current=float(close.iloc[-1])
    high52=float(close.tail(252).max()); low52=float(close.tail(252).min())
    resistance_levels=sorted(set([round(recent_high,2),round(high52,2),round(float(sma50.iloc[-1]),2)]),reverse=True)[:3]
    support_levels=sorted(set([round(recent_low,2),round(low52,2),round(float(sma50.iloc[-1]),2)]),reverse=True)[:3]
    resistance=[x for x in resistance_levels if x>current] or [round(high52,2)]
    support=[x for x in support_levels if x<current] or [round(low52,2)]
    r1=min(resistance); s1=max(support)
    # Trend / signals.
    trend_score=0
    for a,b in [(current,ema20.iloc[-1]),(current,ema50.iloc[-1]),(current,ema200.iloc[-1]),(ema20.iloc[-1],ema50.iloc[-1]),(ema50.iloc[-1],ema200.iloc[-1])]: trend_score += 1 if a>b else 0
    trend_score=round(trend_score/5*100,1)
    momentum_score=round(np.clip((float(rsi.iloc[-1])-30)/40*70 + (20 if macd_hist.iloc[-1]>0 else 0),0,100),1)
    volume_score=round(float(np.clip((vol_ratio.iloc[-1]-0.5)/1.5*100,0,100)),1)
    vol_score=round(float(np.clip(100-(float(atr_pct.iloc[-1])*100-1)*18,0,100)),1)
    structure_score=round(float(np.clip(50 + (20 if current>ema200.iloc[-1] else -15) + (15 if current>ema50.iloc[-1] else -10),0,100)),1)
    # Relative strength vs NIFTY 50.
    # Fetch NIFTY 50 once and reuse it for relative strength and regime.
    # Keeping this as one optional dependency prevents the technical report from
    # hanging when Yahoo is slow or temporarily blocks the index endpoint.
    nifty_close = None
    try:
        nifty_close = yahoo_chart("%5ENSEI",years=2)["Close"].dropna()
    except Exception:
        nifty_close = None

    rs_metrics={}
    try:
        idx=nifty_close
        if idx is None or len(idx) < 30:
            raise RuntimeError("NIFTY 50 history unavailable")
        common=pd.concat([close.rename("stock"),idx.rename("index")],axis=1).dropna()
        for days,label in [(21,"1M"),(63,"3M"),(126,"6M"),(252,"1Y")]:
            if len(common)>days:
                sr=float(common.stock.iloc[-1]/common.stock.iloc[-days-1]-1); ir=float(common.index.iloc[-1]/common.index.iloc[-days-1]-1)
                rs_metrics[label]={"stock":sr,"nifty":ir,"relative":sr-ir}
        rr=common.pct_change().dropna(); rs_metrics["beta"]=float(rr.stock.cov(rr.index)/rr.index.var()) if rr.index.var()>0 else None
        rs_metrics["correlation"]=float(rr.stock.corr(rr.index))
    except Exception:
        pass
    relative_score=50
    if rs_metrics.get("3M"): relative_score=float(np.clip(50+rs_metrics["3M"]["relative"]*500,0,100))
    technical_score=round(.25*trend_score+.20*momentum_score+.15*volume_score+.10*vol_score+.20*structure_score+.10*relative_score,1)
    # Divergence: compare last 40-day price and RSI slopes.
    div="NONE"
    try:
        p_old,p_new=float(close.iloc[-40]),float(close.iloc[-1]); r_old,r_new=float(rsi.iloc[-40]),float(rsi.iloc[-1])
        if p_new<p_old and r_new>r_old+2: div="BULLISH RSI DIVERGENCE"
        elif p_new>p_old and r_new<r_old-2: div="BEARISH RSI DIVERGENCE"
    except Exception: pass
    # Breakout state.
    prior20=float(close.iloc[-21:-1].max()) if len(close)>22 else high52
    prior20low=float(close.iloc[-21:-1].min()) if len(close)>22 else low52
    vr=float(vol_ratio.iloc[-1]) if np.isfinite(vol_ratio.iloc[-1]) else 0
    if current>prior20 and vr>=1.2: breakout="CONFIRMED BREAKOUT"
    elif current>prior20: breakout="BREAKOUT WATCH"
    elif current<prior20low and vr>=1.2: breakout="CONFIRMED BREAKDOWN"
    elif current<prior20low: breakout="BREAKDOWN WATCH"
    else: breakout="RANGE / NO BREAKOUT"
    # Multi-timeframe using resampling of the same daily data where available.
    mtf={}
    for rule,label in [("W","1W"),("ME","1M")]:
        try:
            ctf=close.resample(rule).last().dropna(); e20=ctf.ewm(span=20,adjust=False).mean(); e50=ctf.ewm(span=50,adjust=False).mean()
            mtf[label]={"price":float(ctf.iloc[-1]),"ema20":float(e20.iloc[-1]),"ema50":float(e50.iloc[-1]),"trend":"UP" if ctf.iloc[-1]>e20.iloc[-1]>e50.iloc[-1] else "DOWN" if ctf.iloc[-1]<e20.iloc[-1]<e50.iloc[-1] else "MIXED"}
        except Exception: pass
    mtf["1D"]={"price":current,"ema20":float(ema20.iloc[-1]),"ema50":float(ema50.iloc[-1]),"trend":"UP" if current>ema20.iloc[-1]>ema50.iloc[-1] else "DOWN" if current<ema20.iloc[-1]<ema50.iloc[-1] else "MIXED"}
    # Market regime from NIFTY 50.
    regime="UNAVAILABLE"
    try:
        idx=nifty_close
        if idx is None or len(idx) < 200:
            raise RuntimeError("NIFTY 50 history unavailable")
        e50=idx.rolling(50).mean().iloc[-1]; e200=idx.rolling(200).mean().iloc[-1]
        regime="BULL" if idx.iloc[-1]>e200 and e50>e200 else "BEAR" if idx.iloc[-1]<e200 and e50<e200 else "TRANSITION"
    except Exception: pass
    # Simple historical trend backtest using existing project methodology.
    bt={}
    if len(close)>=504:
        rts=close.pct_change().dropna().tail(min(len(close)-1,1260)); s50=close.rolling(50).mean(); s200=close.rolling(200).mean(); sig=(s50>s200).astype(float).reindex(rts.index).fillna(0); pos=sig.shift(1).fillna(0); strat=pos*rts; eq=(1+strat).cumprod(); bh=(1+rts).cumprod(); years=len(strat)/252
        bt={"strategyCAGR":float(eq.iloc[-1]**(1/years)-1) if years and eq.iloc[-1]>0 else None,"buyHoldCAGR":float(bh.iloc[-1]**(1/years)-1) if years and bh.iloc[-1]>0 else None,"maxDrawdown":float((eq/eq.cummax()-1).min()),"trades":int(pos.diff().abs().fillna(pos.abs()).gt(0).sum()),"strategy":"50/200 DMA long/cash"}
    # Events.
    events=[]
    if current>ema20.iloc[-1]: events.append("Price above EMA20")
    if ema20.iloc[-1]>ema50.iloc[-1]: events.append("EMA20 above EMA50")
    if macd_hist.iloc[-1]>0: events.append("MACD histogram positive")
    if float(rsi.iloc[-1])>70: events.append("RSI overbought")
    elif float(rsi.iloc[-1])<30: events.append("RSI oversold")
    if vr>=1.5: events.append("Volume spike")
    if breakout.startswith("CONFIRMED"): events.append(breakout)
    thesis=[]
    if trend_score>=60: thesis.append("Trend structure is constructive")
    else: thesis.append("Trend structure is mixed or weak")
    if momentum_score>=60: thesis.append("Momentum is supportive")
    else: thesis.append("Momentum confirmation is limited")
    if vr>=1.2: thesis.append("Volume is providing confirmation")
    if current<r1: thesis.append(f"Resistance remains near {r1:.2f}")
    thesis_text=". ".join(thesis)+". Historical indicators require analyst review."
    # Chart data, last 260 points.
    tail=close.tail(260); chart=[]
    for dt in tail.index:
        i=close.index.get_loc(dt)
        chart.append({"date":str(dt)[:10],"close":float(close.iloc[i]),"ema20":float(ema20.iloc[i]),"ema50":float(ema50.iloc[i]),"ema200":float(ema200.iloc[i]) if np.isfinite(ema200.iloc[i]) else None,"bbUpper":float(bb_upper.iloc[i]) if np.isfinite(bb_upper.iloc[i]) else None,"bbLower":float(bb_lower.iloc[i]) if np.isfinite(bb_lower.iloc[i]) else None,"rsi":float(rsi.iloc[i]) if np.isfinite(rsi.iloc[i]) else None,"volume":float(volume.iloc[i]) if np.isfinite(volume.iloc[i]) else None,"volRatio":float(vol_ratio.iloc[i]) if np.isfinite(vol_ratio.iloc[i]) else None})
    return clean({"ticker":ticker,"company":company_map.get(ticker,ticker),"sector":sector_map.get(ticker,"N/A"),"industry":"N/A","price":current,"asOf":str(close.index[-1])[:19],"pipeline":["Market Data","Trend","Momentum","Volume","Volatility","Market Structure","Support / Resistance","Breakout","Divergence","Multi-Timeframe","Relative Strength","Market / Sector Regime","Technical Events","Backtesting","Technical Risk","Technical Score","Technical Thesis","PDF / Excel / Word / Charts"],"dataQuality":{"historyRows":len(close),"status":"PASS" if len(close)>=252 else "REVIEW"},"trend":{"ema20":float(ema20.iloc[-1]),"ema50":float(ema50.iloc[-1]),"ema200":float(ema200.iloc[-1]),"sma20":float(sma20.iloc[-1]),"sma50":float(sma50.iloc[-1]),"sma200":float(sma200.iloc[-1]),"score":trend_score},"momentum":{"rsi":float(rsi.iloc[-1]),"macd":float(macd.iloc[-1]),"signal":float(macd_signal.iloc[-1]),"histogram":float(macd_hist.iloc[-1]),"roc20":float(roc20.iloc[-1]),"stochastic":float(stoch_k.iloc[-1]),"score":momentum_score},"volume":{"current":float(volume.iloc[-1]),"average20":float(vol20.iloc[-1]),"ratio":vr,"obvTrend":"RISING" if obv.iloc[-1]>obv.iloc[-21] else "FALLING","score":volume_score},"volatility":{"atr":float(atr.iloc[-1]),"atrPct":float(atr_pct.iloc[-1]),"bbWidth":float(bb_width.iloc[-1]),"historicalVolatility":hist_vol,"score":vol_score},"structure":{"swingHigh":recent_high,"swingLow":recent_low,"high52":high52,"low52":low52,"support":s1,"resistance":r1,"score":structure_score},"breakout":breakout,"divergence":div,"multiTimeframe":mtf,"relativeStrength":rs_metrics,"marketRegime":regime,"events":events,"backtest":bt,"technicalRisk":{"atrPct":float(atr_pct.iloc[-1]),"supportDistance":float(current/s1-1) if s1 else None,"resistanceDistance":float(r1/current-1) if current else None},"technicalScore":technical_score,"technicalState":"CONSTRUCTIVE" if technical_score>=65 else "MIXED" if technical_score>=45 else "WEAK","thesis":thesis_text,"chart":chart,"humanDecision":"Technical research output only. Final investment decision remains with the analyst."})

def technical_pack(symbol):
    """Create a lightweight technical-only Excel, Word and chart pack."""
    import os, tempfile
    from datetime import datetime
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from openpyxl import Workbook
    from docx import Document
    from docx.shared import Inches
    d = technical_research(symbol)
    ticker = d["ticker"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = Path(tempfile.mkdtemp(prefix=f"GROWISE_{ticker}_TECH_"))
    chart_path = outdir / f"{ticker}_technical_chart.png"
    df = pd.DataFrame(d["chart"])
    df["date"] = pd.to_datetime(df["date"])
    fig, ax = plt.subplots(figsize=(12,5))
    ax.plot(df["date"], df["close"], label="Close")
    ax.plot(df["date"], df["ema20"], label="EMA 20")
    ax.plot(df["date"], df["ema50"], label="EMA 50")
    ax.plot(df["date"], df["ema200"], label="EMA 200")
    ax.set_title(f"{ticker} Technical Research")
    ax.grid(True, alpha=.2); ax.legend(); fig.tight_layout(); fig.savefig(chart_path, dpi=160); plt.close(fig)
    xlsx_path=outdir/f"GROWISEINVEST_{ticker}_Technical_Research.xlsx"
    wb=Workbook(); ws=wb.active; ws.title="Summary"
    rows=[
      ("Ticker",ticker),("Company",d["company"]),("Sector",d["sector"]),("Price",d["price"]),("As Of",d["asOf"]),
      ("Technical Score",d["technicalScore"]),("Technical State",d["technicalState"]),("Breakout",d["breakout"]),("Divergence",d["divergence"]),("Market Regime",d["marketRegime"]),
      ("Support",d["structure"]["support"]),("Resistance",d["structure"]["resistance"]),("RSI",d["momentum"]["rsi"]),("Volume Ratio",d["volume"]["ratio"]),("ATR %",d["volatility"]["atrPct"])
    ]
    for r in rows: ws.append(r)
    for section, obj in [("Trend",d["trend"]),("Momentum",d["momentum"]),("Volume",d["volume"]),("Volatility",d["volatility"]),("Structure",d["structure"]),("Risk",d["technicalRisk"]),("Backtest",d["backtest"] if d["backtest"] else {"status":"Insufficient history"})]:
        sh=wb.create_sheet(section[:31]); sh.append(["Metric","Value"])
        for k,v in obj.items(): sh.append([k,v])
    ch=wb.create_sheet("Chart Data");
    for row in [list(df.columns)]+df.where(pd.notnull(df),None).values.tolist(): ch.append(row)
    wb.save(xlsx_path)
    doc=Document(); doc.add_heading("GROWISE INVEST",0); doc.add_paragraph("ONE STOP TECHNICAL RESEARCH ENGINE")
    doc.add_heading(f"{ticker} | {d['company']}",1); doc.add_paragraph(f"{d['sector']} | Data as of {d['asOf']}")
    for title, obj in [("Technical Summary", {"Technical Score":d["technicalScore"],"State":d["technicalState"],"Breakout":d["breakout"],"Divergence":d["divergence"],"Market Regime":d["marketRegime"]}), ("Trend",d["trend"]),("Momentum",d["momentum"]),("Volume",d["volume"]),("Volatility",d["volatility"]),("Market Structure",d["structure"]),("Relative Strength",d["relativeStrength"]),("Backtesting",d["backtest"]),("Technical Risk",d["technicalRisk"])]:
        doc.add_heading(title,1); table=doc.add_table(rows=1, cols=2); table.style="Table Grid"; table.rows[0].cells[0].text="Metric"; table.rows[0].cells[1].text="Value"
        if obj:
            for k,v in obj.items():
                cells=table.add_row().cells; cells[0].text=str(k); cells[1].text=str(v)
    doc.add_heading("Technical Thesis",1); doc.add_paragraph(d["thesis"]); doc.add_picture(str(chart_path),width=Inches(6.7)); doc.add_paragraph(d["humanDecision"])
    docx_path=outdir/f"GROWISEINVEST_{ticker}_Technical_Research.docx"; doc.save(docx_path)
    return {"excel":str(xlsx_path),"word":str(docx_path),"charts":[str(chart_path)],"directory":str(outdir)}

def module_output(symbol, mid):
    mid = f"{int(str(mid)):02d}" if str(mid).isdigit() and len(str(mid)) <= 2 else str(mid)
    if mid == "77":
        result=technical_research(symbol)
        return {"module":mid,"title":MODULES[mid],"output":result}
    if mid == "98":
        fn=getattr(G,"_v24_diagnostics",None)
        if fn:
            with G.console.capture() as cap: fn()
            return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid == "12":
        with G.console.capture() as cap: G.market_status()
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid == "50":
        return {"module":mid,"title":MODULES[mid],"output":"Terminal clear requested. The MERN workstation keeps the current research session intact."}
    if mid == "99":
        return {"module":mid,"title":MODULES[mid],"output":"GROWISEINVEST V27 FULL INDEX\n\n"+ "\n".join(f"{k}  {v}" for k,v in MODULES.items())}
    if mid == "08":
        _,r=G.run_research(symbol,sims=3000)
        with G.console.capture() as cap: G.show_risk(r)
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid in ("17","18","48"):
        fn=getattr(G, FUNCTIONS[mid])
        with G.console.capture() as cap: fn([symbol])
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid == "10":
        fn=getattr(G, FUNCTIONS[mid])
        with G.console.capture() as cap: fn([symbol])
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid == "22":
        fn=getattr(G, FUNCTIONS[mid])
        with G.console.capture() as cap: fn(symbol)
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid == "23":
        fn=getattr(G, FUNCTIONS[mid])
        with G.console.capture() as cap: fn()
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    if mid in FUNCTIONS:
        fn=getattr(G, FUNCTIONS[mid])
        with G.console.capture() as cap: fn(symbol)
        return {"module":mid,"title":MODULES[mid],"output":cap.get()}
    return {"module":mid,"title":MODULES.get(mid,"MODULE"),"output":"This V27 route is preserved in the index. The original terminal implementation remains available in the bundled engine; no unsupported market data is fabricated in the web UI."}

def pack(symbol):
    from institutional_pack import generate_institutional_pack
    res=generate_institutional_pack(symbol,G.run_research,G.fetch,sims=3000)
    return clean(res)

def main():
    try:
        req=json.loads(sys.stdin.read() or "{}")
        op=req.get("op","analysis")
        symbol=req.get("ticker","TCS")
        if op=="analysis":
            out=analysis(symbol)
        elif op=="technical_research":
            out=technical_research(symbol)
        elif op=="module":
            out=module_output(symbol,req.get("module","01"))
        elif op=="pack":
            out=pack(symbol)
        elif op=="technical_pack":
            out=technical_pack(symbol)
        elif op=="selftest":
            # Lightweight import + model checks.
            import numpy as np, pandas as pd
            idx=pd.Index(["Y1","Y2","Y3","Y4","Y5"])
            raw={"revenue":[100,110,121,133,146],"ebitda":[20,22,24,27,30],"net_income":[10,11,12,13,15],
                 "cfo":[14,15,16,18,20],"capex":[5,6,6,7,8],"cash":[20,21,22,23,24],"debt":[10,9,8,7,6],
                 "equity":[50,55,60,66,72],"assets":[80,85,90,96,102],"current_assets":[30,32,34,36,38],
                 "current_liabilities":[15,15,16,17,18],"ebit":[18,20,22,24,27],"da":[2,2,2,3,3],
                 "interest":[1,1,1,1,1],"tax":[2,2,2,3,3]}
            hist={k:pd.Series(v,index=idx,dtype=float) for k,v in raw.items()}
            a={"revenue_growth":.10,"ebitda_margin":.20,"tax_rate":.25,"nwc_pct":.05,"capex_pct":.06,"da_pct":.035,"interest_rate":.07,"payout":.25}
            model=G.forecast_three_statement(hist,a,5)
            dc=G.dcf(100,12,6,24,shares=10)
            mc=G.monte_carlo(100,pd.Series(np.random.default_rng(42).normal(0,.02,500)),100,20,42)
            out={"status":"PASS","balanceResidual":float(model["Balance Check"].abs().max()),"dcfTarget":dc.target,"mcP50":mc["percentiles"]["P50"]}
        else:
            raise ValueError("Unknown operation")
        print(json.dumps(clean(out),separators=(",",":")))
    except Exception as e:
        print(json.dumps({"status":"ERROR","error":str(e),"type":type(e).__name__},separators=(",",":")))

if __name__=="__main__":
    main()
