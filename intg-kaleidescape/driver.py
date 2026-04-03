#!/usr/bin/env python3
"""Kaleidescape Remote Two/3 Integration Driver."""

import logging
from typing import Any

import config
import ucapi
from api import api, loop
from device import Events, KaleidescapeInfo, KaleidescapePlayer
from media_player import KaleidescapeMediaPlayer
from registry import (all_devices, clear_devices, connect_all, disconnect_all,
                      get_device, register_device, unregister_device)
from remote import REMOTE_STATE_MAPPING, KaleidescapeRemote
from setup_flow import driver_setup_handler
from ucapi.media_player import Attributes as MediaAttr
from ucapi.media_player import States
from utils import setup_logger

_LOG = logging.getLogger("driver")


@api.listens_to(ucapi.Events.CONNECT)
async def on_connect() -> None:
    """Connect all configured receivers when the Remote Two sends the connect command."""
    _LOG.info("Received connect event message from remote")
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)
    loop.create_task(connect_all())


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_r2_disconnect() -> None:
    """Disconnect notification from the Remote Two."""

    _LOG.info("Received disconnect event message from remote")
    await api.set_device_state(ucapi.DeviceStates.DISCONNECTED)
    loop.create_task(disconnect_all())


@api.listens_to(ucapi.Events.ENTER_STANDBY)
async def on_r2_enter_standby() -> None:
    """
    Enter standby notification from Remote Two.

    Disconnect every Kaleidescape instance.
    """

    _LOG.debug("Enter standby event: disconnecting device(s)")
    loop.create_task(disconnect_all())


@api.listens_to(ucapi.Events.EXIT_STANDBY)
async def on_r2_exit_standby() -> None:
    """
    Exit standby notification from Remote Two.

    Connect all Kaleidescape instances.
    """

    _LOG.debug("Exit standby event: connecting device(s)")
    loop.create_task(connect_all())


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """
    Subscribe to given entities.

    :param entity_ids: entity identifiers.
    """
    _LOG.debug("Subscribe entities event: %s", entity_ids)

    if not entity_ids:
        return

    # Assume all entities share the same device
    first_entity = api.configured_entities.get(entity_ids[0])
    if not first_entity:
        _LOG.error("First entity %s not found in configured_entities", entity_ids[0])
        return

    device_id = config.extract_device_id(first_entity)
    device = get_device(device_id)

    if not device:
        fallback_device = config.devices.get(device_id)
        if fallback_device:
            _configure_new_kaleidescape(fallback_device, connect=True)
        else:
            _LOG.error("Failed to subscribe entities: no Kaleidescape configuration found for %s", device_id)
        return

    # After reconfigure the Remote won't send a new connect event (it's
    # already connected), but the device was recreated without connecting.
    # Kick off a connect so state eventually resolves from UNAVAILABLE.
    if not device._connected:
        loop.create_task(device.connect())

    for entity_id in entity_ids:
        _LOG.debug("entity id = %s", entity_id)
        entity = api.configured_entities.get(entity_id)
        if not entity:
            continue

        # Handle media_player or remote entities
        _update_entity_attributes(entity_id, entity, device.attributes)


def _update_entity_attributes(entity_id: str, entity, attributes: dict):
    """
    Update attributes for the given entity based on its type.
    """
    _LOG.debug("Updating %s for %s", entity, attributes)
    if isinstance(entity, KaleidescapeMediaPlayer):
        api.configured_entities.update_attributes(entity_id, attributes)
    elif isinstance(entity, KaleidescapeRemote):
        api.configured_entities.update_attributes(
            entity_id,
            {
                ucapi.remote.Attributes.STATE:
                REMOTE_STATE_MAPPING.get(attributes.get(MediaAttr.STATE, States.UNKNOWN))
            }
        )

@api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """On unsubscribe, disconnect devices only if no other entities are using them."""
    _LOG.debug("Unsubscribe entities event: %s", entity_ids)

    # Collect devices associated with the entities being unsubscribed
    devices_to_remove = {
        config.extract_device_id(api.configured_entities.get(entity_id))
        for entity_id in entity_ids
        if api.configured_entities.get(entity_id)
    }

    # Check other remaining entities to see if they still use these devices
    remaining_entities = [
        e for e in api.configured_entities.get_all()
        if e.get("entity_id") not in entity_ids
    ]

    for entity in remaining_entities:
        device_id = config.extract_device_id(entity)
        devices_to_remove.discard(device_id)  # discard safely removes if present

    # Disconnect and clean up devices no longer in use
    for device_id in devices_to_remove:
        if device_id in all_devices():
            device = get_device(device_id)
            if device is None:
                continue
            await device.disconnect()
            device.events.remove_all_listeners()
            unregister_device(device_id)

