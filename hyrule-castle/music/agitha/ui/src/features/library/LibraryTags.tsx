import { useState } from "react";

import type { DiffRow } from "@/domain/album/diff";
import { lockedKind } from "@/domain/album/tagModel";
import { ARTIST_LISTS, useArtistSearch } from "@/domain/library/artistSearch";
import { glossOf } from "@/domain/library/gloss";
import {
	applyEdits,
	displayKey,
	GENRE,
	isFormatsOwnKey,
	type PanelTrack,
	rawKeyOf,
	sharedTags,
} from "@/domain/library/shared";
import {
	reachOf,
	standingRows,
	tagRows,
	withoutKey,
} from "@/domain/library/tagRows";
import type { DraftEdit, TagNames } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { TagTable } from "@/shared/ui/TagTable";

const joined = (values: string[]) => values.join("\u0000");

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
	tracks: PanelTrack[];
	names: TagNames;
	edits: DraftEdit[];
	genres: string[];
	readOnly: boolean;
	shows?: (row: DiffRow) => boolean;
	empty?: string;
	onEdits: (change: (now: DraftEdit[]) => DraftEdit[]) => void;
}) {
	const { t } = useTranslate();
	const [typed, setTyped] = useState<string[]>([]);
	const [refusal, setRefusal] = useState<string | null>(null);

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

	const rows = tagRows(tracks, edits, names, [
		...standingRows(tracks, names),
		...typed,
	]).filter((row) => typed.includes(row.key) || shows(row));
	const artists = useArtistSearch();
	const listsArtists = (row: DiffRow) => ARTIST_LISTS.includes(row.key);
	const first = tracks[0];

	function set(row: DiffRow, values: string[] | null) {
		const cleared = values === null || values.length === 0;
		if (!cleared && row.key === GENRE) {
			const stray = values.find((value) => !genres.includes(value));
			if (stray !== undefined) {
				setRefusal(t("editor.notGenre", { genre: stray }));
				return;
			}
		}
		setRefusal(null);
		const refs = reachOf(tracks, row.key, names);
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

	function add(key: string, values: string[]) {
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
		if (
			new Set(tracks.map((track) => track.family)).size > 1 &&
			isFormatsOwnKey(key, names)
		)
			return t("editor.oneFormat", { key });
		const row = displayKey(found.track, found.raw, names);
		if (!typed.includes(row)) setTyped([...typed, row]);
		if (values.length > 0)
			set(
				{
					key: row,
					now: null,
					next: null,
					change: "same",
					locked: null,
					edited: false,
					removedBy: [],
				},
				values,
			);
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
			optionsOf={(row) =>
				row.key === GENRE
					? genres
					: listsArtists(row)
						? artists.names
						: undefined
			}
			hintOf={(row, option) =>
				listsArtists(row) ? artists.hintOf(option) : undefined
			}
			onTyped={(row, term) => {
				if (listsArtists(row)) artists.search(term);
			}}
			unsetOf={(row) => (listsArtists(row) ? t("tags.asCredited") : undefined)}
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
