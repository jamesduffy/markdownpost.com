// Lists the device-only drafts of the last signed-in user (app.js records them in mdp:last-user and clears it at logout),
// so on a shared browser one person's drafts are never shown to another. See editor/src/drafts.js for the entry format.
(function () {
  var out = [];
  try {
    var user = localStorage.getItem("mdp:last-user");
    if (!user) return;
    var prefix = "mdp:" + user + ":draft:";
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (!k || k.indexOf(prefix) !== 0) continue;
      try {
        var d = JSON.parse(localStorage.getItem(k));
        if (d && !d.synced && (d.title || d.body)) out.push(d);
      } catch (e) {}
    }
  } catch (e) {
    return;
  }
  if (!out.length) return;
  out.sort(function (a, b) { return b.savedAt - a.savedAt; });
  var list = document.getElementById("local-draft-list");
  out.forEach(function (d) {
    var a = document.createElement("a");
    a.className = "more-card";
    a.href = d.postId ? d.editUrl || "/new/" : "/new/#draft=" + encodeURIComponent(d.key);
    var t = document.createElement("strong");
    t.textContent = d.title || "Untitled";
    var s = document.createElement("span");
    s.textContent = (d.failed ? "Couldn't save" : "Not synced yet") + " · " + (d.body || "").slice(0, 100);
    a.append(t, s);
    list.append(a);
  });
  document.getElementById("local-drafts").hidden = false;
})();
