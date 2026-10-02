import { useRouterState } from "@tanstack/react-router";
import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlbumView, Comparison, Copy } from "@/shared/api/types";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import {
	renderWithProviders,
	screen,
	userEvent,
	waitFor,
	within,
} from "@/test/render";

import { Duplicate } from "./Duplicate";
import { type Pending, usePending } from "./pending";

const DROP = "20260929-210000";
const ALBUM_URL = `/api/drops/${DROP}/albums/01`;
const APPROVE_URL = `${ALBUM_URL}/approve`;
const ALBUM_ROUTE = `/drops/${DROP}/albums/01`;
const LIBRARY_PATH = "/srv/music/library/C/Chrono Cross/(1999) Chrono Cross";

// What the server sends in `rule` and `reason`. The page speaks from the codes
// through the catalogue, so this text must never reach the screen.
const SERVER_TEXT = "SERVER TEXT";

// The facts a copy's tags and files add, the same on both sides unless a case says otherwise.
const TAGGED = {
	release_id: null,
	album: "Chrono Cross",
	album_artist: "Yasunori Mitsuda",
	date: "1999",
	label: null,
	catalog: null,
	country: null,
	media: null,
	discs: 3,
	encoder: null,
	tag_count: 14,
} satisfies Partial<Copy>;

const TRACKS: Comparison["tracks"] = {
	paired: 67,
	length_differs: 0,
	only_new: 0,
	only_library: 0,
	max_length_diff: 0,
};

// 67 FLAC files at 16-bit 44.1 kHz against 67 MP3s.
function chronoCross(): Comparison {
	return {
		new: {
			folder: `/srv/music/inbox/${DROP}/01/C/Chrono Cross/(1999) Chrono Cross`,
			format: "FLAC",
			lossless: true,
			bit_depth: 16,
			sample_rate: 44100,
			bitrate: 900000,
			bitrate_min: 900000,
			bitrate_max: 900000,
			...TAGGED,
			files: 67,
			length: 8040,
			size: 700_000_000,
			cover: { url: `${ALBUM_URL}/cover`, width: 600, height: 600 },
		},
		library: {
			folder: LIBRARY_PATH,
			format: "MP3",
			lossless: false,
			bit_depth: null,
			sample_rate: 44100,
			bitrate: 320000,
			bitrate_min: 320000,
			bitrate_max: 320000,
			...TAGGED,
			files: 67,
			length: 8040,
			size: 320_000_000,
			cover: null,
		},
		recommended: "new",
		rule: SERVER_TEXT,
		rule_code: "lossless",
		tracks: TRACKS,
	};
}

// The library's copy wins here, and every fact the first fixture shares
// between the columns differs, so a cell read from the wrong side shows.
function hiResLibrary(): Comparison {
	const base: Omit<Copy, "folder" | "cover"> = {
		format: "FLAC",
		lossless: true,
		bit_depth: 16,
		sample_rate: 44100,
		bitrate: 800000,
		bitrate_min: 800000,
		bitrate_max: 800000,
		...TAGGED,
		discs: 1,
		files: 12,
		length: 545,
		size: 250_000_000,
	};
	return {
		new: {
			...base,
			folder: `/srv/music/inbox/${DROP}/01/Y/Yoko Shimomura/(2002) Drammatica`,
			cover: null,
		},
		library: {
			...base,
			folder: "/srv/music/library/Y/Yoko Shimomura/(2002) Drammatica",
			bit_depth: 24,
			sample_rate: 88200,
			bitrate: 999000,
			bitrate_min: 999000,
			bitrate_max: 999000,
			length: 2601,
			size: 987_654_321,
			cover: {
				url: "/api/library/Y/Yoko%20Shimomura/(2002)%20Drammatica/cover.jpg",
				width: 1200,
				height: 1000,
			},
		},
		recommended: "library",
		rule: SERVER_TEXT,
		rule_code: "bit-depth",
		tracks: { ...TRACKS, paired: 12 },
	};
}

