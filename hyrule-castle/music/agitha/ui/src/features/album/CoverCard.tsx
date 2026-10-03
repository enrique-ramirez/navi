import { useEffect, useRef, useState } from "react";

import { putCover } from "@/shared/api/album";
import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { CoverPicker, type ShownCover } from "@/shared/ui/CoverPicker";
import type { Pending } from "./pending";

// The image types the server reads.
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

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
	const [chosen, setChosen] = useState<ShownCover | null>(null);
	const [kept, setKept] = useState(false);
	const last = useRef<string | null>(null);
	last.current = chosen?.url ?? null;
	useEffect(
		() => () => {
			if (last.current) URL.revokeObjectURL(last.current);
		},
		[],
	);

	const sent = pending.draft.cover ?? null;
	const shownChosen = sent ? chosen : null;
	const planned = "cover.jpg" in (view.preview?.images ?? {});

	async function take(file: File | null | undefined) {
		if (!file || !IMAGE_TYPES.includes(file.type)) return t("cover.notImage");
		const answer = await putCover(view, file);
		if (!answer.ok) return answer.error ?? t("cover.failed");
		const result = answer.body;
		pending.setCover(result.path);
		if (chosen) URL.revokeObjectURL(chosen.url);
		setChosen({
			url: URL.createObjectURL(file),
			width: result.width,
			height: result.height,
			problem: result.passes ? null : (result.problem ?? ""),
		});
		setKept(false);
		return null;
	}

	// The cover the files have is sent as the owner's, as if it had been dropped here.
	async function keep() {
		if (!view.cover_now) return null;
		let file: File;
		try {
			const answer = await fetch(view.cover_now.url);
			if (!answer.ok) return t("cover.failed");
			const data = await answer.blob();
			file = new File([data], "cover", { type: data.type });
		} catch {
			return t("cover.failed");
		}
		const refusal = await take(file);
		if (refusal === null) setKept(true);
		return refusal;
	}

	return (
		<CoverPicker
			title={title}
			next={shownChosen ?? view.cover}
			// The warning is about the cover the album will get; the one it has is on its way out.
			now={view.cover_now && { ...view.cover_now, problem: null }}
			noNext={t(planned ? "cover.notShown" : "cover.noneNext")}
			noNow={t("cover.noneNow")}
			pickLabel={t("cover.pick")}
			undo={
				shownChosen && planned
					? { label: t("cover.undo"), run: () => pending.setCover(null) }
					: null
			}
			keep={
				view.cover_now && !(shownChosen && kept)
					? { label: t("cover.keep"), run: keep }
					: null
			}
			onFile={take}
		/>
	);
}
