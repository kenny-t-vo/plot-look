New in 0.3.0: the app is one window holding every setting, Colour among them, with a progress bar and Stop; only Render starts a render. Pattern swatches now render evenly, where a fine rotated hatch used to turn to grey mush at the edge of one of the tiles a page is rendered in.

Plot look as an app for Mac and Windows, holding its own Python and poppler, so there is nothing to install and no terminal to use. Download the zip for your computer from the assets below:

- `mac-apple-silicon`: a Mac with an M1 or later chip
- `mac-intel`: a Mac with an Intel processor, on macOS 11 or later (About This Mac, in the Apple menu, shows both)
- `windows`: Windows 10 or 11

The apps aren't signed by Apple or Microsoft, so each system asks once before the first open.

**Mac.** Open the zip and move Plot Look into Applications, then open it. macOS says it can't verify the app: click Done, open System Settings, Privacy & Security, scroll down to the line saying Plot Look was blocked, click Open Anyway and confirm. On macOS 14 or earlier, Control-click the app instead, choose Open, then Open again. After that it opens like any other app. The first time it saves beside a drawing on the Desktop or in Documents or Downloads, macOS asks whether Plot Look may use that folder: allow it.

**Windows.** If the browser says the zip isn't commonly downloaded, choose Keep. Right-click the zip, choose Extract All, and open Plot Look.exe in the folder it makes. If Windows says it protected your PC, click More info, then Run anyway. Plot Look.exe needs the _internal folder beside it; to start it from the desktop, make a shortcut to it.

Drop PDFs on the app (or .ai files saved with PDF compatibility, or a folder of PDFs), or open it and click Add…, then pick a size and the other settings in its window and click Render. The window shows the render's progress and can stop it, and stays open for the next. The PNGs go beside each drawing unless Save to names a folder. Colour keeps a drawing's colours; untick it for the plotted grey. The [README](https://github.com/kenny-t-vo/plot-look#readme) says what the sizes and settings do.
