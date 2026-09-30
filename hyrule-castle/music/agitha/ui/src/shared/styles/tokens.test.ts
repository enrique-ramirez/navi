import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// Read from disk: Vitest hands a test an empty string for any CSS import,
// `?raw` included, so an import would pass every check below on no content.
const SRC = join(import.meta.dirname, "../..");
const TOKENS = "shared/styles/tokens.css";

const stylesheets = () =>
	(readdirSync(SRC, { recursive: true, encoding: "utf8" }) as string[])
		.filter((path) => path.endsWith(".css"))
		.sort()
		.map((path) => ({ path, css: readFileSync(join(SRC, path), "utf8") }));

const tokens = () => {
	const path = join(SRC, TOKENS);
	if (!existsSync(path)) throw new Error(`src/${TOKENS} is missing`);
	return readFileSync(path, "utf8");
};

type Rule = { selectors: string[]; declarations: [string, string][] };

// Innermost blocks only, which is every rule that holds declarations; an
// `@media` wrapper is skipped and the rules inside it are still read.
function rulesIn(css: string): Rule[] {
	const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
	return [...bare.matchAll(/([^{}]*)\{([^{}]*)\}/g)].map(([, head, body]) => ({
		selectors: head
			.split(",")
			.map((selector) => selector.trim())
			.filter(Boolean),
		declarations: [...body.matchAll(/([-\w]+)\s*:\s*([^;]+)/g)].map(
			([, property, value]): [string, string] => [property, value.trim()],
		),
	}));
}

const OPAQUE = String.raw`\s*(?:\/\s*(?:1|1\.0+|100%)\s*)?\)`;
const NUMBER = String.raw`[\d.]+(?:deg)?|none`;

// Pure black and pure white, however they are spelled. OKLCH is on the list
// because it is what tokens.css is written in: `oklch(1 0 0)` is `#fff`.
// A translucent black or white (a shadow, a scrim) is not pure and not flagged.
const PURE = [
	/#(?:000|fff)f?(?![\da-f])/i,
	/#(?:000000|ffffff)(?:ff)?(?![\da-f])/i,
	/(?<![-\w])(?:black|white)(?![-\w])/i,
	new RegExp(String.raw`rgba?\(\s*0[\s,]+0[\s,]+0${OPAQUE}`, "i"),
	new RegExp(String.raw`rgba?\(\s*255[\s,]+255[\s,]+255${OPAQUE}`, "i"),
	new RegExp(
		String.raw`oklch\(\s*(?:0|0%|1|1\.0+|100%)\s+(?:0|0\.0+|0%)\s+(?:${NUMBER})${OPAQUE}`,
		"i",
	),
	new RegExp(
		String.raw`hsla?\(\s*(?:${NUMBER})[\s,]+[\d.]+%?[\s,]+(?:0|100)%${OPAQUE}`,
		"i",
	),
];

const isLight = (selector: string) =>
	/\[data-theme=(["']?)light\1\]/.test(selector);

const setsAColour = (rule: Rule) =>
	rule.declarations.some(
		([property, value]) => property.startsWith("--") && /oklch\(/i.test(value),
	);

describe("tokens.css", () => {
	it("sets the dark theme's colours on :root", () => {
		const dark = rulesIn(tokens()).filter((rule) =>
			rule.selectors.includes(":root"),
		);

		expect(dark.some(setsAColour), ":root sets no OKLCH custom property").toBe(
			true,
		);
	});

	it('sets the light theme\'s colours under [data-theme="light"]', () => {
		const light = rulesIn(tokens()).filter((rule) =>
			rule.selectors.some(isLight),
		);

		expect(
			light.some(setsAColour),
			'[data-theme="light"] sets no OKLCH custom property',
		).toBe(true);
	});

	it("gives the light theme values of its own, not the dark ones restated", () => {
		// Of the custom properties both blocks set, at least one must differ.
		const rules = rulesIn(tokens());
		const values = (pick: (rule: Rule) => boolean) =>
			new Map(
				rules
					.filter(pick)
					.flatMap((rule) => rule.declarations)
					.filter(([property]) => property.startsWith("--")),
			);
		const dark = values((rule) => rule.selectors.includes(":root"));
		const light = values((rule) => rule.selectors.some(isLight));

		const differing = [...light].filter(
			([property, value]) => dark.has(property) && dark.get(property) !== value,
		);
		expect(differing.length).toBeGreaterThan(0);
	});
});

describe("the page's stylesheets", () => {
	it("use no pure black and no pure white anywhere", () => {
		const sheets = stylesheets();
		expect(
			sheets.map(({ path }) => path),
			`src/${TOKENS} is missing`,
		).toContain(TOKENS);

		const found = sheets.flatMap(({ path: file, css }) =>
			rulesIn(css).flatMap((rule) =>
				rule.declarations
					.filter(([, value]) => PURE.some((pure) => pure.test(value)))
					.map(([property, value]) => `${file}: ${property}: ${value}`),
			),
		);

		expect(found).toEqual([]);
	});
});
