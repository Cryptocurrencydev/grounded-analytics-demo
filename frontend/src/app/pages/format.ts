import { Stat } from '../core/models';

export function formatStat(s: Stat): string {
  const sign = (s.unit === 'scale_delta' || s.unit === 'nps_delta' || s.unit === 'pp') && s.value > 0 ? '+' : '';
  const unit = s.unit === 'pct' ? '%' : s.unit === 'pp' ? ' pp' : '';
  const n = s.value.toFixed(s.decimals);
  const sig = s.significant === true ? ' · significant' : s.significant === false ? ' · not significant' : '';
  return `${sign}${n}${unit}${s.n ? ` · n=${s.n.toLocaleString('en-GB')}` : ''}${sig}`;
}
