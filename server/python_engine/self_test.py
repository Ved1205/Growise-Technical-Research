import importlib.util, math, ast, pathlib, numpy as np, pandas as pd

spec=importlib.util.spec_from_file_location("models","engine/models.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

idx=pd.Index(["Y1","Y2","Y3","Y4","Y5"])
raw={
"revenue":[100,110,121,133,146],"ebitda":[20,22,24,27,30],"net_income":[10,11,12,13,15],
"cfo":[14,15,16,18,20],"capex":[5,6,6,7,8],"cash":[20,21,22,23,24],"debt":[10,9,8,7,6],
"equity":[50,55,60,66,72],"assets":[80,85,90,96,102],"current_assets":[30,32,34,36,38],
"current_liabilities":[15,15,16,17,18],"ebit":[18,20,22,24,27],"da":[2,2,2,3,3],
"interest":[1,1,1,1,1],"tax":[2,2,2,3,3]}
hist={k:pd.Series(v,index=idx,dtype=float) for k,v in raw.items()}
a={"revenue_growth":.10,"ebitda_margin":.20,"tax_rate":.25,"nwc_pct":.05,
   "capex_pct":.06,"da_pct":.035,"interest_rate":.07,"payout":.25}
model=m.forecast_three_statement(hist,a,5)
assert np.isfinite(model["Balance Check"]).all()
assert float(model["Balance Check"].abs().max()) < .01

dc=m.dcf(100,12,6,24,shares=10)
assert dc.status == "PASS" and np.isfinite(dc.target)
assert np.isfinite(np.asarray(dc.sensitivity,dtype=float)).sum() > 0

returns=pd.Series(np.random.default_rng(42).normal(0,.02,500))
mc=m.monte_carlo(100,returns,100,20,42)
assert all(k in mc["percentiles"] for k in ["P5","P50","P95"])
assert 0 <= mc["positive_prob"] <= 1

print("GROWISE SELF-TEST: PASS")
print(f"Maximum model balance residual: {model['Balance Check'].abs().max():.3e}")
print(f"DCF target: {dc.target:.2f}")
print(f"Monte Carlo P50: {mc['percentiles']['P50']:.2f}")

# Production route regression: verify the public V27 terminal has all required handlers.
root=pathlib.Path(__file__).resolve().parent
src=(root / "GROWISEINVEST.py").read_text(errors="ignore")
tree=ast.parse(src)
funcs={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
required={
"01":"show_research","02":"show_financials","03":"show_model_cmd","04":"show_dcf","05":"show_valuation_lab","06":"show_technical","07":"show_quant_cmd","08":"show_risk","09":"show_peers","10":"compare","11":"export_excel","12":"market_status","13":"gwi_score","14":"data_quality","15":"backtest","16":"market_regime","17":"portfolio_risk","18":"portfolio_optimizer","19":"research_note","20":"_v24_security_master","21":"conference_call_analyzer","22":"ipo_research","23":"news_tomorrow_events","24":"earnings_intelligence","25":"fundamental_inflection","26":"forensic_engine","27":"what_changed_engine","28":"event_study_engine","29":"scenario_engine","30":"ownership_flow_engine","31":"moat_analyzer","32":"valuation_bridge","33":"corporate_actions_engine","34":"filings_intelligence","35":"red_flag_engine","36":"investment_committee_mode","37":"factor_exposure_v8","38":"quality_scorecard","39":"growth_quality_lab","40":"capital_allocation_lab","41":"sotp_lab","42":"dividend_discount_valuation","43":"residual_income_valuation","44":"probability_valuation","45":"valuation_decomposition_v8","46":"factor_exposure_v8","47":"thesis_tracker","48":"portfolio_attribution","49":"model_control_center","51":"live_market_engine","90":"_v22_intelligence","100":"fair_value_lab"}
missing=[(n,f) for n,f in required.items() if f not in funcs]
assert not missing, f"Missing handlers: {missing}"
dstart=src.index("def _v17_dispatch_same_ticker")
dend=src.index("\nmain=final_main_v17",dstart)
dispatch=src[dstart:dend]
assert "f'{int(n):02d}' if len(n) <= 2" in dispatch
for n in ("04","05","07","08","09","19","51"):
    assert f"'{n}'" in dispatch or f"n=='{n}'" in dispatch
for n in ("01","02","03","06","20","90","98"):
    assert f"n=='{n}'" in src or f"n == '{n}'" in src
assert src.count("if __name__=='__main__':")==1
print(f"V27 ROUTE REGRESSION: PASS ({len(required)} handlers)")
