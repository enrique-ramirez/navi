import { ImageUp, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { putCover } from "@/shared/api/album";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Parasol } from "@/shared/ui/Parasol";
import styles from "./CoverCard.module.css";
import type { Pending } from "./pending";

// The image types the server reads; it names the file it keeps and answers with its path.
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

interface Chosen {
	url: string;
	width: number;
	height: number;
	problem: string | null;
}

// The cover the album will have, which is also where a new one is dropped, and the one it has now.
export function CoverCard({
	view,
	pending,
	title,
}: {
	view: AlbumView;
	pending: Pending;
	title: string;
}) {
	const { t } = useTranslate();
	const [side, setSide] = useState<"next" | "now">("next");
	const [chosen, setChosen] = useState<Chosen | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [over, setOver] = useState(false);
	const last = useRef<string | null>(null);
	last.current = chosen?.url ?? null;
	useEffect(
		() => () => {
			if (last.current) URL.revokeObjectURL(last.current);
		},
		[],
	);

	// A reset draft drops the owner's unsent cover.
	const sent = pending.draft.cover ?? null;
	const shownChosen = sent ? chosen : null;
	const next = shownChosen ?? view.cover;
	const now = view.cover_now;
	const shown = side === "now" ? now : next;
	const planned = Object.keys(view.preview?.images ?? {}).length > 0;

	async function take(file: File | null | undefined) {
		setError(null);
		if (!file || !IMAGE_TYPES.includes(file.type)) {
			setError(t("cover.notImage"));
			return;
		}
		const answer = await putCover(view, file);
		if (!answer.ok) {
			setError(answer.error ?? t("cover.failed"));
			return;
		}
		// The owner's cover wins whether or not it passes; the test only warns.
		const result = answer.body;
		pending.setCover(result.path);
		if (chosen) URL.revokeObjectURL(chosen.url);
		setChosen({
			url: URL.createObjectURL(file),
			width: result.width,
			height: result.height,
			problem: result.passes ? null : (result.problem ?? ""),
		});
		setSide("next");
	}

	const problem = side === "next" ? next?.problem : null;

	return (
		<figure className={styles.card}>
			<label
				className={styles.drop}
				data-over={over || undefined}
				onDragOver={(event) => {
					event.preventDefault();
					setOver(true);
				}}
				onDragLeave={() => setOver(false)}
				onDrop={(event) => {
					event.preventDefault();
					setOver(false);
					const { files, items } = event.dataTransfer;
					const first =
						files?.[0] ??
						Array.from(items ?? [])
							.find((item) => item.kind === "file")
							?.getAsFile();
					void take(first);
				}}
			>
				{shown ? (
					<img
						src={shown.url}
						alt={t("album.cover", { title })}
						className={styles.image}
					/>
				) : (
					<div className={styles.placeholder}>
						<Parasol size={64} />
						<span>
							{t(
								side === "now"
									? "cover.noneNow"
									: planned
										? "cover.notShown"
										: "cover.noneNext",
							)}
						</span>
					</div>
				)}
				<span className={styles.overlay}>
					<ImageUp size={20} aria-hidden="true" />
					{t("cover.replace")}
				</span>
				<input
					type="file"
					accept="image/*"
					className="visually-hidden"
					aria-label={t("cover.pick")}
					onChange={(event) => {
						void take(event.target.files?.[0]);
						event.target.value = "";
					}}
				/>
			</label>

			<figcaption className={styles.caption}>
				<fieldset className={styles.toggle}>
					<legend className="visually-hidden">{t("cover.title")}</legend>
					<button
						type="button"
						aria-pressed={side === "next"}
						onClick={() => setSide("next")}
					>
						{t("cover.next")}
					</button>
					<button
						type="button"
						aria-pressed={side === "now"}
						onClick={() => setSide("now")}
					>
						{t("cover.now")}
					</button>
				</fieldset>
				<span className={styles.size}>
					{shown
						? t("duplicate.by", { w: shown.width, h: shown.height })
						: null}
					{side === "next" && shownChosen && (
						<>
							{" · "}
							<button
								type="button"
								className={styles.link}
								onClick={() => pending.setCover(null)}
							>
								{t("cover.undo")}
							</button>
						</>
					)}
				</span>
			</figcaption>

			{problem && (
				<p role="status" className={styles.warning}>
					<TriangleAlert size={14} aria-hidden="true" />
					{t("cover.fails", { problem })}
				</p>
			)}
			{error && (
				<p role="alert" className={styles.warning}>
					{error}
				</p>
			)}
		</figure>
	);
}
