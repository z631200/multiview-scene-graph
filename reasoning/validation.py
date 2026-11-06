"""Validate text structure and provenance; this does not certify visual truth."""

import re


class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def require(condition, message):
    if not condition:
        raise ValidationError([message])


def sections(text, names):
    result = {}
    current = None
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            require(current in names, f"Unexpected heading: {current}")
            require(current not in result, f"Repeated heading: {current}")
            result[current] = []
        else:
            require(current is not None, "Start with the required ## heading")
            require(line.startswith("- "), f"Expected a '- ' bullet: {line[:100]}")
            result[current].append(line[2:].strip())
    require(set(result) == set(names), f"Required headings: {', '.join(names)}")
    for name, lines in result.items():
        require(bool(lines), f"Empty {name}: use '- None'")
        if lines == ["None"]:
            result[name] = []
        else:
            require("None" not in lines, f"Do not mix None with records in {name}")
    return result


def fields(line, count):
    parts = [p.strip() for p in line.split("|")]
    require(len(parts) == count and all(parts),
            f"Expected {count} nonempty pipe-separated fields: {line[:140]}")
    return parts


def id_list(text, pattern):
    result = [s.strip() for s in text.split(",")]
    require(all(re.fullmatch(pattern, s) for s in result), f"Invalid ID list: {text}")
    require(len(set(result)) == len(result), f"Duplicate ID in: {text}")
    return result


def new_id(key, pattern, existing):
    require(re.fullmatch(pattern, key), f"Invalid ID '{key}'; required pattern: {pattern}")
    require(key not in existing, f"Duplicate ID: {key}")


def check_references(text, objects=(), relations=(), globals_=(), edges=()):
    for pattern, allowed in (
        (r"\bv[1-4]_o[0-9]+\b", objects), (r"\bv[1-4]_r[0-9]+\b", relations),
        (r"\bg[0-9]+\b", globals_), (r"\be[0-9]+\b", edges),
    ):
        missing = set(re.findall(pattern, text)) - set(allowed)
        require(not missing, f"Unknown referenced IDs: {sorted(missing)}")


def validate_observation(text, index):
    parts = sections(text, ["Observation conditions", "Objects", "Relations", "Uncertainties"])
    require(parts["Observation conditions"], "Describe observation conditions")
    require(f"view_{index}" in " ".join(parts["Observation conditions"]),
            f"Observation conditions must identify view_{index}")
    objects, relations = {}, {}
    for line in parts["Objects"]:
        key, name, features, location, occlusion = fields(line, 5)
        new_id(key, rf"v{index}_o[1-9][0-9]*", objects)
        objects[key] = dict(name=name, features=features, location=location, occlusion=occlusion)
    for line in parts["Relations"]:
        key, subject, relation, obj, frame, certainty, evidence = fields(line, 7)
        # Accept the README's two-endpoints-first wording too, without changing meaning.
        if relation in objects and obj not in objects:
            relation, obj = obj, relation
        new_id(key, rf"v{index}_r[1-9][0-9]*", relations)
        require(subject in objects and obj in objects,
                f"{key}: subject '{subject}' and object '{obj}' must be listed local IDs")
        require(subject != obj, f"{key}: endpoints must differ")
        require(frame in ("image", "camera depth", "physical"), f"{key}: invalid frame")
        require(certainty in ("clear", "tentative"), f"{key}: invalid certainty")
        relations[key] = dict(subject=subject, object=obj, relation=relation, frame=frame,
                              certainty=certainty, evidence=evidence, view=f"view_{index}")
    check_references(text, objects, relations)
    return dict(objects=objects, relations=relations)


def collect_observations(observations):
    objects, relations = {}, {}
    require(set(observations) == {f"view_{i}" for i in range(1, 5)},
            "Exactly view_1 through view_4 are required")
    for i in range(1, 5):
        parsed = validate_observation(observations[f"view_{i}"], i)
        objects.update(parsed["objects"])
        relations.update(parsed["relations"])
    return objects, relations


