"""Data collectors for the CEO Briefing Generator.

One static method per data source (7 sources total). Each method returns its
entity type or a safe default. Errors are returned as (None, error_str) tuples
or empty lists — never raised — so the briefing can be generated with partial data.

Sources:
    1. Odoo financial data (via OdooClient)
    2. vault/Done/ completed tasks
    3. vault/Needs_Action/ + vault/Pending_Approval/ pending items
    4. vault/Logs/actions/ communication summary
    5. vault/Business_Goals.md goals and targets
    6. Bottleneck detection (derived from collected data)
    7. Proactive suggestion generation (derived from collected data)
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.briefing import (
    BottleneckEntry,
    BusinessGoals,
    CommunicationSummary,
    CompletedTask,
    Deadline,
    FinancialSnapshot,
    KeyResult,
    PendingItem,
)
from backend.utils.frontmatter import extract_frontmatter
from backend.utils.logging_utils import read_logs_for_date
from backend.utils.timestamps import parse_iso

logger = logging.getLogger(__name__)

# ── Action type categorization ──────────────────────────────────────────────

# System events excluded from communication counts
_SYSTEM_PREFIXES = (
    "orchestrator_",
    "watcher_",
    "briefing_",
    "dashboard_",
    "scheduler_",
)

# Confirmed action_type prefix → communication category mapping (research.md Decision 6)
_ACTION_CATEGORIES: list[tuple[str, str]] = [
    ("email_detected", "emails_processed"),
    ("email_processed", "emails_processed"),
    ("send_email", "emails_processed"),
    ("email_send", "emails_processed"),
    ("email_reply", "emails_processed"),
    ("whatsapp_processed", "whatsapp_flagged"),
    ("whatsapp_", "whatsapp_flagged"),
    ("linkedin_processed", "linkedin_flagged"),
    ("twitter_post_published", "social_posts_published"),
    ("linkedin_post", "social_posts_published"),
    ("facebook_post_published", "social_posts_published"),
    ("instagram_post_published", "social_posts_published"),
    ("social_post", "social_posts_published"),
]


def _categorize_action(action_type: str) -> str | None:
    """Map an action_type string to a CommunicationSummary field name.

    Returns None for system events or unrecognised action types.
    Uses prefix matching for forward-compatibility.
    """
    if not action_type:
        return None

    # Exclude system events first
    for prefix in _SYSTEM_PREFIXES:
        if action_type.startswith(prefix):
            return None

    # Category matching (ordered — most specific first)
    for prefix, category in _ACTION_CATEGORIES:
        if action_type.startswith(prefix):
            return category

    return None  # Unknown — excluded from counts


def _get_file_date(fm: dict, path: Path) -> datetime:
    """Extract datetime from frontmatter or fall back to file mtime."""
    ts_value = fm.get("completed_at") or fm.get("generated_at") or fm.get("approved_at")
    if ts_value:
        try:
            return parse_iso(str(ts_value))
        except (ValueError, TypeError):
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _extract_h1_title(body: str) -> str | None:
    """Extract the first H1 heading from a Markdown body."""
    match = re.search(r"^#\s+(.+)", body, re.MULTILINE)
    return match.group(1).strip() if match else None


# ── Collector: Financial (T006) ─────────────────────────────────────────────


class DataCollectors:
    """Static collector methods — one per data source."""

    @staticmethod
    def collect_financial(
        dev_mode: bool,
        period_start: date,
        period_end: date,
        monthly_target: float | None = None,
    ) -> tuple[FinancialSnapshot | None, str | None]:
        """Collect financial data from Odoo for the review period.

        Args:
            dev_mode: When True, use mock Odoo data without network calls.
            period_start: Start of review period.
            period_end: End of review period (inclusive).
            monthly_target: Optional revenue target from Business_Goals.md.

        Returns:
            (FinancialSnapshot, None) on success.
            (None, error_str) on any failure.
        """
        try:
            from backend.mcp_servers.odoo.odoo_client import OdooClient

            odoo = OdooClient(
                url=os.getenv("ODOO_URL", "http://localhost:8069"),
                db=os.getenv("ODOO_DATABASE", "ai_employee"),
                username=os.getenv("ODOO_USERNAME", ""),
                api_key=os.getenv("ODOO_API_KEY", ""),
                dev_mode=dev_mode,
            )
            odoo.authenticate()

            # Fetch all posted invoices
            all_invoices = odoo.list_invoices(limit=100, status="posted")

            # Filter for weekly period
            period_invoices = []
            for inv in all_invoices:
                inv_date_str = inv.get("invoice_date", "")
                if not inv_date_str:
                    continue
                try:
                    inv_date = date.fromisoformat(str(inv_date_str))
                except (ValueError, TypeError):
                    continue
                if period_start <= inv_date <= period_end:
                    period_invoices.append(inv)

            weekly_revenue = sum(float(inv.get("amount_total", 0)) for inv in period_invoices)

            # MTD revenue: from 1st of period_end's month to period_end
            month_start = period_end.replace(day=1)
            mtd_invoices = [
                inv for inv in all_invoices
                if inv.get("invoice_date") and
                month_start <= date.fromisoformat(str(inv["invoice_date"])) <= period_end
            ]
            mtd_revenue = sum(float(inv.get("amount_total", 0)) for inv in mtd_invoices)

            # Outstanding invoices (posted, not fully paid)
            outstanding = [
                inv for inv in all_invoices
                if inv.get("payment_status") not in ("paid",)
            ]
            outstanding_total = sum(float(inv.get("amount_total", 0)) for inv in outstanding)

            # Payments received in period (from transactions)
            try:
                transactions = odoo.list_transactions(
                    date_from=period_start.isoformat(),
                    date_to=period_end.isoformat(),
                )
                payments = [
                    t for t in transactions
                    if float(t.get("debit", 0)) > 0
                    and "payment" in (t.get("description") or "").lower()
                ]
                payments_total = sum(float(t.get("debit", 0)) for t in payments)
                payments_count = len(payments)
            except Exception:
                payments_total = 0.0
                payments_count = 0

            # Bank balance
            try:
                account_id = int(os.getenv("ODOO_MAIN_ACCOUNT_ID", "13"))
                balance_data = odoo.get_account_balance(account_id)
                bank_balance = float(balance_data.get("balance", 0))
            except Exception:
                bank_balance = 0.0

            # Currency
            currency = period_invoices[0].get("currency", "USD") if period_invoices else "USD"

            # MTD percent of target
            mtd_pct: float | None = None
            if monthly_target and monthly_target > 0:
                mtd_pct = (mtd_revenue / monthly_target) * 100

            snapshot = FinancialSnapshot(
                weekly_revenue=weekly_revenue,
                mtd_revenue=mtd_revenue,
                monthly_target=monthly_target,
                mtd_pct_of_target=mtd_pct,
                outstanding_invoices_count=len(outstanding),
                outstanding_invoices_total=outstanding_total,
                payments_received_count=payments_count,
                payments_received_total=payments_total,
                bank_balance=bank_balance,
                currency=currency,
            )
            return snapshot, None

        except Exception as exc:
            logger.warning("Financial data collection failed: %s", exc)
            return None, str(exc)

    # ── Collector: Completed Tasks (T007) ───────────────────────────────────

    @staticmethod
    def collect_completed_tasks(
        vault_path: Path,
        period_start: date,
        period_end: date,
    ) -> list[CompletedTask]:
        """Collect completed tasks from vault/Done/ within the review period.

        Args:
            vault_path: Path to vault root.
            period_start: Start of review period (inclusive).
            period_end: End of review period (inclusive).

        Returns:
            List of CompletedTask, sorted by completion time ascending.
        """
        done_dir = vault_path / "Done"
        if not done_dir.exists():
            return []

        tasks: list[CompletedTask] = []
        for md_file in done_dir.glob("*.md"):
            if md_file.name.startswith("."):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                fm, body = extract_frontmatter(content)
                completed_at = _get_file_date(fm, md_file)
                if not (period_start <= completed_at.date() <= period_end):
                    continue
                title = _extract_h1_title(body) or md_file.stem
                tasks.append(CompletedTask(
                    title=title,
                    completed_at=completed_at,
                    completed_date=completed_at.date().isoformat(),
                    task_type=str(fm.get("type", "unknown")),
                    source_file=md_file.name,
                ))
            except Exception as exc:
                logger.debug("Skipping Done/ file %s: %s", md_file.name, exc)

        return sorted(tasks, key=lambda t: t.completed_at)

    # ── Collector: Pending Items (T008) ─────────────────────────────────────

    @staticmethod
    def collect_pending_items(vault_path: Path) -> list[PendingItem]:
        """Collect pending items from vault/Needs_Action/ and vault/Pending_Approval/.

        Age is calculated using file mtime — NOT the `received` frontmatter field,
        which is RFC 2822 format and not parseable with parse_iso().

        Args:
            vault_path: Path to vault root.

        Returns:
            List of PendingItem sorted by age descending (oldest first).
        """
        today = date.today()
        items: list[PendingItem] = []

        for folder_name in ("Needs_Action", "Pending_Approval"):
            folder = vault_path / folder_name
            if not folder.exists():
                continue
            for md_file in folder.glob("*.md"):
                if md_file.name.startswith("."):
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                    fm, body = extract_frontmatter(content)

                    # Use mtime for age — received field is RFC 2822, not ISO 8601
                    mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=UTC)
                    age_days = (today - mtime.date()).days

                    title = (
                        str(fm.get("subject") or "")
                        or _extract_h1_title(body)
                        or md_file.stem
                    )

                    items.append(PendingItem(
                        title=title,
                        item_type=str(fm.get("type", "unknown")),
                        priority=str(fm.get("priority", "medium")),
                        vault_folder=folder_name,
                        created_at=mtime,
                        age_days=age_days,
                        source_file=md_file.name,
                    ))
                except Exception as exc:
                    logger.debug("Skipping %s/%s: %s", folder_name, md_file.name, exc)

        return sorted(items, key=lambda i: i.age_days, reverse=True)

    # ── Collector: Communication Summary (T009) ─────────────────────────────

    @staticmethod
    def collect_communication_summary(
        vault_path: Path,
        period_start: date,
        period_end: date,
    ) -> CommunicationSummary:
        """Aggregate communication action counts from vault/Logs/actions/*.json.

        Iterates each date in the period and calls read_logs_for_date(). Uses
        prefix-matching on action_type to categorize events.

        Args:
            vault_path: Path to vault root.
            period_start: Start of period.
            period_end: End of period (inclusive).

        Returns:
            CommunicationSummary with counts per category.
        """
        log_dir = vault_path / "Logs" / "actions"
        counts: dict[str, int] = defaultdict(int)
        total_non_system = 0

        current = period_start
        while current <= period_end:
            try:
                entries = read_logs_for_date(log_dir, current.isoformat())
                for entry in entries:
                    action_type = entry.get("action_type", "")
                    category = _categorize_action(action_type)
                    if category:
                        counts[category] += 1
                        total_non_system += 1
            except Exception as exc:
                logger.debug("Could not read logs for %s: %s", current.isoformat(), exc)
            current += timedelta(days=1)

        return CommunicationSummary(
            emails_processed=counts.get("emails_processed", 0),
            whatsapp_flagged=counts.get("whatsapp_flagged", 0),
            linkedin_flagged=counts.get("linkedin_flagged", 0),
            social_posts_published=counts.get("social_posts_published", 0),
            total_actions=total_non_system,
        )

    # ── Collector: Business Goals (T010) ────────────────────────────────────

    @staticmethod
    def collect_business_goals(vault_path: Path) -> BusinessGoals | None:
        """Parse vault/Business_Goals.md for revenue targets and KPIs.

        Returns None if the file is absent or all target values are placeholders.

        Args:
            vault_path: Path to vault root.

        Returns:
            BusinessGoals instance or None.
        """
        goals_file = vault_path / "Business_Goals.md"
        if not goals_file.exists():
            return None

        try:
            content = goals_file.read_text(encoding="utf-8")
        except OSError:
            return None

        if not content.strip():
            return None

        monthly_revenue_target: float | None = None
        new_clients_target: int | None = None
        key_results: list[KeyResult] = []
        upcoming_deadlines: list[Deadline] = []

        # Parse Revenue Targets table rows
        # Format: | Metric | Target | Current | Gap |
        table_rows = re.findall(
            r"\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|",
            content,
        )
        for cols in table_rows:
            metric = cols[0].strip()
            target = cols[1].strip()
            current_val = cols[2].strip()

            # Skip header rows and separator rows
            if not metric or metric.lower() in ("metric", "---", "key result", "result"):
                continue
            if set(target) <= {"-", " ", "|"}:
                continue

            # Detect placeholder values
            is_placeholder = "[" in target or "$[" in target or not target or target == "N/A"

            if "revenue" in metric.lower() or "mrr" in metric.lower():
                if not is_placeholder:
                    # Extract numeric value (strip currency symbols, commas)
                    numeric_str = re.sub(r"[^\d.]", "", target)
                    if numeric_str:
                        try:
                            monthly_revenue_target = float(numeric_str)
                        except ValueError:
                            pass
            elif "client" in metric.lower() or "customer" in metric.lower():
                if not is_placeholder:
                    numeric_str = re.sub(r"[^\d]", "", target)
                    if numeric_str:
                        try:
                            new_clients_target = int(numeric_str)
                        except ValueError:
                            pass

            # Only collect non-placeholder rows as key results
            if not is_placeholder:
                key_results.append(KeyResult(
                    metric=metric,
                    target=target,
                    current=current_val,
                ))

        # Parse Key Initiatives / deadlines (lines with dates)
        deadline_pattern = re.compile(
            r"\|\s*([^|]+?)\s*\|\s*(\d{4}-\d{2}-\d{2}[^|]*)\s*\|"
        )
        for match in deadline_pattern.finditer(content):
            initiative = match.group(1).strip()
            deadline_str = match.group(2).strip()
            if initiative and deadline_str and initiative.lower() not in ("initiative", "task", "item", "---"):
                upcoming_deadlines.append(Deadline(
                    initiative=initiative,
                    deadline=deadline_str,
                ))

        # Return None if nothing useful was parsed
        if (
            monthly_revenue_target is None
            and new_clients_target is None
            and not key_results
        ):
            return None

        return BusinessGoals(
            monthly_revenue_target=monthly_revenue_target,
            new_clients_target=new_clients_target,
            key_results=key_results[:10],  # cap at 10 rows
            upcoming_deadlines=upcoming_deadlines[:5],
            raw_text=content[:1000],
        )

    # ── Detector: Bottlenecks (T011) ────────────────────────────────────────

    @staticmethod
    def detect_bottlenecks(
        pending_items: list[PendingItem],
        communication: CommunicationSummary,
        completed_tasks: list[CompletedTask],
    ) -> list[BottleneckEntry]:
        """Detect bottlenecks from pending items and communication patterns.

        Rules:
        1. Age-based: Any PendingItem with age_days >= 2 is a bottleneck.
        2. Frequency-based: Any action prefix appearing 3+ times without
           corresponding completions is flagged.
        3. Pattern-based: Zero completed tasks despite active pending items.

        Args:
            pending_items: Collected pending items.
            communication: Communication summary.
            completed_tasks: Completed tasks in period.

        Returns:
            List of BottleneckEntry, ordered by severity (age_days desc).
        """
        bottlenecks: list[BottleneckEntry] = []

        # Rule 1: Age-based bottlenecks (48h = 2 days threshold)
        aged_items = [i for i in pending_items if i.age_days >= 2]
        for item in sorted(aged_items, key=lambda x: x.age_days, reverse=True):
            bottlenecks.append(BottleneckEntry(
                item=item.title,
                reason=f"Waiting {item.age_days} days in {item.vault_folder}",
                age_days=item.age_days,
                bottleneck_type="age",
            ))

        # Rule 2: Frequency-based (too many items of same type with no resolution)
        type_counts: dict[str, int] = defaultdict(int)
        for item in pending_items:
            if item.item_type and item.item_type != "unknown":
                type_counts[item.item_type] += 1

        for item_type, count in type_counts.items():
            if count >= 3:
                bottlenecks.append(BottleneckEntry(
                    item=f"{count}x {item_type} items pending",
                    reason=f"{count} items of type '{item_type}' unresolved",
                    frequency=count,
                    bottleneck_type="frequency",
                ))

        # Rule 3: Pattern — no completed tasks despite pending items
        if not completed_tasks and pending_items:
            bottlenecks.append(BottleneckEntry(
                item="No tasks completed this period",
                reason="Zero tasks moved to Done/ despite active pending items — possible workflow blockage",
                bottleneck_type="pattern",
            ))

        return bottlenecks

    # ── Generator: Suggestions (T011) ───────────────────────────────────────

    @staticmethod
    def generate_suggestions(
        pending_items: list[PendingItem],
        communication: CommunicationSummary,
        financial: FinancialSnapshot | None,
        business_goals: BusinessGoals | None,
        bottlenecks: list[BottleneckEntry],
    ) -> list[str]:
        """Generate actionable proactive suggestions based on observed patterns.

        Always returns at least one suggestion.

        Args:
            pending_items: Current pending items.
            communication: Communication summary.
            financial: Financial snapshot (may be None).
            business_goals: Business goals (may be None).
            bottlenecks: Detected bottlenecks.

        Returns:
            List of suggestion strings (at least 1).
        """
        suggestions: list[str] = []

        # Suggestion: Handle aged pending items
        old_items = [i for i in pending_items if i.age_days >= 3]
        if old_items:
            oldest = old_items[0]
            suggestions.append(
                f"Review '{oldest.title}' — it has been waiting {oldest.age_days} days "
                f"in {oldest.vault_folder}. Consider actioning or archiving."
            )

        # Suggestion: Financial trend
        if financial:
            if financial.trend == "Behind":
                suggestions.append(
                    f"Revenue is behind target ({financial.mtd_pct_of_target:.0f}% of monthly goal). "
                    "Consider reviewing outstanding invoices and following up on payments."
                )
            elif financial.outstanding_invoices_count > 0:
                suggestions.append(
                    f"Follow up on {financial.outstanding_invoices_count} outstanding "
                    f"invoice(s) totalling {financial.currency} "
                    f"{financial.outstanding_invoices_total:,.2f}."
                )

        # Suggestion: Social media consistency
        if communication.social_posts_published == 0:
            suggestions.append(
                "No social media posts were published this week. "
                "Consider running the content scheduler: "
                "`python -m backend.scheduler.content_scheduler --generate-now`"
            )

        # Suggestion: Upcoming deadlines from business goals
        if business_goals and business_goals.upcoming_deadlines:
            next_deadline = business_goals.upcoming_deadlines[0]
            suggestions.append(
                f"Upcoming deadline: '{next_deadline.initiative}' — {next_deadline.deadline}. "
                "Ensure milestones are on track."
            )

        # Suggestion: No goals configured
        if business_goals is None:
            suggestions.append(
                "Business goals are not yet configured. "
                "Add `vault/Business_Goals.md` to enable KPI tracking and target comparisons."
            )

        # Frequency bottlenecks
        for bottleneck in bottlenecks:
            if bottleneck.bottleneck_type == "frequency":
                suggestions.append(
                    f"High volume of pending {bottleneck.item} — "
                    "consider batching or automating the resolution workflow."
                )
                break  # One suggestion per category

        # Fallback: always at least one suggestion
        if not suggestions:
            suggestions.append(
                "System is operating normally. No critical issues detected this week."
            )

        return suggestions[:5]  # Cap at 5 suggestions
