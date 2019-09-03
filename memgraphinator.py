#!/usr/bin/env python3
import signal
import sys
import os
import argparse
import subprocess
import time
import math
from collections import namedtuple

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib, Gtk, Gdk, Pango  # noqa: E402


def list_processes():
    for n in os.listdir('/proc'):
        if n.isdigit():
            yield int(n)


def get_command_line(pid):
    try:
        with open('/proc/%d/cmdline' % pid, 'rb') as f:
            cmdline = f.read().replace(b'\0', b' ')
        if not cmdline:
            with open('/proc/%d/stat' % pid, 'rb') as f:
                stat = f.read()
                cmdline = stat.partition(b'(')[-1].rpartition(b')')[0]
        return cmdline.decode('UTF-8', 'replace')
    except IOError:
        return None


def get_owner(pid):
    try:
        return os.stat('/proc/%d' % pid).st_uid
    except IOError:
        return None


MemoryUsage = namedtuple('MemoryUsage', 'virt, rss')
MemoryUsage.zero = MemoryUsage(0, 0)
MemoryUsage.invalid = MemoryUsage(-1, -1)


def get_mem_usage(pid):
    virt = rss = None
    try:
        with open('/proc/%d/status' % pid) as fp:
            for line in fp:
                if line.startswith('VmSize:'):
                    virt = int(line.split()[1])
                elif line.startswith('VmRSS:'):
                    rss = int(line.split()[1])
    except IOError:
        pass
    if virt is not None and rss is not None:
        return MemoryUsage(virt, rss)


