"""Water softener controller - schematic definition.

All coordinates are in schematic grid units (1 unit = 2.54 mm).  Every sheet
is drawn block by block; nets that leave a block use global labels.
"""
from kisch import Library, Pin, Project, Sheet, Sym, U, r
from sexp import dump

NAME = 'water_softener'
TITLE = 'Water Softener Controller'
DESCRIPTION = 'ESP32-C6 metered water softener valve controller, 12 V DC'

S = Sym

# ---- footprints ------------------------------------------------------------
R0603 = 'Resistor_SMD:R_0603_1608Metric'
C0603 = 'Capacitor_SMD:C_0603_1608Metric'
C0805 = 'Capacitor_SMD:C_0805_2012Metric'
C1206 = 'Capacitor_SMD:C_1206_3216Metric'
SOD123 = 'Diode_SMD:D_SOD-123'
TB = 'Connector_Phoenix_MC:PhoenixContact_MC_1,5_%d-G-3.5_1x%02d_P3.50mm_Horizontal'
TB_MPN = {2: '1844210', 3: '1844223', 4: '1844236'}
TP_FP = 'TestPoint:TestPoint_Pad_D1.5mm'

ABOVE = {'Reference': (0, -4.6), 'Value': (0, -2.6)}
BELOW = {'Reference': (0, 2.6), 'Value': (0, 4.6)}
LEFT = {'Reference': (-2.2, -1.27, 'right'), 'Value': (-2.2, 1.27, 'right')}


def mpn(mfr, part, **extra):
    d = {'Manufacturer': mfr, 'MPN': part}
    d.update(extra)
    return d


class B:
    """Drawing helper working in grid units with automatic reference numbers."""
    counters = {}

    def __init__(self, sheet):
        self.s = sheet

    @staticmethod
    def mm(p):
        return p if isinstance(p, Pin) else (r(p[0] * U), r(p[1] * U))

    @staticmethod
    def ref(prefix):
        B.counters[prefix] = B.counters.get(prefix, 0) + 1
        return '%s%d' % (prefix, B.counters[prefix])

    def part(self, lib, prefix, x, y, **kw):
        return self.s.part(lib, self.ref(prefix), r(x * U), r(y * U), **kw)

    def w(self, *pts):
        return self.s.wire(*[self.mm(p) for p in pts])

    def gl(self, name, x, y, side='right', shape='bidirectional'):
        self.s.glabel(name, self.mm((x, y)), side, shape)

    def lb(self, name, x, y):
        self.s.label(name, self.mm((x, y)))

    def pw(self, name, x, y, rot=0):
        return self.s.power(name, self.mm((x, y)), rot)

    def gnd(self, x, y, rot=0):
        return self.pw('GND', x, y, rot)

    def nc(self, p):
        self.s.nc(self.mm(p))

    def tag(self, pin, name, n=2, shape='bidirectional'):
        return self.s.tag(pin, name, n, shape)

    def text(self, t, x, y, **kw):
        self.s.text(t, self.mm((x, y)), **kw)

    def block(self, x0, y0, x1, y1, title):
        self.s.block(self.mm((x0, y0)), self.mm((x1, y1)), title)

    # ---- passives ----------------------------------------------------------
    def R(self, x, y, val, rot=0, fp=R0603, rating='1% 0.1W', **kw):
        return self.part('Device:R', 'R', x, y, rot=rot, value=val, footprint=fp,
                         fields={'Rating': rating}, **kw)

    def C(self, x, y, val, rating, fp=C0603, rot=0, lib='Device:C', extra=None, **kw):
        f = {'Rating': rating}
        f.update(extra or {})
        return self.part(lib, 'C', x, y, rot=rot, value=val, footprint=fp, fields=f, **kw)

    def r_up(self, x, y, val, rail='+3V3', **kw):
        """Resistor from node (x, y) up to a supply rail."""
        p = self.R(x, y - 1.5, val, **kw)
        self.pw(rail, x, y - 3)
        return p

    def r_dn(self, x, y, val, **kw):
        p = self.R(x, y + 1.5, val, **kw)
        self.gnd(x, y + 3)
        return p

    def c_dn(self, x, y, val, rating, **kw):
        p = self.C(x, y + 1.5, val, rating, **kw)
        self.gnd(x, y + 3)
        return p

    def r_h(self, x, y, val, **kw):
        """Horizontal resistor, pin 1 at (x, y), pin 2 at (x + 3, y)."""
        return self.R(x + 1.5, y, val, rot=90, **kw)

    def tp(self, x, y, name, rot=0):
        return self.part('Connector:TestPoint', 'TP', x, y, rot=rot, value=name,
                         footprint=TP_FP, in_bom=False)

    def term(self, n, x, y, value, mirror=None):
        """Pluggable 3.5 mm terminal block header."""
        fpos = None
        if mirror:
            top = -3.6 if n == 2 else -5.6
            bot = {2: 6.4, 3: 5.6, 4: 8.2}[n]
            fpos = {'Reference': (0, top), 'Value': (0, bot)}
        return self.part('Connector:Screw_Terminal_01x%02d' % n, 'J', x, y, mirror=mirror,
                         value=value, footprint=TB % (n, n), fpos=fpos,
                         fields=mpn('Phoenix Contact', TB_MPN[n],
                                    Description='Pluggable terminal block header MC 1,5/%d-G-3,5' % n))


# ---------------------------------------------------------------------------
# project symbol library (parts missing from the stock KiCad libraries)
# ---------------------------------------------------------------------------
def _eff(hide=False):
    e = [S('effects'), [S('font'), [S('size'), 1.27, 1.27]]]
    return e


def _prop(name, value, x, y, hide=False, just=None):
    n = [S('property'), name, value, [S('at'), x, y, 0]]
    if hide:
        n.append([S('hide'), S('yes')])
    e = _eff()
    if just:
        e.append([S('justify'), S(just)])
    n.append(e)
    return n


def _pin(etype, x, y, angle, name, number):
    return [S('pin'), S(etype), S('line'), [S('at'), x, y, angle], [S('length'), 2.54],
            [S('name'), name, _eff()], [S('number'), number, _eff()]]


