# automated-hardware-characterization-rig

**Python Based Circuit Testing Using the Digilent Analog Discovery 3**

## Overview

This project started as a way to explore automated circuit testing and gain more hands on experience with electrical engineering concepts.

Using a Digilent Analog Discovery 3 (AD3) and Python, I developed a system that can generate test signals, collect voltage measurements, perform frequency sweeps, and compare experimental results against theoretical circuit models.

I started with relatively simple circuits and gradually introduced more advanced features, including SPI communication, digitally adjustable resistance, operational amplifiers, and second order filters.

The project consists of four experiments:

1. DC Voltage Divider Characterization
2. Fixed RC Low Pass Filter Characterization
3. Digitally Programmable First Order RC Filter
4. Digitally Programmable Second Order Active Filter

A major focus throughout the project was making the measurements reliable and repeatable rather than relying entirely on manual oscilloscope readings.

## Hardware and Software

### Hardware

- Digilent Analog Discovery 3
- MCP4131-103 Digital Potentiometer (10 kΩ)
- MCP6022 Dual Operational Amplifier
- Resistors and ceramic capacitors
- Breadboard and jumper wires

### Software

- Python
- Digilent WaveForms SDK
- WaveForms
- NumPy
- Matplotlib
- CSV for data logging

The AD3 was used for waveform generation, voltage measurements, power delivery, and SPI communication. Python handled instrument control, data collection, calculations, and plotting.

---

## 1. DC Voltage Divider Characterization

The first experiment involved testing a simple voltage divider using two nominally equal resistors.

Although the circuit itself was straightforward, the goal was to automate the entire measurement process.

I wrote a Python script that swept the input voltage from 0.5 V to 2.5 V using the AD3's waveform generator. At each step, the script measured both the input and output voltages and compared their ratio against the ideal value of 0.5.

The theoretical relationship is:

`Vout = Vin × R2 / (R1 + R2)`

The script automatically saved the measurements to a CSV file and generated plots showing the voltage response and percentage error.

### Results

- Five automated voltage measurements
- Input range: 0.5–2.5 V
- Measured voltage ratios consistently close to 0.5
- Percentage deviation from the ideal ratio: 0.18%–0.55%
- Mean absolute deviation: approximately 0.28%

The measurements closely matched the expected behaviour of the voltage divider.

This experiment also provided a foundation for using the WaveForms SDK to control the AD3 directly through Python.

---

## 2. Fixed RC Low Pass Filter Characterization

For the second experiment, I moved from DC measurements to frequency-domain analysis.

I built a first order RC low pass filter using a 10 kΩ resistor and a 10 nF capacitor.

The goal was to measure how the circuit's gain and phase changed with frequency and compare the results against its theoretical transfer function.

The transfer function is:

`H(s) = 1 / (1 + sRC)`

The cutoff frequency is:

`fc = 1 / (2πRC)`

For the selected component values, the theoretical cutoff frequency was approximately 1,591.55 Hz.

I developed a Python script to generate sine waves over a frequency range of 100 Hz to 20 kHz. The AD3 captured the input and output waveforms, and the script used sine fitting to calculate their amplitudes and phase difference.

These measurements were then used to generate magnitude and phase Bode plots.

### Results

I performed three separate frequency sweeps to check the consistency of the measurements.

| Measurement | Result |
|---|---:|
| Theoretical cutoff | 1,591.55 Hz |
| Mean measured cutoff | 1,655.07 Hz |
| Standard deviation | 0.25 Hz |
| Error relative to theory | +3.99% |

The measured response followed the expected first order behaviour, with increasing attenuation at higher frequencies and phase approaching −90°.

The three cutoff measurements were also very close to one another, suggesting that the automated measurement process was highly repeatable under the same test conditions.

---

## 3. Digitally Programmable First Order RC Filter

After characterizing a fixed RC filter, I wanted to explore whether I could change a circuit's frequency response directly through software.

To do this, I introduced an MCP4131-103 digital potentiometer into the RC circuit.

The filter used a fixed series resistance of 2.22 kΩ, a programmable resistance of up to approximately 10 kΩ, and a 10 nF capacitor.

