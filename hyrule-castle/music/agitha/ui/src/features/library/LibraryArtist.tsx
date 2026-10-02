import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Tags, Undo2, X } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { formatLength, formatTotalLength } from "@/domain/album/format";
import { summaryOfFiles } from "@/domain/album/summary";
import { describeQuality } from "@/domain/album/summaryFacts";
import { genresQuery, libraryArtistQuery } from "@/domain/library/libraryQuery";
import {
	applyEdits,
	type PanelTrack,
	sharedTags,
} from "@/domain/library/shared";
import type {
	JobAlbum,
	LibraryAlbumSummary,
	TrackRef,
} from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import bar from "@/shared/styles/reviewBar.module.css";
import { Parasol } from "@/shared/ui/Parasol";
import { BatchPreview, BatchProgress } from "./BatchPreview";
import { isEmpty, toWire } from "./draft";
import { FlowNotices } from "./FlowNotices";
import styles from "./LibraryArtist.module.css";
import { Panel } from "./Panel";
import { TagField } from "./TagField";
import { lastSegment, tagOf } from "./tracks";
import { useDraftFlow } from "./useDraftFlow";

// The tags only the album's page edits: those that name a track or an album, or move a file.
const LOCKED = [
	"Title",
	"Artist",
	"Album artist",
	"Artist sort order",
	"Album artist sort order",
	"Album",
	"Date",
	"Original release date",
	"Track number",
	"Disc number",
	"Disc subtitle",
];

// The first tab of the tags: what says which album and which track a file is. Every other tag is under the second.
const ALBUM_DATA = [...LOCKED, "Genre", "Media", "Compilation"];

const GENRE = "Genre";

type Tab = "album" | "meta";

// Two albums may hold a file of one name, so a track is told by both.
const keyOf = (track: TrackRef) => `${track.album}\n${track.path}`;

const ended = (album: JobAlbum) =>
	album.state === "done" || album.state === "failed";

/** The genres of the tracks given, most carried first, each with how many carry it. */
function genresOf(
	tracks: PanelTrack[],
	names: Parameters<typeof sharedTags>[1],
) {
	return (
		sharedTags(tracks, names).find((row) => row.key === GENRE)?.values ?? []
	);
}

