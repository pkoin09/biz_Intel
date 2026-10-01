"""
Centralized logging helpers.

All framework logging should go through this module.
"""

from __future__ import annotations

import logging


class FrameworkLogger:

    def __init__(self, name: str):

        self.logger = logging.getLogger(name)

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def success(self, message: str) -> None:
        """
        Alias for info().

        Reserved for future colored output.
        """
        self.logger.info(message)

    def section(
        self,
        title: str,
    ) -> None:

        self.logger.info("-" * 60)
        self.logger.info(title)
        self.logger.info("-" * 60)
