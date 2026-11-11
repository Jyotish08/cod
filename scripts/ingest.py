#!/usr/bin/env python3
"""Idempotently ingest JSONL problems with zero-loss raw payload retention."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.contracts import Difficulty, IngestionStatus
from core.database import Base, make_engine, make_session_factory
from core.models import CodeTemplate, Problem, Solution, TestCase

LOG = logging.getLogger("oj_ingest")
PLACEHOLDER = "class Solution:\n    def solve(self, *args):\n        pass"


def first(mapping: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "untitled-problem"


class ProblemNormalizer:
    """Map discovered source variants to a canonical ORM-ready row."""
    def normalize(self, raw: dict[str, Any], raw_line: str, line_num: int) -> dict[str, Any]:
        nested = raw.get("leetcode_dataset")
        nested = nested if isinstance(nested, dict) else {}
        title = as_text(first(raw, ("title", "problem_name", "name", "header")))
        title = title or f"Untitled Problem #{line_num}"
        statement = as_text(first(raw, ("description", "statement", "problem_statement", "desc", "content")))
        if not statement:
            statement = as_text(first(nested, ("problem_description", "description", "statement")))
        if not statement:
            statement = "Problem statement pending enrichment."
        tags = first(raw, ("category_tags", "tags", "topics"))
        if tags is None:
            tags = nested.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list):
            tags = []
        tags = [as_text(tag) for tag in tags if as_text(tag)]

        diff = first(raw, ("difficulty",))
        if diff is None:
            diff = nested.get("difficulty")
        diff = as_text(diff).upper()
        difficulty = diff if diff in {d.value for d in Difficulty if d != Difficulty.UNKNOWN} else "UNKNOWN"

        raw_id = first(raw, ("problem_number", "id", "question_id"))
        if raw_id is None:
            raw_id = nested.get("question_id") or nested.get("task_id") or line_num
        external_id = str(raw_id)
        source_slug = as_text(first(raw, ("slug", "leetcode_slug"))) or as_text(nested.get("task_id"))
        base_slug = slugify(source_slug or title)

        test_values = first(raw, ("test_cases", "testcases", "tests", "examples", "samples"))
        if test_values is None:
            test_values = raw.get("input_output", nested.get("input_output"))
        if isinstance(test_values, dict):
            test_values = [test_values]
        cases = []
        if isinstance(test_values, list):
            for idx, item in enumerate(test_values):
                if isinstance(item, dict):
                    inp = first(item, ("input_data", "input", "stdin", "args", "case"))
                    out = first(item, ("expected_output", "expected", "output", "stdout", "answer"))
                    if inp is None or out is None:
                        continue
                    cases.append({"input_data": as_text(inp), "expected_output": as_text(out),
                                  "is_sample": True, "explanation": as_text(item.get("explanation")) or None,
                                  "order_index": idx})
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    cases.append({"input_data": as_text(item[0]), "expected_output": as_text(item[1]),
                                  "is_sample": True, "order_index": idx})

        template_value = first(raw, ("starter_code", "template", "code_snippet", "skeleton"))
        if template_value is None:
            template_value = nested.get("starter_code")
        templates = {}
        if isinstance(template_value, dict):
            templates = {str(lang or "python").lower(): as_text(code)
                         for lang, code in template_value.items() if as_text(code)}
        elif as_text(template_value):
            lang = as_text(first(raw, ("language", "starter_code_language"))) or "python"
            templates[lang.lower()] = as_text(template_value)
        has_starter = bool(templates)
        if not templates:
            templates["python"] = PLACEHOLDER

        solution_value = first(raw, ("solution", "reference_solution", "official_solution", "code", "canonical_solution"))
        if solution_value is None:
            solution_value = nested.get("canonical_solution")
        solutions = {}
        if isinstance(solution_value, dict):
            solutions = {str(lang or "python").lower(): as_text(code)
                         for lang, code in solution_value.items() if as_text(code)}
        elif as_text(solution_value):
            lang = as_text(raw.get("canonical_solution_language") or raw.get("solution_language") or "python").lower()
            lang = {"py": "python", "js": "javascript"}.get(lang, lang)
            solutions[lang] = as_text(solution_value)

        missing = []
        if statement == "Problem statement pending enrichment.": missing.append("statement")
        if not cases: missing.append("test_cases")
        if not has_starter: missing.append("starter_code")
        if not solutions: missing.append("solution")
        if difficulty == "UNKNOWN": missing.append("difficulty")
        if not cases:
            status = IngestionStatus.PARTIAL_MISSING_TESTS.value
        elif not has_starter:
            status = IngestionStatus.PARTIAL_MISSING_TEMPLATE.value
        elif not solutions:
            status = IngestionStatus.PARTIAL_MISSING_SOLUTION.value
        elif difficulty == "UNKNOWN":
            status = IngestionStatus.NEEDS_MANUAL_REVIEW.value
        else:
            status = IngestionStatus.COMPLETE.value
        return {
            "external_id": external_id, "title": title, "base_slug": base_slug,
            "difficulty": difficulty, "statement_md": statement, "constraints_md": None,
            "tags": tags, "templates": templates, "has_starter_code": has_starter,
            "test_cases": cases, "solutions": solutions, "missing_fields": missing,
            "has_statement": statement != "Problem statement pending enrichment.",
            "has_sample_tests": any(c["is_sample"] for c in cases), "has_hidden_tests": False,
            "has_solution": bool(solutions), "ingestion_status": status,
            "raw_payload_backup": raw_line.rstrip("\r\n"),
            "raw_source_hash": hashlib.sha256(raw_line.rstrip("\r\n").encode("utf-8")).hexdigest(),
            "time_limit_ms": 2000, "memory_limit_kb": 262144,
        }


def unique_slug(session: Session, base: str, external_id: str) -> str:
    existing = session.scalar(select(Problem).where(Problem.external_id == external_id))
    if existing:
        return existing.slug
    if session.scalar(select(Problem.id).where(Problem.slug == base)) is None:
        return base
    suffix_base = f"{base}-{slugify(external_id)}"
    candidate, suffix = suffix_base, 1
    while session.scalar(select(Problem.id).where(Problem.slug == candidate)) is not None:
        candidate = f"{suffix_base}-{suffix}"
        suffix += 1
    return candidate


def put_record(session: Session, row: dict[str, Any]) -> None:
    problem = session.scalar(select(Problem).where(Problem.external_id == row["external_id"]))
    slug = problem.slug if problem else unique_slug(session, row["base_slug"], row["external_id"])
    if problem is None:
        problem = Problem(external_id=row["external_id"], slug=slug, title=row["title"])
        session.add(problem)
    else:
        problem.title = row["title"]
        problem.slug = slug
    for name in ("difficulty", "statement_md", "constraints_md", "tags", "time_limit_ms",
                 "memory_limit_kb", "has_statement", "has_sample_tests", "has_hidden_tests",
                 "has_starter_code", "has_solution", "ingestion_status", "missing_fields",
                 "raw_payload_backup"):
        setattr(problem, name, row[name])
    problem.test_cases.clear(); problem.code_templates.clear(); problem.solutions.clear()
    # Flush relationship deletes before inserting replacements so the unique
    # (problem_id, language) template constraint also works on repeat imports.
    session.flush()
    problem.test_cases.extend(TestCase(**case) for case in row["test_cases"])
    problem.code_templates.extend(CodeTemplate(language=lang, starter_code=code)
                                  for lang, code in row["templates"].items())
    problem.solutions.extend(Solution(language=lang, solution_code=code)
                             for lang, code in row["solutions"].items())


def ingest(input_path: Path, db_url: str, batch_size: int = 250) -> dict[str, Any]:
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)
    normalizer = ProblemNormalizer()
    report = {"total_lines_read": 0, "total_db_rows_committed": 0, "failed_records": [],
              "complete_count": 0, "partial": {"missing_tests_ids": [], "missing_templates_ids": [],
              "missing_solutions_ids": [], "missing_difficulty_ids": []}}
    batch = []

    def flush():
        if not batch:
            return
        try:
            with SessionFactory.begin() as session:
                for line_num, raw_id, row in batch:
                    put_record(session, row)
            report["total_db_rows_committed"] += len(batch)
            for _, _, row in batch:
                eid = row["external_id"]
                if row["ingestion_status"] == IngestionStatus.COMPLETE.value:
                    report["complete_count"] += 1
                if "test_cases" in row["missing_fields"]: report["partial"]["missing_tests_ids"].append(eid)
                if "starter_code" in row["missing_fields"]: report["partial"]["missing_templates_ids"].append(eid)
                if "solution" in row["missing_fields"]: report["partial"]["missing_solutions_ids"].append(eid)
                if "difficulty" in row["missing_fields"]: report["partial"]["missing_difficulty_ids"].append(eid)
        except Exception as exc:
            LOG.exception("Transaction failed for batch of %d; isolating rows", len(batch))
            for line_num, raw_id, row in batch:
                try:
                    with SessionFactory.begin() as session:
                        put_record(session, row)
                    report["total_db_rows_committed"] += 1
                    eid = row["external_id"]
                    if row["ingestion_status"] == IngestionStatus.COMPLETE.value: report["complete_count"] += 1
                    if "test_cases" in row["missing_fields"]: report["partial"]["missing_tests_ids"].append(eid)
                    if "starter_code" in row["missing_fields"]: report["partial"]["missing_templates_ids"].append(eid)
                    if "solution" in row["missing_fields"]: report["partial"]["missing_solutions_ids"].append(eid)
                    if "difficulty" in row["missing_fields"]: report["partial"]["missing_difficulty_ids"].append(eid)
                except Exception as record_exc:
                    report["failed_records"].append({"line_number": line_num,
                        "raw_identifier": raw_id, "error_reason": str(record_exc)})
                    LOG.error("Record line %s (%s) failed: %s", line_num, raw_id, record_exc)
        batch.clear()

    try:
        with input_path.open("r", encoding="utf-8-sig") as stream:
            for line_num, line in enumerate(stream, 1):
                report["total_lines_read"] += 1
                raw_id = "unknown"
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise ValueError("JSONL record is not an object")
                    raw_id = str(raw.get("problem_number") or raw.get("id") or raw.get("question_id") or line_num)
                    row = normalizer.normalize(raw, line, line_num)
                    batch.append((line_num, raw_id, row))
                except Exception as exc:
                    report["failed_records"].append({"line_number": line_num,
                        "raw_identifier": raw_id, "error_reason": str(exc)})
                    LOG.error("Record line %s (%s) failed to normalize: %s", line_num, raw_id, exc)
                if len(batch) >= batch_size:
                    flush()
                    if report["total_lines_read"] % 1000 < batch_size:
                        LOG.info("Read %d lines", report["total_lines_read"])
        flush()
    finally:
        engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="leetcode_1-4100_merged.jsonl")
    parser.add_argument("--db", default="sqlite:///oj_platform.db")
    parser.add_argument("--audit", default="audit_report.json")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1: parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    path = Path(args.input)
    if not path.is_file(): parser.error(f"Input file does not exist: {path}")
    report = ingest(path, args.db, args.batch_size)
    Path(args.audit).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Lines read: {report['total_lines_read']}")
    print(f"DB rows committed: {report['total_db_rows_committed']}")
    print(f"Complete problems: {report['complete_count']}")
    print(f"Failed records: {len(report['failed_records'])}")
    for name, ids in report["partial"].items(): print(f"{name}: {len(ids)}")
    print(f"Audit report: {Path(args.audit).resolve()}")
    return 1 if report["failed_records"] else 0


if __name__ == "__main__":
    sys.exit(main())
