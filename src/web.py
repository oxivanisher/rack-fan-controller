"""Status page + override API, built on microdot.

Reads/writes the same in-memory state main.py owns (a dict of FanGroup
objects and a get_status() callable) rather than maintaining its own copy.

microdot is not vendored in this repo — see README.md "Dependencies".
"""

from microdot import Microdot, Response
import microdot.microdot as _microdot_impl
import json

app = Microdot()
Response.default_content_type = "application/json"

# Populated by main.py before starting the server.
_fan_groups = {}
_get_status = None

# microdot dumps a full traceback for every request line/header it can't
# parse (handle_request's bare except). The common cause on a LAN device is
# a browser retrying https:// against this plain-http server before falling
# back - the TLS ClientHello has no newline, so it blows past max_readline
# and raises ValueError("line too long"). That's harmless and expected, so
# swallow just that case down to one line; anything else still gets the
# full traceback for debugging.
_orig_print_exception = _microdot_impl.print_exception


def _print_exception(exc):
    if isinstance(exc, ValueError) and str(exc) == "line too long":
        print("web: dropped an unparsable request line (likely a browser "
              "trying https:// against this http-only server) - retry with "
              "http://<host>")
        return
    _orig_print_exception(exc)


_microdot_impl.print_exception = _print_exception


def init(fan_groups, get_status_fn):
    global _fan_groups, _get_status
    _fan_groups = fan_groups
    _get_status = get_status_fn


@app.route("/status", methods=["GET"])
def status(request):
    return _get_status()


@app.route("/override", methods=["POST"])
def set_override(request):
    body = request.json
    group_name = body.get("group")
    duty = body.get("duty")
    duration_s = body.get("duration_s")

    if group_name not in _fan_groups:
        return {"error": "unknown group %s" % group_name}, 400
    if not isinstance(duty, (int, float)) or not (0 <= duty <= 100):
        return {"error": "duty must be 0-100"}, 400
    if not isinstance(duration_s, (int, float)) or duration_s <= 0:
        return {"error": "duration_s must be > 0"}, 400

    _fan_groups[group_name].set_override(duty, duration_s)
    return {"ok": True}


@app.route("/override/cancel", methods=["POST"])
def cancel_override(request):
    body = request.json
    group_name = body.get("group")
    if group_name not in _fan_groups:
        return {"error": "unknown group %s" % group_name}, 400
    _fan_groups[group_name].cancel_override()
    return {"ok": True}


@app.route("/", methods=["GET"])
def index(request):
    return Response(body=_PAGE_HTML, headers={"Content-Type": "text/html"})


# Minimal single-page UI: polls /status every 2s, posts overrides.
# Deliberately no external CSS/JS dependencies so it works standalone on the LAN.
_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rack Fan Controller</title>
<style>
  body { font-family: sans-serif; max-width: 480px; margin: 2em auto; padding: 0 1em; }
  .group { border: 1px solid #ccc; border-radius: 8px; padding: 1em; margin-bottom: 1em; }
  .group h2 { margin-top: 0; }
  .row { display: flex; justify-content: space-between; margin: 0.3em 0; }
  button { padding: 0.4em 0.8em; margin-right: 0.3em; }
  .override-badge { color: #b45309; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; }
  td, th { text-align: left; padding: 0.2em 0.4em; }
  .unconfigured { color: #b45309; }
  .configured { color: #6b7280; }
  code { font-size: 0.9em; }
</style>
</head>
<body>
<h1>Rack Fan Controller</h1>
<div class="row"><span>Rack temp</span><span id="rack_temp">-</span></div>
<div class="row"><span>Outside temp</span><span id="outside_temp">-</span></div>

<div id="groups"></div>

<div class="group">
  <h2>Detected 1-Wire sensors</h2>
  <p>Every DS18B20 seen on the bus, live. Unconfigured ROMs are highlighted
  — touch a physical sensor and watch which temp moves to identify it, then
  paste its ROM code into <code>config.json</code> under
  <code>sensors.rack</code> / <code>sensors.outside</code> and reboot.</p>
  <table>
    <thead><tr><th>ROM</th><th>Temp</th><th>Status</th></tr></thead>
    <tbody id="detected_sensors"></tbody>
  </table>
</div>

<script>
function fmtTemp(t) {
  return (t === null || t === undefined) ? '—' : t.toFixed(1) + ' C';
}

async function fetchStatus() {
  const res = await fetch('/status');
  const data = await res.json();
  document.getElementById('rack_temp').textContent = fmtTemp(data.rack_temp);
  document.getElementById('outside_temp').textContent = fmtTemp(data.outside_temp);

  const sensorsBody = document.getElementById('detected_sensors');
  sensorsBody.innerHTML = '';
  for (const s of (data.detected_sensors || [])) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${s.rom}</code></td>
      <td>${fmtTemp(s.temp)}</td>
      <td class="${s.configured ? 'configured' : 'unconfigured'}">${s.configured ? 'configured' : 'unassigned'}</td>
    `;
    sensorsBody.appendChild(tr);
  }

  const container = document.getElementById('groups');
  container.innerHTML = '';
  for (const [name, g] of Object.entries(data.groups)) {
    const div = document.createElement('div');
    div.className = 'group';
    const overrideText = g.override
      ? `<span class="override-badge">OVERRIDE ${g.override.duty}% (${g.override.expires_in_s}s left)</span>`
      : 'auto';
    div.innerHTML = `
      <h2>${name}</h2>
      <div class="row"><span>Duty</span><span>${g.duty}%</span></div>
      <div class="row"><span>RPM</span><span>${g.rpm.join(' / ')}</span></div>
      <div class="row"><span>Mode</span><span>${overrideText}</span></div>
      <div>
        <button onclick="setOverride('${name}', 0)">0%</button>
        <button onclick="setOverride('${name}', 50)">50%</button>
        <button onclick="setOverride('${name}', 100)">100%</button>
        <button onclick="cancelOverride('${name}')">Auto</button>
      </div>
    `;
    container.appendChild(div);
  }
}

async function setOverride(group, duty) {
  await fetch('/override', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({group, duty, duration_s: 600})
  });
  fetchStatus();
}

async function cancelOverride(group) {
  await fetch('/override/cancel', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({group})
  });
  fetchStatus();
}

fetchStatus();
setInterval(fetchStatus, 2000);
</script>
</body>
</html>
"""
