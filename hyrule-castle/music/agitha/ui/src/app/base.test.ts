import { fileURLToPath } from "node:url";

import { loadConfigFromFile, type UserConfig } from "vite";
import { describe, expect, it } from "vitest";

// Read at the time the test runs, as favicon.test.ts reads its files.
const TEXT = import.meta.glob<string>(
	["/index.html", "/src/shared/i18n/locale.ts"],
	{ query: "?raw", import: "default", eager: true },
);

function read(path: string): string {
	const content = TEXT[path];
	if (content === undefined) throw new Error(`${path} is missing`);
	return content;
}

// Loaded as `vite build` loads it. An import through Vitest would not do: Vite
// rewrites the config's `new URL("./src", import.meta.url)` into an http: URL.
async function viteConfig(): Promise<UserConfig> {
	const loaded = await loadConfigFromFile(
		{ command: "build", mode: "production" },
		fileURLToPath(new globalThis.URL("../../vite.config.ts", import.meta.url)),
	);
	if (!loaded) throw new Error("vite.config.ts is missing");
	return loaded.config;
}

// An album's address is two folders deep, so anything the page loads by a
// relative URL is asked for under /drops/<drop>/albums/ and gets index.html.
describe("what the page loads, from an album's address", () => {
	it("builds its scripts and styles under /", async () => {
		expect((await viteConfig()).base).toBe("/");
	});

	it("links every favicon from the root", () => {
		const { head } = new DOMParser().parseFromString(
			read("/index.html"),
			"text/html",
		);
		const hrefs = [
			...head.querySelectorAll(
				'link[rel~="icon"], link[rel="apple-touch-icon"]',
			),
		].map((link) => link.getAttribute("href"));

		expect(hrefs.length).toBeGreaterThan(0);
		for (const href of hrefs) expect(href).toMatch(/^\//);
	});

	it("fetches the Spanish catalogue from /locales/", () => {
		const source = read("/src/shared/i18n/locale.ts");

		expect(source).toMatch(/["'`]\/locales\//);
		expect(source).not.toMatch(/["'`](\.\/)?locales\//);
	});
});
