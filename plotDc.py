
import csv
import matplotlib.pyplot as plt
from pathlib import Path

# Create results folder
Path("results").mkdir(exist_ok=True)

# Read experimental measurements
vin = []
vout = []
expected = []
errors = []

with open("dc_results.csv", "r") as file:
    reader = csv.DictReader(file)

    for row in reader:
        vin.append(float(row["Measured Vin (V)"]))
        vout.append(float(row["Measured Vout (V)"]))
        expected.append(float(row["Expected Vout (V)"]))
        errors.append(float(row["Error (%)"]))

# ---------------------------------------
# GRAPH 1: MEASURED VS THEORETICAL
# ---------------------------------------

plt.figure(figsize=(8, 5))

plt.plot(
    vin, expected, "--",
    label="Theoretical Vout"
)

plt.plot(
    vin, vout, "o-",
    label="Measured Vout"
)

plt.xlabel("Input Voltage (V)")
plt.ylabel("Output Voltage (V)")
plt.title("DC Voltage Divider Characterization")
plt.legend()
plt.grid(True)
plt.tight_layout()

plt.savefig("results/dc_voltage_response.png", dpi=300)
plt.close()

# ---------------------------------------
# GRAPH 2: PERCENTAGE ERROR
# ---------------------------------------

plt.figure(figsize=(8, 5))

plt.plot(vin, errors, "o-")

plt.xlabel("Input Voltage (V)")
plt.ylabel("Percentage Error (%)")
plt.title("Voltage Divider Error Analysis")
plt.grid(True)
plt.tight_layout()

plt.savefig("results/dc_error.png", dpi=300)
plt.close()

# ---------------------------------------
# SUMMARY
# ---------------------------------------

mean_error = sum(abs(e) for e in errors) / len(errors)
max_error = max(abs(e) for e in errors)

print("Graphs generated successfully!")
print(f"Mean absolute error: {mean_error:.3f}%")
print(f"Maximum absolute error: {max_error:.3f}%")
