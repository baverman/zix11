const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;
const c = @cImport({
    @cInclude("cairo/cairo.h");
});

const width: u16 = 640;
const height: u16 = 360;
const bytes_per_pixel: usize = 4;
const max_putimage_bytes: usize = 256 * 1024;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    const root_geometry = try conn.request(x.GetGeometry, .{
        .drawable = @enumFromInt(@intFromEnum(conn.root_window)),
    });
    const depth = root_geometry.depth;

    const window = try conn.allocId(x.Window);
    const pixmap = try conn.allocId(x.Pixmap);
    const gc = try conn.allocId(x.Gcontext);

    try conn.request(x.CreateWindow, .{
        .depth = depth,
        .wid = window,
        .parent = conn.root_window,
        .x = 160,
        .y = 90,
        .width = width,
        .height = height,
        .border_width = 0,
        .class = .CopyFromParent,
        .visual = 0,
        .value_list = .{
            .background_pixel = 0x000b1018,
            .event_mask = x.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });
    defer conn.request(x.DestroyWindow, .{ .window = window }) catch {};

    try conn.request(x.CreatePixmap, .{
        .depth = depth,
        .pid = pixmap,
        .drawable = @enumFromInt(@intFromEnum(window)),
        .width = width,
        .height = height,
    });
    defer conn.request(x.FreePixmap, .{ .pixmap = pixmap }) catch {};

    try conn.request(x.CreateGC, .{
        .cid = gc,
        .drawable = @enumFromInt(@intFromEnum(pixmap)),
        .value_list = .{},
    });
    defer conn.request(x.FreeGC, .{ .gc = gc }) catch {};

    const pixels = try init.gpa.alignedAlloc(u8, .of(u32), @as(usize, width) * @as(usize, height) * bytes_per_pixel);
    defer init.gpa.free(pixels);

    const surface = c.cairo_image_surface_create_for_data(
        pixels.ptr,
        c.CAIRO_FORMAT_ARGB32,
        width,
        height,
        width * 4,
    ) orelse return error.CairoSurfaceCreateFailed;
    defer c.cairo_surface_destroy(surface);

    const cr = c.cairo_create(surface) orelse return error.CairoCreateFailed;
    defer c.cairo_destroy(cr);

    var phase: f64 = 0.0;
    drawScene(cr, phase);

    try conn.request(x.MapWindow, .{ .window = window });
    try present(&conn, window, pixmap, gc, depth, surface, pixels);

    while (true) {
        if (try conn.pollEventTimeout(16)) |event| {
            switch (event) {
                .Expose => |ev| {
                    if (ev.window == window and ev.count == 0) {
                        drawScene(cr, phase);
                        try present(&conn, window, pixmap, gc, depth, surface, pixels);
                    }
                },
                .ButtonPress => |ev| {
                    if (ev.event == window) return;
                },
                else => {},
            }
            continue;
        }

        phase += 0.085;
        drawScene(cr, phase);
        try present(&conn, window, pixmap, gc, depth, surface, pixels);
    }
}

fn present(
    conn: *zix11.Connection,
    window: x.Window,
    pixmap: x.Pixmap,
    gc: x.Gcontext,
    depth: u8,
    surface: *c.cairo_surface_t,
    pixels: []const u8,
) !void {
    c.cairo_surface_flush(surface);
    const stride = @as(usize, width) * bytes_per_pixel;
    const max_rows = @max(@as(usize, 1), max_putimage_bytes / stride);
    var y: usize = 0;
    while (y < height) {
        const row_count = @min(max_rows, @as(usize, height) - y);
        const start = y * stride;
        const end = start + row_count * stride;
        try conn.request(x.PutImage, .{
            .format = .ZPixmap,
            .drawable = @enumFromInt(@intFromEnum(pixmap)),
            .gc = gc,
            .width = width,
            .height = @intCast(row_count),
            .dst_x = 0,
            .dst_y = @intCast(y),
            .left_pad = 0,
            .depth = depth,
            .data = pixels[start..end],
        });
        y += row_count;
    }

    try conn.request(x.CopyArea, .{
        .src_drawable = @enumFromInt(@intFromEnum(pixmap)),
        .dst_drawable = @enumFromInt(@intFromEnum(window)),
        .gc = gc,
        .src_x = 0,
        .src_y = 0,
        .dst_x = 0,
        .dst_y = 0,
        .width = width,
        .height = height,
    });
}

