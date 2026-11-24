"""Render the standalone model-combination widget and manage its configuration."""

import argparse
import json
from pathlib import Path
import re
import sys

if __package__:
    from . import aa_fetcher, combo_engine, config_store, t3_mapper
else:
    import aa_fetcher
    import combo_engine
    import config_store
    import t3_mapper


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "ui" / "widget.html"
PAYLOAD_PLACEHOLDER = "/*__PAYLOAD_JSON__*/null"
SCRIPT_MARKUP = re.compile(r"</script|<", re.IGNORECASE)


def inject_payload(template, payload):
    if template.count(PAYLOAD_PLACEHOLDER) != 1:
        raise ValueError("界面模板须包含且仅包含一个数据占位符")
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    encoded = SCRIPT_MARKUP.sub(
        lambda match: r"<\/" + match[0][2:] if len(match[0]) > 1 else r"\u003c",
        encoded,
    ).replace("\u2028", r"\u2028").replace("\u2029", r"\u2029")
    return template.replace(PAYLOAD_PLACEHOLDER, encoded, 1)


def summarize_creators(models):
    creators = {}
    best_scores = {}
    for model in models:
        name = model["creator"]
        entry = creators.setdefault(name, {"name": name, "color": model["creatorColor"], "count": 0})
        entry["count"] += 1
        best_scores[name] = max(best_scores.get(name, 0), model["intelligenceIndex"])
    return sorted(creators.values(), key=lambda c: (-best_scores[c["name"]], c["name"]))


def build_payload(snapshot, capabilities, config):
    models, providers = t3_mapper.map_models(snapshot["models"], capabilities)
    creators = summarize_creators(models)
    defaults = config["defaults"]
    mode = defaults["mode"]
    if mode == "t3" and not combo_engine.default_provider_ids(providers):
        mode = "creator"
    groups = config["customGroups"]
    candidates = combo_engine.select_candidates(
        models, providers, mode=mode, creator_names=[c["name"] for c in creators[:6]],
        group=groups[0] if groups else None,
    )
    combos = combo_engine.rank_combos(
        candidates, combo_size=defaults["comboSize"], preference=defaults["preference"],
        min_intelligence=defaults["minIntelligence"], max_budget=defaults["maxBudget"],
        exclude_same_release=defaults["excludeSameRelease"],
    )
    return {
        "generatedAt": aa_fetcher.utc_now().isoformat(),
        "source": snapshot["source"],
        "models": models,
        "t3Providers": providers,
        "creators": creators,
        "config": config,
        "initialTopCombos": combos[:10],
    }


def render(args, store):
    template = None
    if args.output is not None or args.json_out is None:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if args.output and args.json_out and args.output.resolve() == args.json_out.resolve():
        raise ValueError("HTML 与 JSON 输出须使用不同路径")
    output = args.output or Path("t3-model-combo.html")
    for destination in (output if template is not None else None, args.json_out):
        if destination is not None and destination.resolve() == TEMPLATE_PATH.resolve():
            raise ValueError("输出路径须与界面模板路径不同")

    config = store.load()
    config["defaults"].update(default_changes(args))
    config_store.validate_defaults(config["defaults"])
    capabilities = t3_mapper.load_capabilities(args.capabilities_file)
    payload = build_payload(aa_fetcher.fetch_models(refresh=args.refresh), capabilities, config)
    if template is not None:
        html = inject_payload(template, payload)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
    if args.json_out is not None:
        config_store.write_json(args.json_out, payload)


def parse_budget(value):
    return None if value.casefold() in ("none", "null") else float(value)


def add_default_flags(parser):
    flags = {"default": argparse.SUPPRESS}
    parser.add_argument("--mode", choices=("t3", "creator", "custom"), **flags)
    parser.add_argument("--combo-size", dest="comboSize", choices=(2, 3), type=int, **flags)
    parser.add_argument("--preference", type=float, **flags)
    parser.add_argument("--min-intelligence", dest="minIntelligence", type=float, **flags)
    parser.add_argument("--max-budget", dest="maxBudget", type=parse_budget, **flags)
    parser.add_argument("--exclude-same-release", dest="excludeSameRelease",
                        action=argparse.BooleanOptionalAction, **flags)


def default_changes(args):
    return {key: getattr(args, key) for key in config_store.DEFAULTS if hasattr(args, key)}


def flatten_list(values):
    return [item for value in values for item in value.split(",")]


def make_parser():
    parser = argparse.ArgumentParser(description="生成模型性价比组合榜单")
    commands = parser.add_subparsers(dest="command", required=True)
    render_parser = commands.add_parser("render", help="生成榜单 HTML 或 JSON")
    render_parser.add_argument("--capabilities-file", type=Path)
    render_parser.add_argument("--refresh", action="store_true")
    render_parser.add_argument("--output", type=Path, help="HTML 输出路径，默认 t3-model-combo.html")
    render_parser.add_argument("--json-out", type=Path, help="JSON 输出路径，单独使用时仅写 JSON")
    add_default_flags(render_parser)

    group_save = commands.add_parser("group-save", help="新增或更新分组")
    group_save.add_argument("--id", "--group-id", dest="group_id")
    group_save.add_argument("--name")
    for field, flags in {
        "t3ProviderIds": ("--t3-provider-ids", "--provider-ids"),
        "creators": ("--creators",),
        "includeModelIds": ("--include-model-ids",),
        "excludeModelIds": ("--exclude-model-ids",),
    }.items():
        group_save.add_argument(*flags, dest=field, nargs="*", action="extend")

    favorite_save = commands.add_parser("favorite-save", help="保存黄金组合")
    favorite_save.add_argument("--id", "--favorite-id", dest="favorite_id")
    favorite_save.add_argument("--name")
    favorite_save.add_argument("--model-ids", nargs="+", action="extend", required=True)

    for entry in ("group", "favorite"):
        delete = commands.add_parser(f"{entry}-delete", help="按 ID 删除")
        identifier = delete.add_mutually_exclusive_group(required=True)
        identifier.add_argument("entry_id", nargs="?")
        identifier.add_argument("--id", f"--{entry}-id", dest="named_id")
        commands.add_parser(f"{entry}-list", help="查看已保存项目")
    add_default_flags(commands.add_parser("defaults-set", help="更新默认参数"))
    return parser


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    store = config_store.ConfigStore()
    try:
        if args.command == "render":
            render(args, store)
            return 0
        if args.command == "group-save":
            filters = {field: flatten_list(getattr(args, field))
                       for field in config_store.GROUP_LIST_FIELDS if getattr(args, field) is not None}
            result = store.save_group(group_id=args.group_id, name=args.name, **filters)
        elif args.command == "favorite-save":
            result = store.save_favorite(model_ids=flatten_list(args.model_ids),
                                         name=args.name, favorite_id=args.favorite_id)
        elif args.command == "defaults-set":
            result = store.update_defaults(**default_changes(args))
        elif args.command == "group-delete":
            result = {"deleted": store.delete_group(args.named_id or args.entry_id)}
        elif args.command == "favorite-delete":
            result = {"deleted": store.delete_favorite(args.named_id or args.entry_id)}
        elif args.command == "group-list":
            result = store.load()["customGroups"]
        else:
            result = store.load()["favoriteCombos"]
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(f"操作失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
