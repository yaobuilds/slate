const msgEl = document.getElementById('theme-msg');
const saveBtn = document.getElementById('theme-save');
saveBtn.disabled = true;
const picked = {
  tvAppearance: 'sculptural', tvMotion: 'drift', tvIntensity: 'balanced', ambientPreset: 'aurora',
  tvAquaPalette: 'tide', tvFlurryPalette: 'spectrum',
};
let clearPreview = () => {};
let ambientPresets = {};
let ambientPalettes = {};
const looks = window.SlateLooks.palettes;
function homeProfile(value) {
  if (value === 'classic') return 'sculptural';
  if (value === 'scenic') return 'aqua';
  if (value === 'sculptural' || value === 'aqua' || value === 'flurry') return value;
  return 'sculptural';
}
const LOOKS = [
  ['sculptural', 'Sculptural Light', 'Deep ink and luminous forms.'],
  ['aqua', 'Aqua', 'Flowing ribbons inspired by early Mac looks.'],
  ['flurry', 'Flurry', 'Colored light streaks meeting at a bright core.'],
];
const groups = [
  ['appearance-motion', 'tvMotion', [['still', 'Still'], ['drift', 'Drift'], ['reactive', 'Reactive']]],
  ['appearance-intensity', 'tvIntensity', [['soft', 'Soft'], ['balanced', 'Balanced'], ['vivid', 'Vivid']]],
];
const NEUTRAL = ['#72c9d0', '#837ee0', '#db9cae'];

