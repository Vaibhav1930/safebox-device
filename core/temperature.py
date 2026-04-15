import glob
from core.logger import get_logger, with_request_id

log = get_logger("temperature")

W1_BASE = "/sys/bus/w1/devices/"


def _find_sensor():
    devices = glob.glob(W1_BASE + "28-*")
    if not devices:
        log.warning("sensor.temperature.not_found", extra=with_request_id())
        return None
    return devices[0] + "/w1_slave"


def read_celsius():
    sensor_path = _find_sensor()
    if not sensor_path:
        return None
    try:
        with open(sensor_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if "YES" not in lines[0]:
            log.warning("sensor.temperature.crc_failed", extra=with_request_id())
            return None
        temp_line = lines[1]
        t_pos = temp_line.find("t=")
        if t_pos == -1:
            log.warning("sensor.temperature.malformed", extra=with_request_id())
            return None
        temp_c = float(temp_line[t_pos + 2:]) / 1000.0
        temp_c = round(temp_c, 1)
        log.info(f"sensor.temperature.read value_c={temp_c}", extra=with_request_id())
        return temp_c
    except Exception as e:
        log.warning(f"sensor.temperature.failed error={e}", extra=with_request_id())
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
    fahrenheit = round(celsius * 9 / 5 + 32, 1) if celsius is not None else None
    return {
        "connected": celsius is not None,
        "celsius": celsius,
        "fahrenheit": fahrenheit,
        "status": "ok" if celsius is not None else "unavailable",
    }
