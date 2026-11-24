import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError

from scripts import aa_fetcher, build_widget, combo_engine, config_store, t3_mapper


def aa_row(model_id, slug, release_name, suffix=None, score=44, cost=0.75, **fields):
    return {
        "id": model_id, "release": {"slug": slug, "name": release_name},
        "name": f"{release_name} ({suffix})" if suffix else release_name,
        "suffix": suffix, "intelligenceIndex": score,
        "intelligenceIndexCostPerTask": cost, "intelligenceIndexTimePerTask": 235,
        "modelCreatorName": "Google", "modelCreatorColor": "#34A853",
        "contextWindowTokens": 1000000, "isReasoning": True, "isOpenWeights": False,
        "deprecated": False, **fields,
    }


def flight_html(rows):
    record = '21:' + json.dumps(["$", "$L22", None, {"initialModels": rows}])
    split = record.index("intelligenceIndex") + 4
    return ("<script>self.__next_f.push([0])</script>"
            + "<script>self.__next_f.push([1,\"22:I[]\\n\"])</script>"
            + "".join(f"<script>self.__next_f.push({json.dumps([1, chunk])});</script>"
                      for chunk in (record[:split], record[split:] + "\n")))


def provider(provider_id, models, **fields):
    return {
        "providerInstanceId": provider_id, "displayName": provider_id.upper(),
        "canRunChildTask": True, "constraints": [], "models": models, **fields,
    }


def ranked_model(model_id, score, cost, release=None, creator="A", seconds=None):
    return {"id": model_id, "releaseSlug": release or model_id, "creator": creator,
            "intelligenceIndex": score, "costPerTask": cost, "timePerTaskSec": seconds}


class FetcherTests(unittest.TestCase):
    def test_split_flight_stream_preserves_values_and_filter_counts(self):
        rows = [
            aa_row("neon", "gemini-4-neon", 'Gemini 4 Neon "preview"', "Low", 44.08, .745),
            aa_row("deprecated", "old", "Old", deprecated=True),
            aa_row("no-score", "missing", "Missing", score=None),
            aa_row("free", "free", "Free", cost=0),
            aa_row("no-cost", "no-cost", "No cost", cost=None),
            aa_row("negative", "negative", "Negative", score=-1),
        ]
        snapshot = aa_fetcher.parse_leaderboard(flight_html(rows + [rows[0]]))
        self.assertEqual(snapshot["stats"], {
            "totalModels": 6, "validModels": 1, "deprecatedModels": 1,
            "invalidModels": 4,
        })
        self.assertEqual(snapshot["models"], [{
            "id": "neon", "releaseSlug": "gemini-4-neon",
            "releaseName": 'Gemini 4 Neon "preview"',
            "name": 'Gemini 4 Neon "preview" (Low)',
            "shortName": 'Gemini 4 Neon "preview" (Low)', "suffix": "Low",
            "creator": "Google", "creatorColor": "#34A853", "intelligenceIndex": 44.08,
            "costPerTask": .745, "timePerTaskSec": 235, "contextWindowTokens": 1000000,
            "isReasoning": True, "isOpenWeights": False, "t3Matches": [],
        }])

    def test_missing_models_detected_as_fetch_failure(self):
        with self.assertRaises(ValueError):
            aa_fetcher.parse_leaderboard("<script>self.__next_f.push([1,\"0:{}\"])</script>")

    def test_cache_hit_expiration_forced_refresh_and_stale_fallback(self):
        html = flight_html([aa_row("neon", "gemini-4-neon", "Gemini 4 Neon", "Low")])
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"T3_MODEL_COMBO_CACHE_DIR": tmp}):
            with patch.object(aa_fetcher, "download_html", return_value=html):
                fresh = aa_fetcher.fetch_models()
            with patch.object(aa_fetcher, "download_html", side_effect=URLError("offline")):
                cached = aa_fetcher.fetch_models()
                stale = aa_fetcher.fetch_models(refresh=True)
                expired = aa_fetcher.fetch_models(ttl=0)
            self.assertFalse(fresh["source"]["fromCache"])
            self.assertTrue(cached["source"]["fromCache"])
            self.assertFalse(cached["source"]["stale"])
            self.assertTrue(stale["source"]["stale"])
            self.assertTrue(expired["source"]["stale"])
            self.assertEqual(stale["source"]["fetchedAt"], fresh["source"]["fetchedAt"])
            self.assertEqual(stale["models"], fresh["models"])
            with patch.object(aa_fetcher, "download_html", return_value=flight_html([
                aa_row("next", "next", "Next"),
            ])):
                self.assertEqual(aa_fetcher.fetch_models(refresh=True)["models"][0]["id"], "next")


