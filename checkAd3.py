
from ctypes import cdll, c_int, byref, create_string_buffer

# Load the Digilent WaveForms SDK
dwf = cdll.LoadLibrary("dwf.dll")

# Retrieve SDK version
version = create_string_buffer(32)
dwf.FDwfGetVersion(version)

print("WaveForms SDK Version:", version.value.decode())

# Count connected Digilent devices
device_count = c_int()
dwf.FDwfEnum(c_int(0), byref(device_count))

print("Devices Found:", device_count.value)

# Display connected device names
for i in range(device_count.value):
    name = create_string_buffer(64)

    dwf.FDwfEnumDeviceName(c_int(i), name)

    print("Device", i, ":", name.value.decode())
