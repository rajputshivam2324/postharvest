# Tomato-box pilot

Configured on 2026-10-29 for the ESP32 with MAC `8c:94:df:b4:e8:30`.

| Setting | Value |
| --- | --- |
| Batch | `TOMATO-BOX-PILOT-B4E830` |
| Batch ID | `476f49c6-fbde-4ea2-8179-d581181ce6e8` |
| Commodity / quantity | Tomato / one box; actual tomato count and weight not yet supplied |
| Device | `ESP32-TOMATO-BOX-B4E830` |
| Device ID | `79d17bcd-35b8-4701-96a6-b4b5e022cd51` |
| Firmware | `tomato-box-pilot-v1` |
| Inputs | DHT22 GPIO 4; MQ135 analog output through existing divider to GPIO 34 |
| Backend | `http://192.168.1.11:8000/api/v1/readings` |
| Collection | One reading every five minutes; first reading as soon as Wi-Fi/time/sensors work |
| ADC | Checked ADC1 conversions, average of 32 samples, calibration of those same samples |
| Source | Physical device (`simulated: false`) |
| Current stage | Initial preheat, outside the box; `warming_up: true` |

Wi-Fi details and device credentials are in ignored `sketch_oct15a/config.h`.
Keep the backend computer running on the same reachable LAN. A five-second retry
handles clock/sensor failures and pending requests, independently of the five-minute
sample interval. Network retries retain their original event ID, values and time.
Health probes run every 30 seconds. Pending readings are held only in RAM, so
power loss discards a pending reading; this is not an offline data logger.

## Before tomatoes go in

The owner reported a fresh MQ135 with approximately 5–7 hours of prior powered
use. The [Winsen MQ135 manual](https://www.winsen-sensor.com/manual/mq135.html)
specifies over 48 hours of initial preheat. Follow the actual module's manual;
a glowing LED or a few stable samples does not establish completed conditioning.
Keep it powered in ventilated room air for conditioning and reference collection.

After conditioning, verify a stable nonzero room-air response under the same
power source and divider that will be used for the experiment. Record the
observed reference in Devices → Record baseline for `ESP32-TOMATO-BOX-B4E830`.
Use the actual reference collection time before the subsequent experiment
readings, and note the conditions. A reference is not a gas-concentration
calibration. Do not reuse a simulated device's baseline or relabel previous
warm-up readings.

The current firmware intentionally keeps `MQ_WARMING_UP = true`; it does not
automatically switch off after a timer. Once conditioning and the baseline are
verified, change it to `false`, rebuild and upload before starting the experiment.

## In the tomato box

Record the placement time and initial tomato count/weight, ripeness, visible
condition and ventilation as a batch observation. Keep sensor openings exposed
to the box air and clear of fruit/liquid. The MQ135 has a heater: mount it so it
does not contact fruit or the box material, and keep the DHT22 away from that
heater when measuring the box's ambient temperature. Do not make the box
airtight: ventilation and changing humidity affect the comparison.

Raw charts are available during warm-up. The existing six-hour tomato policy
requires a usable baseline and enough valid, fresh, non-warm-up readings before
it can produce an assessment. Its thresholds are illustrative and have not
been calibrated for this box, variety or ripeness. MQ135 readings are a broad
gas response; they do not identify tomato ethylene or establish whether fruit
is safe to eat. Compare trends with regular visual observations.

## Verification

The compiled binary was checked for the current device/batch IDs and firmware
version before USB upload; flash hash verification passed. The live database
received real `tomato-box-pilot-v1` readings for this batch, with gas ADC 551
at `2026-10-29T13:29:37Z`, `simulated: false`, `warming_up: true`.
No baseline has been fabricated or automatically recorded.
