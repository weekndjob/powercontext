// seekdb 1.4.0 validates generated SELECT SQL with a keyword regex. Keywords
// inside correctly quoted search strings are values, not executable commands.
// Mask only string contents before invoking the SDK's original validator.
export function maskSqlStrings(sql) {
  if (typeof sql !== 'string') throw new Error('Invalid generated SQL');
  let result = '';
  for (let i = 0; i < sql.length; i++) {
    const quote = sql[i];
    if (quote !== "'" && quote !== '"') { result += quote; continue; }
    result += ' ';
    let closed = false;
    for (i++; i < sql.length; i++) {
      if (sql[i] === '\\') { result += '  '; i++; continue; }
      if (sql[i] === quote) {
        if (sql[i + 1] === quote) { result += '  '; i++; continue; }
        result += ' '; closed = true; break;
      }
      result += sql[i] === '\n' ? '\n' : ' ';
    }
    if (!closed) throw new Error('Unterminated string in generated SQL');
  }
  return result;
}
