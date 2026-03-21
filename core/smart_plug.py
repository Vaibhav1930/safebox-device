"""
core/smart_plug.py
Tapo P110 smart plug controller via local LAN using python-kasa.
"""

import asyncio
import os
from core.logger import get_logger

log = get_logger("smart_plug")

PLUG_IP = os.environ.get("TAPO_PLUG_IP", "")
TAPO_USER = os.environ.get("TAPO_USER", "")
TAPO_PASS = os.environ.get("TAPO_PASS", "")


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)


async def _get_plug():
    from kasa import Discover
    if not PLUG_IP:
        raise ValueError("TAPO_PLUG_IP not set in environment")
    device = await Discover.discover_single(PLUG_IP, username=TAPO_USER, password=TAPO_PASS)
    await device.update()
    return device


def turn_on() -> str:
    try:
        async def _on():
            device = await _get_plug()
            await device.turn_on()
            await device.update()
            log.info("smart_plug.on | success")
            return "Smart plug is now ON."
        return _run(_on())
    except Exception as e:
        log.warning(f"smart_plug.on.failed | reason={e}")
        return "Sorry, I couldn't reach the smart plug."


def turn_off() -> str:
    try:
        async def _off():
            device = await _get_plug()
            await device.turn_off()
            await device.update()
            log.info("smart_plug.off | success")
            return "Smart plug is now OFF."
        return _run(_off())
    except Exception as e:
        log.warning(f"smart_plug.off.failed | reason={e}")
        return "Sorry, I couldn't reach the smart plug."


def get_power_usage() -> str:
    try:
        async def _power():
            device = await _get_plug()
            emeter = device.emeter_realtime
            watts = emeter.get("power", 0)
            state = "ON" if device.is_on else "OFF"
            return f"The plug is {state} and drawing {watts:.1f} watts."
        return _run(_power())
    except Exception as e:
        log.warning(f"smart_plug.power.failed | reason={e}")
        return "Sorry, I couldn't get power usage right now."


def get_status() -> dict:
    try:
        async def _status():
            device = await _get_plug()
            return {"connected": True, "state": "on" if device.is_on else "off", "ip": PLUG_IP}
        return _run(_status())
    except Exception as e:
        log.warning(f"smart_plug.status.failed | reason={e}")
        return {"connected": False, "state": "unknown", "ip": PLUG_IP}
