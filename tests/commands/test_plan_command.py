"""Tests for the `manage plan` command."""

import pytest
from django.core.management import call_command

from django_dirt_ratings import models, plan


@pytest.mark.django_db
def test_apply_activates_plan(tmp_path):
    f = tmp_path / "dirt.toml"
    f.write_text('[ordering]\nstrategy = "anomaly_first"\n')
    call_command("plan", str(f))
    assert plan.active().strategy == models.ReviewStrategy.ANOMALY_FIRST


@pytest.mark.django_db
def test_show_reports_active(tmp_path, capsys):
    f = tmp_path / "dirt.toml"
    f.write_text('name = "shown"\n')
    call_command("plan", str(f))
    call_command("plan", show=True)
    assert "shown" in capsys.readouterr().out
