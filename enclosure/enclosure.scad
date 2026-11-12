// Water softener controller: enclosure and assembly.
//
// Coordinates follow the board.  x runs to the right and y runs DOWN from the
// board's top-left corner (the helpers below flip it), z is up from the top
// surface of the board.  Everything is in millimetres.
//
//   openscad -D 'part="cover"' -o cover.stl enclosure.scad
//
// board.scad is written by scripts/enclosure.py from the board layout, so the
// openings follow the parts when the board changes.

include <board.scad>

part = "assembly";
$fn = 72;
eps = 0.01;

// ---- main dimensions ----------------------------------------------------------
pcb_t     = 1.6;     // board thickness
gap       = 1.0;     // board edge to the inside of the wall
wall      = 2.4;
floor_t   = 2.0;
standoff  = 5.0;     // underside of the board to the floor
ceil_z    = 17.8;    // inside of the front face, above the board
skin      = 2.4;     // front face thickness
bay       = 32.0;    // wiring bay below the board edge
r_out     = 5.0;     // outside corner radius
chamfer   = 1.2;     // front edge
tongue_h  = 2.0;     // lap joint between base and cover
tongue_t  = 1.1;
fit       = 0.15;    // clearance between mating parts

xi0 = -gap;            xi1 = pcb_w + gap;          // inside faces
yi0 = -gap;            yi1 = pcb_h + bay;
xo0 = xi0 - wall;      xo1 = xi1 + wall;           // outside faces
yo0 = yi0 - wall;      yo1 = yi1 + wall;
z_floor  = -pcb_t - standoff;                      // inside of the floor
z_bottom = z_floor - floor_t;                      // rear face
z_front  = ceil_z + skin;                          // front face

// ---- wiring door ----------------------------------------------------------------
door_t   = 1.8;
door_x0  = 7;    door_x1 = pcb_w - 7;
door_y0  = 62;   door_y1 = yi1 - 1;
open_x0  = 9;    open_x1 = pcb_w - 9;      // clear opening
open_y1  = door_y1 - 2;
part_y0  = 68.4; part_y1 = 70.2;           // partition between electronics and bay
part_z   = tongue_h + 0.2;                 // its lower edge
frame_t  = 1.0;                            // backing behind the door seat
z_seat   = z_front - door_t;               // door seat and label strip
tab_x    = [30, pcb_w - 30];               // door tabs (centres), top edge
tab_w    = 10;
dscrew   = [pcb_w / 2, door_y1 - 4.5];     // door screw
cable_x  = [12, 24, 36, 48, 72, 84, 96, 108];
cable_w  = 7;

// ---- front face features ---------------------------------------------------------
win      = [24.5, 13.5];       // display opening
lens     = [30, 19, 1.5];      // smoked window, glued into a recess
lens_c   = oled_view;          // centre of the visible display area
btn_d    = 7.0;                // button shaft
btn_top  = 1.0;                // how far a button stands proud
sw_top   = 4.3;                // top of the tact switch plunger above the board
pipe_d   = 3.0;                // light pipe
led_top  = 0.9;
post_d   = 7.5;
insert_d = 4.0;                // hole for an M3 heat-set insert
insert_h = 7.5;

// ---- side openings ------------------------------------------------------------
usb_w = 13;  usb_h = 7;  usb_zc = 1.65;    // takes the plug overmould
jack_w = 10.4; jack_h = 11.7;

// ---- rear ---------------------------------------------------------------------------
keyhole  = [pcb_w / 2, 17];    // wide end of the keyhole slot
wall_scr = [[25, pcb_h + 20], [pcb_w - 25, pcb_h + 20]];

font_b = "Arial:style=Bold";
font_r = "Arial";

// ---- helpers --------------------------------------------------------------------
module at(p) translate([p[0], -p[1], 0]) children();
module brect(x0, y0, x1, y1, r = 0) {
    translate([x0, -y1])
        if (r > 0) offset(r = r) offset(delta = -r) square([x1 - x0, y1 - y0]);
        else square([x1 - x0, y1 - y0]);
}
module bbox3(x0, y0, x1, y1, z0, z1, r = 0)
    translate([0, 0, z0]) linear_extrude(z1 - z0) brect(x0, y0, x1, y1, r);
module outline(d = 0)
    offset(r = r_out - d) offset(delta = -r_out) brect(xo0, yo0, xo1, yo1);
module txt(s, size, font = font_b, spacing = 1)
    text(s, size = size, font = font, halign = "center", valign = "center", spacing = spacing);
