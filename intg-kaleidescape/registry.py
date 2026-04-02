"""
Registry for active Kaleidescape Player instances.

Used to store and retrieve device connections by device ID.
"""

from typing import Dict, Iterator

from device import KaleidescapePlayer

_configured_players: Dict[str, KaleidescapePlayer] = {}


def get_device(device_id: str) -> KaleidescapePlayer | None:
    """
    Retrieve the device associated with a given device ID.

    Args:
        device_id: Unique identifier for the Kaleidescape Player.

    Returns:
        The corresponding Kaleidescape Player instance, or None if not found.
    """
    return _configured_players.get(device_id)


def register_device(device_id: str, device: KaleidescapePlayer) -> None:
    """
    Register a Kaleidescape Player for a given device ID.

    Args:
        device_id: Unique identifier for the Kaleidescape Player.
        device: Kaleidescape Player instance to associate with the device.
    """
    if device_id not in _configured_players:
        _configured_players[device_id] = device


def unregister_device(device_id: str) -> None:
    """
    Remove the device associated with the given device ID.

    Args:
        device_id: Unique identifier of the device to remove.
    """
    _configured_players.pop(device_id, None)


def all_devices() -> Dict[str, KaleidescapePlayer]:
    """
    Get a dictionary of all currently registered devices.

    Returns:
        A dictionary mapping device IDs to their Kaleidescape Player instances.
    """
    return _configured_players


def clear_devices() -> None:
    """
    Remove all registered devicess from the registry.
    """
    _configured_players.clear()


async def connect_all() -> None:
    """
    Connect all registered Kaleidescape Player instances asynchronously.
    """
    for device in list(iter_devices()):
        await device.connect()


async def disconnect_all() -> None:
    """
    Disconnect all registered Kaleidescape Player instances asynchronously.
    """
    for device in list(iter_devices()):
        await device.disconnect()


def iter_devices() -> Iterator[KaleidescapePlayer]:
    """
    Yield each registered Kaleidescape Player instance.

    Returns:
        An iterator over all registered device objects.
    """
    return iter(_configured_players.values())
