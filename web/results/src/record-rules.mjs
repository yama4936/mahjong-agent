// Old operator logs predate the rules field and used the four-player-only runner.
// A sanma-named run without an explicit rules receipt is quarantined, not yonma.
export function recordRules(record) {
  if (['sanma', 'yonma', 'unknown'].includes(record.rules)) return record.rules;
  if (record.rules != null) return 'unknown';
  return /sanma|3ma|三麻/.test(record.run || '') ? 'unknown' : 'yonma';
}
export function recordsForRules(records, rules) {
  return records.filter(record => recordRules(record) === rules);
}
export function rankSummary(records, rules) {
  const last = rules === 'sanma' ? 3 : 4;
  const known = records.filter(r => Number.isInteger(r.rank) && r.rank >= 1 && r.rank <= last);
  return {known, last, average:known.length ? known.reduce((sum,r)=>sum+r.rank,0)/known.length : null,
    rate:rank=>known.length ? known.filter(r=>r.rank===rank).length/known.length : null};
}
