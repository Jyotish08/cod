"""Fast static AST metrics for Python submissions."""
import ast
from typing import Any, Dict

from core.contracts import ExecutionRequestDTO, ExecutionResponseDTO, ProblemCanonicalContract
from core.ports.plugin_port import ISubmissionPlugin


class _MetricsVisitor(ast.NodeVisitor):
    def __init__(self):
        self.loop_depth = 0
        self.max_loop_depth = 0
        self.branches = 0
        self.recursive_functions: set[str] = set()
        self._functions: list[str] = []

    def visit_For(self, node):
        self.branches += 1
        self.loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        self.generic_visit(node)
        self.loop_depth -= 1

    visit_AsyncFor = visit_For

    def visit_While(self, node):
        self.branches += 1
        self.loop_depth += 1
        self.max_loop_depth = max(self.max_loop_depth, self.loop_depth)
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_If(self, node):
        self.branches += 1
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self.branches += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self.branches += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.branches += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in self._functions:
            self.recursive_functions.add(node.func.id)
        self.generic_visit(node)


class ASTMetricsPlugin(ISubmissionPlugin):
    name = "ast_metrics"

    def on_submission_completed(self, problem: ProblemCanonicalContract,
            request: ExecutionRequestDTO, response: ExecutionResponseDTO) -> Dict[str, Any]:
        source = request.source_code or ""
        try:
            tree = ast.parse(source)
            visitor = _MetricsVisitor()
            visitor.visit(tree)
            return {"line_count": len(source.splitlines()),
                    "max_loop_nesting_depth": visitor.max_loop_depth,
                    "has_recursion": bool(visitor.recursive_functions),
                    "recursive_functions": sorted(visitor.recursive_functions),
                    "cyclomatic_branches": visitor.branches + 1}
        except SyntaxError as exc:
            return {"line_count": len(source.splitlines()), "parse_error": exc.msg,
                    "line": exc.lineno}
