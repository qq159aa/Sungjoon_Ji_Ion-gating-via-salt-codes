#include <Wire.h>
#include "DFRobot_MCP4725.h"

// ---------------- DAC settings ----------------
#define REF_VOLTAGE 5000   // mV

DFRobot_MCP4725 DAC_Nitrogen1;
DFRobot_MCP4725 DAC_Nitrogen2;


// ---------------- Valve pin settings ----------------
const int valve_DI[] = {0, 37, 39, 41, 43};
const int valve_Nitrogen[] = {0, 45, 47, 49, 51};

// Valves used in this experiment
const int valve2use_DI[] = {valve_DI[2]};
const int valve2use_N2[] = {valve_Nitrogen[4]};


// ---------------- Experimental conditions ----------------
const int drying_time[] = {10000};   // N2 purge time, unit: s

int n_cycle = 5;

// Pressure, unit: kPa
int p_nitrogen = 30;
int p_DI = 30;

// Time
const int t_inter = 0;    // empty interval, unit: s
const int t_wait = 300;   // waiting period after DI refill, unit: s
int t_DI = 10;            // DI applying time, unit: 0.1 s

bool init_process = true;


// ============================================================
// Setup
// ============================================================
void setup() {
  initializeValvePins();

  Serial.begin(9600);
  delay(10);

  DAC_Nitrogen1.init(0x60, REF_VOLTAGE);
  DAC_Nitrogen2.init(0x61, REF_VOLTAGE);

  DAC_Nitrogen1.outputVoltage(0);
  DAC_Nitrogen2.outputVoltage(0);
  delay(1000);

  pulseAllValves();

  // Type anything in the serial monitor to start.
  while (Serial.available() == 0) {
    Serial.println("waiting");
  }
}


// ============================================================
// Main loop
// ============================================================
void loop() {
  Serial.println("get started");
  delay(10000);

  int n_drying_conditions = sizeof(drying_time) / sizeof(int);

  int n_N2_valves = sizeof(valve2use_N2) / sizeof(int);
  for (int i = 1; i <= n_N2_valves; i++) {
    digitalWrite(valve2use_N2[i - 1], HIGH);
  }

  if (init_process == true) {
    for (int j = 0; j <= n_drying_conditions - 1; j++) {
      for (int i = 1; i <= n_cycle; i++) {
        Serial.println("Cycle state:" + String(i) + "/" + String(n_cycle));

        applyNitrogen(p_nitrogen, drying_time[j]);

        for (int k = 0; k <= t_inter; k++) {
          delay(1000);
          Serial.println("empty " + String(k) + "/" + String(t_inter));
        }

        applyDI(p_DI, t_DI);

        for (int k = 0; k <= t_wait; k++) {
          delay(1000);
          Serial.println("DI " + String(k) + "/" + String(t_wait));
        }
      }

      init_process = false;
    }
  }

  DAC_Nitrogen1.outputVoltage(0);
  DAC_Nitrogen2.outputVoltage(0);
  delay(100);

  Serial.println("");
  Serial.println("==============================================");
  Serial.println("Process Done! with the " + String(n_cycle) + " time(s) repeated");
  Serial.println("Nitrogen was applied with " + String(p_nitrogen) + " kPa for " + String(drying_time[0]) + " sec(s)");
  Serial.println("DI was applied with " + String(p_DI) + " kPa for " + String(t_DI) + " step(s), unit = 0.1 s");
  Serial.println("==============================================");
  Serial.println("");

  delay(1000);

  // Stop program after completing the programmed sequence.
  while (true) {
    delay(1000);
  }
}


// ============================================================
// Initialization functions
// ============================================================
void initializeValvePins() {
  for (int i = 0; i <= 7; i++) {
    pinMode(37 + i * 2, OUTPUT);
  }
}


