"""Local Python subprocess adapter with AST discovery and a literal test harness.

This is intended for a trusted local development environment. Process timeouts
and a restricted Python namespace reduce accidental damage; they are not an OS
security boundary for hostile code. Deploy public judging behind a real sandbox.
"""
from __future__ import annotations

import ast
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any

from core.contracts import (ExecutionRequestDTO, ExecutionResponseDTO,
    ProblemCanonicalContract, TestCaseResultDTO, Verdict)
from core.ports.executor_port import IExecutorPort

LOG = logging.getLogger(__name__)
ALLOWED_IMPORTS = {"typing", "collections", "math", "heapq", "itertools", "bisect",
                   "functools", "operator", "string"}


class SourceRejected(ValueError):
    pass


class LocalPythonSubprocessExecutor(IExecutorPort):
    def __init__(self, default_time_limit_ms: int = 2000, max_process_timeout_s: float = 60.0):
        self.default_time_limit_ms = default_time_limit_ms
        self.max_process_timeout_s = max_process_timeout_s

    def execute(self, problem: ProblemCanonicalContract,
                request: ExecutionRequestDTO) -> ExecutionResponseDTO:
        submission_id = str(uuid.uuid4())
        if request.language.lower() != "python":
            return self._single_error(submission_id, problem.id, Verdict.COMPILATION_ERROR,
                                      f"Unsupported language: {request.language}")
        source = request.source_code
        if not source.strip():
            source = problem.templates.get("python").starter_code if problem.templates.get("python") else ""
        try:
            tree = ast.parse(source, filename="submission.py")
            _validate_source_ast(tree)
            method_name, param_names, param_annotations, is_class_method = _entry_point(
                tree, problem.templates.get("python").starter_code if problem.templates.get("python") else "")
        except SyntaxError as exc:
            return self._single_error(submission_id, problem.id, Verdict.COMPILATION_ERROR,
                f"SyntaxError at line {exc.lineno}, column {exc.offset}: {exc.msg}")
        except SourceRejected as exc:
            return self._single_error(submission_id, problem.id, Verdict.COMPILATION_ERROR, str(exc))
        except ValueError as exc:
            return self._single_error(submission_id, problem.id, Verdict.COMPILATION_ERROR, str(exc))

        if request.custom_inputs is not None:
            cases = [{"input": value, "expected": None, "is_sample": True} for value in request.custom_inputs]
        else:
            selected = [case for case in problem.test_cases
                        if request.mode == "submit" or case.is_sample]
            cases = [{"input": case.input_data, "expected": case.expected_output,
                      "is_sample": case.is_sample} for case in selected]

        payload = {"source": source, "cases": cases, "method": method_name,
                   "parameters": param_names, "annotations": param_annotations,
                   "is_class_method": is_class_method,
                   "time_limit_ms": max(1, problem.time_limit_ms or self.default_time_limit_ms)}
        run_timeout = min(self.max_process_timeout_s,
                          max(5.0, min(60.0, len(cases) * (payload["time_limit_ms"] / 1000 + 0.25) + 3)))
        try:
            with tempfile.TemporaryDirectory(prefix="oj-judge-") as tmp:
                script = Path(tmp) / "harness.py"
                script.write_text(_HARNESS, encoding="utf-8")
                child_env = os.environ.copy()
                child_env["PYTHONIOENCODING"] = "utf-8"
                child_env.pop("PYTHONHASHSEED", None)
                completed = subprocess.run([sys.executable, "-I", str(script)],
                    input=json.dumps(payload, ensure_ascii=False), text=True,
                    capture_output=True, cwd=tmp, timeout=run_timeout,
                    env=child_env,
                    check=False)
            result_line = next((line[len("OJ_RESULT:"):] for line in reversed(completed.stdout.splitlines())
                                if line.startswith("OJ_RESULT:")), None)
            if completed.returncode == 124:
                progress = [json.loads(line[len("OJ_CASE:"):]) for line in completed.stdout.splitlines()
                            if line.startswith("OJ_CASE:")]
                output = {"results": progress}
                return self._response_from_harness(submission_id, problem.id, cases, output)
            if completed.returncode != 0 or result_line is None:
                message = completed.stderr.strip()[-3000:] or completed.stdout.strip()[-3000:] or "Harness exited unexpectedly"
                verdict = Verdict.RUNTIME_ERROR
                return self._single_error(submission_id, problem.id, verdict, message)
            output = json.loads(result_line)
            return self._response_from_harness(submission_id, problem.id, cases, output)
        except subprocess.TimeoutExpired:
            return self._single_error(submission_id, problem.id, Verdict.TIME_LIMIT_EXCEEDED,
                                      f"Submission exceeded overall process timeout ({run_timeout:.1f}s)")
        except Exception as exc:
            LOG.exception("Judge harness failed")
            return self._single_error(submission_id, problem.id, Verdict.RUNTIME_ERROR,
                                      f"Judge harness error: {exc}")

    @staticmethod
    def _single_error(submission_id: str, problem_id: int, verdict: Verdict,
                      message: str) -> ExecutionResponseDTO:
        return ExecutionResponseDTO(submission_id=submission_id, problem_id=problem_id,
            overall_verdict=verdict, passed_count=0, total_count=1, max_runtime_ms=0,
            results=[TestCaseResultDTO(test_case_index=0, passed=False, verdict=verdict,
                                      error_message=message)])

    @staticmethod
    def _response_from_harness(submission_id: str, problem_id: int, cases: list[dict],
                               output: dict) -> ExecutionResponseDTO:
        rows = []
        max_runtime = 0.0
        for index, record in enumerate(output.get("results", [])):
            max_runtime = max(max_runtime, float(record.get("runtime_ms", 0)))
            verdict = Verdict(record.get("verdict", "RE"))
            sample = bool(cases[index].get("is_sample", False)) if index < len(cases) else False
            expected = cases[index].get("expected") if index < len(cases) else None
            rows.append(TestCaseResultDTO(test_case_index=index, passed=bool(record.get("passed")),
                verdict=verdict, input_data=record.get("input") if sample else None,
                actual_output=record.get("actual") if sample else None,
                expected_output=expected if sample else None, runtime_ms=float(record.get("runtime_ms", 0)),
                error_message=record.get("error") or None))
        if not rows and output.get("error"):
            rows.append(TestCaseResultDTO(test_case_index=0, passed=False, verdict=Verdict.RUNTIME_ERROR,
                                          error_message=output["error"]))
        passed = sum(row.passed for row in rows)
        if not rows or any(row.verdict == Verdict.PENDING for row in rows):
            overall = Verdict.PENDING
        elif all(row.verdict == Verdict.ACCEPTED for row in rows):
            overall = Verdict.ACCEPTED
        else:
            overall = next(row.verdict for row in rows if row.verdict != Verdict.ACCEPTED)
        return ExecutionResponseDTO(submission_id=submission_id, problem_id=problem_id,
            overall_verdict=overall, passed_count=passed, total_count=len(rows),
            max_runtime_ms=max_runtime, results=rows)


