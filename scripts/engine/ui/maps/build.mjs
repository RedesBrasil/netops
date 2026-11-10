import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs/promises';
process.chdir(fileURLToPath(new URL('.', import.meta.url)));
const result = await build({
  entryPoints: ['editor.jsx'], bundle: true, outfile: '../static/vendor/map-editor.js',
  format: 'esm', minify: true, jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [{ name: 'shared-preact', setup(build) {
    build.onResolve({ filter: /^(react|react-dom)(\/.*)?$/ }, args => ({ path: args.path, namespace: 'shared-preact' }));
    build.onLoad({ filter: /.*/, namespace: 'shared-preact' }, args => ({ contents:
      args.path.includes('jsx-runtime') ? 'export * from "preact/jsx-runtime";' :
      'import * as compat from "preact/compat"; export * from "preact/compat"; export default compat;', loader: 'js' }));
  } }],
  legalComments: 'linked',
  external: ['preact', 'preact/*'], define: { 'process.env.NODE_ENV': '"production"' }, metafile: true,
});
if (Object.keys(result.metafile.inputs).some(p => /node_modules\/(react|react-dom|preact)\//.test(p))) throw new Error('runtime duplicado no editor');
await fs.writeFile('build-meta.json', JSON.stringify(result.metafile, null, 2));
console.log('Editor gerado, sem runtime React ou Preact duplicado.');
