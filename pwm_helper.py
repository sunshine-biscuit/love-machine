from pathlib import Path
import time

# --- select the PWM device that worked in your manual test ---
PWMCHIP  = 0        # you said pwmchip0/pwm0 worked
CHANNEL  = 0

BASE   = Path(f"/sys/class/pwm/pwmchip{PWMCHIP}/pwm{CHANNEL}")
PERIOD = BASE / "period"
DUTY   = BASE / "duty_cycle"
ENABLE = BASE / "enable"

# --- pick your PWM frequency (higher removes audible whine) ---
# 40_000 ns = 25 kHz   (good)
# 33_333 ns ≈ 30 kHz   (also good)
PERIOD_NS = 40_000

def _write(p: Path, text: str):
    p.write_text(text)

def init_pwm():
    # make sure channel is exported and configured
    chip = BASE.parent
    export = chip / "export"
    if not BASE.exists():
        try:
            export.write_text(str(CHANNEL))
            # allow kernel to create files
            time.sleep(0.05)
        except Exception as e:
            raise PermissionError(f"Failed to export PWM channel: {e}")

    # disable before reconfiguring
    if ENABLE.exists():
        try: _write(ENABLE, "0")
        except: pass

    # set period then duty (duty must be <= period)
    _write(PERIOD, str(PERIOD_NS))
    _write(DUTY, "0")

    # enable output
    _write(ENABLE, "1")

def set_brightness(level01: float):
    # clamp 0..1 then scale to duty in nanoseconds
    x = 0.0 if level01 < 0 else (1.0 if level01 > 1.0 else level01)
    duty = int(PERIOD_NS * x)
    _write(DUTY, str(duty))
