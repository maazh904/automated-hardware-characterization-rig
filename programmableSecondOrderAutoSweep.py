"""Automated two-pole programmable ACTIVE low-pass filter characterization.

AD3 + MCP4131-103 + MCP6022 dual unity-gain buffers.

Required connections (both chips share a 3.3 V supply and common GND):
  AD3 digital 0 -> MCP4131 pin 1 (CS)
  AD3 digital 1 -> MCP4131 pin 2 (SCK)
  AD3 digital 2 -> MCP4131 pin 3 (SDI)
  MCP4131 pin 8 -> V+ (3.3 V); pin 4 -> GND
  AD3 W1 -> 1k + 1k + 220 ohm in series -> MCP4131 pin 5 (A)
  MCP4131 pin 7 (B) -> pin 6 (wiper)
  MCP4131 pin 6 -> first 10 nF filter capacitor -> GND
  MCP4131 pin 6 -> MCP6022 pin 3 (+IN A)
  MCP6022 pin 1 (OUT A) -> MCP6022 pin 2 (-IN A)
  MCP6022 pin 1 -> 10k ohm -> MCP6022 pin 5 (+IN B)
  MCP6022 pin 5 -> second 10 nF filter capacitor -> GND
  MCP6022 pin 7 (OUT B) -> MCP6022 pin 6 (-IN B)
  MCP6022 pin 8 -> V+ (3.3 V); pin 4 -> GND
  AD3 CH1+ -> W1, CH1- -> GND
  AD3 CH2+ -> MCP6022 pin 7, CH2- -> GND
  100 nF decoupling capacitors from each chip's VDD to VSS (close to chip).

The ideal transfer function is
    H(s) = 1 / [(1 + s*Rprog*C1) (1 + s*R2*C2)]
where Rprog = 2220 + 10000*(128-code)/128 ohms (nominal model).
"""
from __future__ import annotations

import csv
import math
import time
from ctypes import byref, c_byte, c_double, c_int, c_ubyte, cdll, create_string_buffer
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # save images; no GUI pop-up
import matplotlib.pyplot as plt
import numpy as np

# --- Hardware and experiment settings ---
WIPERS = (32, 64, 96)  # 0x20, 0x40, 0x60
FIXED_R_OHMS = 2220.0
DIGIPOT_R_OHMS = 10000.0
FIRST_STAGE_CAP_F = 10e-9
SECOND_STAGE_R_OHMS = 10_000.0
SECOND_STAGE_CAP_F = 10e-9
# Simple nominal model ignores wiper contact resistance and component tolerance.
WIPER_CONTACT_R_OHMS = 0.0

MIN_FREQ_HZ = 100.0
MAX_FREQ_HZ = 20000.0
POINTS_PER_WIPER = 40
FREQUENCIES_HZ = np.geomspace(MIN_FREQ_HZ, MAX_FREQ_HZ, POINTS_PER_WIPER)
W1_PEAK_V = 0.3
W1_OFFSET_V = 1.65
SUPPLY_V = 3.3
SAMPLE_COUNT = 4096
SAMPLES_PER_CYCLE = 200  # ~20 sine cycles in each capture
SETTLING_S = 0.25
MAX_RETRIES = 3
OUTPUT_DIR = Path(__file__).resolve().parent / 'results_second_order'


def nominal_resistance_ohms(code: int) -> float:
    # A-to-wiper resistance gets LOWER as code increases; B is shorted to W.
    return (FIXED_R_OHMS + DIGIPOT_R_OHMS * (128 - code) / 128
            + WIPER_CONTACT_R_OHMS)


def first_pole_hz(code: int) -> float:
    return 1.0 / (2.0 * math.pi * nominal_resistance_ohms(code) * FIRST_STAGE_CAP_F)


def second_pole_hz() -> float:
    return 1.0 / (2.0 * math.pi * SECOND_STAGE_R_OHMS * SECOND_STAGE_CAP_F)


