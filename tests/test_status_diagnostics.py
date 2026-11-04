"""Status-only diagnostics must not change transport or expose identity data."""
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from resources.lib.tubecast.youtube import app as module


@pytest.fixture
def receiver(mocker):
    app = module.YoutubeCastV1.__new__(module.YoutubeCastV1)
    app.ofs = 0
    app.base_url = 'https://synthetic.invalid'
    app.bind_vals = {'SID': 'synthetic-private-session',
                     'loungeIdToken': 'synthetic-private-token'}
    app.session = Mock()
    mocker.patch.object(module, 'get_setting_as_bool', return_value=False)
    return app


@pytest.mark.parametrize('status', [200, 400, 500])
def test_send_status_is_visible_without_payload_or_session(receiver, status, caplog):
    receiver.session.post.return_value.status_code = status
    with caplog.at_level(logging.INFO):
        getattr(receiver, '_YoutubeCastV1__post_bind')('onStateChange', {'private': 'synthetic-private-body'})
    assert 'Lounge send onStateChange: HTTP {}'.format(status) in caplog.text
    for secret in ['synthetic-private-session', 'synthetic-private-token',
                   'synthetic-private-body', 'https://synthetic.invalid']:
        assert secret not in caplog.text
    # Diagnostics deliberately preserve the old request/retry semantics.
    assert receiver.session.post.call_count == 1


def test_dial_start_logs_no_pairing_code(receiver, mocker, caplog):
    receiver._pair = Mock()
    mocker.patch.object(module, 'request', SimpleNamespace(forms={'pairingCode': 'synthetic-private-pairing'}))
    mocker.patch.object(module, 'response', SimpleNamespace())
    with caplog.at_level(logging.INFO):
        receiver._register_listener()
    assert 'DIAL receiver start requested' in caplog.text
    assert 'synthetic-private-pairing' not in caplog.text
    receiver._pair.assert_called_once_with('synthetic-private-pairing')


def test_dial_stop_can_be_distinguished_from_remote_disconnected(receiver, mocker, caplog):
    receiver._initial_app_state = Mock()
    mocker.patch.object(module, 'response', SimpleNamespace())
    with caplog.at_level(logging.INFO):
        receiver._remove_listener()
    assert 'DIAL receiver stop requested' in caplog.text
    receiver._initial_app_state.assert_called_once()


def test_receive_status_and_end_are_logged_without_url(receiver, caplog):
    response = MagicMock(status_code=200)
    response.iter_content.return_value = iter([b'synthetic-chunk'])
    receiver.session.get.return_value.__enter__ = Mock(return_value=response)
    receiver.session.get.return_value.__exit__ = Mock(return_value=False)
    listener = module.YoutubeListener(receiver)
    with caplog.at_level(logging.INFO):
        chunks = list(getattr(listener, '_YoutubeListener__read_cmd_chunks')(
            'https://synthetic.invalid/?SID=synthetic-private-session'))
    assert chunks == [b'synthetic-chunk']
    assert 'Lounge receive channel: HTTP 200' in caplog.text
    assert 'Lounge receive stream ended (stop=False)' in caplog.text
    assert 'synthetic-private-session' not in caplog.text
    assert 'synthetic-chunk' not in caplog.text
    response.raise_for_status.assert_called_once()
