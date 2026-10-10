// The transport: one AudioContext, one clock, every track locked to it.
// docs/plans/05-playback.md, 5b.
//
// No DOM in here, so the scheduling reads on its own; `mixer.js` is the page.
//
// Several <audio> elements each run their own clock, and between stems of one
// recording the gap is audible as comb filtering within seconds. Here every
// track is an AudioBufferSourceNode started by `start(when, offset)` against
// the same context time with the same offset, so they are sample-locked for as
// long as they play. Seek stops every source and starts them all again at the
// new offset; a loop is the same loopStart / loopEnd on all of them, which
// keeps the lock across the seam.
//
// Speed is not playbackRate (that moves the pitch): the server renders each
// track at the speed wanted and `swap` puts the new buffers in at the same
// place in the tune. So there are two timelines. Buffer seconds are what the
// sources play; tune seconds are the original file's, which is what the page
// shows and seeks in. `stretch` is the speed the buffers were rendered at:
// tune = buffer * stretch.
(function (global) {
  "use strict";

  // How far ahead a start is scheduled, so every source's start lands on the
  // same render quantum rather than on whichever one the call happened in.
  var LEAD = 0.05;

  // The time constant of a gain move: fast enough to feel instant,
  // slow enough not to click.
  var SMOOTH = 0.01;

  function Transport(ctx) {
    this.ctx = ctx;
    this.master = ctx.createGain();
    this.master.connect(ctx.destination);
    this.tracks = [];
    this.stretch = 1;
    this.playing = false;
    this.offset = 0; // buffer seconds: where the current run started, or paused
    this.t0 = 0; // context time the current run started at
    this.loop = null; // {start, end} in tune seconds, or null
    this.run = 0; // a source's `ended` from an earlier run is not this run's
    this.ends = [];
    this.onended = null;
  }

  // The tracks and their mix, once: `buffers` rendered at `stretch`, `mix` an
  // array of {gain, muted}. Each is source → gain → master.
  Transport.prototype.load = function (buffers, stretch, mix) {
    var ctx = this.ctx;
    var master = this.master;
    this.stop();
    this.tracks.forEach(function (track) { track.gain.disconnect(); });
    this.tracks = buffers.map(function (buffer, i) {
      var gain = ctx.createGain();
      gain.connect(master);
      var wanted = mix[i] || {};
      return {
        buffer: buffer,
        gain: gain,
        level: wanted.gain == null ? 1 : wanted.gain,
        muted: !!wanted.muted,
        soloed: false,
        source: null
      };
    });
    this.stretch = stretch;
    this.offset = 0;
    this.applyMix(true);
  };

  // New buffers for the same tracks — another speed or pitch — at the same
  // place in the tune, playing if it was playing.
  Transport.prototype.swap = function (buffers, stretch) {
    var at = this.position();
    var wasPlaying = this.playing;
    this.stop();
    this.tracks.forEach(function (track, i) { track.buffer = buffers[i]; });
    this.stretch = stretch;
    this.offset = this.toBuffer(at);
    if (wasPlaying) this.start();
  };

  // The length of the tune in tune seconds: the longest track's.
  Transport.prototype.duration = function () {
    var longest = 0;
    this.tracks.forEach(function (track) {
      longest = Math.max(longest, track.buffer.duration);
    });
    return longest * this.stretch;
  };

  Transport.prototype.toBuffer = function (tune) {
    var end = this.duration() / this.stretch;
    return Math.max(0, Math.min(end, tune / this.stretch));
  };

  // Where the playhead is, in tune seconds, read off the one clock.
  Transport.prototype.position = function () {
    return this.bufferPosition() * this.stretch;
  };

  Transport.prototype.bufferPosition = function () {
    if (!this.playing) return this.offset;
    var at = this.offset + Math.max(0, this.ctx.currentTime - this.t0);
    var span = this.bufferLoop();
    if (span && at >= span.end) {
      at = span.start + ((at - span.end) % (span.end - span.start));
    }
    return Math.min(at, this.duration() / this.stretch);
  };

  Transport.prototype.bufferLoop = function () {
    if (!this.loop) return null;
    return { start: this.loop.start / this.stretch, end: this.loop.end / this.stretch };
  };

  Transport.prototype.play = function () {
    if (this.playing || !this.tracks.length) return;
    if (this.ctx.state === "suspended") this.ctx.resume();
    if (this.offset >= this.duration() / this.stretch - 0.001) this.offset = 0;
    this.start();
  };

  Transport.prototype.pause = function () {
    if (!this.playing) return;
    this.offset = this.bufferPosition();
    this.stop();
  };

  Transport.prototype.seek = function (tune) {
    var wasPlaying = this.playing;
    this.stop();
    this.offset = this.toBuffer(tune);
    if (wasPlaying) this.start();
  };

  // Loop `span` ({start, end} in tune seconds), or stop looping with null.
  // A playing transport restarts where it is, so the position arithmetic and
  // the sources agree about where the seam is.
  Transport.prototype.setLoop = function (span) {
    var at = this.bufferPosition();
    var wasPlaying = this.playing;
    this.stop();
    this.loop = span && span.end > span.start ? span : null;
    this.offset = at;
    if (wasPlaying) this.start();
  };

  // Every source started at one context time with one offset: the lock.
  Transport.prototype.start = function () {
    var self = this;
    var span = this.bufferLoop();
    if (span && (this.offset < span.start || this.offset >= span.end)) {
      this.offset = span.start;
    }
    var when = this.ctx.currentTime + LEAD;
    var run = ++this.run;
    this.ends = [];
    this.tracks.forEach(function (track) {
      var source = self.ctx.createBufferSource();
      source.buffer = track.buffer;
      if (span) {
        source.loop = true;
        source.loopStart = span.start;
        source.loopEnd = span.end;
      }
      source.connect(track.gain);
      source.onended = function () { self.ended(run, track); };
      source.start(when, Math.min(self.offset, track.buffer.duration));
      track.source = source;
    });
    this.t0 = when;
    this.playing = true;
  };

  Transport.prototype.stop = function () {
    this.run++;
    this.tracks.forEach(function (track) {
      if (!track.source) return;
      track.source.onended = null;
      try { track.source.stop(); } catch (e) { /* never started */ }
      track.source.disconnect();
      track.source = null;
    });
    this.playing = false;
  };

  // The drift check. A source that played to its end should have taken
  // exactly its remaining length of context time; how far each one is off,
  // and how far apart they are, says whether they stayed on the one clock.
  // The `ended` event is dispatched on the main thread, so a few
  // milliseconds of the spread are the event loop, not the audio.
  Transport.prototype.ended = function (run, track) {
    if (run !== this.run) return;
    var expected = Math.max(0, track.buffer.duration - this.offset);
    this.ends.push(this.ctx.currentTime - this.t0 - expected);
    if (this.ends.length < this.tracks.length) return;
    var low = Math.min.apply(null, this.ends);
    var high = Math.max.apply(null, this.ends);
    this.offset = this.duration() / this.stretch;
    this.stop();
    if (this.onended) this.onended({ spread: high - low, late: high });
  };

  Transport.prototype.setGain = function (i, gain) {
    this.tracks[i].level = gain;
    this.applyMix();
  };

  Transport.prototype.setMuted = function (i, muted) {
    this.tracks[i].muted = muted;
    this.applyMix();
  };

  Transport.prototype.setSolo = function (i, soloed) {
    this.tracks[i].soloed = soloed;
    this.applyMix();
  };

  Transport.prototype.setVolume = function (volume) {
    this.master.gain.setTargetAtTime(volume, this.ctx.currentTime, SMOOTH);
  };

  // Solo is a view over mute: with any track soloed only the soloed ones are
  // heard, whatever their mute says; with none, mute decides.
  Transport.prototype.audible = function (track) {
    var soloing = this.tracks.some(function (other) { return other.soloed; });
    return soloing ? track.soloed : !track.muted;
  };

  Transport.prototype.applyMix = function (now) {
    var self = this;
    this.tracks.forEach(function (track) {
      var target = self.audible(track) ? track.level : 0;
      if (now) track.gain.gain.value = target;
      else track.gain.gain.setTargetAtTime(target, self.ctx.currentTime, SMOOTH);
    });
  };

  Transport.prototype.close = function () {
    this.stop();
    if (this.ctx.close) this.ctx.close();
  };

  // Fetch and decode every url, reporting progress as each one lands.
  //
  // Decoded audio is the budget: float32 PCM, about 350 KB a second for a
  // stereo track at 44.1 kHz. A set is asked for in mono and decoded at
  // `rate` through an OfflineAudioContext, which decodes at its own rate —
  // an AudioContext would decode at the output device's, typically 48 kHz.
  // Resolves to the buffers in url order; rejects with the server's own
  // sentence when it gave one (a 409 names the missing file).
  Transport.decode = function (urls, options) {
    var Offline = global.OfflineAudioContext || global.webkitOfflineAudioContext;
    var decoder = new Offline(options.channels || 2, 1, options.rate || 44100);
    var done = 0;
    return Promise.all(urls.map(function (url) {
      return global.fetch(url)
        .then(function (response) {
          if (response.ok) return response.arrayBuffer();
          return response.json().catch(function () { return {}; }).then(function (body) {
            throw new Error(body.detail || "the audio could not be loaded");
          });
        })
        .then(function (bytes) {
          return new Promise(function (resolve, reject) {
            decoder.decodeAudioData(bytes, resolve, function () {
              reject(new Error("the audio could not be decoded"));
            });
          });
        })
        .then(function (buffer) {
          done++;
          if (options.onprogress) options.onprogress(done, urls.length);
          return buffer;
        });
    }));
  };

  global.Transport = Transport;
})(this);
