// Lógica pura do gerenciador de arquivos (sem DOM) — testada em tests/files-core.test.mjs.

export function normPath(p) {
  const parts = [];
  for (const seg of String(p || "/").split("/")) {
    if (!seg || seg === ".") continue;
    if (seg === "..") parts.pop(); else parts.push(seg);
  }
  return "/" + parts.join("/");
}

export function joinPath(dir, name) {
  return normPath(String(dir || "/") + "/" + name);
}

export function parentPath(p) {
  const n = normPath(p);
  if (n === "/") return null;
  const i = n.lastIndexOf("/");
  return i <= 0 ? "/" : n.slice(0, i);
}

export function baseName(p) {
  const n = normPath(p);
  return n === "/" ? "/" : n.slice(n.lastIndexOf("/") + 1);
}

// [{name, path}] do / até a pasta atual (barra de caminho clicável).
export function crumbs(p) {
  const n = normPath(p);
  const out = [{ name: "/", path: "/" }];
  let acc = "";
  for (const seg of n.split("/").filter(Boolean)) { acc += "/" + seg; out.push({ name: seg, path: acc }); }
  return out;
}

export function formatSize(n) {
  if (n == null || isNaN(n)) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 ? String(v) : v.toFixed(v < 10 ? 1 : 0)) + " " + u[i];
}

export function formatDate(sec) {
  if (!sec) return "";
  const d = new Date(sec * 1000), z = (x) => String(x).padStart(2, "0");
  return `${z(d.getDate())}/${z(d.getMonth() + 1)}/${d.getFullYear()} ${z(d.getHours())}:${z(d.getMinutes())}`;
}

// sort: "name" | "-name" | "size" | "-size" | "mtime" | "-mtime". Pastas sempre primeiro.
export function sortEntries(entries, sort = "name") {
  const desc = String(sort).startsWith("-");
  const key = String(sort).replace(/^-/, "") || "name";
  const cmpName = (a, b) => a.name.localeCompare(b.name, "pt-BR", { numeric: true, sensitivity: "base" });
  return [...entries].sort((a, b) => {
    if (!!a.is_dir !== !!b.is_dir) return a.is_dir ? -1 : 1;
    let c = 0;
    if (key === "size") c = (a.size || 0) - (b.size || 0);
    else if (key === "mtime") c = (a.mtime || 0) - (b.mtime || 0);
    if (!c) c = cmpName(a, b);
    return desc ? -c : c;
  });
}

export function filterEntries(entries, { q = "", hidden = true } = {}) {
  const n = String(q || "").trim().toLowerCase();
  return entries.filter((e) => (hidden || !e.name.startsWith(".")) && (!n || e.name.toLowerCase().includes(n)));
}

// Seleção estilo explorador: clique simples, Ctrl (alterna), Shift (intervalo a partir da âncora).
export function nextSelection(names, selected, anchor, name, { ctrl = false, shift = false } = {}) {
  if (shift && anchor != null && names.includes(anchor)) {
    const a = names.indexOf(anchor), b = names.indexOf(name);
    const [i, j] = a < b ? [a, b] : [b, a];
    const range = names.slice(i, j + 1);
    return { selected: ctrl ? [...new Set([...selected, ...range])] : range, anchor };
  }
  if (ctrl) {
    const s = new Set(selected);
    s.has(name) ? s.delete(name) : s.add(name);
    return { selected: [...s], anchor: name };
  }
  return { selected: [name], anchor: name };
}

// "rwxr-x---" <-> 0o750 (só os 9 bits de permissão; setuid etc. ficam no octal digitado).
export function modeToOctal(mode) {
  return (Number(mode) & 0o7777).toString(8).padStart(3, "0");
}
export function octalToBits(oct) {
  const m = parseInt(oct, 8) || 0;
  return [0o400, 0o200, 0o100, 0o40, 0o20, 0o10, 0o4, 0o2, 0o1].map((b) => !!(m & b));
}
export function bitsToOctal(bits, base = "") {
  let m = 0;
  [0o400, 0o200, 0o100, 0o40, 0o20, 0o10, 0o4, 0o2, 0o1].forEach((b, i) => { if (bits[i]) m |= b; });
  const special = (parseInt(base, 8) || 0) & 0o7000;
  return ((m | special) & 0o7777).toString(8).padStart(3, "0");
}

// Tipo do ícone pela extensão (só visual).
const EXT = {
  code: ["py", "sh", "js", "mjs", "ts", "go", "rs", "c", "h", "cpp", "java", "php", "pl", "rb", "lua", "rsc"],
  conf: ["conf", "cfg", "ini", "yaml", "yml", "json", "toml", "xml", "env", "service", "timer", "network", "rules"],
  text: ["txt", "md", "log", "csv", "out", "list"],
  archive: ["zip", "gz", "tgz", "xz", "bz2", "zst", "tar", "7z", "rar", "deb", "rpm", "npk"],
  image: ["png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp"],
  disk: ["qcow2", "img", "iso", "vmdk", "raw", "vdi", "vma"],
  key: ["pem", "key", "crt", "cer", "pub", "p12", "pfx"],
};
export function fileKind(entry) {
  if (entry.is_dir) return "dir";
  const n = String(entry.name || "").toLowerCase();
  const ext = n.includes(".") ? n.slice(n.lastIndexOf(".") + 1) : "";
  for (const [k, list] of Object.entries(EXT)) if (list.includes(ext)) return k;
  if (/^(id_|authorized_keys|known_hosts)/.test(n)) return "key";
  if (/(^\.|rc$|^makefile$|^dockerfile$)/.test(n)) return "conf";
  return entry.mode & 0o111 && entry.type === "file" ? "exec" : "file";
}

// Nome livre na pasta (upload/novo arquivo): "nome", "nome (2)", ...
export function freeName(name, taken) {
  const set = taken instanceof Set ? taken : new Set(taken);
  if (!set.has(name)) return name;
  const dot = name.lastIndexOf(".");
  const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
  for (let i = 2; ; i++) { const c = `${stem} (${i})${ext}`; if (!set.has(c)) return c; }
}

// Nomes do 1º nível de uma lista de envios [{rel}] (conflito é checado só no topo).
export function topNames(items) {
  return [...new Set(items.map((it) => String(it.rel).split("/")[0]))];
}

export function validName(name) {
  const n = String(name || "").trim();
  if (!n) return "Informe um nome.";
  if (n === "." || n === "..") return "Nome inválido.";
  if (n.includes("/")) return "O nome não pode ter /.";
  return "";
}