def theoretical_cutoff_hz(code: int) -> float:
    """Combined two-pole -3.0103 dB cutoff (NOT either individual pole)."""
    tau1 = nominal_resistance_ohms(code) * FIRST_STAGE_CAP_F
    tau2 = SECOND_STAGE_R_OHMS * SECOND_STAGE_CAP_F
    # Set (1 + (w*tau1)^2) * (1 + (w*tau2)^2) = 2.
    # Let x=w^2; solve a*x^2 + b*x - 1=0 using stable root.
    a = (tau1 * tau2) ** 2
    b = tau1**2 + tau2**2
    omega_squared = 2.0 / (b + math.sqrt(b*b + 4*a))
    return math.sqrt(omega_squared) / (2.0 * math.pi)


def theory_at(frequency_hz: float | np.ndarray, code: int):
    """Returns overall magnitude in dB and total phase in degrees."""
    omega = 2.0 * np.pi * np.asarray(frequency_hz)
    tau1 = nominal_resistance_ohms(code) * FIRST_STAGE_CAP_F
    tau2 = SECOND_STAGE_R_OHMS * SECOND_STAGE_CAP_F
    a = omega * tau1
    b = omega * tau2
    gain_db = -10.0 * np.log10((1.0 + a*a) * (1.0 + b*b))
    phase_deg = -np.degrees(np.arctan(a) + np.arctan(b))
    return gain_db, phase_deg


def get_error(dwf) -> str:
    message = create_string_buffer(512)
    dwf.FDwfGetLastErrorMsg(message)
    return message.value.decode(errors='replace')


def call(dwf, function: str, *args):
    if getattr(dwf, function)(*args) == 0:
        raise RuntimeError(f'{function}: {get_error(dwf)}')


def set_wiper(dwf, device, code: int) -> None:
    if not 0 <= code <= 128:
        raise ValueError(f'Invalid MCP4131 wiper code {code}')
    data = (c_ubyte * 2)(0x00, code)
    call(dwf, 'FDwfDigitalSpiSelect', device, c_int(0), c_int(0))
    try:
        call(dwf, 'FDwfDigitalSpiWrite', device, c_int(0), c_int(8), data, c_int(2))
    finally:
        call(dwf, 'FDwfDigitalSpiSelect', device, c_int(0), c_int(1))


def set_frequency(dwf, device, frequency: float) -> None:
    # This exact stop/set/start workaround fixed stale Wavegen frequency
    # readings in the user's previous RC test.
    call(dwf, 'FDwfAnalogOutConfigure', device, c_int(0), c_int(0))
    call(dwf, 'FDwfAnalogOutNodeFrequencySet', device, c_int(0), c_int(0), c_double(frequency))
    call(dwf, 'FDwfAnalogOutConfigure', device, c_int(0), c_int(1))
    readback = c_double()
    call(dwf, 'FDwfAnalogOutNodeFrequencyGet', device, c_int(0), c_int(0), byref(readback))
    if abs(readback.value - frequency) > max(1, 0.001 * frequency):
        raise RuntimeError(f'Wavegen readback {readback.value:.2f} Hz; requested {frequency:.2f} Hz')
    time.sleep(SETTLING_S)


