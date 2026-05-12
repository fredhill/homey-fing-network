"""
Fing Network Monitor — Homey Python app entry point.

The App class acts as a lightweight shared-state container.
Heavy lifting lives in the driver and device classes.

Shared state:
  app.device_state — dict keyed by uppercase MAC address.
    Each value: { online: bool, ip: str, last_changed: str, name: str }
    Written by FingboxDevice after every poll.
    Read by NetworkDeviceDevice.refresh_from_state().
"""

from homey import app


class FingNetworkMonitorApp(app.App):

    async def on_init(self):
        await super().on_init()

        # Shared state dict: { "AA:BB:CC:DD:EE:FF": { online, ip, last_changed, name } }
        # Initialised to empty so NetworkDeviceDevice can safely read it
        # even before the first poll completes.
        self.device_state: dict[str, dict] = {}

        self.log("Fing Network Monitor started")


homey_export = FingNetworkMonitorApp
