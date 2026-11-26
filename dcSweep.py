
import csv
import time
from ctypes import (
    cdll, c_int, c_double, c_byte,
    byref, create_string_buffer
)

# ------------------------------------------
# LOAD WAVEFORMS SDK
# ------------------------------------------

dwf = cdll.LoadLibrary("dwf.dll")

# ------------------------------------------
# EXPERIMENT SETTINGS
# ------------------------------------------

R1 = 1000.0
R2 = 1000.0

voltages = [0.5, 1.0, 1.5, 2.0, 2.5]

SAMPLES = 1024
SETTLING_TIME = 2.0
VOLTAGE_TOLERANCE = 0.1

hdwf = c_int(0)


# ------------------------------------------
# SDK ERROR CHECKING
# ------------------------------------------

def check(function, *args):

    result = getattr(dwf, function)(*args)

    if result == 0:
        error = create_string_buffer(512)
        dwf.FDwfGetLastErrorMsg(error)

        raise RuntimeError(
            f"{function}: {error.value.decode()}"
        )


# ------------------------------------------
# OSCILLOSCOPE MEASUREMENT
# ------------------------------------------

def measure_channel(channel):

    buffer = (c_double * SAMPLES)()

    check(
        "FDwfAnalogInStatusData",
        hdwf,
        c_int(channel),
        buffer,
        c_int(SAMPLES)
    )

    return sum(buffer) / SAMPLES


def acquire_measurement():

    # Start a new acquisition
    check(
        "FDwfAnalogInConfigure",
        hdwf,
        c_int(1),
        c_int(1)
    )

    status = c_byte()
    deadline = time.monotonic() + 5.0

    # Wait for acquisition to finish
    while True:

        check(
            "FDwfAnalogInStatus",
            hdwf,
            c_int(1),
            byref(status)
        )

        if status.value == 2:
            break

        if time.monotonic() > deadline:
            raise TimeoutError(
                "Oscilloscope acquisition timed out"
            )

        time.sleep(0.01)

    vin = measure_channel(0)
    vout = measure_channel(1)

    return vin, vout


# ------------------------------------------
# MAIN PROGRAM
# ------------------------------------------

