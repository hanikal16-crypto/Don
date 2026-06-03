"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  return n;
};

const state = { runId: null, source: null, agents: {} };

// --- Tiny markdown renderer (safe: escapes first, then formats) -------------

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inline(s) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function renderMarkdown(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  let inCode = false;
  let codeBuf = [];
  let listBuf = [];

  const flushList = () => {
    if (listBuf.length) {
      out.push("<ul>" + listBuf.map((t) => `<li>${inline(t)}</li>`).join("") + "</ul>");
      listBuf = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      if (inCode) {
        out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
        codeBuf = [];
        inCode = false;
      } else {
        flushList();
        inCode = true;
      }
      i++;
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      i++;
      continue;
    }

    // Tables: a header row followed by a |---| separator.
    if (line.includes("|") && (lines[i + 1] || "").match(/^\s*\|?[\s:|-]+\|[\s:|-]+$/)) {
      flushList();
      const parseRow = (r) =>
        r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
      const header = parseRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|")) {
        rows.push(parseRow(lines[i]));
        i++;
      }
      let t = "<table><thead><tr>";
      t += header.map((h) => `<th>${inline(h)}</th>`).join("");
      t += "</tr></thead><tbody>";
      for (const row of rows) {
        t += "<tr>" + row.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
      }
      t += "</tbody></table>";
      out.push(t);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i++;
      continue;
    }

    if (line.match(/^\s*[-*]\s+/)) {
      listBuf.push(line.replace(/^\s*[-*]\s+/, ""));
      i++;
      continue;
    }

    if (line.match(/^\s*---+\s*$/)) {
      flushList();
      out.push("<hr/>");
      i++;
      continue;
    }

    if (line.trim() === "") {
      flushList();
      i++;
      continue;
    }

    flushList();
    out.push(`<p>${inline(line)}</p>`);
    i++;
  }
  flushList();
  if (inCode) out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
  return out.join("\n");
}

// --- Agent roster -----------------------------------------------------------

async function loadAgents() {
  const data = await fetch("/api/agents").then((r) => r.json());
  renderGroup("#architects", data.architects);
  renderGroup("#engineers", data.engineers);
}

function renderGroup(sel, list) {
  const ul = $(sel);
  ul.innerHTML = "";
  for (const a of list) {
    const li = el("li");
    li.dataset.key = a.key;
    li.innerHTML = `
      <span class="emoji">${a.emoji}</span>
      <span class="who"><span class="title">${a.title}</span>
        <span class="remit">${a.remit}</span></span>
      <span class="state">idle</span>`;
    ul.appendChild(li);
    state.agents[a.key] = li;
  }
}

function setAgentState(key, cls, label) {
  const li = state.agents[key];
  if (!li) return;
  const badge = li.querySelector(".state");
  badge.className = "state " + cls;
  badge.textContent = label;
}

function resetAgents() {
  for (const key in state.agents) setAgentState(key, "", "idle");
}

// --- Activity log -----------------------------------------------------------

function log(message, cls) {
  const li = el("li", cls || "");
  li.textContent = message;
  $("#log").appendChild(li);
  $("#tab-log").scrollTop = $("#tab-log").scrollHeight;
}

// --- Run flow ---------------------------------------------------------------

async function startRun() {
  const spec = $("#spec").value.trim();
  if (!spec) {
    $("#hint").textContent = "Please enter a specification first.";
    return;
  }
  $("#run").disabled = true;
  $("#hint").textContent = "Assembling the team…";
  $("#log").innerHTML = "";
  $("#actions").classList.add("hidden");
  $("#tab-architecture").innerHTML = "";
  $("#tab-solution").innerHTML = "";
  $("#tab-files").innerHTML = "";
  resetAgents();
  showTab("log");

  const body = {
    spec,
    build: $("#build").checked,
    effort: $("#effort").value || null,
  };

  try {
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const { run_id } = await res.json();
    state.runId = run_id;
    listen(run_id);
  } catch (err) {
    $("#hint").textContent = "Error: " + err.message;
    $("#run").disabled = false;
  }
}

function listen(runId) {
  if (state.source) state.source.close();
  const src = new EventSource(`/api/runs/${runId}/events`);
  state.source = src;
  $("#hint").textContent = "The team is working — watch the Activity tab.";

  src.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "end") {
      src.close();
      finish(runId);
      return;
    }
    if (e.type === "phase") {
      log((e.phase === "done" ? "✓ " : "▶ ") + e.message, "phase");
    } else if (e.type === "agent") {
      if (e.phase === "start") {
        setAgentState(e.agent, "working", "working…");
        log("  " + (e.agent_meta?.emoji || "") + " " + e.message);
      } else {
        const extra = e.data && e.data.files ? ` (${e.data.files} files)` : "";
        setAgentState(e.agent, "done", "done");
        log("  ✅ " + e.message + extra, "done");
      }
    } else if (e.type === "files") {
      log("  📦 " + e.message);
    } else if (e.type === "error") {
      log(e.message, "error");
    } else if (e.type === "complete") {
      log("✓ " + e.message, "phase");
    }
  };

  src.onerror = () => {
    // EventSource auto-reconnects; the server replays buffered events.
  };
}

async function finish(runId) {
  $("#run").disabled = false;
  const info = await fetch(`/api/runs/${runId}`).then((r) => r.json());

  if (info.status === "failed") {
    $("#hint").textContent = "Run failed. See the Activity tab.";
    return;
  }
  $("#hint").textContent = info.cache_read_tokens
    ? `Done. Reused ${info.cache_read_tokens.toLocaleString()} cached tokens.`
    : "Done.";

  if (info.has_review) {
    const md = await fetch(`/api/runs/${runId}/result.md`).then((r) => r.text());
    $("#tab-architecture").innerHTML = renderMarkdown(md);
  }

  if (info.has_solution) {
    const md = await fetch(`/api/runs/${runId}/solution.md`).then((r) => r.text());
    $("#tab-solution").innerHTML = renderMarkdown(md);

    const files = (await fetch(`/api/runs/${runId}/files`).then((r) => r.json())).files;
    renderFiles(files);

    const dl = $("#dl-zip");
    dl.href = `/api/runs/${runId}/download.zip`;
    $("#actions").classList.remove("hidden");
    showTab("solution");
  } else {
    showTab("architecture");
  }
}

function renderFiles(files) {
  const body = $("#tab-files");
  if (!files || !files.length) {
    body.innerHTML = '<p class="empty">No files generated.</p>';
    return;
  }
  const rows = files
    .map(
      (f) =>
        `<tr><td>${escapeHtml(f.path)}</td><td class="size">${f.bytes.toLocaleString()} B</td></tr>`
    )
    .join("");
  body.innerHTML = `<table class="files-table"><tbody>${rows}</tbody></table>`;
}

// --- Tabs -------------------------------------------------------------------

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name)
  );
  document.querySelectorAll(".tab-body").forEach((b) =>
    b.classList.toggle("active", b.id === "tab-" + name)
  );
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => showTab(t.dataset.tab))
);

$("#run").addEventListener("click", startRun);
loadAgents();