def project_symbol_lib():
    name = 'DRV8876PWP'
    left = [('EN/IN1', '1', 10.16, 'input'), ('PH/IN2', '2', 7.62, 'input'),
            ('nSLEEP', '3', 5.08, 'input'), ('nFAULT', '4', 2.54, 'open_collector'),
            ('PMODE', '16', -2.54, 'input'), ('IMODE', '7', -5.08, 'input'),
            ('VREF', '5', -7.62, 'input'), ('IPROPI', '6', -10.16, 'output')]
    right = [('VCP', '12', 10.16, 'passive'), ('CPH', '13', 5.08, 'passive'),
             ('CPL', '14', 2.54, 'passive'), ('OUT1', '8', -2.54, 'output'),
             ('OUT2', '10', -7.62, 'output')]
    pins = [_pin(t, -15.24, y, 0, n, num) for n, num, y, t in left]
    pins += [_pin(t, 15.24, y, 180, n, num) for n, num, y, t in right]
    pins.append(_pin('power_in', 0, 17.78, 270, 'VM', '11'))
    pins.append(_pin('power_in', -2.54, -17.78, 90, 'GND', '15'))
    pins.append(_pin('power_in', 0, -17.78, 90, 'PGND', '9'))
    pins.append(_pin('power_in', 2.54, -17.78, 90, 'PAD', '17'))
    sym = [S('symbol'), name,
           [S('exclude_from_sim'), S('no')], [S('in_bom'), S('yes')], [S('on_board'), S('yes')],
           _prop('Reference', 'U', -12.7, 16.51, just='left'),
           _prop('Value', name, 2.54, 16.51, just='left'),
           _prop('Footprint',
                 'Package_SO:HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask3x3mm_ThermalVias',
                 0, -22.86, hide=True),
           _prop('Datasheet', 'https://www.ti.com/lit/ds/symlink/drv8876.pdf', 0, 0, hide=True),
           _prop('Description',
                 'H-bridge motor driver, 4.5-37 V, 3.5 A peak, integrated current sense '
                 'and regulation, HTSSOP-16', 0, 0, hide=True),
           _prop('ki_keywords', 'brushed DC motor driver H-bridge current sense', 0, 0, hide=True),
           _prop('ki_fp_filters', 'HTSSOP*4.4x5mm*P0.65mm*', 0, 0, hide=True),
           [S('symbol'), name + '_0_1',
            [S('rectangle'), [S('start'), -12.7, 15.24], [S('end'), 12.7, -15.24],
             [S('stroke'), [S('width'), 0.254], [S('type'), S('default')]],
             [S('fill'), [S('type'), S('background')]]]],
           [S('symbol'), name + '_1_1'] + pins,
           [S('embedded_fonts'), S('no')]]
    return [S('kicad_symbol_lib'), [S('version'), 20251024],
            [S('generator'), 'kicad_symbol_editor'], [S('generator_version'), '10.0'], sym]


