const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;
const render = zix11.render;
const c = @cImport({
    @cInclude("cairo/cairo.h");
});

const width: u16 = 420;
const height: u16 = 260;
const bytes_per_pixel: usize = 4;
const max_putimage_bytes: usize = 256 * 1024;

const ArgbVisual = struct {
    visual: u32,
    depth: u8,
    format: render.Pictformat,
};

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();
    try conn.registerExtension(.RENDER);

    var formats = try conn.requestAlloc(init.gpa, render.QueryPictFormats, .{});
    defer formats.deinit(init.gpa);

    const argb = findArgbVisual(formats) orelse return error.NoArgbVisual;

    const window = try conn.allocId(x.Window);
    const colormap = try conn.allocId(x.Colormap);
    const pixmap = try conn.allocId(x.Pixmap);
    const gc = try conn.allocId(x.Gcontext);
    const src_picture = try conn.allocId(render.Picture);
    const dst_picture = try conn.allocId(render.Picture);

    try conn.request(x.CreateColormap, .{
        .alloc = .None,
        .mid = colormap,
        .window = conn.root_window,
        .visual = argb.visual,
    });
    defer conn.request(x.FreeColormap, .{ .cmap = colormap }) catch {};

    try conn.request(x.CreateWindow, .{
        .depth = argb.depth,
        .wid = window,
        .parent = conn.root_window,
        .x = 180,
        .y = 120,
        .width = width,
        .height = height,
        .border_width = 0,
        .class = .InputOutput,
        .visual = argb.visual,
        .value_list = .{
            .border_pixel = 0,
            .colormap = colormap,
            .event_mask = x.EventMask.of(&.{ .Exposure, .ButtonPress, .StructureNotify }),
        },
    });
    defer conn.request(x.DestroyWindow, .{ .window = window }) catch {};

    try conn.request(x.CreatePixmap, .{
        .depth = argb.depth,
        .pid = pixmap,
        .drawable = .{ .window = window },
        .width = width,
        .height = height,
    });
    defer conn.request(x.FreePixmap, .{ .pixmap = pixmap }) catch {};

    try conn.request(x.CreateGC, .{
        .cid = gc,
        .drawable = .{ .pixmap = pixmap },
        .value_list = .{
            .graphics_exposures = 0,
        },
    });
    defer conn.request(x.FreeGC, .{ .gc = gc }) catch {};

    try conn.request(render.CreatePicture, .{
        .pid = src_picture,
        .drawable = .{ .pixmap = pixmap },
        .format = argb.format,
        .value_list = .{},
    });
    defer conn.request(render.FreePicture, .{ .picture = src_picture }) catch {};

    try conn.request(render.CreatePicture, .{
        .pid = dst_picture,
        .drawable = .{ .window = window },
        .format = argb.format,
        .value_list = .{},
    });
    defer conn.request(render.FreePicture, .{ .picture = dst_picture }) catch {};

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

    drawScene(cr);

    try conn.request(x.MapWindow, .{ .window = window });
    try present(&conn, gc, argb.depth, pixmap, src_picture, dst_picture, surface, pixels);

    while (true) {
        const event = try conn.nextEvent();
        switch (event) {
            .Expose => |ev| {
                if (ev.window == window and ev.count == 0) {
                    try present(&conn, gc, argb.depth, pixmap, src_picture, dst_picture, surface, pixels);
                }
            },
            .ButtonPress => |ev| {
                if (ev.event == window) return;
            },
            else => {},
        }
    }
}

fn findArgbVisual(reply: render.QueryPictFormatsReply) ?ArgbVisual {
    for (reply.formats) |format| {
        if (format.type != .Direct) continue;
        if (format.depth != 32) continue;
        if (format.direct.alpha_mask == 0) continue;

        for (reply.screens) |screen| {
            for (screen.depths) |depth| {
                if (depth.depth != 32) continue;
                for (depth.visuals) |visual| {
                    if (visual.format == format.id) {
                        return .{
                            .visual = visual.visual,
                            .depth = depth.depth,
                            .format = format.id,
                        };
                    }
                }
            }
        }
    }
    return null;
}

fn present(
    conn: *zix11.Connection,
    gc: x.Gcontext,
    depth: u8,
    pixmap: x.Pixmap,
    src_picture: render.Picture,
    dst_picture: render.Picture,
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
            .drawable = .{ .pixmap = pixmap },
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

    try clearPicture(conn, dst_picture);
    try conn.request(render.Composite, .{
        .op = .Over,
        .src = src_picture,
        .mask = @enumFromInt(0),
        .dst = dst_picture,
        .src_x = 0,
        .src_y = 0,
        .mask_x = 0,
        .mask_y = 0,
        .dst_x = 0,
        .dst_y = 0,
        .width = width,
        .height = height,
    });
}

