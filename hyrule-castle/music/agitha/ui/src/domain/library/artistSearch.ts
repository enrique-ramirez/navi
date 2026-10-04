import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { fetchArtists } from "@/shared/api/library";
import type { FoundArtist } from "@/shared/api/types";

/** The readable names of the tags that hold one value per artist. */
export const ARTIST_LISTS = ["Artists", "Album artists"];

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
 * does not blink between letters.
 */
export function useArtistSearch() {
	const [typed, setTyped] = useState("");
	const [name, setName] = useState("");
	useEffect(() => {
		const timer = setTimeout(() => setName(typed.trim()), WAIT_MS);
		return () => clearTimeout(timer);
	}, [typed]);

	const found = useQuery({
		queryKey: ["artists", name.toLowerCase()],
		queryFn: () => fetchArtists(name),
		enabled: name.length >= SHORTEST,
		staleTime: Number.POSITIVE_INFINITY,
		refetchOnWindowFocus: false,
		retry: false,
		placeholderData: keepPreviousData,
	});

	const hints = new Map<string, string>();
	for (const artist of found.data?.artists ?? [])
		if (!hints.has(artist.name)) hints.set(artist.name, hintOf(artist));

	return {
		search: setTyped,
		names: [...hints.keys()],
		hintOf: (artist: string) => hints.get(artist) || undefined,
	};
}
