"""Tests for backend.orchestrator.dashboard — rendering and file operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.orchestrator.dashboard import (
    DashboardState,
    count_vault_files,
    render_dashboard,
    write_dashboard,
)
from backend.orchestrator.watchdog import WatcherInfo

# ── count_vault_files Tests ──────────────────────────────────────


class TestCountVaultFiles:
    def test_empty_vault(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        counts = count_vault_files(vault)
        assert all(c == 0 for c in counts.values())

    def test_counts_md_files(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "Approved").mkdir(parents=True)
        (vault / "Done").mkdir(parents=True)
        (vault / "Needs_Action").mkdir(parents=True)

        (vault / "Approved" / "a.md").write_text("test", encoding="utf-8")
        (vault / "Approved" / "b.md").write_text("test", encoding="utf-8")
        (vault / "Done" / "c.md").write_text("test", encoding="utf-8")

        counts = count_vault_files(vault)
        assert counts["Approved"] == 2
        assert counts["Done"] == 1
        assert counts["Needs_Action"] == 0

    def test_ignores_non_md_files(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        (vault / "Approved").mkdir(parents=True)
        (vault / "Approved" / "data.json").write_text("{}", encoding="utf-8")
        (vault / "Approved" / "real.md").write_text("test", encoding="utf-8")

        counts = count_vault_files(vault)
        assert counts["Approved"] == 1


# ── render_dashboard Tests ───────────────────────────────────────


class TestRenderDashboard:
    def test_basic_render(self) -> None:
        state = DashboardState(
            watchers=[
                WatcherInfo(
                    name="Gmail",
                    status="running",
                    restart_count=0,
                    last_error=None,
                    started_at="2026-02-18T09:00:00Z",
                ),
            ],
            vault_counts={"Approved": 2, "Done": 5, "Needs_Action": 1},
            dev_mode=True,
            last_update="2026-02-18T09:05:00Z",
            uptime_seconds=300,
            errors=[],
        )
        md = render_dashboard(state)
        assert "DEV MODE" in md
        assert "Gmail" in md
        assert "running" in md
        assert "Approved" in md
        assert "Last Updated" in md

    def test_production_mode_badge(self) -> None:
        state = DashboardState(dev_mode=False, last_update="2026-02-18T09:00:00Z")
        md = render_dashboard(state)
        assert "PRODUCTION" in md

    def test_errors_section(self) -> None:
        state = DashboardState(
            dev_mode=True,
            last_update="2026-02-18T09:00:00Z",
            errors=["Gmail: Token expired", "WhatsApp: Playwright not found"],
        )
        md = render_dashboard(state)
        assert "Recent Errors" in md
        assert "Token expired" in md
        assert "Playwright not found" in md

    def test_no_watchers_message(self) -> None:
        state = DashboardState(dev_mode=True, last_update="2026-02-18T09:00:00Z")
        md = render_dashboard(state)
        assert "No watchers configured" in md

    def test_uptime_formatting(self) -> None:
        state = DashboardState(dev_mode=True, last_update="now", uptime_seconds=3661)
        md = render_dashboard(state)
        assert "1h 1m" in md


# ── write_dashboard Tests ────────────────────────────────────────


class TestWriteDashboard:
    @pytest.mark.asyncio
    async def test_writes_dashboard_file(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()

        await write_dashboard(vault, "# Test Dashboard\n\nHello")

        dashboard = vault / "Dashboard.md"
        assert dashboard.exists()
        content = dashboard.read_text(encoding="utf-8")
        assert "Test Dashboard" in content

    @pytest.mark.asyncio
    async def test_overwrites_existing(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "Dashboard.md").write_text("old content", encoding="utf-8")

        await write_dashboard(vault, "new content")

        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert content == "new content"
