// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

// Compile repository TS in memory and render the real React/Cloudscape components.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ui = path.resolve(__dirname, '../report_ui');
const uiRequire = Module.createRequire(path.join(ui, 'package.json'));
const ts = uiRequire('typescript');
const React = uiRequire('react');
const { renderToStaticMarkup } = uiRequire('react-dom/server');
const loaded = new Map();
const originalJsLoader = Module._extensions['.js'];
Module._extensions['.css'] = () => {};
Module._extensions['.js'] = (mod, filename) => {
  if (!filename.includes('/@cloudscape-design/')) return originalJsLoader(mod, filename);
  const source = fs.readFileSync(filename, 'utf8');
  const result = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, esModuleInterop: true, target: ts.ScriptTarget.ES2022
  }});
  mod._compile(result.outputText, filename);
};
function load(name) {
  if (loaded.has(name)) return loaded.get(name).exports;
  const filename = path.join(ui, 'src', name);
  let source = fs.readFileSync(filename, 'utf8');
  if (name === 'main.tsx') source += '\nexport { ReportApplication, QuestionDetail, DiscoveryDetails, ErrorView, withReportLanguage };';
  const result = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true,
    target: ts.ScriptTarget.ES2022
  }});
  const mod = new Module(filename);
  mod.paths = Module._nodeModulePaths(ui);
  mod.require = function(request) {
    if (request.endsWith('.css')) return {};
    if (request.startsWith('.')) {
      const relative = request.slice(2);
      return load(fs.existsSync(path.join(ui, 'src', relative + '.ts')) ? relative + '.ts' : relative + '.tsx');
    }
    return uiRequire(request);
  };
  loaded.set(name, mod);
  mod._compile(result.outputText, filename);
  return mod.exports;
}
// main's DOMContentLoaded callback is deliberately not fired during SSR.
global.document = { querySelector() { return null; }, documentElement: {clientWidth: 1280, clientHeight: 900}, readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
const main = load('main.tsx');
delete global.document;
// Python sends fresh synthetic payloads generated from the current definitions.
const reports = JSON.parse(fs.readFileSync(0, 'utf8'));
const output = { views: {} };
const mode = process.argv[2] || 'en';
function reportForMode(report) {
  const copy = structuredClone(report);
  copy.meta.generatedAt = '2026-11-25T01:02:03+00:00';
  if (mode === 'missing') delete copy.meta.language;
  else copy.meta.language = mode;
  return copy;
}
for (const level of ['0', '1', '2', '3', '4']) {
  for (const kind of ['single', 'organization']) {
    const report = reportForMode(reports[level][kind]);
    output.views[`${level}-${kind}`] = renderToStaticMarkup(React.createElement(main.ReportApplication, {report, initialMode: 'light'}));
  }
}
const provider = uiRequire('@cloudscape-design/components/i18n').I18nProvider;
const single = reportForMode(reports['1'].single);
const application = main.ReportApplication({ report: single, initialMode: 'light' });
output.usesProvider = application.type === provider;
output.providerLocale = application.props.locale;
const i18n = load('i18n.ts');
output.discoveryTranslations = Object.fromEntries(
  Object.entries(i18n.ja).filter(([key]) => /discovery checks?/i.test(key))
);
output.deprecatedDiscoveryTerms = Object.keys(i18n.ja).filter(
  key => i18n.ja[key].includes('検出チェック')
);
const data = load('data.ts');
const translated = i18n.reportLanguage(mode);
const render = (Component, props) => renderToStaticMarkup(React.createElement(
  i18n.ReportLanguageContext.Provider, { value: translated }, React.createElement(Component, props)));
output.views.detail = render(main.QuestionDetail, {
  question: single.questions[0], expanded: true, onExpandedChange() {}
});
output.views.discovery = render(main.DiscoveryDetails, { check: single.discovery[0], region: 'us-west-2' });
const script = {tagName:'SCRIPT', getAttribute:()=> 'application/json', textContent: JSON.stringify({meta:mode === 'missing' ? {} : {language:mode},summary:{},categories:[], reportType:'organization'})};
global.document = {getElementById: () => script};
try { data.parseReport(); } catch(error) { output.parseError = error.message; }
delete global.document;
const errorView = main.withReportLanguage(translated, React.createElement(main.ErrorView, { message: output.parseError }));
output.errorUsesProvider = errorView.type === provider;
output.views.error = renderToStaticMarkup(errorView);
const originalLocaleString = Date.prototype.toLocaleString;
const dateArguments = [];
Date.prototype.toLocaleString = function(...args) { dateArguments.push(args); return 'date'; };
data.timeText('2026-11-25T01:02:03+00:00', translated);
Date.prototype.toLocaleString = originalLocaleString;
output.dateArguments = dateArguments;
output.invalidDate = data.timeText('not a date', translated);
output.missingDate = data.timeText(null, translated);
output.date = data.timeText('2026-11-25T01:02:03+00:00', translated);
output.expectedDate = new Date('2026-11-25T01:02:03+00:00').toLocaleString(translated === 'ja' ? 'ja-JP' : undefined);
output.keysEqual = JSON.stringify(Object.keys(i18n.en).sort()) === JSON.stringify(Object.keys(i18n.ja).sort());
process.stdout.write(JSON.stringify(output));
