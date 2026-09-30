import React, {useEffect, useMemo, useState} from "react";
import {createRoot} from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API || "http://localhost:5000";
const PIPELINE = [
  ["Market Data","PRICE • OHLCV • HISTORY"],
  ["Trend","EMA • SMA • TREND STRUCTURE"],
  ["Momentum","RSI • MACD • ROC • STOCHASTIC"],
  ["Volume","VOLUME RATIO • OBV • CONFIRMATION"],
  ["Volatility","ATR • BB WIDTH • HISTORICAL VOL"],
  ["Market Structure","SWINGS • 52W HIGH/LOW"],
  ["Support / Resistance","KEY TECHNICAL LEVELS"],
  ["Breakout","BREAKOUT • BREAKDOWN • RETEST"],
  ["Divergence","PRICE • RSI DIVERGENCE"],
  ["Multi-Timeframe","1D • 1W • 1M"],
  ["Relative Strength","STOCK vs NIFTY 50"],
  ["Market / Sector Regime","MARKET CONTEXT"],
  ["Technical Events","CROSSOVERS • SPIKES • SIGNALS"],
  ["Backtesting","50/200 DMA HISTORICAL TEST"],
  ["Technical Risk","ATR • SUPPORT DISTANCE"],
  ["Technical Score","TRANSPARENT SCORECARD"],
  ["Technical Thesis","RESEARCH INTERPRETATION"],
  ["PDF / Excel / Word / Charts","DOWNLOADABLE OUTPUT"]
];

const fmt=(v,d=2)=>v==null||Number.isNaN(Number(v))?"N/A":Number(v).toLocaleString("en-IN",{maximumFractionDigits:d});
const pct=v=>v==null||Number.isNaN(Number(v))?"N/A":`${(Number(v)*100).toFixed(2)}%`;
const money=v=>v==null?"N/A":`₹${fmt(v,2)}`;

