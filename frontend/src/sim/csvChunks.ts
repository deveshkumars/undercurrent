/**
 * Split CSV text into chunks under a byte budget, each starting with the header row.
 * Splits only between records, never inside a quoted field (which may contain newlines).
 */
export function csvChunks(text: string, maxBytes = 2_800_000): string[] {
  const clean = text.replace(/^﻿/, "");
  const ends: number[] = [];
  let inQuotes = false;
  for (let i = 0; i < clean.length; i++) {
    const c = clean[i];
    if (c === '"') {
      if (inQuotes && clean[i + 1] === '"') i++;
      else inQuotes = !inQuotes;
    } else if (c === "\n" && !inQuotes) {
      ends.push(i + 1);
    }
  }
  if (!ends.length || ends[ends.length - 1] !== clean.length) ends.push(clean.length);
  const header = clean.slice(0, ends[0]);
  const headerLine = header.endsWith("\n") ? header : header + "\n";
  const enc = new TextEncoder();
  const chunks: string[] = [];
  let start = ends[0];
  let current = "";
  let size = enc.encode(headerLine).length;
  for (let k = 1; k < ends.length; k++) {
    const rec = clean.slice(start, ends[k]);
    start = ends[k];
    if (!rec.trim()) continue;
    const recSize = enc.encode(rec).length;
    if (current && size + recSize > maxBytes) {
      chunks.push(headerLine + current);
      current = "";
      size = enc.encode(headerLine).length;
    }
    current += rec.endsWith("\n") ? rec : rec + "\n";
    size += recSize;
  }
  if (current) chunks.push(headerLine + current);
  return chunks;
}
