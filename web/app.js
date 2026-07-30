/**
 * ADA PDF Remediator interface.
 *
 * Everything shown here comes from the server. The previous version advanced a
 * four step indicator on setTimeout and printed invented log lines while the
 * real work happened invisibly, then displayed a hardcoded scorecard that read
 * "100% COMPLIANT" no matter what the audit returned. For a tool whose whole
 * subject is whether documents tell the truth about themselves, that was the
 * wrong thing to ship.
 */

const API_BASE = window.location.hostname.endsWith('pages.dev')
  ? 'https://ada-pdf-remediator.onrender.com'
  : '';

/** Stages the pipeline reports, in the order they occur. */
const STAGES = [
  ['opening', 'Reading'],
  ['analysing-page', 'Analysing pages'],
  ['tagging-figures', 'Figures'],
  ['recognising-text', 'Recognising text'],
  ['recovering-fonts', 'Character maps'],
  ['building-structure', 'Structure'],
  ['writing', 'Writing'],
  ['auditing', 'Auditing'],
];

const SEVERITY_LABEL = { error: 'Error', warning: 'Warning', review: 'Review' };

const el = (id) => document.getElementById(id);

const dom = {
  dropzone: el('dropzone'),
  form: el('upload-form'),
  file: el('file-input'),
  submit: el('submit-button'),
  run: el('run'),
  runFilename: el('run-filename'),
  stages: el('stages'),
  status: el('run-status'),
  log: el('log'),
  cancel: el('cancel-button'),
  error: el('error-box'),
  errorMessage: el('error-message'),
  errorRetry: el('error-retry'),
  report: el('report'),
  verdict: el('report-verdict'),
  tally: el('tally'),
  findings: el('findings'),
  download: el('download-link'),
};

let stream = null;

/* ------------------------------------------------------------------ view */

function show(node, visible) {
  node.hidden = !visible;
}

function reset() {
  if (stream) {
    stream.close();
    stream = null;
  }
  show(dom.run, false);
  show(dom.report, false);
  show(dom.error, false);
  dom.dropzone.hidden = false;
  dom.log.replaceChildren();
  dom.stages.replaceChildren();
  dom.form.reset();
  dom.submit.disabled = true;
  dom.submit.removeAttribute('aria-busy');
  dom.submit.textContent = 'Remediate this document';
  dom.file.focus();
}

function buildStages() {
  dom.stages.replaceChildren(
    ...STAGES.map(([id, label]) => {
      const item = document.createElement('li');
      item.dataset.stage = id;
      item.textContent = label;
      return item;
    }),
  );
}

function markStage(stage) {
  const order = STAGES.findIndex(([id]) => id === stage);
  if (order < 0) return;
  for (const [index, item] of [...dom.stages.children].entries()) {
    item.dataset.done = String(index <= order);
    item.dataset.current = String(index === order);
  }
}

function appendLog(message) {
  const line = document.createElement('p');
  const time = document.createElement('time');
  const now = new Date();
  time.dateTime = now.toISOString();
  time.textContent = now.toLocaleTimeString([], { hour12: false });
  line.append(time, document.createTextNode(message));
  dom.log.append(line);
  // Only follow the tail when the reader has not scrolled up to look at
  // something, otherwise the log yanks itself away from under them.
  const atBottom = dom.log.scrollHeight - dom.log.scrollTop - dom.log.clientHeight < 40;
  if (atBottom) dom.log.scrollTop = dom.log.scrollHeight;
}

function fail(message) {
  if (stream) {
    stream.close();
    stream = null;
  }
  show(dom.run, false);
  show(dom.error, true);
  dom.errorMessage.textContent = message;
  dom.errorRetry.focus();
}

/* ---------------------------------------------------------------- report */

