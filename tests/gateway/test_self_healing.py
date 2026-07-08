"""Tests for the self-healing background health checker (gateway/self_healing.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gateway.self_healing import (
    HealthCheckResult,
    _check_config_yaml,
    _check_disk_space,
    _check_local_model,
    _check_state_db,
    run_health_checks,
    start_self_healing_monitor,
    stop_self_healing_monitor,
)


@pytest.fixture(autouse=True)
def _zeb_home(tmp_path, monkeypatch):
    monkeypatch.setattr("zeb_constants.get_zeb_home", lambda: tmp_path)
    yield tmp_path


class TestCheckLocalModel:
    def test_not_loaded_is_ok(self, monkeypatch):
        monkeypatch.setattr("agent.llama_cpp_adapter.is_model_loaded", lambda: False)
        result = _check_local_model({})
        assert result.status == "ok"
        assert "not loaded" in result.message

    def test_loaded_and_responsive_is_ok(self, monkeypatch):
        monkeypatch.setattr("agent.llama_cpp_adapter.is_model_loaded", lambda: True)
        monkeypatch.setattr("agent.llama_cpp_adapter._loaded_model_path", "/fake/model.gguf")
        fake_client = MagicMock()
        fake_client.ping.return_value = True
        monkeypatch.setattr(
            "agent.llama_cpp_adapter.LlamaCppClient", lambda model_path: fake_client
        )
        result = _check_local_model({})
        assert result.status == "ok"
        assert result.repaired is False

    def test_ping_failure_unloads_and_reports_degraded(self, monkeypatch):
        monkeypatch.setattr("agent.llama_cpp_adapter.is_model_loaded", lambda: True)
        monkeypatch.setattr("agent.llama_cpp_adapter._loaded_model_path", "/fake/model.gguf")
        fake_client = MagicMock()
        fake_client.ping.return_value = False
        monkeypatch.setattr(
            "agent.llama_cpp_adapter.LlamaCppClient", lambda model_path: fake_client
        )
        unload_calls = []
        monkeypatch.setattr(
            "agent.llama_cpp_adapter.unload_model", lambda: unload_calls.append(1)
        )
        result = _check_local_model({})
        assert result.status == "degraded"
        assert result.repaired is True
        assert unload_calls == [1]


class TestCheckDiskSpace:
    def test_reports_ok_with_plenty_of_space(self, tmp_path):
        result = _check_disk_space({})
        assert result.status == "ok"


class TestCheckStateDb:
    def test_missing_db_is_ok(self):
        result = _check_state_db({})
        assert result.status == "ok"
        assert "not created yet" in result.message

    def test_readable_db_is_ok(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "state.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
        conn.close()
        result = _check_state_db({})
        assert result.status == "ok"
        assert result.message == "readable"


class TestCheckConfigYaml:
    def test_missing_config_is_ok(self):
        result = _check_config_yaml({})
        assert result.status == "ok"

    def test_valid_yaml_is_ok(self, tmp_path):
        (tmp_path / "config.yaml").write_text("model: foo\n")
        result = _check_config_yaml({})
        assert result.status == "ok"

    def test_corrupt_yaml_is_critical_and_backed_up(self, tmp_path):
        (tmp_path / "config.yaml").write_text("model: [unterminated\n")
        result = _check_config_yaml({})
        assert result.status == "critical"
        backups = list(tmp_path.glob("config.yaml.corrupt-backup-*"))
        assert len(backups) == 1


class TestRunHealthChecks:
    def test_returns_one_result_per_check(self):
        results = run_health_checks({})
        assert len(results) == 4
        assert all(isinstance(r, HealthCheckResult) for r in results)

    def test_one_check_raising_does_not_break_others(self, monkeypatch):
        # _CHECKS binds function objects at module-definition time, so
        # patching the module-level name doesn't reach it — patch a real
        # dependency inside the check instead, which is also how this would
        # actually fail in production (e.g. disk_usage erroring on a
        # platform quirk).
        def _boom(path):
            raise RuntimeError("kaboom")

        monkeypatch.setattr("shutil.disk_usage", _boom)
        results = run_health_checks({})
        assert len(results) == 4
        disk_result = next(r for r in results if r.component == "disk_space")
        assert disk_result.status == "degraded"
        assert "kaboom" in disk_result.message


class TestMonitorLifecycle:
    def test_start_and_stop(self):
        try:
            assert start_self_healing_monitor(interval_seconds=60.0) is True
            # Idempotent — calling again while running is a no-op success.
            assert start_self_healing_monitor(interval_seconds=60.0) is True
        finally:
            stop_self_healing_monitor(timeout=2.0)
