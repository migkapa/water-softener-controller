// Written by scripts/enclosure.py from scripts/pcb_layout.py.  Do not edit.
pcb_w = 120.0;
pcb_h = 80.0;
holes = [[4, 4], [116, 4], [4, 76], [116, 76]];
// DOWN, UP, SET: centres of the tact switches
buttons = [[42.75, 38.25], [52.75, 38.25], [62.75, 38.25]];
led = [58.5, 12.0];
buzzer = [10.5, 14.0];
reset = [70.0, 13.5];
// OLED module: centre of its 4-pin socket and of the visible display area
oled_hdr = [40.0, 6.0];
oled_view = [40.0, 16.5];
usb_y = 30.0;
jack_y = 50.0;
// terminal blocks: x of pin 1, ways, name, pin labels
terminals = [
    [12.1, 2, "12V IN", ["+", "-"]],
    [21.8, 2, "MOTOR", ["1", "2"]],
    [31.5, 2, "AUX 12V", ["+", "SW"]],
    [41.2, 4, "VALVE POS", ["5V", "HM", "EN", "G"]],
    [57.9, 3, "FLOW", ["5V", "P", "G"]],
    [71.1, 4, "SALT", ["5V", "D", "A", "G"]],
    [87.8, 2, "LEAK", ["P", "G"]],
    [97.5, 3, "RELAY", ["NC", "NO", "C"]],
];
