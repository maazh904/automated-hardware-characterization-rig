"""
Automated RC low-pass filter characterization with Digilent Analog Discovery 3.

Wiring: W1 and 1+ -> Vin; 2+ -> Vout; GND, 1-, 2- -> GND.

"""

import csv
import math
import time
from ctypes import byref, c_byte, c_double, c_int, cdll, create_string_buffer
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# ---------- Experiment settings ----------
R = 10_000.0                 # ohms (nominal)
C = 10e-9                    # farads (nominal)
AMPLITUDE = 1.0              # W1 sine amplitude in volts (peak)
START_FREQ = 100.0           # Hz
STOP_FREQ = 20_000.0         # Hz
STEPS = 31
SAMPLES = 4096
SETTLE_SECONDS = 0.35
MAX_RETRIES = 2

OUTPUT_DIR = Path(__file__).resolve().parent / "results"
FREQUENCIES = np.unique(np.sort(np.append(
    np.geomspace(START_FREQ, STOP_FREQ, STEPS),
    1 / (2 * math.pi * R * C)  # include theoretical cutoff
)))

dwf = cdll.LoadLibrary("dwf.dll")
hdwf = c_int(0)


def check(name, *args):
    if getattr(dwf, name)(*args) == 0:
        message = create_string_buffer(512)
        dwf.FDwfGetLastErrorMsg(message)
        raise RuntimeError(f"{name} failed: {message.value.decode(errors='replace')}")


def capture(frequency):
    """Acquire synchronized scope data for input and output."""
    # Use 200 samples per sine-wave period, with ~20 cycles per capture.
    requested_rate = frequency * 200
    check("FDwfAnalogInFrequencySet", hdwf, c_double(requested_rate))
    check("FDwfAnalogInBufferSizeSet", hdwf, c_int(SAMPLES))

    # Read the actual sample rate in case the device rounded it.
    actual_rate = c_double()
    check("FDwfAnalogInFrequencyGet", hdwf, byref(actual_rate))

    check("FDwfAnalogInConfigure", hdwf, c_int(1), c_int(1))

    state = c_byte()
    deadline = time.monotonic() + 5.0
    while True:
        check("FDwfAnalogInStatus", hdwf, c_int(1), byref(state))
        if state.value == 2:    # DwfStateDone
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"Scope timed out at {frequency:.1f} Hz")
        time.sleep(0.005)

    ch1_buffer = (c_double * SAMPLES)()
    ch2_buffer = (c_double * SAMPLES)()
    check("FDwfAnalogInStatusData", hdwf, c_int(0), ch1_buffer, c_int(SAMPLES))
    check("FDwfAnalogInStatusData", hdwf, c_int(1), ch2_buffer, c_int(SAMPLES))

    time_axis = np.arange(SAMPLES) / actual_rate.value
    return (time_axis,
            np.ctypeslib.as_array(ch1_buffer).copy(),
            np.ctypeslib.as_array(ch2_buffer).copy())


def fit_sine(time_axis, voltage, frequency):
    """Fit V(t) = A*sin(wt) + B*cos(wt) + DC.

    Returns peak amplitude and phase in radians. Fitting both channels with
    the same time base makes their phase difference directly comparable.
    """
    angle = 2 * np.pi * frequency * time_axis
    design = np.column_stack((np.sin(angle), np.cos(angle), np.ones_like(angle)))
    sin_coef, cos_coef, _dc = np.linalg.lstsq(design, voltage, rcond=None)[0]
    amplitude = np.hypot(sin_coef, cos_coef)
    phase = np.arctan2(cos_coef, sin_coef)
    return float(amplitude), float(phase)


def estimate_signal_frequency(time_axis, vin_data):
    """Estimate actual frequency from rising zero crossings of CH1.

    Unlike a fixed-frequency sine fit, this can spot a generator that
    is still producing the preceding sweep frequency.
    """
    centered = vin_data - np.mean(vin_data)
    crossings = np.flatnonzero((centered[:-1] < 0) & (centered[1:] >= 0))
    if len(crossings) < 4:
        return float("nan")
    # Interpolate crossing times between adjacent ADC samples.
    left = centered[crossings]
    right = centered[crossings + 1]
    frac = -left / (right - left)
    crossing_times = time_axis[crossings] + frac * (time_axis[1] - time_axis[0])
    periods = np.diff(crossing_times)
    good_periods = periods[periods > 0]
    if len(good_periods) < 3:
        return float("nan")
    return float(1.0 / np.median(good_periods))


def update_wavegen(frequency):
    """Stop W1, stage new frequency, then start to apply settings."""
    check("FDwfAnalogOutConfigure", hdwf, c_int(0), c_int(0))  # stop
    check("FDwfAnalogOutNodeFrequencySet", hdwf, c_int(0), c_int(0), c_double(frequency))
    check("FDwfAnalogOutConfigure", hdwf, c_int(0), c_int(1))  # start
    # Readback confirms the SDK setting, not the physical output. CH1
    # verification below is what confirms actual frequency.
    readback = c_double()
    check("FDwfAnalogOutNodeFrequencyGet", hdwf, c_int(0), c_int(0), byref(readback))
    if abs(readback.value - frequency) > max(1.0, frequency * 0.001):
        raise RuntimeError(f"SDK frequency readback is {readback.value:.2f} Hz, expected {frequency:.2f} Hz")
    time.sleep(SETTLE_SECONDS)


