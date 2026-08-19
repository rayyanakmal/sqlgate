"""SQLGate: natural language to safe, executable SQL through a deterministic gate."""

from sqlgate.gate import Gate
from sqlgate.proposer import IntentProposal, StubProposer
from sqlgate.result import GateResult
from sqlgate.schema import Schema

__version__ = "0.1.0"
__all__ = ["Gate", "GateResult", "IntentProposal", "Schema", "StubProposer", "__version__"]
