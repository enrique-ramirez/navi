import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import {
	ChevronRight,
	Disc3,
	Folder,
	FolderOpen,
	LibraryBig,
	Trash2,
} from "lucide-react";
import {
	type KeyboardEvent,
	type ReactNode,
	useEffect,
	useRef,
	useState,
} from "react";

import {
	libraryArtistQuery,
	libraryLetterQuery,
	libraryRootQuery,
} from "@/domain/library/libraryQuery";
import {
	ancestorsOf,
	isHere,
	type Place,
	pathOf,
} from "@/domain/library/treeState";
import { deleteLibraryFolder, Refused } from "@/shared/api/library";
import { useTranslate } from "@/shared/i18n/useTranslate";
import { Alert } from "@/shared/ui/Alert";
import { Confirm } from "@/shared/ui/Confirm";
import styles from "./Library.module.css";
import { LibraryAlbum } from "./LibraryAlbum";
import { LibraryArtist } from "./LibraryArtist";

/** What every folder of the tree needs from the page around it. */
interface Tree {
	url: Place;
	/** The folders open, by path: `S` and `S/Sonata Arctica`. */
	open: ReadonlySet<string>;
	/** The one item Tab reaches; the arrows move from it. */
	tabStop: string;
	go: (place: Place) => void;
	toggle: (path: string) => void;
	focused: (path: string) => void;
	remove: (parts: string[]) => void;
}

