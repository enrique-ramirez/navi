import { useEffect, useRef, useState } from "react";

import { albumTags } from "@/domain/album/albumTags";
import { putCover } from "@/shared/api/album";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Parasol } from "@/shared/ui/Parasol";
import styles from "./CoverDrop.module.css";
import type { Pending } from "./pending";

// The image types the server reads; it names the file it keeps and answers with its path.
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

export function CoverDrop({
	view,
	pending,
}: {
	view: AlbumView;
	pending: Pending;
}) {
	const { t } = useTranslate();
	const [chosen, setChosen] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const last = useRef<string | null>(null);
	last.current = chosen;
	useEffect(
		() => () => {
			if (last.current) URL.revokeObjectURL(last.current);
		},
		[],
	);
	const shown = chosen ?? view.cover?.url ?? null;
	const title = albumTags(view).title || view.name;

	async function take(file: File | null | undefined) {
		setError(null);
		setProblem(null);
		if (!file || !IMAGE_TYPES.includes(file.type)) {
			setError(t("cover.notImage"));
			return;
		}
		const answer = await putCover(view, file);
		if (!answer.ok) {
			setError(answer.error ?? t("cover.failed"));
			return;
		}
		const result = answer.body;
		// The owner's cover wins whether or not it passes; the test only warns.
		if (!result.passes) setProblem(result.problem ?? "");
		pending.setCover(result.path);
		if (chosen) URL.revokeObjectURL(chosen);
		setChosen(URL.createObjectURL(file));
	}

	return (
		<section
			className={styles.cover}
			aria-labelledby="cover-title"
			onDragOver={(event) => event.preventDefault()}
			onDrop={(event) => {
				event.preventDefault();
				const { files, items } = event.dataTransfer;
				const first =
					files?.[0] ??
					Array.from(items ?? [])
						.find((item) => item.kind === "file")
						?.getAsFile();
				void take(first);
			}}
		>
			<h2 id="cover-title">{t("cover.title")}</h2>
			<div className={styles.picture}>
				{shown ? (
					<img src={shown} alt={t("album.cover", { title })} />
				) : (
					<div className={styles.placeholder}>
						<Parasol size={72} />
					</div>
				)}
			</div>
			<p className={styles.hint}>{t("cover.drop")}</p>
			<label className={styles.pick}>
				{t("cover.pick")}
				<input
					type="file"
					accept="image/*"
					className="visually-hidden"
					onChange={(event) => {
						void take(event.target.files?.[0]);
						event.target.value = "";
					}}
				/>
			</label>
			{problem !== null && (
				<div role="status" className={styles.warning}>
					<p>{t("cover.fails", { problem })}</p>
					<p>{t("cover.wins")}</p>
				</div>
			)}
			{error && <p role="alert">{error}</p>}
		</section>
	);
}
