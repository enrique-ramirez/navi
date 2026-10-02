import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { formatLength } from "@/domain/album/format";
import { genresQuery, libraryArtistQuery } from "@/domain/library/libraryQuery";
import type { PanelTrack } from "@/domain/library/shared";
import type { JobAlbum, TrackRef } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { BatchPreview, BatchProgress } from "./BatchPreview";
import { isEmpty, toWire } from "./draft";
import { FlowNotices } from "./FlowNotices";
import styles from "./LibraryArtist.module.css";
import { Panel } from "./Panel";
import { lastSegment, tagOf } from "./TrackTable";
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

// Two albums may hold a file of one name, so a track is told by both.
const keyOf = (track: TrackRef) => `${track.album}\n${track.path}`;

const ended = (album: JobAlbum) =>
	album.state === "done" || album.state === "failed";

export function LibraryArtist({
	letter,
	artist,
}: {
	letter: string;
	artist: string;
}) {
	const { t } = useTranslate();
	const queryClient = useQueryClient();
	const artistQuery = useQuery(libraryArtistQuery(letter, artist));
	const genres = useQuery(genresQuery());
	const [selected, setSelected] = useState<string[]>([]);
	const [open, setOpen] = useState<string[]>([]);

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
	if (!view) return <p>{t("page.loading")}</p>;

	const refs = tracks
		.filter((track) => selected.includes(keyOf(track)))
		.map(({ album, path }) => ({ album, path }));
	const titleOfAlbum = (path: string) =>
		view.albums.find((each) => each.path === path)?.title ?? lastSegment(path);

	function setMany(keys: string[], on: boolean) {
		setSelected((now) => [
			...now.filter((key) => !keys.includes(key)),
			...(on ? keys : []),
		]);
	}

	const everyKey = tracks.map(keyOf);
	const progress =
		flow.outcome ?? (readOnly && flow.job !== undefined ? flow.job : null);

	return (
		<section className={styles.artist}>
			<h2 className={styles.title}>{artist}</h2>

			<label className={styles.all}>
				<input
					type="checkbox"
					aria-label={t("library.selectAll")}
					checked={everyKey.length > 0 && selected.length === everyKey.length}
					disabled={readOnly}
					onChange={(event) => setMany(everyKey, event.target.checked)}
				/>
			</label>

			<ul className={styles.albums}>
				{view.albums.map((album) => {
					const keys = album.tracks.map((track) =>
						keyOf({ album: album.path, path: track.path }),
					);
					const chosen = keys.filter((key) => selected.includes(key)).length;
					const isOpen = open.includes(album.path);
					const [, , folder = ""] = album.path.split("/");
					return (
						<li key={album.path} className={styles.album}>
							<div className={styles.head}>
								<input
									type="checkbox"
									aria-label={t("library.select", { title: album.title })}
									checked={keys.length > 0 && chosen === keys.length}
									ref={(box) => {
										if (box)
											box.indeterminate = chosen > 0 && chosen < keys.length;
									}}
									disabled={readOnly}
									onChange={(event) => setMany(keys, event.target.checked)}
								/>
								{album.cover_url && (
									<img
										src={album.cover_url}
										alt={t("album.cover", { title: album.title })}
										className={styles.cover}
									/>
								)}
								<span className={styles.year}>{album.year}</span>
								<Link
									to="/library/$letter/$artist/$album"
									params={{ letter, artist, album: folder }}
								>
									{album.title}
								</Link>
								<button
									type="button"
									className={styles.open}
									aria-expanded={isOpen}
									onClick={() =>
										setOpen((now) =>
											isOpen
												? now.filter((each) => each !== album.path)
												: [...now, album.path],
										)
									}
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
									{album.tracks.map((track) => {
										const name =
											tagOf(
												{ ...track, album: album.path },
												"Title",
												view.names,
											)[0] || lastSegment(track.path);
										const key = keyOf({ album: album.path, path: track.path });
										return (
											<li key={track.path}>
												<input
													type="checkbox"
													aria-label={t("library.select", { title: name })}
													checked={selected.includes(key)}
													disabled={readOnly}
													onChange={(event) =>
														setMany([key], event.target.checked)
													}
												/>{" "}
												<span>{name}</span>{" "}
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
				})}
			</ul>

			{progress && (
				<BatchProgress albums={progress.albums} titleOf={titleOfAlbum} />
			)}

			{genres.data && (
				<Panel
					readOnly={readOnly}
					tracks={tracks}
					selected={refs}
					names={view.names}
					edits={draft.edits}
					genres={genres.data.genres}
					locked={LOCKED}
					onEdit={(edit) =>
						flow.changeDraft((now) => ({ ...now, edits: [...now.edits, edit] }))
					}
				/>
			)}

			<div className={styles.actions}>
				<button
					type="button"
					disabled={readOnly || isEmpty(draft) || flow.previewPending}
					onClick={() => flow.review(toWire(draft, tracks, view.names, true))}
				>
					{t("library.review")}
				</button>
				<button
					type="button"
					disabled={readOnly || isEmpty(draft)}
					onClick={flow.discard}
				>
					{t("library.discard")}
				</button>
			</div>

			{!readOnly && flow.preview && (
				<BatchPreview
					preview={flow.preview}
					titleOf={titleOfAlbum}
					onApply={() => flow.save(toWire(draft, tracks, view.names, true))}
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
		</section>
	);
}
