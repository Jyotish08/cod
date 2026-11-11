"""SQLite schema for the normalized LeetCode problem archive.

The complete source record is retained in ``problems.source_json`` so fields
not yet represented by a normalized table are never lost.
"""

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (difficulty IN ('EASY','MEDIUM','HARD','UNKNOWN')),
    description_md TEXT NOT NULL DEFAULT 'Description pending.',
    category_tags TEXT NOT NULL DEFAULT '[]',
    source_json TEXT NOT NULL,
    has_testcases INTEGER NOT NULL CHECK (has_testcases IN (0,1)),
    has_starter_code INTEGER NOT NULL CHECK (has_starter_code IN (0,1)),
    has_solution INTEGER NOT NULL CHECK (has_solution IN (0,1)),
    ingestion_status TEXT NOT NULL CHECK (ingestion_status IN
        ('COMPLETE','PARTIAL_NEEDS_TESTS','PARTIAL_NEEDS_CODE','CORRUPTED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_problems_difficulty ON problems(difficulty);
CREATE INDEX IF NOT EXISTS idx_problems_title ON problems(title);
CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    input TEXT NOT NULL,
    expected_output TEXT NOT NULL,
    is_sample INTEGER NOT NULL DEFAULT 1 CHECK (is_sample IN (0,1)),
    explanation TEXT
);
CREATE INDEX IF NOT EXISTS idx_test_cases_problem ON test_cases(problem_id);
CREATE TABLE IF NOT EXISTS code_templates (
    id INTEGER PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    language TEXT NOT NULL DEFAULT 'python',
    starter_code TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_code_templates_problem ON code_templates(problem_id);
CREATE TABLE IF NOT EXISTS solutions (
    id INTEGER PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    language TEXT NOT NULL DEFAULT 'python',
    solution_code TEXT NOT NULL,
    complexity_time TEXT,
    complexity_space TEXT
);
CREATE INDEX IF NOT EXISTS idx_solutions_problem ON solutions(problem_id);
"""
