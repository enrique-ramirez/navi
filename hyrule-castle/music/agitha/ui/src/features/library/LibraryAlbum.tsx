import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeftRight, ScanSearch, Undo2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { describeEncoding } from "@/domain/album/describeEncoding";
import {
	formatKbps,
	formatLength,
	formatSize,
	formatValues,
} from "@/domain/album/format";
import { summaryOfFiles } from "@/domain/album/summary";
import { summaryFacts } from "@/domain/album/summaryFacts";
import {
	genresQuery,
	isSaving,
	libraryAlbumKey,
	libraryAlbumQuery,
	libraryArtistQuery,
	libraryOrderQuery,
} from "@/domain/library/libraryQuery";
import { applyEdits, type PanelTrack } from "@/domain/library/shared";
import { ALBUM_TAGS, tagRows } from "@/domain/library/tagRows";
import { mimeOf, usePlayer } from "@/domain/player/usePlayer";
import { postMatch, Refused } from "@/shared/api/library";
import type { DraftEdit, LibraryJob } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import page from "@/shared/styles/albumPage.module.css";
import bar from "@/shared/styles/reviewBar.module.css";
import detail from "@/shared/styles/trackDetail.module.css";
import { Alert } from "@/shared/ui/Alert";
import { FactsList } from "@/shared/ui/FactsList";
import { SideSummary } from "@/shared/ui/SideSummary";
import { TrackRows } from "@/shared/ui/TrackRows";
import { isEmpty, toWire, withSwap } from "./draft";
import { FlowNotices } from "./FlowNotices";
import styles from "./LibraryAlbum.module.css";
import { LibraryCover, versioned } from "./LibraryCover";
import { LibraryTags } from "./LibraryTags";
import { ReviewChanges } from "./ReviewChanges";
import { SaveProgress } from "./SaveProgress";
import { OrderNote, RowOrder } from "./TrackOrder";
import { lastSegment, tagOf } from "./tracks";
import { useDraftFlow } from "./useDraftFlow";

