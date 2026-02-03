"""
Workflow module for comment automation state machine.
"""

from .state_machine import CommentWorkflowFSM, WorkflowState, WorkflowResult
from .consumption import ConsumptionPhase
from .research import ResearchPhase
from .interaction import InteractionPhase
from .finalization import FinalizationPhase

__all__ = [
    "CommentWorkflowFSM",
    "WorkflowState",
    "WorkflowResult",
    "ConsumptionPhase",
    "ResearchPhase",
    "InteractionPhase",
    "FinalizationPhase",
]
