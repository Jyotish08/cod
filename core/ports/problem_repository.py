"""Problem repository interface and SQLAlchemy adapter."""
from abc import ABC, abstractmethod
import hashlib
import json
from typing import Any, Dict, List

from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.orm import Session, selectinload

from core.contracts import (AuditMetadataContract, CodeTemplateContract, Difficulty,
    ExecutionRequestDTO, ExecutionResponseDTO, IngestionStatus, ProblemCanonicalContract,
    ProblemSummaryDTO, ProblemWorkspaceDTO, SubmissionHistoryDTO,
    SolutionContract, TestCaseContract)
from core.models import Problem, SubmissionModel


class IProblemRepository(ABC):
    @abstractmethod
    def list_problems(self, difficulty=None, tags=None, only_complete=False, limit=50, offset=0) -> List[ProblemSummaryDTO]: ...

    @abstractmethod
    def get_workspace_problem(self, slug_or_id) -> ProblemWorkspaceDTO: ...

    @abstractmethod
    def get_judge_payload(self, problem_id) -> ProblemCanonicalContract: ...

    @abstractmethod
    def get_enrichment_queue(self, missing_field_type) -> List[int]: ...

    @abstractmethod
    def record_submission(self, request: ExecutionRequestDTO, response: ExecutionResponseDTO) -> None: ...

    @abstractmethod
    def get_problem_submissions(self, problem_id: int, limit: int = 20) -> List[SubmissionHistoryDTO]: ...

    @abstractmethod
    def get_user_stats(self) -> Dict[str, Any]: ...


