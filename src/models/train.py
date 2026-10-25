"""Run from repository root: python -m src.models.train [--force-graph] [--quick]."""
from __future__ import annotations
import argparse
from src.contract import mapdata
from src.models.graph import GRAPH_PATH,build_graph
from src.models.labels import read_events
from src.models.route_model import fit
from src.models.backtest import evaluate,save_backtest
from src.models.predictor import MODEL_PATH,BACKTEST_PATH


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--force-graph',action='store_true')
    parser.add_argument('--quick',action='store_true',help='Backtest only five events (smoke test)')
    args=parser.parse_args()
    graph=build_graph(force=args.force_graph)
    print('Graph:',len(graph.segments),'directed segments')
    events=read_events(graph)
    print('Training events:',len(events),'observations:',
          sum(max(0,len(x.route)-1) for x in events))
    if len(events)<2:raise SystemExit('Insufficient labelled routes: check DB waypoints and connectivity.')
    model=fit(graph,events,targets_for=mapdata.cause_targets)
    model.to_json(MODEL_PATH)
    print('Conditional logit fitted:',model.stats)
    backtest=evaluate(graph,events,max_events=5 if args.quick else None)
    save_backtest(backtest,BACKTEST_PATH)
    print('Backtest events:',backtest.n_events)
    for name,metric in backtest.summary.items():print(name,metric)
    print('Saved:',GRAPH_PATH,MODEL_PATH,BACKTEST_PATH)
    if backtest.summary['route_model']['mean_log_likelihood'] <= backtest.summary['shortest_path']['mean_log_likelihood']:
        print('WARNING: route model has NOT beaten the shortest-path baseline. Do not claim it has.')

if __name__=='__main__':main()