function radio(label, checked, onPick, className) {
  const button = document.createElement('button');
  button.type = 'button';
  button.setAttribute('role', 'radio');
  button.setAttribute('aria-checked', String(checked));
  button.className = className;
  button.addEventListener('click', onPick);
  if (label) button.textContent = label;
  return button;
}
function swatches(colors) {
  const row = document.createElement('span');
  row.className = 'swatch-row';
  row.setAttribute('aria-hidden', 'true');
  for (const color of colors.slice(0, 3)) {
    const dot = document.createElement('span');
    dot.style.background = color;
    row.append(dot);
  }
  return row;
}
function sculptColors() {
  const preset = ambientPresets[picked.ambientPreset] || {};
  if (preset.enabled === false) return NEUTRAL;
  return ambientPalettes[preset.palette]?.colors || NEUTRAL;
}
function lookColors(look) {
  if (look === 'aqua') return (looks.aqua[picked.tvAquaPalette] || looks.aqua.tide).colors;
  if (look === 'flurry') return (looks.flurry[picked.tvFlurryPalette] || looks.flurry.spectrum).colors;
  return sculptColors();
}
/* Small static art on each look card, drawn from that look's current colors. */
function lookArt(look) {
  const c = lookColors(look);
  if (look === 'aqua') {
    const base = (looks.aqua[picked.tvAquaPalette] || looks.aqua.tide).base;
    return `linear-gradient(160deg, transparent 38%, ${c[0]}99 46%, ${c[1]}cc 52%, ${c[2]}88 58%, transparent 66%), linear-gradient(150deg, ${base}, #10141a 70%)`;
  }
  if (look === 'flurry') {
    const stops = c.map((color, i) => `${color}88 ${Math.round(i * 360 / c.length)}deg`).join(', ');
    return `radial-gradient(circle at 64% 44%, rgba(230,225,215,.75) 0, rgba(230,225,215,.14) 8%, transparent 18%), radial-gradient(circle at 64% 44%, transparent 12%, rgba(11,14,19,.55) 45%, #0b0e13 85%), conic-gradient(from 20deg at 64% 44%, ${stops}, ${c[0]}88 360deg), #0b0e13`;
  }
  return `radial-gradient(circle at 26% 62%, ${c[0]}88, transparent 42%), radial-gradient(circle at 58% 40%, ${c[1] || c[0]}77, transparent 44%), radial-gradient(circle at 84% 68%, ${c[2] || c[0]}77, transparent 40%), #10141a`;
}
function renderLooks() {
  const root = document.getElementById('appearance-styles');
  root.replaceChildren();
  for (const [value, label, description] of LOOKS) {
    const card = radio('', picked.tvAppearance === value, () => { picked.tvAppearance = value; renderAll(); }, 'look-card');
    card.dataset.value = value;
    card.setAttribute('aria-label', `${label}. ${description}`);
    const art = document.createElement('span');
    art.className = 'look-art';
    art.style.background = lookArt(value);
    const name = document.createElement('span');
    name.className = 'look-name';
    name.textContent = label;
    card.append(art, name);
    root.append(card);
  }
}
function colorChoices() {
  const look = picked.tvAppearance;
  if (look === 'aqua' || look === 'flurry') {
    const key = look === 'aqua' ? 'tvAquaPalette' : 'tvFlurryPalette';
    return { key, items: Object.entries(looks[look]).map(([value, pal]) => [value, pal.name, pal.colors]) };
  }
  return {
    key: 'ambientPreset',
    items: Object.entries(ambientPresets).map(([value, preset]) => {
      const off = preset.enabled === false;
      const colors = off ? [] : (ambientPalettes[preset.palette]?.colors || []);
      return [value, (preset.name || value).replace(' (default)', ''), colors];
    }),
  };
}
function renderColors() {
  const root = document.getElementById('appearance-colors');
  root.replaceChildren();
  const { key, items } = colorChoices();
  for (const [value, label, colors] of items) {
    const chip = radio('', picked[key] === value, () => { picked[key] = value; renderAll(); }, 'palette-chip');
    chip.dataset.value = value;
    chip.setAttribute('aria-label', label);
    chip.append(colors.length ? swatches(colors) : Object.assign(document.createElement('span'), { className: 'swatch-row swatch-off', ariaHidden: 'true' }));
    const name = document.createElement('span');
    name.className = 'palette-name';
    name.textContent = label;
    chip.append(name);
    root.append(chip);
  }
  document.getElementById('color-hint').textContent = key === 'ambientPreset'
    ? 'Also used on Dashboard and other devices'
    : 'Used by this look on Home';
}
function renderOptions() {
  for (const [id, key, options] of groups) {
    const root = document.getElementById(id);
    root.replaceChildren();
    for (const [value, label] of options) {
      const button = radio(label, picked[key] === value, () => { picked[key] = value; renderAll(); }, 'appearance-option');
      button.dataset.value = value;
      root.append(button);
    }
  }
}
function updatePreview() {
  const preview = document.getElementById('appearance-preview');
  const look = picked.tvAppearance;
  preview.dataset.style = look;
  clearPreview();
  const key = look === 'aqua' ? picked.tvAquaPalette : look === 'flurry' ? picked.tvFlurryPalette : '';
  clearPreview = window.SlateLooks.decorate(document.getElementById('preview-backdrop'), look, picked.tvMotion, picked.tvIntensity, sculptColors(), key);
  const info = LOOKS.find(([value]) => value === look) || LOOKS[0];
  document.getElementById('appearance-name').textContent = info[1];
  document.getElementById('appearance-description').textContent = info[2];
  document.getElementById('motion-description').textContent = {
    still: 'A still composition, with no decorative animation.',
    drift: 'Slow movement. Focus leans the field and leaves a short streak.',
    reactive: 'Focus and the pointer pull the field. A press flashes the core.',
  }[picked.tvMotion];
  preview.classList.remove('menu-turn');
  void preview.offsetWidth;
  preview.classList.add('menu-turn');
}
function renderAll() {
  const focusedGroup = document.activeElement?.closest?.('[role="radiogroup"]')?.id;
  const focusedValue = document.activeElement?.dataset?.value;
  renderLooks();
  renderColors();
  renderOptions();
  updatePreview();
  if (focusedGroup) {
    const again = document.querySelector(`#${focusedGroup} [data-value="${focusedValue}"]`);
    again?.focus({ preventScroll: true });
  }
}
async function paintPreviewIcons() {
  const nodes = [...document.querySelectorAll('#appearance-preview [data-icon]')];
  await Promise.all(nodes.map(async node => {
    try {
      const response = await fetch(`assets/icons/${node.dataset.icon}.svg`);
      if (!response.ok) return;
      node.innerHTML = (await response.text()).replace('<svg ', '<svg class="i" focusable="false" aria-hidden="true" ');
    } catch (err) { /* text labels still show */ }
  }));
}
async function persistTheme() {
  saveBtn.disabled = true;
  try {
    const result = await saveSettings({ ...picked });
    if (result.error === 'pin') { wireSettingsPinForm(persistTheme); return; }
    if (result.error) {
      msgEl.textContent = result.error === 'slow' ? 'Wait a moment and try again.'
        : result.error === 'offline' ? 'Could not reach Slate. Keep this page open and try again.' : 'Could not save.';
      return;
    }
    location.href = 'index.html';
  } catch (err) {
    msgEl.textContent = 'Could not reach Slate. Keep this page open and try again.';
  } finally { saveBtn.disabled = false; }
}
async function init() {
  try {
    const [ambient, settings] = await Promise.all([readJson('ambient.json'), loadSettings()]);
    ambientPresets = ambient.presets || {};
    ambientPalettes = ambient.palettes || {};
    for (const key of Object.keys(picked)) if (typeof settings[key] === 'string') picked[key] = settings[key];
    picked.tvAppearance = homeProfile(picked.tvAppearance);
    if (!looks.aqua[picked.tvAquaPalette]) picked.tvAquaPalette = 'tide';
    if (!looks.flurry[picked.tvFlurryPalette]) picked.tvFlurryPalette = 'spectrum';
    renderAll();
    paintPreviewIcons();
    saveBtn.disabled = false;
  } catch (err) {
    msgEl.textContent = 'Could not load appearance settings.';
    saveBtn.disabled = true;
    renderAll();
  }
}
saveBtn.addEventListener('click', persistTheme);
addEventListener('pagehide', () => clearPreview());
document.addEventListener('slate:motion-preference', updatePreview);
function reactPreview(x, y) {
  if (picked.tvMotion === 'still' || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const backdrop = document.getElementById('preview-backdrop');
  backdrop.style.setProperty('--look-x', `${(x - .5) * 12}px`);
  backdrop.style.setProperty('--look-y', `${(y - .5) * 8}px`);
}
document.addEventListener('pointermove', event => reactPreview(event.clientX / innerWidth, event.clientY / innerHeight));
document.addEventListener('focusin', event => {
  const rect = event.target.getBoundingClientRect?.();
  if (rect) reactPreview((rect.left + rect.width / 2) / innerWidth, (rect.top + rect.height / 2) / innerHeight);
});
init();
