// review.html's only script. Reads the "plan" and "decisions-skeleton"
// JSON blocks review.py embedded, adds field editing on top of the
// server-rendered markup, and exports decisions.json against them - no
// server, no network request but the CAA thumbnails already in the page.
(function () {
  "use strict";

  var plan = JSON.parse(document.getElementById("plan").textContent);
  var skeleton = JSON.parse(document.getElementById("decisions-skeleton").textContent);

  var albumsByKey = {};
  plan.albums.forEach(function (a) { albumsByKey[a.source] = a; });

  function albumSection(key) {
    var nodes = document.querySelectorAll("[data-album]");
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute("data-album") === key) { return nodes[i]; }
    }
    return null;
  }

  // A CSS attribute selector's quoted value only needs its own quote and a
  // backslash escaped; album keys are file paths, not CSS identifiers, so
  // CSS.escape (built for the latter) would mangle the slashes instead.
  function quote(value) {
    return value.replace(/[\\"]/g, "\\$&");
  }

  // review.py renders an album-level field once, with no data-position,
  // when every position agreed on it; a track-scoped field, or one the
  // positions disagreed on, gets one input per position instead. This must
  // read the two cases the same way review.py chose to render them: a
  // position-specific control wins where one exists, and its absence means
  // "every position shares the wide one".
  function currentValues(section, field, position) {
    var narrow = section.querySelectorAll(
      '[data-field="' + quote(field) + '"][data-position="' + quote(position) + '"]'
    );
    var controls = narrow.length
      ? narrow
      : section.querySelectorAll('[data-field="' + quote(field) + '"]:not([data-position])');
    return Array.prototype.map.call(controls, function (c) { return c.value; });
  }

  function arraysEqual(a, b) {
    if (a.length !== b.length) { return false; }
    for (var i = 0; i < a.length; i++) { if (a[i] !== b[i]) { return false; } }
    return true;
  }

  function editsForAlbum(album, section) {
    var fields = album.fields || {};
    var edits = JSON.parse(JSON.stringify(album.edits || {}));
    Object.keys(fields).sort().forEach(function (position) {
      Object.keys(fields[position]).sort().forEach(function (field) {
        var original = fields[position][field];
        var now = currentValues(section, field, position);
        if (now.length === 0 || arraysEqual(original, now)) { return; }
        edits[position] = edits[position] || {};
        edits[position][field] = now;
      });
    });
    return edits;
  }

  function gameChoice(section, fallback) {
    var checked = section.querySelector('input[type="radio"][name^="game-"]:checked');
    return checked ? checked.value : (fallback || null);
  }

  // `errors` collects one line per album the export cannot honestly
  // represent, rather than quietly downgrading it to skip: the command
  // reading this file back would reject it whole for exactly these (a
  // missing game choice on a game album's accept, an empty repoint), so
  // catching them here saves the owner a round trip.
  function heldDecision(album, errors) {
    var section = albumSection(album.source);
    var actionInput = section.querySelector('input[name="action-' + quote(album.source) + '"]:checked');
    var action = actionInput ? actionInput.value : "skip";
    if (action === "accept") {
      var candidate = section.querySelector('input[name="candidate-' + quote(album.source) + '"]:checked');
      if (!candidate) {
        errors.push(album.source + ": choose a candidate release");
        return { action: "skip" };
      }
      var out = { action: "accept", release_id: candidate.value, edits: editsForAlbum(album, section), game: null };
      if (album.game_choice) {
        out.game = gameChoice(section, album.game);
        if (!out.game) { errors.push(album.source + ": choose video game music, soundtrack or neither"); }
      }
      return out;
    }
    if (action === "repoint") {
      var box = section.querySelector("[data-repoint]");
      var value = box ? box.value.trim() : "";
      if (!value) {
        errors.push(album.source + ": enter a MusicBrainz release URL or MBID, or choose skip");
        return { action: "skip" };
      }
      return { action: "repoint", release: value };
    }
    return { action: "skip" };
  }

  function autoDecision(album, errors) {
    var section = albumSection(album.source);
    var edits = editsForAlbum(album, section);
    var game = album.game_choice ? gameChoice(section, album.game) : null;
    var alreadyFolded = album.decision === "accept";
    if (!alreadyFolded && Object.keys(edits).length === 0 && !game) { return null; }
    if (album.game_choice && !game) {
      errors.push(album.source + ": choose video game music, soundtrack or neither");
    }
    return { action: "accept", release_id: album.release_id, edits: edits, game: game };
  }

  function buildDecisions(errors) {
    var albums = {};
    Object.keys(skeleton.albums).forEach(function (key) {
      albums[key] = heldDecision(albumsByKey[key], errors);
    });
    plan.albums.forEach(function (a) {
      if (a.state !== "auto") { return; }
      var decision = autoDecision(a, errors);
      if (decision) { albums[a.source] = decision; }
    });
    return { job: skeleton.job, albums: albums };
  }

  function download() {
    var errors = [];
    var decisions = buildDecisions(errors);
    if (errors.length) {
      alert("Fix these before exporting:\n" + errors.join("\n"));
      return;
    }
    var data = JSON.stringify(decisions, null, 1);
    var blob = new Blob([data], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "decisions.json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  var button = document.getElementById("export");
  if (button) { button.addEventListener("click", download); }
})();