export function LibraryArtist({
	letter,
	artist,
}: {
	letter: string;
	artist: string;
}) {
	const { t } = useTranslate();
	const uid = useId();
	const queryClient = useQueryClient();
	const artistQuery = useQuery(libraryArtistQuery(letter, artist));
	const genres = useQuery(genresQuery());
	// Every track is selected until it is taken out, as on an album's page.
	const [unselected, setUnselected] = useState<string[]>([]);
	const [open, setOpen] = useState<string[]>([]);
	const [tagsShown, setTagsShown] = useState(false);
	const [tab, setTab] = useState<Tab>("album");
	const [refusal, setRefusal] = useState<string | null>(null);

	const view = artistQuery.data;
	// The artist and every album under it: a batch may have written any of them.
	const refetchArtist = () =>
		queryClient.invalidateQueries({
			queryKey: libraryArtistQuery(letter, artist).queryKey,
		});

	const flow = useDraftFlow({
		adopted: undefined,
		// The batch has ended once every album it lists is done or failed; it then stands as failed if any was.
		stateOf: (job) => {
			if (job.albums.length === 0) return undefined;
			const running = job.albums.find((each) => !ended(each));
			if (running) return running.state;
			return job.albums.some((each) => each.state === "failed")
				? "failed"
				: "done";
		},
		errorOf: () => t("library.batchFailed"),
		onDone: refetchArtist,
		onFailed: () => void refetchArtist(),
		refresh: () => void refetchArtist(),
	});
	const { draft, readOnly } = flow;

	const albums = view?.albums;
	const tracks = useMemo<PanelTrack[]>(
		() =>
			(albums ?? []).flatMap((album) =>
				album.tracks.map((track) => ({ ...track, album: album.path })),
			),
		[albums],
	);

	if (artistQuery.isError && !view)
		return <p role="alert">{t("library.failed")}</p>;
	if (!view) return <p className={styles.loading}>{t("page.loading")}</p>;

	const names = view.names;
	const isSelected = (key: string) => !unselected.includes(key);
	const chosen = tracks.filter((track) => isSelected(keyOf(track)));
	const refs = chosen.map(({ album, path }) => ({ album, path }));
	const chosenAlbums = view.albums.filter((album) =>
		album.tracks.some((track) =>
			isSelected(keyOf({ album: album.path, path: track.path })),
		),
	);
	const titleOfAlbum = (path: string) =>
		view.albums.find((each) => each.path === path)?.title ?? lastSegment(path);

	function setMany(keys: string[], on: boolean) {
		setUnselected((now) => [
			...now.filter((key) => !keys.includes(key)),
			...(on ? [] : keys),
		]);
	}

	const everyKey = tracks.map(keyOf);
	const progress =
		flow.outcome ?? (readOnly && flow.job !== undefined ? flow.job : null);

	// The name the tags give the artist, where they all give one; the folder's may carry a moved article.
	const tagged = new Set(
		tracks.flatMap((track) => tagOf(track, "Album artist", names)),
	);
	const [onlyName] = tagged;
	const name = tagged.size === 1 && onlyName ? onlyName : artist;

	const after = applyEdits(chosen, draft.edits, names);
	const genresNow = genresOf(after, names);
	const genresWere = genresOf(chosen, names);
	const countWas = (genre: string) =>
		genresWere.find((each) => each.value === genre)?.count ?? 0;
	const dropped = genresWere.filter(
		(was) => !genresNow.some((now) => now.value === was.value),
	);

	const years = chosenAlbums
		.map((album) => album.year)
		.filter(Boolean)
		.sort();
	const span =
		years.length === 0
			? null
			: years[0] === years.at(-1)
				? years[0]
				: `${years[0]}–${years.at(-1)}`;
	const qualities = new Map<string, number>();
	for (const album of chosenAlbums) {
		const summary = summaryOfFiles(album.tracks);
		if (!summary) continue;
		const quality = describeQuality(summary, t);
		qualities.set(quality, (qualities.get(quality) ?? 0) + 1);
	}

	const edit = (change: { add?: string; remove?: string }) =>
		flow.changeDraft((now) => ({
			...now,
			edits: [
				...now.edits,
				{
					tracks: refs,
					set: {},
					add: change.add ? { [GENRE]: [change.add] } : {},
					remove: change.remove ? { [GENRE]: [change.remove] } : {},
				},
			],
		}));

	function addGenre(genre: string) {
		if (genre === "") return false;
		if (!genres.data?.genres.includes(genre)) {
			setRefusal(t("editor.notGenre", { genre }));
			return false;
		}
		setRefusal(null);
		edit({ add: genre });
		return true;
	}

	const wire = () => toWire(draft, tracks, names, true);

	return (
		<section className={styles.artist} aria-labelledby={`${uid}-name`}>
			<header className={styles.header}>
				<p className={styles.caption}>
					{t("artist.caption")} · {letter}/{artist}
				</p>
				<h2 id={`${uid}-name`} className={styles.name}>
					{name}
				</h2>
				<p className={styles.stats}>
					<span>
						<strong>{chosenAlbums.length}</strong>{" "}
						{chosenAlbums.length !== view.albums.length
							? t("artist.albumsOf", { of: view.albums.length })
							: t(chosenAlbums.length === 1 ? "artist.album" : "artist.albums")}
					</span>
					<span>
						<strong>{chosen.length}</strong>{" "}
						{t(chosen.length === 1 ? "artist.track" : "artist.tracks")}
					</span>
					<span>
						{formatTotalLength(
							chosen.reduce((sum, track) => sum + track.length, 0),
						)}
					</span>
					{span && <span>{span}</span>}
					{[...qualities].map(([quality, count]) => (
						<span key={quality} className={styles.quality}>
							{quality}
							{qualities.size > 1 && <> × {count}</>}
						</span>
					))}
				</p>

				<fieldset className={styles.genres} aria-label={t("editor.genres")}>
					<ul className={styles.chips}>
						{genresNow.map(({ value, count }) => (
							<li
								key={value}
								className={styles.chip}
								data-changed={count !== countWas(value) || undefined}
							>
								<span>{value}</span>
								{count < after.length && (
									<span className={styles.count}>
										{count}/{after.length}
									</span>
								)}
								{!readOnly && (
									<button
										type="button"
										className={styles.chipRemove}
										aria-label={t("editor.removeGenre", { genre: value })}
										title={t("artist.removeGenre", {
											genre: value,
											n: count,
										})}
										onClick={() => {
											setRefusal(null);
											edit({ remove: value });
										}}
									>
										<X size={12} aria-hidden="true" />
									</button>
								)}
							</li>
						))}
						{dropped.map(({ value, count }) => (
							<li key={value} className={styles.chip} data-dropped>
								<span>{value}</span>
								<span className={styles.count}>
									{count}/{chosen.length}
								</span>
							</li>
						))}
						{genresNow.length + dropped.length === 0 && (
							<li className={styles.none}>{t("artist.noGenres")}</li>
						)}
					</ul>
					{!readOnly && chosen.length > 0 && genres.data && (
						<span className={styles.addGenre}>
							<TagField
								label={t("editor.addGenre")}
								placeholder={t("artist.addGenre", { n: chosen.length })}
								suggestions={genres.data.genres}
								onCommit={addGenre}
							/>
						</span>
					)}
				</fieldset>
				{refusal && (
					<p role="alert" className={styles.error}>
						{refusal}
					</p>
				)}
			</header>

			<div className={styles.middle}>
				<label className={styles.all}>
					<input
						type="checkbox"
						aria-label={t("library.selectAll")}
						checked={everyKey.length > 0 && chosen.length === everyKey.length}
						ref={(box) => {
							if (box)
								box.indeterminate =
									chosen.length > 0 && chosen.length < everyKey.length;
						}}
						disabled={readOnly}
						onChange={(event) => setMany(everyKey, event.target.checked)}
					/>
					<span>
						{t("artist.selected", {
							n: chosenAlbums.length,
							of: view.albums.length,
						})}
					</span>
				</label>

				<ul className={styles.albums}>
					{view.albums.map((album) => (
						<AlbumRow
							key={album.path}
							album={album}
							letter={letter}
							artist={artist}
							names={names}
							edits={draft.edits}
							isSelected={isSelected}
							readOnly={readOnly}
							isOpen={open.includes(album.path)}
							onOpen={() =>
								setOpen((now) =>
									now.includes(album.path)
										? now.filter((each) => each !== album.path)
										: [...now, album.path],
								)
							}
							setMany={setMany}
						/>
					))}
				</ul>
			</div>

			<footer className={styles.footer}>
				<div className={styles.drawer}>
					{progress && (
						<BatchProgress albums={progress.albums} titleOf={titleOfAlbum} />
					)}

					{!readOnly && flow.preview && (
						<BatchPreview
							preview={flow.preview}
							titleOf={titleOfAlbum}
							onApply={() => flow.save(wire())}
						/>
					)}

					<FlowNotices
						flow={flow}
						failed={genres.isError}
						onReload={() => {
							flow.discard();
							void refetchArtist();
						}}
					/>

					{tagsShown && genres.data && (
						<div id={`${uid}-tags`} className={styles.tags}>
							<div role="tablist" className={styles.tabs}>
								{(["album", "meta"] as const).map((each) => (
									<button
										key={each}
										type="button"
										role="tab"
										aria-selected={tab === each}
										className={styles.tab}
										onClick={() => setTab(each)}
									>
										{t(each === "album" ? "artist.tabAlbum" : "artist.tabMeta")}
									</button>
								))}
							</div>
							<Panel
								readOnly={readOnly}
								tracks={tracks}
								selected={refs}
								names={names}
								edits={draft.edits}
								genres={genres.data.genres}
								locked={LOCKED}
								shows={(key) => ALBUM_DATA.includes(key) === (tab === "album")}
								onEdit={(each) =>
									flow.changeDraft((now) => ({
										...now,
										edits: [...now.edits, each],
									}))
								}
							/>
						</div>
					)}
				</div>

				<div className={styles.actions}>
					<button
						type="button"
						className={bar.ghost}
						aria-expanded={tagsShown}
						aria-controls={`${uid}-tags`}
						onClick={() => setTagsShown(!tagsShown)}
					>
						<Tags size={14} aria-hidden="true" />
						{t(tagsShown ? "artist.hideTags" : "artist.showTags")}
					</button>
					<span className={styles.spacer} />
					{!isEmpty(draft) && !readOnly && (
						<span className={bar.unsaved}>{t("library.unsaved")}</span>
					)}
					<button
						type="button"
						className={bar.ghost}
						disabled={readOnly || isEmpty(draft)}
						onClick={() => {
							setRefusal(null);
							flow.discard();
						}}
					>
						<Undo2 size={14} aria-hidden="true" />
						{t("library.discard")}
					</button>
					<button
						type="button"
						className={bar.primary}
						disabled={readOnly || isEmpty(draft) || flow.previewPending}
						onClick={() => flow.review(wire())}
					>
						{t("library.review")}
					</button>
				</div>
			</footer>
		</section>
	);
}

