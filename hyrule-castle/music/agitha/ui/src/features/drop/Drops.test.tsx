import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlbumSummary, Drop } from "@/shared/api/types";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import {
	renderWithProviders,
	screen,
	userEvent,
	waitFor,
	within,
} from "@/test/render";

import { Drops } from "./Drops";

function album(
	n: string,
	name: string,
	over: Partial<AlbumSummary> = {},
): AlbumSummary {
	return {
		n,
		name,
		state: "ready",
		title: null,
		artist: null,
		year: null,
		destination: null,
		duplicate_of: null,
		stderr: "",
		error: null,
		busy: false,
		actions: ["discard"],
		...over,
	};
}

function drop(id: string, over: Partial<Drop> = {}): Drop {
	return {
		id,
		state: "ready",
		started: "2026-09-29T21:00:00",
		items: [],
		ignored: [],
		refused: [],
		albums: [],
		actions: ["discard"],
		received: { files: 0, bytes: 0 },
		error: null,
		...over,
	};
}

const STDERR = [
	"Traceback (most recent call last):",
	'  File "/usr/local/bin/musiclib", line 8, in <module>',
	"ValueError: no release matches 67 tracks",
].join("\n");

const BUSY = "20260929-210000";
const INCOMPLETE = "20260929-220000-2";

// One album per thing the list must show. Album 06 is being identified, so its
// drop offers no Discard either.
const busyDrop = drop(BUSY, {
	actions: [],
	albums: [
		album("01", "Pariahs Child rip", {
			title: "Pariah's Child",
			artist: "Sonata Arctica",
			year: "2014",
		}),
		album("02", "chrono_cross-original_soundtrack-1999", {
			state: "identify failed",
			stderr: STDERR,
			actions: ["retry", "discard"],
		}),
		album("03", "llly-2019-web", {
			state: "written, not moved",
			title: "Blockbuster",
			artist: "La La Love You",
			actions: ["move", "discard"],
		}),
		album("04", "Por que me mirais asi", { duplicate_of: "05" }),
		album("05", "Bonus tracks", { duplicate_of: "04" }),
		album("06", "Ecliptica rip", {
			state: "identifying",
			busy: true,
			actions: [],
		}),
		album("07", "Silence rip", { state: "in the library", actions: [] }),
	],
});

const incompleteDrop = drop(INCOMPLETE, {
	state: "incomplete",
	started: "2026-09-29T22:00:00",
	items: [
		{
			name: "Ecliptica",
			kind: "folder",
			files: [{ path: "01.mp3", size: 10 }],
		},
	],
	received: { files: 0, bytes: 0 },
});

let server: ReturnType<typeof fakeFetch> | undefined;

afterEach(() => {
	server?.restore();
	server = undefined;
	vi.useRealTimers();
});

const ok = () => new Response(null, { status: 204 });

function serve(list: () => Drop[], discardAlbum: () => Response = ok) {
	server = fakeFetch({
		"GET /api/drops": () => Response.json(list()),
		"POST /api/drops/:drop/discard": ok,
		"POST /api/drops/:drop/albums/:n/discard": discardAlbum,
		"POST /api/drops/:drop/albums/:n/retry": ok,
		"POST /api/drops/:drop/albums/:n/move": ok,
	});
	return server;
}

const gets = (calls: Call[]) =>
	calls.filter((call) => call.method === "GET").length;
const posted = (calls: Call[]) =>
	calls
		.filter((call) => call.method === "POST")
		.map((call) => new URL(call.url).pathname);

// The innermost list item or table row holding `text`, whichever the list is built from.
function rowOf(text: string): HTMLElement {
	const rows = [
		...screen.queryAllByRole("listitem"),
		...screen.queryAllByRole("row"),
	].filter((row) => row.textContent?.includes(text));
	const inner = rows.filter(
		(row) => !rows.some((other) => other !== row && row.contains(other)),
	);
	if (inner.length !== 1)
		throw new Error(`${inner.length} rows hold "${text}"`);
	return inner[0]!;
}

