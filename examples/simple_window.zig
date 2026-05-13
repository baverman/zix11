const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.xproto;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromInit(init, init.gpa);
    defer conn.deinit();

    const window = try conn.allocId(x.Window);

    try conn.request(x.CreateWindow, .{
        .depth = 0,
        .wid = window,
        .parent = conn.root_window,
        .x = 100,
        .y = 100,
        .width = 320,
        .height = 200,
        .border_width = 0,
        .class = .CopyFromParent,
        .visual = 0,
        .value_list = .{
            .background_pixel = 0x00ff0000,
            .event_mask = x.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });

    conn.request(x.MapWindow, .{ .window = @enumFromInt(0xbadbad) }) catch |err| switch (err) {
        error.X11ProtocolError => {
            const e = conn.lastError();
            switch (e.code) {
                .Window => {
                    std.debug.print("BadWidnow: 0x{x}\n", .{e.bad_value});
                },
                else => return err,
            }
        },
        else => return err,
    };

    try conn.request(x.MapWindow, .{ .window = window });
    std.debug.print("created window: 0x{x}\n", .{@intFromEnum(window)});

    while (true) {
        const event = try conn.nextEvent();
        switch (event) {
            .Expose => |ev| {
                if (ev.window == window and ev.count == 0) {
                    std.debug.print("expose {}x{}\n", .{ ev.width, ev.height });
                }
            },
            .ButtonPress => |ev| {
                if (ev.event == window) {
                    std.debug.print("button press at {}, {}\n", .{ ev.event_x, ev.event_y });
                    break;
                }
            },
            else => {},
        }
    }
}
