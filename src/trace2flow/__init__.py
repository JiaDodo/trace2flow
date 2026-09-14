"""Typed trace ingestion and upstream adapters for Trace2Flow."""

from .asp import (
    PARAM_ENCODING,
    AspTraceBundle,
    decode_json_value,
    encode_json_value,
    to_asp,
)
from .candidate import (
    AlignmentStatus,
    CandidateDag,
    CandidateNode,
    DagEdge,
    UnresolvedDependency,
    build_candidate_dag,
    candidate_json,
    mine_candidate_dag,
)
from .datasets import (
    DatasetLeakageError,
    DatasetSplit,
    assert_disjoint,
    split_by_test_run_ids,
)
from .io import (
    TraceFormatError,
    canonical_json,
    dump_trace_dataset,
    load_trace_dataset,
    loads_trace_dataset,
)
from .models import (
    DatasetPartition,
    RunProvenance,
    RunStatus,
    SideEffect,
    SideEffectKind,
    StepStatus,
    TraceDataset,
    TraceRun,
    TraceStep,
)
from .upstream import (
    UPSTREAM_BASELINE_COMMIT,
    RuleProfile,
    UpstreamCompilationError,
    UpstreamSignals,
    compile_with_upstream,
)

__all__ = [
    "PARAM_ENCODING",
    "UPSTREAM_BASELINE_COMMIT",
    "AlignmentStatus",
    "AspTraceBundle",
    "CandidateDag",
    "CandidateNode",
    "DagEdge",
    "DatasetLeakageError",
    "DatasetPartition",
    "DatasetSplit",
    "RuleProfile",
    "RunProvenance",
    "RunStatus",
    "SideEffect",
    "SideEffectKind",
    "StepStatus",
    "TraceDataset",
    "TraceFormatError",
    "TraceRun",
    "TraceStep",
    "UnresolvedDependency",
    "UpstreamCompilationError",
    "UpstreamSignals",
    "assert_disjoint",
    "build_candidate_dag",
    "candidate_json",
    "canonical_json",
    "compile_with_upstream",
    "decode_json_value",
    "dump_trace_dataset",
    "encode_json_value",
    "load_trace_dataset",
    "loads_trace_dataset",
    "mine_candidate_dag",
    "split_by_test_run_ids",
    "to_asp",
]
