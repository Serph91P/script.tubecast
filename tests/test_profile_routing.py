"""Companion protocol tests; Kodi/network/player are explicitly mocked."""
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

from resources.lib.tubecast.youtube import kodibrigde as bridge
from resources.lib.tubecast.youtube.app import CastState, YoutubeCastV1


@pytest.fixture
def settings(mocker):
    mocker.patch.object(bridge.utils, 'get_setting_as_int', return_value=0)
    return mocker.patch.object(bridge.utils, 'get_setting_as_bool', return_value=True)


def test_legacy_url_is_unchanged_when_disabled(settings):
    settings.return_value = False
    assert bridge.get_youtube_plugin_path('synthetic', 2) == 'plugin://plugin.video.youtube/play/?video_id=synthetic&seek=2.0'


def test_profile_url_uses_opaque_identity_and_encodes_display_name(settings, mocker):
    mocker.patch.object(bridge, '_supports_profile_routing', return_value=True)
    url = bridge.get_youtube_plugin_path('synthetic', 2, sender={'id': 'device-A', 'name': 'Phone & A'})
    params = parse_qs(urlsplit(url).query)
    assert params['cast_device'] == [sha256(b'device-A').hexdigest()]
    assert params['cast_name'] == ['Phone & A']
    assert 'device-A' not in url


@pytest.mark.parametrize('sender', [None, {}, {'name': 'A'}, {'id': ''}])
def test_missing_identity_aborts_instead_of_using_active_profile(settings, sender):
    with pytest.raises(bridge.ProfileRoutingError):
        bridge.get_youtube_plugin_path('synthetic', sender=sender)


def test_unpatched_youtube_fails_closed(settings, mocker):
    mocker.patch.object(bridge, '_supports_profile_routing', return_value=False)
    with pytest.raises(bridge.ProfileRoutingError):
        bridge.get_youtube_plugin_path('synthetic', sender={'id': 'A'})


def test_package_marker_detects_real_installed_companion(tmp_path, mocker):
    import sys
    import types
    import xbmcaddon
    resources = tmp_path / 'resources'
    resources.mkdir()
    marker = resources / 'tubecast-profile-api.json'
    mocker.patch.object(xbmcaddon.Addon, 'getAddonInfo', return_value=str(tmp_path))
    mocker.patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(File=lambda path: open(path))})
    assert not bridge._supports_profile_routing()
    marker.write_text('{"version": 1}')
    assert bridge._supports_profile_routing()
    marker.write_text('{"version": 2}')
    assert not bridge._supports_profile_routing()
    marker.write_text('broken')
    assert not bridge._supports_profile_routing()


def test_backend_captions_match_actual_routing():
    from pathlib import Path
    from xml.etree import ElementTree as ET
    path = Path(__file__).resolve().parents[1] / 'resources/settings.xml'
    setting = ET.parse(path).find('.//setting[@id="playback-addon"]')
    assert {option.text: option.attrib['label'] for option in setting.findall('.//option')} == {
        '0': '32018', '1': '32017',
    }


def test_tubed_is_unaffected(settings, mocker):
    mocker.patch.object(bridge.utils, 'get_setting_as_int', return_value=1)
    assert bridge.get_youtube_plugin_path('synthetic', 2) == 'plugin://plugin.video.tubed/?mode=play&video_id=synthetic&start_offset=2.0'


@pytest.fixture
def app(mocker):
    instance = YoutubeCastV1.__new__(YoutubeCastV1)
    instance.screen_uid = instance.default_screen_name = instance.default_screen_app = 'fixture'
    instance.listener = None
    instance.player = Mock()
    instance.player.isPlaying.return_value = False
    instance.volume_monitor = Mock()
    instance._initial_app_state()
    mocker.patch.object(instance, '_disable_autoplay')
    mocker.patch('resources.lib.tubecast.youtube.app.get_setting_as_bool', side_effect=lambda key: key == 'phone-profiles')
    mocker.patch.object(instance, 'report_state_change')
    mocker.patch.object(instance, 'report_now_playing')
    mocker.patch.object(bridge, 'remote_connected')
    mocker.patch.object(bridge, 'remote_disconnected')
    mocker.patch.object(bridge.utils, 'notification')
    mocker.patch.object(bridge.utils, 'get_setting_as_int', return_value=0)
    return instance


def connect(app, sequence=1, sender='phone-A'):
    app.handle_cmd((sequence, 'remoteConnected', {'id': sender, 'name': sender}))


def playlist(app, sequence=2):
    app.handle_cmd((sequence, 'setPlaylist', {'listId': 'queue-A', 'videoId': 'video-A', 'videoIds': 'video-A,video-B', 'currentIndex': '0', 'currentTime': '3'}))


def test_all_playback_paths_forward_same_sender(app, mocker):
    get_url = mocker.patch.object(bridge, 'get_youtube_plugin_path', return_value='fixture-url')
    connect(app)
    playlist(app)
    app._next()
    app._previous()
    app._resume()
    app.report_playback_ended()
    assert get_url.call_count == 5
    for call in get_url.call_args_list:
        assert call.kwargs['sender'] == {'id': 'phone-A', 'name': 'phone-A'}


def test_second_phone_cannot_take_over_existing_queue(app, mocker):
    get_url = mocker.patch.object(bridge, 'get_youtube_plugin_path', return_value='fixture-url')
    connect(app)
    playlist(app)
    connect(app, sequence=3, sender='phone-B')
    app._next()
    assert get_url.call_count == 1


def test_disconnect_forgets_phone_and_queue_owner(app, mocker):
    get_url = mocker.patch.object(bridge, 'get_youtube_plugin_path', return_value='fixture-url')
    connect(app)
    playlist(app)
    app.handle_cmd((3, 'remoteDisconnected', {'id': 'phone-A', 'name': 'phone-A'}))
    app._play_video()
    assert get_url.call_args.kwargs['sender'] is None


def test_routing_failure_does_not_start_player(app, mocker):
    mocker.patch.object(bridge, 'get_youtube_plugin_path', side_effect=bridge.ProfileRoutingError('fixture'))
    connect(app)
    playlist(app)
    app.player.play_from_youtube.assert_not_called()
    bridge.utils.notification.assert_called_once()