export function Library() {
	const { t } = useTranslate();
	const params: Place = useParams({ strict: false });
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const root = useQuery(libraryRootQuery());

	// A library that cannot be read has no folders to ask for.
	const readable = root.data?.readable === true;
	const url: Place = readable ? params : {};
	const address = pathOf(url);

	const letterQuery = useQuery(libraryLetterQuery(url.letter));
	const artistQuery = useQuery(libraryArtistQuery(url.letter, url.artist));

	// The tree opens to wherever the address goes, and from there the folders open and close by hand.
	const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
	const [followed, setFollowed] = useState<string | null>(null);
	if (followed !== address) {
		setFollowed(address);
		setOpen(new Set([...open, ...ancestorsOf(url)]));
	}

	const [focusedPath, setFocusedPath] = useState<string | null>(null);
	const [removing, setRemoving] = useState<string[] | null>(null);

	const sidebar = useRef<HTMLDivElement>(null);
	// biome-ignore lint/correctness/useExhaustiveDependencies: the address is what moves the current item.
	useEffect(() => {
		sidebar.current
			?.querySelector('[aria-current="page"] > span')
			?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
	}, [address, letterQuery.data, artistQuery.data]);

	const go = ({ letter, artist, album }: Place) => {
		if (letter === undefined) return navigate({ to: "/library" });
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

	const removal = useMutation({
		mutationFn: deleteLibraryFolder,
		onSuccess: async ({ removed }) => {
			const gone = (path: string) =>
				removed.some((each) => path === each || path.startsWith(`${each}/`));
			setOpen((now) => new Set([...now].filter((path) => !gone(path))));
			// The address may name a folder that is gone: leave for the nearest one still there.
			if (gone(address)) {
				const [letter, artist] = address.split("/");
				const left: Place = {};
				if (letter !== undefined && !gone(letter)) {
					left.letter = letter;
					if (artist !== undefined && !gone(`${letter}/${artist}`))
						left.artist = artist;
				}
				await go(left);
			}
			await queryClient.invalidateQueries({ queryKey: ["library"] });
		},
	});

	if (root.isError && !root.data)
		return (
			<main className={styles.message}>
				<p role="alert">{t("library.failed")}</p>
			</main>
		);
	if (!root.data)
		return (
			<main className={styles.message}>
				<p>{t("library.loading")}</p>
			</main>
		);
	if (!root.data.readable)
		return (
			<main className={styles.message}>
				<p role="alert">{t("library.unreadable", { root: root.data.root })}</p>
			</main>
		);

	const tree: Tree = {
		url,
		open,
		tabStop: focusedPath ?? (address || (root.data.letters[0] ?? "")),
		go,
		toggle: (path) => {
			const closing = open.has(path);
			setOpen(
				new Set(
					closing ? [...open].filter((each) => each !== path) : [...open, path],
				),
			);
			// Tab must still land in the tree once the item it stopped on is folded away.
			if (closing && focusedPath?.startsWith(`${path}/`)) setFocusedPath(path);
		},
		focused: setFocusedPath,
		remove: (parts) => {
			removal.reset();
			setRemoving(parts);
		},
	};

	function onKeyDown(event: KeyboardEvent<HTMLUListElement>) {
		const item = event.target as HTMLElement;
		if (item.getAttribute("role") !== "treeitem") return;
		const items = [
			...event.currentTarget.querySelectorAll<HTMLElement>('[role="treeitem"]'),
		];
		const at = items.indexOf(item);
		const expanded = item.getAttribute("aria-expanded");
		const path = item.dataset.path ?? "";
		switch (event.key) {
			case "ArrowDown":
				items[at + 1]?.focus();
				break;
			case "ArrowUp":
				items[at - 1]?.focus();
				break;
			case "Home":
				items[0]?.focus();
				break;
			case "End":
				items.at(-1)?.focus();
				break;
			case "ArrowRight":
				if (expanded === "false") tree.toggle(path);
				else if (expanded === "true") items[at + 1]?.focus();
				break;
			case "ArrowLeft":
				if (expanded === "true") tree.toggle(path);
				else
					item.parentElement
						?.closest<HTMLElement>('[role="treeitem"]')
						?.focus();
				break;
			case "Enter":
			case " ":
				item.click();
				break;
			case "Delete":
				if (item.dataset.empty === undefined) return;
				tree.remove(path.split("/"));
				break;
			default:
				return;
		}
		event.preventDefault();
	}

	return (
		<main className={styles.library}>
			<div ref={sidebar} className={styles.sidebar}>
				<ul
					// biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: a tree is a list of treeitems.
					role="tree"
					aria-label={t("library.tree")}
					className={styles.tree}
					onKeyDown={onKeyDown}
				>
					{root.data.letters.map((letter) => (
						<LetterNode key={letter} letter={letter} tree={tree} />
					))}
				</ul>
				{removal.isError && (
					<Alert>
						{removal.error instanceof Refused && removal.error.sentence
							? removal.error.sentence
							: t("library.removeFailed")}
					</Alert>
				)}
			</div>
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

			{removing && (
				<Confirm
					message={t("library.removeConfirm", { path: removing.join("/") })}
					confirmLabel={t("library.remove")}
					onCancel={() => setRemoving(null)}
					onConfirm={() => {
						removal.mutate(removing);
						setRemoving(null);
					}}
				/>
			)}
		</main>
	);
}

function LetterNode({ letter, tree }: { letter: string; tree: Tree }) {
	const expanded = tree.open.has(letter);
	const query = useQuery(libraryLetterQuery(expanded ? letter : undefined));
	return (
		<Item
			path={letter}
			name={letter}
			tree={tree}
			place={{ letter }}
			expanded={expanded}
			busy={expanded && query.isPending}
		>
			{expanded && query.data && (
				<Group>
					{query.data.artists.map(({ name: artist, empty }) => (
						<ArtistNode
							key={artist}
							letter={letter}
							artist={artist}
							empty={empty}
							tree={tree}
						/>
					))}
				</Group>
			)}
		</Item>
	);
}

function ArtistNode({
	letter,
	artist,
	empty,
	tree,
}: {
	letter: string;
	artist: string;
	empty: boolean;
	tree: Tree;
}) {
	const path = `${letter}/${artist}`;
	const expanded = tree.open.has(path);
	const query = useQuery(
		libraryArtistQuery(
			expanded ? letter : undefined,
			expanded ? artist : undefined,
		),
	);
	return (
		<Item
			path={path}
			name={artist}
			tree={tree}
			place={{ letter, artist }}
			expanded={expanded}
			busy={expanded && query.isPending}
			empty={empty}
		>
			{expanded && query.data && query.data.albums.length > 0 && (
				<Group>
					{query.data.albums.map((album) => (
						<Item
							key={album.name}
							path={`${path}/${album.name}`}
							name={album.name}
							tree={tree}
							place={{ letter, artist, album: album.name }}
							empty={album.empty}
						/>
					))}
				</Group>
			)}
		</Item>
	);
}

interface ItemProps {
	/** Library-relative, which is also what tells the items apart. */
	path: string;
	name: string;
	tree: Tree;
	place: Place;
	/** Left out on an album, which has nothing to open. */
	expanded?: boolean;
	busy?: boolean;
	/** The folder holds nothing, so it may be removed. */
	empty?: boolean;
	children?: ReactNode;
}

// The item itself takes the click and the key, so the whole row is the target;
// a nested item stops the event before it reaches the folder around it.
function Item({
	path,
	name,
	tree,
	place,
	expanded,
	busy,
	empty,
	children,
}: ItemProps) {
	const { t } = useTranslate();
	const parts = path.split("/");
	const current = isHere(tree.url, ...parts);
	const Icon = expanded === undefined ? Disc3 : expanded ? FolderOpen : Folder;
	return (
		// biome-ignore lint/a11y/useKeyWithClickEvents: the tree takes the keys of every item, and Enter clicks the one focused.
		<li
			role="treeitem"
			// The label keeps the nested folders' names out of this item's own.
			aria-label={t("library.folder", { name })}
			aria-expanded={expanded}
			aria-current={current ? "page" : undefined}
			aria-busy={busy ? true : undefined}
			tabIndex={tree.tabStop === path ? 0 : -1}
			data-path={path}
			data-empty={empty || undefined}
			className={styles.item}
			onFocus={(event) => {
				if (event.target === event.currentTarget) tree.focused(path);
			}}
			onClick={(event) => {
				event.stopPropagation();
				// A click on the folder the page is at folds or unfolds it; on any other it goes there, which opens it.
				if (current && expanded !== undefined) tree.toggle(path);
				else tree.go(place);
			}}
		>
			<span className={styles.row} title={name}>
				{expanded === undefined ? (
					<span className={styles.chevron} />
				) : (
					// A pointer's shortcut; the arrow keys fold and unfold the item.
					<span
						className={styles.chevron}
						aria-hidden="true"
						onClick={(event) => {
							event.stopPropagation();
							tree.toggle(path);
						}}
					>
						<ChevronRight size={14} />
					</span>
				)}
				<Icon size={15} aria-hidden="true" className={styles.icon} />
				<span className={styles.name}>{name}</span>
				{empty && (
					<button
						type="button"
						// Delete on the item is the keyboard's way to it.
						tabIndex={-1}
						className={styles.remove}
						aria-label={t("library.removeFolder", { name })}
						title={t("library.removeFolder", { name })}
						onClick={(event) => {
							event.stopPropagation();
							tree.remove(parts);
						}}
					>
						<Trash2 size={14} aria-hidden="true" />
					</button>
				)}
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
	if (failed)
		return (
			<div className={styles.blank}>
				<p role="alert">{t("library.failed")}</p>
			</div>
		);
	if (place.letter !== undefined && empty)
		return (
			<div className={styles.blank}>
				<Folder size={40} aria-hidden="true" />
				<p className={styles.blankTitle}>{t("library.empty")}</p>
			</div>
		);
	if (
		place.letter !== undefined &&
		place.album !== undefined &&
		place.artist !== undefined
	)
		return (
			<LibraryAlbum
				key={[place.letter, place.artist, place.album].join("/")}
				letter={place.letter}
				artist={place.artist}
				album={place.album}
			/>
		);
	if (place.letter !== undefined && place.artist !== undefined)
		return (
			<LibraryArtist
				key={[place.letter, place.artist].join("/")}
				letter={place.letter}
				artist={place.artist}
			/>
		);
	return (
		<div className={styles.blank}>
			<LibraryBig size={40} aria-hidden="true" />
			<p className={styles.blankTitle}>{t("library.pick")}</p>
			<p>{t("library.pickHint")}</p>
		</div>
	);
}
