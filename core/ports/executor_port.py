"""Abstraction for pluggable execution backends."""
from abc import ABC, abstractmethod

from core.contracts import ExecutionRequestDTO, ExecutionResponseDTO, ProblemCanonicalContract


class IExecutorPort(ABC):
    @abstractmethod
    def execute(self, problem: ProblemCanonicalContract,
                request: ExecutionRequestDTO) -> ExecutionResponseDTO:
        """Execute source against samples (run) or all cases (submit)."""
        raise NotImplementedError
