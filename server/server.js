const express = require("express");
const cors = require("cors");
const mongoose = require("mongoose");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const PDFDocument = require("pdfkit");
const archiver = require("archiver");
const { research: technicalResearch, createPack: createTechnicalPack, pdf: streamTechnicalPdf, cleanTicker } = require("./technical_engine");

const app = express();
app.use(cors());
app.use(express.json({limit:"2mb"}));

const PORT = process.env.PORT || 5000;
const MONGO_URI = process.env.MONGO_URI || "mongodb://127.0.0.1:27017/growiseinvest";

const WatchSchema = new mongoose.Schema({
  ticker:{type:String,required:true,uppercase:true,trim:true},
  company:{type:String,default:""},
  addedAt:{type:Date,default:Date.now}
});
const NoteSchema = new mongoose.Schema({
  ticker:{type:String,required:true,uppercase:true,trim:true},
  title:{type:String,default:"Research Note"},
  body:{type:String,default:""},
  createdAt:{type:Date,default:Date.now}
});
const Watch = mongoose.model("Watch",WatchSchema);
const Note = mongoose.model("Note",NoteSchema);

let mongoReady=false;
mongoose.connect(MONGO_URI).then(()=>{mongoReady=true; console.log("MongoDB connected");})
.catch(err=>console.log("MongoDB unavailable. App continues with API-only mode:",err.message));

const PY = process.env.PYTHON || (process.platform==="win32" ? "python" : "python3");
const BRIDGE = path.join(__dirname,"python_engine","bridge.py");

function runPython(payload){
  return new Promise((resolve,reject)=>{
    const child=spawn(PY,[BRIDGE],{cwd:path.dirname(BRIDGE),windowsHide:true});
    let out="", err="", settled=false;
    const timer=setTimeout(()=>{
      if(settled)return; settled=true;
      child.kill();
      reject(new Error("Technical research timed out after 30 seconds. Market data provider may be unavailable or slow. Please try again."));
    },30000);
    child.stdout.on("data",d=>out+=d.toString());
    child.stderr.on("data",d=>err+=d.toString());
    child.on("error",e=>{if(!settled){settled=true;clearTimeout(timer);reject(new Error(`Python engine unavailable: ${e.message}`));}});
    child.on("close",code=>{
      if(settled)return; settled=true; clearTimeout(timer);
      if(code!==0) return reject(new Error(err||`Python engine exited with code ${code}`));
      try{
        const result=JSON.parse(out.trim());
        if(result.status==="ERROR") return reject(new Error(result.error));
        resolve(result);
      }catch(e){ reject(new Error(`Invalid engine response. ${e.message}\n${out.slice(-500)}`)); }
    });
  });
}

function normalizeTicker(t){
  let x=String(t||"").trim().toUpperCase().replace(".NS","").replace(".BO","");
  if(!/^[A-Z0-9&.-]{1,25}$/.test(x)) throw new Error("Invalid ticker format");
  return x;
}

const catalog = [
  ["TCS","Tata Consultancy Services","Technology"],["INFY","Infosys","Technology"],["HCLTECH","HCL Technologies","Technology"],
  ["WIPRO","Wipro","Technology"],["TECHM","Tech Mahindra","Technology"],["LTIM","LTIMindtree","Technology"],
  ["RELIANCE","Reliance Industries","Energy"],["ONGC","ONGC","Energy"],["NTPC","NTPC","Energy"],["POWERGRID","Power Grid","Energy"],
  ["HDFCBANK","HDFC Bank","Financial Services"],["ICICIBANK","ICICI Bank","Financial Services"],["SBIN","State Bank of India","Financial Services"],
  ["AXISBANK","Axis Bank","Financial Services"],["KOTAKBANK","Kotak Mahindra Bank","Financial Services"],
  ["ITC","ITC","Consumer Defensive"],["HINDUNILVR","Hindustan Unilever","Consumer Defensive"],["NESTLEIND","Nestle India","Consumer Defensive"],
  ["MARUTI","Maruti Suzuki","Automobiles"],["M&M","Mahindra & Mahindra","Automobiles"],["TATAMOTORS","Tata Motors","Automobiles"],
  ["EICHERMOT","Eicher Motors","Automobiles"],["SUNPHARMA","Sun Pharma","Healthcare"],["DRREDDY","Dr Reddy's Laboratories","Healthcare"],
  ["CIPLA","Cipla","Healthcare"],["DIVISLAB","Divi's Laboratories","Healthcare"],["APOLLOHOSP","Apollo Hospitals","Healthcare"],
  ["LT","Larsen & Toubro","Industrials"],["SIEMENS","Siemens","Industrials"],["ABB","ABB India","Industrials"],["BEL","Bharat Electronics","Industrials"],["HAL","Hindustan Aeronautics","Industrials"],
  ["TATASTEEL","Tata Steel","Basic Materials"],["JSWSTEEL","JSW Steel","Basic Materials"],["HINDALCO","Hindalco","Basic Materials"],["ULTRACEMCO","UltraTech Cement","Basic Materials"],["GRASIM","Grasim Industries","Basic Materials"]
];

