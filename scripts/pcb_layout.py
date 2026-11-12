"""Board definition: outline, placement, net classes and copper planes.

All coordinates are board millimetres with the origin at the top-left corner
of the outline, x to the right and y down.  Rotation follows KiCad: degrees,
counter-clockwise as seen from the top.
"""

BOARD_W, BOARD_H = 120.0, 80.0
ORIGIN = (40.0, 40.0)            # where the board sits on the KiCad page

# ---- placement: ref -> (x, y, rotation) -------------------------------------
P = {}

# mounting holes
P.update(H1=(4, 4, 0), H2=(116, 4, 0), H3=(4, 76, 0), H4=(116, 76, 0))

# field terminals along the bottom edge, power on the left, sensors, relay
P.update(J2=(12.1, 72, 0), J6=(21.8, 72, 0), J8=(31.5, 72, 0), J9=(41.2, 72, 0),
         J10=(57.9, 72, 0), J11=(71.1, 72, 0), J12=(87.8, 72, 0), J7=(97.5, 72, 0))

# 12 V input and protection
P.update(J1=(13.5, 50.0, 270), F1=(20.0, 50.0, 0), D1=(26.0, 53.0, 90),
         Q1=(27.0, 46.0, 180), D2=(32.5, 44.6, 0), R1=(32.5, 46.8, 0),
         C1=(37.5, 53.0, 0), C2=(30.0, 51.5, 90), TP1=(30.0, 55.3, 0))

# logic supply: diode-OR, bulk cap, 3.3 V buck
P.update(D3=(20.0, 41.5, 0), D4=(20.0, 29.5, 0), C3=(9.0, 36.5, 90), C4=(17.5, 36.0, 90),
         U1=(21.5, 35.0, 0), C5=(25.2, 33.0, 180), L1=(27.5, 37.0, 0),
         C6=(31.8, 37.0, 90), C7=(34.2, 37.0, 90), R2=(31.8, 41.0, 0), D5=(35.0, 41.0, 180),
         TP2=(13.0, 27.5, 0), TP3=(36.5, 33.5, 0))

# 5 V sensor regulator
P.update(U2=(48.0, 50.0, 0), C8=(44.0, 51.6, 90), C9=(44.0, 47.9, 90))

# buzzer
P.update(LS1=(8.0, 14.0, 0), Q2=(20.5, 14.0, 180), R20=(19.3, 17.0, 0),
         R18=(24.6, 15.0, 180), R19=(24.6, 13.0, 0))

# display socket, status LED, buttons
P.update(J4=(36.19, 6.0, 90), D6=(58.5, 12.0, 0), C16=(58.5, 14.7, 0), R17=(58.5, 16.4, 0),
         SW4=(39.5, 36.0, 0), SW3=(49.5, 36.0, 0), SW2=(59.5, 36.0, 0),
         R9=(41.0, 43.3, 0), R8=(44.5, 43.3, 180), R7=(52.5, 43.3, 0), R6=(62.5, 43.3, 0))

# ESP32-C6 module (antenna flush with the top edge) and its support parts
P.update(U3=(86.0, 11.05, 0), C12=(76.0, 8.6, 90), C11=(73.8, 8.6, 90),
         R5=(75.5, 12.0, 0), C13=(75.5, 13.7, 180), SW1=(70.0, 13.5, 180),
         C27=(78.5, 22.0, 270), C10=(80.6, 22.0, 270), C18=(82.7, 22.0, 270),
         R15=(84.8, 22.0, 90), R16=(86.9, 22.0, 90), TP7=(96.5, 10.0, 0))

# supply-voltage divider next to the 12 V rail (only the divided signal travels)
P.update(R3=(46.5, 54.6, 0), R4=(46.5, 56.3, 180))

# real-time clock and backup capacitor
P.update(U5=(98.5, 21.0, 0), C14=(98.5, 24.6, 0), C15=(102.8, 21.0, 90))

# USB-C on the right edge
P.update(J3=(116.8, 30.0, 90), U4=(108.0, 30.0, 0), R11=(101.5, 29.1, 180),
         R12=(101.5, 30.9, 180), R14=(110.3, 25.9, 90), R13=(110.3, 33.9, 270),
         R10=(109.0, 36.6, 0), J5=(112.0, 44.0, 90))

# valve motor driver
P.update(U6=(25.75, 63.0, 0),
         R25=(17.0, 59.6, 180), R26=(17.0, 61.8, 0), C17=(17.0, 64.0, 180), R23=(17.0, 66.2, 180),
         R21=(13.0, 61.8, 0), R22=(13.0, 64.0, 180), R24=(13.0, 66.2, 0),
         C21=(32.8, 63.3, 90), C22=(34.6, 62.3, 90), C19=(32.8, 66.5, 90), C20=(36.6, 65.9, 90))

# switched 12 V output
P.update(D8=(40.5, 59.5, 0), R29=(39.6, 63.0, 0), R30=(39.6, 64.8, 180), Q4=(43.3, 65.6, 0))