def analyze(time_axis, vin_data, vout_data, frequency):
    actual_frequency = estimate_signal_frequency(time_axis, vin_data)
    if not math.isfinite(actual_frequency) or abs(actual_frequency - frequency) > max(2.0, 0.02 * frequency):
        raise RuntimeError(f"CH1 frequency mismatch: expected {frequency:.2f} Hz, measured {actual_frequency:.2f} Hz")

    vin_amp, vin_phase = fit_sine(time_axis, vin_data, frequency)
    vout_amp, vout_phase = fit_sine(time_axis, vout_data, frequency)

    # Diagnose an amplitude-fit failure before rejecting the capture.
    if not (0.6 * AMPLITUDE <= vin_amp <= 1.4 * AMPLITUDE):
        # If the waveform has normal peak-to-peak voltage but a low fitted
        # amplitude, the actual signal may be at the WRONG frequency.
        p2p = float(np.percentile(vin_data, 99) - np.percentile(vin_data, 1))
        raw_rms = float(np.std(vin_data))
        centered = vin_data - np.mean(vin_data)
        window = np.hanning(len(centered))
        spectrum = np.abs(np.fft.rfft(centered * window))
        fft_freqs = np.fft.rfftfreq(len(centered), d=float(time_axis[1] - time_axis[0]))
        dominant = float(fft_freqs[1 + np.argmax(spectrum[1:])])
        amp_at_100, _ = fit_sine(time_axis, vin_data, 100.0)
        print("\n--- CAPTURE DIAGNOSTICS ---")
        print(f"Requested frequency: {frequency:.2f} Hz")
        print(f"Raw CH1 peak-to-peak: {p2p:.4f} V")
        print(f"Raw CH1 standard deviation: {raw_rms:.4f} V")
        print(f"Estimated actual signal frequency (FFT): {dominant:.2f} Hz")
        print(f"Sine-fit amplitude at requested frequency: {vin_amp:.4f} V")
        print(f"Sine-fit amplitude at original 100 Hz: {amp_at_100:.4f} V")
        print("A ~2 V raw peak-to-peak signal with a ~100 Hz FFT peak means")
        print("Wavegen is still near 100 Hz, even though a new frequency was requested.")
        print("A near-zero raw peak-to-peak signal suggests the output stopped")
        print("or the scope captured near-zero voltage instead.")
        print("--- END DIAGNOSTICS ---\n")
        raise RuntimeError(
            f"Invalid CH1 sine fit at {frequency:.1f} Hz: {vin_amp:.4f} V. "
            "See diagnostic measurements above."
        )
    if vout_amp <= 0:
        raise RuntimeError(f"Invalid CH2 amplitude at {frequency:.1f} Hz")

    gain = vout_amp / vin_amp
    gain_db = 20 * math.log10(gain)
    phase_rad = (vout_phase - vin_phase + math.pi) % (2 * math.pi) - math.pi
    phase_deg = math.degrees(phase_rad)

    theoretical_gain = 1 / math.sqrt(1 + (2 * math.pi * frequency * R * C) ** 2)
    theoretical_db = 20 * math.log10(theoretical_gain)
    theoretical_phase = -math.degrees(math.atan(2 * math.pi * frequency * R * C))

    return {
        "frequency_hz": frequency,
        "measured_input_frequency_hz": actual_frequency,
        "vin_peak_v": vin_amp,
        "vout_peak_v": vout_amp,
        "gain_ratio": gain,
        "gain_db": gain_db,
        "phase_deg": phase_deg,
        "theory_gain_db": theoretical_db,
        "theory_phase_deg": theoretical_phase,
    }


def estimate_cutoff(rows):
    """Approximate -3.0103 dB crossing using log-frequency interpolation."""
    target = -10 * math.log10(2)
    for left, right in zip(rows[:-1], rows[1:]):
        y1, y2 = left["gain_db"], right["gain_db"]
        if (y1 - target) * (y2 - target) <= 0 and y1 != y2:
            fraction = (target - y1) / (y2 - y1)
            log_f = math.log(left["frequency_hz"]) + fraction * (
                math.log(right["frequency_hz"]) - math.log(left["frequency_hz"])
            )
            return math.exp(log_f)
    return None