function renderTally(audit) {
  const counts = audit.counts ?? {};
  const axes = audit.axescheck_summary;
  const entries = [
    ['Errors', counts.errors ?? 0, counts.errors ? 'error' : 'good'],
    ['Warnings', counts.warnings ?? 0, counts.warnings ? 'warning' : 'neutral'],
    ['Rules run', audit.rulesRun ?? 0, 'neutral'],
  ];

  if (axes && axes.success) {
    if (axes.pdfuaScore !== undefined && axes.pdfuaScore !== null) {
      entries.push(['axesCheck PDF/UA', `${axes.pdfuaScore}/100`, axes.pdfuaScore === 100 ? 'good' : 'warning']);
    }
    if (axes.wcagScore !== undefined && axes.wcagScore !== null) {
      entries.push(['axesCheck WCAG', `${axes.wcagScore}/100`, axes.wcagScore === 100 ? 'good' : 'warning']);
    }
    entries.push(['axesCheck Errors', axes.totalErrors ?? 0, axes.totalErrors ? 'error' : 'good']);
  }

  if (counts.review) entries.push(['Needs review', counts.review, 'neutral']);

  dom.tally.replaceChildren(
    ...entries.map(([label, value, tone]) => {
      const group = document.createElement('div');
      group.dataset.tone = tone;
      const dd = document.createElement('dd');
      dd.textContent = String(value);
      const dt = document.createElement('dt');
      dt.textContent = label;
      group.append(dd, dt);
      return group;
    }),
  );
}

function renderFinding(finding) {
  const item = document.createElement('li');
  item.className = 'finding';
  item.dataset.severity = finding.severity;

  const severity = document.createElement('span');
  severity.className = 'finding__severity';
  // The word is present as well as the glyph and the colour, so the severity
  // survives greyscale printing and does not depend on colour vision.
  severity.textContent = SEVERITY_LABEL[finding.severity] ?? finding.severity;

  const body = document.createElement('div');
  body.className = 'finding__body';

  const message = document.createElement('p');
  message.className = 'finding__message';
  message.textContent = finding.message;
  body.append(message);

  if (finding.remedy) {
    const remedy = document.createElement('p');
    remedy.className = 'finding__remedy';
    remedy.textContent = finding.remedy;
    body.append(remedy);
  }

  const meta = document.createElement('p');
  meta.className = 'finding__meta';
  const condition = document.createElement('span');
  condition.className = 'finding__condition';
  condition.textContent = `Matterhorn ${finding.condition}`;
  meta.append(condition);
  const where = finding.location ?? {};
  if (where.page !== null && where.page !== undefined) {
    const page = document.createElement('span');
    page.textContent = `Page ${where.page + 1}`;
    meta.append(page);
  }
  if (where.structPath) {
    const path = document.createElement('span');
    path.textContent = where.structPath;
    meta.append(path);
  }
  body.append(meta);

  item.append(severity, body);
  return item;
}

function renderFindings(audit) {
  const findings = audit.findings ?? [];
  if (findings.length === 0) {
    const clean = document.createElement('div');
    clean.className = 'report__clean';
    const heading = document.createElement('h3');
    heading.textContent = 'No automatable problems found';
    const detail = document.createElement('p');
    detail.textContent =
      `All ${audit.rulesRun} rules ran and none of them found anything. ` +
      'That is the strongest statement software can make about this file.';
    clean.append(heading, detail);
    dom.findings.replaceChildren(clean);
    return;
  }

  const groups = new Map();
  for (const finding of findings) {
    const key = finding.checkpoint ?? 'other';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(finding);
  }

  dom.findings.replaceChildren(
    ...[...groups.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([checkpoint, group]) => {
        const section = document.createElement('section');
        section.className = 'checkpoint';
        const heading = document.createElement('h3');
        heading.textContent = `Checkpoint ${checkpoint} · ${group.length} finding${
          group.length === 1 ? '' : 's'
        }`;
        const list = document.createElement('ul');
        list.append(...group.map(renderFinding));
        section.append(heading, list);
        return section;
      }),
  );
}

function renderReport(job) {
  const audit = job.result?.audit;
  if (!audit) {
    fail('The job finished but returned no report.');
    return;
  }

  const axes = audit.axescheck_summary;
  let verdictText = audit.conformant
    ? 'No conformance errors were found by internal checks.'
    : `${audit.counts.errors} conformance ${
        audit.counts.errors === 1 ? 'error' : 'errors'
      } remain. They are listed below with the clause behind each one.`;

  if (axes && axes.success) {
    verdictText += ` Official axesCheck report: PDF/UA Score ${axes.pdfuaScore}/100, WCAG Score ${axes.wcagScore}/100 (${axes.totalErrors} errors).`;
  }

  dom.verdict.textContent = verdictText;
  renderTally(audit);
  renderFindings(audit);
  dom.download.href = `${API_BASE}/api/jobs/${job.id}/download`;
  dom.download.download = `remediator_${job.filename}`;
  show(dom.run, false);
  show(dom.report, true);
  dom.download.focus();
  dom.report.querySelector('h2')?.focus({ preventScroll: true });
  dom.report.scrollIntoView({ behavior: 'smooth', block: 'start' });
}


