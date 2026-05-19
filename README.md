# zix11

A Zig library implementing a client for the X11 protocol

Protocol generator uses https://gitlab.freedesktop.org/xorg/proto/xcbproto XML
descriptions to create Zig types and decoders/encoders for X11.

Goals:

- Fix xlib situation with error handlers. BadWindow is legitimate response and
  should be handled at call site.
- Fix xlib/xcb response ownership. Consumer should have control how and where
  response should be stored.
- Be nearer to X11 without xlib helper functions. There are connection, request
  structs and send functions able to send request struct and decode response.
- Use distinct types for X11 primitives. Passing ATOM value to WINDOW arg
  should be a compile error.


## LLM Disclaimer

Initial version was generated with LLM help. Later design
and important parts like libxcb schema validator are handwritten.


## Example

Create a window, map it, and handle expose and button press events:

```zig
const std = @import("std");
const zix11 = @import("zix11");
const x = zix11.x;

pub fn main(init: std.process.Init) !void {
    var conn = try zix11.Connection.connectFromEnv(init.gpa, init.io, init.environ_map);
    defer conn.deinit();

    const window = try conn.allocId(x.Window);

    // There is no XCreateWindow function with a zillion arguments.
    // Just a direct struct initialization and conn.request call.
    // BTW, it has sync semantics: if request fails, it would be a Zig error.
    // WIP: sensible defaults.
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
        // Juicy part. The library handles the value list mask for you.
        .value_list = .{
            .background_pixel = 0x00ff0000,
            .event_mask = x.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });

    // Handle errors directly. Try doing that with xlib :)
    conn.request(x.MapWindow, .{ .window = @enumFromInt(0xbadbad) }) catch |err| switch (conn.lastError(err)) {
        .Window => |e| {
            std.debug.print("BadWindow: 0x{x}\n", .{e.bad_value});
        },
        else => return err,
    };

    try conn.request(x.MapWindow, .{ .window = window });
    std.debug.print("created window: 0x{x}\n", .{@intFromEnum(window)});

    while (true) {
        while (try conn.pollEvent()) |event| {
            // Event is tagged union.
            switch (event) {
                .Expose => |ev| {
                    if (ev.window == window and ev.count == 0) {
                        std.debug.print("expose {}x{}\n", .{ ev.width, ev.height });
                    }
                },
                .ButtonPress => |ev| {
                    if (ev.event == window) {
                        std.debug.print("button press at {}, {}\n", .{ ev.event_x, ev.event_y });
                        return;
                    }
                },
                else => {},
            }
        }

        if (!try conn.waitForEvents(3000)) {
            std.debug.print("No events, do something else\n", .{});
            continue;
        }
    }
}
```
