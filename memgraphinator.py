#!/usr/bin/env python
import signal
import os
import argparse
import subprocess

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, Gtk, Pango


def list_processes():
    for n in os.listdir('/proc'):
        if n.isdigit():
            yield int(n)


def get_command_line(pid):
    try:
        with open('/proc/%d/cmdline' % pid, 'rb') as f:
            cmdline = f.read().replace('\0', ' ')
        if not cmdline:
            with open('/proc/%d/stat' % pid, 'rb') as f:
                stat = f.read()
                cmdline = stat.partition('(')[-1].rpartition(')')[0]
        return cmdline
    except IOError:
        return None


def get_owner(pid):
    try:
        return os.stat('/proc/%d' % pid).st_uid
    except IOError:
        return None


def get_mem_usage(pid):
    try:
        with open('/proc/%d/status' % pid) as fp:
            for line in fp:
                if line.startswith('VmSize:'):
                    return int(line.split()[1])
    except IOError:
        return None


def format_size(size):
    return '{:,} MB'.format(size / 1024)


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


class ProcessGraph(Gtk.VBox):

    def __init__(self):
        super(ProcessGraph, self).__init__()
        self.label = Gtk.Label('Process', xalign=0,
                               ellipsize=Pango.EllipsizeMode.END)
        self.pack_start(self.label, False, False, 0)
        self.graph = Graph()
        self.pack_start(self.graph, True, True, 0)
        self.size_label = Gtk.Label('', xalign=1.0)
        self.pack_start(self.size_label, False, False, 0)
        self._pid = None

    @property
    def pid(self):
        return self._pid

    @pid.setter
    def pid(self, new_pid):
        self._pid = new_pid
        self.label.set_label(get_command_line(new_pid))

    def add_point(self, value):
        if value is not None:
            self.graph.add_point(value)
            self.size_label.set_label(format_size(value))


class MainWindow(Gtk.Window):

    _pid = None
    exit_when_process_dies = False

    def __init__(self, pid):
        super(MainWindow, self).__init__()

        self.connect("delete-event", Gtk.main_quit)
        self.set_default_size(300, 100)
        self.set_border_width(6)

        self.select_button = Gtk.Button("Select a process")
        self.select_button.set_relief(Gtk.ReliefStyle.NONE)
        self.select_button.connect("clicked", self.select_process)

        self.graph = ProcessGraph()
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
            self.graph.pid = new_pid
            self.add(self.graph)
            self.graph.show_all()
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
        value = get_mem_usage(self.pid)
        if value is None:
            if self.exit_when_process_dies:
                Gtk.main_quit()
            return False
        else:
            self.graph.add_point(value)
            return True

    def select_process(self, target):
        process_selector_dialog = ProcessSelector(self)
        if process_selector_dialog.run() == Gtk.ResponseType.OK:
            self.pid = process_selector_dialog.pid
        process_selector_dialog.destroy()


class ProcessSelector(Gtk.Dialog):

    class Column:
        types = (int, str, int, str, bool)
        PID, COMMAND, SIZE, SIZE_TEXT, MINE = range(len(types))

    def __init__(self, parent):
        super(ProcessSelector, self).__init__(
            "Select a process", parent=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.USE_HEADER_BAR,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                     Gtk.STOCK_OK, Gtk.ResponseType.OK))
        self.set_default_size(600, 400)
        area = self.get_content_area()
        self.store = Gtk.ListStore(*self.Column.types)
        self.filter_model = Gtk.TreeModelFilter(child_model=self.store)
        self.filter_model.set_visible_func(self.is_process_visible)
        self.process_list = Gtk.TreeView(model=self.filter_model)
        self.process_list.set_search_column(self.Column.COMMAND)
        column = Gtk.TreeViewColumn("PID", Gtk.CellRendererText(xalign=1.0),
                                    text=self.Column.PID)
        column.set_sort_column_id(self.Column.PID)
        self.process_list.append_column(column)
        column = Gtk.TreeViewColumn("Command",
                                    Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END),
                                    text=self.Column.COMMAND)
        column.set_sort_column_id(self.Column.COMMAND)
        column.set_expand(True)
        column.set_max_width(200)
        self.process_list.append_column(column)
        column = Gtk.TreeViewColumn("Size", Gtk.CellRendererText(xalign=1.0),
                                    text=self.Column.SIZE_TEXT)
        column.set_sort_column_id(self.Column.SIZE)
        self.process_list.append_column(column)
        self.process_list.connect("row_activated", self.select_process)
        w = Gtk.ScrolledWindow()
        w.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        w.add(self.process_list)
        area.pack_start(w, True, True, 0)
        self.show_all_checkbox = Gtk.CheckButton(label='Show processes belonging to all users')
        self.show_all_checkbox.connect('toggled', self.show_all_toggled)
        area.pack_start(self.show_all_checkbox, False, False, 0)
        area.show_all()
        GObject.idle_add(self.refresh_process_list)

    @property
    def pid(self):
        model, iter = self.process_list.get_selection().get_selected()
        if not iter:
            return None
        return model[iter][self.Column.PID]

    def show_all_toggled(self, widget):
        self.filter_model.refilter()

    def is_process_visible(self, model, iter, data):
        if self.show_all_checkbox.get_active():
            return True
        return model[iter][self.Column.MINE]

    def select_process(self, treeview, path, view_column):
        self.response(Gtk.ResponseType.OK)

    def refresh_process_list(self):
        self.store.clear()
        my_uid = os.getuid()
        for pid in list_processes():
            cmdline = get_command_line(pid)
            owner = get_owner(pid)
            size = get_mem_usage(pid)
            if cmdline is None or owner is None or size is None:
                # process must've just died.  size being None might also
                # indicate a kernel thread (and we're not interested in those)
                continue
            size_mb = format_size(size)
            mine = owner == my_uid
            self.store.append([pid, cmdline, size, size_mb, mine])


def main():
    parser = argparse.ArgumentParser(description="Graph process memory usage")
    parser.add_argument('command', nargs='*',
                        help='Command to execute')
    parser.add_argument('-p', '--pid', type=int, help='Existing process to monitor')
    parser.add_argument('--exit-when-process-dies', action='store_true',
                        help='Exit when monitored process dies')
    args = parser.parse_args()
    if args.command and len(args.command) == 1 and args.command[0].isdigit():
        pid = int(args.command[0])
    elif args.pid:
        pid = args.pid
    elif args.command:
        pid = subprocess.Popen(args.command).pid
    else:
        pid = None
    win = MainWindow(pid)
    win.exit_when_process_dies = args.exit_when_process_dies
    win.show_all()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()

if __name__ == '__main__':
    main()