def validate_correspondence(text, observations):
    objects, relations = collect_observations(observations)
    parts = sections(text, ["Global objects", "Mapping", "Ambiguities"])
    nodes, mapping = {}, {}
    bad_ids = [line.split("|")[0].strip() for line in parts["Global objects"]
               if not re.fullmatch(r"g[1-9][0-9]*", line.split("|")[0].strip())]
    require(not bad_ids, f"Invalid global IDs: {bad_ids}. Use only g plus a positive integer "
            "(g1, g2, g3, ...), with no underscores or words. Rename EVERY such ID to a "
            "distinct unused numeric ID and update ALL its references in Mapping and Ambiguities.")
    for line in parts["Global objects"]:
        key, description, sources, status, reason = fields(line, 5)
        new_id(key, r"g[1-9][0-9]*", nodes)
        sources = id_list(sources, r"v[1-4]_o[1-9][0-9]*")
        require(set(sources) <= set(objects), f"{key}: unknown local source")
        require(status in ("provisional", "unresolved"), f"{key}: invalid status")
        nodes[key] = dict(description=description, sources=sources, status=status, reason=reason)
    for line in parts["Mapping"]:
        key, targets, status = fields(line, 3)
        require(key in objects, f"Mapping contains unknown local object: {key}")
        require(key not in mapping, f"Repeated mapping: {key}")
        candidates = [] if targets == "unknown" else id_list(targets, r"g[1-9][0-9]*")
        require(set(candidates) <= set(nodes), f"{key}: unknown global candidate")
        require(status in ("provisional", "unresolved"), f"{key}: invalid mapping status")
        if status == "provisional":
            require(len(candidates) == 1, f"{key}: provisional mapping needs one target")
        mapping[key] = dict(candidates=candidates, status=status)
    require(set(mapping) == set(objects),
            f"Missing mappings: {sorted(set(objects) - set(mapping))}")
    errors = []
    for key, node in nodes.items():
        memberships = {local for local, m in mapping.items() if key in m["candidates"]}
        if memberships != set(node["sources"]):
            errors.append(f"{key}: Global objects sources must be exactly {sorted(memberships)} to match Mapping")
        accepted = [local.split("_")[0] for local in memberships
                    if mapping[local]["status"] == "provisional"]
        if len(accepted) != len(set(accepted)):
            collisions = sorted(local for local in memberships
                                if accepted.count(local.split("_")[0]) > 1)
            errors.append(f"{key}: cannot provisionally merge separate objects in the same view: "
                          f"{collisions}. Split into separate global objects and update Mapping, "
                          "or mark the node AND all those Mapping rows unresolved; preserve ambiguity.")
        if any(mapping[local]["status"] == "unresolved" for local in memberships):
            if node["status"] != "unresolved":
                errors.append(f"{key}: uncertain membership needs unresolved in Global objects")
    if errors:
        raise ValidationError(errors)
    check_references(text, objects, relations, nodes)
    return dict(nodes=nodes, mapping=mapping)


