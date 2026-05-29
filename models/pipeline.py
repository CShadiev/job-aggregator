"""Pipeline stage identifiers for jobs in the processing queue."""


class PipelineStage:
    """String constants stored on processing documents as ``pipeline_stage``."""

    COLLECTED = "collected"
    NORMALIZED = "normalized"
    DEDUPLICATED = "deduplicated"
    ASSESSED = "assessed"
