import type { AlbumView } from "@/shared/api/types";
import { useTranslate } from "@/shared/i18n/useTranslate";
import styles from "./Landing.module.css";

interface Folder {
	name: string;
	// `null` for a file; a folder holds its children in the order they first appeared.
	children: Folder[] | null;
}

// Files of one folder gather under one item, wherever they sit in the list; every level keeps the given order.
function nest(paths: string[]): Folder[] {
	const root: Folder[] = [];
	for (const path of paths) {
		const parts = path.split("/");
		let level = root;
		parts.forEach((name, index) => {
			const isFile = index === parts.length - 1;
			let node = level.find((each) => each.name === name);
			if (!node) {
				node = { name, children: isFile ? null : [] };
				level.push(node);
			}
			if (node.children) level = node.children;
		});
	}
	return root;
}

function Tree({ nodes, label }: { nodes: Folder[]; label: string }) {
	return (
		<ul className={styles.tree} aria-label={label}>
			{nodes.map((node) => (
				<li key={node.name}>
					<span>{node.name}</span>
					{node.children && <Tree nodes={node.children} label={node.name} />}
				</li>
			))}
		</ul>
	);
}

export function Landing({ view }: { view: AlbumView }) {
	const { t } = useTranslate();
	const preview = view.preview;

	return (
		<section className={styles.landing} aria-labelledby="landing-title">
			<h2 id="landing-title">{t("landing.title")}</h2>
			{preview === null ? (
				<p>{t("landing.noPreview")}</p>
			) : (
				<>
					<h3>{t("landing.library")}</h3>
					{view.library_path ? (
						<p className={styles.path}>{view.library_path}</p>
					) : (
						<p>{t("landing.noDestination")}</p>
					)}

					<h3>{t("landing.folder")}</h3>
					<Tree nodes={nest(view.tree)} label={t("landing.folder")} />

					<h3>{t("landing.deleted")}</h3>
					{preview.deletions.length === 0 ? (
						<p>{t("landing.none")}</p>
					) : (
						<ul className={styles.plain} aria-label={t("landing.deleted")}>
							{preview.deletions.map((path) => (
								<li key={path}>{path}</li>
							))}
						</ul>
					)}

					<h3>{t("landing.extras")}</h3>
					{view.extras_to.length === 0 ? (
						<p>{t("landing.none")}</p>
					) : (
						<ul className={styles.plain} aria-label={t("landing.extras")}>
							{view.extras_to.map((extra) => (
								<li key={extra.source}>
									<span>{extra.source}</span>{" "}
									<span className={styles.muted}>{t("landing.goesTo")}</span>{" "}
									<span className={styles.path}>{extra.path}</span>
								</li>
							))}
						</ul>
					)}

					<dl className={styles.facts}>
						<dt>{t("landing.status")}</dt>
						<dd>{t(`status.${preview.status}`)}</dd>
						<dt>{t("landing.state")}</dt>
						<dd>{t(`planState.${preview.state}`)}</dd>
					</dl>

					<h3>{t("landing.holds")}</h3>
					{preview.holds.length === 0 ? (
						<p>{t("landing.noHolds")}</p>
					) : (
						<ul className={styles.plain} aria-label={t("landing.holds")}>
							{preview.holds.map((hold) => (
								<li key={`${hold.kind}: ${hold.detail}`}>
									{hold.detail
										? `${t(`hold.${hold.kind}`)}: ${hold.detail}`
										: t(`hold.${hold.kind}`)}
								</li>
							))}
						</ul>
					)}
				</>
			)}
		</section>
	);
}
