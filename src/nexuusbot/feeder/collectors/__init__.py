"""Platform readers for the feeder: the macOS Notification Center reader
and the Windows WPN alert reader, one module per local alert store."""

from nexuusbot.feeder.collectors.mac_notifications import MacNotificationCollector
from nexuusbot.feeder.collectors.wpn import WpnCollector

__all__ = ["MacNotificationCollector", "WpnCollector"]
