# ESP32 HTTP contract and pilot

The physical ESP32 sketch is in [sketch_oct15a](../sketch_oct15a/README.md).
On 2026-10-29 it was compiled, flashed and verified against the live backend:
the board at `192.168.1.9` received HTTP 201 and its real readings were persisted.
This verifies connectivity and ingestion, not sensor calibration or risk accuracy.

Register a **real** device (`simulated: false`) as an operator or administrator, retain
its one-time credential securely, and record a clean-air baseline. The device is
registered once and then assigned to each batch it monitors (see "Devices, batches and
history" in the main README), so it does not need reflashing between batches. Never put device
tokens or Wi-Fi credentials in committed files. Post to `/api/v1/readings` with
`X-Device-Token` and `Content-Type: application/json`:

```json
{
  "device_id": "REGISTERED_UUID",
  "event_id": "BOOT_UUID:SEQUENCE",
  "temperature_c": 22.5,
  "humidity_pct": 78.1,
  "gas_adc": 1020,
  "gas_voltage_v": 0.82,
  "source_timestamp": "2026-10-12T12:00:00Z",
  "warming_up": true,
  "simulated": false,
  "firmware_version": "YOUR_VERSION"
}
```

`batch_id` is deprecated and should be omitted: the server chooses the batch from the
device's current assignment. Firmware that still sends it, including the current
`sketch_oct15a` (not yet updated), keeps working, and the value is ignored. A
device that is not assigned yet still gets HTTP 201 (the response carries a `notice`),
and its readings are kept without a batch rather than rejected.

Use NTP time in UTC. Gas voltage is the measured ESP32 ADC-pin voltage after
the divider, not a gas concentration or the module's 5V analog-output voltage.
HTTP 201 means newly accepted; HTTP 200 with `duplicate: true` means a successful
retry. Retries must preserve **all** fields, including source time and event ID.
HTTP 409 `event_conflict` requires investigation, not an overwritten reading.
Buffer disconnected readings with stable boot UUID/sequence IDs. The backend
accepts historical readings up to `MAX_HISTORY_DAYS` (default 30).

Default cadence is five minutes. Flag every MQ-135 warm-up reading. Verify burn-in
and warm-up against the actual module's documentation. Verify the voltage divider,
ADC1 pin and electrical limits against ESP32/MQ-135 datasheets before wiring;
the backend's ADC input limit is 3.3V. DHT22 condensation can compromise readings.

See [the pilot runbook](../docs/PILOT.md) and the current
[tomato-box pilot setup](../docs/TOMATO_BOX_PILOT.md). Physical ingestion was
verified as described above; that does not establish sensor calibration.
