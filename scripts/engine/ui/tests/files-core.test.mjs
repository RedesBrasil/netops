import assert from "node:assert/strict";
import test from "node:test";

const f = await import("../static/js/files-core.js");

test("caminhos: normaliza, junta, pai, nome, migalhas", () => {
  assert.equal(f.normPath("/etc//nginx/./conf.d/../"), "/etc/nginx");
  assert.equal(f.normPath("/../.."), "/");
  assert.equal(f.joinPath("/etc", "hosts"), "/etc/hosts");
  assert.equal(f.joinPath("/", "a/b"), "/a/b");
  assert.equal(f.parentPath("/etc/nginx"), "/etc");
  assert.equal(f.parentPath("/etc"), "/");
  assert.equal(f.parentPath("/"), null);
  assert.equal(f.baseName("/etc/hosts"), "hosts");
  assert.deepEqual(f.crumbs("/etc/nginx").map((c) => c.path), ["/", "/etc", "/etc/nginx"]);
});

test("ordenação: pastas primeiro; nome natural; tamanho/data com inversão", () => {
  const e = [{ name: "b10", size: 5, mtime: 3 }, { name: "b2", size: 50, mtime: 1 }, { name: "zdir", is_dir: true }, { name: "Adir", is_dir: true }];
  assert.deepEqual(f.sortEntries(e).map((x) => x.name), ["Adir", "zdir", "b2", "b10"]);
  assert.deepEqual(f.sortEntries(e, "-size").map((x) => x.name), ["zdir", "Adir", "b2", "b10"]);
  assert.deepEqual(f.sortEntries(e, "mtime").map((x) => x.name).slice(2), ["b2", "b10"]);
});

test("filtro: texto e ocultos", () => {
  const e = [{ name: ".bashrc" }, { name: "notas.txt" }, { name: "Nota2" }];
  assert.deepEqual(f.filterEntries(e, { q: "nota" }).map((x) => x.name), ["notas.txt", "Nota2"]);
  assert.deepEqual(f.filterEntries(e, { hidden: false }).map((x) => x.name), ["notas.txt", "Nota2"]);
});

test("seleção: simples, ctrl alterna, shift intervalo", () => {
  const n = ["a", "b", "c", "d"];
  let r = f.nextSelection(n, [], null, "b");
  assert.deepEqual(r, { selected: ["b"], anchor: "b" });
  r = f.nextSelection(n, r.selected, r.anchor, "d", { shift: true });
  assert.deepEqual(r.selected, ["b", "c", "d"]);
  r = f.nextSelection(n, r.selected, r.anchor, "c", { ctrl: true });
  assert.deepEqual(r.selected, ["b", "d"]);
});

test("permissões: octal <-> bits preservando especiais", () => {
  assert.equal(f.modeToOctal(0o755), "755");
  assert.deepEqual(f.octalToBits("640"), [true, true, false, true, false, false, false, false, false]);
  assert.equal(f.bitsToOctal(f.octalToBits("750")), "750");
  assert.equal(f.bitsToOctal(f.octalToBits("755"), "4755"), "4755");
});

test("nomes: livre, topo do envio, validação, ícone", () => {
  assert.equal(f.freeName("a.txt", ["a.txt", "a (2).txt"]), "a (3).txt");
  assert.deepEqual(f.topNames([{ rel: "p/x" }, { rel: "p/y/z" }, { rel: "q" }]), ["p", "q"]);
  assert.ok(f.validName("a/b"));
  assert.equal(f.validName("ok.txt"), "");
  assert.equal(f.fileKind({ name: "x", is_dir: true }), "dir");
  assert.equal(f.fileKind({ name: "r.rsc" }), "code");
  assert.equal(f.fileKind({ name: "img.qcow2" }), "disk");
  assert.equal(f.fileKind({ name: "run", type: "file", mode: 0o755 }), "exec");
});
