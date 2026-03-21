"""
core/temperature.py
DS18B20 temperature sensor reader via 1-Wire GPIO.
Sensor must be on GPIO 4 with 4.7k pull-up resistor.
"""

import glob
from core.logger import get_logger

log = get_logger("temperature")

W1_BASE = "/sys/bus/w1/devices/"


def _find_sensor():
    devices = glob.glob(W1_BASE + "28-*")
    if not devices:
        log.warning("temperature.sensor_not_found")
        return None
    return devices[0] + "/w1_slave"


def read_celsius():
    sensor_path = _find_sensor()
    if not sensor_path:
        return None
    try:
        with open(sensor_path, "r") as f:
            lines = f.readlines()
        if "YES" not in lines[0]:
            log.warning("temperature.crc_failed")
            return None
        temp_line = lines[1]
        t_pos = temp_line.find("t=")
        if t_pos == -1:
            return None
        temp_c = float(temp_line[t_pos + 2:]) / 1000.0
        log.info(f"temperature.read | celsius={temp_c}")
        return round(temp_c, 1)
    except Exception as e:
        log.warning(f"temperature.read.failed | reason={e}")
        return None


def read_fahrenheit():
    celsius = read_celsius()
    if celsius is None:
        return None
    return round(celsius * 9 / 5 + 32, 1)


def get_temperature_response() -> str:
    celsius = read_celsius()
    if celsius is None:
        return "Sorry, I couldn't read the temperature sensor. Make sure it's connected."
    fahrenheit = round(celsius * 9 / 5 + 32, 1)
    return f"The current temperature is {celsius} degrees Celsius, or {fahrenheit} degrees Fahrenheit."


def get_status() -> dict:
    celsius = read_celsius()
    return {
        "connected": celsius is not None,
        "celsius": celsius,
        "fahrenheit": read_fahrenheit() if celsius is not None else None,
    }
