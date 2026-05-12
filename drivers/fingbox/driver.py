"""
FingboxDriver — manual pairing driver for the Fingbox hardware unit.

Pairing flow:
  1. start_pairing  — instructions screen (template)
  2. credentials    — custom HTML form (pair/credentials.html)
  3. add_devices    — Homey confirmation screen (template)

The HTML form emits 'test_connection' with {ip, port, key}.
We validate by calling get_agent_info(), then store credentials and
return the device via on_pair_list_devices so add_devices can show it.
"""

import httpx
from fing_agent_api import FingAgent
from homey import driver


class FingboxDriver(driver.Driver):

    async def on_init(self):
        await super().on_init()
        # Temporary storage during an active pairing session.
        # Populated by the 'test_connection' handler; read by on_pair_list_devices.
        self._temp_credentials: dict = {}
        self.log("FingboxDriver ready")

    # ------------------------------------------------------------------
    # Pairing — event handler for the custom 'credentials' view
    # ------------------------------------------------------------------

    async def on_pair_event(self, event: str, data: dict):
        """
        Receives events emitted from pair/credentials.html via Homey.emit().
        Returns a value that becomes the callback result in the HTML.
        Raising an exception sends the error message back to the HTML.
        """
        if event == "test_connection":
            ip  = str(data.get("ip",  "")).strip()
            port = int(data.get("port", 49090))
            key = str(data.get("key",  "")).strip()

            if not ip or not key:
                raise Exception(
                    "Please enter an IP address and API key."
                )

            self.log(f"Testing connection to Fingbox at {ip}:{port}")

            try:
                agent = FingAgent(ip, port, key)
                info  = await agent.get_agent_info()
            except httpx.ConnectError:
                raise Exception(
                    "Could not connect to Fingbox. "
                    "Check the IP address and port, and make sure the Fingbox is online."
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
                raise Exception(f"Unexpected error: {exc}")

            # Extract a friendly name for the device (may be None)
            friendly_name = getattr(info, "friendly_name", None) or "Fingbox"

            # Stash credentials so on_pair_list_devices can use them
            self._temp_credentials = {
                "ip":           ip,
                "port":         port,
                "key":          key,
                "friendly_name": friendly_name,
            }

            self.log(f"Fingbox connection verified — name: {friendly_name}")
            return {"ok": True, "name": friendly_name}

    # ------------------------------------------------------------------
    # Pairing — device list for the add_devices template
    # ------------------------------------------------------------------

    async def on_pair_list_devices(self, view_data: dict) -> list:
        """
        Called by the add_devices template to get the list of devices to add.
        Returns the single Fingbox device built from temp credentials.
        """
        if not self._temp_credentials:
            raise Exception(
                "No connection details available. "
                "Please go back and enter your Fingbox credentials."
            )

        creds = self._temp_credentials
        ip    = creds["ip"]

        # Derive a stable device ID from the IP.
        # One Fingbox per app instance is expected, but the ID must be unique.
        device_id = f"fingbox-{ip.replace('.', '-')}"

        return [
            {
                "name": creds["friendly_name"],
                "data": {
                    "id": device_id,
                },
                "store": {
                    # api_key goes in store (encrypted), NOT in settings (user-visible)
                    "ip":      ip,
                    "port":    creds["port"],
                    "api_key": creds["key"],
                },
                "capabilities": [
                    "alarm_connectivity",
                    "measure_generic.online_count",
                ],
                "settings": {
                    "ip":   ip,
                    "port": creds["port"],
                },
            }
        ]


homey_export = FingboxDriver
