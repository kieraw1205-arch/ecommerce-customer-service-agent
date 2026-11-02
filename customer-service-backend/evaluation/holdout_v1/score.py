"""Offline grading: open expected labels only after the worker has exited."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation import evaluate

def wilson(correct,total):
    if not total:return None
    z=1.959963984540054;p=correct/total;den=1+z*z/total
    center=(p+z*z/(2*total))/den
    half=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/den
    return [0 if correct==0 else max(0,center-half),1 if correct==total else min(1,center+half)]

def grade(labels,records):
    result=evaluate(labels,records,mode='holdout-offline-grading-unverified-adapter')
    for value in result['metrics'].values():value['wilson95']=wilson(value['correct'],value['denominator'])
    n=len(labels);correct=result['metrics']['task_success']['correct']
    result['all_labeled_task_rate']=correct/n
    result['category_distribution']=dict(Counter(tag for c in labels for tag in c['category']))
    latencies=[t['metrics']['duration_ms'] for r in records for t in r.get('prediction',{}).get('turns',[])]
    latencies.sort()
    result['agent_turn_trace_latency_ms']={'n':len(latencies),'mean':mean(latencies) if latencies else None,
        'p95':latencies[math.ceil(.95*len(latencies))-1] if latencies else None,'max':max(latencies) if latencies else None}
    result['uncertainty_note']='Wilson intervals describe this small authored sample; cases are correlated and not an IID production sample. Scenario-level and final-turn metrics differ from the tuned development set.'
    result['nominal_cost_cny']=None  # Provider billing/pricing is not inferred by offline grading.
    return result

def main():
    p=argparse.ArgumentParser()
    for key in ('labels','records','freeze','output'):p.add_argument('--'+key,required=True)
    a=p.parse_args();frozen=json.loads(Path(a.freeze).read_text())
    if hashlib.sha256(Path(a.labels).read_bytes()).hexdigest()!=frozen['labels_sha256']:raise RuntimeError('label drift')
    records=[json.loads(line) for line in Path(a.records).read_text().splitlines() if line]
    result=grade(json.loads(Path(a.labels).read_text()),records)
    result['freeze']=frozen
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'metrics':result['metrics'],'coverage':result['coverage']['scenarios'],'tokens':result['tokens'],'cost_cny':result['nominal_cost_cny'],'failures':[{'id':x['id'],'metrics':x['failed_metrics']} for x in result['failures']]},ensure_ascii=False))

if __name__=='__main__':main()