module tri(up, s = 3.4)
    rotate(up ? 0 : 180) polygon([[-s / 2, -s * 0.4], [s / 2, -s * 0.4], [0, s * 0.45]]);

// ---- openings shared by base and cover ---------------------------------------------
module side_openings() {
    // USB-C, right wall
    translate([xi1 - 0.5, -usb_y, usb_zc]) rotate([90, 0, 90]) linear_extrude(wall + 2)
        offset(r = 2.5) square([usb_w - 5, usb_h - 5], center = true);
    // 12 V jack, left wall
    translate([xo0 - 1, -jack_y, 0]) rotate([90, 0, 90]) linear_extrude(wall + 1.5)
        hull() {
            translate([-jack_w / 2, -eps]) square([jack_w, 1]);
            for (s = [-1, 1]) translate([s * (jack_w / 2 - 1.2), jack_h - 1.2]) circle(1.2);
        }
    // cable entries, bottom wall
    for (cx = cable_x) translate([cx, -(yi1 - 0.5), 0]) rotate([90, 0, 0]) linear_extrude(wall + 2)
        hull() {
            translate([-cable_w / 2, -eps]) square([cable_w, 1]);
            translate([0, 3]) circle(d = cable_w);
        }
}

// ---- base -----------------------------------------------------------------------
module base() {
    kx = keyhole[0]; ky = keyhole[1];
    difference() {
        union() {
            difference() {
                translate([0, 0, z_bottom]) linear_extrude(-z_bottom) outline(0);
                translate([0, 0, z_floor]) linear_extrude(-z_floor + 1) outline(wall);
            }
            // tongue of the lap joint
            translate([0, 0, -eps]) linear_extrude(tongue_h + eps)
                difference() { outline(wall - tongue_t); outline(wall); }
            // board bosses and the supports under the buttons
            for (h = holes) at(h) translate([0, 0, z_floor - eps]) cylinder(d = 8.5, h = standoff + eps);
            for (b = buttons) at(b) translate([0, 0, z_floor - eps]) cylinder(d = 4, h = standoff + eps);
            // pocket that takes the head of the hanging screw
            bbox3(kx - 6.7, ky - 11.2, kx + 6.7, ky + 6.7, z_floor - eps, z_floor + 4.6, 1.5);
            // reinforcement around the two fixing holes in the wiring bay
            for (w = wall_scr) at(w) translate([0, 0, z_floor - eps]) cylinder(d = 11, h = 1.2);
        }
        // board screws: clearance hole and a counterbore for the head
        for (h = holes) at(h) {
            translate([0, 0, z_bottom - 1]) cylinder(d = 3.4, h = 20);
            translate([0, 0, z_bottom - 1]) cylinder(d = 6.4, h = 4);
        }
        // keyhole and its pocket
        bbox3(kx - 5.5, ky - 10, kx + 5.5, ky + 5.5, z_floor - 0.5, z_floor + 3.6, 1);
        translate([0, 0, z_bottom - 1]) linear_extrude(floor_t + 2) {
            at(keyhole) circle(d = 9.5);
            hull() { at(keyhole) circle(d = 4.6); at([kx, ky - 7]) circle(d = 4.6); }
        }
        for (w = wall_scr) at(w) translate([0, 0, z_bottom - 1]) cylinder(d = 4.6, h = 10);
        side_openings();
        // rating text on the rear
        translate([0, 0, z_bottom - eps]) linear_extrude(0.3) mirror([1, 0, 0]) translate([-pcb_w, 0]) {
            translate([pcb_w / 2, -46]) txt("12 V DC   1.5 A MAX", 3.2);
            translate([pcb_w / 2, -53]) txt("LOW VOLTAGE WIRING ONLY", 2.4, font_r);
            translate([pcb_w / 2, -58.5]) txt("INDOOR USE", 2.4, font_r);
        }
    }
}

// ---- cover --------------------------------------------------------------------------
module front_legend_2d() {
    translate([buttons[0][0], -buttons[0][1] - 7.4]) tri(false);
    translate([buttons[1][0], -buttons[1][1] - 7.4]) tri(true);
    translate([buttons[2][0], -buttons[2][1] - 7.4]) txt("SET", 2.3);
    translate([reset[0], -reset[1] - 3.3]) txt("RESET", 1.4);
    translate([96, -14.5]) txt("WATER SOFTENER", 3.3);
    translate([96, -20.5]) txt("CONTROLLER", 2.3, font_r, 1.25);
}
module strip_legend_2d() {
    for (t = terminals) {
        translate([t[0] + (t[1] - 1) * 1.75, -64.0]) txt(t[2], 1.5);
        for (i = [0 : t[1] - 1]) translate([t[0] + 3.5 * i, -66.9]) txt(t[3][i], 1.15, font_r);
    }
}

