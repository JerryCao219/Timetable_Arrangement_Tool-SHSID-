/* SHSID Timetable front-end: renders window.DATA produced by solver.py */
(function () {
  const D = window.DATA;
  const DAYS = [1, 2, 3, 4, 5];
  const PERIODS = [1, 2, 3, 4, 5, 6, 7];
  const FRI_MAX = 5;

  const state = { kind: "student", week: "odd", id: null };

  // ------------------------------------------------------------- indexing
  const students = Object.fromEntries(D.students.map(s => [s.id, s]));
  const teachers = Object.fromEntries(D.teachers.map(t => [t.id, t]));
  const tname = id => (teachers[id] ? teachers[id].name : id);

  const byStudent = {};   // sid -> [{week,day,period,...}]
  const byTeacher = {};
  for (const sec of D.sections) {
    for (const m of sec.meetings) {
      const cell = {
        week: m.week, day: m.day, period: m.period, room: m.room,
        double: m.double, subject: sec.subject, level: sec.level,
        secId: sec.id, size: sec.size, teacher: sec.teacher,
      };
      for (const sid of sec.students) {
        (byStudent[sid] = byStudent[sid] || []).push(cell);
      }
      (byTeacher[sec.teacher] = byTeacher[sec.teacher] || [])
        .push({ ...cell, students: sec.size });
    }
  }

  // -------------------------------------------------------------- examples
  const exWrap = document.getElementById("examples");
  function renderExamples() {
    const list = D.examples.filter(e => e.kind === state.kind);
    document.getElementById("exCount").textContent =
      `(${list.length} featured ${state.kind} timetables)`;
    exWrap.innerHTML = "";
    for (const ex of list) {
      const b = document.createElement("button");
      b.innerHTML = `${ex.name}<span class="tag">${ex.label}</span>`;
      b.title = ex.why;
      b.onclick = () => selectPerson(ex.kind, ex.id);
      exWrap.appendChild(b);
    }
  }

  // ------------------------------------------------------- browse-all list
  const browseAll = document.getElementById("browseAll");
  document.getElementById("browseToggle").addEventListener("click", () => {
    browseAll.classList.toggle("hidden");
  });
  function renderBrowseAll() {
    browseAll.innerHTML = "";
    if (state.kind === "student") {
      const byBand = {};
      for (const s of D.students) {
        (byBand[s.band] = byBand[s.band] || []).push(s);
      }
      for (const band of Object.keys(byBand).sort()) {
        const h = document.createElement("h3");
        h.textContent = `Grade ${band.slice(0, -1)} · Band ${band.slice(-1)}`;
        browseAll.appendChild(h);
        const row = document.createElement("div");
        row.className = "roster";
        for (const s of byBand[band]) {
          const b = document.createElement("button");
          b.textContent = s.name;
          b.onclick = () => selectPerson("student", s.id);
          row.appendChild(b);
        }
        browseAll.appendChild(row);
      }
    } else {
      const bySubj = {};
      for (const t of D.teachers) {
        (bySubj[t.main] = bySubj[t.main] || []).push(t);
      }
      for (const subj of Object.keys(bySubj).sort()) {
        const h = document.createElement("h3");
        h.textContent = subj;
        browseAll.appendChild(h);
        const row = document.createElement("div");
        row.className = "roster";
        for (const t of bySubj[subj]) {
          const b = document.createElement("button");
          b.textContent = t.name;
          b.onclick = () => selectPerson("teacher", t.id);
          row.appendChild(b);
        }
        browseAll.appendChild(row);
      }
    }
  }

  // -------------------------------------------------------------- controls
  const search = document.getElementById("search");
  const datalist = document.getElementById("people");
  let nameToId = {};
  function refreshList() {
    const items = state.kind === "student" ? D.students : D.teachers;
    nameToId = {};
    for (const p of items) {
      if (!(p.name in nameToId)) nameToId[p.name] = p.id;
    }
    // search shows the plain name only - no ID, no course details
    datalist.innerHTML = Object.keys(nameToId)
      .map(n => `<option value="${n}"></option>`).join("");
    search.placeholder = state.kind === "student"
      ? "Search a student by name…" : "Search a teacher by name…";
    search.value = "";
  }
  search.addEventListener("change", () => {
    const id = nameToId[search.value.trim()];
    if (id) selectPerson(state.kind, id);
  });
  document.getElementById("kindSeg").addEventListener("click", e => {
    if (e.target.dataset.kind) {
      state.kind = e.target.dataset.kind;
      setSeg("kindSeg", "kind", state.kind);
      state.id = null; refreshList(); renderExamples(); renderBrowseAll();
      render();
    }
  });
  document.getElementById("weekSeg").addEventListener("click", e => {
    if (e.target.dataset.week) {
      state.week = e.target.dataset.week;
      setSeg("weekSeg", "week", state.week);
      render();
    }
  });
  function setSeg(id, key, val) {
    for (const b of document.getElementById(id).children) {
      b.classList.toggle("on", b.dataset[key] === val);
    }
  }
  function selectPerson(kind, id) {
    state.kind = kind; state.id = id;
    setSeg("kindSeg", "kind", kind);
    const p = kind === "student" ? students[id] : teachers[id];
    if (p) search.value = p.name;
    renderExamples();
    render();
  }

  // ---------------------------------------------------------------- render
  const FIXED_LABEL = { PE: "PE", CAS: "CAS", Optional: "Optional" };

  function render() {
    const card = document.getElementById("personCard");
    const grid = document.getElementById("grid");
    if (!state.id) { card.classList.add("hidden"); grid.classList.add("hidden");
      return; }
    const isStu = state.kind === "student";
    const p = isStu ? students[state.id] : teachers[state.id];
    const cells = (isStu ? byStudent : byTeacher)[state.id] || [];
    const mine = cells.filter(c => c.week === state.week ||
      c.week === "both");

    // person summary card
    let meta;
    if (isStu) {
      const secOf = {};
      for (const sec of D.sections) {
        if (sec.students.includes(state.id)) secOf[sec.subject] = sec;
      }
      const courses = Object.values(secOf)
        .map(s => `${s.subject}${s.level ? " " + s.level : ""}`).sort();
      meta = `<span class="meta">Grade <b>${p.grade}</b> · Band <b>${p.band}</b></span>
        <span class="meta">${courses.length} courses: ${courses.join(" · ")}</span>`;
    } else {
      const st = D.teacherStats.weeklyHours[state.id] || 0;
      const daily = (D.teacherStats.daily[state.id] || {})[state.week] || {};
      const load = DAYS.map(d => daily[String(d)] || 0)
        .map((h, i) => `${D.dayNames[String(i + 1)]} ${h}h`).join(" · ");
      meta = `<span class="meta">Subjects: <b>${(p.subjects || []).join(", ")}</b></span>
        <span class="meta">Load <b>${st} h/wk</b> — ${load}</span>`;
    }
    card.innerHTML = `<h2>${p.name}</h2>${meta}`;
    card.classList.remove("hidden");

    // grid lookup
    const at = {};
    for (const c of mine) at[`${c.day}-${c.period}`] = c;

    document.getElementById("ttHead").innerHTML =
      `<th class="time">Period</th>` +
      DAYS.map(d => `<th>${D.dayNames[String(d)]}</th>`).join("");

    const rows = [];
    for (const per of PERIODS) {
      const tds = [`<td class="period">P${per}<br>${D.periodTimes[String(per)]}</td>`];
      for (const d of DAYS) {
        if (d === 5 && per > FRI_MAX) { tds.push("<td></td>"); continue; }
        const c = at[`${d}-${per}`];
        if (!c) { tds.push('<td class="cell empty"></td>'); continue; }
        const cls = ["cell"];
        if (c.double) cls.push("double");
        if (isWeekDep(c)) cls.push("weekdep");
        if (FIXED_LABEL[c.subject]) cls.push("fixed");
        const lvl = c.level ? ` <span class="det">${c.level}</span>` : "";
        const detail = isStu
          ? `<span class="det">Room ${c.room} · ${esc(tname(c.teacher))}</span>`
          : `<span class="det">Room ${c.room} · ${c.students} students</span>`;
        const wk = isWeekDep(c) && c.week !== "both"
          ? `<span class="det">${c.week}-week only</span>` : "";
        tds.push(`<td class="${cls.join(" ")}">
          <span class="subj">${esc(c.subject)}${lvl}</span>${detail}${wk}</td>`);
      }
      // lunch marker between P4 and P5
      rows.push(`<tr>${tds.join("")}</tr>`);
      if (per === 4) {
        rows.push(`<tr><td class="period">Lunch</td>${
          DAYS.map(() => '<td class="cell lunch">Lunch break</td>').join("")
        }</tr>`);
      }
    }
    document.getElementById("ttBody").innerHTML = rows.join("");
    grid.classList.remove("hidden");
  }

  function isWeekDep(c) {
    // week-dependent if the section meets at this (day, period) in only
    // one of the two weeks (CAS odd-only, filler double even-only)
    const sec = D.sections.find(s => s.id === c.secId);
    const weeks = new Set(sec.meetings
      .filter(m => m.day === c.day && m.period === c.period)
      .map(m => m.week));
    return weeks.size === 1;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, ch =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  }

  refreshList();
  renderBrowseAll();
  // open the first featured example by default
  if (D.examples.length) selectPerson(D.examples[0].kind, D.examples[0].id);
})();