# ---------------------------------------------------------------------------
# sheet 2 - power
# ---------------------------------------------------------------------------
def sheet_power():
    s = Sheet('Power', 'power.kicad_sch', TITLE + ' - power', page='2')
    b = B(s)

    # ---- 12 V input and protection ----------------------------------------
    b.block(8, 14, 66, 50, '12 V INPUT AND PROTECTION')
    j1 = b.part('Connector:Barrel_Jack_Switch', 'J', 16, 30, value='12V DC IN',
                footprint='Connector_BarrelJack:BarrelJack_CUI_PJ-102AH_Horizontal',
                fields=mpn('CUI Devices', 'PJ-102AH',
                           Description='DC barrel jack 5.5 x 2.1 mm, centre positive'))
    j2 = b.term(2, 16, 40, '12V IN (ALT)', mirror='y')
    f1 = b.part('Device:Polyfuse', 'F', 26, 29, rot=90, value='1.5A / 24V',
                footprint='Fuse:Fuse_1812_4532Metric',
                fields=mpn('Bourns', 'MF-MSMF150/24X-2', Rating='1.5 A hold, 3 A trip, 24 V'))
    b.w(j1['1'], f1['1'])
    b.w(j2['1'], (22, 40), (22, 29))
    b.w(j1['2'], (21, 31), (21, 33)); b.gnd(21, 33)
    b.w(j1['3'], (21, 30), (21, 31))
    b.w(j2['2'], (21, 41), (21, 43)); b.gnd(21, 43)
    b.lb('VDC_IN', 19.5, 29)
    q1 = b.part('Transistor_FET:DMP3099L', 'Q', 38, 30, rot=90, value='DMP3099L',
                fpos={'Reference': (0, -8.4), 'Value': (0, -6.2)},
                fields=mpn('Diodes Inc.', 'DMP3099L-7', Rating='-30 V, 65 mOhm, Vgs +/-20 V'))
    b.w(f1['2'], q1['D'])
    b.lb('VDC_FUSED', 28, 29)
    b.part('Diode:SMAJ16CA', 'D', 31, 30.5, rot=90, value='SMAJ16CA',
           fields=mpn('Littelfuse', 'SMAJ16CA', Rating='16 V standoff, 400 W, bidirectional'))
    b.gnd(31, 32)
    b.w(q1['S'], (63, 29))
    b.part('Device:D_Zener', 'D', 43, 30.5, rot=270, value='BZT52C10', footprint=SOD123,
           fields=mpn('Diodes Inc.', 'BZT52C10-7-F', Rating='10 V 5%'))
    b.w((43, 32), (43, 34), (38, 34))
    b.w(q1['G'], (38, 34))
    b.r_dn(38, 34, '100k')
    b.C(50, 30.5, '220uF', '25 V aluminium, 105 C', fp='Capacitor_SMD:CP_Elec_8x10',
        lib='Device:C_Polarized', extra=mpn('Panasonic', 'EEE-FK1E221P'))
    b.gnd(50, 32)
    b.c_dn(55, 29, '100nF', '50 V X7R')
    b.pw('PWR_FLAG', 59, 29)
    b.pw('+12V', 63, 29)
    b.text('12 V DC nominal (9 to 16 V), 2 A supply, centre positive.', 10, 46)
    b.text('Q1 blocks reverse polarity; D2 clamps its gate; D1 clamps surges to 26 V.', 10, 48)

    # ---- logic supply ------------------------------------------------------
    b.block(68, 14, 150, 50, 'LOGIC SUPPLY: DIODE-OR + 3.3 V BUCK')
    b.pw('+12V', 72, 29)
    d3 = b.part('Diode:SS14', 'D', 75.5, 29, rot=180, value='SS14',
                fields=mpn('Vishay', 'SS14-E3/61T', Rating='40 V 1 A Schottky'))
    b.w((72, 29), d3['A'])
    b.pw('VBUS', 72, 36)
    d4 = b.part('Diode:SS14', 'D', 75.5, 36, rot=180, value='SS14',
                fields=mpn('Vishay', 'SS14-E3/61T', Rating='40 V 1 A Schottky'))
    b.w((72, 36), d4['A'])
    b.w(d4['K'], (79, 36), (79, 29))
    u1 = b.part('Regulator_Switching:AP63203WU', 'U', 100, 30, value='AP63203WU',
                fields=mpn('Diodes Inc.', 'AP63203WU-7'))
    b.w(d3['K'], u1['IN'])
    b.pw('PWR_FLAG', 81, 29)
    b.lb('VSYS', 81.5, 29)
    b.C(85, 30.5, '470uF', '25 V aluminium, 105 C', fp='Capacitor_SMD:CP_Elec_10x10',
        lib='Device:C_Polarized', extra=mpn('Panasonic', 'EEE-FK1E471P'))
    b.gnd(85, 32)
    b.c_dn(90, 29, '10uF', '25 V X7R', fp=C1206)
    b.w(u1['EN'], (94, 31), (94, 29))
    b.w(u1['GND'], (100, 34)); b.gnd(100, 34)
    l1 = b.part('Device:L', 'L', 111.5, 26, rot=90, value='4.7uH',
                footprint='Inductor_SMD:L_Coilcraft_XAL4030-XXX', fpos=ABOVE,
                fields=mpn('Coilcraft', 'XAL4030-472MEC', Rating='4.7 uH, Isat 4.5 A, 44 mOhm'))
    b.w(u1['SW'], (106, 29), (106, 26), l1['1'])
    b.C(108, 27.5, '100nF', '50 V X7R')
    b.w((108, 29), (108, 30), u1['BST'])
    b.w(l1['2'], (140, 26))
    b.w(u1['FB'], (118, 31), (118, 26))
    b.c_dn(122, 26, '22uF', '10 V X5R', fp=C0805)
    b.c_dn(126, 26, '22uF', '10 V X5R', fp=C0805)
    b.pw('PWR_FLAG', 130, 26)
    b.R(135, 27.5, '1k')
    b.part('Device:LED', 'D', 135, 30.5, rot=90, value='GREEN',
           footprint='LED_SMD:LED_0603_1608Metric',
           fields=mpn('Wurth Elektronik', '150060GS75000', Description='Power indicator LED'))
    b.gnd(135, 32)
    b.pw('+3V3', 140, 26)
    b.text('VSYS = 12 V rail or USB VBUS, whichever is present. USB alone runs the logic for', 70, 42)
    b.text('service and programming; motor, relay and sensor rails need the 12 V input.', 70, 44)
    b.text('The 470 uF on VSYS holds the MCU up long enough to save state when 12 V drops.', 70, 46)
    b.text('3.3 V buck: 1.1 MHz, 2 A, ripple current about 0.46 A at 12 V in.', 70, 48)

    # ---- 5 V sensor rail ---------------------------------------------------
    b.block(8, 54, 52, 84, '5 V SENSOR SUPPLY')
    b.pw('+12V', 14, 64)
    u2 = b.part('Regulator_Linear:L78L05_SOT89', 'U', 24, 64, value='L78L05',
                fields=mpn('STMicroelectronics', 'L78L05ABUTR'))
    b.w((14, 64), u2['IN'])
    b.c_dn(17, 64, '1uF', '50 V X7R', fp=C0805)
    b.w(u2['GND'], (24, 68)); b.gnd(24, 68)
    b.w(u2['OUT'], (37, 64))
    b.c_dn(32, 64, '1uF', '50 V X7R', fp=C0805)
    b.pw('+5V', 37, 64)
    b.text('+5V feeds the flow meter, valve position', 10, 76)
    b.text('sensors and salt sensor only (100 mA,', 10, 78)
    b.text('short-circuit protected by U2).', 10, 80)

    # ---- supply monitor ----------------------------------------------------
    b.block(56, 54, 96, 84, 'SUPPLY MONITOR')
    b.r_up(62, 65, '100k', rail='+12V')
    b.r_dn(62, 65, '15k')
    b.w((62, 65), (74, 65))
    b.c_dn(69, 65, '100nF', '50 V X7R')
    b.gl('VIN_SENSE', 74, 65, 'right', 'output')
    b.text('VIN_SENSE = 0.130 x V(+12V)', 58, 76)
    b.text('12 V -> 1.57 V, 16 V -> 2.09 V', 58, 78)
    b.text('Used for power-fail warning.', 58, 80)

    # ---- test points and mechanical ---------------------------------------
    b.block(100, 54, 150, 84, 'TEST POINTS AND MOUNTING')
    b.tp(106, 64, '+12V', rot=180); b.pw('+12V', 106, 64)
    b.tp(113, 64, 'VSYS', rot=180); b.w((110, 64), (113, 64)); b.lb('VSYS', 110, 64)
    b.tp(119, 64, '+3V3', rot=180); b.pw('+3V3', 119, 64)
    b.tp(125, 64, '+5V', rot=180); b.pw('+5V', 125, 64)
    b.tp(131, 64, 'GND'); b.gnd(131, 64)
    b.tp(137, 64, 'GND'); b.gnd(137, 64)
    b.w((137, 64), (141, 64)); b.pw('PWR_FLAG', 141, 64)
    for i in range(4):
        b.part('Mechanical:MountingHole', 'H', 107 + i * 10, 77, value='M3',
               footprint='MountingHole:MountingHole_3.2mm_M3', in_bom=False)
    return s


