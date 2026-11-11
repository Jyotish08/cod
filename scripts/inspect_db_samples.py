#!/usr/bin/env python3
"""Print representative stored starter, solution, and case formats."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import make_engine, make_session_factory
from core.models import Problem


def main() -> None:
    engine = make_engine("sqlite:///oj_platform.db")
    Session = make_session_factory(engine)
    with Session() as session:
        stmt = (select(Problem).options(selectinload(Problem.test_cases),
                    selectinload(Problem.code_templates), selectinload(Problem.solutions))
                .where(Problem.ingestion_status == "COMPLETE")
                .order_by(Problem.id).limit(5))
        rows = session.scalars(stmt).all()
        for problem in rows:
            print(f"\n=== {problem.id}: {problem.title} [{problem.slug}] ===")
            template = next((x for x in problem.code_templates if x.language == "python"), None)
            solution = next((x for x in problem.solutions if x.language == "python"), None)
            print("STARTER_CODE:\n" + ((template.starter_code if template else "<missing>")[:1200]))
            print("SOLUTION_CODE:\n" + ((solution.solution_code if solution else "<missing>")[:1800]))
            print("TEST_CASES:")
            for case in [x for x in problem.test_cases if x.is_sample][:3]:
                print({"input_data": case.input_data[:1000], "expected_output": case.expected_output[:500]})
    engine.dispose()


if __name__ == "__main__":
    main()
