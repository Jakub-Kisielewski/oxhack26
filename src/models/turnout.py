"""Small-sample turnout estimate: cause-specific median and empirical uncertainty."""
from __future__ import annotations
import statistics
from src.contract.types import MarchContext,TurnoutEstimate
from src.models.labels import TrainingEvent


def base(context:MarchContext,events:list[TrainingEvent])->tuple[int,str]:
    """Median turnout of past marches with this cause (all marches if the cause is unknown or unseen)."""
    sample=[int(e.context['turnout']) for e in events if context.cause and e.cause==context.cause]
    label=f'median of {len(sample)} past {context.cause.replace("_"," ")} marches' if sample else ''
    if not sample:
        sample=[int(e.context['turnout']) for e in events]
        label=f'median of all {len(sample)} past marches' if sample else 'default'
    return (int(statistics.median(sample)) if sample else 10000),label


def estimate(context:MarchContext,events:list[TrainingEvent],adjusted:int|None=None)->TurnoutEstimate:
    """`adjusted` is the base after condition multipliers (see conditions.py)."""
    if context.turnout is not None:
        n=max(1,int(context.turnout));return TurnoutEstimate(n,n,n,'user')
    median=adjusted if adjusted is not None else base(context,events)[0]
    return TurnoutEstimate(median,max(100,int(median*.5)),max(100,int(median*1.8)),'model')
