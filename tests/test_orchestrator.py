"""Tests for backend.orchestrator.orchestrator — lifecycle, lock file, config."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.orchestrator.orchestrator import (
    OrchestratorConfig,
    acquire_lock,
    is_process_alive,
    release_lock,
)

# ── OrchestratorConfig Tests ─────────────────────────────────────


class TestOrchestratorConfig:
    def test_defaults(self) -> None:
        config = OrchestratorConfig()
        assert config.vault_path == "./vault"
        assert config.check_interval == 30
        assert config.dashboard_interval == 300
        assert config.max_restart_attempts == 3
        assert config.dev_mode is True
        assert config.dry_run is False

    def test_from_env(self) -> None:
        env = {
            "VAULT_PATH": "/tmp/testvault",
            "ORCHESTRATOR_CHECK_INTERVAL": "15",
            "ORCHESTRATOR_DASHBOARD_UPDATE_INTERVAL": "60",
            "ORCHESTRATOR_MAX_RESTART_ATTEMPTS": "5",
            "DEV_MODE": "false",
            "DRY_RUN": "true",
            "LOG_LEVEL": "DEBUG",
        }
        with patch.dict(os.environ, env, clear=False):
            config = OrchestratorConfig.from_env()
        assert config.vault_path == "/tmp/testvault"
        assert config.check_interval == 15
        assert config.dashboard_interval == 60
        assert config.max_restart_attempts == 5
        assert config.dev_mode is False
        assert config.dry_run is True
        assert config.log_level == "DEBUG"


# ── Lock File Tests ──────────────────────────────────────────────


class TestLockFile:
    def test_acquire_creates_lock(self, tmp_path: Path) -> None:
        lock = tmp_path / "test.lock"
        result = acquire_lock(lock)
        assert result is True
        assert lock.exists()
        content = lock.read_text(encoding="utf-8")
        assert f"PID: {os.getpid()}" in content

    def test_acquire_fails_if_pid_alive(self, tmp_path: Path) -> None:
        lock = tmp_path / "test.lock"
        # Write current PID (which IS alive)
        lock.write_text(f"PID: {os.getpid()}\nSTARTED: 2026-01-01T00:00:00Z\n", encoding="utf-8")
        result = acquire_lock(lock)
        assert result is False

    def test_acquire_overwrites_stale_lock(self, tmp_path: Path) -> None:
        lock = tmp_path / "test.lock"
        # Write a PID that doesn't exist (99999999)
        lock.write_text("PID: 99999999\nSTARTED: 2026-01-01T00:00:00Z\n", encoding="utf-8")
        result = acquire_lock(lock)
        assert result is True
        content = lock.read_text(encoding="utf-8")
        assert f"PID: {os.getpid()}" in content

    def test_release_deletes_lock(self, tmp_path: Path) -> None:
        lock = tmp_path / "test.lock"
        lock.write_text("PID: 1234\n", encoding="utf-8")
        release_lock(lock)
        assert not lock.exists()

    def test_release_nonexistent_is_noop(self, tmp_path: Path) -> None:
        lock = tmp_path / "nonexistent.lock"
        release_lock(lock)  # Should not raise


# ── is_process_alive Tests ───────────────────────────────────────


class TestIsProcessAlive:
    def test_current_process_is_alive(self) -> None:
        assert is_process_alive(os.getpid()) is True

    def test_nonexistent_pid(self) -> None:
        assert is_process_alive(99999999) is False


# ── Vault Directory Initialization ───────────────────────────────


class TestEnsureVaultDirs:
    @pytest.mark.asyncio
    async def test_creates_missing_dirs(self, tmp_path: Path) -> None:
        from backend.orchestrator.orchestrator import Orchestrator

        config = OrchestratorConfig(vault_path=str(tmp_path / "vault"))
        orch = Orchestrator(config)
        orch._ensure_vault_dirs()

        assert (tmp_path / "vault" / "Approved").is_dir()
        assert (tmp_path / "vault" / "Done").is_dir()
        assert (tmp_path / "vault" / "Needs_Action").is_dir()
        assert (tmp_path / "vault" / "Logs" / "actions").is_dir()
