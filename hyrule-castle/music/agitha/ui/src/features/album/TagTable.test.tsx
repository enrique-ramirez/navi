import { describe, expect, it } from "vitest";

import type { AlbumView, PlanEntry, PlanFile } from "@/shared/api/types";
import autoClean from "@/test/fixtures/auto-clean/plan.json";
import { renderWithProviders, screen, within } from "@/test/render";

import { TagTable } from "./TagTable";

function freshPreview(): PlanEntry {
	// A deep copy per test, so an edit made for one case never leaks into another.
	return structuredClone(autoClean.albums[0]) as unknown as PlanEntry;
}

// The engine writes a picture frame's key as mutagen's `HashKey` (`APIC:` for
// one with no description). No fixture holds a binary frame yet, so the value
// takes the shape `types.ts` names: the key, then `(N bytes)`.
const PICTURE = "APIC: (12345 bytes)";

function editedPreview(): PlanEntry {
	const preview = freshPreview();
	const first = preview.files[0] as PlanFile;
	const second = preview.files[1] as PlanFile;
	first.before = {
		...first.before,
		"TXXX:MOOD": ["Mellow"],
		"APIC:": [PICTURE],
		// Removed by the residue rule below.
		TENC: ["LAME 3.99"],
		// Gone from `after` too, but the residue entry naming it is another file's.
		TSSE: ["LAME 3.99.5"],
	};
	first.after = {
		...first.after,
		"TXXX:MOOD": ["Mellow"],
		"APIC:": [PICTURE],
		TCON: ["rock", "indie"],
		TCOM: ["Yoko Kanno"],
		TSOC: ["Kanno, Yoko"],
	};
	preview.residue = [
		{ file: first.source, key: "TENC", value: null, rule: "encoded by" },
		{ file: second.source, key: "TSSE", value: null, rule: "encoder" },
	];
	return preview;
}

function albumView(preview: PlanEntry): AlbumView {
	return {
		drop: "20260929-210000",
		n: "01",
		name: "Clean Album",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview,
		files: [],
		names: {
			id3: {
				TPE2: "Album artist",
				TCOM: "Composer",
				TSOC: "Composer sort order",
				TIT2: "Title",
			},
			vorbis: {},
			mp4: {},
			asf: {},
		},
		library_path: `/srv/music/library/${preview.destination}`,
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		duplicate: null,
		approvable: { ok: true, reason: null, code: null, hold: null },
	};
}

async function tagTable() {
	return screen.findByRole("table", { name: "Tags" });
}

function inOrder(elements: HTMLElement[]) {
	return [...elements].sort((a, b) =>
		a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
	);
}

// The Tag cell may be a row header or a plain cell.
function cellsOf(row: HTMLElement) {
	return inOrder([
		...within(row).queryAllByRole("rowheader"),
		...within(row).queryAllByRole("cell"),
	]);
}

function bodyRows(table: HTMLElement) {
	return within(table)
		.getAllByRole("row")
		.filter((row) => within(row).queryAllByRole("columnheader").length === 0);
}

function columnIndex(table: HTMLElement, name: string) {
	const headers = within(table)
		.getAllByRole("columnheader")
		.map((header) => header.textContent?.trim());
	const index = headers.indexOf(name);
	expect(
		index,
		`a column named ${name} among ${headers.join(", ")}`,
	).toBeGreaterThanOrEqual(0);
	return index;
}

function rowFor(table: HTMLElement, tag: string) {
	const rows = bodyRows(table).filter(
		(row) => cellsOf(row)[0]?.textContent?.trim() === tag,
	);
	expect(rows, `rows whose Tag is ${tag}`).toHaveLength(1);
	return rows[0] as HTMLElement;
}

function cell(
	table: HTMLElement,
	tag: string,
	column: "Tag" | "Before" | "After",
) {
	const found = cellsOf(rowFor(table, tag))[columnIndex(table, column)];
	expect(found, `the ${column} cell of ${tag}`).toBeDefined();
	return found as HTMLElement;
}

// What assistive technology reads for the row: its text and any aria-label in it.
// A word match, so a value such as `unchanged` never counts.
function saysChanged(row: HTMLElement) {
	const labels = [
		row,
		...row.querySelectorAll<HTMLElement>("[aria-label]"),
	].map((element) => element.getAttribute("aria-label") ?? "");
	return [row.textContent ?? "", ...labels].some((text) =>
		/\bchanged\b/i.test(text),
	);
}

const UNITS: Record<string, number[]> = {
	b: [1],
	bytes: [1],
	kb: [1e3, 2 ** 10],
	kib: [2 ** 10],
};

function showsSize(text: string, bytes: number) {
	return [...text.matchAll(/(\d[\d,]*(?:\.\d+)?)\s*(bytes|Ki?B|kB|B)\b/g)].some(
		([, shown = "", unit = ""]) =>
			(UNITS[unit.toLowerCase()] ?? []).some(
				(factor) =>
					Math.abs(Number(shown.replace(/,/g, "")) * factor - bytes) / bytes <=
					0.06,
			),
	);
}

