# Uproot Browser
A very simple GTK application to browse the contents of ROOT files.

## Installation
Requires Python3 and the Python packages `uproot`, `awkward`, `matplotlib` and `PyGObject`.

`PyGObject` is preinstalled on many GNU/Linux distributions such as Ubuntu. For other OS please see https://pygobject.readthedocs.io/en/latest/getting_started.html

The other python packages can simply be installed with Pip

> python3 -m pip install awkward uproot matplotlib

If you're on Linux you can add the starter to your menu for quick access

> ./install_starter.sh


## Running

It is recommended to run this application locally instead of running it through an SSH tunnel. To access remote ROOT files, you can mount their directories using for example sshfs. On GNU/Linux this can be done with

>mkdir -p local_directory; sshfs username@ssh_server:/path/to/remote/file local_directory

where you have to adjust `local_directory`, `username`, `ssh_server` and `/path/to/remote/file` according to your needs.

Simply start the application with

> python3 uproot_browser.py
