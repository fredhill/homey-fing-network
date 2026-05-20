"""
NetworkDeviceDevice — represents one network device tracked by Fing.

State is driven entirely by FingboxDevice after each poll cycle:
  - FingboxDevice writes to app.device_state (keyed by MAC address)
  - FingboxDevice calls device.refresh_from_state() on each NetworkDeviceDevice
  - This device reads its entry and updates its Homey capabilities

Capabilities:
  presence_status  — enum: "present" or "away" (human-readable text on card)
  alarm_presence   — true = away (alarm), false = home (no alarm); drives visual indicator + flows
  ip_address       — current IP (updates on DHCP reassignment)
  last_seen        — ISO timestamp of last Fing state-change event
"""

import asyncio
from datetime import datetime, timezone
from homey import device


def _fmt_timestamp(raw: str) -> str:
    """
    Convert a Fing UTC timestamp to a clean "YYYY-MM-DD HH:MM" string in the
    system's local timezone (i.e. whatever timezone the Raspberry Pi is set to).

    Fing always returns UTC timestamps, e.g.:
      "2026-05-12T21:06:32Z"      (Z suffix = UTC)
      "2026-05-12T21:06:32+00:00" (explicit UTC offset)
      "2026-05-12T21:06:32"       (no suffix — also treated as UTC)

    Falls back to the original string if parsing fails.
    """
    if not raw:
        return raw
    try:
        normalised = raw.strip()

        # datetime.fromisoformat() (Python 3.11+) understands +HH:MM offsets
        # but NOT the trailing "Z" shorthand — replace it first.
        if normalised.endswith("Z"):
            normalised = normalised[:-1] + "+00:00"

        dt = datetime.fromisoformat(normalised)

        # If the timestamp has no timezone info assume it is UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert to the host system's local timezone (e.g. America/New_York)
        dt_local = dt.astimezone()

        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return raw


class NetworkDeviceDevice(device.Device):

    async def on_init(self):
        await super().on_init()

        store = self.get_store()
        self._mac: str = store.get("mac_address", "").upper()

        self.log(f"NetworkDeviceDevice initialising — MAC: {self._mac}")

        # Attempt to populate capabilities from whatever state is already available
        asyncio.create_task(self.refresh_from_state())

    # ------------------------------------------------------------------
    # State refresh (called by FingboxDevice after each poll)
    # ------------------------------------------------------------------

    async def refresh_from_state(self):
        """
        Reads the shared app.device_state dict and updates capabilities.
        Safe to call even before the first poll — does nothing if the MAC
        is not yet present in the state dict.
        """
        if not self._mac:
            return

        try:
            state_dict: dict = self.homey.app.device_state
        except AttributeError:
            # App hasn't initialised device_state yet (very early startup)
            return

        entry = state_dict.get(self._mac)
        if entry is None:
            # Device not seen in the last poll; leave current capabilities unchanged
            return

        try:
            await self.update_presence(entry["online"])

            if entry.get("ip"):
                await self.set_capability_value("ip_address", entry["ip"])

            if entry.get("last_changed"):
                await self.set_capability_value("last_seen", _fmt_timestamp(entry["last_changed"]))

        except Exception as exc:
            self.log(f"refresh_from_state error for {self._mac}: {exc}")

    # ------------------------------------------------------------------
    # Presence update (also called directly by FingboxDevice for bulk-offline)
    # ------------------------------------------------------------------

    async def update_presence(self, online: bool):
        """
        Sets the alarm_presence capability.

        Homey flashes red when an alarm_* capability is True, so we use the
        inverted convention that makes UX sense for presence:
          alarm_presence = False  →  home / present  →  quiet (white)
          alarm_presence = True   →  away / not present  →  red alert

        This also makes flow cards read naturally:
          "alarm_presence turned on"  =  "device left home"
          "alarm_presence turned off" =  "device arrived home"

        NOTE: We deliberately do NOT call set_unavailable() when a device
        goes offline. set_unavailable() in Homey means 'the SDK cannot
        communicate with the device' (greys out the tile with a warning).
        Being absent from the network is a normal, expected state.
        """
        try:
            await self.set_capability_value("presence_status", "present" if online else "away")
            await self.set_capability_value("alarm_presence", not online)
            if online:
                await self.set_available()
        except Exception as exc:
            self.log(f"update_presence error for {self._mac}: {exc}")


homey_export = NetworkDeviceDevice
