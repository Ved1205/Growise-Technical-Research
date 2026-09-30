# GROWISE INVEST - MERN Technical Research Workstation

## What this version does

Enter an NSE ticker once, for example `TCS`, `RELIANCE`, or `INFY`. The application automatically runs the complete technical research workflow and displays the result.

```text
Ticker
  ↓
Market Data
  ↓
Trend
  ↓
Momentum
  ↓
Volume
  ↓
Volatility
  ↓
Market Structure
  ↓
Support / Resistance
  ↓
Breakout
  ↓
Divergence
  ↓
Multi-Timeframe
  ↓
Relative Strength
  ↓
Market / Sector Regime
  ↓
Technical Events
  ↓
Backtesting
  ↓
Technical Risk
  ↓
Technical Score
  ↓
Technical Thesis
  ↓
PDF / Excel / Word / Chart
```

You do **not** enter module `77`. The number is an internal architecture designation only.

## Important runtime change

The live technical research route is now implemented directly in Node.js. It does **not** start the large Python V27 fundamental/DCF engine for a ticker search. This removes the previous source of long waits.

Market data providers are attempted with short timeouts:

1. Yahoo Finance Chart endpoint
2. NSE historical CSV endpoint
3. Successful real market data is cached locally for later repeat requests

If a provider is unavailable, the application reports the provider error instead of spinning indefinitely.

## Start from terminal

### Terminal 1

```powershell
cd "C:\Users\VED LINGAYAT\Downloads\GROWISEINVEST_V27_MERN_TECHNICAL_RESEARCH_FINAL_RUNNING\GROWISEINVEST_V27_MERN_EDITION\server"
npm install
npm start
```

Expected:

```text
Server running on http://localhost:5000
```

### Terminal 2

```powershell
cd "C:\Users\VED LINGAYAT\Downloads\GROWISEINVEST_V27_MERN_TECHNICAL_RESEARCH_FINAL_RUNNING\GROWISEINVEST_V27_MERN_EDITION\client"
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

### One-click Windows start

Double-click `RUN_TECHNICAL_RESEARCH.bat`.

## Direct API test

Before using the browser, test:

```powershell
Invoke-WebRequest http://localhost:5000/api/health
```

Then:

```powershell
Invoke-WebRequest "http://localhost:5000/api/technical-research/TCS" -TimeoutSec 40
```

A JSON response means the research engine is working.

## Downloads

The result page provides:

- Technical PDF
- Technical Research Pack ZIP
- Excel-compatible research workbook
- Word-compatible research document
- Technical SVG chart

## Data integrity

The application does not manufacture market prices. If no live provider and no previously cached real dataset is available, the request fails with a clear data-provider error.

Historical technical indicators and backtests are analytical outputs. They are not guarantees or investment recommendations.
