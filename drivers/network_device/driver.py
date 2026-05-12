"""
NetworkDeviceDriver — list-based pairing driver for individual network devices.

Pairing:
  1. Requires a Fingbox device to already be added and connected.
  2. Fetches the current device list from the Fingbox's FingAgent.
  3. Presents the list to the user; each device is identified by MAC address.
  4. Devices already paired in Homey are excluded from the list.
"""

import httpx
from homey import driver


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
            raise Exception(f"Failed to fetch device list from Fingbox: {exc}")

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
                    "alarm_presence",
                    "ip_address",
                    "last_seen",
                ],
                # Pre-populate initial capability values
                "capabilitiesOptions": {},
                "state": {
                    "alarm_presence": dev.active,
                    "ip_address":     ip_str,
                    "last_seen":      dev.last_changed or "",
                },
            })

        if not result:
            raise Exception(
                "All Fing-tracked devices are already added to Homey. "
                "You can add more when new devices appear on your network."
            )

        return result


homey_export = NetworkDeviceDriver
