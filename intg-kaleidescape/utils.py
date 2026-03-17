"""
Utility functions for logging setup and command validation in the Kaleidescape integration.

Includes:
- `setup_logger()`: Dynamically sets logging levels for UC API and related modules based on the
  `UC_LOG_LEVEL` environment variable.
- `validate_simple_commands_exist_on_executor()`: Validates that all commands defined in a given Enum
  are implemented as callables on a specified executor object. Useful for debugging and consistency checks.

These utilities support development and runtime diagnostics in UC API-based Kaleidescape integrations.
"""


import logging
import os
from enum import Enum
from typing import Type


def setup_logger():
    """Configure log levels for all integration modules.

    Third-party libraries (ucapi, pykaleidescape) are left unconfigured:
    - ucapi uses NullHandler, so it's silent unless explicitly enabled.
    - pykaleidescape inherits WARNING from the root logger.
    """
    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()

    for name in (
        "driver", "config", "discover", "setup_flow",
        "device", "remote", "media_player", "registry", "utils",
    ):
        logging.getLogger(name).setLevel(level)

    # Uncomment for troubleshooting underlying libraries:
    # logging.getLogger("ucapi").setLevel(logging.DEBUG)
    # logging.getLogger("kaleidescape").setLevel(logging.DEBUG)



def validate_simple_commands_exist_on_executor(
    enum_class: Type[Enum],
    executor: object,
    logger: logging.Logger = logging.getLogger(__name__)
) -> list[str]:
    """
    Ensures that each command in the enum resolves to a callable method on the executor,
    using getattr(), which also triggers __getattr__ fallbacks.

    :param enum_class: Enum containing command names.
    :param executor: The CommandExecutor instance.
    :param logger: Logger for output.
    :return: List of commands that failed resolution.
    """
    missing = []

    for cmd in enum_class:
        method_name = cmd.value.lower()
        try:
            method = getattr(executor, method_name)
            if not callable(method):
                missing.append(method_name)
        except AttributeError:
            missing.append(method_name)

    if missing:
        logger.warning(
            "Executor missing methods for SimpleCommands: %s", ", ".join(missing)
        )
    else:
        logger.debug("All SimpleCommands are implemented by the executor.")

    return missing

def normalize_cmd(cmd: str) -> str:
    """Normalize the cmd"""
    return cmd.lower().replace(" / ", "_").replace(" ", "_").replace("ok", "select")