# ---------------------------------------------------------------------------
# sheet 3 - MCU, USB, RTC, user interface
# ---------------------------------------------------------------------------
MCU_NETS = {
    'EN': ('EN', 'input'), 'IO0': ('VIN_SENSE', 'input'), 'IO1': ('MOTOR_ISENSE', 'input'),
    'IO2': ('LEAK_SENSE', 'input'), 'IO3': ('FLOW_PULSE', 'input'), 'IO4': ('BTN_UP', 'input'),
    'IO5': ('RELAY_DRV', 'output'), 'IO6': ('I2C_SDA', 'bidirectional'),
    'IO7': ('I2C_SCL', 'output'), 'IO8': ('LED_DIN', 'output'), 'IO9': ('BTN_SET', 'input'),
    'TXD0': ('U0TXD', 'bidirectional'), 'RXD0': ('SALT_RX', 'input'),
    'IO12': ('USB_D_N', 'bidirectional'), 'IO13': ('USB_D_P', 'bidirectional'),
    'IO14': ('BUZZER_DRV', 'output'), 'IO15': ('AUX_DRV', 'output'),
    'IO18': ('MOTOR_IN1', 'output'), 'IO19': ('MOTOR_IN2', 'output'),
    'IO20': ('MOTOR_nSLEEP', 'output'), 'IO21': ('MOTOR_nFAULT', 'input'),
    'IO22': ('POS_HOME', 'input'), 'IO23': ('POS_ENC', 'input'),
}


