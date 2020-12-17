#!/bin/bash

mkdir -p ~/.local/share/applications/
pwdesc=$(pwd -P | sed 's_/_\\/_g')
cat uproot_browser.desktop | sed "s/Exec=browser.py/Exec=$pwdesc\/browser.py/" > ~/.local/share/applications/uproot_browser.desktop
chmod +x uproot_browser.py

