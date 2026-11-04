"""Playback callbacks must not stop progress reporting during AV startup."""
from unittest.mock import Mock

import pytest

from resources.lib.tubecast.youtube import player as module


@pytest.fixture
def player(mocker):
    cast = Mock(has_client=True)
    instance = module.CastPlayer(cast)
    instance.from_yt = True
    instance.isPlaying = Mock(return_value=True)
    instance.getTime = Mock(return_value=12.5)
    instance.getTotalTime = Mock(return_value=120.0)
    mocker.patch.object(module.xbmc, 'getCondVisibility', return_value=False)
    mocker.patch.object(module.monitor, 'abortRequested', return_value=False)
    # A callback must return, never wait for playback to finish on Kodi's
    # interpreter callback thread. Avoid hanging the regression test itself.
    mocker.patch.object(module.monitor, 'waitForAbort',
                        side_effect=AssertionError('blocking playback callback'))
    return instance


def test_playback_started_callback_does_not_block_kodi_event_delivery(player):
    player.onPlayBackStarted()
    module.monitor.waitForAbort.assert_not_called()


def test_time_unavailable_at_startup_does_not_raise_from_callback(player):
    player.getTime.side_effect = RuntimeError('Kodi is not playing any file')
    player.onPlayBackStarted()


def test_early_start_defers_time_reads_until_progress_tick(player):
    player.isPlaying.return_value = False
    player.onPlayBackStarted()
    assert player.report_progress() is False
    player.getTime.assert_not_called()
    player.isPlaying.return_value = True
    player.onAVStarted()
    assert player.report_progress() is True
    player.cast.report_state_change.assert_called_once_with(module.STATUS_PLAYING, 12, 120)
    player.cast.report_now_playing.assert_called_once()


@pytest.mark.parametrize('getter', ['getTime', 'getTotalTime'])
def test_transient_time_race_recovers_on_next_tick(player, getter):
    getattr(player, getter).side_effect = [RuntimeError('not ready'), 20]
    player.onPlayBackStarted()
    assert player.report_progress() is False
    assert player.report_progress() is True
    player.cast.report_state_change.assert_called_once()


def test_one_progress_report_per_five_seconds(player, mocker):
    clock = mocker.patch.object(module, 'monotonic', return_value=0)
    player.onPlayBackStarted()
    assert player.report_progress() is True
    for now in (1, 2, 4.99):
        clock.return_value = now
        assert player.report_progress() is False
    clock.return_value = 5
    assert player.report_progress() is True
    assert player.cast.report_state_change.call_count == 2
    player.cast.report_now_playing.assert_called_once()


def test_paused_video_keeps_reporting_without_a_playing_only_gate(player, mocker):
    mocker.patch.object(module.xbmc, 'getCondVisibility', return_value=True)
    assert player.report_progress() is True
    player.cast.report_state_change.assert_called_once_with(module.STATUS_PAUSED, 12, 120)


@pytest.mark.parametrize('callback', ['onPlayBackResumed', 'onPlayBackPaused'])
def test_event_time_race_does_not_raise(player, callback):
    player.getTime.side_effect = RuntimeError('stream changed')
    getattr(player, callback)()
    player.cast.report_state_change.assert_not_called()


@pytest.mark.parametrize('callback, expected', [
    ('onPlayBackStopped', 'report_playback_stopped'),
    ('onPlayBackError', 'report_playback_stopped'),
    ('onPlayBackEnded', 'report_playback_ended'),
])
def test_stop_error_and_end_cannot_report_a_later_unrelated_video(player, callback, expected):
    getattr(player, callback)()
    assert player.from_yt is False
    getattr(player.cast, expected).assert_called_once()
    assert player.report_progress() is False
    player.cast.report_state_change.assert_not_called()


def test_non_cast_or_inactive_session_never_reports(player):
    player.from_yt = False
    assert player.report_progress() is False
    player.from_yt = True
    player.cast.has_client = False
    assert player.report_progress() is False
    player.getTime.assert_not_called()


def test_metadata_time_race_is_retried_instead_of_killing_reporter(player, mocker):
    clock = mocker.patch.object(module, 'monotonic', return_value=0)
    player.cast.report_now_playing.side_effect = [RuntimeError('stream changed'), None]
    player.onPlayBackStarted()
    assert player.report_progress() is True
    clock.return_value = 5
    assert player.report_progress() is True
    assert player.cast.report_now_playing.call_count == 2


def test_receiver_loop_drives_progress_instead_of_a_callback(player, mocker):
    from resources.lib.tubecast.youtube import app as app_module
    cast = app_module.YoutubeCastV1.__new__(app_module.YoutubeCastV1)
    cast.has_client = True
    cast.listener = None
    mocker.patch.object(app_module, 'CastPlayer', return_value=player)
    mocker.patch.object(player, 'report_progress')
    mocker.patch.object(app_module.monitor, 'abortRequested', side_effect=[False, False, True])
    mocker.patch.object(app_module.monitor, 'waitForAbort', return_value=False)
    getattr(cast, '_YoutubeCastV1__player_thread')()
    assert player.report_progress.call_count == 2
