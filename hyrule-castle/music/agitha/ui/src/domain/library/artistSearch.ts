import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { fetchArtists } from "@/shared/api/library";
import type { FoundArtist } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import type { Lookup } from "@/shared/ui/SuggestInput";

/** The readable name of the tag that holds each artist of a track's credit. */
export const TRACK_ARTISTS = "Artists";

/** The readable names of the tags that hold one value per artist. */
export const ARTIST_LISTS = [TRACK_ARTISTS, "Album artists"];

const WAIT_MS = 300;
const SHORTEST = 2;

/** What tells one artist from another of the same name: its kind, its country and MusicBrainz's own note. */
const hintOf = (artist: FoundArtist) =>
	[artist.type, artist.country, artist.disambiguation]
		.filter(Boolean)
		.join(" \u00b7 ");

/**
 * The artists MusicBrainz knows by the name being typed, asked for once the
 * typing rests. The last answer stays while the next is fetched, so the list
 * does not blink between letters, and an answer is kept for the page's life:
 * `retry` asks MusicBrainz again.
 */
export function useArtistLookup(): Lookup {
	const { t } = useTranslate();
	const [typed, setTyped] = useState("");
	const [name, setName] = useState("");
	const wanted = typed.trim();
	useEffect(() => {
		const timer = setTimeout(() => setName(wanted), WAIT_MS);
		return () => clearTimeout(timer);
	}, [wanted]);

	const asks = name.length >= SHORTEST;
	const found = useQuery({
		queryKey: ["artists", name.toLowerCase()],
		queryFn: () => fetchArtists(name),
		enabled: asks,
		staleTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		retry: false,
		placeholderData: keepPreviousData,
	});

	const hints = new Map<string, string>();
	for (const artist of found.data?.artists ?? [])
		if (!hints.has(artist.name)) hints.set(artist.name, hintOf(artist));

	const retry = {
		label: t("artists.again"),
		run: () => void found.refetch(),
	};
	const busy =
		wanted.length >= SHORTEST && (wanted !== name || found.isFetching);
	const status = busy
		? { text: t("artists.searching") }
		: !asks || wanted.length < SHORTEST
			? null
			: found.isError || found.data?.answered === false
				? { text: t("artists.noAnswer"), retry }
				: hints.size === 0
					? { text: t("artists.none", { name }), retry }
					: null;

	return {
		options: [...hints.keys()],
		hintOf: (artist) => hints.get(artist) || undefined,
		search: setTyped,
		status,
	};
}
