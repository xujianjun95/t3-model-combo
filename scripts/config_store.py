"""Persistent local widget preferences."""

import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


DEFAULTS = {
    "mode": "t3",
    "comboSize": 2,
    "preference": 55,
    "minIntelligence": 35,
    "maxBudget": None,
    "excludeSameRelease": True,
}
GROUP_LIST_FIELDS = ("t3ProviderIds", "creators", "includeModelIds", "excludeModelIds")


def config_path():
    override = os.environ.get("T3_MODEL_COMBO_CONFIG_PATH")
    return Path(override).expanduser() if override else Path.home() / ".config/t3-model-combo/config.json"


def write_json(path, value):
    """Replace the file only after its complete contents have been flushed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=f".{path.name}.", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, ensure_ascii=False, indent=2, allow_nan=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_defaults(defaults):
    if defaults["mode"] not in ("t3", "creator", "custom"):
        raise ValueError("模式须为 t3、creator 或 custom")
    if type(defaults["comboSize"]) is not int or defaults["comboSize"] not in (2, 3):
        raise ValueError("组合模型数须为 2 或 3")
    for field in ("preference", "minIntelligence", "maxBudget"):
        value = defaults[field]
        if field == "maxBudget" and value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{field} 须为有限数字")
        if field != "maxBudget" and not 0 <= value <= 100:
            raise ValueError(f"{field} 须在 0 到 100 之间")
    if type(defaults["excludeSameRelease"]) is not bool:
        raise ValueError("excludeSameRelease 须为布尔值")


def clean_strings(values):
    if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) for v in values):
        raise ValueError("列表中的项目须为字符串")
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class ConfigStore:
    def __init__(self, path=None):
        self.path = config_path() if path is None else Path(path).expanduser()

    def load(self):
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            stored = {}
        if not isinstance(stored, dict):
            raise ValueError("配置须为 JSON 对象")
        defaults = stored.get("defaults", {})
        if not isinstance(defaults, dict):
            raise ValueError("defaults 须为 JSON 对象")
        config = {
            "customGroups": stored.get("customGroups", []),
            "favoriteCombos": stored.get("favoriteCombos", []),
            "defaults": {key: defaults.get(key, value) for key, value in DEFAULTS.items()},
        }
        for field in ("customGroups", "favoriteCombos"):
            entries = config[field]
            if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
                raise ValueError(f"{field} 须为 JSON 对象数组")
        validate_defaults(config["defaults"])
        return config

    def save(self, config):
        validate_defaults(config["defaults"])
        write_json(self.path, config)

    def update_defaults(self, **changes):
        unknown = changes.keys() - DEFAULTS.keys()
        if unknown:
            raise ValueError(f"未知默认参数 {', '.join(sorted(unknown))}")
        config = self.load()
        config["defaults"].update(changes)
        self.save(config)
        return config["defaults"]

    def save_group(self, *, group_id=None, name=None, **filters):
        if filters.keys() - set(GROUP_LIST_FIELDS):
            raise ValueError("自定义分组包含未知筛选项")
        config = self.load()
        groups = config["customGroups"]
        name = name.strip() if isinstance(name, str) else None
        identity = ("id", group_id) if group_id else ("name", name)
        existing = next((group for group in groups if group.get(identity[0]) == identity[1]), None)
        group = dict(existing) if existing is not None else {
            "id": group_id or uuid4().hex, **{field: [] for field in GROUP_LIST_FIELDS},
        }
        if name is not None:
            group["name"] = name
        if not group.get("name"):
            raise ValueError("请输入分组名称")
        for field, values in filters.items():
            group[field] = clean_strings(values)
        self._save_entry(config, "customGroups", group, existing)
        return group

    def save_favorite(self, *, model_ids, name=None, favorite_id=None):
        model_ids = clean_strings(model_ids)
        if len(model_ids) not in (2, 3):
            raise ValueError("收藏须包含 2 或 3 个不同的模型 ID")
        config = self.load()
        favorites = config["favoriteCombos"]
        existing = next((entry for entry in favorites if entry.get("id") == favorite_id), None)
        duplicate = next((entry for entry in favorites
                          if set(entry.get("modelIds", [])) == set(model_ids)), None)
        if existing is not None and duplicate is not None and existing is not duplicate:
            raise ValueError("这组模型已经收藏")
        existing = existing if existing is not None else duplicate
        favorite = dict(existing or {"id": favorite_id or uuid4().hex})
        favorite["modelIds"] = model_ids
        if name is not None:
            favorite["name"] = name.strip()
        self._save_entry(config, "favoriteCombos", favorite, existing)
        return favorite

    def delete_group(self, group_id):
        return self._delete_entry("customGroups", group_id)

    def delete_favorite(self, favorite_id):
        return self._delete_entry("favoriteCombos", favorite_id)

    def _save_entry(self, config, field, entry, existing):
        entries = config[field]
        if existing is None:
            entries.append(entry)
        else:
            entries[entries.index(existing)] = entry
        self.save(config)

    def _delete_entry(self, field, entry_id):
        config = self.load()
        entries = config[field]
        config[field] = [entry for entry in entries if entry.get("id") != entry_id]
        if len(entries) == len(config[field]):
            return False
        self.save(config)
        return True