def sheet_mcu():
    s = Sheet('MCU', 'mcu.kicad_sch', TITLE + ' - MCU, USB, RTC and user interface', page='3')
    b = B(s)

    # ---- module ------------------------------------------------------------
    b.block(66, 36, 102, 72, 'ESP32-C6 MODULE')
    u = b.part('RF_Module:ESP32-C6-MINI-1', 'U', 84, 56, value='ESP32-C6-MINI-1-N4',
               fpos={'Reference': (-12.7, -24.4, 'left'), 'Value': (2.4, 24.6, 'left')},
               fields=mpn('Espressif', 'ESP32-C6-MINI-1-N4'))
    for pin, (net, shape) in MCU_NETS.items():
        b.tag(u[pin], net, 2, shape)
    b.w(u['3V3'], (84, 41)); b.pw('+3V3', 84, 41)
    b.w((84, 42), (95, 42))
    b.c_dn(90, 42, '10uF', '10 V X5R', fp=C0805)
    b.c_dn(95, 42, '100nF', '50 V X7R')
    b.w(u['GND'], (84, 67)); b.gnd(84, 67)

    # ---- reset -------------------------------------------------------------
    b.block(10, 16, 44, 40, 'RESET')
    b.r_up(18, 26, '10k')
    b.c_dn(18, 26, '1uF', '16 V X7R')
    sw = b.part('Switch:SW_Push', 'SW', 26, 26, value='RESET',
                footprint='Button_Switch_SMD:SW_SPST_B3U-1000P',
                fields=mpn('Omron', 'B3U-1000P'))
    b.w((14, 26), sw['1'])
    b.w(sw['2'], (30, 26), (30, 29)); b.gnd(30, 29)
    b.gl('EN', 14, 26, 'left', 'output')
    b.text('10k / 1uF power-on reset delay', 12, 36)
    b.text('per Espressif design guide.', 12, 38)

    # ---- buttons -----------------------------------------------------------
    b.block(10, 44, 62, 74, 'USER BUTTONS')
    tact = dict(footprint='Button_Switch_THT:SW_PUSH_6mm', fields=mpn('Omron', 'B3F-1000'))
    b.r_up(18, 53, '10k')
    sw = b.part('Switch:SW_Push', 'SW', 26, 53, value='SET / BOOT', **tact)
    b.w((14, 53), sw['1'])
    b.w(sw['2'], (30, 53), (30, 55)); b.gnd(30, 55)
    b.gl('BTN_SET', 14, 53, 'left', 'output')
    b.r_up(18, 65, '10k')
    tact = dict(footprint='Button_Switch_THT:SW_PUSH_6mm', fields=mpn('Omron', 'B3F-1000'))
    sw = b.part('Switch:SW_Push', 'SW', 26, 65, value='UP', **tact)
    b.w((14, 65), sw['1'])
    b.w(sw['2'], (30, 65), (30, 67)); b.gnd(30, 67)
    b.gl('BTN_UP', 14, 65, 'left', 'output')
    b.gl('U0TXD', 40, 53, 'left', 'bidirectional')
    b.tp(41, 53, 'U0TXD')
    rs = b.r_h(42, 53, '1k')
    b.w((40, 53), rs['1'])
    b.r_up(48, 53, '10k')
    tact = dict(footprint='Button_Switch_THT:SW_PUSH_6mm', fields=mpn('Omron', 'B3F-1000'))
    sw = b.part('Switch:SW_Push', 'SW', 54, 53, value='DOWN', **tact)
    b.w(rs['2'], sw['1'])
    b.w(sw['2'], (58, 53), (58, 55)); b.gnd(58, 55)
    b.text('SET doubles as the ESP32 BOOT strap (hold while', 12, 70)
    b.text('resetting). DOWN shares GPIO16 (ROM boot log on TP).', 12, 72)

    # ---- USB ---------------------------------------------------------------
    b.block(10, 78, 73, 110, 'USB-C: SERVICE AND PROGRAMMING')
    j = b.part('Connector:USB_C_Receptacle_USB2.0_16P', 'J', 22, 90, value='USB-C',
               footprint='Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal',
               fields=mpn('GCT', 'USB4105-GF-A'))
    b.w(j['A4'], (68, 84))
    b.pw('PWR_FLAG', 47, 84)
    b.r_dn(62, 84, '10k')
    b.pw('VBUS', 68, 84)
    b.w(j['A5'], (30, 86)); b.lb('USB_CC1', 30, 86)
    b.w(j['B5'], (30, 87))
    b.w((30, 87), (31, 87)); b.lb('USB_CC2', 31, 87)
    b.w(j['A7'], (30, 89)); b.w(j['B7'], (30, 90)); b.w((30, 89), (30, 90))
    b.w(j['A6'], (31, 91)); b.w(j['B6'], (31, 92)); b.w((31, 91), (31, 92))
    tv = b.part('Power_Protection:USBLC6-2SC6', 'U', 40, 98, value='USBLC6-2SC6',
                fpos={'Reference': (3.2, 10.0, 'left'), 'Value': (3.2, 12.0, 'left')},
                fields=mpn('STMicroelectronics', 'USBLC6-2SC6'))
    rn = b.r_h(49, 89, '22R', fpos=ABOVE)
    rp = b.r_h(49, 92, '22R', fpos=BELOW)
    b.w((30, 89), rn['1'])
    b.w((31, 92), rp['1'])
    b.w(tv['1'], (36, 98), (36, 89))
    b.w(tv['6'], (44, 98), (44, 89))
    b.w(tv['3'], (35, 99), (35, 92))
    b.w(tv['4'], (45, 99), (45, 92))
    b.pw('VBUS', 40, 96)
    b.gnd(40, 101)
    b.w(rn['2'], (54, 89)); b.gl('USB_D_N', 54, 89, 'right')
    b.w(rp['2'], (54, 92)); b.gl('USB_D_P', 54, 92, 'right')
    b.nc(j['A8']); b.nc(j['B8'])
    b.w(j['A1'], (22, 100)); b.w(j['SH'], (19, 100), (22, 100)); b.gnd(22, 100)
    b.w((55, 97), (59, 97)); b.lb('USB_CC1', 55, 97); b.r_dn(59, 97, '5.1k')
    b.w((63, 97), (67, 97)); b.lb('USB_CC2', 63, 97); b.r_dn(67, 97, '5.1k')
    b.text('Native USB Serial/JTAG on GPIO12/13.', 44, 106)
    b.text('VBUS feeds VSYS through a diode only.', 44, 108)

    # ---- RTC ---------------------------------------------------------------
    b.block(106, 16, 150, 44, 'REAL-TIME CLOCK WITH BACKUP')
    rtc = b.part('Timer_RTC:RV-3028-C7', 'U', 128, 32, value='RV-3028-C7',
                 fields=mpn('Micro Crystal', 'RV-3028-C7 32.768kHz 1ppm TA QC'))
    b.tag(rtc['SCL'], 'I2C_SCL', 2, 'input')
    b.tag(rtc['SDA'], 'I2C_SDA', 2, 'bidirectional')
    b.w(rtc['EVI'], (121, 33), (121, 35)); b.gnd(121, 35)
    b.w(rtc['VSS'], (128, 37)); b.gnd(128, 37)
    b.w(rtc['VDD'], (127, 22)); b.pw('+3V3', 127, 22)
    b.w((127, 24), (116, 24))
    b.c_dn(116, 24, '100nF', '50 V X7R')
    b.w(rtc['VBACKUP'], (128, 26), (139, 26))
    b.pw('PWR_FLAG', 133, 26)
    b.C(139, 27.5, '11mF', '3.3 V EDLC', fp='Capacitor_SMD:C_1210_3225Metric',
        lib='Device:C_Polarized', extra=mpn('Seiko Instruments', 'CPH3225A'))
    b.gnd(139, 29)
    b.nc(rtc['~{INT}']); b.nc(rtc['CLKOUT'])
    b.text('Backup cap is trickle-charged by the RTC (enable', 108, 41)
    b.text('in EEPROM 37h). Keeps time for days without power.', 108, 43)

    # ---- I2C ---------------------------------------------------------------
    b.block(106, 48, 150, 78, 'I2C BUS: DISPLAY AND EXPANSION')
    b.r_up(114, 56, '2.2k')
    b.w((114, 56), (114, 58), (112, 58)); b.gl('I2C_SDA', 112, 58, 'left')
    b.r_up(120, 56, '2.2k')
    b.w((120, 56), (120, 58), (122, 58)); b.gl('I2C_SCL', 122, 58, 'right')
    j = b.part('Connector_Generic:Conn_01x04', 'J', 144, 56, value='OLED',
               footprint='Connector_PinSocket_2.54mm:PinSocket_1x04_P2.54mm_Vertical',
               fields=mpn('Generic', '1x04 2.54 mm socket',
                          Description='Socket for 0.96 / 1.3 inch I2C OLED module'))
    b.w(j['1'], (140, 55)); b.gnd(140, 55, rot=270)
    b.w(j['2'], (140, 56)); b.pw('+3V3', 140, 56, rot=90)
    b.tag(j['3'], 'I2C_SCL', 2); b.tag(j['4'], 'I2C_SDA', 2)
    j = b.part('Connector_Generic_MountingPin:Conn_01x04_MountingPin', 'J', 144, 68, value='QWIIC',
               fpos={'Value': (4.6, 8.6, 'left')},
               footprint='Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal',
               fields=mpn('JST', 'SM04B-SRSS-TB'))
    b.w(j['1'], (140, 67)); b.gnd(140, 67, rot=270)
    b.w(j['2'], (140, 68)); b.pw('+3V3', 140, 68, rot=90)
    b.tag(j['3'], 'I2C_SDA', 2); b.tag(j['4'], 'I2C_SCL', 2)
    b.w(j['MP'], (144, 73)); b.gnd(144, 73)
    b.text('J4 pin order GND / 3V3 / SCL / SDA - check the', 108, 74)
    b.text('OLED module before fitting (some swap GND and VCC).', 108, 76)

    # ---- status LED --------------------------------------------------------
    b.block(106, 82, 150, 98, 'STATUS LED')
    led = b.part('LED:WS2812B-2020', 'D', 126, 90, value='WS2812B-2020',
                 fpos={'Reference': (2.2, 7.2, 'left'), 'Value': (2.2, 9.2, 'left')},
                 fields=mpn('Worldsemi', 'WS2812B-2020 (V6)'))
    b.w(led['VDD'], (126, 85)); b.pw('+3V3', 126, 85)
    b.w((126, 86), (133, 86)); b.c_dn(133, 86, '100nF', '50 V X7R')
    b.w(led['VSS'], (126, 94)); b.gnd(126, 94)
    b.nc(led['DOUT'])
    b.w(led['DIN'], (114, 90))
    b.r_up(118, 90, '10k')
    b.gl('LED_DIN', 114, 90, 'left', 'input')

    # ---- buzzer ------------------------------------------------------------
    b.block(75, 84, 104, 110, 'ALARM BUZZER')
    q = b.part('Transistor_FET:BSS138', 'Q', 94, 101, value='BSS138',
               fields=mpn('onsemi', 'BSS138'))
    b.gl('BUZZER_DRV', 83, 101, 'left', 'input')
    rg = b.r_h(84, 101, '100R', fpos=ABOVE)
    b.w((83, 101), rg['1'])
    b.w(rg['2'], q['G'])
    b.r_dn(89, 101, '100k')
    b.gnd(95, 103)
    ls = b.part('Device:Buzzer', 'LS', 100, 95, value='PS1240',
                footprint='Buzzer_Beeper:Buzzer_TDK_PS1240P02BT_D12.2mm_H6.5mm',
                fields=mpn('TDK', 'PS1240P02BT', Description='Piezo sounder 4 kHz, 30 Vp-p max'))
    b.pw('+12V', 95, 92)
    b.w((95, 92), (95, 94))
    b.R(95, 95.5, '2.2k', fpos=LEFT)
    b.w((95, 94), ls['1'])
    b.w(ls['2'], (97, 96), (97, 97), (95, 97))
    b.w((95, 97), q['D'])
    return s