describe("the tag table for one track", () => {
	it("is a table named Tags with the columns Tag, Before and After", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-1" />,
		);

		const table = await tagTable();

		expect(
			within(table)
				.getAllByRole("columnheader")
				.map((header) => header.textContent?.trim()),
		).toEqual(["Tag", "Before", "After"]);
	});

	it("lists every tag the track has before or after, once each", async () => {
		const preview = editedPreview();
		const first = preview.files[0] as PlanFile;
		const union = new Set([
			...Object.keys(first.before),
			...Object.keys(first.after),
		]);
		renderWithProviders(<TagTable view={albumView(preview)} position="1-1" />);

		const table = await tagTable();

		// The fixture's 23 keys after, and six more this file adds.
		expect(union.size).toBe(29);
		expect(bodyRows(table)).toHaveLength(union.size);
		for (const key of [
			"TENC",
			"TSSE",
			"TALB",
			"TXXX:MusicBrainz Album Id",
			"APIC:",
		]) {
			rowFor(table, key);
		}
	});

	it("shows the track picked by position, not the first", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-2" />,
		);

		const table = await tagTable();

		expect(cell(table, "Title", "Before")).toHaveTextContent("two");
		expect(cell(table, "Title", "After")).toHaveTextContent("Two");
		// TXXX:MOOD was only added to 1-1.
		expect(
			bodyRows(table).filter(
				(row) => cellsOf(row)[0]?.textContent?.trim() === "TXXX:MOOD",
			),
		).toHaveLength(0);
	});

	it("names a known tag in words and an unknown one by its raw key, the raw key kept as the title", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-1" />,
		);

		const table = await tagTable();

		for (const [name, key] of [
			["Album artist", "TPE2"],
			["Composer", "TCOM"],
			["Composer sort order", "TSOC"],
			["Title", "TIT2"],
		] as const) {
			const tag = cell(table, name, "Tag");
			const titled = tag.closest("[title]") ?? tag.querySelector("[title]");
			expect(titled?.getAttribute("title"), name).toBe(key);
		}
		// Unknown to `names`, so shown as they are in the file.
		rowFor(table, "TXXX:MOOD");
		rowFor(table, "TALB");
		expect(
			bodyRows(table).filter(
				(row) => cellsOf(row)[0]?.textContent?.trim() === "TPE2",
			),
		).toHaveLength(0);
	});

	it("shows the value as dropped and as written, several values joined with a slash, empty where absent", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-1" />,
		);

		const table = await tagTable();

		expect(cell(table, "TXXX:MOOD", "Before")).toHaveTextContent("Mellow");
		expect(cell(table, "TXXX:MOOD", "After")).toHaveTextContent("Mellow");
		expect(cell(table, "Title", "Before")).toHaveTextContent("one");
		expect(cell(table, "Title", "After")).toHaveTextContent("One");
		expect(cell(table, "TCON", "After")).toHaveTextContent("rock / indie");
		expect(cell(table, "TCON", "Before").textContent?.trim()).toBe("");
		expect(cell(table, "Composer", "After")).toHaveTextContent("Yoko Kanno");
		expect(cell(table, "Composer sort order", "After")).toHaveTextContent(
			"Kanno, Yoko",
		);
	});

	it("marks a row whose value changes and leaves an unchanged one unmarked", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-1" />,
		);

		const table = await tagTable();

		expect(saysChanged(rowFor(table, "Title"))).toBe(true);
		expect(saysChanged(rowFor(table, "TDRC"))).toBe(true);
		// Added by the engine: absent before, so it changes too.
		expect(saysChanged(rowFor(table, "Composer"))).toBe(true);
		for (const same of ["TALB", "TPE1", "TXXX:MOOD", "APIC:"]) {
			expect(saysChanged(rowFor(table, same)), same).toBe(false);
		}
	});

	it("says which residue rule removed a tag, and only for this track's own residue", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-1" />,
		);

		const table = await tagTable();

		expect(cell(table, "TENC", "Before")).toHaveTextContent("LAME 3.99");
		expect(cell(table, "TENC", "After")).toHaveTextContent(
			"removed: encoded by",
		);
		// The `encoder` entry is for 02 two.mp3, whose file is keyed by source, not position.
		expect(rowFor(table, "TSSE")).not.toHaveTextContent("removed");
		expect(rowFor(table, "TALB")).not.toHaveTextContent("removed");
	});

	it("shows a binary frame as its kind and size", async () => {
		renderWithProviders(
			<TagTable view={albumView(editedPreview())} position="1-1" />,
		);

		const table = await tagTable();

		for (const column of ["Before", "After"] as const) {
			const text = cell(table, "APIC:", column).textContent?.trim() ?? "";
			expect(text, column).toMatch(/^APIC:?, /);
			expect(showsSize(text, 12345), `${column}: ${text}`).toBe(true);
		}
	});
});

describe("the tag table for all tracks", () => {
	it("shows a value every track agrees on, and says differs where the tracks disagree", async () => {
		renderWithProviders(
			<TagTable view={albumView(freshPreview())} position="all" />,
		);

		const table = await tagTable();

		expect(cell(table, "TALB", "Before")).toHaveTextContent("Clean Album");
		expect(cell(table, "TALB", "After")).toHaveTextContent("Clean Album");
		expect(cell(table, "TDRC", "Before")).toHaveTextContent("1989");
		expect(cell(table, "TDRC", "After")).toHaveTextContent("2010-05-24");
		expect(cell(table, "TALB", "After")).not.toHaveTextContent("differs");
		// One, Two and Three: no single value to show.
		for (const column of ["Before", "After"] as const) {
			const title = cell(table, "Title", column);
			expect(title, column).toHaveTextContent("differs");
			expect(title, column).not.toHaveTextContent(/\b(one|One)\b/);
		}
		expect(cell(table, "TRCK", "After")).toHaveTextContent("differs");
	});
});
