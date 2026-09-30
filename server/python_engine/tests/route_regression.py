"""Dependency-free structural regression test for the GROWISEINVEST V27 terminal.
This does not claim live market connectivity; it verifies the application has all
public handlers and that the canonical/legacy routing contract is intact.
"""
from pathlib import Path
import ast, re, sys

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'GROWISEINVEST.py'
text=SRC.read_text(errors='ignore')
tree=ast.parse(text)
funcs={n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
required={
'01':'show_research','02':'show_financials','03':'show_model_cmd','04':'show_dcf','05':'show_valuation_lab',
'06':'show_technical','07':'show_quant_cmd','08':'show_risk','09':'show_peers','10':'compare','11':'export_excel',
'12':'market_status','13':'gwi_score','14':'data_quality','15':'backtest','16':'market_regime','17':'portfolio_risk',
'18':'portfolio_optimizer','19':'research_note','20':'_v24_security_master','21':'conference_call_analyzer',
'22':'ipo_research','23':'news_tomorrow_events','24':'earnings_intelligence','25':'fundamental_inflection',
'26':'forensic_engine','27':'what_changed_engine','28':'event_study_engine','29':'scenario_engine',
'30':'ownership_flow_engine','31':'moat_analyzer','32':'valuation_bridge','33':'corporate_actions_engine',
'34':'filings_intelligence','35':'red_flag_engine','36':'investment_committee_mode','37':'factor_exposure_v8',
'38':'quality_scorecard','39':'growth_quality_lab','40':'capital_allocation_lab','41':'sotp_lab','42':'dividend_discount_valuation',
'43':'residual_income_valuation','44':'probability_valuation','45':'valuation_decomposition_v8','46':'factor_exposure_v8',
'47':'thesis_tracker','48':'portfolio_attribution','49':'model_control_center','51':'live_market_engine',
'90':'_v22_intelligence','100':'fair_value_lab'}
missing=[(n,f) for n,f in required.items() if f not in funcs]
assert not missing, f'Missing handlers: {missing}'
start=text.index('def _v17_dispatch_same_ticker')
end=text.index('\nmain=final_main_v17',start)
dispatch=text[start:end]
assert "f'{int(n):02d}' if len(n) <= 2" in dispatch, 'Leading-zero normalization missing'
for n in ('04','05','07','08','09','19','51'):
    assert f"'{n}'" in dispatch or f"n=='{n}'" in dispatch, f'Critical route missing: {n}'
for n in ('01','02','03','06','20','90','98'):
    assert (f"n=='{n}'" in text or f"n == '{n}'" in text), f'Canonical route missing: {n}'
assert text.count("if __name__=='__main__':") == 1, 'Multiple canonical entrypoints found'
assert 'def _v24_diagnostics' in text and 'SYSTEM DIAGNOSTICS / V27' in text
print('V27 ROUTE REGRESSION: PASS')
print(f'Handlers checked: {len(required)}')
print('Critical routes: 04,05,07,08,09,19,51')
print('Canonical routes: 01,02,03,06,20,90,98')
print('Entrypoints: 1')
