import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Só as funções puras de agenda (presets <-> {type, expr|minutes|at}); imports viram stubs.
const src = readFileSync(new URL("../static/js/pages/schedules.js", import.meta.url), "utf8")
  .replace(/^import .*$/gm, "")
  .replace(/^/, "const html=()=>null,useState=()=>[],useEffect=()=>{};\n");
const s = await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"));

test("presets viram expressão cron/intervalo/uma vez", () => {
  assert.deepEqual(s.toSchedule({ preset: "daily", time: "08:30" }), { type: "cron", expr: "30 8 * * *" });
  assert.deepEqual(s.toSchedule({ preset: "weekdays", time: "09:00" }), { type: "cron", expr: "0 9 * * 1-5" });
  assert.deepEqual(s.toSchedule({ preset: "weekly", time: "07:05", days: ["1", "4"] }), { type: "cron", expr: "5 7 * * 1,4" });
  assert.deepEqual(s.toSchedule({ preset: "monthly", time: "00:00", day: 40 }), { type: "cron", expr: "0 0 31 * *" });
  assert.deepEqual(s.toSchedule({ preset: "interval", minutes: "30" }), { type: "interval", minutes: 30 });
  assert.deepEqual(s.toSchedule({ preset: "once", at: "2026-11-20T09:00" }), { type: "once", at: "2026-11-20T09:00" });
  assert.deepEqual(s.toSchedule({ preset: "cron", expr: " */5 * * * * " }), { type: "cron", expr: "*/5 * * * *" });
});

test("ida e volta: agenda salva reabre no mesmo preset", () => {
  for (const p of [{ preset: "daily", time: "08:30" }, { preset: "weekdays", time: "09:00" },
    { preset: "weekly", time: "07:05", days: ["1", "4"] }, { preset: "monthly", time: "10:00", day: 5 },
    { preset: "hourly", minute: 15 }, { preset: "interval", minutes: 45 }]) {
    const back = s.fromSchedule(s.toSchedule(p));
    assert.equal(back.preset, p.preset);
    assert.deepEqual(s.toSchedule(back), s.toSchedule(p));
  }
  assert.equal(s.fromSchedule({ type: "cron", expr: "0 9-18/2 * * *" }).preset, "cron");
  assert.equal(s.fromSchedule({ type: "once", at: "2026-11-20T09:00-03:00" }).at, "2026-11-20T09:00");
});

test("texto amigável da agenda", () => {
  assert.equal(s.scheduleText({ type: "cron", expr: "0 9 * * 1-5" }), "Seg–Sex às 09:00");
  assert.equal(s.scheduleText({ type: "interval", minutes: 120 }), "A cada 2 h");
  assert.equal(s.scheduleText({ type: "cron", expr: "0 8 * * 1,3" }), "Seg, Qua às 08:00");
});