def format_size(size):
    return '{:,} MB'.format(size // 1024)


def format_time_ago(seconds):
    if seconds < 60:
        return '%d seconds ago' % seconds
    elif seconds < 60 * 60:
        m, s = divmod(seconds, 60)
        return '%d minutes, %d seconds ago' % (m, s)
    else:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return '%d hours, %d minutes, %d seconds ago' % (h, m, s)


class Graph(Gtk.DrawingArea):

    # color stolen from virt-manager
    VIRT_COLOR = (0.421875, 0.640625, 0.73046875)
    VIRT_COLOR_PAUSED = (0.421875, 0.73046875, 0.4705882)
    VIRT_FILL = (0.71484375, 0.84765625, 0.89453125, .5)
    VIRT_FILL_PAUSED = (0.854902, 0.945098, 0.8627451, .5)
    RSS_COLOR = (0.73046875, 0.421875, 0.640625)
    RSS_COLOR_PAUSED = (0.4705882, 0.421875, 0.73046875)
    RSS_FILL = (0.89453125, 0.71484375, 0.84765625, .5)
    RSS_FILL_PAUSED = (0.8627451, 0.854902, 0.945098, .5)
    SELECTION_COLOR = (0.75, 0.75, 0.75, 0.5)

    interval = GObject.Property(
        type=int, default=100, minimum=1, nick='Update interval (ms)')

    zoom = GObject.Property(
        type=float, default=1.0, minimum=1.0, nick='Zoom factor',
        blurb='Scale factor for zooming out the horizontal (time) axis')

    def __init__(self):
        super(Graph, self).__init__()
        self.time = None
        self.data = []
        self.peak = 1
        self._paused = False
        self._terminated = False
        self.visible_data = self.data
        self.visible_time = None
        self.visible_peak = None
        self.cur_pos = None
        self._cur_time = -1
        self._cur_value = MemoryUsage.invalid
        self.set_size_request(50, 50)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK |
                        Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect('notify::zoom', lambda *a: self.queue_draw())

    @GObject.Property(type=float, nick='Time (time_t) value under pointer')
    def cur_time(self):
        return self._cur_time

    @GObject.Property(type=int, nick='Value under pointer')
    def cur_value(self):
        return self._cur_value

    def _set_cur_time_value(self, time, value):
        if time == self._cur_time and value == self._cur_value:
            return
        self._cur_time = time
        self._cur_value = value
        self.notify("cur-time")
        self.notify("cur-value")

    @GObject.Property(type=bool, default=False, nick='Terminated')
    def terminated(self):
        return self._terminated

    @terminated.setter
    def terminated(self, new_value):
        self._terminated = new_value
        if self._terminated:
            self.paused = True

    @GObject.Property(type=bool, default=False, nick='Paused')
    def paused(self):
        return self._paused

    @paused.setter
    def paused(self, new_value):
        if self.terminated:
            new_value = True
        if new_value != self._paused:
            self._paused = new_value
            if self._paused:
                self.visible_data = list(self.data)
            else:
                self.visible_data = self.data
                self.visible_time = self.time
            self.queue_draw()

    def add_point(self, value):
        if value is not None:
            self.time = time.time()
            self.data.append(value)
            self.peak = max(self.peak, value.virt)
            if not self.paused:
                self.visible_time = self.time
                self.visible_peak = self.peak
                self.queue_draw()

    def do_motion_notify_event(self, event):
        self.cur_pos = event.x, event.y
        self.queue_draw()

    def do_leave_notify_event(self, event):
        self.cur_pos = None
        self._set_cur_time_value(-1, MemoryUsage.invalid)
        self.queue_draw()

    def do_button_press_event(self, event):
        if event.button == Gdk.BUTTON_PRIMARY:
            self.paused = not self.paused
            return True

    def do_draw(self, cr):
        cr.save()
        self._draw(cr)
        cr.restore()

    def _draw(self, cr):
        window = self.get_window()
        w = window.get_width()
        h = window.get_height()

        # white background
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # the graph
        n = len(self.visible_data)
        if n:
            self._draw_graph(cr, w, h)
        else:
            if self.cur_pos:
                self._draw_cur_pos(cr, h)
                self._set_cur_time_value(-1, MemoryUsage.invalid)

    def _draw_cur_pos(self, cr, h):
        x, y = self.cur_pos
        cr.set_source_rgba(*self.SELECTION_COLOR)
        cr.set_line_width(1)
        cr.move_to(x + 0.5, 0)
        cr.line_to(x + 0.5, h)
        cr.stroke()

    def _draw_graph(self, cr, w, h):
        if self.paused:
            virt_color, virt_fill = self.VIRT_COLOR_PAUSED, self.VIRT_FILL_PAUSED
            rss_color, rss_fill = self.RSS_COLOR_PAUSED, self.RSS_FILL_PAUSED
        else:
            virt_color, virt_fill = self.VIRT_COLOR, self.VIRT_FILL
            rss_color, rss_fill = self.RSS_COLOR, self.RSS_FILL

        # draw the graph from right to left, discarding data if it no longer fits
        dx = 1 / self.zoom
        dy = float(max(1, h - 10)) / self.visible_peak
        n = min(len(self.visible_data), int(w * self.zoom + 1))

        cr.set_line_width(1)

        # VIRT
        virt_points = self._points(w - n * dx + 1, h, dx, -dy, self.visible_data[-n:],
                                   MemoryUsage._fields.index('virt'))
        cr.set_source_rgba(*virt_fill)
        self._polygon(cr, virt_points, h)
        cr.fill()
        cr.set_source_rgb(*virt_color)
        self._line(cr, virt_points)
        cr.stroke()

        # RSS
        rss_points = self._points(w - n * dx + 1, h, dx, -dy, self.visible_data[-n:],
                                  MemoryUsage._fields.index('rss'))
        cr.set_source_rgba(*rss_fill)
        self._polygon(cr, rss_points, h)
        cr.fill()
        cr.set_source_rgb(*rss_color)
        self._line(cr, rss_points)
        cr.stroke()

        # Current position
        if self.cur_pos:
            self._draw_cur_pos(cr, h)
        if self.cur_pos and self.visible_time:
            x, y = self.cur_pos
            distance_from_right = (w - x)
            time = (
                self.visible_time
                - distance_from_right * self.zoom * self.interval * 0.001
            )
            idx = -int(round((distance_from_right + 1) * self.zoom))
            if not -n <= idx < 0:
                value = MemoryUsage.invalid
            else:
                value = self.visible_data[idx]
                cr.set_source_rgb(*virt_color)
                cr.arc(x + 0.5, h - value.virt * dy, 2, 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgb(*rss_color)
                cr.arc(x + 0.5, h - value.rss * dy, 2, 0, 2 * math.pi)
                cr.fill()
            self._set_cur_time_value(time, value)

    def _points(self, x0, y0, dx, dy, data, idx):
        pts = []
        step = max(1, int(1 / dx))
        for i in range(0, len(data), step):
            pts.append((x0 + i * dx, y0 + data[i][idx] * dy))
        return pts

    def _line(self, cr, points):
        for i, (x, y) in enumerate(points):
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)

    def _polygon(self, cr, points, h):
        self._line(cr, points)
        cr.line_to(points[-1][0], h)
        cr.line_to(points[0][0], h)


class ProcessGraph(Gtk.VBox):

    zoom = GObject.Property(
        type=float, default=1.0, minimum=1.0, nick='Zoom factor',
        blurb='Scale factor for zooming out the horizontal (time) axis')

    def __init__(self):
        super(ProcessGraph, self).__init__(spacing=2)
        self.label = Gtk.Label(label='Process', xalign=0,
                               ellipsize=Pango.EllipsizeMode.END)
        self.pack_start(self.label, False, False, 0)
        self.graph = Graph()
        self.bind_property("interval", self.graph, "interval")
        self.bind_property("zoom", self.graph, "zoom")
        f = Gtk.Frame()
        f.add(self.graph)
        self.pack_start(f, True, True, 0)
        b = Gtk.HBox()
        self.cur_value_label = Gtk.Label(label='', xalign=0.0,
                                         ellipsize=Pango.EllipsizeMode.END)
        self.graph.connect("notify::cur-value", self.cur_value_changed)
        self.graph.connect("notify::paused", self.cur_value_changed)
        self.graph.connect("notify::terminated", self.cur_value_changed)
        b.pack_start(self.cur_value_label, True, True, 0)
        self.size_label = Gtk.Label(label='', xalign=1.0)
        b.pack_end(self.size_label, True, True, 0)
        self.pack_start(b, False, False, 0)
        self._pid = None
        self._interval = 100
        self._stop = False

    @property
    def pid(self):
        return self._pid

    @pid.setter
    def pid(self, new_pid):
        self._pid = new_pid
        self.label.set_label(get_command_line(new_pid))
        self._start_polling()

    @GObject.Property(
        type=int, default=100, minimum=1, nick='Update interval (ms)')
    def interval(self):
        return self._interval

    @interval.setter
    def interval(self, new_value):
        if self.pid is not None:
            raise TypeError('Cannot change interval once polling is started')
        self._interval = new_value

    @GObject.Property(
        type=bool, default=True, nick='Alive')
    def alive(self):
        return not self.graph.terminated

    def stop(self):
        self._stop = True

    def _start_polling(self):
        self._start_polling = lambda: None  # don't do this again
        self._poll()
        GLib.timeout_add(self.interval, self._poll)

    def _poll(self):
        if self._stop:
            return False
        value = get_mem_usage(self.pid)
        if value is None:
            self.graph.add_point(MemoryUsage.zero)
            self.graph.terminated = True
            self.notify('alive')
            return False
        else:
            self.graph.add_point(value)
            self.size_label.set_label('{} / {}'.format(
                format_size(value.rss), format_size(value.virt)))
            return True

    def add_point(self, value):
        self.graph.add_point(value)

    def cur_value_changed(self, *args):
        if self.graph.cur_time == -1 or self.graph.visible_time is None:
            self.cur_value_label.set_label('')
            return
        ago = self.graph.visible_time - self.graph.cur_time
        when = format_time_ago(ago)
        if self.graph.terminated:
            when += ' before process died'
        elif self.graph.paused:
            when += ' before graph was paused'
        value = self.graph.cur_value
        if value == MemoryUsage.invalid:
            self.cur_value_label.set_label(when)
        else:
            self.cur_value_label.set_label("{rss} / {virt}, {when}".format(
                rss=format_size(value.rss), virt=format_size(value.virt),
                when=when))


def _scrollable(widget):
    """Wrap widget in a Gtk.ScrolledWindow()."""
    w = Gtk.ScrolledWindow()
    w.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    w.add(widget)
    return w


def _framed(widget):
    """Wrap widget in a Gtk.Frame()."""
    frame = Gtk.Frame()
    frame.add(widget)
    return frame


class MainWindow(Gtk.Window):

    zoom = GObject.Property(
        type=float, default=1.0, minimum=1.0, nick='Zoom factor',
        blurb='Scale factor for zooming out the horizontal (time) axis')

    def __init__(self, exit_when_process_dies=False):
        super(MainWindow, self).__init__()

        self.exit_when_process_dies = exit_when_process_dies
        self.graphs = []

        self.connect("delete-event", Gtk.main_quit)
        self.set_default_size(400, 250)
        self.set_border_width(6)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_title("Memory usage")
        self.set_titlebar(hb)

        button = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.select_process)
        hb.pack_start(button)

        box = Gtk.HBox()
        box.get_style_context().add_class("linked")

        self.zoom_out_button = Gtk.Button.new_from_icon_name(
            "zoom-out-symbolic", Gtk.IconSize.BUTTON)
        self.zoom_out_button.set_sensitive(False)
        self.zoom_out_button.connect("clicked", self.zoom_out)
        box.add(self.zoom_out_button)

        self.zoom_in_button = Gtk.Button.new_from_icon_name(
            "zoom-in-symbolic", Gtk.IconSize.BUTTON)
        self.zoom_in_button.set_sensitive(False)
        self.zoom_in_button.connect("clicked", self.zoom_in)
        box.add(self.zoom_in_button)

        hb.pack_end(box)

        self.select_button = Gtk.Button(label="Select a process")
        self.select_button.set_relief(Gtk.ReliefStyle.NONE)
        self.select_button.connect("clicked", self.select_process)

        self.vbox = Gtk.VBox()
        self.vbox.add(self.select_button)
        w = Gtk.ScrolledWindow()
        w.add(self.vbox)
        self.add(w)

        self.graph_popup = Gtk.Menu()
        remove_graph = Gtk.MenuItem.new_with_mnemonic(label="_Remove")
        remove_graph.connect("activate", self.remove_graph)
        self.graph_popup.append(remove_graph)
        self.graph_popup.show_all()

    def watch_pid(self, pid, start_from_zero=False):
        graph = ProcessGraph()
        graph.connect('notify::alive', self.process_exited)
        graph.zoom = self.zoom
        self.bind_property("zoom", graph, "zoom")
        if start_from_zero:
            graph.add_point(MemoryUsage.zero)
        graph.pid = pid
        graph.connect("button-press-event", self.show_graph_popup)
        graph.show_all()

        if not self.graphs:
            self.vbox.remove(self.select_button)
            self.zoom_out_button.set_sensitive(True)
            if self.zoom != 1.0:
                self.zoom_in_button.set_sensitive(True)
            grow = False
        else:
            grow = True

        self.graphs.append(graph)
        self.vbox.add(graph)

        if grow:
            w, h = self.get_size()
            mh = self.get_max_height()
            if h < mh:
                gh = self.graphs[0].get_allocated_height()
                if gh == 1:
                    # XXX: There's no size allocation before the window is
                    # actually shown, so when we're adding multiple graphs
                    # initially we don't know how big to make them.  So pick a
                    # number, any number.
                    gh = 138
                h = min(mh, h + gh)
                self.resize(w, h)

    def get_min_height(self):
        return 250

    def get_max_height(self):
        screen = self.get_screen()
        return min(screen.get_monitor_geometry(n).height
                   for n in range(screen.get_n_monitors())) - 100

    def zoom_in(self, target):
        if self.zoom > 1.0:
            self.zoom *= 0.5
        if self.zoom == 1.0:
            self.zoom_in_button.set_sensitive(False)

    def zoom_out(self, target):
        self.zoom *= 2.0
        self.zoom_in_button.set_sensitive(True)

    def select_process(self, target):
        process_selector_dialog = ProcessSelector(self)
        if process_selector_dialog.run() == Gtk.ResponseType.OK:
            pid = process_selector_dialog.pid
            if pid is not None:
                # TODO: disable the Ok button if there's no selection
                self.watch_pid(pid)
        process_selector_dialog.destroy()

    def process_exited(self, *args):
        if self.exit_when_process_dies:
            if not any(g.alive for g in self.graphs):
                Gtk.main_quit()

    def show_graph_popup(self, widget, event):
        if event.button == Gdk.BUTTON_SECONDARY:
            self.graph_popup.selected_graph = widget
            self.graph_popup.popup(None, None, None, None, event.button, event.time)
            return True

    def remove_graph(self, action):
        graph = self.graph_popup.selected_graph
        self.graph_popup.selected_graph = None
        graph.stop()
        self.graphs.remove(graph)
        self.vbox.remove(graph)
        if not self.graphs:
            self.vbox.add(self.select_button)
            self.select_button.show_all()
            self.zoom_out_button.set_sensitive(False)
            self.zoom_in_button.set_sensitive(False)
        else:
            w, h = self.get_size()
            # XXX: these hardcoded numbers are icky, how can I get gtk to
            # compute them for me?
            desired_h = 112 + 138 * len(self.graphs)
            mh = self.get_max_height()
            h = min(mh, desired_h)
            self.resize(w, h)
        self.process_exited()