# ---------------------------------------------------------------------------
# sheet 4 - valve motor drive and outputs
# ---------------------------------------------------------------------------
def sheet_drive():
    s = Sheet('Valve drive', 'drive.kicad_sch', TITLE + ' - valve motor drive and outputs', page='4')
    b = B(s)

    b.block(10, 16, 112, 70, 'VALVE MOTOR DRIVE')
    u = b.part('water_softener:DRV8876PWP', 'U', 70, 44, value='DRV8876PWP',
               fields=mpn('Texas Instruments', 'DRV8876PWPR'))
    b.tag(u['EN/IN1'], 'MOTOR_IN1', 2, 'input')
    b.tag(u['PH/IN2'], 'MOTOR_IN2', 2, 'input')
    b.tag(u['nSLEEP'], 'MOTOR_nSLEEP', 2, 'input')
    b.tag(u['nFAULT'], 'MOTOR_nFAULT', 2, 'output')
    b.w(u['PMODE'], (62, 45)); b.pw('+3V3', 62, 45, rot=90)
    b.w(u['IMODE'], (62, 46)); b.gnd(62, 46, rot=270)
    # current-limit reference
    b.w(u['VREF'], (42, 47))
    b.r_up(42, 47, '10k')
    b.r_dn(42, 47, '30.1k')
    b.c_dn(47, 47, '100nF', '50 V X7R')
    b.lb('VREF', 51, 47)
    # current sense
    b.w(u['IPROPI'], (62, 48), (62, 54), (55, 54))
    b.r_dn(58, 54, '2.49k')
    rf = b.r_h(52, 54, '10k', fpos=ABOVE)
    b.w(rf['1'], (46, 54))
    b.c_dn(49, 54, '100nF', '50 V X7R')
    b.gl('MOTOR_ISENSE', 46, 54, 'left', 'output')
    # supply and charge pump
    b.w(u['VM'], (70, 29)); b.pw('+12V', 70, 29)
    b.w((70, 31), (86, 31))
    b.c_dn(76, 31, '100nF', '50 V X7R')
    b.c_dn(81, 31, '10uF', '25 V X7R', fp=C1206)
    b.C(86, 32.5, '100nF', '50 V X7R')
    b.w((86, 34), (86, 40), u['VCP'])
    b.C(82, 42.5, '22nF', '50 V X7R')
    b.w(u['CPH'], (80, 42), (80, 41), (82, 41))
    b.w(u['CPL'], (80, 43), (80, 44), (82, 44))
    j = b.term(2, 102, 45, 'VALVE MOTOR')
    b.w(u['OUT1'], j['1'])
    b.w(u['OUT2'], (98, 47), (98, 46), j['2'])
    b.lb('MOTOR_A', 88, 45); b.lb('MOTOR_B', 88, 47)
    b.w(u['GND'], (69, 52)); b.w(u['PGND'], (70, 52)); b.w(u['PAD'], (71, 52))
    b.w((69, 52), (71, 52)); b.gnd(70, 52)
    # pull resistors on the control lines
    b.gl('MOTOR_nSLEEP', 44, 26, 'left', 'input')
    b.w((44, 26), (48, 26)); b.r_dn(48, 26, '10k')
    b.r_up(48, 38, '10k')
    b.w((48, 38), (44, 38)); b.gl('MOTOR_nFAULT', 44, 38, 'left', 'output')
    b.text('PMODE high: IN1/IN2 PWM control (00 coast, 10 forward, 01 reverse, 11 brake).', 12, 60)
    b.text('IMODE low: fixed off-time current regulation, automatic retry after over-current.', 12, 62)
    b.text('I(trip) = VREF / (R(IPROPI) x 1000 uA/A) = 2.48 V / 2.49 k = 1.0 A.', 12, 64)
    b.text('MOTOR_ISENSE = 2.49 V per amp of motor current (stall and jam detection).', 12, 66)
    b.text('nSLEEP is pulled low so the bridge stays off until firmware enables it.', 12, 68)

    # ---- relay -------------------------------------------------------------
    b.block(10, 74, 74, 110, 'AUX RELAY (DRY CONTACT)')
    k = b.part('Relay:G5Q-1', 'K', 42, 88, value='G5Q-14 DC12',
               fields=mpn('Omron', 'G5Q-14 DC12', Rating='12 V coil 33 mA, SPDT'))
    b.pw('+12V', 40, 80)
    b.w((40, 80), k['5'])
    d = b.part('Diode:1N4148W', 'D', 35, 88, rot=270, value='1N4148W',
               fpos=LEFT, fields=mpn('Diodes Inc.', '1N4148W-7-F'))
    b.w(d['K'], (35, 83), (40, 83))
    b.w(d['A'], (35, 93), (40, 93))
    q = b.part('Transistor_FET:BSS138', 'Q', 39, 97, value='BSS138', fields=mpn('onsemi', 'BSS138'))
    b.w(k['1'], q['D'])
    b.gnd(40, 99)
    b.gl('RELAY_DRV', 22, 97, 'left', 'input')
    rg = b.r_h(24, 97, '100R', fpos=ABOVE)
    b.w((22, 97), rg['1'])
    b.w(rg['2'], q['G'])
    b.r_dn(32, 97, '10k')
    j = b.term(3, 62, 86, 'RELAY')
    b.w(k['4'], (43, 82), (52, 82), (52, 85), j['1'])
    b.w(k['3'], (45, 84), (50, 84), (50, 86), j['2'])
    b.w(k['2'], (44, 92), (56, 92), (56, 87), j['3'])
    b.text('1 = NC', 65, 85.4); b.text('2 = NO', 65, 86.4); b.text('3 = COM', 65, 87.4)
    b.text('Contacts for SELV circuits only (30 V, 3 A max):', 44, 104)
    b.text('alarm, pump interlock or bypass valve.', 44, 106)

    # ---- switched 12 V output ---------------------------------------------
    b.block(78, 74, 150, 98, 'SWITCHED 12 V OUTPUT (LOW SIDE)')
    j = b.term(2, 140, 84, 'AUX 12V OUT')
    b.pw('+12V', 128, 79)
    b.w((128, 79), (128, 84), j['1'])
    b.part('Diode:SS14', 'D', 128, 85.5, rot=270, value='SS14', fpos=LEFT,
           fields=mpn('Vishay', 'SS14-E3/61T', Rating='40 V 1 A Schottky'))
    q = b.part('Transistor_FET:AO3400A', 'Q', 119, 89, value='AO3400A',
               fields=mpn('Alpha & Omega', 'AO3400A'))
    b.w(j['2'], (134, 85), (134, 87), q['D'])
    b.gnd(120, 91)
    b.gl('AUX_DRV', 98, 89, 'left', 'input')
    rg = b.r_h(100, 89, '100R', fpos=ABOVE)
    b.w((98, 89), rg['1'])
    b.w(rg['2'], q['G'])
    b.r_dn(110, 89, '10k')
    b.text('J8: 1 = +12V, 2 = switched to GND', 126, 92)
    b.text('Load 0.5 A max: solenoid or motorised shut-off valve.', 80, 96)
    return s


