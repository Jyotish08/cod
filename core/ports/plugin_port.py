"""Submission-completion plugin socket and lightweight registry."""
from abc import ABC, abstractmethod
from typing import Any, Dict

from core.contracts import ExecutionRequestDTO, ExecutionResponseDTO, ProblemCanonicalContract


class ISubmissionPlugin(ABC):
    name: str

    @abstractmethod
    def on_submission_completed(self, problem: ProblemCanonicalContract,
            request: ExecutionRequestDTO, response: ExecutionResponseDTO) -> Dict[str, Any]:
        raise NotImplementedError


class PluginRegistry:
    def __init__(self):
        self._plugins: dict[str, ISubmissionPlugin] = {}

    def register(self, plugin: ISubmissionPlugin) -> None:
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)

    def dispatch(self, problem: ProblemCanonicalContract,
                 request: ExecutionRequestDTO, response: ExecutionResponseDTO) -> None:
        for name, plugin in tuple(self._plugins.items()):
            try:
                payload = plugin.on_submission_completed(problem, request, response)
                if payload is not None:
                    response.plugin_payloads[name] = payload
            except Exception as exc:  # plugin faults must not erase a judge verdict
                response.plugin_payloads.setdefault("plugin_errors", {})[name] = str(exc)
