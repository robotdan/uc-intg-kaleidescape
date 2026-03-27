"""
Remote entity functions.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from const import RemoteDef
from const import SimpleCommands as cmds
from device import KaleidescapeInfo, KaleidescapePlayer
from ucapi import StatusCodes
from ucapi.media_player import Attributes as MediaAttributes
from ucapi.media_player import States as MediaStates
from ucapi.remote import Attributes, Commands, EntityCommand, Remote, States
from ucapi.ui import (Buttons, DeviceButtonMapping, Size, UiPage,
                      create_btn_mapping, create_ui_text)
from utils import normalize_cmd

_LOG = logging.getLogger(__name__)

REMOTE_STATE_MAPPING = {
    MediaStates.OFF: States.OFF,
    MediaStates.ON: States.ON,
    MediaStates.STANDBY: States.OFF,
    MediaStates.UNAVAILABLE: States.UNAVAILABLE,
    MediaStates.UNKNOWN: States.UNKNOWN,
}


class KaleidescapeRemote(Remote):
    """Representation of a Kaleidescape Remote entity."""

    def __init__(self, info: KaleidescapeInfo, device: KaleidescapePlayer):
        """Initialize the class."""
        self._device = device
        entity_id = f"remote.{info.id}"
        features = RemoteDef.features
        attributes = RemoteDef.attributes
        super().__init__(
            entity_id,
            f"{info.friendly_name} Remote",
            features,
            attributes,
            simple_commands=RemoteDef.simple_commands,
            button_mapping=self.create_button_mappings(),
            ui_pages=self.create_ui()
        )


        _LOG.debug("KaleidescapeRemote init %s : %s", entity_id, attributes)

    def create_button_mappings(self) -> list[DeviceButtonMapping | dict[str, Any]]:
        """Create button mappings."""
        return [
            create_btn_mapping(Buttons.BACK, cmds.BACK.display_name),
            create_btn_mapping(Buttons.DPAD_UP, cmds.UP.display_name),
            create_btn_mapping(Buttons.DPAD_DOWN, cmds.DOWN.display_name),
            create_btn_mapping(Buttons.DPAD_LEFT, cmds.LEFT.display_name),
            create_btn_mapping(Buttons.DPAD_RIGHT, cmds.RIGHT.display_name),
            create_btn_mapping(Buttons.DPAD_MIDDLE, cmds.OK.display_name),
            create_btn_mapping(Buttons.PREV, cmds.PREVIOUS.display_name),
            create_btn_mapping(Buttons.PLAY, cmds.PLAY_PAUSE.display_name),
            create_btn_mapping(Buttons.NEXT, cmds.NEXT.display_name),
            create_btn_mapping(Buttons.CHANNEL_DOWN, cmds.PAGE_DOWN.display_name),
            create_btn_mapping(Buttons.CHANNEL_UP, cmds.PAGE_UP.display_name),
            DeviceButtonMapping(
                button="MENU",
                short_press=EntityCommand(cmd_id=cmds.MENU.display_name, params=None), long_press=None),
            DeviceButtonMapping(
                button="STOP",
                short_press=EntityCommand(cmd_id=cmds.STOP.display_name, params=None), long_press=None),
        ]

    def create_ui(self) -> list[UiPage | dict[str, Any]]:
        """Create a user interface with different pages that includes all commands"""

        ui_page1 = UiPage("page1", "Power", grid=Size(6, 6))
        ui_page1.add(create_ui_text("Power On", 0, 0, size=Size(3, 1), cmd=Commands.ON))
        ui_page1.add(create_ui_text("Standby", 3, 0, size=Size(3, 1), cmd=Commands.OFF))
        ui_page1.add(create_ui_text("Intermission", 0, 1, size=Size(3, 1), cmd=cmds.INTERMISSION.display_name))
        ui_page1.add(create_ui_text("Replay", 3, 1, size=Size(3, 1), cmd=cmds.REPLAY.display_name))
        ui_page1.add(create_ui_text("*** OSD Control ***", 0, 2, size=Size(6, 1)))
        ui_page1.add(create_ui_text("Collections", 0, 3, size=Size(2, 1), cmd=cmds.MOVIE_COLLECTIONS.display_name))
        ui_page1.add(create_ui_text("Covers", 2, 3, size=Size(2, 1), cmd=cmds.MOVIE_COVERS.display_name))
        ui_page1.add(create_ui_text("List", 4, 3, size=Size(2, 1), cmd=cmds.MOVIE_LIST.display_name))
        ui_page1.add(create_ui_text("Alphabetize", 0, 4, size=Size(2, 1), cmd=cmds.ALPHABETIZE_COVER_ART.display_name))
        ui_page1.add(create_ui_text("Shuffle", 2, 4, size=Size(2, 1), cmd=cmds.SHUFFLE_COVER_ART.display_name))
        ui_page1.add(create_ui_text("Store", 4, 4, size=Size(2, 1), cmd=cmds.MOVIE_STORE.display_name))
        ui_page1.add(create_ui_text("Cancel", 0, 5, size=Size(2, 1), cmd=cmds.CANCEL.display_name))
        ui_page1.add(create_ui_text("Search", 2, 5, size=Size(2, 1), cmd=cmds.SEARCH.display_name))
        ui_page1.add(create_ui_text("Subtitles", 4, 5, size=Size(2, 1), cmd=cmds.SUBTITLES.display_name))

        return [ui_page1]

    async def command(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """
        Handle command requests from the integration API for the media-player entity.

        :param cmd_id: Command identifier (e.g., "ON", "OFF", "TOGGLE", "SEND_CMD")
        :param params: Optional dictionary of parameters associated with the command
        :return: Status code indicating the result of the command execution
        """
        params = params or {}

        simple_cmd: str | None = params.get("command")
        if simple_cmd and simple_cmd.startswith("remote"):
            cmd_id = simple_cmd.split(".")[1]

        _LOG.info(
            "Received Remote command request: %s with parameters: %s",
            cmd_id, params or "no parameters")


        status = StatusCodes.BAD_REQUEST  # Default fallback

        try:
            cmd = Commands(cmd_id)
            _LOG.debug("Resolved command: %s", cmd)
        except ValueError:
            status = StatusCodes.NOT_IMPLEMENTED
        else:
            match cmd:
                case Commands.ON:
                    status = await self._device.power_on()

                case Commands.OFF:
                    status = await self._device.power_off()

                case Commands.SEND_CMD:
                    if not simple_cmd:
                        _LOG.warning("Missing command in SEND_CMD")
                        status = StatusCodes.BAD_REQUEST
                    else:
                        simple_cmd = normalize_cmd(simple_cmd)

                        match simple_cmd:
                            case cmds.ALPHABETIZE_COVER_ART:
                                status = await self._device.alphabetize_cover_art()
                            case cmds.BACK:
                                status = await self._device.back()
                            case cmds.INTERMISSION:
                                status = await self._device.intermission_toggle()
                            case cmds.MENU:
                                status = await self._device.menu()
                            case cmds.MOVIE_COLLECTIONS:
                                status = await self._device.collections()
                            case cmds.MOVIE_COVERS:
                                status = await self._device.movie_covers()
                            case cmds.MOVIE_LIST:
                                status = await self._device.list()
                            case cmds.MOVIE_STORE:
                                status = await self._device.movie_store()
                            case cmds.PAGE_DOWN:
                                status = await self._device.page_down()
                            case cmds.PAGE_DOWN_PRESS:
                                status = await self._device.page_down_press()
                            case cmds.PAGE_DOWN_RELEASE:
                                status = await self._device.page_down_release()
                            case cmds.PAGE_UP:
                                status = await self._device.page_up()
                            case cmds.PAGE_UP_PRESS:
                                status = await self._device.page_up_press()
                            case cmds.PAGE_UP_RELEASE:
                                status = await self._device.page_up_release()
                            case cmds.PLAY_PAUSE:
                                status = await self._device.play_pause()
                            case cmds.REPLAY:
                                status = await self._device.replay()
                            case cmds.SEARCH:
                                status = await self._device.search()
                            case cmds.SHUFFLE_COVER_ART:
                                status = await self._device.shuffle_cover_art()
                            case cmds.SUBTITLES:
                                status = await self._device.subtitles()
                            case _:
                                status = await self._device.send_command(simple_cmd)

                case _:
                    status = StatusCodes.NOT_IMPLEMENTED

        return status

    def filter_changed_attributes(self, update: dict[str, Any]) -> dict[str, Any]:
        """
        Filter the given media-player attributes and return remote attributes with converted state.

        :param update: dictionary with MediaAttributes.
        :return: dictionary with changed remote.Attributes only.
        """
        attributes = {}

        if MediaAttributes.STATE in update:
            media_state = update[MediaAttributes.STATE]

            try:
                media_state_enum = MediaStates(media_state)
            except ValueError:
                _LOG.warning("Unknown media_state value: %s", media_state)
                media_state_enum = MediaStates.UNKNOWN

            new_state: States = REMOTE_STATE_MAPPING.get(media_state_enum, States.UNKNOWN)
            current_state = self.attributes.get(Attributes.STATE)

            if current_state != new_state:
                attributes[Attributes.STATE] = new_state

        _LOG.debug("Kaleidescape Remote update attributes %s -> %s", update, attributes)
        return attributes
