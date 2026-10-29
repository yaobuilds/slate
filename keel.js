(function () {
  const LANES = 5;
  const BAR_H = 32;
  const BAR_CROSS_MS = 7000;
  const BOB_CYCLE_MS = 3200;
  const BOB_AMP = 4;
  const SPAWN_GAP = 220;

  const stage = document.getElementById("keel-stage");
  const field = document.getElementById("keel-field");
  const barsRoot = document.getElementById("keel-bars");
  const ring = document.getElementById("keel-ring");
  const scoreEl = document.getElementById("keel-score");
  const padLeft = document.getElementById("keel-pad-left");
  const padRight = document.getElementById("keel-pad-right");

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const DRIFT = [
    [0, 0], [1, 0], [2, 1], [1, -1], [0, -2], [-2, -1], [-2, 0], [-1, 1], [0, 2], [2, 2],
  ];
  let driftIndex = 0;
  let driftX = 0;
  let driftY = 0;

  let lane = 2;
  let running = false;
  let score = 0;
  let bars = [];
  let gapHistory = [];
  let fieldH = 0;
  let fieldW = 0;
  let ringBaseY = 0;
  let barSpeed = 0;
  let rafId = 0;
  let lastTs = 0;
  function leaveHome() {
    window.location.href = "index.html";
  }

  function applyStageTransform() {
    if (!stage) return;
    const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    stage.style.transform =
      `translate(calc(-50% + ${driftX}px), calc(-50% + ${driftY}px)) scale(${scale})`;
  }

  function shiftStage() {
    const pair = DRIFT[driftIndex % DRIFT.length];
    driftX = pair[0];
    driftY = pair[1];
    driftIndex += 1;
    applyStageTransform();
  }

  function measureField() {
    if (!field) return;
    fieldW = field.clientWidth;
    fieldH = field.clientHeight;
    ringBaseY = fieldH * (2 / 3);
    barSpeed = (fieldH + BAR_H) / BAR_CROSS_MS;
    layoutRing(0);
  }

  function laneCenterX(index) {
    const laneW = fieldW / LANES;
    return laneW * (index + 0.5);
  }

  function layoutRing(bobOffset) {
    if (!ring || !fieldW) return;
    ring.style.left = `${laneCenterX(lane)}px`;
    ring.style.top = `${ringBaseY + bobOffset}px`;
  }

  function pickGapLane() {
    const choices = [];
    for (let i = 0; i < LANES; i += 1) {
      const last = gapHistory[gapHistory.length - 1];
      const prev = gapHistory[gapHistory.length - 2];
      if (last === i && prev === i) continue;
      choices.push(i);
    }
    const lanePick = choices[Math.floor(Math.random() * choices.length)] || 0;
    gapHistory.push(lanePick);
    if (gapHistory.length > 3) gapHistory.shift();
    return lanePick;
  }

  function makeBarElement(gapLane) {
    const bar = document.createElement("div");
    bar.className = "keel-bar";
    for (let i = 0; i < LANES; i += 1) {
      const seg = document.createElement("div");
      seg.className = "keel-bar-seg" + (i === gapLane ? " is-gap" : "");
      bar.appendChild(seg);
    }
    barsRoot.appendChild(bar);
    return bar;
  }

  function spawnBar(y) {
    const gapLane = pickGapLane();
    const el = makeBarElement(gapLane);
    const bar = { el, y, gapLane, scored: false, active: true };
    bars.push(bar);
    el.style.transform = `translateY(${y}px)`;
    return bar;
  }

  function seedBars() {
    barsRoot.textContent = "";
    bars = [];
    gapHistory = [];
    let y = -BAR_H;
    while (y < fieldH + BAR_H) {
      spawnBar(y);
      y += SPAWN_GAP;
    }
  }

  function maybeSpawnBar() {
    if (!bars.length) {
      spawnBar(-BAR_H);
      return;
    }
    let minY = bars[0].y;
    for (let i = 1; i < bars.length; i += 1) {
      if (bars[i].y < minY) minY = bars[i].y;
    }
    if (minY > -BAR_H + SPAWN_GAP * 0.45) {
      spawnBar(minY - SPAWN_GAP);
    }
  }

  function setScore(value) {
    score = value;
    scoreEl.textContent = String(score);
  }

  function startRun() {
    running = true;
    setScore(0);
  }

  function endRun() {
    running = false;
  }

  function moveLane(delta) {
    lane = Math.max(0, Math.min(LANES - 1, lane + delta));
  }

  function steer(delta) {
    moveLane(delta);
  }

  function tapSteer(delta) {
    steer(delta);
    if (!running) startRun();
  }

  function ringRect(bobOffset) {
    const size = 56;
    const cx = laneCenterX(lane);
    const cy = ringBaseY + bobOffset;
    return {
      left: cx - size / 2,
      right: cx + size / 2,
      top: cy - size / 2,
      bottom: cy + size / 2,
    };
  }

  function barOverlapsRing(bar, bobOffset) {
    const ringR = ringRect(bobOffset);
    const barTop = bar.y;
    const barBottom = bar.y + BAR_H;
    return barBottom > ringR.top && barTop < ringR.bottom;
  }

  function updateBars(dt, bobOffset) {
    for (let i = bars.length - 1; i >= 0; i -= 1) {
      const bar = bars[i];
      bar.y += barSpeed * dt;
      bar.el.style.transform = `translateY(${bar.y}px)`;

      if (running && !bar.scored && barOverlapsRing(bar, bobOffset)) {
        if (lane === bar.gapLane) {
          bar.scored = true;
          setScore(score + 1);
        } else {
          endRun();
        }
      }

      if (bar.y > fieldH + BAR_H) {
        bar.el.remove();
        bars.splice(i, 1);
      }
    }
    maybeSpawnBar();
  }

  function bobOffset(now) {
    const phase = (now % BOB_CYCLE_MS) / BOB_CYCLE_MS;
    if (reducedMotion) {
      return phase < 0.5 ? -BOB_AMP : BOB_AMP;
    }
    return Math.sin(phase * Math.PI * 2) * BOB_AMP;
  }

  function frame(ts) {
    if (document.hidden) {
      lastTs = 0;
      rafId = 0;
      return;
    }
    if (!lastTs) lastTs = ts;
    const dt = Math.min(ts - lastTs, 48);
    lastTs = ts;
    const bob = bobOffset(ts);
    layoutRing(bob);
    if (fieldH > 0) updateBars(dt, bob);
    rafId = requestAnimationFrame(frame);
  }

  function ensureLoop() {
    if (!rafId && !document.hidden) {
      lastTs = 0;
      rafId = requestAnimationFrame(frame);
    }
  }

  function onKeyDown(event) {
    const key = event.key;
    if (key === "ArrowLeft" || key === "Left") {
      event.preventDefault();
      steer(-1);
      return;
    }
    if (key === "ArrowRight" || key === "Right") {
      event.preventDefault();
      steer(1);
      return;
    }
    if (key === "Enter") {
      if (!running) startRun();
      event.preventDefault();
      return;
    }
    if (
      key === "Escape" ||
      key === "Backspace" ||
      key === "BrowserBack" ||
      key === "GoBack" ||
      key === "Back" ||
      event.keyCode === 4 ||
      event.keyCode === 461 ||
      event.keyCode === 10009
    ) {
      event.preventDefault();
      leaveHome();
    }
  }

  function bindPad(el, delta) {
    el.addEventListener("pointerup", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      tapSteer(delta);
    });
  }
  bindPad(padLeft, -1);
  bindPad(padRight, 1);

  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("resize", () => {
    measureField();
    applyStageTransform();
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) ensureLoop();
  });

  history.pushState({ keel: 1 }, "", window.location.href);
  window.addEventListener("popstate", leaveHome);

  if (window.SlateTV) {
    window.SlateTV.goHome = leaveHome;
    window.SlateTV.onBackPressed = leaveHome;
  }

  measureField();
  seedBars();
  applyStageTransform();
  shiftStage();
  setInterval(shiftStage, 3 * 60 * 1000);
  ensureLoop();
})();
