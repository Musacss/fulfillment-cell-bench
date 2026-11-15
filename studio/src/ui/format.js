export function euros(cents, locale = 'ru-RU') {
  if (typeof cents !== 'number' || !Number.isFinite(cents)) return '—';
  return new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(cents / 100);
}

export function number(value, locale = 'ru-RU', maximumFractionDigits = 2) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(locale, { maximumFractionDigits }).format(value);
}

export function duration(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '—';
  return [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    Math.floor(seconds) % 60,
  ]
    .map((v) => String(v).padStart(2, '0'))
    .join(':');
}

export function percent(numerator, denominator, locale = 'ru-RU', maximumFractionDigits = 1) {
  if (
    typeof numerator !== 'number' ||
    typeof denominator !== 'number' ||
    !Number.isFinite(numerator) ||
    !Number.isFinite(denominator) ||
    denominator <= 0
  ) {
    return '—';
  }
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits }).format(
    numerator / denominator,
  );
}

export function html(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}