class SqlAlchemyProblemRepository(IProblemRepository):
    def __init__(self, session: Session):
        self.session = session

    def list_problems(self, difficulty=None, tags=None, only_complete=False, limit=50, offset=0) -> List[ProblemSummaryDTO]:
        stmt = select(Problem).order_by(Problem.id).limit(limit).offset(offset)
        if difficulty:
            value = difficulty.value if isinstance(difficulty, Difficulty) else str(difficulty).upper()
            stmt = stmt.where(Problem.difficulty == value)
        if only_complete:
            stmt = stmt.where(Problem.ingestion_status == IngestionStatus.COMPLETE.value)
        if tags:
            for tag in tags:
                stmt = stmt.where(Problem.tags.contains([tag]))
        rows = self.session.scalars(stmt).all()
        statuses = self._submission_statuses([p.id for p in rows])
        return [ProblemSummaryDTO(id=p.id, slug=p.slug, title=p.title, difficulty=p.difficulty,
            tags=p.tags or [], is_ready_to_solve=bool(p.has_sample_tests and p.has_starter_code),
            user_status=statuses.get(p.id, "UNSOLVED")) for p in rows]

    def _submission_statuses(self, problem_ids: List[int]) -> dict[int, str]:
        if not problem_ids:
            return {}
        attempted = set(self.session.scalars(select(SubmissionModel.problem_id).where(
            SubmissionModel.mode == "submit", SubmissionModel.problem_id.in_(problem_ids)).distinct()).all())
        solved = set(self.session.scalars(select(SubmissionModel.problem_id).where(
            SubmissionModel.mode == "submit", SubmissionModel.overall_verdict == "AC",
            SubmissionModel.problem_id.in_(problem_ids)).distinct()).all())
        return {problem_id: ("SOLVED" if problem_id in solved else "ATTEMPTED")
                for problem_id in attempted}

    @staticmethod
    def _history(row: SubmissionModel) -> SubmissionHistoryDTO:
        return SubmissionHistoryDTO(id=row.id, problem_id=row.problem_id,
            language=row.language, overall_verdict=row.overall_verdict,
            passed_count=row.passed_count, total_count=row.total_count,
            max_runtime_ms=row.max_runtime_ms, created_at=row.created_at,
            source_code=row.source_code, ast_metrics=row.ast_metrics_json or {})

    def record_submission(self, request: ExecutionRequestDTO, response: ExecutionResponseDTO) -> None:
        metrics = response.plugin_payloads.get("ast_metrics", {})
        self.session.add(SubmissionModel(id=response.submission_id,
            problem_id=response.problem_id, language=request.language,
            source_code=request.source_code, mode=request.mode,
            overall_verdict=response.overall_verdict.value,
            passed_count=response.passed_count, total_count=response.total_count,
            max_runtime_ms=response.max_runtime_ms, ast_metrics_json=metrics))
        self.session.commit()

    def get_problem_submissions(self, problem_id: int, limit: int = 20) -> List[SubmissionHistoryDTO]:
        stmt = (select(SubmissionModel).where(SubmissionModel.problem_id == problem_id)
                .order_by(SubmissionModel.created_at.desc(), SubmissionModel.id.desc())
                .limit(max(1, min(limit, 100))))
        return [self._history(row) for row in self.session.scalars(stmt).all()]

    def get_user_stats(self) -> Dict[str, Any]:
        total = self.session.scalar(select(func.count()).select_from(SubmissionModel)) or 0
        accepted = self.session.scalar(select(func.count()).select_from(SubmissionModel).where(
            SubmissionModel.overall_verdict == "AC")) or 0
        solved_rows = self.session.execute(select(Problem.difficulty,
            func.count(distinct(Problem.id))).join(SubmissionModel,
            SubmissionModel.problem_id == Problem.id).where(
            SubmissionModel.mode == "submit", SubmissionModel.overall_verdict == "AC")
            .group_by(Problem.difficulty)).all()
        solved = {"Easy": 0, "Medium": 0, "Hard": 0}
        for difficulty, count in solved_rows:
            label = {"EASY": "Easy", "MEDIUM": "Medium", "HARD": "Hard"}.get(difficulty)
            if label:
                solved[label] = count
        recent = self.session.scalars(select(SubmissionModel)
            .order_by(SubmissionModel.created_at.desc(), SubmissionModel.id.desc()).limit(10)).all()
        return {"solved_by_difficulty": solved, "total_submissions": total,
            "acceptance_rate": round((accepted / total * 100) if total else 0.0, 2),
            "recent_activity": [self._history(row) for row in recent]}

    def _problem(self, slug_or_id) -> Problem:
        stmt = select(Problem).options(selectinload(Problem.test_cases),
            selectinload(Problem.code_templates), selectinload(Problem.solutions))
        if isinstance(slug_or_id, int) or (isinstance(slug_or_id, str) and slug_or_id.isdigit()):
            stmt = stmt.where(or_(Problem.id == int(slug_or_id), Problem.external_id == str(slug_or_id)))
        else:
            stmt = stmt.where(Problem.slug == str(slug_or_id))
        result = self.session.scalars(stmt).first()
        if result is None:
            raise LookupError(f"Problem not found: {slug_or_id}")
        return result

    def get_workspace_problem(self, slug_or_id) -> ProblemWorkspaceDTO:
        p = self._problem(slug_or_id)
        # Construct a deliberately narrow DTO: hidden tests, raw source and solutions
        # are never traversed or serialized into the client response.
        templates = {t.language: t.starter_code for t in p.code_templates}
        samples = [TestCaseContract(id=t.id, input_data=t.input_data,
            expected_output=t.expected_output, is_sample=True, explanation=t.explanation,
            order_index=t.order_index) for t in p.test_cases if t.is_sample]
        return ProblemWorkspaceDTO(id=p.id, slug=p.slug, title=p.title,
            difficulty=p.difficulty, statement_md=p.statement_md, constraints_md=p.constraints_md,
            tags=p.tags or [], templates=templates, sample_test_cases=samples,
            time_limit_ms=p.time_limit_ms, memory_limit_kb=p.memory_limit_kb)

    def get_judge_payload(self, problem_id) -> ProblemCanonicalContract:
        p = self._problem(problem_id)
        try:
            difficulty = Difficulty(p.difficulty)
        except ValueError:
            difficulty = Difficulty.UNKNOWN
        try:
            status = IngestionStatus(p.ingestion_status)
        except ValueError:
            status = IngestionStatus.NEEDS_MANUAL_REVIEW
        raw_hash = hashlib.sha256(p.raw_payload_backup.encode("utf-8")).hexdigest()
        audit = AuditMetadataContract(has_statement=p.has_statement,
            has_sample_tests=p.has_sample_tests, has_hidden_tests=p.has_hidden_tests,
            has_starter_code=p.has_starter_code, has_solution=p.has_solution,
            status=status, missing_fields=p.missing_fields or [], raw_source_hash=raw_hash)
        templates = {t.language: CodeTemplateContract(language=t.language,
            starter_code=t.starter_code, driver_code=t.driver_code) for t in p.code_templates}
        cases = [TestCaseContract(id=t.id, input_data=t.input_data,
            expected_output=t.expected_output, is_sample=t.is_sample,
            explanation=t.explanation, order_index=t.order_index) for t in p.test_cases]
        solutions = {s.language: SolutionContract(language=s.language,
            solution_code=s.solution_code, approach_explanation_md=s.approach_explanation_md,
            time_complexity=s.time_complexity, space_complexity=s.space_complexity) for s in p.solutions}
        return ProblemCanonicalContract(id=p.id, external_id=p.external_id, slug=p.slug,
            title=p.title, difficulty=difficulty, statement_md=p.statement_md,
            constraints_md=p.constraints_md, tags=p.tags or [], templates=templates,
            test_cases=cases, solutions=solutions, time_limit_ms=p.time_limit_ms,
            memory_limit_kb=p.memory_limit_kb, audit=audit)

    def get_enrichment_queue(self, missing_field_type) -> List[int]:
        field = str(missing_field_type).strip().lower()
        mapping = {
            "tests": Problem.has_sample_tests,
            "test_cases": Problem.has_sample_tests,
            "templates": Problem.has_starter_code,
            "starter_code": Problem.has_starter_code,
            "solutions": Problem.has_solution,
            "difficulty": Problem.difficulty,
            "statement": Problem.has_statement,
        }
        if field not in mapping:
            raise ValueError(f"Unknown enrichment field: {missing_field_type}")
        column = mapping[field]
        stmt = select(Problem.id).order_by(Problem.id)
        if field == "difficulty":
            stmt = stmt.where(Problem.difficulty == Difficulty.UNKNOWN.value)
        else:
            stmt = stmt.where(column.is_(False))
        return list(self.session.scalars(stmt).all())
