import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import ConfigError, load_config
from app.core.settings import BACKEND_ROOT

CONFIG_DIR = BACKEND_ROOT / "config"


def _shipped(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))
    return data


def _write(tmp_path: Path, files: dict[str, dict[str, Any]]) -> Path:
    for name, data in files.items():
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


def test_shipped_config_is_valid() -> None:
    config = load_config(CONFIG_DIR)
    assert config.learning.mastery.half_life_days == 21
    assert config.learning.mastery.difficulty_weights.exam == 1.7
    escalation = config.ai.routing["proof_marking"].escalate_to
    assert escalation is not None
    assert (escalation.model, escalation.effort) == ("opus", "high")


def test_budget_is_ten_pounds_a_month_with_conservative_conversion() -> None:
    budget = load_config(CONFIG_DIR).ai.budget
    assert (budget.currency, budget.monthly_cap) == ("GBP", 10.0)
    assert budget.from_usd(10.0) == 8.0


def test_every_route_resolves_to_a_model() -> None:
    ai = load_config(CONFIG_DIR).ai
    for route in ai.routing.values():
        for step in route.steps():
            assert step.model in ai.models


@pytest.mark.parametrize(
    ("file", "path", "value", "expected"),
    [
        ("learning", ["mastery", "flashcard_blend_lambda"], 1.5, "less than or equal to 1"),
        ("learning", ["mastery", "half_life_days"], 0, "greater than 0"),
        ("learning", ["mastery", "difficulty_weights", "easy"], 2.0, "must not decrease"),
        ("learning", ["difficulty", "target_success", "min"], 0.9, "must be below"),
        ("learning", ["spaced_repetition", "target_retention"], 1.0, "less than 1"),
        ("learning", ["mistakes", "categories"], ["a", "a"], "must be unique"),
        ("learning", ["mastery", "half_lfe_days"], 21, "Extra inputs are not permitted"),
        ("ai", ["routing", "tutoring", "model"], "gpt", "unknown model alias 'gpt'"),
        (
            "ai",
            ["routing", "tutoring", "escalate_to"],
            {"model": "nope"},
            "unknown model alias 'nope'",
        ),
        ("ai", ["routing", "tutoring", "effort"], None, "model 'sonnet' needs an effort"),
        ("ai", ["routing", "query_rewrite", "effort"], "low", "'haiku' does not accept an effort"),
        ("ai", ["routing", "tutoring", "effort"], "extreme", "Input should be 'low'"),
        ("ai", ["models", "sonnet", "effort_levels"], ["low"], "effort 'medium' not available"),
        (
            "ai",
            ["routing", "tutoring", "escalate_to"],
            {"model": "sonnet", "effort": "medium"},
            "escalation must differ",
        ),
        ("ai", ["budget", "daily_cap"], 50.0, "daily_cap cannot exceed monthly_cap"),
        ("ai", ["budget", "currency"], "JPY", "Input should be 'GBP'"),
        ("ai", ["budget", "usd_to_currency"], 0, "greater than 0"),
        ("ai", ["budget", "warn_fraction"], 1.0, "less than 1"),
        ("ai", ["models", "haiku", "pricing", "input"], -1.0, "greater than or equal to 0"),
        ("platform", ["auth", "session_idle_hours"], 10_000, "cannot exceed session_absolute"),
        ("platform", ["auth", "password_min_length"], 4, "greater than or equal to 8"),
        ("platform", ["rate_limits", "login", "max_attempts"], 0, "greater than 0"),
    ],
)
def test_invalid_values_are_rejected(
    tmp_path: Path, file: str, path: list[str], value: Any, expected: str
) -> None:
    data = {name: _shipped(f"{name}.yaml") for name in ("learning", "ai", "platform")}
    node = data[file]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    config_dir = _write(tmp_path, data)

    with pytest.raises(ConfigError, match=re.escape(expected)) as exc_info:
        load_config(config_dir)
    assert f"{file}.yaml" in str(exc_info.value)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    (tmp_path / "learning.yaml").write_text(
        yaml.safe_dump(_shipped("learning.yaml")), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path)


def test_malformed_yaml_is_reported(tmp_path: Path) -> None:
    (tmp_path / "learning.yaml").write_text("mastery: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(tmp_path)


def test_model_ids_live_only_in_config() -> None:
    """ARCHITECTURE.md section 8: model strings appear only in config/ai.yaml."""
    pattern = re.compile(r"claude-(haiku|sonnet|opus|fable)-")
    offenders = [
        str(p.relative_to(BACKEND_ROOT))
        for p in (BACKEND_ROOT / "app").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
