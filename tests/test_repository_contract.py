"""Public workspace DTO must validate and must not expose judge-only data."""
import json

from sqlalchemy import select

from core.contracts import ProblemWorkspaceDTO
from core.database import Base, make_engine, make_session_factory
from core.models import CodeTemplate, Problem, Solution, TestCase as DBTestCase
from core.ports.problem_repository import SqlAlchemyProblemRepository


def test_workspace_contract_does_not_leak_hidden_tests_or_solutions():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    try:
        with sessions.begin() as session:
            for n in range(1, 4):
                problem = Problem(external_id=str(n), slug=f"problem-{n}", title=f"Problem {n}",
                    difficulty="EASY", statement_md="Statement", tags=["Arrays"],
                    has_statement=True, has_sample_tests=True, has_hidden_tests=True,
                    has_starter_code=True, has_solution=True, ingestion_status="COMPLETE",
                    missing_fields=[], raw_payload_backup="{}")
                problem.test_cases.extend([
                    DBTestCase(input_data=f"sample-{n}", expected_output="ok", is_sample=True, order_index=0),
                    DBTestCase(input_data=f"hidden-secret-{n}", expected_output="secret", is_sample=False, order_index=1),
                ])
                problem.code_templates.append(CodeTemplate(language="python", starter_code="class Solution: pass"))
                problem.solutions.append(Solution(language="python", solution_code=f"secret-solution-{n}"))
                session.add(problem)
        with sessions() as session:
            repo = SqlAlchemyProblemRepository(session)
            ids = list(session.scalars(select(Problem.id).order_by(Problem.id)).all())
            assert len(ids) == 3
            for problem_id in ids:
                result = repo.get_workspace_problem(problem_id)
                validated = ProblemWorkspaceDTO.model_validate(result.model_dump(), strict=True)
                encoded = json.dumps(validated.model_dump(), ensure_ascii=False)
                assert len(validated.sample_test_cases) == 1
                assert validated.sample_test_cases[0].is_sample is True
                assert "hidden-secret" not in encoded
                assert "secret-solution" not in encoded
                assert "solutions" not in validated.model_fields_set
                assert "hidden_test_cases" not in validated.model_fields_set
    finally:
        engine.dispose()


