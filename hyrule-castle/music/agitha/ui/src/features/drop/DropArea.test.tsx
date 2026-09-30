import { File as NodeFile } from "node:buffer";

// user-event cannot build a DataTransfer whose items hand out folder entries,
// so the drop itself is the one event dispatched with fireEvent.
import { fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { CreateDropRequest, Drop, DropItem } from "@/shared/api/types";
import { type Call, fakeFetch } from "@/test/fakeFetch";
import { renderWithProviders, screen, waitFor } from "@/test/render";

import { DropArea } from "./DropArea";
import { Drops } from "./Drops";

const DROP = "20260929-210000";
const AUDIO = [
	"mp3",
	"flac",
	"m4a",
	"ogg",
	"opus",
	"wma",
	"wav",
	"aiff",
	"ape",
	"wv",
	"mpc",
];

type Spec =
	| { name: string; content: string | Uint8Array }
	| { name: string; children: Spec[]; batch?: number };

const file = (
	name: string,
	content: string | Uint8Array = `bytes of ${name}`,
) => ({ name, content }) satisfies Spec;

// `batch` is how many entries one readEntries call gives; Chromium gives at most 100.
const folder = (name: string, children: Spec[], batch = 100) =>
	({ name, children, batch }) satisfies Spec;

// The page reads a File's bytes into the request body. jsdom's File cannot be a
// fetch body under Node, so the entries hand out Node's, as a browser hands out its own.
function blobOf(spec: { name: string; content: string | Uint8Array }): File {
	return new NodeFile(
		[spec.content] as ConstructorParameters<typeof NodeFile>[0],
		spec.name,
	) as unknown as File;
}

function entryOf(spec: Spec, parent = ""): FileSystemEntry {
	const fullPath = `${parent}/${spec.name}`;
	if ("content" in spec) {
		return {
			isFile: true,
			isDirectory: false,
			name: spec.name,
			fullPath,
			file(success: (file: File) => void) {
				setTimeout(() => success(blobOf(spec)), 0);
			},
		} as unknown as FileSystemFileEntry;
	}
	const children = spec.children.map((child) => entryOf(child, fullPath));
	return {
		isFile: false,
		isDirectory: true,
		name: spec.name,
		fullPath,
		createReader() {
			let read = 0;
			return {
				// Batches of at most `batch`, then an empty one, answered later as a browser does.
				readEntries(success: (entries: FileSystemEntry[]) => void) {
					const next = children.slice(read, read + (spec.batch ?? 100));
					read += next.length;
					setTimeout(() => success(next), 0);
				},
			};
		},
	} as unknown as FileSystemDirectoryEntry;
}

// A browser empties the DataTransfer once the drop handler returns, so an entry
// asked for after an `await` is gone. The fake does the same.
function dropOnto(region: HTMLElement, specs: Spec[]) {
	let live = true;
	const items = specs.map((spec) => {
		const entry = entryOf(spec);
		return {
			kind: "file",
			type: "",
			webkitGetAsEntry: () => (live ? entry : null),
			getAsFile: () => (live && "content" in spec ? blobOf(spec) : null),
		};
	});
	const dataTransfer = {
		items: [...items],
		files: [],
		types: ["Files"],
		dropEffect: "copy",
		effectAllowed: "all",
	};
	fireEvent.drop(region, { dataTransfer });
	live = false;
	dataTransfer.items.length = 0;
}

type Handler = (req: Request) => Response | Promise<Response>;

const noContent = () => new Response(null, { status: 204 });

function serve({
	create = () => Response.json({ drop: DROP }, { status: 201 }),
	put = noContent,
	done = noContent,
	drops = () => Response.json([]),
}: {
	create?: Handler;
	put?: Handler;
	done?: Handler;
	drops?: Handler;
} = {}) {
	const handlers: Record<string, Handler> = {
		"GET /api/drops": drops,
		"POST /api/drops": create,
		"POST /api/drops/:drop/done": done,
	};
	// fakeFetch's `:param` is one segment, and a file's path has several.
	for (let depth = 1; depth <= 6; depth++) {
		handlers[`PUT /api/drops/:drop/files/:item${"/:path".repeat(depth)}`] = put;
	}
	server = fakeFetch(handlers);
	return server;
}

let server: ReturnType<typeof fakeFetch> | undefined;

afterEach(() => {
	server?.restore();
	server = undefined;
});

// Each segment decoded on its own, so a `#`, `?` or `%` left unencoded shows.
function uploadOf(url: string) {
	const [, rest = ""] = new URL(url).pathname.split(
		`/api/drops/${DROP}/files/`,
	);
	const [item = "", ...path] = rest.split("/").map(decodeURIComponent);
	return { item, path: path.join("/") };
}

const puts = (calls: Call[]) => calls.filter((call) => call.method === "PUT");
const posts = (calls: Call[]) =>
	calls.filter(
		(call) => call.method === "POST" && pathOf(call) === "/api/drops",
	);
const dones = (calls: Call[]) =>
	calls.filter((call) => pathOf(call) === `/api/drops/${DROP}/done`);
const pathOf = (call: Call) => new URL(call.url).pathname;

function created(calls: Call[]): DropItem[] {
	const [first] = posts(calls);
	if (!first) throw new Error("no POST /api/drops was sent");
	const body = JSON.parse(first.body) as CreateDropRequest;
	return body.items
		.map((item) => ({
			...item,
			files: [...item.files].sort((a, b) => a.path.localeCompare(b.path)),
		}))
		.sort((a, b) => a.name.localeCompare(b.name));
}

const size = (content: string) => new TextEncoder().encode(content).length;

// The helper's router mounts the component after a tick.
function region() {
	return screen.findByRole("region", { name: "Drop music here" });
}

const UNITS: Record<string, number[]> = {
	b: [1],
	bytes: [1],
	kb: [1e3, 2 ** 10],
	kib: [2 ** 10],
	mb: [1e6, 2 ** 20],
	mib: [2 ** 20],
	gb: [1e9, 2 ** 30],
	gib: [2 ** 30],
	tb: [1e12, 2 ** 40],
};

// True when `shown` in `unit` is `bytes`, read as decimal or binary units, to 6%.
function means(shown: string, unit: string, bytes: number) {
	const value = Number(shown.replace(/,/g, ""));
	if (bytes === 0) return value === 0;
	return (UNITS[unit.toLowerCase()] ?? []).some(
		(factor) => Math.abs(value * factor - bytes) / bytes <= 0.06,
	);
}

function sizesIn(text: string) {
	return [
		...text.matchAll(/(\d[\d,]*(?:\.\d+)?)\s*(bytes|[KMGT]i?B|B)\b/gi),
	].map(([, shown = "", unit = ""]) => ({ shown, unit }));
}

function names(text: string, bytes: number) {
	return sizesIn(text).some(({ shown, unit }) => means(shown, unit, bytes));
}

const PROGRESS =
	/(\d+) of (\d+) files, (\d[\d,]*(?:\.\d+)?)\s*([KMGT]i?B|B)? of (\d[\d,]*(?:\.\d+)?)\s*([KMGT]i?B|B)/;

function progress() {
	const text = screen.getByText(/\d+ of \d+ files/).textContent ?? "";
	const found = PROGRESS.exec(text);
	if (!found) throw new Error(`progress reads "${text}"`);
	const [, sent, files, bytes, unit, total, totalUnit = ""] = found;
	return {
		text,
		files: `${sent} of ${files} files`,
		bytesMean: (expected: number) =>
			means(bytes ?? "", unit ?? totalUnit, expected),
		totalMeans: (expected: number) => means(total ?? "", totalUnit, expected),
	};
}

// The bar's fill as a fraction, from ARIA or from a native <progress>.
function fill(bar: HTMLElement) {
	if (bar instanceof HTMLProgressElement) return bar.value / bar.max;
	return (
		Number(bar.getAttribute("aria-valuenow")) /
		Number(bar.getAttribute("aria-valuemax") ?? 100)
	);
}

function deferred() {
	let release = () => {};
	const promise = new Promise<Response>((resolve) => {
		release = () => resolve(noContent());
	});
	return { promise, release };
}

describe("DropArea", () => {
	const sonata = folder("Sonata Arctica", [
		folder("2014 - Pariah's Child", [
			file("01 - The Wolves Die Young.mp3"),
			file("folder.jpg"),
			folder("CD2", [file("01 - Love.mp3")]),
		]),
	]);
	// A `#`, a `?`, a `%` and an accent in the item and its paths, each of which breaks an unencoded URL.
	const himno = folder("La La Love You? #1", [
		file("03 - Himno (para los que están jodidos).mp3"),
		file("04 - What? #2.mp3"),
		file("05 - 100% Pure.mp3"),
	]);
	const zip = file(
		"La La Love You - Blockbuster.zip",
		"PK\u0003\u0004 zip bytes",
	);

	it("sends two folders and a zip as one drop listing every file's path inside its item and its size", async () => {
		const { calls } = serve();
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [sonata, himno, zip]);

		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		expect(posts(calls)).toHaveLength(1);
		const bytes = (name: string) => size(`bytes of ${name}`);
		expect(created(calls)).toEqual(
			[
				{
					name: "La La Love You? #1",
					kind: "folder",
					files: [
						{
							path: "03 - Himno (para los que están jodidos).mp3",
							size: bytes("03 - Himno (para los que están jodidos).mp3"),
						},
						{ path: "04 - What? #2.mp3", size: bytes("04 - What? #2.mp3") },
						{ path: "05 - 100% Pure.mp3", size: bytes("05 - 100% Pure.mp3") },
					],
				},
				{
					name: "La La Love You - Blockbuster.zip",
					kind: "archive",
					files: [
						{
							path: "La La Love You - Blockbuster.zip",
							size: size("PK\u0003\u0004 zip bytes"),
						},
					],
				},
				{
					name: "Sonata Arctica",
					kind: "folder",
					files: [
						{
							path: "2014 - Pariah's Child/01 - The Wolves Die Young.mp3",
							size: bytes("01 - The Wolves Die Young.mp3"),
						},
						{
							path: "2014 - Pariah's Child/CD2/01 - Love.mp3",
							size: bytes("01 - Love.mp3"),
						},
						{
							path: "2014 - Pariah's Child/folder.jpg",
							size: bytes("folder.jpg"),
						},
					],
				},
			].sort((a, b) => a.name.localeCompare(b.name)),
		);
	});

	it("puts each file's bytes at its item and path, then posts done after the last one", async () => {
		const { calls } = serve();
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [sonata, himno, zip]);

		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		const byPlace = (
			a: { item: string; path: string },
			b: { item: string; path: string },
		) => `${a.item}/${a.path}`.localeCompare(`${b.item}/${b.path}`);
		const uploaded = puts(calls)
			.map((call) => ({ ...uploadOf(call.url), body: call.body }))
			.sort(byPlace);
		expect(uploaded).toEqual(
			[
				{
					item: "La La Love You? #1",
					path: "03 - Himno (para los que están jodidos).mp3",
					body: "bytes of 03 - Himno (para los que están jodidos).mp3",
				},
				{
					item: "La La Love You? #1",
					path: "04 - What? #2.mp3",
					body: "bytes of 04 - What? #2.mp3",
				},
				{
					item: "La La Love You? #1",
					path: "05 - 100% Pure.mp3",
					body: "bytes of 05 - 100% Pure.mp3",
				},
				{
					item: "La La Love You - Blockbuster.zip",
					path: "La La Love You - Blockbuster.zip",
					body: "PK\u0003\u0004 zip bytes",
				},
				{
					item: "Sonata Arctica",
					path: "2014 - Pariah's Child/01 - The Wolves Die Young.mp3",
					body: "bytes of 01 - The Wolves Die Young.mp3",
				},
				{
					item: "Sonata Arctica",
					path: "2014 - Pariah's Child/CD2/01 - Love.mp3",
					body: "bytes of 01 - Love.mp3",
				},
				{
					item: "Sonata Arctica",
					path: "2014 - Pariah's Child/folder.jpg",
					body: "bytes of folder.jpg",
				},
			].sort(byPlace),
		);
		expect(calls.indexOf(dones(calls)[0]!)).toBeGreaterThan(
			calls.indexOf(puts(calls).at(-1)!),
		);
	});

	it("sends a .rar and a .7z whole, as archives", async () => {
		const { calls } = serve();
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [file("Mp3.rar", "Rar!"), file("Scans.7z", "7z")]);

		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		expect(created(calls)).toEqual([
			{
				name: "Mp3.rar",
				kind: "archive",
				files: [{ path: "Mp3.rar", size: 4 }],
			},
			{
				name: "Scans.7z",
				kind: "archive",
				files: [{ path: "Scans.7z", size: 2 }],
			},
		]);
		expect(
			puts(calls)
				.map((call) => call.body)
				.sort(),
		).toEqual(["7z", "Rar!"]);
	});

	it("reads a folder of 150 entries through every batch the browser gives", async () => {
		const tracks = Array.from({ length: 150 }, (_, i) =>
			file(`${String(i + 1).padStart(3, "0")}.flac`),
		);
		// A reader giving fewer than 100 before its end, so stopping on a short batch shows.
		const scans = folder(
			"Scans",
			Array.from({ length: 5 }, (_, i) => file(`${i}.jpg`)),
			2,
		);
		const { calls } = serve();
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [
			folder("chrono_cross-original_soundtrack-1999", [...tracks, scans]),
		]);

		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		const [item] = created(calls);
		expect(item?.files.map((f) => f.path)).toEqual(
			[
				...tracks.map((t) => t.name),
				...[0, 1, 2, 3, 4].map((i) => `Scans/${i}.jpg`),
			].sort((a, b) => a.localeCompare(b)),
		);
		expect(puts(calls)).toHaveLength(155);
	});

	it.each(AUDIO)(
		"refuses a loose .%s before sending anything, naming the file",
		async (extension) => {
			const { calls } = serve();
			renderWithProviders(<DropArea />);

			dropOnto(await region(), [sonata, file(`x.${extension}`)]);

			const alert = await screen.findByRole("alert");
			expect(alert).toHaveTextContent("drop the folder that holds it");
			expect(alert).toHaveTextContent(`x.${extension}`);

			// A second, good drop bounds the wait: had the first sent anything, it
			// would sit in the log ahead of this one.
			dropOnto(await region(), [himno]);
			await waitFor(() => expect(dones(calls)).toHaveLength(1));
			expect(posts(calls)).toHaveLength(1);
			expect(created(calls).map((item) => item.name)).toEqual([
				"La La Love You? #1",
			]);
		},
	);

	it("lists a loose text file and image under Ignored and sends only the folder beside them", async () => {
		const { calls } = serve();
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [file("readme.txt"), sonata, file("cover.jpg")]);

		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		expect(await screen.findByText(/Ignored/)).toBeInTheDocument();
		expect(screen.getByText(/readme\.txt/)).toBeInTheDocument();
		expect(screen.getByText(/cover\.jpg/)).toBeInTheDocument();
		expect(created(calls).map((item) => item.name)).toEqual(["Sonata Arctica"]);
		expect(puts(calls).map((call) => uploadOf(call.url).item)).not.toContain(
			"readme.txt",
		);
		expect(puts(calls).map((call) => uploadOf(call.url).item)).not.toContain(
			"cover.jpg",
		);
	});

	it("shows a refusal for space with its reason and both numbers, and uploads nothing", async () => {
		const { calls } = serve({
			// The sentence carries no numbers, so the ones on screen are the page's.
			create: () =>
				Response.json(
					{
						error: "Not enough free space on /srv/music.",
						free: 1_500_000_000,
						needed: 4_000_000_000,
					},
					{ status: 400 },
				),
		});
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [sonata]);

		const alert = await screen.findByRole("alert");
		expect(alert).toHaveTextContent("Not enough free space on /srv/music.");
		const text = alert.textContent ?? "";
		expect(names(text, 1_500_000_000), `free in "${text}"`).toBe(true);
		expect(names(text, 4_000_000_000), `needed in "${text}"`).toBe(true);
		expect(puts(calls)).toHaveLength(0);
		expect(dones(calls)).toHaveLength(0);
	});

	it("says the upload stopped when the network fails mid-drop, in the page's words, and does not call the drop done", async () => {
		const browserSays = "NetworkError when attempting to fetch resource.";
		let sent = 0;
		const { calls } = serve({
			// The second file never arrives, as when the connection drops.
			put: () => {
				sent++;
				if (sent === 2) throw new TypeError(browserSays);
				return noContent();
			},
		});
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [sonata]);

		expect(
			await screen.findByText(/the upload stopped before its last file/),
		).toBeInTheDocument();
		expect(screen.queryByText(new RegExp(browserSays))).toBeNull();
		// Criterion 15: a drop missing a file stays incomplete, so the server is never told it is done.
		expect(dones(calls)).toHaveLength(0);
	});

	it("shows files and bytes sent against the drop's totals as each upload finishes", async () => {
		const sizes: Record<string, number> = {
			"01.flac": 2_000_000,
			"02.flac": 3_000_000,
			"03.flac": 5_000_000,
		};
		const waiting = new Map<string, () => void>();
		const doneCall = deferred();
		const { calls } = serve({
			put: (req) => {
				const upload = deferred();
				waiting.set(uploadOf(req.url).path, upload.release);
				return upload.promise;
			},
			done: () => doneCall.promise,
		});
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [
			folder(
				"Album",
				Object.entries(sizes).map(([name, bytes]) =>
					file(name, new Uint8Array(bytes)),
				),
			),
		]);

		const bar = await screen.findByRole("progressbar");
		expect(bar).toHaveAccessibleName();
		await waitFor(() => expect(waiting.size).toBe(3));
		const fills = [fill(bar)];
		expect(progress().files).toBe("0 of 3 files");
		expect(progress().totalMeans(10_000_000), progress().text).toBe(true);

		// Out of order, so bytes counted by position instead of by file show.
		const steps: [string, string, number][] = [
			["02.flac", "1 of 3 files", 3_000_000],
			["01.flac", "2 of 3 files", 5_000_000],
			["03.flac", "3 of 3 files", 10_000_000],
		];
		for (const [name, files, bytes] of steps) {
			waiting.get(name)?.();
			await waitFor(() => expect(progress().files).toBe(files));
			expect(progress().bytesMean(bytes), progress().text).toBe(true);
			expect(progress().totalMeans(10_000_000), progress().text).toBe(true);
			fills.push(fill(screen.getByRole("progressbar")));
		}

		expect(fills[0]).toBe(0);
		expect(fills[1]).toBeGreaterThan(fills[0]!);
		expect(fills[2]).toBeGreaterThan(fills[1]!);
		expect(fills[3]).toBe(1);
		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		doneCall.release();
	});

	it("keeps four uploads in flight at a time, never more", async () => {
		const waiting: (() => void)[] = [];
		let inFlight = 0;
		let most = 0;
		const { calls } = serve({
			put: () => {
				inFlight++;
				most = Math.max(most, inFlight);
				const upload = deferred();
				waiting.push(() => {
					inFlight--;
					upload.release();
				});
				return upload.promise;
			},
		});
		renderWithProviders(<DropArea />);

		dropOnto(await region(), [
			folder(
				"Album",
				Array.from({ length: 10 }, (_, i) => file(`${i}.mp3`)),
			),
		]);

		for (let finished = 0; finished < 10; finished++) {
			await waitFor(() =>
				expect(waiting).toHaveLength(Math.min(4, 10 - finished)),
			);
			if (finished === 9) expect(dones(calls)).toHaveLength(0);
			waiting.shift()?.();
		}

		await waitFor(() => expect(dones(calls)).toHaveLength(1));
		expect(puts(calls)).toHaveLength(10);
		expect(most).toBe(4);
	});

	it("refreshes the list of drops once the drop is done", async () => {
		const arrived: Drop = {
			id: DROP,
			state: "extracting",
			started: "2026-09-29T21:00:00",
			items: [],
			ignored: [],
			refused: [],
			albums: [],
			actions: ["discard"],
			received: { files: 1, bytes: 10 },
			error: null,
		};
		let isDone = false;
		serve({
			done: () => {
				isDone = true;
				return noContent();
			},
			drops: () => Response.json(isDone ? [arrived] : []),
		});
		renderWithProviders(
			<>
				<DropArea />
				<Drops />
			</>,
		);

		dropOnto(await region(), [himno]);

		expect(
			await screen.findByRole("heading", { name: new RegExp(DROP) }),
		).toBeInTheDocument();
	});

	it("labels both file pickers, one of which takes folders", async () => {
		serve();
		const { container } = renderWithProviders(<DropArea />);
		await region();

		// A file input has no role to query it by.
		const pickers = [
			...container.querySelectorAll<HTMLInputElement>('input[type="file"]'),
		];
		expect(pickers).toHaveLength(2);
		for (const picker of pickers) expect(picker).toHaveAccessibleName();
		expect(
			pickers.filter((picker) => picker.hasAttribute("webkitdirectory")),
		).toHaveLength(1);
	});
});