async function shown(text: string) {
	await screen.findAllByText(new RegExp(literally(text)));
	return rowOf(text);
}

function literally(text: string) {
	return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const DISCARD = /^Discard/;

// A discard only posts once the dialog it opens is confirmed.
async function confirmDiscard() {
	const dialog = await screen.findByRole("alertdialog");
	await userEvent.click(
		within(dialog).getByRole("button", { name: "Discard" }),
	);
}

// A drop's own Discard: one outside every album row, under that drop's heading
// and no other drop's.
function dropDiscards(id: string): HTMLElement[] {
	const heading = screen.getByRole("heading", {
		name: new RegExp(literally(id)),
	});
	const dropHeadings = screen
		.getAllByRole("heading")
		.filter((h) => /\d{8}-\d{6}/.test(h.textContent ?? ""));
	const albumRows = screen
		.getAllByRole("link", { name: /^Open/ })
		.map((link) =>
			link.closest<HTMLElement>('li, tr, [role="listitem"], [role="row"]'),
		);
	const loose = screen
		.queryAllByRole("button", { name: DISCARD })
		.filter((button) => !albumRows.some((row) => row?.contains(button)));
	for (let scope = heading.parentElement; scope; scope = scope.parentElement) {
		if (
			dropHeadings.some((other) => other !== heading && scope.contains(other))
		)
			break;
		const found = loose.filter((button) => scope.contains(button));
		if (found.length > 0) return found;
	}
	return [];
}

describe("Drops", () => {
	it("shows each album's folder name, its title and artist where known, and its state", async () => {
		serve(() => [busyDrop, incompleteDrop]);
		renderWithProviders(<Drops />);

		for (const each of busyDrop.albums) {
			const row = await shown(each.name);
			expect(within(row).getByText(each.state)).toBeInTheDocument();
			if (each.title) expect(row).toHaveTextContent(each.title);
			if (each.artist) expect(row).toHaveTextContent(each.artist);
		}
		expect(
			screen.getByRole("heading", { name: new RegExp(BUSY) }),
		).toBeInTheDocument();
		expect(
			screen.getByRole("heading", { name: new RegExp(literally(INCOMPLETE)) }),
		).toBeInTheDocument();
	});

	it("links every album to its own address", async () => {
		serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		for (const each of busyDrop.albums) {
			const row = await shown(each.name);
			expect(within(row).getByRole("link", { name: /^Open/ })).toHaveAttribute(
				"href",
				`/drops/${BUSY}/albums/${each.n}`,
			);
		}
	});

	it("shows a failed identify's stderr line for line and offers Retry and Discard, and Retry posts it", async () => {
		const { calls } = serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		const row = await shown("chrono_cross-original_soundtrack-1999");
		const pre = within(row).getByText(
			(_, element) => element?.tagName === "PRE",
		);
		expect(pre).toHaveTextContent(STDERR, { normalizeWhitespace: false });
		expect(
			within(row).getByRole("button", { name: DISCARD }),
		).toBeInTheDocument();
		expect(
			within(row).queryByRole("button", { name: /^Move into the library/ }),
		).toBeNull();
		// An album with nothing on stderr shows no empty block.
		expect(rowOf("Pariahs Child rip").querySelector("pre")).toBeNull();

		await userEvent.click(within(row).getByRole("button", { name: /^Retry/ }));
		await waitFor(() =>
			expect(posted(calls)).toEqual([`/api/drops/${BUSY}/albums/02/retry`]),
		);
	});

	it("offers Move into the library for an album written but not moved, and Move posts it", async () => {
		const { calls } = serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		const row = await shown("llly-2019-web");
		expect(
			within(row).getByRole("button", { name: DISCARD }),
		).toBeInTheDocument();
		expect(within(row).queryByRole("button", { name: /^Retry/ })).toBeNull();

		await userEvent.click(
			within(row).getByRole("button", { name: /^Move into the library/ }),
		);
		await waitFor(() =>
			expect(posted(calls)).toEqual([`/api/drops/${BUSY}/albums/03/move`]),
		);
	});

	it("offers no Discard for an album musiclib is working on, nor for its drop", async () => {
		serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		const busy = await shown("Ecliptica rip");
		expect(within(busy).queryByRole("button", { name: DISCARD })).toBeNull();
		expect(
			within(rowOf("Pariahs Child rip")).getByRole("button", { name: DISCARD }),
		).toBeInTheDocument();
		expect(dropDiscards(BUSY)).toEqual([]);
	});

	it("offers no button for an album already in the library", async () => {
		serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		const row = await shown("Silence rip");
		expect(within(row).queryAllByRole("button")).toEqual([]);
	});

	it("says on each of two albums planning the same folder which the other is", async () => {
		serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		expect(await shown("Por que me mirais asi")).toHaveTextContent(
			"plans the same folder as album 05",
		);
		expect(rowOf("Bonus tracks")).toHaveTextContent(
			"plans the same folder as album 04",
		);
		expect(rowOf("Pariahs Child rip")).not.toHaveTextContent(
			"plans the same folder",
		);
	});

	it("offers a drop that stopped before its last file only Discard", async () => {
		const { calls } = serve(() => [incompleteDrop]);
		renderWithProviders(<Drops />);

		await screen.findByRole("heading", {
			name: new RegExp(literally(INCOMPLETE)),
		});
		expect(screen.getByText("incomplete")).toBeInTheDocument();
		const buttons = screen.getAllByRole("button");
		expect(buttons).toHaveLength(1);
		expect(buttons[0]).toHaveAccessibleName(DISCARD);
		expect(screen.queryAllByRole("link")).toEqual([]);

		await userEvent.click(buttons[0]!);
		await confirmDiscard();
		await waitFor(() =>
			expect(posted(calls)).toEqual([`/api/drops/${INCOMPLETE}/discard`]),
		);
	});

	it("lists an item that holds no audio with no audio files", async () => {
		serve(() => [
			drop(BUSY, {
				albums: [album("01", "Pariahs Child rip")],
				ignored: [{ item: "Scans only", path: "", reason: "no audio files" }],
			}),
		]);
		renderWithProviders(<Drops />);

		expect(await screen.findByText(/Scans only/)).toBeInTheDocument();
		expect(screen.getByText(/no audio files/)).toBeInTheDocument();
	});

	it("discards one album by posting its discard, then shows the list without it", async () => {
		const id = "20260930-080000";
		let discarded = false;
		const { calls } = serve(
			() => [
				drop(id, {
					albums: [
						...(discarded ? [] : [album("01", "Ecliptica rip")]),
						album("02", "Silence rip"),
					],
				}),
			],
			() => {
				discarded = true;
				return ok();
			},
		);
		renderWithProviders(<Drops />);

		const row = await shown("Ecliptica rip");
		const before = gets(calls);
		await userEvent.click(within(row).getByRole("button", { name: DISCARD }));
		expect(posted(calls)).toEqual([]);
		expect(screen.getByRole("alertdialog")).toHaveTextContent(
			"Discard Ecliptica rip?",
		);
		await confirmDiscard();

		// The list only loses the album by asking the server again after the POST.
		await waitFor(() => expect(screen.queryByText(/Ecliptica rip/)).toBeNull());
		expect(posted(calls)).toEqual([`/api/drops/${id}/albums/01/discard`]);
		expect(gets(calls)).toBeGreaterThan(before);
		expect(screen.getByText(/Silence rip/)).toBeInTheDocument();
	});

	it("discards a whole drop from its heading", async () => {
		const other = "20260930-080000";
		const { calls } = serve(() => [
			drop(other, { albums: [album("01", "Ecliptica rip")] }),
			drop(INCOMPLETE, { albums: [album("01", "Silence rip")] }),
		]);
		renderWithProviders(<Drops />);

		await shown("Silence rip");
		const [button, ...more] = dropDiscards(INCOMPLETE);
		expect(more).toEqual([]);
		await userEvent.click(button!);
		expect(posted(calls)).toEqual([]);
		expect(screen.getByRole("alertdialog")).toHaveTextContent(
			`Discard drop ${INCOMPLETE} and its album?`,
		);
		await confirmDiscard();

		await waitFor(() =>
			expect(posted(calls)).toEqual([`/api/drops/${INCOMPLETE}/discard`]),
		);
	});

	it("names how many albums a drop's discard takes with it", async () => {
		serve(() => [
			drop(INCOMPLETE, {
				albums: [album("01", "Silence rip"), album("02", "Ecliptica rip")],
			}),
		]);
		renderWithProviders(<Drops />);

		await shown("Silence rip");
		await userEvent.click(dropDiscards(INCOMPLETE)[0]!);
		expect(screen.getByRole("alertdialog")).toHaveTextContent(
			`Discard drop ${INCOMPLETE} and all 2 of its albums?`,
		);
	});

	it("posts nothing when a discard is cancelled, by its button or by Escape", async () => {
		const { calls } = serve(() => [
			drop(INCOMPLETE, { albums: [album("01", "Silence rip")] }),
		]);
		renderWithProviders(<Drops />);

		const row = await shown("Silence rip");
		const discard = within(row).getByRole("button", { name: DISCARD });

		await userEvent.click(discard);
		expect(
			within(screen.getByRole("alertdialog")).getByRole("button", {
				name: "Cancel",
			}),
		).toHaveFocus();
		await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
		expect(screen.queryByRole("alertdialog")).toBeNull();
		expect(discard).toHaveFocus();

		await userEvent.click(discard);
		await userEvent.keyboard("{Escape}");
		expect(screen.queryByRole("alertdialog")).toBeNull();
		expect(posted(calls)).toEqual([]);
	});

	it("has no Open button: the album's name is the row's link", async () => {
		serve(() => [busyDrop]);
		renderWithProviders(<Drops />);

		const row = await shown("Pariahs Child rip");
		expect(within(row).getByRole("link")).toHaveTextContent(
			"Pariahs Child rip",
		);
		expect(within(row).queryByRole("button", { name: /^Open/ })).toBeNull();
	});

	describe("polling, on fake timers that also run with the clock so findBy still waits", () => {
		const running: [string, Drop][] = [
			[
				"an album is queued",
				drop(BUSY, {
					albums: [
						album("01", "Ecliptica rip", {
							state: "queued",
							busy: true,
							actions: [],
						}),
					],
				}),
			],
			[
				"an album is identifying",
				drop(BUSY, {
					albums: [
						album("01", "Ecliptica rip", {
							state: "identifying",
							busy: true,
							actions: [],
						}),
					],
				}),
			],
			[
				"an album is applying",
				drop(BUSY, {
					albums: [
						album("01", "Ecliptica rip", {
							state: "applying",
							busy: true,
							actions: [],
						}),
					],
				}),
			],
			["the drop is uploading", drop(BUSY, { state: "uploading", albums: [] })],
			[
				"the drop is extracting",
				drop(BUSY, { state: "extracting", albums: [] }),
			],
		];

		it.each(running)(
			"asks again after 2 s while %s, and stops once nothing runs",
			async (_, first) => {
				vi.useFakeTimers({ shouldAdvanceTime: true });
				const settled = drop(BUSY, { albums: [album("01", "Ecliptica rip")] });
				let answered = 0;
				const { calls } = serve(() => (answered++ === 0 ? [first] : [settled]));
				renderWithProviders(<Drops />);

				await screen.findByRole("heading", { name: new RegExp(BUSY) });
				expect(gets(calls)).toBe(1);

				await vi.advanceTimersByTimeAsync(1_800);
				expect(gets(calls)).toBe(1);
				await vi.advanceTimersByTimeAsync(400);
				await waitFor(() => expect(gets(calls)).toBe(2));
				await waitFor(() =>
					expect(
						within(rowOf("Ecliptica rip")).getByText("ready"),
					).toBeInTheDocument(),
				);

				await vi.advanceTimersByTimeAsync(10_000);
				expect(gets(calls)).toBe(2);
			},
		);
	});
});