app.get("/api/health",(req,res)=>res.json({status:"ok",service:"GROWISEINVEST MERN V27",mongo:mongoReady}));
app.get("/api/search",(req,res)=>{
  const q=String(req.query.q||"").toUpperCase().trim();
  res.json(catalog.filter(x=>!q || x[0].includes(q) || x[1].toUpperCase().includes(q)).slice(0,12)
    .map(x=>({ticker:x[0],company:x[1],sector:x[2]})));
});
app.get("/api/analysis/:ticker",async(req,res)=>{
  try{ const ticker=normalizeTicker(req.params.ticker); res.json(await technicalResearch(ticker));}
  catch(e){res.status(502).json({error:e.message});}
});

app.get("/api/technical-research/:ticker",async(req,res)=>{
  const started=Date.now();
  try{
    const ticker=normalizeTicker(req.params.ticker);
    const data=await technicalResearch(ticker);
    res.setHeader("Cache-Control","private, max-age=300");
    res.json(data);
    console.log(`Technical research ${ticker} completed in ${Date.now()-started}ms via ${data.provider}`);
  }catch(e){
    console.error(`Technical research failed after ${Date.now()-started}ms:`,e.message);
    res.status(502).json({error:e.message});
  }
});
app.post("/api/module",async(req,res)=>{
  try{const ticker=normalizeTicker(req.body.ticker); const module=String(req.body.module||"01"); res.json(await runPython({op:"module",ticker,module}));}
  catch(e){res.status(502).json({error:e.message});}
});
app.post("/api/selftest",async(req,res)=>{
  try{res.json(await runPython({op:"selftest"}));}catch(e){res.status(500).json({error:e.message});}
});

app.get("/api/watchlist",async(req,res)=>{
  if(!mongoReady) return res.json([]);
  res.json(await Watch.find().sort({addedAt:-1}).lean());
});
app.post("/api/watchlist",async(req,res)=>{
  if(!mongoReady) return res.status(503).json({error:"MongoDB is not connected"});
  try{
    const ticker=normalizeTicker(req.body.ticker);
    const row=await Watch.findOneAndUpdate({ticker},{ticker,company:req.body.company||""},{upsert:true,new:true});
    res.json(row);
  }catch(e){res.status(400).json({error:e.message});}
});
app.delete("/api/watchlist/:ticker",async(req,res)=>{
  if(!mongoReady) return res.status(503).json({error:"MongoDB is not connected"});
  await Watch.deleteOne({ticker:normalizeTicker(req.params.ticker)}); res.json({status:"deleted"});
});
app.get("/api/notes/:ticker",async(req,res)=>{
  if(!mongoReady) return res.json([]);
  res.json(await Note.find({ticker:normalizeTicker(req.params.ticker)}).sort({createdAt:-1}).lean());
});
app.post("/api/notes",async(req,res)=>{
  if(!mongoReady) return res.status(503).json({error:"MongoDB is not connected"});
  try{const row=await Note.create({ticker:normalizeTicker(req.body.ticker),title:req.body.title,body:req.body.body});res.json(row);}
  catch(e){res.status(400).json({error:e.message});}
});

