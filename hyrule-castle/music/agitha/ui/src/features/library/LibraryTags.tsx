import { useState } from "react";

import type { DiffRow } from "@/domain/album/diff";
import { lockedKind } from "@/domain/album/tagModel";
import { glossOf } from "@/domain/library/gloss";
import {
	applyEdits,
	displayKey,
	isFormatsOwnKey,
	type PanelTrack,
	rawKeyOf,
	sharedTags,
} from "@/domain/library/shared";
import { reachOf, tagRows, withoutKey } from "@/domain/library/tagRows";
import type { DraftEdit, TagNames } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { TagTable } from "@/shared/ui/TagTable";

const GENRE = "Genre";

const joined = (values: string[]) => values.join("\u0000");

/**
 * The review's tag table over tracks of the library: what the files hold, and
 * what the draft makes of it. A value typed in is set on every track given.
 */
export function LibraryTags({
	label,
	addLabel,
	tracks,
	names,
	edits,
	genres,
	readOnly,
	shows = () => true,
	empty,
	onEdits,
}: {
	label: string;
	addLabel?: string;
	/** The tracks an edit made here names. */
	tracks: PanelTrack[];
	names: TagNames;
	edits: DraftEdit[];
	genres: string[];
	readOnly: boolean;
	/** Which of the tracks' tags this table lists; all of them where left out. */
	shows?: (row: DiffRow) => boolean;
	empty?: string;
	onEdits: (change: (now: DraftEdit[]) => DraftEdit[]) => void;
}) {
	const { t } = useTranslate();
	// Tags typed in by key that no track carries yet: each has a row to take its value.
	const [typed, setTyped] = useState<string[]>([]);
	const [refusal, setRefusal] = useState<string | null>(null);

	// Where the tracks differ on a tag, each of its values with how many of them carry it.
	const counts = (of: PanelTrack[]) =>
		new Map(
			sharedTags(of, names).map((row) => [
				row.key,
				row.values
					.map(({ value, count }) => `${value} ${count}/${row.of}`)
					.join("; "),
			]),
		);
	const countsNow = counts(tracks);
	const countsNext = counts(applyEdits(tracks, edits, names));

	const rows = tagRows(tracks, edits, names, typed).filter(
		(row) => typed.includes(row.key) || shows(row),
	);
	const first = tracks[0];

	function set(row: DiffRow, values: string[] | null) {
		const cleared = values === null || values.length === 0;
		if (!cleared && row.key === GENRE) {
			// A genre field takes names on the list only.
			const stray = values.find((value) => !genres.includes(value));
			if (stray !== undefined) {
				setRefusal(t("editor.notGenre", { genre: stray }));
				return;
			}
		}
		setRefusal(null);
		const refs = reachOf(tracks, row.key, names);
		// What the files hold already needs no edit.
		const asHeld = cleared
			? row.now === null
			: Array.isArray(row.now) && joined(row.now) === joined(values);
		onEdits((now) => {
			const rest = withoutKey(now, refs, row.key);
			if (asHeld) return rest;
			return [
				...rest,
				{
					tracks: refs,
					set: { [row.key]: cleared ? null : values },
					add: {},
					remove: {},
				},
			];
		});
	}

	function add(key: string) {
		const reached = tracks.flatMap((track) => {
			const raw = rawKeyOf(track, key, names);
			return raw === null ? [] : [{ track, raw }];
		});
		const [found] = reached;
		const refused =
			found === undefined ||
			lockedKind(key, []) !== null ||
			reached.some(
				({ track, raw }) =>
					track.readonly.includes(raw) || lockedKind(raw, []) !== null,
			);
		if (refused) return t("editor.lockedKey", { key });
		// Each format reads such a key its own way, and the server refuses the edit over tracks of more than one.
		if (
			new Set(tracks.map((track) => track.family)).size > 1 &&
			isFormatsOwnKey(key, names)
		)
			return t("editor.oneFormat", { key });
		const row = displayKey(found.track, found.raw, names);
		if (!typed.includes(row)) setTyped([...typed, row]);
		return null;
	}

	const nameOf = (key: string) => {
		const gloss = glossOf(key);
		return gloss ? t("editor.glossed", { key, gloss: t(gloss) }) : key;
	};

	return (
		<TagTable
			rows={rows}
			label={label}
			addLabel={addLabel}
			editable={!readOnly && tracks.length > 0}
			nameOf={nameOf}
			titleOf={(key) => (first && rawKeyOf(first, key, names)) ?? key}
			empty={empty}
			error={refusal}
			describe={(row, side) =>
				(side === "now" ? countsNow : countsNext).get(row.key)
			}
			onSet={set}
			onUndo={(row) => {
				setRefusal(null);
				setTyped(typed.filter((each) => each !== row.key));
				onEdits((now) =>
					withoutKey(now, reachOf(tracks, row.key, names), row.key),
				);
			}}
			onAdd={add}
		/>
	);
}
