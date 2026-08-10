"""Build and compile the LangGraph job pipeline."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestration.deps import PipelineDeps
from orchestration.nodes.batch import make_batch_nodes
from orchestration.nodes.pair import make_pair_nodes
from orchestration.state import PairState, PipelineState


def build_pair_subgraph(deps: PipelineDeps) -> CompiledStateGraph:
    nodes = make_pair_nodes(deps)
    builder = StateGraph(PairState)
    builder.add_node("screen", nodes["screen"])
    builder.add_node("assess", nodes["assess"])
    builder.add_node("cover_letter", nodes["cover_letter"])
    builder.add_node("emit_pair_result", nodes["emit_pair_result"])

    builder.add_edge(START, "screen")
    builder.add_conditional_edges(
        "screen",
        nodes["route_screen"],
        {"assess": "assess", "pair_end": "emit_pair_result"},
    )
    builder.add_conditional_edges(
        "assess",
        nodes["route_assess"],
        {"cover_letter": "cover_letter", "pair_end": "emit_pair_result"},
    )
    builder.add_edge("cover_letter", "emit_pair_result")
    builder.add_edge("emit_pair_result", END)
    return builder.compile()


def build_pipeline_graph(
    deps: PipelineDeps,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    batch = make_batch_nodes(deps)
    pair_pipeline = build_pair_subgraph(deps)

    builder = StateGraph(PipelineState)
    builder.add_node("collect", batch["collect"])
    builder.add_node("normalize", batch["normalize"])
    builder.add_node("dedupe", batch["dedupe"])
    builder.add_node("persist_jobs", batch["persist_jobs"])
    builder.add_node("build_pairs", batch["build_pairs"])
    builder.add_node("pair_pipeline", pair_pipeline)
    builder.add_node("finalize", batch["finalize"])

    builder.add_edge(START, "collect")
    builder.add_edge("collect", "normalize")
    builder.add_edge("normalize", "dedupe")
    builder.add_edge("dedupe", "persist_jobs")
    builder.add_edge("persist_jobs", "build_pairs")
    builder.add_conditional_edges(
        "build_pairs",
        batch["fanout"],
        ["pair_pipeline", "finalize"],
    )
    builder.add_edge("pair_pipeline", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
