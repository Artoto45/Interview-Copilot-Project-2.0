"""
Saldo Manager and Fuel Gauge
============================
Tracks per-provider credit balances and estimates remaining runtime
("fuel") in minutes based on observed and baseline burn rates.
"""

from __future__ import annotations

import logging
import math
import os
import time
import json
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger("saldo")

PROVIDERS = ("openai", "deepgram", "anthropic")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid float for {name}='{raw}', using default={default}"
        )
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "on"}


def _round6(value: float) -> float:
    return round(float(value), 6)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_rfc3339(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_unix_seconds(dt: datetime) -> int:
    return int(dt.timestamp())


def format_minutes_for_display(minutes: Optional[float]) -> str:
    """Human-friendly formatter for fuel estimates."""
    if minutes is None or math.isinf(minutes):
        return "unbounded"
    if minutes < 0:
        return "0 min"
    if minutes < 60:
        return f"{minutes:.0f} min"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.1f} h"
    days = hours / 24.0
    return f"{days:.1f} d"


@dataclass
class FuelSettings:
    """
    Baseline assumptions for the current system profile.

    These are used when there is not enough observed spend data yet.
    """

    # Interview dynamics assumptions
    candidate_speaking_ratio: float = 0.40
    interviewer_speaking_ratio: float = 0.35
    questions_per_minute: float = 0.35

    # Typical token shape per response
    avg_generation_input_tokens: int = 1800
    avg_generation_output_tokens: int = 280
    avg_embedding_tokens_per_question: int = 70

    # API rates (USD)
    openai_realtime_per_audio_minute: float = _env_float(
        "COST_OPENAI_REALTIME_AUDIO_PER_MINUTE",
        0.020,
    )
    deepgram_realtime_per_audio_minute: float = _env_float(
        "COST_DEEPGRAM_REALTIME_AUDIO_PER_MINUTE",
        0.0043,
    )
    openai_input_per_1m: float = _env_float(
        "COST_OPENAI_GPT4O_MINI_INPUT_PER_1M",
        0.15,
    )
    openai_output_per_1m: float = _env_float(
        "COST_OPENAI_GPT4O_MINI_OUTPUT_PER_1M",
        0.60,
    )
    openai_embedding_per_1m: float = _env_float(
        "COST_OPENAI_EMBEDDING_INPUT_PER_1M",
        0.020,
    )
    anthropic_input_per_1m: float = _env_float(
        "COST_CLAUDE_INPUT_PER_1M",
        3.0,
    )
    anthropic_output_per_1m: float = _env_float(
        "COST_CLAUDE_OUTPUT_PER_1M",
        15.0,
    )

    # Whether Anthropic/OpenAI generation is active in the runtime.
    # The current default pipeline uses OpenAI generation.
    openai_generation_active: bool = _env_bool(
        "SALDO_OPENAI_GENERATION_ACTIVE",
        True,
    )
    anthropic_generation_active: bool = _env_bool(
        "SALDO_ANTHROPIC_GENERATION_ACTIVE",
        True,
    )

    def baseline_burn_rates(self) -> dict[str, float]:
        """
        Compute USD/minute baseline burn for each provider.
        """
        # OpenAI transcription + optional generation + embeddings
        openai_audio = (
            self.candidate_speaking_ratio
            * self.openai_realtime_per_audio_minute
        )

        openai_gen_per_question = (
            (self.avg_generation_input_tokens / 1_000_000.0)
            * self.openai_input_per_1m
            + (self.avg_generation_output_tokens / 1_000_000.0)
            * self.openai_output_per_1m
        )
        openai_embed_per_question = (
            (self.avg_embedding_tokens_per_question / 1_000_000.0)
            * self.openai_embedding_per_1m
        )
        openai_qpm_component = (
            self.questions_per_minute
            * (
                (openai_gen_per_question if self.openai_generation_active else 0.0)
                + openai_embed_per_question
            )
        )
        openai_total = openai_audio + openai_qpm_component

        # Deepgram interviewer transcription
        deepgram_total = (
            self.interviewer_speaking_ratio
            * self.deepgram_realtime_per_audio_minute
        )

        # Anthropic generation (only if active/desired)
        anthropic_gen_per_question = (
            (self.avg_generation_input_tokens / 1_000_000.0)
            * self.anthropic_input_per_1m
            + (self.avg_generation_output_tokens / 1_000_000.0)
            * self.anthropic_output_per_1m
        )
        anthropic_total = (
            self.questions_per_minute * anthropic_gen_per_question
            if self.anthropic_generation_active
            else 0.0
        )

        return {
            "openai": openai_total,
            "deepgram": deepgram_total,
            "anthropic": anthropic_total,
        }


