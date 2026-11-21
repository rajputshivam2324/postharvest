#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <esp_system.h>
#include <esp_adc/adc_oneshot.h>
#include <esp_adc/adc_cali.h>
#include <esp_adc/adc_cali_scheme.h>
#include <time.h>
#include "config.h"

#define DHT_PIN 4
#define DHT_TYPE DHT22
#define MQ_PIN 34

DHT dht(DHT_PIN, DHT_TYPE);
const char* FIRMWARE_VERSION = "tomato-box-pilot-v1";
// Keep true until the actual module's warm-up and baseline are verified.
const bool MQ_WARMING_UP = true;
// The risk policy samples on a five-minute cadence; faster device collection
// only creates redundant readings and cannot replace a clean-air baseline.
const unsigned long SAMPLE_INTERVAL_MS = 5UL * 60UL * 1000UL;
const unsigned long HEALTH_INTERVAL_MS = 30000;
const unsigned long READING_RETRY_MS = 5000;
String bootId;
String pendingPayload;
uint32_t sequenceNumber = 0;
unsigned long lastHealthCheck = 0;
bool healthCheckDue = true;
bool sampleDue = true;
unsigned long lastSampleAt = 0;
unsigned long lastReadingAttemptAt = 0;
bool readingAttempted = false;
adc_oneshot_unit_handle_t gasAdc = nullptr;
adc_cali_handle_t gasCalibration = nullptr;
adc_channel_t gasChannel;
bool gasAdcReady = false;

bool initGasAdc() {
  adc_unit_t unit;
  esp_err_t error = adc_oneshot_io_to_channel(MQ_PIN, &unit, &gasChannel);
  if (error != ESP_OK || unit != ADC_UNIT_1) {
    Serial.printf("MQ GPIO %d must map to ADC1 (error %s)\n", MQ_PIN, esp_err_to_name(error));
    return false;
  }
  adc_oneshot_unit_init_cfg_t unitConfig = {};
  unitConfig.unit_id = unit;
  unitConfig.ulp_mode = ADC_ULP_MODE_DISABLE;
  error = adc_oneshot_new_unit(&unitConfig, &gasAdc);
  if (error != ESP_OK) {
    Serial.printf("MQ ADC initialization failed: %s\n", esp_err_to_name(error));
    return false;
  }
  adc_oneshot_chan_cfg_t channelConfig = {};
  channelConfig.bitwidth = ADC_BITWIDTH_12;
  channelConfig.atten = ADC_ATTEN_DB_12;
  error = adc_oneshot_config_channel(gasAdc, gasChannel, &channelConfig);
  if (error == ESP_OK) {
    adc_cali_line_fitting_config_t calibrationConfig = {};
    calibrationConfig.unit_id = unit;
    calibrationConfig.bitwidth = ADC_BITWIDTH_12;
    calibrationConfig.atten = ADC_ATTEN_DB_12;
    error = adc_cali_create_scheme_line_fitting(&calibrationConfig, &gasCalibration);
  }
  if (error != ESP_OK) {
    Serial.printf("MQ ADC configuration/calibration failed: %s\n", esp_err_to_name(error));
    adc_oneshot_del_unit(gasAdc);
    gasAdc = nullptr;
    return false;
  }
  Serial.printf("MQ ADC ready: GPIO %d, ADC1 channel %d, 12 bits\n", MQ_PIN, gasChannel);
  return true;
}

bool readGas(int& averageRaw, float& pinVoltage) {
  if (!gasAdcReady) {
    Serial.println("MQ ADC unavailable; sample skipped rather than reporting a false zero");
    return false;
  }
  const int samples = 32;
  uint32_t rawSum = 0;
  uint32_t millivoltSum = 0;
  int rawMin = 4095;
  int rawMax = 0;
  int zeroSamples = 0;
  int raw;
  esp_err_t error = adc_oneshot_read(gasAdc, gasChannel, &raw);
  if (error != ESP_OK) {
    Serial.printf("MQ ADC settling read failed: %s\n", esp_err_to_name(error));
    return false;
  }
  delayMicroseconds(250);
  for (int i = 0; i < samples; ++i) {
    error = adc_oneshot_read(gasAdc, gasChannel, &raw);
    if (error != ESP_OK) {
      Serial.printf("MQ ADC read failed: %s; no gas reading sent\n", esp_err_to_name(error));
      return false;
    }
    int millivolts;
    // Calibrate this exact raw sample, rather than taking another conversion.
    error = adc_cali_raw_to_voltage(gasCalibration, raw, &millivolts);
    if (error != ESP_OK) {
      Serial.printf("MQ voltage conversion failed: %s\n", esp_err_to_name(error));
      return false;
    }
    rawSum += raw;
    millivoltSum += millivolts;
    rawMin = min(rawMin, raw);
    rawMax = max(rawMax, raw);
    if (raw == 0) ++zeroSamples;
    delayMicroseconds(250);
  }
  averageRaw = (rawSum + samples / 2) / samples;
  pinVoltage = millivoltSum / (1000.0f * samples);
  Serial.printf("MQ diagnostic: mean=%d min=%d max=%d zeros=%d/%d pin=%.3f V\n",
                averageRaw, rawMin, rawMax, zeroSamples, samples, pinVoltage);
  if (zeroSamples == samples)
    Serial.println("MQ ADC reads succeeded, but all samples were zero (below measurable range)");
  return true;
}