module cover() {
    lx = lens_c[0]; ly = lens_c[1];
    difference() {
        union() {
            difference() {
                union() {
                    // shell with a chamfered front edge
                    difference() {
                        hull() {
                            linear_extrude(z_front - chamfer) outline(0);
                            translate([0, 0, z_front - eps]) linear_extrude(eps) outline(chamfer);
                        }
                        translate([0, 0, -1]) linear_extrude(ceil_z + 1) outline(wall);
                    }
                    // everything that hangs from the front face
                    intersection() {
                        translate([0, 0, -eps]) linear_extrude(ceil_z + 0.5) outline(0.6);
                        union() {
                            bbox3(xi0 - 1, door_y0 - 3.5, xi1 + 1, yi1 + 1, ceil_z - frame_t, ceil_z + eps);
                            bbox3(xi0 - 1, part_y0, xi1 + 1, part_y1, part_z, ceil_z + eps);
                            for (h = holes) at(h) cylinder(d = post_d, h = ceil_z + eps);
                            // light shield round the display
                            bbox3(lx - win[0] / 2 - 2.2, ly - win[1] / 2 - 2.2, lx + win[0] / 2 + 2.2,
                                  ly + win[1] / 2 + 2.2, 14.4, ceil_z + eps, 1.5);
                            for (b = buttons) at(b) translate([0, 0, 11.8]) cylinder(d = 10, h = ceil_z - 11.8 + eps);
                            at(led) translate([0, 0, 9.8]) cylinder(d = 6, h = ceil_z - 9.8 + eps);
                            at(reset) translate([0, 0, 3.0]) cylinder(d = 4.4, h = ceil_z - 3.0 + eps);
                        }
                    }
                }
                // wiring bay opening, the seat for the door and pockets for its tabs
                bbox3(open_x0, part_y1, open_x1, open_y1, ceil_z - frame_t - 1, z_front + 1, 1.5);
                bbox3(door_x0, door_y0, door_x1, door_y1, z_seat, z_front + 1, 2);
                for (tx = tab_x)
                    bbox3(tx - tab_w / 2 - 0.4, door_y0 - 3, tx + tab_w / 2 + 0.4, door_y0 + 1, z_seat - 0.1, z_seat + 1.2);
            }
            // block for the door screw
            bbox3(dscrew[0] - 5, dscrew[1] - 4.5, dscrew[0] + 5, yi1 + eps, 9.0, z_seat);
        }
        // nail slot for lifting the door
        bbox3(pcb_w - 34, door_y1 - 0.5, pcb_w - 22, door_y1 + 1.5, z_front - 1.2, z_front + 1, 0.7);
        // groove for the tongue of the base
        translate([0, 0, -1]) linear_extrude(tongue_h + 0.2 + 1) outline(wall - tongue_t - fit);
        // display window and the recess for the lens
        bbox3(lx - win[0] / 2, ly - win[1] / 2, lx + win[0] / 2, ly + win[1] / 2, ceil_z - 5, z_front + 1, 1);
        bbox3(lx - lens[0] / 2 - fit, ly - lens[1] / 2 - fit, lx + lens[0] / 2 + fit, ly + lens[1] / 2 + fit,
              z_front - lens[2] - 0.1, z_front + 1, 2 + fit);
        // buttons, light pipe, reset pin hole, sounder
        for (b = buttons) at(b) translate([0, 0, ceil_z - 7]) cylinder(d = btn_d + 0.4, h = 12);
        at(led) translate([0, 0, ceil_z - 9]) cylinder(d = pipe_d + 0.4, h = 14);
        at(reset) { translate([0, 0, 2]) cylinder(d = 2.2, h = ceil_z - 2 + 0.6);
                    translate([0, 0, ceil_z]) cylinder(d = 1.8, h = skin + 1); }
        at(buzzer) translate([0, 0, ceil_z - 1]) {
            cylinder(d = 1.6, h = skin + 2);
            for (a = [0 : 60 : 359]) rotate(a) translate([3.2, 0, 0]) cylinder(d = 1.6, h = skin + 2);
        }
        // threaded inserts
        for (h = holes) at(h) translate([0, 0, -eps]) cylinder(d = insert_d, h = insert_h);
        at(dscrew) translate([0, 0, z_seat - 7]) cylinder(d = insert_d, h = 8);
        side_openings();
        // legends: shallow engraving, filled with ink in the renders
        translate([0, 0, z_front - 0.3]) linear_extrude(1) front_legend_2d();
        translate([0, 0, z_seat - 0.3]) linear_extrude(1) strip_legend_2d();
    }
}