export function LibraryAlbum({
	letter,
	artist,
	album,
}: {
	letter: string;
	artist: string;
	album: string;
}) {
	const { t } = useTranslate();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const player = usePlayer();
	const path = [letter, artist, album].join("/");
	const albumKey = libraryAlbumKey(letter, artist, album);

	const albumQuery = useQuery(libraryAlbumQuery(letter, artist, album));
	const genres = useQuery(genresQuery());
	const order = useQuery(
		libraryOrderQuery(letter, artist, album, albumQuery.data !== undefined),
	);
	// The tracks an edit of the album's tags leaves out, and the one whose own tags are on show.
	const [unselected, setUnselected] = useState<string[]>([]);
	const [focused, setFocused] = useState<string | null>(null);

	const view = albumQuery.data;
	const names = view?.names;

	const ofThisAlbum = (job: LibraryJob | undefined) =>
		job?.albums.find((each) => each.path === path);

	// Bumped by a done save that carried a cover: the album is then served at the same cover URL.
	const [coverVersion, setCoverVersion] = useState(0);
	const savedCover = useRef(false);
	// Where the draft's cover can be shown from; the cover card owns the address.
	const [coverUrl, setCoverUrl] = useState<string | null>(null);

	const flow = useDraftFlow({
		adopted: view?.job,
		stateOf: (job) => ofThisAlbum(job)?.state,
		errorOf: (job) => ofThisAlbum(job)?.error,
		refresh: () =>
			void queryClient.invalidateQueries({ queryKey: albumKey, exact: true }),
		onDone: async (job) => {
			if (savedCover.current) setCoverVersion((now) => now + 1);
			const moved = ofThisAlbum(job)?.new_path;
			const artists = {
				queryKey: libraryArtistQuery(letter, artist).queryKey,
				exact: true,
			};
			if (moved !== undefined && moved !== path) {
				// Leave the old address before anything asks for it again, then list every folder afresh.
				const [l = "", a = "", b = ""] = moved.split("/");
				await navigate({
					to: "/library/$letter/$artist/$album",
					params: { letter: l, artist: a, album: b },
				});
				queryClient.removeQueries({ queryKey: albumKey });
				await queryClient.invalidateQueries({ queryKey: ["library"] });
				return;
			}
			await Promise.all([
				queryClient.invalidateQueries(artists),
				queryClient.invalidateQueries({ queryKey: albumKey, exact: true }),
				queryClient.invalidateQueries({
					queryKey: libraryOrderQuery(letter, artist, album, true).queryKey,
					exact: true,
				}),
			]);
		},
	});
	const { draft, state } = flow;

	const matching = useMutation({
		mutationFn: postMatch,
		onSuccess: async ({ drop, n }) => {
			// The album is read-only from now on; what comes back to must not be the copy cached before.
			await queryClient.invalidateQueries({ queryKey: albumKey, exact: true });
			await navigate({ to: "/drops/$drop/albums/$n", params: { drop, n } });
		},
	});

	const tracks = useMemo<PanelTrack[]>(
		() => (view?.tracks ?? []).map((track) => ({ ...track, album: path })),
		[view, path],
	);
	// How many of each track's tags the draft changes, for the mark on its row.
	const changes = useMemo(
		() =>
			names
				? Object.fromEntries(
						tracks.map((track) => [
							track.path,
							tagRows([track], draft.edits, names).filter(
								(row) => row.change !== "same",
							).length,
						]),
					)
				: {},
		[tracks, draft.edits, names],
	);

	if (albumQuery.isError && !view)
		return <p role="alert">{t("library.failed")}</p>;
	if (!view || !names)
		return <p className={styles.loading}>{t("page.loading")}</p>;

	const selected = tracks.filter((track) => !unselected.includes(track.path));
	const shown = tracks.find((track) => track.path === focused) ?? tracks[0];

	// The side column says what the album is once the draft lands, as the review's does.
	const [first] = applyEdits(tracks.slice(0, 1), draft.edits, names);
	const title = (first && tagOf(first, "Album", names)[0]) || lastSegment(path);
	const heading =
		(tracks[0] && tagOf(tracks[0], "Album", names)[0]) || lastSegment(path);
	const summary = summaryOfFiles(tracks);
	const answer = flow.preview?.albums[0];
	// An album with a match open is the review's to change until the match lands.
	const readOnly = flow.readOnly || view.match !== null;

	const editEdits = (change: (now: DraftEdit[]) => DraftEdit[]) =>
		flow.changeDraft((now) => ({ ...now, edits: change(now.edits) }));

	// A tag the selected tracks agree on, or one that says what the album is, is the album's; the rest are each track's own.
	const albumRows = new Set(
		tagRows(selected, draft.edits, names)
			.filter((row) => row.next !== "differs" || ALBUM_TAGS.includes(row.key))
			.map((row) => row.key),
	);
	const shownIsSelected =
		shown !== undefined && !unselected.includes(shown.path);

	const discs = new Set(tracks.map((track) => track.disc));
	const numberOf = (track: PanelTrack) => {
		const number = String(track.number).padStart(2, "0");
		return discs.size > 1 ? `${track.disc}-${number}` : number;
	};
	const labelOf = (file: string) => {
		const found = tracks.find((track) => track.path === file);
		return found ? numberOf(found) : file;
	};
	const titleOf = (track: PanelTrack) =>
		tagOf(track, "Title", names)[0] || lastSegment(track.path);
	// A pair goes to the draft in album order, whichever way round it was named.
	const inAlbumOrder = ([a, b]: [string, string]): [string, string] =>
		tracks.findIndex((track) => track.path === a) <=
		tracks.findIndex((track) => track.path === b)
			? [a, b]
			: [b, a];
	const swap = (pair: [string, string]) =>
		flow.changeDraft((now) => withSwap(now, inAlbumOrder(pair)));

	function reload() {
		flow.discard();
		void queryClient.invalidateQueries({ queryKey: albumKey, exact: true });
	}

	return (
		<section className={styles.album}>
			<div className={bar.bar}>
				<div className={bar.inner}>
					<div className={bar.where}>
						<Link
							to="/library/$letter/$artist"
							params={{ letter, artist }}
							className={bar.crumb}
						>
							{t("library.crumb")} · {letter} / {artist}
						</Link>
						<div className={bar.titleLine}>
							<h2 className={bar.title}>{heading}</h2>
						</div>
					</div>
					<div className={bar.actions}>
						{!isEmpty(draft) && !readOnly && (
							<span className={bar.unsaved}>{t("library.unsaved")}</span>
						)}
						{!readOnly && selected.length === 2 && (
							<button
								type="button"
								className={bar.ghost}
								onClick={() =>
									swap([selected[0]?.path ?? "", selected[1]?.path ?? ""])
								}
							>
								<ArrowLeftRight size={14} aria-hidden="true" />
								{t("library.swap")}
							</button>
						)}
						<button
							type="button"
							className={bar.ghost}
							disabled={readOnly || !isEmpty(draft) || matching.isPending}
							onClick={() => matching.mutate(view.path)}
						>
							<ScanSearch size={14} aria-hidden="true" />
							{t("library.match")}
						</button>
						<button
							type="button"
							className={bar.ghost}
							disabled={readOnly || isEmpty(draft)}
							onClick={flow.discard}
						>
							<Undo2 size={14} aria-hidden="true" />
							{t("library.discard")}
						</button>
						<button
							type="button"
							className={bar.primary}
							disabled={readOnly || isEmpty(draft) || flow.previewPending}
							onClick={() => flow.review(toWire(draft, tracks, names, false))}
						>
							{t("library.review")}
						</button>
					</div>
				</div>
			</div>

			<div className={styles.notices}>
				{view.match && (
					<p className={styles.inReview}>
						{t("library.openInReview")}{" "}
						<Link
							to="/drops/$drop/albums/$n"
							params={{ drop: view.match.drop, n: view.match.n }}
						>
							{t("library.openReview")}
						</Link>
					</p>
				)}
				{state !== null && isSaving(state) && <SaveProgress state={state} />}
				{!readOnly && answer && (
					<ReviewChanges
						preview={answer}
						was={view.cover}
						covers={{
							was: view.cover && versioned(view.cover.url, coverVersion),
							next: coverUrl,
						}}
						onSave={() => {
							savedCover.current = draft.cover !== null;
							flow.save(toWire(draft, tracks, names, false));
						}}
					/>
				)}
				{matching.isError && (
					<Alert>
						{matching.error instanceof Refused && matching.error.sentence
							? matching.error.sentence
							: t("library.failed")}
					</Alert>
				)}
				<FlowNotices flow={flow} failed={genres.isError} onReload={reload} />
			</div>

			<div className={page.album}>
				<SideSummary
					cover={
						<LibraryCover
							current={view.cover}
							cover={draft.cover}
							version={coverVersion}
							title={heading}
							readOnly={readOnly}
							onCover={(cover, url) => {
								setCoverUrl(url);
								flow.changeDraft((now) => ({ ...now, cover }));
							}}
						/>
					}
					title={title}
					titleIsHeading={false}
					artist={formatValues(
						first ? tagOf(first, "Album artist", names) : [],
					)}
					year={(first && tagOf(first, "Date", names)[0]?.slice(0, 4)) ?? ""}
					genres={first ? tagOf(first, "Genre", names) : []}
					facts={[
						...(summary ? summaryFacts(summary, t) : []),
						{ name: t("library.folder.fact"), value: view.path, path: true },
					]}
				/>
				<div className={page.main}>
					<div className={page.group}>
						<h3 className={page.label}>
							{selected.length === tracks.length
								? t("page.albumTags", { n: tracks.length })
								: t("library.tagsOnSelected", { n: selected.length })}
						</h3>
						{genres.data && (
							<LibraryTags
								label={t("page.albumTags", { n: tracks.length })}
								tracks={selected}
								names={names}
								edits={draft.edits}
								genres={genres.data.genres}
								readOnly={readOnly}
								shows={(row) => albumRows.has(row.key)}
								empty={
									selected.length === 0 ? t("library.noneSelected") : undefined
								}
								onEdits={editEdits}
							/>
						)}
					</div>
				</div>
			</div>

			<section className={page.tracks} aria-labelledby="tracks-title">
				<div className={page.trackList}>
					<h3 id="tracks-title" className={page.label}>
						{t("tracks.title")}
					</h3>
					<TrackRows
						player={player}
						rows={tracks.map((track) => ({
							id: track.path,
							number: numberOf(track),
							title: titleOf(track),
							artist: formatValues(tagOf(track, "Artist", names)),
							file: lastSegment(track.path),
							length: formatLength(track.length),
							audio: {
								format: track.format,
								url: track.audio_url,
								mime: mimeOf(track.format),
							},
							changes: changes[track.path] ?? 0,
							note: (
								<RowOrder
									path={track.path}
									flags={order.data?.checked ? order.data.flags : []}
									swaps={draft.swaps}
									labelOf={labelOf}
									readOnly={readOnly}
									onSwap={swap}
								/>
							),
						}))}
						selected={shown?.path ?? null}
						onSelect={setFocused}
						checks={{
							checked: (file) => !unselected.includes(file),
							disabled: readOnly,
							labelAll: t("library.selectAll"),
							labelOf: (row) => t("library.select", { title: row.title }),
							onToggle: (file) =>
								setUnselected((now) =>
									now.includes(file)
										? now.filter((each) => each !== file)
										: [...now, file],
								),
							onToggleAll: () =>
								setUnselected(
									selected.length === tracks.length
										? tracks.map((track) => track.path)
										: [],
								),
						}}
					/>
					<OrderNote order={order} />
					{view.unreadable.length > 0 && (
						<ul className={styles.unreadable}>
							{view.unreadable.map((file) => (
								<li key={file}>
									{t("library.fileUnreadable", { path: file })}
								</li>
							))}
						</ul>
					)}
				</div>

				{shown && (
					<section className={detail.detail} aria-labelledby="track-title">
						<h3 id="track-title" className={detail.title}>
							{titleOf(shown)}
						</h3>
						<div className={detail.group}>
							<h4 className={detail.label}>{t("track.ownTags")}</h4>
							{genres.data && (
								<LibraryTags
									// A table's own state, the rows typed in by key, is one track's.
									key={shown.path}
									label={t("track.ownTagsOf", { title: titleOf(shown) })}
									addLabel={t("library.tagKeyOf", { title: titleOf(shown) })}
									tracks={[shown]}
									names={names}
									edits={draft.edits}
									genres={genres.data.genres}
									readOnly={readOnly}
									shows={(row) => !(shownIsSelected && albumRows.has(row.key))}
									onEdits={editEdits}
								/>
							)}
						</div>
						<div className={detail.group}>
							<h4 className={detail.label}>{t("file.title")}</h4>
							<FactsList
								facts={[
									{
										name: t("file.format"),
										value: `${describeEncoding(shown, t)} · ${t(
											shown.channels === 1 ? "file.channel" : "file.channels",
											{ n: shown.channels },
										)}`,
									},
									{ name: t("file.bitrate"), value: formatKbps(shown.bitrate) },
									{ name: t("file.length"), value: formatLength(shown.length) },
									{ name: t("file.size"), value: formatSize(shown.size) },
									{ name: t("file.path"), value: shown.path, path: true },
								]}
							/>
						</div>
					</section>
				)}
			</section>
		</section>
	);
}
