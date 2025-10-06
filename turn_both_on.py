# turn_both_on.py
import time, RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
for pin in (12, 13):
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, True)   # drive SIG high → LEDs on
time.sleep(10)               # on for 10s
GPIO.cleanup()
