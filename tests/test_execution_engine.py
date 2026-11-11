"""Ground-truth executor, verdict, plugin, and response-safety checks."""
import json
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import create_app
from core.contracts import ExecutionRequestDTO, Verdict
from core.database import make_engine, make_session_factory
from core.models import Problem, Solution, SubmissionModel
from core.ports.problem_repository import SqlAlchemyProblemRepository

DB_URL = "sqlite:///oj_platform.db"


def _execute_endpoint(api, request):
    from core.contracts import ExecutionRequestDTO
    route = next(route for route in api.routes
                 if getattr(route, "path", None) == "/api/execute" and "POST" in route.methods)
    return route.endpoint(ExecutionRequestDTO.model_validate(request))


def test_self_hosting_ground_truth_15_stored_solutions():
    engine = make_engine(DB_URL)
    sessions = make_session_factory(engine)
    with sessions() as session:
        stmt = (select(Problem).join(Problem.solutions).join(Problem.test_cases)
            .where(Problem.ingestion_status == "COMPLETE", Problem.has_sample_tests.is_(True),
                   Problem.has_solution.is_(True), Problem.solutions.any(Solution.language == "python"))
            .group_by(Problem.id).order_by(Problem.id).limit(15)
            .options(selectinload(Problem.solutions), selectinload(Problem.test_cases)))
        candidates = session.scalars(stmt).unique().all()
        selected = [(p.id, next(s.solution_code for s in p.solutions if s.language == "python" and s.solution_code))
                    for p in candidates]
    engine.dispose()
    assert len(selected) == 15
    passed = 0
    failures = []
    api = create_app(DB_URL)
    for problem_id, source in selected:
        structures = [name for name in ("ListNode", "TreeNode") if name in source]
        if structures:
            print(f"Problem {problem_id}: exercising {', '.join(structures)} input/output helpers")
        request = {"problem_id": problem_id, "language": "python", "source_code": source, "mode": "submit"}
        response = _execute_endpoint(api, request)
        assert response.problem_id == problem_id
        if response.overall_verdict == Verdict.ACCEPTED:
            passed += 1
        else:
            failures.append({"problem_id": problem_id, "verdict": response.overall_verdict.value,
                "passed_count": response.passed_count, "total_count": response.total_count,
                "first_failures": [x.model_dump(mode="json") for x in response.results if not x.passed][:3]})
    api.state.engine.dispose()
    print(f"Self-hosted solution results: {passed}/15 accepted")
    if failures:
        print("Self-hosted non-accepted diagnostics:\n" + json.dumps(failures, indent=2, ensure_ascii=False))
    assert passed == 15, json.dumps({"accepted": passed, "diagnostics": failures}, indent=2)


def test_verdict_coverage_and_plugin_payload():
    cases = [
        ("wrong_answer", "class Solution:\n    def twoSum(self, nums, target):\n        return []\n", "WA"),
        ("timeout", "class Solution:\n    def twoSum(self, nums, target):\n        while True: pass\n", "TLE"),
        ("runtime", "class Solution:\n    def twoSum(self, nums, target):\n        return 1 / 0\n", "RE"),
        ("syntax", "def broken(:\n", "CE"),
    ]
    api = create_app(DB_URL)
    for _, source, expected in cases:
        request = {"problem_id": 1, "language": "python", "source_code": source, "mode": "run"}
        response = _execute_endpoint(api, request)
        assert response.overall_verdict.value == expected, response.model_dump_json()
        assert "ast_metrics" in response.plugin_payloads
    api.state.engine.dispose()


def test_hidden_case_output_is_masked_by_executor():
    from core.adapters.local_python_executor import LocalPythonSubprocessExecutor
    from core.contracts import (AuditMetadataContract, CodeTemplateContract, Difficulty,
        ExecutionRequestDTO, IngestionStatus, ProblemCanonicalContract, SolutionContract,
        TestCaseContract)

    problem = ProblemCanonicalContract(id=999, slug="hidden", title="Hidden", difficulty=Difficulty.EASY,
        templates={"python": CodeTemplateContract(starter_code="class Solution:\n    def solve(self):\n        pass")},
        test_cases=[TestCaseContract(input_data="1", expected_output="1", is_sample=True),
                    TestCaseContract(input_data="hidden-input-secret", expected_output="hidden-output-secret", is_sample=False)],
        solutions={"python": SolutionContract(solution_code="secret-solution")},
        audit=AuditMetadataContract(status=IngestionStatus.COMPLETE), time_limit_ms=500)
    request = ExecutionRequestDTO(problem_id=999, language="python",
        source_code="class Solution:\n    def solve(self, x):\n        return x", mode="submit")
    executor = LocalPythonSubprocessExecutor()
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(executor.execute, problem, request).result(timeout=10)
    encoded = json.dumps(response.model_dump())
    assert "hidden-input-secret" not in encoded
    assert "hidden-output-secret" not in encoded
    assert "secret-solution" not in encoded
    assert len(response.results) == 2, response.model_dump_json()
    hidden = response.results[1]
    assert hidden.input_data is None and hidden.expected_output is None and hidden.actual_output is None


