"""
FingboxDevice — the Fingbox hub device.

Responsibilities:
  - Owns the FingAgent instance and the single polling loop.
  - Writes a shared state dict to app.device_state after every poll.
    Shape: { "AA:BB:CC:DD:EE:FF": { online, ip, last_changed, name } }
  - Updates alarm_connectivity and measure_generic.online_count capabilities.
  - Fires the new_unknown_device flow trigger for online devices not yet
    paired in Homey, deduplicating within a session.
  - Notifies all NetworkDeviceDevice instances to refresh their state.
"""

import asyncio
import httpx
from fing_agent_api import FingAgent
from homey import device

# Seconds between polls (read from app settings each cycle, with this fallback)
DEFAULT_POLL_INTERVAL = 30
MIN_POLL_INTERVAL     = 10
MAX_POLL_INTERVAL     = 300

# How many consecutive empty device-list responses before we trust it
# and mark all network devices offline (guards against momentary API blips)
CONSECUTIVE_EMPTY_THRESHOLD = 2

# Defensive caps for untrusted Fing API data
MAX_NAME_LENGTH       = 200    # device names are passed into flow tokens / logs
MAX_SEEN_MACS         = 500    # bound the in-memory dedup set


class FingboxDevice(device.Device):

    async def on_init(self):
        await super().on_init()

        # Read connection config from device store (populated during pairing)
        store = self.get_store()
        self._ip      = store.get("ip",      "")
        self._api_key = store.get("api_key", "")

        # Guard against a corrupt/missing port value crashing device init
        try:
            self._port = int(store.get("port", 49090))
        except (TypeError, ValueError):
            self._port = 49090

        # Security: the API key was also written to app settings during pairing
        # so the user could type it into the pairing form.  Now that it lives
        # in the encrypted device store we no longer need it in plain-text
        # settings — clear it so it isn't sitting around unnecessarily.
        try:
            if self.homey.settings.get("fingbox_api_key"):
                self.homey.settings.set("fingbox_api_key", "")
        except Exception:
            pass  # Best-effort; non-fatal if settings manager isn't ready yet

        # Runtime state
        self._poll_task: asyncio.Task | None = None
        self._consecutive_empty: int = 0
        # MACs that have already triggered new_unknown_device this session
        self._session_seen_macs: set[str] = set()

        # FingAgent: synchronous constructor, all methods are async
        self._agent = FingAgent(self._ip, self._port, self._api_key)

        # Cache the flow trigger card (fetched once at init)
        self._unknown_trigger = self.homey.flow.get_trigger_card("new_unknown_device")

        self.log(f"FingboxDevice initialising — {self._ip}:{self._port}")

        # Fire-and-forget: quick initial connectivity check (non-blocking)
        asyncio.create_task(self._initial_check())

        # Start the main poll loop
        self._poll_task = asyncio.create_task(self._poll_loop())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_deleted(self):
        """Cancel the poll loop cleanly when the device is removed."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self.log("FingboxDevice removed — poll loop stopped")

    async def on_settings(self, old_settings: dict, new_settings: dict, changed_keys: list):
        """Rebuild FingAgent if IP or port changes in device settings."""
        if "ip" in changed_keys or "port" in changed_keys:
            self._ip = new_settings.get("ip", self._ip)
            try:
                self._port = int(new_settings.get("port", self._port))
            except (TypeError, ValueError):
                self._port = 49090
            self._agent = FingAgent(self._ip, self._port, self._api_key)
            self.log(f"Connection updated — {self._ip}:{self._port}")

    # ------------------------------------------------------------------
    # Public accessor (used by NetworkDeviceDriver during pairing)
    # ------------------------------------------------------------------

    def get_agent(self) -> FingAgent:
        return self._agent

    # ------------------------------------------------------------------
    # Initial connectivity check (runs once at startup)
    # ------------------------------------------------------------------

    async def _initial_check(self):
        try:
            await self._agent.get_agent_info()
            await self.set_capability_value("alarm_connectivity", False)  # False = no problem
            await self.set_available()
            self.log("Fingbox reachable — initial check passed")
        except Exception as exc:
            self.log(f"Initial check failed: {exc}")
            await self.set_capability_value("alarm_connectivity", True)   # True = connection lost
            await self.set_unavailable("Fingbox is unreachable")

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _poll_loop(self):
        """
        Infinite loop — sleeps for the configured interval then runs _poll().
        Cancelled cleanly by on_deleted().
        """
        while True:
            try:
                await asyncio.sleep(self._get_poll_interval())
                await self._poll()
            except asyncio.CancelledError:
                self.log("Poll loop cancelled")
                return
            except Exception as exc:
                # Unexpected error — log and keep going
                self.log(f"Unhandled error in poll loop: {exc}")

    def _get_poll_interval(self) -> int:
        """Read poll_interval from app settings with bounds-checking."""
        try:
            raw = self.homey.settings.get("poll_interval")
            if raw is not None:
                val = int(raw)
                if MIN_POLL_INTERVAL <= val <= MAX_POLL_INTERVAL:
                    return val
        except Exception:
            pass
        return DEFAULT_POLL_INTERVAL

    # ------------------------------------------------------------------
    # Single poll cycle
    # ------------------------------------------------------------------

    async def _poll(self):
        """
        Fetches the full device list from Fing, updates shared state,
        fires triggers, and notifies NetworkDeviceDevice instances.
        """
        # ---- Fetch devices ----
        try:
            response = await self._agent.get_devices()
            devices  = response.devices  # list[fing_agent_api.models.Device]
        except httpx.ConnectError:
            self.log("Poll: ConnectError — Fingbox unreachable")
            await self._on_connectivity_lost()
            return
        except httpx.TimeoutException:
            self.log("Poll: request timed out")
            await self._on_connectivity_lost()
            return
        except httpx.HTTPStatusError as exc:
            self.log(f"Poll: HTTP {exc.response.status_code}")
            await self._on_connectivity_lost()
            return
        except asyncio.CancelledError:
            raise  # Must propagate so the loop can exit
        except Exception as exc:
            self.log(f"Poll: unexpected error: {exc}")
            await self._on_connectivity_lost()
            return

        # ---- Mark connected (False = no alarm = all good) ----
        await self.set_capability_value("alarm_connectivity", False)
        await self.set_available()

        # ---- Handle empty response ----
        if not devices:
            self._consecutive_empty += 1
            self.log(
                f"Poll: empty device list "
                f"(consecutive: {self._consecutive_empty}/{CONSECUTIVE_EMPTY_THRESHOLD})"
            )
            if self._consecutive_empty >= CONSECUTIVE_EMPTY_THRESHOLD:
                self.log("Poll: consecutive empties threshold reached — marking all offline")
                await self._mark_all_network_devices_offline()
            return

        # ---- Non-empty response ----
        self._consecutive_empty = 0
        paired_macs = self._get_paired_network_device_macs()
        new_state: dict[str, dict] = {}

        # Defensive: cap dedup set so a flood of one-off MACs (rogue AP,
        # randomised-MAC privacy clients, etc.) can't grow it without bound.
        if len(self._session_seen_macs) > MAX_SEEN_MACS:
            self.log(
                f"Pruning session_seen_macs (was {len(self._session_seen_macs)} entries)"
            )
            # Drop everything that isn't in the current device list — that
            # gives us a fresh window without losing entries for devices
            # actually present.
            current_macs = {d.mac.upper() for d in devices if getattr(d, "mac", None)}
            self._session_seen_macs &= current_macs

        for dev in devices:
            mac      = (dev.mac or "").upper()           # normalise to uppercase
            if not mac:
                continue                                  # skip malformed entries
            ip_list  = dev.ip or []
            ip_str   = ip_list[0] if ip_list else ""
            # Bound untrusted device name length before it flows into logs,
            # flow tokens, or capability values.
            name     = (dev.name or "Unknown")[:MAX_NAME_LENGTH]

            new_state[mac] = {
                "online":        dev.active,
                "ip":            ip_str,
                "last_changed":  dev.last_changed or "",
                "name":          name,
            }

            # Fire unknown-device trigger if: online, not paired, not already seen this session
            if (
                dev.active
                and mac not in paired_macs
                and mac not in self._session_seen_macs
            ):
                self._session_seen_macs.add(mac)
                asyncio.create_task(
                    self._fire_unknown_trigger(name=name, mac=mac, ip=ip_str)
                )

        # ---- Write shared state ----
        self.homey.app.device_state = new_state

        # ---- Update online count ----
        online_count = sum(1 for s in new_state.values() if s["online"])
        await self.set_capability_value("online_count", online_count)

        # ---- Update agent health info (best-effort; may fail on some configurations) ----
        asyncio.create_task(self._update_agent_info())

        # ---- Notify paired NetworkDeviceDevices to refresh ----
        await self._notify_network_devices()

    async def _on_connectivity_lost(self):
        """Called when any poll attempt fails."""
        await self.set_capability_value("alarm_connectivity", True)   # True = connection lost
        await self.set_unavailable("Fingbox is unreachable")

    # ------------------------------------------------------------------
    # Agent info update (best-effort, runs after poll)
    # ------------------------------------------------------------------

    async def _update_agent_info(self):
        """
        Refreshes connectivity status from get_agent_info().
        This may fail on some Fingbox firmware versions — suppress errors.
        """
        try:
            await self._agent.get_agent_info()
            # If we get here, the agent is reachable — no alarm
            await self.set_capability_value("alarm_connectivity", False)
        except Exception:
            pass  # Already reflected in alarm_connectivity from _poll

    # ------------------------------------------------------------------
    # Flow trigger
    # ------------------------------------------------------------------

    async def _fire_unknown_trigger(self, name: str, mac: str, ip: str):
        """Fire the new_unknown_device trigger for one device."""
        try:
            tokens = {
                "device_name": name,
                "mac_address": mac,
                "ip_address":  ip,
            }
            await self._unknown_trigger.trigger(self, tokens, {})
            self.log(f"Trigger fired — unknown device: {name} ({mac}) @ {ip}")
        except Exception as exc:
            self.log(f"Failed to fire unknown-device trigger: {exc}")

    # ------------------------------------------------------------------
    # Cross-driver helpers
    # ------------------------------------------------------------------

    def _get_paired_network_device_macs(self) -> set[str]:
        """
        Returns the set of MAC addresses for all currently-paired
        NetworkDeviceDevice instances (used for trigger deduplication).
        """
        macs: set[str] = set()
        try:
            nd_driver = self.homey.drivers.get_driver("network_device")
            for device in nd_driver.get_devices():
                mac = device.get_store().get("mac_address", "").upper()
                if mac:
                    macs.add(mac)
        except Exception as exc:
            self.log(f"Could not read paired network-device MACs: {exc}")
        return macs

    async def _notify_network_devices(self):
        """
        Asks every paired NetworkDeviceDevice to refresh its capabilities
        from the shared state dict.  Fire-and-forget per device.
        """
        try:
            nd_driver = self.homey.drivers.get_driver("network_device")
            for device in nd_driver.get_devices():
                asyncio.create_task(device.refresh_from_state())
        except Exception as exc:
            self.log(f"Error notifying network devices: {exc}")

    async def _mark_all_network_devices_offline(self):
        """
        Mark every paired NetworkDeviceDevice as not present.
        Called only after CONSECUTIVE_EMPTY_THRESHOLD empty responses.
        """
        try:
            nd_driver = self.homey.drivers.get_driver("network_device")
            for device in nd_driver.get_devices():
                asyncio.create_task(device.update_presence(online=False))
        except Exception as exc:
            self.log(f"Error marking network devices offline: {exc}")


homey_export = FingboxDevice
