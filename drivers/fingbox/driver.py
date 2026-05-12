"""
FingboxDriver — pairing driver for the Fingbox hardware unit.

Pairing flow:
  1. list_devices  — calls on_pair_list_devices, which reads connection
                     details from the app settings page (fingbox_ip,
                     fingbox_port, fingbox_api_key).  If any setting is
                     missing the user gets a clear error message telling
                     them to fill in the app settings first.
  2. add_devices   — standard Homey confirmation screen.

Credentials are stored in the device store (encrypted) after pairing, so
FingboxDevice can read them without touching app settings again.
"""

import httpx
from fing_agent_api import FingAgent
from homey import driver


class FingboxDriver(driver.Driver):

    async def on_init(self):
        await super().on_init()
        self.log("FingboxDriver ready")

    # ------------------------------------------------------------------
    # Pairing — reads credentials from app settings
    # ------------------------------------------------------------------

    async def on_pair_list_devices(self, view_data: dict) -> list:
        """
        Called when the list_devices pairing view renders.
        Reads Fingbox connection details from app settings, validates the
        connection, and returns a single device entry for the Fingbox.
        """
        # ---- Read from app settings ----
        ip      = str(self.homey.settings.get("fingbox_ip")      or "").strip()
        port    = self.homey.settings.get("fingbox_port")
        api_key = str(self.homey.settings.get("fingbox_api_key") or "").strip()

        if not ip or not api_key:
            raise Exception(
                "Please open the Fing Network Monitor app settings and enter "
                "your Fingbox IP address and API key before adding the device."
            )

        try:
            port = int(port) if port is not None else 49090
        except (ValueError, TypeError):
            port = 49090

        self.log(f"Pairing: testing connection to Fingbox at {ip}:{port}")

        # ---- Validate connection ----
        try:
            agent = FingAgent(ip, port, api_key)
            info  = await agent.get_agent_info()
        except httpx.ConnectError:
            raise Exception(
                f"Could not connect to Fingbox at {ip}:{port}. "
                "Check the IP address and make sure the Fingbox is powered on."
            )
        except httpx.TimeoutException:
            raise Exception(
                "Connection timed out. "
                "Check that the Fingbox is powered on and reachable."
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise Exception(
                    "Invalid API key. "
                    "Check the key in the Fing app under Fingbox → Settings → Local API."
                )
            raise Exception(
                f"Fingbox returned an unexpected error (HTTP {exc.response.status_code})."
            )
        except Exception as exc:
            raise Exception(f"Unexpected error connecting to Fingbox: {exc}")

        friendly_name = getattr(info, "friendly_name", None) or "Fingbox"
        device_id = f"fingbox-{ip.replace('.', '-')}"

        self.log(f"Pairing: Fingbox verified — {friendly_name} ({ip}:{port})")

        return [
            {
                "name": friendly_name,
                "data": {
                    "id": device_id,
                },
                "store": {
                    # Store credentials in device store (encrypted by Homey)
                    "ip":      ip,
                    "port":    port,
                    "api_key": api_key,
                },
                "capabilities": [
                    "alarm_connectivity",
                    "online_count",
                ],
                "settings": {
                    "ip":   ip,
                    "port": port,
                },
            }
        ]


homey_export = FingboxDriver
