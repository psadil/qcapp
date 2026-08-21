"""Tests for the `manage plan` command."""

import pytest
from django.core.management import call_command

from django_dirt_ratings import models, plan


@pytest.fixture
def write_plan(tmp_path):
    """Write a dirt.toml under tmp_path; hand back its path."""

    def _write(text: str) -> str:
        path = tmp_path / "dirt.toml"
        path.write_text(text)
        return str(path)

    return _write


@pytest.mark.django_db
def test_apply_activates_plan(write_plan):
    path = write_plan('[ordering]\nstrategy = "anomaly_first"\n')

    call_command("plan", path)

    assert plan.active().strategy == models.ReviewStrategy.ANOMALY_FIRST


@pytest.mark.django_db
def test_show_reports_active(write_plan, capsys):
    call_command("plan", write_plan('name = "shown"\n'))
    capsys.readouterr()  # discard the apply run's output, so --show is on its own

    call_command("plan", show=True)

    assert "shown" in capsys.readouterr().out
