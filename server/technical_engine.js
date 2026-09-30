const dns = require('dns');
dns.setDefaultResultOrder?.('ipv4first');
const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');
const { execFile } = require('child_process');
const { promisify } = require('util');
const execFileAsync = promisify(execFile);
const { URL } = require('url');
const PDFDocument = require('pdfkit');
const archiver = require('archiver');

const CACHE_DIR = path.join(__dirname, 'data_cache');
fs.mkdirSync(CACHE_DIR, { recursive: true });
const USER_AGENT = 'GROWISEINVEST Technical Research/1.0';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function cleanTicker(t) {
  const x = String(t || '').trim().toUpperCase().replace(/\.NS$|\.BO$/,'');
  if (!/^[A-Z0-9&.-]{1,25}$/.test(x)) throw new Error('Invalid NSE ticker');
  return x;
}
function num(x) { const n=Number(x); return Number.isFinite(n)?n:null; }
function avg(a){const v=a.filter(Number.isFinite);return v.length?v.reduce((s,x)=>s+x,0)/v.length:null;}
function sum(a){return a.filter(Number.isFinite).reduce((s,x)=>s+x,0);}
function pctChange(a,b){return a!=null&&b!=null&&b!==0?a/b-1:null;}
function clamp(x,a=0,b=100){return Math.max(a,Math.min(b,x));}
function sleepTimeout(ms){return new Promise((_,rej)=>setTimeout(()=>rej(new Error(`Timeout after ${ms}ms`)),ms));}
async function fetchText(url, options={}, timeout=8000){
  const ac=new AbortController(); const timer=setTimeout(()=>ac.abort(),timeout);
  try { const r=await fetch(url,{...options,signal:ac.signal}); if(!r.ok) throw new Error(`HTTP ${r.status}`); return await r.text(); }
  catch(e){ throw new Error(`${e.name==='AbortError'?'Request timed out':e.message}`); }
  finally{clearTimeout(timer);}
}

async function curlText(url, timeoutSec=8){
  const curl=process.platform==='win32'?'curl.exe':'curl';
  const {stdout}=await execFileAsync(curl,['-L','--silent','--show-error','--max-time',String(timeoutSec),'-A',USER_AGENT,url],{windowsHide:true,maxBuffer:20*1024*1024});
  return stdout;
}
async function fetchJson(url, options={}, timeout=8000){ return JSON.parse(await fetchText(url,options,timeout)); }