def test_executor_timeout_watchdog_terminates_loop():
    from core.adapters.local_python_executor import LocalPythonSubprocessExecutor
    from core.contracts import (AuditMetadataContract, CodeTemplateContract, Difficulty,
        ExecutionRequestDTO, IngestionStatus, ProblemCanonicalContract, TestCaseContract)
    problem = ProblemCanonicalContract(id=998, slug="loop", title="Loop", difficulty=Difficulty.EASY,
        templates={"python": CodeTemplateContract(starter_code="class Solution:\n    def solve(self):\n        pass")},
        test_cases=[TestCaseContract(input_data="1", expected_output="1", is_sample=True)],
        audit=AuditMetadataContract(status=IngestionStatus.COMPLETE), time_limit_ms=100)
    request = ExecutionRequestDTO(problem_id=998, language="python",
        source_code="class Solution:\n    def solve(self, x):\n        while True: pass", mode="submit")
    result = LocalPythonSubprocessExecutor().execute(problem, request)
    assert result.overall_verdict == Verdict.TIME_LIMIT_EXCEEDED, result.model_dump_json()


def test_fastapi_catalog_routes_and_health():
    api = create_app(DB_URL)
    paths = {(method, route.path) for route in api.routes
             for method in getattr(route, "methods", set())}
    assert ("GET", "/api/health") in paths
    assert ("GET", "/api/problems") in paths
    assert ("GET", "/api/problems/{slug_or_id}") in paths
    assert ("GET", "/api/problems/{problem_id}/submissions") in paths
    assert ("GET", "/api/stats") in paths
    assert ("POST", "/api/execute") in paths
    health_route = next(r for r in api.routes if getattr(r, "path", None) == "/api/health")
    health = health_route.endpoint()
    assert health["database"] == "connected"
    assert health["total_problems"] == 4100 and health["ready_to_solve"] == 2869
    workspace_route = next(r for r in api.routes if getattr(r, "path", None) == "/api/problems/{slug_or_id}")
    workspace = workspace_route.endpoint("two-sum")
    assert workspace.slug == "two-sum"
    assert not hasattr(workspace, "solutions") and not hasattr(workspace, "hidden_test_cases")
    listing_route = next(r for r in api.routes if getattr(r, "path", None) == "/api/problems")
    listings = listing_route.endpoint(None, "Array", "Two Sum", True, 10, 0)
    assert listings and any(item.slug == "two-sum" for item in listings)
    api.state.engine.dispose()


def test_myatoi_stored_solution_accepts_legacy_malformed_inputs():
    engine = make_engine(DB_URL)
    sessions = make_session_factory(engine)
    api = create_app(DB_URL)
    with sessions() as session:
        solution = session.scalar(select(Solution).where(
            Solution.problem_id == 8, Solution.language == "python"))
        source = solution.solution_code
    response = _execute_endpoint(api, {"problem_id": 8, "language": "python",
        "source_code": source, "mode": "submit"})
    assert response.overall_verdict == Verdict.ACCEPTED, response.model_dump_json()
    api.state.engine.dispose()
    engine.dispose()


def test_submit_persists_history_progress_and_stats():
    api = create_app(DB_URL)
    with api.state.sessions() as session:
        before = SqlAlchemyProblemRepository(session).get_user_stats()
        solution = session.scalar(select(Solution).where(
            Solution.problem_id == 1, Solution.language == "python"))
        source = solution.solution_code
    response = _execute_endpoint(api, {"problem_id": 1, "language": "python",
        "source_code": source, "mode": "submit"})
    assert response.overall_verdict == Verdict.ACCEPTED, response.model_dump_json()
    with api.state.sessions() as session:
        stored = session.get(SubmissionModel, response.submission_id)
        assert stored is not None
        assert stored.ast_metrics_json
        repo = SqlAlchemyProblemRepository(session)
        history = repo.get_problem_submissions(1, limit=20)
        assert any(item.id == response.submission_id and item.source_code == source for item in history)
        statuses = repo._submission_statuses([1])
        after = repo.get_user_stats()
        assert statuses[1] == "SOLVED"
        assert after["total_submissions"] == before["total_submissions"] + 1
        assert after["acceptance_rate"] == round(
            (before["total_submissions"] * before["acceptance_rate"] / 100 + 1)
            / after["total_submissions"] * 100, 2)
    stats_route = next(r for r in api.routes if getattr(r, "path", None) == "/api/stats")
    stats = stats_route.endpoint()
    assert stats["total_submissions"] == after["total_submissions"]
    assert all(key in stats["solved_by_difficulty"] for key in ("Easy", "Medium", "Hard"))
    listing_route = next(r for r in api.routes if getattr(r, "path", None) == "/api/problems")
    two_sum = next(item for item in listing_route.endpoint(None, "Array", "Two Sum", True, 10, 0)
                   if item.id == 1)
    assert two_sum.user_status == "SOLVED"
    history_route = next(r for r in api.routes if getattr(r, "path", None) == "/api/problems/{problem_id}/submissions")
    assert any(item.id == response.submission_id for item in history_route.endpoint(1, 20))
    api.state.engine.dispose()