def save_results(rows):
    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / "rc_results.csv"
    with csv_path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    f_smooth = np.geomspace(START_FREQ, STOP_FREQ, 400)
    theoretical_db = -10 * np.log10(1 + (2 * np.pi * f_smooth * R * C) ** 2)
    theoretical_phase = -np.degrees(np.arctan(2 * np.pi * f_smooth * R * C))
    measured_f = [row["frequency_hz"] for row in rows]
    fc = 1 / (2 * math.pi * R * C)

    for filename, theory, key, ylabel, title in [
        ("rc_magnitude.png", theoretical_db, "gain_db", "Gain (dB)", "RC Low-Pass Magnitude Response"),
        ("rc_phase.png", theoretical_phase, "phase_deg", "Phase (degrees)", "RC Low-Pass Phase Response"),
    ]:
        plt.figure(figsize=(8, 5))
        plt.semilogx(f_smooth, theory, "--", label="Theory (nominal R, C)")
        plt.semilogx(measured_f, [r[key] for r in rows], "o-", markersize=3,
                     label="AD3 measurement")
        plt.axvline(fc, linestyle=":", label=f"Nominal cutoff: {fc:.0f} Hz")
        plt.xlabel("Frequency (Hz)")
        plt.ylabel(ylabel)
        plt.title(title)
        plt.grid(True, which="both", alpha=0.35)
        plt.legend()
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / filename, dpi=300)
        plt.close()

    print(f"\nSaved CSV and two Bode plots to: {OUTPUT_DIR}")
    cutoff = estimate_cutoff(rows)
    if cutoff is not None:
        print(f"Estimated experimental -3 dB frequency: {cutoff:.1f} Hz")
        print(f"Nominal theoretical cutoff: {fc:.1f} Hz")
        print(f"Difference: {100 * (cutoff - fc) / fc:+.2f}%")
    else:
        print("Couldn't bracket the -3 dB crossing; inspect the measured values.")


def main():
    try:
        check("FDwfDeviceOpen", c_int(-1), byref(hdwf))
        if hdwf.value == 0:
            raise RuntimeError("Could not open AD3. Close WaveForms and retry.")
        print("Connected to Analog Discovery 3")
        check("FDwfDeviceAutoConfigureSet", hdwf, c_int(0))

        # Set up W1 for a continuous 1 V-peak sine wave.
        check("FDwfAnalogOutNodeEnableSet", hdwf, c_int(0), c_int(0), c_int(1))
        check("FDwfAnalogOutNodeFunctionSet", hdwf, c_int(0), c_int(0), c_int(1))
        check("FDwfAnalogOutNodeAmplitudeSet", hdwf, c_int(0), c_int(0), c_double(AMPLITUDE))
        check("FDwfAnalogOutNodeOffsetSet", hdwf, c_int(0), c_int(0), c_double(0))
        check("FDwfAnalogOutNodeFrequencySet", hdwf, c_int(0), c_int(0),
              c_double(float(FREQUENCIES[0])))
        check("FDwfAnalogOutRunSet", hdwf, c_int(0), c_double(0))

        # Set up both scope inputs; no trigger needed for sine fitting.
        for channel in (0, 1):
            check("FDwfAnalogInChannelEnableSet", hdwf, c_int(channel), c_int(1))
            check("FDwfAnalogInChannelRangeSet", hdwf, c_int(channel), c_double(5.0))
        check("FDwfAnalogInTriggerSourceSet", hdwf, c_int(0))

        check("FDwfAnalogOutConfigure", hdwf, c_int(0), c_int(1))
        time.sleep(1.0)

        # Previously the first AD3 acquisition was faulty: explicitly discard it.
        print("Discarding first (startup) scope acquisition...")
        capture(float(FREQUENCIES[0]))

        rows = []
        print("\nFrequency (Hz) | Gain (dB) | Phase (deg)")
        print("-" * 44)
        for frequency in FREQUENCIES:
            frequency = float(frequency)
            update_wavegen(frequency)

            # On this AD3 / SDK setup, the first scope capture after a
            # frequency update has consistently contained the previous
            # frequency. Discard it before collecting a verified capture.
            # This is a workaround for observed behavior, not a confirmed
            # explanation of the underlying acquisition-state mechanism.
            capture(frequency)

            # Retain actual-frequency verification and retries for any
            # intermittent errors; reacquire without restarting Wavegen.
            for attempt in range(MAX_RETRIES + 1):
                t, vin, vout = capture(frequency)
                try:
                    row = analyze(t, vin, vout, frequency)
                    break
                except RuntimeError as exc:
                    if attempt == MAX_RETRIES:
                        raise RuntimeError(
                            f"Failed {MAX_RETRIES + 1} verified attempts at {frequency:.2f} Hz. "
                            f"Last problem: {exc}"
                        ) from exc
                    print(f"Reacquiring {frequency:.1f} Hz: {exc}")
                    time.sleep(0.4)

            rows.append(row)
            print(
                f"{frequency:14.1f} | {row['gain_db']:9.2f} | "
                f"{row['phase_deg']:11.2f} | measured CH1 frequency "
                f"{row['measured_input_frequency_hz']:.1f} Hz"
            )

        save_results(rows)
    finally:
        if hdwf.value != 0:
            try:
                dwf.FDwfAnalogOutConfigure(hdwf, c_int(0), c_int(0))
                dwf.FDwfAnalogOutReset(hdwf, c_int(0))
            finally:
                dwf.FDwfDeviceClose(hdwf)
            print("AD3 disconnected; waveform generator stopped.")


if __name__ == "__main__":
    main()
