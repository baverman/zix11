const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;
const shm = zix11.shm;
const c = @cImport({
    @cInclude("errno.h");
    @cInclude("sys/ipc.h");
    @cInclude("sys/shm.h");
    @cInclude("cairo/cairo.h");
});

const width: u16 = 640;
const height: u16 = 360;
const bytes_per_pixel: usize = 4;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    try conn.registerExtension(.MIT_SHM);
    _ = try conn.request(shm.QueryVersion, .{});

    const root_geometry = try conn.request(x.GetGeometry, .{
        .drawable = .{ .window = conn.root_window },
    });
    const depth = root_geometry.depth;

    const window = try conn.allocId(x.Window);
    const gc = try conn.allocId(x.Gcontext);
    const shmseg = try conn.allocId(shm.Seg);

    try conn.request(x.CreateWindow, .{
        .depth = depth,
        .wid = window,
        .parent = conn.root_window,
        .x = 120,
        .y = 80,
        .width = width,
        .height = height,
        .border_width = 0,
        .class = .CopyFromParent,
        .visual = 0,
        .value_list = .{
            .background_pixel = 0x00111111,
            .event_mask = x.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });
    defer conn.request(x.DestroyWindow, .{ .window = window }) catch {};

    try conn.request(x.CreateGC, .{
        .cid = gc,
        .drawable = .{ .window = window },
        .value_list = .{},
    });
    defer conn.request(x.FreeGC, .{ .gc = gc }) catch {};

    const image_len = @as(usize, width) * @as(usize, height) * bytes_per_pixel;
    const shmid = c.shmget(c.IPC_PRIVATE, image_len, c.IPC_CREAT | 0o600);
    if (shmid < 0) return posixError("shmget failed");
    defer _ = c.shmctl(shmid, c.IPC_RMID, null);

    const shmaddr = c.shmat(shmid, null, 0);
    if (@intFromPtr(shmaddr) == @as(usize, @bitCast(@as(isize, -1)))) {
        return posixError("shmat failed");
    }
    defer _ = c.shmdt(shmaddr);

    const pixels_ptr: [*]align(@alignOf(u32)) u8 = @ptrCast(@alignCast(shmaddr));
    const pixels = pixels_ptr[0..image_len];

    try conn.request(shm.Attach, .{
        .shmseg = shmseg,
        .shmid = @intCast(shmid),
        .read_only = false,
    });
    defer conn.request(shm.Detach, .{ .shmseg = shmseg }) catch {};

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

    drawScene(cr);

    try conn.request(x.MapWindow, .{ .window = window });
    try present(&conn, window, gc, depth, surface, shmseg);

    while (true) {
        const event = try conn.nextEvent();
        switch (event) {
            .Expose => |ev| {
                if (ev.window == window and ev.count == 0) {
                    try present(&conn, window, gc, depth, surface, shmseg);
                }
            },
            .ButtonPress => |ev| {
                if (ev.event == window) return;
            },
            else => {},
        }
    }
}

fn present(
    conn: *zix11.Connection,
    window: x.Window,
    gc: x.Gcontext,
    depth: u8,
    surface: *c.cairo_surface_t,
    shmseg: shm.Seg,
) !void {
    c.cairo_surface_flush(surface);
    try conn.request(shm.PutImage, .{
        .drawable = .{ .window = window },
        .gc = gc,
        .total_width = width,
        .total_height = height,
        .src_x = 0,
        .src_y = 0,
        .src_width = width,
        .src_height = height,
        .dst_x = 0,
        .dst_y = 0,
        .depth = depth,
        .format = @intFromEnum(x.ImageFormat.ZPixmap),
        .send_event = false,
        .shmseg = shmseg,
        .offset = 0,
    });
}

fn posixError(msg: []const u8) error{SystemResources}!void {
    std.log.err("{s}", .{msg});
    return error.SystemResources;
}

fn drawScene(cr: *c.cairo_t) void {
    const bg = c.cairo_pattern_create_linear(0, 0, 0, height);
    defer c.cairo_pattern_destroy(bg);
    c.cairo_pattern_add_color_stop_rgb(bg, 0.0, 0.07, 0.09, 0.16);
    c.cairo_pattern_add_color_stop_rgb(bg, 0.55, 0.19, 0.10, 0.18);
    c.cairo_pattern_add_color_stop_rgb(bg, 1.0, 0.39, 0.16, 0.20);
    _ = c.cairo_set_source(cr, bg);
    c.cairo_rectangle(cr, 0, 0, width, height);
    _ = c.cairo_fill(cr);

    drawOrb(cr, 120, 110, 130, 0.22, 0.72, 0.86, 0.34);
    drawOrb(cr, 520, 80, 110, 0.98, 0.75, 0.18, 0.28);
    drawOrb(cr, 500, 290, 150, 0.95, 0.35, 0.42, 0.22);

    drawCard(cr, 92, 84, 456, 192, 26);

    c.cairo_select_font_face(cr, "Sans", c.CAIRO_FONT_SLANT_NORMAL, c.CAIRO_FONT_WEIGHT_BOLD);
    c.cairo_set_font_size(cr, 34);
    c.cairo_set_source_rgba(cr, 0.96, 0.97, 0.99, 1.0);
    c.cairo_move_to(cr, 132, 168);
    _ = c.cairo_show_text(cr, "zix11 + cairo + shm");

    c.cairo_select_font_face(cr, "Sans", c.CAIRO_FONT_SLANT_NORMAL, c.CAIRO_FONT_WEIGHT_NORMAL);
    c.cairo_set_font_size(cr, 17);
    c.cairo_set_source_rgba(cr, 0.88, 0.90, 0.94, 0.9);
    c.cairo_move_to(cr, 136, 204);
    _ = c.cairo_show_text(cr, "software image surface in SysV shared memory");
    c.cairo_move_to(cr, 136, 230);
    _ = c.cairo_show_text(cr, "uploaded with MIT-SHM PutImage directly to the window");
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

fn drawCard(cr: *c.cairo_t, x0: f64, y0: f64, w: f64, h: f64, radius: f64) void {
    const shadow = c.cairo_pattern_create_linear(x0, y0, x0, y0 + h);
    defer c.cairo_pattern_destroy(shadow);
    c.cairo_pattern_add_color_stop_rgba(shadow, 0.0, 0.02, 0.02, 0.04, 0.72);
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

    c.cairo_set_line_width(cr, 1.2);
    c.cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.12);
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