class SaldoManager:
    """
    Tracks real-time credit balance per provider and fuel estimates.
    """

    def __init__(
        self,
        starting_balances: Optional[dict[str, float]] = None,
        baseline_burn_rates: Optional[dict[str, float]] = None,
        settings: Optional[FuelSettings] = None,
    ):
        self.settings = settings or FuelSettings()
        self.starting_balances = starting_balances or {
            "openai": _env_float("SALDO_OPENAI_USD", 9.92),
            "deepgram": _env_float("SALDO_DEEPGRAM_USD", 188.69),
            "anthropic": _env_float("SALDO_ANTHROPIC_USD", 4.74),
        }

        self.baseline_burn_rates = (
            baseline_burn_rates or self.settings.baseline_burn_rates()
        )
        self.session_spend_by_provider = {
            provider: 0.0 for provider in PROVIDERS
        }
        self.live_balance_overrides: dict[str, float] = {}
        self.live_spend_since_baseline: dict[str, float] = {}

        self.live_refresh_enabled = _env_bool(
            "SALDO_ENABLE_LIVE_REFRESH",
            False,
        )
        self.live_refresh_interval_s = _env_float(
            "SALDO_REFRESH_INTERVAL_S",
            120.0,
        )
        self._last_refresh_monotonic = 0.0

        self._deepgram_project_id = os.getenv("DEEPGRAM_PROJECT_ID", "").strip()
        self._deepgram_api_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
        self._openai_admin_key = os.getenv("OPENAI_ADMIN_KEY", "").strip()
        self._anthropic_admin_key = os.getenv("ANTHROPIC_ADMIN_KEY", "").strip()
        self._openai_live_enabled = _env_bool("SALDO_LIVE_OPENAI_ENABLED", True)
        self._anthropic_live_enabled = _env_bool("SALDO_LIVE_ANTHROPIC_ENABLED", True)

        baseline_raw = os.getenv("SALDO_BASELINE_START_UTC", "").strip()
        self._baseline_start_utc = _parse_rfc3339(baseline_raw) or _utc_now()

    @staticmethod
    def provider_from_api_name(api_name: str) -> Optional[str]:
        """
        Resolve internal api_name values to provider group.
        """
        key = (api_name or "").strip().lower()
        if not key:
            return None
        if "deepgram" in key:
            return "deepgram"
        if "claude" in key or "anthropic" in key:
            return "anthropic"
        if "openai" in key or "gpt" in key:
            return "openai"
        return None

    def record_cost(self, api_name: str, cost_usd: float):
        provider = self.provider_from_api_name(api_name)
        if provider is None:
            return
        if cost_usd <= 0:
            return
        self.session_spend_by_provider[provider] += float(cost_usd)

    def update_starting_balance(self, provider: str, amount_usd: float):
        provider = provider.strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'")
        self.starting_balances[provider] = float(amount_usd)

    def set_live_balance_override(self, provider: str, amount_usd: float):
        provider = provider.strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'")
        self.live_balance_overrides[provider] = float(amount_usd)

    def maybe_refresh_live_balances(self):
        if not self.live_refresh_enabled:
            return
        now = time.monotonic()
        if (
            self._last_refresh_monotonic > 0
            and now - self._last_refresh_monotonic < self.live_refresh_interval_s
        ):
            return
        self._last_refresh_monotonic = now
        self.refresh_deepgram_balance()
        self.refresh_openai_balance()
        self.refresh_anthropic_balance()

    def refresh_deepgram_balance(self) -> Optional[float]:
        """
        Refresh Deepgram remaining balance using official Project Balances endpoint.
        Returns the balance in USD when available.
        """
        if not self._deepgram_project_id or not self._deepgram_api_key:
            return None

        url = (
            "https://api.deepgram.com/v1/projects/"
            f"{self._deepgram_project_id}/balances"
        )
        headers = {"Authorization": f"Token {self._deepgram_api_key}"}
        try:
            payload = self._request_json(url, headers)
            balances = payload.get("balances", [])
            usd_total = 0.0
            for item in balances:
                if not isinstance(item, dict):
                    continue
                units = str(item.get("units", "USD")).upper()
                if units != "USD":
                    continue
                amount = float(item.get("amount", 0.0))
                usd_total += amount
            if usd_total > 0:
                self.live_balance_overrides["deepgram"] = usd_total
                return usd_total
        except Exception as e:
            logger.warning(f"Deepgram live balance refresh failed: {e}")
        return None

    def refresh_openai_balance(self) -> Optional[float]:
        """
        Refresh OpenAI remaining balance using official organization costs API.

        Endpoint:
        - GET https://api.openai.com/v1/organization/costs
        - Requires OPENAI_ADMIN_KEY (Admin API key)
        """
        if not self._openai_live_enabled:
            return None
        if not self._openai_admin_key:
            return None

        try:
            now_utc = _utc_now()
            start_unix = _to_unix_seconds(self._baseline_start_utc)
            end_unix = _to_unix_seconds(now_utc)
            if end_unix <= start_unix:
                return None

            spent = self._fetch_openai_cost_usd(
                start_time_unix=start_unix,
                end_time_unix=end_unix,
            )
            remaining = max(
                0.0,
                float(self.starting_balances.get("openai", 0.0)) - float(spent),
            )
            self.live_spend_since_baseline["openai"] = float(spent)
            self.live_balance_overrides["openai"] = remaining
            return remaining
        except Exception as e:
            logger.warning(f"OpenAI live balance refresh failed: {e}")
            return None

    def _fetch_openai_cost_usd(
        self,
        start_time_unix: int,
        end_time_unix: int,
    ) -> float:
        base_url = "https://api.openai.com/v1/organization/costs"
        headers = {"Authorization": f"Bearer {self._openai_admin_key}"}

        total = 0.0
        page = None
        for _ in range(12):
            params = {
                "start_time": start_time_unix,
                "end_time": end_time_unix,
                "bucket_width": "1d",
                "limit": 31,
            }
            if page:
                params["page"] = page
            url = f"{base_url}?{urllib.parse.urlencode(params)}"
            payload = self._request_json(url, headers)

            for bucket in payload.get("data", []):
                if not isinstance(bucket, dict):
                    continue
                results = bucket.get("results", [])
                if not isinstance(results, list):
                    continue
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    amount = result.get("amount")
                    if isinstance(amount, dict):
                        value = amount.get("value", 0.0)
                    else:
                        value = amount or result.get("cost", 0.0)
                    try:
                        total += float(value)
                    except (TypeError, ValueError):
                        continue

            if not payload.get("has_more", False):
                break
            page = payload.get("next_page")
            if not page:
                break
        return max(0.0, float(total))

    def refresh_anthropic_balance(self) -> Optional[float]:
        """
        Refresh Anthropic remaining balance using official cost_report API.

        Endpoint:
        - GET https://api.anthropic.com/v1/organizations/cost_report
        - Requires ANTHROPIC_ADMIN_KEY (Admin API key)
        """
        if not self._anthropic_live_enabled:
            return None
        if not self._anthropic_admin_key:
            return None

        try:
            start_at = _to_rfc3339(self._baseline_start_utc)
            end_at = _to_rfc3339(_utc_now())
            spent = self._fetch_anthropic_cost_usd(
                start_at_rfc3339=start_at,
                end_at_rfc3339=end_at,
            )
            remaining = max(
                0.0,
                float(self.starting_balances.get("anthropic", 0.0)) - float(spent),
            )
            self.live_spend_since_baseline["anthropic"] = float(spent)
            self.live_balance_overrides["anthropic"] = remaining
            return remaining
        except Exception as e:
            logger.warning(f"Anthropic live balance refresh failed: {e}")
            return None

    def _fetch_anthropic_cost_usd(
        self,
        start_at_rfc3339: str,
        end_at_rfc3339: str,
    ) -> float:
        base_url = "https://api.anthropic.com/v1/organizations/cost_report"
        headers = {
            "x-api-key": self._anthropic_admin_key,
            "anthropic-version": "2023-06-01",
        }

        total = 0.0
        page = None
        for _ in range(12):
            params = {
                "starting_at": start_at_rfc3339,
                "ending_at": end_at_rfc3339,
                "bucket_width": "1d",
                "limit": 31,
            }
            if page:
                params["page"] = page
            url = f"{base_url}?{urllib.parse.urlencode(params)}"
            payload = self._request_json(url, headers)

            data_rows = payload.get("data", [])
            if isinstance(data_rows, dict):
                data_rows = [data_rows]

            for bucket in data_rows:
                if not isinstance(bucket, dict):
                    continue
                results = bucket.get("results", [])
                if isinstance(results, dict):
                    results = [results]
                if not isinstance(results, list):
                    results = []

                if results:
                    for result in results:
                        if not isinstance(result, dict):
                            continue
                        amount = result.get("amount", result.get("cost", 0.0))
                        if isinstance(amount, dict):
                            amount = amount.get("value", amount.get("usd", 0.0))
                        try:
                            total += float(amount)
                        except (TypeError, ValueError):
                            continue
                else:
                    # Defensive fallback for shapes without nested "results"
                    amount = bucket.get("amount", bucket.get("cost", 0.0))
                    if isinstance(amount, dict):
                        amount = amount.get("value", amount.get("usd", 0.0))
                    try:
                        total += float(amount)
                    except (TypeError, ValueError):
                        pass

            has_more = payload.get("has_more", False)
            page = payload.get("next_page")
            if not has_more or not page:
                break
        return max(0.0, float(total))

    def _request_json(self, url: str, headers: dict[str, str]) -> dict:
        request = urllib.request.Request(
            url=url,
            method="GET",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"HTTP {e.code} from {url}: {body[:200]}"
            ) from e
        return json.loads(raw)

    def build_snapshot(self, elapsed_minutes: float) -> dict:
        """
        Build full balance + fuel snapshot.
        """
        self.maybe_refresh_live_balances()

        providers: dict[str, dict] = {}
        depletion_order: list[tuple[str, float]] = []

        elapsed = max(0.0, float(elapsed_minutes))

        for provider in PROVIDERS:
            initial = float(self.starting_balances.get(provider, 0.0))
            spent = float(self.session_spend_by_provider.get(provider, 0.0))

            has_live = provider in self.live_balance_overrides
            if has_live:
                remaining = max(
                    0.0,
                    float(self.live_balance_overrides[provider]),
                )
                source = "live_api"
            else:
                remaining = max(0.0, initial - spent)
                source = "session_estimate"

            observed_rate = spent / elapsed if elapsed > 0 else 0.0
            baseline_rate = float(self.baseline_burn_rates.get(provider, 0.0))
            if observed_rate > 0 and baseline_rate > 0:
                burn_rate = (0.8 * observed_rate) + (0.2 * baseline_rate)
            elif observed_rate > 0:
                burn_rate = observed_rate
            else:
                burn_rate = baseline_rate

            if burn_rate > 0:
                minutes_left = remaining / burn_rate
                depletion_order.append((provider, minutes_left))
            else:
                minutes_left = None

            if initial > 0:
                fuel_percent = (remaining / initial) * 100.0
            else:
                fuel_percent = 0.0

            providers[provider] = {
                "provider": provider,
                "source": source,
                "initial_balance_usd": _round6(initial),
                "session_spent_usd": _round6(spent),
                "live_spend_since_baseline_usd": _round6(
                    float(self.live_spend_since_baseline.get(provider, 0.0))
                ),
                "remaining_usd": _round6(remaining),
                "fuel_percent": _round6(fuel_percent),
                "observed_burn_usd_per_min": _round6(observed_rate),
                "baseline_burn_usd_per_min": _round6(baseline_rate),
                "effective_burn_usd_per_min": _round6(burn_rate),
                "minutes_remaining": (
                    _round6(minutes_left) if minutes_left is not None else None
                ),
                "human_readable_remaining": format_minutes_for_display(
                    minutes_left
                ),
            }

        if depletion_order:
            bottleneck_provider, bottleneck_minutes = min(
                depletion_order,
                key=lambda item: item[1],
            )
            minutes_until_any_depletion = _round6(bottleneck_minutes)
        else:
            bottleneck_provider = None
            minutes_until_any_depletion = None

        return {
            "providers": providers,
            "fuel_gauge": {
                "bottleneck_provider": bottleneck_provider,
                "minutes_until_any_depletion": minutes_until_any_depletion,
                "human_readable_until_any_depletion": format_minutes_for_display(
                    minutes_until_any_depletion
                ),
            },
            "settings": {
                "candidate_speaking_ratio": self.settings.candidate_speaking_ratio,
                "interviewer_speaking_ratio": self.settings.interviewer_speaking_ratio,
                "questions_per_minute": self.settings.questions_per_minute,
                "avg_generation_input_tokens": self.settings.avg_generation_input_tokens,
                "avg_generation_output_tokens": self.settings.avg_generation_output_tokens,
                "avg_embedding_tokens_per_question": self.settings.avg_embedding_tokens_per_question,
                "baseline_start_utc": _to_rfc3339(self._baseline_start_utc),
                "live_openai_enabled": self._openai_live_enabled,
                "live_anthropic_enabled": self._anthropic_live_enabled,
            },
        }
