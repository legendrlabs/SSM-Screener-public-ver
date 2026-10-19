"""Run the full universe and replay an older engine on identical cached inputs.

The SEC contact stays in the runner's environment. No source cache or secrets
are written to artifacts. Only standard outputs and bounded evidence metadata
are retained. Both engines use the same configuration, discovered filings,
market snapshots and successful/failed SEC responses.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from ssm import pipeline
from ssm.providers.sec import SecClient
from ssm.report import write_outputs
from ssm.validation_audit import compare_candidates, summarize_invariants

class FrozenInputs(SecClient):
    def __init__(self):
        super().__init__();self.responses={};self.errors={};self.discovery={}
    def _get(self,url):
        if url in self.errors:raise self.errors[url]
        if url not in self.responses:
            try:self.responses[url]=super()._get(url)
            except Exception as exc:self.errors[url]=exc;raise
        return self.responses[url]
    def recent_filings(self,days,forms):
        key=(days,tuple(forms))
        if key not in self.discovery:self.discovery[key]=super().recent_filings(days,forms)
        return self.discovery[key]

def load_previous(source):
    package=Path(source)/'ssm'
    spec=importlib.util.spec_from_file_location('ssm_previous',package/'__init__.py',submodule_search_locations=[str(package)])
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    from ssm_previous import pipeline as previous
    return previous

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-source',required=True);parser.add_argument('--baseline-commit',required=True)
    parser.add_argument('--days',type=int,default=7);parser.add_argument('--out',default='output')
    args=parser.parse_args();sec=FrozenInputs();market={}
    original_bulk=pipeline.market_snapshots;original_single=pipeline.market_snapshot
    def bulk(tickers):
        missing=[t for t in tickers if t not in market]
        if missing:
            values=original_bulk(missing)
            for ticker in missing:market[ticker]=values.get(ticker,{'price':None,'adv20_usd':None})
        return {t:market[t] for t in tickers}
    def single(ticker):
        if ticker not in market:market[ticker]=original_single(ticker)
        return market[ticker]
    pipeline.SecClient=lambda:sec;pipeline.market_snapshots=bulk;pipeline.market_snapshot=single
    print('Starting current full-universe scan',flush=True)
    current,cfg=pipeline.scan(args.days);write_outputs(current,cfg,args.out)
    print(f'Current scan complete: {len(current)} securities; replaying baseline from frozen inputs',flush=True)
    previous=load_previous(args.baseline_source)
    previous.SecClient=lambda:sec;previous.market_snapshots=bulk;previous.market_snapshot=single
    baseline,_=previous.scan(args.days)
    audit=summarize_invariants(current)
    audit['comparison']=compare_candidates(current,baseline)
    audit['baseline_source_commit']=args.baseline_commit
    audit['input_scope']={'discovery':'shared frozen universe','market':'shared snapshots','SEC':'shared successful and failed responses',
                          'sec_responses_cached':len(sec.responses),'sec_errors_cached':len(sec.errors)}
    output=Path(args.out)
    (output/'validation_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    (output/'baseline_candidates.json').write_text(json.dumps([c.to_dict() for c in baseline]),encoding='utf-8')
    print(json.dumps({'candidate_count':len(current),'baseline_count':len(baseline),
                      'invariants':{k:{'observed':v['observed'],'violations':v['violations']} for k,v in audit['invariants'].items()},
                      'comparison':{k:v for k,v in audit['comparison'].items() if k!='changes'}}),flush=True)

if __name__=='__main__':main()
