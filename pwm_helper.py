# pwm_helper.py — dual-channel sysfs PWM (Pi 5, pwmchip0 channels 2 & 3)
# API: init_pwm(); set_brightness(level01: 0..1)
from pathlib import Path
import time

PWMCHIP = 0              # <-- you confirmed pwmchip0 works
CHANNELS = (2, 3)        # <-- GPIO18 = CH2, GPIO19 = CH3 on your Pi 5
PERIOD_NS = 40_000       # 25 kHz (quiet)
ACTIVE_HIGH = True       # True: 0=off, 1=full. Flip to False if inverted

CHIP = Path(f"/sys/class/pwm/pwmchip{PWMCHIP}")

def _pwm_base(ch: int) -> Path:
    return CHIP / f"pwm{ch}"

def _write(p: Path, s: str):
    # tiny retry for races on first write
    try:
        p.write_text(s)
    except Exception:
        time.sleep(0.01)
        p.write_text(s)

def _ensure_exported(ch: int):
    base = _pwm_base(ch)
    if not base.exists():
        (CHIP / "export").write_text(str(ch))
        # wait for sysfs to appear
        for _ in range(100):
            if base.exists(): break
            time.sleep(0.01)

def _setup_channel(ch: int):
    base = _pwm_base(ch)
    enable = base / "enable"
    period = base / "period"
    duty   = base / "duty_cycle"

    # disable while configuring (ignore if missing)
    try:
        if enable.exists():
            _write(enable, "0")
    except Exception:
        pass

    # set period
    try:
        cur = period.read_text().strip()
    except Exception:
        cur = ""
    if cur != str(PERIOD_NS):
        _write(period, str(PERIOD_NS))

    # start OFF
    off_ns = 0 if ACTIVE_HIGH else PERIOD_NS
    _write(duty, str(off_ns))

    # enable
    _write(enable, "1")

def init_pwm():
    if not CHIP.exists():
        raise RuntimeError(f"{CHIP} not found. Ensure /boot/firmware/config.txt has:\n"
                           "  dtparam=audio=off\n"
                           "  dtoverlay=pwm-2chan,pin=18,pin2=19,func=2\n"
                           "and you rebooted.")
    try:
        for ch in CHANNELS:
            _ensure_exported(ch)
            _setup_channel(ch)
    except PermissionError:
        raise RuntimeError("Need permission to write /sys/class/pwm. Run with sudo.")

def set_brightness(level01: float):
    # clamp 0..1
    try:
        x = float(level01)
    except Exception:
        x = 0.0
    if x < 0: x = 0.0
    if x > 1: x = 1.0

    duty_ns = int(PERIOD_NS * x)
    if not ACTIVE_HIGH:
        duty_ns = PERIOD_NS - duty_ns

    for ch in CHANNELS:
        _write(_pwm_base(ch) / "duty_cycle", str(duty_ns))
