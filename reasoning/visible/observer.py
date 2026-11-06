"""Serialize validated local observations; preserve the model's relation wording."""

from reasoning.validation import validate_observation


def export_observation(text, index):
    data = validate_observation(text, index)
    return dict(schema_version="local-observation-v1", graph_type="visible_reasoning", view_id=f"view_{index}",
        status="model_prediction", nodes=[dict(id=i, **v) for i,v in data["objects"].items()],
        edges=[dict(id=i, source=e["subject"], target=e["object"], **{k:v for k,v in e.items() if k not in ("subject", "object")})
               for i,e in data["relations"].items()])