# ---------------------------------------------------------------------------
# sheet 5 - sensor inputs
# ---------------------------------------------------------------------------
def input_chain(b, x, y, jname, net, pull='2.2k', cap='10nF'):
    """Connector node -> pass FET (5 V tolerant) -> pull-up -> RC -> MCU label."""
    b.lb(jname, x + 0.5, y)
    q = b.part('Transistor_FET:BSS138', 'Q', x + 6, y - 1, rot=270, mirror='y', value='BSS138',
               fpos={'Reference': (-3.4, -4.8, 'right'), 'Value': (-3.4, -2.8, 'right')},
               fields=mpn('onsemi', 'BSS138'))
    b.w((x, y), q['D'])
    b.pw('+3V3', x + 6, y - 3)
    rs = b.r_h(x + 13, y, '1k')
    b.w(q['S'], rs['1'])
    b.r_up(x + 10.5, y, pull)
    b.w(rs['2'], (x + 21, y))
    b.c_dn(x + 18, y, cap, '50 V X7R')
    b.gl(net, x + 21, y, 'right', 'output')


def sheet_sensors():
    s = Sheet('Sensors', 'sensors.kicad_sch', TITLE + ' - sensor inputs', page='5')
    b = B(s)

    b.block(10, 16, 84, 44, 'VALVE POSITION INPUTS')
    j = b.term(4, 16, 28, 'VALVE POS', mirror='y')
    b.w(j['1'], (20, 27), (20, 24)); b.pw('+5V', 20, 24)
    b.w(j['4'], (20, 30), (20, 33)); b.gnd(20, 33)
    b.w(j['2'], (25, 28), (25, 25), (30, 25))
    b.w(j['3'], (23, 29), (23, 36), (30, 36))
    input_chain(b, 30, 25, 'HOME_J', 'POS_HOME')
    input_chain(b, 30, 36, 'ENC_J', 'POS_ENC')
    b.text('1 +5V   2 HOME   3 ENC   4 GND', 62, 22)
    b.text('Cam switch, hall or optical sensor', 62, 24)
    b.text('pulling the line to GND.', 62, 26)

    b.block(10, 48, 84, 66, 'FLOW METER INPUT')
    j = b.term(3, 16, 57, 'FLOW', mirror='y')
    b.w(j['1'], (20, 56), (20, 53)); b.pw('+5V', 20, 53)
    b.w(j['3'], (20, 58), (20, 60)); b.gnd(20, 60)
    b.w(j['2'], (30, 57))
    input_chain(b, 30, 57, 'FLOW_J', 'FLOW_PULSE')
    b.text('1 +5V   2 PULSE   3 GND', 62, 52)
    b.text('Hall turbine (open collector) or reed.', 62, 54)

    b.block(10, 70, 84, 90, 'SALT LEVEL SENSOR (UART)')
    j = b.term(4, 16, 80, 'SALT UART', mirror='y')
    b.w(j['1'], (20, 79), (20, 76)); b.pw('+5V', 20, 76)
    b.w(j['4'], (20, 82), (20, 84)); b.gnd(20, 84)
    b.w(j['2'], (24, 80), (24, 78), (30, 78))
    b.w(j['3'], (26, 81)); b.lb('SALT_AUX_J', 26, 81)
    input_chain(b, 30, 78, 'SALT_J', 'SALT_RX', pull='10k', cap='1nF')
    b.text('1 +5V   2 DATA (sensor TX)', 62, 74)
    b.text('3 AUX (sensor RX, n/c)   4 GND', 62, 76)
    b.text('Ultrasonic level sensor, 9600 baud.', 62, 86)

    b.block(10, 94, 84, 112, 'LEAK PROBE INPUT')
    j = b.term(2, 16, 102, 'LEAK', mirror='y')
    b.w(j['2'], (20, 103), (20, 105)); b.gnd(20, 105)
    rs = b.r_h(34, 102, '100k')
    b.w(j['1'], rs['1'])
    b.lb('LEAK_J', 20.5, 102)
    b.r_up(29, 102, '470k')
    b.w(rs['2'], (46, 102))
    b.c_dn(41, 102, '100nF', '50 V X7R')
    b.gl('LEAK_SENSE', 46, 102, 'right', 'output')
    b.text('Two-electrode floor probe. Dry reads 3.3 V;', 54, 100)
    b.text('water across the probe pulls the node low.', 54, 102)

    b.block(88, 16, 150, 60, 'ESD PROTECTION (AT THE TERMINALS)')
    u = b.part('Power_Protection:USBLC6-4SC6', 'U', 114, 30, value='USBLC6-4SC6',
               fields=mpn('STMicroelectronics', 'USBLC6-4SC6'))
    for pin, name in (('1', 'HOME_J'), ('3', 'ENC_J'), ('4', 'FLOW_J')):
        p = u[pin]
        b.w(p, (102, p.y / U)); b.lb(name, 102, p.y / U)
    b.w(u['6'], (107, 32)); b.pw('+5V', 107, 32, rot=90)
    b.nc(u['5']); b.gnd(114, 34)
    u = b.part('Power_Protection:USBLC6-4SC6', 'U', 114, 48, value='USBLC6-4SC6',
               fields=mpn('STMicroelectronics', 'USBLC6-4SC6'))
    for pin, name in (('1', 'SALT_J'), ('3', 'SALT_AUX_J'), ('4', 'LEAK_J')):
        p = u[pin]
        b.w(p, (102, p.y / U)); b.lb(name, 102, p.y / U)
    b.w(u['6'], (107, 50)); b.pw('+5V', 107, 50, rot=90)
    b.nc(u['5']); b.gnd(114, 52)
    b.text('Pin 5 is left open so the arrays clamp to their internal', 122, 28)
    b.text('TVS (about 6 V) instead of a supply rail: sensor', 122, 30)
    b.text('outputs may swing to 5 V without back-feeding +5V.', 122, 32)
    b.text('One channel of each array clamps the +5V sensor rail.', 122, 46)
    b.text('First array sits at J9/J10, second at J11/J12.', 122, 48)

    b.block(88, 64, 150, 96, 'INPUT STAGE NOTES')
    notes = [
        'Each digital input passes through a BSS138 with its gate at 3.3 V: the',
        'MCU only ever sees its own 3.3 V pull-up, so 5 V push-pull or',
        'open-collector sensors and a +5V-to-signal wiring fault are harmless.',
        'A low at the terminal turns the FET on and is passed through unchanged.',
        'Pull-ups give 1.5 mA wetting current for switch contacts.',
        'RC filters: 16 kHz (position, flow), 160 kHz (UART), 16 Hz (leak).',
    ]
    for i, t in enumerate(notes):
        b.text(t, 90, 70 + i * 2)
    return s


