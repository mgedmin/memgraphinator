#!/usr/bin/env python
import sys

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib, Gdk, Gio, Gtk, Pango


if len(sys.argv) < 2:
    sys.exit('Usage: %s pid' % sys.argv[0])

pid = int(sys.argv[1])


def mem_usage(pid):
    try:
        with open('/proc/%d/status' % pid) as fp:
            for line in fp:
                if line.startswith('VmSize:'):
                    return int(line.split()[1])
    except IOError:
        return None


class Graph(Gtk.DrawingArea):

    def __init__(self):
        super(Graph, self).__init__()
        self.data = []

    def add_point(self, value):
        self.data.append(value)
        self.queue_draw()

    def do_draw(self, cr):
        cr.save()

        window = self.get_window()
        w = window.get_width()
        h = window.get_height()

        # white background
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        n = len(self.data)
        if not n:
            return

        # approach 1: draw the graph from left to right, squeezing it when it no longer fits
        scale = max(self.data)
        if n > w:
            dx = float(w - 1) / (n - 1)
        else:
            dx = 1
        dy = float(max(1, h - 10)) / scale
        points = self._points(0, h, dx, -dy)

        # color stolen from virt-manager
        cr.set_source_rgb(0.421875, 0.640625, 0.73046875)
        cr.set_line_width(1)
        self._line(cr, points)
        cr.stroke()

        cr.set_source_rgba(0.71484375, 0.84765625, 0.89453125, .5)
        self._line(cr, points)
        cr.line_to(points[-1][0], h)
        cr.line_to(0, h)
        cr.fill()

        cr.restore()

    def _points(self, x0, y0, dx, dy):
        pts = []
        for i, pt in enumerate(self.data):
            pts.append((x0 + i * dx, y0 + pt * dy))
        return pts

    def _line(self, cr, points):
        for i, (x, y) in enumerate(points):
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)


class MainWindow(Gtk.Window):
    def __init__(self, pid):
        super(MainWindow, self).__init__()
        self.pid = pid

        self.set_default_size(300, 100)

        self.graph = Graph()
        self.add(self.graph)
        self.set_property("title", "Memory usage of %d" % pid)

        self.connect("delete-event", Gtk.main_quit)
        self.poll()
        GObject.timeout_add_seconds(1, self.poll)

    def poll(self):
        self.graph.add_point(mem_usage(self.pid))
        return True


win = MainWindow(pid)
win.show_all()
Gtk.main()
