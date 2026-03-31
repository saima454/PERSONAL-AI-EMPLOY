"""Abstract base class for all perception layer watchers."""

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseWatcher(ABC):
    """Base class for watchers that poll external sources and create vault action files.

    Subclasses must implement:
        - check_for_updates() -> list of new items
        - create_action_file(item) -> Path to created file
    """

    def __init__(self, vault_path: str, check_interval: int = 60):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.logs_path = self.vault_path / "Logs"
        self.check_interval = check_interval
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def check_for_updates(self) -> list[dict[str, Any]]:
        """Return list of new items to process."""

    @abstractmethod
    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        """Create .md file in Needs_Action folder. Returns the file path or None."""

    async def run(self) -> None:
        """Main polling loop. Override for custom behavior."""
        self.logger.info("Starting %s", self.__class__.__name__)
        while True:
            try:
                items = await self.check_for_updates()
                for item in items:
                    await self.create_action_file(item)
            except Exception:
                self.logger.exception("Error in %s", self.__class__.__name__)
            await asyncio.sleep(self.check_interval)
