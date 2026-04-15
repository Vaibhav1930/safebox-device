import asyncio
import os
from core.logger import get_logger, with_request_id

log = get_logger("smart_plug")

PLUG_IP = os.environ.get("TAPO_PLUG_IP", "")
TAPO_USER = os.environ.get("TAPO_USER", "")
TAPO_PASS = os.environ.get("TAPO_PASS", "")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()


async def _get_plug():
    from kasa import Discover
    if not PLUG_IP:
        raise ValueError("TAPO_PLUG_IP not set in environment")
    device = await Discover.discover_single(PLUG_IP, username=TAPO_USER, password=TAPO_PASS)
    await device.update()
    return device


async def _close(device):
    try:
        if hasattr(device, "protocol") and hasattr(device.protocol, "close"):
            await device.protocol.close()
    except Exception:
        pass


def turn_on() -> str:
    try:
        async def _on():
            device = await _get_plug()
            try:
                log.info("plug.command.request action=on", extra=with_request_id())
                await device.turn_on()
                await device.update()
                log.info("plug.command.result action=on success=True", extra=with_request_id())
                return "Smart plug is now ON."
            finally:
                await _close(device)
        return _run(_on())
    except Exception as e:
        log.warning(f"plug.command.failed action=on error={e}", extra=with_request_id())
        return "Sorry, I couldn't reach the smart plug."


def turn_off() -> str:
    try:
        async def _off():
            device = await _get_plug()
            try:
                log.info("plug.command.request action=off", extra=with_request_id())
                await device.turn_off()
                await device.update()
                log.info("plug.command.result action=off success=True", extra=with_request_id())
                return "Smart plug is now OFF."
            finally:
                await _close(device)
        return _run(_off())
    except Exception as e:
        log.warning(f"plug.command.failed action=off error={e}", extra=with_request_id())
        return "Sorry, I couldn't reach the smart plug."


def get_power_usage() -> str:
    try:
        async def _power():
            device = await _get_plug()
            try:
                await device.update()
                emeter = getattr(device, "emeter_realtime", {}) or {}
                watts = emeter.get("power", 0)
                state = "ON" if device.is_on else "OFF"
                log.info(
                    f"plug.power.read state={state.lower()} watts={watts}",
                    extra=with_request_id(),
                )
                return f"The plug is {state} and drawing {watts:.1f} watts."
            finally:
                await _close(device)
        return _run(_power())
    except Exception as e:
        log.warning(f"plug.power.failed error={e}", extra=with_request_id())
        return "Sorry, I couldn't get power usage right now."


def get_status() -> dict:
    try:
        async def _status():
            device = await _get_plug()
            try:
                await device.update()
                alias = getattr(device, "alias", None)
                emeter = getattr(device, "emeter_realtime", {}) or {}
                watts = emeter.get("power", 0)
                status = {
                    "configured": bool(PLUG_IP),
                    "connected": True,
                    "on": bool(device.is_on),
                    "state": "on" if device.is_on else "off",
                    "alias": alias,
                    "ip": PLUG_IP,
                    "power_w": round(float(watts), 1) if watts is not None else None,
                }
                log.info(
                    f"plug.status.read connected=True state={status['state']}",
                    extra=with_request_id(),
                )
                return status
            finally:
                await _close(device)
        return _run(_status())
    except Exception as e:
        log.warning(f"plug.status.failed error={e}", extra=with_request_id())
        return {
            "configured": bool(PLUG_IP),
            "connected": False,
            "on": None,
            "state": "unknown",
            "alias": None,
            "ip": PLUG_IP,
            "power_w": None,
        }