# sensor input stages, directly above their terminals
P.update(Q5=(47.5, 65.5, 270), R32=(46.5, 62.0, 270), R31=(48.5, 62.0, 90), C23=(48.5, 58.9, 90),
         Q6=(51.5, 65.5, 270), R34=(50.6, 62.0, 270), R33=(52.4, 62.0, 90), C24=(52.4, 58.9, 90),
         U7=(56.5, 66.3, 0), TP4=(59.7, 62.3, 0),
         Q7=(63.0, 65.5, 270), R36=(62.1, 62.0, 270), R35=(63.9, 62.0, 90), C25=(63.9, 58.9, 90),
         Q8=(76.0, 65.5, 270), R38=(75.1, 62.0, 270), R37=(76.9, 62.0, 90), C26=(76.9, 58.9, 90),
         U8=(86.0, 66.3, 0), R40=(90.0, 66.5, 270), R39=(91.8, 66.5, 90))

# relay and its driver
P.update(K1=(115.5, 58.5, 180), Q3=(112.0, 53.0, 0), D7=(106.0, 53.5, 0),
         R27=(112.0, 49.5, 0), R28=(115.5, 49.5, 0))

# ground test points
P.update(TP5=(70.0, 47.0, 0), TP6=(5.0, 66.5, 0))

# ---- net classes -------------------------------------------------------------
# name: (track width, clearance, via diameter, via drill)
CLASSES = {
    'Default': (0.20, 0.15, 0.60, 0.30),
    'Power':   (0.40, 0.20, 0.80, 0.40),
    'Supply':  (0.80, 0.20, 0.80, 0.40),
    'Relay':   (1.20, 0.40, 1.00, 0.50),
}
NET_CLASS = {
    'GND': 'Power', '+12V': 'Power', '+5V': 'Power', '+3V3': 'Power', 'VBUS': 'Power',
    '/Valve drive/MOTOR_A': 'Power', '/Valve drive/MOTOR_B': 'Power',
    'Net-(U1-SW)': 'Power', 'Net-(D8-A)': 'Power', 'Net-(D7-A)': 'Power',
    '/Power/VDC_IN': 'Supply', '/Power/VDC_FUSED': 'Supply', '/Power/VSYS': 'Supply',
    'Net-(J7-Pin_1)': 'Relay', 'Net-(J7-Pin_2)': 'Relay', 'Net-(J7-Pin_3)': 'Relay',
}

# ---- copper planes on the inner layers -----------------------------------------
# (net, layer, polygon)
SPLIT_X, SPLIT_Y = 47.0, 40.0
PLANES = [
    ('GND', 'In1.Cu', [(0, 0), (BOARD_W, 0), (BOARD_W, BOARD_H), (0, BOARD_H)]),
    ('+12V', 'In2.Cu', [(0, SPLIT_Y), (SPLIT_X, SPLIT_Y), (SPLIT_X, BOARD_H), (0, BOARD_H)]),
    ('+3V3', 'In2.Cu', [(0, 0), (BOARD_W, 0), (BOARD_W, BOARD_H), (SPLIT_X, BOARD_H),
                        (SPLIT_X, SPLIT_Y), (0, SPLIT_Y)]),
]

# ---- silkscreen legends above the terminal blocks -----------------------------
LEGENDS = [
    ('12V IN', 13.85, 68.9), ('MOTOR', 23.55, 68.9), ('AUX 12V', 33.25, 68.9),
    ('VALVE POS', 46.45, 68.9), ('FLOW', 61.4, 68.9), ('SALT', 76.35, 68.9),
    ('LEAK', 89.55, 68.9), ('RELAY', 101.0, 68.9),
]

# ---- simple 3D bodies for parts that have no model in the KiCad library -------
# ref: (file, size x/y/z mm, centre offset x/y mm in footprint coordinates, colour)
BODIES = {
    'K1': ('relay_g5q', (20.3, 10.3, 15.8), (8.89, -3.81), (0.12, 0.12, 0.13)),
    'J1': ('jack_pj102', (9.0, 14.4, 11.0), (0.0, 6.5), (0.10, 0.10, 0.10)),
    'F1': ('fuse_1812', (4.5, 3.2, 1.2), (0.0, 0.0), (0.16, 0.30, 0.20)),
    'U5': ('rtc_c7', (1.5, 3.2, 0.8), (0.0, 0.0), (0.75, 0.68, 0.45)),
    'D6': ('led_2020', (2.0, 2.0, 0.85), (0.0, 0.0), (0.93, 0.93, 0.88)),
}

# ---- extra areas the router must stay out of -----------------------------------
# (x0, y0, x1, y1, layers) with layer 0 = top, 1 = bottom.  They keep tracks from
# running around or under the antenna end of the module.
KEEP_OUT = [
    (64.4, 0.0, 79.3, 6.6, (0, 1)),
    (92.7, 0.0, 107.6, 6.6, (0, 1)),
    (79.3, 0.0, 92.7, 7.2, (1,)),
]
