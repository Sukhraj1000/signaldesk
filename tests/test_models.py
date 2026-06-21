from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from signaldesk_backend import (
    Candle,
    CatalystContext,
    CatalystEvent,
    FundamentalContext,
    KeyLevels,
    Provenance,
    ProviderCapability,
    ProviderMode,
    ProviderResult,
    Quote,
    RiskAssessment,
    RiskFlag,
    ScoreBreakdown,
    ScoreReason,
    SignalCard,
    Symbol,
    TechnicalEvent,
    TechnicalSnapshot,
    UnavailableContext,
)

NOW = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)


def test_symbol_normalizes_ticker_and_defaults() -> None:
    symbol = Symbol(" amd ")

    assert symbol.ticker == "AMD"
    assert symbol.asset_class == "equity"
    assert symbol.currency == "USD"


@pytest.mark.parametrize("ticker", ["", "   ", "BRK B"])
def test_symbol_rejects_empty_or_space_separated_tickers(ticker: str) -> None:
    with pytest.raises(ValueError, match="ticker"):
        Symbol(ticker)


@pytest.mark.parametrize("field_name", ["asset_class", "currency"])
def test_symbol_rejects_blank_metadata(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        Symbol("AMD", **{field_name: " "})


def test_candle_accepts_valid_ohlcv_data() -> None:
    candle = Candle(
        symbol=Symbol("AMD"),
        timestamp=NOW,
        open=Decimal("100.00"),
        high=Decimal("105.50"),
        low=Decimal("99.25"),
        close=Decimal("102.75"),
        volume=1_000_000,
    )

    assert candle.symbol.ticker == "AMD"
    assert candle.high == Decimal("105.50")
    assert candle.volume == 1_000_000


def test_candle_rejects_invalid_price_range() -> None:
    with pytest.raises(ValueError, match="high"):
        Candle(
            symbol=Symbol("AMD"),
            timestamp=NOW,
            open=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=100,
        )


@pytest.mark.parametrize("volume", [-1, -100])
def test_candle_rejects_negative_volume(volume: int) -> None:
    with pytest.raises(ValueError, match="volume"):
        Candle(
            symbol=Symbol("AMD"),
            timestamp=NOW,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=volume,
        )


def test_quote_accepts_bid_ask_last_snapshot() -> None:
    quote = Quote(
        symbol=Symbol("msft"),
        timestamp=NOW,
        bid=Decimal("420.10"),
        ask=Decimal("420.15"),
        last=Decimal("420.12"),
    )

    assert quote.symbol.ticker == "MSFT"
    assert quote.ask == Decimal("420.15")


def test_quote_rejects_crossed_bid_ask() -> None:
    with pytest.raises(ValueError, match="ask"):
        Quote(
            symbol=Symbol("MSFT"),
            timestamp=NOW,
            bid=Decimal("420.20"),
            ask=Decimal("420.10"),
            last=Decimal("420.12"),
        )


def test_provider_capability_records_supported_features() -> None:
    capability = ProviderCapability(
        provider="yfinance",
        data_role=" Price ",
        provider_tier=" Default ",
        supports_realtime=False,
        supports_historical=True,
        supported_asset_classes=frozenset({"equity", "etf"}),
        supported_intervals=frozenset({"1D", " 1wk "}),
        credential_state=" Not Required ",
        live_check_suitable=True,
        max_history_days=3650,
        rate_limit_per_minute=None,
    )

    assert capability.provider == "yfinance"
    assert capability.data_role == "price"
    assert capability.provider_tier == "default"
    assert capability.supports_historical is True
    assert "equity" in capability.supported_asset_classes
    assert capability.supported_intervals == frozenset({"1d", "1wk"})
    assert capability.credential_state == "not_required"
    assert capability.live_check_suitable is True


def test_provider_capability_validates_data_role() -> None:
    with pytest.raises(ValueError, match="data_role"):
        ProviderCapability(
            provider="fmp",
            data_role="news",
            supports_realtime=True,
            supports_historical=True,
        )


def test_provider_capability_validates_provider_tier() -> None:
    with pytest.raises(ValueError, match="provider_tier"):
        ProviderCapability(
            provider="fmp",
            provider_tier="paid",
            supports_realtime=True,
            supports_historical=True,
        )


def test_provider_result_success_and_failure_shapes() -> None:
    candle = Candle(
        symbol=Symbol("AMD"),
        timestamp=NOW,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.50"),
        volume=100,
    )

    success = ProviderResult.success(provider="stub", data=candle, warnings=("delayed",))
    failure: ProviderResult[str] = ProviderResult.failure(provider="stub", error="not available")

    assert success.ok is True
    assert success.data == candle
    assert success.warnings == ("delayed",)
    assert failure.ok is False
    assert failure.error == "not available"


def test_provider_result_rejects_ambiguous_data_and_error() -> None:
    with pytest.raises(ValueError, match="either data or error"):
        ProviderResult(provider="stub", data="payload", error="failed")


def _analysis_fixture() -> tuple[Provenance, KeyLevels, TechnicalEvent, TechnicalSnapshot]:
    provenance = Provenance(
        provider="fixture",
        source="unit-test-candles",
        generated_at=NOW,
        timeframe="1d",
        inputs=("AMD", "  close  "),
    )
    levels = KeyLevels(
        support=(Decimal("100"), Decimal("95.50")),
        resistance=(Decimal("110"),),
        confirmation=Decimal("111"),
        invalidation=Decimal("94"),
    )
    event = TechnicalEvent(
        event_type="Breakout",
        observed_at=NOW,
        summary="Closed above resistance",
        price=Decimal("112"),
        severity="bullish",
    )
    snapshot = TechnicalSnapshot(
        symbol=Symbol("amd"),
        as_of=NOW,
        timeframe="1d",
        trend="UP",
        last_price=Decimal("112"),
        key_levels=levels,
        events=(event,),
        provenance=provenance,
        indicators={" RSI ": Decimal("62.5")},
    )
    return provenance, levels, event, snapshot


def test_analysis_models_construct_and_normalize_values() -> None:
    provenance, levels, event, snapshot = _analysis_fixture()

    assert provenance.inputs == ("AMD", "close")
    assert levels.support == (Decimal("100"), Decimal("95.50"))
    assert event.event_type == "breakout"
    assert snapshot.symbol.ticker == "AMD"
    assert snapshot.trend == "up"
    assert snapshot.indicators == {"rsi": Decimal("62.5")}


def test_fundamental_context_normalizes_provider_facts_without_ta_signals() -> None:
    context = FundamentalContext(
        symbol=Symbol("amd"),
        provider=" FMP ",
        generated_at=NOW,
        company_name=" Advanced Micro Devices, Inc. ",
        exchange=" NASDAQ ",
        industry=" Semiconductors ",
        sector=" Technology ",
        market_cap=289_000_000_000,
        currency=" USD ",
        price=Decimal("176.5"),
        beta=Decimal("1.84"),
        pe_ratio=Decimal("45.2"),
        eps=Decimal("3.91"),
        source_url=" https://www.amd.com ",
    )

    assert context.symbol.ticker == "AMD"
    assert context.provider == "fmp"
    assert context.company_name == "Advanced Micro Devices, Inc."
    assert context.exchange == "NASDAQ"
    assert context.industry == "Semiconductors"
    assert context.sector == "Technology"
    assert context.market_cap == 289_000_000_000
    assert context.currency == "USD"
    assert context.price == Decimal("176.5")
    assert context.beta == Decimal("1.84")
    assert context.pe_ratio == Decimal("45.2")
    assert context.eps == Decimal("3.91")
    assert context.source_url == "https://www.amd.com"


def test_catalyst_context_normalizes_provider_events_without_ta_signals() -> None:
    event = CatalystEvent(
        headline=" AMD announces data center accelerator update ",
        provider=" FMP ",
        published_at=NOW,
        source=" Example Wire ",
        url=" https://example.test/amd-news ",
        summary=" Provider supplied article summary. ",
    )
    context = CatalystContext(
        symbol=Symbol("amd"),
        provider=" FMP ",
        generated_at=NOW,
        events=(event,),
    )

    assert event.headline == "AMD announces data center accelerator update"
    assert event.provider == "fmp"
    assert event.source == "Example Wire"
    assert event.url == "https://example.test/amd-news"
    assert event.summary == "Provider supplied article summary."
    assert context.symbol.ticker == "AMD"
    assert context.provider == "fmp"
    assert context.events == (event,)


@pytest.mark.parametrize("market_cap", [-1, -100])
def test_fundamental_context_rejects_negative_market_cap(market_cap: int) -> None:
    with pytest.raises(ValueError, match="market_cap"):
        FundamentalContext(
            symbol=Symbol("amd"),
            provider="fmp",
            generated_at=NOW,
            market_cap=market_cap,
        )


def test_unavailable_context_normalizes_without_asserting_absence() -> None:
    unavailable = UnavailableContext(
        context_type=" Catalyst Data ",
        reason="FMP_API_KEY is not configured",
        provider=" fmp ",
        details=" ",
    )

    assert unavailable.context_type == "catalyst_data"
    assert unavailable.reason == "FMP_API_KEY is not configured"
    assert unavailable.provider == "fmp"
    assert unavailable.details is None


def test_signal_card_defaults_to_no_unavailable_context() -> None:
    card = SignalCard(
        symbol=Symbol("AMD"),
        generated_at=NOW,
        timeframe="1d",
        bias="neutral",
        summary="Facts-only summary.",
        confidence=Decimal("0.50"),
    )

    assert card.unavailable_context == ()


def test_risk_assessment_normalizes_typed_flags_and_overall_severity() -> None:
    flag = RiskFlag(
        kind=" Breakdown Risk ",
        severity=" WARNING ",
        message="Close below invalidation would weaken the setup.",
        source=" Technical Levels ",
    )
    assessment = RiskAssessment(flags=(flag,), overall_severity=" Warning ")

    assert flag.kind == "breakdown_risk"
    assert flag.severity == "warning"
    assert flag.message == "Close below invalidation would weaken the setup."
    assert flag.source == "technical_levels"
    assert assessment.flags == (flag,)
    assert assessment.overall_severity == "warning"


def test_risk_assessment_derives_highest_flag_severity_when_not_supplied() -> None:
    assessment = RiskAssessment(
        flags=(
            RiskFlag(kind="scope_limit", severity="info", message="TA-only output."),
            RiskFlag(kind="volatility", severity="critical", message="ATR is elevated."),
        )
    )

    assert assessment.overall_severity == "critical"


def test_score_breakdown_normalizes_deterministic_reasons() -> None:
    reason = ScoreReason(
        code=" Trend Alignment ",
        message="Price is above the short and long moving averages.",
        source=" Deterministic TA ",
        weight=Decimal("0.40"),
    )
    score = ScoreBreakdown(
        category=" Setup Quality ",
        score=Decimal("82.5"),
        reasons=(reason,),
    )

    assert reason.code == "trend_alignment"
    assert reason.source == "deterministic_ta"
    assert reason.weight == Decimal("0.40")
    assert score.category == "setup_quality"
    assert score.reasons == (reason,)


def test_signal_card_can_attach_setup_risk_and_data_quality_scores() -> None:
    scores = (
        ScoreBreakdown(
            category="setup_quality",
            score=Decimal("75"),
            reasons=(
                ScoreReason(
                    code="breakout_confirmation",
                    message="Latest close reclaimed the confirmation level.",
                    source="technical_events",
                ),
            ),
        ),
        ScoreBreakdown(
            category="risk",
            score=Decimal("40"),
            reasons=(
                ScoreReason(
                    code="overextension_risk",
                    message="Close is extended versus ATR.",
                    source="risk_engine",
                ),
            ),
        ),
        ScoreBreakdown(
            category="data_quality",
            score=Decimal("90"),
            reasons=(
                ScoreReason(
                    code="sufficient_history",
                    message="Enough candles were available for configured indicators.",
                    source="provider_data",
                ),
            ),
        ),
    )

    card = SignalCard(
        symbol=Symbol("AMD"),
        generated_at=NOW,
        timeframe="1d",
        bias="watch",
        summary="Deterministic score fixture.",
        confidence=Decimal("0.65"),
        scores=scores,
    )

    assert card.scores == scores


def test_signal_card_references_analysis_facts_without_credentials() -> None:
    provenance, levels, event, snapshot = _analysis_fixture()
    unavailable = UnavailableContext(
        context_type="catalyst data",
        reason="FMP_API_KEY is not configured",
        provider="fmp",
    )

    card = SignalCard(
        symbol=Symbol("AMD"),
        generated_at=NOW,
        timeframe="1d",
        bias="Watch",
        summary="Watch for continuation above confirmation with invalidation below support.",
        confidence=Decimal("0.70"),
        snapshot=snapshot,
        key_levels=levels,
        events=(event,),
        provider_mode=ProviderMode(
            mode=" Enhanced ",
            price_provider=" YFinance ",
            catalyst_provider=" FMP ",
            fundamentals_provider=" ",
            llm_provider=" OpenAI ",
        ),
        provenance=(provenance,),
        unavailable_context=(unavailable,),
        risk_assessment=RiskAssessment(
            flags=(
                RiskFlag(
                    kind="scope_limit",
                    severity="info",
                    message="TA-only output; catalysts are unavailable context.",
                ),
            )
        ),
        tags=(" Breakout ", "Momentum"),
    )

    assert card.bias == "watch"
    assert card.snapshot == snapshot
    assert card.key_levels == levels
    assert card.events == (event,)
    assert card.provider_mode == ProviderMode(
        mode="enhanced",
        price_provider="yfinance",
        catalyst_provider="fmp",
        llm_provider="openai",
    )
    assert card.provenance == (provenance,)
    assert card.unavailable_context == (unavailable,)
    assert card.risk_assessment is not None
    assert card.risk_assessment.overall_severity == "info"
    assert card.tags == ("breakout", "momentum")


def test_analysis_models_serialize_with_dataclass_payloads() -> None:
    provenance, levels, event, snapshot = _analysis_fixture()
    unavailable = UnavailableContext(
        context_type="fundamentals",
        reason="enhanced provider not configured",
        provider="fmp",
    )
    card = SignalCard(
        symbol=Symbol("AMD"),
        generated_at=NOW,
        timeframe="1d",
        bias="neutral",
        summary="Facts-only summary.",
        confidence=Decimal("0.50"),
        snapshot=snapshot,
        key_levels=levels,
        events=(event,),
        provider_mode=ProviderMode(mode="default", price_provider="yfinance"),
        provenance=(provenance,),
        unavailable_context=(unavailable,),
        risk_assessment=RiskAssessment(
            flags=(
                RiskFlag(
                    kind="scope_limit",
                    severity="info",
                    message="Enhanced context is unavailable.",
                ),
            )
        ),
        scores=(
            ScoreBreakdown(
                category="data_quality",
                score=Decimal("90"),
                reasons=(
                    ScoreReason(
                        code="fixture_available",
                        message="Fixture data was available for serialization.",
                        source="unit_test",
                    ),
                ),
            ),
        ),
    )

    provenance_payload = asdict(provenance)
    reconstructed_provenance = Provenance(**provenance_payload)
    card_payload = asdict(card)

    assert reconstructed_provenance == provenance
    assert card_payload["symbol"]["ticker"] == "AMD"
    assert card_payload["snapshot"]["key_levels"]["confirmation"] == Decimal("111")
    assert card_payload["provider_mode"]["mode"] == "default"
    assert card_payload["provider_mode"]["price_provider"] == "yfinance"
    assert card_payload["provenance"][0]["source"] == "unit-test-candles"
    assert card_payload["unavailable_context"][0]["context_type"] == "fundamentals"
    assert card_payload["unavailable_context"][0]["reason"] == "enhanced provider not configured"
    assert card_payload["risk_assessment"]["overall_severity"] == "info"
    assert card_payload["risk_assessment"]["flags"][0]["kind"] == "scope_limit"
    assert card_payload["scores"][0]["category"] == "data_quality"
    assert card_payload["scores"][0]["reasons"][0]["code"] == "fixture_available"


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: Provenance(
                provider=" ", source="fixture", generated_at=NOW, timeframe="1d"
            ),
            "provider",
        ),
        (lambda: KeyLevels(support=(Decimal("0"),)), "support"),
        (
            lambda: TechnicalEvent(
                event_type="breakout", observed_at=NOW, summary=" ", severity="info"
            ),
            "summary",
        ),
        (
            lambda: TechnicalSnapshot(
                symbol=Symbol("AMD"),
                as_of=NOW,
                timeframe="1d",
                trend="maybe",
                last_price=Decimal("100"),
                key_levels=KeyLevels(support=(Decimal("90"),)),
            ),
            "trend",
        ),
        (
            lambda: TechnicalSnapshot(
                symbol=Symbol("AMD"),
                as_of=NOW,
                timeframe="1d",
                trend="up",
                last_price=Decimal("100"),
                key_levels=KeyLevels(support=(Decimal("90"),)),
                indicators={"RSI": Decimal("60"), " rsi ": Decimal("61")},
            ),
            "indicator names collide",
        ),
        (
            lambda: UnavailableContext(context_type=" ", reason="not configured"),
            "context_type",
        ),
        (
            lambda: UnavailableContext(context_type="catalyst", reason=" "),
            "reason",
        ),
        (
            lambda: ProviderMode(mode="paid", price_provider="yfinance"),
            "mode",
        ),
        (
            lambda: ProviderMode(mode="default", price_provider=" "),
            "price_provider",
        ),
        (
            lambda: RiskFlag(kind=" ", severity="info", message="risk"),
            "kind",
        ),
        (
            lambda: RiskFlag(kind="scope_limit", severity="urgent", message="risk"),
            "severity",
        ),
        (
            lambda: RiskFlag(kind="scope_limit", severity="info", message=" "),
            "message",
        ),
        (
            lambda: RiskAssessment(flags=()),
            "risk assessment must include at least one flag",
        ),
        (
            lambda: RiskAssessment(
                flags=(RiskFlag(kind="scope_limit", severity="info", message="risk"),),
                overall_severity="urgent",
            ),
            "overall_severity",
        ),
        (
            lambda: RiskAssessment(
                flags=(RiskFlag(kind="volatility", severity="critical", message="risk"),),
                overall_severity="warning",
            ),
            "overall_severity must not be lower than highest flag severity",
        ),
        (
            lambda: ScoreReason(code=" ", message="reason", source="rule"),
            "code",
        ),
        (
            lambda: ScoreReason(code="trend", message=" ", source="rule"),
            "message",
        ),
        (
            lambda: ScoreReason(
                code="trend", message="reason", source="rule", weight=Decimal("-0.1")
            ),
            "weight",
        ),
        (
            lambda: ScoreBreakdown(
                category="timing",
                score=Decimal("50"),
                reasons=(ScoreReason(code="trend", message="reason", source="rule"),),
            ),
            "category",
        ),
        (
            lambda: ScoreBreakdown(
                category="risk",
                score=Decimal("101"),
                reasons=(ScoreReason(code="trend", message="reason", source="rule"),),
            ),
            "score",
        ),
        (
            lambda: ScoreBreakdown(category="risk", score=Decimal("50"), reasons=()),
            "score breakdown must include at least one reason",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=Decimal("0.5"),
                unavailable_context=("missing",),  # type: ignore[arg-type]
            ),
            "unavailable_context entries",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=Decimal("0.5"),
                provider_mode="default",  # type: ignore[arg-type]
            ),
            "provider_mode must be ProviderMode",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=Decimal("0.5"),
                scores=("score",),  # type: ignore[arg-type]
            ),
            "scores entries must be ScoreBreakdown",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=Decimal("1.1"),
            ),
            "confidence",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=1,  # type: ignore[arg-type]
            ),
            "confidence must be a Decimal",
        ),
    ],
)
def test_analysis_models_reject_invalid_values(
    factory: Callable[[], object], match: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=match):
        factory()
