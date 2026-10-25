"""Weighted conditional logit on directed street-segment choices, trained by L-BFGS-B."""
from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp,softmax
from scipy.sparse import csr_matrix
from src.models.features import NAMES,feature_vector
from src.models.labels import TrainingEvent,history_counts
from src.models.graph import MarchGraph

# Shrink noisy estimates toward small, interpretable prior effects (standardised features).
PRIOR=np.array([.5,.1,.05,.1,.1,-.5,.1,-.15,-.3,.05,.05],dtype=float)

@dataclass
class ChoiceModel:
    theta:list[float]=field(default_factory=lambda:list(PRIOR))
    mean:list[float]=field(default_factory=lambda:[0.0]*len(NAMES))
    std:list[float]=field(default_factory=lambda:[1.0]*len(NAMES))
    features:tuple[str,...]=NAMES
    fitted:bool=False
    stats:dict=field(default_factory=dict)

    def to_json(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        with open(path,'w') as f:
            json.dump(dict(theta=self.theta,mean=self.mean,std=self.std,features=self.features,
                           fitted=self.fitted,stats=self.stats),f,indent=2)

    @classmethod
    def from_json(cls,path:Path):
        with open(path) as f:d=json.load(f)
        if list(d['features'])!=list(NAMES):raise ValueError('Feature version mismatch; retrain model')
        return cls(d['theta'],d['mean'],d['std'],tuple(d['features']),d['fitted'],d['stats'])

    def probs(self,g:MarchGraph,current:str, candidates:list[str],destination:tuple[float,float],
              context:dict|None=None,history:dict|None=None,targets:list|None=None):
        if not candidates:return np.array([])
        X=np.stack([feature_vector(g,current,b,destination,context,history,targets) for b in candidates])
        x=(X-np.asarray(self.mean))/np.maximum(np.asarray(self.std),1e-6)
        return softmax(np.clip(x@np.asarray(self.theta),-100,100))

    def transition_matrix(self,g:MarchGraph, ids:list[str],context:dict,destination:tuple[float,float],
                          history:dict|None=None,targets:list|None=None) -> csr_matrix:
        index={sid:i for i,sid in enumerate(ids)}
        rows=[];cols=[];values=[]
        for a in ids:
            candidates=[b for b in g.next_ids(a) if b in index]
            for b,p in zip(candidates,self.probs(g,a,candidates,destination,context,history,targets)):
                rows.append(index[a]);cols.append(index[b]);values.append(float(p))
        return csr_matrix((values,(rows,cols)),shape=(len(ids),len(ids)))


def fit(g:MarchGraph,events:list[TrainingEvent],targets_for=None,
        reg:float=2.0,maxiter:int=90) -> ChoiceModel:
    history=history_counts(events)
    arrays=[];indices=[];weights=[]; n_events=0
    for event in events:
        targ=targets_for(event.cause) if targets_for else []
        n=0
        for k,(current,chosen) in enumerate(zip(event.route,event.route[1:])):
            options=g.next_ids(current)
            if len(options)<2 or chosen not in options:continue
            X=np.stack([feature_vector(g,current,b,event.destination,event.context,history,targ) for b in options])
            arrays.append(X);indices.append(options.index(chosen));weights.append(event.weight[k+1]);n+=1
        n_events+=bool(n)
    if not arrays:return ChoiceModel(stats={'n_events':0,'n_choices':0})
    sizes=[len(a) for a in arrays]
    X=np.concatenate(arrays)
    means=X.mean(axis=0);std=X.std(axis=0);std[std<1e-6]=1.0
    X=(X-means)/std
    offsets=np.cumsum([0]+sizes)
    prior=PRIOR.copy();chosen=np.asarray(indices);w=np.asarray(weights,dtype=float)
    chosen_idx=offsets[:-1]+chosen
    repeated_weights=np.repeat(w,sizes)
    weighted_chosen_X=w@X[chosen_idx]

    def loss_grad(theta):
        # Batched ragged softmax: avoids tens of thousands of Python loops per
        # optimiser iteration and makes leave-one-event-out backtests feasible.
        logits=X@theta
        maxima=np.maximum.reduceat(logits,offsets[:-1])
        expvalues=np.exp(logits-np.repeat(maxima,sizes))
        totals=np.add.reduceat(expvalues,offsets[:-1])
        probs=expvalues/np.repeat(totals,sizes)
        loss=np.dot(w,maxima+np.log(totals)-logits[chosen_idx])
        grad=X.T@(probs*repeated_weights)-weighted_chosen_X
        deviation=theta-prior
        return float(loss+reg/2*(deviation@deviation)), grad+reg*deviation

    result=minimize(loss_grad,prior,method='L-BFGS-B',jac=True,
                    options={'maxiter':maxiter,'ftol':1e-7})
    return ChoiceModel(result.x.tolist(),means.tolist(),std.tolist(),NAMES,True,
                       {'n_events':n_events,'n_choices':len(arrays),'weighted_choices':float(w.sum()),
                        'loss':float(result.fun),'converged':bool(result.success)})
