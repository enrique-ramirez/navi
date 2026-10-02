import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";

import {
	genresQuery,
	isSaving,
	libraryAlbumKey,
	libraryAlbumQuery,
	libraryArtistQuery,
	libraryOrderQuery,
} from "@/domain/library/libraryQuery";
import type { PanelTrack } from "@/domain/library/shared";
import { postMatch, Refused } from "@/shared/api/library";
import type { LibraryJob, TrackRef } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { isEmpty, toWire, withSwap } from "./draft";
import { FlowNotices } from "./FlowNotices";
import styles from "./LibraryAlbum.module.css";
import { LibraryCover } from "./LibraryCover";
import { Panel } from "./Panel";
import { ReviewChanges } from "./ReviewChanges";
import { SaveProgress } from "./SaveProgress";
import { OrderNote } from "./TrackOrder";
import { lastSegment, TrackTable, tagOf } from "./TrackTable";
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
	const path = [letter, artist, album].join("/");
	const albumKey = libraryAlbumKey(letter, artist, album);

	const albumQuery = useQuery(libraryAlbumQuery(letter, artist, album));
	const genres = useQuery(genresQuery());
	const order = useQuery(
		libraryOrderQuery(letter, artist, album, albumQuery.data !== undefined),
	);
	const [unselected, setUnselected] = useState<string[]>([]);

	const view = albumQuery.data;
	const names = view?.names;

	const ofThisAlbum = (job: LibraryJob | undefined) =>
		job?.albums.find((each) => each.path === path);

	// Bumped by a done save that carried a cover: the album is then served at the same cover URL.
	const [coverVersion, setCoverVersion] = useState(0);
	const savedCover = useRef(false);

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

	if (albumQuery.isError && !view)
		return <p role="alert">{t("library.failed")}</p>;
	if (!view || !names) return <p>{t("page.loading")}</p>;

	const selected: TrackRef[] = tracks
		.filter((track) => !unselected.includes(track.path))
		.map(({ album: from, path: file }) => ({ album: from, path: file }));

	const first = tracks[0];
	const title = (first && tagOf(first, "Album", names)[0]) || lastSegment(path);
	const answer = flow.preview?.albums[0];
	// An album with a match open is the review's to change until the match lands.
	const readOnly = flow.readOnly || view.match !== null;

	function reload() {
		flow.discard();
		void queryClient.invalidateQueries({ queryKey: albumKey, exact: true });
	}

	return (
		<section className={styles.album}>
			<h2 className={styles.title}>{title}</h2>

			<LibraryCover
				current={view.cover}
				cover={draft.cover}
				version={coverVersion}
				title={title}
				readOnly={readOnly}
				onCover={(cover) => flow.changeDraft((now) => ({ ...now, cover }))}
			/>

			{view.match && (
				<p>
					{t("library.openInReview")}{" "}
					<Link
						to="/drops/$drop/albums/$n"
						params={{ drop: view.match.drop, n: view.match.n }}
					>
						{t("library.openReview")}
					</Link>
				</p>
			)}

			<TrackTable
				tracks={tracks}
				names={names}
				unselected={unselected}
				readOnly={readOnly}
				flags={order.data?.checked ? order.data.flags : []}
				swaps={draft.swaps}
				onSwap={(pair) => flow.changeDraft((now) => withSwap(now, pair))}
				onToggle={(file) =>
					setUnselected((now) =>
						now.includes(file)
							? now.filter((each) => each !== file)
							: [...now, file],
					)
				}
				onToggleAll={() =>
					setUnselected(
						selected.length === tracks.length
							? tracks.map((track) => track.path)
							: [],
					)
				}
			/>

			<OrderNote order={order} />

			{view.unreadable.length > 0 && (
				<ul className={styles.unreadable}>
					{view.unreadable.map((file) => (
						<li key={file}>{t("library.fileUnreadable", { path: file })}</li>
					))}
				</ul>
			)}

			{state !== null && isSaving(state) && <SaveProgress state={state} />}

			{genres.data && (
				<Panel
					readOnly={readOnly}
					tracks={tracks}
					selected={selected}
					names={names}
					edits={draft.edits}
					genres={genres.data.genres}
					onEdit={(edit) =>
						flow.changeDraft((now) => ({ ...now, edits: [...now.edits, edit] }))
					}
				/>
			)}

			<div className={styles.actions}>
				<button
					type="button"
					disabled={readOnly || isEmpty(draft) || flow.previewPending}
					onClick={() => flow.review(toWire(draft, tracks, names, false))}
				>
					{t("library.review")}
				</button>
				{!readOnly && selected.length === 2 && (
					<button
						type="button"
						onClick={() =>
							flow.changeDraft((now) =>
								withSwap(now, [
									selected[0]?.path ?? "",
									selected[1]?.path ?? "",
								]),
							)
						}
					>
						{t("library.swap")}
					</button>
				)}
				<button
					type="button"
					disabled={readOnly || isEmpty(draft)}
					onClick={flow.discard}
				>
					{t("library.discard")}
				</button>
				<button
					type="button"
					disabled={readOnly || !isEmpty(draft) || matching.isPending}
					onClick={() => matching.mutate(view.path)}
				>
					{t("library.match")}
				</button>
			</div>

			{!readOnly && answer && (
				<ReviewChanges
					preview={answer}
					was={view.cover}
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
		</section>
	);
}
