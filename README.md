# zix11

A zig library implementing a client for X11 protocol

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


## Example

Create a window, map it, and handle expose and button press events:

```zig
const std = @import("std");
const zix = @import("zix");

pub fn main(init: std.process.Init) !void {
    // WIP. Temporary shortcut.
    var conn = try zix.Connection.connectFromInit(init, init.gpa);
    defer conn.deinit();

    const window = try conn.allocId(zix.xproto.Window);

    // There is no XCreateWindow function with zillion agruments.
    // Just a direct struct initialization and conn.request call.
    // BTW, it has sync semantics, if request fails, it would be a Zig error.
    // WIP: sensible defaults.
    try conn.request(zix.xproto.CreateWindowRequest{
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
        // Jucy part. Library handles value list mask for you.
        .value_list = .{
            .background_pixel = 0x00ff0000,
            .event_mask = zix.xproto.EventMask.of(&.{ .Exposure, .ButtonPress }),
        },
    });

    try conn.request(zix.xproto.MapWindowRequest{
        .window = window,
    });

    while (true) {
        const event = try conn.nextEvent();
        // Event is tagged union.
        switch (event) {
            .expose => |ev| {
                if (ev.window == window and ev.count == 0) {
                    std.debug.print("expose {}x{}\n", .{ ev.width, ev.height });
                }
            },
            .button_press => |ev| {
                if (ev.event == window) {
                    std.debug.print("button press at {}, {}\n", .{ ev.event_x, ev.event_y });
                    break;
                }
            },
            else => {},
        }
    }
}
```