def capture(dwf, device, frequency_hz: float):
    requested_sample_rate = float(SAMPLES_PER_CYCLE * frequency_hz)
    call(dwf, 'FDwfAnalogInFrequencySet', device, c_double(requested_sample_rate))
    call(dwf, 'FDwfAnalogInBufferSizeSet', device, c_int(SAMPLE_COUNT))
    actual_rate = c_double()
    call(dwf, 'FDwfAnalogInFrequencyGet', device, byref(actual_rate))
    if actual_rate.value <= 0:
        raise RuntimeError('Invalid oscilloscope sample rate')
    call(dwf, 'FDwfAnalogInConfigure', device, c_int(1), c_int(1))
    status = c_byte()
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        call(dwf, 'FDwfAnalogInStatus', device, c_int(1), byref(status))
        if status.value == 2:  # DwfStateDone
            break
        time.sleep(0.005)
    else:
        raise TimeoutError(f'Scope acquisition timeout at {frequency_hz:.2f} Hz')
    ch1 = (c_double * SAMPLE_COUNT)()
    ch2 = (c_double * SAMPLE_COUNT)()
    call(dwf, 'FDwfAnalogInStatusData', device, c_int(0), ch1, c_int(SAMPLE_COUNT))
    call(dwf, 'FDwfAnalogInStatusData', device, c_int(1), ch2, c_int(SAMPLE_COUNT))
    t = np.arange(SAMPLE_COUNT, dtype=float) / actual_rate.value
    return t, np.ctypeslib.as_array(ch1).copy(), np.ctypeslib.as_array(ch2).copy()


def measured_frequency(t: np.ndarray, voltage: np.ndarray) -> float:
    """Estimate source frequency from interpolated rising zero crossings."""
    data = voltage - voltage.mean()
    indices = np.flatnonzero((data[:-1] < 0) & (data[1:] >= 0))
    if len(indices) < 4:
        return float('nan')
    frac = -data[indices] / (data[indices + 1] - data[indices])
    crossing_times = t[indices] + frac * (t[1] - t[0])
    periods = np.diff(crossing_times)
    periods = periods[periods > 0]
    return float(1.0 / np.median(periods)) if len(periods) >= 3 else float('nan')


def sine_fit(t: np.ndarray, voltage: np.ndarray, frequency_hz: float):
    """Least-squares fit of sin, cos and DC, returning peak amplitude and phase."""
    angle = 2 * np.pi * frequency_hz * t
    matrix = np.column_stack((np.sin(angle), np.cos(angle), np.ones_like(angle)))
    a, b, dc = np.linalg.lstsq(matrix, voltage, rcond=None)[0]
    return float(np.hypot(a, b)), float(np.arctan2(b, a)), float(dc)


def analyze_capture(t, vin, vout, freq_hz: float, code: int):
    detected = measured_frequency(t, vin)
    if not math.isfinite(detected) or abs(detected - freq_hz) > max(2.0, 0.02 * freq_hz):
        raise RuntimeError(f'stale/incorrect CH1 frequency: requested {freq_hz:.1f}, measured {detected:.1f} Hz')
    vin_peak, phase_in, vin_dc = sine_fit(t, vin, freq_hz)
    vout_peak, phase_out, vout_dc = sine_fit(t, vout, freq_hz)
    if not (W1_PEAK_V * 0.65 <= vin_peak <= W1_PEAK_V * 1.35):
        raise RuntimeError(f'bad CH1 peak amplitude {vin_peak:.4f} V at {freq_hz:.1f} Hz')
    if not (0.00025 <= vout_peak <= 1.2 * W1_PEAK_V):
        raise RuntimeError(f'bad CH2 peak amplitude {vout_peak:.4f} V at {freq_hz:.1f} Hz')
    if abs(vout_dc - W1_OFFSET_V) > 0.35:
        raise RuntimeError(f'CH2 DC offset {vout_dc:.3f} V; expected near {W1_OFFSET_V:.2f} V (check wiring)')
    phase_deg = math.degrees((phase_out - phase_in + math.pi) % (2 * math.pi) - math.pi)
    gain_db = 20 * math.log10(vout_peak / vin_peak)
    expected_db, expected_phase = theory_at(freq_hz, code)
    return {
        'wiper_decimal': code,
        'wiper_hex': f'h{code:02X}',
        'frequency_hz': float(freq_hz),
        'actual_input_frequency_hz': detected,
        'vin_peak_v': vin_peak,
        'vout_peak_v': vout_peak,
        'vin_dc_v': vin_dc,
        'vout_dc_v': vout_dc,
        'gain_db': gain_db,
        'phase_deg': phase_deg,
        'theory_gain_db': float(expected_db),
        'theory_phase_deg': float(expected_phase),
        'nominal_first_stage_resistance_ohm': nominal_resistance_ohms(code),
        'first_stage_pole_hz': first_pole_hz(code),
        'second_stage_pole_hz': second_pole_hz(),
    }