try:

    # Open Analog Discovery 3
    check(
        "FDwfDeviceOpen",
        c_int(-1),
        byref(hdwf)
    )

    if hdwf.value == 0:
        raise RuntimeError("Could not open AD3")

    print("Connected to Analog Discovery 3")

    # Disable automatic configuration
    check(
        "FDwfDeviceAutoConfigureSet",
        hdwf,
        c_int(0)
    )

    # --------------------------------------
    # CONFIGURE WAVEGEN
    # --------------------------------------

    # Enable W1 carrier
    check(
        "FDwfAnalogOutNodeEnableSet",
        hdwf,
        c_int(0),
        c_int(0),
        c_int(1)
    )

    # DC waveform function
    check(
        "FDwfAnalogOutNodeFunctionSet",
        hdwf,
        c_int(0),
        c_int(0),
        c_int(0)
    )

    # Continuous output
    check(
        "FDwfAnalogOutRunSet",
        hdwf,
        c_int(0),
        c_double(0)
    )

    # --------------------------------------
    # CONFIGURE OSCILLOSCOPE
    # --------------------------------------

    for channel in (0, 1):

        check(
            "FDwfAnalogInChannelEnableSet",
            hdwf,
            c_int(channel),
            c_int(1)
        )

        check(
            "FDwfAnalogInChannelRangeSet",
            hdwf,
            c_int(channel),
            c_double(5.0)
        )

    check(
        "FDwfAnalogInFrequencySet",
        hdwf,
        c_double(200000)
    )

    check(
        "FDwfAnalogInBufferSizeSet",
        hdwf,
        c_int(SAMPLES)
    )

    # Disable triggering
    check(
        "FDwfAnalogInTriggerSourceSet",
        hdwf,
        c_int(0)
    )

    # --------------------------------------
    # INITIAL STARTUP MEASUREMENT
    # --------------------------------------

    print("\nInitializing hardware...")

    # Set initial voltage to 0.5 V
    check(
        "FDwfAnalogOutNodeOffsetSet",
        hdwf,
        c_int(0),
        c_int(0),
        c_double(voltages[0])
    )

    # Start Wavegen ONCE
    check(
        "FDwfAnalogOutConfigure",
        hdwf,
        c_int(0),
        c_int(1)
    )

    time.sleep(SETTLING_TIME)

    # Discard initial scope acquisition
    startup_vin, startup_vout = acquire_measurement()

    print(
        f"Startup measurement (excluded): "
        f"Vin = {startup_vin:.4f} V | "
        f"Vout = {startup_vout:.4f} V"
    )

    # --------------------------------------
    # AUTOMATED DC VOLTAGE SWEEP
    # --------------------------------------

    print("\nStarting automated voltage sweep...\n")

    with open(
        "dc_results.csv",
        "w",
        newline=""
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "Set Voltage (V)",
            "Measured Vin (V)",
            "Measured Vout (V)",
            "Expected Vout (V)",
            "Divider Ratio",
            "Error (%)"
        ])

        for voltage in voltages:

            # Update W1 voltage
            check(
                "FDwfAnalogOutNodeOffsetSet",
                hdwf,
                c_int(0),
                c_int(0),
                c_double(voltage)
            )

            # IMPORTANT FIX:
            # 3 = Apply changes without restarting
            check(
                "FDwfAnalogOutConfigure",
                hdwf,
                c_int(0),
                c_int(3)
            )

            # Allow hardware to settle
            time.sleep(SETTLING_TIME)

            # Acquire measurements
            vin, vout = acquire_measurement()

            # ----------------------------------
            # VALIDATE INPUT MEASUREMENT
            # ----------------------------------

            if abs(vin - voltage) > VOLTAGE_TOLERANCE:

                raise RuntimeError(
                    f"Invalid measurement at {voltage:.2f} V: "
                    f"Vin = {vin:.4f} V. "
                    f"Expected approximately {voltage:.2f} V."
                )

            # ----------------------------------
            # CALCULATE EXPECTED OUTPUT
            # ----------------------------------

            expected = vin * R2 / (R1 + R2)

            if abs(expected) < 1e-9:
                raise RuntimeError(
                    "Expected voltage too small "
                    "for percentage error calculation"
                )

            # ----------------------------------
            # CALCULATE DIVIDER RATIO
            # ----------------------------------

            ratio = vout / vin

            # ----------------------------------
            # CALCULATE PERCENTAGE ERROR
            # ----------------------------------

            error = (
                (vout - expected)
                / expected
            ) * 100

            # ----------------------------------
            # SAVE MEASUREMENTS
            # ----------------------------------

            writer.writerow([
                voltage,
                vin,
                vout,
                expected,
                ratio,
                error
            ])

            # Display measurements
            print(
                f"Set: {voltage:.2f} V | "
                f"Vin: {vin:.4f} V | "
                f"Vout: {vout:.4f} V | "
                f"Ratio: {ratio:.4f} | "
                f"Error: {error:.2f}%"
            )

    print("\nVoltage sweep complete!")
    print("Results saved to dc_results.csv")


# ------------------------------------------
# SAFE HARDWARE CLEANUP
# ------------------------------------------

finally:

    if hdwf.value != 0:

        try:
            # Stop waveform generator
            dwf.FDwfAnalogOutConfigure(
                hdwf,
                c_int(0),
                c_int(0)
            )

            # Reset waveform generator
            dwf.FDwfAnalogOutReset(
                hdwf,
                c_int(0)
            )

        finally:
            # Disconnect device
            dwf.FDwfDeviceClose(hdwf)

        print("\nAD3 disconnected safely.")
