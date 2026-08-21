"""Tests for the ordering-strategy registry."""

import pytest

from django_dirt_ratings import ordering
from django_dirt_ratings.models import ReviewStrategy


def test_registry_covers_every_strategy():
    every_key = {s.value for s in ReviewStrategy}

    registered = set(ordering.OrderingStrategy._registry)

    assert registered == every_key


@pytest.mark.parametrize(
    "key, expected_class",
    [
        ("breadth_first", ordering.BreadthFirst),
        ("anomaly_first", ordering.AnomalyFirst),
        ("triage", ordering.Triage),
        # Session.strategy may be a ReviewStrategy member or its str value.
        (ReviewStrategy.ANOMALY_FIRST, ordering.AnomalyFirst),
    ],
)
def test_build_resolves_key_to_its_strategy(key, expected_class):
    built = ordering.OrderingStrategy.build(key)

    assert isinstance(built, expected_class)


def test_build_passes_triage_depth_through():
    built = ordering.OrderingStrategy.build("triage", triage_depth=5)

    assert built.triage_depth == 5


def test_triage_is_anomaly_first_plus_a_filter():
    # Triage subclasses AnomalyFirst — same ordering, plus the n_reviews guard.
    assert issubclass(ordering.Triage, ordering.AnomalyFirst)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        ordering.OrderingStrategy.build("nonesuch")
