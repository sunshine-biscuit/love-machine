import RPi.GPIO as GPIO
import time

SENSOR_PIN = 17  # GPIO17, physical pin 11

GPIO.setmode(GPIO.BCM)
GPIO.setup(SENSOR_PIN, GPIO.IN)

print("Waiting for paper... (CTRL+C to quit)")
try:
    while True:
        if GPIO.input(SENSOR_PIN) == 0:
            print("✅ Paper detected!")
            time.sleep(1)  # debounce delay
        else:
            print("… no paper")
        time.sleep(0.2)

except KeyboardInterrupt:
    print("\nExiting...")
    GPIO.cleanup()
