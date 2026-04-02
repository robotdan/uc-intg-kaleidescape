"""Provides connection utilities for communicating with a Kaleidescape Player."""

import asyncio
import json
import logging
import time
from asyncio import AbstractEventLoop
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any

import ucapi
from const import EntityPrefix
from kaleidescape import Device as KaleidescapeDevice
from kaleidescape import KaleidescapeError
from kaleidescape.const import (DEVICE_POWER_STATE, DEVICE_POWER_STATE_ON,
                                DEVICE_POWER_STATE_STANDBY,
                                PLAY_STATUS_PLAYING, STATE_CONNECTED,
                                STATE_DISCONNECTED)
from pyee.asyncio import AsyncIOEventEmitter
from ucapi.media_player import Attributes as MediaAttr
from ucapi.media_player import States as MediaStates

_LOG = logging.getLogger(__name__)

class Events(IntEnum):
    """Driver lifecycle events used internally for signaling."""

    CONNECTED = 0
    DISCONNECTED = 1
    UPDATE = 2

class DeviceState:
    """
    Constants representing the possible states of a device connection.

    This class encapsulates connection state strings to provide a namespaced
    and safe way to reference them, especially in pattern matching constructs.

    Attributes:
        CONNECTED (str): Indicates the device is currently connected.
        DISCONNECTED (str): Indicates the device is currently disconnected.
    """
    CONNECTED = STATE_CONNECTED
    DISCONNECTED = STATE_DISCONNECTED


@dataclass
class KaleidescapeInfo:
    """
    Represents a Kaleidescape Player discovered on the network.
    """
    id: str
    host: str
    location: str
    friendly_name: str
    manufacturer: str
    model_name: str
    serial_number: str

    def to_json(self, indent: int = 2, sort_keys: bool = True) -> str:
        """
        Return a JSON string representation of this device.
        :param indent: Indentation level for pretty-printing.
        :param sort_keys: Whether to sort keys alphabetically.
        :return: JSON string.
        """
        return json.dumps(asdict(self), indent=indent, sort_keys=sort_keys)

