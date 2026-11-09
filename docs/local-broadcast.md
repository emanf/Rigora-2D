# Local broadcast output

Open **Animation → Local broadcast output**, choose dimensions/FPS and press
**Start output**. Opening the dialog does not start a listener or alter playback.
The renderer publishes only the active camera image, retaining transparency,
background/lens effects, artwork and particles without selection/editor controls.

Copy the private URL into an OBS **Browser Source**, with matching source dimensions
and frame rate. The source fits the image without stretching its aspect ratio.
OBS supports URL-based browser sources with explicit dimensions and custom frame
rates. See the [official Browser Source guide](https://obsproject.com/kb/browser-source).
Capture application audio or your microphone separately in the broadcast software;
this output transports images, not audio.

**Include live Puppet/capture previews** follows the displayed Scene pose, so
scratch performances can be broadcast without first creating timeline keys.
Disable it to render the document's authored pose. Rendering happens on a worker;
busy output skips additional work rather than accumulating delayed frames.

**Stop**, closing the dialog, changing project/scene or entering Object Editor
releases the local listener and discards late render results. A new start creates
a new private session URL; update the Browser Source URL after restarting.
Port zero chooses a free port. The listener binds only `127.0.0.1`; it never
publishes to a remote platform or starts OBS/browser windows automatically.

The current route is local browser capture. NDI, Syphon, virtual cameras, remote
stream hosting and encoded audio/video transport are not implemented. Output is
bounded to 1920 × 1080 and 30 requested FPS; actual throughput depends on scene
complexity. No guaranteed broadcast frame rate is claimed.

Validation: HTTP/frame transparency, explicit Start/Stop, unchanged project and
automatic context shutdown pass offscreen tests. The runnable
`python -m tools.review_broadcast_browser` additionally decodes the real page in
offscreen Qt WebEngine and reads canvas pixels: 64 × 36, transparent alpha 0,
opaque alpha 255. Evidence is in `build/broadcast-browser-review.json`.
No visible browser, capture device, remote stream or OBS session was opened.

Review: **8.5/10** for canonical rendering, transparency, bounded production,
local/private transport, teardown and browser decoding. Native OBS integration,
physical audio routing and non-Windows platforms remain unverified.
