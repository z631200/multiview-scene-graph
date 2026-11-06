"""Export the existing central-LLM result without adding geometric inferences."""

from reasoning.validation import validate_correspondence, validate_graph


def export_views(text, observations, correspondence, budget=4):
    graph = validate_graph(text, observations, correspondence, budget)
    result = {}
    for vid in observations:
        result[vid] = dict(schema_version="reasoning-graph-v1", graph_type="full_reasoning", view_id=vid,
            method="central_llm", status="model_prediction", nodes=[dict(id=i, **v) for i, v in graph["nodes"].items()],
            edges=[dict(id=i, source=e["subject"], target=e["object"], **{k:v for k,v in e.items() if k not in ("subject", "object")})
                   for i,e in graph["edges"].items() if e["frame"] in ("physical", vid)],
            verification_requests={i:v for i,v in graph["requests"].items() if v["view"] == vid})
    return result, validate_correspondence(correspondence, observations)
