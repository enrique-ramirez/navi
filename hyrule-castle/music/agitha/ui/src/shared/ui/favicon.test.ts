import { describe, expect, it } from "vitest";

// Read at the time the test runs; a missing file is a missing key, so each case
// below names the file it lacks.
const TEXT = import.meta.glob<string>(["/public/favicon.svg", "/index.html"], {
	query: "?raw",
	import: "default",
	eager: true,
});
const PNG = import.meta.glob<string>("/public/*.png", {
	query: "?inline",
	import: "default",
	eager: true,
});

function read<T>(files: Record<string, T>, path: string): T {
	const content = files[path];
	if (content === undefined) throw new Error(`${path} is missing`);
	return content;
}

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

// Width and height are the first two fields of IHDR, which a PNG must put first.
function png(path: string) {
	const inline = read(PNG, path);
	const base64 = inline.slice(inline.indexOf(",") + 1);
	const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
	const view = new DataView(bytes.buffer);
	return {
		signature: [...bytes.subarray(0, 8)],
		chunk: String.fromCharCode(...bytes.subarray(12, 16)),
		width: view.getUint32(16),
		height: view.getUint32(20),
	};
}

const svg = () =>
	new DOMParser().parseFromString(
		read(TEXT, "/public/favicon.svg"),
		"image/svg+xml",
	);

describe("the favicons", () => {
	it("keep favicon.svg under 1 KB", () => {
		const bytes = new TextEncoder().encode(read(TEXT, "/public/favicon.svg"));

		expect(bytes.length).toBeLessThan(1024);
	});

	it("make favicon.svg one drawn <svg> with a viewBox", () => {
		const text = read(TEXT, "/public/favicon.svg");
		const root = svg().documentElement;

		expect(root.localName, "favicon.svg does not parse as SVG").toBe("svg");
		expect(root.getAttribute("viewBox")).toMatch(
			/^\s*[-\d.]+(?:[\s,]+[-\d.]+){3}\s*$/,
		);
		expect(text.match(/<svg\b/g)).toHaveLength(1);
		expect(
			root.querySelectorAll(
				"path, circle, ellipse, line, polyline, polygon, rect",
			).length,
		).toBeGreaterThan(0);
		// A bitmap wrapped in SVG is not a drawing, and would blur at 16 px.
		expect(root.querySelector("image")).toBe(null);
	});

	it("ship a 32 px PNG", () => {
		expect(png("/public/favicon-32.png")).toEqual({
			signature: PNG_SIGNATURE,
			chunk: "IHDR",
			width: 32,
			height: 32,
		});
	});

	it("ship a 180 px touch icon", () => {
		expect(png("/public/apple-touch-icon.png")).toEqual({
			signature: PNG_SIGNATURE,
			chunk: "IHDR",
			width: 180,
			height: 180,
		});
	});

	it("are linked from index.html, the PNGs for browsers that take no SVG", () => {
		const { head } = new DOMParser().parseFromString(
			read(TEXT, "/index.html"),
			"text/html",
		);
		const href = (selector: string) =>
			head.querySelector(selector)?.getAttribute("href") ?? null;

		expect({
			svg: href('link[rel~="icon"][type="image/svg+xml"]'),
			png: href('link[rel~="icon"][type="image/png"][sizes="32x32"]'),
			touch: href('link[rel="apple-touch-icon"]'),
		}).toEqual({
			svg: "/favicon.svg",
			png: "/favicon-32.png",
			touch: "/apple-touch-icon.png",
		});
	});
});