// ---- small parts -----------------------------------------------------------------
module door() {
    difference() {
        union() {
            bbox3(door_x0 + fit, door_y0 + fit, door_x1 - fit, door_y1 - fit, z_seat, z_front, 2 - fit);
            for (tx = tab_x) bbox3(tx - tab_w / 2, door_y0 - 2.6, tx + tab_w / 2, door_y0 + 2, z_seat, z_seat + 1.0);
        }
        at(dscrew) {
            translate([0, 0, z_seat - 1]) cylinder(d = 3.4, h = 5);
            translate([0, 0, z_front - 1.6]) cylinder(d1 = 3.4, d2 = 6.6, h = 1.6 + eps);
        }
    }
}

module lens_part()
    bbox3(lens_c[0] - lens[0] / 2, lens_c[1] - lens[1] / 2, lens_c[0] + lens[0] / 2, lens_c[1] + lens[1] / 2,
          z_front - lens[2] - 0.05, z_front - 0.05, 2);

view = [22.6, 11.7];             // clear area of the lens; the rest is printed black on the back
module lens_mask() translate([0, 0, z_front - lens[2] - 0.05]) linear_extrude(0.06) difference() {
    brect(lens_c[0] - lens[0] / 2, lens_c[1] - lens[1] / 2, lens_c[0] + lens[0] / 2, lens_c[1] + lens[1] / 2, 2);
    brect(lens_c[0] - view[0] / 2, lens_c[1] - view[1] / 2, lens_c[0] + view[0] / 2, lens_c[1] + view[1] / 2, 0.8);
}

module button() {       // one button, standing on the switch plunger at z = sw_top
    translate([0, 0, sw_top]) cylinder(d = 4.6, h = 9.5 - sw_top + eps);
    translate([0, 0, 9.5]) cylinder(d = 9.0, h = 2.0);
    translate([0, 0, 11.5 - eps]) cylinder(d = btn_d, h = z_front + btn_top - 11.5 - 0.6);
    translate([0, 0, z_front + btn_top - 0.6 - eps]) cylinder(d1 = btn_d, d2 = btn_d - 1.2, h = 0.6);
}
module buttons_placed() for (b = buttons) at(b) button();

module lightpipe() at(led) {
    translate([0, 0, led_top + 0.7]) cylinder(d = pipe_d, h = z_front - led_top - 0.7);
    translate([0, 0, 8.6]) cylinder(d = 4.6, h = 1.0);
}

// ---- stand-ins for bought parts (renders and the clearance check only) -----------
oled_x0 = oled_hdr[0] - 13.65;  oled_y0 = oled_hdr[1] - 2.0;     // module outline, 27.3 x 27.8
oled_z  = 8.5 + 2.54;                                            // underside of the module board
module oled_board() difference() {
    bbox3(oled_x0, oled_y0, oled_x0 + 27.3, oled_y0 + 27.8, oled_z, oled_z + 1.2, 1);
    for (dx = [2, 25.3], dy = [2, 25.8]) at([oled_x0 + dx, oled_y0 + dy]) translate([0, 0, oled_z - 1]) cylinder(d = 2, h = 4);
}
module oled_header() bbox3(oled_hdr[0] - 5.08, oled_hdr[1] - 1.27, oled_hdr[0] + 5.08, oled_hdr[1] + 1.27, 8.5, oled_z);
module oled_pins() for (i = [-1.5 : 1.5]) at([oled_hdr[0] + 2.54 * i, oled_hdr[1]]) translate([-0.32, -0.32, 2.5]) cube([0.64, 0.64, oled_z + 1.7 - 2.5]);
module oled_glass() bbox3(oled_x0 + 0.3, oled_y0 + 5.0, oled_x0 + 27.0, oled_y0 + 24.3, oled_z + 1.2, oled_z + 2.7);
module oled_active() bbox3(oled_view[0] - 10.87, oled_view[1] - 5.43, oled_view[0] + 10.87, oled_view[1] + 5.43, oled_z + 2.7, oled_z + 2.72);
module display_on() translate([0, 0, oled_z + 2.72]) linear_extrude(0.03) {
    translate([oled_view[0] - 10.2, -oled_view[1] + 3.6]) text("IN SERVICE", size = 1.5, font = font_b, valign = "center");
    translate([oled_view[0] - 10.2, -oled_view[1] - 0.2]) text("1840 L", size = 3.6, font = font_b, valign = "center");
    // capacity bar
    translate([oled_view[0] - 10.2, -oled_view[1] - 4.6]) {
        difference() { square([20.4, 1.7]); translate([0.25, 0.25]) square([19.9, 1.2]); }
        translate([0.5, 0.5]) square([13.5, 0.7]);
    }
}

