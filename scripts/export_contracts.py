#!/usr/bin/env python3
"""Export Pydantic JSON Schemas and stable TypeScript DTO interfaces."""
import json
import sys
from pathlib import Path
from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.contracts import (AuditMetadataContract, CodeTemplateContract,
    Difficulty, ExecutionRequestDTO, ExecutionResponseDTO,
    IngestionStatus, ProblemCanonicalContract, ProblemSummaryDTO,
    ProblemWorkspaceDTO, SolutionContract, SubmissionHistoryDTO, TestCaseContract,
    TestCaseResultDTO, Verdict)

MODELS = [Difficulty, IngestionStatus, Verdict, TestCaseContract,
          CodeTemplateContract, SolutionContract, AuditMetadataContract,
          ProblemCanonicalContract, ProblemSummaryDTO, ProblemWorkspaceDTO,
          SubmissionHistoryDTO, ExecutionRequestDTO, TestCaseResultDTO, ExecutionResponseDTO]

TS_TYPES = '''// Generated from core/contracts.py. Do not edit by hand.
export type Difficulty = "EASY" | "MEDIUM" | "HARD" | "UNKNOWN";
export type IngestionStatus = "COMPLETE" | "PARTIAL_MISSING_TESTS" | "PARTIAL_MISSING_TEMPLATE" | "PARTIAL_MISSING_SOLUTION" | "NEEDS_MANUAL_REVIEW";
export type Verdict = "AC" | "WA" | "TLE" | "MLE" | "RE" | "CE" | "PENDING";

export interface TestCaseContract { id?: number | null; input_data: string; expected_output: string; is_sample?: boolean; explanation?: string | null; order_index?: number; }
export interface CodeTemplateContract { language?: string; starter_code: string; driver_code?: string | null; }
export interface SolutionContract { language?: string; solution_code: string; approach_explanation_md?: string | null; time_complexity?: string | null; space_complexity?: string | null; }
export interface AuditMetadataContract { has_statement?: boolean; has_sample_tests?: boolean; has_hidden_tests?: boolean; has_starter_code?: boolean; has_solution?: boolean; status?: IngestionStatus; missing_fields?: string[]; raw_source_hash?: string | null; }
export interface ProblemCanonicalContract { id: number; external_id?: string | null; slug: string; title: string; difficulty?: Difficulty; statement_md?: string; constraints_md?: string | null; tags?: string[]; templates?: Record<string, CodeTemplateContract>; test_cases?: TestCaseContract[]; solutions?: Record<string, SolutionContract>; time_limit_ms?: number; memory_limit_kb?: number; audit: AuditMetadataContract; }
export interface ProblemSummaryDTO { id: number; slug: string; title: string; difficulty: Difficulty; tags: string[]; is_ready_to_solve: boolean; user_status?: string | null; }
export interface SubmissionHistoryDTO { id: string; problem_id: number; language: string; overall_verdict: Verdict; passed_count: number; total_count: number; max_runtime_ms: number; created_at: string; source_code: string; ast_metrics: Record<string, unknown>; }
export interface ProblemWorkspaceDTO { id: number; slug: string; title: string; difficulty: Difficulty; statement_md: string; constraints_md: string | null; tags: string[]; templates: Record<string, string>; sample_test_cases: TestCaseContract[]; time_limit_ms: number; memory_limit_kb: number; }
export interface ExecutionRequestDTO { problem_id: number; language: string; source_code: string; mode?: "run" | "submit"; custom_inputs?: string[] | null; }
export interface TestCaseResultDTO { test_case_index: number; passed: boolean; verdict: Verdict; input_data?: string | null; actual_output?: string | null; expected_output?: string | null; runtime_ms?: number; error_message?: string | null; }
export interface ExecutionResponseDTO { submission_id: string; problem_id: number; overall_verdict: Verdict; passed_count: number; total_count: number; max_runtime_ms: number; results: TestCaseResultDTO[]; plugin_payloads?: Record<string, unknown>; }
'''


def main() -> None:
    schema_dir = ROOT / "contracts" / "json_schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        name = model.__name__
        payload = (model.model_json_schema(mode="validation") if hasattr(model, "model_json_schema")
                   else TypeAdapter(model).json_schema(mode="validation"))
        (schema_dir / f"{name}.schema.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "contracts" / "types.ts").write_text(TS_TYPES, encoding="utf-8")
    print(f"Exported {len(MODELS)} JSON Schemas to {schema_dir}")
    print(f"Exported TypeScript interfaces to {ROOT / 'contracts' / 'types.ts'}")


if __name__ == "__main__":
    main()
