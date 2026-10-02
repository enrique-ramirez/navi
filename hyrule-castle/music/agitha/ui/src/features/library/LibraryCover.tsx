import { useEffect, useRef, useState } from "react";

import { putLibraryCover, Refused } from "@/shared/api/library";
import type {
	CoverCheck,
	CoverUpload,
	LibraryCover as ServedCover,
} from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { droppedFile } from "@/shared/ui/droppedFile";
import styles from "./LibraryCover.module.css";

interface Picked {
	token: string;
	url: string;
}

/**
 * The album's cover and the image that would replace it. The new image is
 * `cover`, the page's draft; the card keeps only its own preview address.
 */
export function LibraryCover({
	current,
	cover,
	version,
	title,
	readOnly,
	onCover,
}: {
	current: ServedCover | null;
	cover: CoverUpload | null;
	/** Counts the saves that wrote a cover, so the browser fetches the one now served. */
	version: number;
	title: string;
	readOnly: boolean;
	onCover: (cover: CoverUpload) => void;
}) {
	const { t } = useTranslate();
	const [picked, setPicked] = useState<Picked | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [uploading, setUploading] = useState(false);
	const [over, setOver] = useState(false);
	const last = useRef<string | null>(null);
	last.current = picked?.url ?? null;
	useEffect(
		() => () => {
			if (last.current) URL.revokeObjectURL(last.current);
		},
		[],
	);
	useEffect(() => {
		if (cover !== null || !last.current) return;
		URL.revokeObjectURL(last.current);
		setPicked(null);
	}, [cover]);

	const busy = readOnly || uploading;
	const added =
		cover !== null && picked?.token === cover.cover
			? { check: cover, url: picked.url }
			: null;

	async function take(file: File | null | undefined) {
		if (busy || !file) return;
		setError(null);
		setUploading(true);
		try {
			const answer = await putLibraryCover(file);
			if (picked) URL.revokeObjectURL(picked.url);
			setPicked({ token: answer.cover, url: URL.createObjectURL(file) });
			onCover(answer);
		} catch (failure) {
			setError(
				failure instanceof Refused && failure.sentence !== null
					? failure.sentence
					: t("library.failed"),
			);
		} finally {
			setUploading(false);
		}
	}

	const shownUrl =
		current &&
		(version === 0
			? current.url
			: `${current.url}${current.url.includes("?") ? "&" : "?"}v=${version}`);

	return (
		<figure
			className={styles.card}
			data-over={over || undefined}
			onDragOver={(event) => {
				event.preventDefault();
				setOver(true);
			}}
			onDragLeave={() => setOver(false)}
			onDrop={(event) => {
				event.preventDefault();
				setOver(false);
				void take(droppedFile(event.dataTransfer));
			}}
		>
			<div className={styles.images}>
				{current && shownUrl ? (
					<CoverImage
						src={shownUrl}
						alt={t("album.cover", { title })}
						check={current}
					/>
				) : (
					<p>{t("library.noCover")}</p>
				)}
				{added && (
					<CoverImage
						src={added.url}
						alt={t("library.newCover")}
						check={added.check}
					/>
				)}
			</div>
			<input
				type="file"
				accept="image/*"
				aria-label={t("library.replaceCover")}
				disabled={busy}
				onChange={(event) => {
					void take(event.target.files?.[0]);
					event.target.value = "";
				}}
			/>
			{error && <p role="alert">{error}</p>}
		</figure>
	);
}

function CoverImage({
	src,
	alt,
	check,
}: {
	src: string;
	alt: string;
	check: CoverCheck;
}) {
	const { t } = useTranslate();
	return (
		<figure className={styles.image}>
			<img src={src} alt={alt} />
			<figcaption>
				{t("duplicate.by", { w: check.width, h: check.height })}
			</figcaption>
			{!check.passes && (
				<p className={styles.warning}>
					{t("cover.fails", { problem: check.problem ?? "" })}
				</p>
			)}
		</figure>
	);
}
