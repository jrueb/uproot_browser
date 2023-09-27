#!/usr/bin/env python3

import os
import time
import threading
from functools import partial
import queue
import awkward as ak
import uproot
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from matplotlib.backends.backend_gtk3agg import (
        FigureCanvasGTK3Agg as FigureCanvas)
from matplotlib.backends.backend_gtk3 import (
    NavigationToolbar2GTK3 as NavigationToolbar)
from matplotlib.figure import Figure
import numpy as np
import sys
from collections.abc import Mapping
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, Gdk, GLib  # noqa: E402


class Browser(Gtk.ApplicationWindow):

    COL_KEY = 0
    COL_VISIBLE = 1
    PAGE_PLOT = 0
    PAGE_INSPECT = 1

    NUM_TBRANCH_FASTLOAD = 100000

    def __init__(self, app, file=None):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.set_default_size(750, 600)
        self.set_border_width(10)

        self.load_queue = queue.Queue()
        self.load_thread = threading.Thread(target=self.load_if_available)
        self.load_thread.daemon = True
        self.load_thread.start()

        self.store = Gtk.TreeStore(str, bool)
        self.file = file

        self.headerbar = Gtk.HeaderBar()
        self.headerbar.set_show_close_button(True)
        self.headerbar.set_title("Browser")
        open_button = Gtk.Button.new_from_icon_name("document-open-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        open_button.set_tooltip_text("Open a file")
        open_button.connect("clicked", self.on_open_button_clicked)
        self.headerbar.pack_start(open_button)
        self.set_titlebar(self.headerbar)

        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.add(paned)

        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 5)
        box.set_margin_right(5)
        paned.pack1(box, False, False)

        self.filter = self.store.filter_new()
        self.paths_to_expand = []
        self.filter.set_visible_column(self.COL_VISIBLE)
        self.filter_entry = Gtk.SearchEntry()
        self.filter_entry.set_tooltip_text("Search for a specific key")
        self.filter_entry.set_placeholder_text("Filter")
        self.filter_needs_update = False
        self.filter_last_update = time.time()
        self.filter_entry.connect("changed", self.on_filter_entry_changed)
        GLib.timeout_add(250, self.update_filter)
        box.pack_start(self.filter_entry, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(200, -1)
        box.pack_start(scroll, True, True, 0)

        self.treepopup = Gtk.Menu()
        self.treepopup.plot_item = Gtk.MenuItem("Plot")
        self.treepopup.plot_item.connect("activate", self.on_popup_plot_item_activated)
        self.treepopup.append(self.treepopup.plot_item)
        self.treepopup.plotsame_item = Gtk.MenuItem("Plot in same figure")
        self.treepopup.plotsame_item.connect("activate", self.on_popup_plotsame_item_activated)
        self.treepopup.append(self.treepopup.plotsame_item)
        self.treepopup.inspect_item = Gtk.MenuItem("Inspect")
        self.treepopup.inspect_item.connect("activate", self.on_popup_inspect_item_activated)
        self.treepopup.append(self.treepopup.inspect_item)

        self.treeview = Gtk.TreeView.new_with_model(self.filter)
        column = Gtk.TreeViewColumn("ROOT file", Gtk.CellRendererText(), text=self.COL_KEY)
        self.treeview.append_column(column)
        self.treeview.connect("row_activated", self.on_row_activated)
        self.treeview.connect("button-press-event", self.on_button_press_event_tree)
        scroll.add(self.treeview)

        self.notebook = Gtk.Notebook()
        paned.pack2(self.notebook, True, True)

        overlay = Gtk.Overlay.new()
        tab_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        self.plot_spinner = Gtk.Spinner()
        tab_box.pack_start(self.plot_spinner, False, False, 0)
        tab_box.pack_start(Gtk.Label.new("Plot"), True, True, 0)
        tab_box.show_all()
        self.notebook.append_page(overlay, tab_box)
        self.notebook.child_set_property(overlay, "tab-expand", True)

        self.plot_infobar = Gtk.InfoBar.new()
        self.plot_infobar.set_show_close_button(True)
        self.plot_infobar_cbs = []
        self.plot_infobar.connect("response", self.plot_infobar_response)
        self.plot_infobar.set_property("valign", Gtk.Align.START)
        self.plot_infobar.set_revealed(False)
        self.plot_infobar.label = Gtk.Label.new("")
        self.plot_infobar.get_content_area().add(self.plot_infobar.label)
        overlay.add_overlay(self.plot_infobar)

        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        overlay.add(box)
        self.plot_canvas = FigureCanvas(Figure(figsize=(5, 4)))
        box.pack_start(self.plot_canvas, True, True, 0)
        self.plot_ax = self.plot_canvas.figure.subplots()
        self.colorbar = None

        self.toolbar = NavigationToolbar(self.plot_canvas, self)
        box.pack_start(self.toolbar, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        self.notebook.append_page(scroll, Gtk.Label.new("Inspect"))
        self.notebook.child_set_property(scroll, "tab-expand", True)

        self.inspect_store = Gtk.TreeStore(str, str)
        inspector = Gtk.TreeView.new_with_model(self.inspect_store)
        inspector.append_column(Gtk.TreeViewColumn("Key", Gtk.CellRendererText(), text=0))
        inspector.append_column(Gtk.TreeViewColumn("Value", Gtk.CellRendererText(), text=1))
        scroll.add(inspector)

        self.open(self.file)

    def on_open_button_clicked(self, button):
        self.open()

    def on_filter_entry_changed(self, editable):
        self.filter_last_update = time.time()
        self.filter_needs_update = True

    def update_filter(self):
        if not self.filter_needs_update or time.time() - self.filter_last_update < 1:
            return True
        self.filter_needs_update = False
        text = self.filter_entry.get_text()
        self.store.foreach(self.apply_filter_on_row, False)
        self.store.foreach(self.apply_filter_on_row, text)
        self.filter.refilter()
        return True

    def apply_filter_on_row(self, model, path, iter, text):
        if text == "" or text is None:
            self.store.set_value(iter, self.COL_VISIBLE, True)
        elif not text:
            self.store.set_value(iter, self.COL_VISIBLE, False)
        elif text.lower() in model[iter][self.COL_KEY].lower():
            self.store.set_value(iter, self.COL_VISIBLE, True)
            parent = model.iter_parent(iter)
            while parent:
                self.store.set_value(parent, self.COL_VISIBLE, True)
                parent = model.iter_parent(parent)
            self.make_subtree_visible(model, iter)

    def make_subtree_visible(self, model, iter):
        for i in range(model.iter_n_children(iter)):
            subtree = model.iter_nth_child(iter, i)
            if model[subtree][self.COL_VISIBLE]:
                continue
            self.store.set_value(subtree, self.COL_VISIBLE, True)
            self.make_subtree_visible(model, subtree)

    def get_full_path(self, path):
        row = self.filter[path]
        key = row[self.COL_KEY]
        full_path = key
        while row.get_parent():
            row = row.get_parent()
            full_path = row[self.COL_KEY] + "/" + full_path
        return full_path, key

    def on_row_activated(self, tree_view, path, column):
        full_path, key = self.get_full_path(path)
        try:
            obj = self.file[full_path]
            couldplot = self.plot(obj)
            self.inspect(key, obj)
            if not couldplot:
                self.notebook.set_current_page(self.PAGE_INSPECT)
        except (ValueError, uproot.deserialization.DeserializationError) as e:
            self.show_error("Unsupported object", str(e))
            raise

    def get_path_capabilities(self, path):
        full_path, key = self.get_full_path(path)
        if self.file.classname_of(full_path.rsplit("/", 1)[0]) == "TTree":
            classname = "TBranch"
        else:
            classname = self.file.classname_of(full_path)
        plot = classname in (
            "TGraph", "TGraphErrors", "TGraphAsymmErrors", "TH1D", "TH1F",
            "TH1I", "TH1S", "TH1C", "TH2D", "TH2F", "TH2I", "TH2S", "TH2C",
            "TBranch"
        )
        plotsame = classname in (
            "TGraph", "TGraphErrors", "TGraphAsymmErrors", "TH1D", "TH1F",
            "TH1I", "TH1S", "TH1C", "TBranch"
        )
        inspect = True

        return plot, plotsame, inspect

    def on_popup_plot_item_activated(self, menu_item):
        self.plot(self.file[self.get_full_path(self.treepopup.last_path)[0]])
        self.notebook.set_current_page(self.PAGE_PLOT)

    def on_popup_plotsame_item_activated(self, menu_item):
        self.plot(self.file[self.get_full_path(self.treepopup.last_path)[0]], False)
        self.notebook.set_current_page(self.PAGE_PLOT)

    def on_popup_inspect_item_activated(self, menu_item):
        full_path, key = self.get_full_path(self.treepopup.last_path)
        self.inspect(key, self.file[full_path])
        self.notebook.set_current_page(self.PAGE_INSPECT)

    def on_button_press_event_tree(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            path = self.treeview.get_path_at_pos(int(event.x), int(event.y))[0]
            self.treepopup.last_path = path
            canplot, canplotsame, caninspect = self.get_path_capabilities(path)
            self.treepopup.plot_item.set_sensitive(canplot)
            self.treepopup.plotsame_item.set_sensitive(canplotsame)
            self.treepopup.inspect_item.set_sensitive(caninspect)
            self.treepopup.popup(None, None, None, None, event.button, event.time)
            self.treepopup.show_all()

    def add_dir(self, directory, iter=None):
        for key, classname in directory.iterclassnames(recursive=False):
            piter = self.store.append(iter, [key, True])
            if classname == "TDirectory":
                self.add_dir(directory[key], piter)
            elif classname == "TTree":
                self.add_tree(directory[key], piter)

    def add_tree(self, tree, iter):
        for key in tree.keys():
            self.store.append(iter, [key, True])

    def plot(self, obj, clear=True):
        self.plot_canvas.hide()
        self.plot_spinner.start()
        if clear:
            self.plot_ax.clear()
        if self.colorbar is not None:
            self.colorbar.remove()
            self.colorbar = None
        canplot = True
        should_update = True
        if not hasattr(obj, "classname"):
            canplot = False
        elif obj.classname in ["TGraph"]:
            self.plot_ax.plot(obj.all_members["fX"], obj.all_members["fY"])
            self.plot_ax.set_title(obj.all_members["fTitle"])
        elif obj.classname in ["TGraphErrors", "TGraphAsymmErrors"]:
            if "Asymm" in obj.classname:
                xerr = np.array([obj.all_members["fEXlow"], obj.all_members["fEXhigh"]])
                yerr = np.array([obj.all_members["fEYlow"], obj.all_members["fEYhigh"]])
            else:
                xerr = obj.all_members["fEX"]
                yerr = obj.all_members["fEY"]
            self.plot_ax.errorbar(x=obj.all_members["fX"], y=obj.all_members["fY"], xerr=xerr, yerr=yerr, linestyle="none")
            self.plot_ax.set_title(obj.all_members["fTitle"])
        elif obj.classname in ["TH1D", "TH1F", "TH1I", "TH1S", "TH1C"]:
            edges = obj.axis().edges()
            values = obj.values()
            errors = obj.variances() ** .5
            centers = (edges[1:] + edges[:-1]) / 2
            widths = (edges[1:] - edges[:-1]) / 2
            self.plot_ax.errorbar(x=centers, y=values, xerr=widths, yerr=errors, linestyle="none")
            self.plot_ax.set_xlabel(obj.all_members["fXaxis"].all_members["fTitle"])
            self.plot_ax.set_ylabel(obj.all_members["fYaxis"].all_members["fTitle"])
            self.plot_ax.set_title(obj.all_members["fTitle"])
        elif obj.classname in ["TH2D", "TH2F", "TH2I", "TH2S", "TH2C"]:
            edgesx = obj.axis(0).edges()
            edgesy = obj.axis(1).edges()
            x, y = np.meshgrid(edgesx, edgesy)
            values = obj.values()
            c = self.plot_ax.pcolormesh(x, y, values.T)
            self.plot_ax.set_xlabel(obj.all_members["fXaxis"].all_members["fTitle"])
            self.plot_ax.set_ylabel(obj.all_members["fYaxis"].all_members["fTitle"])
            self.plot_ax.set_title(obj.all_members["fTitle"])
            self.colorbar = self.plot_ax.figure.colorbar(c)
            self.colorbar.set_label(obj.all_members["fZaxis"].all_members["fTitle"])
        elif obj.classname in ["TBranch"]:
            self.load_queue.put((obj, {"entry_stop": self.NUM_TBRANCH_FASTLOAD}, self.finish_tbranch_plot))
            should_update = False
        else:
            print(obj.classname)
            canplot = False
        if should_update:
            self.update_plot_tab()
        return canplot

    def update_plot_tab(self):
        self.plot_canvas.figure.tight_layout()
        self.plot_canvas.draw()
        # Remind the toolbar about the new axis limits
        self.toolbar.update()
        if self.load_queue.empty():
            self.plot_spinner.stop()
        self.plot_canvas.show()

    def load_if_available(self):
        while True:
            obj, array_kwargs, cb = self.load_queue.get()
            data = obj.array(**array_kwargs)
            data = np.asarray(ak.flatten(data, None))
            data = data[np.isfinite(data)]
            self.load_queue.task_done()
            Gdk.threads_add_idle(0, cb, obj, array_kwargs, data)

    def finish_tbranch_plot(self, obj, array_kwargs, data):
        if data.dtype == bool:
            data = data.astype(int)
        self.plot_ax.hist(data, bins=50)
        self.plot_ax.set_xlabel(obj.name)
        self.plot_ax.set_ylabel("Counts")
        self.update_plot_tab()
        if "entry_stop" in array_kwargs and array_kwargs["entry_stop"] < obj.num_entries:
            self.show_plot_info_message(
                f"Only showing {array_kwargs['entry_stop']} out of {obj.num_entries} rows",
                {"Load all": partial(self.plot_entire_tbranch, obj)})

    def plot_entire_tbranch(self, obj):
        self.plot_canvas.hide()
        self.plot_spinner.start()
        self.plot_ax.clear()
        if self.colorbar is not None:
            self.colorbar.remove()
            self.colorbar = None
        self.load_queue.put((obj, {}, self.finish_tbranch_plot))

    def show_plot_info_message(self, text, buttons):
        self.plot_infobar.label.set_text(text)
        buttonbox = self.plot_infobar.get_action_area()
        for button in buttonbox.get_children():
            buttonbox.remove(button)
        self.plot_infobar_cbs = []
        for i, (label, callback) in enumerate(buttons.items()):
            self.plot_infobar.add_button(label, i)
            self.plot_infobar_cbs.append(callback)
        self.plot_infobar.show_all()
        self.plot_infobar.set_revealed(True)

    def plot_infobar_response(self, widget, response):
        self.plot_infobar.set_revealed(False)
        if response >= 0:
            self.plot_infobar_cbs[response]()

    def inspect(self, key, obj):
        def make_str(s):
            if isinstance(s, str):
                return f"'{s}'"
            else:
                return str(s)

        def add_members(iter, obj):
            if hasattr(obj, "classname") and obj.classname in ("THashList", "TList", "TObjArray"):
                obj = {**obj.all_members, **{str(i): obj[i] for i in range(len(obj))}}
            elif hasattr(obj, "classname") and obj.classname.startswith("TArray"):
                obj = {**obj.all_members, "data": np.array(obj)}
            elif hasattr(obj, "all_members"):
                obj = obj.all_members
            elif isinstance(obj, list):
                obj = dict(zip(range(len(obj)), obj))
            if isinstance(obj, Mapping):
                for key, value in obj.items():
                    subiter = self.inspect_store.append(iter, [key, make_str(value)])
                    add_members(subiter, value)
        self.inspect_store.clear()
        iter = self.inspect_store.append(None, [key, make_str(obj)])
        add_members(iter, obj)

    def show_error(self, text, secondary_text=None):
        dialog = Gtk.MessageDialog(
            parent=self, secondary_text=self, flags=Gtk.DialogFlags.MODAL,
            type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            message_format=text)
        if secondary_text is not None:
            dialog.format_secondary_text(secondary_text)
        dialog.run()
        dialog.destroy()

    def clear(self):
        self.store.clear()
        self.plot_ax.clear()
        self.inspect_store.clear()

    def open(self, path=None):
        if path is None:
            dialog = Gtk.FileChooserDialog(
                title="Please choose a file", parent=self, action=Gtk.FileChooserAction.OPEN, flags=Gtk.DialogFlags.MODAL)
            dialog.add_buttons(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
            filter = Gtk.FileFilter()
            filter.set_name("ROOT files")
            filter.add_pattern("*.root")
            dialog.add_filter(filter)
            filter = Gtk.FileFilter()
            filter.set_name("Any files")
            filter.add_pattern("*")
            dialog.add_filter(filter)
            response = dialog.run()
            if response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.DELETE_EVENT):
                dialog.destroy()
                return
            path = dialog.get_filename()
            dialog.destroy()
        self.clear()
        try:
            file = uproot.open(path)
        except Exception as e:
            self.show_error("Error opening file", str(e))
        else:
            self.file = file
            self.add_dir(self.file)
            self.headerbar.set_title(os.path.basename(path))
            self.headerbar.set_subtitle(os.path.dirname(os.path.realpath(path)))


class BrowserApplication(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.custom_exit_status = 0

    def do_activate(self):
        win = Browser(self)
        win.show_all()

    def do_open(self, files, nfiles, hint):
        file = files[0].get_path()
        try:
            handle = uproot.open(file)
        except FileNotFoundError as e:
            self.custom_exit_status = 1
            raise e from None
        handle.close()
        win = Browser(self, file)
        win.show_all()

    def do_startup(self):
        Gtk.Application.do_startup(self)


if __name__ == "__main__":
    app = BrowserApplication()
    exit_status = app.run(sys.argv)
    exit_status = exit_status if exit_status != 0 else app.custom_exit_status
    sys.exit(exit_status)
