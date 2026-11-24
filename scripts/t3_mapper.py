"""Join model benchmarks to available T3 provider models and effort values."""

from collections import defaultdict
import json
from pathlib import Path
import re
import unicodedata


ALIASES_PATH = Path(__file__).with_name("model_aliases.json")
EFFORT_OPTIONS = {"thoughtlevel", "reasoningeffort", "effort"}
EFFORT_LEVELS = {
    "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh",
    "extrahigh": "xhigh", "veryhigh": "xhigh", "max": "max",
    "maximum": "max", "ultra": "ultra", "ultrathink": "ultra",
    "minimal": "minimal", "nonreasoning": "nonreasoning", "none": "nonreasoning",
    "reasoning": "reasoning", "enabled": "reasoning",
}
FIXED_TIER = re.compile(
    r"[\s_\-(:]+(extra[\s_-]*high|non[\s_-]*reasoning|ultrathink|"
    r"minimal|medium|xhigh|ultra|reasoning|high|low|max|none)\)?$",
    re.IGNORECASE,
)


def normalize(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(char for char in value if char.isalnum())


def identity_keys(value):
    # Provider-qualified model IDs commonly use the namespace/model form.
    return tuple(dict.fromkeys(filter(None, (normalize(value), normalize(value.rsplit("/", 1)[-1])))))


def load_capabilities(path):
    if path is None:
        return {"providers": []}
    capabilities = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(capabilities, dict) and "structuredContent" in capabilities:
        capabilities = capabilities["structuredContent"]
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("providers"), list):
        raise ValueError("T3 渠道文件须包含 providers 数组")
    return capabilities


def effort_choices(model):
    for option in model.get("options") or []:
        option_id = option.get("id") or ""
        if normalize(option_id) not in EFFORT_OPTIONS:
            continue
        values = [value for value in option.get("values", [])
                  if isinstance(value, str) and normalize(value) in EFFORT_LEVELS]
        default = option.get("default")
        if default in values:
            values.remove(default)
            values.insert(0, default)
        for value in dict.fromkeys(values):
            yield option_id, value, EFFORT_LEVELS[normalize(value)]


def model_tier(row):
    suffix = row.get("suffix")
    if suffix:
        tier = normalize(re.split(r"[,;/]", suffix, maxsplit=1)[0])
        return EFFORT_LEVELS.get(tier, tier)
    for display_name in (row["name"], row.get("shortName") or ""):
        if normalize(display_name) == normalize(row["releaseName"]):
            continue
        tier = FIXED_TIER.search(display_name)
        if tier:
            return EFFORT_LEVELS[normalize(tier[1])]
    return None


def resolve_rows(model, release_index, variant_index, aliases):
    model_id = model["id"]
    label = model.get("label") or model_id
    for value in (model_id, label):
        keys = identity_keys(value)
        for key in keys:
            if key in release_index:
                return release_index[key], None
        for key in keys:
            if key in aliases:
                for alias in aliases[key]:
                    for alias_key in identity_keys(alias):
                        if alias_key in release_index:
                            return release_index[alias_key], None
        for key in keys:
            if key in variant_index:
                row = variant_index[key][0]
                return release_index[normalize(row["releaseSlug"])], model_tier(row)
        tier = FIXED_TIER.search(value)
        if tier:
            for key in identity_keys(value[:tier.start()]):
                if key in release_index:
                    return release_index[key], EFFORT_LEVELS[normalize(tier[1])]
    return (), None


def match_variants(model, rows, fixed_tier):
    if not rows:
        return
    by_tier = defaultdict(list)
    for row in rows:
        by_tier[model_tier(row)].append(row)
    choices = list(effort_choices(model))
    if choices:
        for option_id, value, tier in choices:
            for row in by_tier.get(tier) or by_tier.get(None, ()):
                yield row, option_id, value
    else:
        variants = by_tier.get(fixed_tier) or by_tier.get(None)
        # Without a documented effort setting, a single row is unambiguous.
        if not variants and fixed_tier is None and len(rows) == 1:
            variants = rows
        for row in variants or ():
            yield row, None, None


def map_models(models, capabilities):
    aliases = {normalize(key): values for key, values in
               json.loads(ALIASES_PATH.read_text(encoding="utf-8")).items()}
    models = [dict(model, t3Matches=[]) for model in models]
    release_index = defaultdict(list)
    variant_index = defaultdict(list)
    for model in models:
        for key in {normalize(model["releaseSlug"]), normalize(model["releaseName"])} - {""}:
            release_index[key].append(model)
        for key in {normalize(model["name"]), normalize(model["shortName"])} - {""}:
            variant_index[key].append(model)

    def is_enabled(provider):
        return (provider.get("canRunChildTask") is not False and provider.get("enabled") is not False
                and not any(re.search(r"\bdisabled\b", str(constraint), re.IGNORECASE)
                            for constraint in provider.get("constraints") or []))

    providers = []
    for provider in sorted(capabilities.get("providers", []), key=is_enabled, reverse=True):
        provider_id = provider["providerInstanceId"]
        display_name = provider.get("displayName") or provider_id
        matched_ids = {}
        unmatched = []
        for model in provider.get("models") or []:
            model_id = model["id"]
            label = model.get("label") or model_id
            rows, fixed_tier = resolve_rows(model, release_index, variant_index, aliases)
            matches = list(match_variants(model, rows, fixed_tier))
            if not matches:
                unmatched.append({"modelId": model_id, "label": label, "reason": "榜单暂无此模型数据"})
            for row, option_id, value in matches:
                matched_ids[row["id"]] = None
                match = {
                    "providerInstanceId": provider_id,
                    "providerDisplayName": display_name,
                    "modelId": model_id,
                    "modelLabel": label,
                    "effortOptionId": option_id,
                    "effortValue": value,
                }
                if match not in row["t3Matches"]:
                    row["t3Matches"].append(match)
        providers.append({
            "providerInstanceId": provider_id,
            "displayName": display_name,
            "enabled": is_enabled(provider),
            "matchedModelIds": list(matched_ids),
            "unmatchedModels": unmatched,
        })
    return models, providers
