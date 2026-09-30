# GROWISE INVEST V27 MERN Edition
## Project Report

### 1. Project Title
GROWISE INVEST V27 - MERN Equity Research Workstation

### 2. Objective
To provide a professional equity research workstation where an analyst can search an NSE ticker and access market data, technical analysis, financial quality, valuation, quantitative risk and the broader V27 research module stack from a single React interface.

### 3. Technology Stack
- MongoDB: persistent watchlist and research notes
- Express.js: REST API layer
- React + Vite: professional workstation interface
- Node.js: application server and report delivery
- Python V27 engine: retained analytical engine for parity with the supplied V27 system
- PDFKit: downloadable PDF research report
- Archiver: downloadable institutional research pack

### 4. Core Workflow
Ticker search -> Express API -> V27 analytical engine -> normalized JSON -> React workstation -> report download.

### 5. Main Features
1. Ticker-first security search
2. Market price and company overview
3. Technical structure
4. SMA 20/50/200 and RSI
5. Price/EMA chart layer
6. Fundamental quality
7. DCF and valuation stack
8. 3-statement model control
9. Monte Carlo and risk analytics
10. Peer comparison
11. V27 research module execution
12. MongoDB watchlist
13. Downloadable PDF report
14. Word/Excel/chart research pack
15. Data quality and human-decision separation

### 6. UI/UX Design
The workstation uses a dark institutional research theme, compact metric cards, a left research-module rail, ticker-first search, restrained borders, clear hierarchy, responsive layouts and dedicated research output panels.

### 7. Error-Control Design
- API input validation
- Provider failures returned as controlled errors
- Missing provider fields represented as N/A/REVIEW
- MongoDB failure does not prevent the analytical interface from loading
- Python engine output is validated as JSON before reaching React
- Download endpoints verify generated files
- V27 self-test remains bundled

### 8. Viva Explanation
MongoDB stores user-specific research state. Express and Node expose the API. React provides the user interface. The original V27 analytical engine is retained behind the Express API so the MERN interface can present the same research logic without converting it into a weaker demo implementation.

### 9. Disclaimer
This project is a research and academic software system. Market data may be delayed, unavailable or provider-dependent. Automated analytical output is not a substitute for independent analyst judgment.
