# Homey App Store Submission

Reference notes for when this app is submitted to the Homey App Store via
`npx homey app publish` and the developer portal at
<https://apps.developer.homey.app/>.

---

## Long description (paste into the developer portal)

Fing Network Monitor turns your Fingbox into a real-time presence-detection
and network-security hub for Homey. Add any device that Fing already tracks
— phones, tablets, laptops, smart-home gear — as an individual Homey device,
and use its presence in flows: turn on the lights when someone arrives, arm
the alarm when everyone has left, or notify you when the kids get home. The
Fingbox itself appears as a hub device showing the live count of devices on
your network, with an alert if connectivity to the box is ever lost.

Every check happens locally — the app talks directly to your Fingbox over
your LAN, so nothing about your network is ever sent to a cloud relay. The
Fing API key is held in Homey's encrypted device store and is never
displayed back after pairing. A built-in flow trigger fires the moment an
unknown device appears on your network, with its name, MAC address, and
IP available as tokens, making it easy to wire up notifications, lighting
cues, or any other automation for guest detection and unauthorised-device
alerts. Requires a Fingbox with the Local API enabled (Fing app → Fingbox
→ Settings → Local API).

---

## Submission checklist

- [ ] Re-run final smoke tests (pairing, flows, settings save round-trip)
- [ ] Confirm version in `app.json` is `1.0.0` (or bumped if you've made
      meaningful changes since the last submission)
- [ ] Confirm `.homeychangelog.json` has an entry for the current version
- [ ] `npx homey app validate --level publish` passes (already passing)
- [ ] Gather screenshots for the portal:
  - Fingbox device card with online count
  - A Network Device card showing "Present" with the house icon
  - Settings page showing the timezone dropdown
  - Optional: an example flow card
- [ ] Confirm support contact: `fredhill@mac.com`
- [ ] Confirm homepage URL: <https://github.com/fredhill/homey-fing-network>

---

## Publish flow

```bash
cd /Users/fredhill/Developer/homey-fing
npx homey app publish
```

This re-validates, bundles, uploads to Athom, and opens the developer
portal to fill in screenshots / long description / support info.

After upload the app lands in the **Test track** by default — share the
test URL (`https://homey.app/a/com.fredhill.fing/test/`) for closed-beta
testing. When ready, click **Promote to Live** in the developer portal
to trigger the public App Store review (typically 1-2 weeks).
