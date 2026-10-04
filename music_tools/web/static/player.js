// The player for a lone audio or video file: a waveform drawn from
// server-computed peaks, a playhead, click to seek, a loop toggle, a speed
// slider and a semitone control. docs/plans/05-playback.md, 5a.
//
// No framework and no build step. The markup is server-rendered with a working
// <audio controls> inside; this takes the controls over when it runs, so with
// the JavaScript off the card is still a player.
//
// Speed is `playbackRate` with `preservesPitch`, written back to the exercise
// through POST data-speed-url. Pitch is a server render: changing it swaps the
// audio source for `?semitones=N` and resumes where it was.
(function () {
  "use strict";

  var BUCKETS = 1000;

  function init(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = "1";

    var audio = root.querySelector("audio");
    var canvas = root.querySelector("canvas.wave");
    var playButton = root.querySelector("button.play");
    var loop = root.querySelector(".loop input");
    var slider = root.querySelector(".speed input");
    var readout = root.querySelector(".speed output");
    var pitch = root.querySelector(".pitch select");
    var audioUrl = root.dataset.audioUrl;
    var speedUrl = root.dataset.speedUrl;

    var peaks = [];
    var duration = 0;
    var frame = 0;
    var problem = document.createElement("p");
    problem.className = "problem";
    problem.hidden = true;
    root.appendChild(problem);

    audio.removeAttribute("controls");
    audio.preservesPitch = true;
    audio.mozPreservesPitch = true;
    audio.webkitPreservesPitch = true;
    slider.value = root.dataset.ratio;
    applyRate();

    function say(message) {
      problem.textContent = message || "";
      problem.hidden = !message;
    }

    function applyRate() {
      audio.playbackRate = parseFloat(slider.value);
    }

    function length() {
      return audio.duration > 0 && isFinite(audio.duration) ? audio.duration : duration;
    }

    function draw() {
      var ratio = window.devicePixelRatio || 1;
      var width = canvas.clientWidth;
      var height = canvas.clientHeight || 80;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      var ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      var style = getComputedStyle(canvas);
      var mid = height / 2;

      ctx.fillStyle = style.getPropertyValue("--wave") || style.color;
      for (var x = 0; x < width; x++) {
        var peak = peaks[Math.min(peaks.length - 1, Math.floor((x / width) * peaks.length))];
        if (!peak) continue;
        var top = mid - peak[1] * mid;
        var bottom = mid - peak[0] * mid;
        ctx.fillRect(x, top, 1, Math.max(1, bottom - top));
      }

      var span = length();
      if (span > 0) {
        ctx.fillStyle = style.getPropertyValue("--playhead") || "#d33";
        ctx.fillRect(Math.round((audio.currentTime / span) * width), 0, 2, height);
      }
    }

    function tick() {
      draw();
      if (!audio.paused) frame = requestAnimationFrame(tick);
    }

    function seekFrom(event) {
      var span = length();
      if (!span) return;
      var box = canvas.getBoundingClientRect();
      var fraction = (event.clientX - box.left) / box.width;
      audio.currentTime = Math.max(0, Math.min(1, fraction)) * span;
      draw();
    }

    fetch(root.dataset.peaksUrl + "?buckets=" + BUCKETS)
      .then(function (response) {
        if (!response.ok) throw new Error(response.status);
        return response.json();
      })
      .then(function (body) {
        peaks = body.peaks;
        duration = body.duration;
        draw();
      })
      .catch(function () {
        say("Could not draw the waveform; the audio still plays.");
      });

    canvas.addEventListener("click", seekFrom);
    playButton.addEventListener("click", function () {
      if (audio.paused) audio.play(); else audio.pause();
    });
    audio.addEventListener("play", function () {
      playButton.textContent = "pause";
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(tick);
    });
    audio.addEventListener("pause", function () {
      playButton.textContent = "play";
      cancelAnimationFrame(frame);
      draw();
    });
    audio.addEventListener("seeked", draw);
    audio.addEventListener("timeupdate", function () {
      if (audio.paused) draw();
    });
    audio.addEventListener("error", function () {
      // The file route's 409 names the path; the element only knows it failed.
      fetch(audio.currentSrc || audioUrl).then(function (response) {
        return response.json().catch(function () { return {}; });
      }).then(function (body) {
        say(body.detail || "The audio could not be played.");
      });
    });
    window.addEventListener("resize", draw);

    loop.addEventListener("change", function () {
      audio.loop = loop.checked;
    });

    slider.addEventListener("input", function () {
      applyRate();
      var percent = Math.round(parseFloat(slider.value) * 100);
      readout.textContent = percent + "%";
    });
    slider.addEventListener("change", function () {
      var body = new URLSearchParams({ ratio: slider.value });
      fetch(speedUrl, { method: "POST", body: body })
        .then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.json();
        })
        .then(function (answer) {
          readout.textContent = answer.text;
          say("");
        })
        .catch(function () {
          say("The speed could not be saved.");
        });
    });

    if (pitch) {
      pitch.addEventListener("change", function () {
        var semitones = parseInt(pitch.value, 10);
        var at = audio.currentTime;
        var wasPlaying = !audio.paused;
        pitch.disabled = true;
        say(semitones ? "Rendering…" : "");
        audio.addEventListener("loadedmetadata", function resume() {
          audio.removeEventListener("loadedmetadata", resume);
          audio.currentTime = at;
          applyRate();
          pitch.disabled = false;
          say("");
          if (wasPlaying) audio.play();
        });
        audio.src = audioUrl + (semitones ? "?semitones=" + semitones : "");
        audio.load();
      });
    }
  }

  function scan(scope) {
    (scope || document).querySelectorAll(".player").forEach(init);
  }

  // HTMX swaps the card in when an exercise is started, so look again after
  // every settle as well as on load.
  document.addEventListener("DOMContentLoaded", function () { scan(); });
  document.addEventListener("htmx:afterSettle", function (event) { scan(); });
})();
