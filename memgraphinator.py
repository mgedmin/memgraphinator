#!/usr/bin/env python
import signal
import sys
import os

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, Gtk, Pango


if len(sys.argv) < 2:
    pid = None
else:
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
        if value is not None:
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

        # approach 2: draw the graph from right to left, discarding data if it no longer fits
        scale = max(self.data)
        dx = 1
        dy = float(max(1, h - 10)) / scale
        n = min(len(self.data), w)
        points = self._points(w - n, h, dx, -dy, slice(-n, None))

        # color stolen from virt-manager
        cr.set_source_rgb(0.421875, 0.640625, 0.73046875)
        cr.set_line_width(1)
        self._line(cr, points)
        cr.stroke()

        cr.set_source_rgba(0.71484375, 0.84765625, 0.89453125, .5)
        self._line(cr, points)
        cr.line_to(points[-1][0], h)
        cr.line_to(points[0][0], h)
        cr.fill()

        cr.restore()

    def _points(self, x0, y0, dx, dy, slice=slice(None)):
        pts = []
        for i, pt in enumerate(self.data[slice]):
            pts.append((x0 + i * dx, y0 + pt * dy))
        return pts

    def _line(self, cr, points):
        for i, (x, y) in enumerate(points):
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)


class MainWindow(Gtk.Window):

    _pid = None

    def __init__(self, pid):
        super(MainWindow, self).__init__()

        self.connect("delete-event", Gtk.main_quit)
        self.set_default_size(300, 100)
        self.set_border_width(6)

        self.select_button = Gtk.Button("Select a process")
        self.select_button.set_relief(Gtk.ReliefStyle.NONE)
        self.select_button.connect("clicked", self.select_process)

        self.graph = Graph()

        self.pid = pid

    @property
    def pid(self):
        return self._pid

    @pid.setter
    def pid(self, new_pid):
        child = self.get_child()
        if child:
            self.remove(child)
        if new_pid:
            self._pid = new_pid
            self.set_title("Memory usage of %d" % new_pid)
            self.add(self.graph)
            self.graph.show()
            self._start_polling()
        else:
            self.set_title("Memory usage of a process")
            self.add(self.select_button)
            self.select_button.show()

    def _start_polling(self):
        self._start_polling = lambda: None  # don't do this again
        self.poll()
        GObject.timeout_add(100, self.poll)

    def poll(self):
        self.graph.add_point(mem_usage(self.pid))
        return True

    def select_process(self, target):
        process_selector_dialog = ProcessSelector(self)
        if process_selector_dialog.run() == Gtk.ResponseType.OK:
            self.pid = process_selector_dialog.pid
        process_selector_dialog.destroy()


class ProcessSelector(Gtk.Dialog):

    def __init__(self, parent):
        super(ProcessSelector, self).__init__(
            "Select a process", parent=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.USE_HEADER_BAR,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                     Gtk.STOCK_OK, Gtk.ResponseType.OK))
        self.set_default_size(600, 400)
        area = self.get_content_area()
        self.store = Gtk.ListStore(int, str, int, str) # pid, command, size, size_string
        self.refresh_process_list()
        self.process_list = Gtk.TreeView(model=self.store)
        self.process_list.set_search_column(1)
        column = Gtk.TreeViewColumn("PID", Gtk.CellRendererText(xalign=1.0), text=0)
        column.set_sort_column_id(0)
        self.process_list.append_column(column)
        column = Gtk.TreeViewColumn("Command", Gtk.CellRendererText(), text=1)
        column.set_sort_column_id(1)
        column.set_expand(True)
        column.set_max_width(200)
        self.process_list.append_column(column)
        column = Gtk.TreeViewColumn("Size", Gtk.CellRendererText(xalign=1.0), text=3)
        column.set_sort_column_id(2)
        self.process_list.append_column(column)
        self.process_list.connect("row_activated", self.select_process)
        w = Gtk.ScrolledWindow()
        w.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        w.add(self.process_list)
        area.pack_start(w, True, True, 0)
        area.show_all()

    @property
    def pid(self):
        model, iter = self.process_list.get_selection().get_selected()
        if not iter:
            return None
        return model[iter][0]

    def select_process(self, treeview, path, view_column):
        self.response(Gtk.ResponseType.OK)

    def refresh_process_list(self):
        self.store.clear()
        for n in os.listdir('/proc'):
            if n.isdigit():
                try:
                    with open('/proc/%s/cmdline' % n, 'rb') as f:
                        cmdline = f.read().replace('\0', ' ')
                    if not cmdline:
                        with open('/proc/%s/stat' % n, 'rb') as f:
                            stat = f.read()
                            cmdline = stat.partition('(')[-1].rpartition(')')[0]
                except IOError:
                    continue
                pid = int(n)
                size = mem_usage(pid) or 0
                size_mb = '{:,} MB'.format(size / 1024)
                self.store.append([pid, cmdline, size, size_mb])


win = MainWindow(pid)
win.show_all()
signal.signal(signal.SIGINT, signal.SIG_DFL)
Gtk.main()
