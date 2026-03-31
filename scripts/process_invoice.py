"""Process approved Odoo invoices through the ActionExecutor.

This script:
1. Reads all odoo_invoice files in vault/Approved/
2. Ensures the customer exists in Odoo (creates if missing)
3. Runs the ActionExecutor to create invoices and move files to Done
"""

import asyncio
import logging
import os
import xmlrpc.client
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _get_odoo_connection():
    """Connect and authenticate to Odoo. Returns (uid, models proxy)."""
    url = os.getenv("ODOO_URL", "http://localhost:8069")
    db = os.getenv("ODOO_DATABASE", "ai_employee")
    username = os.getenv("ODOO_USERNAME", "")
    api_key = os.getenv("ODOO_API_KEY", "")

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, api_key, {})
    if not uid:
        raise ConnectionError(
            "Odoo auth failed — check ODOO_USERNAME and ODOO_API_KEY in config/.env"
        )
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return uid, models, db, api_key


def ensure_customers_exist(vault_path: str):
    """Scan vault/Approved/ for odoo_invoice files and create missing customers."""
    from backend.utils.frontmatter import extract_frontmatter

    uid, models, db, api_key = _get_odoo_connection()

    approved_dir = Path(vault_path) / "Approved"
    if not approved_dir.exists():
        return

    for md_file in approved_dir.glob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        fm, _ = extract_frontmatter(content)
        if not fm or fm.get("type") != "odoo_invoice":
            continue

        customer_id = fm.get("customer_id")
        customer_name = fm.get("customer_name", "Unknown")
        if not customer_id:
            continue

        # Check if customer exists
        existing = models.execute_kw(
            db, uid, api_key, "res.partner", "search_read",
            [[["id", "=", int(customer_id)]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if existing:
            logger.info(
                "Customer %d exists: %s", customer_id, existing[0]["name"]
            )
        else:
            new_id = models.execute_kw(
                db, uid, api_key, "res.partner", "create",
                [{"name": customer_name, "is_company": False, "customer_rank": 1}],
            )
            logger.info(
                "Created customer '%s' with id=%d (expected id=%d)",
                customer_name, new_id, customer_id,
            )
            if new_id != int(customer_id):
                logger.warning(
                    "Customer ID mismatch! Odoo assigned id=%d but file has customer_id=%d. "
                    "Updating the file...",
                    new_id, customer_id,
                )
                from backend.utils.frontmatter import update_frontmatter
                update_frontmatter(md_file, {"customer_id": new_id})


async def process_approved():
    """Run one cycle of the ActionExecutor."""
    from backend.orchestrator.action_executor import ActionExecutor
    from backend.orchestrator.orchestrator import OrchestratorConfig

    config = OrchestratorConfig.from_env()
    executor = ActionExecutor(config)

    logger.info("Scanning vault/Approved/ ...")
    files = executor._scan_approved()
    logger.info("Found %d file(s) to process", len(files))

    for file_path, fm in files:
        logger.info("Processing: %s (type=%s)", file_path.name, fm.get("type"))
        success = await executor.process_file(file_path, fm)
        if success:
            logger.info("SUCCESS — %s → vault/Done/", file_path.name)
        else:
            logger.error("FAILED — %s still in vault/Approved/", file_path.name)

    # Show final state
    vault = Path(config.vault_path)
    approved = list((vault / "Approved").glob("*.md"))
    done = list((vault / "Done").glob("ODOO_*.md"))
    logger.info("--- Final State ---")
    logger.info("vault/Approved/: %d file(s)", len(approved))
    logger.info("vault/Done/ (Odoo): %d file(s)", len(done))
    for f in done:
        logger.info("  %s", f.name)


if __name__ == "__main__":
    vault = os.getenv("VAULT_PATH", "./vault")

    print("Step 1: Ensuring customers exist in Odoo...")
    ensure_customers_exist(vault)

    print("\nStep 2: Processing approved files...")
    asyncio.run(process_approved())