# ---------------------------------------------------------------------------
# root sheet
# ---------------------------------------------------------------------------
def sheet_root(children):
    s = Sheet('Root', NAME + '.kicad_sch', TITLE, paper='A4', page='1')
    b = B(s)
    b.text(TITLE, 10, 14, size=3.5, bold=True)
    b.text(DESCRIPTION, 10, 17, size=1.8)
    boxes = [(10, 24), (36, 24), (62, 24), (88, 24)]
    blurbs = {
        'Power': ['12 V input, fuse, TVS,', 'reverse protection,', '3.3 V buck, 5 V sensor rail'],
        'MCU': ['ESP32-C6 module, USB-C,', 'RTC + backup, OLED, buttons,', 'status LED, buzzer'],
        'Valve drive': ['DRV8876 H-bridge with', 'current sense, aux relay,', 'switched 12 V output'],
        'Sensors': ['Valve position, flow meter,', 'salt level, leak probe,', 'ESD protection'],
    }
    out = []
    for (x, y), child in zip(boxes, children):
        out.append((child, (r(x * U), r(y * U)), (r(22 * U), r(12 * U))))
        for i, line in enumerate(blurbs[child.name]):
            b.text(line, x + 0.8, y + 4 + i * 2)
    lines = [
        'Rails:  +12V protected input rail (motor, relay, switched output)   VSYS diode-OR of +12V and USB VBUS (buck input)',
        '        +3V3 logic   +5V sensor supply   VBUS USB service port',
        'Signals between sheets use global labels. Field wiring lands on 3.5 mm pluggable terminal blocks.',
        'Regeneration sequence, metering and connectivity (Wi-Fi 6 / BLE / Thread) are firmware functions of the ESP32-C6.',
    ]
    for i, t in enumerate(lines):
        b.text(t, 10, 44 + i * 2.2)
    return s, out


def build(directory):
    Library.paths[NAME] = directory + '/' + NAME + '.kicad_sym'
    with open(Library.paths[NAME], 'w', encoding='utf-8') as fh:
        fh.write(dump(project_symbol_lib()) + '\n')
    B.counters = {}
    Sheet.pwr_count = 0
    prj = Project(NAME, directory, DESCRIPTION)
    children = [sheet_power(), sheet_mcu(), sheet_drive(), sheet_sensors()]
    root, placed = sheet_root(children)
    prj.set_root(root)
    for child, at, size in placed:
        prj.add_child(child, at, size)
    return prj
