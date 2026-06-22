import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import signaldesk_backend.providers as providers_module
import signaldesk_cli.main as cli_main
from pytest import MonkeyPatch
from signaldesk_backend import (
    Candle,
    ProviderCapability,
    ProviderRegistry,
    ProviderResult,
    Quote,
    Settings,
    Symbol,
)
from signaldesk_cli.main import (
    _config_inspect_payload,
    _format_config_inspect,
    _format_provider_capabilities,
    _format_provider_health,
    _run_provider_health_checks,
    _scan_watchlist_payload,
    app,
)
from typer.testing import CliRunner


@dataclass(frozen=True)
class ExplodingProvider:
    name: str = "exploding"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return ()

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        return ProviderResult.failure(provider=self.name, error="not implemented")

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        return ProviderResult.failure(provider=self.name, error="not implemented")

    def health_check(self) -> ProviderResult[str]:
        raise RuntimeError("secret detail should not be shown")


@dataclass(frozen=True)
class ExplodingCapabilitiesProvider(ExplodingProvider):
    name: str = "exploding-capabilities"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        raise RuntimeError("secret capability detail should not be shown")


@dataclass(frozen=True)
class WorkingProvider:
    name: str = "working"
    credential_state: str = "not_required"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"fixture"}),
                supported_intervals=frozenset({"1d"}),
                credential_state=self.credential_state,
                live_check_suitable=True,
                max_history_days=365,
                rate_limit_per_minute=60,
            ),
        )

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        candles = tuple(
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal(index + 10),
                high=Decimal(index + 11),
                low=Decimal(index + 9),
                close=Decimal(index + 10),
                volume=1000 + index,
            )
            for index in range(40)
        )
        return ProviderResult.success(provider=self.name, data=candles)

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        return ProviderResult.failure(provider=self.name, error="not implemented")

    def health_check(self) -> ProviderResult[str]:
        return ProviderResult.success(provider=self.name, data="healthy")


@dataclass(frozen=True)
class FundamentalsCapabilityProvider(WorkingProvider):
    name: str = "fundamentals-provider"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider=self.name,
                data_role="fundamentals",
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity"}),
                supported_intervals=frozenset({"1d"}),
                credential_state="required",
                live_check_suitable=False,
            ),
        )


@dataclass(frozen=True)
class FmpRolesProvider(WorkingProvider):
    name: str = "fmp"
    credential_state: str = "configured"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider=self.name,
                data_role="price",
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity"}),
                supported_intervals=frozenset({"1d"}),
                credential_state=self.credential_state,
                provider_tier="enhanced",
            ),
            ProviderCapability(
                provider=self.name,
                data_role="fundamentals",
                supports_realtime=False,
                supports_historical=False,
                supported_asset_classes=frozenset({"equity"}),
                credential_state=self.credential_state,
                provider_tier="enhanced",
            ),
            ProviderCapability(
                provider=self.name,
                data_role="catalyst",
                supports_realtime=False,
                supports_historical=False,
                supported_asset_classes=frozenset({"equity"}),
                credential_state=self.credential_state,
                provider_tier="enhanced",
            ),
        )


@dataclass(frozen=True)
class SwingingProvider(WorkingProvider):
    name: str = "swinging"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        candles = [
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=1000 + index,
            )
            for index in range(34)
        ]
        pattern = (
            ("10", "8.50", "9"),
            ("12.05", "9", "12"),
            ("11", "8", "8.50"),
            ("12", "9", "11"),
            ("10", "8.05", "9"),
            ("11", "9", "10"),
        )
        for offset, (high, low, close) in enumerate(pattern, start=34):
            candles.append(
                Candle(
                    symbol=symbol,
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=offset),
                    open=Decimal("10"),
                    high=Decimal(high),
                    low=Decimal(low),
                    close=Decimal(close),
                    volume=1000 + offset,
                )
            )
        return ProviderResult.success(provider=self.name, data=tuple(candles))


@dataclass(frozen=True)
class MovingAverageCrossProvider(WorkingProvider):
    name: str = "ma-cross"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        closes = (*("10" for _ in range(19)), "9", "12")
        candles = tuple(
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=1000 + index,
            )
            for index, close in enumerate(closes)
        )
        return ProviderResult.success(provider=self.name, data=candles)


@dataclass(frozen=True)
class TrendRegimeShiftProvider(WorkingProvider):
    name: str = "trend-regime-shift"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        closes = (*("10" for _ in range(50)), "70")
        candles = tuple(
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal(close),
                high=Decimal("80"),
                low=Decimal("1"),
                close=Decimal(close),
                volume=1000 + index,
            )
            for index, close in enumerate(closes)
        )
        return ProviderResult.success(provider=self.name, data=candles)


@dataclass(frozen=True)
class RelativeVolumeSpikeProvider(WorkingProvider):
    name: str = "relative-volume-spike"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        candles = tuple(
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=200 if index == 20 else 100,
            )
            for index in range(21)
        )
        return ProviderResult.success(provider=self.name, data=candles)


@dataclass(frozen=True)
class OverextensionProvider(WorkingProvider):
    name: str = "overextension"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        closes = (*("10" for _ in range(18)), "14", "15")
        candles = tuple(
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=1000 + index,
            )
            for index, close in enumerate(closes)
        )
        return ProviderResult.success(provider=self.name, data=candles)


@dataclass(frozen=True)
class FailingHistoricalProvider(WorkingProvider):
    name: str = "failing-history"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        return ProviderResult.failure(
            provider=self.name,
            error="GET https://example.test/path?apikey=secret failed",
        )


@dataclass(frozen=True)
class ConcurrencyRecordingProvider(WorkingProvider):
    name: str = "concurrency-recording"
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: int = 0
    max_active: int = 0

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        with self.lock:
            active = self.active + 1
            object.__setattr__(self, "active", active)
            object.__setattr__(self, "max_active", max(self.max_active, active))
        try:
            time.sleep(0.01)
            return super().get_historical_candles(symbol, start=start, end=end, interval=interval)
        finally:
            with self.lock:
                object.__setattr__(self, "active", self.active - 1)


def test_health_command() -> None:
    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    assert "SignalDesk is configured for local." in result.stdout


def test_config_inspect_reports_sanitized_table(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://signaldesk:dbpass@example.test:5432/signaldesk"
    )
    monkeypatch.setenv("REDIS_URL", "redis://:redispass@cache.test:6379/0")
    monkeypatch.setenv("LLM_PROVIDER", "none")

    result = CliRunner().invoke(app, ["config", "inspect"])

    assert result.exit_code == 0
    assert "setting\tvalue" in result.stdout
    assert "app_env\ttest" in result.stdout
    assert "log_level\tdebug" in result.stdout
    assert "database_url\tpostgresql://<redacted>@example.test:5432/signaldesk" in result.stdout
    assert "redis_url\tredis://<redacted>@cache.test:6379/0" in result.stdout
    assert "dbpass" not in result.stdout
    assert "redispass" not in result.stdout


