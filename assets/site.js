// Client-side helpers: mobile contents toggle, copy-on-click paragraph links,
// and the "go to" / search page backed by /model-rules.json.
(function () {
  var toc = document.querySelector(".toc");
  if (toc) {
    toc.addEventListener("click", function (e) {
      if (e.target === toc) toc.classList.toggle("open");
    });
  }

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.pnum");
    if (!a || !navigator.clipboard) return;
    var url = location.origin + location.pathname + a.getAttribute("href");
    navigator.clipboard.writeText(url).catch(function () {});
  });

  var results = document.getElementById("results");
  if (!results) return;

  var params = new URLSearchParams(location.search);
  var q = (params.get("q") || "").trim();
  var input = document.getElementById("q");
  var status = document.getElementById("status");
  if (input) input.value = q;
  if (!q) return;

  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function blockText(blocks) {
    return blocks.map(function (b) {
      if (b.type === "table") return b.header.join(" ") + " " + b.rows.map(function (r) { return r.join(" "); }).join(" ");
      return (b.label ? b.label + " " : "") + b.text.replace(/<[^>]+>/g, " ");
    }).join(" ");
  }
  function slug(s) {
    return s.normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  // Direct references: "3.2.6", "Article 3.2", "art. 5", "chapter 4".
  var ref = q.replace(/^(articles?|art\.?|paragraph|para\.?|chapter|ch\.?)\s*/i, "");
  var isChapter = /^(chapter|ch\.?)\s*\d+$/i.test(q);
  var m = ref.match(/^(\d+)(?:\.(\d+))?(?:\.(\d+))?\.?$/);

  fetch("/model-rules.json").then(function (r) { return r.json(); }).then(function (data) {
    var articles = [], defs = [];
    data.chapters.forEach(function (ch) {
      ch.articles.forEach(function (a) {
        articles.push(a);
        a.definitions.forEach(function (d) { defs.push(d); });
      });
    });

    if (m) {
      var art = m[2] ? m[1] + "." + m[2] : null;
      if (!art || isChapter) {
        if (data.chapters.some(function (c) { return String(c.number) === m[1]; })) {
          location.replace("/chapters/" + m[1]); return;
        }
      } else if (articles.some(function (a) { return a.id === art; })) {
        location.replace("/articles/" + art + (m[3] ? "#" + art + "." + m[3] : "")); return;
      }
    }
    var exact = defs.filter(function (d) { return d.term.toLowerCase() === q.toLowerCase() || d.id === slug(q); })[0];
    if (exact) { location.replace("/definitions#" + exact.id); return; }

    var words = q.toLowerCase().split(/\s+/).filter(Boolean);
    var hits = [];
    articles.forEach(function (a) {
      a.paragraphs.forEach(function (p) {
        hits.push({ url: "/articles/" + a.id + "#" + p.id, title: "Article " + p.id + " — " + a.title, text: blockText(p.blocks) });
      });
    });
    defs.forEach(function (d) {
      hits.push({ url: "/definitions#" + d.id, title: "Definition: " + d.term, text: blockText(d.blocks), term: d.term });
    });
    hits = hits.map(function (h) {
      var lower = h.text.toLowerCase(), score = 0;
      words.forEach(function (w) {
        var i = lower.indexOf(w);
        if (i < 0) score = -1e9; else score += 1 + lower.split(w).length;
      });
      if (h.term && h.term.toLowerCase().indexOf(q.toLowerCase()) >= 0) score += 50;
      return { h: h, score: score };
    }).filter(function (x) { return x.score > 0; }).sort(function (a, b) { return b.score - a.score; }).slice(0, 50);

    status.textContent = hits.length ? hits.length + (hits.length === 50 ? "+" : "") + " matches" : "No matches.";
    var re = new RegExp("(" + words.map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|") + ")", "gi");
    results.innerHTML = hits.map(function (x) {
      var t = x.h.text, i = t.toLowerCase().indexOf(words[0]);
      var snip = (i > 80 ? "…" : "") + t.slice(Math.max(0, i - 80), i + 220) + "…";
      return '<li><a href="' + x.h.url + '">' + esc(x.h.title) + '</a><div class="snip">' +
        esc(snip).replace(re, "<mark>$1</mark>") + "</div></li>";
    }).join("");
  });
})();