def validate_graph(text, observations, correspondence, budget=4):
    objects, relations = collect_observations(observations)
    matched = validate_correspondence(correspondence, observations)
    parts = sections(text, ["Nodes", "Edges", "Unresolved issues", "Verification requests"])
    nodes, edges, requests = {}, {}, {}
    for line in parts["Nodes"]:
        key, description, sources, status = fields(line, 4)
        new_id(key, r"g[1-9][0-9]*", nodes)
        require(key in matched["nodes"], f"Invented global object: {key}")
        source_ids = id_list(sources, r"v[1-4]_o[1-9][0-9]*")
        original = matched["nodes"][key]
        require(set(source_ids) == set(original["sources"]), f"{key}: preserve node sources")
        require(status == original["status"], f"{key}: preserve correspondence status")
        nodes[key] = dict(description=description, sources=source_ids, status=status)
    require(set(nodes) == set(matched["nodes"]),
            f"Graph must retain all global nodes. Missing: {sorted(set(matched['nodes']) - set(nodes))}")
    edge_errors = []
    for line in parts["Edges"]:
        try:
            key, triple, frame, status, basis, sources, premises, evidence = fields(line, 8)
            new_id(key, r"e[1-9][0-9]*", edges)
            parsed = re.fullmatch(r"\(\s*(g[1-9][0-9]*)\s*,\s*([a-z_]+)\s*,\s*(g[1-9][0-9]*)\s*\)", triple)
            require(parsed is not None, f"{key}: invalid triple")
            subject, relation, obj = parsed.groups()
            require(subject in nodes and obj in nodes and subject != obj, f"{key}: invalid endpoints")
            require(relation in ("on", "inside", "image_left_of", "closer_to_camera"),
                    f"{key}: unknown relation {relation}")
            expected = "physical" if relation in ("on", "inside") else None
            hint = ("physical" if expected else
                    "the source view ID (view_1, view_2, view_3 or view_4), NOT a relation name")
            require(frame == expected if expected else frame in {f"view_{i}" for i in range(1, 5)},
                    f"{key}: invalid reference frame '{frame}' for {relation}; expected {hint}. "
                    f"Use the view of source relation IDs {sources}; do not change endpoints or predicate.")
            require(status in ("provisional", "unresolved", "conflicting"), f"{key}: invalid status")
            require(basis == "observed" and premises == "none", f"{key}: inference is not enabled")
            source_ids = id_list(sources, r"v[1-4]_r[1-9][0-9]*")
            uncertain = any(nodes[n]["status"] == "unresolved" for n in (subject, obj))
            for source in source_ids:
                require(source in relations, f"{key}: unknown relation source {source}")
                local = relations[source]
                require(frame == "physical" or local["view"] == frame, f"{key}: source view mismatch")
                required_frame = {"on": "physical", "inside": "physical",
                                  "image_left_of": "image", "closer_to_camera": "camera depth"}[relation]
                require(local["frame"] == required_frame, f"{key}: source reference type mismatch")
                for endpoint, global_id in ((local["subject"], subject), (local["object"], obj)):
                    require(global_id in matched["mapping"][endpoint]["candidates"],
                            f"{key}: {source} endpoints do not support triple order")
                    uncertain |= matched["mapping"][endpoint]["status"] == "unresolved"
                uncertain |= local["certainty"] == "tentative"
            require(not uncertain or status != "provisional", f"{key}: uncertain evidence cannot be provisional")
            edges[key] = dict(subject=subject, relation=relation, object=obj, frame=frame,
                              status=status, sources=source_ids, evidence=evidence)
        except ValidationError as exc:
            edge_errors.extend(exc.errors)
    if edge_errors:
        raise ValidationError(edge_errors)
    seen = {}
    for key, edge in edges.items():
        signature = (edge["subject"], edge["relation"], edge["object"], edge["frame"])
        require(signature not in seen, f"{key}: duplicate triple and frame; combine sources")
        reverse = (edge["object"], edge["relation"], edge["subject"], edge["frame"])
        if edge["relation"] in ("image_left_of", "closer_to_camera") and reverse in seen:
            other = edges[seen[reverse]]
            require(edge["status"] == other["status"] == "conflicting",
                    f"{key}: opposite same-view claims must both be conflicting")
        seen[signature] = key
    for line in parts["Verification requests"]:
        key, view, targets, question = fields(line, 4)
        new_id(key, r"q[1-9][0-9]*", requests)
        require(view in observations, f"{key}: invalid target view")
        try:
            source_ids = id_list(targets, r"v[1-4]_o[1-9][0-9]*")
        except ValidationError as exc:
            raise ValidationError([f"{key}: invalid target object list '{targets}'. "
                                   "Use existing local IDs in the requested view, or omit "
                                   "this request if no listed object can be targeted."]) from exc
        require(all(s in objects and s.startswith(f"v{view[-1]}_") for s in source_ids),
                f"{key}: target objects must belong to requested view")
        mentioned_views = re.findall(r"\bview[_ ]?([1-4])\b", question, flags=re.I)
        require(all(v == view[-1] for v in mentioned_views),
                f"{key}: verifier only sees {view}. Ask about visible features in that "
                "image, not identity comparisons with another view.")
        check_references(question, source_ids)
        requests[key] = dict(view=view, objects=source_ids, question=question)
    require(len(requests) <= budget, f"Verification requests exceed budget {budget}")
    check_references(text, objects, relations, nodes, edges)
    return dict(nodes=nodes, edges=edges, requests=requests)


