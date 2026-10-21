import os

app = defines.get("app")
app_name = os.path.basename(app) if app else "RT.app"

files = [app] if app else []
symlinks = {"Applications": "/Applications"}

# dmgbuild esegue questo file con exec(): __file__ non esiste, la cartella arriva da build_app.py.
here = defines["dir"]
background = os.path.join(here, "background.png")
icon = os.path.join(os.path.dirname(here), "icons", "rt.icns")

window_rect = ((200, 120), (660, 400))
icon_size = 128

icon_locations = {
    app_name: (160, 150),
    "Applications": (500, 150),
}

format = "UDZO"
volume_name = "RT"
show_status_bar = False
show_toolbar = False
show_sidebar = False
