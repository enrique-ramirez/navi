import type { AlbumView } from "@/shared/api/types";
import { albumStatePhrase } from "@/shared/i18n/albumState";
import type { useTranslate } from "@/shared/i18n/useTranslate";

type Translate = ReturnType<typeof useTranslate>["t"];

const upperFirst = (text: string) =>
	text.charAt(0).toUpperCase() + text.slice(1);

// The details `_missing_holds` in `musiclib/batch/identify.py` words for a `missing` hold. The
// title of a told track ends at the closing quote, not at the first colon, since a title can hold one.
const TOLD = /^track (\d+), "(.*?)"(?:: (.*))?$/s;
const COULD_BE = /^(.+) could be it, but it cannot be read$/s;
const UNPLACED = /^a track is missing: (.+) cannot be read$/s;
const FOLDER = /^tracks may be missing: (.+) cannot be read$/s;

export function missingWords(detail: string, t: Translate) {
	const told = TOLD.exec(detail);
	if (told) {
		const [, n = "", title = "", rest] = told;
		const sentence = title
			? t("missing.track", { n, title })
			: t("missing.trackBare", { n });
		const file = rest === undefined ? undefined : COULD_BE.exec(rest)?.[1];
		if (file !== undefined)
			return { sentence, extra: t("missing.couldBe", { file }) };
		return { sentence, extra: rest ? upperFirst(rest) : null };
	}
	const unplaced = UNPLACED.exec(detail)?.[1];
	if (unplaced !== undefined) {
		return { sentence: t("missing.unplaced", { file: unplaced }), extra: null };
	}
	const folder = FOLDER.exec(detail)?.[1];
	if (folder !== undefined) {
		return { sentence: t("missing.folder", { folder }), extra: null };
	}
	return { sentence: upperFirst(detail), extra: null };
}

// The server's `reason` sentence is for logs and never shown.
export function approveReason(view: AlbumView, t: Translate): string | null {
	const { code, hold, ok } = view.approvable;
	if (ok) return null;
	switch (code) {
		case "not-accepted":
			return t("approve.notAccepted");
		case "held":
			if (hold?.kind === "missing") {
				const { sentence, extra } = missingWords(hold.detail, t);
				return extra ? `${sentence}: ${extra}` : sentence;
			}
			return hold?.detail
				? t("approve.held", {
						kind: t(`hold.${hold.kind}`),
						detail: hold.detail,
					})
				: t("approve.heldBare", { kind: hold ? t(`hold.${hold.kind}`) : "" });
		case "in-library":
			return t("state.inLibrary");
		default:
			return t(albumStatePhrase[view.state]);
	}
}