fn clearPicture(conn: *zix11.Connection, picture: render.Picture) !void {
    const rects = [_]x.RECTANGLE{.{
        .x = 0,
        .y = 0,
        .width = width,
        .height = height,
    }};
    try conn.request(render.FillRectangles, .{
        .op = .Src,
        .dst = picture,
        .color = .{
            .red = 0,
            .green = 0,
            .blue = 0,
            .alpha = 0,
        },
        .rects = &rects,
    });
}

fn drawScene(cr: *c.cairo_t) void {
    c.cairo_set_operator(cr, c.CAIRO_OPERATOR_SOURCE);
    c.cairo_set_source_rgba(cr, 0.0, 0.0, 0.0, 0.0);
    _ = c.cairo_paint(cr);

    drawShadow(cr, 88, 54, 244, 152, 38);
    drawBlob(cr, 132, 88, 94, 0.18, 0.86, 0.98, 0.44);
    drawBlob(cr, 290, 176, 108, 0.98, 0.32, 0.60, 0.34);

    c.cairo_set_fill_rule(cr, c.CAIRO_FILL_RULE_EVEN_ODD);
    c.cairo_new_path(cr);
    roundedRect(cr, 78, 44, 264, 172, 42);
    c.cairo_arc(cr, 210, 130, 54, 0, std.math.pi * 2.0);
    c.cairo_set_source_rgba(cr, 0.08, 0.10, 0.16, 0.76);
    _ = c.cairo_fill_preserve(cr);

    c.cairo_set_line_width(cr, 2.0);
    c.cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.22);
    _ = c.cairo_stroke(cr);
    c.cairo_set_fill_rule(cr, c.CAIRO_FILL_RULE_WINDING);

    c.cairo_set_line_width(cr, 12.0);
    c.cairo_arc(cr, 210, 130, 60, 0, std.math.pi * 2.0);
    c.cairo_set_source_rgba(cr, 0.98, 0.84, 0.30, 0.55);
    _ = c.cairo_stroke(cr);

    c.cairo_select_font_face(cr, "Sans", c.CAIRO_FONT_SLANT_NORMAL, c.CAIRO_FONT_WEIGHT_BOLD);
    c.cairo_set_font_size(cr, 24);
    c.cairo_set_source_rgba(cr, 0.98, 0.99, 1.0, 0.94);
    c.cairo_move_to(cr, 108, 90);
    _ = c.cairo_show_text(cr, "transparent hole");

    c.cairo_select_font_face(cr, "Sans", c.CAIRO_FONT_SLANT_NORMAL, c.CAIRO_FONT_WEIGHT_NORMAL);
    c.cairo_set_font_size(cr, 15);
    c.cairo_set_source_rgba(cr, 0.86, 0.90, 0.95, 0.86);
    c.cairo_move_to(cr, 98, 190);
    _ = c.cairo_show_text(cr, "The center circle stays fully transparent.");
}

fn drawShadow(cr: *c.cairo_t, x0: f64, y0: f64, w: f64, h: f64, radius: f64) void {
    const shadow = c.cairo_pattern_create_linear(x0, y0, x0, y0 + h);
    defer c.cairo_pattern_destroy(shadow);
    c.cairo_pattern_add_color_stop_rgba(shadow, 0.0, 0.00, 0.00, 0.00, 0.28);
    c.cairo_pattern_add_color_stop_rgba(shadow, 1.0, 0.00, 0.00, 0.00, 0.14);
    roundedRect(cr, x0 + 12, y0 + 14, w, h, radius);
    _ = c.cairo_set_source(cr, shadow);
    _ = c.cairo_fill(cr);
}

fn drawCard(cr: *c.cairo_t, x0: f64, y0: f64, w: f64, h: f64, radius: f64) void {
    const panel = c.cairo_pattern_create_linear(x0, y0, x0, y0 + h);
    defer c.cairo_pattern_destroy(panel);
    c.cairo_pattern_add_color_stop_rgba(panel, 0.0, 0.08, 0.10, 0.16, 0.64);
    c.cairo_pattern_add_color_stop_rgba(panel, 1.0, 0.06, 0.08, 0.12, 0.52);

    roundedRect(cr, x0, y0, w, h, radius);
    _ = c.cairo_set_source(cr, panel);
    _ = c.cairo_fill_preserve(cr);

    c.cairo_set_line_width(cr, 1.4);
    c.cairo_set_source_rgba(cr, 1.0, 1.0, 1.0, 0.18);
    _ = c.cairo_stroke(cr);
}

fn drawBlob(cr: *c.cairo_t, cx: f64, cy: f64, radius: f64, r: f64, g: f64, b: f64, alpha: f64) void {
    const orb = c.cairo_pattern_create_radial(cx, cy, radius * 0.08, cx, cy, radius);
    defer c.cairo_pattern_destroy(orb);
    c.cairo_pattern_add_color_stop_rgba(orb, 0.0, r, g, b, alpha);
    c.cairo_pattern_add_color_stop_rgba(orb, 1.0, r, g, b, 0.0);
    _ = c.cairo_set_source(cr, orb);
    c.cairo_arc(cr, cx, cy, radius, 0, std.math.pi * 2.0);
    _ = c.cairo_fill(cr);
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
