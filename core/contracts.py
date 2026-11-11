"""Canonical, validated API and persistence boundary models (Pydantic v2)."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class Difficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    UNKNOWN = "UNKNOWN"


class IngestionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL_MISSING_TESTS = "PARTIAL_MISSING_TESTS"
    PARTIAL_MISSING_TEMPLATE = "PARTIAL_MISSING_TEMPLATE"
    PARTIAL_MISSING_SOLUTION = "PARTIAL_MISSING_SOLUTION"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"


class Verdict(str, Enum):
    ACCEPTED = "AC"
    WRONG_ANSWER = "WA"
    TIME_LIMIT_EXCEEDED = "TLE"
    MEMORY_LIMIT_EXCEEDED = "MLE"
    RUNTIME_ERROR = "RE"
    COMPILATION_ERROR = "CE"
    PENDING = "PENDING"


class TestCaseContract(BaseModel):
    id: Optional[int] = None
    input_data: str = Field(..., description="Raw or serialized stdin/arguments for the test case")
    expected_output: str = Field(..., description="Expected stdout or serialized return value")
    is_sample: bool = Field(default=False, description="True if visible to user in UI; False if hidden judge test")
    explanation: Optional[str] = None
    order_index: int = 0


class CodeTemplateContract(BaseModel):
    language: str = Field(default="python", description="e.g., python, javascript, cpp, java")
    starter_code: str = Field(..., description="User-facing boilerplate function/class signature")
    driver_code: Optional[str] = Field(default=None, description="Hidden wrapper that parses input_data and invokes starter_code")


class SolutionContract(BaseModel):
    language: str = Field(default="python")
    solution_code: str
    approach_explanation_md: Optional[str] = None
    time_complexity: Optional[str] = None
    space_complexity: Optional[str] = None


class AuditMetadataContract(BaseModel):
    has_statement: bool = False
    has_sample_tests: bool = False
    has_hidden_tests: bool = False
    has_starter_code: bool = False
    has_solution: bool = False
    status: IngestionStatus = IngestionStatus.NEEDS_MANUAL_REVIEW
    missing_fields: List[str] = Field(default_factory=list)
    raw_source_hash: Optional[str] = None


class ProblemCanonicalContract(BaseModel):
    id: int
    external_id: Optional[str] = None
    slug: str
    title: str
    difficulty: Difficulty = Difficulty.UNKNOWN
    statement_md: str = "Problem statement pending enrichment."
    constraints_md: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    templates: Dict[str, CodeTemplateContract] = Field(default_factory=dict)
    test_cases: List[TestCaseContract] = Field(default_factory=list)
    solutions: Dict[str, SolutionContract] = Field(default_factory=dict)
    time_limit_ms: int = 2000
    memory_limit_kb: int = 262144
    audit: AuditMetadataContract


class ProblemSummaryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    is_ready_to_solve: bool
    user_status: Optional[str] = "UNSOLVED"


class SubmissionHistoryDTO(BaseModel):
    id: str
    problem_id: int
    language: str
    overall_verdict: Verdict
    passed_count: int
    total_count: int
    max_runtime_ms: float
    created_at: datetime
    source_code: str
    ast_metrics: Dict[str, Any] = Field(default_factory=dict)


class ProblemWorkspaceDTO(BaseModel):
    id: int
    slug: str
    title: str
    difficulty: Difficulty
    statement_md: str
    constraints_md: Optional[str]
    tags: List[str]
    templates: Dict[str, str]
    sample_test_cases: List[TestCaseContract]
    time_limit_ms: int
    memory_limit_kb: int


class ExecutionRequestDTO(BaseModel):
    problem_id: int
    language: str
    source_code: str
    mode: str = Field(default="run", pattern="^(run|submit)$")
    custom_inputs: Optional[List[str]] = None


class TestCaseResultDTO(BaseModel):
    test_case_index: int
    passed: bool
    verdict: Verdict
    input_data: Optional[str] = None
    actual_output: Optional[str] = None
    expected_output: Optional[str] = None
    runtime_ms: float = 0.0
    error_message: Optional[str] = None


class ExecutionResponseDTO(BaseModel):
    submission_id: str
    problem_id: int
    overall_verdict: Verdict
    passed_count: int
    total_count: int
    max_runtime_ms: float
    results: List[TestCaseResultDTO]
    plugin_payloads: Dict[str, Any] = Field(default_factory=dict, description="Socket for AI hints, AST metrics, etc.")
