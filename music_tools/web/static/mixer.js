// The player: lanes, a shared playhead and time axis, the transport controls
// and, for a track set, the mixer strip. docs/plans/05-playback.md, 5b.
//
// One engine for one file and for eight: a lone file is a set of one. All the
// audio is `transport.js`; this is the page around it. No framework and no
// build step. The markup is server-rendered with a working <audio controls>
// per track inside, which is the whole thing with the JavaScript off — stacked
// and unsynchronised, and honest about it. This takes over when it runs.
//
// Speed and pitch are server renders (`/media/{id}/audio?speed=&semitones=`):
// moving either fetches every track again and swaps the buffers in at the same
// place in the tune. The slider is the exercise's speed, written back through
// POST data-speed-url. Gain, pan and mute are the track's own columns, written
// through PATCH /media/{id}; solo is a view and is not stored.
(function () {
  "use strict";

  var BUCKETS = 1000;

  // A set is played in mono at half the CD rate: decoded PCM is the budget,
  // and eight four-minute stems at 44.1 kHz stereo is around 680 MB. A lone
  // file keeps its stereo and its rate.
  var SET_RATE = 22050;
  var LONE_RATE = 44100;

  // Seconds between labels on the time axis: the first that leaves room.
  var STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300];

  var players = [];

  function clock(seconds) {
    var whole = Math.max(0, Math.floor(seconds));
    var rest = whole % 60;
    return Math.floor(whole / 60) + ":" + (rest < 10 ? "0" : "") + rest;
  }

  function init(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "1";

    var isSet = root.dataset.set === "1";
    var lanes = Array.prototype.slice.call(root.querySelectorAll(".track"));
    var axis = root.querySelector("canvas.axis");
    var playButton = root.querySelector("button.play");
    var time = root.querySelector("output.clock");
    var loop = root.querySelector(".loop input");
    var slider = root.querySelector(".speed input");
    var readout = root.querySelector(".speed output");
    var pitch = root.querySelector(".pitch select");
    var volume = root.querySelector(".volume input");
    var speedUrl = root.dataset.speedUrl;

    var problem = document.createElement("p");
    problem.className = "problem";
    problem.hidden = true;
    root.appendChild(problem);
    var status = document.createElement("p");
    status.className = "muted status";
    status.setAttribute("aria-live", "polite");
    root.appendChild(status);

    var transport = null;
    var known = 0; // the tune's length from the peaks, until the audio is in
    var span = null; // a dragged loop span, in tune seconds
    var frame = 0;
    var wanted = 0; // the latest load asked for; an older one that lands late is dropped
    // The range input clamps what it is given, so a row at 40% starts the
    // slider (and the render asked for) at its floor of 50%.
    slider.value = slider.disabled ? 1 : parseFloat(root.dataset.ratio) || 1;
    var speed = Math.round(parseFloat(slider.value) * 100) / 100;

    var player = { root: root, close: function () { if (transport) transport.close(); } };
    players.push(player);

    // Web Audio plays from here on: the fallback players go, before they
    // fetch anything more than their metadata.
    lanes.forEach(function (lane) {
      var audio = lane.querySelector("audio");
      if (audio) {
        audio.removeAttribute("src");
        audio.load();
        audio.remove();
      }
      lane.peaks = [];
      lane.strip = {
        mute: lane.querySelector(".mute input"),
        solo: lane.querySelector(".solo input"),
        gain: lane.querySelector(".gain input"),
        pan: lane.querySelector(".pan input")
      };
    });

    function say(message) {
      problem.textContent = message || "";
      problem.hidden = !message;
    }

    function length() {
      return transport ? transport.duration() : known;
    }

    function position() {
      return transport ? transport.position() : 0;
    }

    function mixOf(lane) {
      return {
        gain: parseFloat(lane.dataset.gain),
        pan: parseFloat(lane.dataset.pan),
        muted: lane.dataset.muted === "1"
      };
    }

    function urlFor(lane) {
      var query = [];
      if (speed !== 1) query.push("speed=" + speed);
      var semitones = parseInt(pitch.value, 10);
      if (semitones) query.push("semitones=" + semitones);
      if (isSet) query.push("mono=1");
      return lane.dataset.audioUrl + (query.length ? "?" + query.join("&") : "");
    }

    // Fetch and decode every track at the current speed and pitch, then hand
    // them to the transport: the first time as a load, after that as a swap
    // at the same place in the tune.
    function load() {
      var ask = ++wanted;
      var at = speed;
      status.textContent = transport ? "Rendering " + Math.round(at * 100) + "%…"
        : "Loading" + (isSet ? " 0 of " + lanes.length : "") + "…";
      Transport.decode(lanes.map(urlFor), {
        channels: isSet ? 1 : 2,
        rate: isSet ? SET_RATE : LONE_RATE,
        onprogress: function (done, total) {
          if (ask === wanted && !transport && isSet) {
            status.textContent = "Loading " + done + " of " + total + "…";
          }
        }
      }).then(function (buffers) {
        if (ask !== wanted) return;
        if (!transport) {
          var Context = window.AudioContext || window.webkitAudioContext;
          transport = new Transport(new Context());
          transport.onended = finished;
          transport.load(buffers, at, lanes.map(mixOf));
          transport.setVolume(parseFloat(volume.value));
          if (loop.checked) transport.setLoop(span || { start: 0, end: transport.duration() });
        } else {
          transport.swap(buffers, at);
        }
        playButton.disabled = false;
        status.textContent = "";
        say("");
        draw();
      }).catch(function (failed) {
        if (ask !== wanted) return;
        status.textContent = "";
        say(failed.message);
      });
    }

    function finished(drift) {
      playButton.textContent = "play";
      cancelAnimationFrame(frame);
      draw();
      // The drift check, for the checklist in the plan: how far apart the
      // tracks came to the end, measured on the transport's own clock.
      if (isSet) {
        status.textContent = "Played to the end: the tracks agreed within "
          + Math.round(drift.spread * 1000) + " ms.";
      }
      root.dataset.drift = drift.spread.toFixed(4);
    }

    function draw() {
      var total = length();
      var at = position();
      lanes.forEach(function (lane) {
        drawLane(lane.querySelector("canvas.wave"), lane.peaks, at, total);
      });
      if (axis) drawAxis(total);
      if (time) time.textContent = clock(at) + " / " + clock(Math.round(total));
    }

    function drawLane(canvas, peaks, at, total) {
      var ratio = window.devicePixelRatio || 1;
      var width = canvas.clientWidth;
      var height = canvas.clientHeight || 80;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      var ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      var style = getComputedStyle(canvas);
      var mid = height / 2;

      if (span && total > 0) {
        ctx.fillStyle = style.getPropertyValue("--loop") || "rgba(0, 0, 0, 0.08)";
        var left = (span.start / total) * width;
        ctx.fillRect(left, 0, (span.end / total) * width - left, height);
      }

      ctx.fillStyle = style.getPropertyValue("--wave") || style.color;
      for (var x = 0; x < width; x++) {
        var peak = peaks[Math.min(peaks.length - 1, Math.floor((x / width) * peaks.length))];
        if (!peak) continue;
        var top = mid - peak[1] * mid;
        var bottom = mid - peak[0] * mid;
        ctx.fillRect(x, top, 1, Math.max(1, bottom - top));
      }

      if (total > 0) {
        ctx.fillStyle = style.getPropertyValue("--playhead") || "#d33";
        ctx.fillRect(Math.round((at / total) * width), 0, 2, height);
      }
    }

    function drawAxis(total) {
      var ratio = window.devicePixelRatio || 1;
      var width = axis.clientWidth;
      var height = axis.clientHeight || 18;
      axis.width = Math.round(width * ratio);
      axis.height = Math.round(height * ratio);
      var ctx = axis.getContext("2d");
      ctx.scale(ratio, ratio);
      if (!(total > 0) || !width) return;
      var style = getComputedStyle(axis);
      var step = STEPS[STEPS.length - 1];
      for (var i = 0; i < STEPS.length; i++) {
        if ((STEPS[i] / total) * width >= 48) { step = STEPS[i]; break; }
      }
      ctx.fillStyle = style.color;
      ctx.font = "11px sans-serif";
      ctx.textBaseline = "top";
      for (var s = 0; s <= total; s += step) {
        var x = Math.round((s / total) * width);
        ctx.fillRect(x, 0, 1, 4);
        if (x + 30 <= width) ctx.fillText(clock(s), x + 2, 4);
      }
    }

    function tick() {
      draw();
      if (transport && transport.playing) frame = requestAnimationFrame(tick);
    }

    // Peaks are per track and drawn as they arrive; the audio is decoded
    // separately, so a waveform never waits on eight decodes.
    lanes.forEach(function (lane) {
      fetch(lane.dataset.peaksUrl + "?buckets=" + BUCKETS)
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.json();
        })
        .then(function (body) {
          lane.peaks = body.peaks;
          known = Math.max(known, body.duration);
          draw();
        })
        .catch(function () {
          say("Could not draw a waveform; the audio still plays.");
        });
    });

    // Click to seek, drag to choose a span to loop. A click outside the span
    // lets go of it.
    lanes.forEach(function (lane) {
      var canvas = lane.querySelector("canvas.wave");
      var from = null;
      function at(event) {
        var box = canvas.getBoundingClientRect();
        return Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) * length();
      }
      canvas.addEventListener("mousedown", function (event) {
        from = { x: event.clientX, t: at(event) };
      });
      canvas.addEventListener("mouseup", function (event) {
        if (!from || !transport) { from = null; return; }
        var to = at(event);
        if (Math.abs(event.clientX - from.x) < 4) {
          if (span && (to < span.start || to >= span.end)) {
            span = null;
            transport.setLoop(loop.checked ? { start: 0, end: length() } : null);
          }
          transport.seek(to);
        } else {
          span = { start: Math.min(from.t, to), end: Math.max(from.t, to) };
          loop.checked = true;
          transport.setLoop(span);
          transport.seek(span.start);
        }
        from = null;
        draw();
      });
    });

    playButton.disabled = true;
    playButton.addEventListener("click", function () {
      if (!transport) return;
      if (transport.playing) {
        transport.pause();
        playButton.textContent = "play";
        cancelAnimationFrame(frame);
        draw();
      } else {
        transport.play();
        playButton.textContent = "pause";
        status.textContent = "";
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(tick);
      }
    });

    loop.addEventListener("change", function () {
      if (!transport) return;
      transport.setLoop(loop.checked ? span || { start: 0, end: length() } : null);
      draw();
    });

    volume.addEventListener("input", function () {
      if (transport) transport.setVolume(parseFloat(volume.value));
    });

    slider.addEventListener("input", function () {
      readout.textContent = Math.round(parseFloat(slider.value) * 100) + "%";
    });
    slider.addEventListener("change", function () {
      speed = Math.round(parseFloat(slider.value) * 100) / 100;
      load();
      var body = new URLSearchParams({ ratio: slider.value });
      fetch(speedUrl, { method: "POST", body: body })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.json();
        })
        .then(function (answer) { readout.textContent = answer.text; })
        .catch(function () { say("The speed could not be saved."); });
    });

    pitch.addEventListener("change", load);

    // The strip. Moves are heard at once; gain, pan and mute are saved when
    // a control is let go of, solo never.
    lanes.forEach(function (lane, i) {
      var strip = lane.strip;
      if (!strip.gain) return;
      strip.gain.addEventListener("input", function () {
        if (transport) transport.setGain(i, parseFloat(strip.gain.value));
      });
      strip.pan.addEventListener("input", function () {
        if (transport) transport.setPan(i, parseFloat(strip.pan.value));
      });
      strip.mute.addEventListener("change", function () {
        if (transport) transport.setMuted(i, strip.mute.checked);
        save(lane);
      });
      strip.solo.addEventListener("change", function () {
        if (transport) transport.setSolo(i, strip.solo.checked);
      });
      strip.gain.addEventListener("change", function () { save(lane); });
      strip.pan.addEventListener("change", function () { save(lane); });
    });

    function save(lane) {
      var strip = lane.strip;
      lane.dataset.gain = strip.gain.value;
      lane.dataset.pan = strip.pan.value;
      lane.dataset.muted = strip.mute.checked ? "1" : "0";
      var values = { gain: strip.gain.value, pan: strip.pan.value };
      if (strip.mute.checked) values.muted = "on";
      // On the running card the attachment list shows the same columns, so it
      // is redrawn from the answer; elsewhere the answer is not needed.
      var list = document.getElementById("now-media-list");
      if (window.htmx && list) {
        htmx.ajax("PATCH", lane.dataset.describeUrl, {
          target: "#now-media-list", swap: "outerHTML", values: values
        });
      } else {
        fetch(lane.dataset.describeUrl, {
          method: "PATCH", body: new URLSearchParams(values),
          headers: { "HX-Request": "true" }
        }).catch(function () { say("The mix could not be saved."); });
      }
    }

    // A gain, pan or mute typed into the attachment list is the same column:
    // the strip and the transport follow it.
    player.follow = function () {
      lanes.forEach(function (lane, i) {
        var id = lane.dataset.id;
        var gain = document.getElementById("media-" + id + "-gain");
        var pan = document.getElementById("media-" + id + "-pan");
        var muted = document.getElementById("media-" + id + "-muted");
        var strip = lane.strip;
        if (!gain || !strip.gain) return;
        var g = parseFloat(gain.value), p = parseFloat(pan.value);
        if (!isNaN(g) && g !== parseFloat(strip.gain.value)) {
          strip.gain.value = g;
          if (transport) transport.setGain(i, g);
        }
        if (!isNaN(p) && p !== parseFloat(strip.pan.value)) {
          strip.pan.value = p;
          if (transport) transport.setPan(i, p);
        }
        if (muted.checked !== strip.mute.checked) {
          strip.mute.checked = muted.checked;
          if (transport) transport.setMuted(i, muted.checked);
        }
      });
    };

    window.addEventListener("resize", draw);
    load();
  }

  function scan() {
    // A card swapped out takes its transport with it: close the context, or
    // the tune plays on with nothing on the page to stop it.
    players = players.filter(function (player) {
      if (player.root.isConnected) return true;
      player.close();
      return false;
    });
    document.querySelectorAll(".player").forEach(init);
    players.forEach(function (player) { if (player.follow) player.follow(); });
  }

  // HTMX swaps the card in when an exercise is started, so look again after
  // every settle as well as on load.
  document.addEventListener("DOMContentLoaded", scan);
  document.addEventListener("htmx:afterSettle", scan);
})();