def test_config_inspect_reports_json_and_rejects_unknown_output(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@example.test/db?sslmode=require")
    monkeypatch.setenv("REDIS_URL", "redis://redis.test:6379/0")

    json_result = CliRunner().invoke(app, ["config", "inspect", "--output", "json"])
    invalid_result = CliRunner().invoke(app, ["config", "inspect", "--output", "xml"])

    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["database_url"] == "postgresql://<redacted>@example.test/db?sslmode=require"
    assert payload["redis_url"] == "redis://redis.test:6379/0"
    assert "password" not in json_result.stdout
    assert invalid_result.exit_code == 2
    assert "--output must be 'table' or 'json'." in invalid_result.stderr


def test_scan_command_runs_watchlist_against_fixture_provider(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("symbols:\n  - amd\n  - MSFT\n  - AMD\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--watchlist",
            str(watchlist),
            "--provider",
            "working",
            "--llm",
            "none",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["symbols"] == ["AMD", "MSFT"]
    assert payload["provider_mode"] == {
        "mode": "explicit",
        "price_provider": "working",
        "fundamentals_provider": None,
        "catalyst_provider": None,
        "llm_provider": None,
        "unavailable_context": [],
    }
    assert [item["status"] for item in payload["results"]] == ["ok", "ok"]
    assert [item["symbol"] for item in payload["ranked_setups"]] == ["AMD", "MSFT"]
    assert [item["rank"] for item in payload["ranked_setups"]] == [1, 2]
    assert payload["failed_symbols"] == []
    assert payload["summary"] == {"total": 2, "ok": 2, "failed": 0, "skipped": 0}
    first_summary = payload["results"][0]["summary"]
    assert first_summary["schema_version"] == "signaldesk.ta.v1"
    assert first_summary["symbol"] == "AMD"
    assert first_summary["provider"] == "working"
    assert first_summary["latest_close"] == "49"
    assert first_summary["provenance"] == [
        {
            "provider": "working",
            "source": "historical_candles",
            "timeframe": "1d",
            "inputs": ["AMD"],
            "observations": 40,
        }
    ]
    assert first_summary["unavailable_context"] == [
        {
            "context_type": "fundamentals",
            "reason": "not available in the default technical-analysis CLI path",
            "provider": "working",
        },
        {
            "context_type": "llm_narrative",
            "reason": "--llm none selected; narrative explanations are disabled",
            "provider": None,
        },
    ]


def test_scan_payload_uses_bounded_concurrency_and_keeps_input_order(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    provider = ConcurrencyRecordingProvider()
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((provider,))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "symbols:\n  - AMD\n  - MSFT\n  - NVDA\n",
        encoding="utf-8",
    )
    watchlist_model = cli_main._load_watchlist_model(watchlist)

    exit_code, payload = _scan_watchlist_payload(
        watchlist_model=watchlist_model,
        watchlist=watchlist,
        provider="concurrency-recording",
        mode="default",
        interval="1d",
        days=120,
        max_workers=2,
    )

    assert exit_code == 0
    assert [result["symbol"] for result in payload["results"]] == ["AMD", "MSFT", "NVDA"]
    assert provider.max_active == 2


def test_scan_command_outputs_markdown_watchlist_report(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "name: Markdown Watch\ntags:\n  - default-mode\nsymbols:\n  - AMD\n  - MSFT\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "scan",
            "--watchlist",
            str(watchlist),
            "--provider",
            "working",
            "--output",
            "markdown",
        ],
    )

    assert result.exit_code == 0
    assert "# SignalDesk watchlist report" in result.stdout
    assert "- Watchlist name: `Markdown Watch`" in result.stdout
    assert "| 1 | AMD | ok | working | 49 | unknown | 50 | 60 |" in result.stdout
    assert "| 2 | MSFT | ok | working | 49 | unknown | 50 | 60 |" in result.stdout
    assert "- Symbols scanned: `2`" in result.stdout
    assert "- Failed symbols: `0`" in result.stdout
    assert "## Provenance" in result.stdout
    assert "provider `working`" in result.stdout


def test_scan_command_includes_watchlist_metadata_and_skips_disabled_watchlists(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "name: Growth Watch\n"
        "tags:\n"
        "  - momentum\n"
        "  - default-mode\n"
        "asset_class: equity\n"
        "provider_preference: local-fixture\n"
        "enabled: false\n"
        "notes: Disabled during review.\n"
        "symbols:\n"
        "  - amd\n"
        "  - AMD\n"
        "  - MSFT\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["scan", "--watchlist", str(watchlist), "--provider", "working", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["watchlist_model"] == {
        "name": "Growth Watch",
        "tags": ["momentum", "default-mode"],
        "asset_class": "equity",
        "provider_preference": "local-fixture",
        "enabled": False,
        "notes": "Disabled during review.",
        "symbols": ["AMD", "MSFT"],
    }
    assert payload["ranked_setups"] == []
    assert payload["failed_symbols"] == []
    assert payload["summary"] == {"total": 2, "ok": 0, "failed": 0, "skipped": 2}
    assert payload["skipped_symbols"] == [
        {"symbol": "AMD", "status": "skipped", "reason": "watchlist is disabled"},
        {"symbol": "MSFT", "status": "skipped", "reason": "watchlist is disabled"},
    ]

    table_result = CliRunner().invoke(
        app, ["scan", "--watchlist", str(watchlist), "--provider", "working"]
    )

    assert table_result.exit_code == 0
    assert "AMD\tskipped" in table_result.stdout
    assert "MSFT\tskipped" in table_result.stdout
    assert "watchlist is disabled" in table_result.stdout
    assert "ok=0 failed=0 skipped=2 total=2" in table_result.stdout


def test_scan_command_reports_watchlist_errors(tmp_path: Path) -> None:
    missing_result = CliRunner().invoke(
        app, ["scan", "--watchlist", str(tmp_path / "missing.yaml")]
    )

    assert missing_result.exit_code == 2
    assert "watchlist file not found" in missing_result.stderr

    directory_result = CliRunner().invoke(app, ["scan", "--watchlist", str(tmp_path)])

    assert directory_result.exit_code == 2
    assert "watchlist file not found" in directory_result.stderr


def test_scan_uses_watchlist_provider_preference_when_provider_is_omitted(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "name: Preferred Provider Watch\n"
        "provider_preference: working\n"
        "symbols:\n"
        "  - AMD\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app, ["scan", "--watchlist", str(watchlist), "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["provider_mode"] == {
        "mode": "explicit",
        "price_provider": "working",
        "fundamentals_provider": None,
        "catalyst_provider": None,
        "llm_provider": None,
        "unavailable_context": [],
    }
    assert payload["watchlist_model"]["provider_preference"] == "working"
    assert payload["results"][0]["summary"]["provider"] == "working"


def test_scan_payload_ranks_successes_and_splits_failures(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((WorkingProvider(), FailingHistoricalProvider())),
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("symbols:\n  - MSFT\n  - AMD\n", encoding="utf-8")

    success_result = CliRunner().invoke(
        app,
        ["scan", "--watchlist", str(watchlist), "--provider", "working", "--output", "json"],
    )

    assert success_result.exit_code == 0
    success_payload = json.loads(success_result.stdout)
    assert [item["rank"] for item in success_payload["ranked_setups"]] == [1, 2]
    assert [item["symbol"] for item in success_payload["ranked_setups"]] == ["AMD", "MSFT"]
    assert success_payload["failed_symbols"] == []

    failure_result = CliRunner().invoke(
        app,
        [
            "scan",
            "--watchlist",
            str(watchlist),
            "--provider",
            "failing-history",
            "--output",
            "json",
        ],
    )

    assert failure_result.exit_code == 1
    failure_payload = json.loads(failure_result.stdout)
    assert failure_payload["ranked_setups"] == []
    assert failure_payload["summary"] == {"total": 2, "ok": 0, "failed": 2, "skipped": 0}
    assert [item["symbol"] for item in failure_payload["failed_symbols"]] == ["MSFT", "AMD"]
    assert all(item["status"] == "failed" for item in failure_payload["failed_symbols"])
    assert "apikey=<redacted>" in failure_payload["failed_symbols"][0]["error"]
    assert "secret" not in json.dumps(failure_payload)


def test_config_inspect_helpers_redact_secrets_from_payload() -> None:
    payload = _config_inspect_payload(
        Settings(
            app_env="ci",
            log_level="warning",
            database_url="postgresql://user:password@example.test/db",
            redis_url="redis://:password@redis.test:6379/0",
            llm_provider="none",
        )
    )
    lines = _format_config_inspect(payload)

    assert payload["database_url"] == "postgresql://<redacted>@example.test/db"
    assert payload["redis_url"] == "redis://<redacted>@redis.test:6379/0"
    assert "password" not in json.dumps(payload)
    assert "password" not in "\n".join(lines)


def test_providers_check_is_available_from_help() -> None:
    result = CliRunner().invoke(app, ["providers", "--help"])

    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "list" in result.stdout
    assert "mode" in result.stdout


def test_providers_list_reports_yfinance_capabilities(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "list"])

    assert result.exit_code == 0
    assert (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute"
        in result.stdout
    )
    assert (
        "local-fixture\tdefault\tprice\tfalse\ttrue\tequity,fixture\t1d\tnot_required\ttrue"
        in result.stdout
    )
    assert (
        "polygon\tenhanced\tprice\ttrue\ttrue\tequity,etf,index\t1d\tplaceholder\tfalse"
        in result.stdout
    )
    assert (
        "twelve-data\tenhanced\tprice\ttrue\ttrue\tequity,etf,index\t1d\tplaceholder\tfalse"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tprice\ttrue\ttrue\tequity,etf,index\t1d\tnot_configured\tfalse"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tfundamentals\tfalse\tfalse\tequity,etf,index\t\tnot_configured\tfalse"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tcatalyst\tfalse\tfalse\tequity,etf,index\t\tnot_configured\tfalse"
        in result.stdout
    )
    assert "yfinance\tdefault\tprice\ttrue\ttrue\tcrypto,equity,etf,index" in result.stdout
    assert "not_required\tfalse" in result.stdout


def test_providers_mode_resolves_default_price_role(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "mode"])

    assert result.exit_code == 0
    assert "role\tprovider" in result.stdout
    assert "mode\tdefault" in result.stdout
    assert "price\tyfinance" in result.stdout
    assert "fundamentals\tunavailable" in result.stdout
    assert "catalyst\tunavailable" in result.stdout


def test_providers_mode_honors_default_price_role_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALDESK_DEFAULT_PRICE_PROVIDER", "local-fixture")

    result = CliRunner().invoke(app, ["providers", "mode"])

    assert result.exit_code == 0
    assert "mode\tdefault" in result.stdout
    assert "price\tlocal-fixture" in result.stdout


def test_providers_mode_rejects_unusable_default_price_role_env(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("SIGNALDESK_DEFAULT_PRICE_PROVIDER", "fmp")

    result = CliRunner().invoke(app, ["providers", "mode", "--output", "json"])

    assert result.exit_code == 2
    assert "default price provider is not usable for price role: fmp" in result.stderr


def test_providers_mode_reports_unusable_enhanced_role_env(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("SIGNALDESK_ENHANCED_PRICE_PROVIDER", "missing-provider")

    result = CliRunner().invoke(
        app, ["providers", "mode", "--mode", "enhanced", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["price_provider"] == "yfinance"
    assert payload["unavailable_context"][0]["provider"] == "missing-provider"


def test_providers_mode_json_reports_enhanced_unavailable_context(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app, ["providers", "mode", "--mode", "enhanced", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "enhanced"
    assert payload["price_provider"] == "yfinance"
    assert payload["fundamentals_provider"] is None
    assert payload["catalyst_provider"] is None
    assert [item["context_type"] for item in payload["unavailable_context"]] == [
        "enhanced_price",
        "fundamentals",
        "catalyst",
    ]
    assert all(item["provider"] == "fmp" for item in payload["unavailable_context"])


def test_providers_list_json_reports_machine_readable_capabilities(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "list", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    capabilities = payload["providers"]
    assert {
        "provider": "local-fixture",
        "tier": "default",
        "role": "price",
        "realtime": False,
        "historical": True,
        "asset_classes": ["equity", "fixture"],
        "intervals": ["1d"],
        "credential_state": "not_required",
        "live_check": True,
        "max_history_days": None,
        "rate_limit_per_minute": None,
    } in capabilities
    assert {
        "provider": "fmp",
        "tier": "enhanced",
        "role": "fundamentals",
        "realtime": False,
        "historical": False,
        "asset_classes": ["equity", "etf", "index"],
        "intervals": [],
        "credential_state": "not_configured",
        "live_check": False,
        "max_history_days": None,
        "rate_limit_per_minute": None,
    } in capabilities
    assert any(
        capability["provider"] == "yfinance"
        and capability["tier"] == "default"
        and capability["role"] == "price"
        and capability["credential_state"] == "not_required"
        for capability in capabilities
    )


def test_providers_list_filters_capabilities_by_role_and_tier(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        ["providers", "list", "--role", "fundamentals", "--tier", "enhanced"],
    )

    assert result.exit_code == 0
    assert (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tfundamentals\tfalse\tfalse\tequity,etf,index\t\tnot_configured\tfalse"
        in result.stdout
    )
    assert "fmp\tenhanced\tprice" not in result.stdout
    assert "local-fixture" not in result.stdout
    assert "yfinance" not in result.stdout


def test_providers_list_json_filters_capabilities_by_default_tier(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "list", "--output", "json", "--tier", "default"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    capabilities = payload["providers"]
    assert capabilities
    assert all(capability["tier"] == "default" for capability in capabilities)
    assert {capability["provider"] for capability in capabilities} == {
        "local-fixture",
        "stooq",
        "yfinance",
    }


def test_providers_list_filters_by_credential_state_and_live_check_safety(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "providers",
            "list",
            "--credential-state",
            "not required",
            "--live-check-only",
        ],
    )

    assert result.exit_code == 0
    assert (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute"
        in result.stdout
    )
    assert (
        "local-csv\tdefault\tprice\tfalse\ttrue\tcrypto,equity,etf,index\t1d\tnot_required\ttrue"
        not in result.stdout
    )
    assert (
        "local-fixture\tdefault\tprice\tfalse\ttrue\tequity,fixture\t1d\tnot_required\ttrue"
        in result.stdout
    )
    assert "stooq" not in result.stdout
    assert "yfinance" not in result.stdout
    assert "fmp" not in result.stdout


def test_providers_list_json_filters_by_credential_state(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "providers",
            "list",
            "--output",
            "json",
            "--credential-state",
            "not_configured",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    capabilities = payload["providers"]
    assert capabilities
    assert all(capability["credential_state"] == "not_configured" for capability in capabilities)
    assert {capability["provider"] for capability in capabilities} == {"fmp"}
    assert {capability["role"] for capability in capabilities} == {
        "price",
        "fundamentals",
        "catalyst",
    }


def test_providers_list_rejects_unknown_output_format() -> None:
    result = CliRunner().invoke(app, ["providers", "list", "--output", "xml"])

    assert result.exit_code == 2
    assert "--output must be 'table' or 'json'." in result.stderr


def test_providers_check_reports_default_local_provider_without_secrets() -> None:
    result = CliRunner().invoke(app, ["providers", "check"])

    assert result.exit_code == 0
    assert "provider\tstatus\tresult" in result.stdout
    assert (
        "local-fixture\tok\tready (deterministic historical candles; "
        "no external credentials required)" in result.stdout
    )
    assert (
        "polygon\tok\tunavailable until Polygon integration is implemented/configured"
        in result.stdout
    )
    assert (
        "twelve-data\tok\tunavailable until Twelve Data integration is implemented/configured"
        in result.stdout
    )
    assert (
        "stooq\tok\tnot checked (no external credentials required; "
        "network availability is verified only during candle fetches)" in result.stdout
    )
    assert "API_KEY" not in result.stdout
    assert "TOKEN" not in result.stdout


def test_providers_check_live_check_only_uses_capability_safety() -> None:
    result = CliRunner().invoke(app, ["providers", "check", "--live-check-only"])

    assert result.exit_code == 0
    assert "provider\tstatus\tresult" in result.stdout
    assert (
        "local-fixture\tok\tready (deterministic historical candles; "
        "no external credentials required)" in result.stdout
    )
    assert "stooq" not in result.stdout
    assert "yfinance" not in result.stdout
    assert "fmp" not in result.stdout
    assert "polygon" not in result.stdout
    assert "twelve-data" not in result.stdout


def test_providers_check_json_live_check_only_reports_safe_subset() -> None:
    result = CliRunner().invoke(
        app, ["providers", "check", "--output", "json", "--live-check-only"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "providers": [
            {
                "provider": "local-fixture",
                "status": "ok",
                "result": (
                    "ready (deterministic historical candles; no external credentials required)"
                ),
                "warnings": [],
            }
        ]
    }


def test_ta_command_runs_against_default_local_fixture_without_network(
    monkeypatch: MonkeyPatch,
) -> None:
    def fail_on_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("local-fixture smoke path must not open network connections")

    monkeypatch.setattr(providers_module, "urlopen", fail_on_network)

    result = CliRunner().invoke(
        app,
        ["ta", "AMD", "--provider", "local-fixture", "--llm", "none", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["symbol"] == "AMD"
    assert payload["provider"] == "local-fixture"
    assert payload["candles"] == 60
    assert payload["provenance"] == [
        {
            "provider": "local-fixture",
            "source": "historical_candles",
            "timeframe": "1d",
            "inputs": ["AMD"],
            "observations": 60,
        }
    ]


def test_ta_command_runs_provider_to_indicator_bridge(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "working", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    assert '"symbol": "AMD"' in result.stdout
    assert '"provider": "working"' in result.stdout
    assert '"latest_close": "49"' in result.stdout
    assert '"sma_20"' in result.stdout
    assert '"rsi_14"' in result.stdout


def test_ta_command_defaults_to_yfinance_provider(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((WorkingProvider(name="yfinance"),)),
    )

    result = CliRunner().invoke(app, ["ta", "AMD", "--llm", "none", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["symbol"] == "AMD"
    assert payload["provider"] == "yfinance"
    assert payload["provider_mode"] == {
        "mode": "default",
        "price_provider": "yfinance",
        "fundamentals_provider": None,
        "catalyst_provider": None,
        "llm_provider": None,
    }
    assert payload["provenance"][0]["provider"] == "yfinance"


def test_ta_command_resolves_enhanced_mode_price_provider(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry(
            (
                WorkingProvider(name="yfinance"),
                FmpRolesProvider(credential_state="configured"),
            )
        ),
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--mode", "enhanced", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["provider"] == "fmp"
    assert payload["provider_mode"] == {
        "mode": "enhanced",
        "price_provider": "fmp",
        "fundamentals_provider": "fmp",
        "catalyst_provider": "fmp",
        "llm_provider": None,
    }


def test_ta_command_reports_enhanced_mode_unavailable_context_when_fmp_key_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry(
            (
                WorkingProvider(name="yfinance"),
                FmpRolesProvider(credential_state="not_configured"),
            )
        ),
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--mode", "enhanced", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["provider"] == "yfinance"
    assert payload["provider_mode"]["mode"] == "enhanced"
    assert payload["provider_mode"]["price_provider"] == "yfinance"
    assert payload["unavailable_context"][:3] == [
        {
            "context_type": "enhanced_price",
            "reason": "FMP credentials are not configured; using default yfinance price provider",
            "provider": "fmp",
            "details": None,
        },
        {
            "context_type": "fundamentals",
            "reason": "FMP credentials are not configured",
            "provider": "fmp",
            "details": None,
        },
        {
            "context_type": "catalyst",
            "reason": "FMP credentials are not configured",
            "provider": "fmp",
            "details": None,
        },
    ]


def test_ta_json_contract_has_explicit_fact_signal_risk_provenance_sections(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "working", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    expected: dict[str, Any] = {
        "schema_version": "signaldesk.ta.v1",
        "symbol": "AMD",
        "provider": "working",
        "provider_mode": {
            "mode": "explicit",
            "price_provider": "working",
            "fundamentals_provider": None,
            "catalyst_provider": None,
            "llm_provider": None,
        },
        "interval": "1d",
        "candles": 40,
        "latest_timestamp": "2024-02-09T00:00:00+00:00",
        "latest_close": "49",
        "sma_20": "39.5",
        "ema_20": "39.50000000000000000000000000",
        "rsi_14": "100",
        "macd": "7.00000000000000000000000000",
        "macd_signal": "7.000000000000000000000000000",
        "macd_histogram": "0E-27",
        "atr_14": "2",
        "volume_average_20": "1029.5",
        "relative_volume_20": "1.010209042294603791929995139",
        "trend_regime": {
            "regime": "unknown",
            "source_rule": "insufficient_history_for_trend_regime",
            "reason": "Need at least 50 closes to classify trend; received 40.",
        },
        "volatility_regime": {
            "regime": "unknown",
            "source_rule": "insufficient_history_for_volatility_regime",
            "reason": "Need at least 64 candles to classify volatility; received 40.",
        },
        "volume_regime": {
            "regime": "normal_volume",
            "source_rule": "latest_volume_within_prior_average_band",
            "reason": "Latest volume is between 0.75x and 1.5x its prior trailing average.",
        },
        "technical_events": [],
        "latest_swing_high": None,
        "latest_swing_low": None,
        "confirmation_level": None,
        "invalidation_level": None,
        "facts": {
            "symbol": "AMD",
            "provider": "working",
            "interval": "1d",
            "candles": 40,
            "latest_timestamp": "2024-02-09T00:00:00+00:00",
            "latest_close": "49",
        },
        "deterministic_signals": {
            "indicators": {
                "sma_20": "39.5",
                "ema_20": "39.50000000000000000000000000",
                "rsi_14": "100",
                "macd": "7.00000000000000000000000000",
                "macd_signal": "7.000000000000000000000000000",
                "macd_histogram": "0E-27",
                "atr_14": "2",
                "volume_average_20": "1029.5",
                "relative_volume_20": "1.010209042294603791929995139",
            },
            "regimes": {
                "trend": {
                    "regime": "unknown",
                    "source_rule": "insufficient_history_for_trend_regime",
                    "reason": "Need at least 50 closes to classify trend; received 40.",
                },
                "volatility": {
                    "regime": "unknown",
                    "source_rule": "insufficient_history_for_volatility_regime",
                    "reason": "Need at least 64 candles to classify volatility; received 40.",
                },
                "volume": {
                    "regime": "normal_volume",
                    "source_rule": "latest_volume_within_prior_average_band",
                    "reason": (
                        "Latest volume is between 0.75x and 1.5x its prior trailing average."
                    ),
                },
            },
            "events": [],
            "swing_levels": {"latest_swing_high": None, "latest_swing_low": None},
            "fibonacci_levels": [],
            "setup_levels": {"confirmation_level": None, "invalidation_level": None},
        },
        "risks": [
            {
                "kind": "scope_limit",
                "severity": "info",
                "message": (
                    "This output contains deterministic technical analysis only; missing "
                    "enhanced context is reported as unavailable context, not as no risk."
                ),
                "source": "technical_analysis_scope",
            },
            {
                "kind": "insufficient_history",
                "severity": "warning",
                "message": (
                    "Provider returned 40 candle(s); some trend and setup rules require "
                    "at least 50 observations."
                ),
                "source": "historical_candles",
            },
            {
                "kind": "stale_data",
                "severity": "warning",
                "message": (
                    "Latest candle is older than the deterministic freshness threshold of 7 day(s)."
                ),
                "source": "historical_candles",
            },
            {
                "kind": "unknown_trend_regime",
                "severity": "warning",
                "message": "Need at least 50 closes to classify trend; received 40.",
                "source": "insufficient_history_for_trend_regime",
            },
            {
                "kind": "unknown_volatility_regime",
                "severity": "warning",
                "message": "Need at least 64 candles to classify volatility; received 40.",
                "source": "insufficient_history_for_volatility_regime",
            },
            {
                "kind": "missing_invalidation_level",
                "severity": "warning",
                "message": "No deterministic invalidation level is available from recent swings.",
                "source": "derive_confirmation_invalidation_levels",
            },
            {
                "kind": "unavailable_enhanced_context",
                "severity": "info",
                "message": (
                    "Fundamental/catalyst context is unavailable and remains separate "
                    "from deterministic TA risk."
                ),
                "source": "unavailable_context",
            },
        ],
        "scores": [
            {
                "category": "setup_quality",
                "score": "50",
                "reasons": [
                    {
                        "code": "deterministic_baseline",
                        "message": "Setup quality starts from a neutral deterministic baseline.",
                        "source": "deterministic_ta",
                        "weight": "0.20",
                    },
                    {
                        "code": "trend_alignment_unconfirmed",
                        "message": (
                            "Trend regime is unknown; no directional setup boost is applied."
                        ),
                        "source": "insufficient_history_for_trend_regime",
                        "weight": "0.20",
                    },
                    {
                        "code": "confirmation_level_unavailable",
                        "message": (
                            "No deterministic confirmation level is available from recent swings."
                        ),
                        "source": "derive_confirmation_invalidation_levels",
                        "weight": "0.10",
                    },
                    {
                        "code": "invalidation_level_unavailable",
                        "message": (
                            "No deterministic invalidation level is available from recent swings."
                        ),
                        "source": "derive_confirmation_invalidation_levels",
                        "weight": "0.10",
                    },
                ],
            },
            {
                "category": "risk",
                "score": "60",
                "reasons": [
                    {
                        "code": "technical_only_scope_limit",
                        "message": (
                            "Risk score includes a baseline because this CLI path is TA-only."
                        ),
                        "source": "scope_limit",
                        "weight": "0.20",
                    },
                    {
                        "code": "unknown_trend_regime",
                        "message": "Trend regime is unknown, increasing risk.",
                        "source": "insufficient_history_for_trend_regime",
                        "weight": "0.15",
                    },
                    {
                        "code": "unknown_volatility_regime",
                        "message": "Volatility regime is unknown, increasing risk.",
                        "source": "insufficient_history_for_volatility_regime",
                        "weight": "0.15",
                    },
                    {
                        "code": "missing_invalidation_level",
                        "message": (
                            "No deterministic invalidation level is available, increasing risk."
                        ),
                        "source": "derive_confirmation_invalidation_levels",
                        "weight": "0.10",
                    },
                ],
            },
            {
                "category": "data_quality",
                "score": "40",
                "reasons": [
                    {
                        "code": "price_history_available",
                        "message": "Provider returned 40 historical candle(s).",
                        "source": "historical_candles",
                        "weight": "0.30",
                    },
                    {
                        "code": "insufficient_history_for_trend_regime",
                        "message": "Need at least 50 closes to classify trend; received 40.",
                        "source": "insufficient_history_for_trend_regime",
                        "weight": "0.15",
                    },
                    {
                        "code": "insufficient_history_for_volatility_regime",
                        "message": "Need at least 64 candles to classify volatility; received 40.",
                        "source": "insufficient_history_for_volatility_regime",
                        "weight": "0.15",
                    },
                    {
                        "code": "stale_price_history",
                        "message": (
                            "Latest candle is older than the deterministic freshness threshold "
                            "of 7 day(s)."
                        ),
                        "source": "historical_candles",
                        "weight": "0.20",
                    },
                    {
                        "code": "fundamentals_unavailable",
                        "message": (
                            "Fundamental context is unavailable and is reported separately "
                            "from TA facts."
                        ),
                        "source": "unavailable_context",
                        "weight": "0.10",
                    },
                ],
            },
        ],
        "provenance": [
            {
                "provider": "working",
                "source": "historical_candles",
                "timeframe": "1d",
                "inputs": ["AMD"],
                "observations": 40,
            }
        ],
        "unavailable_context": [
            {
                "context_type": "fundamentals",
                "reason": "not available in the default technical-analysis CLI path",
                "provider": "working",
            },
            {
                "context_type": "llm_narrative",
                "reason": "--llm none selected; narrative explanations are disabled",
                "provider": None,
            },
        ],
        "llm": "none",
        "narrative": None,
    }
    generated_at = payload["identity"]["generated_at"]
    assert isinstance(generated_at, str)
    datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    expected["facts"]["data_start"] = "2024-01-01T00:00:00+00:00"
    expected["facts"]["data_end"] = "2024-02-09T00:00:00+00:00"
    expected["facts"]["latest_volume"] = 1039
    expected["identity"] = {
        "symbol": "AMD",
        "timeframe": "1d",
        "generated_at": generated_at,
        "schema_version": "signaldesk.ta.v1",
    }
    expected["trend"] = {
        "moving_averages": {
            "sma_20": expected["sma_20"],
            "ema_20": expected["ema_20"],
        },
        "momentum": {
            "rsi_14": expected["rsi_14"],
            "macd": expected["macd"],
            "macd_signal": expected["macd_signal"],
            "macd_histogram": expected["macd_histogram"],
        },
        "volatility": {
            "atr_14": expected["atr_14"],
        },
        "volume": {
            "volume_average_20": expected["volume_average_20"],
            "relative_volume_20": expected["relative_volume_20"],
        },
        "regimes": expected["deterministic_signals"]["regimes"],
    }
    expected["levels"] = {
        "support": None,
        "resistance": None,
        "fibonacci": [],
        "confirmation": None,
        "invalidation": None,
    }
    expected["events"] = expected["technical_events"]
    expected["risk"] = {
        "flags": expected["risks"],
        "unavailable_context": expected["unavailable_context"],
    }
    expected["score"] = {
        "breakdowns": expected["scores"],
    }
    expected["signal_card"] = {
        "identity": expected["identity"],
        "provider_mode": expected["provider_mode"],
        "facts": expected["facts"],
        "trend": expected["trend"],
        "levels": expected["levels"],
        "events": expected["events"],
        "risk": expected["risk"],
        "score": expected["score"],
        "provenance": expected["provenance"],
        "unavailable_context": expected["unavailable_context"],
        "llm": "none",
        "narrative": None,
    }
    assert payload == expected


def test_ta_command_outputs_markdown_from_signal_card(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "working", "--llm", "none", "--output", "markdown"]
    )

    assert result.exit_code == 0
    assert "# SignalDesk TA report: AMD" in result.stdout
    assert "## Facts" in result.stdout
    assert "- Generated at: `" in result.stdout
    assert "- Price provider: `working`" in result.stdout
    assert "- Latest close: `49`" in result.stdout
    assert "## Setup" in result.stdout
    assert "- What is the setup? `unknown` trend regime" in result.stdout
    assert "- Why it matters:" in result.stdout
    assert "## Deterministic signals" in result.stdout
    assert "- Trend regime: `unknown`" in result.stdout
    assert "- Score reasons:" in result.stdout
    assert "`setup_quality` `50`" in result.stdout
    assert "deterministic baseline" in result.stdout
    assert "## Technical events" in result.stdout
    assert "- none detected" in result.stdout
    assert "## Confirmation and invalidation" in result.stdout
    assert "- What confirms it: `unavailable`" in result.stdout
    assert "- What invalidates it: `unavailable`" in result.stdout
    assert "## Risks" in result.stdout
    assert "technical analysis only" in result.stdout
    assert "## Unavailable context" in result.stdout
    assert (
        "`fundamentals` via `working`: not available in the default technical-analysis CLI path."
        in result.stdout
    )
    assert "## Provenance" in result.stdout
    assert (
        "provider `working`, source `historical_candles`, timeframe `1d`, "
        "inputs `AMD`, observations `40`"
        in result.stdout
    )
    assert "## Optional narrative" in result.stdout
    assert "- LLM: `none`" in result.stdout
    assert "- Narrative: unavailable" in result.stdout


def test_ta_table_output_stays_flat_when_json_contract_sections_are_added(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(app, ["ta", "AMD", "--provider", "working", "--llm", "none"])

    assert result.exit_code == 0
    assert "schema_version\tsignaldesk.ta.v1" in result.stdout
    assert "symbol\tAMD" in result.stdout
    assert "latest_close\t49" in result.stdout
    assert "setup\tunknown trend; setup_quality=50; risk=60" in result.stdout
    assert "why_it_matters\t" in result.stdout
    assert "what_confirms\tunavailable" in result.stdout
    assert "what_invalidates\tunavailable" in result.stdout
    assert "risk_summary\t" in result.stdout
    assert (
        "unavailable_context_summary\tfundamentals via working: not available in the "
        "default technical-analysis CLI path"
        in result.stdout
    )
    assert "facts\t" not in result.stdout
    assert "deterministic_signals\t" not in result.stdout
    assert "signal_card\t" not in result.stdout
    assert "scores\t" not in result.stdout
    assert "unavailable_context\t" not in result.stdout


def test_ta_command_includes_traceable_confirmation_and_invalidation_levels(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((SwingingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "swinging", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    confirmation = payload["confirmation_level"]
    invalidation = payload["invalidation_level"]

    assert confirmation is not None
    assert confirmation["kind"] == "confirmation"
    assert confirmation["price"] == "12.05"
    assert confirmation["source_rule"] == "nearest_resistance_above_latest_close"
    assert confirmation["source_level"] == "resistance_zone[12.05,12.05] touches=1"
    assert confirmation["reason"] == (
        "Latest close remains below this resistance zone; a move through it would "
        "confirm upside continuation."
    )
    assert invalidation is not None
    assert invalidation["kind"] == "invalidation"
    assert invalidation["price"] == "8"
    assert invalidation["source_rule"] == "nearest_support_below_latest_close"
    assert invalidation["source_level"] == "support_zone[8,8] touches=1"
    assert invalidation["reason"] == (
        "Latest close remains above this support zone; a break below it would "
        "invalidate the current technical setup."
    )


def test_ta_command_includes_traceable_fibonacci_levels(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((SwingingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "swinging", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    fibonacci = payload["levels"]["fibonacci"]

    assert fibonacci == [
        {
            "ratio": "0.236",
            "percent": "23.600",
            "price": "11.09420",
            "direction": "up",
            "swing_start": "8",
            "swing_end": "12.05",
            "source_rule": "latest_swing_low_to_high_retracement",
        },
        {
            "ratio": "0.382",
            "percent": "38.200",
            "price": "10.50290",
            "direction": "up",
            "swing_start": "8",
            "swing_end": "12.05",
            "source_rule": "latest_swing_low_to_high_retracement",
        },
        {
            "ratio": "0.5",
            "percent": "50.0",
            "price": "10.025",
            "direction": "up",
            "swing_start": "8",
            "swing_end": "12.05",
            "source_rule": "latest_swing_low_to_high_retracement",
        },
        {
            "ratio": "0.618",
            "percent": "61.800",
            "price": "9.54710",
            "direction": "up",
            "swing_start": "8",
            "swing_end": "12.05",
            "source_rule": "latest_swing_low_to_high_retracement",
        },
        {
            "ratio": "0.786",
            "percent": "78.600",
            "price": "8.86670",
            "direction": "up",
            "swing_start": "8",
            "swing_end": "12.05",
            "source_rule": "latest_swing_low_to_high_retracement",
        },
    ]
    assert payload["signal_card"]["levels"]["fibonacci"] == fibonacci
    assert payload["deterministic_signals"]["fibonacci_levels"] == fibonacci


def test_ta_command_includes_traceable_moving_average_events(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((MovingAverageCrossProvider(),)),
    )

    result = CliRunner().invoke(
        app,
        ["ta", "AMD", "--provider", "ma-cross", "--llm", "none", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["technical_events"] == [
        {
            "event_type": "reclaimed_moving_average",
            "timestamp": "2024-01-21T00:00:00+00:00",
            "candle_index": 20,
            "severity": "bullish",
            "source_rule": "close_crossed_above_sma",
            "source_indicators": ["sma_20"],
            "reason": (
                "Latest close 12 moved above sma_20 10.05 after the prior close was not "
                "above its SMA."
            ),
            "price": "12",
            "invalidation_condition": (
                "A close back below sma_20 10.05 would invalidate the reclaim event."
            ),
        }
    ]
    assert payload["deterministic_signals"]["events"] == payload["technical_events"]


def test_ta_command_includes_traceable_trend_regime_shift_events(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((TrendRegimeShiftProvider(),)),
    )

    result = CliRunner().invoke(
        app,
        [
            "ta",
            "AMD",
            "--provider",
            "trend-regime-shift",
            "--llm",
            "none",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["technical_events"] == [
        {
            "event_type": "reclaimed_moving_average",
            "timestamp": "2024-02-20T00:00:00+00:00",
            "candle_index": 50,
            "severity": "bullish",
            "source_rule": "close_crossed_above_sma",
            "source_indicators": ["sma_20"],
            "reason": (
                "Latest close 70 moved above sma_20 13 after the prior close was not above its SMA."
            ),
            "price": "70",
            "invalidation_condition": (
                "A close back below sma_20 13 would invalidate the reclaim event."
            ),
        },
        {
            "event_type": "trend_regime_shift",
            "timestamp": "2024-02-20T00:00:00+00:00",
            "candle_index": 50,
            "severity": "bullish",
            "source_rule": "latest_candle_changed_trend_regime_classification",
            "source_indicators": ["sma_20", "sma_50"],
            "reason": (
                "Trend regime shifted from sideways to uptrend: Latest close is above "
                "the short SMA, and the short SMA is above the long SMA."
            ),
            "price": "70",
            "invalidation_condition": (
                "A later close changing the deterministic trend regime away from uptrend "
                "would end this regime-shift condition."
            ),
        },
    ]
    assert payload["deterministic_signals"]["events"] == payload["technical_events"]


def test_ta_command_includes_traceable_relative_volume_spike_events(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((RelativeVolumeSpikeProvider(),)),
    )

    result = CliRunner().invoke(
        app,
        [
            "ta",
            "AMD",
            "--provider",
            "relative-volume-spike",
            "--llm",
            "none",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["technical_events"] == [
        {
            "event_type": "relative_volume_spike",
            "timestamp": "2024-01-21T00:00:00+00:00",
            "candle_index": 20,
            "severity": "info",
            "source_rule": "latest_volume_at_least_threshold_x_prior_average",
            "source_indicators": ["relative_volume_20"],
            "reason": "Latest volume 200 is 2x its prior 20-candle average volume 100.",
            "price": "10",
            "invalidation_condition": (
                "Relative volume below 1.5x the prior 20-candle average would end "
                "the spike condition."
            ),
        }
    ]
    assert payload["deterministic_signals"]["events"] == payload["technical_events"]


def test_ta_command_includes_traceable_overextension_events(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((OverextensionProvider(),)),
    )

    result = CliRunner().invoke(
        app,
        ["ta", "AMD", "--provider", "overextension", "--llm", "none", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["technical_events"] == [
        {
            "event_type": "overextension_up",
            "timestamp": "2024-01-20T00:00:00+00:00",
            "candle_index": 19,
            "severity": "warning",
            "source_rule": "latest_close_at_least_atr_multiple_above_sma",
            "source_indicators": ["sma_20", "atr_14"],
            "reason": (
                "Latest close 15 is at least 7x ATR above sma_20 10.45; latest ATR "
                "is 0.3367346938775510204081632653."
            ),
            "price": "15",
            "invalidation_condition": (
                "A close back within 7x ATR of sma_20 10.45 would end the upside "
                "overextension condition."
            ),
        }
    ]
    assert payload["deterministic_signals"]["events"] == payload["technical_events"]


def test_ta_command_reports_provider_failures_without_secrets(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((FailingHistoricalProvider(),)),
    )

    result = CliRunner().invoke(app, ["ta", "AMD", "--provider", "failing-history"])

    assert result.exit_code == 1
    assert "apikey=<redacted>" in result.stderr
    assert "secret" not in result.stderr


def test_ta_command_rejects_llm_modes_until_guardrails_exist() -> None:
    result = CliRunner().invoke(app, ["ta", "AMD", "--llm", "openai"])

    assert result.exit_code == 2
    assert "Only --llm none is currently supported." in result.stderr


def test_ta_command_reports_validation_errors(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    unknown_provider = CliRunner().invoke(app, ["ta", "AMD", "--provider", "missing"])
    invalid_symbol = CliRunner().invoke(app, ["ta", "bad symbol", "--provider", "working"])

    assert unknown_provider.exit_code == 2
    assert "provider not registered: missing" in unknown_provider.stderr
    assert invalid_symbol.exit_code == 2
    assert "ticker must not contain whitespace" in invalid_symbol.stderr


def test_provider_health_formatter_reports_failure_status() -> None:
    line = _format_provider_health(
        "broken",
        ProviderResult.failure(provider="broken", error="unavailable without configured adapter"),
    )

    assert line == "broken\tfailed\tunavailable without configured adapter"


def test_provider_health_formatter_redacts_credential_diagnostics() -> None:
    line = _format_provider_health(
        "broken",
        ProviderResult.failure(
            provider="broken",
            error="GET https://example.test/path?apikey=abc123&symbol=AMD failed",
        ),
    )

    assert "abc123" not in line
    assert line == (
        "broken\tfailed\tGET https://example.test/path?apikey=<redacted>&symbol=AMD failed"
    )


def test_provider_capability_formatter_reports_registry_capabilities() -> None:
    lines = _format_provider_capabilities(ProviderRegistry((ExplodingProvider(),)))

    assert lines == (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute",
        "exploding\tunknown\tunknown\tfalse\tfalse\t\t\tunknown\tfalse\t\t",
    )


def test_provider_capability_formatter_uses_declared_data_role() -> None:
    lines = _format_provider_capabilities(ProviderRegistry((FundamentalsCapabilityProvider(),)))

    assert lines == (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute",
        "fundamentals-provider\tdefault\tfundamentals\tfalse\ttrue\tequity\t1d\trequired\tfalse\t\t",
    )


def test_provider_capability_formatter_includes_limits_when_declared() -> None:
    lines = _format_provider_capabilities(ProviderRegistry((WorkingProvider(),)))

    assert lines == (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute",
        "working\tdefault\tprice\tfalse\ttrue\tfixture\t1d\tnot_required\ttrue\t365\t60",
    )


def test_providers_list_continues_when_capabilities_raise(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((ExplodingCapabilitiesProvider(), ExplodingProvider())),
    )

    result = CliRunner().invoke(app, ["providers", "list"])

    assert result.exit_code == 0
    assert (
        "exploding-capabilities\tunknown\tunknown\tfalse\tfalse\t\t\tunknown\tfalse\t\t"
        in result.stdout
    )
    assert "exploding\tunknown\tunknown\tfalse\tfalse\t\t\tunknown\tfalse\t\t" in result.stdout
    assert "secret capability detail" not in result.stdout


def test_provider_health_checks_convert_exceptions_to_sanitized_failures() -> None:
    exit_code, provider_statuses = _run_provider_health_checks(
        ProviderRegistry((ExplodingProvider(),))
    )

    assert exit_code == 1
    assert provider_statuses == (
        {
            "provider": "exploding",
            "status": "failed",
            "result": "health check raised an exception",
            "warnings": (),
        },
    )
    assert "secret detail" not in json.dumps(provider_statuses)


def test_providers_check_json_reports_sanitized_machine_readable_status(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((WorkingProvider(), ExplodingProvider())),
    )

    result = CliRunner().invoke(app, ["providers", "check", "--output", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "providers": [
            {
                "provider": "exploding",
                "status": "failed",
                "result": "health check raised an exception",
                "warnings": [],
            },
            {
                "provider": "working",
                "status": "ok",
                "result": "healthy",
                "warnings": [],
            },
        ]
    }
    assert "secret detail" not in result.stdout


def test_providers_check_rejects_unknown_output_format() -> None:
    result = CliRunner().invoke(app, ["providers", "check", "--output", "xml"])

    assert result.exit_code == 2
    assert "--output must be 'table' or 'json'." in result.stderr


def test_ta_json_schema_documents_required_signal_card_sections(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "docs/schemas/signaldesk.ta.v1.schema.json"
    golden_path = repo_root / "tests/golden/ta_signal_card_contract_v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    golden_contract = json.loads(golden_path.read_text(encoding="utf-8"))
    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "working", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    signal_card_required = schema["properties"]["signal_card"]["required"]

    assert golden_contract["schema_version"] == "signaldesk.ta.v1"
    assert schema["properties"]["schema_version"] == {"const": "signaldesk.ta.v1"}
    assert payload["schema_version"] == golden_contract["schema_version"]
    assert schema["required"] == golden_contract["required_top_level_sections"]
    assert signal_card_required == golden_contract["required_signal_card_sections"]
    assert set(golden_contract["required_top_level_sections"]).issubset(payload)
    assert set(signal_card_required) == set(payload["signal_card"].keys())
    for section in golden_contract["alias_sections_that_must_match_signal_card"]:
        assert payload["signal_card"][section] == payload[section]
    assert sorted(
        item["context_type"] for item in payload["signal_card"]["unavailable_context"]
    ) == sorted(golden_contract["required_unavailable_context_types"])
    assert [
        item["category"] for item in payload["signal_card"]["score"]["breakdowns"]
    ] == golden_contract["score_breakdown_categories"]
    assert schema["$defs"]["risk"]["required"] == ["flags", "unavailable_context"]
    assert schema["$defs"]["score"]["required"] == ["breakdowns"]


def test_report_watchlist_markdown_uses_fixture_provider(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("symbols:\n  - AMD\n  - MSFT\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["report", "--watchlist", str(watchlist), "--provider", "working", "--format", "markdown"],
    )

    assert result.exit_code == 0
    assert "# SignalDesk watchlist report" in result.stdout
    assert "| 1 | AMD | ok | working | 49 | unknown | 50 | 60 |" in result.stdout
    assert "| 2 | MSFT | ok | working | 49 | unknown | 50 | 60 |" in result.stdout
    assert "## Provenance" in result.stdout
    assert "provider `working`" in result.stdout

def test_report_watchlist_markdown_separates_signal_card_sections(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("symbols:\n  - AMD\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["report", "--watchlist", str(watchlist), "--provider", "working", "--format", "markdown"],
    )

    assert result.exit_code == 0
    assert "## Signal cards" in result.stdout
    assert "### AMD" in result.stdout
    assert "#### Facts" in result.stdout
    assert "#### Setup" in result.stdout
    assert "- What is the setup? `unknown` trend regime" in result.stdout
    assert "- Why it matters:" in result.stdout
    assert "#### Deterministic signals" in result.stdout
    assert "#### Confirmation and invalidation" in result.stdout
    assert "- What confirms it: `unavailable`" in result.stdout
    assert "- What invalidates it: `unavailable`" in result.stdout
    assert "#### Risks" in result.stdout
    assert "#### Unavailable context" in result.stdout
    assert "- Latest close: `49`" in result.stdout
    assert "- Trend regime: `unknown`" in result.stdout
    assert (
        "- `fundamentals` via `working`: not available in the default technical-analysis CLI path"
        in result.stdout
    )
    assert (
        "- `llm_narrative` via `none`: --llm none selected; narrative explanations are disabled"
        in result.stdout
    )

def test_report_watchlist_json_uses_fixture_provider(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("symbols:\n  - AMD\n  - MSFT\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["report", "--watchlist", str(watchlist), "--provider", "working", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["watchlist"] == str(watchlist)
    assert payload["provider_mode"] == {
        "mode": "explicit",
        "price_provider": "working",
        "fundamentals_provider": None,
        "catalyst_provider": None,
        "llm_provider": None,
        "unavailable_context": [],
    }
    assert payload["symbols"] == ["AMD", "MSFT"]
    assert [result["status"] for result in payload["results"]] == ["ok", "ok"]
    assert [result["rank"] for result in payload["ranked_setups"]] == [1, 2]
    assert [result["symbol"] for result in payload["ranked_setups"]] == ["AMD", "MSFT"]
    assert payload["failed_symbols"] == []
    amd_summary = payload["results"][0]["summary"]
    assert amd_summary["symbol"] == "AMD"
    assert amd_summary["provider"] == "working"
    assert amd_summary["latest_close"] == "49"
    assert amd_summary["provenance"][0]["provider"] == "working"
    assert sorted(item["context_type"] for item in amd_summary["unavailable_context"]) == [
        "fundamentals",
        "llm_narrative",
    ]


def test_report_watchlist_redacts_provider_failure_secrets(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((FailingHistoricalProvider(),)),
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("symbols:\n  - AMD\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "report",
            "--watchlist",
            str(watchlist),
            "--provider",
            "failing-history",
            "--format",
            "markdown",
        ],
    )

    assert result.exit_code == 1
    assert "apikey=<redacted>" in result.stdout
    assert "secret" not in result.stdout
    assert "secret" not in result.stderr


def test_report_watchlist_rejects_unsupported_format_and_llm() -> None:
    bad_format = CliRunner().invoke(
        app, ["report", "--watchlist", "watchlists/default.yaml", "--format", "html"]
    )
    bad_llm = CliRunner().invoke(
        app, ["report", "--watchlist", "watchlists/default.yaml", "--llm", "openai"]
    )

    assert bad_format.exit_code == 2
    assert "--format must be 'markdown' or 'json'." in bad_format.stderr
    assert bad_llm.exit_code == 2
    assert "Only --llm none is currently supported." in bad_llm.stderr


def test_fixtures_generate_writes_local_csv_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "fixtures"

    result = CliRunner().invoke(
        app,
        [
            "fixtures",
            "generate",
            "--symbol",
            "AMD",
            "--output-dir",
            str(output_dir),
            "--days",
            "3",
            "--as-of",
            "2024-12-31",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    fixture_path = output_dir / "amd-1d.csv"
    assert payload == {
        "generated": [
            {
                "as_of": "2024-12-31",
                "compatible_provider": "local-csv",
                "interval": "1d",
                "path": str(fixture_path),
                "provider": "local-fixture",
                "rows": 3,
                "symbol": "AMD",
            }
        ],
        "schema_version": "signaldesk.fixtures.v1",
    }
    assert fixture_path.read_text(encoding="utf-8").splitlines() == [
        "Date,Open,High,Low,Close,Volume",
        "2024-12-29,157,159,155,158,10057",
        "2024-12-30,158,160,156,159,10058",
        "2024-12-31,159,161,157,160,10059",
    ]


def test_fixtures_generate_rejects_invalid_options(tmp_path: Path) -> None:
    bad_output = CliRunner().invoke(
        app,
        ["fixtures", "generate", "--output-dir", str(tmp_path), "--output", "xml"],
    )
    bad_date = CliRunner().invoke(
        app,
        [
            "fixtures",
            "generate",
            "--output-dir",
            str(tmp_path),
            "--as-of",
            "12/31/2024",
        ],
    )

    assert bad_output.exit_code == 2
    assert "--output must be 'table' or 'json'." in bad_output.stderr
    assert bad_date.exit_code == 2
    assert "--as-of must use YYYY-MM-DD format" in bad_date.stderr