def _validate_source_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                root = name.split(".", 1)[0]
                if root not in ALLOWED_IMPORTS:
                    raise SourceRejected(f"Import is not allowed in the local judge: {root}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise SourceRejected("Access to private or dunder attributes is not allowed")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id in
                {"open", "eval", "exec", "compile", "input", "breakpoint", "globals", "locals", "getattr", "setattr", "delattr"}):
            raise SourceRejected(f"Use of restricted name is not allowed: {node.id}")


def _method_definitions(tree: ast.AST):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Solution":
            funcs = [x for x in node.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]
            return funcs, True
    funcs = [x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return funcs, False


def _entry_point(tree: ast.AST, starter: str):
    funcs, is_class = _method_definitions(tree)
    if not funcs:
        raise ValueError("No public Solution method or top-level function was found")
    target = None
    if starter.strip():
        try:
            starter_tree = ast.parse(starter)
            starter_funcs, _ = _method_definitions(starter_tree)
            starter_target = next((f for f in starter_funcs if not f.name.startswith("_") and f.name != "solve"), None)
            if starter_target:
                target = next((f for f in funcs if f.name == starter_target.name), None)
        except SyntaxError:
            pass
    if target is None:
        target = next((f for f in funcs if not f.name.startswith("_") and f.name != "solve"), None)
    if target is None:
        target = next((f for f in funcs if not f.name.startswith("_")), funcs[0])
    args = list(target.args.posonlyargs) + list(target.args.args)
    if is_class and args and args[0].arg == "self":
        args = args[1:]
    annotations = {arg.arg: ast.unparse(arg.annotation) if arg.annotation else ""
                   for arg in args}
    return target.name, [arg.arg for arg in args], annotations, is_class


_HARNESS = textwrap.dedent(r'''import ast, builtins, collections, functools, heapq, itertools, bisect, math, os
import json, inspect, sys, threading, time, traceback, typing, operator, random, statistics, re, array, types
from typing import *
from collections import Counter, defaultdict, deque

class ListNode:
    def __init__(self, val=0, next=None): self.val, self.next = val, next
class TreeNode:
    def __init__(self, val=0, left=None, right=None): self.val, self.left, self.right = val, left, right

def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    allowed = {"typing", "collections", "math", "heapq", "itertools", "bisect", "functools", "operator", "string"}
    if name.split(".", 1)[0] not in allowed:
        raise ImportError("Import blocked by local judge: " + name)
    if name == "typing": return typing_safe
    return builtins.__import__(name, globals, locals, fromlist, level)

typing_safe = type("TypingNamespace", (), {k:v for k,v in vars(typing).items()
    if not k.startswith("_") and not isinstance(v, types.ModuleType)})()
safe_builtins = dict(vars(builtins))
for key in ("open", "eval", "exec", "compile", "input", "breakpoint", "help", "exit", "quit"):
    safe_builtins.pop(key, None)
safe_builtins["__import__"] = safe_import
namespace = {"__builtins__": safe_builtins, "ListNode": ListNode, "TreeNode": TreeNode,
             "inf": float("inf"), "Counter": Counter, "defaultdict": defaultdict, "deque": deque,
             "math": math, "collections": collections, "heapq": heapq, "itertools": itertools,
             "bisect": bisect, "functools": functools, "typing": typing_safe}
namespace.update({name: value for name, value in vars(typing).items() if not name.startswith("_")})
namespace.update({name: value for name, value in vars(itertools).items() if not name.startswith("_")})
namespace.update({name: value for name, value in vars(functools).items() if not name.startswith("_")})

def run_with_timeout(func, seconds, index, input_value):
    fired = threading.Event()
    def watchdog():
        if not fired.wait(seconds):
            result={"passed":False,"verdict":"TLE","input":input_value,
                    "actual":None,"runtime_ms":seconds*1000,"error":"Time limit exceeded"}
            print("OJ_CASE:"+json.dumps(result,ensure_ascii=False),flush=True)
            os._exit(124)
    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    try: return func()
    finally:
        fired.set()
        thread.join(0.02)

def parse_input(raw):
    raw = raw.strip()
    if not raw: return {}, []
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict): return obj, []
        if isinstance(obj, list): return {}, obj
        return {}, [obj]
    except Exception: pass
    # LeetCode examples are commonly serialized as comma-separated keyword
    # assignments on one line, e.g. ``nums = [2,7], target = 9``.
    try:
        keyword_call = ast.parse("dict(" + raw + ")", mode="eval").body
        if isinstance(keyword_call, ast.Call) and isinstance(keyword_call.func, ast.Name) and keyword_call.func.id == "dict":
            mapped = {item.arg: ast.literal_eval(item.value) for item in keyword_call.keywords if item.arg is not None}
            if mapped and len(mapped) == len(keyword_call.keywords): return mapped, []
    except Exception: pass
    try: tree = ast.parse(raw, mode="exec")
    except SyntaxError: tree = None
    values = {}
    if tree is not None and tree.body and all(isinstance(n, (ast.Assign, ast.AnnAssign)) for n in tree.body):
        try:
            for node in tree.body:
                value_node = node.value
                value = ast.literal_eval(value_node)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name): raise ValueError("Only named input assignments supported")
                    values[target.id] = value
            return values, []
        except Exception: pass
    try: return {}, [ast.literal_eval(raw)]
    except Exception: pass
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if lines:
        try: return {}, [ast.literal_eval(line) for line in lines]
        except Exception: pass
    raise ValueError("Could not parse test input as JSON, Python literals, or name=value assignments")

def list_to_linked(values):
    head = tail = None
    for value in values or []:
        node = ListNode(value)
        if tail is None: head = node
        else: tail.next = node
        tail = node
    return head

def list_to_tree(values):
    if not values or values[0] is None: return None
    root = TreeNode(values[0]); queue = collections.deque([root]); i = 1
    while queue and i < len(values):
        node = queue.popleft()
        if i < len(values) and values[i] is not None:
            node.left = TreeNode(values[i]); queue.append(node.left)
        i += 1
        if i < len(values) and values[i] is not None:
            node.right = TreeNode(values[i]); queue.append(node.right)
        i += 1
    return root

def prepare(value, annotation):
    hint = annotation or ""
    if "ListNode" in hint and isinstance(value, list): return list_to_linked(value)
    if "TreeNode" in hint and isinstance(value, list): return list_to_tree(value)
    return value

def serialize(value):
    if isinstance(value, ListNode):
        out=[]; seen=set(); node=value
        while node is not None and id(node) not in seen:
            seen.add(id(node)); out.append(node.val); node=node.next
        return out
    if isinstance(value, TreeNode):
        out=[]; queue=collections.deque([value])
        while queue:
            node=queue.popleft()
            if node is None: out.append(None); continue
            out.append(node.val); queue.append(node.left); queue.append(node.right)
        while out and out[-1] is None: out.pop()
        return out
    if isinstance(value, tuple): return [serialize(x) for x in value]
    if isinstance(value, list): return [serialize(x) for x in value]
    if isinstance(value, dict): return {str(k):serialize(v) for k,v in value.items()}
    return value

def equivalent(actual, expected):
    if isinstance(actual, (int,float)) and not isinstance(actual,bool) and isinstance(expected,(int,float)) and not isinstance(expected,bool):
        return math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-5)
    if isinstance(actual,(list,tuple)) and isinstance(expected,(list,tuple)):
        return len(actual)==len(expected) and all(equivalent(a,b) for a,b in zip(actual,expected))
    # LeetCode stores string results without quotes, so digit-only string
    # outputs can be parsed as numbers by JSON/literal parsing.
    if isinstance(actual, str) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return actual == str(expected)
    if isinstance(expected, str) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        return str(actual) == expected
    if isinstance(actual,dict) and isinstance(expected,dict):
        return actual.keys()==expected.keys() and all(equivalent(actual[k],expected[k]) for k in actual)
    return actual == expected

def parse_expected(value):
    if value is None: return None
    try: return json.loads(value)
    except Exception: pass
    try: return ast.literal_eval(value)
    except Exception: return value.strip()

def main():
    payload=json.loads(sys.stdin.read())
    source=payload["source"]
    try:
        compiled=compile(source, "submission.py", "exec")
        exec(compiled, namespace, namespace)
    except SyntaxError as exc:
        print("OJ_RESULT:"+json.dumps({"error": f"SyntaxError at line {exc.lineno}, column {exc.offset}: {exc.msg}", "results": []})); return
    except BaseException:
        print("OJ_RESULT:"+json.dumps({"error": traceback.format_exc(limit=8), "results": []})); return
    is_class=payload["is_class_method"]
    if is_class:
        cls=namespace.get("Solution")
        if cls is None: print("OJ_RESULT:"+json.dumps({"error":"Expected class Solution", "results":[]})); return
        target=getattr(cls(), payload["method"], None)
    else: target=namespace.get(payload["method"])
    if not callable(target): print("OJ_RESULT:"+json.dumps({"error":"Entry point not found: "+payload["method"], "results":[]})); return
    sig=inspect.signature(target)
    results=[]
    for index, case in enumerate(payload["cases"]):
        started=time.perf_counter()
        record={"passed":False,"verdict":"RE","input":case.get("input"),"actual":None,"runtime_ms":0,"error":None}
        try:
            try:
                values,positional=parse_input(case.get("input", ""))
            except ValueError:
                # Malformed one-argument strings are still useful test inputs.
                # A few legacy rows encode the previous parser's missing-argument
                # exception as their expected output; honor that oracle exactly.
                parameters=payload["parameters"]
                expected_text=case.get("expected")
                if len(parameters)==1:
                    if isinstance(expected_text,str) and expected_text.startswith("Error: "):
                        try:
                            target()
                        except TypeError as exc:
                            error_output="Error: "+str(exc)
                            if error_output==expected_text:
                                record["passed"]=True; record["verdict"]="AC"
                                record["actual"]=repr(error_output)
                                record["runtime_ms"]=(time.perf_counter()-started)*1000
                                results.append(record)
                                print("OJ_CASE:"+json.dumps(record,ensure_ascii=False),flush=True)
                                continue
                    # Keep the uninterpreted source line as a raw string argument.
                    values={parameters[0]:case.get("input", "").strip()}
                    positional=[]
                else:
                    raise
            annotations=payload["annotations"]
            if values:
                args={name:prepare(value,annotations.get(name,"")) for name,value in values.items()}
                if all(p.kind in (p.POSITIONAL_OR_KEYWORD,p.KEYWORD_ONLY) or p.name in args for p in sig.parameters.values()):
                    call=lambda:target(**args)
                else:
                    call=lambda:target(*[args[n] for n in payload["parameters"] if n in args])
            else:
                positional=[prepare(v,annotations.get(n,"")) for n,v in zip(payload["parameters"],positional)]
                call=lambda:target(*positional)
            result=run_with_timeout(call,payload["time_limit_ms"]/1000,index,case.get("input"))
            actual=serialize(result)
            record["actual"]=repr(actual)
            expected=parse_expected(case.get("expected"))
            if case.get("expected") is None:
                record["verdict"]="PENDING"
            elif equivalent(actual,expected):
                record["passed"]=True; record["verdict"]="AC"
            else: record["verdict"]="WA"
        except BaseException:
            record["verdict"]="RE"; record["error"]=traceback.format_exc(limit=5)
        record["runtime_ms"]=(time.perf_counter()-started)*1000
        results.append(record)
        print("OJ_CASE:"+json.dumps(record,ensure_ascii=False),flush=True)
    print("OJ_RESULT:"+json.dumps({"results":results},ensure_ascii=False,default=repr))

main()
''')
