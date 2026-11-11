#!/usr/bin/env python3
"""Discover JSONL record fields and sample shapes without loading the file."""
import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="leetcode_1-4100_merged.jsonl")
    args = parser.parse_args()
    top_keys: Counter[str] = Counter()
    nested_keys: Counter[str] = Counter()
    samples = []
    count = 0
    wanted = {1, 100, 500, 1000, 2000, 3000, 4100}
    with Path(args.input).open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            record = json.loads(line)
            count += 1
            if not isinstance(record, dict):
                continue
            top_keys.update(record.keys())
            for key, value in record.items():
                if isinstance(value, dict):
                    nested_keys.update(f"{key}.{child}" for child in value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            nested_keys.update(f"{key}.{child}" for child in item)
            if line_no in wanted:
                nested = record.get("leetcode_dataset") or {}
                nested = nested if isinstance(nested, dict) else {}
                sample = {
                    "line": line_no,
                    "problem_number": record.get("problem_number"),
                    "title": record.get("title"),
                    "test_fields": {
                        key: (type(record[key]).__name__ if key in record else None)
                        for key in ("test_cases", "testcases", "tests", "examples", "samples", "input_output")
                    },
                    "nested_test_fields": {
                        key: (type(nested[key]).__name__ if key in nested else None)
                        for key in ("test_cases", "testcases", "tests", "examples", "samples", "input_output")
                    },
                    "input_output_first_item": (nested.get("input_output") or record.get("input_output") or [])[:1],
                    "solution_shape": type(record.get("canonical_solution") or record.get("solution") or "missing").__name__,
                    "starter_shape": type(nested.get("starter_code") or record.get("starter_code") or "missing").__name__,
                }
                samples.append(sample)
    print(f"line_count: {count}")
    print("top_level_keys:")
    for key in sorted(top_keys):
        print(f"  {key} ({top_keys[key]} records)")
    print("nested_keys:")
    for key in sorted(nested_keys):
        print(f"  {key}")
    print("sample_records:")
    print(json.dumps(samples, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
