# -*- coding: utf-8 -*-
import xbmc

from resources.lib.kodi import kodilogging
from resources.lib.kodi.utils import get_setting_as_bool
from resources.lib.tubecast.chromecast import Chromecast
from resources.lib.tubecast.kodicast import Kodicast, generate_uuid
from resources.lib.tubecast.ssdp import SSDPserver

logger = kodilogging.get_logger("service")
monitor = xbmc.Monitor()

MAX_WAIT_FOR_NETWORK = 120  # seconds
NETWORK_CHECK_INTERVAL = 2  # seconds


def wait_for_network():
    """Wait until the network is available or timeout is reached.

    Returns True if network is available, False if aborted.
    """
    waited = 0
    while not monitor.abortRequested() and waited < MAX_WAIT_FOR_NETWORK:
        ip = xbmc.getIPAddress()
        if ip and ip != '127.0.0.1' and ip != '0.0.0.0':
            logger.info('Network available (IP: %s) after %d seconds', ip, waited)
            return True
        if monitor.waitForAbort(NETWORK_CHECK_INTERVAL):
            return False
        waited += NETWORK_CHECK_INTERVAL
    logger.warning('Network wait timeout after %d seconds', MAX_WAIT_FOR_NETWORK)
    return not monitor.abortRequested()


def wait_for_kodi_ready():
    """Wait until Kodi is fully initialized (friendly name available).

    Returns True if ready, False if aborted.
    """
    waited = 0
    while not monitor.abortRequested() and waited < 30:
        friendly_name = xbmc.getInfoLabel("System.FriendlyName")
        if friendly_name:
            logger.info('Kodi ready (FriendlyName: %s) after %d seconds', friendly_name, waited)
            return True
        if monitor.waitForAbort(1):
            return False
        waited += 1
    logger.warning('Kodi ready wait timeout, continuing anyway')
    return not monitor.abortRequested()


def run():
    # Wait for Kodi to be fully initialized
    if not wait_for_kodi_ready():
        return

    # Wait for network to be available
    if not wait_for_network():
        return

    generate_uuid()

    # Start HTTP server
    chromecast = Chromecast(monitor)
    chromecast_addr = chromecast.start()
    logger.info('HTTP server started on %s:%s', *chromecast_addr)

    # Start SSDP service
    ssdp_started = False
    if get_setting_as_bool('enable-ssdp'):
        ssdp_server = SSDPserver()
        ssdp_server.start(chromecast_addr, interfaces=Kodicast.interfaces)
        ssdp_started = True

    while not monitor.abortRequested():
        monitor.waitForAbort(1)

    # Abort services
    if ssdp_started:
        ssdp_server.shutdown()
    chromecast.abort()