Instead of manually replacing resistors, I used the AD3's digital I/O pins to communicate with the potentiometer over SPI.

This allowed Python to adjust the resistance electronically and measure the resulting change in the filter's cutoff frequency.

The relationship between resistance and cutoff frequency remained:

`fc = 1 / (2πRC)`

Decreasing the effective resistance increased the cutoff frequency, allowing more of the higher-frequency signal to pass through.

### Automation

I expanded the Python program to automatically:

- Configure the potentiometer through SPI
- Generate sine waves at 40 frequencies
- Measure input and output amplitudes
- Calculate gain and phase
- Estimate the cutoff frequency
- Export CSV data and Bode plots

I tested three potentiometer settings, resulting in 120 automated frequency measurements.

### Results

| SPI Setting | Theoretical Cutoff | Measured Cutoff | Error |
|---|---:|---:|---:|
| h20 | 1,637.4 Hz | 1,650.0 Hz | +0.77% |
| h40 | 2,204.4 Hz | 2,210.6 Hz | +0.28% |
| h60 | 3,371.9 Hz | 3,320.1 Hz | −1.54% |

All three measured cutoff frequencies were within 2% of their nominal theoretical predictions.

This was an important step in the project because it combined digital communication with analog circuit behaviour.

It also showed that the AD3 could be used not only to measure a circuit but to automatically change its operating conditions.

---

## 4. Digitally Programmable Second Order Active Filter

For the final experiment, I extended the programmable RC filter into a second order active low pass filter.

I added a second RC stage consisting of a 10 kΩ resistor and a 10 nF capacitor. An MCP6022 dual operational amplifier was used to create two unity-gain buffers, isolating the filter stages and reducing loading effects.

With the two buffered RC stages connected in series, the ideal transfer function becomes:

`H(s) = 1 / [(1 + sR1C1)(1 + sR2C2)]`

Unlike the previous first order filters, this circuit contains two poles.

As a result, the high-frequency magnitude response approaches −40 dB/decade rather than −20 dB/decade, while the phase approaches −180°.

The cutoff frequency could still be adjusted through SPI, since the first stage retained its digitally programmable resistance.

### Automation and Testing

I modified the existing Python automation to characterize the complete second order filter.

The script automatically changed between three potentiometer settings, performed 40 frequency measurements for each setting, calculated gain and phase, and estimated the overall cutoff frequency.

To evaluate repeatability, I ran the full experiment three times without changing the circuit.

This produced a total of **360 automated measurements**.

### Results

| SPI Setting | Theoretical Cutoff | Mean Measured Cutoff | Standard Deviation |
|---|---:|---:|---:|
| h20 | 1,038.8 Hz | 1,009.0 Hz | 0.99 Hz |
| h40 | 1,183.2 Hz | 1,140.2 Hz | 1.20 Hz |
| h60 | 1,353.0 Hz | 1,290.8 Hz | 1.07 Hz |

The measured mean cutoff frequencies were within 4.6% of the nominal theoretical model.

The repeatability results were particularly encouraging:

| SPI Setting | Coefficient of Variation |
|---|---:|
| h20 | 0.098% |
| h40 | 0.105% |
| h60 | 0.083% |

All three configurations had cutoff frequency coefficients of variation below 0.11%.

The measured Bode plots also showed the expected second order behaviour, including a high-frequency rolloff approaching −40 dB/decade and phase approaching −180°.

Overall, the results showed that the system could reliably characterize a more complex analog circuit while automatically changing its frequency response.

---

## Data Acquisition and Analysis

The measurement programs were written in Python using the Digilent WaveForms SDK.

Rather than manually recording values from the oscilloscope, I used the SDK to configure the AD3's instruments and collect synchronized voltage measurements.

For frequency sweeps, the input and output waveforms were analyzed using sine wave fitting to determine their amplitudes and phases.

Voltage gain was calculated using:

`Gain (dB) = 20log10(Vout / Vin)`

The measured gain and phase were compared against the theoretical transfer functions for each circuit.

Cutoff frequencies were estimated by interpolating between measurements around the −3 dB point.

