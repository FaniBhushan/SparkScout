"""Public data contracts for ScoutSpark."""

from .candidate_idea import CandidateIdea
from .candidate_assessment import CandidateAssessment, CriterionJudgment, GateJudgment
from .critic_result import CriticResult
from .evaluation_configuration import CriterionDefinition, EvaluationConfiguration
from .evaluation_result import CriterionScore, EvaluationResult, HardGateResult
from .final_proposal import AlternativeApproach, FinalProposal, ProposalEvaluationPlan
from .input_request import InputRequest, SkillLevel
from .library_result import LibraryResult
from .orchestration_result import OrchestrationResult, RankedCandidate
from .resolved_search_configuration import ResolvedProvider, ResolvedSearchConfiguration
from .search_defaults import SearchDefaults, SearchLimits, SearchPreset
from .retrieved_chunk import RetrievedChunk
from .scout_query import ScoutQuery, SourceQuery
from .scout_result import ScoutResult
from .source_configuration import (
    DomainRoute,
    EvidenceTier,
    ProviderDefinition,
    SourceConfiguration,
    SourcePolicy,
    SourceTypeDefinition,
)
from .source_record import RetrievalStatus, SourceChunk, SourceRecord
from .usage_record import UsageRecord

__all__ = [
    "AlternativeApproach",
    "CandidateAssessment",
    "CandidateIdea",
    "CriticResult",
    "CriterionDefinition",
    "CriterionJudgment",
    "CriterionScore",
    "DomainRoute",
    "EvaluationResult",
    "EvaluationConfiguration",
    "EvidenceTier",
    "FinalProposal",
    "HardGateResult",
    "InputRequest",
    "LibraryResult",
    "OrchestrationResult",
    "ProposalEvaluationPlan",
    "ProviderDefinition",
    "ResolvedProvider",
    "ResolvedSearchConfiguration",
    "RankedCandidate",
    "SearchDefaults",
    "SearchLimits",
    "SearchPreset",
    "RetrievalStatus",
    "RetrievedChunk",
    "GateJudgment",
    "ScoutQuery",
    "ScoutResult",
    "SkillLevel",
    "SourceChunk",
    "SourceConfiguration",
    "SourcePolicy",
    "SourceQuery",
    "SourceRecord",
    "SourceTypeDefinition",
    "UsageRecord",
]
