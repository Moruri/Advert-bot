from __future__ import annotations

import pytest

from app.services.targeting import is_uk_audience, score_text


def test_strong_uk_signals_score_high() -> None:
    score = score_text(
        "Find the best deals in London, prices in £GBP. Visit shop.co.uk today.",
        language_code="en-GB",
    )
    assert score >= 0.55


def test_non_uk_text_scores_low() -> None:
    score = score_text("Salut! Découvrez nos offres à Paris, prix en €.", language_code="fr-FR")
    assert score < 0.2


def test_uk_postcode_boosts_score() -> None:
    base = score_text("Random sports chat group", language_code="en-US")
    with_postcode = score_text(
        "Meeting in SW1A 1AA area, join us", language_code="en-US"
    )
    assert with_postcode > base


def test_empty_input_is_zero() -> None:
    assert score_text(None) == 0.0
    assert score_text("") == 0.0


def test_is_uk_audience_threshold() -> None:
    assert is_uk_audience(
        "Official HMRC updates for UK taxpayers — nhs and royal mail coverage.",
        language_code="en-GB",
    )
    assert not is_uk_audience("General worldwide news in Spanish", language_code="es-ES")


@pytest.mark.parametrize(
    "text,expected_min",
    [
        ("NHS England and the BBC", 0.3),
        ("Tesco Manchester branch reopening", 0.3),
        ("Premier League fixtures this weekend in Glasgow", 0.4),
    ],
)
def test_culture_and_city_signals(text: str, expected_min: float) -> None:
    assert score_text(text) >= expected_min