class ProcessSelector(Gtk.Dialog):

    use_header_bar = hasattr(Gtk.DialogFlags, 'USE_HEADER_BAR')

    class Column:
        types = (int, str, int, str, bool)
        PID, COMMAND, SIZE, SIZE_TEXT, MINE = range(len(types))

    def __init__(self, parent):
        kwargs = {}
        if self.use_header_bar:
            kwargs['use_header_bar'] = True
        super(ProcessSelector, self).__init__(
            title="Select a process", transient_for=parent,
            **kwargs)
        self.set_default_size(600, 400)
        self.set_border_width(6)
        self._init_buttons()

        self.store = Gtk.ListStore(*self.Column.types)
        self.filter_model = Gtk.TreeModelFilter(child_model=self.store)
        self.filter_model.set_visible_func(self.is_process_visible)
        self.sort_model = Gtk.TreeModelSort(model=self.filter_model)
        self.process_list = self._make_process_list(self.sort_model)
        self.process_list.connect("row_activated", self.select_process)

        self.show_all_checkbox = Gtk.CheckButton(
            label='Show processes belonging to all users')
        self.show_all_checkbox.connect('toggled', self.show_all_toggled)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.connect('search-changed', self.search)
        self.search_bar = self._make_search_bar(self.search_entry)
        self.search_button = self._make_search_button()
        self.search_button.bind_property(
            "active", self.search_bar, "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL)

        area = self.get_content_area()
        area.pack_start(self.search_bar,
                        expand=False, fill=False, padding=0)
        area.pack_start(_framed(_scrollable(self.process_list)),
                        expand=True, fill=True, padding=0)
        area.pack_start(self.show_all_checkbox,
                        expand=False, fill=False, padding=6)
        area.show_all()
        self.connect("key-press-event", self.on_key_press)
        GLib.idle_add(self.refresh_process_list)

    def _init_buttons(self):
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok_button = self.add_button("Select", Gtk.ResponseType.OK)
        ok_button.get_style_context().add_class("suggested-action")

    def _make_search_button(self):
        search_button = Gtk.ToggleButton()
        search_button.add(Gtk.Image.new_from_icon_name(
            "edit-find-symbolic", Gtk.IconSize.MENU))
        search_button.set_valign(Gtk.Align.CENTER)
        search_button.get_style_context().add_class("image-button")
        search_button.show_all()
        self.get_titlebar().pack_end(search_button)
        return search_button

    def _make_search_bar(self, entry):
        bar = Gtk.SearchBar()
        bar.add(entry)
        return bar

    def _make_process_list(self, model):
        process_list = Gtk.TreeView(model=model)
        process_list.set_search_column(self.Column.COMMAND)
        column = Gtk.TreeViewColumn(
            "PID", Gtk.CellRendererText(xalign=1.0),
            text=self.Column.PID)
        column.set_sort_column_id(self.Column.PID)
        process_list.append_column(column)
        column = Gtk.TreeViewColumn(
            "Command",
            Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END),
            text=self.Column.COMMAND)
        column.set_sort_column_id(self.Column.COMMAND)
        column.set_expand(True)
        process_list.append_column(column)
        column = Gtk.TreeViewColumn("Size", Gtk.CellRendererText(xalign=1.0),
                                    text=self.Column.SIZE_TEXT)
        column.set_sort_column_id(self.Column.SIZE)
        process_list.append_column(column)
        return process_list

    @property
    def pid(self):
        model, iter = self.process_list.get_selection().get_selected()
        if not iter:
            return None
        return model[iter][self.Column.PID]

    def on_key_press(self, widget, event):
        if (event.state & Gdk.ModifierType.CONTROL_MASK
                and Gdk.keyval_name(event.keyval) == 'f'):
            self.search_bar.set_search_mode(not self.search_bar.get_search_mode())
            return True
        if not self.search_entry.is_focus():
            if self.search_entry.im_context_filter_keypress(event):
                self.search_bar.set_search_mode(True)
                self.search_entry.grab_focus()
                length = self.search_entry.get_text_length()
                self.search_entry.select_region(length, length)
                return True
        return False

    def show_all_toggled(self, widget):
        self.filter_model.refilter()

    def search(self, widget):
        self.filter_model.refilter()

    def is_process_visible(self, model, iter, data):
        if not self.show_all_checkbox.get_active():
            if not model[iter][self.Column.MINE]:
                return False
        s = self.search_entry.get_text()
        if s:
            if s.isdigit() and int(s) == model[iter][self.Column.PID]:
                return True
            if s in model[iter][self.Column.COMMAND]:
                return True
            return False
        return True

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
            size_mb = format_size(size.virt)
            mine = (owner == my_uid)
            self.store.append([pid, cmdline, size.virt, size_mb, mine])


