"""Tests for the ordering-strategy registry."""

import pytest

from django_dirt_ratings import ordering
from django_dirt_ratings.models import ReviewStrategy


def test_registry_covers_every_strategy():
    assert set(ordering.OrderingStrategy._registry) == {s.value for s in ReviewStrategy}


def test_build_resolves_each_key():
    assert isinstance(
        ordering.OrderingStrategy.build("breadth_first"), ordering.BreadthFirst
    )
    assert isinstance(
        ordering.OrderingStrategy.build("anomaly_first"), ordering.AnomalyFirst
    )
    triage = ordering.OrderingStrategy.build("triage", triage_depth=5)
    assert isinstance(triage, ordering.Triage)
    assert triage.triage_depth == 5


def test_triage_is_anomaly_first_plus_a_filter():
    # Triage subclasses AnomalyFirst — same ordering, plus the n_reviews guard.
    assert issubclass(ordering.Triage, ordering.AnomalyFirst)


def test_build_accepts_enum_member():
    # Session.strategy may be a ReviewStrategy member or its str value.
    built = ordering.OrderingStrategy.build(ReviewStrategy.ANOMALY_FIRST)
    assert isinstance(built, ordering.AnomalyFirst)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        ordering.OrderingStrategy.build("nonesuch")
