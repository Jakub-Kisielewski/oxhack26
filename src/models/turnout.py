"""Small-sample turnout estimate: cause-specific median and empirical uncertainty."""
from __future__ import annotations
import statistics
from src.contract.types import MarchContext,TurnoutEstimate
from src.models.labels import TrainingEvent


def estimate(context:MarchContext,events:list[TrainingEvent])->TurnoutEstimate:
    if context.turnout is not None:
        n=max(1,int(context.turnout));return TurnoutEstimate(n,n,n,'user')
    sample=[int(e.context['turnout']) for e in events if (not context.cause or e.cause==context.cause)]
    if not sample:sample=[10000]
    median=int(statistics.median(sample))
    return TurnoutEstimate(median,max(100,int(median*.5)),max(100,int(median*1.8)),'model')