def _configure_new_kaleidescape(info: KaleidescapeInfo, connect: bool = False) -> None:
    """
    Create and configure a new Kaleidescape device.

    If a device already exists for the given device ID, reuse it.
    Otherwise, create and register a new one.

    :param info: The Kaleidescape device configuration.
    :param connect: Whether to initiate connection immediately.
    """

    async def _reconfigure_existing_device(device: KaleidescapePlayer) -> None:
        try:
            await device.disconnect()
        except Exception as err:
            _LOG.error("Failed to disconnect during reconfigure: %s", err)
        if connect:
            await device.connect()

    device = get_device(info.id)
    if device:
        loop.create_task(_reconfigure_existing_device(device))
    else:
        device = KaleidescapePlayer(info.host, device_id=info.id)

        device.events.on(Events.CONNECTED.name, on_kaleidescape_connected)
        device.events.on(Events.DISCONNECTED.name, on_kaleidescape_disconnected)
        device.events.on(Events.UPDATE.name, on_kaleidescape_update)

        register_device(info.id, device)

        if connect:
            loop.create_task(device.connect())

    _register_available_entities(info, device)

def _register_available_entities(info: KaleidescapeInfo, device: KaleidescapePlayer) -> None:
    """
    Register remote and media player entities for a Kaleidescape device and associate its device.

    :param info: Kaleidescape configuration
    :param device: Active KaleidescapeDevice for the device
    """
    for entity_cls in (KaleidescapeMediaPlayer, KaleidescapeRemote):
        entity = entity_cls(info, device)
        if api.available_entities.contains(entity.id):
            api.available_entities.remove(entity.id)
        api.available_entities.add(entity)

async def on_kaleidescape_connected(device_id: str) -> None:
    """Handle Kaleidescape connection events."""
    _LOG.debug("Kaleidescape connected: %s", device_id)
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)

async def on_kaleidescape_disconnected(device_id: str) -> None:
    """Handle Kaleidescape disconnection events."""
    _LOG.debug("Kaleidescape disconnected: %s", device_id)

    any_connected = any(
        device is not None and getattr(device, "_connected", False)
        for device in all_devices().values()
    )

    await api.set_device_state(
        ucapi.DeviceStates.CONNECTED
        if any_connected
        else ucapi.DeviceStates.DISCONNECTED
    )

async def on_kaleidescape_update(entity_id: str, update: dict[str, Any] | None) -> None:
    """
    Update attributes of configured media-player or remote entity if device attributes changed.

    :param device_id: Device identifier.
    :param update: Dictionary containing the updated attributes or None.
    """
    if update is None:
        return

    device_id = entity_id.split(".", 1)[1]
    device = get_device(device_id)
    if device is None:
        return

    _LOG.debug("[%s] Kaleidescape update: %s", device_id, update)

    entity: KaleidescapeMediaPlayer | KaleidescapeRemote | None = api.configured_entities.get(entity_id)
    if entity is None:
        _LOG.debug("Entity %s not found", entity_id)
        return

    changed_attrs = entity.filter_changed_attributes(update)
    if changed_attrs:
        _LOG.debug("Changed Attrs: %s, %s", entity_id, changed_attrs)
        api_update_attributes = api.configured_entities.update_attributes(entity_id, changed_attrs)
        _LOG.debug("api_update_attributes = %s", api_update_attributes)
    else:
        _LOG.debug("attributes not changed")

def on_player_added(player_info: KaleidescapeInfo) -> None:
    """Handle a newly added player in the configuration."""
    _LOG.debug("New Kaleidescape Player added: %s", player_info)
    _configure_new_kaleidescape(player_info, connect=False)

def on_player_removed(player_info: KaleidescapeInfo | None) -> None:
    """Handle removal of a Kaleidescape Player from config."""
    if player_info is None:
        _LOG.info("All devices cleared from config.")
        for device in list(all_devices().values()):
            loop.create_task(_async_remove(device))
        clear_devices()
        api.configured_entities.clear()
        api.available_entities.clear()
        return

    device = get_device(player_info.id)
    if device:
        unregister_device(player_info.id)
        loop.create_task(_async_remove(device))
        api.configured_entities.remove(f"media_player.{player_info.id}")
        api.configured_entities.remove(f"remote.{player_info.id}")
        _LOG.info("Device for device_id %s cleaned up", player_info.id)
    else:
        _LOG.debug("No Device found for removed device %s", player_info.id)

async def _async_remove(device: KaleidescapePlayer) -> None:
    """Disconnect from receiver and remove all listeners."""
    _LOG.debug("Disconnecting and removing all listeners")
    await device.disconnect()
    device.events.remove_all_listeners()


async def main():
    """Start the Remote Two integration driver."""

    logging.basicConfig(
        format=(
            "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
            "%(name)-14s | %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    setup_logger()

    _LOG.debug("Starting driver...")
    await api.init("driver.json", driver_setup_handler)

    config.devices = config.Devices(api.config_dir_path, on_player_added, on_player_removed)
    for device in config.devices:
        _configure_new_kaleidescape(device, connect=False)


if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except KeyboardInterrupt:
        pass
