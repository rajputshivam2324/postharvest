# Physical ESP32 HTTP sketch

`sketch_oct15a.ino` targets the existing Arduino IDE profile
`esp32:esp32:uPesy_wroom` (ESP32 Wroom DevKit), with DHT22 on GPIO 4 and
MQ ADC input on GPIO 34. Keep the board and backend computer on the same LAN.
Start the backend with `--host 0.0.0.0 --port 8000`.

Private settings are in ignored `config.h`. For another board, copy
`config.example.h` to `config.h` and configure the backend URLs, Wi-Fi, registered
real-device ID and one-time device credential. There is no batch ID: the server uses
the batch the device is currently assigned to, so moving a board to another batch is
done in the app. Do not share `config.h` or compiled firmware containing its credentials.

Firmware `tomato-box-pilot-v2-https` can talk to a hosted backend. An `https://`
`SERVER_URL` is verified against the root certificates embedded in the sketch
(`ROOT_CA`: Google Trust Services GTS Root R4 and ISRG Root X1); plain `http://` still
works for a LAN backend. The board waits for NTP time first because certificate dates
are checked. If the host changes certificate authority, replace `ROOT_CA`. Certificate
verification is never turned off.

The sketch sends authenticated `/api/v1/readings` requests, NTP UTC timestamps,
stable event IDs for network retries and the voltage at the ESP32 ADC input
after the divider. It does not reconstruct the MQ module's output voltage.
It checks `/health` on connection and every 30 seconds, independently of the
DHT sensor, so sensor failure cannot hide network connectivity. Read serial
output at 115200 baud. HTTP 201 or 200 confirms an accepted reading.

Sampling is every five minutes for the tomato-box pilot. `MQ_WARMING_UP` is
deliberately true until the module's actual warm-up and clean-air baseline have
been verified. A successful upload or ingestion does not establish calibration.
No baseline or inventory measurement is fabricated by the sketch.

Firmware `esp32-http-v2` uses the ADC1 oneshot driver directly, checks conversion
errors, averages 32 samples and calibrates those same samples into pin voltage.
Serial diagnostics include the raw minimum, maximum and number of zero samples.
Failed ADC reads are skipped rather than silently sent as zero. A genuine zero
is retained; averaging does not invent a signal or establish sensor calibration.
The attenuation and GPIO remain equivalent to the original 11 dB / GPIO 34
configuration. The voltage divider is handled by reporting its ADC-pin output;
resistor values are not assumed or used to fabricate a module-side voltage.

For the tomato-box pilot, firmware `tomato-box-pilot-v1` reports every five
minutes to match the backend policy. It remains in warm-up mode until the MQ135
has warmed in clean air and a real clean-air baseline is recorded. Do not place
the device inside the tomato box or use its readings for assessment before that
baseline is complete.

The current firmware uses device `ESP32-TOMATO-BOX-B4E830` in batch
`TOMATO-BOX-PILOT-B4E830` (commodity `tomato`, quantity one box). Earlier bench
readings remain under `ESP32-8C94DFB4E830` in `ESP32-CONNECTION-TEST-B4E830`.
That test batch's quantity/unit are explicitly marked setup placeholders.
See [tomato-box pilot setup](../docs/TOMATO_BOX_PILOT.md) for the current stage.

Verified on 2026-10-29: Arduino ESP32 core 3.3.12 compiled the sketch (80% flash,
15% global RAM). USB upload to `/dev/ttyUSB0` passed flash hash verification.
The board at `192.168.1.9` received HTTP 201 from the backend at `192.168.1.11`.
Database verification found four stored real readings; the latest at that check
was 27.4 °C, 59.7% RH, gas ADC 602 and ADC-pin voltage 0.640 V, timestamped
`2026-10-29T12:55:53Z`, with `simulated: false` and `warming_up: true`.

Verified on 2026-11-22: compiled with `arduino-cli` (esp32 core 3.3.12, 80% flash, 15% RAM)
and flashed over USB to `/dev/ttyUSB0` with flash hash verification. Against the deployed
backend (`https://postharvest-k5r3.onrender.com`) the health check returned 200 and the
first real reading returned 201; the reading appeared in batch `ESP32-LIVE-TEST-1` through
the API and on the deployed frontend, stored as `simulated: false`, `warming_up: true`.
