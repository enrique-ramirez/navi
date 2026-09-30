import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Upload } from "lucide-react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";

import {
	type Gathered,
	gatherEntries,
	gatherFiles,
	inPool,
	takeEntries,
} from "@/domain/drop/entries";
import type { CreateDropResponse, ErrorBody } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./DropArea.module.css";

const AT_ONCE = 4;

interface Progress {
	files: number;
	sent: number;
	bytes: number;
	sentBytes: number;
}

class Refusal extends Error {}

// Megabytes of 10^6 bytes, as the free-space check counts them.
const megabytes = (bytes: number) => `${(bytes / 1e6).toFixed(1)} MB`;

const encoded = (path: string) =>
	path.split("/").map(encodeURIComponent).join("/");

// One button for both pickers: a browser opens its file dialog for files or
// for folders, never both, so the button asks which.
function Picker({
	onPick,
}: {
	onPick: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
	const { t } = useTranslate();
	const [open, setOpen] = useState(false);
	const root = useRef<HTMLDivElement>(null);
	const folder = useRef<HTMLInputElement>(null);
	const files = useRef<HTMLInputElement>(null);

	useEffect(() => {
		if (!open) return;
		const onPointer = (event: PointerEvent) => {
			if (!root.current?.contains(event.target as Node)) setOpen(false);
		};
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") setOpen(false);
		};
		document.addEventListener("pointerdown", onPointer);
		document.addEventListener("keydown", onKey);
		return () => {
			document.removeEventListener("pointerdown", onPointer);
			document.removeEventListener("keydown", onKey);
		};
	}, [open]);

	function choose(input: HTMLInputElement | null) {
		setOpen(false);
		input?.click();
	}

	return (
		<div ref={root} className={styles.picker}>
			<button
				type="button"
				className={styles.pick}
				aria-haspopup="menu"
				aria-expanded={open}
				onClick={() => setOpen((was) => !was)}
			>
				{t("drop.pick")}
				<ChevronDown className={styles.chevron} aria-hidden="true" />
			</button>
			{open && (
				<div role="menu" className={styles.menu}>
					<button
						type="button"
						role="menuitem"
						className={styles.item}
						onClick={() => choose(folder.current)}
					>
						{t("drop.pickFolder")}
					</button>
					<button
						type="button"
						role="menuitem"
						className={styles.item}
						onClick={() => choose(files.current)}
					>
						{t("drop.pickFiles")}
					</button>
				</div>
			)}
			<input
				ref={folder}
				type="file"
				className="visually-hidden"
				tabIndex={-1}
				aria-label={t("drop.pickFolder")}
				{...{ webkitdirectory: "" }}
				onChange={onPick}
			/>
			<input
				ref={files}
				type="file"
				multiple
				className="visually-hidden"
				tabIndex={-1}
				aria-label={t("drop.pickFiles")}
				onChange={onPick}
			/>
		</div>
	);
}

export function DropArea() {
	const { t } = useTranslate();
	const client = useQueryClient();
	const [error, setError] = useState<string | null>(null);
	const [ignored, setIgnored] = useState<string[]>([]);
	const [progress, setProgress] = useState<Progress | null>(null);
	const [over, setOver] = useState(false);
	const busy = useRef(false);

	async function refusal(response: Response) {
		const body = (await response.json().catch(() => null)) as ErrorBody | null;
		const reason = body?.error ?? String(response.status);
		return new Refusal(
			body?.free !== undefined && body.needed !== undefined
				? `${reason} ${t("drop.space", { free: megabytes(body.free), needed: megabytes(body.needed) })}`
				: reason,
		);
	}

	async function send(gathered: Gathered) {
		setError(null);
		setIgnored(gathered.ignored);
		// A loose audio file refuses the whole drop, before any request (criterion 7).
		if (gathered.looseAudio.length > 0) {
			setError(`${gathered.looseAudio.join(", ")}: ${t("drop.looseAudio")}`);
			return;
		}
		if (gathered.items.length === 0) return;

		busy.current = true;
		const total: Progress = {
			files: gathered.uploads.length,
			sent: 0,
			bytes: gathered.uploads.reduce((sum, up) => sum + up.file.size, 0),
			sentBytes: 0,
		};
		setProgress(total);
		try {
			const created = await fetch("/api/drops", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({ items: gathered.items }),
			});
			if (!created.ok) throw await refusal(created);
			const { drop } = (await created.json()) as CreateDropResponse;
			void client.invalidateQueries({ queryKey: ["drops"] });

			let sent = 0;
			let sentBytes = 0;
			await inPool(gathered.uploads, AT_ONCE, async (upload) => {
				const response = await fetch(
					`/api/drops/${encodeURIComponent(drop)}/files/${encodeURIComponent(upload.item)}/${encoded(upload.path)}`,
					{ method: "PUT", body: upload.file },
				);
				if (!response.ok) throw await refusal(response);
				sent += 1;
				sentBytes += upload.file.size;
				setProgress({ ...total, sent, sentBytes });
			});
			const done = await fetch(`/api/drops/${encodeURIComponent(drop)}/done`, {
				method: "POST",
			});
			if (!done.ok) throw await refusal(done);
		} catch (failure) {
			// A drop that stops before its last file stays in the list as incomplete (criterion 15).
			// The browser's own message is English and about the transport, so only the server's sentence is shown.
			setError(failure instanceof Refusal ? failure.message : t("drop.failed"));
		} finally {
			busy.current = false;
			setProgress(null);
			void client.invalidateQueries({ queryKey: ["drops"] });
		}
	}

	function pick(event: ChangeEvent<HTMLInputElement>) {
		const files = Array.from(event.target.files ?? []);
		event.target.value = "";
		if (!busy.current) void send(gatherFiles(files));
	}

	return (
		<section
			className={over ? styles.over : styles.area}
			aria-label={t("drop.region")}
			onDragOver={(event) => {
				event.preventDefault();
				setOver(true);
			}}
			onDragLeave={() => setOver(false)}
			onDrop={(event) => {
				event.preventDefault();
				setOver(false);
				if (busy.current) return;
				const { entries, files } = takeEntries(event.dataTransfer.items);
				void gatherEntries(entries, files).then(send);
			}}
		>
			<Upload className={styles.icon} aria-hidden="true" />
			<p className={styles.hint}>{t("drop.here")}</p>
			<Picker onPick={pick} />
			{progress && (
				<div className={styles.progress}>
					<div
						role="progressbar"
						aria-label={t("drop.uploading")}
						aria-valuemin={0}
						aria-valuemax={progress.bytes}
						aria-valuenow={progress.sentBytes}
						className={styles.bar}
					>
						<div
							className={styles.fill}
							style={{
								width: `${progress.bytes ? (100 * progress.sentBytes) / progress.bytes : 0}%`,
							}}
						/>
					</div>
					<p>
						{t("drop.progress", {
							sent: progress.sent,
							files: progress.files,
							bytes: megabytes(progress.sentBytes),
							total: megabytes(progress.bytes),
						})}
					</p>
				</div>
			)}
			{error && <p role="alert">{error}</p>}
			{ignored.length > 0 && (
				<div>
					<p>{t("drop.ignoredTitle")}</p>
					<ul>
						{ignored.map((name) => (
							<li key={name}>{name}</li>
						))}
					</ul>
				</div>
			)}
		</section>
	);
}