function view(over: Partial<AlbumView> = {}): AlbumView {
	return {
		drop: DROP,
		n: "01",
		name: "chrono_cross-original_soundtrack-1999",
		state: "ready",
		stderr: "",
		error: null,
		step: null,
		file: null,
		busy: false,
		preview: null,
		files: [],
		names: { id3: {}, vorbis: {}, mp4: {}, asf: {} },
		library_path: LIBRARY_PATH,
		tree: [],
		extras_to: [],
		decision: null,
		cover: null,
		cover_now: null,
		uploaded: [],
		duplicate: chronoCross(),
		approvable: { ok: true, reason: null, code: null, hold: null },
		replaces: null,
		suggestions: [],
		...over,
	};
}

const json = (body: unknown) =>
	new Response(JSON.stringify(body), {
		headers: { "Content-Type": "application/json; charset=utf-8" },
	});

const APPLYING = {
	state: "applying",
	path: null,
	error: null,
	step: null,
	file: null,
};

// The album answers `before` until approve is posted, then `applying` for two
// polls, then `after`. Two applying answers keep `applying` on screen for a
// poll whether or not the page refetches the moment the POST returns.
function serveApproval(before: AlbumView, after: AlbumView) {
	let approved = false;
	let pollsSinceApprove = 0;
	return fakeFetch({
		[`GET ${ALBUM_URL}`]: () => {
			if (!approved) return json(before);
			pollsSinceApprove++;
			return json(
				pollsSinceApprove <= 2
					? { ...before, state: "applying", busy: true }
					: after,
			);
		},
		[`POST ${APPROVE_URL}`]: () => {
			approved = true;
			return json(APPLYING);
		},
	});
}

const CELL_ROLES = ["cell", "gridcell", "rowheader", "columnheader"];

// In document order. A function matcher misses implicit roles, so each role
// is queried on its own and the results merged.
function cellsOf(row: HTMLElement) {
	return CELL_ROLES.flatMap((role) => within(row).queryAllByRole(role)).sort(
		(a, b) =>
			a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
	);
}

function comparison() {
	const region = screen.getByRole("region", { name: "Already in the library" });
	return within(region).getByRole("table", { name: "Comparison" });
}

// The column a header starts with, counted in the header row, so the test
// holds whether or not the table has a corner cell above the fact names.
function columnIndex(table: HTMLElement, header: RegExp) {
	const headerRow = within(table)
		.getAllByRole("row")
		.find((row) => within(row).queryAllByRole("columnheader").length > 1);
	if (!headerRow) throw new Error("the comparison has no header row");
	const index = cellsOf(headerRow).findIndex((cell) =>
		header.test(cell.textContent?.trim() ?? ""),
	);
	if (index < 0) throw new Error(`no column header matches ${header}`);
	return index;
}

function factRow(table: HTMLElement, fact: string) {
	const row = within(table)
		.getAllByRole("row")
		.find((r) => cellsOf(r)[0]?.textContent?.trim() === fact);
	if (!row) throw new Error(`no row for ${fact}`);
	return row;
}

function cell(fact: string, column: "New" | "In the library") {
	const table = comparison();
	const index = columnIndex(
		table,
		column === "New" ? /^New\b/ : /^In the library\b/,
	);
	const found = cellsOf(factRow(table, fact))[index];
	if (!found) throw new Error(`no ${column} cell in the ${fact} row`);
	return found;
}

const text = (element: HTMLElement) =>
	(element.textContent ?? "").replace(/\s+/g, " ").trim();

function header(column: RegExp) {
	return within(comparison())
		.getAllByRole("columnheader")
		.find((h) => column.test(text(h)));
}

// The route the router is on. The harness renders the component under a
// catch-all route, so the path is read from the router and shown here; a test
// id because it is part of the test and not of the page.
function Where() {
	const path = useRouterState({ select: (s) => s.location.pathname });
	return <p data-testid="where">{path}</p>;
}

// The last pending the harness saw, so a case can make the draft dirty as
// another part of the page would.
let latest: Pending | undefined;

