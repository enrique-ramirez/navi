import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { DiffRow } from "@/domain/album/diff";
import { editKeyOf } from "@/domain/album/diff";
import { GENRE } from "@/domain/album/neutral";
import { lockedKind } from "@/domain/album/tagModel";
import { ARTIST_LISTS, useArtistSearch } from "@/domain/library/artistSearch";
import { genresQuery } from "@/domain/library/libraryQuery";
import type { AlbumView, Family } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { TagTable } from "@/shared/ui/TagTable";
import type { Pending } from "./pending";

export function TagDiff({
	view,
	pending,
	rows,
	scope,
	family,
	label,
}: {
	view: AlbumView;
	pending: Pending;
	rows: DiffRow[];
	scope: string | "all";
	family: Family;
	label: string;
}) {
	const { t } = useTranslate();
	const names = view.names[family] ?? {};
	const genres = useQuery(genresQuery()).data?.genres;
	const [refusal, setRefusal] = useState<string | null>(null);
	const artists = useArtistSearch();
	const listsArtists = (row: DiffRow) =>
		ARTIST_LISTS.includes(names[row.key] ?? "");

	// Identify refuses a genre that is not on the list; saying so here saves the wait for it.
	function offTheList(key: string, values: string[] | null) {
		const stray =
			key === GENRE && genres
				? values?.find((value) => !genres.includes(value))
				: undefined;
		setRefusal(
			stray === undefined ? null : t("editor.notGenre", { genre: stray }),
		);
		return stray !== undefined;
	}

	function set(row: DiffRow, values: string[] | null) {
		const key = editKeyOf(view, row.key);
		if (offTheList(key, values)) return;
		const planned = view.preview?.files.find(
			(file) => scope === "all" || file.position === scope,
		)?.after[row.key];
		const same =
			values !== null &&
			planned !== undefined &&
			values.join("\u0000") === planned.join("\u0000");
		if (same) pending.removeEdit(scope, key);
		else
			pending.setEdit(scope, key, values && values.length > 0 ? values : null);
	}

	function add(typed: string, values: string[]) {
		if (lockedKind(typed, [])) return t("editor.lockedKey", { key: typed });
		// The neutral name, however it was typed, so `Genre` lands on the genre's own row.
		const key = typed.toLowerCase() === GENRE ? GENRE : editKeyOf(view, typed);
		if (offTheList(key, values)) return null;
		const held = rows.some(
			(row) => row.key === typed || editKeyOf(view, row.key) === key,
		);
		if (values.length > 0) pending.setEdit(scope, key, values);
		else if (!held) pending.setEdit(scope, key, [""]);
		return null;
	}

	return (
		<TagTable
			rows={rows}
			label={label}
			editable={pending.draft.action === "accept"}
			nameOf={(key) => names[key] ?? key}
			error={refusal}
			// A list from the start, empty until the genres arrive: the field is not swapped under the owner's typing.
			optionsOf={(row) =>
				editKeyOf(view, row.key) === GENRE
					? (genres ?? [])
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
				pending.removeEdit(scope, editKeyOf(view, row.key));
			}}
			onAdd={add}
		/>
	);
}
