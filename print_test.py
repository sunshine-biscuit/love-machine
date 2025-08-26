#!/usr/bin/env python3
"""
Simple Epson TM-T88VI test script.
Sends a short ESC/POS job to confirm connectivity.
"""

from escpos.printer import Network

PRINTER_IP = "192.168.192.168"   # direct-link IP
PRINTER_PORT = 9100              # standard ESC/POS port

try:
    p = Network(PRINTER_IP, port=PRINTER_PORT, timeout=10)
    p.text("=== Epson TM-T88VI Test ===\n")
    p.text("Hello from Raspberry Pi 5!\n")
    p.text("-----------------------------\n\n")
    p.cut()
    print("✅ Test print sent successfully.")
except Exception as e:
    print("❌ Failed to print:", e)