function WithPending({ view }: { view: AlbumView }) {
	const pending = usePending(view);
	latest = pending;
	return <Duplicate view={view} pending={pending} />;
}

function renderDuplicate(v: AlbumView) {
	return renderWithProviders(
		<>
			<WithPending view={v} />
			<Where />
		</>,
		{ route: ALBUM_ROUTE },
	);
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const gets = (calls: Call[]) => calls.filter((c) => c.method === "GET");
const pathOf = (call: Call) => new URL(call.url).pathname;

// Advances the clock a poll at a time until `check` passes.
async function throughPolls(check: () => void, polls = 6) {
	for (let i = 0; i < polls; i++) {
		try {
			check();
			return;
		} catch {
			await vi.advanceTimersByTimeAsync(2_100);
		}
	}
	check();
}

describe("Duplicate", () => {
	let restore: (() => void) | undefined;

	afterEach(() => {
		restore?.();
		restore = undefined;
		latest = undefined;
		vi.useRealTimers();
	});

	describe("the comparison (criteria 47, 48)", () => {
		it("shows both copies' facts side by side, each in its own column", async () => {
			restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(view()) }).restore;
			renderDuplicate(view());

			await screen.findByRole("table", { name: "Comparison" });
			const expected: [string, string, string][] = [
				[
					"Folder",
					`/srv/music/inbox/${DROP}/01/C/Chrono Cross/(1999) Chrono Cross`,
					LIBRARY_PATH,
				],
				["Format", "FLAC", "MP3"],
				["Lossless", "lossless", "lossy"],
				// A lossy file has no bit depth; the cell shows a dash, never `null-bit`.
				["Bit depth", "16-bit", "—"],
				["Sample rate", "44.1 kHz", "44.1 kHz"],
				["Average bitrate", "900 kbps", "320 kbps"],
				["Audio files", "67 on 3 discs", "67 on 3 discs"],
				// 8040 s is 2 h 14 min.
				["Total length", "2:14:00", "2:14:00"],
				// Megabytes of 10^6 bytes, as DropArea counts them.
				["Total size", "700.0 MB", "320.0 MB"],
			];
			for (const [fact, left, right] of expected) {
				expect(text(cell(fact, "New")), `${fact}, New`).toBe(left);
				expect(text(cell(fact, "In the library")), `${fact}, library`).toBe(
					right,
				);
			}
		});

		it("shows the new copy's cover with its size and says the library's copy has none", async () => {
			restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(view()) }).restore;
			renderDuplicate(view());

			await screen.findByRole("table", { name: "Comparison" });
			const newCover = header(/^New\b/)!;
			const image = within(newCover).getByRole("img", {
				name: /^new cover, 600 by 600$/i,
			});
			expect(image).toHaveAttribute("src", `${ALBUM_URL}/cover`);
			expect(text(newCover)).toMatch(/600\D+600/);

			const libraryCover = header(/^In the library\b/)!;
			expect(text(libraryCover)).toMatch(/no cover/);
			expect(within(libraryCover).queryByRole("img")).not.toBeInTheDocument();
		});

		it("reads every cell from its own side when the copies differ in each fact", async () => {
			const v = view({ duplicate: hiResLibrary() });
			restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(v) }).restore;
			renderDuplicate(v);

			await screen.findByRole("table", { name: "Comparison" });
			expect(text(cell("Bit depth", "New"))).toBe("16-bit");
			expect(text(cell("Bit depth", "In the library"))).toBe("24-bit");
			expect(text(cell("Sample rate", "New"))).toBe("44.1 kHz");
			expect(text(cell("Sample rate", "In the library"))).toBe("88.2 kHz");
			expect(text(cell("Average bitrate", "New"))).toBe("800 kbps");
			expect(text(cell("Average bitrate", "In the library"))).toBe("999 kbps");
			// Under an hour the length drops the hours and pads nothing: 545 s is 9:05.
			expect(text(cell("Total length", "New"))).toBe("9:05");
			expect(text(cell("Total length", "In the library"))).toBe("43:21");
			expect(text(cell("Total size", "New"))).toBe("250.0 MB");
			expect(text(cell("Total size", "In the library"))).toBe("987.7 MB");

			expect(text(header(/^New\b/)!)).toMatch(/no cover/);
			const libraryCover = header(/^In the library\b/)!;
			expect(
				within(libraryCover).getByRole("img", {
					name: /^library cover, 1200 by 1000$/i,
				}),
			).toHaveAttribute(
				"src",
				"/api/library/Y/Yoko%20Shimomura/(2002)%20Drammatica/cover.jpg",
			);
			// Width first, then height: 1200 by 1000, not 1000 by 1200.
			expect(text(libraryCover)).toMatch(/1200\D+1000/);
		});

		it("marks the new copy recommended and names the rule that decided", async () => {
			restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(view()) }).restore;
			renderDuplicate(view());

			const region = await screen.findByRole("region", {
				name: "Already in the library",
			});
			expect(text(header(/^New\b/)!)).toMatch(/recommended/i);
			expect(text(header(/^In the library\b/)!)).not.toMatch(/recommended/i);
			expect(
				within(region)
					.getAllByRole("status")
					.map(text)
					.some((line) =>
						/Recommended: keep the new one \(lossless over lossy\)/.test(line),
					),
			).toBe(true);
			expect(
				screen.queryByText(new RegExp(SERVER_TEXT)),
			).not.toBeInTheDocument();
		});

		it("marks the library's copy recommended when the server recommends it, with the server's rule", async () => {
			const v = view({ duplicate: hiResLibrary() });
			restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(v) }).restore;
			renderDuplicate(v);

			const region = await screen.findByRole("region", {
				name: "Already in the library",
			});
			expect(text(header(/^In the library\b/)!)).toMatch(/recommended/i);
			expect(text(header(/^New\b/)!)).not.toMatch(/recommended/i);
			const lines = within(region).getAllByRole("status").map(text);
			expect(
				lines.some((line) =>
					/Recommended: keep the one in the library \(higher bit depth\)/.test(
						line,
					),
				),
			).toBe(true);
			expect(lines.join(" ")).not.toMatch(/the new one/);
			expect(
				screen.queryByText(new RegExp(SERVER_TEXT)),
			).not.toBeInTheDocument();
		});

		// Criterion 48's words for each rule; the server's `rule` text is ignored.
		it.each([
			["more-files", "more audio files"],
			["lossless", "lossless over lossy"],
			["bit-depth", "higher bit depth"],
			["sample-rate", "higher sample rate"],
			["bitrate", "higher average bitrate"],
		] as const)(
			"says the rule from rule_code %s as its catalogue phrase",
			async (code, phrase) => {
				const v = view({
					duplicate: { ...chronoCross(), rule_code: code },
				});
				restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(v) }).restore;
				renderDuplicate(v);

				const region = await screen.findByRole("region", {
					name: "Already in the library",
				});
				const lines = within(region).getAllByRole("status").map(text);
				expect(
					lines.some((line) =>
						line.includes(`Recommended: keep the new one (${phrase})`),
					),
				).toBe(true);
				expect(lines.join(" ")).not.toContain(SERVER_TEXT);
			},
		);
	});

	describe("the two buttons (criteria 47, 57)", () => {
		it("offers Keep the new one and Keep the one in the library in place of Approve, every control named", async () => {
			restore = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(view()) }).restore;
			renderDuplicate(view());

			expect(
				await screen.findByRole("button", { name: "Keep the new one" }),
			).toBeEnabled();
			expect(
				screen.getByRole("button", { name: "Keep the one in the library" }),
			).toBeEnabled();
			expect(
				screen.queryByRole("button", { name: /approve/i }),
			).not.toBeInTheDocument();
			for (const control of [
				...screen.queryAllByRole("button"),
				...screen.queryAllByRole("link"),
				...screen.queryAllByRole("checkbox"),
				...screen.queryAllByRole("radio"),
				...screen.queryAllByRole("textbox"),
			]) {
				expect(control).toHaveAccessibleName();
			}
		});

		it("disables both buttons while a process runs and says so in their names", async () => {
			const v = view({ busy: true, state: "identifying" });
			const fake = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(v) });
			restore = fake.restore;
			const user = userEvent.setup();
			renderDuplicate(v);

			const keepNew = await screen.findByRole("button", {
				name: "Keep the new one: a process is running",
			});
			const keepLibrary = screen.getByRole("button", {
				name: "Keep the one in the library: a process is running",
			});
			expect(keepNew).toBeDisabled();
			expect(keepLibrary).toBeDisabled();

			await user.click(keepNew);
			await user.click(keepLibrary);
			expect(posts(fake.calls)).toEqual([]);
		});

		it("disables both buttons while the draft has a change the preview does not reflect", async () => {
			const fake = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(view()) });
			restore = fake.restore;
			const user = userEvent.setup();
			renderDuplicate(view());

			expect(
				await screen.findByRole("button", { name: "Keep the new one" }),
			).toBeEnabled();
			act(() => latest!.setGame("neither"));

			const keepNew = await screen.findByRole("button", {
				name: "Keep the new one: update the preview first",
			});
			const keepLibrary = screen.getByRole("button", {
				name: "Keep the one in the library: update the preview first",
			});
			expect(keepNew).toBeDisabled();
			expect(keepLibrary).toBeDisabled();
			await user.click(keepNew);
			await user.click(keepLibrary);
			expect(posts(fake.calls)).toEqual([]);

			// Back to what the preview reflects: both are on offer again.
			act(() => latest!.reset());
			expect(
				await screen.findByRole("button", { name: "Keep the new one" }),
			).toBeEnabled();
			expect(
				screen.getByRole("button", { name: "Keep the one in the library" }),
			).toBeEnabled();
		});

		// The server's `reason` is SERVER TEXT; the name is built from `code` and `hold`.
		it("stops only Keep the new one while a collision holds the album, naming it from its code", async () => {
			const v = view({
				approvable: {
					ok: false,
					reason: SERVER_TEXT,
					code: "held",
					hold: {
						kind: "collision",
						detail:
							"C/Chrono Cross/(1999) Chrono Cross is planned by album 02 too",
					},
				},
			});
			const fake = fakeFetch({ [`GET ${ALBUM_URL}`]: () => json(v) });
			restore = fake.restore;
			renderDuplicate(v);

			expect(
				await screen.findByRole("button", {
					name: "Keep the new one: held: collision: C/Chrono Cross/(1999) Chrono Cross is planned by album 02 too",
				}),
			).toBeDisabled();
			expect(
				screen.getByRole("button", { name: "Keep the one in the library" }),
			).toBeEnabled();
			for (const button of screen.getAllByRole("button")) {
				expect(button).not.toHaveAccessibleName(new RegExp(SERVER_TEXT));
			}
		});

		it("accepts a preview not accepted yet before keeping the new one", async () => {
			const v = view({
				approvable: {
					ok: false,
					reason: SERVER_TEXT,
					code: "not-accepted",
					hold: null,
				},
			});
			const fake = fakeFetch({
				[`GET ${ALBUM_URL}`]: () => json(v),
				[`POST ${ALBUM_URL}/decision`]: () => json({ state: "queued" }),
			});
			restore = fake.restore;
			const user = userEvent.setup();
			renderDuplicate(v);

			await user.click(
				await screen.findByRole("button", { name: "Keep the new one" }),
			);

			await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
			const [post] = posts(fake.calls);
			expect(pathOf(post!)).toBe(`${ALBUM_URL}/decision`);
			expect(JSON.parse(post!.body)).toMatchObject({ action: "accept" });
		});

		it("can be reached and pressed from the keyboard", async () => {
			const fake = serveApproval(
				view(),
				view({ state: "in the library", duplicate: null }),
			);
			restore = fake.restore;
			const user = userEvent.setup();
			renderDuplicate(view());

			const keepNew = await screen.findByRole("button", {
				name: "Keep the new one",
			});
			for (let i = 0; i < 10 && document.activeElement !== keepNew; i++) {
				await user.tab();
			}
			expect(keepNew).toHaveFocus();
			await user.keyboard("{Enter}");

			await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
			expect(JSON.parse(posts(fake.calls)[0]!.body)).toEqual({ keep: "new" });
		});
	});

	describe("Keep the new one (criterion 49)", () => {
		it("posts keep new to the album's approve, then polls until the album is in the library and shows where", async () => {
			vi.useFakeTimers({ shouldAdvanceTime: true });
			const fake = serveApproval(
				view(),
				view({
					state: "in the library",
					library_path: LIBRARY_PATH,
					duplicate: null,
				}),
			);
			restore = fake.restore;
			const user = userEvent.setup({
				advanceTimers: vi.advanceTimersByTime,
			});
			renderDuplicate(view());

			await user.click(
				await screen.findByRole("button", { name: "Keep the new one" }),
			);

			await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
			const [post] = posts(fake.calls);
			expect(pathOf(post!)).toBe(APPROVE_URL);
			expect(JSON.parse(post!.body)).toEqual({ keep: "new" });

			// While apply runs both choices wait; the running state itself is the review bar's to show.
			await throughPolls(() =>
				expect(
					screen.getByRole("button", {
						name: "Keep the new one: a process is running",
					}),
				).toBeDisabled(),
			);
			const statusText = () => screen.queryAllByRole("status").map(text);
			await throughPolls(() =>
				expect(
					statusText().some(
						(s) => s.includes("in the library") && s.includes(LIBRARY_PATH),
					),
				).toBe(true),
			);
			for (const get of gets(fake.calls)) {
				expect(pathOf(get)).toBe(ALBUM_URL);
			}

			// Once the album is in the library nothing runs, so the polling stops.
			const settled = gets(fake.calls).length;
			await vi.advanceTimersByTimeAsync(10_000);
			expect(gets(fake.calls)).toHaveLength(settled);
		});

		// Whether Move is offered here is left to the review bar (criterion 41).
		it("shows which step failed on which file when the move is not verified", async () => {
			vi.useFakeTimers({ shouldAdvanceTime: true });
			const error =
				"the SHA-256 of 03. Track.flac in the library differs from the one recorded";
			const fake = serveApproval(
				view(),
				view({
					state: "written, not moved",
					error,
					step: 4,
					file: "03. Track.flac",
				}),
			);
			restore = fake.restore;
			const user = userEvent.setup({
				advanceTimers: vi.advanceTimersByTime,
			});
			renderDuplicate(view());

			await user.click(
				await screen.findByRole("button", { name: "Keep the new one" }),
			);

			await throughPolls(() => screen.getByRole("alert"));
			const alert = screen.getByRole("alert");
			expect(text(alert)).toContain(error);
			expect(text(alert)).toContain("step 4 failed on 03. Track.flac");
		});
	});

	describe("Keep the one in the library (criterion 50)", () => {
		it("posts keep library to the album's approve and goes back to the drops", async () => {
			const fake = fakeFetch({
				[`GET ${ALBUM_URL}`]: () => json(view()),
				[`POST ${APPROVE_URL}`]: () => json({ state: "discarded" }),
			});
			restore = fake.restore;
			const user = userEvent.setup();
			renderDuplicate(view());

			expect(await screen.findByTestId("where")).toHaveTextContent(ALBUM_ROUTE);
			await user.click(
				await screen.findByRole("button", {
					name: "Keep the one in the library",
				}),
			);

			await waitFor(() => expect(posts(fake.calls)).toHaveLength(1));
			const [post] = posts(fake.calls);
			expect(pathOf(post!)).toBe(APPROVE_URL);
			expect(JSON.parse(post!.body)).toEqual({ keep: "library" });
			await waitFor(() =>
				expect(screen.getByTestId("where").textContent).toBe("/"),
			);
		});
	});
});