def find_cutoff(rows: list[dict]) -> float | None:
    target = -10 * math.log10(2)
    # Find overall -3.0103 dB crossing, interpolate on log-frequency scale.
    for left, right in zip(rows[:-1], rows[1:]):
        a, b = left['gain_db'], right['gain_db']
        if (a - target) * (b - target) <= 0 and a != b:
            fraction = (target - a) / (b - a)
            return math.exp(math.log(left['frequency_hz']) + fraction *
                            (math.log(right['frequency_hz']) - math.log(left['frequency_hz'])))
    return None


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def save_results(all_rows: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT_DIR / 'second_order_auto_all.csv', all_rows)
    cutoffs = []
    for code in WIPERS:
        rows = [r for r in all_rows if r['wiper_decimal'] == code]
        write_csv(OUTPUT_DIR / f'second_order_auto_h{code:02x}.csv', rows)
        theoretical_fc = theoretical_cutoff_hz(code)
        measured_fc = find_cutoff(rows)
        cutoffs.append({
            'wiper_decimal': code,
            'nominal_first_stage_resistance_ohm': nominal_resistance_ohms(code),
            'first_stage_pole_hz': first_pole_hz(code),
            'second_stage_pole_hz': second_pole_hz(),
            'theoretical_cutoff_hz': theoretical_fc,
            'measured_cutoff_hz': '' if measured_fc is None else measured_fc,
            'cutoff_error_percent': '' if measured_fc is None else 100 * (measured_fc / theoretical_fc - 1),
        })

    write_csv(OUTPUT_DIR / 'second_order_auto_cutoffs.csv', cutoffs)
    smooth_f = np.geomspace(MIN_FREQ_HZ, MAX_FREQ_HZ, 400)
    for key, theory_index, ylabel, filename, title in [
        ('gain_db', 0, 'Gain (dB)', 'second_order_auto_magnitude.png',
         'Programmable Two-Pole Active Filter — Magnitude Response'),
        ('phase_deg', 1, 'Phase (degrees)', 'second_order_auto_phase.png',
         'Programmable Two-Pole Active Filter — Phase Response'),
    ]:
        plt.figure(figsize=(9, 5.5))
        for code in WIPERS:
            rows = [r for r in all_rows if r['wiper_decimal'] == code]
            if not rows:
                continue
            label = f'h{code:02X} (nominal $f_c$={theoretical_cutoff_hz(code):.0f} Hz)'
            predicted = theory_at(smooth_f, code)[theory_index]
            line, = plt.semilogx(smooth_f, predicted, '--', alpha=0.75, label=f'{label}, theory')
            plt.semilogx([r['frequency_hz'] for r in rows], [r[key] for r in rows],
                         'o-', markersize=3, color=line.get_color(), label=f'h{code:02X}, measured')
        plt.title(title)
        plt.xlabel('Frequency (Hz)')
        plt.ylabel(ylabel)
        plt.grid(which='both', alpha=0.3)
        plt.legend(fontsize=8)
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / filename, dpi=220)
        plt.close()

    print('\n' + '=' * 66)
    print('OVERALL TWO-POLE CUTOFF FREQUENCIES (-3.010 dB)')
    print('Wiper  | Theory (Hz) | Measured (Hz) | Error (%)')
    for row in cutoffs:
        code = row['wiper_decimal']
        f_measured = row['measured_cutoff_hz']
        err = row['cutoff_error_percent']
        print(f'h{code:02X}    | {row["theoretical_cutoff_hz"]:11.1f} | '
              f'{f_measured:13.1f} | {err:+8.2f}' if isinstance(f_measured, float)
              else f'h{code:02X}    | {row["theoretical_cutoff_hz"]:11.1f} | not bracketed | --')
    print(f'\nSaved output files in: {OUTPUT_DIR}')
    print('  second_order_auto_all.csv')
    print('  second_order_auto_h20.csv / h40.csv / h60.csv')
    print('  second_order_auto_cutoffs.csv')
    print('  second_order_auto_magnitude.png')
    print('  second_order_auto_phase.png')
    print('Note: Above ~10 kHz, two-pole output may be only a few millivolts;')
    print('      phase and gain may be noisier than for the first-order filter.')


