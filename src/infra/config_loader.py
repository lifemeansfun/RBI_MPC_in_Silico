"""
Configuration loader for RBI MPC In Silico.
Reads config/config.yaml and merges with environment variables.
"""

import os
from pathlib import Path
from typing import Literal, Optional
import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Automatically load .env if present
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class RunConfig(BaseModel):
    provider: Literal["gemini", "openai", "anthropic", "ollama", "mock"] = "gemini"
    dev_model: str = "gemini-3.8-flash"
    final_model: str = "gemini-3.8-flash"
    fallback_models: list[str] = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
    rate_limit_rpm: int = 5
    budget_usd_cap: float = 25.0
    temperature: float = 0.6
    n_replicates: int = 3
    seed_base: int = 42
    use_cache: bool = True
    cache_dir: str = ".cache/llm_cache.sqlite"


class DecisionSpaceConfig(BaseModel):
    action_set_bps: list[int] = [-50, -25, 0, 25, 50]
    simulate_stance: bool = True
    stance_set: list[str] = ["withdrawal_of_accommodation", "neutral", "accommodative"]


class PanelsConfig(BaseModel):
    primary_roster: str = "2020_2024"
    primary_panel_start: str = "2020-10-01"
    primary_panel_end: str = "2024-08-31"
    calibration_holdout_split: float = 0.67
    forward_test_panel_start: str = "2024-10-01"
    forward_test_panel_end: str = "latest"


class TaylorRuleConfig(BaseModel):
    r_star_pct: float = 1.4
    pi_star_pct: float = 4.0
    hp_filter_lambda: float = 14400.0
    smoothing_rho: float = 0.75
    default_alpha: float = 1.5
    default_beta: float = 0.5
    default_gamma: float = 0.2
    us_neutral_rate_pct: float = 2.5


class MonteCarloConfig(BaseModel):
    n_draws: int = 1000
    macro_noise_std_pct: float = 0.20


class ValidationConfig(BaseModel):
    directional_accuracy_threshold: float = 0.75
    stance_accuracy_threshold: float = 0.70
    dissent_f1_threshold: float = 0.50


class DebateProtocolConfig(BaseModel):
    rounds: int = 4
    order_mode: str = "fixed_governor_last"
    cross_visibility: bool = True


class AppConfig(BaseModel):
    project_name: str = "RBI_MPC_In_Silico"
    version: str = "2.0.0"
    run: RunConfig = Field(default_factory=RunConfig)
    decision_space: DecisionSpaceConfig = Field(default_factory=DecisionSpaceConfig)
    panels: PanelsConfig = Field(default_factory=PanelsConfig)
    taylor_rule: TaylorRuleConfig = Field(default_factory=TaylorRuleConfig)
    monte_carlo: MonteCarloConfig = Field(default_factory=MonteCarloConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    debate_protocol: DebateProtocolConfig = Field(default_factory=DebateProtocolConfig)

    # API keys loaded from environment
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    fred_api_key: Optional[str] = None


_CONFIG_CACHE: Optional[AppConfig] = None


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    """Loads configuration from YAML file and merges environment variables."""
    global _CONFIG_CACHE
    if config_path is None:
        config_path = PROJECT_ROOT / "config" / "config.yaml"
    else:
        config_path = Path(config_path)

    data = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw_yaml = yaml.safe_load(f) or {}
            data = {
                "project_name": raw_yaml.get("project", {}).get("name", "RBI_MPC_In_Silico"),
                "version": raw_yaml.get("project", {}).get("version", "2.0.0"),
                "run": raw_yaml.get("run", {}),
                "decision_space": raw_yaml.get("decision_space", {}),
                "panels": raw_yaml.get("panels", {}),
                "taylor_rule": raw_yaml.get("taylor_rule", {}),
                "monte_carlo": raw_yaml.get("monte_carlo", {}),
                "validation": raw_yaml.get("validation", {}),
                "debate_protocol": raw_yaml.get("debate_protocol", {}),
            }

    # Inject environment keys
    data["gemini_api_key"] = os.getenv("GEMINI_API_KEY")
    data["openai_api_key"] = os.getenv("OPENAI_API_KEY")
    data["anthropic_api_key"] = os.getenv("ANTHROPIC_API_KEY")
    data["fred_api_key"] = os.getenv("FRED_API_KEY")

    cfg = AppConfig(**data)
    _CONFIG_CACHE = cfg
    return cfg


def get_config() -> AppConfig:
    """Returns the cached configuration or loads it."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        return load_config()
    return _CONFIG_CACHE
