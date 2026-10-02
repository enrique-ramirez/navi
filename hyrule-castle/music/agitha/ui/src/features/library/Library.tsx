import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import { ChevronRight, Folder } from "lucide-react";
import { type ReactNode, useState } from "react";

import {
	libraryArtistQuery,
	libraryLetterQuery,
	libraryRootQuery,
} from "@/domain/library/libraryQuery";
import {
	isHere,
	type Place,
	type Shown,
	shownFor,
} from "@/domain/library/treeState";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Library.module.css";
import { LibraryAlbum } from "./LibraryAlbum";
import { LibraryArtist } from "./LibraryArtist";

export function Library() {
	const { t } = useTranslate();
	const params: Place = useParams({ strict: false });
	const navigate = useNavigate();
	const root = useQuery(libraryRootQuery());

	// A library that cannot be read has no folders to ask for.
	const readable = root.data?.readable === true;
	const url: Place = readable ? params : {};

	const letterQuery = useQuery(libraryLetterQuery(url.letter));
	const artistQuery = useQuery(libraryArtistQuery(url.letter, url.artist));

	const [shown, setShown] = useState<Shown>({});
	const next = shownFor(url, shown, {
		letter: letterQuery.isPending,
		artist: artistQuery.isPending,
	});
	if (next.letter !== shown.letter || next.artist !== shown.artist)
		setShown(next);

	const shownLetter = useQuery(libraryLetterQuery(shown.letter));
	const shownArtist = useQuery(libraryArtistQuery(shown.letter, shown.artist));

	if (root.isError && !root.data)
		return (
			<main className={styles.library}>
				<p role="alert">{t("library.failed")}</p>
			</main>
		);
	if (!root.data)
		return (
			<main className={styles.library}>
				<p>{t("library.loading")}</p>
			</main>
		);
	if (!root.data.readable)
		return (
			<main className={styles.library}>
				<p role="alert">{t("library.unreadable", { root: root.data.root })}</p>
			</main>
		);

	const go = ({ letter, artist, album }: Place) => {
		if (letter === undefined) return;
		if (artist === undefined)
			return navigate({ to: "/library/$letter", params: { letter } });
		if (album === undefined)
			return navigate({
				to: "/library/$letter/$artist",
				params: { letter, artist },
			});
		return navigate({
			to: "/library/$letter/$artist/$album",
			params: { letter, artist, album },
		});
	};

	return (
		<main className={styles.library}>
			{/* biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a tree is a list of treeitems. */}
			<ul role="tree" aria-label={t("library.tree")} className={styles.tree}>
				{root.data.letters.map((letter) => (
					<Item
						key={letter}
						name={letter}
						expanded={shown.letter === letter}
						current={isHere(url, letter)}
						busy={url.letter === letter && letterQuery.isPending}
						open={() => go({ letter })}
					>
						{shown.letter === letter && shownLetter.data && (
							<Group>
								{shownLetter.data.artists.map(({ name: artist }) => (
									<Item
										key={artist}
										name={artist}
										expanded={shown.artist === artist}
										current={isHere(url, letter, artist)}
										busy={url.artist === artist && artistQuery.isPending}
										open={() => go({ letter, artist })}
									>
										{shown.artist === artist && shownArtist.data && (
											<Albums
												albums={shownArtist.data.albums.map((a) => a.name)}
												url={url}
												letter={letter}
												artist={artist}
												go={go}
											/>
										)}
									</Item>
								))}
							</Group>
						)}
					</Item>
				))}
			</ul>
			<div className={styles.pane}>
				<Pane
					place={url}
					// A failed refetch leaves what the page holds on show: a draft lives in the page.
					failed={
						url.artist !== undefined
							? artistQuery.isError && !artistQuery.data
							: letterQuery.isError && !letterQuery.data
					}
					empty={
						url.artist !== undefined
							? artistQuery.data?.albums.length === 0
							: letterQuery.data?.artists.length === 0
					}
				/>
			</div>
		</main>
	);
}

interface ItemProps {
	name: string;
	/** Left out on an album, which has nothing to open. */
	expanded?: boolean;
	current: boolean;
	busy?: boolean;
	open: () => void;
	children?: ReactNode;
}

// The item itself takes the click and the key, so the whole row is the target;
// a nested item stops the event before it reaches the folder around it.
function Item({ name, expanded, current, busy, open, children }: ItemProps) {
	const { t } = useTranslate();
	return (
		<li
			role="treeitem"
			// The label keeps the nested folders' names out of this item's own.
			aria-label={t("library.folder", { name })}
			aria-expanded={expanded}
			aria-current={current ? "page" : undefined}
			aria-busy={busy ? true : undefined}
			tabIndex={0}
			className={styles.item}
			onClick={(event) => {
				event.stopPropagation();
				open();
			}}
			onKeyDown={(event) => {
				if (event.target !== event.currentTarget) return;
				if (event.key !== "Enter" && event.key !== " ") return;
				event.preventDefault();
				open();
			}}
		>
			<span className={styles.row}>
				{expanded === undefined ? null : (
					<ChevronRight
						size={14}
						aria-hidden="true"
						className={styles.chevron}
					/>
				)}
				<Folder size={14} aria-hidden="true" />
				<span>{name}</span>
			</span>
			{children}
		</li>
	);
}

function Group({ children }: { children: ReactNode }) {
	return (
		// biome-ignore lint/a11y/useSemanticElements: a fieldset is not a list of treeitems.
		<ul role="group" className={styles.group}>
			{children}
		</ul>
	);
}

function Albums({
	albums,
	url,
	letter,
	artist,
	go,
}: {
	albums: string[];
	url: Place;
	letter: string;
	artist: string;
	go: (place: Place) => void;
}) {
	return (
		<Group>
			{albums.map((album) => (
				<Item
					key={album}
					name={album}
					current={isHere(url, letter, artist, album)}
					open={() => go({ letter, artist, album })}
				/>
			))}
		</Group>
	);
}

function Pane({
	place,
	failed,
	empty,
}: {
	place: Place;
	failed: boolean;
	empty: boolean;
}) {
	const { t } = useTranslate();
	if (place.letter === undefined) return null;
	if (failed) return <p role="alert">{t("library.failed")}</p>;
	if (empty) return <p>{t("library.empty")}</p>;
	if (place.album !== undefined && place.artist !== undefined)
		return (
			<LibraryAlbum
				key={[place.letter, place.artist, place.album].join("/")}
				letter={place.letter}
				artist={place.artist}
				album={place.album}
			/>
		);
	if (place.artist !== undefined)
		return (
			<LibraryArtist
				key={[place.letter, place.artist].join("/")}
				letter={place.letter}
				artist={place.artist}
			/>
		);
	return null;
}
