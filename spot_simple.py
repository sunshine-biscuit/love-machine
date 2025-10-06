# spot_simple.py — simple ON/OFF on GPIO13 using RPi.GPIO (no PWM)
try:
    import RPi.GPIO as GPIO
    _OK = True
except Exception as e:
    print("[spot] WARN: RPi.GPIO not available:", e)
    _OK = False

PIN = 13  # BCM (physical pin 33)
_inited = False

def init_spot():
    global _inited
    if not _OK or _inited: return
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN, GPIO.OUT, initial=GPIO.LOW)  # active-HIGH module
    _inited = True
    print("[spot] ON/OFF ready on GPIO13")

def spot_on():
    if _OK: GPIO.output(PIN, GPIO.HIGH)

def spot_off():
    if _OK: GPIO.output(PIN, GPIO.LOW)

def cleanup_spot():
    if not _OK: return
    try:
        GPIO.output(PIN, GPIO.LOW)
    except Exception:
        pass
    try:
        GPIO.cleanup(PIN)
    except Exception:
        pass
