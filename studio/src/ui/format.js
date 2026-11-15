// Display formatting only. Money in replay packs is integer euro cents.
const decimal = new Intl.NumberFormat('en-US', {maximumFractionDigits: 2});
const currency = new Intl.NumberFormat('en-IE', {style: 'currency', currency: 'EUR'});
const percentage = new Intl.NumberFormat('en-US', {style: 'percent', maximumFractionDigits: 1});
const finite = value => typeof value === 'number' && Number.isFinite(value);

export const number = value => finite(value) ? decimal.format(value) : '—';
export const euros = cents => finite(cents) ? currency.format(cents / 100) : '—';
export const percent = (numerator, denominator) => finite(numerator) && finite(denominator) && denominator > 0
  ? percentage.format(numerator / denominator) : '—';
export function duration(seconds) {
  if (!finite(seconds) || seconds < 0) return '—';
  const whole = Math.floor(seconds);
  return [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60]
    .map(part => String(part).padStart(2, '0')).join(':');
}
export const html = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));
