"""
NetworkDeviceDriver — list-based pairing driver for individual network devices.

Pairing:
  1. Requires a Fingbox device to already be added and connected.
  2. Fetches the current device list from the Fingbox's FingAgent.
  3. Presents the list to the user; each device is identified by MAC address.
  4. Devices already paired in Homey are excluded from the list.
"""

import httpx
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from homey import driver


# Duplicated from device.py — Homey loads driver/device files as standalone
# modules, so we can't relative-import. Keep these in sync if either side
# changes.

def _resolve_timezone(homey=None):
    """See device.py for full docstring. Returns a ZoneInfo or None."""
    if homey is not None:
        try:
            tz_name = (homey.settings.get("timezone") or "").strip()
            if tz_name:
                return ZoneInfo(tz_name)
        except Exception:
            pass
        for path in ("clock", "geolocation"):
            mgr = getattr(homey, path, None)
            if mgr is None:
                continue
            for method_name in ("get_timezone", "getTimezone"):
                meth = getattr(mgr, method_name, None)
                if callable(meth):
                    try:
                        tz_name = meth()
                        if hasattr(tz_name, "__await__"):
                            continue
                        if tz_name:
                            return ZoneInfo(str(tz_name).strip())
                    except Exception:
                        pass
    tz_name = (os.environ.get("TZ") or "").strip()
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return None


def _fmt_timestamp(raw: str, tz=None) -> str:
    """Convert Fing UTC timestamp to 'YYYY-MM-DD HH:MM' in the given tz."""
    if not raw:
        return raw
    try:
        normalised = raw.strip()
        if normalised.endswith("Z"):
            normalised = normalised[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalised)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_local = dt.astimezone(tz) if tz is not None else dt.astimezone()
        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return raw


class NetworkDeviceDriver(driver.Driver):

    async def on_init(self):
        await super().on_init()
        self.log("NetworkDeviceDriver ready")

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    async def on_pair_list_devices(self, view_data: dict) -> list:
        """
        Called when the list_devices pairing view renders.
        Returns a list of Fing-tracked devices not yet added to Homey.
        """
        # ---- Locate the Fingbox device ----
        try:
            fingbox_driver = self.homey.drivers.get_driver("fingbox")
            fingbox_devices = fingbox_driver.get_devices()
        except Exception:
            fingbox_devices = []

        if not fingbox_devices:
            raise Exception(
                "Please add your Fingbox first before adding network devices."
            )

        fingbox = fingbox_devices[0]

        # ---- Fetch fresh device list from Fing ----
        try:
            agent    = fingbox.get_agent()
            response = await agent.get_devices()
            fing_devices = response.devices
        except httpx.ConnectError:
            raise Exception(
                "Fingbox is currently unreachable. "
                "Please check connectivity and try again."
            )
        except Exception as exc:
            # Log full detail locally; show a generic message to the UI so
            # internal library / network details aren't exposed.
            self.log(f"Pairing: failed to fetch device list from Fingbox: {exc!r}")
            raise Exception(
                "Failed to fetch device list from Fingbox. Please try again."
            )

        if not fing_devices:
            raise Exception(
                "No devices found on your Fing network. "
                "Make sure Fing has scanned your network recently."
            )

        # ---- Exclude already-paired MACs ----
        already_paired: set[str] = {
            d.get_store().get("mac_address", "").upper()
            for d in self.get_devices()
        }

        # ---- Build the pairing list ----
        result = []

        for dev in fing_devices:
            mac = dev.mac.upper()

            if mac in already_paired:
                continue

            ip_list = dev.ip or []
            ip_str  = ip_list[0] if ip_list else ""

            # Build a human-readable display name
            display_name = dev.name or mac
            if dev.make:
                display_name = f"{display_name} ({dev.make})"

            status = "online" if dev.active else "offline"

            result.append({
                "name": f"{display_name} — {status}",
                "data": {
                    # MAC is the stable unique identifier (not IP)
                    "id": mac,
                },
                "store": {
                    "mac_address": mac,
                    "fing_name":   dev.name or "",
                },
                "capabilities": [
                    "presence_status",
                    "alarm_presence",
                    "ip_address",
                    "last_seen",
                ],
                "capabilitiesOptions": {},
                "state": {
                    "presence_status": "present" if dev.active else "away",
                    "alarm_presence":  not dev.active,
                    "ip_address":      ip_str,
                    "last_seen":       _fmt_timestamp(dev.last_changed or "", tz=_resolve_timezone(self.homey)),
                },
            })

        if not result:
            raise Exception(
                "All Fing-tracked devices are already added to Homey. "
                "You can add more when new devices appear on your network."
            )

        return result


homey_export = NetworkDeviceDriver