fn drawScene(cr: *c.cairo_t, phase: f64) void {
    const bg = c.cairo_pattern_create_linear(0, 0, 0, height);
    defer c.cairo_pattern_destroy(bg);
    c.cairo_pattern_add_color_stop_rgb(bg, 0.0, 0.04, 0.08, 0.14);
    c.cairo_pattern_add_color_stop_rgb(bg, 0.48, 0.12, 0.08, 0.22);
    c.cairo_pattern_add_color_stop_rgb(bg, 1.0, 0.38, 0.16, 0.20);
    _ = c.cairo_set_source(cr, bg);
    c.cairo_rectangle(cr, 0, 0, width, height);
    _ = c.cairo_fill(cr);

    const wave = std.math.sin(phase);
    const drift = std.math.cos(phase * 0.78);
    const sway = std.math.sin(phase * 0.52);
    const pulse = 0.5 + 0.5 * std.math.sin(phase * 1.8);

    drawOrb(cr, 96 + 56 * drift, 90 + 34 * sway, 150 + 10 * pulse, 0.20, 0.72, 0.88, 0.42);
    drawOrb(cr, 548 + 42 * wave, 86 + 32 * drift, 124 + 8 * pulse, 0.98, 0.76, 0.22, 0.34);
    drawOrb(cr, 504 - 46 * sway, 294 + 28 * wave, 168 + 12 * pulse, 0.96, 0.34, 0.40, 0.28);
    drawOrb(cr, 278 + 62 * wave, 324 + 22 * drift, 106 + 8 * pulse, 0.52, 0.84, 0.62, 0.22);

    drawPulseRing(cr, 420 + 38 * drift, 158 + 20 * wave, 44 + 22 * pulse, 0.96, 0.82, 0.26, 0.22);
    drawPulseRing(cr, 204 - 32 * wave, 272 + 18 * sway, 32 + 18 * pulse, 0.28, 0.82, 0.96, 0.18);

    drawGlowStripe(cr, phase);
    drawCard(cr, 92, 84, 456, 192, 26, phase);

    c.cairo_select_font_face(cr, "Sans", c.CAIRO_FONT_SLANT_NORMAL, c.CAIRO_FONT_WEIGHT_BOLD);
    c.cairo_set_font_size(cr, 34);
    c.cairo_set_source_rgba(cr, 0.97, 0.98, 0.99, 1.0);
    c.cairo_move_to(cr, 132, 166);
    _ = c.cairo_show_text(cr, "zix11 + cairo");

    c.cairo_select_font_face(cr, "Sans", c.CAIRO_FONT_SLANT_NORMAL, c.CAIRO_FONT_WEIGHT_NORMAL);
    c.cairo_set_font_size(cr, 17);
    c.cairo_set_source_rgba(cr, 0.88, 0.90, 0.94, 0.92);
    c.cairo_move_to(cr, 136, 204);
    _ = c.cairo_show_text(cr, "animated software surface");
    c.cairo_move_to(cr, 136, 230);
    _ = c.cairo_show_text(cr, "cairo raster + pixmap-backed zix11 blit");
}

fn drawGlowStripe(cr: *c.cairo_t, phase: f64) void {
    const center = 0.5 + 0.34 * std.math.sin(phase * 0.62);
    const beam = c.cairo_pattern_create_linear(0, 0, width, height);
    defer c.cairo_pattern_destroy(beam);
    c.cairo_pattern_add_color_stop_rgba(beam, 0.0, 0.0, 0.0, 0.0, 0.0);
    c.cairo_pattern_add_color_stop_rgba(beam, center - 0.12, 0.0, 0.0, 0.0, 0.0);
    c.cairo_pattern_add_color_stop_rgba(beam, center - 0.02, 0.48, 0.78, 1.0, 0.04);
    c.cairo_pattern_add_color_stop_rgba(beam, center, 0.92, 0.96, 1.0, 0.13);
    c.cairo_pattern_add_color_stop_rgba(beam, center + 0.02, 1.0, 0.78, 0.42, 0.06);
    c.cairo_pattern_add_color_stop_rgba(beam, center + 0.12, 0.0, 0.0, 0.0, 0.0);
    c.cairo_pattern_add_color_stop_rgba(beam, 1.0, 0.0, 0.0, 0.0, 0.0);
    _ = c.cairo_set_source(cr, beam);
    c.cairo_rectangle(cr, 0, 0, width, height);
    _ = c.cairo_fill(cr);
}

