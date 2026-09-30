import type { DropItem } from "@/shared/api/types";

const ARCHIVES = [".zip", ".rar", ".7z"];
const AUDIO = [
	".mp3",
	".flac",
	".m4a",
	".ogg",
	".opus",
	".wma",
	".wav",
	".aiff",
	".ape",
	".wv",
	".mpc",
];

function hasExtension(name: string, extensions: string[]) {
	const lower = name.toLowerCase();
	return extensions.some((extension) => lower.endsWith(extension));
}

/** One file to send: `item` and `path` name where the server keeps it. */
export interface Upload {
	item: string;
	path: string;
	file: File;
}

export interface Gathered {
	/** What the server is told: folders and archives, each file with its size. */
	items: DropItem[];
	uploads: Upload[];
	/** Loose files at the top level that the drop does not send. */
	ignored: string[];
	/** Loose audio files at the top level; a drop holding one is refused whole. */
	looseAudio: string[];
}

function empty(): Gathered {
	return { items: [], uploads: [], ignored: [], looseAudio: [] };
}

// A loose top-level file is an archive to send, audio to refuse, or something to leave out.
function addLoose(into: Gathered, file: File) {
	if (hasExtension(file.name, ARCHIVES)) {
		into.items.push({
			name: file.name,
			kind: "archive",
			files: [{ path: file.name, size: file.size }],
		});
		into.uploads.push({ item: file.name, path: file.name, file });
	} else if (hasExtension(file.name, AUDIO)) {
		into.looseAudio.push(file.name);
	} else {
		into.ignored.push(file.name);
	}
}

/**
 * The entries of a drop, taken while the drop handler still runs: a browser
 * empties the DataTransfer when the handler returns, so nothing may wait first.
 */
export function takeEntries(items: DataTransferItemList | DataTransferItem[]) {
	const entries: FileSystemEntry[] = [];
	const files: File[] = [];
	for (const item of Array.from(items)) {
		if (item.kind !== "file") continue;
		const entry = item.webkitGetAsEntry();
		if (entry) entries.push(entry);
		else {
			const file = item.getAsFile();
			if (file) files.push(file);
		}
	}
	return { entries, files };
}

// readEntries answers in batches (Chromium gives at most 100), so it is asked until it answers none.
async function readAll(directory: FileSystemDirectoryEntry) {
	const reader = directory.createReader();
	const all: FileSystemEntry[] = [];
	for (;;) {
		const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
			reader.readEntries(resolve, reject),
		);
		if (batch.length === 0) return all;
		all.push(...batch);
	}
}

const fileOf = (entry: FileSystemFileEntry) =>
	new Promise<File>((resolve, reject) => entry.file(resolve, reject));

async function walk(
	entry: FileSystemEntry,
	prefix: string,
	item: string,
	into: Gathered,
	files: DropItem["files"],
) {
	if (entry.isFile) {
		const file = await fileOf(entry as FileSystemFileEntry);
		files.push({ path: `${prefix}${entry.name}`, size: file.size });
		into.uploads.push({ item, path: `${prefix}${entry.name}`, file });
		return;
	}
	for (const child of await readAll(entry as FileSystemDirectoryEntry))
		await walk(child, `${prefix}${entry.name}/`, item, into, files);
}

// The folder's own name is the item, so the paths under it start below it.
async function walkFolder(entry: FileSystemDirectoryEntry, into: Gathered) {
	const files: DropItem["files"] = [];
	for (const child of await readAll(entry))
		await walk(child, "", entry.name, into, files);
	into.items.push({ name: entry.name, kind: "folder", files });
}

export async function gatherEntries(
	entries: FileSystemEntry[],
	looseFiles: File[] = [],
): Promise<Gathered> {
	const gathered = empty();
	for (const entry of entries) {
		if (entry.isDirectory)
			await walkFolder(entry as FileSystemDirectoryEntry, gathered);
		else addLoose(gathered, await fileOf(entry as FileSystemFileEntry));
	}
	for (const file of looseFiles) addLoose(gathered, file);
	return gathered;
}

/** Files from a picker: a folder picker's carry their path from the folder down. */
export function gatherFiles(files: File[]): Gathered {
	const gathered = empty();
	const folders = new Map<string, DropItem>();
	for (const file of files) {
		const relative = file.webkitRelativePath;
		const [folder, ...rest] = relative.split("/");
		if (!relative || rest.length === 0 || !folder) {
			addLoose(gathered, file);
			continue;
		}
		let item = folders.get(folder);
		if (!item) {
			item = { name: folder, kind: "folder", files: [] };
			folders.set(folder, item);
			gathered.items.push(item);
		}
		const path = rest.join("/");
		item.files.push({ path, size: file.size });
		gathered.uploads.push({ item: folder, path, file });
	}
	return gathered;
}

/** Runs `task` over `queue` with at most `limit` at once, stopping at the first failure. */
export async function inPool<T>(
	queue: T[],
	limit: number,
	task: (each: T) => Promise<void>,
) {
	const waiting = [...queue];
	let failure: unknown;
	let failed = false;
	async function worker() {
		for (
			let next = waiting.shift();
			next !== undefined;
			next = waiting.shift()
		) {
			if (failed) return;
			try {
				await task(next);
			} catch (error) {
				failed = true;
				failure = error;
				return;
			}
		}
	}
	await Promise.all(Array.from({ length: limit }, worker));
	if (failed) throw failure;
}