class KaleidescapePlayer:
    """Handles communication with a Kaleidescape Player over TCP."""

    def __init__(
        self,
        host: str,
        device_id: str | None = None,
        loop: AbstractEventLoop | None = None,
    ):
        # Identity and core connection
        self.device_id = device_id or "unknown"
        self.host = host
        self.device = KaleidescapeDevice(host, timeout=5, reconnect=True, reconnect_delay=5)

        # Event loop setup
        self._event_loop = loop or asyncio.get_running_loop()

        # Internal connection and media state
        self._connected: bool = False
        self._connecting: bool = False
        self._reconnect_task: asyncio.Task | None = None
        self._attr_state = MediaStates.UNAVAILABLE

        # Playback state
        self._position_seconds = 0
        self._duration_seconds = 0
        self._last_position_update = time.monotonic()
        self._is_playing = False
        self._position_updater_task: asyncio.Task | None = None

        # Event communication
        self.events = AsyncIOEventEmitter(self._event_loop)
        self.device.dispatcher.connect(self._on_event)

    @property
    def attributes(self) -> dict[str, Any]:
        """Return the device attributes."""
        updated_data = {
            MediaAttr.STATE: self.state,
        }
        return updated_data

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self.device.power.state == DEVICE_POWER_STATE_ON

    @property
    def state(self) -> MediaStates:
        """Return the cached state of the device."""
        return self._attr_state

    async def connect(self) -> bool:
        """Connect to the device. The library handles auto-reconnect on drops.

        If the initial connection fails, a background retry task is started
        that retries until successful or disconnect() is called.
        """
        if self._connected:
            _LOG.debug("Already connected to %s", self.host)
            return True

        _LOG.debug("Connecting to player at %s", self.host)

        # UPSTREAM WORKAROUND: Device.disconnect() guards on is_connected which
        # is False during STATE_RECONNECTING, silently skipping cleanup. Call
        # Connection.disconnect() directly to reliably cancel any active
        # reconnect task. Remove once pykaleidescape PR #17 lands and
        # Device.disconnect() handles all states.
        await self._cancel_reconnect_task()
        await self.device.connection.disconnect()

        self._connecting = True
        try:
            await self.device.connect()
            await self.device.refresh()
            self._connected = True
            await self._sync_full_state()
            return True
        except (KaleidescapeError, ConnectionError, OSError) as err:
            _LOG.error("Unable to connect to %s: %s", self.host, err)
            await self.device.connection.disconnect()
            self._connected = False
            self._reconnect_task = asyncio.create_task(self._retry_connect())
            return False
        finally:
            self._connecting = False

    async def disconnect(self):
        """Disconnect from the device and cancel all reconnect activity."""
        _LOG.debug("Disconnecting from player at %s", self.host)
        await self._cancel_reconnect_task()
        self._stop_position_updater()
        # UPSTREAM WORKAROUND: see comment in connect().
        await self.device.connection.disconnect()
        self._connected = False
        await self._handle_power_state()

    async def _cancel_reconnect_task(self):
        """Cancel the integration-level retry task if running."""
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

    async def _retry_connect(self):
        """Retry initial connection until successful or cancelled.

        The library's reconnect=True only activates after a successful first
        connection (by design). This task provides persistent retry for the
        initial connect failure case at the integration level.

        Runs indefinitely — cancellation is handled by _cancel_reconnect_task()
        which is called from disconnect() and connect(). There is no automatic
        give-up because there is no other recovery path for the user.
        """
        # UPSTREAM: _reconnect_delay is a private attribute on Connection.
        # Replace with a public accessor if pykaleidescape exposes one.
        delay = self.device.connection._reconnect_delay or 5
        while True:
            _LOG.debug("Retrying connection to %s in %ss", self.host, delay)
            await asyncio.sleep(delay)
            self._connecting = True
            try:
                await self.device.connect()
                await self.device.refresh()
                self._connected = True
                await self._sync_full_state()
                self._reconnect_task = None
                _LOG.info("Reconnected to %s", self.host)
                return
            except (KaleidescapeError, ConnectionError, OSError) as err:
                _LOG.warning("Retry connect to %s failed: %s", self.host, err)
                await self.device.connection.disconnect()
            finally:
                self._connecting = False

    async def send_command(self, command: str) -> ucapi.StatusCodes:
        """Send a command to a device."""
        if not self.is_on:
            _LOG.debug("Cannot send command: '%s' device is powered off", command)
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE

        method = getattr(self.device, command, None)
        if not callable(method):
            _LOG.warning("Device method for command '%s' is not callable or missing", command)
            return ucapi.StatusCodes.NOT_FOUND

        _LOG.debug("Sending command: %s", command)
        try:
            await method()
            return ucapi.StatusCodes.OK
        except Exception as e:
            _LOG.error("Failed to send command '%s': %s", command, e)
            return ucapi.StatusCodes.SERVER_ERROR

    async def _send_socket_command(
        self,
        message: str,
        *,
        port: int = 10000,
        timeout: int = 2,
    ) -> None:
        """Send a raw socket command to the device if it is powered on."""
        if not self.is_on:
            _LOG.debug("Cannot send command: '%s' device is powered off", message.strip())
            return

        writer = None
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, port),
                timeout=timeout,
            )

            writer.write(message.encode("utf-8"))
            await asyncio.wait_for(writer.drain(), timeout=timeout)

        except (asyncio.TimeoutError, OSError) as err:
            _LOG.error(
                "Socket command failed to %s:%s - %s",
                self.host,
                port,
                err,
            )
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    async def power_on(self) -> ucapi.StatusCodes:
        if not self._connected:
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE

        if self.is_on:
            _LOG.debug("Power on skipped: already ON")
            return ucapi.StatusCodes.OK

        try:
            _LOG.debug("Sending leave_standby...")
            await self.device.leave_standby()
            return ucapi.StatusCodes.OK
        except (KaleidescapeError, ConnectionError, OSError) as err:
            _LOG.error("Power on failed: %s", err)
            return ucapi.StatusCodes.SERVER_ERROR

    async def power_off(self) -> ucapi.StatusCodes:
        if not self._connected:
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE

        if not self.is_on:
            _LOG.debug("Power off skipped: already STANDBY/OFF")
            return ucapi.StatusCodes.OK

        try:
            _LOG.debug("Sending enter_standby...")
            await self.device.enter_standby()
            return ucapi.StatusCodes.OK
        except (KaleidescapeError, ConnectionError, OSError) as err:
            _LOG.error("Power off failed: %s", err)
            return ucapi.StatusCodes.SERVER_ERROR

    async def alphabetize_cover_art(self) -> ucapi.StatusCodes:
        """Trigger the 'alphabetize_cover_art' command."""
        await self._send_socket_command("01/7/ALPHABETIZE_COVER_ART:\r")
        return ucapi.StatusCodes.OK

    async def back(self) -> ucapi.StatusCodes:
        """Trigger the 'back' command."""
        if self.is_on:
            await self.device.cancel()
        return ucapi.StatusCodes.OK

    async def cancel(self) -> ucapi.StatusCodes:
        """Trigger the 'cancel' command."""
        if self.is_on:
            await self.device.cancel()
        return ucapi.StatusCodes.OK

    async def collections(self) -> ucapi.StatusCodes:
        """Trigger the 'go movie collections' command."""
        if self.is_on:
            await self.device.go_movie_collections()
        return ucapi.StatusCodes.OK

    async def cursor_down(self) -> ucapi.StatusCodes:
        """Trigger the 'cursor down' command."""
        if self.is_on:
            await self.device.down()
        return ucapi.StatusCodes.OK

    async def cursor_left(self) -> ucapi.StatusCodes:
        """Trigger the 'cursor left' command."""
        if self.is_on:
            await self.device.left()
        return ucapi.StatusCodes.OK

    async def cursor_right(self) -> ucapi.StatusCodes:
        """Trigger the 'cursor right' command."""
        if self.is_on:
            await self.device.right()
        return ucapi.StatusCodes.OK

    async def cursor_up(self) -> ucapi.StatusCodes:
        """Trigger the 'cursor up' command."""
        if self.is_on:
            await self.device.up()
        return ucapi.StatusCodes.OK

    async def fast_forward(self) -> ucapi.StatusCodes:
        """Trigger the 'fast forward' command."""
        if self.is_on:
            await self.device.scan_forward()
        return ucapi.StatusCodes.OK

    async def intermission_toggle(self) -> ucapi.StatusCodes:
        """Trigger the 'intermission toggle' command."""
        if self.is_on:
            await self.device.intermission_toggle()
        return ucapi.StatusCodes.OK

    async def list(self) -> ucapi.StatusCodes:
        """Trigger the 'go movie list' command."""
        if self.is_on:
            await self.device.go_movie_list()
        return ucapi.StatusCodes.OK

    async def media_next_track(self) -> ucapi.StatusCodes:
        """Trigger the 'next track' command."""
        if self.is_on:
            await self.device.next()
        return ucapi.StatusCodes.OK

    async def media_pause(self) -> ucapi.StatusCodes:
        """Trigger the 'pause' command."""
        if self.is_on:
            await self.device.pause()
        return ucapi.StatusCodes.OK

    async def media_play(self) -> ucapi.StatusCodes:
        """Trigger the 'play' command."""
        if self.is_on:
            await self.device.play()
        return ucapi.StatusCodes.OK

    async def media_previous_track(self) -> ucapi.StatusCodes:
        """Trigger the 'previous track' command."""
        if self.is_on:
            await self.device.previous()
        return ucapi.StatusCodes.OK

    async def media_select(self) -> ucapi.StatusCodes:
        """Trigger the 'select' command."""
        if self.is_on:
            await self.device.select()
        return ucapi.StatusCodes.OK

    async def media_stop(self) -> ucapi.StatusCodes:
        """Trigger the 'stop' command."""
        if self.is_on:
            await self.device.stop()
        return ucapi.StatusCodes.OK

    async def menu(self) -> ucapi.StatusCodes:
        """Trigger the 'disc_or_kaleidescape_menu' command."""
        await self._send_socket_command("01/6/DISC_OR_KALEIDESCAPE_MENU:\r")
        return ucapi.StatusCodes.OK

    async def movie_covers(self) -> ucapi.StatusCodes:
        """Trigger the 'go movie covers' command."""
        if self.is_on:
            await self.send_command("go_movie_covers")
        else:
            _LOG.debug("Cannot send command: 'go_movie_covers' device is powered off")
        return ucapi.StatusCodes.OK

    async def page_up(self) -> ucapi.StatusCodes:
        """Trigger the 'page_up' command."""
        await self._send_socket_command("01/6/PAGE_UP:\r")
        return ucapi.StatusCodes.OK

    async def page_up_press(self) -> ucapi.StatusCodes:
        """Trigger the 'page_up_press' command."""
        await self._send_socket_command("01/6/PAGE_UP_PRESS:\r")
        return ucapi.StatusCodes.OK

    async def page_up_release(self) -> ucapi.StatusCodes:
        """Trigger the 'page_up_release' command."""
        await self._send_socket_command("01/6/PAGE_UP_RELEASE:\r")
        return ucapi.StatusCodes.OK

    async def page_down(self) -> ucapi.StatusCodes:
        """Trigger the 'page_down' command."""
        await self._send_socket_command("01/6/PAGE_DOWN:\r")
        return ucapi.StatusCodes.OK

    async def page_down_press(self) -> ucapi.StatusCodes:
        """Trigger the 'page_down_press' command."""
        await self._send_socket_command("01/6/PAGE_DOWN_PRESS:\r")
        return ucapi.StatusCodes.OK

    async def page_down_release(self) -> ucapi.StatusCodes:
        """Trigger the 'page_down_release' command."""
        await self._send_socket_command("01/6/PAGE_DOWN_RELEASE:\r")
        return ucapi.StatusCodes.OK

    async def play_pause(self) -> ucapi.StatusCodes:
        """Toggle between play and pause based on current playback state."""
        _LOG.debug("Play / Pause State = %s", self.device.movie.play_status)
        if self.is_on:
            if self.device.movie.play_status == PLAY_STATUS_PLAYING:
                await self.media_pause()
            else:
                await self.media_play()
        else:
            _LOG.debug("Cannot send command: 'media_pause or media_play' device is powered off")
        return ucapi.StatusCodes.OK

    async def replay(self) -> ucapi.StatusCodes:
        """Trigger the 'replay' command."""
        await self._send_socket_command("01/6/REPLAY:\r")
        return ucapi.StatusCodes.OK

    async def rewind(self) -> ucapi.StatusCodes:
        """Trigger the 'rewind' command."""
        if self.is_on:
            await self.device.scan_reverse()
        return ucapi.StatusCodes.OK

    async def shuffle_cover_art(self) -> ucapi.StatusCodes:
        """Trigger the 'shuffle_cover_art' command."""
        await self._send_socket_command("01/6/SHUFFLE_COVER_ART:\r")
        return ucapi.StatusCodes.OK

    async def movie_store(self) -> ucapi.StatusCodes:
        """Trigger the 'go_movie_store' command."""
        await self._send_socket_command("01/6/GO_MOVIE_STORE:\r")
        return ucapi.StatusCodes.OK

    async def search(self) -> ucapi.StatusCodes:
        """Trigger the 'go_search' command."""
        await self._send_socket_command("01/9/GO_SEARCH:\r")
        return ucapi.StatusCodes.OK

    async def subtitles(self) -> ucapi.StatusCodes:
        """Trigger the 'subtitles_next' command."""
        await self._send_socket_command("01/9/SUBTITLES_NEXT:\r")
        return ucapi.StatusCodes.OK

    async def _on_event(self, event: str, params: Any | None = None):
        """Handle device connection state changes based on incoming event."""
        if event == "":
            return
        _LOG.debug("Received Event: %s params=%s...........................", event, params)
        handlers = {
            DEVICE_POWER_STATE: self._handle_power_state,
            DeviceState.CONNECTED: self._handle_connected,
            DeviceState.DISCONNECTED: self._handle_disconnected,
        }

        handler = handlers.get(event, lambda: self._handle_events(event))
        await handler()

    async def _handle_connected(self):
        """Handle library auto-reconnect completion.

        UPSTREAM WORKAROUND: The library dispatches STATE_CONNECTED during both
        initial connect() and auto-reconnect, but doesn't call refresh() after
        reconnect. We gate on _connecting to avoid double refresh/sync during
        initial connect (where connect() already handles it), and only run the
        full resync on auto-reconnect. Remove the _connecting guard once the
        library either suppresses the event during initial connect or calls
        refresh() itself after reconnect.
        """
        self._connected = True
        self.events.emit(Events.CONNECTED.name, self.device_id)

        if self._connecting:
            return

        try:
            await self.device.refresh()
        except (KaleidescapeError, ConnectionError, OSError) as err:
            _LOG.warning("Failed to refresh state after reconnect: %s", err)

        await self._sync_full_state()

    async def _sync_full_state(self) -> None:
        """Sync and emit the full current device state."""
        await self._handle_power_state()
        await self._handle_play_status()
        await self._sync_media_attributes()

    async def _sync_media_attributes(self) -> None:
        """Emit current media attributes from the library's dataclasses."""
        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_IMAGE_URL,
            self.device.movie.cover,
        )
        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_TITLE,
            self.device.movie.title,
        )
        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_TYPE,
            self.device.movie.media_type,
        )

        self._position_seconds = self.device.movie.title_location or 0
        self._last_position_update = time.monotonic()
        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_POSITION,
            self._position_seconds,
        )

        self._duration_seconds = self.device.movie.title_length or 0
        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_DURATION,
            self._duration_seconds,
        )

    async def _handle_disconnected(self):
        """
        Mark device as unavailable when disconnected.
        Avoids redundant updates if already handled by power state logic.
        """
        self._connected = False
        _LOG.warning("[%s] Device disconnected", self.device_id)

        # Only emit if current state is NOT already unavailable
        if self._attr_state != MediaStates.UNAVAILABLE:
            self._attr_state = MediaStates.UNAVAILABLE
            await self._emit_update(EntityPrefix.MEDIA_PLAYER.value, MediaAttr.STATE, self.state)
            await self._emit_update(EntityPrefix.REMOTE.value, MediaAttr.STATE, self.state)

    async def _handle_play_status(self):
        _LOG.debug("Player Status = %s", self.device.movie.play_status)
        new_state = self.device.movie.play_status == PLAY_STATUS_PLAYING
        if new_state != self._is_playing:
            self._is_playing = new_state
            self._last_position_update = time.monotonic()
            if self._is_playing:
                self._start_position_updater()
            else:
                self._stop_position_updater()

    async def _handle_power_state(self):
        """
        Update the power state of the player using raw reported power only.

        Resolves to:
            - ON: if power state is ON and connected
            - STANDBY: if power state is STANDBY and connected
            - UNAVAILABLE: if not connected
            - UNKNOWN: if power state is None or unrecognized
        Emits updates only when state has changed.
        """
        raw_power = getattr(self.device.power, "state", None)

        _LOG.debug("Evaluating power state for device [%s]", self.device_id)
        _LOG.debug("Connection: %s | Raw Power: %s", self._connected, raw_power)

        if not self._connected:
            resolved_state = MediaStates.UNAVAILABLE
        elif raw_power == DEVICE_POWER_STATE_ON:
            resolved_state = MediaStates.ON
        elif raw_power == DEVICE_POWER_STATE_STANDBY:
            resolved_state = MediaStates.STANDBY
        elif raw_power is None:
            resolved_state = MediaStates.UNKNOWN
        else:
            resolved_state = MediaStates.UNKNOWN

        if resolved_state == self._attr_state:
            _LOG.debug("State unchanged: %s", resolved_state)
            return

        _LOG.debug("State changed: %s -> %s", self._attr_state, resolved_state)
        self._attr_state = resolved_state

        await self._emit_update(EntityPrefix.MEDIA_PLAYER.value, MediaAttr.STATE, self.state)
        await self._emit_update(EntityPrefix.REMOTE.value, MediaAttr.STATE, self.state)

    async def _handle_events(self, event: str):
        """Handle library events by syncing media state.

        The library has already parsed the event and updated its dataclasses
        before dispatching, so we just read the current values and emit
        updates for media-related attributes. Power state has its own handler.
        """
        _LOG.debug("Event received: %s", event)
        await self._handle_play_status()
        await self._sync_media_attributes()

    def _start_position_updater(self):
        if self._position_updater_task is None or self._position_updater_task.done():
            self._position_updater_task = asyncio.create_task(self._position_updater())

    def _stop_position_updater(self):
        if self._position_updater_task:
            self._position_updater_task.cancel()
            self._position_updater_task = None

    async def _position_updater(self):
        try:
            while self._is_playing:
                await asyncio.sleep(1)
                elapsed = int(time.monotonic() - self._last_position_update)
                current_position = min(self._position_seconds + elapsed, self._duration_seconds)
                await self._emit_update(EntityPrefix.MEDIA_PLAYER.value, MediaAttr.MEDIA_POSITION, current_position)
        except asyncio.CancelledError:
            pass

        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_POSITION,
            self.device.movie.title_location or 0,
        )
        await self._emit_update(
            EntityPrefix.MEDIA_PLAYER.value,
            MediaAttr.MEDIA_DURATION,
            self.device.movie.title_length or 0,
        )

    async def _emit_update(self, prefix: str, attr: str, value: Any) -> None:
        entity_id = f"{prefix}.{self.device_id}"
        self.events.emit(Events.UPDATE.name, entity_id, {attr: value})
