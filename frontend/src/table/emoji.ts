/**
 * Splitting a name into text and emoji, so the emoji can be aligned.
 *
 * People put emoji in their table names, and emoji come from a colour font
 * whose baseline and metrics are nothing like the Latin one beside them. Inside
 * a single text run there is no lever to correct that — `vertical-align` needs
 * an element, and a glyph is not one. So the string is cut into runs and the
 * picture ones get wrapped.
 *
 * It matters more here than it would anywhere else: seat cards are rotated to
 * face their players, so a glyph sitting low on the line doesn't look slightly
 * low, it looks like it has fallen off the side of the name.
 */

/**
 * Emoji, including the multi-codepoint ones.
 *
 * `Extended_Pictographic` is the property that actually means "emoji" —
 * `Emoji` also matches bare digits and `#`, which would wrap half of
 * `Grumpy Platypus 42`. The trailing parts pick up skin tones, variation
 * selectors and ZWJ sequences so a family or a flag stays one run instead of
 * being sliced into unrenderable pieces.
 */
const EMOJI_RUN =
  /(\p{Extended_Pictographic}(?:️|\p{Emoji_Modifier}|‍\p{Extended_Pictographic}|[\u{1F3FB}-\u{1F3FF}])*)+/gu;

export interface NameSegment {
  text: string;
  emoji: boolean;
}

/**
 * A name as alternating plain and emoji runs. Adjacent emoji stay in one run,
 * so `🦅🤘` is wrapped once rather than twice.
 */
export function splitEmoji(name: string): NameSegment[] {
  const out: NameSegment[] = [];
  let last = 0;
  for (const m of name.matchAll(EMOJI_RUN)) {
    if (m.index > last) out.push({ text: name.slice(last, m.index), emoji: false });
    out.push({ text: m[0], emoji: true });
    last = m.index + m[0].length;
  }
  if (last < name.length) out.push({ text: name.slice(last), emoji: false });
  return out;
}

/** Whether a name has any emoji at all — cheap enough to skip the wrapping. */
export function hasEmoji(name: string): boolean {
  return /\p{Extended_Pictographic}/u.test(name);
}