fn drawOrb(cr: *c.cairo_t, cx: f64, cy: f64, radius: f64, r: f64, g: f64, b: f64, alpha: f64) void {
    const orb = c.cairo_pattern_create_radial(cx, cy, radius * 0.1, cx, cy, radius);
    defer c.cairo_pattern_destroy(orb);
    c.cairo_pattern_add_color_stop_rgba(orb, 0.0, r, g, b, alpha);
    c.cairo_pattern_add_color_stop_rgba(orb, 1.0, r, g, b, 0.0);
    _ = c.cairo_set_source(cr, orb);
    c.cairo_arc(cr, cx, cy, radius, 0, std.math.pi * 2.0);
    _ = c.cairo_fill(cr);
}

fn drawPulseRing(cr: *c.cairo_t, cx: f64, cy: f64, radius: f64, r: f64, g: f64, b: f64, alpha: f64) void {
    c.cairo_new_path(cr);
    c.cairo_arc(cr, cx, cy, radius, 0, std.math.pi * 2.0);
    c.cairo_set_line_width(cr, 3.0);
    c.cairo_set_source_rgba(cr, r, g, b, alpha);
    _ = c.cairo_stroke(cr);
}

fn drawCard(cr: *c.cairo_t, x0: f64, y0: f64, w: f64, h: f64, radius: f64, phase: f64) void {
    const pulse = 0.5 + 0.5 * std.math.sin(phase * 1.8);
    const shadow = c.cairo_pattern_create_linear(x0, y0, x0, y0 + h);
    defer c.cairo_pattern_destroy(shadow);
    c.cairo_pattern_add_color_stop_rgba(shadow, 0.0, 0.02, 0.02, 0.04, 0.74);
    c.cairo_pattern_add_color_stop_rgba(shadow, 1.0, 0.08, 0.08, 0.10, 0.58);

    roundedRect(cr, x0 + 10, y0 + 14, w, h, radius);
    _ = c.cairo_set_source(cr, shadow);
    _ = c.cairo_fill(cr);

    const panel = c.cairo_pattern_create_linear(x0, y0, x0, y0 + h);
    defer c.cairo_pattern_destroy(panel);
    c.cairo_pattern_add_color_stop_rgba(panel, 0.0, 0.11, 0.13, 0.19, 0.86);
    c.cairo_pattern_add_color_stop_rgba(panel, 1.0, 0.07, 0.09, 0.13, 0.82);

    roundedRect(cr, x0, y0, w, h, radius);
    _ = c.cairo_set_source(cr, panel);
    _ = c.cairo_fill_preserve(cr);

    c.cairo_set_line_width(cr, 1.2 + 1.0 * pulse);
    c.cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.12 + 0.14 * pulse);
    _ = c.cairo_stroke(cr);

    const accent = c.cairo_pattern_create_linear(x0, y0, x0 + w, y0 + h);
    defer c.cairo_pattern_destroy(accent);
    c.cairo_pattern_add_color_stop_rgba(accent, 0.0, 0.30, 0.70, 0.94, 0.00);
    c.cairo_pattern_add_color_stop_rgba(accent, 0.35, 0.30, 0.70, 0.94, 0.08 + 0.08 * pulse);
    c.cairo_pattern_add_color_stop_rgba(accent, 0.6, 0.98, 0.82, 0.28, 0.14 + 0.10 * pulse);
    c.cairo_pattern_add_color_stop_rgba(accent, 1.0, 0.98, 0.82, 0.28, 0.00);

    roundedRect(cr, x0 + 1, y0 + 1, w - 2, h - 2, radius - 1);
    _ = c.cairo_set_source(cr, accent);
    _ = c.cairo_stroke(cr);
}

fn roundedRect(cr: *c.cairo_t, x0: f64, y0: f64, w: f64, h: f64, radius: f64) void {
    const x1 = x0 + w;
    const y1 = y0 + h;
    c.cairo_new_sub_path(cr);
    c.cairo_arc(cr, x1 - radius, y0 + radius, radius, -std.math.pi / 2.0, 0.0);
    c.cairo_arc(cr, x1 - radius, y1 - radius, radius, 0.0, std.math.pi / 2.0);
    c.cairo_arc(cr, x0 + radius, y1 - radius, radius, std.math.pi / 2.0, std.math.pi);
    c.cairo_arc(cr, x0 + radius, y0 + radius, radius, std.math.pi, std.math.pi * 1.5);
    c.cairo_close_path(cr);
}
