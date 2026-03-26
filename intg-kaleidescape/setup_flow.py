"""
Initial setup and configuration logic for Kaleidescape integration.

Handles user interaction, automatic discovery of Kaleidescape player,
and device onboarding into the system.
"""

import logging

import config
import ucapi
from api import api
from device import KaleidescapeInfo
from discover import discover_kaleidescape_device, fetch_device_info
from registry import clear_devices

_LOG = logging.getLogger(__name__)


def _basic_input_form(ip: str = "") -> ucapi.RequestUserInput:
    """
    Returns a form for manual configuration of IP.

    Args:
        ip (str): IP address to prepopulate. Default is empty.

    Returns:
        ucapi.RequestUserInput: Form requesting user input for IP and port.
    """
    return ucapi.RequestUserInput(
        {"en": "Manual Configuration"},
        [
            {
                "id": "ip",
                "label": {"en": "Enter Kaleidescape Player Ip Address:"},
                "field": {"text": {"value": ip}}
            },
        ]
    )

async def driver_setup_handler(msg: ucapi.SetupDriver) -> ucapi.SetupAction:
    """
    Main entry point for handling all setup-related UCAPI messages.

    Args:
        msg (ucapi.SetupDriver): Message from UCAPI.

    Returns:
        ucapi.SetupAction: Action to take in response to the setup request.
    """

    if isinstance(msg, ucapi.DriverSetupRequest):
        return await handle_driver_setup(msg)
    if isinstance(msg, ucapi.UserDataResponse):
        return await handle_user_data_response(msg)
    if isinstance(msg, ucapi.AbortDriverSetup):
        _LOG.info("Setup was aborted with code: %s", msg.error)
        clear_devices()

    _LOG.error("Error during setup")
    return ucapi.SetupError()

async def handle_driver_setup(msg: ucapi.DriverSetupRequest) -> ucapi.SetupAction:
    """
    Handle initial setup or reconfiguration request from the user.

    Args:
        msg (ucapi.DriverSetupRequest): Setup message containing context and flags.

    Returns:
        ucapi.SetupAction: Action (form, complete, or error) based on discovery result.
    """
    _LOG.info(msg)

    if msg.reconfigure:
        _LOG.info("Starting reconfiguration")

    api.available_entities.clear()
    api.configured_entities.clear()

    if msg.setup_data.get("manual") == "true":
        _LOG.info("Entering manual setup settings")
        return _basic_input_form()

    info: KaleidescapeInfo = await discover_kaleidescape_device()
    host = info.host
    if not host:
        return ucapi.SetupError()

    _LOG.info("Using host ip = %s", host)

    return ucapi.RequestUserInput(
        {"en": "Discovered Kaleidescape Player"},
        [
            {
                "id": "ip",
                "label": {"en": "Discovered Kaleidescape Player at IP Address:"},
                "field": {"text": {"value": host}},
            },
            {
                "id": "name",
                "label": {"en": "Kaleidescape Player Name:"},
                "field": {"text": {"value": info.friendly_name}},
            }
        ]
    )

async def handle_user_data_response(msg: ucapi.UserDataResponse) -> ucapi.SetupAction:
    """
    Handle the user's submitted data from the input form and validate device.

    Args:
        msg (ucapi.UserDataResponse): Contains IP and port info submitted by the user.

    Returns:
        ucapi.SetupAction: Action signaling success or failure of setup.
    """
    _LOG.info(msg)

    ip = msg.input_values.get("ip")
    name = msg.input_values.get("name")

    url = f"http://{ip}:8080/description.xml"
    raw_info = fetch_device_info(url)
    if not raw_info:
        return ucapi.SetupError()

    sn: str = raw_info.get("serialNumber", "")

    info = KaleidescapeInfo(
        id=sn.replace(" ", ""),
        host=ip,
        location=url,
        friendly_name=name or raw_info.get("friendlyName", ""),
        manufacturer=raw_info.get("manufacturer", ""),
        model_name=raw_info.get("modelName", ""),
        serial_number=sn
    )

    config.devices.clear()
    config.devices.add(info)

    _LOG.info("Setup complete")
    return ucapi.SetupComplete()