def main():
    dwf = cdll.LoadLibrary('dwf.dll')
    device = c_int()
    all_rows: list[dict] = []
    try:
        call(dwf, 'FDwfDeviceOpen', c_int(-1), byref(device))
        if device.value == 0:
            raise RuntimeError(f'AD3 not opened. Close WaveForms. SDK says: {get_error(dwf)}')
        print('Connected to AD3. Initializing safe 3.3 V power...')

        # Always supply MCP4131 before generating W1's biased sine wave.
        call(dwf, 'FDwfAnalogIOEnableSet', device, c_int(0))
        call(dwf, 'FDwfAnalogIOChannelNodeSet', device, c_int(0), c_int(1), c_double(SUPPLY_V))
        call(dwf, 'FDwfAnalogIOChannelNodeSet', device, c_int(0), c_int(0), c_double(1))
        call(dwf, 'FDwfAnalogIOEnableSet', device, c_int(1))
        time.sleep(0.5)

        # SPI configuration exactly as in successful smoke test.
        call(dwf, 'FDwfDigitalSpiReset', device)
        call(dwf, 'FDwfDigitalSpiFrequencySet', device, c_double(100_000))
        call(dwf, 'FDwfDigitalSpiClockSet', device, c_int(1))
        call(dwf, 'FDwfDigitalSpiDataSet', device, c_int(0), c_int(2))
        call(dwf, 'FDwfDigitalSpiModeSet', device, c_int(0))
        call(dwf, 'FDwfDigitalSpiOrderSet', device, c_int(1))
        call(dwf, 'FDwfDigitalSpiSelectSet', device, c_int(0), c_int(1))
        call(dwf, 'FDwfDigitalSpiSelect', device, c_int(0), c_int(1))
        set_wiper(dwf, device, 64)

        # Wavegen W1 at safe 1.65 +/- 0.3 V, after power is enabled.
        call(dwf, 'FDwfAnalogOutIdleSet', device, c_int(0), c_int(0))
        call(dwf, 'FDwfAnalogOutNodeEnableSet', device, c_int(0), c_int(0), c_int(1))
        call(dwf, 'FDwfAnalogOutNodeFunctionSet', device, c_int(0), c_int(0), c_int(1))
        call(dwf, 'FDwfAnalogOutNodeFrequencySet', device, c_int(0), c_int(0),
             c_double(float(FREQUENCIES_HZ[0])))
        call(dwf, 'FDwfAnalogOutNodeAmplitudeSet', device, c_int(0), c_int(0), c_double(W1_PEAK_V))
        call(dwf, 'FDwfAnalogOutNodeOffsetSet', device, c_int(0), c_int(0), c_double(W1_OFFSET_V))
        call(dwf, 'FDwfAnalogOutConfigure', device, c_int(0), c_int(1))

        for channel in (0, 1):
            call(dwf, 'FDwfAnalogInChannelEnableSet', device, c_int(channel), c_int(1))
            call(dwf, 'FDwfAnalogInChannelRangeSet', device, c_int(channel), c_double(5.0))
        call(dwf, 'FDwfAnalogInTriggerSourceSet', device, c_int(0))
        time.sleep(0.6)
        print('Performing second-order filter characterization: 3 settings x 40 frequencies = 120 points.')
        print(f'Fixed second RC stage: {SECOND_STAGE_R_OHMS:.0f} ohm, {SECOND_STAGE_CAP_F*1e9:.0f} nF, pole={second_pole_hz():.1f} Hz')
        print('CH1 frequency is independently verified at each point.')
        print('CH2 measures the second op-amp output (MCP6022 pin 7).\n')

        # Preflight at 3 kHz: reject obviously missing second stage/wrong output lead.
        # Expected around -11 dB for h40, vs around -4.5 dB if CH2 is still
        # connected to the first buffer. Warn only, because analog tolerances vary.
        preflight_freq = 3000.0
        set_wiper(dwf, device, 64)
        set_frequency(dwf, device, preflight_freq)
        capture(dwf, device, preflight_freq)
        for _ in range(MAX_RETRIES):
            t, vin, vout = capture(dwf, device, preflight_freq)
            try:
                quick = analyze_capture(t, vin, vout, preflight_freq, 64)
                break
            except RuntimeError:
                time.sleep(0.1)
        else:
            raise RuntimeError('3 kHz preflight failed: check power, W1, scope, and op-amp wiring')
        print(f'Preflight h40 @ 3 kHz: gain {quick["gain_db"]:.2f} dB, '
              f'phase {quick["phase_deg"]:.1f} deg '
              f'(model {float(theory_at(preflight_freq, 64)[0]):.2f} dB, '
              f'{float(theory_at(preflight_freq, 64)[1]):.1f} deg)')
        if quick['gain_db'] > -7.0:
            print('WARNING: Attenuation is unexpectedly small for TWO RC stages. '
                  'Check AD3 CH2+ goes to MCP6022 pin 7 and the 2nd 10 nF capacitor.')
        print()

        for code in WIPERS:
            print(f'\n--- Wiper code {code} (h{code:02X}), overall theory fc = {theoretical_cutoff_hz(code):.0f} Hz ---')
            set_wiper(dwf, device, code)
            time.sleep(0.25)
            for i, freq in enumerate(FREQUENCIES_HZ, start=1):
                f = float(freq)
                set_frequency(dwf, device, f)
                capture(dwf, device, f)  # discard first capture after W1 change
                for attempt in range(1, MAX_RETRIES + 1):
                    t, vin, vout = capture(dwf, device, f)
                    try:
                        row = analyze_capture(t, vin, vout, f, code)
                        break
                    except RuntimeError as exc:
                        if attempt == MAX_RETRIES:
                            raise RuntimeError(
                                f'Bad measurement at h{code:02X}, {f:.1f} Hz after '
                                f'{MAX_RETRIES} attempts: {exc}') from exc
                        print(f'  Retrying {f:.1f} Hz ({attempt}/{MAX_RETRIES}): {exc}')
                        time.sleep(0.2)
                all_rows.append(row)
                print(f' [{i:02d}/{POINTS_PER_WIPER}] {f:8.1f} Hz  '
                      f'{row["gain_db"]:7.2f} dB  {row["phase_deg"]:7.2f} deg')

        save_results(all_rows)
        print('\nCompleted successfully.')

    except Exception:
        # Save partial data too, in case of wiring/intermittent acquisition issues.
        if all_rows:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            path = OUTPUT_DIR / 'second_order_auto_partial.csv'
            write_csv(path, all_rows)
            print(f'Partial results saved: {path}')
        raise
    finally:
        if device.value != 0:
            # Disable analog stimulus before removing chip power.
            try:
                dwf.FDwfAnalogOutConfigure(device, c_int(0), c_int(0))
                dwf.FDwfAnalogOutNodeEnableSet(device, c_int(0), c_int(0), c_int(0))
                time.sleep(0.05)
            finally:
                dwf.FDwfAnalogIOEnableSet(device, c_int(0))
                dwf.FDwfDeviceClose(device)


if __name__ == '__main__':
    main()
