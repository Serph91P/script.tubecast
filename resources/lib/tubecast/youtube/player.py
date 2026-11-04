# -*- coding: utf-8 -*-
from time import monotonic

import xbmc

from resources.lib.kodi import kodilogging

monitor = xbmc.Monitor()
logger = kodilogging.get_logger("player")

STATUS_PLAYING = 1
STATUS_PAUSED = 2
STATUS_LOADING = 3
STATUS_STOPPED = 4


class CastPlayer(xbmc.Player):
    def __init__(self, cast):  # type: (YoutubeCastV1) -> None
        super(CastPlayer, self).__init__()
        self.cast = cast
        # auxiliary variable to know if the request came from the youtube background thread
        self.from_yt = False
        self._cast_start_pending = False
        self._next_progress_at = 0
        self._announce_pending = False

    def play_from_youtube(self, url):  # type: (str) -> None
        self._cast_start_pending = True
        self.from_yt = True
        self.play(url)

    @property
    def status_code(self):  # type: () -> int
        if xbmc.getCondVisibility("Player.Paused"):
            return STATUS_PAUSED

        if self.isPlaying():
            return STATUS_PLAYING

        return STATUS_STOPPED

    @property
    def playing(self):  # type: () -> bool
        """Whether the player is currently playing.

        This is different from `isPlaying` in that it returns `False` if the
        player is paused or otherwise not actively playing.
        """
        return xbmc.getCondVisibility("Player.Playing")

    def __should_report(self):  # type: () -> bool
        return self.cast.has_client and self.from_yt

    def __report_state_change(self, status_code=None):
        if not self.__should_report() or not self.isPlaying():
            return False

        try:
            position = int(self.getTime())
            duration = int(self.getTotalTime())
            if status_code is None:
                status_code = self.status_code
        except RuntimeError:
            # Streams can change between isPlaying() and getTime(). Let the
            # receiver's next tick retry rather than lose its status reporter.
            logger.debug("Playback time not available yet; deferring progress")
            return False

        self.cast.report_state_change(status_code, position, duration)
        return True

    def report_progress(self):
        """Run from the receiver thread, never a blocking Kodi callback loop."""
        now = monotonic()
        if now < self._next_progress_at or not self.__report_state_change():
            return False
        if self._announce_pending:
            try:
                self.cast.report_now_playing()
            except RuntimeError:
                logger.debug("Playback metadata not available yet; deferring announcement")
            else:
                self._announce_pending = False
        self._next_progress_at = now + 5
        return True

    def onPlayBackStarted(self):
        # Kodi's early callback does not guarantee an available AV stream.
        # A stop for the previous item may have arrived after play() requested
        # its replacement. Only our pending play request owns the new item.
        self.from_yt = self._cast_start_pending
        self._cast_start_pending = False
        self._announce_pending = True
        self._next_progress_at = 0

    def onAVStarted(self):
        self._announce_pending = True
        self._next_progress_at = 0

    def onPlayBackResumed(self):
        self.__report_state_change()

    def onPlayBackPaused(self):
        self.__report_state_change()

    def onPlayBackEnded(self):
        should_report = self.__should_report()
        self.from_yt = False

        if should_report:
            self.cast.report_playback_ended()

    def onPlayBackSeek(self, time, seek_offset):
        self.__report_state_change(status_code=STATUS_LOADING)

    def onPlayBackStopped(self):
        should_report = self.__should_report()
        self.from_yt = False
        if should_report:
            self.cast.report_playback_stopped()

    def onPlayBackError(self):
        self._cast_start_pending = False
        self.onPlayBackStopped()