class MappingTests(unittest.TestCase):
    def test_alias_effort_plain_fallback_and_disabled_providers(self):
        raw = [
            aa_row("neon-high", "gemini-4-neon", "Gemini 4 Neon", "High"),
            aa_row("neon-xhigh", "gemini-4-neon", "Gemini 4 Neon", "Xhigh"),
            aa_row("hy4", "tencent-hy4", "Tencent Hy4"),
            aa_row("claude", "claude-opus-5-5", "Claude Opus 5.5", "Max, Default Fallback"),
            aa_row("future", "future-7-8-pro", "Future 7.8 Pro", "Ultra"),
        ]
        models = aa_fetcher.parse_leaderboard(flight_html(raw))["models"]
        model_entries = [
            {"id": "gemini-4-neon", "options": [{"id": "thought_level",
                                               "values": ["high", "xhigh", "low"]}]},
            {"id": "hy4std", "options": [{"id": "thought_level", "values": ["high"]}]},
            {"id": "claude-opus-5-5", "options": [{"id": "effort", "values": ["max"]}]},
            {"id": "vendor/future_7.8-pro", "options": [
                {"id": "reasoning_effort", "values": ["ultra"]},
                {"id": "fastMode", "values": [True, False]},
            ]},
            {"id": "future-7-8", "label": "Future 7.8"},
        ]
        matches, providers = t3_mapper.map_models(models, {"providers": [
            provider("off", model_entries, constraints=["Provider instance is disabled."]),
            provider("on", model_entries),
            provider("blocked", model_entries, canRunChildTask=False),
        ]})
        self.assertEqual([p["enabled"] for p in providers], [True, False, False])
        self.assertEqual(providers[0]["matchedModelIds"], ["neon-high", "neon-xhigh", "hy4",
                                                          "claude", "future"])
        self.assertEqual(providers[0]["unmatchedModels"], [{
            "modelId": "future-7-8", "label": "Future 7.8", "reason": "榜单暂无此模型数据",
        }])
        self.assertEqual(matches[0]["t3Matches"][0], {
            "providerInstanceId": "on", "providerDisplayName": "ON",
            "modelId": "gemini-4-neon", "modelLabel": "gemini-4-neon",
            "effortOptionId": "thought_level", "effortValue": "high",
        })
        self.assertEqual(matches[1]["t3Matches"][0]["effortValue"], "xhigh")
        self.assertEqual(matches[2]["t3Matches"][0]["modelId"], "hy4std")
        self.assertEqual(matches[3]["t3Matches"][0]["effortValue"], "max")
        self.assertEqual(matches[4]["t3Matches"][0]["effortValue"], "ultra")
        self.assertTrue(all(not m["t3Matches"] for m in models))

    def test_match_by_label_and_fixed_tier_id(self):
        models = aa_fetcher.parse_leaderboard(flight_html([
            aa_row("low", "my-model", "My Model", "Low"),
            aa_row("max", "my-model", "My Model", "Max"),
            aa_row("none", "plain", "Plain"),
        ]))["models"]
        matched, _ = t3_mapper.map_models(models, {"providers": [provider("on", [
            {"id": "my_model-max"},
            {"id": "opaque", "label": "Plain"},
        ])]})
        self.assertEqual([len(m["t3Matches"]) for m in matched], [0, 1, 1])
        self.assertIsNone(matched[1]["t3Matches"][0]["effortOptionId"])

    def test_versioned_alias_requires_a_known_variant_when_multiple_exist(self):
        models = aa_fetcher.parse_leaderboard(flight_html([
            aa_row("high", "deepseek-v4-1-flash-1017", "DeepSeek V4.1 Flash 1017", "High"),
            aa_row("max", "deepseek-v4-1-flash-1017", "DeepSeek V4.1 Flash 1017", "Max"),
        ]))["models"]
        matched, providers = t3_mapper.map_models(models, {"providers": [
            provider("explicit", [{"id": "deepseek-v4.1-flash", "options": [
                {"id": "effort", "values": ["high"]},
            ]}]),
            provider("unknown", [{"id": "deepseek-v4.1-flash"}]),
        ]})
        self.assertEqual(matched[0]["t3Matches"][0]["providerInstanceId"], "explicit")
        self.assertEqual(matched[1]["t3Matches"], [])
        self.assertEqual(providers[1]["matchedModelIds"], [])


