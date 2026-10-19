# -*- coding: utf-8 -*-
import hashlib
import json
import os
from urllib.parse import urlencode

from resources.lib.kodi import utils


class ProfileRoutingError(Exception):
    """Do not start a cast under an unknown YouTube profile."""


def _supports_profile_routing():
    # Package capability, not a saved setting that can outlive the fork.
    try:
        import xbmcaddon
        import xbmcvfs
        addon = xbmcaddon.Addon('plugin.video.youtube')
        path = os.path.join(addon.getAddonInfo('path'), 'resources', 'tubecast-profile-api.json')
        handle = xbmcvfs.File(path)
        try:
            return json.loads(handle.read()).get('version') == 1
        finally:
            handle.close()
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError, ImportError):
        return False


def get_kodi_volume():
    result = utils.kodi_json_request({"jsonrpc": "2.0",
                                      "method": "Application.GetProperties",
                                      "params": {"properties": ["volume"]},
                                      "id": 7})
    return result["volume"]


def set_kodi_volume(volume):
    utils.kodi_json_request({"jsonrpc": "2.0",
                             "method": "Application.SetVolume",
                             "params": {"volume": volume}, "id": 8})


def get_youtube_plugin_path(videoid, seek=0, sender=None):
    # playback-addon: 0 = YouTube, 1 = Tubed
    if utils.get_setting_as_int("playback-addon") == 1:
        return "plugin://plugin.video.tubed/?mode=play&video_id={}&start_offset={}".format(
            videoid, float(seek))
    if not utils.get_setting_as_bool('phone-profiles'):
        return "plugin://plugin.video.youtube/play/?video_id={}&seek={}".format(
            videoid, float(seek))
    sender_id = sender.get('id') if isinstance(sender, dict) else None
    if not isinstance(sender_id, str) or not sender_id.strip():
        raise ProfileRoutingError('Missing or ambiguous phone identity')
    if not _supports_profile_routing():
        raise ProfileRoutingError('Install the profile-aware YouTube companion add-on')
    params = {
        'video_id': videoid,
        'seek': float(seek),
        'cast_device': hashlib.sha256(sender_id.encode('utf-8')).hexdigest(),
        'cast_name': str(sender.get('name') or sender.get('clientName') or 'TubeCast')[:80],
    }
    return 'plugin://plugin.video.youtube/play/?' + urlencode(params)


def remote_connected(name):
    utils.notification(message="{} {}!".format(name, utils.get_string(32006)))


def remote_disconnected(name):
    utils.notification(message="{} {}!".format(name, utils.get_string(32007)))
