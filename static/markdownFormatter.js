/* WhiteBook Markdown Formatter
 *
 * Models occasionally collapse list items into a single paragraph
 * ("Age: 65 years (1 point).2. Cancer: No (0 points).3. Heart failure: …").
 * Marked.js renders that as a wall of text. This module repairs the upstream
 * output before it reaches Marked. The repairs are conservative — we never
 * touch fenced code blocks or inline code, and we always preserve user
 * intent (paragraphs, headings, blockquotes, tables).
 *
 * Fix priority order (each step assumes the prior steps ran):
 *   1. Strip carriage returns / non-breaking space artifacts.
 *   2. Walk the buffer and protect fenced code, inline code, and link bodies.
 *   3. In the unprotected text:
 *        a. Force a newline before any inline numbered item ("foo.2. bar").
 *        b. Force a newline before mid-line bullets that follow punctuation
 *           ("foo.- bar", "foo.• bar").
 *        c. Auto-bold inline parameter labels ("Age: 65 years" → "**Age**: …")
 *           but only when they appear at the start of a list item.
 *        d. Promote standalone "Total X: …" lines into bold totals.
 *   4. Collapse triple+ blank lines.
 *   5. Re-stitch protected segments back in.
 */

(() => {
	const PROTECTED_PLACEHOLDER = (index) => `\u0000WBPRO${index}\u0000`;
	const PROTECTED_PATTERN = /\u0000WBPRO(\d+)\u0000/g;
	const FENCED_CODE = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
	const INLINE_CODE = /(`[^`\n]+`)/g;

	// Words that commonly appear as parameter labels in clinical lists.
	const LABEL_TOKEN = /^([A-Z][\w()/\- ]{1,40}?)(?:\s*\([^)]+\))?:\s+/;

	function protect(text) {
		const segments = [];
		const place = (match) => {
			segments.push(match);
			return PROTECTED_PLACEHOLDER(segments.length - 1);
		};
		let next = text.replace(FENCED_CODE, place);
		next = next.replace(INLINE_CODE, place);
		return { text: next, segments };
	}

	function restore(text, segments) {
		return text.replace(PROTECTED_PATTERN, (_, index) => segments[Number(index)] ?? "");
	}

	function normalizeWhitespace(text) {
		return text
			.replace(/\r\n/g, "\n")
			.replace(/\r/g, "\n")
			.replace(/\u00A0/g, " ")
			.replace(/[ \t]+\n/g, "\n")
			.replace(/[ \t]{2,}/g, " ");
	}

	function explodeInlineNumberedLists(text) {
		// "Item one.2. Item two.3. Item three" -> separate lines.
		// Pattern: any non-newline content that ends with sentence-end punctuation
		// followed (with optional whitespace) by `<digit>. ` and a capitalized word.
		let next = text;
		next = next.replace(/([^\n])\s*(\d{1,2}\.\s+(?=[A-Z(*_]))/g, (match, before, marker) => {
			if (/^\s*$/.test(before)) return match;
			// Skip when the previous line is an actual numbered list start (e.g. "1.").
			if (/^\s*\d{1,2}\.\s*$/.test(before)) return match;
			return `${before}\n${marker}`;
		});
		return next;
	}

	function explodeInlineBullets(text) {
		// "Item one.- Item two- Item three" -> separate bullet lines.
		let next = text;
		next = next.replace(/([.;:!?])\s*-\s+(?=[A-Z(*_])/g, "$1\n- ");
		next = next.replace(/([.;:!?])\s*•\s+(?=[A-Z(*_])/g, "$1\n- ");
		next = next.replace(/([.;:!?])\s*\*\s+(?=[A-Z(*_])/g, "$1\n- ");
		// Inline bullet without preceding punctuation but with a unit/word boundary,
		// e.g. "Age: 1 point- All other parameters: 0 points".
		// Trigger when we see " <word|digit><dash><space><Capital>" inside a list-like line.
		next = next.replace(/(\b\w+\b)\s*-\s+(?=[A-Z(*_][a-z])/g, (match, before, offset, full) => {
			// Avoid hyphenated words like "well-known" or "Wolff-Parkinson-White".
			// We only split when there is whitespace before the dash in the source.
			const lookback = full.slice(Math.max(0, offset - 6), offset + before.length + 2);
			if (/-\s+\w+-/.test(lookback)) return match;
			if (/\w-\w/.test(match)) return match;
			return `${before}\n- `;
		});
		// Hyphen-as-bullet at line start (•, ·, *).
		next = next.replace(/^[•·*]\s+/gm, "- ");
		return next;
	}

	function repairListItemBoundaries(text) {
		// Ensure list markers always start a new line when preceded by content.
		let next = text;
		next = next.replace(/([^\n])\n(\d{1,2}\.\s+)/g, "$1\n\n$2");
		next = next.replace(/([^\n])\n(- )/g, "$1\n$2");
		return next;
	}

	function collapseRunOnSpaces(text) {
		return text.replace(/[ \t]{2,}/g, " ");
	}

	function autoBoldLabels(text) {
		// On list items, bold the leading label up to the first colon.
		const lines = text.split("\n");
		for (let i = 0; i < lines.length; i += 1) {
			const line = lines[i];
			const listMatch = line.match(/^(\s*(?:[-*]\s+|\d{1,2}\.\s+))(.*)$/);
			if (!listMatch) continue;
			const [, marker, body] = listMatch;
			if (body.startsWith("**")) continue;
			const labelMatch = body.match(LABEL_TOKEN);
			if (!labelMatch) continue;
			const label = labelMatch[1];
			const rest = body.slice(labelMatch[0].length);
			lines[i] = `${marker}**${label}**: ${rest}`;
		}
		return lines.join("\n");
	}

	function emphasizeTotals(text) {
		// "Total PESI score: 1" -> "**Total PESI score:** 1"
		return text.replace(/^(\s*)(Total[^:\n]{1,80}):\s*(\S[^\n]*)$/gm, "$1**$2:** $3");
	}

	function tidyHeadings(text) {
		// If model emits "Calculation:" lines, leave them. If it emits ALL CAPS
		// banner lines like "PARAMETERS:" alone on a line, convert to a markdown
		// heading-like bold so they render with weight rather than a code-block.
		return text.replace(/^([A-Z][A-Z0-9 \-/&]{3,}):\s*$/gm, "**$1**");
	}

	function collapseExcessBlankLines(text) {
		return text.replace(/\n{3,}/g, "\n\n");
	}

	function trimEdges(text) {
		const lines = text.split("\n").map((line) => line.replace(/[ \t]+$/g, ""));
		return lines.join("\n").replace(/^\n+/, "").replace(/\n+$/, "");
	}

	function processBody(text) {
		let next = normalizeWhitespace(text);
		next = explodeInlineNumberedLists(next);
		next = explodeInlineBullets(next);
		next = repairListItemBoundaries(next);
		next = collapseRunOnSpaces(next);
		next = autoBoldLabels(next);
		next = emphasizeTotals(next);
		next = tidyHeadings(next);
		next = collapseExcessBlankLines(next);
		next = trimEdges(next);
		return next;
	}

	function normalizeMarkdownOutput(input) {
		const text = typeof input === "string" ? input : String(input ?? "");
		if (!text.trim()) return "";
		const { text: protectedText, segments } = protect(text);
		const processed = processBody(protectedText);
		return restore(processed, segments);
	}

	window.MarkdownFormatter = {
		normalizeMarkdownOutput,
	};
})();