Matplotlib was used to generate Bode plots and other experimental graphs, while CSV files preserved the measurement data for further analysis.

---

## Challenges and Troubleshooting

One of the most valuable parts of this project was troubleshooting problems that weren't immediately obvious from the circuit diagrams.

### Incorrect Waveform Frequency During Sweeps

While developing the first RC frequency-sweep program, I encountered an issue where the AD3 occasionally captured a waveform at the previous frequency instead of the newly requested one.

The instrument configuration appeared correct, but the measurements were inconsistent.

After investigating the captured signals, I added several checks to the Python program:

- Discarding the first acquisition after changing frequency
- Estimating the actual frequency from the input waveform
- Rejecting measurements that did not match the requested frequency
- Retrying failed acquisitions

This made the sweeps more reliable and prevented incorrect data from being included in the final results.

### SPI Communication

Controlling the MCP4131 was another challenge.

Before using it as part of a filter, I tested it independently as a digitally controlled voltage divider.

By sending different SPI commands and measuring the wiper voltage, I could confirm that the communication was working correctly.

Once that test was successful, I incorporated the potentiometer into the RC filter and automated the SPI commands through Python.

### Breadboard Connections

During testing, I also encountered inconsistent measurements caused by poor breadboard connections.

These problems were particularly noticeable when changing the potentiometer settings did not produce the expected changes in the frequency response.

Testing individual components and circuit stages helped isolate the issues without having to rebuild the entire system each time.

### Combining Two RC Stages

When designing the second order filter, I needed to account for loading between the two RC stages.

I used the MCP6022 as a pair of voltage followers to isolate the stages, making their behaviour easier to model and predict.

This was also an opportunity to apply what I had learned about operational amplifiers and negative feedback to a practical circuit.

---

## Repository Structure

The repository contains the Python programs, experimental measurements, and plots for each stage of the project.

### Python Programs

- `dcSweep.py` — Automated voltage divider measurements
- `plotDc.py` — DC characterization plots
- `rcSweep.py` — Fixed RC frequency sweeps
- `programmableRcAutoSweep.py` — Programmable first order filter automation
- `programmableSecondOrderAutoSweep.py` — Second order filter automation

### Experimental Results

- `01_dc_voltage_divider/` — Voltage divider measurements and error plots
- `02_fixed_rc_lowpass/` — Fixed RC Bode plots and repeatability tests
- `03_programmable_rc/` — Programmable first order filter measurements
- `04_second_order_active_filter/` — Second order filter results and repeatability analysis

The CSV files contain the collected measurement data, while the generated plots provide visual comparisons between experimental and theoretical results.

---

## Running the Programs

The automation scripts were developed and tested on Windows using Python and the Digilent WaveForms SDK.

### Requirements

- Python 3
- Digilent WaveForms and WaveForms SDK
- NumPy
- Matplotlib
- Digilent Analog Discovery 3

Install the Python dependencies using:

`py -m pip install numpy matplotlib`

Each script requires the corresponding circuit to be connected to the AD3.

Before running a program, verify the wiring and supply voltages, and close WaveForms so the Python script can access the device.

The scripts configure the required AD3 instruments, perform the measurements, and save the resulting data and plots.

---

## What I Learned

This project gave me a better understanding of how circuit theory translates into real hardware behaviour.

In particular, I gained experience with:

- Automating laboratory measurements using Python
- Working directly with hardware through the WaveForms SDK
- Using SPI to control analog circuit parameters
- Applying Laplace transforms and transfer functions to real circuits
- Understanding how poles affect magnitude and phase response
- Using operational amplifiers to isolate circuit stages
- Analyzing measurement errors and repeatability
- Troubleshooting both hardware connections and software controlled instruments

One of my biggest takeaways was the importance of verifying measurements rather than assuming that correctly configured instruments are always producing valid data.

By the end of the project, I had developed a reusable testing workflow that could control a circuit, collect measurements, compare them against theory, and evaluate how consistently the results could be reproduced.

The project also strengthened my interest in analog electronics, instrumentation, and hardware testing.

---

*Personal electrical engineering project developed using the Digilent Analog Discovery 3 and Python.*
