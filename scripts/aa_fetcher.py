"""Read the public Artificial Analysis model leaderboard and cache a snapshot."""

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen

if __package__:
    from .config_store import write_json
else:
    from config_store import write_json


SOURCE_URL = "https://artificialanalysis.ai/zh/leaderboards/models"
CACHE_TTL = 21600
FLIGHT_PUSH = re.compile(r"(?:^|;)\s*self\.__next_f\.push\(\s*")
FLIGHT_ROW = re.compile(r"^[\da-f]+:(?:[A-Z])?(?=[\[{\"-])")


class FlightScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inside_script = False
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.inside_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside_script = False

    def handle_data(self, contents):
        if not self.inside_script:
            return
        decoder = json.JSONDecoder()
        for push in FLIGHT_PUSH.finditer(contents):
            try:
                packet, _ = decoder.raw_decode(contents, push.end())
            except json.JSONDecodeError:
                continue
            if (isinstance(packet, list) and len(packet) >= 2 and packet[0] == 1
                    and isinstance(packet[1], str)):
                self.chunks.append(packet[1])


def is_model_row(value):
    if not isinstance(value, dict):
        return False
    release = value.get("release")
    return (
        isinstance(value.get("id"), str) and bool(value["id"])
        and isinstance(release, dict) and bool(release.get("slug"))
        and isinstance(release["slug"], str) and isinstance(value.get("name"), str)
        and ("intelligenceIndex" in value or "intelligenceIndexCostPerTask" in value)
    )


def model_lists(value, primary, other):
    if isinstance(value, dict):
        for field, child in value.items():
            if field == "initialModels" and isinstance(child, list):
                primary.extend(row for row in child if is_model_row(row))
            else:
                model_lists(child, primary, other)
    elif isinstance(value, list):
        for child in value:
            if is_model_row(child):
                other.append(child)
            else:
                model_lists(child, primary, other)


def positive_metric(value):
    return type(value) in (float, int) and math.isfinite(value) and value > 0


def parse_leaderboard(html):
    parser = FlightScripts()
    parser.feed(html)
    parser.close()
    primary, other = [], []
    # Packet boundaries can split a field, an escape, or a complete model row.
    for line in "".join(parser.chunks).split("\n"):
        row_prefix = FLIGHT_ROW.match(line)
        candidate = line[row_prefix.end():] if row_prefix else line
        if not candidate.startswith(("[", "{", '"')):
            continue
        try:
            value = json.loads(candidate)
            if isinstance(value, str) and value.startswith(("[", "{")):
                value = json.loads(value)
        except json.JSONDecodeError:
            continue
        model_lists(value, primary, other)
    rows = {}
    for row in primary or other:
        rows.setdefault(row["id"], row)
    if not rows:
        raise ValueError("榜单页面中未找到可解析的模型清单")

    models = []
    deprecated = 0
    invalid = 0
    for row in rows.values():
        if row.get("deprecated") is True:
            deprecated += 1
            continue
        score = row.get("intelligenceIndex")
        cost = row.get("intelligenceIndexCostPerTask")
        if not positive_metric(score) or not positive_metric(cost):
            invalid += 1
            continue
        duration = row.get("intelligenceIndexTimePerTask")
        context = row.get("contextWindowTokens")
        models.append({
            "id": row["id"],
            "releaseSlug": row["release"]["slug"],
            "releaseName": row["release"].get("name") or row["name"],
            "name": row["name"],
            "shortName": row.get("shortName") or row["name"],
            "suffix": row.get("suffix") or None,
            "creator": row.get("modelCreatorName") or "未知原厂",
            "creatorColor": row.get("modelCreatorColor") or "#71717a",
            "intelligenceIndex": score,
            "costPerTask": cost,
            "timePerTaskSec": duration if positive_metric(duration) else None,
            "contextWindowTokens": context if positive_metric(context) else None,
            "isReasoning": row.get("isReasoning") is True,
            "isOpenWeights": row.get("isOpenWeights") is True,
            "t3Matches": [],
        })
    return {"models": models, "stats": {
        "totalModels": len(rows),
        "validModels": len(models),
        "deprecatedModels": deprecated,
        "invalidModels": invalid,
    }}


def utc_now():
    return datetime.now(timezone.utc)


def cache_path():
    override = os.environ.get("T3_MODEL_COMBO_CACHE_DIR")
    directory = Path(override).expanduser() if override else Path.home() / ".cache/t3-model-combo"
    return directory / "aa_models.json"


def read_cache(path):
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        source = cached["source"]
        fetched_at = datetime.fromisoformat(source["fetchedAt"].replace("Z", "+00:00"))
        if (fetched_at.tzinfo is not None and isinstance(cached["models"], list)
                and isinstance(cached["stats"], dict) and source["url"] == SOURCE_URL):
            return cached, fetched_at
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None, None


def download_html():
    request = Request(SOURCE_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; t3-model-combo/1.0)",
        "Accept": "text/html",
    })
    with urlopen(request, timeout=20) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8")


def fetch_models(*, refresh=False, ttl=CACHE_TTL):
    path = cache_path()
    cached, fetched_at = read_cache(path)
    if cached is not None and not refresh and 0 <= (utc_now() - fetched_at).total_seconds() < ttl:
        cached["source"].update(fromCache=True, stale=False)
        return cached
    try:
        snapshot = parse_leaderboard(download_html())
    except (OSError, ValueError) as error:
        if cached is None:
            raise RuntimeError(f"无法读取 Artificial Analysis 榜单：{error}") from error
        cached["source"].update(fromCache=True, stale=True)
        return cached
    snapshot["source"] = {
        "url": SOURCE_URL,
        "fetchedAt": utc_now().isoformat(),
        "fromCache": False,
        "stale": False,
        "totalModels": snapshot["stats"]["totalModels"],
    }
    write_json(path, snapshot)
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="读取 Artificial Analysis 模型榜单")
    parser.add_argument("--refresh", action="store_true", help="强制重新抓取")
    args = parser.parse_args(argv)
    try:
        snapshot = fetch_models(refresh=args.refresh)
    except (RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
