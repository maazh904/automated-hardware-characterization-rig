"""First Python-controlled MCP4131 + RC filter test using Analog Discovery 3.

Connections are the same as the manually validated 2.22 kOhm + MCP4131 + 10 nF filter.
The script powers the chip at 3.3 V, drives W1 with a 3 kHz sine centered
at 1.65 V, changes the MCP4131 wiper over SPI, and measures input/output
amplitudes and phase using the AD3 oscilloscope.

Close the WaveForms application before running (the SDK opens the AD3).
"""

from ctypes import byref, c_byte, c_double, c_int, c_ubyte, cdll, create_string_buffer
import math
import time

DWF = cdll.LoadLibrary("dwf.dll")  # Windows with WaveForms installed
DEVICE = c_int()

FREQ_HZ = 3000.0
SAMPLE_RATE = 200_000.0
SAMPLES = 8000


def check(name, *args):
    if getattr(DWF, name)(*args) == 0:
        message = create_string_buffer(512)
        DWF.FDwfGetLastErrorMsg(message)
        raise RuntimeError(f"{name} failed: {message.value.decode(errors='replace')}")


def set_wiper(value):
    """Write 0x00, wiper value (0..128) in ONE SPI transaction."""
    if not 0 <= value <= 128:
        raise ValueError("Wiper value must be 0 through 128")
    packet = (c_ubyte * 2)(0x00, value)
    check("FDwfDigitalSpiSelect", DEVICE, c_int(0), c_int(0))  # CS low
    try:
        check("FDwfDigitalSpiWrite", DEVICE, c_int(0), c_int(8), packet, c_int(2))
    finally:
        check("FDwfDigitalSpiSelect", DEVICE, c_int(0), c_int(1))  # CS high


def capture():
    """Collect one pair of synchronously sampled traces; discard startup capture."""
    check("FDwfAnalogInConfigure", DEVICE, c_int(1), c_int(1))
    status = c_byte()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        check("FDwfAnalogInStatus", DEVICE, c_int(1), byref(status))
        if status.value == 2:  # DwfStateDone
            break
        time.sleep(0.005)
    else:
        raise TimeoutError("Scope acquisition did not complete")

    vin = (c_double * SAMPLES)()
    vout = (c_double * SAMPLES)()
    check("FDwfAnalogInStatusData", DEVICE, c_int(0), vin, c_int(SAMPLES))
    check("FDwfAnalogInStatusData", DEVICE, c_int(1), vout, c_int(SAMPLES))
    return vin, vout


def sine_amplitude_phase(samples):
    """Project onto a known-frequency sine and cosine: return peak volts, phase radians."""
    n = len(samples)
    avg = sum(samples) / n
    omega = 2.0 * math.pi * FREQ_HZ / SAMPLE_RATE
    a = 2.0 / n * sum((v - avg) * math.cos(omega * i) for i, v in enumerate(samples))
    b = 2.0 / n * sum((v - avg) * math.sin(omega * i) for i, v in enumerate(samples))
    return math.hypot(a, b), math.atan2(-b, a)


try:
    check("FDwfDeviceOpen", c_int(-1), byref(DEVICE))
    if DEVICE.value == 0:
        raise RuntimeError("Could not open AD3. Close WaveForms and try again.")
    print("AD3 connected")

    # Power first, before any analog stimulus, to protect MCP4131 terminals.
    check("FDwfAnalogIOEnableSet", DEVICE, c_int(0))
    check("FDwfAnalogIOChannelNodeSet", DEVICE, c_int(0), c_int(1), c_double(3.3))
    check("FDwfAnalogIOChannelNodeSet", DEVICE, c_int(0), c_int(0), c_double(1))
    check("FDwfAnalogIOEnableSet", DEVICE, c_int(1))
    time.sleep(0.4)

    # SPI: CS=0, SCK=1, MOSI=2, mode 0, MSB first, 100 kHz.
    check("FDwfDigitalSpiReset", DEVICE)
    check("FDwfDigitalSpiFrequencySet", DEVICE, c_double(100_000))
    check("FDwfDigitalSpiClockSet", DEVICE, c_int(1))
    check("FDwfDigitalSpiDataSet", DEVICE, c_int(0), c_int(2))
    check("FDwfDigitalSpiModeSet", DEVICE, c_int(0))
    check("FDwfDigitalSpiOrderSet", DEVICE, c_int(1))
    check("FDwfDigitalSpiSelectSet", DEVICE, c_int(0), c_int(1))
    check("FDwfDigitalSpiSelect", DEVICE, c_int(0), c_int(1))
    set_wiper(64)

    # W1: 3 kHz, 0.3 V peak, 1.65 V DC offset.
    # Set idle output to 0 V rather than leaving the 1.65 V offset active.
    check("FDwfAnalogOutIdleSet", DEVICE, c_int(0), c_int(0))
    check("FDwfAnalogOutNodeEnableSet", DEVICE, c_int(0), c_int(0), c_int(1))
    check("FDwfAnalogOutNodeFunctionSet", DEVICE, c_int(0), c_int(0), c_int(1))
    check("FDwfAnalogOutNodeFrequencySet", DEVICE, c_int(0), c_int(0), c_double(FREQ_HZ))
    check("FDwfAnalogOutNodeAmplitudeSet", DEVICE, c_int(0), c_int(0), c_double(0.3))
    check("FDwfAnalogOutNodeOffsetSet", DEVICE, c_int(0), c_int(0), c_double(1.65))
    check("FDwfAnalogOutConfigure", DEVICE, c_int(0), c_int(1))

    # Oscilloscope: two channels, 200 kS/s, 8000 samples.
    check("FDwfAnalogInFrequencySet", DEVICE, c_double(SAMPLE_RATE))
    check("FDwfAnalogInBufferSizeSet", DEVICE, c_int(SAMPLES))
    check("FDwfAnalogInTriggerSourceSet", DEVICE, c_int(0))  # no trigger
    for channel in (0, 1):
        check("FDwfAnalogInChannelEnableSet", DEVICE, c_int(channel), c_int(1))
        check("FDwfAnalogInChannelRangeSet", DEVICE, c_int(channel), c_double(5))
    time.sleep(0.5)

    print("\nWiper | Vin peak | Vout peak | Gain (dB) | Phase (deg)")
    print("------|----------|-----------|-----------|------------")
    for code in (32, 64, 96):
        set_wiper(code)
        time.sleep(0.20)
        capture()  # Discard first capture after changing settings.
        vin, vout = capture()
        ain, pin = sine_amplitude_phase(vin)
        aout, pout = sine_amplitude_phase(vout)
        if ain < 0.05:
            raise RuntimeError("CH1 amplitude is unexpectedly low: check W1 and CH1 wiring")
        gain_db = 20 * math.log10(aout / ain)
        phase = math.degrees((pout - pin + math.pi) % (2 * math.pi) - math.pi)
        print(f"{code:5d} | {ain:8.4f} | {aout:9.4f} | {gain_db:9.2f} | {phase:10.2f}")

finally:
    if DEVICE.value != 0:
        # Turn off W1 BEFORE turning off MCP4131 power.
        try:
            DWF.FDwfAnalogOutConfigure(DEVICE, c_int(0), c_int(0))
            DWF.FDwfAnalogOutNodeEnableSet(DEVICE, c_int(0), c_int(0), c_int(0))
            time.sleep(0.05)
        finally:
            DWF.FDwfAnalogIOEnableSet(DEVICE, c_int(0))
            DWF.FDwfDeviceClose(DEVICE)
