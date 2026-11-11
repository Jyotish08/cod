#!/usr/bin/env python3
"""Stream a JSONL problem archive into SQLite and emit an enrichment audit."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from models import SCHEMA

LOG = logging.getLogger("ingest")


def first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "untitled-problem"


def normalize_test_cases(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    cases = []
    for item in value:
        if isinstance(item, dict):
            inp = first(item, ("input", "stdin", "args", "case"))
            out = first(item, ("expected_output", "expected", "output", "stdout", "answer"))
            if inp is None and out is None:
                # Preserve malformed-but-present examples rather than dropping them.
                cases.append({"input": json.dumps(item, ensure_ascii=False), "expected_output": ""})
                continue
            cases.append({"input": text(inp), "expected_output": text(out),
                          "explanation": text(first(item, ("explanation", "explain"))) or None})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            cases.append({"input": text(item[0]), "expected_output": text(item[1])})
        elif isinstance(item, str):
            # A plain example block is retained as input with unavailable output.
            cases.append({"input": item, "expected_output": ""})
        else:
            cases.append({"input": text(item), "expected_output": ""})
    return cases


def normalize(record: dict[str, Any], line_number: int) -> dict[str, Any]:
    nested = record.get("leetcode_dataset")
    nested = nested if isinstance(nested, dict) else {}
    title = text(first(record, ("title", "problem_name", "name", "header")))
    if not title:
        title = text(first(nested, ("title", "name")))
    title = title or f"Untitled problem line {line_number}"
    description = first(record, ("description", "statement", "problem_statement", "desc", "content"))
    if description is None:
        description = first(nested, ("problem_description", "description", "statement"))
    description = text(description) or "Description pending."

    cases_value = first(record, ("test_cases", "testcases", "tests", "examples", "samples"))
    cases = normalize_test_cases(cases_value)
    if not cases:
        # This export's public examples use input_output; judge tests are in `test`.
        cases = normalize_test_cases(record.get("input_output") or nested.get("input_output"))

    templates_value = first(record, ("starter_code", "template", "code_snippet", "skeleton"))
    if templates_value is None:
        templates_value = nested.get("starter_code")
    templates: list[tuple[str, str]] = []
    if isinstance(templates_value, dict):
        templates = [(str(lang or "python").lower(), text(code)) for lang, code in templates_value.items() if text(code)]
    elif text(templates_value):
        language = text(first(record, ("language", "starter_code_language"))) or "python"
        templates = [(language.lower(), text(templates_value))]

    solution_value = first(record, ("solution", "reference_solution", "official_solution", "code"))
    if solution_value is None:
        solution_value = first(record, ("canonical_solution",))
    if solution_value is None:
        solution_value = nested.get("canonical_solution")
    solutions: list[tuple[str, str]] = []
    if isinstance(solution_value, dict):
        solutions = [(str(lang or "python").lower(), text(code)) for lang, code in solution_value.items() if text(code)]
    elif text(solution_value):
        lang = text(first(record, ("solution_language", "canonical_solution_language"))) or text(record.get("canonical_solution_language")) or "python"
        # Dataset uses short language codes; normalize common aliases.
        lang = {"py": "python", "js": "javascript", "cpp": "cpp"}.get(lang.lower(), lang.lower())
        solutions = [(lang, text(solution_value))]

    raw_difficulty = first(record, ("difficulty",))
    if raw_difficulty is None:
        raw_difficulty = nested.get("difficulty")
    difficulty = text(raw_difficulty).upper()
    if difficulty not in {"EASY", "MEDIUM", "HARD"}:
        difficulty = "UNKNOWN"

    tags = first(record, ("category_tags", "tags", "topics"))
    if tags is None:
        tags = nested.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        tags = []

    source_id = first(record, ("problem_number", "id", "question_id"))
    if source_id is None:
        source_id = nested.get("question_id") or nested.get("task_id") or line_number
    source_key = str(source_id)
    raw_slug = first(record, ("slug", "leetcode_slug")) or nested.get("task_id")
    base_slug = slugify(text(raw_slug) or title)
    status = "COMPLETE"
    if not cases:
        status = "PARTIAL_NEEDS_TESTS"
    elif not templates:
        status = "PARTIAL_NEEDS_CODE"
    return {"source_key": source_key, "title": title, "description": description,
            "difficulty": difficulty, "tags": tags, "cases": cases, "templates": templates,
            "solutions": solutions, "has_testcases": bool(cases), "has_starter_code": bool(templates),
            "has_solution": bool(solutions), "status": status, "base_slug": base_slug,
            "source_json": json.dumps(record, ensure_ascii=False, separators=(",", ":"))}


def choose_slug(conn: sqlite3.Connection, base: str, source_key: str) -> str:
    existing = conn.execute("SELECT slug FROM problems WHERE source_key=?", (source_key,)).fetchone()
    if existing:
        return existing[0]
    candidate, suffix = base, 1
    while conn.execute("SELECT 1 FROM problems WHERE slug=?", (candidate,)).fetchone():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def ingest(source: Path, db_path: str, batch_size: int = 100) -> dict[str, Any]:
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    audit: dict[str, Any] = {
        "total_lines_processed": 0, "successful_records_inserted": 0, "failed_records": [],
        "enrichment_backlog": {"missing_testcases_ids": [], "missing_solutions_ids": [],
            "missing_starter_code_ids": [], "unknown_difficulty_ids": []}}
    pending: list[tuple[int, str, dict[str, Any]]] = []

    def flush() -> None:
        if not pending:
            return
        try:
            with db:
                for line_no, raw_id, row in pending:
                    now = datetime.now(timezone.utc).isoformat()
                    slug = choose_slug(db, row["base_slug"], row["source_key"])
                    db.execute("""INSERT INTO problems
                        (source_key,slug,title,difficulty,description_md,category_tags,source_json,
                         has_testcases,has_starter_code,has_solution,ingestion_status,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(source_key) DO UPDATE SET slug=excluded.slug,title=excluded.title,
                         difficulty=excluded.difficulty,description_md=excluded.description_md,
                         category_tags=excluded.category_tags,source_json=excluded.source_json,
                         has_testcases=excluded.has_testcases,has_starter_code=excluded.has_starter_code,
                         has_solution=excluded.has_solution,ingestion_status=excluded.ingestion_status,
                         updated_at=excluded.updated_at""",
                        (row["source_key"], slug, row["title"], row["difficulty"], row["description"],
                         json.dumps(row["tags"], ensure_ascii=False), row["source_json"],
                         int(row["has_testcases"]), int(row["has_starter_code"]), int(row["has_solution"]),
                         row["status"], now, now))
                    problem_id = db.execute("SELECT id FROM problems WHERE source_key=?", (row["source_key"],)).fetchone()[0]
                    for table in ("test_cases", "code_templates", "solutions"):
                        db.execute(f"DELETE FROM {table} WHERE problem_id=?", (problem_id,))
                    for case in row["cases"]:
                        db.execute("INSERT INTO test_cases(problem_id,input,expected_output,is_sample,explanation) VALUES (?,?,?,?,?)",
                                   (problem_id, case["input"], case["expected_output"], 1, case.get("explanation")))
                    for lang, code in row["templates"]:
                        db.execute("INSERT INTO code_templates(problem_id,language,starter_code) VALUES (?,?,?)", (problem_id,lang,code))
                    for lang, code in row["solutions"]:
                        db.execute("INSERT INTO solutions(problem_id,language,solution_code) VALUES (?,?,?)", (problem_id,lang,code))
                    audit["successful_records_inserted"] += 1
                    label = f"{row['source_key']}:{slug}"
                    backlog = audit["enrichment_backlog"]
                    if not row["cases"]: backlog["missing_testcases_ids"].append(label)
                    if not row["solutions"]: backlog["missing_solutions_ids"].append(label)
                    if not row["templates"]: backlog["missing_starter_code_ids"].append(label)
                    if row["difficulty"] == "UNKNOWN": backlog["unknown_difficulty_ids"].append(label)
        except Exception as exc:
            # Batch rollback is atomic; isolate each record to preserve every valid neighbor.
            LOG.exception("Batch failed; retrying %d records individually", len(pending))
            for line_no, raw_id, row in pending:
                try:
                    single = [ (line_no, raw_id, row) ]
                    # Execute the same transaction path without recursively retrying.
                    with db:
                        now = datetime.now(timezone.utc).isoformat()
                        slug = choose_slug(db, row["base_slug"], row["source_key"])
                        db.execute("""INSERT INTO problems(source_key,slug,title,difficulty,description_md,category_tags,source_json,has_testcases,has_starter_code,has_solution,ingestion_status,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET slug=excluded.slug,title=excluded.title,difficulty=excluded.difficulty,description_md=excluded.description_md,category_tags=excluded.category_tags,source_json=excluded.source_json,has_testcases=excluded.has_testcases,has_starter_code=excluded.has_starter_code,has_solution=excluded.has_solution,ingestion_status=excluded.ingestion_status,updated_at=excluded.updated_at""",
                            (row["source_key"],slug,row["title"],row["difficulty"],row["description"],json.dumps(row["tags"],ensure_ascii=False),row["source_json"],int(row["has_testcases"]),int(row["has_starter_code"]),int(row["has_solution"]),row["status"],now,now))
                        pid=db.execute("SELECT id FROM problems WHERE source_key=?",(row["source_key"],)).fetchone()[0]
                        for table in ("test_cases","code_templates","solutions"): db.execute(f"DELETE FROM {table} WHERE problem_id=?",(pid,))
                        for c in row["cases"]: db.execute("INSERT INTO test_cases(problem_id,input,expected_output,is_sample,explanation) VALUES(?,?,?,?,?)",(pid,c["input"],c["expected_output"],1,c.get("explanation")))
                        for lang,code in row["templates"]: db.execute("INSERT INTO code_templates(problem_id,language,starter_code) VALUES(?,?,?)",(pid,lang,code))
                        for lang,code in row["solutions"]: db.execute("INSERT INTO solutions(problem_id,language,solution_code) VALUES(?,?,?)",(pid,lang,code))
                    audit["successful_records_inserted"] += 1
                    label=f"{row['source_key']}:{slug}"; b=audit["enrichment_backlog"]
                    if not row["cases"]: b["missing_testcases_ids"].append(label)
                    if not row["solutions"]: b["missing_solutions_ids"].append(label)
                    if not row["templates"]: b["missing_starter_code_ids"].append(label)
                    if row["difficulty"]=="UNKNOWN": b["unknown_difficulty_ids"].append(label)
                except Exception as record_exc:
                    audit["failed_records"].append({"line_number":line_no,"raw_identifier":raw_id,"error_reason":str(record_exc)})
                    LOG.error("Line %d (%s) failed: %s", line_no, raw_id, record_exc)
        pending.clear()

    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, 1):
                audit["total_lines_processed"] += 1
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("JSONL record must be an object")
                    row = normalize(value, line_no)
                    raw_id = row["source_key"]
                    pending.append((line_no, raw_id, row))
                except Exception as exc:
                    raw_id = "unknown"
                    try:
                        parsed = json.loads(line)
                        if isinstance(parsed, dict): raw_id = str(first(parsed, ("problem_number","id","question_id")) or "unknown")
                    except Exception: pass
                    audit["failed_records"].append({"line_number":line_no,"raw_identifier":raw_id,"error_reason":str(exc)})
                    LOG.error("Line %d (%s) failed to parse: %s", line_no, raw_id, exc)
                if len(pending) >= batch_size:
                    flush()
                    if audit["total_lines_processed"] % 1000 < batch_size:
                        LOG.info("Processed %d lines", audit["total_lines_processed"])
        flush()
    finally:
        db.close()
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="leetcode_1-4100_merged.jsonl", help="Input JSONL path")
    parser.add_argument("--db", default="sqlite:///problems.db", help="SQLite URL (sqlite:///path.db)")
    parser.add_argument("--audit", default="audit_report.json", help="Audit JSON output path")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if not args.db.startswith("sqlite:///"):
        parser.error("This standalone importer supports sqlite:///path only")
    db_path = args.db[len("sqlite:///"):]
    source = Path(args.file)
    if not source.is_file():
        parser.error(f"Input file does not exist: {source}")
    audit = ingest(source, db_path, args.batch_size)
    Path(args.audit).write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    b = audit["enrichment_backlog"]
    print("Ingestion complete")
    print(f"Lines processed: {audit['total_lines_processed']}")
    print(f"Successful records inserted/upserted: {audit['successful_records_inserted']}")
    print(f"Failed records: {len(audit['failed_records'])}")
    print(f"Missing test cases: {len(b['missing_testcases_ids'])}")
    print(f"Missing solutions: {len(b['missing_solutions_ids'])}")
    print(f"Missing starter code: {len(b['missing_starter_code_ids'])}")
    print(f"Unknown difficulty: {len(b['unknown_difficulty_ids'])}")
    print(f"Audit report: {Path(args.audit).resolve()}")
    return 1 if audit["failed_records"] else 0


if __name__ == "__main__":
    sys.exit(main())
