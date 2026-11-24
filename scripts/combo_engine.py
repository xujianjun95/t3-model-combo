"""Candidate selection and model combination ranking for the widget."""

from itertools import combinations
import math

if __package__:
    from .config_store import DEFAULTS
else:
    from config_store import DEFAULTS


def default_provider_ids(providers):
    matches = [provider for provider in providers if provider["matchedModelIds"]]
    enabled = [provider for provider in matches if provider["enabled"]]
    return [provider["providerInstanceId"] for provider in enabled or matches]


def select_candidates(models, providers, *, mode, provider_ids=None, creator_names=None, group=None):
    by_id = {model["id"]: model for model in models}
    if mode == "creator":
        creators = set(creator_names) if creator_names is not None else {m["creator"] for m in models}
        return [model for model in models if model["creator"] in creators]

    if mode == "t3":
        selected = set(default_provider_ids(providers) if provider_ids is None else provider_ids)
        excluded = set()
    elif mode == "custom":
        group = group or {}
        selected = set(group.get("t3ProviderIds", []))
        excluded = set(group.get("excludeModelIds", []))
    else:
        raise ValueError("模式须为 t3、creator 或 custom")

    pool = {}
    for provider in providers:
        if provider["providerInstanceId"] in selected:
            for model_id in provider["matchedModelIds"]:
                if model_id in by_id and model_id not in excluded:
                    pool[model_id] = by_id[model_id]
    if mode == "custom":
        included = set(group.get("includeModelIds", []))
        creators = set(group.get("creators", []))
        for model in models:
            model_id = model["id"]
            if model_id not in excluded and (model_id in included or model["creator"] in creators):
                pool[model_id] = model
    return list(pool.values())


def mark_pareto(combos):
    # In increasing cost order only identical points may share the best score.
    best_score = -math.inf
    best_cost = None
    for combo in sorted(combos, key=lambda c: (c["totalCost"], -c["totalScore"])):
        score, cost = combo["totalScore"], combo["totalCost"]
        if score > best_score:
            best_score, best_cost = score, cost
        combo["isPareto"] = score == best_score and cost == best_cost


def rank_combos(models, *, combo_size=DEFAULTS["comboSize"], preference=DEFAULTS["preference"],
                min_intelligence=DEFAULTS["minIntelligence"], max_budget=DEFAULTS["maxBudget"],
                exclude_same_release=DEFAULTS["excludeSameRelease"]):
    if combo_size not in (2, 3):
        raise ValueError("组合模型数须为 2 或 3")
    if not 0 <= preference <= 100:
        raise ValueError("能力偏好须在 0 到 100 之间")

    candidates = [
        model for model in models
        if type(model.get("intelligenceIndex")) in (int, float)
        and model["intelligenceIndex"] >= min_intelligence
        and type(model.get("costPerTask")) in (int, float)
        and model["costPerTask"] > 0
    ]
    if combo_size == 3 and len(candidates) > 35:
        by_score = sorted(candidates, key=lambda m: -m["intelligenceIndex"])[:22]
        by_value = sorted(candidates, key=lambda m: -m["intelligenceIndex"] / math.sqrt(m["costPerTask"]))[:18]
        candidates = list({model["id"]: model for model in by_score + by_value}.values())

    budget = max_budget if max_budget is not None and max_budget > 0 else math.inf
    combos = []
    for members in combinations(candidates, combo_size):
        if exclude_same_release and len({m["releaseSlug"] for m in members}) != combo_size:
            continue
        total_cost, total_score, total_time = 0, 0, 0
        for model in members:
            total_cost += model["costPerTask"]
            total_score += model["intelligenceIndex"]
            total_time += model.get("timePerTaskSec") or 0
        if total_cost > budget:
            continue
        combos.append({
            "key": "|".join(sorted(model["id"] for model in members)),
            "models": sorted(members, key=lambda m: -m["intelligenceIndex"]),
            "totalScore": total_score,
            "totalCost": total_cost,
            "totalTimeSec": total_time,
        })
    if not combos:
        return []

    mark_pareto(combos)
    min_score = min(combo["totalScore"] for combo in combos)
    score_span = max(combo["totalScore"] for combo in combos) - min_score
    log_costs = [math.log10(max(combo["totalCost"], 0.001)) for combo in combos]
    max_log_cost = max(log_costs)
    cost_span = max_log_cost - min(log_costs)
    weight_score = preference / 100
    weight_cost = 1 - weight_score
    for combo, log_cost in zip(combos, log_costs):
        normalized_score = (combo["totalScore"] - min_score) / score_span if score_span else 1
        normalized_cost = (max_log_cost - log_cost) / cost_span if cost_span else 1
        composite = weight_score * normalized_score + weight_cost * normalized_cost
        # Scores are nonnegative; use the widget's JavaScript rounding at half ties.
        scaled = composite * 1000
        integral = math.floor(scaled)
        combo["compositeScore"] = (integral + (scaled - integral >= 0.5)) / 10

    return sorted(combos, key=lambda c: (
        -c["compositeScore"], not c["isPareto"], -c["totalScore"], c["totalCost"],
    ))
