const msgEl = document.getElementById('theme-msg');
const saveBtn = document.getElementById('theme-save');
const picked = { tvAppearance: 'sculptural', tvMotion: 'drift', tvIntensity: 'balanced', ambientPreset: 'aurora' };
let clearPreview = () => {};
let ambientPresets = {};
let ambientPalettes = {};
const groups = [
  ['appearance-styles', 'tvAppearance', [['sculptural', 'Sculptural Light'], ['aqua', 'Aqua'], ['flurry', 'Flurry']]],
  ['appearance-motion', 'tvMotion', [['still', 'Still'], ['drift', 'Drift'], ['reactive', 'Reactive']]],
  ['appearance-intensity', 'tvIntensity', [['soft', 'Soft'], ['balanced', 'Balanced'], ['vivid', 'Vivid']]],
];
function renderOptions() {
  for (const [id, key, options] of groups) {
    const root = document.getElementById(id);
    root.replaceChildren();
    for (const [value, label] of options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'radio');
      button.setAttribute('aria-checked', String(picked[key] === value));
      button.className = 'appearance-option';
      button.dataset.value = value;
      button.textContent = label;
      button.addEventListener('click', () => {
        picked[key] = value;
        updatePreview();
      });
      root.append(button);
    }
  }
  updatePreview();
}
function updatePreview() {
  for (const [id, key] of groups) {
    document.getElementById(id).querySelectorAll('button').forEach(button => button.setAttribute('aria-checked', String(button.dataset.value === picked[key])));
  }
  const profile = window.SlateLooks.normalizeAppearance(picked);
  window.SlateLooks.applyTheme(picked);
  const preview = document.getElementById('appearance-preview');
  preview.dataset.style = profile.tvAppearance;
  clearPreview();
  const preset = ambientPresets[picked.ambientPreset] || {};
  const colors = preset.enabled === false ? [] : ambientPalettes[preset.palette]?.colors;
  clearPreview = window.SlateLooks.decorate(
    document.getElementById('preview-backdrop'),
    profile.tvAppearance,
    picked.tvMotion,
    picked.tvIntensity,
    colors,
  );
  document.getElementById('appearance-description').textContent = {
    sculptural: 'Deep ink and luminous forms.',
    aqua: 'Water ribbons over deep ink.',
    flurry: 'Colored light streaks meeting at a bright core.',
  }[profile.tvAppearance];
  document.getElementById('motion-description').textContent = {
    still: 'A still composition, with no decorative animation.',
    drift: 'Slow movement. Focus leans the field and leaves a short streak.',
    reactive: 'Focus and the pointer pull the field. A press flashes the core.',
  }[picked.tvMotion];
  document.getElementById('ambient-controls').hidden = profile.tvAppearance !== 'sculptural';
  preview.classList.remove('menu-turn');
  void preview.offsetWidth;
  preview.classList.add('menu-turn');
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
    const profile = window.SlateLooks.normalizeAppearance(settings);
    picked.tvAppearance = profile.tvAppearance;
    picked.tvMotion = profile.tvMotion;
    picked.tvIntensity = profile.tvIntensity;
    if (typeof settings.ambientPreset === 'string') picked.ambientPreset = settings.ambientPreset;
    const select = document.getElementById('ambient-preset');
    for (const [key, preset] of Object.entries(ambient.presets || {})) {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = preset.name || key;
      select.append(option);
    }
    select.value = picked.ambientPreset;
    select.addEventListener('change', () => { picked.ambientPreset = select.value; updatePreview(); });
    renderOptions();
  } catch (err) { msgEl.textContent = 'Could not load appearance settings.'; }
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