void checkBackend() {
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(10000);
  if (!http.begin(SERVER_HEALTH_URL)) return;
  int code = http.GET();
  if (code > 0) Serial.printf("Backend health HTTP status: %d\n", code);
  else Serial.printf("Backend unreachable: %s\n", http.errorToString(code).c_str());
  http.end();
  lastHealthCheck = millis();
  healthCheckDue = false;
}

bool connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 20000) {
    delay(500);
    Serial.print('.');
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("\nWi-Fi connection failed (status %d); retrying\n", WiFi.status());
    return false;
  }
  Serial.println("\nWi-Fi connected");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("ESP32 MAC: ");
  Serial.println(WiFi.macAddress());
  Serial.print("Backend: ");
  Serial.println(SERVER_URL);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  healthCheckDue = true;
  return true;
}

bool captureReading() {
  struct tm utc;
  if (!getLocalTime(&utc, 2000)) {
    Serial.println("Waiting for NTP time; no fabricated timestamps will be sent");
    return false;
  }
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT22 reading failed; backend health checks continue");
    return false;
  }
  int gasRaw;
  float gasVoltage;
  if (!readGas(gasRaw, gasVoltage)) return false;
  if (temperature < -40 || temperature > 80 || humidity < 0 || humidity > 100 ||
      gasVoltage > 3.3f) {
    Serial.println("Sensor reading outside backend limits; sample skipped");
    return false;
  }
  char timestamp[25];
  strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%SZ", &utc);
  String eventId = bootId + ":" + String(++sequenceNumber);
  pendingPayload.reserve(512);
  pendingPayload = "{\"device_id\":\"" + String(DEVICE_ID) + "\",";
  pendingPayload += "\"batch_id\":\"" + String(BATCH_ID) + "\",";
  pendingPayload += "\"event_id\":\"" + eventId + "\",";
  pendingPayload += "\"temperature_c\":" + String(temperature, 1) + ",";
  pendingPayload += "\"humidity_pct\":" + String(humidity, 1) + ",";
  pendingPayload += "\"gas_adc\":" + String(gasRaw) + ",";
  pendingPayload += "\"gas_voltage_v\":" + String(gasVoltage, 3) + ",";
  pendingPayload += "\"source_timestamp\":\"" + String(timestamp) + "\",";
  pendingPayload += "\"simulated\":false,\"warming_up\":";
  pendingPayload += MQ_WARMING_UP ? "true," : "false,";
  pendingPayload += "\"firmware_version\":\"" + String(FIRMWARE_VERSION) + "\"}";
  Serial.printf("Reading: %.1f C, %.1f %% RH, gas %d ADC, %.3f V at %s\n",
                temperature, humidity, gasRaw, gasVoltage, timestamp);
  return true;
}

void sendReading() {
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(15000);
  if (!http.begin(SERVER_URL)) return;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  int code = http.POST(pendingPayload);
  if (code > 0) {
    Serial.printf("Backend reading HTTP status: %d\n", code);
    if (code == 200 || code == 201) {
      Serial.println("Reading accepted by backend");
      pendingPayload = "";
    } else {
      Serial.println(http.getString());
      if (code >= 400 && code < 500) {
        Serial.println("Request rejected; check device configuration and reported error");
        pendingPayload = "";
      }
    }
  } else {
    Serial.printf("Backend request failed: %s; retaining sample for retry\n",
                  http.errorToString(code).c_str());
  }
  // Network/server retries reuse the original event ID, timestamp and values.
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.printf("\nPost-harvest ESP32 firmware %s\n", FIRMWARE_VERSION);
  dht.begin();
  gasAdcReady = initGasAdc();
  WiFi.mode(WIFI_STA);
  char randomId[18];
  snprintf(randomId, sizeof(randomId), "%08lx%08lx",
           (unsigned long)esp_random(), (unsigned long)esp_random());
  bootId = String(randomId);
  connectWiFi();
  delay(2000);
}

void loop() {
  if (!connectWiFi()) {
    delay(3000);
    return;
  }
  // Probe connectivity even when the DHT fails; never fabricate sensor readings.
  if (healthCheckDue || millis() - lastHealthCheck >= HEALTH_INTERVAL_MS) checkBackend();
  unsigned long now = millis();
  if (!sampleDue && now - lastSampleAt >= SAMPLE_INTERVAL_MS) sampleDue = true;
  if ((sampleDue || pendingPayload.length()) &&
      (!readingAttempted || now - lastReadingAttemptAt >= READING_RETRY_MS)) {
    readingAttempted = true;
    lastReadingAttemptAt = now;
    if (!pendingPayload.length() && captureReading()) {
      sampleDue = false;
      lastSampleAt = millis();
    }
    if (pendingPayload.length()) sendReading();
  }
  delay(100);
}