/* ------------------------------------------------------------------ flow */

function follow(jobId) {
  stream = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);

  stream.addEventListener('progress', (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    markStage(payload.stage);
    const counted =
      payload.current && payload.total ? ` (${payload.current} of ${payload.total})` : '';
    dom.status.textContent = `${payload.label}${counted}`;
    appendLog(payload.message);
  });

  stream.addEventListener('succeeded', (event) => {
    stream.close();
    stream = null;
    renderReport(JSON.parse(event.data));
  });

  stream.addEventListener('failed', (event) => {
    stream.close();
    stream = null;
    const job = JSON.parse(event.data);
    fail(job.error || 'The document could not be processed.');
  });

  stream.onerror = () => {
    // EventSource reconnects on its own. Only give up once the connection is
    // definitively closed, otherwise a transient blip looks like a failure.
    if (stream && stream.readyState === EventSource.CLOSED) {
      stream = null;
      pollOnce(jobId);
    }
  };
}

async function pollOnce(jobId) {
  try {
    const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
    const job = await response.json();
    if (job.state === 'succeeded') renderReport(job);
    else if (job.state === 'failed') fail(job.error || 'The document could not be processed.');
    else fail('The connection to the server was lost while the document was being processed.');
  } catch {
    fail('The connection to the server was lost.');
  }
}

async function submit(event) {
  event.preventDefault();
  const file = dom.file.files?.[0];
  if (!file) return;

  dom.submit.disabled = true;
  dom.submit.setAttribute('aria-busy', 'true');
  dom.submit.textContent = 'Uploading';

  const body = new FormData();
  body.append('pdf', file);
  body.append(
    'undescribedImages',
    dom.form.querySelector('input[name="undescribedImages"]:checked')?.value ?? 'figure',
  );

  dom.dropzone.hidden = true;
  show(dom.error, false);
  show(dom.report, false);
  show(dom.run, true);
  dom.runFilename.textContent = file.name;
  buildStages();
  dom.status.textContent = 'Uploading the document.';
  appendLog(`Selected ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB).`);

  let job;
  try {
    const response = await fetch(`${API_BASE}/api/jobs`, { method: 'POST', body });
    job = await response.json();
    if (!response.ok) {
      fail(job.error || `The server refused the upload (${response.status}).`);
      return;
    }
  } catch {
    fail('The server could not be reached. It may be starting up; try again in a moment.');
    return;
  }

  for (const warning of job.warnings ?? []) appendLog(`Note: ${warning}`);
  appendLog('Queued.');
  follow(job.id);
}

/* ------------------------------------------------------------------ wire */

dom.form.addEventListener('submit', submit);
dom.file.addEventListener('change', () => {
  dom.submit.disabled = !dom.file.files?.length;
});
dom.cancel.addEventListener('click', reset);
dom.errorRetry.addEventListener('click', reset);

for (const name of ['dragenter', 'dragover']) {
  dom.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dom.dropzone.dataset.dragging = 'true';
  });
}

for (const name of ['dragleave', 'drop']) {
  dom.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    if (name === 'dragleave' && dom.dropzone.contains(event.relatedTarget)) return;
    dom.dropzone.dataset.dragging = 'false';
  });
}

dom.dropzone.addEventListener('drop', (event) => {
  const dropped = event.dataTransfer?.files?.[0];
  if (!dropped) return;
  // Assigning to the input rather than tracking a separate variable keeps one
  // source of truth, so the form and the drop path cannot disagree.
  const transfer = new DataTransfer();
  transfer.items.add(dropped);
  dom.file.files = transfer.files;
  dom.submit.disabled = false;
  dom.file.dispatchEvent(new Event('change'));
});

window.addEventListener('beforeunload', () => stream?.close());