function AlbumRow({
	album,
	letter,
	artist,
	names,
	edits,
	isSelected,
	readOnly,
	isOpen,
	onOpen,
	setMany,
}: {
	album: LibraryAlbumSummary;
	letter: string;
	artist: string;
	names: Parameters<typeof sharedTags>[1];
	edits: Parameters<typeof applyEdits>[1];
	isSelected: (key: string) => boolean;
	readOnly: boolean;
	isOpen: boolean;
	onOpen: () => void;
	setMany: (keys: string[], on: boolean) => void;
}) {
	const { t } = useTranslate();
	const own = album.tracks.map(
		(track): PanelTrack => ({ ...track, album: album.path }),
	);
	const keys = own.map(keyOf);
	const chosen = keys.filter(isSelected).length;
	const summary = summaryOfFiles(album.tracks);
	const after = applyEdits(own, edits, names);
	const genres = genresOf(after, names);

	return (
		<li className={styles.album} data-selected={chosen > 0 || undefined}>
			<div className={styles.head}>
				<input
					type="checkbox"
					aria-label={t("library.select", { title: album.title })}
					checked={keys.length > 0 && chosen === keys.length}
					ref={(box) => {
						if (box) box.indeterminate = chosen > 0 && chosen < keys.length;
					}}
					disabled={readOnly}
					onChange={(event) => setMany(keys, event.target.checked)}
				/>
				{album.cover_url ? (
					<img
						src={album.cover_url}
						alt={t("album.cover", { title: album.title })}
						className={styles.cover}
						loading="lazy"
					/>
				) : (
					<span className={styles.cover} data-none>
						<Parasol size={20} />
					</span>
				)}
				<div className={styles.what}>
					<Link
						to="/library/$letter/$artist/$album"
						params={{ letter, artist, album: album.name }}
						className={styles.albumTitle}
					>
						{album.title}
					</Link>
					<p className={styles.facts}>
						<span className={styles.year}>{album.year}</span>
						<span>{t("match.tracks", { n: album.tracks.length })}</span>
						{summary && <span>{describeQuality(summary, t)}</span>}
					</p>
				</div>
				<ul className={styles.albumGenres} aria-label={t("editor.genres")}>
					{genres.map(({ value, count }) => (
						<li key={value} data-partial={count < after.length || undefined}>
							{value}
							{count < after.length && (
								<span className={styles.count}>
									{" "}
									{count}/{after.length}
								</span>
							)}
						</li>
					))}
				</ul>
				<button
					type="button"
					className={styles.open}
					aria-expanded={isOpen}
					onClick={onOpen}
				>
					<ChevronRight
						size={14}
						aria-hidden="true"
						className={isOpen ? styles.turned : undefined}
					/>
					<span className="visually-hidden">{album.title}</span>
				</button>
			</div>
			{isOpen && (
				<ul className={styles.tracks}>
					{own.map((track) => {
						const title =
							tagOf(track, "Title", names)[0] || lastSegment(track.path);
						const key = keyOf(track);
						return (
							<li key={track.path}>
								<label>
									<input
										type="checkbox"
										aria-label={t("library.select", { title })}
										checked={isSelected(key)}
										disabled={readOnly}
										onChange={(event) => setMany([key], event.target.checked)}
									/>
									<span>{title}</span>
								</label>
								<span className={styles.length}>
									{formatLength(track.length)}
								</span>
							</li>
						);
					})}
				</ul>
			)}
		</li>
	);
}