class ConfigTests(unittest.TestCase):
    def test_group_and_favorite_upserts_and_defaults_persist(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "T3_MODEL_COMBO_CONFIG_PATH": str(Path(tmp) / "nested" / "config.json"),
        }):
            store = config_store.ConfigStore()
            self.assertEqual(store.load()["defaults"]["preference"], 55)
            group = store.save_group(name="主力", creators=["Google"], t3ProviderIds=["agi"])
            updated = store.save_group(group_id=group["id"], name="改名", excludeModelIds=["x"])
            self.assertEqual(updated["creators"], ["Google"])
            self.assertEqual(updated["excludeModelIds"], ["x"])
            self.assertEqual(updated["name"], "改名")
            first = store.save_favorite(model_ids=["b", "a"])
            second = store.save_favorite(model_ids=["a", "b"], name="常用")
            self.assertEqual(first["id"], second["id"])
            store.update_defaults(mode="custom", comboSize=3, maxBudget=2.5)
            readback = config_store.ConfigStore().load()
            self.assertEqual(len(readback["customGroups"]), 1)
            self.assertEqual(readback["favoriteCombos"], [second])
            self.assertEqual(readback["defaults"]["comboSize"], 3)
            self.assertEqual(readback["defaults"]["minIntelligence"], 35)
            self.assertTrue(store.delete_group(group["id"]))
            self.assertTrue(store.delete_favorite(first["id"]))
            self.assertFalse(store.delete_favorite(first["id"]))
            self.assertEqual(store.load()["customGroups"], [])
            self.assertEqual(store.load()["favoriteCombos"], [])

    def test_failed_atomic_write_keeps_previous_config(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            store = config_store.ConfigStore(path)
            store.update_defaults(preference=60)
            with patch.object(config_store.os, "replace", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    store.update_defaults(preference=80)
            self.assertEqual(store.load()["defaults"]["preference"], 60)
            self.assertEqual(list(path.parent.iterdir()), [path])


class CombinationTests(unittest.TestCase):
    def setUp(self):
        self.models = [
            ranked_model("a", 60, 9, release="a", seconds=15),
            ranked_model("alt", 58, 12, release="a", seconds=3),
            ranked_model("b", 45, 2.5, seconds=12),
            ranked_model("c", 40, 1.5),
            ranked_model("weak", 20, .1),
        ]

    def test_same_release_and_intelligence_filter(self):
        combos = combo_engine.rank_combos(self.models, min_intelligence=35)
        keys = {entry["key"] for entry in combos}
        self.assertNotIn("a|alt", keys)
        self.assertFalse(any("weak" in key for key in keys))
        self.assertIn("a|alt", {entry["key"] for entry in combo_engine.rank_combos(
            self.models, exclude_same_release=False)})

    def test_preference_budget_and_metrics(self):
        cheap = combo_engine.rank_combos(self.models, preference=0)[0]
        high_score = combo_engine.rank_combos(self.models, preference=100)[0]
        self.assertEqual(cheap["key"], "b|c")
        self.assertEqual(cheap["totalTimeSec"], 12)
        self.assertEqual(high_score["key"], "a|b")
        self.assertEqual(high_score["totalScore"], 105)
        self.assertEqual(high_score["totalTimeSec"], 27)
        self.assertEqual(high_score["compositeScore"], 100)
        self.assertEqual([c["key"] for c in combo_engine.rank_combos(
            self.models, max_budget=4)], ["b|c"])

    def test_identical_pareto_points_both_survive_and_strictly_worse_do_not(self):
        entries = combo_engine.rank_combos([
            ranked_model("a", 50, 4), ranked_model("b", 50, 4),
            ranked_model("cheap", 40, 1), ranked_model("worse", 35, 1),
        ])
        self.assertEqual({c["key"] for c in entries if c["isPareto"]},
                         {"a|b", "a|cheap", "b|cheap", "cheap|worse"})

    def test_three_model_pruning_is_fast_and_retains_efficient_models(self):
        candidates = [ranked_model(str(i), 35 + i / 100, 1 + i)
                      for i in range(600)]
        start = time.monotonic()
        entries = combo_engine.rank_combos(candidates, combo_size=3, preference=0)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(len(entries), math.comb(40, 3))
        self.assertEqual(entries[0]["key"], "0|1|2")

    def test_modes_apply_default_enabled_channels_and_custom_include_exclude(self):
        channels = [
            {"providerInstanceId": "disabled", "enabled": False, "matchedModelIds": ["a"]},
            {"providerInstanceId": "enabled", "enabled": True, "matchedModelIds": ["b"]},
        ]
        self.assertEqual([m["id"] for m in combo_engine.select_candidates(
            self.models, channels, mode="t3")], ["b"])
        self.assertEqual([m["id"] for m in combo_engine.select_candidates(
            self.models, channels[:1], mode="t3")], ["a"])
        self.assertEqual(combo_engine.select_candidates(
            self.models, channels, mode="creator", creator_names=["B"]), [])
        group = {"t3ProviderIds": ["disabled"], "includeModelIds": ["c"],
                 "excludeModelIds": ["a"]}
        self.assertEqual([m["id"] for m in combo_engine.select_candidates(
            self.models, channels, mode="custom", group=group)], ["c"])


class WidgetTests(unittest.TestCase):
    def test_html_embedding_escapes_mixed_case_script_close(self):
        payload = {"name": "<!--<script></ScRiPt><script>evil()</script>", "label": "中文"}
        template = "<script>const data = /*__PAYLOAD_JSON__*/null;</script>"
        html = build_widget.inject_payload(template, payload)
        self.assertEqual(html.lower().count("</script"), 1)
        self.assertEqual(html.lower().count("<script"), 1)
        self.assertEqual(json.loads(html.split(" = ", 1)[1].rsplit(";", 1)[0]), payload)

    def test_render_json_only_with_missing_template(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "T3_MODEL_COMBO_CONFIG_PATH": str(Path(tmp) / "config.json"),
            "T3_MODEL_COMBO_CACHE_DIR": str(Path(tmp) / "cache"),
        }):
            json_out = Path(tmp) / "result.json"
            capabilities = Path(tmp) / "capabilities.json"
            capabilities.write_text(json.dumps({"providers": [provider("on", [
                {"id": "neon"}, {"id": "hydrogen"},
            ])]}), encoding="utf-8")
            html = flight_html([aa_row("a", "neon", "Neon"), aa_row("b", "hydrogen", "Hydrogen")])
            with patch.object(build_widget, "TEMPLATE_PATH", Path(tmp) / "absent.html"), \
                 patch.object(aa_fetcher, "download_html", return_value=html):
                self.assertEqual(build_widget.main(["render", "--capabilities-file",
                    str(capabilities), "--json-out", str(json_out)]), 0)
            payload = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(set(payload), {"generatedAt", "source", "models", "t3Providers",
                                           "creators", "config", "initialTopCombos"})
            self.assertEqual(set(payload["source"]), {"url", "fetchedAt", "fromCache",
                                                    "stale", "totalModels"})
            self.assertEqual(payload["initialTopCombos"][0]["key"], "a|b")
            self.assertEqual(payload["creators"], [{"name": "Google", "color": "#34A853", "count": 2}])


if __name__ == "__main__":
    unittest.main()