function parseYahoo(payload){
  const r=payload?.chart?.result?.[0]; if(!r) throw new Error(payload?.chart?.error?.description||'Yahoo returned no data');
  const q=r.indicators?.quote?.[0]||{}; const a=r.indicators?.adjclose?.[0]?.adjclose||[]; const ts=r.timestamp||[];
  const rows=[];
  for(let i=0;i<ts.length;i++){
    const close=num(q.close?.[i]); if(close==null) continue;
    rows.push({date:new Date(ts[i]*1000).toISOString().slice(0,10),open:num(q.open?.[i]),high:num(q.high?.[i]),low:num(q.low?.[i]),close,volume:num(q.volume?.[i])||0,adjclose:num(a[i])||close});
  }
  if(rows.length<50) throw new Error('Yahoo returned insufficient history');
  return {rows,meta:r.meta||{},provider:'Yahoo Chart'};
}
async function yahoo(symbol, range='5y'){
  const urls=[1,2].map(q=>`https://query${q}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${range}&interval=1d&events=history&includeAdjustedClose=true`);
  const jobs=urls.map(async u=>{
    try{return parseYahoo(await fetchJson(u,{headers:{'User-Agent':USER_AGENT,'Accept':'application/json'}},6500));}
    catch(e){return parseYahoo(JSON.parse(await curlText(u,7)));}
  });
  try{return await Promise.any(jobs);}catch(e){const msgs=(e.errors||[]).map(x=>x.message).join(' | ');throw new Error(`Yahoo unavailable: ${msgs||'unknown error'}`);}
}
function parseCsv(text){
  const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  if(!lines.length) throw new Error('NSE returned empty CSV');
  const split=line=>line.match(/(?:"(?:[^"]|"")*"|[^,])+/g)?.map(x=>x.replace(/^"|"$/g,'').replace(/""/g,'"'))||[];
  const h=split(lines[0]).map(x=>x.toLowerCase().replace(/[^a-z]/g,''));
  const find=(...names)=>names.map(n=>h.indexOf(n)).find(i=>i>=0);
  const di=find('date','tradedate','timestamp'); const oi=find('open','openingprice'); const hi=find('high','highestprice'); const li=find('low','lowestprice'); const ci=find('close','closingprice'); const vi=find('volume','totaltradedvolume','ttltradgvol');
  if(ci<0) throw new Error('NSE CSV schema not recognized');
  const rows=[];
  for(const line of lines.slice(1)){
    const c=split(line); const close=num(c[ci]); if(close==null) continue;
    const rawDate=c[di]||''; let d=rawDate;
    const m=rawDate.match(/^(\d{2})-(\d{2})-(\d{4})$/); if(m)d=`${m[3]}-${m[2]}-${m[1]}`;
    const iso=/^\d{4}-\d{2}-\d{2}/.test(d)?d.slice(0,10):rawDate;
    rows.push({date:iso,open:num(c[oi]),high:num(c[hi]),low:num(c[li]),close,volume:num(c[vi])||0,adjclose:close});
  }
  rows.sort((a,b)=>a.date.localeCompare(b.date));
  if(rows.length<50) throw new Error('NSE returned insufficient history');
  return {rows,meta:{},provider:'NSE Historical CSV'};
}
async function nse(symbol){
  const now=new Date(); const from=new Date(now.getTime()-365*5.2*86400000);
  const fmt=d=>`${String(d.getDate()).padStart(2,'0')}-${String(d.getMonth()+1).padStart(2,'0')}-${d.getFullYear()}`;
  const home=await fetchText('https://www.nseindia.com/',{headers:{'User-Agent':USER_AGENT,'Accept':'text/html,application/xhtml+xml','Accept-Language':'en-US,en;q=0.9'}},7000);
  // Node fetch does not expose Set-Cookie in all runtimes, so obtain it with a small https request when possible.
  let cookie='';
  try{await new Promise((resolve,reject)=>{const req=https.get('https://www.nseindia.com/',{headers:{'User-Agent':USER_AGENT}},res=>{cookie=(res.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ');res.resume();res.on('end',resolve)});req.setTimeout(6000,()=>{req.destroy();reject(new Error('NSE session timeout'))});req.on('error',reject)});}catch{}
  const u=`https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData?symbol=${encodeURIComponent(symbol)}&from=${fmt(from)}&to=${fmt(now)}&series=EQ&type=priceVolumeDeliverable&csv=true`;
  const text=await fetchText(u,{headers:{'User-Agent':USER_AGENT,'Accept':'text/csv,application/csv,*/*','Referer':'https://www.nseindia.com/get-quotes/equity','X-Requested-With':'XMLHttpRequest',...(cookie?{'Cookie':cookie}:{})}},8000);
  return parseCsv(text);
}
async function getHistory(symbol){
  const key=path.join(CACHE_DIR,`${symbol}.json`);
  const providers=[()=>yahoo(`${symbol}.NS`),()=>nse(symbol)];
  let result=null,last=[];
  try { result=await Promise.any(providers.map(fn=>fn())); } catch(e) { last=(e.errors||[]).map(x=>x.message); }
  if(!result){
    if(fs.existsSync(key)){
      try{const cached=JSON.parse(fs.readFileSync(key,'utf8')); if(cached.rows?.length>=50)return {...cached,provider:`Cached ${cached.provider||'market data'}`};}catch{}
    }
    throw new Error(`No live market-data provider responded. Yahoo: ${last[0]||'failed'} | NSE: ${last[1]||'failed'}. Check internet/DNS or try again.`);
  }
  fs.writeFileSync(key,JSON.stringify({savedAt:new Date().toISOString(),provider:result.provider,rows:result.rows}));
  return result;
}

function sma(v,n){return v.map((_,i)=>i+1<n?null:avg(v.slice(i-n+1,i+1)));}
function ema(v,n){const out=[]; const k=2/(n+1); let e=null; for(let i=0;i<v.length;i++){e=e==null?v[i]:v[i]*k+e*(1-k);out.push(e)} return out;}
function rsi(v,n=14){const out=Array(v.length).fill(null); let gain=0,loss=0; for(let i=1;i<=n&&i<v.length;i++){const d=v[i]-v[i-1];gain+=Math.max(d,0);loss+=Math.max(-d,0);} if(v.length>n){gain/=n;loss/=n;out[n]=loss===0?100:100-100/(1+gain/loss); for(let i=n+1;i<v.length;i++){const d=v[i]-v[i-1];gain=(gain*(n-1)+Math.max(d,0))/n;loss=(loss*(n-1)+Math.max(-d,0))/n;out[i]=loss===0?100:100-100/(1+gain/loss)}} return out;}
function std(v){if(v.length<2)return null;const m=avg(v);return Math.sqrt(avg(v.map(x=>(x-m)**2)));}
function returns(v,n=1){return v.map((x,i)=>i<n?null:x/v[i-n]-1);}
function atr(rows,n=14){const tr=rows.map((r,i)=>i===0?(r.high-r.low):Math.max(r.high-r.low,Math.abs(r.high-rows[i-1].close),Math.abs(r.low-rows[i-1].close)));return ema(tr,n);}
function stoch(rows,n=14){return rows.map((r,i)=>{if(i<n-1)return null;const w=rows.slice(i-n+1,i+1), hi=Math.max(...w.map(x=>x.high)),lo=Math.min(...w.map(x=>x.low));return hi===lo?50:(r.close-lo)/(hi-lo)*100});}
function obv(rows){let o=0,out=[0];for(let i=1;i<rows.length;i++){o+=rows[i].close>rows[i-1].close?rows[i].volume:rows[i].close<rows[i-1].close?-rows[i].volume:0;out.push(o)}return out;}
function corr(a,b){const x=[],y=[];for(let i=0;i<Math.min(a.length,b.length);i++)if(Number.isFinite(a[i])&&Number.isFinite(b[i])){x.push(a[i]);y.push(b[i])}if(x.length<3)return null;const mx=avg(x),my=avg(y);const num=sum(x.map((z,i)=>(z-mx)*(y[i]-my)));const den=Math.sqrt(sum(x.map(z=>(z-mx)**2))*sum(y.map(z=>(z-my)**2)));return den?num/den:null;}
function beta(a,b){const c=corr(a,b);if(c==null)return null;const vb=std(b);const va=std(a);return vb?c*(va/vb):null;}
function aggregate(rows, step){const out=[]; for(let i=step-1;i<rows.length;i+=step){const w=rows.slice(i-step+1,i+1);out.push({date:w.at(-1).date,open:w[0].open,high:Math.max(...w.map(x=>x.high)),low:Math.min(...w.map(x=>x.low)),close:w.at(-1).close,volume:sum(w.map(x=>x.volume))})} return out;}
function trendLabel(p,e20,e50,e200){if(p>e20&&e20>e50&&e50>e200)return 'UPTREND';if(p<e20&&e20<e50&&e50<e200)return 'DOWNTREND';return 'MIXED';}
function scoreTrend(p,e20,e50,e200){let s=50;s+=(p>e20?15:-15);s+=(e20>e50?15:-15);s+=(e50>e200?20:-20);return clamp(s);}
function compute(rows, niftyRows=null, symbol){
  rows=rows.filter(r=>r.close!=null).sort((a,b)=>a.date.localeCompare(b.date)); const c=rows.map(r=>r.close), vol=rows.map(r=>r.volume||0), h=rows.map(r=>r.high), l=rows.map(r=>r.low);
  const e20=ema(c,20),e50=ema(c,50),e100=ema(c,100),e200=ema(c,200),s20=sma(c,20),s50=sma(c,50),s200=sma(c,200),R=rsi(c),st=stoch(rows),a=atr(rows),vol20=sma(vol,20),O=obv(rows),r20=returns(c,20),r60=returns(c,60),r120=returns(c,120),r252=returns(c,252);
  const mid=s20, sd=c.map((_,i)=>i<19?null:std(c.slice(i-19,i+1))), bbU=mid.map((x,i)=>x==null?null:x+2*sd[i]),bbL=mid.map((x,i)=>x==null?null:x-2*sd[i]);
  const e12=ema(c,12),e26=ema(c,26),macd=c.map((_,i)=>e12[i]-e26[i]),sig=ema(macd,9),hist=macd.map((x,i)=>x-sig[i]);
  const current=c.at(-1), idx=c.length-1, vr=vol20[idx]?vol[idx]/vol20[idx]:null, atrPct=a[idx]/current, bbWidth=(bbU[idx]-bbL[idx])/mid[idx], hv=std(r20.slice(-252).filter(x=>x!=null))*Math.sqrt(252);
  const trendScore=scoreTrend(current,e20[idx],e50[idx],e200[idx]);
  const momentumScore=clamp(50+(R[idx]-50)*.8+(hist[idx]>0?15:-15)+(r20[idx]>0?10:-10));
  const volumeScore=clamp(50+(vr-1)*25+(O[idx]>O[Math.max(0,idx-20)]?15:-15));
  const volScore=clamp(75-(atrPct*100*2));
  const high52=Math.max(...h.slice(-252)),low52=Math.min(...l.slice(-252));
  const recentHigh=Math.max(...h.slice(-60)),recentLow=Math.min(...l.slice(-60));
  const support=Math.max(low52,Math.min(recentLow,s20[idx]||low52));
  const resistance=Math.min(high52,Math.max(recentHigh,s50[idx]||high52));
  const structureScore=clamp(50+(current>e50[idx]?20:-20)+(e50[idx]>e200[idx]?20:-20)+(current>support?10:-10));
  const breakout=current>recentHigh*0.995 && vr>1.2?'BREAKOUT WATCH':current<recentLow*1.005&&vr>1.2?'BREAKDOWN WATCH':'NO CONFIRMED BREAKOUT';
  const div = R[idx]>55 && c[idx]<Math.max(...c.slice(-40,-10)) ? 'POSSIBLE BEARISH DIVERGENCE' : R[idx]<45 && c[idx]>Math.min(...c.slice(-40,-10)) ? 'POSSIBLE BULLISH DIVERGENCE' : 'NO CLEAR DIVERGENCE';
  const tf={}; for(const [name,step] of [['1D',1],['1W',5],['1M',21]]){const rr=step===1?rows:aggregate(rows,step);const cc=rr.map(x=>x.close),ee20=ema(cc,20).at(-1),ee50=ema(cc,50).at(-1),ee200=ema(cc,200).at(-1);tf[name]={trend:trendLabel(cc.at(-1),ee20,ee50,ee200),ema20:ee20,ema50:ee50,ema200:ee200};}
  let rs={}; if(niftyRows?.length){const nc=niftyRows.map(x=>x.close); for(const [k,n] of [['1M',21],['3M',63],['6M',126],['1Y',252]]){const sr=returns(c,n).at(-1),nr=returns(nc,n).at(-1);rs[k]={stock:sr,nifty:nr,relative:sr!=null&&nr!=null?sr-nr:null};} const stockRet=returns(c,Math.min(252,c.length-1)).filter(x=>x!=null).slice(-Math.min(252,niftyRows.length));const niftyRet=returns(nc,Math.min(252,nc.length-1)).filter(x=>x!=null).slice(-Math.min(252,niftyRows.length));rs.beta=beta(stockRet,niftyRet);rs.correlation=corr(stockRet,niftyRet);} else {for(const k of ['1M','3M','6M','1Y'])rs[k]={stock:null,nifty:null,relative:null};rs.beta=null;rs.correlation=null;}
  const regime=trendLabel(current,e20[idx],e50[idx],e200[idx]);
  const events=[]; if(e20[idx]>e50[idx]&&e20[idx-1]<=e50[idx-1])events.push('EMA 20/50 GOLDEN CROSS'); if(e20[idx]<e50[idx]&&e20[idx-1]>=e50[idx-1])events.push('EMA 20/50 DEATH CROSS'); if(R[idx]>70)events.push('RSI OVERBOUGHT'); if(R[idx]<30)events.push('RSI OVERSOLD'); if(vr>1.8)events.push('HIGH VOLUME SPIKE'); if(breakout!=='NO CONFIRMED BREAKOUT')events.push(breakout); if(hist[idx]>0&&hist[idx-1]<=0)events.push('MACD POSITIVE CROSS'); if(hist[idx]<0&&hist[idx-1]>=0)events.push('MACD NEGATIVE CROSS');
  const strategy=[]; let inPos=false,entry=0,trades=0,vals=[1]; for(let i=200;i<c.length;i++){const buy=c[i]>s200[i]&&e20[i]>e50[i],sell=c[i]<s200[i]||e20[i]<e50[i]; if(!inPos&&buy){inPos=true;entry=c[i];trades++;} if(inPos&&sell){vals.push(vals.at(-1)*(c[i]/entry));inPos=false;entry=0;trades++;} else vals.push(vals.at(-1));} const strategyCAGR=vals.length>1?Math.pow(vals.at(-1),252/Math.max(1,vals.length))-1:null; const bh=c.length>252?Math.pow(c.at(-1)/c.at(-252),252/252)-1:null; const maxDD=(()=>{let peak=1,dd=0;for(const v of vals){peak=Math.max(peak,v);dd=Math.min(dd,v/peak-1)}return dd})();
  const rsScore=rs['3M']?.relative==null?50:clamp(50+rs['3M'].relative*500);
  const technicalScore=+(0.25*trendScore+0.20*momentumScore+0.15*volumeScore+0.10*volScore+0.20*structureScore+0.10*rsScore).toFixed(1);
  const state=technicalScore>=65?'CONSTRUCTIVE':technicalScore>=45?'MIXED':'WEAK';
  const thesis=`${symbol} is in a ${regime.toLowerCase()} based on price versus the 20, 50 and 200 period EMA structure. Momentum is ${R[idx]>=55?'positive':R[idx]<=45?'soft':'mixed'} with RSI ${R[idx].toFixed(1)} and MACD histogram ${hist[idx]>=0?'positive':'negative'}. Volume is ${vr>=1.2?'confirming':'not strongly confirming'} the latest move at ${vr?.toFixed(2)??'N/A'}x its 20 day average. Key technical levels are support ₹${support.toFixed(2)} and resistance ₹${resistance.toFixed(2)}. ${breakout}. ${div}. Final investment decisions remain with the analyst.`;
  const chart=rows.slice(-260).map((r,i)=>({date:r.date,close:r.close,ema20:e20[rows.length-260+i],ema50:e50[rows.length-260+i],ema200:e200[rows.length-260+i],bbUpper:bbU[rows.length-260+i],bbLower:bbL[rows.length-260+i],rsi:R[rows.length-260+i],volume:r.volume,volRatio:vol20[rows.length-260+i]?r.volume/vol20[rows.length-260+i]:null}));
  return {ticker:`${symbol}.NS`,company:companyMap[symbol]||symbol,sector:sectorMap[symbol]||'N/A',industry:'N/A',price:current,asOf:rows.at(-1).date,provider:rows[0].provider,pipeline:['Market Data','Trend','Momentum','Volume','Volatility','Market Structure','Support / Resistance','Breakout','Divergence','Multi-Timeframe','Relative Strength','Market / Sector Regime','Technical Events','Backtesting','Technical Risk','Technical Score','Technical Thesis','PDF / Excel / Word / Charts'],dataQuality:{historyRows:rows.length,status:rows.length>=252?'PASS':'REVIEW'},trend:{ema20:e20[idx],ema50:e50[idx],ema100:e100[idx],ema200:e200[idx],sma20:s20[idx],sma50:s50[idx],sma200:s200[idx],score:trendScore,trend:trendLabel(current,e20[idx],e50[idx],e200[idx])},momentum:{rsi:R[idx],macd:macd[idx],signal:sig[idx],histogram:hist[idx],roc20:r20[idx],stochastic:st[idx],score:momentumScore},volume:{current:vol[idx],average20:vol20[idx],ratio:vr,obvTrend:O[idx]>O[Math.max(0,idx-20)]?'RISING':'FALLING',score:volumeScore},volatility:{atr:a[idx],atrPct,bbWidth,historicalVolatility:hv,score:volScore},structure:{swingHigh:recentHigh,swingLow:recentLow,high52,low52,support,resistance,score:structureScore},breakout,divergence:div,multiTimeframe:tf,relativeStrength:rs,marketRegime:regime,events,backtest:{strategy:'200DMA + EMA20/50',strategyCAGR,buyHoldCAGR:bh,maxDrawdown:maxDD,trades},technicalRisk:{atrPct,supportDistance:current/support-1,resistanceDistance:resistance/current-1},technicalScore,technicalState:state,thesis,chart,humanDecision:'Technical research output only. Final investment decision remains with the analyst.'};
}
const companyMap={TCS:'Tata Consultancy Services Limited',INFY:'Infosys Limited',HCLTECH:'HCL Technologies Limited',WIPRO:'Wipro Limited',TECHM:'Tech Mahindra Limited',RELIANCE:'Reliance Industries Limited',HDFCBANK:'HDFC Bank Limited',ICICIBANK:'ICICI Bank Limited',SBIN:'State Bank of India',ITC:'ITC Limited',LT:'Larsen & Toubro Limited',MARUTI:'Maruti Suzuki India Limited',SUNPHARMA:'Sun Pharmaceutical Industries Limited',TATAMOTORS:'Tata Motors Limited'};
const sectorMap={TCS:'Technology',INFY:'Technology',HCLTECH:'Technology',WIPRO:'Technology',TECHM:'Technology',RELIANCE:'Energy',HDFCBANK:'Financial Services',ICICIBANK:'Financial Services',SBIN:'Financial Services',ITC:'Consumer Defensive',LT:'Industrials',MARUTI:'Automobiles',SUNPHARMA:'Healthcare',TATAMOTORS:'Automobiles'};

async function research(symbol){const s=cleanTicker(symbol);let h=await getHistory(s);let nifty=null;try{nifty=(await yahoo('%5ENSEI','2y')).rows}catch{};return compute(h.rows,nifty,s);}

function flatten(obj,prefix='',out=[]){if(obj==null||typeof obj!=='object'||Array.isArray(obj)){out.push([prefix,String(obj??'')]);return out;}for(const [k,v] of Object.entries(obj)){const p=prefix?`${prefix}.${k}`:k;if(v&&typeof v==='object'&&!Array.isArray(v))flatten(v,p,out);else out.push([p,String(v??'')]);}return out;}
function xmlEscape(v){return String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&apos;');}
function cellXml(v){const s=String(v??'');return `<c t="inlineStr"><is><t>${xmlEscape(s)}</t></is></c>`;}
function reportRows(d){
  return [
    ['Technical Summary',[['Price',d.price],['Technical Score',`${d.technicalScore}/100`],['Technical State',d.technicalState],['Market Regime',d.marketRegime],['Breakout',d.breakout],['Divergence',d.divergence]]],
    ['Market Data',[['Provider',d.provider],['Data As Of',d.asOf],['History Rows',d.dataQuality?.historyRows],['Data Quality',d.dataQuality?.status]]],
    ['Trend',d.trend],['Momentum',d.momentum],['Volume',d.volume],['Volatility',d.volatility],['Market Structure',d.structure],
    ['Multi-Timeframe',d.multiTimeframe],['Relative Strength',d.relativeStrength],['Technical Events',[['Events',(d.events||[]).join(' • ')||'No major technical event']]],
    ['Backtesting',d.backtest],['Technical Risk',d.technicalRisk]
  ];
}

function addPdfChrome(doc, cover=false){
  const range=doc.bufferedPageRange();
  const page=doc.page;
  doc.save();
  doc.lineWidth(0.8).strokeColor('#AFC4DF').rect(24,24,page.width-48,page.height-48).stroke();
  doc.restore();
  if(!cover){
    doc.save();
    doc.fontSize(7).fillColor('#5D7697').text('GROWISE INVEST  |  Your One-Stop Investment House',42,31,{width:page.width-84,align:'left'});
    doc.fontSize(7).fillColor('#5D7697').text('Technical Research Report',42,31,{width:page.width-84,align:'right'});
    doc.restore();
  }
  doc.save();
  doc.fontSize(7).fillColor('#6C819D').text(`Prepared by Ved Lingayat  |  Generated ${new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}`,42,page.height-34,{width:page.width-84,align:'left'});
  doc.text(`Page ${range.start + 1}`,42,page.height-34,{width:page.width-84,align:'right'});
  doc.restore();
}

function pdf(d,res){
  const doc=new PDFDocument({size:'A4',margin:52,bufferPages:true});
  res.setHeader('Content-Type','application/pdf');
  res.setHeader('Content-Disposition',`attachment; filename="GROWISEINVEST_${d.ticker.replace('.NS','')}_Technical_Research.pdf"`);
  doc.pipe(res);

  // Cover
  doc.rect(24,24,doc.page.width-48,doc.page.height-48).lineWidth(1.2).strokeColor('#163D73').stroke();
  doc.moveDown(3);
  doc.fontSize(12).fillColor('#4B73A5').text('GROWISE INVEST',{align:'center',characterSpacing:2});
  doc.moveDown(.5);
  doc.fontSize(9).fillColor('#6D84A2').text('Your One-Stop Investment House',{align:'center'});
  doc.moveDown(4);
  doc.fontSize(28).fillColor('#082A55').text('TECHNICAL RESEARCH REPORT',{align:'center'});
  doc.moveDown(1.2);
  doc.fontSize(22).fillColor('#176FE6').text(`${d.ticker.replace('.NS','')}`,{align:'center'});
  doc.moveDown(.3);
  doc.fontSize(14).fillColor('#294E78').text(d.company,{align:'center'});
  doc.moveDown(2);
  doc.fontSize(10).fillColor('#66809F').text(`Generated on ${new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'long',year:'numeric'})}`,{align:'center'});
  doc.fontSize(10).fillColor('#66809F').text('Prepared by Ved Lingayat',{align:'center'});
  doc.moveDown(4);
  doc.roundedRect(95,430,405,95,14).fillAndStroke('#F1F6FD','#D3E1F1');
  doc.fontSize(9).fillColor('#66809F').text('RESEARCH SNAPSHOT',115,450,{width:365,align:'center'});
  doc.fontSize(25).fillColor('#0A2D5D').text(`${d.technicalScore}/100`,115,472,{width:175,align:'center'});
  doc.fontSize(11).fillColor('#176FE6').text(d.technicalState,290,480,{width:170,align:'center'});
  doc.fontSize(8).fillColor('#7A8FA9').text('Technical analytics • trend • momentum • risk • structure',{align:'center'});
  addPdfChrome(doc,true);

  doc.addPage();
  const section=(title)=>{doc.moveDown(.4);doc.fontSize(15).fillColor('#082A55').text(title);doc.moveTo(52,doc.y+4).lineTo(543,doc.y+4).lineWidth(.7).strokeColor('#C9D8EA').stroke();doc.moveDown(.45);};
  const table=(rows)=>{
    const left=52,right=543;
    for(const [k,v] of rows){
      if(doc.y>730){doc.addPage();}
      doc.fontSize(8.5).fillColor('#68809E').text(String(k),left,doc.y,{width:220});
      doc.fontSize(9).fillColor('#173A63').text(String(v==null?'N/A':v),285,doc.y,{width:right-285,align:'right'});
      doc.moveTo(left,doc.y+12).lineWidth(.35).strokeColor('#E1EAF4').stroke();
      doc.moveDown(.38);
    }
  };
  doc.fontSize(19).fillColor('#082A55').text(`${d.ticker.replace('.NS','')} Technical Research`);
  doc.fontSize(9).fillColor('#66809F').text(`${d.sector||'Sector N/A'}  •  ${d.industry||'Industry N/A'}  •  Data as of ${d.asOf}`);
  doc.moveDown(.8);
  section('Executive Technical Snapshot'); table(reportRows(d)[0][1]);
  section('Market Data & Quality'); table(reportRows(d)[1][1]);
  section('Trend Intelligence'); table(flatten(d.trend));
  section('Momentum Intelligence'); table(flatten(d.momentum));
  section('Volume Intelligence'); table(flatten(d.volume));
  section('Volatility Intelligence'); table(flatten(d.volatility));
  doc.addPage(); section('Market Structure'); table(flatten(d.structure));
  section('Multi-Timeframe'); table(flatten(d.multiTimeframe));
  section('Relative Strength'); table(flatten(d.relativeStrength));
  section('Technical Events'); table([['Events',(d.events||[]).join(' • ')||'No major technical event']]);
  section('Backtesting'); table(flatten(d.backtest));
  section('Technical Risk'); table(flatten(d.technicalRisk));
  section('Technical Thesis'); doc.fontSize(10).fillColor('#294E78').text(d.thesis,{lineGap:5});
  doc.moveDown(1);doc.fontSize(8).fillColor('#6C819D').text('Analytical note: historical indicators and backtests are analytical outputs, not guarantees. Final investment decisions remain with the analyst.');

  const range=doc.bufferedPageRange();
  for(let i=0;i<range.count;i++){
    doc.switchToPage(i);
    addPdfChrome(doc,i===0);
  }
  doc.end();
}

function xmlEscape(v){return String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&apos;');}
function cellXml(v,style=''){return `<c${style?` s="${style}"`:''} t="inlineStr"><is><t>${xmlEscape(v)}</t></is></c>`;}
function sheetXml(rows){return rows.map((r,i)=>`<row r="${i+1}">${r.map((v,j)=>cellXml(v,(i===0||j===0)?'1':'')).join('')}</row>`).join('');}
async function makeExcel(d,file){
  const rows=[['GROWISE INVEST | ONE STOP TECHNICAL RESEARCH HOUSE',''],['Technical Research Report',''],['Prepared By','Ved Lingayat'],['Generated',new Date().toLocaleDateString('en-IN')],['Ticker',d.ticker],['Company',d.company],['Data As Of',d.asOf],[],['Metric','Value']];
  for(const [k,v] of [['Price',d.price],['Technical Score',d.technicalScore],['Technical State',d.technicalState],['Market Regime',d.marketRegime],['Breakout',d.breakout],['Divergence',d.divergence]])rows.push([k,v]);
  rows.push([]);
  for(const [section,obj] of reportRows(d).slice(1)){
    rows.push([section,'']);
    for(const [k,v] of flatten(obj)) rows.push([k,v]);
    rows.push([]);
  }
  const technicalRows=d.chart.map(x=>[x.date,x.close,x.ema20,x.ema50,x.ema200,x.rsi,x.volume,x.volRatio]);
  const files={
    '[Content_Types].xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`,
    '_rels/.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    'xl/workbook.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Research Summary" sheetId="1" r:id="rId1"/><sheet name="Price History" sheetId="2" r:id="rId2"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`,
    'xl/styles.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="123D73"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyFont="1" applyFill="1"/></cellXfs></styleSheet>`,
    'xl/worksheets/sheet1.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="1" max="1" width="28" customWidth="1"/><col min="2" max="2" width="48" customWidth="1"/></cols><sheetData>${sheetXml(rows)}</sheetData><pane ySplit="9" topLeftCell="A10" activePane="bottomLeft" state="frozen"/></worksheet>`,
    'xl/worksheets/sheet2.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="1" max="1" width="14" customWidth="1"/><col min="2" max="8" width="16" customWidth="1"/></cols><sheetData>${sheetXml([['Date','Close','EMA20','EMA50','EMA200','RSI','Volume','Volume Ratio'],...technicalRows])}</sheetData><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></worksheet>`
  };
  await new Promise((resolve,reject)=>{const out=fs.createWriteStream(file);const a=archiver('zip',{zlib:{level:9}});out.on('close',resolve);a.on('error',reject);a.pipe(out);for(const [name,content] of Object.entries(files))a.append(content,{name});a.finalize();});
}

function makeWordXml(d){
  const p=(text,b=false,center=false)=>`<w:p><w:pPr>${center?'<w:jc w:val="center"/>':''}</w:pPr><w:r>${b?'<w:rPr><w:b/><w:color w:val="123D73"/></w:rPr>':''}<w:t xml:space="preserve">${xmlEscape(text)}</w:t></w:r></w:p>`;
  const body=[p('GROWISE INVEST',true,true),p('Your One-Stop Investment House',false,true),p('TECHNICAL RESEARCH REPORT',true,true),p(d.ticker.replace('.NS',''),true,true),p(d.company,false,true),p(`Generated: ${new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'long',year:'numeric'})}`,false,true),p('Prepared by: Ved Lingayat',false,true),'<w:p><w:r><w:br w:type="page"/></w:r></w:p>'];
  body.push(p(`${d.ticker.replace('.NS','')} | Technical Research`,true));
  for(const [section,obj] of reportRows(d)){
    body.push(p(section,true));
    for(const [k,v] of (Array.isArray(obj)?obj:flatten(obj))) body.push(p(`${k}: ${v==null?'N/A':v}`));
  }
  body.push(p('Technical Thesis',true),p(d.thesis),p('Analytical note: historical indicators and backtests are analytical outputs, not guarantees. Final investment decisions remain with the analyst.'));
  return body.join('');
}
async function makeWord(d,file){
  const document=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>${makeWordXml(d)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1100" w:right="900" w:bottom="1100" w:left="900"/><w:pgBorders w:offsetFrom="page"><w:top w:val="single" w:sz="8" w:space="24" w:color="123D73"/><w:left w:val="single" w:sz="8" w:space="24" w:color="123D73"/><w:bottom w:val="single" w:sz="8" w:space="24" w:color="123D73"/><w:right w:val="single" w:sz="8" w:space="24" w:color="123D73"/></w:pgBorders><w:footerReference w:type="default" r:id="rIdFooter"/><w:headerReference w:type="default" r:id="rIdHeader"/></w:sectPr></w:body></w:document>`;
  const header=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:rPr><w:b/><w:color w:val="123D73"/></w:rPr><w:t>GROWISE INVEST  |  Your One-Stop Investment House</w:t></w:r></w:p></w:hdr>`;
  const footer=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:jc w:val="center"/><w:r><w:t>Prepared by Ved Lingayat  |  Page </w:t></w:r><w:r><w:fldSimple w:instr="PAGE"/></w:r></w:p></w:ftr>`;
  const files={
    '[Content_Types].xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>`,
    '_rels/.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`,
    'word/document.xml':document,
    'word/header1.xml':header,
    'word/footer1.xml':footer,
    'word/_rels/document.xml.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>`
  };
  await new Promise((resolve,reject)=>{const out=fs.createWriteStream(file);const a=archiver('zip',{zlib:{level:9}});out.on('close',resolve);a.on('error',reject);a.pipe(out);for(const [name,content] of Object.entries(files))a.append(content,{name});a.finalize();});
}
function svgChart(d,file){const a=d.chart||[];const w=1400,h=560,p=60;const vals=a.map(x=>x.close).filter(Number.isFinite);const max=Math.max(...vals),min=Math.min(...vals),r=max-min||1;const pts=a.map((x,i)=>`${p+i/Math.max(1,a.length-1)*(w-2*p)},${h-p-(x.close-min)/r*(h-2*p)}`).join(' ');const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="100%" height="100%" rx="22" fill="#F5F9FF"/><rect x="20" y="20" width="${w-40}" height="${h-40}" rx="18" fill="#FFFFFF" stroke="#C9D8EA"/><text x="60" y="62" fill="#082A55" font-family="Arial" font-size="25" font-weight="700">${xmlEscape(d.ticker.replace('.NS',''))} Technical Price Chart</text><text x="60" y="92" fill="#66809F" font-family="Arial" font-size="14">GROWISE INVEST • Prepared by Ved Lingayat</text><polyline points="${pts}" fill="none" stroke="#176FE6" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/></svg>`;fs.writeFileSync(file,svg);}
async function createPack(d){const dir=fs.mkdtempSync(path.join(os.tmpdir(),`GROWISE_${d.ticker}_TECH_`));const xlsx=path.join(dir,`GROWISEINVEST_${d.ticker.replace('.NS','')}_Technical_Research.xlsx`),docx=path.join(dir,`GROWISEINVEST_${d.ticker.replace('.NS','')}_Technical_Research.docx`),chart=path.join(dir,`${d.ticker.replace('.NS','')}_Technical_Chart.svg`);await makeExcel(d,xlsx);await makeWord(d,docx);svgChart(d,chart);return {dir,xlsx,docx,chart};}

module.exports={research,createPack,pdf,cleanTicker};