void pulseAllValves() {
  for (int i = 1; i <= 4; i++) {
    pulseValve(valve_DI[i]);
  }

  for (int i = 1; i <= 4; i++) {
    pulseValve(valve_Nitrogen[i]);
  }
}


void pulseValve(int valve_pin) {
  digitalWrite(valve_pin, HIGH);
  delay(50);
  digitalWrite(valve_pin, LOW);
}


// ============================================================
// Process functions
// ============================================================
void applyNitrogen(int pressure, long applytime) {
  // pressure: kPa
  // applytime: s

  int n_N2_valves = sizeof(valve2use_N2) / sizeof(int);

  if (applytime == 0) {
    Serial.println("");
    Serial.println("======================================");
    Serial.println("Set Nitrogen pressure and/or time 'zero'");
    Serial.println("======================================");
    Serial.println("");
    delay(50);
  }

  else {
    Serial.println("");
    Serial.println("===========================================================");
    Serial.println("Nitrogen Applying with " + String(pressure) + " kPa for " + String(applytime) + " sec(s) after 1 second");
    Serial.println("===========================================================");
    Serial.println("");
    delay(50);

    Serial.println("Nitrogen Applying Start! with " + String(pressure) + " kPa for " + String(applytime) + " sec(s)");
    Serial.println("");

    // Original logic preserved:
    // N2 pinch valve is opened by LOW and closed by HIGH.
    digitalWrite(valve2use_N2[0], LOW);
    DAC_Nitrogen1.outputVoltage(pressure * 50);
    DAC_Nitrogen2.outputVoltage(pressure * 50);

    for (long i = 1; i <= applytime; i++) {
      delay(980);
      Serial.println("----------------------------------");
      Serial.println(String(i) + "/" + String(applytime));
    }

    Serial.println("----------------------------------");
    Serial.println("");
    Serial.println("=================================================");
    Serial.println("Nitrogen Applying Done! with " + String(pressure) + " kPa for " + String(applytime) + " sec(s)");
    Serial.println("=================================================");
    Serial.println("");

    DAC_Nitrogen1.outputVoltage(0);
    DAC_Nitrogen2.outputVoltage(0);

    // Original logic preserved.
    digitalWrite(valve2use_N2[0], HIGH);
  }
}


void applyDI(int pressure, int applytime) {
  // pressure: kPa
  // applytime: 0.1 s step

  if (pressure == 0 || applytime == 0) {
    Serial.println("");
    Serial.println("======================================");
    Serial.println("Set DI pressure and/or time 'zero'");
    Serial.println("======================================");
    Serial.println("");
    delay(50);
  }

  else {
    Serial.println("");
    Serial.println("===========================================================");
    Serial.println("DI Applying for " + String(applytime) + " step(s), unit = 0.1 s");
    Serial.println("===========================================================");
    Serial.println("");
    delay(50);

    // Original logic preserved.
    digitalWrite(valve_DI[2], HIGH);
    digitalWrite(valve_Nitrogen[4], LOW);

    delay(1000);

    Serial.println("DI Applying Start! for " + String(applytime) + " step(s), unit = 0.1 s");
    Serial.println("");

    for (int i = 1; i <= applytime; i++) {
      Serial.println("----------------------------------");
      Serial.println("DI applying");
      Serial.println(String(i) + "/" + String(applytime));
      delay(100);
    }

    Serial.println("----------------------------------");
    Serial.println("");
    Serial.println("=================================================");
    Serial.println("DI Applying Done! for " + String(applytime) + " step(s), unit = 0.1 s");
    Serial.println("=================================================");
    Serial.println("");

    DAC_Nitrogen1.outputVoltage(0);
    DAC_Nitrogen2.outputVoltage(0);

    // Original logic preserved.
    digitalWrite(valve_DI[2], LOW);
    delay(500);
    digitalWrite(valve_Nitrogen[4], HIGH);

    DAC_Nitrogen1.outputVoltage(0);
    DAC_Nitrogen2.outputVoltage(0);
  }
}