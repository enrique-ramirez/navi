import { useEffect, useRef, useState } from "react";
import { putLibraryCover, Refused } from "@/shared/api/library";
import type {
	CoverCheck,
	CoverUpload,
	LibraryCover as ServedCover,
} from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { CoverPicker, type ShownCover } from "@/shared/ui/CoverPicker";

interface Picked {
	token: string;
	url: string;
}

const shownOf = (check: CoverCheck, url: string): ShownCover => ({
	url,
	width: check.width,
	height: check.height,
	problem: check.passes ? null : (check.problem ?? ""),
});

/** The address the album's cover is fetched from after `version` saves have written one over it. */
export const versioned = (url: string, version: number) =>
	version === 0 ? url : `${url}${url.includes("?") ? "&" : "?"}v=${version}`;

/**
 * The album's cover and the image that would replace it. The new image is
 * `cover`, the page's draft; the card keeps only its own preview address, and
 * hands it up with the draft so the review can show the image too.
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
	/** The new cover and where the page can show it from; `null` twice to keep the one the album has. */
	onCover: (cover: CoverUpload | null, url: string | null) => void;
}) {
	const { t } = useTranslate();
	const [picked, setPicked] = useState<Picked | null>(null);
	const [uploading, setUploading] = useState(false);
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

	const added =
		cover !== null && picked?.token === cover.cover
			? shownOf(cover, picked.url)
			: null;
	const now = current && shownOf(current, versioned(current.url, version));

	async function take(file: File | null | undefined) {
		if (!file) return null;
		setUploading(true);
		try {
			const answer = await putLibraryCover(file);
			if (picked) URL.revokeObjectURL(picked.url);
			const url = URL.createObjectURL(file);
			setPicked({ token: answer.cover, url });
			onCover(answer, url);
			return null;
		} catch (failure) {
			return failure instanceof Refused && failure.sentence !== null
				? failure.sentence
				: t("library.failed");
		} finally {
			setUploading(false);
		}
	}

	return (
		<CoverPicker
			title={title}
			next={added ?? now}
			now={now}
			sides={added !== null}
			nextAlt={added ? t("library.newCover") : undefined}
			noNext={t("library.noCover")}
			noNow={t("library.noCover")}
			pickLabel={t("library.replaceCover")}
			disabled={readOnly || uploading}
			undo={
				added && !readOnly
					? { label: t("library.keepCover"), run: () => onCover(null, null) }
					: null
			}
			onFile={take}
		/>
	);
}