app.get("/api/report/:ticker/pdf",async(req,res)=>{
  try{
    const ticker=normalizeTicker(req.params.ticker);
    const data=await runPython({op:"analysis",ticker});
    const doc=new PDFDocument({size:"A4",margin:42});
    const filename=`GROWISEINVEST_${ticker}_Research_Report.pdf`;
    res.setHeader("Content-Type","application/pdf");
    res.setHeader("Content-Disposition",`attachment; filename="${filename}"`);
    doc.pipe(res);
    doc.fontSize(22).fillColor("#10243e").text("GROWISE INVEST");
    doc.fontSize(9).fillColor("#667085").text("Your One-Stop Investment House");
    doc.moveDown(1);
    doc.fontSize(18).fillColor("#111827").text(`${data.ticker}  |  ${data.company}`);
    doc.fontSize(10).fillColor("#667085").text(`${data.sector||"Sector N/A"} • ${data.industry||"Industry N/A"}`);
    doc.moveDown();
    const cards=[["Price",fmt(data.price)],["GWI Score",fmt(data.score)],["Technical",fmt(data.technicalScore)],["Classification",data.classification]];
    cards.forEach((c,i)=>{doc.roundedRect(42+i*126,145,116,55,7).stroke("#D0D5DD");doc.fontSize(9).fillColor("#667085").text(c[0],50+i*126,155);doc.fontSize(14).fillColor("#111827").text(c[1],50+i*126,172);});
    doc.moveDown(5);
    section(doc,"Fundamental Snapshot");
    const f=data.fundamentals;
    rows(doc,[["Revenue CAGR",pct(f.revenueCagr)],["Earnings CAGR",pct(f.earningsCagr)],["EBITDA Margin",pct(f.ebitdaMargin)],["FCF Conversion",pct(f.fcfConversion)],["ROE",pct(f.roe)],["Debt / Equity",f.de==null?"N/A":`${f.de.toFixed(2)}x`]]);
    section(doc,"Technical Analysis");
    const t=data.technical;
    rows(doc,[["Price",money(t.price)],["SMA 20",money(t.sma20)],["SMA 50",money(t.sma50)],["SMA 200",money(t.sma200)],["RSI 14",num(t.rsi)],["52W High",money(t.high)],["52W Low",money(t.low)],["Technical Score",num(t.score)]]);
    section(doc,"Valuation");
    const v=data.valuation;
    rows(doc,[["DCF",money(v.dcf)],["Peer Implied",money(v.peerImplied)],["Blended Value",money(v.blended)],["Upside / Downside",pct(v.upside)],["DCF Status",v.status]]);
    section(doc,"Model Controls");
    rows(doc,[["3-Statement Balance",data.model.balanceOk?"PASS":"REVIEW"],["Data History Rows",String(data.dataQuality.historyRows)],["Financial Years",String(data.dataQuality.financialYears)]]);
    doc.moveDown();
    doc.fontSize(8).fillColor("#667085").text(data.humanDecision);
    doc.moveDown(1);
    doc.fontSize(8).text("Source control: market and financial data are provider-dependent. Missing values are shown as N/A/REVIEW rather than fabricated.");
    doc.end();
  }catch(e){res.status(502).json({error:e.message});}
});

app.get("/api/report/:ticker/technical-pdf",async(req,res)=>{
  try{ const ticker=normalizeTicker(req.params.ticker); const data=await technicalResearch(ticker); pdf(data,res); }
  catch(e){ if(!res.headersSent)res.status(502).json({error:e.message}); }
});

app.get("/api/report/:ticker/technical-pack",async(req,res)=>{
  try{
    const ticker=normalizeTicker(req.params.ticker);
    const out=await createTechnicalPack(await technicalResearch(ticker));
    const archive=archiver("zip",{zlib:{level:9}});
    const files=[out.xlsx,out.docx,out.chart].filter(fs.existsSync);
    res.setHeader("Content-Type","application/zip");
    res.setHeader("Content-Disposition",`attachment; filename="GROWISEINVEST_${ticker}_Technical_Research_Pack.zip"`);
    archive.on("error",err=>{if(!res.headersSent)res.status(500).end();}); archive.pipe(res);
    files.forEach(f=>archive.file(f,{name:path.basename(f)}));
    await archive.finalize();
  }catch(e){if(!res.headersSent)res.status(502).json({error:e.message});}
});

app.get("/api/report/:ticker/pack",async(req,res)=>{
  try{
    const ticker=normalizeTicker(req.params.ticker);
    const out=await runPython({op:"pack",ticker});
    const archive=archiver("zip",{zlib:{level:9}});
    const files=[out.excel,out.word,...(out.charts||[])].filter(Boolean).filter(fs.existsSync);
    if(!files.length) throw new Error("Research pack did not produce files");
    res.setHeader("Content-Type","application/zip");
    res.setHeader("Content-Disposition",`attachment; filename="GROWISEINVEST_${ticker}_Research_Pack.zip"`);
    archive.on("error",err=>{throw err;}); archive.pipe(res);
    files.forEach(f=>archive.file(f,{name:path.basename(f)}));
    await archive.finalize();
  }catch(e){if(!res.headersSent)res.status(502).json({error:e.message});}
});

function fmt(v){return v==null?"N/A":(typeof v==="number"?v.toFixed(2):String(v));}
function money(v){return v==null?"N/A":`₹${Number(v).toLocaleString("en-IN",{maximumFractionDigits:2})}`;}
function pct(v){return v==null?"N/A":`${(Number(v)*100).toFixed(2)}%`;}
function num(v){return v==null?"N/A":Number(v).toFixed(2);}
function section(doc,title){doc.moveDown(.7);doc.fontSize(13).fillColor("#10243e").text(title);doc.moveDown(.25);}
function rows(doc,data){data.forEach(([a,b])=>{doc.fontSize(9).fillColor("#667085").text(a,50);doc.fontSize(10).fillColor("#111827").text(String(b),260);doc.moveTo(45,doc.y+3).lineTo(550,doc.y+3).stroke("#EAECF0");doc.moveDown(.25);});}

app.listen(PORT,()=>console.log(`Server running on http://localhost:${PORT}`));
