import time
import serial
import threading

def _checksum(payload):
    # payload = bytes [0xFF,0x06,CMD,0x00,PH,PL]
    s = sum(payload) & 0xFFFF
    return ((0 - s) & 0xFFFF)

class DFPlayer:
    def __init__(self, port="/dev/serial0", baud=9600, verbose=True):
        self.verbose = verbose
        self.ser = serial.Serial(port, baudrate=baud, timeout=0.25)
        time.sleep(0.2)
        self._lock = threading.Lock()

    def _send(self, cmd, param=0):
        PH = (param >> 8) & 0xFF
        PL = param & 0xFF
        payload = bytearray([0xFF, 0x06, cmd, 0x00, PH, PL])
        chk = _checksum(payload)
        frame = bytearray([0x7E]) + payload + bytearray([(chk >> 8) & 0xFF, chk & 0xFF, 0xEF])
        with self._lock:
            if self.verbose:
                print(f"[DFP] CMD=0x{cmd:02X} PARAM=0x{param:04X}")
            self.ser.write(frame)
            self.ser.flush()
            time.sleep(0.05)

    # Common commands
    def reset(self):
        self._send(0x0C)
        time.sleep(0.5)

    def set_device_tf(self):
        # 0x09: specify device; 0x0002 = TF (microSD)
        self._send(0x09, 0x0002)
        time.sleep(0.2)

    def set_volume(self, vol):
        vol = max(0, min(30, int(vol)))
        self._send(0x06, vol)

    def stop(self):
        self._send(0x16)

    def pause(self):
        self._send(0x0E)

    def resume(self):
        self._send(0x0D)

    def single_loop_on(self):
        self._send(0x19, 0x0001)

    def single_loop_off(self):
        self._send(0x19, 0x0000)

    # Play methods (try all if needed)
    def play_mp3_index(self, idx):
        # plays /mp3/0001.mp3 as index 1 on most cards
        self._send(0x12, idx)

    def play_track_index_global(self, idx):
        # legacy: absolute index across device (sometimes works better)
        self._send(0x03, idx)

    def play_folder_track(self, folder_idx, file_idx):
        # plays /<folder_idx>/<00..255>.mp3 — e.g., /01/001.mp3 = (0x01,0x01)
        self._send(0x0F, ((folder_idx & 0xFF) << 8) | (file_idx & 0xFF))

def start_init_loop(volume=26):
    p = DFPlayer()
    try:
        p.reset()
        p.set_device_tf()
        p.set_volume(volume)
        p.single_loop_on()

        # Try a few play styles; one should “catch”:
        # 1) /mp3/0001.mp3 via MP3 index
        p.play_mp3_index(1)
        time.sleep(0.5)

        # 2) global index 1
        p.play_track_index_global(1)
        time.sleep(0.5)

        # 3) folder play (in case you used /01/001.mp3)
        # (harmless if folder/track doesn't exist)
        p.play_folder_track(1, 1)

    except Exception as e:
        print("[DFP] start_init_loop error:", e)
    return p

def stop_any(p):
    if not p:
        return
    try:
        p.stop()
    except Exception as e:
        print("[DFP] stop error:", e)
    try:
        p.ser.close()
    except Exception:
        pass