def main():
    parser = argparse.ArgumentParser(description="Graph process memory usage")
    parser.add_argument('command', nargs='*',
                        help='Command to execute')
    parser.add_argument('-p', '--pid', type=int, action='append',
                        help='Existing process to monitor')
    parser.add_argument('--self', action='store_true',
                        help='Watch the memory usage of memgraphinator itself')
    parser.add_argument('--exit-when-process-dies', action='store_true',
                        help='Exit when monitored process dies')
    args = parser.parse_args()
    if args.command and all(arg.isdigit() for arg in args.command):
        if args.pid is None:
            args.pid = []
        args.pid.extend(map(int, args.command))
        args.command = None

    start_from_zero = False
    child = None
    if args.command:
        start_from_zero = True
        try:
            child = subprocess.Popen(args.command)
            pids = [child.pid]
        except OSError as e:
            sys.exit("%s: %s" % (args.command[0], e))
    else:
        pids = args.pid or []
    try:
        win = MainWindow(exit_when_process_dies=args.exit_when_process_dies)
        if args.self:
            win.watch_pid(os.getpid(), start_from_zero=True)
        for pid in pids:
            win.watch_pid(pid, start_from_zero=start_from_zero)
        win.show_all()
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        Gtk.main()
    finally:
        if child and child.poll() is None:
            print("Killing child %d" % child.pid)
            child.terminate()
            timeout = 50  # 5 seconds
            while child.poll() is None and timeout:
                time.sleep(0.1)
                timeout -= 1
            if child.poll() is None:
                print("Killing child %d with SIGKILL" % child.pid)
                child.send_signal(9)
                child.wait()


if __name__ == '__main__':
    main()