def normalize_graph(text, observations, correspondence):
    """Only repair uniquely recoverable frame aliases and consolidate identical edges.

    Claims, node identity and predicate direction stay as supplied by the model.
    The caller must still validate the result and preserve the raw text and audit log.
    """
    _, local_relations = collect_observations(observations)
    matched = validate_correspondence(correspondence, observations)
    parts = sections(text, ["Nodes", "Edges", "Unresolved issues", "Verification requests"])
    changes, aliases, merged, seen_ids = [], {}, {}, set()
    for line in parts["Edges"]:
        record = fields(line, 8)
        edge_id, triple, frame, status, basis, source_text, premises, evidence = record
        new_id(edge_id, r"e[1-9][0-9]*", seen_ids)
        seen_ids.add(edge_id)
        parsed = re.fullmatch(r"\(\s*(g[1-9][0-9]*)\s*,\s*([a-z_]+)\s*,\s*(g[1-9][0-9]*)\s*\)", triple)
        if parsed is None:
            # Malformed triples are left for the validator, never guessed.
            merged[("invalid", edge_id)] = record
            continue
        subject, relation, obj = parsed.groups()
        source_ids = id_list(source_text, r"v[1-4]_r[1-9][0-9]*")
        local = [local_relations[s] for s in source_ids if s in local_relations]
        known_sources = len(local) == len(source_ids)
        endpoints_match = known_sources and all(
            subject in matched["mapping"][r["subject"]]["candidates"]
            and obj in matched["mapping"][r["object"]]["candidates"] for r in local
        )
        required_type = {"on": "physical", "inside": "physical",
                         "image_left_of": "image", "closer_to_camera": "camera depth"}.get(relation)
        if endpoints_match and required_type and all(r["frame"] == required_type for r in local):
            target = None
            if relation in ("on", "inside") and frame == relation:
                target = "physical"
            elif relation in ("image_left_of", "closer_to_camera"):
                views = {r["view"] for r in local}
                # Never override a supplied view_N, even if it appears incorrect.
                if frame in (relation, required_type) and len(views) == 1:
                    target = next(iter(views))
            if target and target != frame:
                changes.append(dict(kind="reference_frame", edge=edge_id,
                                    before=frame, after=target, sources=source_ids))
                frame = record[2] = target
        signature = (subject, relation, obj, frame)
        previous = merged.get(signature)
        valid_statuses = {"provisional", "unresolved", "conflicting"}
        if (previous and basis == previous[4] == "observed"
                and premises == previous[6] == "none"
                and status in valid_statuses and previous[3] in valid_statuses):
            previous_id = previous[0]
            before_sources = id_list(previous[5], r"v[1-4]_r[1-9][0-9]*")
            combined = list(dict.fromkeys(before_sources + source_ids))
            previous_status = previous[3]
            combined_status = ("conflicting" if "conflicting" in (status, previous_status)
                               else "unresolved" if "unresolved" in (status, previous_status)
                               else "provisional")
            previous[3], previous[5] = combined_status, ", ".join(combined)
            if evidence != previous[7]:
                previous[7] += "; " + evidence
            aliases[edge_id] = previous_id
            changes.append(dict(kind="duplicate_edge", edge=edge_id, retained=previous_id,
                                before_statuses=[previous_status, status], after_status=combined_status,
                                sources=combined))
        else:
            # Do not erase incompatible records merely because their signature matches.
            key = signature if previous is None else ("incompatible", edge_id)
            merged[key] = record
    if not changes:
        return text, []
    parts["Edges"] = [" | ".join(record) for record in merged.values()]
    if aliases:
        pattern = r"\b(?:" + "|".join(re.escape(key) for key in aliases) + r")\b"
        for name in ("Unresolved issues", "Verification requests"):
            parts[name] = [re.sub(pattern, lambda m: aliases[m[0]], line) for line in parts[name]]
    normalized = "\n\n".join(
        "## " + name + "\n" + "\n".join("- " + line for line in (lines or ["None"]))
        for name, lines in parts.items()
    ) + "\n"
    return normalized, changes
