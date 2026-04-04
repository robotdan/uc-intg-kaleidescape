"""
Media-player entity functions.

:copyright: (c) 2023 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import logging
from typing import Any

from const import MediaPlayerDef
from const import SimpleCommands as cmds
from device import KaleidescapeInfo, KaleidescapePlayer
from ucapi import MediaPlayer, StatusCodes, media_player
from ucapi.media_player import Attributes, Commands, DeviceClasses, States
from utils import normalize_cmd

_LOG = logging.getLogger(__name__)

class KaleidescapeMediaPlayer(MediaPlayer):
    """Representation of a Kaleidescape Media Player entity."""

    def __init__(self, mp_info: KaleidescapeInfo, device: KaleidescapePlayer):
        """Initialize the class."""
        self._device = device
        entity_id = f"media_player.{mp_info.id}"
        features = MediaPlayerDef.features
        attributes = MediaPlayerDef.attributes
        options={
            media_player.Options.SIMPLE_COMMANDS: [
                cmds.ALPHABETIZE_COVER_ART.display_name,
                cmds.CANCEL.display_name,
                cmds.INTERMISSION.display_name,
                cmds.MOVIE_COLLECTIONS.display_name,
                cmds.MOVIE_COVERS.display_name,
                cmds.MOVIE_LIST.display_name,
                cmds.MOVIE_STORE.display_name,
                cmds.PAGE_DOWN.display_name,
                cmds.PAGE_DOWN_PRESS.display_name,
                cmds.PAGE_DOWN_RELEASE.display_name,
                cmds.PAGE_UP.display_name,
                cmds.PAGE_UP_PRESS.display_name,
                cmds.PAGE_UP_RELEASE.display_name,
                cmds.REPLAY.display_name,
                cmds.SEARCH.display_name,
                cmds.SHUFFLE_COVER_ART.display_name,
                cmds.SUBTITLES.display_name
            ]
        }

        super().__init__(
            entity_id,
            f"{mp_info.friendly_name} Media Player",
            features,
            attributes,
            device_class=DeviceClasses.STREAMING_BOX,
            options=options,
        )

        _LOG.debug("KaleidescapeMediaPlayer init %s : %s", entity_id, attributes)

    async def command(self, cmd_id: str, params: dict[str, Any] | None = None) -> StatusCodes:
        """
        Media-player entity command handler.

        Called by the integration-API if a command is sent to a configured media-player entity.

        :param cmd_id: command
        :param params: optional command parameters
        :return: status code of the command request
        """
        _LOG.info("Got %s command request: %s %s", self.id, cmd_id, params)

        try:
            cmd = Commands(cmd_id)
        except ValueError:
            try:
                _LOG.debug("Command Received = %s", cmd_id)
                cmd = normalize_cmd(cmd_id)
                _LOG.debug("Command Normalized = %s", cmd)
                cmd = cmds(cmd)
                _LOG.debug("Actual Command = %s", cmd)
            except ValueError:
                return StatusCodes.NOT_IMPLEMENTED


        match cmd:
            case Commands.ON:
                res = await self._device.power_on()
            case Commands.OFF:
                res = await self._device.power_off()
            case cmds.ALPHABETIZE_COVER_ART:
                res = await self._device.alphabetize_cover_art()
            case Commands.PLAY_PAUSE:
                if self._device.is_on:
                    res = await self._device.play_pause()
                else:
                    return StatusCodes.OK
            case Commands.NEXT:
                res = await self._device.media_next_track()
            case Commands.PREVIOUS:
                res = await self._device.media_previous_track()
            case Commands.CURSOR_ENTER:
                res = await self._device.media_select()
            case Commands.BACK:
                res = await self._device.back()
            case Commands.STOP:
                res = await self._device.media_stop()
            case Commands.CURSOR_UP:
                res = await self._device.cursor_up()
            case Commands.CURSOR_DOWN:
                res = await self._device.cursor_down()
            case Commands.CURSOR_LEFT:
                res = await self._device.cursor_left()
            case Commands.CURSOR_RIGHT:
                res = await self._device.cursor_right()
            case Commands.HOME:
                res = await self._device.collections()
            case Commands.MENU:
                res = await self._device.menu()
            case Commands.FAST_FORWARD:
                res = await self._device.fast_forward()
            case Commands.REWIND:
                res = await self._device.rewind()
            case cmds.CANCEL:
                res = await self._device.cancel()
            case cmds.INTERMISSION:
                res = await self._device.intermission_toggle()
            case cmds.MOVIE_COLLECTIONS:
                res = await self._device.collections()
            case cmds.MOVIE_COVERS:
                res = await self._device.movie_covers()
            case cmds.MOVIE_LIST:
                res = await self._device.list()
            case cmds.MOVIE_STORE:
                res = await self._device.movie_store()
            case cmds.PAGE_DOWN:
                res = await self._device.page_down()
            case cmds.PAGE_DOWN_PRESS:
                res = await self._device.page_down_press()
            case cmds.PAGE_DOWN_RELEASE:
                res = await self._device.page_down_release()
            case cmds.PAGE_UP:
                res = await self._device.page_up()
            case cmds.PAGE_UP_PRESS:
                res = await self._device.page_up_press()
            case cmds.PAGE_UP_RELEASE:
                res = await self._device.page_up_release()
            case cmds.REPLAY:
                res = await self._device.replay()
            case cmds.SEARCH:
                res = await self._device.search()
            case cmds.SHUFFLE_COVER_ART:
                res = await self._device.shuffle_cover_art()
            case cmds.SUBTITLES:
                res = await self._device.subtitles()
            case _:
                _LOG.debug("Not Implemented: %s", cmd)
                return StatusCodes.NOT_IMPLEMENTED

        return res

    def filter_changed_attributes(self, update: dict[str, Any]) -> dict[str, Any]:
        """
        Filter the given attributes and return only the changed values.

        :param update: dictionary with attributes.
        :return: filtered entity attributes containing changed attributes only.
        """
        attributes = {}

        for key in (
            Attributes.MEDIA_DURATION,
            Attributes.MEDIA_IMAGE_URL,
            Attributes.MEDIA_POSITION,
            Attributes.MEDIA_POSITION_UPDATED_AT,
            Attributes.MEDIA_TITLE,
            Attributes.MEDIA_TYPE,
            Attributes.STATE,
        ):
            if key in update and key in self.attributes:
                if update[key] != self.attributes[key]:
                    attributes[key] = update[key]

        if attributes.get(Attributes.STATE) == States.OFF:
            attributes[Attributes.SOURCE] = ""

        _LOG.debug("Kaleidescape MediaPlayer update attributes %s -> %s", update, attributes)
        return attributes
