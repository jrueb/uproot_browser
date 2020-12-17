#!/usr/bin/env python3

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio
import os
import awkward1 as awkward
import uproot4 as uproot
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from matplotlib.backends.backend_gtk3agg import (
        FigureCanvasGTK3Agg as FigureCanvas)
from matplotlib.backends.backend_gtk3 import (
    NavigationToolbar2GTK3 as NavigationToolbar)
from matplotlib.figure import Figure
import numpy as np
import argparse
import sys
from collections import Mapping


class Browser(Gtk.ApplicationWindow):

    COL_KEY = 0
    COL_VISIBLE = 1
    PAGE_PLOT = 0
    PAGE_INSPECT = 1

    def __init__(self, app, file=None):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.set_default_size(750, 600)
        self.set_border_width(10)

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
        self.filter_entry = Gtk.Entry()
        self.filter_entry.set_tooltip_text("Search for a specific key")
        self.filter_entry.set_placeholder_text("Filter")
        self.filter_entry.connect("changed", self.on_filter_entry_changed)
        box.pack_start(self.filter_entry, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(200, -1)
        box.pack_start(scroll, True, True, 0)

        self.treeview = Gtk.TreeView.new_with_model(self.filter)
        column = Gtk.TreeViewColumn("ROOT file", Gtk.CellRendererText(), text=self.COL_KEY)
        self.treeview.append_column(column)
        self.treeview.connect("row_activated", self.on_row_activated)
        scroll.add(self.treeview)

        self.notebook = Gtk.Notebook()
        paned.pack2(self.notebook, True, True)

        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        self.notebook.append_page(box, Gtk.Label.new("Plot"))
        self.notebook.child_set_property(box, "tab-expand", True)

        canvas = FigureCanvas(Figure(figsize=(5, 4)))
        box.pack_start(canvas, True, True, 0)
        self.plot_ax = canvas.figure.subplots()
        self.colorbar = None

        self.toolbar = NavigationToolbar(canvas, self)
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
        text = self.filter_entry.get_text()
        self.store.foreach(self.apply_filter_on_row, False)
        self.store.foreach(self.apply_filter_on_row, text)
        self.filter.refilter()

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

    def on_row_activated(self, tree_view, path, column):
        row = self.filter[path]
        key = row[self.COL_KEY]
        full_path = key
        while row.get_parent():
            row = row.get_parent()
            full_path = row[self.COL_KEY] + "/" + full_path
        try:
            obj = self.file[full_path]
            couldplot = self.plot(obj)
            self.inspect(key, obj)
            if not couldplot:
                self.notebook.set_current_page(self.PAGE_INSPECT)
        except ValueError as e:
            self.show_error("Unsupported object", str(e))
            raise

    def add_dir(self, directory, iter=None):
        for key in directory.keys(recursive=False):
            try:
                obj = directory[key]
            except ValueError:
                obj = None
            piter = self.store.append(iter, [key, True])
            if isinstance(obj, uproot.ReadOnlyDirectory):
                self.add_dir(obj, piter)
            elif hasattr(obj, "classname") and obj.classname == "TTree":
                self.add_tree(obj, piter)

    def add_tree(self, tree, iter):
        for key in tree.keys():
            self.store.append(iter, [key, True])

    def plot(self, obj):
        self.plot_ax.clear()
        if self.colorbar is not None:
            self.colorbar.remove()
            self.colorbar = None
        if not hasattr(obj, "classname"):
            canplot = False
        elif obj.classname in ["TGraph"]:
            self.plot_ax.plot(obj.all_members["fX"], obj.all_members["fY"])
            self.plot_ax.set_title(obj.all_members["fTitle"])
            canplot = True
        elif obj.classname in ["TGraphAsymmErrors"]:
            xerr = np.array([obj.all_members["fEXlow"], obj.all_members["fEXhigh"]])
            yerr = np.array([obj.all_members["fEYlow"], obj.all_members["fEYhigh"]])
            self.plot_ax.errorbar(x=obj.all_members["fX"], y=obj.all_members["fY"], xerr=xerr, yerr=yerr, linestyle="none")
            self.plot_ax.set_title(obj.all_members["fTitle"])
            canplot = True
        elif obj.classname in ["TH1D", "TH1F", "TH1I", "TH1S", "TH1C"]:
            # Ignore overflow
            edges = obj.edges()[1:-1]
            values, errors = obj.values_errors()
            values = values[1:-1]
            errors = errors[1:-1]
            centers = (edges[1:] + edges[:-1]) / 2
            widths = (edges[1:] - edges[:-1]) / 2
            self.plot_ax.errorbar(x=centers, y=values, xerr=widths, yerr=errors, linestyle="none")
            self.plot_ax.set_xlabel(obj.all_members["fXaxis"].all_members["fTitle"])
            self.plot_ax.set_ylabel(obj.all_members["fYaxis"].all_members["fTitle"])
            self.plot_ax.set_title(obj.all_members["fTitle"])
            canplot = True
        elif obj.classname in ["TH2D", "TH2F", "TH2I", "TH2S", "TH2C"]:
            # Ignore overflow
            edgesx = obj.edges(0)[1:-1]
            edgesy = obj.edges(1)[1:-1]
            x, y = np.meshgrid(edgesx, edgesy)
            values = obj.values()[1:-1, 1:-1]
            c = self.plot_ax.pcolormesh(x, y, values.T)
            self.plot_ax.set_xlabel(obj.all_members["fXaxis"].all_members["fTitle"])
            self.plot_ax.set_ylabel(obj.all_members["fYaxis"].all_members["fTitle"])
            self.plot_ax.set_title(obj.all_members["fTitle"])
            self.colorbar = self.plot_ax.figure.colorbar(c)
            self.colorbar.set_label(obj.all_members["fZaxis"].all_members["fTitle"])
            canplot = True
        elif obj.classname in ["TBranch"]:
            data = awkward.to_numpy(awkward.flatten(obj.array(), None))
            data = data[np.isfinite(data)]
            self.plot_ax.hist(data, bins=50)
            self.plot_ax.set_xlabel(obj.name)
            self.plot_ax.set_ylabel("Counts")
            canplot = True
        else:
            print(obj.classname)
            canplot = False
        self.plot_ax.figure.canvas.draw()
        # Remind the toolbar about the new axis limits
        self.toolbar.update()
        return canplot

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
            if response == Gtk.ResponseType.CANCEL:
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