function App(){
  const [query,setQuery]=useState("TCS"),[suggest,setSuggest]=useState([]),[data,setData]=useState(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState("");
  const [download,setDownload]=useState("");
  const [watch,setWatch]=useState([]);
  const [progress,setProgress]=useState(0);
  const [scrollDir,setScrollDir]=useState("up");

  useEffect(()=>{
    let last=window.scrollY;
    const onScroll=()=>{
      const now=window.scrollY;
      const dir=now>last?"down":"up";
      document.documentElement.style.setProperty("--scroll-shift", `${Math.min(Math.abs(now-last)*0.22, 18)}px`);
      document.documentElement.dataset.scrollDir=dir;
      setScrollDir(dir);
      last=now;
    };
    window.addEventListener("scroll",onScroll,{passive:true});
    return()=>window.removeEventListener("scroll",onScroll);
  },[]);

  useEffect(()=>{fetch(`${API}/api/watchlist`).then(r=>r.json()).then(setWatch).catch(()=>{});},[]);
  useEffect(()=>{
    const q=query.trim();
    if(!q){setSuggest([]);return;}
    const id=setTimeout(()=>fetch(`${API}/api/search?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(setSuggest).catch(()=>setSuggest([])),180);
    return()=>clearTimeout(id);
  },[query]);

  useEffect(()=>{
    if(!loading)return;
    setProgress(1);
    const id=setInterval(()=>setProgress(p=>p<PIPELINE.length?p+1:p),700);
    return()=>clearInterval(id);
  },[loading]);

  async function research(sym=query){
    const t=String(sym||"").trim().toUpperCase(); if(!t)return;
    setLoading(true);setError("");setSuggest([]);setData(null);setProgress(0);
    try{
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 32000);
      let r;
      try {
        r = await fetch(`${API}/api/technical-research/${encodeURIComponent(t)}`, {signal: controller.signal});
      } catch (err) {
        if (err.name === "AbortError") throw new Error("Research timed out. The market-data provider did not respond in time.");
        throw err;
      } finally { clearTimeout(timeout); }
      const j=await r.json();
      if(!r.ok)throw new Error(j.error||"Technical research failed");
      setData(j);setQuery(j.ticker.replace(".NS",""));
    }catch(e){setError(e.message)}finally{setLoading(false);setProgress(0)}
  }
  function go(url,label){setDownload(label);window.location.href=url;setTimeout(()=>setDownload(""),1500)}
  async function addWatch(){
    if(!data)return;
    const t=data.ticker.replace(".NS","");
    const r=await fetch(`${API}/api/watchlist`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ticker:t,company:data.company})});
    if(r.ok)setWatch([await r.json(),...watch.filter(x=>x.ticker!==t)]);
  }
  const chart=data?.chart||[];
  const max=Math.max(...chart.map(x=>x.close).filter(Number.isFinite),1), min=Math.min(...chart.map(x=>x.close).filter(Number.isFinite),0), range=max-min||1;
  const points=chart.map((x,i)=>`${(i/(Math.max(chart.length-1,1))*100).toFixed(2)},${(100-(x.close-min)/range*90-5).toFixed(2)}`).join(" ");
  return <div className="app">
    <header className="topbar">
      <div className="brand"><div className="brandmark">G</div><div><strong>GROWISE INVEST</strong><span>Your One-Stop Investment House</span></div></div>
      <div className="searchWrap">
        <div className="searchBox"><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>e.key==="Enter"&&research()} placeholder="Search NSE ticker or company"/><button onClick={()=>research()}>RESEARCH</button></div>
        {suggest.length>0&&<div className="suggestions">{suggest.map(s=><button key={s.ticker} onClick={()=>research(s.ticker)}><b>{s.ticker}</b><span>{s.company}</span><small>{s.sector}</small></button>)}</div>}
      </div>
      <div className="engineStatus"><i/> TECHNICAL RESEARCH</div>
    </header>

    <div className={`marketScenery ${scrollDir}`} aria-hidden="true">
      <div className="sceneryGrid"/>
      <svg viewBox="0 0 1600 520" preserveAspectRatio="none">
        <defs>
          <linearGradient id="lineGlow" x1="0" x2="1">
            <stop offset="0" stopColor="#123c7a" stopOpacity="0.10"/>
            <stop offset="0.45" stopColor="#1976ff" stopOpacity="0.85"/>
            <stop offset="1" stopColor="#123c7a" stopOpacity="0.12"/>
          </linearGradient>
          <filter id="softGlow"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        <path className="marketLine faint" d="M0 390 C100 340 130 410 220 350 S360 250 440 320 S560 380 650 250 S800 170 890 250 S1030 340 1120 210 S1250 120 1330 230 S1460 330 1600 170"/>
        <path className="marketLine" d="M0 430 L85 400 L145 420 L210 350 L275 365 L330 300 L390 330 L455 270 L520 315 L590 235 L655 260 L720 190 L785 250 L850 205 L915 285 L985 220 L1050 160 L1120 205 L1185 125 L1250 190 L1320 105 L1390 175 L1460 125 L1530 160 L1600 90"/>
      </svg>
    </div>

    <main className="main">
      <section className="macroStrip glass">
        <div className="macroIntro"><span className="eyebrow">RBI • BANKING FRAMEWORK</span><h2>Policy & Reserve Rates</h2><small>Structural banking indicators • updated periodically, not intraday market quotes</small></div>
        <div className="macroCards">
          {[
            ["Repo Rate","5.25%","RBI Policy Rate"],["SDF","5.00%","Standing Deposit Facility"],["MSF","5.50%","Marginal Standing Facility"],["Bank Rate","5.50%","RBI Bank Rate"],["Fixed Reverse Repo","3.35%","Liquidity absorption tool"],["CRR","3.00%","Cash Reserve Ratio"],["SLR","18.00%","Statutory Liquidity Ratio"]
          ].map(([n,v,d])=><div className="macroCard glassInner" key={n}><span>{n}</span><strong>{v}</strong><small>{d}</small></div>)}
        </div>
        <div className="macroSource">Source: Reserve Bank of India • rate panel verified against RBI published data (11 Sep 2026).</div>
      </section>
      {error&&<div className="error">{error}</div>}
      {!data&&!loading&&<section className="landing">
        <div className="eyebrow">GROWISEINVEST TECHNICAL RESEARCH WORKSTATION</div>
        <h1>Search a ticker.<br/><span>Get the complete technical research.</span></h1>
        <p>One search automatically runs the full technical workflow and prepares a downloadable research report.</p>
        <div className="quick">{["TCS","INFY","RELIANCE","HDFCBANK"].map(t=><button key={t} onClick={()=>research(t)}>{t}</button>)}</div>
      </section>}
      {loading&&<section className="loadingPanel"><div className="spinner"/><h2>Building technical research for {query.toUpperCase()}</h2><p>Running the complete One Stop Technical Research Engine automatically.</p><div className="progressTrack"><i style={{width:`${Math.round((progress/PIPELINE.length)*100)}%`}}/></div><div className="progressLabel">{Math.min(progress,PIPELINE.length)} / {PIPELINE.length} stages</div><div className="loadingSteps">{PIPELINE.map(([x],i)=><span className={i<progress?"done":i===progress?"active":""} key={x}><b>{String(i+1).padStart(2,"0")}</b>{x}<em>{i<progress?"✓":i===progress?"…":""}</em></span>)}</div></section>}
      {data&&!loading&&<>
        <section className="securityHeader">
          <div><div className="eyebrow">ONE STOP TECHNICAL RESEARCH ENGINE</div><h1>{data.ticker.replace(".NS","")} <small>{data.company}</small></h1><p>{data.sector||"Sector N/A"} · {data.industry||"Industry N/A"} · Data as of {data.asOf}</p></div>
          <div className="actions"><button onClick={addWatch}>＋ Watchlist</button><button onClick={()=>go(`${API}/api/report/${data.ticker.replace(".NS","")}/technical-pdf`,"PDF")}>Download PDF</button><button className="primary" onClick={()=>go(`${API}/api/report/${data.ticker.replace(".NS","")}/technical-pack`,"PACK")}>Research Pack</button></div>
        </section>

        <section className="pipelineCard">
          <div className="pipelineTitle"><div><span className="eyebrow">AUTOMATED WORKFLOW</span><h2>Technical Research Pipeline</h2></div><span className="pipelineTag">{data.dataQuality?.status||"PASS"}</span></div>
          <div className="pipeline">{PIPELINE.map(([name,sub],i)=><React.Fragment key={name}><div className="pipeItem"><b>{String(i+1).padStart(2,"0")}</b><strong>{name}</strong><small>{sub}</small><em>✓</em></div>{i<PIPELINE.length-1&&<div className="pipeArrow">↓</div>}</React.Fragment>)}</div>
        </section>

        <section className="heroGrid">
          <div className="heroScore"><span>TECHNICAL SCORE</span><strong>{fmt(data.technicalScore,0)}<small>/100</small></strong><b>{data.technicalState}</b></div>
          <div className="heroLevel"><span>PRICE</span><strong>{money(data.price)}</strong><small>Support {money(data.structure.support)} · Resistance {money(data.structure.resistance)}</small></div>
          <div className="heroLevel"><span>BREAKOUT</span><strong>{data.breakout}</strong><small>Volume ratio {fmt(data.volume.ratio)}x</small></div>
          <div className="heroLevel"><span>REGIME</span><strong>{data.marketRegime}</strong><small>RSI {fmt(data.momentum.rsi)}</small></div>
        </section>

        <div className="grid two">
          <section className="panel chartPanel"><div className="panelHead"><div><span className="eyebrow">MARKET DATA</span><h2>Price & Trend</h2></div><span className="muted">Last 260 observations</span></div><svg viewBox="0 0 100 100" preserveAspectRatio="none" className="chart"><polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/></svg><div className="chartStats"><span>52W High <b>{money(data.structure.high52)}</b></span><span>52W Low <b>{money(data.structure.low52)}</b></span><span>History <b>{data.dataQuality.historyRows} rows</b></span></div></section>
          <section className="panel"><div className="panelHead"><div><span className="eyebrow">TREND</span><h2>Trend Intelligence</h2></div></div><DataRows rows={[["EMA 20",money(data.trend.ema20)],["EMA 50",money(data.trend.ema50)],["EMA 200",money(data.trend.ema200)],["SMA 20",money(data.trend.sma20)],["SMA 50",money(data.trend.sma50)],["SMA 200",money(data.trend.sma200)],["Trend Score",`${fmt(data.trend.score,0)}/100`]]}/></section>
        </div>

        <div className="grid three">
          <MetricPanel title="MOMENTUM" rows={[["RSI 14",fmt(data.momentum.rsi)],["MACD",fmt(data.momentum.macd)],["Signal",fmt(data.momentum.signal)],["Histogram",fmt(data.momentum.histogram)],["ROC 20",pct(data.momentum.roc20)],["Stochastic",fmt(data.momentum.stochastic)]]}/>
          <MetricPanel title="VOLUME" rows={[["Current",fmt(data.volume.current,0)],["20D Average",fmt(data.volume.average20,0)],["Volume Ratio",`${fmt(data.volume.ratio)}x`],["OBV Trend",data.volume.obvTrend],["Volume Score",`${fmt(data.volume.score,0)}/100`]]}/>
          <MetricPanel title="VOLATILITY" rows={[["ATR",money(data.volatility.atr)],["ATR %",pct(data.volatility.atrPct)],["BB Width",pct(data.volatility.bbWidth)],["Historical Vol",pct(data.volatility.historicalVolatility)],["Volatility Score",`${fmt(data.volatility.score,0)}/100`]]}/>
        </div>

        <div className="grid two">
          <section className="panel"><div className="panelHead"><div><span className="eyebrow">MARKET STRUCTURE</span><h2>Support / Resistance</h2></div></div><div className="levels"><div className="res"><small>RESISTANCE</small><strong>{money(data.structure.resistance)}</strong><span>{pct(data.technicalRisk.resistanceDistance)} away</span></div><div className="current"><small>CURRENT</small><strong>{money(data.price)}</strong></div><div className="sup"><small>SUPPORT</small><strong>{money(data.structure.support)}</strong><span>{pct(data.technicalRisk.supportDistance)} away</span></div></div><DataRows rows={[["Swing High",money(data.structure.swingHigh)],["Swing Low",money(data.structure.swingLow)],["52W High",money(data.structure.high52)],["52W Low",money(data.structure.low52)]]}/></section>
          <section className="panel"><div className="panelHead"><div><span className="eyebrow">SIGNALS</span><h2>Breakout & Divergence</h2></div></div><DataRows rows={[["Breakout",data.breakout],["Divergence",data.divergence],["Technical Events",data.events.length?data.events.join(" • "):"No major event"],["Structure Score",`${fmt(data.structure.score,0)}/100`]]}/></section>
        </div>

        <section className="panel"><div className="panelHead"><div><span className="eyebrow">MULTI-TIMEFRAME</span><h2>Timeframe Alignment</h2></div></div><div className="tfGrid">{Object.entries(data.multiTimeframe).map(([tf,v])=><div key={tf}><b>{tf}</b><span>{v.trend}</span><small>EMA20 {money(v.ema20)}<br/>EMA50 {money(v.ema50)}</small></div>)}</div></section>

        <div className="grid two">
          <section className="panel"><div className="panelHead"><div><span className="eyebrow">RELATIVE STRENGTH</span><h2>Stock vs NIFTY 50</h2></div></div><div className="rsTable">{["1M","3M","6M","1Y"].map(k=>data.relativeStrength[k]&&<div key={k}><b>{k}</b><span>Stock {pct(data.relativeStrength[k].stock)}</span><span>NIFTY {pct(data.relativeStrength[k].nifty)}</span><strong>{data.relativeStrength[k].relative>=0?"+":""}{pct(data.relativeStrength[k].relative)}</strong></div>)}</div><DataRows rows={[["Beta",fmt(data.relativeStrength.beta)],["Correlation",fmt(data.relativeStrength.correlation)]]}/></section>
          <section className="panel"><div className="panelHead"><div><span className="eyebrow">TECHNICAL EVENTS</span><h2>Detected Events</h2></div></div><ul className="events">{(data.events.length?data.events:["No major technical event detected"]).map(e=><li key={e}><i/> {e}</li>)}</ul><div className="regime">MARKET REGIME <b>{data.marketRegime}</b></div></section>
        </div>

        <section className="panel"><div className="panelHead"><div><span className="eyebrow">BACKTESTING</span><h2>Historical Strategy Test</h2></div><span className="muted">Historical only</span></div>{data.backtest?.strategyCAGR!=null?<DataRows rows={[["Strategy",data.backtest.strategy],["Strategy CAGR",pct(data.backtest.strategyCAGR)],["Buy & Hold CAGR",pct(data.backtest.buyHoldCAGR)],["Maximum Drawdown",pct(data.backtest.maxDrawdown)],["Trade / Position Changes",String(data.backtest.trades)]]}/>:<p className="muted">Insufficient history for the historical strategy test.</p>}</section>

        <div className="grid two">
          <section className="panel"><div className="panelHead"><div><span className="eyebrow">TECHNICAL RISK</span><h2>Risk Context</h2></div></div><DataRows rows={[["ATR %",pct(data.technicalRisk.atrPct)],["Support Distance",pct(data.technicalRisk.supportDistance)],["Resistance Distance",pct(data.technicalRisk.resistanceDistance)],["Volatility Score",`${fmt(data.volatility.score,0)}/100`]]}/></section>
          <section className="panel scoreCard"><div className="panelHead"><div><span className="eyebrow">TECHNICAL SCORE</span><h2>Transparent Scorecard</h2></div></div>{[["Trend",data.trend.score],["Momentum",data.momentum.score],["Volume",data.volume.score],["Volatility",data.volatility.score],["Structure",data.structure.score],["Relative Strength",data.relativeStrength["3M"]?Math.max(0,Math.min(100,50+data.relativeStrength["3M"].relative*500)):50]].map(([n,v])=><div className="scoreRow" key={n}><span>{n}</span><div><i style={{width:`${v}%`}}/></div><b>{fmt(v,0)}</b></div>)}</section>
        </div>

        <section className="thesis"><div><span className="eyebrow">TECHNICAL THESIS</span><h2>Research Interpretation</h2><p>{data.thesis}</p></div><div className="thesisActions"><button onClick={()=>go(`${API}/api/report/${data.ticker.replace(".NS","")}/technical-pdf`,"PDF")}>Download Technical PDF</button><button onClick={()=>go(`${API}/api/report/${data.ticker.replace(".NS","")}/technical-pack`,"PACK")}>Download Research Pack</button></div></section>

        <section className="panel watchPanel"><div className="panelHead"><div><span className="eyebrow">WORKSPACE</span><h2>Watchlist</h2></div></div>{watch.length?<div className="watchlist">{watch.map(w=><button key={w._id} onClick={()=>research(w.ticker)}><b>{w.ticker}</b><span>{w.company}</span></button>)}</div>:<p className="muted">Add the security to keep it in your research workspace.</p>}</section>
        {download&&<div className="toast">Preparing {download}...</div>}
        <footer>GROWISE INVEST · Your One-Stop Investment House · Technical research is analytical support. Final investment decisions remain with the analyst.</footer>
      </>}
    </main>
  </div>
}
function DataRows({rows}){return <div className="dataRows">{rows.map(([a,b])=><div key={a}><span>{a}</span><b>{b}</b></div>)}</div>}
function MetricPanel({title,rows}){return <section className="panel"><div className="panelHead"><div><span className="eyebrow">{title}</span><h2>Intelligence</h2></div></div><DataRows rows={rows}/></section>}

createRoot(document.getElementById("root")).render(<App/>);