plug_len = 9.2;      // how far a wired plug stands out of its header
module plug_bodies() for (t = terminals) {
    x0 = t[0] - 1.75 - 0.4; x1 = t[0] + (t[1] - 1) * 3.5 + 1.75 + 0.4;
    difference() {
        union() {
            bbox3(x0, pcb_h + 0.3, x1, pcb_h + plug_len, -2.2, 8.4, 0.4);
            bbox3(x0 + 0.6, pcb_h - 5, x1 - 0.6, pcb_h + 0.4, 1.4, 6.0);
        }
        for (i = [0 : t[1] - 1]) {
            at([t[0] + 3.5 * i, pcb_h + 4.4]) translate([0, 0, 7.4]) cylinder(d = 2.9, h = 2);
            bbox3(t[0] + 3.5 * i - 1.25, pcb_h + plug_len - 3, t[0] + 3.5 * i + 1.25, pcb_h + plug_len + 1, 0.2, 2.8);
        }
    }
}
module plug_metal() for (t = terminals) for (i = [0 : t[1] - 1])
    at([t[0] + 3.5 * i, pcb_h + 4.4]) difference() {
        translate([0, 0, 6.6]) cylinder(d = 2.7, h = 1.2);
        translate([-0.25, -2, 7.4]) cube([0.5, 4, 1]);
    }

module rear_screws() for (h = holes) at(h) {
    translate([0, 0, z_bottom + 0.6]) cylinder(d = 5.6, h = 2.4);
    translate([0, 0, z_bottom + 3 - eps]) cylinder(d = 2.9, h = 12 - eps);
}
module door_screw() at(dscrew) {
    translate([0, 0, z_front - 1.6]) cylinder(d1 = 3.0, d2 = 6.0, h = 1.55);
    translate([0, 0, z_front - 9.5]) cylinder(d = 2.9, h = 8);
}
module sounder() at(buzzer) difference() {
    cylinder(d = 12.2, h = 6.5);
    translate([0, 0, 5]) cylinder(d = 2.4, h = 3);
}
module ink_front() translate([0, 0, z_front - 0.3]) linear_extrude(0.31) front_legend_2d();
module ink_door() translate([0, 0, z_front - 0.01]) linear_extrude(0.03)
    translate([(door_x0 + door_x1) / 2, -(door_y0 + 7)]) txt("TERMINALS", 2.2, font_r, 1.3);
module ink_strip() translate([0, 0, z_seat - 0.3]) linear_extrude(0.31) strip_legend_2d();

// ---- part selection -------------------------------------------------------------------
if (part == "base") base();
else if (part == "cover") cover();
else if (part == "door") door();
else if (part == "lens") lens_part();
else if (part == "button") button();
else if (part == "buttons") buttons_placed();
else if (part == "lightpipe") lightpipe();
else if (part == "oled_board") oled_board();
else if (part == "oled_header") oled_header();
else if (part == "oled_pins") oled_pins();
else if (part == "oled_glass") oled_glass();
else if (part == "oled_active") oled_active();
else if (part == "display_on") display_on();
else if (part == "plug_bodies") plug_bodies();
else if (part == "plug_metal") plug_metal();
else if (part == "rear_screws") rear_screws();
else if (part == "door_screw") door_screw();
else if (part == "sounder") sounder();
else if (part == "ink_front") ink_front();
else if (part == "ink_strip") ink_strip();
else if (part == "ink_door") ink_door();
else if (part == "lens_mask") lens_mask();
else {
    color([0.80, 0.81, 0.82]) base();
    color([0.90, 0.91, 0.92]) cover();
    color([0.90, 0.91, 0.92]) door();
    color([0.1, 0.1, 0.12, 0.6]) lens_part();
    color([0.35, 0.45, 0.55]) buttons_placed();
    color([1, 1, 1, 0.7]) lightpipe();
    color([0.1, 0.25, 0.6]) oled_board();
    color([0.05, 0.05, 0.05]) { oled_header(); oled_glass(); }
    color([0.1, 0.5, 0.2]) plug_bodies();
    color([0.2, 0.2, 0.2]) { ink_front(); ink_strip(); }
    color([0.1, 0.35, 0.15]) translate([0, -pcb_h, -pcb_t]) cube([pcb_w, pcb_h, pcb_t]);
}
